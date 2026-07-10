"""Project save/load manager for MetaTaskGapFill."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import math
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import cobra


class _AppState(Protocol):
    _model: Any
    _engine: Any
    _config: Any
    _version_manager: Any
    _task_panel: Any
    _universal_table: Any
    _loaded_universal_path: str | None


class ProjectFormatError(ValueError):
    """Raised when a project snapshot is missing, corrupt, or unsupported."""


def _sanitize_for_json(obj: object) -> object:
    """Make objects JSON-safe: replace nan/inf, convert non-serializable objects."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
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

    format_version: str = "2.0"
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
    cobra_model: cobra.Model | None = field(default=None, repr=False)


class ProjectManager:
    """Save/load project state as JSON files."""

    GEMP_EXTENSION = ".json"
    FORMAT_VERSION = "2.0"
    _MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024

    @staticmethod
    def _portable_path(value: str | None, project_dir: Path) -> str | None:
        if not value:
            return value
        candidate = Path(value).expanduser()
        try:
            return str(candidate.resolve().relative_to(project_dir.resolve()))
        except ValueError:
            return str(candidate)

    @staticmethod
    def _resolve_path(value: str | None, project_dir: Path) -> str | None:
        if not value:
            return value
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = project_dir / candidate
        return str(candidate.resolve())

    @classmethod
    def _encode_model_snapshot(cls, project: ProjectData, project_dir: Path) -> dict | None:
        if project.cobra_model is None:
            return None

        from cobra.io import write_sbml_model

        project_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".model_snapshot_", suffix=".xml", dir=project_dir, delete=False
        ) as handle:
            snapshot_path = Path(handle.name)
        try:
            write_sbml_model(project.cobra_model, str(snapshot_path))
            raw = snapshot_path.read_bytes()
        finally:
            snapshot_path.unlink(missing_ok=True)

        return {
            "encoding": "gzip+base64",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "uncompressed_bytes": len(raw),
            "data": base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii"),
        }

    @classmethod
    def _restore_model_snapshot(cls, path: Path, snapshot: dict) -> str:
        if snapshot.get("encoding") != "gzip+base64":
            raise ProjectFormatError("Unsupported model snapshot encoding")
        try:
            compressed = base64.b64decode(snapshot["data"], validate=True)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                raw = stream.read(cls._MAX_SNAPSHOT_BYTES + 1)
        except (EOFError, KeyError, ValueError, gzip.BadGzipFile) as exc:
            raise ProjectFormatError("Corrupt embedded model snapshot") from exc
        if len(raw) > cls._MAX_SNAPSHOT_BYTES:
            raise ProjectFormatError("Embedded model snapshot exceeds the 512 MiB limit")
        expected_size = snapshot.get("uncompressed_bytes")
        if expected_size is not None and expected_size != len(raw):
            raise ProjectFormatError("Embedded model snapshot size mismatch")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != snapshot.get("sha256"):
            raise ProjectFormatError("Embedded model snapshot SHA-256 mismatch")

        restored_path = path.with_name(f".{path.stem}.model.xml")
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(raw)
        temporary_path.replace(restored_path)
        return str(restored_path.resolve())

    @staticmethod
    def save(path: str, project: ProjectData) -> None:
        """Save project to JSON file."""
        output_path = Path(path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        project.format_version = ProjectManager.FORMAT_VERSION
        project.last_modified = datetime.now(timezone.utc).isoformat()
        if not project.created_at:
            project.created_at = project.last_modified

        data = {
            "format_version": project.format_version,
            "created_at": project.created_at,
            "last_modified": project.last_modified,
            "model": {
                "sbml_path": ProjectManager._portable_path(project.sbml_path, output_path.parent),
                "model_id": project.model_id,
                "model_name": project.model_name,
                "organism_code": project.organism_code,
                "organism_name": project.organism_name,
                "snapshot": ProjectManager._encode_model_snapshot(project, output_path.parent),
            },
            "evaluation": {
                "results": project.evaluation_results,
            },
            "gapfill": {
                "universal_path": ProjectManager._portable_path(
                    project.universal_path, output_path.parent
                ),
                "tasks_path": ProjectManager._portable_path(project.tasks_path, output_path.parent),
                "task_results_before": project.task_results_before,
                "task_results_after": project.task_results_after,
                "universal_candidates": project.universal_candidates,
            },
            "version_info": {
                "current_version_id": project.current_version_id,
                "version_dir": ProjectManager._portable_path(
                    project.version_dir, output_path.parent
                ),
            },
            "settings": {
                "scoring_weights": project.scoring_weights,
            },
        }
        sanitized_data = _sanitize_for_json(data)
        serialized = json.dumps(sanitized_data, indent=2, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
        temporary_path.replace(output_path)

    @staticmethod
    def load(path: str) -> ProjectData:
        """Load project from JSON file."""
        project_path = Path(path).expanduser().resolve()
        raw = json.loads(project_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ProjectFormatError("Project root must be a JSON object")
        format_version = str(raw.get("format_version", "1.0"))
        if format_version not in {"1.0", ProjectManager.FORMAT_VERSION}:
            raise ProjectFormatError(f"Unsupported project format version: {format_version}")

        model = raw.get("model", {})
        evaluation = raw.get("evaluation", {})
        gapfill = raw.get("gapfill", {})
        version_info = raw.get("version_info", {})
        settings = raw.get("settings", {})

        snapshot = model.get("snapshot")
        if snapshot is not None:
            if not isinstance(snapshot, dict):
                raise ProjectFormatError("Model snapshot metadata must be an object")
            sbml_path = ProjectManager._restore_model_snapshot(project_path, snapshot)
        else:
            sbml_path = (
                ProjectManager._resolve_path(model.get("sbml_path", ""), project_path.parent) or ""
            )

        return ProjectData(
            format_version=format_version,
            created_at=raw.get("created_at", ""),
            last_modified=raw.get("last_modified", ""),
            sbml_path=sbml_path,
            model_id=model.get("model_id", ""),
            model_name=model.get("model_name", ""),
            organism_code=model.get("organism_code"),
            organism_name=model.get("organism_name"),
            evaluation_results=evaluation.get("results", {}),
            universal_path=ProjectManager._resolve_path(
                gapfill.get("universal_path"), project_path.parent
            ),
            tasks_path=ProjectManager._resolve_path(gapfill.get("tasks_path"), project_path.parent),
            task_results_before=gapfill.get("task_results_before"),
            task_results_after=gapfill.get("task_results_after"),
            universal_candidates=gapfill.get("universal_candidates"),
            current_version_id=version_info.get("current_version_id"),
            version_dir=ProjectManager._resolve_path(
                version_info.get("version_dir"), project_path.parent
            ),
            scoring_weights=settings.get("scoring_weights", {}),
            project_path=str(project_path),
        )

    @staticmethod
    def from_app_state(window: _AppState) -> ProjectData:
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
            sbml_path=(
                getattr(window, "_sbml_filepath", "")
                or getattr(window, "_loading_filepath", "")
                or ""
            ),
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
            scoring_weights={},
            cobra_model=model.cobra_model if model else None,
        )
