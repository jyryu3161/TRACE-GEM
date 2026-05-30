"""Version history panel with table layout and git-style change tracking."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.models import ModelDiff, ModelVersion
from src.gui.theme import THEME
from src.gui.version_graph import VersionGraphWidget

# Column indices
COL_VERSION = 0
COL_DATE = 1
COL_TYPE = 2
COL_CHANGES = 3
COL_QC = 4
COL_DESC = 5
_NUM_COLS = 6

# Change type display config
_TYPE_CONFIG: dict[str, tuple[str, str]] = {
    "initial_load": ("Initial", THEME.version_type_initial),
    "gap_fill": ("GapFill", THEME.version_type_gap_fill),
    "manual_edit": ("Edit", THEME.version_type_manual_edit),
    "restore": ("Restore", THEME.version_type_restore),
}


class VersionPanelWidget(QWidget):
    """Panel displaying version history as a table with git-style change tracking.

    Columns: Version | Date | Type | Changes | QC | Description
    Features:
    - Current version highlighted with bold + background color
    - Change type color badges
    - Git-style diff summary (+N rxn, -M rxn, ~K mod)
    - Rich tooltips with detailed diff info
    - Filter by change type
    """

    restore_requested = Signal(str)       # version_id
    compare_requested = Signal(str, str)  # version_a, version_b
    export_requested = Signal(str)        # version_id
    detail_requested = Signal(str)        # version_id (double-click)
    rename_requested = Signal(str, str)   # old_version_id, new_version_id
    description_updated = Signal(str, str)  # version_id, new_description
    delete_requested = Signal(str)        # version_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._versions: list[ModelVersion] = []
        self._current_version_id: str | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Header row: title + filter
        header_layout = QHBoxLayout()
        title = QLabel("Version History")
        title.setObjectName("sectionTitle")
        header_layout.addWidget(title)
        header_layout.addStretch()

        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet(f"color: {THEME.muted_text}; font-size: 12px;")
        header_layout.addWidget(filter_label)

        self._type_filter = QComboBox()
        self._type_filter.addItem("All Types", "")
        for key, (label, _color) in _TYPE_CONFIG.items():
            self._type_filter.addItem(label, key)
        self._type_filter.setFixedWidth(100)
        self._type_filter.currentIndexChanged.connect(self._apply_filter)
        header_layout.addWidget(self._type_filter)

        self._graph_btn = QPushButton("Graph \u25b2")
        self._graph_btn.setFixedWidth(70)
        self._graph_btn.setCheckable(True)
        self._graph_btn.setChecked(True)
        self._graph_btn.clicked.connect(self._toggle_graph)
        header_layout.addWidget(self._graph_btn)

        layout.addLayout(header_layout)

        # Tree widget (table mode)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(_NUM_COLS)
        self._tree.setHeaderLabels([
            "Version", "Date", "Type", "Changes", "QC", "Description",
        ])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._tree.setSortingEnabled(True)
        self._tree.setMouseTracking(True)

        # Column sizing
        header = self._tree.header()
        header.setSectionResizeMode(COL_VERSION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DATE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_CHANGES, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_QC, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DESC, QHeaderView.ResizeMode.Stretch)

        # Double-click to view diff details
        self._tree.itemDoubleClicked.connect(self._on_double_click)

        # Right-click context menu
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)

        # Table ↔ Graph selection sync
        self._tree.itemSelectionChanged.connect(self._on_table_selection_changed)

        # Splitter: table (top) + graph (bottom)
        self._graph = VersionGraphWidget()
        self._graph.version_selected.connect(self._on_graph_version_selected)

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._tree)
        self._splitter.addWidget(self._graph)
        self._splitter.setSizes([300, 200])

        layout.addWidget(self._splitter)

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_history(
        self,
        versions: list[ModelVersion],
        current_version_id: str | None = None,
    ) -> None:
        """Load version history into the table (newest first)."""
        self._versions = list(versions)
        if current_version_id:
            self._current_version_id = current_version_id
        elif versions:
            self._current_version_id = versions[-1].version_id

        self._rebuild_tree()
        self._graph.set_versions(self._versions, self._current_version_id)

    def clear(self) -> None:
        """Clear all version data."""
        self._versions.clear()
        self._current_version_id = None
        self._tree.clear()
        self._graph.clear()

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def _rebuild_tree(self) -> None:
        """Populate tree from self._versions (newest first)."""
        self._tree.setSortingEnabled(False)
        self._tree.clear()

        active_filter = self._type_filter.currentData()

        for version in reversed(self._versions):
            if active_filter and version.change_type != active_filter:
                continue
            item = self._make_item(version)
            self._tree.addTopLevelItem(item)

        self._tree.setSortingEnabled(True)

    def _make_item(self, version: ModelVersion) -> QTreeWidgetItem:
        """Create a QTreeWidgetItem for a single version."""
        is_current = version.version_id == self._current_version_id

        # Version column
        version_text = f"\u2605 {version.version_id}" if is_current else f"  {version.version_id}"

        # Date column — convert UTC ISO timestamp to local time
        ts = version.timestamp
        try:
            dt_local = datetime.fromisoformat(ts).astimezone()
            date_text = dt_local.strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            date_text = ts[:16] if isinstance(ts, str) else "—"

        # Type column
        type_label, _type_color = _TYPE_CONFIG.get(
            version.change_type, (version.change_type, THEME.muted_text)
        )

        # Changes column
        changes_text = self._format_changes(version.diff)

        # QC column
        qc_text = version.task_pass_rate or "\u2014"

        # Description column
        desc = version.description or ""
        if len(desc) > 80:
            desc = desc[:77] + "..."

        item = QTreeWidgetItem([
            version_text,
            date_text,
            type_label,
            changes_text,
            qc_text,
            desc,
        ])

        # Store version_id for retrieval
        item.setData(COL_VERSION, Qt.ItemDataRole.UserRole, version.version_id)

        # --- Styling ---

        # Type badge color
        _label, type_color = _TYPE_CONFIG.get(
            version.change_type, (version.change_type, THEME.muted_text)
        )
        item.setForeground(COL_TYPE, QBrush(QColor(type_color)))
        type_font = item.font(COL_TYPE)
        type_font.setBold(True)
        item.setFont(COL_TYPE, type_font)

        # Changes column coloring
        self._style_changes_cell(item, version.diff)

        # QC column — color based on pass rate
        self._style_qc_cell(item, version.task_pass_rate)

        # Current version highlight
        if is_current:
            bold_font = QFont()
            bold_font.setBold(True)
            for col in range(_NUM_COLS):
                item.setFont(col, bold_font)
            bg = QColor(THEME.version_current_bg)
            for col in range(_NUM_COLS):
                item.setBackground(col, QBrush(bg))

        # Rich tooltip
        item.setToolTip(COL_VERSION, self._build_tooltip(version))

        # Muted description color
        item.setForeground(COL_DESC, QBrush(QColor(THEME.muted_text)))
        # Muted date color
        item.setForeground(COL_DATE, QBrush(QColor(THEME.muted_text)))

        return item

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_changes(diff: ModelDiff | None) -> str:
        """Git-style compact change summary."""
        if diff is None or diff.is_empty:
            return "\u2014"
        return diff.compact_summary

    @staticmethod
    def _style_changes_cell(
        item: QTreeWidgetItem, diff: ModelDiff | None
    ) -> None:
        """Color the Changes cell based on dominant change type."""
        if diff is None or diff.is_empty:
            item.setForeground(COL_CHANGES, QBrush(QColor(THEME.muted_text)))
            return

        # Use addition color if mostly additions, removal if mostly removals
        adds = len(diff.reactions_added) + len(diff.genes_added) + len(diff.metabolites_added)
        rems = len(diff.reactions_removed) + len(diff.genes_removed) + len(diff.metabolites_removed)
        mods = len(diff.reactions_modified)

        if adds >= rems and adds >= mods:
            color = THEME.diff_addition
        elif rems >= adds and rems >= mods:
            color = THEME.diff_removal
        else:
            color = THEME.diff_modification
        item.setForeground(COL_CHANGES, QBrush(QColor(color)))

    @staticmethod
    def _style_qc_cell(
        item: QTreeWidgetItem, task_pass_rate: str | None
    ) -> None:
        """Color QC cell green/yellow/red based on pass percentage."""
        if not task_pass_rate or "/" not in task_pass_rate:
            return
        try:
            passed, total = task_pass_rate.split("/")
            ratio = int(passed) / max(int(total), 1)
        except (ValueError, ZeroDivisionError):
            return

        if ratio >= 0.9:
            color = THEME.score_high
        elif ratio >= 0.7:
            color = THEME.score_mid
        else:
            color = THEME.score_low
        item.setForeground(COL_QC, QBrush(QColor(color)))
        qc_font = item.font(COL_QC)
        qc_font.setBold(True)
        item.setFont(COL_QC, qc_font)

    @staticmethod
    def _build_tooltip(version: ModelVersion) -> str:
        """Build a rich text tooltip for a version."""
        try:
            date_display = (
                datetime.fromisoformat(version.timestamp)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S %Z")
            )
        except (ValueError, TypeError):
            date_display = version.timestamp
        lines = [
            f"<b>Version:</b> {version.version_id}",
            f"<b>Date:</b> {date_display}",
            f"<b>Type:</b> {version.change_type}",
        ]
        if version.parent_version_id:
            lines.append(f"<b>Parent:</b> {version.parent_version_id}")

        diff = version.diff
        if diff and not diff.is_empty:
            lines.append("")
            lines.append("<b>Changes:</b>")
            lines.append(
                f"&nbsp;&nbsp;Reactions: +{len(diff.reactions_added)} added, "
                f"-{len(diff.reactions_removed)} removed, "
                f"~{len(diff.reactions_modified)} modified"
            )
            lines.append(
                f"&nbsp;&nbsp;Genes: +{len(diff.genes_added)} added, "
                f"-{len(diff.genes_removed)} removed"
            )
            lines.append(
                f"&nbsp;&nbsp;Metabolites: +{len(diff.metabolites_added)} added, "
                f"-{len(diff.metabolites_removed)} removed"
            )

        if version.task_pass_rate:
            lines.append("")
            try:
                passed, total = version.task_pass_rate.split("/")
                pct = int(passed) / max(int(total), 1) * 100
                lines.append(
                    f"<b>QC:</b> {version.task_pass_rate} tasks passed ({pct:.1f}%)"
                )
            except ValueError:
                lines.append(f"<b>QC:</b> {version.task_pass_rate}")

        if version.description:
            lines.append("")
            lines.append(f"<b>Description:</b> {version.description}")

        return "<br>".join(lines)

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Rebuild tree when filter changes."""
        self._rebuild_tree()

    # ------------------------------------------------------------------
    # Graph toggle
    # ------------------------------------------------------------------

    def _toggle_graph(self) -> None:
        """Show/hide the version graph panel."""
        visible = self._graph_btn.isChecked()
        self._graph.setVisible(visible)
        self._graph_btn.setText("Graph \u25b2" if visible else "Graph \u25bc")

    # ------------------------------------------------------------------
    # Table ↔ Graph sync
    # ------------------------------------------------------------------

    def _on_table_selection_changed(self) -> None:
        """Sync table selection → graph highlight."""
        ids = self._get_selected_version_ids()
        if len(ids) == 1:
            self._graph.highlight_version(ids[0])

    def _on_graph_version_selected(self, version_id: str) -> None:
        """Sync graph node click → table selection."""
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(COL_VERSION, Qt.ItemDataRole.UserRole) == version_id:
                self._tree.setCurrentItem(item)
                break

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _get_selected_version_ids(self) -> list[str]:
        """Return version_ids of selected items."""
        ids: list[str] = []
        for item in self._tree.selectedItems():
            vid = item.data(COL_VERSION, Qt.ItemDataRole.UserRole)
            if vid:
                ids.append(vid)
        return ids

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

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

    def _show_context_menu(self, pos) -> None:
        """Show right-click context menu for rename/delete."""
        item = self._tree.itemAt(pos)
        if not item:
            return

        vid = item.data(COL_VERSION, Qt.ItemDataRole.UserRole)
        if not vid:
            return

        is_current = vid == self._current_version_id

        menu = QMenu(self)
        rename_action = menu.addAction("Rename ID...")
        edit_desc_action = menu.addAction("Edit Description...")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        if is_current:
            delete_action.setEnabled(False)
            delete_action.setText("Delete (current version)")

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == rename_action:
            self._on_rename(vid, item)
        elif action == edit_desc_action:
            self._on_edit_description(vid, item)
        elif action == delete_action:
            self._on_delete(vid)

    def _on_rename(self, version_id: str, item: QTreeWidgetItem) -> None:
        """Prompt user for new version ID and emit rename signal."""
        new_id, ok = QInputDialog.getText(
            self, "Rename Version ID",
            f"New ID for version {version_id}:",
            text=version_id,
        )
        if ok and new_id and new_id != version_id:
            self.rename_requested.emit(version_id, new_id)

    def _on_edit_description(self, version_id: str, item: QTreeWidgetItem) -> None:
        """Prompt user for new description and emit description_updated signal."""
        current_desc = item.text(COL_DESC)
        new_desc, ok = QInputDialog.getText(
            self, "Edit Description",
            f"New description for {version_id}:",
            text=current_desc,
        )
        if ok and new_desc != current_desc:
            self.description_updated.emit(version_id, new_desc)

    def _on_delete(self, version_id: str) -> None:
        """Confirm and emit delete signal."""
        reply = QMessageBox.question(
            self,
            "Delete Version",
            f"Delete version {version_id}?\n"
            "This will permanently remove the saved SBML file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(version_id)

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        """Emit detail_requested on double-click to show version diff."""
        vid = item.data(COL_VERSION, Qt.ItemDataRole.UserRole)
        if vid:
            self.detail_requested.emit(vid)
