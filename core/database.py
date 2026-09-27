"""
Módulo de Persistencia y Base de Datos SQLite (SQLite Persistence Layer).

Implementa el esquema relacional con modo WAL (Write-Ahead Logging) para
concurrencia de lectura/escritura y claves foráneas activas.
Gestiona:
1. Proyectos (Projects)
2. Custodia de planos importados (Drawings)
3. Partidas de cómputo métrico (TakeOffItems)
4. Marcas y mediciones vectoriales (Marks)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from core.color_utils import sync_style_with_iso


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS Projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Drawings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    last_page INTEGER DEFAULT 0,
    FOREIGN KEY(project_id) REFERENCES Projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS TakeOffItems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    unit TEXT DEFAULT 'UND',
    color TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES Projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS Marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drawing_id INTEGER NOT NULL,
    page INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    tag_number INTEGER,
    x_pdf REAL NOT NULL,
    y_pdf REAL NOT NULL,
    deleted_at DATETIME DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(drawing_id) REFERENCES Drawings(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES TakeOffItems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS DrawingPages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drawing_id INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    page_name TEXT NOT NULL,
    FOREIGN KEY(drawing_id) REFERENCES Drawings(id) ON DELETE CASCADE,
    UNIQUE(drawing_id, page_index)
);

CREATE INDEX IF NOT EXISTS idx_drawings_project ON Drawings(project_id);
CREATE INDEX IF NOT EXISTS idx_marks_drawing_page ON Marks(drawing_id, page);
CREATE INDEX IF NOT EXISTS idx_items_project ON TakeOffItems(project_id);
CREATE INDEX IF NOT EXISTS idx_drawing_pages ON DrawingPages(drawing_id, page_index);

CREATE TABLE IF NOT EXISTS Annotations (
    id TEXT PRIMARY KEY NOT NULL,
    drawing_id INTEGER NOT NULL,
    page_index INTEGER NOT NULL,
    type TEXT NOT NULL,
    geometry JSON NOT NULL,
    style JSON NOT NULL,
    content TEXT,
    subject TEXT DEFAULT NULL,
    layer TEXT DEFAULT 'General',
    status TEXT DEFAULT 'None',
    tags JSON NOT NULL DEFAULT '[]',
    properties JSON NOT NULL DEFAULT '{}',
    discipline TEXT GENERATED ALWAYS AS (json_extract(properties, '$.discipline')) STORED,
    -- Puertos de conexión [N] para conectores futuros (implementables vía plugin).
    -- Arreglo JSON de objetos: [{"id", "name", "side", "index", "x", "y"}]
    -- side: 'top'|'bottom'|'left'|'right'  x,y: [0.0..1.0] normalizado al bounding box
    -- Si vacío ('[]'), el motor usa los 4 puertos automáticos de los 4 lados.
    ports JSON NOT NULL DEFAULT '[]',
    item_id INTEGER DEFAULT NULL,
    tag_number INTEGER DEFAULT NULL,
    author TEXT DEFAULT 'Usuario' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    deleted_at DATETIME DEFAULT NULL,
    FOREIGN KEY(drawing_id) REFERENCES Drawings(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES TakeOffItems(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_annotations_page ON Annotations(drawing_id, page_index) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_annotations_discipline ON Annotations(discipline);

CREATE TABLE IF NOT EXISTS AnnotationRelations (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    metadata JSON DEFAULT '{}' NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (source_id, target_id, relation_type),
    FOREIGN KEY(source_id) REFERENCES Annotations(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES Annotations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_relations_source ON AnnotationRelations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON AnnotationRelations(target_id);
"""


