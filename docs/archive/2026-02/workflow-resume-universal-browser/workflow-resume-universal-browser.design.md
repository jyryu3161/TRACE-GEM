# Design: Workflow Resume & Universal Model Browser

> Plan 참조: `docs/01-plan/features/workflow-resume-universal-browser.plan.md`

---

## 0. 파일 변경 목록

### Phase A: Cancel Recovery (수정 파일)

| 파일 | 변경 |
|------|------|
| `src/core/models.py` | `GapFillResult`에 `completed_phase`, `all_candidates`, `is_partial` 필드 추가. `WorkflowCheckpoint` dataclass 추가 |
| `src/gapfill/engine.py` | `run()`에 `cancel_event` 파라미터 추가, 각 Phase 전 cancel 체크, partial result 반환 |
| `src/gui/workers.py` | `GapFillWorkerSignals`에 `cancelled` signal 추가. `GapFillWorkflowWorker`에 `_cancel_event`, `cancel()` 메서드 추가 |
| `src/gui/main_window.py` | `_on_gapfill_cancelled()` 핸들러, `_workflow_checkpoint` 필드, cancel 시 Phase별 부분 UI 업데이트 |
| `src/gui/gapfill_panel.py` | `set_partial_result()` 메서드, "Resume available" 배너 |

### Phase B: Resume (수정 파일)

| 파일 | 변경 |
|------|------|
| `src/gui/main_window.py` | `_start_workflow()`에서 checkpoint 확인, Resume 다이얼로그, checkpoint 초기화 |
| `src/gui/workers.py` | `GapFillWorkflowWorker`에 checkpoint 기반 resume 파라미터 추가 |
| `src/gapfill/engine.py` | `run()`에 `start_phase`, `preloaded_before` 파라미터로 Phase 스킵 |

### Phase C: Universal Model Browser (수정 + 신규)

| 파일 | 변경 |
|------|------|
| `src/gui/main_window.py` | "Load Universal Model..." 메뉴, Universal 탭, 반응 클릭 → detail 연동, evaluate 연동 |
| `src/gui/candidate_table.py` | `set_mode()` 메서드 — browse 모드에서 evaluate 버튼, overview 헤더 표시 |
| `src/gui/reaction_detail.py` | `set_read_only()` 메서드 — universal 반응 읽기 전용 표시 |

### 테스트

| 파일 | 설명 |
|------|------|
| `tests/test_gapfill_engine.py` | cancel recovery, partial result, start_phase 스킵 테스트 |
| `tests/test_gui_task_panel.py` | (기존) partial result UI 관련 테스트 추가 |

---

## 1. 데이터 모델 (`src/core/models.py` 변경)

### 1.1 GapFillResult 확장

```python
@dataclass
class GapFillResult:
    """Complete result of a gap-filling workflow."""

    # 기존 필드
    added_reactions: list[CandidateReaction] = field(default_factory=list)
    task_results_before: list[TaskResult] = field(default_factory=list)
    task_results_after: list[TaskResult] = field(default_factory=list)
    tasks_fixed: int = 0
    total_tasks: int = 0
    iterations: int = 0
    infeasible_tasks: list[str] = field(default_factory=list)

    # 신규 필드
    completed_phase: int = 0          # 0~5, 완료된 Phase 번호
    all_candidates: list[CandidateReaction] = field(default_factory=list)  # Phase 2 이후 전체 후보
    is_partial: bool = False          # Cancel로 인한 부분 결과 여부
```

### 1.2 WorkflowCheckpoint (신규)

```python
@dataclass
class WorkflowCheckpoint:
    """Gap-fill workflow 중단점 — 메모리 보관용."""

    completed_phase: int              # 완료된 Phase (0~5)
    result: GapFillResult             # 부분 결과
    universal_path: str               # universal model 경로
    task_path: str | None             # task 파일 경로
    options: dict = field(default_factory=dict)  # WorkflowWizard 설정
    timestamp: str = ""               # ISO 8601
```

---

## 2. Phase A: Cancel Recovery

### 2.1 GapFillEngine 변경 (`src/gapfill/engine.py`)

`run()` 메서드에 `cancel_event` 파라미터 추가. 각 Phase 시작 전 cancel 체크.

