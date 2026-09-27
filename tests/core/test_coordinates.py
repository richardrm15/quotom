"""
Tests de ``core/coordinates.py`` — matemática pura PDF <-> escena Qt.

Este módulo es lógica de dominio: NO debe requerir Qt ni QApplication.
"""
from __future__ import annotations

import sys

from tests.support import run_standalone

from core.coordinates import (
    CoordinateConverter,
    pdf_to_scene_geometry,
    scene_to_pdf_geometry,
)

DIMS = (100.0, 200.0)  # (ancho_pts, alto_pts)


def test_pdf_to_scene_invierte_eje_y():
    """El origen cartesiano del PDF (abajo-izq) pasa a la esquina superior-izq de la escena."""
    x, y = CoordinateConverter.pdf_to_scene((0.0, 200.0), 2.0, *DIMS[::-1])
    assert (x, y) == (0.0, 0.0), (x, y)

    x, y = CoordinateConverter.pdf_to_scene((0.0, 0.0), 2.0, *DIMS[::-1])
    assert (x, y) == (0.0, 400.0), (x, y)


def test_pdf_to_scene_geometry_rect():
    """El rectángulo PDF se convierte a rectángulo de escena con Y invertida."""
    geom = pdf_to_scene_geometry(
        "rect", {"x": 0, "y": 0, "w": 10, "h": 20}, 2.0, DIMS
    )
    assert geom == {"x": 0.0, "y": 360.0, "w": 20.0, "h": 40.0}, geom


def test_scene_to_pdf_geometry_ida_y_vuelta():
    """La ida y vuelta PDF -> escena -> PDF es idempotente."""
    original = {"x": 5.0, "y": 15.0, "w": 10.0, "h": 20.0}
    scene = pdf_to_scene_geometry("rect", original, 2.0, DIMS)
    back = scene_to_pdf_geometry("rect", scene, 2.0, DIMS)
    for key in ("x", "y", "w", "h"):
        assert abs(back[key] - original[key]) < 1e-6, (key, back, original)


def test_geometry_acepta_json_string():
    """La geometría puede llegar serializada como JSON string."""
    geom = pdf_to_scene_geometry(
        "rect", '{"x": 0, "y": 0, "w": 10, "h": 20}', 2.0, DIMS
    )
    assert geom["w"] == 20.0 and geom["h"] == 40.0, geom


def test_escala_invalida_no_divide_por_cero():
    """Una escala <= 0 se normaliza a 1.0 en lugar de lanzar ZeroDivisionError."""
    x, y = CoordinateConverter.scene_to_pdf((10.0, 20.0), 0.0, 200.0, 100.0)
    assert x == 10.0 and y == 180.0, (x, y)


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
