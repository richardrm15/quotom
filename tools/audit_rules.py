#!/usr/bin/env python3
"""
Auditoría de arquitectura de Quotom.

Comprueba las **22 reglas obligatorias** de `docs/ESPECIFICACION_ARQUITECTURA.md` §20
(R1…R22). El documento es la autoridad: su §22 define **qué se audita, con qué tipo de
verificación (automática / informativa / manual) y cómo se aplican las excepciones**.

Uso:
    python3 tools/audit_rules.py                       # informe completo
    python3 tools/audit_rules.py --resumen             # solo contadores
    python3 tools/audit_rules.py --json                # salida máquina
    python3 tools/audit_rules.py --baseline f.json     # compara con una línea base
    python3 tools/audit_rules.py --guardar f.json      # escribe la línea base actual

Código de salida:
    0   sin hallazgos, o todo dentro de la línea base
    1   algún contador ha SUBIDO respecto a la línea base
    2   error de uso

Reglas de este programa:
  * No tiene efectos al importarse: todo ocurre dentro de `main()`.
  * Cada chequeo dice **qué mira** y **dónde**, y declara sus excepciones con motivo.
  * Lo que no puede medirse se declara **manual**; nunca se cuenta como si se midiera.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Alcance (spec §22.1)
# --------------------------------------------------------------------------

EXCLUIDOS = {"env", "__pycache__", "build", "dist", ".git", ".pytest_cache", ".cache"}

RUTAS_DOMINIO = ("core",)          # R1, R15, R21
RUTAS_COMPARTIDAS = ("common",)    # R7, R13, R14, R16-19
RUTAS_UI = ("ui",)                 # R2-R4, R7, R8, R13, R14, R16-18
TESTS = "tests"                    # organización (R20)

#: Módulos de UI por encima de este tamaño se consideran sospechosos de contener
#: lógica que no les corresponde (R8). Es un indicador, no una medida exacta.
LIMITE_MODULO_UI = 400

#: Métodos/nombres que delatan manipulación de widgets desde un comando (R14).
NOMBRES_DE_WIDGET = {
    "QtWidgets", "QMessageBox", "QInputDialog", "QFileDialog", "QDialog",
    "QWidget", "QTableWidget", "QTableWidgetItem", "QStatusBar", "QToolBar",
    "setText", "setHtml", "setVisible", "setEnabled", "setDisabled", "setChecked",
    "setIcon", "setStyleSheet", "setWindowTitle", "setToolTip", "setStatusTip",
    "addWidget", "addItem", "addRow", "insertRow", "setItem", "setRowCount",
    "setColumnCount", "setCurrentIndex", "setValue", "setRange", "setMaximum",
    "showMessage", "warning", "information", "critical", "show", "hide",
    "_sidebar", "_status_bar", "statusBar", "_table_view",
}

#: Objetos gráficos de Qt que no pueden formar parte del modelo de dominio (R21).
NOMBRES_GRAFICOS = {
    "QColor", "QBrush", "QPen", "QFont", "QIcon", "QImage", "QPixmap", "QPainter",
    "QPainterPath", "QPolygon", "QTransform", "QCursor", "QBitmap",
}

#: Excepciones justificadas (spec §22.3). Cada una lleva **qué** y **por qué**.
#:
#: Nota importante: las "guardas de capacidad" (`hasattr(obj, "metodo")` para saber si
#: la versión de Qt soporta algo) **no** se exceptúan. `requirements.txt` fija
#: PySide6 >= 6.6, así que capacidades como `setColorScheme` (Qt 6.5) o
#: `startSystemMove` (Qt 5.15) están garantizadas: la guarda es código muerto y cuenta
#: como violación.
EXCEPCIONES_R13: dict[tuple[str, str], str] = {}
EXCEPCIONES_R14: dict[tuple[str, str], str] = {}
EXCEPCIONES_R16 = {
    "common/styles/style_manager.py":
        "único punto autorizado para generar y aplicar QSS en toda la aplicación",
}

# --------------------------------------------------------------------------
# Estructuras
# --------------------------------------------------------------------------


@dataclass
class Hallazgo:
    """Un incumplimiento concreto."""

    archivo: str
    linea: int
    mensaje: str

    def __str__(self) -> str:
        return f"{self.archivo}:{self.linea}  {self.mensaje}"


@dataclass
class Regla:
    """Metadatos de una regla del spec, según su §22.2."""

    id: str
    titulo: str
    tipo: str                      # "auto" | "informativa" | "manual"
    revisa: str                    # qué mira y dónde
    hallazgos: list[Hallazgo] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)

    @property
    def cuenta(self) -> int:
        """Número de hallazgos (solo tiene sentido en reglas automáticas)."""
        return len(self.hallazgos)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def archivos(base, nombre: str = "*.py") -> list[Path]:
    """Módulos `.py` de una ruta del proyecto, saltando entornos y cachés."""
    raiz = ROOT / base if isinstance(base, str) else base
    if not raiz.exists():
        return []
    return sorted(
        p for p in raiz.rglob(nombre)
        if not any(parte in EXCLUIDOS for parte in p.parts)
    )


def arboles(rutas) -> list[tuple[Path, ast.Module]]:
    """Pares (archivo, AST) de los módulos indicados, ignorando los que no compilan."""
    salida = []
    for p in rutas:
        try:
            salida.append((p, ast.parse(p.read_text(encoding="utf-8"))))
        except (OSError, SyntaxError):
            continue
    return salida


def relativo(p: Path) -> str:
    """Ruta relativa al proyecto."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def lineas(p: Path) -> list[str]:
    """Líneas del archivo (vacío si no se puede leer)."""
    try:
        return p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def busca(rutas, patron: str, flags: int = 0) -> list[Hallazgo]:
    """
    Busca un patrón **línea a línea** y devuelve hallazgos.

    Se usa cuando el criterio depende del texto (SQL dentro de una cadena, QSS…),
    no de la estructura del código.
    """
    rx = re.compile(patron, flags)
    encontrados = []
    for p in rutas:
        for i, l in enumerate(lineas(p), 1):
            if rx.search(l):
                encontrados.append(Hallazgo(relativo(p), i, l.strip()[:100]))
    return encontrados


