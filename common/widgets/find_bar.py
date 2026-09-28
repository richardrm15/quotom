"""
Barra de Búsqueda Flotante (In-Page Find Bar / Ctrl+F).
Diseño compacto, moderno y flotante sobre el visor de planos.
"""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QFrame,
)
from PySide6.QtGui import QKeyEvent
from common.styles.style_manager import ThemeManager


class FindBar(QFrame):
    """
    Barra flotante de búsqueda para encontrar texto en la página actual del plano.
    Soporta navegación con Enter / Shift+Enter, F3 / Shift+F3 y cierre con Escape.
    """
    search_changed = Signal(str, bool)  # (query, match_case)
    find_next = Signal()
    find_prev = Signal()
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("findBar")
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumWidth(380)

        # Timer para evitar congelamientos en planos densos al tipear rápido
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(200)  # 200 ms de pausa antes de buscar
        self._debounce_timer.timeout.connect(self._emit_search)

        self._setup_ui()
        self._apply_theme()

    def _setup_ui(self):
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Icono indicador de búsqueda
        self._lbl_icon = QLabel(self)
        self._lbl_icon.setFixedSize(16, 16)
        self._lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        # Campo de entrada de texto
        self._input = QLineEdit(self)
        self._input.setObjectName("findInput")
        self._input.setPlaceholderText("Buscar en página... [Enter / F3]")
        self._input.setClearButtonEnabled(True)
        self._input.setFixedHeight(24)
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input, 1, Qt.AlignmentFlag.AlignVCenter)

        # Contador de coincidencias (ej: '3 de 12')
        self._lbl_count = QLabel("", self)
        self._lbl_count.setObjectName("findCountLabel")
        self._lbl_count.setMinimumWidth(65)
        self._lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_count, 0, Qt.AlignmentFlag.AlignVCenter)

        # Botón anterior (Shift+Enter / Shift+F3)
        self._btn_prev = QPushButton(self)
        self._btn_prev.setObjectName("findBtnPrev")
        self._btn_prev.setFixedSize(24, 24)
        self._btn_prev.setToolTip("Coincidencia anterior (Shift+Enter / Shift+F3)")
        self._btn_prev.clicked.connect(self.find_prev.emit)
        layout.addWidget(self._btn_prev, 0, Qt.AlignmentFlag.AlignVCenter)

        # Botón siguiente (Enter / F3)
        self._btn_next = QPushButton(self)
        self._btn_next.setObjectName("findBtnNext")
        self._btn_next.setFixedSize(24, 24)
        self._btn_next.setToolTip("Coincidencia siguiente (Enter / F3)")
        self._btn_next.clicked.connect(self.find_next.emit)
        layout.addWidget(self._btn_next, 0, Qt.AlignmentFlag.AlignVCenter)

        # Botón cerrar (Esc)
        self._btn_close = QPushButton(self)
        self._btn_close.setObjectName("findBtnClose")
        self._btn_close.setFixedSize(24, 24)
        self._btn_close.setToolTip("Cerrar búsqueda (Esc)")
        self._btn_close.clicked.connect(self.close_bar)
        layout.addWidget(self._btn_close, 0, Qt.AlignmentFlag.AlignVCenter)

    def _apply_theme(self):
        """
        Refresca los elementos no declarativos del widget.

        El estilo (marco, input, botones y contador) vive íntegramente en
        ``common/styles/theme.qss``; aquí solo se actualizan los pixmap/iconos, que
        dependen del tema de forma no expresable en QSS.
        """
        self._lbl_icon.setPixmap(ThemeManager.get_icon("search", size=16).pixmap(16, 16))
        self._btn_prev.setIcon(ThemeManager.get_icon("chevron-left", size=14))
        self._btn_next.setIcon(ThemeManager.get_icon("chevron-right", size=14))
        self._btn_close.setIcon(ThemeManager.get_icon("close", size=12))

    def apply_theme(self) -> None:
        """Reaplica el estilo tras un cambio de tema (Methods Down)."""
        self._apply_theme()

    def get_current_query(self) -> str:
        """Retorna la consulta de búsqueda actual (sin espacios extremos)."""
        return self._input.text().strip()

    def _on_text_changed(self, text: str):
        self._debounce_timer.start()

    def _emit_search(self):
        self.search_changed.emit(self._input.text().strip(), False)

    def _update_count_status(self, status: str):
        """Aplica la propiedad CSS dinámica y fuerza la actualización visual en Qt."""
        if self._lbl_count.property("status") != status:
            self._lbl_count.setProperty("status", status)
            self._lbl_count.style().unpolish(self._lbl_count)
            self._lbl_count.style().polish(self._lbl_count)

    def set_match_status(self, current_idx: int, total_matches: int):
        """Actualiza el texto y el estado del contador sin romper las hojas de estilo."""
        if total_matches <= 0:
            if self._input.text().strip():
                self._lbl_count.setText("0 de 0")
                self._update_count_status("error")
            else:
                self._lbl_count.setText("")
                self._update_count_status("default")
            self._btn_prev.setEnabled(False)
            self._btn_next.setEnabled(False)
        else:
            self._lbl_count.setText(f"{current_idx + 1} de {total_matches}")
            self._update_count_status("found")
            self._btn_prev.setEnabled(True)
            self._btn_next.setEnabled(True)

    def open_bar(self, initial_query: str = ""):
        """Abre la barra flotante, enfoca el campo de texto y selecciona el contenido."""
        self.show()
        self.raise_()
        if initial_query:
            self._input.setText(initial_query)
        self._input.setFocus()
        self._input.selectAll()

    def close_bar(self):
        """Detiene temporizadores activos y cierra la barra."""
        self._debounce_timer.stop()
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close_bar()
            event.accept()
            return
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F3):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_prev.emit()
            else:
                self.find_next.emit()
            event.accept()
            return

        super().keyPressEvent(event)