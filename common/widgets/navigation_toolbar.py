from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QToolBar,
    QPushButton,
    QComboBox,
    QLabel,
)

from common.widgets.page_entry import PageEntryWidget
from common.styles.style_manager import ThemeManager


class NavigationToolBar(QWidget):
    """
    Barra superior horizontal centrada dinámicamente sobre el plano PDF.
    Integra:
    - Selector desplegable de hojas y planos CAD.
    - Controles secuenciales y salto numérico in-place de páginas.
    - Botón de apertura del gestor de páginas.
    - Controles de zoom porcentual y ajuste a ventana.
    - Selector de herramientas de interacción (Puntero, Paneo, Texto, Búsqueda).
    """
    page_changed = Signal(int)
    prev_page_requested = Signal()
    next_page_requested = Signal()
    manage_pages_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    fit_requested = Signal()
    tool_mode_requested = Signal(str)    # "select", "pan", "text_select"
    find_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("toolbarWrapper")

        self._build_ui()
        self.apply_icons()

    def _build_ui(self):
        wrapper_layout = QHBoxLayout(self)
        wrapper_layout.setContentsMargins(6, 3, 6, 3)
        wrapper_layout.setSpacing(0)

        wrapper_layout.addStretch(1)

        self._toolbar = QToolBar("Navegación", self)
        self._toolbar.setObjectName("viewerToolBar")
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(20, 20))

        # 1. Combo de hojas CAD
        self._combo_pages = QComboBox(self._toolbar)
        self._combo_pages.setObjectName("pageSelectCombo")
        self._combo_pages.setFixedHeight(28)
        self._combo_pages.setMinimumWidth(150)
        self._combo_pages.setMaximumWidth(220)
        self._combo_pages.setMaxVisibleItems(20)
        self._combo_pages.setToolTip("Seleccionar hoja o plano CAD")
        self._combo_pages.currentIndexChanged.connect(self._on_combo_page_changed)
        self._toolbar.addWidget(self._combo_pages)

        self._toolbar.addSeparator()

        # 2. Navegación secuencial y numérica
        self._btn_prev_page = QPushButton(self._toolbar)
        self._btn_prev_page.setToolTip("Página anterior")
        self._btn_prev_page.setFixedSize(32, 28)
        self._btn_prev_page.clicked.connect(self.prev_page_requested.emit)
        self._toolbar.addWidget(self._btn_prev_page)

        self._page_entry = PageEntryWidget(self._toolbar)
        self._page_entry.page_selected.connect(self.page_changed.emit)
        self._toolbar.addWidget(self._page_entry)

        self._btn_next_page = QPushButton(self._toolbar)
        self._btn_next_page.setToolTip("Página siguiente")
        self._btn_next_page.setFixedSize(32, 28)
        self._btn_next_page.clicked.connect(self.next_page_requested.emit)
        self._toolbar.addWidget(self._btn_next_page)

        self._btn_manage_pages = QPushButton(self._toolbar)
        self._btn_manage_pages.setObjectName("btnManagePages")
        self._btn_manage_pages.setToolTip("Gestor de páginas (Agregar, duplicar, eliminar páginas) [Ctrl+Shift+P]")
        self._btn_manage_pages.setFixedSize(32, 28)
        self._btn_manage_pages.clicked.connect(self.manage_pages_requested.emit)
        self._toolbar.addWidget(self._btn_manage_pages)

        self._toolbar.addSeparator()

        # 3. Controles de Zoom
        self._btn_zoom_out = QPushButton(self._toolbar)
        self._btn_zoom_out.setToolTip("Reducir zoom (Ctrl+-)")
        self._btn_zoom_out.setFixedSize(32, 28)
        self._btn_zoom_out.clicked.connect(self.zoom_out_requested.emit)
        self._toolbar.addWidget(self._btn_zoom_out)

        self._lbl_zoom = QLabel("100%", self._toolbar)
        self._lbl_zoom.setObjectName("zoomLabel")
        self._toolbar.addWidget(self._lbl_zoom)

        self._btn_zoom_in = QPushButton(self._toolbar)
        self._btn_zoom_in.setToolTip("Aumentar zoom (Ctrl++)")
        self._btn_zoom_in.setFixedSize(32, 28)
        self._btn_zoom_in.clicked.connect(self.zoom_in_requested.emit)
        self._toolbar.addWidget(self._btn_zoom_in)

        self._btn_fit = QPushButton("Ajustar", self._toolbar)
        self._btn_fit.setToolTip("Ajustar plano a la ventana (Ctrl+0)")
        self._btn_fit.clicked.connect(self.fit_requested.emit)
        self._toolbar.addWidget(self._btn_fit)

        self._toolbar.addSeparator()

        # 4. Modos interactivos
        self._btn_tool_select = QPushButton(self._toolbar)
        self._btn_tool_select.setObjectName("btnToolSelect")
        self._btn_tool_select.setCheckable(True)
        self._btn_tool_select.setChecked(True)
        self._btn_tool_select.setFixedSize(32, 28)
        self._btn_tool_select.setToolTip("Puntero / Selección [1]")
        self._btn_tool_select.clicked.connect(lambda: self.tool_mode_requested.emit("select"))
        self._toolbar.addWidget(self._btn_tool_select)

        self._btn_tool_pan = QPushButton(self._toolbar)
        self._btn_tool_pan.setObjectName("btnToolPan")
        self._btn_tool_pan.setCheckable(True)
        self._btn_tool_pan.setChecked(False)
        self._btn_tool_pan.setFixedSize(32, 28)
        self._btn_tool_pan.setToolTip("Mano de Paneo libre [V]")
        self._btn_tool_pan.clicked.connect(lambda: self.tool_mode_requested.emit("pan"))
        self._toolbar.addWidget(self._btn_tool_pan)

        self._btn_tool_text = QPushButton(self._toolbar)
        self._btn_tool_text.setObjectName("btnToolText")
        self._btn_tool_text.setCheckable(True)
        self._btn_tool_text.setChecked(False)
        self._btn_tool_text.setFixedSize(32, 28)
        self._btn_tool_text.setToolTip("Seleccionar y copiar texto [T] (Ctrl+C para copiar)")
        self._btn_tool_text.clicked.connect(lambda: self.tool_mode_requested.emit("text_select"))
        self._toolbar.addWidget(self._btn_tool_text)

        self._btn_find = QPushButton(self._toolbar)
        self._btn_find.setObjectName("btnFindText")
        self._btn_find.setFixedSize(32, 28)
        self._btn_find.setToolTip("Buscar texto en la página [Ctrl+F]")
        self._btn_find.clicked.connect(self.find_requested.emit)
        self._toolbar.addWidget(self._btn_find)

        wrapper_layout.addWidget(self._toolbar, 0, Qt.AlignmentFlag.AlignCenter)
        wrapper_layout.addStretch(1)

    def apply_icons(self):
        self._btn_prev_page.setIcon(ThemeManager.get_icon("chevron-left"))
        self._btn_next_page.setIcon(ThemeManager.get_icon("chevron-right"))
        self._btn_manage_pages.setIcon(ThemeManager.get_icon("pages-grid"))
        self._btn_zoom_out.setIcon(ThemeManager.get_icon("zoom-out"))
        self._btn_zoom_in.setIcon(ThemeManager.get_icon("zoom-in"))
        self._btn_fit.setIcon(ThemeManager.get_icon("fit-window"))
        self._btn_tool_select.setIcon(ThemeManager.get_icon("select"))
        self._btn_tool_pan.setIcon(ThemeManager.get_icon("hand"))
        self._btn_tool_text.setIcon(ThemeManager.get_icon("text-select"))
        self._btn_find.setIcon(ThemeManager.get_icon("search"))

    def _on_combo_page_changed(self, index: int):
        if index >= 0:
            p_idx = self._combo_pages.itemData(index)
            if p_idx is not None:
                self.page_changed.emit(p_idx)

    def set_pages(self, current_page: int, total_pages: int):
        self._page_entry.set_pages(current_page, total_pages)
        self._combo_pages.blockSignals(True)
        if 0 <= current_page < self._combo_pages.count():
            self._combo_pages.setCurrentIndex(current_page)
        self._combo_pages.blockSignals(False)

    def set_page_names(self, page_names: list[str], current_page: int = 0):
        self._combo_pages.blockSignals(True)
        self._combo_pages.clear()
        for i, raw_name in enumerate(page_names):
            clean = raw_name.strip()
            num = i + 1
            if clean.lower().startswith("página") or clean.lower().startswith("pagina") or clean == str(num):
                text = f"Pág. {num}"
            elif clean:
                text = f"Pág. {num} - {clean}"
            else:
                text = f"Pág. {num}"
            self._combo_pages.addItem(text, i)

        if 0 <= current_page < self._combo_pages.count():
            self._combo_pages.setCurrentIndex(current_page)
        self._combo_pages.blockSignals(False)

    def set_zoom(self, zoom_percent: float):
        self._lbl_zoom.setText(f"{int(zoom_percent)}%")

    def set_tool_mode(self, mode: str):
        self._btn_tool_select.setChecked(mode == "select")
        self._btn_tool_pan.setChecked(mode == "pan")
        self._btn_tool_text.setChecked(mode == "text_select")

    def set_controls_enabled(self, has_doc: bool, can_navigate: bool, current_page: int = 0, total_pages: int = 0):
        self._btn_prev_page.setEnabled(can_navigate and current_page > 0)
        self._btn_next_page.setEnabled(can_navigate and current_page < total_pages - 1)
        self._btn_manage_pages.setEnabled(has_doc)
        self._combo_pages.setEnabled(can_navigate)
        self._btn_zoom_in.setEnabled(has_doc)
        self._btn_zoom_out.setEnabled(has_doc)
        self._btn_fit.setEnabled(has_doc)
        self._btn_tool_select.setEnabled(has_doc)
        self._btn_tool_pan.setEnabled(has_doc)
        self._btn_tool_text.setEnabled(has_doc)
        self._btn_find.setEnabled(has_doc)
        if not has_doc:
            self._page_entry.set_pages(0, 0)
            self._combo_pages.clear()
