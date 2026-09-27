"""
Entradas de texto emergentes (``QInputDialog``).

Los dibuja Qt, por lo que heredan el estilo centralizado y el tema activo.
"""
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QLineEdit, QWidget

__all__ = ["ask_text"]


def ask_text(
    parent: QWidget | None,
    title: str,
    label: str,
    text: str = "",
) -> tuple[str, bool]:
    """
    Pide una línea de texto al usuario.

    Returns:
        ``(texto, aceptado)``: ``aceptado`` es ``False`` si el usuario canceló.
    """
    return QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, text)
