import shutil
from pathlib import Path

from trading_system.composition import build_application_services
from trading_system.config import Settings


class FakeSecretStorage:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_stage0_bootstrap_is_idempotent_and_services_are_healthy(tmp_path: Path) -> None:
    source_sql = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source_sql, sql_dir)

    settings = Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )
    services = build_application_services(
        settings,
        secret_storage=FakeSecretStorage(),
    )

    try:
        first = services.bootstrap_databases.execute()
        second = services.bootstrap_databases.execute()
        status = services.get_system_status.execute()

        assert first.applied_migrations == {
            "market": (1, 2),
            "research": (1,),
            "live": (1,),
        }
        assert second.applied_migrations == {
            "market": (),
            "research": (),
            "live": (),
        }
        assert status.healthy is True
        assert {database.name for database in status.databases} == {
            "market",
            "research",
            "live",
        }

        services.tinvest_token.set_token("session-only", persist=False)
        assert services.tinvest_token.get_token() == "session-only"
    finally:
        services.close()
