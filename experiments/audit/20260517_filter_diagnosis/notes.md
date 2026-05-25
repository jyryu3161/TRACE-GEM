# v6 diagnosis — metabolite-compat filter drops 16 of 113 removed reactions

**Date**: 2026-05-17
**Trigger**: v4/v5 iML1515 runs both failed at cobrapy's `validate()`
step despite Gurobi solving the MILP in 11-87 seconds. Source-reading
showed the validation failure means "MILP-chosen reactions don't restore
growth ≥ 0.05" — i.e. the *right* reactions aren't in the candidate
pool. v5 notes (`experiments/gapfilling/20260517_smoke_v5_notes.md`)
proposed the metabolite-compat filter as the likely culprit.

## Verdict

**HYPOTHESIS CONFIRMED**.

```json
{
  "n_removed": 113,
  "n_survivors": 97,
  "n_dropped_by_metabolite_filter": 16,
  "n_not_in_universal": 0,
  "n_metabolites_orphan_removed": 13
}
```

- 113/113 removed reactions exist in the universal (re-verified).
- After deplete-with-`remove_orphans=True`, 13 metabolites are dropped.
- **16 of the 113 universal-side removed reactions use at least one
  of those 13 orphans**, so the metabolite-compat filter rejects them.
- The MILP therefore cannot select them. cobrapy's `validate()` adds the
  *available* selections to the original model and finds growth still
  below 0.05 → `RuntimeError: Failed to validate gap filled model`.

## The 13 orphaned metabolites and the 16 reactions they take down

```
5dglcn_p     -> 5DGLCNt2rpp, 5DGLCNtex
acglc__D_c   -> GLCATr
dmbzid_c     -> NNDMBRT
frulys_p     -> FRULYSt2pp, FRULYStex
g6p_p        -> G6Pt6_2pp, G6Ptex
gam_c        -> MC6PH
h2s_p        -> H2St1pp, H2Stex
malt6p_c     -> MALTptspp, MC6PH
mchtbs6p_c   -> DC6PDA, MC6PH
thcur_c      -> DHCURR
udcpgl_c     -> UDPGPT
34dhpha_c    -> HPACOAT
34dphacoa_c  -> HPACOAT
```

Pattern: most of these are dead-end byproducts that only appear in one
or two specialised reactions. When the only-producer-or-consumer is
itself in the removed sample, the metabolite is orphaned, and every
universal-side reaction touching that metabolite is now incompatible
with the depleted model.

## Why this defeats both v4 and v5

- Total candidate pool after metabolite-compat filter: 4664 reactions
  (includes the 97 surviving removed-reaction IDs + ~4567 others).
- The MILP can't reconstruct the *original* biomass-producing topology
  because 16 essential pieces are absent.
- It picks alternative reactions, but they can't carry the lost flux —
  `validate()` rejects.
- v5's `integer_threshold=1e-9` widened the selection set but did not
  add back the 16 missing reactions.

## Recommended fix (production-grade, reference-free)

### v6.A (preferred) — deplete with `remove_orphans=False`

One-line change in `recovery_runner.py:_run_async`:

```python
depleted.remove_reactions(removed_in_copy, remove_orphans=True)
                                                       # ^^^^ change to False
```

Effects:

- Depleted keeps all 1877 metabolites (vs 1864 currently).
- Universal versions of the 16 currently-dropped reactions pass the
  metabolite-compat filter.
- Candidate pool grows to ~4680 (4664 + 16). MILP sees all 113 removed
  reactions as candidates.
- Side-effect: orphan metabolites stay in depleted with no producer or
  consumer. They cannot accumulate or be consumed in FBA, so they don't
  perturb the baseline. Verified by yesterday's Step-2 diagnostic which
  did exactly this implicitly (manual `add_reactions` reintroduces the
  metabolites; growth went back to 1.0000 × baseline).

This fix is **reference-free**: it changes only how the depleted model
is built, never inspects `removed_reaction_ids` in the filter. Compliant
with `AGENTS.md §Gap-filling protocol` selection-must-be-reference-free
clause.

### v6.B (alternative) — leave deplete as-is, restore the orphan metabolites separately

If keeping orphans inside depleted is undesirable for other reasons,
the metabolite-compat filter could be relaxed:

```python
# OLD: require all metabolites present
incompatible = [r for r in filtered.reactions
                if not all(m.id in depleted_met_ids for m in r.metabolites)]
# NEW: require at least one metabolite present
incompatible = [r for r in filtered.reactions
                if not any(m.id in depleted_met_ids for m in r.metabolites)]
```

This is less surgical (allows reactions that introduce entirely-new
metabolites). Would balloon the candidate pool. Slower MILP. Likely
unnecessary given 6.A's clean fit.

### Why NOT v6.C — narrow metabolite-compat to organism-relevant metabolites only

Tempting but **reference-shaded**: would require knowing which
metabolites the organism is expected to use, which leaks information
about the target system. Don't go there.

## Suggested v6 implementation order

1. Apply v6.A (single-line edit).
2. Re-run iML1515 5%/seed42 v6 (recovery_runner with same flags as v5).
3. Expected: `n_added_reactions ≈ 113`, `recovery_recall > 0.5`,
   `gapfilled_growth ≈ 0.877` (matches baseline per Step-2 manual
   restore).
4. If v6 succeeds: close design.md §6.1 (bound mismatch — fixed in v3),
   §6.2 (GLPK timeout — fixed in v4), §6.3 (random essentials — by
   design), §6.4 (KEGG outage — independent). The new gap (orphan
   metabolite over-filter) was found and closed here.

## Files

```
experiments/audit/20260517_filter_diagnosis/
├── diagnose.py     (155 lines, read-only probe)
├── output.txt      (full diagnostic log)
├── summary.json    (machine-readable result)
└── notes.md        (this file)
```

진단 스크립트(diagnose.py)는 archive/recovery-runner-v7 branch에 보존됨.

## Time

- Hypothesis design: 2 min
- Script + run: 6 min
- Interpretation + writeup: 5 min
- Total: ~13 min (within 15-min cap)
