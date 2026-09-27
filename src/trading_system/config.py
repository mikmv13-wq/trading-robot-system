from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class TInvestConfig:
    token_env: str
    base_url: str
    request_timeout_seconds: float
    requests_per_minute: int
    max_retries: int
    app_name: str


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    interval: str
    history_from: datetime
    request_window_hours: int
    overlap_minutes: int
    candle_source: str
    only_complete: bool


@dataclass(frozen=True, slots=True)
class StorageConfig:
    root_path: Path
    catalog_path: Path
    compression: str


@dataclass(frozen=True, slots=True)
class AggregationConfig:
    enabled: bool
    intervals: tuple[str, ...]
    run_after_collect: bool


@dataclass(frozen=True, slots=True)
class InstrumentConfig:
    instrument_id: str
    ticker: str | None
    enabled: bool


@dataclass(frozen=True, slots=True)
class Settings:
    t_invest: TInvestConfig
    collector: CollectorConfig
    storage: StorageConfig
    aggregations: AggregationConfig
    instruments: tuple[InstrumentConfig, ...]


def _parse_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("history_from must include timezone, preferably Z/UTC")
    return dt.astimezone(timezone.utc)


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    ti = _require(raw, "t_invest")
    collector = _require(raw, "collector")
    storage = _require(raw, "storage")
    aggregations = raw.get("aggregations") or {}
    raw_instruments = _require(raw, "instruments")

    settings = Settings(
        t_invest=TInvestConfig(
            token_env=str(ti.get("token_env", "T_INVEST_TOKEN")),
            base_url=str(ti.get("base_url", "https://invest-public-api.tbank.ru/rest")).rstrip("/"),
            request_timeout_seconds=float(ti.get("request_timeout_seconds", 20)),
            requests_per_minute=int(ti.get("requests_per_minute", 480)),
            max_retries=int(ti.get("max_retries", 6)),
            app_name=str(ti.get("app_name", "trading-robot-system")),
        ),
        collector=CollectorConfig(
            interval=str(collector.get("interval", "1m")),
            history_from=_parse_utc(str(_require(collector, "history_from"))),
            request_window_hours=int(collector.get("request_window_hours", 24)),
            overlap_minutes=int(collector.get("overlap_minutes", 5)),
            candle_source=str(collector.get("candle_source", "CANDLE_SOURCE_EXCHANGE")),
            only_complete=bool(collector.get("only_complete", True)),
        ),
        storage=StorageConfig(
            root_path=Path(storage.get("root_path", "data/market")),
            catalog_path=Path(storage.get("catalog_path", "data/trading.duckdb")),
            compression=str(storage.get("compression", "zstd")).lower(),
        ),
        aggregations=AggregationConfig(
            enabled=bool(aggregations.get("enabled", True)),
            intervals=tuple(
                str(item) for item in aggregations.get("intervals", ["15m", "30m", "1h"])
            ),
            run_after_collect=bool(aggregations.get("run_after_collect", True)),
        ),
        instruments=tuple(
            InstrumentConfig(
                instrument_id=str(_require(item, "instrument_id")),
                ticker=str(item["ticker"]) if item.get("ticker") else None,
                enabled=bool(item.get("enabled", True)),
            )
            for item in raw_instruments
        ),
    )

    if settings.collector.interval != "1m":
        raise ValueError("Current collector supports only collector.interval=1m")
    if not 1 <= settings.collector.request_window_hours <= 24:
        raise ValueError("request_window_hours must be between 1 and 24 for 1-minute candles")
    if settings.collector.overlap_minutes < 0:
        raise ValueError("overlap_minutes must be >= 0")
    if not 1 <= settings.t_invest.requests_per_minute <= 600:
        raise ValueError("requests_per_minute must be between 1 and 600")
    supported_compressions = {"uncompressed", "snappy", "gzip", "zstd", "brotli", "lz4", "lz4_raw"}
    if settings.storage.compression not in supported_compressions:
        raise ValueError(
            f"Unsupported Parquet compression: {settings.storage.compression}; "
            f"expected one of {sorted(supported_compressions)}"
        )
    supported_aggregations = {"15m", "30m", "1h"}
    unknown = set(settings.aggregations.intervals) - supported_aggregations
    if unknown:
        raise ValueError(f"Unsupported aggregation intervals: {sorted(unknown)}")
    if not settings.instruments:
        raise ValueError("At least one instrument must be configured")

    return settings
