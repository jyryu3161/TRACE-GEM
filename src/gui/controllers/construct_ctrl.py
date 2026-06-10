"""Construct controller — manages CarveMe model construction and handoff."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from src.gui.workers import BatchBuildWorker, BuildModelWorker
from src.utils.constants import KEGG_CODE_TO_NAME

# Safety cap for waiting on the evidence engine to (re)initialize before a
# build→refine gap-fill. The engine init is local (cache/mapping load) and fast;
# if it somehow stalls we proceed anyway (gap-fill handles a null engine: the
# organism filter is built from the model's own KEGG code).
_ENGINE_WAIT_TIMEOUT_MS = 30000
_ENGINE_WAIT_INTERVAL_MS = 200

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow

logger = logging.getLogger("metataskgapfill.gui.construct")


class ConstructController:
    """Drives the Build panel: single/batch CarveMe builds and the handoff
    of built models into the evaluator (task/gap-fill) pipeline."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window
        self._worker: object | None = None
        self._refine_wait_timer: QTimer | None = None

    # -- navigation ---------------------------------------------------------

    def open_build_panel(self) -> None:
        panel = getattr(self._w, "_build_panel", None)
        if panel is not None:
            self._w._right_tabs.setCurrentWidget(panel)

    # -- availability -------------------------------------------------------

    def _options(self, spec: dict):
        from src.build.build_engine import BuildEngine

        engine = BuildEngine(self._w._config)
        return engine.options_from_config(
            solver=spec.get("solver") or None,
            universe=spec.get("universe") or None,
            gapfill_media=spec.get("gapfill_media") or None,
            init_medium=spec.get("init_medium") or None,
            gzip_output=bool(spec.get("gzip")),
            dna=bool(spec.get("dna")),
        )

    # -- single build -------------------------------------------------------

    def start_single_build(self, refine_after: bool = False) -> None:
        panel = self._w._build_panel
        spec = panel.get_single_spec()
        fasta = spec.get("fasta", "")
        if not fasta or not Path(fasta).exists():
            QMessageBox.warning(self._w, "Build", "Select a valid protein FASTA file.")
            return
        # CarveMe toolchain availability is checked inside the worker (off the GUI
        # thread) so the carve/diamond subprocess probes don't freeze the UI.

        kegg = spec.get("kegg_code") or None
        options = self._options(spec)
        output = spec.get("output") or None

        panel.clear_log()
        panel.set_busy(True)
        panel.append_log(f"Building {Path(fasta).name} (solver={options.solver})...")

        worker = BuildModelWorker(self._w._config, fasta, kegg, options, output)
        self._worker = worker
        self._w._active_workers.append(worker)
        worker.signals.line.connect(panel.append_log)
        worker.signals.result.connect(
            lambda built: self._on_single_built(built, refine_after)
        )
        worker.signals.error.connect(self._on_build_error)
        worker.signals.finished.connect(lambda: self._on_worker_finished(worker))
        self._w._thread_pool.start(worker)

    def _on_single_built(self, built: object, refine_after: bool) -> None:
        md = built.model_data  # type: ignore[attr-defined]
        label = f"{md.id} ({md.reaction_count} rxn, {md.gene_count} gene)"
        self._w._build_panel.add_built(built, label, ok=True)
        self._w._build_panel.append_log(f"Built {label} -> {built.sbml_path}")  # type: ignore[attr-defined]
        self._w._statusbar.showMessage(f"Built model {md.id}: {md.reaction_count} reactions")
        if refine_after:
            self._handoff(built)
            self._start_refine_when_engine_ready()

    # -- batch build --------------------------------------------------------

    def start_batch_build(self) -> None:
        from src.build.build_manifest import BuildJob

        panel = self._w._build_panel
        raw_jobs = panel.get_batch_jobs()
        if not raw_jobs:
            QMessageBox.warning(self._w, "Batch build", "Add at least one row with a FASTA file.")
            return

        jobs: list[BuildJob] = []
        problems: list[str] = []
        for i, d in enumerate(raw_jobs, start=1):
            fasta = d["fasta"]
            if not Path(fasta).exists():
                problems.append(f"row {i}: fasta not found: {fasta}")
                continue
            if not d.get("kegg_code"):
                problems.append(f"row {i}: missing KEGG code")
                continue
            jobs.append(
                BuildJob(
                    fasta_path=Path(fasta),
                    kegg_code=d["kegg_code"],
                    universe=d.get("universe", ""),
                    medium=d.get("medium", ""),
                    label=d.get("label", ""),
                )
            )
        if problems:
            QMessageBox.critical(self._w, "Batch build", "\n".join(problems))
            return
        # Availability checked inside the worker (off the GUI thread).

        options = self._options(panel.get_options_spec())
        output_dir = panel.get_batch_output_dir() or None

        panel.clear_log()
        panel.clear_results()
        panel.set_busy(True)
        panel.append_log(f"Batch building {len(jobs)} model(s)...")

        worker = BatchBuildWorker(self._w._config, jobs, options, output_dir)
        self._worker = worker
        self._w._active_workers.append(worker)
        worker.signals.line.connect(panel.append_log)
        worker.signals.model_built.connect(self._on_model_built)
        worker.signals.progress.connect(
            lambda done, total, label: self._w._statusbar.showMessage(
                f"Building models: {done}/{total} ({label})"
            )
        )
        worker.signals.result.connect(self._on_batch_done)
        worker.signals.error.connect(self._on_build_error)
        worker.signals.finished.connect(lambda: self._on_worker_finished(worker))
        self._w._thread_pool.start(worker)

    def _on_model_built(self, item: object) -> None:
        ok = bool(getattr(item, "ok", False))
        job = getattr(item, "job", None)
        label = getattr(job, "label", "model")
        if ok:
            md = item.built.model_data  # type: ignore[attr-defined]
            self._w._build_panel.add_built(
                item, f"{label}: {md.id} ({md.reaction_count} rxn)", ok=True
            )
        else:
            err = getattr(item, "error", "build failed")
            self._w._build_panel.add_built(item, f"{label}: FAILED — {err}", ok=False)

    def _on_batch_done(self, results: object) -> None:
        items = results if isinstance(results, list) else []
        ok = sum(1 for r in items if getattr(r, "ok", False))
        self._w._statusbar.showMessage(f"Batch complete: {ok}/{len(items)} model(s) built")
        self._w._build_panel.append_log(f"Batch complete: {ok}/{len(items)} built")

    # -- handoff / refine ---------------------------------------------------

    def send_to_evaluator(self, built: object) -> None:
        self._handoff(built)

    def refine_selected(self, built: object) -> None:
        self._handoff(built)
        self._start_refine_when_engine_ready()

    def _engine_ready(self) -> bool:
        w = self._w
        return (
            w._engine is not None
            and not w._engine_init_in_progress
            and not w._pending_engine_init
        )

    def _start_refine_when_engine_ready(self) -> None:
        """Launch the gap-fill workflow, but only once the evidence engine has
        finished (re)initializing for the built organism — handing off a model
        triggers an async engine reinit, and starting gap-fill before it is ready
        would run with a stale/null engine (wrong-organism evidence)."""
        if self._engine_ready():
            self._w._gapfill_ctrl.start_workflow()
            return

        self._w._statusbar.showMessage(
            "Waiting for the evidence engine to initialize for the built organism..."
        )
        elapsed = {"ms": 0}
        timer = QTimer(self._w)
        self._refine_wait_timer = timer  # keep a reference so it isn't GC'd

        def _check() -> None:
            elapsed["ms"] += _ENGINE_WAIT_INTERVAL_MS
            if self._engine_ready() or elapsed["ms"] >= _ENGINE_WAIT_TIMEOUT_MS:
                timer.stop()
                self._refine_wait_timer = None
                self._w._gapfill_ctrl.start_workflow()

        timer.timeout.connect(_check)
        timer.start(_ENGINE_WAIT_INTERVAL_MS)

    def _handoff(self, built: object) -> None:
        """Route a built model into the full evaluator pipeline (reuses the
        canonical model-load path so every panel + versioning is wired up)."""
        md = built.model_data  # type: ignore[attr-defined]
        organism_changed = False
        if md.kegg_organism_code:
            old_code = self._w._config.kegg_organism_code
            self._w._config.kegg_organism_code = md.kegg_organism_code
            self._w._config.organism_name = md.organism or KEGG_CODE_TO_NAME.get(
                md.kegg_organism_code, md.kegg_organism_code
            )
            # We already know the organism — don't prompt again.
            self._w._skip_organism_dialog = True
            organism_changed = md.kegg_organism_code != old_code
        self._w._loading_filepath = str(built.sbml_path)  # type: ignore[attr-defined]
        self._w._on_model_loaded(md)
        # _on_model_loaded reinitializes the evidence engine only when it is None
        # or it detects an organism change; since we pre-set the organism above,
        # that detection is defeated. Force a reinit when the organism actually
        # changed so the engine (and organism filter) match the built model.
        if organism_changed:
            self._w._init_engine()
        self._w._statusbar.showMessage(
            f"Loaded built model {md.id} into evaluator ({md.reaction_count} reactions)"
        )

    # -- worker lifecycle ---------------------------------------------------

    def cancel(self) -> None:
        if self._worker is not None and hasattr(self._worker, "cancel"):
            self._worker.cancel()  # type: ignore[attr-defined]
            self._w._build_panel.append_log("Cancellation requested...")

    def _on_build_error(self, error: str) -> None:
        # Cancellation arrives via the same error signal — present it neutrally,
        # not as a critical failure dialog.
        if "cancel" in error.lower():
            self._w._build_panel.append_log("Build cancelled.")
            self._w._statusbar.showMessage("Build cancelled")
            return
        self._w._build_panel.append_log(f"ERROR: {error}")
        QMessageBox.critical(self._w, "Build failed", error)
        self._w._statusbar.showMessage("Build failed")

    def _on_worker_finished(self, worker: object) -> None:
        if worker in self._w._active_workers:
            self._w._active_workers.remove(worker)
        if self._worker is worker:
            self._worker = None
        self._w._build_panel.set_busy(False)
