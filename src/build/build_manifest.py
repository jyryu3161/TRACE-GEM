"""Batch build manifest parsing and validation.

A manifest is a CSV/TSV with a header row. Required columns: ``fasta`` and
``kegg_code``. Optional columns: ``universe``, ``universe_file``, ``gram``,
``medium``, ``label`` (``universe_file`` overrides ``universe``).

    fasta,kegg_code,universe,medium,label
    data/eco_protein.faa,eco,gramneg,M9,E. coli
    data/cgb_protein.faa,cgb,grampos,,C. glutamicum

The KEGG code is NOT consumed by CarveMe — it is carried through to the
downstream evaluator (organism filter + evidence) once the model is built.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from src.build.carveme_runner import VALID_UNIVERSES
from src.utils.constants import KEGG_CODE_TO_NAME

logger = logging.getLogger("metataskgapfill.build.manifest")


def _detect_delimiter(path: Path, suffix: str) -> str:
    """Pick CSV vs TSV delimiter: by extension, else sniff the header line.

    Handles tab-delimited .txt/.csv files (extension alone is unreliable).
    """
    if suffix in {".tsv", ".tab"}:
        return "\t"
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        first = lines[0] if lines else ""
    except Exception:  # noqa: BLE001
        first = ""
    if "\t" in first and "," not in first:
        return "\t"
    return ","

_GRAM_TO_UNIVERSE = {
    "+": "grampos",
    "pos": "grampos",
    "positive": "grampos",
    "grampos": "grampos",
    "gram+": "grampos",
    "-": "gramneg",
    "neg": "gramneg",
    "negative": "gramneg",
    "gramneg": "gramneg",
    "gram-": "gramneg",
}

_REQUIRED_COLUMNS = ("fasta", "kegg_code")
_OPTIONAL_COLUMNS = ("universe", "universe_file", "gram", "medium", "label")


class ManifestError(ValueError):
    """Raised when a batch manifest is malformed. Reports all row errors."""


@dataclass
class BuildJob:
    """One genome to build, plus the metadata the evaluator needs afterward."""

    fasta_path: Path
    kegg_code: str
    universe: str = ""        # explicit carve universe template (overrides gram)
    universe_file: str = ""   # custom carve --universe-file (overrides universe)
    gram: str = ""            # convenience alias -> grampos/gramneg
    medium: str = ""          # carve --init medium for this genome
    label: str = ""

    def __post_init__(self) -> None:
        self.fasta_path = Path(self.fasta_path)
        if not self.label:
            self.label = self.fasta_path.stem

    def resolve_universe(self) -> str:
        """Return the carve universe name, deriving it from gram if needed."""
        if self.universe:
            return self.universe
        if self.gram:
            return _GRAM_TO_UNIVERSE.get(self.gram.strip().lower(), "")
        return ""


def validate_kegg_code(code: str) -> tuple[bool, str | None]:
    """Soft-validate a KEGG organism code.

    Unknown codes are allowed (KEGG has thousands of organisms; only a handful
    are in the local name map). Returns ``(is_nonempty, resolved_name_or_None)``.
    """
    code = (code or "").strip()
    if not code:
        return False, None
    return True, KEGG_CODE_TO_NAME.get(code)


def _normalize_universe(value: str, row_num: int, errors: list[str]) -> str:
    value = (value or "").strip()
    if value and value not in VALID_UNIVERSES:
        # Soft warning rather than hard error: carve ships extra universes and
        # accepts custom names. Keep the value but note it.
        errors.append(
            f"row {row_num}: universe '{value}' is not a standard CarveMe "
            f"template {VALID_UNIVERSES[1:]}; passing through as-is"
        )
    return value


def parse_manifest(path: str | Path) -> list[BuildJob]:
    """Parse and validate a batch manifest. Raises ManifestError on any problem.

    All row-level problems are collected and reported together so the user can
    fix the whole file in one pass.
    """
    path = Path(path)
    if not path.exists():
        raise ManifestError(f"Manifest file not found: {path}")

    delimiter = _detect_delimiter(path, path.suffix.lower())
    errors: list[str] = []
    warnings: list[str] = []
    jobs: list[BuildJob] = []

    # utf-8-sig strips a UTF-8 BOM so the first header isn't read as "﻿fasta".
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ManifestError(f"Manifest {path} is empty")
        header = {(h or "").strip().lower() for h in reader.fieldnames}
        missing = [c for c in _REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ManifestError(
                f"Manifest {path} missing required column(s): {', '.join(missing)}. "
                f"Expected header with: {', '.join(_REQUIRED_COLUMNS)}"
                f"[, {', '.join(_OPTIONAL_COLUMNS)}]"
            )

        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            # Robust to ragged rows: csv.DictReader puts extra columns under the
            # None restkey as a list, and missing trailing columns yield None.
            norm: dict[str, str] = {}
            for k, v in row.items():
                if k is None:  # extra columns beyond the header
                    errors.append(f"row {row_num}: more columns than header")
                    continue
                if isinstance(v, list):
                    v = ",".join(str(x) for x in v)
                norm[(k or "").strip().lower()] = (str(v) if v is not None else "").strip()
            fasta = norm.get("fasta", "")
            kegg = norm.get("kegg_code", "")

            if not fasta:
                errors.append(f"row {row_num}: empty 'fasta'")
                continue
            fasta_path = Path(fasta)
            if not fasta_path.exists():
                errors.append(f"row {row_num}: fasta not found: {fasta}")
            ok, _name = validate_kegg_code(kegg)
            if not ok:
                errors.append(f"row {row_num}: empty 'kegg_code'")

            universe = _normalize_universe(norm.get("universe", ""), row_num, warnings)
            universe_file = norm.get("universe_file", "")
            if universe_file and not Path(universe_file).exists():
                errors.append(f"row {row_num}: universe_file not found: {universe_file}")
            jobs.append(
                BuildJob(
                    fasta_path=fasta_path,
                    kegg_code=kegg,
                    universe=universe,
                    universe_file=universe_file,
                    gram=norm.get("gram", ""),
                    medium=norm.get("medium", ""),
                    label=norm.get("label", ""),
                )
            )

    for warning in warnings:
        logger.warning("Manifest %s: %s", path.name, warning)

    if not jobs and not errors:
        raise ManifestError(f"Manifest {path} contains no data rows")
    if errors:
        raise ManifestError(
            "Manifest validation failed:\n  " + "\n  ".join(errors)
        )
    return jobs
