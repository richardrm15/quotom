# common/widgets/annotation_handles.py
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush


def compute_handles(annot_type: str, geometry_data: dict, style_data: dict) -> dict[str, QPointF]:
    """Retorna las coordenadas locales de los tiradores de redimensionamiento disponibles."""
    t = annot_type
    if t == "text":
        x = float(geometry_data.get("x", 0))
        y = float(geometry_data.get("y", 0))
        w = max(30.0, float(geometry_data.get("w", 120)))
        h = max(24.0, float(geometry_data.get("h", 32)))
        shape = style_data.get("shape", "rect")
        cx = x + w / 2.0
        cy = y + h / 2.0

        if shape in ("circle", "ellipse"):
            r = min(w, h) / 2.0
            left, right = cx - r, cx + r
            top, bottom = cy - r, cy + r
        elif shape == "hexagon":
            r = min(w / 2.0, h / 1.7320508075688772)
            dy = r * 0.8660254037844386
            left, right = cx - r, cx + r
            top, bottom = cy - dy, cy + dy
        elif shape == "triangle":
            r = min(w / 1.7320508075688772, h / 1.5)
            dx = r * 0.8660254037844386
            dy = r * 0.75
            left, right = cx - dx, cx + dx
            top, bottom = cy - dy, cy + dy
        else:
            left, right = min(x, x + w), max(x, x + w)
            top, bottom = min(y, y + h), max(y, y + h)

        if shape in ("circle", "ellipse", "hexagon", "triangle"):
            return {
                "tl": QPointF(left, top),
                "tr": QPointF(right, top),
                "br": QPointF(right, bottom),
                "bl": QPointF(left, bottom),
            }
        else:
            return {
                "tl": QPointF(left, top),
                "tc": QPointF((left + right) / 2.0, top),
                "tr": QPointF(right, top),
                "mr": QPointF(right, (top + bottom) / 2.0),
                "br": QPointF(right, bottom),
                "bc": QPointF((left + right) / 2.0, bottom),
                "bl": QPointF(left, bottom),
                "ml": QPointF(left, (top + bottom) / 2.0),
            }

    elif t in ("rect", "circle", "cloud"):
        x = float(geometry_data.get("x", 0))
        y = float(geometry_data.get("y", 0))
        w = float(geometry_data.get("w", 50))
        h = float(geometry_data.get("h", 50))
        left, right = min(x, x + w), max(x, x + w)
        top, bottom = min(y, y + h), max(y, y + h)
        return {
            "tl": QPointF(left, top),
            "tr": QPointF(right, top),
            "br": QPointF(right, bottom),
            "bl": QPointF(left, bottom),
        }

    elif t in ("line", "arrow"):
        p1 = QPointF(float(geometry_data.get("x1", 0)), float(geometry_data.get("y1", 0)))
        p2 = QPointF(float(geometry_data.get("x2", 50)), float(geometry_data.get("y2", 50)))
        return {"p1": p1, "p2": p2}

    elif t == "callout":
        p_anchor = QPointF(float(geometry_data.get("anchor_x", 0)), float(geometry_data.get("anchor_y", 0)))
        bx = float(geometry_data.get("box_x", 0))
        by = float(geometry_data.get("box_y", 0))
        bw = float(geometry_data.get("box_w", 120))
        bh = float(geometry_data.get("box_h", 36))
        left, right = min(bx, bx + bw), max(bx, bx + bw)
        top, bottom = min(by, by + bh), max(by, by + bh)
        return {
            "anchor": p_anchor,
            "tl": QPointF(left, top),
            "tr": QPointF(right, top),
            "br": QPointF(right, bottom),
            "bl": QPointF(left, bottom),
        }

    return {}


