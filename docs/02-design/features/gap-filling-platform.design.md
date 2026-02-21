# Design: Gap-Filling Platform

> Plan 참조: `docs/01-plan/features/gap-filling-platform.plan.md`

---

## 1. 파일 변경 목록

### 1.1 신규 파일

| 파일 경로 | 역할 |
|-----------|------|
| `src/core/universal_loader.py` | Universal model 로더 (JSON/SBML) |
| `src/core/task_parser.py` | Metabolic task CSV 파서 + FBA 실행기 |
| `src/gapfill/__init__.py` | Gap-fill 모듈 패키지 |
| `src/gapfill/engine.py` | Gap-filling 오케스트레이터 |
| `src/gapfill/organism_filter.py` | KEGG 기반 종 특이성 필터 |
| `src/gapfill/penalty_calculator.py` | Evidence score → penalty 변환 |
| `src/gapfill/gpr_assigner.py` | KEGG orthology → GPR 할당 |
| `src/gui/workflow_wizard.py` | 입력 마법사 다이얼로그 |
| `src/gui/task_panel.py` | Metabolic task pass/fail 패널 |
| `src/gui/gapfill_panel.py` | Gap-filling 결과 패널 |
| `src/gui/candidate_table.py` | 후보 반응 테이블 위젯 |
| `tests/test_universal_loader.py` | Universal loader 테스트 |
| `tests/test_task_parser.py` | Task parser/runner 테스트 |
| `tests/test_organism_filter.py` | Organism filter 테스트 |
| `tests/test_penalty_calculator.py` | Penalty calculator 테스트 |
| `tests/test_gapfill_engine.py` | Gap-fill engine 테스트 |
| `tests/test_gpr_assigner.py` | GPR assigner 테스트 |
| `tests/test_gui_task_panel.py` | Task panel GUI 테스트 |
| `tests/test_integration_gapfill.py` | Gap-fill E2E 통합 테스트 |

### 1.2 수정 파일

| 파일 경로 | 변경 내용 |
|-----------|----------|
| `src/core/models.py` | 신규 dataclass 5개 추가 |
| `src/core/id_mapper.py` | `resolve_universal()` 메서드 추가 |
| `src/evidence/engine.py` | `evaluate_candidates()` 메서드 추가 |
| `src/gui/main_window.py` | 메뉴, 탭, Worker 통합 |
| `src/gui/workers.py` | 3개 Worker 클래스 추가 |
| `src/utils/config.py` | Gap-fill 관련 설정 필드 추가 |
| `src/utils/constants.py` | Gap-fill 관련 상수 추가 |
| `src/cli.py` | `--gap-fill` 모드 추가 |

---

## 2. 데이터 모델 상세 설계

### 2.1 신규 Dataclasses (`src/core/models.py`에 추가)

```python
@dataclass
class CandidateReaction:
    """Universal model에서 추출한 후보 반응."""
    reaction: Reaction
    source_model: str = "bigg_universal"
    organism_exists: bool | None = None       # KEGG 종 존재 확인 결과
    kegg_organism_genes: list[str] = field(default_factory=list)
    assigned_gpr: str = ""
    penalty: float = 1.0
    selected: bool = False                    # 사용자가 gap-fill에 포함시킬지 선택


@dataclass
class MetabolicTask:
    """Metabolic task 정의."""
    task_id: str
    task_type: str                            # "Metabolite" or "Reaction"
    target_id: str
    medium: dict[str, float] = field(default_factory=dict)
    constraints: dict[str, tuple[float, float]] = field(default_factory=dict)
    expected_operator: str = ">"              # ">", "<", "=", ">="
    expected_value: float = 0.0
    description: str = ""
    category: str = ""


@dataclass
class TaskResult:
    """단일 metabolic task 실행 결과."""
    task: MetabolicTask
    passed: bool
    actual_value: float
    error_message: str | None = None
    phase: str = "before"                     # "before" | "after"


@dataclass
class GapFillResult:
    """Gap-filling 전체 결과."""
    added_reactions: list[CandidateReaction] = field(default_factory=list)
    task_results_before: list[TaskResult] = field(default_factory=list)
    task_results_after: list[TaskResult] = field(default_factory=list)
    tasks_fixed: int = 0
    total_tasks: int = 0
    iterations: int = 0
    infeasible_tasks: list[str] = field(default_factory=list)


class ReactionOrigin(Enum):
    """반응의 출처 구분."""
    MODEL = "model"           # 사용자 모델에 원래 존재
    UNIVERSAL = "universal"   # Universal model에서 후보로 추출
    GAP_FILLED = "gap_filled" # Gap-filling으로 추가됨
```

### 2.2 Config 확장 (`src/utils/config.py`)

