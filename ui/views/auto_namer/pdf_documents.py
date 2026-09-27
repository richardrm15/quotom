"""
Caché de documentos PDFium abiertos (responsabilidad propia del auto-nombrador).

El diálogo abre planos para renderizarlos y para extraer su capa de texto. Mantener
esos documentos abiertos y cerrarlos correctamente es una responsabilidad con
suficiente entidad propia como para no vivir dentro del diálogo.

Todo el acceso va bajo ``PDFIUM_LOCK``: PDFium **no** soporta acceso concurrente.
"""

import os
from typing import Dict, Optional

import pypdfium2 as pdfium

from core.pdf_lock import PDFIUM_LOCK


class PdfDocumentCache:
    """
    Mantiene abiertos los documentos PDFium durante el ciclo de vida del diálogo.

    Reutilizar el documento evita reabrir el mismo archivo en cada página (varias
    páginas de una misma importación comparten plano) y permite cerrarlos todos
    de golpe al terminar.
    """

    def __init__(self) -> None:
        self._docs: Dict[str, pdfium.PdfDocument] = {}

    def get(self, pdf_path: str) -> Optional[pdfium.PdfDocument]:
        """
        Devuelve el documento de ``pdf_path``, abriéndolo la primera vez.

        Args:
            pdf_path: Ruta del PDF. El valor ``":blank:"`` es un pseudo-plano en
                blanco que no se abre; tampoco se abre una ruta inexistente.

        Returns:
            El documento abierto y cacheado, o ``None`` si no se pudo abrir.
            Un fallo de apertura **no** se cachea: se reintenta en la próxima llamada.
        """
        if pdf_path in self._docs:
            return self._docs[pdf_path]

        if pdf_path == ":blank:" or not os.path.exists(pdf_path):
            return None

        try:
            with PDFIUM_LOCK:
                self._docs[pdf_path] = pdfium.PdfDocument(pdf_path)
        except Exception:
            return None
        return self._docs[pdf_path]

    def close_all(self) -> None:
        """Cierra todos los documentos abiertos y vacía la caché."""
        with PDFIUM_LOCK:
            for doc in self._docs.values():
                try:
                    doc.close()
                except Exception:
                    pass
            self._docs.clear()

    def __len__(self) -> int:
        """Número de documentos abiertos (introspección y tests)."""
        return len(self._docs)
