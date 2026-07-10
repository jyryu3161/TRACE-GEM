"""Custom delegates for table cell rendering."""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from src.gui.theme import THEME, evidence_tier_color, score_color


class ScoreBarDelegate(QStyledItemDelegate):
    """Renders a color-coded score bar in a table cell."""

    def paint(  # type: ignore[override]
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        value = index.data(Qt.ItemDataRole.DisplayRole)
        if value is None or value == "":
            super().paint(painter, option, index)
            return

        try:
            score = float(value)
        except (ValueError, TypeError):
            self._paint_tier(painter, option, str(value))
            return

        view_option = cast(Any, option)  # PySide stubs omit inherited style attributes.
        painter.save()

        # Draw background
        if view_option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(view_option.rect, view_option.palette.highlight())
        else:
            painter.fillRect(view_option.rect, view_option.palette.base())

        # Score bar dimensions
        margin = 4
        bar_rect = QRect(
            view_option.rect.left() + margin,
            view_option.rect.top() + margin,
            view_option.rect.width() - 2 * margin,
            view_option.rect.height() - 2 * margin,
        )

        # Background bar
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(THEME.score_bar_bg)))
        painter.drawRoundedRect(bar_rect, 3, 3)

        # Score bar (colored)
        if score > 0:
            color = QColor(score_color(score))
            fill_width = int(bar_rect.width() * score)
            fill_rect = QRect(
                bar_rect.left(),
                bar_rect.top(),
                max(fill_width, 6),
                bar_rect.height(),
            )
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(fill_rect, 3, 3)

        # Score text
        text = f"{score:.2f}"
        text_color = (
            QColor(THEME.score_text_light) if score > 0.5 else QColor(THEME.score_text_dark)
        )
        painter.setPen(QPen(text_color))
        painter.drawText(bar_rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()

    def _paint_tier(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        value: str,
    ) -> None:
        view_option = cast(Any, option)  # PySide stubs omit inherited style attributes.
        painter.save()
        if view_option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(view_option.rect, view_option.palette.highlight())
        else:
            painter.fillRect(view_option.rect, view_option.palette.base())

        margin = 5
        badge_rect = QRect(
            view_option.rect.left() + margin,
            view_option.rect.top() + margin,
            view_option.rect.width() - 2 * margin,
            view_option.rect.height() - 2 * margin,
        )
        color = QColor(evidence_tier_color(value))
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(color.lighter(175)))
        painter.drawRoundedRect(badge_rect, 4, 4)

        painter.setPen(QPen(QColor(THEME.text)))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, value)
        painter.restore()
