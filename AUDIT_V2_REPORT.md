# Informe y Plan de Auditoría — Quotom (documento único)

Documento **autoritativo** del proceso de auditoría y refactorización: informe de estado,
plan de trabajo por bloques y decisiones de alcance.

> **Ya no se crean documentos de plan separados** (`AUDIT_ACTION_PLAN.md` y
> `REFACTORING_PLAN.md` fueron absorbidos aquí para evitar que diverjan).

---

## 0. Cómo usar este documento

| Acción | Comando |
|---|---|
| Ver el estado actual (contadores) | `python3 tools/audit_rules.py --resumen` |
| Informe completo con archivo:línea | `python3 tools/audit_rules.py` |
| Ejecutar todos los tests | `./env/bin/python -m pytest tests/` |
| Un test como script | `./env/bin/python -m tests.core.test_coordinates` |
| Compilar todo | `find core ui common main.py tools -name '*.py' \| xargs python3 -m py_compile` |

**Criterio de aceptación de cualquier cambio:** los tests deben quedar en verde y el
contador del bloque en el que se trabaja debe **bajar**, nunca subir.

---

## 1. Resumen ejecutivo (estado actual)

| # | Regla | Inicial | Actual | Estado |
|---|---|---|---|---|
| 1 | 1/4 — Vistas desacopladas (`parent`/`window`) | 15 | **15** | ⚠️ |
| 2 | 2/8–13 — `QUndoCommand` canónico | 0 | **0** | ✅ |
| 3 | 3/10/15/20 — `core/` sin Qt | 3 | **0** | ✅ |
| 4 | 5/6 — `view.py` sin SQL ni database | 0 | **0** | ✅ |
| 5 | 7/14 — Vistas hermanas no se conocen | 0 | **0** | ✅ |
| 6 | 8 — Controllers sin acceso a BD | 4 | **0** | ✅ |
| 7 | 13/17 — Sin inspección dinámica | 130 | **126** | ❌ |
| 8 | 18 — Estilos centralizados | 72 | **0** | ✅ |
| 9 | 20 — Tests de `core` sin Qt | 0 | **0** | ✅ |
| 10 | 21 — Gráficos fuera del dominio | 2 | **0** | ✅ |
| 11 | Estructura objetivo | 14 | **0** | ✅ |
| 12 | Restos / deuda técnica | 0 | **0** | ✅ |
| — | Tests automáticos (soporte, no regla) | 0 | **117** | — |
| | **TOTAL** | **204** | **140** | |

**Tests: 117 en verde** · **Compilación: OK** · **Emojis en el código: 0**
Bloques cerrados: **Sprint 0**, **Q**, **FIX**, **P0.1**, **S**, **S6**, **H1**, **P2**, **FIX-T**, **P0.2**, **CONV**, **P0.3**, **A0**, **A1** (pendiente solo la migración de diálogos **DIAG**, en pausa por decisión del usuario)

> ℹ️ **Corrección de medición (auditor):** el chequeo de la Regla 8 no detectaba `self._db`
> (solo `.db`). Se endureció y el número real subió de 4 → **8**; tras migrar
> `ProjectController` y `AnnotationController` a los servicios, la regla queda en **0**
> y ningún controlador referencia ya la base de datos.


---

## 2. Cambios respecto a la auditoría v1

La nueva especificación es **más estricta** y añade requisitos no medidos antes:

| Nuevo requisito | Impacto |
|---|---|
| `core/services/`, `core/models.py`, `core/business_rules.py` | Nuevo gap estructural (6 archivos) |
| `tests/{core,commands,controllers}/` | Reorganización de 8 archivos de test |
| Prohibición global de `hasattr/getattr/setattr` (regla 17) | Nuevo contador: **130** |
| Prohibición explícita de `QGraphics*` en dominio (regla 21) | Nuevo contador: 2 |
| Controllers sin acceso a BD (regla 8) | Nuevo contador: 4 |
| Dirección `Services → Business Rules → Models` | Cambio de arquitectura interna de `core/` |

---

## 3. Detalle de hallazgos

### 3.1 Estructura objetivo — 14 desviaciones

**Faltantes (no existen):**

| Ruta | Requerido por |
|---|---|
| `core/services/` | Regla 9 (lógica de negocio en servicios) |
| `core/services/project_service.py` | Estructura §1 |
| `core/services/drawing_service.py` | Estructura §1 |
| `core/services/annotation_service.py` | Estructura §1 |
| `core/models.py` | Estructura §1 (dataclasses de dominio) |
| `core/business_rules.py` | Estructura §1 |
| `common/commands/global_commands.py` | Estructura §1 |
| `requirements.txt` | Estructura §1 (existe `requirements`, sin extensión) |
| `tests/core/`, `tests/commands/`, `tests/controllers/` | Estructura §1 + Regla 16 |
| `common/widgets/__init__.py`, `tests/__init__.py` | Paquetes incompletos |
| `ui/views/project_editor/view.py` | El canvas vive en `common/widgets/graphics_view.py` |

**Lo que SÍ cumple:** `core/`, `common/{commands,widgets}/`, `ui/{styles,icons,views}/`,
`ui/views/{main_window,project_editor}/`, `main.py`.

### 3.2 Regla 3/10/15/20 — `core/` sin Qt (3)

```
core/geometry_utils.py:5   from PySide6.QtGui import QFont, QFontMetricsF
core/ocr_engine.py:9       from PySide6.QtCore import QRectF
core/text_layer.py:8       from PySide6.QtCore import QRectF, QPointF
```
✅ **Cumple:** `core/` no usa `QWidget|QObject|Signal|QIcon|QGraphicsItem|QApplication`
ni importa capas UI.

### 3.3 Regla 1/4/7/14 — Vistas desacopladas (15 = 8 + 7)

**Acceso a la ventana contenedora (8):**
```
common/widgets/app_menu_bar.py:93    self.window().close()
common/widgets/graphics_view.py:793  mw = self.window()
common/widgets/graphics_view.py:805  mw = self.window()
common/widgets/graphics_view.py:902  mw = self.window()
common/widgets/graphics_view.py:1070 mw = self.window()
common/widgets/page_manager.py:1606  parent_win = self.parent()
common/widgets/window_resizer.py:183 win = self.window()
common/widgets/window_resizer.py:203 win = self.window()
```

**Acceso a estado privado del padre (7):**
```
common/widgets/graphics_view.py:794-795  hasattr(mw,"_undo_stack") / mw._undo_stack.undo()
common/widgets/graphics_view.py:806-807  hasattr(mw,"_undo_stack") / mw._undo_stack.redo()
common/widgets/graphics_view.py:903-904  mw._property_inspector.get_tool_defaults(...)
common/widgets/graphics_view.py:1071     mw._clipboard_annotations
```
✅ **Cumple:** 0 accesos a `scene().views()`; 0 vistas hermanas importándose.

