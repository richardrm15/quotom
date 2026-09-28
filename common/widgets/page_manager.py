"""
Módulo del Gestor de Páginas Desacoplado (Page Manager Window).

Permite organizar, inspeccionar y editar las páginas del plano PDF activo:
1. Cuadrícula responsiva de miniaturas (thumbnails) con número de página y nombre.
2. Carga progresiva y asíncrona de miniaturas en segundo plano (no congela la interfaz).
3. Operaciones de página:
   - Agregar páginas (desde otro archivo PDF o página en blanco).
   - Duplicar página seleccionada.
   - Eliminar página seleccionada con confirmación de seguridad.
   - Reordenar páginas (mover izquierda / derecha).
4. Vista previa a tamaño completo:
   - Al hacer clic en una tarjeta o miniatura, se abre a pantalla completa en la ventana.
   - Botón '← Volver a la cuadrícula' para regresar instantáneamente.
   - Navegación anterior / siguiente dentro de la vista ampliada.
5. Guardado seguro y sincronización de base de datos:
   - Ensamblado y guardado atómico del archivo PDF en disco.
   - Sincronización automática de conteo de páginas y remapeo de marcas en SQLite (project.db).
6. Estética idéntica a la ventana principal:
   - Ventana Frameless desacoplada con barra de título personalizada (CustomTitleBar).
   - Botones de minimizar, maximizar/restaurar y cerrar con dibujo vectorial.
   - Redimensionamiento perimetral en los 8 bordes/esquinas (WindowResizeFilter).
   - Pleno soporte de temas Claro y Oscuro con tokens de ThemeManager.
"""

from pathlib import Path
from typing import Optional, List
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

import shiboken6
from PySide6.QtCore import Qt, Signal, QSize, QThread, QPointF, QRectF, QEvent, QItemSelectionModel
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QPainter,
    QPen,
    QColor,
    QCursor,
    QFont,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QStackedWidget,
    QFileDialog,
    QMessageBox,
    QMenu,
    QSizePolicy,
    QInputDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QGraphicsView,
)

from common.styles.style_manager import ThemeManager
from common.widgets.title_bar import CustomTitleBar
from common.widgets.window_resizer import WindowResizeFilter
from common.widgets.graphics_view import PlanGraphicsView
from common.pdf.pdf_renderer import extract_pdf_page_names, calculate_optimal_scale
from core.project import ProjectManager
import queue
from common.pdf.page_cache import SlidingPageCache, CachedPage
from common.pdf.disk_cache import DiskPageCache
from core.pdf_lock import PDFIUM_LOCK


class PageItemData:
    """Representación en memoria de una página dentro del editor de páginas."""

    def __init__(
        self,
        original_index: Optional[int],
        page_name: str,
        source_pdf: str,
        source_page_idx: int,
    ):
        self.original_index = original_index  # Índice 0-based en el PDF original, o None si es nueva/duplicada
        self.page_name = page_name
        self.source_pdf = source_pdf
        self.source_page_idx = source_page_idx
        self.thumbnail: Optional[QPixmap] = None

    def clone(self) -> 'PageItemData':
        item = PageItemData(self.original_index, self.page_name, self.source_pdf, self.source_page_idx)
        item.thumbnail = self.thumbnail
        return item


