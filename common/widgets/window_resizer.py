"""
Filtro de eventos de redimensionamiento nativo para ventanas Frameless.
En Wayland (GNOME Mutter), startSystemResize(edges) es la ÚNICA forma permitida por el protocolo
para redimensionar bordes izquierdo y superior (ya que Wayland bloquea setGeometry/move manual).
"""

from __future__ import annotations
import sys
from PySide6.QtCore import QObject, QEvent, Qt, QPoint
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QSizeGrip
import shiboken6

from common.styles.style_manager import ThemeManager

BORDER_MARGIN = 8    # Margen perimetral para bordes rectos (L, R, T, B)
CORNER_MARGIN = 24   # Margen ampliado para esquinas (especialmente esquina inferior derecha con SizeGrip)
DEFAULT_TITLE_BAR_HEIGHT = 34
DEFAULT_WINDOW_CONTROLS_WIDTH = 135


class WindowResizeFilter(QObject):
    def __init__(
        self,
        window: QWidget,
        border_margin: int = BORDER_MARGIN,
        corner_margin: int = CORNER_MARGIN,
        exclude_widget: QWidget | None = None,
    ):
        super().__init__(window)
        self._window = window
        self.border_margin = border_margin
        self.corner_margin = corner_margin
        self._exclude_widget = exclude_widget

    def set_exclusion_widget(self, widget: QWidget | None) -> None:
        """Permite asignar explícitamente el contenedor de botones de la barra de título."""
        self._exclude_widget = widget

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not shiboken6.isValid(self._window) or self._window.isMaximized():
            return False

        if isinstance(watched, QWidget) and watched.window() != self._window:
            return False

        etype = event.type()
        if etype == QEvent.Type.MouseMove:
            return self._handle_mouse_move(event)
        elif etype == QEvent.Type.MouseButtonPress:
            return self._handle_mouse_press(event)

        return False

    def _is_excluded(self, global_pos: QPoint) -> bool:
        # Si se configuró un widget explícito de exclusión, usamos su geometría real
        if self._exclude_widget and shiboken6.isValid(self._exclude_widget):
            local_pos = self._exclude_widget.mapFromGlobal(global_pos)
            return self._exclude_widget.rect().contains(local_pos)

        # Fallback retrocompatible: exclusion fija por coordenadas de la barra superior derecha
        pos = self._window.mapFromGlobal(global_pos)
        x = pos.x()
        y = pos.y()
        w = self._window.width()
        return y <= DEFAULT_TITLE_BAR_HEIGHT and x >= (w - DEFAULT_WINDOW_CONTROLS_WIDTH)

    def _get_edges_at_global_pos(self, global_pos: QPoint) -> Qt.Edges:
        if self._is_excluded(global_pos):
            return Qt.Edges()

        pos = self._window.mapFromGlobal(global_pos)
        x = pos.x()
        y = pos.y()
        w = self._window.width()
        h = self._window.height()

        # 1. Esquinas con área activa para agarre cómodo
        if x >= w - self.corner_margin and y >= h - self.corner_margin:
            return Qt.Edge.RightEdge | Qt.Edge.BottomEdge
        if x <= self.corner_margin and y >= h - self.corner_margin:
            return Qt.Edge.LeftEdge | Qt.Edge.BottomEdge
        if x <= self.corner_margin and y <= self.corner_margin:
            return Qt.Edge.LeftEdge | Qt.Edge.TopEdge
        if x >= w - self.corner_margin and y <= self.corner_margin:
            return Qt.Edge.RightEdge | Qt.Edge.TopEdge

        # 2. Bordes perimetrales rectos
        edges = Qt.Edges()
        if -self.border_margin <= x <= self.border_margin:
            edges |= Qt.Edge.LeftEdge
        elif w - self.border_margin <= x <= w + self.border_margin:
            edges |= Qt.Edge.RightEdge

        if -self.border_margin <= y <= self.border_margin:
            edges |= Qt.Edge.TopEdge
        elif h - self.border_margin <= y <= h + self.border_margin:
            edges |= Qt.Edge.BottomEdge

        return edges

    def _update_cursor(self, edges: Qt.Edges) -> None:
        if not shiboken6.isValid(self._window):
            return

        if (edges & Qt.Edge.TopEdge and edges & Qt.Edge.LeftEdge) or \
           (edges & Qt.Edge.BottomEdge and edges & Qt.Edge.RightEdge):
            self._window.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (edges & Qt.Edge.TopEdge and edges & Qt.Edge.RightEdge) or \
             (edges & Qt.Edge.BottomEdge and edges & Qt.Edge.LeftEdge):
            self._window.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self._window.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            self._window.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self._window.unsetCursor()

    def _handle_mouse_move(self, event: QMouseEvent) -> bool:
        if not shiboken6.isValid(self._window):
            return False

        edges = self._get_edges_at_global_pos(event.globalPosition().toPoint())
        self._update_cursor(edges)
        return False

    def _handle_mouse_press(self, event: QMouseEvent) -> bool:
        if not shiboken6.isValid(self._window):
            return False

        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._get_edges_at_global_pos(event.globalPosition().toPoint())
            if edges:
                handle = self._window.windowHandle()
                if handle:
                    if handle.startSystemResize(edges):
                        event.accept()
                        return True

        return False


class ResizeGrip(QSizeGrip):
    """
    Control visual e interactivo de redimensionamiento ubicado en la esquina inferior derecha.
    Dibuja líneas diagonales de agarre limpias en armonía con el tema visual activo,
    con un área táctil amplia y cómoda para redimensionar la ventana fácilmente.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        normal_color: QColor | None = None,
        hover_color: QColor | None = None,
    ):
        super().__init__(parent)
        self.setFixedSize(24, 22)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Arrastrar para redimensionar ventana")
        self._is_hovered = False

        self._normal_color = normal_color
        self._hover_color = hover_color

    def set_colors(self, normal: QColor, hover: QColor) -> None:
        """Permite inyectar colores manualmente en cualquier momento."""
        self._normal_color = normal
        self._hover_color = hover
        self.update()

    def enterEvent(self, event) -> None:
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            if win:
                handle = win.windowHandle()
                if handle:
                    if handle.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
                        event.accept()
                        return
        super().mousePressEvent(event)

    def _resolve_color(self) -> QColor:
        """Resuelve el color del grip según el estado de hover y el tema activo."""
        # 1. Si fueron inyectados directamente por código, se usan de inmediato
        if self._normal_color and self._hover_color:
            return self._hover_color if self._is_hovered else self._normal_color

        # 2. Tokens del tema activo (ThemeManager centralizado)
        tok = ThemeManager.tokens()
        return QColor(tok.primary) if self._is_hovered else QColor(tok.text_secondary)

    def paintEvent(self, event) -> None:
        win = self.window()
        if win and win.isMaximized():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = self._resolve_color()
        pen = QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        w = self.width()
        h = self.height()

        # 3 líneas diagonales clásicas de resize grip con espaciado amplio y nítido
        painter.drawLine(w - 4, h - 7, w - 7, h - 4)
        painter.drawLine(w - 4, h - 12, w - 12, h - 4)
        painter.drawLine(w - 4, h - 17, w - 17, h - 4)