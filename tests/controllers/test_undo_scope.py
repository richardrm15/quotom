"""
Alcance del undo con un solo documento activo (AUDIT_V2_REPORT §8 D2).

Regla: la historia de deshacer **no debe cruzar planos**. Si no se vacía, un Ctrl+Z
tras cambiar de documento aplicaría un cambio invisible sobre el plano anterior.
"""
from __future__ import annotations

import inspect
import sys

from tests.support import app, run_standalone

from PySide6.QtGui import QUndoCommand

from ui.styles.style_manager import ThemeManager
from ui.views.main_window.controller import MainWindowController
from ui.views.main_window.view import MainWindowView


class _DummyCommand(QUndoCommand):
    """Comando sin efecto, solo para contar entradas en la pila."""

    def redo(self) -> None:
        """No hace nada (comando de prueba)."""

    def undo(self) -> None:
        """No hace nada (comando de prueba)."""


def _make_controller() -> MainWindowController:
    """Crea un controlador real con su vista (offscreen, sin proyecto)."""
    _ = app()
    ThemeManager.apply_theme("dark")
    return MainWindowController(view=MainWindowView())


def test_cambiar_de_documento_vacia_la_pila():
    """Al cambiar de plano se limpia la historia; al recargar el mismo, se conserva."""
    ctrl = _make_controller()
    try:
        stack = ctrl._undo_stack

        # 1. Documento A con un cambio pendiente
        ctrl._sync_undo_scope("/planos/A.pdf")
        stack.push(_DummyCommand())
        assert stack.count() == 1

        # 2. Recargar el MISMO plano conserva la historia
        ctrl._sync_undo_scope("/planos/A.pdf")
        assert stack.count() == 1, "recargar el mismo plano no debe borrar la historia"

        # 3. Cambiar de plano vacía la historia
        ctrl._sync_undo_scope("/planos/B.pdf")
        assert stack.count() == 0, "cambiar de plano debe vaciar la pila"
    finally:
        ctrl._doc_ctrl.stop()


def test_cerrar_documento_vacia_la_pila():
    """Al cerrar el documento activo la pila queda limpia."""
    ctrl = _make_controller()
    try:
        ctrl._sync_undo_scope("/planos/A.pdf")
        ctrl._undo_stack.push(_DummyCommand())
        assert ctrl._undo_stack.count() == 1

        ctrl._clear_undo_scope()

        assert ctrl._undo_stack.count() == 0
        assert ctrl._undo_doc_path is None
    finally:
        ctrl._doc_ctrl.stop()


def test_el_cambio_de_documento_esta_cableado():
    """Guardarraíl: `_on_document_loaded` debe sincronizar el alcance del undo."""
    source = inspect.getsource(MainWindowController._on_document_loaded)
    assert "_sync_undo_scope" in source, (
        "_on_document_loaded dejó de llamar a _sync_undo_scope: la historia de undo "
        "volvería a cruzar planos"
    )


def test_el_cierre_de_documento_esta_cableado():
    """Guardarraíl: cerrar el documento debe limpiar el alcance del undo."""
    source = inspect.getsource(MainWindowController.close_current_document)
    assert "_clear_undo_scope" in source, (
        "close_current_document dejó de llamar a _clear_undo_scope"
    )


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
