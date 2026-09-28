"""
Vista del auto-nombrado de planos (``AutoNamerDialog``).

Diálogo modal de interfaz para seleccionar zonas de cajetín, previsualizar en vivo
los nombres calculados, comprobar homogeneidad de dimensiones y aplicar renombrado.

Solo compone widgets y dibuja: el estado y la lógica viven en
:class:`~ui.views.auto_namer.controller.AutoNamerController`.
"""

import logging
from typing import List, Dict

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from common.styles.style_manager import ThemeManager
from common.widgets.title_bar import CustomTitleBar
from common.widgets.window_resizer import WindowResizeFilter
from common.pdf.pdf_renderer import calculate_optimal_scale
from core.text_geometry import Rect
from core.text_layer import PageTextData
from core.settings import settings
from common.pdf.page_cache import SlidingPageCache
from common.pdf.disk_cache import DiskPageCache
from core.pdf_lock import PDFIUM_LOCK

from .canvas import RegionData, RegionCanvasView, REGION_COLORS, DEBUG_HIGHLIGHT_CHARS
from .controller import AutoNamerController
from .widgets import AlertBanner, SeparatorRow, ZoneCard
from .text_extractor import (
    extract_text_from_norm_rect_static,
    clean_boilerplate,
    BOILERPLATE_PATTERNS,
)

logger = logging.getLogger("quotom")


