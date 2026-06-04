# MetaTaskGapFill

Metabolic-task-aware gap-filling tool — draft SBML 모델, universal 모델, medium, metabolic task를 입력받아 KEGG/BiGG evidence 기반으로 누락 반응을 탐색하고 모델을 복구하는 도구.

## 주요 기능

- **SBML 모델 로딩**: COBRApy 기반 SBML 파싱 (반응, 유전자, 대사물질 추출)
- **Evidence 검증**: KEGG/BiGG 기반 반응 검증
  - **KEGG**: BiGG ID → KEGG 매핑을 통한 반응 존재 여부 및 기질/산물 일치도 확인
  - **BiGG Models**: 범용 반응 데이터베이스 검증
- **Confidence Scoring**: KEGG/BiGG 가중 점수 산출
- **Gap-Filling**: metabolic task 기반 자동 gap-filling (MILP 최적화)
  - Metabolic task 기반 모델 검증 (before/after 비교)
  - Organism-specific 유전자 필터링 (KEGG API)
  - GPR 규칙 자동 할당
- **반응 관리**: 반응 편집, 제거 (task impact preview 포함)
- **버전 관리**: 모델 변경 이력 추적 및 복원
- **GUI**: PySide6(Qt6) 기반 데스크톱 UI (반응 테이블, evidence 패널, 점수 시각화)
- **CLI 모드**: 서버/자동화 환경에서 evidence 평가와 task-aware gap-filling 실행
- **Export**: CSV / JSON 형식으로 평가 결과 내보내기
- **캐싱**: SQLite 기반 API 응답 캐시 (TTL 설정 가능)

## 환경 요구사항

| 항목 | 요구사항 |
|------|----------|
| Python | 3.10 이상 |
| OS | macOS, Linux |
| GUI | 디스플레이 환경 필요 (headless 시 `QT_QPA_PLATFORM=offscreen`) |

### 시스템 의존성

#### macOS

```bash
# Xcode Command Line Tools (libxml2 등 C 라이브러리 필요)
xcode-select --install

# Git LFS (데이터 파일 관리)
brew install git-lfs
```

#### Ubuntu / Debian

```bash
# 빌드 도구 및 Qt 의존성
sudo apt update
sudo apt install -y \
    python3.10-venv \
    build-essential \
    libgl1-mesa-glx \
    libegl1 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    libxkbcommon0 \
    libdbus-1-3 \
    git-lfs

# Wayland 환경의 경우 추가
sudo apt install -y libwayland-client0
```

#### Fedora / RHEL

```bash
sudo dnf install -y \
    python3-devel \
    gcc gcc-c++ \
    mesa-libGL \
    mesa-libEGL \
    libxcb \
    libxkbcommon \
    dbus-libs \
    git-lfs
```

## 설치

### 1. Git LFS 설치

`data/` 폴더의 매핑 데이터 파일(최대 77MB)은 Git LFS로 관리됩니다. 클론 전에 Git LFS가 설치되어 있어야 합니다.

```bash
git lfs install
```

### 2. 저장소 클론

```bash
git clone https://github.com/jyryu3161/model_evaluator.git MetaTaskGapFill
cd MetaTaskGapFill
```

> Git LFS가 설치된 상태에서 클론하면 `data/` 파일이 자동으로 다운로드됩니다.
> 이미 클론한 경우 `git lfs pull`로 데이터 파일을 받을 수 있습니다.

### 3. 가상환경 생성 및 활성화

```bash
python3 -m venv .venv
source .venv/bin/activate
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

### 5. 설치 확인

```bash
# Python 버전 확인
python --version  # 3.10 이상

# Qt 플러그인 정상 여부 확인
python -c "from PySide6.QtWidgets import QApplication; print('PySide6 OK')"