def referencias(nodos, nombres: set[str], incluir_import: bool = True) -> list[tuple[int, str]]:
    """Líneas donde aparecen los nombres dados (AST: ignora comentarios y docstrings)."""
    encontrados = []
    for n in ast.walk(nodos):
        if isinstance(n, ast.Name) and n.id in nombres:
            encontrados.append((n.lineno, f"usa {n.id}"))
        elif isinstance(n, ast.Attribute) and n.attr in nombres:
            encontrados.append((n.lineno, f"usa .{n.attr}"))
        elif incluir_import and isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                if alias.name.split(".")[0] in nombres or alias.name in nombres:
                    encontrados.append((n.lineno, f"importa {alias.name}"))
    return encontrados


def clases_que_heredan(nodos, base: str) -> list[ast.ClassDef]:
    """Clases que heredan de `base` (comparando por nombre)."""
    salida = []
    for n in ast.walk(nodos):
        if isinstance(n, ast.ClassDef) and any(
            (isinstance(b, ast.Name) and b.id == base)
            or (isinstance(b, ast.Attribute) and b.attr == base)
            for b in n.bases
        ):
            salida.append(n)
    return salida


def es_llamada(nodo, nombres: set[str]) -> bool:
    """¿Es una llamada a alguno de esos nombres (función o método)?"""
    if not isinstance(nodo, ast.Call):
        return False
    f = nodo.func
    return (isinstance(f, ast.Name) and f.id in nombres) or (
        isinstance(f, ast.Attribute) and f.attr in nombres
    )

# --------------------------------------------------------------------------
# Chequeos — dominio (R1, R15, R21) y vistas (R2, R3, R4, R7)
# --------------------------------------------------------------------------

QT_RAICES = {"PySide6", "PyQt5", "PyQt6"}


def chequeo_r1(base: Path = ROOT) -> list[Hallazgo]:
    """R1 — `core/` no importa PySide6 (ni PyQt)."""
    salida: list[Hallazgo] = []
    for p, t in arboles(archivos(base / "core")):
        for n in ast.walk(t):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                modulos = [a.name for a in n.names]
                if isinstance(n, ast.ImportFrom) and n.module:
                    modulos.append(n.module)
                if any(m.split(".")[0] in QT_RAICES for m in modulos):
                    salida.append(Hallazgo(relativo(p), n.lineno, "importa Qt en el dominio"))
    return salida