```python
async def run(
    self,
    user_model: cobra.Model,
    universal_model: cobra.Model,
    candidates: list[CandidateReaction],
    tasks: list[MetabolicTask],
    evidence_results: dict[str, ReactionEvidence],
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    cancel_event: asyncio.Event | None = None,       # 신규
    start_phase: int = 1,                              # 신규 (Phase B용)
    preloaded_before: list[TaskResult] | None = None,  # 신규 (Phase B용)
) -> GapFillResult:
```

**Cancel 체크 패턴** — 각 Phase 완료 후:

```python
result = GapFillResult(total_tasks=len(tasks))
result.all_candidates = list(candidates)  # Phase 2 전 전체 후보 보관

def _is_cancelled() -> bool:
    return cancel_event is not None and cancel_event.is_set()

# Phase 1
if start_phase <= 1:
    result.task_results_before = self._run_tasks(...)
    result.completed_phase = 1

    if _is_cancelled():
        result.is_partial = True
        return result

# Phase 2
if start_phase <= 2:
    await self._organism_filter.filter_candidates(candidates, ...)
    result.all_candidates = list(candidates)  # 필터 결과 갱신
    result.completed_phase = 2

    if _is_cancelled():
        result.is_partial = True
        return result

# Phase 3
if start_phase <= 3:
    added_reactions = await self._run_gapfill(...)
    result.added_reactions = self._apply_gapfill_results(...)
    result.completed_phase = 3

    if _is_cancelled():
        result.is_partial = True
        return result

# Phase 4
if start_phase <= 4:
    await self._gpr_assigner.assign_batch(...)
    result.completed_phase = 4

    if _is_cancelled():
        result.is_partial = True
        return result

# Phase 5
result.task_results_after = self._run_tasks(...)
result.completed_phase = 5
# tasks_fixed 계산 (기존 로직)
```

### 2.2 Worker 변경 (`src/gui/workers.py`)

#### GapFillWorkerSignals 확장

```python
class GapFillWorkerSignals(QObject):
    """Signals for gap-fill workflow with phase-aware progress."""

    started = Signal()
    progress = Signal(str, int, int, str)  # phase, current, total, detail
    result = Signal(object)                # GapFillResult (완료 시)
    cancelled = Signal(object, int)        # (GapFillResult, completed_phase) — cancel 시
    error = Signal(str)
    finished = Signal()
```

#### GapFillWorkflowWorker 변경

```python
class GapFillWorkflowWorker(QRunnable):
    def __init__(
        self,
        config: Config,
        model_data: ModelData,
        universal_path: str,
        task_path: str | None,
        evidence_engine: EvidenceEngine | None,
        options: dict,
        # 신규: resume 파라미터
        start_phase: int = 1,
        preloaded_before: list[TaskResult] | None = None,
        preloaded_candidates: list[CandidateReaction] | None = None,
    ) -> None:
        super().__init__()
        # ... 기존 필드들
        self._start_phase = start_phase
        self._preloaded_before = preloaded_before
        self._preloaded_candidates = preloaded_candidates
        self._cancel_event: asyncio.Event | None = None
        self.setAutoDelete(False)  # cancel 대비 GC 방지

    def cancel(self) -> None:
        """Request pipeline cancellation."""
        if self._cancel_event:
            self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        _safe_emit(self.signals.started)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._cancel_event = asyncio.Event()
            try:
                result = loop.run_until_complete(self._run_pipeline())
                if isinstance(result, GapFillResult) and result.is_partial:
                    _safe_emit(self.signals.cancelled, result, result.completed_phase)
                else:
                    _safe_emit(self.signals.result, result)
            finally:
                loop.close()
        except Exception as e:
            logger.error("Gap-fill workflow error: %s\n%s", e, traceback.format_exc())
            _safe_emit(self.signals.error, str(e))
        finally:
            _safe_emit(self.signals.finished)

    async def _run_pipeline(self) -> object:
        # ... 기존 Step 1~4 (loading, extracting, parsing, evaluating)
        # 단, start_phase > 1이면 candidates 로딩 후 바로 engine.run()으로 전달

        # Step 5: Run gap-fill engine
        result = await engine.run(
            user_model=cobra_model,
            universal_model=universal_model,
            candidates=candidates,
            tasks=tasks,
            evidence_results=evidence_results,
            progress_callback=on_progress,
            cancel_event=self._cancel_event,          # 신규
            start_phase=self._start_phase,             # 신규
            preloaded_before=self._preloaded_before,   # 신규
        )
        return result
```

