"""CLI for MetaTaskGapFill batch evaluation and task-aware gap-filling."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.core.models import (
    EvidenceSource,
    EvidenceTier,
    GapFillResult,
    MetabolicTask,
    ModelData,
    Reaction,
    ReactionEvidence,
)
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
            "Evaluate SBML model reactions and run metabolic-task-based gap-filling."
        ),
    )
    parser.add_argument("model", help="Path to SBML model file (.xml)")
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (extension determines format: .csv or .json). "
        "Default: {model_id}_evidence.csv",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("csv", "json"),
        help="Force output format (overrides extension detection)",
    )
    parser.add_argument(
        "--organism",
        help="KEGG organism code override (e.g. eco, sce, hsa)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Batch size override",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        help="Max concurrent requests override",
    )
    parser.add_argument(
        "--skip-exchange",
        action="store_true",
        help="Skip exchange reactions (EX_*)",
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
            "Base medium for metabolic tasks. Accepts JSON, CSV, or inline spec "
            "like 'glc__D_e(-10);o2_e(-1000)'. If omitted, the draft model's "
            "COBRA medium is used."
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
        help="Skip evidence evaluation of model and candidates",
    )
    gf_group.add_argument(
        "--include-exchange-gapfill",
        action="store_true",
        help=(
            "Allow exchange/demand/sink reactions from the universal model as "
            "gap-fill candidates. Default: excluded."
        ),
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
    """Parse inline medium spec: ``glc__D_e(-10);EX_o2_e(-1000)``."""
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
        medium[rxn_id] = float(match.group(2))
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
    """Load CLI medium input or fall back to the draft model's default medium."""
    if value:
        path = Path(value)
        if path.exists():
            if path.suffix.lower() == ".json":
                return _load_medium_json(path)
            if path.suffix.lower() in {".csv", ".tsv"}:
                return _load_medium_csv(path)
            raise ValueError(f"Unsupported medium file extension: {path.suffix}")
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


def apply_base_medium_to_tasks(
    tasks: list[MetabolicTask],
    base_medium: dict[str, float],
) -> list[MetabolicTask]:
    """Merge base medium into tasks, letting task-specific medium override it."""
    if not base_medium:
        return tasks

    merged_tasks: list[MetabolicTask] = []
    for task in tasks:
        merged_medium = dict(base_medium)
        merged_medium.update(task.medium)
        merged_tasks.append(
            MetabolicTask(
                task_id=task.task_id,
                task_type=task.task_type,
                target_id=task.target_id,
                medium=merged_medium,
                constraints=dict(task.constraints),
                expected_operator=task.expected_operator,
                expected_value=task.expected_value,
                description=task.description,
                category=task.category,
            )
        )
    return merged_tasks


def _resolve_format(args: argparse.Namespace) -> str:
    """Determine output format from --format flag or file extension."""
    if args.format:
        return str(args.format)
    if args.output:
        ext = Path(args.output).suffix.lower()
        if ext == ".json":
            return "json"
    return "csv"


def _serialize_raw_data(raw_data: dict | None) -> dict | None:
    """Make raw_data JSON-serializable."""
    if raw_data is None:
        return None
    result = {}
    for k, v in raw_data.items():
        if hasattr(v, "__dataclass_fields__"):
            result[k] = asdict(v)
        else:
            result[k] = v
    return result


