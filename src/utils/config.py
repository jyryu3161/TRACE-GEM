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

    # API keys for LLM verification
    gemini_api_key: str | None = None
    perplexity_api_key: str | None = None

    # Scoring weights (3 sources)
    weight_kegg: float = 0.50
    weight_gemini: float = 0.25
    weight_perplexity: float = 0.25

    # LLM feature flags
    enable_gemini: bool = True
    enable_perplexity: bool = True

    # UI settings
    recent_files: list[str] = field(default_factory=list)
    window_geometry: str | None = None

    @classmethod
    def load(cls) -> Config:
        if CONFIG_FILE_PATH.exists():
            try:
                data = json.loads(CONFIG_FILE_PATH.read_text())
                filtered = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                # Strip whitespace from API keys to prevent header injection errors
                for key in ("gemini_api_key", "perplexity_api_key"):
                    if key in filtered and isinstance(filtered[key], str):
                        filtered[key] = filtered[key].strip() or None
                return cls(**filtered)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE_PATH.write_text(json.dumps(asdict(self), indent=2, default=str))

    def add_recent_file(self, filepath: str) -> None:
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        self.recent_files.insert(0, filepath)
        self.recent_files = self.recent_files[:10]

    @property
    def weights(self) -> dict[str, float]:
        return {
            "kegg": self.weight_kegg,
            "gemini": self.weight_gemini,
            "perplexity": self.weight_perplexity,
        }
