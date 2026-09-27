"""
Transformación de coordenadas entre el espacio vectorial PDF y la escena gráfica.

El PDF expresa sus coordenadas en puntos tipográficos (1/72 de pulgada) con origen
en la esquina **inferior izquierda** (sistema cartesiano, eje Y hacia arriba).

La escena gráfica de Qt usa píxeles de bitmap con origen en la esquina
**superior izquierda** (eje Y hacia abajo).

Este módulo es 100% lógica de dominio: **no** importa PySide6 ni conoce Qt.
Trabaja con tuplas ``(x, y)`` y diccionarios de geometría serializables.
"""
from __future__ import annotations

import json

Point = tuple[float, float]


class CoordinateConverter:
    """Conversor matemático bidireccional entre la escena gráfica y el PDF."""

    @staticmethod
    def scene_to_pdf(
        scene_point: Point,
        scale_factor: float,
        page_height_pts: float,
        page_width_pts: float = 0.0,
        rotation: int = 0,
        crop_x: float = 0.0,
        crop_y: float = 0.0,
    ) -> Point:
        """
        Convierte una coordenada ``(x, y)`` de la escena Qt a puntos PDF (72 DPI).

        Considera el factor de escala de rasterizado y la rotación intrínseca
        del plano.
        """
        if scale_factor <= 0:
            scale_factor = 1.0

        dx = scene_point[0] / scale_factor
        dy = scene_point[1] / scale_factor
        rot = int(rotation) % 360

        if rot == 90:
            px = crop_x + (page_width_pts - dy)
            py = crop_y + (page_height_pts - dx)
        elif rot == 180:
            px = crop_x + (page_width_pts - dx)
            py = crop_y + dy
        elif rot == 270:
            px = crop_x + dy
            py = crop_y + dx
        else:
            px = crop_x + dx
            py = crop_y + (page_height_pts - dy)

        return px, py

    @staticmethod
    def pdf_to_scene(
        pdf_point: Point,
        scale_factor: float,
        page_height_pts: float,
        page_width_pts: float = 0.0,
        rotation: int = 0,
        crop_x: float = 0.0,
        crop_y: float = 0.0,
    ) -> Point:
        """Convierte una coordenada vectorial PDF a píxeles de la escena Qt."""
        if scale_factor <= 0:
            scale_factor = 1.0

        px = pdf_point[0] - crop_x
        py = pdf_point[1] - crop_y
        rot = int(rotation) % 360

        if rot == 90:
            dx = page_height_pts - py
            dy = page_width_pts - px
        elif rot == 180:
            dx = page_width_pts - px
            dy = py
        elif rot == 270:
            dx = py
            dy = px
        else:
            dx = px
            dy = page_height_pts - py

        return dx * scale_factor, dy * scale_factor