### 3.4 Regla 8 — Controllers accediendo a la BD (4)

```
ui/views/main_window/project_controller.py:142  self._project_mgr.db
ui/views/main_window/project_controller.py:145  self._project_mgr.db.get_drawing(...)
ui/views/main_window/project_controller.py:178  self._project_mgr.db
ui/views/main_window/project_controller.py:181  self._project_mgr.db.get_drawing(...)
```
El controller de proyecto habla con `DatabaseManager` en vez de con un `DrawingService`.

### 3.5 Regla 13/17 — Inspección dinámica (130)

Clasificación por naturaleza:

| Categoría | Cantidad | Naturaleza |
|---|---|---|
| **A.** Estado propio (`getattr(self, "_x", def)`) | **89** | Reducible: inicializar en `__init__` (patrón ya aplicado en `annotation_item.py`) |
| **B.** Objeto UI externo (widget/item/viewer/`mw`) | **26** | **Violación real** — incluye los 7 de `graphics_view` + `page_manager` |
| **C.** Token/theme (`getattr(tok, ...)`) | 2 | Benigna (fallback defensivo) |
| **D.** Worker/DB interno | 2 | Revisar |
| **E.** Otros | 13 | Mixto |

Distribución por capa: `core/` **0** ✅ · `ui/views/` **22** · `common/widgets/` **108**.

### 3.6 Regla 18 — Estilos (36)

```
common/widgets/autonamer/main_window_auto_namer.py   14
common/widgets/page_manager.py                        9
common/widgets/project_sidebar.py                     5
common/widgets/markups_panel.py                       3
common/widgets/annotation_toolbar.py                  2
common/widgets/graphics_view.py                       2
common/widgets/find_bar.py                            1
```
(`property_inspector.py` → 0 ✅ tras el Sprint P0.1)
✅ `setProperty()` presente en 2 puntos (patrón de estado dinámico correcto).

### 3.7 Regla 21 — Gráficos en el dominio (2)

Ambos son **menciones textuales** en `core/text_layer.py` (docstring y comentario).
La violación real es la del punto 3.2 (`QRectF`/`QPointF` importados).

### 3.8 Regla 16 — Tests

```
FALTA tests/core/        FALTA tests/commands/        FALTA tests/controllers/
Actual: 8 archivos en la raíz de tests/ (20 tests, todos verdes)
```
✅ Los tests de `core` actuales **no** importan Qt (Regla 20 cumplida).

---

## 4. Brecha arquitectónica principal

El cambio conceptual más importante: **hoy `core/` es infraestructura, no dominio**.

```
ESTADO ACTUAL                          OBJETIVO (espec. v2)
─────────────────────────────          ─────────────────────────────
core/                                  core/
  database.py   (SQL directo)            database.py
  project.py    (ProjectManager          models.py          <-- NUEVO
                 = lógica + SQL +        business_rules.py  <-- NUEVO
                   acceso a ficheros)    services/          <-- NUEVO
  coordinates.py                           project_service.py
  geometry_utils.py  (usa Qt)              drawing_service.py
  color_utils.py                           annotation_service.py
  text_layer.py      (usa Qt)
  ocr_engine.py      (usa Qt)
  settings.py, pdf_*.py
                                         Services → Rules → Models
                                              ↓
                                           Database
```

**Los "modelos" actuales son diccionarios crudos** provenientes de `sqlite3.Row`
(p. ej. `drawing["abs_path"]`, `annot["style"]`). La UI depende del esquema de la BD.
La Regla 15 (objetos Qt fuera del dominio) **sí se cumple** — los `QGraphicsItem` viven
en `common/widgets/annotation_item.py`, no en `core/`.

---

## 5. Plan de trabajo por bloques (estado)

| # | Bloque | Cierra | Estado |
|---|---|---|---|
| **Q** | **Quick wins estructurales**: `requirements.txt`, `common/widgets/__init__.py`, `tests/` por capas, `global_commands.py` | Estructura 14 → **6** | ✅ **cerrado** |
| **FIX** | **Bug del undo al cambiar de documento** (D2): vaciar la pila, conservando la historia al recargar el mismo plano | D5.1 | ✅ **cerrado** |
| **P0.1** | Estilos de `property_inspector.py` + `ColorSwatchButton` | Regla 18: 72 → 36 | ✅ **cerrado** |
| **S** | **Capa de dominio**: `core/models.py`, `core/business_rules.py`, `core/services/*`; ambos controladores sin BD; `ProjectService` unifica el `ProjectServiceProtocol` de los comandos | Regla 8: 8 → **0** · Estructura: 6 → **0** | ✅ **cerrado** |
| **S6** | `MainWindowController` + `AnnotationController` + portapapeles migrados a los servicios (el orquestador ya no llama a la API del repositorio) | Punto ciego de la Regla 8 | ✅ **cerrado** |
| **P2** | **`core/` sin Qt**: `core/text_geometry.py` (`Rect`/`Point` + `Protocol`), fuentes a `ui/helpers/text_metrics.py`, adaptadores `ui/helpers/qt_geometry.py` | Regla 3: 3 → **0** | ✅ **cerrado** |
| **FIX-T** | **Doble aplicación del tema**: `_toggle_theme()` re-aplicaba el estilo global que `ThemeManager.toggle_theme()` ya había aplicado (2 *restyles* por clic) | Rendimiento y exposición a un segfault de Qt | ✅ **cerrado** |
| **P0.2** | Estilos (lote 1): `find_bar`, `annotation_toolbar`, `graphics_view`, `markups_panel`, `project_sidebar` → `theme.qss` | Regla 18: 36 → **23** (Regla 17: 129 → 126) | ✅ **cerrado** |
| **CONV** | **Convención sin emojis**: 9 pictogramas sustituidos por iconos de `ui/icons/`, nuevo icono `alert-triangle`, tokens `warning`, guardarraíl permanente | Deuda de presentación | ✅ **cerrado** |
| **DIAG** | **Fachada de diálogos** `ui/dialogs/`: mensajes, entradas y ficheros centralizados; `QFileDialog` dibujado por Qt (`DontUseNativeDialog`) para armonizar con el tema; QSS de diálogos; guardarraíl con trinquete | Desacoplamiento/estilo | ⏸️ **en pausa por decisión del usuario** (2/6 archivos) |
| **P0.3** | Estilos (resto): `page_manager` 9 + `autonamer` 13 → `theme.qss` | Regla 18: 22 → **0** | ✅ **cerrado** |
| **A0** | **Auto-nombrador**: red de seguridad (**+10 tests** con PDF generado por código) + eliminación de **84 líneas de código muerto** (el diálogo redefinía las funciones ya extraídas) | Prepara **H2**/desacoplamiento | ✅ **cerrado** |
| **A1** | **Auto-nombrador desacoplado**: `naming` (dominio puro), `pdf_documents` (caché PDFium), `widgets` (tarjeta/fila/banner) y traslado a **`ui/views/auto_namer/`** con `view.py` + `controller.py` | **Regla 19** (D5.5) · diálogo **1.126 → 739** líneas | ✅ **cerrado** |
| **P1** | Desacoplar vistas: señales `undo_requested`/`exit_requested`, `PageManagerOwner`, `graphics_view` sin `mw._*` | Regla 1/4: 15 → 0 | ⬜ |
| **P2** | `core/` sin Qt: fuentes a `ui/helpers/`, `TextRect` puro | Regla 3: 3 → 0, Regla 21: 2 → 0 | ⬜ |
| **P3** | Regla 17: 89 guardas de estado propio (mecánico) + 26 reales + 13 varios | Regla 17: 130 → 0 | ⬜ |
| **F4** | `page_manager` → `ui/views/page_manager/` con `QUndoStack` propio (D5.3) | Deuda estructural | ⬜ |
| **H1** | `.gitignore` (el repo no tenía ninguno ni commits: `env/` 695 MB + `.cache/` 862 MB entraban en un `git add -A`) | Riesgo de commit de ~1,5 GB | ✅ **cerrado** |
| **H2** | Resto de higiene: `PendingTasks` → `docs/`, `common/widgets/autonamer/` → `ui/views/auto_namer/` (D5.5, D5.6) | Regla 19 | ⏳ **mitad hecha**: el traslado del auto-nombrador lo cerró **A1**; falta `PendingTasks` → `docs/` |

