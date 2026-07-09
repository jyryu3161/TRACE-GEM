"""CLI for MetaTaskGapFill batch evaluation and task-aware gap-filling."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from src.core.models import (
    GapFillResult,
    MetabolicTask,
    ModelData,
    ReactionEvidence,
)
from src.gapfill.refine import apply_base_medium_to_tasks
from src.utils.config import Config
from src.utils.constants import KEGG_CODE_TO_NAME


def _eprint(*args: object, **kwargs: Any) -> None:
    """Print to stderr."""
    print(*args, file=sys.stderr, **kwargs)


def _format_time(seconds: float) -> str:
    """Format seconds into human-readable string."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metatask-gapfill-cli",
        description=(
            "Task-aware gap-filling of genome-scale models, with universal "
            "candidate reactions weighted by KEGG evidence."
        ),
    )
    parser.add_argument(
        "model",
        nargs="?",
        default=None,
        help="Path to SBML model file (.xml). Requires --gap-fill. "
        "Omit when using --build/--batch-build.",
    )
    parser.add_argument(
        "--organism",
        help="KEGG organism code override (e.g. eco, sce, hsa)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Candidate-evaluation batch size override",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        help="Max concurrent requests override",
    )

    # Gap-filling options
    gf_group = parser.add_argument_group("Gap-filling options")
    gf_group.add_argument(
        "--gap-fill",
        action="store_true",
        help="Enable gap-filling mode",
    )
    gf_group.add_argument(
        "--universal",
        metavar="PATH",
        default=None,
        help="Path to universal model file (JSON/SBML). Default: BiGG universal",
    )
    gf_group.add_argument(
        "--tasks",
        metavar="PATH",
        default=None,
        help="Path to metabolic tasks CSV file. Default: universal essential tasks",
    )
    gf_group.add_argument(
        "--medium",
        metavar="PATH_OR_SPEC",
        default=None,
        help=(
            "Explicit base medium merged into every metabolic task. Accepts JSON, "
            "CSV, or inline spec like 'glc__D_e(-10);o2_e(-1000)'. If omitted, each "
            "task uses its own self-contained medium and NO base medium is merged "
            "(the model's default medium is NOT applied; merging it would break "
            "negative-constraint tasks)."
        ),
    )
    gf_group.add_argument(
        "--output-model",
        metavar="PATH",
        default=None,
        help="Path to save improved SBML model after gap-filling",
    )
    gf_group.add_argument(
        "--output-report",
        metavar="PATH",
        default=None,
        help="Path to save gap-filling report CSV",
    )
    gf_group.add_argument(
        "--skip-evaluation",
        action="store_true",
        help="Skip KEGG evidence evaluation of gap-fill candidates "
        "(use default penalties)",
    )
    gf_group.add_argument(
        "--include-exchange-gapfill",
        action="store_true",
        help=(
            "Allow exchange/demand/sink reactions from the universal model as "
            "gap-fill candidates. Default: excluded."
        ),
    )

    # Model construction (CarveMe) options
    build_group = parser.add_argument_group("Model construction (CarveMe)")
    build_group.add_argument(
        "--build",
        metavar="FASTA",
        default=None,
        help="Build one model from a protein FASTA using CarveMe",
    )
    build_group.add_argument(
        "--batch-build",
        metavar="MANIFEST",
        default=None,
        help=(
            "Build multiple models from a manifest CSV/TSV "
            "(columns: fasta,kegg_code[,universe,universe_file,gram,medium,label])"
        ),
    )
    build_group.add_argument(
        "--build-output",
        metavar="PATH",
        default=None,
        help="Output SBML path (single build) or output directory (batch). "
        "Default: <stem>.xml / built_models/",
    )
    build_group.add_argument(
        "--carveme-solver",
        choices=("gurobi", "cplex", "scip"),
        default=None,
        help="MILP solver for CarveMe (config default: gurobi)",
    )
    build_group.add_argument(
        "--carveme-universe",
        choices=("bacteria", "grampos", "gramneg", "archaea", "cyanobacteria"),
        default=None,
        help="CarveMe universe template (default: carve's own default)",
    )
    build_group.add_argument(
        "--carveme-universe-file",
        metavar="PATH",
        default=None,
        help="Custom CarveMe reaction universe model (SBML); overrides "
        "--carveme-universe",
    )
    build_group.add_argument(
        "--carveme-gapfill-media",
        metavar="MEDIA",
        default=None,
        help="CarveMe's own gap-fill media (carve -g), e.g. 'M9,LB'",
    )
    build_group.add_argument(
        "--carveme-init-medium",
        metavar="MEDIUM",
        default=None,
        help="CarveMe init medium (carve -i), e.g. 'M9'",
    )
    build_group.add_argument(
        "--carveme-env",
        metavar="NAME",
        default=None,
        help="Conda env containing `carve` (invoked via conda run)",
    )
    build_group.add_argument(
        "--carveme-executable",
        metavar="PATH",
        default=None,
        help="Path to the carve executable (default: 'carve' on PATH)",
    )
    build_group.add_argument(
        "--carveme-timeout",
        type=int,
        default=None,
        help="Per-model build timeout in seconds (default: 1800)",
    )
    build_group.add_argument(
        "--carveme-max-parallel",
        type=int,
        default=None,
        help="Batch build subprocess parallelism (default: 1)",
    )
    build_group.add_argument(
        "--gzip-model",
        action="store_true",
        help="Write compressed .xml.gz model output",
    )
    build_group.add_argument(
        "--build-dna",
        action="store_true",
        help="Treat the build input as a DNA fasta (carve --dna)",
    )
    build_group.add_argument(
        "--refine",
        action="store_true",
        help="After building, run task-aware gap-fill on the built model "
        "(single model at a time)",
    )
    build_group.add_argument(
        "--check-carveme",
        action="store_true",
        help="Check the CarveMe toolchain (carve/diamond/solver) and exit",
    )

    # Pipeline (YAML config) options
    pipe_group = parser.add_argument_group("Pipeline (YAML config)")
    pipe_group.add_argument(
        "--config",
        metavar="FILE.yaml",
        default=None,
        help="Run a full build → refine (gap-fill) pipeline from a YAML config "
        "(jobs carry KEGG taxonomy codes). Mutually exclusive with other modes.",
    )
    pipe_group.add_argument(
        "--config-validate",
        action="store_true",
        help="Validate the --config YAML and exit without running",
    )

    return parser


