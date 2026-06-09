"""Shared test fixtures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.core.models import (
    EvaluationStatus,
    EvidenceItem,
    EvidenceSource,
    EvidenceStrength,
    EvidenceTier,
    Gene,
    Metabolite,
    ModelData,
    Reaction,
    ReactionEvidence,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _check_qapp_available() -> bool:
    """Probe whether QApplication can be created (subprocess to avoid SIGABRT)."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen');"
                "from PySide6.QtWidgets import QApplication; import sys;"
                "app = QApplication(sys.argv); print('OK')",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "OK" in result.stdout
    except Exception:
        return False


# Probe once at import time — safe because it runs in a subprocess
GUI_AVAILABLE = _check_qapp_available()


@pytest.fixture
def mini_model_path() -> Path:
    return FIXTURES_DIR / "mini_model.xml"


@pytest.fixture
def sample_reaction() -> Reaction:
    return Reaction(
        id="ENO",
        name="enolase",
        equation="D-Glycerate 2-phosphate <=> H2O + Phosphoenolpyruvate",
        equation_id="2pg_c <=> h2o_c + pep_c",
        subsystem="Glycolysis/Gluconeogenesis",
        lower_bound=-1000.0,
        upper_bound=1000.0,
        gene_reaction_rule="b2779",
        genes=["b2779"],
        reactants={"2pg_c": 1.0},
        products={"pep_c": 1.0, "h2o_c": 1.0},
    )


@pytest.fixture
def exchange_reaction() -> Reaction:
    return Reaction(
        id="EX_glc__D_e",
        name="D-Glucose exchange",
        equation="glc__D_e -->",
        subsystem="Exchange",
        lower_bound=-10.0,
        upper_bound=1000.0,
        gene_reaction_rule="",
        genes=[],
    )


@pytest.fixture
def sample_evidence() -> ReactionEvidence:
    ev = ReactionEvidence(reaction_id="ENO")
    ev.items = [
        EvidenceItem(
            source=EvidenceSource.KEGG,
            strength=EvidenceStrength.STRONG,
            description="KEGG reaction R00658 — substrate match: 100%, product match: 100%",
            url="https://www.kegg.jp/entry/R00658",
        ),
    ]
    ev.kegg_score = 1.0
    ev.evidence_tier = EvidenceTier.HIGH
    ev.evidence_rationale = "KEGG reaction evidence is present for this reaction."
    ev.substrate_match_ratio = 1.0
    ev.product_match_ratio = 1.0
    return ev


@pytest.fixture
def sample_model() -> ModelData:
    """A small in-memory model for testing GUI components."""
    reactions = [
        Reaction(
            id="ENO",
            name="enolase",
            equation="2pg <=> pep + h2o",
            subsystem="Glycolysis/Gluconeogenesis",
            genes=["b2779"],
            gene_reaction_rule="b2779",
            reactants={"2pg_c": 1.0},
            products={"pep_c": 1.0, "h2o_c": 1.0},
        ),
        Reaction(
            id="PFK",
            name="phosphofructokinase",
            equation="atp + f6p --> adp + fdp",
            subsystem="Glycolysis/Gluconeogenesis",
            genes=["b3916", "b1723"],
            gene_reaction_rule="b3916 or b1723",
            reactants={"atp_c": 1.0, "f6p_c": 1.0},
            products={"adp_c": 1.0, "fdp_c": 1.0},
        ),
        Reaction(
            id="EX_glc__D_e",
            name="D-Glucose exchange",
            equation="glc__D_e -->",
            subsystem="Exchange",
            genes=[],
        ),
    ]
    metabolites = [
        Metabolite(id="2pg_c", name="D-Glycerate 2-phosphate", compartment="c"),
        Metabolite(id="pep_c", name="Phosphoenolpyruvate", compartment="c"),
        Metabolite(id="h2o_c", name="H2O", compartment="c"),
        Metabolite(id="atp_c", name="ATP", compartment="c"),
        Metabolite(id="f6p_c", name="D-Fructose 6-phosphate", compartment="c"),
    ]
    genes = [
        Gene(id="b2779", name="eno"),
        Gene(id="b3916", name="pfkA"),
        Gene(id="b1723", name="pfkB"),
    ]
    return ModelData(
        id="test_model",
        name="Test Model",
        reactions=reactions,
        metabolites=metabolites,
        genes=genes,
        organism="Escherichia coli",
        kegg_organism_code="eco",
    )


@pytest.fixture
def mock_bigg_response() -> dict:
    """Load mock BiGG API response from fixture file."""
    import json

    return json.loads((FIXTURES_DIR / "mock_bigg_response.json").read_text())


@pytest.fixture
def sample_evidence_map() -> dict[str, ReactionEvidence]:
    """Evidence results for the sample model reactions."""
    ev_eno = ReactionEvidence(reaction_id="ENO")
    ev_eno.confidence_score = 1.0
    ev_eno.evidence_tier = EvidenceTier.HIGH
    ev_eno.evidence_rationale = "KEGG reaction evidence is present for this reaction."
    ev_eno.status = EvaluationStatus.EVALUATED
    ev_eno.kegg_score = 1.0
    ev_eno.substrate_match_ratio = 1.0
    ev_eno.product_match_ratio = 1.0
    ev_eno.ec_numbers = ["4.2.1.11"]
    ev_eno.kegg_reaction_ids = ["R00658"]
    ev_eno.items = [
        EvidenceItem(
            source=EvidenceSource.KEGG,
            strength=EvidenceStrength.STRONG,
            description="KEGG reaction R00658",
            url="https://www.kegg.jp/entry/R00658",
        ),
    ]

    ev_pfk = ReactionEvidence(reaction_id="PFK")
    ev_pfk.confidence_score = 0.6
    ev_pfk.evidence_tier = EvidenceTier.MODERATE
    ev_pfk.evidence_rationale = "KEGG evidence is weak or partial."
    ev_pfk.status = EvaluationStatus.EVALUATED
    ev_pfk.kegg_score = 0.6

    return {"ENO": ev_eno, "PFK": ev_pfk}
