"""Regression: tasks use self-contained media; the model default must NOT be merged.

A complete model passes all 52 tasks with task-only media. Auto-merging the
draft model's default medium (e.g. glucose) adds nutrients back into
negative-constraint tasks that omit them on purpose ("no X without carbon
source"), breaking those tests and making CLI disagree with the GUI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ECORE = Path("data/e_coli_core.xml")
TASKS = Path("data/universal_essential_tasks.csv")

pytestmark = pytest.mark.skipif(
    not (ECORE.exists() and TASKS.exists()),
    reason="e_coli_core / task data not available",
)


def _runner_and_model():
    from src.core.sbml_parser import SBMLParser
    from src.core.task_parser import TaskParser, TaskRunner

    md = SBMLParser().load_model(ECORE)
    md.cobra_model.solver = "glpk"  # fast + quiet, deterministic
    tasks = TaskParser().parse(TASKS)
    return md.cobra_model, tasks, TaskRunner()


def test_negative_tasks_pass_task_only_break_with_base_medium() -> None:
    from src.cli import load_medium_argument
    from src.gapfill.refine import apply_base_medium_to_tasks

    cobra_model, all_tasks, runner = _runner_and_model()
    # "no ATP/no R5P without carbon source" negative-constraint tasks
    neg = [t for t in all_tasks if t.task_id in {"U041", "U051"}]
    assert len(neg) == 2

    # task-only media: negative constraints correctly satisfied (=0)
    task_only = {r.task.task_id: r.passed for r in runner.run_all(cobra_model, neg)}
    assert task_only["U041"] and task_only["U051"], "negatives should pass without carbon"

    # merging the model default medium (glucose) breaks them — this is the bug
    # that the CLI no longer triggers when --medium is omitted.
    base = load_medium_argument(None, cobra_model)
    assert "EX_glc__D_e" in base  # model default includes glucose
    merged = apply_base_medium_to_tasks(neg, base)
    with_base = {r.task.task_id: r.passed for r in runner.run_all(cobra_model, merged)}
    assert not with_base["U041"] and not with_base["U051"]


def test_base_merge_only_breaks_negatives_never_gains() -> None:
    """Across all 52 tasks: merging the model default medium can only BREAK
    negative-constraint tasks, never gain any — so task-only is strictly better."""
    from src.cli import load_medium_argument
    from src.gapfill.refine import apply_base_medium_to_tasks

    cobra_model, all_tasks, runner = _runner_and_model()
    task_only = {r.task.task_id: r.passed for r in runner.run_all(cobra_model, all_tasks)}

    base = load_medium_argument(None, cobra_model)
    merged = apply_base_medium_to_tasks(all_tasks, base)
    with_base = {r.task.task_id: r.passed for r in runner.run_all(cobra_model, merged)}

    gained = [t for t in task_only if not task_only[t] and with_base[t]]
    broken = [t for t in task_only if task_only[t] and not with_base[t]]
    assert gained == [], f"base merge should never gain tasks, gained: {gained}"
    assert broken, "expected base merge to break at least one negative-constraint task"
    assert sum(task_only.values()) > sum(with_base.values())
