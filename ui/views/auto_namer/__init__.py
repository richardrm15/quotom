"""
Feature **Auto-nombrado por región de cajetín** (``ui/views/auto_namer``).

Estructura de la feature:

* ``view.py`` — ``AutoNamerDialog``: composición de la interfaz y dibujo del plano.
* ``controller.py`` — ``AutoNamerController``: estado, extracción con caché y lotes.
* ``canvas.py`` / ``widgets.py`` — lienzo de captura y widgets propios.
* ``naming.py`` — regla de composición del nombre (dominio puro, sin Qt).
* ``pdf_documents.py`` — caché de documentos PDFium.
* ``text_extractor.py`` / ``worker.py`` — extracción de texto y cálculo en segundo plano.

No tiene ``commands.py`` a propósito: el diálogo **no** crea comandos de deshacer,
solo devuelve el mapeo de nombres y es el gestor de páginas (que ya tiene su
``QUndoStack``) quien los aplica.
"""

from .canvas import RegionData, RegionCanvasView, REGION_COLORS, DEBUG_HIGHLIGHT_CHARS
from .controller import AutoNamerController
from .naming import assemble_name, has_captured_text
from .pdf_documents import PdfDocumentCache
from .text_extractor import (
    clean_boilerplate,
    extract_bounded_text_fast,
    extract_text_from_norm_rect_static,
    BOILERPLATE_PATTERNS,
)
from .view import AutoNamerDialog
from .widgets import AlertBanner, SeparatorRow, ZoneCard
from .worker import AutoNamerPreviewWorker

__all__ = [
    "AutoNamerDialog",
    "AutoNamerController",
    "AutoNamerPreviewWorker",
    "AlertBanner",
    "SeparatorRow",
    "ZoneCard",
    "PdfDocumentCache",
    "RegionData",
    "RegionCanvasView",
    "REGION_COLORS",
    "DEBUG_HIGHLIGHT_CHARS",
    "assemble_name",
    "has_captured_text",
    "clean_boilerplate",
    "extract_bounded_text_fast",
    "extract_text_from_norm_rect_static",
    "BOILERPLATE_PATTERNS",
]
