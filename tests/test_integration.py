"""Integration tests."""

from pathlib import Path

import pytest

from src.core.models import EvaluationStatus, Reaction
from src.core.sbml_parser import SBMLParser
from src.utils.config import Config


class TestModelLoading:
    """Test loading and parsing the full iJO1366 model."""

    @pytest.fixture(scope="class")
    def ijo1366_path(self):
        path = Path("/Users/jaeyongryu/Documents/projects/model_evaluator/input/iJO1366.xml")
        if not path.exists():
            pytest.skip("iJO1366.xml not found")
        return path

    @pytest.fixture(scope="class")
    def model(self, ijo1366_path):
        parser = SBMLParser()
        return parser.load_model(ijo1366_path)

    def test_reaction_count(self, model):
        assert model.reaction_count >= 1800

    def test_gene_count(self, model):
        assert model.gene_count >= 1000

    def test_metabolite_count(self, model):
        assert model.metabolite_count >= 1200

    def test_organism_detected(self, model):
        assert model.organism == "Escherichia coli"
        assert model.kegg_organism_code == "eco"

    def test_eno_reaction(self, model):
        eno = model.get_reaction("ENO")
        assert eno is not None
        assert "enolase" in eno.name.lower()
        assert "b2779" in eno.genes
        assert eno.subsystem == "Glycolysis/Gluconeogenesis"

    def test_exchange_reactions(self, model):
        exchanges = [r for r in model.reactions if r.is_exchange]
        assert len(exchanges) >= 200

    def test_subsystems(self, model):
        subs = model.get_subsystems()
        assert len(subs) >= 30
        assert "Glycolysis/Gluconeogenesis" in subs

    def test_all_reactions_have_equation(self, model):
        for rxn in model.reactions:
            assert rxn.equation, f"Reaction {rxn.id} has no equation"


class TestConfigPersistence:
    def test_save_and_load(self, tmp_path, monkeypatch):
        import src.utils.constants as constants

        monkeypatch.setattr(constants, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(constants, "CONFIG_FILE_PATH", tmp_path / "config.json")

        # Need to also patch the module-level imports in config
        import src.utils.config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE_PATH", tmp_path / "config.json")

        config = Config(
            kegg_organism_code="sce",
            organism_name="Saccharomyces cerevisiae",
        )
        config.save()

        loaded = Config.load()
        assert loaded.kegg_organism_code == "sce"
        assert loaded.organism_name == "Saccharomyces cerevisiae"

    def test_weights_property(self):
        config = Config()
        weights = config.weights
        # Evidence is KEGG-only: BiGG is no longer a weighted source.
        assert weights["kegg"] == 1.0
        assert "bigg" not in weights

    def test_recent_files(self):
        config = Config()
        config.add_recent_file("/path/to/model.xml")
        config.add_recent_file("/path/to/model2.xml")
        assert config.recent_files[0] == "/path/to/model2.xml"
        assert len(config.recent_files) == 2

        # Adding duplicate moves to front
        config.add_recent_file("/path/to/model.xml")
        assert config.recent_files[0] == "/path/to/model.xml"
        assert len(config.recent_files) == 2

    def test_recent_files_max_10(self):
        config = Config()
        for i in range(15):
            config.add_recent_file(f"/path/model_{i}.xml")
        assert len(config.recent_files) == 10
        assert config.recent_files[0] == "/path/model_14.xml"

    def test_load_missing_file(self, tmp_path, monkeypatch):
        import src.utils.config as config_mod

        monkeypatch.setattr(config_mod, "CONFIG_FILE_PATH", tmp_path / "nonexistent.json")
        config = Config.load()
        assert config.kegg_organism_code == "eco"  # default

    def test_load_corrupted_file(self, tmp_path, monkeypatch):
        import src.utils.config as config_mod
        from src.utils.config import ConfigError

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not valid json{{{")
        monkeypatch.setattr(config_mod, "CONFIG_FILE_PATH", cfg_file)
        with pytest.raises(ConfigError, match="Cannot load"):
            Config.load()

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"batch_size": 0}, "batch_size"),
            ({"candidate_evidence_max_error_fraction": 1.1}, "error_fraction"),
            ({"gapfill_penalty_high": 10.0}, "tier penalties"),
            ({"carveme_solver": "invalid"}, "carveme_solver"),
        ],
    )
    def test_invalid_config_is_rejected(self, kwargs, message):
        from src.utils.config import ConfigError

        with pytest.raises(ConfigError, match=message):
            Config(**kwargs)


class TestEndToEndMocked:
    """End-to-end test with mocked API clients."""

    @pytest.mark.asyncio
    async def test_evaluate_candidate_end_to_end(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock

        from src.core.models import (
            CandidateReaction,
            EvidenceItem,
            EvidenceSource,
            EvidenceStrength,
            ExternalIDs,
        )
        from src.evidence.engine import EvidenceEngine

        config = Config(
            kegg_organism_code="eco",
            batch_size=5,
        )
        engine = EvidenceEngine(config)

        # Mock dependencies
        engine._cache = MagicMock()
        engine._mapper = MagicMock()
        engine._mapper.resolve = AsyncMock(
            return_value=ExternalIDs(reaction_id="ENO", bigg_id="ENO")
        )
        engine._kegg = MagicMock()
        engine._kegg.check_evidence = AsyncMock(
            return_value=[
                EvidenceItem(
                    source=EvidenceSource.KEGG,
                    strength=EvidenceStrength.STRONG,
                    description="KEGG reaction R00658 — substrate match: 100%, product match: 100%",
                    raw_data={
                        "kegg_id": "R00658",
                        "kegg_anchored": True,
                        "reconciliation_state": "full",
                        "ec_concordance_state": "concordant",
                        "substrate_match": 1.0,
                        "product_match": 1.0,
                    },
                ),
            ]
        )

        rxn = Reaction(id="ENO", name="enolase", equation="2pg <=> pep")
        ev = await engine.evaluate_candidate(CandidateReaction(rxn))

        assert ev.status == EvaluationStatus.EVALUATED
        assert ev.confidence_score > 0
        assert len(ev.items) >= 1
