"""
Reglas de composición del nombre de plano (**dominio puro, sin Qt**).

Vive separada del diálogo y del trabajador en segundo plano porque la regla es
la misma en los tres sitios: al previsualizar en vivo, al poblar la tabla en
paralelo y al aplicar los nombres definitivos.

Antes de este módulo esa regla estaba **duplicada en tres lugares**
(`AutoNamerDialog._assemble_name_for_page`, `AutoNamerPreviewWorker.run` y la
aplicación final), con riesgo de que las tres versiones divergieran.
"""

from typing import Sequence


def has_captured_text(values: Sequence[str]) -> bool:
    """
    Indica si al menos una zona aportó texto.

    Es la condición que decide si se renombra la página o se deja el nombre
    original: un plano sin texto capturado **no** debe renombrarse.

    Args:
        values: texto capturado por cada zona (cadena vacía si no aportó nada).

    Returns:
        ``True`` si alguna zona devolvió texto.
    """
    return any(values)


def assemble_name(values: Sequence[str], separators: Sequence[str]) -> str:
    """
    Compone el nombre final uniendo los valores capturados con sus separadores.

    Args:
        values: texto de cada zona, en el orden de las zonas del diálogo.
        separators: separador que va **después** de cada valor; el último valor
            puede quedarse sin separador.

    Returns:
        El nombre compuesto, sin separadores sueltos al principio ni al final,
        o ``""`` si ninguna zona aportó texto (el llamador decide si en ese caso
        conserva el nombre original).
    """
    if not has_captured_text(values):
        return ""

    parts: list[str] = []
    for idx, val in enumerate(values):
        parts.append(val)
        if idx < len(separators):
            parts.append(separators[idx])

    assembled = "".join(parts).strip()

    # El primer/último separador queda suelto cuando la zona vecina no aportó
    # texto (típico cajetín sin capturar): se poda por los dos extremos.
    for sep in separators:
        s_val = sep.strip()
        if not s_val:
            continue
        if assembled.endswith(s_val):
            assembled = assembled[: -len(s_val)].strip()
        if assembled.startswith(s_val):
            assembled = assembled[len(s_val):].strip()

    return assembled