def export_csv(
    filepath: str,
    model_id: str,
    reactions: list[Reaction],
    results: dict[str, ReactionEvidence],
) -> None:
    """Export evaluation results to CSV."""
    from src.evidence.evidence_types import get_ordered_sources

    source_order = get_ordered_sources()
    score_headers = [f"{sc.display_name} Score" for _, sc in source_order]

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Reaction ID",
                "Name",
                "Subsystem",
                "Genes",
                "GPR",
                "Evidence Tier",
                "Evidence Rationale",
                "Legacy Confidence Score",
                *score_headers,
                "Substrate Match",
                "Product Match",
                "EC Numbers",
                "KEGG IDs",
                "Status",
            ]
        )
        for rxn in reactions:
            ev = results.get(rxn.id, ReactionEvidence(rxn.id))
            per_source = []
            for source, _ in source_order:
                attr = f"{source.value}_score"
                per_source.append(f"{getattr(ev, attr, 0.0):.4f}")

            writer.writerow(
                [
                    rxn.id,
                    rxn.name,
                    rxn.subsystem or "",
                    ";".join(rxn.genes),
                    rxn.gene_reaction_rule,
                    ev.evidence_tier.label,
                    ev.evidence_rationale,
                    f"{ev.confidence_score:.4f}",
                    *per_source,
                    f"{ev.substrate_match_ratio:.4f}",
                    f"{ev.product_match_ratio:.4f}",
                    ";".join(ev.ec_numbers),
                    ";".join(ev.kegg_reaction_ids),
                    ev.status.value,
                ]
            )


def export_json(
    filepath: str,
    model_id: str,
    organism: str | None,
    reactions: list[Reaction],
    results: dict[str, ReactionEvidence],
) -> None:
    """Export evaluation results to JSON."""
    reactions_dict: dict[str, dict] = {}
    export: dict[str, object] = {
        "model_id": model_id,
        "organism": organism,
        "total_reactions": len(reactions),
        "reactions": reactions_dict,
    }
    for rxn in reactions:
        ev = results.get(rxn.id, ReactionEvidence(rxn.id))
        reactions_dict[rxn.id] = {
            "name": rxn.name,
            "subsystem": rxn.subsystem,
            "equation": rxn.equation,
            "genes": rxn.genes,
            "evidence_tier": ev.evidence_tier.value,
            "evidence_rationale": ev.evidence_rationale,
            "confidence_score": ev.confidence_score,
            "scores": {
                source.value: getattr(ev, f"{source.value}_score", 0.0) for source in EvidenceSource
            },
            "verification": {
                "substrate_match_ratio": ev.substrate_match_ratio,
                "product_match_ratio": ev.product_match_ratio,
            },
            "ec_numbers": ev.ec_numbers,
            "kegg_reaction_ids": ev.kegg_reaction_ids,
            "evidence_items": [
                {
                    "source": item.source.value,
                    "strength": item.strength.name,
                    "description": item.description,
                    "url": item.url,
                    "raw_data": _serialize_raw_data(item.raw_data),
                }
                for item in ev.items
            ],
            "status": ev.status.value,
        }

    with open(filepath, "w") as f:
        json.dump(export, f, indent=2)


