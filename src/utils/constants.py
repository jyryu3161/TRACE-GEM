"""Constants for TRACE-GEM."""

import site
import sys
import sysconfig
from pathlib import Path

APP_NAME = "TRACE-GEM"
APP_VERSION = "0.2.0"

# Default directories
CONFIG_DIR = Path.home() / ".metataskgapfill"
CACHE_DB_PATH = CONFIG_DIR / "cache.db"
CONFIG_FILE_PATH = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"

# Source checkouts keep data beside ``src``; wheels install the same files
# below the environment prefix via ``tool.setuptools.data-files``.
_SOURCE_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DATA_DIR_CANDIDATES = (
    _SOURCE_DATA_DIR,
    Path(sysconfig.get_path("data") or sys.prefix) / "share" / "metatask-gapfill" / "data",
    Path(site.USER_BASE or sys.prefix) / "share" / "metatask-gapfill" / "data",
    Path(sys.prefix) / "share" / "metatask-gapfill" / "data",
)
DATA_DIR = next(
    (
        candidate
        for candidate in _DATA_DIR_CANDIDATES
        if (candidate / "universal_essential_tasks.csv").is_file()
    ),
    _DATA_DIR_CANDIDATES[1],
)

# Cache TTL (seconds)
API_CACHE_TTL = 7 * 24 * 3600  # 7 days
ID_MAPPING_CACHE_TTL = 30 * 24 * 3600  # 30 days
EVIDENCE_CACHE_TTL = 24 * 3600  # 24 hours

# API base URLs
KEGG_API_BASE = "https://rest.kegg.jp"
BIGG_API_BASE = "https://bigg.ucsd.edu/api/v2"

# Rate limits (requests per second)
RATE_LIMITS = {
    "kegg": 3.0,
    "bigg": 5.0,
}

# Batch processing
BATCH_SIZE = 10
MAX_CONCURRENT_REQUESTS = 5

# KEGG organism code -> full organism name
KEGG_CODE_TO_NAME: dict[str, str] = {
    "eco": "Escherichia coli",
    "sce": "Saccharomyces cerevisiae",
    "hsa": "Homo sapiens",
    "bsu": "Bacillus subtilis",
    "ppu": "Pseudomonas putida",
    "cgb": "Corynebacterium glutamicum",
    "cgl": "Corynebacterium glutamicum",
}

# Common organism mappings (model ID prefix -> KEGG org code)
# Gap-fill defaults
DEFAULT_UNIVERSAL_MODEL = str(DATA_DIR / "bigg_universal_model_fixed.json")
DEFAULT_TASK_FILE = str(DATA_DIR / "universal_essential_tasks.csv")
GAPFILL_LOWER_BOUND = 0.05
ORGANISM_FILTER_CACHE_TTL = 30 * 24 * 3600  # 30 days

# Version control defaults
VERSION_DIR = CONFIG_DIR / "versions"
MAX_VERSIONS_DEFAULT = 20

ORGANISM_MAP = {
    "iJO1366": "eco",
    "iML1515": "eco",
    "iAF1260": "eco",
    "iMM904": "sce",
    "iND750": "sce",
    "Recon3D": "hsa",
    "Recon2": "hsa",
    "iYO844": "bsu",
    "iJN746": "ppu",
}
