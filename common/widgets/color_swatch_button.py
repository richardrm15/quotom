"""
Botón de muestra de color pintado con ``QPainter`` (Patrón C: cero QSS inline).

Se usa para los swatches del inspector de propiedades. Reproduce los tres estados
visuales necesarios **sin** ``setStyleSheet``:

* **Color de paleta**: círculo relleno con el color y anillo de selección.
* **Personalizado / sin relleno**: borde discontinuo con texto (``+`` / ``Ø`` / ``✓``).
* **Peligro** ("Sin relleno" seleccionado): acento rojo.

Consume los tokens de ``ThemeManager``, por lo que es reactivo al cambio de tema.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from ui.styles.style_manager import ThemeManager

_BORDER_SUBTLE = QColor(128, 128, 128, 90)
_DANGER = QColor("#EF4444")


class ColorSwatchButton(QAbstractButton):
    """Muestra de color circular con anillo de selección y texto opcional."""

    def __init__(
        self,
        color: str | None = None,
        parent: QWidget | None = None,
        *,
        dashed: bool = False,
        text: str = "",
        danger: bool = False,
        size: int = 24,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("colorSwatch")
        self._color = self._normalize(color)
        self._dashed = dashed
        self._text = text
        self._danger = danger
        self._selected = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------ API pública

    @staticmethod
    def _normalize(color: str | None) -> QColor | None:
        """Convierte un color hex/``None`` en ``QColor`` válido (``None`` si no aplica)."""
        if not color or color == "transparent":
            return None
        parsed = QColor(color)
        return parsed if parsed.isValid() else None

    def set_color(self, color: str | None) -> None:
        """Define el color de relleno (``None`` = vacío/transparente)."""
        self._color = self._normalize(color)
        self.update()

    def set_selected(self, selected: bool) -> None:
        """Activa o desactiva el anillo de selección."""
        if self._selected != bool(selected):
            self._selected = bool(selected)
            self.update()

    def set_dashed(self, dashed: bool) -> None:
        """Activa el borde discontinuo (estado 'personalizado' / 'sin relleno')."""
        self._dashed = bool(dashed)
        self.update()

    def set_badge_text(self, text: str) -> None:
        """Texto superpuesto (``+``, ``Ø``, ``✓``)."""
        self._text = text or ""
        self.update()

    def set_danger(self, danger: bool) -> None:
        """Usa el acento rojo (estado 'Sin relleno' activo)."""
        self._danger = bool(danger)
        self.update()

    def is_selected(self) -> bool:
        """Indica si el swatch está marcado como seleccionado."""
        return self._selected

    # ---------------------------------------------------------------- Pintado

    def sizeHint(self) -> QSize:
        """Tamaño preferido (coincide con el tamaño fijo asignado)."""
        return QSize(self.width(), self.height())

    def paintEvent(self, event) -> None:  # noqa: N802 - API de Qt
        """Dibuja el swatch: relleno, anillo de estado y texto superpuesto."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        tok = ThemeManager.tokens()
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        hovering = self.underMouse()

        # 1. Resolver fondo, borde y trazo según el estado
        if self._danger and self._selected:
            fill = QColor(_DANGER)
            fill.setAlpha(64)
            border, width, style = _DANGER, 2.5, Qt.PenStyle.SolidLine
        elif self._dashed:
            fill = QColor(tok.bg_button_hover if hovering else tok.bg_input)
            border = QColor(tok.primary) if hovering else QColor(tok.border_hover)
            width = 1.5
            style = Qt.PenStyle.SolidLine if hovering else Qt.PenStyle.DashLine
        else:
            fill = self._color or QColor(tok.bg_input)
            border = QColor(tok.text_primary) if self._selected else _BORDER_SUBTLE
            width = 2.5 if self._selected else 1.0
            style = Qt.PenStyle.SolidLine

        pen = QPen(border, width, style)
        if style == Qt.PenStyle.SolidLine:
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(fill)

        radius = rect.width() / 2.0
        painter.drawRoundedRect(rect, radius, radius)

        # 2. Texto superpuesto (+, Ø, ✓)
        if not self._text:
            return

        if self._danger:
            text_color = _DANGER
        elif self._selected and self._color is not None:
            text_color = QColor("#FFFFFF")
        else:
            text_color = QColor(tok.text_secondary)

        painter.setPen(QPen(text_color))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(11.0 if len(self._text) == 1 else 9.0)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
