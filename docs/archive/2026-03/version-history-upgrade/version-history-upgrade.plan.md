# Plan: Version History Upgrade

## 1. Overview

Version History 패널을 2가지 방향으로 개선한다:

1. **패널 크기 조절**: Version History 탭의 높이/너비를 사용자가 드래그로 조절 가능하게 함
2. **버전 그래프 시각화**: parent_version_id 관계를 이용한 분기 그래프 표시 (git log --graph 스타일)

## 2. 현재 상태 분석

### 탭 크기
- Version History는 `right_tabs` (QTabWidget) 안의 탭으로 존재
- 좌/우 비율은 main QSplitter (`setSizes([600, 500])`)로 고정
- 탭 내부에서 추가 크기 조절 불가

### 버전 그래프
- `ModelVersion.parent_version_id` 필드가 존재하지만 tooltip에서만 표시
- `QTreeWidget`을 flat list로 사용 (`setRootIsDecorated(False)`)
- 분기/합류 시각화 없음

## 3. 요구사항

### FR-01: 패널 크기 조절
- Version History 탭 내에서 테이블과 그래프 영역을 QSplitter로 분할
- 사용자가 드래그 핸들로 두 영역의 비율 조절 가능
- 그래프 영역을 접을 수 있는 토글 버튼 제공

### FR-02: 버전 그래프 시각화
- PyQtGraph 기반 커스텀 위젯으로 버전 트리 그래프 표시
- 노드: 각 버전 (change_type별 색상 구분)
- 엣지: parent → child 관계 (분기선)
- 현재 버전 강조 (별표 또는 하이라이트)
- 노드 클릭 시 테이블에서 해당 버전 선택
- 노드 hover 시 tooltip (version_id, change_type, timestamp, diff summary)
- Restore 분기도 시각적으로 표시 (restore 노드에서 원본으로의 점선)

## 4. 범위

### In Scope
| 항목 | 설명 |
|------|------|
| QSplitter 분할 | 테이블(상) + 그래프(하) 수직 분할 |
| VersionGraphWidget | PyQtGraph ScatterPlotItem + 커스텀 라인 기반 그래프 |
| 테이블-그래프 연동 | 테이블 선택 ↔ 그래프 하이라이트 양방향 동기화 |
| 그래프 토글 | "Graph" 버튼으로 그래프 영역 표시/숨김 |

### Out of Scope
| 항목 | 이유 |
|------|------|
| 버전 병합(merge) | 현재 모델에 merge 개념 없음 |
| 확대/축소(zoom) | 버전 수가 적어서 불필요 (MAX_VERSIONS_DEFAULT=20) |
| 드래그 앤 드롭 재배치 | 버전 순서는 시간순 고정 |

## 5. 기술 접근

### 5.1 레이아웃 변경

```
VersionPanelWidget (기존 QVBoxLayout)
│
├─ Header (title + filter + graph toggle)
│
├─ QSplitter (Vertical)
│   ├─ QTreeWidget (기존 테이블, 상단)
│   └─ VersionGraphWidget (신규, 하단)
│
└─ Buttons (Compare, Restore, Export)
```

### 5.2 VersionGraphWidget

PyQtGraph의 `PlotWidget`을 사용한 커스텀 그래프:
- X축: 시간순 인덱스 (왼쪽=oldest, 오른쪽=newest)
- Y축: 분기 레인 (같은 부모에서 나온 분기는 다른 Y 레인)
- 노드: ScatterPlotItem (change_type별 색상)
- 엣지: PlotCurveItem (parent→child 연결선)
- 현재 버전: 큰 원 + 하이라이트 테두리

### 5.3 그래프 레이아웃 알고리즘

```
1. 버전 목록을 시간순 정렬
2. 각 버전에 X 좌표 할당 (인덱스)
3. 메인 브랜치(initial_load에서 시작)는 Y=0
4. restore 분기: 새로운 Y 레인 할당
5. parent→child 엣지 그리기
```

## 6. 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/gui/version_panel.py` | QSplitter 추가, 그래프 토글, 테이블-그래프 연동 |
| `src/gui/version_graph.py` | **신규** — VersionGraphWidget (PyQtGraph 기반) |
| `tests/test_gui_widgets.py` | VersionGraphWidget 인스턴스화 테스트 추가 |

## 7. 의존성

- PyQtGraph (이미 설치됨, `score_visualization.py`에서 사용 중)
- 추가 패키지 불필요

## 8. 테스트 전략

| 테스트 | 설명 |
|--------|------|
| `test_graph_instantiation` | VersionGraphWidget 기본 생성 |
| `test_graph_set_versions` | 버전 데이터 설정 시 노드/엣지 생성 확인 |
| `test_graph_highlight` | 특정 버전 하이라이트 동작 |
| `test_splitter_exists` | QSplitter로 테이블/그래프 분할 확인 |
| `test_toggle_graph` | 그래프 표시/숨김 토글 동작 |

## 9. 리스크

| 리스크 | 대응 |
|--------|------|
| PyQtGraph ScatterPlot 클릭 이벤트 | sigClicked 시그널 사용 (검증됨) |
| 버전 20개 이상 시 그래프 복잡도 | MAX_VERSIONS_DEFAULT=20으로 제한, 스크롤 지원 |
| 분기 레이아웃 겹침 | 단순 Y 레인 할당으로 충분 (복잡한 git-flow 아님) |