# COBRApy 확인
python -c "import cobra; print(f'COBRApy {cobra.__version__}')"
```

### 6. Pre-commit 훅 설치 (개발 시)

```bash
pre-commit install
```

## 환경 설정

### 평가 설정

앱 실행 후 **Settings** 대화상자에서 organism/evidence 설정을 조정하거나, 설정 파일을 직접 편집할 수 있습니다.

설정 파일 경로: `~/.metataskgapfill/config.json`

```json
{
  "kegg_organism_code": "eco",
  "organism_name": "Escherichia coli",
  "enable_bigg": true,
  "weight_kegg": 0.70,
  "weight_bigg": 0.30,
  "batch_size": 10,
  "max_concurrent": 5
}
```

### 주요 설정 항목

| 항목 | 기본값 | 설명 |
|------|--------|------|
| `kegg_organism_code` | `eco` | KEGG organism 코드 (예: `eco`, `sce`, `hsa`) |
| `organism_name` | `Escherichia coli` | organism 표시 이름 |
| `enable_bigg` | `true` | BiGG local lookup 사용 여부 |
| `weight_kegg` | `0.70` | KEGG 검증 가중치 |
| `weight_bigg` | `0.30` | BiGG 검증 가중치 |
| `batch_size` | `10` | 배치 평가 크기 |
| `max_concurrent` | `5` | 최대 동시 평가 수 |
| `default_universal_model` | `data/bigg_universal_model_fixed.json` | CLI/GUI gap-fill 기본 universal 모델 |
| `default_task_file` | `data/universal_essential_tasks.csv` | CLI/GUI gap-fill 기본 metabolic task CSV |
| `candidate_evidence_eager_limit` | `0` | `0`이면 모든 후보 반응 evidence를 gap-fill 전에 계산 |

### Headless 환경 (서버)

디스플레이가 없는 환경에서는:

```bash
export QT_QPA_PLATFORM=offscreen
```

## 실행

### GUI 애플리케이션

```bash
source .venv/bin/activate
python -m src.app
```

또는 (editable 설치 시):

```bash
metatask-gapfill
```

### CLI 모드

CLI는 두 가지 방식으로 사용할 수 있습니다.

1. **Evidence 평가 모드**: draft 모델의 기존 반응을 KEGG/BiGG로 평가하고 CSV/JSON으로 저장
2. **Gap-fill 모드**: draft 모델, universal 모델, medium, metabolic task를 입력받아 task-aware gap-filling 수행

#### Evidence 평가 모드

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
metatask-gapfill-cli input/iJO1366.xml -o output.csv
```

#### Gap-fill 모드

기본 입력은 다음 네 가지입니다.

| 입력 | CLI 옵션 | 필수 여부 | 설명 |
|------|----------|-----------|------|
| Draft 모델 | positional `MODEL.xml` | 필수 | 복구할 SBML/COBRA draft 모델 |
| Universal 모델 | `--universal PATH` | 선택 | JSON 또는 SBML universal 모델. 생략 시 설정값 또는 `data/bigg_universal_model_fixed.json` 사용 |
| Medium | `--medium PATH_OR_SPEC` | 선택 | 기본 배지. 생략 시 draft 모델의 COBRA `model.medium` 사용 |
| Metabolic task | `--tasks PATH` | 선택 | task CSV. 생략 시 설정값 또는 `data/universal_essential_tasks.csv` 사용 |

가장 일반적인 실행:

```bash
python -m src.cli data/iML1515.xml \
  --gap-fill \
  --universal data/bigg_universal_model_fixed.json \
  --tasks data/universal_essential_tasks.csv \
  --output-model output/iML1515_gapfilled.xml \
  --output-report output/iML1515_gapfill_report.csv
```

editable 설치 후:

```bash
metatask-gapfill-cli data/iML1515.xml \
  --gap-fill \
  --universal data/bigg_universal_model_fixed.json \
  --tasks data/universal_essential_tasks.csv \
  --output-model output/iML1515_gapfilled.xml \
  --output-report output/iML1515_gapfill_report.csv
```

medium을 생략하면 draft 모델의 default medium을 사용합니다.

