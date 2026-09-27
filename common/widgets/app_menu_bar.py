from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QUndoStack
from PySide6.QtWidgets import QMenuBar, QMenu

from core.settings import settings
from ui.styles.style_manager import ThemeManager


class AppMenuBar(QMenuBar):
    """
    Barra de menús principal del sistema (File, Edit, Tool, Help).
    """
    # File
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_recent_requested = Signal(str)
    import_drawings_requested = Signal()
    close_project_requested = Signal()

    # Edit
    copy_requested = Signal()
    paste_requested = Signal()
    rename_drawing_requested = Signal()
    delete_drawing_requested = Signal()
    reload_drawing_requested = Signal()
    manage_pages_requested = Signal()
    rename_page_requested = Signal()
    theme_changed = Signal(str)
    toggle_theme_requested = Signal()

    # Tool
    fit_requested = Signal()
    zoom_in_requested = Signal()
    zoom_out_requested = Signal()
    tool_mode_requested = Signal(str)
    annotation_tool_requested = Signal(str)
    find_requested = Signal()
    toggle_sidebar_requested = Signal()
    toggle_inspector_requested = Signal()
    toggle_markups_requested = Signal()

    # Help
    shortcuts_requested = Signal()
    about_requested = Signal()

    def __init__(self, undo_stack: QUndoStack | None = None, parent=None):
        super().__init__(parent)
        self._undo_stack = undo_stack
        self._setup_file_menu()
        self._setup_edit_menu()
        self._setup_tool_menu()
        self._setup_help_menu()
        self.apply_icons()

    def set_undo_stack(self, undo_stack: QUndoStack):
        self._undo_stack = undo_stack
        if hasattr(self, "_act_undo") and hasattr(self, "_act_redo"):
            # Reconectar acciones si ya fueron instanciadas
            pass

    def _setup_file_menu(self):
        self._menu_file = self.addMenu("&File")

        self._act_new_proj = self._menu_file.addAction("&Nuevo Proyecto...")
        self._act_new_proj.setShortcut(QKeySequence("Ctrl+N"))
        self._act_new_proj.triggered.connect(self.new_project_requested.emit)

        self._act_open_proj = self._menu_file.addAction("&Abrir Proyecto...")
        self._act_open_proj.setShortcut(QKeySequence("Ctrl+O"))
        self._act_open_proj.triggered.connect(self.open_project_requested.emit)

        self._menu_recent = self._menu_file.addMenu("Proyectos &Recientes")
        self._menu_file.aboutToShow.connect(self.refresh_recent_projects)
        self.refresh_recent_projects()

        self._menu_file.addSeparator()

        self._act_import = self._menu_file.addAction("&Importar Planos...")
        self._act_import.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self._act_import.triggered.connect(self.import_drawings_requested.emit)

        self._act_close_proj = self._menu_file.addAction("&Cerrar Proyecto")
        self._act_close_proj.setShortcut(QKeySequence("Ctrl+W"))
        self._act_close_proj.triggered.connect(self.close_project_requested.emit)

        self._menu_file.addSeparator()

        self._act_exit = self._menu_file.addAction("&Salir")
        self._act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        self._act_exit.triggered.connect(lambda: self.window().close() if self.window() else None)

    def refresh_recent_projects(self):
        self._menu_recent.clear()
        recent_list = settings.get("general.recent_projects", [])
        if not recent_list:
            act_empty = QAction("(No hay proyectos recientes)", self)
            act_empty.setEnabled(False)
            self._menu_recent.addAction(act_empty)
            return

        for p_str in recent_list:
            p = Path(p_str)
            name = p.name if p.name else p_str
            action = QAction(f"{name}  ({p_str})", self)
            action.triggered.connect(lambda _, path=p_str: self.open_recent_requested.emit(path))
            self._menu_recent.addAction(action)

        self._menu_recent.addSeparator()
        act_clear = QAction("Borrar historial de recientes", self)
        act_clear.triggered.connect(self._clear_recent_projects)
        self._menu_recent.addAction(act_clear)

    def _clear_recent_projects(self):
        settings.set("general.recent_projects", [])
        self.refresh_recent_projects()

    def _setup_edit_menu(self):
        self._menu_edit = self.addMenu("&Edit")

        if self._undo_stack:
            self._act_undo = self._undo_stack.createUndoAction(self, "&Deshacer")
            self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
            self._menu_edit.addAction(self._act_undo)

            self._act_redo = self._undo_stack.createRedoAction(self, "&Rehacer")
            self._act_redo.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Y")])
            self._menu_edit.addAction(self._act_redo)
        else:
            self._act_undo = self._menu_edit.addAction("&Deshacer")
            self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
            self._act_redo = self._menu_edit.addAction("&Rehacer")
            self._act_redo.setShortcut(QKeySequence.StandardKey.Redo)

        self._menu_edit.addSeparator()

        self._act_copy = self._menu_edit.addAction("&Copiar")
        self._act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self._act_copy.triggered.connect(self.copy_requested.emit)

        self._act_paste = self._menu_edit.addAction("&Pegar")
        self._act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        self._act_paste.triggered.connect(self.paste_requested.emit)

        self._menu_edit.addSeparator()

        self._act_rename = self._menu_edit.addAction("&Renombrar Plano Seleccionado...")
        self._act_rename.setShortcut(QKeySequence("F2"))
        self._act_rename.triggered.connect(self.rename_drawing_requested.emit)

        self._act_delete = self._menu_edit.addAction("&Eliminar Plano del Proyecto")
        self._act_delete.setShortcut(QKeySequence("Shift+Delete"))
        self._act_delete.triggered.connect(self.delete_drawing_requested.emit)

        self._act_reload = self._menu_edit.addAction("&Recargar Plano Actual")
        self._act_reload.setShortcuts([QKeySequence("F5"), QKeySequence("Ctrl+R")])
        self._act_reload.triggered.connect(self.reload_drawing_requested.emit)

        self._act_manage_pages = self._menu_edit.addAction("&Gestor de Páginas...")
        self._act_manage_pages.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self._act_manage_pages.triggered.connect(self.manage_pages_requested.emit)

        self._act_rename_page = self._menu_edit.addAction("Renombrar Página &Actual...")
        self._act_rename_page.setShortcut(QKeySequence("Shift+F2"))
        self._act_rename_page.triggered.connect(self.rename_page_requested.emit)

        self._menu_edit.addSeparator()

        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)

        self._act_theme_dark = self._menu_edit.addAction("Modo &Oscuro")
        self._act_theme_dark.setCheckable(True)
        self._act_theme_dark.triggered.connect(lambda: self.theme_changed.emit("dark"))
        self._theme_action_group.addAction(self._act_theme_dark)

        self._act_theme_light = self._menu_edit.addAction("Modo &Claro")
        self._act_theme_light.setCheckable(True)
        self._act_theme_light.triggered.connect(lambda: self.theme_changed.emit("light"))
        self._theme_action_group.addAction(self._act_theme_light)

        curr_mode = ThemeManager.current_mode()
        self._act_theme_dark.setChecked(curr_mode == "dark")
        self._act_theme_light.setChecked(curr_mode == "light")

        self._menu_edit.addSeparator()

        self._act_toggle_theme = self._menu_edit.addAction("&Alternar Tema")
        self._act_toggle_theme.setShortcut(QKeySequence("Ctrl+T"))
        self._act_toggle_theme.triggered.connect(self.toggle_theme_requested.emit)

    def _setup_tool_menu(self):
        self._menu_tool = self.addMenu("&Tool")

        self._act_fit = self._menu_tool.addAction("Ajustar a la &Ventana")
        self._act_fit.setShortcut(QKeySequence("Ctrl+0"))
        self._act_fit.triggered.connect(self.fit_requested.emit)

        self._act_zoom_in = self._menu_tool.addAction("Acercar &Zoom")
        self._act_zoom_in.setShortcut(QKeySequence("Ctrl++"))
        self._act_zoom_in.triggered.connect(self.zoom_in_requested.emit)

        self._act_zoom_out = self._menu_tool.addAction("Alejar Z&oom")
        self._act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self._act_zoom_out.triggered.connect(self.zoom_out_requested.emit)

        self._menu_tool.addSeparator()

        self._act_tool_select = self._menu_tool.addAction("Herramienta &Puntero / Selección")
        self._act_tool_select.setShortcut(QKeySequence("1"))
        self._act_tool_select.triggered.connect(lambda: self.tool_mode_requested.emit("select"))

        self._act_tool_pan = self._menu_tool.addAction("Herramienta &Mano (Paneo)")
        self._act_tool_pan.setShortcuts([QKeySequence("V"), QKeySequence("H")])
        self._act_tool_pan.triggered.connect(lambda: self.tool_mode_requested.emit("pan"))

        self._act_tool_text = self._menu_tool.addAction("Herramienta Seleccionar &Texto")
        self._act_tool_text.setShortcut(QKeySequence("T"))
        self._act_tool_text.triggered.connect(lambda: self.tool_mode_requested.emit("text_select"))

        self._menu_tool.addSeparator()

        drawing_tools = [
            ("line", "Línea simple", "2"),
            ("arrow", "Flecha directriz", "3"),
            ("rect", "Rectángulo", "4"),
            ("circle", "Círculo / Elipse", "5"),
            ("cloud", "Nube de Revisión", "6"),
            ("text", "Texto libre", "7"),
            ("callout", "Llamada con flecha", "8"),
        ]
        self._act_drawing_tools = {}
        for tid, name, key in drawing_tools:
            act = self._menu_tool.addAction(f"Anotación: {name}")
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(lambda _, t=tid: self.annotation_tool_requested.emit(t))
            self._act_drawing_tools[tid] = act

        self._menu_tool.addSeparator()

        self._act_find = self._menu_tool.addAction("&Buscar en página...")
        self._act_find.setShortcut(QKeySequence("Ctrl+F"))
        self._act_find.triggered.connect(self.find_requested.emit)

        self._menu_tool.addSeparator()

        self._act_sidebar = self._menu_tool.addAction("Mostrar / Ocultar &Panel de Proyecto")
        self._act_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        self._act_sidebar.triggered.connect(self.toggle_sidebar_requested.emit)

        self._act_inspector = self._menu_tool.addAction("Mostrar / Ocultar &Inspector de Propiedades")
        self._act_inspector.setShortcut(QKeySequence("Ctrl+I"))
        self._act_inspector.triggered.connect(self.toggle_inspector_requested.emit)

        self._act_markups = self._menu_tool.addAction("Mostrar / Ocultar &Lista de Marcas")
        self._act_markups.setShortcut(QKeySequence("Ctrl+M"))
        self._act_markups.triggered.connect(self.toggle_markups_requested.emit)

    def _setup_help_menu(self):
        self._menu_help = self.addMenu("&Help")

        self._act_shortcuts = self._menu_help.addAction("&Atajos de Teclado...")
        self._act_shortcuts.triggered.connect(self.shortcuts_requested.emit)

        self._act_about = self._menu_help.addAction("&Acerca de BMS BidSuite...")
        self._act_about.triggered.connect(self.about_requested.emit)

    def apply_icons(self):
        self._act_new_proj.setIcon(ThemeManager.get_icon("plus"))
        self._act_open_proj.setIcon(ThemeManager.get_icon("folder"))
        self._act_import.setIcon(ThemeManager.get_icon("file-plus"))
        self._act_reload.setIcon(ThemeManager.get_icon("refresh"))
        self._act_manage_pages.setIcon(ThemeManager.get_icon("layout"))
        self._act_find.setIcon(ThemeManager.get_icon("search"))
        self._act_fit.setIcon(ThemeManager.get_icon("maximize"))
        self._act_zoom_in.setIcon(ThemeManager.get_icon("zoom-in"))
        self._act_zoom_out.setIcon(ThemeManager.get_icon("zoom-out"))
        self._act_sidebar.setIcon(ThemeManager.get_icon("sidebar"))
        self._act_inspector.setIcon(ThemeManager.get_icon("edit"))
        self._act_shortcuts.setIcon(ThemeManager.get_icon("help"))
        self._act_about.setIcon(ThemeManager.get_icon("help"))

    def sync_theme_checks(self, current_mode: str):
        self._act_theme_dark.setChecked(current_mode == "dark")
        self._act_theme_light.setChecked(current_mode == "light")

    def update_states(self, has_doc: bool, is_project_active: bool, has_selection: bool = False):
        self._act_import.setEnabled(is_project_active)
        self._act_close_proj.setEnabled(is_project_active)
        self._act_reload.setEnabled(has_doc)
        self._act_manage_pages.setEnabled(has_doc)
        self._act_rename_page.setEnabled(has_doc)
        self._act_rename.setEnabled(is_project_active and (has_doc or has_selection))
        self._act_delete.setEnabled(is_project_active and (has_doc or has_selection))

        self._act_fit.setEnabled(has_doc)
        self._act_zoom_in.setEnabled(has_doc)
        self._act_zoom_out.setEnabled(has_doc)
        self._act_tool_select.setEnabled(has_doc)
        self._act_tool_pan.setEnabled(has_doc)
        self._act_tool_text.setEnabled(has_doc)
        self._act_find.setEnabled(has_doc)
        self._act_copy.setEnabled(has_doc)
        self._act_paste.setEnabled(has_doc)
        for act in self._act_drawing_tools.values():
            act.setEnabled(has_doc)
