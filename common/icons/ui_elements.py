from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QColor
from .base import draw_lines, set_pen_width


def draw_folder(painter: QPainter, _):
    tab = QPainterPath()
    tab.moveTo(2.0, 4.5)
    tab.lineTo(2.0, 2.2)
    tab.lineTo(7.5, 2.2)
    tab.lineTo(9.5, 4.5)
    tab.lineTo(18.0, 4.5)
    painter.drawPath(tab)

    body = QPainterPath()
    body.moveTo(2.0, 4.5)
    body.lineTo(18.0, 4.5)
    body.lineTo(18.0, 14.5)
    body.lineTo(2.0, 14.5)
    body.closeSubpath()
    painter.drawPath(body)


def draw_file_pdf(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    path = QPainterPath()
    path.moveTo(4.0, 2.5)
    path.lineTo(12.0, 2.5)
    path.lineTo(16.0, 6.5)
    path.lineTo(16.0, 17.5)
    path.lineTo(4.0, 17.5)
    path.closeSubpath()
    painter.drawPath(path)
    draw_lines(painter, [(12.0, 2.5, 12.0, 6.5), (12.0, 6.5, 16.0, 6.5)])


def draw_file_page(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.4)
    path = QPainterPath()
    path.moveTo(5.0, 3.0)
    path.lineTo(12.0, 3.0)
    path.lineTo(15.0, 6.0)
    path.lineTo(15.0, 17.0)
    path.lineTo(5.0, 17.0)
    path.closeSubpath()
    painter.drawPath(path)
    draw_lines(painter, [
        (12.0, 3.0, 12.0, 6.0),
        (12.0, 6.0, 15.0, 6.0),
        (7.5, 9.5, 12.5, 9.5),
        (7.5, 12.5, 12.5, 12.5),
    ])


def draw_list(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.5)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(3.0, 4.5, 2.0, 2.0))
    painter.drawEllipse(QRectF(3.0, 9.0, 2.0, 2.0))
    painter.drawEllipse(QRectF(3.0, 13.5, 2.0, 2.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw_lines(painter, [
        (7.5, 5.5, 17.0, 5.5),
        (7.5, 10.0, 17.0, 10.0),
        (7.5, 14.5, 17.0, 14.5),
    ])


def draw_sidebar(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    painter.drawRoundedRect(QRectF(2.5, 3.0, 15.0, 14.0), 2.0, 2.0)
    painter.drawLine(QPointF(7.5, 3.0), QPointF(7.5, 17.0))


def draw_pages_grid(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.5)
    painter.drawRoundedRect(QRectF(3.0, 3.0, 5.8, 5.8), 1.0, 1.0)
    painter.drawRoundedRect(QRectF(11.2, 3.0, 5.8, 5.8), 1.0, 1.0)
    painter.drawRoundedRect(QRectF(3.0, 11.2, 5.8, 5.8), 1.0, 1.0)
    painter.drawRoundedRect(QRectF(11.2, 11.2, 5.8, 5.8), 1.0, 1.0)


def draw_bookmark(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.5)
    path = QPainterPath()
    path.moveTo(5.5, 3.0)
    path.lineTo(14.5, 3.0)
    path.lineTo(14.5, 17.0)
    path.lineTo(10.0, 13.5)
    path.lineTo(5.5, 17.0)
    path.closeSubpath()
    painter.drawPath(path)


def draw_help(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    painter.drawEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
    path = QPainterPath()
    path.moveTo(7.5, 8.0)
    path.cubicTo(7.5, 5.5, 12.5, 5.5, 12.5, 8.0)
    path.cubicTo(12.5, 10.0, 10.0, 10.5, 10.0, 12.0)
    painter.drawPath(path)
    painter.drawLine(QPointF(10.0, 14.0), QPointF(10.0, 14.5))


def draw_sun(painter: QPainter, _):
    painter.drawEllipse(QRectF(6.0, 6.0, 8.0, 8.0))
    draw_lines(painter, [
        (10.0, 1.5, 10.0, 3.5),
        (10.0, 16.5, 10.0, 18.5),
        (1.5, 10.0, 3.5, 10.0),
        (16.5, 10.0, 18.5, 10.0),
        (4.0, 4.0, 5.5, 5.5),
        (14.5, 14.5, 16.0, 16.0),
        (4.0, 16.0, 5.5, 14.5),
        (14.5, 5.5, 16.0, 4.0),
    ])


def draw_moon(painter: QPainter, _):
    path = QPainterPath()
    path.moveTo(10.0, 2.5)
    path.cubicTo(15.0, 2.5, 17.5, 7.5, 16.5, 12.0)
    path.cubicTo(15.5, 15.5, 12.0, 17.5, 8.0, 17.5)
    path.cubicTo(6.0, 17.5, 4.5, 16.8, 3.5, 15.8)
    path.cubicTo(8.5, 15.8, 12.0, 12.0, 12.0, 7.0)
    path.cubicTo(12.0, 5.0, 11.0, 3.5, 10.0, 2.5)
    path.closeSubpath()
    painter.drawPath(path)


def draw_alert_triangle(painter: QPainter, color: QColor):
    """
    Triángulo de advertencia con signo de exclamación (avisos y alertas).

    Las esquinas quedan redondeadas por el ``RoundJoin`` del pincel, igual que en
    el resto de la fábrica. Sustituye al emoji de aviso, que no se adaptaba al tema.
    """
    set_pen_width(painter, color, 1.6)

    triangle = QPainterPath()
    triangle.moveTo(10.0, 2.6)
    triangle.lineTo(17.9, 16.6)
    triangle.lineTo(2.1, 16.6)
    triangle.closeSubpath()
    painter.drawPath(triangle)

    # Signo de exclamación: punto inferior + trazo vertical
    painter.setBrush(color)
    painter.drawEllipse(QRectF(9.2, 13.6, 1.6, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw_lines(painter, [(10.0, 7.2, 10.0, 11.8)])


UI_ICONS = {
    "folder-open": draw_folder,
    "file-pdf": draw_file_pdf,
    "file-page": draw_file_page,
    "list": draw_list,
    "sidebar": draw_sidebar,
    "pages-grid": draw_pages_grid,
    "layout": draw_pages_grid,
    "folder": draw_folder,
    "file-text": draw_file_page,
    "grid": draw_pages_grid,
    "bookmark": draw_bookmark,
    "help": draw_help,
    "alert-triangle": draw_alert_triangle,
    "sun": draw_sun,
    "moon": draw_moon,
}