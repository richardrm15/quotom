"""
Configuración de pytest para Quotom.

Fija el backend Qt *offscreen* y añade la raíz del proyecto a ``sys.path``.
La lógica de entorno vive en ``tests/support.py`` para reutilizarla también
cuando los tests se ejecutan como scripts.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