### 2.3 MainWindow 변경 (`src/gui/main_window.py`)

#### 필드 추가

```python
class MainWindow(QMainWindow):
    def __init__(self, config: Config) -> None:
        # ... 기존 필드
        self._workflow_checkpoint: WorkflowCheckpoint | None = None  # 신규
```

#### _run_gapfill_workflow 변경

```python
def _run_gapfill_workflow(self, selections: dict) -> None:
    """Start the gap-filling workflow worker."""
    if not self._model:
        return

    dialog = ProgressDialog("Gap-Fill Workflow", self)

    worker = GapFillWorkflowWorker(
        config=self._config,
        model_data=self._model,
        universal_path=selections.get("universal_model_path", ""),
        task_path=selections.get("task_file_path"),
        evidence_engine=self._engine,
        options=selections,
    )
    self._gapfill_worker = worker
    self._active_workers.append(worker)  # GC 방지

    def on_progress(phase: str, current: int, total: int, detail: str) -> None:
        display = f"[{phase}] {detail}"
        dialog.update_progress(current, total, display)

    worker.signals.progress.connect(on_progress)
    worker.signals.result.connect(lambda r: self._on_gapfill_complete(r, dialog))
    worker.signals.cancelled.connect(
        lambda r, p: self._on_gapfill_cancelled(r, p, dialog, selections)
    )
    worker.signals.error.connect(lambda e: self._on_gapfill_error(e, dialog))
    worker.signals.finished.connect(
        lambda: self._active_workers.remove(worker) if worker in self._active_workers else None
    )

    # Cancel 버튼 연결
    dialog.cancel_requested.connect(worker.cancel)

    self._thread_pool.start(worker)
    dialog.exec()
```

#### _on_gapfill_cancelled 핸들러 (신규)

```python
def _on_gapfill_cancelled(
    self,
    result: GapFillResult,
    completed_phase: int,
    dialog: ProgressDialog,
    selections: dict,
) -> None:
    """Handle workflow cancellation with partial results."""
    dialog.set_complete()
    self._gapfill_worker = None

    # Checkpoint 저장
    from datetime import datetime
    self._workflow_checkpoint = WorkflowCheckpoint(
        completed_phase=completed_phase,
        result=result,
        universal_path=selections.get("universal_model_path", ""),
        task_path=selections.get("task_file_path"),
        options=selections,
        timestamp=datetime.now().isoformat(),
    )

    # Phase별 부분 UI 업데이트
    if completed_phase >= 1 and result.task_results_before:
        self._task_panel.set_results(result.task_results_before)

    if completed_phase >= 2 and result.all_candidates:
        self._candidate_table.set_candidates(result.all_candidates)
        self._left_tabs.setCurrentWidget(self._candidate_table)

    if completed_phase >= 3 and result.added_reactions:
        self._gapfill_panel.set_partial_result(result)
        self._right_tabs.setCurrentWidget(self._gapfill_panel)

    if completed_phase >= 4:
        # GPR 할당 완료 — gapfill_panel에 반영됨
        pass

    self._statusbar.showMessage(
        f"Workflow cancelled at Phase {completed_phase}/5 — Resume available"
    )
```

### 2.4 GapFillPanel 변경 (`src/gui/gapfill_panel.py`)

#### set_partial_result 메서드 (신규)

