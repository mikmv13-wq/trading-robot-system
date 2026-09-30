import shutil
from pathlib import Path

import pytest

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import (
    BootstrapDatabasesUseCase,
    InstrumentSyncError,
    SyncInstrumentsUseCase,
)
from trading_system.config import FileUniverseConfig, Settings
from trading_system.domain import Instrument


class FakeInstrumentsClient:
    def __init__(self, instruments: tuple[Instrument, ...]) -> None:
        self._instruments = instruments

    def list_shares(self) -> tuple[Instrument, ...]:
        return self._instruments


def _bootstrap(tmp_path: Path) -> tuple[Settings, DuckDBMarketRepository]:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)
    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
        config_dir=tmp_path / "config",
    )
    BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    return settings, DuckDBMarketRepository(settings.market_db_path)


def _write_universe(settings: Settings, tickers: list[str]) -> None:
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    quoted = ", ".join(f'"{ticker}"' for ticker in tickers)
    settings.universe_config_path.write_text(
        f'[universes.default]\nname = "Default"\ntickers = [{quoted}]\n',
        encoding="utf-8",
    )


def test_sync_instruments_resolves_uid_and_persists_universe(tmp_path: Path) -> None:
    settings, repository = _bootstrap(tmp_path)
    _write_universe(settings, ["SBER", "GAZP"])
    broker_instruments = (
        Instrument(
            instrument_uid="uid-sber",
            ticker="SBER",
            lot_size=10,
            exchange="MOEX",
            active=True,
        ),
        Instrument(
            instrument_uid="uid-gazp",
            ticker="GAZP",
            lot_size=10,
            exchange="MOEX",
            active=True,
        ),
    )

    result = SyncInstrumentsUseCase(
        FileUniverseConfig(settings.universe_config_path),
        FakeInstrumentsClient(broker_instruments),
        repository,
    ).execute()

    assert result.instruments == broker_instruments
    assert repository.list_instruments() == (
        broker_instruments[1],
        broker_instruments[0],
    )
    assert repository.get_universe("default") == result.universe
    assert set(result.universe.instrument_uids) == {"uid-sber", "uid-gazp"}


def test_sync_instruments_does_not_write_partial_universe(tmp_path: Path) -> None:
    settings, repository = _bootstrap(tmp_path)
    _write_universe(settings, ["SBER", "MISSING"])

    use_case = SyncInstrumentsUseCase(
        FileUniverseConfig(settings.universe_config_path),
        FakeInstrumentsClient(
            (
                Instrument(
                    instrument_uid="uid-sber",
                    ticker="SBER",
                    lot_size=10,
                    active=True,
                ),
            )
        ),
        repository,
    )

    with pytest.raises(InstrumentSyncError, match="MISSING: not found"):
        use_case.execute()

    assert repository.list_instruments() == ()
    assert repository.get_universe("default") is None


def test_sync_instruments_rejects_ambiguous_active_ticker(tmp_path: Path) -> None:
    settings, repository = _bootstrap(tmp_path)
    _write_universe(settings, ["SBER"])

    use_case = SyncInstrumentsUseCase(
        FileUniverseConfig(settings.universe_config_path),
        FakeInstrumentsClient(
            (
                Instrument("uid-1", "SBER", 10, active=True),
                Instrument("uid-2", "SBER", 10, active=True),
            )
        ),
        repository,
    )

    with pytest.raises(InstrumentSyncError, match="ambiguous"):
        use_case.execute()

    assert repository.list_instruments() == ()
