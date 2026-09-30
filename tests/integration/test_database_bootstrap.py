import shutil
from pathlib import Path

import duckdb

from trading_system.adapters.duckdb import DuckDBBootstrapper
from trading_system.application import BootstrapDatabasesUseCase
from trading_system.config import Settings


def _copy_migrations(target: Path) -> None:
    source = Path(__file__).parents[2] / "sql"
    shutil.copytree(source, target)


def test_bootstrap_creates_three_databases_and_is_idempotent(tmp_path: Path) -> None:
    sql_dir = tmp_path / "sql"
    _copy_migrations(sql_dir)
    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )
    use_case = BootstrapDatabasesUseCase(DuckDBBootstrapper(settings))

    first = use_case.execute()
    second = use_case.execute()

    assert first.applied_migrations == {
        "market": (1, 2),
        "research": (1,),
        "live": (1,),
    }
    assert second.applied_migrations == {
        "market": (),
        "research": (),
        "live": (),
    }

    for kind, path in {
        "market": settings.market_db_path,
        "research": settings.research_db_path,
        "live": settings.live_db_path,
    }.items():
        assert path.exists()
        connection = duckdb.connect(str(path), read_only=True)
        try:
            migrations = connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
            metadata = dict(
                connection.execute(
                    "SELECT key, value FROM database_metadata"
                ).fetchall()
            )
        finally:
            connection.close()

        expected_migrations = (
            [(1, "init"), (2, "market_data")]
            if kind == "market"
            else [(1, "init")]
        )
        assert migrations == expected_migrations
        assert metadata["database_kind"] == kind
        assert metadata["schema_baseline"] == "stage-0"
