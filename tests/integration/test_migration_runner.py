from pathlib import Path

import duckdb
import pytest

from trading_system.adapters.duckdb import MigrationError, MigrationRunner


def test_failed_migration_is_rolled_back_and_not_recorded(tmp_path: Path) -> None:
    migration_dir = tmp_path / "sql"
    migration_dir.mkdir()
    (migration_dir / "001_init.sql").write_text(
        "CREATE TABLE sample(id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )
    (migration_dir / "002_broken.sql").write_text(
        "CREATE TABLE should_rollback(id INTEGER); INVALID SQL;",
        encoding="utf-8",
    )

    connection = duckdb.connect(str(tmp_path / "test.duckdb"))
    try:
        with pytest.raises(MigrationError, match="002_broken"):
            MigrationRunner(connection, migration_dir).migrate()

        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert versions == [(1,)]
    assert "sample" in tables
    assert "should_rollback" not in tables
