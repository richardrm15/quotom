"""
Barra de herramientas lateral tipo pestañas (Side Tab Bar / Activity Bar).
Dockeada en el borde izquierdo para alternar paneles de herramientas,
comenzando con el explorador de archivos del proyecto.
"""

from typing import Callable
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QToolButton
from common.styles.style_manager import ThemeManager


class SideTabBar(QWidget):
    """Barra lateral vertical de pestañas ubicada en el borde de la aplicación."""

    tab_toggled = Signal(str, bool)

    def __init__(self, parent=None, position: str = "left"):
        super().__init__(parent)
        self._position = position
        self.setObjectName("sideTabBar" if position == "left" else "rightTabBar")
        self.setFixedWidth(42)

        self._tabs: dict[str, dict] = {}

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(3, 6, 3, 6)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._layout.addStretch(1)

    def add_tab(self, tab_id: str, icon_name: str, tooltip: str, on_click: Callable | None = None) -> QToolButton:
        """Agrega una pestaña a la barra lateral vertical."""
        btn = QToolButton(self)
        btn.setProperty("class", "sideTabButton")
        btn.setObjectName(f"sideTab_{tab_id}")
        btn.setFixedSize(36, 36)
        btn.setIconSize(QSize(20, 20))
        btn.setCheckable(True)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.ArrowCursor)

        icon = ThemeManager.get_icon(icon_name)
        btn.setIcon(icon)

        if on_click:
            btn.clicked.connect(on_click)

        btn.toggled.connect(lambda checked: self.tab_toggled.emit(tab_id, checked))

        count = self._layout.count()
        self._layout.insertWidget(count - 1, btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self._tabs[tab_id] = {
            "button": btn,
            "icon_name": icon_name,
        }
        return btn

    def set_tab_checked(self, tab_id: str, checked: bool):
        if tab_id in self._tabs:
            btn = self._tabs[tab_id]["button"]
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)

    def is_tab_checked(self, tab_id: str) -> bool:
        if tab_id in self._tabs:
            return self._tabs[tab_id]["button"].isChecked()
        return False

    def set_active_tab(self, active_tab_id: str | None):
        """Marca como activa una pestaña y desmarca el resto (para alternancia de futuros paneles)."""
        for tab_id, info in self._tabs.items():
            btn = info["button"]
            btn.blockSignals(True)
            btn.setChecked(tab_id == active_tab_id)
            btn.blockSignals(False)

    def get_tab_button(self, tab_id: str) -> QToolButton | None:
        if tab_id in self._tabs:
            return self._tabs[tab_id]["button"]
        return None

    def apply_theme(self):
        """Actualiza los iconos de todas las pestañas al cambiar de tema."""
        for info in self._tabs.values():
            btn = info["button"]
            icon_name = info["icon_name"]
            btn.setIcon(ThemeManager.get_icon(icon_name))


RightTabBar = SideTabBar
