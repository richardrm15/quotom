"""
Medición de texto y auto-ajuste de contenedores de anotación.

Vive en ``ui/`` (no en ``core/``) porque depende de las fuentes de Qt
(``QFont``/``QFontMetricsF``): el dominio debe permanecer libre de Qt
(reglas 3/10/15/20). La geometría pura —``shift_geometry``— sigue en
``core.geometry_utils``.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QFont, QFontMetricsF

__all__ = ["measure_text_block", "calculate_autofit_scene_geometry"]


def measure_text_block(content: str, style_data: dict) -> tuple[float, float]:
    """Mide (ancho, alto) del bloque de texto con la fuente indicada en el estilo."""
    font = QFont(style_data.get("font_family", "sans-serif"), int(float(style_data.get("font_size", 11.0))))
    if style_data.get("font_bold", False):
        font.setBold(True)
    if style_data.get("font_italic", False):
        font.setItalic(True)

    fm = QFontMetricsF(font)
    lines = content.splitlines() if content else ["Texto"]
    max_line_w = max((fm.horizontalAdvance(line) for line in lines), default=40.0)
    total_text_h = fm.height() * max(1, len(lines))
    return max(24.0, max_line_w), max(16.0, total_text_h)


def calculate_autofit_scene_geometry(content: str, style_data: dict, current_scene_geom: dict) -> dict:
    """
    Calcula las dimensiones simétricas óptimas (círculo, hexágono, triángulo o caja rectangular)
    para ajustar el contenedor al tamaño del texto proporcionado, manteniendo el centro de la figura.
    """
    shape = style_data.get("shape", "rect")
    tw, th = measure_text_block(content, style_data)

    gx = float(current_scene_geom.get("x", 0))
    gy = float(current_scene_geom.get("y", 0))
    gw = float(current_scene_geom.get("w", 120))
    gh = float(current_scene_geom.get("h", 32))
    cx = gx + gw / 2.0
    cy = gy + gh / 2.0

    if shape in ("circle", "ellipse"):
        r = max(20.0, 0.5 * math.hypot(tw, th) + 12.0)
        new_w, new_h = 2.0 * r, 2.0 * r
    elif shape == "hexagon":
        r = max(22.0, (tw + 20.0) / 1.25, (th + 16.0) / 1.15)
        new_w, new_h = 2.0 * r, 1.7320508 * r
    elif shape == "triangle":
        r = max(24.0, (tw + 20.0) / 1.05, (th + 16.0) / 0.75)
        new_w, new_h = 1.7320508 * r, 1.5 * r
    else:
        side = max(tw + 20.0, th + 16.0, 40.0)
        new_w, new_h = side, side

    return {
        "x": round(cx - new_w / 2.0, 2),
        "y": round(cy - new_h / 2.0, 2),
        "w": round(new_w, 2),
        "h": round(new_h, 2),
    }
