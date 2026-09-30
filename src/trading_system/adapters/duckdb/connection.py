from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb


class DuckDBConnectionFactory:
    def connect(self, path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(database=str(path), read_only=read_only)

    @contextmanager
    def open(
        self,
        path: Path,
        *,
        read_only: bool = False,
    ) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = self.connect(path, read_only=read_only)
        try:
            yield connection
        finally:
            connection.close()
