# Design: Stability, Score-Based Gap-Fill, Version Control

> Plan 참조: `docs/01-plan/features/stability-scoring-versioning.plan.md`
> Phase A (안정성)는 이미 구현 완료. 이 문서는 Phase B, C를 설계함.

---

## 0. Phase A: 안정성 수정 (완료)

### 수정 내용

| 파일 | 변경 | 상태 |
|------|------|------|
| `src/gui/workers.py` | `_safe_emit()` 함수 추가 — 모든 signal emit을 `try/except RuntimeError`로 보호 | ✅ |
| `src/gui/workers.py` | `InitEngineWorker`, `CloseEngineWorker`, `LoadModelWorker`를 `setAutoDelete(False)`로 변경 | ✅ |
| `src/gui/main_window.py` | `_active_worker` → `_active_workers: list[object]`로 변경, Worker GC 방지 강화 | ✅ |
| `src/gui/main_window.py` | `LoadModelWorker`에 `finished` signal로 자동 리스트 해제 연결 | ✅ |
| `src/core/sbml_parser.py` | COBRApy 경고를 `warnings.catch_warnings()`로 suppress | ✅ |

---

## 1. 파일 변경 목록

### 1.1 Phase B: Score-Based Gap-Fill (수정 파일만)

| 파일 | 변경 |
|------|------|
| `src/gapfill/engine.py` | penalty dict 전달 검증, 결과 score 순 정렬 |
| `src/gui/candidate_table.py` | 기본 정렬을 Score 내림차순으로 |
| `src/gui/gapfill_panel.py` | 추가 반응 Score 내림차순 표시 |

### 1.2 Phase C: 버전 컨트롤 (신규 + 수정)

**신규 파일:**

| 파일 | 역할 |
|------|------|
| `src/versioning/__init__.py` | 패키지 |
| `src/versioning/diff_engine.py` | cobra.Model 비교 → ModelDiff |
| `src/versioning/storage.py` | 파일 시스템 기반 버전 저장/로드 |
| `src/versioning/version_manager.py` | 버전 관리 오케스트레이터 |
| `src/versioning/change_summarizer.py` | LLM/자동 변경 요약 생성 |
| `src/gui/save_dialog.py` | 저장 다이얼로그 (QC 옵션) |
| `src/gui/version_panel.py` | 버전 히스토리 타임라인 |
| `src/gui/diff_dialog.py` | 버전 비교 다이얼로그 |
| `tests/test_diff_engine.py` | Diff engine 테스트 |
| `tests/test_version_manager.py` | Version manager 테스트 |
| `tests/test_change_summarizer.py` | Change summarizer 테스트 |

**수정 파일:**

| 파일 | 변경 |
|------|------|
| `src/core/models.py` | ModelVersion, ModelDiff, ReactionChange 추가 |
| `src/utils/config.py` | 버전 관련 설정 추가 |
| `src/utils/constants.py` | 버전 관련 상수 추가 |
| `src/gui/main_window.py` | Version 탭, Save 메뉴, 자동 스냅샷 연동 |

---

## 2. 데이터 모델 (`src/core/models.py` 추가)

```python
@dataclass
class ReactionChange:
    """단일 반응의 필드 변경."""
    reaction_id: str
    field: str          # "lower_bound", "upper_bound", "gene_reaction_rule", "name"
    old_value: str
    new_value: str


@dataclass
class ModelDiff:
    """두 모델 버전 간 차이."""
    reactions_added: list[str] = field(default_factory=list)
    reactions_removed: list[str] = field(default_factory=list)
    reactions_modified: list[ReactionChange] = field(default_factory=list)
    genes_added: list[str] = field(default_factory=list)
    genes_removed: list[str] = field(default_factory=list)
    metabolites_added: list[str] = field(default_factory=list)
    metabolites_removed: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any([
            self.reactions_added, self.reactions_removed, self.reactions_modified,
            self.genes_added, self.genes_removed,
            self.metabolites_added, self.metabolites_removed,
        ])

    @property
    def summary_counts(self) -> str:
        parts = []
        if self.reactions_added:
            parts.append(f"+{len(self.reactions_added)} reactions")
        if self.reactions_removed:
            parts.append(f"-{len(self.reactions_removed)} reactions")
        if self.reactions_modified:
            parts.append(f"~{len(self.reactions_modified)} modified")
        if self.genes_added:
            parts.append(f"+{len(self.genes_added)} genes")
        if self.genes_removed:
            parts.append(f"-{len(self.genes_removed)} genes")
        return ", ".join(parts) if parts else "No changes"


@dataclass
class ModelVersion:
    """단일 모델 버전 스냅샷 메타데이터."""
    version_id: str
    timestamp: str
    parent_version_id: str | None = None
    model_id: str = ""
    description: str = ""
    change_type: str = "initial_load"  # initial_load, manual_edit, gap_fill, restore
    diff: ModelDiff | None = None
    task_pass_rate: str | None = None   # "35/52"
    sbml_filename: str = "model.xml"
```