def chequeo_r15(base: Path = ROOT) -> list[Hallazgo]:
    """R15 — `core/` no utiliza `Signal` de Qt."""
    return [
        Hallazgo(relativo(p), i, msg)
        for p, t in arboles(archivos(base / "core"))
        for i, msg in referencias(t, {"Signal"}, incluir_import=True)
    ]


def chequeo_r21(base: Path = ROOT) -> list[Hallazgo]:
    """R21 — ningún objeto gráfico de Qt forma parte del modelo de dominio."""
    return [
        Hallazgo(relativo(p), i, msg)
        for p, t in arboles(archivos(base / "core"))
        for i, msg in referencias(t, NOMBRES_GRAFICOS, incluir_import=True)
    ]


# SQL: se exige la **estructura** de la sentencia (dos palabras clave), para no
# confundir un método `self.update()` con una consulta. Insensible a mayúsculas,
# porque en Python las consultas suelen escribirse en minúsculas.
PATRON_SQL = (
    r"\b(delete\s+from|insert\s+into|create\s+table|drop\s+table"
    r"|update\s+\w+\s+set|select\b[^\n]{0,120}?\bfrom\b)\b"
)


def vistas(base: Path = ROOT) -> list[Path]:
    """Todos los `view.py` del proyecto (el alcance de R2/R3/R6)."""
    return [p for p in archivos(base / "ui") if p.name == "view.py"]


def chequeo_r2(base: Path = ROOT) -> list[Hallazgo]:
    """
    R2 — `view.py` no contiene SQL.

    Limitación conocida: la búsqueda es por línea, así que una consulta partida en
    varias líneas podría no detectarse. Se prefiere quedarse corto antes que marcar
    falsos positivos por palabras sueltas.
    """
    return busca(vistas(base), PATRON_SQL, re.IGNORECASE)


def chequeo_r3(base: Path = ROOT) -> list[Hallazgo]:
    """R3 — `view.py` no accede directamente a la base de datos."""
    return busca(vistas(base), r"core\.database|DatabaseManager|\bimport\s+database\b")


def chequeo_r4(base: Path = ROOT) -> list[Hallazgo]:
    """
    R4 — las vistas no llaman `parent()` / `parentWidget()` / `window()`.

    Se comprueba con AST: solo cuentan **llamadas** sobre `self`, no menciones en
    comentarios ni docstrings.
    """
    salida: list[Hallazgo] = []
    for p, t in arboles(archivos(base / "ui") + archivos(base / "common")):
        for n in ast.walk(t):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            if n.func.attr not in {"parent", "parentWidget", "window"}:
                continue
            receptor = n.func.value
            if isinstance(receptor, ast.Name) and receptor.id == "self":
                salida.append(Hallazgo(relativo(p), n.lineno, f"self.{n.func.attr}()"))
    return salida


def features(base: Path = ROOT) -> list[str]:
    """Nombres de las features de `ui/views/`."""
    vistas_ui = base / "ui" / "views"
    if not vistas_ui.is_dir():
        return []
    return sorted(d.name for d in vistas_ui.iterdir()
                  if d.is_dir() and d.name != "__pycache__")


def chequeo_r7(base: Path = ROOT) -> list[Hallazgo]:
    """
    R7 — las vistas hermanas no se conocen entre sí.

    Ninguna feature de `ui/views/` puede importar de otra. Sin listas blancas: si dos
    features necesitan compartir algo, ese algo pertenece a `common/`.
    """
    conocidas = set(features(base))
    salida: list[Hallazgo] = []
    for nombre in sorted(conocidas):
        for p, t in arboles(archivos(base / "ui" / "views" / nombre)):
            for n in ast.walk(t):
                modulos: list[str] = []
                if isinstance(n, ast.ImportFrom) and n.module:
                    modulos.append(n.module)
                elif isinstance(n, ast.Import):
                    modulos += [a.name for a in n.names]
                for m in modulos:
                    partes = m.split(".")
                    if len(partes) >= 3 and partes[0] == "ui" and partes[1] == "views":
                        if partes[2] in conocidas and partes[2] != nombre:
                            salida.append(
                                Hallazgo(relativo(p), n.lineno,
                                         f"importa la feature hermana {partes[2]}")
                            )
    return salida

# --------------------------------------------------------------------------
# Chequeos — controllers y commands (R8, R10-R14)
# --------------------------------------------------------------------------


