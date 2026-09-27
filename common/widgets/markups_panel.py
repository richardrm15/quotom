"""
Panel Inferior de Tabla de Anotaciones y Marcas (Markups List / Annotations Table).

Proporciona una vista tabular de alta densidad y rendimiento de todas las
marcas y anotaciones del plano (estilo Bluebeam Revu / CAD Takeoff):
- Sincronización bidireccional inmediata con el canvas gráfico.
- Filtros por texto libre, ámbito (página actual / todo el plano) y especialidad.
- Ordenación por columnas mediante QSortFilterProxyModel.
- Exportación directa a CSV / Excel.
"""

import csv
from PySide6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Signal,
    QSize,
    QRectF,
    QPointF,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QBrush,
    QPen,
    QPixmap,
    QIcon,
    QKeySequence,
    QFont,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QToolButton,
    QMenu,
    QHeaderView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QFileDialog,
    QMessageBox,
)

from ui.styles.style_manager import ThemeManager


def parse_color(c, default=None):
    if default is None:
        default = QColor("#0284C7")
    if not c or c == "transparent":
        return QColor(Qt.GlobalColor.transparent)
    col = QColor(c)
    return col if col.isValid() else default

TYPE_LABELS = {
    "line": "Línea simple",
    "arrow": "Flecha directriz",
    "rect": "Rectángulo",
    "circle": "Círculo",
    "cloud": "Nube de revisión",
    "text": "Texto libre",
    "callout": "Llamada con flecha",
}

STATUS_COLORS = {
    "Aprobado": "#10B981",
    "Completado": "#059669",
    "Pendiente": "#F59E0B",
    "Rechazado": "#EF4444",
    "Cancelado": "#64748B",
    "None": "#94A3B8",
}

def format_tags(tags) -> str:
    """Formatea la lista de etiquetas separada por comas."""
    if not tags:
        return ""
    if isinstance(tags, str):
        if tags.startswith("[") and tags.endswith("]"):
            import json
            try:
                tags = json.loads(tags)
            except Exception:
                pass
        else:
            return tags.strip()
    if isinstance(tags, list):
        clean_tags = [str(t).strip() for t in tags if str(t).strip()]
        return ", ".join(clean_tags)
    return str(tags)


def format_properties(props) -> str:
    """Formatea el diccionario de propiedades como clave: valor."""
    if not props:
        return ""
    if isinstance(props, str):
        if props.startswith("{") and props.endswith("}"):
            import json
            try:
                props = json.loads(props)
            except Exception:
                return props.strip()
        else:
            return props.strip()
    if isinstance(props, dict):
        pairs = [f"{k}: {v}" for k, v in props.items() if str(v).strip()]
        if not pairs:
            return ""
        return "{ " + ", ".join(pairs) + " }"
    return str(props)

COL_PAGE_NUM = 0
COL_PAGE_NAME = 1
COL_SUBJECT = 2
COL_CONTENT = 3
COL_LAYER = 4
COL_TAGS = 5
COL_PROPS = 6
COL_AUTHOR = 7
COL_STATUS = 8
COL_DATE = 9

COLUMN_HEADERS = [
    "Nº Pág.",
    "Nombre de Página",
    "Subject",
    "Content",
    "Layer",
    "Etiquetas",
    "Propiedades",
    "Author",
    "Estado",
    "Fecha",
]


