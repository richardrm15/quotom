"""
Módulo de Capa de Texto y Búsqueda para Planos PDF.
Proporciona estructuras optimizadas y funciones de mapeo matemático entre
coordenadas de la página PDF y el espacio de escena QGraphicsScene de Qt.

Dominio puro: la geometría usa ``core.text_geometry`` (``Rect``/``Point``), que
expone la misma API de lectura que ``QRectF``/``QPointF``. No importa PySide6.
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from core.pdf_lock import PDFIUM_LOCK
from core.text_geometry import PointLike, Rect


@dataclass
class CharBox:
    index: int
    char: str
    rect: Rect  # En coordenadas de QGraphicsScene (píxeles de imagen)


@dataclass
class SearchMatch:
    start_char_idx: int
    char_count: int
    text: str
    rects: List[Rect]  # Rectángulos que componen el match en coordenadas de escena


class PageTextData:
    """
    Contenedor optimizado de texto para una página PDF específica.
    Permite selección continua por arrastre, búsqueda y copiado al portapapeles.
    """
    def __init__(self, page_index: int, width_pts: float, height_pts: float, scale: float):
        self.page_index = page_index
        self.width_pts = width_pts
        self.height_pts = height_pts
        self.scale = scale
        self.char_boxes: List[CharBox] = []
        self.full_text: str = ""
        self._grid: dict[tuple[int, int], list[int]] = {}
        self._cell_size: float = 64.0

    @classmethod
    def extract_from_page(cls, doc: pdfium.PdfDocument, page_index: int, scale: float) -> "PageTextData":
        import ctypes
        page = doc[page_index]
        width_pts, height_pts = page.get_size()
        data = cls(page_index, width_pts, height_pts, scale)

        textpage = page.get_textpage()
        count = textpage.count_chars()
        if count <= 0:
            return data

        w_px = int(round(width_pts * scale))
        h_px = int(round(height_pts * scale))

        chars_list = []
        char_boxes = []

        dev_x1 = ctypes.c_int()
        dev_y1 = ctypes.c_int()
        dev_x2 = ctypes.c_int()
        dev_y2 = ctypes.c_int()
        raw_page = page.raw

        full_text = textpage.get_text_range()
        for i in range(count):
            ch = full_text[i] if i < len(full_text) else ""
            chars_list.append(ch)
            l, b, r, t = textpage.get_charbox(i)

            # Usar FPDF_PageToDevice nativo de PDFium para respetar automáticamente
            # la rotación interna del plano (/Rotate 0, 90, 180, 270) y la escala exacta:
            pdfium_c.FPDF_PageToDevice(raw_page, 0, 0, w_px, h_px, 0, l, t, ctypes.byref(dev_x1), ctypes.byref(dev_y1))
            pdfium_c.FPDF_PageToDevice(raw_page, 0, 0, w_px, h_px, 0, r, b, ctypes.byref(dev_x2), ctypes.byref(dev_y2))

            x0 = float(min(dev_x1.value, dev_x2.value))
            x1 = float(max(dev_x1.value, dev_x2.value))
            y0 = float(min(dev_y1.value, dev_y2.value))
            y1 = float(max(dev_y1.value, dev_y2.value))

            w = max(1.0, x1 - x0)
            h = max(1.0, y1 - y0)
            char_boxes.append(CharBox(index=i, char=ch, rect=Rect(x0, y0, w, h)))

        data.char_boxes = char_boxes
        data.full_text = "".join(chars_list)
        # Construir índice espacial para búsqueda instantánea O(1) en mouse move
        cell = data._cell_size
        grid = {}
        for cb in char_boxes:
            r = cb.rect
            gx0 = int(r.left() // cell)
            gx1 = int(r.right() // cell)
            gy0 = int(r.top() // cell)
            gy1 = int(r.bottom() // cell)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    k = (gx, gy)
                    if k not in grid:
                        grid[k] = []
                    grid[k].append(cb.index)
        data._grid = grid
        return data


    def __getstate__(self):
        # Serialización compacta en tuplas nativas (x, y, w, h) para almacenamiento ultrarrápido en disco
        boxes = [(cb.rect.x(), cb.rect.y(), cb.rect.width(), cb.rect.height()) for cb in self.char_boxes]
        return (self.page_index, self.width_pts, self.height_pts, self.scale, self.full_text, boxes)

    def __setstate__(self, state):
        self.page_index, self.width_pts, self.height_pts, self.scale, self.full_text, boxes = state
        self._cell_size = 64.0
        cell = self._cell_size
        char_boxes = []
        grid = {}
        for i, (x, y, w, h) in enumerate(boxes):
            r = Rect(x, y, w, h)
            ch = self.full_text[i] if i < len(self.full_text) else ''
            char_boxes.append(CharBox(index=i, char=ch, rect=r))
            gx0 = int(x // cell)
            gx1 = int((x + w) // cell)
            gy0 = int(y // cell)
            gy1 = int((y + h) // cell)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    k = (gx, gy)
                    if k not in grid:
                        grid[k] = []
                    grid[k].append(i)
        self.char_boxes = char_boxes
        self._grid = grid

    def get_char_index_at(self, scene_pos: PointLike, threshold: float = 40.0) -> Optional[int]:
        """Encuentra el índice del caracter más cercano al punto dado en coordenadas de escena en O(1)."""
        if not self.char_boxes:
            return None

        px, py = scene_pos.x(), scene_pos.y()
        cell = self._cell_size
        radius = max(threshold, 16.0)
        gx0 = int((px - radius) // cell)
        gx1 = int((px + radius) // cell)
        gy0 = int((py - radius) // cell)
        gy1 = int((py + radius) // cell)

        candidates = set()
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                bucket = self._grid.get((gx, gy))
                if bucket:
                    candidates.update(bucket)

        if not candidates:
            return None

        # 1. Búsqueda exacta o con margen ajustado
        for idx in candidates:
            cb = self.char_boxes[idx]
            if cb.rect.adjusted(-8, -8, 8, 8).contains(scene_pos):
                return cb.index

        # 2. Búsqueda por proximidad euclidiana al centro
        best_idx = None
        min_dist_sq = threshold * threshold
        for idx in candidates:
            cb = self.char_boxes[idx]
            cx = cb.rect.center().x()
            cy = cb.rect.center().y()
            dist_sq = (px - cx) ** 2 + (py - cy) ** 2
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                best_idx = cb.index

        return best_idx

    def get_selection_range(self, start_idx: int, end_idx: int) -> Tuple[str, List[Rect]]:
        """
        Retorna la cadena de texto seleccionada y los rectángulos visuales unidos para dibujar.
        """
        if start_idx is None or end_idx is None or not self.char_boxes:
            return "", []

        first = min(start_idx, end_idx)
        last = max(start_idx, end_idx)
        first = max(0, min(first, len(self.char_boxes) - 1))
        last = max(0, min(last, len(self.char_boxes) - 1))

        selected_chars = self.char_boxes[first:last + 1]
        text = "".join(cb.char for cb in selected_chars)

        # Agrupar rectángulos adyacentes para un renderizado visual continuo
        rects: List[Rect] = []
        for cb in selected_chars:
            if cb.char.strip():  # Omitir cajas vacías de saltos de línea para el resaltado visual
                rects.append(cb.rect)

        merged_rects = self._merge_rects(rects)
        return text, merged_rects

    def search_matches(self, query: str, match_case: bool = False) -> List[SearchMatch]:
        """
        Busca todas las apariciones de 'query' en la página actual y devuelve sus rectángulos.
        """
        if not query or not self.full_text or not self.char_boxes:
            return []

        haystack = self.full_text if match_case else self.full_text.lower()
        needle = query if match_case else query.lower()

        matches: List[SearchMatch] = []
        start = 0
        q_len = len(needle)

        while True:
            idx = haystack.find(needle, start)
            if idx == -1:
                break

            matched_chars = self.char_boxes[idx:idx + q_len]
            raw_rects = [cb.rect for cb in matched_chars if cb.char.strip()]
            merged = self._merge_rects(raw_rects)

            match_text = self.full_text[idx:idx + q_len]
            matches.append(SearchMatch(
                start_char_idx=idx,
                char_count=q_len,
                text=match_text,
                rects=merged
            ))

            start = idx + max(1, q_len)

        return matches

    @staticmethod
    def _merge_rects(rects: List[Rect], tol: float = 4.0) -> List[Rect]:
        """
        Fusiona rectángulos de caracteres adyacentes en la misma línea visual
        (soportando tanto texto horizontal como vertical de planos CAD).
        """
        if not rects:
            return []

        merged: List[Rect] = []
        current = rects[0]  # inmutable: no requiere copia

        for r in rects[1:]:
            # Caso 1: Texto horizontal (mismo nivel Y, continuo en X)
            same_line_h = abs(r.top() - current.top()) <= tol and abs(r.bottom() - current.bottom()) <= tol
            adjacent_x = abs(r.left() - current.right()) <= tol or abs(r.right() - current.left()) <= tol or current.intersects(r)

            # Caso 2: Texto vertical CAD (mismo nivel X, continuo en Y)
            same_line_v = abs(r.left() - current.left()) <= tol and abs(r.right() - current.right()) <= tol
            adjacent_y = abs(r.top() - current.bottom()) <= tol or abs(r.bottom() - current.top()) <= tol or current.intersects(r)

            if (same_line_h and adjacent_x) or (same_line_v and adjacent_y):
                current = current.united(r)
            else:
                merged.append(current)
                current = r

        merged.append(current)
        return merged
