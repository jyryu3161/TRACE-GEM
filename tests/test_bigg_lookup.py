"""Tests for local BiGG lookup fallbacks."""

from __future__ import annotations

import json

import pytest

from src.api.bigg_lookup import BiGGLookup
from src.core.models import EvidenceSource, EvidenceStrength, Reaction


class TestBiGGLookup:
    @pytest.mark.asyncio
    async def test_universal_json_fallback_when_flat_files_missing(self, tmp_path) -> None:
        data = {
            "reactions": [
                {
                    "id": "ENO",
                    "name": "Enolase",
                    "metabolites": {"2pg_c": -1.0, "h2o_c": 1.0, "pep_c": 1.0},
                    "notes": {"original_bigg_ids": ["ENO_OLD"]},
                    "annotation": {"KEGG Reaction": ["R00658"]},
                }
            ]
        }
        (tmp_path / "bigg_universal_model_fixed.json").write_text(
            json.dumps(data),
            encoding="utf-8",
        )

        lookup = BiGGLookup(data_dir=tmp_path)
        item = (await lookup.check_evidence(
            Reaction(id="ENO", name="Enolase", equation="2pg <=> pep + h2o")
        ))[0]

        assert item.source == EvidenceSource.BIGG
        assert item.strength == EvidenceStrength.WEAK
        assert item.raw_data["matched_bigg_id"] == "ENO"

        alias_item = (await lookup.check_evidence(
            Reaction(id="ENO_OLD", name="Enolase", equation="2pg <=> pep + h2o")
        ))[0]
        assert alias_item.strength == EvidenceStrength.WEAK
        assert alias_item.raw_data["matched_bigg_id"] == "ENO"