def _normalize_medium_reaction_id(raw_id: str) -> str:
    """Return an exchange reaction ID from a metabolite or exchange ID."""
    medium_id = raw_id.strip()
    if medium_id.startswith("EX_"):
        return medium_id
    return f"EX_{medium_id}"


def _medium_value_to_lower_bound(value: float) -> float:
    """Convert medium values to exchange lower bounds.

    Positive values are treated as COBRA-style uptake capacities and converted
    to negative lower bounds. Negative values are treated as explicit lower
    bounds. Zero closes uptake.
    """
    if value > 0:
        return -value
    return value


def _parse_medium_spec(spec: str) -> dict[str, float]:
    """Parse inline medium spec: ``glc__D_e(-10);EX_o2_e(-1000)``.

    Values use the same sign convention as JSON/CSV media: a positive number is
    an uptake capacity converted to a negative lower bound, a negative number is
    an explicit lower bound. Without this, ``glc__D_e(10)`` would force glucose
    *efflux* while the equivalent JSON ``{"glc__D_e": 10}`` allows uptake.
    """
    import re

    medium: dict[str, float] = {}
    for entry in spec.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        match = re.match(r"^(.+?)\(([^)]+)\)$", entry)
        if not match:
            raise ValueError(f"Invalid medium entry: {entry}")
        rxn_id = _normalize_medium_reaction_id(match.group(1))
        medium[rxn_id] = _medium_value_to_lower_bound(float(match.group(2)))
    return medium


def _load_medium_json(path: Path) -> dict[str, float]:
    """Load medium from JSON mapping or list records."""
    data = json.loads(path.read_text())
    medium: dict[str, float] = {}

    if isinstance(data, dict):
        for raw_id, value in data.items():
            medium[_normalize_medium_reaction_id(str(raw_id))] = _medium_value_to_lower_bound(
                float(value)
            )
        return medium

    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                raise ValueError("JSON medium list entries must be objects")
            raw_id = row.get("reaction_id") or row.get("exchange") or row.get("id")
            if raw_id is None:
                raise ValueError("JSON medium rows need reaction_id, exchange, or id")
            if "lower_bound" in row:
                value = float(row["lower_bound"])
            elif "uptake" in row:
                value = _medium_value_to_lower_bound(float(row["uptake"]))
            elif "bound" in row:
                value = _medium_value_to_lower_bound(float(row["bound"]))
            else:
                raise ValueError("JSON medium rows need lower_bound, uptake, or bound")
            medium[_normalize_medium_reaction_id(str(raw_id))] = value
        return medium

    raise ValueError("JSON medium must be an object or list of objects")


