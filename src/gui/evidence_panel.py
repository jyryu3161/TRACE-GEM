"""Evidence panel showing multi-source verification results."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.core.models import EvidenceItem, EvidenceSource, ReactionEvidence
from src.evidence.evidence_types import (
    SOURCE_LABELS,
    SOURCE_REGISTRY,
    STRENGTH_COLORS,
    STRENGTH_LABELS,
)
from src.gui.theme import THEME, score_color


class EvidencePanelWidget(QWidget):
    """Panel showing evidence details with all source results."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Score display
        score_layout = QHBoxLayout()
        score_layout.addWidget(QLabel("Confidence Score:"))
        self._score_label = QLabel("-")
        self._score_label.setObjectName("scoreLabel")
        score_layout.addWidget(self._score_label)
        score_layout.addStretch()
        layout.addLayout(score_layout)

        # Evidence browser (single view, no tabs)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setPlainText("Select a reaction and evaluate")
        layout.addWidget(self._browser)

    def set_evidence(self, evidence: ReactionEvidence) -> None:
        score = evidence.confidence_score
        color = score_color(score)
        self._score_label.setText(f"{score:.3f}")
        self._score_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")

        html_parts = []

        # KEGG Verification summary card (special — includes match ratios)
        html_parts.append(self._render_kegg_card(evidence))

        # Database source cards (BiGG, UniProt, PubMed)
        for source in (
            EvidenceSource.BIGG,
            EvidenceSource.UNIPROT,
            EvidenceSource.PUBMED,
        ):
            items = [i for i in evidence.items if i.source == source]
            if items:
                html_parts.append(self._render_source_card(source, items[0]))

        # Gemini verification card
        gemini_items = [i for i in evidence.items if i.source == EvidenceSource.GEMINI]
        if gemini_items:
            html_parts.append(self._render_source_card(EvidenceSource.GEMINI, gemini_items[0]))

        # Perplexity verification card
        pplx_items = [i for i in evidence.items if i.source == EvidenceSource.PERPLEXITY]
        if pplx_items:
            html_parts.append(self._render_source_card(EvidenceSource.PERPLEXITY, pplx_items[0]))

        # Individual evidence items (all sources)
        for item in evidence.items:
            strength_label = STRENGTH_LABELS[item.strength]
            strength_color = STRENGTH_COLORS[item.strength]
            source_label = SOURCE_LABELS.get(item.source, item.source.value)

            html_parts.append(
                f'<div style="margin-bottom: 8px; padding: 8px; '
                f"border-left: 4px solid {strength_color}; "
                f"background-color: {THEME.evidence_item_bg}; "
                f'color: {THEME.text};">'
                f'<b style="color: {strength_color};">[{source_label}] {strength_label}</b><br>'
                f"{item.description}"
            )
            if item.url:
                html_parts.append(f'<br><a href="{item.url}">View source</a>')
            html_parts.append("</div>")

        self._browser.setHtml("".join(html_parts))

    def _render_kegg_card(self, evidence: ReactionEvidence) -> str:
        """Render KEGG-specific card with match ratios."""
        parts = []
        kegg_color = SOURCE_REGISTRY[EvidenceSource.KEGG].color

        parts.append(
            f'<div style="margin-bottom: 12px; padding: 10px; '
            f"border-left: 4px solid {kegg_color}; "
            f"background-color: {THEME.evidence_item_bg}; "
            f'color: {THEME.text}; border-radius: 4px;">'
            f"<h3>KEGG Verification</h3>"
        )

        kegg_items = [i for i in evidence.items if i.source == EvidenceSource.KEGG]
        if evidence.substrate_match_ratio > 0 or evidence.product_match_ratio > 0:
            sub_color = self._ratio_color(evidence.substrate_match_ratio)
            prod_color = self._ratio_color(evidence.product_match_ratio)

            sub_detail = f"{evidence.substrate_match_ratio:.0%}"
            prod_detail = f"{evidence.product_match_ratio:.0%}"
            sub_breakdown = ""
            prod_breakdown = ""
            if kegg_items and kegg_items[0].raw_data:
                rd = kegg_items[0].raw_data
                model_subs = rd.get("model_substrates", [])
                kegg_subs = rd.get("kegg_substrates", [])
                if model_subs or kegg_subs:
                    s_model_set = set(model_subs)
                    s_kegg_set = set(kegg_subs)
                    s_overlap = len(s_model_set & s_kegg_set)
                    s_total = len(s_model_set | s_kegg_set)
                    sub_detail = f"{s_overlap}/{s_total} ({evidence.substrate_match_ratio:.0%})"
                    sub_breakdown = self._format_compound_breakdown(
                        s_model_set, s_kegg_set, "Substrate",
                    )
                model_prods = rd.get("model_products", [])
                kegg_prods = rd.get("kegg_products", [])
                if model_prods or kegg_prods:
                    p_model_set = set(model_prods)
                    p_kegg_set = set(kegg_prods)
                    p_overlap = len(p_model_set & p_kegg_set)
                    p_total = len(p_model_set | p_kegg_set)
                    prod_detail = f"{p_overlap}/{p_total} ({evidence.product_match_ratio:.0%})"
                    prod_breakdown = self._format_compound_breakdown(
                        p_model_set, p_kegg_set, "Product",
                    )

            parts.append(
                f'<b>Substrates matched:</b> <span style="color: {sub_color};">'
                f"{sub_detail}</span> | "
                f'<b>Products matched:</b> <span style="color: {prod_color};">'
                f"{prod_detail}</span><br>"
            )
            if sub_breakdown or prod_breakdown:
                parts.append(
                    f'<div style="font-size: 12px; margin-top: 6px; '
                    f"padding: 6px; background: {THEME.chart_bg}; "
                    f'border-radius: 3px; color: {THEME.text};">'
                    f'<b style="color: {THEME.muted_text};">Compound ID Details:</b><br>'
                    f"{sub_breakdown}{prod_breakdown}"
                    f"</div>"
                )

        if evidence.kegg_reaction_ids:
            links = []
            for kid in evidence.kegg_reaction_ids:
                url = f"https://www.kegg.jp/entry/{kid}"
                links.append(f'<a href="{url}">{kid}</a>')
            parts.append(f"<b>KEGG IDs:</b> {', '.join(links)}<br>")

        if evidence.ec_numbers:
            parts.append(f"<b>EC Numbers:</b> {', '.join(evidence.ec_numbers)}<br>")

        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _render_source_card(source: EvidenceSource, item: EvidenceItem) -> str:
        """Render a generic evidence source card."""
        sc = SOURCE_REGISTRY.get(source)
        source_color = sc.color if sc else THEME.neutral
        display_name = sc.display_name if sc else source.value
        strength_color = STRENGTH_COLORS[item.strength]

        parts = [
            f'<div style="margin-bottom: 12px; padding: 10px; '
            f"border-left: 4px solid {source_color}; "
            f"background-color: {THEME.evidence_item_bg}; "
            f'color: {THEME.text}; border-radius: 4px;">',
            f"<h3>{display_name}</h3>",
            f'<span style="color: {strength_color};">',
            f"{STRENGTH_LABELS[item.strength]}</span><br>",
            item.description,
        ]
        if item.url:
            parts.append(f'<br><a href="{item.url}">View source</a>')
        parts.append("</div>")
        return "".join(parts)

    def clear(self) -> None:
        self._score_label.setText("-")
        self._score_label.setStyleSheet(f"color: {THEME.neutral};")
        self._browser.setPlainText("Select a reaction and evaluate")

    @staticmethod
    def _format_compound_breakdown(
        model_set: set[str], kegg_set: set[str], label: str,
    ) -> str:
        """Format matched/unmatched compound IDs for display."""
        matched = sorted(model_set & kegg_set)
        model_only = sorted(model_set - kegg_set)
        kegg_only = sorted(kegg_set - model_set)

        lines = [f"<b>{label}s:</b><br>"]
        for cid in matched:
            url = f"https://www.kegg.jp/entry/{cid}"
            lines.append(
                f'&nbsp;&nbsp;<span style="color: {THEME.strength_strong};">\u2713</span> '
                f'<a href="{url}">{cid}</a> (both)<br>'
            )
        for cid in model_only:
            url = f"https://www.kegg.jp/entry/{cid}"
            lines.append(
                f'&nbsp;&nbsp;<span style="color: {THEME.strength_weak};">\u2717</span> '
                f'<a href="{url}">{cid}</a> (model only)<br>'
            )
        for cid in kegg_only:
            url = f"https://www.kegg.jp/entry/{cid}"
            lines.append(
                f'&nbsp;&nbsp;<span style="color: {THEME.strength_weak};">\u2717</span> '
                f'<a href="{url}">{cid}</a> (KEGG only)<br>'
            )
        return "".join(lines)

    @staticmethod
    def _ratio_color(ratio: float) -> str:
        """Return color based on match ratio."""
        if ratio >= 0.8:
            return THEME.strength_strong
        elif ratio >= 0.5:
            return THEME.strength_moderate
        else:
            return THEME.strength_weak
