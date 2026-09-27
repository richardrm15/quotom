from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QColor
from .base import draw_lines, draw_poly, set_pen_width


def draw_chevron_left(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 2.0)
    draw_poly(painter, [(12.5, 5.0), (7.5, 10.0), (12.5, 15.0)])


def draw_chevron_right(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 2.0)
    draw_poly(painter, [(7.5, 5.0), (12.5, 10.0), (7.5, 15.0)])


def draw_arrow_left(painter: QPainter, _):
    draw_lines(painter, [
        (16.0, 10.0, 4.0, 10.0),
        (9.5, 5.0, 4.0, 10.0),
        (9.5, 15.0, 4.0, 10.0),
    ])


def draw_zoom_in(painter: QPainter, _):
    painter.drawEllipse(QRectF(3.0, 3.0, 10.5, 10.5))
    draw_lines(painter, [
        (11.0, 11.0, 17.5, 17.5),
        (8.25, 5.5, 8.25, 11.0),
        (5.5, 8.25, 11.0, 8.25),
    ])


def draw_zoom_out(painter: QPainter, _):
    painter.drawEllipse(QRectF(3.0, 3.0, 10.5, 10.5))
    draw_lines(painter, [
        (11.0, 11.0, 17.5, 17.5),
        (5.5, 8.25, 11.0, 8.25),
    ])


def draw_fit_window(painter: QPainter, _):
    draw_lines(painter, [
        (12.5, 3.0, 17.0, 3.0),
        (17.0, 3.0, 17.0, 7.5),
        (17.0, 3.0, 12.0, 8.0),
        (7.5, 17.0, 3.0, 17.0),
        (3.0, 17.0, 3.0, 12.5),
        (3.0, 17.0, 8.0, 12.0),
    ])


def draw_hand(painter: QPainter, color: QColor):
    set_pen_width(painter, color, 1.6)
    draw_poly(painter, [
        (5, 14), (5, 9), (7, 8), (7, 13), (9, 7), (11, 7),
        (11, 13), (13, 8), (15, 8), (15, 14), (15, 17),
        (12, 19), (7, 19), (5, 16), (5, 14),
    ])


NAVIGATION_ICONS = {
    "chevron-left": draw_chevron_left,
    "chevron-right": draw_chevron_right,
    "arrow-left": draw_arrow_left,
    "zoom-in": draw_zoom_in,
    "zoom-out": draw_zoom_out,
    "fit-window": draw_fit_window,
    "maximize": draw_fit_window,
    "hand": draw_hand,
    "pan": draw_hand,
}