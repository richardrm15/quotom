"""
Modelos de dominio de Quotom (dataclasses puras, sin dependencias de Qt).

Objetivo
--------
Sustituir el uso de diccionarios crudos de SQLite (``dict(sqlite3.Row)``) por tipos
explícitos, de modo que la UI deje de depender del esquema de la base de datos.

Compatibilidad
--------------
Los modelos ofrecen ``from_row()`` (construcción desde una fila) y ``to_dict()``
(serialización al **contrato de diccionario actual**, incluidas las claves ISO 32000-1),
por lo que pueden adoptarse de forma incremental sin romper consumidores existentes.

Reglas arquitectónicas:
* Lógica de dominio pura: **cero** imports de PySide6/Qt.
* Sin objetos gráficos: los ``QGraphicsItem`` viven en la capa UI.
* Solo datos y validaciones triviales; las reglas no triviales van en ``business_rules``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def _as_dict(value: Any) -> dict:
    """Normaliza un valor JSON a ``dict`` (acepta str serializado o ``None``)."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list:
    """Normaliza un valor JSON a ``list`` (acepta str serializado o ``None``)."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return list(parsed) if isinstance(parsed, (list, tuple)) else []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


@dataclass(frozen=True)
class Project:
    """Proyecto de cómputo (raíz del espacio de trabajo)."""

    id: int
    name: str
    created_at: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Project":
        """Construye un ``Project`` desde una fila de la tabla ``Projects``."""
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            created_at=row.get("created_at"),
        )

    def to_dict(self) -> dict:
        """Serializa al formato de diccionario usado por la UI."""
        return {"id": self.id, "name": self.name, "created_at": self.created_at}


@dataclass(frozen=True)
class Drawing:
    """Plano PDF custodiado dentro de la carpeta ``drawings/`` del proyecto."""

    id: int
    project_id: int
    path: str                 # Ruta relativa al proyecto, p. ej. "drawings/A.pdf"
    name: str                 # Nombre visible
    page_count: int = 0
    last_page: int = 0
    abs_path: str = ""        # Ruta absoluta resuelta (la inyecta el servicio)

    @classmethod
    def from_row(cls, row: Mapping[str, Any], abs_path: str = "") -> "Drawing":
        """Construye un ``Drawing`` desde una fila de la tabla ``Drawings``."""
        return cls(
            id=int(row["id"]),
            project_id=int(row["project_id"]),
            path=str(row.get("path") or ""),
            name=str(row.get("name") or ""),
            page_count=int(row.get("page_count") or 0),
            last_page=int(row.get("last_page") or 0),
            abs_path=abs_path or str(row.get("abs_path") or ""),
        )

    def with_abs_path(self, abs_path: str) -> "Drawing":
        """Retorna una copia del plano con la ruta absoluta resuelta."""
        return Drawing(
            id=self.id,
            project_id=self.project_id,
            path=self.path,
            name=self.name,
            page_count=self.page_count,
            last_page=self.last_page,
            abs_path=abs_path,
        )

    def to_dict(self) -> dict:
        """Serializa al formato de diccionario usado por la UI."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "path": self.path,
            "name": self.name,
            "page_count": self.page_count,
            "last_page": self.last_page,
            "abs_path": self.abs_path,
        }


@dataclass(frozen=True)
class DrawingPage:
    """Página de un plano con su nombre visible (personalizado o autogenerado)."""

    page_index: int
    page_name: str

    @property
    def display_name(self) -> str:
        """Nombre a mostrar, con respaldo ``Página N`` (1-based)."""
        return self.page_name or f"Página {self.page_index + 1}"

    def to_dict(self) -> dict:
        """Serializa al formato de diccionario usado por la UI."""
        return {"page_index": self.page_index, "page_name": self.display_name}


