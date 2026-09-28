"""
Adaptadores de geometría entre el dominio puro y Qt.

`core/` define `Rect`/`Point` (sin Qt). Este módulo es el **único punto** donde esa
geometría se convierte a tipos de Qt (`QRectF`/`QPointF`), para que la frontera
quede explícita y testeable en lugar de repartida por el código de UI.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF

__all__ = ["to_qrectf", "to_qpointf"]


def to_qrectf(rect) -> QRectF:
    """Convierte cualquier rectángulo con ``x()/y()/width()/height()`` a ``QRectF``."""
    if isinstance(rect, QRectF):
        return rect
    return QRectF(rect.x(), rect.y(), rect.width(), rect.height())


def to_qpointf(point) -> QPointF:
    """Convierte cualquier punto con ``x()/y()`` a ``QPointF``."""
    if isinstance(point, QPointF):
        return point
    return QPointF(point.x(), point.y())