```python
@dataclass
class Config:
    # ... 기존 필드 유지 ...

    # Gap-fill settings (신규)
    default_universal_model: str = "data/bigg_universal_model_fixed.json"
    default_task_file: str = "data/universal_essential_tasks.csv"
    gapfill_lower_bound: float = 0.05
    gapfill_iterations: int = 1
    organism_filter_cache_ttl: int = 30 * 24 * 3600  # 30 days
    gapfill_penalty_epsilon: float = 0.01
    gapfill_organism_penalty_multiplier: float = 10.0
    gapfill_no_kegg_penalty_multiplier: float = 2.0
```

### 2.3 Constants 확장 (`src/utils/constants.py`)

```python
# Gap-fill defaults
DEFAULT_UNIVERSAL_MODEL = "data/bigg_universal_model_fixed.json"
DEFAULT_TASK_FILE = "data/universal_essential_tasks.csv"
GAPFILL_LOWER_BOUND = 0.05
GAPFILL_MAX_PENALTY = 1000.0
ORGANISM_FILTER_CACHE_TTL = 30 * 24 * 3600
```

---

## 3. 모듈별 상세 설계

### 3.1 `src/core/universal_loader.py`

```python
"""Universal metabolic model loader (JSON/SBML)."""

class UniversalLoader:
    """Universal model을 로드하고 후보 반응을 추출한다."""

    def load(self, filepath: str | Path) -> cobra.Model:
        """확장자 기반 자동 감지 로드.

        .json → load_json()
        .xml, .sbml → load_sbml()
        """

    def load_json(self, filepath: str | Path) -> cobra.Model:
        """BiGG JSON format 로드.

        cobra.io.load_json_model() 사용.
        bigg_universal_model_fixed.json 구조:
        - reactions[]: id, name, metabolites, bounds, annotation
        - metabolites[]: id, name, formula, annotation
        - genes[]: (비어있음)
        """

    def load_sbml(self, filepath: str | Path) -> cobra.Model:
        """SBML/XML format 로드.

        cobra.io.read_sbml_model() 사용.
        Custom universal model 지원.
        """

    def extract_candidates(
        self,
        universal: cobra.Model,
        user_model: ModelData,
    ) -> list[CandidateReaction]:
        """Universal model에서 user_model에 없는 반응을 추출.

        1. user_model의 reaction ID set 구성
        2. universal의 각 reaction 중 user_model에 없는 것 추출
        3. Exchange/demand reaction 제외 (EX_, DM_, SK_ prefix)
        4. Reaction → 내부 Reaction 형식 변환
        5. CandidateReaction 래핑하여 반환

        ID 비교시 normalize: R_ prefix 제거, 대소문자 무시
        """
```

**비교 로직 상세**:
```python
def _build_model_reaction_ids(self, model: ModelData) -> set[str]:
    """사용자 모델의 반응 ID를 정규화하여 set으로 구성."""
    ids = set()
    for rxn in model.reactions:
        ids.add(rxn.id.lower())
        # R_ prefix 없는 버전도 추가
        if rxn.id.startswith("R_"):
            ids.add(rxn.id[2:].lower())
        else:
            ids.add(f"R_{rxn.id}".lower())
    return ids

def _is_utility_reaction(self, rxn_id: str) -> bool:
    """Exchange, demand, sink 반응 여부."""
    return any(rxn_id.startswith(p) for p in ("EX_", "DM_", "SK_", "sink_"))
```

### 3.2 `src/core/task_parser.py`

```python
"""Metabolic task CSV parser and FBA-based task runner."""

class TaskParser:
    """Metabolic task CSV 파일을 파싱한다."""

    def parse(self, filepath: str | Path) -> list[MetabolicTask]:
        """CSV 파일을 읽어 MetabolicTask 리스트로 변환.

        CSV 형식:
        Task ID,Type,ID,Medium,Constraints,Expected value,Description,Category

        Medium 파싱: "glc__D_e(-10.0);o2_e(-1000.0)"
          → {"EX_glc__D_e": -10.0, "EX_o2_e": -1000.0}

        Constraints 파싱: "EX_o2_e(-1000.0#1000.0)"
          → {"EX_o2_e": (-1000.0, 1000.0)}

        Expected value 파싱: ">0.0", "<50.0", "=0.0"
          → operator=">", value=0.0
        """

    def _parse_medium(self, medium_str: str) -> dict[str, float]:
        """Medium 문자열 → {exchange_reaction_id: lower_bound}."""

    def _parse_constraints(self, constraint_str: str) -> dict[str, tuple[float, float]]:
        """Constraint 문자열 → {reaction_id: (lower, upper)}."""

    def _parse_expected(self, expected_str: str) -> tuple[str, float]:
        """Expected value → (operator, value)."""


class TaskRunner:
    """FBA 기반 metabolic task 실행기."""

    def run_task(self, model: cobra.Model, task: MetabolicTask) -> TaskResult:
        """단일 task를 FBA로 실행하고 결과를 반환.

        1. 모델 복사 (model.copy())
        2. Medium 설정: 모든 exchange 닫기 → task.medium 적용
        3. Constraint 설정: task.constraints 적용
        4. Objective 설정:
           - Metabolite type: demand reaction 추가 → objective
           - Reaction type: 해당 reaction을 objective로
        5. FBA 실행 (model.optimize())
        6. Expected value와 비교하여 pass/fail 판정
        7. 임시 반응 cleanup
        """

    def run_all(
        self,
        model: cobra.Model,
        tasks: list[MetabolicTask],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[TaskResult]:
        """모든 task를 순차 실행.

        각 task는 모델 복사본에서 독립 실행 (부작용 없음).
        """

    def _apply_medium(self, model: cobra.Model, medium: dict[str, float]) -> None:
        """Exchange reaction bounds를 medium에 따라 설정."""

    def _apply_constraints(
        self, model: cobra.Model, constraints: dict[str, tuple[float, float]]
    ) -> None:
        """추가 bound constraint 적용."""

    def _check_expected(self, actual: float, operator: str, expected: float) -> bool:
        """Expected value 조건 검사.

        ">": actual > expected - tolerance
        "<": actual < expected + tolerance
        "=": abs(actual - expected) < tolerance
        tolerance = 1e-6
        """
```