class AnnotationsTableModel(QAbstractTableModel):
    """Modelo de datos tabular de solo lectura/virtual para anotaciones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._annotations: list[dict] = []
        self._icon_cache: dict[tuple, QIcon] = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._annotations)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(COLUMN_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(COLUMN_HEADERS):
                return COLUMN_HEADERS[section]
        return None

    def _get_color_icon(self, color_hex: str, annot_type: str = "rect") -> QIcon:
        key = (color_hex, annot_type)
        if key not in self._icon_cache:
            size = 14
            pix = QPixmap(size, size)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            c = parse_color(color_hex, QColor("#0284C7"))
            p.setPen(QPen(c.darker(120), 1.2))
            p.setBrush(QBrush(c))
            radius = size / 2.0 - 1.5
            cx = size / 2.0
            cy = size / 2.0
            if annot_type in ("circle", "ellipse"):
                p.drawEllipse(QPointF(cx, cy), radius, radius)
            elif annot_type == "rect":
                p.drawRoundedRect(QRectF(cx - radius, cy - radius, radius * 2, radius * 2), 2.0, 2.0)
            elif annot_type == "cloud":
                p.drawEllipse(QPointF(cx - 2, cy), radius * 0.7, radius * 0.7)
                p.drawEllipse(QPointF(cx + 2, cy), radius * 0.7, radius * 0.7)
                p.drawEllipse(QPointF(cx, cy - 2), radius * 0.7, radius * 0.7)
            elif annot_type in ("line", "arrow"):
                p.drawLine(QPointF(cx - radius, cy + radius), QPointF(cx + radius, cy - radius))
            else:
                p.drawRoundedRect(QRectF(cx - radius, cy - radius + 1, radius * 2, radius * 1.6), 2.0, 2.0)
            p.end()
            self._icon_cache[key] = QIcon(pix)
        return self._icon_cache[key]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._annotations)):
            return None

        annot = self._annotations[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_PAGE_NUM:
                page_idx = annot.get("page_index", 0)
                return str(page_idx + 1)
            elif col == COL_PAGE_NAME:
                p_name = annot.get("page_name")
                if not p_name:
                    p_name = f"Página {annot.get('page_index', 0) + 1}"
                return p_name
            elif col == COL_SUBJECT:
                subj = annot.get("subject") or annot.get("/Subj")
                if not subj:
                    t = annot.get("type", "rect")
                    subj = TYPE_LABELS.get(t, t.capitalize())
                return subj
            elif col == COL_CONTENT:
                txt = annot.get("content") or annot.get("/Contents") or ""
                return txt.replace("\n", " ").strip()
            elif col == COL_LAYER:
                return annot.get("layer") or annot.get("discipline") or "General"
            elif col == COL_TAGS:
                return format_tags(annot.get("tags"))
            elif col == COL_PROPS:
                return format_properties(annot.get("properties"))
            elif col == COL_AUTHOR:
                return annot.get("author") or annot.get("/T") or "Usuario"
            elif col == COL_STATUS:
                return annot.get("status") or annot.get("/State") or "None"
            elif col == COL_DATE:
                created = annot.get("created_at", "")
                if created and len(created) >= 16:
                    return created[:16].replace("T", " ")
                return created or "-"

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == COL_SUBJECT:
                st = annot.get("style") or {}
                color_hex = st.get("stroke_color") or st.get("stroke") or "#0284C7"
                return self._get_color_icon(color_hex, annot.get("type", "rect"))

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_PAGE_NUM, COL_STATUS, COL_DATE):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_PROPS:
                props = annot.get("properties") or {}
                if isinstance(props, dict) and props:
                    return "\n".join(f"• {k}: {v}" for k, v in props.items())
            elif col == COL_TAGS:
                tags_str = format_tags(annot.get("tags"))
                if tags_str:
                    return f"Etiquetas: {tags_str}"
            cid = annot.get("id", "")[:8]
            subj = annot.get("subject") or TYPE_LABELS.get(annot.get("type", ""), "")
            cnt = annot.get("content", "")
            return f"[#{cid}] {subj}\n{cnt}" if cnt else f"[#{cid}] {subj}"
        elif role == Qt.ItemDataRole.UserRole:
            return annot

        elif role == Qt.ItemDataRole.UserRole + 1:
            return annot.get("id")

        elif role == Qt.ItemDataRole.UserRole + 2:
            return annot.get("page_index", 0)

        return None

    def set_annotations(self, annotations: list[dict]):
        self.beginResetModel()
        self._annotations = list(annotations)
        self.endResetModel()

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def get_annotation_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._annotations):
            return self._annotations[row]
        return None


class AnnotationsFilterProxyModel(QSortFilterProxyModel):
    """Proxy model que implementa filtros por ámbito (página), especialidad y texto global."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scope: str = "current"  # "current" o "all"
        self._current_page: int = 0
        self._discipline_filter: str = ""
        self._search_text: str = ""

    def _trigger_filter_update(self):
        if hasattr(self, "invalidate"):
            self.invalidate()
        else:
            self.invalidateFilter()

    def set_scope(self, scope: str, current_page: int):
        self._scope = scope
        self._current_page = current_page
        self._trigger_filter_update()

    def set_current_page(self, current_page: int):
        if self._current_page != current_page:
            self._current_page = current_page
            if self._scope == "current":
                self._trigger_filter_update()

    def set_discipline_filter(self, disc: str):
        self._discipline_filter = disc.strip()
        self._trigger_filter_update()

    def set_search_text(self, text: str):
        self._search_text = text.strip().lower()
        self._trigger_filter_update()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, AnnotationsTableModel):
            return True

        annot = model.get_annotation_at(source_row)
        if not annot:
            return False

        # 1. Filtro de ámbito de página
        if self._scope == "current":
            if int(annot.get("page_index", 0)) != self._current_page:
                return False

        # 2. Filtro de disciplina / especialidad
        if self._discipline_filter and self._discipline_filter != "Todas":
            disc = (annot.get("discipline") or annot.get("layer") or "General").strip()
            if disc.lower() != self._discipline_filter.lower():
                return False

        # 3. Filtro de búsqueda por texto
        if self._search_text:
            p_idx = annot.get("page_index", 0)
            text_targets = [
                str(p_idx + 1),
                str(annot.get("page_name", "")),
                str(annot.get("subject", "")),
                str(annot.get("content", "")),
                str(annot.get("layer", "")),
                str(annot.get("discipline", "")),
                format_tags(annot.get("tags")),
                format_properties(annot.get("properties")),
                str(annot.get("author", "")),
                str(annot.get("status", "")),
                TYPE_LABELS.get(annot.get("type", ""), ""),
                str(annot.get("id", "")),
            ]
            combined = " ".join(text_targets).lower()
            if self._search_text not in combined:
                return False

        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, AnnotationsTableModel):
            return super().lessThan(left, right)

        annot_l = model.get_annotation_at(left.row())
        annot_r = model.get_annotation_at(right.row())
        if not annot_l or not annot_r:
            return super().lessThan(left, right)

        col = left.column()
        if col == COL_PAGE_NUM:
            return int(annot_l.get("page_index", 0)) < int(annot_r.get("page_index", 0))
        elif col == COL_PAGE_NAME:
            return (annot_l.get("page_name") or "").lower() < (annot_r.get("page_name") or "").lower()
        elif col == COL_SUBJECT:
            s_l = (annot_l.get("subject") or annot_l.get("type") or "").lower()
            s_r = (annot_r.get("subject") or annot_r.get("type") or "").lower()
            return s_l < s_r
        elif col == COL_CONTENT:
            return (annot_l.get("content") or "").lower() < (annot_r.get("content") or "").lower()
        elif col == COL_LAYER:
            l_l = (annot_l.get("layer") or annot_l.get("discipline") or "").lower()
            l_r = (annot_r.get("layer") or annot_r.get("discipline") or "").lower()
            return l_l < l_r
        elif col == COL_TAGS:
            return format_tags(annot_l.get("tags")).lower() < format_tags(annot_r.get("tags")).lower()
        elif col == COL_PROPS:
            return format_properties(annot_l.get("properties")).lower() < format_properties(annot_r.get("properties")).lower()
        elif col == COL_AUTHOR:
            return (annot_l.get("author") or "").lower() < (annot_r.get("author") or "").lower()
        elif col == COL_STATUS:
            return (annot_l.get("status") or "").lower() < (annot_r.get("status") or "").lower()
        elif col == COL_DATE:
            return (annot_l.get("created_at") or "") < (annot_r.get("created_at") or "")
        return super().lessThan(left, right)


