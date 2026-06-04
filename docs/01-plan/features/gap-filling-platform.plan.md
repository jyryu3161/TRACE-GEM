# Plan: Gap-Filling Platform

> GEM Evaluator를 단순 평가 도구에서 **모델 개선 플랫폼**으로 확장

---

## 1. 개요

### 1.1 현재 상태
- SBML 모델을 로드하고, 모델 내 반응들을 KEGG/BiGG evidence로 평가하여 confidence score를 부여
- 평가 결과를 CSV/JSON/SBML로 내보내기 가능
- GUI(PySide6) + CLI 이중 인터페이스

### 1.2 목표 상태
사용자가 **종(organism), 내 모델, (선택) universal model, (선택) metabolic task 파일**을 입력하면:

1. **내 모델**의 반응을 기존 방식으로 평가
2. **Universal model**에서 내 모델에 없는 반응(후보 반응)을 추출하여 동일 방식으로 평가 + 종 특이성 검증
3. **Metabolic task** 기반 gap-filling을 수행하여 모델을 개선
4. 단계별 task pass/fail 시각화
5. 개선된 모델을 SBML로 다운로드

### 1.3 핵심 변경 사항
- Universal model 로더 (default: `bigg_universal_model_fixed.json`, custom: JSON/SBML 파일)
- Universal model 반응에 대한 **종 특이성(organism-specificity) 검증** 파이프라인
- KEGG 기반 GPR 할당
- Metabolic task 파서 및 실행기
- COBRApy `GapFiller` 기반 gap-filling 엔진 (evidence score를 penalty로 활용)
- Gap-filling 결과 시각화 및 단계별 task pass/fail 표시
- 개선된 모델 SBML 내보내기

---

## 2. 요구사항 분석

### 2.1 입력

| 입력 | 필수 | 형식 | 기본값 |
|------|------|------|--------|
| SBML 모델 | 필수 | `.xml`, `.sbml` | - |
| 종 (KEGG organism code) | 필수 | `eco`, `sce`, `hsa` 등 | 자동 감지 |
| Universal model | 선택 | `.json` (BiGG format), `.xml`/`.sbml` (COBRA format) | `data/bigg_universal_model_fixed.json` |
| Metabolic task 파일 | 선택 | `.csv` (Task ID, Type, ID, Medium, Constraints, Expected, Description, Category) | `data/universal_essential_tasks.csv` |

### 2.2 Universal Model 데이터 특성

**`bigg_universal_model_fixed.json` 분석 결과:**
- 28,301 reactions, 15,638 metabolites, **0 genes** (유전자 정보 없음)
- `gene_reaction_rule`: 모든 반응에서 빈 문자열
- Annotation 커버리지:
  - MetaNetX: 15,094/28,301 (53%)
  - EC Number: 3,973/28,301 (14%)
  - KEGG Reaction: 2,749/28,301 (10%)
  - BioCyc: 3,168/28,301 (11%)
  - RHEA: 3,303/28,301 (12%)

**ID 매핑 전략:**
1. 반응 annotation에서 직접 KEGG Reaction ID 추출 (2,749건)
2. MetaNetX ID → `reac_xref.tsv` → KEGG Reaction ID (15,094건 중 매핑 가능분)
3. EC Number → `reaction_analysis_result.tsv` → KEGG Reaction ID (3,973건)
4. BiGG reaction ID → `reac_xref.tsv` → KEGG Reaction ID (기존 매핑)

### 2.3 Metabolic Task 형식

```
Task ID,Type,ID,Medium,Constraints,Expected value,Description,Category
U001,Metabolite,atp_c,glc__D_e(-10.0);o2_e(-1000.0);pi_e(-1000.0),EX_o2_e(-1000.0#1000.0),>0.0,ATP production from glucose,Energy
U036,Reaction,ATPM,glc__D_e(-10.0);o2_e(-1000.0),EX_o2_e(-1000.0#1000.0),>0.0,Maintenance ATP requirement,Maintenance
```