**Medium 설정 상세 로직**:
```
입력: "glc__D_e(-10.0);o2_e(-1000.0);pi_e(-1000.0)"
파싱: [("glc__D_e", -10.0), ("o2_e", -1000.0), ("pi_e", -1000.0)]

적용:
1. 모든 exchange reaction의 lower_bound를 0으로 (모두 닫기)
2. 각 medium 항목에 대해:
   - "EX_{met_id}" 반응 찾기
   - lower_bound 설정 (e.g., -10.0)
```

**Metabolite type task 실행 상세**:
```
Task: U001,Metabolite,atp_c,...,>0.0

1. Demand reaction 추가: "DM_atp_c" (atp_c → nothing)
2. Objective: maximize DM_atp_c
3. FBA 실행
4. objective_value > 0.0 이면 pass
```

### 3.3 `src/gapfill/organism_filter.py`

```python
"""KEGG-based organism specificity filter for candidate reactions."""

class OrganismFilter:
    """후보 반응이 특정 종에 존재하는지 KEGG API로 확인."""

    def __init__(
        self,
        organism_code: str,
        cache_manager: CacheManager | None = None,
        mapping_data: MappingData | None = None,
    ) -> None:
        self._organism = organism_code
        self._cache = cache_manager
        self._mapping = mapping_data
        self._kegg_client: BaseAPIClient  # rate-limited KEGG access
        self._organism_reactions: set[str] | None = None  # 캐시된 종 반응 set

    async def initialize(self) -> None:
        """종의 전체 반응 목록을 한번에 가져와서 캐시.

        KEGG API: GET /link/reaction/{organism_code}
        예: /link/reaction/eco → eco:b0001\trn:R00001 형식

        이 접근이 개별 반응 확인보다 효율적:
        - 1 API call로 종의 모든 반응 확보
        - 이후 in-memory set lookup (O(1))
        """

    async def filter_candidates(
        self,
        candidates: list[CandidateReaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[CandidateReaction]:
        """후보 반응들의 종 존재 여부를 판별.

        1. 종의 KEGG 반응 set 로드 (initialize or cache)
        2. 각 후보의 KEGG Reaction ID를 resolve
        3. KEGG 반응 set과 비교하여 organism_exists 설정
        4. 존재하는 경우 관련 유전자도 추출
        """

    def _resolve_kegg_ids(self, candidate: CandidateReaction) -> list[str]:
        """후보 반응의 KEGG Reaction ID를 다단계로 resolve.

        1. Annotation에서 직접 'KEGG Reaction' 추출
        2. 'MetaNetX (MNX) Equation' → MappingData → KEGG
        3. BiGG reaction ID → MappingData.rxn_bigg_to_kegg
        4. 'EC Number' → MappingData.rxn_ec_to_kegg
        """

    async def _load_organism_reactions(self) -> set[str]:
        """KEGG에서 종의 전체 반응 목록 로드.

        캐시 키: f"organism_reactions:{self._organism}"
        캐시 TTL: 30일

        API 응답 파싱:
        "eco:b0001\trn:R00200\n" → {"R00200", ...}
        """

    async def _get_organism_genes_for_reaction(
        self, kegg_reaction_id: str
    ) -> list[str]:
        """특정 반응에 대한 종의 유전자 목록.

        KEGG API: GET /link/genes/{organism}/rn:{reaction_id}
        """
```

**핵심 최적화**: 개별 반응 API 호출 대신 종 전체 반응을 1회 호출로 가져옴.
- E. coli: ~1,700 KEGG reactions
- 이후 모든 비교는 in-memory set lookup (28,301 후보에 대해 <1초)

### 3.4 `src/gapfill/penalty_calculator.py`

