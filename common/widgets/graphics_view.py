from common.widgets.cursor_manager import ViewerCursorManager
import math
from common.widgets.annotation_item import AnnotationGraphicsItem, parse_color
# QInputDialog eliminado para edición in-place directa en canvas
from enum import Enum
from typing import List, Optional
from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QKeySequence,
    QPainter,
    QPixmap,
    QWheelEvent,
    QMouseEvent,
    QKeyEvent,
    QTransform,
    QResizeEvent,
    QColor,
    QBrush,
    QPen,
    QGuiApplication,
    QCursor,
    QFont,
)
from PySide6.QtWidgets import (
    QMenu,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsItem,
    QTextEdit,
    QFrame,
)
from common.styles.style_manager import ThemeManager
from core.text_layer import PageTextData, SearchMatch
from common.helpers.qt_geometry import to_qpointf, to_qrectf


class ToolMode(Enum):
    SELECT = "select"
    PAN = "pan"
    TEXT_SELECT = "text_select"


class InlineTextEditor(QTextEdit):
    """Editor flotante in-place para escribir texto directamente en la anotación del plano."""
    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptRichText(False)
        self._is_closing = False

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._is_closing = True
            self.cancelled.emit()
            event.accept()
            return
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self._is_closing = True
                self.committed.emit(self.toPlainText())
                event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if not getattr(self, "_is_closing", False):
            self._is_closing = True
            self.committed.emit(self.toPlainText())


