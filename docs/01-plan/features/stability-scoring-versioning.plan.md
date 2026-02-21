# Plan: Stability, Score-Based Gap-Fill, Version Control

---

## 1. 개요

3가지 독립적이지만 연관된 개선을 수행한다:

1. **앱 안정성** — 모델 로드 시 크래시 수정 (에러 핸들링 강화)
2. **Score-Based Gap-Fill 우선순위** — Evidence score가 gap-filling 반응 선택에 반영
3. **버전 컨트롤 & QC** — 모델 변경 이력 추적, LLM 기반 변경 요약, 복구, 저장 시 Metabolic Task QC

---

## 2. Issue 1: 앱 안정성 (크래시 수정)

### 2.1 원인 분석

디버깅 결과 확인된 문제:
- `InitEngineWorker`에서 signal이 emit되기 전에 Worker 객체가 GC됨 → `RuntimeError: Signal source has been deleted`
- 대형 SBML 모델 로드 시 COBRApy 경고가 stderr로 출력되며 예외 발생 가능
- `Perplexity` 초기화 시 `atexit` 에러 (`can't register atexit after shutdown`)
- Gemini `google.genai` import 실패 시 cascade 에러

### 2.2 수정 방안

| 파일 | 수정 |
|------|------|
| `src/gui/workers.py` | Worker 시그널 emit을 try/except RuntimeError로 감싸기 |
| `src/gui/main_window.py` | `_active_worker` 외에 모든 worker를 리스트로 관리하여 GC 방지 |
| `src/gui/main_window.py` | 모델 로드 에러 시 상세 traceback을 QMessageBox로 표시 |
| `src/evidence/engine.py` | Perplexity/Gemini 초기화 실패 시 graceful skip (경고만) |
| `src/core/sbml_parser.py` | COBRApy 경고를 logging으로 redirect, 예외 catch 강화 |

---

## 3. Issue 2: Score-Based Gap-Fill 우선순위

### 3.1 현재 상태

현재 `PenaltyCalculator`가 이미 evidence score를 penalty로 변환하고 있음:
```
penalty = 1.0 / (confidence_score + 0.01)
```

그러나 이 penalty가 COBRApy `gapfill()`에 전달되는 방식을 검증하고, 사용자에게 우선순위가 시각적으로 보이도록 해야 함.

### 3.2 수정 방안

| 항목 | 수정 |
|------|------|
| `src/gapfill/engine.py` | Gap-fill 실행 전에 반드시 `PenaltyCalculator.calculate_batch()` 호출하여 penalties dict 생성 → `cobra.flux_analysis.gapfill(penalties=penalties)` 전달 확인 |
| `src/gapfill/engine.py` | 후보 반응을 evidence score 순으로 정렬하여 Gap-fill 결과에서 고점수 반응이 먼저 표시 |
| `src/gui/candidate_table.py` | Score 컬럼 기본 내림차순 정렬 |
| `src/gui/gapfill_panel.py` | 추가된 반응을 Score 내림차순으로 표시, "Evidence Score" 컬럼 강조 |
| `src/cli.py` | Gap-fill 결과 출력 시 Score 순 정렬 |

### 3.3 Penalty → 우선순위 흐름 확인

```
Evidence 평가 → confidence_score (0.0~1.0)
       │
       ▼
PenaltyCalculator.calculate()
  → penalty = 1.0 / (score + 0.01)
  → 종 미존재: × 10
  → KEGG 미매칭: × 2
  → cap at 1000.0
       │
       ▼
cobra.flux_analysis.gapfill(penalties={rxn_id: penalty})
  → LP solver가 penalty 합이 최소인 반응 조합 선택
  → 높은 score (낮은 penalty) 반응이 우선 선택됨 ✅
```

---

## 4. Issue 3: 버전 컨트롤 & QC

### 4.1 기능 요약

| 기능 | 설명 |
|------|------|
| **자동 저장/임시저장** | 모델 변경 시 자동으로 스냅샷 저장 |
| **변경 이력** | 각 스냅샷에 LLM이 생성한 변경 요약 첨부 |
| **버전 비교** | 두 버전 간 diff (추가/제거/수정된 반응, 유전자, bounds) |
| **복구** | 이전 버전으로 롤백 |
| **저장 시 QC** | 저장 전 metabolic task 평가 실행 여부를 묻고, task pass/fail 결과를 버전 메타데이터에 포함 |

### 4.2 데이터 모델

