from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QPainter, QPainterPath, QBrush, QColor
from .base import draw_lines, set_pen_width


def draw_select(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.2)
    painter.setBrush(QBrush(color))
    path = QPainterPath()
    path.moveTo(4.5, 3.5)
    path.lineTo(4.5, 16.5)
    path.lineTo(8.0, 13.0)
    path.lineTo(11.0, 18.0)
    path.lineTo(13.0, 17.0)
    path.lineTo(10.0, 12.0)
    path.lineTo(14.0, 12.0)
    path.closeSubpath()
    painter.drawPath(path)


def draw_line(painter: QPainter, _):
    painter.drawLine(QPointF(4, 15), QPointF(16, 5))


def draw_arrow(painter: QPainter, _):
    painter.drawLine(QPointF(4, 15), QPointF(15, 5))
    head = QPainterPath()
    head.moveTo(10, 5)
    head.lineTo(15, 5)
    head.lineTo(15, 10)
    painter.drawPath(head)


def draw_rect(painter: QPainter, _):
    painter.drawRoundedRect(QRectF(3.5, 4.5, 13.0, 11.0), 1.5, 1.5)


def draw_circle(painter: QPainter, _):
    painter.drawEllipse(QRectF(3.5, 3.5, 13.0, 13.0))


def draw_cloud(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    path = QPainterPath()
    path.moveTo(4.5, 13.5)
    path.cubicTo(2.5, 11.5, 3.0, 7.5, 6.5, 7.5)
    path.cubicTo(7.0, 4.5, 12.0, 4.0, 14.0, 6.5)
    path.cubicTo(17.5, 6.5, 18.0, 10.5, 16.5, 13.0)
    path.cubicTo(16.5, 15.5, 13.0, 16.5, 10.5, 15.0)
    path.cubicTo(8.5, 16.5, 4.5, 16.0, 4.5, 13.5)
    painter.drawPath(path)


def draw_text(painter: QPainter, _):
    draw_lines(painter, [(4.0, 5.0, 16.0, 5.0), (10.0, 5.0, 10.0, 16.0)])


def draw_callout(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    painter.drawRoundedRect(QRectF(3.5, 3.5, 13.0, 9.0), 1.5, 1.5)
    path = QPainterPath()
    path.moveTo(6.5, 12.5)
    path.lineTo(4.5, 16.5)
    path.lineTo(10.5, 12.5)
    painter.drawPath(path)


def draw_text_select(painter: QPainter, _):
    draw_lines(painter, [
        (5.0, 5.0, 15.0, 5.0),
        (10.0, 5.0, 10.0, 15.0),
        (6.0, 15.0, 14.0, 15.0),
    ])


EDITOR_ICONS = {
    "select": draw_select,
    "pointer": draw_select,
    "line": draw_line,
    "arrow": draw_arrow,
    "rect": draw_rect,
    "square": draw_rect,
    "circle": draw_circle,
    "cloud": draw_cloud,
    "text": draw_text,
    "callout": draw_callout,
    "text-select": draw_text_select,
    "cursor-text": draw_text_select,
    "cursor": draw_select,
    "type": draw_text_select,
    "text_select": draw_text_select,
}