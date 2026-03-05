# Design: Task Detail Display

## Feature ID
`task-detail-display`

## Reference
- Plan: `docs/01-plan/features/task-detail-display.plan.md`

---

## Implementation Items

총 9개 구현 항목 (A: 테이블 확장 5개, B: 다이얼로그 4개)

---

## Phase A: Detail 테이블 확장

### A-1. 컬럼 구조 변경 (`task_panel.py`)

**현재**: 5 컬럼 — `Task ID | Description | Category | Before | After`
**변경**: 7 컬럼 — `Task ID | Type | Description | Category | Expected | Before | After`

```python
# _setup_ui() 변경
self._detail_table.setColumnCount(7)
self._detail_table.setHorizontalHeaderLabels(
    ["Task ID", "Type", "Description", "Category", "Expected", "Before", "After"]
)
```

컬럼 인덱스 상수:
```python
_COL_TASK_ID = 0
_COL_TYPE = 1
_COL_DESC = 2
_COL_CATEGORY = 3
_COL_EXPECTED = 4
_COL_BEFORE = 5
_COL_AFTER = 6
```

### A-2. 컬럼 리사이즈 설정 (`task_panel.py`)

```python
header = self._detail_table.horizontalHeader()
header.setSectionResizeMode(_COL_TASK_ID, QHeaderView.ResizeMode.ResizeToContents)
header.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
header.setSectionResizeMode(_COL_DESC, QHeaderView.ResizeMode.Stretch)
header.setSectionResizeMode(_COL_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)
header.setSectionResizeMode(_COL_EXPECTED, QHeaderView.ResizeMode.ResizeToContents)
header.setSectionResizeMode(_COL_BEFORE, QHeaderView.ResizeMode.ResizeToContents)
header.setSectionResizeMode(_COL_AFTER, QHeaderView.ResizeMode.ResizeToContents)
```

### A-3. Before/After 셀에 실제 값 표시 (`task_panel.py`)

**현재**: `✅` 또는 `❌` (아이콘만)
**변경**: `✅ 23.45` 또는 `❌ 0.00` (아이콘 + 실제 값)

`_build_detail_table()` 수정:
```python
# Before 값 포맷
icon = "\u2705" if br.passed else "\u274c"
val = _format_value(br.actual_value)
before_item = QTableWidgetItem(f"{icon} {val}")
before_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

# After 값 포맷 (동일 패턴)
icon = "\u2705" if ar.passed else "\u274c"
val = _format_value(ar.actual_value)
after_item = QTableWidgetItem(f"{icon} {val}")
```

헬퍼 함수:
```python
def _format_value(value: float) -> str:
    """실제 시뮬레이션 값을 읽기 좋게 포맷."""
    if value == 0.0:
        return "0"
    if abs(value) < 0.01:
        return f"{value:.2e}"
    if abs(value) >= 1000:
        return f"{value:.1f}"
    return f"{value:.4f}"
```

### A-4. Expected 컬럼 + Type 컬럼 추가 (`task_panel.py`)

`_build_detail_table()` 내부:
```python
# Type (A-4)
type_item = QTableWidgetItem(task.task_type)
self._detail_table.setItem(row, _COL_TYPE, type_item)

# Expected condition (A-4)
expected_text = f"{task.expected_operator}{task.expected_value:g}"
expected_item = QTableWidgetItem(expected_text)
expected_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
self._detail_table.setItem(row, _COL_EXPECTED, expected_item)
```

### A-5. 결과 맵 저장 + 더블클릭 연결 (`task_panel.py`)

`set_results()`에서 맵을 인스턴스 변수로 저장:
```python
def set_results(self, before, after=None):
    self._before_map = {r.task.task_id: r for r in before}
    self._after_map = {r.task.task_id: r for r in after} if after else {}
    # ... 기존 로직
```

`_setup_ui()`에서 더블클릭 시그널 연결:
```python
self._detail_table.cellDoubleClicked.connect(self._on_detail_double_clicked)
```

핸들러:
```python
def _on_detail_double_clicked(self, row: int, _col: int) -> None:
    task_id_item = self._detail_table.item(row, _COL_TASK_ID)
    if not task_id_item:
        return
    task_id = task_id_item.text()
    before_result = self._before_map.get(task_id)
    if not before_result:
        return
    after_result = self._after_map.get(task_id)

    from src.gui.task_detail_dialog import TaskDetailDialog
    dialog = TaskDetailDialog(before_result, after_result, parent=self)
    dialog.exec()
```

---

## Phase B: Task 상세 다이얼로그

### B-1. 파일 생성 (`src/gui/task_detail_dialog.py`)

```python
class TaskDetailDialog(QDialog):
    def __init__(
        self,
        before: TaskResult,
        after: TaskResult | None = None,
        parent=None,
    ) -> None:
```

### B-2. Task Info 섹션

QGroupBox "Task Info" + QFormLayout:
```
Task ID:     U001
Type:        Metabolite
Target:      atp_c
Description: ATP production from glucose (energy metabolism)
Category:    Energy
```

### B-3. Objective + Medium + Constraints 섹션

**Objective** (QGroupBox "Objective Function"):
```
Metabolite 타입 → "Maximize DM_{target_id} (demand reaction for {target_id})"
Reaction 타입  → "Maximize {target_id} flux"
```

**Medium** (QGroupBox "Medium" + QTableWidget 2열):
```
Exchange Reaction  |  Lower Bound
EX_glc__D_e        |  -10.0
EX_o2_e            |  -1000.0
EX_pi_e            |  -1000.0
```

빈 medium → `QLabel("Default (no medium changes)")`

**Constraints** (QGroupBox "Additional Constraints" + QTableWidget 3열):
```
Reaction     |  Lower Bound  |  Upper Bound
EX_o2_e      |  -1000.0      |  1000.0
```

빈 constraints → `QLabel("No additional constraints")`

### B-4. Result 섹션

QGroupBox "Result" + QFormLayout:

```
Expected:       >0.0
Before:         ✅ PASS  (actual: 23.4505)
After:          ✅ PASS  (actual: 25.1230)    [after가 있는 경우만]
Error:          -                              [error_message가 있으면 표시]
```

Before/After QLabel 색상: `_COLOR_PASS_PASS` 등 기존 transition color 재사용

다이얼로그 하단: `QDialogButtonBox(QDialogButtonBox.StandardButton.Close)`

---

## Implementation Order

```
A-1 → A-2 → A-3 → A-4 → A-5 → B-1 → B-2 → B-3 → B-4
```

Phase A는 `task_panel.py`만 수정.
Phase B는 `task_detail_dialog.py` 신규 생성.
Phase A 완료 후 Phase B 진행 (A-5에서 B를 import).

## Affected Files

| File | Action | Items |
|------|--------|-------|
| `src/gui/task_panel.py` | Modified | A-1~A-5 |
| `src/gui/task_detail_dialog.py` | **New** | B-1~B-4 |

## Data Model Changes

없음. `MetabolicTask`와 `TaskResult`에 필요한 모든 필드가 이미 존재:
- `task.task_type`, `task.target_id`, `task.medium`, `task.constraints`
- `task.expected_operator`, `task.expected_value`
- `result.actual_value`, `result.error_message`
