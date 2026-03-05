# Design: Project Save/Load

## 1. Overview

프로젝트 단위로 모델 + 평가 결과 + gap-fill 상태를 `.gemp` 파일에 저장하고 복원하는 기능.
사용자가 앱을 닫았다 열어도 이전 분석 상태를 그대로 이어서 작업 가능.

**Plan 참조**: `docs/01-plan/features/project-save-load.plan.md`

## 2. Architecture

### 2.1 Component Diagram

```
MainWindow
├─ _project_path: str | None          ← 현재 프로젝트 파일 경로
├─ _project_dirty: bool               ← 변경 감지 플래그
│
├─ File Menu (수정)
│   ├─ Open Model...        (Ctrl+O)
│   ├─ Open Project...      (Ctrl+Shift+O)  ← 신규
│   ├─ ─────────────
│   ├─ Save Project         (Ctrl+S)        ← 신규 (기존 CSV export 단축키 제거)
│   ├─ Save Project As...                   ← 신규
│   ├─ ─────────────
│   ├─ Recent Models >
│   ├─ Recent Projects >                    ← 신규
│   └─ ...
│
└─ ProjectManager (신규)
    ├─ save(path, project_data) → None
    ├─ load(path) → ProjectData
    ├─ from_app_state(window) → ProjectData
    └─ apply_to_app(project_data, window) → None
```

### 2.2 File Structure

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/core/project_manager.py` | **신규** | ProjectData dataclass + ProjectManager 클래스 |
| `src/core/models.py` | 수정 | `to_dict()`/`from_dict()` 메서드 추가 (ReactionEvidence, EvidenceItem) |
| `src/gui/main_window.py` | 수정 | File 메뉴 변경, save/load 액션, dirty flag, closeEvent |
| `src/utils/config.py` | 수정 | `recent_projects` 리스트 추가 |
| `tests/test_project_manager.py` | **신규** | 저장/로딩/직렬화 테스트 |

## 3. Detailed Design

### 3.1 직렬화 메서드 (`src/core/models.py`)

기존 dataclass에 `to_dict()` / `from_dict()` 클래스 메서드 추가.

#### 3.1.1 EvidenceItem

```python
@dataclass
class EvidenceItem:
    # ... 기존 필드 ...

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "strength": self.strength.value,
            "description": self.description,
            "url": self.url,
            "raw_data": self.raw_data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EvidenceItem:
        return cls(
            source=EvidenceSource(data["source"]),
            strength=EvidenceStrength(data["strength"]),
            description=data["description"],
            url=data.get("url"),
            raw_data=data.get("raw_data"),
        )
```

#### 3.1.2 ReactionEvidence

```python
@dataclass
class ReactionEvidence:
    # ... 기존 필드 ...

    def to_dict(self) -> dict:
        return {
            "reaction_id": self.reaction_id,
            "confidence_score": self.confidence_score,
            "status": self.status.value,
            "error_message": self.error_message,
            "kegg_score": self.kegg_score,
            "bigg_score": self.bigg_score,
            "uniprot_score": self.uniprot_score,
            "pubmed_score": self.pubmed_score,
            "gemini_score": self.gemini_score,
            "perplexity_score": self.perplexity_score,
            "ec_numbers": self.ec_numbers,
            "kegg_reaction_ids": self.kegg_reaction_ids,
            "substrate_match_ratio": self.substrate_match_ratio,
            "product_match_ratio": self.product_match_ratio,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReactionEvidence:
        items = [EvidenceItem.from_dict(d) for d in data.get("items", [])]
        return cls(
            reaction_id=data["reaction_id"],
            confidence_score=data.get("confidence_score", 0.0),
            status=EvaluationStatus(data.get("status", "not_evaluated")),
            error_message=data.get("error_message"),
            kegg_score=data.get("kegg_score", 0.0),
            bigg_score=data.get("bigg_score", 0.0),
            uniprot_score=data.get("uniprot_score", 0.0),
            pubmed_score=data.get("pubmed_score", 0.0),
            gemini_score=data.get("gemini_score", 0.0),
            perplexity_score=data.get("perplexity_score", 0.0),
            ec_numbers=data.get("ec_numbers", []),
            kegg_reaction_ids=data.get("kegg_reaction_ids", []),
            substrate_match_ratio=data.get("substrate_match_ratio", 0.0),
            product_match_ratio=data.get("product_match_ratio", 0.0),
            items=items,
        )
```

#### 3.1.3 TaskResult / MetabolicTask

```python
@dataclass
class MetabolicTask:
    # ... 기존 필드 ...

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "target_id": self.target_id,
            "medium": self.medium,
            "constraints": {k: list(v) for k, v in self.constraints.items()},
            "expected_operator": self.expected_operator,
            "expected_value": self.expected_value,
            "description": self.description,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MetabolicTask:
        constraints = {k: tuple(v) for k, v in data.get("constraints", {}).items()}
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            target_id=data["target_id"],
            medium=data.get("medium", {}),
            constraints=constraints,
            expected_operator=data.get("expected_operator", ">"),
            expected_value=data.get("expected_value", 0.0),
            description=data.get("description", ""),
            category=data.get("category", ""),
        )

