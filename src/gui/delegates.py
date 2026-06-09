"""Custom delegates for table cell rendering."""

from __future__ import annotations

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

        painter.save()

        # Draw background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        # Score bar dimensions
        margin = 4
        bar_rect = QRect(
            option.rect.left() + margin,
            option.rect.top() + margin,
            option.rect.width() - 2 * margin,
            option.rect.height() - 2 * margin,
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
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        else:
            painter.fillRect(option.rect, option.palette.base())

        margin = 5
        badge_rect = QRect(
            option.rect.left() + margin,
            option.rect.top() + margin,
            option.rect.width() - 2 * margin,
            option.rect.height() - 2 * margin,
        )
        color = QColor(evidence_tier_color(value))
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(color.lighter(175)))
        painter.drawRoundedRect(badge_rect, 4, 4)

        painter.setPen(QPen(QColor(THEME.text)))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, value)
        painter.restore()


class StatusDelegate(QStyledItemDelegate):
    """Renders evaluation status with colored indicator."""

    STATUS_COLORS = {
        "not_evaluated": THEME.status_pending,
        "in_progress": THEME.status_in_progress,
        "evaluated": THEME.status_evaluated,
        "error": THEME.status_error,
    }

    STATUS_LABELS = {
        "not_evaluated": "Pending",
        "in_progress": "Evaluating...",
        "evaluated": "Done",
        "error": "Error",
    }

    def paint(  # type: ignore[override]
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        status = index.data(Qt.ItemDataRole.DisplayRole) or "not_evaluated"

        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Status dot
        dot_size = 8
        dot_x = option.rect.left() + 8
        dot_y = option.rect.center().y() - dot_size // 2

        color = QColor(self.STATUS_COLORS.get(status, THEME.status_pending))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)

        # Status text
        label = self.STATUS_LABELS.get(status, status)
        text_rect = QRect(
            dot_x + dot_size + 6,
            option.rect.top(),
            option.rect.width() - dot_size - 20,
            option.rect.height(),
        )
        painter.setPen(QPen(QColor(THEME.text)))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, label)

        painter.restore()
