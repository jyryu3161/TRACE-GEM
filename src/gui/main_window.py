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
    QFileDialog,
    QLabel,
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
    ModelData,
    Reaction,
    ReactionEvidence,
)
from src.evidence.engine import EvidenceEngine
from src.gui.delegates import ScoreBarDelegate, StatusDelegate
from src.gui.evidence_panel import EvidencePanelWidget
from src.gui.gene_panel import GenePanelWidget
from src.gui.metabolite_panel import MetabolitePanelWidget
from src.gui.model_overview import ModelOverviewWidget
from src.gui.progress_dialog import ProgressDialog
from src.gui.reaction_detail import ReactionDetailWidget
from src.gui.reaction_table import ReactionTableWidget
from src.gui.score_visualization import ScoreVisualizationWidget
from src.gui.styles import MAIN_STYLESHEET
from src.gui.workers import (
    CloseEngineWorker,
    EvaluateBatchWorker,
    EvaluateReactionWorker,
    InitEngineWorker,
    LoadModelWorker,
)
from src.utils.config import Config
from src.utils.constants import APP_NAME, APP_VERSION

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
        self._active_worker: object | None = None  # prevent GC of QRunnable

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

        # Export menu
        export_menu = menubar.addMenu("E&xport")
        export_menu.addAction("Export &CSV...", self._export_csv, "Ctrl+S")
        export_menu.addAction("Export &JSON...", self._export_json)
        export_menu.addAction("Export &SBML...", self._export_sbml)

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

        self._reaction_table = ReactionTableWidget()
        self._reaction_table.reaction_selected.connect(self._on_reaction_selected)
        left_layout.addWidget(self._reaction_table)

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

        splitter.addWidget(right_tabs)
        splitter.setSizes([600, 500])

        main_layout.addWidget(splitter)

        # Set delegates
        self._score_delegate = ScoreBarDelegate(self._reaction_table)
        self._status_delegate = StatusDelegate(self._reaction_table)
        self._reaction_table.set_delegates(self._score_delegate, self._status_delegate)

    def _setup_statusbar(self) -> None:
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._gemini_status = QLabel()
        self._perplexity_status = QLabel()
        self._statusbar.addPermanentWidget(self._gemini_status)
        self._statusbar.addPermanentWidget(self._perplexity_status)
        self._update_llm_status()

        self._statusbar.showMessage("Ready — Open an SBML model to begin")

    def _update_llm_status(self) -> None:
        """Update the permanent LLM connection indicators in the status bar."""
        if self._config.gemini_api_key and self._config.enable_gemini:
            self._gemini_status.setText(" Gemini: ON ")
            self._gemini_status.setStyleSheet(
                "color: #4caf50; font-weight: bold; margin-right: 8px;"
            )
        else:
            reason = "no key" if not self._config.gemini_api_key else "disabled"
            self._gemini_status.setText(f" Gemini: OFF ({reason}) ")
            self._gemini_status.setStyleSheet(
                "color: #999; margin-right: 8px;"
            )

        if self._config.perplexity_api_key and self._config.enable_perplexity:
            self._perplexity_status.setText(" Perplexity: ON ")
            self._perplexity_status.setStyleSheet(
                "color: #4caf50; font-weight: bold;"
            )
        else:
            reason = "no key" if not self._config.perplexity_api_key else "disabled"
            self._perplexity_status.setText(f" Perplexity: OFF ({reason}) ")
            self._perplexity_status.setStyleSheet("color: #999;")

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
        self._active_worker = worker  # prevent GC before signals are delivered
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
        self._update_llm_status()
        self._statusbar.showMessage("Evidence engine ready")
        logger.info("Evidence engine initialized")

    def _on_engine_init_error(self, token: int, error: str) -> None:
        if token != self._engine_init_token:
            return
        self._engine_error = error
        self._statusbar.showMessage(f"Engine init failed: {error}")

    def _on_engine_init_finished(self, token: int) -> None:
        self._active_worker = None
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
        self._active_worker = worker
        self._thread_pool.start(worker)

    def _on_engine_closed_for_reinit(self) -> None:
        self._active_worker = None
        self._engine_close_in_progress = False
        self._start_engine_init()

    def _close_engine_background(self, engine: EvidenceEngine) -> None:
        worker = CloseEngineWorker(engine)
        worker.signals.error.connect(lambda e: logger.warning("Engine close failed: %s", e))
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
        worker.signals.result.connect(self._on_model_loaded)
        worker.signals.error.connect(self._on_model_error)
        self._thread_pool.start(worker)

    def _on_model_loaded(self, model: object) -> None:
        if not isinstance(model, ModelData):
            return
        self._model = model

        # Update config with detected organism
        needs_reinit = self._engine is None
        if model.kegg_organism_code:
            if model.kegg_organism_code != self._config.kegg_organism_code:
                needs_reinit = True
            self._config.kegg_organism_code = model.kegg_organism_code
        if model.organism:
            if model.organism != self._config.organism_name:
                needs_reinit = True
            self._config.organism_name = model.organism

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
                    "KEGG Score",
                    "Gemini Score",
                    "Perplexity Score",
                    "Substrate Match",
                    "Product Match",
                    "EC Numbers",
                    "KEGG IDs",
                    "Status",
                    "Gemini Analysis",
                    "Perplexity Analysis",
                ]
            )
            for rxn in self._model.reactions:
                ev = results.get(rxn.id, ReactionEvidence(rxn.id))
                gemini_desc = ""
                pplx_desc = ""
                for item in ev.items:
                    if item.source == EvidenceSource.GEMINI:
                        gemini_desc = item.description
                    elif item.source == EvidenceSource.PERPLEXITY:
                        pplx_desc = item.description
                writer.writerow(
                    [
                        rxn.id,
                        rxn.name,
                        rxn.subsystem or "",
                        ";".join(rxn.genes),
                        rxn.gene_reaction_rule,
                        f"{ev.confidence_score:.4f}",
                        f"{ev.kegg_score:.4f}",
                        f"{ev.gemini_score:.4f}",
                        f"{ev.perplexity_score:.4f}",
                        f"{ev.substrate_match_ratio:.4f}",
                        f"{ev.product_match_ratio:.4f}",
                        ";".join(ev.ec_numbers),
                        ";".join(ev.kegg_reaction_ids),
                        ev.status.value,
                        gemini_desc,
                        pplx_desc,
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
                    "kegg": ev.kegg_score,
                    "gemini": ev.gemini_score,
                    "perplexity": ev.perplexity_score,
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
                    right.setCurrentIndex(3)  # Charts tab
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
            "<p>Evaluates reactions in SBML models against KEGG, Gemini, "
            "and Perplexity to verify reaction evidence.</p>",
        )

    def _show_settings(self) -> None:
        from src.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._config.save()
            self._update_llm_status()
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
