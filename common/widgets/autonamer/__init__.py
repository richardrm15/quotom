"""
Paquete Autonamer: Módulo Desacoplado de Auto-Nombrado por Región de Cajetín.
"""

from .canvas import RegionData, RegionCanvasView, REGION_COLORS, DEBUG_HIGHLIGHT_CHARS
from .worker import AutoNamerPreviewWorker
from .text_extractor import (
    clean_boilerplate,
    extract_bounded_text_fast,
    extract_text_from_norm_rect_static,
    BOILERPLATE_PATTERNS,
)
from .main_window_auto_namer import AutoNamerDialog

__all__ = [
    "AutoNamerDialog",
    "AutoNamerPreviewWorker",
    "RegionData",
    "RegionCanvasView",
    "REGION_COLORS",
    "DEBUG_HIGHLIGHT_CHARS",
    "clean_boilerplate",
    "extract_bounded_text_fast",
    "extract_text_from_norm_rect_static",
    "BOILERPLATE_PATTERNS",
]
