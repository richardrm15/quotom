"""
Módulo desacoplado de reconocimiento óptico de caracteres (OCR) para BMSBidSuite.
Utiliza RapidOCR (basado en ONNX Runtime) para reconocer texto en láminas escaneadas
o exportadas sin capa vectorial de texto (ej. AutoCAD con tipografía SHX).
"""

import logging
from typing import Optional, List, Tuple
from core.text_geometry import Rect, RectLike

logger = logging.getLogger(__name__)

_ocr_instance = None
_ocr_initialized = False


def is_ocr_available() -> bool:
    """Verifica si RapidOCR está disponible e inicializado."""
    global _ocr_instance, _ocr_initialized
    if not _ocr_initialized:
        _init_ocr()
    return _ocr_instance is not None


def _init_ocr():
    global _ocr_instance, _ocr_initialized
    _ocr_initialized = True
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_instance = RapidOCR()
        logger.info("RapidOCR inicializado exitosamente.")
    except Exception as e:
        logger.warning("RapidOCR no está disponible en el entorno: %s", e)
        _ocr_instance = None


def recognize_crop(crop_bgr) -> Tuple[str, List[dict]]:
    """
    Ejecuta OCR sobre un recorte en formato numpy array BGR o RGB.
    Retorna (texto_concatenado, lista_de_items_con_caja_y_texto).
    """
    if not is_ocr_available() or _ocr_instance is None:
        return "", []

    try:
        result, _ = _ocr_instance(crop_bgr)
        if not result:
            return "", []

        # result = [[[dt_boxes], text, score], ...]
        items = []
        text_parts = []
        for entry in result:
            if len(entry) >= 2 and entry[1]:
                txt = str(entry[1]).strip()
                score = float(entry[2]) if len(entry) > 2 else 1.0
                if txt:
                    items.append({
                        "box": entry[0],
                        "text": txt,
                        "score": score
                    })
                    text_parts.append(txt)

        return " ".join(text_parts).strip(), items
    except Exception as e:
        logger.error("Error ejecutando OCR sobre recorte: %s", e, exc_info=True)
        return "", []


def recognize_pdf_region(
    source_pdf: str,
    page_idx: int,
    norm_rect: RectLike,
    scale: float = 2.0
) -> Tuple[str, List[Rect]]:
    """
    Renderiza únicamente la zona normalizada de la página indicada y ejecuta RapidOCR.
    ``norm_rect`` admite cualquier objeto con ``x()/y()/width()/height()``
    (``Rect`` puro o un ``QRectF`` del lado Qt).
    Retorna:
        - text: Texto extraído limpio.
        - char_rects: Lista de rectángulos de cajas detectadas en coordenadas normalizadas [0..1, 0..1].
    """
    if not is_ocr_available():
        return "", []

    try:
        import pypdfium2 as pdfium
        from core.pdf_lock import PDFIUM_LOCK

        with PDFIUM_LOCK:
            doc = pdfium.PdfDocument(source_pdf)
            page = doc[page_idx]
            bm = page.render(scale=scale)
            try:
                arr = bm.to_numpy()
                h, w, _ = arr.shape

                # Calcular límites en píxeles del recorte
                x0 = max(0, min(int(norm_rect.x() * w), w - 1))
                y0 = max(0, min(int(norm_rect.y() * h), h - 1))
                x1 = max(x0 + 1, min(int((norm_rect.x() + norm_rect.width()) * w), w))
                y1 = max(y0 + 1, min(int((norm_rect.y() + norm_rect.height()) * h), h))

                crop = arr[y0:y1, x0:x1, :3]
                if crop.size == 0 or crop.shape[0] < 5 or crop.shape[1] < 5:
                    return "", []

                text, items = recognize_crop(crop)

                # Convertir cajas detectadas por OCR de vuelta a coordenadas normalizadas
                norm_boxes: List[Rect] = []
                crop_w = float(x1 - x0)
                crop_h = float(y1 - y0)
                for item in items:
                    box = item.get("box")  # 4 puntos [[x0,y0], [x1,y0], [x1,y1], [x0,y1]]
                    if box and len(box) >= 4:
                        bx_min = min(p[0] for p in box)
                        bx_max = max(p[0] for p in box)
                        by_min = min(p[1] for p in box)
                        by_max = max(p[1] for p in box)

                        # En coordenadas globales normalizadas de la página
                        abs_x = (x0 + bx_min) / float(w)
                        abs_y = (y0 + by_min) / float(h)
                        abs_w = (bx_max - bx_min) / float(w)
                        abs_h = (by_max - by_min) / float(h)
                        norm_boxes.append(Rect(abs_x, abs_y, abs_w, abs_h))

                return text, norm_boxes
            finally:
                bm.close()
                doc.close()
    except Exception as e:
        logger.error("Error en recognize_pdf_region para pág %d: %s", page_idx, e, exc_info=True)
        return "", []
