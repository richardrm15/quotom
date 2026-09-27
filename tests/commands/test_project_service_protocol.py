"""
Contrato que consumen los comandos de renombrado del proyecto.

Tras el bloque S, ``core.services.ProjectService`` debe satisfacer
``ui.views.main_window.commands.ProjectServiceProtocol`` y ser lo que reciban los
comandos, de modo que la capa de comandos (única que toca Undo/Redo) no dependa
del repositorio ``ProjectManager``.
"""
from __future__ import annotations

import sys
import tempfile

from tests.support import app, run_standalone

from PySide6.QtGui import QUndoStack

from core.project import ProjectManager
from core.services import ProjectService
from ui.views.main_window.commands import (
    ProjectServiceProtocol,
    RenameDrawingCommand,
    RenamePageCommand,
)


def _new_service():
    """Crea un proyecto temporal y devuelve un ``ProjectService`` ya abierto."""
    tmp = tempfile.mkdtemp(prefix="quotom_cmd_")
    svc = ProjectService()
    svc.create(tmp, "Comandos")
    return svc


def test_project_service_cumple_el_protocolo():
    """La capa de dominio satisface el contrato de los comandos."""
    assert isinstance(ProjectService(), ProjectServiceProtocol)


def test_project_manager_tambien_cumple_el_protocolo():
    """Compatibilidad: el repositorio sigue satisfaciendo el mismo contrato."""
    assert isinstance(ProjectManager(), ProjectServiceProtocol)


def test_rename_drawing_retorna_dict():
    """El protocolo exige un dict (``redo``/``undo`` del comando lo usan)."""
    svc = _new_service()
    try:
        drawing_id = svc.manager.db.add_drawing(svc.info.id, "drawings/A.pdf", "A", 4)
        result = svc.rename_drawing(drawing_id, "Planta Baja")
        assert isinstance(result, dict)
        assert result["name"] == "Planta Baja"
    finally:
        svc.close()


def test_comando_renombrar_plano_usa_el_servicio():
    """``RenameDrawingCommand`` renombra y revierte a través del servicio."""
    _ = app()
    svc = _new_service()
    try:
        drawing_id = svc.manager.db.add_drawing(svc.info.id, "drawings/A.pdf", "A", 2)
        stack = QUndoStack()
        stack.push(RenameDrawingCommand(svc, drawing_id, "A", "Planta Baja"))
        assert svc.drawings.get(drawing_id).name == "Planta Baja"
        stack.undo()
        assert svc.drawings.get(drawing_id).name == "A"
    finally:
        svc.close()


def test_comando_renombrar_pagina_usa_el_servicio():
    """``RenamePageCommand`` escribe y revierte el nombre de página vía servicio."""
    _ = app()
    svc = _new_service()
    try:
        drawing_id = svc.manager.db.add_drawing(svc.info.id, "drawings/A.pdf", "A", 3)
        inicial = svc.drawings.page_names(drawing_id)[0]

        stack = QUndoStack()
        stack.push(RenamePageCommand(svc, drawing_id, 0, inicial, "Planta Baja"))
        assert svc.drawings.page_names(drawing_id)[0] == "Planta Baja"
        stack.undo()
        assert svc.drawings.page_names(drawing_id)[0] == inicial
    finally:
        svc.close()


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
