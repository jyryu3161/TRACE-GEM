"""Diagnose why recovery_runner.py reported recall=0 / infeasible on iML1515.

Hypothesis under test (Step 1):
- 113 removed reactions are present in BiGG universal (already verified).
- If we BYPASS cobrapy gapfilling.gapfill() and ADD them straight to the
  depleted model, does growth recover to baseline?
  - YES → gapfill MILP is failing despite a feasible solution. Move to
    Step 2 (solver / search diagnostics).
  - NO  → the universal definitions of those reactions differ from the
    iML1515 definitions (bounds, metabolites, stoichiometry).
          Move to Step 2 (definition mismatch).

This script is a thin probe — no algorithmic logic. Run with:
    .venv/bin/python -u experiments/audit/20260514_gapfill_diagnosis/diagnose.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cobra

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root

from src.core.universal_loader import UniversalLoader
from src.gapfill.recovery_runner import select_gpr_reactions

OUT = Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
LOG: list[str] = []


def say(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


def safe_growth(m: cobra.Model) -> float:
    try:
        sol = m.optimize()
        return float(sol.objective_value or 0.0) if sol.status == "optimal" else 0.0
    except Exception:
        return 0.0


def main() -> int:
    say("=== Step 1: manual restoration probe ===")

    # 1. Load iML1515 and measure baseline
    say("[1] loading iML1515...")
    model = cobra.io.read_sbml_model("data/iML1515.xml")
    baseline = safe_growth(model)
    say(f"    iML1515: {len(model.reactions)} rxns, {len(model.metabolites)} mets")
    say(f"    baseline growth: {baseline:.6f}")

    # 2. Same sampling rule as recovery_runner (ratio=0.05, seed=42)
    sampled = select_gpr_reactions(model, 0.05, 42)
    removed_ids = [r.id for r in sampled]
    say(f"[2] sampled removal: {len(removed_ids)} reactions (seed=42)")
    say(f"    first 5 removed: {removed_ids[:5]}")

    # 3. Deplete
    say("[3] depleting copy...")
    depleted = model.copy()
    n_mets_before = len(depleted.metabolites)
    depleted.remove_reactions(
        [depleted.reactions.get_by_id(r.id) for r in sampled],
        remove_orphans=True,
    )
    n_mets_after = len(depleted.metabolites)
    depleted_growth = safe_growth(depleted)
    say(
        f"    depleted: {len(depleted.reactions)} rxns, "
        f"{n_mets_after} mets (was {n_mets_before}; "
        f"{n_mets_before - n_mets_after} metabolites orphan-removed)"
    )
    say(f"    depleted growth: {depleted_growth:.6f}")

    # 4. Load universal
    say("[4] loading universal model...")
    universal = UniversalLoader().load("data/bigg_universal_model_fixed.json")
    say(f"    universal: {len(universal.reactions)} rxns, " f"{len(universal.metabolites)} mets")

    # 5. Restore from universal — direct add (bypass cobrapy gapfill solver)
    say("[5] restoring 113 reactions directly from universal...")
    to_restore: list[cobra.Reaction] = []
    not_found: list[str] = []
    for rid in removed_ids:
        try:
            uni_rxn = universal.reactions.get_by_id(rid)
            to_restore.append(uni_rxn.copy())
        except KeyError:
            not_found.append(rid)
    say(f"    found in universal: {len(to_restore)} / {len(removed_ids)}")
    if not_found:
        say(f"    NOT FOUND in universal: {not_found[:10]}")

    restored = depleted.copy()
    restored.add_reactions(to_restore)
    restored_growth = safe_growth(restored)
    say(f"    restored: {len(restored.reactions)} rxns, " f"{len(restored.metabolites)} mets")
    say(f"    restored growth: {restored_growth:.6f}")
    say(
        f"    >>> growth ratio vs baseline: "
        f"{restored_growth / baseline if baseline else 0.0:.4f}"
    )

    # 6. If restored growth still below baseline, investigate first 5 mismatches
    say("[6] per-reaction comparison (first 5 removed):")
    diffs_summary: dict[str, dict] = {}
    for rid in removed_ids[:5]:
        say(f"\n  --- {rid} ---")
        try:
            orig = model.reactions.get_by_id(rid)
        except KeyError:
            say(f"    iML1515 lookup KeyError on {rid}")
            continue
        try:
            uni = universal.reactions.get_by_id(rid)
        except KeyError:
            say(f"    universal lookup KeyError on {rid}")
            continue

        orig_mets = {m.id: orig.metabolites[m] for m in orig.metabolites}
        uni_mets = {m.id: uni.metabolites[m] for m in uni.metabolites}

        bounds_match = orig.bounds == uni.bounds
        mets_match = orig_mets == uni_mets

        say(
            f"    orig bounds: {orig.bounds}    universal bounds: {uni.bounds}    "
            f"match={bounds_match}"
        )
        say(f"    orig reaction: {orig.reaction}")
        say(f"    uni  reaction: {uni.reaction}")
        say(f"    metabolite-stoich match: {mets_match}")
        if not mets_match:
            only_orig = {k: v for k, v in orig_mets.items() if k not in uni_mets}
            only_uni = {k: v for k, v in uni_mets.items() if k not in orig_mets}
            stoich_diff = {
                k: (orig_mets[k], uni_mets[k])
                for k in orig_mets
                if k in uni_mets and orig_mets[k] != uni_mets[k]
            }
            say(f"    only in orig: {only_orig}")
            say(f"    only in uni:  {only_uni}")
            say(f"    stoich diff:  {stoich_diff}")

        diffs_summary[rid] = {
            "bounds_match": bounds_match,
            "stoich_match": mets_match,
            "orig_bounds": list(orig.bounds),
            "uni_bounds": list(uni.bounds),
        }

    # 7. Diagnostic verdict
    say("\n=== verdict ===")
    if restored_growth >= 0.99 * baseline:
        verdict = (
            "MANUAL RESTORE FULLY RECOVERS GROWTH → cobrapy gapfill is the "
            "bottleneck (search heuristic / MILP), not the universal definitions"
        )
    elif restored_growth >= 0.5 * baseline:
        verdict = (
            "MANUAL RESTORE PARTIALLY RECOVERS GROWTH → both definitions mismatch "
            "AND solver search likely contribute"
        )
    elif restored_growth > 0.0:
        verdict = (
            "MANUAL RESTORE BARELY HELPS → universal definitions differ from "
            "iML1515 for at least some critical reactions"
        )
    else:
        verdict = (
            "MANUAL RESTORE DOES NOTHING → universal definitions disagree on "
            "essential reactions, or removed reactions share an orphaned metabolite"
        )
    say(verdict)

    # 8. Save numeric summary
    summary = {
        "baseline_growth": baseline,
        "depleted_growth": depleted_growth,
        "restored_growth": restored_growth,
        "n_removed": len(removed_ids),
        "n_found_in_universal": len(to_restore),
        "metabolites_orphan_removed": n_mets_before - n_mets_after,
        "verdict_short": verdict,
        "first5_diffs": diffs_summary,
    }
    (OUT / "step1_summary.json").write_text(json.dumps(summary, indent=2))
    (OUT / "step1_log.txt").write_text("\n".join(LOG) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
