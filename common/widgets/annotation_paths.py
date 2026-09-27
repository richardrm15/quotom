# common/widgets/annotation_paths.py
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF


def generate_cloud_path(x: float, y: float, w: float, h: float, arc_size: float = 18.0) -> QPainterPath:
    """Genera una trayectoria matemática de arcos convexos continuos simulando nubes de revisión CAD."""
    path = QPainterPath()
    pts = [
        QPointF(x, y),
        QPointF(x + w, y),
        QPointF(x + w, y + h),
        QPointF(x, y + h),
    ]
    path.moveTo(pts[0])

    for i in range(len(pts)):
        p1 = pts[i]
        p2 = pts[(i + 1) % len(pts)]
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        seg_len = math.hypot(dx, dy)
        if seg_len < 1:
            continue

        num_arcs = max(1, int(round(seg_len / arc_size)))
        step_x = dx / num_arcs
        step_y = dy / num_arcs
        step_len = seg_len / num_arcs

        nx = dy / seg_len
        ny = -dx / seg_len

        curr = p1
        for j in range(num_arcs):
            next_pt = QPointF(p1.x() + (j + 1) * step_x, p1.y() + (j + 1) * step_y)
            mid = QPointF((curr.x() + next_pt.x()) / 2, (curr.y() + next_pt.y()) / 2)
            ctrl = QPointF(mid.x() + nx * (step_len * 0.45), mid.y() + ny * (step_len * 0.45))
            path.quadTo(ctrl, next_pt)
            curr = next_pt

    path.closeSubpath()
    return path


def build_rect_path(geometry: dict) -> QPainterPath:
    path = QPainterPath()
    x = float(geometry.get("x", 0))
    y = float(geometry.get("y", 0))
    w = float(geometry.get("w", 50))
    h = float(geometry.get("h", 50))
    norm_rect = QRectF(min(x, x + w), min(y, y + h), abs(w), abs(h))
    path.addRoundedRect(norm_rect, 2.0, 2.0)
    return path


def build_circle_path(geometry: dict) -> QPainterPath:
    path = QPainterPath()
    x = float(geometry.get("x", 0))
    y = float(geometry.get("y", 0))
    w = float(geometry.get("w", 50))
    h = float(geometry.get("h", 50))
    norm_rect = QRectF(min(x, x + w), min(y, y + h), abs(w), abs(h))
    path.addEllipse(norm_rect)
    return path


def build_line_path(geometry: dict) -> QPainterPath:
    path = QPainterPath()
    x1 = float(geometry.get("x1", 0))
    y1 = float(geometry.get("y1", 0))
    x2 = float(geometry.get("x2", 50))
    y2 = float(geometry.get("y2", 50))
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)
    return path


def build_arrow_path(geometry: dict) -> QPainterPath:
    path = QPainterPath()
    x1 = float(geometry.get("x1", 0))
    y1 = float(geometry.get("y1", 0))
    x2 = float(geometry.get("x2", 50))
    y2 = float(geometry.get("y2", 50))
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)

    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length > 2:
        ux = dx / length
        uy = dy / length
        head_len = min(18.0, max(8.0, length * 0.35))
        head_w = head_len * 0.45
        px = -uy
        py = ux
        bx = x2 - ux * head_len
        by = y2 - uy * head_len
        path.moveTo(bx + px * head_w, by + py * head_w)
        path.lineTo(x2, y2)
        path.lineTo(bx - px * head_w, by - py * head_w)
        path.closeSubpath()
    return path


def build_cloud_path(geometry: dict, arc_size: float = 18.0) -> QPainterPath:
    x = float(geometry.get("x", 0))
    y = float(geometry.get("y", 0))
    w = float(geometry.get("w", 100))
    h = float(geometry.get("h", 80))
    rx = min(x, x + w)
    ry = min(y, y + h)
    rw = max(20.0, abs(w))
    rh = max(20.0, abs(h))
    return generate_cloud_path(rx, ry, rw, rh, arc_size)


