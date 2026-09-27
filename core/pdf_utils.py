"""
Módulo de Utilidades de Bajo Nivel para PDF (pypdfium2).
Capa Core: Funciones puras de análisis e inspección de documentos PDF sin dependencias de UI.
"""

import ctypes
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from core.pdf_lock import PDFIUM_LOCK


def extract_pdf_page_names(pdf_path: str) -> list[str]:
    """
    Extrae los nombres o títulos de páginas del PDF utilizando:
    1. Marcadores TOC/Bookmarks (nombres reales de hojas CAD, ej. 'MD2202').
    2. Etiquetas de página nativas en el diccionario del PDF (FPDF_GetPageLabel).
    3. Si la página no tiene nombre o está vacío, fallback al número de página 'Página X' (1-based).
    """
    path_str = str(pdf_path)
    with PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(path_str)
        except Exception:
            return []

        try:
            total_pages = len(doc)
            if total_pages == 0:
                return []

            def _resolve_dest_idx(bm_item) -> int | None:
                # 1. Destino directo (/Dest)
                try:
                    dest = bm_item.get_dest()
                    if dest is not None:
                        idx = dest.get_index()
                        if idx is not None and idx >= 0:
                            return idx
                except Exception:
                    pass
                # 2. Acción (/Action /GoTo)
                try:
                    action = pdfium_c.FPDFBookmark_GetAction(bm_item.raw)
                    if action:
                        dest_raw = pdfium_c.FPDFAction_GetDest(doc.raw, action)
                        if dest_raw:
                            idx = pdfium_c.FPDFDest_GetDestPageIndex(doc.raw, dest_raw)
                            if idx is not None and idx >= 0:
                                return idx
                except Exception:
                    pass
                return None

            # 1. Mapear marcadores / bookmarks (TOC) a índice de página
            bm_map: dict[int, tuple[int, str]] = {}
            try:
                for bm in doc.get_toc():
                    p_idx = _resolve_dest_idx(bm)
                    if p_idx is not None and 0 <= p_idx < total_pages:
                        title = (bm.get_title() or "").strip()
                        if title:
                            if p_idx not in bm_map or bm.level >= bm_map[p_idx][0]:
                                bm_map[p_idx] = (bm.level, title)
            except Exception:
                pass

            # 2. Iterar páginas y extraer etiquetas nativas si no hay marcador
            buf = ctypes.create_string_buffer(512)
            page_names: list[str] = []

            for i in range(total_pages):
                name = bm_map[i][1] if i in bm_map else None
                if not name:
                    try:
                        req_len = pdfium_c.FPDF_GetPageLabel(doc.raw, i, buf, 512)
                        if req_len > 0:
                            raw_bytes = buf.raw[:req_len]
                            raw_str = raw_bytes.decode("utf-16le", errors="ignore").rstrip(chr(0)).strip()
                            if raw_str:
                                name = raw_str
                    except Exception:
                        pass

                if not name:
                    name = f"Página {i + 1}"

                page_names.append(name)

            return page_names
        finally:
            try:
                doc.close()
            except Exception:
                pass
