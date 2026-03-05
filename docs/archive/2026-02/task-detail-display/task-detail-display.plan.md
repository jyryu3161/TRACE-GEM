# Plan: Task Detail Display

## Feature ID
`task-detail-display`

## Summary
Metabolic task 평가 결과에 실제 시뮬레이션 값, 조건, objective function 등 상세 정보를 표시하고, 각 task를 클릭하면 상세 다이얼로그로 볼 수 있도록 개선

## Problem Statement

현재 TaskPanelWidget의 Detail 테이블:
- 컬럼: `Task ID | Description | Category | Before | After`
- Before/After 셀에는 체크/엑스 아이콘만 표시
- **실제로 어떤 값이 나왔는지** (actual_value) 보이지 않음
- **기대 조건** (expected_operator + expected_value, 예: `>0.0`) 보이지 않음
- **어떤 배지/조건** (medium, constraints)에서 실행되었는지 알 수 없음
- **objective function** (task_type + target_id)이 무엇이었는지 표시 안 됨

## Requirements

### REQ-1: Detail 테이블에 실제 값 표시
- Before/After 컬럼에 pass/fail 아이콘 + 실제 값을 함께 표시
- 형식: `✅ 23.45` 또는 `❌ 0.00`
- 기대 조건 컬럼 추가: `>0.0`, `<50.0`, `=0.0` 등
- 사용자가 통과 여부의 근거를 한눈에 파악

### REQ-2: Task 상세 다이얼로그
- Detail 테이블의 행을 더블클릭 (또는 "Details" 버튼)하면 다이얼로그 표시
- 다이얼로그에 표시할 정보:
  1. **Task Info**: Task ID, Type, Target ID, Description, Category
  2. **Objective**: objective function이 무엇이었는지 (Metabolite demand / Reaction flux)
  3. **Medium**: 어떤 배지 설정으로 실행했는지 (exchange reaction → lower_bound 목록)
  4. **Constraints**: 추가 제약 조건 목록 (reaction → lower#upper)
  5. **Expected**: 기대 조건 (`>0.0` 등)
  6. **Result**: 실제 시뮬레이션 값, pass/fail, error message (있는 경우)
  7. **Before/After 비교**: gap-fill 전후 값 비교 (있는 경우)

### REQ-3: Expected 조건 컬럼 추가
- Detail 테이블에 "Expected" 컬럼 추가 (Before/After 사이)
- 형식: `>0.0`, `<50.0`, `=0.0`, `>=1.0` 등

## Current State Analysis

### TaskResult 데이터 (`models.py:232`)
```python
@dataclass
class TaskResult:
    task: MetabolicTask  # 원본 task 정보 전체 포함
    passed: bool
    actual_value: float
    error_message: str | None = None
    phase: str = "before"
```
- `actual_value`가 이미 저장되어 있지만 UI에 표시하지 않음
- `task.medium`, `task.constraints`, `task.expected_operator`, `task.expected_value` 모두 접근 가능

### TaskPanelWidget (`task_panel.py`)
- `_build_detail_table()`: Before/After 셀에 아이콘만 설정
- `set_results()`: before/after 리스트를 받아 테이블 구성
- 행 클릭/더블클릭 이벤트 없음

## Implementation Plan

### Phase A: Detail 테이블 확장
1. `_build_detail_table()` 수정:
   - "Expected" 컬럼 추가 (기대 조건 표시)
   - Before/After 셀 형식: `✅ 23.45` / `❌ 0.00`
   - 컬럼 순서: `Task ID | Type | Description | Category | Expected | Before | After`
2. 컬럼 폭 조정 (Expected는 ResizeToContents, Before/After도 적당히)

### Phase B: Task 상세 다이얼로그
1. `TaskDetailDialog` 생성 (`src/gui/task_detail_dialog.py`)
   - QDialog + QFormLayout
   - **Task Info 섹션**: Task ID, Type (Metabolite/Reaction), Target ID, Description, Category
   - **Objective 섹션**: "Maximize DM_{target_id}" (Metabolite) / "Maximize {target_id}" (Reaction)
   - **Medium 섹션**: QTableWidget로 exchange reaction → bound 표시
   - **Constraints 섹션**: QTableWidget로 reaction → lower/upper 표시
   - **Result 섹션**:
     - Expected condition: `>0.0`
     - Before result: actual_value, pass/fail
     - After result: actual_value, pass/fail (있는 경우)
     - Error message (있는 경우)
2. `TaskPanelWidget`에 더블클릭 시그널 연결
   - `_detail_table.cellDoubleClicked` → `_show_task_detail()`

### Phase C: 연동
1. `TaskPanelWidget`에 before/after 결과 맵 저장 (더블클릭 시 참조)
2. `TaskDetailDialog`에 before/after `TaskResult` 전달

## Affected Files
- `src/gui/task_panel.py` — 테이블 확장, 더블클릭 핸들러
- `src/gui/task_detail_dialog.py` — 신규 파일 (상세 다이얼로그)

## Out of Scope
- MetabolicTask/TaskResult 데이터 구조 변경 (이미 필요한 정보 모두 보유)
- TaskParser/TaskRunner 수정 없음
- CSV 파일 형식 변경 없음
