# GUI Refactoring Planning Document

> **Summary**: 코드 품질 분석에서 발견된 아키텍처 위반, DRY 위반, 캡슐화 문제, 보안 이슈를 체계적으로 수정하는 리팩토링
>
> **Project**: GEM Evaluator
> **Author**: Claude Code
> **Date**: 2026-02-27
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

코드 품질 분석(72/100)에서 발견된 Critical 3건, High 7건, Medium 10건의 이슈를 수정하여 코드베이스의 유지보수성, 보안, 아키텍처 건전성을 개선한다.

### 1.2 Background

GEM Evaluator는 빠르게 기능이 추가되면서 (7개 증거 소스, gap-filling, 버전 관리) 코드 중복과 아키텍처 위반이 누적되었다. 특히:
- `MainWindow`가 1,694줄로 비대화
- `evidence` 모듈이 `gui` 모듈에 의존하는 레이어 역전
- 동일 로직이 3~4곳에 복제됨
- API 키가 권한 없이 저장됨

### 1.3 Related Documents

- Code Analysis: 이전 세션의 code-analyzer 결과 (72/100)
- Architecture: `CLAUDE.md` Project Structure 섹션

---

## 2. Scope

### 2.1 In Scope

- [x] Phase 1: 아키텍처 위반 수정 (evidence → gui 의존성 제거)
- [x] Phase 2: 캡슐화 위반 수정 (EvidenceEngine public API)
- [x] Phase 3: DRY 위반 수정 (공통 유틸리티 추출)
- [x] Phase 4: MainWindow 분해 (Controller 패턴)
- [x] Phase 5: 보안 개선 (config 파일 권한, HTTPS)
- [x] Phase 6: Medium/Low 이슈 수정

### 2.2 Out of Scope

- 새로운 기능 추가
- UI/UX 변경
- 테스트 커버리지 확대 (별도 PDCA 사이클)
- CLI 리팩토링 (별도 PDCA 사이클)
- 성능 최적화 (`ModelData.get_reaction()` dict 인덱스 제외)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | `evidence` 모듈이 `gui` 모듈 import 없이 독립 동작 | Critical | Pending |
| FR-02 | `EvidenceEngine`에 `cache_manager`, `mapping_data` public property 추가 | Critical | Pending |
| FR-03 | `config.json` 파일 권한 `0o600` 설정 + 환경변수 오버라이드 | Critical | Pending |
| FR-04 | `cobra_utils.py`에 `convert_cobra_reaction()`, `normalize_annotation()` 추출 | High | Pending |
| FR-05 | `EvidenceEngine`에서 `_run_evidence_pipeline()` 공통 메서드 추출 | High | Pending |
| FR-06 | `llm_utils.py`에 `extract_json_from_llm_response()` 추출 | High | Pending |
| FR-07 | `IdentifierMapper.resolve()` / `resolve_universal()` 통합 | High | Pending |
| FR-08 | `MainWindow`를 Controller 패턴으로 분해 (목표: 각 클래스 300줄 이하) | High | Pending |
| FR-09 | `ReactionTableModel`에 public accessor 메서드 추가 | High | Pending |
| FR-10 | BiGG API URL을 HTTPS로 변경 | Medium | Pending |
| FR-11 | `asyncio.set_event_loop()` deprecated 호출 제거 | Medium | Pending |
| FR-12 | `ModelData.get_reaction()` O(n) → O(1) dict 인덱스 추가 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Regression | 기존 테스트 100% 통과 | `pytest tests/ -v` |
| Architecture | evidence 모듈 독립 import 가능 | `python -c "from src.evidence import ..."` (PySide6 없이) |
| Security | config 파일 권한 600 | `stat -f "%Lp" ~/.gem_evaluator/config.json` |
| Maintainability | 단일 파일 300줄 이하 (MainWindow 분해 후) | `wc -l` |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 모든 FR 구현 완료
- [ ] 기존 테스트 전체 통과 (`pytest tests/ -v`)
- [ ] `ruff check src/ tests/` 에러 없음
- [ ] `mypy src/ --ignore-missing-imports` 통과
- [ ] evidence 모듈 독립 동작 확인

### 4.2 Quality Criteria

