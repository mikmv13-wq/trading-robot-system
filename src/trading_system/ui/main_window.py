from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from trading_system.application import (
    DataApplicationService,
    GetSystemStatusUseCase,
    JobApplicationService,
    TInvestTokenService,
)
from trading_system.config import Settings
from trading_system.ui.pages import DashboardPage, DataPage, PlaceholderPage, SettingsPage
from trading_system.ui.widgets import StatusBadge


@dataclass(frozen=True, slots=True)
class NavigationEntry:
    key: str
    label: str
    description: str
    icon: str


NAVIGATION: tuple[NavigationEntry, ...] = (
    NavigationEntry(
        "dashboard",
        "Панель управления",
        "Общее состояние приложения.",
        "SP_DesktopIcon",
    ),
    NavigationEntry("data", "Данные", "Инструменты, история и качество данных.", "SP_DriveHDIcon"),
    NavigationEntry("charts", "Графики", "Просмотр свечей и результатов стратегии.", "SP_FileIcon"),
    NavigationEntry(
        "backtest",
        "Бэктест",
        "Запуск и анализ результатов тестирования стратегии.",
        "SP_MediaPlay",
    ),
    NavigationEntry(
        "optimization",
        "Оптимизация",
        "Подбор устойчивых параметров.",
        "SP_BrowserReload",
    ),
    NavigationEntry(
        "validation",
        "Валидация",
        "Финальная проверка на отложенных данных.",
        "SP_DialogApplyButton",
    ),
    NavigationEntry("strategies", "Стратегии", "Реестр торговых стратегий.", "SP_FileIcon"),
    NavigationEntry(
        "trading",
        "Торговля",
        "Песочница и рабочий режим торговли.",
        "SP_ArrowForward",
    ),
    NavigationEntry("logs", "Журнал", "Журнал событий приложения.", "SP_FileIcon"),
    NavigationEntry(
        "settings",
        "Настройки",
        "Настройки настольного приложения.",
        "SP_ComputerIcon",
    ),
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        get_system_status: GetSystemStatusUseCase,
        jobs: JobApplicationService,
        tinvest_token: TInvestTokenService | None = None,
        data: DataApplicationService | None = None,
        settings: Settings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle("Система торговых роботов")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 700)

        central = QWidget()
        central.setObjectName("centralShell")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar(tinvest_token))

        workspace = QWidget()
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        workspace_layout.addWidget(sidebar)

        self._stack = QStackedWidget()
        self._stack.setObjectName("pageStack")

        for entry in NAVIGATION:
            page: QWidget
            if entry.key == "dashboard":
                page = DashboardPage(get_system_status, jobs)
            elif entry.key == "data":
                page = DataPage(data)
            elif entry.key == "settings":
                page = SettingsPage(tinvest_token, settings)
            else:
                page = PlaceholderPage(
                    entry.label,
                    entry.description,
                    page_key=entry.key,
                )
            self._stack.addWidget(page)

        self._navigation.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._navigation.setCurrentRow(0)

        workspace_layout.addWidget(self._stack, 1)
        root.addWidget(workspace, 1)
        root.addWidget(self._build_bottom_bar())

        self.setCentralWidget(central)
        self.statusBar().setVisible(False)

    def _build_top_bar(self, tinvest_token: TInvestTokenService | None) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topStatusBar")
        bar.setFixedHeight(58)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        mark = QLabel("▥")
        mark.setObjectName("productMark")
        layout.addWidget(mark)

        title = QLabel("Система торговых роботов")
        title.setObjectName("topProductName")
        layout.addWidget(title)
        layout.addStretch(1)

        mode_caption = QLabel("Режим")
        mode_caption.setObjectName("topMeta")
        layout.addWidget(mode_caption)
        layout.addWidget(StatusBadge("ИССЛЕДОВАНИЕ", tone="success"))

        layout.addWidget(self._vertical_divider())

        broker_caption = QLabel("Т-Инвестиции")
        broker_caption.setObjectName("topMeta")
        layout.addWidget(broker_caption)

        configured = False
        if tinvest_token is not None:
            try:
                configured = tinvest_token.status().configured
            except Exception:
                configured = False
        broker_status = StatusBadge(
            "ТОКЕН НАСТРОЕН" if configured else "НЕТ ТОКЕНА",
            tone="success" if configured else "warning",
        )
        broker_status.setObjectName("topBrokerStatus")
        layout.addWidget(broker_status)

        layout.addWidget(self._vertical_divider())

        jobs_caption = QLabel("Фоновые задачи")
        jobs_caption.setObjectName("topMeta")
        layout.addWidget(jobs_caption)
        layout.addWidget(StatusBadge("ГОТОВО", tone="info"))

        return bar

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(230)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(14)

        product_row = QHBoxLayout()
        product_row.setSpacing(9)
        product_mark = QLabel("СТР")
        product_mark.setObjectName("productMark")
        product_row.addWidget(product_mark)

        product_label = QLabel("Рабочая область")
        product_label.setObjectName("productName")
        product_label.setWordWrap(True)
        product_row.addWidget(product_label, 1)
        layout.addLayout(product_row)

        caption = QLabel("РАЗДЕЛЫ")
        caption.setObjectName("topMeta")
        layout.addWidget(caption)

        self._navigation = QListWidget()
        self._navigation.setObjectName("navigationList")
        self._navigation.setFrameShape(QFrame.Shape.NoFrame)
        self._navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._navigation.setIconSize(QSize(18, 18))

        style = QApplication.style()
        fallback = QStyle.StandardPixmap.SP_FileIcon
        for entry in NAVIGATION:
            item = QListWidgetItem(entry.label)
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            pixmap = getattr(QStyle.StandardPixmap, entry.icon, fallback)
            item.setIcon(style.standardIcon(pixmap))
            item.setSizeHint(QSize(0, 44))
            item.setToolTip(entry.description)
            self._navigation.addItem(item)

        layout.addWidget(self._navigation, 1)

        footer = QLabel("ЛОКАЛЬНОЕ ПРИЛОЖЕНИЕ\nDuckDB · PySide6")
        footer.setObjectName("footerMeta")
        layout.addWidget(footer)
        return sidebar

    @staticmethod
    def _vertical_divider() -> QFrame:
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setObjectName("topDivider")
        divider.setStyleSheet("color: #253751;")
        return divider

    @staticmethod
    def _build_bottom_bar() -> QFrame:
        bar = QFrame()
        bar.setObjectName("bottomStatusBar")
        bar.setFixedHeight(38)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(10)

        layout.addWidget(StatusBadge("ИССЛЕДОВАНИЕ", tone="success"))

        storage = QLabel("Локальное хранилище DuckDB")
        storage.setObjectName("footerMeta")
        layout.addWidget(storage)

        layout.addStretch(1)

        runtime = QLabel("Приложение готово к работе")
        runtime.setObjectName("footerMeta")
        layout.addWidget(runtime)
        return bar

    def current_page_key(self) -> str:
        page = self._stack.currentWidget()
        if page is None:
            return ""
        return page.objectName().removeprefix("page-")