```python
"""Evidence-based penalty calculation for gap-filling."""

class PenaltyCalculator:
    """Evidence score를 COBRApy gap-fill penalty로 변환."""

    def __init__(self, config: Config) -> None:
        self._epsilon = config.gapfill_penalty_epsilon      # 0.01
        self._org_mult = config.gapfill_organism_penalty_multiplier  # 10.0
        self._no_kegg_mult = config.gapfill_no_kegg_penalty_multiplier  # 2.0
        self._max_penalty = GAPFILL_MAX_PENALTY              # 1000.0

    def calculate(self, candidate: CandidateReaction, evidence: ReactionEvidence | None) -> float:
        """단일 후보 반응의 penalty 계산.

        높은 evidence score → 낮은 penalty → gap-filler가 우선 선택

        공식:
          base = 1.0 / (confidence_score + epsilon)
          if organism_exists == False: base *= org_mult
          elif organism_exists is None: base *= 3.0
          if len(kegg_reaction_ids) == 0: base *= no_kegg_mult
          return min(base, max_penalty)
        """

    def calculate_batch(
        self,
        candidates: list[CandidateReaction],
        evidence_results: dict[str, ReactionEvidence],
    ) -> dict[str, float]:
        """전체 후보에 대한 penalty dict 생성.

        반환: {reaction_id: penalty} — cobra.flux_analysis.gapfill()의 penalties 파라미터용
        """
```

**Penalty 예시**:

| Evidence Score | Organism Exists | KEGG Match | Penalty |
|---------------|----------------|------------|---------|
| 0.90 | Yes | Yes | 1.1 |
| 0.60 | Yes | Yes | 1.6 |
| 0.30 | Yes | Yes | 3.2 |
| 0.60 | No | Yes | 16.4 |
| 0.10 | None | No | 54.5 |
| 0.00 | No | No | 1000.0 (capped) |

### 3.5 `src/gapfill/gpr_assigner.py`

```python
"""KEGG-based GPR (Gene-Protein-Reaction) assignment."""

class GPRAssigner:
    """KEGG orthology를 이용해 반응에 GPR rule을 할당."""

    def __init__(
        self,
        organism_code: str,
        cache_manager: CacheManager | None = None,
    ) -> None:
        self._organism = organism_code
        self._cache = cache_manager
        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter(rate=3.0, burst=3)

    async def assign_gpr(
        self, kegg_reaction_id: str
    ) -> tuple[str, list[str]]:
        """반응의 GPR rule과 유전자 리스트를 반환.

        1. KEGG: rn:{id} → ko:{orthology_id}
           GET /link/ko/rn:{reaction_id}
        2. KEGG: ko:{id} → {organism}:{gene_id}
           GET /link/{organism}/ko:{ko_id}
        3. 유전자 리스트 → GPR rule 생성
           - 단일 KO의 복수 유전자: "gene1 or gene2" (isozymes)
           - 복수 KO의 유전자: "(ko1_genes) and (ko2_genes)" (subunits)

        반환: (gene_reaction_rule, [gene_ids])
        """

    async def assign_batch(
        self,
        candidates: list[CandidateReaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """배치로 GPR 할당. candidate.assigned_gpr 직접 수정."""

    async def close(self) -> None:
        """aiohttp 세션 정리."""
```

**GPR 생성 규칙**:
```
Case 1: 1 KO → 2 genes
  ko:K00844 → eco:b2388, eco:b1101
  GPR: "b2388 or b1101"

Case 2: 2 KOs → 1 gene each (subunit complex)
  ko:K00134 → eco:b1779
  ko:K00150 → eco:b1780
  GPR: "b1779 and b1780"

Case 3: 0 KOs (매핑 실패)
  GPR: ""  (빈 문자열, 나중에 사용자가 수정 가능)
```

### 3.6 `src/gapfill/engine.py`

