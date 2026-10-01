from pathlib import Path

from trading_system.config import Settings


def test_database_paths_are_derived_from_data_dir(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "db",
        log_dir=tmp_path / "logs",
        sql_dir=tmp_path / "sql",
        config_dir=tmp_path / "config",
    )

    assert settings.market_db_path == tmp_path / "db" / "market.duckdb"
    assert settings.research_db_path == tmp_path / "db" / "research.duckdb"
    assert settings.live_db_path == tmp_path / "db" / "live.duckdb"
    assert settings.universe_config_path == tmp_path / "config" / "universe.toml"



def test_custom_ca_path_is_persisted_and_cleared(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TRADING_SYSTEM_LOG_LEVEL=DEBUG\nOTHER_SETTING=value\n",
        encoding="utf-8",
    )
    ca_path = tmp_path / "corporate-root.pem"
    ca_path.write_text("dummy", encoding="utf-8")

    settings = Settings()
    settings.persist_ca_bundle_path(ca_path, env_path=env_path)

    text = env_path.read_text(encoding="utf-8")
    assert "TRADING_SYSTEM_LOG_LEVEL=DEBUG" in text
    assert "OTHER_SETTING=value" in text
    assert (
        f"TRADING_SYSTEM_CA_BUNDLE_PATH={ca_path.resolve().as_posix()}"
        in text
    )
    assert settings.ca_bundle_path == ca_path.resolve()

    settings.persist_ca_bundle_path(None, env_path=env_path)

    text = env_path.read_text(encoding="utf-8")
    assert "TRADING_SYSTEM_CA_BUNDLE_PATH" not in text
    assert settings.ca_bundle_path is None
