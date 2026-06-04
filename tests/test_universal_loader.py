"""Tests for UniversalLoader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import cobra
import pytest

from src.core.models import CandidateReaction, ModelData, Reaction
from src.core.universal_loader import UniversalLoader


@pytest.fixture
def loader() -> UniversalLoader:
    return UniversalLoader()


@pytest.fixture
def mock_cobra_model() -> MagicMock:
    """Create a mock cobra.Model with a few reactions."""
    model = MagicMock()
    model.id = "universal_model"
    model.name = "Universal Model"

    def _make_rxn(rxn_id: str, name: str, subsystem: str = "") -> MagicMock:
        rxn = MagicMock()
        rxn.id = rxn_id
        rxn.name = name
        rxn.subsystem = subsystem
        rxn.gene_reaction_rule = ""
        rxn.lower_bound = -1000.0
        rxn.upper_bound = 1000.0
        rxn.annotation = {}
        rxn.metabolites = {}
        rxn.build_reaction_string.return_value = f"{name} equation"
        return rxn

    rxn_pfk = _make_rxn("PFK", "Phosphofructokinase", "Glycolysis")
    rxn_eno = _make_rxn("ENO", "Enolase", "Glycolysis")
    rxn_glns = _make_rxn("GLNS", "Glutamine synthetase", "Amino Acid")
    rxn_tkt = _make_rxn("TKT1", "Transketolase", "Pentose Phosphate")
    rxn_ex = _make_rxn("EX_glc__D_e", "Glucose exchange", "Exchange")
    rxn_dm = _make_rxn("DM_atp_c", "ATP demand", "Demand")
    rxn_sk = _make_rxn("SK_h2o_c", "H2O sink", "Sink")
    rxn_sink = _make_rxn("sink_coa_c", "CoA sink", "Sink")

    model.reactions = [rxn_pfk, rxn_eno, rxn_glns, rxn_tkt, rxn_ex, rxn_dm, rxn_sk, rxn_sink]
    model.metabolites = []

    return model


@pytest.fixture
def user_model_data() -> ModelData:
    """User model with ENO and PFK reactions."""
    return ModelData(
        id="test_model",
        name="Test Model",
        reactions=[
            Reaction(id="ENO", name="enolase", equation="2pg <=> pep + h2o"),
            Reaction(id="PFK", name="phosphofructokinase", equation="atp + f6p --> adp + fdp"),
            Reaction(id="EX_glc__D_e", name="Glucose exchange", equation="glc__D_e -->"),
        ],
    )


class TestLoadJson:
    def test_load_json(self, loader: UniversalLoader, tmp_path: Path) -> None:
        """load_json delegates to cobra.io.load_json_model."""
        fake_file = tmp_path / "model.json"
        fake_file.touch()

        mock_model = MagicMock()
        mock_model.id = "test"
        mock_model.reactions = []
        mock_model.metabolites = []

        with patch("src.core.universal_loader.cobra.io.load_json_model", return_value=mock_model) as mock_load:
            result = loader.load_json(fake_file)

        mock_load.assert_called_once_with(str(fake_file))
        assert result is mock_model

    def test_load_json_removes_solver_reserved_reactions(
        self,
        loader: UniversalLoader,
        tmp_path: Path,
    ) -> None:
        """Solver keyword reaction IDs are removed from universal models."""
        fake_file = tmp_path / "model.json"
        fake_file.touch()

        model = cobra.Model("universal")
        reserved = cobra.Reaction("St")
        safe = cobra.Reaction("SAFE_RXN")
        model.add_reactions([reserved, safe])

        with patch("src.core.universal_loader.cobra.io.load_json_model", return_value=model):
            result = loader.load_json(fake_file)

        assert "St" not in result.reactions
        assert "SAFE_RXN" in result.reactions

    def test_load_json_file_not_found(self, loader: UniversalLoader) -> None:
        """load_json raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="Universal model file not found"):
            loader.load_json("/nonexistent/model.json")


