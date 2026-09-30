import keyring
import pytest
from keyring.errors import NoKeyringError, PasswordDeleteError

from trading_system.adapters.keychain import KeyringSecretStorage
from trading_system.ports import SecretStorageError


def test_keyring_adapter_delegates_without_exposing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[tuple[str, str], str] = {}

    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda service, key: values.get((service, key)),
    )
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda service, key, value: values.__setitem__((service, key), value),
    )
    monkeypatch.setattr(
        keyring,
        "delete_password",
        lambda service, key: values.pop((service, key), None),
    )

    storage = KeyringSecretStorage("test-service")
    storage.set("token", "super-secret")

    assert storage.get("token") == "super-secret"

    storage.delete("token")
    assert storage.get("token") is None


def test_keyring_backend_error_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get(service: str, key: str) -> str | None:
        raise NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", fail_get)
    storage = KeyringSecretStorage("test-service")

    with pytest.raises(SecretStorageError, match="OS keychain is unavailable"):
        storage.get("token")


def test_delete_missing_secret_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(service: str, key: str) -> None:
        raise PasswordDeleteError("missing")

    monkeypatch.setattr(keyring, "delete_password", missing)
    storage = KeyringSecretStorage("test-service")

    storage.delete("token")
