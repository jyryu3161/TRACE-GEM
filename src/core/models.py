"""Data models for the GEM Evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvidenceStrength(Enum):
    STRONG = 1.0
    MODERATE = 0.6
    WEAK = 0.3
    ABSENT = 0.0


class EvidenceSource(Enum):
    KEGG = "kegg"
    BIGG = "bigg"
    UNIPROT = "uniprot"
    PUBMED = "pubmed"
    METACYC = "metacyc"
    GEMINI = "gemini"
    PERPLEXITY = "perplexity"


class EvaluationStatus(Enum):
    NOT_EVALUATED = "not_evaluated"
    IN_PROGRESS = "in_progress"
    EVALUATED = "evaluated"
    ERROR = "error"


# --- GPR tree nodes ---


@dataclass
class GPRNode:
    """Base node for gene-protein-reaction association tree."""

    pass


@dataclass
class GeneNode(GPRNode):
    gene_id: str


@dataclass
class AndNode(GPRNode):
    children: list[GPRNode] = field(default_factory=list)


@dataclass
class OrNode(GPRNode):
    children: list[GPRNode] = field(default_factory=list)


# --- Core model data ---


@dataclass
class Metabolite:
    id: str
    name: str
    formula: str | None = None
    compartment: str | None = None
    charge: int | None = None
    annotation: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Gene:
    id: str
    name: str | None = None
    annotation: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Reaction:
    id: str
    name: str
    equation: str
    subsystem: str | None = None
    lower_bound: float = -1000.0
    upper_bound: float = 1000.0
    gene_reaction_rule: str = ""
    gpr_tree: GPRNode | None = None
    genes: list[str] = field(default_factory=list)
    reactants: dict[str, float] = field(default_factory=dict)
    products: dict[str, float] = field(default_factory=dict)
    annotation: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_exchange(self) -> bool:
        return self.id.startswith("EX_")

    @property
    def is_transport(self) -> bool:
        return "transport" in (self.subsystem or "").lower()

    @property
    def has_genes(self) -> bool:
        return len(self.genes) > 0


@dataclass
class ModelData:
    id: str
    name: str
    reactions: list[Reaction] = field(default_factory=list)
    metabolites: list[Metabolite] = field(default_factory=list)
    genes: list[Gene] = field(default_factory=list)
    organism: str | None = None
    kegg_organism_code: str | None = None
    cobra_model: object | None = field(default=None, repr=False)

    @property
    def reaction_count(self) -> int:
        return len(self.reactions)

    @property
    def metabolite_count(self) -> int:
        return len(self.metabolites)

    @property
    def gene_count(self) -> int:
        return len(self.genes)

    def get_reaction(self, reaction_id: str) -> Reaction | None:
        for r in self.reactions:
            if r.id == reaction_id:
                return r
        return None

    def get_subsystems(self) -> list[str]:
        subs = sorted({r.subsystem for r in self.reactions if r.subsystem})
        return subs


# --- Evidence data ---


@dataclass
class EvidenceItem:
    source: EvidenceSource
    strength: EvidenceStrength
    description: str
    url: str | None = None
    raw_data: dict | None = None


@dataclass
class ReactionEvidence:
    reaction_id: str
    items: list[EvidenceItem] = field(default_factory=list)
    confidence_score: float = 0.0
    status: EvaluationStatus = EvaluationStatus.NOT_EVALUATED
    error_message: str | None = None

    # Per-source scores
    kegg_score: float = 0.0
    bigg_score: float = 0.0
    uniprot_score: float = 0.0
    pubmed_score: float = 0.0
    metacyc_score: float = 0.0
    gemini_score: float = 0.0
    perplexity_score: float = 0.0

    # Cross-reference IDs resolved
    ec_numbers: list[str] = field(default_factory=list)
    kegg_reaction_ids: list[str] = field(default_factory=list)

    # Reaction verification results
    substrate_match_ratio: float = 0.0
    product_match_ratio: float = 0.0


@dataclass
class ExternalIDs:
    """Cross-reference IDs for a reaction resolved via offline mapping."""

    reaction_id: str
    bigg_id: str | None = None
    ec_numbers: list[str] = field(default_factory=list)
    kegg_reaction_ids: list[str] = field(default_factory=list)
    kegg_substrate_ids: list[str] = field(default_factory=list)
    kegg_product_ids: list[str] = field(default_factory=list)
    mnxr_ids: list[str] = field(default_factory=list)
