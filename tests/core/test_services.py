"""
Tests de `core/services/` — casos de uso del núcleo.

Se ejecutan **sin iniciar Qt** (Regla 20): los servicios son dominio puro y usan
un proyecto temporal real en disco (SQLite + carpeta ``drawings/``).
"""
from __future__ import annotations

import sys
import tempfile

from tests.support import imported_top_level_modules, run_standalone

from core.models import Annotation, Drawing, Project
from core.services import AnnotationService, DrawingService, ProjectService


def _new_project():
    """Crea un proyecto temporal y retorna (servicio, carpeta temporal)."""
    tmp = tempfile.mkdtemp(prefix="quotom_svc_")
    svc = ProjectService()
    svc.create(tmp, "Servicios")
    return svc, tmp


def test_project_service_crea_y_cierra():
    """`create` devuelve un modelo `Project` y `close` desactiva el servicio."""
    svc, _ = _new_project()
    try:
        assert isinstance(svc.info, Project)
        assert svc.info.name == "Servicios"
        assert svc.is_active is True
        assert svc.drawings_dir is not None and svc.drawings_dir.name == "drawings"
    finally:
        svc.close()
    assert svc.is_active is False
    assert svc.info is None


def test_servicios_expuestos_por_project_service():
    """`ProjectService` expone los servicios de planos y anotaciones."""
    svc, _ = _new_project()
    try:
        assert isinstance(svc.drawings, DrawingService)
        assert isinstance(svc.annotations, AnnotationService)
    finally:
        svc.close()


def test_drawing_service_sin_proyecto_es_seguro():
    """Sin proyecto activo los servicios responden vacío/None sin lanzar."""
    svc = ProjectService()
    assert svc.drawings.is_available is False
    assert svc.drawings.list() == []
    assert svc.drawings.get(1) is None
    assert svc.drawings.last_page("/x.pdf") == 0
    assert svc.annotations.get("nope") is None
    assert svc.annotations.for_page(1, 0) == []


def test_drawing_service_devuelve_modelos():
    """`DrawingService` devuelve modelos `Drawing`, no diccionarios."""
    svc, _ = _new_project()
    try:
        project_id = svc.manager.project_info["id"]
        drawing_id = svc.manager.db.add_drawing(project_id, "drawings/A.pdf", "A", 12)

        drawing = svc.drawings.get(drawing_id)
        assert isinstance(drawing, Drawing)
        assert (drawing.name, drawing.page_count) == ("A", 12)

        assert [d.name for d in svc.drawings.list()] == ["A"]
        assert svc.drawings.find(drawing_id).id == drawing_id
    finally:
        svc.close()


def test_drawing_service_renombra_y_borra():
    """Renombrar devuelve el modelo actualizado; borrar deja la lista vacía."""
    svc, _ = _new_project()
    try:
        project_id = svc.manager.project_info["id"]
        drawing_id = svc.manager.db.add_drawing(project_id, "drawings/A.pdf", "A", 3)

        renamed = svc.drawings.rename(drawing_id, "Planta Baja")
        assert isinstance(renamed, Drawing)
        assert renamed.name == "Planta Baja"
        assert renamed.path.endswith(".pdf"), "debe conservar la extensión"

        svc.drawings.delete(drawing_id, delete_file=False)
        assert svc.drawings.list() == []
    finally:
        svc.close()


def test_drawing_service_nombres_de_pagina():
    """Los nombres de página se leen y escriben a través del servicio."""
    svc, _ = _new_project()
    try:
        project_id = svc.manager.project_info["id"]
        drawing_id = svc.manager.db.add_drawing(project_id, "drawings/A.pdf", "A", 2)

        svc.drawings.set_page_name(drawing_id, 0, "Planta Baja")
        names = svc.drawings.page_names(drawing_id)
        assert names[0] == "Planta Baja"
    finally:
        svc.close()


def test_annotation_service_crud_y_regla_iso():
    """El servicio crea/lee/actualiza/borra anotaciones aplicando la regla ISO."""
    svc, _ = _new_project()
    try:
        project_id = svc.manager.project_info["id"]
        drawing_id = svc.manager.db.add_drawing(project_id, "drawings/A.pdf", "A", 5)

        created = svc.annotations.create(
            drawing_id=drawing_id,
            page_index=1,
            annot_type="rect",
            geometry={"x": 1, "y": 2, "w": 3, "h": 4},
            style={"stroke_color": "#FF0000"},
        )
        assert isinstance(created, Annotation)
        assert created.style.get("/C"), "el servicio debe normalizar el estilo a ISO"

        fetched = svc.annotations.get(created.id)
        assert fetched.id == created.id
        assert len(svc.annotations.for_page(drawing_id, 1)) == 1

        updated = svc.annotations.update(created.id, {"content": "Hola"})
        assert updated.content == "Hola"

        assert svc.annotations.delete(created.id, soft=True) is True
        assert svc.annotations.get(created.id).is_deleted is True

        restored = svc.annotations.restore(created.id)
        assert restored is not None and restored.is_deleted is False
    finally:
        svc.close()


def test_annotation_service_sin_proyecto_es_seguro():
    """Sin proyecto activo las escrituras devuelven None/False sin lanzar."""
    svc = ProjectService()
    assert svc.annotations.create(1, 0, "rect", {}, {}) is None
    assert svc.annotations.update("x", {}) is None
    assert svc.annotations.delete("x") is False
    assert svc.annotations.restore("x") is None


def test_services_no_importan_qt():
    """Guardarraíl: los servicios son dominio puro (Regla 3/20)."""
    prohibidos = {"PySide6", "PyQt5", "PyQt6"}
    for modulo in (ProjectService, DrawingService, AnnotationService):
        import importlib
        mod = importlib.import_module(modulo.__module__)
        assert not (imported_top_level_modules(mod) & prohibidos), modulo.__module__


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
