from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from trading_system.composition import ApplicationServices, build_application_services
from trading_system.config import Settings
from trading_system.observability import configure_logging
from trading_system.ui import MainWindow
from trading_system.ui.theme import apply_theme


def create_main_window(
    services: ApplicationServices,
    settings: Settings | None = None,
) -> MainWindow:
    """Build the desktop window using already-composed application services."""

    return MainWindow(
        services.get_system_status,
        services.jobs,
        services.tinvest_token,
        services.data,
        settings,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Desktop application entry point."""

    settings = Settings()
    configure_logging(settings)

    qt_app = QApplication(list(argv) if argv is not None else sys.argv)
    qt_app.setApplicationName("Trading Robot System")
    qt_app.setOrganizationName("Trading Robot System")
    apply_theme(qt_app)

    services = build_application_services(settings)
    qt_app.aboutToQuit.connect(services.close)

    window = create_main_window(services, settings)
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