def _load_medium_csv(path: Path) -> dict[str, float]:
    """Load medium from CSV with exchange/reaction_id/id and bound columns."""
    medium: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
        for row in reader:
            raw_id = row.get("reaction_id") or row.get("exchange") or row.get("id")
            if raw_id is None:
                raise ValueError("CSV medium needs reaction_id, exchange, or id column")
            if row.get("lower_bound") not in (None, ""):
                value = float(row["lower_bound"])
            elif row.get("uptake") not in (None, ""):
                value = _medium_value_to_lower_bound(float(row["uptake"]))
            elif row.get("bound") not in (None, ""):
                value = _medium_value_to_lower_bound(float(row["bound"]))
            else:
                raise ValueError("CSV medium needs lower_bound, uptake, or bound column")
            medium[_normalize_medium_reaction_id(raw_id)] = value
    return medium


def load_medium_argument(value: str | None, cobra_model: Any | None) -> dict[str, float]:
    """Parse an explicit medium spec/file into {EX_id: lower_bound}.

    Only called with a truthy ``value`` on the gap-fill path (tasks are otherwise
    self-contained and no base medium is merged). The ``value is None`` branch
    that falls back to ``cobra_model.medium`` is retained for callers that
    explicitly want the model's default medium.
    """
    if value:
        path = Path(value)
        if path.exists():
            if path.suffix.lower() == ".json":
                return _load_medium_json(path)
            if path.suffix.lower() in {".csv", ".tsv"}:
                return _load_medium_csv(path)
            raise ValueError(f"Unsupported medium file extension: {path.suffix}")
        # Not an existing file. If the value clearly names a medium file (a known
        # extension or a path separator) rather than an inline spec, report the
        # missing file instead of misparsing it as inline syntax and raising a
        # confusing "Invalid medium entry" error.
        if path.suffix.lower() in {".json", ".csv", ".tsv"} or "/" in value or "\\" in value:
            raise FileNotFoundError(f"Medium file not found: {value}")
        return _parse_medium_spec(value)

    if cobra_model is None:
        return {}

    try:
        cobra_medium = cobra_model.medium
    except Exception:
        cobra_medium = {}

    medium = {
        _normalize_medium_reaction_id(str(rxn_id)): _medium_value_to_lower_bound(float(value))
        for rxn_id, value in cobra_medium.items()
    }
    if medium:
        return medium

    try:
        exchanges = list(cobra_model.exchanges)
    except Exception:
        exchanges = []
    return {
        rxn.id: rxn.lower_bound
        for rxn in exchanges
        if getattr(rxn, "lower_bound", 0.0) < 0
    }


