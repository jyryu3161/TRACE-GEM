# Audit type — code_structure (v1)

> Type-wide guide for `experiments/audit/<YYYYMMDD>_code_structure_v*/`.
> Per AGENTS.md §Experiment storage, this `design.md` is written before the
> first experiment of this type and lock-ins the methodology.

## Purpose

Locate where the model_evaluator's **6-source scoring** and **gap-filling** logic
live, so we can plan the minimal-redesign edits called for in
`AGENTS.md §Goal` (KEGG + BiGG only, others disabled).

This is *audit*, not implementation. No code is modified during these audits.

## Method

For each audit run:

1. Read `AGENTS.md` and `CLAUDE.md` first.
2. Trace the call graph from `run.sh` → `src/app.py` → first major branches.
3. For each behavior under question, locate the file and quote ≤5 lines of
   actual source. Include `path:line` references.
4. If a behavior is not derivable from the code (e.g., requires runtime
   data), record it as **"not verified from code"** in `notes.md`. Do not
   infer.

## Output structure

```
20260513_code_structure_v1/
├── design.md      # this file
├── notes.md       # detailed per-section findings (A → B → C → D)
└── summary.md     # ≤1 page meeting brief
```

## Scope (v1)

In:

- A. Entry point and run modes (GUI vs CLI)
- B. 6 evidence sources — file/class location, on/off mechanism
- C. Scoring logic — strength judgement, weighted average, hardcoded vs config
- D. Gap-filling — `cobra.flux_analysis.gapfill()` call site, universal
  model loading, GPR-based reaction filtering

Out (deferred to later audits):

- Versioning system (`src/versioning/*`)
- GUI internals (PySide6 worker model, Qt signals)
- Cache layer correctness audit (we only note its existence)
- Test fixtures

## Time budget

Target ≤60 min total. Per AGENTS.md §Working with sessions, if exceeded,
stop and report progress.

## Sign-off criteria

`summary.md` must contain:

1. One paragraph describing the current architecture.
2. A list of edit locations needed for the minimal-scoring transition.
3. A list of open questions ("not verified from code" items).
