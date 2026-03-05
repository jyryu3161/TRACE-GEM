# Design: Reaction Removal with Task Impact Preview

**Plan Reference**: `docs/01-plan/features/reaction-removal-preview.plan.md`

## 1. Architecture Overview

```
┌─ ReactionTableWidget ──────────────────────────────────────────────┐
│  Right-click → Context Menu → "Remove Reaction..."                │
│  Signal: removal_requested(str)  ─────────────────┐               │
└────────────────────────────────────────────────────┤               │
                                                     ▼               │
┌─ ReactionDetailWidget ─────────┐    ┌─ MainWindow ──────────────┐ │
│  [Remove] button (red)         │    │  _on_removal_requested()  │ │
│  Signal: removal_requested(str)├───►│    ├─ tasks loaded?        │ │
└────────────────────────────────┘    │    │   YES → open          │ │
                                      │    │   ReactionRemovalDialog│ │
                                      │    │   NO → simple confirm │ │
                                      │    └─ on confirm:          │ │
                                      │       _execute_removal()   │ │
                                      └────────────────────────────┘ │
                                                     │               │
                                                     ▼               │
                                      ┌─ ReactionRemovalDialog ───┐ │
                                      │  1. Show "Analyzing..."   │ │
                                      │  2. TaskSimWorker runs    │ │
                                      │  3. Show before/after     │ │
                                      │  4. [Cancel] [Remove]     │ │
                                      └────────────────────────────┘ │
```

## 2. Component Design

### 2.1 ReactionTableWidget — Context Menu

**File**: `src/gui/reaction_table.py`

```python
# New Signal
removal_requested = Signal(str)  # reaction_id

# In _setup_ui():
self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
self._table.customContextMenuRequested.connect(self._show_context_menu)

def _show_context_menu(self, pos: QPoint) -> None:
    index = self._table.indexAt(pos)
    if not index.isValid():
        return
    source_index = self._proxy.mapToSource(index)
    rxn = self._model.get_reaction(source_index.row())
    if not rxn:
        return

    menu = QMenu(self)
    remove_action = menu.addAction("Remove Reaction...")
    action = menu.exec(self._table.viewport().mapToGlobal(pos))
    if action == remove_action:
        self.removal_requested.emit(rxn.id)
```

**Selection Mode**: 기존 SingleSelection 유지. 우클릭 시 해당 행 자동 선택.

### 2.2 ReactionDetailWidget — Remove Button

**File**: `src/gui/reaction_detail.py`

```python
# New Signal
removal_requested = Signal(str)  # reaction_id

# In _setup_ui(), btn_layout section:
self._remove_btn = QPushButton("Remove")
self._remove_btn.setStyleSheet(
    "QPushButton { background-color: #c0392b; color: white; font-weight: bold; }"
    "QPushButton:hover { background-color: #e74c3c; }"
    "QPushButton:disabled { background-color: #555; color: #999; }"
)
self._remove_btn.clicked.connect(self._on_remove_clicked)
self._remove_btn.setEnabled(False)
btn_layout.addWidget(self._remove_btn)

def _on_remove_clicked(self) -> None:
    if self._reaction:
        self.removal_requested.emit(self._reaction.id)

# In set_reaction():
self._remove_btn.setEnabled(True)

# In clear():
self._remove_btn.setEnabled(False)

# In set_read_only():
self._remove_btn.setVisible(not read_only)
```

### 2.3 ReactionRemovalDialog — Impact Preview

**File**: `src/gui/reaction_removal_dialog.py` (신규)

```python
class TaskSimulationSignals(QObject):
    finished = Signal(list)  # list[TaskResult]
    error = Signal(str)


class TaskSimulationWorker(QRunnable):
    """Run tasks on a model copy with the target reaction removed."""

    def __init__(
        self,
        cobra_model: cobra.Model,
        reaction_id: str,
        tasks: list[MetabolicTask],
    ) -> None:
        super().__init__()
        self.signals = TaskSimulationSignals()
        self._cobra_model = cobra_model
        self._reaction_id = reaction_id
        self._tasks = tasks
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            test_model = self._cobra_model.copy()
            rxn = test_model.reactions.get_by_id(self._reaction_id)
            test_model.remove_reactions([rxn])
            runner = TaskRunner()
            results = runner.run_all(test_model, self._tasks)
            _safe_emit(self.signals.finished, results)
        except Exception as e:
            _safe_emit(self.signals.error, str(e))


class ReactionRemovalDialog(QDialog):
    """Dialog showing task impact preview before reaction removal."""

    def __init__(
        self,
        reaction: Reaction,
        cobra_model: cobra.Model,
        tasks: list[MetabolicTask],
        current_results: list[TaskResult],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._reaction = reaction
        self._cobra_model = cobra_model
        self._tasks = tasks
        self._current_results = current_results
        self._confirmed = False
        self._setup_ui()
        self._start_simulation()
```

