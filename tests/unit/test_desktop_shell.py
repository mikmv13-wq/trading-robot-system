import os
from collections.abc import Mapping

from PySide6.QtWidgets import QApplication, QListWidget, QStackedWidget, QTableWidget

from trading_system.application import GetSystemStatusUseCase
from trading_system.ui.main_window import MainWindow, NAVIGATION

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


def test_main_window_contains_all_roadmap_pages() -> None:
    qt_app = _qt_app()
    window = MainWindow(_status_use_case())

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

    window.close()


def test_dashboard_renders_database_status_from_application_layer() -> None:
    _qt_app()
    window = MainWindow(_status_use_case())

    table = window.findChild(QTableWidget, "databaseStatusTable")

    assert table is not None
    assert table.rowCount() == 3
    assert table.item(0, 0).text() == "market"
    assert table.item(0, 1).text() == "OK"
    assert table.item(0, 2).text() == "1"
    assert table.item(0, 3).text() == "stage-0"

    window.close()


def test_dashboard_stays_operational_when_database_status_fails() -> None:
    _qt_app()
    use_case = GetSystemStatusUseCase(
        {
            "market": FakeRepository("market", error=RuntimeError("unavailable")),
            "research": FakeRepository("research"),
            "live": FakeRepository("live"),
        }
    )
    window = MainWindow(use_case)

    table = window.findChild(QTableWidget, "databaseStatusTable")

    assert table is not None
    assert table.item(0, 1).text() == "ERROR"
    assert "unavailable" in table.item(0, 1).toolTip()

    window.close()
