"""
Widgets propios del auto-nombrador.

Vivían construidos a mano dentro de ``AutoNamerDialog._init_ui`` (194 líneas) y
``_rebuild_sequence_widgets``. Se extraen aquí porque son componentes con
identidad propia, estado propio y señales propias: el diálogo se limita a
colocarlos y a reaccionar.

Todo su aspecto vive en ``ui/styles/theme.qss`` (objectNames ``autoNamer*``).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ui.styles.style_manager import ThemeManager


class AlertBanner(QFrame):
    """
    Banda de aviso (icono + mensaje) que solo aparece cuando hay algo que advertir.

    Se usa, por ejemplo, cuando las páginas seleccionadas tienen tamaños distintos.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("autoNamerAlertBanner")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        self._icon = QLabel(self)
        self._icon.setObjectName("autoNamerAlertIcon")
        self._icon.setFixedSize(16, 16)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        self._message = QLabel(self)
        self._message.setObjectName("autoNamerAlertMsg")
        self._message.setWordWrap(True)
        layout.addWidget(self._message, 1)

        self.setVisible(False)

    def show_message(self, text: str) -> None:
        """Muestra la banda con el aviso indicado."""
        self._message.setText(text)
        self.setVisible(True)

    def message(self) -> str:
        """Texto del aviso actual (introspección y tests)."""
        return self._message.text()

    def icon_pixmap(self) -> QPixmap:
        """Pixmap actual del icono (introspección y tests)."""
        return self._icon.pixmap()

    def refresh_icon(self) -> None:
        """
        Repinta el icono de aviso con el token ``warning``.

        Es un *pixmap* dependiente del tema, así que hay que refrescarlo cada vez
        que el tema cambia. Sin emojis: icono vectorial de ``ui/icons``.
        """
        color = ThemeManager.tokens().warning
        self._icon.setPixmap(
            ThemeManager.get_icon("alert-triangle", size=16, color=color).pixmap(16, 16)
        )


class ZoneCard(QFrame):
    """
    Tarjeta de una zona de captura: color, etiqueta y texto capturado.

    No conoce al diálogo: publica señales y el diálogo decide qué hacer.
    """

    capture_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, region, index: int, removable: bool, active: bool, parent=None):
        """
        Args:
            region: ``RegionData`` de la zona que representa la tarjeta.
            index: Posición de la zona (se muestra como número de la insignia).
            removable: ``True`` si se puede borrar (nunca con una sola zona).
            active: ``True`` si esta zona es la que recibe el próximo recuadro.
        """
        super().__init__(parent)
        self.setObjectName("autoNamerZoneCard")
        self._region_id = region.region_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        badge = QLabel(f" {index + 1} ", self)
        badge.setObjectName("autoNamerZoneBadge")
        ThemeManager.apply_zone_color(badge, region.color_hex)
        layout.addWidget(badge)

        name = QLabel(region.label, self)
        name.setObjectName("autoNamerZoneName")
        layout.addWidget(name)

        layout.addStretch()

        preview = QLabel(f"[ {region.sample_text or 'Sin capturar'} ]", self)
        preview.setObjectName("autoNamerZonePreview")
        layout.addWidget(preview)

        capture = QPushButton("Capturar", self)
        capture.setObjectName("autoNamerCaptureBtn")
        capture.setFixedSize(68, 24)
        capture.setToolTip(
            f"Hacer clic y luego arrastrar en el plano para definir {region.label}"
        )
        if active:
            ThemeManager.apply_zone_color(capture, region.color_hex)
        capture.clicked.connect(lambda: self.capture_requested.emit(self._region_id))
        layout.addWidget(capture)

        if removable:
            remove = QPushButton(self)
            remove.setFixedSize(22, 22)
            remove.setIcon(ThemeManager.get_icon("trash", size=12))
            remove.setToolTip("Eliminar esta zona")
            remove.clicked.connect(lambda: self.remove_requested.emit(self._region_id))
            layout.addWidget(remove)


class SeparatorRow(QWidget):
    """
    Fila con el separador de texto que une dos zonas consecutivas.

    Se comporta como un ``QLineEdit`` pero con su etiqueta y su señal de cambio,
    para que el diálogo no tenga que conocer los detalles internos.
    """

    edited = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 2, 16, 2)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Texto / Separador intermedio:", self))

        self._edit = QLineEdit(text, self)
        self._edit.setFixedHeight(24)
        self._edit.textChanged.connect(lambda _: self.edited.emit())
        layout.addWidget(self._edit)

    def text(self) -> str:
        """Texto actual del separador."""
        return self._edit.text()

    def set_text(self, text: str) -> None:
        """Fija el texto del separador (al restaurar una plantilla guardada)."""
        self._edit.setText(text)