```bash
python -m src.cli draft.xml \
  --gap-fill \
  --universal universal.json \
  --tasks tasks.csv \
  --output-model repaired.xml
```

medium을 inline spec으로 지정할 수 있습니다. 값은 exchange lower bound입니다.

```bash
python -m src.cli draft.xml \
  --gap-fill \
  --medium "glc__D_e(-10);o2_e(-1000);nh4_e(-1000)" \
  --tasks tasks.csv \
  --output-model repaired.xml
```

medium JSON 파일도 사용할 수 있습니다. 양수 값은 COBRA `model.medium` 스타일의 uptake capacity로 보고 음수 lower bound로 변환합니다.

```json
{
  "EX_glc__D_e": 10,
  "EX_o2_e": 1000,
  "EX_nh4_e": 1000
}
```

```bash
python -m src.cli draft.xml \
  --gap-fill \
  --medium medium.json \
  --tasks tasks.csv \
  --output-model repaired.xml
```

medium CSV 파일도 사용할 수 있습니다.

```csv
reaction_id,lower_bound
EX_glc__D_e,-10
EX_o2_e,-1000
EX_nh4_e,-1000
```

또는 uptake column을 양수로 줄 수 있습니다.

```csv
reaction_id,uptake
EX_glc__D_e,10
EX_o2_e,1000
EX_nh4_e,1000
```

task CSV의 `Medium` 컬럼은 CLI/model base medium 위에 적용되는 task-specific override입니다. 예를 들어 base medium에서 `EX_o2_e=-1000`이어도 특정 task가 `o2_e(0.0)`을 지정하면 해당 task에서는 산소 uptake가 닫힙니다.

evidence 계산을 건너뛰고 순수 task gap-fill만 실행하려면:

```bash
python -m src.cli draft.xml \
  --gap-fill \
  --universal universal.json \
  --tasks tasks.csv \
  --skip-evaluation \
  --output-model repaired.xml
```

gap-fill report CSV에는 요약, 추가된 반응, before/after task 결과가 포함됩니다.

```bash
python -m src.cli --help
metatask-gapfill-cli --help
```

### GUI 사용 순서

1. **모델 로드**: File > Open 에서 SBML 파일(`.xml`) 선택
2. **Settings 확인**: Settings에서 organism, API 키, 가중치 설정
3. **평가 실행**:
   - 개별 반응: 반응 선택 후 "Evaluate" 버튼
   - 전체 평가: "Evaluate All" 버튼
4. **결과 확인**: 반응 테이블에서 confidence score 확인, 반응 클릭 시 evidence 패널에서 상세 내용 확인
5. **Gap-Filling**: Gap-Fill 탭에서 universal model 로드 → 워크플로우 실행
6. **반응 제거**: 반응 우클릭 > "Remove Reaction..." 또는 상세 패널의 Remove 버튼
7. **버전 관리**: Version History 패널에서 변경 이력 확인 및 복원
8. **내보내기**: File > Export에서 CSV 또는 JSON으로 결과 저장

## 트러블슈팅

### Qt platform plugin 오류

```
qt.qpa.plugin: Could not find the Qt platform plugin "cocoa" in ""
```

PySide6 설치가 손상된 경우 발생합니다. 재설치로 해결:

```bash
source .venv/bin/activate
pip install --force-reinstall PySide6
```

위 명령이 `Cannot uninstall` 오류를 내면:

```bash
SITE_PKGS="$(python -c 'import site; print(site.getsitepackages()[0])')"
rm -rf "$SITE_PKGS/PySide6" "$SITE_PKGS/shiboken6" "$SITE_PKGS"/PySide6*.dist-info "$SITE_PKGS"/shiboken6*.dist-info
pip install PySide6
```

### Linux에서 `libGL.so.1` 오류

```bash
# Ubuntu/Debian
sudo apt install libgl1-mesa-glx libegl1

# Fedora/RHEL
sudo dnf install mesa-libGL mesa-libEGL
```

### Linux에서 `xcb` 관련 오류

