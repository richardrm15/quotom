"""
Tests del extractor de texto del auto-nombrador (``ui/views/auto_namer/text_extractor.py``).

Son la **red de seguridad** que faltaba en esta feature (no tenía ni un test) y
cubren las dos funciones puras que el diálogo duplicaba:

* ``clean_boilerplate``: limpieza de etiquetas de cajetín.
* ``extract_text_from_norm_rect_static``: extracción geométrica por cajas de carácter.
* ``extract_bounded_text_fast``: extracción acotada con la API C de PDFium.

Los PDFs se **generan en el test** (``tests.support.make_text_pdf``), así que la
prueba no depende de archivos de ejemplo externos ni de que existan en la máquina.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tests.support import make_text_pdf, run_standalone

import pypdfium2 as pdfium

from core.text_geometry import Rect
from core.text_layer import PageTextData

from ui.views.auto_namer.text_extractor import (
    clean_boilerplate,
    extract_bounded_text_fast,
    extract_text_from_norm_rect_static,
)

# PDF de prueba: título arriba (coordenadas PDF, origen abajo-izquierda) y
# código de plano abajo, separados para poder acotar por región.
LINEAS = [
    ("PLANTA BAJA - NIVEL 2", 72, 700),
    ("ESCALA: 1:50", 72, 680),
    ("A-101", 480, 60),
]

# Regiones normalizadas (0..1). OJO: la función interpreta la región en
# coordenadas de ESCENA (origen arriba-izquierda), no en coordenadas PDF.
# El título está a x≈73..214, y≈83..92 en escena sobre 612x792.
REGION_TITULO = Rect(0.10, 0.098, 0.30, 0.025)   # solo la primera línea
REGION_CODIGO = Rect(0.75, 0.86, 0.20, 0.09)     # "A-101" (abajo)
REGION_VACIA = Rect(0.45, 0.45, 0.05, 0.05)      # zona sin texto


def _datos_del_pdf() -> tuple[PageTextData, str]:
    """Genera el PDF de prueba y devuelve (PageTextData, ruta)."""
    ruta = str(Path(tempfile.mkdtemp(prefix="quotom_txt_")) / "plano.pdf")
    make_text_pdf(ruta, LINEAS)
    doc = pdfium.PdfDocument(ruta)
    try:
        datos = PageTextData.extract_from_page(doc, 0, scale=1.0)
    finally:
        doc.close()
    return datos, ruta


# --------------------------------------------------------------------- limpieza

def test_clean_boilerplate_quita_la_etiqueta_del_cajetin():
    """La etiqueta estática desaparece y queda solo el dato útil."""
    assert clean_boilerplate("SHEET NUMBER: A-101") == "A-101"
    assert clean_boilerplate("ESCALA: 1:50") == "1:50"


def test_clean_boilerplate_conserva_texto_util():
    """Un texto normal no se toca."""
    assert clean_boilerplate("PLANTA BAJA NIVEL 2") == "PLANTA BAJA NIVEL 2"


def test_clean_boilerplate_normaliza_espacios_y_bordes():
    """Colapsa espacios y quita separadores sueltos de los extremos."""
    assert clean_boilerplate("  PLANTA    BAJA  ") == "PLANTA BAJA"
    assert clean_boilerplate("__PLANTA__") == "PLANTA"


# ------------------------------------------------------------------ extracción

def test_el_pdf_generado_tiene_capa_de_texto():
    """Guardarraíl de la infraestructura: el PDF de prueba se lee de verdad."""
    datos, _ = _datos_del_pdf()
    # Los saltos de línea también son caracteres, de ahí el >=
    assert len(datos.char_boxes) >= sum(len(t) for t, _, _ in LINEAS)
    assert "PLANTA BAJA - NIVEL 2" in datos.full_text
    assert "A-101" in datos.full_text


def test_extrae_solo_el_texto_de_la_region_indicada():
    """
    Acotar al título trae el título y no el código del cajetín.

    Nota: la función descarta los espacios del PDF y los reinserta con una
    heurística de separación, así que se comprueban fragmentos distintivos y no
    el espaciado exacto.
    """
    datos, _ = _datos_del_pdf()
    texto = extract_text_from_norm_rect_static(datos, REGION_TITULO)
    assert "PLANTA BAJA" in texto
    assert "NIVEL 2" in texto
    assert "A-101" not in texto


def test_extrae_el_codigo_cuando_la_region_lo_cubre():
    """La misma página, otra región: trae el código y no el título."""
    datos, _ = _datos_del_pdf()
    texto = extract_text_from_norm_rect_static(datos, REGION_CODIGO)
    assert texto.replace(" ", "") == "A-101"
    assert "PLANTA" not in texto


def test_region_vacia_devuelve_cadena_vacia():
    """Una región sin caracteres no inventa texto."""
    datos, _ = _datos_del_pdf()
    assert extract_text_from_norm_rect_static(datos, REGION_VACIA) == ""


def test_sin_cajas_de_caracteres_devuelve_vacio():
    """Página sin capa de texto (plano rasterizado) no rompe."""
    vacio = PageTextData(page_index=0, width_pts=612.0, height_pts=792.0, scale=1.0)
    assert extract_text_from_norm_rect_static(vacio, REGION_TITULO) == ""


def test_extraccion_por_api_nativa_acotada():
    """`extract_bounded_text_fast` (API C de PDFium) devuelve el texto de la zona."""
    ruta = str(Path(tempfile.mkdtemp(prefix="quotom_txt_")) / "plano.pdf")
    make_text_pdf(ruta, LINEAS)
    doc = pdfium.PdfDocument(ruta)
    try:
        texto = extract_bounded_text_fast(doc, 0, REGION_TITULO)
    finally:
        doc.close()
    assert "PLANTA BAJA" in texto
    assert "A-101" not in texto


# ------------------------------------------------------------------ guardarraíl

def test_el_dialogo_no_duplica_la_logica_de_extraccion():
    """
    El diálogo debe **usar** estas funciones, no tener copias propias.

    Historial: se extrajeron a este módulo y se dejaron alias en la clase, pero
    las copias locales posteriores los anulaban (refactor a medias). Este test
    impide que vuelva a pasar.
    """
    import ast

    from tests.support import PROJECT_ROOT

    fuente = (
        PROJECT_ROOT / "ui/views/auto_namer/view.py"
    ).read_text(encoding="utf-8")
    clase = next(
        n for n in ast.parse(fuente).body if isinstance(n, ast.ClassDef)
    )
    duplicadas = [
        m.name
        for m in clase.body
        if isinstance(m, ast.FunctionDef)
        and m.name in ("clean_boilerplate", "extract_text_from_norm_rect_static")
    ]
    assert not duplicadas, (
        f"El diálogo redefine {duplicadas}; debe importarlas de text_extractor"
    )


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