class PlanGraphicsView(QGraphicsView):
    """
    Viewport interactivo de alto rendimiento para visualización de planos.
    - Paneo libre ilimitado (ScrollHandDrag y botón central) estilo AutoCAD / Miro.
    - Modo dual: Herramienta de Paneo (Mano) y Herramienta de Selección de Texto (I-Beam).
    - Capa de selección de texto con feedback visual (resaltado translúcido) y copiado con Ctrl+C.
    - Capa de búsqueda y resaltado en vivo (coincidencias amarillas / coincidencia activa naranja).
    - Zoom centrado suavemente bajo la posición del ratón.
    - Preserva nivel de zoom y posición relativa de paneo al cambiar de página.
    - Auto-encuadre inteligente (fitInView).
    """
    zoom_changed = Signal(float)
    tool_mode_changed = Signal(str)  # 'pan' o 'text_select'
    text_copied = Signal(str)        # notifica texto copiado al portapapeles
    annotation_created = Signal(str, dict, str)  # (tool_id, scene_geometry, content)
    annotation_text_edited = Signal(str, str, str)  # (annot_id, old_content, new_content)
    annotation_deleted = Signal(str)             # (annot_id)
    annotation_selected = Signal(object)         # (AnnotationGraphicsItem or None)
    annotations_selected = Signal(list)          # (list[AnnotationGraphicsItem])
    annotation_double_clicked = Signal(object)    # (AnnotationGraphicsItem)
    annotation_item_moved = Signal(str, float, float) # (annot_id, dx, dy)
    annotation_item_resized = Signal(str, dict, dict) # (annot_id, old_scene_geom, new_scene_geom)
    request_inspect_annotation = Signal(str)     # (annot_id)
    request_autofit_annotation = Signal(object)  # (str | list[str])
    request_duplicate_annotation = Signal(str)   # (annot_id)
    request_reorder_annotation = Signal(str, str) # (annot_id, 'front'|'back')
    request_copy_annotations = Signal()
    request_paste_annotations = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("planCanvas")  # QSS centralizado: QGraphicsView#planCanvas
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)

        # Optimizaciones de renderizado Qt (60 FPS con miles de anotaciones)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.BspTreeIndex)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._current_zoom: float = 1.0
        self._annotation_tool: str = "select"
        self._is_drawing_annotation: bool = False
        self._draw_start_pt = QPointF()
        self._draw_curr_pt = QPointF()
        self._preview_item: AnnotationGraphicsItem | None = None
        self._annotation_items: dict[str, AnnotationGraphicsItem] = {} 
        self._auto_fit: bool = True

        # Modo de herramienta activo
        self._cursor_mgr = ViewerCursorManager(self)
        self._tool_mode: ToolMode = ToolMode.SELECT

        # Paneo con botón central o modo mano
        self._is_middle_panning: bool = False
        self._middle_pan_start = QPoint()

        # Datos de texto de la página activa
        self._page_text_data: Optional[PageTextData] = None

        # Selección de texto activa
        self._is_selecting_text: bool = False
        self._sel_start_char_idx: Optional[int] = None
        self._sel_end_char_idx: Optional[int] = None
        self._selected_text_str: str = ""
        self._selection_items: List[QGraphicsRectItem] = []

        # Búsqueda y resaltado de coincidencias
        self._search_matches: List[SearchMatch] = []
        self._current_match_idx: int = -1
        self._match_items: List[QGraphicsRectItem] = []

        self.set_tool_mode(ToolMode.SELECT)
        self.setMouseTracking(True)
        if self.viewport():
            self.viewport().setMouseTracking(True)
        self.update_canvas_theme()

    # --- Gestión de Modos de Herramienta ---

    @property
    def cursor_manager(self) -> ViewerCursorManager:
        """Retorna el gestor desacoplado de cursores de la vista."""
        return self._cursor_mgr

    def _set_active_cursor(self, cursor: Qt.CursorShape):
        """Delega la aplicación del cursor al CursorManager desacoplado."""
        self._cursor_mgr.set_override(cursor)
        self._cursor_mgr.apply(self)

    def _restore_active_cursor(self):
        """Restaura el cursor estándar delegando en el CursorManager desacoplado."""
        self._cursor_mgr.set_override(None)
        self._cursor_mgr.apply(self)

    def annotation_tool(self) -> str:
        """Retorna la herramienta de anotación activa."""
        return getattr(self, "_annotation_tool", "select")

    def set_annotation_tool(self, tool_id: str):
        """Configura la herramienta de anotación activa y adapta el cursor y modo de arrastre."""
        self._annotation_tool = tool_id
        self._cursor_mgr.set_drawing_tool(tool_id)
        if tool_id == "select":
            self._tool_mode = ToolMode.SELECT
            self._cursor_mgr.set_tool_mode("select")
            self._cursor_mgr.apply(self)
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.tool_mode_changed.emit(self._tool_mode.value)
        elif tool_id in ("line", "arrow", "rect", "circle", "cloud", "text", "callout"):
            self._tool_mode = ToolMode.SELECT
            self._cursor_mgr.set_tool_mode("select")
            self._cursor_mgr.apply(self)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._sync_annotation_interaction()

    def tool_mode(self) -> str:
        return self._tool_mode.value

    def set_tool_mode(self, mode: ToolMode | str):
        if isinstance(mode, str):
            if mode == "pan":
                mode = ToolMode.PAN
            elif mode == "text_select":
                mode = ToolMode.TEXT_SELECT
            else:
                mode = ToolMode.SELECT
        self._tool_mode = mode

        self._cursor_mgr.set_tool_mode(self._tool_mode.value)
        self._cursor_mgr.set_drawing_tool("select")
        self._annotation_tool = "select"

        if self._tool_mode == ToolMode.PAN:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif self._tool_mode == ToolMode.TEXT_SELECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self._tool_mode = ToolMode.SELECT
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        self._cursor_mgr.apply(self)
        self._sync_annotation_interaction()

        self.tool_mode_changed.emit(self._tool_mode.value)

    def toggle_tool_mode(self):
        new_mode = ToolMode.TEXT_SELECT if self._tool_mode == ToolMode.PAN else ToolMode.PAN
        self.set_tool_mode(new_mode)

    # --- Capa de Texto y Búsqueda ---

    def set_page_text_data(self, text_data: Optional[PageTextData]):
        """Asocia los datos de texto vectoriales de la página activa."""
        self.clear_selection()
        self.clear_search()
        self._page_text_data = text_data

    @property
    def page_text_data(self) -> Optional[PageTextData]:
        return self._page_text_data

    @property
    def selected_text(self) -> str:
        return self._selected_text_str

    def copy_selection_to_clipboard(self) -> bool:
        """Copia el texto actualmente seleccionado al portapapeles de la app."""
        if self._selected_text_str:
            clipboard = QGuiApplication.clipboard()
            if clipboard:
                clipboard.setText(self._selected_text_str)
                self.text_copied.emit(self._selected_text_str)
                return True
        return False

    def clear_selection(self):
        """Elimina el resaltado de texto seleccionado en la escena."""
        for item in self._selection_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._selection_items.clear()
        self._sel_start_char_idx = None
        self._sel_end_char_idx = None
        self._selected_text_str = ""
        self._is_selecting_text = False

    def _render_selection_rects(self, rects: List[QRectF]):
        """Dibuja los polígonos de selección de texto con estilo azul translúcido moderno."""
        # Limpiar rectángulos visuales anteriores
        for item in self._selection_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._selection_items.clear()

        # Estilo azul translúcido moderno (RGBA: 41, 128, 255, 90)
        fill_brush = QBrush(QColor(41, 128, 255, 95))
        outline_pen = QPen(QColor(41, 128, 255, 160), 0.8)

        for r in rects:
            item = QGraphicsRectItem(to_qrectf(r))
            item.setBrush(fill_brush)
            item.setPen(outline_pen)
            item.setZValue(20.0)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._scene.addItem(item)
            self._selection_items.append(item)

    # --- Búsqueda (Ctrl+F) ---

    def execute_search(self, query: str, match_case: bool = False) -> int:
        """
        Busca coincidencias en la página activa y dibuja rectángulos de resaltado.
        Retorna la cantidad total de coincidencias encontradas.
        """
        self.clear_search()
        if not self._page_text_data or not query.strip():
            return 0

        self._search_matches = self._page_text_data.search_matches(query.strip(), match_case)
        if not self._search_matches:
            return 0

        self._current_match_idx = 0
        self._render_search_matches()
        self._scroll_to_current_match()
        return len(self._search_matches)

    def next_search_match(self) -> int:
        """Avanza a la siguiente coincidencia."""
        if not self._search_matches:
            return -1
        self._current_match_idx = (self._current_match_idx + 1) % len(self._search_matches)
        self._render_search_matches()
        self._scroll_to_current_match()
        return self._current_match_idx

    def prev_search_match(self) -> int:
        """Retrocede a la coincidencia anterior."""
        if not self._search_matches:
            return -1
        self._current_match_idx = (self._current_match_idx - 1) % len(self._search_matches)
        self._render_search_matches()
        self._scroll_to_current_match()
        return self._current_match_idx

    def clear_search(self):
        """Limpia el resaltado de búsqueda."""
        for item in self._match_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._match_items.clear()
        self._search_matches.clear()
        self._current_match_idx = -1

    def _render_search_matches(self):
        for item in self._match_items:
            if item.scene() == self._scene:
                self._scene.removeItem(item)
        self._match_items.clear()

        # Coincidencias inactivas: Amarillo cálido translúcido
        normal_brush = QBrush(QColor(255, 235, 59, 110))
        normal_pen = QPen(QColor(251, 192, 45, 180), 1.0)

        # Coincidencia activa: Naranja vibrante
        active_brush = QBrush(QColor(255, 112, 67, 160))
        active_pen = QPen(QColor(216, 67, 21, 230), 1.5)

        for idx, match in enumerate(self._search_matches):
            is_active = (idx == self._current_match_idx)
            brush = active_brush if is_active else normal_brush
            pen = active_pen if is_active else normal_pen
            z = 30.0 if is_active else 25.0

            for r in match.rects:
                item = QGraphicsRectItem(to_qrectf(r))
                item.setBrush(brush)
                item.setPen(pen)
                item.setZValue(z)
                item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self._scene.addItem(item)
                self._match_items.append(item)

    def _scroll_to_current_match(self):
        if 0 <= self._current_match_idx < len(self._search_matches):
            match = self._search_matches[self._current_match_idx]
            if match.rects:
                # Centrar suavemente en la primera caja del match
                self.centerOn(to_qpointf(match.rects[0].center()))

    # --- Renderizado de Lienzo y Zoom ---

    def update_canvas_theme(self):
        """
        Reaplica el tema al lienzo (Methods Down).

        El fondo del lienzo vive en ``common/styles/theme.qss`` (``#planCanvas``);
        aquí solo se fuerza un *repolish* para que Qt vuelva a evaluar la hoja
        global tras un cambio de tema.
        """
        self.style().unpolish(self)
        self.style().polish(self)

    def _update_scene_rect(self):
        if not self._pixmap_item:
            return

        pix_rect = self._pixmap_item.boundingRect()
        pw = pix_rect.width()
        ph = pix_rect.height()

        margin_x = max(2000.0, pw * 3.0)
        margin_y = max(2000.0, ph * 3.0)

        extended_rect = QRectF(
            -margin_x,
            -margin_y,
            pw + 2.0 * margin_x,
            ph + 2.0 * margin_y
        )
        self._scene.setSceneRect(extended_rect)

    
    # --- Edición Directa de Texto In-Place en Canvas ---

    def start_inline_text_edit(self, item: AnnotationGraphicsItem):
        """Inicia edición in-place directamente sobre el recuadro de la anotación en el canvas sin diálogos."""
        if not item or item.annot_type not in ("text", "callout"):
            return

        self.commit_inline_text_edit()

        self._editing_item = item
        self._editing_annot_id = item.annot_id
        self._editing_orig_content = item.content or ""

        text_rect = item.get_text_rect()
        poly = item.mapToScene(text_rect)
        view_rect = self.mapFromScene(poly).boundingRect()

        editor = InlineTextEditor(self.viewport())
        w = max(view_rect.width(), 90.0)
        h = max(view_rect.height(), 32.0)
        editor.setGeometry(int(view_rect.x() - 2), int(view_rect.y() - 2), int(w + 4), int(h + 4))

        st = item.style_data
        font_fam = st.get("font_family", "sans-serif")
        font_sz = max(9.0, float(st.get("font_size", 11.0)) * self._current_zoom)
        font = QFont(font_fam, int(font_sz))
        if st.get("font_bold", False):
            font.setBold(True)
        if st.get("font_italic", False):
            font.setItalic(True)
        editor.setFont(font)

        tc = st.get("text_color", "#FFFFFF")
        tc_color = parse_color(tc, QColor("#FFFFFF"))
        lum = 0.299 * tc_color.red() + 0.587 * tc_color.green() + 0.114 * tc_color.blue()
        bg_color = "rgba(15, 23, 42, 0.95)" if lum > 128 else "rgba(248, 250, 252, 0.95)"

        ThemeManager.apply_inline_editor_style(editor, tc, bg_color)

        # Configurar texto primero para que la alineación persista correctamente
        editor.setPlainText(item.content or "")

        align = str(st.get("text_align", "left")).lower()
        if align == "center":
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elif align == "right":
            editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        else:
            editor.setAlignment(Qt.AlignmentFlag.AlignLeft)

        editor.selectAll()
        editor.show()
        editor.setFocus()

        editor.committed.connect(self._on_inline_editor_committed)
        editor.cancelled.connect(self._on_inline_editor_cancelled)
        self._inline_editor = editor

    def commit_inline_text_edit(self):
        """Confirma y cierra la edición in-place si está activa."""
        if getattr(self, "_inline_editor", None):
            txt = self._inline_editor.toPlainText()
            self._on_inline_editor_committed(txt)

    def cancel_inline_text_edit(self):
        """Cancela y descarta la edición in-place sin guardar."""
        if getattr(self, "_inline_editor", None):
            self._on_inline_editor_cancelled()

    def _on_inline_editor_committed(self, new_text: str):
        editor = getattr(self, "_inline_editor", None)
        if not editor:
            return
        editor._is_closing = True
        self._inline_editor = None
        editor.deleteLater()

        item = getattr(self, "_editing_item", None)
        annot_id = getattr(self, "_editing_annot_id", None)
        orig_content = getattr(self, "_editing_orig_content", "")
        self._editing_item = None
        self._editing_annot_id = None

        if annot_id:
            cleaned = new_text.strip()
            if not cleaned and not orig_content:
                cleaned = "Texto" if (item and getattr(item, "annot_type", "") == "text") else "Nota"
            if cleaned != orig_content:
                self.annotation_text_edited.emit(annot_id, orig_content, cleaned)

    def _on_inline_editor_cancelled(self):
        editor = getattr(self, "_inline_editor", None)
        if not editor:
            return
        editor._is_closing = True
        self._inline_editor = None
        editor.deleteLater()
        self._editing_item = None
        self._editing_annot_id = None

    def _update_inline_editor_pos(self):
        if not getattr(self, "_inline_editor", None) or not getattr(self, "_editing_item", None):
            return
        item = self._editing_item
        text_rect = item.get_text_rect()
        poly = item.mapToScene(text_rect)
        view_rect = self.mapFromScene(poly).boundingRect()
        w = max(view_rect.width(), 90.0)
        h = max(view_rect.height(), 32.0)
        self._inline_editor.setGeometry(int(view_rect.x() - 2), int(view_rect.y() - 2), int(w + 4), int(h + 4))

    def scrollContentsBy(self, dx: int, dy: int):
        super().scrollContentsBy(dx, dy)
        self._update_inline_editor_pos()

    # --- Gestión de Anotaciones en Escena ---

    def add_annotation_item(self, annot_data: dict) -> AnnotationGraphicsItem:
        """Instancia y añade un elemento gráfico de anotación a la escena."""
        item = AnnotationGraphicsItem(annot_data)
        item.setZValue(25)
        # Methods Down: estado inicial empujado por la vista
        item.set_view_scale(self._current_zoom)
        item.set_interaction_enabled(self._cursor_mgr.can_interact_with_annotations())
        # Signals Up: las señales del item se reenvían por las de la vista
        item.moved.connect(
            lambda annot_id, dx, dy: self.annotation_item_moved.emit(annot_id, dx, dy)
        )
        item.resized.connect(
            lambda annot_id, old_geom, new_geom: self.annotation_item_resized.emit(
                annot_id, old_geom, new_geom
            )
        )
        item.double_clicked.connect(
            lambda item_obj: self.annotation_double_clicked.emit(item_obj)
        )
        self._scene.addItem(item)
        self._annotation_items[item.annot_id] = item
        return item

    def get_annotation_item(self, annot_id: str) -> AnnotationGraphicsItem | None:
        """Obtiene el elemento gráfico correspondiente a un ID."""
        return self._annotation_items.get(annot_id)

    def remove_annotation_item(self, annot_id: str):
        """Remueve de la escena el elemento gráfico de una anotación."""
        item = self._annotation_items.pop(annot_id, None)
        if item and item.scene():
            self._scene.removeItem(item)

    def clear_annotation_selection(self):
        """Deselecciona todas las marcas y anotaciones en la escena."""
        if hasattr(self, "_scene") and self._scene:
            self._scene.clearSelection()

    def select_annotation_item(self, annot_id: str, clear_others: bool = True) -> bool:
        """Selecciona el elemento gráfico correspondiente al ID especificado."""
        if clear_others:
            self.clear_annotation_selection()
        item = self.get_annotation_item(annot_id)
        if item:
            item.setSelected(True)
            return True
        return False

    def clear_annotations(self):
        """Limpia todos los elementos de anotación de la escena."""
        for item in list(self._annotation_items.values()):
            if item.scene():
                self._scene.removeItem(item)
        self._annotation_items.clear()

    clear_annotation_items = clear_annotations

    def selected_items(self) -> list[QGraphicsItem]:
        """Retorna los items actualmente seleccionados en la escena (Methods Down)."""
        return self._scene.selectedItems()

    @property
    def search_matches(self) -> List[SearchMatch]:
        """Coincidencias de búsqueda activas en la página actual (solo lectura)."""
        return self._search_matches

    @property
    def current_match_idx(self) -> int:
        """Índice de la coincidencia de búsqueda activa (-1 si no hay)."""
        return self._current_match_idx

    def cancel_drawing_annotation(self) -> None:
        """Cancela un trazado de anotación en curso y limpia su previsualización."""
        if self._preview_item is not None and self._preview_item.scene() is not None:
            self._scene.removeItem(self._preview_item)
        self._preview_item = None
        self._is_drawing_annotation = False
        self._cursor_mgr.set_drawing_active(False)
        self._cursor_mgr.apply(self)

    def selected_annotations(self) -> list[AnnotationGraphicsItem]:
        """Retorna la lista de elementos de anotación actualmente seleccionados."""
        return [item for item in self._annotation_items.values() if item.isSelected()]

    # --- Sincronización descendente de estado a las anotaciones (Methods Down) ---

    def _sync_annotation_interaction(self) -> None:
        """
        Empuja a cada anotación si el modo de herramienta actual permite interactuar.

        Evita que las anotaciones consulten a la vista (hijo -> padre); la vista es
        quien decide y notifica.
        """
        enabled = self._cursor_mgr.can_interact_with_annotations()
        for item in self._annotation_items.values():
            item.set_interaction_enabled(enabled)

    def _sync_annotation_view_scale(self) -> None:
        """Empuja la escala de zoom actual a cada anotación (tiradores invariantes al zoom)."""
        for item in self._annotation_items.values():
            item.set_view_scale(self._current_zoom)

    def _compute_geometry(self, p1: QPointF, p2: QPointF) -> dict:
        """Calcula el diccionario de geometría en coordenadas de escena según la herramienta."""
        tool = self._annotation_tool
        if tool in ("line", "arrow"):
            return {
                "x1": round(p1.x(), 2),
                "y1": round(p1.y(), 2),
                "x2": round(p2.x(), 2),
                "y2": round(p2.y(), 2),
            }
        elif tool == "callout":
            bw = 120.0
            bh = 36.0
            return {
                "anchor_x": round(p1.x(), 2),
                "anchor_y": round(p1.y(), 2),
                "box_x": round(p2.x(), 2),
                "box_y": round(p2.y(), 2),
                "box_w": bw,
                "box_h": bh,
            }
        else:
            # rect, circle, cloud, text
            x = min(p1.x(), p2.x())
            y = min(p1.y(), p2.y())
            w = max(8.0, abs(p2.x() - p1.x()))
            h = max(8.0, abs(p2.y() - p1.y()))
            return {
                "x": round(x, 2),
                "y": round(y, 2),
                "w": round(w, 2),
                "h": round(h, 2),
            }

    def set_page_pixmap(self, pixmap: QPixmap, preserve_view: bool = False):
        saved_transform = QTransform(self.transform()) if preserve_view else None
        saved_zoom = self._current_zoom if preserve_view else 1.0
        saved_h_val = self.horizontalScrollBar().value() if preserve_view else 0
        saved_v_val = self.verticalScrollBar().value() if preserve_view else 0

        self._scene.clear()
        self._annotation_items.clear()
        self._selection_items.clear()
        self._match_items.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._update_scene_rect()

        if preserve_view and saved_transform:
            self.setTransform(saved_transform)
            self._current_zoom = saved_zoom
            self.horizontalScrollBar().setValue(saved_h_val)
            self.verticalScrollBar().setValue(saved_v_val)
            self.zoom_changed.emit(self._current_zoom * 100.0)
        else:
            self.fit_in_view()

        # Reasegurar cursor e interacción según la herramienta activa
        if self._tool_mode == ToolMode.PAN:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        elif getattr(self, "_annotation_tool", "select") != "select":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._tool_mode == ToolMode.TEXT_SELECT:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._restore_active_cursor()

    def get_mouse_scene_pos_if_inside_pdf(self) -> QPointF | None:
        """
        Retorna la coordenada de escena bajo el cursor actual del ratón
        únicamente si el cursor se encuentra dentro de los límites del plano PDF.
        Si el ratón está fuera del PDF o no hay plano cargado, retorna None.
        """
        if not self._pixmap_item:
            return None

        viewport = self.viewport()
        if not viewport:
            return None

        # 1. Obtener la posición física global del cursor del ratón y mapear a viewport
        global_pos = QCursor.pos()
        viewport_pos = viewport.mapFromGlobal(global_pos)

        # 2. Comprobar si el cursor está físicamente dentro del área del viewport
        if not viewport.rect().contains(viewport_pos):
            return None

        # 3. Mapear a coordenadas de la escena
        scene_pos = self.mapToScene(viewport_pos)

        # 4. Comprobar si incide dentro del rectángulo del plano PDF renderizado
        pdf_rect = self._pixmap_item.sceneBoundingRect()
        if not pdf_rect.contains(scene_pos):
            return None

        return scene_pos

    def fit_in_view(self):
        if self._pixmap_item and self.viewport().width() > 10 and self.viewport().height() > 10:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self._current_zoom = self.transform().m11()
            self._auto_fit = True
            self._sync_annotation_view_scale()
            self.zoom_changed.emit(self._current_zoom * 100.0)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        if self._pixmap_item and self._auto_fit:
            self.fit_in_view()

    def zoom_in(self):
        self._apply_zoom(1.25)

    def zoom_out(self):
        self._apply_zoom(0.8)

    def reset_zoom(self):
        self.fit_in_view()

    def clear(self):
        self.clear_selection()
        self.clear_search()
        self._scene.clear()
        self._pixmap_item = None
        self._page_text_data = None
        self._current_zoom = 1.0
        self._auto_fit = True
        self.resetTransform()
        self.zoom_changed.emit(100.0)

    def _apply_zoom(self, factor: float):
        self.commit_inline_text_edit()
        new_zoom = self._current_zoom * factor
        if 0.05 <= new_zoom <= 20.0:
            self.scale(factor, factor)
            self._current_zoom = new_zoom
            self._auto_fit = False
            self._sync_annotation_view_scale()
            self.zoom_changed.emit(self._current_zoom * 100.0)

    def wheelEvent(self, event: QWheelEvent):
        self.commit_inline_text_edit()
        angle = event.angleDelta().y()
        if angle > 0:
            self._apply_zoom(1.15)
        elif angle < 0:
            self._apply_zoom(1.0 / 1.15)
        event.accept()

    # --- Manejo de Eventos de Ratón y Teclado ---

    def enterEvent(self, event):
        super().enterEvent(event)
        self._restore_active_cursor()

    def keyPressEvent(self, event: QKeyEvent):
        # Deshacer con Ctrl+Z
        if event.matches(QKeySequence.StandardKey.Undo) or (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z
        ):
            mw = self.window()
            if hasattr(mw, "_undo_stack") and mw._undo_stack.canUndo():
                mw._undo_stack.undo()
                event.accept()
                return

        # Rehacer con Ctrl+Y o Ctrl+Shift+Z
        if event.matches(QKeySequence.StandardKey.Redo) or (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Y
        ) or (
            event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) and event.key() == Qt.Key.Key_Z
        ):
            mw = self.window()
            if hasattr(mw, "_undo_stack") and mw._undo_stack.canRedo():
                mw._undo_stack.redo()
                event.accept()
                return

        # Duplicar anotación con Ctrl+D
        if event.key() == Qt.Key.Key_D and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            sel_annots = self.selected_annotations()
            if sel_annots:
                self.request_duplicate_annotation.emit(sel_annots[0].annot_id)
                event.accept()
                return
        # Eliminar anotaciones seleccionadas con Delete o Backspace
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sel_annots = self.selected_annotations()
            if sel_annots:
                for item in sel_annots:
                    self.annotation_deleted.emit(item.annot_id)
                event.accept()
                return

        # Cancelar dibujo o volver a selección con Escape
        if event.key() == Qt.Key.Key_Escape:
            if getattr(self, "_is_drawing_annotation", False):
                self._is_drawing_annotation = False
                if self._preview_item and self._preview_item.scene():
                    self._scene.removeItem(self._preview_item)
                self._preview_item = None
                self._restore_active_cursor()
                event.accept()
                return
            elif getattr(self, "_annotation_tool", "select") != "select":
                self.set_annotation_tool("select")
                event.accept()
                return
            elif self._tool_mode != ToolMode.SELECT:
                self.set_tool_mode(ToolMode.SELECT)
                event.accept()
                return
            else:
                self._scene.clearSelection()
                self.clear_selection()
                event.accept()
                return

        # Copiar anotación o texto con Ctrl+C
        if event.matches(QKeySequence.StandardKey.Copy) or (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C
        ):
            sel_annots = self.selected_annotations()
            if sel_annots:
                self.request_copy_annotations.emit()
                event.accept()
                return
            elif self.copy_selection_to_clipboard():
                event.accept()
                return

        # Pegar con Ctrl+V en la posición actual del cursor del ratón (solo si está dentro del PDF)
        if event.matches(QKeySequence.StandardKey.Paste) or (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V
        ):
            scene_pos = self.get_mouse_scene_pos_if_inside_pdf()
            if scene_pos is not None:
                self.request_paste_annotations.emit(scene_pos)
            event.accept()
            return

        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        self._is_middle_panning = False
        self._restore_active_cursor()
        super().focusOutEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        self.setFocus()
        if getattr(self, "_inline_editor", None):
            self.commit_inline_text_edit()
        # 1. Paneo con botón central (siempre disponible independientemente del modo activo)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_middle_panning = True
            self._middle_pan_start = event.position().toPoint()
            self._cursor_mgr.set_panning(True)
            self._cursor_mgr.apply(self)
            event.accept()
            return

        # 2. Trazado interactivo de anotaciones si la herramienta no es 'select'
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, "_annotation_tool", "select") != "select":
            scene_pos = self.mapToScene(event.pos())
            self._is_drawing_annotation = True
            self._draw_start_pt = scene_pos
            self._draw_curr_pt = scene_pos

            tool_style = {"stroke_color": "#EC4899", "stroke_width": 2.0, "fill_color": "transparent"}
            mw = self.window()
            if hasattr(mw, "_property_inspector") and mw._property_inspector:
                defaults = mw._property_inspector.get_tool_defaults(self._annotation_tool)
                if defaults.get("style"):
                    tool_style.update(defaults["style"])

            preview_data = {
                "id": "__preview__",
                "type": self._annotation_tool,
                "geometry": self._compute_geometry(self._draw_start_pt, self._draw_curr_pt),
                "style": tool_style,
                "content": "Texto" if self._annotation_tool in ("text", "callout") else "",
            }
            self._preview_item = AnnotationGraphicsItem(preview_data)
            self._preview_item.setZValue(100)
            self._scene.addItem(self._preview_item)
            event.accept()
            return

        # 3. Selección de texto con botón izquierdo en modo TEXT_SELECT
        if event.button() == Qt.MouseButton.LeftButton and self._tool_mode == ToolMode.TEXT_SELECT:
            if self._page_text_data:
                scene_pos = self.mapToScene(event.pos())
                char_idx = self._page_text_data.get_char_index_at(scene_pos)
                if char_idx is not None:
                    self._is_selecting_text = True
                    self._sel_start_char_idx = char_idx
                    self._sel_end_char_idx = char_idx
                    text, rects = self._page_text_data.get_selection_range(char_idx, char_idx)
                    self._selected_text_str = text
                    self._render_selection_rects(rects)
                else:
                    self.clear_selection()
            event.accept()
            return

        # Si se hace clic en modo de selección de anotaciones, limpiar selección de texto activa
        if getattr(self, "_annotation_tool", "select") == "select" and self._selected_text_str:
            self.clear_selection()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Trazado en tiempo real de la anotación (rubber-banding)
        if getattr(self, "_is_drawing_annotation", False) and self._preview_item:
            self._draw_curr_pt = self.mapToScene(event.pos())
            self._preview_item.geometry_data = self._compute_geometry(self._draw_start_pt, self._draw_curr_pt)
            self._preview_item.rebuild_path()
            self._preview_item.update()
            event.accept()
            return

        # Paneo con botón central
        if self._is_middle_panning:
            delta = event.position().toPoint() - self._middle_pan_start
            self._middle_pan_start = event.position().toPoint()

            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            if h_bar:
                h_bar.setValue(h_bar.value() - delta.x())
            if v_bar:
                v_bar.setValue(v_bar.value() - delta.y())

            event.accept()
            return

        # Actualización continua de selección de texto al arrastrar el ratón
        if self._is_selecting_text and self._page_text_data and self._sel_start_char_idx is not None:
            scene_pos = self.mapToScene(event.pos())
            char_idx = self._page_text_data.get_char_index_at(scene_pos, threshold=60.0)
            if char_idx is not None and char_idx != self._sel_end_char_idx:
                self._sel_end_char_idx = char_idx
                text, rects = self._page_text_data.get_selection_range(
                    self._sel_start_char_idx, self._sel_end_char_idx
                )
                self._selected_text_str = text
                self._render_selection_rects(rects)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton and self._is_middle_panning:
            self._is_middle_panning = False
            self._cursor_mgr.set_panning(False)
            self._cursor_mgr.apply(self)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and getattr(self, "_is_drawing_annotation", False):
            self._is_drawing_annotation = False
            if self._preview_item:
                if self._preview_item.scene():
                    self._scene.removeItem(self._preview_item)
                self._preview_item = None

            end_pt = self.mapToScene(event.position().toPoint())
            dx = end_pt.x() - self._draw_start_pt.x()
            dy = end_pt.y() - self._draw_start_pt.y()
            if math.hypot(dx, dy) >= 6.0:
                geom = self._compute_geometry(self._draw_start_pt, end_pt)
                content = ""
                self.annotation_created.emit(self._annotation_tool, geom, "")
            self._restore_active_cursor()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._is_selecting_text:
            self._is_selecting_text = False
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        """
        Menú contextual dinámico sensible al tipo de selección activa en el plano.
        - Si hay texto seleccionado y el clic derecho ocurre sobre la selección: muestra 'Copiar' (Ctrl+C).
        - Si no hay selección activa (ni de texto ni de anotación): no hace nada.
        """
        scene_pos = self.mapToScene(event.pos())

        # 1. Comprobar si el clic derecho incide sobre una selección activa de texto
        if self._selected_text_str and self._selection_items:
            # Comprobar si la posición del clic está dentro de alguno de los rectángulos seleccionados
            clicked_on_selection = any(
                item.boundingRect().contains(scene_pos) or item.contains(scene_pos)
                for item in self._selection_items
            )

            if clicked_on_selection:
                menu = QMenu(self)
                menu.setObjectName("planContextMenu")

                act_copy = menu.addAction("Copiar")
                act_copy.setIcon(ThemeManager.get_icon("copy"))
                act_copy.setShortcut(QKeySequence.StandardKey.Copy)
                act_copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
                act_copy.triggered.connect(self.copy_selection_to_clipboard)

                menu.exec(event.globalPos())
                event.accept()
                return

        # 2. Comprobar si el clic derecho incide sobre una anotación
        items_at_pos = self.items(event.pos())
        annot_item = None
        for it in items_at_pos:
            if isinstance(it, AnnotationGraphicsItem):
                annot_item = it
                break

        if annot_item:
            if not annot_item.isSelected():
                self._scene.clearSelection()
                annot_item.setSelected(True)
            self._show_annotation_context_menu(annot_item, event.globalPos())
            event.accept()
            return

        # Si no se hizo clic sobre una anotación y había una herramienta de dibujo activa:
        # salir al modo puntero de selección (estilo CAD / Bluebeam)
        if getattr(self, "_annotation_tool", "select") != "select":
            self.set_annotation_tool("select")
            event.accept()
            return

        mw = self.window()
        if hasattr(mw, "_clipboard_annotations") and bool(mw._clipboard_annotations):
            menu = QMenu(self)
            menu.setObjectName("canvasContextMenu")
            act_paste = menu.addAction("Pegar")
            act_paste.setShortcut(QKeySequence.StandardKey.Paste)
            act_paste.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            act_paste.triggered.connect(lambda: self.request_paste_annotations.emit(scene_pos))
            menu.exec(event.globalPos())
            event.accept()
            return

        event.accept()

    def _on_scene_selection_changed(self):
        """Emite la anotación o anotaciones actualmente seleccionadas cuando cambia la selección en la escena."""
        sel = [it for it in self._scene.selectedItems() if isinstance(it, AnnotationGraphicsItem)]
        self.annotations_selected.emit(sel)
        if len(sel) == 1:
            self.annotation_selected.emit(sel[0])
        elif len(sel) == 0:
            self.annotation_selected.emit(None)

    def _create_annotation_context_menu(self, item: AnnotationGraphicsItem, global_pos=None) -> QMenu:
        """Crea y configura el menú contextual para una anotación."""
        menu = QMenu(self)
        menu.setObjectName("annotationContextMenu")

        act_props = menu.addAction("Propiedades...")
        act_props.setIcon(ThemeManager.get_icon("edit"))
        act_props.triggered.connect(lambda: self.request_inspect_annotation.emit(item.annot_id))

        # Auto-fit exclusivo para FreeText (texto) para convertir a figura pura según el texto
        selected_items = [it for it in self._scene.selectedItems() if isinstance(it, AnnotationGraphicsItem)]
        target_items = selected_items if (item.isSelected() and len(selected_items) > 1) else [item]

        text_items = [it for it in target_items if it.annot_type == "text"]
        if text_items:
            count = len(text_items)
            lbl = f"Ajustar al texto ({count})" if count > 1 else "Ajustar al texto (Auto-fit)"
            act_autofit = menu.addAction(lbl)
            act_autofit.setIcon(ThemeManager.get_icon("resize") or ThemeManager.get_icon("edit"))
            ids = [it.annot_id for it in text_items]
            act_autofit.triggered.connect(lambda _, tids=ids: self.request_autofit_annotation.emit(tids if len(tids) > 1 else tids[0]))

        menu.addSeparator()

        act_copy = menu.addAction("Copiar")
        act_copy.setIcon(ThemeManager.get_icon("copy"))
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        act_copy.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        act_copy.triggered.connect(lambda: self.request_copy_annotations.emit())

        scene_pos = self.mapToScene(self.viewport().mapFromGlobal(global_pos)) if (global_pos and self.viewport()) else None
        act_paste = menu.addAction("Pegar")
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        act_paste.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        act_paste.triggered.connect(lambda: self.request_paste_annotations.emit(scene_pos))

        act_dup = menu.addAction("Duplicar")
        act_dup.setIcon(ThemeManager.get_icon("duplicate"))
        act_dup.setShortcut(QKeySequence("Ctrl+D"))
        act_dup.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        act_dup.triggered.connect(lambda: self.request_duplicate_annotation.emit(item.annot_id))

        act_copy_id = menu.addAction("Copiar ID")
        act_copy_id.setIcon(ThemeManager.get_icon("copy"))
        act_copy_id.triggered.connect(lambda: QGuiApplication.clipboard().setText(item.annot_id))

        menu.addSeparator()

        act_front = menu.addAction("Traer al Frente")
        act_front.triggered.connect(lambda: self.request_reorder_annotation.emit(item.annot_id, "front"))

        act_back = menu.addAction("Enviar al Fondo")
        act_back.triggered.connect(lambda: self.request_reorder_annotation.emit(item.annot_id, "back"))

        menu.addSeparator()

        act_del = menu.addAction("Eliminar")
        act_del.setIcon(ThemeManager.get_icon("trash"))
        act_del.setShortcut(QKeySequence.StandardKey.Delete)
        act_del.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        act_del.triggered.connect(lambda: self.annotation_deleted.emit(item.annot_id))

        return menu

    def _show_annotation_context_menu(self, item: AnnotationGraphicsItem, global_pos):
        """Despliega el menú contextual enriquecido al hacer clic derecho en una anotación."""
        menu = self._create_annotation_context_menu(item, global_pos)
        menu.exec(global_pos)
