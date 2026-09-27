"""
Tests de los widgets propios del auto-nombrador (``autonamer/widgets.py``).

Comprueban que cada widget se comporta de forma autónoma (sin conocer al
diálogo): publica sus señales, expone su estado y no revienta al construirse.
"""
from __future__ import annotations

import sys

from tests.support import app, apply_theme_once, run_standalone

from ui.views.auto_namer.canvas import RegionData
from ui.views.auto_namer.widgets import AlertBanner, SeparatorRow, ZoneCard


def _region(region_id: int = 1, label: str = "Zona 1 (Número)", sample: str = "") -> RegionData:
    reg = RegionData(region_id, "#3B82F6", label)
    reg.sample_text = sample
    return reg


# ----------------------------------------------------------------- AlertBanner

def test_el_banner_empieza_oculto_y_con_icono_de_aviso():
    """El aviso no ocupa espacio hasta que hay algo que advertir."""
    _ = app()
    apply_theme_once("dark")
    banner = AlertBanner()
    assert banner.isHidden() is True

    banner.refresh_icon()
    assert not banner.icon_pixmap().isNull()


def test_el_banner_muestra_el_mensaje():
    """`show_message` deja el texto y hace visible la banda."""
    _ = app()
    apply_theme_once("dark")
    banner = AlertBanner()
    banner.show_message("Las páginas tienen tamaños distintos")
    assert banner.message() == "Las páginas tienen tamaños distintos"
    assert banner.isHidden() is False


# ------------------------------------------------------------------- ZoneCard

def _textos(widget) -> list[str]:
    """Textos de todas las etiquetas del widget (para comprobar qué muestra)."""
    from PySide6.QtWidgets import QLabel

    return [lb.text() for lb in widget.findChildren(QLabel)]


def _boton_por_texto(widget, texto: str):
    from PySide6.QtWidgets import QPushButton

    return next(b for b in widget.findChildren(QPushButton) if b.text() == texto)


def _boton_por_tooltip(widget, texto: str):
    from PySide6.QtWidgets import QPushButton

    return next(b for b in widget.findChildren(QPushButton) if b.toolTip() == texto)


def test_el_boton_capturar_emite_el_id_de_su_zona():
    """Locks el cierre de la lambda: cada tarjeta debe emitir SU id, no el último."""
    _ = app()
    apply_theme_once("dark")
    recibidos = []
    card = ZoneCard(_region(region_id=7), index=0, removable=False, active=False)
    card.capture_requested.connect(recibidos.append)

    _boton_por_texto(card, "Capturar").click()

    assert recibidos == [7]


def test_el_boton_eliminar_emite_el_id_y_solo_existe_si_se_puede_borrar():
    """Con una sola zona no se puede borrar: el botón no debe existir."""
    _ = app()
    apply_theme_once("dark")
    recibidos = []
    card = ZoneCard(_region(region_id=3), index=1, removable=True, active=False)
    card.remove_requested.connect(recibidos.append)
    _boton_por_tooltip(card, "Eliminar esta zona").click()
    assert recibidos == [3]

    unica = ZoneCard(_region(region_id=1), index=0, removable=False, active=False)
    assert not [
        b for b in unica.findChildren(type(_boton_por_texto(unica, "Capturar")))
        if b.toolTip() == "Eliminar esta zona"
    ]


def test_la_tarjeta_muestra_el_texto_capturado_o_su_ausencia():
    """El texto de muestra capturado aparece entre corchetes."""
    _ = app()
    apply_theme_once("dark")
    con_texto = ZoneCard(_region(sample="A-101"), index=0, removable=True, active=True)
    sin_texto = ZoneCard(_region(sample=""), index=0, removable=True, active=True)

    assert any("A-101" in t for t in _textos(con_texto))
    assert any("Sin capturar" in t for t in _textos(sin_texto))


# ---------------------------------------------------------------- SeparatorRow

def test_el_separador_expone_y_fija_su_texto():
    """`text`/`set_text` son la única API que necesita el diálogo."""
    _ = app()
    apply_theme_once("dark")
    row = SeparatorRow(" - ")
    assert row.text() == " - "
    row.set_text(" / ")
    assert row.text() == " / "


def test_el_separador_avisa_al_cambiar():
    """Escribir en el separador emite la señal que refresca la previsualización."""
    _ = app()
    apply_theme_once("dark")
    avisos = []
    row = SeparatorRow(" - ")
    row.edited.connect(lambda: avisos.append(True))
    row.set_text(" | ")
    assert avisos, "el cambio de texto debe emitir `edited`"


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
