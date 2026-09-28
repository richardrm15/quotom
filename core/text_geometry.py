"""
Geometría pura del dominio (sin Qt).

``Point`` y ``Rect`` son objetos de valor inmutables que exponen **la misma API de
lectura que** ``QPointF``/``QRectF``: ``x()``, ``y()``, ``width()``, ``height()``,
``left()``, ``right()``, ``top()``, ``bottom()``, ``center()``, ``contains()``,
``intersects()``, ``united()`` y ``adjusted()``.

**Por qué imitan la API de Qt y no son "más pitónicos":** el índice de texto
(``core.text_layer``) y el motor de OCR (``core.ocr_engine``) alimentan directamente
al canvas Qt y al auto-nombrador. Replicar la API de lectura permite que ``core/``
deje de depender de PySide6 (reglas 3/10/15/20) **sin** tocar los ~50 puntos de
consumo donde se leen rectángulos, que es donde un renombrado masivo (``.x()`` →
``.x``) introduciría fallos silenciosos en código sin cobertura de tests.

La conversión a tipos Qt es explícita y se hace en la frontera con
``common.helpers.qt_geometry`` (``to_qrectf`` / ``to_qpointf``).

Los ``Protocol`` ``PointLike`` y ``RectLike`` documentan el tipado estructural: los
consumidores pueden seguir pasando ``QPointF``/``QRectF`` reales a las funciones de
``core/`` y funcionarán, sin que ``core/`` conozca a Qt.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Point", "Rect", "PointLike", "RectLike"]


@runtime_checkable
class PointLike(Protocol):
    """Cualquier objeto con ``x()`` e ``y()`` (``Point`` o ``QPointF``)."""

    def x(self) -> float: ...

    def y(self) -> float: ...


@runtime_checkable
class RectLike(Protocol):
    """Cualquier objeto con la API de lectura de un rectángulo (``Rect`` o ``QRectF``)."""

    def x(self) -> float: ...

    def y(self) -> float: ...

    def width(self) -> float: ...

    def height(self) -> float: ...


class Point:
    """Punto 2D inmutable."""

    __slots__ = ("_x", "_y")

    def __init__(self, x: float = 0.0, y: float = 0.0):
        object.__setattr__(self, "_x", float(x))
        object.__setattr__(self, "_y", float(y))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} es inmutable")

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def __iter__(self):
        return iter((self._x, self._y))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Point):
            return (self._x, self._y) == (other._x, other._y)
        if isinstance(other, tuple):
            return (self._x, self._y) == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._x, self._y))

    def __repr__(self) -> str:
        return f"Point({self._x}, {self._y})"


class Rect:
    """
    Rectángulo alineado a los ejes, inmutable.

    Construcción: ``Rect(x, y, ancho, alto)``. Al ser inmutable no necesita
    constructor de copia (``QRectF(otro)`` → usar ``otro`` directamente).
    """

    __slots__ = ("_x", "_y", "_w", "_h")

    def __init__(self, x: float = 0.0, y: float = 0.0, w: float = 0.0, h: float = 0.0):
        object.__setattr__(self, "_x", float(x))
        object.__setattr__(self, "_y", float(y))
        object.__setattr__(self, "_w", float(w))
        object.__setattr__(self, "_h", float(h))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__} es inmutable")

    # ----------------------------------------------------------- Lectura (API Qt)
    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def width(self) -> float:
        return self._w

    def height(self) -> float:
        return self._h

    def left(self) -> float:
        return self._x

    def right(self) -> float:
        return self._x + self._w

    def top(self) -> float:
        return self._y

    def bottom(self) -> float:
        return self._y + self._h

    def center(self) -> Point:
        return Point(self._x + self._w / 2.0, self._y + self._h / 2.0)

    def to_tuple(self) -> tuple[float, float, float, float]:
        """``(x, y, ancho, alto)``, para serialización."""
        return (self._x, self._y, self._w, self._h)

    # ------------------------------------------------------------- Operaciones
    def contains(self, point: PointLike) -> bool:
        """``True`` si el punto está dentro o sobre el borde (igual que ``QRectF``)."""
        px, py = point.x(), point.y()
        return (self._x <= px <= self._x + self._w) and (self._y <= py <= self._y + self._h)

    def intersects(self, other: RectLike) -> bool:
        """``True`` si ambos rectángulos se solapan (bordes que se tocan no cuentan)."""
        return (
            self._x < other.x() + other.width()
            and other.x() < self._x + self._w
            and self._y < other.y() + other.height()
            and other.y() < self._y + self._h
        )

    def united(self, other: RectLike) -> "Rect":
        """Rectángulo mínimo que contiene a ambos."""
        x0 = min(self._x, other.x())
        y0 = min(self._y, other.y())
        x1 = max(self._x + self._w, other.x() + other.width())
        y1 = max(self._y + self._h, other.y() + other.height())
        return Rect(x0, y0, x1 - x0, y1 - y0)

    def adjusted(self, dx0: float, dy0: float, dx1: float, dy1: float) -> "Rect":
        """Desplaza los cuatro bordes (``dx0, dy0`` = superior-izquierda)."""
        return Rect(
            self._x + dx0,
            self._y + dy0,
            self._w + (dx1 - dx0),
            self._h + (dy1 - dy0),
        )

    # ------------------------------------------------------------- Dunder
    def __eq__(self, other: object) -> bool:
        if isinstance(other, Rect):
            return (self._x, self._y, self._w, self._h) == (
                other._x, other._y, other._w, other._h,
            )
        if isinstance(other, tuple):
            return (self._x, self._y, self._w, self._h) == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._x, self._y, self._w, self._h))

    def __repr__(self) -> str:
        return f"Rect({self._x}, {self._y}, {self._w}, {self._h})"
