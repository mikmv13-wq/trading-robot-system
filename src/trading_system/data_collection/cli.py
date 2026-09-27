from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from trading_system.config import load_settings

from .aggregation import AggregateBuilder
from .collector import HistoricalCandleCollector
from .storage import ParquetCandleStorage
from .t_invest_client import TInvestMarketDataClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-data")
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="Collect raw 1-minute historical candles")
    collect.add_argument("--config", default="config/settings.yaml")

    aggregate = subparsers.add_parser("aggregate", help="Build 15m/30m/1h candles from raw 1m")
    aggregate.add_argument("--config", default="config/settings.yaml")
    aggregate.add_argument(
        "--all",
        action="store_true",
        help="Rebuild every raw monthly partition instead of only dirty partitions",
    )

    status = subparsers.add_parser("status", help="Show Parquet dataset status")
    status.add_argument("--config", default="config/settings.yaml")
    return parser


def _create_storage(settings) -> ParquetCandleStorage:
    storage = ParquetCandleStorage(
        settings.storage.root_path,
        settings.storage.catalog_path,
        compression=settings.storage.compression,
    )
    storage.initialize()
    return storage


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings(Path(args.config))
    storage = _create_storage(settings)

    if args.command == "status":
        rows = storage.stats()
        if not rows:
            print("Dataset is empty")
            return 0
        print("timeframe\tinstrument_id\trows\tfirst\tlast")
        for timeframe, instrument_id, count, first, last in rows:
            print(f"{timeframe}\t{instrument_id}\t{count}\t{first}\t{last}")
        return 0

    if args.command == "aggregate":
        if not settings.aggregations.enabled:
            print("Aggregations are disabled in config", file=sys.stderr)
            return 2
        totals = AggregateBuilder(storage, settings.aggregations.intervals).rebuild(
            all_partitions=args.all
        )
        print("aggregated: " + ", ".join(f"{key}={value}" for key, value in totals.items()))
        return 0

    token = os.getenv(settings.t_invest.token_env)
    if not token:
        print(
            f"Environment variable {settings.t_invest.token_env} is not set",
            file=sys.stderr,
        )
        return 2

    enabled = [instrument for instrument in settings.instruments if instrument.enabled]
    if not enabled:
        print("No enabled instruments in config", file=sys.stderr)
        return 2

    with TInvestMarketDataClient(
        token=token,
        base_url=settings.t_invest.base_url,
        timeout_seconds=settings.t_invest.request_timeout_seconds,
        requests_per_minute=settings.t_invest.requests_per_minute,
        max_retries=settings.t_invest.max_retries,
        app_name=settings.t_invest.app_name,
    ) as client:
        collector = HistoricalCandleCollector(
            client=client,
            storage=storage,
            config=settings.collector,
        )
        for instrument in enabled:
            result = collector.collect_instrument(instrument)
            print(
                f"{instrument.ticker or instrument.instrument_id}: "
                f"received={result.received}, saved={result.saved}"
            )

    if settings.aggregations.enabled and settings.aggregations.run_after_collect:
        totals = AggregateBuilder(storage, settings.aggregations.intervals).rebuild()
        print("aggregated: " + ", ".join(f"{key}={value}" for key, value in totals.items()))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