class AutoNamerDialog(QDialog):
    """
    Diálogo modal de auto-nombrado por zonas de cajetín.

    Es la **vista**: compone los widgets, dibuja el plano y muestra resultados. El
    estado y la lógica (extracción, cachés, lote) viven en
    :class:`~ui.views.auto_namer.controller.AutoNamerController`.
    """

    BOILERPLATE_PATTERNS = BOILERPLATE_PATTERNS
    clean_boilerplate = staticmethod(clean_boilerplate)
    extract_text_from_norm_rect_static = staticmethod(extract_text_from_norm_rect_static)

    def __init__(
        self,
        items: list,
        selected_indices: List[int],
        pdf_path: str,
        parent=None,
        page_cache: Optional[SlidingPageCache] = None,
        disk_cache: Optional[DiskPageCache] = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._sync_with_parent: bool = True
        self._syncing_move: bool = False
        self._already_centered: bool = False

        self._items = items
        self._selected_indices = selected_indices
        self._pdf_path = pdf_path
        self._page_cache = page_cache
        self._disk_cache = disk_cache
        self._controller = AutoNamerController(
            items=items,
            selected_indices=selected_indices,
            pdf_path=pdf_path,
            page_cache=page_cache,
            disk_cache=disk_cache,
            parent=self,
        )

        self._preview_debounce_timer = QTimer(self)
        self._preview_debounce_timer.setSingleShot(True)
        self._preview_debounce_timer.setInterval(250)
        self._preview_debounce_timer.timeout.connect(self._start_preview_worker)

        self._regions: List[RegionData] = [
            RegionData(1, REGION_COLORS[0], "Zona 1 (Número)"),
            RegionData(2, REGION_COLORS[1], "Zona 2 (Título)"),
        ]
        self._separators: List[SeparatorRow] = []

        self.setObjectName("autoNamerDialog")
        self.resize(1220, 800)
        self.setMinimumSize(920, 620)

        self._resizer = WindowResizeFilter(self)
        self.installEventFilter(self._resizer)

        self._init_ui()
        self._connect_controller()
        self._check_dimensions()
        self._load_sample_page(self._selected_indices[0] if self._selected_indices else 0)
        self._start_preview_worker()

    def _connect_controller(self):
        """Conecta las señales del controlador con las actualizaciones de la tabla."""
        self._controller.row_computed.connect(self._on_worker_row_computed)
        self._controller.progress.connect(self._on_worker_progress)
        self._controller.finished_all.connect(self._on_worker_finished)

    def closeEvent(self, event):
        self._controller.close()
        super().closeEvent(event)

    def reject(self):
        self._controller.close()
        super().reject()

    def get_generated_names(self) -> Dict[int, str]:
        """Retorna el mapeo de índice de página a nuevo nombre generado."""
        return self._controller.generated_names

    def _init_ui(self):
        """Compone el diálogo: marco, lienzo del plano y panel de herramientas."""
        self._build_frame()
        self._build_canvas_panel()
        self._build_tools_panel()
        self._apply_theme()
        self._load_cached_template()

    def _build_frame(self):
        """Marco principal: barra de título propia, banda de aviso y divisor."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._main_container = QFrame(self)
        self._main_container.setObjectName("autoNamerMainFrame")
        container_layout = QVBoxLayout(self._main_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self._title_bar = CustomTitleBar(self, title="Auto-Nombrar Páginas por Región de Cajetín")
        container_layout.addWidget(self._title_bar)

        self._alert_banner = AlertBanner(self._main_container)
        container_layout.addWidget(self._alert_banner)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self._main_container)
        self._splitter.setObjectName("autoNamerSplitter")
        container_layout.addWidget(self._splitter, 1)

        root_layout.addWidget(self._main_container)

    def _build_canvas_panel(self):
        """Panel izquierdo: selector de página de muestra, controles de zoom y lienzo."""
        splitter = self._splitter
        left_widget = QWidget(splitter)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        canvas_bar = QFrame(left_widget)
        canvas_bar.setObjectName("autoNamerCanvasBar")
        canvas_bar.setFixedHeight(40)
        cb_layout = QHBoxLayout(canvas_bar)
        cb_layout.setContentsMargins(12, 4, 12, 4)
        cb_layout.setSpacing(8)

        cb_layout.addWidget(QLabel("Página de muestra:", canvas_bar))
        self._combo_sample = QComboBox(canvas_bar)
        self._combo_sample.setMinimumWidth(220)
        for idx in self._selected_indices:
            item = self._items[idx]
            self._combo_sample.addItem(f"Pág. {idx + 1} — {item.page_name}", idx)
        self._combo_sample.currentIndexChanged.connect(self._on_sample_page_changed)
        cb_layout.addWidget(self._combo_sample)

        cb_layout.addStretch()

        self._btn_zoom_out = QPushButton(canvas_bar)
        self._btn_zoom_out.setFixedSize(28, 28)
        self._btn_zoom_out.setIcon(ThemeManager.get_icon("zoom-out"))
        self._btn_zoom_out.setToolTip("Reducir zoom")
        self._btn_zoom_out.clicked.connect(lambda: self._canvas.zoom_out())
        cb_layout.addWidget(self._btn_zoom_out)

        self._btn_fit = QPushButton(canvas_bar)
        self._btn_fit.setFixedSize(28, 28)
        self._btn_fit.setIcon(ThemeManager.get_icon("fit-window"))
        self._btn_fit.setToolTip("Ajustar a ventana")
        self._btn_fit.clicked.connect(lambda: self._canvas.fit_in_view())
        cb_layout.addWidget(self._btn_fit)

        self._btn_zoom_in = QPushButton(canvas_bar)
        self._btn_zoom_in.setFixedSize(28, 28)
        self._btn_zoom_in.setIcon(ThemeManager.get_icon("zoom-in"))
        self._btn_zoom_in.setToolTip("Aumentar zoom")
        self._btn_zoom_in.clicked.connect(lambda: self._canvas.zoom_in())
        cb_layout.addWidget(self._btn_zoom_in)

        left_layout.addWidget(canvas_bar)

        self._canvas = RegionCanvasView(left_widget)
        self._canvas.region_drawn.connect(self._on_region_drawn)
        self._canvas.set_regions(self._regions)
        left_layout.addWidget(self._canvas, 1)

        lbl_hint = QLabel("Arrastra con clic izquierdo para dibujar el recuadro de captura. Paneo con botón central/derecho o rueda de scroll.", left_widget)
        lbl_hint.setObjectName("autoNamerHintLabel")
        left_layout.addWidget(lbl_hint)

        splitter.addWidget(left_widget)

    def _build_tools_panel(self):
        """Panel derecho: zonas, separadores, nombre en vivo, tabla en lote y acciones."""
        splitter = self._splitter
        right_widget = QWidget(splitter)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(16, 12, 16, 12)
        right_layout.setSpacing(10)

        lbl_sec_title = QLabel("Estructura del Nombre", right_widget)
        lbl_sec_title.setObjectName("autoNamerSectionTitle")
        right_layout.addWidget(lbl_sec_title)

        self._seq_container = QWidget(right_widget)
        self._seq_layout = QVBoxLayout(self._seq_container)
        self._seq_layout.setContentsMargins(0, 0, 0, 0)
        self._seq_layout.setSpacing(8)
        right_layout.addWidget(self._seq_container)

        self._rebuild_sequence_widgets()

        self._btn_add_region = QPushButton("+ Agregar otra zona de captura", right_widget)
        self._btn_add_region.setIcon(ThemeManager.get_icon("plus"))
        self._btn_add_region.clicked.connect(self._add_region)
        right_layout.addWidget(self._btn_add_region)

        preview_box = QFrame(right_widget)
        preview_box.setObjectName("autoNamerPreviewCard")
        pb_layout = QVBoxLayout(preview_box)
        pb_layout.setContentsMargins(12, 10, 12, 10)
        pb_layout.setSpacing(4)

        lbl_pv_title = QLabel("Nombre resultante (Página de muestra):", preview_box)
        lbl_pv_title.setObjectName("autoNamerPreviewTitle")
        pb_layout.addWidget(lbl_pv_title)

        self._lbl_live_name = QLabel("(Dibuja las zonas sobre el plano para generar el nombre)", preview_box)
        self._lbl_live_name.setObjectName("autoNamerLiveName")
        self._lbl_live_name.setWordWrap(True)
        pb_layout.addWidget(self._lbl_live_name)

        right_layout.addWidget(preview_box)

        tbl_hdr_layout = QHBoxLayout()
        tbl_hdr_layout.setContentsMargins(0, 0, 0, 0)
        lbl_tbl_title = QLabel(f"Previsualización en lote ({len(self._selected_indices)} páginas):", right_widget)
        lbl_tbl_title.setObjectName("autoNamerTableTitle")
        tbl_hdr_layout.addWidget(lbl_tbl_title)
        tbl_hdr_layout.addStretch()

        self._progress_bar_preview = QProgressBar(right_widget)
        self._progress_bar_preview.setObjectName("autoNamerProgressBar")
        self._progress_bar_preview.setFixedHeight(14)
        self._progress_bar_preview.setFixedWidth(120)
        self._progress_bar_preview.setTextVisible(False)
        self._progress_bar_preview.setVisible(False)
        tbl_hdr_layout.addWidget(self._progress_bar_preview)

        self._lbl_preview_progress = QLabel("", right_widget)
        self._lbl_preview_progress.setObjectName("autoNamerProgressLabel")
        tbl_hdr_layout.addWidget(self._lbl_preview_progress)
        right_layout.addLayout(tbl_hdr_layout)

        self._table_preview = QTableWidget(right_widget)
        self._table_preview.setColumnCount(3)
        self._table_preview.setHorizontalHeaderLabels(["Pág.", "Nombre Actual", "Nuevo Nombre"])
        self._table_preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table_preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._table_preview.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table_preview.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table_preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table_preview.setObjectName("autoNamerPreviewTable")
        right_layout.addWidget(self._table_preview, 1)

        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(0, 8, 0, 0)
        btn_bar.setSpacing(8)

        self._btn_cancel = QPushButton("Cancelar", right_widget)
        self._btn_cancel.setFixedSize(100, 32)
        self._btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self._btn_cancel)

        btn_bar.addStretch()

        self._btn_apply = QPushButton(f"Aplicar a las {len(self._selected_indices)} páginas", right_widget)
        self._btn_apply.setObjectName("primaryActionButton")
        self._btn_apply.setIcon(ThemeManager.get_icon("save"))
        self._btn_apply.setFixedHeight(32)
        self._btn_apply.clicked.connect(self._apply_to_pages)
        btn_bar.addWidget(self._btn_apply)

        right_layout.addLayout(btn_bar)

        splitter.addWidget(right_widget)
        # Proporción 2/3 (67%) para el plano y 1/3 (33%) para el panel de herramientas
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([800, 400])

    def _load_cached_template(self):
        """Restaura la plantilla de regiones previamente guardada en la caché de este documento."""
        tpl = self._controller.load_template()
        if not tpl:
            return

        saved_regs = tpl.get("regions", [])
        if saved_regs:
            new_regs = []
            for sreg in saved_regs:
                r = RegionData(sreg["region_id"], sreg["color_hex"], sreg["label"])
                nr = sreg.get("norm_rect")
                if nr and len(nr) == 4:
                    r.norm_rect = QRectF(nr[0], nr[1], nr[2], nr[3])
                new_regs.append(r)
            if new_regs:
                self._regions = new_regs
                self._rebuild_sequence_widgets()
                self._canvas.set_regions(self._regions)

        saved_seps = tpl.get("separators", [])
        for idx, text in enumerate(saved_seps):
            if idx < len(self._separators):
                self._separators[idx].set_text(text)

    def _save_cached_template(self):
        """Persiste la plantilla de zonas y separadores en la caché del documento."""
        self._controller.save_template(
            self._regions, [sep.text() for sep in self._separators]
        )

    def showEvent(self, event):
        super().showEvent(event)
        # Proporción exacta: 2/3 (66.7%) para el plano y 1/3 (33.3%) para el panel de herramientas
        if hasattr(self, "_splitter"):
            total_w = max(600, self.width())
            left_w = int(total_w * (2.0 / 3.0))
            right_w = total_w - left_w
            self._splitter.setSizes([left_w, right_w])
        QTimer.singleShot(0, self._canvas.fit_in_view)

    def _check_dimensions(self):
        """
        Avisa si las páginas seleccionadas tienen tamaños distintos.

        El cálculo vive en el controlador; aquí solo se muestra el aviso. Un
        cajetín no cae en el mismo sitio en planos de formatos distintos, así que
        la plantilla de zonas deja de ser fiable.
        """
        warning = self._controller.dimension_warning()
        if warning:
            self._alert_banner.show_message(warning)

    def _rebuild_sequence_widgets(self):
        """Reconstruye la lista de zonas de captura y sus separadores intermedios.

        Los separadores se añaden como **widgets** (``SeparatorRow``) y no como
        layouts: al reconstruir, un layout no tiene ``widget()`` y sus hijos
        quedaban sin liberar (fuga en cada recuadro dibujado).
        """
        while self._seq_layout.count() > 0:
            item = self._seq_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._separators.clear()
        saved_seps = settings.get("auto_namer.last_separators", [" - "])
        removable = len(self._regions) > 1
        active_id = self._canvas.active_capture_id()

        for idx, reg in enumerate(self._regions):
            card = ZoneCard(
                region=reg,
                index=idx,
                removable=removable,
                active=(active_id == reg.region_id),
                parent=self._seq_container,
            )
            card.capture_requested.connect(self._set_active_region_capture)
            card.remove_requested.connect(self._remove_region)
            self._seq_layout.addWidget(card)

            if idx < len(self._regions) - 1:
                init_val = saved_seps[idx] if idx < len(saved_seps) else " - "
                separator = SeparatorRow(init_val, self._seq_container)
                separator.edited.connect(self._on_separator_changed)
                self._separators.append(separator)
                self._seq_layout.addWidget(separator)

    def _on_separator_changed(self):
        """Maneja cambios en separadores de texto: actualiza muestra de inmediato y debouncea la tabla."""
        self._update_sample_preview()
        self._preview_debounce_timer.start(250)
        # Guardar separadores en ajustes persistentes
        seps = [s.text() for s in self._separators]
        settings.set("auto_namer.last_separators", seps)

    def _add_region(self):
        new_id = max([r.region_id for r in self._regions], default=0) + 1
        color_idx = (new_id - 1) % len(REGION_COLORS)
        new_reg = RegionData(new_id, REGION_COLORS[color_idx], f"Zona {len(self._regions) + 1}")
        self._regions.append(new_reg)
        self._canvas.set_regions(self._regions)
        self._set_active_region_capture(new_id)

    def _remove_region(self, region_id: int):
        self._regions = [r for r in self._regions if r.region_id != region_id]
        if self._regions:
            self._set_active_region_capture(self._regions[0].region_id)
        else:
            self._set_active_region_capture(None)
        self._canvas.set_regions(self._regions)
        self._rebuild_sequence_widgets()
        self._update_debug_highlights()
        self._update_sample_preview()
        self._preview_debounce_timer.start(250)

    def _set_active_region_capture(self, region_id: Optional[int]):
        self._canvas.set_active_capture_id(region_id)
        self._rebuild_sequence_widgets()

    def _on_region_drawn(self, region_id: int, norm_rect: QRectF):
        sample_item_idx = self._combo_sample.currentData()
        for reg in self._regions:
            if reg.region_id == region_id:
                reg.norm_rect = norm_rect
                self._controller.invalidate_region_cache(region_id)
                if sample_item_idx is not None:
                    reg.sample_text = self._controller.text_for_region(sample_item_idx, reg)
                break

        self._canvas.set_regions(self._regions)
        self._rebuild_sequence_widgets()
        self._update_debug_highlights()
        self._update_sample_preview()
        self._preview_debounce_timer.start(250)

        for reg in self._regions:
            if reg.norm_rect is None:
                self._set_active_region_capture(reg.region_id)
                return

    def _load_sample_page(self, item_index: int):
        """Carga el renderizado de la página indicada en el lienzo interactivo."""
        if not (0 <= item_index < len(self._items)):
            return

        item = self._items[item_index]

        if item.source_pdf == ":blank:":
            blank_pix = QPixmap(1600, 1100)
            blank_pix.fill(Qt.GlobalColor.white)
            self._canvas.set_page_pixmap(blank_pix)
            return

        if self._page_cache:
            cached = self._page_cache.get(item_index)
            if cached:
                self._canvas.set_page_pixmap(cached.pixmap)
                return

        if (
            self._disk_cache
            and item.source_pdf == self._pdf_path
            and self._disk_cache.doc_dir
            and self._disk_cache.has_page(item.source_page_idx)
        ):
            cached_disk = self._disk_cache.load_page(item.source_page_idx)
            if cached_disk is not None:
                qimg, scale, dims = cached_disk
                pix = QPixmap.fromImage(qimg)
                self._canvas.set_page_pixmap(pix)
                if self._page_cache:
                    self._page_cache.put(item_index, pix, scale, dims)
                return

        try:
            with PDFIUM_LOCK:
                doc = self._controller.document_for(item.source_pdf)
                if doc is not None:
                    page = doc[item.source_page_idx]
                    w_pts, h_pts = page.get_size()
                    dims = (float(w_pts), float(h_pts))
                    scale = calculate_optimal_scale(w_pts, h_pts)

                    bm = page.render(scale=scale)
                    try:
                        w, h, stride = bm.width, bm.height, bm.stride
                        qimg = QImage(bytes(bm.buffer), w, h, stride, QImage.Format.Format_BGR888).copy()
                        pix = QPixmap.fromImage(qimg)
                        self._canvas.set_page_pixmap(pix)
                        if self._disk_cache and item.source_pdf == self._pdf_path:
                            self._disk_cache.save_page(item.source_page_idx, qimg, scale, dims)
                        if self._page_cache:
                            self._page_cache.put(item_index, pix, scale, dims)
                    finally:
                        bm.close()
        except Exception as exc:
            # No se silencia: ocultar el fallo fue justo lo que mantuvo invisible
            # durante toda la vida del diálogo que la página salía en blanco.
            logger.warning(
                "Auto-nombrador: no se pudo renderizar la página %s: %s",
                item.source_page_idx,
                exc,
            )
            err_pix = QPixmap(800, 600)
            err_pix.fill(Qt.GlobalColor.white)
            self._canvas.set_page_pixmap(err_pix)

    def _on_sample_page_changed(self, combo_idx: int):
        item_idx = self._combo_sample.currentData()
        if item_idx is not None:
            self._load_sample_page(item_idx)
            for reg in self._regions:
                if reg.norm_rect is not None:
                    reg.sample_text = self._controller.text_for_region(item_idx, reg)
            self._rebuild_sequence_widgets()
            self._update_debug_highlights()
            self._update_sample_preview()

    def _update_debug_highlights(self):
        """Actualiza el resaltado fosforescente de los caracteres capturados (vectoriales u OCR)."""
        if not DEBUG_HIGHLIGHT_CHARS or not hasattr(self, "_canvas"):
            return

        sample_item_idx = self._combo_sample.currentData()
        if sample_item_idx is None or not self._canvas._page_pixmap:
            self._canvas.clear_debug_highlights()
            return

        pw = float(self._canvas._page_pixmap.width())
        ph = float(self._canvas._page_pixmap.height())

        text_data = self._controller.text_data_for_page(sample_item_idx)
        w_px = round(text_data.width_pts * text_data.scale) if text_data else 0
        h_px = round(text_data.height_pts * text_data.scale) if text_data else 0
        sx = pw / w_px if w_px > 0 else 1.0
        sy = ph / h_px if h_px > 0 else 1.0

        all_matched: List[QRectF] = []
        for reg in self._regions:
            if reg.norm_rect is None:
                continue

            found_vector = False
            if text_data and text_data.char_boxes and w_px > 0:
                target = Rect(
                    reg.norm_rect.x() * w_px,
                    reg.norm_rect.y() * h_px,
                    reg.norm_rect.width() * w_px,
                    reg.norm_rect.height() * h_px,
                )
                for cb in text_data.char_boxes:
                    if target.contains(cb.rect.center()) and cb.char.strip() and cb.char.isprintable():
                        all_matched.append(
                            QRectF(cb.rect.x() * sx, cb.rect.y() * sy, cb.rect.width() * sx, cb.rect.height() * sy)
                        )
                        found_vector = True

            if not found_vector:
                for obox in self._controller.ocr_boxes_for_region(sample_item_idx, reg.region_id):
                    all_matched.append(
                        QRectF(obox.x() * pw, obox.y() * ph, obox.width() * pw, obox.height() * ph)
                    )

        self._canvas.show_debug_highlights(all_matched, 1.0, 1.0)

    def _assemble_name_for_page(self, item_idx: int) -> str:
        """
        Compone el nombre de una página según las regiones y separadores configurados.

        La vista solo aporta las zonas y los separadores (estado editable por el
        usuario); la regla de composición y la extracción viven en el controlador.
        """
        return self._controller.assemble_name_for_page(
            item_idx, self._regions, [sep.text() for sep in self._separators]
        )

    def _update_sample_preview(self):
        """Actualiza instantáneamente el nombre de muestra en la tarjeta del panel derecho."""
        sample_item_idx = self._combo_sample.currentData()
        if sample_item_idx is not None:
            sample_name = self._assemble_name_for_page(sample_item_idx)
            if sample_name:
                self._lbl_live_name.setText(sample_name)
            else:
                self._lbl_live_name.setText("(Texto no detectado en el recuadro seleccionado)")

    def _start_preview_worker(self):
        """Refresca la tabla y lanza el cálculo en lote en segundo plano."""
        self._controller.cancel_preview()

        self._table_preview.setRowCount(len(self._selected_indices))
        has_any_region = any(r.norm_rect is not None for r in self._regions)
        generated = self._controller.generated_names

        for row, idx in enumerate(self._selected_indices):
            item = self._items[idx]
            item_num = QTableWidgetItem(f"Pág. {idx + 1}")
            item_num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table_preview.setItem(row, 0, item_num)

            item_old = QTableWidgetItem(item.page_name)
            self._table_preview.setItem(row, 1, item_old)

            item_new = QTableWidgetItem()
            if not has_any_region:
                item_new.setText(item.page_name)
                item_new.setForeground(QBrush(QColor("#888888")))
            elif idx in generated and generated[idx] != item.page_name:
                item_new.setText(generated[idx])
                item_new.setForeground(QBrush(QColor("#2563EB")))
                item_new.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
            else:
                item_new.setText("Calculando...")
                item_new.setForeground(QBrush(QColor("#A0AEC0")))
                item_new.setFont(QFont("sans-serif", 10, QFont.Weight.Normal))
            self._table_preview.setItem(row, 2, item_new)

        if not has_any_region:
            self._lbl_preview_progress.setText("Esperando definición de zonas...")
            return

        self._progress_bar_preview.setRange(0, len(self._selected_indices))
        self._progress_bar_preview.setValue(0)
        self._progress_bar_preview.setVisible(True)
        self._lbl_preview_progress.setText(f"Generando previsualización (0 / {len(self._selected_indices)})...")

        self._controller.start_preview(
            self._regions, [sep.text() for sep in self._separators]
        )

    def _on_worker_row_computed(self, row: int, idx: int, final_name: str, has_text: bool):
        item_new = QTableWidgetItem()
        if has_text:
            item_new.setText(final_name)
            item_new.setForeground(QBrush(QColor("#2563EB")))
            item_new.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
        else:
            item_new.setText(f"{final_name} (Sin texto detectado)")
            item_new.setForeground(QBrush(QColor("#888888")))
            item_new.setFont(QFont("sans-serif", 10, QFont.Weight.Normal))
        self._table_preview.setItem(row, 2, item_new)

    def _on_worker_progress(self, current: int, total: int):
        self._progress_bar_preview.setValue(current)
        self._lbl_preview_progress.setText(f"Generando ({current} / {total})...")

    def _on_worker_finished(self):
        self._progress_bar_preview.setVisible(False)
        self._lbl_preview_progress.setText(f"✓ {len(self._selected_indices)} páginas procesadas")

    def _update_live_preview(self):
        """Compatibilidad: actualiza muestra y dispara trabajador en lote."""
        self._update_sample_preview()
        self._start_preview_worker()

    def _apply_to_pages(self):
        """Valida y confirma la aplicación de los nombres a las páginas seleccionadas."""
        if not any(r.norm_rect is not None for r in self._regions):
            QMessageBox.warning(
                self,
                "Sin regiones definidas",
                "Por favor dibuja al menos una zona sobre el plano antes de aplicar los nombres.",
            )
            return

        missing_indices = self._controller.missing_page_indices()
        if missing_indices:
            self._controller.cancel_preview()

            progress = QProgressDialog(
                "Finalizando la extracción en paralelo de nombres de planos...",
                "Cancelar",
                0,
                len(self._selected_indices),
                self,
            )
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(len(self._controller.generated_names))

            for idx in missing_indices:
                if progress.wasCanceled():
                    # Si el usuario cancela la ventana modal, actualizar la tabla con lo que se haya
                    # calculado y reanudar el preview worker en segundo plano para que la barra de progreso
                    # y la lista de la derecha sigan vivas y avanzando:
                    self._start_preview_worker()
                    return
                final_name = self._assemble_name_for_page(idx)
                self._controller.remember_generated_name(idx, final_name)
                # Actualizar celda de la tabla para este índice si está visible
                if idx in self._selected_indices:
                    r_idx = self._selected_indices.index(idx)
                    item_new = QTableWidgetItem(final_name)
                    item_new.setForeground(QBrush(QColor("#2563EB")))
                    item_new.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
                    self._table_preview.setItem(r_idx, 2, item_new)
                progress.setValue(len(self._controller.generated_names))

        self._save_cached_template()
        self._controller.close()
        self.accept()

    def _apply_theme(self):
        """
        Reaplica el tema al diálogo (Methods Down).

        Todo su estilo vive en ``common/styles/theme.qss``; aquí solo se refresca el
        icono del banner de aviso, que es un *pixmap* dependiente del tema.
        """
        self._alert_banner.refresh_icon()
