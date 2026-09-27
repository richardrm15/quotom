# ui/views/annotation_controller.py
from __future__ import annotations

import copy
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QObject, Signal, QPointF, QPoint

from core.geometry_utils import shift_geometry
from core.services import ProjectService
from core.settings import settings
from ui.helpers.text_metrics import calculate_autofit_scene_geometry
from ui.views.project_editor.commands import (
    CreateAnnotationCommand,
    DeleteAnnotationCommand,
    UpdateAnnotationCommand,
)
from core.coordinates import (
    pdf_to_scene_geometry,
    scene_to_pdf_geometry,
)
from ui.views.project_editor.clipboard import AnnotationClipboard

if TYPE_CHECKING:
    from PySide6.QtGui import QUndoStack
    from common.widgets.graphics_view import PlanGraphicsView
    from core.project import ProjectManager

logger = logging.getLogger("quotom")


class AnnotationController(QObject):
    """
    Controlador central para el dominio de anotaciones y cómputo métrico (Quantity Take-Off).
    Orquesta las operaciones CRUD, Undo/Redo, transformación de coordenadas y portapapeles,
    delegando responsabilidades especializadas en sus submódulos.
    """

    annotation_inspected = Signal(object)
    annotations_inspected = Signal(list)
    annotation_cleared = Signal()
    annotation_mutated = Signal(str, dict)
    markups_updated = Signal(list, int)
    markup_selected = Signal(str)
    inspector_requested = Signal(bool)
    status_message_requested = Signal(str, int)
    markups_table_refresh_requested = Signal()

    _DEFAULT_TOOL_STYLE = {
        "rect": {"stroke_color": "#EF4444", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.15},
        "circle": {"stroke_color": "#3B82F6", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.15},
        "cloud": {"stroke_color": "#10B981", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.15},
        "line": {"stroke_color": "#F59E0B", "stroke_width": 2.0},
        "arrow": {"stroke_color": "#8B5CF6", "stroke_width": 2.0},
        "text": {"stroke_color": "#000000", "font_size": 12.0, "font_family": "Arial", "text_align": "left", "shape": "rect"},
        "callout": {"stroke_color": "#EC4899", "stroke_width": 2.0, "font_size": 11.0, "shape": "rect"},
    }

    def __init__(
        self,
        viewer: PlanGraphicsView,
        project_service: ProjectService,
        undo_stack: QUndoStack,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._viewer = viewer
        # Servicios de dominio: el controlador NO accede a la base de datos directamente.
        self._project_svc = project_service
        self._annotation_svc = project_service.annotations
        self._undo_stack = undo_stack

        self._current_pdf_path: str | None = None
        self._current_page: int = 0
        self._current_scale: float = 1.0
        self._current_dims_pts: tuple[float, float] = (0.0, 0.0)
        self._page_names: list[str] = []

        # Submódulos desacoplados
        self._clipboard_mgr = AnnotationClipboard()

    # =========================================================================
    # HELPERS INTERNOS DE CONTROLADOR (DRY)
    # =========================================================================

    def _get_active_drawing(self, pdf_path: str | None = None) -> dict | None:
        """Resuelve y retorna el registro de plano activo en la base de datos."""
        path = pdf_path or self._current_pdf_path
        if not path or not self._project_svc or not self._project_svc.is_active:
            return None
        found = self._project_svc.drawings.find(path)
        return found.to_dict() if found else None

    def _get_annot_and_item(self, annot_id: str):
        """Retorna la tupla (datos_db, item_grafico) para una anotación dada."""
        found = self._annotation_svc.get(annot_id)
        annot = found.to_dict() if found else None
        item = self._viewer.get_annotation_item(annot_id)
        return annot, item

    @staticmethod
    def _to_id_list(annot_ids: str | Iterable[str]) -> list[str]:
        """Normaliza una entrada de IDs individuales o colecciones a una lista limpia."""
        if not annot_ids:
            return []
        if isinstance(annot_ids, str):
            return [annot_ids]
        return list(annot_ids)

    @contextmanager
    def _macro_undo(self, title: str, count: int):
        """Context manager para envolver operaciones por lotes en macros de Undo/Redo."""
        is_macro = count > 1 and self._undo_stack is not None
        if is_macro:
            self._undo_stack.beginMacro(f"{title} ({count})")
        try:
            yield
        finally:
            if is_macro:
                self._undo_stack.endMacro()

    def _notify(self, message: str, timeout: int = 2500):
        """Emite un mensaje de estado hacia la barra inferior."""
        self.status_message_requested.emit(message, timeout)

    # =========================================================================
    # PROPIEDADES DE COMPATIBILIDAD
    # =========================================================================

    @property
    def _clipboard_annotations(self) -> list[dict]:
        return self._clipboard_mgr.items

    @_clipboard_annotations.setter
    def _clipboard_annotations(self, val: list[dict]):
        self._clipboard_mgr.items = val

    @property
    def _paste_count(self) -> int:
        return self._clipboard_mgr._paste_count

    @_paste_count.setter
    def _paste_count(self, val: int):
        self._clipboard_mgr._paste_count = val

    # =========================================================================
    # CONTEXTO DEL DOCUMENTO Y COORDENADAS
    # =========================================================================

    def set_document_context(
        self,
        pdf_path: str | None,
        page_index: int,
        scale: float,
        dims_pts: tuple[float, float],
    ):
        """Actualiza el contexto del plano activo y métricas de escala visual."""
        self._current_pdf_path = pdf_path
        self._current_page = page_index
        self._current_scale = scale
        self._current_dims_pts = dims_pts

    def set_document_metrics(self, scale: float, dims_pts: tuple[float, float]):
        """Actualiza únicamente la escala y dimensiones en puntos del PDF."""
        self._current_scale = scale
        self._current_dims_pts = dims_pts

    def set_page_names(self, page_names: list[str]):
        """Almacena la lista de nombres/títulos legibles de las páginas del PDF."""
        self._page_names = page_names

    def pdf_to_scene_geometry(self, annot_type: str, geom_pdf: dict | str) -> dict:
        """Delega la transformación de coordenadas PDF a coordenadas de escena Qt."""
        return pdf_to_scene_geometry(annot_type, geom_pdf, self._current_scale, self._current_dims_pts)

    def scene_to_pdf_geometry(self, annot_type: str, scene_geom: dict) -> dict:
        """Delega la transformación de coordenadas de escena Qt a coordenadas PDF estándar."""
        return scene_to_pdf_geometry(annot_type, scene_geom, self._current_scale, self._current_dims_pts)

    # =========================================================================
    # RENDERIZADO Y CARGA
    # =========================================================================

    def render_annotation_item(self, annot_data: dict, current_page: int | None = None):
        """Instancia y añade un elemento gráfico en la escena si pertenece a la página visible."""
        page = self._current_page if current_page is None else current_page
        if annot_data.get("page_index") != page:
            return
        scene_geom = self.pdf_to_scene_geometry(annot_data["type"], annot_data["geometry"])
        render_payload = copy.deepcopy(annot_data)
        render_payload["geometry"] = scene_geom
        render_payload["scene_geometry"] = scene_geom
        self._viewer.add_annotation_item(render_payload)

    def load_annotations_for_page(self, pdf_path: str | None = None, page_index: int | None = None):
        """Carga desde SQLite y renderiza todas las anotaciones de la página actual."""
        if pdf_path is not None:
            self._current_pdf_path = pdf_path
        if page_index is not None:
            self._current_page = page_index

        self._viewer.clear_annotations()
        self.annotation_cleared.emit()

        drawing = self._get_active_drawing(self._current_pdf_path)
        if not drawing or not self._annotation_svc.is_available:
            self.markups_updated.emit([], self._current_page)
            return

        annots = [
            a.to_dict() for a in self._annotation_svc.for_page(drawing["id"], self._current_page)
        ]
        for a in annots:
            self.render_annotation_item(a, self._current_page)

        self.refresh_markups_table(self._current_pdf_path, self._current_page)

    def refresh_markups_table(self, pdf_path: str | None = None, current_page: int | None = None):
        """Recarga y notifica todas las anotaciones del plano a la tabla inferior."""
        drawing = self._get_active_drawing(pdf_path)
        page_idx = self._current_page if current_page is None else current_page

        if not drawing or not self._annotation_svc.is_available:
            self.markups_updated.emit([], page_idx)
            return

        all_annots = [a.to_dict() for a in self._annotation_svc.for_drawing(drawing["id"])]
        page_names = self._page_names
        if not page_names and self._current_pdf_path and self._project_svc:
            page_names = list(self._project_svc.drawings.page_names(self._current_pdf_path))
            self._page_names = page_names

        if page_names:
            for annot in all_annots:
                p_idx = annot.get("page_index", 0)
                if 0 <= p_idx < len(page_names) and page_names[p_idx]:
                    annot["page_name"] = page_names[p_idx].strip()
                elif not annot.get("page_name"):
                    annot["page_name"] = f"Página {p_idx + 1}"

        self.markups_updated.emit(all_annots, page_idx)

    # =========================================================================
    # PERSISTENCIA Y COMANDOS DE MUTACIÓN (Undo/Redo)
    # =========================================================================

    def restore_annotation(self, annot_data: dict):
        """Restaura una marca en SQLite y la dibuja de nuevo en la escena (Undo de borrado)."""
        if not self._annotation_svc.is_available:
            return
        annot_id = annot_data["id"]
        restored = self._annotation_svc.restore(annot_id)
        fresh = restored.to_dict() if restored else annot_data
        self.render_annotation_item(fresh, fresh.get("page_index", self._current_page))
        self.markups_table_refresh_requested.emit()

    def remove_annotation(self, annot_id: str):
        """Oculta o borra una marca en SQLite y la elimina de la escena Qt."""
        if not self._annotation_svc.is_available:
            return
        self._annotation_svc.delete(annot_id, soft=True)
        self._viewer.remove_annotation_item(annot_id)
        self.markups_table_refresh_requested.emit()

    def apply_annotation_state(self, annot_id: str, state: dict):
        """Aplica directamente un estado guardado a SQLite y al canvas visual."""
        if not self._annotation_svc.is_available:
            return
        updated = self._annotation_svc.update(annot_id, state)
        item = self._viewer.get_annotation_item(annot_id)
        if item:
            if "geometry" in state:
                scene_geom = self.pdf_to_scene_geometry(item.annot_type, state["geometry"])
                item.setPos(0, 0)
                item.update_data({"scene_geometry": scene_geom, "geometry": scene_geom})
            else:
                item.update_data(state)

        self.annotation_mutated.emit(annot_id, updated.to_dict() if updated else state)
        self.markups_table_refresh_requested.emit()

    def mutate_annotation(
        self,
        annot_id: str,
        old_state: dict,
        new_state: dict,
        description: str = "Modificar anotación",
    ):
        """Canal unificado para cualquier cambio de propiedad de anotación con registro en Undo/Redo."""
        # El cambio lo aplica el comando en redo(); nunca antes de enviarlo al stack.
        cmd = UpdateAnnotationCommand(self, annot_id, old_state, new_state, description=description)
        self._undo_stack.push(cmd)

    # =========================================================================
    # EVENTOS DE INTERACCIÓN Y CRUD
    # =========================================================================

    def on_annotation_created(
        self,
        tool_id: str,
        scene_geom: dict,
        content: str = "",
        pdf_path: str | None = None,
        current_page: int | None = None,
        custom_defaults: dict | None = None,
    ):
        """Crea y persiste una nueva anotación a partir del dibujo interactivo."""
        drawing = self._get_active_drawing(pdf_path)
        if not drawing or not self._annotation_svc.is_available:
            return

        page = self._current_page if current_page is None else current_page
        pdf_geom = self.scene_to_pdf_geometry(tool_id, scene_geom)

        defaults = custom_defaults or settings.get(f"annotations.tool_defaults.{tool_id}", {})
        fallback_style = dict(self._DEFAULT_TOOL_STYLE.get(tool_id, {
            "stroke_color": "#EC4899", "stroke_width": 2.0, "fill_color": "transparent", "font_size": 11.0,
        }))
        fallback_style.update(defaults.get("style", {}))

        properties = defaults.get("properties", {})
        if "discipline" not in properties and defaults.get("discipline"):
            properties["discipline"] = defaults["discipline"]

        tags = defaults.get("tags", [])
        content_default = defaults.get("content", content)
        final_content = content_default if not content and content_default else content

        annot_rec = self._annotation_svc.create(
            drawing_id=drawing["id"],
            page_index=page,
            annot_type=tool_id,
            geometry=pdf_geom,
            style=fallback_style,
            content=final_content,
            subject=defaults.get("subject", ""),
            layer=defaults.get("layer", defaults.get("discipline", properties.get("discipline", "General"))),
            author=defaults.get("author", "Usuario"),
            status=defaults.get("status", "None"),
            tags=tags,
            properties=properties,
        )
        if annot_rec is None:
            return
        annot_rec = annot_rec.to_dict()

        self._undo_stack.push(CreateAnnotationCommand(self, annot_rec))
        self._notify(f"Anotación guardada (ID: {annot_rec['id'][:8]}...)")

        created_item = self._viewer.get_annotation_item(annot_rec["id"])
        if created_item:
            self._viewer.select_annotation_item(annot_rec["id"], clear_others=True)
            self.inspector_requested.emit(True)

            self.annotation_inspected.emit(annot_rec)

            if tool_id in ("text", "callout"):
                self._viewer.start_inline_text_edit(created_item)

        self.refresh_markups_table(pdf_path, page)

    def on_annotation_deleted(self, annot_ids):
        """Maneja la eliminación individual o múltiple de marcas con macro Undo/Redo."""
        ids = self._to_id_list(annot_ids)
        if not ids or not self._annotation_svc.is_available:
            return

        with self._macro_undo("Eliminar anotaciones", len(ids)):
            for aid in ids:
                found = self._annotation_svc.get(aid)
                annot_data = found.to_dict() if found else None
                self._undo_stack.push(DeleteAnnotationCommand(self, aid, annot_data))

        self.annotation_cleared.emit()
        msg = f"{len(ids)} anotaciones eliminadas" if len(ids) > 1 else "Anotación eliminada"
        self._notify(msg)
        self.refresh_markups_table()

    def on_annotation_selected(self, item):
        """Maneja la selección de una anotación individual en la escena."""
        if item and hasattr(item, "annot_id"):
            self.markup_selected.emit(item.annot_id)

        if item and hasattr(item, "raw_data"):
            self._viewer.clear_selection()
            self._viewer.setFocus()

            annot_id = item.annot_id
            found = self._annotation_svc.get(annot_id)
            annot_data = (found.to_dict() if found else None) or item.raw_data
            self.annotation_inspected.emit(annot_data)
        else:
            self.annotation_cleared.emit()

    def on_annotations_selected(self, items: list):
        """Maneja la selección múltiple coordinada con el PropertyInspector."""
        if not items:
            self.annotation_cleared.emit()
            return
        if len(items) == 1:
            self.on_annotation_selected(items[0])
            return

        annot_list = []
        for it in items:
            aid = getattr(it, "annot_id", None)
            found = self._annotation_svc.get(aid) if aid else None
            annot_list.append(found.to_dict() if found else getattr(it, "raw_data", {}))

        self._viewer.clear_selection()
        self._viewer.setFocus()
        self.annotations_inspected.emit(annot_list)

    def on_markups_table_selected(self, annot_id: str, page_index: int | None = None):
        """Sincroniza la selección visual en el canvas al hacer clic en la tabla inferior."""
        if annot_id:
            item = self._viewer.get_annotation_item(annot_id)
            if item:
                self._viewer.select_annotation_item(annot_id, clear_others=True)

    def on_property_inspector_modified(self, annot_id: str, old_state: dict, updates: dict):
        """Aplica cambios individuales desde el panel de propiedades."""
        self.mutate_annotation(annot_id, old_state, updates, description="Modificar propiedad de anotación")

    def on_property_inspector_multi_modified(self, annot_ids: list[str], updates: dict):
        """Aplica cambios simultáneos sobre un conjunto de anotaciones."""
        ids = self._to_id_list(annot_ids)
        if not ids or not self._annotation_svc.is_available:
            return

        with self._macro_undo("Modificar anotaciones", len(ids)):
            for aid in ids:
                found = self._annotation_svc.get(aid)
                annot = found.to_dict() if found else None
                if annot:
                    old_state = {k: annot.get(k) for k in updates.keys()}
                    self.mutate_annotation(aid, old_state, updates, description="Modificación múltiple")

        self._notify(f"{len(ids)} anotaciones actualizadas")

    def on_property_inspector_preview(self, annot_id: str, updates: dict):
        """Previsualiza en tiempo real los cambios mientras se arrastran sliders o se escribe."""
        item = self._viewer.get_annotation_item(annot_id)
        if item:
            item.update_data(updates)

    def on_annotation_text_edited(self, annot_id: str, old_content: str, new_content: str):
        """Manejador tras finalizar la edición inline con doble clic sobre texto/callout."""
        if old_content != new_content:
            self.mutate_annotation(
                annot_id,
                {"content": old_content},
                {"content": new_content},
                description="Editar contenido de texto",
            )
            self._notify("Texto actualizado (Ctrl+Z para deshacer)", 2000)

    def on_annotation_item_moved(self, annot_id: str, dx: float, dy: float, pdf_path: str | None = None):
        """Maneja el desplazamiento de una anotación tras ser arrastrada por el ratón."""
        drawing = self._get_active_drawing(pdf_path)
        annot, item = self._get_annot_and_item(annot_id)
        if not drawing or not annot or not item:
            return

        old_pdf_geom = annot.get("geometry", {})
        old_scene_geom = dict(item.geometry_data)
        new_scene_geom = shift_geometry(old_scene_geom, dx, dy)
        new_pdf_geom = self.scene_to_pdf_geometry(item.annot_type, new_scene_geom)

        self.mutate_annotation(
            annot_id,
            {"geometry": old_pdf_geom},
            {"geometry": new_pdf_geom},
            description="Mover anotación",
        )
        self._notify("Anotación desplazada (Ctrl+Z para deshacer)")

    def on_annotation_item_resized(
        self,
        annot_id: str,
        old_scene_geom: dict,
        new_scene_geom: dict,
        pdf_path: str | None = None,
    ):
        """Maneja el redimensionamiento de una anotación al arrastrar sus extremos."""
        drawing = self._get_active_drawing(pdf_path)
        annot, item = self._get_annot_and_item(annot_id)
        if not drawing or not annot or not item:
            return

        old_pdf_geom = self.scene_to_pdf_geometry(item.annot_type, old_scene_geom)
        new_pdf_geom = self.scene_to_pdf_geometry(item.annot_type, new_scene_geom)

        self.mutate_annotation(
            annot_id,
            {"geometry": old_pdf_geom},
            {"geometry": new_pdf_geom},
            description="Redimensionar anotación",
        )
        self._notify("Anotación redimensionada (Ctrl+Z para deshacer)")

    def on_request_autofit_annotation(self, annot_ids):
        """Ajusta el contenedor al texto mediante las funciones matemáticas desacopladas."""
        ids = self._to_id_list(annot_ids)
        if not ids or not self._annotation_svc.is_available:
            return

        with self._macro_undo("Ajustar tamaño de textos (Auto-fit)", len(ids)):
            for aid in ids:
                annot, item = self._get_annot_and_item(aid)
                if not annot or annot.get("type") != "text" or not item:
                    continue
                old_scene_geom = copy.deepcopy(item.geometry_data)
                new_scene_geom = calculate_autofit_scene_geometry(
                    content=item.content or "", style_data=item.style_data or {}, current_scene_geom=old_scene_geom
                )
                old_pdf_geom = self.scene_to_pdf_geometry("text", old_scene_geom)
                new_pdf_geom = self.scene_to_pdf_geometry("text", new_scene_geom)
                self.mutate_annotation(aid, {"geometry": old_pdf_geom}, {"geometry": new_pdf_geom}, description="Ajustar tamaño al texto (Auto-fit)")

        msg = f"{len(ids)} textos ajustados" if len(ids) > 1 else "Tamaño de texto ajustado"
        self._notify(f"{msg} (Ctrl+Z para deshacer)")

    def on_request_duplicate_annotation(self, annot_ids, pdf_path: str | None = None, current_page: int | None = None):
        """Duplica una o varias marcas desplazándolas ligeramente."""
        ids = self._to_id_list(annot_ids)
        drawing = self._get_active_drawing(pdf_path)
        if not ids or not drawing or not self._annotation_svc.is_available:
            return

        page = self._current_page if current_page is None else current_page

        with self._macro_undo("Duplicar anotaciones", len(ids)):
            for aid in ids:
                annot = db.get_annotation(aid)
                if not annot:
                    continue
                new_geom = shift_geometry(annot.get("geometry", {}), 20.0, -20.0)

                new_annot = db.create_annotation(
                    drawing_id=drawing["id"],
                    page_index=page,
                    annot_type=annot.get("type", "rect"),
                    geometry=new_geom,
                    style=copy.deepcopy(annot.get("style", {})),
                    content=annot.get("content", ""),
                    subject=annot.get("subject", ""),
                    layer=annot.get("layer", annot.get("discipline", "General")),
                    author=annot.get("author", "Usuario"),
                    status=annot.get("status", "None"),
                    tags=copy.deepcopy(annot.get("tags", [])),
                    properties=copy.deepcopy(annot.get("properties", {})),
                )
                self._undo_stack.push(CreateAnnotationCommand(self, new_annot))

        msg = f"{len(ids)} anotaciones duplicadas" if len(ids) > 1 else "Anotación duplicada"
        self._notify(msg)
        self.refresh_markups_table(pdf_path, page)

    def on_request_reorder_annotation(self, annot_id: str, direction: str):
        """Ajusta el orden Z de renderizado de la anotación."""
        item = self._viewer.get_annotation_item(annot_id)
        if not item:
            return
        curr_z = item.zValue()
        new_z = curr_z + 10.0 if direction == "front" else max(1.0, curr_z - 10.0)
        item.setZValue(new_z)
        self.mutate_annotation(
            annot_id,
            {"z_index": curr_z},
            {"z_index": new_z},
            description=f"Enviar al {'frente' if direction == 'front' else 'fondo'}",
        )
        self._notify(f"Anotación enviada al {'frente' if direction == 'front' else 'fondo'}", 2000)

    # =========================================================================
    # PORTAPAPELES (DELEGACIÓN A CLIPBOARD MANAGER)
    # =========================================================================

    def copy_selection(self):
        count = self._clipboard_mgr.copy_selected(self._viewer, self._project_svc, self._current_scale)
        if count > 0:
            self._notify(f"{count} anotación{'es' if count > 1 else ''} copiada{'s' if count > 1 else ''}")

    def paste_selection(
        self,
        target_pos_or_path: QPointF | QPoint | str | None = None,
        page_index: int | None = None,
        target_pos: QPointF | QPoint | None = None,
        pdf_path: str | None = None,
    ):
        pasted = self._clipboard_mgr.paste(
            controller=self,
            viewer=self._viewer,
            project_service=self._project_svc,
            undo_stack=self._undo_stack,
            target_pos_or_path=target_pos_or_path,
            current_page=page_index if page_index is not None else self._current_page,
            current_scale=self._current_scale,
            current_dims_pts=self._current_dims_pts,
            default_pdf_path=pdf_path or self._current_pdf_path,
        )
        if pasted:
            self.on_annotation_selected(pasted[0])
            self._notify(f"{len(pasted)} anotaciones pegadas")