class MarkupTableDelegate(QStyledItemDelegate):
    """Delegado visual para renderizar badges de estado con nitidez y estilo moderno."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        col = index.column()

        if col == COL_STATUS:
            # Dibujar badge coloreado para el estado
            painter.save()
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

                if bool(option.state & QStyle.StateFlag.State_Selected):
                    painter.fillRect(option.rect, option.palette.highlight())

                status = str(index.data(Qt.ItemDataRole.DisplayRole) or "None")
                badge_hex = STATUS_COLORS.get(status, "#94A3B8")
                badge_color = QColor(badge_hex)

                r = option.rect
                badge_w = min(r.width() - 8, 76)
                badge_h = 18
                bx = r.center().x() - badge_w // 2
                by = r.center().y() - badge_h // 2
                badge_rect = QRectF(bx, by, badge_w, badge_h)

                bg_col = QColor(badge_color)
                bg_col.setAlpha(35)
                painter.setPen(QPen(badge_color, 1.0))
                painter.setBrush(QBrush(bg_col))
                painter.drawRoundedRect(badge_rect, 4.0, 4.0)

                painter.setPen(badge_color.lighter(130) if badge_color.lightness() < 120 else badge_color)
                font = painter.font()
                font.setPointSize(max(7, font.pointSize() - 2))
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, status)
            finally:
                painter.restore()
            return

        super().paint(painter, option, index)

    def createEditor(self, parent, option, index):
        """Deshabilita la creación de editores en celdas de la tabla de marcas (solo lectura)."""
        return None


class MarkupsPanel(QWidget):
    """Panel inferior completo desplegable para gestión tabular de anotaciones."""

    annotation_selected = Signal(str, int)     # (annot_id, page_index) al hacer clic simple
    annotation_activated = Signal(str, int)    # (annot_id, page_index) al hacer doble clic (navegación y foco)
    annotation_delete_requested = Signal(list) # lista de annot_ids para eliminar
    request_close = Signal()                   # cerrar o colapsar panel
    count_changed = Signal(int)                # emite cantidad de anotaciones filtradas

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("markupsPanel")
        self._current_page = 0
        self._all_annotations: list[dict] = []
        self._is_syncing_selection = False

        self._setup_ui()
        self.apply_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 1. Barra de Herramientas Superior del Panel
        toolbar = QWidget(self)
        toolbar.setObjectName("markupsToolbar")
        toolbar.setFixedHeight(36)
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(10, 4, 10, 4)
        tb_lay.setSpacing(8)

        # Título y contador
        lbl_title = QLabel("Lista de Anotaciones", toolbar)
        lbl_title.setObjectName("markupsTitleLabel")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)  # texto centrado en su recuadro
        tb_lay.addWidget(lbl_title)

        self._lbl_count = QLabel("(0 marcas)", toolbar)
        self._lbl_count.setObjectName("markupsCountLabel")
        self._lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb_lay.addWidget(self._lbl_count)

        tb_lay.addSpacing(12)

        # Buscador en tiempo real
        self._txt_search = QLineEdit(toolbar)
        self._txt_search.setObjectName("markupsSearchInput")
        self._txt_search.setPlaceholderText("Buscar en anotaciones...")
        self._txt_search.setClearButtonEnabled(True)
        self._txt_search.setFixedWidth(200)
        self._txt_search.textChanged.connect(self._on_search_changed)
        tb_lay.addWidget(self._txt_search)

        # Ámbito: Página Actual vs Todo el Plano
        self._combo_scope = QComboBox(toolbar)
        self._combo_scope.addItem("Página actual", "current")
        self._combo_scope.addItem("Todo el plano", "all")
        self._combo_scope.currentIndexChanged.connect(self._on_scope_changed)
        tb_lay.addWidget(self._combo_scope)

        # Filtro de Especialidad
        self._combo_discipline = QComboBox(toolbar)
        self._combo_discipline.addItem("Todas las especialidades", "Todas")
        self._combo_discipline.currentIndexChanged.connect(self._on_discipline_changed)
        tb_lay.addWidget(self._combo_discipline)

        tb_lay.addStretch(1)

        # Botón Exportar CSV
        self._btn_export = QPushButton("Exportar CSV", toolbar)
        self._btn_export.setIcon(ThemeManager.get_icon("file-text") or ThemeManager.get_icon("download"))
        self._btn_export.setToolTip("Exportar marcas visibles a archivo CSV (Ctrl+E)")
        self._btn_export.clicked.connect(self.export_to_csv)
        tb_lay.addWidget(self._btn_export)

        # Botón Cerrar / Ocultar panel
        btn_close = QToolButton(toolbar)
        btn_close.setObjectName("markupsBtnClose")
        btn_close.setText("✕")
        btn_close.setToolTip("Ocultar tabla de marcas (Ctrl+M)")
        btn_close.setFixedSize(24, 24)
        btn_close.clicked.connect(self.request_close.emit)
        tb_lay.addWidget(btn_close)

        layout.addWidget(toolbar)

        # 2. Tabla de Datos
        self._table = QTableView(self)
        self._table.setObjectName("markupsTableView")
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.setShowGrid(False)

        # Modelos
        self._model = AnnotationsTableModel(self)
        self._proxy = AnnotationsFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._table.setModel(self._proxy)

        # Delegado para columnas visuales
        self._delegate = MarkupTableDelegate(self)
        self._table.setItemDelegate(self._delegate)

        # Configuración de cabeceras interactivas y redimensionables libremente por el usuario
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(28)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionsMovable(True)
        header.setHighlightSections(False)

        # Anchos predeterminados compactos y limpios
        default_widths = {
            COL_PAGE_NUM: 64,
            COL_PAGE_NAME: 140,
            COL_SUBJECT: 120,
            COL_CONTENT: 170,
            COL_LAYER: 95,
            COL_TAGS: 120,
            COL_PROPS: 160,
            COL_AUTHOR: 85,
            COL_STATUS: 90,
            COL_DATE: 120,
        }
        for col_idx, width in default_widths.items():
            header.resizeSection(col_idx, width)

        # Restaurar estado previo si fue guardado por el usuario
        self._restore_header_state()

        # Guardar automáticamente cualquier ajuste manual de ancho o posición de columnas
        header.sectionResized.connect(self._save_header_state)
        header.sectionMoved.connect(self._save_header_state)

        # Eventos de interacción
        self._table.clicked.connect(self._on_table_clicked)
        self._table.doubleClicked.connect(self._on_table_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self._table, 1)

    # --- Persistencia del Estado de Cabeceras ---

    def _restore_header_state(self):
        """Restaura anchos y orden de columnas personalizados desde settings de la aplicación."""
        try:
            from core.settings import settings
            from PySide6.QtCore import QByteArray
            saved_state = settings.get("markups.header_state", None)
            if saved_state:
                header = self._table.horizontalHeader()
                header.restoreState(QByteArray.fromHex(saved_state.encode("ascii")))
                header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        except Exception:
            pass

    def _save_header_state(self, *args):
        """Guarda anchos y orden de columnas en los ajustes persistentes del usuario."""
        try:
            from core.settings import settings
            header = self._table.horizontalHeader()
            hex_data = bytes(header.saveState().toHex()).decode("ascii")
            settings.set("markups.header_state", hex_data)
        except Exception:
            pass

    # --- Sincronización de Datos ---

    def get_annotation_count(self) -> int:
        """Retorna el total de anotaciones cargadas en el modelo."""
        return self._model.rowCount()

    def set_annotations(self, annotations: list[dict], current_page: int = 0):
        """Carga o actualiza la lista total de anotaciones en el modelo."""
        self._all_annotations = list(annotations)
        self._current_page = current_page
        self._model.set_annotations(self._all_annotations)
        self._proxy.set_current_page(current_page)
        self._update_discipline_dropdown()
        self._update_counter()

    def set_current_page(self, page_index: int):
        """Notifica cambio de página para recalcular el filtro si el ámbito es 'Página actual'."""
        self._current_page = page_index
        self._proxy.set_current_page(page_index)
        self._update_counter()

    def select_annotation(self, annot_id: str):
        """Selecciona la fila correspondiente al annot_id en la tabla sin emitir bucles."""
        if not annot_id:
            self._table.clearSelection()
            return

        self._is_syncing_selection = True
        try:
            for row in range(self._proxy.rowCount()):
                idx = self._proxy.index(row, 0)
                aid = self._proxy.data(idx, Qt.ItemDataRole.UserRole + 1)
                if aid == annot_id:
                    sel_model = self._table.selectionModel()
                    if sel_model:
                        from PySide6.QtCore import QItemSelectionModel
                        sel_model.select(idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
                        self._table.scrollTo(idx, QTableView.ScrollHint.EnsureVisible)
                    break
        finally:
            self._is_syncing_selection = False

    def _update_discipline_dropdown(self):
        """Actualiza las opciones de especialidades detectadas dinámicamente."""
        current_disc = self._combo_discipline.currentData() or "Todas"
        disciplines = set()
        for a in self._all_annotations:
            d = a.get("discipline") or a.get("layer")
            if d:
                disciplines.add(d.strip())

        self._combo_discipline.blockSignals(True)
        self._combo_discipline.clear()
        self._combo_discipline.addItem("Todas las especialidades", "Todas")
        for d in sorted(disciplines):
            self._combo_discipline.addItem(d, d)

        idx = self._combo_discipline.findData(current_disc)
        self._combo_discipline.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_discipline.blockSignals(False)

    def _update_counter(self):
        count = self._proxy.rowCount()
        total = len(self._all_annotations)
        if self._combo_scope.currentData() == "current":
            self._lbl_count.setText(f"({count} en esta pág. / {total} total)")
        else:
            self._lbl_count.setText(f"({count} marcas)")
        self.count_changed.emit(count)

    # --- Handlers de Filtros ---

    def _on_search_changed(self, text: str):
        self._proxy.set_search_text(text)
        self._update_counter()

    def _on_scope_changed(self, index: int):
        scope = self._combo_scope.itemData(index) or "current"
        self._proxy.set_scope(scope, self._current_page)
        self._update_counter()

    def _on_discipline_changed(self, index: int):
        disc = self._combo_discipline.itemData(index) or "Todas"
        self._proxy.set_discipline_filter(disc)
        self._update_counter()

    # --- Handlers de Interacción ---

    def _on_table_clicked(self, index: QModelIndex):
        if self._is_syncing_selection or not index.isValid():
            return
        annot_id = self._proxy.data(index, Qt.ItemDataRole.UserRole + 1)
        page_idx = self._proxy.data(index, Qt.ItemDataRole.UserRole + 2)
        if annot_id is not None:
            self.annotation_selected.emit(annot_id, int(page_idx or 0))

    def _on_table_double_clicked(self, index: QModelIndex):
        if not index.isValid():
            return
        annot_id = self._proxy.data(index, Qt.ItemDataRole.UserRole + 1)
        page_idx = self._proxy.data(index, Qt.ItemDataRole.UserRole + 2)
        if annot_id is not None:
            self.annotation_activated.emit(annot_id, int(page_idx or 0))

    def _show_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return

        annot_id = self._proxy.data(index, Qt.ItemDataRole.UserRole + 1)
        page_idx = self._proxy.data(index, Qt.ItemDataRole.UserRole + 2)
        annot = self._proxy.data(index, Qt.ItemDataRole.UserRole)
        if not annot_id:
            return

        menu = QMenu(self)
        menu.setObjectName("markupsContextMenu")

        act_goto = menu.addAction("Centrar en el plano (Doble clic)")
        act_goto.setIcon(ThemeManager.get_icon("search") or ThemeManager.get_icon("eye"))
        act_goto.triggered.connect(lambda: self.annotation_activated.emit(annot_id, int(page_idx or 0)))

        menu.addSeparator()

        content = annot.get("content", "")
        if content:
            from PySide6.QtGui import QGuiApplication
            act_copy = menu.addAction("Copiar contenido")
            act_copy.setIcon(ThemeManager.get_icon("copy"))
            act_copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(content))

        # Eliminar seleccionados
        selected_rows = self._table.selectionModel().selectedRows()
        selected_ids = []
        for r_idx in selected_rows:
            aid = self._proxy.data(r_idx, Qt.ItemDataRole.UserRole + 1)
            if aid: selected_ids.append(aid)
        if not selected_ids:
            selected_ids = [annot_id]

        lbl_del = f"Eliminar {len(selected_ids)} anotaciones" if len(selected_ids) > 1 else "Eliminar anotación"
        act_del = menu.addAction(lbl_del)
        act_del.setIcon(ThemeManager.get_icon("trash"))
        act_del.triggered.connect(lambda: self.annotation_delete_requested.emit(selected_ids))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            selected_rows = self._table.selectionModel().selectedRows()
            selected_ids = [self._proxy.data(r, Qt.ItemDataRole.UserRole + 1) for r in selected_rows if self._proxy.data(r, Qt.ItemDataRole.UserRole + 1)]
            if selected_ids:
                self.annotation_delete_requested.emit(selected_ids)
                event.accept()
                return
        super().keyPressEvent(event)

    # --- Exportación a CSV ---

    def export_to_csv(self, file_path: str = None):
        """Exporta las marcas actualmente visibles según los filtros activos a archivo CSV."""
        row_count = self._proxy.rowCount()
        is_interactive = file_path is None
        if row_count == 0:
            if is_interactive:
                QMessageBox.information(self, "Exportar CSV", "No hay anotaciones visibles para exportar.")
            return

        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Exportar Lista de Anotaciones a CSV",
                "Anotaciones_Plano.csv",
                "Archivos CSV (*.csv);;Todos los archivos (*.*)",
            )
            if not file_path:
                return

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Nº Pág.", "Nombre de Página", "Subject", "Content", "Layer", "Etiquetas", "Propiedades", "Author", "Estado", "Fecha", "ID"])
                for row in range(row_count):
                    idx = self._proxy.index(row, 0)
                    annot = self._proxy.data(idx, Qt.ItemDataRole.UserRole)
                    if not annot:
                        continue
                    p_idx = annot.get("page_index", 0)
                    writer.writerow([
                        str(p_idx + 1),
                        annot.get("page_name") or f"Página {p_idx + 1}",
                        annot.get("subject") or annot.get("/Subj") or TYPE_LABELS.get(annot.get("type", ""), annot.get("type", "")),
                        annot.get("content", ""),
                        annot.get("layer") or annot.get("discipline") or "General",
                        format_tags(annot.get("tags")),
                        format_properties(annot.get("properties")),
                        annot.get("author", "Usuario"),
                        annot.get("status", "None"),
                        annot.get("created_at", ""),
                        annot.get("id", ""),
                    ])

            if is_interactive:
                QMessageBox.information(self, "Exportación Exitosa", f"Se exportaron {row_count} anotaciones a: " + str(file_path))
        except Exception as e:
            if is_interactive:
                QMessageBox.critical(self, "Error al exportar", f"No se pudo guardar el archivo CSV: " + str(e))
            else:
                raise
    def apply_theme(self):
        """
        Reaplica el tema al panel (Methods Down).

        Todo el estilo (panel, toolbar, tabla, cabeceras, buscador y botón de
        cierre) vive en ``ui/styles/theme.qss``; aquí solo se fuerza un
        *repolish* para que Qt reevalúe la hoja global.
        """
        self.style().unpolish(self)
        self.style().polish(self)
