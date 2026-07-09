#!/usr/bin/env python
"""Publication-grade validation of the KEGG-only evidence tier system.

Gold standard: a manually-curated GEM (default iML1515). Because the model's own
KEGG/EC annotations feed the scorer, "% High" alone would only measure annotation
completeness. The non-circular signal is **cross-line agreement**: metabolite
reconciliation and EC concordance are derived from *different* curator inputs
(compound IDs vs EC numbers, neither the reaction KEGG ID), so their agreement —
compared against a permutation baseline — is genuine cross-validation. Given the
false-positive priority, the headline metric is the **decoy false-positive rate**:
deliberately-wrong reactions must not be scored High.

Usage:
    python scripts/validate_evidence_tiers.py [--model data/iML1515.xml]
        [--organism eco] [--limit N] [--seed 0] [--concurrency 8]
        [--currency-sweep] [--json out.json]

KEGG is fetched live but cached; warm the cache once, then reruns are offline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api import kegg_client as kc  # noqa: E402
from src.core.models import EvidenceTier, ReactionEvidence  # noqa: E402
from src.core.sbml_parser import SBMLParser  # noqa: E402
from src.evidence.engine import EvidenceEngine  # noqa: E402
from src.evidence.scoring import ConfidenceScorer  # noqa: E402
from src.utils.config import Config  # noqa: E402


class Inputs:
    """Resolved KEGG inputs for one reaction (or a decoy of one)."""

    __slots__ = ("rxn_id", "kegg_ids", "subs", "prods", "ec", "is_boundary")

    def __init__(self, rxn_id, kegg_ids, subs, prods, ec, is_boundary):
        self.rxn_id = rxn_id
        self.kegg_ids = kegg_ids
        self.subs = subs
        self.prods = prods
        self.ec = ec
        self.is_boundary = is_boundary


async def resolve_inputs(engine: EvidenceEngine, reaction) -> Inputs:
    ext = await engine._mapper.resolve(reaction)
    is_boundary = reaction.id.startswith(("EX_", "DM_", "SK_", "sink_")) or not (
        reaction.reactants and reaction.products
    )
    return Inputs(
        reaction.id,
        list(ext.kegg_reaction_ids),
        list(ext.kegg_substrate_ids),
        list(ext.kegg_product_ids),
        list(ext.ec_numbers),
        is_boundary,
    )


async def classify(kegg, scorer: ConfidenceScorer, inp: Inputs):
    """Run the real scoring path (kegg_client + scorer) for a set of inputs."""
    items = await kegg.check_evidence(
        None,
        kegg_reaction_ids=inp.kegg_ids,
        ec_numbers=inp.ec,
        model_substrates_kegg=inp.subs,
        model_products_kegg=inp.prods,
    )
    ev = ReactionEvidence(reaction_id=inp.rxn_id)
    ev.items = items
    best = items[0] if items else None
    raw = best.raw_data if (best and best.raw_data) else {}
    ev.kegg_anchored = bool(raw.get("kegg_anchored", False))
    ev.reconciliation_state = raw.get("reconciliation_state", "unverifiable")
    ev.ec_concordance_state = raw.get("ec_concordance_state", "unknown")
    scorer.score(ev)
    return ev.evidence_tier, ev.reconciliation_state, ev.ec_concordance_state, ev.kegg_anchored


async def gather_limited(coros, concurrency):
    sem = asyncio.Semaphore(concurrency)

    async def _run(c):
        async with sem:
            return await c

    return await asyncio.gather(*[_run(c) for c in coros])


def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


async def evaluate_all(kegg, scorer, inputs, concurrency):
    results = await gather_limited([classify(kegg, scorer, i) for i in inputs], concurrency)
    return list(zip(inputs, results, strict=True))


async def run(args) -> dict:
    rng = random.Random(args.seed)
    md = SBMLParser().load_model(args.model)
    reactions = list(md.reactions)
    rng.shuffle(reactions)
    if args.limit:
        reactions = reactions[: args.limit]

    cfg = Config(kegg_organism_code=args.organism, organism_name=args.organism)
    engine = EvidenceEngine(cfg)
    await engine.initialize()
    kegg, scorer = engine._kegg, ConfidenceScorer()

    try:
        print(f"Resolving {len(reactions)} reactions from {args.model} ...")
        inputs = [await resolve_inputs(engine, r) for r in reactions]

        print("Evaluating real reactions against KEGG (cached) ...")
        real = await evaluate_all(kegg, scorer, inputs, args.concurrency)

        report: dict = {"model": str(args.model), "n": len(reactions)}

        # --- 1. Tier distribution + NA composition -----------------------
        dist = Counter(tier.value for _, (tier, *_r) in real)
        report["tier_distribution"] = dict(dist)
        assessable = sum(1 for _, (_t, _r, _e, anc) in real if anc)
        report["assessable_fraction"] = assessable / len(real)
        na = [inp for inp, (tier, *_r) in real if tier == EvidenceTier.NOT_ASSESSABLE]
        na_boundary = sum(1 for i in na if i.is_boundary)
        report["not_assessable"] = {
            "count": len(na),
            "boundary_transport_or_exchange": na_boundary,
            "internal_no_kegg": len(na) - na_boundary,
        }

        # --- 2. Cross-line agreement (non-circular) + permutation --------
        # Reactions where BOTH channels give a definite verdict.
        both = [
            (recon == kc.RECON_FULL, ecs == kc.EC_CONCORDANT)
            for _, (_t, recon, ecs, _a) in real
            if recon != kc.RECON_UNVERIFIABLE and ecs != kc.EC_UNKNOWN
        ]
        if both:
            met = [m for m, _ in both]
            ec = [e for _, e in both]
            observed = sum(1 for m, e in zip(met, ec, strict=True) if m == e) / len(both)
            baselines = []
            for _ in range(200):
                shuffled = ec[:]
                rng.shuffle(shuffled)
                baselines.append(
                    sum(1 for m, e in zip(met, shuffled, strict=True) if m == e) / len(both)
                )
            report["cross_line_agreement"] = {
                "n_both_informative": len(both),
                "observed": round(observed, 3),
                "permutation_baseline_mean": round(sum(baselines) / len(baselines), 3),
                "permutation_baseline_max": round(max(baselines), 3),
            }
        else:
            report["cross_line_agreement"] = {"n_both_informative": 0}

        # --- 3. Decoy false-positive rate --------------------------------
        # Pool: fully-specified reactions (KEGG id + informative mets + EC).
        pool = [
            i for i, (_t, recon, _e, anc) in real
            if anc and i.kegg_ids and (i.subs or i.prods) and i.ec
            and recon != kc.RECON_UNVERIFIABLE
        ]
        report["decoy_pool_size"] = len(pool)
        decoy_inputs: list[Inputs] = []
        kinds: list[str] = []
        if len(pool) >= 2:
            for i in pool:
                donor = pool[rng.randrange(len(pool))]
                while donor.rxn_id == i.rxn_id and len(pool) > 1:
                    donor = pool[rng.randrange(len(pool))]
                # wrong-identity: swap BOTH KEGG id and EC to another reaction,
                # keep this reaction's metabolites. Both identity channels then
                # describe a different reaction, so its metabolites must mismatch.
                # (Corrupting EC too is required — keeping the real EC lets the
                # EC-fallback correctly re-identify the reaction, which is a true
                # positive, not a false one.)
                decoy_inputs.append(
                    Inputs(f"{i.rxn_id}~wrongid", donor.kegg_ids, i.subs, i.prods, donor.ec, False)
                )
                kinds.append("wrong_identity")
                # metabolite-shuffle: this reaction's KEGG id/EC, another's mets.
                decoy_inputs.append(
                    Inputs(f"{i.rxn_id}~shufmet", i.kegg_ids, donor.subs, donor.prods, i.ec, False)
                )
                kinds.append("metabolite_shuffle")
            decoy_res = await evaluate_all(kegg, scorer, decoy_inputs, args.concurrency)
            hi = sum(1 for _, (t, *_r) in decoy_res if t == EvidenceTier.HIGH)
            momore = sum(
                1 for _, (t, *_r) in decoy_res
                if t in (EvidenceTier.HIGH, EvidenceTier.MODERATE)
            )
            per_kind = Counter()
            per_kind_hi = Counter()
            for kind, (_, (t, *_r)) in zip(kinds, decoy_res, strict=True):
                per_kind[kind] += 1
                if t == EvidenceTier.HIGH:
                    per_kind_hi[kind] += 1
            report["decoys"] = {
                "n": len(decoy_res),
                "high_false_positive_rate": round(hi / len(decoy_res), 4),
                "ge_moderate_rate": round(momore / len(decoy_res), 4),
                "high_fpr_by_kind": {
                    k: round(per_kind_hi[k] / per_kind[k], 4) for k in per_kind
                },
            }
        else:
            report["decoys"] = {"n": 0, "note": "insufficient fully-specified pool"}

        return report
    finally:
        await engine.close()


def print_report(rep: dict) -> None:
    n = rep["n"]
    print("\n" + "=" * 70)
    print(f"EVIDENCE TIER VALIDATION — {rep['model']}  (n={n} reactions)")
    print("=" * 70)
    print("\nTier distribution:")
    for tier in ("high", "moderate", "low", "not_assessable"):
        c = rep["tier_distribution"].get(tier, 0)
        print(f"  {tier:16s} {c:5d}  ({_pct(c, n)})")
    print(f"\nAssessable (KEGG-anchored): {_pct(int(rep['assessable_fraction']*n), n)}")
    na = rep["not_assessable"]
    print(
        f"Not-assessable breakdown: {na['count']} total — "
        f"{na['boundary_transport_or_exchange']} boundary/transport, "
        f"{na['internal_no_kegg']} internal-no-KEGG"
    )
    cl = rep["cross_line_agreement"]
    if cl.get("n_both_informative"):
        print("\nCross-line agreement (metabolite reconciliation vs EC concordance):")
        print(f"  informative on both channels: {cl['n_both_informative']}")
        print(f"  observed agreement:           {cl['observed']}")
        print(
            f"  permutation baseline:         {cl['permutation_baseline_mean']} "
            f"(max {cl['permutation_baseline_max']})"
        )
    d = rep["decoys"]
    print(f"\nDecoys (pool={rep.get('decoy_pool_size', 0)}, n={d.get('n', 0)}):")
    if d.get("n"):
        print(f"  HIGH false-positive rate:  {d['high_false_positive_rate']}  (target ~0)")
        print(f"  >=MODERATE rate:           {d['ge_moderate_rate']}")
        print(f"  HIGH-FPR by kind:          {d['high_fpr_by_kind']}")
    print("=" * 70)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="data/iML1515.xml")
    ap.add_argument("--organism", default="eco")
    ap.add_argument("--limit", type=int, default=0, help="0 = all reactions")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument(
        "--currency-sweep",
        action="store_true",
        help="Re-run under empty / default / expanded currency sets (sensitivity).",
    )
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    default_currency = set(kc._CURRENCY_COMPOUND_IDS)
    report = await run(args)
    print_report(report)

    if args.currency_sweep:
        report["sensitivity_currency_set"] = {}
        expanded = default_currency | {
            "C00021", "C00027", "C00025", "C00024", "C00068", "C00131",
        }
        for name, cset in (("empty", set()), ("expanded", expanded)):
            kc._CURRENCY_COMPOUND_IDS = cset
            print(f"\n--- sensitivity: currency set = {name} ({len(cset)} compounds) ---")
            rep2 = await run(args)
            report["sensitivity_currency_set"][name] = {
                "tier_distribution": rep2["tier_distribution"],
                "decoy_high_fpr": rep2["decoys"].get("high_false_positive_rate"),
                "cross_line_observed": rep2["cross_line_agreement"].get("observed"),
            }
            print(
                f"  tiers={rep2['tier_distribution']}  "
                f"decoy_high_fpr={rep2['decoys'].get('high_false_positive_rate')}  "
                f"cross_line={rep2['cross_line_agreement'].get('observed')}"
            )
        kc._CURRENCY_COMPOUND_IDS = default_currency

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
