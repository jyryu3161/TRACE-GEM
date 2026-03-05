# Plan: Workflow Resume & Universal Model Browser

---

## 1. 개요

2가지 사용성 개선:

1. **Gap-Fill Workflow Cancel Recovery & Resume** — Cancel 시 분석 완료된 부분까지 보여주고, 다음 실행 시 이어서 진행
2. **Universal Model Browser** — Universal 모델 반응을 Model Overview처럼 개별 조회 + evidence score 확인

---

## 2. Feature 1: Gap-Fill Cancel Recovery & Resume

### 2.1 현재 문제

- `GapFillWorkflowWorker`에 취소 메커니즘 없음 (cancel() 호출해도 no-op)
- Cancel 시 진행된 분석 결과(Phase 1 task 테스트, Phase 2 organism 필터링 등)가 모두 버려짐
- 다음 실행 시 처음부터 다시 시작해야 함

### 2.2 목표

| 목표 | 설명 |
|------|------|
| **Cancel 시 partial result 표시** | 어느 Phase까지 완료됐든 그 시점의 결과를 UI에 표시 |
| **Resume 기능** | 다음 Workflow 실행 시 이전 partial result를 로드하여 미완료 Phase부터 이어서 진행 |

### 2.3 5-Phase Pipeline & Partial Results

```
Phase 1: testing_before  → task_results_before (TaskResult 리스트)
Phase 2: filtering        → candidates에 organism_exists 플래그 세팅
Phase 3: gap_filling      → added_reactions (선택된 후보 반응)
Phase 4: assigning_gpr    → added_reactions에 GPR 할당
Phase 5: testing_after    → task_results_after
```

각 Phase 완료 시 `GapFillResult`의 해당 필드가 채워지며, 중간에 Cancel되면 채워진 필드까지만 유효.

### 2.4 Cancel Recovery 설계

#### 2.4.1 Worker 취소 메커니즘

```python
class GapFillWorkflowWorker(QRunnable):
    def cancel(self) -> None:
        self._cancel_event.set()  # asyncio.Event 플래그

    def _run_pipeline(self):
        # 각 Phase 시작 전 cancel 체크
        if self._cancel_event.is_set():
            return partial_result

        # Phase 실행
        result.task_results_before = self._engine.run_tasks(phase="before")

        if self._cancel_event.is_set():
            return partial_result  # Phase 1까지의 결과

        # ... 이하 동일 패턴
```

#### 2.4.2 Partial Result Signal

```python
class GapFillWorkerSignals(QObject):
    result = Signal(GapFillResult)           # 기존: 완료 시
    partial_result = Signal(GapFillResult, int)  # 신규: (부분결과, 완료된_phase_번호)
    cancelled = Signal(GapFillResult, int)       # 신규: cancel 시 partial result 전달
```

#### 2.4.3 GapFillResult 확장

```python
@dataclass
class GapFillResult:
    # 기존 필드
    added_reactions: list[CandidateReaction] = ...
    task_results_before: list[TaskResult] = ...
    task_results_after: list[TaskResult] = ...
    tasks_fixed: int = 0
    total_tasks: int = 0
    iterations: int = 0
    infeasible_tasks: list[str] = ...

    # 신규 필드
    completed_phase: int = 0          # 0~5, 완료된 Phase 번호
    all_candidates: list[CandidateReaction] = ...  # 전체 후보 (Phase 2 결과 포함)
    is_partial: bool = False          # Cancel로 인한 부분 결과인지
```

#### 2.4.4 UI 처리 (main_window.py)

Cancel 시:
1. partial result 수신
2. `completed_phase`에 따라 해당 탭 업데이트:
   - Phase ≥ 1: Task Panel에 before 결과 표시
   - Phase ≥ 2: Candidate Table에 organism 필터링된 후보 표시
   - Phase ≥ 3: Gap-Fill Panel에 added reactions 표시
   - Phase ≥ 4: GPR 할당 결과 반영
3. 상태바에 "Workflow cancelled at Phase {N}" 표시
4. Gap-Fill Panel 상단에 "Partial result — Resume available" 배너

### 2.5 Resume 설계

#### 2.5.1 Checkpoint 저장

Cancel 또는 완료 시 checkpoint를 메모리에 보관:

