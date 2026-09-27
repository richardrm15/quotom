"""
Inspector de Propiedades de Anotaciones (Property Inspector Sidebar).

Proporciona un panel lateral colapsable (estilo Bluebeam / Figma) para visualizar y
editar en tiempo real todas las propiedades de las anotaciones:
1. Información general (Tipo de anotación ISO, UUID, autor, fecha).
2. Disciplina técnica (HVAC, Electricidad, Plomería, Arquitectura, Estructura, etc.).
3. Contenido / Notas técnicas de ingeniería (texto enriquecido / multilínea).
4. Estilo visual ISO 128 (Color de trazo, grosor de línea, color y opacidad de fondo/relleno, tamaño de fuente).
5. Etiquetas infinitas (Tags con chips interactivos para filtrado).
6. Diccionario de propiedades clave-valor (Metadatos técnicos e ingeniería).
8. Soporte completo de Deshacer / Rehacer (Ctrl+Z y Ctrl+Y) para cada modificación.
"""

from typing import Any
import json
import copy
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QPoint, QRect
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QToolButton,
    QSlider,
    QSpinBox,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QStackedWidget,
    QFrame,
    QColorDialog,
    QApplication,
    QLayout,
    QSizePolicy,
)


class FlowLayout(QLayout):
    """Layout que organiza widgets horizontalmente y los envuelve a la siguiente línea si no caben."""

    def __init__(self, parent=None, margin=0, h_spacing=4, v_spacing=4):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._item_list = []

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._item_list.append(item)

    def count(self):
        return len(self._item_list)

    def itemAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0

        for item in self._item_list:
            space_x = self._h_spacing
            space_y = self._v_spacing
            item_w = item.sizeHint().width()
            item_h = item.sizeHint().height()
            next_x = x + item_w + space_x
            if next_x - space_x > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + space_y
                next_x = x + item_w + space_x
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item_h)

        return y + line_height - rect.y()

from ui.styles.style_manager import ThemeManager

from common.widgets.color_swatch_button import ColorSwatchButton


AEC_PALETTE = [
    ("#EC4899", "Rosa"),
    ("#EF4444", "Rojo"),
    ("#F59E0B", "Ámbar"),
    ("#10B981", "Verde"),
    ("#06B6D4", "Cian"),
    ("#3B82F6", "Azul"),
    ("#8B5CF6", "Púrpura"),
    ("#64748B", "Pizarra"),
]

DISCIPLINE_OPTIONS = [
    "General",
    "HVAC",
    "Electricidad",
    "Plomería",
    "Arquitectura",
    "Estructura",
    "Contra Incendios",
    "Telecomunicaciones",
]

# Estados de revisión estándar ISO 32000-1 §12.5.6.3 (StateModel: Review)
# Utilizados por Bluebeam Revu y Adobe Acrobat
STATUS_OPTIONS = [
    "None",         # Sin estado / Pendiente
    "Accepted",     # Aceptado
    "Rejected",     # Rechazado
    "Cancelled",    # Cancelado
    "Completed",    # Completado
]

TYPE_LABELS = {
    "rect": "Rectángulo",
    "circle": "Círculo / Elipse",
    "line": "Línea Recta",
    "arrow": "Flecha Directriz",
    "cloud": "Nube de Revisión",
    "text": "Texto Libre",
    "callout": "Nota con Flecha",
}


