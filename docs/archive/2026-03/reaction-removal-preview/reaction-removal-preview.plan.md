# Plan: Reaction Removal with Task Impact Preview

## 1. Overview

**Feature**: 대사 모델에서 반응식을 클릭으로 쉽게 제거하고, 제거 전 task 성공 개수 변화를 미리 확인할 수 있는 기능

**Problem**: 현재 GUI에는 반응식 제거 기능이 없음. 반응식 선택, 편집(이름/bounds/GPR), 평가 기능만 존재. 사용자가 불필요한 반응식을 모델에서 제거하려면 외부 도구를 사용해야 함.

**Solution**: 반응식 테이블에서 우클릭 컨텍스트 메뉴 또는 상세 패널의 "Remove" 버튼을 통해 반응식 제거 요청 → task 시뮬레이션으로 제거 전/후 성공 개수 비교 → 확인 다이얼로그에서 최종 삭제 결정

## 2. User Flow

```
1. 사용자가 반응식 테이블에서 반응식 선택
2. 우클릭 → "Remove Reaction..." 메뉴 클릭
   (또는 상세 패널의 "Remove" 버튼 클릭)
3. [Impact Preview Dialog] 표시:
   - "Analyzing impact..." 프로그레스 표시
   - COBRApy 모델 복사본에서 해당 반응식 제거
   - TaskRunner.run_all()로 제거 후 task 결과 시뮬레이션
   - 결과 표시:
     ┌─────────────────────────────────────┐
     │  Remove Reaction: ENO (enolase)     │
     │                                     │
     │  Task Impact Preview                │
     │  ─────────────────────────────────  │
     │  Before: 45/52 tasks passed         │
     │  After:  38/52 tasks passed         │
     │  Change: -7 tasks will FAIL         │
     │                                     │
     │  Affected Tasks:                    │
     │  ┌───────────────────────────────┐  │
     │  │ T001  Glycolysis   PASS→FAIL │  │
     │  │ T003  ATP prod     PASS→FAIL │  │
     │  │ T012  Growth       PASS→FAIL │  │
     │  │ ...                          │  │
     │  └───────────────────────────────┘  │
     │                                     │
     │  ⚠ Warning: 7 tasks will fail      │
     │                                     │
     │  [Cancel]              [Remove]     │
     └─────────────────────────────────────┘
4. 사용자 확인 → 실제 모델에서 반응식 제거
5. 버전 시스템에 변경 기록
```

## 3. Scope

### In Scope
- 반응식 테이블 우클릭 컨텍스트 메뉴 ("Remove Reaction...")
- 반응식 상세 패널 "Remove" 버튼
- Task impact preview 다이얼로그 (제거 전/후 task 성공 개수 비교)
- 영향받는 task 목록 표시 (PASS→FAIL 전환 항목)
- COBRApy 모델 + 내부 ModelData 동기 제거
- 버전 시스템 기록 (change_type = "reaction_removal")

### Out of Scope
- 다중 반응식 일괄 제거 (v2에서 고려)
- Undo/Redo 기능 (기존 버전 시스템의 restore로 대체)
- 반응식 추가 기능

## 4. Technical Approach

### 4.1 Context Menu (reaction_table.py)
- `ReactionTableWidget`에 `customContextMenu` 이벤트 핸들러 추가
- 우클릭 시 "Remove Reaction..." 메뉴 항목 표시
- `reaction_removal_requested` Signal 추가

### 4.2 Remove Button (reaction_detail.py)
- 버튼 레이아웃에 "Remove" 버튼 추가 (빨간색 강조)
- `removal_requested` Signal 추가

### 4.3 Impact Preview Dialog (신규: reaction_removal_dialog.py)
- `QDialog` 서브클래스
- Worker thread에서 task 시뮬레이션 수행:
  1. `model.cobra_model.copy()` → 반응식 제거
  2. `TaskRunner.run_all(modified_model, tasks)` 실행
  3. 기존 결과와 비교
- 결과 표시: before/after 카운트, 변화량, 영향받는 task 목록
- Warning 레벨: 0 변화(초록), 1-3 감소(노랑), 4+ 감소(빨강)

### 4.4 Actual Removal (main_window.py)
- 확인 후 실제 제거 수행:
  1. `cobra_model.remove_reactions([rxn])` — COBRApy 모델에서 제거
  2. `ModelData.reactions` 리스트에서 제거
  3. 관련 metabolites 정리 (orphaned metabolites 제거)
  4. `ReactionTableModel` 갱신
  5. 버전 스냅샷 생성

### 4.5 Task 결과 조건
- Tasks가 로드되지 않은 경우: task preview 없이 단순 확인 다이얼로그
- Tasks가 로드된 경우: 전체 impact preview 표시

## 5. Files to Modify

| File | Change |
|------|--------|
| `src/gui/reaction_table.py` | 우클릭 컨텍스트 메뉴, `removal_requested` Signal |
| `src/gui/reaction_detail.py` | "Remove" 버튼 추가, `removal_requested` Signal |
| `src/gui/reaction_removal_dialog.py` | **신규** — Impact preview 다이얼로그 |
| `src/gui/main_window.py` | Signal 연결, 제거 로직 오케스트레이션 |
| `src/gui/workers.py` | `TaskSimulationWorker` 추가 (impact preview용) |
| `src/core/models.py` | `ModelData.remove_reaction()` 메서드 추가 |

## 6. Dependencies

- COBRApy: `model.remove_reactions()` API 사용
- 기존 `TaskRunner`: task 시뮬레이션에 재사용
- 기존 `VersionManager`: 변경 기록에 사용
- Tasks CSV 파일이 로드된 상태여야 impact preview 가능

## 7. Testing Strategy

- `test_reaction_removal_dialog.py`: Dialog 생성 및 결과 표시 테스트
- `test_model_data_removal.py`: ModelData.remove_reaction() 단위 테스트
- 기존 `test_task_parser.py`: TaskRunner가 반응식 제거 후에도 정상 동작 확인
