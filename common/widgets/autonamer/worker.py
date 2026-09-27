"""
Trabajador Asíncrono en Segundo Plano (AutoNamerPreviewWorker).

Procesa lotes de planos en segundo plano sin congelar la interfaz gráfica,
aprovechando la jerarquía de caché unificada (RAM y SSD) y OCR como fallback.
"""

import ctypes
from typing import List, Dict, Tuple, Optional
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from PySide6.QtCore import QThread, Signal, QRectF
from core.text_layer import PageTextData
from core.pdf_lock import PDFIUM_LOCK
from core.ocr_engine import recognize_pdf_region
from common.pdf.pdf_renderer import calculate_optimal_scale

from .canvas import RegionData
from .text_extractor import extract_text_from_norm_rect_static, clean_boilerplate

class AutoNamerPreviewWorker(QThread):
    """Trabajador asíncrono en segundo plano (QThread) que procesa las páginas sin bloquear la UI."""

    row_computed = Signal(int, int, str, bool)  # row_idx, item_idx, final_name, has_text
    progress = Signal(int, int)  # current, total
    finished_all = Signal()

    def __init__(
        self,
        items: list,
        selected_indices: List[int],
        regions: List[RegionData],
        separators_text: List[str],
        cached_region_text: Dict[Tuple[int, int, float, float, float, float], str],
        cached_ocr_results: Dict[Tuple[int, int], Tuple[str, List[QRectF]]],
        disk_cache=None,
        page_cache=None,
        parent=None,
    ):
        super().__init__(parent)
        self._items = items
        self._selected_indices = selected_indices
        self._disk_cache = disk_cache
        self._page_cache = page_cache
        self._regions_info: List[Tuple[int, Tuple[float, float, float, float]]] = [
            (
                r.region_id,
                (
                    round(r.norm_rect.x(), 4),
                    round(r.norm_rect.y(), 4),
                    round(r.norm_rect.width(), 4),
                    round(r.norm_rect.height(), 4),
                )
                if r.norm_rect is not None
                else (0.0, 0.0, 0.0, 0.0),
            )
            for r in regions
        ]
        self._separators_text = list(separators_text)
        self._cached_region_text = cached_region_text
        self._cached_ocr_results = cached_ocr_results
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        total = len(self._selected_indices)
        if total == 0 or self._is_cancelled:
            return

        docs_map: Dict[str, pdfium.PdfDocument] = {}

        try:
            completed_count = 0
            for row, idx in enumerate(self._selected_indices):
                if self._is_cancelled:
                    break

                if not (0 <= idx < len(self._items)):
                    continue
                item = self._items[idx]

                all_cached = True
                parts = []
                has_captured_text = False
                missing_regs = []

                # 1. Consultar caché en memoria
                for reg_idx, (reg_id, (rx, ry, rw, rh)) in enumerate(self._regions_info):
                    if rw > 0 and rh > 0:
                        ck = (idx, reg_id, rx, ry, rw, rh)
                        if ck in self._cached_region_text:
                            val = self._cached_region_text[ck]
                        else:
                            all_cached = False
                            missing_regs.append((reg_idx, reg_id, rx, ry, rw, rh))
                            val = ""
                    else:
                        val = ""
                    if val:
                        has_captured_text = True
                    parts.append(val)
                    if reg_idx < len(self._separators_text):
                        parts.append(self._separators_text[reg_idx])

                # 2. Consultar memoria RAM Tier 1 (SlidingPageCache)
                if not all_cached and self._page_cache:
                    cached_text = self._page_cache.get_text_data(idx)
                    if cached_text and isinstance(cached_text, PageTextData) and cached_text.char_boxes:
                        all_cached = True
                        for reg_idx, reg_id, rx, ry, rw, rh in missing_regs:
                            target_rect = QRectF(rx, ry, rw, rh)
                            val = extract_text_from_norm_rect_static(cached_text, target_rect)
                            ck = (idx, reg_id, rx, ry, rw, rh)
                            self._cached_region_text[ck] = val
                            parts[reg_idx * 2] = val
                            if val:
                                has_captured_text = True

                # 3. Consultar disco SSD Tier 2 (DiskPageCache)
                if not all_cached and self._disk_cache and self._disk_cache.has_text(item.source_page_idx):
                    text_data = self._disk_cache.load_text(item.source_page_idx)
                    if text_data is not None and isinstance(text_data, PageTextData):
                        all_cached = True
                        if self._page_cache:
                            self._page_cache.set_text_data(idx, text_data)
                        for reg_idx, reg_id, rx, ry, rw, rh in missing_regs:
                            target_rect = QRectF(rx, ry, rw, rh)
                            val = extract_text_from_norm_rect_static(text_data, target_rect)
                            ck = (idx, reg_id, rx, ry, rw, rh)
                            self._cached_region_text[ck] = val
                            parts[reg_idx * 2] = val
                            if val:
                                has_captured_text = True

                # 4. Fallback directo: extraer con PDFium y persistir bidireccionalmente en caché
                if not all_cached:
                    if item.source_pdf not in docs_map:
                        try:
                            docs_map[item.source_pdf] = pdfium.PdfDocument(item.source_pdf)
                        except Exception:
                            pass
                    doc = docs_map.get(item.source_pdf)
                    if doc and item.source_page_idx < len(doc):
                        text_data = None
                        with PDFIUM_LOCK:
                            try:
                                page = doc[item.source_page_idx]
                                w_pt, h_pt = page.get_size()
                                scale = calculate_optimal_scale(float(w_pt), float(h_pt))
                                text_data = PageTextData.extract_from_page(doc, item.source_page_idx, scale=scale)
                            except Exception:
                                text_data = None

                        if text_data and text_data.char_boxes:
                            if self._disk_cache:
                                self._disk_cache.save_text(item.source_page_idx, text_data)
                            if self._page_cache:
                                self._page_cache.set_text_data(idx, text_data)

                            for reg_idx, reg_id, rx, ry, rw, rh in missing_regs:
                                target_rect = QRectF(rx, ry, rw, rh)
                                val = extract_text_from_norm_rect_static(text_data, target_rect)
                                ck = (idx, reg_id, rx, ry, rw, rh)
                                self._cached_region_text[ck] = val
                                parts[reg_idx * 2] = val
                                if val:
                                    has_captured_text = True
                        else:
                            # Si es plano rasterizado, fallback a OCR acotado
                            for reg_idx, reg_id, rx, ry, rw, rh in missing_regs:
                                ocr_key = (idx, reg_id)
                                if ocr_key in self._cached_ocr_results:
                                    val = self._cached_ocr_results[ocr_key][0]
                                else:
                                    target_rect = QRectF(rx, ry, rw, rh)
                                    ocr_text, ocr_boxes = recognize_pdf_region(item.source_pdf, item.source_page_idx, target_rect)
                                    val = clean_boilerplate(ocr_text) if ocr_text else ""
                                    self._cached_ocr_results[ocr_key] = (val, ocr_boxes)
                                ck = (idx, reg_id, rx, ry, rw, rh)
                                self._cached_region_text[ck] = val
                                parts[reg_idx * 2] = val
                                if val:
                                    has_captured_text = True

                # Ensamblar nombre final
                if has_captured_text:
                    assembled = "".join(parts).strip()
                    for sep in self._separators_text:
                        s_val = sep.strip()
                        if s_val and assembled.endswith(s_val):
                            assembled = assembled[:-len(s_val)].strip()
                        if s_val and assembled.startswith(s_val):
                            assembled = assembled[len(s_val):].strip()
                    final_name = assembled if assembled else item.page_name
                else:
                    final_name = item.page_name

                completed_count += 1
                self.row_computed.emit(row, idx, final_name, has_captured_text)
                self.progress.emit(completed_count, total)

        finally:
            for d in docs_map.values():
                try:
                    d.close()
                except Exception:
                    pass

        if not self._is_cancelled:
            self.finished_all.emit()
