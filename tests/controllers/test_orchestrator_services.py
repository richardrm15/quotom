"""
Bloque S6: el orquestador (`MainWindowController`) atraviesa los servicios de dominio.

Cubre dos cosas:

1. Guardarraíl estático: el orquestador no llama a métodos de persistencia del
   repositorio ``ProjectManager`` (solo lo conserva como repositorio compartido
   para los colaboradores aún no migrados, p. ej. ``PageManagerWindow``).
2. Regresión: la recarga del sidebar tras guardar páginas usaba un
   ``self.get_drawings()`` inexistente en el orquestador.
"""
from __future__ import annotations

import inspect
import sys
import tempfile

from tests.support import apply_theme_once, app, run_standalone, teardown_widgets


# Métodos del repositorio que el orquestador ya NO debe invocar directamente.
PROHIBIDOS = (
    "_project_mgr.is_active",
    "_project_mgr.project_info",
    "_project_mgr.resolve_path",
    "_project_mgr.get_drawings",
    "_project_mgr.find_drawing",
    "_project_mgr.get_drawing_by_id",
    "_project_mgr.get_drawing_last_page",
    "_project_mgr.update_drawing_last_page",
    "_project_mgr.sync_drawing_page_count",
    "_project_mgr.get_drawing_page_names",
    "_project_mgr.set_drawing_page_name",
    "_project_mgr.import_drawing",
    "_project_mgr.rename_drawing",
    "_project_mgr.delete_drawing",
    "_project_mgr.create_project",
    "_project_mgr.open_project",
    "_project_mgr.close_project",
)


def _controller():
    from ui.views.main_window.controller import MainWindowController
    from ui.views.main_window.view import MainWindowView

    _ = app()
    apply_theme_once()
    return MainWindowController(view=MainWindowView())


def test_orquestador_no_llama_al_repositorio():
    """Guardarraíl: el orquestador usa servicios, no la API del repositorio."""
    from ui.views.main_window.controller import MainWindowController

    source = inspect.getsource(sys.modules[MainWindowController.__module__])
    for llamada in PROHIBIDOS:
        assert llamada not in source, f"el orquestador sigue llamando a {llamada}"


def test_orquestador_compone_los_servicios():
    """El orquestador expone los servicios y los comparte con los subcontroladores."""
    controller = _controller()
    try:
        assert controller._project_svc is not None
        assert controller._drawing_svc is controller._project_svc.drawings
        assert controller._project_ctrl.project_service is controller._project_svc
        assert controller._annot_ctrl._project_svc is controller._project_svc
        assert controller._annot_ctrl._annotation_svc is controller._project_svc.annotations
    finally:
        teardown_widgets(controller._view)
        controller._doc_ctrl.stop()


def test_recarga_del_sidebar_tras_guardar_paginas():
    """Regresión S6: recargar el sidebar tras guardar páginas no debe fallar."""
    controller = _controller()
    try:
        tmp = tempfile.mkdtemp(prefix="quotom_s6_")
        info = controller._project_ctrl.create_project(tmp, "S6")
        assert info is not None
        controller._project_svc.manager.db.add_drawing(info["id"], "drawings/A.pdf", "A", 3)

        capturado: dict = {}
        controller._view.sidebar.set_project = lambda p, d: capturado.update(proj=p, drawings=d)
        controller.load_pdf = lambda *a, **k: None  # aislado: no hay PDF real en disco

        controller._on_pages_saved_from_manager("drawings/A.pdf", 0)

        assert capturado["proj"] is not None and capturado["proj"]["name"] == "S6"
        assert [d["name"] for d in capturado["drawings"]] == ["A"]
    finally:
        teardown_widgets(controller._view)
        controller._doc_ctrl.stop()


def test_toggle_de_tema_aplica_el_estilo_una_sola_vez():
    """
    Regresión: un clic en "cambiar tema" debe re-estilar el árbol UNA vez.

    ``ThemeManager.toggle_theme()`` ya aplica el tema globalmente; el controlador
    lo volvía a aplicar, duplicando el *restyle* completo (y la exposición al
    puntero colgante de Qt que ya provocó un segfault en la suite).
    """
    controller = _controller()
    try:
        from ui.styles.style_manager import ThemeManager

        llamadas = {"n": 0}
        original = ThemeManager.apply_theme_to_app

        def spy(app_, mode="dark"):
            llamadas["n"] += 1
            return original(app_, mode)

        ThemeManager.apply_theme_to_app = spy
        try:
            controller._toggle_theme()
        finally:
            ThemeManager.apply_theme_to_app = original

        assert llamadas["n"] == 1, f"el estilo global se aplicó {llamadas['n']} veces"
    finally:
        teardown_widgets(controller._view)
        controller._doc_ctrl.stop()


def test_set_theme_aplica_el_modo_pedido():
    """`_set_theme` aplica el modo solicitado (no alterna: soporta N temas)."""
    controller = _controller()
    try:
        from ui.styles.style_manager import ThemeManager

        original = ThemeManager.apply_theme
        aplicados: list[str] = []

        def spy(mode="dark"):
            aplicados.append(mode)
            return original(mode)

        # El tema es estado GLOBAL compartido entre tests: fijar un punto de
        # partida conocido ANTES de espiar, o la aserción depende del test previo.
        original("dark")
        ThemeManager.apply_theme = spy
        try:
            controller._set_theme("light")
            controller._set_theme("light")  # idempotente: no repite
            controller._set_theme("dark")
        finally:
            ThemeManager.apply_theme = original
            original("dark")

        assert aplicados == ["light", "dark"], f"se aplicaron: {aplicados}"
    finally:
        teardown_widgets(controller._view)
        controller._doc_ctrl.stop()


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
