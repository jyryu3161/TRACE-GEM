"""Tests for CSV and JSON export functionality."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict

import pytest

from src.core.models import ReactionEvidence
from src.evidence.evidence_types import get_ordered_sources


class TestCSVExport:
    def _export_csv(self, model, results, filepath):
        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            source_order = get_ordered_sources()
            score_headers = [f"{sc.display_name} Score" for _, sc in source_order]
            writer.writerow(
                [
                    "Reaction ID",
                    "Name",
                    "Subsystem",
                    "Genes",
                    "GPR",
                    "Evidence Tier",
                    "Evidence Rationale",
                    "Legacy Confidence Score",
                    *score_headers,
                    "Substrate Match",
                    "Product Match",
                    "EC Numbers",
                    "KEGG IDs",
                    "Status",
                ]
            )
            for rxn in model.reactions:
                ev = results.get(rxn.id, ReactionEvidence(rxn.id))
                per_source = [
                    f"{getattr(ev, f'{source.value}_score', 0.0):.4f}"
                    for source, _ in source_order
                ]
                writer.writerow(
                    [
                        rxn.id,
                        rxn.name,
                        rxn.subsystem or "",
                        ";".join(rxn.genes),
                        rxn.gene_reaction_rule,
                        ev.evidence_tier.label,
                        ev.evidence_rationale,
                        f"{ev.confidence_score:.4f}",
                        *per_source,
                        f"{ev.substrate_match_ratio:.4f}",
                        f"{ev.product_match_ratio:.4f}",
                        ";".join(ev.ec_numbers),
                        ";".join(ev.kegg_reaction_ids),
                        ev.status.value,
                    ]
                )

    def test_csv_header(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header[0] == "Reaction ID"
        assert header[5] == "Evidence Tier"
        assert header[7] == "Legacy Confidence Score"
        assert header[8:10] == ["KEGG Score", "BiGG Models Score"]
        assert len(header) == 15

    def test_csv_data_rows(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 4
        eno_row = rows[1]
        assert eno_row[0] == "ENO"
        assert eno_row[5] == "High"
        assert float(eno_row[7]) == pytest.approx(1.0, abs=0.01)

    def test_csv_unevaluated_reaction(self, tmp_path, sample_model):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, {}, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        for row in rows[1:]:
            assert row[5] == "Low"
            assert float(row[7]) == 0.0
            assert row[14] == "not_evaluated"

    def test_csv_genes_semicolon_separated(self, tmp_path, sample_model, sample_evidence_map):
        filepath = tmp_path / "test.csv"
        self._export_csv(sample_model, sample_evidence_map, filepath)

        with open(filepath) as f:
            reader = csv.reader(f)
            rows = list(reader)

        pfk_row = rows[2]
        assert ";" in pfk_row[3]


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
                "evidence_tier": ev.evidence_tier.value,
                "evidence_rationale": ev.evidence_rationale,
                "confidence_score": ev.confidence_score,
                "scores": {
                    "kegg": ev.kegg_score,
                    "bigg": ev.bigg_score,
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
        assert eno["evidence_tier"] == "high"
        assert eno["confidence_score"] == pytest.approx(1.0, abs=0.01)
        assert eno["scores"]["kegg"] == 1.0
        assert eno["scores"]["bigg"] == 0.0
        assert eno["verification"]["substrate_match"] == 1.0
        assert eno["verification"]["product_match"] == 1.0
        assert len(eno["evidence_items"]) == 1

    def test_json_unevaluated(self, tmp_path, sample_model):
        filepath = tmp_path / "test.json"
        self._export_json(sample_model, {}, filepath)

        with open(filepath) as f:
            data = json.load(f)

        eno = data["reactions"]["ENO"]
        assert eno["evidence_tier"] == "low"
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
