# AGENTS.md

> Research operations guide for AI coding agents working in this repository.
> For tool usage (install, run, I/O), see `CLAUDE.md`. This document adds the
> *research workflow* on top of the tool itself.
>
> Branch: `auto-research` · Base: `main` (6-source system)
> This branch is a minimal redesign for autonomous task quality and gap-filling research.

---

## Layered framework: bkit + AGENTS.md

This project uses a **two-layer harness**:

- **bkit** (process harness) — Manages PDCA workflow, state machine, quality gates, and feature-development tracking under `docs/01-plan/`, `docs/02-design/`, `docs/03-analysis/`, with runtime state in `.bkit/state/`. Invoked via the `/pdca` skill family. Decides *how* work progresses.
- **AGENTS.md** (domain harness, this file) — The single source of truth for GEM-evaluation policy: the §Goal (reference-free quality), the §Task quality 2×2 framework, the §Gap-filling protocol, §Code constraints, and what the agent may or may not do. Decides *what is correct*.

The layers do not overlap. bkit owns workflow mechanics; AGENTS.md owns domain truth. **Conflict precedence: domain policy > process.** If a bkit-suggested step contradicts a domain rule here (e.g., a `/pdca` Do step that would violate §Code constraints), the domain rule wins.

Practical mapping:

- Research experiments (hypothesis tests, ablations, gap-fill runs) → `experiments/<type>/<run>/notes.md` (per §Experiment storage vs feature documentation)
- Feature development (e.g., new `src/` module, refactor) → bkit `/pdca` → `docs/01-plan/` → `docs/02-design/` → implementation → `docs/03-analysis/`
- Quick scripts and one-off analyses → `experiments/scratch/` (no PDCA needed)

---

## Read order

Before any work, read in this order:

1. `CLAUDE.md` — what the tool does (install, run, I/O, code structure)
2. `AGENTS.md` (this file) — domain policy for the research workflow
3. `bkit` `/pdca status` — current PDCA state for any in-flight feature work (skip if no PDCA cycle active)

Skipping step 1 leads to attempting auto-research without understanding the underlying tool. Don't do it.

---

## Goal

This branch focuses on two capabilities for autonomous model quality
enhancement of GEMs:

1. **Task quality evaluation** — does the model perform what it should,
and refuse what it shouldn't?
2. **Gap-filling quality** — when reactions are needed, are they
selected from the universal DB in a principled way?

### Final research target

The end goal is *reference-free* model quality enhancement: given a
species or target, an AI agent autonomously selects reactions from a
universal DB to improve the model — without comparing against a
ground-truth reference model.

The current GPR-removal benchmark (remove n% of reactions, attempt
recovery) is a *training/validation environment* for measuring
gap-filling capability. Recovery recall against the original reactions
is a useful benchmark metric but NOT the production metric.

### Implication for evaluation

Production metric: model functional quality (growth recovery, Q1/Q2
universal task pass rate, Q3/Q4 species task pass rate, reaction
overhead).

Benchmark metric: recovery recall, used only when ground-truth exists.

Approaches that "cheat" using ground-truth information (e.g.,
selectively correcting bounds only on known-removed reactions) are
not acceptable — they don't transfer to the reference-free setting.

---

## Domain harness principles

