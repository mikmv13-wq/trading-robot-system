import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import BootstrapDatabasesUseCase
from trading_system.config import Settings
from trading_system.domain import Candle1m, CandleDataStats, Instrument, Universe


def _bootstrap(tmp_path: Path) -> Settings:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)

    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )
    BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    return settings


def test_market_repository_round_trip(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)

    instrument = Instrument(
        instrument_uid="uid-sber",
        ticker="SBER",
        lot_size=10,
        name="Sberbank",
        currency="rub",
        figi="BBG004730N88",
        exchange="MOEX",
        instrument_type="share",
    )
    repository.upsert_instrument(instrument)
    repository.replace_universe(
        Universe(
            universe_id="default",
            name="Default universe",
            instrument_uids=(instrument.instrument_uid,),
        )
    )

    candle = Candle1m(
        instrument_uid=instrument.instrument_uid,
        ts=datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        open=Decimal("300.100000000"),
        high=Decimal("301.200000000"),
        low=Decimal("299.900000000"),
        close=Decimal("300.800000000"),
        volume=12345,
    )
    repository.insert_candle(candle)

    assert repository.get_instrument(instrument.instrument_uid) == instrument
    assert repository.list_instruments() == (instrument,)
    assert repository.get_universe("default") == Universe(
        universe_id="default",
        name="Default universe",
        instrument_uids=(instrument.instrument_uid,),
    )
    assert repository.list_candles(instrument.instrument_uid) == (candle,)


def test_instrument_upsert_preserves_universe_membership(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)

    repository.upsert_instrument(
        Instrument(instrument_uid="uid", ticker="OLD", lot_size=1)
    )
    repository.replace_universe(
        Universe(universe_id="default", name="Default", instrument_uids=("uid",))
    )

    repository.upsert_instrument(
        Instrument(instrument_uid="uid", ticker="NEW", lot_size=10)
    )

    assert repository.get_instrument("uid") == Instrument(
        instrument_uid="uid",
        ticker="NEW",
        lot_size=10,
    )
    assert repository.get_universe("default") == Universe(
        universe_id="default",
        name="Default",
        instrument_uids=("uid",),
    )


def _instrument(uid: str = "uid-sber") -> Instrument:
    return Instrument(instrument_uid=uid, ticker="SBER", lot_size=10)


def _candle_at(
    minute: int,
    *,
    uid: str = "uid-sber",
    close: str = "300.800000000",
    volume: int = 12345,
    is_complete: bool = True,
) -> Candle1m:
    return Candle1m(
        instrument_uid=uid,
        ts=datetime(2026, 1, 5, 7, minute, tzinfo=UTC),
        open=Decimal("300.100000000"),
        high=Decimal("301.200000000"),
        low=Decimal("299.900000000"),
        close=Decimal(close),
        volume=volume,
        is_complete=is_complete,
    )


def test_candle_batch_upsert_is_idempotent(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.upsert_instrument(_instrument())

    candles = (_candle_at(0), _candle_at(1), _candle_at(2))

    repository.upsert_candles(candles)
    first_stats = repository.get_candle_stats("uid-sber")
    repository.upsert_candles(candles)
    second_stats = repository.get_candle_stats("uid-sber")

    assert first_stats == CandleDataStats(
        instrument_uid="uid-sber",
        row_count=3,
        min_timestamp=datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        max_timestamp=datetime(2026, 1, 5, 7, 2, tzinfo=UTC),
    )
    assert second_stats == first_stats
    assert repository.list_candles("uid-sber") == candles


def test_candle_upsert_updates_existing_timestamp(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.upsert_instrument(_instrument())

    repository.upsert_candles(
        (_candle_at(0, close="300.500000000", volume=100, is_complete=False),)
    )
    updated = _candle_at(
        0,
        close="300.900000000",
        volume=150,
        is_complete=True,
    )
    repository.upsert_candles((updated,))

    assert repository.get_candle_stats("uid-sber").row_count == 1
    assert repository.list_candles("uid-sber") == (updated,)


def test_get_candles_and_stats_use_half_open_range(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.upsert_instrument(_instrument())
    repository.upsert_candles(
        (_candle_at(0), _candle_at(1), _candle_at(2), _candle_at(3))
    )

    from_ts = datetime(2026, 1, 5, 7, 1, tzinfo=UTC)
    to_ts = datetime(2026, 1, 5, 7, 3, tzinfo=UTC)

    assert repository.get_candles(
        "uid-sber",
        from_ts=from_ts,
        to_ts=to_ts,
    ) == (_candle_at(1), _candle_at(2))
    assert repository.get_candle_stats(
        "uid-sber",
        from_ts=from_ts,
        to_ts=to_ts,
    ) == CandleDataStats(
        instrument_uid="uid-sber",
        row_count=2,
        min_timestamp=datetime(2026, 1, 5, 7, 1, tzinfo=UTC),
        max_timestamp=datetime(2026, 1, 5, 7, 2, tzinfo=UTC),
    )


def test_empty_candle_stats_have_no_timestamps(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.upsert_instrument(_instrument())

    assert repository.get_candle_stats("uid-sber") == CandleDataStats(
        instrument_uid="uid-sber",
        row_count=0,
        min_timestamp=None,
        max_timestamp=None,
    )


def test_candle_batch_is_atomic_on_foreign_key_error(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.upsert_instrument(_instrument())

    valid = _candle_at(0)
    invalid_fk = _candle_at(1, uid="missing-uid")

    try:
        repository.upsert_candles((valid, invalid_fk))
    except Exception:
        pass
    else:
        raise AssertionError("batch with invalid instrument UID must fail")

    assert repository.get_candle_stats("uid-sber").row_count == 0
