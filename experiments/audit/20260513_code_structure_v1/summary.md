# Summary — code_structure_v1 (meeting brief)

## Current architecture (one paragraph)

`run.sh` boots a PySide6 GUI (`src/app.py` → `MainWindow`); a parallel
headless CLI lives in `src/cli.py`. Both feed a single `EvidenceEngine`
(`src/evidence/engine.py`) that orchestrates **6 evidence sources** —
KEGG (always on), BiGG (local lookup), UniProt, PubMed, Gemini, Perplexity
— and a `ConfidenceScorer` (`src/evidence/scoring.py`) that takes the
maximum strength per source (STRONG=1.0 / MODERATE=0.6 / WEAK=0.3 /
ABSENT=0.0), normalizes weights over only-active sources, and returns a
final score in `[0, 1]`. Gap-filling is a separate task-driven pipeline
(`src/gapfill/engine.py`) that runs failed metabolic tasks through
`cobra.flux_analysis.gapfilling.gapfill()` against the BiGG universal
model loaded by `src/core/universal_loader.py`. Source weights and
on/off flags live in `src/utils/config.py`; per-source strength
thresholds are hardcoded inside each client.

## Edit locations for minimal-scoring transition (KEGG + BiGG only)

Goal stated in `AGENTS.md §Goal`: keep KEGG and BiGG, disable the others.

Two routes; the **config route is enough** for the 2-source weighted formula
because the scorer auto-redistributes weights over active sources.

### Route 1 — config-only (recommended for v1)

| Edit | File:line | Change |
|---|---|---|
| Disable UniProt | `src/utils/config.py:45` | `enable_uniprot: bool = False` (default) |
| Disable PubMed | `src/utils/config.py:46` | `enable_pubmed: bool = False` |
| Disable Gemini | `src/utils/config.py:47` | `enable_gemini: bool = False` |
| Disable Perplexity | `src/utils/config.py:48` | `enable_perplexity: bool = False` |
| Two-source weight defaults | `src/utils/config.py:36-41` | `weight_kegg=0.6`, `weight_bigg=0.4`, others `0.0` (or leave; auto-renormalized) |

Alternatively, ship a config JSON committed to the repo with the same
values rather than editing module defaults. Either way, no `src/`
behavior changes.

### Route 2 — code path removal (cleaner, larger diff)

If we want the four LLM/text sources to be *unreachable*, not just
disabled:

| Edit | File:line | Change |
|---|---|---|
| Remove UniProt branch | `src/evidence/engine.py:77-87` | Delete the `if self._config.enable_uniprot:` block |
| Remove PubMed branch | `src/evidence/engine.py:90-101` | Delete |
| Remove Gemini branch | `src/evidence/engine.py:104-114` | Delete |
| Remove Perplexity branch | `src/evidence/engine.py:117-127` | Delete |
| Remove pipeline calls | `src/evidence/engine.py:341-410` | Delete `_run_evidence_pipeline()` body for those 4 sources |
| Remove client files | `src/api/{uniprot,pubmed,gemini,perplexity}_client.py` | Delete + clean imports |
| Trim source registry | `src/evidence/evidence_types.py:80-119` | Remove 4 entries from `SOURCE_REGISTRY` |
| Trim config fields | `src/utils/config.py:27-48` | Remove unused weights/keys/flags |

Per `AGENTS.md §Operating rules`, all `src/` edits need user approval before
execution.

### Implement KEGG/BiGG threshold externalization (independent change)

Currently hardcoded; needed if scoring grid search is in scope.

| Concern | File:line | Suggested change |
|---|---|---|
| KEGG match-ratio thresholds (0.2 / 0.5 / 0.8) | `src/api/kegg_client.py:246-256` | Move to `Config.kegg_strength_thresholds: tuple[float, float, float]` |
| BiGG model-count thresholds (5 / 2 / 1) | `src/api/bigg_lookup.py:354-363` | Move to `Config.bigg_strength_thresholds: tuple[int, int]` |

### Implement GPR-removal gap-fill protocol (separate, larger work)

`AGENTS.md §Gap-filling protocol` describes a 5/10/15% × 5-seed reaction
removal protocol. **No such code exists** in `src/gapfill/`. This is an
implementation task, not a refactor. The current gap-fill engine is
task-driven (run failed metabolic tasks → gap-fill them) and would need
either:

- A new entry point alongside `GapFillEngine.run()` that takes
  `(model, removal_ratio, seed)` → randomly removes GPR-positive reactions
  → calls existing gap-fill against the depleted model → returns recovery
  metrics. New file: `src/gapfill/recovery_runner.py` (proposed name).
- A wrapper script under `experiments/gapfilling/` that calls into
  whatever new `src/` API we add. Per `AGENTS.md §Code constraints`,
  algorithm logic must live in `src/`, not `experiments/`.

This is **not part of the minimal-scoring transition** and is listed here
only because it appeared in the audit scope.

## Open questions (need user input or deeper audit)

1. **`src/api/bigg_client.py` is unreferenced by `engine.py`.** Dead code,
   or used by GUI/tests? If dead, delete during minimal-scoring transition.
   Needs grep across `tests/` and `src/gui/`.
2. **Per-source strength thresholds in UniProt / PubMed / Gemini /
   Perplexity clients** — assumed hardcoded based on KEGG/BiGG pattern;
   not actually verified. Will not matter if those sources are disabled.
3. **Universal model path resolution** — `config.default_universal_model`
   is `"data/bigg_universal_model_fixed.json"` (relative); the absolute
   path resolution call site is not traced. Matters if the GUI is run from
   a different CWD.
4. **Worker thread architecture** — `src/gui/workers.py` not opened. CLAUDE.md
   claims asyncio runs in worker threads, but that should be verified
   before any concurrency-sensitive change.
5. **The GPR-removal protocol from `AGENTS.md`** — confirm with user that
   this is genuinely planned-not-yet-built, not something I missed. If
   confirmed, it should be its own design doc, separate from
   minimal-scoring transition.

## Recommended next step

For the meeting:

- Show this summary as the architecture overview.
- Ask the user whether the minimal-scoring transition should follow
  Route 1 (config-only, ~5 line edit, reversible) or Route 2
  (delete code, larger diff, irreversible without git).
- Defer the GPR-removal protocol to a separate design doc.
