from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Local application settings.

    Secrets are intentionally excluded. Broker credentials are provided by
    the OS keychain adapter.
    """

    model_config = SettingsConfigDict(
        env_prefix="TRADING_SYSTEM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("data"))
    log_dir: Path = Field(default=Path("logs"))
    sql_dir: Path = Field(default=Path("sql"))
    config_dir: Path = Field(default=Path("config"))
    ca_bundle_path: Path | None = Field(default=None)
    log_level: LogLevel = "INFO"

    @property
    def market_db_path(self) -> Path:
        return self.data_dir / "market.duckdb"

    @property
    def research_db_path(self) -> Path:
        return self.data_dir / "research.duckdb"

    @property
    def live_db_path(self) -> Path:
        return self.data_dir / "live.duckdb"

    @property
    def universe_config_path(self) -> Path:
        return self.config_dir / "universe.toml"

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def persist_ca_bundle_path(
        self,
        path: Path | None,
        *,
        env_path: Path = Path(".env"),
    ) -> None:
        key = "TRADING_SYSTEM_CA_BUNDLE_PATH"
        lines: list[str] = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        filtered = [
            line
            for line in lines
            if not line.lstrip().startswith(f"{key}=")
        ]
        if path is not None:
            normalized = path.expanduser().resolve()
            filtered.append(f"{key}={normalized.as_posix()}")
            self.ca_bundle_path = normalized
        else:
            self.ca_bundle_path = None

        content = "\n".join(filtered).rstrip()
        if content:
            content += "\n"
        env_path.write_text(content, encoding="utf-8")
