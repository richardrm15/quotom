"""
Tests de la caché de documentos PDFium (``autonamer/pdf_documents.py``).

Incluye la **regresión del bug** encontrado al extraer esta responsabilidad del
diálogo: se llamaba a ``Path(pdf_path).exists()`` sin importar ``Path``, el
``NameError`` lo tragaba un ``except`` genérico y la página de muestra quedaba en
blanco (pixmap de error 800×600) cuando las cachés estaban frías.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tests.support import make_text_pdf, run_standalone

from ui.views.auto_namer.pdf_documents import PdfDocumentCache


def _pdf_de_prueba(nombre: str = "plano.pdf") -> str:
    ruta = str(Path(tempfile.mkdtemp(prefix="quotom_pdfdoc_")) / nombre)
    return make_text_pdf(ruta, [("PLANTA BAJA", 72, 700)])


def test_abre_un_pdf_real():
    """Regresión: abrir un PDF existente no debe fallar ni devolver None."""
    cache = PdfDocumentCache()
    doc = cache.get(_pdf_de_prueba())
    assert doc is not None
    assert len(doc) == 1
    cache.close_all()


def test_reutiliza_el_documento_ya_abierto():
    """El segundo acceso debe devolver el MISMO objeto, no reabrir el archivo."""
    cache = PdfDocumentCache()
    ruta = _pdf_de_prueba()
    primero = cache.get(ruta)
    segundo = cache.get(ruta)
    assert primero is segundo
    assert len(cache) == 1
    cache.close_all()


def test_ruta_inexistente_devuelve_none():
    """Un plano que ya no está en disco no debe romper el diálogo."""
    cache = PdfDocumentCache()
    assert cache.get("/ruta/que/no/existe/plano.pdf") is None
    assert len(cache) == 0


def test_pseudo_plano_en_blanco_no_se_abre():
    """``:blank:`` es un pseudo-plano interno, no un archivo."""
    cache = PdfDocumentCache()
    assert cache.get(":blank:") is None
    assert len(cache) == 0


def test_archivo_corrupto_devuelve_none_y_no_se_cachea():
    """Un PDF inválido devuelve None y se reintenta en la próxima llamada."""
    ruta = str(Path(tempfile.mkdtemp(prefix="quotom_pdfdoc_")) / "roto.pdf")
    Path(ruta).write_bytes(b"esto no es un PDF")
    cache = PdfDocumentCache()
    assert cache.get(ruta) is None
    assert len(cache) == 0


def test_close_all_cierra_y_vacia():
    """Tras cerrar, la caché queda vacía y se puede volver a usar."""
    cache = PdfDocumentCache()
    ruta = _pdf_de_prueba()
    cache.get(ruta)
    assert len(cache) == 1
    cache.close_all()
    assert len(cache) == 0
    # El mismo objeto ya no sirve, pero la caché puede reabrir el archivo
    assert cache.get(ruta) is not None
    cache.close_all()


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