### Config 추가 (`src/utils/config.py`)

```python
    # Version control settings
    enable_versioning: bool = True
    max_versions: int = 20
    auto_save_on_edit: bool = True
    version_dir: str = ""   # default: ~/.gem_evaluator/versions/
```

### Constants 추가 (`src/utils/constants.py`)

```python
VERSION_DIR = CONFIG_DIR / "versions"
MAX_VERSIONS_DEFAULT = 20
```

---

## 3. 모듈별 상세 설계

### 3.1 `src/versioning/diff_engine.py`

```python
"""Compute diffs between two cobra.Model instances."""

class DiffEngine:
    """두 cobra.Model 간 차이를 계산."""

    def compute_diff(
        self, old_model: cobra.Model, new_model: cobra.Model
    ) -> ModelDiff:
        """두 모델을 비교하여 ModelDiff 반환.

        비교 항목:
        1. Reactions: ID 기반 set diff → added/removed
        2. Reactions modified: 동일 ID의 bounds, GPR, name 비교
        3. Genes: ID 기반 set diff
        4. Metabolites: ID 기반 set diff

        Performance: O(n) — ID set 연산
        """

    def _compare_reactions(
        self,
        old_rxns: dict[str, cobra.Reaction],
        new_rxns: dict[str, cobra.Reaction],
    ) -> tuple[list[str], list[str], list[ReactionChange]]:
        """반응 비교 → (added, removed, modified)."""

    def _diff_reaction(
        self, old: cobra.Reaction, new: cobra.Reaction
    ) -> list[ReactionChange]:
        """단일 반응의 필드 변경 감지.

        비교 필드:
        - lower_bound, upper_bound
        - gene_reaction_rule
        - name
        - subsystem
        """
```

### 3.2 `src/versioning/storage.py`

```python
"""File-system based version storage."""

class VersionStorage:
    """버전 스냅샷을 파일 시스템에 저장/로드."""

    def __init__(self, base_dir: Path | None = None) -> None:
        """base_dir: ~/.gem_evaluator/versions/ (default)"""

    def save_version(
        self,
        model_id: str,
        version: ModelVersion,
        cobra_model: cobra.Model,
    ) -> Path:
        """버전 저장.

        구조:
        {base_dir}/{model_id}/v{NNN}/
            model.xml      — cobra.io.write_sbml_model()
            meta.json      — ModelVersion as JSON

        반환: 저장된 디렉토리 경로
        """

    def load_version(
        self, model_id: str, version_id: str
    ) -> tuple[cobra.Model, ModelVersion]:
        """특정 버전 로드.

        반환: (cobra_model, version_metadata)
        """

    def load_history(self, model_id: str) -> list[ModelVersion]:
        """모델의 전체 버전 히스토리 로드.

        {base_dir}/{model_id}/history.json 읽기
        """

    def save_history(self, model_id: str, versions: list[ModelVersion]) -> None:
        """히스토리 인덱스 저장."""

    def cleanup_old_versions(self, model_id: str, max_keep: int = 20) -> int:
        """오래된 버전 정리. 반환: 삭제된 버전 수."""

    def get_next_version_id(self, model_id: str) -> str:
        """다음 버전 ID 생성 (v001, v002, ...)."""
```

### 3.3 `src/versioning/version_manager.py`

