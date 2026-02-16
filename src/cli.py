"""CLI for batch evaluation of genome-scale metabolic models."""

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

from src.core.models import EvidenceSource, Reaction, ReactionEvidence
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
        prog="gem-evaluator-cli",
        description="Batch-evaluate SBML model reactions against biological databases.",
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
    return parser


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
                "Confidence Score",
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
        high = sum(1 for ev in results.values() if ev.confidence_score >= 0.7)
        low = sum(1 for ev in results.values() if ev.confidence_score < 0.4)
        mid = len(results) - high - low
        _eprint(f"  High (>=0.7):  {high} ({high / total * 100:.1f}%)")
        _eprint(f"  Medium:        {mid} ({mid / total * 100:.1f}%)")
        _eprint(f"  Low (<0.4):    {low} ({low / total * 100:.1f}%)")
        _eprint(f"Results saved to {output_path}")

        return results
    finally:
        await engine.close()


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