@dataclass
class TaskResult:
    # ... 기존 필드 ...

    def to_dict(self) -> dict:
        return {
            "task": self.task.to_dict(),
            "passed": self.passed,
            "actual_value": self.actual_value,
            "error_message": self.error_message,
            "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskResult:
        return cls(
            task=MetabolicTask.from_dict(data["task"]),
            passed=data["passed"],
            actual_value=data["actual_value"],
            error_message=data.get("error_message"),
            phase=data.get("phase", "before"),
        )
```

### 3.2 ProjectManager (`src/core/project_manager.py`)

#### 3.2.1 ProjectData

```python
from dataclasses import dataclass, field

@dataclass
class ProjectData:
    """Complete project state container for save/load."""

    format_version: str = "1.0"
    created_at: str = ""
    last_modified: str = ""

    # Model reference
    sbml_path: str = ""
    model_id: str = ""
    model_name: str = ""
    organism_code: str | None = None
    organism_name: str | None = None

    # Evaluation results (reaction_id → serialized ReactionEvidence)
    evaluation_results: dict[str, dict] = field(default_factory=dict)

    # Gap-fill state
    universal_path: str | None = None
    tasks_path: str | None = None
    task_results_before: list[dict] | None = None
    task_results_after: list[dict] | None = None

    # Version reference
    current_version_id: str | None = None
    version_dir: str | None = None

    # Settings snapshot (scoring weights only — API keys는 포함하지 않음)
    scoring_weights: dict[str, float] = field(default_factory=dict)

    # Runtime (not serialized)
    project_path: str | None = field(default=None, repr=False)
```

#### 3.2.2 ProjectManager 클래스

```python
import json
from datetime import datetime, timezone
from pathlib import Path

class ProjectManager:
    """Save/load project state as .gemp JSON files."""

    GEMP_EXTENSION = ".gemp"
    FORMAT_VERSION = "1.0"

    @staticmethod
    def save(path: str, project: ProjectData) -> None:
        """Save project to .gemp file."""
        project.last_modified = datetime.now(timezone.utc).isoformat()
        if not project.created_at:
            project.created_at = project.last_modified

        data = {
            "format_version": project.format_version,
            "created_at": project.created_at,
            "last_modified": project.last_modified,
            "model": {
                "sbml_path": project.sbml_path,
                "model_id": project.model_id,
                "model_name": project.model_name,
                "organism_code": project.organism_code,
                "organism_name": project.organism_name,
            },
            "evaluation": {
                "results": project.evaluation_results,
            },
            "gapfill": {
                "universal_path": project.universal_path,
                "tasks_path": project.tasks_path,
                "task_results_before": project.task_results_before,
                "task_results_after": project.task_results_after,
            },
            "version_info": {
                "current_version_id": project.current_version_id,
                "version_dir": project.version_dir,
            },
            "settings": {
                "scoring_weights": project.scoring_weights,
            },
        }
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def load(path: str) -> ProjectData:
        """Load project from .gemp file."""
        raw = json.loads(Path(path).read_text())

        model = raw.get("model", {})
        evaluation = raw.get("evaluation", {})
        gapfill = raw.get("gapfill", {})
        version_info = raw.get("version_info", {})
        settings = raw.get("settings", {})

        return ProjectData(
            format_version=raw.get("format_version", "1.0"),
            created_at=raw.get("created_at", ""),
            last_modified=raw.get("last_modified", ""),
            sbml_path=model.get("sbml_path", ""),
            model_id=model.get("model_id", ""),
            model_name=model.get("model_name", ""),
            organism_code=model.get("organism_code"),
            organism_name=model.get("organism_name"),
            evaluation_results=evaluation.get("results", {}),
            universal_path=gapfill.get("universal_path"),
            tasks_path=gapfill.get("tasks_path"),
            task_results_before=gapfill.get("task_results_before"),
            task_results_after=gapfill.get("task_results_after"),
            current_version_id=version_info.get("current_version_id"),
            version_dir=version_info.get("version_dir"),
            scoring_weights=settings.get("scoring_weights", {}),
            project_path=path,
        )

    @staticmethod
    def from_app_state(window) -> ProjectData:
        """Extract project data from MainWindow state."""
        # window: MainWindow (import 순환 방지를 위해 type hint 생략)
        ...

    @staticmethod
    def apply_to_app(project: ProjectData, window) -> None:
        """Apply loaded project data to MainWindow."""
        ...
```

#### 3.2.3 from_app_state 구현 상세

```python
@staticmethod
def from_app_state(window) -> ProjectData:
    model = window._model
    engine = window._engine
    vm = window._version_manager
    config = window._config

    # 평가 결과 수집
    eval_results: dict[str, dict] = {}
    if engine:
        for rid, ev in engine.get_all_results().items():
            eval_results[rid] = ev.to_dict()

    # Gap-fill task 결과
    task_before = None
    task_after = None
    task_panel = window._task_panel
    if hasattr(task_panel, "_before_map") and task_panel._before_map:
        task_before = [tr.to_dict() for tr in task_panel._before_map.values()]
    if hasattr(task_panel, "_after_map") and task_panel._after_map:
        task_after = [tr.to_dict() for tr in task_panel._after_map.values()]

    return ProjectData(
        sbml_path=getattr(window, "_loading_filepath", "") or "",
        model_id=model.id if model else "",
        model_name=model.name if model else "",
        organism_code=config.kegg_organism_code,
        organism_name=config.organism_name,
        evaluation_results=eval_results,
        universal_path=window._loaded_universal_path,
        tasks_path=getattr(window, "_loaded_tasks_path", None),
        task_results_before=task_before,
        task_results_after=task_after,
        current_version_id=(
            vm.current_version.version_id if vm and vm.current_version else None
        ),
        version_dir=config.version_dir or None,
        scoring_weights=config.weights,
    )
```

#### 3.2.4 apply_to_app 구현 상세

```python
@staticmethod
def apply_to_app(project: ProjectData, window) -> None:
    """Restore project state to MainWindow.

    Flow:
    1. SBML 모델 로딩 (기존 _load_model 활용)
    2. organism 설정 복원
    3. 평가 결과 복원 (engine._results에 주입)
    4. 버전 히스토리 복원
    5. Gap-fill task 결과 복원
    6. UI 업데이트
    """
    from pathlib import Path
    from src.core.models import ReactionEvidence

    # 1. SBML 파일 존재 확인
    sbml_path = project.sbml_path
    if not Path(sbml_path).exists():
        raise FileNotFoundError(f"SBML file not found: {sbml_path}")

    # 2. Organism 설정 복원 (모델 로드 시 다이얼로그 건너뛰기 위해)
    if project.organism_code:
        window._config.kegg_organism_code = project.organism_code
    if project.organism_name:
        window._config.organism_name = project.organism_name
    if project.scoring_weights:
        for key, val in project.scoring_weights.items():
            attr = f"weight_{key}"
            if hasattr(window._config, attr):
                setattr(window._config, attr, val)
    window._config.save()

    # 3. 모델 로드 (동기적 — _load_model_sync 사용)
    window._load_model_for_project(sbml_path, project)

    # 4~6은 _on_project_model_loaded 콜백에서 처리
```

### 3.3 MainWindow 수정 (`src/gui/main_window.py`)

#### 3.3.1 새 인스턴스 변수

```python
def __init__(self, config: Config) -> None:
    # ... 기존 ...
    self._project_path: str | None = None
    self._project_dirty: bool = False
    self._loading_filepath: str = ""       # 현재 로딩 중인 SBML 경로 (기존)
    self._loaded_tasks_path: str | None = None  # task 파일 경로 추적
```

#### 3.3.2 메뉴 변경

```python
def _setup_menu(self) -> None:
    menubar = self.menuBar()
    file_menu = menubar.addMenu("&File")

    file_menu.addAction("&Open Model...", self._open_model, "Ctrl+O")
    file_menu.addAction("Open &Project...", self._open_project, "Ctrl+Shift+O")
    self._recent_menu = file_menu.addMenu("Recent Models")
    self._recent_projects_menu = file_menu.addMenu("Recent Projects")
    self._update_recent_menu()
    self._update_recent_projects_menu()
    file_menu.addSeparator()

    file_menu.addAction("&Save Project", self._save_project, "Ctrl+S")
    file_menu.addAction("Save Project &As...", self._save_project_as)
    file_menu.addSeparator()

    # ... 기존 메뉴 항목들 ...
    # Export > CSV의 단축키 Ctrl+S 제거
```

#### 3.3.3 Save 메서드

```python
def _save_project(self) -> None:
    """Save project to current path, or prompt for path."""
    if self._project_path:
        self._do_save_project(self._project_path)
    else:
        self._save_project_as()

def _save_project_as(self) -> None:
    """Save project to a new path."""
    if not self._model:
        QMessageBox.warning(self, "Save Project", "No model loaded.")
        return

    path, _ = QFileDialog.getSaveFileName(
        self, "Save Project",
        f"{self._model.id}.gemp",
        "GEM Project (*.gemp)",
    )
    if path:
        self._do_save_project(path)

def _do_save_project(self, path: str) -> None:
    """Actual save logic."""
    from src.core.project_manager import ProjectManager

    project = ProjectManager.from_app_state(self)
    project.project_path = path
    ProjectManager.save(path, project)
    self._project_path = path
    self._project_dirty = False
    self._update_title()
    self._config.add_recent_project(path)
    self._config.save()
    self._update_recent_projects_menu()
    self._statusbar.showMessage(f"Project saved: {path}", 5000)
```

#### 3.3.4 Load 메서드

```python
def _open_project(self) -> None:
    """Open a .gemp project file."""
    path, _ = QFileDialog.getOpenFileName(
        self, "Open Project", "", "GEM Project (*.gemp)"
    )
    if path:
        self._load_project(path)

def _load_project(self, path: str) -> None:
    """Load project and restore state."""
    from src.core.project_manager import ProjectManager

    try:
        project = ProjectManager.load(path)
    except (json.JSONDecodeError, KeyError) as e:
        QMessageBox.critical(self, "Error", f"Invalid project file:\n{e}")
        return

    # SBML 파일 존재 확인
    if not Path(project.sbml_path).exists():
        # SBML 파일을 찾을 수 없으면 사용자에게 수동 지정 요청
        new_path, _ = QFileDialog.getOpenFileName(
            self, f"SBML file not found: {project.sbml_path}",
            "", "SBML Files (*.xml *.sbml)"
        )
        if not new_path:
            return
        project.sbml_path = new_path

    # 설정 복원
    if project.organism_code:
        self._config.kegg_organism_code = project.organism_code
    if project.organism_name:
        self._config.organism_name = project.organism_name
    if project.scoring_weights:
        for key, val in project.scoring_weights.items():
            attr = f"weight_{key}"
            if hasattr(self._config, attr):
                setattr(self._config, attr, val)
        self._config.save()
        self._init_engine()  # Reinit with restored weights

    # 모델 로드 (기존 _load_model 활용, but skip organism dialog)
    self._pending_project = project  # 임시 저장
    self._loading_filepath = project.sbml_path
    self._skip_organism_dialog = True
    self._load_model(project.sbml_path)

def _on_model_loaded(self, model: object) -> None:
    # ... 기존 로직 ...
    # 프로젝트 로드 후 평가 결과 복원
    pending = getattr(self, "_pending_project", None)
    if pending:
        self._restore_project_state(pending)
        self._pending_project = None
```

#### 3.3.5 상태 복원 메서드

```python
def _restore_project_state(self, project: ProjectData) -> None:
    """Restore evaluation results and gap-fill state from project."""
    from src.core.models import ReactionEvidence, TaskResult

    # 평가 결과 복원
    if self._engine and project.evaluation_results:
        for rid, ev_dict in project.evaluation_results.items():
            evidence = ReactionEvidence.from_dict(ev_dict)
            self._engine._results[rid] = evidence
        # UI 업데이트: 테이블에 결과 반영
        self._reaction_table.update_all_evidence(self._engine.get_all_results())
        self._overview.update_evaluation_count(
            len(project.evaluation_results),
            self._model.reaction_count if self._model else 0,
        )

    # Gap-fill task 결과 복원
    if project.task_results_before is not None:
        before = [TaskResult.from_dict(d) for d in project.task_results_before]
        after = (
            [TaskResult.from_dict(d) for d in project.task_results_after]
            if project.task_results_after
            else []
        )
        self._task_panel.set_results(before, after)

    # 경로 복원
    self._loaded_universal_path = project.universal_path
    self._loaded_tasks_path = project.tasks_path
    self._project_path = project.project_path
    self._project_dirty = False
    self._update_title()
```

#### 3.3.6 Dirty Flag 관리

```python
def _mark_dirty(self) -> None:
    """Mark project as having unsaved changes."""
    if not self._project_dirty:
        self._project_dirty = True
        self._update_title()

def _update_title(self) -> None:
    """Update window title with project name and dirty indicator."""
    title = f"{APP_NAME} v{APP_VERSION}"
    if self._model:
        title += f" — {self._model.id}"
    if self._project_path:
        title += f" [{Path(self._project_path).name}]"
    if self._project_dirty:
        title += " *"
    self.setWindowTitle(title)
```

**_mark_dirty 호출 시점**:
- `_on_evidence_result()` — 평가 결과 수신 시
- `_on_gap_fill_done()` — gap-fill 완료 시
- `_version_ctrl.save_version()` — 버전 생성 시
- `_on_reaction_removed()` — 반응 제거 시

#### 3.3.7 closeEvent 수정

```python
def closeEvent(self, event: QCloseEvent) -> None:
    if self._project_dirty and self._model:
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Save project before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Save:
            self._save_project()
        elif reply == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return

    # 기존 cleanup 로직
    if self._batch_worker:
        self._batch_worker.cancel()
    # ... 기존 engine close ...
    super().closeEvent(event)
```

### 3.4 Config 수정 (`src/utils/config.py`)

```python
@dataclass
class Config:
    # ... 기존 필드 ...

    # Project settings
    recent_projects: list[str] = field(default_factory=list)

    def add_recent_project(self, filepath: str) -> None:
        if filepath in self.recent_projects:
            self.recent_projects.remove(filepath)
        self.recent_projects.insert(0, filepath)
        self.recent_projects = self.recent_projects[:10]
```

## 4. Implementation Order

```
Step 1: models.py — to_dict()/from_dict() 추가
  1a: EvidenceItem.to_dict() / from_dict()
  1b: ReactionEvidence.to_dict() / from_dict()
  1c: MetabolicTask.to_dict() / from_dict()
  1d: TaskResult.to_dict() / from_dict()

Step 2: config.py — recent_projects, add_recent_project() 추가

Step 3: project_manager.py — 신규 생성
  3a: ProjectData dataclass
  3b: ProjectManager.save() / load()
  3c: ProjectManager.from_app_state()

Step 4: main_window.py — 메뉴 + save/load + dirty flag
  4a: 메뉴 항목 추가 (Open Project, Save Project, Recent Projects)
  4b: _save_project / _save_project_as / _do_save_project
  4c: _open_project / _load_project
  4d: _restore_project_state
  4e: _mark_dirty / _update_title
  4f: closeEvent 수정
  4g: _skip_organism_dialog 처리 in _on_model_loaded

Step 5: tests/test_project_manager.py — 테스트 추가
```

## 5. Test Specifications

| 테스트 | 설명 | 검증 |
|--------|------|------|
| `test_evidence_item_to_dict` | EvidenceItem 직렬화 | dict 필드 정확성 |
| `test_evidence_item_from_dict` | EvidenceItem 역직렬화 | 원본 복원 |
| `test_evidence_roundtrip` | ReactionEvidence 왕복 | to_dict→from_dict 일치 |
| `test_task_result_roundtrip` | TaskResult 왕복 | to_dict→from_dict 일치 |
| `test_project_data_creation` | ProjectData 기본 생성 | format_version="1.0" |
| `test_save_and_load_roundtrip` | 저장→로딩 왕복 | 모든 필드 일치 |
| `test_load_missing_sbml_path` | 존재하지 않는 SBML 경로 | sbml_path 포함, 로딩 자체는 성공 |
| `test_load_invalid_json` | 잘못된 JSON | json.JSONDecodeError 발생 |
| `test_config_recent_projects` | recent_projects 추가/관리 | 최대 10개, 중복 제거 |
| `test_dirty_flag_initial` | 초기 dirty=False | False 확인 |

## 6. Edge Cases

| 케이스 | 처리 |
|--------|------|
| SBML 원본 파일 이동/삭제 | 로딩 시 경고 + QFileDialog로 수동 재지정 |
| 평가 결과 없이 저장 | evaluation.results = {} (빈 dict) |
| EvidenceEngine 미초기화 상태 | from_app_state에서 빈 결과 반환 |
| 구버전 format_version | format_version 체크 후 필드 기본값 적용 |
| 프로젝트 없이 Ctrl+S | "No model loaded" 경고 |
| 동일 파일 중복 저장 | 기존 파일 덮어쓰기 (JSON이므로 안전) |
| cobra_model 없는 상태 | 버전 관리 비활성, 다른 기능은 정상 |

## 7. Dependencies

- 추가 패키지 불필요 (json 표준 라이브러리만 사용)