**Orden recomendado y esfuerzo restante (~15-18 h):**

```
[SIGUIENTE] P0 (estilos, 36)  ▸  P1 (vistas, 15)
            ▸  H2 (higiene)  ▸  F4  ▸  P3 (Regla 17, 129)
```

**Por qué `P0` antes que `P1`:** es mecánico, sin riesgo de comportamiento y cierra un
contador completo (Regla 18: 36 → 0). `P1` mueve contratos entre vistas hermanas (riesgo
medio) y `P3` es la regla más discutible del spec: 129 marcas de `getattr`/`hasattr`
donde "arreglar" sin criterio rompe comportamiento.

**Deuda residual conocida tras S6:** `common/widgets/page_manager.py` todavía recibe el
`ProjectManager` (usa su API de alto nivel: sincronización de páginas y remapeo de marcas).
Se abordará con **F4**, que ya planea convertir `page_manager` en `ui/views/page_manager/`
con `QUndoStack` propio.

### Detalle de lo ya ejecutado

**Bloque Q**
| Ítem | Resultado |
|---|---|
| `requirements` → `requirements.txt` | Nadie lo referenciaba; renombrado |
| `common/widgets/__init__.py` | Creado |
| `tests/` | `{core,commands,controllers,ui}/` + `__init__.py`; `conftest.py` y `support.py` en la raíz |
| `common/commands/global_commands.py` | Placeholder documentado (`__all__ = []`) con el contrato de los futuros comandos multi-ventana |
| `project_editor/view.py` | **Excepción documentada** (ver §8 D3) |
| Auditor | Comprobaciones de comandos migradas a **AST** (elimina falsos positivos de docstrings) + registro de excepciones justificadas + regla nueva: *los comandos no capturan `QUndoStack`* |

**Bloque FIX**
| Ítem | Resultado |
|---|---|
| `_sync_undo_scope()` / `_clear_undo_scope()` en `MainWindowController` | Cableados en `_on_document_loaded()` y `close_current_document()` |
| `tests/controllers/test_undo_scope.py` | 4 tests: cambio de documento, recarga del mismo, cierre y 2 guardarraíles de cableado |

**Bloque S (capa de dominio)**
| Ítem | Resultado |
|---|---|
| `core/models.py` | `Project`, `Drawing`, `DrawingPage`, `Annotation` con `from_row()` / `to_dict()` compatible (incluye claves ISO 32000-1) · **10 tests** |
| `core/business_rules.py` | `build_pdf_filename()`, `resolve_collision()` (E/S por *callback*), `normalize_style_iso()` · **10 tests** |
| `ProjectManager` | `import_drawing()` y `rename_drawing()` ahora **usan** las reglas de dominio (≈30 líneas de negocio salieron de la persistencia) |
| `core/services/` | `ProjectService` (ciclo de vida + composición), `DrawingService` (custodia/metadatos), `AnnotationService` (CRUD + regla ISO al escribir) · **9 tests** |
| `ProjectController` | Ya **no** toca `_project_mgr.db`: usa `DrawingService`/`ProjectService` |
| `AnnotationController` | Ya **no** usa `self._db` (propiedad eliminada): todo el CRUD pasa por `AnnotationService` · **3 tests de integración** (crear/leer/actualizar/borrar/restaurar) |
| `ProjectService` ↔ comandos | `ProjectService` ahora implementa `rename_drawing`/`set_drawing_page_name`, así **satisface** `ProjectServiceProtocol`; los comandos de renombrado reciben el servicio y no el repositorio · **5 tests** |
| Red de seguridad | La prueba E2E detectó y evitó publicar un `NameError` introducido durante la extracción de las reglas; el hueco de cobertura del `AnnotationController` se cerró con un test de integración antes de dar S5 por cerrado |

