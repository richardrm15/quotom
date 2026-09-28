"""
Módulo unificado de Iconos Vectoriales Nativos.
"""

from PySide6.QtGui import QIcon
from .base import render_icon
from .navigation import NAVIGATION_ICONS
from .actions import ACTIONS_ICONS
from .editor_tools import EDITOR_ICONS
from .ui_elements import UI_ICONS

DRAW_FUNCS = {
    **NAVIGATION_ICONS,
    **ACTIONS_ICONS,
    **EDITOR_ICONS,
    **UI_ICONS,
}


def get_icon(name: str, color_hex: str = "#CCCCCC", size: int = 20) -> QIcon:
    func = DRAW_FUNCS.get(name)
    if not func:
        return QIcon()
    return render_icon(func, color_hex=color_hex, size=size)


__all__ = ["get_icon", "DRAW_FUNCS"]