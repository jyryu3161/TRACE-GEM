# GEM Evaluator

Genome-Scale Metabolic Model Evidence Evaluator — SBML 모델의 반응(reaction)을 7개 생물학적 데이터베이스 및 LLM 소스(KEGG, BiGG, UniProt, PubMed, MetaCyc, Gemini, Perplexity)를 사용하여 검증하고 confidence score를 산출하는 도구.

## 주요 기능

- **SBML 모델 로딩**: COBRApy 기반 SBML 파싱 (반응, 유전자, 대사물질 추출)
- **다중 소스 검증**: 7개 evidence 소스를 통한 반응 검증
  - **KEGG**: BiGG ID → KEGG 매핑을 통한 반응 존재 여부 및 기질/산물 일치도 확인
  - **BiGG Models**: 범용 반응 데이터베이스 검증
  - **UniProt**: 단백질/유전자 기반 evidence
  - **PubMed**: 문헌 기반 evidence
  - **MetaCyc**: MetaCyc/BioCyc 경로 데이터베이스
  - **Gemini**: LLM 기반 반응 정합성 검증
  - **Perplexity**: LLM 기반 organism 특이성 검증
- **Confidence Scoring**: 7-source 가중 점수 산출
- **GUI**: PySide6(Qt6) 기반 데스크톱 UI (반응 테이블, evidence 패널, 점수 시각화)
- **CLI 배치 평가**: 서버/자동화 환경에서 전체 반응 평가 및 결과 파일 내보내기
- **Export**: CSV / JSON 형식으로 평가 결과 내보내기
- **캐싱**: SQLite 기반 API 응답 캐시 (TTL 설정 가능)

## 환경 요구사항

| 항목 | 요구사항 |
|------|----------|
| Python | 3.10 이상 |
| OS | macOS, Linux, Windows |
| GUI | 디스플레이 환경 (headless 시 `QT_QPA_PLATFORM=offscreen`) |

### API 키 (선택)

LLM 검증 기능을 사용하려면 아래 API 키가 필요합니다. 없어도 KEGG/BiGG/UniProt/PubMed/MetaCyc 기반 평가는 동작합니다.

