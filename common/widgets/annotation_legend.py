# common/widgets/annotation_legend.py
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QFont,
    QFontMetricsF,
)


def format_display_properties(properties: dict | None) -> list[tuple[str, str]]:
    """Filtra y formatea las propiedades clave-valor personalizadas para la leyenda técnica."""
    if not isinstance(properties, dict):
        return []

    ignored = {
        "source_port",
        "target_port",
        "route_mode",
        "source_id",
        "target_id",
        "_is_template",
        "custom_color",
    }

    display_props = []
    for k, v in properties.items():
        if not k or not isinstance(k, str):
            continue
        k_clean = k.strip()
        if not k_clean or k_clean.startswith("_") or k_clean.lower() in ignored:
            continue

        if isinstance(v, (list, tuple, set)):
            val_strs = [str(x).strip() for x in v if x is not None and str(x).strip()]
            if not val_strs:
                continue
            v_str = ", ".join(val_strs)
        elif isinstance(v, dict):
            parts = [f"{dk}: {dv}" for dk, dv in v.items() if str(dv).strip()]
            if not parts:
                continue
            v_str = ", ".join(parts)
        else:
            if v is None:
                continue
            v_str = str(v).strip()
            if not v_str:
                continue

        display_props.append((k_clean, v_str))
    return display_props


def compute_legend_layout(
    annot_type: str,
    geometry_data: dict,
    display_props: list[tuple[str, str]],
    callout_box_rect: QRectF | None = None,
) -> tuple[QRectF, QPointF | None]:
    """Calcula el rectángulo delimitador y punto de anclaje de la tarjeta de leyenda."""
    if not display_props:
        return QRectF(), None

    key_font = QFont("sans-serif", 8, QFont.Weight.DemiBold)
    val_font = QFont("sans-serif", 8, QFont.Weight.Normal)

    def _est_width(s: str, font: QFont) -> float:
        try:
            fm = QFontMetricsF(font)
            adv = fm.horizontalAdvance(s)
            if adv > 0:
                return adv
        except Exception:
            pass
        return len(s) * 6.5

    max_line_w = 0.0
    for k, v in display_props:
        w = _est_width(f"{k}: ", key_font) + _est_width(v, val_font)
        if w > max_line_w:
            max_line_w = w

    pad_x = 10.0
    pad_y = 5.0
    line_h = 16.0
    legend_w = max(70.0, max_line_w + pad_x * 2 + 4.0)
    legend_h = len(display_props) * line_h + pad_y * 2

    t = annot_type
    attach_pt = None

    if t in ("rect", "circle", "cloud"):
        x = float(geometry_data.get("x", 0))
        y = float(geometry_data.get("y", 0))
        w = float(geometry_data.get("w", 50))
        h = float(geometry_data.get("h", 50))
        cx = (min(x, x + w) + max(x, x + w)) / 2.0
        bottom = max(y, y + h)
        lx = cx - legend_w / 2.0
        ly = bottom + 10.0
        attach_pt = QPointF(cx, bottom)

    elif t == "text":
        x = float(geometry_data.get("x", 0))
        y = float(geometry_data.get("y", 0))
        w = max(30.0, float(geometry_data.get("w", 120)))
        h = max(24.0, float(geometry_data.get("h", 32)))
        cx = x + w / 2.0
        bottom = y + h
        lx = cx - legend_w / 2.0
        ly = bottom + 10.0
        attach_pt = QPointF(cx, bottom)

    elif t == "callout":
        if callout_box_rect:
            cx = callout_box_rect.center().x()
            bottom = callout_box_rect.bottom()
        else:
            bx = float(geometry_data.get("box_x", 0))
            by = float(geometry_data.get("box_y", 0))
            bw = float(geometry_data.get("box_w", 120))
            bh = float(geometry_data.get("box_h", 36))
            cx = (min(bx, bx + bw) + max(bx, bx + bw)) / 2.0
            bottom = max(by, by + bh)
        lx = cx - legend_w / 2.0
        ly = bottom + 10.0
        attach_pt = QPointF(cx, bottom)

    elif t in ("line", "arrow", "relation"):
        x1 = float(geometry_data.get("x1", 0))
        y1 = float(geometry_data.get("y1", 0))
        x2 = float(geometry_data.get("x2", 50))
        y2 = float(geometry_data.get("y2", 50))
        mx = (x1 + x2) / 2.0
        my = (y1 + y2) / 2.0
        lx = mx - legend_w / 2.0
        ly = my + 12.0
        attach_pt = QPointF(mx, my)
    else:
        lx = 0.0
        ly = 0.0

    return QRectF(lx, ly, legend_w, legend_h), attach_pt


def paint_legend_card(
    painter: QPainter,
    legend_rect: QRectF,
    display_props: list[tuple[str, str]],
    attach_pt: QPointF | None,
    base_color: QColor,
):
    """Renderiza la tarjeta de leyenda técnica con diseño CAD / BIM de alta fidelidad."""
    if not display_props or not legend_rect or legend_rect.isEmpty():
        return

    # 1. Línea sutil de conexión punteada
    if attach_pt is not None:
        conn_pen = QPen(QColor(base_color.red(), base_color.green(), base_color.blue(), 150), 1.0, Qt.PenStyle.DotLine)
        painter.setPen(conn_pen)
        target_x = max(legend_rect.left() + 10.0, min(attach_pt.x(), legend_rect.right() - 10.0))
        painter.drawLine(attach_pt, QPointF(target_x, legend_rect.top()))

    # 2. Sombra suave para contraste
    shadow_rect = legend_rect.translated(1.0, 1.5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(0, 0, 0, 95)))
    painter.drawRoundedRect(shadow_rect, 4.0, 4.0)

    # 3. Fondo dark slate translúcido estilo BIM con borde fino
    border_col = QColor(base_color.red(), base_color.green(), base_color.blue(), 190)
    card_pen = QPen(border_col, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(card_pen)
    painter.setBrush(QBrush(QColor(15, 23, 42, 235)))
    painter.drawRoundedRect(legend_rect, 4.0, 4.0)

    # 4. Indicador de color lateral / píldora de acento
    indicator_rect = QRectF(legend_rect.left() + 3.0, legend_rect.top() + 4.5, 2.5, max(4.0, legend_rect.height() - 9.0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(base_color))
    painter.drawRoundedRect(indicator_rect, 1.25, 1.25)

    # 5. Renderizado de líneas de propiedad clave-valor
    key_font = QFont("sans-serif", 8, QFont.Weight.DemiBold)
    val_font = QFont("sans-serif", 8, QFont.Weight.Normal)
    fm_k = QFontMetricsF(key_font)

    start_x = legend_rect.left() + 10.0
    start_y = legend_rect.top() + 5.0
    line_h = 16.0

    for i, (k, v) in enumerate(display_props):
        cur_y = start_y + i * line_h
        k_txt = f"{k}: "
        k_w = fm_k.horizontalAdvance(k_txt)
        k_rect = QRectF(start_x, cur_y, k_w, line_h)
        v_rect = QRectF(start_x + k_w, cur_y, max(10.0, legend_rect.width() - (start_x - legend_rect.left()) - k_w - 4.0), line_h)

        painter.setFont(key_font)
        painter.setPen(QColor("#7DD3FC"))
        painter.drawText(k_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, k_txt)

        painter.setFont(val_font)
        painter.setPen(QColor("#F8FAFC"))
        painter.drawText(v_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, v)
