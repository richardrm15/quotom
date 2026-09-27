"""
Fachada única de diálogos emergentes de Quotom.

**Único lugar del proyecto autorizado a usar `QMessageBox`, `QInputDialog` y
`QFileDialog`.** Las vistas y los controladores llaman a estas funciones, no a
PySide6: así el estilo vive en un solo sitio, la migración a otro toolkit no
toca la lógica y los tests pueden sustituir la fachada sin abrir ventanas modales.

Criterio de diseño (los diálogos son de Qt para mantener el estilo visual):

* **Mensajes y preguntas** (`QMessageBox`) y **entradas de texto** (`QInputDialog`):
  los dibuja Qt, por lo que heredan ``theme.qss`` y la paleta del tema activo.
* **Ficheros** (`QFileDialog`): se fuerza ``DontUseNativeDialog`` a propósito.
  Un diálogo nativo lo dibuja el sistema operativo e **ignora** nuestro QSS y
  nuestra paleta, así que en modo oscuro aparecería blanco. Dibujado por Qt,
  hereda el tema activo (claro u oscuro) de forma garantizada.
"""
from __future__ import annotations

from ui.dialogs.file_dialogs import (
    ANY_FILE,
    PDF_FILES,
    open_files,
    save_file,
    select_directory,
)
from ui.dialogs.messages import about, confirm, error, info, warn
from ui.dialogs.prompts import ask_text

__all__ = [
    # Mensajes
    "info",
    "warn",
    "error",
    "about",
    "confirm",
    # Entradas
    "ask_text",
    # Ficheros
    "open_files",
    "save_file",
    "select_directory",
    "ANY_FILE",
    "PDF_FILES",
]
