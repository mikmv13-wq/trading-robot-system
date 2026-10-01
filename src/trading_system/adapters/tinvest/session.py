from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from threading import RLock
from typing import Any, TypeVar, cast

from trading_system.adapters.tinvest.errors import (
    TInvestAuthenticationError,
    TInvestResponseError,
)
from trading_system.adapters.tinvest.sdk import Client, RequestError

T = TypeVar("T")
ClientFactory = Callable[[str], AbstractContextManager[Any]]


def _default_client_factory(token: str) -> AbstractContextManager[Any]:
    return cast(AbstractContextManager[Any], Client(token))


class TInvestGrpcSession:
    """Own one reusable T-Invest SDK gRPC channel for application adapters."""

    def __init__(
        self,
        token_provider: Callable[[], str | None],
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._client_factory = client_factory or _default_client_factory
        self._lock = RLock()
        self._token: str | None = None
        self._manager: AbstractContextManager[Any] | None = None
        self._client: Any | None = None

    def execute(self, operation: Callable[[Any], T]) -> T:
        with self._lock:
            client = self._ensure_client_locked()
            try:
                return operation(client)
            except RequestError as exc:
                raise TInvestResponseError(self._request_error_message(exc)) from exc

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _ensure_client_locked(self) -> Any:
        token = self._token_provider()
        if token is None or not token.strip():
            raise TInvestAuthenticationError("T-Invest token is not configured")
        normalized = token.strip()

        if self._client is not None and self._token == normalized:
            return self._client

        self._close_locked()
        manager = self._client_factory(normalized)
        try:
            client = manager.__enter__()
        except RequestError as exc:
            raise TInvestResponseError(self._request_error_message(exc)) from exc

        self._token = normalized
        self._manager = manager
        self._client = client
        return client

    def _close_locked(self) -> None:
        manager = self._manager
        self._token = None
        self._manager = None
        self._client = None
        if manager is not None:
            manager.__exit__(None, None, None)

    @staticmethod
    def _request_error_message(error: RequestError) -> str:
        detail = str(error)
        normalized = detail.lower()
        tls_markers = (
            "certificate_verify_failed",
            "certificate verify failed",
            "handshake failed",
            "tls handshake",
        )
        if any(marker in normalized for marker in tls_markers):
            return (
                "T-Invest gRPC TLS handshake failed even though SDK certificate "
                "verification is enabled (SSL_TBANK_VERIFY=True): "
                f"{detail}. Check whether a proxy or antivirus is intercepting TLS."
            )
        return f"T-Invest gRPC request failed: {detail}"
