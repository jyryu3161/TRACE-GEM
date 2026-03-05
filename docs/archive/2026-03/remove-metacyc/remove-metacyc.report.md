# Completion Report: remove-metacyc

**Date**: 2026-03-03
**Match Rate**: 100%
**Status**: COMPLETED

## Summary

MetaCyc/BioCyc API 클라이언트를 코드베이스에서 완전히 제거. MetaCyc는 `enable_metacyc: False`로 기본 비활성화 상태였으며, 제한된 무료 API 접근으로 실질적 가치가 낮아 제거 결정. 나머지 6개 evidence source의 가중치를 재분배하여 합계 1.0 유지.

## PDCA Cycle

| Phase | Status | Detail |
|-------|:------:|--------|
| Plan | DONE | `docs/01-plan/features/remove-metacyc.plan.md` |
| Design | SKIPPED | 단순 제거 작업으로 별도 설계 불필요 |
| Do | DONE | 2개 파일 삭제, 13개 파일 수정 |
| Check | DONE | Match Rate 100% |
| Report | DONE | 본 문서 |

## Changes Made

### Files Deleted (2)
| File | Description |
|------|-------------|
| `src/api/metacyc_client.py` | MetaCycClient 클래스 전체 |
| `tests/test_metacyc_client.py` | MetaCyc 클라이언트 테스트 |

### Files Modified (13)
| File | Change |
|------|--------|
| `src/core/models.py` | `EvidenceSource.METACYC` enum 제거, `metacyc_score` field 제거 |
| `src/utils/constants.py` | `METACYC_API_BASE` 제거, rate_limits/weights에서 metacyc 제거 |
| `src/utils/config.py` | `weight_metacyc`, `enable_metacyc` 제거, weights() 수정 |
| `src/evidence/engine.py` | `_metacyc` 초기화/호출/close 블록 제거 |
| `src/evidence/scoring.py` | `metacyc_score` 할당 라인 제거 |
| `src/evidence/evidence_types.py` | METACYC label, color, SourceConfig 제거 |
| `src/gui/evidence_panel.py` | METACYC source card 제거 |
| `src/gui/evidence_colors.py` | METACYC color mapping 제거 |
| `src/gui/theme.py` | `source_metacyc` 색상 속성 제거 |
| `src/gui/main_window.py` | About 텍스트에서 "MetaCyc" 제거 |
| `src/api/perplexity_client.py` | Prompt에서 "MetaCyc" 제거 |
| `tests/test_evidence_types.py` | 7 → 6 sources, MockConfig에서 metacyc 제거 |
| `tests/test_multi_source_integration.py` | `metacyc_score` assertion 제거 |
| `tests/test_models.py` | EvidenceSource count 7 → 6 |
| `tests/fixtures/mock_bigg_response.json` | MetaCyc cross-reference 항목 제거 |

### Weight Redistribution
| Source | Before | After |
|--------|:------:|:-----:|
| KEGG | 0.30 | 0.30 |
| BiGG | 0.15 | 0.15 |
| UniProt | 0.15 | 0.15 |
| PubMed | 0.10 | **0.15** |
| Gemini | 0.10 | **0.125** |
| Perplexity | 0.10 | **0.125** |
| ~~MetaCyc~~ | ~~0.10~~ | removed |
| **Total** | **1.0** | **1.0** |

## Verification

| Check | Result |
|-------|:------:|
| `grep -ri metacyc src/` | 0 matches |
| `grep -ri metacyc tests/` | 0 matches |
| Weight sum | 1.0 |
| Tests | 398 passed, 46 skipped, 0 failed |
| App imports | All clean |
