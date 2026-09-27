#!/usr/bin/env python3
"""
Auditoría de arquitectura de Quotom (v2 — estándar de 22 reglas).

Verifica el cumplimiento de "Arquitectura Modular Desacoplada":

  Reglas 1, 4        Acoplamiento de vistas (parent / parentWidget / window)
  Reglas 2, 8-13     QUndoCommand canónico; commands sin widgets ni inspección
  Reglas 3, 10, 15, 20  core/ sin Qt, sin Signals, sin objetos gráficos
  Reglas 5, 6        view.py sin SQL ni acceso a database
  Reglas 7, 14       Vistas hermanas no se conocen entre sí
  Regla  9           Lógica de negocio en core/services y core/business_rules
  Regla  16          Tests organizados por capa
  Regla  17          Sin inspección dinámica de dependencias
  Reglas 18, 19      Estilos centralizados; sin setStyleSheet disperso
  Regla  21          Iconos vía ui.icons.get_icon()
  Estructura         Árbol objetivo (core/services, tests/{core,commands,controllers}...)

Uso:
    python3 tools/audit_rules.py            # informe completo
    python3 tools/audit_rules.py --resumen  # solo contadores

Criterio de refactor: cada contador debe BAJAR, nunca subir.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = {"env", "__pycache__", "build", "dist", ".git", ".pytest_cache"}

COUNTS: dict[str, int] = {}


# Excepciones justificadas y documentadas (ver AUDIT_V2_REPORT.md §8).
JUSTIFIED_EXCEPTIONS = {
    "project_editor/view.py":
        "el canvas (PlanGraphicsView) es un widget compartido por 2 features (Regla 19)",
    "auto_namer/commands.py":
        "el auto-nombrador no crea comandos: devuelve el mapeo de nombres y el gestor "
        "de páginas (con su propio QUndoStack) es quien los aplica",
    "common/pdf/":
        "soporte PDF/caché compartido; el spec solo describe common/widgets y common/commands",
}


def py_files(base: Path):
    """Genera los .py del árbol dado, excluyendo entornos y artefactos de build."""
    for path in sorted(base.rglob("*.py")):
        if any(part in EXCLUDE for part in path.parts):
            continue
        yield path


def rel(path: Path) -> str:
    """Ruta relativa al proyecto."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def grep(files, pattern: str, flags: int = 0):
    """Busca un patrón regex línea a línea y devuelve (archivo, línea, texto)."""
    rx = re.compile(pattern, flags)
    hits = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append((rel(f), i, line.strip()[:110]))
    return hits


def ast_refs_prefix(files, prefixes: tuple[str, ...]):
    """
    Referencias **reales** (AST) a identificadores que empiezan por algún prefijo.

    Se usa para familias de clases como ``QGraphics*`` sin depender de listas fijas.

    Returns:
        Lista de tuplas ``(archivo, línea, descripción)``.
    """
    hits = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name and name.startswith(prefixes):
                hits.append((rel(f), node.lineno, f"referencia a {name}"))
    return hits


def section(title: str) -> None:
    """Imprime un encabezado de sección."""
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def ast_refs(files, names: set[str]):
    """
    Referencias **reales** a nombres dados, usando el AST de Python.

    A diferencia de ``grep``, ignora docstrings y comentarios, por lo que las
    menciones explicativas en la documentación no cuentan como violaciones.

    Returns:
        Lista de tuplas ``(archivo, línea, descripción)``.
    """
    hits = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in names:
                hits.append((rel(f), node.lineno, f"referencia a {node.id}"))
            elif isinstance(node, ast.Attribute) and node.attr in names:
                hits.append((rel(f), node.lineno, f"referencia a .{node.attr}"))
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in names or (node.module or "") in names:
                        hits.append((rel(f), node.lineno, f"importa {alias.name}"))
    return hits


def report(title: str, hits, key: str, limit: int = 30) -> None:
    """Imprime un bloque de hallazgos y acumula su contador."""
    COUNTS[key] = COUNTS.get(key, 0) + len(hits)
    print(f"\n{title}  -> {len(hits)}")
    if not hits:
        print("   (ninguna)")
        return
    for f, i, line in hits[:limit]:
        print(f"   {f}:{i}  {line}")
    if len(hits) > limit:
        print(f"   ... y {len(hits) - limit} más")


