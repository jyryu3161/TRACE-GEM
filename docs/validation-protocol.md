# Validation Protocol

## Claim Boundaries

The bundled `universal_essential_tasks.csv` is an E. coli-oriented regression
suite. Passing it is not evidence that a model is globally biologically accurate,
nor that the same tasks are valid for another organism. The software may claim
task feasibility for the stated model, medium, solver, and task file. It must not
claim a universally high-quality GEM from that pass rate alone.

The synthetic controls in `scripts/validate_evidence_tiers.py` test whether
deliberately mismatched KEGG identities are rejected. They are diagnostic tests,
not an independent estimate of biological precision.

## Independent Evidence Benchmark

Use a preregistered CSV with `reaction_id,label,split` columns. Labels must be
assigned by curators without using this tool's tier output, its BiGG-to-KEGG
mapping, or the same KEGG reconciliation rule as the labeling criterion.
`label` is `positive` or `negative`; `split` identifies organism/source and must
be fixed before analysis. Report every exclusion and unresolved ID.

Run both strict (`High`) and permissive (`High or Moderate`) thresholds. Report
sensitivity, specificity, precision, negative predictive value, F1, balanced
accuracy, Matthews correlation coefficient, confusion counts, and 95% Wilson
intervals. Compare against annotation-presence and always-positive baselines,
and report EC and metabolite-reconciliation ablations with paired McNemar tests.

## Gap-Fill Benchmark

1. Hold out reactions from published models using pathway-aware splits; do not
   sample only single reactions that remain bypassable.
2. Remove complete multi-step pathway segments and record the true held-out set.
3. Evaluate reaction precision/recall, task recovery, protected-task regression,
   weighted objective, cardinality, runtime, and infeasibility.
4. Compare unweighted COBRApy gap-fill, tier-only, organism-only, and the full
   policy. Sweep all penalty ratios declared in the run manifest.
5. Use at least one organism not represented in rule development. Supply an
   organism-specific task set and media; do not reuse the bundled E. coli suite.

## External Model Quality

Report MEMOTE results, experimentally observed growth/no-growth across media,
gene-essentiality precision/recall where data exist, mass/charge balance,
blocked-reaction fraction, thermodynamically infeasible cycles, and comparison
against the unmodified draft. Preserve raw inputs, tool versions, solver, random
seeds, exclusions, and the generated manifest for every run.
