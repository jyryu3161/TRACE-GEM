"""Tests for the TaskPanelWidget GUI component."""

from __future__ import annotations

import os
import sys

import pytest

from src.core.models import MetabolicTask, TaskResult
from tests.conftest import GUI_AVAILABLE

pytestmark = pytest.mark.skipif(not GUI_AVAILABLE, reason="PySide6 GUI not available")

if GUI_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)
    from src.gui.task_panel import (
        _COLOR_FAIL_FAIL,
        _COLOR_FAIL_PASS,
        _COLOR_PASS_FAIL,
        _COLOR_PASS_PASS,
        TaskPanelWidget,
    )


@pytest.fixture
def sample_tasks() -> list[MetabolicTask]:
    return [
        MetabolicTask(task_id="U001", task_type="Metabolite", target_id="atp_c", description="ATP production", category="Energy"),
        MetabolicTask(task_id="U002", task_type="Metabolite", target_id="nadh_c", description="NADH production", category="Energy"),
        MetabolicTask(task_id="U013", task_type="Metabolite", target_id="glu__L_c", description="Glutamate biosynthesis", category="Amino Acid"),
        MetabolicTask(task_id="U020", task_type="Metabolite", target_id="amp_c", description="AMP biosynthesis", category="Nucleotide"),
    ]


@pytest.fixture
def before_results(sample_tasks: list[MetabolicTask]) -> list[TaskResult]:
    return [
        TaskResult(task=sample_tasks[0], passed=True, actual_value=10.0, phase="before"),
        TaskResult(task=sample_tasks[1], passed=True, actual_value=5.0, phase="before"),
        TaskResult(task=sample_tasks[2], passed=False, actual_value=0.0, phase="before"),
        TaskResult(task=sample_tasks[3], passed=False, actual_value=0.0, phase="before"),
    ]


@pytest.fixture
def after_results(sample_tasks: list[MetabolicTask]) -> list[TaskResult]:
    return [
        TaskResult(task=sample_tasks[0], passed=True, actual_value=10.0, phase="after"),
        TaskResult(task=sample_tasks[1], passed=True, actual_value=5.0, phase="after"),
        TaskResult(task=sample_tasks[2], passed=True, actual_value=2.5, phase="after"),
        TaskResult(task=sample_tasks[3], passed=False, actual_value=0.0, phase="after"),
    ]


class TestTaskPanelWidget:
    """Tests for TaskPanelWidget."""

    def test_creation(self) -> None:
        widget = TaskPanelWidget()
        assert widget._summary_label.text() == "No task results available"
        assert widget._category_table.rowCount() == 0
        assert widget._detail_table.rowCount() == 0

    def test_set_results_before_only(self, before_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results)
        assert "2/4 tasks passed" in widget._summary_label.text()
        assert widget._detail_table.rowCount() == 4

    def test_set_results_before_and_after(self, before_results, after_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results, after_results)
        text = widget._summary_label.text()
        assert "2/4 passed (before)" in text
        assert "3/4 passed (after)" in text
        assert "1 tasks fixed" in text

    def test_detail_table_row_count(self, before_results, after_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results, after_results)
        assert widget._detail_table.rowCount() == 4

    def test_detail_table_task_ids(self, before_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results)
        task_ids = [
            widget._detail_table.item(row, 0).text()
            for row in range(widget._detail_table.rowCount())
        ]
        assert "U001" in task_ids
        assert "U013" in task_ids

    def test_category_table_populated(self, before_results, after_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results, after_results)
        assert widget._category_table.rowCount() == 3
        categories = [
            widget._category_table.item(row, 0).text()
            for row in range(widget._category_table.rowCount())
        ]
        assert "Energy" in categories
        assert "Amino Acid" in categories
        assert "Nucleotide" in categories

    def test_category_before_counts(self, before_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results)
        for row in range(widget._category_table.rowCount()):
            if widget._category_table.item(row, 0).text() == "Energy":
                assert widget._category_table.item(row, 1).text() == "2/2"
                break

    def test_clear(self, before_results) -> None:
        widget = TaskPanelWidget()
        widget.set_results(before_results)
        assert widget._detail_table.rowCount() > 0
        widget.clear()
        assert widget._summary_label.text() == "No task results available"
        assert widget._category_table.rowCount() == 0
        assert widget._detail_table.rowCount() == 0

    def test_transition_color_pass_pass(self) -> None:
        assert TaskPanelWidget._transition_color(True, True) == _COLOR_PASS_PASS

    def test_transition_color_fail_pass(self) -> None:
        assert TaskPanelWidget._transition_color(False, True) == _COLOR_FAIL_PASS

    def test_transition_color_fail_fail(self) -> None:
        assert TaskPanelWidget._transition_color(False, False) == _COLOR_FAIL_FAIL

    def test_transition_color_pass_fail(self) -> None:
        assert TaskPanelWidget._transition_color(True, False) == _COLOR_PASS_FAIL

    def test_empty_results(self) -> None:
        widget = TaskPanelWidget()
        widget.set_results([])
        assert "0/0" in widget._summary_label.text()
        assert widget._detail_table.rowCount() == 0
        assert widget._category_table.rowCount() == 0
