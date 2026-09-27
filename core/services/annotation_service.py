"""
Servicio de anotaciones (``AnnotationService``) — casos de uso sobre las marcas.

Responsabilidades:
* CRUD de anotaciones (crear, leer, actualizar, borrado lógico, restaurar).
* Aplicar la **regla de estilo** de dominio (``normalize_style_iso``) al escribir,
  garantizando que lo persistido ya cumple ISO 32000-1.
* Devolver **modelos** ``Annotation`` en lugar de diccionarios crudos de SQLite.

Servicio de dominio puro (sin Qt), con dependencia explícita del ``ProjectManager``.
"""
from __future__ import annotations

from typing import Any

from core.business_rules import normalize_style_iso
from core.models import Annotation
from core.project import ProjectManager


class AnnotationService:
    """Casos de uso sobre las anotaciones del proyecto activo."""

    def __init__(self, manager: ProjectManager):
        self._manager = manager

    # ------------------------------------------------------------------ Estado

    @property
    def is_available(self) -> bool:
        """Indica si hay un proyecto activo con base de datos lista."""
        return self._manager.is_active and self._manager.db is not None

    def _wrap(self, row: dict | None) -> Annotation | None:
        """Convierte una fila de la base de datos en un modelo ``Annotation``."""
        return Annotation.from_row(row) if row else None

    # -------------------------------------------------------------- Consultas

    def get(self, annot_id: str) -> Annotation | None:
        """Obtiene una anotación por su ID."""
        if not self.is_available:
            return None
        return self._wrap(self._manager.db.get_annotation(annot_id))

    def for_page(
        self, drawing_id: int, page_index: int, include_deleted: bool = False
    ) -> list[Annotation]:
        """Anotaciones de una página concreta de un plano."""
        if not self.is_available:
            return []
        rows = self._manager.db.get_annotations_for_page(
            drawing_id, page_index, include_deleted=include_deleted
        )
        return [a for a in (self._wrap(r) for r in rows) if a]

    def for_drawing(self, drawing_id: int, include_deleted: bool = False) -> list[Annotation]:
        """Todas las anotaciones de un plano (para la tabla de marcas)."""
        if not self.is_available:
            return []
        rows = self._manager.db.get_annotations_for_drawing(
            drawing_id, include_deleted=include_deleted
        )
        return [a for a in (self._wrap(r) for r in rows) if a]

    # -------------------------------------------------------------- Comandos

    def create(
        self,
        drawing_id: int,
        page_index: int,
        annot_type: str,
        geometry: dict,
        style: dict,
        **extra: Any,
    ) -> Annotation | None:
        """
        Crea una anotación aplicando la regla de estilo ISO.

        ``extra`` admite los campos restantes del repositorio: ``content``, ``subject``,
        ``layer``, ``author``, ``status``, ``tags``, ``properties``, ``item_id``,
        ``tag_number`` y ``annot_id``.
        """
        if not self.is_available:
            return None
        row = self._manager.db.create_annotation(
            drawing_id=drawing_id,
            page_index=page_index,
            annot_type=annot_type,
            geometry=geometry,
            style=normalize_style_iso(style),
            **extra,
        )
        return self._wrap(row)

    def update(self, annot_id: str, changes: dict) -> Annotation | None:
        """Actualiza parcialmente una anotación, normalizando el estilo si viene."""
        if not self.is_available:
            return None
        if "style" in changes and isinstance(changes["style"], dict):
            changes = dict(changes)
            changes["style"] = normalize_style_iso(changes["style"])
        return self._wrap(self._manager.db.update_annotation(annot_id, changes))

    def delete(self, annot_id: str, soft: bool = True) -> bool:
        """Elimina una anotación (borrado lógico por defecto)."""
        if not self.is_available:
            return False
        return bool(self._manager.db.delete_annotation(annot_id, soft=soft))

    def restore(self, annot_id: str) -> Annotation | None:
        """Restaura una anotación eliminada lógicamente."""
        if not self.is_available:
            return None
        if not self._manager.db.restore_annotation(annot_id):
            return None
        return self._wrap(self._manager.db.get_annotation(annot_id))


__all__ = ["AnnotationService"]
