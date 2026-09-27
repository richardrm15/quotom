"""
Test de integración del ``AnnotationController`` tras migrarlo a ``AnnotationService``.

Objetivo (Regla 8): el controlador ya **no** accede a ``project_mgr.db``; todo el CRUD
pasa por el servicio de dominio. Este test ejercita el ciclo completo contra un
proyecto temporal real: crear → leer → actualizar → borrar (lógico) → restaurar.
"""
from __future__ import annotations

import inspect
import sys
import tempfile

from tests.support import apply_theme_once, app, run_standalone, teardown_widgets

from PySide6.QtGui import QUndoStack

from common.widgets.graphics_view import PlanGraphicsView
from core.project import ProjectManager
from core.services import AnnotationService, ProjectService
from ui.views.project_editor.annotation_controller import AnnotationController

DIMS = (612.0, 792.0)  # tamaño carta en puntos


def _setup():
    """Crea proyecto temporal + plano y un ``AnnotationController`` cableado."""
    _ = app()
    apply_theme_once()
    tmp = tempfile.mkdtemp(prefix="quotom_annot_ctrl_")
    mgr = ProjectManager()
    mgr.create_project(tmp, "Integración")
    project_id = mgr.project_info["id"]
    drawing_id = mgr.db.add_drawing(project_id, "drawings/A.pdf", "A", 5)

    viewer = PlanGraphicsView()
    undo = QUndoStack()
    ctrl = AnnotationController(viewer, ProjectService(mgr), undo)
    ctrl.set_document_context(str(mgr.resolve_path("drawings/A.pdf")), 0, 1.0, DIMS)
    return mgr, ctrl, viewer, undo, drawing_id


def test_controller_no_accede_a_la_bd():
    """Guardarraíl estático: no quedan accesos directos a ``db`` en el controlador."""
    source = inspect.getsource(sys.modules[AnnotationController.__module__])
    assert "self._db" not in source, "el controlador sigue usando self._db"
    assert "_project_mgr.db" not in source, "el controlador sigue usando project_mgr.db"
    assert "_annotation_svc" in source, "el controlador debe usar el servicio de dominio"
    assert "_project_svc" in source, "el controlador debe usar el servicio de proyecto"


def test_clipboard_no_accede_a_la_bd():
    """Guardarraíl estático: el portapapeles tampoco toca SQLite directamente."""
    from ui.views.project_editor import clipboard as clipboard_mod

    source = inspect.getsource(clipboard_mod)
    assert ".db." not in source, "el portapapeles sigue accediendo a la base de datos"
    assert "project_mgr.db" not in source, "el portapapeles sigue usando project_mgr.db"


def test_crud_completo_a_traves_del_servicio():
    """Crear/leer/actualizar/borrar/restaurar funcionan y persisten en SQLite."""
    mgr, ctrl, viewer, undo, drawing_id = _setup()
    svc = AnnotationService(mgr)
    try:
        # --- Estado inicial (sin anotaciones) ---
        recibido = {}
        ctrl.markups_updated.connect(lambda l, p: recibido.update(items=l, page=p))
        ctrl.load_annotations_for_page(page_index=0)
        assert recibido["items"] == []

        # --- Crear (el controlador persiste vía AnnotationService) ---
        ctrl.on_annotation_created("rect", {"x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0})
        stored = svc.for_page(drawing_id, 0)
        assert len(stored) == 1, "la anotación no se persistió"

        annot_id = stored[0].id
        assert viewer.get_annotation_item(annot_id) is not None, "no se dibujó en el canvas"

        # --- Recargar desde disco (camino de lectura del servicio) ---
        ctrl.load_annotations_for_page(page_index=0)
        assert [a["id"] for a in recibido["items"]] == [annot_id]
        assert recibido["items"][0]["page_name"] == "Página 1"

        # --- Actualizar (aplica el servicio) ---
        ctrl.apply_annotation_state(annot_id, {"content": "Muro de carga"})
        assert svc.get(annot_id).content == "Muro de carga"

        # --- Actualizar vía Undo/Redo (el comando ejecuta en redo) ---
        ctrl.mutate_annotation(annot_id, {"content": "Muro de carga"}, {"content": "Muro"})
        assert svc.get(annot_id).content == "Muro"

        # --- Borrado lógico ---
        ctrl.remove_annotation(annot_id)
        assert svc.get(annot_id).is_deleted is True
        assert viewer.get_annotation_item(annot_id) is None

        # --- Restauración (Undo del borrado) ---
        ctrl.restore_annotation({"id": annot_id, "page_index": 0})
        assert svc.get(annot_id).is_deleted is False
        assert viewer.get_annotation_item(annot_id) is not None

        # --- Borrado en lote (macro Undo) ---
        ctrl.on_annotation_deleted([annot_id])
        assert svc.get(annot_id).is_deleted is True
    finally:
        teardown_widgets(viewer)
        mgr.close_project()


def test_helpers_retornan_diccionarios_compatibles():
    """Los helpers internos siguen entregando dicts con las claves que consume la UI."""
    mgr, ctrl, viewer, undo, drawing_id = _setup()
    try:
        ctrl.on_annotation_created("rect", {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0})
        annot_id = AnnotationService(mgr).for_page(drawing_id, 0)[0].id

        annot, item = ctrl._get_annot_and_item(annot_id)
        assert isinstance(annot, dict), "la UI espera un dict, no un modelo"
        assert item is not None
        for clave in ("id", "type", "geometry", "style", "page_index", "page_name", "/C"):
            assert clave in annot, f"falta la clave '{clave}' en el contrato de la UI"

        capturado = {}
        ctrl.annotations_inspected.connect(lambda lst: capturado.update(lista=lst))
        ctrl.on_annotations_selected([item, item])  # 2 items -> ruta de selección múltiple
        assert capturado["lista"] and isinstance(capturado["lista"][0], dict)

        capturado1 = {}
        ctrl.annotation_inspected.connect(lambda d: capturado1.update(data=d))
        ctrl.on_annotation_selected(item)
        assert capturado1["data"]["id"] == annot_id
    finally:
        teardown_widgets(viewer)
        mgr.close_project()


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
