"""
Ventana Principal de Auto-Nombrado de Planos (AutoNamerDialog).

Diálogo modal de interfaz para seleccionar zonas de cajetín, previsualizar en vivo
los nombres calculados, comprobar homogeneidad de dimensiones y aplicar renombrado.
"""

import os
from typing import List, Dict, Tuple, Optional
import pypdfium2 as pdfium

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal, QSize, QTimer
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QColor,
    QBrush,
    QFont,
)
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QScrollArea,
    QFrame,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QSplitter,
    QProgressDialog,
    QProgressBar,
)

from ui.styles.style_manager import ThemeManager
from common.widgets.title_bar import CustomTitleBar
from common.widgets.window_resizer import WindowResizeFilter
from common.pdf.pdf_renderer import calculate_optimal_scale
from core.text_geometry import Rect
from core.text_layer import PageTextData
from core.settings import settings
from common.pdf.page_cache import SlidingPageCache
from common.pdf.disk_cache import DiskPageCache
from core.pdf_lock import PDFIUM_LOCK
from core.ocr_engine import recognize_pdf_region

from .canvas import RegionData, RegionCanvasView, REGION_COLORS, DEBUG_HIGHLIGHT_CHARS
from .worker import AutoNamerPreviewWorker
from .text_extractor import (
    extract_bounded_text_fast,
    extract_text_from_norm_rect_static,
    clean_boilerplate,
    BOILERPLATE_PATTERNS,
)




