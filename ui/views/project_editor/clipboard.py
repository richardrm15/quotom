# ui/views/annotation_controller/clipboard.py
from __future__ import annotations

import copy
import uuid
from typing import TYPE_CHECKING
from PySide6.QtCore import QPointF, QPoint
from core.coordinates import CoordinateConverter
from ui.views.project_editor.commands import CreateAnnotationCommand

if TYPE_CHECKING:
    from PySide6.QtGui import QUndoStack


class AnnotationClipboard:
    """Gestiona el almacenamiento temporal y la duplicación de marcas con asignación de nuevos UUID."""

    def __init__(self):
        self._clipboard_annotations: list[dict] = []
        self._paste_count: int = 0

    @property
    def items(self) -> list[dict]:
        return self._clipboard_annotations

    @items.setter
    def items(self, val: list[dict]):
        self._clipboard_annotations = list(val)

    def clear(self):
        self._clipboard_annotations.clear()
        self._paste_count = 0

    def copy_selected(self, viewer, project_service, scale: float) -> int:
        """Copia las marcas seleccionadas en memoria."""
        sel_annots = viewer.selected_annotations() if hasattr(viewer, "selected_annotations") else []
        if not sel_annots:
            if hasattr(viewer, "copy_selection_to_clipboard"):
                viewer.copy_selection_to_clipboard()
            return 0

        self._clipboard_annotations.clear()
        for item in sel_annots:
            stored = project_service.annotations.get(item.annot_id) if project_service else None
            annot = stored.to_dict() if stored else dict(item.raw_data)
            geom = copy.deepcopy(annot.get("geometry", {}))
            pos = item.pos()
            if pos.x() != 0 or pos.y() != 0:
                dx_pdf = pos.x() / scale
                dy_pdf = -pos.y() / scale
                for k in ("x", "x1", "x2", "anchor_x", "box_x"):
                    if k in geom: geom[k] = float(geom[k]) + dx_pdf
                for k in ("y", "y1", "y2", "anchor_y", "box_y"):
                    if k in geom: geom[k] = float(geom[k]) + dy_pdf

            payload = {
                "type": annot.get("type", "rect"),
                "geometry": geom,
                "style": copy.deepcopy(annot.get("style", {})),
                "content": annot.get("content", ""),
                "subject": annot.get("subject") or annot.get("/Subj", ""),
                "layer": annot.get("layer") or annot.get("/OC", annot.get("discipline", "General")),
                "author": annot.get("author") or annot.get("/T", "Usuario"),
                "status": annot.get("status") or annot.get("/State", "None"),
                "tags": copy.deepcopy(annot.get("tags", [])),
                "properties": copy.deepcopy(annot.get("properties", {})),
                "discipline": annot.get("discipline", "General"),
            }
            self._clipboard_annotations.append(payload)

        self._paste_count = 0
        return len(self._clipboard_annotations)

    def paste(
        self,
        controller,
        viewer,
        project_service,
        undo_stack: QUndoStack,
        target_pos_or_path: QPointF | QPoint | str | None,
        current_page: int,
        current_scale: float,
        current_dims_pts: tuple[float, float],
        default_pdf_path: str | None,
    ) -> list:
        """Pega las marcas del portapapeles con cálculo de vector delta."""
        target_pos = None
        pdf_path = default_pdf_path
        if isinstance(target_pos_or_path, str):
            pdf_path = target_pos_or_path
        elif isinstance(target_pos_or_path, (QPointF, QPoint)):
            target_pos = target_pos_or_path

        if (
            not self._clipboard_annotations
            or not project_service
            or not project_service.annotations.is_available
            or not pdf_path
        ):
            return []

        if not isinstance(target_pos, (QPointF, QPoint)) and hasattr(viewer, "get_mouse_scene_pos_if_inside_pdf"):
            target_pos = viewer.get_mouse_scene_pos_if_inside_pdf()

        if target_pos is None:
            return []

        drawing = project_service.drawings.find(pdf_path)
        if not drawing:
            return []

        scale = current_scale
        w_pts, h_pts = current_dims_pts
        target_pdf = CoordinateConverter.scene_to_pdf(
            (target_pos.x(), target_pos.y()), scale, h_pts, w_pts
        )

        first_geom = self._clipboard_annotations[0].get("geometry", {})
        ref_x = float(first_geom.get("x", first_geom.get("x1", first_geom.get("anchor_x", 0))))
        ref_y = float(first_geom.get("y", first_geom.get("y1", first_geom.get("anchor_y", 0))))
        dx_target = target_pdf[0] - ref_x
        dy_target = target_pdf[1] - ref_y

        viewer.clear_annotation_selection()
        pasted_items = []

        undo_stack.beginMacro(f"Pegar {len(self._clipboard_annotations)} anotaciones")
        try:
            for tmpl in self._clipboard_annotations:
                new_geom = copy.deepcopy(tmpl.get("geometry", {}))
                for k in ("x", "x1", "x2", "anchor_x", "box_x"):
                    if k in new_geom: new_geom[k] = float(new_geom[k]) + dx_target
                for k in ("y", "y1", "y2", "anchor_y", "box_y"):
                    if k in new_geom: new_geom[k] = float(new_geom[k]) + dy_target

                new_id = str(uuid.uuid4())
                created = project_service.annotations.create(
                    drawing_id=drawing.id,
                    page_index=current_page,
                    annot_type=tmpl.get("type", "rect"),
                    geometry=new_geom,
                    style=copy.deepcopy(tmpl.get("style", {})),
                    content=tmpl.get("content", ""),
                    subject=tmpl.get("subject", ""),
                    layer=tmpl.get("layer", "General"),
                    author=tmpl.get("author", "Usuario"),
                    status=tmpl.get("status", "None"),
                    tags=copy.deepcopy(tmpl.get("tags", [])),
                    properties=copy.deepcopy(tmpl.get("properties", {})),
                    annot_id=new_id,
                )
                if created is None:
                    continue
                undo_stack.push(CreateAnnotationCommand(controller, created.to_dict()))
                it = viewer.get_annotation_item(new_id)
                if it:
                    it.setSelected(True)
                    pasted_items.append(it)
        finally:
            undo_stack.endMacro()

        return pasted_items
