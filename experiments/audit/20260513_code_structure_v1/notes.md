# notes.md — code_structure_v1

> First-pass audit. Per `design.md`, all behavioral claims cite ≤5 lines of
> source. "Not verified from code" used where a behavior cannot be confirmed
> from `src/` alone.

---

## A. Entry point

### Run modes

`run.sh` runs the GUI only:

```bash
# run.sh
cd "$(dirname "$0")"
source .venv/bin/activate
python -m src.app "$@"
```

The CLI exists separately and is not exposed by `run.sh`. It must be invoked
explicitly with `python -m src.cli <args>`.

### GUI entry

`src/app.py:17-31`:

```python
def main() -> None:
    setup_logging()
    config = Config.load()
    app = QApplication(sys.argv)
    ...
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())
```

Launches PySide6 `QApplication` and constructs `MainWindow(config)` from
`src/gui/main_window.py`. All evaluation work happens inside the GUI via
worker threads (`src/gui/workers.py` per CLAUDE.md §Tech Stack — not opened
in this audit).

### CLI entry

`src/cli.py:551` defines `def main(argv: list[str] | None = None)`; the
file is 667 lines and wraps the same evaluation pipeline for headless
batch use. Bottom of file:

```python
asyncio.run(
    async_main(config=config, reactions=reactions,
               output_path=output_path, fmt=fmt,
               model_id=model_data.id, organism=model_data.organism)
)
```

CLI calls into the same `EvidenceEngine` as the GUI (verified via shared
imports of `src/core/models.py` types).

| Mode | Invoked by | Entry function | Notes |
|---|---|---|---|
| GUI | `run.sh` → `python -m src.app` | `src/app.py:17 main()` | Default user-facing path |
| CLI | direct: `python -m src.cli <model.xml>` | `src/cli.py:551 main()` | Used for batch scripts |

---

## B. 6 evidence sources — location and on/off

Orchestration in `src/evidence/engine.py:48-127` (`EvidenceEngine.initialize()`).

| Source | Client file | Class | Initialized at | On/off mechanism |
|---|---|---|---|---|
| **KEGG** | `src/api/kegg_client.py` | `KEGGClient` | engine.py:55-58 | **None — unconditional.** No `enable_kegg` flag exists. |
| **BiGG** | `src/api/bigg_lookup.py` | `BiGGLookup` | engine.py:62-74 | `config.enable_bigg` (config.py:44) |
| **UniProt** | `src/api/uniprot_client.py` | `UniProtClient` | engine.py:77-87 | `config.enable_uniprot` (config.py:45) |
| **PubMed** | `src/api/pubmed_client.py` | `PubMedClient` | engine.py:90-101 | `config.enable_pubmed` (config.py:46) |
| **Gemini** | `src/api/gemini_client.py` | `GeminiClient` | engine.py:104-114 | `config.enable_gemini` AND `gemini_api_key` (engine.py:104) |
| **Perplexity** | `src/api/perplexity_client.py` | `PerplexityClient` | engine.py:117-127 | `config.enable_perplexity` AND `perplexity_api_key` (engine.py:117) |

Per-reaction calls happen in `evaluate_reaction()` and `_run_evidence_pipeline()`
(engine.py:167-410), each guarded by `if self._kegg / self._bigg / self._uniprot / ...`
checks. So a disabled source results in `self._<source> is None`, and the
corresponding `if` block is skipped at evaluation time — no exceptions.

KEGG asymmetry — sample (engine.py:174):

```python
assert self._kegg is not None, "Engine not initialized"
```

KEGG is treated as required. Same in `evidence_types.py:get_active_sources()`:

```python
# evidence_types.py:137-139
if source == EvidenceSource.KEGG:
    active.append(source)  # KEGG is always active
    continue
```

### Note on `bigg_client.py` vs `bigg_lookup.py`

Both files exist in `src/api/`. `engine.py` imports only `BiGGLookup` from
`bigg_lookup.py` (engine.py:64). `bigg_client.py` is not referenced by the
engine — **not verified from code** whether it is dead code or used elsewhere
(GUI, tests). No deeper trace done in this audit.

### Source registry

`src/evidence/evidence_types.py:59-120` defines `SOURCE_REGISTRY: dict[EvidenceSource, SourceConfig]`
with one entry per source. Each entry maps:

- `enable_key` — config attribute name controlling on/off
- `weight_key` — config attribute name for the weight
- `requires_api_key` — whether an API key is needed

