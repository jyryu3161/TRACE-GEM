"""Main application window."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.models import (
    EvaluationStatus,
    EvidenceSource,
    GapFillResult,
    ModelData,
    Reaction,
    ReactionEvidence,
)
from src.evidence.engine import EvidenceEngine
from src.gui.candidate_table import CandidateTableWidget
from src.gui.delegates import ScoreBarDelegate, StatusDelegate
from src.gui.diff_dialog import DiffDialog
from src.gui.evidence_panel import EvidencePanelWidget
from src.gui.gapfill_panel import GapFillPanelWidget
from src.gui.gene_panel import GenePanelWidget
from src.gui.metabolite_panel import MetabolitePanelWidget
from src.gui.model_overview import ModelOverviewWidget
from src.gui.progress_dialog import ProgressDialog
from src.gui.reaction_detail import ReactionDetailWidget
from src.gui.reaction_table import ReactionTableWidget
from src.gui.save_dialog import SaveDialog
from src.gui.score_visualization import ScoreVisualizationWidget
from src.gui.styles import MAIN_STYLESHEET
from src.gui.task_panel import TaskPanelWidget
from src.gui.version_panel import VersionPanelWidget
from src.gui.workers import (
    CloseEngineWorker,
    EvaluateBatchWorker,
    EvaluateReactionWorker,
    GapFillWorkflowWorker,
    InitEngineWorker,
    LoadModelWorker,
)
from src.utils.config import Config
from src.utils.constants import APP_NAME, APP_VERSION, KEGG_CODE_TO_NAME
from src.versioning.version_manager import VersionManager

logger = logging.getLogger("gem_evaluator.gui")


class MainWindow(QMainWindow):
    """Main application window for GEM Evaluator."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._model: ModelData | None = None
        self._engine: EvidenceEngine | None = None
        self._thread_pool = QThreadPool.globalInstance()
        self._batch_worker: EvaluateBatchWorker | None = None
        self._engine_init_in_progress = False
        self._engine_close_in_progress = False
        self._pending_engine_init = False
        self._engine_init_token = 0
        self._engine_error: str | None = None
        self._active_workers: list[object] = []  # prevent GC of QRunnable
        self._gapfill_worker: GapFillWorkflowWorker | None = None
        self._version_manager: VersionManager | None = None

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)
        self.setStyleSheet(MAIN_STYLESHEET)

        self._setup_menu()
        self._setup_ui()
        self._setup_statusbar()
        self._init_engine()

    # --- Setup ---

    def _setup_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&Open Model...", self._open_model, "Ctrl+O")
        self._recent_menu = file_menu.addMenu("Recent Files")
        self._update_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction("&Save Version...", self._save_version, "Ctrl+Shift+S")
        file_menu.addSeparator()
        settings_action = QAction("&Settings...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.setMenuRole(QAction.MenuRole.NoRole)
        settings_action.triggered.connect(self._show_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close, "Ctrl+Q")

        # Evaluation menu
        eval_menu = menubar.addMenu("&Evaluation")
        eval_menu.addAction("Evaluate &Selected", self._evaluate_selected, "Ctrl+E")
        eval_menu.addAction("Evaluate &All", self._evaluate_all, "Ctrl+Shift+E")
        eval_menu.addSeparator()
        eval_menu.addAction("&Clear Results", self._clear_results)

        # Workflow menu
        workflow_menu = menubar.addMenu("&Workflow")
        workflow_menu.addAction("Start &Workflow...", self._start_workflow, "Ctrl+W")
        workflow_menu.addAction("Load &Task File...", self._load_task_file)

        # Export menu
        export_menu = menubar.addMenu("E&xport")
        export_menu.addAction("Export &CSV...", self._export_csv, "Ctrl+S")
        export_menu.addAction("Export &JSON...", self._export_json)
        export_menu.addAction("Export &SBML...", self._export_sbml)
        export_menu.addSeparator()
        export_menu.addAction("Export &Improved SBML...", self._export_improved_sbml)

        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction("&Charts", self._show_charts, "Ctrl+G")

        # Help menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&About", self._show_about)

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Main splitter: left (overview + table) | right (detail + evidence)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._overview = ModelOverviewWidget()
        self._overview.setMaximumHeight(250)
        left_layout.addWidget(self._overview)

        # Left tabs: Model Reactions + Candidates
        self._left_tabs = QTabWidget()

        self._reaction_table = ReactionTableWidget()
        self._reaction_table.reaction_selected.connect(self._on_reaction_selected)
        self._left_tabs.addTab(self._reaction_table, "Model Reactions")

        self._candidate_table = CandidateTableWidget()
        self._candidate_table.candidate_selected.connect(self._on_candidate_selected)
        self._left_tabs.addTab(self._candidate_table, "Candidates")

        left_layout.addWidget(self._left_tabs)

        splitter.addWidget(left_widget)

        # Right side — tabs for detail views
        right_tabs = QTabWidget()

        # Detail + Evidence tab
        detail_evidence = QWidget()
        de_layout = QVBoxLayout(detail_evidence)
        de_layout.setContentsMargins(0, 0, 0, 0)

        detail_splitter = QSplitter(Qt.Orientation.Vertical)

        self._reaction_detail = ReactionDetailWidget()
        self._reaction_detail.evaluate_requested.connect(self._evaluate_reaction_by_id)
        self._reaction_detail.reaction_modified.connect(self._on_reaction_modified)
        detail_splitter.addWidget(self._reaction_detail)

        self._evidence_panel = EvidencePanelWidget()
        detail_splitter.addWidget(self._evidence_panel)

        detail_splitter.setSizes([300, 400])
        de_layout.addWidget(detail_splitter)
        right_tabs.addTab(detail_evidence, "Detail & Evidence")

        # Gene panel tab
        self._gene_panel = GenePanelWidget()
        right_tabs.addTab(self._gene_panel, "Genes")

        # Metabolite panel tab
        self._metabolite_panel = MetabolitePanelWidget()
        right_tabs.addTab(self._metabolite_panel, "Metabolites")

        # Charts tab
        self._chart_widget = ScoreVisualizationWidget()
        right_tabs.addTab(self._chart_widget, "Charts")

        # Tasks tab
        self._task_panel = TaskPanelWidget()
        right_tabs.addTab(self._task_panel, "Tasks")

        # Gap-Fill tab
        self._gapfill_panel = GapFillPanelWidget()
        self._gapfill_panel.apply_requested.connect(self._on_apply_gapfill)
        self._gapfill_panel.export_sbml_requested.connect(self._export_improved_sbml)
        self._gapfill_panel.export_report_requested.connect(self._export_gapfill_report)
        right_tabs.addTab(self._gapfill_panel, "Gap-Fill")

        # Versions tab
        self._version_panel = VersionPanelWidget()
        self._version_panel.restore_requested.connect(self._restore_version)
        self._version_panel.compare_requested.connect(self._compare_versions)
        self._version_panel.export_requested.connect(self._export_version_sbml)
        right_tabs.addTab(self._version_panel, "Versions")

        self._right_tabs = right_tabs

        splitter.addWidget(right_tabs)
        splitter.setSizes([600, 500])

        main_layout.addWidget(splitter)

        # Set delegates
        self._score_delegate = ScoreBarDelegate(self._reaction_table)
        self._status_delegate = StatusDelegate(self._reaction_table)
        self._reaction_table.set_delegates(self._score_delegate, self._status_delegate)

        # Candidate table score delegate
        self._candidate_score_delegate = ScoreBarDelegate(self._candidate_table)
        self._candidate_table.set_score_delegate(self._candidate_score_delegate)

    def _setup_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._source_status_labels: dict[str, QLabel] = {}
        self._update_source_status()

        self._statusbar.showMessage("Ready — Open an SBML model to begin")

    def _update_source_status(self) -> None:
        """Update the permanent source connection indicators in the status bar."""
        from src.evidence.evidence_types import get_ordered_sources

        # Remove old labels
        for label in self._source_status_labels.values():
            self._statusbar.removeWidget(label)
            label.deleteLater()
        self._source_status_labels.clear()

        for source, sc in get_ordered_sources():
            if source == EvidenceSource.KEGG:
                continue  # KEGG always active, no indicator needed

            # Determine on/off status
            is_enabled = getattr(self._config, sc.enable_key, False) if sc.enable_key else True
            needs_key = sc.requires_api_key
            has_key = bool(getattr(self._config, sc.config_key, None)) if sc.config_key else True

            label = QLabel()
            name = sc.display_name

            if is_enabled and (has_key or not needs_key):
                label.setText(f" {name}: ON ")
                label.setStyleSheet(f"color: {sc.color}; font-weight: bold; margin-right: 6px;")
            else:
                if not is_enabled:
                    reason = "disabled"
                elif needs_key and not has_key:
                    reason = "no key"
                else:
                    reason = "off"
                label.setText(f" {name}: OFF ({reason}) ")
                label.setStyleSheet("color: #999; margin-right: 6px;")

            self._statusbar.addPermanentWidget(label)
            self._source_status_labels[source.value] = label

    # --- Engine init ---

    def _init_engine(self) -> None:
        # Coalesce repeated requests while an init/close cycle is in progress.
        if self._engine_close_in_progress or self._engine_init_in_progress:
            self._pending_engine_init = True
            return

        # Close existing engine before creating a new one.
        if self._engine is not None:
            self._close_engine_for_reinit()
            return

        self._start_engine_init()

    def _start_engine_init(self) -> None:
        self._engine_init_in_progress = True
        self._engine_error = None
        self._engine_init_token += 1
        token = self._engine_init_token
        worker = InitEngineWorker(self._config)
        worker.setAutoDelete(False)
        worker.signals.result.connect(lambda engine, t=token: self._on_engine_ready(t, engine))
        worker.signals.error.connect(lambda e, t=token: self._on_engine_init_error(t, e))
        worker.signals.finished.connect(lambda t=token: self._on_engine_init_finished(t))
        self._active_workers.append(worker)  # prevent GC before signals are delivered
        self._thread_pool.start(worker)

    def _on_engine_ready(self, token: int, engine: object) -> None:
        if token != self._engine_init_token:
            if isinstance(engine, EvidenceEngine):
                self._close_engine_background(engine)
            return

        if not isinstance(engine, EvidenceEngine):
            self._statusbar.showMessage("Engine init failed: invalid engine")
            return

        self._engine = engine
        if engine.mapper:
            self._metabolite_panel.set_mapper(engine.mapper)
        self._update_source_status()
        self._statusbar.showMessage("Evidence engine ready")
        logger.info("Evidence engine initialized")

    def _on_engine_init_error(self, token: int, error: str) -> None:
        if token != self._engine_init_token:
            return
        self._engine_error = error
        self._statusbar.showMessage(f"Engine init failed: {error}")

    def _on_engine_init_finished(self, token: int) -> None:
        self._active_workers = [w for w in self._active_workers if not isinstance(w, InitEngineWorker)]
        if token != self._engine_init_token:
            return
        self._engine_init_in_progress = False
        if self._pending_engine_init:
            self._pending_engine_init = False
            self._init_engine()

    def _close_engine_for_reinit(self) -> None:
        engine = self._engine
        self._engine = None
        if engine is None:
            self._start_engine_init()
            return

        self._engine_close_in_progress = True
        worker = CloseEngineWorker(engine)
        worker.setAutoDelete(False)
        worker.signals.error.connect(lambda e: logger.warning("Engine close failed: %s", e))
        worker.signals.finished.connect(self._on_engine_closed_for_reinit)
        self._active_workers.append(worker)
        self._thread_pool.start(worker)

    def _on_engine_closed_for_reinit(self) -> None:
        self._active_workers = [w for w in self._active_workers if not isinstance(w, CloseEngineWorker)]
        self._engine_close_in_progress = False
        self._start_engine_init()

    def _close_engine_background(self, engine: EvidenceEngine) -> None:
        worker = CloseEngineWorker(engine)
        worker.setAutoDelete(False)
        worker.signals.error.connect(lambda e: logger.warning("Engine close failed: %s", e))
        worker.signals.finished.connect(
            lambda: self._active_workers.__contains__(worker) and self._active_workers.remove(worker)
        )
        self._active_workers.append(worker)
        self._thread_pool.start(worker)

    # --- File operations ---

    def _open_model(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open SBML Model",
            "",
            "SBML Files (*.xml *.sbml);;All Files (*)",
        )
        if filepath:
            self._load_model(filepath)

    def _load_model(self, filepath: str) -> None:
        self._statusbar.showMessage(f"Loading {Path(filepath).name}...")
        self._loading_filepath = filepath
        worker = LoadModelWorker(filepath)
        worker.setAutoDelete(False)
        worker.signals.result.connect(self._on_model_loaded)
        worker.signals.error.connect(self._on_model_error)
        worker.signals.finished.connect(
            lambda: worker in self._active_workers and self._active_workers.remove(worker)
        )
        self._active_workers.append(worker)
        self._thread_pool.start(worker)

    def _show_organism_dialog(
        self, detected_code: str | None, detected_name: str | None
    ) -> tuple[str, str] | None:
        """Show dialog for user to confirm/enter KEGG organism code.

        Returns (kegg_code, organism_name) or None if cancelled.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Set Organism")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)

        info_label = QLabel()
        if detected_code:
            info_label.setText(
                f"Auto-detected organism: <b>{detected_code}</b>"
                f" ({detected_name or ''}). Confirm or modify below."
            )
        else:
            info_label.setText(
                "Could not auto-detect organism from model. Please enter the KEGG organism code."
            )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        form = QFormLayout()

        code_edit = QLineEdit()
        code_edit.setPlaceholderText("e.g. eco")
        if detected_code:
            code_edit.setText(detected_code)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. Escherichia coli")
        if detected_name:
            name_edit.setText(detected_name)

        # Auto-fill organism name when a known KEGG code is entered
        def _on_code_changed(text: str) -> None:
            code = text.strip().lower()
            known_name = KEGG_CODE_TO_NAME.get(code)
            if known_name:
                name_edit.setText(known_name)

        code_edit.textChanged.connect(_on_code_changed)

        form.addRow("KEGG Organism Code:", code_edit)
        form.addRow("Organism Name:", name_edit)
        layout.addLayout(form)

        ref_label = QLabel(
            "<small>Common codes: "
            "<b>eco</b> (E. coli), <b>sce</b> (S. cerevisiae), "
            "<b>hsa</b> (H. sapiens), <b>bsu</b> (B. subtilis)</small>"
        )
        ref_label.setWordWrap(True)
        layout.addWidget(ref_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            code = code_edit.text().strip().lower()
            name = name_edit.text().strip()
            if not code:
                return None
            if not name:
                name = KEGG_CODE_TO_NAME.get(code, code)
            return (code, name)
        return None

    def _on_model_loaded(self, model: object) -> None:
        if not isinstance(model, ModelData):
            return
        self._model = model

        # Show organism dialog for user to confirm/enter
        result = self._show_organism_dialog(model.kegg_organism_code, model.organism)

        needs_reinit = self._engine is None
        if result:
            kegg_code, org_name = result
            if kegg_code != self._config.kegg_organism_code:
                needs_reinit = True
            if org_name != self._config.organism_name:
                needs_reinit = True
            self._config.kegg_organism_code = kegg_code
            self._config.organism_name = org_name
            model.kegg_organism_code = kegg_code
            model.organism = org_name
            self._config.save()

        # Reinit only when settings changed or engine is unavailable.
        if needs_reinit:
            self._init_engine()

        # Update UI
        self._overview.set_model(model)
        self._reaction_table.set_model_data(model)
        self._gene_panel.set_model(model)
        self._metabolite_panel.set_model(model)
        self._reaction_detail.set_model(model)
        self._reaction_detail.clear()
        self._evidence_panel.clear()

        # Save to recent files
        filepath: str | None = getattr(self, "_loading_filepath", None)
        if filepath:
            self._config.add_recent_file(filepath)
            self._config.save()
            self._update_recent_menu()
            self._loading_filepath = ""

        # Initialize version control
        if self._config.enable_versioning and model.cobra_model:
            try:
                self._version_manager = VersionManager(self._config)
                self._version_manager.set_base_model(model.cobra_model, model.id)
                self._version_panel.set_history(self._version_manager.get_history())
            except Exception as e:
                logger.warning("Version manager init failed: %s", e)
                self._version_manager = None

        self._statusbar.showMessage(
            f"{model.id} | {model.reaction_count} reactions | "
            f"{model.gene_count} genes | {model.metabolite_count} metabolites"
        )
        logger.info("Model loaded: %s", model.id)

    def _on_model_error(self, error: str) -> None:
        QMessageBox.critical(self, "Error Loading Model", error)
        self._statusbar.showMessage("Model load failed")

    # --- Reaction selection ---

    def _on_reaction_selected(self, reaction_id: str) -> None:
        if not self._model:
            return
        rxn = self._model.get_reaction(reaction_id)
        if not rxn:
            return

        self._reaction_detail.set_reaction(rxn)
        self._gene_panel.set_reaction(rxn)
        self._metabolite_panel.set_reaction(rxn)

        # Show evidence if available
        if self._engine:
            ev = self._engine.get_result(reaction_id)
            if ev:
                self._reaction_detail.update_evidence(ev)
                self._evidence_panel.set_evidence(ev)
            else:
                self._evidence_panel.clear()

    # --- Evaluation ---

    def _evaluate_selected(self) -> None:
        """Evaluate currently selected reaction."""
        rxn = self._get_selected_reaction()
        if rxn:
            self._evaluate_reaction(rxn)

    def _evaluate_reaction_by_id(self, reaction_id: str) -> None:
        if not self._model:
            return
        rxn = self._model.get_reaction(reaction_id)
        if rxn:
            self._evaluate_reaction(rxn)

    def _evaluate_reaction(self, reaction: Reaction) -> None:
        if not self._engine:
            if self._engine_error:
                QMessageBox.warning(
                    self,
                    "Engine Error",
                    f"Evidence engine initialization failed: {self._engine_error}",
                )
            elif self._engine_init_in_progress or self._engine_close_in_progress:
                QMessageBox.warning(self, "Not Ready", "Evidence engine is still initializing.")
            else:
                self._init_engine()
                QMessageBox.warning(
                    self,
                    "Not Ready",
                    "Evidence engine is not ready yet. Initialization has been retried.",
                )
            return

        self._statusbar.showMessage(f"Evaluating {reaction.id}...")
        worker = EvaluateReactionWorker(self._engine, reaction)
        worker.signals.result.connect(self._on_reaction_evaluated)
        worker.signals.error.connect(
            lambda e: self._statusbar.showMessage(f"Evaluation error: {e}")
        )
        self._thread_pool.start(worker)

    def _on_reaction_evaluated(self, evidence: object) -> None:
        if not isinstance(evidence, ReactionEvidence):
            return

        self._reaction_table.update_evidence(evidence.reaction_id, evidence)
        self._reaction_detail.update_evidence(evidence)
        self._evidence_panel.set_evidence(evidence)

        self._update_eval_count()
        self._statusbar.showMessage(
            f"Evaluated {evidence.reaction_id} — Score: {evidence.confidence_score:.3f}"
        )

    def _evaluate_all(self) -> None:
        if not self._model or not self._engine:
            QMessageBox.warning(self, "Not Ready", "Load a model and wait for engine init.")
            return

        reactions = self._model.reactions
        dialog = ProgressDialog("Evaluating All Reactions", self)

        worker = EvaluateBatchWorker(self._engine, reactions)
        self._batch_worker = worker

        worker.signals.progress.connect(dialog.update_progress)
        worker.signals.result.connect(lambda r: self._on_batch_complete(r, dialog))
        worker.signals.error.connect(lambda e: self._on_batch_error(e, dialog))
        dialog.cancelled.connect(worker.cancel)

        self._thread_pool.start(worker)
        dialog.exec()

    def _on_batch_complete(self, results: object, dialog: ProgressDialog) -> None:
        if isinstance(results, dict):
            self._reaction_table.update_all_evidence(results)
            self._update_charts()
        dialog.set_complete()
        self._update_eval_count()
        self._statusbar.showMessage("Batch evaluation complete")
        self._batch_worker = None

    def _on_batch_error(self, error: str, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        QMessageBox.warning(self, "Evaluation Error", error)
        self._batch_worker = None

    def _clear_results(self) -> None:
        if self._engine:
            self._engine.clear_results()
        self._evidence_panel.clear()
        if self._model:
            self._reaction_table.set_model_data(self._model)
        self._update_eval_count()
        self._statusbar.showMessage("Results cleared")

    # --- Export ---

    def _export_csv(self) -> None:
        if not self._engine or not self._model:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            f"{self._model.id}_evidence.csv",
            "CSV Files (*.csv)",
        )
        if not filepath:
            return

        results = self._engine.get_all_results()

        # Build dynamic header and score columns from all sources
        from src.evidence.evidence_types import get_ordered_sources

        source_order = get_ordered_sources()
        score_headers = [f"{sc.display_name} Score" for _, sc in source_order]

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Reaction ID",
                    "Name",
                    "Subsystem",
                    "Genes",
                    "GPR",
                    "Confidence Score",
                    *score_headers,
                    "Substrate Match",
                    "Product Match",
                    "EC Numbers",
                    "KEGG IDs",
                    "Status",
                ]
            )
            for rxn in self._model.reactions:
                ev = results.get(rxn.id, ReactionEvidence(rxn.id))
                # Dynamic per-source scores
                per_source = []
                for source, _ in source_order:
                    attr = f"{source.value}_score"
                    per_source.append(f"{getattr(ev, attr, 0.0):.4f}")

                writer.writerow(
                    [
                        rxn.id,
                        rxn.name,
                        rxn.subsystem or "",
                        ";".join(rxn.genes),
                        rxn.gene_reaction_rule,
                        f"{ev.confidence_score:.4f}",
                        *per_source,
                        f"{ev.substrate_match_ratio:.4f}",
                        f"{ev.product_match_ratio:.4f}",
                        ";".join(ev.ec_numbers),
                        ";".join(ev.kegg_reaction_ids),
                        ev.status.value,
                    ]
                )

        self._statusbar.showMessage(f"Exported to {filepath}")

    def _export_json(self) -> None:
        if not self._engine or not self._model:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            f"{self._model.id}_evidence.json",
            "JSON Files (*.json)",
        )
        if not filepath:
            return

        results = self._engine.get_all_results()
        reactions_dict: dict[str, dict] = {}
        export: dict[str, object] = {
            "model_id": self._model.id,
            "organism": self._model.organism,
            "total_reactions": self._model.reaction_count,
            "reactions": reactions_dict,
        }
        for rxn in self._model.reactions:
            ev = results.get(rxn.id, ReactionEvidence(rxn.id))
            reactions_dict[rxn.id] = {
                "name": rxn.name,
                "subsystem": rxn.subsystem,
                "equation": rxn.equation,
                "genes": rxn.genes,
                "confidence_score": ev.confidence_score,
                "scores": {
                    source.value: getattr(ev, f"{source.value}_score", 0.0)
                    for source in EvidenceSource
                },
                "verification": {
                    "substrate_match_ratio": ev.substrate_match_ratio,
                    "product_match_ratio": ev.product_match_ratio,
                },
                "ec_numbers": ev.ec_numbers,
                "kegg_reaction_ids": ev.kegg_reaction_ids,
                "evidence_items": [
                    {
                        "source": item.source.value,
                        "strength": item.strength.name,
                        "description": item.description,
                        "url": item.url,
                        "raw_data": self._serialize_raw_data(item.raw_data),
                    }
                    for item in ev.items
                ],
                "status": ev.status.value,
            }

        with open(filepath, "w") as f:
            json.dump(export, f, indent=2)

        self._statusbar.showMessage(f"Exported to {filepath}")

    def _export_sbml(self) -> None:
        if not self._model or not self._model.cobra_model:
            QMessageBox.warning(self, "No Model", "No SBML model loaded.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export SBML",
            f"{self._model.id}_modified.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return
        import cobra

        cobra.io.write_sbml_model(self._model.cobra_model, filepath)
        self._statusbar.showMessage(f"SBML exported to {filepath}")

    # --- Workflow ---

    def _start_workflow(self) -> None:
        """Open the workflow wizard and start gap-filling."""
        if not self._model:
            QMessageBox.warning(self, "No Model", "Load an SBML model first.")
            return

        from src.gui.workflow_wizard import WorkflowWizard

        wizard = WorkflowWizard(self._config, self._model, self)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            return

        selections = wizard.get_selections()
        self._run_gapfill_workflow(selections)

    def _load_task_file(self) -> None:
        """Load a metabolic task CSV file and display results."""
        if not self._model or not self._model.cobra_model:
            QMessageBox.warning(self, "No Model", "Load an SBML model first.")
            return

        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Load Metabolic Task File",
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        try:
            from src.core.task_parser import TaskParser, TaskRunner

            parser = TaskParser()
            tasks = parser.parse(filepath)

            runner = TaskRunner()
            results = runner.run_all(self._model.cobra_model, tasks)

            self._task_panel.set_results(results)
            self._right_tabs.setCurrentWidget(self._task_panel)
            self._statusbar.showMessage(
                f"Loaded {len(tasks)} tasks — "
                f"{sum(1 for r in results if r.passed)}/{len(results)} passed"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Tasks", str(e))

    def _run_gapfill_workflow(self, selections: dict) -> None:
        """Start the gap-filling workflow worker."""
        if not self._model:
            return

        dialog = ProgressDialog("Gap-Fill Workflow", self)

        worker = GapFillWorkflowWorker(
            config=self._config,
            model_data=self._model,
            universal_path=selections.get("universal_model_path", ""),
            task_path=selections.get("task_file_path"),
            evidence_engine=self._engine,
            options=selections,
        )
        self._gapfill_worker = worker

        def on_progress(phase: str, current: int, total: int, detail: str) -> None:
            display = f"[{phase}] {detail}"
            dialog.update_progress(current, total, display)

        worker.signals.progress.connect(on_progress)
        worker.signals.result.connect(lambda r: self._on_gapfill_complete(r, dialog))
        worker.signals.error.connect(lambda e: self._on_gapfill_error(e, dialog))

        self._thread_pool.start(worker)
        dialog.exec()

    def _on_gapfill_complete(self, result: object, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        self._gapfill_worker = None

        if not isinstance(result, GapFillResult):
            return

        # Update task panel with before/after results
        if result.task_results_before:
            after = result.task_results_after if result.task_results_after else None
            self._task_panel.set_results(result.task_results_before, after)

        # Update gapfill panel
        self._gapfill_panel.set_result(result)

        # Update candidate table if we have added reactions
        if result.added_reactions:
            self._candidate_table.set_candidates(result.added_reactions)
            self._left_tabs.setCurrentWidget(self._candidate_table)

        # Switch to Gap-Fill tab
        self._right_tabs.setCurrentWidget(self._gapfill_panel)

        self._statusbar.showMessage(
            f"Gap-fill complete: {len(result.added_reactions)} reactions added, "
            f"{result.tasks_fixed}/{result.total_tasks} tasks fixed"
        )
        logger.info(
            "Gap-fill complete: %d added, %d/%d fixed",
            len(result.added_reactions),
            result.tasks_fixed,
            result.total_tasks,
        )

        # Auto-save version after gap-fill
        if self._version_manager and self._model and self._model.cobra_model:
            task_results = result.task_results_after or result.task_results_before or None
            self._do_save_version(
                change_type="gap_fill",
                task_results=task_results,
            )

    def _on_gapfill_error(self, error: str, dialog: ProgressDialog) -> None:
        dialog.set_complete()
        self._gapfill_worker = None
        QMessageBox.critical(self, "Gap-Fill Error", error)
        self._statusbar.showMessage("Gap-fill failed")

    def _on_apply_gapfill(self) -> None:
        """Apply gap-fill results to the current model display."""
        if self._model:
            # Refresh the reaction table with updated model data
            self._reaction_table.set_model_data(self._model)
            self._overview.set_model(self._model)
            self._statusbar.showMessage("Gap-fill results applied to model")

    def _export_improved_sbml(self) -> None:
        """Export the improved model after gap-filling."""
        if not self._model or not self._model.cobra_model:
            QMessageBox.warning(self, "No Model", "No model available for export.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Improved SBML",
            f"{self._model.id}_improved.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return

        import cobra

        cobra.io.write_sbml_model(self._model.cobra_model, filepath)
        self._statusbar.showMessage(f"Improved SBML exported to {filepath}")

    def _export_gapfill_report(self) -> None:
        """Export gap-fill report as CSV."""
        if not self._model:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Gap-Fill Report",
            f"{self._model.id}_gapfill_report.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        # Collect data from gapfill panel
        # For now, write basic report from available data
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Reaction ID", "Name", "Penalty", "GPR", "Selected"])

        self._statusbar.showMessage(f"Report exported to {filepath}")

    def _on_candidate_selected(self, reaction_id: str) -> None:
        """Handle candidate reaction selection from candidate table."""
        # Show basic info in the detail panel if available
        pass

    # --- View ---

    def _show_charts(self) -> None:
        # Switch to charts tab
        layout = self.centralWidget().layout()
        if layout is None:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, QSplitter):
                right = widget.widget(1)
                if isinstance(right, QTabWidget):
                    right.setCurrentIndex(right.count() - 1)  # Charts tab (last)
                    self._update_charts()
                    break

    def _update_charts(self) -> None:
        if not self._engine or not self._model:
            return
        results = self._engine.get_all_results()
        if not results:
            return

        subsystem_map = {r.id: r.subsystem or "Unknown" for r in self._model.reactions}
        self._chart_widget.update_charts(results, subsystem_map)

    # --- Help ---

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About GEM Evaluator",
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            "<p>Genome-Scale Metabolic Model Evidence Evaluator</p>"
            "<p>Evaluates reactions in SBML models against KEGG, BiGG, UniProt, "
            "PubMed, MetaCyc, Gemini, and Perplexity to verify reaction evidence.</p>",
        )

    def _show_settings(self) -> None:
        from src.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._config.save()
            self._update_source_status()
            self._init_engine()  # Reinit with new settings

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._batch_worker:
            self._batch_worker.cancel()

        if self._engine:
            engine = self._engine
            self._engine = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(engine.close())
                finally:
                    loop.close()
            except Exception as e:
                logger.warning("Engine close during shutdown failed: %s", e)

        super().closeEvent(event)

    # --- Reaction modification ---

    def _on_reaction_modified(self, reaction_id: str) -> None:
        """Handle reaction edits from the detail panel."""
        if self._model:
            rxn = self._model.get_reaction(reaction_id)
            if rxn:
                self._reaction_table.update_reaction_row(reaction_id)
        self._statusbar.showMessage(f"Reaction {reaction_id} modified")

        # Auto-save version on edit if enabled
        if (
            self._config.auto_save_on_edit
            and self._version_manager
            and self._model
            and self._model.cobra_model
        ):
            self._auto_save_version("manual_edit")

    # --- Version control ---

    def _save_version(self) -> None:
        """Show the save dialog and save a new version."""
        if not self._model or not self._model.cobra_model:
            QMessageBox.warning(self, "No Model", "Load an SBML model first.")
            return
        if not self._version_manager:
            QMessageBox.warning(
                self, "Versioning Disabled", "Version control is not active."
            )
            return

        current = self._version_manager.current_version
        dialog = SaveDialog(self._config, current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        options = dialog.get_options()

        # Run QC if requested
        task_results = None
        if options["run_qc"]:
            task_results = self._run_qc_for_version()

        # Save version in worker thread via asyncio
        self._do_save_version(
            change_type=options["change_type"],
            custom_description=options["description"],
            task_results=task_results,
        )

        # Export SBML copy if requested
        if options["export_sbml"]:
            self._export_sbml()

    def _do_save_version(
        self,
        change_type: str,
        custom_description: str | None = None,
        task_results=None,
    ) -> None:
        """Save a version synchronously by running async in a new event loop."""
        if not self._version_manager or not self._model or not self._model.cobra_model:
            return

        try:
            loop = asyncio.new_event_loop()
            try:
                version = loop.run_until_complete(
                    self._version_manager.save_version(
                        self._model.cobra_model,
                        change_type,
                        task_results=task_results,
                        custom_description=custom_description,
                    )
                )
            finally:
                loop.close()

            self._version_panel.set_history(self._version_manager.get_history())
            self._statusbar.showMessage(
                f"Saved version {version.version_id}: {version.description}"
            )
        except Exception as e:
            logger.warning("Failed to save version: %s", e)
            QMessageBox.warning(self, "Version Save Error", str(e))

    def _auto_save_version(self, change_type: str) -> None:
        """Auto-save a version without showing dialog."""
        if not self._version_manager or not self._model or not self._model.cobra_model:
            return
        self._do_save_version(change_type=change_type)

    def _restore_version(self, version_id: str) -> None:
        """Restore a specific version."""
        if not self._version_manager or not self._model:
            return

        try:
            restored_model = self._version_manager.restore_version(version_id)

            # Update the model data's cobra_model reference
            self._model.cobra_model = restored_model

            # Refresh all panels
            self._reaction_table.set_model_data(self._model)
            self._overview.set_model(self._model)
            self._gene_panel.set_model(self._model)
            self._metabolite_panel.set_model(self._model)
            self._reaction_detail.clear()
            self._evidence_panel.clear()
            self._version_panel.set_history(self._version_manager.get_history())

            self._statusbar.showMessage(f"Restored to version {version_id}")
        except Exception as e:
            logger.warning("Failed to restore version: %s", e)
            QMessageBox.critical(self, "Restore Error", str(e))

    def _compare_versions(self, version_a: str, version_b: str) -> None:
        """Show a diff dialog comparing two versions."""
        if not self._version_manager:
            return

        try:
            diff = self._version_manager.compare_versions(version_a, version_b)
            history = self._version_manager.get_history()

            meta_a = next((v for v in history if v.version_id == version_a), None)
            meta_b = next((v for v in history if v.version_id == version_b), None)

            if not meta_a or not meta_b:
                QMessageBox.warning(
                    self, "Compare Error", "Could not find version metadata."
                )
                return

            dialog = DiffDialog(diff, meta_a, meta_b, self)
            dialog.exec()
        except Exception as e:
            logger.warning("Failed to compare versions: %s", e)
            QMessageBox.critical(self, "Compare Error", str(e))

    def _export_version_sbml(self, version_id: str) -> None:
        """Export a specific version as SBML."""
        if not self._version_manager:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export Version SBML",
            f"{version_id}_model.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return

        try:
            import cobra

            model, _ = self._version_manager._storage.load_version(
                self._version_manager._model_id, version_id
            )
            cobra.io.write_sbml_model(model, filepath)
            self._statusbar.showMessage(f"Exported {version_id} to {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _run_qc_for_version(self):
        """Run metabolic task QC and return results."""
        if not self._model or not self._model.cobra_model:
            return None

        try:
            from src.core.task_parser import TaskParser, TaskRunner

            task_file = self._config.default_task_file
            parser = TaskParser()
            tasks = parser.parse(task_file)
            runner = TaskRunner()
            return runner.run_all(self._model.cobra_model, tasks)
        except Exception as e:
            logger.warning("QC run failed: %s", e)
            return None

    # --- Helpers ---

    def _get_selected_reaction(self) -> Reaction | None:
        if not self._model:
            return None
        # Get from reaction table widget
        table = self._reaction_table
        idx = table._table.currentIndex()
        if idx.isValid():
            source_idx = table._proxy.mapToSource(idx)
            return table._model.get_reaction(source_idx.row())
        return None

    def _update_eval_count(self) -> None:
        if not self._model or not self._engine:
            return
        results = self._engine.get_all_results()
        evaluated = sum(1 for ev in results.values() if ev.status == EvaluationStatus.EVALUATED)
        total = self._model.reaction_count
        self._overview.update_evaluation_count(evaluated, total)

    @staticmethod
    def _serialize_raw_data(raw_data: dict | None) -> dict | None:
        """Make raw_data JSON-serializable by converting non-serializable objects."""
        if raw_data is None:
            return None
        result = {}
        for k, v in raw_data.items():
            if hasattr(v, "__dataclass_fields__"):
                # Convert dataclass to dict
                from dataclasses import asdict

                result[k] = asdict(v)
            else:
                result[k] = v
        return result

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        for fp in self._config.recent_files[:10]:
            name = Path(fp).name
            self._recent_menu.addAction(name, lambda p=fp: self._load_model(p))
