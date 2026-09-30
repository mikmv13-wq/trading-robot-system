from trading_system.application import (
    TInvestTokenService,
    TokenSource,
    TokenStorageError,
)
from trading_system.ports import SecretStorageError


class FakeSecretStorage:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.unavailable = unavailable

    def get(self, key: str) -> str | None:
        if self.unavailable:
            raise SecretStorageError("unavailable")
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        if self.unavailable:
            raise SecretStorageError("unavailable")
        self.values[key] = value

    def delete(self, key: str) -> None:
        if self.unavailable:
            raise SecretStorageError("unavailable")
        self.values.pop(key, None)


def test_session_token_never_writes_secret_storage() -> None:
    storage = FakeSecretStorage()
    service = TInvestTokenService(storage)

    service.set_token(" session-token ", persist=False)

    status = service.status()
    assert status.configured is True
    assert status.source is TokenSource.SESSION
    assert storage.values == {}
    assert service.get_token() == "session-token"


def test_persisted_token_uses_secret_storage() -> None:
    storage = FakeSecretStorage()
    service = TInvestTokenService(storage)

    service.set_token("persisted-token", persist=True)

    assert storage.values[service.TOKEN_KEY] == "persisted-token"
    assert service.status().source is TokenSource.KEYCHAIN
    assert service.get_token() == "persisted-token"

    service.clear()
    assert service.status().configured is False
    assert storage.values == {}


def test_keychain_unavailability_is_reported_without_crashing_status() -> None:
    storage = FakeSecretStorage(unavailable=True)
    service = TInvestTokenService(storage)

    status = service.status()

    assert status.configured is False
    assert status.source is TokenSource.NONE
    assert status.keychain_available is False
    assert status.error == "unavailable"


def test_persist_failure_is_normalized() -> None:
    storage = FakeSecretStorage(unavailable=True)
    service = TInvestTokenService(storage)

    try:
        service.set_token("secret", persist=True)
    except TokenStorageError as exc:
        assert str(exc) == "Unable to save token in OS keychain"
    else:
        raise AssertionError("TokenStorageError was not raised")
