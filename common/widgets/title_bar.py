"""
Barra de título personalizada (Custom Title Bar / CSD) estilo VS Code / Blender.
Botones vectoriales dibujados con QPainter nativo (sin caracteres Unicode defectuosos).
"""

from __future__ import annotations
import sys
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
)
from common.styles.style_manager import ThemeManager

class WindowControlButton(QPushButton):
    """Botón de control de ventana (minimizar, maximizar, cerrar) con dibujo vectorial nativo."""

    def __init__(self, action_type: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.action_type = action_type  # 'min', 'max', 'close'
        self.is_maximized = False
        self.setFixedSize(44, 34)

    def _resolve_color(self) -> QColor:
        """Resuelve el color del trazo del control según el estado y el tema activo."""
        if self.action_type == "close" and self.underMouse():
            return ThemeManager.color("text_on_primary")
        return (
            ThemeManager.color("icon_hover")
            if self.underMouse()
            else ThemeManager.color("icon_default")
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        pen = QPen(self._resolve_color(), 1.2)
        painter.setPen(pen)

        cx = self.width() // 2
        cy = self.height() // 2

        if self.action_type == "min":
            painter.drawLine(cx - 5, cy, cx + 5, cy)
        elif self.action_type == "max":
            if not self.is_maximized:
                painter.drawRect(cx - 5, cy - 5, 10, 10)
            else:
                painter.drawRect(cx - 3, cy - 5, 8, 8)
                painter.drawRect(cx - 5, cy - 3, 8, 8)
        elif self.action_type == "close":
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
            painter.drawLine(cx + 4, cy - 4, cx - 4, cy + 4)

        painter.end()


class CustomTitleBar(QWidget):
    """
    Barra de título CSD desacoplada.
    Soporta Wayland nativo (startSystemMove), centrado simétrico automático
    y contenedor unificado para botones de control.
    """

    def __init__(
        self,
        parent: QWidget,
        title: str = "BMS BidSuite - Take-Off Viewer",
        supports_saving: bool = False,
    ):
        super().__init__(parent)
        self._parent = parent
        self._window = parent
        self._drag_pos = QPoint()
        self.system_move_enabled = True

        self.setFixedHeight(34)
        self.setObjectName("customTitleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Contenedor unificado de controles (derecha)
        self.controls_widget = QWidget(self)
        self.controls_widget.setObjectName("windowControlsContainer")
        controls_layout = QHBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)

        self._btn_min = WindowControlButton("min", self.controls_widget)
        self._btn_min.setObjectName("winMinButton")
        self._btn_min.setToolTip("Minimizar")
        self._btn_min.clicked.connect(self._window.showMinimized)

        self._btn_max = WindowControlButton("max", self.controls_widget)
        self._btn_max.setObjectName("winMaxButton")
        self._btn_max.setToolTip("Maximizar")
        self._btn_max.clicked.connect(self._toggle_max_restore)

        self._btn_close = WindowControlButton("close", self.controls_widget)
        self._btn_close.setObjectName("winCloseButton")
        self._btn_close.setToolTip("Cerrar")
        self._btn_close.clicked.connect(self._window.close)

        controls_layout.addWidget(self._btn_min)
        controls_layout.addWidget(self._btn_max)
        controls_layout.addWidget(self._btn_close)

        # 2. Espaciador izquierdo para centrar simétricamente el título (44px * 3 = 132px)
        controls_total_width = 44 * 3
        self._balance_left = QWidget(self)
        self._balance_left.setFixedSize(controls_total_width, 34)
        self._balance_left.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._balance_left, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addStretch(1)

        # 3. Zona central (Título centrado limpio)
        center_widget = QWidget(self)
        center_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        center_layout = QHBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._lbl_title = QLabel(title, center_widget)
        self._lbl_title.setObjectName("titleLabel")
        self._lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self._lbl_title)

        self._lbl_save_badge = None
        self._save_timer = None

        layout.addWidget(center_widget, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

        # 4. Añadir controles a la derecha
        layout.addWidget(self.controls_widget, 0, Qt.AlignmentFlag.AlignRight)

    def set_title(self, title: str) -> None:
        self._lbl_title.setText(title)

    def apply_theme(self) -> None:
        """Repinta la barra de título tras un cambio de tema (Methods Down)."""
        self.update()

    def sync_window_state(self) -> None:
        """Sincroniza el icono de maximizar con el estado real de la ventana."""
        is_max = self._window.isMaximized()
        if self._btn_max.is_maximized != is_max:
            self._btn_max.is_maximized = is_max
            self._btn_max.setToolTip("Restaurar" if is_max else "Maximizar")
            self._btn_max.update()

    def _toggle_max_restore(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_window_state()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            sync_active = getattr(self._window, "_sync_with_parent", False)
            handle = self._window.windowHandle()

            # `startSystemMove` existe desde Qt 5.15 (el proyecto exige PySide6 >= 6.6):
            # no se comprueba la capacidad, solo que haya ventana nativa.
            if self.system_move_enabled and not sync_active and handle:
                if handle.startSystemMove():
                    event.accept()
                    return

            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            sync_active = getattr(self._window, "_sync_with_parent", False)
            handle = self._window.windowHandle()

            if sync_active or not handle:
                self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max_restore()
            event.accept()

    def notify_saved(self, text: str = "✓ Guardado") -> None:
        pass