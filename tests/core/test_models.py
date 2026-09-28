"""
Tests de `core/models.py` — modelos de dominio puros.

Deben poder ejecutarse **sin iniciar Qt** (R20).
"""
from __future__ import annotations

import sys

from tests.support import run_standalone

from core.models import (
    Annotation,
    Drawing,
    DrawingPage,
    Project,
    annotations_from_rows,
    drawings_from_rows,
)


def test_project_from_row_y_vuelta():
    """`Project` se construye desde una fila y serializa al contrato de la UI."""
    p = Project.from_row({"id": 1, "name": "Obra X", "created_at": "2025-01-01"})
    assert (p.id, p.name) == (1, "Obra X")
    assert p.to_dict() == {"id": 1, "name": "Obra X", "created_at": "2025-01-01"}


def test_drawing_normaliza_tipos_y_ruta_absoluta():
    """`Drawing` tolera `None`/strings numéricos y admite la ruta absoluta resuelta."""
    d = Drawing.from_row(
        {"id": "7", "project_id": "2", "path": "drawings/A.pdf", "name": "A",
         "page_count": None, "last_page": "3"}
    )
    assert (d.id, d.project_id, d.page_count, d.last_page) == (7, 2, 0, 3)

    con_ruta = d.with_abs_path("/tmp/proy/drawings/A.pdf")
    assert con_ruta.abs_path.endswith("A.pdf")
    assert d.abs_path == "", "with_abs_path no debe mutar el original (frozen)"


def test_annotation_parsea_json_serializado():
    """`Annotation.from_row` deserializa geometry/style/tags/properties/ports."""
    a = Annotation.from_row({
        "id": "uuid-1", "drawing_id": 4, "page_index": 2, "type": "rect",
        "geometry": '{"x": 1, "y": 2, "w": 3, "h": 4}',
        "style": '{"stroke_color": "#FF0000"}',
        "tags": '["a", "b"]',
        "properties": '{"discipline": "Eléctrico"}',
        "ports": '[{"id": "p1"}]',
        "content": "Hola", "author": "Ana",
    })
    assert a.geometry["w"] == 3
    assert a.style["stroke_color"] == "#FF0000"
    assert a.tags == ["a", "b"]
    assert a.ports == [{"id": "p1"}]
    assert a.page_name == "Página 3"


def test_annotation_tolera_json_corrupto():
    """Un JSON inválido degrada a valores vacíos en lugar de lanzar excepción."""
    a = Annotation.from_row({
        "id": "u", "drawing_id": 1, "page_index": 0, "type": "line",
        "geometry": "{no-json", "style": "tampoco", "tags": "{x}", "properties": "[]",
    })
    assert a.geometry == {} and a.style == {} and a.tags == []
    assert a.properties == {}


def test_annotation_disciplina_e_iso32000():
    """La disciplina cae a `layer`/`General` y `to_dict` expone las claves ISO."""
    a = Annotation.from_row({
        "id": "u", "drawing_id": 1, "page_index": 0, "type": "rect",
        "style": {"stroke_color": "#00FF00", "/C": [0, 1, 0], "/CA": 1.0},
        "layer": "E-LUM", "status": "Accepted", "content": "Txt", "author": "Luis",
    })
    assert a.discipline == "E-LUM"

    data = a.to_dict()
    assert data["/OC"] == "E-LUM"
    assert data["/T"] == "Luis"
    assert data["/State"] == "Accepted"
    assert data["/StateModel"] == "Review"
    assert data["/C"] == [0, 1, 0]
    assert data["/Contents"] == "Txt"
    # El contrato original debe conservarse
    for key in ("id", "drawing_id", "page_index", "type", "geometry", "style",
                "content", "subject", "layer", "status", "tags", "properties",
                "ports", "item_id", "tag_number", "author", "discipline", "page_name"):
        assert key in data, f"falta la clave heredada '{key}'"


def test_annotation_property_tiene_prioridad_en_disciplina():
    """`properties.discipline` manda sobre `layer`."""
    a = Annotation.from_row({
        "id": "u", "drawing_id": 1, "page_index": 0, "type": "rect",
        "properties": '{"discipline": "Mecánico"}', "layer": "General",
    })
    assert a.discipline == "Mecánico"


def test_annotation_borrado_logico():
    """`is_deleted` refleja `deleted_at`."""
    base = {"id": "u", "drawing_id": 1, "page_index": 0, "type": "rect"}
    assert Annotation.from_row(base).is_deleted is False
    assert Annotation.from_row({**base, "deleted_at": "2025-01-01"}).is_deleted is True


def test_drawing_page_display_name():
    """`DrawingPage` autogenera el nombre si viene vacío."""
    assert DrawingPage(2, "Planta Baja").display_name == "Planta Baja"
    assert DrawingPage(2, "").display_name == "Página 3"


def test_helpers_de_colecciones():
    """Los helpers convierten secuencias de filas."""
    assert len(drawings_from_rows([{"id": 1, "project_id": 1, "path": "", "name": "A"}])) == 1
    assert len(annotations_from_rows([{"id": "u", "drawing_id": 1, "page_index": 0,
                                       "type": "rect"}])) == 1


def test_models_no_importa_qt():
    """Guardarraíl: `core/models.py` es dominio puro (R1/15 y R20)."""
    from tests.support import imported_top_level_modules

    import core.models as module

    prohibidos = {"PySide6", "PyQt5", "PyQt6"}
    assert not (imported_top_level_modules(module) & prohibidos)


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