class TestLoadSbml:
    def test_load_sbml(self, loader: UniversalLoader, tmp_path: Path) -> None:
        """load_sbml delegates to cobra.io.read_sbml_model."""
        fake_file = tmp_path / "model.xml"
        fake_file.touch()

        mock_model = MagicMock()
        mock_model.id = "test"
        mock_model.reactions = []
        mock_model.metabolites = []

        with patch("src.core.universal_loader.cobra.io.read_sbml_model", return_value=mock_model) as mock_load:
            result = loader.load_sbml(fake_file)

        mock_load.assert_called_once_with(str(fake_file))
        assert result is mock_model

    def test_load_sbml_file_not_found(self, loader: UniversalLoader) -> None:
        """load_sbml raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="Universal model file not found"):
            loader.load_sbml("/nonexistent/model.xml")


class TestLoadAutoDetect:
    def test_load_auto_detect_json(self, loader: UniversalLoader) -> None:
        """load() routes .json to load_json."""
        mock_model = MagicMock()
        mock_model.id = "test"
        mock_model.reactions = []
        mock_model.metabolites = []

        with patch.object(loader, "load_json", return_value=mock_model) as mock_load:
            result = loader.load("/fake/model.json")

        mock_load.assert_called_once()
        assert result is mock_model

    def test_load_auto_detect_xml(self, loader: UniversalLoader) -> None:
        """load() routes .xml to load_sbml."""
        mock_model = MagicMock()
        mock_model.id = "test"
        mock_model.reactions = []
        mock_model.metabolites = []

        with patch.object(loader, "load_sbml", return_value=mock_model) as mock_load:
            result = loader.load("/fake/model.xml")

        mock_load.assert_called_once()
        assert result is mock_model

    def test_load_auto_detect_sbml(self, loader: UniversalLoader) -> None:
        """load() routes .sbml to load_sbml."""
        mock_model = MagicMock()

        with patch.object(loader, "load_sbml", return_value=mock_model) as mock_load:
            result = loader.load("/fake/model.sbml")

        mock_load.assert_called_once()
        assert result is mock_model

    def test_load_unsupported_format(self, loader: UniversalLoader) -> None:
        """load() raises ValueError for unsupported extensions."""
        with pytest.raises(ValueError, match="Unsupported file format"):
            loader.load("/fake/model.txt")


class TestExtractCandidates:
    def test_extract_candidates_excludes_model_reactions(
        self,
        loader: UniversalLoader,
        mock_cobra_model: MagicMock,
        user_model_data: ModelData,
    ) -> None:
        """Reactions already in user model are excluded."""
        candidates = loader.extract_candidates(mock_cobra_model, user_model_data)
        candidate_ids = {c.reaction.id for c in candidates}

        # ENO and PFK are in the user model, should be excluded
        assert "ENO" not in candidate_ids
        assert "PFK" not in candidate_ids

        # GLNS and TKT1 are NOT in user model, should be included
        assert "GLNS" in candidate_ids
        assert "TKT1" in candidate_ids

    def test_extract_candidates_excludes_exchange(
        self,
        loader: UniversalLoader,
        mock_cobra_model: MagicMock,
        user_model_data: ModelData,
    ) -> None:
        """Exchange, demand, sink reactions are excluded."""
        candidates = loader.extract_candidates(mock_cobra_model, user_model_data)
        candidate_ids = {c.reaction.id for c in candidates}

        assert "EX_glc__D_e" not in candidate_ids
        assert "DM_atp_c" not in candidate_ids
        assert "SK_h2o_c" not in candidate_ids
        assert "sink_coa_c" not in candidate_ids

    def test_extract_candidates_normalizes_r_prefix(
        self,
        loader: UniversalLoader,
        user_model_data: ModelData,
    ) -> None:
        """R_ prefix is stripped for ID comparison."""
        model = MagicMock()
        model.id = "universal"

        # Universal has R_ENO, user model has ENO -> should be excluded
        rxn = MagicMock()
        rxn.id = "R_ENO"
        rxn.name = "Enolase"
        rxn.subsystem = ""
        rxn.gene_reaction_rule = ""
        rxn.lower_bound = -1000.0
        rxn.upper_bound = 1000.0
        rxn.annotation = {}
        rxn.metabolites = {}
        rxn.build_reaction_string.return_value = "equation"

        model.reactions = [rxn]
        model.metabolites = []

        candidates = loader.extract_candidates(model, user_model_data)
        assert len(candidates) == 0

    def test_extract_candidates_case_insensitive(
        self,
        loader: UniversalLoader,
        user_model_data: ModelData,
    ) -> None:
        """ID comparison is case-insensitive."""
        model = MagicMock()
        model.id = "universal"

        rxn = MagicMock()
        rxn.id = "eno"  # lowercase, user model has "ENO"
        rxn.name = "Enolase"
        rxn.subsystem = ""
        rxn.gene_reaction_rule = ""
        rxn.lower_bound = -1000.0
        rxn.upper_bound = 1000.0
        rxn.annotation = {}
        rxn.metabolites = {}
        rxn.build_reaction_string.return_value = "equation"

        model.reactions = [rxn]
        model.metabolites = []

        candidates = loader.extract_candidates(model, user_model_data)
        assert len(candidates) == 0

    def test_extract_candidates_returns_candidate_reaction(
        self,
        loader: UniversalLoader,
        mock_cobra_model: MagicMock,
        user_model_data: ModelData,
    ) -> None:
        """Returned items are CandidateReaction with correct source_model."""
        candidates = loader.extract_candidates(mock_cobra_model, user_model_data)

        assert len(candidates) > 0
        for c in candidates:
            assert isinstance(c, CandidateReaction)
            assert isinstance(c.reaction, Reaction)
            assert c.source_model == "universal_model"
            assert c.penalty == 1.0
            assert c.selected is False
