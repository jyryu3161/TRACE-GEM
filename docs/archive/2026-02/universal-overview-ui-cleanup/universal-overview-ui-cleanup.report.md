# Completion Report: Universal Overview & UI Cleanup

> Feature: universal-overview-ui-cleanup
> Date: 2026-02-23
> PDCA Cycle: Plan → Do → Iterate → Report

---

## 1. Executive Summary

GEM Evaluator의 Universal Model UI를 개선하여, 중복 탭 제거 및 Model Overview 통합, 반응식 표시 개선, 워크플로우 안정성 강화를 완료.

| 항목 | 결과 |
|------|------|
| **Tests** | 497 pass (3 pre-existing failures) |
| **신규 코드** | ~430 LOC (12 files) |
| **수정 파일** | 12 files |
| **Lint** | 0 new warnings (16 pre-existing) |
| **버그 수정** | 4건 (Critical 1, Minor 3) |
| **Iteration** | 1회 (PDCA iterate 검토) |

---

## 2. Requirements Completion

### REQ-1: Universal Model Overview

| 항목 | 상태 | 세부 |
|------|------|------|
| Model Overview 탭 레이아웃 | DONE | QTabWidget으로 "Model" / "Universal" 탭 구성 |
| Universal 정보 표시 | DONE | Model ID, Total Reactions, Excluded, Candidates, Evaluated |
| 동적 탭 관리 | DONE | `set_universal_info()`로 추가, `clear_universal()`로 제거 |
| Evaluation count 업데이트 | DONE | `update_universal_evaluation_count()` 메서드 |

### REQ-2: Candidates 탭 제거

| 항목 | 상태 | 세부 |
|------|------|------|
| "Candidates" 탭 제거 | DONE | `_candidate_table` 인스턴스 및 시그널 핸들러 제거 |
| Gap-fill 결과 Universal 탭 이동 | DONE | `_on_gapfill_complete/cancelled` → `_universal_table` 사용 |
| import 정리 | DONE | `CandidateTableWidget`은 Universal 탭 용도로 유지 |

### 추가 개선 (Plan 외)

| 항목 | 상태 | 세부 |
|------|------|------|
| Equation ID 표시 | DONE | 테이블에 `equation_id` (metabolite ID 기반) 표시 |
| Detail 패널 이중 표시 | DONE | "Equation (ID)" read-only + "Equation (Name)" 편집 가능 |
| Workflow Wizard 경로 재사용 | DONE | 이전 로드 경로 `universal_path` 전달 |
| Cancel 버튼 개선 | DONE | `asyncio.Event` 기반 세밀한 취소 체크 포인트 |
| Null model guard | DONE | `_load_universal_model()` 호출 시 모델 없으면 경고 |

---

## 3. Implementation Details

### 3.1 Model Overview 탭 구조 변경

**파일**: `src/gui/model_overview.py` (+67 lines)

기존 stacked GroupBox 레이아웃을 `QTabWidget`으로 변경:
- **Model 탭**: 기존 정보 (ID, Name, Organism, KEGG Code, Reactions, Metabolites, Genes, Subsystems, Evaluated)
- **Universal 탭**: 동적 추가/제거 (Model ID, Total Reactions, Excluded, Candidates, Evaluated)

주요 메서드:
- `set_universal_info()` — Universal 탭 생성 및 정보 표시
- `update_universal_evaluation_count()` — 평가 진행률 갱신
- `clear_universal()` — Universal 탭 제거

### 3.2 Main Window 리팩토링

**파일**: `src/gui/main_window.py` (+233/-13 lines)

변경 사항:
1. `_candidate_table` 제거 (탭, delegate, 시그널 핸들러)
2. `_loaded_universal_path` 상태 추가 — 워크플로우 시작 시 재사용
3. `_load_universal_model()` null guard 추가
4. `_on_gapfill_complete()` / `_on_gapfill_cancelled()` → `_universal_table` 사용
5. `WorkflowWizard`에 `universal_path` 전달

### 3.3 Equation ID 표시

**파일**: `src/core/models.py` (+18), `src/core/sbml_parser.py` (+1), `src/core/universal_loader.py` (+1)

- `Reaction` 데이터클래스에 `equation_id: str = ""` 필드 추가
- SBML/Universal 파서에서 `rxn.build_reaction_string(use_metabolite_names=False)` 호출

**파일**: `src/gui/reaction_table.py` (+4/-1), `src/gui/candidate_table.py` (+43)

- 테이블 COL_EQUATION에 `rxn.equation_id or rxn.equation` 표시
- 툴팁도 동일

**파일**: `src/gui/reaction_detail.py` (+29)

- "Equation (ID)" GroupBox: read-only `QTextEdit` (`_equation_id_display`)
- "Equation (Name)" GroupBox: 편집 가능 `QTextEdit` (`_equation_edit`)

### 3.4 Worker 안정성

**파일**: `src/gui/workers.py` (+61)

- `GapFillWorkflowWorker`에 `asyncio.Event` 기반 cancel mechanism
- 5-phase 파이프라인 각 단계별 `_is_cancelled()` 체크
- `_cancel_event.set()`으로 안전한 중단

---

## 4. Bug Fixes (Iterate Phase)

| # | 심각도 | 파일 | 내용 |
|---|--------|------|------|
| 1 | Critical | `main_window.py` | `_load_universal_model()`: `self._model` null 상태에서 crash. Guard 추가 |
| 2 | Minor | `conftest.py` | `sample_reaction` fixture에 `equation_id` 누락 → 추가 |
| 3 | Minor | `test_gui_widgets.py` | 존재하지 않는 `ev.directionality_match` 속성 사용 → 제거 |
| 4 | Minor | `test_gui_widgets.py` | `equation_id` 표시 검증 assertion 추가 |

---

## 5. Affected Files

| File | Change Type | LOC |
|------|-------------|-----|
| `src/gui/main_window.py` | Modified | +233/-13 |
| `src/gui/model_overview.py` | Modified | +67/-6 |
| `src/gui/workers.py` | Modified | +61/-9 |
| `src/gui/candidate_table.py` | Modified | +43/-1 |
| `src/gui/reaction_detail.py` | Modified | +29/-3 |
| `src/core/models.py` | Modified | +18 |
| `src/gui/workflow_wizard.py` | Modified | +7 |
| `tests/test_gui_widgets.py` | Modified | +5/-1 |
| `src/gui/reaction_table.py` | Modified | +4/-1 |
| `src/core/sbml_parser.py` | Modified | +1 |
| `src/core/universal_loader.py` | Modified | +1 |
| `tests/conftest.py` | Modified | +1 |
| **Total** | **12 files** | **+430/-40** |

---

## 6. Test Results

```
497 passed, 3 failed (pre-existing), 11 warnings
```

Pre-existing failures (unchanged):
- `test_integration.py::TestModelLoading::test_eno_reaction`
- `test_integration.py::TestModelLoading::test_subsystems`
- `test_sbml_parser.py::TestSBMLParser::test_subsystems`

---

## 7. Lessons Learned

1. **Null guard 필수**: 상태 의존적 메서드는 반드시 전제 조건 검증 필요 (`self._model` 등)
2. **Fixture 동기화**: 모델에 필드를 추가하면 관련 테스트 fixture도 즉시 업데이트
3. **탭 레이아웃 우월성**: 조건부로 보이는 정보(Universal model)는 GroupBox보다 탭이 공간 효율적
4. **Equation 이중 표시**: 사용자는 metabolite ID(equation_id)와 이름(equation)을 모두 필요로 함 — read-only/editable 분리가 효과적
