"""
Módulo Desacoplado de Gestión y Resolución de Cursores (Cursor Manager).

Centraliza la máquina de estados de los cursores, prioridades de interacción
y sincronización unificada con la vista y el viewport de Qt.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView


class ViewerCursorManager:
    """
    Gestor desacoplado del estado del cursor para visores CAD/PDF.
    
    Jerarquía de Prioridades:
    1. Acción Activa (Arrastre con botón central, redimensión de tirador, arrastre de elementos).
    2. Modificador Temporal / Override forzado.
    3. Hover sobre Tiradores o Elementos (solo si la herramienta lo permite).
    4. Cursor por Defecto de la Herramienta Activa (select, pan, text_select, dibujo).
    """

    def __init__(self, view: QGraphicsView | None = None):
        self._view: QGraphicsView | None = view
        self._tool_mode: str = "select"          # "select", "pan", "text_select"
        self._drawing_tool: str = "select"       # "select", "rect", "line", etc.
        self._is_panning: bool = False           # Paneo activo (ej. botón central presionado)
        self._is_resizing: bool = False          # Redimensión activa de tirador
        self._active_handle: str | None = None   # Tirador actualmente arrastrado
        self._is_drawing_active: bool = False    # Arrastrando para trazar una forma
        self._override_cursor: Qt.CursorShape | None = None

    # --- Configuración de Estados ---

    def set_tool_mode(self, mode: str):
        """Establece el modo base ('select', 'pan', 'text_select')."""
        self._tool_mode = str(mode)

    def tool_mode(self) -> str:
        return self._tool_mode

    def set_drawing_tool(self, tool_id: str):
        """Establece la herramienta de anotación activa ('select', 'rect', 'line', etc.)."""
        self._drawing_tool = str(tool_id)

    def drawing_tool(self) -> str:
        return self._drawing_tool

    def set_panning(self, is_panning: bool):
        """Activa o desactiva el estado de paneo con botón central o arrastre de mano."""
        self._is_panning = is_panning

    def is_panning(self) -> bool:
        return self._is_panning

    def set_resizing(self, is_resizing: bool, handle: str | None = None):
        """Activa o desactiva el estado de redimensión activa de un tirador."""
        self._is_resizing = is_resizing
        self._active_handle = handle if is_resizing else None

    def set_drawing_active(self, is_drawing: bool):
        """Activa o desactiva el estado de trazado activo en el lienzo."""
        self._is_drawing_active = is_drawing

    def set_override(self, cursor: Qt.CursorShape | None):
        """Fuerza temporalmente un cursor específico con máxima prioridad."""
        self._override_cursor = cursor

    # --- Reglas de Interacción ---

    def can_interact_with_annotations(self) -> bool:
        """
        Determina si el modo actual permite que las anotaciones muestren tiradores,
        reaccionen al hover y cambien el cursor inteligentemente.
        """
        if self._tool_mode in ("pan", "text_select"):
            return False
        if self._drawing_tool != "select":
            return False
        if self._is_drawing_active or self._is_panning:
            return False
        return True

    # --- Resolución de Cursores ---

    def resolve_cursor(self) -> Qt.CursorShape:
        """
        Resuelve el cursor final aplicando la jerarquía de prioridades estricta.
        """
        # Prioridad 1: Acción de Paneo Activa (botón central)
        if self._is_panning:
            return Qt.CursorShape.ClosedHandCursor

        # Prioridad 2: Redimensión de tirador activa
        if self._is_resizing and self._active_handle:
            return self.get_handle_cursor(self._active_handle)

        # Prioridad 3: Override forzado
        if self._override_cursor is not None:
            return self._override_cursor

        # Prioridad 4: Herramienta de dibujo activa (todas las anotaciones comparten el cursor cruz de colocación/trazado)
        if self._drawing_tool in ("line", "arrow", "rect", "circle", "cloud", "text", "callout"):
            return Qt.CursorShape.CrossCursor

        # Prioridad 5: Modo de herramienta base
        if self._tool_mode == "pan":
            return Qt.CursorShape.OpenHandCursor
        elif self._tool_mode == "text_select":
            return Qt.CursorShape.IBeamCursor

        # Modo Selección estándar por defecto
        return Qt.CursorShape.ArrowCursor

    # --- Métodos de Utilidad Estáticos ---

    @staticmethod
    def get_handle_cursor(handle: str | None) -> Qt.CursorShape:
        """Retorna el cursor direccional exacto correspondiente al tirador especificado."""
        if handle in ("tl", "br"):
            return Qt.CursorShape.SizeFDiagCursor
        elif handle in ("tr", "bl"):
            return Qt.CursorShape.SizeBDiagCursor
        elif handle in ("p1", "p2", "anchor"):
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.SizeAllCursor

    @staticmethod
    def get_item_hover_cursor(handle: str | None, can_interact: bool) -> Qt.CursorShape:
        """
        Calcula el cursor para hover sobre una anotación (tirador o cuerpo).
        Si no se permite interacción, retorna ArrowCursor.
        """
        if not can_interact:
            return Qt.CursorShape.ArrowCursor
        if handle:
            return ViewerCursorManager.get_handle_cursor(handle)
        return Qt.CursorShape.SizeAllCursor

    # --- Sincronización con Qt ---

    def apply(self, view: QGraphicsView | None = None):
        """
        Aplica de forma unificada el cursor resuelto tanto al widget principal
        como al viewport interno de la vista (evitando el trap de cursor de Qt).
        """
        v = view or self._view
        if not v:
            return
        cursor = self.resolve_cursor()
        super(QGraphicsView, v).setCursor(cursor)
        viewport = v.viewport()
        if viewport:
            viewport.setCursor(cursor)
