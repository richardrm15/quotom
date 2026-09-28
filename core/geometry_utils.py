"""
Utilidades de geometría pura del dominio (sin Qt).

El auto-ajuste de texto que necesita fuentes de Qt vive en
``common.helpers.text_metrics`` (reglas 3/10/15/20).
"""
from __future__ import annotations

import copy


def shift_geometry(geometry: dict, *args, **kwargs) -> dict:
    """
    Aplica un desplazamiento cartesiano (dx, dy) a cualquier tipo de geometría de anotación
    (línea, flecha, rectángulo, callout, nube, etc.).
    Soporta tanto shift_geometry(geom, dx, dy) como shift_geometry(geom, annot_type, dx, dy).
    """
    if len(args) == 3:
        dx, dy = float(args[1]), float(args[2])
    elif len(args) == 2:
        dx, dy = float(args[0]), float(args[1])
    else:
        dx = float(kwargs.get("dx", 0.0))
        dy = float(kwargs.get("dy", 0.0))

    new_geom = copy.deepcopy(geometry)
    for k in ("x", "x1", "x2", "anchor_x", "box_x"):
        if k in new_geom:
            new_geom[k] = float(new_geom[k]) + dx
    for k in ("y", "y1", "y2", "anchor_y", "box_y"):
        if k in new_geom:
            new_geom[k] = float(new_geom[k]) + dy
    if "points" in new_geom and isinstance(new_geom["points"], list):
        new_geom["points"] = [[float(p[0]) + dx, float(p[1]) + dy] for p in new_geom["points"]]
    return new_geom


__all__ = ["shift_geometry"]
