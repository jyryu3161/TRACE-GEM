"""Centralized theme system for MetaTaskGapFill GUI.

Strategy: Fusion style + QPalette + minimal QSS.
1. Fusion style — identical rendering on Windows/Mac/Linux.
2. QPalette — explicit color roles override OS theme completely.
3. Minimal QSS — only for border-radius, padding, pseudo-states.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeColors:
    """Single source of truth for all application colors."""

    # --- Base palette ---
    window: str = "#f5f5f5"
    window_text: str = "#2c3e50"
    base: str = "#ffffff"
    alternate_base: str = "#fafafa"
    text: str = "#2c3e50"
    button: str = "#ecf0f1"
    button_text: str = "#2c3e50"
    highlight: str = "#3498db"
    highlight_text: str = "#ffffff"
    link: str = "#2980b9"
    placeholder_text: str = "#95a5a6"
    disabled: str = "#bdc3c7"

    # --- Borders ---
    border: str = "#cccccc"
    border_light: str = "#e0e0e0"
    border_focus: str = "#3498db"

    # --- Semantic colors ---
    primary: str = "#3498db"
    primary_hover: str = "#2980b9"
    primary_pressed: str = "#2471a3"
    success: str = "#27ae60"
    success_hover: str = "#219a52"
    warning: str = "#f39c12"
    error: str = "#e74c3c"
    neutral: str = "#95a5a6"

    # --- Score colors ---
    score_high: str = "#27ae60"
    score_mid: str = "#f39c12"
    score_low: str = "#e74c3c"
    score_none: str = "#bdc3c7"
    score_bar_bg: str = "#ecf0f1"
    score_text_light: str = "#ffffff"
    score_text_dark: str = "#2c3e50"

    # --- Status colors ---
    status_pending: str = "#95a5a6"
    status_in_progress: str = "#3498db"
    status_evaluated: str = "#27ae60"
    status_error: str = "#e74c3c"

    # --- Strength colors ---
    strength_strong: str = "#2ecc71"
    strength_moderate: str = "#f1c40f"
    strength_weak: str = "#e67e22"
    strength_absent: str = "#e74c3c"

    # --- Chart colors ---
    chart_primary: str = "#3498db"
    chart_secondary: str = "#9b59b6"
    chart_pen: str = "#2c3e50"
    chart_bg: str = "#ffffff"
    chart_fg: str = "#2c3e50"

    # --- Source colors (per evidence source) ---
    source_kegg: str = "#3498db"  # Blue
    source_bigg: str = "#2ecc71"  # Green

    # --- HTML evidence ---
    evidence_item_bg: str = "#f9f9f9"
    muted_text: str = "#7f8c8d"

    # --- Version tracking ---
    version_current_bg: str = "#eaf4fc"
    version_type_initial: str = "#95a5a6"
    version_type_gap_fill: str = "#27ae60"
    version_type_manual_edit: str = "#3498db"
    version_type_restore: str = "#f39c12"
    diff_addition: str = "#27ae60"
    diff_removal: str = "#e74c3c"
    diff_modification: str = "#f39c12"

    # --- Version graph ---
    graph_edge: str = "#bdc3c7"
    graph_edge_restore: str = "#f39c12"
    graph_current_border: str = "#2c3e50"
    graph_bg: str = "#ffffff"


THEME = ThemeColors()


def build_palette(colors: ThemeColors) -> QPalette:
    """Build a QPalette that explicitly sets every color role.

    Covers Active, Inactive, and Disabled groups to fully override
    the OS theme (including macOS dark mode).
    """
    palette = QPalette()

    # Active and Inactive share the same colors
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, QColor(colors.window))
        palette.setColor(group, QPalette.ColorRole.WindowText, QColor(colors.window_text))
        palette.setColor(group, QPalette.ColorRole.Base, QColor(colors.base))
        palette.setColor(group, QPalette.ColorRole.AlternateBase, QColor(colors.alternate_base))
        palette.setColor(group, QPalette.ColorRole.Text, QColor(colors.text))
        palette.setColor(group, QPalette.ColorRole.Button, QColor(colors.button))
        palette.setColor(group, QPalette.ColorRole.ButtonText, QColor(colors.button_text))
        palette.setColor(group, QPalette.ColorRole.Highlight, QColor(colors.highlight))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(colors.highlight_text))
        palette.setColor(group, QPalette.ColorRole.Link, QColor(colors.link))
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, QColor(colors.placeholder_text))
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, QColor(colors.base))
        palette.setColor(group, QPalette.ColorRole.ToolTipText, QColor(colors.text))
        palette.setColor(group, QPalette.ColorRole.BrightText, QColor(colors.highlight_text))
        palette.setColor(group, QPalette.ColorRole.Light, QColor(colors.base))
        palette.setColor(group, QPalette.ColorRole.Midlight, QColor(colors.alternate_base))
        palette.setColor(group, QPalette.ColorRole.Mid, QColor(colors.border))
        palette.setColor(group, QPalette.ColorRole.Dark, QColor(colors.border_light))
        palette.setColor(group, QPalette.ColorRole.Shadow, QColor(colors.border))

    # Disabled group — muted variants
    disabled_group = QPalette.ColorGroup.Disabled
    palette.setColor(disabled_group, QPalette.ColorRole.Window, QColor(colors.window))
    palette.setColor(disabled_group, QPalette.ColorRole.WindowText, QColor(colors.disabled))
    palette.setColor(disabled_group, QPalette.ColorRole.Base, QColor(colors.alternate_base))
    palette.setColor(
        disabled_group, QPalette.ColorRole.AlternateBase, QColor(colors.alternate_base)
    )
    palette.setColor(disabled_group, QPalette.ColorRole.Text, QColor(colors.disabled))
    palette.setColor(disabled_group, QPalette.ColorRole.Button, QColor(colors.button))
    palette.setColor(disabled_group, QPalette.ColorRole.ButtonText, QColor(colors.disabled))
    palette.setColor(disabled_group, QPalette.ColorRole.Highlight, QColor(colors.disabled))
    palette.setColor(
        disabled_group, QPalette.ColorRole.HighlightedText, QColor(colors.highlight_text)
    )
    palette.setColor(disabled_group, QPalette.ColorRole.Link, QColor(colors.disabled))
    palette.setColor(disabled_group, QPalette.ColorRole.PlaceholderText, QColor(colors.disabled))

    return palette


def generate_stylesheet(colors: ThemeColors) -> str:
    """Generate minimal QSS that complements the QPalette.

    QPalette handles base colors for all widgets. QSS here only covers:
    - border-radius, padding, margins
    - pseudo-states (:hover, :pressed, :disabled, :selected, :focus)
    - specific widget overrides (object-name selectors)
    - widgets that QPalette doesn't fully style (QTextBrowser, QListWidget, etc.)
    """
    return f"""
