"""
Módulo de Sincronización Global de PDFium (Global Thread-Safety Lock).

PDFium es una biblioteca C++ que mantiene estructuras globales de memoria y
análisis sintáctico. Para garantizar estabilidad absoluta y evitar errores
de tipo 'Data format error' o corrupciones de punteros en entornos multihilo,
todas las operaciones directas de apertura, renderizado y guardado con pypdfium2
dentro del mismo proceso deben sincronizarse mediante PDFIUM_LOCK.
"""

import threading

# Reentrant lock global para el proceso
PDFIUM_LOCK = threading.RLock()
