"""Tests for project save/load and model serialization."""

from __future__ import annotations

import json

import pytest

from src.core.models import (
    EvaluationStatus,
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    MetabolicTask,
    ReactionEvidence,
    TaskResult,
)
from src.core.project_manager import ProjectData, ProjectManager
from src.utils.config import Config


class TestEvidenceItemSerialization:
    def test_to_dict(self):
        item = EvidenceItem(
            source=EvidenceSource.KEGG,
            strength=EvidenceStrength.STRONG,
            description="KEGG reaction R00658",
            url="https://kegg.jp/R00658",
            raw_data={"id": "R00658"},
        )
        d = item.to_dict()
        assert d["source"] == "kegg"
        assert d["strength"] == 1.0
        assert d["description"] == "KEGG reaction R00658"
        assert d["url"] == "https://kegg.jp/R00658"
        assert d["raw_data"] == {"id": "R00658"}

    def test_from_dict(self):
        d = {
            "source": "bigg",
            "strength": 0.6,
            "description": "BiGG match",
            "url": None,
            "raw_data": None,
        }
        item = EvidenceItem.from_dict(d)
        assert item.source == EvidenceSource.BIGG
        assert item.strength == EvidenceStrength.MODERATE
        assert item.description == "BiGG match"

    def test_roundtrip(self):
        item = EvidenceItem(
            source=EvidenceSource.BIGG,
            strength=EvidenceStrength.WEAK,
            description="BiGG mention",
        )
        restored = EvidenceItem.from_dict(item.to_dict())
        assert restored.source == item.source
        assert restored.strength == item.strength
        assert restored.description == item.description
        assert restored.url == item.url


class TestReactionEvidenceSerialization:
    def test_roundtrip(self):
        ev = ReactionEvidence(
            reaction_id="PFK",
            confidence_score=0.85,
            status=EvaluationStatus.EVALUATED,
            kegg_score=0.9,
            bigg_score=0.8,
            ec_numbers=["2.7.1.11"],
            kegg_reaction_ids=["R00756"],
            substrate_match_ratio=1.0,
            product_match_ratio=0.75,
            items=[
                EvidenceItem(
                    source=EvidenceSource.KEGG,
                    strength=EvidenceStrength.STRONG,
                    description="KEGG match",
                ),
            ],
        )
        d = ev.to_dict()
        restored = ReactionEvidence.from_dict(d)

        assert restored.reaction_id == "PFK"
        assert restored.confidence_score == 0.85
        assert restored.status == EvaluationStatus.EVALUATED
        assert restored.kegg_score == 0.9
        assert restored.ec_numbers == ["2.7.1.11"]
        assert restored.substrate_match_ratio == 1.0
        assert len(restored.items) == 1
        assert restored.items[0].source == EvidenceSource.KEGG

    def test_from_dict_defaults(self):
        d = {"reaction_id": "TEST"}
        ev = ReactionEvidence.from_dict(d)
        assert ev.reaction_id == "TEST"
        assert ev.confidence_score == 0.0
        assert ev.status == EvaluationStatus.NOT_EVALUATED
        assert ev.items == []

    def test_empty_items(self):
        ev = ReactionEvidence(reaction_id="ENO")
        d = ev.to_dict()
        assert d["items"] == []
        restored = ReactionEvidence.from_dict(d)
        assert restored.items == []


class TestTaskResultSerialization:
    def test_metabolic_task_roundtrip(self):
        task = MetabolicTask(
            task_id="T1",
            task_type="Reaction",
            target_id="ENO",
            medium={"glc__D_e": -10.0},
            constraints={"EX_o2_e": (-20.0, 1000.0)},
            expected_operator=">",
            expected_value=0.01,
            description="ENO flux test",
            category="core",
        )
        d = task.to_dict()
        restored = MetabolicTask.from_dict(d)

        assert restored.task_id == "T1"
        assert restored.target_id == "ENO"
        assert restored.medium == {"glc__D_e": -10.0}
        assert restored.constraints == {"EX_o2_e": (-20.0, 1000.0)}
        assert restored.expected_value == 0.01
        assert restored.category == "core"

    def test_task_result_roundtrip(self):
        task = MetabolicTask(
            task_id="T1", task_type="Reaction", target_id="PFK",
        )
        result = TaskResult(
            task=task, passed=True, actual_value=0.42, phase="before",
        )
        d = result.to_dict()
        restored = TaskResult.from_dict(d)

        assert restored.passed is True
        assert restored.actual_value == 0.42
        assert restored.phase == "before"
        assert restored.task.task_id == "T1"
        assert restored.task.target_id == "PFK"


