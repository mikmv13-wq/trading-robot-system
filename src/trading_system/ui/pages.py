from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trading_system.application import GetSystemStatusUseCase, HealthStatus


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        title_label.setStyleSheet("font-size: 24px; font-weight: 600;")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)


class PlaceholderPage(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        page_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"page-{page_key}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(PageHeader(title, subtitle))

        message = QLabel("Экран подготовлен. Функциональность будет добавлена на следующих этапах.")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(message)
        layout.addStretch(1)


class DashboardPage(QWidget):
    def __init__(
        self,
        get_system_status: GetSystemStatusUseCase,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-dashboard")
        self._get_system_status = get_system_status

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(
            PageHeader(
                "Dashboard",
                "Состояние desktop-приложения и локальной инфраструктуры.",
            )
        )

        mode_row = QHBoxLayout()
        mode_caption = QLabel("Режим:")
        mode_value = QLabel("RESEARCH")
        mode_value.setObjectName("applicationMode")
        mode_value.setStyleSheet("font-weight: 600;")
        mode_row.addWidget(mode_caption)
        mode_row.addWidget(mode_value)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        database_title_row = QHBoxLayout()
        database_title = QLabel("DuckDB")
        database_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        database_title_row.addWidget(database_title)
        database_title_row.addStretch(1)

        refresh_button = QPushButton("Обновить")
        refresh_button.setObjectName("refreshDatabaseStatus")
        refresh_button.clicked.connect(self.refresh_status)
        database_title_row.addWidget(refresh_button)
        layout.addLayout(database_title_row)

        self._database_table = QTableWidget(0, 4)
        self._database_table.setObjectName("databaseStatusTable")
        self._database_table.setHorizontalHeaderLabels(
            ["Database", "Status", "Schema", "Baseline"]
        )
        self._database_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._database_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._database_table.verticalHeader().setVisible(False)

        header = self._database_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._database_table)
        layout.addStretch(1)

        self.refresh_status()

    def refresh_status(self) -> None:
        result = self._get_system_status.execute()
        self._database_table.setRowCount(len(result.databases))

        for row, database in enumerate(result.databases):
            status_text = database.status.value
            schema_text = (
                str(database.schema_version)
                if database.schema_version is not None
                else "—"
            )
            baseline = database.metadata.get("schema_baseline", "—")

            values = (database.name, status_text, schema_text, baseline)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if database.status is HealthStatus.ERROR and database.error:
                    item.setToolTip(database.error)
                self._database_table.setItem(row, column, item)
