from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Local application settings.

    Secrets are intentionally excluded. Broker credentials will be provided by
    the OS keychain adapter in a later stage.
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

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
