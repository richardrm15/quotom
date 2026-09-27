"""
Lienzo Interactivo de Captura de Regiones (RegionCanvasView).

Permite navegar el plano (zoom, paneo) y seleccionar interactivamente
rectángulos de cajetín ('Zona 1', 'Zona 2', etc.) emitiendo coordenadas normalizadas.
"""

from typing import List, Dict, Tuple, Optional
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal, QSizeF
from PySide6.QtGui import (
    QPixmap,
    QPainter,
    QPen,
    QColor,
    QBrush,
    QFont,
    QWheelEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)

DEBUG_HIGHLIGHT_CHARS: bool = True

REGION_COLORS = [
    "#2563EB",  # Azul eléctrico (Zona 1)
    "#059669",  # Verde esmeralda (Zona 2)
    "#D97706",  # Ámbar dorado (Zona 3)
    "#7C3AED",  # Violeta (Zona 4)
    "#DC2626",  # Carmesí (Zona 5)
]


class RegionData:
    """Representa una zona de captura rectangular sobre el plano."""

    def __init__(self, region_id: int, color_hex: str, label: str):
        self.region_id = region_id
        self.color_hex = color_hex
        self.label = label
        self.norm_rect: Optional[QRectF] = None  # Normalizado [0.0..1.0, 0.0..1.0]
        self.sample_text: str = ""




