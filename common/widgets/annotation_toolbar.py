"""
Barra de Herramientas de Anotaciones y Marcado (Annotation Toolbar).

Widget vertical desacoplado para seleccionar herramientas de dibujo y colocado
de anotaciones sobre planos PDF (ISO 128 / ISO 32000):
- Líneas y Flechas (line, arrow)
- Figuras geométricas (rect, circle)
- Nube de revisión (cloud)
- Comentarios y llamadas (text, callout)
"""

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QToolButton,
    QButtonGroup,
    QFrame,
)
from common.styles.style_manager import ThemeManager


class AnnotationToolBar(QWidget):
    """Barra vertical compacta de herramientas de anotación y marcado."""

    tool_changed = Signal(str)  # Emite el id de la herramienta seleccionada

    TOOLS = [
        ("line", "line", "Línea simple (2)"),
        ("arrow", "arrow", "Flecha directriz (3)"),
        ("---", None, None),
        ("rect", "rect", "Rectángulo (4)"),
        ("circle", "circle", "Círculo / Elipse (5)"),
        ("cloud", "cloud", "Nube de Revisión (6)"),
        ("---", None, None),
        ("text", "text", "Texto libre (7)"),
        ("callout", "callout", "Llamada / Callout con flecha (8)"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("annotationToolBar")
        self.setFixedWidth(44)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        self._current_tool: str = ""

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 8, 4, 8)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._build_tools()
        self.apply_theme()

    def _build_tools(self):
        for tool_id, icon_name, tooltip in self.TOOLS:
            if tool_id == "---":
                sep = QFrame(self)
                sep.setObjectName("toolSeparator")
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                sep.setFixedHeight(1)
                self._layout.addWidget(sep)
                continue

            btn = QToolButton(self)
            btn.setObjectName(f"toolBtn_{tool_id}")
            btn.setFixedSize(34, 34)
            btn.setIconSize(QSize(18, 18))
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.ArrowCursor)

            if icon_name:
                btn.setIcon(ThemeManager.get_icon(icon_name))

            btn.clicked.connect(lambda checked, tid=tool_id: self._on_btn_clicked(tid))
            self._button_group.addButton(btn)
            self._buttons[tool_id] = btn
            self._layout.addWidget(btn)

    def _on_btn_clicked(self, tool_id: str):
        if self._current_tool == tool_id:
            self.clear_selection()
            self.tool_changed.emit("select")
            return

        self._current_tool = tool_id
        self.tool_changed.emit(tool_id)

    def clear_selection(self):
        """Deselecciona cualquier herramienta de anotación activa."""
        self._button_group.setExclusive(False)
        for btn in self._buttons.values():
            btn.setChecked(False)
        self._button_group.setExclusive(True)
        self._current_tool = ""

    def set_active_tool(self, tool_id: str):
        """Activa programáticamente una herramienta sin romper la exclusión mutua."""
        if tool_id == self._current_tool:
            return
        if tool_id in self._buttons:
            self._buttons[tool_id].setChecked(True)
            self._current_tool = tool_id
            self.tool_changed.emit(tool_id)
        elif tool_id in ("select", ""):
            self.clear_selection()

    def current_tool(self) -> str:
        """Retorna el identificador de la herramienta activa."""
        return self._current_tool

    def apply_theme(self):
        """
        Actualiza los iconos vectoriales según el tema activo (Methods Down).

        El estilo del contenedor, de los botones y de los separadores vive en
        ``common/styles/theme.qss``; aquí solo se regeneran los iconos, que no son
        expresables en QSS.
        """
        for tool_id, icon_name, _ in self.TOOLS:
            if icon_name and tool_id in self._buttons:
                self._buttons[tool_id].setIcon(ThemeManager.get_icon(icon_name))