```python
def set_partial_result(self, result: GapFillResult) -> None:
    """Display partial results from a cancelled workflow."""
    phase = result.completed_phase
    added = len(result.added_reactions)

    # 배너 표시
    self._summary_label.setText(
        f"Partial result (Phase {phase}/5): {added} reactions added — "
        f"Resume available"
    )
    self._summary_label.setStyleSheet("color: #f0ad4e; font-weight: bold;")

    # added reactions가 있으면 테이블에 표시
    if result.added_reactions:
        self._reaction_table.setSortingEnabled(False)
        self._reaction_table.setRowCount(added)
        for row, candidate in enumerate(result.added_reactions):
            rxn = candidate.reaction
            self._reaction_table.setItem(row, 0, QTableWidgetItem(rxn.id))
            self._reaction_table.setItem(row, 1, QTableWidgetItem(rxn.name))

            score_item = QTableWidgetItem()
            score_item.setData(Qt.ItemDataRole.DisplayRole, f"{candidate.penalty:.1f}")
            score_item.setData(Qt.ItemDataRole.UserRole, candidate.penalty)
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._reaction_table.setItem(row, 2, score_item)

            gpr = candidate.assigned_gpr or "-"
            self._reaction_table.setItem(row, 3, QTableWidgetItem(gpr))
            self._reaction_table.setItem(row, 4, QTableWidgetItem(""))

        self._reaction_table.setSortingEnabled(True)
        self._reaction_table.sortByColumn(2, Qt.SortOrder.DescendingOrder)

    # 버튼 비활성화 (partial result는 apply 불가)
    self._apply_btn.setEnabled(False)
    self._export_sbml_btn.setEnabled(False)
    self._export_report_btn.setEnabled(added > 0)
```

### 2.5 ProgressDialog Cancel 버튼

기존 `ProgressDialog`에 `cancel_requested` Signal 추가:

```python
class ProgressDialog(QDialog):
    cancel_requested = Signal()  # 신규

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        # ... 기존 UI 설정

        # Cancel 버튼 추가
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel_btn)

    def _on_cancel(self) -> None:
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelling...")
        self.cancel_requested.emit()
```

---

## 3. Phase B: Resume Workflow

### 3.1 MainWindow _start_workflow 변경

```python
def _start_workflow(self) -> None:
    """Open the workflow wizard and start gap-filling."""
    if not self._model:
        QMessageBox.warning(self, "No Model", "Load an SBML model first.")
        return

    # Checkpoint 확인
    if self._workflow_checkpoint:
        cp = self._workflow_checkpoint
        reply = QMessageBox.question(
            self,
            "Resume Workflow",
            f"이전 분석이 Phase {cp.completed_phase}/5까지 완료되었습니다.\n"
            f"이어서 진행하시겠습니까?\n\n"
            f"Timestamp: {cp.timestamp}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return
        if reply == QMessageBox.StandardButton.Yes:
            self._resume_workflow()
            return
        # No → checkpoint 삭제, 새로 시작
        self._workflow_checkpoint = None

    from src.gui.workflow_wizard import WorkflowWizard

    wizard = WorkflowWizard(self._config, self._model, self)
    if wizard.exec() != QDialog.DialogCode.Accepted:
        return

    selections = wizard.get_selections()
    self._run_gapfill_workflow(selections)
```

### 3.2 _resume_workflow (신규)

```python
def _resume_workflow(self) -> None:
    """Resume a cancelled workflow from checkpoint."""
    cp = self._workflow_checkpoint
    if not cp or not self._model:
        return

    dialog = ProgressDialog("Gap-Fill Workflow (Resume)", self)

    worker = GapFillWorkflowWorker(
        config=self._config,
        model_data=self._model,
        universal_path=cp.universal_path,
        task_path=cp.task_path,
        evidence_engine=self._engine,
        options=cp.options,
        start_phase=cp.completed_phase + 1,
        preloaded_before=cp.result.task_results_before if cp.result else None,
        preloaded_candidates=cp.result.all_candidates if cp.result else None,
    )
    self._gapfill_worker = worker
    self._active_workers.append(worker)

    def on_progress(phase: str, current: int, total: int, detail: str) -> None:
        display = f"[Resume Phase {cp.completed_phase + 1}+] [{phase}] {detail}"
        dialog.update_progress(current, total, display)

    worker.signals.progress.connect(on_progress)
    worker.signals.result.connect(lambda r: self._on_gapfill_complete(r, dialog))
    worker.signals.cancelled.connect(
        lambda r, p: self._on_gapfill_cancelled(r, p, dialog, cp.options)
    )
    worker.signals.error.connect(lambda e: self._on_gapfill_error(e, dialog))
    worker.signals.finished.connect(
        lambda: self._active_workers.remove(worker) if worker in self._active_workers else None
    )
    dialog.cancel_requested.connect(worker.cancel)

    # Checkpoint 소비 (성공 시 초기화)
    self._workflow_checkpoint = None

    self._thread_pool.start(worker)
    dialog.exec()
```

