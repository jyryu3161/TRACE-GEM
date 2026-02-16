"""Score visualization charts using PyQtGraph."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from src.core.models import ReactionEvidence
from src.evidence.evidence_types import get_ordered_sources
from src.gui.theme import THEME

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False


class ScoreVisualizationWidget(QWidget):
    """Charts showing score distribution, match ratios, by-source, and subsystem breakdown."""

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

        # Histogram tab
        self._hist_widget = pg.PlotWidget(title="Score Distribution")
        self._hist_widget.setLabel("bottom", "Confidence Score")
        self._hist_widget.setLabel("left", "Reaction Count")
        self._tabs.addTab(self._hist_widget, "Distribution")

        # Match ratio chart
        self._match_widget = pg.PlotWidget(title="Database Match Ratios")
        self._match_widget.setLabel("bottom", "Match Ratio")
        self._match_widget.setLabel("left", "Reaction Count")
        self._tabs.addTab(self._match_widget, "Match Ratios")

        # By Source chart (new)
        self._source_widget = pg.PlotWidget(title="Average Score by Source")
        self._source_widget.setLabel("bottom", "Source")
        self._source_widget.setLabel("left", "Average Score")
        self._tabs.addTab(self._source_widget, "By Source")

        # Per-subsystem chart
        self._subsystem_widget = pg.PlotWidget(title="Average Score by Subsystem")
        self._subsystem_widget.setLabel("bottom", "Subsystem")
        self._subsystem_widget.setLabel("left", "Average Score")
        self._tabs.addTab(self._subsystem_widget, "By Subsystem")

        layout.addWidget(self._tabs)

    def update_charts(
        self,
        evidence: dict[str, ReactionEvidence],
        subsystem_map: dict[str, str] | None = None,
    ) -> None:
        if not HAS_PYQTGRAPH:
            return

        scores = [ev.confidence_score for ev in evidence.values() if ev.confidence_score >= 0]
        if not scores:
            return

        self._update_histogram(scores)
        self._update_match_chart(evidence)
        self._update_source_chart(evidence)
        if subsystem_map:
            self._update_subsystem_chart(evidence, subsystem_map)

    def _update_histogram(self, scores: list[float]) -> None:
        self._hist_widget.clear()

        import numpy as np

        bins = np.linspace(0, 1, 21)
        counts, edges = np.histogram(scores, bins=bins)

        colors = []
        for edge in edges[:-1]:
            mid = edge + 0.025
            if mid >= 0.7:
                colors.append(pg.mkBrush(THEME.score_high))
            elif mid >= 0.4:
                colors.append(pg.mkBrush(THEME.score_mid))
            else:
                colors.append(pg.mkBrush(THEME.score_low))

        bar = pg.BarGraphItem(
            x=edges[:-1] + 0.025,
            height=counts,
            width=0.045,
            brushes=colors,
            pen=pg.mkPen(THEME.chart_pen, width=1),
        )
        self._hist_widget.addItem(bar)

    def _update_match_chart(self, evidence: dict[str, ReactionEvidence]) -> None:
        """Show distribution of substrate/product match ratios."""
        self._match_widget.clear()

        import numpy as np

        sub_ratios = [ev.substrate_match_ratio for ev in evidence.values()]
        prod_ratios = [ev.product_match_ratio for ev in evidence.values()]

        bins = np.linspace(0, 1, 11)

        # Substrate match histogram
        sub_counts, _ = np.histogram(sub_ratios, bins=bins)
        bar1 = pg.BarGraphItem(
            x=bins[:-1] + 0.03,
            height=sub_counts,
            width=0.04,
            brush=pg.mkBrush(THEME.chart_primary),
            pen=pg.mkPen(THEME.chart_pen, width=1),
            name="Substrates",
        )
        self._match_widget.addItem(bar1)

        # Product match histogram (offset)
        prod_counts, _ = np.histogram(prod_ratios, bins=bins)
        bar2 = pg.BarGraphItem(
            x=bins[:-1] + 0.07,
            height=prod_counts,
            width=0.04,
            brush=pg.mkBrush(THEME.chart_secondary),
            pen=pg.mkPen(THEME.chart_pen, width=1),
            name="Products",
        )
        self._match_widget.addItem(bar2)

        # Add legend
        self._match_widget.addLegend()

    def _update_source_chart(self, evidence: dict[str, ReactionEvidence]) -> None:
        """Show average score per evidence source."""
        self._source_widget.clear()

        ordered = get_ordered_sources()
        names = []
        averages = []
        brushes = []

        for source, sc in ordered:
            attr = f"{source.value}_score"
            scores = [getattr(ev, attr, 0.0) for ev in evidence.values()]
            avg = sum(scores) / len(scores) if scores else 0.0
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

        ax = self._source_widget.getAxis("bottom")
        ax.setTicks([list(zip(x, names, strict=False))])

    def _update_subsystem_chart(
        self,
        evidence: dict[str, ReactionEvidence],
        subsystem_map: dict[str, str],
    ) -> None:
        self._subsystem_widget.clear()

        sub_scores: dict[str, list[float]] = {}
        for rxn_id, ev in evidence.items():
            sub = subsystem_map.get(rxn_id, "Unknown")
            sub_scores.setdefault(sub, []).append(ev.confidence_score)

        # Sort by average score
        sorted_subs = sorted(
            sub_scores.items(),
            key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
        )

        # Limit to top 20 subsystems
        sorted_subs = sorted_subs[-20:]

        names = [s[0][:25] for s in sorted_subs]
        averages = [sum(s[1]) / len(s[1]) if s[1] else 0 for s in sorted_subs]

        x = list(range(len(names)))
        bar = pg.BarGraphItem(
            x=x,
            height=averages,
            width=0.6,
            brush=pg.mkBrush(THEME.chart_secondary),
            pen=pg.mkPen(THEME.chart_pen, width=1),
        )
        self._subsystem_widget.addItem(bar)

        ax = self._subsystem_widget.getAxis("bottom")
        ax.setTicks([list(zip(x, names, strict=False))])
