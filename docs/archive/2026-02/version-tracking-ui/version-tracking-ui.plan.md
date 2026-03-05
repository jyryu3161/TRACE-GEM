# Plan: Version Tracking UI 개선

---

## 1. 개요

현재 Version History 패널이 QListWidget + plain text 형식으로 정보를 한 줄씩 나열하고 있어, 버전 간 변경 사항을 한눈에 파악하기 어렵다. Git처럼 수정사항을 직관적으로 tracking할 수 있도록 UI를 전면 개선한다.

---

## 2. 현재 문제점

### 2.1 UI 문제

| 문제 | 상세 |
|------|------|
| QListWidget 사용 | 컬럼 구분 없이 파이프(`\|`)로 구분된 plain text → 정렬/필터 불가 |
| 변경사항 미표시 | diff 데이터가 ModelVersion에 있지만 목록에서 보이지 않음 |
| change_type 미표시 | initial_load, gap_fill, manual_edit, restore 구분 불가 |
| 시각적 계층 부재 | 모든 버전이 동일한 스타일로 나열, current 표시 없음 |

### 2.2 현재 format_item 코드

```python
# version_panel.py:86-105
def _format_item(self, version: ModelVersion) -> str:
    parts = [version.version_id]
    ts = version.timestamp
    if "T" in ts:
        ts = ts.split("T")[0] + " " + ts.split("T")[1][:8]
    parts.append(ts)
    if version.description:
        desc = version.description[:57] + "..." if len(desc) > 60
        parts.append(desc)
    if version.task_pass_rate:
        parts.append(f"[{version.task_pass_rate}]")
    return "  |  ".join(parts)
```

결과: `v001  |  2026-02-21 09:30:00  |  Initial model load  |  [35/52]`

---

## 3. 개선 목표

### 3.1 핵심 요구사항

1. **테이블 형식 버전 목록** — QTreeWidget로 컬럼 구분 (Version, Date, Type, Changes, QC, Description)
2. **Git-style 변경 추적** — `+23 rxn, -0 rxn, ~5 mod` 같은 인라인 diff summary
3. **변경 타입 뱃지** — change_type별 색상 구분 (initial=회색, gap_fill=초록, manual_edit=파랑, restore=주황)
4. **현재 버전 강조** — current version에 볼드 + 아이콘 표시
5. **diff 상세보기 개선** — 테이블 row 더블클릭 시 해당 버전의 diff 상세 표시

### 3.2 부가 요구사항

6. **컬럼 정렬** — 날짜, QC pass rate 등으로 정렬 가능
7. **필터** — change_type 별 필터링
8. **변경사항 요약 tooltip** — 마우스 hover 시 상세 diff 요약 표시

---

## 4. 기술 설계

### 4.1 QListWidget → QTreeWidget 전환

QTreeWidget 선택 이유:
- 컬럼 헤더 지원 (정렬 가능)
- Multi-selection 지원 (Compare용)
- Custom widget/delegate 적용 가능
- QTableWidget보다 가벼움 (read-only 용도)

### 4.2 컬럼 구조

```
┌────────┬────────────┬───────────┬──────────────────────┬────────┬───────────────────────────────┐
│ Version│ Date       │ Type      │ Changes              │ QC     │ Description                   │
├────────┼────────────┼───────────┼──────────────────────┼────────┼───────────────────────────────┤
│ ★ v003 │ 02-21 10:30│ ✏ Edit    │ ~5 rxn               │ 48/52  │ Manual edit: PFK bounds adj...│
│   v002 │ 02-21 10:15│ 🧩 GapFill│ +23 rxn, +15 gene    │ 48/52  │ Gap-fill: 23 reactions, 13 ...│
│   v001 │ 02-21 09:30│ 📥 Initial│ +2583 rxn, +1366 gene│ 35/52  │ Initial model load            │
└────────┴────────────┴───────────┴──────────────────────┴────────┴───────────────────────────────┘
```

### 4.3 Change Type 뱃지 색상

