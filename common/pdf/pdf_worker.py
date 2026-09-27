import threading
"""
Módulo de Worker Dedicado de PDF (PDF Dedicated Worker Thread).

Maneja el ciclo de vida del documento PDF con pypdfium2 de forma serializada
en un único hilo secundario dedicado y gestiona la caché de disco Tier 2:
1. Thread-safety estricto: El hilo principal de UI nunca interactúa con la biblioteca C de PDFium.
2. Cola prioritaria: Prioriza la página visible actual sobre la precarga y el cacheo en segundo plano.
3. Descarte de peticiones obsoletas mediante generation_id.
4. Integración con Tier 2 Disk Cache (WebP Lossless en .cache/).
5. Señales Qt directas para entrega de QImage y notificación de progreso de caché en segundo plano.
"""

import queue
from pathlib import Path
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from common.pdf.pdf_renderer import calculate_optimal_scale
from common.pdf.disk_cache import DiskPageCache
from core.pdf_lock import PDFIUM_LOCK
from core.text_layer import PageTextData


class PdfWorker(QThread):
    """
    Worker serializado que procesa operaciones de lectura, caché y renderizado de planos
    en un hilo secundario independiente de la UI.
    """
    document_loaded = Signal(str, int)  # (pdf_path, total_pages)
    page_rendered = Signal(int, QImage, float, tuple, int, bool, str)  # (page_idx, qimage, scale, (w_pts, h_pts), gen_id, is_prefetch, source)
    text_data_ready = Signal(int, object, int)  # (page_idx, PageTextData, gen_id)
    cache_progress = Signal(int, int)  # (cached_pages, total_pages)
    error_occurred = Signal(str)
    busy_changed = Signal(bool)

    # Prioridades de cola (menor valor = mayor prioridad)
    CMD_STOP = 0
    CMD_OPEN = 1
    CMD_CLOSE = 2
    CMD_RENDER = 3
    CMD_PREFETCH = 4
    CMD_EXTRACT_TEXT = 5

    def __init__(self, parent=None, cache_dir: Path | str | None = None):
        super().__init__(parent)
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._running: bool = True
        self._doc: pdfium.PdfDocument | None = None
        self._current_gen_id: int = 0
        self._current_pdf_path: str | None = None
        self._disk_cache: DiskPageCache = DiskPageCache(cache_dir)

    def __del__(self):
        try:
            if self.isRunning():
                self.stop()
        except Exception:
            pass

    @property
    def disk_cache(self) -> DiskPageCache:
        return self._disk_cache

    def open_document(self, file_path: str):
        """Solicita abrir un nuevo documento PDF (cierra el anterior si existe)."""
        self._current_gen_id += 1
        self._current_pdf_path = file_path
        self._queue.put((self.CMD_OPEN, self._current_gen_id, file_path))

    def close_document(self, wait: bool = False, timeout: float = 2.0):
        """Solicita cerrar inmediatamente el documento actual y liberar su archivo."""
        self._current_gen_id += 1
        self._current_pdf_path = None
        ev = threading.Event() if wait else None
        self._queue.put((self.CMD_CLOSE, self._current_gen_id, ev))
        if wait and ev is not None:
            ev.wait(timeout=timeout)

    def set_extract_text(self, enabled: bool):
        """Activa o desactiva la extracción bajo demanda de la capa de texto."""
        self._extract_text = enabled

    def request_text(self, page_index: int, scale: float):
        """Solicita extraer el texto de la página en segundo plano sin bloquear el render de la imagen."""
        self._queue.put((self.CMD_EXTRACT_TEXT, self._current_gen_id, (page_index, scale)))

    def request_page(self, page_index: int):
        """Solicita renderizar o cargar la página visible actual (Alta prioridad)."""
        self._current_gen_id += 1
        self._queue.put((self.CMD_RENDER, self._current_gen_id, (page_index, False)))

    def prefetch_page(self, page_index: int):
        """Solicita precargar una página vecina en segundo plano (Baja prioridad)."""
        self._queue.put((self.CMD_PREFETCH, self._current_gen_id, (page_index, True)))

    def stop(self):
        """Detiene ordenadamente el hilo secundario y libera el documento."""
        self._running = False
        self._queue.put((self.CMD_STOP, 9999999, None))
        self.wait(2000)

    def run(self):
        """Bucle principal de trabajo en el hilo secundario."""
        while self._running:
            try:
                cmd, gen_id, payload = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if cmd == self.CMD_STOP or not self._running:
                break

            if cmd == self.CMD_OPEN:
                self._handle_open(payload, gen_id)
            elif cmd == self.CMD_CLOSE:
                self._handle_close(payload)
            elif cmd in (self.CMD_RENDER, self.CMD_PREFETCH):
                page_index, is_prefetch = payload
                # Descartar precargas obsoletas de generaciones anteriores
                if is_prefetch and gen_id < self._current_gen_id:
                    continue
                self._handle_render(page_index, gen_id, is_prefetch)
            elif cmd == self.CMD_EXTRACT_TEXT:
                page_index, scale = payload
                if gen_id >= self._current_gen_id:
                    self._handle_extract_text(page_index, scale, gen_id)


        # Liberar recursos de PDFium en el mismo hilo antes de terminar
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None

    def _handle_close(self, ev=None):
        with PDFIUM_LOCK:
            if self._doc is not None:
                try:
                    self._doc.close()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                self._doc = None
        if ev is not None:
            ev.set()

    def _handle_open(self, file_path: str, gen_id: int):
        self.busy_changed.emit(True)
        try:
            with PDFIUM_LOCK:
                if self._doc is not None:
                    try:
                        self._doc.close()
                    except Exception:
                        pass
                    self._doc = None

                self._disk_cache.set_document(file_path)
                doc = pdfium.PdfDocument(file_path)
                self._doc = doc
                total = len(doc)
            self.document_loaded.emit(file_path, total)

            # Notificar estado inicial del caché
            cached_now = self._disk_cache.cached_count
            self.cache_progress.emit(cached_now, total)
        except Exception as e:
            self.error_occurred.emit(f"Error al abrir el plano PDF:\n{str(e)}")
        finally:
            self.busy_changed.emit(False)

    def _handle_extract_text(self, page_index: int, scale: float, gen_id: int):
        if not self._doc or page_index < 0 or page_index >= len(self._doc):
            return
        # 1. Si existe en la caché de disco (Tier 2), cargar instantáneamente (~5 ms)
        text_data = self._disk_cache.load_text(page_index)
        if text_data is not None:
            self.text_data_ready.emit(page_index, text_data, gen_id)
            return

        # 2. Si no existe en disco, extraer con PDFium y guardar en caché
        try:
            with PDFIUM_LOCK:
                text_data = PageTextData.extract_from_page(self._doc, page_index, scale)
            self._disk_cache.save_text(page_index, text_data)
            self.text_data_ready.emit(page_index, text_data, gen_id)
        except Exception as e:
            import traceback
            traceback.print_exc()

    def _handle_render(self, page_index: int, gen_id: int, is_prefetch: bool):
        if not self._doc:
            return

        total_pages = len(self._doc)
        if page_index < 0 or page_index >= total_pages:
            return

        # 1. Comprobar si existe en Tier 2 (Caché en disco WebP Lossless)
        cached_disk = self._disk_cache.load_page(page_index)
        if cached_disk is not None:
            qimage, scale, dims_pts = cached_disk
            self.page_rendered.emit(
                page_index, qimage, scale, dims_pts, gen_id, is_prefetch, "disk"
            )
            if self._doc and page_index < len(self._doc) and not is_prefetch:
                self.request_text(page_index, scale)
            return

        # 2. Renderizado crudo con PDFium si aún no está en disco
        self.busy_changed.emit(True)
        try:
            with PDFIUM_LOCK:
                if not self._doc or page_index >= len(self._doc):
                    return
                page = self._doc[page_index]
                w_pts, h_pts = page.get_size()
                scale = calculate_optimal_scale(w_pts, h_pts)

                bitmap = page.render(scale=scale)
                try:
                    w, h, stride = bitmap.width, bitmap.height, bitmap.stride
                    raw_bytes = bytes(bitmap.buffer)

                    if bitmap.format == pdfium_c.FPDFBitmap_BGR:
                        fmt = QImage.Format.Format_BGR888
                    elif bitmap.format == pdfium_c.FPDFBitmap_BGRA:
                        fmt = QImage.Format.Format_ARGB32_Premultiplied
                    elif bitmap.format == pdfium_c.FPDFBitmap_Gray:
                        fmt = QImage.Format.Format_Grayscale8
                    else:
                        fmt = QImage.Format.Format_BGR888

                    temp_image = QImage(raw_bytes, w, h, stride, fmt)
                    qimage = temp_image.copy()
                finally:
                    bitmap.close()

            # Guardar en Tier 2 (WebP Lossless en .cache/)
            if self._disk_cache.save_page(page_index, qimage, scale, (w_pts, h_pts)):
                self.cache_progress.emit(self._disk_cache.cached_count, total_pages)

            self.page_rendered.emit(
                page_index, qimage, scale, (w_pts, h_pts), gen_id, is_prefetch, "render"
            )
            if self._doc and page_index < len(self._doc) and not is_prefetch:
                self.request_text(page_index, scale)
        except Exception as e:
            if not is_prefetch:
                self.error_occurred.emit(
                    f"Error al renderizar página {page_index + 1}:\n{str(e)}"
                )
        finally:
            self.busy_changed.emit(False)
