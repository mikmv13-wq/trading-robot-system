from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from trading_system.ports import Repository


class HealthStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    name: str
    status: HealthStatus
    schema_version: int | None
    metadata: Mapping[str, str]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SystemStatus:
    databases: tuple[DatabaseStatus, ...]

    @property
    def healthy(self) -> bool:
        return all(database.status is HealthStatus.OK for database in self.databases)


class GetSystemStatusUseCase:
    """Collect storage health without exposing DuckDB details to callers."""

    def __init__(self, repositories: Mapping[str, Repository]) -> None:
        self._repositories = dict(repositories)

    def execute(self) -> SystemStatus:
        statuses = tuple(
            self._database_status(name, repository)
            for name, repository in self._repositories.items()
        )
        return SystemStatus(databases=statuses)

    @staticmethod
    def _database_status(name: str, repository: Repository) -> DatabaseStatus:
        try:
            repository.healthcheck()
            schema_version = repository.schema_version()
            metadata = dict(repository.metadata())
        except Exception as exc:
            return DatabaseStatus(
                name=name,
                status=HealthStatus.ERROR,
                schema_version=None,
                metadata={},
                error=f"{type(exc).__name__}: {exc}",
            )

        return DatabaseStatus(
            name=name,
            status=HealthStatus.OK,
            schema_version=schema_version,
            metadata=metadata,
        )
