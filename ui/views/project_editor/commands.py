# ui/views/project_editor/commands.py
"""
Comandos reversibles (``QUndoCommand``) de la feature del editor técnico (canvas).

Arquitectura canónica:
* El cambio se ejecuta **siempre** en ``redo()`` (nada de ``_applied_once`` ni de
  aplicar antes de enviar al stack).
* Cada comando recibe un **contrato explícito** (``AnnotationServiceProtocol``);
  prohibido ``hasattr``/``getattr`` o adivinar el receptor.
* El comando solo invoca operaciones del servicio (que muta el modelo y sincroniza
  la vista mediante señales); nunca manipula widgets directamente.
"""
from __future__ import annotations

import copy
import logging
from typing import Protocol

from PySide6.QtGui import QUndoCommand

logger = logging.getLogger("quotom.commands.project_editor")


class AnnotationServiceProtocol(Protocol):
    """Operaciones de dominio que un comando de anotación necesita del servicio."""

    def restore_annotation(self, annot_data: dict) -> None:
        """Re-crea (o restaura) la anotación en el modelo y su representación visual."""

    def remove_annotation(self, annot_id: str) -> None:
        """Elimina (soft-delete) la anotación del modelo y su representación visual."""

    def apply_annotation_state(self, annot_id: str, state: dict) -> None:
        """Aplica un estado de propiedades, estilo o geometría a la anotación."""


class CreateAnnotationCommand(QUndoCommand):
    """Comando reversible para crear (o restaurar) una anotación en el plano."""

    def __init__(self, service: AnnotationServiceProtocol, annot_data: dict):
        super().__init__(f"Crear anotación {annot_data.get('type', '')}")
        self._service = service
        self._annot_data: dict = copy.deepcopy(annot_data)
        self._annot_id: str = annot_data["id"]

    def redo(self) -> None:
        try:
            self._service.restore_annotation(copy.deepcopy(self._annot_data))
        except Exception as exc:  # pragma: no cover - registro defensivo
            logger.error("Error al rehacer creación de anotación: %s", exc)

    def undo(self) -> None:
        try:
            self._service.remove_annotation(self._annot_id)
        except Exception as exc:  # pragma: no cover - registro defensivo
            logger.error("Error al deshacer creación de anotación: %s", exc)


class DeleteAnnotationCommand(QUndoCommand):
    """Comando reversible para eliminar una anotación del plano."""

    def __init__(
        self,
        service: AnnotationServiceProtocol,
        annot_id: str,
        annot_data: dict | None,
    ):
        super().__init__("Eliminar anotación")
        self._service = service
        self._annot_id = annot_id
        self._annot_data: dict | None = (
            copy.deepcopy(annot_data) if annot_data else None
        )

    def redo(self) -> None:
        try:
            self._service.remove_annotation(self._annot_id)
        except Exception as exc:  # pragma: no cover - registro defensivo
            logger.error("Error al rehacer eliminación de anotación: %s", exc)

    def undo(self) -> None:
        if not self._annot_data:
            return
        try:
            self._service.restore_annotation(copy.deepcopy(self._annot_data))
        except Exception as exc:  # pragma: no cover - registro defensivo
            logger.error("Error al deshacer eliminación de anotación: %s", exc)


class UpdateAnnotationCommand(QUndoCommand):
    """Comando reversible para actualizar propiedades, estilo o geometría."""

    def __init__(
        self,
        service: AnnotationServiceProtocol,
        annot_id: str,
        old_state: dict,
        new_state: dict,
        description: str = "Modificar anotación",
    ):
        super().__init__(description)
        self._service = service
        self._annot_id = annot_id
        self._old_state: dict = copy.deepcopy(old_state)
        self._new_state: dict = copy.deepcopy(new_state)

    def redo(self) -> None:
        self._apply(self._new_state)

    def undo(self) -> None:
        self._apply(self._old_state)

    def _apply(self, state: dict) -> None:
        try:
            self._service.apply_annotation_state(self._annot_id, state)
        except Exception as exc:  # pragma: no cover - registro defensivo
            logger.error("Error al aplicar estado de anotación: %s", exc)


__all__ = [
    "AnnotationServiceProtocol",
    "CreateAnnotationCommand",
    "DeleteAnnotationCommand",
    "UpdateAnnotationCommand",
]
