"""Version history timeline panel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelVersion


class VersionPanelWidget(QWidget):
    """Panel displaying the version history timeline.

    Shows a list of model versions (newest first) with buttons
    for compare, restore, and export operations.
    """

    restore_requested = Signal(str)       # version_id
    compare_requested = Signal(str, str)  # version_a, version_b
    export_requested = Signal(str)        # version_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._versions: list[ModelVersion] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Title
        title = QLabel("Version History")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # Version list
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self._list)

        # Buttons
        btn_layout = QHBoxLayout()

        self._compare_btn = QPushButton("Compare")
        self._compare_btn.setToolTip("Select exactly 2 versions to compare")
        self._compare_btn.clicked.connect(self._on_compare)
        btn_layout.addWidget(self._compare_btn)

        self._restore_btn = QPushButton("Restore")
        self._restore_btn.setToolTip("Restore selected version")
        self._restore_btn.clicked.connect(self._on_restore)
        btn_layout.addWidget(self._restore_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setToolTip("Export selected version as SBML")
        self._export_btn.clicked.connect(self._on_export)
        btn_layout.addWidget(self._export_btn)

        layout.addLayout(btn_layout)

    def set_history(self, versions: list[ModelVersion]) -> None:
        """Load version history into the list (newest first)."""
        self._versions = list(versions)
        self._list.clear()

        for version in reversed(self._versions):
            text = self._format_item(version)
            item = QListWidgetItem(text)
            item.setData(256, version.version_id)  # Qt.UserRole = 256
            self._list.addItem(item)

    def clear(self) -> None:
        """Clear all version data."""
        self._versions.clear()
        self._list.clear()

    def _format_item(self, version: ModelVersion) -> str:
        """Format a version for display."""
        parts = [version.version_id]

        # Timestamp (show date/time portion)
        ts = version.timestamp
        if "T" in ts:
            ts = ts.split("T")[0] + " " + ts.split("T")[1][:8]
        parts.append(ts)

        if version.description:
            desc = version.description
            if len(desc) > 60:
                desc = desc[:57] + "..."
            parts.append(desc)

        if version.task_pass_rate:
            parts.append(f"[{version.task_pass_rate}]")

        return "  |  ".join(parts)

    def _get_selected_version_ids(self) -> list[str]:
        """Return version_ids of selected items."""
        ids = []
        for item in self._list.selectedItems():
            vid = item.data(256)
            if vid:
                ids.append(vid)
        return ids

    def _on_compare(self) -> None:
        selected = self._get_selected_version_ids()
        if len(selected) != 2:
            QMessageBox.information(
                self, "Compare", "Select exactly 2 versions to compare."
            )
            return
        self.compare_requested.emit(selected[0], selected[1])

    def _on_restore(self) -> None:
        selected = self._get_selected_version_ids()
        if len(selected) != 1:
            QMessageBox.information(
                self, "Restore", "Select exactly 1 version to restore."
            )
            return
        reply = QMessageBox.question(
            self,
            "Restore Version",
            f"Restore model to version {selected[0]}?\n"
            "A new version will be created recording this restoration.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.restore_requested.emit(selected[0])

    def _on_export(self) -> None:
        selected = self._get_selected_version_ids()
        if len(selected) != 1:
            QMessageBox.information(
                self, "Export", "Select exactly 1 version to export."
            )
            return
        self.export_requested.emit(selected[0])
