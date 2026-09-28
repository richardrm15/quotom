from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QStatusBar,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QApplication,
)

# AHORA (según donde tengas los módulos en quotom/):
from common.widgets.app_menu_bar import AppMenuBar
from common.widgets.navigation_toolbar import NavigationToolBar
from common.widgets.project_sidebar import ProjectSidebar
from common.widgets.side_tab_bar import SideTabBar
from common.widgets.annotation_toolbar import AnnotationToolBar
from common.widgets.find_bar import FindBar
from common.widgets.graphics_view import PlanGraphicsView
from common.widgets.title_bar import CustomTitleBar
from common.widgets.window_resizer import WindowResizeFilter, ResizeGrip
from common.widgets.property_inspector import PropertyInspector
from common.widgets.markups_panel import MarkupsPanel
from common.styles.style_manager import ThemeManager


class MainWindowView(QMainWindow):
    """
    Vista pura de la ventana principal.
    Responsable únicamente de la disposición de componentes visuales,
    redimensionamiento y emisión de eventos de usuario hacia el controlador.
    """

    # Señales de ciclo de vida e interfaz
    window_closed = Signal(bool, int, int)  # is_maximized, width, height
    escape_pressed = Signal()
    copy_requested = Signal()
    paste_requested = Signal()

    def __init__(self, init_w: int = 1280, init_h: int = 800, start_maximized: bool = False):
        super().__init__()
        self.setObjectName("mainAppWindow")
        self.resize(init_w, init_h)
        # Qt puede emitir resize/changeEvent antes de que exista la UI.
        self._ui_ready: bool = False
        if start_maximized:
            QTimer.singleShot(0, self.showMaximized)

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self._setup_ui()
        self._ui_ready = True

        self._resize_filter = WindowResizeFilter(self)
        QApplication.instance().installEventFilter(self._resize_filter)

        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self.escape_pressed.emit)

    def _setup_ui(self) -> None:
        root_container = QWidget(self)
        root_layout = QVBoxLayout(root_container)
        root_layout.setContentsMargins(2, 2, 2, 2)
        root_layout.setSpacing(0)

        # Barra de título CSD
        self.custom_title_bar = CustomTitleBar(self)
        root_layout.addWidget(self.custom_title_bar)

        # Barra de menús
        self.menu_bar = AppMenuBar(parent=self)
        root_layout.addWidget(self.menu_bar)

        # Contenedor del visor central
        self.viewer = PlanGraphicsView(self)
        self.viewer_container = QWidget(self)
        self.viewer_container.setObjectName("viewerContainer")
        viewer_layout = QVBoxLayout(self.viewer_container)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(0)

        self.nav_toolbar = NavigationToolBar(self.viewer_container)
        viewer_layout.addWidget(self.nav_toolbar)

        canvas_box = QWidget(self.viewer_container)
        canvas_layout = QHBoxLayout(canvas_box)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        canvas_layout.addWidget(self.viewer, 1)

        self.annotation_toolbar = AnnotationToolBar(canvas_box)
        canvas_layout.addWidget(self.annotation_toolbar, 0)

        self.markups_panel = MarkupsPanel(self.viewer_container)

        self.viewer_splitter = QSplitter(Qt.Orientation.Vertical, self.viewer_container)
        self.viewer_splitter.addWidget(canvas_box)
        self.viewer_splitter.addWidget(self.markups_panel)
        self.viewer_splitter.setCollapsible(0, False)
        self.viewer_splitter.setCollapsible(1, True)
        self.viewer_splitter.setStretchFactor(0, 1)
        self.viewer_splitter.setStretchFactor(1, 0)
        self.viewer_splitter.setSizes([550, 190])
        viewer_layout.addWidget(self.viewer_splitter, 1)

        self.find_bar = FindBar(self.viewer_container)
        self.find_bar.hide()

        # Espacio de trabajo horizontal
        self.workspace_container = QWidget(self)
        ws_layout = QHBoxLayout(self.workspace_container)
        ws_layout.setContentsMargins(0, 0, 0, 0)
        ws_layout.setSpacing(0)

        self.sidebar = ProjectSidebar(self)
        self.panel_stack = QStackedWidget(self.workspace_container)
        self.panel_stack.setObjectName("leftPanelStack")
        self.panel_stack.addWidget(self.sidebar)
        self.panel_stack.setCurrentIndex(0)

        self.side_tab_bar = SideTabBar(self.workspace_container, position="left")
        self.side_tab_bar.add_tab(
            tab_id="project",
            icon_name="folder",
            tooltip="Panel de Proyectos (Ctrl+B)",
            on_click=lambda: self.toggle_panel("project"),
        )
        self.side_tab_bar.set_active_tab("project")
        ws_layout.addWidget(self.side_tab_bar, 0)

        self.property_inspector = PropertyInspector(self.workspace_container)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self.workspace_container)
        self.main_splitter.addWidget(self.panel_stack)
        self.main_splitter.addWidget(self.viewer_container)
        self.main_splitter.addWidget(self.property_inspector)
        self.main_splitter.setCollapsible(0, True)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setCollapsible(2, True)
        self.main_splitter.setSizes([260, 720, 320])
        ws_layout.addWidget(self.main_splitter, 1)

        self.right_tab_bar = SideTabBar(self.workspace_container, position="right")
        self.right_tab_bar.add_tab(
            tab_id="inspector",
            icon_name="edit",
            tooltip="Inspector de Propiedades (Ctrl+I)",
            on_click=self.toggle_inspector,
        )
        self.right_tab_bar.set_active_tab("inspector")
        ws_layout.addWidget(self.right_tab_bar, 0)
        root_layout.addWidget(self.workspace_container, 1)

        # Barra inferior de toggle de marcas
        self.bottom_bar = QWidget(self)
        self.bottom_bar.setObjectName("bottomBar")
        self.bottom_bar.setFixedHeight(26)
        bb_layout = QHBoxLayout(self.bottom_bar)
        bb_layout.setContentsMargins(8, 0, 8, 0)
        bb_layout.setSpacing(8)

        self.btn_toggle_markups = QPushButton("Marcas (0)", self.bottom_bar)
        self.btn_toggle_markups.setObjectName("btnToggleMarkups")
        self.btn_toggle_markups.setCheckable(True)
        self.btn_toggle_markups.setChecked(True)
        self.btn_toggle_markups.setFixedHeight(22)
        self.btn_toggle_markups.setToolTip("Mostrar / Ocultar tabla inferior de anotaciones (Ctrl+M)")
        self.btn_toggle_markups.clicked.connect(self.toggle_markups_panel)
        bb_layout.addWidget(self.btn_toggle_markups)
        bb_layout.addStretch(1)
        root_layout.addWidget(self.bottom_bar, 0)

        # Barra de estado
        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        root_layout.addWidget(self.status_bar)

        self.bg_cache_widget = QWidget(self.status_bar)
        bg_layout = QHBoxLayout(self.bg_cache_widget)
        bg_layout.setContentsMargins(6, 0, 8, 0)
        bg_layout.setSpacing(8)
        self.lbl_cache_status = QLabel("", self.bg_cache_widget)
        bg_layout.addWidget(self.lbl_cache_status)
        self.progress_cache = QProgressBar(self.bg_cache_widget)
        self.progress_cache.setFixedSize(120, 13)
        self.progress_cache.setTextVisible(False)
        bg_layout.addWidget(self.progress_cache)
        self.status_bar.addPermanentWidget(self.bg_cache_widget)
        self.bg_cache_widget.setVisible(False)

        # Indicador de guardado usando id para estilos QSS centralizados
        self.lbl_saved_indicator = QLabel("✓ Guardado", self.status_bar)
        self.lbl_saved_indicator.setObjectName("lblSavedIndicator")
        self.lbl_saved_indicator.setVisible(False)
        self.status_bar.addPermanentWidget(self.lbl_saved_indicator)

        self.save_indicator_timer = QTimer(self)
        self.save_indicator_timer.setSingleShot(True)
        self.save_indicator_timer.timeout.connect(lambda: self.lbl_saved_indicator.setVisible(False))

        self.size_grip = ResizeGrip(self)
        self.status_bar.addPermanentWidget(self.size_grip)

        self.setCentralWidget(root_container)

    # =========================================================================
    # MÉTODOS PÚBLICOS DE ACTUALIZACIÓN DE UI (Methods Down)
    # =========================================================================

    def show_saved_indicator(self, message: str = "✓ Guardado") -> None:
        self.lbl_saved_indicator.setText(message)
        self.lbl_saved_indicator.setVisible(True)
        self.save_indicator_timer.start(2400)

    def set_window_title(self, title: str) -> None:
        self.custom_title_bar.set_title(title)

    def set_cache_progress(self, cached: int, total: int) -> None:
        if total <= 0:
            self.bg_cache_widget.setVisible(False)
            return
        if cached >= total:
            self.lbl_cache_status.setText(f"✓ Caché SSD ({cached}/{total})")
            self.progress_cache.setValue(total)
            QTimer.singleShot(1000, lambda: self.bg_cache_widget.setVisible(False))
            return

        self.bg_cache_widget.setVisible(True)
        self.progress_cache.setRange(0, total)
        self.progress_cache.setValue(cached)
        pct = int((cached / total) * 100)
        self.lbl_cache_status.setText(f"Indexando SSD: {cached}/{total} ({pct}%)")

    def toggle_inspector(self) -> None:
        self.set_inspector_visible(not self.property_inspector.isVisible())

    def set_inspector_visible(self, visible: bool) -> None:
        self.property_inspector.setVisible(visible)
        self.right_tab_bar.set_active_tab("inspector" if visible else None)
        if visible:
            sizes = self.main_splitter.sizes()
            if len(sizes) == 3 and sizes[2] < 50:
                self.main_splitter.setSizes([sizes[0], max(300, sizes[1] - 300), 300])

    def toggle_markups_panel(self) -> None:
        self.set_markups_panel_visible(not self.markups_panel.isVisible())

    def set_markups_panel_visible(self, visible: bool) -> None:
        self.markups_panel.setVisible(visible)
        self.btn_toggle_markups.setChecked(visible)
        if visible:
            sizes = self.viewer_splitter.sizes()
            if len(sizes) == 2 and sizes[1] < 40:
                total = sum(sizes) or 750
                self.viewer_splitter.setSizes([max(300, total - 200), 200])

    def set_markups_count(self, count: int) -> None:
        self.btn_toggle_markups.setText(f"Marcas ({count})")

    def apply_bottom_bar_icons(self) -> None:
        """Aplica los iconos de la barra inferior (Methods Down; reactivo al tema)."""
        self.btn_toggle_markups.setIcon(ThemeManager.get_icon("list", size=14))

    def toggle_panel(self, panel_id: str) -> None:
        is_hidden = self.panel_stack.isHidden()
        curr_idx = self.panel_stack.currentIndex()
        tgt_idx = 0 if panel_id == "project" else 1

        if not is_hidden and curr_idx == tgt_idx:
            self.panel_stack.setVisible(False)
            self.side_tab_bar.set_active_tab(None)
        else:
            self.panel_stack.setCurrentIndex(tgt_idx)
            self.panel_stack.setVisible(True)
            self.side_tab_bar.set_active_tab(panel_id)

    def position_find_bar(self) -> None:
        tb_h = self.nav_toolbar.height()
        x = max(10, self.viewer_container.width() - self.find_bar.width() - 50)
        self.find_bar.move(x, tb_h + 10)

    # =========================================================================
    # EVENTOS DE QT
    # =========================================================================

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._ui_ready:
            return
        self.position_find_bar()
        self.size_grip.setVisible(not self.isMaximized())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if not self._ui_ready:
            return
        self.size_grip.setVisible(not self.isMaximized())

    def closeEvent(self, event) -> None:
        self.window_closed.emit(self.isMaximized(), self.width(), self.height())
        super().closeEvent(event)