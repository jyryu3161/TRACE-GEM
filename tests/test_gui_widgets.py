"""Tests for GUI widgets — instantiation, data binding, signals."""

from __future__ import annotations

import os
import sys

import pytest

from src.core.models import (
    ReactionEvidence,
)
from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(not GUI_AVAILABLE, reason="PySide6 GUI not available")

# Only create QApplication if GUI is available (avoids SIGABRT)
if GUI_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)


class TestModelOverviewWidget:
    def test_instantiation(self):
        from src.gui.model_overview import ModelOverviewWidget

        widget = ModelOverviewWidget()
        assert widget is not None

    def test_set_model(self, sample_model):
        from src.gui.model_overview import ModelOverviewWidget

        widget = ModelOverviewWidget()
        widget.set_model(sample_model)
        assert widget._model_id.text() == "test_model"
        assert widget._reactions.text() == "3"
        assert widget._genes.text() == "3"

    def test_update_evaluation_count(self):
        from src.gui.model_overview import ModelOverviewWidget

        widget = ModelOverviewWidget()
        widget.update_evaluation_count(5, 10)
        assert widget._evaluated.text() == "5 / 10"


class TestReactionDetailWidget:
    def test_instantiation(self):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        assert widget is not None
        assert widget._eval_btn.isEnabled() is False

    def test_set_reaction(self, sample_reaction):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        widget.set_reaction(sample_reaction)
        assert widget._id_label.text() == "ENO"
        assert widget._name_edit.text() == "enolase"
        assert widget._eval_btn.isEnabled() is True

    def test_clear(self, sample_reaction):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        widget.set_reaction(sample_reaction)
        widget.clear()
        assert widget._id_label.text() == "-"
        assert widget._eval_btn.isEnabled() is False

    def test_update_evidence(self):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        ev = ReactionEvidence(reaction_id="ENO")
        ev.ec_numbers = ["4.2.1.11"]
        ev.kegg_reaction_ids = ["R00658"]
        ev.substrate_match_ratio = 1.0
        ev.product_match_ratio = 1.0
        ev.directionality_match = True
        widget.update_evidence(ev)
        # Should contain the EC number in the xref browser
        html = widget._xref_browser.toHtml()
        assert "4.2.1.11" in html

    def test_evaluate_signal(self, sample_reaction):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        widget.set_reaction(sample_reaction)

        received = []
        widget.evaluate_requested.connect(lambda rid: received.append(rid))
        widget._on_evaluate_clicked()
        assert received == ["ENO"]


class TestEvidencePanelWidget:
    def test_instantiation(self):
        from src.gui.evidence_panel import EvidencePanelWidget

        widget = EvidencePanelWidget()
        assert widget is not None

    def test_set_evidence(self, sample_evidence):
        from src.gui.evidence_panel import EvidencePanelWidget

        widget = EvidencePanelWidget()
        sample_evidence.confidence_score = 1.0
        widget.set_evidence(sample_evidence)
        assert "1.000" in widget._score_label.text()

    def test_clear(self):
        from src.gui.evidence_panel import EvidencePanelWidget

        widget = EvidencePanelWidget()
        widget.clear()
        assert widget._score_label.text() == "-"


class TestGenePanelWidget:
    def test_instantiation(self):
        from src.gui.gene_panel import GenePanelWidget

        widget = GenePanelWidget()
        assert widget is not None

    def test_set_model_and_reaction(self, sample_model, sample_reaction):
        from src.gui.gene_panel import GenePanelWidget

        widget = GenePanelWidget()
        widget.set_model(sample_model)
        widget.set_reaction(sample_reaction)
        assert widget._gene_list.count() == 1  # b2779

    def test_clear(self, sample_model, sample_reaction):
        from src.gui.gene_panel import GenePanelWidget

        widget = GenePanelWidget()
        widget.set_model(sample_model)
        widget.set_reaction(sample_reaction)
        widget.clear()
        assert widget._gene_list.count() == 0


class TestMetabolitePanelWidget:
    def test_instantiation(self):
        from src.gui.metabolite_panel import MetabolitePanelWidget

        widget = MetabolitePanelWidget()
        assert widget is not None

    def test_set_model_and_reaction(self, sample_model, sample_reaction):
        from src.gui.metabolite_panel import MetabolitePanelWidget

        widget = MetabolitePanelWidget()
        widget.set_model(sample_model)
        widget.set_reaction(sample_reaction)
        assert widget._reactant_list.count() == 1  # 2pg_c
        assert widget._product_list.count() == 2  # pep_c, h2o_c

    def test_clear(self):
        from src.gui.metabolite_panel import MetabolitePanelWidget

        widget = MetabolitePanelWidget()
        widget.clear()
        assert widget._reactant_list.count() == 0
        assert widget._product_list.count() == 0


class TestProgressDialog:
    def test_instantiation(self):
        from src.gui.progress_dialog import ProgressDialog

        dialog = ProgressDialog("Test Progress")
        assert dialog is not None
        assert dialog.windowTitle() == "Test Progress"

    def test_update_progress(self):
        from src.gui.progress_dialog import ProgressDialog

        dialog = ProgressDialog()
        dialog.update_progress(5, 10, "RXN5")
        assert dialog._progress_bar.value() == 50
        assert "5 / 10" in dialog._status_label.text()

    def test_set_complete(self):
        from src.gui.progress_dialog import ProgressDialog

        dialog = ProgressDialog()
        dialog.set_complete()
        assert dialog._progress_bar.value() == 100
        assert "complete" in dialog._status_label.text().lower()


class TestSettingsDialog:
    def test_instantiation(self):
        from src.gui.settings_dialog import SettingsDialog
        from src.utils.config import Config

        config = Config()
        dialog = SettingsDialog(config)
        assert dialog is not None

    def test_loads_config_values(self):
        from src.gui.settings_dialog import SettingsDialog
        from src.utils.config import Config

        config = Config(kegg_organism_code="sce", batch_size=20)
        dialog = SettingsDialog(config)
        assert dialog._kegg_code.text() == "sce"
        assert dialog._batch_size.value() == 20


class TestScoreVisualizationWidget:
    def test_instantiation(self):
        from src.gui.score_visualization import ScoreVisualizationWidget

        widget = ScoreVisualizationWidget()
        assert widget is not None
