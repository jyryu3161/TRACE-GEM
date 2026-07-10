"""Configuration management for the MetaTaskGapFill."""

from __future__ import annotations

import json
import math
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.utils.constants import (
    CONFIG_DIR,
    CONFIG_FILE_PATH,
    DEFAULT_TASK_FILE,
    DEFAULT_UNIVERSAL_MODEL,
)


class ConfigError(ValueError):
    """Raised when persisted or runtime configuration is invalid."""


@dataclass
class Config:
    # Organism settings
    kegg_organism_code: str = "eco"
    organism_name: str = "Escherichia coli"

    # Cache settings
    api_cache_ttl: int = 7 * 24 * 3600
    id_mapping_cache_ttl: int = 30 * 24 * 3600
    evidence_cache_ttl: int = 24 * 3600

    # Evaluation settings
    batch_size: int = 10
    max_concurrent: int = 5
    # Abort evidence-weighted runs when the evaluated batch exceeds this error
    # fraction. Zero is the reproducible/paper-safe default: no API failures are
    # silently converted into biological absence.
    candidate_evidence_max_error_fraction: float = 0.0

    # Gap-fill settings
    default_universal_model: str = DEFAULT_UNIVERSAL_MODEL
    default_task_file: str = DEFAULT_TASK_FILE
    gapfill_lower_bound: float = 0.05
    gapfill_iterations: int = 5
    gapfill_alternatives: int = 5
    gapfill_exclude_exchange_reactions: bool = True
    gapfill_universal_prune_threshold: int = 5000
    gapfill_prune_to_model_metabolites: bool = True
    organism_filter_cache_ttl: int = 30 * 24 * 3600
    # Ordinal evidence costs. These are optimization preferences, not
    # probabilities; every value is captured in the run manifest.
    gapfill_penalty_high: float = 1.0
    gapfill_penalty_moderate: float = 5.0
    gapfill_penalty_low: float = 25.0
    gapfill_penalty_not_assessable: float = 25.0
    gapfill_organism_penalty_multiplier: float = 10.0
    gapfill_organism_unknown_multiplier: float = 3.0
    gapfill_no_kegg_penalty_multiplier: float = 2.0
    gapfill_max_penalty: float = 1000.0

    # Model construction (CarveMe)
    # CarveMe is invoked as an external subprocess (the `carve` CLI), never
    # imported, to keep its reframed/python-libsbml deps isolated from cobra.
    carveme_executable: str = "carve"
    # Conda env that has `carve` installed. Empty = use carveme_executable on
    # PATH directly; otherwise the runner invokes `conda run -n <env> carve`.
    carveme_env: str = ""
    carveme_diamond_executable: str = "diamond"
    # MILP solver passed to carve: "gurobi" (default, fastest if licensed),
    # "cplex", or "scip" (free, slow). Empty uses carve's own default.
    carveme_solver: str = "gurobi"
    # CarveMe universe template: "", "gramneg", "grampos", "bacteria", "archaea".
    carveme_universe: str = ""
    # Custom CarveMe reaction universe model (SBML). When set, this overrides the
    # named carveme_universe template (carve --universe-file).
    carveme_universe_file: str = ""
    # CarveMe's own gap-fill media (carve -g), e.g. "M9,LB". Empty = none.
    carveme_gapfill_media: str = ""
    # CarveMe init medium (carve -i), e.g. "M9". Empty = none.
    carveme_init_medium: str = ""
    carveme_output_dir: str = "built_models"
    carveme_timeout: int = 1800  # seconds per model
    carveme_gzip_output: bool = False
    carveme_max_parallel: int = 1  # batch subprocess parallelism

    # Version control settings
    enable_versioning: bool = True
    max_versions: int = 20
    auto_save_on_edit: bool = True
    version_dir: str = ""  # default: ~/.metataskgapfill/versions/

    # UI settings
    recent_files: list[str] = field(default_factory=list)
    recent_projects: list[str] = field(default_factory=list)
    window_geometry: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate settings that can alter scientific or runtime behavior."""
        errors: list[str] = []

        if (
            not isinstance(self.kegg_organism_code, str)
            or not self.kegg_organism_code.strip()
            or any(char.isspace() for char in self.kegg_organism_code)
        ):
            errors.append("kegg_organism_code must be non-empty and contain no whitespace")

        positive_ints = {
            "batch_size": self.batch_size,
            "max_concurrent": self.max_concurrent,
            "gapfill_iterations": self.gapfill_iterations,
            "gapfill_alternatives": self.gapfill_alternatives,
            "carveme_timeout": self.carveme_timeout,
            "carveme_max_parallel": self.carveme_max_parallel,
            "max_versions": self.max_versions,
        }
        for name, value in positive_ints.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(f"{name} must be an integer >= 1")

        nonnegative_ints = {
            "api_cache_ttl": self.api_cache_ttl,
            "id_mapping_cache_ttl": self.id_mapping_cache_ttl,
            "evidence_cache_ttl": self.evidence_cache_ttl,
            "organism_filter_cache_ttl": self.organism_filter_cache_ttl,
            "gapfill_universal_prune_threshold": self.gapfill_universal_prune_threshold,
        }
        for name, value in nonnegative_ints.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{name} must be an integer >= 0")

        finite_positive = {
            "gapfill_lower_bound": self.gapfill_lower_bound,
            "gapfill_penalty_high": self.gapfill_penalty_high,
            "gapfill_penalty_moderate": self.gapfill_penalty_moderate,
            "gapfill_penalty_low": self.gapfill_penalty_low,
            "gapfill_penalty_not_assessable": self.gapfill_penalty_not_assessable,
            "gapfill_organism_penalty_multiplier": self.gapfill_organism_penalty_multiplier,
            "gapfill_organism_unknown_multiplier": self.gapfill_organism_unknown_multiplier,
            "gapfill_no_kegg_penalty_multiplier": self.gapfill_no_kegg_penalty_multiplier,
            "gapfill_max_penalty": self.gapfill_max_penalty,
        }
        for name, numeric_value in finite_positive.items():
            if (
                not isinstance(numeric_value, (int, float))
                or isinstance(numeric_value, bool)
                or not math.isfinite(numeric_value)
                or numeric_value <= 0
            ):
                errors.append(f"{name} must be a finite number > 0")

        error_fraction = self.candidate_evidence_max_error_fraction
        if (
            not isinstance(error_fraction, (int, float))
            or isinstance(error_fraction, bool)
            or not math.isfinite(error_fraction)
            or not 0.0 <= error_fraction <= 1.0
        ):
            errors.append("candidate_evidence_max_error_fraction must be between 0 and 1")
        penalty_values = (
            self.gapfill_penalty_high,
            self.gapfill_penalty_moderate,
            self.gapfill_penalty_low,
            self.gapfill_penalty_not_assessable,
            self.gapfill_max_penalty,
        )
        if all(isinstance(value, (int, float)) for value in penalty_values):
            if not (
                self.gapfill_penalty_high
                <= self.gapfill_penalty_moderate
                <= self.gapfill_penalty_low
            ):
                errors.append("gapfill tier penalties must be ordered high <= moderate <= low")
            if self.gapfill_penalty_not_assessable < self.gapfill_penalty_moderate:
                errors.append("gapfill_penalty_not_assessable must be >= moderate penalty")
            if self.gapfill_max_penalty < max(
                self.gapfill_penalty_low, self.gapfill_penalty_not_assessable
            ):
                errors.append("gapfill_max_penalty must be >= all base tier penalties")
        for name in (
            "gapfill_organism_penalty_multiplier",
            "gapfill_organism_unknown_multiplier",
            "gapfill_no_kegg_penalty_multiplier",
        ):
            value = getattr(self, name)
            if isinstance(value, (int, float)) and value < 1.0:
                errors.append(f"{name} must be >= 1.0")

        valid_solvers = {"", "gurobi", "cplex", "scip"}
        if self.carveme_solver not in valid_solvers:
            errors.append(f"carveme_solver must be one of {sorted(valid_solvers)!r}")
        valid_universes = {
            "",
            "archaea",
            "bacteria",
            "cyanobacteria",
            "gramneg",
            "grampos",
        }
        if self.carveme_universe not in valid_universes:
            errors.append(f"carveme_universe must be one of {sorted(valid_universes)!r}")

        if errors:
            raise ConfigError("Invalid configuration: " + "; ".join(errors))

    @classmethod
    def load(cls) -> Config:
        if CONFIG_FILE_PATH.exists():
            try:
                data = json.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ConfigError("configuration root must be a JSON object")
                filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                config = cls(**filtered)
            except (json.JSONDecodeError, TypeError, ConfigError) as exc:
                raise ConfigError(f"Cannot load {CONFIG_FILE_PATH}: {exc}") from exc
        else:
            config = cls()

        return config

    def save(self) -> None:
        self.validate()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{CONFIG_FILE_PATH.name}.",
            suffix=".tmp",
            dir=CONFIG_DIR,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(json.dumps(asdict(self), indent=2, default=str))
        temporary_path.chmod(0o600)
        temporary_path.replace(CONFIG_FILE_PATH)

    def add_recent_file(self, filepath: str) -> None:
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:10]

    def add_recent_project(self, filepath: str) -> None:
        if filepath in self.recent_projects:
            self.recent_projects.remove(filepath)
        self.recent_projects.insert(0, filepath)
        self.recent_projects = self.recent_projects[:10]

    @property
    def weights(self) -> dict[str, float]:
        """Legacy project-export view; KEGG is the sole fixed source."""
        return {"kegg": 1.0}
