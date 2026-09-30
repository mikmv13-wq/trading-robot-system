from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from trading_system.domain import (
    DataQualityReport,
    DataQualityStatus,
    InstrumentDataQuality,
)
from trading_system.ports import MarketRepository


class DataQualityError(RuntimeError):
    """Base error for market data quality validation."""


class DataQualityUniverseNotFoundError(DataQualityError):
    """Raised when the requested universe does not exist."""


class DataQualityRangeError(DataQualityError):
    """Raised when a validation range cannot be inferred."""


class ValidateMarketDataUseCase:
    """Validate historical 1m data and persist gaps plus a DQ run summary."""

    INTERVAL = "1m"

    def __init__(
        self,
        market_repository: MarketRepository,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._market_repository = market_repository
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def execute(
        self,
        universe_id: str = "default",
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> DataQualityReport:
        universe = self._market_repository.get_universe(universe_id)
        if universe is None:
            raise DataQualityUniverseNotFoundError(
                f"universe {universe_id!r} has not been synchronized"
            )
        if not universe.instrument_uids:
            raise DataQualityError(f"universe {universe_id!r} is empty")

        resolved_from, resolved_to = self._resolve_range(
            universe.instrument_uids,
            from_ts,
            to_ts,
        )
        started_at = self._now_provider().astimezone(UTC)
        now = started_at
        instruments: list[InstrumentDataQuality] = []
        expected_minutes = self._market_repository.count_observed_market_minutes(
            universe_id,
            from_ts=resolved_from,
            to_ts=resolved_to,
        )

        for instrument_uid in universe.instrument_uids:
            stats = self._market_repository.get_candle_stats(
                instrument_uid,
                from_ts=resolved_from,
                to_ts=resolved_to,
            )
            quality = self._market_repository.get_candle_quality_counts(
                instrument_uid,
                from_ts=resolved_from,
                to_ts=resolved_to,
                now=now,
            )
            gaps = self._market_repository.scan_data_gaps(
                universe_id,
                instrument_uid,
                from_ts=resolved_from,
                to_ts=resolved_to,
            )
            self._market_repository.replace_data_gaps(
                instrument_uid,
                from_ts=resolved_from,
                to_ts=resolved_to,
                gaps=gaps,
            )
            missing_minutes = sum(
                int((gap.end_ts - gap.start_ts).total_seconds() // 60)
                for gap in gaps
            )
            coverage_ratio = (
                0.0
                if expected_minutes == 0
                else min(1.0, stats.row_count / expected_minutes)
            )
            anomaly_reasons = self._anomaly_reasons(
                row_count=stats.row_count,
                expected_minutes=expected_minutes,
                gap_count=len(gaps),
                missing_minutes=missing_minutes,
                incomplete_count=quality.incomplete_count,
                future_count=quality.future_count,
                invalid_ohlc_count=quality.invalid_ohlc_count,
                negative_volume_count=quality.negative_volume_count,
                off_minute_count=quality.off_minute_count,
            )
            status = self._instrument_status(
                stats.row_count,
                gap_count=len(gaps),
                incomplete_count=quality.incomplete_count,
                future_count=quality.future_count,
                invalid_ohlc_count=quality.invalid_ohlc_count,
                negative_volume_count=quality.negative_volume_count,
                off_minute_count=quality.off_minute_count,
            )
            instruments.append(
                InstrumentDataQuality(
                    instrument_uid=instrument_uid,
                    status=status,
                    stats=stats,
                    gap_count=len(gaps),
                    missing_minutes=missing_minutes,
                    expected_minutes=expected_minutes,
                    coverage_ratio=coverage_ratio,
                    anomaly_reasons=anomaly_reasons,
                    quality=quality,
                )
            )

        completed_at = self._now_provider().astimezone(UTC)
        report = DataQualityReport(
            run_id=uuid4().hex,
            universe_id=universe_id,
            started_at=started_at,
            completed_at=completed_at,
            status=self._overall_status(instruments),
            from_ts=resolved_from,
            to_ts=resolved_to,
            instruments=tuple(instruments),
        )
        self._market_repository.save_data_quality_report(report)
        return report

    def _resolve_range(
        self,
        instrument_uids: tuple[str, ...],
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[datetime, datetime]:
        if (from_ts is None) != (to_ts is None):
            raise ValueError("from_ts and to_ts must be provided together")
        if from_ts is not None and to_ts is not None:
            self._require_range(from_ts, to_ts)
            return from_ts, to_ts

        checkpoint_ranges = {
            (checkpoint.requested_from, checkpoint.requested_to)
            for instrument_uid in instrument_uids
            if (
                checkpoint := self._market_repository.get_ingestion_checkpoint(
                    instrument_uid,
                    self.INTERVAL,
                )
            )
            is not None
        }
        if len(checkpoint_ranges) == 1:
            return next(iter(checkpoint_ranges))
        if len(checkpoint_ranges) > 1:
            raise DataQualityRangeError(
                "ingestion checkpoints contain inconsistent requested ranges"
            )

        stats = [
            self._market_repository.get_candle_stats(instrument_uid)
            for instrument_uid in instrument_uids
        ]
        populated = [
            item
            for item in stats
            if item.min_timestamp is not None and item.max_timestamp is not None
        ]
        if not populated:
            raise DataQualityRangeError("no market data is available to validate")

        inferred_from = min(
            item.min_timestamp for item in populated if item.min_timestamp is not None
        )
        inferred_max = max(
            item.max_timestamp for item in populated if item.max_timestamp is not None
        )
        inferred_to = inferred_max + timedelta(minutes=1)
        self._require_range(inferred_from, inferred_to)
        return inferred_from, inferred_to

    @staticmethod
    def _anomaly_reasons(
        *,
        row_count: int,
        expected_minutes: int,
        gap_count: int,
        missing_minutes: int,
        incomplete_count: int,
        future_count: int,
        invalid_ohlc_count: int,
        negative_volume_count: int,
        off_minute_count: int,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if row_count == 0:
            reasons.append("no candles in validation range")
        if expected_minutes == 0:
            reasons.append("no observed market activity in universe")
        if gap_count > 0:
            reasons.append(
                f"{missing_minutes} missing minute(s) during observed market activity"
            )
        if incomplete_count > 0:
            reasons.append(f"{incomplete_count} incomplete candle(s)")
        if future_count > 0:
            reasons.append(f"{future_count} future candle(s)")
        if invalid_ohlc_count > 0:
            reasons.append(f"{invalid_ohlc_count} invalid OHLC candle(s)")
        if negative_volume_count > 0:
            reasons.append(f"{negative_volume_count} negative-volume candle(s)")
        if off_minute_count > 0:
            reasons.append(f"{off_minute_count} off-minute candle(s)")
        return tuple(reasons)

    @staticmethod
    def _instrument_status(
        row_count: int,
        *,
        gap_count: int,
        incomplete_count: int,
        future_count: int,
        invalid_ohlc_count: int,
        negative_volume_count: int,
        off_minute_count: int,
    ) -> DataQualityStatus:
        if (
            row_count == 0
            or future_count > 0
            or invalid_ohlc_count > 0
            or negative_volume_count > 0
            or off_minute_count > 0
        ):
            return DataQualityStatus.FAIL
        if gap_count > 0 or incomplete_count > 0:
            return DataQualityStatus.WARNING
        return DataQualityStatus.PASS

    @staticmethod
    def _overall_status(
        instruments: list[InstrumentDataQuality],
    ) -> DataQualityStatus:
        statuses = {item.status for item in instruments}
        if DataQualityStatus.FAIL in statuses:
            return DataQualityStatus.FAIL
        if DataQualityStatus.WARNING in statuses:
            return DataQualityStatus.WARNING
        return DataQualityStatus.PASS

    @staticmethod
    def _require_range(from_ts: datetime, to_ts: datetime) -> None:
        for value, field_name in ((from_ts, "from_ts"), (to_ts, "to_ts")):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware UTC")
            if value.utcoffset() != timedelta(0):
                raise ValueError(f"{field_name} must be UTC")
        if from_ts >= to_ts:
            raise ValueError("from_ts must be earlier than to_ts")
