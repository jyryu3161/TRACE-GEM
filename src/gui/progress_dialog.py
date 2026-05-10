"""Progress dialog for batch evaluation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.gui.theme import THEME


class ProgressDialog(QDialog):
    """Modal progress dialog for batch evaluation with cancel support."""

    cancelled = Signal()

    def __init__(self, title: str = "Evaluating Reactions", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._status_label = QLabel("Initializing...")
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        self._detail_label = QLabel("")
        self._detail_label.setStyleSheet(f"color: {THEME.muted_text}; font-size: 11px;")
        layout.addWidget(self._detail_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._ok_btn = QPushButton("OK")
        self._ok_btn.setMinimumWidth(80)
        self._ok_btn.clicked.connect(self.accept)
        self._ok_btn.hide()
        btn_layout.addWidget(self._ok_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setMinimumWidth(80)
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

    def update_progress(self, current: int, total: int, reaction_id: str = "") -> None:
        percent = int(current / total * 100) if total > 0 else 0
        self._progress_bar.setValue(percent)
        self._status_label.setText(f"Evaluating {current} / {total} reactions...")
        if reaction_id:
            self._detail_label.setText(f"Current: {reaction_id}")

    def set_complete(self) -> None:
        self._progress_bar.setValue(100)
        self._status_label.setText("Evaluation complete!")
        self._detail_label.setText("")
        self._cancel_btn.hide()
        self._ok_btn.show()
        self._ok_btn.setFocus()

    def _on_cancel(self) -> None:
        self._status_label.setText("Cancelling...")
        self._cancel_btn.setEnabled(False)
        self.cancelled.emit()
