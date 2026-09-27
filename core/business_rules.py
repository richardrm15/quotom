"""
Reglas y cálculos de dominio de Quotom (Python puro, sin Qt).

Este módulo concentra las **decisiones de negocio** que antes estaban enterradas en
la capa de persistencia o en los gestores:

* Normalización del nombre visible de un plano a un nombre de archivo seguro.
* Resolución de colisiones de nombre en la carpeta ``drawings/``.
* Normalización de estilos de anotación al estándar ISO 32000-1 (delegado en
  ``core.color_utils``, que se reexporta como único punto de entrada de dominio).

Reglas arquitectónicas:
* Lógica pura: no accede a disco ni a la base de datos. Las operaciones de E/S se
  inyectan como *callbacks* (p. ej. ``exists``), lo que las hace testeables sin Qt
  ni sistema de archivos.
* Cero imports de PySide6/Qt.
"""
from __future__ import annotations

import os
from typing import Callable, Mapping

from core.color_utils import sync_style_with_iso

# Caracteres no permitidos en nombres de archivo (Windows/macOS/Linux).
INVALID_FILENAME_CHARS = '<>:"/\\|?*'

DEFAULT_PDF_EXTENSION = ".pdf"


def build_pdf_filename(display_name: str, default_ext: str = DEFAULT_PDF_EXTENSION) -> str:
    """
    Normaliza el nombre visible de un plano a un nombre de archivo seguro.

    Garantiza la extensión ``.pdf`` y sustituye los caracteres inválidos por ``_``.

    Args:
        display_name: Nombre visible introducido por el usuario (p. ej. ``"Planta 1/2"``).
        default_ext: Extensión a garantizar.

    Returns:
        Nombre de archivo saneado (p. ej. ``"Planta 1_2.pdf"``).

    Raises:
        ValueError: Si el nombre queda vacío tras normalizar.
    """
    name = (display_name or "").strip()
    if not name:
        raise ValueError("El nombre del plano no puede estar vacío.")
    if not name.lower().endswith(default_ext):
        name = f"{name}{default_ext}"
    for char in INVALID_FILENAME_CHARS:
        name = name.replace(char, "_")
    return name


def resolve_collision(
    filename: str,
    exists: Callable[[str], bool],
    is_source: Callable[[str], bool] | None = None,
) -> str:
    """
    Devuelve un nombre libre de colisiones añadiendo ``_1``, ``_2``, …

    Args:
        filename: Nombre de archivo candidato (p. ej. ``"A.pdf"``).
        exists: Callback que indica si un nombre ya está ocupado en destino.
        is_source: Callback opcional que indica si un nombre corresponde al **mismo
            archivo origen**. En ese caso no se añade sufijo, evitando duplicar el
            plano al reimportarlo.

    Returns:
        El nombre original si está libre, o ``"A_1.pdf"``, ``"A_2.pdf"``, …
    """

    def taken(name: str) -> bool:
        if not exists(name):
            return False
        return not (is_source is not None and is_source(name))

    if not taken(filename):
        return filename

    stem, ext = os.path.splitext(filename)
    counter = 1
    candidate = f"{stem}_{counter}{ext}"
    while taken(candidate):
        counter += 1
        candidate = f"{stem}_{counter}{ext}"
    return candidate


def normalize_style_iso(style: Mapping | None) -> dict:
    """
    Normaliza el estilo de una anotación al estándar ISO 32000-1.

    Punto de entrada de dominio para la regla de estilo: delega en
    ``core.color_utils.sync_style_with_iso`` (que garantiza el contrato
    ``stroke_color`` ⇄ ``/C``, ``fill_opacity`` ⇄ ``/ca``, etc.).
    """
    return sync_style_with_iso(dict(style or {}))


__all__ = [
    "INVALID_FILENAME_CHARS",
    "DEFAULT_PDF_EXTENSION",
    "build_pdf_filename",
    "resolve_collision",
    "normalize_style_iso",
    "sync_style_with_iso",
]