**Dialog Layout**:

```
┌─────────────────────────────────────────────────────┐
│  Remove Reaction: {rxn.id} ({rxn.name})             │
│                                                     │
│  ┌─ Task Impact Preview ─────────────────────────┐  │
│  │  [QProgressBar or results]                    │  │
│  │                                               │  │
│  │  Before: XX/YY tasks passed                   │  │
│  │  After:  XX/YY tasks passed                   │  │
│  │  Change: ±N tasks                             │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌─ Affected Tasks ──────────────────────────────┐  │
│  │  QTableWidget (Task ID | Category | Change)   │  │
│  │  - color coded: red=PASS→FAIL, blue=FAIL→PASS │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌─ Warning Label ───────────────────────────────┐  │
│  │  (severity-based color and icon)              │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│                        [Cancel]  [Remove Reaction]  │
└─────────────────────────────────────────────────────┘
```

**Warning 레벨**:
| Condition | Color | Icon | Text |
|-----------|-------|------|------|
| 변화 없음 (0) | Green (#27ae60) | None | "No task impact detected" |
| 소폭 감소 (1-3) | Yellow (#f39c12) | Warning | "N task(s) will fail after removal" |
| 대폭 감소 (4+) | Red (#e74c3c) | Critical | "N tasks will fail — significant model impact" |
| 개선 (증가) | Blue (#3498db) | Info | "N task(s) will improve after removal" |

**Remove 버튼**: 시뮬레이션 완료 전 disabled, 완료 후 enabled.

### 2.4 ModelData.remove_reaction()

**File**: `src/core/models.py`

```python
def remove_reaction(self, reaction_id: str) -> Reaction | None:
    """Remove a reaction from the model data.

    Returns the removed Reaction, or None if not found.
    Does NOT modify the cobra_model — caller is responsible.
    """
    for i, rxn in enumerate(self.reactions):
        if rxn.id == reaction_id:
            removed = self.reactions.pop(i)
            # Clean up orphaned metabolites
            remaining_met_ids: set[str] = set()
            for r in self.reactions:
                remaining_met_ids.update(r.reactants.keys())
                remaining_met_ids.update(r.products.keys())
            self.metabolites = [
                m for m in self.metabolites if m.id in remaining_met_ids
            ]
            # Clean up orphaned genes
            remaining_gene_ids: set[str] = set()
            for r in self.reactions:
                remaining_gene_ids.update(g.id for g in r.genes)
            self.genes = [g for g in self.genes if g.id in remaining_gene_ids]
            return removed
    return None
```

### 2.5 MainWindow — Orchestration

**File**: `src/gui/main_window.py`

```python
# In _setup_ui(), after reaction_table and reaction_detail creation:
self._reaction_table.removal_requested.connect(self._on_removal_requested)
self._reaction_detail.removal_requested.connect(self._on_removal_requested)

def _on_removal_requested(self, reaction_id: str) -> None:
    """Handle reaction removal request from table or detail panel."""
    if not self._model or not self._model.cobra_model:
        return

    rxn = self._model.get_reaction(reaction_id)
    if not rxn:
        return

    # If tasks are loaded, show impact preview dialog
    if self._loaded_tasks:
        # Get current task results (run if not available)
        current_results = self._get_current_task_results()
        dialog = ReactionRemovalDialog(
            reaction=rxn,
            cobra_model=self._model.cobra_model,
            tasks=self._loaded_tasks,
            current_results=current_results,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._execute_removal(reaction_id)
    else:
        # Simple confirmation without task preview
        reply = QMessageBox.question(
            self,
            "Remove Reaction",
            f"Remove reaction '{reaction_id}' ({rxn.name})?\n\n"
            "No metabolic tasks loaded — impact preview unavailable.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._execute_removal(reaction_id)

def _execute_removal(self, reaction_id: str) -> None:
    """Actually remove the reaction from both cobra and internal models."""
    import cobra

    # 1. Remove from cobra model
    cm = self._model.cobra_model
    if isinstance(cm, cobra.Model):
        try:
            cobra_rxn = cm.reactions.get_by_id(reaction_id)
            cm.remove_reactions([cobra_rxn], remove_orphans=True)
        except KeyError:
            pass

    # 2. Remove from ModelData
    removed = self._model.remove_reaction(reaction_id)

    # 3. Refresh UI
    self._reaction_table.set_model_data(self._model)
    self._reaction_detail.clear()
    self._overview.set_model(self._model)

    # 4. Auto-save version
    if self._version_manager and self._config.auto_save_on_edit:
        self._version_ctrl.auto_save_version("reaction_removal")

    self._statusbar.showMessage(f"Reaction '{reaction_id}' removed")

def _get_current_task_results(self) -> list[TaskResult]:
    """Get current task results, running simulation if needed."""
    # Use cached results from task_panel if available
    if self._task_panel._before_map:
        return list(self._task_panel._before_map.values())
    # Otherwise run fresh
    if self._model and self._model.cobra_model and self._loaded_tasks:
        runner = TaskRunner()
        return runner.run_all(self._model.cobra_model, self._loaded_tasks)
    return []
```

## 3. Implementation Order

| Step | File | Description |
|------|------|-------------|
| 1 | `src/core/models.py` | `ModelData.remove_reaction()` 메서드 추가 |
| 2 | `src/gui/reaction_removal_dialog.py` | **신규** 파일: Dialog + Worker |
| 3 | `src/gui/reaction_table.py` | Context menu + `removal_requested` Signal |
| 4 | `src/gui/reaction_detail.py` | Remove 버튼 + `removal_requested` Signal |
| 5 | `src/gui/main_window.py` | Signal 연결 + 오케스트레이션 로직 |
| 6 | Tests | 단위 테스트 작성 |

## 4. Data Flow

```
User right-click "Remove Reaction..."
        │
        ▼
ReactionTableWidget.removal_requested.emit(rxn_id)
        │
        ▼
MainWindow._on_removal_requested(rxn_id)
        │
        ├─ tasks loaded? ──NO──► QMessageBox.question() ──Yes──┐
        │                                                       │
        YES                                                     │
        │                                                       │
        ▼                                                       │
ReactionRemovalDialog(rxn, cobra_model, tasks, current_results) │
        │                                                       │
        ├─ TaskSimulationWorker.run()                           │
        │   └─ cobra_model.copy() → remove rxn → run_all()     │
        │                                                       │
        ├─ Show before/after results                            │
        │   └─ Affected tasks table (PASS→FAIL highlighted)     │
        │                                                       │
        ├─ User clicks [Remove]                                 │
        │                                                       │
        ▼                                                       ▼
MainWindow._execute_removal(rxn_id)
        │
        ├─ cobra_model.remove_reactions([rxn], remove_orphans=True)
        ├─ model_data.remove_reaction(rxn_id)
        ├─ Refresh UI (table, detail, overview)
        └─ Auto-save version (if enabled)
```

## 5. Edge Cases

| Case | Handling |
|------|----------|
| Exchange reaction 제거 시도 | 허용 — 사용자 판단에 맡김 |
| 마지막 반응식 제거 | 허용 — 빈 모델 상태 |
| Task가 없는 상태 | 단순 확인 다이얼로그 (impact preview 생략) |
| 시뮬레이션 중 오류 | 에러 메시지 표시, Remove 버튼 비활성 유지 |
| cobra_model이 None | _on_removal_requested 시작 시 early return |
| 이미 제거된 반응식 | get_reaction() → None → early return |

## 6. Testing

### Unit Tests

```python
# test_model_data_removal.py
class TestModelDataRemoval:
    def test_remove_existing_reaction(self, sample_model):
        removed = sample_model.remove_reaction("ENO")
        assert removed is not None
        assert removed.id == "ENO"
        assert sample_model.get_reaction("ENO") is None
        assert sample_model.reaction_count == 2  # was 3

    def test_remove_nonexistent(self, sample_model):
        removed = sample_model.remove_reaction("NONEXISTENT")
        assert removed is None
        assert sample_model.reaction_count == 3  # unchanged

    def test_orphaned_metabolites_cleaned(self, sample_model):
        # If a metabolite only belongs to removed reaction, it should be cleaned
        before_count = sample_model.metabolite_count
        sample_model.remove_reaction("ENO")
        assert sample_model.metabolite_count <= before_count

    def test_orphaned_genes_cleaned(self, sample_model):
        before_count = sample_model.gene_count
        sample_model.remove_reaction("ENO")
        assert sample_model.gene_count <= before_count
```

### GUI Tests (pytest-qt, PySide6 환경에서만)

```python
# test_reaction_removal_dialog.py (skipif PySide6 not available)
class TestReactionRemovalDialog:
    def test_dialog_creation(self, qtbot):
        # Basic instantiation test
        ...

    def test_remove_button_disabled_initially(self, qtbot):
        # Remove button should be disabled until simulation completes
        ...
```
