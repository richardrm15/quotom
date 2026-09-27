"""
Soporte común de la suite de tests de Quotom.

Se encarga de:
1. Forzar el backend Qt *offscreen* ANTES de importar PySide6 (entornos sin display).
2. Añadir la raíz del proyecto a ``sys.path`` para importar ``core``/``common``/``ui``.
3. Proveer una ``QApplication`` única y compartida por todo el proceso.
4. Permitir ejecutar cada archivo de tests como script independiente
   (``python tests/test_x.py``), sin depender de pytest.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# 1. Backend sin display: debe fijarse antes de importar PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 2. Raíz del proyecto en sys.path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_app = None


def app():
    """Retorna la ``QApplication`` compartida, creándola la primera vez."""
    global _app
    from PySide6.QtWidgets import QApplication

    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def run_standalone(namespace: dict) -> int:
    """
    Ejecuta todas las funciones ``test_*`` del namespace dado.

    Permite usar cada archivo de tests como script (sin pytest).

    Returns:
        Código de salida: 0 si todas pasan, 1 si alguna falla.
    """
    tests = [
        (name, obj)
        for name, obj in namespace.items()
        if name.startswith("test_") and callable(obj)
    ]
    failures = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:  # noqa: BLE001 - runner de diagnóstico
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
        else:
            print(f"OK    {name}")

    print(f"\n{len(tests) - failures}/{len(tests)} pruebas OK")
    return 1 if failures else 0


def event_loop_for(ms: int):
    """Crea un ``QEventLoop`` que se cierra solo a los ``ms`` milisegundos."""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    return loop


def make_text_pdf(path: str, lines, page_size: tuple[float, float] = (612.0, 792.0)) -> str:
    """
    Genera un PDF de una página **con capa de texto** real, sin dependencias externas.

    Permite probar de forma determinista la extracción de texto (auto-nombrador,
    búsqueda, OCR) con contenido y coordenadas conocidas, en lugar de depender de
    un PDF de ejemplo que puede no existir en la máquina (el E2E actual se salta
    la prueba si falta).

    Args:
        path: Ruta donde escribir el PDF.
        lines: Iterable de ``(texto, x_pts, y_pts)`` en coordenadas PDF (origen
            en la esquina **inferior** izquierda, como marca la especificación).
        page_size: ``(ancho, alto)`` en puntos. Por defecto tamaño carta.

    Returns:
        La ruta del PDF generado.
    """
    ancho, alto = page_size
    contenido = ["BT", "/F1 12 Tf"]
    for texto, x, y in lines:
        escapado = (
            texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        )
        contenido.append(f"1 0 0 1 {x:g} {y:g} Tm")
        contenido.append(f"({escapado}) Tj")
    contenido.append("ET")
    stream = "\n".join(contenido).encode("latin-1")

    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {ancho:g} {alto:g}] "
            f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("latin-1"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    salida = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for numero, cuerpo in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{numero} 0 obj\n".encode() + cuerpo + b"\nendobj\n"

    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode()
    salida += b"0000000000 65535 f \n"
    for offset in offsets:
        salida += f"{offset:010d} 00000 n \n".encode()
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
        f"startxref\n{inicio_xref}\n%%EOF\n"
    ).encode()

    with open(path, "wb") as f:
        f.write(salida)
    return path


_theme_applied = False


def apply_theme_once(mode: str = "dark") -> None:
    """
    Aplica el tema global **una única vez por proceso**.

    ``QApplication.setStyleSheet()`` desencadena un *restyle* de todo el árbol de
    widgets vivos. Repetirlo mientras el recolector libera widgets de tests
    anteriores provoca en Qt un segfault por puntero colgante (reproducido:
    ``ThemeManager.apply_theme_to_app`` → ``setStyleSheet``). Aplicarlo una sola
    vez basta para que los tests de UI tengan estilo y elimina ese fallo
    intermitente.

    Usar SIEMPRE este helper en los tests en lugar de llamar a
    ``ThemeManager.apply_theme`` directamente.
    """
    global _theme_applied
    if _theme_applied:
        return

    from ui.styles.style_manager import ThemeManager

    ThemeManager.apply_theme(mode)
    _theme_applied = True


def teardown_widgets(*widgets) -> None:
    """
    Libera widgets creados por un test y drena los eventos de borrado pendientes.

    Evita que objetos ``QWidget`` queden vivos (o se liberen tarde) mientras otros
    tests siguen bombeando el bucle de eventos, que es la otra mitad del fallo de
    ``setStyleSheet`` descrito en ``apply_theme_once``.
    """
    from PySide6.QtWidgets import QApplication

    for widget in widgets:
        if widget is not None:
            widget.deleteLater()
    app_instance = QApplication.instance()
    if app_instance is not None:
        app_instance.processEvents()


def imported_top_level_modules(module) -> set[str]:
    """
    Retorna los módulos de nivel superior que importa un módulo Python.

    Usa el AST, por lo que las **menciones en docstrings no cuentan**: sirve para
    verificar que ``core/`` no importa Qt sin falsos positivos.

    Args:
        module: Módulo ya importado (se inspecciona su archivo fuente).
    """
    import ast
    from pathlib import Path

    source = Path(module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    return imported


if __name__ == "__main__":
    sys.exit(0)
