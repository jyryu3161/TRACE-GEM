"""Genome-scale model construction (CarveMe) subsystem.

CarveMe is invoked as an external ``carve`` subprocess — never imported — so
its ``reframed``/``python-libsbml`` dependencies stay isolated from the app's
``cobra``/``PySide6`` stack. The produced SBML is loaded back through the
existing :class:`~src.core.sbml_parser.SBMLParser` and flows into the standard
task-aware gap-fill pipeline.
"""

from src.build.build_engine import BuildEngine, BuiltModel
from src.build.build_manifest import BuildJob, ManifestError, parse_manifest, validate_kegg_code
from src.build.carveme_runner import (
    CarveMeAvailability,
    CarveMeNotInstalledError,
    CarveMeOptions,
    CarveMeResult,
    CarveMeRunError,
    CarveMeRunner,
)

__all__ = [
    "BuildEngine",
    "BuiltModel",
    "BuildJob",
    "ManifestError",
    "parse_manifest",
    "validate_kegg_code",
    "CarveMeAvailability",
    "CarveMeNotInstalledError",
    "CarveMeOptions",
    "CarveMeResult",
    "CarveMeRunError",
    "CarveMeRunner",
]
