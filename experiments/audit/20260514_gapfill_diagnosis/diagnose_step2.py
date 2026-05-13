"""Step 2: Confirm the Step-1 hypothesis.

Step 1 found that manual restoration of the 113 reactions from universal
yielded zero growth — same as depleted — despite all 113 being present in
the universal. The first 5 inspections showed that 2 of 5 had irreversible
bounds in universal vs reversible in iML1515. So:

Hypothesis: BiGG universal stores many reactions as forward-only (0..1000),
but iML1515 holds them as reversible (-1000..1000). When cobrapy
gapfilling.gapfill() picks reactions FROM universal, it picks them WITH
those universal bounds. The added forward-only versions cannot replace
the lost reverse fluxes, so the depleted model stays infeasible.

This script:
1. Counts how many of 113 differ in bounds.
2. Manually restores with **original iML1515 bounds** and re-checks growth.
3. If growth returns to baseline → hypothesis confirmed.

Run:  .venv/bin/python -u experiments/audit/20260514_gapfill_diagnosis/diagnose_step2.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cobra

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.core.universal_loader import UniversalLoader
from src.gapfill.recovery_runner import select_gpr_reactions

OUT = Path(__file__).resolve().parent
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
    say("=== Step 2: bounds-mismatch confirmation ===")

    model = cobra.io.read_sbml_model("data/iML1515.xml")
    baseline = safe_growth(model)
    say(f"iML1515 baseline growth: {baseline:.6f}")

    sampled = select_gpr_reactions(model, 0.05, 42)
    removed_ids = [r.id for r in sampled]
    say(f"removed: {len(removed_ids)} reactions (seed=42)")

    universal = UniversalLoader().load("data/bigg_universal_model_fixed.json")

    # 1. Count bound mismatches across all 113
    bounds_diff: list[dict] = []
    stoich_diff: list[str] = []
    for rid in removed_ids:
        orig = model.reactions.get_by_id(rid)
        uni = universal.reactions.get_by_id(rid)

        orig_mets = {m.id: orig.metabolites[m] for m in orig.metabolites}
        uni_mets = {m.id: uni.metabolites[m] for m in uni.metabolites}

        if orig.bounds != uni.bounds:
            bounds_diff.append({"id": rid, "orig": list(orig.bounds), "uni": list(uni.bounds)})
        if orig_mets != uni_mets:
            stoich_diff.append(rid)

    say(
        f"\nbound mismatches: {len(bounds_diff)} / {len(removed_ids)} "
        f"({100*len(bounds_diff)/len(removed_ids):.1f}%)"
    )
    say(f"stoichiometry mismatches: {len(stoich_diff)} / {len(removed_ids)}")
    say("\nfirst 10 bound diffs (id, orig_bounds, universal_bounds):")
    for b in bounds_diff[:10]:
        say(f"    {b['id']:20s} {b['orig']!s:18s} -> {b['uni']!s:18s}")

    # Classify bound mismatch types
    rev_to_fwd = sum(1 for b in bounds_diff if b["orig"][0] < 0 and b["uni"][0] == 0)
    fwd_to_rev = sum(1 for b in bounds_diff if b["orig"][0] == 0 and b["uni"][0] < 0)
    other = len(bounds_diff) - rev_to_fwd - fwd_to_rev
    say(
        f"\nclass: reversible->forward = {rev_to_fwd}, "
        f"forward->reversible = {fwd_to_rev}, other = {other}"
    )

    # 2. Deplete + restore with ORIGINAL iML1515 bounds
    say("\n=== restoration with original iML1515 bounds ===")
    depleted = model.copy()
    depleted.remove_reactions(
        [depleted.reactions.get_by_id(r.id) for r in sampled],
        remove_orphans=True,
    )
    say(f"depleted growth: {safe_growth(depleted):.6f}")

    restored = depleted.copy()
    to_restore: list[cobra.Reaction] = []
    for rid in removed_ids:
        uni_rxn = universal.reactions.get_by_id(rid).copy()
        orig_rxn = model.reactions.get_by_id(rid)
        # Override bounds with iML1515's original
        uni_rxn.lower_bound = orig_rxn.lower_bound
        uni_rxn.upper_bound = orig_rxn.upper_bound
        to_restore.append(uni_rxn)
    restored.add_reactions(to_restore)
    restored_growth = safe_growth(restored)
    say(f"restored (orig bounds) growth: {restored_growth:.6f}")
    say(f"ratio vs baseline: {restored_growth / baseline if baseline else 0:.4f}")

    # 3. Cross-check: restore with universal bounds (replicate Step 1)
    say("\n=== restoration with universal bounds (sanity check) ===")
    restored_u = depleted.copy()
    restored_u.add_reactions([universal.reactions.get_by_id(rid).copy() for rid in removed_ids])
    g_u = safe_growth(restored_u)
    say(f"restored (universal bounds) growth: {g_u:.6f}")

    # 4. Verdict
    say("\n=== verdict ===")
    if restored_growth >= 0.99 * baseline and g_u < 0.5 * baseline:
        verdict = (
            "CONFIRMED: BiGG universal stores forward-only versions of many "
            "reactions that iML1515 holds as reversible. cobrapy gapfill()"
            " adds them with universal bounds, so the recovered model is "
            "missing essential reverse fluxes."
        )
    elif restored_growth >= 0.99 * baseline:
        verdict = (
            "CONFIRMED: original bounds restore growth fully (universal "
            "bounds also work in this case — but that's not what Step 1 saw)"
        )
    elif restored_growth > 0.5 * baseline:
        verdict = (
            "PARTIAL: bounds matter, but not the whole story. Some other "
            "factor (orphan metabolites? medium?) also blocks recovery."
        )
    else:
        verdict = (
            "REJECTED: bound mismatch is NOT the root cause. Even with "
            "original bounds the model does not grow. Look elsewhere."
        )
    say(verdict)

    summary = {
        "baseline_growth": baseline,
        "depleted_growth": safe_growth(depleted),
        "restored_with_original_bounds_growth": restored_growth,
        "restored_with_universal_bounds_growth": g_u,
        "n_removed": len(removed_ids),
        "n_bound_mismatches": len(bounds_diff),
        "n_stoich_mismatches": len(stoich_diff),
        "bound_mismatch_classes": {
            "reversible_to_forward": rev_to_fwd,
            "forward_to_reversible": fwd_to_rev,
            "other": other,
        },
        "first_10_bound_diffs": bounds_diff[:10],
        "verdict_short": verdict,
    }
    (OUT / "step2_summary.json").write_text(json.dumps(summary, indent=2))
    (OUT / "step2_log.txt").write_text("\n".join(LOG) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
