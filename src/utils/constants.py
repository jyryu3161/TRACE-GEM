"""Constants for MetaTaskGapFill."""

from pathlib import Path

APP_NAME = "MetaTaskGapFill"
APP_VERSION = "0.2.0"

# Default directories
CONFIG_DIR = Path.home() / ".metataskgapfill"
CACHE_DB_PATH = CONFIG_DIR / "cache.db"
CONFIG_FILE_PATH = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"

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

# Scoring weights
SOURCE_WEIGHTS = {
    "kegg": 0.70,
    "bigg": 0.30,
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
DEFAULT_UNIVERSAL_MODEL = "data/bigg_universal_model_fixed.json"
DEFAULT_TASK_FILE = "data/universal_essential_tasks.csv"
GAPFILL_LOWER_BOUND = 0.05
GAPFILL_MAX_PENALTY = 1000.0
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