def build_text_path(geometry: dict, style_data: dict) -> tuple[QPainterPath, QRectF]:
    path = QPainterPath()
    x = float(geometry.get("x", 0))
    y = float(geometry.get("y", 0))
    w = max(30.0, float(geometry.get("w", 120)))
    h = max(24.0, float(geometry.get("h", 32)))
    norm_rect = QRectF(x, y, w, h)
    cx = x + w / 2.0
    cy = y + h / 2.0
    shape = style_data.get("shape", "rect")

    if shape in ("circle", "ellipse"):
        r = min(w, h) / 2.0
        path.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    elif shape == "hexagon":
        r = min(w / 2.0, h / 1.7320508075688772)
        dx = r * 0.5
        dy = r * 0.8660254037844386
        poly = QPolygonF([
            QPointF(cx - dx, cy - dy),
            QPointF(cx + dx, cy - dy),
            QPointF(cx + r, cy),
            QPointF(cx + dx, cy + dy),
            QPointF(cx - dx, cy + dy),
            QPointF(cx - r, cy),
        ])
        path.addPolygon(poly)
        path.closeSubpath()
    elif shape == "triangle":
        r = min(w / 1.7320508075688772, h / 1.5)
        dx = r * 0.8660254037844386
        dy = r * 0.75
        poly = QPolygonF([
            QPointF(cx, cy - dy),
            QPointF(cx + dx, cy + dy),
            QPointF(cx - dx, cy + dy),
        ])
        path.addPolygon(poly)
        path.closeSubpath()
    else:
        path.addRect(norm_rect)

    return path, norm_rect


def build_callout_path(geometry: dict) -> tuple[QPainterPath, QRectF, QPointF, QPointF, QPointF, list[QPointF]]:
    path = QPainterPath()
    ax = float(geometry.get("anchor_x", 0))
    ay = float(geometry.get("anchor_y", 0))
    bx = float(geometry.get("box_x", ax + 40))
    by = float(geometry.get("box_y", ay + 30))
    bw = float(geometry.get("box_w", 120))
    bh = float(geometry.get("box_h", 36))

    box_rect = QRectF(min(bx, bx + bw), min(by, by + bh), max(40.0, abs(bw)), max(24.0, abs(bh)))
    b_left = box_rect.left()
    b_right = box_rect.right()
    b_top = box_rect.top()
    b_bottom = box_rect.bottom()
    b_cy = box_rect.center().y()

    if ax >= b_right:
        p_box_edge = QPointF(b_right, b_cy)
        p_knee = QPointF(b_right + 15.0, b_cy) if (ax - b_right > 25.0) else p_box_edge
    elif ax <= b_left:
        p_box_edge = QPointF(b_left, b_cy)
        p_knee = QPointF(b_left - 15.0, b_cy) if (b_left - ax > 25.0) else p_box_edge
    elif ay <= b_top:
        p_box_edge = QPointF(ax, b_top)
        p_knee = p_box_edge
    else:
        p_box_edge = QPointF(ax, b_bottom)
        p_knee = p_box_edge

    p_anchor = QPointF(ax, ay)
    dx = p_knee.x() - ax
    dy = p_knee.y() - ay
    dist = math.hypot(dx, dy)
    if dist > 2.0:
        ux = dx / dist
        uy = dy / dist
        head_len = 10.0
        head_w = 4.5
        nx = -uy
        ny = ux
        base_x = ax + ux * head_len
        base_y = ay + uy * head_len
        arrow_poly = [QPointF(ax, ay), QPointF(base_x + nx * head_w, base_y + ny * head_w), QPointF(base_x - nx * head_w, base_y - ny * head_w)]
    else:
        arrow_poly = []

    path.addRoundedRect(box_rect, 3.0, 3.0)
    path.moveTo(ax, ay)
    path.lineTo(p_knee)
    path.lineTo(p_box_edge)
    if arrow_poly:
        path.moveTo(arrow_poly[1])
        path.lineTo(arrow_poly[0])
        path.lineTo(arrow_poly[2])

    return path, box_rect, p_box_edge, p_knee, p_anchor, arrow_poly
