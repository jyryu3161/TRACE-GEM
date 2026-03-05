"""Version comparison dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.models import ModelDiff, ModelVersion
from src.gui.theme import THEME


class DiffDialog(QDialog):
    """Dialog showing the diff between two model versions.

    Supports two modes:
    - Two-version comparison (constructor)
    - Single-version detail view (from_single_version classmethod)
    """

    def __init__(
        self,
        diff: ModelDiff,
        version_a: ModelVersion,
        version_b: ModelVersion,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._diff = diff
        self._version_a = version_a
        self._version_b = version_b
        self.setWindowTitle(
            f"Compare: {version_a.version_id} \u2190 {version_b.version_id}"
        )
        self.setMinimumSize(700, 500)
        self._setup_ui()

    @classmethod
    def from_single_version(
        cls, version: ModelVersion, parent=None
    ) -> DiffDialog:
        """Show diff details for a single version's recorded changes."""
        diff = version.diff or ModelDiff()
        dialog = cls.__new__(cls)
        QDialog.__init__(dialog, parent)
        dialog._diff = diff
        dialog._version_a = version
        dialog._version_b = None  # type: ignore[assignment]
        dialog.setWindowTitle(f"Changes in {version.version_id}")
        dialog.setMinimumSize(700, 500)
        dialog._setup_single_ui(version)
        return dialog

    def _setup_single_ui(self, version: ModelVersion) -> None:
        """Build UI for single-version detail mode."""
        layout = QVBoxLayout(self)

        # Header with version info
        header = QLabel(
            f"<b>{version.version_id}</b> &mdash; {version.change_type}"
        )
        header.setStyleSheet(f"font-size: 14px; color: {THEME.text};")
        layout.addWidget(header)

        # Metadata row
        meta_parts = [version.timestamp]
        if version.task_pass_rate:
            meta_parts.append(f"QC: {version.task_pass_rate}")
        if version.parent_version_id:
            meta_parts.append(f"Parent: {version.parent_version_id}")
        meta_label = QLabel(" | ".join(meta_parts))
        meta_label.setStyleSheet(f"color: {THEME.muted_text}; margin-bottom: 4px;")
        layout.addWidget(meta_label)

        if version.description:
            desc_label = QLabel(version.description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(f"color: {THEME.text}; margin-bottom: 8px;")
            layout.addWidget(desc_label)

        # Summary line
        summary_label = QLabel(f"<b>Summary:</b> {self._diff.compact_summary}")
        summary_label.setStyleSheet("margin-bottom: 4px;")
        layout.addWidget(summary_label)

        # Reuse the common diff sections
        self._add_diff_sections(layout)

        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        header = QLabel(
            f"<b>{self._version_a.version_id}</b> vs "
            f"<b>{self._version_b.version_id}</b>"
        )
        header.setStyleSheet(f"font-size: 14px; color: {THEME.text};")
        layout.addWidget(header)

        # QC comparison
        rate_a = self._version_a.task_pass_rate
        rate_b = self._version_b.task_pass_rate
        if rate_a or rate_b:
            qc_label = QLabel(
                f"QC: {self._version_a.version_id} ({rate_a or 'N/A'}) "
                f"\u2192 {self._version_b.version_id} ({rate_b or 'N/A'})"
            )
            qc_label.setStyleSheet(f"color: {THEME.muted_text}; margin-bottom: 8px;")
            layout.addWidget(qc_label)

        self._add_diff_sections(layout)

        layout.addStretch()

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_diff_sections(self, layout: QVBoxLayout) -> None:
        """Add the common diff detail sections (reactions, genes, metabolites)."""
        # Reactions Added
        added = self._diff.reactions_added
        layout.addWidget(self._section_label(f"Reactions Added ({len(added)})"))
        if added:
            table = self._make_id_table(added)
            layout.addWidget(table)
        else:
            layout.addWidget(QLabel("(none)"))

        # Reactions Removed
        removed = self._diff.reactions_removed
        layout.addWidget(self._section_label(f"Reactions Removed ({len(removed)})"))
        if removed:
            table = self._make_id_table(removed)
            layout.addWidget(table)
        else:
            layout.addWidget(QLabel("(none)"))

        # Reactions Modified
        modified = self._diff.reactions_modified
        layout.addWidget(self._section_label(f"Reactions Modified ({len(modified)})"))
        if modified:
            table = QTableWidget()
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels(
                ["Reaction", "Field", "Old Value", "New Value"]
            )
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents
            )
            table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
            table.verticalHeader().setVisible(False)
            table.setAlternatingRowColors(True)
            table.setRowCount(len(modified))

            for row, change in enumerate(modified):
                table.setItem(row, 0, QTableWidgetItem(change.reaction_id))
                table.setItem(row, 1, QTableWidgetItem(change.field))
                table.setItem(row, 2, QTableWidgetItem(change.old_value))
                table.setItem(row, 3, QTableWidgetItem(change.new_value))

            table.setMaximumHeight(min(200, 30 * len(modified) + 30))
            layout.addWidget(table)
        else:
            layout.addWidget(QLabel("(none)"))

        # Genes / Metabolites summary
        genes_added = self._diff.genes_added
        genes_removed = self._diff.genes_removed
        mets_added = self._diff.metabolites_added
        mets_removed = self._diff.metabolites_removed

        summary_parts = []
        if genes_added:
            summary_parts.append(f"+{len(genes_added)} genes")
        if genes_removed:
            summary_parts.append(f"-{len(genes_removed)} genes")
        if mets_added:
            summary_parts.append(f"+{len(mets_added)} metabolites")
        if mets_removed:
            summary_parts.append(f"-{len(mets_removed)} metabolites")

        if summary_parts:
            summary = QLabel("Other: " + ", ".join(summary_parts))
            summary.setStyleSheet(f"color: {THEME.muted_text}; margin-top: 8px;")
            layout.addWidget(summary)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-weight: bold; color: {THEME.text}; margin-top: 12px;"
        )
        return label

    @staticmethod
    def _make_id_table(ids: list[str]) -> QTableWidget:
        """Create a simple single-column table of IDs."""
        table = QTableWidget()
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["Reaction ID"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setRowCount(len(ids))

        for row, rid in enumerate(ids):
            table.setItem(row, 0, QTableWidgetItem(rid))

        table.setMaximumHeight(min(150, 30 * len(ids) + 30))
        return table