```python
@dataclass
class ModelVersion:
    """단일 모델 버전 스냅샷."""
    version_id: str                    # UUID or sequential
    timestamp: str                     # ISO 8601
    parent_version_id: str | None      # 이전 버전 (None = 초기)
    model_id: str                      # SBML model ID
    description: str                   # LLM이 생성한 변경 요약
    change_type: str                   # "initial_load", "manual_edit", "gap_fill", "restore"
    changes: ModelDiff                 # 상세 diff
    task_results: list[TaskResult] | None  # QC 결과 (선택)
    sbml_path: str                     # 저장된 SBML 파일 경로

@dataclass
class ModelDiff:
    """두 모델 버전 간 차이."""
    reactions_added: list[str]         # 추가된 반응 ID
    reactions_removed: list[str]       # 제거된 반응 ID
    reactions_modified: list[ReactionChange]  # bounds/GPR 변경
    genes_added: list[str]
    genes_removed: list[str]
    metabolites_added: list[str]
    metabolites_removed: list[str]

@dataclass
class ReactionChange:
    """단일 반응의 변경 내용."""
    reaction_id: str
    field: str                         # "lower_bound", "upper_bound", "gene_reaction_rule", etc.
    old_value: str
    new_value: str
```

### 4.3 신규 모듈

```
src/
├── versioning/
│   ├── __init__.py
│   ├── version_manager.py     # 버전 관리 (저장, 비교, 복구)
│   ├── diff_engine.py         # 두 cobra.Model 비교 → ModelDiff
│   ├── change_summarizer.py   # LLM 기반 변경 요약 생성
│   └── storage.py             # 버전 스냅샷 파일 시스템 관리
├── gui/
│   ├── version_panel.py       # 버전 히스토리 패널 (타임라인 뷰)
│   ├── diff_dialog.py         # 두 버전 비교 다이얼로그
│   └── save_dialog.py         # 저장 다이얼로그 (QC 옵션 포함)
```

### 4.4 VersionManager 동작 흐름

```
[사용자가 모델 수정]
       │
       ▼
┌──────────────────────────────────────────────────────┐
│ 1. DiffEngine.compute_diff(old_model, new_model)     │
│    → ModelDiff (추가/제거/수정된 반응 등)               │
│                                                      │
│ 2. ChangeSummarizer.summarize(diff, change_type)     │
│    → LLM에게 diff 전달 → 자연어 요약 생성             │
│    예: "Gap-filling으로 23개 반응 추가 (글루타민         │
│         합성, PRPP 합성 등). 13개 metabolic task 수정." │
│                                                      │
│ 3. SaveDialog (선택)                                  │
│    → "Metabolic task QC를 실행할까요?"                 │
│    → Yes: TaskRunner.run_all() → task_results        │
│    → No: task_results = None                         │
│                                                      │
│ 4. VersionManager.save_version(                      │
│        model, diff, description, task_results)       │
│    → SBML 파일 저장                                   │
│    → 메타데이터 JSON 저장                              │
│    → 버전 히스토리 업데이트                             │
└──────────────────────────────────────────────────────┘
```

### 4.5 저장 구조

```
~/.gem_evaluator/versions/{model_id}/
├── history.json               # 버전 히스토리 인덱스
├── v001/
│   ├── model.xml              # SBML 스냅샷
│   └── meta.json              # {version_id, timestamp, description, changes, task_results}
├── v002/
│   ├── model.xml
│   └── meta.json
└── ...
```

**history.json** 구조:
```json
{
  "model_id": "iJO1366",
  "versions": [
    {
      "version_id": "v001",
      "timestamp": "2026-02-21T09:30:00Z",
      "description": "Initial model load",
      "change_type": "initial_load",
      "task_pass_rate": "35/52"
    },
    {
      "version_id": "v002",
      "timestamp": "2026-02-21T10:15:00Z",
      "description": "Gap-filling: 23 reactions added, 13 tasks fixed",
      "change_type": "gap_fill",
      "task_pass_rate": "48/52"
    }
  ],
  "current_version": "v002"
}
```

### 4.6 GUI 통합

**SaveDialog** (저장 시):
```
┌──────────────────────────────────────────────┐
│  Save Model                                  │
├──────────────────────────────────────────────┤
│                                              │
│  Version Description:                        │
│  ┌──────────────────────────────────────┐    │
│  │ Gap-filling: 23 reactions added,     │    │
│  │ 13 metabolic tasks fixed.            │    │ ← LLM 자동 생성, 편집 가능
│  └──────────────────────────────────────┘    │
│                                              │
│  ☑ Run Metabolic Task QC before saving       │
│  ☐ Save as SBML file (export copy)           │
│                                              │
│  Previous QC: 35/52 passed                   │
│                                              │
│         [Cancel]  [Save Version]              │
└──────────────────────────────────────────────┘
```