async def async_gapfill_main(
    config: Config,
    model_data: ModelData,
    universal_path: str,
    tasks_path: str,
    medium_arg: str | None,
    output_model: str | None,
    output_report: str | None,
    skip_evaluation: bool,
    include_exchange_gapfill: bool = False,
) -> None:
    """Run the async gap-filling pipeline."""
    from src.core.task_parser import TaskParser
    from src.core.universal_loader import UniversalLoader
    from src.evidence.engine import EvidenceEngine
    from src.gapfill.engine import GapFillEngine

    start_time = time.monotonic()

    # Step 1: Load universal model
    _eprint("Loading universal model...")
    loader = UniversalLoader()
    universal_model = loader.load(universal_path)
    config.gapfill_exclude_exchange_reactions = not include_exchange_gapfill
    _eprint(
        f"  Universal model: {len(universal_model.reactions)} reactions, "
        f"{len(universal_model.metabolites)} metabolites"
    )
    if config.gapfill_exclude_exchange_reactions:
        _eprint("  Gap-fill candidates: exchange/demand/sink reactions excluded")
    else:
        _eprint("  Gap-fill candidates: exchange/demand/sink reactions included")

    # Step 2: Extract candidates
    _eprint("Extracting candidate reactions...")
    candidates = loader.extract_candidates(
        universal_model,
        model_data,
        exclude_exchange_reactions=config.gapfill_exclude_exchange_reactions,
    )
    _eprint(f"  {len(candidates)} candidate reactions extracted")

    # Step 3: Parse metabolic tasks
    _eprint(f"Loading metabolic tasks from {Path(tasks_path).name}...")
    task_parser = TaskParser()
    tasks = task_parser.parse(tasks_path)
    # Tasks are self-contained (each declares its full medium). Only merge an
    # EXPLICIT --medium; auto-merging the model's default medium would add
    # nutrients (e.g. glucose) back into negative-constraint tasks that omit them
    # on purpose ("no X without carbon source"), breaking those tests and making
    # CLI disagree with the GUI.
    if medium_arg:
        base_medium = load_medium_argument(medium_arg, model_data.cobra_model)
        tasks = apply_base_medium_to_tasks(tasks, base_medium)
        _eprint(f"  {len(tasks)} tasks loaded")
        _eprint(f"  Base medium: {len(base_medium)} exchanges from {medium_arg}")
    else:
        _eprint(f"  {len(tasks)} tasks loaded (task-specific media; no base medium merged)")

    # Step 4: Evidence evaluation (optional)
    evidence_results: dict[str, ReactionEvidence] = {}

    evidence_engine = EvidenceEngine(config)
    try:
        await evidence_engine.initialize()

        # KEGG evidence is computed only for gap-fill candidates (to weight
        # which universal reactions to add). Model quality is judged by tasks.
        if skip_evaluation:
            _eprint("Skipping candidate evidence evaluation (--skip-evaluation)")
        else:
            # Honor candidate_evidence_eager_limit so the CLI matches the GUI:
            # defer candidate evidence for large universals, leaving default
            # penalties for those candidates.
            eager_limit = max(0, config.candidate_evidence_eager_limit)
            if eager_limit and len(candidates) > eager_limit:
                _eprint(
                    f"Deferring candidate evidence: {len(candidates)} candidates "
                    f"exceeds eager limit ({eager_limit}); using default penalties"
                )
            else:
                _eprint(f"Evaluating {len(candidates)} candidate reactions...")
                cand_start = time.monotonic()

                def cand_progress(completed: int, total: int, reaction_id: str) -> None:
                    pct = completed / total * 100 if total else 0
                    filled = int(pct / 5)
                    bar = "=" * filled + ">" + " " * (20 - filled - 1)
                    elapsed = time.monotonic() - cand_start
                    _eprint(
                        f"\r  Candidate eval: [{bar}] {completed}/{total} ({pct:.1f}%) "
                        f"-- {reaction_id} [{_format_time(elapsed)}]",
                        end="",
                    )

                evidence_results = await evidence_engine.evaluate_candidates_batch(
                    candidates, progress_callback=cand_progress
                )
                _eprint(
                    f"\n  Candidate evaluation complete: {len(evidence_results)} reactions scored"
                )

        # Step 5: Run gap-fill pipeline
        _eprint("Starting gap-fill pipeline...")
        assert model_data.cobra_model is not None, "COBRA model not available"

        gapfill_engine = GapFillEngine(config)
        cache_mgr = evidence_engine.cache_manager
        mapping_data = evidence_engine.mapping_data

        try:
            await gapfill_engine.initialize(
                organism_code=config.kegg_organism_code,
                cache_manager=cache_mgr,
                mapping_data=mapping_data,
            )

            def gf_progress(phase: str, current: int, total: int, detail: str) -> None:
                _eprint(f"\r  [{phase}] {current}/{total} -- {detail}    ", end="")

            gf_result = await gapfill_engine.run(
                user_model=model_data.cobra_model,
                universal_model=universal_model,
                candidates=candidates,
                tasks=tasks,
                evidence_results=evidence_results,
                progress_callback=gf_progress,
            )
            _eprint("")  # newline after progress

        finally:
            await gapfill_engine.close()

    finally:
        await evidence_engine.close()

    elapsed = time.monotonic() - start_time

    # Step 6: Print task results summary
    _eprint(f"\nGap-fill complete in {_format_time(elapsed)}")
    _eprint(f"  Reactions added: {len(gf_result.added_reactions)}")
    _eprint(f"  Tasks fixed: {gf_result.tasks_fixed}/{gf_result.total_tasks}")

    if gf_result.infeasible_tasks:
        _eprint(f"  Infeasible tasks: {', '.join(gf_result.infeasible_tasks)}")

    # Before/After task results table
    before_map = {r.task.task_id: r for r in gf_result.task_results_before}
    after_map = {r.task.task_id: r for r in gf_result.task_results_after}

    _eprint("")
    _eprint(f"{'Task ID':<8} {'Description':<45} {'Before':>7} {'After':>7} {'Status':>8}")
    _eprint("-" * 80)

    for task in tasks:
        before = before_map.get(task.task_id)
        after = after_map.get(task.task_id)
        b_str = "PASS" if (before and before.passed) else "FAIL"
        a_str = "PASS" if (after and after.passed) else "FAIL"

        if b_str == "FAIL" and a_str == "PASS":
            status = "FIXED"
        elif b_str == "PASS" and a_str == "FAIL":
            status = "REGRESS"
        elif b_str == "FAIL" and a_str == "FAIL":
            status = "FAILING"
        else:
            status = "OK"

        desc = task.description[:44] if len(task.description) > 44 else task.description
        _eprint(f"{task.task_id:<8} {desc:<45} {b_str:>7} {a_str:>7} {status:>8}")

    before_pass = sum(1 for r in gf_result.task_results_before if r.passed)
    after_pass = sum(1 for r in gf_result.task_results_after if r.passed)
    _eprint("-" * 80)
    _eprint(
        f"{'TOTAL':<8} {'':45} {before_pass:>4}/{len(tasks):<2} {after_pass:>4}/{len(tasks):<2}"
    )

    # Step 7: Save improved model
    if output_model and model_data.cobra_model:
        import cobra as cobra_io

        cobra_io.io.write_sbml_model(model_data.cobra_model, output_model)
        _eprint(f"\nImproved model saved to {output_model}")

    # Step 8: Save report CSV
    if output_report:
        _save_gapfill_report(output_report, gf_result, tasks)
        _eprint(f"Gap-fill report saved to {output_report}")


