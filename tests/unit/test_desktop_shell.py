import os
import time
from collections.abc import Callable, Mapping

from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
)

from trading_system.application import GetSystemStatusUseCase, JobApplicationService
from trading_system.infrastructure import ThreadJobManager
from trading_system.ui.main_window import NAVIGATION, MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeRepository:
    def __init__(
        self,
        kind: str,
        *,
        error: Exception | None = None,
    ) -> None:
        self._kind = kind
        self._error = error

    def healthcheck(self) -> None:
        if self._error is not None:
            raise self._error

    def schema_version(self) -> int:
        return 1

    def metadata(self) -> Mapping[str, str]:
        return {
            "database_kind": self._kind,
            "schema_baseline": "stage-0",
        }


def _qt_app() -> QApplication:
    instance = QApplication.instance()
    if instance is not None:
        return instance
    return QApplication([])


def _status_use_case() -> GetSystemStatusUseCase:
    return GetSystemStatusUseCase(
        {
            "market": FakeRepository("market"),
            "research": FakeRepository("research"),
            "live": FakeRepository("live"),
        }
    )


def _jobs(
    *,
    sleeper: Callable[[float], None] | None = None,
) -> tuple[ThreadJobManager, JobApplicationService]:
    manager = ThreadJobManager(max_workers=1)
    service = JobApplicationService(manager, sleeper=sleeper or time.sleep)
    return manager, service


def test_main_window_contains_all_roadmap_pages() -> None:
    qt_app = _qt_app()
    manager, jobs = _jobs(sleeper=lambda _: None)
    window = MainWindow(_status_use_case(), jobs)

    try:
        navigation = window.findChild(QListWidget, "navigationList")
        stack = window.findChild(QStackedWidget, "pageStack")

        assert navigation is not None
        assert stack is not None
        assert navigation.count() == len(NAVIGATION) == 10
        assert stack.count() == len(NAVIGATION)

        labels = [navigation.item(index).text() for index in range(navigation.count())]
        assert labels == [entry.label for entry in NAVIGATION]

        navigation.setCurrentRow(3)
        qt_app.processEvents()

        assert window.current_page_key() == "backtest"
        current_widget = stack.currentWidget()
        assert current_widget is not None
        assert current_widget.objectName() == "page-backtest"
    finally:
        window.close()
        manager.shutdown()


def test_dashboard_renders_database_status_from_application_layer() -> None:
    _qt_app()
    manager, jobs = _jobs(sleeper=lambda _: None)
    window = MainWindow(_status_use_case(), jobs)

    try:
        table = window.findChild(QTableWidget, "databaseStatusTable")

        assert table is not None
        assert table.rowCount() == 3
        assert table.item(0, 0).text() == "market"
        assert table.item(0, 1).text() == "OK"
        assert table.item(0, 2).text() == "1"
        assert table.item(0, 3).text() == "stage-0"
    finally:
        window.close()
        manager.shutdown()


def test_dashboard_stays_operational_when_database_status_fails() -> None:
    _qt_app()
    use_case = GetSystemStatusUseCase(
        {
            "market": FakeRepository("market", error=RuntimeError("unavailable")),
            "research": FakeRepository("research"),
            "live": FakeRepository("live"),
        }
    )
    manager, jobs = _jobs(sleeper=lambda _: None)
    window = MainWindow(use_case, jobs)

    try:
        table = window.findChild(QTableWidget, "databaseStatusTable")

        assert table is not None
        assert table.item(0, 1).text() == "ERROR"
        assert "unavailable" in table.item(0, 1).toolTip()
    finally:
        window.close()
        manager.shutdown()


def test_background_test_job_does_not_block_navigation() -> None:
    qt_app = _qt_app()
    manager, jobs = _jobs()
    window = MainWindow(_status_use_case(), jobs)

    try:
        run_button = window.findChild(QPushButton, "runTestJob")
        navigation = window.findChild(QListWidget, "navigationList")
        progress = window.findChild(QProgressBar, "jobProgress")

        assert run_button is not None
        assert navigation is not None
        assert progress is not None

        run_button.click()
        navigation.setCurrentRow(2)
        qt_app.processEvents()

        assert window.current_page_key() == "charts"
        assert 0 <= progress.value() <= 100
    finally:
        window.close()
        manager.shutdown(wait=True, cancel_running=True)
