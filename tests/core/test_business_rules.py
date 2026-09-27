"""
Tests de `core/business_rules.py` — reglas de dominio puras.

Deben poder ejecutarse **sin iniciar Qt** y **sin tocar el sistema de archivos**
(la E/S se inyecta mediante callbacks).
"""
from __future__ import annotations

import sys

from tests.support import imported_top_level_modules, run_standalone

from core.business_rules import (
    build_pdf_filename,
    normalize_style_iso,
    resolve_collision,
)


def test_build_pdf_filename_anade_extension():
    """Garantiza la extensión .pdf sin duplicarla si ya está presente."""
    assert build_pdf_filename("Planta Baja") == "Planta Baja.pdf"
    assert build_pdf_filename("Planta Baja.pdf") == "Planta Baja.pdf"
    assert build_pdf_filename("PLANTA.PDF") == "PLANTA.PDF"


def test_build_pdf_filename_sanea_caracteres_invalidos():
    """Los caracteres no permitidos en nombres de archivo se sustituyen por '_'."""
    assert build_pdf_filename('A/B\\C:D*E?F"G<H>I|J') == "A_B_C_D_E_F_G_H_I_J.pdf"


def test_build_pdf_filename_rechaza_vacio():
    """Un nombre vacío o en blanco es un error de dominio."""
    for value in ("", "   ", None):
        try:
            build_pdf_filename(value)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"debería lanzar ValueError para {value!r}")


def test_build_pdf_filename_recorta_espacios():
    """Los espacios extremos no llegan al nombre de archivo."""
    assert build_pdf_filename("  A  ") == "A.pdf"


def test_resolve_collision_libre():
    """Si el nombre está libre se devuelve tal cual."""
    assert resolve_collision("A.pdf", exists=lambda _n: False) == "A.pdf"


def test_resolve_collision_anade_sufijo_incremental():
    """Ante colisiones añade _1, _2, … preservando la extensión."""
    ocupados = {"A.pdf", "A_1.pdf"}
    assert resolve_collision("A.pdf", exists=ocupados.__contains__) == "A_2.pdf"


def test_resolve_collision_respeta_el_archivo_origen():
    """Si el candidato ya es el mismo archivo origen no se añade sufijo."""
    ocupados = {"A.pdf"}
    result = resolve_collision(
        "A.pdf",
        exists=ocupados.__contains__,
        is_source=lambda name: name == "A.pdf",
    )
    assert result == "A.pdf", "reimportar el mismo PDF no debe duplicarlo"


def test_resolve_collision_ignora_is_source_ajeno():
    """`is_source` solo protege al archivo origen, no a los demás."""
    ocupados = {"A.pdf"}
    result = resolve_collision(
        "A.pdf",
        exists=ocupados.__contains__,
        is_source=lambda name: name == "OTRO.pdf",
    )
    assert result == "A_1.pdf"


def test_normalize_style_iso_delega_en_la_regla_de_color():
    """`normalize_style_iso` produce el contrato ISO 32000-1."""
    style = normalize_style_iso({"stroke_color": "#FF0000"})
    assert style.get("/C"), "debe derivar la clave ISO /C del color de trazo"
    assert normalize_style_iso(None) == normalize_style_iso({})


def test_business_rules_no_importa_qt():
    """Guardarraíl: `core/business_rules.py` es dominio puro (Regla 3/20)."""
    import core.business_rules as module

    prohibidos = {"PySide6", "PyQt5", "PyQt6"}
    assert not (imported_top_level_modules(module) & prohibidos)


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
