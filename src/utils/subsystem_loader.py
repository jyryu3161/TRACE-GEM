"""BiGG model JSON loader for reaction subsystem lookup.

SBML files distributed by BiGG (e.g. iML1515.xml) do not contain subsystem
information in any form (no `<notes>`, no SBML L3 `<groups>`, no
`r.subsystem` attribute). The official BiGG JSON model bundle, however,
ships with subsystem populated at 100% coverage. This module downloads
that bundle (or uses a local cache) and exposes a lookup helper that the
SBML loader calls after model conversion.

Network/IO failures are absorbed silently — the lookup returns an empty
map and the caller leaves `Reaction.subsystem` as None. The UI then
displays an empty cell, matching the previous behavior.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.models import Reaction

logger = logging.getLogger("metataskgapfill.subsystem_loader")

_BIGG_MODEL_URL = "http://bigg.ucsd.edu/static/models/{model_id}.json"
_DOWNLOAD_TIMEOUT = 10.0


def download_bigg_model_json(
    model_id: str, dest_dir: Path, timeout: float = _DOWNLOAD_TIMEOUT
) -> Path | None:
    """Download a BiGG model JSON to dest_dir/{model_id}.json.

    Returns the path on success, None on any failure (network, HTTP, IO).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{model_id}.json"
    url = _BIGG_MODEL_URL.format(model_id=model_id)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = resp.read()
        dest_path.write_bytes(payload)
        logger.info("Downloaded BiGG model JSON for %s (%d bytes)", model_id, len(payload))
        return dest_path
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        logger.warning("BiGG model JSON download failed for %s: %s", model_id, e)
        return None


def build_subsystem_map(json_path: Path) -> dict[str, str]:
    """Parse a BiGG JSON and return {reaction_id: subsystem}, case-sensitive."""
    try:
        data = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to parse BiGG JSON %s: %s", json_path, e)
        return {}
    return {
        r["id"]: r["subsystem"]
        for r in data.get("reactions", [])
        if r.get("id") and r.get("subsystem")
    }


def get_subsystem_map(model_id: str, cache_dir: Path) -> dict[str, str]:
    """Return {reaction_id: subsystem} for model_id, using cache or downloading.

    Never raises. Empty dict on any failure — callers should fall back to
    leaving subsystem unfilled.
    """
    if not model_id:
        return {}
    cache_path = cache_dir / f"{model_id}.json"
    if not cache_path.exists() and download_bigg_model_json(model_id, cache_dir) is None:
        return {}
    return build_subsystem_map(cache_path)


def lookup_subsystem(reaction: Reaction, subsystem_map: dict[str, str]) -> str | None:
    """Resolve a reaction's subsystem via 4-step fallback.

    1. annotation['bigg.reaction'] (list[0] or str)
    2. reaction.id (case-sensitive)
    3. reaction.id with 'R_' prefix stripped
    4. None
    """
    ann = reaction.annotation.get("bigg.reaction") if reaction.annotation else None
    if ann:
        bigg_id = ann[0] if isinstance(ann, list) and ann else ann
        if isinstance(bigg_id, str) and bigg_id in subsystem_map:
            return subsystem_map[bigg_id]
    if reaction.id in subsystem_map:
        return subsystem_map[reaction.id]
    if reaction.id.startswith("R_"):
        stripped = reaction.id[2:]
        if stripped in subsystem_map:
            return subsystem_map[stripped]
    return None