def controllers(base: Path = ROOT) -> list[Path]:
    """Archivos que actúan como controller (por convención de nombre)."""
    return [p for p in archivos(base / "ui")
            if p.name == "controller.py" or p.name.endswith("_controller.py")]


def commands(base: Path = ROOT) -> list[Path]:
    """
    Archivos de comandos: los de cada feature.

    `common/commands/global_commands.py` ya no existe: la aplicación tiene **una sola
    ventana**, así que no hay comandos compartidos entre ventanas (decisión D3). Cuando
    haga falta multi-ventana, se creará donde el spec diga.
    """
    return [p for p in archivos(base / "ui") if p.name == "commands.py"]


def chequeo_r6(base: Path = ROOT) -> list[Hallazgo]:
    """
    R6 — quien llama a una vista usa su interfaz pública.

    Comprobación: en los controllers, una llamada `self.<colaborador>._metodo()` es
    acceso a la parte **privada** de otro objeto. Cuando el colaborador es la vista, es
    exactamente lo que la regla prohíbe.

    No se marca el acceso a atributos privados del propio controller (`self._algo`),
    porque eso es estado propio, no la interfaz de otro.
    """
    salida: list[Hallazgo] = []
    for p, t in arboles(controllers(base)):
        for n in ast.walk(t):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            metodo = n.func.attr
            if not metodo.startswith("_") or metodo.startswith("__"):
                continue
            receptor = n.func.value
            if (isinstance(receptor, ast.Attribute)
                    and isinstance(receptor.value, ast.Name)
                    and receptor.value.id == "self"):
                salida.append(
                    Hallazgo(relativo(p), n.lineno,
                             f"llama a {receptor.attr}.{metodo}() (privado de otro objeto)")
                )
    return salida


def chequeo_r8(base: Path = ROOT) -> list[Hallazgo]:
    """
    R8 — los controllers orquestan: no tocan la base de datos ni cargan lógica.

    Dos comprobaciones:

      (a) **acceso directo a la BD desde un controller** — es la regla;
      (b) **presupuesto de tamaño de los módulos** (spec §22.2): módulos que pasan del
          umbral son candidatos a revisión, porque un módulo muy grande suele esconder
          lógica que debería estar en un servicio o en otro módulo.

    El tamaño se mide sobre **todos** los módulos de la aplicación (decisión D1: los tres
    mayores viven en `common/`, así que mirar solo `ui/` los ocultaba). Es un
    **indicador con presupuesto**, no una violación: su meta no es 0, sino **no crecer y
    bajar cuando el módulo tenga responsabilidades mezcladas** (decisión D2).
    """
    salida = busca(controllers(base), r"self\._db\b|\bDatabaseManager\b|\b\w+\.db\s*\.")
    for p in archivos(base / "core") + archivos(base / "common") + archivos(base / "ui"):
        n = len(lineas(p))
        if n > LIMITE_MODULO_UI:
            salida.append(Hallazgo(relativo(p), 1,
                                   f"{n} líneas (presupuesto de tamaño, umbral {LIMITE_MODULO_UI})"))
    return salida


def chequeo_r9(base: Path = ROOT) -> tuple[list[Hallazgo], list[str]]:
    """
    R9 — la lógica de negocio vive en `core/services` y `core/business_rules`.

    Verificación **informativa**: se comprueba que existan los servicios y que no
    dependan de Qt (si dependieran, no serían dominio).
    """
    servicios = archivos(base / "core" / "services")
    reglas = base / "core" / "business_rules.py"
    notas = [f"{len(servicios)} archivos en core/services/",
             f"core/business_rules.py {'existe' if reglas.exists() else 'FALTA'}"]
    salida: list[Hallazgo] = []
    for p, t in arboles(servicios):
        for n in ast.walk(t):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                modulos = [a.name for a in n.names]
                if isinstance(n, ast.ImportFrom) and n.module:
                    modulos.append(n.module)
                if any(m.split(".")[0] in QT_RAICES for m in modulos):
                    salida.append(Hallazgo(relativo(p), n.lineno,
                                           "un servicio de dominio importa Qt"))
    return salida, notas


