"""
Módulo de Panel Lateral Izquierdo de Proyecto (Project Explorer Sidebar).

Proporciona navegación visual y gestión de planos dentro del espacio de trabajo:
1. Vista de árbol jerárquica (QTreeWidget) de planos del proyecto y sus páginas individuales.
2. Muestra los nombres de hoja reales (etiquetas/bookmarks CAD ej. 'MD2202'), o número si no tienen nombre.
3. Navegación directa por página al hacer clic en un nodo hoja.
4. Acciones rápidas para importar planos PDF a la carpeta de custodia 'drawings/'.
5. Soporte para modo proyecto y estado en reposo cuando no hay proyecto activo.
6. Totalmente integrado con los tokens de ThemeManager (Dark / Light).
"""

from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QMenu,
    QMessageBox,
    QInputDialog,
    QFrame,
)
from PySide6.QtGui import QIcon

from ui.styles.style_manager import ThemeManager


class ProjectSidebar(QWidget):
    """Panel lateral colapsable para administración del proyecto y catálogo jerárquico de planos y páginas."""

    drawing_selected = Signal(str)            # (abs_path)
    page_selected = Signal(str, int)          # (abs_path, page_index)
    request_new_project = Signal()
    request_open_project = Signal()
    request_open_recent_project = Signal(str)
    request_import_drawing = Signal()
    request_close_project = Signal()
    request_delete_drawing = Signal(int)
    request_rename_drawing = Signal(int, str)
    request_reload_drawing = Signal(str)
    request_manage_pages = Signal(str)
    toggle_collapsed = Signal()
    selection_changed = Signal()              # el plano seleccionado cambió

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_data: dict | None = None
        self._drawings: list[dict] = []
        self._is_collapsed: bool = False

        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self.setObjectName("projectSidebar")

        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 1. Cabecera del Panel
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        self._lbl_header = QLabel("Proyectos", self)
        self._lbl_header.setObjectName("sidebarHeaderLabel")
        header_layout.addWidget(self._lbl_header, 1)

        layout.addLayout(header_layout)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # 2. Contenedor Estado: Sin Proyecto Activo
        self._empty_container = QWidget(self)
        empty_layout = QVBoxLayout(self._empty_container)
        empty_layout.setContentsMargins(6, 12, 6, 12)
        empty_layout.setSpacing(10)

        lbl_no_proj = QLabel("Ningún proyecto abierto", self._empty_container)
        lbl_no_proj.setObjectName("sidebarEmptyTitle")
        lbl_no_proj.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(lbl_no_proj)

        lbl_hint = QLabel(
            "Crea o abre un proyecto para organizar, importar y medir planos PDF.",
            self._empty_container
        )
        lbl_hint.setObjectName("sidebarEmptyHint")
        lbl_hint.setWordWrap(True)
        lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(lbl_hint)

        self._btn_new_proj = QPushButton("Nuevo Proyecto", self._empty_container)
        self._btn_new_proj.clicked.connect(self.request_new_project.emit)
        empty_layout.addWidget(self._btn_new_proj)

        self._btn_open_proj = QPushButton("Abrir Proyecto", self._empty_container)
        self._btn_open_proj.clicked.connect(self.request_open_project.emit)
        empty_layout.addWidget(self._btn_open_proj)

        # Sección de Proyectos Recientes en el Sidebar
        self._recent_group = QWidget(self._empty_container)
        self._recent_layout = QVBoxLayout(self._recent_group)
        self._recent_layout.setContentsMargins(0, 10, 0, 0)
        self._recent_layout.setSpacing(4)
        
        lbl_recent_title = QLabel("Proyectos Recientes:", self._recent_group)
        lbl_recent_title.setObjectName("sidebarSectionTitle")
        self._recent_layout.addWidget(lbl_recent_title)
        
        self._recent_list_container = QWidget(self._recent_group)
        self._recent_items_layout = QVBoxLayout(self._recent_list_container)
        self._recent_items_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_items_layout.setSpacing(2)
        self._recent_layout.addWidget(self._recent_list_container)
        
        empty_layout.addWidget(self._recent_group)
        self.update_recent_projects_ui()

        empty_layout.addStretch()
        layout.addWidget(self._empty_container)

        # 3. Contenedor Estado: Con Proyecto Activo
        self._project_container = QWidget(self)
        proj_layout = QVBoxLayout(self._project_container)
        proj_layout.setContentsMargins(0, 0, 0, 0)
        proj_layout.setSpacing(6)

        # Sub-barra de acciones del proyecto
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        self._btn_import = QPushButton(" Importar Plano", self._project_container)
        self._btn_import.setToolTip("Copiar plano PDF a la carpeta drawings/ del proyecto")
        self._btn_import.clicked.connect(self.request_import_drawing.emit)
        action_layout.addWidget(self._btn_import, 1)

        self._btn_proj_menu = QPushButton(self._project_container)
        self._btn_proj_menu.setToolTip("Opciones de proyecto")
        self._btn_proj_menu.setFixedSize(28, 28)
        self._btn_proj_menu.clicked.connect(self._show_project_menu)
        action_layout.addWidget(self._btn_proj_menu)

        proj_layout.addLayout(action_layout)

        # Etiqueta de sección de planos
        lbl_drawings_title = QLabel("PLANOS DEL PROYECTO", self._project_container)
        lbl_drawings_title.setObjectName("sidebarSectionTitleCaps")
        proj_layout.addWidget(lbl_drawings_title)

        # Árbol jerárquico de planos y hojas (QTreeWidget)
        self._tree_drawings = QTreeWidget(self._project_container)
        self._tree_drawings.setObjectName("drawingsTree")
        self._tree_drawings.setHeaderHidden(True)
        self._tree_drawings.setRootIsDecorated(False)
        self._tree_drawings.setIndentation(4)
        self._tree_drawings.setAnimated(True)
        self._tree_drawings.setIconSize(QSize(16, 16))
        self._tree_drawings.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree_drawings.customContextMenuRequested.connect(self._show_drawing_context_menu)
        self._tree_drawings.itemClicked.connect(self._on_item_clicked)
        self._tree_drawings.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree_drawings.setExpandsOnDoubleClick(False)

        def _on_tree_key_press(event):
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                item = self._tree_drawings.currentItem()
                if item:
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        self._confirm_delete_drawing(data)
                        return
            elif event.key() == Qt.Key.Key_F2:
                item = self._tree_drawings.currentItem()
                if item:
                    data = item.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        self._prompt_rename_drawing(data)
                        return
            QTreeWidget.keyPressEvent(self._tree_drawings, event)

        self._tree_drawings.keyPressEvent = _on_tree_key_press
        proj_layout.addWidget(self._tree_drawings, 1)

        layout.addWidget(self._project_container)

        # Inicialmente en estado sin proyecto
        self._show_empty_state()

    def update_recent_projects_ui(self):
        """Actualiza la lista visual de proyectos recientes en el estado vacío."""
        if not hasattr(self, "_recent_items_layout"):
            return
        # Limpiar elementos anteriores
        while self._recent_items_layout.count():
            item = self._recent_items_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from core.settings import settings
        from pathlib import Path
        recent_list = settings.get("general.recent_projects", [])
        if not recent_list:
            self._recent_group.setVisible(False)
            return

        self._recent_group.setVisible(True)
        for p_str in recent_list[:5]:
            p = Path(p_str)
            name = p.name if p.name else p_str
            btn = QPushButton(name, self._recent_list_container)
            btn.setObjectName("recentProjectButton")
            btn.setIcon(ThemeManager.get_icon("folder-open", size=14))
            btn.setToolTip(p_str)
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            btn.clicked.connect(lambda checked, path=p_str: self.request_open_recent_project.emit(path))
            self._recent_items_layout.addWidget(btn)

    def _apply_theme(self):
        self._btn_new_proj.setIcon(ThemeManager.get_icon("plus"))
        self._btn_open_proj.setIcon(ThemeManager.get_icon("folder-open"))
        self._btn_import.setIcon(ThemeManager.get_icon("plus"))
        self._btn_proj_menu.setIcon(ThemeManager.get_icon("sidebar"))

        # Actualizar iconos de elementos ya existentes en el árbol
        pdf_icon = ThemeManager.get_icon("file-pdf")
        page_icon = ThemeManager.get_icon("file-page")
        for i in range(self._tree_drawings.topLevelItemCount()):
            parent_item = self._tree_drawings.topLevelItem(i)
            parent_item.setIcon(0, pdf_icon)
            for j in range(parent_item.childCount()):
                parent_item.child(j).setIcon(0, page_icon)

    def _show_empty_state(self):
        self._empty_container.setVisible(True)
        self._project_container.setVisible(False)
        self._lbl_header.setText("Proyectos")

    def _show_active_state(self, project_name: str):
        self._empty_container.setVisible(False)
        self._project_container.setVisible(True)
        self._lbl_header.setText(project_name)

    def set_project(self, project_data: dict | None, drawings: list[dict]):
        """Actualiza la vista con el proyecto activo y su listado de planos."""
        self._project_data = project_data
        self._drawings = drawings

        if not project_data:
            self._show_empty_state()
            self._tree_drawings.clear()
            return

        self._show_active_state(project_data.get("name", "Proyecto"))
        self._populate_drawings(drawings)


    def _populate_drawings(self, drawings: list[dict]):
        self._tree_drawings.clear()
        pdf_icon = ThemeManager.get_icon("file-pdf")

        for d in drawings:
            name = d.get("name", "Sin título")
            abs_path = d.get("abs_path", "")
            raw_pages = d.get("page_count", 0)
            pages_str = f"{raw_pages} págs" if raw_pages != 1 else "1 pág"

            item = QTreeWidgetItem(self._tree_drawings)
            item.setIcon(0, pdf_icon)
            item.setText(0, f"{name} ({pages_str})")
            item.setToolTip(0, f"Plano: {name}\nUbicación: {abs_path}\nPáginas: {raw_pages}")
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "drawing",
                "abs_path": abs_path,
                "id": d.get("id"),
                "name": name,
                "page_count": raw_pages,
            })

        self._tree_drawings.clearSelection()
        self._tree_drawings.setCurrentItem(None)
        self.selection_changed.emit()

    def update_drawing_page_count(self, abs_path: str, new_page_count: int):
        """Actualiza dinámicamente el conteo de páginas de un plano en el árbol lateral."""
        target_path = Path(abs_path).resolve()
        self.invalidate_cache(abs_path)

        pages_str = f"{new_page_count} págs" if new_page_count != 1 else "1 pág"
        for i in range(self._tree_drawings.topLevelItemCount()):
            item = self._tree_drawings.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and Path(data.get("abs_path", "")).resolve() == target_path:
                name = data.get("name", "Sin título")
                item.setText(0, f"{name} ({pages_str})")
                tip = f"Plano: {name}\nUbicación: {abs_path}\nPáginas: {new_page_count}"
                item.setToolTip(0, tip)
                data["page_count"] = new_page_count
                item.setData(0, Qt.ItemDataRole.UserRole, data)
                break

    def invalidate_cache(self, abs_path: str | None = None):
        """Método de compatibilidad para invalidación de caché externa."""
        pass

    def highlight_drawing(self, file_path: str):
        """Selecciona y enfoca visualmente el plano activo en la lista."""
        if not file_path:
            return
        target_path = Path(file_path).resolve()

        self._tree_drawings.blockSignals(True)
        try:
            for i in range(self._tree_drawings.topLevelItemCount()):
                item = self._tree_drawings.topLevelItem(i)
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data and Path(data.get("abs_path", "")).resolve() == target_path:
                    self._tree_drawings.setCurrentItem(item)
                    self._tree_drawings.scrollToItem(item)
                    return
        finally:
            self._tree_drawings.blockSignals(False)

    def highlight_page(self, file_path: str, page_index: int = 0):
        self.highlight_drawing(file_path)

    def has_selection(self) -> bool:
        """Indica si hay un plano seleccionado actualmente en el árbol."""
        return self.get_selected_drawing_id() is not None

    def get_selected_drawing_id(self) -> int | None:
        """Retorna el ID del plano seleccionado, o ``None`` si no hay selección."""
        item = self._tree_drawings.currentItem()
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "drawing":
            return None
        return data.get("id")

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int = 0):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        abs_path = data.get("abs_path")
        if abs_path:
            self.drawing_selected.emit(abs_path)
        self.selection_changed.emit()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int = 0):
        self._on_item_clicked(item, column)

    def _show_project_menu(self):
        menu = QMenu(self)
        action_close = menu.addAction(ThemeManager.get_icon("folder-open"), "Cerrar Proyecto")
        action_close.triggered.connect(self.request_close_project.emit)
        menu.exec(self._btn_proj_menu.mapToGlobal(self._btn_proj_menu.rect().bottomLeft()))

    def _show_drawing_context_menu(self, pos):
        item = self._tree_drawings.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        menu = QMenu(self)
        action_open = menu.addAction(ThemeManager.get_icon("file-pdf"), "Abrir Plano")
        action_open.triggered.connect(lambda: self.drawing_selected.emit(data["abs_path"]))
        action_manage_pages = menu.addAction(ThemeManager.get_icon("pages-grid"), "Gestor de Páginas... (Ctrl+Shift+P)")
        action_manage_pages.triggered.connect(lambda: self.request_manage_pages.emit(data["abs_path"]))
        action_reload = menu.addAction(ThemeManager.get_icon("refresh"), "Recargar Plano Actual")
        action_reload.triggered.connect(lambda: self.request_reload_drawing.emit(data["abs_path"]))
        action_rename = menu.addAction(ThemeManager.get_icon("edit"), "Renombrar Plano... (F2)")
        action_rename.triggered.connect(lambda: self._prompt_rename_drawing(data))
        menu.addSeparator()
        action_delete = menu.addAction(ThemeManager.get_icon("trash"), "Eliminar del Proyecto")
        action_delete.triggered.connect(lambda: self._confirm_delete_drawing(data))

        menu.exec(self._tree_drawings.mapToGlobal(pos))

    def _prompt_rename_drawing(self, drawing_data: dict):
        drawing_id = drawing_data.get("id") or drawing_data.get("drawing_id")
        current_name = drawing_data.get("name", "")
        if not drawing_id:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Renombrar Plano",
            "Nuevo nombre del plano:",
            text=current_name
        )
        if not ok or not new_name.strip() or new_name.strip() == current_name:
            return

        self.request_rename_drawing.emit(drawing_id, new_name.strip())

    def _confirm_delete_drawing(self, drawing_data: dict):
        d_name = drawing_data.get("name", "este plano")
        drawing_id = drawing_data.get("id") or drawing_data.get("drawing_id")
        if not drawing_id:
            return

        box = QMessageBox(
            QMessageBox.Icon.Warning,
            "Eliminar Plano del Proyecto",
            (
                f"¿Estás seguro de que deseas eliminar permanentemente '{d_name}'?\n\n"
                "Esta acción es destructiva e irreversible:\n"
                "• Se eliminarán todas las mediciones, marcas y datos vinculados a este plano.\n"
                "• Se eliminará físicamente el archivo PDF de la carpeta de custodia 'drawings/'.\n"
                "• Esta operación NO se puede deshacer con Ctrl+Z."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_btn = box.button(QMessageBox.StandardButton.Yes)
        if yes_btn:
            yes_btn.setText("Sí, eliminar permanentemente")
        no_btn = box.button(QMessageBox.StandardButton.No)
        if no_btn:
            no_btn.setText("Cancelar")

        if box.exec() == QMessageBox.StandardButton.Yes:
            self.request_delete_drawing.emit(drawing_id)
