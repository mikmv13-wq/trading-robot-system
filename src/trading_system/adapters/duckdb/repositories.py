from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import duckdb

from trading_system.adapters.duckdb.connection import DuckDBConnectionFactory


class RepositoryError(RuntimeError):
    """Base error for DuckDB repository access."""


class DatabaseIdentityError(RepositoryError):
    """Raised when a repository is wired to the wrong DuckDB file."""


class DuckDBRepository:
    """Shared read-side foundation for the three DuckDB repositories.

    Repository methods intentionally use short-lived read-only connections.
    Write ownership and transaction boundaries are introduced by the use cases
    that need them in later stages.
    """

    def __init__(
        self,
        path: Path,
        expected_kind: str,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        self._path = path
        self._expected_kind = expected_kind
        self._connection_factory = connection_factory or DuckDBConnectionFactory()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def database_kind(self) -> str:
        return self._expected_kind

    def healthcheck(self) -> None:
        with self._verified_connection() as connection:
            connection.execute("SELECT 1").fetchone()
            self._schema_version(connection)

    def schema_version(self) -> int:
        with self._verified_connection() as connection:
            return self._schema_version(connection)

    def metadata(self) -> Mapping[str, str]:
        with self._verified_connection() as connection:
            return self._read_metadata(connection)

    @contextmanager
    def _verified_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        try:
            with self._connection_factory.open(self._path, read_only=True) as connection:
                metadata = self._read_metadata(connection)
                actual_kind = metadata.get("database_kind")
                if actual_kind != self._expected_kind:
                    raise DatabaseIdentityError(
                        f"expected {self._expected_kind!r} database at {self._path}, "
                        f"found {actual_kind!r}"
                    )
                yield connection
        except RepositoryError:
            raise
        except Exception as exc:
            raise RepositoryError(
                f"failed to access {self._expected_kind!r} database at {self._path}"
            ) from exc

    @staticmethod
    def _read_metadata(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
        rows = connection.execute(
            "SELECT key, value FROM database_metadata ORDER BY key"
        ).fetchall()
        return {str(key): str(value) for key, value in rows}

    @staticmethod
    def _schema_version(connection: duckdb.DuckDBPyConnection) -> int:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        if row is None:
            raise RepositoryError("schema_migrations query returned no row")
        value = row[0]
        return 0 if value is None else int(value)


class DuckDBMarketRepository(DuckDBRepository):
    def __init__(
        self,
        path: Path,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        super().__init__(path, "market", connection_factory)


class DuckDBResearchRepository(DuckDBRepository):
    def __init__(
        self,
        path: Path,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        super().__init__(path, "research", connection_factory)


class DuckDBLiveRepository(DuckDBRepository):
    def __init__(
        self,
        path: Path,
        connection_factory: DuckDBConnectionFactory | None = None,
    ) -> None:
        super().__init__(path, "live", connection_factory)