### 3.3 GapFillEngine start_phase 로직

`run()` 메서드에서 `start_phase` > 1 이면 이전 Phase 결과를 preloaded로 사용:

```python
async def run(self, ..., start_phase=1, preloaded_before=None):
    result = GapFillResult(total_tasks=len(tasks))
    result.all_candidates = list(candidates)

    # Phase 1: 이전 결과 재활용 또는 새로 실행
    if start_phase <= 1:
        result.task_results_before = self._run_tasks(...)
        result.completed_phase = 1
        if _is_cancelled(): ...
    elif preloaded_before:
        result.task_results_before = preloaded_before
        result.completed_phase = 1

    # Phase 2~5: start_phase 기준으로 스킵
    if start_phase <= 2:
        # organism filtering 실행
        ...
    # ... 이하 동일 패턴
```

### 3.4 Checkpoint 초기화 시점

```python
def _on_model_loaded(self, model_data: ModelData) -> None:
    # 기존 로직 ...
    self._workflow_checkpoint = None  # 새 모델 로드 시 이전 checkpoint 삭제
```

---

## 4. Phase C: Universal Model Browser

### 4.1 MainWindow 메뉴 추가

```python
def _setup_menu(self) -> None:
    # File menu 기존 항목 뒤에:
    file_menu.addSeparator()
    file_menu.addAction("Load &Universal Model...", self._load_universal_model)
```

### 4.2 Universal 탭 추가 (Left Panel)

`_setup_ui()`에서 left_tabs에 Universal 탭 추가:

```python
# Left tabs: Model Reactions + Candidates + Universal
self._left_tabs = QTabWidget()

self._reaction_table = ReactionTableWidget()
self._left_tabs.addTab(self._reaction_table, "Model Reactions")

self._candidate_table = CandidateTableWidget()
self._left_tabs.addTab(self._candidate_table, "Candidates")

# 신규: Universal 탭
self._universal_table = CandidateTableWidget()
self._universal_table.candidate_selected.connect(self._on_universal_selected)
self._left_tabs.addTab(self._universal_table, "Universal")
```

### 4.3 CandidateTableWidget 확장 (`src/gui/candidate_table.py`)

browse 모드 지원을 위한 `set_mode()` 추가:

```python
class CandidateTableWidget(QWidget):
    candidate_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = "default"  # "default" | "browse"
        self._model = CandidateTableModel()
        self._proxy = CandidateFilterProxy()
        self._proxy.setSourceModel(self._model)
        self._overview_label: QLabel | None = None
        self._evaluate_btn: QPushButton | None = None
        self._setup_ui()

    def set_mode(self, mode: str) -> None:
        """Set widget mode: 'default' (gap-fill candidates) or 'browse' (universal)."""
        self._mode = mode
        if self._overview_label:
            self._overview_label.setVisible(mode == "browse")
        if self._evaluate_btn:
            self._evaluate_btn.setVisible(mode == "browse")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Overview 헤더 (browse 모드 전용, 기본 숨김)
        self._overview_label = QLabel()
        self._overview_label.setObjectName("sectionTitle")
        self._overview_label.setWordWrap(True)
        self._overview_label.setVisible(False)
        layout.addWidget(self._overview_label)

        # 기존 filter bar ...

        # Evaluate 버튼 (browse 모드 전용, 기본 숨김)
        eval_layout = QHBoxLayout()
        eval_layout.addStretch()
        self._evaluate_btn = QPushButton("Evaluate Selected")
        self._evaluate_btn.setVisible(False)
        self._evaluate_btn.clicked.connect(self._on_evaluate_clicked)
        eval_layout.addWidget(self._evaluate_btn)
        layout.addLayout(eval_layout)

        # 기존 table view ...

    evaluate_requested = Signal(list)  # list[CandidateReaction]

    def _on_evaluate_clicked(self) -> None:
        selected = self.get_selected_candidates()
        if selected:
            self.evaluate_requested.emit(selected)

    def set_overview(self, text: str) -> None:
        """Set overview header text (browse mode)."""
        if self._overview_label:
            self._overview_label.setText(text)
```

### 4.4 ReactionDetailWidget 확장 (`src/gui/reaction_detail.py`)

`set_read_only()` 메서드 추가:

