"""
Guardarraíl de la Regla 4 (estilos centralizados).

**Sprint P0 completado**: no queda ningún archivo con QSS inline. Todo el estilo
vive en ``ui/styles/theme.qss`` (o en ``style_manager.py``, único punto autorizado
a construir y aplicar la hoja).

El trinquete se mantiene para que **no pueda volver**:

* ``MIGRATED``: archivos limpios → deben tener **0** ``setStyleSheet``.
* ``PENDING``: presupuesto por archivo → **solo puede bajar** (hoy vacío).
"""
from __future__ import annotations

import sys
from pathlib import Path

from tests.support import PROJECT_ROOT, run_standalone

# Archivos migrados a ui/styles/theme.qss (deben tener 0 llamadas inline).
MIGRATED = [
    "common/widgets/property_inspector.py",
    "common/widgets/color_swatch_button.py",
    "common/widgets/find_bar.py",
    "common/widgets/annotation_toolbar.py",
    "common/widgets/graphics_view.py",
    "common/widgets/markups_panel.py",
    "common/widgets/project_sidebar.py",
    "common/widgets/page_manager.py",
    "common/widgets/autonamer/main_window_auto_namer.py",
]

# Presupuesto restante por archivo. Vacío = Sprint P0 cerrado; nunca debe crecer.
PENDING: dict[str, int] = {}

# Único punto autorizado para aplicar el QSS global.
ALLOWED = "ui/styles/style_manager.py"


def _count(relative_path: str) -> int:
    """Cuenta las llamadas reales a ``.setStyleSheet(`` en un archivo."""
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8").count(".setStyleSheet(")


def test_archivos_migrados_sin_setStyleSheet():
    """Los archivos ya migrados no deben contener QSS inline."""
    offenders = {rel: _count(rel) for rel in MIGRATED if _count(rel) > 0}
    assert not offenders, f"Regla 4 violada en archivos migrados: {offenders}"


def test_pendientes_no_superan_el_presupuesto():
    """Los archivos pendientes no pueden aumentar su deuda de estilos."""
    over = {
        rel: (_count(rel), budget)
        for rel, budget in PENDING.items()
        if _count(rel) > budget
    }
    assert not over, f"Regla 4: presupuesto superado (actual, max): {over}"


def test_ningun_archivo_nuevo_usa_qss_inline():
    """
    Cualquier archivo de UI fuera de la lista de migrados debe estar a **0**.

    Sin esto, un archivo nuevo con ``setStyleSheet`` entraría sin que el trinquete
    (que solo mira ``MIGRATED`` y ``PENDING``) lo detectara.
    """
    offenders: dict[str, int] = {}
    for carpeta in ("ui", "common"):
        base = PROJECT_ROOT / carpeta
        if not base.is_dir():
            continue
        for ruta in base.rglob("*.py"):
            rel = str(ruta.relative_to(PROJECT_ROOT))
            if "__pycache__" in rel or rel == ALLOWED or rel in MIGRATED:
                continue
            n = (ruta.read_text(encoding="utf-8")).count(".setStyleSheet(")
            if n > 0:
                offenders[rel] = n
    assert not offenders, (
        f"QSS inline en archivos no migrados (usa ui/styles/theme.qss): {offenders}"
    )


def test_style_manager_es_el_unico_punto_de_aplicacion():
    """``style_manager`` es el único autorizado a aplicar la hoja QSS global."""
    assert (PROJECT_ROOT / ALLOWED).exists()
    assert _count(ALLOWED) > 0, "style_manager debe aplicar el QSS global"


def test_theme_qss_se_sustituye_por_completo():
    """
    Trampa al editar ``theme.qss`` a mano: una sola llave mal escapada hace que
    ``str.format`` lance y ``build_qss`` devuelva ``""``, dejando la aplicación
    **sin estilos y en silencio**. Este test lo convierte en un fallo ruidoso.
    """
    from tests.support import app
    from ui.styles.style_manager import DARK_TOKENS, LIGHT_TOKENS, build_qss

    _ = app()
    for tokens, mode in ((DARK_TOKENS, "dark"), (LIGHT_TOKENS, "light")):
        qss = build_qss(tokens, mode)
        assert qss, f"build_qss('{mode}') devolvió vacío: revisa las llaves de theme.qss"
        assert "{{" not in qss and "}}" not in qss, f"llaves sin sustituir en el modo '{mode}'"


def test_tokens_de_estado_existen():
    """Los colores semánticos de estado forman parte del contrato de tokens."""
    from ui.styles.style_manager import DARK_TOKENS, LIGHT_TOKENS

    for tokens in (DARK_TOKENS, LIGHT_TOKENS):
        assert tokens.error and tokens.success, "faltan tokens error/success"


def test_sin_emojis_en_el_codigo():
    """
    **Convención del proyecto**: la interfaz usa la fábrica de iconos de ``ui/icons/``,
    nunca emojis.

    Motivos (verificado en el bug del panel de marcas):

    * Un emoji ausente en la fuente de la etiqueta **reserva avance pero no se
      dibuja**, así que descuadra el texto (el pictograma U+1F4CB del título
      metía 18 px invisibles y desplazaba las letras 9 px).
    * Los emojis no se adaptan al tema; los iconos de la fábrica sí.
    * El color de un emoji depende de la fuente del sistema, no del sistema de diseño.

    Se ignoran los **símbolos tipográficos** legítimos (``✓ ✕ — → • …``), que sí
    existen en las fuentes y se usan como texto.
    """
    import unicodedata

    from tests.support import PROJECT_ROOT

    # Rangos de pictogramas (emoji). Fuera quedan Dingbats y Misc Symbols, donde
    # viven ✓ ✕ ⚠, que son símbolos tipográficos y no pictogramas.
    rangos = ((0x1F000, 0x1FAFF), (0xFE0F, 0xFE0F))

    def es_emoji(caracter: str) -> bool:
        return any(a <= ord(caracter) <= b for a, b in rangos)

    offenders: list[str] = []
    for carpeta in ("ui", "common", "core", "tools", "tests"):
        base = PROJECT_ROOT / carpeta
        for ruta in base.rglob("*.py"):
            if "__pycache__" in str(ruta):
                continue
            for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
                pictogramas = [c for c in linea if es_emoji(c)]
                if pictogramas:
                    nombres = ", ".join(
                        f"{c!r} {unicodedata.name(c, '?')}" for c in pictogramas
                    )
                    offenders.append(f"{ruta.relative_to(PROJECT_ROOT)}:{numero}  {nombres}")

    assert not offenders, (
        "Convención del proyecto: nada de emojis en la UI, usa ThemeManager.get_icon(): "
        + " | ".join(offenders)
    )


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