| 서비스 | 용도 | 발급처 |
|--------|------|--------|
| Gemini API | KEGG 매핑 정합성 검증 | [Google AI Studio](https://aistudio.google.com/apikey) |
| Perplexity API | Organism 특이적 반응 존재 검증 | [Perplexity Settings](https://www.perplexity.ai/settings/api) |

## 설치

### 1. Git LFS 설치

`data/` 폴더의 매핑 데이터 파일(최대 77MB)은 Git LFS로 관리됩니다. 클론 전에 Git LFS가 설치되어 있어야 합니다.

```bash
# macOS
brew install git-lfs

# Ubuntu / Debian
sudo apt install git-lfs

# Windows (Git for Windows에 포함)
# 별도 설치 불필요

git lfs install
```

### 2. 저장소 클론

```bash
git clone https://github.com/jyryu3161/model_evaluator.git
cd model_evaluator
```

> Git LFS가 설치된 상태에서 클론하면 `data/` 파일이 자동으로 다운로드됩니다.
> 이미 클론한 경우 `git lfs pull`로 데이터 파일을 받을 수 있습니다.

### 3. 가상환경 생성 및 활성화

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 4. 의존성 설치

```bash
# 실행만 하는 경우
pip install -r requirements.txt

# 개발 (테스트, 린트, 타입체크 포함)
pip install -r requirements-dev.txt
```

또는 editable 모드로 설치:

```bash
pip install -e ".[dev]"
```

### 5. Pre-commit 훅 설치 (개발 시)

```bash
pre-commit install
```

## 환경 설정

### API 키 설정

앱 실행 후 **Settings** 대화상자에서 API 키를 입력하거나, 설정 파일을 직접 편집할 수 있습니다.

설정 파일 경로: `~/.gem_evaluator/config.json`

```json
{
  "kegg_organism_code": "eco",
  "organism_name": "Escherichia coli",
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "perplexity_api_key": "YOUR_PERPLEXITY_API_KEY",
  "enable_bigg": true,
  "enable_uniprot": true,
  "enable_pubmed": true,
  "enable_metacyc": false,
  "enable_gemini": true,
  "enable_perplexity": true,
  "weight_kegg": 0.30,
  "weight_bigg": 0.15,
  "weight_uniprot": 0.15,
  "weight_pubmed": 0.10,
  "weight_metacyc": 0.10,
  "weight_gemini": 0.10,
  "weight_perplexity": 0.10,
  "batch_size": 10,
  "max_concurrent": 5
}
```

### 주요 설정 항목

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `kegg_organism_code` | `eco` | KEGG organism 코드 (예: `eco`, `sce`, `hsa`) |
| `organism_name` | `Escherichia coli` | LLM 프롬프트에 사용되는 organism 이름 |
| `weight_kegg` | `0.30` | KEGG 검증 가중치 |
| `weight_bigg` | `0.15` | BiGG 검증 가중치 |
| `weight_uniprot` | `0.15` | UniProt 검증 가중치 |
| `weight_pubmed` | `0.10` | PubMed 검증 가중치 |
| `weight_metacyc` | `0.10` | MetaCyc 검증 가중치 |
| `weight_gemini` | `0.10` | Gemini 검증 가중치 |
| `weight_perplexity` | `0.10` | Perplexity 검증 가중치 |
| `batch_size` | `10` | 배치 평가 크기 |
| `max_concurrent` | `5` | 최대 동시 평가 수 |

### Headless 환경 (서버)

디스플레이가 없는 환경에서는:

```bash
export QT_QPA_PLATFORM=offscreen
```

## 실행

### GUI 애플리케이션

```bash
python -m src.app
```

또는 (editable 설치 시):

```bash
gem-evaluator
```

### CLI 배치 평가

서버/자동화 환경에서 전체 반응을 평가하고 결과를 파일로 내보냅니다.

```bash
# 기본 CSV 출력
python -m src.cli input/iJO1366.xml

# 출력 파일 지정 (확장자로 형식 자동 판별)
python -m src.cli input/iJO1366.xml -o output.csv
python -m src.cli input/iJO1366.xml -o output.json

# 형식 강제 지정
python -m src.cli input/iJO1366.xml -o results.txt -f json

# 옵션
python -m src.cli input/iJO1366.xml --organism eco --skip-exchange --batch-size 20 --max-concurrent 10

# 도움말
python -m src.cli --help
```

또는 (editable 설치 시):

```bash
gem-evaluator-cli input/iJO1366.xml -o output.csv
```

### GUI 사용 순서

1. **모델 로드**: File > Open 에서 SBML 파일(`.xml`) 선택
2. **Settings 확인**: Settings에서 organism, API 키, 가중치 설정
3. **평가 실행**:
   - 개별 반응: 반응 선택 후 "Evaluate" 버튼
   - 전체 평가: "Evaluate All" 버튼
4. **결과 확인**: 반응 테이블에서 confidence score 확인, 반응 클릭 시 evidence 패널에서 상세 내용 확인
5. **내보내기**: File > Export에서 CSV 또는 JSON으로 결과 저장

## 테스트

```bash
# 전체 테스트
pytest tests/ -v

# 커버리지 포함
pytest tests/ --cov=src --cov-report=term-missing

# 특정 모듈만
pytest tests/test_gemini_client.py -v
```

## 개발 도구

```bash
# 린트 및 자동 수정
ruff check src/ tests/ --fix

# 코드 포맷팅
ruff format src/ tests/

# 타입 체크
mypy src/ --ignore-missing-imports

# Pre-commit (모든 훅)
pre-commit run --all-files
```

## 프로젝트 구조

```
src/
├── core/              # 데이터 모델, SBML 파싱, GPR 파싱, ID 매핑
│   ├── models.py          # Reaction, ModelData, EvidenceItem 등 데이터클래스
│   ├── sbml_parser.py     # COBRApy 기반 SBML 로더
│   ├── gpr_parser.py      # Gene-Protein-Reaction 규칙 파서
│   ├── id_mapper.py       # BiGG → KEGG/EC 외부 DB ID 변환
│   └── mapping_data.py    # 오프라인 매핑 데이터 로더
├── api/               # 외부 API 클라이언트 (비동기)
│   ├── base_client.py     # ABC: 속도 제한, 재시도, 서킷 브레이커
│   ├── rate_limiter.py    # 토큰 버킷 속도 제한기
│   ├── kegg_client.py     # KEGG REST API 클라이언트
│   ├── bigg_client.py     # BiGG Models API 클라이언트
│   ├── uniprot_client.py  # UniProt REST API 클라이언트
│   ├── pubmed_client.py   # PubMed/NCBI API 클라이언트
│   ├── metacyc_client.py  # MetaCyc/BioCyc API 클라이언트
│   ├── gemini_client.py   # Gemini 2.5 Flash 검증 클라이언트
│   └── perplexity_client.py # Perplexity Sonar 검증 클라이언트
├── evidence/          # Evidence 수집 및 스코어링
│   ├── engine.py          # 오케스트레이터: 7개 소스별 반응 검증 실행
│   ├── scoring.py         # 가중 다중 소스 confidence 점수 산출
│   └── evidence_types.py  # 임계값 및 표시 상수
├── gui/               # PySide6 (Qt6) GUI
│   ├── main_window.py     # 메인 앱 윈도우, 메뉴, 내보내기
│   ├── workers.py         # QRunnable 워커 (워커 스레드에서 비동기 실행)
│   ├── reaction_table.py  # 반응 테이블 모델 + 필터 프록시 + 위젯
│   ├── delegates.py       # 점수 바 및 상태 셀 렌더러
│   ├── model_overview.py  # 모델 개요 위젯
│   ├── reaction_detail.py # 반응 상세 위젯
│   ├── evidence_panel.py  # Evidence 패널
│   ├── gene_panel.py      # 유전자 정보 패널
│   ├── metabolite_panel.py # 대사물질 정보 패널
│   ├── score_visualization.py # PyQtGraph 차트
│   ├── progress_dialog.py # 진행률 대화상자
│   ├── settings_dialog.py # 설정 대화상자
│   ├── theme.py           # 테마 시스템
│   └── styles.py          # 스타일시트
├── cache/             # SQLite 캐싱 레이어
│   ├── cache_manager.py
│   └── schema.py
├── utils/             # 설정, 로깅, 상수
│   ├── config.py
│   ├── constants.py
│   └── logging_config.py
├── app.py             # GUI 엔트리 포인트
└── cli.py             # CLI 배치 평가 엔트리 포인트
```

## 기술 스택

- **SBML 파싱**: COBRApy (libsbml 래핑)
- **GUI**: PySide6 (Qt6) + PyQtGraph
- **DB APIs**: Biopython (KEGG, PubMed), aiohttp (BiGG, UniProt, MetaCyc REST)
- **LLM APIs**: google-genai (Gemini), openai SDK (Perplexity)
- **캐싱**: SQLite (aiosqlite)
- **비동기**: QRunnable 워커 + asyncio 이벤트 루프 (워커 스레드, GUI) / asyncio.run (CLI)

## 라이선스

MIT