CORE = list(py_files(ROOT / "core"))
UI = list(py_files(ROOT / "ui"))
COMMON = list(py_files(ROOT / "common"))
TESTS = list(py_files(ROOT / "tests"))
WIDGETS = list(py_files(ROOT / "common" / "widgets"))
VIEW_PY = [p for p in UI if p.name == "view.py"]
CMD_PY = [p for p in UI if p.name == "commands.py"]
_global_cmds = ROOT / "common/commands/global_commands.py"
if _global_cmds.exists():
    CMD_PY.append(_global_cmds)
CTRL_PY = [p for p in UI if p.name == "controller.py" or p.name.endswith("_controller.py")]
ALL_APP = CORE + UI + COMMON + [ROOT / "main.py"]

# ==================================================== 1. ESTRUCTURA OBJETIVO
section("1. ESTRUCTURA OBJETIVO")
estructura = 0

for d in [
    "core", "core/services", "common", "common/commands", "common/widgets",
    "ui", "ui/styles", "ui/icons", "ui/views", "ui/views/main_window",
    "ui/views/project_editor", "tests", "tests/core", "tests/commands",
    "tests/controllers",
]:
    ok = (ROOT / d).is_dir()
    estructura += 0 if ok else 1
    print(f"   {'OK   ' if ok else 'FALTA'} {d}/")

print("\n[1.1] Archivos clave del núcleo:")
for f in ["core/models.py", "core/business_rules.py", "core/services/project_service.py",
          "core/services/drawing_service.py", "core/services/annotation_service.py",
          "common/commands/global_commands.py", "requirements.txt", "main.py"]:
    ok = (ROOT / f).is_file()
    estructura += 0 if ok else 1
    print(f"   {'OK   ' if ok else 'FALTA'} {f}")

print("\n[1.2] __init__.py faltantes:")
for d in ["core", "core/services", "common", "common/commands", "common/widgets",
          "ui", "ui/styles", "ui/icons", "ui/views", "ui/views/main_window",
          "ui/views/project_editor", "tests", "tests/core", "tests/commands",
          "tests/controllers", "common/pdf", "ui/views/auto_namer"]:
    p = ROOT / d
    if p.is_dir() and not (p / "__init__.py").exists():
        print(f"   FALTA {d}/__init__.py")
        estructura += 1

print("\n[1.3] Features en ui/views/ (view + controller + commands):")
for d in sorted((ROOT / "ui/views").iterdir()):
    if d.is_dir() and d.name != "__pycache__":
        files = sorted(x.name for x in d.glob("*.py"))
        falta = []
        if not (d / "view.py").exists():
            falta.append("view.py")
        if not (d / "commands.py").exists():
            falta.append("commands.py")
        if not [n for n in files if n == "controller.py" or n.endswith("_controller.py")]:
            falta.append("controller.py")
        print(f"   {d.name}/ -> {files}")
        if falta:
            for f_name in list(falta):
                key = f"{d.name}/{f_name}"
                if key in JUSTIFIED_EXCEPTIONS:
                    print(f"      excepción documentada: {f_name} "
                          f"({JUSTIFIED_EXCEPTIONS[key]})")
                    falta.remove(f_name)
        if falta:
            print(f"      falta: {falta}")
            estructura += len(falta)

print("\n[1.4] common/ por subcarpeta (regla 19):")
for d in sorted((ROOT / "common").iterdir()):
    if d.is_dir() and d.name != "__pycache__":
        print(f"   {d.name}/ ({len(list(d.glob('*.py')))} .py)")

COUNTS["estructura"] = estructura

# ============================================ 2. CORE SIN QT (reglas 3,10,15)
section("2. REGLA 3/10/15/20 — core/ INDEPENDIENTE DE Qt")
report("[2.1] core/ importa PySide6 / PyQt",
       grep(CORE, r"^\s*(from|import)\s+(PySide6|PyQt[56])"), "regla3")
report("[2.2] core/ usa nombres de Qt (QWidget|QObject|Signal|QIcon|QGraphicsItem|QApplication)",
       ast_refs(CORE, {"QWidget", "QObject", "Signal", "QIcon",
                       "QGraphicsItem", "QApplication"}), "regla3")
report("[2.3] core/ importa capas UI",
       grep(CORE, r"^\s*(from|import)\s+(ui|common)\b"), "regla3")
report("[2.4] core/ usa objetos gráficos (regla 21: gráficos fuera del dominio)",
       ast_refs_prefix(CORE, ("QGraphics",)), "regla21")

# ======================================== 3. VIEWS SIN SQL/DB (reglas 5,6)
section("3. REGLA 5/6 — view.py SIN SQL NI ACCESO A DATABASE")
report("[3.1] view.py con SQL directo",
       grep(VIEW_PY, r"\b(SELECT|INSERT INTO|UPDATE |DELETE FROM|CREATE TABLE)\b"), "regla5")
