"""Version history graph visualization using PyQtGraph.

Displays ModelVersion nodes connected by parent→child edges in a
git-log-style branch graph. Supports click-to-select, hover tooltips,
and current version highlighting.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.core.models import ModelVersion
from src.gui.theme import THEME

try:
    import pyqtgraph as pg

    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

# Node size constants
_NODE_SIZE = 10
_CURRENT_NODE_SIZE = 14

# Change type → THEME color mapping
_TYPE_COLORS: dict[str, str] = {
    "initial_load": THEME.version_type_initial,
    "gap_fill": THEME.version_type_gap_fill,
    "manual_edit": THEME.version_type_manual_edit,
    "restore": THEME.version_type_restore,
}


class VersionGraphWidget(QWidget):
    """PyQtGraph-based version history graph visualization.

    Displays ModelVersion nodes connected by parent→child edges.
    Supports click-to-select, hover tooltips, and current version highlight.
    """

    version_selected = Signal(str)  # version_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._versions: list[ModelVersion] = []
        self._current_version_id: str | None = None
        # version_id → (x, y) coordinate mapping
        self._positions: dict[str, tuple[float, float]] = {}
        # Reference to the scatter plot item for highlight updates
        self._scatter: object | None = None
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not HAS_PYQTGRAPH:
            layout.addWidget(QLabel("PyQtGraph not installed — graph unavailable"))
            return

        pg.setConfigOptions(
            antialias=True,
            background=THEME.graph_bg,
            foreground=THEME.chart_fg,
        )

        self._plot = pg.PlotWidget()
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.getPlotItem().hideAxis("bottom")
        self._plot.getPlotItem().hideAxis("left")
        self._plot.setMenuEnabled(False)

        layout.addWidget(self._plot)

        self._legend = QLabel(self._build_legend_html())
        self._legend.setTextFormat(Qt.TextFormat.RichText)
        self._legend.setStyleSheet(
            f"color: {THEME.muted_text}; font-size: 11px; padding: 2px 4px;"
        )
        self._legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._legend)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_versions(
        self,
        versions: list[ModelVersion],
        current_version_id: str | None = None,
    ) -> None:
        """Set version data and rebuild the graph."""
        self._versions = list(versions)
        self._current_version_id = current_version_id
        self._rebuild_graph()

    def highlight_version(self, version_id: str) -> None:
        """Highlight a specific version node (for table sync)."""
        if not HAS_PYQTGRAPH or not self._versions:
            return
        self._rebuild_graph(highlight_id=version_id)

    def clear(self) -> None:
        """Clear all graph data."""
        self._versions.clear()
        self._current_version_id = None
        self._positions.clear()
        if HAS_PYQTGRAPH and hasattr(self, "_plot"):
            self._plot.clear()
            self._plot.setTitle("No versions")

    # ------------------------------------------------------------------
    # Graph building
    # ------------------------------------------------------------------

    def _rebuild_graph(self, highlight_id: str | None = None) -> None:
        """Rebuild the entire graph from self._versions."""
        can_render = HAS_PYQTGRAPH and hasattr(self, "_plot")
        if can_render:
            self._plot.clear()
            self._plot.setTitle("")
        self._scatter = None

        if not self._versions:
            self._positions.clear()
            if can_render:
                self._plot.setTitle("No versions")
            return

        # 1. Sort by timestamp (oldest first)
        sorted_versions = sorted(self._versions, key=lambda v: v.timestamp)

        # 2. Build parent→children map and assign coordinates
        self._positions = {}
        vid_to_version: dict[str, ModelVersion] = {}
        parent_children: dict[str, list[str]] = {}

        for v in sorted_versions:
            vid_to_version[v.version_id] = v
            if v.parent_version_id:
                parent_children.setdefault(v.parent_version_id, []).append(v.version_id)

        # 3. Assign X (time index) and Y (lane) coordinates
        lane_counter = 0
        vid_lane: dict[str, int] = {}

        for i, v in enumerate(sorted_versions):
            x = float(i)

            if v.change_type == "initial_load" or v.parent_version_id is None:
                # Main branch or orphan
                if v.version_id not in vid_lane:
                    vid_lane[v.version_id] = 0
            else:
                parent_id = v.parent_version_id
                parent_lane = vid_lane.get(parent_id, 0)
                children_of_parent = parent_children.get(parent_id, [])

                if len(children_of_parent) <= 1:
                    # Single child — same lane as parent
                    vid_lane[v.version_id] = parent_lane
                else:
                    # Branch — first child stays on parent lane, others get new lanes
                    child_idx = children_of_parent.index(v.version_id)
                    if child_idx == 0:
                        vid_lane[v.version_id] = parent_lane
                    else:
                        lane_counter += 1
                        vid_lane[v.version_id] = lane_counter

            y = float(vid_lane.get(v.version_id, 0))
            self._positions[v.version_id] = (x, y)

        if not can_render:
            return

        # 4. Draw edges (parent → child)
        for v in sorted_versions:
            if v.parent_version_id and v.parent_version_id in self._positions:
                px, py = self._positions[v.parent_version_id]
                cx, cy = self._positions[v.version_id]

                if py == cy:
                    # Same lane — straight line
                    self._plot.plot(
                        [px, cx],
                        [py, cy],
                        pen=pg.mkPen(THEME.graph_edge, width=2),
                    )
                else:
                    # Different lane — L-shaped connector
                    mid_x = (px + cx) / 2
                    self._plot.plot(
                        [px, mid_x, mid_x, cx],
                        [py, py, cy, cy],
                        pen=pg.mkPen(THEME.graph_edge, width=2),
                    )

            # Restore dotted line (restore node → source version it restores from)
            if v.change_type == "restore" and v.description:
                # Try to find restored version reference in description
                for other_v in sorted_versions:
                    if (
                        other_v.version_id != v.version_id
                        and other_v.version_id in v.description
                        and other_v.version_id in self._positions
                    ):
                        rx, ry = self._positions[other_v.version_id]
                        vx, vy = self._positions[v.version_id]
                        self._plot.plot(
                            [vx, rx],
                            [vy, ry],
                            pen=pg.mkPen(
                                THEME.graph_edge_restore,
                                width=1,
                                style=Qt.PenStyle.DashLine,
                            ),
                        )
                        break

        # 5. Draw nodes (ScatterPlotItem)
        spots = []
        for v in sorted_versions:
            x, y = self._positions[v.version_id]
            is_current = v.version_id == self._current_version_id
            is_highlighted = v.version_id == highlight_id

            color = _TYPE_COLORS.get(v.change_type, THEME.version_type_initial)
            size = _CURRENT_NODE_SIZE if is_current else _NODE_SIZE

            if is_current or is_highlighted:
                border_pen = pg.mkPen(THEME.graph_current_border, width=2)
            else:
                border_pen = pg.mkPen(color, width=1)

            spots.append({
                "pos": (x, y),
                "size": size,
                "pen": border_pen,
                "brush": pg.mkBrush(color),
                "symbol": "o",
                "data": v.version_id,
            })

        scatter = pg.ScatterPlotItem()
        scatter.addPoints(spots)
        scatter.sigClicked.connect(self._on_node_clicked)
        self._plot.addItem(scatter)
        self._scatter = scatter

        # 6. Add version labels below nodes
        for v in sorted_versions:
            x, y = self._positions[v.version_id]
            short_id = v.version_id[:8] if len(v.version_id) > 8 else v.version_id
            text = pg.TextItem(short_id, color=THEME.chart_fg, anchor=(0.5, 0))
            text.setPos(x, y - 0.4)
            font = text.textItem.font()
            font.setPointSize(8)
            text.setFont(font)
            self._plot.addItem(text)

        # 7. Auto-range with padding
        self._plot.autoRange(padding=0.15)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_node_clicked(self, _scatter: object, points: list, ev: object = None) -> None:
        """Handle scatter node click."""
        if points:
            version_id = points[0].data()
            if version_id:
                self.version_selected.emit(version_id)
                # Show tooltip on click
                tip = ""
                for v in self._versions:
                    if v.version_id == version_id:
                        tip = self._build_tooltip(v)
                        break
                if tip:
                    self.setToolTip(tip)

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------

    @staticmethod
    def _build_legend_html() -> str:
        """Build a compact rich-text legend for the graph colors."""
        entries = [
            ("Initial", THEME.version_type_initial),
            ("Gap-fill", THEME.version_type_gap_fill),
            ("Manual edit", THEME.version_type_manual_edit),
            ("Restore", THEME.version_type_restore),
            ("Current", THEME.graph_current_border),
        ]
        parts = []
        for label, color in entries:
            parts.append(
                f'<span style="color:{color}; font-weight:bold;">●</span> {label}'
            )
        parts.append(
            f'<span style="color:{THEME.graph_edge_restore};">- - -</span> restore source'
        )
        return "&nbsp;&nbsp;".join(parts)

    @staticmethod
    def _build_tooltip(version: ModelVersion) -> str:
        """Build a plain-text tooltip for a version node."""
        lines = [
            f"Version: {version.version_id}",
            f"Type: {version.change_type}",
            f"Date: {version.timestamp}",
        ]
        if version.parent_version_id:
            lines.append(f"Parent: {version.parent_version_id}")

        diff = version.diff
        if diff and not diff.is_empty:
            lines.append(diff.compact_summary)

        if version.task_pass_rate:
            lines.append(f"QC: {version.task_pass_rate}")

        if version.description:
            desc = version.description
            if len(desc) > 60:
                desc = desc[:57] + "..."
            lines.append(f"Desc: {desc}")

        return "\n".join(lines)
