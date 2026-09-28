"""
Tests del sistema de tema centralizado (``common/styles/style_manager.py`` + ``theme.qss``).

Verifica que la hoja QSS se parametriza sin marcadores huérfanos, que el cambio de
tema funciona y que la fábrica de iconos responde al tema activo.
"""
from __future__ import annotations

import sys

from tests.support import app, run_standalone

from common.styles.style_manager import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ThemeManager,
    build_qss,
)


def test_theme_qss_se_parametriza_sin_marcadores_huerfanos():
    """``build_qss`` sustituye TODOS los marcadores ``{token}`` del QSS."""
    qss = build_qss(DARK_TOKENS, "dark")
    assert len(qss) > 5000, f"QSS sospechosamente corto: {len(qss)}"
    assert "{bg_base}" not in qss, "Quedaron marcadores sin sustituir"
    assert "{primary}" not in qss


def test_aplicar_tema_oscuro():
    """El tema oscuro se aplica y expone sus tokens."""
    _ = app()
    ThemeManager.apply_theme("dark")

    assert ThemeManager.current_mode() == "dark"
    assert ThemeManager.tokens().bg_base == "#181818"
    assert ThemeManager.canvas_background_color() == "#0E0E0E"


def test_colores_dinamicos_y_paleta_marcas():
    """``color()`` y ``mark_palette()`` entregan los valores del tema activo."""
    _ = app()
    ThemeManager.apply_theme("dark")

    assert ThemeManager.color("bg_base").name().lower() == "#181818"
    assert ThemeManager.mark_palette()["E-LUM"] == "#EC4899"


def test_fabrica_de_iconos_retorna_icono_valido():
    """``get_icon`` devuelve un QIcon no nulo (iconos vectoriales por QPainter)."""
    _ = app()
    ThemeManager.apply_theme("dark")

    icon = ThemeManager.get_icon("folder")
    assert not icon.isNull(), "get_icon devolvió un QIcon nulo"


def test_toggle_alterna_modo_y_reconstruye_qss():
    """``toggle_theme`` alterna dark/light y reconstruye el QSS con los nuevos tokens."""
    _ = app()
    ThemeManager.apply_theme("dark")

    new_mode = ThemeManager.toggle_theme()
    assert new_mode == "light"
    assert ThemeManager.current_mode() == "light"
    assert ThemeManager.tokens().bg_base == LIGHT_TOKENS.bg_base
    assert len(build_qss(ThemeManager.tokens(), "light")) > 5000

    # Restaurar estado por defecto para no afectar a otros tests.
    ThemeManager.apply_theme("dark")


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