def _save_gapfill_report(
    filepath: str,
    result: GapFillResult,
    tasks: list[MetabolicTask],
) -> None:
    """Save gap-filling results to a CSV report."""
    before_map = {r.task.task_id: r for r in result.task_results_before}
    after_map = {r.task.task_id: r for r in result.task_results_after}

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)

        # Section 1: Summary
        writer.writerow(["Gap-Fill Summary"])
        writer.writerow(["Reactions Added", len(result.added_reactions)])
        writer.writerow(["Tasks Fixed", result.tasks_fixed])
        writer.writerow(["Tasks Broken", result.tasks_broken])
        writer.writerow(["Total Tasks", result.total_tasks])
        writer.writerow(["Iterations", result.iterations])
        writer.writerow(["Infeasible Tasks", ";".join(result.infeasible_tasks)])
        writer.writerow([])

        # Section 2: Added reactions (with KEGG evidence provenance)
        writer.writerow(["Added Reactions"])
        writer.writerow([
            "Reaction ID", "Name", "Subsystem", "Penalty", "GPR",
            "Evidence Tier", "Weight (penalty)",
        ])
        for candidate in result.added_reactions:
            rxn = candidate.reaction
            tier_label = (
                candidate.evidence_tier.label if candidate.evidence_tier else "—"
            )
            writer.writerow([
                rxn.id,
                rxn.name,
                rxn.subsystem or "",
                f"{candidate.penalty:.4f}",
                candidate.assigned_gpr,
                tier_label,
                f"{candidate.penalty:.2f}",
            ])
        writer.writerow([])

        # Section 2b: Tasks that could not be gap-filled because no KEGG-mapped
        # universal reaction was available (strict KEGG-only gap-fill).
        if result.unfillable_no_kegg:
            writer.writerow(["Unfillable (no KEGG-mapped reaction)"])
            writer.writerow(["Task ID"])
            for task_id in result.unfillable_no_kegg:
                writer.writerow([task_id])
            writer.writerow([])

        # Section 3: Task results
        writer.writerow(["Task Results"])
        writer.writerow([
            "Task ID", "Type", "Target", "Category", "Description",
            "Before Pass", "Before Value", "After Pass", "After Value", "Status",
        ])
        for task in tasks:
            before = before_map.get(task.task_id)
            after = after_map.get(task.task_id)
            b_pass = before.passed if before else False
            b_val = before.actual_value if before else 0.0
            a_pass = after.passed if after else False
            a_val = after.actual_value if after else 0.0

            if not b_pass and a_pass:
                status = "FIXED"
            elif b_pass and not a_pass:
                status = "REGRESSION"
            elif not b_pass and not a_pass:
                status = "FAILING"
            else:
                status = "OK"

            writer.writerow([
                task.task_id,
                task.task_type,
                task.target_id,
                task.category,
                task.description,
                str(b_pass),
                f"{b_val:.6f}",
                str(a_pass),
                f"{a_val:.6f}",
                status,
            ])