| change_type | 표시 | 색상 |
|-------------|------|------|
| initial_load | Initial | `#95a5a6` (neutral) |
| gap_fill | GapFill | `#27ae60` (success) |
| manual_edit | Edit | `#3498db` (primary) |
| restore | Restore | `#f39c12` (warning) |

### 4.4 Changes 컬럼 포맷

ModelDiff의 summary_counts를 활용하되, 더 compact한 표현:

```python
def _format_changes(diff: ModelDiff | None) -> str:
    if diff is None or diff.is_empty:
        return "—"
    parts = []
    total_add = len(diff.reactions_added)
    total_rem = len(diff.reactions_removed)
    total_mod = len(diff.reactions_modified)
    if total_add:
        parts.append(f"+{total_add} rxn")
    if total_rem:
        parts.append(f"-{total_rem} rxn")
    if total_mod:
        parts.append(f"~{total_mod} mod")
    # gene changes
    gene_add = len(diff.genes_added)
    gene_rem = len(diff.genes_removed)
    if gene_add:
        parts.append(f"+{gene_add} gene")
    if gene_rem:
        parts.append(f"-{gene_rem} gene")
    return ", ".join(parts)
```

Git-style 색상:
- `+N` → 초록색
- `-N` → 빨간색
- `~N` → 주황색

### 4.5 Tooltip 상세 정보

마우스 hover 시 rich tooltip:
```
Version: v002
Date: 2026-02-21 10:15:00 UTC
Type: gap_fill
Parent: v001

Changes:
  Reactions: +23 added, -0 removed, ~0 modified
  Genes: +15 added, -0 removed
  Metabolites: +30 added, -0 removed

QC: 48/52 tasks passed (92.3%)

Description: Gap-filling으로 23개 반응 추가...
```

### 4.6 Custom Delegate (ChangeTypeDelegate)

change_type 컬럼에 색상 뱃지를 렌더링하는 custom delegate:

```python
class ChangeTypeDelegate(QStyledItemDelegate):
    """Render change_type as a colored badge."""

    COLORS = {
        "initial_load": "#95a5a6",
        "gap_fill": "#27ae60",
        "manual_edit": "#3498db",
        "restore": "#f39c12",
    }
    LABELS = {
        "initial_load": "Initial",
        "gap_fill": "GapFill",
        "manual_edit": "Edit",
        "restore": "Restore",
    }
```

---

## 5. 수정 파일 목록

| 파일 | 수정 내용 |
|------|-----------|
| `src/gui/version_panel.py` | QListWidget → QTreeWidget 전환, 컬럼 구조, 변경사항 표시, current 강조, 필터, tooltip |
| `src/gui/theme.py` | version_* 색상 추가 (change_type 뱃지, diff 색상) |
| `src/gui/diff_dialog.py` | 단일 버전 diff 상세보기 모드 추가 (더블클릭 시) |
| `src/core/models.py` | ModelDiff에 compact_summary 프로퍼티 추가 |
| `tests/test_gui_widgets.py` | VersionPanelWidget 테스트 업데이트 |

---

## 6. 구현 순서

```
1. models.py — ModelDiff에 compact_summary 추가
   ↓
2. theme.py — 버전 관련 색상 상수 추가
   ↓
3. version_panel.py — QTreeWidget 전환 + 전체 UI 재구현
   ↓
4. diff_dialog.py — 단일 버전 상세보기 모드 추가
   ↓
5. tests — 테스트 업데이트
```

### 의존성 관계

```
Step 1 (models.py) ─┬─→ Step 3 (version_panel.py)
Step 2 (theme.py)  ─┘         ↓
                        Step 4 (diff_dialog.py)
                               ↓
                        Step 5 (tests)
```

---

## 7. 리스크

| 리스크 | 완화 |
|--------|------|
| QTreeWidget로 전환 시 기존 시그널 호환성 | restore_requested, compare_requested, export_requested 시그널 유지 |
| 대량 버전 (20+) 시 렌더링 성능 | max_versions=20으로 이미 제한됨, 문제 없음 |
| diff가 None인 오래된 버전 | None 처리 로직 포함 ("—" 표시) |

---

*Plan created: 2026-02-23*
*Feature: version-tracking-ui*
*PDCA Phase: Plan*
