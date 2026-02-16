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
BIGG_API_BASE = "http://bigg.ucsd.edu/api/v2"
UNIPROT_API_BASE = "https://rest.uniprot.org"
PUBMED_API_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
METACYC_API_BASE = "https://websvc.biocyc.org"

# Rate limits (requests per second)
RATE_LIMITS = {
    "kegg": 3.0,
    "bigg": 5.0,
    "uniprot": 3.0,
    "pubmed_no_key": 3.0,
    "pubmed_with_key": 10.0,
    "metacyc": 1.0,
    "gemini": 5.0,
    "perplexity": 2.0,
}

# Scoring weights (7 sources — Option A)
SOURCE_WEIGHTS = {
    "kegg": 0.30,
    "bigg": 0.15,
    "uniprot": 0.15,
    "pubmed": 0.10,
    "metacyc": 0.10,
    "gemini": 0.10,
    "perplexity": 0.10,
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