Helper `evidence_types.py:133-142 get_active_sources(config)` returns the
active subset, applying the KEGG-always-on rule.

---

## C. Scoring logic

### Strength enum (numeric)

`src/core/models.py:9-13`:

```python
class EvidenceStrength(Enum):
    STRONG = 1.0
    MODERATE = 0.6
    WEAK = 0.3
    ABSENT = 0.0
```

### Strength judgement — *per-source, distributed, hardcoded*

The `ConfidenceScorer` does NOT classify strength; each client decides on its
own.

**KEGG** (`src/api/kegg_client.py:240-258`): based on `avg_match` =
mean of substrate and product match ratios.

```python
if avg_match < 0.2:
    return None
if avg_match >= 0.8:    strength = EvidenceStrength.STRONG
elif avg_match >= 0.5:  strength = EvidenceStrength.MODERATE
else:                   strength = EvidenceStrength.WEAK
```

Thresholds 0.2 / 0.5 / 0.8 are **hardcoded** in `kegg_client.py`. Not in
`Config`. Not in `constants.py`. Magic numbers in source.

**BiGG** (`src/api/bigg_lookup.py:340-365`): based on number of BiGG
models containing the reaction.

```python
if model_count > 5:    strength = EvidenceStrength.STRONG
elif model_count >= 2: strength = EvidenceStrength.MODERATE
elif model_count == 1: strength = EvidenceStrength.WEAK
else:                  strength = EvidenceStrength.WEAK
```

Thresholds 5 / 2 / 1 are **hardcoded** in `bigg_lookup.py`.

**Other sources**: not opened in v1. Per-source strength rules in `uniprot_client.py`,
`pubmed_client.py`, `gemini_client.py`, `perplexity_client.py` — same pattern
expected (hardcoded inside each client). Not verified in v1.

### Weighted average

`src/evidence/scoring.py:24-65` — `ConfidenceScorer.score(evidence)`:

1. Per-source raw score = max strength value among that source's items
   (`scoring.py:67-77 _compute_source_scores`).
2. Active sources = those with at least one item (`scoring.py:36-44`).
3. Active-source weights are **re-normalized** to sum to 1
   (`scoring.py:51-61`). Disabled sources are excluded automatically.
4. Final score is the weighted sum, clamped to `[0, 1]` (`scoring.py:64`).

This means: turning off UniProt/PubMed/Gemini/Perplexity does *not* require
weight rebalancing — the scorer redistributes automatically.

### Weights — externalized

`src/utils/config.py:36-41`:

```python
weight_kegg: float = 0.30
weight_bigg: float = 0.15
weight_uniprot: float = 0.15
weight_pubmed: float = 0.15
weight_gemini: float = 0.125
weight_perplexity: float = 0.125
```

Loaded from `CONFIG_FILE_PATH` JSON via `Config.load()` (config.py:71-100).
Engine consumes `config.weights` (`config.py:119-128 @property weights`)
which materializes the dict the scorer expects.

| Item | Externalized? | Where to change |
|---|---|---|
| Source weights | ✅ Yes | `~/.config/.../config.json` or edit defaults in `config.py:36-41` |
| Source on/off (5 of 6) | ✅ Yes | Same JSON, `enable_<source>` keys |
| KEGG on/off | ❌ No | Hardcoded; needs code edit |
| KEGG strength thresholds (0.2/0.5/0.8) | ❌ No | `src/api/kegg_client.py:246-256` |
| BiGG strength thresholds (5/2/1) | ❌ No | `src/api/bigg_lookup.py:354-363` |
| Other sources' thresholds | Not verified | Inside each `*_client.py` |

---

## D. Gap-filling

### `cobra.flux_analysis.gapfilling.gapfill()` call site

`src/gapfill/engine.py:408-413`:

```python
result = cobra.flux_analysis.gapfilling.gapfill(
    test_model,
    universal,
    lower_bound=lower_bound,
    penalties=penalties,
)
```

Wrapped by `_gapfill_for_task(model, universal, task, penalties, lower_bound)`
(engine.py:348-418). Called from `_run_gapfill()` (engine.py:278-346), which
iterates over **failed metabolic tasks** and gap-fills each, with a fallback
retry at `lower_bound=0.01` if the primary call raises `RuntimeError`
(engine.py:319-323).

### Universal model loading

`src/core/universal_loader.py:23-72` — `UniversalLoader`:

```python
def load(self, filepath: str | Path) -> cobra.Model:
    ...
    if suffix == ".json":  return self.load_json(filepath)
    if suffix in (".xml", ".sbml"):  return self.load_sbml(filepath)
```

