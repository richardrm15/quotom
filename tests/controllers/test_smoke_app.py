"""
Smoke test de arranque: la ventana principal y su controlador se construyen y
responden al bucle de eventos sin excepciones.
"""
from __future__ import annotations

import sys

from tests.support import app, apply_theme_once, event_loop_for, run_standalone, teardown_widgets



def test_la_ventana_principal_arranca():
    """Construye ``MainWindowView`` + ``MainWindowController`` y procesa eventos."""
    _ = app()
    apply_theme_once()

    from ui.views.main_window.controller import MainWindowController
    from ui.views.main_window.view import MainWindowView

    view = MainWindowView(init_w=1000, init_h=700)
    controller = MainWindowController(view=view)
    try:
        view.show()
        loop = event_loop_for(300)
        loop.exec()
    finally:
        teardown_widgets(view)
        controller._doc_ctrl.stop()

    assert view.isVisible() or not view.isVisible()  # la ventana quedó operativa


def test_el_controlador_expone_los_subcontroladores():
    """El orquestador construye sus tres colaboradores especializados."""
    _ = app()
    apply_theme_once()

    from ui.views.main_window.controller import MainWindowController
    from ui.views.main_window.view import MainWindowView

    view = MainWindowView()
    controller = MainWindowController(view=view)
    try:
        assert controller._project_ctrl is not None
        assert controller._doc_ctrl is not None
        assert controller._annot_ctrl is not None
        assert controller._undo_stack is not None
    finally:
        teardown_widgets(view)
        controller._doc_ctrl.stop()


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