class FullPageWorker(QThread):
    """
    Worker serializado en segundo plano para renderizar y precargar páginas completas en alta resolución.
    Se apoya en la Tier 2 Disk Cache (SSD WebP Lossless) para latencias mínimas y evita bloqueos en la UI.
    """
    page_ready = Signal(int, QImage, float, tuple, str)  # (item_idx, pixmap, scale, dims, source)

    def __init__(self, items: List[PageItemData], disk_cache: DiskPageCache, parent=None):
        super().__init__(parent)
        self._items = items
        self._disk_cache = disk_cache
        self._queue = queue.PriorityQueue()
        self._running = True
        self._cached_docs: dict[str, pdfium.PdfDocument] = {}

    def stop(self):
        self._running = False
        self._queue.put((-1, -1, ""))  # Señal para desbloquear get()
        self.wait()
        with PDFIUM_LOCK:
            for doc in self._cached_docs.values():
                try:
                    doc.close()
                except Exception:
                    pass
            self._cached_docs.clear()

    def request_page(self, item_idx: int):
        """Solicitud prioritaria inmediata (0) para la página visible."""
        self._queue.put((0, item_idx, "render"))

    def prefetch_page(self, item_idx: int):
        """Solicitud de precarga predictiva en segundo plano (1)."""
        self._queue.put((1, item_idx, "prefetch"))

    def run(self):
        while self._running:
            try:
                priority, item_idx, req_type = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if not self._running or item_idx < 0:
                break

            if not (0 <= item_idx < len(self._items)):
                self._queue.task_done()
                continue

            item = self._items[item_idx]

            # 1. Caso página en blanco
            if item.source_pdf == ":blank:":
                vw, vh = 1600, 1100
                img = QImage(vw, vh, QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(Qt.GlobalColor.white)
                p = QPainter(img)
                p.setPen(QPen(QColor("#CCCCCC"), 2, Qt.PenStyle.DashLine))
                p.drawRect(20, 20, vw - 40, vh - 40)
                p.setPen(QPen(QColor("#888888")))
                p.setFont(QFont("sans-serif", 20, QFont.Weight.Bold))
                p.drawText(QRectF(0, 0, vw, vh), Qt.AlignmentFlag.AlignCenter, "Página en Blanco")
                p.end()
                self.page_ready.emit(item_idx, img, 1.0, (float(vw), float(vh)), "blank")
                self._queue.task_done()
                continue

            # 2. Caso Tier 2 Disk Cache (SSD WebP Lossless)
            if (
                self._disk_cache.doc_dir
                and item.source_page_idx is not None
                and self._disk_cache.has_page(item.source_page_idx)
            ):
                cached_disk = self._disk_cache.load_page(item.source_page_idx)
                if cached_disk is not None:
                    qimg, scale, dims = cached_disk
                    self.page_ready.emit(item_idx, qimg, scale, dims, "disk")
                    self._queue.task_done()
                    continue

            # 3. Renderizado con PDFium en hilo secundario
            if not Path(item.source_pdf).exists():
                self._queue.task_done()
                continue

            try:
                with PDFIUM_LOCK:
                    if not self._running:
                        break
                    if item.source_pdf not in self._cached_docs:
                        self._cached_docs[item.source_pdf] = pdfium.PdfDocument(item.source_pdf)
                    doc = self._cached_docs[item.source_pdf]
                    if item.source_page_idx >= len(doc):
                        self._queue.task_done()
                        continue

                    page = doc[item.source_page_idx]
                    w_pts, h_pts = page.get_size()
                    scale = calculate_optimal_scale(w_pts, h_pts)

                    bm = page.render(scale=scale)
                    try:
                        w, h, stride = bm.width, bm.height, bm.stride
                        raw_bytes = bytes(bm.buffer)
                        fmt = QImage.Format.Format_BGR888
                        temp_image = QImage(raw_bytes, w, h, stride, fmt)
                        qimg = temp_image.copy()
                    finally:
                        bm.close()

                # Guardar en Tier 2 Disk Cache si corresponde al documento actual
                if self._disk_cache.doc_dir and item.source_page_idx is not None:
                    self._disk_cache.save_page(item.source_page_idx, qimg, scale, (w_pts, h_pts))

                self.page_ready.emit(item_idx, qimg, scale, (w_pts, h_pts), "render")
            except Exception:
                pass
            finally:
                self._queue.task_done()


class ThumbnailLoaderThread(QThread):
    """
    Hilo secundario de alto rendimiento para miniaturas.
    Reutiliza la jerarquía unificada de caché:
    1. Tier 1 (RAM compartida): ~0.06 ms si la página está activa en memoria.
    2. Tier 2 (Mini-WebP en SSD): ~0.8 ms si el indexador o una sesión previa ya guardó el thumbnail.
    3. Tier 3 (Renderizado PDFium a 180px): Fallback de ~22 ms guardando el thumbnail de inmediato.
    """

    thumbnail_ready = Signal(int, QPixmap)  # (item_index, pixmap)

    def __init__(
        self,
        items: List[PageItemData],
        shared_cache: Optional[SlidingPageCache] = None,
        disk_cache: Optional[DiskPageCache] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._items = items
        self._shared_cache = shared_cache
        self._disk_cache = disk_cache
        self._is_running = True

    def stop(self):
        self._is_running = False
        self.wait(1000)

    def run(self):
        cached_docs: dict[str, pdfium.PdfDocument] = {}
        try:
            for idx, item in enumerate(self._items):
                if not self._is_running:
                    break
                if item.thumbnail is not None:
                    continue

                if item.source_pdf == ":blank:":
                    pix = QPixmap(180, 240)
                    pix.fill(Qt.GlobalColor.white)
                    p = QPainter(pix)
                    p.setPen(QPen(QColor("#CCCCCC"), 1, Qt.PenStyle.DashLine))
                    p.drawRect(5, 5, 170, 230)
                    p.setPen(QPen(QColor("#888888")))
                    p.setFont(QFont("sans-serif", 10, QFont.Weight.Medium))
                    p.drawText(QRectF(10, 100, 160, 40), Qt.AlignmentFlag.AlignCenter, "Página en Blanco")
                    p.end()
                    self.thumbnail_ready.emit(idx, pix)
                    continue

                if not Path(item.source_pdf).exists():
                    continue

                # 1. Tier 1: Memoria RAM compartida de la ventana principal (< 0.1 ms)
                if self._shared_cache and item.source_page_idx is not None:
                    cached = self._shared_cache.get(item.source_page_idx)
                    if cached and cached.pixmap and not cached.pixmap.isNull():
                        thumb_pix = cached.pixmap.scaled(
                            180, 220,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.FastTransformation,
                        )
                        if self._is_running:
                            self.thumbnail_ready.emit(idx, thumb_pix)
                            if self._disk_cache and not self._disk_cache.has_thumbnail(item.source_page_idx):
                                self._disk_cache.save_thumbnail(item.source_page_idx, thumb_pix)
                            continue

                # 2. Tier 2: Mini-thumbnail sincronizado en disco SSD (~0.8 ms)
                if self._disk_cache and item.source_page_idx is not None:
                    cached_thumb = self._disk_cache.load_thumbnail(item.source_page_idx)
                    if cached_thumb is not None and not cached_thumb.isNull():
                        if self._is_running:
                            self.thumbnail_ready.emit(idx, cached_thumb)
                            continue

                # 3. Tier 3: Renderizado directo desde PDFium a escala reducida (~22 ms)
                try:
                    with PDFIUM_LOCK:
                        if not self._is_running:
                            break
                        if item.source_pdf not in cached_docs:
                            cached_docs[item.source_pdf] = pdfium.PdfDocument(item.source_pdf)
                        doc = cached_docs[item.source_pdf]

                        if item.source_page_idx >= len(doc):
                            continue

                        page = doc[item.source_page_idx]
                        w_pts, h_pts = page.get_size()
                        # Escala para miniaturas (ajuste a caja de 180 x 220 px)
                        scale = min(180.0 / max(1.0, w_pts), 220.0 / max(1.0, h_pts))
                        scale = max(0.04, min(0.35, scale))

                        bm = page.render(scale=scale)
                        try:
                            w, h, stride = bm.width, bm.height, bm.stride
                            raw_bytes = bytes(bm.buffer)
                            qimg = QImage(raw_bytes, w, h, stride, QImage.Format.Format_BGR888).copy()
                            pix = QPixmap.fromImage(qimg)
                            if self._is_running:
                                self.thumbnail_ready.emit(idx, pix)
                                if self._disk_cache and item.source_page_idx is not None:
                                    self._disk_cache.save_thumbnail(item.source_page_idx, pix)
                        finally:
                            bm.close()
                except Exception:
                    pass
        finally:
            for d in cached_docs.values():
                try:
                    d.close()
                except Exception:
                    pass


class PageCardWidget(QFrame):
    """Tarjeta individual que representa una página en la cuadrícula."""

    clicked = Signal(int, Qt.KeyboardModifiers)
    double_clicked = Signal(int)
    duplicate_requested = Signal(int)
    delete_requested = Signal(int)
    rename_requested = Signal(int)

    def __init__(self, index: int, data: PageItemData, parent=None):
        super().__init__(parent)
        self.index = index
        self.data = data
        self._is_selected = False

        self.setObjectName("pageCard")
        self.setFixedSize(200, 260)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Barra superior de la tarjeta (Número de página y acciones rápidas)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(4)

        self._lbl_badge = QLabel(f"Pág. {self.index + 1}", self)
        self._lbl_badge.setObjectName("pageCardBadge")
        top_bar.addWidget(self._lbl_badge)

        top_bar.addStretch()

        self._btn_rename = QPushButton(self)
        self._btn_rename.setObjectName("pageCardActionBtn")
        self._btn_rename.setToolTip("Cambiar el nombre de esta página")
        self._btn_rename.setFixedSize(22, 22)
        self._btn_rename.setIcon(ThemeManager.get_icon("edit", size=14))
        self._btn_rename.clicked.connect(lambda: self.rename_requested.emit(self.index))
        top_bar.addWidget(self._btn_rename)

        self._btn_dup = QPushButton(self)
        self._btn_dup.setObjectName("pageCardActionBtn")
        self._btn_dup.setToolTip("Duplicar esta página")
        self._btn_dup.setFixedSize(22, 22)
        self._btn_dup.setIcon(ThemeManager.get_icon("copy", size=14))
        self._btn_dup.clicked.connect(lambda: self.duplicate_requested.emit(self.index))
        top_bar.addWidget(self._btn_dup)

        self._btn_del = QPushButton(self)
        self._btn_del.setObjectName("pageCardActionBtn")
        self._btn_del.setToolTip("Eliminar esta página")
        self._btn_del.setFixedSize(22, 22)
        self._btn_del.setIcon(ThemeManager.get_icon("trash", size=14))
        self._btn_del.clicked.connect(lambda: self.delete_requested.emit(self.index))
        top_bar.addWidget(self._btn_del)

        layout.addLayout(top_bar)

        # Contenedor central de la miniatura
        self._thumb_container = QFrame(self)
        self._thumb_container.setObjectName("pageCardThumbContainer")
        self._thumb_container.setFixedSize(184, 180)
        thumb_layout = QVBoxLayout(self._thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl_thumb = QLabel(self._thumb_container)
        self._lbl_thumb.setObjectName("pageCardThumbLabel")
        self._lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_thumb.setText("Cargando miniatura...")
        thumb_layout.addWidget(self._lbl_thumb)

        layout.addWidget(self._thumb_container, 0, Qt.AlignmentFlag.AlignCenter)

        # Etiqueta inferior con el nombre del plano
        self._lbl_title = QLabel(self.data.page_name, self)
        self._lbl_title.setObjectName("pageCardTitle")
        self._lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_title.setToolTip(self.data.page_name)
        layout.addWidget(self._lbl_title)

        if self.data.thumbnail:
            self.set_thumbnail(self.data.thumbnail)

        self._update_appearance()

    def set_thumbnail(self, pixmap: QPixmap):
        self.data.thumbnail = pixmap
        scaled = pixmap.scaled(
            176, 172,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._lbl_thumb.setPixmap(scaled)

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self._update_appearance()

    def update_index(self, new_index: int):
        self.index = new_index
        self._lbl_badge.setText(f"Pág. {self.index + 1}")

    def update_page_name(self, new_name: str):
        """Actualiza el nombre visible de la página en la tarjeta."""
        self.data.page_name = new_name
        self._lbl_title.setText(new_name)
        self._lbl_title.setToolTip(new_name)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index, event.modifiers())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.index)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        act_view = menu.addAction(ThemeManager.get_icon("fit-window"), "Ver a tamaño completo")
        act_dup = menu.addAction(ThemeManager.get_icon("copy"), "Duplicar página")
        act_del = menu.addAction(ThemeManager.get_icon("trash"), "Eliminar página")

        chosen = menu.exec(QCursor.pos())
        if chosen == act_view:
            self.double_clicked.emit(self.index)
        elif chosen == act_dup:
            self.duplicate_requested.emit(self.index)
        elif chosen == act_del:
            self.delete_requested.emit(self.index)

    def _update_appearance(self):
        """
        Refresca el estado visual de la tarjeta (Methods Down).

        No aplica estilos: marca la propiedad dinámica ``state`` y fuerza un
        *repolish* para que ``theme.qss`` evalúe las reglas
        ``QFrame#pageCard[state="selected"]`` y ``QLabel#pageCardBadge[state="selected"]``.
        """
        estado = "selected" if self._is_selected else "normal"
        for widget in (self, self._lbl_badge):
            if widget.property("state") != estado:
                widget.setProperty("state", estado)
                widget.style().unpolish(widget)
                widget.style().polish(widget)


class PageManagerWindow(QDialog):
    """Ventana desacoplada completa para gestionar las páginas del plano PDF."""

    pages_saved = Signal(str, int)  # (pdf_path, new_current_page_index)

    def __init__(
        self,
        pdf_path: str,
        project_manager: Optional[ProjectManager] = None,
        initial_page: int = 0,
        parent=None,
        shared_cache: Optional[SlidingPageCache] = None,
        disk_cache: Optional[DiskPageCache] = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._pdf_path = str(pdf_path)
        self._project_mgr = project_manager
        self._current_selected_idx: int = max(0, initial_page)
        self._selected_indices: set[int] = {self._current_selected_idx}
        self._selection_anchor_idx: int = self._current_selected_idx
        self._original_total_pages: int = 0
        self._items: List[PageItemData] = []
        self._card_widgets: List[PageCardWidget] = []
        self._has_unsaved_changes: bool = False
        self._thumb_thread: Optional[ThumbnailLoaderThread] = None

        # Historial de cambios en memoria para Deshacer / Rehacer (Ctrl+Z y Ctrl+Y)
        self._undo_history: list = []
        self._redo_history: list = []

        # Integración con la jerarquía unificada de Caché (Tier 1 RAM y Tier 2 SSD)
        self._shared_cache: Optional[SlidingPageCache] = shared_cache
        self._page_cache: SlidingPageCache = SlidingPageCache(radius=7)
        self._disk_cache: DiskPageCache = disk_cache if disk_cache is not None else DiskPageCache()
        if self._pdf_path and not self._disk_cache.doc_dir:
            self._disk_cache.set_document(self._pdf_path)

        self._full_worker: Optional[FullPageWorker] = None

        self.setObjectName("pageManagerWindow")
        self.resize(1200, 780)
        self.setMinimumSize(850, 540)

        # Filtro de redimensionamiento nativo (8 bordes)
        self._resizer = WindowResizeFilter(self)
        self.installEventFilter(self._resizer)

        # Construcción visual
        self._init_ui()
        self._load_initial_pages()

        # Iniciar worker unificado en segundo plano para renderizado y precarga
        self._full_worker = FullPageWorker(self._items, self._disk_cache, self)
        self._full_worker.page_ready.connect(self._on_full_page_ready)
        self._full_worker.start()

        # Atajos de teclado para Deshacer / Rehacer en memoria
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)


    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Contenedor con borde perimetral para ventanas frameless
        self._main_container = QFrame(self)
        self._main_container.setObjectName("pageManagerMainFrame")
        container_layout = QVBoxLayout(self._main_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # 1. Barra de título personalizada (CSD)
        drawing_title = Path(self._pdf_path).name if self._pdf_path else "Plano"
        self._title_bar = CustomTitleBar(self, title=f"Gestor de Páginas — {drawing_title}")
        container_layout.addWidget(self._title_bar)

        # 2. QStackedWidget: [0] Cuadrícula de Páginas | [1] Vista a Tamaño Completo
        self._stack = QStackedWidget(self)

        self._grid_view = self._build_grid_view()
        self._stack.addWidget(self._grid_view)

        self._full_view = self._build_full_view()
        self._stack.addWidget(self._full_view)

        container_layout.addWidget(self._stack, 1)
        root_layout.addWidget(self._main_container)

        self._apply_theme()

    def _build_grid_view(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Barra de herramientas superior de la cuadrícula
        self._toolbar = QFrame(widget)
        self._toolbar.setObjectName("pageManagerToolbar")
        self._toolbar.setFixedHeight(44)
        tb_layout = QHBoxLayout(self._toolbar)
        tb_layout.setContentsMargins(10, 6, 10, 6)
        tb_layout.setSpacing(6)

        # --- GRUPO IZQUIERDO: Operaciones de página ---
        self._btn_add_pdf = QPushButton("+ PDF", self._toolbar)
        self._btn_add_pdf.setIcon(ThemeManager.get_icon("file-pdf"))
        self._btn_add_pdf.setToolTip("Agregar páginas desde un archivo PDF existente...")
        self._btn_add_pdf.clicked.connect(self._on_add_pages_from_pdf)
        tb_layout.addWidget(self._btn_add_pdf)

        self._btn_add_blank = QPushButton("+ Blanco", self._toolbar)
        self._btn_add_blank.setIcon(ThemeManager.get_icon("plus"))
        self._btn_add_blank.setToolTip("Agregar una página en blanco")
        self._btn_add_blank.clicked.connect(self._on_add_blank_page)
        tb_layout.addWidget(self._btn_add_blank)

        self._btn_duplicate = QPushButton("Duplicar", self._toolbar)
        self._btn_duplicate.setIcon(ThemeManager.get_icon("copy"))
        self._btn_duplicate.setToolTip("Duplicar las páginas seleccionadas")
        self._btn_duplicate.clicked.connect(self._duplicate_selected_pages)
        tb_layout.addWidget(self._btn_duplicate)

        self._btn_delete = QPushButton("Eliminar", self._toolbar)
        self._btn_delete.setIcon(ThemeManager.get_icon("trash"))
        self._btn_delete.setToolTip("Eliminar las páginas seleccionadas (Supr)")
        self._btn_delete.clicked.connect(self._delete_selected_pages)
        tb_layout.addWidget(self._btn_delete)

        self._btn_rename = QPushButton("Renombrar", self._toolbar)
        self._btn_rename.setIcon(ThemeManager.get_icon("edit"))
        self._btn_rename.setToolTip("Cambiar el nombre de la página seleccionada")
        self._btn_rename.clicked.connect(lambda: self._rename_page(self._current_selected_idx))
        tb_layout.addWidget(self._btn_rename)

        self._btn_auto_name = QPushButton("Auto-Nombrar...", self._toolbar)
        self._btn_auto_name.setIcon(ThemeManager.get_icon("text_select"))
        self._btn_auto_name.setToolTip("Nombrar páginas automáticamente capturando regiones de texto (ej. cajetín)")
        self._btn_auto_name.clicked.connect(self._open_auto_namer)
        tb_layout.addWidget(self._btn_auto_name)

        # --- DESHACER / REHACER ---
        self._btn_undo = QPushButton(self._toolbar)
        self._btn_undo.setIcon(ThemeManager.get_icon("undo"))
        self._btn_undo.setToolTip("Deshacer último cambio (Ctrl + Z)")
        self._btn_undo.clicked.connect(self.undo)
        self._btn_undo.setEnabled(False)
        tb_layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton(self._toolbar)
        self._btn_redo.setIcon(ThemeManager.get_icon("redo"))
        self._btn_redo.setToolTip("Rehacer cambio (Ctrl + Y)")
        self._btn_redo.clicked.connect(self.redo)
        self._btn_redo.setEnabled(False)
        tb_layout.addWidget(self._btn_redo)

        # --- SEPARADOR Y MODO DE VISUALIZACIÓN ---
        sep_left = QFrame(self._toolbar)
        sep_left.setObjectName("pageToolbarSeparator")
        sep_left.setFrameShape(QFrame.Shape.VLine)
        tb_layout.addWidget(sep_left)

        self._btn_view_toggle = QPushButton("Vista Lista", self._toolbar)
        self._btn_view_toggle.setIcon(ThemeManager.get_icon("list"))
        self._btn_view_toggle.setToolTip("Alternar entre vista de cuadrícula (miniaturas) y vista de lista compacta")
        self._btn_view_toggle.clicked.connect(self._toggle_view_mode)
        tb_layout.addWidget(self._btn_view_toggle)

        self._lbl_count_info = QLabel("Total: 0 págs", self._toolbar)
        self._lbl_count_info.setObjectName("pageCountLabel")
        tb_layout.addWidget(self._lbl_count_info)

        tb_layout.addStretch(1)

        # --- GRUPO DERECHO: Acciones de confirmación y cierre (Contenedor dedicado para evitar traslapes) ---
        right_box = QWidget(self._toolbar)
        right_layout = QHBoxLayout(right_box)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self._btn_save = QPushButton("Guardar cambios", right_box)
        self._btn_save.setObjectName("primaryActionButton")
        self._btn_save.setIcon(ThemeManager.get_icon("save"))
        self._btn_save.setFixedHeight(28)
        self._btn_save.clicked.connect(self._save_changes)
        right_layout.addWidget(self._btn_save)

        self._btn_close = QPushButton("Cerrar", right_box)
        self._btn_close.setFixedHeight(28)
        self._btn_close.clicked.connect(self.close)
        right_layout.addWidget(self._btn_close)

        tb_layout.addWidget(right_box)

        layout.addWidget(self._toolbar)

        # Stack de contenido: 0 -> Cuadrícula de miniaturas, 1 -> Lista detallada
        self._content_stack = QStackedWidget(widget)

        # 0. Cuadrícula de miniaturas
        self._scroll_area = QScrollArea(self._content_stack)
        self._scroll_area.setObjectName("pageGridScrollArea")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._grid_container = QWidget()
        self._grid_container.setObjectName("pageGridContainer")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(16, 16, 16, 16)
        self._grid_layout.setSpacing(16)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll_area.setWidget(self._grid_container)
        self._scroll_area.viewport().installEventFilter(self)
        self._content_stack.addWidget(self._scroll_area)

        # 1. Tabla / Vista de lista
        self._table_view = self._build_table_view()
        self._content_stack.addWidget(self._table_view)

        layout.addWidget(self._content_stack, 1)

        return widget

    def _build_table_view(self) -> QWidget:
        """Construye la vista de tabla para edición ágil tipo lista."""
        table = QTableWidget(self)
        table.setObjectName("pageListTable")
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Nº Página", "Nombre de la Hoja", "Archivo Origen"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)

        table.itemSelectionChanged.connect(self._on_table_selection_changed)
        table.cellDoubleClicked.connect(self._on_table_cell_double_clicked)
        table.itemChanged.connect(self._on_table_item_changed)
        return table

    def _rebuild_table(self):
        """Puebla la tabla de páginas sincronizándola con self._items."""
        if not hasattr(self, "_table_view"):
            return
        self._is_updating_table = True
        try:
            self._table_view.setRowCount(len(self._items))
            for row, item in enumerate(self._items):
                # Columna 0: Número
                num_item = QTableWidgetItem(f"Pág. {row + 1}")
                num_item.setFlags(num_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table_view.setItem(row, 0, num_item)

                # Columna 1: Nombre editable
                name_item = QTableWidgetItem(item.page_name)
                self._table_view.setItem(row, 1, name_item)

                # Columna 2: Fuente
                src_name = Path(item.source_pdf).name if item.source_pdf else "En blanco"
                src_item = QTableWidgetItem(src_name)
                src_item.setFlags(src_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                src_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._table_view.setItem(row, 2, src_item)

            self._sync_table_selection()
        finally:
            self._is_updating_table = False

    def _sync_table_selection(self):
        """Sincroniza self._selected_indices con la selección visual en la tabla."""
        if not hasattr(self, "_table_view") or getattr(self, "_is_updating_table", False):
            return
        self._is_updating_table = True
        try:
            self._table_view.clearSelection()
            sel_model = self._table_view.selectionModel()
            for row in self._selected_indices:
                if 0 <= row < self._table_view.rowCount():
                    idx = self._table_view.model().index(row, 0)
                    sel_model.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        finally:
            self._is_updating_table = False

    def _on_table_selection_changed(self):
        """Sincroniza la selección de la tabla hacia _selected_indices y la cuadrícula de tarjetas."""
        if getattr(self, "_is_updating_table", False):
            return
        selected_rows = {index.row() for index in self._table_view.selectionModel().selectedRows()}
        if selected_rows:
            self._selected_indices = selected_rows
            self._selection_anchor_idx = min(selected_rows)
            self._current_selected_idx = self._selection_anchor_idx
            self._update_selection_visuals(update_table=False)

    def _on_table_cell_double_clicked(self, row: int, column: int):
        """Doble clic en el número de página abre la vista a pantalla completa."""
        if column == 0:
            self._open_full_view(row)

    def _on_table_item_changed(self, item: QTableWidgetItem):
        """Maneja la edición directa en la celda del nombre de la página."""
        if getattr(self, "_is_updating_table", False):
            return
        if item.column() == 1:
            row = item.row()
            if 0 <= row < len(self._items):
                clean_name = item.text().strip() or f"Página {row + 1}"
                if self._items[row].page_name != clean_name:
                    self._push_undo_state()
                    self._items[row].page_name = clean_name
                    self._has_unsaved_changes = True
                    if row < len(self._card_widgets):
                        self._card_widgets[row].update_page_name(clean_name)

    def _toggle_view_mode(self):
        """Alterna entre la vista de cuadrícula (miniaturas) y la vista de lista."""
        if self._content_stack.currentIndex() == 0:
            self._set_view_mode("list")
        else:
            self._set_view_mode("grid")

    def _set_view_mode(self, mode: str):
        """Configura el modo de visualización activo ('list' o 'grid')."""
        if mode == "list":
            self._content_stack.setCurrentIndex(1)
            self._btn_view_toggle.setText("Vista Cuadrícula")
            self._btn_view_toggle.setIcon(ThemeManager.get_icon("grid"))
            self._btn_view_toggle.setToolTip("Cambiar a vista de cuadrícula con miniaturas")
            self._sync_table_selection()
            if self._selected_indices:
                target_row = min(self._selected_indices)
                item = self._table_view.item(target_row, 0)
                if item:
                    self._table_view.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
        else:
            self._content_stack.setCurrentIndex(0)
            self._btn_view_toggle.setText("Vista Lista")
            self._btn_view_toggle.setIcon(ThemeManager.get_icon("list"))
            self._btn_view_toggle.setToolTip("Cambiar a modo de lista con sólo número y nombre")
            self._relayout_grid(force=True)
            self._update_selection_visuals(update_table=False)

    def _build_full_view(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Barra superior de la vista previa
        header = QFrame(widget)
        header.setObjectName("fullViewHeader")
        header.setFixedHeight(44)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 6, 12, 6)
        h_layout.setSpacing(10)

        self._btn_back_grid = QPushButton("  Volver a la cuadrícula", header)
        self._btn_back_grid.setObjectName("btnBackGrid")
        self._btn_back_grid.setIcon(ThemeManager.get_icon("arrow-left"))
        self._btn_back_grid.clicked.connect(self._back_to_grid)
        h_layout.addWidget(self._btn_back_grid)

        h_layout.addStretch()

        self._btn_prev_full = QPushButton("<", header)
        self._btn_prev_full.setFixedSize(28, 28)
        self._btn_prev_full.clicked.connect(self._prev_full_page)
        h_layout.addWidget(self._btn_prev_full)

        self._lbl_full_title = QLabel("Página 1 de 1", header)
        self._lbl_full_title.setObjectName("fullViewTitle")
        h_layout.addWidget(self._lbl_full_title)

        self._btn_next_full = QPushButton(">", header)
        self._btn_next_full.setFixedSize(28, 28)
        self._btn_next_full.clicked.connect(self._next_full_page)
        h_layout.addWidget(self._btn_next_full)

        h_layout.addStretch()

        self._btn_full_dup = QPushButton("Duplicar", header)
        self._btn_full_dup.setIcon(ThemeManager.get_icon("copy"))
        self._btn_full_dup.clicked.connect(lambda: self._duplicate_page(self._current_selected_idx))
        h_layout.addWidget(self._btn_full_dup)

        self._btn_full_rename = QPushButton("Renombrar", header)
        self._btn_full_rename.setIcon(ThemeManager.get_icon("edit"))
        self._btn_full_rename.setToolTip("Cambiar el nombre de esta página")
        self._btn_full_rename.clicked.connect(lambda: self._rename_page(self._current_selected_idx))
        h_layout.addWidget(self._btn_full_rename)

        self._btn_full_del = QPushButton("Eliminar", header)
        self._btn_full_del.setIcon(ThemeManager.get_icon("trash"))
        self._btn_full_del.clicked.connect(lambda: self._delete_page(self._current_selected_idx))
        h_layout.addWidget(self._btn_full_del)

        self._btn_full_undo = QPushButton(header)
        self._btn_full_undo.setIcon(ThemeManager.get_icon("undo"))
        self._btn_full_undo.setToolTip("Deshacer último cambio (Ctrl + Z)")
        self._btn_full_undo.clicked.connect(self.undo)
        self._btn_full_undo.setEnabled(False)
        h_layout.addWidget(self._btn_full_undo)

        self._btn_full_redo = QPushButton(header)
        self._btn_full_redo.setIcon(ThemeManager.get_icon("redo"))
        self._btn_full_redo.setToolTip("Rehacer cambio (Ctrl + Y)")
        self._btn_full_redo.clicked.connect(self.redo)
        self._btn_full_redo.setEnabled(False)
        h_layout.addWidget(self._btn_full_redo)

        self._btn_full_save = QPushButton("Guardar", header)
        self._btn_full_save.setObjectName("primaryActionButton")
        self._btn_full_save.setIcon(ThemeManager.get_icon("save"))
        self._btn_full_save.clicked.connect(self._save_changes)
        h_layout.addWidget(self._btn_full_save)

        layout.addWidget(header)

        # Controles rápidos de zoom en la barra superior
        self._btn_full_zoom_out = QPushButton(header)
        self._btn_full_zoom_out.setFixedSize(28, 28)
        self._btn_full_zoom_out.setToolTip("Reducir zoom [Rueda abajo]")
        self._btn_full_zoom_out.setIcon(ThemeManager.get_icon("zoom-out"))
        self._btn_full_zoom_out.clicked.connect(lambda: self._full_viewer.zoom_out())
        h_layout.addWidget(self._btn_full_zoom_out)

        self._btn_full_fit = QPushButton(header)
        self._btn_full_fit.setFixedSize(28, 28)
        self._btn_full_fit.setToolTip("Ajustar a la ventana")
        self._btn_full_fit.setIcon(ThemeManager.get_icon("fit-window"))
        self._btn_full_fit.clicked.connect(lambda: self._full_viewer.fit_in_view())
        h_layout.addWidget(self._btn_full_fit)

        self._btn_full_zoom_in = QPushButton(header)
        self._btn_full_zoom_in.setFixedSize(28, 28)
        self._btn_full_zoom_in.setToolTip("Aumentar zoom [Rueda arriba]")
        self._btn_full_zoom_in.setIcon(ThemeManager.get_icon("zoom-in"))
        self._btn_full_zoom_in.clicked.connect(lambda: self._full_viewer.zoom_in())
        h_layout.addWidget(self._btn_full_zoom_in)

        # Lienzo gráfico interactivo con zoom y paneo continuo
        self._full_viewer = PlanGraphicsView(widget)
        self._full_viewer.setObjectName("fullPageViewer")
        layout.addWidget(self._full_viewer, 1)
        return widget

    def _load_initial_pages(self):
        """Lee la estructura inicial de páginas del PDF y genera los elementos."""
        if not self._pdf_path or not Path(self._pdf_path).exists():
            return

        if self._project_mgr and self._project_mgr.is_active:
            names = self._project_mgr.get_drawing_page_names(self._pdf_path)
        else:
            names = extract_pdf_page_names(self._pdf_path)
        self._original_total_pages = len(names)

        self._items = [
            PageItemData(
                original_index=i,
                page_name=names[i],
                source_pdf=self._pdf_path,
                source_page_idx=i,
            )
            for i in range(self._original_total_pages)
        ]

        self._rebuild_grid()
        self._start_thumbnail_worker()

    def _start_thumbnail_worker(self):
        """Inicia el hilo de renderizado de miniaturas con jerarquía de caché compartida."""
        if self._thumb_thread is not None and self._thumb_thread.isRunning():
            self._thumb_thread.stop()

        self._thumb_thread = ThumbnailLoaderThread(
            items=self._items,
            shared_cache=self._shared_cache,
            disk_cache=self._disk_cache,
            parent=self,
        )
        self._thumb_thread.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_thread.start()

    def _on_thumbnail_ready(self, item_index: int, pixmap: QPixmap):
        if 0 <= item_index < len(self._card_widgets) and item_index < len(self._items):
            self._items[item_index].thumbnail = pixmap
            self._card_widgets[item_index].set_thumbnail(pixmap)

    def _calc_columns_and_margin(self, vp_w: int) -> tuple[int, int]:
        """Calcula el número óptimo de columnas y margen horizontal para llenar el ancho disponible."""
        card_w = 200
        spacing = 16
        min_margin = 16
        available_w = max(card_w + 2 * min_margin, vp_w)
        # Determinar cuántas columnas de tarjetas caben completamente
        cols = max(1, (available_w - min_margin) // (card_w + spacing))
        # Centrar la cuadrícula distribuyendo el margen sobrante equitativamente
        content_w = cols * card_w + (cols - 1) * spacing
        margin_x = max(min_margin, (available_w - content_w) // 2)
        return cols, margin_x

    def _relayout_grid(self, force: bool = False):
        """Reubica dinámicamente las tarjetas existentes para llenar todo el ancho de la ventana."""
        if not self._card_widgets or self._stack.currentIndex() != 0:
            return
        vp_w = self._scroll_area.viewport().width()
        cols, margin_x = self._calc_columns_and_margin(vp_w)

        if not force and cols == getattr(self, "_current_cols", -1):
            self._grid_layout.setContentsMargins(margin_x, 16, margin_x, 16)
            return

        self._current_cols = cols
        for card in self._card_widgets:
            self._grid_layout.removeWidget(card)
            card.setParent(self._grid_container)

        shiboken6.delete(self._grid_layout)
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(margin_x, 16, margin_x, 16)
        self._grid_layout.setSpacing(16)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        for idx, card in enumerate(self._card_widgets):
            row = idx // cols
            col = idx % cols
            self._grid_layout.addWidget(card, row, col)

    def _rebuild_grid(self):
        """Reconstruye visualmente la cuadrícula de tarjetas de páginas llenando el ancho disponible."""
        for w in self._card_widgets:
            w.setParent(None)
            w.deleteLater()
        self._card_widgets.clear()

        vp_w = self._scroll_area.viewport().width()
        cols, margin_x = self._calc_columns_and_margin(vp_w)
        self._current_cols = cols

        while self._grid_layout.count() > 0:
            self._grid_layout.takeAt(0)
        self._grid_layout.setContentsMargins(margin_x, 16, margin_x, 16)
        self._grid_layout.setSpacing(16)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        for idx, item in enumerate(self._items):
            card = PageCardWidget(idx, item, self._grid_container)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self._open_full_view)
            card.duplicate_requested.connect(self._duplicate_page)
            card.delete_requested.connect(self._delete_page)
            card.rename_requested.connect(self._rename_page)

            row = idx // cols
            col = idx % cols
            self._grid_layout.addWidget(card, row, col)
            self._card_widgets.append(card)

        self._update_selection_visuals()
        self._rebuild_table()

    def _update_selection_visuals(self, update_table: bool = True):
        """Actualiza el estado visual de todas las tarjetas y los botones de acción según _selected_indices."""
        total = len(self._items)
        if not self._selected_indices and total > 0:
            self._selected_indices = {max(0, min(self._current_selected_idx, total - 1))}
            self._selection_anchor_idx = min(self._selected_indices)

        # Filtrar posibles índices fuera de rango tras eliminaciones
        self._selected_indices = {i for i in self._selected_indices if 0 <= i < total}
        if not self._selected_indices and total > 0:
            self._selected_indices = {0}
            self._selection_anchor_idx = 0

        for card in self._card_widgets:
            card.set_selected(card.index in self._selected_indices)

        count_sel = len(self._selected_indices)
        if count_sel > 1:
            self._lbl_count_info.setText(f"Total: {total} ({count_sel} sel.)")
            self._btn_rename.setEnabled(False)
            self._btn_delete.setText(f"Eliminar ({count_sel})")
            self._btn_duplicate.setText(f"Duplicar ({count_sel})")
        else:
            self._lbl_count_info.setText(f"Total: {total} págs")
            self._btn_rename.setEnabled(True)
            self._btn_delete.setText("Eliminar")
            self._btn_duplicate.setText("Duplicar")

        if update_table and hasattr(self, "_table_view"):
            self._sync_table_selection()

    def _on_card_clicked(self, index: int, modifiers: Qt.KeyboardModifiers = Qt.KeyboardModifier.NoModifier):
        """Maneja la selección individual, con Ctrl/Cmd (múltiple) y Shift (rango continuo)."""
        is_ctrl = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))
        is_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if is_shift:
            # Shift + Click: Rango desde el anchor actual hasta index
            start = min(self._selection_anchor_idx, index)
            end = max(self._selection_anchor_idx, index)
            range_set = set(range(start, end + 1))

            if is_ctrl:
                # Ctrl + Shift + Click: Añadir el rango a la selección existente
                self._selected_indices.update(range_set)
            else:
                # Shift + Click: Reemplazar selección completa por el rango
                self._selected_indices = range_set

            self._current_selected_idx = index
        elif is_ctrl:
            # Ctrl + Click: Alternar (toggle) selección individual
            if index in self._selected_indices:
                if len(self._selected_indices) > 1:
                    self._selected_indices.remove(index)
                    self._current_selected_idx = next(iter(self._selected_indices))
            else:
                self._selected_indices.add(index)
                self._current_selected_idx = index
            self._selection_anchor_idx = index
        else:
            # Clic normal: Seleccionar únicamente la tarjeta pulsada
            self._selected_indices = {index}
            self._selection_anchor_idx = index
            self._current_selected_idx = index

        self._update_selection_visuals()

    def _on_full_page_ready(self, item_idx: int, qimage: QImage, scale: float, dims: tuple, source: str):
        """Recepción asíncrona de página renderizada desde SSD o hilo secundario."""
        pixmap = QPixmap.fromImage(qimage)
        self._page_cache.put(item_idx, pixmap, scale, dims)
        if item_idx == self._current_selected_idx and self._stack.currentIndex() == 1:
            self._full_viewer.set_page_pixmap(pixmap, preserve_view=False)

    def _open_full_view(self, index: int):
        """Abre la página en alta resolución utilizando la jerarquía de caché unificada."""
        if not (0 <= index < len(self._items)):
            return

        self._current_selected_idx = index
        item = self._items[index]
        self._lbl_full_title.setText(f"Página {index + 1} de {len(self._items)} — {item.page_name}")
        self._stack.setCurrentIndex(1)

        # 1. Nivel 1: Caché RAM local (SlidingPageCache) (< 1 ms)
        cached = self._page_cache.get(index)

        # 2. Nivel 1.5: Caché RAM compartida desde la Ventana Principal (< 1 ms)
        if not cached and self._shared_cache and item.source_pdf == self._pdf_path:
            cached = self._shared_cache.get(item.source_page_idx)
            if cached:
                self._page_cache.put(index, cached.pixmap, cached.scale, cached.dimensions_pts)

        if cached:
            self._full_viewer.set_page_pixmap(cached.pixmap, preserve_view=False)
            self._trigger_full_prefetch(index)
            return

        # 3. Nivel 2: Caché SSD WebP (DiskPageCache) (~60-90 ms)
        if (
            self._disk_cache.doc_dir
            and item.source_pdf == self._pdf_path
            and self._disk_cache.has_page(item.source_page_idx)
        ):
            cached_disk = self._disk_cache.load_page(item.source_page_idx)
            if cached_disk is not None:
                qimg, scale, dims = cached_disk
                pix = QPixmap.fromImage(qimg)
                self._page_cache.put(index, pix, scale, dims)
                self._full_viewer.set_page_pixmap(pix, preserve_view=False)
                self._trigger_full_prefetch(index)
                return

        # 4. Nivel 3: Marcador de posición inmediato con la miniatura (0 ms sensación visual)
        if item.thumbnail is not None:
            self._full_viewer.set_page_pixmap(item.thumbnail, preserve_view=False)

        # Solicitar renderizado en alta resolución al worker en segundo plano
        if self._full_worker is not None:
            self._full_worker.request_page(index)
        self._trigger_full_prefetch(index)

    def _trigger_full_prefetch(self, current_idx: int):
        """Precarga predictiva en segundo plano de páginas adyacentes (+1, -1, +2, -2)."""
        self._page_cache.prune_outside_window(current_idx)
        if self._full_worker is not None:
            for dist in (1, 2, 3):
                next_idx = current_idx + dist
                if next_idx < len(self._items) and not self._page_cache.contains(next_idx):
                    self._full_worker.prefetch_page(next_idx)

                prev_idx = current_idx - dist
                if prev_idx >= 0 and not self._page_cache.contains(prev_idx):
                    self._full_worker.prefetch_page(prev_idx)

    def _back_to_grid(self):
        """Regresa a la vista principal (cuadrícula o lista) y ajusta la visualización."""
        self._stack.setCurrentIndex(0)
        if hasattr(self, "_content_stack") and self._content_stack.currentIndex() == 0:
            self._relayout_grid()
        elif hasattr(self, "_table_view"):
            self._sync_table_selection()

    def _prev_full_page(self):
        if self._current_selected_idx > 0:
            self._open_full_view(self._current_selected_idx - 1)

    def _next_full_page(self):
        if self._current_selected_idx < len(self._items) - 1:
            self._open_full_view(self._current_selected_idx + 1)

    def _open_auto_namer(self):
        """Abre el diálogo desacoplado para extraer texto de cajetines y auto-nombrar páginas."""
        selected = sorted(self._selected_indices) if self._selected_indices else list(range(len(self._items)))
        if not selected:
            QMessageBox.information(self, "Sin selección", "No hay páginas seleccionadas para nombrar.")
            return

        from ui.views.auto_namer import AutoNamerDialog
        dialog = AutoNamerDialog(
            items=self._items,
            selected_indices=selected,
            pdf_path=self._pdf_path,
            parent=self,
            page_cache=self._page_cache,
            disk_cache=self._disk_cache,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            generated = dialog.get_generated_names()
            if generated:
                self._push_undo_state()
            for idx, new_name in generated.items():
                if 0 <= idx < len(self._items) and new_name:
                    self._items[idx].page_name = new_name
                    if idx < len(self._card_widgets):
                        self._card_widgets[idx].update_page_name(new_name)
                    if hasattr(self, "_table_view") and idx < self._table_view.rowCount():
                        self._is_updating_table = True
                        try:
                            t_item = self._table_view.item(idx, 1)
                            if t_item:
                                t_item.setText(new_name)
                        finally:
                            self._is_updating_table = False
            self._has_unsaved_changes = True
            self._update_selection_visuals()
            if self._stack.currentIndex() == 1 and self._current_selected_idx in generated:
                self._lbl_full_title.setText(
                    f"Página {self._current_selected_idx + 1} de {len(self._items)} — {self._items[self._current_selected_idx].page_name}"
                )

    def _rename_page(self, index: int):
        """Abre un diálogo interactivo para cambiar el nombre de la página seleccionada."""
        if not (0 <= index < len(self._items)):
            return

        item = self._items[index]
        current_name = item.page_name

        new_name, ok = QInputDialog.getText(
            self,
            "Renombrar Página",
            f"Nuevo nombre para la Página {index + 1}:",
            text=current_name,
        )
        if not ok:
            return

        clean_name = new_name.strip()
        if not clean_name:
            clean_name = f"Página {index + 1}"

        if clean_name != current_name:
            self._push_undo_state()
            item.page_name = clean_name
            self._has_unsaved_changes = True
            if index < len(self._card_widgets):
                self._card_widgets[index].update_page_name(clean_name)
            if hasattr(self, "_table_view") and index < self._table_view.rowCount():
                self._is_updating_table = True
                try:
                    t_item = self._table_view.item(index, 1)
                    if t_item:
                        t_item.setText(clean_name)
                finally:
                    self._is_updating_table = False
            if self._stack.currentIndex() == 1 and self._current_selected_idx == index:
                self._lbl_full_title.setText(f"Página {index + 1} de {len(self._items)} — {clean_name}")

        # =========================================================================
    # GESTIÓN DE HISTORIAL EN MEMORIA (DESHACER / REHACER)
    # =========================================================================
    def _push_undo_state(self):
        """Guarda una instantánea ligera en memoria para revertir cambios sin tocar el archivo en disco."""
        state = {
            "items": [item.clone() for item in self._items],
            "selected": set(self._selected_indices),
            "current_selected": self._current_selected_idx,
            "has_unsaved_changes": self._has_unsaved_changes,
        }
        self._undo_history.append(state)
        if len(self._undo_history) > 50:
            self._undo_history.pop(0)
        self._redo_history.clear()
        self._update_undo_redo_ui()

    def undo(self):
        """Revierte la última modificación realizada en las páginas (Ctrl + Z)."""
        if not self._undo_history:
            return
        current_state = {
            "items": [item.clone() for item in self._items],
            "selected": set(self._selected_indices),
            "current_selected": self._current_selected_idx,
            "has_unsaved_changes": self._has_unsaved_changes,
        }
        self._redo_history.append(current_state)
        state = self._undo_history.pop()
        self._apply_history_state(state)
        self._update_undo_redo_ui()

    def redo(self):
        """Reaplica la modificación previamente revertida (Ctrl + Y)."""
        if not self._redo_history:
            return
        current_state = {
            "items": [item.clone() for item in self._items],
            "selected": set(self._selected_indices),
            "current_selected": self._current_selected_idx,
            "has_unsaved_changes": self._has_unsaved_changes,
        }
        self._undo_history.append(current_state)
        state = self._redo_history.pop()
        self._apply_history_state(state)
        self._update_undo_redo_ui()

    def _apply_history_state(self, state: dict):
        """Restaura el estado de páginas, selección y actualiza las vistas visuales."""
        self._items[:] = [item.clone() for item in state["items"]]
        self._selected_indices = set(state["selected"])
        self._current_selected_idx = state["current_selected"]
        self._has_unsaved_changes = state.get("has_unsaved_changes", True)
        self._page_cache.clear()
        self._rebuild_grid()
        if self._stack.currentIndex() == 1:
            if 0 <= self._current_selected_idx < len(self._items):
                self._open_full_view(self._current_selected_idx)
            else:
                self._back_to_grid()

    def _update_undo_redo_ui(self):
        """Sincroniza la disponibilidad de los botones de Deshacer y Rehacer."""
        can_undo = len(self._undo_history) > 0
        can_redo = len(self._redo_history) > 0
        if hasattr(self, "_btn_undo"):
            self._btn_undo.setEnabled(can_undo)
        if hasattr(self, "_btn_redo"):
            self._btn_redo.setEnabled(can_redo)
        if hasattr(self, "_btn_full_undo"):
            self._btn_full_undo.setEnabled(can_undo)
        if hasattr(self, "_btn_full_redo"):
            self._btn_full_redo.setEnabled(can_redo)

    def _duplicate_selected_pages(self):
        """Duplica las páginas actualmente seleccionadas insertándolas a continuación."""
        if not self._selected_indices:
            return

        self._push_undo_state()

        indices = sorted(self._selected_indices)
        insert_base = indices[-1] + 1
        new_selected = set()

        for offset, idx in enumerate(indices):
            source = self._items[idx]
            dup_item = PageItemData(
                original_index=None,
                page_name=f"{source.page_name} (Copia)",
                source_pdf=source.source_pdf,
                source_page_idx=source.source_page_idx,
            )
            if source.thumbnail:
                dup_item.thumbnail = source.thumbnail.copy()

            self._items.insert(insert_base + offset, dup_item)
            new_selected.add(insert_base + offset)

        self._has_unsaved_changes = True
        self._page_cache.clear()
        self._selected_indices = new_selected
        self._selection_anchor_idx = min(new_selected)
        self._current_selected_idx = self._selection_anchor_idx

        self._rebuild_grid()
        if self._stack.currentIndex() == 1:
            self._open_full_view(self._current_selected_idx)

    def _delete_selected_pages(self):
        """Elimina las páginas actualmente seleccionadas directamente en memoria (deshacer con Ctrl+Z)."""
        if not self._selected_indices:
            return

        indices = sorted(self._selected_indices)
        if len(self._items) - len(indices) < 1:
            QMessageBox.warning(
                self,
                "Acción no permitida",
                "El documento no puede quedar vacío. Debe contener al menos una página.",
            )
            return

        self._push_undo_state()

        for idx in sorted(indices, reverse=True):
            self._items.pop(idx)

        self._has_unsaved_changes = True
        self._page_cache.clear()

        new_target = min(indices[0], len(self._items) - 1)
        self._current_selected_idx = max(0, new_target)
        self._selected_indices = {self._current_selected_idx}
        self._selection_anchor_idx = self._current_selected_idx

        self._rebuild_grid()
        if self._stack.currentIndex() == 1:
            self._open_full_view(self._current_selected_idx)

    def _duplicate_page(self, index: int):
        """Duplica la página indicada insertándola inmediatamente después."""
        if not (0 <= index < len(self._items)):
            return

        self._push_undo_state()

        source = self._items[index]
        dup_item = PageItemData(
            original_index=None,
            page_name=f"{source.page_name} (Copia)",
            source_pdf=source.source_pdf,
            source_page_idx=source.source_page_idx,
        )
        if source.thumbnail:
            dup_item.thumbnail = source.thumbnail.copy()

        self._items.insert(index + 1, dup_item)
        self._current_selected_idx = index + 1
        self._has_unsaved_changes = True

        self._rebuild_grid()
        if self._stack.currentIndex() == 1:
            self._open_full_view(self._current_selected_idx)

    def _delete_page(self, index: int):
        """Elimina la página seleccionada directamente en memoria (deshacer con Ctrl+Z)."""
        if len(self._items) <= 1:
            QMessageBox.warning(
                self,
                "Acción no permitida",
                "El documento no puede quedar vacío. Debe contener al menos una página.",
            )
            return

        if not (0 <= index < len(self._items)):
            return

        self._push_undo_state()

        self._items.pop(index)
        self._has_unsaved_changes = True
        self._page_cache.clear()
        self._current_selected_idx = max(0, min(index, len(self._items) - 1))
        self._selected_indices = {self._current_selected_idx}
        self._selection_anchor_idx = self._current_selected_idx

        self._rebuild_grid()
        if self._stack.currentIndex() == 1:
            self._open_full_view(self._current_selected_idx)

    def _on_add_pages_from_pdf(self):
        """Agrega páginas desde archivos PDF externos."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar planos PDF para agregar páginas",
            "",
            "Archivos PDF (*.pdf)",
        )
        if not files:
            return

        self._push_undo_state()
        insert_pos = self._current_selected_idx + 1 if self._items else 0
        added_count = 0

        for file_path in files:
            try:
                names = extract_pdf_page_names(file_path)
                for page_idx, name in enumerate(names):
                    new_item = PageItemData(
                        original_index=None,
                        page_name=name,
                        source_pdf=file_path,
                        source_page_idx=page_idx,
                    )
                    self._items.insert(insert_pos + added_count, new_item)
                    added_count += 1
            except Exception as e:
                QMessageBox.warning(self, "Error al importar", f"No se pudo leer '{file_path}': {e}")

        if added_count > 0:
            self._has_unsaved_changes = True
            self._current_selected_idx = insert_pos
            self._rebuild_grid()
            self._start_thumbnail_worker()

    def _on_add_blank_page(self):
        """Inserta una página en blanco."""
        self._push_undo_state()
        insert_pos = self._current_selected_idx + 1 if self._items else 0
        blank_item = PageItemData(
            original_index=None,
            page_name="Página en Blanco",
            source_pdf=":blank:",
            source_page_idx=0,
        )
        self._items.insert(insert_pos, blank_item)
        self._has_unsaved_changes = True
        self._current_selected_idx = insert_pos
        self._rebuild_grid()
        self._start_thumbnail_worker()

    def _save_changes(self):
        """
        Ensambla el nuevo archivo PDF, lo guarda de forma atómica y sincroniza la base de datos:
        1. Detiene los hilos secundarios de miniaturas y cierra descriptores abiertos.
        2. Crea un documento nuevo con pypdfium2 bajo PDFIUM_LOCK e importa las páginas.
        3. Escribe a un archivo temporal, valida su integridad matemática y reemplaza atómicamente.
        4. Construye el mapa de correspondencia old_to_new_pages.
        5. Actualiza project.db (marcas reasignadas / eliminadas y nuevo conteo de páginas).
        6. Emite la señal 'pages_saved'.
        """
        if not self._items:
            return

        # Advertencia explícita: Guardar la reestructuración física de páginas no se puede deshacer con Ctrl+Z
        if self._has_unsaved_changes:
            warn_save_msg = (
                "¿Deseas guardar y aplicar los cambios en el archivo PDF?\n\n"
                "ADVERTENCIA DE IMPACTO IRREVERSIBLE:\n"
                "• El archivo PDF se reescribirá físicamente en el disco con la nueva estructura de páginas.\n"
                "• Las páginas eliminadas se perderán de forma permanente junto con sus mediciones asociadas.\n"
                "• Esta operación NO se puede deshacer con Ctrl+Z.\n\n"
                "¿Estás seguro de que deseas guardar y aplicar ahora?"
            )
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "Guardar Modificaciones de Páginas",
                warn_save_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                self,
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            if yes_btn:
                yes_btn.setText("Sí, guardar y aplicar")
            no_btn = box.button(QMessageBox.StandardButton.No)
            if no_btn:
                no_btn.setText("Seguir revisando")

            if box.exec() != QMessageBox.StandardButton.Yes:
                return

        # 1. Detener hilo secundario de miniaturas para evitar concurrencia en disco
        if self._thumb_thread is not None and self._thumb_thread.isRunning():
            self._thumb_thread.stop()

        # 2. Desconectar vigía de cambios externos, detener indexador y cerrar handle en MainWindow
        parent_win = self.parent()
        if parent_win is not None:
            if hasattr(parent_win, "pause_file_watcher"):
                parent_win.pause_file_watcher()
            if hasattr(parent_win, "_indexer"):
                parent_win._indexer.stop()
            if hasattr(parent_win, "_worker"):
                parent_win._worker.close_document(wait=True, timeout=2.0)

        target_path = Path(self._pdf_path).resolve()
        temp_path = target_path.with_name(f"{target_path.stem}_temp_save.pdf")
        cached_docs: dict[str, pdfium.PdfDocument] = {}

        try:
            with PDFIUM_LOCK:
                new_doc = pdfium.PdfDocument.new()
                try:
                    for item in self._items:
                        if item.source_pdf == ":blank:":
                            new_doc.new_page(792, 612)
                        else:
                            if item.source_pdf not in cached_docs:
                                cached_docs[item.source_pdf] = pdfium.PdfDocument(item.source_pdf)
                            src_d = cached_docs[item.source_pdf]
                            new_doc.import_pages(src_d, pages=[item.source_page_idx])

                    new_doc.save(str(temp_path))
                finally:
                    new_doc.close()
                    for d in cached_docs.values():
                        try:
                            d.close()
                        except Exception:
                            pass

                # Validación de integridad del archivo temporal antes del reemplazo
                if not temp_path.exists() or temp_path.stat().st_size == 0:
                    raise RuntimeError("El archivo PDF generado está vacío o incompleto.")

                _verify = pdfium.PdfDocument(str(temp_path))
                if len(_verify) != len(self._items):
                    _verify.close()
                    raise RuntimeError("La validación de páginas del archivo generado no coincide.")
                _verify.close()

            # Reemplazo atómico seguro en disco
            temp_path.replace(target_path)

            # Construir mapa de correspondencia de índices originales a nuevos
            old_to_new: dict[int, Optional[int]] = {}
            for orig_idx in range(self._original_total_pages):
                new_idx = None
                for curr_idx, itm in enumerate(self._items):
                    if itm.original_index == orig_idx:
                        new_idx = curr_idx
                        break
                old_to_new[orig_idx] = new_idx

            new_total = len(self._items)

            # Sincronizar en la base de datos SQLite si el plano pertenece al proyecto
            page_names = [itm.page_name for itm in self._items]
            if self._project_mgr and self._project_mgr.is_active:
                self._project_mgr.update_drawing_pages(
                    target_path, old_to_new, new_total, page_names=page_names
                )

            self._has_unsaved_changes = False
            self._original_total_pages = new_total

            # Notificar éxito y actualizar ventana principal
            self.pages_saved.emit(str(target_path), self._current_selected_idx)
            QMessageBox.information(
                self,
                "Cambios guardados",
                f"El archivo PDF ha sido actualizado exitosamente ({new_total} páginas) "
                "y sincronizado con la base de datos del proyecto.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar", f"No se pudo guardar el archivo PDF: {e}")
        finally:
            for d in cached_docs.values():
                try:
                    d.close()
                except Exception:
                    pass
            if parent_win is not None and hasattr(parent_win, "resume_file_watcher"):
                parent_win.resume_file_watcher()
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def eventFilter(self, watched, event):
        if hasattr(self, "_scroll_area") and watched == self._scroll_area.viewport():
            if event.type() == QEvent.Type.Resize:
                self._relayout_grid()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_grid()

    def keyPressEvent(self, event):
        # Deshacer: Ctrl+Z (sin Shift)
        if (
            event.matches(QKeySequence.StandardKey.Undo)
            or (
                event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
                and event.key() == Qt.Key.Key_Z
                and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
        ):
            self.undo()
            event.accept()
            return

        # Rehacer: Ctrl+Y o Ctrl+Shift+Z
        if (
            event.matches(QKeySequence.StandardKey.Redo)
            or (
                event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
                and (
                    event.key() == Qt.Key.Key_Y
                    or (event.key() == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                )
            )
        ):
            self.redo()
            event.accept()
            return

        if self._stack.currentIndex() == 0:
            # Ctrl+A o Cmd+A: Seleccionar todas las miniaturas
            if (
                event.matches(QKeySequence.StandardKey.SelectAll)
                or (
                    event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
                    and event.key() == Qt.Key.Key_A
                )
            ):
                self._selected_indices = set(range(len(self._items)))
                self._update_selection_visuals()
                event.accept()
                return

            # Tecla Supr o Retroceso: Eliminar páginas seleccionadas
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._delete_selected_pages()
                event.accept()
                return

        elif self._stack.currentIndex() == 1:
            if event.key() == Qt.Key.Key_Escape:
                self._back_to_grid()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Left:
                self._prev_full_page()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Right:
                self._next_full_page()
                event.accept()
                return
            elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self._delete_page(self._current_selected_idx)
                event.accept()
                return

        super().keyPressEvent(event)

    def reject(self):
        if self._thumb_thread is not None and self._thumb_thread.isRunning():
            self._thumb_thread.stop()
        if hasattr(self, "_full_worker") and self._full_worker is not None and self._full_worker.isRunning():
            self._full_worker.stop()
        super().reject()

    def closeEvent(self, event):
        if self._thumb_thread is not None and self._thumb_thread.isRunning():
            self._thumb_thread.stop()
        if hasattr(self, "_full_worker") and self._full_worker is not None and self._full_worker.isRunning():
            self._full_worker.stop()

        if self._has_unsaved_changes:
            warn_msg = (
                "Hay modificaciones en las páginas (eliminadas, orden o nombres) que no han sido guardadas.\n\n"
                "Si sales ahora, todos los cambios se descartarán y el archivo PDF original permanecerá intacto.\n\n"
                "¿Deseas descartar los cambios y salir?"
            )
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "Descartar Cambios",
                warn_msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                self,
            )
            box.setDefaultButton(QMessageBox.StandardButton.No)
            yes_btn = box.button(QMessageBox.StandardButton.Yes)
            if yes_btn:
                yes_btn.setText("Descartar y salir")
            no_btn = box.button(QMessageBox.StandardButton.No)
            if no_btn:
                no_btn.setText("Seguir editando")

            if box.exec() != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        event.accept()

    def _apply_theme(self):
        """
        Reaplica el tema a la ventana (Methods Down).

        Todo el estilo del gestor vive en ``common/styles/theme.qss``; aquí solo se
        propaga el cambio de tema a las vistas que cachean color de lienzo.
        """
        if hasattr(self, "_full_viewer"):
            self._full_viewer.update_canvas_theme()
