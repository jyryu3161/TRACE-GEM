"""Regression checks for GUI edits and project persistence using real Qt controls."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import Mock

import cobra
import pytest

from src.core.cobra_utils import sync_model_data_from_cobra
from src.core.models import ModelData
from src.core.project_manager import ProjectData, ProjectManager
from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(not GUI_AVAILABLE, reason="PySide6 GUI not available")

if GUI_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)


def make_model(name="test_model", bounds=(0.0, 10.0)):
    cm = cobra.Model(name)
    cm.solver = "glpk"
    a = cobra.Metabolite("a_c", name="A", compartment="c")
    b = cobra.Metabolite("b_c", name="B", compartment="c")
    reaction = cobra.Reaction("R", name="original")
    reaction.bounds = bounds
    reaction.add_metabolites({a: -1, b: 1})
    cm.add_reactions([reaction])
    cm.objective = reaction
    return sync_model_data_from_cobra(ModelData(id=name, name=name), cm)


@pytest.fixture
def window(monkeypatch, tmp_path):
    from src.gui.main_window import MainWindow
    from src.utils.config import Config

    monkeypatch.setattr(MainWindow, "_init_engine", lambda self: None)
    monkeypatch.setattr(Config, "save", lambda self: None)
    widget = MainWindow(Config(version_dir=str(tmp_path / "versions")))
    yield widget
    widget._project_dirty = False
    widget.close()


def load_model(window, model):
    window._skip_organism_dialog = True
    window._on_model_loaded(model)


def test_new_sbml_save_does_not_overwrite_previous_project(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    original_path = tmp_path / "project_A.json"
    new_path = tmp_path / "project_B.json"
    load_model(window, make_model("model_A"))
    window._do_save_project(str(original_path))
    original_contents = original_path.read_bytes()

    load_model(window, make_model("model_B"))
    assert window._project_path is None
    assert "project_A.json" not in window.windowTitle()
    save_dialog = Mock(return_value=(str(new_path), "GEM Project (*.json)"))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_dialog)
    window._save_project()

    save_dialog.assert_called_once()
    assert original_path.read_bytes() == original_contents
    assert json.loads(new_path.read_text())["model"]["model_id"] == "model_B"


def test_project_load_retains_its_save_path(window, tmp_path):
    project_path = str(tmp_path / "loaded_project.json")
    window._pending_project = ProjectData(project_path=project_path)
    load_model(window, make_model())

    assert window._project_path == project_path
    window._save_project()
    assert ProjectManager.load(project_path).model_id == "test_model"


@pytest.mark.parametrize(
    "bounds",
    [
        (6.86, 10000.0),
        (-10000.0, 1.2345678901234567),
        (1e-18, 1000.0),
        (float("-inf"), float("inf")),
    ],
)
def test_name_only_edit_preserves_exact_bounds(bounds):
    from src.gui.reaction_detail import ReactionDetailWidget

    model = make_model(bounds=bounds)
    widget = ReactionDetailWidget()
    widget.set_model(model)
    widget.set_reaction(model.reactions[0])
    try:
        for name in ("renamed", "renamed again"):
            widget._name_edit.setText(name)
            widget._save_changes()
            assert model.cobra_model.reactions.R.bounds == bounds
            assert (model.reactions[0].lower_bound, model.reactions[0].upper_bound) == bounds
            assert model.cobra_model.reactions.R.name == name
    finally:
        widget.close()


@pytest.mark.parametrize("bounds", [(20.0, 30.0), (-30.0, -20.0), (6.86, 10000.0)])
def test_bound_edits_reach_calculation_model(bounds):
    from src.gui.reaction_detail import ReactionDetailWidget

    model = make_model()
    widget = ReactionDetailWidget()
    widget.set_model(model)
    widget.set_reaction(model.reactions[0])
    modified = []
    widget.reaction_modified.connect(modified.append)
    try:
        widget._lower_bound_spin.setValue(bounds[0])
        widget._upper_bound_spin.setValue(bounds[1])
        widget._save_changes()

        assert model.cobra_model.reactions.R.bounds == bounds
        assert (model.reactions[0].lower_bound, model.reactions[0].upper_bound) == bounds
        assert modified == ["R"]
    finally:
        widget.close()


def test_failed_edit_rolls_back_calculation_model_and_does_not_emit_success(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from src.gui.reaction_detail import ReactionDetailWidget

    model = make_model()
    original = model.reactions[0].to_dict()
    widget = ReactionDetailWidget()
    widget.set_model(model)
    widget.set_reaction(model.reactions[0])
    modified = []
    widget.reaction_modified.connect(modified.append)
    original_gpr = cobra.Reaction.gene_reaction_rule

    def reject_proposed_gpr(reaction, value):
        if value == "reject_me":
            raise ValueError("Model rejected the edit")
        original_gpr.fset(reaction, value)

    monkeypatch.setattr(
        cobra.Reaction,
        "gene_reaction_rule",
        property(original_gpr.fget, reject_proposed_gpr),
    )
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    try:
        widget._name_edit.setText("renamed")
        widget._lower_bound_spin.setValue(20.0)
        widget._upper_bound_spin.setValue(30.0)
        widget._gpr_edit.setPlainText("reject_me")
        widget._save_changes()

        assert model.cobra_model.reactions.R.bounds == (0.0, 10.0)
        assert model.cobra_model.reactions.R.name == "original"
        assert model.cobra_model.reactions.R.gene_reaction_rule == ""
        assert model.reactions[0].to_dict() == original
        assert modified == []
        warning.assert_called_once()
    finally:
        widget.close()


def test_restore_prompts_to_save_and_persists_restored_model(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    load_model(window, make_model())
    window._on_reaction_selected("R")
    window._reaction_detail._upper_bound_spin.setValue(20.0)
    window._reaction_detail._save_changes()
    assert window._version_manager.current_version.version_id == "v002"
    project_path = str(tmp_path / "project.json")
    window._do_save_project(project_path)
    assert not window._project_dirty

    window._version_ctrl.restore_version("v001")
    assert window._model.cobra_model.reactions.R.bounds == (0.0, 10.0)
    assert window._project_dirty
    assert window._version_manager.current_version.restore_source_version_id == "v001"
    question = Mock(return_value=QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QMessageBox, "question", question)
    window.close()

    question.assert_called_once()
    project = ProjectManager.load(project_path)
    restored = cobra.io.read_sbml_model(project.sbml_path)
    assert restored.reactions.R.bounds == (0.0, 10.0)
    assert project.current_version_id == "v003"