```python
@dataclass
class WorkflowCheckpoint:
    """Gap-fill workflow 중단점."""
    completed_phase: int              # 완료된 Phase (0~5)
    result: GapFillResult             # 부분 결과
    candidates: list[CandidateReaction]  # Phase 2까지 처리된 전체 후보
    universal_model: cobra.Model | None  # 로드된 universal model
    tasks: list[MetabolicTask]        # 파싱된 metabolic tasks
    organism_code: str                # 종 코드
    timestamp: str                    # ISO 8601
```

- `MainWindow`에 `_workflow_checkpoint: WorkflowCheckpoint | None` 필드 추가
- Cancel 시 checkpoint 저장
- 새 모델 로드 시 checkpoint 초기화

#### 2.5.2 Resume Workflow

다음 `Start Workflow...` 실행 시:
1. checkpoint가 있으면 "이전 분석을 이어서 진행하시겠습니까?" 다이얼로그 표시
2. Resume 선택 시:
   - WorkflowWizard 스킵 (이전 설정 재활용)
   - `completed_phase + 1`부터 pipeline 재개
3. "새로 시작" 선택 시:
   - checkpoint 삭제
   - 정상 WorkflowWizard 진행

#### 2.5.3 GapFillEngine 수정

```python
class GapFillEngine:
    async def run(
        self,
        ...,
        cancel_event: asyncio.Event | None = None,
        start_phase: int = 1,              # 신규: 시작 Phase
        preloaded_candidates: list | None = None,  # 신규: 이전 후보
        preloaded_before: list | None = None,       # 신규: 이전 before 결과
    ) -> GapFillResult:
```

---

## 3. Feature 2: Universal Model Browser

### 3.1 현재 상태

- Universal 모델은 gap-fill workflow 내에서만 로딩됨 (`UniversalLoader`)
- 로드 후 `extract_candidates()`로 후보만 추출 → 개별 반응 상세 조회 불가
- 사용자가 universal 반응의 evidence score를 사전에 확인할 방법 없음

### 3.2 목표

| 목표 | 설명 |
|------|------|
| **Universal 반응 테이블** | Model Overview 옆에 "Universal Reactions" 탭 추가 |
| **Evidence 평가** | 개별 반응 선택 후 evidence score 확인 가능 |
| **상세 보기** | 반응 클릭 시 detail panel에 equation, annotation, cross-reference 표시 |
| **Score 정렬/필터** | 기존 reaction_table과 동일한 Score 정렬, 필터 기능 |

### 3.3 UI 레이아웃

```
┌─────────────────────────────────────────────────────────────────┐
│ Left Panel                          │ Right Panel               │
├─────────────────────────────────────┤                           │
│ [Model Reactions] [Candidates]      │ [Overview] [Evidence] ... │
│   [Universal ▼]  ← 새 탭           │                           │
│                                     │                           │
│ ┌─────────────────────────────────┐ │                           │
│ │ Universal Model: bigg_universal │ │                           │
│ │ Reactions: 28,301              │ │                           │
│ │ (excluded: 1,366 model + 842   │ │                           │
│ │  exchange = 26,093 candidates) │ │                           │
│ ├─────────────────────────────────┤ │                           │
│ │ Filter: [________] [Subsystem▼]│ │                           │
│ │ Score:  [0.0 ━━━━━━━━━━ 1.0]  │ │                           │
│ ├─────────────────────────────────┤ │                           │
│ │ ID   │ Name  │ Score │ Org │   │ │                           │
│ │ GLNS │ Glut..│ 0.85  │ ✅  │   │ │                           │
│ │ PFK2 │ 6-Ph..│ 0.72  │ ❌  │   │ │                           │
│ │ ...  │       │       │     │   │ │                           │
│ └─────────────────────────────────┘ │                           │
└─────────────────────────────────────┴───────────────────────────┘
```

### 3.4 구현 방안

#### 3.4.1 Universal Reactions 탭 (좌측)

기존 `CandidateTableWidget`을 재활용하되, 독립적으로 universal 반응을 표시:

- Universal 모델 로드: `File → Load Universal Model...` 메뉴 추가
- 또는 Workflow Wizard에서 로드한 universal을 자동으로 탭에 표시
- 반응 클릭 시 right panel의 detail 영역에 정보 표시

#### 3.4.2 Evidence 평가 통합