```python
"""Gap-filling engine orchestrator."""

class GapFillEngine:
    """Task-driven gap-filling을 orchestrate."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._task_runner = TaskRunner()
        self._penalty_calc = PenaltyCalculator(config)
        self._gpr_assigner: GPRAssigner | None = None
        self._organism_filter: OrganismFilter | None = None

    async def initialize(
        self,
        organism_code: str,
        cache_manager: CacheManager | None = None,
        mapping_data: MappingData | None = None,
    ) -> None:
        """초기화: organism filter, GPR assigner 설정."""

    async def close(self) -> None:
        """리소스 정리."""

    async def run(
        self,
        user_model: cobra.Model,
        universal_model: cobra.Model,
        candidates: list[CandidateReaction],
        tasks: list[MetabolicTask],
        evidence_results: dict[str, ReactionEvidence],
        progress_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> GapFillResult:
        """전체 gap-filling 파이프라인 실행.

        progress_callback(phase, current, total, detail)

        Phase 1: "testing_before" — 초기 task 테스트
        Phase 2: "filtering" — 종 특이성 필터링
        Phase 3: "gap_filling" — COBRApy gap-fill 실행
        Phase 4: "assigning_gpr" — GPR 할당
        Phase 5: "testing_after" — 최종 task 테스트
        """

    def _run_initial_tests(
        self, model: cobra.Model, tasks: list[MetabolicTask]
    ) -> list[TaskResult]:
        """Phase 1: 초기 task 테스트."""

    async def _run_gapfill(
        self,
        model: cobra.Model,
        universal: cobra.Model,
        failed_tasks: list[MetabolicTask],
        penalties: dict[str, float],
    ) -> list[cobra.Reaction]:
        """Phase 3: Task-driven gap-filling.

        실패한 task별로 gap-fill:
        1. 모델 복사
        2. Task의 medium/constraint 적용
        3. Task target을 objective로 설정
        4. cobra.flux_analysis.gapfill() 실행
        5. 결과 반응 수집 (중복 제거)

        Infeasible한 task는 infeasible_tasks에 기록.
        """

    def _apply_gapfill_results(
        self,
        model: cobra.Model,
        reactions_to_add: list[cobra.Reaction],
        candidates: list[CandidateReaction],
    ) -> list[CandidateReaction]:
        """Gap-fill 결과를 모델에 적용.

        1. cobra.Model.add_reactions()으로 반응 추가
        2. 추가된 반응에 해당하는 CandidateReaction 찾기
        3. 해당 candidate.selected = True로 설정
        """

    def _run_final_tests(
        self, model: cobra.Model, tasks: list[MetabolicTask]
    ) -> list[TaskResult]:
        """Phase 5: 최종 task 테스트."""
```

### 3.7 `src/core/id_mapper.py` 확장

```python
class IdentifierMapper:
    # ... 기존 메서드 유지 ...

    async def resolve_universal(self, reaction: Reaction) -> ExternalIDs:
        """Universal model 반응의 external ID를 resolve.

        기존 resolve()와의 차이:
        - annotation key가 다름 ("KEGG Reaction" vs "kegg.reaction")
        - MetaNetX annotation에서 MNXR ID를 직접 추출
        - EC Number annotation에서도 KEGG 매핑
        """

    def _extract_from_universal_annotation(
        self, reaction: Reaction, ext: ExternalIDs
    ) -> None:
        """Universal model 반응의 annotation에서 ID 추출.

        지원하는 annotation key:
        - "KEGG Reaction" → kegg_reaction_ids
        - "EC Number" → ec_numbers
        - "MetaNetX (MNX) Equation" → mnxr_ids → kegg (via mapping)
        - "BioCyc" → metacyc reference (향후)
        - "RHEA" → RHEA reference (향후)
        """
```

### 3.8 `src/evidence/engine.py` 확장

```python
class EvidenceEngine:
    # ... 기존 코드 유지 ...

    async def evaluate_candidate(self, candidate: CandidateReaction) -> ReactionEvidence:
        """단일 후보 반응 평가.

        기존 evaluate_reaction()과의 차이:
        - resolve_universal() 사용 (annotation 형식 차이)
        - 유전자가 없으므로 UniProt는 EC 기반 검색만
        - BiGG verification: universal model 자체에서 왔으므로 자동 STRONG
        """

    async def evaluate_candidates_batch(
        self,
        candidates: list[CandidateReaction],
        progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, ReactionEvidence]:
        """후보 반응 배치 평가.

        기존 evaluate_batch()와 동일한 배치/세마포어 패턴 사용.
        """
```

---

## 4. GUI 설계

### 4.1 전체 레이아웃 변경

```
MainWindow
├── MenuBar
│   ├── File (기존)
│   ├── Evaluation (기존)
│   ├── Workflow (신규)           ← "Gap-Fill Workflow..." 메뉴
│   │   ├── "Start Workflow..."   → WorkflowWizard 열기
│   │   └── "Load Task File..."  → TaskParser로 task 로딩
│   ├── Export (기존 + 확장)
│   │   └── "Export Improved SBML..." (신규)
│   ├── View (기존)
│   └── Help (기존)
│
├── CentralWidget
│   └── QSplitter (Horizontal)
│       ├── Left Panel
│       │   ├── ModelOverviewWidget (수정: universal model 정보 추가)
│       │   └── QTabWidget (신규: 탭으로 테이블 전환)
│       │       ├── Tab "Model Reactions" → ReactionTableWidget (기존)
│       │       └── Tab "Candidates" → CandidateTableWidget (신규)
│       │
│       └── Right Panel — QTabWidget
│           ├── Tab "Detail & Evidence" (기존)
│           ├── Tab "Genes" (기존)
│           ├── Tab "Metabolites" (기존)
│           ├── Tab "Charts" (기존)
│           ├── Tab "Tasks" → TaskPanelWidget (신규)
│           └── Tab "Gap-Fill" → GapFillPanelWidget (신규)
│
└── StatusBar (기존 + workflow phase 표시)
```

### 4.2 `WorkflowWizard` (`src/gui/workflow_wizard.py`)

