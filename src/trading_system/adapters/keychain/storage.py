from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from trading_system.ports import SecretStorageError


class KeyringSecretStorage:
    """OS credential/keychain-backed secret storage."""

    def __init__(self, service_name: str = "trading-robot-system") -> None:
        if not service_name.strip():
            raise ValueError("service_name must not be empty")
        self._service_name = service_name

    def get(self, key: str) -> str | None:
        self._validate_key(key)
        try:
            return keyring.get_password(self._service_name, key)
        except KeyringError as exc:
            raise SecretStorageError("OS keychain is unavailable") from exc

    def set(self, key: str, value: str) -> None:
        self._validate_key(key)
        if not value:
            raise ValueError("secret value must not be empty")
        try:
            keyring.set_password(self._service_name, key, value)
        except KeyringError as exc:
            raise SecretStorageError("OS keychain is unavailable") from exc

    def delete(self, key: str) -> None:
        self._validate_key(key)
        try:
            keyring.delete_password(self._service_name, key)
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise SecretStorageError("OS keychain is unavailable") from exc

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key.strip():
            raise ValueError("secret key must not be empty")
