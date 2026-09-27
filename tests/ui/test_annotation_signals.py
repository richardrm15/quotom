"""
Tests de desacoplamiento del canvas (Regla 1: Methods Down, Signals Up).

Verifica que ``AnnotationGraphicsItem`` no consulta a su vista y que
``PlanGraphicsView`` reenvía sus señales y empuja el estado hacia abajo.
"""
from __future__ import annotations

import sys

from tests.support import app, run_standalone

from common.widgets.graphics_view import PlanGraphicsView

ANNOT = {
    "id": "a1",
    "type": "rect",
    "scene_geometry": {"x": 0, "y": 0, "w": 50, "h": 40},
    "style": {
        "stroke_color": "#3B82F6",
        "stroke_width": 2.0,
        "fill_color": "transparent",
    },
}


def test_item_no_conoce_a_su_vista():
    """El item no debe leer ``scene().views()`` ni consultar al contenedor."""
    import inspect

    from common.widgets import annotation_item

    source = inspect.getsource(annotation_item)
    assert "scene().views()" not in source, "El item sigue consultando a su vista"
    assert "hasattr(" not in source, "El item usa hasattr()"
    assert "getattr(" not in source, "El item usa getattr()"


def test_signals_up_del_item_llegan_a_la_vista():
    """Las señales del item se reenvían por las señales públicas de la vista."""
    _ = app()
    view = PlanGraphicsView()

    captured = {}
    view.annotation_item_moved.connect(lambda i, dx, dy: captured.setdefault("moved", (i, dx, dy)))
    view.annotation_item_resized.connect(lambda i, o, n: captured.setdefault("resized", (i, o, n)))
    view.annotation_double_clicked.connect(lambda obj: captured.setdefault("double", obj))

    item = view.add_annotation_item(ANNOT)
    assert view.get_annotation_item("a1") is item

    item.moved.emit("a1", 3.0, -2.0)
    item.resized.emit("a1", {"x": 0}, {"x": 5})
    item.double_clicked.emit(item)

    assert captured["moved"] == ("a1", 3.0, -2.0)
    assert captured["resized"] == ("a1", {"x": 0}, {"x": 5})
    assert captured["double"] is item


def test_methods_down_estado_inicial_y_cambio_de_modo():
    """La vista empuja interacción y escala al item (el hijo nunca pregunta)."""
    _ = app()
    view = PlanGraphicsView()
    item = view.add_annotation_item(ANNOT)

    assert item._view_scale == view._current_zoom
    assert item._interaction_enabled is True

    view.set_tool_mode("pan")
    assert item._interaction_enabled is False, "pan debe deshabilitar la interacción"

    view.set_tool_mode("select")
    assert item._interaction_enabled is True, "select debe habilitarla de nuevo"


def test_zoom_empuja_escala_a_las_anotaciones():
    """Al cambiar el zoom, la vista informa la nueva escala a cada anotación."""
    _ = app()
    view = PlanGraphicsView()
    item = view.add_annotation_item(ANNOT)

    view._current_zoom = 1.0
    view._apply_zoom(2.0)
    assert item._view_scale == view._current_zoom


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