- **Type**: `Metabolite` (demand reaction으로 테스트) 또는 `Reaction` (FBA objective로 테스트)
- **Medium**: exchange reaction bounds 설정 (`metabolite_id(lower_bound)` 형식)
- **Constraints**: 추가 bound 제약 (`reaction_id(lower#upper)` 형식)
- **Expected value**: `>0.0`, `<50.0`, `=0.0` 등 조건
- **Category**: Energy, Central Carbon, Amino Acid, Nucleotide, Cofactor, Lipid, Maintenance, Negative Constraint, PPP 등

### 2.4 COBRApy Gap-Filling API

```python
cobra.flux_analysis.gapfill(
    model,                    # 내 모델
    universal=universal_model,# universal model (cobra.Model)
    lower_bound=0.05,         # 최소 flux threshold
    penalties=penalties_dict,  # {reaction: cost} — evidence score 반영
    demand_reactions=True,
    exchange_reactions=False,
    iterations=1,             # 대안 솔루션 수
)
# Returns: list[list[Reaction]] — 추가해야 할 반응 리스트
```

**핵심**: `penalties` dict에 evidence score의 역수를 넣어, 높은 confidence의 반응이 우선 선택되도록 함.

### 2.5 출력

| 출력 | 형식 | 설명 |
|------|------|------|
| 평가 결과 (내 모델 + universal) | 테이블, CSV, JSON | 반응별 confidence score |
| Task pass/fail 결과 | 테이블, 시각화 | 단계별 progress |
| Gap-filling 결과 | 추가된 반응 리스트, GPR 정보 | |
| 개선된 SBML 모델 | `.xml` | cobra.io.write_sbml_model |

---

## 3. 아키텍처 설계

### 3.1 새로운 모듈 구조

```
src/
├── core/
│   ├── models.py              # [수정] CandidateReaction, MetabolicTask, GapFillResult 추가
│   ├── universal_loader.py    # [신규] Universal model 로더 (JSON/SBML)
│   ├── task_parser.py         # [신규] Metabolic task CSV 파서 + 실행기
│   ├── sbml_parser.py         # [기존 유지]
│   ├── gpr_parser.py          # [기존 유지]
│   ├── id_mapper.py           # [기존 유지]
│   └── mapping_data.py        # [기존 유지]
├── gapfill/                   # [신규 모듈]
│   ├── engine.py              # Gap-filling 오케스트레이터
│   ├── organism_filter.py     # KEGG 기반 종 특이성 필터링
│   ├── penalty_calculator.py  # Evidence score → gap-fill penalty 변환
│   └── gpr_assigner.py        # KEGG 기반 GPR 할당
├── evidence/
│   ├── engine.py              # [수정] Universal model 반응 평가 지원
│   ├── scoring.py             # [기존 유지]
│   └── evidence_types.py      # [기존 유지]
├── gui/
│   ├── main_window.py         # [수정] 워크플로우 탭 추가
│   ├── workflow_wizard.py     # [신규] 입력 위저드 (모델, 종, universal, task)
│   ├── universal_table.py     # [신규] Universal 반응 후보 테이블
│   ├── task_panel.py          # [신규] Metabolic task pass/fail 시각화
│   ├── gapfill_panel.py       # [신규] Gap-filling 결과 패널
│   ├── workers.py             # [수정] 새 Worker 타입 추가
│   └── ...                    # 기존 GUI 모듈 유지
├── cli.py                     # [수정] gap-filling CLI 옵션 추가
└── app.py                     # [기존 유지]
```

### 3.2 데이터 흐름