```bash
# Ubuntu/Debian
sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon0

# 또는 XCB 대신 Wayland 사용
export QT_QPA_PLATFORM=wayland
```

### `ModuleNotFoundError: No module named 'PySide6'`

가상환경이 활성화되지 않은 경우:

```bash
source .venv/bin/activate
python -m src.app
```

### Git LFS 데이터 파일 누락

`data/` 파일이 텍스트 포인터(~130 bytes)로 보이는 경우:

```bash
git lfs install
git lfs pull
```

## 테스트

```bash
# 전체 테스트
pytest tests/ -v

# 커버리지 포함
pytest tests/ --cov=src --cov-report=term-missing

# 특정 모듈만
pytest tests/test_reaction_removal.py -v
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
│   ├── mapping_data.py    # 오프라인 매핑 데이터 로더
│   ├── cobra_utils.py     # COBRApy 모델 ↔ ModelData 변환
│   ├── task_parser.py     # Metabolic task 파서 및 FBA 실행기
│   └── universal_loader.py # BiGG universal model 로더
├── api/               # 외부 API 클라이언트 (비동기)
│   ├── base_client.py     # ABC: 속도 제한, 재시도, 서킷 브레이커
│   ├── rate_limiter.py    # 토큰 버킷 속도 제한기
│   ├── kegg_client.py     # KEGG REST API 클라이언트
│   ├── bigg_client.py     # BiGG Models API 클라이언트
│   └── bigg_lookup.py     # BiGG local lookup
├── evidence/          # Evidence 수집 및 스코어링
│   ├── engine.py          # KEGG/BiGG 반응 검증 실행
│   ├── scoring.py         # 가중 confidence 점수 산출
│   └── evidence_types.py  # 임계값 및 표시 상수
├── gapfill/           # Gap-filling 엔진
│   ├── engine.py          # MILP 기반 gap-fill 워크플로우
│   ├── organism_filter.py # KEGG API 기반 organism 유전자 필터
│   ├── penalty_calculator.py # 반응 페널티 계산
│   └── gpr_assigner.py   # GPR 규칙 자동 할당
├── gui/               # PySide6 (Qt6) GUI
│   ├── main_window.py     # 메인 앱 윈도우, 메뉴, 내보내기
│   ├── workers.py         # QRunnable 워커 (워커 스레드에서 비동기 실행)
│   ├── reaction_table.py  # 반응 테이블 모델 + 필터 프록시 + 위젯
│   ├── reaction_detail.py # 반응 상세 위젯 (편집, 제거)
│   ├── reaction_removal_dialog.py # 반응 제거 다이얼로그 (task impact preview)
│   ├── delegates.py       # 점수 바 및 상태 셀 렌더러
│   ├── model_overview.py  # 모델 개요 위젯
│   ├── evidence_panel.py  # Evidence 패널
│   ├── gene_panel.py      # 유전자 정보 패널
│   ├── metabolite_panel.py # 대사물질 정보 패널
│   ├── gapfill_panel.py   # Gap-filling 패널
│   ├── task_panel.py      # Metabolic task 패널
│   ├── workflow_wizard.py # Gap-fill 워크플로우 마법사
│   ├── version_panel.py   # 버전 이력 패널
│   ├── diff_dialog.py     # 버전 비교 다이얼로그
│   ├── score_visualization.py # PyQtGraph 차트
│   ├── progress_dialog.py # 진행률 대화상자
│   ├── settings_dialog.py # 설정 대화상자
│   ├── theme.py           # 테마 시스템
│   └── evidence_colors.py # Evidence 색상 상수
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
- **DB APIs**: Biopython (KEGG), aiohttp (REST), BiGG local lookup
- **Gap-Filling**: COBRApy MILP solver (GLPK/Gurobi)
- **캐싱**: SQLite (aiosqlite)
- **비동기**: QRunnable 워커 + asyncio 이벤트 루프 (워커 스레드, GUI) / asyncio.run (CLI)

## 라이선스

MIT