Format auto-detected by extension. JSON path uses `cobra.io.load_json_model()`,
SBML path uses `cobra.io.read_sbml_model()`.

Default file from `Config.default_universal_model = "data/bigg_universal_model_fixed.json"`
(`config.py:51`). Not verified from code where this string is dereferenced
to a path (the CLI/GUI controllers may resolve it relative to repo root or
absolute — not traced in v1).

`UniversalLoader.extract_candidates(universal, user_model)` (universal_loader.py:74-114)
returns reactions in the universal model that are NOT in the user model
(after lowercase and `R_` prefix normalization), excluding utility reactions
(EX_, DM_, SK_ — not verified in v1).

### GPR-based reaction filtering — **not present in current gap-fill**

The current gap-fill engine is *task-driven*: it runs metabolic tasks, finds
failed ones, and gap-fills against the universal model to make them feasible.
There is no code that:

- Selects user-model reactions where `gene_reaction_rule` is non-empty,
- Removes a random fraction (5/10/15%),
- Calls gap-fill on the depleted model,
- Measures recovery.

Confirmed by repo-wide grep:

- `gene_reaction_rule` appears as a data field (`models.py:94`, `cobra_utils.py:13,35`,
  `cli.py:185` — output formatting only).
- `gpr_assigner.py:112` uses GPR to **assign** rules to gap-filled reactions,
  not to **select** removal targets.
- No `random.sample` / `np.random` over reaction lists in `src/gapfill/`.

→ The protocol described in `AGENTS.md §Gap-filling protocol` ("Targets:
reactions with non-empty GPR; Selection: random sampling; Ratios: 5%, 10%,
15%; Repeats: 5 seeds 42-46") is **planned, not implemented**. **Not
verified from code** because it does not exist in `src/`.

### Other gap-fill machinery (location only)

| Component | File | Purpose |
|---|---|---|
| Pipeline orchestrator | `src/gapfill/engine.py` | 5-phase pipeline: testing_before → filtering → gap_filling → assigning_gpr → testing_after |
| Organism filter | `src/gapfill/organism_filter.py` | KEGG-based species filter for candidate reactions |
| GPR assigner | `src/gapfill/gpr_assigner.py` | Assigns gene-reaction rules to filled reactions |
| Penalty calculator | `src/gapfill/penalty_calculator.py` | Builds the `penalties` dict passed to `cobra.flux_analysis.gapfilling.gapfill()` |
| Universal loader | `src/core/universal_loader.py` | Loads `bigg_universal_model_fixed.json` and extracts candidates |
| Task runner | `src/core/task_parser.py` (`TaskRunner`) | Runs metabolic tasks for testing_before/testing_after |

---

## Open questions (not verified from code)

1. **`bigg_client.py` purpose** — referenced nowhere by `engine.py`. Is it
   dead code, used by tests, or used by GUI directly? Needs grep across
   `tests/` and `gui/` — out of scope for v1.
2. **Strength thresholds in UniProt/PubMed/Gemini/Perplexity clients** —
   assumed hardcoded based on KEGG/BiGG pattern, not actually opened.
3. **Universal model path resolution** — `config.default_universal_model`
   is a relative path string; how it resolves to an absolute path
   (relative to repo root? CWD? GUI base dir?) was not traced.
4. **Utility-reaction prefixes** — `_UTILITY_PREFIXES` in `universal_loader.py`
   not opened; specific prefixes (EX_, DM_, SK_, …) inferred but not verified.
5. **Worker thread isolation** — CLAUDE.md §Async claims asyncio runs in
   worker threads off the GUI thread. Worker code in `src/gui/workers.py`
   not opened in v1.
6. **GPR-based removal protocol** — `AGENTS.md §Gap-filling protocol`
   describes 5/10/15% × 5 seeds removal, but no such code exists in `src/`.
   This is an *implementation gap*, not a comprehension gap.
7. **Where the actual `data/bigg_universal_model_fixed.json` is read at
   runtime** — the load happens through `UniversalLoader.load_json`, but
   *who* calls `UniversalLoader.load(...)` and from where (GUI controller?
   CLI?) is not traced.

---

## Time spent

Approx. 35-40 minutes — within the 60-min cap from `design.md`. Each
section:

- A: 5 min (small files, direct read)
- B: 12 min (engine.py is 467 lines, scanned key sections)
- C: 10 min (scoring.py + 2 client snippets)
- D: 10 min (gapfill engine, universal_loader, repo grep)
