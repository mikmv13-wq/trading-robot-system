from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import quote, unquote

from .models import Candle


DATASET_VIEWS = {
    "1m": "candles_1m",
    "15m": "candles_15m",
    "30m": "candles_30m",
    "1h": "candles_1h",
}

SUPPORTED_COMPRESSIONS = {
    "uncompressed",
    "snappy",
    "gzip",
    "zstd",
    "brotli",
    "lz4",
    "lz4_raw",
}


class CandleStorage(Protocol):
    def initialize(self) -> None: ...

    def upsert(self, candles: Iterable[Candle]) -> int: ...

    def latest_time(self, instrument_id: str) -> datetime | None: ...


class ParquetCandleStorage:
    """Parquet market-data lake with a DuckDB catalog.

    Candle history stays in monthly Parquet partitions. DuckDB stores only compact
    operational metadata/checkpoints and exposes SQL views over the Parquet datasets.
    It is intentionally not used as the primary candle store.
    """

    def __init__(
        self,
        root_path: str | Path,
        catalog_path: str | Path,
        *,
        compression: str = "zstd",
    ) -> None:
        self.root_path = Path(root_path)
        self.catalog_path = Path(catalog_path)
        self.compression = compression.lower()
        if self.compression not in SUPPORTED_COMPRESSIONS:
            raise ValueError(f"Unsupported Parquet compression: {compression}")
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)

    def connect_catalog(self):
        duckdb = _load_duckdb()
        return duckdb.connect(str(self.catalog_path))

    def initialize(self) -> None:
        connection = self.connect_catalog()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS partitions (
                    timeframe VARCHAR NOT NULL,
                    instrument_id VARCHAR NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    row_count BIGINT NOT NULL,
                    first_time TIMESTAMPTZ,
                    last_time TIMESTAMPTZ,
                    dirty BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (timeframe, instrument_id, year, month)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS system_metadata (
                    key VARCHAR PRIMARY KEY,
                    value VARCHAR NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO system_metadata (key, value, updated_at)
                VALUES ('storage_schema_version', '1', ?)
                ON CONFLICT (key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [datetime.now(timezone.utc)],
            )
        finally:
            connection.close()

        # A lost/new catalog must not force a five-year re-download when Parquet already exists.
        self._bootstrap_catalog_if_empty()

        # Rebind views to the current absolute data path when a project is moved.
        self.refresh_dataset_views()

    def upsert(self, candles: Iterable[Candle]) -> int:
        rows = list(candles)
        if not rows:
            return 0

        grouped: dict[tuple[str, int, int], list[Candle]] = defaultdict(list)
        for candle in rows:
            utc_time = candle.time.astimezone(timezone.utc)
            grouped[(candle.instrument_id, utc_time.year, utc_time.month)].append(candle)

        for (instrument_id, year, month), partition_rows in grouped.items():
            existing = self.read_partition("1m", instrument_id, year, month)
            merged = {candle.time.astimezone(timezone.utc): candle for candle in existing}
            for candle in partition_rows:
                merged[candle.time.astimezone(timezone.utc)] = candle
            final_rows = sorted(merged.values(), key=lambda item: item.time)
            self._write_partition("1m", instrument_id, year, month, final_rows)
            self._record_partition(
                timeframe="1m",
                instrument_id=instrument_id,
                year=year,
                month=month,
                rows=final_rows,
                dirty=True,
            )
            self._ensure_dataset_view("1m")
        return len(rows)

    def replace_aggregate_partition(
        self,
        timeframe: str,
        instrument_id: str,
        year: int,
        month: int,
        candles: Iterable[Candle],
    ) -> int:
        if timeframe == "1m":
            raise ValueError("replace_aggregate_partition cannot write raw 1m data")
        if timeframe not in DATASET_VIEWS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        rows = sorted(candles, key=lambda item: item.time)
        self._write_partition(timeframe, instrument_id, year, month, rows)
        self._record_partition(
            timeframe=timeframe,
            instrument_id=instrument_id,
            year=year,
            month=month,
            rows=rows,
            dirty=False,
        )
        self._ensure_dataset_view(timeframe)
        return len(rows)

    def latest_time(self, instrument_id: str) -> datetime | None:
        connection = self.connect_catalog()
        try:
            row = connection.execute(
                """
                SELECT MAX(last_time)
                FROM partitions
                WHERE timeframe = '1m' AND instrument_id = ?
                """,
                [instrument_id],
            ).fetchone()
        finally:
            connection.close()

        if not row or row[0] is None:
            return None
        return _as_utc(row[0])

    def read_partition(
        self,
        timeframe: str,
        instrument_id: str,
        year: int,
        month: int,
    ) -> list[Candle]:
        path = self.partition_path(timeframe, instrument_id, year, month)
        if not path.exists():
            return []

        duckdb = _load_duckdb()
        connection = duckdb.connect()
        try:
            rows = connection.execute(
                f"""
                SELECT
                    instrument_id, time, open_nano, high_nano, low_nano,
                    close_nano, volume, is_complete, source
                FROM read_parquet({_sql_literal(path)})
                ORDER BY time
                """
            ).fetchall()
        finally:
            connection.close()

        return [_row_to_candle(row) for row in rows]

    def query_candles(
        self,
        timeframe: str,
        instrument_id: str,
        *,
        from_: datetime | None = None,
        to: datetime | None = None,
    ) -> list[Candle]:
        """Query a whole timeframe through DuckDB without importing Parquet into the catalog."""
        view_name = self._ensure_dataset_view(timeframe)
        if view_name is None:
            return []

        predicates = ["instrument_id = ?"]
        parameters: list[Any] = [instrument_id]
        if from_ is not None:
            predicates.append("time >= ?")
            parameters.append(from_.astimezone(timezone.utc))
        if to is not None:
            predicates.append("time < ?")
            parameters.append(to.astimezone(timezone.utc))

        connection = self.connect_catalog()
        try:
            rows = connection.execute(
                f"""
                SELECT
                    instrument_id, time, open_nano, high_nano, low_nano,
                    close_nano, volume, is_complete, source
                FROM {view_name}
                WHERE {' AND '.join(predicates)}
                ORDER BY time
                """,
                parameters,
            ).fetchall()
        finally:
            connection.close()
        return [_row_to_candle(row) for row in rows]

    def partition_path(self, timeframe: str, instrument_id: str, year: int, month: int) -> Path:
        if timeframe not in DATASET_VIEWS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        safe_id = quote(instrument_id, safe="")
        return (
            self.root_path
            / timeframe
            / f"instrument_id={safe_id}"
            / f"year={year:04d}"
            / f"month={month:02d}"
            / "candles.parquet"
        )

    def dirty_raw_partitions(self) -> list[tuple[str, int, int]]:
        connection = self.connect_catalog()
        try:
            rows = connection.execute(
                """
                SELECT instrument_id, year, month
                FROM partitions
                WHERE timeframe = '1m' AND dirty = TRUE
                ORDER BY instrument_id, year, month
                """
            ).fetchall()
        finally:
            connection.close()
        return [(str(instrument_id), int(year), int(month)) for instrument_id, year, month in rows]

    def all_raw_partitions(self) -> list[tuple[str, int, int]]:
        connection = self.connect_catalog()
        try:
            rows = connection.execute(
                """
                SELECT instrument_id, year, month
                FROM partitions
                WHERE timeframe = '1m'
                ORDER BY instrument_id, year, month
                """
            ).fetchall()
        finally:
            connection.close()
        return [(str(instrument_id), int(year), int(month)) for instrument_id, year, month in rows]

    def mark_raw_partition_clean(self, instrument_id: str, year: int, month: int) -> None:
        connection = self.connect_catalog()
        try:
            connection.execute(
                """
                UPDATE partitions
                SET dirty = FALSE, updated_at = ?
                WHERE timeframe = '1m' AND instrument_id = ? AND year = ? AND month = ?
                """,
                [datetime.now(timezone.utc), instrument_id, year, month],
            )
        finally:
            connection.close()

    def stats(self) -> list[tuple[str, str, int, datetime | None, datetime | None]]:
        connection = self.connect_catalog()
        try:
            rows = connection.execute(
                """
                SELECT timeframe, instrument_id, SUM(row_count), MIN(first_time), MAX(last_time)
                FROM partitions
                GROUP BY timeframe, instrument_id
                ORDER BY timeframe, instrument_id
                """
            ).fetchall()
        finally:
            connection.close()
        return [
            (
                str(timeframe),
                str(instrument_id),
                int(row_count),
                _as_utc(first_time) if first_time is not None else None,
                _as_utc(last_time) if last_time is not None else None,
            )
            for timeframe, instrument_id, row_count, first_time, last_time in rows
        ]

    def refresh_dataset_views(self) -> None:
        for timeframe in DATASET_VIEWS:
            if self._dataset_has_files(timeframe):
                self._create_or_replace_dataset_view(timeframe)

    def _bootstrap_catalog_if_empty(self) -> None:
        connection = self.connect_catalog()
        try:
            row = connection.execute("SELECT COUNT(*) FROM partitions").fetchone()
            has_metadata = bool(row and row[0])
        finally:
            connection.close()

        if has_metadata:
            return

        partition_files = list(self._iter_partition_files())
        if not partition_files:
            return

        duckdb = _load_duckdb()
        parquet_connection = duckdb.connect()
        catalog_connection = self.connect_catalog()
        now = datetime.now(timezone.utc)
        try:
            for timeframe, instrument_id, year, month, path in partition_files:
                row = parquet_connection.execute(
                    f"""
                    SELECT COUNT(*), MIN(time), MAX(time), MIN(instrument_id)
                    FROM read_parquet({_sql_literal(path)})
                    """
                ).fetchone()
                row_count = int(row[0]) if row else 0
                first_time = _as_utc(row[1]) if row and row[1] is not None else None
                last_time = _as_utc(row[2]) if row and row[2] is not None else None
                stored_instrument_id = (
                    str(row[3]) if row and row[3] is not None else instrument_id
                )
                catalog_connection.execute(
                    """
                    INSERT INTO partitions (
                        timeframe, instrument_id, year, month, row_count,
                        first_time, last_time, dirty, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (timeframe, instrument_id, year, month) DO NOTHING
                    """,
                    [
                        timeframe,
                        stored_instrument_id,
                        year,
                        month,
                        row_count,
                        first_time,
                        last_time,
                        timeframe == "1m",
                        now,
                    ],
                )
        finally:
            catalog_connection.close()
            parquet_connection.close()

    def _iter_partition_files(self):
        for timeframe in DATASET_VIEWS:
            timeframe_dir = self.root_path / timeframe
            if not timeframe_dir.exists():
                continue
            pattern = "instrument_id=*/year=*/month=*/candles.parquet"
            for path in sorted(timeframe_dir.glob(pattern)):
                try:
                    instrument_id = unquote(path.parent.parent.parent.name.split("=", 1)[1])
                    year = int(path.parent.parent.name.split("=", 1)[1])
                    month = int(path.parent.name.split("=", 1)[1])
                except (IndexError, ValueError):
                    continue
                yield timeframe, instrument_id, year, month, path

    def _write_partition(
        self,
        timeframe: str,
        instrument_id: str,
        year: int,
        month: int,
        rows: list[Candle],
    ) -> None:
        path = self.partition_path(timeframe, instrument_id, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name("candles.parquet.tmp")
        temp_path.unlink(missing_ok=True)

        duckdb = _load_duckdb()
        connection = duckdb.connect()
        try:
            connection.execute(
                """
                CREATE TEMP TABLE partition_candles (
                    instrument_id VARCHAR NOT NULL,
                    time TIMESTAMPTZ NOT NULL,
                    open_nano BIGINT NOT NULL,
                    high_nano BIGINT NOT NULL,
                    low_nano BIGINT NOT NULL,
                    close_nano BIGINT NOT NULL,
                    volume BIGINT NOT NULL,
                    is_complete BOOLEAN NOT NULL,
                    source VARCHAR
                )
                """
            )
            if rows:
                connection.executemany(
                    """
                    INSERT INTO partition_candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            candle.instrument_id,
                            candle.time.astimezone(timezone.utc),
                            candle.open_nano,
                            candle.high_nano,
                            candle.low_nano,
                            candle.close_nano,
                            candle.volume,
                            candle.is_complete,
                            candle.source,
                        )
                        for candle in rows
                    ],
                )

            connection.execute(
                f"""
                COPY (
                    SELECT * FROM partition_candles ORDER BY time
                ) TO {_sql_literal(temp_path)}
                (FORMAT parquet, COMPRESSION {self.compression})
                """
            )
        finally:
            connection.close()

        os.replace(temp_path, path)

    def _record_partition(
        self,
        *,
        timeframe: str,
        instrument_id: str,
        year: int,
        month: int,
        rows: list[Candle],
        dirty: bool,
    ) -> None:
        updated_at = datetime.now(timezone.utc)
        first_time = rows[0].time.astimezone(timezone.utc) if rows else None
        last_time = rows[-1].time.astimezone(timezone.utc) if rows else None

        connection = self.connect_catalog()
        try:
            connection.execute(
                """
                INSERT INTO partitions (
                    timeframe, instrument_id, year, month, row_count,
                    first_time, last_time, dirty, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (timeframe, instrument_id, year, month) DO UPDATE SET
                    row_count = excluded.row_count,
                    first_time = excluded.first_time,
                    last_time = excluded.last_time,
                    dirty = excluded.dirty,
                    updated_at = excluded.updated_at
                """,
                [
                    timeframe,
                    instrument_id,
                    year,
                    month,
                    len(rows),
                    first_time,
                    last_time,
                    dirty,
                    updated_at,
                ],
            )
        finally:
            connection.close()

    def _dataset_glob(self, timeframe: str) -> Path:
        return (
            self.root_path.resolve()
            / timeframe
            / "instrument_id=*"
            / "year=*"
            / "month=*"
            / "candles.parquet"
        )

    def _dataset_has_files(self, timeframe: str) -> bool:
        directory = self.root_path / timeframe
        return directory.exists() and any(directory.rglob("candles.parquet"))

    def _ensure_dataset_view(self, timeframe: str) -> str | None:
        if timeframe not in DATASET_VIEWS:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if not self._dataset_has_files(timeframe):
            return None

        view_name = DATASET_VIEWS[timeframe]
        connection = self.connect_catalog()
        try:
            exists = connection.execute(
                "SELECT 1 FROM duckdb_views() WHERE schema_name = 'main' AND view_name = ? LIMIT 1",
                [view_name],
            ).fetchone()
        finally:
            connection.close()

        if not exists:
            self._create_or_replace_dataset_view(timeframe)
        return view_name

    def _create_or_replace_dataset_view(self, timeframe: str) -> None:
        view_name = DATASET_VIEWS[timeframe]
        parquet_glob = self._dataset_glob(timeframe)
        connection = self.connect_catalog()
        try:
            connection.execute(
                f"""
                CREATE OR REPLACE VIEW {view_name} AS
                SELECT
                    instrument_id, time, open_nano, high_nano, low_nano,
                    close_nano, volume, is_complete, source
                FROM read_parquet(
                    {_sql_literal(parquet_glob)},
                    hive_partitioning = false,
                    union_by_name = true
                )
                """
            )
        finally:
            connection.close()


def _load_duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency error is environment-specific
        raise RuntimeError(
            "Storage requires DuckDB. Install project dependencies with: pip install -e ."
        ) from exc
    return duckdb


def _sql_literal(path: str | Path) -> str:
    value = str(path).replace("'", "''")
    return f"'{value}'"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_to_candle(row: tuple[Any, ...]) -> Candle:
    timestamp = _as_utc(row[1])
    return Candle(
        instrument_id=str(row[0]),
        time=timestamp,
        open_nano=int(row[2]),
        high_nano=int(row[3]),
        low_nano=int(row[4]),
        close_nano=int(row[5]),
        volume=int(row[6]),
        is_complete=bool(row[7]),
        source=str(row[8]) if row[8] is not None else None,
    )