def _apply_carveme_overrides(config: Config, args: argparse.Namespace) -> set[str]:
    """Apply CarveMe CLI flag overrides onto the config (per-invocation).

    Returns the set of config field names the CLI explicitly set, so a YAML
    ``--config`` run can keep CLI flags taking precedence over file defaults
    (CLI > YAML > built-in defaults).
    """
    overridden: set[str] = set()
    if getattr(args, "carveme_solver", None):
        config.carveme_solver = args.carveme_solver
        overridden.add("carveme_solver")
    if getattr(args, "carveme_universe", None):
        config.carveme_universe = args.carveme_universe
        overridden.add("carveme_universe")
    if getattr(args, "carveme_universe_file", None):
        config.carveme_universe_file = args.carveme_universe_file
        overridden.add("carveme_universe_file")
    if getattr(args, "carveme_env", None) is not None:
        config.carveme_env = args.carveme_env
        overridden.add("carveme_env")
    if getattr(args, "carveme_executable", None):
        config.carveme_executable = args.carveme_executable
        overridden.add("carveme_executable")
    if getattr(args, "carveme_timeout", None) is not None:
        config.carveme_timeout = args.carveme_timeout
        overridden.add("carveme_timeout")
    if getattr(args, "carveme_max_parallel", None) is not None:
        config.carveme_max_parallel = args.carveme_max_parallel
        overridden.add("carveme_max_parallel")
    if getattr(args, "gzip_model", False):
        config.carveme_gzip_output = True
        overridden.add("carveme_gzip_output")
    if getattr(args, "carveme_gapfill_media", None) is not None:
        config.carveme_gapfill_media = args.carveme_gapfill_media
        overridden.add("carveme_gapfill_media")
    if getattr(args, "carveme_init_medium", None) is not None:
        config.carveme_init_medium = args.carveme_init_medium
        overridden.add("carveme_init_medium")
    return overridden


def _run_check_carveme(config: Config) -> None:
    """Print CarveMe toolchain availability and exit non-zero if unusable."""
    from src.build.carveme_runner import CarveMeRunner

    runner = CarveMeRunner(
        executable=config.carveme_executable,
        conda_env=config.carveme_env,
        diamond_executable=config.carveme_diamond_executable,
    )
    avail = runner.check_available(solver=config.carveme_solver)
    _eprint(avail.message)
    if not avail.ok:
        sys.exit(1)


