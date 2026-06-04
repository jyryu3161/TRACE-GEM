"""Project save/load manager for MetaTaskGapFill."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _sanitize_for_json(obj: object) -> object:
    """Make objects JSON-safe: replace nan/inf, convert non-serializable objects."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (str, int, bool, type(None))):
        return obj
    # Convert non-serializable objects (e.g., KEGGReactionData) to dict or str
    if hasattr(obj, "__dict__"):
        return _sanitize_for_json(vars(obj))
    return str(obj)


@dataclass
class ProjectData:
    """Complete project state container for save/load."""

    format_version: str = "1.0"
    created_at: str = ""
    last_modified: str = ""

    # Model reference
    sbml_path: str = ""
    model_id: str = ""
    model_name: str = ""
    organism_code: str | None = None
    organism_name: str | None = None

    # Evaluation results (reaction_id -> serialized ReactionEvidence)
    evaluation_results: dict[str, dict] = field(default_factory=dict)

    # Gap-fill state
    universal_path: str | None = None
    tasks_path: str | None = None
    task_results_before: list[dict] | None = None
    task_results_after: list[dict] | None = None

    # Universal candidates (serialized CandidateReaction list)
    universal_candidates: list[dict] | None = None

    # Version reference
    current_version_id: str | None = None
    version_dir: str | None = None

    # Settings snapshot (scoring weights only)
    scoring_weights: dict[str, float] = field(default_factory=dict)

    # Runtime (not serialized)
    project_path: str | None = field(default=None, repr=False)


class ProjectManager:
    """Save/load project state as JSON files."""

    GEMP_EXTENSION = ".json"
    FORMAT_VERSION = "1.0"

    @staticmethod
    def save(path: str, project: ProjectData) -> None:
        """Save project to JSON file."""
        project.last_modified = datetime.now(timezone.utc).isoformat()
        if not project.created_at:
            project.created_at = project.last_modified

        data = {
            "format_version": project.format_version,
            "created_at": project.created_at,
            "last_modified": project.last_modified,
            "model": {
                "sbml_path": project.sbml_path,
                "model_id": project.model_id,
                "model_name": project.model_name,
                "organism_code": project.organism_code,
                "organism_name": project.organism_name,
            },
            "evaluation": {
                "results": project.evaluation_results,
            },
            "gapfill": {
                "universal_path": project.universal_path,
                "tasks_path": project.tasks_path,
                "task_results_before": project.task_results_before,
                "task_results_after": project.task_results_after,
                "universal_candidates": project.universal_candidates,
            },
            "version_info": {
                "current_version_id": project.current_version_id,
                "version_dir": project.version_dir,
            },
            "settings": {
                "scoring_weights": project.scoring_weights,
            },
        }
        data = _sanitize_for_json(data)
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def load(path: str) -> ProjectData:
        """Load project from JSON file."""
        raw = json.loads(Path(path).read_text())

        model = raw.get("model", {})
        evaluation = raw.get("evaluation", {})
        gapfill = raw.get("gapfill", {})
        version_info = raw.get("version_info", {})
        settings = raw.get("settings", {})

        return ProjectData(
            format_version=raw.get("format_version", "1.0"),
            created_at=raw.get("created_at", ""),
            last_modified=raw.get("last_modified", ""),
            sbml_path=model.get("sbml_path", ""),
            model_id=model.get("model_id", ""),
            model_name=model.get("model_name", ""),
            organism_code=model.get("organism_code"),
            organism_name=model.get("organism_name"),
            evaluation_results=evaluation.get("results", {}),
            universal_path=gapfill.get("universal_path"),
            tasks_path=gapfill.get("tasks_path"),
            task_results_before=gapfill.get("task_results_before"),
            task_results_after=gapfill.get("task_results_after"),
            universal_candidates=gapfill.get("universal_candidates"),
            current_version_id=version_info.get("current_version_id"),
            version_dir=version_info.get("version_dir"),
            scoring_weights=settings.get("scoring_weights", {}),
            project_path=path,
        )

    @staticmethod
    def from_app_state(window: object) -> ProjectData:
        """Extract project data from MainWindow state."""
        model = window._model
        engine = window._engine
        config = window._config
        vm = window._version_manager

        # Collect evaluation results
        eval_results: dict[str, dict] = {}
        if engine:
            for rid, ev in engine.get_all_results().items():
                eval_results[rid] = ev.to_dict()

        # Gap-fill task results
        task_before = None
        task_after = None
        task_panel = window._task_panel
        if hasattr(task_panel, "_before_map") and task_panel._before_map:
            task_before = [tr.to_dict() for tr in task_panel._before_map.values()]
        if hasattr(task_panel, "_after_map") and task_panel._after_map:
            task_after = [tr.to_dict() for tr in task_panel._after_map.values()]

        # Universal candidates
        universal_candidates_data = None
        universal_table = window._universal_table
        candidates = universal_table.get_candidates()
        if candidates:
            universal_candidates_data = [c.to_dict() for c in candidates]

        return ProjectData(
            sbml_path=getattr(window, "_sbml_filepath", "") or getattr(window, "_loading_filepath", "") or "",
            model_id=model.id if model else "",
            model_name=model.name if model else "",
            organism_code=config.kegg_organism_code,
            organism_name=config.organism_name,
            evaluation_results=eval_results,
            universal_path=window._loaded_universal_path,
            tasks_path=getattr(window, "_loaded_tasks_path", None),
            task_results_before=task_before,
            task_results_after=task_after,
            universal_candidates=universal_candidates_data,
            current_version_id=(
                vm.current_version.version_id if vm and vm.current_version else None
            ),
            version_dir=config.version_dir or None,
            scoring_weights=config.weights,
        )
