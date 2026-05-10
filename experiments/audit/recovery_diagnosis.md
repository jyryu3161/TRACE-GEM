# Recovery Diagnosis — model_evaluator

**Date:** 2026-05-04
**Working dir:** `/Users/koonayeon/CSBL/model_evaluator`
**Current branch:** `auto-research` (HEAD = `ee293f4`)
**Diagnosis purpose:** 9b26311 "checkpoint" commit과 LFS 충돌 상태를 정상화

---

## ⚠️ TL;DR — 사용자가 알고 있던 것과 다른 점 3가지

1. **`origin/main`은 이미 `9b26311`이다** — 사용자는 "push 안 했다"고 했지만, `git ls-remote origin` (실시간 원격 조회)과 reflog `update by push` 양쪽 모두에서 push한 흔적 확인.
2. **`9b26311`은 "전부 비정상"이 아니다** — data/* 4개는 사실 **LFS pointer로 정상 변환**됐다. data/ 신규 5개도 LFS pointer로 들어갔다. 진짜 오염은 단 한 파일: 루트의 `iML1515-task-0%.json` (36.5MB raw blob).
3. **`ee293f4` (base)도 "깨끗"하지 않다** — `data/*` 4개가 raw blob (~106MB)으로 박혀있다. `.gitattributes`는 LFS라고 선언하지만 실제 변환은 `9b26311`이 한 것. 즉 LFS 도입 시점 = 9b26311.

---

## 1. Git/branch 상태

### 1.1 현재 HEAD 및 branch

```
* auto-research  → ee293f4
  main           → 9b26311
  origin/main    → 9b26311  ← REMOTE에도 9b26311이 있음
```

### 1.2 reflog (HEAD)
```
ee293f4 HEAD@{0}: checkout: moving from main to auto-research
9b26311 HEAD@{1}: commit: [checkpoint] consolidate prior work before auto-research branch
ee293f4 HEAD@{2}: checkout: moving from auto-research to main
ee293f4 HEAD@{3}: checkout: moving from main to auto-research
ee293f4 HEAD@{4}: pull: Fast-forward
ff7b7b8 HEAD@{5}: clone: from https://github.com/jyryu3161/model_evaluator
```

### 1.3 reflog (origin/main) — **push 흔적**
```
9b26311 refs/remotes/origin/main@{0}: update by push    ← 9b26311이 push됨
ee293f4 refs/remotes/origin/main@{1}: pull: fast-forward
```

### 1.4 ls-remote (실시간 원격 검증)
```
9b263119b08ff7c27e5813f930077914681b33fa  HEAD
9b263119b08ff7c27e5813f930077914681b33fa  refs/heads/main
```
→ 원격 main은 진짜로 9b26311. `auto-research` branch는 원격에 없음.

### 1.5 Stash
```
(empty)
```

### 1.6 Working tree (auto-research)
```
modified:   data/bigg_universal_model_fixed.json
modified:   data/reac_prop.tsv
modified:   data/reac_xref.tsv
modified:   data/universal_essential_tasks.csv

Untracked:
    prompt/
```

`prompt/`은 `.gitignore`에 있어야 하는데 ee293f4에는 없음 → 9b26311에는 추가됨.

---

## 2. LFS 환경

### 2.1 설치 및 필터
```
git-lfs/3.7.1 (GitHub; darwin arm64; go 1.25.3)

filter.lfs.smudge   = git-lfs smudge -- %f
filter.lfs.clean    = git-lfs clean -- %f
filter.lfs.process  = git-lfs filter-process
```
→ Global config에 LFS 필터 정상 설치되어 있음. `git lfs install --local` 추가 필요는 **없음**.

### 2.2 .gitattributes (양쪽 commit 동일)
```
data/** filter=lfs diff=lfs merge=lfs -text
```

### 2.3 commit별 LFS 추적 상태

| 파일 | ee293f4 | 9b26311 | 의미 |
|---|---|---|---|
| data/bigg_universal_model_fixed.json | raw 19MB blob | LFS pointer (133B) | 9b26311이 LFS로 마이그레이션 |
| data/reac_prop.tsv | raw 9.8MB blob | LFS pointer (133B) | 동일 |
| data/reac_xref.tsv | raw 77MB blob | LFS pointer (133B) | 동일 |
| data/universal_essential_tasks.csv | raw 7.3KB blob | LFS pointer (129B) | 동일 |
| data/bigg_models_metabolites.txt | (없음) | LFS pointer (132B) | 9b26311이 신규 추가 |
| data/bigg_models_reactions.txt | (없음) | LFS pointer (133B) | 동일 |
| data/e_coli_core.xml | (없음) | LFS pointer (131B) | 동일 |
| data/iML1515.xml | (없음) | LFS pointer (133B) | 동일 |
| data/universal_model.json | (없음) | LFS pointer (133B) | 동일 |

### 2.4 LFS fsck (현재 HEAD = ee293f4 기준)
```
pointer: unexpectedGitObject: "data/reac_prop.tsv" (treeish ee293f4) should have been a pointer but was not
pointer: unexpectedGitObject: "data/universal_essential_tasks.csv" should have been a pointer but was not
pointer: unexpectedGitObject: "data/bigg_universal_model_fixed.json" should have been a pointer but was not
pointer: unexpectedGitObject: "data/reac_xref.tsv" should have been a pointer but was not
```
→ ee293f4 base에서 .gitattributes는 LFS인데 파일들이 raw blob. 9b26311이 그걸 fix했음.

### 2.5 LFS object cache (downloaded `*` vs not `-`)
```
9b26311 기준:
  ae282c0dff *  data/bigg_universal_model_fixed.json   (있음)
  8582cc187d *  data/reac_prop.tsv                     (있음)
  2610e2998f *  data/reac_xref.tsv                     (있음)
  697c652cfb *  data/universal_essential_tasks.csv     (있음)
  2b12a1871e -  data/bigg_models_metabolites.txt       (캐시에 없음)
  e1c11add0c -  data/bigg_models_reactions.txt         (캐시에 없음)
  b4db506aee -  data/e_coli_core.xml                   (캐시에 없음)
  9c772d44ca -  data/iML1515.xml                       (캐시에 없음)
  a9ebc6df7f -  data/universal_model.json              (캐시에 없음)
```
→ 기존 4개는 working dir에 raw 형태로 있어서 LFS oid와 매칭됨. 5개는 working dir에서 사라진 상태.

---

## 3. 4개 충돌 파일의 실제 상태 (현재 working dir)

| 파일 | head -1 | file 명령 | 크기 | 결론 |
|---|---|---|---|---|
| data/bigg_universal_model_fixed.json | `{"metabolites": [{"id": "4crsol_c"...}` | ASCII text long lines | 19M | **실제 데이터** |
| data/reac_prop.tsv | `### MetaNetX/MNXref reconciliation ###` | ASCII text | 9.8M | **실제 데이터** |
| data/reac_xref.tsv | `### MetaNetX/MNXref reconciliation ###` | ASCII text | 77M | **실제 데이터** |
| data/universal_essential_tasks.csv | `Task ID,Type,ID,Medium,Constraints,...` | CSV text | 7.3K | **실제 데이터** |

→ 4개 모두 **LFS pointer가 아니라 실제 파일**. ee293f4에 raw blob으로 박혀있는 게 working dir에 그대로 풀린 것.

`git lfs status`:
```
data/bigg_universal_model_fixed.json (Git: ae282c0 -> File: ae282c0)
data/reac_prop.tsv                   (Git: 8582cc1 -> File: 8582cc1)
data/reac_xref.tsv                   (Git: 2610e29 -> File: 2610e29)
data/universal_essential_tasks.csv   (Git: 697c652 -> File: 697c652)
```
→ "Git" oid와 "File" oid가 일치 = working dir의 raw 내용 SHA256이 LFS pointer가 가리켜야 할 oid와 같다 → working dir의 데이터는 **9b26311이 가리키는 LFS pointer 내용과 정확히 동일** (즉 보존되어 있음, 손실 없음).

`git status`가 modified로 보고하는 이유: ee293f4의 raw blob hash (4cbe0b3 등) ≠ LFS clean filter가 만들어내는 pointer hash. **데이터 자체의 차이가 아니라 표현 형식의 차이**.

---

## 4. data/ 디렉토리 인벤토리 (현재 working dir, ee293f4)

| 파일 | 크기 | mtime | 분류 | 출처/처리 방침 후보 |
|---|---|---|---|---|
| bigg_universal_model_fixed.json | 19M | 5/4 16:44 | C (가공된 reference) | LFS commit |
| reac_prop.tsv | 9.8M | 5/4 16:44 | B (외부 DB; MetaNetX) | LFS or download script |
| reac_xref.tsv | 77M | 5/4 16:44 | B (외부 DB; MetaNetX) | LFS or download script |
| universal_essential_tasks.csv | 7.3K | 5/4 16:44 | C (가공된 reference) | 일반 commit (작음) |

총 합계: **106M**

> 9b26311에는 추가로 5개 파일 (e_coli_core.xml, iML1515.xml, bigg_models_metabolites.txt, bigg_models_reactions.txt, universal_model.json)이 LFS pointer로 들어가 있으나 working dir 캐시에는 없음. main으로 checkout하면 LFS download 필요.

### 분류 정의
- **A (핵심 입력 모델, repo에 포함)**: e_coli_core.xml, iML1515.xml — SBML 모델, 연구 입력
- **B (외부 DB 캐시, ignore 가능)**: reac_prop.tsv, reac_xref.tsv (MetaNetX), bigg_models_*.txt, universal_model.json — 다운로드로 재현 가능
- **C (가공된 reference)**: universal_essential_tasks.csv (작음), bigg_universal_model_fixed.json — 사용자 가공물
- **D (임시 산출물)**: iML1515-task-0%.json, output.csv — 빌드 결과, 항상 .gitignore

---

## 5. 9b26311 commit 변경 내역 분석

### 5.1 stat 요약
```
28 files changed, 1072597 insertions(+), 562804 deletions(-)
```

### 5.2 1M+ insertion의 진짜 원인 — **`iML1515-task-0%.json` 한 파일**

루트(data/ 아님)에 추가된 `iML1515-task-0%.json`:
- git blob hash: `8fb86e1af13a1be2af65609a588975ee1c60241a`
- 크기: **36,476,823 bytes (36.5MB)** raw blob
- 추가 줄 수: **1,071,446줄** (전체 insertion 1,072,597 중 99.9%)

→ **이 한 파일이 1M 줄 추가의 거의 전부.** 나머지 코드 변경 + LFS pointer 추가 + .gitignore 변경 등은 합쳐서 ~1,150줄.

### 5.3 562k deletion의 원인 — raw blob → LFS pointer 변환

ee293f4에 raw로 박혀 있던 3개 파일을 9b26311이 LFS pointer로 바꾸면서 삭제로 카운트:
- `data/reac_prop.tsv`: 84,188줄 raw → 3줄 pointer = 84,185 deletion
- `data/reac_xref.tsv`: 478,490줄 raw → 3줄 pointer = 478,487 deletion
- `data/universal_essential_tasks.csv`: 56줄 변경
- 합계 ≈ 562,728 deletion (실제 562,804와 ~76줄 오차는 코드 수정에서 발생)

→ **deletion은 비정상이 아니라 LFS 정상화의 결과**.

### 5.4 9b26311의 28개 파일 분류

| 분류 | 파일 | 처리 |
|---|---|---|
| **버려야 함** | `iML1515-task-0%.json` (36MB raw) | DROP — 빌드 산출물 |
| **버려야 함** | `output.csv` (709B) | DROP — 임시 결과 |
| **유지 (LFS 변환은 좋음)** | data/bigg_universal_model_fixed.json | KEEP as LFS |
| **유지 (LFS 변환은 좋음)** | data/reac_prop.tsv | KEEP as LFS (또는 .gitignore + 다운로드) |
| **유지 (LFS 변환은 좋음)** | data/reac_xref.tsv | KEEP as LFS (또는 .gitignore + 다운로드) |
| **유지 (LFS 변환은 좋음)** | data/universal_essential_tasks.csv | KEEP (작음, 일반 commit도 가능) |
| **신규, 핵심 모델** | data/iML1515.xml | KEEP as LFS |
| **신규, 핵심 모델** | data/e_coli_core.xml | KEEP as LFS |
| **신규, 외부 캐시** | data/bigg_models_metabolites.txt | .gitignore 권장 |
| **신규, 외부 캐시** | data/bigg_models_reactions.txt | .gitignore 권장 |
| **신규, 외부 캐시** | data/universal_model.json | .gitignore 권장 |
| **유지** | .gitignore (prompt/ 추가) | KEEP |
| **유지** | src/* 14개 파일 (코드 수정) | KEEP — 실제 작업물 |

→ 9b26311의 본질은 "**LFS 마이그레이션 + 코드 작업 + 신규 데이터 + 빌드 산출물 오염**"
→ 회수해야 할 것: 코드 수정 14개 + LFS 변환 + 핵심 모델 추가
→ 버려야 할 것: `iML1515-task-0%.json` + `output.csv`

### 5.5 9b26311 트리에서 가장 큰 blob들
```
36,476,823  iML1515-task-0%.json     ← 유일한 36MB 오염원
    40,893  src/gui/main_window.py
    40,693  docs/02-design/features/gap-filling-platform.design.md
    29,190  docs/archive/2026-02/.../workflow-resume-universal-browser.design.md
    ...
```
→ 두 번째로 큰 파일이 40KB. iML1515-task-0%.json이 다른 모든 파일을 압도.

---

## 6. agent.md 백업 검증

```
-rw-r--r--  1 koonayeon  staff  15492  May 4 12:58  /Users/koonayeon/agent.md.backup
```
- 크기: 15.5KB
- 내용 미리보기:
  ```
  # agent.md — Model Evaluator (auto-research branch)
  > 이 문서는 AI 코딩 에이전트(Claude Code, bikit/autoresearch)의 연구 운용 지침서입니다.
  ...
  ```
- ✅ 정상 보존됨, 복구 시 사용 가능.

---

## 7. 핵심 결론

### 7.1 사실 정리
1. `origin/main = 9b26311` (이미 push된 상태). 사용자 가정과 다름.
2. `9b26311`의 본질적 문제는 **단 한 파일 (`iML1515-task-0%.json` 36MB)**. 나머지는 대부분 정상 작업.
3. `ee293f4` 자체에 data/* 4개가 raw blob으로 박혀있어 origin 시점부터 ~106MB 히스토리 부담이 존재.
4. 데이터 손실 위험은 0 — 모든 작업물 (working dir 4파일 + agent.md 백업)이 보존됨.
5. LFS 인프라는 정상 설치돼 있고 9b26311의 LFS pointer 변환도 정상 작동.

### 7.2 복구 전략 갈래 (사용자 결정 필요)

#### Option A — 9b26311 위에 정리 commit 쌓기 (가장 안전, 히스토리 보존)
- iML1515-task-0%.json만 `git rm` + .gitignore 추가
- output.csv도 동일 처리
- LFS 마이그레이션과 코드 변경은 그대로 유지
- 새 정리 commit 1개 추가 → push (force-push 불필요)
- **단점**: 36MB가 git history(9b26311)에 영원히 남음. clone 시 매번 다운로드.

#### Option B — 9b26311 reset + 의미 단위 재commit + force-push (히스토리 깔끔, force-push 필요)
- `git reset --mixed HEAD~1`로 9b26311 변경분을 working dir에 보존
- `iML1515-task-0%.json`, `output.csv` 빼고 의미 단위 commit 4~5개로 재구성
- `git push --force-with-lease origin main` 필요
- **단점**: force-push. 다른 협업자가 있으면 충돌. (이 repo는 jyryu3161 계정 단독으로 보임)
- **장점**: 히스토리에서 36MB 완전 제거, repo 크기 감소.

#### Option C — Option B + ee293f4의 raw data/* 도 LFS로 재작성 (history rewrite)
- `git filter-repo` 또는 BFG로 ee293f4까지 거슬러 올라가 data/* raw blob을 LFS pointer로 변환
- 100MB+ history bloat 완전 해소
- **단점**: 매우 침습적, 모든 commit hash 변경, force-push 범위 큼
- **장점**: clone 크기 최소화, 진정한 정상화

### 7.3 추천 — Option B (사용자 확인 필수)
- 36MB 오염을 main 히스토리에서 제거하면서 작업 commit은 의미 있게 분리
- ee293f4의 raw blob은 그대로 두지만 (Option C는 과함), 추후 큰 문제는 아님
- force-push는 1회로 끝남, 사용자가 단독 owner로 보여 충돌 위험 낮음

### 7.4 다음 단계 결정 항목
1. ✅/❌ Option B 진행에 동의?
2. data/reac_prop.tsv, data/reac_xref.tsv (총 87MB, MetaNetX 외부 DB) — LFS commit? 아니면 .gitignore + 다운로드 스크립트?
3. data/iML1515.xml, data/e_coli_core.xml — LFS로 commit (찬성 가정)
4. data/bigg_models_metabolites.txt, data/bigg_models_reactions.txt, data/universal_model.json — .gitignore? 아니면 LFS?
5. data/universal_essential_tasks.csv (7.3KB) — 일반 commit으로 OK?
6. force-push 시점은 사용자 명시 승인 후에만.
