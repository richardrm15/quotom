from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from PySide6.QtGui import QUndoCommand

logger = logging.getLogger("quotom.commands.main_window")


# Contrato explícito de lo que estos comandos esperan que el servicio sepa hacer.
# Es runtime_checkable para poder verificar el cumplimiento en tests.
@runtime_checkable
class ProjectServiceProtocol(Protocol):
    """
    Contrato de mutación que consumen los comandos de renombrado.

    Lo satisfacen tanto ``core.services.ProjectService`` (capa de dominio, la ruta
    recomendada) como ``core.project.ProjectManager`` (repositorio), de modo que los
    comandos no dependen de una implementación concreta.
    """

    def rename_drawing(self, drawing_id: int, new_name: str) -> dict:
        ...

    def set_drawing_page_name(
        self, drawing_id: int, page_index: int, new_name: str
    ) -> None:
        ...


class RenameDrawingCommand(QUndoCommand):
    """Comando reversible para renombrar un plano en el proyecto."""

    def __init__(
        self,
        project_service: ProjectServiceProtocol,
        drawing_id: int,
        old_name: str,
        new_name: str,
    ):
        super().__init__(f"Renombrar plano a '{new_name}'")
        self._service = project_service
        self._drawing_id = drawing_id
        self._old_name = old_name
        self._new_name = new_name

    def redo(self) -> None:
        try:
            self._service.rename_drawing(self._drawing_id, self._new_name)
        except Exception as e:
            logger.error("Error al renombrar plano (redo): %s", e)

    def undo(self) -> None:
        try:
            self._service.rename_drawing(self._drawing_id, self._old_name)
        except Exception as e:
            logger.error("Error al revertir renombrado de plano (undo): %s", e)


class RenamePageCommand(QUndoCommand):
    """Comando reversible para renombrar una página de un plano."""

    def __init__(
        self,
        project_service: ProjectServiceProtocol,
        drawing_id: int,
        page_index: int,
        old_name: str,
        new_name: str,
    ):
        super().__init__(f"Renombrar página a '{new_name}'")
        self._service = project_service
        self._drawing_id = drawing_id
        self._page_index = page_index
        self._old_name = old_name
        self._new_name = new_name

    def redo(self) -> None:
        try:
            self._service.set_drawing_page_name(
                self._drawing_id, self._page_index, self._new_name
            )
        except Exception as e:
            logger.error("Error al renombrar página (redo): %s", e)

    def undo(self) -> None:
        try:
            self._service.set_drawing_page_name(
                self._drawing_id, self._page_index, self._old_name
            )
        except Exception as e:
            logger.error("Error al revertir renombrado de página (undo): %s", e)