report("[3.2] view.py acoplada a core.database",
       grep(VIEW_PY, r"core\.database|DatabaseManager"), "regla5")

# ==================================== 4. ACOPLAMIENTO VISTAS (reglas 1,4,7)
section("4. REGLA 1/4/7/14 — DESACOPLAMIENTO DE VISTAS")
report("[4.1] Widgets llamando a parent()/parentWidget()/window()",
       grep(WIDGETS, r"\bself\.parent\(\)|\bself\.parentWidget\(\)|\bself\.window\(\)"), "regla1")
report("[4.2] Acceso a estado privado de la ventana (mw._ / main_window._)",
       grep(WIDGETS, r"mw\._|main_window\._"), "regla1")
report("[4.3] Acceso a scene().views() (hijo -> vista)",
       grep(ALL_APP, r"scene\(\)\.views\(\)"), "regla1")
report("[4.4] Vistas hermanas importándose entre sí",
       grep(VIEW_PY, r"^\s*(from|import)\s+ui\.views\.(?!main_window\b|project_editor\b)"), "regla7")

# ============================================ 5. COMMANDS (reglas 2,8-14)
section("5. REGLA 2/8-14 — QUndoCommand CANÓNICO")
print(f"\n[5.0] commands.py: {[rel(p) for p in CMD_PY]}")
# Comprobaciones por AST: ignoran docstrings/comentarios (evitan falsos positivos).
report("[5.1] commands.py con inspección dinámica real",
       ast_refs(CMD_PY, {"hasattr", "getattr", "setattr"}), "regla2")
report("[5.2] commands.py con _applied_once",
       ast_refs(CMD_PY, {"_applied_once"}), "regla2")
report("[5.3] commands.py manipulando widgets",
       ast_refs(CMD_PY, {"QtWidgets", "showMessage", "setText", "setVisible",
                         "setStyleSheet", "_sidebar", "_status_bar"}), "regla2")
report("[5.4] commands.py capturando una QUndoStack (impide una pila por ventana)",
       ast_refs(CMD_PY, {"QUndoStack", "QUndoGroup"}), "regla2")
print("\n[5.5] Estructura de cada comando (redo/undo + protocolo):")
for p in CMD_PY:
    text = p.read_text(encoding="utf-8")
    print(f"   {rel(p)}: {len(re.findall(r'\(QUndoCommand\)', text))} comandos, "
          f"{len(re.findall(r'\(Protocol\)', text))} Protocol, "
          f"redo={len(re.findall(r'^    def redo', text, re.M))}, "
          f"undo={len(re.findall(r'^    def undo', text, re.M))}")

# ============================ 6. INSPECCIÓN DINÁMICA GLOBAL (regla 13/17)
section("6. REGLA 13/17 — INSPECCIÓN DINÁMICA EN CÓDIGO DE APLICACIÓN")
report("[6.1] hasattr/getattr/setattr en core/",
       grep(CORE, r"\b(hasattr|getattr|setattr)\("), "regla17")
report("[6.2] hasattr/getattr/setattr en ui/views/ (controllers incluidos)",
       grep([p for p in UI if "views" in p.parts], r"\b(hasattr|getattr|setattr)\("), "regla17")
report("[6.3] hasattr/getattr/setattr en common/widgets/",
       grep(WIDGETS, r"\b(hasattr|getattr|setattr)\("), "regla17")

# ================================ 7. SERVICIOS Y CONTROLLERS (reglas 8,9,10)
section("7. REGLA 8/9/10 — SERVICIOS, BUSINESS RULES Y CONTROLLERS")
print(f"\n[7.1] Servicios de dominio en core/services/: "
      f"{len(list((ROOT / 'core/services').glob('*.py'))) if (ROOT / 'core/services').is_dir() else 0} archivos")
report("[7.2] Controllers accediendo directamente a la BD (regla 8)",
       grep(CTRL_PY, r"self\._db\b|\b\w+\.db\b"), "regla8")

# Guardarraíl EXTRA (no es una regla del spec, pero cubre un punto ciego real:
# helpers de la capa UI, como el portapapeles, que accedían a `project_mgr.db`).
ui_db = [h for h in grep(UI, r"\b\w+\.db\s*\.") if "__pycache__" not in str(h[0])]
print(f"\n[7.2b] *Acceso a la BD en la capa UI* (guardarraíl extra)  -> {len(ui_db)}")
for f, i, t in ui_db:
    print(f"   {rel(f)}:{i}  {t}")
