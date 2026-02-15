"""Evidence type definitions and strength classifiers."""

from __future__ import annotations

from src.core.models import EvidenceSource, EvidenceStrength
from src.gui.theme import THEME

# Display labels
STRENGTH_LABELS = {
    EvidenceStrength.STRONG: "Strong",
    EvidenceStrength.MODERATE: "Moderate",
    EvidenceStrength.WEAK: "Weak",
    EvidenceStrength.ABSENT: "Not found",
}

SOURCE_LABELS = {
    EvidenceSource.KEGG: "KEGG",
    EvidenceSource.GEMINI: "Gemini",
    EvidenceSource.PERPLEXITY: "Perplexity",
}

# Color coding for evidence strength (hex)
STRENGTH_COLORS = {
    EvidenceStrength.STRONG: THEME.strength_strong,
    EvidenceStrength.MODERATE: THEME.strength_moderate,
    EvidenceStrength.WEAK: THEME.strength_weak,
    EvidenceStrength.ABSENT: THEME.strength_absent,
}
