"""Tests for reaction table model, proxy filter, and delegates."""

from __future__ import annotations

import os
import sys

import pytest

from src.core.models import (
    EvaluationStatus,
    EvidenceTier,
    ReactionEvidence,
)
from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(not GUI_AVAILABLE, reason="PySide6 GUI not available")

# Only create QApplication if GUI is available (avoids SIGABRT)
if GUI_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QModelIndex, Qt
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)


class TestReactionTableModel:
    def test_instantiation(self):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 8

    def test_set_reactions(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)
        assert model.rowCount() == 3

    def test_column_headers(self):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        expected = ["ID", "Name", "Equation", "Subsystem", "Genes", "GPR", "Evidence", "Status"]
        for i, name in enumerate(expected):
            header = model.headerData(i, Qt.Orientation.Horizontal)
            assert header == name

    def test_data_display_role(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)

        # ID column
        idx = model.index(0, ReactionTableModel.COL_ID)
        assert model.data(idx) == "ENO"

        # Name column
        idx = model.index(0, ReactionTableModel.COL_NAME)
        assert model.data(idx) == "enolase"

        # Subsystem column
        idx = model.index(0, ReactionTableModel.COL_SUBSYSTEM)
        assert model.data(idx) == "Glycolysis/Gluconeogenesis"

        # Genes column (count)
        idx = model.index(0, ReactionTableModel.COL_GENES)
        assert model.data(idx) == "1"

    def test_data_score_unevaluated(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)

        idx = model.index(0, ReactionTableModel.COL_SCORE)
        assert model.data(idx) == ""

    def test_data_score_evaluated(self, sample_model, sample_evidence_map):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)
        model.update_all_evidence(sample_evidence_map)

        idx = model.index(0, ReactionTableModel.COL_SCORE)
        tier_text = model.data(idx)
        assert tier_text == "High"

    def test_data_user_role_score(self, sample_model, sample_evidence_map):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)
        model.update_all_evidence(sample_evidence_map)

        idx = model.index(0, ReactionTableModel.COL_SCORE)
        tier_rank = model.data(idx, Qt.ItemDataRole.UserRole)
        assert tier_rank == EvidenceTier.HIGH.rank

    def test_data_tooltip_role(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)

        idx = model.index(0, ReactionTableModel.COL_GPR)
        tooltip = model.data(idx, Qt.ItemDataRole.ToolTipRole)
        assert tooltip == "b2779"

    def test_get_reaction(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)

        rxn = model.get_reaction(0)
        assert rxn.id == "ENO"

    def test_get_reaction_out_of_range(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)

        assert model.get_reaction(99) is None
        assert model.get_reaction(-1) is None

    def test_update_single_evidence(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)

        ev = ReactionEvidence(reaction_id="ENO")
        ev.confidence_score = 0.75
        ev.evidence_tier = EvidenceTier.HIGH
        ev.status = EvaluationStatus.EVALUATED
        model.update_evidence("ENO", ev)

        idx = model.index(0, ReactionTableModel.COL_SCORE)
        assert model.data(idx) == "High"

    def test_sort_by_id(self, sample_model):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        model.set_reactions(sample_model.reactions)
        model.sort(ReactionTableModel.COL_ID, Qt.SortOrder.AscendingOrder)
        assert model.get_reaction(0).id == "ENO"

    def test_invalid_index(self):
        from src.gui.reaction_table import ReactionTableModel

        model = ReactionTableModel()
        idx = QModelIndex()
        assert model.data(idx) is None


class TestReactionFilterProxy:
    def test_instantiation(self):
        from src.gui.reaction_table import ReactionFilterProxy, ReactionTableModel

        source = ReactionTableModel()
        proxy = ReactionFilterProxy()
        proxy.setSourceModel(source)
        assert proxy.rowCount() == 0

    def test_text_filter(self, sample_model):
        from src.gui.reaction_table import ReactionFilterProxy, ReactionTableModel

        source = ReactionTableModel()
        source.set_reactions(sample_model.reactions)

        proxy = ReactionFilterProxy()
        proxy.setSourceModel(source)

        assert proxy.rowCount() == 3
        proxy.set_text_filter("enolase")
        assert proxy.rowCount() == 1

    def test_subsystem_filter(self, sample_model):
        from src.gui.reaction_table import ReactionFilterProxy, ReactionTableModel

        source = ReactionTableModel()
        source.set_reactions(sample_model.reactions)

        proxy = ReactionFilterProxy()
        proxy.setSourceModel(source)

        proxy.set_subsystem_filter("Exchange")
        assert proxy.rowCount() == 1

    def test_clear_filter(self, sample_model):
        from src.gui.reaction_table import ReactionFilterProxy, ReactionTableModel

        source = ReactionTableModel()
        source.set_reactions(sample_model.reactions)

        proxy = ReactionFilterProxy()
        proxy.setSourceModel(source)

        proxy.set_text_filter("enolase")
        assert proxy.rowCount() == 1
        proxy.set_text_filter("")
        assert proxy.rowCount() == 3


class TestReactionTableWidget:
    def test_instantiation(self):
        from src.gui.reaction_table import ReactionTableWidget

        widget = ReactionTableWidget()
        assert widget is not None

    def test_set_model_data(self, sample_model):
        from src.gui.reaction_table import ReactionTableWidget

        widget = ReactionTableWidget()
        widget.set_model_data(sample_model)
        # Subsystem combo should have "All Subsystems" + actual subsystems
        assert widget._subsystem_combo.count() >= 2


class TestDelegates:
    def test_score_bar_delegate_instantiation(self):
        from src.gui.delegates import ScoreBarDelegate

        delegate = ScoreBarDelegate()
        assert delegate is not None

    def test_status_delegate_instantiation(self):
        from src.gui.delegates import StatusDelegate

        delegate = StatusDelegate()
        assert delegate is not None

    def test_status_delegate_colors(self):
        from src.gui.delegates import StatusDelegate

        assert "not_evaluated" in StatusDelegate.STATUS_COLORS
        assert "evaluated" in StatusDelegate.STATUS_COLORS
        assert "error" in StatusDelegate.STATUS_COLORS

    def test_status_delegate_labels(self):
        from src.gui.delegates import StatusDelegate

        assert StatusDelegate.STATUS_LABELS["evaluated"] == "Done"
        assert StatusDelegate.STATUS_LABELS["error"] == "Error"

    def test_score_color(self):
        from src.gui.theme import score_color

        assert score_color(0.8) == "#27ae60"
        assert score_color(0.5) == "#f39c12"
        assert score_color(0.2) == "#e74c3c"
        assert score_color(0.0) == "#bdc3c7"
