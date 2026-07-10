"""Machine-readable run provenance for reproducible model evaluation."""

from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.gapfill.penalty_calculator import PenaltyCalculator
from src.utils.constants import APP_NAME, APP_VERSION, DATA_DIR, KEGG_API_BASE

if TYPE_CHECKING:
    import cobra

    from src.core.models import GapFillResult
    from src.utils.config import Config


def file_record(path: str | Path | None) -> dict[str, Any] | None:
    """Return a resolved path, byte count, and SHA-256 for an input/output file."""
    if not path:
        return None
    resolved = Path(path).expanduser().resolve()
    record: dict[str, Any] = {"path": str(resolved), "exists": resolved.is_file()}
    if resolved.is_file():
        digest = hashlib.sha256()
        size = 0
        with resolved.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        record.update({"bytes": size, "sha256": digest.hexdigest()})
    return record


def _software_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for distribution in (
        "cobra",
        "optlang",
        "python-libsbml",
        "numpy",
        "scipy",
        "aiohttp",
        "aiosqlite",
    ):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = "not-installed"
    return versions


def _git_state() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unavailable", "dirty": None}


def _solver_record(model: cobra.Model | None) -> dict[str, Any]:
    if model is None:
        return {}
    try:
        interface = model.solver.interface.__name__
    except (AttributeError, RuntimeError):
        interface = "unknown"
    return {
        "optlang_interface": interface,
        "objective_direction": getattr(model.objective, "direction", "unknown"),
    }


def _mapping_records() -> dict[str, Any]:
    names = (
        "bigg_universal_model_fixed.json",
        "reac_xref.tsv",
        "reaction_analysis_result.tsv",
        "bigg_models_reactions.txt",
        "bigg_models_metabolites.txt",
    )
    return {name: file_record(DATA_DIR / name) for name in names}


def _config_snapshot(config: Config) -> dict[str, Any]:
    """Exclude GUI history/state that is irrelevant and potentially private."""
    excluded = {"recent_files", "recent_projects", "window_geometry"}
    return {key: value for key, value in asdict(config).items() if key not in excluded}


def build_gapfill_manifest(
    *,
    config: Config,
    result: GapFillResult,
    model: cobra.Model | None,
    inputs: dict[str, str | Path | None],
    outputs: dict[str, str | Path | None],
    command: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete, JSON-safe provenance document for one gap-fill run."""
    tier_counts = Counter(
        evidence.evidence_tier.value for evidence in result.evidence_results.values()
    )
    status_counts = Counter(evidence.status.value for evidence in result.evidence_results.values())
    return {
        "schema_version": "1.0",
        "run_type": "task_aware_gapfill",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "application": {"name": APP_NAME, "version": APP_VERSION},
        "command": command if command is not None else list(sys.argv),
        "platform": platform.platform(),
        "software": _software_versions(),
        "git": _git_state(),
        "solver": _solver_record(model),
        "inputs": {name: file_record(path) for name, path in inputs.items()},
        "outputs": {name: file_record(path) for name, path in outputs.items()},
        "mapping_files": _mapping_records(),
        "external_evidence": {
            "source": "KEGG REST",
            "base_url": KEGG_API_BASE,
            "organism_code": config.kegg_organism_code,
            "database_release": "unavailable_from_rest_api",
            "cache_policy": "SQLite TTL cache; results may mix cached and live responses",
            "error_fraction_limit": config.candidate_evidence_max_error_fraction,
            "evaluated_candidates": len(result.evidence_results),
            "status_counts": dict(sorted(status_counts.items())),
            "tier_counts": dict(sorted(tier_counts.items())),
        },
        "configuration": _config_snapshot(config),
        "penalty_policy": PenaltyCalculator(config).parameters(),
        "result": {
            "total_tasks": result.total_tasks,
            "tasks_fixed": result.tasks_fixed,
            "tasks_broken": result.tasks_broken,
            "iterations": result.iterations,
            "added_reaction_ids": [c.reaction.id for c in result.added_reactions],
            "infeasible_task_ids": list(result.infeasible_tasks),
        },
        "extra": extra or {},
    }


def build_construction_manifest(
    *,
    config: Config,
    carve_result: Any,
    availability: Any | None = None,
) -> dict[str, Any]:
    """Build provenance for a CarveMe model-construction subprocess."""
    options = asdict(carve_result.options) if carve_result.options is not None else {}
    toolchain = (
        asdict(availability)
        if availability is not None
        else {
            "carve_version": "not-probed",
            "diamond_version": "not-probed",
            "solver_name": options.get("solver", ""),
        }
    )
    universe_file = options.get("universe_file")
    return {
        "schema_version": "1.0",
        "run_type": "carveme_model_construction",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "application": {"name": APP_NAME, "version": APP_VERSION},
        "platform": platform.platform(),
        "software": _software_versions(),
        "git": _git_state(),
        "command": list(carve_result.argv),
        "inputs": {
            "fasta": file_record(carve_result.fasta_path),
            "universe_file": file_record(universe_file),
        },
        "outputs": {"model": file_record(carve_result.output_path)},
        "toolchain": toolchain,
        "carveme_options": options,
        "configuration": _config_snapshot(config),
        "result": {
            "returncode": carve_result.returncode,
            "duration_seconds": carve_result.duration_s,
            "cancelled": carve_result.cancelled,
            "error": carve_result.error,
            "organism_code": carve_result.kegg_code,
        },
    }


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    """Atomically write a provenance manifest as deterministic, indented JSON."""
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
    temporary.replace(output)
    return output


def write_evidence_snapshot(path: str | Path, result: GapFillResult) -> Path:
    """Atomically preserve every candidate evidence record used by the solver."""
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "records": {
            reaction_id: evidence.to_dict()
            for reaction_id, evidence in sorted(result.evidence_results.items())
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    compressed = gzip.compress(encoded, mtime=0)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(compressed)
    temporary.replace(output)
    return output
