from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

_MIGRATION_PATTERN = re.compile(r"^(?P<version>\d+)_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path


class MigrationRunner:
    def __init__(self, connection: duckdb.DuckDBPyConnection, migration_dir: Path) -> None:
        self._connection = connection
        self._migration_dir = migration_dir

    def migrate(self) -> tuple[int, ...]:
        migrations = self._discover()
        self._ensure_history_table()
        applied = self._applied_versions()

        applied_now: list[int] = []
        for migration in migrations:
            if migration.version in applied:
                continue
            self._apply(migration)
            applied_now.append(migration.version)
        return tuple(applied_now)

    def _discover(self) -> tuple[Migration, ...]:
        if not self._migration_dir.is_dir():
            raise MigrationError(f"migration directory does not exist: {self._migration_dir}")

        migrations: list[Migration] = []
        versions: set[int] = set()
        for path in sorted(self._migration_dir.glob("*.sql")):
            match = _MIGRATION_PATTERN.fullmatch(path.name)
            if match is None:
                raise MigrationError(f"invalid migration filename: {path.name}")
            version = int(match.group("version"))
            if version in versions:
                raise MigrationError(f"duplicate migration version {version}: {path.name}")
            versions.add(version)
            migrations.append(Migration(version, match.group("name"), path))

        return tuple(sorted(migrations, key=lambda item: item.version))

    def _ensure_history_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name VARCHAR NOT NULL,
                applied_at TIMESTAMP NOT NULL
            )
            """
        )

    def _applied_versions(self) -> set[int]:
        rows = self._connection.execute("SELECT version FROM schema_migrations").fetchall()
        return {int(row[0]) for row in rows}

    def _apply(self, migration: Migration) -> None:
        sql = migration.path.read_text(encoding="utf-8")
        try:
            self._connection.execute("BEGIN TRANSACTION")
            self._connection.execute(sql)
            self._connection.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                [migration.version, migration.name],
            )
            self._connection.execute("COMMIT")
        except Exception as exc:
            self._connection.execute("ROLLBACK")
            raise MigrationError(
                f"failed to apply migration {migration.version}_{migration.name}"
            ) from exc
