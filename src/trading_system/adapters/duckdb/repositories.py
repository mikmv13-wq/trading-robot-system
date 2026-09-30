from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from trading_system.adapters.duckdb.connection import DuckDBConnectionFactory
from trading_system.domain import (
    Candle1m,
    CandleDataStats,
    CandleQualityCounts,
    DataGap,
    DataQualityReport,
    GapClassification,
    IngestionCheckpoint,
    IngestionStatus,
    Instrument,
    Universe,
)


class RepositoryError(RuntimeError):
    """Base error for DuckDB repository access."""


class DatabaseIdentityError(RepositoryError):
    """Raised when a repository is wired to the wrong DuckDB file."""


class DuckDBRepository:
    """Shared foundation for the three DuckDB repositories."""

    def __init__(
        self,
        path: Path,
        expected_kind: str,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        self._path = path
        self._expected_kind = expected_kind
        self._connection_factory = connection_factory or DuckDBConnectionFactory()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def database_kind(self) -> str:
        return self._expected_kind

    def healthcheck(self) -> None:
        with self._verified_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            self._schema_version(connection)

    def schema_version(self) -> int:
        with self._verified_connection() as connection:
            return self._schema_version(connection)

    def metadata(self) -> Mapping[str, str]:
        with self._verified_connection() as connection:
            return self._read_metadata(connection)

    @contextmanager
    def _verified_connection(
        self,
        *,
        read_only: bool = True,
    ) -> Iterator[duckdb.DuckDBPyConnection]:
        try:
            with self._connection_factory.open(
                self._path,
                read_only=read_only,
            ) as connection:
                metadata = self._read_metadata(connection)
                actual_kind = metadata.get("database_kind")
                if actual_kind != self._expected_kind:
                    raise DatabaseIdentityError(
                        f"expected {self._expected_kind!r} database at {self._path}, "
                        f"found {actual_kind!r}"
                    )
                yield connection
        except RepositoryError:
            raise
        except Exception as exc:
            raise RepositoryError(
                f"failed to access {self._expected_kind!r} database at {self._path}"
            ) from exc

    @staticmethod
    def _read_metadata(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
        rows = connection.execute(
            "SELECT key, value FROM database_metadata ORDER BY key"
        ).fetchall()
        return {str(key): str(value) for key, value in rows}

    @staticmethod
    def _schema_version(connection: duckdb.DuckDBPyConnection) -> int:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        if row is None:
            raise RepositoryError("schema_migrations query returned no row")
        value = row[0]
        return 0 if value is None else int(value)


class DuckDBMarketRepository(DuckDBRepository):
    def __init__(
        self,
        path: Path,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        super().__init__(path, "market", connection_factory)

    def upsert_instrument(self, instrument: Instrument) -> None:
        with self._verified_connection(read_only=False) as connection:
            self._upsert_instrument(connection, instrument)

    def get_instrument(self, instrument_uid: str) -> Instrument | None:
        with self._verified_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    instrument_uid,
                    ticker,
                    lot_size,
                    name,
                    currency,
                    figi,
                    exchange,
                    instrument_type,
                    active
                FROM instruments
                WHERE instrument_uid = ?
                """,
                [instrument_uid],
            ).fetchone()

        if row is None:
            return None
        return self._instrument_from_row(row)

    def list_instruments(self) -> tuple[Instrument, ...]:
        with self._verified_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    instrument_uid,
                    ticker,
                    lot_size,
                    name,
                    currency,
                    figi,
                    exchange,
                    instrument_type,
                    active
                FROM instruments
                ORDER BY ticker, instrument_uid
                """
            ).fetchall()
        return tuple(self._instrument_from_row(row) for row in rows)

    def replace_universe(self, universe: Universe) -> None:
        with self._verified_connection(read_only=False) as connection:
            try:
                connection.execute("BEGIN TRANSACTION")
                self._replace_universe(connection, universe)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def sync_universe(
        self,
        universe: Universe,
        instruments: tuple[Instrument, ...],
    ) -> None:
        expected_uids = set(universe.instrument_uids)
        actual_uids = {instrument.instrument_uid for instrument in instruments}
        if expected_uids != actual_uids:
            raise ValueError("universe instrument_uids must match synchronized instruments")

        with self._verified_connection(read_only=False) as connection:
            try:
                connection.execute("BEGIN TRANSACTION")
                for instrument in instruments:
                    self._upsert_instrument(connection, instrument)
                self._replace_universe(connection, universe)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _upsert_instrument(
        connection: duckdb.DuckDBPyConnection,
        instrument: Instrument,
    ) -> None:
        connection.execute(
            """
            INSERT INTO instruments(
                instrument_uid,
                ticker,
                lot_size,
                name,
                currency,
                figi,
                exchange,
                instrument_type,
                active,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (instrument_uid) DO UPDATE SET
                ticker = EXCLUDED.ticker,
                lot_size = EXCLUDED.lot_size,
                name = EXCLUDED.name,
                currency = EXCLUDED.currency,
                figi = EXCLUDED.figi,
                exchange = EXCLUDED.exchange,
                instrument_type = EXCLUDED.instrument_type,
                active = EXCLUDED.active,
                updated_at = now()
            """,
            [
                instrument.instrument_uid,
                instrument.ticker,
                instrument.lot_size,
                instrument.name,
                instrument.currency,
                instrument.figi,
                instrument.exchange,
                instrument.instrument_type,
                instrument.active,
            ],
        )

    @staticmethod
    def _replace_universe(
        connection: duckdb.DuckDBPyConnection,
        universe: Universe,
    ) -> None:
        connection.execute(
            """
            INSERT INTO universes(
                universe_id,
                name,
                created_at,
                updated_at
            )
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (universe_id) DO UPDATE SET
                name = EXCLUDED.name,
                updated_at = now()
            """,
            [universe.universe_id, universe.name],
        )
        connection.execute(
            "DELETE FROM universe_instruments WHERE universe_id = ?",
            [universe.universe_id],
        )
        for instrument_uid in universe.instrument_uids:
            connection.execute(
                """
                INSERT INTO universe_instruments(universe_id, instrument_uid)
                VALUES (?, ?)
                """,
                [universe.universe_id, instrument_uid],
            )

    def get_universe(self, universe_id: str) -> Universe | None:
        with self._verified_connection() as connection:
            row = connection.execute(
                "SELECT universe_id, name FROM universes WHERE universe_id = ?",
                [universe_id],
            ).fetchone()
            if row is None:
                return None
            member_rows = connection.execute(
                """
                SELECT instrument_uid
                FROM universe_instruments
                WHERE universe_id = ?
                ORDER BY instrument_uid
                """,
                [universe_id],
            ).fetchall()

        return Universe(
            universe_id=str(row[0]),
            name=str(row[1]),
            instrument_uids=tuple(str(member[0]) for member in member_rows),
        )

    def insert_candle(self, candle: Candle1m) -> None:
        self.upsert_candles((candle,))

    def upsert_candles(self, candles: Sequence[Candle1m]) -> None:
        if not candles:
            return

        rows = [
            (
                candle.instrument_uid,
                candle.ts,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.is_complete,
            )
            for candle in candles
        ]
        with self._verified_connection(read_only=False) as connection:
            try:
                connection.execute("BEGIN TRANSACTION")
                connection.executemany(
                    """
                    INSERT INTO candles_1m(
                        instrument_uid,
                        ts,
                        open,
                        high,
                        low,
                        close,
                        volume,
                        is_complete
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (instrument_uid, ts) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        is_complete = EXCLUDED.is_complete
                    """,
                    rows,
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get_candles(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[Candle1m, ...]:
        normalized_uid = instrument_uid.strip()
        if not normalized_uid:
            raise ValueError("instrument_uid must not be empty")
        self._validate_optional_utc(from_ts, "from_ts")
        self._validate_optional_utc(to_ts, "to_ts")
        if from_ts is not None and to_ts is not None and from_ts >= to_ts:
            raise ValueError("from_ts must be earlier than to_ts")

        where_sql, params = self._candle_range_filter(
            normalized_uid,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        with self._verified_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    instrument_uid,
                    ts,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    is_complete
                FROM candles_1m
                WHERE {where_sql}
                ORDER BY ts
                """,
                params,
            ).fetchall()

        return tuple(self._candle_from_row(row) for row in rows)

    def list_candles(self, instrument_uid: str) -> tuple[Candle1m, ...]:
        return self.get_candles(instrument_uid)

    def get_candle_stats(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> CandleDataStats:
        normalized_uid = instrument_uid.strip()
        if not normalized_uid:
            raise ValueError("instrument_uid must not be empty")
        self._validate_optional_utc(from_ts, "from_ts")
        self._validate_optional_utc(to_ts, "to_ts")
        if from_ts is not None and to_ts is not None and from_ts >= to_ts:
            raise ValueError("from_ts must be earlier than to_ts")

        where_sql, params = self._candle_range_filter(
            normalized_uid,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        with self._verified_connection() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*), MIN(ts), MAX(ts)
                FROM candles_1m
                WHERE {where_sql}
                """,
                params,
            ).fetchone()

        if row is None:
            raise RepositoryError("candle statistics query returned no row")
        row_count = int(row[0])
        return CandleDataStats(
            instrument_uid=normalized_uid,
            row_count=row_count,
            min_timestamp=None if row[1] is None else row[1].astimezone(UTC),
            max_timestamp=None if row[2] is None else row[2].astimezone(UTC),
        )

    def save_ingestion_checkpoint(
        self,
        checkpoint: IngestionCheckpoint,
    ) -> None:
        with self._verified_connection(read_only=False) as connection:
            connection.execute(
                """
                INSERT INTO ingestion_checkpoints(
                    instrument_uid,
                    interval,
                    requested_from,
                    requested_to,
                    completed_until,
                    status,
                    last_error,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, now())
                ON CONFLICT (instrument_uid, interval) DO UPDATE SET
                    requested_from = EXCLUDED.requested_from,
                    requested_to = EXCLUDED.requested_to,
                    completed_until = EXCLUDED.completed_until,
                    status = EXCLUDED.status,
                    last_error = EXCLUDED.last_error,
                    updated_at = now()
                """,
                [
                    checkpoint.instrument_uid,
                    checkpoint.interval,
                    checkpoint.requested_from,
                    checkpoint.requested_to,
                    checkpoint.completed_until,
                    checkpoint.status.value,
                    checkpoint.last_error,
                ],
            )

    def get_ingestion_checkpoint(
        self,
        instrument_uid: str,
        interval: str,
    ) -> IngestionCheckpoint | None:
        normalized_uid = instrument_uid.strip()
        normalized_interval = interval.strip()
        if not normalized_uid:
            raise ValueError("instrument_uid must not be empty")
        if not normalized_interval:
            raise ValueError("interval must not be empty")

        with self._verified_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    instrument_uid,
                    interval,
                    requested_from,
                    requested_to,
                    completed_until,
                    status,
                    last_error,
                    updated_at
                FROM ingestion_checkpoints
                WHERE instrument_uid = ? AND interval = ?
                """,
                [normalized_uid, normalized_interval],
            ).fetchone()

        if row is None:
            return None
        return IngestionCheckpoint(
            instrument_uid=str(row[0]),
            interval=str(row[1]),
            requested_from=row[2].astimezone(UTC),
            requested_to=row[3].astimezone(UTC),
            completed_until=(
                None if row[4] is None else row[4].astimezone(UTC)
            ),
            status=IngestionStatus(str(row[5])),
            last_error=None if row[6] is None else str(row[6]),
            updated_at=row[7].astimezone(UTC),
        )

    def scan_data_gaps(
        self,
        universe_id: str,
        instrument_uid: str,
        *,
        from_ts: datetime,
        to_ts: datetime,
    ) -> tuple[DataGap, ...]:
        self._validate_optional_utc(from_ts, "from_ts")
        self._validate_optional_utc(to_ts, "to_ts")
        if from_ts >= to_ts:
            raise ValueError("from_ts must be earlier than to_ts")

        with self._verified_connection() as connection:
            rows = connection.execute(
                """
                WITH observed AS (
                    SELECT DISTINCT c.ts
                    FROM candles_1m AS c
                    JOIN universe_instruments AS ui
                      ON ui.instrument_uid = c.instrument_uid
                    WHERE ui.universe_id = ?
                      AND c.ts >= ?
                      AND c.ts < ?
                ),
                missing AS (
                    SELECT
                        o.ts,
                        row_number() OVER (ORDER BY o.ts) AS rn
                    FROM observed AS o
                    LEFT JOIN candles_1m AS target
                      ON target.instrument_uid = ?
                     AND target.ts = o.ts
                    WHERE target.ts IS NULL
                ),
                grouped AS (
                    SELECT
                        ts,
                        ts - rn * INTERVAL '1 minute' AS gap_group
                    FROM missing
                )
                SELECT
                    min(ts) AS start_ts,
                    max(ts) + INTERVAL '1 minute' AS end_ts
                FROM grouped
                GROUP BY gap_group
                ORDER BY start_ts
                """,
                [universe_id, from_ts, to_ts, instrument_uid],
            ).fetchall()

        return tuple(
            DataGap(
                instrument_uid=instrument_uid,
                start_ts=row[0].astimezone(UTC),
                end_ts=row[1].astimezone(UTC),
                classification=GapClassification.MISSING_DURING_OBSERVED_MARKET,
            )
            for row in rows
        )

    def replace_data_gaps(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime,
        to_ts: datetime,
        gaps: Sequence[DataGap],
    ) -> None:
        with self._verified_connection(read_only=False) as connection:
            try:
                connection.execute("BEGIN TRANSACTION")
                connection.execute(
                    """
                    DELETE FROM data_gaps
                    WHERE instrument_uid = ?
                      AND start_ts >= ?
                      AND end_ts <= ?
                    """,
                    [instrument_uid, from_ts, to_ts],
                )
                if gaps:
                    connection.executemany(
                        """
                        INSERT INTO data_gaps(
                            instrument_uid,
                            start_ts,
                            end_ts,
                            classification,
                            detected_at
                        )
                        VALUES (?, ?, ?, ?, now())
                        ON CONFLICT (instrument_uid, start_ts, end_ts)
                        DO UPDATE SET
                            classification = EXCLUDED.classification,
                            detected_at = now()
                        """,
                        [
                            (
                                gap.instrument_uid,
                                gap.start_ts,
                                gap.end_ts,
                                gap.classification.value,
                            )
                            for gap in gaps
                        ],
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get_data_gaps(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> tuple[DataGap, ...]:
        clauses = ["instrument_uid = ?"]
        params: list[object] = [instrument_uid]
        if from_ts is not None:
            clauses.append("end_ts > ?")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("start_ts < ?")
            params.append(to_ts)

        with self._verified_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT instrument_uid, start_ts, end_ts, classification
                FROM data_gaps
                WHERE {' AND '.join(clauses)}
                ORDER BY start_ts
                """,
                params,
            ).fetchall()
        return tuple(
            DataGap(
                instrument_uid=str(row[0]),
                start_ts=row[1].astimezone(UTC),
                end_ts=row[2].astimezone(UTC),
                classification=GapClassification(str(row[3])),
            )
            for row in rows
        )

    def get_candle_quality_counts(
        self,
        instrument_uid: str,
        *,
        from_ts: datetime,
        to_ts: datetime,
        now: datetime,
    ) -> CandleQualityCounts:
        with self._verified_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    count(*),
                    sum(CASE WHEN NOT is_complete THEN 1 ELSE 0 END),
                    sum(CASE WHEN ts > ? THEN 1 ELSE 0 END),
                    sum(
                        CASE
                            WHEN low > open OR low > close OR low > high
                              OR high < open OR high < close OR high < low
                            THEN 1 ELSE 0
                        END
                    ),
                    sum(CASE WHEN volume < 0 THEN 1 ELSE 0 END),
                    sum(
                        CASE WHEN date_trunc('minute', ts) <> ts
                             THEN 1 ELSE 0 END
                    )
                FROM candles_1m
                WHERE instrument_uid = ?
                  AND ts >= ?
                  AND ts < ?
                """,
                [now, instrument_uid, from_ts, to_ts],
            ).fetchone()

        if row is None:
            raise RepositoryError("candle quality query returned no row")
        values = [0 if value is None else int(value) for value in row]
        return CandleQualityCounts(
            instrument_uid=instrument_uid,
            row_count=values[0],
            incomplete_count=values[1],
            future_count=values[2],
            invalid_ohlc_count=values[3],
            negative_volume_count=values[4],
            off_minute_count=values[5],
        )

    def save_data_quality_report(self, report: DataQualityReport) -> None:
        summary = json.dumps(
            {
                "universe_id": report.universe_id,
                "from_ts": report.from_ts.isoformat(),
                "to_ts": report.to_ts.isoformat(),
                "calendar_mode": report.calendar_mode,
                "status": report.status.value,
                "instruments": [
                    {
                        "instrument_uid": item.instrument_uid,
                        "status": item.status.value,
                        "row_count": item.stats.row_count,
                        "min_timestamp": (
                            None
                            if item.stats.min_timestamp is None
                            else item.stats.min_timestamp.isoformat()
                        ),
                        "max_timestamp": (
                            None
                            if item.stats.max_timestamp is None
                            else item.stats.max_timestamp.isoformat()
                        ),
                        "gap_count": item.gap_count,
                        "missing_minutes": item.missing_minutes,
                        "incomplete_count": item.quality.incomplete_count,
                        "future_count": item.quality.future_count,
                        "invalid_ohlc_count": item.quality.invalid_ohlc_count,
                        "negative_volume_count": item.quality.negative_volume_count,
                        "off_minute_count": item.quality.off_minute_count,
                    }
                    for item in report.instruments
                ],
            },
            sort_keys=True,
        )
        with self._verified_connection(read_only=False) as connection:
            connection.execute(
                """
                INSERT INTO data_quality_runs(
                    run_id,
                    started_at,
                    completed_at,
                    status,
                    summary
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    completed_at = EXCLUDED.completed_at,
                    status = EXCLUDED.status,
                    summary = EXCLUDED.summary
                """,
                [
                    report.run_id,
                    report.started_at,
                    report.completed_at,
                    report.status.value,
                    summary,
                ],
            )

    @staticmethod
    def _candle_range_filter(
        instrument_uid: str,
        *,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[str, list[object]]:
        clauses = ["instrument_uid = ?"]
        params: list[object] = [instrument_uid]
        if from_ts is not None:
            clauses.append("ts >= ?")
            params.append(from_ts)
        if to_ts is not None:
            clauses.append("ts < ?")
            params.append(to_ts)
        return " AND ".join(clauses), params

    @staticmethod
    def _validate_optional_utc(value: datetime | None, field_name: str) -> None:
        if value is None:
            return
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must be UTC")

    @staticmethod
    def _candle_from_row(row: tuple[Any, ...]) -> Candle1m:
        return Candle1m(
            instrument_uid=str(row[0]),
            ts=row[1].astimezone(UTC),
            open=row[2],
            high=row[3],
            low=row[4],
            close=row[5],
            volume=int(row[6]),
            is_complete=bool(row[7]),
        )

    @staticmethod
    def _instrument_from_row(row: tuple[Any, ...]) -> Instrument:
        return Instrument(
            instrument_uid=str(row[0]),
            ticker=str(row[1]),
            lot_size=int(row[2]),
            name=None if row[3] is None else str(row[3]),
            currency=None if row[4] is None else str(row[4]),
            figi=None if row[5] is None else str(row[5]),
            exchange=None if row[6] is None else str(row[6]),
            instrument_type=None if row[7] is None else str(row[7]),
            active=bool(row[8]),
        )


class DuckDBResearchRepository(DuckDBRepository):
    def __init__(
        self,
        path: Path,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        super().__init__(path, "research", connection_factory)


class DuckDBLiveRepository(DuckDBRepository):
    def __init__(
        self,
        path: Path,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        super().__init__(path, "live", connection_factory)