- "Evaluate Selected" 또는 "Evaluate All" 버튼
- 기존 `EvidenceEngine.evaluate_candidate()` 재활용
- `EvaluateCandidatesWorker`로 비동기 처리
- Score가 테이블에 실시간 업데이트

#### 3.4.3 Universal Reaction Detail

기존 `ReactionDetailWidget`은 model reaction용이므로 편집 기능이 포함되어 있음.
Universal 반응은 **읽기 전용** detail panel을 표시:

- Reaction ID, Name, Equation
- Subsystem, Bounds
- Annotations (KEGG, EC, MetaNetX 등)
- Evidence Score (평가 시)
- Organism Exists 여부 (필터링 후)

→ 기존 `ReactionDetailWidget`에 `read_only` 모드 추가로 구현.

#### 3.4.4 Universal Model Overview

탭 상단에 요약 정보:

```python
# 표시 항목:
- Universal Model ID (예: "bigg_universal")
- Total reactions
- Excluded (model 중복 + exchange)
- Available candidates
- Evaluated count / Total
```

---

## 4. 구현 단계

### Phase A: Cancel Recovery (필수)

| Task | 파일 | 설명 |
|------|------|------|
| A-1 | `src/core/models.py` | `GapFillResult`에 `completed_phase`, `all_candidates`, `is_partial` 추가. `WorkflowCheckpoint` dataclass 추가 |
| A-2 | `src/gapfill/engine.py` | `run()`에 `cancel_event`, `start_phase`, preloaded 파라미터 추가. 각 Phase 전 cancel 체크 |
| A-3 | `src/gui/workers.py` | `GapFillWorkflowWorker`에 `_cancel_event` 추가, `cancelled` signal로 partial result 전달 |
| A-4 | `src/gui/main_window.py` | `_on_gapfill_cancelled()` 핸들러, Phase별 부분 UI 업데이트, `_workflow_checkpoint` 필드 |
| A-5 | `src/gui/gapfill_panel.py` | Partial result 배너 ("Resume available"), Phase 표시 |
| A-6 | Tests | cancel recovery, partial result, checkpoint 테스트 |

### Phase B: Resume (A 완료 후)

| Task | 파일 | 설명 |
|------|------|------|
| B-1 | `src/gui/main_window.py` | `_start_workflow()`에서 checkpoint 확인, Resume 다이얼로그 |
| B-2 | `src/gui/workers.py` | `GapFillWorkflowWorker`에 checkpoint 기반 resume 지원 |
| B-3 | `src/gapfill/engine.py` | `start_phase` 기반 Phase 스킵 로직 |
| B-4 | Tests | resume workflow, checkpoint persistence 테스트 |

### Phase C: Universal Model Browser

| Task | 파일 | 설명 |
|------|------|------|
| C-1 | `src/gui/main_window.py` | "Load Universal Model..." 메뉴, Universal 탭 추가 |
| C-2 | `src/gui/candidate_table.py` | Universal browsing 모드 (evaluate 버튼, overview 헤더) |
| C-3 | `src/gui/reaction_detail.py` | `read_only` 모드 추가 — universal 반응 상세 표시 |
| C-4 | `src/gui/main_window.py` | Universal 반응 클릭 → detail panel 연동, evaluate 연동 |
| C-5 | Tests | universal browser 기능 테스트 |

### 의존성

```
Phase A (Cancel Recovery) ← 독립, 즉시 시작
Phase B (Resume) ← A 완료 후
Phase C (Universal Browser) ← 독립, 즉시 시작 (A와 병렬 가능)
```

---

## 5. 리스크

| 리스크 | 완화 |
|--------|------|
| Cancel 타이밍 — Phase 중간에 cancel 시 불완전 데이터 | Phase 단위로만 cancel 처리, Phase 내부는 원자적 |
| Universal 반응 28K+ 개 → 테이블 성능 | 기존 CandidateTableWidget의 가상화/필터 재활용 |
| Checkpoint가 메모리에만 → 앱 재시작 시 유실 | v1은 메모리만, 향후 디스크 저장 고려 |
| Universal evaluate 시 API 비용 | "Evaluate Selected" 기본, Evaluate All은 경고 표시 |

---

*Plan created: 2026-02-23*
*Feature: workflow-resume-universal-browser*
*PDCA Phase: Plan*