This file is the *domain harness* — the deliberate set of policies that keep AI coding agents focused on GEM-evaluation research that holds up scientifically. (Process harness — PDCA workflow, state machine, automation levels, quality gates — is bkit's job; see §Layered framework.)

### Why a domain harness is needed

Auto-research lets the agent run many experiments with limited supervision. Without explicit domain rules, the agent may:

- Implement algorithms instead of using existing `src/` code (see §Code constraints)
- Cite "industry standard" to bypass project rules
- Discard inconvenient results to make metrics look better
- Drift from the original research question over time
- Answer code-dependent questions from filenames or function signatures alone

### Domain harness components in this repo

| Component | Purpose | Location |
|---|---|---|
| `AGENTS.md` (this file) | Domain behavioral contract | repo root |
| `experiments/<type>/design.md` | Per-type hypothesis lock-in | each type dir |
| `experiments/<type>/<exp>/notes.md` | Per-experiment observation log | each experiment dir |
| §Code constraints (this file) | Enforce `src/`-only algorithm logic | this file |
| §Operating rules (this file) | Domain Always / Ask / Never | this file |
| §Tie-breakers (this file) | Conflict resolution priorities | this file |

For PDCA progression, state tracking, automation levels (L0–L4), and quality gates (M1–M10), see bkit — `/pdca status`, `.bkit/state/`, and the bkit `bkit-rules` skill.

### Read code before answering

When asked about tool behavior, scoring logic, gap-filling, version tracking, or any code-dependent question, the agent MUST inspect the actual source code (in `src/`) before answering. Do not guess based on filenames, function signatures, or this document alone. Quote the relevant code (≤15 lines) when making claims about behavior.

If a behavior cannot be verified from the code, say "not verified from code" — do not infer.

### When the harness is incomplete

If the agent encounters a *domain* situation this document does not cover:

1. Stop. Do not improvise.
2. Record the gap in the active experiment's `notes.md`.
3. Report to the user with a proposed harness addition.
4. Wait for explicit decision before proceeding.

(Process gaps — missing workflow steps, unclear PDCA phase transitions, automation-level questions — are bkit's domain. Raise those through bkit channels, not here.)

The harness evolves over time. Gaps are not failures — unrecorded gaps are.

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
| **Universal** | **Q1** — EGC, free metabolite production, anaerobic OXPHOS block | **Q2** — ATP yield ≤ 38/glucose, mass/charge balance |
| **Species** | **Q3** — Tasks the organism cannot do (e.g., E. coli ≠ cellulose) | **Q4** — Yields within known organism range (e.g., E. coli lysine ≤ 0.3 g/g) |

Q1/Q2/Q3/Q4 names match the production-metric labels referenced in §Goal §Implication.

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

This is the **benchmark / training-validation protocol** for measuring
gap-filling capability (see §Goal §Final research target). It is *not*
the production protocol. `recovery_recall` is a benchmark-only metric,
valid only when the removed reactions are known. Production quality is
measured via §Task quality 2×2 (Q1–Q4), growth recovery, and reaction
overhead.

**Selection logic must be reference-free.** Approaches that exploit
ground-truth information (e.g., narrowing the candidate pool to the
known-removed IDs, correcting bounds only on those IDs, scoring against
the original reaction set) are not acceptable — they don't transfer to
the production setting.

- **Targets**: reactions with non-empty GPR
- **Selection**: random sampling
- **Ratios**: 5%, 10%, 15% (independent — re-sample from original each time)
- **Repeats**: 5 seeds per ratio (42, 43, 44, 45, 46)
- **Filler**: `cobra.flux_analysis.gapfilling.gapfill()`
- **Universal DB**: `data/bigg_universal_model_fixed.json`

Five metrics per run (recall is benchmark-only; the other four are
production-relevant):

1. **Recovery recall** *(benchmark only)* — fraction of removed reactions restored
2. **Functional preservation** — Δgrowth, essential-gene Jaccard
3. **Over-addition** — new reactions added that weren't original (lower is better)
4. **Quality delta** — ΔMEMOTE, mean score of added reactions
5. **Failure mode** — count and reason for infeasible gap-fills

---

## Directory layout

```
model_evaluator/
├── CLAUDE.md            # tool docs (read-only)
├── AGENTS.md            # this file — domain policy
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
├── experiments/         # research runs (domain layer — owned by AGENTS.md)
│   └── <type>/<run>/{config.json,metrics.json,notes.md}
├── docs/                # feature development tracking (process layer — owned by bkit)
│   ├── 01-plan/         # PDCA Plan documents (created by /pdca plan)
│   ├── 02-design/       # PDCA Design documents (created by /pdca design)
│   └── 03-analysis/     # PDCA Gap-analysis reports (created by /pdca analyze)
└── .bkit/
    └── state/           # bkit state machine (memory.json, pdca-status.json) — do not hand-edit
```

External data (MetaNetX, BiGG caches) are NOT in git. Run `bash scripts/download_external_data.sh` once after cloning.

**Layer ownership:**

- `experiments/` — research runs. The agent freely creates, edits, and commits here (see §Operating rules). Results of hypothesis tests, ablations, gap-fill runs, and audits all live here.
- `docs/01-plan/`, `docs/02-design/`, `docs/03-analysis/` — bkit's. Created and updated by `/pdca` skills during feature development (e.g., introducing a new `src/` module). Do not hand-edit; use the `/pdca plan|design|analyze` commands.
- `.bkit/state/` — bkit runtime state. **Never edit by hand.** Inspect via `/pdca status` if needed.

---

## Operating rules (domain)

These are the *domain* rules. For automation level / trust / guardrail mechanics, see bkit's L0–L4 system (`bkit:control`, `bkit:bkit-rules`). The domain rules below are absolute regardless of bkit automation level.

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
- Edit anything under `docs/01-plan/`, `docs/02-design/`, `docs/03-analysis/` by hand (prefer `/pdca` skills)

### Never do

- Modify or delete `data/iML1515.xml`, `data/bigg_universal_model_fixed.json`, or `data/validation/*`
- Push to `main` (push only to `auto-research`)
- `git rebase`, `git push --force` (user does this)
- Call paid external APIs (this branch has no LLM sources — stop immediately if any LLM call is triggered)
- Discard experiment results
- Edit `.bkit/state/` files by hand

---

## Experiment storage vs feature documentation

This project keeps **two parallel records**, each for a different purpose. They are not interchangeable.

### Research experiments → `experiments/`

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

### Feature development → `docs/01-plan/`, `docs/02-design/`, `docs/03-analysis/`

Managed by bkit `/pdca`. Used when adding or modifying functionality in `src/` (e.g., introducing a new scoring rule, refactoring `recovery_runner.py`). Flow: `/pdca plan <feature>` → `/pdca design <feature>` → implementation → `/pdca analyze <feature>`.

### Why both exist (do not collapse them)

| | `experiments/<type>/<run>/notes.md` | `docs/01-plan/<feature>.md` |
|---|---|---|
| Granularity | One hypothesis test or audit | One `src/` feature |
| Lifecycle | Permanent record of what happened | Lives until feature ships, then summarized in `docs/03-analysis/` |
| Owned by | AGENTS.md domain policy | bkit process workflow |
| Reproducible artifact | yes (`config.json` + `metrics.json` + notes) | no (a planning doc) |

Mixing them loses both signals. A gap-fill experiment result is not a feature plan; a refactor design is not a research observation. **Don't put feature plans under `experiments/` and don't put hypothesis test results under `docs/`.**

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

For *feature-development* requests ("add a new scoring rule", "refactor recovery_runner"), the trigger is bkit `/pdca` (e.g., `/pdca plan kegg-substructure-scoring`) — see the bkit skill list. The table above covers *research-run* requests only.

---

## Session conventions

(See §Layered framework for how bkit and AGENTS.md divide responsibilities.)

- Sessions start at the project root (where this file lives). All paths are relative to it.
- For a new research goal, write `experiments/<type>/design.md` first.
- For a new `src/` feature, run `/pdca plan <feature>` first (bkit process layer).
- Multi-step experiments go into `scripts/` as batch scripts, not interactive runs. Better for reproducibility and resumption.
- Before asking the user a question, search prior `experiments/<type>/*/notes.md` — the answer may already be there.
- After ~5 experiments in one session, summarize results to the user and ask whether to continue.
- Auto-create `experiments/`, `tests/`, `configs/`, `scripts/` on first use. The user does not pre-create them. `docs/01-plan/` and siblings are created by bkit when needed.

---

## Git conventions

- All work commits to `auto-research`. Only the user merges to `main`.
- Commit message style: `[scoring] add KEGG weight grid search` (lowercase tag, English, concise).
- One commit = one logical change. Don't mix code, results, and docs in one commit.
- Commit `experiments/` outputs for reproducibility. Files >5 MB → `.gitignore` (note location in `notes.md`).
- LFS-tracked patterns are defined in `.gitattributes`. New large data files: ask before adding.

---

## Known constraints

- Of the original 6 evidence sources, only **KEGG** and **BiGG** are active in this branch. UniProt, PubMed, Gemini, and Perplexity are all disabled. If any code path tries to call them, stop immediately.
- KEGG cofactor scope is currently {H⁺, OH⁻, stereoisomers}. Don't expand without user approval.
- COBRApy `gapfill` cannot restore reactions absent from the universal DB. Such failures are normal — log them with reason.
- Python 3.9 environment. Some tools (ruff) suggest 3.10+ syntax; do not accept those auto-fixes.
- Pre-commit mypy hook: staged files only. For non-`src/` `.py` files (e.g., scripts under `experiments/audit/`) the hook does not trigger at all. For `src/` `.py` modifications, mypy still follows transitive imports and may surface the ~72 legacy errors in dependent files. `--no-verify` acceptable for existing-code-only commits with reason documented in body. (Future: dedicated cleanup track for the 72 legacy errors.)
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