def pdf_to_scene_geometry(
    annot_type: str,
    geom_pdf: dict | str,
    scale: float,
    dims_pts: tuple[float, float],
) -> dict:
    """Transforma geometría en puntos PDF a píxeles de escena Qt."""
    w_pts, h_pts = dims_pts
    if isinstance(geom_pdf, str):
        try:
            geom_pdf = json.loads(geom_pdf)
        except Exception:
            geom_pdf = {}

    if annot_type in ("line", "arrow"):
        p1 = CoordinateConverter.pdf_to_scene(
            (float(geom_pdf.get("x1", 0)), float(geom_pdf.get("y1", 0))),
            scale,
            h_pts,
            w_pts,
        )
        p2 = CoordinateConverter.pdf_to_scene(
            (float(geom_pdf.get("x2", 0)), float(geom_pdf.get("y2", 0))),
            scale,
            h_pts,
            w_pts,
        )
        return {"x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1]}

    if annot_type == "callout":
        p_anchor = CoordinateConverter.pdf_to_scene(
            (float(geom_pdf.get("anchor_x", 0)), float(geom_pdf.get("anchor_y", 0))),
            scale,
            h_pts,
            w_pts,
        )
        p_box = CoordinateConverter.pdf_to_scene(
            (float(geom_pdf.get("box_x", 0)), float(geom_pdf.get("box_y", 0))),
            scale,
            h_pts,
            w_pts,
        )
        return {
            "anchor_x": p_anchor[0],
            "anchor_y": p_anchor[1],
            "box_x": p_box[0],
            "box_y": p_box[1],
            "box_w": float(geom_pdf.get("box_w", 120)) * scale,
            "box_h": float(geom_pdf.get("box_h", 36)) * scale,
        }

    if annot_type == "cloud":
        pts_pdf = geom_pdf.get("points", [])
        scene_pts = []
        for pt in pts_pdf:
            p_scene = CoordinateConverter.pdf_to_scene(
                (float(pt[0]), float(pt[1])), scale, h_pts, w_pts
            )
            scene_pts.append([p_scene[0], p_scene[1]])
        return {"points": scene_pts}

    # Rectángulos / elipses / texto (x, y) en PDF = esquina inferior izquierda
    w = float(geom_pdf.get("w", 0)) * scale
    h = float(geom_pdf.get("h", 0)) * scale
    p_scene = CoordinateConverter.pdf_to_scene(
        (float(geom_pdf.get("x", 0)), float(geom_pdf.get("y", 0))), scale, h_pts, w_pts
    )
    return {"x": p_scene[0], "y": p_scene[1] - h, "w": w, "h": h}


def scene_to_pdf_geometry(
    annot_type: str,
    scene_geom: dict,
    scale: float,
    dims_pts: tuple[float, float],
) -> dict:
    """Transforma geometría en píxeles de escena Qt a puntos vectoriales PDF."""
    w_pts, h_pts = dims_pts

    if annot_type in ("line", "arrow"):
        p1_pdf = CoordinateConverter.scene_to_pdf(
            (scene_geom.get("x1", 0), scene_geom.get("y1", 0)), scale, h_pts, w_pts
        )
        p2_pdf = CoordinateConverter.scene_to_pdf(
            (scene_geom.get("x2", 0), scene_geom.get("y2", 0)), scale, h_pts, w_pts
        )
        return {"x1": p1_pdf[0], "y1": p1_pdf[1], "x2": p2_pdf[0], "y2": p2_pdf[1]}

    if annot_type == "callout":
        p_anchor_pdf = CoordinateConverter.scene_to_pdf(
            (scene_geom.get("anchor_x", 0), scene_geom.get("anchor_y", 0)),
            scale,
            h_pts,
            w_pts,
        )
        p_box_pdf = CoordinateConverter.scene_to_pdf(
            (scene_geom.get("box_x", 0), scene_geom.get("box_y", 0)), scale, h_pts, w_pts
        )
        return {
            "anchor_x": p_anchor_pdf[0],
            "anchor_y": p_anchor_pdf[1],
            "box_x": p_box_pdf[0],
            "box_y": p_box_pdf[1],
            "box_w": float(scene_geom.get("box_w", 120)) / scale,
            "box_h": float(scene_geom.get("box_h", 36)) / scale,
        }

    if annot_type == "cloud":
        pts_scene = scene_geom.get("points", [])
        pdf_pts = []
        for pt in pts_scene:
            p_pdf = CoordinateConverter.scene_to_pdf(
                (float(pt[0]), float(pt[1])), scale, h_pts, w_pts
            )
            pdf_pts.append([p_pdf[0], p_pdf[1]])
        return {"points": pdf_pts}

    w_pdf = float(scene_geom.get("w", 0)) / scale
    h_pdf = float(scene_geom.get("h", 0)) / scale
    p_bottom_left = CoordinateConverter.scene_to_pdf(
        (scene_geom.get("x", 0), scene_geom.get("y", 0) + scene_geom.get("h", 0)),
        scale,
        h_pts,
        w_pts,
    )
    return {"x": p_bottom_left[0], "y": p_bottom_left[1], "w": w_pdf, "h": h_pdf}


__all__ = [
    "Point",
    "CoordinateConverter",
    "pdf_to_scene_geometry",
    "scene_to_pdf_geometry",
]