- [ ] 코드 품질 점수 72 → 85+ 목표
- [ ] Critical 이슈 0건
- [ ] High 이슈 0건
- [ ] 새로운 경고/에러 없음

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| MainWindow 분해 시 시그널/슬롯 연결 누락 | High | Medium | 단계적 분해 + 각 단계마다 GUI 수동 테스트 |
| evidence_types.py 색상 이동 시 기존 참조 깨짐 | Medium | Medium | Grep으로 모든 import 추적 후 일괄 수정 |
| cobra_utils.py 추출 시 미묘한 동작 차이 | Medium | Low | 기존 테스트가 두 경로 모두 커버 |
| config 권한 변경이 기존 사용자에게 영향 | Low | Low | 기존 파일은 읽기 후 권한만 변경 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | |
| **Dynamic** | Feature-based modules, BaaS integration | Web apps with backend | ✅ |
| **Enterprise** | Strict layer separation, DI, microservices | High-traffic systems | |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| GUI Framework | PySide6 (기존) | PySide6 | 변경 없음 |
| MainWindow 분해 패턴 | MVC / Controller 추출 / Mixin | Controller 추출 | 기존 코드에서 가장 자연스러운 분리 |
| 색상 상수 위치 | evidence에 hex 리터럴 / gui 전용 모듈 | gui/evidence_colors.py | evidence 레이어 독립성 보장 |
| DRY 추출 위치 | core/utils.py / core/cobra_utils.py | core/cobra_utils.py | 명확한 역할 표현 |
| LLM 유틸 위치 | api/utils.py / api/llm_utils.py | api/llm_utils.py | 명확한 역할 표현 |

### 6.3 리팩토링 후 모듈 구조

```
src/
├── core/
│   ├── cobra_utils.py      ← NEW: convert_cobra_reaction(), normalize_annotation()
│   ├── models.py            (+ _reaction_index lazy dict)
│   ├── sbml_parser.py       (→ cobra_utils 호출)
│   ├── universal_loader.py  (→ cobra_utils 호출)
│   └── id_mapper.py         (resolve 통합, strip_compartment public)
├── api/
│   ├── llm_utils.py         ← NEW: extract_json_from_llm_response()
│   ├── gemini_client.py     (→ llm_utils 호출)
│   └── perplexity_client.py (→ llm_utils 호출)
├── evidence/
│   ├── engine.py            (+ _run_evidence_pipeline(), public properties)
│   └── evidence_types.py    (gui import 제거, hex 리터럴만)
├── gui/
│   ├── evidence_colors.py   ← NEW: theme 색상 + evidence 소스 매핑
│   ├── main_window.py       (300줄 이하로 축소)
│   ├── controllers/         ← NEW
│   │   ├── evaluation_ctrl.py
│   │   ├── gapfill_ctrl.py
│   │   ├── export_ctrl.py
│   │   └── version_ctrl.py
│   └── reaction_table.py    (+ public accessors)
└── utils/
    ├── config.py            (+ chmod 0o600, env var override)
    └── constants.py         (BiGG → HTTPS)
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [x] `from __future__ import annotations` in every module
- [x] Type hints on all public functions
- [x] Dataclasses for data models
- [x] ABC for client interfaces
- [x] asyncio for API calls in worker threads
- [ ] `docs/01-plan/conventions.md` (없음)

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **File size limit** | 암묵적 | 단일 파일 300줄 이하 권장 | High |
| **Private API 접근** | 위반 존재 | `_` prefix는 외부 접근 금지 | High |
| **Layer dependency** | 위반 존재 | gui → evidence → core (단방향만 허용) | High |
| **공통 유틸 위치** | 미정의 | `core/cobra_utils.py`, `api/llm_utils.py` | Medium |

---

## 8. Implementation Order

구현 순서는 의존성과 위험도를 고려하여 설정:

```
Phase 1: 아키텍처 위반 (FR-01)
  └→ evidence_types.py gui 의존 제거 + evidence_colors.py 생성

Phase 2: 캡슐화 (FR-02, FR-09)
  └→ EvidenceEngine public properties + ReactionTableModel accessors

Phase 3: DRY 추출 (FR-04, FR-05, FR-06, FR-07)
  ├→ core/cobra_utils.py 생성
  ├→ api/llm_utils.py 생성
  ├→ evidence/engine.py 공통 파이프라인 추출
  └→ id_mapper.py resolve 통합

Phase 4: MainWindow 분해 (FR-08)
  ├→ controllers/evaluation_ctrl.py
  ├→ controllers/gapfill_ctrl.py
  ├→ controllers/export_ctrl.py
  └→ controllers/version_ctrl.py

Phase 5: 보안 + 기타 (FR-03, FR-10, FR-11, FR-12)
  ├→ config.py 권한 + 환경변수
  ├→ constants.py HTTPS
  ├→ workers.py set_event_loop 제거
  └→ models.py reaction index
```

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`gui-refactoring.design.md`)
2. [ ] 각 Phase별 상세 파일 변경 목록 정의
3. [ ] 구현 시작

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-02-27 | Initial draft from code analysis results | Claude Code |