```python
"""Version management orchestrator."""

class VersionManager:
    """모델 버전 관리 — 저장, 비교, 복구를 orchestrate."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._storage = VersionStorage(...)
        self._diff_engine = DiffEngine()
        self._summarizer = ChangeSummarizer(config)
        self._current_version: ModelVersion | None = None
        self._previous_model: cobra.Model | None = None  # diff 계산용

    def set_base_model(self, cobra_model: cobra.Model, model_id: str) -> None:
        """초기 모델 로드 시 호출. v001으로 저장."""

    async def save_version(
        self,
        cobra_model: cobra.Model,
        change_type: str,
        task_results: list[TaskResult] | None = None,
        custom_description: str | None = None,
    ) -> ModelVersion:
        """새 버전 저장.

        1. DiffEngine.compute_diff(previous, current)
        2. ChangeSummarizer.summarize(diff, change_type) — or use custom_description
        3. VersionStorage.save_version()
        4. VersionStorage.cleanup_old_versions() if over limit
        5. Update current_version and previous_model
        """

    def restore_version(self, version_id: str) -> cobra.Model:
        """특정 버전으로 복구.

        1. VersionStorage.load_version(version_id)
        2. 새 "restore" 버전으로 저장
        3. 반환: 복구된 cobra.Model
        """

    def get_history(self) -> list[ModelVersion]:
        """현재 모델의 버전 히스토리."""

    def compare_versions(
        self, version_a: str, version_b: str
    ) -> ModelDiff:
        """두 버전 비교."""

    @property
    def current_version(self) -> ModelVersion | None:
        """현재 버전."""
```

### 3.4 `src/versioning/change_summarizer.py`

```python
"""Generate human-readable change summaries."""

class ChangeSummarizer:
    """ModelDiff를 자연어 요약으로 변환."""

    def __init__(self, config: Config) -> None:
        self._config = config

    async def summarize(self, diff: ModelDiff, change_type: str) -> str:
        """변경 요약 생성.

        1. 템플릿 기반 자동 생성

        요약 예:
        "Gap-filling: added {N} reactions"
        """

    def _template_summary(self, diff: ModelDiff, change_type: str) -> str:
        """LLM fallback — 템플릿 기반 요약.

        예시:
        - "Initial model load (1366 reactions, 904 genes)"
        - "Gap-filling: added 23 reactions, 13 metabolic tasks fixed"
        - "Manual edit: modified bounds for PFK, PGK"
        - "Restored to version v002"
        """
```

### 3.5 GUI: `src/gui/save_dialog.py`

```python
"""Save dialog with version control and QC options."""

class SaveDialog(QDialog):
    """모델 저장 다이얼로그.

    ┌────────────────────────────────────────────┐
    │  Save Model Version                        │
    ├────────────────────────────────────────────┤
    │  Change Type: [Gap-Fill ▼]                 │
    │                                            │
    │  Description:                              │
    │  ┌────────────────────────────────────┐    │
    │  │ (LLM 자동 생성 또는 수동 입력)      │    │
    │  └────────────────────────────────────┘    │
    │                                            │
    │  ☑ Run Metabolic Task QC before saving     │
    │  ☐ Also export SBML file copy              │
    │                                            │
    │  Previous: v002 (48/52 tasks passed)       │
    │                                            │
    │         [Cancel]  [Save Version]            │
    └────────────────────────────────────────────┘
    """

    def __init__(
        self, config: Config, current_version: ModelVersion | None, parent=None
    ) -> None: ...

    def get_options(self) -> dict:
        """반환: {change_type, description, run_qc, export_sbml}"""
```

### 3.6 GUI: `src/gui/version_panel.py`

```python
"""Version history timeline panel."""

class VersionPanelWidget(QWidget):
    """버전 히스토리 타임라인.

    - QListWidget으로 버전 목록 (최신 상단)
    - 각 항목: version_id, timestamp, description, task_pass_rate
    - 버튼: Compare, Restore, Export
    - Signals: restore_requested(str), compare_requested(str, str), export_requested(str)
    """

    restore_requested = Signal(str)     # version_id
    compare_requested = Signal(str, str) # version_a, version_b
    export_requested = Signal(str)      # version_id

    def set_history(self, versions: list[ModelVersion]) -> None:
        """히스토리 로드."""

    def clear(self) -> None:
        """초기화."""
```

