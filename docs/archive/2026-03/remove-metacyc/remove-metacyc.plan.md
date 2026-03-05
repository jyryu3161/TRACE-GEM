# Plan: Remove MetaCyc Integration

## Overview
MetaCyc/BioCyc API client를 코드베이스에서 완전히 제거한다. MetaCyc는 현재 `enable_metacyc: bool = False`로 기본 비활성화 상태이며, 제한된 무료 API 접근으로 실질적 가치가 낮다. 제거 후 나머지 6개 evidence source의 가중치를 재분배하고, 모든 기존 기능을 유지한다.

## Scope

### 삭제 대상
| File | Action | Detail |
|------|--------|--------|
| `src/api/metacyc_client.py` | **파일 삭제** | MetaCycClient 클래스 전체 |
| `tests/test_metacyc_client.py` | **파일 삭제** | MetaCyc 테스트 전체 |

### 수정 대상 (12 files)
| File | Changes |
|------|---------|
| `src/core/models.py` | `EvidenceSource.METACYC` enum 제거, `metacyc_score` field 제거 |
| `src/utils/constants.py` | `METACYC_API_BASE`, rate_limits/weights에서 metacyc 제거 |
| `src/utils/config.py` | `weight_metacyc`, `enable_metacyc` 제거, weights() 메서드 수정 |
| `src/evidence/engine.py` | `_metacyc` 초기화/사용/close 제거 (Step 7 MetaCyc verification 블록) |
| `src/evidence/scoring.py` | `metacyc_score` 할당 라인 제거 |
| `src/evidence/evidence_types.py` | METACYC display name, color, SourceConfig 제거 |
| `src/gui/evidence_panel.py` | METACYC source card 제거 |
| `src/gui/evidence_colors.py` | METACYC color mapping 제거 |
| `src/gui/theme.py` | `source_metacyc` 색상 속성 제거 |
| `src/gui/main_window.py` | About dialog 텍스트에서 "MetaCyc" 언급 제거 |
| `src/api/perplexity_client.py` | Prompt 텍스트에서 "MetaCyc" 제거 |
| `tests/test_evidence_types.py` | METACYC 관련 테스트 assertion 수정 |
| `tests/test_multi_source_integration.py` | METACYC 관련 참조 제거 |

### 가중치 재분배
현재 (7 sources, total = 1.0):
- KEGG: 0.30, BiGG: 0.15, UniProt: 0.15, PubMed: 0.10, **MetaCyc: 0.10**, Gemini: 0.10, Perplexity: 0.10

제거 후 (6 sources, total = 1.0):
- KEGG: 0.30, BiGG: 0.15, UniProt: 0.15, PubMed: 0.15, Gemini: 0.125, Perplexity: 0.125

근거: MetaCyc의 0.10 가중치를 나머지 DB sources (PubMed +0.05)와 LLM sources (각 +0.025)에 분배.

## Implementation Order
1. `models.py` — enum/field 제거 (다른 파일들의 기반)
2. `constants.py`, `config.py` — 설정값 제거 및 가중치 재분배
3. `evidence/engine.py` — MetaCyc 클라이언트 초기화/호출 제거
4. `evidence/scoring.py`, `evidence_types.py` — scoring 관련 제거
5. `gui/*` — UI 참조 제거
6. `api/perplexity_client.py` — prompt 텍스트 수정
7. `metacyc_client.py` — 파일 삭제
8. `tests/*` — 테스트 파일 삭제/수정
9. 전체 테스트 실행 검증

## Risk Assessment
- **Risk Level**: Low — MetaCyc는 이미 기본 비활성화 상태
- **기존 기능 영향**: 없음 — 6개 source로 정상 동작
- **Rollback**: git revert로 즉시 복원 가능

## Acceptance Criteria
- [ ] `METACYC` 관련 코드 0건 (grep 확인)
- [ ] 6개 source 가중치 합계 = 1.0
- [ ] 전체 테스트 pass (기존 402개 기준)
- [ ] 앱 import 정상
