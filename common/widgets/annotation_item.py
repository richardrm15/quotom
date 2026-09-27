from common.widgets.cursor_manager import ViewerCursorManager
from common.widgets.annotation_paths import (
    build_rect_path,
    build_circle_path,
    build_line_path,
    build_arrow_path,
    build_cloud_path,
    build_text_path,
    build_callout_path,
    generate_cloud_path,
)
from common.widgets.annotation_handles import (
    compute_handles,
    calculate_handle_resize,
    paint_handles,
)
from common.widgets.annotation_legend import (
    format_display_properties,
    compute_legend_layout,
    paint_legend_card,
)
"""
Elementos Gráficos Vectoriales de Anotación (Annotation Graphics Items).

Implementa elementos interactivos para QGraphicsScene conformes a ISO 128 / ISO 32000:
- Rectángulo (rect)
- Círculo / Elipse (circle)
- Línea recta (line)
- Flecha directriz (arrow)
- Nube de revisión continua (cloud)
- Texto libre en plano (text)
- Llamada con flecha (callout)

Optimizado para 60 FPS con BspTreeIndex y caché geométrica de QPainterPath.
"""

import copy
import json
import math
from typing import Any

from PySide6.QtCore import QObject, Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QColor,
    QPen,
    QBrush,
    QFont,
    QFontMetricsF,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QStyleOptionGraphicsItem,
    QWidget,
)



def parse_color(color_val: Any, default: QColor = Qt.GlobalColor.transparent) -> QColor:
    """Parsea con seguridad colores en formato hex (#RRGGBB, #AARRGGBB), rgba(r,g,b,a) o nombres Qt."""
    if not color_val or color_val == "transparent":
        return default
    if isinstance(color_val, str) and color_val.startswith("rgba"):
        try:
            parts = color_val.replace("rgba(", "").replace(")", "").split(",")
            r = int(parts[0].strip())
            g = int(parts[1].strip())
            b = int(parts[2].strip())
            a = float(parts[3].strip())
            alpha_int = int(round(a * 255)) if a <= 1.0 else int(a)
            return QColor(r, g, b, alpha_int)
        except Exception:
            pass
    c = QColor(color_val)
    if c.isValid():
        return c
    return default


class _AnnotationItemSignals(QObject):
    """Emisor de señales de una anotación (QGraphicsItem no hereda de QObject)."""

    moved = Signal(str, float, float)
    resized = Signal(str, dict, dict)
    double_clicked = Signal(object)


