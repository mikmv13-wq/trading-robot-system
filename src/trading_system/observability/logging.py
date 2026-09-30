from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_system.config import Settings


class JsonFormatter(logging.Formatter):
    """Small dependency-free JSON formatter for application logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings) -> Path:
    """Configure console and JSON file logging and return the log file path."""

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.log_dir / "trading-system.jsonl"

    formatter = JsonFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.log_level)
    root.addHandler(console)
    root.addHandler(file_handler)

    return log_file
