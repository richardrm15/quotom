from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QPen


def set_pen_width(painter: QPainter, color: QColor, width: float):
    painter.setPen(
        QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )


def draw_poly(painter: QPainter, points: list[tuple[float, float]]):
    painter.drawPolyline([QPointF(x, y) for x, y in points])


def draw_lines(painter: QPainter, segments: list[tuple[float, float, float, float]]):
    for x1, y1, x2, y2 in segments:
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def render_icon(draw_func, color_hex: str = "#CCCCCC", size: int = 20, default_width: float = 1.8) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if size != 20:
        scale_val = size / 20.0
        painter.scale(scale_val, scale_val)

    color = QColor(color_hex)
    painter.setPen(
        QPen(color, default_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)

    draw_func(painter, color)
    painter.end()

    return QIcon(pixmap)