```
┌──────────────────────────────────────────────┐
│  Gap-Fill Workflow Setup                      │
├──────────────────────────────────────────────┤
│                                              │
│  Step 1: Model & Organism                    │
│  ┌──────────────────────────────────────┐    │
│  │ SBML Model: [iJO1366.xml      ] [📂] │    │
│  │ Organism:   [eco] [Escherichia coli]  │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  Step 2: Universal Model                     │
│  ┌──────────────────────────────────────┐    │
│  │ (●) Default (BiGG Universal)         │    │
│  │ ( ) Custom: [               ] [📂]   │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  Step 3: Metabolic Tasks                     │
│  ┌──────────────────────────────────────┐    │
│  │ (●) Default (Universal Essential)    │    │
│  │ ( ) Custom: [               ] [📂]   │    │
│  │ ( ) Skip tasks (gap-fill only)       │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  Step 4: Options                             │
│  ┌──────────────────────────────────────┐    │
│  │ ☑ Evaluate model reactions           │    │
│  │ ☑ Evaluate candidate reactions       │    │
│  │ ☑ Filter by organism (KEGG)          │    │
│  │ ☑ Run gap-filling                    │    │
│  │ ☑ Assign GPR from KEGG              │    │
│  └──────────────────────────────────────┘    │
│                                              │
│         [Cancel]  [Start Workflow]            │
└──────────────────────────────────────────────┘
```

**구현**: `QDialog` + `QFormLayout` + `QButtonGroup` (radio) + `QCheckBox`

### 4.3 `CandidateTableWidget` (`src/gui/candidate_table.py`)

기존 `ReactionTableWidget`과 동일한 패턴 (QAbstractTableModel + QSortFilterProxyModel)

```python
class CandidateTableModel(QAbstractTableModel):
    COLUMNS = [
        "ID", "Name", "Equation", "Subsystem",
        "Organism", "Score", "Penalty", "KEGG IDs", "GPR", "Selected"
    ]

    # "Organism" 컬럼: ✅ (존재), ❌ (미존재), ❓ (미확인)
    # "Selected" 컬럼: 체크박스 (gap-fill에 포함 여부)
    # "Score" 컬럼: ScoreBarDelegate 재사용
```

**필터 기능**:
- Organism exists: All / Yes only / No only
- Score range: slider (0.0 ~ 1.0)
- Subsystem: dropdown

### 4.4 `TaskPanelWidget` (`src/gui/task_panel.py`)

```
┌────────────────────────────────────────────────────────────┐
│  Metabolic Tasks                                           │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Summary: 35/52 passed (before) → 48/52 passed (after)    │
│           13 tasks fixed by gap-filling                    │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Category     │ Before │ After  │ Fixed │             │  │
│  ├──────────────┼────────┼────────┼───────┤             │  │
│  │ Energy       │ 4/5    │ 5/5    │ 1     │ ████░ 100% │  │
│  │ Central C.   │ 5/7    │ 7/7    │ 2     │ ████░ 100% │  │
│  │ Amino Acid   │ 3/7    │ 6/7    │ 3     │ ███░░  86% │  │
│  │ Nucleotide   │ 6/8    │ 8/8    │ 2     │ ████░ 100% │  │
│  │ Cofactor     │ 4/6    │ 5/6    │ 1     │ ███░░  83% │  │
│  │ ...          │        │        │       │             │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ID   │ Description              │ Cat.  │ Before│After│  │
│  ├──────┼──────────────────────────┼───────┼───────┼─────┤  │
│  │ U001 │ ATP production from glc  │ Energ │  ✅   │ ✅  │  │
│  │ U013 │ L-Glutamate biosynthesis │ Amino │  ❌   │ ✅  │  │  ← 파란색 (fixed)
│  │ U046 │ No heme w/o iron         │ Neg.  │  ✅   │ ✅  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  Filter: [All ▼] [Pass/Fail ▼]  Show: [Before ▼/After ▼]  │
└────────────────────────────────────────────────────────────┘
```

**색상 코딩**:
- Before Pass + After Pass: 녹색 배경
- Before Fail + After Pass: 파란색 배경 (fixed)
- Before Fail + After Fail: 빨간색 배경 (still failing)
- Before Pass + After Fail: 주황색 배경 (regression — 주의)

### 4.5 `GapFillPanelWidget` (`src/gui/gapfill_panel.py`)

```
┌────────────────────────────────────────────────────────────┐
│  Gap-Fill Results                                          │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Added 23 reactions | 13/17 failed tasks fixed             │
│  4 tasks remain infeasible                                 │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ ID          │ Name           │ Score │ GPR    │ Task │  │
│  ├─────────────┼────────────────┼───────┼────────┼──────┤  │
│  │ GLNS        │ Glutamine syn. │ 0.85  │ b0485  │ U014 │  │
│  │ PRPPS       │ PRPP synthase  │ 0.72  │ b1207  │ U012 │  │
│  │ ...         │                │       │        │      │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  [Apply to Model]  [Export Improved SBML]  [Export Report] │
└────────────────────────────────────────────────────────────┘
```