```
[입력]
  사용자 모델 (.xml)
  종 (KEGG code)
  Universal model (.json/.xml)     ← custom 가능
  Metabolic tasks (.csv)           ← custom 가능
        │
        ▼
┌──────────────────────────────────────────────┐
│ Phase 1: 모델 로딩 & 후보 추출                │
│                                              │
│  SBMLParser → ModelData (내 모델)             │
│  UniversalLoader → cobra.Model + Reaction[]  │
│  TaskParser → MetabolicTask[]                │
│                                              │
│  후보 반응 = Universal - 내 모델 (ID 기준)     │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ Phase 2: 종 특이성 필터링                      │
│                                              │
│  후보 반응 → ID 매핑 (KEGG Reaction ID)       │
│  KEGG API: 종별 반응 존재 여부 확인            │
│  결과: organism_filtered_candidates[]         │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ Phase 3: Evidence 평가                        │
│                                              │
│  내 모델 반응 → EvidenceEngine (기존)          │
│  후보 반응 → EvidenceEngine (확장)             │
│  결과: ReactionEvidence (score per reaction)  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ Phase 4: Metabolic Task 초기 테스트            │
│                                              │
│  내 모델 → TaskRunner.run_all(tasks)          │
│  결과: task_results_before[]  (pass/fail)     │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ Phase 5: Gap-Filling                          │
│                                              │
│  Evidence score → Penalty 변환                │
│    penalty = 1.0 / (score + 0.01)            │
│    종 미존재 반응 → penalty * 10              │
│                                              │
│  cobra.flux_analysis.gapfill(                │
│    model, universal,                         │
│    penalties=penalties_dict                   │
│  )                                           │
│  결과: 추가할 반응 리스트                      │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ Phase 6: GPR 할당 & 모델 업데이트              │
│                                              │
│  추가된 반응 → KEGG 기반 GPR 할당             │
│    KEGG orthology → organism genes            │
│  모델에 반응 추가 (cobra.Model.add_reactions) │
│                                              │
│  Metabolic Task 재테스트                      │
│  결과: task_results_after[] (pass/fail)       │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
[출력]
  ├── 평가 결과 테이블 (내 모델 + 후보)
  ├── Task pass/fail 비교 (before vs after)
  ├── Gap-fill 추가 반응 리스트 + GPR
  └── 개선된 SBML 모델 (.xml)
```

### 3.3 핵심 데이터 모델 (신규/수정)

```python
# --- 신규 데이터 모델 ---

@dataclass
class CandidateReaction:
    """Universal model에서 추출한 후보 반응."""
    reaction: Reaction                    # 기존 Reaction 재사용
    source_model: str                     # "bigg_universal" 또는 custom model ID
    organism_exists: bool | None = None   # KEGG에서 종 존재 확인 결과
    kegg_organism_genes: list[str] = field(default_factory=list)
    assigned_gpr: str = ""
    penalty: float = 1.0                  # gap-filling penalty

@dataclass
class MetabolicTask:
    """Metabolic task 정의."""
    task_id: str
    task_type: str          # "Metabolite" or "Reaction"
    target_id: str          # metabolite or reaction ID
    medium: dict[str, float]         # exchange bounds
    constraints: dict[str, tuple[float, float]]  # reaction bound overrides
    expected_operator: str  # ">", "<", "=", ">="
    expected_value: float
    description: str
    category: str

@dataclass
class TaskResult:
    """단일 metabolic task 실행 결과."""
    task: MetabolicTask
    passed: bool
    actual_value: float
    phase: str              # "before_gapfill", "after_gapfill"

@dataclass
class GapFillResult:
    """Gap-filling 전체 결과."""
    added_reactions: list[CandidateReaction]
    task_results_before: list[TaskResult]
    task_results_after: list[TaskResult]
    tasks_fixed: int        # before fail → after pass 된 수
    total_tasks: int
    iterations: int
```

---

## 4. 구현 단계 (Implementation Phases)

### Phase 1: Core — Universal Model 로더 & Task 파서
**파일**: `src/core/universal_loader.py`, `src/core/task_parser.py`, `src/core/models.py`

1. `UniversalLoader` 클래스
   - `load_json(path)` — BiGG JSON format 파싱 (`bigg_universal_model_fixed.json` 구조)
   - `load_sbml(path)` — COBRApy로 SBML 로드
   - `load(path)` — 확장자 기반 자동 감지
   - 반환: `cobra.Model` + `list[Reaction]` (내부 형식)
   - 내 모델과 겹치는 반응 제외 로직 포함

2. `TaskParser` 클래스
   - `parse_csv(path)` → `list[MetabolicTask]`
   - Medium/Constraints 파싱 (`glc__D_e(-10.0)` → `{"EX_glc__D_e": -10.0}`)
   - Expected value 파싱 (`>0.0` → operator=">", value=0.0)

