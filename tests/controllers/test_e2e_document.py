"""
Prueba End-to-End real: crear proyecto -> importar PDF -> cargar documento -> renderizar.

Es la red de seguridad contra APIs inventadas o roturas de integración entre
``ProjectController``, ``DocumentController`` y la vista.

Si no se encuentra ningún PDF de ejemplo, la prueba se omite (SKIP).
"""
from __future__ import annotations

import glob
import os
import sys
import tempfile

from tests.support import app, run_standalone

from common.styles.style_manager import ThemeManager

PDF_GLOBS = (
    "/home/richard/Documents/BMSBidSuite/pdf-examples/*.pdf",
    "tests/assets/*.pdf",
    "pdf-examples/*.pdf",
)


def _find_sample_pdf() -> str | None:
    """Retorna el PDF de ejemplo más pequeño disponible, o ``None`` si no hay."""
    candidates: list[str] = []
    for pattern in PDF_GLOBS:
        candidates.extend(glob.glob(pattern))
    if not candidates:
        return None
    return min(candidates, key=os.path.getsize)


def _skip(reason: str) -> None:
    """Omite la prueba en pytest o imprime SKIP cuando se ejecuta como script."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        import pytest

        pytest.skip(reason)
    print(f"SKIP  {reason}")


def test_proyecto_importa_pdf_y_renderiza_pagina():
    """Recorre el flujo completo hasta que la primera página se renderiza."""
    pdf = _find_sample_pdf()
    if not pdf:
        _skip("No hay PDF de ejemplo disponible")
        return

    _ = app()
    ThemeManager.apply_theme("dark")

    from PySide6.QtCore import QTimer

    from ui.views.main_window.controller import MainWindowController
    from ui.views.main_window.view import MainWindowView

    state = {"pages": 0, "total": 0}
    tmp_dir = tempfile.mkdtemp(prefix="quotom_e2e_")

    view = MainWindowView(init_w=1000, init_h=700)
    controller = MainWindowController(view=view)
    try:
        controller._doc_ctrl.page_ready.connect(lambda *_: state.update(pages=state["pages"] + 1))
        controller._doc_ctrl.document_loaded.connect(lambda _p, t: state.update(total=t))

        # 1. Proyecto nuevo  2. Importar PDF  3. Cargar el documento
        controller._project_ctrl.create_project(tmp_dir, "E2E")
        assert controller._project_ctrl.import_drawings([pdf]) == 1

        drawing = controller._project_mgr.get_drawings()[0]
        controller.load_pdf(drawing["abs_path"])

        # 4. Esperar como máximo 60 s a que llegue page_ready
        from PySide6.QtCore import QEventLoop

        loop = QEventLoop()
        controller._doc_ctrl.page_ready.connect(loop.quit)
        QTimer.singleShot(60_000, loop.quit)
        loop.exec()
    finally:
        controller._doc_ctrl.stop()

    assert state["total"] > 0, "El documento no reportó páginas"
    assert state["pages"] > 0, "No se renderizó ninguna página"


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
