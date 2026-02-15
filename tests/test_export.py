"""Tests for CSV and JSON export functionality."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict

import pytest

from src.core.models import (
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    ReactionEvidence,
)


class TestCSVExport:
    def _export_csv(self, model, results, filepath):
        """Replicate the CSV export logic from main_window.py."""
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Reaction ID",
                    "Name",
                    "Subsystem",
                    "Genes",
                    "GPR",
                    "Confidence Score",
                    "KEGG Score",
                    "Gemini Score",
                    "Perplexity Score",
                    "Substrate Match",
                    "Product Match",
                    "EC Numbers",
                    "KEGG IDs",
                    "Status",
                    "Gemini Analysis",
                    "Perplexity Analysis",
                ]
            )
            for rxn in model.reactions:
                ev = results.get(rxn.id, ReactionEvidence(rxn.id))
                gemini_desc = ""
                pplx_desc = ""
                for item in ev.items:
                    if item.source == EvidenceSource.GEMINI:
                        gemini_desc = item.description
                    elif item.source == EvidenceSource.PERPLEXITY:
                        pplx_desc = item.description
                writer.writerow(
                    [
                        rxn.id,
                        rxn.name,
                        rxn.subsystem or "",
                        ";".join(rxn.genes),
                        rxn.gene_reaction_rule,
                        f"{ev.confidence_score:.4f}",
                        f"{ev.kegg_score:.4f}",
                        f"{ev.gemini_score:.4f}",
                        f"{ev.perplexity_score:.4f}",
                        f"{ev.substrate_match_ratio:.4f}",
                        f"{ev.product_match_ratio:.4f}",
                        ";".join(ev.ec_numbers),
                        ";".join(ev.kegg_reaction_ids),
                        ev.status.value,
                        gemini_desc,
                        pplx_desc,
                    ]
                )

    def test_csv_header(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header[0] == "Reaction ID"
        assert header[5] == "Confidence Score"
        assert header[14] == "Gemini Analysis"
        assert header[15] == "Perplexity Analysis"
        assert len(header) == 16

    def test_csv_data_rows(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 4  # header + 3 reactions
        # First data row should be ENO
        eno_row = rows[1]
        assert eno_row[0] == "ENO"
        assert float(eno_row[5]) == pytest.approx(1.0, abs=0.01)

    def test_csv_unevaluated_reaction(self, tmp_path, sample_model):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, {}, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        # All should have 0.0 score and not_evaluated status
        for row in rows[1:]:
            assert float(row[5]) == 0.0
            assert row[13] == "not_evaluated"

    def test_csv_genes_semicolon_separated(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        pfk_row = rows[2]  # PFK has 2 genes
        assert ";" in pfk_row[3]

    def test_csv_llm_analysis_columns(self, tmp_path, sample_model):
        """CSV should include Gemini and Perplexity analysis text."""
        ev_eno = ReactionEvidence(reaction_id="ENO")
        ev_eno.items = [
            EvidenceItem(
                source=EvidenceSource.GEMINI,
                strength=EvidenceStrength.STRONG,
                description="Gemini says this reaction is valid.",
            ),
            EvidenceItem(
                source=EvidenceSource.PERPLEXITY,
                strength=EvidenceStrength.MODERATE,
                description="Perplexity confirms in E. coli.",
            ),
        ]
        results = {"ENO": ev_eno}

        filepath = tmp_path / "test_llm.csv"
        self._export_csv(sample_model, results, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        eno_row = rows[1]
        assert eno_row[14] == "Gemini says this reaction is valid."
        assert eno_row[15] == "Perplexity confirms in E. coli."


class TestJSONExport:
    @staticmethod
    def _serialize_raw_data(raw_data):
        if raw_data is None:
            return None
        result = {}
        for k, v in raw_data.items():
            if hasattr(v, "__dataclass_fields__"):
                result[k] = asdict(v)
            else:
                result[k] = v
        return result

    def _export_json(self, model, results, filepath):
        """Replicate the JSON export logic from main_window.py."""
        export = {
            "model_id": model.id,
            "organism": model.organism,
            "total_reactions": model.reaction_count,
            "reactions": {},
        }
        for rxn in model.reactions:
            ev = results.get(rxn.id, ReactionEvidence(rxn.id))
            export["reactions"][rxn.id] = {
                "name": rxn.name,
                "subsystem": rxn.subsystem,
                "equation": rxn.equation,
                "genes": rxn.genes,
                "confidence_score": ev.confidence_score,
                "scores": {
                    "kegg": ev.kegg_score,
                    "gemini": ev.gemini_score,
                    "perplexity": ev.perplexity_score,
                },
                "verification": {
                    "substrate_match": ev.substrate_match_ratio,
                    "product_match": ev.product_match_ratio,
                },
                "ec_numbers": ev.ec_numbers,
                "kegg_reaction_ids": ev.kegg_reaction_ids,
                "evidence_items": [
                    {
                        "source": item.source.value,
                        "strength": item.strength.name,
                        "description": item.description,
                        "url": item.url,
                        "raw_data": self._serialize_raw_data(item.raw_data),
                    }
                    for item in ev.items
                ],
                "status": ev.status.value,
            }

        with open(filepath, "w") as f:
            json.dump(export, f, indent=2)

    def test_json_structure(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.json"
        self._export_json(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            data = json.load(f)

        assert data["model_id"] == "test_model"
        assert data["organism"] == "Escherichia coli"
        assert data["total_reactions"] == 3
        assert "ENO" in data["reactions"]

    def test_json_reaction_data(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.json"
        self._export_json(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            data = json.load(f)

        eno = data["reactions"]["ENO"]
        assert eno["name"] == "enolase"
        assert eno["confidence_score"] == pytest.approx(1.0, abs=0.01)
        assert eno["scores"]["kegg"] == 1.0
        assert eno["scores"]["gemini"] == 0.0
        assert eno["scores"]["perplexity"] == 0.0
        assert eno["verification"]["substrate_match"] == 1.0
        assert eno["verification"]["product_match"] == 1.0
        assert len(eno["evidence_items"]) == 1

    def test_json_unevaluated(self, tmp_path, sample_model):
        filepath = tmp_path / "test.json"
        self._export_json(sample_model, {}, filepath)

        with open(filepath) as f:
            data = json.load(f)

        eno = data["reactions"]["ENO"]
        assert eno["confidence_score"] == 0.0
        assert eno["status"] == "not_evaluated"

    def test_json_evidence_items(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.json"
        self._export_json(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            data = json.load(f)

        items = data["reactions"]["ENO"]["evidence_items"]
        assert len(items) == 1
        assert items[0]["source"] == "kegg"
        assert items[0]["strength"] == "STRONG"
        assert "R00658" in items[0]["description"]

    def test_json_evidence_items_include_raw_data(self, tmp_path, sample_model):
        """JSON export should include raw_data in evidence items."""
        ev_eno = ReactionEvidence(reaction_id="ENO")
        ev_eno.items = [
            EvidenceItem(
                source=EvidenceSource.KEGG,
                strength=EvidenceStrength.STRONG,
                description="KEGG reaction R00658",
                raw_data={
                    "kegg_id": "R00658",
                    "substrate_match": 1.0,
                    "model_substrates": ["C00631"],
                },
            ),
        ]
        results = {"ENO": ev_eno}

        filepath = tmp_path / "test_raw.json"
        self._export_json(sample_model, results, filepath)

        with open(filepath) as f:
            data = json.load(f)

        item = data["reactions"]["ENO"]["evidence_items"][0]
        assert item["raw_data"] is not None
        assert item["raw_data"]["kegg_id"] == "R00658"
        assert item["raw_data"]["substrate_match"] == 1.0
        assert item["raw_data"]["model_substrates"] == ["C00631"]

    def test_json_is_valid(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.json"
        self._export_json(sample_model, sample_evidence_map, filepath)

        # Should be valid JSON
        with open(filepath) as f:
            data = json.load(f)  # should not raise
        assert isinstance(data, dict)
