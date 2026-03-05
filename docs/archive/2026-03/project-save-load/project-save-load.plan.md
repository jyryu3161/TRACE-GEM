# Plan: Project Save/Load

## 1. Overview

프로젝트 단위로 모델 + 평가 결과 + 버전 히스토리 + gap-fill 상태를 한 번에 저장하고, 다시 불러와서 이전 분석을 이어서 할 수 있는 기능을 추가한다.

**핵심 가치**: 사용자가 SBML 모델을 로드하고 evidence 평가를 진행한 후 앱을 닫았다 다시 열었을 때, 이전 분석 상태를 그대로 복원하여 이어서 작업할 수 있다.

## 2. 현재 상태 분석

### 저장되는 것
- 버전 히스토리: `~/.gem_evaluator/versions/{model_id}/` (이미 파일시스템에 저장)
- 설정: `~/.gem_evaluator/config.json`
- API 캐시: `~/.gem_evaluator/cache.db` (SQLite)
- 최근 파일 목록: `config.recent_files`

### 저장되지 않는 것 (앱 종료 시 소실)
- **평가 결과** (`EvidenceEngine._results`): 모든 `ReactionEvidence` 객체 (in-memory dict)
- **Gap-fill 체크포인트** (`WorkflowCheckpoint`): 진행 중인 gap-fill 상태
- **Task 결과** (`TaskPanel._before_map`, `_after_map`): gap-fill 전후 비교 데이터
- **Universal 모델 경로** (`_loaded_universal_path`)
- **로드된 Task 목록** (`_loaded_tasks`)
- **모델-설정 연관** (어떤 모델에 어떤 organism code를 사용했는지)

## 3. 요구사항

### FR-01: 프로젝트 저장 (Save Project)
- File 메뉴에 "Save Project" (Ctrl+S) 및 "Save Project As..." (Ctrl+Shift+S) 추가
- `.gemp` (GEM Project) 확장자로 JSON 파일 저장
- 저장 내용: 모델 SBML 경로, 평가 결과, organism 설정, scoring weights, gap-fill 상태
- 버전 히스토리는 기존 `~/.gem_evaluator/versions/` 경로 참조만 저장 (복사 안 함)

### FR-02: 프로젝트 로딩 (Load Project)
- File 메뉴에 "Open Project..." 추가
- `.gemp` 파일을 열면 모델 + 평가 결과 + 설정을 한 번에 복원
- 복원 후 UI는 저장 시점과 동일한 상태
- 최근 프로젝트 목록 유지 (recent_projects, 최근 SBML과 별도)

### FR-03: 자동 저장 (Auto-save)
- 평가 완료 시 자동으로 프로젝트 저장 (설정으로 on/off)
- 앱 종료 시 변경사항 있으면 저장 확인 대화상자

### FR-04: 프로젝트 파일 포맷
- JSON 기반 `.gemp` 파일 (사람이 읽을 수 있는 형식)
- SBML 모델은 원본 파일 경로 참조 (복사 안 함 — 파일이 크므로)
- 평가 결과는 프로젝트 파일에 직접 포함

## 4. 범위

### In Scope
| 항목 | 설명 |
|------|------|
| ProjectData dataclass | 프로젝트 상태를 담는 데이터 모델 |
| ProjectManager | 저장/로딩 로직 담당 클래스 |
| .gemp 파일 포맷 | JSON 기반 프로젝트 파일 |
| File 메뉴 연동 | Save/Load/Recent Projects |
| 평가 결과 직렬화 | ReactionEvidence → JSON 변환 |
| Gap-fill 상태 저장 | WorkflowCheckpoint 직렬화 |
| 종료 시 저장 확인 | 변경 감지 + 대화상자 |

### Out of Scope
| 항목 | 이유 |
|------|------|
| SBML 파일 임베딩 | 모델 파일이 크므로 경로 참조만 |
| 버전 파일 복사 | 이미 filesystem에 저장됨 |
| UI 레이아웃 저장 | 복잡도 대비 가치 낮음 |
| 프로젝트 병합 | 단일 모델 워크플로우에서 불필요 |
| 캐시 파일 포함 | 재생성 가능하므로 불필요 |

## 5. 기술 접근

### 5.1 프로젝트 파일 구조 (`.gemp`)

```json
{
  "format_version": "1.0",
  "created_at": "2026-03-05T10:00:00Z",
  "last_modified": "2026-03-05T14:30:00Z",
  "model": {
    "sbml_path": "/path/to/ecoli_core.xml",
    "model_id": "e_coli_core",
    "model_name": "E. coli Core Model",
    "organism_code": "eco",
    "organism_name": "Escherichia coli"
  },
  "evaluation": {
    "completed_count": 95,
    "total_count": 100,
    "results": {
      "PFK": {
        "status": "evaluated",
        "confidence_score": 0.85,
        "kegg_score": 0.9,
        "bigg_score": 0.8,
        "items": [...]
      }
    }
  },
  "gapfill": {
    "universal_path": "/path/to/bigg_universal_model_fixed.json",
    "tasks_path": "/path/to/universal_essential_tasks.csv",
    "checkpoint": null,
    "task_results_before": [...],
    "task_results_after": [...]
  },
  "settings": {
    "scoring_weights": {"kegg": 0.30, "bigg": 0.15, ...}
  },
  "version_info": {
    "current_version_id": "v003",
    "version_dir": "~/.gem_evaluator/versions/e_coli_core"
  }
}
```