**Bloque P2 (core sin Qt)**
| Ítem | Resultado |
|---|---|
| `core/text_geometry.py` | **Nuevo**. `Point`/`Rect` inmutables (inmutabilidad **forzada**, no solo declarada) con la misma API de lectura que `QPointF`/`QRectF`; `PointLike`/`RectLike` como `Protocol` de tipado estructural |
| 🎯 **Decisión de diseño** | Se replicó la API de lectura de Qt (`x()`, `top()`…) **en lugar** de "pitonizar" a propiedades (`.x`, `.top`). Motivo: hay ~50 puntos de consumo en el auto-nombrador (`main_window_auto_namer.py`, `text_extractor.py`, `worker.py`, `graphics_view.py`) que leen rectángulos y **no tienen tests**; un renombrado masivo allí habría dado fallos silenciosos (un método es *truthy*). Así `core/` sale de Qt con **0 cambios** en esos sitios |
| `core/text_layer.py` | `QRectF`/`QPointF` → `Rect`/`Point`. `get_char_index_at` acepta cualquier `PointLike`, así que la UI puede seguir pasando un `QPointF` real |
| `core/ocr_engine.py` | `Rect`; `norm_rect: RectLike` (acepta `QRectF` del lado Qt sin conversión) |
| `core/geometry_utils.py` | Queda **solo** `shift_geometry` (geometría pura). El auto-ajuste de texto se movió a `ui/helpers/text_metrics.py` porque necesita `QFont`/`QFontMetricsF` |
| `ui/helpers/qt_geometry.py` | **Nuevo**: `to_qrectf`/`to_qpointf`. Único punto de conversión dominio→Qt (4 usos en `graphics_view`) |
| 🐛 **Segfault encontrado y corregido** | La suite empezó a **abortar con SIGSEGV** en `ThemeManager.apply_theme_to_app` → `app.setStyleSheet()`. Diagnóstico: **no** era el código nuevo (el E2E pasaba aislado), sino *restyle* global repetido mientras el recolector liberaba widgets de tests anteriores → puntero colgante en Qt. Se añadió `tests/support.apply_theme_once()` (una sola aplicación por proceso) y `teardown_widgets()`; verificado con **3 ejecuciones consecutivas en verde** |
| Tests | **+11** en `tests/core/test_text_geometry.py` (puro, sin Qt): API, `contains`/`intersects`/`united`/`adjusted`, inmutabilidad, tipado estructural, fusión de rectángulos, serialización y búsqueda |

**Bloque P0.2 (estilos, lote 1)**
| Ítem | Resultado |
|---|---|
| Archivos migrados | `find_bar`, `annotation_toolbar`, `graphics_view`, `markups_panel`, `project_sidebar` → **0** `setStyleSheet` cada uno |
| Tests | **+2 guardarraíles nuevos**: «`theme.qss` se sustituye por completo» y «existen los tokens de estado» |
| 🎯 **Hallazgo clave** | `find_bar` **duplicaba** reglas que `theme.qss` **ya tenía** (desde P0.1). La hoja del widget ganaba por especificidad, así que la centralizada era letra muerta (radios y paddings distintos). Al eliminarla, manda `theme.qss`: es el objetivo declarado del sistema de diseño |
| Patrón aplicado | Estilo → `theme.qss` con `objectName` (`#planCanvas`, `#markupsPanel`, `#toolSeparator`, `#sidebarSectionTitle`…); `apply_theme()` queda reducido a **iconos** o a un *repolish*. El color por-instancia no se fuerza a QSS: va a `ThemeManager.apply_inline_editor_style()` (documentado como estilo **derivado de datos**) |
| ⚠️ Corrección necesaria al centralizar | `markups_panel` aplicaba `QHeaderView::section` **sin acotar**; en la hoja global habría afectado a **todas** las tablas de la app → se acotó a `QWidget#markupsPanel QHeaderView::section` |
| Tokens nuevos | `error` y `success` en `ThemeTokens` (dark `#E06C75`/`#98C379`, light `#C0392B`/`#2E7D32`) → sustituyen 3 `getattr` defensivos, reduciendo también la Regla 17 |
| Cambios visuales aceptados | (a) `find_bar` pasa a los valores de `theme.qss` (radio 8 vs 6, padding 0/8 vs 2/6). (b) `opacity: 0.7` del contador de marcas **no es una propiedad QSS válida** (Qt la ignora) → se sustituyó por `color: {text_secondary}`, que sí expresa la intención de atenuarlo |
| Trinquete | `tests/ui/test_style_rules.py`: 5 archivos movidos de `PENDING` a `MIGRATED` (presupuesto a 0, solo puede bajar) |

**Veredicto sobre `setColorScheme` (lo que pediste revisar)**
| Ítem | Resultado |
|---|---|
| ¿Es redundante con `setPalette`/`setStyleSheet`? | **No.** `setColorScheme` es la única vía para comunicar claro/oscuro al **nivel de plataforma**; QSS y la paleta solo afectan a los widgets que Qt dibuja |
| Evidencia | La app tiene **64** puntos de uso de diálogos nativos (`QFileDialog`, `QMessageBox`…) y `theme.qss` **no** los estiliza (imposible: usan el tema del SO). Los scrollbars **sí** los cubre QSS (8 reglas), pero los diálogos nativos no |
| Decisión | **Mantener.** Quitarlo haría que los diálogos nativos ignorasen el tema (destello blanco en modo oscuro) |
| Nota sobre su `hasattr` | Es legítimo, no deuda: `QStyleHints.setColorScheme` existe desde Qt 6.5; el `hasattr` protege versiones anteriores |
| Coste actual | **1 llamada por aplicación de tema** (antes 2, por el bug de FIX-T). El riesgo que sospechaba está acotado |

**Bloque P0.3 (estilos: Regla 18 a 0)**
| Ítem | Resultado |
|---|---|
| Archivos migrados | `page_manager` (**9 → 0**) y `autonamer/main_window_auto_namer` (**13 → 0**) |
| 🎯 **Duplicación eliminada** | Los dos archivos **repetían en su `_apply_theme`** reglas que `theme.qss` **ya tenía** (`pageGridScrollArea`, `primaryActionButton`, `btnBackGrid`, `pageManagerWindow`…). La hoja del widget ganaba por especificidad, así que la centralizada era letra muerta |
| Estado por propiedades dinámicas | Las tarjetas de página usaban QSS generado en `_update_appearance` según `_is_selected` → ahora `setProperty("state", "selected"/"normal")` + *repolish*, y las reglas `QFrame#pageCard[state="selected"]` / `QLabel#pageCardBadge[state="selected"]` viven en el QSS |
| ⚠️ **Corrección necesaria al centralizar** | Los dos archivos aplicaban `QHeaderView::section` y `QTableWidget` **sin acotar**. En la hoja global habrían re-estilizado **todas** las tablas de la app → se acotaron a `QDialog#pageManagerWindow` y `QDialog#autoNamerDialog` |
| Color **dato** (no tema) | El badge y el botón de captura por zona usan el color elegido por el usuario (`reg.color_hex`): no puede ir a QSS → nuevo `ThemeManager.apply_zone_color()`, centralizado y documentado (el resto del aspecto sí está en el QSS) |
| Propiedades QSS inválidas eliminadas | `opacity: 0.7` (marcas) y `text-transform: uppercase` (cabeceras del gestor): Qt **las ignora** en silencio. Sustituidas por `color: {text_secondary}` cuando expresaban la intención |
| Colores hardcodeados → tokens | `#888888` → `{text_secondary}`, `#3B82F6`/`#2563EB` → `{primary}`, ámbar `#D97706` → `{warning}`, y la barra de progreso del auto-nombrador deja de ser oscura fija (rompía el tema claro) |
| Trinquete | `PENDING` queda **vacío** (Sprint P0 cerrado) y se añade un guardarraíl que impide que **cualquier archivo nuevo** use `setStyleSheet` |
| Tests | **+1** (nuevo archivo con QSS inline) |

