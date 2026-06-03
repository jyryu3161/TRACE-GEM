"""Configuration management for the GEM Evaluator."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from src.utils.constants import CONFIG_DIR, CONFIG_FILE_PATH


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
    # 0 means evaluate evidence for all candidates before gap-filling.
    candidate_evidence_eager_limit: int = 0

    # Scoring weights
    weight_kegg: float = 0.70
    weight_bigg: float = 0.30

    # Source enable flags
    enable_bigg: bool = True

    # Gap-fill settings
    default_universal_model: str = "data/bigg_universal_model_fixed.json"
    default_task_file: str = "data/universal_essential_tasks.csv"
    gapfill_lower_bound: float = 0.05
    gapfill_iterations: int = 5
    gapfill_universal_prune_threshold: int = 5000
    gapfill_prune_to_model_metabolites: bool = True
    organism_filter_cache_ttl: int = 30 * 24 * 3600
    gapfill_penalty_epsilon: float = 0.01
    gapfill_organism_penalty_multiplier: float = 10.0
    gapfill_no_kegg_penalty_multiplier: float = 2.0

    # Version control settings
    enable_versioning: bool = True
    max_versions: int = 20
    auto_save_on_edit: bool = True
    version_dir: str = ""  # default: ~/.gem_evaluator/versions/

    # UI settings
    recent_files: list[str] = field(default_factory=list)
    recent_projects: list[str] = field(default_factory=list)
    window_geometry: str | None = None

    @classmethod
    def load(cls) -> Config:
        if CONFIG_FILE_PATH.exists():
            try:
                data = json.loads(CONFIG_FILE_PATH.read_text())
                filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                config = cls(**filtered)
            except (json.JSONDecodeError, TypeError):
                config = cls()
        else:
            config = cls()

        return config

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE_PATH.write_text(json.dumps(asdict(self), indent=2, default=str))
        CONFIG_FILE_PATH.chmod(0o600)

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
        return {
            "kegg": self.weight_kegg,
            "bigg": self.weight_bigg,
        }
