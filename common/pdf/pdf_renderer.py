import math
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PySide6.QtGui import QImage
from core.pdf_lock import PDFIUM_LOCK

# Límite de seguridad (~35 Megapíxeles) para evitar sobrecarga de memoria en planos gigantes
MAX_PIXELS_CAP = 35_000_000


def calculate_optimal_scale(width_pts: float, height_pts: float, max_pixels: int = MAX_PIXELS_CAP) -> float:
    """
    Calcula el factor de escala de rasterizado según el Roadmap §6.1:
    Target Scale = min(2.5, sqrt(Max_Pixels / (width_pts * height_pts)))
    """
    area_pts = width_pts * height_pts
    if area_pts <= 0:
        return 2.0
    scale_from_cap = math.sqrt(max_pixels / area_pts)
    return max(0.5, min(2.5, scale_from_cap))


from core.pdf_utils import extract_pdf_page_names