3. `TaskRunner` 클래스
   - `run_task(model, task)` → `TaskResult`
   - `run_all(model, tasks)` → `list[TaskResult]`
   - FBA 기반: demand reaction 추가 또는 objective 설정 후 optimize

4. `models.py` 확장 — `CandidateReaction`, `MetabolicTask`, `TaskResult`, `GapFillResult` 추가

### Phase 2: Core — 종 특이성 필터링 & GPR 할당
**파일**: `src/gapfill/organism_filter.py`, `src/gapfill/gpr_assigner.py`

1. `OrganismFilter` 클래스
   - 후보 반응의 KEGG Reaction ID를 resolve (annotation + reac_xref.tsv)
   - KEGG API: `https://rest.kegg.jp/link/{organism}/rn:{reaction_id}` 로 종 존재 확인
   - 결과: `organism_exists` boolean + 관련 유전자 리스트
   - 배치 처리 + 캐싱 (기존 CacheManager 활용)

2. `GPRAssigner` 클래스
   - KEGG orthology API로 반응 → 유전자 매핑
   - `https://rest.kegg.jp/link/genes/{organism}:{gene_id}` 활용
   - Gene reaction rule 문자열 생성
   - 캐싱 지원

### Phase 3: Gap-Filling 엔진
**파일**: `src/gapfill/engine.py`, `src/gapfill/penalty_calculator.py`

1. `PenaltyCalculator` 클래스
   - Evidence score → penalty 변환
   - 기본 공식: `penalty = 1.0 / (confidence_score + epsilon)`
   - 종 미존재 반응: penalty × 10 (강한 불이익)
   - 종 존재 + 고점수 반응: 최저 penalty (우선 선택)

2. `GapFillEngine` 클래스
   - `run(model, universal, tasks, evidence_results, organism_filter_results)` → `GapFillResult`
   - 내부 워크플로우:
     1. 초기 task 테스트 (before)
     2. Penalty 계산
     3. 실패한 task별로 gap-filling 실행
     4. 추가된 반응에 GPR 할당
     5. 최종 task 테스트 (after)
   - COBRApy `cobra.flux_analysis.gapfill()` 래핑
   - Task-driven: 실패한 task마다 objective 설정 후 gap-fill

### Phase 4: Evidence Engine 확장
**파일**: `src/evidence/engine.py` 수정

1. `evaluate_candidates()` 메서드 추가
   - Universal model 반응을 KEGG/BiGG 전용 `evaluate_reaction()` 파이프라인으로 평가
   - 후보 반응이 universal model에서 왔으면 BiGG evidence는 자동 STRONG으로 기록
   - KEGG 매핑과 metabolite match ratio를 evidence에 포함

2. `evaluate_batch()` 확장
   - 내 모델 + 후보 반응을 구분하여 배치 처리
   - progress callback에 phase 정보 추가

### Phase 5: GUI — 워크플로우 위저드 & 새 패널
**파일**: `src/gui/workflow_wizard.py`, `src/gui/task_panel.py`, `src/gui/gapfill_panel.py`, `src/gui/universal_table.py`

1. `WorkflowWizard` — 입력 마법사
   - Step 1: SBML 모델 선택 + 종 확인
   - Step 2: Universal model 선택 (기본/커스텀)
   - Step 3: Metabolic task 파일 선택 (기본/커스텀)
   - Step 4: 평가 옵션 설정 (batch size, sources 등)
   - "Start Workflow" 버튼

2. `UniversalTableWidget` — 후보 반응 테이블
   - 기존 `ReactionTableWidget`과 유사한 구조
   - 추가 컬럼: organism_exists, penalty, selected(체크박스)
   - 필터: 종 존재 여부, score 범위, subsystem

3. `TaskPanelWidget` — Metabolic task 결과 패널
   - Task 목록 테이블: Task ID, Description, Category, Before(pass/fail), After(pass/fail)
   - 카테고리별 pass/fail 요약 차트 (bar chart)
   - Before vs After 비교 시각화
   - 색상 코딩: pass=녹색, fail=빨강, fixed=파랑

4. `GapFillPanelWidget` — Gap-filling 결과 패널
   - 추가된 반응 리스트 + 각 반응의 evidence score, GPR
   - "Apply to Model" 버튼
   - "Export Improved Model" 버튼

