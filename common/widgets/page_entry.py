"""
Campo de entrada camuflado para número de página (Opción 1).
- En reposo se ve exactamente igual que QLabel ("Pág 1 / 157") con fondo transparente.
- Al hacer clic o ganar foco, muestra solo el número actual seleccionado ("1") con un borde de enfoque sutil.
- Al presionar Enter o perder foco, valida el número, emite page_selected(0_based) y vuelve a mostrar "Pág X / Total".
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator, QFocusEvent
from PySide6.QtWidgets import QLineEdit


class PageEntryWidget(QLineEdit):
    page_selected = Signal(int)  # Emite el índice 0-based

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pageEntryWidget")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._current_page: int = 0
        self._total_pages: int = 0
        self._is_editing: bool = False

        self._validator = QIntValidator(1, 1, self)
        self.setValidator(self._validator)

        self.returnPressed.connect(self._commit)
        self._update_display()

    def set_pages(self, current_0_based: int, total: int):
        self._current_page = current_0_based
        self._total_pages = total

        if total > 0:
            self._validator.setRange(1, total)
            self.setEnabled(True)
        else:
            self._validator.setRange(1, 1)
            self.setEnabled(False)

        if not self._is_editing:
            self._update_display()

    def _update_display(self):
        if self._total_pages > 0:
            self.setText(f"Pág {self._current_page + 1} / {self._total_pages}")
        else:
            self.setText("Pág 0 / 0")

    def focusInEvent(self, event: QFocusEvent):
        super().focusInEvent(event)
        if self._total_pages > 0:
            self._is_editing = True
            # Mostrar solo el número de página actual y seleccionarlo todo para tipear de inmediato
            self.setText(str(self._current_page + 1))
            self.selectAll()

    def focusOutEvent(self, event: QFocusEvent):
        super().focusOutEvent(event)
        if self._is_editing:
            self._commit()

    def _commit(self):
        self._is_editing = False
        text = self.text().strip()
        if text.isdigit() and self._total_pages > 0:
            target_1_based = int(text)
            target_0_based = max(0, min(self._total_pages - 1, target_1_based - 1))
            self.page_selected.emit(target_0_based)
        self._update_display()
        self.clearFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._is_editing = False
            self._update_display()
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)