class RegionCanvasView(QGraphicsView):
    """Lienzo interactivo con zoom, paneo continuo y herramienta de arrastre para capturar regiones."""

    region_drawn = Signal(int, QRectF)  # (region_id, norm_rect)
    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._page_pixmap: Optional[QPixmap] = None
        self._regions: List[RegionData] = []
        self._active_capture_id: Optional[int] = 1

        self._is_capturing = False
        self._drag_start_scene = QPointF()
        self._temp_rect_item: Optional[QGraphicsRectItem] = None
        self._region_items: Dict[int, Tuple[QGraphicsRectItem, QGraphicsSimpleTextItem]] = {}
        self._debug_highlight_items: List[QGraphicsRectItem] = []

        self._is_middle_panning = False
        self._middle_pan_start = QPoint()
        self._auto_fit = True

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_page_pixmap(self, pixmap: QPixmap):
        """Carga el mapa de bits del plano en el lienzo."""
        self._page_pixmap = pixmap
        self._scene.clear()
        self._region_items.clear()
        self._temp_rect_item = None
        self._debug_highlight_items.clear()

        if pixmap and not pixmap.isNull():
            self._pixmap_item = self._scene.addPixmap(pixmap)
            self._pixmap_item.setZValue(0)
            pw = float(pixmap.width())
            ph = float(pixmap.height())
            margin_x = max(2000.0, pw * 2.5)
            margin_y = max(2000.0, ph * 2.5)
            self._scene.setSceneRect(-margin_x, -margin_y, pw + 2.0 * margin_x, ph + 2.0 * margin_y)
            self._redraw_regions()
            if self._auto_fit:
                self.fit_in_view()
        else:
            self._pixmap_item = None

    def set_regions(self, regions: List[RegionData]):
        self._regions = regions
        self._redraw_regions()

    def active_capture_id(self) -> Optional[int]:
        """Zona que recibirá el próximo recuadro dibujado (``None`` si ninguna)."""
        return self._active_capture_id

    def set_active_capture_id(self, region_id: Optional[int]):
        self._active_capture_id = region_id
        if region_id is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _redraw_regions(self):
        """Dibuja en la escena todas las regiones definidas con sus colores correspondientes."""
        if not self._page_pixmap or self._page_pixmap.isNull():
            return

        for rect_item, text_item in self._region_items.values():
            self._scene.removeItem(rect_item)
            self._scene.removeItem(text_item)
        self._region_items.clear()

        pw = float(self._page_pixmap.width())
        ph = float(self._page_pixmap.height())

        for reg in self._regions:
            if reg.norm_rect is None:
                continue

            scene_rect = QRectF(
                reg.norm_rect.x() * pw,
                reg.norm_rect.y() * ph,
                reg.norm_rect.width() * pw,
                reg.norm_rect.height() * ph,
            )

            color = QColor(reg.color_hex)
            pen = QPen(color, 2.0, Qt.PenStyle.SolidLine)
            brush = QBrush(QColor(color.red(), color.green(), color.blue(), 45))

            rect_item = self._scene.addRect(scene_rect, pen, brush)
            rect_item.setZValue(10)

            badge_text = self._scene.addSimpleText(f"Zona {reg.region_id}", QFont("sans-serif", 10, QFont.Weight.Bold))
            badge_text.setBrush(QBrush(color))
            badge_text.setPos(scene_rect.left() + 4, max(0.0, scene_rect.top() - 18))
            badge_text.setZValue(11)

            self._region_items[reg.region_id] = (rect_item, badge_text)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._is_middle_panning = True
            self._middle_pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._active_capture_id is not None and self._page_pixmap:
                sp = self.mapToScene(event.position().toPoint())
                pw = float(self._page_pixmap.width())
                ph = float(self._page_pixmap.height())
                clamped_x = max(0.0, min(sp.x(), pw))
                clamped_y = max(0.0, min(sp.y(), ph))

                self._is_capturing = True
                self._drag_start_scene = QPointF(clamped_x, clamped_y)

                color_hex = "#2563EB"
                for r in self._regions:
                    if r.region_id == self._active_capture_id:
                        color_hex = r.color_hex
                        break

                color = QColor(color_hex)
                pen = QPen(color, 2.0, Qt.PenStyle.DashLine)
                brush = QBrush(QColor(color.red(), color.green(), color.blue(), 30))

                if self._temp_rect_item:
                    self._scene.removeItem(self._temp_rect_item)
                self._temp_rect_item = self._scene.addRect(QRectF(self._drag_start_scene, QSizeF(0, 0)), pen, brush)
                self._temp_rect_item.setZValue(20)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_middle_panning:
            delta = event.position().toPoint() - self._middle_pan_start
            self._middle_pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self._is_capturing and self._temp_rect_item and self._page_pixmap:
            sp = self.mapToScene(event.position().toPoint())
            pw = float(self._page_pixmap.width())
            ph = float(self._page_pixmap.height())
            curr_x = max(0.0, min(sp.x(), pw))
            curr_y = max(0.0, min(sp.y(), ph))

            rect = QRectF(self._drag_start_scene, QPointF(curr_x, curr_y)).normalized()
            self._temp_rect_item.setRect(rect)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) and self._is_middle_panning:
            self._is_middle_panning = False
            if self._active_capture_id is not None:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._is_capturing:
            self._is_capturing = False
            if self._temp_rect_item and self._page_pixmap:
                rect = self._temp_rect_item.rect().normalized()
                self._scene.removeItem(self._temp_rect_item)
                self._temp_rect_item = None

                pw = float(self._page_pixmap.width())
                ph = float(self._page_pixmap.height())

                if rect.width() >= 6 and rect.height() >= 6 and pw > 0 and ph > 0:
                    norm_rect = QRectF(
                        rect.x() / pw,
                        rect.y() / ph,
                        rect.width() / pw,
                        rect.height() / ph,
                    )
                    if self._active_capture_id is not None:
                        self.region_drawn.emit(self._active_capture_id, norm_rect)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)
        self.scale(factor, factor)
        self._auto_fit = False
        self.zoom_changed.emit(self.transform().m11())
        event.accept()

    def fit_in_view(self):
        """Ajusta el plano completo al viewport con un margen estético."""
        if self._page_pixmap and not self._page_pixmap.isNull():
            self.resetTransform()
            page_rect = QRectF(0, 0, self._page_pixmap.width(), self._page_pixmap.height())
            self.fitInView(page_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.centerOn(page_rect.center())
            self._auto_fit = True

    def zoom_in(self):
        self.scale(1.25, 1.25)
        self._auto_fit = False

    def zoom_out(self):
        self.scale(0.8, 0.8)
        self._auto_fit = False

    def clear_debug_highlights(self):
        """Limpia los rectángulos de depuración fosforescentes de la escena."""
        for item in self._debug_highlight_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._debug_highlight_items.clear()

    def show_debug_highlights(self, char_rects: List[QRectF], scale_x: float = 1.0, scale_y: float = 1.0):
        """Ilumina en verde fosforescente los caracteres capturados para inspección milimétrica."""
        self.clear_debug_highlights()
        if not DEBUG_HIGHLIGHT_CHARS:
            return

        pen = QPen(QColor("#00FF66"), 1.2, Qt.PenStyle.SolidLine)
        brush = QBrush(QColor(0, 255, 102, 70))

        for r in char_rects:
            rect_item = self._scene.addRect(
                QRectF(r.x() * scale_x, r.y() * scale_y, r.width() * scale_x, r.height() * scale_y),
                pen,
                brush,
            )
            rect_item.setZValue(25)
            self._debug_highlight_items.append(rect_item)