```python
class ReactionDetailWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._reaction: Reaction | None = None
        self._model: ModelData | None = None
        self._read_only = False  # 신규
        self._setup_ui()

    def set_read_only(self, read_only: bool) -> None:
        """Toggle read-only mode for universal reactions."""
        self._read_only = read_only
        self._name_edit.setReadOnly(read_only)
        self._subsystem_edit.setReadOnly(read_only)
        self._lower_bound_spin.setReadOnly(read_only)
        self._upper_bound_spin.setReadOnly(read_only)
        self._equation_edit.setReadOnly(read_only)
        self._gpr_edit.setReadOnly(read_only)
        self._save_btn.setVisible(not read_only)
```

### 4.5 Universal Model 로드 (`src/gui/main_window.py`)

```python
def _load_universal_model(self) -> None:
    """Load a universal model for browsing."""
    filepath, _ = QFileDialog.getOpenFileName(
        self,
        "Load Universal Model",
        "",
        "Model Files (*.json *.xml *.sbml);;All Files (*)",
    )
    if not filepath:
        return

    from src.core.universal_loader import UniversalLoader

    try:
        loader = UniversalLoader()
        universal_model = loader.load(filepath)

        # Extract candidates (모든 반응을 CandidateReaction으로)
        candidates = loader.extract_candidates(universal_model, self._model)

        # Overview 정보
        total = len(universal_model.reactions)
        excluded = total - len(candidates)
        overview = (
            f"Universal Model: {universal_model.id}\n"
            f"Total reactions: {total} | "
            f"Excluded: {excluded} (model + exchange) | "
            f"Available candidates: {len(candidates)}"
        )

        # Universal 탭에 표시
        self._universal_table.set_mode("browse")
        self._universal_table.set_overview(overview)
        self._universal_table.set_candidates(candidates)
        self._left_tabs.setCurrentWidget(self._universal_table)

        self._statusbar.showMessage(
            f"Universal model loaded: {len(candidates)} candidate reactions"
        )
    except Exception as e:
        QMessageBox.critical(self, "Load Error", str(e))
```

### 4.6 Universal 반응 선택 처리

```python
def _on_universal_selected(self, reaction_id: str) -> None:
    """Handle universal reaction selection → show in detail panel (read-only)."""
    # candidate에서 Reaction 찾기
    for candidate in self._universal_table._model._candidates:
        if candidate.reaction.id == reaction_id:
            self._reaction_detail.set_read_only(True)
            self._reaction_detail.set_reaction(candidate.reaction)
            break
```

### 4.7 Universal Evaluate 연동

```python
# _setup_ui() 에서:
self._universal_table.evaluate_requested.connect(self._evaluate_universal_candidates)

def _evaluate_universal_candidates(self, candidates: list[CandidateReaction]) -> None:
    """Evaluate selected universal candidates with evidence engine."""
    if not self._engine:
        QMessageBox.warning(self, "No Engine", "Evidence engine not initialized.")
        return

    reactions = [c.reaction for c in candidates]
    self._evaluate_batch(reactions, tag="universal")
```

---

## 5. 구현 순서

```
Phase A (Cancel Recovery):
  A-1: models.py — GapFillResult 확장, WorkflowCheckpoint 추가
  A-2: engine.py — cancel_event, is_cancelled 체크, partial result 반환
  A-3: workers.py — cancelled signal, cancel() 메서드, setAutoDelete(False)
  A-4: progress_dialog.py — cancel_requested signal, Cancel 버튼
  A-5: main_window.py — _on_gapfill_cancelled, _workflow_checkpoint
  A-6: gapfill_panel.py — set_partial_result()

Phase B (Resume): A 완료 후
  B-1: main_window.py — _start_workflow 에서 checkpoint 확인
  B-2: main_window.py — _resume_workflow
  B-3: engine.py — start_phase, preloaded_before 로직
  B-4: workers.py — resume 파라미터 전달

Phase C (Universal Browser): A와 병렬 가능
  C-1: candidate_table.py — set_mode(), overview, evaluate 버튼
  C-2: reaction_detail.py — set_read_only()
  C-3: main_window.py — "Load Universal Model..." 메뉴, Universal 탭
  C-4: main_window.py — _on_universal_selected, evaluate 연동
```

---

## 6. 구현 항목 체크리스트 (Gap Analysis용)

