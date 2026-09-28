from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import QObject
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

# core/
from core.settings import settings
from core.project import ProjectManager
from core.services import ProjectService

# Fachada de diálogos (único punto autorizado a usar PySide6 para emergentes)
from ui.dialogs import about, ask_text, confirm, error, info, warn

# Widgets compartidos y estilos
from common.widgets.annotation_item import AnnotationGraphicsItem
from common.widgets.page_manager import PageManagerWindow
from common.styles.style_manager import ThemeManager

# Controladores de la feature principal
from ui.views.main_window.project_controller import ProjectController
from ui.views.main_window.view import MainWindowView

# Controladores de la feature del editor técnico (canvas)
from ui.views.project_editor.document_controller import DocumentController
from ui.views.project_editor.annotation_controller import AnnotationController

logger = logging.getLogger("quotom")


class MainWindowController(QObject):
    """
    Controlador Orquestador de la Ventana Principal.
    Conecta la vista con los módulos del núcleo y los subcontroladores especializados.
    """

    def __init__(self, view: MainWindowView, initial_project: str | None = None):
        super().__init__()
        self._view = view
        self._project_mgr = ProjectManager()
        # Servicios de dominio (bloque S6): el orquestador NO llama al repositorio
        # directamente; atraviesa siempre los servicios. El `ProjectManager` se
        # conserva solo como repositorio compartido que se inyecta a los
        # colaboradores que aún no han migrado (p. ej. `PageManagerWindow`).
        self._project_svc = ProjectService(self._project_mgr)
        self._drawing_svc = self._project_svc.drawings
        self._undo_stack = QUndoStack(self)
        # Alcance del undo: un único documento activo a la vez (ver AUDIT_V2_REPORT.md §8 D2).
        self._undo_doc_path: str | None = None

        # Subcontroladores
        self._project_ctrl = ProjectController(self._project_svc, self._undo_stack, parent=self)
        self._doc_ctrl = DocumentController(parent=self)
        self._annot_ctrl = AnnotationController(
            viewer=self._view.viewer,
            project_service=self._project_svc,
            undo_stack=self._undo_stack,
            parent=self,
        )

        self._view.menu_bar.set_undo_stack(self._undo_stack)

        self._connect_signals()
        self._apply_icons()
        self._update_controls_state()

        if initial_project and Path(initial_project).is_dir():
            self._project_ctrl.open_project_from_path(initial_project, parent_widget=self._view)

    def _connect_signals(self) -> None:
        # Ciclo de vida de la ventana
        self._view.window_closed.connect(self._on_window_closed)
        self._view.escape_pressed.connect(self._on_escape_pressed)

        # 1. ProjectController -> MainWindowView / Subcontroladores
        self._project_ctrl.project_opened.connect(self._on_project_opened)
        self._project_ctrl.project_closed.connect(self._on_project_closed)
        self._project_ctrl.drawings_updated.connect(self._on_drawings_updated)
        self._project_ctrl.drawing_renamed.connect(self._on_drawing_renamed)
        self._project_ctrl.drawing_deleted.connect(self._on_drawing_deleted)
        self._project_ctrl.status_message.connect(lambda msg, ms: self._view.status_bar.showMessage(msg, ms))
        self._project_ctrl.saved_notification.connect(self._view.show_saved_indicator)
        self._project_ctrl.error_occurred.connect(lambda title, msg: error(self._view, title, msg))

        # 2. DocumentController -> MainWindowView
        self._doc_ctrl.document_loaded.connect(self._on_document_loaded)
        self._doc_ctrl.page_ready.connect(self._on_page_ready)
        self._doc_ctrl.text_data_ready.connect(self._on_text_data_ready)
        self._doc_ctrl.cache_progress_updated.connect(self._view.set_cache_progress)
        self._doc_ctrl.loading_state_changed.connect(lambda _: self._update_controls_state())
        self._doc_ctrl.reload_prompt_requested.connect(self._handle_external_file_changed_prompt)
        self._doc_ctrl.status_message_requested.connect(lambda msg: self._view.status_bar.showMessage(msg, 3000))
        self._doc_ctrl.error_occurred.connect(lambda err: error(self._view, "Error PDF", err))

        # 3. AnnotationController -> Inspección y Marcas
        self._annot_ctrl.annotation_inspected.connect(self._view.property_inspector.load_annotation)
        self._annot_ctrl.annotations_inspected.connect(self._view.property_inspector.load_annotations)
        self._annot_ctrl.annotation_cleared.connect(lambda: self._view.property_inspector.load_annotation(None))
        self._annot_ctrl.annotation_mutated.connect(self._view.property_inspector.refresh_if_current)
        self._annot_ctrl.markups_updated.connect(self._view.markups_panel.set_annotations)
        self._annot_ctrl.markup_selected.connect(self._view.markups_panel.select_annotation)
        self._annot_ctrl.inspector_requested.connect(self._view.set_inspector_visible)
        self._annot_ctrl.status_message_requested.connect(lambda msg, ms: self._view.status_bar.showMessage(msg, ms))
        self._annot_ctrl.markups_table_refresh_requested.connect(self._annot_ctrl.refresh_markups_table)
        self._undo_stack.indexChanged.connect(lambda _: self._annot_ctrl.refresh_markups_table())

        # 4. NavigationToolBar
        self._view.nav_toolbar.page_changed.connect(lambda p: self._doc_ctrl.request_page(p, preserve_view=True))
        self._view.nav_toolbar.prev_page_requested.connect(self._prev_page)
        self._view.nav_toolbar.next_page_requested.connect(self._next_page)
        self._view.nav_toolbar.manage_pages_requested.connect(self._open_page_manager)
        self._view.nav_toolbar.zoom_in_requested.connect(self._view.viewer.zoom_in)
        self._view.nav_toolbar.zoom_out_requested.connect(self._view.viewer.zoom_out)
        self._view.nav_toolbar.fit_requested.connect(self._view.viewer.fit_in_view)
        self._view.nav_toolbar.tool_mode_requested.connect(self._toggle_tool_mode)
        self._view.nav_toolbar.find_requested.connect(self._open_find_bar)

        # 5. AppMenuBar
        self._view.menu_bar.new_project_requested.connect(lambda: self._project_ctrl.new_project(self._view))
        self._view.menu_bar.open_project_requested.connect(lambda: self._project_ctrl.open_project(self._view))
        self._view.menu_bar.open_recent_requested.connect(lambda p: self._project_ctrl.open_project_from_path(p, self._view))
        self._view.menu_bar.import_drawings_requested.connect(lambda: self._project_ctrl.import_drawings(self._view))
        self._view.menu_bar.close_project_requested.connect(self._project_ctrl.close_project)
        self._view.menu_bar.copy_requested.connect(self._on_copy_requested)
        self._view.menu_bar.paste_requested.connect(self._on_paste_requested)
        self._view.menu_bar.rename_drawing_requested.connect(self._rename_selected_or_current_drawing)
        self._view.menu_bar.delete_drawing_requested.connect(self._delete_selected_or_current_drawing)
        self._view.menu_bar.reload_drawing_requested.connect(lambda: self.reload_current_pdf(force_reindex=True))
        self._view.menu_bar.manage_pages_requested.connect(self._open_page_manager)
        self._view.menu_bar.rename_page_requested.connect(self._rename_current_page)
        self._view.menu_bar.theme_changed.connect(self._set_theme)
        self._view.menu_bar.toggle_theme_requested.connect(self._toggle_theme)
        self._view.menu_bar.fit_requested.connect(self._view.viewer.fit_in_view)
        self._view.menu_bar.zoom_in_requested.connect(self._view.viewer.zoom_in)
        self._view.menu_bar.zoom_out_requested.connect(self._view.viewer.zoom_out)
        self._view.menu_bar.tool_mode_requested.connect(self._toggle_tool_mode)
        self._view.menu_bar.annotation_tool_requested.connect(self._on_annotation_tool_changed)
        self._view.menu_bar.find_requested.connect(self._open_find_bar)
        self._view.menu_bar.toggle_sidebar_requested.connect(lambda: self._view.toggle_panel("project"))
        self._view.menu_bar.toggle_inspector_requested.connect(self._view.toggle_inspector)
        self._view.menu_bar.toggle_markups_requested.connect(self._view.toggle_markups_panel)
        self._view.menu_bar.shortcuts_requested.connect(self._show_shortcuts_dialog)
        self._view.menu_bar.about_requested.connect(self._show_about_dialog)

        # 6. Visor Gráfico
        self._view.viewer.zoom_changed.connect(self._view.nav_toolbar.set_zoom)
        self._view.viewer.tool_mode_changed.connect(self._on_tool_mode_changed)
        self._view.viewer.text_copied.connect(lambda txt: self._view.status_bar.showMessage(f"Texto copiado: {txt[:40]}...", 3000))
        self._view.viewer.annotation_created.connect(self._annot_ctrl.on_annotation_created)
        self._view.viewer.annotation_deleted.connect(self._annot_ctrl.on_annotation_deleted)
        self._view.viewer.annotations_selected.connect(self._annot_ctrl.on_annotations_selected)
        self._view.viewer.annotation_selected.connect(self._on_annotation_selected)
        self._view.viewer.annotation_double_clicked.connect(self._on_annotation_double_clicked)
        self._view.viewer.annotation_text_edited.connect(self._annot_ctrl.on_annotation_text_edited)
        self._view.viewer.annotation_item_moved.connect(self._annot_ctrl.on_annotation_item_moved)
        self._view.viewer.annotation_item_resized.connect(self._annot_ctrl.on_annotation_item_resized)
        self._view.viewer.request_inspect_annotation.connect(self._on_request_inspect_annotation)
        self._view.viewer.request_autofit_annotation.connect(self._annot_ctrl.on_request_autofit_annotation)
        self._view.viewer.request_duplicate_annotation.connect(self._annot_ctrl.on_request_duplicate_annotation)
        self._view.viewer.request_reorder_annotation.connect(self._annot_ctrl.on_request_reorder_annotation)
        self._view.viewer.request_copy_annotations.connect(self._on_copy_requested)
        self._view.viewer.request_paste_annotations.connect(self._annot_ctrl.paste_selection)

        # 7. Inspector de Propiedades
        self._view.property_inspector.annotation_modified.connect(self._annot_ctrl.on_property_inspector_modified)
        self._view.property_inspector.multi_annotations_modified.connect(self._annot_ctrl.on_property_inspector_multi_modified)
        self._view.property_inspector.preview_modified.connect(self._annot_ctrl.on_property_inspector_preview)
        self._view.property_inspector.request_close.connect(lambda: self._view.set_inspector_visible(False))
        self._view.property_inspector.request_duplicate.connect(self._annot_ctrl.on_request_duplicate_annotation)
        self._view.property_inspector.request_delete.connect(self._annot_ctrl.on_annotation_deleted)

        # 8. Panel de Marcas
        self._view.markups_panel.annotation_selected.connect(self._annot_ctrl.on_markups_table_selected)
        self._view.markups_panel.annotation_activated.connect(self._on_markups_table_activated)
        self._view.markups_panel.annotation_delete_requested.connect(self._annot_ctrl.on_annotation_deleted)
        self._view.markups_panel.request_close.connect(lambda: self._view.set_markups_panel_visible(False))
        self._view.markups_panel.count_changed.connect(self._view.set_markups_count)

        # 9. Sidebar
        self._view.sidebar.drawing_selected.connect(self.load_pdf)
        self._view.sidebar.page_selected.connect(self._on_sidebar_page_selected)
        self._view.sidebar.request_new_project.connect(lambda: self._project_ctrl.new_project(self._view))
        self._view.sidebar.request_open_project.connect(lambda: self._project_ctrl.open_project(self._view))
        self._view.sidebar.request_open_recent_project.connect(lambda p: self._project_ctrl.open_project_from_path(p, self._view))
        self._view.sidebar.request_import_drawing.connect(lambda: self._project_ctrl.import_drawings(self._view))
        self._view.sidebar.request_close_project.connect(self._project_ctrl.close_project)
        self._view.sidebar.request_delete_drawing.connect(lambda did: self._project_ctrl.delete_drawing(did, self._view))
        self._view.sidebar.request_rename_drawing.connect(lambda did, name: self._project_ctrl.rename_drawing(did, name, self._view))
        self._view.sidebar.toggle_collapsed.connect(lambda: self._view.toggle_panel("project"))
        self._view.sidebar.request_reload_drawing.connect(lambda p: self.load_pdf(p, force_reindex=True))
        self._view.sidebar.request_manage_pages.connect(self._open_page_manager_for_drawing)
        self._view.sidebar.selection_changed.connect(self._update_controls_state)

        # 10. Herramientas secundarias
        self._view.annotation_toolbar.tool_changed.connect(self._on_annotation_tool_changed)
        self._view.find_bar.search_changed.connect(self._on_find_search_changed)
        self._view.find_bar.find_next.connect(self._on_find_next)
        self._view.find_bar.find_prev.connect(self._on_find_prev)
        self._view.find_bar.closed.connect(self._on_find_closed)

    # =========================================================================
    # LÓGICA DE PROYECTO Y ARCHIVOS
    # =========================================================================

    def _on_project_opened(self, p_data: dict, drawings: list) -> None:
        self._view.panel_stack.setCurrentIndex(0)
        self._view.panel_stack.setVisible(True)
        self._view.side_tab_bar.set_active_tab("project")
        self._view.sidebar.set_project(p_data, drawings)
        self._view.set_window_title(f"BMS BidSuite - Proyecto: {p_data.get('name', '')}")
        self._view.menu_bar.refresh_recent_projects()
        self.close_current_document()
        self._update_controls_state()

    def _on_project_closed(self) -> None:
        self._view.sidebar.set_project(None, [])
        self._view.sidebar.update_recent_projects_ui()
        self.close_current_document()
        self._view.set_window_title("Quotom Viewer")
        self._update_controls_state()

    def _on_drawings_updated(self, drawings: list) -> None:
        self._view.sidebar.set_project(self._project_ctrl.project_info, drawings)
        self._update_controls_state()

    def _on_drawing_renamed(self, drawing_id: int, old_abs_path: str, new_abs_path: str) -> None:
        if old_abs_path:
            self._view.sidebar.invalidate_cache(old_abs_path)
        self._view.sidebar.invalidate_cache(new_abs_path)

        curr_pdf = self._doc_ctrl.current_pdf_path
        if curr_pdf and old_abs_path and Path(old_abs_path).resolve() == Path(curr_pdf).resolve():
            self._doc_ctrl.current_pdf_path = new_abs_path
            self._view.set_window_title(f"BMS BidSuite - [{Path(new_abs_path).name}]")

        if self._doc_ctrl.current_pdf_path:
            self._view.sidebar.highlight_page(self._doc_ctrl.current_pdf_path, self._doc_ctrl.current_page)

    def _on_drawing_deleted(self, drawing_id: int, deleted_abs_path: str) -> None:
        curr_pdf = self._doc_ctrl.current_pdf_path
        if curr_pdf and deleted_abs_path and Path(deleted_abs_path).resolve() == Path(curr_pdf).resolve():
            self.close_current_document()

    def _rename_selected_or_current_drawing(self) -> None:
        did = self._view.sidebar.get_selected_drawing_id()
        if not did and self._doc_ctrl.current_pdf_path:
            drawing_meta = self._drawing_svc.find(self._doc_ctrl.current_pdf_path)
            if drawing_meta:
                did = drawing_meta.id

        if not did:
            return

        drawing = self._drawing_svc.find(did)
        if not drawing:
            return

        curr_name = drawing.name
        new_name, ok = ask_text(
            self._view, "Renombrar Plano", "Nuevo nombre para el plano:", curr_name
        )
        if ok and new_name.strip() and new_name.strip() != curr_name:
            self._project_ctrl.rename_drawing(did, new_name.strip(), self._view)

    def _delete_selected_or_current_drawing(self) -> None:
        did = self._view.sidebar.get_selected_drawing_id()
        if not did and self._doc_ctrl.current_pdf_path:
            drawing_meta = self._drawing_svc.find(self._doc_ctrl.current_pdf_path)
            if drawing_meta:
                did = drawing_meta.id

        if not did:
            return

        drawing = self._drawing_svc.find(did)
        d_name = drawing.name if drawing else "Plano"

        confirmado = confirm(
            self._view,
            "Eliminar Plano",
            f"¿Estás seguro de que deseas eliminar '{d_name}' del proyecto?\n"
            "El archivo PDF será borrado del almacenamiento del proyecto.",
        )
        if confirmado:
            self._project_ctrl.delete_drawing(did, self._view)

    # =========================================================================
    # DOCUMENTO Y RENDERIZADO
    # =========================================================================

    def load_pdf(self, pdf_path: str, initial_page: int | None = None, force_reindex: bool = False) -> None:
        if not self._project_svc.is_active:
            warn(
                self._view,
                "Proyecto Requerido",
                "Los planos PDF solo se pueden abrir si están agregados a un proyecto.\n\n"
                "Por favor, crea o abre un proyecto primero.",
            )
            return

        resolved = self._project_svc.resolve_path(pdf_path) if not Path(pdf_path).is_absolute() else Path(pdf_path)
        if resolved:
            pdf_path = str(resolved)

        if initial_page is None:
            initial_page = self._drawing_svc.last_page(pdf_path)

        d_info = self._drawing_svc.find(pdf_path)
        if d_info and d_info.page_count:
            self._doc_ctrl.total_pages = d_info.page_count

        self._view.status_bar.showMessage("Abriendo plano PDF...")
        self._view.set_window_title(f"BMS BidSuite - [{Path(pdf_path).name}]")
        self._view.sidebar.highlight_page(pdf_path, initial_page)
        self._doc_ctrl.open_document(pdf_path, initial_page, force_reindex=force_reindex)

    def reload_current_pdf(self, force_reindex: bool = True) -> None:
        pdf_path = self._doc_ctrl.current_pdf_path
        if pdf_path and Path(pdf_path).exists():
            self.load_pdf(pdf_path, initial_page=self._doc_ctrl.current_page, force_reindex=force_reindex)

    def close_current_document(self) -> None:
        self._clear_undo_scope()
        self._doc_ctrl.close_document()
        self._view.viewer.clear()
        self._view.nav_toolbar.set_controls_enabled(False, False)
        self._view.bg_cache_widget.setVisible(False)
        self._view.set_window_title("Quotom Viewer")
        self._view.status_bar.showMessage("Sin plano activo.")
        self._update_controls_state()

    # =========================================================================
    # ALCANCE DEL UNDO (un solo documento activo)
    # =========================================================================

    def _sync_undo_scope(self, pdf_path: str) -> None:
        """
        Vacía la pila al cambiar de documento.

        La historia de deshacer no debe cruzar planos: si no se vacía, un Ctrl+Z
        tras cambiar de documento aplicaría un cambio invisible sobre el plano
        anterior. Recargar el **mismo** plano conserva la historia.
        """
        if pdf_path != self._undo_doc_path:
            self._undo_stack.clear()
            self._undo_doc_path = pdf_path

    def _clear_undo_scope(self) -> None:
        """Vacía la pila al cerrar el documento activo."""
        self._undo_stack.clear()
        self._undo_doc_path = None

    def _on_document_loaded(self, pdf_path: str, total_pages: int) -> None:
        # Un único documento activo: la historia de deshacer no cruza planos.
        self._sync_undo_scope(pdf_path)
        self._update_controls_state()
        if self._project_svc.is_active:
            self._drawing_svc.sync_page_count(pdf_path, total_pages)
            self._view.sidebar.update_drawing_page_count(pdf_path, total_pages)

        page_names = (
            self._drawing_svc.page_names(pdf_path)
            if self._project_svc.is_active
            else extract_pdf_page_names(pdf_path)
        )
        self._annot_ctrl.set_page_names(page_names)
        self._view.nav_toolbar.set_page_names(page_names, self._doc_ctrl.current_page)

    def _on_page_ready(self, page_index: int, pixmap, scale: float, dims_pts: tuple, source: str) -> None:
        self._view.viewer.set_page_pixmap(pixmap, preserve_view=self._doc_ctrl.preserve_view_on_render)
        self._annot_ctrl.set_document_context(self._doc_ctrl.current_pdf_path, page_index, scale, dims_pts)
        self._annot_ctrl.load_annotations_for_page(self._doc_ctrl.current_pdf_path, page_index)

        self._view.nav_toolbar.set_pages(page_index, self._doc_ctrl.total_pages)
        self._view.sidebar.highlight_page(self._doc_ctrl.current_pdf_path, page_index)

        self._update_status_display(scale, dims_pts, pixmap.width(), pixmap.height(), source)
        self._update_controls_state()

        if self._drawing_svc.is_available and self._doc_ctrl.current_pdf_path:
            self._drawing_svc.update_last_page(self._doc_ctrl.current_pdf_path, page_index)
            self._view.show_saved_indicator("✓ Guardado")

    def _on_text_data_ready(self, page_index: int, text_data: object) -> None:
        if page_index == self._doc_ctrl.current_page:
            self._view.viewer.set_page_text_data(text_data)
            self._update_search_if_find_bar_active()

    def _handle_external_file_changed_prompt(self, file_path: str) -> None:
        recargar = confirm(
            self._view,
            "Plano Modificado Externamente",
            f"El archivo '{Path(file_path).name}' fue modificado por otra aplicación.\n\n"
            "¿Deseas recargar el plano para actualizar la visualización?",
            default_yes=True,
        )
        if recargar:
            self.reload_current_pdf(force_reindex=True)

    # =========================================================================
    # NAVEGACIÓN Y FOCO
    # =========================================================================

    def _prev_page(self) -> None:
        if not self._doc_ctrl.is_loading and self._doc_ctrl.current_page > 0:
            self._doc_ctrl.request_page(self._doc_ctrl.current_page - 1, preserve_view=True)

    def _next_page(self) -> None:
        if not self._doc_ctrl.is_loading and self._doc_ctrl.current_page < self._doc_ctrl.total_pages - 1:
            self._doc_ctrl.request_page(self._doc_ctrl.current_page + 1, preserve_view=True)

    def _on_sidebar_page_selected(self, abs_path: str, page_index: int) -> None:
        curr_path = self._doc_ctrl.current_pdf_path
        if curr_path and Path(curr_path).resolve() == Path(abs_path).resolve():
            if 0 <= page_index < self._doc_ctrl.total_pages and page_index != self._doc_ctrl.current_page:
                self._doc_ctrl.request_page(page_index, preserve_view=True)
            self._view.sidebar.highlight_page(abs_path, page_index)
        else:
            self.load_pdf(abs_path, initial_page=page_index)

    def _update_controls_state(self) -> None:
        has_doc = self._doc_ctrl.current_pdf_path is not None and self._doc_ctrl.total_pages > 0
        can_nav = has_doc and not self._doc_ctrl.is_loading
        curr_p = self._doc_ctrl.current_page
        tot_p = self._doc_ctrl.total_pages

        self._view.nav_toolbar.set_controls_enabled(has_doc, can_nav, curr_p, tot_p)
        is_proj = self._project_svc.is_active
        has_sel = self._view.sidebar.has_selection()
        self._view.menu_bar.update_states(has_doc=has_doc, is_project_active=is_proj, has_selection=has_sel)

    def _update_status_display(self, scale: float, dims_pts: tuple, w_px: int, h_px: int, source: str) -> None:
        curr_pdf = self._doc_ctrl.current_pdf_path
        if not curr_pdf:
            return
        w_pts, h_pts = dims_pts
        tags = {"ram": " [Caché RAM]", "disk": " [Caché SSD]"}
        tag_cache = tags.get(source, " [Renderizado]")
        self._view.status_bar.showMessage(
            f"Plano: {Path(curr_pdf).name} | Página {self._doc_ctrl.current_page + 1}/{self._doc_ctrl.total_pages} | "
            f"Dimensiones: {int(w_pts)}x{int(h_pts)} pt (~{int(w_pts/72)}\"x{int(h_pts/72)}\") | "
            f"Bitmap: {w_px}x{h_px} px (Escala: {scale:.2f}x){tag_cache}"
        )

    def _on_copy_requested(self) -> None:
        focus = QApplication.focusWidget()
        # Solo los campos de texto tienen `copy`; el tipo lo garantiza (no hay que
        # sondear la capacidad).
        if type(focus).__name__ in ("QLineEdit", "QTextEdit", "QPlainTextEdit"):
            focus.copy()
            return
        self._annot_ctrl.copy_selection()

    def _on_paste_requested(self) -> None:
        focus = QApplication.focusWidget()
        if type(focus).__name__ in ("QLineEdit", "QTextEdit", "QPlainTextEdit"):
            focus.paste()
            return
        self._annot_ctrl.paste_selection()

    def _on_annotation_tool_changed(self, tool_id: str) -> None:
        tool_names = {
            "select": "Puntero / Selección", "line": "Línea simple", "arrow": "Flecha directriz",
            "rect": "Rectángulo", "circle": "Círculo / Elipse", "cloud": "Nube de Revisión",
            "text": "Texto libre", "callout": "Llamada con flecha"
        }
        self._view.status_bar.showMessage(f"Herramienta activa: {tool_names.get(tool_id, tool_id.capitalize())}", 2500)

        if tool_id in ("select", ""):
            self._view.nav_toolbar.set_tool_mode("select")
            self._view.viewer.set_tool_mode("select")
            self._view.viewer.set_annotation_tool("select")
        else:
            self._view.nav_toolbar.set_tool_mode("annotation")
            self._view.viewer.set_annotation_tool(tool_id)
            self._view.set_inspector_visible(True)
            self._view.property_inspector.load_tool_template(tool_id)

    def _toggle_tool_mode(self, mode: str) -> None:
        if self._view.viewer.tool_mode() == mode:
            self._view.annotation_toolbar.clear_selection()
            self._view.viewer.set_tool_mode("select")
            self._view.nav_toolbar.set_tool_mode("select")
        else:
            self._view.annotation_toolbar.clear_selection()
            self._view.viewer.set_tool_mode(mode)
            self._view.nav_toolbar.set_tool_mode(mode)

    def _on_tool_mode_changed(self, mode: str) -> None:
        self._view.nav_toolbar.set_tool_mode(mode)
        if mode in ("pan", "text_select"):
            self._view.annotation_toolbar.clear_selection()

    def _on_escape_pressed(self) -> None:
        if getattr(self._view.viewer, "_is_drawing_annotation", False):
            self._view.viewer.cancel_drawing_annotation()
            return
        if self._view.viewer.annotation_tool() != "select" or self._view.viewer.tool_mode() != "select":
            self._view.annotation_toolbar.clear_selection()
            self._view.viewer.set_tool_mode("select")
            self._view.nav_toolbar.set_tool_mode("select")
            return
        self._view.viewer.clear_selection()

    def _on_annotation_selected(self, item) -> None:
        if self._view.property_inspector.isVisible():
            if getattr(self._view.property_inspector, "_is_template_mode", False):
                return
            if len(getattr(self._view.property_inspector, "_multi_annot_ids", [])) > 1:
                return
        self._annot_ctrl.on_annotation_selected(item)

    def _on_annotation_double_clicked(self, item) -> None:
        if item and hasattr(item, "annot_type") and item.annot_type in ("text", "callout"):
            self._view.viewer.start_inline_text_edit(item)
            return
        self._view.set_inspector_visible(True)
        self._annot_ctrl.on_annotation_selected(item)

    def _on_request_inspect_annotation(self, annot_id: str) -> None:
        self._view.set_inspector_visible(True)
        selected = [it for it in self._view.viewer.selected_items() if isinstance(it, AnnotationGraphicsItem)]
        item = self._view.viewer.get_annotation_item(annot_id)
        if item and item in selected and len(selected) > 1:
            self._annot_ctrl.on_annotations_selected(selected)
        elif item:
            self._annot_ctrl.on_annotation_selected(item)

    def _on_markups_table_activated(self, annot_id: str, page_index: int) -> None:
        if not annot_id:
            return
        if page_index != self._doc_ctrl.current_page:
            self._doc_ctrl.request_page(page_index, preserve_view=True)

        item = self._view.viewer.get_annotation_item(annot_id)
        if item:
            self._view.viewer.clear_selection()
            item.setSelected(True)
            self._view.viewer.centerOn(item)
            self._view.set_inspector_visible(True)
            self._annot_ctrl.on_annotation_selected(item)

    # =========================================================================
    # DIÁLOGOS Y GESTIÓN DE PÁGINAS
    # =========================================================================

    def _open_page_manager(self) -> None:
        curr_pdf = self._doc_ctrl.current_pdf_path
        if not curr_pdf or self._doc_ctrl.total_pages <= 0:
            info(self._view, "Sin plano abierto", "Abre o importa un plano PDF antes de abrir el gestor.")
            return

        dialog = PageManagerWindow(
            pdf_path=curr_pdf,
            project_manager=self._project_mgr,
            initial_page=self._doc_ctrl.current_page,
            parent=self._view,
            shared_cache=self._doc_ctrl.cache,
            disk_cache=self._doc_ctrl.disk_cache,
        )
        dialog.pages_saved.connect(self._on_pages_saved_from_manager)
        dialog.exec()

    def _open_page_manager_for_drawing(self, pdf_path: str) -> None:
        if not pdf_path or not Path(pdf_path).exists():
            return
        if self._doc_ctrl.current_pdf_path != pdf_path:
            self.load_pdf(pdf_path, initial_page=0)
        self._open_page_manager()

    def _on_pages_saved_from_manager(self, pdf_path: str, new_page_index: int) -> None:
        self._doc_ctrl.clear_cache(pdf_path)
        if self._project_svc.is_active:
            self._view.sidebar.invalidate_cache(pdf_path)
            self._view.sidebar.set_project(self._project_ctrl.project_info, self._project_ctrl.get_drawings())
            self._view.sidebar.highlight_drawing(pdf_path)
        self.load_pdf(pdf_path, initial_page=new_page_index)

    def _rename_current_page(self) -> None:
        curr_pdf = self._doc_ctrl.current_pdf_path
        if not curr_pdf or self._doc_ctrl.total_pages <= 0:
            return

        current_names = (
            self._drawing_svc.page_names(curr_pdf)
            if self._project_svc.is_active
            else extract_pdf_page_names(curr_pdf)
        )
        curr_page = self._doc_ctrl.current_page
        current_name = current_names[curr_page] if curr_page < len(current_names) else f"Página {curr_page + 1}"

        new_name, ok = ask_text(
            self._view, "Renombrar Página", f"Nuevo nombre para la Página {curr_page + 1}:", current_name
        )
        if not ok:
            return

        clean_name = new_name.strip() or f"Página {curr_page + 1}"
        if clean_name != current_name:
            drawing = self._drawing_svc.find(curr_pdf) if self._project_svc.is_active else None
            drawing_id = drawing.id if drawing else 0
            self._project_ctrl.rename_page(drawing_id, curr_pdf, curr_page, current_name, clean_name)
            self._view.sidebar.invalidate_cache(curr_pdf)
            page_names = self._drawing_svc.page_names(curr_pdf)
            self._annot_ctrl.set_page_names(page_names)
            self._view.nav_toolbar.set_page_names(page_names, curr_page)
            self._view.status_bar.showMessage(f"Página {curr_page + 1} renombrada a '{clean_name}'.", 4000)

    def _open_find_bar(self) -> None:
        if not self._doc_ctrl.current_pdf_path or self._doc_ctrl.total_pages <= 0:
            return
        self._view.position_find_bar()
        self._view.find_bar.open_bar(initial_query=self._view.viewer.selected_text.strip())

    def _on_find_search_changed(self, query: str, match_case: bool) -> None:
        total = self._view.viewer.execute_search(query, match_case)
        self._view.find_bar.set_match_status(self._view.viewer.current_match_idx, total)

    def _on_find_next(self) -> None:
        curr = self._view.viewer.next_search_match()
        self._view.find_bar.set_match_status(curr, len(self._view.viewer.search_matches))

    def _on_find_prev(self) -> None:
        curr = self._view.viewer.prev_search_match()
        self._view.find_bar.set_match_status(curr, len(self._view.viewer.search_matches))

    def _on_find_closed(self) -> None:
        self._view.viewer.clear_search()
        self._view.viewer.setFocus()

    def _update_search_if_find_bar_active(self) -> None:
        if not self._view.find_bar.isHidden():
            q = self._view.find_bar.get_current_query()
            if q:
                self._on_find_search_changed(q, False)
            else:
                self._view.viewer.clear_search()
                self._view.find_bar.set_match_status(-1, 0)

    # =========================================================================
    # TEMA, CONFIGURACIÓN Y APAGADO
    # =========================================================================

    def _apply_icons(self) -> None:
        self._view.menu_bar.apply_icons()
        self._view.nav_toolbar.apply_icons()
        self._view.apply_bottom_bar_icons()

    def _set_theme(self, mode: str) -> None:
        """Aplica el modo solicitado (a diferencia de ``_toggle_theme``, no alterna)."""
        if ThemeManager.current_mode() == mode:
            return
        ThemeManager.apply_theme(mode)
        self._refresh_widget_themes(mode)

    def _toggle_theme(self) -> str:
        """
        Alterna claro/oscuro y refresca los widgets que pintan por sí mismos.

        ``ThemeManager.toggle_theme()`` ya aplica el tema globalmente, así que aquí
        **no** se vuelve a llamar a ``apply_theme_to_app``: hacerlo repetía el
        *restyle* de todo el árbol de widgets dos veces por clic.
        """
        new_mode = ThemeManager.toggle_theme()
        self._refresh_widget_themes(new_mode)
        return new_mode

    def _refresh_widget_themes(self, mode: str) -> None:
        """Sincroniza los widgets que cachean colores/tokens del tema activo."""
        self._view.menu_bar.sync_theme_checks(mode)
        if hasattr(self._view.custom_title_bar, "apply_theme"):
            self._view.custom_title_bar.apply_theme()
        if hasattr(self._view.find_bar, "apply_theme"):
            self._view.find_bar.apply_theme()

        for widget in (
            self._view.side_tab_bar,
            self._view.annotation_toolbar,
            self._view.property_inspector,
            self._view.markups_panel,
            self._view.right_tab_bar,
            self._view.nav_toolbar,
            self._view.menu_bar,
        ):
            if hasattr(widget, "apply_theme"):
                widget.apply_theme()

        self._apply_icons()
        self._view.viewer.update_canvas_theme()

    def _show_shortcuts_dialog(self) -> None:
        msg = (
            "<h3>Atajos de Teclado - BMS BidSuite</h3>"
            "<table border=\"0\" cellpadding=\"4\">"
            "<tr><td><b>Botón central ratón</b></td><td>Paneo rápido en cualquier modo</td></tr>"
            "<tr><td><b>Esc</b></td><td>Cancelar / Volver a Selección</td></tr>"
            "<tr><td><b>1</b></td><td>Puntero / Selección</td></tr>"
            "<tr><td><b>V / H</b></td><td>Paneo continuo</td></tr>"
            "<tr><td><b>T</b></td><td>Selección de Texto</td></tr>"
            "<tr><td><b>2 - 8</b></td><td>Herramientas de Anotación</td></tr>"
            "<tr><td><b>Supr / Delete</b></td><td>Eliminar Anotación</td></tr>"
            "<tr><td><b>Ctrl+C / Ctrl+V</b></td><td>Copiar / Pegar</td></tr>"
            "<tr><td><b>Ctrl+Z / Ctrl+Y</b></td><td>Deshacer / Rehacer</td></tr>"
            "<tr><td><b>Ctrl+0</b></td><td>Ajustar Plano</td></tr>"
            "<tr><td><b>Ctrl++ / Ctrl+-</b></td><td>Zoom</td></tr>"
            "<tr><td><b>Ctrl+F</b></td><td>Buscar Texto</td></tr>"
            "<tr><td><b>Ctrl+B</b></td><td>Panel Proyecto</td></tr>"
            "<tr><td><b>Ctrl+I</b></td><td>Inspector de Propiedades</td></tr>"
            "<tr><td><b>Ctrl+M</b></td><td>Lista de Marcas</td></tr>"
            "<tr><td><b>Ctrl+T</b></td><td>Alternar Tema Claro / Oscuro</td></tr>"
            "</table>"
        )
        info(self._view, "Atajos de Teclado", msg)

    def _show_about_dialog(self) -> None:
        msg = (
            "<h2>Quotom Viewer</h2>"
            "<p><b>Versión:</b> 2.0.0 (Fase 2)</p>"
            "<p>Sistema profesional de visualización de planos técnicos de gran escala "
            "y preparación para cómputo métrico (Quantity Take-Off).</p>"
            "<hr>"
            "<p><b>Arquitectura y Tecnologías:</b></p>"
            "<ul>"
            "<li><b>Motor Gráfico:</b> PySide6 con Viewport interactivo y Paneo Libre.</li>"
            "<li><b>Renderizado PDF:</b> pypdfium2 (PDFium C++ multi-megapíxeles).</li>"
            "<li><b>Caché Tier 2:</b> Multiprocesamiento paralelo en segundo plano (WebP Lossless).</li>"
            "<li><b>Persistencia:</b> Base de datos SQLite local en modo WAL de alta concurrencia.</li>"
            "</ul>"
            "<p>© 2026 BMS BidSuite. Todos los derechos reservados.</p>"
        )
        about(self._view, "Acerca de BMS BidSuite", msg)

    def _on_window_closed(self, is_maximized: bool, width: int, height: int) -> None:
        settings.set("window.is_maximized", is_maximized, auto_save=False)
        if not is_maximized:
            settings.set("window.width", width, auto_save=False)
            settings.set("window.height", height, auto_save=False)
        settings.save()
        self._doc_ctrl.stop()