class AutoNamerDialog(QDialog):
    """Diálogo modal desacoplado para extraer texto y asignar nombres por región."""

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
        self._generated_names: Dict[int, str] = {}
        self._cached_text_pages: Dict[int, PageTextData] = {}
        self._cached_ocr_results: Dict[Tuple[int, int], Tuple[str, List[QRectF]]] = {}
        self._cached_region_text: Dict[Tuple[int, int, float, float, float, float], str] = {}
        self._open_docs: Dict[str, pdfium.PdfDocument] = {}
        self._preview_worker: Optional[AutoNamerPreviewWorker] = None

        self._preview_debounce_timer = QTimer(self)
        self._preview_debounce_timer.setSingleShot(True)
        self._preview_debounce_timer.setInterval(250)
        self._preview_debounce_timer.timeout.connect(self._start_preview_worker)

        self._regions: List[RegionData] = [
            RegionData(1, REGION_COLORS[0], "Zona 1 (Número)"),
            RegionData(2, REGION_COLORS[1], "Zona 2 (Título)"),
        ]
        self._separators: List[QLineEdit] = []

        self.setObjectName("autoNamerDialog")
        self.resize(1220, 800)
        self.setMinimumSize(920, 620)

        self._resizer = WindowResizeFilter(self)
        self.installEventFilter(self._resizer)

        self._init_ui()
        self._check_dimensions()
        self._load_sample_page(self._selected_indices[0] if self._selected_indices else 0)
        self._start_preview_worker()

    def _get_doc(self, pdf_path: str) -> Optional[pdfium.PdfDocument]:
        """Reutiliza documentos PDFium abiertos durante el ciclo de vida del diálogo."""
        if pdf_path not in self._open_docs:
            if pdf_path == ":blank:" or not Path(pdf_path).exists():
                return None
            try:
                with PDFIUM_LOCK:
                    self._open_docs[pdf_path] = pdfium.PdfDocument(pdf_path)
            except Exception:
                return None
        return self._open_docs[pdf_path]

    def _close_docs(self):
        with PDFIUM_LOCK:
            for d in self._open_docs.values():
                try:
                    d.close()
                except Exception:
                    pass
            self._open_docs.clear()

    def closeEvent(self, event):
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.wait()
        self._close_docs()
        super().closeEvent(event)

    def reject(self):
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.wait()
        self._close_docs()
        super().reject()

    def get_generated_names(self) -> Dict[int, str]:
        """Retorna el mapeo de índice de página a nuevo nombre generado."""
        return self._generated_names

    def _init_ui(self):
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

        self._alert_banner = QFrame(self._main_container)
        self._alert_banner.setObjectName("autoNamerAlertBanner")
        self._alert_banner.setVisible(False)
        alert_layout = QHBoxLayout(self._alert_banner)
        alert_layout.setContentsMargins(16, 8, 16, 8)
        alert_layout.setSpacing(8)

        self._lbl_alert_icon = QLabel(self._alert_banner)
        self._lbl_alert_icon.setObjectName("autoNamerAlertIcon")
        self._lbl_alert_icon.setFixedSize(16, 16)
        alert_layout.addWidget(self._lbl_alert_icon, 0, Qt.AlignmentFlag.AlignTop)

        self._lbl_alert_msg = QLabel(self._alert_banner)
        self._lbl_alert_msg.setObjectName("autoNamerAlertMsg")
        self._lbl_alert_msg.setWordWrap(True)
        alert_layout.addWidget(self._lbl_alert_msg, 1)
        container_layout.addWidget(self._alert_banner)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self._main_container)
        splitter = self._splitter
        splitter.setObjectName("autoNamerSplitter")

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

        container_layout.addWidget(splitter, 1)
        root_layout.addWidget(self._main_container)

        self._apply_theme()
        self._load_cached_template()

    def _load_cached_template(self):
        """Restaura la plantilla de regiones previamente guardada en la caché de este documento."""
        if not self._disk_cache:
            return
        tpl = self._disk_cache.get_auto_namer_template()
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
                self._separators[idx].setText(text)

    def _save_cached_template(self):
        """Persiste la plantilla de regiones en la caché de disco del documento."""
        if not self._disk_cache:
            return
        template = {
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
                    ] if r.norm_rect else None,
                }
                for r in self._regions
            ],
            "separators": [sep.text() for sep in self._separators],
        }
        self._disk_cache.save_auto_namer_template(template)

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
        """Verifica si las páginas seleccionadas tienen el mismo tamaño o avisa al usuario."""
        if self._disk_cache and hasattr(self._disk_cache, "_metadata"):
            pages_meta = self._disk_cache._metadata.get("pages", {})
            dims_set = set()
            for idx in self._selected_indices:
                p_meta = pages_meta.get(str(idx))
                if p_meta and "dims_pts" in p_meta:
                    dims_set.add((round(p_meta["dims_pts"][0], 0), round(p_meta["dims_pts"][1], 0)))
            if len(dims_set) > 1:
                self._alert_banner.setVisible(True)
                self._lbl_alert_msg.setText(
                    "Advertencia de dimensiones: Las páginas seleccionadas tienen diferentes tamaños. "
                    "La ubicación del cajetín podría variar entre planos con formatos distintos."
                )
            return

        sample_indices = self._selected_indices
        if len(self._selected_indices) > 6:
            sample_indices = [
                self._selected_indices[0],
                self._selected_indices[len(self._selected_indices) // 4],
                self._selected_indices[len(self._selected_indices) // 2],
                self._selected_indices[3 * len(self._selected_indices) // 4],
                self._selected_indices[-1],
            ]

        dimension_groups: Dict[Tuple[float, float], List[int]] = {}
        try:
            with PDFIUM_LOCK:
                for idx in sample_indices:
                    if idx >= len(self._items):
                        continue
                    item = self._items[idx]
                    if item.source_pdf == ":blank:":
                        dims = (1600.0, 1100.0)
                    else:
                        doc = self._get_doc(item.source_pdf)
                        if doc and item.source_page_idx < len(doc):
                            page = doc[item.source_page_idx]
                            w, h = page.get_size()
                            dims = (round(w, 0), round(h, 0))
                        else:
                            dims = (0.0, 0.0)
                    dimension_groups.setdefault(dims, []).append(idx)
        except Exception:
            pass

        if len(dimension_groups) > 1:
            desc_parts = []
            for (w, h), pages in dimension_groups.items():
                desc_parts.append(f"{len(pages)} páginas de {int(w)}×{int(h)} pts")
            details = ", ".join(desc_parts)

            self._alert_banner.setVisible(True)
            self._lbl_alert_msg.setText(
                f"Advertencia de dimensiones: Las páginas seleccionadas tienen diferentes tamaños ({details}). "
                "La ubicación del cajetín podría variar entre planos con formatos distintos."
            )

    def _rebuild_sequence_widgets(self):
        """Reconstruye los widgets de configuración de zonas y separadores intermedios."""
        while self._seq_layout.count() > 0:
            item = self._seq_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._separators.clear()

        for idx, reg in enumerate(self._regions):
            card = QFrame(self._seq_container)
            card.setObjectName("autoNamerZoneCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(8)

            badge = QLabel(f" {idx + 1} ", card)
            badge.setObjectName("autoNamerZoneBadge")
            ThemeManager.apply_zone_color(badge, reg.color_hex)
            card_layout.addWidget(badge)

            lbl_name = QLabel(reg.label, card)
            lbl_name.setObjectName("autoNamerZoneName")
            card_layout.addWidget(lbl_name)

            card_layout.addStretch()

            lbl_preview = QLabel(f"[ {reg.sample_text or 'Sin capturar'} ]", card)
            lbl_preview.setObjectName("autoNamerZonePreview")
            card_layout.addWidget(lbl_preview)

            btn_capture = QPushButton("Capturar", card)
            btn_capture.setObjectName("autoNamerCaptureBtn")
            btn_capture.setFixedSize(68, 24)
            btn_capture.setToolTip(f"Hacer clic y luego arrastrar en el plano para definir {reg.label}")
            is_active = (self._canvas._active_capture_id == reg.region_id)
            if is_active:
                ThemeManager.apply_zone_color(btn_capture, reg.color_hex)
            btn_capture.clicked.connect(lambda _, rid=reg.region_id: self._set_active_region_capture(rid))
            card_layout.addWidget(btn_capture)

            if len(self._regions) > 1:
                btn_del = QPushButton(card)
                btn_del.setFixedSize(22, 22)
                btn_del.setIcon(ThemeManager.get_icon("trash", size=12))
                btn_del.setToolTip("Eliminar esta zona")
                btn_del.clicked.connect(lambda _, rid=reg.region_id: self._remove_region(rid))
                card_layout.addWidget(btn_del)

            self._seq_layout.addWidget(card)

            if idx < len(self._regions) - 1:
                sep_box = QHBoxLayout()
                sep_box.setContentsMargins(16, 2, 16, 2)
                sep_box.setSpacing(6)
                sep_box.addWidget(QLabel("Texto / Separador intermedio:", self._seq_container))
                saved_seps = settings.get("auto_namer.last_separators", [" - "])
                init_val = saved_seps[idx] if idx < len(saved_seps) else " - "
                edit_sep = QLineEdit(init_val, self._seq_container)
                edit_sep.setFixedHeight(24)
                edit_sep.textChanged.connect(self._on_separator_changed)
                self._separators.append(edit_sep)
                sep_box.addWidget(edit_sep)
                self._seq_layout.addLayout(sep_box)

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
                self._cached_ocr_results = {k: v for k, v in self._cached_ocr_results.items() if k[1] != region_id}
                self._cached_region_text = {k: v for k, v in self._cached_region_text.items() if k[1] != region_id}
                if sample_item_idx is not None:
                    reg.sample_text = self._extract_text_for_page_region(sample_item_idx, reg)
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
                doc = self._get_doc(item.source_pdf)
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
        except Exception:
            err_pix = QPixmap(800, 600)
            err_pix.fill(Qt.GlobalColor.white)
            self._canvas.set_page_pixmap(err_pix)

    def _on_sample_page_changed(self, combo_idx: int):
        item_idx = self._combo_sample.currentData()
        if item_idx is not None:
            self._load_sample_page(item_idx)
            for reg in self._regions:
                if reg.norm_rect is not None:
                    reg.sample_text = self._extract_text_for_page_region(item_idx, reg)
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

        text_data = self._get_text_data_for_page(sample_item_idx)
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
                cache_key = (sample_item_idx, reg.region_id)
                if cache_key in self._cached_ocr_results:
                    _, ocr_boxes = self._cached_ocr_results[cache_key]
                    for obox in ocr_boxes:
                        all_matched.append(
                            QRectF(obox.x() * pw, obox.y() * ph, obox.width() * pw, obox.height() * ph)
                        )

        self._canvas.show_debug_highlights(all_matched, 1.0, 1.0)

    def _get_text_data_for_page(self, item_idx: int) -> Optional[PageTextData]:
        """Obtiene o extrae la capa de texto vectorial de la página indicada con caché local, RAM y disco (Tier 2)."""
        if item_idx in self._cached_text_pages:
            return self._cached_text_pages[item_idx]

        # 1. Caché en RAM del visor
        if self._page_cache:
            cached_text = self._page_cache.get_text_data(item_idx)
            if cached_text and isinstance(cached_text, PageTextData):
                self._cached_text_pages[item_idx] = cached_text
                return cached_text

        if not (0 <= item_idx < len(self._items)):
            return None

        item = self._items[item_idx]

        # 2. Caché persistente en disco (Tier 2) - ultrarrápido (< 5 ms)
        if self._disk_cache:
            disk_text = self._disk_cache.load_text(item.source_page_idx)
            if disk_text and isinstance(disk_text, PageTextData):
                self._cached_text_pages[item_idx] = disk_text
                if self._page_cache:
                    self._page_cache.set_text_data(item_idx, disk_text)
                return disk_text

        # 3. Fallback: extracción desde el documento PDF y almacenamiento en caché de disco y RAM
        doc = self._get_doc(item.source_pdf)
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

    BOILERPLATE_PATTERNS = [
        "SHEET NUMBER", "SHEET NO.", "SHEET NO", "NO. DE PLANO", "NO. PLANO",
        "SHEET TITLE", "TITULO DE PLANO", "TITULO", "TITLE:",
        "SCALE:", "ESCALA:", "NOT TO SCALE", "AS INDICATED",
        "ISSUED FOR:", "PROJECT NO:", "JOB NO:", "DATE:", "FECHA:",
        "APPROVED:", "CHECKED:", "DRAWN:",
    ]

    @staticmethod
    def clean_boilerplate(raw: str) -> str:
        """Limpia etiquetas estáticas del cajetín que hayan podido quedar atrapadas en la captura."""
        res = raw
        upper = res.upper()
        for bp in AutoNamerDialog.BOILERPLATE_PATTERNS:
            if bp in upper:
                idx = upper.find(bp)
                res = (res[:idx] + " " + res[idx + len(bp):]).strip()
                upper = res.upper()
        return " ".join(res.split()).strip(" :-_#©")

    @staticmethod
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

    def _extract_text_from_norm_rect(self, text_data: PageTextData, norm_rect: QRectF) -> str:
        return extract_text_from_norm_rect_static(text_data, norm_rect)

    def _extract_text_for_page_region(self, item_idx: int, reg: RegionData) -> str:
        """Extrae texto para una región específica, con extracción nativa acotada y fallback a OCR."""
        if reg.norm_rect is None or not (0 <= item_idx < len(self._items)):
            return ""

        cache_key = (
            item_idx,
            reg.region_id,
            round(reg.norm_rect.x(), 4),
            round(reg.norm_rect.y(), 4),
            round(reg.norm_rect.width(), 4),
            round(reg.norm_rect.height(), 4),
        )
        if cache_key in self._cached_region_text:
            return self._cached_region_text[cache_key]

        item = self._items[item_idx]

        if item_idx in self._cached_text_pages:
            text_data = self._cached_text_pages[item_idx]
            if text_data and text_data.char_boxes:
                val = self._extract_text_from_norm_rect(text_data, reg.norm_rect)
                if val.strip():
                    self._cached_region_text[cache_key] = val
                    return val

        # Consultar caché de disco de la página
        if self._disk_cache and self._disk_cache.has_text(item.source_page_idx):
            text_data = self._disk_cache.load_text(item.source_page_idx)
            if text_data is not None:
                self._cached_text_pages[item_idx] = text_data
                val = self._extract_text_from_norm_rect(text_data, reg.norm_rect)
                if val.strip():
                    self._cached_region_text[cache_key] = val
                    return val

        doc = self._get_doc(item.source_pdf)
        if doc and item.source_page_idx < len(doc):
            extracted = ""
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

        ocr_text, ocr_boxes = recognize_pdf_region(item.source_pdf, item.source_page_idx, reg.norm_rect)
        cleaned_ocr = clean_boilerplate(ocr_text) if ocr_text else ""
        self._cached_ocr_results[ocr_key] = (cleaned_ocr, ocr_boxes)
        if cleaned_ocr:
            self._cached_region_text[cache_key] = cleaned_ocr
        return cleaned_ocr

    def _assemble_name_for_page(self, item_idx: int) -> str:
        """Compone el nombre de una página según las regiones y separadores configurados."""
        parts = []
        has_captured_text = False

        for idx, reg in enumerate(self._regions):
            if reg.norm_rect is not None:
                val = self._extract_text_for_page_region(item_idx, reg)
            else:
                val = ""

            if val:
                has_captured_text = True
            parts.append(val)
            if idx < len(self._separators):
                parts.append(self._separators[idx].text())

        if not has_captured_text:
            return ""

        assembled = "".join(parts).strip()
        for sep in self._separators:
            s_val = sep.text().strip()
            if s_val and assembled.endswith(s_val):
                assembled = assembled[:-len(s_val)].strip()
            if s_val and assembled.startswith(s_val):
                assembled = assembled[len(s_val):].strip()

        return assembled

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
        """Inicia el proceso asíncrono en segundo plano para poblar la tabla de previsualización."""
        if self._preview_worker is not None and self._preview_worker.isRunning():
            self._preview_worker.cancel()
            self._preview_worker.wait()

        self._table_preview.setRowCount(len(self._selected_indices))
        has_any_region = any(r.norm_rect is not None for r in self._regions)

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
            elif idx in self._generated_names and self._generated_names[idx] != item.page_name:
                item_new.setText(self._generated_names[idx])
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

        separators_text = [sep.text() for sep in self._separators]
        self._preview_worker = AutoNamerPreviewWorker(
            items=self._items,
            selected_indices=self._selected_indices,
            regions=self._regions,
            separators_text=separators_text,
            cached_region_text=self._cached_region_text,
            cached_ocr_results=self._cached_ocr_results,
            disk_cache=self._disk_cache,
            page_cache=self._page_cache,
            parent=None,
        )
        self._preview_worker.row_computed.connect(self._on_worker_row_computed)
        self._preview_worker.progress.connect(self._on_worker_progress)
        self._preview_worker.finished_all.connect(self._on_worker_finished)
        self._preview_worker.start()

    def _on_worker_row_computed(self, row: int, idx: int, final_name: str, has_text: bool):
        self._generated_names[idx] = final_name
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

        if len(self._generated_names) < len(self._selected_indices):
            if self._preview_worker and self._preview_worker.isRunning():
                self._preview_worker.cancel()
                self._preview_worker.wait()

            missing_indices = [idx for idx in self._selected_indices if idx not in self._generated_names]
            if missing_indices:
                progress = QProgressDialog(
                    "Finalizando la extracción en paralelo de nombres de planos...",
                    "Cancelar",
                    0,
                    len(self._selected_indices),
                    self,
                )
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.setValue(len(self._generated_names))

                regions_args = [
                    (
                        r.region_id,
                        round(r.norm_rect.x(), 4),
                        round(r.norm_rect.y(), 4),
                        round(r.norm_rect.width(), 4),
                        round(r.norm_rect.height(), 4),
                    )
                    for r in self._regions
                    if r.norm_rect is not None
                ]
                separators_text = [sep.text() for sep in self._separators]

                tasks = [
                    (
                        0,
                        idx,
                        self._items[idx].source_pdf,
                        self._items[idx].source_page_idx,
                        regions_args,
                        separators_text,
                        self._items[idx].page_name,
                    )
                    for idx in missing_indices
                ]

                for idx in missing_indices:
                    if progress.wasCanceled():
                        # Si el usuario cancela la ventana modal, actualizar la tabla con lo que se haya
                        # calculado y reanudar el preview worker en segundo plano para que la barra de progreso
                        # y la lista de la derecha sigan vivas y avanzando:
                        self._start_preview_worker()
                        return
                    final_name = self._assemble_name_for_page(idx)
                    self._generated_names[idx] = final_name
                    # Actualizar celda de la tabla para este índice si está visible
                    if idx in self._selected_indices:
                        r_idx = self._selected_indices.index(idx)
                        item_new = QTableWidgetItem(final_name)
                        item_new.setForeground(QBrush(QColor("#2563EB")))
                        item_new.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
                        self._table_preview.setItem(r_idx, 2, item_new)
                    progress.setValue(len(self._generated_names))

        self._save_cached_template()
        self._close_docs()
        self.accept()

    def _apply_alert_icon(self) -> None:
        """
        Pinta el icono de aviso del banner (Methods Down; sin emojis).

        Usa la fábrica vectorial de ``ui/icons`` teñida con el token ``warning``,
        así que es reactivo al tema.
        """
        color = ThemeManager.tokens().warning
        self._lbl_alert_icon.setPixmap(
            ThemeManager.get_icon("alert-triangle", size=16, color=color).pixmap(16, 16)
        )

    def _apply_theme(self):
        """
        Reaplica el tema al diálogo (Methods Down).

        Todo su estilo vive en ``ui/styles/theme.qss``; aquí solo se refresca el
        icono del banner de aviso, que es un *pixmap* dependiente del tema.
        """
        self._apply_alert_icon()