class PropertyInspector(QWidget):
    """Panel lateral de inspección y edición de anotaciones con integración Undo/Redo."""

    annotation_modified = Signal(str, dict, dict)    # (annot_id, old_state_dict, updates_dict)
    multi_annotations_modified = Signal(list, dict)  # (annot_ids: list[str], updates: dict)
    preview_modified = Signal(str, dict)             # (annot_id, delta_updates) para dibujo en vivo
    template_defaults_changed = Signal(str, dict)    # (tool_id, defaults_dict) cuando se edita la plantilla
    request_close = Signal()
    request_duplicate = Signal(object)               # (annot_id: str | list[str])
    request_delete = Signal(object)                  # (annot_id: str | list[str])

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("propertyInspector")
        self.setMinimumWidth(260)
        self.setMaximumWidth(600)

        self._current_annot_id: str | None = None
        self._current_data: dict | None = None
        self._multi_annot_ids: list[str] = []
        self._multi_annot_data: list[dict] = []
        self._is_loading: bool = False
        self._content_before_edit: str = ""
        self._style_before_slider: dict = {}
        # Defaults por herramienta: persistidos en settings de la aplicación (QSettings / JSON)
        from core.settings import settings
        saved_defaults = settings.get("annotations.tool_defaults", {})
        self._tool_defaults: dict[str, dict] = copy.deepcopy(saved_defaults) if isinstance(saved_defaults, dict) else {}
        self._is_template_mode: bool = False  # True cuando no hay anotación real seleccionada
        self._stroke_color_buttons: dict[str, QPushButton] = {}
        self._fill_color_buttons: dict[str, QPushButton] = {}
        self._current_stroke_color: str = "#EC4899"
        self._current_fill_base_color: str = "#EC4899"

        # Temporizador para debounce de escritura de texto (1 comando Undo por frase)
        self._content_timer = QTimer(self)
        self._content_timer.setSingleShot(True)
        self._content_timer.timeout.connect(self._on_content_timer_timeout)

        self._setup_ui()
        self.apply_theme()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Cabecera fija del Inspector
        self._header = QFrame(self)
        self._header.setObjectName("inspectorHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 8, 8, 8)
        header_layout.setSpacing(8)

        self._lbl_title_icon = QLabel(self._header)
        self._lbl_title_icon.setFixedSize(18, 18)
        header_layout.addWidget(self._lbl_title_icon)

        self._lbl_title = QLabel("Propiedades", self._header)
        font = self._lbl_title.font()
        font.setBold(True)
        self._lbl_title.setFont(font)
        header_layout.addWidget(self._lbl_title, 1)

        self._btn_close = QToolButton(self._header)
        self._btn_close.setFixedSize(24, 24)
        self._btn_close.setToolTip("Cerrar Inspector")
        self._btn_close.setCursor(Qt.CursorShape.ArrowCursor)
        self._btn_close.clicked.connect(self.request_close.emit)
        header_layout.addWidget(self._btn_close)

        root_layout.addWidget(self._header, 0)

        # 2. Contenedor apilado (Empty State vs Editor)
        self._stack = QStackedWidget(self)

        # Página 0: Vacío (Sin selección)
        self._empty_page = self._create_empty_page()
        self._stack.addWidget(self._empty_page)

        # Página 1: Editor de propiedades con scroll
        self._editor_scroll = QScrollArea(self)
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._editor_widget = QWidget()
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(8, 8, 8, 12)
        self._editor_layout.setSpacing(8)

        self._build_editor_sections()
        self._editor_layout.addStretch(1)

        self._editor_scroll.setWidget(self._editor_widget)
        self._stack.addWidget(self._editor_scroll)

        root_layout.addWidget(self._stack, 1)
        self._stack.setCurrentIndex(0)

    def _create_empty_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 40, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        icon_lbl = QLabel(page)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setPixmap(ThemeManager.get_icon("edit").pixmap(48, 48))
        layout.addWidget(icon_lbl)

        lbl_no_sel = QLabel("Sin Selección", page)
        lbl_no_sel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = lbl_no_sel.font()
        font.setPointSize(12)
        font.setBold(True)
        lbl_no_sel.setFont(font)
        layout.addWidget(lbl_no_sel)

        lbl_hint = QLabel(
            "Selecciona una anotación o marca en el plano para inspeccionar y editar sus propiedades, estilo visual y metadatos técnicos.",
            page,
        )
        lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_hint.setWordWrap(True)
        lbl_hint.setObjectName("propHintLabel")
        layout.addWidget(lbl_hint)

        layout.addStretch(1)
        return page

    def _create_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self._editor_widget)
        card.setObjectName("inspectorCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        lbl_title = QLabel(title.upper(), card)
        lbl_title.setObjectName("cardTitle")
        lbl_title.setWordWrap(True)
        font = lbl_title.font()
        font.setPointSize(9)
        font.setBold(True)
        lbl_title.setFont(font)
        card_layout.addWidget(lbl_title)

        return card, card_layout

    def _build_editor_sections(self):
        # 1. Tarjeta Metadatos Generales (ISO 32000)
        card_gen, lay_gen = self._create_card("Metadatos Generales (ISO 32000)")

        # Badge de Tipo + Botón copiar ID
        row_type = QHBoxLayout()
        row_type.setSpacing(6)
        self._badge_type = QLabel("TIPO", card_gen)
        self._badge_type.setObjectName("typeBadge")
        row_type.addWidget(self._badge_type)

        self._lbl_id = QLabel("#id", card_gen)
        self._lbl_id.setObjectName("annotIdLabel")
        self._lbl_id.setWordWrap(True)
        row_type.addWidget(self._lbl_id, 1)

        self._btn_copy_id = QToolButton(card_gen)
        self._btn_copy_id.setToolTip("Copiar ID al portapapeles")
        self._btn_copy_id.setIcon(ThemeManager.get_icon("copy"))
        self._btn_copy_id.setFixedSize(22, 22)
        self._btn_copy_id.clicked.connect(self._copy_id_to_clipboard)
        row_type.addWidget(self._btn_copy_id)
        lay_gen.addLayout(row_type)

        # Subject (/Subj)
        row_subj = QHBoxLayout()
        lbl_subj = QLabel("Subject (/Subj):", card_gen)
        lbl_subj.setFixedWidth(95)
        lbl_subj.setObjectName("propFieldLabel")
        row_subj.addWidget(lbl_subj)
        self._txt_subject = QLineEdit(card_gen)
        self._txt_subject.setPlaceholderText("p. ej. Diffuser, Wall, Box...")
        self._txt_subject.editingFinished.connect(self._on_subject_changed)
        row_subj.addWidget(self._txt_subject, 1)
        lay_gen.addLayout(row_subj)

        # Layer (/OC)
        row_layer = QHBoxLayout()
        lbl_layer = QLabel("Layer (/OC):", card_gen)
        lbl_layer.setFixedWidth(95)
        lbl_layer.setObjectName("propFieldLabel")
        row_layer.addWidget(lbl_layer)
        self._combo_layer = QComboBox(card_gen)
        self._combo_layer.setEditable(True)
        self._combo_layer.addItems(DISCIPLINE_OPTIONS)
        self._combo_layer.currentTextChanged.connect(self._on_layer_changed)
        row_layer.addWidget(self._combo_layer, 1)
        lay_gen.addLayout(row_layer)
        self._combo_discipline = self._combo_layer  # Alias de compatibilidad

        # Author (/T)
        row_author = QHBoxLayout()
        lbl_author = QLabel("Author (/T):", card_gen)
        lbl_author.setFixedWidth(95)
        lbl_author.setObjectName("propFieldLabel")
        row_author.addWidget(lbl_author)
        self._txt_author = QLineEdit(card_gen)
        self._txt_author.setPlaceholderText("Nombre del autor...")
        self._txt_author.editingFinished.connect(self._on_author_changed)
        row_author.addWidget(self._txt_author, 1)
        lay_gen.addLayout(row_author)

        # Status (/State)
        row_status = QHBoxLayout()
        lbl_status = QLabel("Status (/State):", card_gen)
        lbl_status.setFixedWidth(95)
        lbl_status.setObjectName("propFieldLabel")
        row_status.addWidget(lbl_status)
        self._combo_status = QComboBox(card_gen)
        self._combo_status.addItems(STATUS_OPTIONS)
        self._combo_status.currentTextChanged.connect(self._on_status_changed)
        row_status.addWidget(self._combo_status, 1)
        lay_gen.addLayout(row_status)

        # Metadatos de fecha
        self._lbl_meta = QLabel("Fecha: -", card_gen)
        self._lbl_meta.setObjectName("propMetaLabel")
        lay_gen.addWidget(self._lbl_meta)

        self._editor_layout.addWidget(card_gen)

        # 2. Tarjeta Contents (/Contents)
        card_content, lay_content = self._create_card("Contents (/Contents)")
        self._txt_content = QTextEdit(card_content)
        self._txt_content.setObjectName("contentEdit")
        self._txt_content.setPlaceholderText("Escribe un texto o comentario técnico (/Contents)...")
        self._txt_content.setMaximumHeight(85)
        self._txt_content.textChanged.connect(self._on_content_changed)
        lay_content.addWidget(self._txt_content)
        self._editor_layout.addWidget(card_content)

        # 2b. Tarjeta Tipografía y Formato (ISO 32000 /DA, /Q) para Texto y Callout
        self._card_typography, lay_typo = self._create_card("Tipografía y Formato (ISO 32000)")

        # Familia de Fuente
        row_font = QHBoxLayout()
        lbl_font = QLabel("Fuente:", self._card_typography)
        lbl_font.setFixedWidth(60)
        lbl_font.setObjectName("propFieldLabel")
        row_font.addWidget(lbl_font)
        self._combo_font_family = QComboBox(self._card_typography)
        self._combo_font_family.addItems([
            "sans-serif",
            "Arial",
            "Helvetica",
            "Roboto",
            "Segoe UI",
            "Times New Roman",
            "Courier",
            "monospace",
        ])
        self._combo_font_family.currentTextChanged.connect(self._on_font_family_changed)
        row_font.addWidget(self._combo_font_family, 1)
        lay_typo.addLayout(row_font)

        # Tamaño y Color de Fuente
        row_size_col = QHBoxLayout()
        row_size_col.setSpacing(6)
        lbl_size = QLabel("Tamaño:", self._card_typography)
        lbl_size.setFixedWidth(60)
        lbl_size.setObjectName("propFieldLabel")
        row_size_col.addWidget(lbl_size)

        self._spin_font_size = QSpinBox(self._card_typography)
        self._spin_font_size.setRange(6, 72)
        self._spin_font_size.setValue(11)
        self._spin_font_size.setSuffix(" pt")
        self._spin_font_size.setFixedWidth(68)
        self._spin_font_size.valueChanged.connect(self._on_typography_font_size_changed)
        row_size_col.addWidget(self._spin_font_size)

        lbl_tc = QLabel("Color:", self._card_typography)
        lbl_tc.setObjectName("propFieldLabel")
        row_size_col.addWidget(lbl_tc)

        self._btn_text_color = ColorSwatchButton("#FFFFFF", self._card_typography)
        self._btn_text_color.setToolTip("Color de texto")
        self._btn_text_color.clicked.connect(self._pick_text_color)
        row_size_col.addWidget(self._btn_text_color)
        row_size_col.addStretch(1)
        lay_typo.addLayout(row_size_col)

        # Estilo (Negrita, Cursiva) y Alineación (Izquierda, Centro, Derecha - ISO /Q)
        row_style_align = QHBoxLayout()
        row_style_align.setSpacing(4)

        self._btn_bold = QToolButton(self._card_typography)
        self._btn_bold.setText("B")
        self._btn_bold.setCheckable(True)
        self._btn_bold.setFixedSize(28, 26)
        self._btn_bold.setToolTip("Negrita (Bold)")
        f_b = self._btn_bold.font()
        f_b.setBold(True)
        self._btn_bold.setFont(f_b)
        self._btn_bold.toggled.connect(self._on_font_bold_toggled)
        row_style_align.addWidget(self._btn_bold)

        self._btn_italic = QToolButton(self._card_typography)
        self._btn_italic.setText("I")
        self._btn_italic.setCheckable(True)
        self._btn_italic.setFixedSize(28, 26)
        self._btn_italic.setToolTip("Cursiva (Italic)")
        f_i = self._btn_italic.font()
        f_i.setItalic(True)
        self._btn_italic.setFont(f_i)
        self._btn_italic.toggled.connect(self._on_font_italic_toggled)
        row_style_align.addWidget(self._btn_italic)

        # Separador vertical
        sep = QFrame(self._card_typography)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        row_style_align.addWidget(sep)

        # Grupo de alineación ISO /Q (0=Left, 1=Center, 2=Right)
        self._btn_align_left = QToolButton(self._card_typography)
        self._btn_align_left.setText("⇤")
        self._btn_align_left.setCheckable(True)
        self._btn_align_left.setChecked(True)
        self._btn_align_left.setFixedSize(28, 26)
        self._btn_align_left.setToolTip("Alinear a la izquierda (ISO /Q 0)")
        self._btn_align_left.clicked.connect(lambda: self._on_text_align_selected("left"))
        row_style_align.addWidget(self._btn_align_left)

        self._btn_align_center = QToolButton(self._card_typography)
        self._btn_align_center.setText("≡")
        self._btn_align_center.setCheckable(True)
        self._btn_align_center.setFixedSize(28, 26)
        self._btn_align_center.setToolTip("Centrar texto (ISO /Q 1)")
        self._btn_align_center.clicked.connect(lambda: self._on_text_align_selected("center"))
        row_style_align.addWidget(self._btn_align_center)

        self._btn_align_right = QToolButton(self._card_typography)
        self._btn_align_right.setText("⇥")
        self._btn_align_right.setCheckable(True)
        self._btn_align_right.setFixedSize(28, 26)
        self._btn_align_right.setToolTip("Alinear a la derecha (ISO /Q 2)")
        self._btn_align_right.clicked.connect(lambda: self._on_text_align_selected("right"))
        row_style_align.addWidget(self._btn_align_right)

        row_style_align.addStretch(1)
        lay_typo.addLayout(row_style_align)

        # Figura del Contenedor (exclusiva para FreeText / Texto)
        self._row_container_shape_widget = QWidget(self._card_typography)
        row_shape = QHBoxLayout(self._row_container_shape_widget)
        row_shape.setContentsMargins(0, 4, 0, 0)
        row_shape.setSpacing(6)

        lbl_shape = QLabel("Figura:", self._row_container_shape_widget)
        lbl_shape.setFixedWidth(60)
        lbl_shape.setObjectName("propFieldLabel")
        row_shape.addWidget(lbl_shape)

        self._combo_container_shape = QComboBox(self._row_container_shape_widget)
        self._combo_container_shape.addItem("Rectángulo", "rect")
        self._combo_container_shape.addItem("Círculo", "circle")
        self._combo_container_shape.addItem("Triángulo", "triangle")
        self._combo_container_shape.addItem("Hexágono", "hexagon")
        self._combo_container_shape.currentIndexChanged.connect(self._on_container_shape_changed)
        row_shape.addWidget(self._combo_container_shape, 1)

        lay_typo.addWidget(self._row_container_shape_widget)

        self._editor_layout.addWidget(self._card_typography)

        # 3. Tarjeta Estilo Visual (ISO 128)
        card_style, lay_style = self._create_card("Estilo Visual (ISO 128)")

        # Color de Trazo (Borde)
        lbl_stroke = QLabel("Color de Trazo (Borde):")
        lbl_stroke.setObjectName("propFieldLabel")
        lay_style.addWidget(lbl_stroke)

        palette_stroke_grid = QGridLayout()
        palette_stroke_grid.setContentsMargins(0, 2, 0, 4)
        palette_stroke_grid.setHorizontalSpacing(6)
        palette_stroke_grid.setVerticalSpacing(6)
        palette_stroke_grid.setColumnStretch(5, 1)

        self._stroke_color_buttons = {}
        for idx, (hex_col, name) in enumerate(AEC_PALETTE):
            btn = ColorSwatchButton(hex_col, card_style)
            btn.setToolTip(f"Trazo {name} ({hex_col})")
            btn.clicked.connect(lambda _, c=hex_col: self._on_stroke_color_selected(c))
            r = idx // 5
            c = idx % 5
            palette_stroke_grid.addWidget(btn, r, c)
            self._stroke_color_buttons[hex_col] = btn

        # Botón para color de trazo personalizado (Fila 1, Col 3)
        self._btn_custom_stroke = ColorSwatchButton(
            None, card_style, dashed=True, text="+"
        )
        self._btn_custom_stroke.setToolTip("Seleccionar más colores de trazo...")
        self._btn_custom_stroke.clicked.connect(self._pick_custom_stroke_color)
        palette_stroke_grid.addWidget(self._btn_custom_stroke, 1, 3)

        lay_style.addLayout(palette_stroke_grid)

        # Grosor de Línea
        row_width = QHBoxLayout()
        row_width.setSpacing(6)
        lbl_w = QLabel("Grosor:")
        lbl_w.setFixedWidth(50)
        row_width.addWidget(lbl_w)
        self._slider_width = QSlider(Qt.Orientation.Horizontal, card_style)
        self._slider_width.setRange(1, 36)
        self._slider_width.setValue(2)
        self._slider_width.sliderPressed.connect(self._on_slider_pressed)
        self._slider_width.valueChanged.connect(self._on_stroke_width_changed)
        self._slider_width.sliderReleased.connect(self._on_slider_released)
        row_width.addWidget(self._slider_width, 1)

        self._spin_width = QSpinBox(card_style)
        self._spin_width.setRange(1, 36)
        self._spin_width.setValue(2)
        self._spin_width.setSuffix(" px")
        self._spin_width.setFixedWidth(56)
        self._spin_width.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_width.valueChanged.connect(self._on_spin_width_changed)
        row_width.addWidget(self._spin_width)
        lay_style.addLayout(row_width)

        # Color de Fondo / Relleno
        lbl_fill = QLabel("Color de Fondo / Relleno:")
        lbl_fill.setObjectName("propFieldLabel")
        lay_style.addWidget(lbl_fill)

        palette_fill_grid = QGridLayout()
        palette_fill_grid.setContentsMargins(0, 2, 0, 4)
        palette_fill_grid.setHorizontalSpacing(6)
        palette_fill_grid.setVerticalSpacing(6)
        palette_fill_grid.setColumnStretch(5, 1)

        # Botón Sin Relleno en Fila 0, Col 0
        self._btn_no_fill = ColorSwatchButton(
            None, card_style, dashed=True, text="Ø", danger=True
        )
        self._btn_no_fill.setToolTip("Sin fondo (Transparente)")
        self._btn_no_fill.clicked.connect(self._on_no_fill_selected)
        palette_fill_grid.addWidget(self._btn_no_fill, 0, 0)

        self._fill_color_buttons = {}
        for idx, (hex_col, name) in enumerate(AEC_PALETTE):
            btn = ColorSwatchButton(hex_col, card_style)
            btn.setToolTip(f"Fondo {name} ({hex_col})")
            btn.clicked.connect(lambda _, c=hex_col: self._on_fill_color_selected(c))
            grid_pos = idx + 1
            r = grid_pos // 5
            c = grid_pos % 5
            palette_fill_grid.addWidget(btn, r, c)
            self._fill_color_buttons[hex_col] = btn

        # Botón para color de fondo personalizado en Fila 1, Col 4
        self._btn_custom_fill = ColorSwatchButton(
            None, card_style, dashed=True, text="+"
        )
        self._btn_custom_fill.setToolTip("Seleccionar más colores de fondo...")
        self._btn_custom_fill.clicked.connect(self._pick_custom_fill_color)
        palette_fill_grid.addWidget(self._btn_custom_fill, 1, 4)

        lay_style.addLayout(palette_fill_grid)

        row_fill_opacity = QHBoxLayout()
        row_fill_opacity.setSpacing(6)
        lbl_op = QLabel("Opacidad:")
        lbl_op.setFixedWidth(50)
        row_fill_opacity.addWidget(lbl_op)
        self._slider_fill_opacity = QSlider(Qt.Orientation.Horizontal, card_style)
        self._slider_fill_opacity.setRange(0, 100)
        self._slider_fill_opacity.setValue(0)
        self._slider_fill_opacity.sliderPressed.connect(self._on_slider_pressed)
        self._slider_fill_opacity.valueChanged.connect(self._on_fill_opacity_changed)
        self._slider_fill_opacity.sliderReleased.connect(self._on_slider_released)
        row_fill_opacity.addWidget(self._slider_fill_opacity, 1)

        self._spin_fill_opacity = QSpinBox(card_style)
        self._spin_fill_opacity.setRange(0, 100)
        self._spin_fill_opacity.setValue(0)
        self._spin_fill_opacity.setSuffix(" %")
        self._spin_fill_opacity.setFixedWidth(56)
        self._spin_fill_opacity.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_fill_opacity.valueChanged.connect(self._on_spin_fill_opacity_changed)
        row_fill_opacity.addWidget(self._spin_fill_opacity)
        lay_style.addLayout(row_fill_opacity)

        # Tamaño de fuente (para Texto y Callout)
        self._row_font = QHBoxLayout()
        self._row_font.setSpacing(6)
        lbl_f = QLabel("Fuente:")
        lbl_f.setFixedWidth(50)
        self._row_font.addWidget(lbl_f)
        self._slider_font = QSlider(Qt.Orientation.Horizontal, card_style)
        self._slider_font.setRange(6, 72)
        self._slider_font.setValue(11)
        self._slider_font.sliderPressed.connect(self._on_slider_pressed)
        self._slider_font.valueChanged.connect(self._on_font_size_changed)
        self._slider_font.sliderReleased.connect(self._on_slider_released)
        self._row_font.addWidget(self._slider_font, 1)

        self._spin_font = QSpinBox(card_style)
        self._spin_font.setRange(6, 72)
        self._spin_font.setValue(11)
        self._spin_font.setSuffix(" pt")
        self._spin_font.setFixedWidth(56)
        self._spin_font.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin_font.valueChanged.connect(self._on_spin_font_changed)
        self._row_font.addWidget(self._spin_font)
        lay_style.addLayout(self._row_font)

        self._editor_layout.addWidget(card_style)

        # 4. Tarjeta Etiquetas (Tags Infinitos)
        card_tags, lay_tags = self._create_card("Etiquetas (Tags)")
        self._tags_container = QWidget(card_tags)
        self._tags_layout = FlowLayout(self._tags_container, margin=0, h_spacing=4, v_spacing=4)
        lay_tags.addWidget(self._tags_container)

        # Fila para agregar tag
        row_add_tag = QHBoxLayout()
        row_add_tag.setSpacing(4)
        self._in_tag = QLineEdit(card_tags)
        self._in_tag.setPlaceholderText("Nueva etiqueta...")
        self._in_tag.returnPressed.connect(self._add_tag)
        row_add_tag.addWidget(self._in_tag, 1)

        self._btn_add_tag = QToolButton(card_tags)
        self._btn_add_tag.setText("+")
        self._btn_add_tag.setFixedSize(24, 24)
        self._btn_add_tag.setToolTip("Agregar etiqueta")
        self._btn_add_tag.clicked.connect(self._add_tag)
        row_add_tag.addWidget(self._btn_add_tag)
        lay_tags.addLayout(row_add_tag)

        self._editor_layout.addWidget(card_tags)

        # 5. Tarjeta Diccionario Clave-Valor (Propiedades Técnicas / Multi-Valor)
        card_props, lay_props = self._create_card("Propiedades Técnicas (Key-Value)")

        # Tabla dinámica: col 0 = Clave, col 1..N = valores, última = acciones
        self._tbl_props = QTableWidget(0, 3, card_props)
        self._tbl_props.setHorizontalHeaderLabels(["Clave", "Valor 1", ""])
        self._tbl_props.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._tbl_props.horizontalHeader().setDefaultSectionSize(90)
        self._tbl_props.horizontalHeader().setStretchLastSection(False)
        self._tbl_props.verticalHeader().setVisible(False)
        self._tbl_props.setMinimumHeight(80)
        self._tbl_props.setMaximumHeight(200)
        self._tbl_props.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._tbl_props.cellChanged.connect(self._on_property_cell_changed)
        lay_props.addWidget(self._tbl_props)

        # Fila inferior: agregar nueva clave con sus valores
        grid_add_prop = QGridLayout()
        grid_add_prop.setContentsMargins(0, 4, 0, 0)
        grid_add_prop.setHorizontalSpacing(4)
        grid_add_prop.setVerticalSpacing(4)

        self._in_prop_key = QLineEdit(card_props)
        self._in_prop_key.setPlaceholderText("Clave (ej. Flow)")
        grid_add_prop.addWidget(self._in_prop_key, 0, 0, 1, 3)

        self._in_prop_val = QLineEdit(card_props)
        self._in_prop_val.setPlaceholderText("Valor 1 (ej. 400)")
        self._in_prop_val.returnPressed.connect(self._add_custom_property)
        grid_add_prop.addWidget(self._in_prop_val, 1, 0)

        self._in_prop_val2 = QLineEdit(card_props)
        self._in_prop_val2.setPlaceholderText("Valor 2 (ej. gpm)")
        self._in_prop_val2.returnPressed.connect(self._add_custom_property)
        grid_add_prop.addWidget(self._in_prop_val2, 1, 1)

        self._btn_add_prop = QToolButton(card_props)
        self._btn_add_prop.setText("+")
        self._btn_add_prop.setFixedSize(24, 24)
        self._btn_add_prop.setToolTip("Agregar propiedad técnica")
        self._btn_add_prop.clicked.connect(self._add_custom_property)
        grid_add_prop.addWidget(self._btn_add_prop, 1, 2)
        lay_props.addLayout(grid_add_prop)

        self._editor_layout.addWidget(card_props)

        # 7. Acciones Rápidas (Duplicar, Eliminar)
        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        self._btn_dup = QPushButton("Duplicar", self._editor_widget)
        self._btn_dup.setIcon(ThemeManager.get_icon("duplicate"))
        self._btn_dup.clicked.connect(self._on_dup_button_clicked)
        row_actions.addWidget(self._btn_dup, 1)

        self._btn_del = QPushButton("Eliminar", self._editor_widget)
        self._btn_del.setIcon(ThemeManager.get_icon("trash"))
        self._btn_del.setObjectName("dangerButton")
        self._btn_del.clicked.connect(self._on_del_button_clicked)
        row_actions.addWidget(self._btn_del, 1)

        self._editor_layout.addLayout(row_actions)

    @staticmethod
    def _get_style_dict(annot_data: dict) -> dict:
        st = annot_data.get("style", {})
        if isinstance(st, str):
            try: return json.loads(st)
            except Exception: return {}
        return dict(st) if isinstance(st, dict) else {}

    def _on_dup_button_clicked(self):
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.request_duplicate.emit(list(self._multi_annot_ids))
        elif self._current_annot_id:
            self.request_duplicate.emit(self._current_annot_id)

    def _on_del_button_clicked(self):
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.request_delete.emit(list(self._multi_annot_ids))
        elif self._current_annot_id:
            self.request_delete.emit(self._current_annot_id)

    def load_annotations(self, annot_list: list[dict]):
        """Carga una o múltiples anotaciones en el inspector para inspección y edición colectiva."""
        if not annot_list:
            self._multi_annot_ids = []
            self._multi_annot_data = []
            self.load_annotation(None)
            return

        if len(annot_list) == 1:
            self._multi_annot_ids = []
            self._multi_annot_data = []
            self.load_annotation(annot_list[0])
            return

        # Modo Selección Múltiple (len > 1)
        self._is_loading = True
        self._is_template_mode = False
        self._current_annot_id = None
        self._current_data = None
        self._multi_annot_ids = [a.get("id") for a in annot_list if a.get("id")]
        self._multi_annot_data = copy.deepcopy(annot_list)
        self._stack.setCurrentIndex(1)

        # 1. Cabecera y datos generales
        types = {a.get("type", "rect") for a in annot_list}
        if len(types) == 1:
            t = list(types)[0]
            self._badge_type.setText(f"{TYPE_LABELS.get(t, t).upper()} ({len(annot_list)})")
        else:
            self._badge_type.setText(f"MÚLTIPLE ({len(annot_list)})")
        self._lbl_id.setText(f"{len(annot_list)} anotaciones seleccionadas")
        self._btn_dup.setVisible(True)
        self._btn_del.setVisible(True)
        self._btn_copy_id.setVisible(False)
        self._lbl_meta.setText(f"Selección múltiple: {len(annot_list)} elementos")

        # 2. Metadatos ISO
        subjs = {a.get("subject") or a.get("/Subj") or "" for a in annot_list}
        self._txt_subject.blockSignals(True)
        if len(subjs) == 1 and list(subjs)[0]:
            self._txt_subject.setText(list(subjs)[0])
            self._txt_subject.setPlaceholderText("")
        else:
            self._txt_subject.setText("")
            self._txt_subject.setPlaceholderText("(Varios valores)" if len(subjs) > 1 else "")
        self._txt_subject.blockSignals(False)

        layers = {a.get("layer") or a.get("/OC") or a.get("discipline") or "General" for a in annot_list}
        self._combo_layer.blockSignals(True)
        if len(layers) == 1:
            idx = self._combo_layer.findText(list(layers)[0])
            self._combo_layer.setCurrentIndex(idx if idx != -1 else 0)
        else:
            self._combo_layer.setCurrentIndex(-1)
        self._combo_layer.blockSignals(False)

        authors = {a.get("author") or a.get("/T") or "" for a in annot_list}
        self._txt_author.blockSignals(True)
        if len(authors) == 1 and list(authors)[0]:
            self._txt_author.setText(list(authors)[0])
            self._txt_author.setPlaceholderText("")
        else:
            self._txt_author.setText("")
            self._txt_author.setPlaceholderText("(Varios autores)" if len(authors) > 1 else "")
        self._txt_author.blockSignals(False)

        statuses = {a.get("status") or a.get("/State") or "None" for a in annot_list}
        self._combo_status.blockSignals(True)
        if len(statuses) == 1:
            idx = self._combo_status.findText(list(statuses)[0])
            self._combo_status.setCurrentIndex(idx if idx != -1 else 0)
        else:
            self._combo_status.setCurrentIndex(-1)
        self._combo_status.blockSignals(False)

        contents = {a.get("content") or a.get("/Contents") or "" for a in annot_list}
        self._txt_content.blockSignals(True)
        if len(contents) == 1 and list(contents)[0]:
            self._txt_content.setPlainText(list(contents)[0])
            self._txt_content.setPlaceholderText("")
        else:
            self._txt_content.setPlainText("")
            self._txt_content.setPlaceholderText("(Contenido múltiple)" if len(contents) > 1 else "")
        self._txt_content.blockSignals(False)

        # 3. Tipografía (ISO 32000)
        has_text = any(a.get("type") in ("text", "callout") for a in annot_list)
        self._card_typography.setVisible(has_text)
        has_freetext = any(a.get("type") == "text" for a in annot_list)
        self._row_container_shape_widget.setVisible(has_freetext)

        styles = [self._get_style_dict(a) for a in annot_list]

        if has_text:
            text_styles = [self._get_style_dict(a) for a in annot_list if a.get("type") in ("text", "callout")]
            fams = {s.get("font_family", "sans-serif") for s in text_styles}
            self._combo_font_family.blockSignals(True)
            if len(fams) == 1:
                idx_fam = self._combo_font_family.findText(list(fams)[0])
                self._combo_font_family.setCurrentIndex(idx_fam if idx_fam != -1 else 0)
            else:
                self._combo_font_family.setCurrentIndex(-1)
            self._combo_font_family.blockSignals(False)

            sizes = {int(float(s.get("font_size", 11))) for s in text_styles}
            self._spin_font_size.blockSignals(True)
            if len(sizes) == 1:
                self._spin_font_size.setValue(list(sizes)[0])
            self._spin_font_size.blockSignals(False)

            bolds = {bool(s.get("font_bold", False)) for s in text_styles}
            self._btn_bold.blockSignals(True)
            self._btn_bold.setChecked(len(bolds) == 1 and list(bolds)[0])
            self._btn_bold.blockSignals(False)

            italics = {bool(s.get("font_italic", False)) for s in text_styles}
            self._btn_italic.blockSignals(True)
            self._btn_italic.setChecked(len(italics) == 1 and list(italics)[0])
            self._btn_italic.blockSignals(False)

            aligns = {str(s.get("text_align", "left")).lower() for s in text_styles}
            self._btn_align_left.blockSignals(True)
            self._btn_align_center.blockSignals(True)
            self._btn_align_right.blockSignals(True)
            if len(aligns) == 1:
                a_val = list(aligns)[0]
                self._btn_align_left.setChecked(a_val == "left")
                self._btn_align_center.setChecked(a_val == "center")
                self._btn_align_right.setChecked(a_val == "right")
            else:
                self._btn_align_left.setChecked(False)
                self._btn_align_center.setChecked(False)
                self._btn_align_right.setChecked(False)
            self._btn_align_left.blockSignals(False)
            self._btn_align_center.blockSignals(False)
            self._btn_align_right.blockSignals(False)

            tcolors = {s.get("text_color", "#FFFFFF") for s in text_styles}
            tc = list(tcolors)[0] if len(tcolors) == 1 else "#888888"
            self._btn_text_color.set_color(tc)

            if has_freetext:
                ft_styles = [self._get_style_dict(a) for a in annot_list if a.get("type") == "text"]
                shapes = {s.get("shape", "rect") for s in ft_styles}
                self._combo_container_shape.blockSignals(True)
                if len(shapes) == 1:
                    sh = list(shapes)[0]
                    if sh == "ellipse": sh = "circle"
                    idx_sh = self._combo_container_shape.findData(sh)
                    self._combo_container_shape.setCurrentIndex(idx_sh if idx_sh != -1 else 0)
                else:
                    self._combo_container_shape.setCurrentIndex(-1)
                self._combo_container_shape.blockSignals(False)

        # 4. Estilo Visual
        stroke_colors = {s.get("stroke_color") for s in styles if s.get("stroke_color")}
        active_stroke = list(stroke_colors)[0] if len(stroke_colors) == 1 else None
        self._current_stroke_color = active_stroke or ""
        if active_stroke:
            self._update_stroke_swatch_selection(active_stroke)
        else:
            for btn in getattr(self, "_stroke_color_buttons", {}).values():
                btn.set_selected(False)
            if hasattr(self, "_btn_custom_stroke"):
                self._btn_custom_stroke.set_dashed(True)
                self._btn_custom_stroke.set_color(None)
                self._btn_custom_stroke.set_selected(False)
                self._btn_custom_stroke.set_badge_text("+")

        widths = {int(float(s.get("stroke_width", 2.0))) for s in styles}
        self._slider_width.blockSignals(True)
        self._spin_width.blockSignals(True)
        if len(widths) == 1:
            w_val = list(widths)[0]
            self._slider_width.setValue(w_val)
            self._spin_width.setValue(w_val)
        self._slider_width.blockSignals(False)
        self._spin_width.blockSignals(False)

        fill_colors = {s.get("fill_color") for s in styles if s.get("fill_color")}
        active_fill = list(fill_colors)[0] if len(fill_colors) == 1 else None
        base_fills = {s.get("fill_base_color") for s in styles if s.get("fill_base_color")}
        active_base_fill = list(base_fills)[0] if len(base_fills) == 1 else (active_fill or "")
        self._current_fill_base_color = active_base_fill or ""
        if active_fill:
            self._update_fill_swatch_selection(active_fill, active_base_fill)
        else:
            for btn in getattr(self, "_fill_color_buttons", {}).values():
                btn.set_selected(False)
            if hasattr(self, "_btn_no_fill"):
                self._btn_no_fill.set_selected(False)
            if hasattr(self, "_btn_custom_fill"):
                self._btn_custom_fill.set_dashed(True)
                self._btn_custom_fill.set_color(None)
                self._btn_custom_fill.set_selected(False)
                self._btn_custom_fill.set_badge_text("+")

        opacities = {int(float(s.get("fill_opacity", 0.08)) * 100) for s in styles}
        self._slider_fill_opacity.blockSignals(True)
        self._spin_fill_opacity.blockSignals(True)
        if len(opacities) == 1:
            op_val = list(opacities)[0]
            self._slider_fill_opacity.setValue(op_val)
            self._spin_fill_opacity.setValue(op_val)
        self._slider_fill_opacity.blockSignals(False)
        self._spin_fill_opacity.blockSignals(False)

        self._is_loading = False

    def load_annotation(self, annot_data: dict | None, *args, **kwargs):
        """Carga una anotación en el inspector para visualización y edición."""
        self._multi_annot_ids = []
        self._multi_annot_data = []
        if not annot_data:
            self._current_annot_id = None
            self._current_data = None
            self._stack.setCurrentIndex(0)
            return

        # Si no viene del load_tool_template, salir del modo plantilla
        if not annot_data.get("_is_template"):
            self._is_template_mode = False

        self._is_loading = True
        self._current_annot_id = annot_data.get("id")
        self._current_data = copy.deepcopy(annot_data)

        for k in ("geometry", "style", "properties", "tags"):
            val = self._current_data.get(k)
            if isinstance(val, str):
                try:
                    self._current_data[k] = json.loads(val)
                except Exception:
                    self._current_data[k] = {} if k != "tags" else []
            elif val is None:
                self._current_data[k] = {} if k != "tags" else []

        # 1. Cabecera y datos generales
        t = annot_data.get("type", "rect")
        self._badge_type.setText(TYPE_LABELS.get(t, t).upper())
        is_tmpl = annot_data.get("_is_template", False)
        if is_tmpl:
            self._lbl_id.setText("PLANTILLA  •  Los cambios se aplican a nuevas anotaciones")
        else:
            short_id = annot_data.get("id", "")[:8]
            self._lbl_id.setText(f"#{short_id}")
        # Mostrar/ocultar acciones según modo
        self._btn_dup.setVisible(not is_tmpl)
        self._btn_del.setVisible(not is_tmpl)
        self._btn_copy_id.setVisible(not is_tmpl)

        style = self._current_data.get("style", {})
        if isinstance(style, str):
            try: style = json.loads(style)
            except Exception: style = {}

        # Subject (/Subj)
        subj = annot_data.get("subject") or annot_data.get("/Subj") or ""
        self._txt_subject.setText(subj)

        # Layer (/OC)
        layer = annot_data.get("layer") or annot_data.get("/OC") or annot_data.get("discipline") or "General"
        idx = self._combo_layer.findText(layer)
        if idx != -1:
            self._combo_layer.setCurrentIndex(idx)
        else:
            self._combo_layer.setCurrentText(layer)

        # Author (/T)
        author = annot_data.get("author") or annot_data.get("/T") or "Usuario"
        self._txt_author.setText(author)

        # Status (/State)
        status_val = annot_data.get("status") or annot_data.get("/State") or "None"
        idx_status = self._combo_status.findText(status_val)
        self._combo_status.setCurrentIndex(idx_status if idx_status != -1 else 0)

        # Metadatos de fecha
        created = annot_data.get("created_at") or "-"
        self._lbl_meta.setText(f"Creado: {created[:19]}")

        # 2. Contents (/Contents)
        content_str = annot_data.get("content") or annot_data.get("/Contents") or annot_data.get("contents") or ""
        self._content_before_edit = content_str
        self._txt_content.setPlainText(content_str)

        # 3. Estilo
        style = annot_data.get("style", {})
        if isinstance(style, str):
            try:
                style = json.loads(style)
            except Exception:
                style = {}

        # Control de visibilidad y valores de Tipografía (ISO 32000)
        is_text_type = t in ("text", "callout")
        self._card_typography.setVisible(is_text_type)
        self._row_container_shape_widget.setVisible(t == "text")
        if is_text_type:
            font_fam = style.get("font_family", "sans-serif")
            idx_fam = self._combo_font_family.findText(font_fam)
            self._combo_font_family.setCurrentIndex(idx_fam if idx_fam != -1 else 0)

            font_sz = int(float(style.get("font_size", 11)))
            self._spin_font_size.blockSignals(True)
            self._spin_font_size.setValue(max(6, min(72, font_sz)))
            self._spin_font_size.blockSignals(False)

            self._btn_bold.blockSignals(True)
            self._btn_bold.setChecked(bool(style.get("font_bold", False)))
            self._btn_bold.blockSignals(False)

            self._btn_italic.blockSignals(True)
            self._btn_italic.setChecked(bool(style.get("font_italic", False)))
            self._btn_italic.blockSignals(False)

            align = str(style.get("text_align", "left")).lower()
            self._btn_align_left.blockSignals(True)
            self._btn_align_center.blockSignals(True)
            self._btn_align_right.blockSignals(True)
            self._btn_align_left.setChecked(align == "left")
            self._btn_align_center.setChecked(align == "center")
            self._btn_align_right.setChecked(align == "right")
            self._btn_align_left.blockSignals(False)
            self._btn_align_center.blockSignals(False)
            self._btn_align_right.blockSignals(False)

            tc = style.get("text_color", "#FFFFFF")
            self._btn_text_color.set_color(tc)

            # Figura del contenedor: visible exclusivamente para FreeText (t == "text")
            is_freetext = (t == "text")
            self._row_container_shape_widget.setVisible(is_freetext)
            if is_freetext:
                shape = style.get("shape", "rect")
                if shape == "ellipse":
                    shape = "circle"
                idx_shape = self._combo_container_shape.findData(shape)
                self._combo_container_shape.blockSignals(True)
                self._combo_container_shape.setCurrentIndex(idx_shape if idx_shape != -1 else 0)
                self._combo_container_shape.blockSignals(False)

        self._style_before_slider = copy.deepcopy(style)

        stroke_w = int(float(style.get("stroke_width", 2.0)))
        self._slider_width.blockSignals(True)
        self._slider_width.setValue(stroke_w)
        self._slider_width.blockSignals(False)
        self._spin_width.blockSignals(True)
        self._spin_width.setValue(stroke_w)
        self._spin_width.blockSignals(False)
        stroke_col = style.get("stroke_color", "#EC4899")
        self._current_stroke_color = stroke_col
        self._update_stroke_swatch_selection(stroke_col)

        fill_col = style.get("fill_color", "transparent")
        self._current_fill_base_color = style.get("fill_base_color", style.get("stroke_color", "#EC4899"))
        if not fill_col or fill_col == "transparent":
            self._slider_fill_opacity.blockSignals(True)
            self._slider_fill_opacity.setValue(0)
            self._slider_fill_opacity.blockSignals(False)
            self._spin_fill_opacity.blockSignals(True)
            self._spin_fill_opacity.setValue(0)
            self._spin_fill_opacity.blockSignals(False)
        elif fill_col.startswith("rgba"):
            try:
                parts = fill_col.replace("rgba(", "").replace(")", "").split(",")
                r = int(parts[0].strip())
                g = int(parts[1].strip())
                b = int(parts[2].strip())
                a = float(parts[3].strip())
                pct = int(round(a * 100)) if a <= 1.0 else int(a)
                self._current_fill_base_color = f"#{r:02x}{g:02x}{b:02x}"
                self._slider_fill_opacity.blockSignals(True)
                self._slider_fill_opacity.setValue(pct)
                self._slider_fill_opacity.blockSignals(False)
                self._spin_fill_opacity.blockSignals(True)
                self._spin_fill_opacity.setValue(pct)
                self._spin_fill_opacity.blockSignals(False)
            except Exception:
                self._slider_fill_opacity.blockSignals(True)
                self._slider_fill_opacity.setValue(30)
                self._slider_fill_opacity.blockSignals(False)
                self._spin_fill_opacity.blockSignals(True)
                self._spin_fill_opacity.setValue(30)
                self._spin_fill_opacity.blockSignals(False)
        else:
            c = QColor(fill_col)
            if c.isValid():
                self._current_fill_base_color = c.name()
                pct = int(round((c.alpha() / 255.0) * 100))
                self._slider_fill_opacity.blockSignals(True)
                self._slider_fill_opacity.setValue(pct)
                self._slider_fill_opacity.blockSignals(False)
                self._spin_fill_opacity.blockSignals(True)
                self._spin_fill_opacity.setValue(pct)
                self._spin_fill_opacity.blockSignals(False)
            else:
                self._slider_fill_opacity.blockSignals(True)
                self._slider_fill_opacity.setValue(0)
                self._slider_fill_opacity.blockSignals(False)
                self._spin_fill_opacity.blockSignals(True)
                self._spin_fill_opacity.setValue(0)
                self._spin_fill_opacity.blockSignals(False)

        # Mostrar/ocultar control de tamaño de fuente
        self._update_fill_swatch_selection(fill_col, self._current_fill_base_color)
        is_text = t in ("text", "callout")
        for i in range(self._row_font.count()):
            w = self._row_font.itemAt(i).widget()
            if w:
                w.setVisible(is_text)

        if is_text:
            f_size = int(float(style.get("font_size", 11.0)))
            self._slider_font.blockSignals(True)
            self._slider_font.setValue(f_size)
            self._slider_font.blockSignals(False)
            self._spin_font.blockSignals(True)
            self._spin_font.setValue(f_size)
            self._spin_font.blockSignals(False)

        # 4. Tags
        self._render_tags(annot_data.get("tags", []))

        # 5. Propiedades Clave-Valor
        props = annot_data.get("properties", {})
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except Exception:
                props = {}
        self._render_properties_table(props)

        self._stack.setCurrentIndex(1)
        self._is_loading = False

    def refresh_if_current(self, annot_id: str, updated_data: dict):
        """Actualiza los datos si la anotación abierta es la que se acaba de modificar (Undo/Redo)."""
        if self._current_annot_id == annot_id:
            merged = copy.deepcopy(self._current_data or {})
            merged.update(updated_data)
            self.load_annotation(merged)

    def _render_tags(self, tags: list):
        """Dibuja los chips de etiquetas con botón para remover."""
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tag_list = list(tags) if isinstance(tags, (list, tuple)) else []
        for tag in tag_list:
            chip = QFrame(self._tags_container)
            chip.setObjectName("tagChip")
            chip_lay = QHBoxLayout(chip)
            chip_lay.setContentsMargins(6, 2, 4, 2)
            chip_lay.setSpacing(4)

            lbl = QLabel(str(tag), chip)
            lbl.setObjectName("tagChipLabel")
            chip_lay.addWidget(lbl)

            btn_del = QToolButton(chip)
            btn_del.setObjectName("tagChipRemove")
            btn_del.setText("✕")
            btn_del.setFixedSize(14, 14)
            btn_del.clicked.connect(lambda _, t_val=tag: self._remove_tag(t_val))
            chip_lay.addWidget(btn_del)

            self._tags_layout.addWidget(chip)

    def _add_tag(self):
        new_tag = self._in_tag.text().strip()
        if not new_tag or not self._current_data:
            return
        old_tags = list(self._current_data.get("tags", []))
        if new_tag not in old_tags:
            new_tags = old_tags + [new_tag]
            self._current_data["tags"] = new_tags
            self._render_tags(new_tags)
            self._in_tag.clear()
            self._emit_modified({"tags": old_tags}, {"tags": new_tags})

    def _remove_tag(self, tag_to_remove: str):
        if not self._current_data:
            return
        old_tags = list(self._current_data.get("tags", []))
        if tag_to_remove in old_tags:
            new_tags = [t for t in old_tags if t != tag_to_remove]
            self._current_data["tags"] = new_tags
            self._render_tags(new_tags)
            self._emit_modified({"tags": old_tags}, {"tags": new_tags})

    # ------------------------------------------------------------------
    # Propiedades Multi-Valor (Key → [v1, v2, ...])
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_props(raw: dict) -> dict:
        """Asegura que cada clave tenga una lista de valores (retrocompat. str/int → list)."""
        normalized = {}
        for k, v in raw.items():
            if isinstance(v, list):
                normalized[k] = [str(i) for i in v]
            else:
                normalized[k] = [str(v)] if v != "" else []
        return normalized

    def _rebuild_table_columns(self, n_vals: int):
        """Ajusta el número de columnas: 1 (Clave) + n_vals (valores) + 1 (acciones)."""
        n_cols = 1 + n_vals + 1
        self._tbl_props.setColumnCount(n_cols)
        headers = ["Clave"] + [f"Valor {i+1}" for i in range(n_vals)] + [""]
        self._tbl_props.setHorizontalHeaderLabels(headers)
        hh = self._tbl_props.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c_idx in range(1, n_vals + 1):
            hh.setSectionResizeMode(c_idx, QHeaderView.ResizeMode.Stretch)
        # Actions column: fixed narrow
        hh.setSectionResizeMode(n_cols - 1, QHeaderView.ResizeMode.Fixed)
        self._tbl_props.setColumnWidth(n_cols - 1, 48)

    def _render_properties_table(self, props: dict):
        """Puebla la tabla multi-columna de propiedades técnicas."""
        self._tbl_props.setCurrentCell(-1, -1)
        self._tbl_props.clearSelection()
        self._tbl_props.blockSignals(True)
        self._tbl_props.setRowCount(0)
        norm = self._normalize_props(props)
        # Compute max values across all keys (at least 1)
        max_vals = max((len(v) for v in norm.values()), default=1)
        max_vals = max(max_vals, 1)
        self._rebuild_table_columns(max_vals)
        n_cols = self._tbl_props.columnCount()
        action_col = n_cols - 1

        for row_idx, (key, values) in enumerate(norm.items()):
            self._tbl_props.insertRow(row_idx)
            # Col 0: key
            self._tbl_props.setItem(row_idx, 0, QTableWidgetItem(key))
            # Cols 1..max_vals: values
            for v_idx, val in enumerate(values):
                self._tbl_props.setItem(row_idx, 1 + v_idx, QTableWidgetItem(val))
            # Empty cells for remaining value cols
            for v_idx in range(len(values), max_vals):
                self._tbl_props.setItem(row_idx, 1 + v_idx, QTableWidgetItem(""))
            # Actions col: "+" add value | "✕" delete row
            btn_w = QWidget()
            btn_lay = QHBoxLayout(btn_w)
            btn_lay.setContentsMargins(2, 0, 2, 0)
            btn_lay.setSpacing(2)
            btn_add_v = QToolButton()
            btn_add_v.setText("+")
            btn_add_v.setFixedSize(22, 22)
            btn_add_v.setToolTip("Agregar valor adicional")
            btn_add_v.clicked.connect(lambda _=False, k=key: self._add_value_to_key(k))
            btn_del = QToolButton()
            btn_del.setText("✕")
            btn_del.setFixedSize(22, 22)
            btn_del.setToolTip("Eliminar propiedad")
            btn_del.clicked.connect(lambda _=False, k=key: self._delete_property_key(k))
            btn_lay.addWidget(btn_add_v)
            btn_lay.addWidget(btn_del)
            self._tbl_props.setCellWidget(row_idx, action_col, btn_w)

        self._tbl_props.blockSignals(False)

    def _collect_props_from_table(self) -> dict:
        """Reconstruye {key: [v1, v2, ...]} desde la tabla."""
        result = {}
        n_cols = self._tbl_props.columnCount()
        action_col = n_cols - 1
        for r in range(self._tbl_props.rowCount()):
            k_item = self._tbl_props.item(r, 0)
            if not k_item or not k_item.text().strip():
                continue
            key = k_item.text().strip()
            values = []
            for c_idx in range(1, action_col):
                v_item = self._tbl_props.item(r, c_idx)
                v = v_item.text().strip() if v_item else ""
                if v:
                    values.append(v)
            result[key] = values
        return result

    def _on_property_cell_changed(self, row: int, col: int):
        if self._is_loading or not self._current_data:
            return
        old_props = copy.deepcopy(self._current_data.get("properties", {}))
        new_props = self._collect_props_from_table()
        self._current_data["properties"] = new_props
        self._emit_modified({"properties": old_props}, {"properties": new_props})

    def _add_custom_property(self):
        k = self._in_prop_key.text().strip()
        v1 = self._in_prop_val.text().strip()
        v2 = self._in_prop_val2.text().strip()
        if not k or not self._current_data:
            return
        old_props = copy.deepcopy(self._current_data.get("properties", {}))
        new_props = self._normalize_props(dict(old_props))
        values = [x for x in [v1, v2] if x]
        if k in new_props:
            for v in values:
                if v not in new_props[k]:
                    new_props[k].append(v)
        else:
            new_props[k] = values
        self._current_data["properties"] = new_props
        self._render_properties_table(new_props)
        self._in_prop_key.clear()
        self._in_prop_val.clear()
        self._in_prop_val2.clear()
        self._emit_modified({"properties": old_props}, {"properties": new_props})

    def _add_value_to_key(self, key: str):
        """Agrega una columna de valor vacía editable a una clave existente."""
        if not self._current_data:
            return
        old_props = copy.deepcopy(self._current_data.get("properties", {}))
        new_props = self._normalize_props(dict(old_props))
        if key not in new_props:
            return
        new_props[key].append("")  # empty value placeholder
        self._current_data["properties"] = new_props
        self._render_properties_table(new_props)
        self._emit_modified({"properties": old_props}, {"properties": new_props})

    def _delete_property_key(self, key: str):
        """Elimina una clave completa con todos sus valores."""
        if not self._current_data:
            return
        old_props = copy.deepcopy(self._current_data.get("properties", {}))
        new_props = self._normalize_props(dict(old_props))
        new_props.pop(key, None)
        self._current_data["properties"] = new_props
        self._render_properties_table(new_props)
        self._emit_modified({"properties": old_props}, {"properties": new_props})


    def _on_subject_changed(self):
        if self._is_loading:
            return
        val = self._txt_subject.text().strip()
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"subject": val, "/Subj": val})
            return
        if not self._current_data:
            return
        old_val = self._current_data.get("subject") or self._current_data.get("/Subj") or ""
        if val != old_val:
            self._current_data["subject"] = val
            self._current_data["/Subj"] = val
            self._emit_modified({"subject": old_val, "/Subj": old_val}, {"subject": val, "/Subj": val})

    def _on_layer_changed(self, layer: str):
        if self._is_loading:
            return
        val = layer.strip()
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"layer": val, "/OC": val, "discipline": val})
            return
        if not self._current_data:
            return
        old_layer = self._current_data.get("layer") or self._current_data.get("/OC") or self._current_data.get("discipline") or "General"
        if old_layer != val:
            self._current_data["layer"] = val
            self._current_data["/OC"] = val
            self._current_data["discipline"] = val
            self._emit_modified(
                {"layer": old_layer, "/OC": old_layer, "discipline": old_layer},
                {"layer": val, "/OC": val, "discipline": val}
            )

    def _on_discipline_changed(self, disc: str):
        self._on_layer_changed(disc)

    def _on_author_changed(self):
        if self._is_loading:
            return
        val = self._txt_author.text().strip()
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"author": val, "/T": val})
            return
        if not self._current_data:
            return
        old_val = self._current_data.get("author") or self._current_data.get("/T") or "Usuario"
        if val != old_val:
            self._current_data["author"] = val
            self._current_data["/T"] = val
            self._emit_modified({"author": old_val, "/T": old_val}, {"author": val, "/T": val})

    def _on_status_changed(self, status: str):
        if self._is_loading:
            return
        val = status.strip()
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"status": val, "/State": val, "/StateModel": "Review"})
            return
        if not self._current_data:
            return
        old_status = self._current_data.get("status") or self._current_data.get("/State") or "None"
        if old_status != val:
            self._current_data["status"] = val
            self._current_data["/State"] = val
            self._current_data["/StateModel"] = "Review"
            self._emit_modified(
                {"status": old_status, "/State": old_status},
                {"status": val, "/State": val, "/StateModel": "Review"}
            )

    def _on_content_changed(self):
        if self._is_loading or not self._current_data:
            return
        new_content = self._txt_content.toPlainText()
        self._current_data["content"] = new_content
        self._current_data["/Contents"] = new_content
        self.preview_modified.emit(self._current_annot_id, {"content": new_content, "/Contents": new_content})
        self._content_timer.start(600)

    def _on_content_timer_timeout(self):
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            new_c = self._txt_content.toPlainText()
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"content": new_c, "/Contents": new_c})
            return
        if not self._current_data or not self._current_annot_id:
            return
        new_content = self._txt_content.toPlainText()
        old_content = getattr(self, "_content_before_edit", "")
        if new_content != old_content:
            self._content_before_edit = new_content
            self._emit_modified(
                {"content": old_content, "/Contents": old_content},
                {"content": new_content, "/Contents": new_content}
            )

    def _on_font_family_changed(self, family: str):
        if self._is_loading:
            return
        self._update_style_field("font_family", family)

    def _on_typography_font_size_changed(self, size: int):
        if hasattr(self, "_slider_font"):
            self._slider_font.blockSignals(True)
            self._slider_font.setValue(size)
            self._slider_font.blockSignals(False)
        if hasattr(self, "_spin_font"):
            self._spin_font.blockSignals(True)
            self._spin_font.setValue(size)
            self._spin_font.blockSignals(False)
        if self._is_loading:
            return
        self._update_style_field("font_size", float(size))

    def _on_font_bold_toggled(self, bold: bool):
        if self._is_loading:
            return
        self._update_style_field("font_bold", bool(bold))

    def _on_font_italic_toggled(self, italic: bool):
        if self._is_loading:
            return
        self._update_style_field("font_italic", bool(italic))

    def _on_text_align_selected(self, align: str):
        self._btn_align_left.blockSignals(True)
        self._btn_align_center.blockSignals(True)
        self._btn_align_right.blockSignals(True)
        self._btn_align_left.setChecked(align == "left")
        self._btn_align_center.setChecked(align == "center")
        self._btn_align_right.setChecked(align == "right")
        self._btn_align_left.blockSignals(False)
        self._btn_align_center.blockSignals(False)
        self._btn_align_right.blockSignals(False)

        if self._is_loading:
            return
        # ISO /Q mapping: 0=left, 1=center, 2=right
        q_val = 1 if align == "center" else (2 if align == "right" else 0)
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"style": {"text_align": align, "/Q": q_val}})
            if hasattr(self, "_multi_annot_data"):
                for a in self._multi_annot_data:
                    st = a.setdefault("style", {})
                    if isinstance(st, dict):
                        st["text_align"] = align
                        st["/Q"] = q_val
            return
        if not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style["text_align"] = align
        new_style["/Q"] = q_val
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _on_container_shape_changed(self, idx: int):
        if self._is_loading:
            return
        shape = self._combo_container_shape.itemData(idx) or self._combo_container_shape.currentData() or "rect"
        self._update_style_field("shape", shape)

    def _pick_text_color(self):
        initial = QColor(self._current_data.get("style", {}).get("text_color", "#FFFFFF") if self._current_data else "#FFFFFF")
        col = QColorDialog.getColor(initial, self, "Seleccionar Color de Texto")
        if col.isValid():
            hex_color = col.name()
            self._btn_text_color.set_color(hex_color)
            self._update_style_field("text_color", hex_color)

    def _update_style_field(self, key: str, value: Any):
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"style": {key: value}})
            if hasattr(self, "_multi_annot_data"):
                for a in self._multi_annot_data:
                    st = a.setdefault("style", {})
                    if isinstance(st, dict):
                        st[key] = value
            return
        if not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style[key] = value
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _on_stroke_color_selected(self, hex_color: str):
        if not hex_color:
            return
        self._current_stroke_color = hex_color
        self._update_stroke_swatch_selection(hex_color)
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self._update_style_field("stroke_color", hex_color)
            return
        if not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style["stroke_color"] = hex_color
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _pick_custom_stroke_color(self):
        initial = QColor(getattr(self, "_current_stroke_color", "#EC4899"))
        col = QColorDialog.getColor(initial, self, "Seleccionar Color de Trazo")
        if col.isValid():
            self._on_stroke_color_selected(col.name())

    def _on_slider_pressed(self):
        if self._current_data:
            self._style_before_slider = copy.deepcopy(self._current_data.get("style", {}))

    def _on_slider_released(self):
        if not self._current_data or not self._current_annot_id:
            return
        old_style = getattr(self, "_style_before_slider", None)
        current_style = copy.deepcopy(self._current_data.get("style", {}))
        if old_style is not None and old_style != current_style:
            self._emit_modified({"style": old_style}, {"style": current_style})
            self._style_before_slider = copy.deepcopy(current_style)

    def _on_stroke_width_changed(self, val: int):
        self._spin_width.blockSignals(True)
        self._spin_width.setValue(val)
        self._spin_width.blockSignals(False)
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self._update_style_field("stroke_width", float(val))
            return
        if not self._current_data:
            return
        style = dict(self._current_data.get("style", {}))
        style["stroke_width"] = float(val)
        self._current_data["style"] = style
        self.preview_modified.emit(self._current_annot_id, {"style": style})

    def _on_spin_width_changed(self, val: int):
        self._slider_width.blockSignals(True)
        self._slider_width.setValue(val)
        self._slider_width.blockSignals(False)
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self._update_style_field("stroke_width", float(val))
            return
        if not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style["stroke_width"] = float(val)
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _on_no_fill_selected(self):
        self._slider_fill_opacity.blockSignals(True)
        self._slider_fill_opacity.setValue(0)
        self._slider_fill_opacity.blockSignals(False)
        self._spin_fill_opacity.blockSignals(True)
        self._spin_fill_opacity.setValue(0)
        self._spin_fill_opacity.blockSignals(False)
        self._update_fill_swatch_selection("transparent", getattr(self, "_current_fill_base_color", ""))
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            fill_update = {"fill_color": "transparent", "fill_opacity": 0.0}
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"style": fill_update})
            if hasattr(self, "_multi_annot_data"):
                for a in self._multi_annot_data:
                    st = a.setdefault("style", {})
                    if isinstance(st, dict):
                        st.update(fill_update)
            return
        if not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style["fill_color"] = "transparent"
        new_style["fill_opacity"] = 0.0
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _on_fill_color_selected(self, hex_color: str):
        if not hex_color:
            return
        self._current_fill_base_color = hex_color
        current_op = self._slider_fill_opacity.value()
        if current_op == 0:
            current_op = 30
            self._slider_fill_opacity.blockSignals(True)
            self._slider_fill_opacity.setValue(30)
            self._slider_fill_opacity.blockSignals(False)
            self._spin_fill_opacity.blockSignals(True)
            self._spin_fill_opacity.setValue(30)
            self._spin_fill_opacity.blockSignals(False)
        c = QColor(hex_color)
        alpha_f = current_op / 100.0
        new_fill_str = f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_f:.2f})"
        self._update_fill_swatch_selection(new_fill_str, hex_color)

        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            fill_update = {
                "fill_color": new_fill_str,
                "fill_opacity": alpha_f,
                "fill_base_color": hex_color,
            }
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"style": fill_update})
            if hasattr(self, "_multi_annot_data"):
                for a in self._multi_annot_data:
                    st = a.setdefault("style", {})
                    if isinstance(st, dict):
                        st.update(fill_update)
            return
        if not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style["fill_color"] = new_fill_str
        new_style["fill_opacity"] = alpha_f
        new_style["fill_base_color"] = hex_color
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _pick_custom_fill_color(self):
        initial = QColor(getattr(self, "_current_fill_base_color", "#EC4899"))
        col = QColorDialog.getColor(initial, self, "Seleccionar Color de Fondo")
        if col.isValid():
            self._on_fill_color_selected(col.name())

    def _on_fill_opacity_changed(self, val: int):
        self._spin_fill_opacity.blockSignals(True)
        self._spin_fill_opacity.setValue(val)
        self._spin_fill_opacity.blockSignals(False)
        base_color = getattr(self, "_current_fill_base_color", None)
        if not base_color:
            style = self._current_data.get("style", {}) if self._current_data else {}
            base_color = style.get("stroke_color", "#EC4899")
            self._current_fill_base_color = base_color

        if val <= 0:
            self._update_fill_swatch_selection("transparent", base_color)
        else:
            self._update_fill_swatch_selection("rgba", base_color)

        if self._is_loading:
            return

        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            if val <= 0:
                fill_update = {"fill_color": "transparent", "fill_opacity": 0.0}
            else:
                c = QColor(base_color)
                alpha_f = val / 100.0
                fill_update = {
                    "fill_color": f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_f:.2f})",
                    "fill_opacity": alpha_f,
                    "fill_base_color": base_color,
                }
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"style": fill_update})
            if hasattr(self, "_multi_annot_data"):
                for a in self._multi_annot_data:
                    st = a.setdefault("style", {})
                    if isinstance(st, dict):
                        st.update(fill_update)
            return

        if not self._current_data:
            return

        style = dict(self._current_data.get("style", {}))
        if val <= 0:
            style["fill_color"] = "transparent"
            style["fill_opacity"] = 0.0
        else:
            c = QColor(base_color)
            alpha_f = val / 100.0
            style["fill_color"] = f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_f:.2f})"
            style["fill_opacity"] = alpha_f
            style["fill_base_color"] = base_color
        self._current_data["style"] = style
        self.preview_modified.emit(self._current_annot_id, {"style": style})

    def _on_spin_fill_opacity_changed(self, val: int):
        self._slider_fill_opacity.blockSignals(True)
        self._slider_fill_opacity.setValue(val)
        self._slider_fill_opacity.blockSignals(False)
        base_color = getattr(self, "_current_fill_base_color", None)
        if not base_color:
            style = self._current_data.get("style", {}) if self._current_data else {}
            base_color = style.get("stroke_color", "#EC4899")
            self._current_fill_base_color = base_color

        if val <= 0:
            self._update_fill_swatch_selection("transparent", base_color)
        else:
            self._update_fill_swatch_selection("rgba", base_color)

        if self._is_loading:
            return

        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            if val <= 0:
                fill_update = {"fill_color": "transparent", "fill_opacity": 0.0}
            else:
                c = QColor(base_color)
                alpha_f = val / 100.0
                fill_update = {
                    "fill_color": f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_f:.2f})",
                    "fill_opacity": alpha_f,
                    "fill_base_color": base_color,
                }
            self.multi_annotations_modified.emit(self._multi_annot_ids, {"style": fill_update})
            if hasattr(self, "_multi_annot_data"):
                for a in self._multi_annot_data:
                    st = a.setdefault("style", {})
                    if isinstance(st, dict):
                        st.update(fill_update)
            return

        if not self._current_data:
            return

        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        if val <= 0:
            new_style["fill_color"] = "transparent"
            new_style["fill_opacity"] = 0.0
        else:
            c = QColor(base_color)
            alpha_f = val / 100.0
            new_style["fill_color"] = f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_f:.2f})"
            new_style["fill_opacity"] = alpha_f
            new_style["fill_base_color"] = base_color
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _update_stroke_swatch_selection(self, hex_color: str):
        """Resalta el swatch de trazo seleccionado o el botón de más colores."""
        if not hex_color or not hasattr(self, "_stroke_color_buttons"):
            return

        hex_norm = hex_color.upper()
        found_in_palette = False

        for color, btn in self._stroke_color_buttons.items():
            is_active = color.upper() == hex_norm
            btn.set_selected(is_active)
            found_in_palette = found_in_palette or is_active

        if hasattr(self, "_btn_custom_stroke"):
            if not found_in_palette:
                self._btn_custom_stroke.set_dashed(False)
                self._btn_custom_stroke.set_color(hex_color)
                self._btn_custom_stroke.set_selected(True)
                self._btn_custom_stroke.set_badge_text("✓")
                self._btn_custom_stroke.setToolTip(
                    f"Color de trazo personalizado: {hex_color}\nClic para elegir otro..."
                )
            else:
                self._btn_custom_stroke.set_dashed(True)
                self._btn_custom_stroke.set_color(None)
                self._btn_custom_stroke.set_selected(False)
                self._btn_custom_stroke.set_badge_text("+")
                self._btn_custom_stroke.setToolTip("Seleccionar más colores de trazo...")

    def _update_fill_swatch_selection(self, fill_col: str, base_hex: str):
        """Resalta el swatch de fondo seleccionado o el botón de más colores."""
        if not hasattr(self, "_fill_color_buttons"):
            return
        is_transparent = (
            not fill_col
            or fill_col == "transparent"
            or (hasattr(self, "_slider_fill_opacity") and self._slider_fill_opacity.value() == 0)
        )

        if hasattr(self, "_btn_no_fill"):
            self._btn_no_fill.set_selected(is_transparent)

        found_in_palette = False
        base_norm = (base_hex or "").upper()
        for color, btn in self._fill_color_buttons.items():
            is_active = not is_transparent and color.upper() == base_norm
            btn.set_selected(is_active)
            found_in_palette = found_in_palette or is_active

        if hasattr(self, "_btn_custom_fill"):
            custom_active = not is_transparent and not found_in_palette and bool(base_hex)
            if custom_active:
                self._btn_custom_fill.set_dashed(False)
                self._btn_custom_fill.set_color(base_hex)
                self._btn_custom_fill.set_selected(True)
                self._btn_custom_fill.set_badge_text("✓")
                self._btn_custom_fill.setToolTip(
                    f"Color de fondo personalizado: {base_hex}\nClic para elegir otro..."
                )
            else:
                self._btn_custom_fill.set_dashed(True)
                self._btn_custom_fill.set_color(None)
                self._btn_custom_fill.set_selected(False)
                self._btn_custom_fill.set_badge_text("+")
                self._btn_custom_fill.setToolTip("Seleccionar más colores de fondo...")

    def _on_font_size_changed(self, val: int):
        self._spin_font.blockSignals(True)
        self._spin_font.setValue(val)
        self._spin_font.blockSignals(False)
        if self._is_loading or not self._current_data:
            return
        style = dict(self._current_data.get("style", {}))
        style["font_size"] = float(val)
        self._current_data["style"] = style
        self.preview_modified.emit(self._current_annot_id, {"style": style})

    def _on_spin_font_changed(self, val: int):
        self._slider_font.blockSignals(True)
        self._slider_font.setValue(val)
        self._slider_font.blockSignals(False)
        if self._is_loading or not self._current_data:
            return
        old_style = copy.deepcopy(self._current_data.get("style", {}))
        new_style = copy.deepcopy(old_style)
        new_style["font_size"] = float(val)
        self._current_data["style"] = new_style
        self._emit_modified({"style": old_style}, {"style": new_style})

    def _copy_id_to_clipboard(self):
        if self._current_annot_id:
            QApplication.clipboard().setText(self._current_annot_id)

    def _save_tool_defaults(self, tool_id: str):
        """Persiste los defaults del tipo de herramienta en settings de la app."""
        if not tool_id:
            return
        from core.settings import settings
        saved = settings.get("annotations.tool_defaults", {})
        if not isinstance(saved, dict):
            saved = {}
        tool_data = self._tool_defaults.get(tool_id, {})
        persist_data = {}
        if "style" in tool_data and isinstance(tool_data["style"], dict):
            persist_data["style"] = copy.deepcopy(tool_data["style"])
        if "discipline" in tool_data:
            persist_data["discipline"] = tool_data["discipline"]
        if "tags" in tool_data and isinstance(tool_data["tags"], list):
            persist_data["tags"] = copy.deepcopy(tool_data["tags"])
        saved[tool_id] = persist_data
        settings.set("annotations.tool_defaults", saved)

    def update_tool_defaults(self, tool_id: str, updates: dict):
        """Actualiza y persiste en SettingsManager los defaults para un tipo de herramienta."""
        if not tool_id:
            return
        defaults = self._tool_defaults.setdefault(tool_id, {})
        for k, v in updates.items():
            if k == "style" and isinstance(v, dict):
                current_st = defaults.setdefault("style", {})
                current_st.update(v)
            else:
                defaults[k] = copy.deepcopy(v)
        self._save_tool_defaults(tool_id)

    def _emit_modified(self, old_state: dict, new_state: dict):
        if self._is_loading:
            return
        if getattr(self, "_multi_annot_ids", None) and len(self._multi_annot_ids) > 1:
            self.multi_annotations_modified.emit(self._multi_annot_ids, new_state)
            return
        if self._is_template_mode:
            # En modo plantilla: actualizar defaults y notificar
            tool_id = self._current_annot_id or ""  # usamos annot_id para guardar el tool_id
            if tool_id:
                defaults = self._tool_defaults.setdefault(tool_id, {})
                defaults.update(new_state)
                self._save_tool_defaults(tool_id)
                self.template_defaults_changed.emit(tool_id, dict(defaults))
        elif self._current_annot_id:
            self.annotation_modified.emit(self._current_annot_id, old_state, new_state)
            # Sincronizar estilo como último usado para la herramienta
            if self._current_data:
                t = self._current_data.get("type")
                if t and t in self._TOOL_TYPE_MAP:
                    defaults = self._tool_defaults.setdefault(t, {})
                    if "style" in new_state and isinstance(new_state["style"], dict):
                        st = defaults.setdefault("style", {})
                        st.update(new_state["style"])
                    if "discipline" in new_state:
                        defaults["discipline"] = new_state["discipline"]
                    self._save_tool_defaults(t)

    # ------------------------------------------------------------------
    # Modo Plantilla: carga propiedades del tipo de herramienta antes de dibujar
    # ------------------------------------------------------------------

    # Defaults visuales por tipo de herramienta
    _TOOL_TYPE_MAP = {
        "rect":    "rect",
        "circle":  "circle",
        "cloud":   "cloud",
        "line":    "line",
        "arrow":   "arrow",
        "text":    "text",
        "callout": "callout",
    }

    _TOOL_DEFAULT_STYLE: dict[str, dict] = {
        "rect":    {"stroke_color": "#3B82F6", "stroke_width": 2.0, "fill_color": "#3B82F6", "fill_opacity": 0.08},
        "circle":  {"stroke_color": "#10B981", "stroke_width": 2.0, "fill_color": "#10B981", "fill_opacity": 0.08},
        "cloud":   {"stroke_color": "#F59E0B", "stroke_width": 2.0, "fill_color": "#F59E0B", "fill_opacity": 0.08},
        "line":    {"stroke_color": "#64748B", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.0},
        "arrow":   {"stroke_color": "#64748B", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.0},
        "text":    {"stroke_color": "#1E293B", "stroke_width": 1.0, "fill_color": "transparent", "fill_opacity": 0.0, "font_size": 12, "shape": "rect"},
        "callout": {"stroke_color": "#8B5CF6", "stroke_width": 2.0, "fill_color": "#8B5CF6", "fill_opacity": 0.08, "font_size": 11},
    }

    def load_tool_template(self, tool_id: str):
        """Muestra el panel de propiedades con defaults del tipo de herramienta.

        Permite al usuario configurar estilo, disciplina y metadatos ANTES de
        dibujar la anotación. Los cambios se guardan como defaults persistentes
        que se aplican automáticamente a cada nueva anotación del mismo tipo.
        """
        if tool_id not in self._TOOL_TYPE_MAP:
            # Herramienta sin configuración (select, pan…) → mostrar página vacía
            self._is_template_mode = False
            self.load_annotation(None)
            return

        annot_type = self._TOOL_TYPE_MAP[tool_id]
        # Recuperar defaults guardados (settings de la app o memoria)
        saved = self.get_tool_defaults(tool_id)
        base_style = dict(self._TOOL_DEFAULT_STYLE.get(tool_id, {}))
        base_style.update(saved.get("style", {}))

        template = {
            "id": tool_id,           # usamos tool_id como ID para identificar el template
            "type": annot_type,
            "content": saved.get("content", ""),
            "geometry": {},
            "style": base_style,
            "tags": saved.get("tags", []),
            "properties": saved.get("properties", {}),
            "discipline": saved.get("discipline", "General"),
            "author": "Usuario",
            "_is_template": True,    # marca interna para distinguirlo de anotaciones reales
        }

        self._is_template_mode = True
        self.load_annotation(template)

    def get_tool_defaults(self, tool_id: str) -> dict:
        """Retorna el dict de defaults acumulados para un tipo de herramienta (desde memoria o settings)."""
        if tool_id in self._tool_defaults and self._tool_defaults[tool_id]:
            return copy.deepcopy(self._tool_defaults[tool_id])
        from core.settings import settings
        saved = settings.get(f"annotations.tool_defaults.{tool_id}")
        if isinstance(saved, dict) and saved:
            self._tool_defaults[tool_id] = copy.deepcopy(saved)
            return copy.deepcopy(saved)
        base_style = dict(self._TOOL_DEFAULT_STYLE.get(tool_id, {}))
        return {"style": base_style, "discipline": "General"}

    def apply_theme(self):
        """Actualiza los elementos dinámicos tras un cambio de tema."""
        # El estilo estático vive centralizado en ui/styles/theme.qss (Regla 4);
        # aquí solo se refrescan los elementos pintados/dependientes del tema.
        if hasattr(self, "_current_stroke_color"):
            self._update_stroke_swatch_selection(self._current_stroke_color)
        if hasattr(self, "_current_data") and self._current_data:
            st = self._current_data.get("style", {})
            self._update_fill_swatch_selection(st.get("fill_color", "transparent"), getattr(self, "_current_fill_base_color", ""))
        self._lbl_title_icon.setPixmap(ThemeManager.get_icon("edit").pixmap(18, 18))
        self._btn_close.setIcon(ThemeManager.get_icon("close"))
        self._btn_copy_id.setIcon(ThemeManager.get_icon("copy"))
        self._btn_dup.setIcon(ThemeManager.get_icon("duplicate"))
        self._btn_del.setIcon(ThemeManager.get_icon("trash"))
