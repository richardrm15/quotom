"""
Tests del auditor de arquitectura (``tools/audit_rules.py``).

El auditor es el instrumento que decide si un cambio **empeora** la arquitectura, así
que él mismo tiene que estar probado: estos tests comprueban que **detecta lo que dice
detectar** y que no se inventa hallazgos.

Estrategia:

* **Primitivas**: las funciones de análisis (AST, búsqueda, clasificación) se prueban
  directamente, con casos construidos en el propio test.
* **Detección por regla**: cada chequeo se ejecuta sobre un **proyecto falso** creado en
  un directorio temporal, con un caso que debe detectar y, cuando aplica, otro que **no**
  debe marcar.
* **Invariantes del instrumento**: que importarlo no tenga efectos, que el código de
  salida sirva de puerta y que el resultado sea determinista.

No usa fixtures de pytest: así el archivo también funciona como script.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from tests.support import PROJECT_ROOT, run_standalone

AUDITOR = PROJECT_ROOT / "tools" / "audit_rules.py"


def _cargar_auditor():
    """Carga `tools/audit_rules.py` como módulo (registrándolo para `dataclasses`)."""
    nombre = "auditor_bajo_prueba"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, AUDITOR)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


aud = _cargar_auditor()

_evluado = None


def reglas_del_proyecto():
    """
    Las 22 reglas evaluadas sobre **este** proyecto, calculadas una sola vez.

    Evaluar el proyecto completo parsea todos los módulos: repetirlo en cada test
    multiplicaría el tiempo de la suite sin aportar nada.
    """
    global _evluado
    if _evluado is None:
        _evluado = aud.evaluar(PROJECT_ROOT)
    return _evluado


@contextlib.contextmanager
def proyecto_falso(archivos: dict[str, str]):
    """Crea un proyecto de mentira y entrega su raíz."""
    with tempfile.TemporaryDirectory(prefix="auditor_") as tmp:
        base = Path(tmp)
        for ruta, contenido in archivos.items():
            destino = base / ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(textwrap.dedent(contenido).lstrip(), encoding="utf-8")
        yield base


def _ast(codigo: str):
    """AST de un fragmento de código."""
    return ast.parse(textwrap.dedent(codigo))


# --------------------------------------------------------------------------
# Primitivas
# --------------------------------------------------------------------------


def test_es_llamada_distingue_funcion_de_metodo_y_de_otras_expresiones():
    """`es_llamada` reconoce `f(x)` y `obj.f(x)`, y descarta lo que no es llamada."""
    arbol = _ast('''
        hasattr(x, "y")
        mw._stack.canUndo()
        valor = 3
    ''')
    sentencias = list(arbol.body)
    assert aud.es_llamada(sentencias[0].value, {"hasattr"}) is True
    assert aud.es_llamada(sentencias[0].value, {"getattr"}) is False
    assert aud.es_llamada(sentencias[1].value, {"canUndo"}) is True
    assert aud.es_llamada(sentencias[2], {"hasattr"}) is False


def test_referencias_ignora_comentarios_y_docstrings():
    """El análisis es con AST: una mención en un docstring no es una violación."""
    arbol = _ast('''
        """Este módulo NO debe importar PySide6."""
        # tampoco aquí: QGraphicsItem
        valor = 1  # QColor
    ''')
    assert aud.referencias(arbol, {"PySide6", "QGraphicsItem", "QColor"}) == []
    arbol2 = _ast("from PySide6.QtGui import QColor")
    assert aud.referencias(arbol2, {"QColor"}) == [(1, "importa QColor")]


def test_clases_que_heredan_solo_devuelve_las_que_heredan():
    """R11 se apoya en esta primitiva: debe filtrar por clase base."""
    arbol = _ast('''
        class Comando(QUndoCommand):
            def redo(self): ...
        class Otra(QObject):
            def redo(self): ...
    ''')
    clases = aud.clases_que_heredan(arbol, "QUndoCommand")
    assert [c.name for c in clases] == ["Comando"]


def test_busca_respeta_mayusculas_salvo_que_se_le_pida_lo_contrario():
    """`busca` es la primitiva de texto: sin IGNORECASE distingue mayúsculas."""
    with proyecto_falso({"ui/views/mi_vista/view.py": "cursor.execute('SELECT a FROM b')\n"}) as base:
        destino = base / "ui/views/mi_vista/view.py"
        assert len(aud.busca([destino], r"\bselect\b")) == 0
        assert len(aud.busca([destino], r"\bselect\b", aud.re.IGNORECASE)) == 1


def test_clasifica_dinamica_separa_los_tres_casos_del_spec():
    """§22.4: estado propio, objeto ajeno y lookup por nombre."""
    casos = {
        'hasattr(self, "_table_view")': "propio",
        "getattr(self._view, 'x', None)": "propio",
        "hasattr(mw, '_undo_stack')": "ajeno",
        "hasattr(item, 'annot_id')": "ajeno",
        "getattr(tokens, nombre_token, None)": "lookup",
    }
    for codigo, esperado in casos.items():
        llamada = _ast(codigo).body[0].value
        assert aud._clasifica_dinamica(llamada) == esperado, codigo


def test_comparar_solo_devuelve_empeoramientos():
    """La puerta de CI se apoya en esto: bajar nunca es un empeoramiento."""
    base = {"R4": 9, "R13": 32}
    assert aud.comparar({"R4": 9, "R13": 32}, base) == []
    assert aud.comparar({"R4": 8, "R13": 0}, base) == []
    assert aud.comparar({"R4": 10, "R13": 32}, base) == ["R4: 9 -> 10"]
    assert aud.comparar({"R4": 9, "R13": 33}, base) == ["R13: 32 -> 33"]


def test_cargar_baseline_tolera_fichero_ausente_o_corrupto():
    """Una línea base ilegible no debe romper la auditoría."""
    with tempfile.TemporaryDirectory() as tmp:
        assert aud.cargar_baseline(Path(tmp) / "no_existe.json") == {}
        corrupto = Path(tmp) / "corrupto.json"
        corrupto.write_text("{esto no es json", encoding="utf-8")
        assert aud.cargar_baseline(corrupto) == {}
        buena = Path(tmp) / "buena.json"
        buena.write_text(json.dumps({"contadores": {"R4": 7}}), encoding="utf-8")
        assert aud.cargar_baseline(buena) == {"R4": 7}

# --------------------------------------------------------------------------
# Detección por regla
# --------------------------------------------------------------------------


def test_r1_detecta_qt_en_el_dominio():
    """R1: un import de Qt en `core/` es un hallazgo."""
    with proyecto_falso({
        "core/models.py": "from PySide6.QtCore import QObject\n",
        "core/limpio.py": "import json\n",
    }) as base:
        hallazgos = aud.chequeo_r1(base)
        assert len(hallazgos) == 1
        assert hallazgos[0].archivo.endswith("core/models.py")


def test_r2_detecta_sql_en_minusculas_y_no_confunde_metodos():
    """R2: el auditor viejo solo veía SQL en mayúsculas; este no."""
    with proyecto_falso({
        "ui/views/a/view.py": "cursor.execute('select * from drawings')\n",
        "ui/views/b/view.py": "db.execute('DELETE FROM drawings')\n",
        "ui/views/c/view.py": "self.update()\nself.table.update_page_name('x')\n",
    }) as base:
        hallazgos = aud.chequeo_r2(base)
        archivos = sorted(h.archivo for h in hallazgos)
        assert len(hallazgos) == 2, hallazgos
        assert archivos[0].endswith("ui/views/a/view.py")
        assert archivos[1].endswith("ui/views/b/view.py")


def test_r3_detecta_acceso_a_la_base_de_datos_desde_la_vista():
    """R3: la vista no puede hablar con `core.database`."""
    with proyecto_falso({
        "ui/views/a/view.py": "from core.database import DatabaseManager\n",
        "ui/views/b/view.py": "self.servicio.listar()\n",
    }) as base:
        assert len(aud.chequeo_r3(base)) == 1


def test_r4_detecta_llamadas_al_padre_y_no_menciones_en_texto():
    """R4: cuenta llamadas de verdad; un docstring que las menciona no cuenta."""
    with proyecto_falso({
        "common/widgets/a.py": '"""Aquí NO se llama a self.window()."""\n# self.parent()\n',
        "common/widgets/b.py": "win = self.window()\npadre = self.parent()\n",
    }) as base:
        hallazgos = aud.chequeo_r4(base)
        assert len(hallazgos) == 2, hallazgos
        assert {h.linea for h in hallazgos} == {1, 2}


def test_r7_detecta_import_entre_features_sin_listas_blancas():
    """R7: ninguna feature puede importar de otra (el auditor viejo las exceptuaba)."""
    with proyecto_falso({
        "ui/views/main_window/view.py": "from ui.views.project_editor.commands import C\n",
        "ui/views/project_editor/view.py": "from common.widgets.title_bar import T\n",
    }) as base:
        hallazgos = aud.chequeo_r7(base)
        assert len(hallazgos) == 1, hallazgos
        assert "project_editor" in hallazgos[0].mensaje


def test_r6_detecta_llamada_a_metodo_privado_de_un_colaborador():
    """R6: un controller no debe llamar a la parte privada de la vista."""
    with proyecto_falso({
        "ui/views/a/controller.py": (
            "class C:\n"
            "    def f(self):\n"
            "        self._vista.set_titulo('x')\n"
            "        self._vista._refrescar_interno()\n"
            "        self._servicio.listar()\n"
            "        self._ajuste_local = 1\n"
        ),
    }) as base:
        hallazgos = aud.chequeo_r6(base)
        assert len(hallazgos) == 1, hallazgos
        assert "_refrescar_interno" in hallazgos[0].mensaje


def test_r8_detecta_bd_en_controller_y_presupuesto_de_tamano_en_cualquier_capa():
    """R8: acceso a la BD y presupuesto de tamaño, mirando core/, common/ y ui/."""
    grande = "\n".join("x = 1" for _ in range(aud.LIMITE_MODULO_UI + 5))
    with proyecto_falso({
        "ui/views/a/controller.py": "self._db.consultar('x')\n",
        "core/gigante.py": grande + "\n",
        "common/widgets/otro_gigante.py": grande + "\n",
        "ui/views/a/pequeno.py": "x = 1\n",
    }) as base:
        hallazgos = aud.chequeo_r8(base)
        resumen = " || ".join(f"{h.archivo}: {h.mensaje}" for h in hallazgos)
        assert len(hallazgos) == 3, resumen
        assert any("_db" in h.mensaje for h in hallazgos)
        assert any(h.archivo.endswith("core/gigante.py") for h in hallazgos)
        assert any(h.archivo.endswith("common/widgets/otro_gigante.py") for h in hallazgos)

def test_r10_detecta_comando_que_captura_la_pila():
    """R10: un comando no debe conocer la QUndoStack."""
    with proyecto_falso({
        "ui/views/a/commands.py": (
            "class C(QUndoCommand):\n"
            "    def __init__(self, stack: QUndoStack, servicio):\n"
            "        self._stack = stack\n"
            "    def redo(self): ...\n"
            "    def undo(self): ...\n"
        ),
        "ui/views/b/commands.py": (
            "class D(QUndoCommand):\n"
            "    def __init__(self, servicio):\n"
            "        self._servicio = servicio\n"
            "    def redo(self): ...\n"
            "    def undo(self): ...\n"
        ),
    }) as base:
        hallazgos = aud.chequeo_r10(base)
        assert len(hallazgos) == 1, hallazgos
        assert hallazgos[0].archivo.endswith("ui/views/a/commands.py")


def test_r11_detecta_comando_sin_undo():
    """R11: todo QUndoCommand debe definir redo() y undo()."""
    with proyecto_falso({
        "ui/views/a/commands.py": (
            "class SinUndo(QUndoCommand):\n"
            "    def redo(self): ...\n"
            "class Completo(QUndoCommand):\n"
            "    def redo(self): ...\n"
            "    def undo(self): ...\n"
        ),
    }) as base:
        hallazgos = aud.chequeo_r11(base)
        assert len(hallazgos) == 1, hallazgos
        assert "SinUndo" in hallazgos[0].mensaje and "undo" in hallazgos[0].mensaje


def test_r12_detecta_el_hack_del_primer_redo():
    """R12: `_applied_once` y equivalentes están prohibidos (definición y uso)."""
    with proyecto_falso({
        "ui/views/a/commands.py": (
            "class C(QUndoCommand):\n"
            "    def __init__(self):\n"
            "        self._applied_once = False\n"
            "    def redo(self):\n"
            "        if self._applied_once:\n"
            "            return\n"
        ),
    }) as base:
        assert len(aud.chequeo_r12(base)) == 2


def test_r13_separa_violaciones_de_estado_propio_y_excepciones():
    """R13: solo el objeto ajeno es violación; el resto se informa aparte."""
    with proyecto_falso({
        "ui/views/a/view.py": (
            "if hasattr(mw, '_undo_stack'):\n"
            "    pass\n"
            "if hasattr(self, '_tabla'):\n"
            "    pass\n"
            "valor = getattr(tokens, nombre, None)\n"
        ),
    }) as base:
        violaciones, propios, excepciones = aud.chequeo_r13(base)
        assert len(violaciones) == 1 and "otro objeto" in violaciones[0].mensaje
        assert len(propios) == 1 and "propio estado" in propios[0].mensaje
        assert len(excepciones) == 1 and "ejecución" in excepciones[0].mensaje


def test_r14_detecta_la_llamada_a_un_widget_importado_directo():
    """R14: el caso que el auditor viejo NO veía (`QMessageBox.warning(...)`)."""
    with proyecto_falso({
        "ui/views/a/commands.py": (
            "from PySide6.QtWidgets import QMessageBox\n"
            "class C(QUndoCommand):\n"
            "    def redo(self):\n"
            "        QMessageBox.warning(None, 'titulo', 'mensaje')\n"
            "    def undo(self): ...\n"
        ),
        "ui/views/b/commands.py": (
            "class D(QUndoCommand):\n"
            "    def __init__(self, servicio):\n"
            "        self._servicio = servicio\n"
            "    def redo(self): self._servicio.renombrar()\n"
            "    def undo(self): self._servicio.renombrar()\n"
        ),
    }) as base:
        hallazgos = aud.chequeo_r14(base)
        archivos = {h.archivo for h in hallazgos}
        assert any("a/commands.py" in a for a in archivos), hallazgos
        assert not any("b/commands.py" in a for a in archivos), hallazgos


def test_r15_y_r21_detectan_qt_y_graficos_en_el_dominio():
    """R15 (Signals) y R21 (objetos gráficos) miran `core/`."""
    with proyecto_falso({
        "core/models.py": "from PySide6.QtCore import Signal\n",
        "core/color_utils.py": "from PySide6.QtGui import QColor\n",
    }) as base:
        assert len(aud.chequeo_r15(base)) == 1
        assert len(aud.chequeo_r21(base)) >= 1


def test_r16_r17_detecta_qss_inline_salvo_en_el_gestor_de_tema():
    """R16/R17: única excepción justificada, `common/styles/style_manager.py`."""
    with proyecto_falso({
        "common/widgets/a.py": "self.setStyleSheet('color: red')\n",
        "common/styles/style_manager.py": "app.setStyleSheet(qss)\n",
    }) as base:
        hallazgos = aud.chequeo_r16_r17(base)
        assert len(hallazgos) == 1, hallazgos
        assert hallazgos[0].archivo.endswith("common/widgets/a.py")


def test_r20_detecta_tests_de_dominio_que_arrancan_qt():
    """R20: los tests de `core/` no deben iniciar Qt."""
    with proyecto_falso({
        "tests/core/test_a.py": "import PySide6\n",
        "tests/core/test_b.py": "import json\n",
        "tests/ui/test_c.py": "import PySide6\n",
    }) as base:
        hallazgos = aud.chequeo_r20(base)
        assert len(hallazgos) == 1, hallazgos
        assert hallazgos[0].archivo.endswith("tests/core/test_a.py")

# --------------------------------------------------------------------------
# Invariantes del instrumento
# --------------------------------------------------------------------------


def test_importar_el_auditor_no_produce_ninguna_salida():
    """
    Regresión del auditor viejo: ejecutaba toda la auditoría al importarse.

    Se comprueba en un subproceso, que es la única forma de observar los efectos de
    un import limpio.
    """
    codigo = (
        "import runpy, sys;"
        f"runpy.run_path(r'{AUDITOR}');"
        "sys.stdout.write('IMPORT_OK')"
    )
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    assert r.stdout == "IMPORT_OK", f"el import produjo salida: {r.stdout[:200]!r}"


def test_el_informe_de_las_22_reglas_es_completo_y_coherente():
    """Las 22 reglas del spec existen, con identificador único y tipo válido."""
    reglas = reglas_del_proyecto()
    assert [r.id for r in reglas] == [f"R{n}" for n in range(1, 23)]
    for r in reglas:
        assert r.tipo in {"auto", "informativa", "manual"}, r.id
        assert r.titulo and r.revisa, r.id
    # Las manuales no pueden tener contador: no se cuentan porque no se miden.
    manuales = {r.id for r in reglas if r.tipo == "manual"}
    assert manuales == {"R5", "R22"}
    assert manuales.isdisjoint(aud.contadores(reglas))
    # R16 y R17 comparten hallazgos (el mismo incumplimiento rompe ambas).
    r16 = next(r for r in reglas if r.id == "R16")
    r17 = next(r for r in reglas if r.id == "R17")
    assert r16.hallazgos == r17.hallazgos


def test_la_auditoria_es_determinista():
    """Dos ejecuciones seguidas deben dar exactamente los mismos contadores."""
    primera = aud.contadores(reglas_del_proyecto())
    segunda = aud.contadores(aud.evaluar(PROJECT_ROOT))
    assert primera == segunda


def test_la_salida_json_es_consumible_y_trae_los_modulos_mas_grandes():
    """El modo máquina es lo que permitirá poner la auditoría en CI."""
    datos = aud.como_json(reglas_del_proyecto())
    for clave in ("reglas", "contadores", "total", "modulos_mas_grandes"):
        assert clave in datos
    assert datos["total"] == sum(datos["contadores"].values())
    assert len(datos["reglas"]) == 22
    modulos = datos["modulos_mas_grandes"]
    assert modulos and all(isinstance(n, int) for _, n in modulos)
    # El orden debe ser de mayor a menor (es el inventario de riesgo estructural)
    tamanos = [n for _, n in modulos]
    assert tamanos == sorted(tamanos, reverse=True)
    json.dumps(datos)  # serializable


def test_el_codigo_de_salida_sirve_de_puerta():
    """`main` devuelve 0 sin empeoramientos y 1 cuando un contador sube."""
    with tempfile.TemporaryDirectory() as tmp:
        silencio = io.StringIO()
        with contextlib.redirect_stdout(silencio):
            assert aud.main(["--resumen"]) == 0

        base_actual = Path(tmp) / "actual.json"
        with contextlib.redirect_stdout(silencio):
            assert aud.main(["--guardar", str(base_actual), "--resumen"]) == 0
        assert aud.cargar_baseline(base_actual) == aud.contadores(reglas_del_proyecto())

        with contextlib.redirect_stdout(silencio):
            assert aud.main(["--baseline", str(base_actual), "--resumen"]) == 0

        # Línea base imposible (todo a 0): cualquier hallazgo real es un empeoramiento
        falsa = Path(tmp) / "falsa.json"
        falsa.write_text(json.dumps({"contadores": {r.id: 0 for r in reglas_del_proyecto()}}),
                         encoding="utf-8")
        with contextlib.redirect_stdout(silencio):
            codigo = aud.main(["--baseline", str(falsa), "--resumen"])
        assert codigo == 1


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
