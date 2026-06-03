"""Bridge: applies theme colors to evidence type constants at GUI startup."""

from __future__ import annotations

from src.core.models import EvidenceSource, EvidenceStrength
from src.evidence.evidence_types import STRENGTH_COLORS
from src.gui.theme import THEME

# Theme-aware source colors for GUI usage
SOURCE_COLORS: dict[EvidenceSource, str] = {
    EvidenceSource.KEGG: THEME.source_kegg,
    EvidenceSource.BIGG: THEME.source_bigg,
}


def apply_theme_colors() -> None:
    """Override default evidence colors with current theme.

    Call once during GUI initialization (in app.py after apply_theme).
    """
    STRENGTH_COLORS[EvidenceStrength.STRONG] = THEME.strength_strong
    STRENGTH_COLORS[EvidenceStrength.MODERATE] = THEME.strength_moderate
    STRENGTH_COLORS[EvidenceStrength.WEAK] = THEME.strength_weak
    STRENGTH_COLORS[EvidenceStrength.ABSENT] = THEME.strength_absent
