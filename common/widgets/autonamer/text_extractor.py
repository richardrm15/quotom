"""
Módulo de Extracción y Limpieza de Texto para Auto-Namer.

Contiene las funciones matemáticas y geométricas puras para:
1. Extracción acotada ultrarrápida usando llamadas C nativas de PDFium.
2. Agrupación y ordenamiento espacial de cajas de caracteres vectoriales.
3. Filtrado de etiquetas estáticas de cajetín (boilerplate / title blocks).
"""

import ctypes
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PySide6.QtCore import QRectF
from core.text_geometry import Rect
from core.text_layer import PageTextData

BOILERPLATE_PATTERNS = [
    "SHEET NUMBER", "SHEET NO.", "SHEET NO", "NO. DE PLANO", "NO. PLANO",
    "SHEET TITLE", "TITULO DE PLANO", "TITULO", "TITLE:",
    "SCALE:", "ESCALA:", "NOT TO SCALE", "AS INDICATED",
    "ISSUED FOR:", "PROJECT NO:", "JOB NO:", "DATE:", "FECHA:",
    "APPROVED:", "CHECKED:", "DRAWN:",
]


def clean_boilerplate(raw: str) -> str:
    """Limpia etiquetas estáticas del cajetín que hayan podido quedar atrapadas en la captura."""
    res = raw
    upper = res.upper()
    for bp in BOILERPLATE_PATTERNS:
        if bp in upper:
            idx = upper.find(bp)
            res = (res[:idx] + " " + res[idx + len(bp):]).strip()
            upper = res.upper()
    return " ".join(res.split()).strip(" :-_#©")


def extract_bounded_text_fast(doc: pdfium.PdfDocument, page_idx: int, norm_rect: QRectF) -> str:
    """Extrae texto nativo acotado a la región geométrica usando FPDFText_GetBoundedText en PDFium C.

    Es de 10 a 100 veces más rápido que extraer todos los caracteres de la página completa,
    especialmente en planos CAD densos con decenas de miles de caracteres.
    """
    if norm_rect.width() <= 0 or norm_rect.height() <= 0:
        return ""

    try:
        page = doc[page_idx]
        w_pt, h_pt = page.get_size()
        w_px, h_px = int(round(w_pt)), int(round(h_pt))
        raw = page.raw
        tpage = page.get_textpage()

        rx0 = int(norm_rect.x() * w_px)
        ry0 = int(norm_rect.y() * h_px)
        rx1 = int((norm_rect.x() + norm_rect.width()) * w_px)
        ry1 = int((norm_rect.y() + norm_rect.height()) * h_px)

        corners = [
            (rx0, ry0),
            (rx1, ry0),
            (rx1, ry1),
            (rx0, ry1),
        ]
        all_px = []
        all_py = []
        px = ctypes.c_double()
        py = ctypes.c_double()
        for cx, cy in corners:
            pdfium_c.FPDF_DeviceToPage(raw, 0, 0, w_px, h_px, 0, cx, cy, ctypes.byref(px), ctypes.byref(py))
            all_px.append(px.value)
            all_py.append(py.value)

        min_x, max_x = min(all_px), max(all_px)
        min_y, max_y = min(all_py), max(all_py)

        raw_txt = tpage.get_text_bounded(left=min_x, bottom=min_y, right=max_x, top=max_y)
        if not raw_txt:
            return ""
        return " ".join(raw_txt.replace(chr(13), " ").replace(chr(10), " ").split()).strip()
    except Exception:
        return ""


def extract_text_from_norm_rect_static(text_data: PageTextData, norm_rect: QRectF) -> str:
    """Extrae texto con alta precisión geométrica usando cajas de caracteres vectoriales."""
    if not text_data.char_boxes:
        return ""

    w_px = round(text_data.width_pts * text_data.scale)
    h_px = round(text_data.height_pts * text_data.scale)

    target = Rect(
        norm_rect.x() * w_px,
        norm_rect.y() * h_px,
        norm_rect.width() * w_px,
        norm_rect.height() * h_px,
    )

    matched = [
        cb for cb in text_data.char_boxes
        if target.contains(cb.rect.center()) and cb.char.strip() and cb.char.isprintable()
    ]
    if not matched:
        return ""

    matched.sort(key=lambda cb: cb.rect.top())
    lines = []
    for cb in matched:
        placed = False
        for line in lines:
            line_top = min(c.rect.top() for c in line)
            line_bottom = max(c.rect.bottom() for c in line)
            line_h = line_bottom - line_top

            ov = max(0.0, min(line_bottom, cb.rect.bottom()) - max(line_top, cb.rect.top()))
            min_h = min(line_h, cb.rect.height())
            if min_h > 0 and (ov / min_h) >= 0.35:
                line.append(cb)
                placed = True
                break
        if not placed:
            lines.append([cb])

    lines.sort(key=lambda l: min(c.rect.top() for c in l))

    line_texts = []
    for line in lines:
        line.sort(key=lambda c: c.rect.left())
        line_chars = []
        for i, c in enumerate(line):
            if i > 0:
                prev = line[i - 1]
                gap = c.rect.left() - prev.rect.right()
                char_w = max(prev.rect.width(), c.rect.width())
                is_symbol = c.char in ".-_/" or prev.char in ".-_/"
                if gap > (char_w * 0.45) and not is_symbol and not (line_chars and line_chars[-1] == ' ') and c.char != ' ':
                    line_chars.append(' ')
            line_chars.append(c.char)

        l_str = "".join(line_chars).strip()
        if l_str:
            line_texts.append(l_str)

    combined = " ".join(line_texts)
    return clean_boilerplate(combined)
