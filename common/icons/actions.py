from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QColor
from .base import draw_lines, set_pen_width


def draw_undo(painter: QPainter, _):
    head = QPainterPath()
    head.moveTo(6.5, 4.5)
    head.lineTo(3.0, 8.0)
    head.lineTo(6.5, 11.5)
    painter.drawPath(head)

    arc = QPainterPath()
    arc.moveTo(3.5, 8.0)
    arc.lineTo(10.0, 8.0)
    arc.cubicTo(15.0, 8.0, 17.0, 11.0, 17.0, 15.5)
    painter.drawPath(arc)


def draw_redo(painter: QPainter, _):
    head = QPainterPath()
    head.moveTo(13.5, 4.5)
    head.lineTo(17.0, 8.0)
    head.lineTo(13.5, 11.5)
    painter.drawPath(head)

    arc = QPainterPath()
    arc.moveTo(16.5, 8.0)
    arc.lineTo(10.0, 8.0)
    arc.cubicTo(5.0, 8.0, 3.0, 11.0, 3.0, 15.5)
    painter.drawPath(arc)


def draw_refresh(painter: QPainter, _):
    painter.drawArc(QRectF(3.5, 3.5, 13.0, 13.0), int(35 * 16), int(290 * 16))
    arrow = QPainterPath()
    arrow.moveTo(14.0, 2.5)
    arrow.lineTo(17.5, 6.0)
    arrow.lineTo(13.5, 7.5)
    painter.drawPath(arrow)


def draw_save(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.5)
    path = QPainterPath()
    path.moveTo(3.5, 3.0)
    path.lineTo(13.0, 3.0)
    path.lineTo(16.5, 6.5)
    path.lineTo(16.5, 17.0)
    path.lineTo(3.5, 17.0)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawRect(QRectF(6.5, 3.0, 5.5, 4.0))
    painter.drawRect(QRectF(5.5, 10.5, 9.0, 6.5))


def draw_copy(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.5)
    path_back = QPainterPath()
    path_back.moveTo(7.0, 3.0)
    path_back.lineTo(16.0, 3.0)
    path_back.lineTo(16.0, 12.5)
    painter.drawPath(path_back)
    painter.drawRoundedRect(QRectF(3.5, 6.0, 9.5, 11.0), 1.2, 1.2)


def draw_edit(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    path = QPainterPath()
    path.moveTo(3.0, 17.0)
    path.lineTo(7.0, 16.5)
    path.lineTo(16.0, 7.5)
    path.lineTo(12.5, 4.0)
    path.lineTo(3.5, 13.0)
    path.closeSubpath()
    painter.drawPath(path)
    draw_lines(painter, [(11.0, 5.5, 14.5, 9.0), (3.0, 17.0, 5.5, 14.5)])


def draw_trash(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    draw_lines(painter, [(3.0, 5.0, 17.0, 5.0), (7.0, 3.0, 13.0, 3.0)])
    path = QPainterPath()
    path.moveTo(5.0, 5.0)
    path.lineTo(6.0, 17.0)
    path.lineTo(14.0, 17.0)
    path.lineTo(15.0, 5.0)
    painter.drawPath(path)


def draw_plus(painter: QPainter, _):
    draw_lines(painter, [(10.0, 4.0, 10.0, 16.0), (4.0, 10.0, 16.0, 10.0)])


def draw_close(painter: QPainter, _):
    draw_lines(painter, [(6.0, 6.0, 14.0, 14.0), (14.0, 6.0, 6.0, 14.0)])


def draw_search(painter: QPainter, _):
    painter.drawEllipse(QRectF(4.0, 4.0, 9.0, 9.0))
    painter.drawLine(QPointF(11.0, 11.0), QPointF(16.0, 16.0))


ACTIONS_ICONS = {
    "save": draw_save,
    "copy": draw_copy,
    "duplicate": draw_copy,
    "edit": draw_edit,
    "trash": draw_trash,
    "plus": draw_plus,
    "close": draw_close,
    "search": draw_search,
    "undo": draw_undo,
    "redo": draw_redo,
    "refresh": draw_refresh,
}