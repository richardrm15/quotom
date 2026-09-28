"""
Tests de `core/text_geometry.py` — geometría pura del dominio.

Se ejecutan **sin Qt** (R1/15 y R20): verifican que los tipos puros replican la
semántica de `QRectF`/`QPointF` y que `core/` ya no depende de PySide6.
"""
from __future__ import annotations

import sys

from tests.support import imported_top_level_modules, run_standalone

from core.text_geometry import Point, PointLike, Rect, RectLike
from core.text_layer import CharBox, PageTextData


def test_rect_api_de_lectura_como_qrectf():
    """`Rect` expone las mismas lecturas que `QRectF`."""
    r = Rect(10.0, 20.0, 30.0, 40.0)
    assert (r.x(), r.y()) == (10.0, 20.0)
    assert (r.width(), r.height()) == (30.0, 40.0)
    assert (r.left(), r.top()) == (10.0, 20.0)
    assert (r.right(), r.bottom()) == (40.0, 60.0)


def test_point_center_de_rect():
    """`center()` devuelve un `Point` con las coordenadas del centro."""
    c = Rect(4.0, 8.0, 20.0, 10.0).center()
    assert isinstance(c, Point)
    assert (c.x(), c.y()) == (14.0, 13.0)


def test_contains_incluye_bordes():
    """`contains` es inclusivo en los bordes, igual que `QRectF`."""
    r = Rect(0.0, 0.0, 10.0, 10.0)
    assert r.contains(Point(5.0, 5.0)) is True
    assert r.contains(Point(0.0, 0.0)) is True
    assert r.contains(Point(10.0, 10.0)) is True
    assert r.contains(Point(10.1, 5.0)) is False


def test_intersects_y_tocar_borde_no_cuenta():
    """Rectángulos que solo comparten borde no se consideran intersecados."""
    a = Rect(0.0, 0.0, 10.0, 10.0)
    assert a.intersects(Rect(5.0, 5.0, 10.0, 10.0)) is True
    assert a.intersects(Rect(10.0, 0.0, 5.0, 5.0)) is False
    assert a.intersects(Rect(20.0, 20.0, 1.0, 1.0)) is False


def test_united_y_adjusted():
    """`united` da el mínimo rectángulo contenedor y `adjusted` mueve los bordes."""
    u = Rect(0.0, 0.0, 10.0, 10.0).united(Rect(20.0, 30.0, 5.0, 5.0))
    assert (u.x(), u.y(), u.width(), u.height()) == (0.0, 0.0, 25.0, 35.0)

    a = Rect(10.0, 10.0, 10.0, 10.0).adjusted(-2.0, -3.0, 4.0, 5.0)
    assert (a.x(), a.y(), a.width(), a.height()) == (8.0, 7.0, 16.0, 18.0)


def test_rect_es_inmutable_y_comparable():
    """`Rect` es inmutable, comparable por valor y hasheable."""
    assert Rect(1.0, 2.0, 3.0, 4.0) == Rect(1.0, 2.0, 3.0, 4.0)
    assert Rect(1.0, 2.0, 3.0, 4.0) == (1.0, 2.0, 3.0, 4.0)
    assert len({Rect(1.0, 2.0, 3.0, 4.0), Rect(1.0, 2.0, 3.0, 4.0)}) == 1
    try:
        Rect(1.0, 2.0, 3.0, 4.0)._x = 9.0
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Rect debería ser inmutable")


def test_estructura_compatible_con_qrectf():
    """Los `Protocol` documentan el tipado estructural (un QRectF encajaría)."""
    assert isinstance(Rect(0, 0, 1, 1), RectLike)
    assert isinstance(Point(0, 0), PointLike)
    assert not isinstance("no-rect", RectLike)


def test_merge_rects_agrupa_texto_horizontal():
    """`_merge_rects` fusiona cajas contiguas de la misma línea y separa líneas."""
    linea = [CharBox(index=i, char="a", rect=Rect(i * 10.0, 0.0, 10.0, 12.0)) for i in range(4)]
    otra = [CharBox(index=9, char="b", rect=Rect(0.0, 100.0, 10.0, 12.0))]

    merged = PageTextData._merge_rects([cb.rect for cb in linea + otra])
    assert len(merged) == 2, "debe fusionar la línea y separar la caja lejana"
    assert merged[0].width() == 40.0


def test_serializacion_round_trip():
    """`__getstate__`/`__setstate__` conservan cajas, texto e índice espacial."""
    data = PageTextData(page_index=0, width_pts=612.0, height_pts=792.0, scale=1.0)
    data.char_boxes = [
        CharBox(index=0, char="A", rect=Rect(1.0, 2.0, 3.0, 4.0)),
        CharBox(index=1, char="B", rect=Rect(5.0, 6.0, 7.0, 8.0)),
    ]
    data.full_text = "AB"

    clon = PageTextData(0, 0.0, 0.0, 1.0)
    clon.__setstate__(data.__getstate__())

    assert clon.full_text == "AB"
    assert clon.char_boxes[1].rect == Rect(5.0, 6.0, 7.0, 8.0)


def test_busqueda_devuelve_rects_puros():
    """`search_matches` devuelve `Rect` del dominio, no tipos de Qt."""
    data = PageTextData(page_index=0, width_pts=100.0, height_pts=100.0, scale=1.0)
    data.full_text = "PLANTA"
    data.char_boxes = [
        CharBox(index=i, char=ch, rect=Rect(i * 8.0, 0.0, 8.0, 10.0))
        for i, ch in enumerate("PLANTA")
    ]

    matches = data.search_matches("PLANTA")
    assert len(matches) == 1
    assert all(isinstance(r, Rect) for r in matches[0].rects)


def test_core_no_importa_qt():
    """Guardarraíl: los módulos de geometría y texto del núcleo son dominio puro."""
    import importlib

    prohibidos = {"PySide6", "PyQt5", "PyQt6"}
    for nombre in ("core.text_geometry", "core.text_layer", "core.ocr_engine", "core.geometry_utils"):
        mod = importlib.import_module(nombre)
        assert not (imported_top_level_modules(mod) & prohibidos), nombre


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
