"""
Módulo de Gestión de Carpeta de Proyecto y Custodia de Archivos (Project Workspace).

Administra la carpeta raíz seleccionada por el usuario (ej. /Proyectos/Obra_X/):
1. Custodia de planos: Ubica los archivos PDF importados dentro de la subcarpeta 'drawings/'.
2. Rutas relativas: Garantiza la portabilidad completa del proyecto si se traslada la carpeta.
3. Base de datos SQLite local: Centraliza project.db dentro de la raíz del proyecto.
"""

import shutil
from pathlib import Path
import pypdfium2 as pdfium

from core.business_rules import build_pdf_filename, resolve_collision
from core.database import DatabaseManager


class ProjectManager:
    """Administrador del espacio de trabajo del proyecto activo."""

    def __init__(self):
        self._root_dir: Path | None = None
        self._db: DatabaseManager | None = None
        self._project: dict | None = None

    @property
    def is_active(self) -> bool:
        return self._root_dir is not None and self._db is not None and self._project is not None

    @property
    def root_dir(self) -> Path | None:
        return self._root_dir

    @property
    def drawings_dir(self) -> Path | None:
        if not self._root_dir:
            return None
        return self._root_dir / "drawings"

    @property
    def db(self) -> DatabaseManager | None:
        return self._db

    @property
    def project_info(self) -> dict | None:
        return self._project

    def create_project(self, target_folder: Path | str, project_name: str) -> dict:
        """
        Crea una nueva carpeta de proyecto con su estructura estándar:
        <target_folder>/<project_name>/
          ├── drawings/
          └── project.db
        """
        p_name = project_name.strip()
        if not p_name:
            raise ValueError("El nombre del proyecto no puede estar vacío.")

        project_dir = Path(target_folder).resolve() / p_name
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "drawings").mkdir(parents=True, exist_ok=True)

        db_path = project_dir / "project.db"
        db = DatabaseManager(db_path)
        project_data = db.get_or_create_project(p_name)

        self._root_dir = project_dir
        self._db = db
        self._project = project_data
        return project_data

    def open_project(self, project_dir: Path | str) -> dict:
        """
        Abre una carpeta de proyecto existente. Si no tiene project.db o drawings/,
        los inicializa de forma resiliente.
        """
        p_dir = Path(project_dir).resolve()
        if not p_dir.is_dir():
            raise FileNotFoundError(f"La carpeta '{p_dir}' no existe o no es un directorio.")

        (p_dir / "drawings").mkdir(parents=True, exist_ok=True)
        db_path = p_dir / "project.db"
        db = DatabaseManager(db_path)

        project_data = db.get_first_project()
        if not project_data:
            project_data = db.get_or_create_project(p_dir.name)

        self._root_dir = p_dir
        self._db = db
        self._project = project_data
        return project_data

    def close_project(self):
        """Cierra el proyecto actual y desconecta la base de datos."""
        self._root_dir = None
        self._db = None
        self._project = None

    def import_drawing(self, source_pdf_path: Path | str, custom_name: str | None = None) -> dict:
        """
        Copia el PDF original a la subcarpeta 'drawings/' del proyecto para custodia protegida,
        registra su ruta relativa en la base de datos y retorna los datos del plano.
        """
        if not self.is_active or not self._root_dir or not self._db or not self._project:
            raise RuntimeError("No hay un proyecto activo para importar planos.")

        src = Path(source_pdf_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"El archivo fuente '{src}' no existe.")

        drawings_dir = self.drawings_dir
        drawings_dir.mkdir(parents=True, exist_ok=True)

        # Regla de dominio: nombre de archivo seguro + resolución de colisiones.
        dest_filename = resolve_collision(
            build_pdf_filename(src.name),
            exists=lambda name: (drawings_dir / name).exists(),
            is_source=lambda name: (drawings_dir / name).resolve() == src,
        )

        dest_path = drawings_dir / dest_filename
        if dest_path.resolve() != src:
            shutil.copy2(src, dest_path)

        # Determinar número total de páginas con pypdfium2 de forma thread-safe
        from core.pdf_lock import PDFIUM_LOCK
        page_count = 0
        try:
            with PDFIUM_LOCK:
                doc = pdfium.PdfDocument(str(dest_path))
                page_count = len(doc)
                doc.close()
        except Exception:
            pass

        display_name = custom_name.strip() if custom_name and custom_name.strip() else src.stem
        rel_path = f"drawings/{dest_filename}"

        drawing_id = self._db.add_drawing(
            project_id=self._project["id"],
            relative_path=rel_path,
            name=display_name,
            page_count=page_count,
        )

        drawing = self._db.get_drawing(drawing_id)
        if drawing:
            drawing["abs_path"] = str(dest_path)
            return drawing
        return {
            "id": drawing_id,
            "project_id": self._project["id"],
            "path": rel_path,
            "name": display_name,
            "page_count": page_count,
            "abs_path": str(dest_path),
        }

    def update_drawing_last_page(self, drawing_id_or_path: int | str | Path, page_index: int):
        """Actualiza la última página vista de un plano en la base de datos del proyecto."""
        if not self.is_active or not self._db or not self._project:
            return

        if isinstance(drawing_id_or_path, int):
            self._db.update_drawing_last_page(drawing_id_or_path, page_index)
        else:
            rel_path = self.get_relative_path(drawing_id_or_path)
            drawing = self._db.get_drawing_by_path(self._project["id"], rel_path)
            if drawing:
                self._db.update_drawing_last_page(drawing["id"], page_index)

    def get_drawing_last_page(self, drawing_id_or_path: int | str | Path) -> int:
        """Obtiene la última página vista guardada para un plano (por defecto 0)."""
        if not self.is_active or not self._db or not self._project:
            return 0

        if isinstance(drawing_id_or_path, int):
            d = self._db.get_drawing(drawing_id_or_path)
            return d.get("last_page", 0) if d else 0
        else:
            rel_path = self.get_relative_path(drawing_id_or_path)
            d = self._db.get_drawing_by_path(self._project["id"], rel_path)
            return d.get("last_page", 0) if d else 0

    def get_drawings(self) -> list[dict]:
        """Retorna la lista de planos del proyecto con sus rutas absolutas resueltas."""
        if not self.is_active or not self._db or not self._project or not self._root_dir:
            return []

        drawings = self._db.get_drawings(self._project["id"])
        for d in drawings:
            d["abs_path"] = str(self._root_dir / d["path"])
        return drawings

    def rename_drawing(self, drawing_id: int, new_name: str) -> dict:
        """
        Renombra un plano tanto en la base de datos como físicamente en la carpeta 'drawings/'.
        Retorna los datos actualizados del plano con su nueva ruta relativa y absoluta.
        """
        if not self.is_active or not self._db or not self._root_dir or not self.drawings_dir:
            raise RuntimeError("No hay un proyecto activo.")

        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("El nuevo nombre del plano no puede estar vacío.")

        drawing = self._db.get_drawing(drawing_id)
        if not drawing:
            raise ValueError(f"No se encontró el plano con ID {drawing_id}.")

        old_rel_path = drawing["path"]
        old_file = self.resolve_path(old_rel_path)

        drawings_dir = self.drawings_dir
        old_resolved = old_file.resolve() if (old_file and old_file.exists()) else None

        # Regla de dominio: nombre de archivo seguro + resolución de colisiones.
        dest_filename = resolve_collision(
            build_pdf_filename(clean_name),
            exists=lambda name: (drawings_dir / name).exists(),
            is_source=(
                (lambda name: (drawings_dir / name).resolve() == old_resolved)
                if old_resolved is not None
                else None
            ),
        )
        new_file = drawings_dir / dest_filename

        # Renombrar físicamente el archivo en la subcarpeta drawings/ del proyecto
        if old_resolved is not None and new_file.resolve() != old_resolved:
            old_file.rename(new_file)

        new_rel_path = f"drawings/{dest_filename}"

        # Actualizar en la base de datos project.db
        self._db.rename_drawing(drawing_id, clean_name, new_rel_path)

        updated_drawing = self._db.get_drawing(drawing_id)
        if updated_drawing:
            updated_drawing["abs_path"] = str(self._root_dir / updated_drawing["path"])
            return updated_drawing
        return {
            "id": drawing_id,
            "project_id": self._project["id"],
            "path": new_rel_path,
            "name": clean_name,
            "page_count": drawing.get("page_count", 0),
            "abs_path": str(new_file),
        }

    def delete_drawing(self, drawing_id: int, delete_file: bool = True):
        """Elimina el plano de la base de datos y borra su archivo de custodia en drawings/ usando su ruta relativa."""
        if not self.is_active or not self._db or not self._root_dir:
            return

        drawing = self._db.get_drawing(drawing_id)
        if drawing:
            if delete_file:
                rel_path = drawing.get("path")
                if rel_path:
                    file_path = self.resolve_path(rel_path)
                    if file_path and file_path.exists():
                        try:
                            file_path.unlink()
                        except Exception:
                            pass
            self._db.delete_drawing(drawing_id)

    def get_relative_path(self, abs_or_rel_path: str | Path) -> str:
        """Convierte una ruta absoluta o relativa a la forma relativa al proyecto (ej. 'drawings/file.pdf')."""
        p = Path(abs_or_rel_path)
        if self._root_dir and p.is_absolute():
            try:
                return p.relative_to(self._root_dir).as_posix()
            except ValueError:
                pass
        posix = p.as_posix()
        if not posix.startswith("drawings/") and (self._root_dir / "drawings" / p.name).exists():
            return f"drawings/{p.name}"
        return posix

    def resolve_path(self, relative_path: str | Path) -> Path | None:
        if not self._root_dir or not relative_path:
            return None
        return (self._root_dir / relative_path).resolve()

    def find_drawing(self, pdf_path_or_id: Path | str | int) -> dict | None:
        """
        Busca un plano del proyecto por su ruta absoluta/relativa o por su ID.

        Método público (contrato estable) equivalente a ``_find_drawing``.
        """
        return self._find_drawing(pdf_path_or_id)

    def get_drawing_by_id(self, drawing_id: int) -> dict | None:
        """Retorna el registro completo de un plano por su ID (incluye ``abs_path``)."""
        return self._find_drawing(drawing_id)

    def sync_drawing_page_count(
        self, pdf_path_or_id: Path | str | int, page_count: int
    ) -> dict | None:
        """
        Sincroniza en la base de datos el número real de páginas de un plano.

        Es idempotente: solo escribe cuando el conteo almacenado difiere del real.
        Retorna el registro actualizado del plano, o ``None`` si no se encontró.
        """
        if not self.is_active or not self._db:
            return None

        drawing = self._find_drawing(pdf_path_or_id)
        if not drawing:
            return None

        if int(drawing.get("page_count", 0)) != int(page_count):
            self._db.update_drawing_page_count(drawing["id"], int(page_count))
            drawing = self._find_drawing(drawing["id"]) or drawing

        return drawing

    def _find_drawing(self, pdf_path_or_id: Path | str | int) -> dict | None:
        if not self.is_active or not self._db or not self._root_dir:
            return None
        if isinstance(pdf_path_or_id, int):
            d = self._db.get_drawing(pdf_path_or_id)
            if d:
                d["abs_path"] = str(self._root_dir / d["path"])
            return d
        target_path = Path(pdf_path_or_id).resolve()
        for d in self.get_drawings():
            if Path(d["abs_path"]).resolve() == target_path:
                return d
        return None

    def get_drawing_page_names(self, pdf_path_or_id: Path | str | int) -> list[str]:
        """
        Retorna la lista de nombres de página del plano. Combina los nombres extraídos
        del PDF con cualquier nombre personalizado guardado en la base de datos.
        """
        from core.pdf_utils import extract_pdf_page_names

        drawing = self._find_drawing(pdf_path_or_id)
        if not drawing:
            if isinstance(pdf_path_or_id, (str, Path)) and Path(pdf_path_or_id).exists():
                return extract_pdf_page_names(str(pdf_path_or_id))
            return []

        abs_path = drawing.get("abs_path", "")
        names = extract_pdf_page_names(abs_path) if abs_path and Path(abs_path).exists() else []
        total = drawing.get("page_count", len(names))
        if len(names) < total:
            names.extend([f"Página {i + 1}" for i in range(len(names), total)])

        db_names = self._db.get_drawing_pages(drawing["id"])
        for idx, custom_name in db_names.items():
            if 0 <= idx < len(names) and custom_name:
                names[idx] = custom_name

        return names

    def set_drawing_page_name(self, pdf_path_or_id: Path | str | int, page_index: int, new_name: str):
        """Guarda el nombre personalizado de una página individual en la base de datos."""
        if not self.is_active or not self._db:
            return
        drawing = self._find_drawing(pdf_path_or_id)
        if drawing:
            self._db.set_drawing_page_name(drawing["id"], page_index, new_name)

    def update_drawing_pages(
        self,
        pdf_path: Path | str,
        old_to_new_pages: dict[int, int | None],
        new_page_count: int,
        page_names: list[str] | None = None,
    ):
        """Busca el plano correspondiente por ruta y actualiza sus páginas, marcas y nombres en project.db."""
        if not self.is_active or not self._db or not self._root_dir:
            return
        drawing = self._find_drawing(pdf_path)
        if drawing:
            self._db.update_drawing_pages_and_marks(
                drawing["id"], old_to_new_pages, new_page_count, page_names=page_names
            )
