import threading
"""
Módulo de Indexación Paralela Multiproceso (Parallel Background Cache Indexer).

Utiliza un ProcessPoolExecutor acotado para exprimir la capacidad de CPUs multinúcleo
sin toparse con el GIL de Python ni generar contención en la biblioteca C de PDFium:
1. Aislamiento C++ estricto: Cada subproceso posee su propio entorno PDFium y runtime.
2. Cero costo de IPC: Los workers guardan el archivo WebP Lossless directamente en disco
   y solo devuelven al hilo principal una tupla ligera de metadatos.
3. Asignación elástica de CPU: Deja núcleos libres para garantizar 60 FPS en la interfaz.
4. Coordinador asíncrono no bloqueante mediante QThread con cancelación instantánea.
"""

import os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QImage
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from common.pdf.pdf_renderer import calculate_optimal_scale


def _render_page_worker(args: tuple) -> tuple[int, float, tuple[float, float], int] | None:
    """
    Función de trabajo aislada ejecutada en un subproceso worker independiente.
    args: (pdf_path, page_index, output_file_path)
    Retorna: (page_index, scale, (w_pts, h_pts), file_size_bytes) o None si falla.
    """
    pdf_path, page_index, output_file_path = args
    try:
        doc = pdfium.PdfDocument(pdf_path)
        page = doc[page_index]
        w_pts, h_pts = page.get_size()
        scale = calculate_optimal_scale(w_pts, h_pts)

        bitmap = page.render(scale=scale)
        try:
            raw_bytes = bytes(bitmap.buffer)
            if bitmap.format == pdfium_c.FPDFBitmap_BGR:
                fmt = QImage.Format.Format_BGR888
            elif bitmap.format == pdfium_c.FPDFBitmap_BGRA:
                fmt = QImage.Format.Format_ARGB32_Premultiplied
            elif bitmap.format == pdfium_c.FPDFBitmap_Gray:
                fmt = QImage.Format.Format_Grayscale8
            else:
                fmt = QImage.Format.Format_BGR888

            temp_img = QImage(raw_bytes, bitmap.width, bitmap.height, bitmap.stride, fmt)
            img = temp_img.copy()
        finally:
            bitmap.close()

        # Extraer y almacenar la capa de texto en disco aprovechando el subproceso paralelo
        try:
            import pickle
            from core.text_layer import PageTextData
            text_path = output_file_path.replace(".webp", "_text.bin")
            text_data = PageTextData.extract_from_page(doc, page_index, scale)
            temp_text_path = text_path + ".tmp"
            with open(temp_text_path, "wb") as tf:
                pickle.dump(text_data, tf, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(temp_text_path, text_path)
        except Exception:
            pass
        finally:
            doc.close()

        # Guardar en disco en formato WebP Lossless (100% sin pérdida de calidad)
        success = img.save(output_file_path, "WEBP", 100)
        if not success:
            return None

        # Guardar miniatura sincronizada en el mismo directorio de caché con las mismas reglas
        thumb_path = output_file_path.replace("page_", "thumb_")
        thumb = img.scaled(180, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        thumb.save(thumb_path, "WEBP", 85)

        file_size = os.path.getsize(output_file_path)
        return page_index, scale, (w_pts, h_pts), file_size
    except Exception:
        return None


class _IndexerCoordinatorThread(QThread):
    """Hilo coordinador secundario que gestiona el ProcessPoolExecutor con prioridad dinámica centrada en la página activa."""
    page_completed = Signal(int, float, tuple, int)  # (page_idx, scale, (w_pts, h_pts), file_size)
    indexing_finished = Signal()

    def __init__(
        self,
        pdf_path: str,
        uncached_pages: list[int],
        output_dir: Path,
        max_workers: int,
        initial_page: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._pending_pages = set(uncached_pages)
        self._output_dir = output_dir
        self._max_workers = max_workers
        self._current_page = initial_page
        self._running = True
        self._executor: ProcessPoolExecutor | None = None
        self._page_lock = threading.Lock()

    def set_current_page(self, current_page: int):
        """Actualiza dinámicamente la página activa para reorganizar la prioridad en tiempo real."""
        with self._page_lock:
            self._current_page = current_page

    def stop(self):
        self._running = False
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def run(self):
        if not self._pending_pages:
            self.indexing_finished.emit()
            return

        self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
        active_futures = {}  # future -> page_idx

        try:
            while self._running and (self._pending_pages or active_futures):
                # Rellenar tareas activas hasta max_workers con las páginas más cercanas a _current_page
                with self._page_lock:
                    curr_p = self._current_page

                # Ordenar pendientes: menor distancia a curr_p, prefiriendo adelante (>= curr_p)
                sorted_pending = sorted(
                    self._pending_pages,
                    key=lambda p: (abs(p - curr_p), 0 if p >= curr_p else 1)
                )

                while len(active_futures) < self._max_workers and sorted_pending:
                    next_page = sorted_pending.pop(0)
                    self._pending_pages.remove(next_page)
                    task = (
                        self._pdf_path,
                        next_page,
                        str(self._output_dir / f"page_{next_page:04d}.webp"),
                    )
                    try:
                        fut = self._executor.submit(_render_page_worker, task)
                        active_futures[fut] = next_page
                    except Exception:
                        break

                if not active_futures:
                    break

                # Esperar a que al menos un worker termine (timeout breve de 0.1s para permitir repriorizar)
                from concurrent.futures import wait, FIRST_COMPLETED
                done, not_done = wait(active_futures.keys(), timeout=0.15, return_when=FIRST_COMPLETED)

                for fut in done:
                    p_idx = active_futures.pop(fut)
                    if not self._running:
                        break
                    try:
                        result = fut.result()
                        if result is not None and self._running:
                            page_idx, scale, dims, sz = result
                            self.page_completed.emit(page_idx, scale, dims, sz)
                    except Exception:
                        pass

        finally:
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                self._executor = None

        if self._running:
            self.indexing_finished.emit()

class BackgroundIndexer(QObject):
    """
    Administrador del indexador de caché en segundo plano.
    Coordina los subprocesos de procesamiento y emite el progreso a la UI.
    """
    progress = Signal(int, int)  # (cached_count, total_count)
    page_saved = Signal(int, float, tuple)  # (page_idx, scale, dims)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._coordinator: _IndexerCoordinatorThread | None = None
        self._current_total: int = 0

    @staticmethod
    def get_optimal_worker_count() -> int:
        cpu_cnt = os.cpu_count() or 4
        if cpu_cnt <= 2:
            return 1
        elif cpu_cnt <= 4:
            return 2
        elif cpu_cnt <= 8:
            return 4
        else:
            # En CPUs de 12 a 24 hilos (ej. Ryzen 9 5900X), usar 6 u 8 workers
            return min(8, cpu_cnt - 4)

    def set_current_page(self, current_page: int):
        """Notifica al indexador qué página está visualizando el usuario para priorizarla inmediatamente."""
        if self._coordinator and self._coordinator.isRunning():
            self._coordinator.set_current_page(current_page)

    def start_indexing(
        self,
        pdf_path: str,
        total_pages: int,
        uncached_pages: list[int],
        output_dir: Path,
        initial_page: int = 0,
    ):
        """Inicia el proceso de indexado multiproceso en segundo plano."""
        self.stop()

        self._current_total = total_pages
        if not uncached_pages:
            self.progress.emit(total_pages, total_pages)
            self.finished.emit()
            return

        workers = self.get_optimal_worker_count()
        self._coordinator = _IndexerCoordinatorThread(
            pdf_path=pdf_path,
            uncached_pages=uncached_pages,
            output_dir=output_dir,
            max_workers=workers,
            initial_page=initial_page,
            parent=self,
        )
        self._coordinator.page_completed.connect(self._on_page_completed)
        self._coordinator.indexing_finished.connect(self._on_indexing_finished)
        self._coordinator.start()

    def _on_page_completed(
        self, page_idx: int, scale: float, dims: tuple[float, float], file_size: int
    ):
        self.page_saved.emit(page_idx, scale, dims)

    def _on_indexing_finished(self):
        self.finished.emit()

    def stop(self):
        """Cancela y detiene el proceso de indexado en curso si existe."""
        if self._coordinator is not None:
            if self._coordinator.isRunning():
                self._coordinator.stop()
                self._coordinator.wait(500)
            self._coordinator = None
