"""
Módulo Centralizado de Ajustes Persistentes (SettingsManager).

Gestiona la configuración global del usuario en formato JSON estándar:
1. Respeta el estándar XDG en Linux (~/.config/bms_bidsuite/settings.json).
2. Es idempotente: genera automáticamente valores por defecto si no existe o está corrupto.
3. Permite acceso por clave jerárquica con notación de punto (ej. settings.get("window.width", 1400)).
4. Guarda de forma atómica y segura mediante archivos temporales para evitar corrupción ante cierres inesperados.
"""

import os
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SettingsManager:
    """Administrador singleton de configuración del sistema."""

    DEFAULT_SETTINGS = {
        "window": {
            "width": 1400,
            "height": 900,
            "is_maximized": False,
        },
        "viewer": {
            "last_tool_mode": "pan",
            "zoom_step": 1.25,
        },
        "theme": {
            "current": "dark",
        },
        "general": {
            "last_project_path": None,
            "recent_projects": [],
            "max_recent_projects": 10,
        },
        "auto_namer": {
            "last_separators": [" - ", " "],
        },
        "annotations": {
            "tool_defaults": {
                "rect": {
                    "style": {"stroke_color": "#3B82F6", "stroke_width": 2.0, "fill_color": "#3B82F6", "fill_opacity": 0.08},
                    "discipline": "General",
                },
                "circle": {
                    "style": {"stroke_color": "#10B981", "stroke_width": 2.0, "fill_color": "#10B981", "fill_opacity": 0.08},
                    "discipline": "General",
                },
                "cloud": {
                    "style": {"stroke_color": "#F59E0B", "stroke_width": 2.0, "fill_color": "#F59E0B", "fill_opacity": 0.08},
                    "discipline": "General",
                },
                "line": {
                    "style": {"stroke_color": "#64748B", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.0},
                    "discipline": "General",
                },
                "arrow": {
                    "style": {"stroke_color": "#64748B", "stroke_width": 2.0, "fill_color": "transparent", "fill_opacity": 0.0},
                    "discipline": "General",
                },
                "text": {
                    "style": {"stroke_color": "#1E293B", "stroke_width": 1.0, "fill_color": "transparent", "fill_opacity": 0.0, "font_size": 12.0},
                    "discipline": "General",
                },
                "callout": {
                    "style": {"stroke_color": "#8B5CF6", "stroke_width": 2.0, "fill_color": "#8B5CF6", "fill_opacity": 0.08, "font_size": 11.0},
                    "discipline": "General",
                },
            }
        }
    }

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, custom_path: Path | str | None = None):
        if self._initialized:
            return
        self._initialized = True

        if custom_path:
            self._file_path = Path(custom_path).resolve()
        else:
            base_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "bms_bidsuite"
            self._file_path = base_dir / "settings.json"

        self._data: dict = {}
        self.load()

    @property
    def file_path(self) -> Path:
        return self._file_path

    def load(self):
        """Carga los ajustes desde el archivo JSON o crea los valores predeterminados."""
        if self._file_path.exists():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        # Fusionar recursivamente con defaults para asegurar que nuevas claves existan
                        self._data = self._deep_merge(self.DEFAULT_SETTINGS, loaded)
                        return
            except Exception as e:
                logger.warning("Error al leer %s, restaurando defaults: %s", self._file_path, e)

        # Si no existe o falló la lectura, clonar defaults
        self._data = json.loads(json.dumps(self.DEFAULT_SETTINGS))
        self.save()

    def save(self):
        """Guarda de manera atómica los ajustes en disco."""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._file_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            temp_path.replace(self._file_path)
        except Exception as e:
            logger.error("Error al guardar ajustes en %s: %s", self._file_path, e)

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Obtiene un valor usando notación de puntos (ej. 'window.width').
        """
        keys = key_path.split(".")
        curr = self._data
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return default
        return curr

    def set(self, key_path: str, value: Any, auto_save: bool = True):
        """
        Asigna un valor usando notación de puntos (ej. 'window.is_maximized', True).
        """
        keys = key_path.split(".")
        curr = self._data
        for k in keys[:-1]:
            if k not in curr or not isinstance(curr[k], dict):
                curr[k] = {}
            curr = curr[k]
        curr[keys[-1]] = value

        if auto_save:
            self.save()

    def add_recent_project(self, project_path: str | Path):
        """Registra un proyecto reciente evitando duplicados y respetando el límite."""
        path_str = str(Path(project_path).resolve())
        recent = self.get("general.recent_projects", [])
        if path_str in recent:
            recent.remove(path_str)
        recent.insert(0, path_str)
        max_items = self.get("general.max_recent_projects", 10)
        self.set("general.recent_projects", recent[:max_items], auto_save=False)
        self.set("general.last_project_path", path_str, auto_save=True)

    @classmethod
    def _deep_merge(cls, default: dict, user: dict) -> dict:
        merged = json.loads(json.dumps(default))
        for k, v in user.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = cls._deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged


# Instancia global conveniente para importar directamente
settings = SettingsManager()
