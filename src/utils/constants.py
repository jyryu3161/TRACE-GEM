"""Constants for the GEM Evaluator."""

from pathlib import Path

APP_NAME = "GEM Evaluator"
APP_VERSION = "0.2.0"

# Default directories
CONFIG_DIR = Path.home() / ".gem_evaluator"
CACHE_DB_PATH = CONFIG_DIR / "cache.db"
CONFIG_FILE_PATH = CONFIG_DIR / "config.json"
LOG_DIR = CONFIG_DIR / "logs"

# Cache TTL (seconds)
API_CACHE_TTL = 7 * 24 * 3600  # 7 days
ID_MAPPING_CACHE_TTL = 30 * 24 * 3600  # 30 days
EVIDENCE_CACHE_TTL = 24 * 3600  # 24 hours

# API base URLs
KEGG_API_BASE = "https://rest.kegg.jp"

# Rate limits (requests per second)
RATE_LIMITS = {
    "kegg": 3.0,
    "gemini": 5.0,
    "perplexity": 2.0,
}

# Scoring weights (3 sources)
SOURCE_WEIGHTS = {
    "kegg": 0.50,
    "gemini": 0.25,
    "perplexity": 0.25,
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
}

# Common organism mappings (model ID prefix -> KEGG org code)
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