**Bloque DIAG (diálogos: un solo punto, estilo propio)**
| Ítem | Resultado |
|---|---|
| Inventario | **52 sitios**: 50 menciones de `QMessageBox` (5 archivos), 5 `QInputDialog`, 5 `QFileDialog`, 2 `QDialog` propios |
| 🎯 Hallazgo | Los `QMessageBox`/`QInputDialog` **ya eran de Qt** (nadie usaba nativos); lo que faltaba era **QSS para ellos**: `theme.qss` no tenía ni una regla de diálogo, así que salían con el aspecto por defecto de Qt |
| ⚠️ Tensión resuelta con el usuario | Un diálogo de ficheros **nativo** lo dibuja el SO e **ignora** QSS y paleta (solo admite un *hint* con `setColorScheme`, que decide el sistema). Se eligió **Qt-dibujado** (`DontUseNativeDialog`) para **garantizar** la armonía claro/oscuro, pasándole además la paleta del tema (`setPalette`) |
| Arquitectura | `ui/dialogs/`: `messages.py` (info/warn/error/about/**confirm** con botones personalizables), `prompts.py` (**ask_text**), `file_dialogs.py` (**open_files/save_file/select_directory**). API mínima que cubre el 100 % de los 52 sitios |
| Estilos | ~15 reglas nuevas en `theme.qss` para `QDialog`, `QMessageBox`, `QInputDialog`, `QFileDialog` (árbol, cabeceras, combos, campos, botones) → los diálogos usan el sistema de diseño |
| Guardarraíl | `tests/ui/test_dialog_rules.py` con **trinquete** `MIGRATED`/`PENDING`: impide que un archivo *nuevo* use PySide6 directo y que un pendiente empeore |
| Migrados | `ui/views/main_window/controller.py` (18 patrones → **0**) y `project_controller.py` (4 → **0**) |
| Pendientes | `project_sidebar` 9, `markups_panel` 5, `autonamer` 3, `page_manager` 24 |
| Verificación | Diálogos **renderizados a PNG** e inspeccionados: fondo del tema, botones estilizados y borde de foco en el campo de texto |
| Hallazgo extra | La app **no carga traductor de Qt**, así que los botones estándar salen en inglés (`Yes`/`No`/`Cancel`). La fachada `confirm()` ya los pone en español; para el resto lo correcto es instalar `qtbase_es.qm` |
| Tests | **+3** (guardarraíl de diálogos) |

**Bloque CONV (convención: sin emojis en la UI)**
| Ítem | Resultado |
|---|---|
| Motivo (con evidencia) | Un emoji **ausente en la fuente** de la etiqueta **reserva avance y no se dibuja**: el pictograma del título del panel metía **18 px invisibles** y desplazaba el texto **9 px** a la derecha. Además no se adaptan al tema |
| Limpieza | **9 pictogramas → 0** en `view.py`, `project_sidebar.py`, `page_manager.py` y `autonamer/main_window_auto_namer.py` |
| Sustituciones | Botón «Marcas» → icono **`list`**; proyectos recientes → **`folder-open`** (reactivos al tema vía `apply_bottom_bar_icons()` enganchado en `_apply_icons()`) |
| «⚠️» en diálogos | **Eran redundantes**: los tres `QMessageBox` ya pasan `Icon.Warning` nativo → se quitó el emoji del texto |
| Icono nuevo | **`alert-triangle`** añadido a `ui/icons/ui_elements.py` (triángulo con esquinas redondeadas + exclamación), registrado en `UI_ICONS` · verificado renderizando a PNG |
| Tintado de iconos | `ThemeManager.get_icon(name, size, color=None)`: parámetro opcional para teñir un icono (retrocompatible). El banner lo usa con el token `warning` |
| Token nuevo | `warning` (`#D97706` dark / `#B45309` light) junto a `error`/`success`; el estilo inline del banner pasó a `theme.qss` (Regla 18: 23 → **22**) |
| Guardarraíl | `test_sin_emojis_en_el_codigo` escanea `ui/`, `common/`, `core/`, `tools/` **y `tests/`**. Detectó un pictograma en el docstring del propio test → sustituido por `U+1F4CB` |
| Símbolos que se conservan | `✓ ✕ — → • … ─ ⇄ ←`: **no son emojis**, son símbolos tipográficos presentes en las fuentes. Se documenta el criterio en el test |

**Bloque FIX-T (cambio de tema)**
| Ítem | Resultado |
|---|---|
| 🔴 **Bug confirmado** | `MainWindowController._toggle_theme()` llamaba a `ThemeManager.toggle_theme()` (que **ya** aplica el tema) y **acto seguido** a `apply_theme_to_app(app, new_mode)` con el **mismo** modo → `setPalette` + `setStyleSheet` + `setColorScheme` **dos veces** por clic |
| Medición | Instrumentando `ThemeManager.apply_theme_to_app`: **1 toggle = 2 aplicaciones** globales. Tras el arreglo: **1** |
| Arreglo | Se eliminó la segunda aplicación; el refresco de los widgets que pintan por sí mismos se extrajo a `_refresh_widget_themes(mode)` |
| 🐛 **Segundo bug, del mismo sitio** | `_set_theme(mode)` llamaba a `_toggle_theme()`, que **alterna** en vez de fijar el modo pedido. Funcionaba solo por haber exactamente 2 temas; ahora aplica el modo solicitado (idempotente) y soporta N temas |
| Tests | **+2**: «un toggle aplica el estilo global exactamente una vez» y «`_set_theme` aplica el modo pedido» (además, +2 guardarraíles de QSS en P0.2) |
| ⚠️ **Límite del hallazgo (honestidad)** | **No** se logró reproducir un cuelgue en el flujo de producción: 3/3 ejecuciones de «ventana viva + 12 alternancias + churn ordenado de widgets» y 3/3 de «ventanas abandonadas + re-aplicar tema» terminaron en verde. El SIGSEGV de la suite sí era real, pero su disparador es el arnés (widgets liberados por el recolector **mientras Qt re-estiliza**), y se corrigió con `apply_theme_once`/`teardown_widgets`. Por tanto: la doble aplicación era **desperdicio y riesgo innecesario**, no un cuelgue demostrado en la app |

**Bloque S6 (raíz de composición única)**
| Ítem | Resultado |
|---|---|
| `MainWindowController` | **~18 llamadas** al repositorio sustituidas por `ProjectService`/`DrawingService` (`find`, `last_page`, `page_names`, `sync_page_count`, `update_last_page`, `resolve_path`, `is_active`, `project_info`…). El `ProjectManager` se conserva **solo** como repositorio compartido que se inyecta a `PageManagerWindow` (aún no migrado) |
| `ProjectController` | Recibe el `ProjectService` ya construido en vez del manager → **una sola instancia** de servicio en toda la ventana (antes había dos) |
| `AnnotationController` | Recibe el `ProjectService`; sus 3 últimos usos del manager (`is_active`, `find_drawing`, `get_drawing_page_names`) pasan a los servicios |
| 🔴 **Portapapeles (**`clipboard.py`**)** | **Accedía a `project_mgr.db` directo** (`.get_annotation` y `.create_annotation`). Migrado a `AnnotationService`. **El auditor no lo detectaba** porque solo inspeccionaba `*controller.py` |
| 🐞 **Bug encontrado y corregido** | En `_on_pages_saved_from_manager` introduje un `self.get_drawings()` **inexistente** en el orquestador; lo detecté grepeando antes de dar el bloque por cerrado y lo cubrí con un test de regresión |
| Nuevo guardarraíl | El auditor incluye `[7.2b] Acceso a la BD en la capa UI` (extra, fuera del spec) → hoy **0**, previene la clase de violación del portapapeles |
| Tests | **+4**: guardarraíl del orquestador, composición de servicios, regresión del sidebar y guardarraíl del portapapeles |

**Bloque H1 (higiene mínima)**
| Ítem | Resultado |
|---|---|
| `.gitignore` | **No existía**. El repo `quotom` (raíz propia) tiene rama `main` **sin ningún commit**, así que un `git add -A` habría intentado commitear `env/` (**695 MB**) + `.cache/drawings/` (**862 MB**) ≈ **1,5 GB** |
| Reglas añadidas | Entornos virtuales, cachés de Python/pytest, caché de render Tier 2 (`.cache/`, recalculable según `common/pdf/disk_cache.py`), datos por proyecto (`*.db`, `drawings/`) y ruido de SO/editor |
| Verificación | `git check-ignore -v` confirma cada regla; lo que entraría pasa de 13 entradas (~1,5 GB) a **99 archivos / 1,1 MB**: 93 `.py` + `requirements.txt`, `theme.qss`, `PendingTasks`, `AUDIT_V2_REPORT.md`, `pytest.ini` y el propio `.gitignore` |
| Sesgo detectado y evitado | `PendingTasks` **parece** un archivo temporal (y no tiene extensión) pero es la **especificación de la auditoría** → se conserva; solo faltaría renombrarlo (H2) |

**Bloque A0 (auto-nombrador: red de seguridad + código muerto)**
| Ítem | Resultado |
|---|---|
| 🎯 **Punto de partida** | `common/widgets/autonamer/main_window_auto_namer.py` = **1.126 líneas**, una sola clase con **35 métodos** (el mayor, `_init_ui`, de **194 líneas**) y **8 responsabilidades** mezcladas: UI, ciclo de vida de PDFs, extracción de texto, reglas del nombre (dominio puro), worker en segundo plano, plantilla cacheada, overlays de depuración y aplicación de resultados |
| 🔴 **Hallazgo: refactor a medias** | El archivo **ya importaba** `clean_boilerplate`, `extract_text_from_norm_rect_static` y `BOILERPLATE_PATTERNS` de `text_extractor.py` y las **aliasaba** en la clase… pero **más abajo las redefinía enteras** (los dos métodos *y* la lista de patrones, que quedaba por triplicado), anulando los alias. Las llamadas reales resolvían al módulo (regla LEGB), así que **el bloque duplicado era código muerto** |
| Acción | Eliminado el bloque (**−84 líneas**) → **1.126 → 1.042**. Riesgo **cero**, verificado: ninguna llamada usaba `self.`/`AutoNamerDialog.` para esos nombres |
| 🧪 **Infraestructura de tests nueva** | `tests/support.make_text_pdf()`: genera un PDF de una página **con capa de texto real** (669 bytes, sin dependencias) en coordenadas conocidas. Necesario porque el E2E actual depende de `~/Documents/BMSBidSuite/pdf-examples/*.pdf` y **se salta la prueba** si no existe: en otra máquina o en CI no correría nunca |
| Tests nuevos | **+10** en `tests/ui/test_text_extractor.py`: limpieza de cajetín, extracción acotada por región (título sí / código no, y viceversa), región vacía, página sin capa de texto, vía nativa de PDFium (`FPDFText_GetBoundedText`) y **guardarraíl anti-duplicación** (AST: la clase no puede volver a redefinir esas funciones) |
| Flujo TDD aplicado | El guardarraíl se escribió **antes** del arreglo → falló en **rojo** (demostrando la duplicación existente) → se borró el bloque muerto → **verde** |
| 📐 Comportamiento documentado | La extracción **descarta los espacios** del PDF y los **reinserta con una heurística** (`gap > 0.45 × ancho`), por eso un `A-101` puede devolverse como `A-1 01`. Los tests lo fijan con fragmentos distintivos en vez de exigir un espaciado que la función nunca prometió |
| Ubicación de los tests | `tests/ui/` y no `tests/core/`: el módulo importa Qt (`QRectF` en las anotaciones), y la Regla 20 exige que `tests/core/` no arranque Qt |
| Siguiente (desacoplamiento real) | Plan por riesgo **decreciente**, ya con red de seguridad: (2) `naming.py` con `assemble_name` + limpieza (dominio puro), (3) caché de documentos PDF fuera del diálogo, (4) widgets propios a `widgets.py` y partir `_init_ui`, (5) mover la feature a `ui/views/auto_namer/` (**H2**, D5.5) con `view`/`controller` |
| Verificación | `compileall` ✅ · suite completa **95 tests** ✅ · 0 emojis ✅ · el diálogo sigue construyéndose (smoke del banner) ✅ · auditor: **TOTAL 141** sin cambios (el código borrado no estaba señalado) |

**Bloque A1 (auto-nombrador desacoplado: 5 pasos)**
| Ítem | Resultado |
|---|---|
| 🎯 **Punto de partida** | Una sola clase de **1.126 líneas** y 35 métodos con **8 responsabilidades** mezcladas (UI, PDFs, extracción, nombres, worker, plantilla, overlays, aplicación) |
| 🔴 **Bug real encontrado y corregido** | `_get_doc` llamaba a `Path(pdf_path).exists()` **sin importar `Path`**. El `NameError` lo tragaba un `except` genérico, así que **la página de muestra quedaba en blanco** (pixmap de error 800×600) cada vez que las cachés estaban frías, y la comprobación de dimensiones se degradaba en silencio. Medido antes/después: `800×600` → **`1530×1980`** (página real renderizada) |
| 🔴 **Segundo bug (fuga)** | Los separadores se añadían al layout como **layouts anidados**; al reconstruir, un layout no tiene `widget()` y sus hijos **nunca se liberaban**: fuga en cada recuadro dibujado. Ahora son widgets (`SeparatorRow`) y se destruyen correctamente |
| 🔍 **El `except` mudo del render** | El fallo de la página en blanco sobrevivió porque un `except Exception` sin traza lo ocultaba. Ahora registra un aviso (`logger.warning`), verificado provocando el fallo: `Auto-nombrador: no se pudo renderizar la página 0: fallo simulado de renderizado` |
| 🧹 **Código muerto eliminado en `_apply_to_pages`** | Se construían `regions_args` y `tasks` (restos de una extracción en paralelo) que **nadie usaba** |
| **Paso 2 — `naming.py`** | Regla de composición del nombre como **dominio puro, sin Qt**. Estaba **triplicada** (diálogo, worker y aplicación final) con riesgo de divergir: ahora los tres usan `assemble_name`/`has_captured_text` |
| **Paso 3 — `pdf_documents.py`** | `PdfDocumentCache`: abrir/reutilizar/cerrar documentos PDFium sale del diálogo (y con él el `Path` del bug) |
| **Paso 4 — `widgets.py`** | `ZoneCard` (con señales propias), `SeparatorRow` y `AlertBanner`. `_init_ui` (**194 líneas**) se divide en `_build_frame` / `_build_canvas_panel` / `_build_tools_panel` (máximo 98 líneas) |
| **Paso 5 — traslado (D5.5)** | La feature pasa de `common/widgets/autonamer/` a **`ui/views/auto_namer/`** con `view.py` (**739 líneas**) + `controller.py` (**393**, 20 métodos) + `canvas`, `widgets`, `worker`, `text_extractor`, `naming`, `pdf_documents`. El auditor la reconoce como feature (`[1.3]`) |
| 🧭 **`commands.py` no existe, a propósito** | El auto-nombrador **no** crea comandos: devuelve el mapeo de nombres y es el gestor de páginas (con su propio `QUndoStack`) quien los aplica. Registrado como **excepción documentada** en el auditor |
| 🔓 **Acoplamientos rotos** | `self._canvas._active_capture_id` → `active_capture_id()`; `self._disk_cache._metadata` → `pages_metadata()`; el controlador expone `document_for()` en lugar de compartir el diccionario interno |
| Tests nuevos | **+22**: `test_naming.py` (**+9**, incluye una **prueba diferencial de +50.000 casos** contra la implementación anterior, que demuestra que unificar la regla no cambió el resultado), `test_pdf_documents.py` (**+6**, con la regresión del `Path`), `test_autonamer_widgets.py` (**+7**, pulsando los botones de verdad para fijar el cierre de las lambdas) |
| 📐 Hallazgos documentados por los tests | La extracción descarta los espacios del PDF y los reinserta con heurística (`A-101` → `A-1 01`); un separador de solo espacios se conserva en medio; si el dato coincide con el separador el nombre queda vacío pero la zona **sí** capturó texto (el worker conserva el nombre original) |
| Verificación | `compileall` ✅ · suite completa **117 tests** ✅ · 0 emojis ✅ · QSS intacto ✅ · auditor: **TOTAL 141 → 140**, Estructura **0** ✅ · smokes: UI completa, banner, extracción real (`PLANTA BAJA - NIVEL 2 - A-101`) y cierre de documentos (1 → 0) |


---

## 6. Riesgos del nuevo alcance

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Introducir `core/services/` puede duplicar `ProjectManager` | Alto | Refactor incremental: el servicio **envuelve** al manager, no lo reescribe |
| Migrar a `models.py` dataclasses obliga a tocar toda la UI | Alto | Introducir modelos de forma aditiva, consumidor por consumidor |
| La Regla 17 toca 108 líneas en widgets → riesgo de regresión | Medio | Los 89 de estado propio son mecánicos y están cubiertos por los 20 tests |
| La Regla 22 advierte contra capas innecesarias | Medio | `services/`+`models.py`+`business_rules.py` **están en la especificación** |

---

## 7. Conclusión

El proyecto está **sólido en los pilares de desacoplamiento**: los comandos son canónicos
(0 violaciones), las vistas no tocan SQL ni la BD, no hay acoplamiento entre vistas
hermanas, los tests de dominio no arrancan Qt y no hay deuda de migración.

Las **dos brechas grandes** son:

1. **Estructural/conceptual** — falta la capa de dominio formal (`models`, `business_rules`,
   `services`), por la que los controllers acceden directamente a `_project_mgr.db`.
2. **Volumen** — 36 estilos inline y 130 inspecciones dinámicas (89 de ellas mecánicas).

---

## 8. Decisiones de alcance (MVP) y excepciones justificadas

Estas decisiones **reducen deliberadamente el alcance** de la auditoría para no introducir
abstracciones antes de necesitarlas (Regla 22). Deben revisarse cuando llegue el modo
multi-ventana.

### D1. Un solo documento / una sola ventana activa

La aplicación muestra **un único documento activo a la vez**. El gestor de páginas es
**modal**, por lo que de facto ya se cumple.

Consecuencias:

* Se mantiene **una única `QUndoStack` global** en `MainWindowController`.
* **No** se implementa `QUndoGroup`.
* **No** se crean controladores por instancia ni cachés por ventana.

Extensión futura (documentada, no implementada): una pila por ventana
(`QUndoStack` en el controlador de cada ventana) + `QUndoGroup` para enrutar el Ctrl+Z
del menú a la ventana enfocada. Los comandos actuales **ya lo permiten** porque reciben
servicios y nunca la pila.

### D2. La pila de undo no debe cruzar documentos

Regla derivada de D1. **Implementada** (bloque FIX):

* `_sync_undo_scope(pdf_path)`: vacía la pila al **cambiar** de documento; recargar el
  **mismo** plano conserva la historia. Cableado en `_on_document_loaded()`.
* `_clear_undo_scope()`: vacía la pila al **cerrar** el documento. Cableado en
  `close_current_document()` (al que también llega `_on_project_closed()`).
* Cubierto por `tests/controllers/test_undo_scope.py` (4 tests, incluidos 2 guardarraíles
  que fallan si alguien quita las llamadas).

Bug corregido: antes, abrir el plano A → crear una anotación → cambiar a B → Ctrl+Z en B
aplicaba un cambio **invisible** sobre una anotación de A (modificaba la BD sin feedback).

### D3. `ui/views/project_editor/view.py` — excepción justificada (NO se crea)

`PlanGraphicsView` es usado por **dos features**:

```
ui/views/main_window/view.py:81      → visor principal
common/widgets/page_manager.py:966   → previsualización del gestor de páginas
```

Por la **Regla 19** (`common/` = componentes realmente compartidos) su ubicación correcta
es `common/widgets/graphics_view.py`. Crear `project_editor/view.py` haría que otra feature
dependiera de las internals de `project_editor`.

**Excepción aceptada**: `ui/views/project_editor/` no tendrá `view.py`; su "vista" es la
composición de widgets compartidos + el canvas de `common/widgets/`.

> Nota: importar una clase **no** viola la Regla 14 (esa regla prohíbe la comunicación en
> tiempo de ejecución entre instancias de vistas hermanas).

### D4. `common/commands/global_commands.py` — placeholder documentado

Se crea como contrato documentado con `__all__ = []`, porque hoy **no existe ningún comando
compartido entre ventanas**:

* `RenameDrawingCommand` / `RenamePageCommand` → solo `main_window`.
* `Create/Update/DeleteAnnotationCommand` → solo `project_editor`.

Alojará comandos multi-ventana cuando llegue D1-extensión. El auditor lo incluye ya en las
comprobaciones de la Regla 2.

### D5. Hallazgos nuevos detectados durante Q (fuera del alcance original)

| # | Hallazgo | Impacto | Bloque |
|---|---|---|---|
| D5.1 | La pila de undo **no se vacía** al cambiar de documento (ver D2) | 🔴 Bug: cambios invisibles en otro plano | ✅ **corregido** (bloque FIX) |
| D5.2 | Regla nueva del auditor: *ningún comando debe capturar una `QUndoStack`* | ✅ Ya se cumple; garantiza el multi-ventana futuro sin tocar comandos | ✅ Hecho |
| D5.3 | `page_manager.py` usa undo casero en vez de `QUndoStack` | Deuda; aceptable mientras haya una sola ventana | Bloque **F4** |
| D5.4 | `common/pdf/` (6 módulos) no está en el spec (solo describe `widgets/` y `commands/`) | Excepción de estructura aceptada: es soporte compartido | Documentado |
| D5.5 | `common/widgets/autonamer/` (5 módulos, ~1.700 líneas) es una **feature**, no un widget | Por Regla 19 debería ir a `ui/views/auto_namer/` | Bloque **H** |
| D5.6 | `PendingTasks` (prompt original) en la raíz | Higiene | Bloque **H** |
### D6. Diálogos emergentes: los dibuja Qt, incluidos los de ficheros (decisión del usuario)

**Política adoptada**: todos los emergentes son de Qt para que hereden ``theme.qss`` y la
paleta del tema. En particular, los diálogos de **abrir/guardar** usan
``QFileDialog.Option.DontUseNativeDialog``.

**Motivo**: un diálogo **nativo** lo dibuja el sistema operativo e **ignora por completo**
nuestro QSS y nuestra paleta — solo admite un *hint* mediante
``QStyleHints.setColorScheme()``, y quien decide es el SO. Con la aplicación en oscuro y
el escritorio en claro aparecería **blanco**. Se prioriza la **armonía visual** sobre la
integración con el SO; se conservan los lugares estándar (Inicio, Escritorio, Documentos,
última carpeta).

**Punto único**: ``ui/dialogs/`` (ver bloque DIAG).
**Guardarraíl**: ``tests/ui/test_dialog_rules.py`` (trinquete ``MIGRATED``/``PENDING``).

### D7. Internacionalización — **PENDIENTE, la abordará el usuario**

Hoy **no se carga ningún traductor de Qt**, así que los botones estándar de los diálogos
salen en inglés (``OK`` / ``Cancel`` / ``Yes`` / ``No``). La fachada ``confirm()`` ya fija
textos en español, pero el resto requiere instalar el traductor en ``main.py``:

```python
translator = QTranslator()
translator.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
app.installTranslator(translator)
```

**Punto de enganche ya preparado**: ``ui/dialogs/`` es el único lugar donde se construyen
diálogos, por lo que centralizar ahí los textos es directo. Lo que falta no es solo
traducir los botones de Qt, sino la capa de traducción de los textos de la aplicación.



---

## 9. Estrategia de ejecución y Definition of Done

* **Un bloque = un cambio cerrado y verificable.** Se cierra cuando todo esto está en verde.
* **Rama por bloque** (`refactor/s-dominio`, `refactor/p0-estilos`, …); merge a `main` solo en verde.
* **El auditor es el juez:** el contador del bloque debe **bajar** y ningún otro subir.
* **Regla de oro:** ningún bloque cambia comportamiento funcional; solo estructura, contratos,
  ubicación de estilos y corrección de bugs explícitamente detectados.

### Definition of Done (por bloque)

- [ ] `py_compile` de `core ui common main.py tools` sin errores.
- [ ] `tools/audit_rules.py`: el contador objetivo baja y no aparecen violaciones nuevas.
- [ ] `./env/bin/python -m pytest tests/` → **todo en verde**.
- [ ] Si se tocó UI: verificación manual en pantalla del área afectada.
- [ ] Este documento actualizado (tabla §1 y estado de §5).

---

## 10. Histórico de progreso

| Momento | TOTAL | Regla 18 | Estructura | Tests |
|---|---|---|---|---|
| Auditoría v1 (spec de 4 reglas) | 95 | 72 | 3 | 0 |
| Guardarraíles (Sprint 0) | 95 | 72 | 3 | 17 |
| Auditoría v2 (spec de 22 reglas) | 204 | 72 | 14 | 20 |
| Tras **P0.1** (estilos del inspector) | 197 | 36 | 8 | 20 |
| Tras **Q** (estructura + auditor AST) | 196 | 36 | **6** | 20 |
| Tras **FIX** (alcance del undo) | 196 | 36 | 6 | 24 |
| Tras **S** (capa de dominio) | **183** | 36 | **0** | **61** |
| Tras **H1** (`.gitignore`) | **183** | 36 | **0** | **61** |
| Tras **S6** (raíz de composición única) | **183** | 36 | **0** | **65** |
| Tras **P2** (`core/` sin Qt) | **180** | 36 | **0** | **76** |
| Tras **FIX-T** (tema una sola vez) | **180** | 36 | **0** | **78** |
| Tras **P0.2** (estilos lote 1) | **164** | **23** | **0** | **78** |
| Tras **CONV** (sin emojis + icono `alert-triangle`) | **163** | **22** | **0** | **81** |
| Tras **P0.3** (estilos a 0) | **141** | **0** | **0** | **85** |
| Tras **A0** (red de seguridad del auto-nombrador) | **141** | **0** | **0** | **95** |
| Tras **A1** (auto-nombrador desacoplado) | **140** | **0** | **0** | **117** |

> Los totales de v1 y v2 no son comparables: v2 mide reglas nuevas (17, 8, 21, estructura
> ampliada) que v1 no contaba.