def chequeo_r10(base: Path = ROOT) -> list[Hallazgo]:
    """
    R10 — los `QUndoCommand` reciben dependencias explícitas.

    Un comando que captura una `QUndoStack` deja de poder usarse en otra ventana, así
    que su presencia es una violación.
    """
    return [
        Hallazgo(relativo(p), i, f"{msg} (el comando no debe capturar la pila)")
        for p, t in arboles(commands(base))
        for i, msg in referencias(t, {"QUndoStack", "QUndoGroup"}, incluir_import=False)
    ]


def chequeo_r11(base: Path = ROOT) -> list[Hallazgo]:
    """R11 — todo `QUndoCommand` define `redo()` y `undo()`."""
    salida: list[Hallazgo] = []
    for p, t in arboles(commands(base)):
        for clase in clases_que_heredan(t, "QUndoCommand"):
            metodos = {n.name for n in clase.body if isinstance(n, ast.FunctionDef)}
            for requerido in ("redo", "undo"):
                if requerido not in metodos:
                    salida.append(Hallazgo(relativo(p), clase.lineno,
                                           f"{clase.name} no define {requerido}()"))
    return salida


def chequeo_r12(base: Path = ROOT) -> list[Hallazgo]:
    """R12 — no se usan hacks tipo `_applied_once` para simular el primer redo."""
    return [
        Hallazgo(relativo(p), i, msg)
        for p, t in arboles(commands(base))
        for i, msg in referencias(t, {"_applied_once", "_applied", "_first_redo"},
                                  incluir_import=False)
    ]

def _clasifica_dinamica(nodo: ast.Call) -> str:
    """
    Clasifica un `hasattr`/`getattr`/`setattr` según el criterio del spec §22.4.

    Returns:
        "propio"  consulta el estado propio (`hasattr(self, ...)`)
        "lookup"  nombre resuelto en ejecución (`getattr(obj, variable, ...)`)
        "ajeno"   consulta otro objeto → violación de R13
    """
    if not nodo.args:
        return "ajeno"
    objetivo = nodo.args[0]
    es_propio = (
        (isinstance(objetivo, ast.Name) and objetivo.id == "self")
        or (isinstance(objetivo, ast.Attribute) and isinstance(objetivo.value, ast.Name)
            and objetivo.value.id == "self")
    )
    if len(nodo.args) >= 2 and not isinstance(nodo.args[1], ast.Constant):
        return "lookup"
    return "propio" if es_propio else "ajeno"


def chequeo_r13(base: Path = ROOT) -> tuple[list[Hallazgo], list[Hallazgo], list[Hallazgo]]:
    """
    R13 — no se usa `hasattr`/`getattr`/`setattr` para descubrir objetos.

    Devuelve tres grupos, porque el spec §22.4 los trata distinto:

      * **violaciones**: consulta otro objeto (`hasattr(mw, "_undo_stack")`).
      * **estado propio**: `hasattr(self, …)`; se corrige inicializando en `__init__`,
        y se informa aparte para no confundirlo con lo anterior.
      * **excepciones**: lookups por nombre y guardas de capacidad declaradas en
        `EXCEPCIONES_R13`; se listan para que se vean, no para contarlas.

    Se usa AST: comentarios y docstrings no cuentan.
    """
    nombres = {"hasattr", "getattr", "setattr"}
    violaciones: list[Hallazgo] = []
    propios: list[Hallazgo] = []
    excepciones: list[Hallazgo] = []
    for p, t in arboles(archivos(base / "ui") + archivos(base / "common")):
        for n in ast.walk(t):
            if not es_llamada(n, nombres):
                continue
            fn = n.func.id if isinstance(n.func, ast.Name) else n.func.attr
            atributo = ""
            if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant):
                atributo = str(n.args[1].value)
            motivo = EXCEPCIONES_R13.get((relativo(p), atributo))
            if motivo:
                excepciones.append(Hallazgo(relativo(p), n.lineno,
                                            f"{fn}: excepción declarada — {motivo}"))
                continue
            grupo = _clasifica_dinamica(n)
            if grupo == "propio":
                propios.append(Hallazgo(relativo(p), n.lineno, f"{fn} sobre el propio estado"))
            elif grupo == "lookup":
                excepciones.append(Hallazgo(relativo(p), n.lineno,
                                            f"{fn}: nombre resuelto en ejecución (§22.4)"))
            else:
                violaciones.append(Hallazgo(relativo(p), n.lineno, f"{fn} sobre otro objeto"))
    return violaciones, propios, excepciones


