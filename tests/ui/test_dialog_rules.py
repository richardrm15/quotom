"""
Guardarraíl de la arquitectura de diálogos emergentes.

**Convención**: los diálogos (`QMessageBox`, `QInputDialog`, `QFileDialog`) solo se
tocan desde ``ui/dialogs/``. Las vistas y los controladores usan esa fachada, así
que el aspecto (y el modo claro/oscuro de los diálogos de ficheros) se controla en
un único sitio.

Funciona como **trinquete** mientras se completa la migración:

* ``MIGRATED``: archivos ya migrados → deben tener **0** llamadas directas.
* ``PENDING``: presupuesto restante por archivo → **solo puede bajar**.
"""
from __future__ import annotations

import sys
from pathlib import Path

from tests.support import PROJECT_ROOT, run_standalone

# Archivos ya migrados a ui/dialogs/ (deben tener 0 llamadas directas).
MIGRATED: list[str] = [
    "ui/views/main_window/controller.py",
    "ui/views/main_window/project_controller.py",
]

# Presupuesto restante por archivo (migración en curso). Nunca debe subir.
PENDING = {
    "common/widgets/project_sidebar.py": 9,
    "common/widgets/markups_panel.py": 5,
    "ui/views/auto_namer/view.py": 1,
    "common/widgets/page_manager.py": 24,
}

PATRONES = ("QMessageBox.", "QMessageBox(", "QInputDialog.", "QFileDialog.")
ALLOWED_DIR = "ui/dialogs"


def _cuenta(ruta: Path) -> int:
    """Cuenta las llamadas directas a diálogos de PySide6 en un archivo."""
    texto = ruta.read_text(encoding="utf-8")
    return sum(texto.count(p) for p in PATRONES)


def _archivos_ui() -> list[Path]:
    archivos: list[Path] = []
    for carpeta in ("ui", "common", "core"):
        base = PROJECT_ROOT / carpeta
        if base.is_dir():
            archivos.extend(
                p for p in base.rglob("*.py")
                if "__pycache__" not in str(p) and ALLOWED_DIR not in str(p)
            )
    return archivos


def test_archivos_migrados_sin_dialogos_directos():
    """Los archivos ya migrados no deben llamar a PySide6 directamente."""
    offenders = {rel: _cuenta(PROJECT_ROOT / rel) for rel in MIGRATED if _cuenta(PROJECT_ROOT / rel) > 0}
    assert not offenders, f"Usa ui.dialogs en lugar de PySide6: {offenders}"


def test_pendientes_no_superan_el_presupuesto():
    """Los archivos pendientes no pueden aumentar su deuda de diálogos directos."""
    over = {}
    for rel, budget in PENDING.items():
        ruta = PROJECT_ROOT / rel
        if ruta.exists():
            actual = _cuenta(ruta)
            if actual > budget:
                over[rel] = (actual, budget)
    assert not over, f"Presupuesto superado (actual, max): {over}"


def test_ningun_archivo_nuevo_usa_dialogos_directos():
    """Cualquier archivo fuera de la lista (migrado o presupuestado) debe estar a 0."""
    conocidos = set(MIGRATED) | set(PENDING)
    offenders = {
        str(p.relative_to(PROJECT_ROOT)): _cuenta(p)
        for p in _archivos_ui()
        if str(p.relative_to(PROJECT_ROOT)) not in conocidos and _cuenta(p) > 0
    }
    assert not offenders, (
        f"Nuevo acoplamiento a diálogos de PySide6 (usa ui.dialogs): {offenders}"
    )


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
