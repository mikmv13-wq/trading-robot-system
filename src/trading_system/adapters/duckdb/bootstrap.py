from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from trading_system.adapters.duckdb.connection import DuckDBConnectionFactory
from trading_system.adapters.duckdb.migrations import MigrationRunner
from trading_system.config import Settings


@dataclass(frozen=True, slots=True)
class DatabaseSpec:
    name: str
    path: Path
    migration_dir: Path


class DuckDBBootstrapper:
    def __init__(
        self,
        settings: Settings,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        self._settings = settings
        self._connection_factory = connection_factory or DuckDBConnectionFactory()

    def bootstrap(self) -> Mapping[str, Sequence[int]]:
        self._settings.ensure_runtime_directories()
        result: dict[str, tuple[int, ...]] = {}

        for spec in self._database_specs():
            connection = self._connection_factory.connect(spec.path)
            try:
                result[spec.name] = MigrationRunner(connection, spec.migration_dir).migrate()
            finally:
                connection.close()

        return result

    def _database_specs(self) -> tuple[DatabaseSpec, ...]:
        return (
            DatabaseSpec(
                "market",
                self._settings.market_db_path,
                self._settings.sql_dir / "market",
            ),
            DatabaseSpec(
                "research",
                self._settings.research_db_path,
                self._settings.sql_dir / "research",
            ),
            DatabaseSpec(
                "live",
                self._settings.live_db_path,
                self._settings.sql_dir / "live",
            ),
        )
