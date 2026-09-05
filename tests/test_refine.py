"""Tests for the shared refine core (refine_model_data + medium merge)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.models import GapFillResult, MetabolicTask, ModelData
from src.gapfill.refine import apply_base_medium_to_tasks, refine_model_data
from src.utils.config import Config


def test_apply_base_medium_merges_and_overrides() -> None:
    tasks = [
        MetabolicTask(
            task_id="T1",
            task_type="Reaction",
            target_id="BIOMASS",
            medium={"EX_glc__D_e": -5.0},
        )
    ]
    merged = apply_base_medium_to_tasks(tasks, {"EX_o2_e": -20.0, "EX_glc__D_e": -10.0})
    # base added, but task-specific value wins for glc
    assert merged[0].medium["EX_o2_e"] == -20.0
    assert merged[0].medium["EX_glc__D_e"] == -5.0
    # original task untouched
    assert tasks[0].medium == {"EX_glc__D_e": -5.0}


def test_apply_base_medium_empty_returns_same() -> None:
    tasks = [MetabolicTask(task_id="T", task_type="Reaction", target_id="R")]
    assert apply_base_medium_to_tasks(tasks, {}) is tasks


@pytest.mark.asyncio
async def test_refine_model_data_orchestration(monkeypatch) -> None:
    class FakeUniversal:
        reactions: list = []
        metabolites: list = []

    class FakeLoader:
        def load(self, path):
            return FakeUniversal()

        def extract_candidates(self, universal, model_data, exclude_exchange_reactions=True):
            return []

    class FakeTaskParser:
        def parse(self, path):
            return [MetabolicTask(task_id="T1", task_type="Reaction", target_id="R")]

    gf_result = GapFillResult(total_tasks=1, tasks_fixed=1)

    class FakeGapFill:
        def __init__(self, config, *, evidence_weighted=True):
            self.config = config
            assert evidence_weighted is False

        async def initialize(self, **kwargs):
            self.org = kwargs.get("organism_code")

        async def run(self, **kwargs):
            return gf_result

        async def close(self):
            pass

    monkeypatch.setattr("src.core.universal_loader.UniversalLoader", FakeLoader)
    monkeypatch.setattr("src.core.task_parser.TaskParser", FakeTaskParser)
    monkeypatch.setattr("src.gapfill.engine.GapFillEngine", FakeGapFill)

    ev_engine = MagicMock()
    ev_engine.cache_manager = None
    ev_engine.mapping_data = None
    ev_engine.evaluate_batch = AsyncMock(return_value={})
    ev_engine.evaluate_candidates_batch = AsyncMock(return_value={})

    cfg = Config()
    cfg.kegg_organism_code = "eco"
    md = ModelData(id="m", name="m", reactions=[], metabolites=[], genes=[])
    md.cobra_model = object()

    logs: list[str] = []
    outcome = await refine_model_data(
        cfg,
        md,
        universal_path="u.json",
        tasks_path="t.csv",
        skip_evaluation=True,
        evidence_engine=ev_engine,
        log=logs.append,
    )
    assert outcome.gf_result is gf_result
    assert len(outcome.tasks) == 1
    # skip_evaluation -> evidence engine not queried
    ev_engine.evaluate_batch.assert_not_called()
    ev_engine.evaluate_candidates_batch.assert_not_called()
    assert any("Gap-fill complete" in m for m in logs)


@pytest.mark.asyncio
async def test_refine_model_data_requires_cobra_model() -> None:
    cfg = Config()
    md = ModelData(id="m", name="m", reactions=[], metabolites=[], genes=[])
    with pytest.raises(ValueError, match="no cobra_model"):
        await refine_model_data(cfg, md, universal_path="u.json", tasks_path="t.csv")