def chequeo_r14(base: Path = ROOT) -> list[Hallazgo]:
    """
    R14 — los commands no manipulan widgets.

    Mira **nombres de widgets y de sus métodos** (no una lista de imports): así detecta
    tanto `QMessageBox.warning(...)` como `self.view.setVisible(True)`.
    """
    return [
        Hallazgo(relativo(p), i, f"command con widget: {msg}")
        for p, t in arboles(commands(base))
        for i, msg in referencias(t, NOMBRES_DE_WIDGET, incluir_import=True)
        if (relativo(p), "") not in EXCEPCIONES_R14
    ]

# --------------------------------------------------------------------------
# Chequeos — estilos, iconos, common/ y tests (R16-R20)
# --------------------------------------------------------------------------


def chequeo_r16_r17(base: Path = ROOT) -> list[Hallazgo]:
    """
    R16/R17 — los estilos viven en `theme.qss`; nada de `setStyleSheet` disperso.

    Única excepción declarada: `common/styles/style_manager.py`, que es donde se genera y
    aplica el QSS (ver `EXCEPCIONES_R16`).
    """
    salida = []
    for h in busca(archivos(base / "ui") + archivos(base / "common"), r"\.setStyleSheet\("):
        if any(exceptuado in h.archivo for exceptuado in EXCEPCIONES_R16):
            continue
        salida.append(h)
    return salida


def chequeo_r18(base: Path = ROOT) -> tuple[list[Hallazgo], list[str]]:
    """
    R18 — los iconos se generan con `common/icons.get_icon()`.

    Verificación **informativa**: cuenta los usos de la fábrica y, como señal, los
    `setIcon(QIcon(` construidos a mano (que es justo lo que la fábrica evita).
    """
    usos = busca(archivos(base / "ui") + archivos(base / "common"), r"get_icon\(")
    directos = busca(archivos(base / "ui") + archivos(base / "common"), r"setIcon\(\s*QIcon\(")
    notas = [f"{len(usos)} usos de get_icon()",
             f"{len(directos)} iconos construidos a mano (setIcon(QIcon(...)))"]
    return directos, notas


def chequeo_r19(base: Path = ROOT) -> tuple[list[Hallazgo], list[str]]:
    """
    R19 — `common/` solo contiene componentes realmente compartidos.

    Verificación **informativa**: para cada subcarpeta de `common/`, cuántos módulos de
    `ui/` la usan. Una subcarpeta que no la usa nadie es candidata a no ser común.
    """
    raiz_common = base / "common"
    notas: list[str] = []
    sospechosas: list[Hallazgo] = []
    if not raiz_common.is_dir():
        return sospechosas, ["no existe common/"]
    modulos_ui = arboles(archivos(base / "ui"))
    for sub in sorted(d for d in raiz_common.iterdir() if d.is_dir() and d.name != "__pycache__"):
        prefijo = f"common.{sub.name}"
        usuarios = 0
        for _, t in modulos_ui:
            for n in ast.walk(t):
                modulos = []
                if isinstance(n, ast.ImportFrom) and n.module:
                    modulos.append(n.module)
                elif isinstance(n, ast.Import):
                    modulos += [a.name for a in n.names]
                if any(m.startswith(prefijo) for m in modulos):
                    usuarios += 1
                    break
        notas.append(f"common/{sub.name}/ -> {usuarios} módulos de ui/ lo usan")
        if usuarios == 0:
            sospechosas.append(Hallazgo(f"common/{sub.name}/", 1,
                                        "ningún módulo de ui/ lo usa (¿realmente compartido?)"))
    return sospechosas, notas


def chequeo_r20(base: Path = ROOT) -> list[Hallazgo]:
    """R20 — los tests de dominio (`tests/core/`) no arrancan Qt."""
    pruebas = archivos(base / "tests" / "core")
    return busca(pruebas, r"^\s*(from|import)\s+(PySide6|PyQt5|PyQt6)")

# --------------------------------------------------------------------------
# Registro de las 22 reglas (spec §22.2)
# --------------------------------------------------------------------------