### 5.2 주요 클래스

```python
# src/core/project_manager.py (신규)

@dataclass
class ProjectData:
    """프로젝트 전체 상태를 담는 컨테이너."""
    format_version: str
    created_at: str
    last_modified: str
    sbml_path: str
    model_id: str
    model_name: str
    organism_code: str | None
    organism_name: str | None
    evaluation_results: dict[str, dict]  # reaction_id → serialized ReactionEvidence
    gapfill_state: dict | None           # serialized gap-fill state
    settings: dict                        # scoring weights 등
    version_info: dict                    # current_version_id, version_dir
    project_path: str | None             # 저장된 .gemp 경로

class ProjectManager:
    """프로젝트 저장/로딩 담당."""

    def save(self, path: str, project: ProjectData) -> None: ...
    def load(self, path: str) -> ProjectData: ...

    @staticmethod
    def from_app_state(main_window) -> ProjectData: ...
    @staticmethod
    def to_app_state(project: ProjectData, main_window) -> None: ...
```

### 5.3 직렬화 전략

| 데이터 | 직렬화 방법 |
|--------|------------|
| ReactionEvidence | dataclass → dict (재귀적 변환) |
| EvidenceItem | dataclass → dict |
| EvidenceStrength (Enum) | `.value` (float) |
| EvidenceSource (Enum) | `.value` (str) |
| WorkflowCheckpoint | dataclass → dict |
| TaskResult | dataclass → dict |
| CandidateReaction | dataclass → dict |
| ModelVersion | 기존 version_manager에서 이미 JSON 저장 → 참조만 |

### 5.4 변경 감지 (Dirty Flag)

```python
# MainWindow에 추가
self._project_dirty: bool = False
self._project_path: str | None = None

# 변경 발생하는 시점:
# - 평가 결과 수신 시
# - gap-fill 실행/완료 시
# - 버전 생성 시
# - 설정 변경 시
```

### 5.5 File 메뉴 변경

```
File
├─ Open Model...          (Ctrl+O)     ← 기존
├─ Open Project...        (Ctrl+Shift+O) ← 신규
├─ ─────────────
├─ Save Project           (Ctrl+S)     ← 신규
├─ Save Project As...                  ← 신규
├─ ─────────────
├─ Recent Models >                     ← 기존 (이름 변경)
├─ Recent Projects >                   ← 신규
├─ ─────────────
├─ Load Universal Model...             ← 기존
├─ Load Metabolic Tasks...             ← 기존
├─ Save Version...        (Ctrl+Shift+S → Ctrl+Alt+S로 변경)
├─ ─────────────
└─ Exit
```

## 6. 수정 파일

| 파일 | 변경 유형 | 설명 |
|------|-----------|----|
| `src/core/project_manager.py` | **신규** | ProjectData, ProjectManager 클래스 |
| `src/core/models.py` | 수정 | `to_dict()` / `from_dict()` 메서드 추가 (ReactionEvidence, EvidenceItem 등) |
| `src/gui/main_window.py` | 수정 | File 메뉴, save/load 액션, dirty flag, closeEvent |
| `src/utils/config.py` | 수정 | `recent_projects`, `auto_save_project` 설정 추가 |
| `tests/test_project_manager.py` | **신규** | 저장/로딩/직렬화 테스트 |

## 7. 의존성

- 추가 패키지 불필요 (json 표준 라이브러리만 사용)

## 8. 테스트 전략

| 테스트 | 설명 |
|--------|------|
| `test_project_data_creation` | ProjectData 기본 생성 |
| `test_save_and_load_roundtrip` | 저장 → 로딩 후 데이터 일치 확인 |
| `test_evidence_serialization` | ReactionEvidence ↔ dict 왕복 변환 |
| `test_evidence_item_serialization` | EvidenceItem ↔ dict 변환 |
| `test_gapfill_state_serialization` | WorkflowCheckpoint/TaskResult 직렬화 |
| `test_load_missing_sbml` | SBML 파일이 없을 때 에러 처리 |
| `test_load_old_format_version` | 구버전 포맷 호환성 |
| `test_dirty_flag` | 변경 감지 동작 확인 |

## 9. 리스크

| 리스크 | 대응 |
|--------|------|
| SBML 원본 파일 이동/삭제 시 | 로딩 시 경고 + 수동 SBML 재지정 UI |
| 프로젝트 파일 크기 (대형 모델) | 평가 결과만 포함, SBML은 참조만 (~1-5MB) |
| dataclass 직렬화 복잡도 | `to_dict()`/`from_dict()` 패턴 통일 |
| Enum 역직렬화 | `EvidenceSource(value)` 패턴 사용 |
| 포맷 버전 호환 | `format_version` 필드로 마이그레이션 가능 |