class DatabaseManager:
    """Administrador de conexiones SQLite para la base de datos local del proyecto (project.db)."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            # Migración resiliente para bases de datos existentes
            try:
                cursor = conn.execute("PRAGMA table_info(Drawings);")
                columns = [row["name"] for row in cursor.fetchall()]
                if "last_page" not in columns:
                    conn.execute("ALTER TABLE Drawings ADD COLUMN last_page INTEGER DEFAULT 0;")
            except Exception:
                pass

            # Migración: columnas ISO 'subject' (/Subj) y 'layer' (/OC)
            try:
                cursor = conn.execute("PRAGMA table_info(Annotations);")
                ann_cols = [row["name"] for row in cursor.fetchall()]
                if "subject" not in ann_cols:
                    conn.execute("ALTER TABLE Annotations ADD COLUMN subject TEXT DEFAULT NULL;")
                if "layer" not in ann_cols:
                    conn.execute("ALTER TABLE Annotations ADD COLUMN layer TEXT DEFAULT 'General';")
                if "status" not in ann_cols:
                    conn.execute("ALTER TABLE Annotations ADD COLUMN status TEXT DEFAULT 'None';")
            except Exception:
                pass

            # Migración: columna 'ports' para puertos de conexión multi-N (plugin-ready)
            try:
                cursor = conn.execute("PRAGMA table_info(Annotations);")
                ann_cols = [row["name"] for row in cursor.fetchall()]
                if "ports" not in ann_cols:
                    conn.execute("ALTER TABLE Annotations ADD COLUMN ports JSON NOT NULL DEFAULT '[]';")
            except Exception:
                pass

            # Migración: columna 'source_port_id' y 'target_port_id' en AnnotationRelations
            # Permite que los plugins referencien puertos por ID en vez de solo por nombre de lado
            try:
                cursor = conn.execute("PRAGMA table_info(AnnotationRelations);")
                rel_cols = [row["name"] for row in cursor.fetchall()]
                if "source_port_id" not in rel_cols:
                    conn.execute("ALTER TABLE AnnotationRelations ADD COLUMN source_port_id TEXT DEFAULT NULL;")
                if "target_port_id" not in rel_cols:
                    conn.execute("ALTER TABLE AnnotationRelations ADD COLUMN target_port_id TEXT DEFAULT NULL;")
            except Exception:
                pass

    # --- Operaciones de Proyecto ---

    def get_or_create_project(self, name: str) -> dict:
        """Obtiene el proyecto existente o crea uno nuevo."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM Projects WHERE name = ? LIMIT 1;", (name,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            cursor = conn.execute("INSERT INTO Projects (name) VALUES (?);", (name,))
            project_id = cursor.lastrowid
            cursor = conn.execute("SELECT * FROM Projects WHERE id = ?;", (project_id,))
            return dict(cursor.fetchone())

    def get_first_project(self) -> dict | None:
        """Obtiene el primer proyecto registrado en la base de datos."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM Projects ORDER BY id ASC LIMIT 1;")
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- Operaciones de Planos (Drawings) ---

    def add_drawing(self, project_id: int, relative_path: str, name: str, page_count: int = 0) -> int:
        """Registra un plano en la base de datos con su ruta relativa."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO Drawings (project_id, path, name, page_count)
                VALUES (?, ?, ?, ?);
                """,
                (project_id, relative_path, name, page_count),
            )
            return cursor.lastrowid

    def update_drawing_last_page(self, drawing_id: int, last_page: int):
        """Guarda la última página visualizada por el usuario en el plano."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE Drawings SET last_page = ? WHERE id = ?;",
                (max(0, last_page), drawing_id)
            )

    def get_drawing_by_path(self, project_id: int, relative_path: str) -> dict | None:
        """Busca un plano en la base de datos por su ruta relativa."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM Drawings WHERE project_id = ? AND path = ? LIMIT 1;",
                (project_id, relative_path)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_drawing_page_count(self, drawing_id: int, page_count: int):
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE Drawings SET page_count = ? WHERE id = ?;",
                (page_count, drawing_id)
            )

    def rename_drawing(self, drawing_id: int, new_name: str, new_relative_path: str):
        """Actualiza el nombre visible y la ruta relativa del plano en la base de datos."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE Drawings SET name = ?, path = ? WHERE id = ?;",
                (new_name, new_relative_path, drawing_id),
            )

    def get_drawings(self, project_id: int) -> list[dict]:
        """Obtiene todos los planos asociados a un proyecto."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM Drawings WHERE project_id = ? ORDER BY id ASC;",
                (project_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_drawing(self, drawing_id: int) -> dict | None:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM Drawings WHERE id = ?;", (drawing_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


    def get_drawing_pages(self, drawing_id: int) -> dict[int, str]:
        """Retorna un mapeo {page_index: page_name} de los nombres personalizados guardados."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT page_index, page_name FROM DrawingPages WHERE drawing_id = ? ORDER BY page_index ASC;",
                (drawing_id,),
            )
            return {row["page_index"]: row["page_name"] for row in cursor.fetchall()}

    def set_drawing_page_name(self, drawing_id: int, page_index: int, page_name: str):
        """Guarda o actualiza el nombre personalizado de una página individual."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO DrawingPages (drawing_id, page_index, page_name)
                VALUES (?, ?, ?)
                ON CONFLICT(drawing_id, page_index) DO UPDATE SET page_name = excluded.page_name;
                """,
                (drawing_id, page_index, page_name.strip()),
            )

    def set_drawing_page_names(self, drawing_id: int, page_names: list[str]):
        """Reemplaza atómicamente todos los nombres de página para el plano."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM DrawingPages WHERE drawing_id = ?;", (drawing_id,))
            for idx, name in enumerate(page_names):
                if name and name.strip():
                    conn.execute(
                        "INSERT INTO DrawingPages (drawing_id, page_index, page_name) VALUES (?, ?, ?);",
                        (drawing_id, idx, name.strip()),
                    )

    def update_drawing_pages_and_marks(
        self,
        drawing_id: int,
        old_to_new_pages: dict[int, int | None],
        new_page_count: int,
        page_names: list[str] | None = None,
    ):
        """
        Sincroniza la estructura de páginas del plano con la base de datos tras inserciones,
        duplicaciones, eliminaciones o cambios de nombres:
        1. Elimina marcas de páginas eliminadas (donde new_page es None).
        2. Remapea las marcas existentes a sus nuevos números de página.
        3. Actualiza el conteo total de páginas del plano en Drawings.
        4. Actualiza los nombres personalizados en DrawingPages si se proporcionan.
        """
        with self._get_connection() as conn:
            # 1. Eliminar marcas de páginas descartadas
            for old_p, new_p in old_to_new_pages.items():
                if new_p is None:
                    conn.execute(
                        "DELETE FROM Marks WHERE drawing_id = ? AND page = ?;",
                        (drawing_id, old_p),
                    )

            # 2. Reubicar marcas supervivientes cuyos índices cambiaron
            marks = conn.execute(
                "SELECT id, page FROM Marks WHERE drawing_id = ?;",
                (drawing_id,),
            ).fetchall()

            for row in marks:
                mark_id = row["id"]
                current_p = row["page"]
                if current_p in old_to_new_pages:
                    target_p = old_to_new_pages[current_p]
                    if target_p is not None and target_p != current_p:
                        conn.execute(
                            "UPDATE Marks SET page = ? WHERE id = ?;",
                            (target_p, mark_id),
                        )

            # 3. Actualizar conteo de páginas en Drawings
            conn.execute(
                "UPDATE Drawings SET page_count = ? WHERE id = ?;",
                (new_page_count, drawing_id),
            )

            # 4. Actualizar nombres de página en DrawingPages
            if page_names is not None:
                conn.execute("DELETE FROM DrawingPages WHERE drawing_id = ?;", (drawing_id,))
                for idx, name in enumerate(page_names):
                    if name and name.strip():
                        conn.execute(
                            "INSERT INTO DrawingPages (drawing_id, page_index, page_name) VALUES (?, ?, ?);",
                            (drawing_id, idx, name.strip()),
                        )
            else:
                existing_pages = conn.execute(
                    "SELECT id, page_index FROM DrawingPages WHERE drawing_id = ?;",
                    (drawing_id,),
                ).fetchall()
                for row in existing_pages:
                    row_id = row["id"]
                    old_idx = row["page_index"]
                    if old_idx in old_to_new_pages:
                        new_idx = old_to_new_pages[old_idx]
                        if new_idx is None:
                            conn.execute("DELETE FROM DrawingPages WHERE id = ?;", (row_id,))
                        elif new_idx != old_idx:
                            conn.execute("UPDATE DrawingPages SET page_index = ? WHERE id = ?;", (new_idx, row_id))

    def delete_drawing(self, drawing_id: int):
        """Elimina un plano del proyecto y sus marcas asociadas (en cascada)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM Drawings WHERE id = ?;", (drawing_id,))

    # --- Operaciones de Anotaciones y Relaciones ---

    def create_annotation(
        self,
        drawing_id: int,
        page_index: int,
        annot_type: str,
        geometry: dict | str,
        style: dict | str,
        content: str | None = None,
        tags: list | str | None = None,
        properties: dict | str | None = None,
        item_id: int | None = None,
        tag_number: int | None = None,
        author: str = "Usuario",
        annot_id: str | None = None,
        ports: list | str | None = None,
        subject: str | None = None,
        layer: str | None = None,
        status: str = "None",
        **kwargs,
    ) -> dict:
        """Crea una nueva anotación vectorial en la base de datos con soporte de nombres estándar e ISO 32000-1."""

        # Soporte para claves ISO 32000-1 (/Subj, /OC, /T, /Contents, /State)
        if subject is None:
            subject = kwargs.get("/Subj") or kwargs.get("subj")

        if author == "Usuario" and "/T" in kwargs:
            author = kwargs["/T"]

        if content is None:
            content = kwargs.get("/Contents") or kwargs.get("contents")

        if layer is None:
            layer = kwargs.get("/OC")

        if status == "None" and ("/State" in kwargs or "status" in kwargs):
            status = kwargs.get("/State") or kwargs.get("status") or "None"

        # Deserializar y sincronizar estilo con vectores de color ISO 32000-1 (/C, /IC, /CA, /ca)
        if isinstance(style, str):
            try:
                style_dict = json.loads(style)
            except Exception:
                style_dict = {}
        elif isinstance(style, dict):
            style_dict = dict(style)
        else:
            style_dict = {}
        style_dict = sync_style_with_iso(style_dict)

        # Deserializar / sincronizar properties dict
        if isinstance(properties, str):
            try:
                props_dict = json.loads(properties)
            except Exception:
                props_dict = {}
        elif isinstance(properties, dict):
            props_dict = dict(properties)
        else:
            props_dict = {}

        if layer is None:
            layer = props_dict.get("discipline") or "General"
        else:
            props_dict["discipline"] = layer

        uid = annot_id or str(uuid.uuid4())
        geom_str = json.dumps(geometry) if isinstance(geometry, dict) else str(geometry)
        style_str = json.dumps(style_dict)
        tags_str = json.dumps(tags if tags is not None else []) if isinstance(tags, list) else str(tags or "[]")
        props_str = json.dumps(props_dict)
        ports_str = json.dumps(ports if ports is not None else []) if isinstance(ports, list) else str(ports or "[]")

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO Annotations (
                    id, drawing_id, page_index, type, geometry, style,
                    content, subject, layer, status, tags, properties, ports, item_id, tag_number, author
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    uid, drawing_id, page_index, annot_type, geom_str, style_str,
                    content, subject, layer, status, tags_str, props_str, ports_str, item_id, tag_number, author
                ),
            )
        return self.get_annotation(uid)

    def _parse_annotation_row(self, row: dict | sqlite3.Row) -> dict:
        """Parsea una fila de la tabla Annotations a un diccionario deserializado con mapeo ISO 32000-1."""
        d = dict(row)
        for field in ("geometry", "properties"):
            val = d.get(field)
            if isinstance(val, str):
                try:
                    d[field] = json.loads(val)
                except Exception:
                    d[field] = {}
            elif val is None:
                d[field] = {}

        for field in ("tags", "ports"):
            val = d.get(field)
            if isinstance(val, str):
                try:
                    d[field] = json.loads(val)
                except Exception:
                    d[field] = []
            elif val is None:
                d[field] = []

        # Deserializar y sincronizar style con ISO
        val_st = d.get("style")
        if isinstance(val_st, str):
            try:
                val_st = json.loads(val_st)
            except Exception:
                val_st = {}
        d["style"] = sync_style_with_iso(val_st or {})

        # Exposición dual: nombres naturales y claves ISO 32000-1
        d["/Subj"] = d.get("subject")
        d["/OC"] = d.get("layer") or d.get("discipline") or "General"
        d["/T"] = d.get("author") or "Usuario"
        d["/Contents"] = d.get("content") or ""
        d["contents"] = d.get("content") or ""
        stat = d.get("status") or "None"
        d["status"] = stat
        d["/State"] = stat
        d["/StateModel"] = "Review"

        # Claves de color ISO a nivel raíz para exportación directa
        d["/C"] = d["style"].get("/C", [])
        d["/CA"] = d["style"].get("/CA", 1.0)
        d["/IC"] = d["style"].get("/IC", [])
        d["/ca"] = d["style"].get("/ca", 0.0)

        if not d.get("discipline"):
            d["discipline"] = d.get("layer") or "General"
        if not d.get("page_name"):
            d["page_name"] = f"Página {d.get('page_index', 0) + 1}"

        return d

    def get_annotations_for_page(self, drawing_id: int, page_index: int, include_deleted: bool = False) -> list[dict]:
        """Obtiene todas las anotaciones de una página dada con mapeo ISO 32000-1."""
        sql = "SELECT * FROM Annotations WHERE drawing_id = ? AND page_index = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        sql += " ORDER BY created_at ASC;"

        with self._get_connection() as conn:
            cursor = conn.execute(sql, (drawing_id, page_index))
            return [self._parse_annotation_row(r) for r in cursor.fetchall()]

    def get_annotations_for_drawing(self, drawing_id: int, include_deleted: bool = False) -> list[dict]:
        """Obtiene todas las anotaciones de un plano completo ordenadas por página y fecha."""
        sql = """
            SELECT a.*, dp.page_name
            FROM Annotations a
            LEFT JOIN DrawingPages dp ON dp.drawing_id = a.drawing_id AND dp.page_index = a.page_index
            WHERE a.drawing_id = ?
        """
        if not include_deleted:
            sql += " AND a.deleted_at IS NULL"
        sql += " ORDER BY a.page_index ASC, a.created_at ASC;"

        with self._get_connection() as conn:
            cursor = conn.execute(sql, (drawing_id,))
            return [self._parse_annotation_row(r) for r in cursor.fetchall()]

    def get_annotation(self, annot_id: str) -> dict | None:
        """Obtiene una anotación específica por su UUID con campos JSON deserializados y mapeo ISO 32000-1."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM Annotations WHERE id = ?;", (annot_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._parse_annotation_row(row)

    def update_annotation(self, annot_id: str, updates: dict) -> dict | None:
        """Actualiza campos específicos de una anotación con soporte de nombres naturales e ISO 32000-1."""
        if not updates:
            return self.get_annotation(annot_id)

        clean_updates = dict(updates)

        # Mapeo de claves ISO 32000-1 a columnas SQL
        if "/Subj" in clean_updates:
            val = clean_updates.pop("/Subj")
            if "subject" not in clean_updates:
                clean_updates["subject"] = val

        if "/OC" in clean_updates:
            val = clean_updates.pop("/OC")
            if "layer" not in clean_updates:
                clean_updates["layer"] = val

        if "/T" in clean_updates:
            val = clean_updates.pop("/T")
            if "author" not in clean_updates:
                clean_updates["author"] = val

        if "/Contents" in clean_updates:
            val = clean_updates.pop("/Contents")
            if "content" not in clean_updates:
                clean_updates["content"] = val

        if "contents" in clean_updates:
            val = clean_updates.pop("contents")
            if "content" not in clean_updates:
                clean_updates["content"] = val

        if "/State" in clean_updates:
            val = clean_updates.pop("/State")
            if "status" not in clean_updates:
                clean_updates["status"] = val
        clean_updates.pop("/StateModel", None)

        # Sincronización de color ISO (/C, /IC, /CA, /ca) hacia style
        iso_color_keys = [k for k in ("/C", "/IC", "/CA", "/ca") if k in clean_updates]
        if iso_color_keys:
            st = clean_updates.get("style")
            if st is None:
                curr = self.get_annotation(annot_id)
                st = curr.get("style", {}) if curr else {}
            elif isinstance(st, str):
                try: st = json.loads(st)
                except Exception: st = {}
            else:
                st = dict(st)
            for k in iso_color_keys:
                st[k] = clean_updates.pop(k)
            clean_updates["style"] = sync_style_with_iso(st, prefer_iso=True)
        elif "style" in clean_updates:
            st = clean_updates["style"]
            if isinstance(st, str):
                try: st = json.loads(st)
                except Exception: st = {}
            elif isinstance(st, dict):
                st = dict(st)
            curr = self.get_annotation(annot_id)
            if curr and curr.get("style"):
                curr_st = curr["style"]
                if isinstance(curr_st, str):
                    try: curr_st = json.loads(curr_st)
                    except Exception: curr_st = {}
                if isinstance(curr_st, dict):
                    merged_st = dict(curr_st)
                    merged_st.update(st)
                    st = merged_st
            clean_updates["style"] = sync_style_with_iso(st)

        # Sincronización bidireccional entre layer y discipline
        if "layer" in clean_updates and "discipline" not in clean_updates:
            clean_updates["discipline"] = clean_updates["layer"]
        elif "discipline" in clean_updates and "layer" not in clean_updates:
            clean_updates["layer"] = clean_updates["discipline"]

        # 'discipline' es columna generada de properties. Si viene en updates, se sincroniza en properties
        if "discipline" in clean_updates:
            disc = clean_updates.pop("discipline")
            props = clean_updates.get("properties")
            if props is None:
                curr = self.get_annotation(annot_id)
                props = curr.get("properties", {}) if curr else {}
            elif isinstance(props, str):
                try:
                    props = json.loads(props)
                except Exception:
                    props = {}
            else:
                props = dict(props)
            props["discipline"] = disc
            clean_updates["properties"] = props

        updatable_columns = {
            "type", "geometry", "style", "content", "subject", "layer", "status",
            "tags", "properties", "ports", "item_id", "tag_number", "author", "deleted_at"
        }

        fields = []
        params = []
        for k, v in clean_updates.items():
            if k not in updatable_columns:
                continue
            if k in ("geometry", "style", "properties", "tags", "ports") and isinstance(v, (dict, list)):
                v = json.dumps(v)
            fields.append(f"{k} = ?")
            params.append(v)

        if not fields:
            return self.get_annotation(annot_id)

        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(annot_id)
        set_clause = ", ".join(fields)
        sql = f"UPDATE Annotations SET {set_clause} WHERE id = ?;"

        with self._get_connection() as conn:
            conn.execute(sql, tuple(params))
        return self.get_annotation(annot_id)

    def delete_annotation(self, annot_id: str, soft: bool = True) -> bool:
        """Elimina una anotación (soft-delete por defecto para Undo/Redo)."""
        with self._get_connection() as conn:
            if soft:
                conn.execute("UPDATE Annotations SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?;", (annot_id,))
            else:
                conn.execute("DELETE FROM Annotations WHERE id = ?;", (annot_id,))
            return True

    def restore_annotation(self, annot_id: str) -> bool:
        """Restaura una anotación previamente eliminada con soft-delete."""
        with self._get_connection() as conn:
            conn.execute("UPDATE Annotations SET deleted_at = NULL WHERE id = ?;", (annot_id,))
            return True

    def create_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str = "relates_to",
        metadata: dict | None = None,
    ) -> dict:
        """Crea una relación entre anotaciones, materializada como una anotación independiente en SQLite."""

        meta = dict(metadata or {})
        source_annot = self.get_annotation(source_id)
        drawing_id = source_annot.get("drawing_id", 1) if source_annot else 1
        page_index = source_annot.get("page_index", 0) if source_annot else 0

        # Obtener o generar el ID de la anotación de relación
        rel_id = meta.get("relation_annot_id")
        if not rel_id:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT metadata FROM AnnotationRelations WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?);",
                    (source_id, target_id, target_id, source_id)
                ).fetchone()
                if row and row["metadata"]:
                    try:
                        m = json.loads(row["metadata"])
                        rel_id = m.get("relation_annot_id")
                    except Exception:
                        pass

        if not rel_id:
            rel_id = str(uuid.uuid4())

        visibility_mode = meta.get("visibility_mode", "on_selection")
        fitting_type = meta.get("fitting_type", relation_type if relation_type != "relates_to" else "relates_to")

        rel_annot = self.get_annotation(rel_id)
        if not rel_annot:
            rel_annot = self.create_annotation(
                drawing_id=drawing_id,
                page_index=page_index,
                annot_type="relation",
                geometry={"source_id": source_id, "target_id": target_id},
                style={
                    "stroke_color": meta.get("stroke_color", "#8B5CF6"),
                    "stroke_width": float(meta.get("stroke_width", 2.0)),
                    "stroke_style": meta.get("stroke_style", "dash"),
                    "visibility_mode": visibility_mode,
                    "fitting_type": fitting_type,
                },
                content=meta.get("content", f"Vínculo: {relation_type}"),
                tags=["Vínculo"],
                properties={
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "fitting_type": fitting_type,
                    "visibility_mode": visibility_mode,
                    "discipline": source_annot.get("discipline", "General") if source_annot else "General",
                },
                annot_id=rel_id,
            )
        else:
            self.restore_annotation(rel_id)

        meta["relation_annot_id"] = rel_id
        meta["visibility_mode"] = visibility_mode
        meta["fitting_type"] = fitting_type
        meta_str = json.dumps(meta)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO AnnotationRelations (source_id, target_id, relation_type, metadata)
                VALUES (?, ?, ?, ?);
                """,
                (source_id, target_id, relation_type, meta_str),
            )
        return rel_annot

    def get_relation_annot_id(self, source_id: str, target_id: str) -> str | None:
        """Obtiene el UUID de la anotación de relación entre dos elementos."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT metadata FROM AnnotationRelations WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?);",
                (source_id, target_id, target_id, source_id)
            ).fetchone()
            if row and row["metadata"]:
                try:
                    m = json.loads(row["metadata"])
                    return m.get("relation_annot_id")
                except Exception:
                    pass
        return None

    def delete_relation(self, source_id: str, target_id: str) -> str | None:
        """Elimina la relación de AnnotationRelations y realiza soft-delete de su anotación correspondiente."""
        rel_annot_id = self.get_relation_annot_id(source_id, target_id)
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM AnnotationRelations WHERE (source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?);",
                (source_id, target_id, target_id, source_id)
            )
        if rel_annot_id:
            self.delete_annotation(rel_annot_id, soft=True)
        return rel_annot_id

    def get_related_annotations(self, annot_id: str, relation_type: str | None = None) -> list[dict]:
        """Obtiene las anotaciones vinculadas directamente con metadatos deserializados."""
        with self._get_connection() as conn:
            if relation_type:
                sql = """
                SELECT a.*, r.relation_type, r.metadata AS rel_metadata, 'outgoing' AS direction
                FROM AnnotationRelations r
                JOIN Annotations a ON a.id = r.target_id
                WHERE r.source_id = ? AND r.relation_type = ? AND a.deleted_at IS NULL
                UNION ALL
                SELECT a.*, r.relation_type, r.metadata AS rel_metadata, 'incoming' AS direction
                FROM AnnotationRelations r
                JOIN Annotations a ON a.id = r.source_id
                WHERE r.target_id = ? AND r.relation_type = ? AND a.deleted_at IS NULL;
                """
                params = (annot_id, relation_type, annot_id, relation_type)
            else:
                sql = """
                SELECT a.*, r.relation_type, r.metadata AS rel_metadata, 'outgoing' AS direction
                FROM AnnotationRelations r
                JOIN Annotations a ON a.id = r.target_id
                WHERE r.source_id = ? AND a.deleted_at IS NULL
                UNION ALL
                SELECT a.*, r.relation_type, r.metadata AS rel_metadata, 'incoming' AS direction
                FROM AnnotationRelations r
                JOIN Annotations a ON a.id = r.source_id
                WHERE r.target_id = ? AND a.deleted_at IS NULL;
                """
                params = (annot_id, annot_id)

            cursor = conn.execute(sql, params)
            results = []
            for r in cursor.fetchall():
                d = dict(r)
                meta_raw = d.get("rel_metadata")
                if meta_raw and isinstance(meta_raw, str):
                    try:
                        d["rel_meta_dict"] = json.loads(meta_raw)
                    except Exception:
                        d["rel_meta_dict"] = {}
                else:
                    d["rel_meta_dict"] = {}
                results.append(d)
            return results
