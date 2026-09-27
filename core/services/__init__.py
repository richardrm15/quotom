"""
Servicios de dominio de Quotom (casos de uso del núcleo).

Los servicios son la puerta de entrada del **dominio**:

* No conocen widgets, ventanas ni señales Qt.
* Reciben sus dependencias de forma explícita (``ProjectManager`` como repositorio).
* Devuelven **modelos** de ``core.models`` en lugar de diccionarios crudos de SQLite,
  de modo que la UI deje de depender del esquema de la base de datos.

Dirección de dependencias: ``UI → Services → Business Rules → Models → Database``.
"""
from __future__ import annotations

from core.services.annotation_service import AnnotationService
from core.services.drawing_service import DrawingService
from core.services.project_service import ProjectService

__all__ = ["ProjectService", "DrawingService", "AnnotationService"]
