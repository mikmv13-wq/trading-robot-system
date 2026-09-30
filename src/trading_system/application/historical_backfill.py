from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trading_system.application.jobs import JobContext, JobManager
from trading_system.domain import CandleDataStats
from trading_system.ports import MarketRepository, TInvestMarketDataClient


class HistoricalBackfillError(RuntimeError):
    """Base error for historical candle ingestion."""


class BackfillUniverseNotFoundError(HistoricalBackfillError):
    """Raised when the requested universe has not been synchronized yet."""


@dataclass(frozen=True, slots=True)
class BackfillChunk:
    from_ts: datetime
    to_ts: datetime

    def __post_init__(self) -> None:
        _require_utc(self.from_ts, "from_ts")
        _require_utc(self.to_ts, "to_ts")
        if self.from_ts >= self.to_ts:
            raise ValueError("chunk from_ts must be earlier than to_ts")


class ChunkPlanner:
    """Split a historical time range into broker-safe request windows."""

    def __init__(self, *, max_span: timedelta = timedelta(days=1)) -> None:
        if max_span <= timedelta(0):
            raise ValueError("max_span must be positive")
        self._max_span = max_span

    @property
    def max_span(self) -> timedelta:
        return self._max_span

    def plan(self, from_ts: datetime, to_ts: datetime) -> tuple[BackfillChunk, ...]:
        _require_utc(from_ts, "from_ts")
        _require_utc(to_ts, "to_ts")
        if from_ts >= to_ts:
            raise ValueError("from_ts must be earlier than to_ts")

        chunks: list[BackfillChunk] = []
        cursor = from_ts
        while cursor < to_ts:
            chunk_end = min(cursor + self._max_span, to_ts)
            chunks.append(BackfillChunk(cursor, chunk_end))
            cursor = chunk_end
        return tuple(chunks)


@dataclass(frozen=True, slots=True)
class InstrumentBackfillResult:
    instrument_uid: str
    requests: int
    fetched_candles: int
    stats: CandleDataStats


@dataclass(frozen=True, slots=True)
class HistoricalBackfillResult:
    universe_id: str
    from_ts: datetime
    to_ts: datetime
    instruments: tuple[InstrumentBackfillResult, ...]

    @property
    def total_requests(self) -> int:
        return sum(item.requests for item in self.instruments)

    @property
    def total_fetched_candles(self) -> int:
        return sum(item.fetched_candles for item in self.instruments)


class BackfillHistoricalCandlesUseCase:
    def __init__(
        self,
        market_data: TInvestMarketDataClient,
        market_repository: MarketRepository,
        *,
        chunk_planner: ChunkPlanner | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._market_data = market_data
        self._market_repository = market_repository
        self._chunk_planner = chunk_planner or ChunkPlanner()
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def default_range(self) -> tuple[datetime, datetime]:
        to_ts = self._now_provider().astimezone(UTC).replace(second=0, microsecond=0)
        return _calendar_years_before(to_ts, 5), to_ts

    def execute(
        self,
        universe_id: str = "default",
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        context: JobContext | None = None,
    ) -> HistoricalBackfillResult:
        universe = self._market_repository.get_universe(universe_id)
        if universe is None:
            raise BackfillUniverseNotFoundError(
                f"universe {universe_id!r} has not been synchronized"
            )

        resolved_from, resolved_to = self._resolve_range(from_ts, to_ts)
        chunks = self._chunk_planner.plan(resolved_from, resolved_to)
        total_steps = len(universe.instrument_uids) * len(chunks)
        completed_steps = 0
        results: list[InstrumentBackfillResult] = []

        if context is not None:
            context.report_progress(
                0.0,
                (
                    f"Backfill {len(universe.instrument_uids)} instruments, "
                    f"{len(chunks)} chunks each"
                ),
            )

        for instrument_index, instrument_uid in enumerate(
            universe.instrument_uids,
            start=1,
        ):
            fetched_candles = 0
            requests = 0

            for chunk_index, chunk in enumerate(chunks, start=1):
                if context is not None:
                    context.raise_if_cancelled()

                candles = self._market_data.get_candles(
                    instrument_uid,
                    chunk.from_ts,
                    chunk.to_ts,
                )

                if context is not None:
                    context.raise_if_cancelled()

                self._market_repository.upsert_candles(candles)
                requests += 1
                fetched_candles += len(candles)
                completed_steps += 1

                if context is not None:
                    context.report_progress(
                        completed_steps / total_steps,
                        (
                            f"Instrument {instrument_index}/"
                            f"{len(universe.instrument_uids)} {instrument_uid}; "
                            f"chunk {chunk_index}/{len(chunks)} "
                            f"{chunk.from_ts:%Y-%m-%d %H:%M} -> "
                            f"{chunk.to_ts:%Y-%m-%d %H:%M}; "
                            f"fetched {fetched_candles}"
                        ),
                    )

            stats = self._market_repository.get_candle_stats(
                instrument_uid,
                from_ts=resolved_from,
                to_ts=resolved_to,
            )
            results.append(
                InstrumentBackfillResult(
                    instrument_uid=instrument_uid,
                    requests=requests,
                    fetched_candles=fetched_candles,
                    stats=stats,
                )
            )

        return HistoricalBackfillResult(
            universe_id=universe_id,
            from_ts=resolved_from,
            to_ts=resolved_to,
            instruments=tuple(results),
        )

    def _resolve_range(
        self,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[datetime, datetime]:
        default_from, default_to = self.default_range()
        resolved_from = default_from if from_ts is None else from_ts
        resolved_to = default_to if to_ts is None else to_ts
        _require_utc(resolved_from, "from_ts")
        _require_utc(resolved_to, "to_ts")
        if resolved_from >= resolved_to:
            raise ValueError("from_ts must be earlier than to_ts")
        return resolved_from, resolved_to


class HistoricalBackfillService:
    """Start historical backfill as a cancellable background job."""

    def __init__(
        self,
        manager: JobManager,
        use_case: BackfillHistoricalCandlesUseCase,
    ) -> None:
        self._manager = manager
        self._use_case = use_case

    def start(
        self,
        universe_id: str = "default",
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> str:
        def task(context: JobContext) -> HistoricalBackfillResult:
            return self._use_case.execute(
                universe_id,
                from_ts=from_ts,
                to_ts=to_ts,
                context=context,
            )

        return self._manager.submit(
            f"Historical 1m backfill: {universe_id}",
            task,
        )


def _calendar_years_before(value: datetime, years: int) -> datetime:
    if years <= 0:
        raise ValueError("years must be positive")
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        # February 29 -> February 28 in a non-leap target year.
        return value.replace(year=value.year - years, day=28)


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
