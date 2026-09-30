import shutil
from pathlib import Path

from trading_system.composition import build_application_services
from trading_system.config import Settings


def _settings(tmp_path: Path) -> Settings:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)
    return Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )


def test_composed_services_bootstrap_then_report_healthy_status(tmp_path: Path) -> None:
    services = build_application_services(_settings(tmp_path))

    bootstrap = services.bootstrap_databases.execute()
    status = services.get_system_status.execute()

    assert bootstrap.applied_migrations == {
        "market": (1,),
        "research": (1,),
        "live": (1,),
    }
    assert status.healthy is True
    assert [database.name for database in status.databases] == [
        "market",
        "research",
        "live",
    ]
    assert all(database.schema_version == 1 for database in status.databases)
