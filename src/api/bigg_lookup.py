"""Local BiGG data lookup — replaces BiGG REST API with file-based parsing."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    Reaction,
)

logger = logging.getLogger("gem_evaluator.api.bigg_lookup")

# Default data directory
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _normalize_equation(eq: str) -> str:
    """Normalize a reaction equation for fuzzy comparison.

    Strips whitespace, lowercases, and unifies arrow styles.
    """
    s = eq.strip().lower()
    # Unify arrow variants to a canonical form
    s = re.sub(r"\s*<?[-=]+>?\s*", " <=> ", s)
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_name(name: str) -> str:
    """Normalize a reaction name for fuzzy comparison."""
    return re.sub(r"\s+", " ", name.strip().lower())


class BiGGReactionEntry:
    """Parsed row from bigg_models_reactions.txt."""

    __slots__ = (
        "bigg_id",
        "name",
        "reaction_string",
        "models",
        "database_links",
        "old_bigg_ids",
        "name_normalized",
        "equation_normalized",
    )

    def __init__(
        self,
        bigg_id: str,
        name: str,
        reaction_string: str,
        models: list[str],
        database_links: dict[str, list[str]],
        old_bigg_ids: list[str],
    ) -> None:
        self.bigg_id = bigg_id
        self.name = name
        self.reaction_string = reaction_string
        self.models = models
        self.database_links = database_links
        self.old_bigg_ids = old_bigg_ids
        self.name_normalized = _normalize_name(name)
        self.equation_normalized = _normalize_equation(reaction_string)


class BiGGMetaboliteEntry:
    """Parsed row from bigg_models_metabolites.txt."""

    __slots__ = (
        "bigg_id",
        "universal_bigg_id",
        "name",
        "models",
        "database_links",
    )

    def __init__(
        self,
        bigg_id: str,
        universal_bigg_id: str,
        name: str,
        models: list[str],
        database_links: dict[str, list[str]],
    ) -> None:
        self.bigg_id = bigg_id
        self.universal_bigg_id = universal_bigg_id
        self.name = name
        self.models = models
        self.database_links = database_links


class BiGGLookup:
    """Local BiGG data lookup using pre-downloaded flat files.

    Replaces ``BiGGClient`` (REST API) with instant in-memory search.

    Data files expected in *data_dir*:
      - ``bigg_models_reactions.txt``   (TSV, ~28k rows)
      - ``bigg_models_metabolites.txt`` (TSV, ~16k rows)
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR

        # Primary index: bigg_id → entry (exact match)
        self._reactions: dict[str, BiGGReactionEntry] = {}
        # Secondary index: old/alias IDs → bigg_id
        self._reaction_aliases: dict[str, str] = {}
        # Metabolite index
        self._metabolites: dict[str, BiGGMetaboliteEntry] = {}
        self._metabolite_aliases: dict[str, str] = {}

        self._loaded = False

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load and index both data files. Call once at startup."""
        if self._loaded:
            return
        self._load_reactions()
        self._load_metabolites()
        self._loaded = True
        logger.info(
            "BiGG local data loaded: %d reactions, %d metabolites",
            len(self._reactions),
            len(self._metabolites),
        )

    def _load_reactions(self) -> None:
        path = self._data_dir / "bigg_models_reactions.txt"
        if not path.exists():
            logger.warning("BiGG reactions file not found: %s", path)
            return

        with open(path, encoding="utf-8") as fh:
            header = fh.readline()  # skip header
            if not header.startswith("bigg_id"):
                logger.warning("Unexpected header in %s: %s", path, header[:80])

            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 6:
                    continue

                bigg_id = parts[0].strip()
                name = parts[1].strip()
                reaction_string = parts[2].strip()
                models = [m.strip() for m in parts[3].split(";") if m.strip()]
                db_links = self._parse_database_links(parts[4])
                old_ids = [o.strip() for o in parts[5].split(";") if o.strip()]

                entry = BiGGReactionEntry(
                    bigg_id=bigg_id,
                    name=name,
                    reaction_string=reaction_string,
                    models=models,
                    database_links=db_links,
                    old_bigg_ids=old_ids,
                )
                self._reactions[bigg_id] = entry

                # Index aliases (old IDs, case-insensitive)
                for alias in old_ids:
                    self._reaction_aliases[alias.lower()] = bigg_id
                # Also index the primary ID in lowercase
                self._reaction_aliases[bigg_id.lower()] = bigg_id

    def _load_metabolites(self) -> None:
        path = self._data_dir / "bigg_models_metabolites.txt"
        if not path.exists():
            logger.warning("BiGG metabolites file not found: %s", path)
            return

        with open(path, encoding="utf-8") as fh:
            header = fh.readline()
            if not header.startswith("bigg_id"):
                logger.warning("Unexpected header in %s: %s", path, header[:80])

            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 5:
                    continue

                bigg_id = parts[0].strip()
                universal_id = parts[1].strip()
                name = parts[2].strip()
                models = [m.strip() for m in parts[3].split(";") if m.strip()]
                db_links = self._parse_database_links(parts[4])

                entry = BiGGMetaboliteEntry(
                    bigg_id=bigg_id,
                    universal_bigg_id=universal_id,
                    name=name,
                    models=models,
                    database_links=db_links,
                )
                self._metabolites[bigg_id] = entry
                self._metabolite_aliases[bigg_id.lower()] = bigg_id
                if universal_id:
                    self._metabolite_aliases[universal_id.lower()] = bigg_id

    @staticmethod
    def _parse_database_links(raw: str) -> dict[str, list[str]]:
        """Parse 'DB: url; DB: url; ...' into {db_name: [urls]}."""
        links: dict[str, list[str]] = {}
        if not raw.strip():
            return links
        for entry in raw.split(";"):
            entry = entry.strip()
            if ": " not in entry:
                continue
            db_name, url = entry.split(": ", 1)
            db_name = db_name.strip()
            url = url.strip()
            links.setdefault(db_name, []).append(url)
        return links

    # ------------------------------------------------------------------
    # Exact ID lookup (기능 1)
    # ------------------------------------------------------------------

    def get_reaction(self, bigg_id: str) -> BiGGReactionEntry | None:
        """Exact lookup by BiGG reaction ID (or alias)."""
        self.load()
        entry = self._reactions.get(bigg_id)
        if entry:
            return entry
        # Try alias lookup (case-insensitive)
        canonical = self._reaction_aliases.get(bigg_id.lower())
        if canonical:
            return self._reactions.get(canonical)
        # Try with/without R_ prefix
        if bigg_id.startswith("R_"):
            return self.get_reaction(bigg_id[2:])
        return None

    def get_metabolite(self, bigg_id: str) -> BiGGMetaboliteEntry | None:
        """Exact lookup by BiGG metabolite ID."""
        self.load()
        entry = self._metabolites.get(bigg_id)
        if entry:
            return entry
        canonical = self._metabolite_aliases.get(bigg_id.lower())
        if canonical:
            return self._metabolites.get(canonical)
        return None

    # ------------------------------------------------------------------
    # Fuzzy matching (기능 2)
    # ------------------------------------------------------------------

    def search_by_name(
        self, query: str, max_results: int = 5
    ) -> list[BiGGReactionEntry]:
        """Search reactions by name (substring, case-insensitive)."""
        self.load()
        q = _normalize_name(query)
        if not q:
            return []

        exact: list[BiGGReactionEntry] = []
        partial: list[BiGGReactionEntry] = []

        for entry in self._reactions.values():
            if entry.name_normalized == q:
                exact.append(entry)
            elif q in entry.name_normalized:
                partial.append(entry)

        results = exact + partial
        return results[:max_results]

    def search_by_equation(
        self, equation: str, max_results: int = 5
    ) -> list[BiGGReactionEntry]:
        """Search reactions by equation string (normalized comparison)."""
        self.load()
        q = _normalize_equation(equation)
        if not q:
            return []

        exact: list[BiGGReactionEntry] = []
        partial: list[BiGGReactionEntry] = []

        for entry in self._reactions.values():
            if entry.equation_normalized == q:
                exact.append(entry)
            elif q in entry.equation_normalized or entry.equation_normalized in q:
                partial.append(entry)

        results = exact + partial
        return results[:max_results]

    # ------------------------------------------------------------------
    # Evidence interface (drop-in replacement for BiGGClient)
    # ------------------------------------------------------------------

    async def check_evidence(
        self, reaction: Reaction, bigg_id: str | None = None, **kwargs
    ) -> list[EvidenceItem]:
        """Check local BiGG data for evidence of reaction existence.

        Scoring logic matches the original BiGGClient:
        - >5 models  → STRONG
        - 2-5 models → MODERATE
        - 1 model    → WEAK
        - 0 models (exists in universal) → WEAK
        - not found  → ABSENT
        """
        rid = bigg_id or reaction.id
        entry = self.get_reaction(rid)

        if entry is None:
            # Try fuzzy match by name as fallback
            if reaction.name:
                matches = self.search_by_name(reaction.name, max_results=1)
                if matches:
                    entry = matches[0]
                    logger.debug(
                        "BiGG fuzzy match: '%s' → '%s' (by name '%s')",
                        rid,
                        entry.bigg_id,
                        reaction.name,
                    )

        if entry is None:
            return [
                EvidenceItem(
                    source=EvidenceSource.BIGG,
                    strength=EvidenceStrength.ABSENT,
                    description=f"Reaction '{rid}' not found in BiGG local data",
                )
            ]

        model_count = len(entry.models)

        if model_count > 5:
            strength = EvidenceStrength.STRONG
            desc = f"Found in {model_count} BiGG models (local)"
        elif model_count >= 2:
            strength = EvidenceStrength.MODERATE
            desc = f"Found in {model_count} BiGG models (local)"
        elif model_count == 1:
            strength = EvidenceStrength.WEAK
            desc = f"Found in 1 BiGG model: {entry.models[0]} (local)"
        else:
            strength = EvidenceStrength.WEAK
            desc = "Reaction exists in BiGG universal but not in any specific model (local)"

        model_names = entry.models[:10]
        url = f"http://bigg.ucsd.edu/universal/reactions/{entry.bigg_id}"

        return [
            EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=strength,
                description=desc,
                url=url,
                raw_data={
                    "model_count": model_count,
                    "models": model_names,
                    "database_links": entry.database_links,
                    "matched_bigg_id": entry.bigg_id,
                    "reaction_name": entry.name,
                    "reaction_string": entry.reaction_string,
                },
            )
        ]

    async def close(self) -> None:
        """No-op — local lookup needs no cleanup."""
        pass

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def reaction_count(self) -> int:
        self.load()
        return len(self._reactions)

    @property
    def metabolite_count(self) -> int:
        self.load()
        return len(self._metabolites)

    def get_database_links(self, bigg_id: str) -> dict[str, list[str]]:
        """Get cross-reference database links for a reaction."""
        entry = self.get_reaction(bigg_id)
        return entry.database_links if entry else {}
