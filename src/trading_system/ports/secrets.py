from __future__ import annotations

from typing import Protocol


class SecretStorageError(RuntimeError):
    """Normalized error raised by secret-storage adapters."""


class SecretStorage(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...
