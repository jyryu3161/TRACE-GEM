# Adversarial Code and Publication Audit

Date: 2026-07-10

## Resolved Findings

| Area | Resolution | Verification |
|---|---|---|
| Infeasible tasks passed as zero | Non-optimal solver states always fail and are exported | Task parser tests; iML1515 52/52 all `optimal` |
| Hidden/invalid task chemistry | Background medium is explicit; only water/proton are implicit; pseudo-turnovers are balanced NTP hydrolysis | Task medium and mass-balance tests |
| Universal pruning removed pathways | Directional forward/backward reachability preserves multi-step paths | Toy pathway regression and gap-fill tests |
| Unsupported GPR inference | Multiple KO groups no longer imply AND; genes are draft/proteome restricted; assigned GPR reaches COBRA/SBML | GPR and engine tests |
| Project model loss | Project 2.0 embeds the current SBML snapshot with gzip and SHA-256 | Portable/corrupt snapshot tests |
| API outage became biological absence | API failure is distinct from 404; evidence batches abort above the configured failure fraction; organism misses remain unknown after partial failure | Evidence/organism failure tests |
| Post-hoc evidence claimed as weighting | Deferred evidence mode was removed; all weighted runs evaluate all candidates before optimization | CLI/core/GUI worker tests |
| GUI stale state and unsafe resume | Gap-fill runs transactionally on a model copy; completion synchronizes ModelData; cancellation checkpoints evidence and phase state; phase-3 cancellation rolls back | Workflow, engine, project tests |
| Global-minimum overclaim | UI/docs now say evidence-weighted feasible iterative union, not globally cardinality-minimal | Documentation audit |
| KEGG coefficient blindness | Numeric KEGG coefficients and proportional equivalence are checked; unresolved symbolic coefficients downgrade identity | KEGG/mapper/scoring tests |
| Hidden penalty constants | Every tier cost/multiplier is named, validated, exportable, and included in manifests | Penalty/config/provenance tests |
| Circular validation | Synthetic intersections/decoys are diagnostic-only; independent CSV path reports confusion metrics, Wilson intervals, baselines, ablations, and exact McNemar tests | Validation metrics tests |
| E. coli task overreach | Bundled tasks identify their E. coli scope; non-E. coli CLI/GUI runs require an explicit task file | CLI/wizard tests and protocol |
| Missing run provenance | Gap-fill manifests contain hashes, versions, solver, config, mapping provenance, and policy; deterministic evidence snapshots preserve every solver input record | Provenance tests |
| Build provenance missing | Successful and batch-failed CarveMe runs record FASTA/universe/output hashes, argv, options, duration, and toolchain versions | Build/provenance tests |
| KEGG/BiGG documentation conflict | KEGG is the sole reaction evidence source; BiGG is described only as universal pool/mapping | Active documentation scan |
| Version graph corruption | Corrupt history raises; same-ID different models are fingerprint-namespaced; cleanup/delete/rename repair parent and restore references; diffs include chemical and metadata fields | Version/diff tests |
| Invalid task rows ignored | Required columns, duplicates, bounds, finite numbers, media, and constraints fail fast | Parser tests |
| Wheel omitted data | Wheel installs default data under the installation scheme and runtime discovery handles venv/user locations | Clean-venv wheel test |
| Quality gates missing | Python 3.10/3.12 CI, lockfile, Ruff, mypy, pytest, LICENSE, and CITATION are present | Local full quality run |
| Incomplete/duplicate report columns | One penalty column; full reaction/evidence/solver/error provenance is exported | Report tests |
| Cache connection leak | A previous SQLite connection is closed before reconnecting on a new event loop | Cache lifecycle test |
| Invalid config accepted | Scientific/runtime ranges and enums are validated; corrupt config fails explicitly; saves are atomic | Config tests |
| Non-portable project paths | Paths are project-relative when possible and the model is self-contained | Project path/snapshot tests |

## Publication Boundaries

The repository does not contain an independently curated evidence benchmark.
Therefore no sensitivity, specificity, precision, or biological superiority claim
is established by the bundled synthetic controls. `evidence_benchmark_template.csv`
is a schema, not data.

The 52 bundled tasks are an E. coli regression suite. A 52/52 iML1515 result is a
software/scenario regression, not a general model-quality score. Cross-organism
claims require organism-specific tasks, experimental media growth/no-growth,
gene-essentiality data, and an external model audit such as MEMOTE.

The gap-fill objective is an evidence-weighted sum solved per failed task and
combined iteratively while protecting passing tasks. It is not a proof of the
globally smallest reaction cardinality across all tasks. Report both weighted
cost and reaction count, plus penalty sensitivity and unweighted baselines.

KEGG REST does not expose a database release identifier in the used responses.
Manifests state this limitation and preserve hashes plus the full evidence
snapshot used by the optimizer. A paper should archive those artifacts and state
the retrieval time and KEGG licensing/access conditions.

## Residual Verification Requirements

- The local environment used for this audit lacked PySide6/pytest-qt, so 102 GUI
  tests were skipped locally. CI installs `.[dev]` and runs them offscreen.
- Real CarveMe/DIAMOND/Gurobi/SCIP construction was not rerun during this audit.
  The integration marker and build manifests are ready for a licensed/toolchain
  environment.
- Numerical tolerances and alternative optima can differ across LP/MILP solvers.
  Publication runs must fix the solver/version and archive every manifest.
- Independent evidence labels, pathway holdouts, phenotype observations, and
  gene-essentiality measurements must be collected externally before a paper can
  make accuracy or biological improvement claims.