def evaluar(base: Path = ROOT) -> list[Regla]:
    """Ejecuta los chequeos y devuelve las 22 reglas evaluadas."""
    r13_violaciones, r13_propios, r13_excepciones = chequeo_r13(base)
    r9_hallazgos, r9_notas = chequeo_r9(base)
    r18_hallazgos, r18_notas = chequeo_r18(base)
    r19_hallazgos, r19_notas = chequeo_r19(base)
    r16_hallazgos = chequeo_r16_r17(base)

    reglas = [
        Regla("R1", "core/ no importa PySide6", "auto", "imports en core/", chequeo_r1(base)),
        Regla("R2", "view.py no contiene SQL", "auto", "SQL en ui/**/view.py", chequeo_r2(base)),
        Regla("R3", "view.py no accede a database.py", "auto", "acceso a BD en view.py", chequeo_r3(base)),
        Regla("R4", "las vistas no llaman parent()/window()", "auto", "llamadas en ui/ y common/", chequeo_r4(base)),
        Regla("R5", "las vistas emiten señales para eventos", "manual",
              "revisión manual al cerrar cada hito (spec §22.2)"),
        Regla("R6", "los controllers llaman métodos públicos de la vista", "auto",
              "llamadas a métodos privados de colaboradores desde controllers", chequeo_r6(base)),
        Regla("R7", "las vistas hermanas no se conocen", "auto",
              "imports entre features de ui/views/", chequeo_r7(base)),
        Regla("R8", "los controllers solo orquestan", "auto",
              "acceso a BD desde controllers + presupuesto de tamaño de todos los módulos",
              chequeo_r8(base)),
        Regla("R9", "la lógica de negocio vive en core/services", "informativa",
              "core/services/ y business_rules.py", r9_hallazgos, r9_notas),
        Regla("R10", "los QUndoCommand reciben dependencias explícitas", "auto",
              "referencias a QUndoStack en commands.py", chequeo_r10(base)),
        Regla("R11", "redo() realiza la operación", "auto",
              "clases QUndoCommand sin redo/undo", chequeo_r11(base)),
        Regla("R12", "sin hacks tipo _applied_once", "auto",
              "marcas de primer-redo en commands.py", chequeo_r12(base)),
        Regla("R13", "sin hasattr/getattr para descubrir objetos", "auto",
              "hasattr/getattr/setattr en ui/ y common/", r13_violaciones),
        Regla("R14", "los commands no manipulan widgets", "auto",
              "widgets usados desde commands.py", chequeo_r14(base)),
        Regla("R15", "core no utiliza Signals de Qt", "auto", "Signal en core/", chequeo_r15(base)),
        Regla("R16", "los estilos permanentes viven en theme.qss", "auto",
              "setStyleSheet fuera de common/styles/", r16_hallazgos),
        Regla("R17", "sin setStyleSheet disperso", "auto",
              "mismo chequeo que R16", list(r16_hallazgos)),
        Regla("R18", "los iconos se generan con get_icon()", "informativa",
              "usos de common/icons", r18_hallazgos, r18_notas),
        Regla("R19", "common/ solo contiene lo realmente compartido", "informativa",
              "uso de cada subcarpeta de common/", r19_hallazgos, r19_notas),
        Regla("R20", "el dominio se prueba sin iniciar Qt", "auto",
              "tests/core/ sin Qt", chequeo_r20(base)),
        Regla("R21", "los gráficos de Qt no son modelo de dominio", "auto",
              "objetos gráficos en core/", chequeo_r21(base)),
        Regla("R22", "sin capas nuevas sin necesidad real", "manual",
              "revisión manual al cerrar cada hito (spec §22.2)"),
    ]
    r13 = next(r for r in reglas if r.id == "R13")
    r13.notas.append(f"{len(r13_propios)} marcas de estado propio (se corrigen inicializando en __init__)")
    r13.notas.append(f"{len(r13_excepciones)} excepciones (lookup por nombre y guardas de capacidad)")
    return reglas


def inventario_modulos(base: Path = ROOT) -> list[tuple[str, int]]:
    """Tamaño de todos los módulos de aplicación, de mayor a menor."""
    todos = archivos(base / "core") + archivos(base / "common") + archivos(base / "ui")
    return sorted(((relativo(p), len(lineas(p))) for p in todos), key=lambda t: -t[1])

# --------------------------------------------------------------------------
# Salida
# --------------------------------------------------------------------------


def contadores(reglas: list[Regla]) -> dict[str, int]:
    """Solo las reglas automáticas tienen contador (las manuales no se cuentan)."""
    return {r.id: r.cuenta for r in reglas if r.tipo == "auto"}