async def async_main(
    config: Config,
    reactions: list[Reaction],
    output_path: str,
    fmt: str,
    model_id: str,
    organism: str | None,
) -> dict[str, ReactionEvidence]:
    """Run the async evaluation pipeline."""
    from src.evidence.engine import EvidenceEngine

    engine = EvidenceEngine(config)
    try:
        _eprint("Initializing evidence engine...")
        await engine.initialize()

        total = len(reactions)
        start_time = time.monotonic()

        def progress_callback(completed: int, total: int, reaction_id: str) -> None:
            pct = completed / total * 100 if total else 0
            filled = int(pct / 5)
            bar = "=" * filled + ">" + " " * (20 - filled - 1)
            elapsed = time.monotonic() - start_time
            _eprint(
                f"\rEvaluating: [{bar}] {completed}/{total} ({pct:.1f}%) "
                f"-- {reaction_id} [{_format_time(elapsed)}]",
                end="",
            )

        results = await engine.evaluate_batch(reactions, progress_callback=progress_callback)
        elapsed = time.monotonic() - start_time
        _eprint(f"\nEvaluation complete: {total} reactions in {_format_time(elapsed)}")

        # Export
        if fmt == "json":
            export_json(output_path, model_id, organism, reactions, results)
        else:
            export_csv(output_path, model_id, reactions, results)

        # Summary statistics
        high = sum(1 for ev in results.values() if ev.evidence_tier == EvidenceTier.HIGH)
        moderate = sum(
            1 for ev in results.values() if ev.evidence_tier == EvidenceTier.MODERATE
        )
        low = sum(1 for ev in results.values() if ev.evidence_tier == EvidenceTier.LOW)
        _eprint(f"  High:      {high} ({high / total * 100:.1f}%)")
        _eprint(f"  Moderate:  {moderate} ({moderate / total * 100:.1f}%)")
        _eprint(f"  Low:       {low} ({low / total * 100:.1f}%)")
        _eprint(f"Results saved to {output_path}")

        return results
    finally:
        await engine.close()


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
    base_medium = load_medium_argument(medium_arg, model_data.cobra_model)
    tasks = apply_base_medium_to_tasks(tasks, base_medium)
    medium_source = medium_arg if medium_arg else "draft model default medium"
    _eprint(f"  {len(tasks)} tasks loaded")
    _eprint(f"  Base medium: {len(base_medium)} exchanges from {medium_source}")

    # Step 4: Evidence evaluation (optional)
    evidence_results: dict[str, ReactionEvidence] = {}

    evidence_engine = EvidenceEngine(config)
    try:
        await evidence_engine.initialize()

        if not skip_evaluation:
            # Evaluate model reactions
            reactions = list(model_data.reactions)
            _eprint(f"Evaluating {len(reactions)} model reactions...")
            eval_start = time.monotonic()

            def model_progress(completed: int, total: int, reaction_id: str) -> None:
                pct = completed / total * 100 if total else 0
                filled = int(pct / 5)
                bar = "=" * filled + ">" + " " * (20 - filled - 1)
                elapsed = time.monotonic() - eval_start
                _eprint(
                    f"\r  Model eval: [{bar}] {completed}/{total} ({pct:.1f}%) "
                    f"-- {reaction_id} [{_format_time(elapsed)}]",
                    end="",
                )

            evidence_results = await evidence_engine.evaluate_batch(
                reactions, progress_callback=model_progress
            )
            _eprint(f"\n  Model evaluation complete: {len(evidence_results)} reactions scored")

            # Evaluate candidates
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

            cand_results = await evidence_engine.evaluate_candidates_batch(
                candidates, progress_callback=cand_progress
            )
            evidence_results.update(cand_results)
            _eprint(f"\n  Candidate evaluation complete: {len(cand_results)} reactions scored")
        else:
            _eprint("Skipping evidence evaluation (--skip-evaluation)")

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

        # Section 2: Added reactions
        writer.writerow(["Added Reactions"])
        writer.writerow(["Reaction ID", "Name", "Subsystem", "Penalty", "GPR"])
        for candidate in result.added_reactions:
            rxn = candidate.reaction
            writer.writerow([
                rxn.id,
                rxn.name,
                rxn.subsystem or "",
                f"{candidate.penalty:.4f}",
                candidate.assigned_gpr,
            ])
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


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Validate model file
    model_path = Path(args.model)
    if not model_path.exists():
        _eprint(f"Error: SBML file not found: {model_path}")
        sys.exit(1)

    # Load config and apply overrides
    from src.utils.logging_config import setup_logging

    setup_logging()
    config = Config.load()

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

    # Filter reactions
    reactions = list(model_data.reactions)
    if args.skip_exchange:
        before = len(reactions)
        reactions = [r for r in reactions if not r.is_exchange]
        _eprint(f"Skipped {before - len(reactions)} exchange reactions")

    if not reactions:
        _eprint("Error: No reactions to evaluate.")
        sys.exit(1)

    # Resolve output path and format
    fmt = _resolve_format(args)
    if args.output:
        output_path = args.output
    else:
        ext = "json" if fmt == "json" else "csv"
        output_path = f"{model_data.id}_evidence.{ext}"

    _eprint(f"Output: {output_path} ({fmt.upper()})")

    # Run evaluation
    asyncio.run(
        async_main(
            config=config,
            reactions=reactions,
            output_path=output_path,
            fmt=fmt,
            model_id=model_data.id,
            organism=model_data.organism,
        )
    )


if __name__ == "__main__":
    main()