print("\n[7.3] Tamaño de los controllers (heurística de lógica de negocio):")
for p in sorted(CTRL_PY):
    n = len(p.read_text(encoding="utf-8").splitlines())
    flag = "  <-- revisar (posible lógica de negocio)" if n > 400 else ""
    print(f"   {rel(p)}: {n} líneas{flag}")

# ================================= 8. ESTILOS E ICONOS (reglas 18, 21)
section("8. REGLA 18/21 — ESTILOS CENTRALIZADOS E ICONOS")
hits = grep(UI + COMMON, r"\.setStyleSheet\(")
by_file: dict[str, list[int]] = {}
for f, i, _ in hits:
    by_file.setdefault(f, []).append(i)
print(f"\n[8.1] setStyleSheet() inline -> {len(hits)} en {len(by_file)} archivos")
for f, lines in sorted(by_file.items(), key=lambda kv: -len(kv[1])):
    print(f"   {f}  ({len(lines)}): {lines[:10]}{'...' if len(lines) > 10 else ''}")
inline = [h for h in hits if "ui/styles/style_manager.py" not in h[0]]
COUNTS["regla4"] = len(inline)
print(f"   (excluyendo style_manager.py -> {len(inline)} violaciones)")
report("[8.2] setProperty() (estado dinámico legítimo)",
       grep(UI + COMMON, r"\.setProperty\("), "ok_setproperty")
init = (ROOT / "ui/icons/__init__.py").read_text(encoding="utf-8") \
    if (ROOT / "ui/icons/__init__.py").exists() else ""
print(f"\n[8.3] Fábrica get_icon: {'OK' if 'def get_icon(' in init else 'FALTA'}")
print(f"      Usos de la fábrica: {len(grep(UI + COMMON, r'get_icon[(]'))}")

# ========================================== 9. LAYOUT DE TESTS (regla 16)
section("9. REGLA 16 — ORGANIZACIÓN DE TESTS")
for d in ["tests/core", "tests/commands", "tests/controllers"]:
    n = len(list((ROOT / d).glob("test_*.py"))) if (ROOT / d).is_dir() else 0
    print(f"   {'OK   ' if n else 'FALTA'} {d}/ ({n} tests)")
print(f"   Raíz de tests/: {len([p for p in TESTS if p.parent == ROOT / 'tests'])} archivos")
print("   Nota: core/ debe poder probarse SIN iniciar Qt (regla 20).")
report("[9.1] Tests de core que importan Qt (viola regla 20)",
       grep([p for p in TESTS if "core" in p.parts],
            r"^\s*(from|import)\s+(PySide6|PyQt)"), "regla20")

# ================================================= 10. RESTOS / DEUDA
section("10. RESTOS / DEUDA TÉCNICA")
report("[10.1] referencias a takeoff_viewer", grep(ALL_APP, r"takeoff_viewer"), "restos")
report("[10.2] theme_module huérfano", grep(ALL_APP, r"theme_module"), "restos")
print("\n[10.3] shiboken6 usado sin import:")
for f in ALL_APP:
    if f.exists() and "shiboken6." in f.read_text(encoding="utf-8"):
        if "import shiboken6" not in f.read_text(encoding="utf-8"):
            print(f"   FALTA import en {rel(f)}")
            COUNTS["restos"] = COUNTS.get("restos", 0) + 1

# ================================================= 11. RESUMEN
section("RESUMEN")
labels = [
    ("regla1", "Regla 1/4 (vistas desacopladas)"),
    ("regla2", "Regla 2/8-13 (commands)"),
    ("regla3", "Regla 3/10/15/20 (core sin Qt)"),
    ("regla4", "Regla 18 (estilos)"),
    ("regla5", "Regla 5/6 (view sin SQL)"),
    ("regla7", "Regla 7/14 (vistas hermanas)"),
    ("regla8", "Regla 8 (controllers sin BD)"),
    ("regla17", "Regla 13/17 (inspección dinámica)"),
    ("regla20", "Regla 20 (tests de core sin Qt)"),
    ("regla21", "Regla 21 (gráficos fuera del dominio)"),
    ("estructura", "Estructura objetivo"),
    ("restos", "Restos / deuda"),
]
for key, label in labels:
    value = COUNTS.get(key, 0)
    mark = "OK " if value == 0 else "   "
    print(f"   {mark}{label:38s}: {value:3d}")
print(f"\n   TOTAL: {sum(v for k, v in COUNTS.items() if k != 'ok_setproperty'):3d}")

if __name__ == "__main__":
    raise SystemExit(0)
