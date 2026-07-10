#!/usr/bin/env python
"""Independent benchmark and synthetic diagnostics for KEGG evidence tiers.

This validates the tier's REAL job — judging universal gap-fill CANDIDATES —
NOT model quality (which is task-based). The tier weights which universal
reactions are worth adding to a strain, so the property that matters is
*candidate-selection precision*: meaningful candidates should score High/Moderate
and spurious ones (decoys) must almost never score High.

An independent performance claim requires ``--benchmark`` with externally
curated ``reaction_id,label,split`` rows. Without it, the script only runs
synthetic identity-corruption diagnostics and explicitly emits
``diagnostic_only``; universal/gold-model ID overlap is not a gold-standard
estimate of biological precision.

Synthetic diagnostic design (default iML1515):

  * Positive set — universal reactions (``data/bigg_universal_model_fixed.json``
    via ``UniversalLoader().load``) whose reaction id is ALSO in the gold model.
    These are database-membership controls, not independently labeled positives.
    Each is evaluated through the real candidate path:
    ``convert_cobra_reaction`` + ``CandidateReaction`` +
    ``EvidenceEngine.evaluate_candidate``.

  * Negative controls (decoys) — built from the fully-specified positives by
    corrupting the resolved KEGG inputs:
        (a) wrong-identity : swap BOTH the KEGG reaction id AND EC to another
            reaction's, keep this reaction's metabolites.
        (b) metabolite-shuffle : keep this reaction's KEGG id + EC, swap in
            another reaction's metabolites.
    Decoys are scored through the SAME KEGG scoring path (kegg_client.check_evidence
    + ConfidenceScorer) as the candidates. The headline metric is the decoy
    HIGH false-positive rate (target ~0), plus P(>=Moderate | decoy).

The cross-line agreement / permutation baseline used by the previous regime is
intentionally dropped: in a curated GEM the EC and KEGG annotations are
curator-correlated, so that signal was null.

Usage:
    python scripts/validate_evidence_tiers.py
        [--model data/iML1515.xml] [--universal data/bigg_universal_model_fixed.json]
        [--benchmark benchmark.csv] [--organism eco] [--limit 200]
        [--seed 0] [--concurrency 8] [--json out.json]

KEGG is fetched live or from a TTL cache. Preserve the generated JSON and the
application evidence snapshot for exact run provenance.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api import kegg_client as kc  # noqa: E402
from src.core.cobra_utils import convert_cobra_reaction  # noqa: E402
from src.core.models import (  # noqa: E402
    CandidateReaction,
    EvidenceTier,
    ReactionEvidence,
)
from src.core.sbml_parser import SBMLParser  # noqa: E402
from src.core.universal_loader import UniversalLoader  # noqa: E402
from src.evidence.engine import EvidenceEngine  # noqa: E402
from src.utils.config import Config  # noqa: E402
from src.utils.provenance import file_record  # noqa: E402
from src.validation.metrics import binary_metrics, exact_mcnemar  # noqa: E402


class Inputs:
    """Resolved KEGG inputs for one candidate reaction (or a decoy of one)."""

    __slots__ = (
        "rxn_id",
        "kegg_ids",
        "subs",
        "prods",
        "sub_stoich",
        "prod_stoich",
        "stoich_complete",
        "ec",
    )

    def __init__(
        self,
        rxn_id,
        kegg_ids,
        subs,
        prods,
        sub_stoich,
        prod_stoich,
        stoich_complete,
        ec,
    ):
        self.rxn_id = rxn_id
        self.kegg_ids = kegg_ids
        self.subs = subs
        self.prods = prods
        self.sub_stoich = sub_stoich
        self.prod_stoich = prod_stoich
        self.stoich_complete = stoich_complete
        self.ec = ec


async def resolve_inputs(engine: EvidenceEngine, reaction) -> Inputs:
    """Resolve a candidate reaction's KEGG inputs (universal annotation format).

    Uses the same ``resolve(universal=True)`` path that ``evaluate_candidate``
    uses internally, so the inputs we manipulate to build decoys match the
    inputs the candidate was actually scored on.
    """
    assert engine._mapper is not None
    ext = await engine._mapper.resolve(reaction, universal=True)
    return Inputs(
        reaction.id,
        list(ext.kegg_reaction_ids),
        list(ext.kegg_substrate_ids),
        list(ext.kegg_product_ids),
        dict(ext.kegg_substrate_stoichiometry),
        dict(ext.kegg_product_stoichiometry),
        ext.kegg_stoichiometry_complete,
        list(ext.ec_numbers),
    )


async def classify(kegg, scorer, inp: Inputs):
    """Score a set of resolved KEGG inputs through the real candidate path.

    Mirrors ``EvidenceEngine._run_kegg_verification`` + ``ConfidenceScorer.score``
    exactly (kegg_client.check_evidence -> lift provenance states -> rule-based
    tier), so decoys and candidates are judged identically.
    """
    items = await kegg.check_evidence(
        None,
        kegg_reaction_ids=inp.kegg_ids,
        ec_numbers=inp.ec,
        model_substrates_kegg=inp.subs,
        model_products_kegg=inp.prods,
        model_substrate_stoichiometry=inp.sub_stoich,
        model_product_stoichiometry=inp.prod_stoich,
        model_stoichiometry_complete=inp.stoich_complete,
    )
    ev = ReactionEvidence(reaction_id=inp.rxn_id)
    ev.items = items
    best = items[0] if items else None
    raw = best.raw_data if (best and best.raw_data) else {}
    ev.kegg_anchored = bool(raw.get("kegg_anchored", False))
    ev.reconciliation_state = raw.get("reconciliation_state", "unverifiable")
    ev.ec_concordance_state = raw.get("ec_concordance_state", "unknown")
    ev.stoichiometry_state = raw.get("stoichiometry_state", "unverifiable")
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


def build_positive_candidates(
    universal, gold_model, loader: UniversalLoader
) -> list[CandidateReaction]:
    """Universal reactions whose id is also in the gold model (known-correct).

    Membership uses the same normalization as ``UniversalLoader.extract_candidates``
    (case-insensitive, ``R_`` prefix tolerant), and skips exchange/demand/sink
    utility reactions — exactly the reactions that would otherwise be offered as
    gap-fill candidates.
    """
    model_ids = loader._build_model_reaction_ids(gold_model)
    positives: list[CandidateReaction] = []
    for rxn in universal.reactions:
        if loader.is_exchange_or_utility_reaction(rxn.id):
            continue
        normalized = rxn.id.lower()
        normalized_no_prefix = rxn.id[2:].lower() if rxn.id.startswith("R_") else rxn.id.lower()
        if normalized in model_ids or normalized_no_prefix in model_ids:
            positives.append(
                CandidateReaction(
                    reaction=convert_cobra_reaction(rxn),
                    source_model=universal.id or "bigg_universal",
                )
            )
    return positives


def _pick_donor(pool: list[Inputs], i: Inputs, rng: random.Random) -> Inputs:
    """Pick a donor reaction distinct from ``i``.

    Prefer a donor whose KEGG ids AND metabolites are disjoint from ``i`` so the
    decoy is unambiguously wrong (two BiGG ids occasionally share a KEGG id).
    Falls back to any different reaction.
    """
    i_keggs = set(i.kegg_ids)
    i_mets = set(i.subs) | set(i.prods)
    for _ in range(8):
        d = pool[rng.randrange(len(pool))]
        if d.rxn_id == i.rxn_id:
            continue
        if set(d.kegg_ids).isdisjoint(i_keggs) and (set(d.subs) | set(d.prods)).isdisjoint(i_mets):
            return d
    d = pool[rng.randrange(len(pool))]
    while d.rxn_id == i.rxn_id and len(pool) > 1:
        d = pool[rng.randrange(len(pool))]
    return d


def _load_benchmark(path: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
        required = {"reaction_id", "label", "split"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError(f"benchmark requires columns: {sorted(required)}")
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            reaction_id = (row.get("reaction_id") or "").strip()
            label = (row.get("label") or "").strip().lower()
            split = (row.get("split") or "").strip()
            if not reaction_id or reaction_id in seen:
                raise ValueError(f"benchmark row {line_number}: missing/duplicate reaction_id")
            if label not in {"positive", "negative"}:
                raise ValueError(f"benchmark row {line_number}: label must be positive/negative")
            if not split:
                raise ValueError(f"benchmark row {line_number}: split is required")
            seen.add(reaction_id)
            rows.append({"reaction_id": reaction_id, "label": label, "split": split})
    if not rows:
        raise ValueError("benchmark contains no labeled rows")
    return rows


def _tier_without(scorer, evidence: ReactionEvidence, component: str) -> EvidenceTier:
    ablated = copy.deepcopy(evidence)
    if component == "ec":
        ablated.ec_concordance_state = "unknown"
    elif component == "metabolites":
        ablated.reconciliation_state = "unverifiable"
        ablated.stoichiometry_state = "unverifiable"
    else:
        raise ValueError(component)
    scorer.score(ablated)
    return ablated.evidence_tier


async def evaluate_independent_benchmark(
    engine: EvidenceEngine, universal, rows: list[dict[str, str]], concurrency: int
) -> dict:
    by_id = {
        reaction.id: CandidateReaction(
            reaction=convert_cobra_reaction(reaction),
            source_model=universal.id or "bigg_universal",
        )
        for reaction in universal.reactions
    }
    missing = [row["reaction_id"] for row in rows if row["reaction_id"] not in by_id]
    if missing:
        raise ValueError(
            f"benchmark reactions missing from universal ({len(missing)}): "
            + ", ".join(missing[:10])
        )
    evidence = await gather_limited(
        [engine.evaluate_candidate(by_id[row["reaction_id"]]) for row in rows], concurrency
    )
    failures = [item.reaction_id for item in evidence if item.status.value == "error"]
    if failures:
        raise RuntimeError(
            f"independent benchmark has {len(failures)} evidence API failures: "
            + ", ".join(failures[:10])
        )

    labels = [row["label"] == "positive" for row in rows]
    strict = [item.evidence_tier is EvidenceTier.HIGH for item in evidence]
    permissive = [
        item.evidence_tier in {EvidenceTier.HIGH, EvidenceTier.MODERATE} for item in evidence
    ]
    annotation_baseline = [bool(item.kegg_reaction_ids) for item in evidence]
    always_positive = [True] * len(rows)
    no_ec = [
        _tier_without(engine._scorer, item, "ec") in {EvidenceTier.HIGH, EvidenceTier.MODERATE}
        for item in evidence
    ]
    no_metabolites = [
        _tier_without(engine._scorer, item, "metabolites")
        in {EvidenceTier.HIGH, EvidenceTier.MODERATE}
        for item in evidence
    ]

    return {
        "status": "independent_benchmark",
        "n": len(rows),
        "labels": dict(Counter(row["label"] for row in rows)),
        "splits": dict(Counter(row["split"] for row in rows)),
        "strict_high": binary_metrics(labels, strict),
        "permissive_high_or_moderate": binary_metrics(labels, permissive),
        "baselines": {
            "annotation_presence": binary_metrics(labels, annotation_baseline),
            "always_positive": binary_metrics(labels, always_positive),
        },
        "ablations": {
            "without_ec": binary_metrics(labels, no_ec),
            "without_metabolite_reconciliation": binary_metrics(labels, no_metabolites),
        },
        "paired_comparisons": {
            "full_vs_annotation_presence": exact_mcnemar(labels, permissive, annotation_baseline),
            "full_vs_without_ec": exact_mcnemar(labels, permissive, no_ec),
            "full_vs_without_metabolites": exact_mcnemar(labels, permissive, no_metabolites),
        },
        "tier_distribution": dict(Counter(item.evidence_tier.value for item in evidence)),
        "records": [
            {
                "reaction_id": row["reaction_id"],
                "label": row["label"],
                "split": row["split"],
                "tier": item.evidence_tier.value,
                "kegg_ids": item.kegg_reaction_ids,
                "verified_kegg_ids": item.verified_kegg_reaction_ids,
                "reconciliation_state": item.reconciliation_state,
                "stoichiometry_state": item.stoichiometry_state,
                "ec_concordance_state": item.ec_concordance_state,
                "error": item.error_message,
            }
            for row, item in zip(rows, evidence, strict=True)
        ],
    }


async def run(args) -> dict:
    rng = random.Random(args.seed)

    loader = UniversalLoader()
    print(f"Loading universal model {args.universal} ...")
    universal = loader.load(args.universal)
    print(f"Loading gold-standard model {args.model} ...")
    gold = SBMLParser().load_model(args.model)

    positives = build_positive_candidates(universal, gold, loader)
    n_intersection = len(positives)
    rng.shuffle(positives)
    if args.limit:
        positives = positives[: args.limit]

    cfg = Config(kegg_organism_code=args.organism, organism_name=args.organism)
    engine = EvidenceEngine(cfg)
    await engine.initialize()
    kegg, scorer = engine._kegg, engine._scorer

    try:
        report: dict = {
            "validation_status": ("independent_benchmark" if args.benchmark else "diagnostic_only"),
            "gold_model": str(args.model),
            "universal": str(args.universal),
            "inputs": {
                "gold_model": file_record(args.model),
                "universal": file_record(args.universal),
            },
            "organism": args.organism,
            "random_seed": args.seed,
            "sample_limit": args.limit,
            "counts": {
                "universal_reactions": len(universal.reactions),
                "gold_reactions": len(gold.reactions),
                "intersection_positives": n_intersection,
                "evaluated_positives": len(positives),
            },
        }
        if args.benchmark:
            benchmark_rows = _load_benchmark(args.benchmark)
            report["benchmark_file"] = file_record(args.benchmark)
            report["independent_benchmark"] = await evaluate_independent_benchmark(
                engine, universal, benchmark_rows, args.concurrency
            )
        if not positives:
            report["positives"] = {"note": "no universal∩gold candidates found"}
            report["decoys"] = {"n": 0, "note": "no positives"}
            return report

        # --- 1. Positives via the real candidate path --------------------
        print(
            f"Evaluating {len(positives)} positive candidates "
            f"(universal∩gold) via evaluate_candidate ..."
        )

        async def _eval_positive(c: CandidateReaction):
            ev = await engine.evaluate_candidate(c)
            inp = await resolve_inputs(engine, c.reaction)  # offline, for decoys
            return ev, inp

        pos = await gather_limited([_eval_positive(c) for c in positives], args.concurrency)
        pos_evidence = [ev for ev, _ in pos]
        pos_inputs = [inp for _, inp in pos]

        errors = sum(1 for ev in pos_evidence if ev.status.value == "error")
        report["counts"]["evaluation_errors"] = errors

        dist = Counter(ev.evidence_tier.value for ev in pos_evidence)
        n = len(pos_evidence)
        assessable = sum(1 for ev in pos_evidence if ev.kegg_anchored)
        hi = dist.get("high", 0)
        mod = dist.get("moderate", 0)
        report["positives"] = {
            "n": n,
            "tier_distribution": dict(dist),
            "assessable_count": assessable,
            "assessable_fraction": round(assessable / n, 4),
            "high_rate": round(hi / n, 4),
            "moderate_rate": round(mod / n, 4),
            "high_or_moderate_rate": round((hi + mod) / n, 4),
            # Conditioned on candidates the tier can actually anchor: when no KEGG
            # anchor exists the tier correctly abstains (Not-assessable) instead of
            # mis-ranking, so the discriminative skew lives in the assessable subset.
            "high_or_moderate_rate_assessable": (
                round((hi + mod) / assessable, 4) if assessable else None
            ),
        }

        # --- 2. Decoy false-positive rate --------------------------------
        # Pool: fully-specified positives (KEGG id + informative mets + EC),
        # anchored and not unverifiable — the only ones that can carry a
        # meaningful (corruptible) identity.
        pool = [
            inp
            for inp, ev in zip(pos_inputs, pos_evidence, strict=True)
            if ev.kegg_anchored
            and inp.kegg_ids
            and (inp.subs or inp.prods)
            and inp.ec
            and ev.reconciliation_state != kc.RECON_UNVERIFIABLE
        ]
        report["counts"]["decoy_pool_size"] = len(pool)

        if len(pool) < 2:
            report["decoys"] = {"n": 0, "note": "insufficient fully-specified pool"}
            return report

        decoy_inputs: list[Inputs] = []
        kinds: list[str] = []
        for i in pool:
            donor = _pick_donor(pool, i, rng)
            # wrong-identity: BOTH identity channels (KEGG id + EC) point to a
            # different reaction, so this reaction's metabolites must mismatch.
            decoy_inputs.append(
                Inputs(
                    f"{i.rxn_id}~wrongid",
                    donor.kegg_ids,
                    i.subs,
                    i.prods,
                    i.sub_stoich,
                    i.prod_stoich,
                    i.stoich_complete,
                    donor.ec,
                )
            )
            kinds.append("wrong_identity")
            # metabolite-shuffle: real KEGG id + EC, another reaction's metabolites.
            decoy_inputs.append(
                Inputs(
                    f"{i.rxn_id}~shufmet",
                    i.kegg_ids,
                    donor.subs,
                    donor.prods,
                    donor.sub_stoich,
                    donor.prod_stoich,
                    donor.stoich_complete,
                    i.ec,
                )
            )
            kinds.append("metabolite_shuffle")

        print(f"Evaluating {len(decoy_inputs)} decoys ...")
        decoy_res = await gather_limited(
            [classify(kegg, scorer, inp) for inp in decoy_inputs], args.concurrency
        )

        nd = len(decoy_res)
        d_hi = sum(1 for (t, *_r) in decoy_res if t == EvidenceTier.HIGH)
        d_mod_up = sum(
            1 for (t, *_r) in decoy_res if t in (EvidenceTier.HIGH, EvidenceTier.MODERATE)
        )
        per_kind: Counter[str] = Counter()
        per_kind_hi: Counter[str] = Counter()
        per_kind_modup: Counter[str] = Counter()
        for kind, (t, *_r) in zip(kinds, decoy_res, strict=True):
            per_kind[kind] += 1
            if t == EvidenceTier.HIGH:
                per_kind_hi[kind] += 1
            if t in (EvidenceTier.HIGH, EvidenceTier.MODERATE):
                per_kind_modup[kind] += 1
        report["decoys"] = {
            "n": nd,
            "tier_distribution": dict(Counter(t.value for (t, *_r) in decoy_res)),
            "high_false_positive_rate": round(d_hi / nd, 4),
            "ge_moderate_rate": round(d_mod_up / nd, 4),
            "high_fpr_by_kind": {k: round(per_kind_hi[k] / per_kind[k], 4) for k in per_kind},
            "ge_moderate_by_kind": {k: round(per_kind_modup[k] / per_kind[k], 4) for k in per_kind},
        }
        return report
    finally:
        await engine.close()


def print_report(rep: dict) -> None:
    c = rep["counts"]
    print("\n" + "=" * 72)
    print("CANDIDATE-SELECTION PRECISION — KEGG-only evidence tier")
    print(f"  status:    {rep['validation_status']}")
    print(f"  gold:      {rep['gold_model']}")
    print(f"  universal: {rep['universal']}  (organism={rep['organism']})")
    print("=" * 72)
    print(
        f"Universal reactions: {c['universal_reactions']:>6}   "
        f"gold reactions: {c['gold_reactions']:>6}"
    )
    print(
        f"Positive pool (universal∩gold, non-utility): {c['intersection_positives']}   "
        f"evaluated: {c['evaluated_positives']}"
    )
    if c.get("evaluation_errors"):
        print(f"  (evaluation errors: {c['evaluation_errors']})")

    pos = rep.get("positives", {})
    if "tier_distribution" in pos:
        n = pos["n"]
        print("\nPOSITIVES (known-correct E. coli candidates) — expect High/Moderate:")
        for tier in ("high", "moderate", "low", "not_assessable"):
            v = pos["tier_distribution"].get(tier, 0)
            print(f"  {tier:16s} {v:5d}  ({_pct(v, n)})")
        anchored = pos["assessable_count"]
        hm_count = pos["tier_distribution"].get("high", 0) + pos["tier_distribution"].get(
            "moderate", 0
        )
        print(f"  {'-' * 34}")
        print(f"  High+Moderate rate (all):       {_pct(hm_count, n)}")
        print(f"  KEGG-anchored (assessable):     {_pct(anchored, n)}")
        if anchored:
            print(
                f"  High+Moderate | anchored:       {_pct(hm_count, anchored)}"
                "   <- discriminative skew"
            )
    else:
        print(f"\nPOSITIVES: {pos.get('note', 'n/a')}")

    d = rep.get("decoys", {})
    print(f"\nDECOYS (pool={c.get('decoy_pool_size', 0)}, n={d.get('n', 0)}) — expect ~0 High:")
    if d.get("n"):
        print(f"  HIGH false-positive rate: {d['high_false_positive_rate']:.4f}  (target ~0)")
        print(f"  >=MODERATE rate:          {d['ge_moderate_rate']:.4f}")
        print(f"  HIGH-FPR by kind:         {d['high_fpr_by_kind']}")
        print(f"  >=MOD    by kind:         {d['ge_moderate_by_kind']}")
    else:
        print(f"  {d.get('note', 'n/a')}")

    # One-line verdict: among candidates the tier can anchor, meaningful ones
    # should skew High/Moderate; decoys must almost never score High.
    if pos.get("tier_distribution") and d.get("n"):
        hm = pos.get("high_or_moderate_rate_assessable") or 0.0
        print(
            "\nSYNTHETIC DIAGNOSTIC (not an independent performance verdict):",
            f"(positives H+M|anchored={hm:.2f}, "
            f"decoy High-FPR={d['high_false_positive_rate']:.3f})",
        )
    independent = rep.get("independent_benchmark")
    if independent:
        strict = independent["strict_high"]
        permissive = independent["permissive_high_or_moderate"]
        print("\nINDEPENDENT BENCHMARK:")
        print(
            f"  n={independent['n']} labels={independent['labels']} splits={independent['splits']}"
        )
        print(
            "  High: sensitivity="
            f"{strict['sensitivity']} specificity={strict['specificity']} "
            f"precision={strict['precision']} MCC={strict['matthews_correlation_coefficient']}"
        )
        print(
            "  High+Moderate: sensitivity="
            f"{permissive['sensitivity']} specificity={permissive['specificity']} "
            f"precision={permissive['precision']} "
            f"MCC={permissive['matthews_correlation_coefficient']}"
        )
    print("=" * 72)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="data/iML1515.xml", help="Gold-standard GEM")
    ap.add_argument(
        "--universal",
        default="data/bigg_universal_model_fixed.json",
        help="Universal model to draw candidates from",
    )
    ap.add_argument("--organism", default="eco")
    ap.add_argument(
        "--benchmark",
        default="",
        help="Independent curated CSV (reaction_id,label,split)",
    )
    ap.add_argument(
        "--require-independent",
        action="store_true",
        help="exit with an error unless --benchmark is provided",
    )
    ap.add_argument("--limit", type=int, default=200, help="Sample size of positives (0 = all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    if args.require_independent and not args.benchmark:
        ap.error("--require-independent requires --benchmark")

    report = await run(args)
    print_report(report)

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
