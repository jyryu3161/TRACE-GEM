"""Export controller — manages file export operations."""

from __future__ import annotations

import csv
import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.core.models import EvidenceSource, ReactionEvidence

if TYPE_CHECKING:
    from src.gui.main_window import MainWindow

logger = logging.getLogger("metataskgapfill.gui.export")


class ExportController:
    """Manages file export operations."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def export_csv(self) -> None:
        if not self._w._engine or not self._w._model:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export CSV",
            f"{self._w._model.id}_evidence.csv",
            "CSV Files (*.csv)",
        )
        if not filepath:
            return

        results = self._w._engine.get_all_results()

        from src.evidence.evidence_types import get_ordered_sources

        source_order = get_ordered_sources()
        score_headers = [f"{sc.display_name} Score" for _, sc in source_order]

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
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
            for rxn in self._w._model.reactions:
                ev = results.get(rxn.id, ReactionEvidence(rxn.id))
                per_source = []
                for source, _ in source_order:
                    attr = f"{source.value}_score"
                    per_source.append(f"{getattr(ev, attr, 0.0):.4f}")

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

        self._w._statusbar.showMessage(f"Exported to {filepath}")

    def export_json(self) -> None:
        if not self._w._engine or not self._w._model:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export JSON",
            f"{self._w._model.id}_evidence.json",
            "JSON Files (*.json)",
        )
        if not filepath:
            return

        results = self._w._engine.get_all_results()
        reactions_dict: dict[str, dict] = {}
        export: dict[str, object] = {
            "model_id": self._w._model.id,
            "organism": self._w._model.organism,
            "total_reactions": self._w._model.reaction_count,
            "reactions": reactions_dict,
        }
        for rxn in self._w._model.reactions:
            ev = results.get(rxn.id, ReactionEvidence(rxn.id))
            reactions_dict[rxn.id] = {
                "name": rxn.name,
                "subsystem": rxn.subsystem,
                "equation": rxn.equation,
                "genes": rxn.genes,
                "evidence_tier": ev.evidence_tier.value,
                "evidence_rationale": ev.evidence_rationale,
                "confidence_score": ev.confidence_score,
                "scores": {
                    source.value: getattr(ev, f"{source.value}_score", 0.0)
                    for source in EvidenceSource
                },
                "verification": {
                    "substrate_match_ratio": ev.substrate_match_ratio,
                    "product_match_ratio": ev.product_match_ratio,
                },
                "ec_numbers": ev.ec_numbers,
                "kegg_reaction_ids": ev.kegg_reaction_ids,
                "evidence_items": [
                    {
                        "source": item.source.value,
                        "strength": item.strength.name,
                        "description": item.description,
                        "url": item.url,
                        "raw_data": self.serialize_raw_data(item.raw_data),
                    }
                    for item in ev.items
                ],
                "status": ev.status.value,
            }

        with open(filepath, "w") as f:
            json.dump(export, f, indent=2)

        self._w._statusbar.showMessage(f"Exported to {filepath}")

    def export_sbml(self) -> None:
        if not self._w._model or not self._w._model.cobra_model:
            QMessageBox.warning(self._w, "No Model", "No SBML model loaded.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export SBML",
            f"{self._w._model.id}_modified.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return
        import cobra

        cobra.io.write_sbml_model(self._w._model.cobra_model, filepath)
        self._w._statusbar.showMessage(f"SBML exported to {filepath}")

    def export_improved_sbml(self) -> None:
        """Export the improved model after gap-filling."""
        if not self._w._model or not self._w._model.cobra_model:
            QMessageBox.warning(self._w, "No Model", "No model available for export.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export Improved SBML",
            f"{self._w._model.id}_improved.xml",
            "SBML Files (*.xml);;All Files (*)",
        )
        if not filepath:
            return

        import cobra

        cobra.io.write_sbml_model(self._w._model.cobra_model, filepath)
        self._w._statusbar.showMessage(f"Improved SBML exported to {filepath}")

    def export_gapfill_report(self) -> None:
        """Export gap-fill report as CSV."""
        if not self._w._model:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self._w,
            "Export Gap-Fill Report",
            f"{self._w._model.id}_gapfill_report.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Reaction ID", "Name", "Penalty", "GPR", "Selected"])

        self._w._statusbar.showMessage(f"Report exported to {filepath}")

    @staticmethod
    def serialize_raw_data(raw_data: dict | None) -> dict | None:
        """Make raw_data JSON-serializable by converting non-serializable objects."""
        if raw_data is None:
            return None
        result = {}
        for k, v in raw_data.items():
            if hasattr(v, "__dataclass_fields__"):
                from dataclasses import asdict

                result[k] = asdict(v)
            else:
                result[k] = v
        return result
