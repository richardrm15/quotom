"""
Tests de la composición del nombre de plano (``autonamer/naming.py``).

La regla estaba **triplicada** (diálogo, worker y aplicación final). Para probar
que la extracción no alteró el comportamiento, además de los casos explícitos se
incluye una **prueba diferencial**: una copia literal del algoritmo anterior se
compara contra el nuevo sobre un producto cartesiano de entradas.
"""
from __future__ import annotations

import itertools
import sys

from tests.support import run_standalone

from ui.views.auto_namer.naming import assemble_name, has_captured_text


def _implementacion_anterior(values, separators) -> str:
    """
    Copia literal del algoritmo que vivía en el diálogo y en el worker.

    Se conserva **solo** como referencia de contraste para la prueba diferencial;
    no debe usarse en producción.
    """
    parts = []
    has_captured_text = False
    for idx, val in enumerate(values):
        if val:
            has_captured_text = True
        parts.append(val)
        if idx < len(separators):
            parts.append(separators[idx])
    if not has_captured_text:
        return ""
    assembled = "".join(parts).strip()
    for sep in separators:
        s_val = sep.strip()
        if s_val and assembled.endswith(s_val):
            assembled = assembled[: -len(s_val)].strip()
        if s_val and assembled.startswith(s_val):
            assembled = assembled[len(s_val) :].strip()
    return assembled


# ------------------------------------------------------------------- casos base

def test_compone_el_nombre_con_los_separadores():
    """Caso normal: número y título unidos por el separador por defecto."""
    assert assemble_name(["A-101", "PLANTA BAJA"], [" - "]) == "A-101 - PLANTA BAJA"


def test_poda_el_separador_suelto_cuando_falta_una_zona():
    """Si una zona no capturó texto, no queda un separador huérfano."""
    assert assemble_name(["A-101", ""], [" - "]) == "A-101"
    assert assemble_name(["", "PLANTA BAJA"], [" - "]) == "PLANTA BAJA"


def test_sin_zonas_con_texto_devuelve_vacio():
    """Sin texto capturado no se propone ningún nombre (no se renombra la página)."""
    assert assemble_name(["", ""], [" - "]) == ""
    assert assemble_name([], []) == ""


def test_tres_zonas_con_dos_separadores():
    """El último valor puede quedarse sin separador."""
    assert (
        assemble_name(["A-101", "PLANTA", "NIVEL 2"], [" - ", " "])
        == "A-101 - PLANTA NIVEL 2"
    )


def test_separador_de_solo_espacios_se_conserva_en_medio():
    """
    Un separador de solo espacios se conserva entre los valores (es el separador
    que eligió el usuario) y no sirve para podar extremos, porque al hacerle
    ``strip`` no queda ningún símbolo reconocible.
    """
    assert assemble_name(["A-101", "PLANTA"], ["   "]) == "A-101   PLANTA"


def test_respeta_el_contenido_interno_de_las_zonas():
    """Los guiones del propio dato (código de plano) no se confunden con separadores."""
    assert assemble_name(["A-101", "PLANTA"], ["-"]) == "A-101-PLANTA"


def test_has_captured_text():
    """La condición de renombrado es 'al menos una zona aportó texto'."""
    assert has_captured_text(["", "PLANTA"]) is True
    assert has_captured_text(["", ""]) is False
    assert has_captured_text([]) is False


def test_caso_limite_separador_igual_que_el_dato():
    """Si el dato es igual al separador, el resultado se vacía (comportamiento heredado)."""
    assert assemble_name(["-"], ["-"]) == ""
    # ...pero la zona SÍ aportó texto: el worker conserva el nombre original.
    assert has_captured_text(["-"]) is True


# ------------------------------------------------------------ prueba diferencial

def test_equivalencia_con_la_implementacion_anterior():
    """
    El resultado debe ser idéntico al del algoritmo anterior en TODO el espacio
    relevante de entradas: es la garantía de que unificar la regla no cambió nada.
    """
    valores = ["", "A-101", "PLANTA BAJA", "-", "A-101-PLANTA", "  ", "NIVEL 2"]
    separadores = ["", " - ", "-", " ", "   ", "/"]

    casos = 0
    for n_zonas in (1, 2, 3):
        for values in itertools.product(valores, repeat=n_zonas):
            for separators in itertools.product(separadores, repeat=n_zonas):
                esperado = _implementacion_anterior(list(values), list(separators))
                obtenido = assemble_name(list(values), list(separators))
                assert obtenido == esperado, (values, separators, esperado, obtenido)
                casos += 1

    # El espacio de casos debe ser amplio de verdad, no un par de muestras
    assert casos > 50000


if __name__ == "__main__":
    sys.exit(run_standalone(dict(globals())))