def calculate_handle_resize(
    annot_type: str,
    orig_geom: dict,
    handle: str,
    cur_pos: QPointF,
    style_data: dict,
) -> dict:
    """Calcula la nueva geometría tras arrastrar un tirador interactivo con el ratón."""
    new_geom = dict(orig_geom)
    cur_x = cur_pos.x()
    cur_y = cur_pos.y()
    t = annot_type
    h = handle

    shape = style_data.get("shape", "rect")
    if t == "text" and shape in ("circle", "ellipse", "hexagon", "triangle"):
        ox = float(orig_geom.get("x", 0))
        oy = float(orig_geom.get("y", 0))
        ow = float(orig_geom.get("w", 50))
        oh = float(orig_geom.get("h", 50))

        ratio = 1.0 if shape in ("circle", "ellipse") else (2.0 / 1.7320508075688772)
        min_w = 32.0

        if h == "br":
            dx = max(min_w, cur_x - ox)
            dy = max(min_w / ratio, cur_y - oy)
            w = max(dx, dy * ratio)
            h_val = w / ratio
            new_geom["x"] = ox
            new_geom["y"] = oy
            new_geom["w"] = w
            new_geom["h"] = h_val
        elif h == "tr":
            dx = max(min_w, cur_x - ox)
            dy = max(min_w / ratio, (oy + oh) - cur_y)
            w = max(dx, dy * ratio)
            h_val = w / ratio
            new_geom["x"] = ox
            new_geom["y"] = (oy + oh) - h_val
            new_geom["w"] = w
            new_geom["h"] = h_val
        elif h == "bl":
            dx = max(min_w, (ox + ow) - cur_x)
            dy = max(min_w / ratio, cur_y - oy)
            w = max(dx, dy * ratio)
            h_val = w / ratio
            new_geom["x"] = (ox + ow) - w
            new_geom["y"] = oy
            new_geom["w"] = w
            new_geom["h"] = h_val
        elif h == "tl":
            dx = max(min_w, (ox + ow) - cur_x)
            dy = max(min_w / ratio, (oy + oh) - cur_y)
            w = max(dx, dy * ratio)
            h_val = w / ratio
            new_geom["x"] = (ox + ow) - w
            new_geom["y"] = (oy + oh) - h_val
            new_geom["w"] = w
            new_geom["h"] = h_val

    elif t in ("rect", "circle", "cloud", "text"):
        ox = float(orig_geom.get("x", 0))
        oy = float(orig_geom.get("y", 0))
        ow = float(orig_geom.get("w", 50))
        oh = float(orig_geom.get("h", 50))
        left = min(ox, ox + ow)
        top = min(oy, oy + oh)
        right = max(ox, ox + ow)
        bottom = max(oy, oy + oh)

        if h == "tl":
            new_left = min(cur_x, right - 10)
            new_top = min(cur_y, bottom - 10)
            new_geom["x"] = new_left
            new_geom["y"] = new_top
            new_geom["w"] = max(10.0, right - new_left)
            new_geom["h"] = max(10.0, bottom - new_top)
        elif h == "tc":
            new_top = min(cur_y, bottom - 10)
            new_geom["y"] = new_top
            new_geom["h"] = max(10.0, bottom - new_top)
        elif h == "tr":
            new_right = max(cur_x, left + 10)
            new_top = min(cur_y, bottom - 10)
            new_geom["x"] = left
            new_geom["y"] = new_top
            new_geom["w"] = max(10.0, new_right - left)
            new_geom["h"] = max(10.0, bottom - new_top)
        elif h == "mr":
            new_right = max(cur_x, left + 10)
            new_geom["w"] = max(10.0, new_right - left)
        elif h == "br":
            new_right = max(cur_x, left + 10)
            new_bottom = max(cur_y, top + 10)
            new_geom["x"] = left
            new_geom["y"] = top
            new_geom["w"] = max(10.0, new_right - left)
            new_geom["h"] = max(10.0, new_bottom - top)
        elif h == "bc":
            new_bottom = max(cur_y, top + 10)
            new_geom["h"] = max(10.0, new_bottom - top)
        elif h == "bl":
            new_left = min(cur_x, right - 10)
            new_bottom = max(cur_y, top + 10)
            new_geom["x"] = new_left
            new_geom["y"] = top
            new_geom["w"] = max(10.0, right - new_left)
            new_geom["h"] = max(10.0, new_bottom - top)
        elif h == "ml":
            new_left = min(cur_x, right - 10)
            new_geom["x"] = new_left
            new_geom["w"] = max(10.0, right - new_left)

    elif t in ("line", "arrow"):
        if h == "p1":
            new_geom["x1"] = cur_x
            new_geom["y1"] = cur_y
        elif h == "p2":
            new_geom["x2"] = cur_x
            new_geom["y2"] = cur_y

    elif t == "callout":
        if h == "anchor":
            new_geom["anchor_x"] = cur_x
            new_geom["anchor_y"] = cur_y
        else:
            bx = float(orig_geom.get("box_x", 0))
            by = float(orig_geom.get("box_y", 0))
            bw = float(orig_geom.get("box_w", 120))
            bh = float(orig_geom.get("box_h", 36))
            left = min(bx, bx + bw)
            top = min(by, by + bh)
            right = max(bx, bx + bw)
            bottom = max(by, by + bh)

            if h == "tl":
                new_left = min(cur_x, right - 20)
                new_top = min(cur_y, bottom - 15)
                new_geom["box_x"] = new_left
                new_geom["box_y"] = new_top
                new_geom["box_w"] = max(20.0, right - new_left)
                new_geom["box_h"] = max(15.0, bottom - new_top)
            elif h == "tc":
                new_top = min(cur_y, bottom - 15)
                new_geom["box_y"] = new_top
                new_geom["box_h"] = max(15.0, bottom - new_top)
            elif h == "tr":
                new_right = max(cur_x, left + 20)
                new_top = min(cur_y, bottom - 15)
                new_geom["box_x"] = left
                new_geom["box_y"] = new_top
                new_geom["box_w"] = max(20.0, new_right - left)
                new_geom["box_h"] = max(15.0, bottom - new_top)
            elif h == "mr":
                new_right = max(cur_x, left + 20)
                new_geom["box_w"] = max(20.0, new_right - left)
            elif h == "br":
                new_right = max(cur_x, left + 20)
                new_bottom = max(cur_y, top + 15)
                new_geom["box_x"] = left
                new_geom["box_y"] = top
                new_geom["box_w"] = max(20.0, new_right - left)
                new_geom["box_h"] = max(15.0, new_bottom - top)
            elif h == "bc":
                new_bottom = max(cur_y, top + 15)
                new_geom["box_h"] = max(15.0, new_bottom - top)
            elif h == "bl":
                new_left = min(cur_x, right - 20)
                new_bottom = max(cur_y, top + 15)
                new_geom["box_x"] = new_left
                new_geom["box_y"] = top
                new_geom["box_w"] = max(20.0, right - new_left)
                new_geom["box_h"] = max(15.0, new_bottom - top)
            elif h == "ml":
                new_left = min(cur_x, right - 20)
                new_geom["box_x"] = new_left
                new_geom["box_w"] = max(20.0, right - new_left)

    return new_geom


