# Design: Version History Upgrade

## 1. Overview

Version History 패널에 2가지 기능을 추가한다:
1. **QSplitter 분할**: 테이블(상단) + 그래프(하단)를 수직 QSplitter로 분할하여 크기 조절 가능
2. **버전 그래프 시각화**: PyQtGraph 기반 VersionGraphWidget으로 parent→child 관계를 git-graph 스타일로 표시

**Plan 참조**: `docs/01-plan/features/version-history-upgrade.plan.md`

## 2. Architecture

### 2.1 Component Diagram

```
VersionPanelWidget (QWidget, QVBoxLayout)
│
├─ Header (QHBoxLayout)
│   ├─ QLabel("Version History")
│   ├─ stretch
│   ├─ QLabel("Filter:")
│   ├─ QComboBox (type filter)        ← 기존
│   └─ QPushButton("Graph ▼/▲")       ← 신규: 그래프 토글
│
├─ QSplitter (Qt.Vertical)             ← 신규
│   ├─ QTreeWidget (기존 테이블)
│   └─ VersionGraphWidget (신규)
│
└─ Buttons (QHBoxLayout)
    ├─ Compare
    ├─ Restore
    └─ Export
```

### 2.2 File Structure

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/gui/version_graph.py` | **신규** | VersionGraphWidget (PyQtGraph PlotWidget 기반) |
| `src/gui/version_panel.py` | 수정 | QSplitter 추가, 그래프 토글, 테이블↔그래프 연동 |
| `src/gui/theme.py` | 수정 | 그래프 노드 색상 추가 (graph_node_*, graph_edge) |
| `tests/test_gui_widgets.py` | 수정 | VersionGraphWidget 테스트 추가 |

## 3. Detailed Design

### 3.1 VersionGraphWidget (`src/gui/version_graph.py`)

PyQtGraph `PlotWidget` 기반 커스텀 위젯. 버전 히스토리를 노드-엣지 그래프로 시각화한다.

#### 3.1.1 Class Interface

```python
class VersionGraphWidget(QWidget):
    """PyQtGraph-based version history graph visualization.

    Displays ModelVersion nodes connected by parent→child edges.
    Supports click-to-select, hover tooltips, and current version highlight.
    """

    version_selected = Signal(str)  # version_id (노드 클릭 시)

    def __init__(self, parent: QWidget | None = None) -> None: ...

    def set_versions(
        self,
        versions: list[ModelVersion],
        current_version_id: str | None = None,
    ) -> None:
        """버전 데이터 설정. 그래프 재구성."""
        ...

    def highlight_version(self, version_id: str) -> None:
        """특정 버전 노드 하이라이트 (테이블 선택 연동)."""
        ...

    def clear(self) -> None:
        """그래프 초기화."""
        ...
```

#### 3.1.2 Graph Layout Algorithm

```
Input: versions: list[ModelVersion] (시간순)

1. 시간순 정렬 (oldest → newest)
2. parent_id → children 매핑 생성
3. X 좌표: 시간순 인덱스 (0, 1, 2, ...)
4. Y 좌표: 브랜치 레인 할당
   - initial_load → lane 0 (메인 브랜치)
   - parent와 같은 lane의 child가 1개 → 같은 lane 유지
   - parent에서 분기 (restore 등) → 새 lane 할당 (lane_counter++)
5. 노드 그리기: ScatterPlotItem
   - 크기: 일반 10px, 현재 버전 14px
   - 색상: change_type별 THEME 색상
6. 엣지 그리기: PlotCurveItem (parent → child 연결선)
   - 같은 lane: 직선
   - 다른 lane: 꺾은선 (parent.x → mid.x, parent.y → child.y → child.x)
7. restore 점선: PlotCurveItem(pen=DashLine) — restore 노드 → 원본 버전
```

#### 3.1.3 노드 색상 매핑

| change_type | 색상 | THEME 속성 |
|-------------|------|-----------|
| initial_load | `#95a5a6` (gray) | `version_type_initial` |
| gap_fill | `#27ae60` (green) | `version_type_gap_fill` |
| manual_edit | `#3498db` (blue) | `version_type_manual_edit` |
| restore | `#f39c12` (orange) | `version_type_restore` |

현재 버전: 노드 외곽에 `#2c3e50` 테두리 (2px)

#### 3.1.4 Interaction

- **노드 클릭**: `ScatterPlotItem.sigClicked` → `version_selected` 시그널 발신
- **hover tooltip**: `ScatterPlotItem.setToolTip()` — version_id, change_type, timestamp, diff summary
- **현재 버전 강조**: 큰 원 + 테두리 (다른 노드와 시각적 구분)
- **축**: X축 숨김 (인덱스 비표시), Y축 숨김, 배경 흰색, 그리드 없음

#### 3.1.5 PyQtGraph Import Guard

```python
try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False
```

`HAS_PYQTGRAPH == False`이면 "PyQtGraph not installed" 라벨 표시 (score_visualization.py 패턴 동일).

### 3.2 VersionPanelWidget 수정 (`src/gui/version_panel.py`)

#### 3.2.1 레이아웃 변경

기존 `layout.addWidget(self._tree)` → `QSplitter`로 교체:

