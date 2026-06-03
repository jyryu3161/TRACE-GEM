"""Main application window."""

from __future__ import annotations

import asyncio
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
    ModelData,
    Reaction,
    TaskResult,
    WorkflowCheckpoint,
)
from src.evidence.engine import EvidenceEngine
from src.gui.candidate_table import CandidateTableWidget
from src.gui.controllers.evaluation_ctrl import EvaluationController
from src.gui.controllers.export_ctrl import ExportController
from src.gui.controllers.gapfill_ctrl import GapFillController
from src.gui.controllers.version_ctrl import VersionController
from src.gui.delegates import ScoreBarDelegate, StatusDelegate
from src.gui.evidence_panel import EvidencePanelWidget
from src.gui.gapfill_panel import GapFillPanelWidget
from src.gui.gene_panel import GenePanelWidget
from src.gui.metabolite_panel import MetabolitePanelWidget
from src.gui.model_overview import ModelOverviewWidget
from src.gui.reaction_detail import ReactionDetailWidget
from src.gui.reaction_table import ReactionTableWidget
from src.gui.score_visualization import ScoreVisualizationWidget
from src.gui.styles import MAIN_STYLESHEET
from src.gui.task_panel import TaskPanelWidget
from src.gui.version_panel import VersionPanelWidget
from src.gui.workers import (
    CloseEngineWorker,
    EvaluateBatchWorker,
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
        self._gapfill_worker = None
        self._version_manager: VersionManager | None = None
        self._workflow_checkpoint: WorkflowCheckpoint | None = None
        self._loaded_universal_path: str | None = None
        self._loaded_tasks: list | None = None
        self._loaded_tasks_path: str | None = None

        # Project save/load state
        self._project_path: str | None = None
        self._project_dirty: bool = False
        self._pending_project = None
        self._pending_restore = None  # Deferred project restore (wait for engine)
        self._skip_organism_dialog: bool = False

        # Controllers
        self._eval_ctrl = EvaluationController(self)
        self._gapfill_ctrl = GapFillController(self)
        self._export_ctrl = ExportController(self)
        self._version_ctrl = VersionController(self)

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
        file_menu.addAction("Open &Project...", self._open_project, "Ctrl+Shift+O")
        self._recent_menu = file_menu.addMenu("Recent Models")
        self._recent_projects_menu = file_menu.addMenu("Recent Projects")
        self._update_recent_menu()
        self._update_recent_projects_menu()
        file_menu.addSeparator()
        file_menu.addAction("&Save Project", self._save_project, "Ctrl+S")
        file_menu.addAction("Save Project &As...", self._save_project_as)
        file_menu.addSeparator()
        file_menu.addAction("Load &Universal Model...", self._gapfill_ctrl.load_universal_model)
        file_menu.addAction("Load Metabolic &Tasks...", self._gapfill_ctrl.load_task_file)
        file_menu.addSeparator()
        file_menu.addAction("&Save Version...", self._version_ctrl.save_version, "Ctrl+Shift+S")
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
        eval_menu.addAction("Evaluate &Selected", self._eval_ctrl.evaluate_selected, "Ctrl+E")
        eval_menu.addAction("Evaluate &All", self._eval_ctrl.evaluate_all, "Ctrl+Shift+E")
        eval_menu.addSeparator()
        eval_menu.addAction("&Clear Results", self._eval_ctrl.clear_results)

        # Analysis menu
        analysis_menu = menubar.addMenu("&Analysis")
        analysis_menu.addAction("Task-Based &Gap-Filling...", self._gapfill_ctrl.start_workflow, "Ctrl+W")

        # Export menu
        export_menu = menubar.addMenu("E&xport")
        export_menu.addAction("Export &CSV...", self._export_ctrl.export_csv)
        export_menu.addAction("Export &JSON...", self._export_ctrl.export_json)
        export_menu.addAction("Export &SBML...", self._export_ctrl.export_sbml)
        export_menu.addSeparator()
        export_menu.addAction("Export &Improved SBML...", self._export_ctrl.export_improved_sbml)

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

        # Left tabs: Model Reactions + Universal
        self._left_tabs = QTabWidget()

        self._reaction_table = ReactionTableWidget()
        self._reaction_table.reaction_selected.connect(self._on_reaction_selected)
        self._reaction_table.removal_requested.connect(self._on_removal_requested)
        self._left_tabs.addTab(self._reaction_table, "Model Reactions")

        # Universal tab
        self._universal_table = CandidateTableWidget()
        self._universal_table.candidate_selected.connect(self._gapfill_ctrl.on_universal_selected)
        self._universal_table.evaluate_requested.connect(self._gapfill_ctrl.evaluate_universal_candidates)
        self._left_tabs.addTab(self._universal_table, "Universal")

        self._left_tabs.currentChanged.connect(lambda _: self._update_charts())
        left_layout.addWidget(self._left_tabs)

        splitter.addWidget(left_widget)

        # Right side — tabs for detail views
        right_tabs = QTabWidget()

        # Detail tab
        self._reaction_detail = ReactionDetailWidget()
        self._reaction_detail.evaluate_requested.connect(self._eval_ctrl.evaluate_reaction_by_id)
        self._reaction_detail.reaction_modified.connect(self._version_ctrl.on_reaction_modified)
        self._reaction_detail.removal_requested.connect(self._on_removal_requested)
        right_tabs.addTab(self._reaction_detail, "Detail")

        # Evidence tab
        self._evidence_panel = EvidencePanelWidget()
        right_tabs.addTab(self._evidence_panel, "Evidence")

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
        self._gapfill_panel.apply_requested.connect(self._gapfill_ctrl.on_apply_gapfill)
        self._gapfill_panel.export_sbml_requested.connect(self._export_ctrl.export_improved_sbml)
        self._gapfill_panel.export_report_requested.connect(self._export_ctrl.export_gapfill_report)
        right_tabs.addTab(self._gapfill_panel, "Gap-Fill")

        # Versions tab
        self._version_panel = VersionPanelWidget()
        self._version_panel.restore_requested.connect(self._version_ctrl.restore_version)
        self._version_panel.compare_requested.connect(self._version_ctrl.compare_versions)
        self._version_panel.export_requested.connect(self._version_ctrl.export_version_sbml)
        self._version_panel.detail_requested.connect(self._version_ctrl.show_version_detail)
        self._version_panel.rename_requested.connect(self._version_ctrl.rename_version)
        self._version_panel.description_updated.connect(self._version_ctrl.update_description)
        self._version_panel.delete_requested.connect(self._version_ctrl.delete_version)
        right_tabs.addTab(self._version_panel, "Versions")

        self._right_tabs = right_tabs

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

        self._source_status_labels: dict[str, QLabel] = {}
        self._update_source_status()

        self._statusbar.showMessage("Ready — Open an SBML model to begin")

    def _update_source_status(self) -> None:
        """Update the permanent source connection indicators in the status bar."""
        # Disabled: KEGG + BiGG 2-source 단순화 후 인디케이터가 정보 가치 없음.
        # Disabled intentionally — see comment above (re-enable: remove this return).
        # Source 추가 시 아래 return 한 줄을 제거하면 부활.
        return
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

        # Apply deferred project restore now that engine is ready
        # But only if no further engine reinit is pending
        if self._pending_restore is not None and not self._pending_engine_init:
            project = self._pending_restore
            self._pending_restore = None
            self._apply_deferred_restore(project)

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
        self._workflow_checkpoint = None  # Clear checkpoint on new model load

        # Skip organism dialog when loading from a project file
        if self._skip_organism_dialog:
            self._skip_organism_dialog = False
            result = (self._config.kegg_organism_code, self._config.organism_name)
        else:
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
            self._sbml_filepath = filepath
            self._loading_filepath = ""

        # Initialize version control
        if self._config.enable_versioning and model.cobra_model:
            try:
                self._version_manager = VersionManager(self._config)
                self._version_manager.set_base_model(model.cobra_model, model.id)
                current_vid = (
                    self._version_manager.current_version.version_id
                    if self._version_manager.current_version
                    else None
                )
                self._version_panel.set_history(
                    self._version_manager.get_history(), current_vid
                )
            except Exception as e:
                logger.warning("Version manager init failed: %s", e)
                self._version_manager = None

        self._statusbar.showMessage(
            f"{model.id} | {model.reaction_count} reactions | "
            f"{model.gene_count} genes | {model.metabolite_count} metabolites"
        )
        logger.info("Model loaded: %s", model.id)

        # Restore project state if loading from a project file
        pending = self._pending_project
        if pending:
            self._pending_project = None
            self._restore_project_state(pending)

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

        self._reaction_detail.set_read_only(False)
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

    # --- Reaction removal ---

    def _on_removal_requested(self, reaction_id: str) -> None:
        """Handle reaction removal request from table or detail panel."""
        if not self._model or not self._model.cobra_model:
            return

        rxn = self._model.get_reaction(reaction_id)
        if not rxn:
            return

        # If tasks are loaded, show impact preview dialog
        if self._loaded_tasks:
            from src.gui.reaction_removal_dialog import ReactionRemovalDialog

            current_results = self._get_current_task_results()
            dialog = ReactionRemovalDialog(
                reaction=rxn,
                cobra_model=self._model.cobra_model,
                tasks=self._loaded_tasks,
                current_results=current_results,
                parent=self,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._execute_removal(reaction_id)
        else:
            # Simple confirmation without task preview
            reply = QMessageBox.question(
                self,
                "Remove Reaction",
                f"Remove reaction '{reaction_id}' ({rxn.name})?\n\n"
                "No metabolic tasks loaded — impact preview unavailable.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._execute_removal(reaction_id)

    def _execute_removal(self, reaction_id: str) -> None:
        """Remove reaction from both cobra and internal models."""
        import cobra

        cm = self._model.cobra_model
        if isinstance(cm, cobra.Model):
            try:
                cobra_rxn = cm.reactions.get_by_id(reaction_id)
                cm.remove_reactions([cobra_rxn], remove_orphans=True)
            except KeyError:
                pass

        self._model.remove_reaction(reaction_id)

        # Refresh UI
        self._reaction_table.set_model_data(self._model)
        self._reaction_detail.clear()
        self._overview.set_model(self._model)

        # Auto-save version
        if (
            self._config.auto_save_on_edit
            and self._version_manager
            and self._model.cobra_model
        ):
            self._version_ctrl.auto_save_version("reaction_removal")

        self._mark_dirty()
        self._statusbar.showMessage(f"Reaction '{reaction_id}' removed")

    def _get_current_task_results(self) -> list[TaskResult]:
        """Get current task results, running simulation if needed."""
        from src.core.task_parser import TaskRunner

        if self._task_panel._before_map:
            return list(self._task_panel._before_map.values())
        if self._model and self._model.cobra_model and self._loaded_tasks:
            runner = TaskRunner()
            return runner.run_all(self._model.cobra_model, self._loaded_tasks)
        return []

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
        if not self._engine:
            return

        all_results = self._engine.get_all_results()
        if not all_results:
            return

        # Determine which results to show based on active left tab
        is_universal = self._left_tabs.currentWidget() is self._universal_table
        if is_universal:
            candidate_ids = {
                c.reaction.id for c in self._universal_table.get_candidates()
            }
            results = {
                rid: ev for rid, ev in all_results.items() if rid in candidate_ids
            }
            subsystem_map = {}
        else:
            if not self._model:
                return
            model_ids = {r.id for r in self._model.reactions}
            results = {
                rid: ev for rid, ev in all_results.items() if rid in model_ids
            }
            subsystem_map = {
                r.id: r.subsystem or "Unknown" for r in self._model.reactions
            }

        if not results:
            return
        self._chart_widget.update_charts(results, subsystem_map)

    # --- Help ---

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About GEM Evaluator",
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            "<p>Genome-Scale Metabolic Model Evidence Evaluator</p>"
            "<p>Evaluates reactions in SBML models against KEGG, BiGG, UniProt, "
            "PubMed, Gemini, and Perplexity to verify reaction evidence.</p>",
        )

    def _show_settings(self) -> None:
        from src.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self._config, self)
        if dialog.exec():
            self._config.save()
            self._update_source_status()
            self._init_engine()  # Reinit with new settings

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        if self._project_dirty and self._model:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save project before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_project()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        if self._batch_worker:
            self._batch_worker.cancel()

        if self._engine:
            engine = self._engine
            self._engine = None
            try:
                loop = asyncio.new_event_loop()
                # asyncio.set_event_loop removed (deprecated in Python 3.12+)
                try:
                    loop.run_until_complete(engine.close())
                finally:
                    loop.close()
            except Exception as e:
                logger.warning("Engine close during shutdown failed: %s", e)

        super().closeEvent(event)

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
        self._mark_dirty()

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        for fp in self._config.recent_files[:10]:
            name = Path(fp).name
            self._recent_menu.addAction(name, lambda p=fp: self._load_model(p))

    def _update_recent_projects_menu(self) -> None:
        self._recent_projects_menu.clear()
        for fp in self._config.recent_projects[:10]:
            name = Path(fp).name
            self._recent_projects_menu.addAction(name, lambda p=fp: self._load_project(p))

    # --- Project save/load ---

    def _save_project(self) -> None:
        """Save project to current path, or prompt for path."""
        if self._project_path:
            self._do_save_project(self._project_path)
        else:
            self._save_project_as()

    def _save_project_as(self) -> None:
        """Save project to a new path."""
        if not self._model:
            QMessageBox.warning(self, "Save Project", "No model loaded.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project",
            f"{self._model.id}.json",
            "GEM Project (*.json)",
        )
        if path:
            if not path.endswith(".json"):
                path += ".json"
            self._do_save_project(path)

    def _do_save_project(self, path: str) -> None:
        """Actual save logic."""
        from src.core.project_manager import ProjectManager

        try:
            project = ProjectManager.from_app_state(self)
            project.project_path = path
            ProjectManager.save(path, project)
            self._project_path = path
            self._project_dirty = False
            self._update_title()
            self._config.add_recent_project(path)
            self._config.save()
            self._update_recent_projects_menu()
            self._statusbar.showMessage(f"Project saved: {path}", 5000)
        except Exception as e:
            QMessageBox.critical(
                self, "Save Error", f"Failed to save project:\n{e}"
            )
            import traceback
            traceback.print_exc()

    def _open_project(self) -> None:
        """Open a project file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "GEM Project (*.json)"
        )
        if path:
            self._load_project(path)

    def _load_project(self, path: str) -> None:
        """Load project and restore state."""
        import json as _json

        from src.core.project_manager import ProjectManager

        try:
            project = ProjectManager.load(path)
        except (_json.JSONDecodeError, KeyError) as e:
            QMessageBox.critical(self, "Error", f"Invalid project file:\n{e}")
            return

        # SBML file existence check
        if not Path(project.sbml_path).exists():
            new_path, _ = QFileDialog.getOpenFileName(
                self,
                f"SBML file not found: {project.sbml_path}",
                "",
                "SBML Files (*.xml *.sbml)",
            )
            if not new_path:
                return
            project.sbml_path = new_path

        # Restore settings
        if project.organism_code:
            self._config.kegg_organism_code = project.organism_code
        if project.organism_name:
            self._config.organism_name = project.organism_name
        if project.scoring_weights:
            for key, val in project.scoring_weights.items():
                attr = f"weight_{key}"
                if hasattr(self._config, attr):
                    setattr(self._config, attr, val)
            self._config.save()
            self._init_engine()

        # Load model (skip organism dialog since we restored settings)
        self._pending_project = project
        self._loading_filepath = project.sbml_path
        self._sbml_filepath = project.sbml_path
        self._skip_organism_dialog = True
        self._load_model(project.sbml_path)

        # Update recent projects
        self._config.add_recent_project(path)
        self._config.save()
        self._update_recent_projects_menu()

    def _restore_project_state(self, project: object) -> None:
        """Restore evaluation results, universal candidates, and gap-fill state."""
        from src.core.models import (
            CandidateReaction,
            TaskResult,
        )

        # Restore universal candidates (does not depend on engine)
        if project.universal_candidates:
            candidates = [
                CandidateReaction.from_dict(d)
                for d in project.universal_candidates
            ]
            self._universal_table.set_candidates(candidates)
        elif project.universal_path and self._model:
            # Candidates weren't saved — reload from universal model file
            self._reload_universal_from_path(project.universal_path)

        # Restore gap-fill task results (does not depend on engine)
        if project.task_results_before is not None:
            before = [TaskResult.from_dict(d) for d in project.task_results_before]
            after = (
                [TaskResult.from_dict(d) for d in project.task_results_after]
                if project.task_results_after
                else []
            )
            self._task_panel.set_results(before, after)

        # Restore paths
        self._loaded_universal_path = project.universal_path
        self._loaded_tasks_path = project.tasks_path
        self._project_path = project.project_path
        self._project_dirty = False
        self._update_title()

        # Evaluation results require the engine — defer if engine is initializing
        if project.evaluation_results:
            if self._engine and not self._engine_init_in_progress and not self._pending_engine_init:
                self._apply_deferred_restore(project)
            else:
                logger.info("Engine not ready — deferring evaluation result restore")
                self._pending_restore = project

    def _apply_deferred_restore(self, project: object) -> None:
        """Apply evaluation results to the current (ready) engine."""
        from src.core.models import ReactionEvidence

        if not self._engine or not project.evaluation_results:
            return

        for rid, ev_dict in project.evaluation_results.items():
            evidence = ReactionEvidence.from_dict(ev_dict)
            self._engine._results[rid] = evidence

        all_results = self._engine.get_all_results()

        # Update model reaction table
        self._reaction_table.update_all_evidence(all_results)

        # Update universal candidate table
        if self._universal_table.get_candidates():
            self._universal_table._model.set_evidence(all_results)

        # Update overview count (model reactions only)
        if self._model:
            model_ids = {r.id for r in self._model.reactions}
            model_evaluated = sum(
                1 for rid in all_results if rid in model_ids
            )
            self._overview.update_evaluation_count(
                model_evaluated, self._model.reaction_count,
            )

        # Update charts
        self._update_charts()
        logger.info("Project evaluation results restored: %d reactions", len(project.evaluation_results))

    def _reload_universal_from_path(self, filepath: str) -> None:
        """Reload universal candidates from file when not saved in project."""
        from pathlib import Path as _Path

        if not _Path(filepath).exists():
            logger.warning("Universal model file not found: %s", filepath)
            return
        try:
            from src.core.universal_loader import UniversalLoader

            loader = UniversalLoader()
            universal_model = loader.load(filepath)
            candidates = loader.extract_candidates(universal_model, self._model)

            total = len(universal_model.reactions)
            excluded = total - len(candidates)
            self._overview.set_universal_info(
                model_id=universal_model.id,
                total_reactions=total,
                excluded=excluded,
                candidates=len(candidates),
            )
            self._universal_table.set_candidates(candidates)
            logger.info(
                "Universal model reloaded from %s: %d candidates", filepath, len(candidates),
            )
        except Exception as e:
            logger.warning("Failed to reload universal model: %s", e)

    def _mark_dirty(self) -> None:
        """Mark project as having unsaved changes."""
        if not self._project_dirty:
            self._project_dirty = True
            self._update_title()

    def _update_title(self) -> None:
        """Update window title with project name and dirty indicator."""
        title = f"{APP_NAME} v{APP_VERSION}"
        if self._model:
            title += f" — {self._model.id}"
        if self._project_path:
            title += f" [{Path(self._project_path).name}]"
        if self._project_dirty:
            title += " *"
        self.setWindowTitle(title)
