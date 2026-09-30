import shutil
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import (
    BackfillHistoricalCandlesUseCase,
    BootstrapDatabasesUseCase,
    HistoricalBackfillService,
    JobStatus,
)
from trading_system.config import Settings
from trading_system.domain import Candle1m, IngestionStatus, Instrument, Universe
from trading_system.infrastructure import ThreadJobManager


class FakeMarketDataClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, datetime, datetime]] = []

    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[Candle1m, ...]:
        self.calls.append((instrument_uid, from_ts, to_ts))
        return (
            Candle1m(
                instrument_uid=instrument_uid,
                ts=from_ts,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=10,
            ),
        )


class SlowFakeMarketDataClient(FakeMarketDataClient):
    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[Candle1m, ...]:
        time.sleep(0.03)
        return super().get_candles(instrument_uid, from_ts, to_ts)


def _bootstrap(tmp_path: Path) -> DuckDBMarketRepository:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)
    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )
    BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    repository = DuckDBMarketRepository(settings.market_db_path)
    instruments = (
        Instrument("uid-a", "AAA", 1),
        Instrument("uid-b", "BBB", 1),
    )
    repository.sync_universe(
        Universe(
            universe_id="default",
            name="Default",
            instrument_uids=("uid-a", "uid-b"),
        ),
        instruments,
    )
    return repository


def test_backfill_fetches_all_chunks_and_persists_candles(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    market_data = FakeMarketDataClient()
    use_case = BackfillHistoricalCandlesUseCase(market_data, repository)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=2, hours=6)

    result = use_case.execute("default", from_ts=start, to_ts=end)

    assert result.total_requests == 6
    assert result.total_fetched_candles == 6
    assert len(market_data.calls) == 6
    assert repository.get_candle_stats("uid-a").row_count == 3
    assert repository.get_candle_stats("uid-b").row_count == 3


def test_backfill_default_range_is_five_calendar_years(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    market_data = FakeMarketDataClient()
    now = datetime(2028, 2, 29, 12, 34, 56, tzinfo=UTC)
    use_case = BackfillHistoricalCandlesUseCase(
        market_data,
        repository,
        now_provider=lambda: now,
    )

    from_ts, to_ts = use_case.default_range()

    assert to_ts == datetime(2028, 2, 29, 12, 34, tzinfo=UTC)
    assert from_ts == datetime(2023, 2, 28, 12, 34, tzinfo=UTC)


def test_background_backfill_reports_progress_and_completes(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    market_data = FakeMarketDataClient()
    manager = ThreadJobManager(max_workers=1)
    service = HistoricalBackfillService(
        manager,
        BackfillHistoricalCandlesUseCase(market_data, repository),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)

    try:
        job_id = service.start(
            "default",
            from_ts=start,
            to_ts=start + timedelta(days=2),
        )
        deadline = time.time() + 5
        snapshot = manager.get(job_id)
        while not snapshot.status.terminal and time.time() < deadline:
            time.sleep(0.01)
            snapshot = manager.get(job_id)

        assert snapshot.status is JobStatus.COMPLETED
        assert snapshot.progress == 1.0
        assert snapshot.error is None
    finally:
        manager.shutdown(wait=True, cancel_running=True)


def test_background_backfill_can_be_cancelled(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    market_data = SlowFakeMarketDataClient()
    manager = ThreadJobManager(max_workers=1)
    service = HistoricalBackfillService(
        manager,
        BackfillHistoricalCandlesUseCase(market_data, repository),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)

    try:
        job_id = service.start(
            "default",
            from_ts=start,
            to_ts=start + timedelta(days=10),
        )
        deadline = time.time() + 5
        while manager.get(job_id).status is JobStatus.PENDING and time.time() < deadline:
            time.sleep(0.01)
        assert manager.cancel(job_id) is True

        snapshot = manager.get(job_id)
        while not snapshot.status.terminal and time.time() < deadline:
            time.sleep(0.01)
            snapshot = manager.get(job_id)

        assert snapshot.status is JobStatus.CANCELLED
        assert len(market_data.calls) < 20
    finally:
        manager.shutdown(wait=True, cancel_running=True)


class FailOnceMarketDataClient(FakeMarketDataClient):
    def __init__(self, fail_on_call: int) -> None:
        super().__init__()
        self._fail_on_call = fail_on_call

    def get_candles(
        self,
        instrument_uid: str,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[Candle1m, ...]:
        next_call = len(self.calls) + 1
        if next_call == self._fail_on_call:
            self.calls.append((instrument_uid, from_ts, to_ts))
            raise RuntimeError("temporary broker failure")
        return super().get_candles(instrument_uid, from_ts, to_ts)


def test_backfill_resume_continues_from_last_completed_chunk(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=3)
    failing_client = FailOnceMarketDataClient(fail_on_call=2)
    use_case = BackfillHistoricalCandlesUseCase(failing_client, repository)

    try:
        use_case.execute("default", from_ts=start, to_ts=end)
    except RuntimeError as exc:
        assert "temporary broker failure" in str(exc)
    else:
        raise AssertionError("initial backfill must fail")

    checkpoint = repository.get_ingestion_checkpoint("uid-a", "1m")
    assert checkpoint is not None
    assert checkpoint.status is IngestionStatus.FAILED
    assert checkpoint.completed_until == start + timedelta(days=1)
    assert checkpoint.last_error == "RuntimeError: temporary broker failure"

    resumed_client = FakeMarketDataClient()
    resumed = BackfillHistoricalCandlesUseCase(resumed_client, repository)
    result = resumed.execute("default", resume=True)

    uid_a_calls = [call for call in resumed_client.calls if call[0] == "uid-a"]
    uid_b_calls = [call for call in resumed_client.calls if call[0] == "uid-b"]
    assert uid_a_calls == [
        ("uid-a", start + timedelta(days=1), start + timedelta(days=2)),
        ("uid-a", start + timedelta(days=2), end),
    ]
    assert len(uid_b_calls) == 3
    assert result.total_requests == 5

    checkpoint = repository.get_ingestion_checkpoint("uid-a", "1m")
    assert checkpoint is not None
    assert checkpoint.status is IngestionStatus.COMPLETED
    assert checkpoint.completed_until == end
    assert checkpoint.last_error is None


def test_resume_skips_completed_instrument(tmp_path: Path) -> None:
    repository = _bootstrap(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=2)
    initial_client = FakeMarketDataClient()
    use_case = BackfillHistoricalCandlesUseCase(initial_client, repository)
    use_case.execute("default", from_ts=start, to_ts=end)

    resumed_client = FakeMarketDataClient()
    result = BackfillHistoricalCandlesUseCase(
        resumed_client,
        repository,
    ).execute("default", resume=True)

    assert resumed_client.calls == []
    assert result.total_requests == 0
    assert all(
        repository.get_ingestion_checkpoint(uid, "1m").status
        is IngestionStatus.COMPLETED
        for uid in ("uid-a", "uid-b")
    )
