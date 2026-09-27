"""
Servicio de proyecto (``ProjectService``) — ciclo de vida del espacio de trabajo.

Es el punto de entrada del dominio: gestiona crear/abrir/cerrar el proyecto y expone
los servicios especializados de planos y anotaciones, que comparten el mismo
repositorio (``ProjectManager``).

Servicio de dominio puro (sin Qt). Devuelve modelos ``Project``.
"""
from __future__ import annotations

from pathlib import Path

from core.models import Project
from core.project import ProjectManager
from core.services.annotation_service import AnnotationService
from core.services.drawing_service import DrawingService


class ProjectService:
    """Ciclo de vida del proyecto activo y acceso a sus servicios de dominio."""

    def __init__(self, manager: ProjectManager | None = None):
        self._manager = manager or ProjectManager()
        self.drawings = DrawingService(self._manager)
        self.annotations = AnnotationService(self._manager)

    # ------------------------------------------------------------------ Estado

    @property
    def manager(self) -> ProjectManager:
        """Repositorio/espacio de trabajo subyacente (uso de bajo nivel)."""
        return self._manager

    @property
    def is_active(self) -> bool:
        """Indica si hay un proyecto abierto."""
        return self._manager.is_active

    @property
    def info(self) -> Project | None:
        """Metadatos del proyecto activo como modelo de dominio."""
        data = self._manager.project_info
        return Project.from_row(data) if data else None

    @property
    def root_dir(self) -> Path | None:
        """Carpeta raíz del proyecto activo."""
        return self._manager.root_dir

    @property
    def drawings_dir(self) -> Path | None:
        """Carpeta ``drawings/`` donde se custodian los planos."""
        return self._manager.drawings_dir

    def resolve_path(self, relative_path: str | Path) -> Path | None:
        """Resuelve una ruta relativa del proyecto a ruta absoluta."""
        return self._manager.resolve_path(relative_path) if relative_path else None

    def to_relative(self, abs_or_rel_path: str | Path) -> str:
        """Convierte una ruta a su forma relativa al proyecto (``drawings/x.pdf``)."""
        return self._manager.get_relative_path(abs_or_rel_path)

    # -------------------------------------------------------------- Comandos

    def create(self, folder: Path | str, name: str) -> Project:
        """
        Crea un proyecto nuevo con su estructura estándar (``drawings/`` + ``project.db``).

        Raises:
            ValueError: Si el nombre está vacío.
        """
        return Project.from_row(self._manager.create_project(folder, name))

    def open(self, folder: Path | str) -> Project:
        """
        Abre un proyecto existente (inicializa lo que falte de forma resiliente).

        Raises:
            FileNotFoundError: Si la carpeta no existe.
        """
        return Project.from_row(self._manager.open_project(folder))

    def close(self) -> None:
        """Cierra el proyecto activo y desconecta la base de datos."""
        self._manager.close_project()

    # =========================================================================
    # CONTRATO DE MUTACIÓN (consumido por los comandos de Undo/Redo)
    # =========================================================================
    # Estos dos métodos hacen que ``ProjectService`` satisfaga
    # ``ui.views.main_window.commands.ProjectServiceProtocol``, el contrato que
    # esperan ``RenameDrawingCommand`` y ``RenamePageCommand``. Así los comandos
    # dependen de la capa de dominio y no del repositorio (``ProjectManager``).

    def rename_drawing(self, drawing_id: int, new_name: str) -> dict:
        """Renombra un plano y retorna su registro como diccionario."""
        drawing = self.drawings.rename(drawing_id, new_name)
        return drawing.to_dict() if drawing else {}

    def set_drawing_page_name(self, drawing_id: int, page_index: int, new_name: str) -> None:
        """Guarda el nombre personalizado de una página del plano."""
        self.drawings.set_page_name(drawing_id, page_index, new_name)


__all__ = ["ProjectService"]
