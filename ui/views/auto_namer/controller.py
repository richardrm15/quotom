"""
Controlador del auto-nombrador: estado, extracción de texto y cálculo en lote.

Todo lo que **no** es dibujar:

* Caché de documentos PDFium abiertos (:class:`PdfDocumentCache`).
* Extracción de texto por zona con la jerarquía de caché completa (RAM del visor,
  disco Tier 2, PDFium y, como último recurso, OCR).
* Composición del nombre (delegada en :func:`naming.assemble_name`).
* Aviso de páginas con dimensiones heterogéneas.
* Persistencia de la plantilla de zonas en la caché de disco del documento.
* Orquestación del trabajador en segundo plano, expuesto hacia la vista con señales.

La vista (``view.AutoNamerDialog``) conserva las zonas y los separadores porque
son estado **editable por el usuario** en el lienzo; al pedir cálculos los pasa
como argumentos, de forma que el controlador no depende de widgets.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QRectF, Signal

from core.ocr_engine import recognize_pdf_region
from core.pdf_lock import PDFIUM_LOCK
from core.text_layer import PageTextData
from common.pdf.disk_cache import DiskPageCache
from common.pdf.page_cache import SlidingPageCache

from .canvas import RegionData
from .naming import assemble_name
from .pdf_documents import PdfDocumentCache
from .text_extractor import (
    clean_boilerplate,
    extract_bounded_text_fast,
    extract_text_from_norm_rect_static,
)
from .worker import AutoNamerPreviewWorker


class AutoNamerController(QObject):
    """Estado y lógica del auto-nombrado de páginas por regiones de cajetín."""

    #: Una fila del lote ya está calculada (fila, índice de página, nombre, ¿tenía texto?).
    row_computed = Signal(int, int, str, bool)
    #: Avance del lote (actual, total).
    progress = Signal(int, int)
    #: El lote terminó por completo.
    finished_all = Signal()

    def __init__(
        self,
        items: list,
        selected_indices: List[int],
        pdf_path: str,
        page_cache: Optional[SlidingPageCache] = None,
        disk_cache: Optional[DiskPageCache] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._items = items
        self._selected_indices = selected_indices
        self._pdf_path = pdf_path
        self._page_cache = page_cache
        self._disk_cache = disk_cache

        self._generated_names: Dict[int, str] = {}
        self._cached_text_pages: Dict[int, PageTextData] = {}
        self._cached_ocr_results: Dict[Tuple[int, int], Tuple[str, List[QRectF]]] = {}
        self._cached_region_text: Dict[Tuple[int, int, float, float, float, float], str] = {}
        self._documents = PdfDocumentCache()
        self._preview_worker: Optional[AutoNamerPreviewWorker] = None

    def document_for(self, pdf_path: str):
        """
        Documento PDFium abierto para ``pdf_path`` (o ``None``).

        Lo comparte la vista para renderizar la página de muestra sin abrir el
        archivo por su cuenta, y **bajo el mismo ``PDFIUM_LOCK``**.
        """
        return self._documents.get(pdf_path)

    # ------------------------------------------------------------------ nombres

    @property
    def generated_names(self) -> Dict[int, str]:
        """Mapeo índice de página -> nombre generado (lo que aplica el gestor de páginas)."""
        return self._generated_names

    def missing_page_indices(self) -> List[int]:
        """Páginas seleccionadas cuyo nombre todavía no se ha calculado."""
        return [idx for idx in self._selected_indices if idx not in self._generated_names]

    def assemble_name_for_page(
        self, item_idx: int, regions: List[RegionData], separators_text: List[str]
    ) -> str:
        """
        Compone el nombre de una página a partir de sus zonas y separadores.

        La regla de composición es compartida con el trabajador en segundo plano
        (:mod:`naming`), de modo que la previsualización y el resultado final no
        pueden divergir.
        """
        values = [
            self.text_for_region(item_idx, reg) if reg.norm_rect is not None else ""
            for reg in regions
        ]
        return assemble_name(values, separators_text)

    # -------------------------------------------------------------- extracción

    def invalidate_region_cache(self, region_id: int) -> None:
        """Descarta el texto cacheado de una zona (cuando el usuario redibuja su recuadro)."""
        self._cached_ocr_results = {
            k: v for k, v in self._cached_ocr_results.items() if k[1] != region_id
        }
        self._cached_region_text = {
            k: v for k, v in self._cached_region_text.items() if k[1] != region_id
        }

    def ocr_boxes_for_region(self, item_idx: int, region_id: int) -> List[QRectF]:
        """Cajas OCR ya detectadas para una zona (las usa el resaltado de depuración)."""
        cached = self._cached_ocr_results.get((item_idx, region_id))
        return list(cached[1]) if cached else []

    def text_for_region(self, item_idx: int, reg: RegionData) -> str:
        """
        Texto de una zona concreta de una página.

        Orden de intentos: caché de texto en RAM, caché de disco, extracción nativa
        acotada de PDFium y, si el plano es un rasterizado sin capa de texto, OCR.
        """
        if reg.norm_rect is None or not (0 <= item_idx < len(self._items)):
            return ""

        cache_key = self._region_cache_key(item_idx, reg)
        if cache_key in self._cached_region_text:
            return self._cached_region_text[cache_key]

        item = self._items[item_idx]

        if item_idx in self._cached_text_pages:
            text_data = self._cached_text_pages[item_idx]
            if text_data and text_data.char_boxes:
                val = extract_text_from_norm_rect_static(text_data, reg.norm_rect)
                if val.strip():
                    self._cached_region_text[cache_key] = val
                    return val

        if self._disk_cache and self._disk_cache.has_text(item.source_page_idx):
            text_data = self._disk_cache.load_text(item.source_page_idx)
            if text_data is not None:
                self._cached_text_pages[item_idx] = text_data
                val = extract_text_from_norm_rect_static(text_data, reg.norm_rect)
                if val.strip():
                    self._cached_region_text[cache_key] = val
                    return val

        doc = self._documents.get(item.source_pdf)
        if doc and item.source_page_idx < len(doc):
            with PDFIUM_LOCK:
                extracted = extract_bounded_text_fast(doc, item.source_page_idx, reg.norm_rect)
            if extracted:
                cleaned = clean_boilerplate(extracted)
                if cleaned:
                    self._cached_region_text[cache_key] = cleaned
                    return cleaned

        ocr_key = (item_idx, reg.region_id)
        if ocr_key in self._cached_ocr_results:
            return self._cached_ocr_results[ocr_key][0]

        ocr_text, ocr_boxes = recognize_pdf_region(
            item.source_pdf, item.source_page_idx, reg.norm_rect
        )
        cleaned_ocr = clean_boilerplate(ocr_text) if ocr_text else ""
        self._cached_ocr_results[ocr_key] = (cleaned_ocr, ocr_boxes)
        if cleaned_ocr:
            self._cached_region_text[cache_key] = cleaned_ocr
        return cleaned_ocr

    @staticmethod
    def _region_cache_key(
        item_idx: int, reg: RegionData
    ) -> Tuple[int, int, float, float, float, float]:
        """Clave de caché de una zona: página, zona y recuadro redondeado."""
        return (
            item_idx,
            reg.region_id,
            round(reg.norm_rect.x(), 4),
            round(reg.norm_rect.y(), 4),
            round(reg.norm_rect.width(), 4),
            round(reg.norm_rect.height(), 4),
        )

    def text_data_for_page(self, item_idx: int) -> Optional[PageTextData]:
        """
        Capa de texto vectorial de una página, con caché local, RAM y disco (Tier 2).

        Refleja el flujo de datos del visor: si el plano ya se renderizó, su capa de
        texto está en disco y se reutiliza en lugar de reprocesar el PDF.
        """
        if item_idx in self._cached_text_pages:
            return self._cached_text_pages[item_idx]

        if self._page_cache:
            cached_text = self._page_cache.get_text_data(item_idx)
            if cached_text and isinstance(cached_text, PageTextData):
                self._cached_text_pages[item_idx] = cached_text
                return cached_text

        if not (0 <= item_idx < len(self._items)):
            return None

        item = self._items[item_idx]

        if self._disk_cache:
            disk_text = self._disk_cache.load_text(item.source_page_idx)
            if disk_text and isinstance(disk_text, PageTextData):
                self._cached_text_pages[item_idx] = disk_text
                if self._page_cache:
                    self._page_cache.set_text_data(item_idx, disk_text)
                return disk_text

        doc = self._documents.get(item.source_pdf)
        if doc is None:
            return None

        try:
            with PDFIUM_LOCK:
                if item.source_page_idx < len(doc):
                    data = PageTextData.extract_from_page(doc, item.source_page_idx, scale=1.0)
                    self._cached_text_pages[item_idx] = data
                    if self._disk_cache:
                        self._disk_cache.save_text(item.source_page_idx, data)
                    if self._page_cache:
                        self._page_cache.set_text_data(item_idx, data)
                    return data
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ avisos

    def dimension_warning(self) -> Optional[str]:
        """
        Aviso si las páginas seleccionadas no comparten tamaño de hoja.

        El cajetín no cae en el mismo sitio en planos de formatos distintos, así que
        la plantilla de zonas deja de ser fiable. Devuelve ``None`` si las páginas
        medidas coinciden.
        """
        if self._disk_cache:
            pages_meta = self._disk_cache.pages_metadata()
            dims_set = set()
            for idx in self._selected_indices:
                p_meta = pages_meta.get(str(idx))
                if p_meta and "dims_pts" in p_meta:
                    dims_set.add(
                        (round(p_meta["dims_pts"][0], 0), round(p_meta["dims_pts"][1], 0))
                    )
            if len(dims_set) > 1:
                return (
                    "Advertencia de dimensiones: Las páginas seleccionadas tienen diferentes tamaños. "
                    "La ubicación del cajetín podría variar entre planos con formatos distintos."
                )
            return None

        dimension_groups: Dict[Tuple[float, float], List[int]] = {}
        try:
            with PDFIUM_LOCK:
                for idx in self._sample_indices():
                    if idx >= len(self._items):
                        continue
                    item = self._items[idx]
                    if item.source_pdf == ":blank:":
                        dims = (1600.0, 1100.0)
                    else:
                        doc = self._documents.get(item.source_pdf)
                        if doc and item.source_page_idx < len(doc):
                            page = doc[item.source_page_idx]
                            w, h = page.get_size()
                            dims = (round(w, 0), round(h, 0))
                        else:
                            dims = (0.0, 0.0)
                    dimension_groups.setdefault(dims, []).append(idx)
        except Exception:
            pass

        if len(dimension_groups) <= 1:
            return None

        details = ", ".join(
            f"{len(pages)} páginas de {int(w)}×{int(h)} pts"
            for (w, h), pages in dimension_groups.items()
        )
        return (
            f"Advertencia de dimensiones: Las páginas seleccionadas tienen diferentes tamaños ({details}). "
            "La ubicación del cajetín podría variar entre planos con formatos distintos."
        )

    def _sample_indices(self) -> List[int]:
        """Muestra representativa de páginas a medir (todas si son pocas)."""
        if len(self._selected_indices) <= 6:
            return list(self._selected_indices)
        return [
            self._selected_indices[0],
            self._selected_indices[len(self._selected_indices) // 4],
            self._selected_indices[len(self._selected_indices) // 2],
            self._selected_indices[3 * len(self._selected_indices) // 4],
            self._selected_indices[-1],
        ]

    # ---------------------------------------------------------------- plantilla

    def load_template(self) -> Optional[dict]:
        """Plantilla de zonas guardada para este documento, o ``None``."""
        if not self._disk_cache:
            return None
        return self._disk_cache.get_auto_namer_template()

    def save_template(self, regions: List[RegionData], separators_text: List[str]) -> None:
        """Persiste la plantilla de zonas y separadores del documento actual."""
        if not self._disk_cache:
            return
        self._disk_cache.save_auto_namer_template(
            {
                "regions": [
                    {
                        "region_id": r.region_id,
                        "color_hex": r.color_hex,
                        "label": r.label,
                        "norm_rect": [
                            round(r.norm_rect.x(), 4),
                            round(r.norm_rect.y(), 4),
                            round(r.norm_rect.width(), 4),
                            round(r.norm_rect.height(), 4),
                        ]
                        if r.norm_rect
                        else None,
                    }
                    for r in regions
                ],
                "separators": list(separators_text),
            }
        )

    # --------------------------------------------------------------------- lote

    def start_preview(self, regions: List[RegionData], separators_text: List[str]) -> None:
        """Lanza el cálculo de nombres de todas las páginas seleccionadas."""
        self.cancel_preview()
        self._preview_worker = AutoNamerPreviewWorker(
            items=self._items,
            selected_indices=self._selected_indices,
            regions=regions,
            separators_text=separators_text,
            cached_region_text=self._cached_region_text,
            cached_ocr_results=self._cached_ocr_results,
            disk_cache=self._disk_cache,
            page_cache=self._page_cache,
            parent=None,
        )
        self._preview_worker.row_computed.connect(self._on_row_computed)
        self._preview_worker.progress.connect(self.progress)
        self._preview_worker.finished_all.connect(self.finished_all)
        self._preview_worker.start()

    def cancel_preview(self) -> None:
        """Detiene el trabajador en segundo plano si sigue vivo."""
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.wait()
        self._preview_worker = None

    def is_previewing(self) -> bool:
        """``True`` si el cálculo en lote sigue en marcha."""
        return self._preview_worker is not None and self._preview_worker.isRunning()

    def close(self) -> None:
        """Cancela el lote en curso y cierra los documentos PDFium abiertos."""
        self.cancel_preview()
        self._documents.close_all()

    def remember_generated_name(self, item_idx: int, name: str) -> None:
        """Registra un nombre calculado fuera del lote (aplicación final)."""
        self._generated_names[item_idx] = name

    def _on_row_computed(self, row: int, idx: int, final_name: str, has_text: bool) -> None:
        """Registra el nombre calculado y lo reenvía a la vista."""
        self._generated_names[idx] = final_name
        self.row_computed.emit(row, idx, final_name, has_text)
