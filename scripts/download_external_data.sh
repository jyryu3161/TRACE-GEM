#!/usr/bin/env bash
# scripts/download_external_data.sh
#
# Download public external reference data not tracked in git.
# Run once after cloning, or whenever you need to refresh the cache.
#
# Files downloaded into <repo>/data/ :
#   - reac_prop.tsv, reac_xref.tsv          (MetaNetX MNXref reaction crossrefs)
#   - bigg_models_metabolites.txt           (BiGG namespace dump)
#   - bigg_models_reactions.txt             (BiGG namespace dump)
#   - universal_model.json                  (BiGG universal SBML in JSON form)
#
# All sources are open public databases. Each download is verified
# against a SHA-256 checksum recorded at the time the project last
# pinned a known-good version of the data.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
mkdir -p "$DATA_DIR"

# ---- helpers ----------------------------------------------------------------

log() { printf '[download] %s\n' "$*"; }
err() { printf '[download][error] %s\n' "$*" >&2; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "missing required command: $1"; exit 1; }
}

require_cmd curl
require_cmd shasum

sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }

check_url() {
  local url="$1"
  local code
  code=$(curl -sIL -o /dev/null -w '%{http_code}' "$url" || true)
  if [[ "$code" != "200" && "$code" != "302" && "$code" != "301" ]]; then
    err "URL not reachable (HTTP $code): $url"
    return 1
  fi
}

download_with_check() {
  local url="$1" out="$2" expected_sha="$3" expected_size="$4"

  if [[ -f "$out" ]]; then
    local actual
    actual=$(sha256_of "$out")
    if [[ "$actual" == "$expected_sha" ]]; then
      log "ok (cached): $(basename "$out")"
      return 0
    fi
    log "checksum mismatch on cached file, re-downloading: $(basename "$out")"
  fi

  log "checking source: $url"
  check_url "$url" || { err "skipping $out due to unreachable source"; return 1; }

  local tmp="${out}.partial"
  log "downloading: $url"
  if ! curl -fL --retry 3 --retry-delay 2 -o "$tmp" "$url"; then
    err "download failed: $url"
    rm -f "$tmp"
    return 1
  fi

  local actual_size actual_sha
  actual_size=$(wc -c < "$tmp" | tr -d ' ')
  actual_sha=$(sha256_of "$tmp")

  if [[ "$actual_size" != "$expected_size" ]]; then
    err "size mismatch for $out: got $actual_size, expected $expected_size"
    rm -f "$tmp"
    return 1
  fi
  if [[ "$actual_sha" != "$expected_sha" ]]; then
    err "checksum mismatch for $out:"
    err "  got      $actual_sha"
    err "  expected $expected_sha"
    err "the upstream may have updated. If intentional, update the expected"
    err "checksum in this script after manual verification."
    rm -f "$tmp"
    return 1
  fi

  mv "$tmp" "$out"
  log "verified: $(basename "$out") ($actual_size bytes)"
}

# ---- MetaNetX (MNXref reaction properties + cross-references) ---------------
# Source:  https://www.metanetx.org/mnxdoc/mnxref.html
# License: CC BY 4.0
# Note:    MetaNetX serves files at versioned URLs. If 4.5 (the version
#          pinned here) is rotated out, update both URL and checksum.

download_with_check \
  "https://www.metanetx.org/cgi-bin/mnxget/mnxref/reac_prop.tsv" \
  "$DATA_DIR/reac_prop.tsv" \
  "8582cc187d03ce127f8e914f8f298282ac9036f1448918117af044ac55b980db" \
  "10274596"

download_with_check \
  "https://www.metanetx.org/cgi-bin/mnxget/mnxref/reac_xref.tsv" \
  "$DATA_DIR/reac_xref.tsv" \
  "2610e2998f582043a4e9d1a8ce42b7a8f4e2480e54d03ded26a7e83fd401f229" \
  "80751943"

# ---- BiGG Models (namespace dumps + universal model) ------------------------
# Source:  http://bigg.ucsd.edu/data_access
# License: BiGG Models Terms of Service (academic use)

download_with_check \
  "http://bigg.ucsd.edu/static/namespace/bigg_models_metabolites.txt" \
  "$DATA_DIR/bigg_models_metabolites.txt" \
  "2b12a1871e8c92cddc06e179795aa33d1377c988a74f029a0a754339888bf725" \
  "7971568"

download_with_check \
  "http://bigg.ucsd.edu/static/namespace/bigg_models_reactions.txt" \
  "$DATA_DIR/bigg_models_reactions.txt" \
  "e1c11add0cb2a1ed3403348eacefd96f1fe487e95a2a03a06eae0edd9a20947d" \
  "10695807"

download_with_check \
  "http://bigg.ucsd.edu/static/namespace/universal_model.json" \
  "$DATA_DIR/universal_model.json" \
  "a9ebc6df7f3161722a3c5980cbcc2970f5d762b4fd995be93e373d77b6a6ea96" \
  "21454113"

log "all external data ready in $DATA_DIR"