**VersionPanel** (히스토리 탭):
```
┌────────────────────────────────────────────────┐
│  Version History                                │
├────────────────────────────────────────────────┤
│                                                │
│  ● v003 (current) — 2026-02-21 10:30           │
│  │  "Manual edit: PFK bounds adjusted"          │
│  │  QC: 48/52 passed                           │
│  │  [Compare] [Restore]                        │
│  │                                              │
│  ● v002 — 2026-02-21 10:15                     │
│  │  "Gap-fill: 23 reactions, 13 tasks fixed"    │
│  │  QC: 48/52 passed                           │
│  │  [Compare] [Restore]                        │
│  │                                              │
│  ● v001 — 2026-02-21 09:30                     │
│     "Initial model load"                        │
│     QC: 35/52 passed                           │
│     [Compare]                                  │
│                                                │
│  [Export Selected Version]                     │
└────────────────────────────────────────────────┘
```

### 4.7 LLM 변경 요약 생성

`ChangeSummarizer`는 기존 Gemini/Perplexity 클라이언트를 재활용:

```python
async def summarize(self, diff: ModelDiff, change_type: str) -> str:
    """ModelDiff를 LLM에게 전달하여 자연어 요약 생성."""
    prompt = f"""
    The following changes were made to a genome-scale metabolic model ({change_type}):
    - Reactions added: {len(diff.reactions_added)} ({', '.join(diff.reactions_added[:5])}...)
    - Reactions removed: {len(diff.reactions_removed)}
    - Reactions modified: {len(diff.reactions_modified)}
    - Genes added: {len(diff.genes_added)}

    Summarize these changes in 1-2 sentences for version history.
    """
    # Gemini API 호출 (기존 클라이언트 재활용)
    # fallback: LLM 없으면 자동 생성 템플릿 사용
```

---

## 5. 구현 단계

### Phase A: 안정성 수정 (긴급)
| Task | 파일 | 설명 |
|------|------|------|
| A-1 | `src/gui/workers.py` | 모든 Worker의 signal emit을 `try/except RuntimeError`로 보호 |
| A-2 | `src/gui/main_window.py` | Worker 리스트 관리로 GC 방지, 에러 핸들링 강화 |
| A-3 | `src/evidence/engine.py` | Gemini/Perplexity 초기화 실패 시 graceful skip |
| A-4 | `src/core/sbml_parser.py` | COBRApy 경고 redirect, 대형 모델 에러 catch |

### Phase B: Score-Based Gap-Fill 검증/개선
| Task | 파일 | 설명 |
|------|------|------|
| B-1 | `src/gapfill/engine.py` | penalty dict 전달 경로 검증, score 순 정렬 |
| B-2 | `src/gui/candidate_table.py` | Score 기본 내림차순 |
| B-3 | `src/gui/gapfill_panel.py` | Score 순 표시, 하이라이트 |

### Phase C: 버전 컨트롤 시스템 (신규)
| Task | 파일 | 설명 |
|------|------|------|
| C-1 | `src/core/models.py` | ModelVersion, ModelDiff, ReactionChange 추가 |
| C-2 | `src/versioning/storage.py` | 파일 시스템 저장/로드 |
| C-3 | `src/versioning/diff_engine.py` | cobra.Model 비교 → ModelDiff |
| C-4 | `src/versioning/version_manager.py` | 버전 관리 오케스트레이터 |
| C-5 | `src/versioning/change_summarizer.py` | LLM 기반 변경 요약 |
| C-6 | `src/gui/save_dialog.py` | 저장 다이얼로그 + QC 옵션 |
| C-7 | `src/gui/version_panel.py` | 버전 히스토리 타임라인 |
| C-8 | `src/gui/diff_dialog.py` | 버전 비교 다이얼로그 |
| C-9 | `src/gui/main_window.py` | Version 탭, Save 메뉴 연동 |
| C-10 | Tests | 전체 테스트 |

### 의존성

```
Phase A (안정성) ← 독립, 즉시 시작
Phase B (Score Gap-Fill) ← 독립, 즉시 시작
Phase C (버전 컨트롤) ← A, B 완료 후 (안정성 확보 필요)
  C-1 → C-2, C-3 (병렬) → C-4 → C-5 → C-6~C-9 (병렬)
```

---

## 6. 리스크

| 리스크 | 완화 |
|--------|------|
| 대형 모델 SBML 저장 시 디스크 공간 | 최대 버전 수 제한 (기본 20), 오래된 버전 자동 정리 |
| LLM API 없을 때 요약 불가 | 자동 생성 템플릿 fallback: "Added N reactions, removed M reactions" |
| cobra.Model 비교 성능 | Reaction ID 기준 set diff → O(n), 대형 모델도 <1초 |

---

*Plan created: 2026-02-21*
*Feature: stability-scoring-versioning*
*PDCA Phase: Plan*
