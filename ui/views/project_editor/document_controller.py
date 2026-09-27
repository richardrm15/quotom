# ui/views/document_controller.py
from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import QImage, QPixmap

from common.pdf.pdf_worker import PdfWorker
from common.pdf.page_cache import SlidingPageCache
from common.pdf.background_indexer import BackgroundIndexer

logger = logging.getLogger("quotom")


class DocumentController(QObject):
    """
    Controlador central para la gestión del documento PDF activo, caché de renderizado,
    indexación en segundo plano y detección de cambios de archivo en disco.
    Totalmente desacoplado de la interfaz gráfica: se comunica exclusivamente por señales Qt.
    """

    document_loaded = Signal(str, int)                      # pdf_path, total_pages
    page_ready = Signal(int, QPixmap, float, tuple, str)    # page_idx, pixmap, scale, dims, source
    text_data_ready = Signal(int, object)                   # page_idx, text_data
    cache_progress_updated = Signal(int, int)               # cached, total
    loading_state_changed = Signal(bool)                    # is_loading
    status_message_requested = Signal(str)
    reload_prompt_requested = Signal(str)                   # file_path
    error_occurred = Signal(str)                            # error_message

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._current_pdf_path: str | None = None
        self._current_page: int = 0
        self._total_pages: int = 0
        self._is_loading_page: bool = False
        self._watcher_paused: bool = False
        self._preserve_view_on_render: bool = False

        self._cache = SlidingPageCache()
        self._worker = PdfWorker(self)
        self._indexer = BackgroundIndexer(self)
        self._file_watcher = QFileSystemWatcher(self)

        self._setup_connections()
        self._worker.start()

    def _setup_connections(self):
        self._worker.document_loaded.connect(self._on_worker_document_loaded)
        self._worker.page_rendered.connect(self._on_worker_page_rendered)
        self._worker.cache_progress.connect(self.cache_progress_updated.emit)
        self._worker.text_data_ready.connect(self._on_worker_text_data_ready)
        self._worker.error_occurred.connect(self.error_occurred.emit)

        self._indexer.page_saved.connect(self._on_indexer_page_saved)
        self._file_watcher.fileChanged.connect(self._on_external_file_changed)

    # =========================================================================
    # PROPIEDADES DE ESTADO
    # =========================================================================

    @property
    def current_pdf_path(self) -> str | None:
        return self._current_pdf_path

    @current_pdf_path.setter
    def current_pdf_path(self, path: str | None):
        self._current_pdf_path = path

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def total_pages(self) -> int:
        return self._total_pages

    @total_pages.setter
    def total_pages(self, count: int):
        self._total_pages = count

    @property
    def is_loading(self) -> bool:
        return self._is_loading_page

    @property
    def preserve_view_on_render(self) -> bool:
        return self._preserve_view_on_render

    @property
    def cache(self) -> SlidingPageCache:
        return self._cache

    @property
    def disk_cache(self):
        return self._worker.disk_cache

    # =========================================================================
    # VIGILANCIA DE ARCHIVOS (File Watcher)
    # =========================================================================

    def pause_file_watcher(self):
        self._watcher_paused = True

    def resume_file_watcher(self):
        QTimer.singleShot(600, lambda: setattr(self, "_watcher_paused", False))

    # =========================================================================
    # OPERACIONES DEL DOCUMENTO
    # =========================================================================

    def open_document(self, pdf_path: str, initial_page: int = 0, force_reindex: bool = False):
        """Inicia la carga asíncrona de un documento PDF, configurando observadores y workers."""
        self._indexer.stop()
        if force_reindex and hasattr(self._worker, "disk_cache"):
            self._worker.disk_cache.set_document(pdf_path)
            self._worker.disk_cache.invalidate_current_document()

        self._current_pdf_path = pdf_path
        self._current_page = initial_page
        self._cache.clear()
        self._set_loading(True)

        try:
            watches = self._file_watcher.files()
            if watches:
                self._file_watcher.removePaths(watches)
            if Path(pdf_path).exists():
                self._file_watcher.addPath(str(Path(pdf_path).resolve()))
        except Exception as exc:
            logger.debug("No se pudo configurar QFileSystemWatcher para %s: %s", pdf_path, exc)

        self._worker.open_document(pdf_path)

    def close_document(self):
        """Cierra el documento actual, deteniendo indexación y liberando recursos."""
        self._indexer.stop()
        self._worker.close_document()
        self._current_pdf_path = None
        self._total_pages = 0
        self._current_page = 0
        self._cache.clear()
        try:
            watches = self._file_watcher.files()
            if watches:
                self._file_watcher.removePaths(watches)
        except Exception as exc:
            logger.debug("No se pudo limpiar QFileSystemWatcher: %s", exc)

    def clear_cache(self, pdf_path: str | None = None):
        """Limpia la memoria caché en RAM y opcionalmente invalida la caché de disco."""
        self._cache.clear()
        if hasattr(self._worker, "disk_cache"):
            if pdf_path:
                self._worker.disk_cache.set_document(pdf_path)
            self._worker.disk_cache.invalidate_current_document()

    def request_page(self, page_index: int, preserve_view: bool = True):
        """Solicita una página: si está en RAM la entrega inmediatamente, sino delega a PdfWorker."""
        if not self._current_pdf_path or self._total_pages <= 0:
            return

        self._preserve_view_on_render = preserve_view
        self._indexer.set_current_page(page_index)
        self._cache.prune_outside_window(page_index)

        # 1. Chequeo de RAM
        cached = self._cache.get(page_index)
        if cached:
            self._set_loading(False)
            self._current_page = page_index
            self.page_ready.emit(page_index, cached.pixmap, cached.scale, cached.dimensions_pts, "ram")
            text_data = cached.text_data or self._cache.get_text_data(page_index)
            if text_data:
                self.text_data_ready.emit(page_index, text_data)
            else:
                self._worker.request_text(page_index, cached.scale)
            self._trigger_prefetch(page_index)
            return

        # 2. Requerir render al worker asíncrono
        self._set_loading(True)
        self._current_page = page_index
        text_data = self._cache.get_text_data(page_index)
        if text_data:
            self.text_data_ready.emit(page_index, text_data)
        self._worker.request_page(page_index)

    def _trigger_prefetch(self, page_index: int):
        """Prefetch predictivo de páginas adyacentes dentro del radio de caché."""
        for dist in range(1, self._cache.radius + 1):
            next_p = page_index + dist
            if next_p < self._total_pages and not self._cache.contains(next_p):
                self._worker.prefetch_page(next_p)
            prev_p = page_index - dist
            if prev_p >= 0 and not self._cache.contains(prev_p):
                self._worker.prefetch_page(prev_p)

    # =========================================================================
    # SLOTS DE RESPUESTA A WORKERS
    # =========================================================================

    def _on_worker_document_loaded(self, pdf_path: str, total_pages: int):
        self._total_pages = total_pages
        self.document_loaded.emit(pdf_path, total_pages)
        if total_pages > 0:
            target = max(0, min(self._current_page, total_pages - 1))
            self.request_page(target, preserve_view=False)

            uncached = self._worker.disk_cache.uncached_pages(total_pages)
            if uncached and self._worker.disk_cache.doc_dir:
                self._indexer.start_indexing(
                    pdf_path=pdf_path,
                    total_pages=total_pages,
                    uncached_pages=uncached,
                    output_dir=self._worker.disk_cache.doc_dir,
                    initial_page=target,
                )

    def _on_worker_page_rendered(
        self,
        page_index: int,
        qimage: QImage,
        scale: float,
        dims_pts: tuple,
        gen_id: int,
        is_prefetch: bool,
        source: str = "render",
    ):
        pixmap = QPixmap.fromImage(qimage)
        self._cache.put(page_index, pixmap, scale, dims_pts)
        if page_index == self._current_page:
            self._set_loading(False)
            self.page_ready.emit(page_index, pixmap, scale, dims_pts, source)
            self._cache.prune_outside_window(self._current_page)
            self._trigger_prefetch(self._current_page)

    def _on_worker_text_data_ready(self, page_index: int, text_data: object, gen_id: int):
        self._cache.set_text_data(page_index, text_data)
        if page_index == self._current_page:
            self.text_data_ready.emit(page_index, text_data)

    def _on_indexer_page_saved(self, page_idx: int, scale: float, dims: tuple):
        self._worker.disk_cache.register_saved_page(page_idx, scale, dims)
        self.cache_progress_updated.emit(self._worker.disk_cache.cached_count, self._total_pages)

    def _on_external_file_changed(self, file_path: str):
        if self._watcher_paused or not self._current_pdf_path:
            return
        if Path(file_path).resolve() == Path(self._current_pdf_path).resolve():
            QTimer.singleShot(400, lambda: self.reload_prompt_requested.emit(file_path))

    def _set_loading(self, loading: bool):
        self._is_loading_page = loading
        self.loading_state_changed.emit(loading)

    def stop(self):
        """Detiene todos los hilos y tareas en segundo plano de forma segura."""
        if self._worker.isRunning():
            self._worker.stop()
        self._indexer.stop()