| # | 항목 | 파일 | 설명 |
|---|------|------|------|
| 1 | `GapFillResult.completed_phase` 필드 | `src/core/models.py` | `int = 0` |
| 2 | `GapFillResult.all_candidates` 필드 | `src/core/models.py` | `list[CandidateReaction]` |
| 3 | `GapFillResult.is_partial` 필드 | `src/core/models.py` | `bool = False` |
| 4 | `WorkflowCheckpoint` dataclass | `src/core/models.py` | completed_phase, result, universal_path, task_path, options, timestamp |
| 5 | `GapFillEngine.run()` — `cancel_event` 파라미터 | `src/gapfill/engine.py` | `asyncio.Event \| None = None` |
| 6 | `GapFillEngine.run()` — Phase별 cancel 체크 | `src/gapfill/engine.py` | 각 Phase 완료 후 `_is_cancelled()` 호출 |
| 7 | `GapFillEngine.run()` — `start_phase` 파라미터 | `src/gapfill/engine.py` | `int = 1`, Phase 스킵 로직 |
| 8 | `GapFillEngine.run()` — `preloaded_before` 파라미터 | `src/gapfill/engine.py` | `list[TaskResult] \| None = None` |
| 9 | `GapFillWorkerSignals.cancelled` signal | `src/gui/workers.py` | `Signal(object, int)` |
| 10 | `GapFillWorkflowWorker.cancel()` 메서드 | `src/gui/workers.py` | `_cancel_event.set()` |
| 11 | `GapFillWorkflowWorker._cancel_event` 필드 | `src/gui/workers.py` | `asyncio.Event` |
| 12 | `GapFillWorkflowWorker` resume 파라미터 | `src/gui/workers.py` | `start_phase`, `preloaded_before`, `preloaded_candidates` |
| 13 | `GapFillWorkflowWorker.setAutoDelete(False)` | `src/gui/workers.py` | Cancel 대비 GC 방지 |
| 14 | `ProgressDialog.cancel_requested` signal | `src/gui/progress_dialog.py` | Cancel 버튼 + signal |
| 15 | `MainWindow._workflow_checkpoint` 필드 | `src/gui/main_window.py` | `WorkflowCheckpoint \| None` |
| 16 | `MainWindow._on_gapfill_cancelled()` 핸들러 | `src/gui/main_window.py` | checkpoint 저장, Phase별 부분 UI 업데이트 |
| 17 | `MainWindow._start_workflow()` checkpoint 확인 | `src/gui/main_window.py` | Resume 다이얼로그, Yes/No/Cancel |
| 18 | `MainWindow._resume_workflow()` 메서드 | `src/gui/main_window.py` | checkpoint 기반 워커 생성 |
| 19 | `MainWindow._on_model_loaded()` checkpoint 초기화 | `src/gui/main_window.py` | `self._workflow_checkpoint = None` |
| 20 | `GapFillPanelWidget.set_partial_result()` | `src/gui/gapfill_panel.py` | 배너 + 부분 테이블 표시 |
| 21 | `MainWindow` — "Load Universal Model..." 메뉴 | `src/gui/main_window.py` | File 메뉴에 추가 |
| 22 | `MainWindow._universal_table` 필드 + Universal 탭 | `src/gui/main_window.py` | left_tabs에 CandidateTableWidget 추가 |
| 23 | `MainWindow._load_universal_model()` | `src/gui/main_window.py` | UniversalLoader → candidates → 탭 표시 |
| 24 | `MainWindow._on_universal_selected()` | `src/gui/main_window.py` | detail panel 읽기 전용 표시 |
| 25 | `CandidateTableWidget.set_mode()` | `src/gui/candidate_table.py` | "default" / "browse" 모드 |
| 26 | `CandidateTableWidget._overview_label` | `src/gui/candidate_table.py` | browse 모드 overview 헤더 |
| 27 | `CandidateTableWidget._evaluate_btn` + `evaluate_requested` signal | `src/gui/candidate_table.py` | Evaluate Selected 버튼 |
| 28 | `ReactionDetailWidget.set_read_only()` | `src/gui/reaction_detail.py` | 읽기 전용 모드 전환 |

---

*Design created: 2026-02-23*
*Feature: workflow-resume-universal-browser*
*PDCA Phase: Design*
