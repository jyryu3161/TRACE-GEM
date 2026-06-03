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
    equation_id: str = ""
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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "equation": self.equation,
            "equation_id": self.equation_id,
            "subsystem": self.subsystem,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "gene_reaction_rule": self.gene_reaction_rule,
            "genes": self.genes,
            "reactants": self.reactants,
            "products": self.products,
            "annotation": self.annotation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Reaction:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            equation=data.get("equation", ""),
            equation_id=data.get("equation_id", ""),
            subsystem=data.get("subsystem"),
            lower_bound=data.get("lower_bound", -1000.0),
            upper_bound=data.get("upper_bound", 1000.0),
            gene_reaction_rule=data.get("gene_reaction_rule", ""),
            genes=data.get("genes", []),
            reactants=data.get("reactants", {}),
            products=data.get("products", {}),
            annotation=data.get("annotation", {}),
        )


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
    _reaction_index: dict[str, Reaction] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.reactions and not self._reaction_index:
            self._reaction_index = {r.id: r for r in self.reactions}

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
        """O(1) reaction lookup by ID."""
        if not self._reaction_index and self.reactions:
            self._reaction_index = {r.id: r for r in self.reactions}
        return self._reaction_index.get(reaction_id)

    def get_subsystems(self) -> list[str]:
        subs = sorted({r.subsystem for r in self.reactions if r.subsystem})
        return subs

    def remove_reaction(self, reaction_id: str) -> Reaction | None:
        """Remove a reaction and clean up orphaned metabolites/genes.

        Returns the removed Reaction, or None if not found.
        Does NOT modify the cobra_model — caller is responsible.
        """
        for i, rxn in enumerate(self.reactions):
            if rxn.id == reaction_id:
                removed = self.reactions.pop(i)
                # Invalidate index
                self._reaction_index = {}
                # Clean up orphaned metabolites
                remaining_met_ids: set[str] = set()
                for r in self.reactions:
                    remaining_met_ids.update(r.reactants.keys())
                    remaining_met_ids.update(r.products.keys())
                self.metabolites = [
                    m for m in self.metabolites if m.id in remaining_met_ids
                ]
                # Clean up orphaned genes
                remaining_gene_ids: set[str] = set()
                for r in self.reactions:
                    remaining_gene_ids.update(r.genes)  # genes is list[str]
                self.genes = [g for g in self.genes if g.id in remaining_gene_ids]
                return removed
        return None


# --- Evidence data ---


@dataclass
class EvidenceItem:
    source: EvidenceSource
    strength: EvidenceStrength
    description: str
    url: str | None = None
    raw_data: dict | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "strength": self.strength.value,
            "description": self.description,
            "url": self.url,
            "raw_data": self.raw_data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EvidenceItem:
        return cls(
            source=EvidenceSource(data["source"]),
            strength=EvidenceStrength(data["strength"]),
            description=data["description"],
            url=data.get("url"),
            raw_data=data.get("raw_data"),
        )


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
    gemini_score: float = 0.0
    perplexity_score: float = 0.0

    # Cross-reference IDs resolved
    ec_numbers: list[str] = field(default_factory=list)
    kegg_reaction_ids: list[str] = field(default_factory=list)

    # Reaction verification results
    substrate_match_ratio: float = 0.0
    product_match_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "reaction_id": self.reaction_id,
            "confidence_score": self.confidence_score,
            "status": self.status.value,
            "error_message": self.error_message,
            "kegg_score": self.kegg_score,
            "bigg_score": self.bigg_score,
            "uniprot_score": self.uniprot_score,
            "pubmed_score": self.pubmed_score,
            "gemini_score": self.gemini_score,
            "perplexity_score": self.perplexity_score,
            "ec_numbers": self.ec_numbers,
            "kegg_reaction_ids": self.kegg_reaction_ids,
            "substrate_match_ratio": self.substrate_match_ratio,
            "product_match_ratio": self.product_match_ratio,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReactionEvidence:
        items = [EvidenceItem.from_dict(d) for d in data.get("items", [])]
        return cls(
            reaction_id=data["reaction_id"],
            confidence_score=data.get("confidence_score", 0.0),
            status=EvaluationStatus(data.get("status", "not_evaluated")),
            error_message=data.get("error_message"),
            kegg_score=data.get("kegg_score", 0.0),
            bigg_score=data.get("bigg_score", 0.0),
            uniprot_score=data.get("uniprot_score", 0.0),
            pubmed_score=data.get("pubmed_score", 0.0),
            gemini_score=data.get("gemini_score", 0.0),
            perplexity_score=data.get("perplexity_score", 0.0),
            ec_numbers=data.get("ec_numbers", []),
            kegg_reaction_ids=data.get("kegg_reaction_ids", []),
            substrate_match_ratio=data.get("substrate_match_ratio", 0.0),
            product_match_ratio=data.get("product_match_ratio", 0.0),
            items=items,
        )


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

    def to_dict(self) -> dict:
        return {
            "reaction": self.reaction.to_dict(),
            "source_model": self.source_model,
            "organism_exists": self.organism_exists,
            "kegg_organism_genes": self.kegg_organism_genes,
            "assigned_gpr": self.assigned_gpr,
            "penalty": self.penalty,
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CandidateReaction:
        return cls(
            reaction=Reaction.from_dict(data["reaction"]),
            source_model=data.get("source_model", "bigg_universal"),
            organism_exists=data.get("organism_exists"),
            kegg_organism_genes=data.get("kegg_organism_genes", []),
            assigned_gpr=data.get("assigned_gpr", ""),
            penalty=data.get("penalty", 1.0),
            selected=data.get("selected", False),
        )


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

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "target_id": self.target_id,
            "medium": self.medium,
            "constraints": {k: list(v) for k, v in self.constraints.items()},
            "expected_operator": self.expected_operator,
            "expected_value": self.expected_value,
            "description": self.description,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MetabolicTask:
        constraints = {k: tuple(v) for k, v in data.get("constraints", {}).items()}
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            target_id=data["target_id"],
            medium=data.get("medium", {}),
            constraints=constraints,
            expected_operator=data.get("expected_operator", ">"),
            expected_value=data.get("expected_value", 0.0),
            description=data.get("description", ""),
            category=data.get("category", ""),
        )