class AnnotationGraphicsItem(QGraphicsItem):
    """
    Elemento vectorial interactivo en la escena gráfica para una anotación.

    Señales hacia arriba (no conoce a su vista contenedora):
        moved(str, float, float): la anotación fue arrastrada (annot_id, dx, dy).
        resized(str, dict, dict): el tirador cambió la geometría.
        double_clicked(object): doble clic sobre la anotación.

    Métodos de entrada (Methods Down) invocados por la vista:
        set_interaction_enabled(bool): habilita/deshabilita hover y tiradores.
        set_view_scale(float): informa la escala de zoom.
        update_from_data(dict): refresca estilo, contenido o geometría.
    """

    def __init__(self, annot_data: dict, parent=None):
        super().__init__(parent)
        # QGraphicsItem no hereda de QObject: se delega la emisión de señales a un
        # emisor dedicado, expuesto de forma pública mediante propiedades.
        self._signals = _AnnotationItemSignals()
        def _to_dict(v):
            if isinstance(v, str):
                try: return json.loads(v)
                except Exception: return {}
            return dict(v) if isinstance(v, dict) else {}

        def _to_list(v):
            if isinstance(v, str):
                try: return json.loads(v)
                except Exception: return []
            return list(v) if isinstance(v, (list, tuple)) else []

        self.annot_id: str = annot_data.get("id", "")
        self.annot_type: str = annot_data.get("type", "rect")
        raw_geom = annot_data.get("scene_geometry") or annot_data.get("geometry", {})
        self.geometry_data: dict = _to_dict(raw_geom)
        self.style_data: dict = _to_dict(annot_data.get("style", {}))
        self.content: str = annot_data.get("content", "") or ""
        self.tags: list = _to_list(annot_data.get("tags", []))
        self.properties: dict = _to_dict(annot_data.get("properties", {}))
        self.raw_data: dict = annot_data

        # Banderas de interacción Qt
        flags = (
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setFlags(flags)
        self.setAcceptHoverEvents(True)

        self._is_hovered: bool = False
        self._drag_start_pos: QPointF = QPointF(0, 0)
        self._is_dragging: bool = False
        self._active_handle: str | None = None
        self._hovered_handle: str | None = None
        self._is_resizing: bool = False
        self._orig_geometry: dict = {}
        self._route_pts: list[QPointF] = []
        self._path = QPainterPath()
        self._legend_rect = QRectF()
        self._legend_attach_pt = None
        self._boundingRect = QRectF()
        self._callout_box_rect: QRectF | None = None
        self._callout_p_box_edge = QPointF()
        self._callout_p_knee = QPointF()
        self._callout_p_anchor = QPointF()
        self._callout_arrow_poly: list[QPointF] = []
        # Estado empujado por la vista (Methods Down)
        self._interaction_enabled: bool = True
        self._view_scale: float = 1.0
        self.rebuild_path()

    # --- Señales públicas (Signals Up) ---

    @property
    def moved(self):
        """Señal emitida al arrastrar la anotación: (annot_id, dx, dy)."""
        return self._signals.moved

    @property
    def resized(self):
        """Señal emitida al redimensionar: (annot_id, geometría_previa, geometría_nueva)."""
        return self._signals.resized

    @property
    def double_clicked(self):
        """Señal emitida en doble clic: (AnnotationGraphicsItem)."""
        return self._signals.double_clicked

    PORT_NAMES = ("top", "bottom", "left", "right")

    def set_view_scale(self, scale: float) -> None:
        """Método público de entrada (Methods Down): la vista informa su escala de zoom."""
        self._view_scale = float(scale) if scale and scale > 0.0001 else 1.0

    def _current_view_scale(self) -> float:
        """Escala de zoom informada por la vista (tiradores invariantes al zoom)."""
        return self._view_scale

    def set_interaction_enabled(self, enabled: bool) -> None:
        """
        Método público de entrada (Methods Down): la vista contenedora comunica si
        el modo de herramienta actual permite interactuar con esta anotación.
        """
        self._interaction_enabled = bool(enabled)
        if not self._interaction_enabled:
            self._hovered_handle = None
            self._is_hovered = False
        self.update()

    def _can_interact(self) -> bool:
        """Indica si el modo actual permite hover, tiradores y arrastre."""
        return self._interaction_enabled

    def hoverEnterEvent(self, event):
        if not self._can_interact():
            super().hoverEnterEvent(event)
            return
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        can_interact = self._can_interact()
        if not can_interact:
            super().hoverMoveEvent(event)
            return

        handle = self.get_handle_at(event.pos())
        if self._hovered_handle != handle:
            self._hovered_handle = handle
            self.update()

        cursor = ViewerCursorManager.get_item_hover_cursor(handle, can_interact)
        self.setCursor(cursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        self._hovered_handle = None
        self.update()
        if not self._can_interact():
            super().hoverLeaveEvent(event)
            return

        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverLeaveEvent(event)

    def get_handles(self) -> dict[str, QPointF]:
        """Retorna exclusivamente las coordenadas de los puntos donde realmente se puede redimensionar."""
        return compute_handles(self.annot_type, self.geometry_data, self.style_data)

    def get_handle_at(self, pos: QPointF, threshold: float = 14.0) -> str | None:
        """Determina si una coordenada local coincide con un tirador de redimensión adaptado al zoom."""
        scale = self._current_view_scale()
        item_threshold = max(14.0, threshold) / scale
        handles = self.get_handles()
        best_h = None
        min_dist = item_threshold
        for h_name, pt in handles.items():
            dist = math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
            if dist <= min_dist:
                min_dist = dist
                best_h = h_name
        return best_h

    def get_text_rect(self) -> QRectF:
        """Retorna el rectángulo en coordenadas locales del elemento donde se renderiza el texto."""
        t = self.annot_type
        if t == "text":
            x = float(self.geometry_data.get("x", 0))
            y = float(self.geometry_data.get("y", 0))
            w = max(30.0, float(self.geometry_data.get("w", 120)))
            h = max(24.0, float(self.geometry_data.get("h", 32)))
            shape = self.style_data.get("shape", "rect")

            if shape in ("circle", "ellipse"):
                inner_w = w * 0.70
                inner_h = h * 0.70
                return QRectF(x + (w - inner_w) / 2.0, y + (h - inner_h) / 2.0, inner_w, inner_h)

            elif shape == "hexagon":
                inner_w = w * 0.65
                inner_h = h * 0.65
                return QRectF(x + (w - inner_w) / 2.0, y + (h - inner_h) / 2.0, inner_w, inner_h)

            elif shape == "triangle":
                inner_w = w * 0.55
                inner_h = h * 0.45
                cx = x + 0.5 * w
                cy = y + 0.62 * h
                return QRectF(cx - inner_w / 2.0, cy - inner_h / 2.0, inner_w, inner_h)

            return QRectF(x + 5, y + 3, max(20.0, w - 10), max(15.0, h - 6))
        elif t == "callout":
            box_rect = self._callout_box_rect
            if box_rect is None:
                bx = float(self.geometry_data.get("box_x", 0))
                by = float(self.geometry_data.get("box_y", 0))
                bw = float(self.geometry_data.get("box_w", 120))
                bh = float(self.geometry_data.get("box_h", 36))
                box_rect = QRectF(min(bx, bx + bw), min(by, by + bh), max(40.0, abs(bw)), max(24.0, abs(bh)))
            return box_rect
        return self.boundingRect()

    def get_port_local_pos(self, port_name: str) -> QPointF:
        br = self.boundingRect()
        return br.center()

    def get_port_scene_pos(self, port_name: str) -> QPointF:
        return self.mapToScene(self.get_port_local_pos(port_name))

    @staticmethod
    def get_auto_ports(item1, item2) -> tuple[str, str]:
        return "right", "left"

    def get_display_properties(self) -> list[tuple[str, str]]:
        """Filtra y formatea las propiedades clave-valor personalizadas para mostrarlas en la leyenda."""
        return format_display_properties(self.properties)

    def _compute_legend_rect(self):
        """Calcula el rectángulo delimitador local de la leyenda según el tipo de anotación y propiedades."""
        callout_box = self._callout_box_rect
        self._legend_rect, self._legend_attach_pt = compute_legend_layout(
            self.annot_type,
            self.geometry_data,
            self.get_display_properties(),
            callout_box,
        )

    def rebuild_path(self):
        """Reconstruye y almacena en caché el QPainterPath vectorial según la geometría."""
        self.prepareGeometryChange()
        t = self.annot_type

        if t == "rect":
            path = build_rect_path(self.geometry_data)
        elif t == "circle":
            path = build_circle_path(self.geometry_data)
        elif t == "line":
            path = build_line_path(self.geometry_data)
        elif t == "arrow":
            path = build_arrow_path(self.geometry_data)
        elif t == "cloud":
            path = build_cloud_path(self.geometry_data)
        elif t == "text":
            path, _ = build_text_path(self.geometry_data, self.style_data)
        elif t == "callout":
            path, self._callout_box_rect, self._callout_p_box_edge, self._callout_p_knee, self._callout_p_anchor, self._callout_arrow_poly = build_callout_path(self.geometry_data)
        elif t == "relation":
            path = build_line_path(self.geometry_data)
        else:
            path = build_line_path(self.geometry_data)

        self._path = path
        stroke_w = float(self.style_data.get("stroke_width", 2.0))

        total_rect = path.boundingRect()
        if t in ("rect", "circle", "cloud", "text"):
            x = float(self.geometry_data.get("x", 0))
            y = float(self.geometry_data.get("y", 0))
            w = float(self.geometry_data.get("w", 50))
            h = float(self.geometry_data.get("h", 50))
            total_rect = total_rect.united(QRectF(min(x, x + w), min(y, y + h), abs(w), abs(h)))
        elif t == "callout":
            box_rect = self._callout_box_rect
            if box_rect:
                total_rect = total_rect.united(box_rect)
            ax = float(self.geometry_data.get("anchor_x", 0))
            ay = float(self.geometry_data.get("anchor_y", 0))
            total_rect = total_rect.united(QRectF(ax - 5, ay - 5, 10, 10))

        self._compute_legend_rect()
        if not self._legend_rect.isEmpty():
            total_rect = total_rect.united(self._legend_rect)

        for pt in self.get_handles().values():
            total_rect = total_rect.united(QRectF(pt.x() - 14, pt.y() - 14, 28, 28))

        self._boundingRect = total_rect.adjusted(-stroke_w - 24, -stroke_w - 24, stroke_w + 24, stroke_w + 24)

    def _generate_cloud_path(self, x: float, y: float, w: float, h: float, arc_size: float = 18.0) -> QPainterPath:
        """Delega la generación de nubes a annotation_paths."""
        return generate_cloud_path(x, y, w, h, arc_size)

    def boundingRect(self) -> QRectF:
        scale = self._current_view_scale()
        handle_margin = max(32.0, 48.0 / scale)
        stroke_w = float(self.style_data.get("stroke_width", 2.0))

        # Unir path vectorial, caja delimitadora y posiciones de todos los tiradores
        rect = self._path.boundingRect()
        t = self.annot_type
        if t in ("rect", "circle", "cloud", "text"):
            x = float(self.geometry_data.get("x", 0))
            y = float(self.geometry_data.get("y", 0))
            w = float(self.geometry_data.get("w", 50))
            h = float(self.geometry_data.get("h", 50))
            rect = rect.united(QRectF(min(x, x + w), min(y, y + h), abs(w), abs(h)))
        elif t == "callout":
            box_rect = self._callout_box_rect
            if box_rect:
                rect = rect.united(box_rect)
            ax = float(self.geometry_data.get("anchor_x", 0))
            ay = float(self.geometry_data.get("anchor_y", 0))
            rect = rect.united(QRectF(ax - 5, ay - 5, 10, 10))

        if not self._legend_rect.isEmpty():
            rect = rect.united(self._legend_rect)

        for pt in self.get_handles().values():
            rect = rect.united(QRectF(pt.x() - 16, pt.y() - 16, 32, 32))

        return rect.adjusted(
            -stroke_w - handle_margin,
            -stroke_w - handle_margin,
            stroke_w + handle_margin,
            stroke_w + handle_margin,
        )

    def shape(self) -> QPainterPath:
        if self.annot_type in ("rect", "circle", "cloud", "text", "callout"):
            p = QPainterPath()
            p.addRect(self.boundingRect())
            return p
        else:
            stroker = QPainterPathStroker()
            stroker.setWidth(max(14.0, float(self.style_data.get("stroke_width", 2.0)) * 2))
            p = stroker.createStroke(self._path)
            if not self._legend_rect.isEmpty():
                p.addRoundedRect(self._legend_rect, 4.0, 4.0)
            return p

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        stroke_color_str = self.style_data.get("stroke_color", "#EC4899")
        fill_color_str = self.style_data.get("fill_color", "transparent")
        stroke_w = float(self.style_data.get("stroke_width", 2.0))

        color = parse_color(stroke_color_str, QColor("#EC4899"))
        fill = parse_color(fill_color_str, Qt.GlobalColor.transparent)

        # Estilo de pluma ISO 128
        pen = QPen(color, stroke_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill))

        t = self.annot_type

        # 1. Dibujo de geometrías
        if t in ("rect", "circle", "cloud"):
            painter.drawPath(self._path)
        elif t in ("line", "arrow"):
            painter.setBrush(QBrush(color))
            painter.drawPath(self._path)
        elif t == "relation":
            painter.setBrush(QBrush(color))
            painter.drawPath(self._path)
        elif t == "callout":
            # 1. Fondo y borde de la caja de texto
            bg_color = fill if fill != Qt.GlobalColor.transparent else parse_color(self.style_data.get("bg_color"), QColor(30, 30, 30, 220))
            painter.setBrush(QBrush(bg_color))
            painter.setPen(pen)
            box_rect = self._callout_box_rect or QRectF(0, 0, 120, 36)
            painter.drawRoundedRect(box_rect, 3.0, 3.0)

            # 2. Línea guía (leader line) sin relleno para que no se deforme
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            leader_path = QPainterPath()
            leader_path.moveTo(self._callout_p_anchor)
            leader_path.lineTo(self._callout_p_knee)
            leader_path.lineTo(self._callout_p_box_edge)
            painter.drawPath(leader_path)

            # 3. Cabeza de flecha rellena con el color del trazo (sólida y nítida)
            arrow_poly = self._callout_arrow_poly
            if arrow_poly and len(arrow_poly) >= 3:
                painter.setBrush(QBrush(pen.color()))
                painter.drawPolygon(QPolygonF(arrow_poly))

            # 4. Texto interior con tipografía completa
            if self.content:
                self._paint_text_content(painter, box_rect.adjusted(6, 4, -6, -4))

        elif t == "text":
            # Fondo de caja de texto si tiene relleno
            bg_color = fill if fill != Qt.GlobalColor.transparent else parse_color(self.style_data.get("bg_color"), Qt.GlobalColor.transparent)
            if bg_color != Qt.GlobalColor.transparent:
                painter.setBrush(QBrush(bg_color))
                painter.setPen(pen)
                painter.drawPath(self._path)
            elif pen.color() != Qt.GlobalColor.transparent and stroke_w > 0:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(pen)
                painter.drawPath(self._path)

            if self.content:
                text_rect = self.get_text_rect()
                self._paint_text_content(painter, text_rect)

        # 1.5 Línea delimitadora discontinua para figuras puras de FreeText al estar seleccionadas o con hover
        if (self.isSelected() or self._is_hovered) and self.annot_type == "text" and self.style_data.get("shape", "rect") != "rect":
            scale = option.levelOfDetailFromTransform(painter.worldTransform()) if option else self._current_view_scale()
            if scale <= 0.0001: scale = 1.0
            dash_pen = QPen(QColor(2, 132, 199, 100), 1.0 / scale, Qt.PenStyle.DashLine)
            painter.setPen(dash_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            handles = self.get_handles()
            tl = handles.get("tl")
            br = handles.get("br")
            if tl and br:
                painter.drawRect(QRectF(tl.x(), tl.y(), br.x() - tl.x(), br.y() - tl.y()))

        # 1.8 Leyenda técnica de propiedades personalizadas (Key-Value BIM Legend)
        if not self._legend_rect.isEmpty():
            self._paint_legend(painter)

        # 2. Tiradores de redimensión adaptados al zoom
        show_handles = (self.isSelected() or self._is_hovered)
        if show_handles and self._can_interact():
            scale = option.levelOfDetailFromTransform(painter.worldTransform()) if option else self._current_view_scale()
            if scale <= 0.0001:
                scale = 1.0

            paint_handles(
                painter,
                self.get_handles(),
                self._active_handle if self._is_resizing else None,
                self._hovered_handle,
                self.isSelected(),
                scale,
            )

    def _paint_legend(self, painter: QPainter):
        """Renderiza la tarjeta de leyenda técnica delegando en annotation_legend."""
        stroke_color_str = self.style_data.get("stroke_color", "#EC4899")
        base_col = parse_color(stroke_color_str, QColor("#38BDF8"))
        paint_legend_card(
            painter,
            self._legend_rect,
            self.get_display_properties(),
            self._legend_attach_pt,
            base_col,
        )

    def _paint_text_content(self, painter: QPainter, text_rect: QRectF):
        """Renderiza texto con soporte completo de tipografía ISO 32000 (/DA, /Q)."""
        text_color = parse_color(self.style_data.get("text_color"), QColor("#FFFFFF"))
        painter.setPen(text_color)

        font_family = self.style_data.get("font_family", "sans-serif")
        font_size = float(self.style_data.get("font_size", 11.0))
        font = QFont(font_family, int(font_size))
        if self.style_data.get("font_bold", False):
            font.setBold(True)
        if self.style_data.get("font_italic", False):
            font.setItalic(True)
        painter.setFont(font)

        align_str = str(self.style_data.get("text_align", "left")).lower()
        if align_str == "center":
            h_align = Qt.AlignmentFlag.AlignHCenter
        elif align_str == "right":
            h_align = Qt.AlignmentFlag.AlignRight
        else:
            h_align = Qt.AlignmentFlag.AlignLeft

        flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter | h_align
        painter.drawText(text_rect, flags, self.content)

    def update_data(self, updates: dict):
        """Actualiza los datos internos del elemento y reconstruye la geometría visual."""
        if not updates:
            return

        def _to_dict(v):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return {}
            return dict(v) if isinstance(v, dict) else {}

        def _to_list(v):
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except Exception:
                    return []
            return list(v) if isinstance(v, (list, tuple)) else []

        if 'style' in updates:
            self.style_data.update(_to_dict(updates['style']))
            self.raw_data['style'] = self.style_data
        if 'content' in updates:
            self.content = str(updates['content'] or '')
            self.raw_data['content'] = self.content
        if 'tags' in updates:
            self.tags = _to_list(updates['tags'])
            self.raw_data['tags'] = self.tags
        if 'properties' in updates:
            self.properties = _to_dict(updates['properties'])
            self.raw_data['properties'] = self.properties
        if 'discipline' in updates:
            self.raw_data['discipline'] = updates['discipline']
        if 'z_index' in updates:
            self.setZValue(float(updates['z_index']))
            self.raw_data['z_index'] = updates['z_index']
        if 'scene_geometry' in updates:
            self.geometry_data = _to_dict(updates['scene_geometry'])
            self.raw_data['geometry'] = self.geometry_data

        self.rebuild_path()
        self.update()
    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if not value:
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self._active_handle = None
                self._is_resizing = False
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if not self._can_interact():
            event.ignore()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.get_handle_at(event.pos())
            if handle:
                self.setSelected(True)
                self._active_handle = handle
                shape = self.style_data.get("shape", "rect")
                if self.annot_type == "text" and shape in ("circle", "ellipse", "hexagon", "triangle"):
                    h_dict = self.get_handles()
                    tl = h_dict["tl"]
                    br = h_dict["br"]
                    nw = br.x() - tl.x()
                    nh = br.y() - tl.y()
                    if abs(float(self.geometry_data.get("x", 0)) - tl.x()) > 0.01 or abs(float(self.geometry_data.get("w", 0)) - nw) > 0.01:
                        self.prepareGeometryChange()
                        self.geometry_data["x"] = tl.x()
                        self.geometry_data["y"] = tl.y()
                        self.geometry_data["w"] = nw
                        self.geometry_data["h"] = nh
                        self.rebuild_path()
                self._orig_geometry = copy.deepcopy(self.geometry_data)
                self._is_resizing = True
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton and bool(self.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable):
            self._drag_start_pos = self.pos()
            self._is_dragging = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_resizing and self._active_handle:
            cur = event.pos()
            old_rect = self.sceneBoundingRect()
            self.prepareGeometryChange()

            self.geometry_data.update(
                calculate_handle_resize(
                    self.annot_type,
                    self._orig_geometry,
                    self._active_handle,
                    cur,
                    self.style_data,
                )
            )

            self.rebuild_path()
            self.update()
            if self.scene():
                new_rect = self.sceneBoundingRect()
                self.scene().update(old_rect.united(new_rect))
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        try:
            super().mouseReleaseEvent(event)
        except TypeError:
            pass
        if self._is_resizing:
            self._is_resizing = False
            self._active_handle = None
            self.update()
            if self.scene():
                self.scene().update(self.sceneBoundingRect())
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

            orig = self._orig_geometry
            if orig and orig != self.geometry_data:
                self.resized.emit(self.annot_id, orig, dict(self.geometry_data))
            event.accept()
            return

        if self._is_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            delta = self.pos() - self._drag_start_pos
            if abs(delta.x()) >= 1.0 or abs(delta.y()) >= 1.0:
                if self.scene():
                    selected_items = [it for it in self.scene().selectedItems() if isinstance(it, AnnotationGraphicsItem)]
                    if not selected_items:
                        selected_items = [self]
                    for it in selected_items:
                        it.moved.emit(it.annot_id, delta.x(), delta.y())

    def mouseDoubleClickEvent(self, event):
        if not self._can_interact():
            event.ignore()
            return
        self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)
