"""Evidence tier visualization charts using PyQtGraph."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from src.core.models import EvidenceTier, ReactionEvidence
from src.evidence.evidence_types import get_ordered_sources
from src.gui.theme import THEME

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False


def _add_value_labels(
    plot_widget: pg.PlotWidget,
    x_vals: list[float],
    y_vals: list[float],
    fmt: str = "{:.2f}",
    color: str = "#FFFFFF",
    offset_y: float = 0.0,
) -> None:
    """Add text labels above each bar showing the numeric value."""
    for xv, yv in zip(x_vals, y_vals, strict=False):
        if yv == 0:
            continue
        label = pg.TextItem(
            text=fmt.format(yv),
            color=color,
            anchor=(0.5, 1.0),
        )
        label.setPos(xv, yv + offset_y)
        plot_widget.addItem(label)


class ScoreVisualizationWidget(QWidget):
    """Charts showing tier distribution, match ratios, by-source, and subsystem breakdown."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not HAS_PYQTGRAPH:
            from PySide6.QtWidgets import QLabel

            layout.addWidget(QLabel("PyQtGraph not installed — charts unavailable"))
            return

        pg.setConfigOptions(antialias=True, background=THEME.chart_bg, foreground=THEME.chart_fg)

        self._tabs = QTabWidget()

        # Evidence tier distribution tab
        self._hist_widget = pg.PlotWidget(title="Evidence Tier Distribution")
        self._hist_widget.setLabel("bottom", "Evidence Tier")
        self._hist_widget.setLabel("left", "Reaction Count")
        self._tabs.addTab(self._hist_widget, "Distribution")

        # Match ratio chart
        self._match_widget = pg.PlotWidget(title="Database Match Ratios")
        self._match_widget.setLabel("bottom", "Match Ratio")
        self._match_widget.setLabel("left", "Reaction Count")
        self._tabs.addTab(self._match_widget, "Match Ratios")

        # By Source chart
        self._source_widget = pg.PlotWidget(title="Average Source Strength")
        self._source_widget.setLabel("bottom", "Source")
        self._source_widget.setLabel("left", "Average Strength")
        self._tabs.addTab(self._source_widget, "By Source")

        # Per-subsystem chart
        self._subsystem_widget = pg.PlotWidget(title="Evidence Tier by Subsystem")
        self._subsystem_widget.setLabel("bottom", "Reaction Count")
        self._subsystem_widget.setLabel("left", "Subsystem")
        self._tabs.addTab(self._subsystem_widget, "By Subsystem")

        self._chart_titles = {
            self._hist_widget: "Evidence Tier Distribution",
            self._match_widget: "Database Match Ratios",
            self._source_widget: "Average Source Strength",
            self._subsystem_widget: "Evidence Tier by Subsystem",
        }
        for widget in self._chart_titles:
            self._style_plot(widget)

        layout.addWidget(self._tabs)

    def _style_plot(self, widget: pg.PlotWidget) -> None:
        """Apply shared chart styling for consistent export/screenshot output."""
        widget.showGrid(x=True, y=True, alpha=0.22)
        widget.setMenuEnabled(False)
        widget.hideButtons()
        widget.getAxis("bottom").setPen(pg.mkPen(THEME.chart_pen))
        widget.getAxis("left").setPen(pg.mkPen(THEME.chart_pen))
        widget.getAxis("bottom").setTextPen(pg.mkPen(THEME.chart_fg))
        widget.getAxis("left").setTextPen(pg.mkPen(THEME.chart_fg))

    def _clear_plots(self, empty: bool = False) -> None:
        """Clear all plots and optionally mark them as empty."""
        for widget, title in self._chart_titles.items():
            widget.clear()
            suffix = " (no data)" if empty else ""
            widget.setTitle(f"{title}{suffix}")

    def update_charts(
        self,
        evidence: dict[str, ReactionEvidence],
        subsystem_map: dict[str, str] | None = None,
    ) -> None:
        if not HAS_PYQTGRAPH:
            return

        evaluated = list(evidence.values())
        if not evaluated:
            self._clear_plots(empty=True)
            return

        self._clear_plots()

        self._update_tier_distribution(evaluated)
        self._update_match_chart(evidence)
        self._update_source_chart(evidence)
        self._update_subsystem_chart(evidence, subsystem_map or {})

    def _update_tier_distribution(self, evidence: list[ReactionEvidence]) -> None:
        tiers = [
            EvidenceTier.HIGH,
            EvidenceTier.MODERATE,
            EvidenceTier.LOW,
            EvidenceTier.NOT_ASSESSABLE,
        ]
        counts = [sum(1 for ev in evidence if ev.evidence_tier == tier) for tier in tiers]
        labels = [tier.label for tier in tiers]
        colors = [pg.mkBrush(self._tier_color(tier)) for tier in tiers]

        x_centers = list(range(len(tiers)))
        bar = pg.BarGraphItem(
            x=x_centers,
            height=counts,
            width=0.62,
            brushes=colors,
            pen=pg.mkPen(THEME.chart_pen, width=1),
        )
        self._hist_widget.addItem(bar)

        max_count = max(counts) if counts else 1
        _add_value_labels(
            self._hist_widget,
            [float(x) for x in x_centers],
            [int(c) for c in counts],
            fmt="{:.0f}",
            color=THEME.chart_fg,
            offset_y=max_count * 0.02,
        )

        ax = self._hist_widget.getAxis("bottom")
        ax.setTicks([list(zip(x_centers, labels, strict=False))])
        self._hist_widget.setXRange(-0.6, len(tiers) - 0.4, padding=0)
        self._hist_widget.setYRange(0, max(max_count * 1.18, 1), padding=0)

    def _update_match_chart(self, evidence: dict[str, ReactionEvidence]) -> None:
        """Show distribution of substrate/product match ratios."""
        import numpy as np

        sub_ratios = [ev.substrate_match_ratio for ev in evidence.values()]
        prod_ratios = [ev.product_match_ratio for ev in evidence.values()]

        bins = np.linspace(0, 1, 11)

        # Substrate match histogram
        sub_counts, _ = np.histogram(sub_ratios, bins=bins)
        x_sub = list(bins[:-1] + 0.03)
        bar1 = pg.BarGraphItem(
            x=x_sub,
            height=sub_counts,
            width=0.04,
            brush=pg.mkBrush(THEME.chart_primary),
            pen=pg.mkPen(THEME.chart_pen, width=1),
            name="Substrates",
        )
        self._match_widget.addItem(bar1)

        # Product match histogram (offset)
        prod_counts, _ = np.histogram(prod_ratios, bins=bins)
        x_prod = list(bins[:-1] + 0.07)
        bar2 = pg.BarGraphItem(
            x=x_prod,
            height=prod_counts,
            width=0.04,
            brush=pg.mkBrush(THEME.chart_secondary),
            pen=pg.mkPen(THEME.chart_pen, width=1),
            name="Products",
        )
        self._match_widget.addItem(bar2)

        # Value labels
        max_count = max(max(sub_counts), max(prod_counts)) if len(sub_counts) else 1
        _add_value_labels(
            self._match_widget, x_sub, [int(c) for c in sub_counts],
            fmt="{:.0f}", color=THEME.chart_fg, offset_y=max_count * 0.02,
        )
        _add_value_labels(
            self._match_widget, x_prod, [int(c) for c in prod_counts],
            fmt="{:.0f}", color=THEME.chart_fg, offset_y=max_count * 0.02,
        )

        legend_y = max(max_count * 1.12, 1.0)
        sub_label = pg.TextItem("Substrates", color=THEME.chart_primary, anchor=(0, 1))
        sub_label.setPos(0.02, legend_y)
        prod_label = pg.TextItem("Products", color=THEME.chart_secondary, anchor=(0, 1))
        prod_label.setPos(0.22, legend_y)
        self._match_widget.addItem(sub_label)
        self._match_widget.addItem(prod_label)
        self._match_widget.setXRange(0, 1, padding=0.01)
        self._match_widget.setYRange(0, max(max_count * 1.25, 1), padding=0)

    def _update_source_chart(self, evidence: dict[str, ReactionEvidence]) -> None:
        """Show average source strength per evidence source."""
        ordered = get_ordered_sources()
        names = []
        averages = []
        brushes = []

        for source, sc in ordered:
            attr = f"{source.value}_score"
            source_scores = [getattr(ev, attr, 0.0) for ev in evidence.values()]
            avg = sum(source_scores) / len(source_scores) if source_scores else 0.0
            names.append(sc.display_name)
            averages.append(avg)
            brushes.append(pg.mkBrush(sc.color))

        x = list(range(len(names)))
        bar = pg.BarGraphItem(
            x=x,
            height=averages,
            width=0.6,
            brushes=brushes,
            pen=pg.mkPen(THEME.chart_pen, width=1),
        )
        self._source_widget.addItem(bar)

        # Value labels on bars
        _add_value_labels(
            self._source_widget,
            [float(v) for v in x],
            averages,
            fmt="{:.3f}",
            color=THEME.chart_fg,
            offset_y=0.01,
        )

        ax = self._source_widget.getAxis("bottom")
        ax.setTicks([list(zip(x, names, strict=False))])
        self._source_widget.setXRange(-0.6, max(len(names) - 0.4, 0.5), padding=0)
        self._source_widget.setYRange(0, 1.05, padding=0)

    def _update_subsystem_chart(
        self,
        evidence: dict[str, ReactionEvidence],
        subsystem_map: dict[str, str],
    ) -> None:
        sub_counts: dict[str, dict[EvidenceTier, int]] = {}
        for rxn_id, ev in evidence.items():
            sub = subsystem_map.get(rxn_id, "Unknown")
            counts = sub_counts.setdefault(
                sub,
                {
                    EvidenceTier.HIGH: 0,
                    EvidenceTier.MODERATE: 0,
                    EvidenceTier.LOW: 0,
                    EvidenceTier.NOT_ASSESSABLE: 0,
                },
            )
            counts[ev.evidence_tier] += 1

        # Sort by total high/moderate/low tier rank, then limit to top 20 subsystems
        sorted_subs = sorted(
            sub_counts.items(),
            key=lambda x: (
                x[1][EvidenceTier.HIGH] * 3
                + x[1][EvidenceTier.MODERATE] * 2
                + x[1][EvidenceTier.LOW]
            ),
        )
        sorted_subs = sorted_subs[-20:]

        totals = [sum(counts.values()) for _, counts in sorted_subs]
        names = [
            self._format_subsystem_label(name, total)
            for (name, _counts), total in zip(sorted_subs, totals, strict=False)
        ]

        y = list(range(len(names)))
        left = [0] * len(names)
        for tier in (EvidenceTier.HIGH, EvidenceTier.MODERATE, EvidenceTier.LOW, EvidenceTier.NOT_ASSESSABLE):
            widths = [counts[tier] for _, counts in sorted_subs]
            if any(widths):
                bar = pg.BarGraphItem(
                    x0=left,
                    y=y,
                    width=widths,
                    height=0.6,
                    brush=pg.mkBrush(self._tier_color(tier)),
                    pen=pg.mkPen(THEME.chart_pen, width=1),
                )
                self._subsystem_widget.addItem(bar)
            left = [offset + width for offset, width in zip(left, widths, strict=False)]

        ax = self._subsystem_widget.getAxis("left")
        ax.setTicks([list(zip(y, names, strict=False))])
        ax.setWidth(280)
        ax.setStyle(tickTextOffset=8, autoExpandTextSpace=True)
        max_total = max(totals) if totals else 1
        self._subsystem_widget.setXRange(0, max(max_total * 1.08, 1), padding=0)
        self._subsystem_widget.setYRange(-0.6, max(len(names) - 0.4, 0.5), padding=0)

        legend_y = max(len(names) - 0.1, 0.5)
        legend_x = max(max_total * 0.04, 0.05)
        for i, tier in enumerate((EvidenceTier.HIGH, EvidenceTier.MODERATE, EvidenceTier.LOW, EvidenceTier.NOT_ASSESSABLE)):
            label = pg.TextItem(tier.label, color=self._tier_color(tier), anchor=(0, 1))
            label.setPos(legend_x + i * max(max_total * 0.22, 1.2), legend_y)
            self._subsystem_widget.addItem(label)

    @staticmethod
    def _format_subsystem_label(name: str, count: int) -> str:
        """Keep subsystem labels readable on a horizontal axis."""
        max_chars = 38
        label = name if len(name) <= max_chars else f"{name[:max_chars - 3]}..."
        return f"{label} (n={count})"

    @staticmethod
    def _tier_color(tier: EvidenceTier) -> str:
        if tier == EvidenceTier.HIGH:
            return THEME.score_high
        if tier == EvidenceTier.MODERATE:
            return THEME.score_mid
        if tier == EvidenceTier.LOW:
            return THEME.score_low
        return THEME.score_none  # Not assessable — neutral grey, distinct from Low
