"""GPR (Gene-Protein-Reaction) rule parser.

Parses boolean gene association rules like:
  "b0726 and b0727" -> AndNode([GeneNode("b0726"), GeneNode("b0727")])
  "b0726 or (b0727 and b0728)" -> OrNode([GeneNode("b0726"), AndNode([...])])
"""

from __future__ import annotations

import logging
import re

from src.core.models import AndNode, GeneNode, GPRNode, OrNode

logger = logging.getLogger("gem_evaluator.gpr_parser")


def parse_gpr(rule_str: str) -> GPRNode | None:
    """Parse a GPR rule string into a tree of GPRNode objects.

    Handles COBRApy-style rules with 'and'/'or' operators and parentheses.
    """
    if not rule_str or not rule_str.strip():
        return None

    tokens = _tokenize(rule_str)
    if not tokens:
        return None

    node, pos = _parse_or(tokens, 0)
    return node


def extract_genes(rule_str: str) -> list[str]:
    """Extract all gene IDs from a GPR rule string."""
    if not rule_str or not rule_str.strip():
        return []
    # Gene IDs are non-keyword tokens (not 'and', 'or', '(', ')')
    tokens = re.findall(r"[^\s()]+", rule_str)
    return sorted({t for t in tokens if t.lower() not in ("and", "or")})


def gpr_to_string(node: GPRNode | None) -> str:
    """Convert a GPR tree back to a string representation."""
    if node is None:
        return ""
    if isinstance(node, GeneNode):
        return node.gene_id
    if isinstance(node, AndNode):
        parts = [gpr_to_string(c) for c in node.children]
        inner = " and ".join(parts)
        return f"({inner})" if len(parts) > 1 else inner
    if isinstance(node, OrNode):
        parts = [gpr_to_string(c) for c in node.children]
        inner = " or ".join(parts)
        return f"({inner})" if len(parts) > 1 else inner
    return ""


# --- Tokenizer ---

_TOKEN_RE = re.compile(r"\(|\)|[^\s()]+")


def _tokenize(rule_str: str) -> list[str]:
    return _TOKEN_RE.findall(rule_str.strip())


# --- Recursive descent parser ---


def _parse_or(tokens: list[str], pos: int) -> tuple[GPRNode, int]:
    """Parse OR expression (lowest precedence)."""
    left, pos = _parse_and(tokens, pos)
    children = [left]

    while pos < len(tokens) and tokens[pos].lower() == "or":
        pos += 1  # skip 'or'
        right, pos = _parse_and(tokens, pos)
        children.append(right)

    if len(children) == 1:
        return children[0], pos
    return OrNode(children=children), pos


def _parse_and(tokens: list[str], pos: int) -> tuple[GPRNode, int]:
    """Parse AND expression (higher precedence than OR)."""
    left, pos = _parse_atom(tokens, pos)
    children = [left]

    while pos < len(tokens) and tokens[pos].lower() == "and":
        pos += 1  # skip 'and'
        right, pos = _parse_atom(tokens, pos)
        children.append(right)

    if len(children) == 1:
        return children[0], pos
    return AndNode(children=children), pos


def _parse_atom(tokens: list[str], pos: int) -> tuple[GPRNode, int]:
    """Parse atom: either a gene ID or a parenthesized expression."""
    if pos >= len(tokens):
        raise ValueError(f"Unexpected end of GPR rule at position {pos}")

    if tokens[pos] == "(":
        pos += 1  # skip '('
        node, pos = _parse_or(tokens, pos)
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1  # skip ')'
        else:
            logger.warning("Malformed GPR: missing closing parenthesis at position %d", pos)
        return node, pos

    # Gene ID
    gene_id = tokens[pos]
    return GeneNode(gene_id=gene_id), pos + 1
