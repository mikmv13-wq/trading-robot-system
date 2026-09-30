from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trading_system.ports import SecretStorage, SecretStorageError


class TokenSource(StrEnum):
    NONE = "NONE"
    SESSION = "SESSION"
    KEYCHAIN = "KEYCHAIN"


class TokenStorageError(RuntimeError):
    """Application-level error for T-Invest token storage operations."""


@dataclass(frozen=True, slots=True)
class TInvestTokenStatus:
    configured: bool
    source: TokenSource
    keychain_available: bool
    error: str | None = None


class TInvestTokenService:
    """Owns T-Invest token access without exposing secrets to settings or logs."""

    TOKEN_KEY = "tinvest-api-token"

    def __init__(self, secret_storage: SecretStorage) -> None:
        self._secret_storage = secret_storage
        self._session_token: str | None = None

    def status(self) -> TInvestTokenStatus:
        stored_token: str | None = None
        keychain_available = True
        error: str | None = None

        try:
            stored_token = self._secret_storage.get(self.TOKEN_KEY)
        except SecretStorageError as exc:
            keychain_available = False
            error = str(exc)

        if self._session_token is not None:
            return TInvestTokenStatus(
                configured=True,
                source=TokenSource.SESSION,
                keychain_available=keychain_available,
                error=error,
            )

        if stored_token:
            return TInvestTokenStatus(
                configured=True,
                source=TokenSource.KEYCHAIN,
                keychain_available=keychain_available,
                error=error,
            )

        return TInvestTokenStatus(
            configured=False,
            source=TokenSource.NONE,
            keychain_available=keychain_available,
            error=error,
        )

    def set_token(self, token: str, *, persist: bool) -> None:
        normalized = token.strip()
        if not normalized:
            raise ValueError("T-Invest token must not be empty")

        if persist:
            try:
                self._secret_storage.set(self.TOKEN_KEY, normalized)
            except SecretStorageError as exc:
                raise TokenStorageError("Unable to save token in OS keychain") from exc
            self._session_token = None
            return

        self._session_token = normalized

    def clear(self) -> None:
        self._session_token = None
        try:
            self._secret_storage.delete(self.TOKEN_KEY)
        except SecretStorageError as exc:
            raise TokenStorageError("Unable to remove token from OS keychain") from exc

    def get_token(self) -> str | None:
        if self._session_token is not None:
            return self._session_token
        try:
            return self._secret_storage.get(self.TOKEN_KEY)
        except SecretStorageError as exc:
            raise TokenStorageError("Unable to read token from OS keychain") from exc
