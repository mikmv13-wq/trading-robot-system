from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from trading_system.composition import build_application_services
from trading_system.config import Settings
from trading_system.observability import configure_logging
from trading_system.ui import MainWindow


def create_main_window(settings: Settings | None = None) -> MainWindow:
    """Build the desktop window through the shared application composition root."""

    resolved_settings = settings or Settings()
    services = build_application_services(resolved_settings)
    return MainWindow(services.get_system_status)


def main(argv: Sequence[str] | None = None) -> int:
    """Desktop application entry point."""

    settings = Settings()
    configure_logging(settings)

    qt_app = QApplication(list(argv) if argv is not None else sys.argv)
    qt_app.setApplicationName("Trading Robot System")
    qt_app.setOrganizationName("Trading Robot System")

    window = create_main_window(settings)
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
