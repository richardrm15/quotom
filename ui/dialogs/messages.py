"""
Mensajes y confirmaciones (``QMessageBox``).

Centraliza las "recetas" que hoy se repiten en 50 puntos: título, icono, botones
y botón por defecto. Los diálogos los dibuja Qt, así que heredan el estilo
centralizado de ``common/styles/theme.qss``.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

__all__ = ["info", "warn", "error", "about", "confirm"]


def info(parent: QWidget | None, title: str, text: str) -> None:
    """Mensaje informativo (operación completada, instrucciones)."""
    QMessageBox.information(parent, title, text)


def warn(parent: QWidget | None, title: str, text: str) -> None:
    """Aviso (algo no salió como se esperaba, pero no es un fallo)."""
    QMessageBox.warning(parent, title, text)


def error(parent: QWidget | None, title: str, text: str) -> None:
    """Error (la operación no se pudo completar)."""
    QMessageBox.critical(parent, title, text)


def about(parent: QWidget | None, title: str, text: str) -> None:
    """Información "Acerca de" (versión, autoría, licencias)."""
    QMessageBox.about(parent, title, text)


def confirm(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    icon: QMessageBox.Icon = QMessageBox.Icon.Question,
    yes_text: str = "Sí",
    no_text: str = "No",
    default_yes: bool = False,
) -> bool:
    """
    Pregunta de confirmación con botones Sí/No y textos personalizables.

    Args:
        icon: Icono del diálogo. ``Warning`` para acciones destructivas.
        yes_text: Texto del botón de confirmación (p. ej. ``"Eliminar"``).
        no_text: Texto del botón de cancelación.
        default_yes: Si es ``False`` (recomendado en acciones destructivas) el
            botón por defecto es el de cancelar, así un ``Enter`` no destruye nada.

    Returns:
        ``True`` si el usuario confirmó.
    """
    box = QMessageBox(
        icon,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        parent,
    )
    box.setDefaultButton(
        QMessageBox.StandardButton.Yes if default_yes else QMessageBox.StandardButton.No
    )
    if yes_text:
        boton_si = box.button(QMessageBox.StandardButton.Yes)
        if boton_si is not None:
            boton_si.setText(yes_text)
    if no_text:
        boton_no = box.button(QMessageBox.StandardButton.No)
        if boton_no is not None:
            boton_no.setText(no_text)
    return box.exec() == QMessageBox.StandardButton.Yes