def imprimir_informe(reglas: list[Regla], detalle: int = 20) -> None:
    """Informe legible, regla por regla."""
    for r in reglas:
        etiqueta = {"auto": "", "informativa": "  [informativa]",
                    "manual": "  [revisión manual]"}[r.tipo]
        if r.tipo == "auto":
            marca = "OK  " if r.cuenta == 0 else "    "
            print(f"\n{marca}{r.id} — {r.titulo}{etiqueta}")
            print(f"     revisa: {r.revisa}  -> {r.cuenta}")
            for h in r.hallazgos[:detalle]:
                print(f"        {h}")
            if len(r.hallazgos) > detalle:
                print(f"        ... y {len(r.hallazgos) - detalle} más")
        else:
            print(f"\n--- {r.id} — {r.titulo}{etiqueta}")
            print(f"     revisa: {r.revisa}")
        for nota in r.notas:
            print(f"     · {nota}")


def imprimir_resumen(reglas: list[Regla]) -> None:
    """Solo contadores, con el total de lo medible."""
    print(f"\n{'REGLA':7s} {'TIPO':12s} {'HALLAZGOS':>9s}  TÍTULO")
    for r in reglas:
        if r.tipo == "auto":
            print(f"{r.id:7s} {'automática':12s} {r.cuenta:9d}  {r.titulo}")
        else:
            print(f"{r.id:7s} {r.tipo:12s} {'-':>9s}  {r.titulo}")
    total = sum(contadores(reglas).values())
    print(f"\nTOTAL (solo reglas automáticas): {total}")


def como_json(reglas: list[Regla]) -> dict:
    """Representación máquina del informe."""
    return {
        "reglas": [
            {
                "id": r.id, "titulo": r.titulo, "tipo": r.tipo, "revisa": r.revisa,
                "hallazgos": [{"archivo": h.archivo, "linea": h.linea,
                               "mensaje": h.mensaje} for h in r.hallazgos],
                "notas": r.notas,
            }
            for r in reglas
        ],
        "contadores": contadores(reglas),
        "total": sum(contadores(reglas).values()),
        "modulos_mas_grandes": inventario_modulos()[:10],
    }


# --------------------------------------------------------------------------
# Línea base
# --------------------------------------------------------------------------


def cargar_baseline(ruta: Path) -> dict[str, int]:
    """Lee una línea base de contadores (vacío si no existe o está corrupta)."""
    if not ruta.exists():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: int(v) for k, v in datos.get("contadores", {}).items()}


def comparar(actual: dict[str, int], base: dict[str, int]) -> list[str]:
    """Lista de empeoramientos respecto a la línea base."""
    return [f"{k}: {base.get(k, 0)} -> {v}"
            for k, v in sorted(actual.items()) if v > base.get(k, 0)]


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Ejecuta la auditoría y devuelve el código de salida."""
    parser = argparse.ArgumentParser(
        description="Auditoría de las 22 reglas de docs/ESPECIFICACION_ARQUITECTURA.md")
    parser.add_argument("--resumen", action="store_true", help="solo contadores")
    parser.add_argument("--json", action="store_true", help="salida máquina")
    parser.add_argument("--baseline", metavar="FICHERO", type=Path,
                        help="compara los contadores con esta línea base")
    parser.add_argument("--guardar", metavar="FICHERO", type=Path,
                        help="escribe la línea base actual")
    parser.add_argument("--detalle", type=int, default=20,
                        help="hallazgos mostrados por regla (por defecto 20)")
    args = parser.parse_args(argv)

    reglas = evaluar()
    actual = contadores(reglas)

    if args.guardar:
        args.guardar.write_text(
            json.dumps({"contadores": actual}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        print(f"Línea base escrita en {args.guardar}")

    if args.json:
        print(json.dumps(como_json(reglas), indent=2, ensure_ascii=False))
    elif args.resumen:
        imprimir_resumen(reglas)
    else:
        imprimir_informe(reglas, detalle=args.detalle)
        imprimir_resumen(reglas)

    if args.baseline:
        base = cargar_baseline(args.baseline)
        empeoramientos = comparar(actual, base)
        if empeoramientos:
            print("\nHA EMPEORADO respecto a la línea base:")
            for e in empeoramientos:
                print(f"   {e}")
            return 1
        print(f"\nSin empeoramientos respecto a {args.baseline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
