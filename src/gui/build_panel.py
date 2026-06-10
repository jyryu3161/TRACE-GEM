"""Model construction (CarveMe) panel: single + batch build with refinement handoff."""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.utils.constants import KEGG_CODE_TO_NAME

_SOLVERS = ("gurobi", "cplex", "scip")
_UNIVERSES = ("(default)", "bacteria", "grampos", "gramneg", "archaea", "cyanobacteria")
_BATCH_COLUMNS = ("fasta", "kegg_code", "universe", "medium", "label")


class BuildPanelWidget(QWidget):
    """Panel for building genome-scale models from protein FASTA via CarveMe."""

    build_requested = Signal()
    batch_build_requested = Signal()
    build_and_refine_requested = Signal()
    cancel_requested = Signal()
    send_to_evaluator_requested = Signal(object)  # BuiltModel
    refine_selected_requested = Signal(object)  # BuiltModel

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    # -- construction -------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Model Construction (CarveMe)")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # Mode selector
        mode_box = QGroupBox("Build mode")
        mode_layout = QHBoxLayout(mode_box)
        self._single_radio = QRadioButton("Single FASTA")
        self._single_radio.setChecked(True)
        self._batch_radio = QRadioButton("Batch (manifest / multiple FASTA + KEGG codes)")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._single_radio, 0)
        self._mode_group.addButton(self._batch_radio, 1)
        mode_layout.addWidget(self._single_radio)
        mode_layout.addWidget(self._batch_radio)
        mode_layout.addStretch()
        layout.addWidget(mode_box)

        # Stacked single/batch inputs
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_single_page())
        self._stack.addWidget(self._build_batch_page())
        layout.addWidget(self._stack)
        self._single_radio.toggled.connect(self._on_mode_changed)

        # Shared CarveMe options
        layout.addWidget(self._build_options_group())

        # Action buttons
        btn_row = QHBoxLayout()
        self._build_btn = QPushButton("Build")
        self._build_btn.clicked.connect(self._on_build_clicked)
        self._refine_btn = QPushButton("Build && Refine")
        self._refine_btn.setToolTip(
            "Build, then run task-aware gap-fill on the model (single model only)."
        )
        self._refine_btn.clicked.connect(self.build_and_refine_requested.emit)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        btn_row.addWidget(self._build_btn)
        btn_row.addWidget(self._refine_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Build log
        log_group = QGroupBox("Build log")
        log_layout = QVBoxLayout(log_group)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(5000)
        self._log.setPlaceholderText("CarveMe output will stream here...")
        log_layout.addWidget(self._log)
        layout.addWidget(log_group)

        # Results + handoff
        res_group = QGroupBox("Built models")
        res_layout = QVBoxLayout(res_group)
        self._results = QListWidget()
        self._results.itemSelectionChanged.connect(self._update_handoff_buttons)
        res_layout.addWidget(self._results)
        handoff_row = QHBoxLayout()
        self._send_btn = QPushButton("Send to Evaluator")
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._refine_sel_btn = QPushButton("Refine selected")
        self._refine_sel_btn.setEnabled(False)
        self._refine_sel_btn.clicked.connect(self._on_refine_selected_clicked)
        handoff_row.addWidget(self._send_btn)
        handoff_row.addWidget(self._refine_sel_btn)
        handoff_row.addStretch()
        res_layout.addLayout(handoff_row)
        layout.addWidget(res_group)

        self._on_mode_changed()

    def _build_single_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        fasta_row = QHBoxLayout()
        self._fasta_edit = QLineEdit()
        self._fasta_edit.setPlaceholderText("protein FASTA (.faa)")
        fasta_browse = QPushButton("Browse...")
        fasta_browse.clicked.connect(self._browse_fasta)
        fasta_row.addWidget(self._fasta_edit)
        fasta_row.addWidget(fasta_browse)
        form.addRow("FASTA file:", fasta_row)

        self._kegg_edit = QLineEdit()
        self._kegg_edit.setPlaceholderText("e.g. eco")
        self._kegg_name = QLabel("")
        self._kegg_edit.textChanged.connect(self._on_kegg_changed)
        kegg_row = QHBoxLayout()
        kegg_row.addWidget(self._kegg_edit)
        kegg_row.addWidget(self._kegg_name)
        form.addRow("KEGG organism code:", kegg_row)

        out_row = QHBoxLayout()
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("(optional) output SBML path")
        out_browse = QPushButton("Browse...")
        out_browse.clicked.connect(self._browse_output_file)
        out_row.addWidget(self._out_edit)
        out_row.addWidget(out_browse)
        form.addRow("Output:", out_row)

        self._dna_check = QCheckBox("Input is a DNA (nucleotide) FASTA")
        form.addRow("", self._dna_check)
        return page

    def _build_batch_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)

        top = QHBoxLayout()
        load_btn = QPushButton("Load manifest...")
        load_btn.clicked.connect(self._load_manifest)
        add_btn = QPushButton("Add row")
        add_btn.clicked.connect(lambda: self._add_batch_row())
        del_btn = QPushButton("Remove row")
        del_btn.clicked.connect(self._remove_batch_row)
        browse_btn = QPushButton("Browse fasta (row)")
        browse_btn.clicked.connect(self._browse_batch_fasta)
        for b in (load_btn, add_btn, del_btn, browse_btn):
            top.addWidget(b)
        top.addStretch()
        v.addLayout(top)

        self._batch_table = QTableWidget(0, len(_BATCH_COLUMNS))
        self._batch_table.setHorizontalHeaderLabels(
            ["FASTA", "KEGG code", "universe", "medium", "label"]
        )
        self._batch_table.verticalHeader().setVisible(False)
        v.addWidget(self._batch_table)

        out_row = QHBoxLayout()
        self._batch_out_edit = QLineEdit()
        self._batch_out_edit.setPlaceholderText("(optional) output directory")
        out_browse = QPushButton("Browse...")
        out_browse.clicked.connect(self._browse_output_dir)
        out_row.addWidget(QLabel("Output dir:"))
        out_row.addWidget(self._batch_out_edit)
        out_row.addWidget(out_browse)
        v.addLayout(out_row)

        note = QLabel(
            "<i>Batch builds models only. Refinement (gap-fill) runs one model at a "
            "time — build the batch, then select a model and 'Refine selected'.</i>"
        )
        note.setWordWrap(True)
        v.addWidget(note)
        return page

    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("CarveMe options")
        form = QFormLayout(box)

        self._solver_combo = QComboBox()
        self._solver_combo.addItems(_SOLVERS)
        form.addRow("Solver:", self._solver_combo)

        self._universe_combo = QComboBox()
        self._universe_combo.addItems(_UNIVERSES)
        form.addRow("Universe:", self._universe_combo)

        self._gapfill_media_edit = QLineEdit()
        self._gapfill_media_edit.setPlaceholderText("(optional) carve -g, e.g. M9,LB")
        form.addRow("CarveMe gap-fill media:", self._gapfill_media_edit)

        self._init_medium_edit = QLineEdit()
        self._init_medium_edit.setPlaceholderText("(optional) carve -i, e.g. M9")
        form.addRow("Init medium:", self._init_medium_edit)

        self._gzip_check = QCheckBox("Write compressed .xml.gz")
        form.addRow("", self._gzip_check)
        return box

    # -- mode / events ------------------------------------------------------

    def _on_mode_changed(self, *_args) -> None:
        is_single = self._single_radio.isChecked()
        self._stack.setCurrentIndex(0 if is_single else 1)
        self._refine_btn.setEnabled(is_single)
        self._build_btn.setText("Build" if is_single else "Build batch")

    def _on_kegg_changed(self, text: str) -> None:
        name = KEGG_CODE_TO_NAME.get(text.strip().lower(), "")
        self._kegg_name.setText(f"({name})" if name else "")

    def _on_build_clicked(self) -> None:
        if self._single_radio.isChecked():
            self.build_requested.emit()
        else:
            self.batch_build_requested.emit()

    def _on_send_clicked(self) -> None:
        built = self.selected_built()
        if built is not None:
            self.send_to_evaluator_requested.emit(built)

    def _on_refine_selected_clicked(self) -> None:
        built = self.selected_built()
        if built is not None:
            self.refine_selected_requested.emit(built)

    def _update_handoff_buttons(self) -> None:
        has = self.selected_built() is not None
        self._send_btn.setEnabled(has)
        self._refine_sel_btn.setEnabled(has)

    # -- file pickers -------------------------------------------------------

    def _browse_fasta(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select protein FASTA", "", "FASTA (*.faa *.fasta *.fa);;All Files (*)"
        )
        if path:
            self._fasta_edit.setText(path)

    def _browse_output_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Output SBML", "", "SBML (*.xml *.xml.gz);;All Files (*)"
        )
        if path:
            self._out_edit.setText(path)

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output directory")
        if path:
            self._batch_out_edit.setText(path)

    def _browse_batch_fasta(self) -> None:
        row = self._batch_table.currentRow()
        if row < 0:
            row = self._add_batch_row()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select protein FASTA", "", "FASTA (*.faa *.fasta *.fa);;All Files (*)"
        )
        if path:
            self._batch_table.setItem(row, 0, QTableWidgetItem(path))

    def _load_manifest(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load manifest", "", "Manifest (*.csv *.tsv *.txt);;All Files (*)"
        )
        if not path:
            return
        try:
            delimiter = "\t" if Path(path).suffix.lower() in {".tsv", ".tab"} else ","
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh, delimiter=delimiter))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Manifest", f"Could not read manifest:\n{exc}")
            return
        self._batch_table.setRowCount(0)
        for row in rows:
            norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            r = self._add_batch_row()
            self._batch_table.setItem(r, 0, QTableWidgetItem(norm.get("fasta", "")))
            self._batch_table.setItem(r, 1, QTableWidgetItem(norm.get("kegg_code", "")))
            self._batch_table.setItem(
                r, 2, QTableWidgetItem(norm.get("universe", norm.get("gram", "")))
            )
            self._batch_table.setItem(r, 3, QTableWidgetItem(norm.get("medium", "")))
            self._batch_table.setItem(r, 4, QTableWidgetItem(norm.get("label", "")))

    def _add_batch_row(self) -> int:
        r = self._batch_table.rowCount()
        self._batch_table.insertRow(r)
        for c in range(len(_BATCH_COLUMNS)):
            self._batch_table.setItem(r, c, QTableWidgetItem(""))
        return r

    def _remove_batch_row(self) -> None:
        row = self._batch_table.currentRow()
        if row >= 0:
            self._batch_table.removeRow(row)

    # -- public API for the controller -------------------------------------

    def get_options_spec(self) -> dict:
        universe = self._universe_combo.currentText()
        return {
            "solver": self._solver_combo.currentText(),
            "universe": "" if universe == "(default)" else universe,
            "gapfill_media": self._gapfill_media_edit.text().strip(),
            "init_medium": self._init_medium_edit.text().strip(),
            "gzip": self._gzip_check.isChecked(),
        }

    def get_single_spec(self) -> dict:
        spec = self.get_options_spec()
        spec.update(
            {
                "fasta": self._fasta_edit.text().strip(),
                "kegg_code": self._kegg_edit.text().strip(),
                "output": self._out_edit.text().strip(),
                "dna": self._dna_check.isChecked(),
            }
        )
        return spec

    def get_batch_jobs(self) -> list[dict]:
        jobs: list[dict] = []
        for r in range(self._batch_table.rowCount()):
            def cell(c: int, r: int = r) -> str:
                item = self._batch_table.item(r, c)
                return item.text().strip() if item else ""

            fasta = cell(0)
            if not fasta:
                continue
            jobs.append(
                {
                    "fasta": fasta,
                    "kegg_code": cell(1),
                    "universe": cell(2),
                    "medium": cell(3),
                    "label": cell(4),
                }
            )
        return jobs

    def get_batch_output_dir(self) -> str:
        return self._batch_out_edit.text().strip()

    def set_busy(self, busy: bool) -> None:
        self._build_btn.setEnabled(not busy)
        self._refine_btn.setEnabled(not busy and self._single_radio.isChecked())
        self._cancel_btn.setEnabled(busy)
        # Lock the mode toggle while a build runs so it can't re-enable the
        # build buttons / start a concurrent build mid-run.
        self._single_radio.setEnabled(not busy)
        self._batch_radio.setEnabled(not busy)

    def append_log(self, line: str) -> None:
        self._log.appendPlainText(line)

    def clear_log(self) -> None:
        self._log.clear()

    def add_built(self, built: object, label: str, ok: bool = True) -> None:
        """Add a built (or failed) model to the results list, storing the object."""
        prefix = "✓" if ok else "✗"
        item = QListWidgetItem(f"{prefix} {label}")
        item.setData(0x0100, built)  # Qt.UserRole
        self._results.addItem(item)
        self._results.setCurrentItem(item)

    def selected_built(self) -> object | None:
        """Return the BuiltModel for the selected results row, or None."""
        item = self._results.currentItem()
        if item is None:
            return None
        obj = item.data(0x0100)  # Qt.UserRole
        # Accept either a BuiltModel or a BuildItemResult (use its .built).
        built = getattr(obj, "built", obj)
        if built is None or getattr(built, "model_data", None) is None:
            return None
        return built

    def clear_results(self) -> None:
        self._results.clear()
        self._update_handoff_buttons()
