# GUI Refactoring Design Document

> **Summary**: 아키텍처 위반, DRY 위반, 캡슐화, 보안 이슈를 5단계로 수정하는 상세 설계
>
> **Project**: GEM Evaluator
> **Author**: Claude Code
> **Date**: 2026-02-27
> **Status**: Draft
> **Planning Doc**: [gui-refactoring.plan.md](../../01-plan/features/gui-refactoring.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. evidence 모듈의 GUI 독립성 확보 (CLI/headless 사용 가능)
2. DRY 원칙 적용으로 중복 코드 제거 (약 300줄 절감)
3. MainWindow 1,694줄 → Controller 분해로 유지보수성 향상
4. API 키 보안 강화

### 1.2 Design Principles

- **Single Responsibility**: 각 모듈/클래스가 하나의 역할만 수행
- **Dependency Inversion**: 상위 레이어만 하위 레이어를 참조 (gui → evidence → core)
- **Open/Closed**: 기존 public API는 유지하면서 내부 구조만 변경

---

## 2. Architecture

### 2.1 현재 의존성 (문제)

```
gui/theme.py
    ↑ ❌ (레이어 역전)
evidence/evidence_types.py → core/models.py
```

### 2.2 수정 후 의존성

```
gui/evidence_colors.py → evidence/evidence_types.py → core/models.py
                       → gui/theme.py
```

### 2.3 Layer Rules

| From | Can Import | Cannot Import |
|------|-----------|---------------|
| gui/ | evidence/, core/, utils/, cache/ | - |
| evidence/ | core/, utils/ | gui/, cache/ (직접 X) |
| core/ | utils/ | gui/, evidence/, api/ |
| api/ | core/, cache/, utils/ | gui/, evidence/ |

---

## 3. Phase 1: 아키텍처 위반 수정 (FR-01)

### 3.1 변경: `src/evidence/evidence_types.py`

**Before**: `from src.gui.theme import THEME` 후 `THEME.strength_strong` 등 참조

**After**: hex 리터럴을 직접 사용하는 기본값 + 선택적 색상 주입

```python
# evidence_types.py — GUI import 완전 제거

# 기본 색상 (hex 리터럴, GUI 없이도 동작)
_DEFAULT_STRENGTH_COLORS = {
    EvidenceStrength.STRONG: "#2ecc71",
    EvidenceStrength.MODERATE: "#f1c40f",
    EvidenceStrength.WEAK: "#e67e22",
    EvidenceStrength.ABSENT: "#e74c3c",
}

_DEFAULT_SOURCE_COLORS = {
    EvidenceSource.KEGG: "#3498db",
    EvidenceSource.BIGG: "#2ecc71",
    EvidenceSource.UNIPROT: "#9b59b6",
    EvidenceSource.PUBMED: "#e74c3c",
    EvidenceSource.METACYC: "#f39c12",
    EvidenceSource.GEMINI: "#1abc9c",
    EvidenceSource.PERPLEXITY: "#34495e",
}

STRENGTH_COLORS = dict(_DEFAULT_STRENGTH_COLORS)  # mutable copy

# SourceConfig.color 필드에 기본 hex 값 사용
# SOURCE_REGISTRY 에서 THEME.source_xxx → _DEFAULT_SOURCE_COLORS[source] 로 교체
```

### 3.2 신규: `src/gui/evidence_colors.py`

```python
"""Bridge: applies theme colors to evidence type constants at GUI startup."""
from __future__ import annotations

from src.evidence.evidence_types import STRENGTH_COLORS, SOURCE_REGISTRY
from src.gui.theme import THEME
from src.core.models import EvidenceStrength


def apply_theme_colors() -> None:
    """Override default evidence colors with current theme.

    Call once during GUI initialization (in app.py or MainWindow.__init__).
    """
    STRENGTH_COLORS[EvidenceStrength.STRONG] = THEME.strength_strong
    STRENGTH_COLORS[EvidenceStrength.MODERATE] = THEME.strength_moderate
    STRENGTH_COLORS[EvidenceStrength.WEAK] = THEME.strength_weak
    STRENGTH_COLORS[EvidenceStrength.ABSENT] = THEME.strength_absent

    # Update SOURCE_REGISTRY colors — SourceConfig is frozen,
    # so store overrides in a separate lookup
    # (or make color field non-frozen)
```

**호출 위치**: `src/app.py`에서 `apply_theme_colors()` 호출

### 3.3 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `src/evidence/evidence_types.py` | `from src.gui.theme import THEME` 제거, 기본 hex 값 사용 |
| `src/gui/evidence_colors.py` | 신규 생성 — 테마 색상 오버라이드 |
| `src/app.py` | `apply_theme_colors()` 호출 추가 |

---

## 4. Phase 2: 캡슐화 수정 (FR-02, FR-09)

### 4.1 변경: `src/evidence/engine.py` — public properties

```python
class EvidenceEngine:
    # 기존 private 속성 유지

    @property
    def cache_manager(self) -> CacheManager | None:
        """Expose cache manager for external use (e.g., gap-fill engine)."""
        return self._cache

    @property
    def mapping_data(self) -> MappingData | None:
        """Expose mapping data for external use."""
        return self._mapping_data
```

**cli.py 수정**:
```python
# Before
engine._cache  →  engine.cache_manager
engine._mapping_data  →  engine.mapping_data
```

### 4.2 변경: `src/gui/reaction_table.py` — public accessors

```python
class ReactionTableModel:
    def get_evidence(self, reaction_id: str) -> ReactionEvidence | None:
        """Get evidence for a specific reaction."""
        return self._evidence.get(reaction_id)

    @property
    def reactions(self) -> list[Reaction]:
        """Get list of all reactions."""
        return list(self._reactions)
```

**ReactionFilterProxy, ReactionTableWidget** 수정: `model._evidence` → `model.get_evidence()`

### 4.3 영향 범위

| 파일 | 변경 내용 |
|------|-----------|
| `src/evidence/engine.py` | `cache_manager`, `mapping_data` property 추가 (2줄x2) |
| `src/cli.py` | `_cache` → `cache_manager`, `_mapping_data` → `mapping_data` |
| `src/gui/reaction_table.py` | `get_evidence()`, `reactions` property 추가, 내부 참조 수정 |

---

## 5. Phase 3: DRY 추출 (FR-04 ~ FR-07)

### 5.1 신규: `src/core/cobra_utils.py`

```python
"""Shared utilities for converting COBRApy objects to internal models."""
from __future__ import annotations

import cobra

from src.core.gpr_parser import extract_genes, parse_gpr
from src.core.models import Reaction


def convert_cobra_reaction(rxn: cobra.Reaction) -> Reaction:
    """Convert a cobra.Reaction to internal Reaction dataclass."""
    gene_rule = rxn.gene_reaction_rule or ""
    genes = extract_genes(gene_rule)
    gpr_tree = parse_gpr(gene_rule)

    reactants: dict[str, float] = {}
    products: dict[str, float] = {}
    for met, coef in rxn.metabolites.items():
        if coef < 0:
            reactants[met.id] = abs(coef)
        else:
            products[met.id] = coef

    annotation = normalize_annotation(rxn.annotation)

    return Reaction(
        id=rxn.id,
        name=rxn.name or rxn.id,
        equation=rxn.build_reaction_string(use_metabolite_names=True),
        equation_id=rxn.build_reaction_string(use_metabolite_names=False),
        subsystem=rxn.subsystem or None,
        lower_bound=rxn.lower_bound,
        upper_bound=rxn.upper_bound,
        gene_reaction_rule=gene_rule,
        gpr_tree=gpr_tree,
        genes=genes,
        reactants=reactants,
        products=products,
        annotation=annotation,
    )


def normalize_annotation(annotation: dict) -> dict[str, list[str]]:
    """Normalize COBRApy annotation dict to {db: [ids]}."""
    result: dict[str, list[str]] = {}
    if not annotation:
        return result
    for key, value in annotation.items():
        if isinstance(value, str):
            result[key] = [value]
        elif isinstance(value, list):
            result[key] = [str(v) for v in value]
        else:
            result[key] = [str(value)]
    return result
```

**수정 대상**:
- `src/core/sbml_parser.py`: `_convert_reaction()` / `_normalize_annotation()` → `cobra_utils` 호출
- `src/core/universal_loader.py`: `_convert_reaction()` / `_normalize_annotation()` → `cobra_utils` 호출

### 5.2 신규: `src/api/llm_utils.py`

```python
"""Shared utilities for LLM API response parsing."""
from __future__ import annotations

import json
import re


def extract_json_from_response(text: str) -> dict | None:
    """Extract JSON object from LLM response text.

    Tries 3 strategies:
    1. Direct JSON parse
    2. Code block extraction (```json ... ```)
    3. Brace extraction (first { ... last })
    """
    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy 2: code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except (json.JSONDecodeError, TypeError):
            pass

    # Strategy 3: brace extraction
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, TypeError):
            pass

    return None
```

**수정 대상**:
- `src/api/gemini_client.py`: `_extract_json()` 삭제 → `llm_utils.extract_json_from_response()` 호출
- `src/api/perplexity_client.py`: `_extract_json()` 삭제 → `llm_utils.extract_json_from_response()` 호출

### 5.3 변경: `src/evidence/engine.py` — 공통 파이프라인 추출

```python
class EvidenceEngine:
    async def _run_evidence_pipeline(
        self,
        reaction: Reaction,
        ext_ids: ExternalIDs,
        evidence: ReactionEvidence,
        bigg_override: EvidenceItem | None = None,
    ) -> None:
        """Shared evidence pipeline: steps 2-10 for both model and candidate reactions."""
        # Step 2: KEGG verification
        kegg_items = await self._kegg.check_evidence(...)
        evidence.items.extend(kegg_items)

        # Step 3: Extract match ratios
        kegg_parsed_data = self._extract_kegg_data(kegg_items, evidence)

        # Step 4: BiGG
        if bigg_override:
            evidence.items.append(bigg_override)
        elif self._bigg:
            # ... existing BiGG logic

        # Steps 5-9: UniProt, PubMed, MetaCyc, Gemini, Perplexity
        # (identical logic extracted here)

        # Step 10: Score
        self._scorer.score(evidence)
        evidence.status = EvaluationStatus.EVALUATED

    async def evaluate_reaction(self, reaction: Reaction) -> ReactionEvidence:
        """Evaluate model reaction."""
        evidence = ReactionEvidence(reaction_id=reaction.id)
        evidence.status = EvaluationStatus.IN_PROGRESS
        try:
            ext_ids = await self._mapper.resolve(reaction)
            evidence.ec_numbers = ext_ids.ec_numbers
            evidence.kegg_reaction_ids = ext_ids.kegg_reaction_ids
            await self._run_evidence_pipeline(reaction, ext_ids, evidence)
        except Exception as e:
            # ... error handling
        self._results[reaction.id] = evidence
        return evidence

    async def evaluate_candidate(self, candidate: CandidateReaction) -> ReactionEvidence:
        """Evaluate candidate reaction."""
        reaction = candidate.reaction
        evidence = ReactionEvidence(reaction_id=reaction.id)
        evidence.status = EvaluationStatus.IN_PROGRESS
        try:
            ext_ids = await self._mapper.resolve_universal(reaction)
            evidence.ec_numbers = ext_ids.ec_numbers
            evidence.kegg_reaction_ids = ext_ids.kegg_reaction_ids
            bigg_override = EvidenceItem(
                source=EvidenceSource.BIGG,
                strength=EvidenceStrength.STRONG,
                description=f"Reaction exists in BiGG universal model (source: {candidate.source_model})",
                url=f"http://bigg.ucsd.edu/universal/reactions/{reaction.id}",
            )
            await self._run_evidence_pipeline(reaction, ext_ids, evidence, bigg_override)
        except Exception as e:
            # ... error handling
        self._results[reaction.id] = evidence
        return evidence
```

**배치 통합**: `evaluate_batch()` + `evaluate_candidates_batch()` → `_run_batch()` 공통 메서드

```python
    async def _run_batch(
        self,
        items: list,
        eval_fn: Callable,
        id_fn: Callable[[Any], str],
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, ReactionEvidence]:
        """Shared batch evaluation logic."""
        # ... semaphore + batch + progress (identical pattern)
```

### 5.4 변경: `src/core/id_mapper.py` — resolve 통합

```python
class IdentifierMapper:
    async def resolve(
        self, reaction: Reaction, *, universal: bool = False
    ) -> ExternalIDs:
        """Resolve external IDs. Set universal=True for BiGG universal model reactions."""
        bigg_id = self._normalize_bigg_id(reaction.id)
        ext = ExternalIDs(reaction_id=reaction.id, bigg_id=bigg_id)

        # Step 1: annotation extraction (format-dependent)
        if universal:
            self._extract_from_universal_annotation(reaction, ext)
        else:
            self._extract_from_annotation(reaction, ext)

        # Steps 2-4: shared mapping logic (identical)
        self._resolve_from_mapping(bigg_id, ext)

        # Steps 5-6: metabolite mapping (only for SBML models)
        if not universal:
            self._resolve_metabolites(reaction, ext)

        return ext

    # Keep resolve_universal() as deprecated wrapper for backward compatibility
    async def resolve_universal(self, reaction: Reaction) -> ExternalIDs:
        """Deprecated: use resolve(reaction, universal=True)."""
        return await self.resolve(reaction, universal=True)
```

`_strip_compartment` → `strip_compartment` (public 이름으로 변경)

### 5.5 영향 범위

| 파일 | 변경 |
|------|------|
| `src/core/cobra_utils.py` | **신규** ~45줄 |
| `src/api/llm_utils.py` | **신규** ~40줄 |
| `src/core/sbml_parser.py` | `_convert_reaction`, `_normalize_annotation` → `cobra_utils` 호출 (-30줄) |
| `src/core/universal_loader.py` | 동일 (-50줄) |
| `src/api/gemini_client.py` | `_extract_json` 삭제 → `llm_utils` 호출 (-25줄) |
| `src/api/perplexity_client.py` | 동일 (-25줄) |
| `src/evidence/engine.py` | `_run_evidence_pipeline`, `_run_batch` 추출 (-150줄) |
| `src/core/id_mapper.py` | resolve 통합, strip_compartment public (-30줄) |

---

## 6. Phase 4: MainWindow 분해 (FR-08)

### 6.1 Controller 분리 전략

MainWindow의 75+ 메서드를 기능 도메인별로 Controller에 위임.
MainWindow는 UI 구성 + 시그널 라우팅만 담당.

### 6.2 Controller 정의

#### `src/gui/controllers/__init__.py`
빈 패키지 파일.

#### `src/gui/controllers/evaluation_ctrl.py` (~150줄)

```python
class EvaluationController:
    """Manages evidence evaluation lifecycle."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    # 이관 메서드:
    def evaluate_selected(self) -> None: ...
    def evaluate_reaction_by_id(self, reaction_id: str) -> None: ...
    def evaluate_reaction(self, reaction: Reaction) -> None: ...
    def on_reaction_evaluated(self, evidence: object) -> None: ...
    def evaluate_all(self) -> None: ...
    def run_model_evaluation(self, ...) -> None: ...
    def run_candidate_evaluation(self, candidates: list) -> None: ...
    def on_batch_complete(self, results: object, dialog: ProgressDialog) -> None: ...
    def on_batch_error(self, error: str, dialog: ProgressDialog) -> None: ...
    def clear_results(self) -> None: ...
    def evaluate_batch(self, reactions: list) -> None: ...
```

#### `src/gui/controllers/gapfill_ctrl.py` (~200줄)

```python
class GapFillController:
    """Manages gap-filling workflow."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    # 이관 메서드:
    def start_workflow(self) -> None: ...
    def resume_workflow(self) -> None: ...
    def load_task_file(self) -> None: ...
    def run_task_analysis(self, tasks: list) -> None: ...
    def run_gapfill_workflow(self, selections: dict) -> None: ...
    def start_gapfill_worker(self, selections: dict) -> None: ...
    def on_gapfill_complete(self, result: object, dialog: ProgressDialog) -> None: ...
    def on_gapfill_cancelled(self, ...) -> None: ...
    def on_gapfill_error(self, error: str, dialog: ProgressDialog) -> None: ...
    def on_apply_gapfill(self) -> None: ...
    def load_universal_model(self) -> None: ...
    def on_universal_selected(self, reaction_id: str) -> None: ...
    def evaluate_universal_candidates(self, candidates: list) -> None: ...
```

#### `src/gui/controllers/export_ctrl.py` (~150줄)

```python
class ExportController:
    """Manages file export operations."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    # 이관 메서드:
    def export_csv(self) -> None: ...
    def export_json(self) -> None: ...
    def export_sbml(self) -> None: ...
    def export_improved_sbml(self) -> None: ...
    def export_gapfill_report(self) -> None: ...

    @staticmethod
    def serialize_raw_data(raw_data: dict | None) -> dict | None: ...
```

#### `src/gui/controllers/version_ctrl.py` (~150줄)

```python
class VersionController:
    """Manages model version control."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    # 이관 메서드:
    def on_reaction_modified(self, reaction_id: str) -> None: ...
    def save_version(self) -> None: ...
    def do_save_version(self, ...) -> None: ...
    def auto_save_version(self, change_type: str) -> None: ...
    def restore_version(self, version_id: str) -> None: ...
    def show_version_detail(self, version_id: str) -> None: ...
    def compare_versions(self, version_a: str, version_b: str) -> None: ...
    def export_version_sbml(self, version_id: str) -> None: ...
    def run_qc_for_version(self) -> None: ...
```

### 6.3 MainWindow 수정 후 구조 (~300줄)

```python
class MainWindow(QMainWindow):
    def __init__(self, config: Config) -> None:
        super().__init__()
        # State
        self._config = config
        self._model: ModelData | None = None
        self._engine: EvidenceEngine | None = None
        # ... (기존 state 유지)

        # Controllers
        self._eval_ctrl = EvaluationController(self)
        self._gapfill_ctrl = GapFillController(self)
        self._export_ctrl = ExportController(self)
        self._version_ctrl = VersionController(self)

        self._setup_menu()
        self._setup_ui()
        self._setup_statusbar()
        self._init_engine()

    # --- Setup (유지) ---
    def _setup_menu(self) -> None: ...     # 메뉴 → controller 메서드 연결
    def _setup_ui(self) -> None: ...       # UI 위젯 생성
    def _setup_statusbar(self) -> None: ...

    # --- Engine lifecycle (유지 — MainWindow 고유 책임) ---
    def _init_engine(self) -> None: ...
    def _start_engine_init(self) -> None: ...
    def _on_engine_ready(self, ...) -> None: ...

    # --- Model loading (유지) ---
    def _open_model(self) -> None: ...
    def _load_model(self, filepath: str) -> None: ...
    def _on_model_loaded(self, model: object) -> None: ...

    # --- Delegation to controllers ---
    # 메뉴 액션에서 직접 controller 메서드 호출
    # 예: eval_menu.addAction("Evaluate &All", self._eval_ctrl.evaluate_all)

    # --- Utilities (유지) ---
    def _get_selected_reaction(self) -> Reaction | None: ...
    def _update_eval_count(self) -> None: ...
    def _update_recent_menu(self) -> None: ...
```

---

## 7. Phase 5: 보안 + 기타 (FR-03, FR-10 ~ FR-12)

### 7.1 `src/utils/config.py` — 보안 강화

```python
import os

class Config:
    # API 키 환경변수 오버라이드
    @classmethod
    def load(cls) -> Config:
        config = cls(...)  # 기존 JSON 로딩
        # 환경변수 우선
        if env_key := os.environ.get("GEM_GEMINI_API_KEY"):
            config.gemini_api_key = env_key
        if env_key := os.environ.get("GEM_PERPLEXITY_API_KEY"):
            config.perplexity_api_key = env_key
        if env_key := os.environ.get("GEM_PUBMED_API_KEY"):
            config.pubmed_api_key = env_key
        return config

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE_PATH.write_text(json.dumps(asdict(self), indent=2, default=str))
        CONFIG_FILE_PATH.chmod(0o600)  # owner-only read/write
```

### 7.2 `src/utils/constants.py` — HTTPS

```python
# Before
BIGG_API_BASE = "http://bigg.ucsd.edu/api/v2"
# After
BIGG_API_BASE = "https://bigg.ucsd.edu/api/v2"
```

### 7.3 `src/gui/workers.py` — set_event_loop 제거

```python
# Before
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)  # deprecated in 3.12+
try:
    loop.run_until_complete(self._run())
finally:
    loop.close()

# After
loop = asyncio.new_event_loop()
try:
    loop.run_until_complete(self._run())
finally:
    loop.close()
```

### 7.4 `src/core/models.py` — reaction index

```python
@dataclass
class ModelData:
    # ... existing fields
    _reaction_index: dict[str, Reaction] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.reactions and not self._reaction_index:
            self._reaction_index = {r.id: r for r in self.reactions}

    def get_reaction(self, reaction_id: str) -> Reaction | None:
        """O(1) reaction lookup by ID."""
        if not self._reaction_index and self.reactions:
            self._reaction_index = {r.id: r for r in self.reactions}
        return self._reaction_index.get(reaction_id)
```

---

## 8. Test Plan

### 8.1 Test Scope

| Type | Target | Tool |
|------|--------|------|
| Unit Test | cobra_utils, llm_utils | pytest |
| Unit Test | EvidenceEngine properties | pytest |
| Unit Test | Config permissions | pytest |
| Integration | evidence module import without PySide6 | subprocess |
| Regression | All existing tests | pytest |

### 8.2 Key Test Cases

- [ ] `test_cobra_utils.py`: `convert_cobra_reaction()` output matches previous `SBMLParser._convert_reaction()`
- [ ] `test_llm_utils.py`: 3가지 전략 (direct, code block, brace extraction) 각각 검증
- [ ] `test_evidence_types.py`: `import src.evidence.evidence_types` 시 PySide6 미설치 환경에서 ImportError 없음
- [ ] `test_config_security.py`: `Config.save()` 후 파일 권한 `0o600` 확인
- [ ] `test_engine_properties.py`: `engine.cache_manager`, `engine.mapping_data` 정상 노출
- [ ] **전체 기존 테스트 통과**: `pytest tests/ -v`

---

## 9. Implementation Order

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5
   │          │          │          │          │
   │          │          │          │          └→ config, constants, workers, models
   │          │          │          └→ MainWindow → 4 controllers
   │          │          └→ cobra_utils, llm_utils, engine pipeline, id_mapper
   │          └→ engine properties, reaction_table accessors
   └→ evidence_types (gui import 제거), evidence_colors (신규)
```

각 Phase 완료 후 `pytest tests/ -v` 실행하여 regression 없음 확인.

---

## 10. File Change Summary

| 변경 유형 | 파일 | Phase |
|-----------|------|-------|
| **신규** | `src/core/cobra_utils.py` | 3 |
| **신규** | `src/api/llm_utils.py` | 3 |
| **신규** | `src/gui/evidence_colors.py` | 1 |
| **신규** | `src/gui/controllers/__init__.py` | 4 |
| **신규** | `src/gui/controllers/evaluation_ctrl.py` | 4 |
| **신규** | `src/gui/controllers/gapfill_ctrl.py` | 4 |
| **신규** | `src/gui/controllers/export_ctrl.py` | 4 |
| **신규** | `src/gui/controllers/version_ctrl.py` | 4 |
| **수정** | `src/evidence/evidence_types.py` | 1 |
| **수정** | `src/app.py` | 1 |
| **수정** | `src/evidence/engine.py` | 2, 3 |
| **수정** | `src/cli.py` | 2 |
| **수정** | `src/gui/reaction_table.py` | 2 |
| **수정** | `src/core/sbml_parser.py` | 3 |
| **수정** | `src/core/universal_loader.py` | 3 |
| **수정** | `src/api/gemini_client.py` | 3 |
| **수정** | `src/api/perplexity_client.py` | 3 |
| **수정** | `src/core/id_mapper.py` | 3 |
| **수정** | `src/gui/main_window.py` | 4 |
| **수정** | `src/utils/config.py` | 5 |
| **수정** | `src/utils/constants.py` | 5 |
| **수정** | `src/gui/workers.py` | 5 |
| **수정** | `src/core/models.py` | 5 |

**총**: 신규 8파일, 수정 14파일

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-27 | Initial design from code analysis | Claude Code |
