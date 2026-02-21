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


class ReactionOrigin(Enum):
    """Origin of a reaction in the workflow."""

    MODEL = "model"
    UNIVERSAL = "universal"
    GAP_FILLED = "gap_filled"


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


# --- Gap-filling data ---


@dataclass
class CandidateReaction:
    """Candidate reaction from a universal model for gap-filling."""

    reaction: Reaction
    source_model: str = "bigg_universal"
    organism_exists: bool | None = None
    kegg_organism_genes: list[str] = field(default_factory=list)
    assigned_gpr: str = ""
    penalty: float = 1.0
    selected: bool = False


@dataclass
class MetabolicTask:
    """Metabolic task definition for model validation."""

    task_id: str
    task_type: str  # "Metabolite" or "Reaction"
    target_id: str
    medium: dict[str, float] = field(default_factory=dict)
    constraints: dict[str, tuple[float, float]] = field(default_factory=dict)
    expected_operator: str = ">"
    expected_value: float = 0.0
    description: str = ""
    category: str = ""


@dataclass
class TaskResult:
    """Result of running a single metabolic task."""

    task: MetabolicTask
    passed: bool
    actual_value: float
    error_message: str | None = None
    phase: str = "before"  # "before" or "after"


@dataclass
class GapFillResult:
    """Complete result of a gap-filling workflow."""

    added_reactions: list[CandidateReaction] = field(default_factory=list)
    task_results_before: list[TaskResult] = field(default_factory=list)
    task_results_after: list[TaskResult] = field(default_factory=list)
    tasks_fixed: int = 0
    total_tasks: int = 0
    iterations: int = 0
    infeasible_tasks: list[str] = field(default_factory=list)


# --- Version control data ---


@dataclass
class ReactionChange:
    """A single field change in a reaction."""

    reaction_id: str
    field: str  # "lower_bound", "upper_bound", "gene_reaction_rule", "name", "subsystem"
    old_value: str
    new_value: str


@dataclass
class ModelDiff:
    """Diff between two model versions."""

    reactions_added: list[str] = field(default_factory=list)
    reactions_removed: list[str] = field(default_factory=list)
    reactions_modified: list[ReactionChange] = field(default_factory=list)
    genes_added: list[str] = field(default_factory=list)
    genes_removed: list[str] = field(default_factory=list)
    metabolites_added: list[str] = field(default_factory=list)
    metabolites_removed: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any([
            self.reactions_added, self.reactions_removed, self.reactions_modified,
            self.genes_added, self.genes_removed,
            self.metabolites_added, self.metabolites_removed,
        ])

    @property
    def summary_counts(self) -> str:
        parts = []
        if self.reactions_added:
            parts.append(f"+{len(self.reactions_added)} reactions")
        if self.reactions_removed:
            parts.append(f"-{len(self.reactions_removed)} reactions")
        if self.reactions_modified:
            parts.append(f"~{len(self.reactions_modified)} modified")
        if self.genes_added:
            parts.append(f"+{len(self.genes_added)} genes")
        if self.genes_removed:
            parts.append(f"-{len(self.genes_removed)} genes")
        return ", ".join(parts) if parts else "No changes"


@dataclass
class ModelVersion:
    """Metadata for a single model version snapshot."""

    version_id: str
    timestamp: str
    parent_version_id: str | None = None
    model_id: str = ""
    description: str = ""
    change_type: str = "initial_load"  # initial_load, manual_edit, gap_fill, restore
    diff: ModelDiff | None = None
    task_pass_rate: str | None = None  # "35/52"
    sbml_filename: str = "model.xml"