@dataclass(frozen=True)
class Annotation:
    """
    Anotación (marca de revisión / cómputo) sobre una página de un plano.

    El ``style`` sigue el estándar ISO 32000-1 (claves ``/C``, ``/CA``, ``/IC``, ``/ca``),
    por lo que ``to_dict()`` expone tanto los nombres naturales como las claves ISO.
    """

    id: str
    drawing_id: int
    page_index: int
    type: str
    geometry: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    content: str = ""
    subject: str = ""
    layer: str = "General"
    status: str = "None"
    tags: list = field(default_factory=list)
    properties: dict = field(default_factory=dict)
    ports: list = field(default_factory=list)
    item_id: int | None = None
    tag_number: int | None = None
    author: str = "Usuario"
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Annotation":
        """Construye una ``Annotation`` desde una fila de la tabla ``Annotations``."""
        return cls(
            id=str(row["id"]),
            drawing_id=int(row["drawing_id"]),
            page_index=int(row.get("page_index") or 0),
            type=str(row.get("type") or ""),
            geometry=_as_dict(row.get("geometry")),
            style=_as_dict(row.get("style")),
            content=str(row.get("content") or ""),
            subject=str(row.get("subject") or ""),
            layer=str(row.get("layer") or "General"),
            status=str(row.get("status") or "None"),
            tags=_as_list(row.get("tags")),
            properties=_as_dict(row.get("properties")),
            ports=_as_list(row.get("ports")),
            item_id=row.get("item_id"),
            tag_number=row.get("tag_number"),
            author=str(row.get("author") or "Usuario"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            deleted_at=row.get("deleted_at"),
        )

    # ------------------------------------------------------------------ Estado

    @property
    def is_deleted(self) -> bool:
        """Indica si la anotación está marcada como eliminada (borrado lógico)."""
        return self.deleted_at is not None

    @property
    def discipline(self) -> str:
        """Disciplina ISO: ``properties.discipline`` con respaldo en ``layer``."""
        value = self.properties.get("discipline") if self.properties else None
        return str(value or self.layer or "General")

    @property
    def page_name(self) -> str:
        """Nombre por defecto de la página que contiene la anotación."""
        return f"Página {self.page_index + 1}"

    # --------------------------------------------------------- Serialización

    def to_dict(self) -> dict:
        """
        Serializa al **contrato de diccionario actual** de la aplicación.

        Incluye los nombres naturales y las claves ISO 32000-1 que ya consumen
        el inspector de propiedades y el exportador.
        """
        data = {
            "id": self.id,
            "drawing_id": self.drawing_id,
            "page_index": self.page_index,
            "type": self.type,
            "geometry": dict(self.geometry),
            "style": dict(self.style),
            "content": self.content,
            "subject": self.subject,
            "layer": self.layer,
            "status": self.status,
            "tags": list(self.tags),
            "properties": dict(self.properties),
            "ports": list(self.ports),
            "item_id": self.item_id,
            "tag_number": self.tag_number,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "discipline": self.discipline,
            "page_name": self.page_name,
            # Claves ISO 32000-1 (compatibilidad con la UI existente)
            "/Subj": self.subject,
            "/OC": self.layer or self.discipline,
            "/T": self.author,
            "/Contents": self.content,
            "contents": self.content,
            "/State": self.status,
            "/StateModel": "Review",
            "/C": self.style.get("/C", []),
            "/CA": self.style.get("/CA", 1.0),
            "/IC": self.style.get("/IC", []),
            "/ca": self.style.get("/ca", 0.0),
        }
        return data


def drawings_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[Drawing]:
    """Convierte una secuencia de filas en una lista de ``Drawing``."""
    return [Drawing.from_row(row) for row in rows]


def annotations_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[Annotation]:
    """Convierte una secuencia de filas en una lista de ``Annotation``."""
    return [Annotation.from_row(row) for row in rows]


__all__ = [
    "Project",
    "Drawing",
    "DrawingPage",
    "Annotation",
    "drawings_from_rows",
    "annotations_from_rows",
]