/* --- GroupBox --- */
QGroupBox {{
    font-weight: bold;
    border: 1px solid {colors.border};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 16px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {colors.window_text};
}}

/* --- Table --- */
QTableView {{
    gridline-color: {colors.border_light};
    alternate-background-color: {colors.alternate_base};
}}
QTableView::item {{
    padding: 4px;
}}
QHeaderView::section {{
    background-color: {colors.button};
    padding: 6px;
    border: 1px solid {colors.border_light};
    font-weight: bold;
}}

/* --- Tabs --- */
QTabWidget::pane {{
    border: 1px solid {colors.border};
    border-radius: 4px;
}}
QTabBar::tab {{
    background: {colors.button};
    border: 1px solid {colors.border};
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: {colors.text};
}}
QTabBar::tab:selected {{
    background: {colors.base};
    border-bottom-color: {colors.base};
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {colors.primary};
    color: {colors.highlight_text};
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
}}
QPushButton:hover {{
    background-color: {colors.primary_hover};
}}
QPushButton:pressed {{
    background-color: {colors.primary_pressed};
}}
QPushButton:disabled {{
    background-color: {colors.disabled};
}}
QPushButton#evaluateAllBtn {{
    background-color: {colors.success};
    font-weight: bold;
}}
QPushButton#evaluateAllBtn:hover {{
    background-color: {colors.success_hover};
}}

/* --- Status Bar --- */
QStatusBar {{
    background-color: {colors.button};
}}

/* --- Progress Bar --- */
QProgressBar {{
    border: 1px solid {colors.disabled};
    border-radius: 4px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {colors.primary};
    border-radius: 3px;
}}

/* --- Line Edit --- */
QLineEdit {{
    border: 1px solid {colors.disabled};
    border-radius: 4px;
    padding: 8px;
    background-color: {colors.base};
    color: {colors.text};
}}
QLineEdit:focus {{
    border-color: {colors.border_focus};
}}

/* --- SpinBox --- */
QDoubleSpinBox, QSpinBox {{
    border: 1px solid {colors.disabled};
    border-radius: 4px;
    padding: 4px 6px;
    background-color: {colors.base};
    color: {colors.text};
}}
QDoubleSpinBox:focus, QSpinBox:focus {{
    border-color: {colors.border_focus};
}}

/* --- TextBrowser / ListWidget / ComboBox (dark-mode fix) --- */
QTextBrowser {{
    background-color: {colors.base};
    color: {colors.text};
    border: 1px solid {colors.border_light};
    border-radius: 2px;
}}
QListWidget {{
    background-color: {colors.base};
    color: {colors.text};
    border: 1px solid {colors.border_light};
}}
QListWidget::item:selected {{
    background-color: {colors.highlight};
    color: {colors.highlight_text};
}}
QComboBox {{
    background-color: {colors.base};
    color: {colors.text};
    border: 1px solid {colors.disabled};
    border-radius: 4px;
    padding: 4px 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {colors.base};
    color: {colors.text};
    selection-background-color: {colors.highlight};
    selection-color: {colors.highlight_text};
}}

/* --- Dialog --- */
QDialog {{
    background-color: {colors.window};
    color: {colors.text};
}}

/* --- Specific object-name selectors --- */
QLabel#scoreLabel {{
    font-size: 24px;
    font-weight: bold;
}}
QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: bold;
    color: {colors.window_text};
}}
"""


def score_color(score: float) -> str:
    """Map a confidence score to a hex color string.

    Used by delegates, evidence_panel, and score_visualization.
    """
    if score >= 0.7:
        return THEME.score_high
    elif score >= 0.4:
        return THEME.score_mid
    elif score > 0:
        return THEME.score_low
    return THEME.score_none


def evidence_tier_color(tier: str) -> str:
    """Map an evidence tier to a hex color string."""
    normalized = tier.lower()
    if normalized == "high":
        return THEME.score_high
    if normalized == "moderate":
        return THEME.score_mid
    if normalized == "low":
        return THEME.score_low
    return THEME.score_none


def apply_theme(app: QApplication) -> None:
    """Apply the full theme: Fusion style + QPalette + QSS.

    Call this after QApplication() but before showing any windows.
    """
    app.setStyle("Fusion")
    app.setPalette(build_palette(THEME))
    app.setStyleSheet(generate_stylesheet(THEME))

    # Ensure tooltips also respect the palette
    app.setAttribute(Qt.ApplicationAttribute.AA_UseStyleSheetPropagationInWidgetStyles, True)