5. `MainWindow` 수정
   - 메뉴에 "Workflow" → "Gap-Fill Workflow..." 추가
   - 새 탭들 추가 (Universal Candidates, Tasks, Gap-Fill Results)
   - Worker 추가: `GapFillWorkflowWorker`

### Phase 6: CLI 확장
**파일**: `src/cli.py` 수정

```bash
# 기존 (유지)
gem-evaluator-cli model.xml -o results.csv

# 신규 gap-filling 모드
gem-evaluator-cli model.xml --gap-fill \
  --organism eco \
  --universal ./data/bigg_universal_model_fixed.json \
  --tasks ./data/universal_essential_tasks.csv \
  --output-model improved_model.xml \
  --output-report gapfill_report.csv
```

### Phase 7: 테스트
**파일**: `tests/` 하위

1. `test_universal_loader.py` — JSON/SBML 로딩, 반응 추출
2. `test_task_parser.py` — CSV 파싱, medium/constraint 해석
3. `test_task_runner.py` — FBA 기반 task 실행 (mock model)
4. `test_organism_filter.py` — KEGG API 호출 (mocked)
5. `test_penalty_calculator.py` — Score → penalty 변환
6. `test_gapfill_engine.py` — 전체 gap-fill 파이프라인 (mock)
7. `test_gpr_assigner.py` — KEGG → GPR 할당
8. `test_gui_task_panel.py` — Task 패널 UI
9. `test_gui_gapfill_panel.py` — Gap-fill 결과 패널 UI
10. `test_integration_gapfill.py` — E2E 테스트 (소규모 모델)

---

## 5. Team 구성 & Task 분배

### 5.1 Team 구성

이 기능은 **5개 작업 스트림**으로 병렬 진행 가능:

| Team | 담당 범위 | 주요 파일 |
|------|----------|----------|
| **T1: Core Data** | Universal 로더, Task 파서, 데이터 모델 | `universal_loader.py`, `task_parser.py`, `models.py` |
| **T2: Gap-Fill Engine** | 종 필터링, penalty, gap-filling, GPR | `gapfill/` 모듈 전체 |
| **T3: Evidence Extension** | Evidence engine 확장, 후보 반응 평가 | `evidence/engine.py` 수정 |
| **T4: GUI** | 위저드, 새 패널들, MainWindow 수정 | `gui/` 하위 신규/수정 |
| **T5: CLI & Test** | CLI 확장, 전체 테스트 | `cli.py`, `tests/` |

### 5.2 의존 관계

```
T1 (Core Data) ─────────┐
                         ├──→ T3 (Evidence Extension) ──┐
T2 (Gap-Fill Engine) ────┤                              ├──→ T4 (GUI)
                         │                              │
                         └──────────────────────────────├──→ T5 (CLI & Test)
                                                        │
T1 완료 후 T2, T3 병렬 가능                               │
T2 + T3 완료 후 T4, T5 병렬 가능
```

### 5.3 상세 Task 목록

#### T1: Core Data (Phase 1)

| Task ID | 작업 | 예상 |
|---------|------|------|
| T1-1 | `models.py`에 `CandidateReaction`, `MetabolicTask`, `TaskResult`, `GapFillResult` 추가 | S |
| T1-2 | `UniversalLoader` — JSON 로더 (BiGG format) | M |
| T1-3 | `UniversalLoader` — SBML 로더 (COBRApy) | S |
| T1-4 | `UniversalLoader` — 내 모델과 겹치는 반응 제외 로직 | S |
| T1-5 | `TaskParser` — CSV 파싱, Medium/Constraint/Expected 해석 | M |
| T1-6 | `TaskRunner` — FBA 기반 task 실행 (demand reaction, objective) | M |
| T1-7 | 테스트: `test_universal_loader.py`, `test_task_parser.py`, `test_task_runner.py` | M |

#### T2: Gap-Fill Engine (Phase 2-3)