class TestProjectData:
    def test_default_creation(self):
        project = ProjectData()
        assert project.format_version == "1.0"
        assert project.sbml_path == ""
        assert project.evaluation_results == {}
        assert project.project_path is None

    def test_creation_with_values(self):
        project = ProjectData(
            sbml_path="/path/to/model.xml",
            model_id="test_model",
            organism_code="eco",
        )
        assert project.sbml_path == "/path/to/model.xml"
        assert project.model_id == "test_model"
        assert project.organism_code == "eco"


class TestProjectManager:
    def test_save_and_load_roundtrip(self, tmp_path):
        project = ProjectData(
            sbml_path="/path/to/model.xml",
            model_id="e_coli_core",
            model_name="E. coli Core Model",
            organism_code="eco",
            organism_name="Escherichia coli",
            evaluation_results={
                "PFK": {
                    "reaction_id": "PFK",
                    "confidence_score": 0.85,
                    "status": "evaluated",
                    "items": [],
                }
            },
            universal_path="/path/to/universal.json",
            tasks_path="/path/to/tasks.csv",
            current_version_id="v003",
            version_dir="~/.gem_evaluator/versions/e_coli_core",
            scoring_weights={"kegg": 0.3, "bigg": 0.15},
        )

        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        loaded = ProjectManager.load(path)
        assert loaded.model_id == "e_coli_core"
        assert loaded.model_name == "E. coli Core Model"
        assert loaded.organism_code == "eco"
        assert loaded.sbml_path == "/path/to/model.xml"
        assert loaded.evaluation_results["PFK"]["confidence_score"] == 0.85
        assert loaded.universal_path == "/path/to/universal.json"
        assert loaded.current_version_id == "v003"
        assert loaded.scoring_weights["kegg"] == 0.3
        assert loaded.project_path == path

    def test_save_sets_timestamps(self, tmp_path):
        project = ProjectData(model_id="test")
        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        loaded = ProjectManager.load(path)
        assert loaded.created_at != ""
        assert loaded.last_modified != ""

    def test_save_preserves_created_at(self, tmp_path):
        project = ProjectData(model_id="test", created_at="2026-01-01T00:00:00Z")
        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        loaded = ProjectManager.load(path)
        assert loaded.created_at == "2026-01-01T00:00:00Z"

    def test_load_missing_sbml_path(self, tmp_path):
        """Loading a project with non-existent SBML path should succeed (path is just a reference)."""
        project = ProjectData(
            sbml_path="/does/not/exist.xml",
            model_id="test",
        )
        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        loaded = ProjectManager.load(path)
        assert loaded.sbml_path == "/does/not/exist.xml"

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "invalid.gemp"
        path.write_text("not valid json {{{")
        with pytest.raises(json.JSONDecodeError):
            ProjectManager.load(str(path))

    def test_file_is_valid_json(self, tmp_path):
        project = ProjectData(model_id="test")
        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        # Should be readable as JSON
        with open(path) as f:
            data = json.load(f)
        assert data["format_version"] == "1.0"
        assert data["model"]["model_id"] == "test"

    def test_empty_evaluation_results(self, tmp_path):
        project = ProjectData(model_id="test")
        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        loaded = ProjectManager.load(path)
        assert loaded.evaluation_results == {}

    def test_gapfill_state_roundtrip(self, tmp_path):
        task = MetabolicTask(
            task_id="T1", task_type="Reaction", target_id="ENO",
        )
        result = TaskResult(task=task, passed=True, actual_value=0.5, phase="before")

        project = ProjectData(
            model_id="test",
            task_results_before=[result.to_dict()],
            task_results_after=[result.to_dict()],
        )
        path = str(tmp_path / "test.gemp")
        ProjectManager.save(path, project)

        loaded = ProjectManager.load(path)
        assert loaded.task_results_before is not None
        assert len(loaded.task_results_before) == 1
        restored = TaskResult.from_dict(loaded.task_results_before[0])
        assert restored.task.task_id == "T1"
        assert restored.passed is True


class TestConfigRecentProjects:
    def test_add_recent_project(self):
        config = Config()
        config.add_recent_project("/path/to/project1.gemp")
        config.add_recent_project("/path/to/project2.gemp")
        assert config.recent_projects[0] == "/path/to/project2.gemp"
        assert config.recent_projects[1] == "/path/to/project1.gemp"

    def test_duplicate_moves_to_front(self):
        config = Config()
        config.add_recent_project("/path/to/p1.gemp")
        config.add_recent_project("/path/to/p2.gemp")
        config.add_recent_project("/path/to/p1.gemp")
        assert len(config.recent_projects) == 2
        assert config.recent_projects[0] == "/path/to/p1.gemp"

    def test_max_10_entries(self):
        config = Config()
        for i in range(15):
            config.add_recent_project(f"/path/to/p{i}.gemp")
        assert len(config.recent_projects) == 10
        assert config.recent_projects[0] == "/path/to/p14.gemp"