def paint_handles(
    painter: QPainter,
    handles: dict[str, QPointF],
    active_handle: str | None,
    hovered_handle: str | None,
    is_selected: bool,
    scale: float,
):
    """Dibuja los tiradores visuales adaptados al zoom de pantalla y estados de interacción."""
    for h_name, pt in handles.items():
        is_active = (active_handle == h_name)
        is_hovered = (hovered_handle == h_name)

        if is_active:
            screen_size = 12.0
        elif is_hovered:
            screen_size = 11.0
        elif is_selected:
            screen_size = 8.5
        else:
            screen_size = 7.5

        h_size = screen_size / scale

        # 1. Aura resplandeciente (Glow aura) en hover o arrastre
        if is_hovered or is_active:
            glow_radius = h_size * 1.5
            glow_color = QColor(14, 165, 233, 85 if is_hovered else 135)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow_color))
            painter.drawEllipse(pt, glow_radius, glow_radius)

        # 2. Sombra de contraste exterior
        shadow_color = QColor(0, 0, 0, 90 if is_selected else 60)
        painter.setPen(QPen(shadow_color, 1.0 / scale))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if h_name in ("p1", "p2", "anchor"):
            painter.drawEllipse(pt, (h_size / 2.0) + (0.5 / scale), (h_size / 2.0) + (0.5 / scale))
        else:
            shadow_rect = QRectF(pt.x() - h_size / 2.0 + (0.5 / scale), pt.y() - h_size / 2.0 + (0.5 / scale), h_size, h_size)
            painter.drawRoundedRect(shadow_rect, 2.0 / scale, 2.0 / scale)

        # 3. Colores de relleno y borde
        if is_active:
            fill_col = QColor("#0284C7")
            border_col = QColor("#FFFFFF")
            border_w = 2.0 / scale
        elif is_hovered:
            fill_col = QColor("#38BDF8")
            border_col = QColor("#0369A1")
            border_w = 1.8 / scale
        elif is_selected:
            fill_col = QColor("#FFFFFF")
            border_col = QColor("#0284C7")
            border_w = 1.6 / scale
        else:
            fill_col = QColor(255, 255, 255, 230)
            border_col = QColor(2, 132, 199, 190)
            border_w = 1.3 / scale

        painter.setPen(QPen(border_col, border_w))
        painter.setBrush(QBrush(fill_col))

        # 4. Geometría según tipo de tirador
        if h_name in ("p1", "p2", "anchor"):
            r_circ = h_size / 2.0
            painter.drawEllipse(pt, r_circ, r_circ)
            center_dot_col = QColor("#FFFFFF") if (is_hovered or is_active) else QColor("#0284C7")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(center_dot_col))
            painter.drawEllipse(pt, 2.0 / scale, 2.0 / scale)
        else:
            handle_rect = QRectF(pt.x() - h_size / 2.0, pt.y() - h_size / 2.0, h_size, h_size)
            painter.drawRoundedRect(handle_rect, 2.0 / scale, 2.0 / scale)
