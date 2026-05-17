"""GPR-removal gap-fill recovery runner.

Implements the protocol described in `AGENTS.md §Gap-filling protocol`:

    Targets: reactions with non-empty GPR
    Selection: random sampling
    Ratios: 5%, 10%, 15% (independent — re-sample from original each time)
    Repeats: 5 seeds per ratio
    Filler: cobra.flux_analysis.gapfilling.gapfill()

This runner is a **thin wrapper** per `AGENTS.md §Code constraints`:

- Algorithmic logic (the actual gap-fill solve) is delegated to
  `cobra.flux_analysis.gapfilling.gapfill()` — a public COBRApy API
  already in `requirements.txt`.
- Universal model loading reuses `src.core.universal_loader.UniversalLoader`.
- Reaction removal uses `cobra.Model.remove_reactions(remove_orphans=True)`.
- Organism filtering reuses `src.gapfill.organism_filter.OrganismFilter`
  to shrink the universal model before gap-fill. Without this filter, the
  default GLPK solver does not return in reasonable time against the full
  BiGG universal (verified: 26+ min on iML1515 without finishing —
  see experiments/gapfilling/20260513_smoke_5pct_seed42/notes.md).

`src/gapfill/engine.py` is *not* imported because its `run()` is
task-driven (requires `tasks` + `evidence_results`); the GPR-removal
protocol is task-agnostic. Both ultimately funnel to the same COBRApy
`gapfill()` call (see `engine.py:408-413`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cobra
from cobra.flux_analysis.gapfilling import gapfill as cobra_gapfill

from src.cache.cache_manager import CacheManager
from src.core.mapping_data import MappingData
from src.core.universal_loader import UniversalLoader
from src.gapfill.organism_filter import OrganismFilter

logger = logging.getLogger("gem_evaluator.gapfill.recovery_runner")

# Project-relative defaults aligned with src/utils/config.py:51
_DEFAULT_UNIVERSAL = "data/bigg_universal_model_fixed.json"
_DEFAULT_LOWER_BOUND = 0.05  # mirrors Config.gapfill_lower_bound


@dataclass
class RunConfig:
    model_path: str
    universal_path: str
    ratio: float
    seed: int
    output_dir: str
    organism: str | None = None  # KEGG organism code (eco, sce, ...). None = skip filter
    lower_bound: float = _DEFAULT_LOWER_BOUND
    reversible_correction: bool = True  # see _apply_reversibility_correction()


@dataclass
class RunMetrics:
    recovery_recall: float = 0.0
    growth_diff: float = 0.0
    over_addition: int = 0
    gapfill_time_sec: float = 0.0
    failure_mode: str = "ok"
    # Supporting numbers for interpretation
    baseline_growth: float = 0.0
    depleted_growth: float = 0.0
    recovered_growth: float = 0.0  # aka gapfilled_growth
    n_gpr_reactions: int = 0
    n_removed: int = 0
    n_added: int = 0  # aka n_added_reactions
    n_recovered: int = 0
    n_universal_before_filter: int = 0
    n_universal_after_filter: int = 0
    n_universal_reversibility_corrected: int = 0
    organism_filter_time_sec: float = 0.0
    removed_reaction_ids: list[str] = field(default_factory=list)
    added_reaction_ids: list[str] = field(default_factory=list)


def _apply_reversibility_correction(universal: cobra.Model) -> int:
    """Restore reversibility on a freshly loaded universal model.

    Per supervisor guidance (2026-05-14):
    BiGG universal stores reversible reactions as forward-only. Restore
    reversibility on load; non-physical flux (EGC etc.) is caught downstream
    by Q1/Q2 quality tests.

    Diagnosis backing this fix is in
    `experiments/audit/20260514_gapfill_diagnosis/notes.md`
    (37/113 mismatched reactions, all reversible->forward, 32.7% of removed
    iML1515 reactions at 5%/seed=42).

    Returns the number of reactions whose lower_bound changed.
    """
    n_corrected = 0
    for rxn in universal.reactions:
        if rxn.upper_bound > 0 and rxn.lower_bound != -1000.0:
            rxn.lower_bound = -1000.0
            n_corrected += 1
    return n_corrected


def select_gpr_reactions(model: cobra.Model, ratio: float, seed: int) -> list[cobra.Reaction]:
    """Pick `ratio` of reactions with a non-empty GPR rule, deterministically."""
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"ratio must be in (0, 1), got {ratio}")

    gpr_rxns = [r for r in model.reactions if r.gene_reaction_rule.strip()]
    if not gpr_rxns:
        return []

    rng = random.Random(seed)
    n = max(1, int(round(len(gpr_rxns) * ratio)))
    # Sort by ID first to make `random.Random.sample` reproducible regardless
    # of cobra's reaction iteration order (which depends on the SBML reader).
    gpr_rxns.sort(key=lambda r: r.id)
    return rng.sample(gpr_rxns, n)


def _safe_growth(model: cobra.Model) -> float:
    """Return optimal objective value, or 0.0 if infeasible."""
    try:
        sol = model.optimize()
        if sol.status != "optimal" or sol.objective_value is None:
            return 0.0
        return float(sol.objective_value)
    except Exception:
        return 0.0


async def _filter_universal_to_organism(
    universal: cobra.Model,
    depleted: cobra.Model,
    organism_code: str,
    note: callable[[str], None],
) -> tuple[cobra.Model, float]:
    """Shrink universal to organism-relevant reactions using OrganismFilter.

    Returns (filtered_universal, elapsed_seconds).

    Strategy:
    1. Use UniversalLoader.extract_candidates(universal, depleted) — this
       yields CandidateReaction objects for every universal reaction NOT in
       the depleted model (so it includes the just-removed reactions we
       want to recover).
    2. Run OrganismFilter.filter_candidates() — sets candidate.organism_exists.
    3. Accept candidates with organism_exists in {True, None}. None means
       "no KEGG ID resolvable" — keep them since they might still be
       relevant (better recall than precision).
    4. Build the filtered universal by COPYING universal and removing all
       reactions whose id is neither in depleted nor in the accepted set.
    """
    t0 = time.monotonic()

    note("extracting candidates (universal ∖ depleted)...")
    loader = UniversalLoader()
    candidates = loader.extract_candidates(universal, depleted)
    note(f"  candidates: {len(candidates)}")

    # Initialize organism filter. CacheManager + MappingData are best-effort.
    cache_mgr: CacheManager | None = None
    mapping: MappingData | None = None
    try:
        cache_mgr = CacheManager()
        await cache_mgr.initialize()
    except Exception as e:
        note(f"  cache disabled: {e}")
        cache_mgr = None
    try:
        mapping = MappingData.load()
    except Exception as e:
        note(f"  mapping_data disabled: {e}")
        mapping = None

    of = OrganismFilter(
        organism_code=organism_code,
        cache_manager=cache_mgr,
        mapping_data=mapping,
    )
    try:
        note(f"initializing OrganismFilter for '{organism_code}' (KEGG link/reaction)...")
        await of.initialize()
        note(f"  organism reactions loaded: {len(of._organism_reactions or [])}")  # noqa: SLF001

        await of.filter_candidates(candidates)

        accepted_ids = {
            c.reaction.id
            for c in candidates
            if c.organism_exists is True or c.organism_exists is None
        }
        rejected = sum(1 for c in candidates if c.organism_exists is False)
        note(
            f"  filter outcome: accepted={len(accepted_ids)} "
            f"(true+unknown), rejected={rejected}"
        )
    finally:
        await of.close()
        if cache_mgr:
            try:
                await cache_mgr.close()
            except Exception:
                pass

    # Also keep reactions already in depleted (don't filter them out — they
    # share metabolite IDs with universal, and removing them costs nothing).
    depleted_ids = {r.id for r in depleted.reactions}

    note("building filtered universal model (copy + prune)...")
    filtered = universal.copy()
    to_drop = [
        r for r in filtered.reactions if r.id not in accepted_ids and r.id not in depleted_ids
    ]
    filtered.remove_reactions(to_drop, remove_orphans=True)
    note(
        f"  after organism filter: {len(filtered.reactions)} rxns "
        f"(was {len(universal.reactions)})"
    )

    # Additional shrinkage: metabolite-compatibility filter. Keep only
    # reactions whose metabolites are ALL present in the depleted model.
    # This is independent of KEGG (no network) and aggressively reduces the
    # MILP size. Removed reactions are preserved because their metabolites
    # remain in `depleted` (cobra.remove_reactions(remove_orphans=True)
    # only drops a metabolite when no remaining reaction uses it).
    depleted_metabolite_ids = {m.id for m in depleted.metabolites}
    incompatible = [
        r
        for r in filtered.reactions
        if not all(m.id in depleted_metabolite_ids for m in r.metabolites)
    ]
    filtered.remove_reactions(incompatible, remove_orphans=True)
    note(
        f"  after metabolite-compat filter: {len(filtered.reactions)} rxns "
        f"(dropped {len(incompatible)} reactions using exotic metabolites)"
    )

    elapsed = time.monotonic() - t0
    return filtered, elapsed


def _make_run_record(cfg: RunConfig, metrics: RunMetrics) -> dict:
    return {
        "config": asdict(cfg),
        "metrics": asdict(metrics),
        "schema": "recovery_runner.v2",
    }


def _ensure_outdir(path: str) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_outputs(out: Path, cfg: RunConfig, metrics: RunMetrics, notes_lines: list[str]) -> None:
    """Write config.json + metrics.json + notes.md side by side."""
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=2))
    (out / "metrics.json").write_text(json.dumps(_make_run_record(cfg, metrics), indent=2))
    (out / "notes.md").write_text("# Run notes\n\n```\n" + "\n".join(notes_lines) + "\n```\n")


async def _run_async(cfg: RunConfig) -> RunMetrics:
    """Async run: required when --organism is given (OrganismFilter is async)."""
    metrics = RunMetrics()
    out = _ensure_outdir(cfg.output_dir)
    notes_lines: list[str] = []

    def note(msg: str) -> None:
        logger.info(msg)
        notes_lines.append(msg)

    note(
        f"recovery_runner v2: model={cfg.model_path} ratio={cfg.ratio} "
        f"seed={cfg.seed} organism={cfg.organism}"
    )

    # 1. Load
    note("loading user model...")
    model = cobra.io.read_sbml_model(cfg.model_path)
    note(f"  user model: {len(model.reactions)} rxns, {len(model.metabolites)} mets")

    note("loading universal model via UniversalLoader...")
    universal = UniversalLoader().load(cfg.universal_path)
    metrics.n_universal_before_filter = len(universal.reactions)
    note(
        f"  universal: {metrics.n_universal_before_filter} rxns, "
        f"{len(universal.metabolites)} mets"
    )

    # Option A — reversibility correction (see _apply_reversibility_correction
    # docstring and experiments/audit/20260514_gapfill_diagnosis/notes.md).
    if cfg.reversible_correction:
        n_corr = _apply_reversibility_correction(universal)
        metrics.n_universal_reversibility_corrected = n_corr
        note(
            f"  reversibility correction: lower_bound -> -1000 on " f"{n_corr} universal reactions"
        )
    else:
        note("  reversibility correction: OFF (--no-reversible-correction)")

    # 2. Baseline
    metrics.baseline_growth = _safe_growth(model)
    note(f"baseline growth: {metrics.baseline_growth:.6f}")

    # 3. Sample
    sampled = select_gpr_reactions(model, cfg.ratio, cfg.seed)
    metrics.n_gpr_reactions = sum(1 for r in model.reactions if r.gene_reaction_rule.strip())
    metrics.n_removed = len(sampled)
    metrics.removed_reaction_ids = [r.id for r in sampled]
    note(f"GPR reactions: {metrics.n_gpr_reactions}, sampled to remove: {metrics.n_removed}")
    if not sampled:
        metrics.failure_mode = "no_gpr_reactions"
        _write_outputs(out, cfg, metrics, notes_lines)
        return metrics

    # 4. Deplete
    depleted = model.copy()
    removed_in_copy = [depleted.reactions.get_by_id(r.id) for r in sampled]
    depleted.remove_reactions(removed_in_copy, remove_orphans=True)
    metrics.depleted_growth = _safe_growth(depleted)
    note(f"depleted: {len(depleted.reactions)} rxns (growth={metrics.depleted_growth:.6f})")

    # 4b. Optional: organism filter to shrink universal
    target_universal = universal
    if cfg.organism:
        target_universal, of_time = await _filter_universal_to_organism(
            universal, depleted, cfg.organism, note
        )
        metrics.organism_filter_time_sec = of_time
        note(f"organism filter elapsed: {of_time:.2f}s")
    else:
        note("organism filter skipped (no --organism flag)")
    metrics.n_universal_after_filter = len(target_universal.reactions)

    # 5. Gap-fill
    note(
        f"running cobra.flux_analysis.gapfilling.gapfill("
        f"lower_bound={cfg.lower_bound}, universal_size={metrics.n_universal_after_filter})..."
    )
    t0 = time.monotonic()
    added: list[cobra.Reaction] = []
    try:
        result = cobra_gapfill(
            depleted,
            target_universal,
            lower_bound=cfg.lower_bound,
            iterations=1,
        )
        if result and result[0]:
            added = list(result[0])
        else:
            metrics.failure_mode = "no_solution"
    except cobra.exceptions.Infeasible as e:
        metrics.failure_mode = f"infeasible: {e}"
    except Exception as e:
        metrics.failure_mode = f"error: {type(e).__name__}: {e}"
    metrics.gapfill_time_sec = time.monotonic() - t0
    note(
        f"gap-fill done in {metrics.gapfill_time_sec:.2f}s, "
        f"added={len(added)}, failure_mode={metrics.failure_mode}"
    )

    # 6. Apply + recovered growth
    if added:
        depleted.add_reactions(added)
        metrics.recovered_growth = _safe_growth(depleted)
    else:
        metrics.recovered_growth = metrics.depleted_growth

    metrics.n_added = len(added)
    metrics.added_reaction_ids = [r.id for r in added]

    # 7. Metrics
    removed_set = set(metrics.removed_reaction_ids)
    added_set = set(metrics.added_reaction_ids)
    recovered_set = removed_set & added_set
    metrics.n_recovered = len(recovered_set)
    metrics.recovery_recall = metrics.n_recovered / metrics.n_removed if metrics.n_removed else 0.0
    metrics.over_addition = max(0, metrics.n_added - metrics.n_recovered)
    metrics.growth_diff = abs(metrics.baseline_growth - metrics.recovered_growth)

    note(
        f"metrics: recall={metrics.recovery_recall:.3f}, "
        f"over_addition={metrics.over_addition}, "
        f"growth_diff={metrics.growth_diff:.6f}"
    )

    _write_outputs(out, cfg, metrics, notes_lines)
    return metrics


def run(cfg: RunConfig) -> RunMetrics:
    """Sync entry that delegates to the async pipeline."""
    return asyncio.run(_run_async(cfg))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="recovery_runner",
        description=(
            "Run a single GPR-removal gap-fill recovery experiment. "
            "Per AGENTS.md §Gap-filling protocol."
        ),
    )
    p.add_argument("--model", required=True, help="Path to user SBML model (.xml)")
    p.add_argument(
        "--universal",
        default=_DEFAULT_UNIVERSAL,
        help=f"Path to universal model (default: {_DEFAULT_UNIVERSAL})",
    )
    p.add_argument(
        "--ratio",
        type=float,
        required=True,
        help="Fraction of GPR reactions to remove (e.g. 0.05 for 5%%)",
    )
    p.add_argument("--seed", type=int, required=True, help="Random seed for sampling")
    p.add_argument(
        "--organism",
        default=None,
        help=(
            "KEGG organism code (e.g. eco). When given, universal is pre-filtered "
            "by OrganismFilter (recommended; full universal is too slow for default "
            "GLPK)."
        ),
    )
    p.add_argument("--output", required=True, help="Experiment output directory")
    p.add_argument(
        "--lower-bound",
        type=float,
        default=_DEFAULT_LOWER_BOUND,
        help=f"Gap-fill objective lower bound (default: {_DEFAULT_LOWER_BOUND})",
    )
    p.add_argument(
        "--no-reversible-correction",
        action="store_true",
        help=(
            "Disable the universal reversibility correction (default: on). "
            "Use this to reproduce v2 behaviour where BiGG universal's "
            "forward-only reactions stayed forward-only."
        ),
    )
    p.add_argument("--log-level", default="INFO", help="Python logging level (default: INFO)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = RunConfig(
        model_path=args.model,
        universal_path=args.universal,
        ratio=args.ratio,
        seed=args.seed,
        output_dir=args.output,
        organism=args.organism,
        lower_bound=args.lower_bound,
        reversible_correction=not args.no_reversible_correction,
    )
    try:
        metrics = run(cfg)
    except FileNotFoundError as e:
        print(f"file not found: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        logger.exception("recovery_runner failed")
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1

    summary = {
        "recovery_recall": round(metrics.recovery_recall, 4),
        "growth_diff": round(metrics.growth_diff, 6),
        "depleted_growth": round(metrics.depleted_growth, 6),
        "gapfilled_growth": round(metrics.recovered_growth, 6),
        "n_added_reactions": metrics.n_added,
        "over_addition": metrics.over_addition,
        "n_universal_reversibility_corrected": metrics.n_universal_reversibility_corrected,
        "gapfill_time_sec": round(metrics.gapfill_time_sec, 3),
        "organism_filter_time_sec": round(metrics.organism_filter_time_sec, 3),
        "n_universal_after_filter": metrics.n_universal_after_filter,
        "n_universal_before_filter": metrics.n_universal_before_filter,
        "failure_mode": metrics.failure_mode,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
