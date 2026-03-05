# Plan: Universal Overview & UI Cleanup

## Feature ID
`universal-overview-ui-cleanup`

## Summary
Universal model 로드 시 Model Overview 표시 + 불필요한 Candidates 탭 제거

## Requirements

### REQ-1: Universal Model Overview
- Universal model을 로드하면 Model Overview에 해당 정보를 함께 표시
- 표시 항목: Model ID, Name, Total reactions, Excluded (model + exchange), Available candidates
- Evaluated 카운트도 표시 (Universal 탭에서 평가된 반응 수 / 전체 후보 수)

### REQ-2: Candidates 탭 제거
- 현재 좌측 탭에 "Model Reactions", "Candidates", "Universal" 3개 탭 존재
- "Candidates" 탭은 Gap-Fill 결과에서 추가된 반응만 표시하는데, 이 정보는 우측 "Gap-Fill" 패널에 이미 표시됨
- "Candidates" 탭을 제거하고, gap-fill 결과의 added_reactions은 Universal 탭에 표시

## Current State Analysis

### Model Overview (`model_overview.py`)
- 현재 user model 정보만 표시 (ID, Name, Organism, Reactions, Metabolites, Genes, Subsystems, Evaluated)
- Universal model 정보 표시 기능 없음

### Candidates 탭 (`candidate_table.py`)
- `CandidateTableWidget` 재사용: Candidates 탭과 Universal 탭에 각각 별도 인스턴스
- Candidates 탭 사용처:
  1. `_on_gapfill_complete()`: `result.added_reactions` 표시
  2. `_on_gapfill_cancelled()`: `result.all_candidates` 표시 (phase >= 2)
- Gap-Fill 패널에서 이미 같은 정보를 표시하므로 중복

### Universal 탭
- `_load_universal_model()`에서 overview text를 `set_overview()`로 표시 (간단한 텍스트)
- browse mode로 동작, Evaluate 버튼 표시

## Implementation Plan

### Phase A: Model Overview 확장
1. `ModelOverviewWidget`에 Universal model 정보 섹션 추가
   - "Universal Model" 그룹 추가 (조건부 표시)
   - 항목: Model ID, Total Reactions, Excluded, Available Candidates, Evaluated
2. `set_universal_info()` 메서드 추가
3. `update_universal_evaluation_count()` 메서드 추가
4. `clear_universal()` 메서드 추가
5. `main_window.py`의 `_load_universal_model()`에서 overview 업데이트

### Phase B: Candidates 탭 제거
1. `main_window.py`에서 `_candidate_table` 관련 코드 제거:
   - `_setup_ui()`: 탭 추가 코드, delegate 설정
   - `_on_candidate_selected()`: 시그널 핸들러
   - `_on_gapfill_complete()`: candidate_table.set_candidates → Universal 탭으로 이동
   - `_on_gapfill_cancelled()`: candidate_table.set_candidates → Universal 탭으로 이동
2. import 정리 (CandidateTableWidget은 Universal 탭에서 여전히 사용하므로 유지)
3. Gap-fill 결과의 added_reactions을 Universal 탭에 표시하도록 변경

## Affected Files
- `src/gui/model_overview.py` — Universal 섹션 추가
- `src/gui/main_window.py` — Candidates 탭 제거, overview 연동

## Out of Scope
- `candidate_table.py` 파일 자체는 Universal 탭에서 사용하므로 삭제하지 않음
- Gap-Fill 패널 UI 변경 없음
