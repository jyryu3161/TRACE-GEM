"""Tests for the centralized theme system."""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError

import pytest
from PySide6.QtGui import QColor, QPalette

from src.gui.theme import THEME, ThemeColors, build_palette, generate_stylesheet, score_color

HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


class TestThemeColors:
    """Tests for the ThemeColors dataclass."""

    def test_frozen(self) -> None:
        with pytest.raises(FrozenInstanceError):
            THEME.window = "#000000"  # type: ignore[misc]

    def test_all_colors_are_valid_hex(self) -> None:
        for field_name in ThemeColors.__dataclass_fields__:
            value = getattr(THEME, field_name)
            assert HEX_PATTERN.match(value), (
                f"ThemeColors.{field_name} = {value!r} is not a valid hex color"
            )

    def test_all_colors_are_valid_qcolors(self) -> None:
        for field_name in ThemeColors.__dataclass_fields__:
            value = getattr(THEME, field_name)
            qcolor = QColor(value)
            assert qcolor.isValid(), f"ThemeColors.{field_name} = {value!r} is not a valid QColor"

    def test_default_instance_exists(self) -> None:
        assert isinstance(THEME, ThemeColors)


class TestBuildPalette:
    """Tests for build_palette()."""

    def test_returns_qpalette(self) -> None:
        palette = build_palette(THEME)
        assert isinstance(palette, QPalette)

    def test_window_color_matches(self) -> None:
        palette = build_palette(THEME)
        actual = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
        expected = QColor(THEME.window)
        assert actual == expected

    def test_base_color_matches(self) -> None:
        palette = build_palette(THEME)
        actual = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Base)
        expected = QColor(THEME.base)
        assert actual == expected

    def test_text_color_matches(self) -> None:
        palette = build_palette(THEME)
        actual = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)
        expected = QColor(THEME.text)
        assert actual == expected

    def test_disabled_text_is_muted(self) -> None:
        palette = build_palette(THEME)
        active_text = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Text)
        disabled_text = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        assert active_text != disabled_text

    def test_inactive_matches_active(self) -> None:
        palette = build_palette(THEME)
        active = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
        inactive = palette.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Window)
        assert active == inactive


class TestScoreColor:
    """Tests for score_color() boundary values."""

    def test_zero_returns_none_color(self) -> None:
        assert score_color(0.0) == THEME.score_none

    def test_low_score(self) -> None:
        assert score_color(0.1) == THEME.score_low

    def test_boundary_0_4(self) -> None:
        assert score_color(0.4) == THEME.score_mid

    def test_below_0_4(self) -> None:
        assert score_color(0.39) == THEME.score_low

    def test_boundary_0_7(self) -> None:
        assert score_color(0.7) == THEME.score_high

    def test_below_0_7(self) -> None:
        assert score_color(0.69) == THEME.score_mid

    def test_max_score(self) -> None:
        assert score_color(1.0) == THEME.score_high

    def test_returns_valid_hex(self) -> None:
        for s in [0.0, 0.1, 0.4, 0.7, 1.0]:
            result = score_color(s)
            assert HEX_PATTERN.match(result), f"score_color({s}) = {result!r}"


class TestGenerateStylesheet:
    """Tests for generate_stylesheet()."""

    def test_returns_string(self) -> None:
        result = generate_stylesheet(THEME)
        assert isinstance(result, str)

    def test_not_empty(self) -> None:
        result = generate_stylesheet(THEME)
        assert len(result) > 100

    def test_contains_text_browser_rule(self) -> None:
        result = generate_stylesheet(THEME)
        assert "QTextBrowser" in result

    def test_contains_list_widget_rule(self) -> None:
        result = generate_stylesheet(THEME)
        assert "QListWidget" in result

    def test_contains_combo_box_rule(self) -> None:
        result = generate_stylesheet(THEME)
        assert "QComboBox" in result

    def test_contains_dialog_rule(self) -> None:
        result = generate_stylesheet(THEME)
        assert "QDialog" in result

    def test_contains_group_box_title(self) -> None:
        result = generate_stylesheet(THEME)
        assert "QGroupBox::title" in result

    def test_contains_evaluate_btn(self) -> None:
        result = generate_stylesheet(THEME)
        assert "#evaluateAllBtn" in result

    def test_contains_score_label(self) -> None:
        result = generate_stylesheet(THEME)
        assert "#scoreLabel" in result

    def test_contains_section_title(self) -> None:
        result = generate_stylesheet(THEME)
        assert "#sectionTitle" in result

    def test_uses_theme_colors(self) -> None:
        result = generate_stylesheet(THEME)
        assert THEME.primary in result
        assert THEME.border in result
        assert THEME.base in result