### 3.7 GUI: `src/gui/diff_dialog.py`

```python
"""Version comparison dialog."""

class DiffDialog(QDialog):
    """두 버전 간 diff를 보여주는 다이얼로그.

    ┌────────────────────────────────────────────────┐
    │  Compare: v001 ← v002                          │
    ├────────────────────────────────────────────────┤
    │  Reactions Added (23):                         │
    │  ┌──────────────────────────────────────────┐  │
    │  │ GLNS  │ Glutamine synthetase │ 0.85     │  │
    │  │ PRPPS │ PRPP synthase        │ 0.72     │  │
    │  └──────────────────────────────────────────┘  │
    │                                                │
    │  Reactions Removed (0):                        │
    │  (none)                                        │
    │                                                │
    │  Reactions Modified (2):                       │
    │  ┌──────────────────────────────────────────┐  │
    │  │ PFK │ lower_bound │ 0.0 → -1000.0       │  │
    │  └──────────────────────────────────────────┘  │
    │                                                │
    │  QC: v001 (35/52) → v002 (48/52)              │
    │                             [Close]            │
    └────────────────────────────────────────────────┘
    """

    def __init__(
        self, diff: ModelDiff, version_a: ModelVersion, version_b: ModelVersion, parent=None
    ) -> None: ...
```

### 3.8 `src/gui/main_window.py` 수정

```python
# __init__에 추가
self._version_manager: VersionManager | None = None

# _setup_menu에 추가
# File 메뉴에:
file_menu.addAction("&Save Version...", self._save_version, "Ctrl+S")

# _setup_ui에 추가
# Right tabs에:
self._version_panel = VersionPanelWidget()
right_tabs.addTab(self._version_panel, "Versions")

# Signal 연결
self._version_panel.restore_requested.connect(self._restore_version)
self._version_panel.compare_requested.connect(self._compare_versions)

# 새 메서드들:
def _on_model_loaded(self, model):
    # ... 기존 코드 ...
    # 초기 버전 저장
    self._version_manager = VersionManager(self._config)
    self._version_manager.set_base_model(model.cobra_model, model.id)
    self._version_panel.set_history(self._version_manager.get_history())

def _save_version(self):
    """SaveDialog 열고, QC 실행 후 버전 저장."""

def _restore_version(self, version_id: str):
    """특정 버전으로 복구."""

def _compare_versions(self, va: str, vb: str):
    """DiffDialog 열기."""

def _on_reaction_modified(self, reaction_id: str):
    # ... 기존 코드 ...
    # 자동 임시 저장 (auto_save_on_edit 설정에 따라)

def _on_gapfill_complete(self, result, dialog):
    # ... 기존 코드 ...
    # Gap-fill 결과를 버전으로 자동 저장
```

---

## 4. 구현 순서

```
Phase B (Score Gap-Fill): 3 파일 수정 — 독립 작업
  1. src/gapfill/engine.py — penalty 전달 검증, score 순 정렬
  2. src/gui/candidate_table.py — 기본 Score 내림차순
  3. src/gui/gapfill_panel.py — Score 순 표시

Phase C (Version Control): 의존 관계 있는 순서
  1. src/core/models.py — ModelVersion, ModelDiff, ReactionChange
  2. src/utils/constants.py, config.py — 버전 설정/상수
  3. src/versioning/__init__.py
  4. src/versioning/diff_engine.py + tests/test_diff_engine.py
  5. src/versioning/storage.py + tests/test_version_manager.py (부분)
  6. src/versioning/change_summarizer.py + tests/test_change_summarizer.py
  7. src/versioning/version_manager.py + tests/test_version_manager.py (완성)
  8. src/gui/save_dialog.py
  9. src/gui/version_panel.py
  10. src/gui/diff_dialog.py
  11. src/gui/main_window.py — 통합
```

---

*Design created: 2026-02-21*
*Feature: stability-scoring-versioning*
*PDCA Phase: Design*
