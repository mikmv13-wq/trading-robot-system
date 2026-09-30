from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trading_system.application import (
    DataApplicationService,
    GetSystemStatusUseCase,
    JobApplicationService,
    TInvestTokenService,
)
from trading_system.ui.pages import DataPage, DashboardPage, PlaceholderPage, SettingsPage


@dataclass(frozen=True, slots=True)
class NavigationEntry:
    key: str
    label: str
    description: str


NAVIGATION: tuple[NavigationEntry, ...] = (
    NavigationEntry("dashboard", "Dashboard", "Общее состояние приложения."),
    NavigationEntry("data", "Data", "Инструменты, история и качество данных."),
    NavigationEntry("charts", "Charts", "Просмотр свечей и результатов стратегии."),
    NavigationEntry("backtest", "Backtest", "Запуск и анализ backtest."),
    NavigationEntry("optimization", "Optimization", "Подбор устойчивых параметров."),
    NavigationEntry("validation", "Validation", "Финальная holdout validation."),
    NavigationEntry("strategies", "Strategies", "Strategy Registry."),
    NavigationEntry("trading", "Trading", "Sandbox и production runtime."),
    NavigationEntry("logs", "Logs", "Журнал событий приложения."),
    NavigationEntry("settings", "Settings", "Настройки desktop-приложения."),
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        get_system_status: GetSystemStatusUseCase,
        jobs: JobApplicationService,
        tinvest_token: TInvestTokenService | None = None,
        data: DataApplicationService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle("Trading Robot System")
        self.resize(1200, 760)
        self.setMinimumSize(960, 640)

        central = QWidget()
        central.setObjectName("centralShell")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFrameShape(QFrame.Shape.StyledPanel)
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(260)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 16)
        sidebar_layout.setSpacing(12)

        product_label = QLabel("Trading Robot System")
        product_label.setObjectName("productName")
        product_label.setWordWrap(True)
        product_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        sidebar_layout.addWidget(product_label)

        self._navigation = QListWidget()
        self._navigation.setObjectName("navigationList")
        self._navigation.setFrameShape(QFrame.Shape.NoFrame)
        self._navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        sidebar_layout.addWidget(self._navigation, 1)

        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")

        for entry in NAVIGATION:
            item = QListWidgetItem(entry.label)
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            self._navigation.addItem(item)

            page: QWidget
            if entry.key == "dashboard":
                page = DashboardPage(get_system_status, jobs)
            elif entry.key == "data":
                page = DataPage(data)
            elif entry.key == "settings":
                page = SettingsPage(tinvest_token)
            else:
                page = PlaceholderPage(
                    entry.label,
                    entry.description,
                    page_key=entry.key,
                )
            self._stack.addWidget(page)

        self._navigation.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._navigation.setCurrentRow(0)

        shell.addWidget(sidebar)
        shell.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage("RESEARCH mode")

    def current_page_key(self) -> str:
        page = self._stack.currentWidget()
        if page is None:
            return ""
        return page.objectName().removeprefix("page-")
