#!/usr/bin/env bash
# Set up the MetaTaskGapFill + CarveMe environment.
#
#   scripts/setup_env.sh            # conda path (recommended, installs diamond)
#   scripts/setup_env.sh uv         # uv path (fast Python deps; diamond separate)
#
# The only non-pip dependency is `diamond` (CarveMe's aligner): the conda path
# installs it from bioconda; the uv path installs Python deps fast but you must
# provide diamond yourself (brew install diamond, or conda install -c bioconda
# diamond). Gurobi needs an academic license; SCIP (pyscipopt) is the free
# fallback.
set -euo pipefail
MODE="${1:-conda}"
ENV_NAME="${ENV_NAME:-metatask}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

smoke() {
  local py="$1"
  echo "=== smoke check ==="
  "$py" -c "import cobra, PySide6, yaml; print('app deps OK: cobra', cobra.__version__)" || echo "APP IMPORT FAILED"
  "${2:-carve}" --help >/dev/null 2>&1 && echo "carve: OK" || echo "carve: MISSING (pip install carveme)"
  "${3:-diamond}" --version 2>/dev/null && echo "diamond: OK" || echo "diamond: MISSING (conda install -c bioconda diamond / brew install diamond)"
  "$py" -c "import gurobipy; gurobipy.Model('t').optimize(); print('gurobi: OK')" 2>/dev/null || echo "gurobi: no license (use SCIP via --carveme-solver scip)"
}

case "$MODE" in
  conda)
    echo "### conda env create -f environment.yml (env: $ENV_NAME)"
    conda env create -n "$ENV_NAME" -f environment.yml || conda env update -n "$ENV_NAME" -f environment.yml
    BIN="$(conda run -n "$ENV_NAME" python -c 'import sys,os;print(os.path.dirname(sys.executable))')"
    smoke "$BIN/python" "$BIN/carve" "$BIN/diamond"
    echo "Done. Activate with: conda activate $ENV_NAME"
    ;;
  uv)
    echo "### uv venv + uv pip install -e .[dev,build]"
    command -v uv >/dev/null || { echo "uv not found — install from https://docs.astral.sh/uv/"; exit 1; }
    uv venv
    uv pip install -e ".[dev,build]"
    echo "NOTE: install the diamond binary separately:"
    echo "      conda install -c bioconda diamond   # or:   brew install diamond"
    smoke ".venv/bin/python" ".venv/bin/carve" "diamond"
    echo "Done. Activate with: source .venv/bin/activate"
    ;;
  *)
    echo "usage: $0 [conda|uv]"; exit 1;;
esac
