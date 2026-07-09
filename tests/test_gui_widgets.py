"""Tests for GUI widgets — instantiation, data binding, signals."""

from __future__ import annotations

import os
import sys

import pytest

from src.core.models import (
    ModelVersion,
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


class TestReactionDetailWidget:
    def test_instantiation(self):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        assert widget is not None

    def test_set_reaction(self, sample_reaction):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        widget.set_reaction(sample_reaction)
        assert widget._id_label.text() == "ENO"
        assert widget._name_edit.text() == "enolase"
        # equation_id display should show the ID-based equation
        assert "2pg_c" in widget._equation_id_display.toPlainText()
        # equation (Name) display should show name-based equation
        assert "D-Glycerate" in widget._equation_edit.toPlainText()

    def test_clear(self, sample_reaction):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        widget.set_reaction(sample_reaction)
        widget.clear()
        assert widget._id_label.text() == "-"

    def test_update_evidence(self):
        from src.gui.reaction_detail import ReactionDetailWidget

        widget = ReactionDetailWidget()
        ev = ReactionEvidence(reaction_id="ENO")
        ev.ec_numbers = ["4.2.1.11"]
        ev.kegg_reaction_ids = ["R00658"]
        ev.substrate_match_ratio = 1.0
        ev.product_match_ratio = 1.0
        widget.update_evidence(ev)
        # Should contain the EC number in the xref browser
        html = widget._xref_browser.toHtml()
        assert "4.2.1.11" in html


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
        assert widget._score_label.text() == "High"

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


class TestReactionRemovalDialog:
    def test_dialog_creation(self, sample_reaction, sample_model):
        from src.core.models import MetabolicTask, TaskResult
        from src.gui.reaction_removal_dialog import ReactionRemovalDialog

        task = MetabolicTask(
            task_id="T1", task_type="Reaction", target_id="ENO",
        )
        current_result = TaskResult(task=task, passed=True, actual_value=1.0)
        # Without cobra_model, we test instantiation only (no simulation)
        dialog = ReactionRemovalDialog(
            reaction=sample_reaction,
            cobra_model=None,
            tasks=[task],
            current_results=[current_result],
        )
        assert dialog is not None
        assert dialog.windowTitle() == f"Remove Reaction: {sample_reaction.id}"

    def test_remove_button_disabled_initially(self, sample_reaction):
        from src.core.models import MetabolicTask, TaskResult
        from src.gui.reaction_removal_dialog import ReactionRemovalDialog

        task = MetabolicTask(
            task_id="T1", task_type="Reaction", target_id="ENO",
        )
        current_result = TaskResult(task=task, passed=True, actual_value=1.0)
        dialog = ReactionRemovalDialog(
            reaction=sample_reaction,
            cobra_model=None,
            tasks=[task],
            current_results=[current_result],
        )
        assert dialog._remove_btn.isEnabled() is False


class TestMainWindowProjectState:
    def test_dirty_flag_initial(self):
        from src.gui.main_window import MainWindow
        from src.utils.config import Config

        config = Config()
        window = MainWindow(config)
        assert window._project_dirty is False
        assert window._project_path is None
        window.close()


class TestVersionPanelWidget:
    def _make_versions(self):
        from src.core.models import ModelDiff, ModelVersion

        return [
            ModelVersion(
                version_id="v001",
                timestamp="2026-02-21T09:30:00Z",
                model_id="test",
                change_type="initial_load",
                description="Initial model load with 100 reactions",
                diff=ModelDiff(
                    reactions_added=["R1", "R2", "R3"],
                    genes_added=["g1", "g2"],
                ),
                task_pass_rate="35/52",
            ),
            ModelVersion(
                version_id="v002",
                timestamp="2026-02-21T10:15:00Z",
                parent_version_id="v001",
                model_id="test",
                change_type="gap_fill",
                description="Gap-fill: 2 reactions added",
                diff=ModelDiff(
                    reactions_added=["R4", "R5"],
                    genes_added=["g3"],
                ),
                task_pass_rate="48/52",
            ),
            ModelVersion(
                version_id="v003",
                timestamp="2026-02-21T10:30:00Z",
                parent_version_id="v002",
                model_id="test",
                change_type="manual_edit",
                description="Manual edit: PFK bounds adjusted",
                diff=ModelDiff(
                    reactions_modified=[],
                ),
                task_pass_rate="48/52",
            ),
        ]

    def test_instantiation(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        assert widget is not None

    def test_set_history(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = self._make_versions()
        widget.set_history(versions, current_version_id="v003")

        # Should have 3 items (newest first)
        assert widget._tree.topLevelItemCount() == 3
        first_item = widget._tree.topLevelItem(0)
        vid = first_item.data(0, 256)  # Qt.UserRole = 256
        assert vid == "v003"

    def test_current_version_highlighted(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = self._make_versions()
        widget.set_history(versions, current_version_id="v003")

        first_item = widget._tree.topLevelItem(0)
        # Current version should have star prefix
        assert "\u2605" in first_item.text(0)

    def test_clear(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = self._make_versions()
        widget.set_history(versions)
        widget.clear()
        assert widget._tree.topLevelItemCount() == 0

    def test_filter_by_type(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = self._make_versions()
        widget.set_history(versions, current_version_id="v003")

        # Filter to gap_fill only
        for i in range(widget._type_filter.count()):
            if widget._type_filter.itemData(i) == "gap_fill":
                widget._type_filter.setCurrentIndex(i)
                break

        assert widget._tree.topLevelItemCount() == 1
        item = widget._tree.topLevelItem(0)
        assert item.data(0, 256) == "v002"

    def test_changes_column_shows_diff(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = self._make_versions()
        widget.set_history(versions, current_version_id="v003")

        # v002 item (index 1, newest first) should show "+2 rxn"
        v002_item = widget._tree.topLevelItem(1)
        changes_text = v002_item.text(3)  # COL_CHANGES = 3
        assert "+2 rxn" in changes_text

    def test_signals_exist(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        # Verify all expected signals exist
        assert hasattr(widget, "restore_requested")
        assert hasattr(widget, "compare_requested")
        assert hasattr(widget, "export_requested")
        assert hasattr(widget, "detail_requested")

    def test_splitter_exists(self):
        from PySide6.QtWidgets import QSplitter

        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        assert hasattr(widget, "_splitter")
        assert isinstance(widget._splitter, QSplitter)
        assert widget._splitter.count() == 2  # tree + graph

    def test_toggle_graph(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        widget.show()

        # Initially visible (checked=True)
        assert widget._graph_btn.isChecked()

        # Toggle off
        widget._graph_btn.setChecked(False)
        widget._toggle_graph()
        assert not widget._graph.isVisible()
        assert "\u25bc" in widget._graph_btn.text()

        # Toggle on
        widget._graph_btn.setChecked(True)
        widget._toggle_graph()
        assert widget._graph.isVisible()
        assert "\u25b2" in widget._graph_btn.text()

        widget.hide()

    def test_table_graph_sync(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = self._make_versions()
        widget.set_history(versions, current_version_id="v003")

        # Graph should have positions for all 3 versions
        assert len(widget._graph._positions) == 3

    def test_legacy_restore_type_display(self):
        from src.gui.version_panel import VersionPanelWidget

        widget = VersionPanelWidget()
        versions = [
            ModelVersion("v001", "2026-06-08T00:00:00+00:00", None),
            ModelVersion("v002", "2026-06-08T00:01:00+00:00", "v001"),
            ModelVersion("v003", "2026-06-08T00:02:00+00:00", "v002"),
            ModelVersion(
                "v004",
                "2026-06-08T00:03:00+00:00",
                "v003",
                description="Restored to version v001",
            ),
        ]
        widget.set_history(versions, current_version_id="v004")

        item = widget._tree.topLevelItem(0)
        assert item is not None
        assert item.text(0).strip().endswith("v004")
        assert item.text(2) == "Restore"

        restore_index = widget._type_filter.findData("restore")
        widget._type_filter.setCurrentIndex(restore_index)
        assert widget._tree.topLevelItemCount() == 1
        assert widget._tree.topLevelItem(0).text(0).strip().endswith("v004")


class TestVersionGraphWidget:
    def _make_versions(self):
        from src.core.models import ModelDiff, ModelVersion

        return [
            ModelVersion(
                version_id="v001",
                timestamp="2026-02-21T09:30:00Z",
                model_id="test",
                change_type="initial_load",
                description="Initial load",
            ),
            ModelVersion(
                version_id="v002",
                timestamp="2026-02-21T10:00:00Z",
                parent_version_id="v001",
                model_id="test",
                change_type="gap_fill",
                description="Gap-fill",
                diff=ModelDiff(reactions_added=["R1"]),
            ),
            ModelVersion(
                version_id="v003",
                timestamp="2026-02-21T10:30:00Z",
                parent_version_id="v002",
                model_id="test",
                change_type="manual_edit",
                description="Edit",
            ),
        ]

    def test_graph_instantiation(self):
        from src.gui.version_graph import VersionGraphWidget

        widget = VersionGraphWidget()
        assert widget is not None

    def test_graph_set_versions(self):
        from src.gui.version_graph import VersionGraphWidget

        widget = VersionGraphWidget()
        versions = self._make_versions()
        widget.set_versions(versions, current_version_id="v003")

        assert len(widget._positions) == 3
        assert "v001" in widget._positions
        assert "v003" in widget._positions

    def test_restore_source_creates_branch_lane(self):
        from src.gui.version_graph import VersionGraphWidget

        versions = [
            ModelVersion("v001", "2026-06-08T00:00:00+00:00", None),
            ModelVersion("v002", "2026-06-08T00:01:00+00:00", "v001"),
            ModelVersion("v003", "2026-06-08T00:02:00+00:00", "v002"),
            ModelVersion("v004", "2026-06-08T00:03:00+00:00", "v003"),
            ModelVersion("v005", "2026-06-08T00:04:00+00:00", "v004"),
            ModelVersion(
                "v006",
                "2026-06-08T00:05:00+00:00",
                "v005",
                change_type="restore",
                description="Restored to version v003",
                restore_source_version_id="v003",
            ),
            ModelVersion("v007", "2026-06-08T00:06:00+00:00", "v006"),
        ]

        widget = VersionGraphWidget()
        widget.set_versions(versions, current_version_id="v007")

        assert widget._positions["v006"][1] != widget._positions["v005"][1]
        assert widget._positions["v007"][1] == widget._positions["v006"][1]

    def test_legacy_restore_description_creates_branch_lane(self):
        from src.gui.version_graph import VersionGraphWidget

        versions = [
            ModelVersion("v001", "2026-06-08T00:00:00+00:00", None),
            ModelVersion("v002", "2026-06-08T00:01:00+00:00", "v001"),
            ModelVersion("v003", "2026-06-08T00:02:00+00:00", "v002"),
            ModelVersion("v004", "2026-06-08T00:03:00+00:00", "v003"),
            ModelVersion("v005", "2026-06-08T00:04:00+00:00", "v004"),
            ModelVersion(
                "v006",
                "2026-06-08T00:05:00+00:00",
                "v005",
                description="Restored to version v003",
            ),
            ModelVersion("v007", "2026-06-08T00:06:00+00:00", "v006"),
        ]

        widget = VersionGraphWidget()
        widget.set_versions(versions, current_version_id="v007")

        assert widget._positions["v006"][1] != widget._positions["v005"][1]
        assert widget._positions["v007"][1] == widget._positions["v006"][1]

    def test_graph_set_versions_empty(self):
        from src.gui.version_graph import VersionGraphWidget

        widget = VersionGraphWidget()
        widget.set_versions([])
        assert len(widget._positions) == 0

    def test_graph_highlight(self):
        from src.gui.version_graph import VersionGraphWidget

        widget = VersionGraphWidget()
        versions = self._make_versions()
        widget.set_versions(versions, current_version_id="v003")
        # Should not raise
        widget.highlight_version("v001")

    def test_graph_clear(self):
        from src.gui.version_graph import VersionGraphWidget

        widget = VersionGraphWidget()
        versions = self._make_versions()
        widget.set_versions(versions)
        widget.clear()
        assert len(widget._positions) == 0
