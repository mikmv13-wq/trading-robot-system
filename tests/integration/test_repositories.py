import shutil
from pathlib import Path

import pytest

from trading_system.adapters.duckdb import (
    DatabaseIdentityError,
    DuckDBBootstrapper,
    DuckDBLiveRepository,
    DuckDBMarketRepository,
    DuckDBResearchRepository,
    RepositoryError,
)
from trading_system.application import BootstrapDatabasesUseCase
from trading_system.config import Settings


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


def test_repositories_report_health_schema_and_metadata(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)

    repositories = (
        (DuckDBMarketRepository(settings.market_db_path), "market"),
        (DuckDBResearchRepository(settings.research_db_path), "research"),
        (DuckDBLiveRepository(settings.live_db_path), "live"),
    )

    for repository, expected_kind in repositories:
        repository.healthcheck()

        assert repository.database_kind == expected_kind
        assert repository.schema_version() == (2 if expected_kind == "market" else 1)
        assert repository.metadata() == {
            "database_kind": expected_kind,
            "schema_baseline": "stage-0",
        }


def test_repository_rejects_wrong_database_file(tmp_path: Path) -> None:
    settings = _bootstrap(tmp_path)
    repository = DuckDBMarketRepository(settings.research_db_path)

    with pytest.raises(DatabaseIdentityError, match="expected 'market'"):
        repository.healthcheck()


def test_repository_wraps_missing_database_error(tmp_path: Path) -> None:
    repository = DuckDBLiveRepository(tmp_path / "missing.duckdb")

    with pytest.raises(RepositoryError, match="failed to access 'live'"):
        repository.healthcheck()

    assert not repository.path.exists()
