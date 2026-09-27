# ui/views/project_controller.py
from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from core.project import ProjectManager
from core.services import ProjectService
from core.settings import settings
from ui.dialogs import PDF_FILES, ask_text, open_files, select_directory
from ui.views.main_window.commands import RenameDrawingCommand, RenamePageCommand

logger = logging.getLogger("quotom")


class ProjectController(QObject):
    """
    Controlador para la gestión del ciclo de vida del proyecto y sus planos.
    Totalmente desacoplado de la interfaz gráfica: se comunica exclusivamente por señales Qt
    y provee métodos de dominio puros (sin diálogos bloqueantes) para creación, apertura e importación.
    """
    project_opened = Signal(dict, list)        # project_info, drawings
    project_closed = Signal()
    drawings_updated = Signal(list)            # drawings
    drawing_renamed = Signal(int, str, str)    # drawing_id, old_abs_path, new_abs_path
    drawing_deleted = Signal(int, str)         # drawing_id, deleted_abs_path
    status_message = Signal(str, int)          # message, timeout_ms
    saved_notification = Signal(str)           # "✓ Guardado"
    error_occurred = Signal(str, str)          # title, error_message

    def __init__(self, project_service: ProjectService, undo_stack=None, parent: QObject | None = None):
        super().__init__(parent)
        # Servicios de dominio: el controlador NO accede a la base de datos directamente.
        # El servicio se recibe ya construido para que exista UNA única instancia
        # compartida por toda la ventana (raíz de composición única).
        self._project_svc = project_service
        self._drawing_svc = project_service.drawings
        self._undo_stack = undo_stack

    # =========================================================================
    # PROPIEDADES DE ESTADO
    # =========================================================================

    @property
    def project_mgr(self) -> ProjectManager:
        """Repositorio subyacente (compatibilidad; preferir los servicios)."""
        return self._project_svc.manager

    @property
    def is_active(self) -> bool:
        return self._project_svc.is_active

    @property
    def project_info(self) -> dict | None:
        info = self._project_svc.info
        return info.to_dict() if info else None

    @property
    def project_service(self) -> ProjectService:
        """Servicio de dominio del proyecto (fuente única para los subcontroladores)."""
        return self._project_svc

    def get_drawings(self) -> list[dict]:
        """Planos del proyecto como diccionarios (contrato que consume la UI)."""
        return [d.to_dict() for d in self._drawing_svc.list()]

    # =========================================================================
    # OPERACIONES PURAS DE DOMINIO (Headless & Test Friendly)
    # =========================================================================

    def create_project(self, folder: Path | str, name: str) -> dict | None:
        """Crea un nuevo proyecto en la carpeta indicada con el nombre dado."""
        try:
            project = self._project_svc.create(str(folder), name.strip())
            settings.add_recent_project(str(folder))
            p_data = project.to_dict()
            drawings = self.get_drawings()
            self.project_opened.emit(p_data, drawings)
            self.status_message.emit(f"Proyecto '{project.name}' creado exitosamente.", 3000)
            return p_data
        except Exception as e:
            logger.error("Error al crear proyecto: %s", e)
            self.error_occurred.emit("Error", f"No se pudo crear el proyecto: {e}")
            return None

    def open_project_from_path(self, folder: Path | str, parent_widget=None) -> dict | None:
        """Abre un proyecto existente desde la carpeta especificada."""
        try:
            project = self._project_svc.open(str(folder))
            p_data = project.to_dict()
            drawings = self.get_drawings()
            settings.add_recent_project(str(folder))
            self.project_opened.emit(p_data, drawings)
            self.status_message.emit(
                f"Proyecto '{project.name}' abierto ({len(drawings)} planos)", 3000
            )
            return p_data
        except Exception as e:
            logger.error("Error al abrir proyecto: %s", e)
            self.error_occurred.emit("Error", f"No se pudo abrir el proyecto: {e}")
            return None

    def close_project(self):
        """Cierra el proyecto activo y libera recursos."""
        if not self._project_svc.is_active:
            return
        info = self._project_svc.info
        p_name = info.name if info else "Proyecto"
        self._project_svc.close()
        self.project_closed.emit()
        self.status_message.emit(f"Proyecto '{p_name}' cerrado.", 3000)

    def import_drawings(self, file_paths: list[str | Path] | None = None, parent_widget=None) -> int:
        """
        Importa planos PDF al proyecto activo.
        Soporta modo puro (pasando lista de rutas) o modo interactivo si se omite la lista.
        """
        if not self._project_svc.is_active:
            self.error_occurred.emit("Aviso", "Primero abre o crea un proyecto.")
            return 0

        # Modo interactivo si no se pasaron rutas
        if file_paths is None or (not isinstance(file_paths, (list, tuple)) and hasattr(file_paths, "winId")):
            widget = file_paths if hasattr(file_paths, "winId") else parent_widget
            default_dir = str(Path.cwd() / "pdf-examples")
            if not Path(default_dir).exists():
                default_dir = str(Path.home())
            files = open_files(
                widget,
                "Seleccionar plano(s) PDF para importar",
                default_dir,
                PDF_FILES,
            )
            if not files:
                return 0
            file_paths = files

        imported_count = 0
        for f in file_paths:
            try:
                self._drawing_svc.import_from(str(f))
                imported_count += 1
            except Exception as e:
                logger.error("Error al importar plano %s: %s", f, e)
                self.error_occurred.emit("Error al importar", f"No se pudo importar '{Path(f).name}': {e}")

        drawings = self.get_drawings()
        self.drawings_updated.emit(drawings)
        self.status_message.emit(
            f"Se importaron {imported_count} plano(s) a la carpeta 'drawings/' del proyecto.",
            3500
        )
        return imported_count

    def rename_drawing(self, drawing_id: int, new_name: str, parent_widget=None) -> dict | None:
        """Renombra un plano en la base de datos y en el sistema de archivos."""
        if not self._drawing_svc.is_available:
            return None

        drawing = self._drawing_svc.get(drawing_id)
        if not drawing:
            return None

        old_name = drawing.name
        old_abs_path = str(self._project_svc.resolve_path(drawing.path) or "")

        try:
            if self._undo_stack is not None and old_name and old_name != new_name:
                # El cambio se ejecuta en redo() del comando; nunca antes de enviarlo.
                self._undo_stack.push(
                    RenameDrawingCommand(self._project_svc, drawing_id, old_name, new_name)
                )
            else:
                self._drawing_svc.rename(drawing_id, new_name)

            updated = self._drawing_svc.find(drawing_id)
            new_abs_path = updated.abs_path if updated else ""
            updated_name = updated.name if updated else ""

            self.drawings_updated.emit(self.get_drawings())
            self.drawing_renamed.emit(drawing_id, old_abs_path, new_abs_path)
            self.status_message.emit(f"Plano renombrado a '{updated_name}'.", 3000)
            self.saved_notification.emit("✓ Guardado")
            return updated.to_dict() if updated else None
        except Exception as e:
            logger.error("Error al renombrar plano: %s", e)
            self.error_occurred.emit("Error al Renombrar", f"No se pudo renombrar el plano: {e}")
            return None

    def delete_drawing(self, drawing_id: int, parent_widget=None):
        """Elimina un plano del proyecto y borra su archivo de disco."""
        if not self._drawing_svc.is_available:
            return

        drawing = self._drawing_svc.get(drawing_id)
        if not drawing:
            return

        d_name = drawing.name or "Plano"
        abs_path = str(self._project_svc.resolve_path(drawing.path) or "")

        self._drawing_svc.delete(drawing_id, delete_file=True)
        self.drawings_updated.emit(self.get_drawings())
        self.drawing_deleted.emit(drawing_id, abs_path)
        self.status_message.emit(f"Plano '{d_name}' eliminado del proyecto.", 3000)

    def rename_page(self, drawing_id: int, pdf_path: str, page_index: int, old_name: str, new_name: str):
        """Renombra una página técnica específica del plano con soporte Undo/Redo."""
        if not self._project_svc.is_active:
            return
        if self._undo_stack is not None and old_name != new_name:
            # El cambio se ejecuta en redo() del comando; nunca antes de enviarlo.
            self._undo_stack.push(
                RenamePageCommand(self._project_svc, drawing_id, page_index, old_name, new_name)
            )
        else:
            self._project_svc.set_drawing_page_name(drawing_id, page_index, new_name)
        self.saved_notification.emit("✓ Guardado")

    # =========================================================================
    # CONVENIENCIA INTERACTIVA CON DIÁLOGOS (Opcional, desacoplada a demanda)
    # =========================================================================

    def new_project(self, parent_widget=None):
        """Abre diálogos para solicitar ruta y nombre, y delega a create_project."""
        folder = select_directory(parent_widget, "Seleccionar ubicación para el nuevo proyecto")
        if not folder:
            return None
        name, ok = ask_text(parent_widget, "Nuevo Proyecto", "Nombre del proyecto:")
        if not ok or not name.strip():
            return None
        return self.create_project(folder, name.strip())

    def open_project(self, parent_widget=None):
        """Abre diálogo para seleccionar carpeta de proyecto y delega a open_project_from_path."""
        folder = select_directory(parent_widget, "Seleccionar carpeta de proyecto")
        if folder:
            return self.open_project_from_path(folder, parent_widget=parent_widget)
        return None