def _run_build(args: argparse.Namespace, config: Config) -> None:
    """Dispatch a single or batch CarveMe build (with optional refinement)."""
    from src.build.build_engine import BuildEngine
    from src.build.build_manifest import parse_manifest, validate_kegg_code
    from src.build.carveme_runner import CarveMeRunError

    engine = BuildEngine(config)
    avail = engine.runner.check_available(solver=config.carveme_solver)
    if not avail.ok:
        _eprint("CarveMe toolchain not ready:\n" + avail.message)
        sys.exit(1)
    _eprint(avail.message)

    if config.carveme_universe_file and not Path(config.carveme_universe_file).exists():
        _eprint(f"Error: universe file not found: {config.carveme_universe_file}")
        sys.exit(1)

    options = engine.options_from_config(dna=getattr(args, "build_dna", False))

    def on_line(line: str) -> None:
        _eprint("  " + line)

    # --- Batch build ---
    if args.batch_build:
        try:
            jobs = parse_manifest(args.batch_build)
        except Exception as exc:  # noqa: BLE001 - surface manifest errors cleanly
            _eprint(f"Error: {exc}")
            sys.exit(1)

        out_dir = args.build_output or config.carveme_output_dir
        _eprint(f"Batch build: {len(jobs)} model(s) -> {out_dir}")

        def on_model_built(index: int, item: object) -> None:
            if item.ok:  # type: ignore[attr-defined]
                md = item.built.model_data  # type: ignore[attr-defined]
                _eprint(
                    f"[OK] {item.job.label}: {md.id} "  # type: ignore[attr-defined]
                    f"({md.reaction_count} rxn, {md.metabolite_count} met, "
                    f"{md.gene_count} gene) -> {item.built.sbml_path}"  # type: ignore[attr-defined]
                )
            else:
                _eprint(f"[FAIL] {item.job.label}: {item.error}")  # type: ignore[attr-defined]

        results = engine.build_batch(
            jobs,
            options=options,
            output_dir=out_dir,
            on_line=on_line,
            on_model_built=on_model_built,
        )
        ok = sum(1 for r in results if r.ok)
        _eprint(f"\nBatch complete: {ok}/{len(results)} model(s) built")
        if args.refine:
            _eprint(
                "Note: --refine is single-model only. Refine each built model "
                "separately (--build <model.xml is not it>; use --build <fasta> "
                "--refine per genome) or in the GUI."
            )
        if ok == 0:
            sys.exit(1)
        return

    # --- Single build ---
    fasta = args.build
    kegg = args.organism
    if kegg:
        _ok, name = validate_kegg_code(kegg)
        _eprint(f"Organism: {name or kegg} ({kegg})")
    else:
        _eprint(
            "Warning: no --organism (KEGG code) given; organism-based filtering "
            "and evidence will be generic."
        )

    _eprint(
        f"Building model from {fasta} "
        f"(solver={config.carveme_solver}, "
        f"universe={config.carveme_universe_file or config.carveme_universe or 'default'})..."
    )
    try:
        built = engine.build_one(
            fasta, kegg, options=options, output_path=args.build_output, on_line=on_line
        )
    except CarveMeRunError as exc:
        _eprint(f"Build failed: {exc}")
        sys.exit(1)

    md = built.model_data
    _eprint(
        f"Built model: {md.id} ({md.reaction_count} reactions, "
        f"{md.metabolite_count} metabolites, {md.gene_count} genes)"
    )
    _eprint(f"Saved to {built.sbml_path}")

    # --- Optional refinement (reuses the full gap-fill CLI path) ---
    if args.refine:
        from src.utils.constants import DEFAULT_TASK_FILE, DEFAULT_UNIVERSAL_MODEL

        universal_path = (
            args.universal or config.default_universal_model or DEFAULT_UNIVERSAL_MODEL
        )
        tasks_path = args.tasks or config.default_task_file or DEFAULT_TASK_FILE
        if not Path(universal_path).exists():
            _eprint(f"Error: Universal model not found: {universal_path}")
            sys.exit(1)
        if not Path(tasks_path).exists():
            _eprint(f"Error: Task file not found: {tasks_path}")
            sys.exit(1)

        if kegg:
            config.kegg_organism_code = kegg
            config.organism_name = KEGG_CODE_TO_NAME.get(kegg, kegg)

        _eprint(f"\nRefining built model with tasks ({Path(tasks_path).name})...")
        asyncio.run(
            async_gapfill_main(
                config=config,
                model_data=built.model_data,
                universal_path=universal_path,
                tasks_path=tasks_path,
                medium_arg=args.medium,
                output_model=args.output_model,
                output_report=args.output_report,
                skip_evaluation=args.skip_evaluation,
                include_exchange_gapfill=args.include_exchange_gapfill,
            )
        )