@dataclass
class TaskResult:
    """Result of running a single metabolic task."""

    task: MetabolicTask
    passed: bool
    actual_value: float
    error_message: str | None = None
    phase: str = "before"  # "before" or "after"

    def to_dict(self) -> dict:
        return {
            "task": self.task.to_dict(),
            "passed": self.passed,
            "actual_value": self.actual_value,
            "error_message": self.error_message,
            "phase": self.phase,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskResult:
        return cls(
            task=MetabolicTask.from_dict(data["task"]),
            passed=data["passed"],
            actual_value=data["actual_value"],
            error_message=data.get("error_message"),
            phase=data.get("phase", "before"),
        )


@dataclass
class GapFillResult:
    """Complete result of a gap-filling workflow."""

    added_reactions: list[CandidateReaction] = field(default_factory=list)
    task_results_before: list[TaskResult] = field(default_factory=list)
    task_results_after: list[TaskResult] = field(default_factory=list)
    tasks_fixed: int = 0
    tasks_broken: int = 0
    total_tasks: int = 0
    iterations: int = 0
    infeasible_tasks: list[str] = field(default_factory=list)

    # Cancel recovery fields
    completed_phase: int = 0  # 0~5, completed phase number
    all_candidates: list[CandidateReaction] = field(default_factory=list)
    is_partial: bool = False  # True if result is from a cancelled workflow


@dataclass
class WorkflowCheckpoint:
    """Gap-fill workflow checkpoint for resume support."""

    completed_phase: int  # completed phase (0~5)
    result: GapFillResult  # partial result
    universal_path: str  # universal model path
    task_path: str | None  # task file path
    options: dict = field(default_factory=dict)  # WorkflowWizard settings
    timestamp: str = ""  # ISO 8601


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

    @property
    def compact_summary(self) -> str:
        """Git-style compact change summary, e.g. '+23 rxn, ~5 mod, +15 gene'."""
        parts: list[str] = []
        if self.reactions_added:
            parts.append(f"+{len(self.reactions_added)} rxn")
        if self.reactions_removed:
            parts.append(f"-{len(self.reactions_removed)} rxn")
        if self.reactions_modified:
            parts.append(f"~{len(self.reactions_modified)} mod")
        if self.genes_added:
            parts.append(f"+{len(self.genes_added)} gene")
        if self.genes_removed:
            parts.append(f"-{len(self.genes_removed)} gene")
        if self.metabolites_added:
            parts.append(f"+{len(self.metabolites_added)} met")
        if self.metabolites_removed:
            parts.append(f"-{len(self.metabolites_removed)} met")
        return ", ".join(parts) if parts else "\u2014"


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
