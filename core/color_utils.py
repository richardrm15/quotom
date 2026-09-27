"""
Utilidades de Color ISO 32000-1 para Anotaciones PDF.

Proporciona conversión bidireccional sin pérdida entre:
1. Formato UI/Web: HEX ('#EC4899'), 'rgba(r,g,b,a)', 'transparent'
2. Formato ISO 32000-1:
   - /C  : Arreglo [r, g, b] normalizado (0.0 a 1.0) para color de trazo (Tabla 164).
   - /IC : Arreglo [r, g, b] normalizado (0.0 a 1.0) para color de relleno interior (Tabla 169).
   - /CA : Opacidad de trazo (0.0 a 1.0, Tabla 168).
   - /ca : Opacidad de relleno (0.0 a 1.0).
"""

import re
from typing import Any


def color_to_iso(color_val: Any, default_alpha: float = 1.0) -> tuple[list[float], float]:
    """
    Convierte cualquier representación de color a un vector ISO 32000-1 [r, g, b] (0.0 a 1.0)
    y opacidad alfa (0.0 a 1.0).

    Si el color es None, vacío o 'transparent', retorna ([], 0.0).
    """
    if not color_val or color_val == "transparent":
        return [], 0.0

    if isinstance(color_val, (list, tuple)):
        nums = [float(x) for x in color_val]
        if len(nums) >= 3:
            if any(x > 1.0 for x in nums[:3]):
                nums = [x / 255.0 for x in nums]
            r, g, b = [max(0.0, min(1.0, round(x, 4))) for x in nums[:3]]
            a = max(0.0, min(1.0, round(nums[3], 4))) if len(nums) >= 4 else default_alpha
            return [r, g, b], a
        return [], 0.0

    c_str = str(color_val).strip()
    if c_str.lower() in ("none", "transparent", ""):
        return [], 0.0

    # Formato Hexadecimal (#RGB, #RRGGBB, #RRGGBBAA)
    if c_str.startswith("#"):
        hex_c = c_str.lstrip("#")
        if len(hex_c) == 3:
            hex_c = "".join(ch * 2 for ch in hex_c)
        if len(hex_c) == 6:
            r = int(hex_c[0:2], 16) / 255.0
            g = int(hex_c[2:4], 16) / 255.0
            b = int(hex_c[4:6], 16) / 255.0
            return [round(r, 4), round(g, 4), round(b, 4)], default_alpha
        elif len(hex_c) == 8:
            r = int(hex_c[0:2], 16) / 255.0
            g = int(hex_c[2:4], 16) / 255.0
            b = int(hex_c[4:6], 16) / 255.0
            a = int(hex_c[6:8], 16) / 255.0
            return [round(r, 4), round(g, 4), round(b, 4)], round(a, 4)

    # Formato CSS rgb(r, g, b) o rgba(r, g, b, a)
    m = re.match(
        r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d\.]+))?\s*\)",
        c_str,
        re.IGNORECASE,
    )
    if m:
        r = int(m.group(1)) / 255.0
        g = int(m.group(2)) / 255.0
        b = int(m.group(3)) / 255.0
        a = float(m.group(4)) if m.group(4) is not None else default_alpha
        return [round(r, 4), round(g, 4), round(b, 4)], round(max(0.0, min(1.0, a)), 4)

    return [0.0, 0.0, 0.0], default_alpha


def iso_to_hex(c_array: list[float] | tuple | None) -> str:
    """Convierte un arreglo ISO 32000-1 [r, g, b] (0.0 a 1.0) a formato HEX '#RRGGBB'."""
    if not c_array or len(c_array) < 3:
        return ""
    r = max(0, min(255, int(round(c_array[0] * 255))))
    g = max(0, min(255, int(round(c_array[1] * 255))))
    b = max(0, min(255, int(round(c_array[2] * 255))))
    return f"#{r:02X}{g:02X}{b:02X}"


def iso_to_rgba(c_array: list[float] | tuple | None, alpha: float = 1.0) -> str:
    """Convierte un arreglo ISO 32000-1 [r, g, b] y opacidad a formato CSS 'rgba(r, g, b, a)'."""
    if not c_array or len(c_array) < 3 or alpha <= 0.0:
        return "transparent"
    r = max(0, min(255, int(round(c_array[0] * 255))))
    g = max(0, min(255, int(round(c_array[1] * 255))))
    b = max(0, min(255, int(round(c_array[2] * 255))))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def sync_style_with_iso(style: dict, prefer_iso: bool = False) -> dict:
    """
    Garantiza que el diccionario de estilo contenga tanto las claves de interfaz
    ('stroke_color', 'fill_color', 'fill_opacity') como las claves estándar ISO 32000-1
    ('/C', '/IC', '/CA', '/ca') listas para exportación directa a PDF.
    Si prefer_iso es True, las claves ISO (/C, /IC, /CA, /ca) actualizan a las claves UI.
    """
    st = dict(style or {})

    # 1. Trazo / Stroke -> /C, /CA
    if prefer_iso and "/C" in st:
        st["stroke_color"] = iso_to_hex(st["/C"])
        if "/CA" in st:
            st["stroke_opacity"] = float(st["/CA"])
        c_arr, _ = color_to_iso(st["stroke_color"])
        st["/C"] = c_arr
    elif "stroke_color" in st:
        c_arr, _ = color_to_iso(st["stroke_color"])
        st["/C"] = c_arr
        st["/CA"] = float(st.get("stroke_opacity", 1.0))
    elif "/C" in st:
        st["stroke_color"] = iso_to_hex(st["/C"])
        if "/CA" in st:
            st["stroke_opacity"] = float(st["/CA"])
    else:
        st["/C"] = []
        st["/CA"] = 1.0

    # 2. Relleno interior / Fill -> /IC, /ca
    if prefer_iso and "/IC" in st:
        fill_ca = float(st.get("/ca", 1.0))
        st["fill_color"] = iso_to_rgba(st["/IC"], fill_ca)
        st["fill_opacity"] = fill_ca
        if not st["/IC"]:
            st["fill_color"] = "transparent"
            st["fill_opacity"] = 0.0
            st["/ca"] = 0.0
    elif "fill_color" in st:
        op = float(st.get("fill_opacity", 1.0))
        if st["fill_color"] == "transparent":
            st["/IC"] = []
            st["/ca"] = 0.0
        else:
            ic_arr, extracted_alpha = color_to_iso(st["fill_color"], default_alpha=op)
            st["/IC"] = ic_arr
            st["/ca"] = extracted_alpha
    elif "/IC" in st:
        fill_ca = float(st.get("/ca", 1.0))
        st["fill_color"] = iso_to_rgba(st["/IC"], fill_ca)
        st["fill_opacity"] = fill_ca
    else:
        st["/IC"] = []
        st["/ca"] = 0.0

    return st