def _run_pipeline_config(
    args: argparse.Namespace,
    config: Config,
    cli_overrides: set[str] | None = None,
) -> None:
    """Load and run (or validate) a YAML pipeline config."""
    from src.pipeline import PipelineError, load_pipeline, run_pipeline

    try:
        spec = load_pipeline(args.config)
        if args.config_validate:
            _eprint(f"Config OK: {args.config}")
            return
        result = asyncio.run(
            run_pipeline(spec, config, log=_eprint, cli_overridden=cli_overrides)
        )
    except PipelineError as exc:
        _eprint(f"Error: {exc}")
        sys.exit(1)

    if result.models_failed > 0 or result.models_built == 0:
        _eprint(
            f"Pipeline finished with failures: {result.models_built} built, "
            f"{result.models_failed} failed"
        )
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Load config and apply overrides
    from src.utils.logging_config import setup_logging

    setup_logging()
    config = Config.load()
    cli_overrides = _apply_carveme_overrides(config, args)

    # YAML pipeline mode takes a config file instead of a model / FASTA.
    if args.config_validate and not args.config:
        parser.error("--config-validate requires --config")
    if args.config:
        if args.model is not None or args.build or args.batch_build:
            parser.error("--config cannot be combined with a model / --build / --batch-build")
        _run_pipeline_config(args, config, cli_overrides)
        return

    # Model construction (CarveMe) modes are dispatched first: they take a
    # FASTA/manifest rather than an SBML model, so the positional 'model' is
    # optional and must not be combined with them.
    if args.check_carveme:
        _run_check_carveme(config)
        return
    if args.build or args.batch_build:
        if args.model is not None:
            parser.error("positional 'model' cannot be combined with --build/--batch-build")
        if args.build and args.batch_build:
            parser.error("--build and --batch-build are mutually exclusive")
        _run_build(args, config)
        return

    # Evidence-evaluation and gap-fill modes require an SBML model file.
    if args.model is None:
        parser.error("a model file is required (or use --build / --batch-build)")
    model_path = Path(args.model)
    if not model_path.exists():
        _eprint(f"Error: SBML file not found: {model_path}")
        sys.exit(1)

    if args.organism:
        config.kegg_organism_code = args.organism
        config.organism_name = KEGG_CODE_TO_NAME.get(args.organism, args.organism)
    if args.batch_size is not None:
        config.batch_size = args.batch_size
    if args.max_concurrent is not None:
        config.max_concurrent = args.max_concurrent

    # Load model
    from src.core.sbml_parser import SBMLParser

    _eprint(f"Loading model: {model_path.name} ...")
    parser_sbml = SBMLParser()
    model_data = parser_sbml.load_model(model_path)
    _eprint(
        f"Model loaded: {model_data.reaction_count} reactions, "
        f"{model_data.metabolite_count} metabolites, "
        f"{model_data.gene_count} genes"
    )

    # Apply organism override (after auto-detect, so explicit flag wins)
    if args.organism:
        model_data.kegg_organism_code = args.organism
        model_data.organism = KEGG_CODE_TO_NAME.get(args.organism, args.organism)
        config.kegg_organism_code = args.organism
        config.organism_name = model_data.organism or args.organism
    elif model_data.kegg_organism_code:
        config.kegg_organism_code = model_data.kegg_organism_code
        if model_data.organism:
            config.organism_name = model_data.organism

    _eprint(f"Organism: {config.organism_name} ({config.kegg_organism_code})")

    # Gap-fill mode
    if args.gap_fill:
        from src.utils.constants import DEFAULT_TASK_FILE, DEFAULT_UNIVERSAL_MODEL

        universal_path = args.universal or config.default_universal_model or DEFAULT_UNIVERSAL_MODEL
        tasks_path = args.tasks or config.default_task_file or DEFAULT_TASK_FILE

        # Validate paths
        if not Path(universal_path).exists():
            _eprint(f"Error: Universal model not found: {universal_path}")
            sys.exit(1)
        if not Path(tasks_path).exists():
            _eprint(f"Error: Task file not found: {tasks_path}")
            sys.exit(1)

        _eprint(f"Universal model: {universal_path}")
        _eprint(f"Task file: {tasks_path}")

        asyncio.run(
            async_gapfill_main(
                config=config,
                model_data=model_data,
                universal_path=universal_path,
                tasks_path=tasks_path,
                medium_arg=args.medium,
                output_model=args.output_model,
                output_report=args.output_report,
                skip_evaluation=args.skip_evaluation,
                include_exchange_gapfill=args.include_exchange_gapfill,
            )
        )
        return

    # No standalone per-reaction model-evaluation mode: KEGG evidence is used
    # only to weight gap-fill candidates, and model quality is judged by
    # metabolic tasks. A bare model therefore requires --gap-fill.
    parser.error(
        "a model was provided without --gap-fill. Per-reaction model evaluation "
        "has been removed; run task-aware gap-filling with --gap-fill (model "
        "quality is judged by metabolic tasks)."
    )


if __name__ == "__main__":
    main()