### 4.6 Workers 추가 (`src/gui/workers.py`)

```python
class GapFillWorkflowWorker(QRunnable):
    """전체 gap-fill 워크플로우를 비동기로 실행."""

    def __init__(
        self,
        config: Config,
        model_data: ModelData,
        universal_path: str,
        task_path: str | None,
        evidence_engine: EvidenceEngine,
        options: dict,  # evaluate_model, evaluate_candidates, filter_organism, etc.
    ) -> None: ...

    # Signals:
    # progress(str, int, int, str) — phase, current, total, detail
    # phase_changed(str) — "loading", "evaluating", "filtering", "gap_filling", "done"
    # result(GapFillResult)
    # error(str)


class OrganismFilterWorker(QRunnable):
    """종 특이성 필터링을 비동기로 실행."""


class EvaluateCandidatesWorker(QRunnable):
    """후보 반응 평가를 비동기로 실행."""
```

---

## 5. CLI 확장 설계 (`src/cli.py`)

```python
def _build_parser() -> argparse.ArgumentParser:
    # ... 기존 arguments 유지 ...

    # Gap-fill mode (신규)
    gf_group = parser.add_argument_group("Gap-filling options")
    gf_group.add_argument(
        "--gap-fill",
        action="store_true",
        help="Enable gap-filling mode",
    )
    gf_group.add_argument(
        "--universal",
        default=None,
        help="Path to universal model (JSON/SBML). Default: built-in BiGG universal",
    )
    gf_group.add_argument(
        "--tasks",
        default=None,
        help="Path to metabolic tasks CSV. Default: built-in universal tasks",
    )
    gf_group.add_argument(
        "--output-model",
        default=None,
        help="Path to save improved SBML model",
    )
    gf_group.add_argument(
        "--output-report",
        default=None,
        help="Path to save gap-fill report CSV",
    )
    gf_group.add_argument(
        "--skip-evaluation",
        action="store_true",
        help="Skip evidence evaluation, use penalty=1.0 for all",
    )
```

**CLI 워크플로우**:
```bash
# 기본 사용 (default universal model + default tasks)
gem-evaluator-cli model.xml --gap-fill --organism eco \
  --output-model improved.xml --output-report report.csv

# Custom universal model + custom tasks
gem-evaluator-cli model.xml --gap-fill --organism eco \
  --universal my_universal.json --tasks my_tasks.csv \
  --output-model improved.xml

# 평가 스킵 (빠른 gap-fill only)
gem-evaluator-cli model.xml --gap-fill --organism eco \
  --skip-evaluation --output-model improved.xml
```

---

## 6. 에러 처리 설계

### 6.1 에러 카테고리

| 에러 | 처리 | 사용자 메시지 |
|------|------|-------------|
| Universal model 파일 없음 | FileNotFoundError | "Universal model file not found: {path}" |
| Universal model 파싱 실패 | ValueError | "Failed to parse universal model: {detail}" |
| Task CSV 형식 오류 | ValueError | "Invalid task format at line {n}: {detail}" |
| KEGG API 실패 (종 필터링) | 캐시 fallback, circuit breaker | "KEGG API unavailable, organism filtering skipped" |
| Gap-fill infeasible | task별 기록 | "Task {id} infeasible: no solution found" |
| GPR 할당 실패 | 빈 GPR로 계속 | "GPR assignment failed for {rxn}: continuing without GPR" |
| 메모리 부족 (대형 모델) | 반응 수 제한 | "Universal model too large, limiting to {n} candidates" |

### 6.2 에러 복구 전략

```python
# Gap-fill infeasible 복구: relaxed bounds 시도
try:
    result = cobra.flux_analysis.gapfill(model, universal, ...)
except RuntimeError:
    # relaxed mode: lower_bound를 0.01로 낮춰서 재시도
    result = cobra.flux_analysis.gapfill(
        model, universal, lower_bound=0.01, ...
    )

# 여전히 infeasible → task를 infeasible_tasks에 기록하고 계속
```

---

## 7. 캐싱 전략

| 캐시 대상 | 캐시 키 패턴 | TTL | 사유 |
|-----------|------------|-----|------|
| 종 전체 반응 목록 | `organism_reactions:{code}` | 30일 | KEGG 데이터 변경 느림 |
| 반응별 종 유전자 | `organism_genes:{code}:{rxn_id}` | 30일 | 동일 |
| KO → 종 유전자 | `ko_genes:{code}:{ko_id}` | 30일 | 동일 |
| 후보 반응 evidence | 기존 패턴 재사용 | 7일 | 기존 evidence 캐시와 동일 |
| Task 결과 | 캐시 안 함 | - | 모델 상태에 따라 변동 |

---