| Task ID | 작업 | 예상 |
|---------|------|------|
| T2-1 | `OrganismFilter` — KEGG API로 종별 반응 존재 확인 | L |
| T2-2 | `OrganismFilter` — 배치 처리 + 캐싱 | M |
| T2-3 | `PenaltyCalculator` — evidence score → penalty 변환 | S |
| T2-4 | `GapFillEngine` — COBRApy gapfill 래핑 + task-driven 실행 | L |
| T2-5 | `GPRAssigner` — KEGG orthology → gene 매핑 | L |
| T2-6 | 테스트: `test_organism_filter.py`, `test_penalty_calculator.py`, `test_gapfill_engine.py`, `test_gpr_assigner.py` | M |

#### T3: Evidence Extension (Phase 4)

| Task ID | 작업 | 예상 |
|---------|------|------|
| T3-1 | `EvidenceEngine.evaluate_candidates()` — 유전자 없는 반응 평가 지원 | M |
| T3-2 | `evaluate_batch()` 확장 — 내 모델 + 후보 구분 | S |
| T3-3 | 종 특이성 결과를 evidence item으로 통합 | S |
| T3-4 | 테스트: evidence engine 후보 평가 | M |

#### T4: GUI (Phase 5)

| Task ID | 작업 | 예상 |
|---------|------|------|
| T4-1 | `WorkflowWizard` — 입력 마법사 (모델, 종, universal, task) | L |
| T4-2 | `UniversalTableWidget` — 후보 반응 테이블 | M |
| T4-3 | `TaskPanelWidget` — Task pass/fail 테이블 + 시각화 | L |
| T4-4 | `GapFillPanelWidget` — 결과 패널 + Apply/Export 버튼 | M |
| T4-5 | `MainWindow` 수정 — 메뉴, 탭, Worker 통합 | L |
| T4-6 | `GapFillWorkflowWorker` — 전체 워크플로우 비동기 실행 | M |
| T4-7 | GUI 테스트 | M |

#### T5: CLI & Integration Test (Phase 6-7)

| Task ID | 작업 | 예상 |
|---------|------|------|
| T5-1 | CLI `--gap-fill` 모드 추가 | M |
| T5-2 | CLI 옵션: `--universal`, `--tasks`, `--output-model` | S |
| T5-3 | Integration test — 소규모 SBML 모델로 E2E | L |
| T5-4 | 문서 업데이트 (README, CLAUDE.md) | S |

**크기 기준**: S = 1-2시간, M = 3-5시간, L = 6-10시간

---

## 6. 기술적 고려사항

### 6.1 Universal Model 반응의 ID 매핑 전략

Universal model 반응은 유전자가 없으므로 다단계 ID 해석이 필요:

```python
def resolve_universal_reaction_kegg(reaction, mapping_data):
    kegg_ids = []

    # 1. 직접 annotation에서 KEGG Reaction ID
    for uri in reaction.annotation.get("KEGG Reaction", []):
        kegg_ids.append(extract_id(uri))  # "R00200"

    # 2. MetaNetX → reac_xref.tsv → KEGG
    for uri in reaction.annotation.get("MetaNetX (MNX) Equation", []):
        mnxr = extract_id(uri)  # "MNXR96888"
        kegg_ids.extend(mnxr_to_kegg.get(mnxr, []))

    # 3. BiGG ID → reac_xref.tsv → KEGG
    kegg_ids.extend(mapping_data.rxn_bigg_to_kegg.get(reaction.id, []))

    # 4. EC Number → reaction_analysis_result.tsv → KEGG
    for uri in reaction.annotation.get("EC Number", []):
        ec = extract_id(uri)
        kegg_ids.extend(mapping_data.rxn_ec_to_kegg.get(ec, []))

    return list(set(kegg_ids))
```

### 6.2 Gap-Filling Penalty 전략

```python
def calculate_penalty(confidence_score, organism_exists, has_kegg_match):
    """높은 evidence = 낮은 penalty = gap-filler가 우선 선택."""
    base = 1.0 / (confidence_score + 0.01)  # [1.0, 100.0] range

    if organism_exists is False:
        base *= 10.0   # 종에 없는 반응은 강한 불이익
    elif organism_exists is None:
        base *= 3.0    # 확인 불가능한 반응도 불이익

    if not has_kegg_match:
        base *= 2.0    # KEGG 매칭 안 되는 반응도 불이익

    return min(base, 1000.0)  # 상한 제한
```

