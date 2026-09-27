"""
Servicio de planos (``DrawingService``) — casos de uso sobre los PDF del proyecto.

Responsabilidades:
* Custodia de archivos (importación, renombrado, borrado físico).
* Metadatos del plano (páginas, última página vista, nombres de página).

Devuelve **modelos** ``Drawing`` en lugar de diccionarios crudos, de forma que los
controladores no necesiten conocer el esquema de ``project.db``.

Es un servicio de dominio puro (sin Qt): depende explícitamente del ``ProjectManager``
que actúa como repositorio/espacio de trabajo.
"""
from __future__ import annotations

from pathlib import Path

from core.models import Drawing
from core.project import ProjectManager


class DrawingService:
    """Casos de uso sobre los planos (drawings) del proyecto activo."""

    def __init__(self, manager: ProjectManager):
        self._manager = manager

    # ------------------------------------------------------------------ Estado

    @property
    def is_available(self) -> bool:
        """Indica si hay un proyecto activo con base de datos lista."""
        return self._manager.is_active and self._manager.db is not None

    def _wrap(self, row: dict | None) -> Drawing | None:
        """Convierte una fila de la base de datos en un modelo ``Drawing``."""
        if not row:
            return None
        return Drawing.from_row(row, abs_path=str(row.get("abs_path") or ""))

    # -------------------------------------------------------------- Consultas

    def list(self) -> list[Drawing]:
        """Retorna todos los planos del proyecto activo."""
        if not self._manager.is_active:
            return []
        return [d for d in (self._wrap(r) for r in self._manager.get_drawings()) if d]

    def get(self, drawing_id: int) -> Drawing | None:
        """Obtiene un plano por su ID (``None`` si no existe o no hay proyecto)."""
        if not self.is_available:
            return None
        return self._wrap(self._manager.db.get_drawing(drawing_id))

    def find(self, pdf_path_or_id: Path | str | int) -> Drawing | None:
        """Busca un plano por ruta (absoluta/relativa) o por ID."""
        if not self._manager.is_active:
            return None
        return self._wrap(self._manager.find_drawing(pdf_path_or_id))

    def last_page(self, pdf_path_or_id: Path | str | int) -> int:
        """Última página vista guardada para el plano (0 si no hay datos)."""
        if not self._manager.is_active:
            return 0
        return int(self._manager.get_drawing_last_page(pdf_path_or_id))

    def page_names(self, pdf_path_or_id: Path | str | int) -> list[str]:
        """Nombres de página del plano (personalizados o autogenerados)."""
        if not self._manager.is_active:
            return []
        return list(self._manager.get_drawing_page_names(pdf_path_or_id))

    # -------------------------------------------------------------- Comandos

    def import_from(self, source_pdf: Path | str, custom_name: str | None = None) -> Drawing:
        """
        Importa un PDF al proyecto (copia a ``drawings/`` y registra metadatos).

        Raises:
            RuntimeError: Si no hay proyecto activo.
            FileNotFoundError: Si el PDF de origen no existe.
        """
        row = self._manager.import_drawing(source_pdf, custom_name)
        drawing = self._wrap(row)
        if drawing is None:  # pragma: no cover - defensivo
            raise RuntimeError(f"No se pudo registrar el plano importado: {source_pdf}")
        return drawing

    def rename(self, drawing_id: int, new_name: str) -> Drawing | None:
        """Renombra el plano (archivo físico + metadatos) y retorna el modelo actualizado."""
        return self._wrap(self._manager.rename_drawing(drawing_id, new_name))

    def delete(self, drawing_id: int, delete_file: bool = True) -> None:
        """Elimina el plano del proyecto y, opcionalmente, su archivo de custodia."""
        self._manager.delete_drawing(drawing_id, delete_file=delete_file)

    def update_last_page(self, pdf_path_or_id: Path | str | int, page_index: int) -> None:
        """Guarda la última página visualizada del plano."""
        self._manager.update_drawing_last_page(pdf_path_or_id, page_index)

    def set_page_name(
        self, pdf_path_or_id: Path | str | int, page_index: int, new_name: str
    ) -> None:
        """Guarda el nombre personalizado de una página individual."""
        self._manager.set_drawing_page_name(pdf_path_or_id, page_index, new_name)

    def sync_page_count(
        self, pdf_path_or_id: Path | str | int, page_count: int
    ) -> Drawing | None:
        """Sincroniza el número real de páginas del plano (idempotente)."""
        if not self.is_available:
            return None
        return self._wrap(self._manager.sync_drawing_page_count(pdf_path_or_id, page_count))


__all__ = ["DrawingService"]
