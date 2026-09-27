"""
Diálogos de ficheros y carpetas (``QFileDialog``), dibujados por Qt.

**Por qué NO usamos el diálogo nativo del sistema** (aunque parezca lo natural):

* Un diálogo nativo lo dibuja el sistema operativo (portal GTK/XDG en Linux) y
  **ignora por completo** nuestro ``theme.qss`` y nuestra paleta. Solo se le puede
  *sugerir* el esquema con ``QStyleHints.setColorScheme`` y decide el sistema: si
  el escritorio está en claro y la aplicación en oscuro, saldría **blanco**.
* Con ``QFileDialog.Option.DontUseNativeDialog`` el diálogo lo dibuja Qt y
  **hereda el tema activo** (claro u oscuro) y el sistema de diseño. Además le
  pasamos explícitamente la paleta del tema con ``setPalette``, que es la forma
  literal de "decirle" en qué modo está la aplicación.

Se conservan los lugares estándar (Inicio, Escritorio, Documentos, última carpeta).
"""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QWidget

from ui.styles.style_manager import ThemeManager

__all__ = ["ANY_FILE", "PDF_FILES", "open_files", "save_file", "select_directory"]

ANY_FILE = "Todos los archivos (*)"
PDF_FILES = "Archivos PDF (*.pdf);;Todos los archivos (*.*)"


def _base_dialog(
    parent: QWidget | None,
    title: str,
    directory: str,
    name_filter: str,
) -> QFileDialog:
    """Crea el diálogo ya forzado a dibujado por Qt y con la paleta del tema activo."""
    dialog = QFileDialog(parent, title, directory or "", name_filter)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    # Armonía explícita con el modo claro/oscuro de la aplicación.
    dialog.setPalette(ThemeManager.palette())
    return dialog


def open_files(
    parent: QWidget | None,
    title: str,
    directory: str = "",
    name_filter: str = ANY_FILE,
    *,
    multiple: bool = True,
) -> list[str]:
    """
    Pide uno o varios ficheros existentes.

    Returns:
        Lista de rutas elegidas (vacía si el usuario canceló).
    """
    dialog = _base_dialog(parent, title, directory, name_filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setFileMode(
        QFileDialog.FileMode.ExistingFiles if multiple else QFileDialog.FileMode.ExistingFile
    )
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return []
    seleccion = dialog.selectedFiles()
    return seleccion if multiple else seleccion[:1]


def save_file(
    parent: QWidget | None,
    title: str,
    default_name: str = "",
    name_filter: str = ANY_FILE,
    *,
    default_suffix: str = "",
) -> str:
    """
    Pide una ruta de destino para guardar.

    Args:
        default_name: Nombre propuesto (se preselecciona en el diálogo).
        default_suffix: Extensión que Qt añade si el usuario no la escribe.

    Returns:
        Ruta elegida (cadena vacía si el usuario canceló).
    """
    dialog = _base_dialog(parent, title, default_name, name_filter)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    if default_name:
        dialog.selectFile(default_name)
    if default_suffix:
        dialog.setDefaultSuffix(default_suffix)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    seleccion = dialog.selectedFiles()
    return seleccion[0] if seleccion else ""


def select_directory(
    parent: QWidget | None,
    title: str,
    directory: str = "",
) -> str:
    """
    Pide una carpeta existente.

    Returns:
        Ruta de la carpeta (cadena vacía si el usuario canceló).
    """
    dialog = _base_dialog(parent, title, directory, ANY_FILE)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
    dialog.setFileMode(QFileDialog.FileMode.Directory)
    dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    if dialog.exec() != QFileDialog.DialogCode.Accepted:
        return ""
    seleccion = dialog.selectedFiles()
    return seleccion[0] if seleccion else ""