### 6.3 Task-Driven Gap-Filling

단순히 biomass objective만으로 gap-fill하면 불필요한 반응이 추가될 수 있음. 대신 **실패한 task별로** gap-fill:

```python
for task in failed_tasks:
    # 1. 해당 task의 medium/constraint 설정
    # 2. task target을 objective로 설정
    # 3. gap-fill 실행
    # 4. 결과 반응을 모델에 추가
    # 5. 다음 task로 이동 (누적)
```

### 6.4 KEGG 기반 GPR 할당

```python
async def assign_gpr(reaction_kegg_id, organism_code):
    # 1. KEGG: reaction → orthology
    # GET https://rest.kegg.jp/link/ko/rn:{reaction_id}

    # 2. KEGG: orthology → organism genes
    # GET https://rest.kegg.jp/link/genes/{organism_code}/ko:{ko_id}

    # 3. Gene reaction rule 생성
    # 복수 유전자 → "gene1 or gene2"
    # (추후 subunit 정보로 and/or 정교화 가능)
    return gene_reaction_rule
```

### 6.5 성능 고려

| 작업 | 예상 시간 | 병목 | 대응 |
|------|----------|------|------|
| Universal model 로딩 | 5-10초 | JSON 파싱 (19MB) + 메모리 | 한 번만 로드, 캐싱 |
| 후보 추출 | <1초 | Set 연산 | - |
| 종 필터링 (28K 반응) | 2-5시간 (API) | KEGG rate limit (3/s) | 배치+캐싱, 30일 TTL |
| 후보 평가 (수백~수천) | 수분~수시간 | 7개 소스 API | 기존 병렬 처리 |
| Gap-filling (COBRApy) | 1-30초/task | LP solver | - |
| GPR 할당 | 수분 | KEGG API | 캐싱 |

**최적화**: 종 필터링은 가장 비용이 크므로, 별도 "Pre-filter" 단계로 분리하고 결과를 캐싱. 이후 세션에서 같은 종이면 캐시 활용.

---

## 7. 리스크 & 완화 전략

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| KEGG 종 필터링이 너무 오래 걸림 | 높음 | 중 | 캐싱(30일), 선필터(annotation에 KEGG 있는 것만), 배치 처리 |
| COBRApy gap-fill이 infeasible | 중 | 높 | fallback: relaxed bounds, iterative approach |
| Universal model이 너무 큼 (메모리) | 중 | 중 | 필요시 반응만 로드, cobra.Model lazy loading |
| GPR 할당 정확도 낮음 | 중 | 낮 | 사용자 편집 가능, "tentative" 마크 |
| Custom universal model 형식 불일치 | 낮 | 중 | 형식 검증 + 에러 메시지 |

---

## 8. 성공 기준

1. Default 파일(universal model + metabolic task)로 E. coli 모델 gap-filling 완료
2. Custom universal model (JSON/SBML) 로딩 및 gap-filling 동작
3. Custom metabolic task CSV 로딩 및 실행 동작
4. Task pass/fail 시각화 (before vs after)
5. 개선된 SBML 모델 내보내기 가능
6. GUI + CLI 모두 동작
7. 기존 evaluation-only 워크플로우가 깨지지 않음 (하위 호환성)
8. 테스트 커버리지 ≥ 80%

---

## 9. 구현 우선순위

```
Week 1:  T1 전체 (Core Data) — 모든 다른 작업의 기반
Week 2:  T2-1~T2-3 (종 필터링, penalty) + T3 전체 (Evidence 확장) — 병렬
Week 3:  T2-4~T2-6 (Gap-fill 엔진, GPR) — T1+T3 의존
Week 4:  T4-1~T4-4 (GUI 신규 패널) + T5-1~T5-2 (CLI) — 병렬
Week 5:  T4-5~T4-7 (GUI 통합) + T5-3~T5-4 (Integration test, 문서)
```

---

*Plan created: 2026-02-21*
*Feature: gap-filling-platform*
*PDCA Phase: Plan*