```python
# 기존
layout.addWidget(self._tree)

# 변경
from PySide6.QtWidgets import QSplitter

self._splitter = QSplitter(Qt.Orientation.Vertical)
self._splitter.addWidget(self._tree)

self._graph = VersionGraphWidget()
self._splitter.addWidget(self._graph)
self._splitter.setSizes([300, 200])  # 테이블 60%, 그래프 40%

layout.addWidget(self._splitter)
```

#### 3.2.2 그래프 토글 버튼

Header에 "Graph" 토글 버튼 추가:

```python
self._graph_btn = QPushButton("Graph ▼")
self._graph_btn.setFixedWidth(70)
self._graph_btn.setCheckable(True)
self._graph_btn.setChecked(True)
self._graph_btn.clicked.connect(self._toggle_graph)
header_layout.addWidget(self._graph_btn)
```

토글 동작:
- 켜짐: 그래프 표시, 버튼 텍스트 "Graph ▲"
- 꺼짐: 그래프 숨김 (`self._graph.hide()`), 버튼 텍스트 "Graph ▼"

#### 3.2.3 테이블 ↔ 그래프 양방향 동기화

```python
# 테이블 → 그래프: 테이블 선택 변경 시 그래프 하이라이트
self._tree.itemSelectionChanged.connect(self._on_table_selection_changed)

def _on_table_selection_changed(self) -> None:
    ids = self._get_selected_version_ids()
    if len(ids) == 1:
        self._graph.highlight_version(ids[0])

# 그래프 → 테이블: 그래프 노드 클릭 시 테이블 선택
self._graph.version_selected.connect(self._on_graph_version_selected)

def _on_graph_version_selected(self, version_id: str) -> None:
    # 테이블에서 해당 version_id 아이템 찾아 선택
    for i in range(self._tree.topLevelItemCount()):
        item = self._tree.topLevelItem(i)
        if item.data(COL_VERSION, Qt.ItemDataRole.UserRole) == version_id:
            self._tree.setCurrentItem(item)
            break
```

#### 3.2.4 set_history 수정

기존 `_rebuild_tree()` 호출 후 그래프도 업데이트:

```python
def set_history(self, versions, current_version_id=None) -> None:
    # ... 기존 로직 ...
    self._rebuild_tree()
    self._graph.set_versions(self._versions, self._current_version_id)  # 추가
```

### 3.3 Theme 수정 (`src/gui/theme.py`)

`ThemeColors`에 그래프 전용 색상 추가:

```python
# --- Version graph ---
graph_edge: str = "#bdc3c7"           # 엣지 기본 색상
graph_edge_restore: str = "#f39c12"   # restore 분기 점선 색상
graph_current_border: str = "#2c3e50" # 현재 버전 테두리
graph_bg: str = "#ffffff"             # 그래프 배경
```

노드 색상은 기존 `version_type_*` 색상 재사용.

## 4. Implementation Order

```
Step 1: theme.py — 그래프 색상 4개 추가
Step 2: version_graph.py — VersionGraphWidget 신규 생성
  2a: 기본 PlotWidget 설정 (배경, 축 숨김)
  2b: set_versions() — 레이아웃 알고리즘 + 노드/엣지 렌더링
  2c: highlight_version() — 하이라이트 동작
  2d: 클릭/hover 인터랙션
Step 3: version_panel.py — 레이아웃 변경
  3a: QSplitter 도입 (테이블 + 그래프)
  3b: 그래프 토글 버튼
  3c: 양방향 동기화 연결
  3d: set_history/clear 수정
Step 4: test_gui_widgets.py — 테스트 추가
```

## 5. Test Specifications

### 5.1 VersionGraphWidget Tests

| 테스트 | 설명 | 검증 |
|--------|------|------|
| `test_graph_instantiation` | 기본 생성 | widget이 None 아님, PlotWidget 존재 |
| `test_graph_set_versions` | 버전 데이터 설정 | 노드 수 == 버전 수, 엣지 존재 |
| `test_graph_set_versions_empty` | 빈 리스트 | 에러 없이 빈 그래프 |
| `test_graph_highlight` | 하이라이트 | highlight 후 에러 없음 |
| `test_graph_clear` | 초기화 | clear 후 빈 그래프 |

### 5.2 VersionPanelWidget Tests (기존 확장)

| 테스트 | 설명 | 검증 |
|--------|------|------|
| `test_splitter_exists` | QSplitter 존재 | splitter 위젯 2개 (테이블, 그래프) |
| `test_toggle_graph` | 그래프 토글 | 버튼 클릭 시 그래프 표시/숨김 |
| `test_table_graph_sync` | 양방향 동기화 | 테이블 선택 → 그래프 하이라이트 |

## 6. Edge Cases

| 케이스 | 처리 |
|--------|------|
| 버전 1개 (initial_load만) | 노드 1개, 엣지 없음 |
| parent_version_id가 None인 비-initial 버전 | lane 0에 독립 노드 |
| 필터 적용 시 | 필터된 버전만 그래프에 표시 |
| PyQtGraph 미설치 | fallback 라벨 표시 |
| 버전 20개 초과 | MAX_VERSIONS_DEFAULT=20으로 제한 (기존 로직) |

## 7. Dependencies

- PyQtGraph ≥0.13.0 (이미 설치됨)
- 추가 패키지 불필요