## 8. 테스트 설계

### 8.1 단위 테스트

**`test_universal_loader.py`**:
```python
def test_load_json_default():
    """기본 BiGG universal model JSON 로드."""

def test_load_sbml_custom():
    """Custom SBML universal model 로드."""

def test_extract_candidates_excludes_model_reactions():
    """사용자 모델에 이미 있는 반응은 제외."""

def test_extract_candidates_excludes_exchange():
    """Exchange/demand/sink 반응은 제외."""

def test_load_auto_detect_json():
    """.json 확장자 자동 감지."""

def test_load_auto_detect_xml():
    """.xml 확장자 자동 감지."""
```

**`test_task_parser.py`**:
```python
def test_parse_csv_basic():
    """기본 CSV 파싱."""

def test_parse_medium():
    """Medium 문자열 파싱: 'glc__D_e(-10.0);o2_e(-1000.0)' """

def test_parse_constraints():
    """Constraint 문자열 파싱: 'EX_o2_e(-1000.0#1000.0)' """

def test_parse_expected_operators():
    """> < = 연산자 파싱."""

def test_run_task_metabolite_type():
    """Metabolite type task FBA 실행."""

def test_run_task_reaction_type():
    """Reaction type task FBA 실행."""

def test_run_task_negative_constraint():
    """Negative constraint (=0.0) task 실행."""

def test_run_all_with_progress():
    """전체 task 실행 + progress callback."""
```

**`test_organism_filter.py`**:
```python
async def test_load_organism_reactions():
    """KEGG에서 종 반응 목록 로드 (mocked)."""

async def test_filter_candidates_sets_organism_exists():
    """후보 반응 필터링 후 organism_exists 설정 확인."""

async def test_resolve_kegg_ids_from_annotation():
    """Annotation에서 KEGG ID 추출."""

async def test_resolve_kegg_ids_from_metanetx():
    """MetaNetX → KEGG 매핑."""

async def test_cache_hit_skips_api():
    """캐시 히트 시 API 호출 안 함."""
```

**`test_gapfill_engine.py`**:
```python
async def test_run_full_pipeline(mock_cobra_model):
    """전체 파이프라인 E2E (mocked cobra)."""

def test_task_driven_gapfill():
    """실패한 task별 개별 gap-fill."""

def test_infeasible_task_recorded():
    """Infeasible task가 결과에 기록됨."""

def test_gpr_assigned_to_added_reactions():
    """추가된 반응에 GPR이 할당됨."""

def test_task_results_before_after():
    """Before/after task 결과 비교."""
```

### 8.2 통합 테스트

**`test_integration_gapfill.py`**:
```python
async def test_e2e_ecoli_mini_model():
    """소규모 E. coli 모델로 전체 워크플로우 테스트.

    1. 소규모 SBML 모델 로드 (glycolysis만)
    2. Universal model에서 후보 추출
    3. 종 필터링 (mocked KEGG)
    4. Evidence 평가 (mocked)
    5. Gap-fill 실행
    6. Task 테스트
    7. SBML 내보내기
    """
```

---

## 9. 구현 순서 (Implementation Order)

```
1. src/core/models.py                    ← 데이터 모델 추가
2. src/utils/constants.py                ← 상수 추가
3. src/utils/config.py                   ← 설정 필드 추가
4. src/core/universal_loader.py          ← Universal model 로더
5. src/core/task_parser.py               ← Task 파서 + 러너
6. tests/test_universal_loader.py        ← 테스트
7. tests/test_task_parser.py             ← 테스트
8. src/core/id_mapper.py                 ← resolve_universal() 추가
9. src/gapfill/__init__.py               ← 패키지 초기화
10. src/gapfill/organism_filter.py       ← 종 필터
11. src/gapfill/penalty_calculator.py    ← Penalty 계산
12. src/gapfill/gpr_assigner.py          ← GPR 할당
13. src/gapfill/engine.py                ← Gap-fill 엔진
14. tests/test_organism_filter.py        ← 테스트
15. tests/test_penalty_calculator.py     ← 테스트
16. tests/test_gpr_assigner.py           ← 테스트
17. tests/test_gapfill_engine.py         ← 테스트
18. src/evidence/engine.py               ← evaluate_candidate(s) 추가
19. src/gui/workflow_wizard.py           ← 입력 마법사
20. src/gui/candidate_table.py           ← 후보 테이블
21. src/gui/task_panel.py                ← Task 패널
22. src/gui/gapfill_panel.py             ← Gap-fill 결과 패널
23. src/gui/workers.py                   ← 새 Worker들
24. src/gui/main_window.py               ← 통합
25. src/cli.py                           ← CLI gap-fill 모드
26. tests/test_integration_gapfill.py    ← E2E 테스트
```

---

*Design created: 2026-02-21*
*Feature: gap-filling-platform*
*PDCA Phase: Design*
*Plan reference: docs/01-plan/features/gap-filling-platform.plan.md*
