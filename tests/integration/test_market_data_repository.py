import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import BootstrapDatabasesUseCase
from trading_system.config import Settings
from trading_system.domain import Candle1m, Instrument, Universe


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
