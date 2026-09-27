# main.py
"""
Punto de entrada único de la aplicación Quotom.

Responsabilidades (y solo estas):
1. Configurar el entorno de ejecución (subprocesos, logging de Qt).
2. Crear la ``QApplication`` y aplicar el tema centralizado.
3. Instanciar la Vista y su Controlador, conectándolos con las dependencias.
"""
from __future__ import annotations

import os
import sys
import multiprocessing

# Soporte crítico para subprocesos en binarios congelados (PyInstaller)
multiprocessing.freeze_support()

# Silenciar advertencias ruidosas de DBus Desktop Portal en entornos sandbox
# (Bazzite, Distrobox, contenedores).
if "QT_LOGGING_RULES" not in os.environ:
    os.environ["QT_LOGGING_RULES"] = (
        "qt.qpa.theme*=false;qt.qpa.theme.gnome=false;qt.qpa.wayland=false"
    )

from PySide6.QtWidgets import QApplication

from core.settings import settings
from ui.styles.style_manager import ThemeManager
from ui.views.main_window.controller import MainWindowController
from ui.views.main_window.view import MainWindowView


def main() -> int:
    """Arranca la aplicación y devuelve el código de salida del bucle de eventos."""
    app = QApplication(sys.argv)
    app.setApplicationName("Quotom")

    # Tema centralizado (único punto de aplicación de estilos)
    ThemeManager.apply_theme(settings.get("theme.current", "dark"))

    init_w: int = settings.get("window.width", 1280)
    init_h: int = settings.get("window.height", 800)
    is_max: bool = settings.get("window.is_maximized", False)

    view = MainWindowView(init_w=init_w, init_h=init_h, start_maximized=is_max)
    # El controlador debe mantenerse vivo durante todo el ciclo de la aplicación.
    controller = MainWindowController(
        view=view,
        initial_project=sys.argv[1] if len(sys.argv) > 1 else None,
    )

    view.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
