# AGENTS.md

> Research operations guide for AI coding agents working in this repository.
> For tool usage (install, run, I/O), see `CLAUDE.md`. This document adds the
> *research workflow* on top of the tool itself.
>
> Branch: `auto-research` · Base: `main` (6-source system)
> This branch is a minimal redesign for autonomous task quality and gap-filling research.

---

## Read order

Before any work, read in this order:

1. `CLAUDE.md` — what the tool does (install, run, I/O, code structure)
2. `AGENTS.md` (this file) — how to run research with the tool

Skipping step 1 leads to attempting auto-research without understanding the underlying tool. Don't do it.

---

## Goal

This branch focuses on two capabilities:

1. **Task quality evaluation** — does the model perform what it should, and refuse what it shouldn't?
2. **Gap-filling quality** — when reactions are removed, are they restored sensibly?

The design is intentionally minimal. Of the original 6 evidence sources, only **KEGG and BiGG** are active. UniProt, PubMed, Gemini, and Perplexity are disabled in this branch.

---

## Autoresearch pattern (adapted)

This work adapts the workflow pattern from [karpathy/autoresearch](https://github.com/karpathy/autoresearch). The original is for LLM training and is not directly applicable; we borrow the *pattern*, not the code.

| karpathy/autoresearch | This project |
|---|---|
| `program.md` (agent skill) | `AGENTS.md` (this file) |
| `train.py` (agent edits) | scoring/gap-filling configs (agent edits, see Code constraints) |
| `prepare.py` (frozen) | `data/`, `src/core/` (frozen, see Code constraints) |
| `val_bpb` (single metric) | 4-quadrant task quality + 5 gap-filling metrics |
| 5-min budget | per-experiment, no fixed budget |
| auto keep/discard | user reviews; agent never discards results |
| GPU loop | CPU loop |

One **cycle** = one hypothesis (e.g., `w_kegg=0.6` vs `0.7`), or one ablation, or one gap-filling ratio at one seed.

---

## Task quality: 2×2 framework

Two orthogonal axes. Every task quality test belongs in exactly one quadrant.

|  | **Feasibility** (yes/no) | **Magnitude** (in-range?) |
|---|---|---|
| **Universal** | EGC, free metabolite production, anaerobic OXPHOS block | ATP yield ≤ 38/glucose, mass/charge balance |
| **Species** | Tasks the organism cannot do (e.g., E. coli ≠ cellulose) | Yields within known organism range (e.g., E. coli lysine ≤ 0.3 g/g) |

A model passes task quality only when:

- All universal feasibility tests pass
- All universal magnitude tests stay in bounds
- All species-specific negative tasks correctly fail
- All species-specific magnitudes stay in known ranges
- All positive tasks (must-succeed) succeed

Universal tests (top row) are static and live in `tests/universal/`.
Species tests (bottom row) are generated dynamically by the agent based on organism metadata, and live in `tests/species/<organism>/`.

**This is an evaluation tool, not a strain-design tool.** Magnitude here means "stays in a realistic range," not "maximize." Don't confuse this with CNApy or OptKnock.

---

## Scoring (minimal)

```
score = w_kegg * kegg_score + w_bigg * bigg_score   # w_kegg + w_bigg = 1
```

- `bigg_score`: 1 if reaction in BiGG universal, else 0
- `kegg_score`: cofactor-aware match in [0, 1]
  - Ignored: H⁺, OH⁻, and stereoisomers within the same KEGG compound family
  - Structural isomers are treated as different
- Default weights: `w_kegg=0.6`, `w_bigg=0.4`. Tune via experiments.

---

## Gap-filling protocol

- **Targets**: reactions with non-empty GPR
- **Selection**: random sampling
- **Ratios**: 5%, 10%, 15% (independent — re-sample from original each time)
- **Repeats**: 5 seeds per ratio (42, 43, 44, 45, 46)
- **Filler**: `cobra.flux_analysis.gapfilling.gapfill()`
- **Universal DB**: `data/bigg_universal_model_fixed.json`

Five metrics per run:

1. **Recovery recall** — fraction of removed reactions restored
2. **Functional preservation** — Δgrowth, essential-gene Jaccard
3. **Over-addition** — new reactions added that weren't original (lower is better)
4. **Quality delta** — ΔMEMOTE, mean score of added reactions
5. **Failure mode** — count and reason for infeasible gap-fills

---

## Directory layout

```
model_evaluator/
├── CLAUDE.md            # tool docs (read-only)
├── AGENTS.md            # this file
├── run.sh               # entry point
├── data/                # ⚠️ read-only inputs (see Operating rules)
│   ├── iML1515.xml      # primary dev model (LFS)
│   ├── e_coli_core.xml  # small smoke-test model
│   ├── bigg_universal_model_fixed.json   # gap-fill universal DB (LFS)
│   ├── universal_essential_tasks.csv
│   └── validation/      # held-out (Phase 2 only)
│       └── iMM904.xml
├── src/                 # source code (changes need user approval)
├── scripts/
│   └── download_external_data.sh  # run once after clone
├── configs/             # scoring weights, thresholds
├── tests/
│   ├── universal/{feasibility,magnitude}/
│   ├── species/<organism>/{feasibility,magnitude}/
│   └── positive/
└── experiments/         # all experiment outputs
```

External data (MetaNetX, BiGG caches) are NOT in git. Run `bash scripts/download_external_data.sh` once after cloning.

---

## Operating rules

### Always do (no confirmation)

- Read anything under `data/`
- Run FBA, FVA, single-deletion, pFBA
- Create/edit/delete files under `experiments/` and `scripts/`
- Run task quality suite or gap-filling experiments
- Write scratch files to `/tmp` or `experiments/scratch/`

### Ask first

- Modify any file under `src/`
- Modify `configs/`, `tests/`, `AGENTS.md`, `CLAUDE.md`
- Create new git branches
- Install or upgrade any package

### Never do

- Modify or delete `data/iML1515.xml`, `data/bigg_universal_model_fixed.json`, or `data/validation/*`
- Push to `main` (push only to `auto-research`)
- `git rebase`, `git push --force` (user does this)
- Call paid external APIs (this branch has no LLM sources — stop immediately if any LLM call is triggered)
- Discard experiment results

---

## Experiment storage

```
experiments/<type>/
├── design.md                  # type-wide hypothesis & method (write before first experiment)
└── <YYYYMMDD_HHMM>_<slug>/
    ├── config.json            # all input parameters (seed, ratios, weights, ...)
    ├── metrics.json           # all measured numbers
    └── notes.md               # observations, surprises, next steps
```

`<type>` ∈ `{baseline, scoring, gapfilling, task_quality, boundary, audit}`

Rules:

- Write `design.md` before the first experiment of any new type. All later experiments of that type follow it. Update `design.md` with rationale when methodology changes.
- Never overwrite existing experiment directories. Use `_a`, `_b` suffixes for ties.
- Commit results under `experiments/` for reproducibility. Files >5 MB go to `.gitignore` with the location noted in `notes.md`.

---

## Phase plan

### Phase 1 — iML1515 only

- Baseline: growth, essentiality, MEMOTE
- KEGG/BiGG scoring distribution
- Build and run universal feasibility + magnitude tests
- Gap-filling: 5/10/15% × 5 seeds
- Build E. coli K-12 species feasibility + magnitude tests

### Phase 2 — iMM904 added (after Phase 1 complete)

- iMM904 baseline
- Apply Phase 1's scoring weights to iMM904 unchanged → check generalization
- If weights hold up, accept; if not, retune
- Build S. cerevisiae species tests

**Do not touch iMM904 during Phase 1.** Tuning on it destroys the generalization check.

---

## Natural-language request → action

| User says | Agent does |
|---|---|
| "Evaluate task quality on iML1515" | Run all 4 quadrants → write `metrics.json` |
| "Remove 10% of gene-associated reactions and gap-fill" | Random, 5 seeds, 10% removed → 5 metrics |
| "Try `w_kegg=0.7` and compare to baseline" | New config (ask first) → run → diff report |
| "Find tasks this organism can't do" | Species feasibility — read organism metadata, query KEGG/BiGG, add tests |
| "Is this model overproducing ATP?" | Run `tests/universal/magnitude/atp_yield_ceiling` |

---

## Working with bikit / autoresearch sessions

- Sessions start at the project root (where this file lives). All paths are relative to it.
- For a new research goal, write `experiments/<type>/design.md` first.
- Multi-step experiments go into `scripts/` as batch scripts, not interactive runs. Better for reproducibility and resumption.
- Before asking the user a question, search prior `experiments/<type>/*/notes.md` — the answer may already be there.
- After ~5 experiments in one session, summarize results to the user and ask whether to continue.
- Auto-create `experiments/`, `tests/`, `configs/`, `scripts/` on first use. The user does not pre-create them.

---

## Git conventions

- All work commits to `auto-research`. Only the user merges to `main`.
- Commit message style: `[scoring] add KEGG weight grid search` (lowercase tag, English, concise).
- One commit = one logical change. Don't mix code, results, and docs in one commit.
- Commit `experiments/` outputs for reproducibility. Files >5 MB → `.gitignore` (note location in `notes.md`).
- LFS-tracked patterns are defined in `.gitattributes`. New large data files: ask before adding.

---

## Known constraints

- LLM sources (Gemini, Perplexity) are disabled in this branch. If any code path tries to call them, stop immediately.
- KEGG cofactor scope is currently {H⁺, OH⁻, stereoisomers}. Don't expand without user approval.
- COBRApy `gapfill` cannot restore reactions absent from the universal DB. Such failures are normal — log them with reason.
- Python 3.9 environment. Some tools (ruff) suggest 3.10+ syntax; do not accept those auto-fixes.
- Pre-commit hooks should pass. Legacy type errors (~60) inherited at branch start may be bypassed with `--no-verify` for *existing* code only. New code must pass all hooks.
- External datasets (MetaNetX, BiGG raw) are not in git. Run `scripts/download_external_data.sh` first.

---

## Tie-breakers (when in doubt)

1. **Reproducibility > speed** — slower but reproducible wins
2. **Explicit > inferred** — when metadata is missing, ask, don't guess
3. **Simple > rich** — minimal-branch principle; new sources/metrics need user approval
4. **Local data > external calls** — prefer files already in `data/`
5. **Documented > undocumented** — every result needs `design.md` / `notes.md` next to it
6. **Existing code > new code** — see Code constraints below

---

## Code constraints (CRITICAL)

This section overrides anything else when in conflict.

### Use only what's in this repo

The agent may use:

- Existing code in `src/`, `data/`, `scripts/` of this repo ([github.com/jyryu3161/model_evaluator](https://github.com/jyryu3161/model_evaluator))
- Dependencies already declared in `pyproject.toml` / `requirements.txt`
- Python standard library

That's it.

### Never (without explicit approval)

- Install new dependencies (`pip install`, etc.)
- Implement an algorithm that doesn't exist in this repo (a new scoring rule, a new gap-fill strategy, etc.)
- Reimplement something `src/` already does
- Put algorithm logic in `experiments/` or `scripts/` — those are wrappers only
- Cite "industry standard" as a reason to introduce something new

### When something is missing

If existing code can't do the task:

1. Stop. Don't write new logic.
2. In the active experiment's `notes.md`, record: what was attempted, what's missing, where in `src/` you'd extend it.
3. Report to the user. Wait for explicit approval.
4. Only after approval, add code to `src/` (not to `experiments/`).

### Scripts are thin wrappers

Anything under `experiments/` or `scripts/` should:

- Call `src/` functions
- Marshal inputs and outputs (JSON in, `metrics.json` out)
- Contain no algorithm logic

### Self-check before each commit

- [ ] Did I call into `src/` rather than reimplement?
- [ ] Is algorithm logic confined to `src/`?
- [ ] Did I avoid adding new dependencies?
- [ ] If `pyproject.toml` / `requirements.txt` changed, did the user approve?

If any answer is "no," stop and report.

---

*Last updated: 2026-04-27 · Maintained on `auto-research` branch.*
