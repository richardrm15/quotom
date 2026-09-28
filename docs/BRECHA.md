# Brecha spec ↔ código — documento vivo

Qué es: la **distancia medida** entre lo que exige
[`ESPECIFICACION_ARQUITECTURA.md`](ESPECIFICACION_ARQUITECTURA.md) y lo que hace el
código, más el **orden de trabajo** (coste/beneficio) y el plan por bloques.

Cómo se mantiene: los números salen del auditor, no de la memoria.

```bash
python3 tools/audit_rules.py --resumen                 # contadores
python3 tools/audit_rules.py --json                    # informe completo en JSON
python3 tools/audit_rules.py --baseline tools/audit_baseline.json   # ¿hemos empeorado?
python3 tools/audit_rules.py --guardar tools/audit_baseline.json    # nueva línea base
```

Reglas de este documento:

* Un bloque **solo se cierra** cuando su contador baja y la suite sigue verde.
* Lo que no se mide se declara (§5): no se disfraza de cero.
* Una excepción sin motivo escrito no existe (spec §22.3).

---

## 1. Estado medido (línea base `tools/audit_baseline.json`)

| Regla | Qué exige | Tipo | Hallazgos | Dónde |
|---|---|---|---|---|
| R1 | `core/` no importa PySide6 | auto | **0** | — |
| R2 | `view.py` sin SQL | auto | **0** | — |
| R3 | `view.py` sin `database.py` | auto | **0** | — |
| R4 | vistas sin `parent()`/`window()` | auto | **9** | `graphics_view` 4 · `window_resizer` 2 · `app_menu_bar` 2 · `page_manager` 1 |
| R5 | las vistas emiten señales | manual | — | checklist §5.2 |
| R6 | controllers llaman métodos públicos | auto | **0** | llamadas a métodos privados de colaboradores |
| **R7** | vistas hermanas no se conocen | auto | **2** | `main_window/controller.py:27,28` |
| **R8** | controllers solo orquestan | auto | **12** | 0 de BD · 12 de presupuesto de tamaño (§2.4) |
| R9 | dominio en `core/services` | informativa | — | 4 servicios, ninguno importa Qt |
| R10 | `QUndoCommand` con dependencias explícitas | auto | **0** | — |
| R11 | `redo()` hace la operación | auto | **0** | — |
| R12 | sin `_applied_once` | auto | **0** | — |
| **R13** | sin `hasattr`/`getattr` para descubrir objetos | auto | **32** | §2.1 y §2.2 |
| R14 | commands sin widgets | auto | **0** | — |
| R15 | `core` sin `Signal` | auto | **0** | — |
| R16 | estilos en `theme.qss` | auto | **0** | — |
| R17 | sin `setStyleSheet` disperso | auto | **0** | — |
| R18 | iconos con `get_icon()` | informativa | — | 104 usos · 0 iconos a mano |
| R19 | `common/` solo lo compartido | informativa | — | sin subcarpetas sospechosas |
| R20 | el dominio se prueba sin Qt | auto | **0** | — |
| R21 | sin gráficos de Qt en el dominio | auto | **0** | — |
| R22 | sin capas nuevas sin necesidad | manual | — | checklist §5.2 |

**TOTAL medible: 48**: R4 **9** · R7 **2** · R8 **12** · R13 **25**.
Suite: **144 tests** (117 de la aplicación + 27 del auditor).

> ℹ️ **Historia del número** (para que nadie lea una subida como empeoramiento):
> el auditor nuevo midió **47**; al corregir dos mediciones (D1: el tamaño se mide en
> todas las capas; D4: R6 pasó a automática) subió a **55** — era deuda que existía sin
> medirse. Después, **B0** quitó 7 guardas muertas y bajó a **48**.


## 2. La brecha, por causa raíz

### 2.1 Un widget mirando dentro de su dueño — R4 9 + R13 9

```
common/widgets/graphics_view.py:793   mw = self.window()
common/widgets/graphics_view.py:794   if hasattr(mw, "_undo_stack") and mw._undo_stack.canUndo():
common/widgets/page_manager.py:1582   parent_win = self.parent()
common/widgets/page_manager.py:1584   if hasattr(parent_win, "pause_file_watcher"):
common/widgets/window_resizer.py:183  win = self.window()
common/widgets/app_menu_bar.py:93     self.window().close()
```

Un widget necesita algo de quien lo contiene y lo busca **en tiempo de ejecución**:
sondea si existe el método, si existe el atributo, y actúa. Es exactamente lo que el
spec prohíbe (R4 y R13), y además es frágil: si el atributo cambia de nombre, el
`hasattr` no falla, simplemente deja de hacer su trabajo **en silencio**.

**Arreglo**: interfaz explícita (`Protocol`) inyectada en el constructor, y señales
para lo ascendente (*Methods Down, Signals Up*).

### 2.2 Duck typing sobre colaboradores — R13 16

```
ui/views/main_window/controller.py:685   if hasattr(widget, "apply_theme"):
ui/views/project_editor/annotation_controller.py:383   if item and hasattr(item, "annot_id"):
ui/views/project_editor/clipboard.py:36   sel = viewer.selected_annotations() if hasattr(viewer, ...) else []
ui/views/main_window/project_controller.py:124   ... and hasattr(file_paths, "winId")
```

Se pregunta al objeto **qué es** en lugar de saberlo. Se arregla con tipos explícitos
(`isinstance`), un `Protocol` para lo que se repite (`apply_theme` en los widgets que
se repintan al cambiar el tema) y **API explícitas** en lugar de parámetros que a veces
son una lista de rutas y a veces un widget (`file_paths` con `winId`).

Concentración (cifras **tras B0**): `main_window/controller.py` **7** ·
`annotation_controller` **4** · `clipboard` **3** · `project_controller` **2**.

### 2.3 Una feature compone a otra — R7 2

```
ui/views/main_window/controller.py:27  from ui.views.project_editor.document_controller import DocumentController
ui/views/main_window/controller.py:28  from ui.views.project_editor.annotation_controller import AnnotationController
ui/views/main_window/controller.py:55  self._doc_ctrl = DocumentController(parent=self)
```

El controlador de la ventana principal **crea** los controladores del editor. La
coordinación entre features debe pasar por el punto de composición de la aplicación
(`main.py`), no por una vista que conoce a su hermana.

### 2.4 Módulos por encima del presupuesto de tamaño — R8 12

El presupuesto (umbral 400 líneas) se mide sobre **todas** las capas desde la decisión
D1. Estos son los 12 módulos y su **revisión D2** (¿tiene sentido reducirlos?), hecha
mirando su estructura interna:

| Módulo | Líneas | Estructura | Revisión D2 |
|---|---|---|---|
| `common/widgets/property_inspector.py` | **2130** | `PropertyInspector` **1957** + `FlowLayout` | ❌ **Dividir**: una clase de 1957 líneas mezcla paneles, estilo y edición |
| `common/widgets/page_manager.py` | **1803** | `PageManagerWindow` **1315** + 3 clases | ❌ **Dividir** (bloque **B3**) |
| `common/widgets/graphics_view.py` | **1160** | `PlanGraphicsView` **1079** + 2 | ❌ **Dividir** (bloque **B4**) |
| `core/database.py` | 854 | `DatabaseManager` **725** | ❌ **Dividir**: el spec §7 ya prevé repositorios por entidad si crece |
| `common/widgets/markups_panel.py` | 848 | `MarkupsPanel` 392 + modelo 144 + proxy 114 + delegate 47 | ⚠️ **Parcial**: ya está descompuesto; extraer del panel lo que no es presentación |
| `ui/views/auto_namer/view.py` | 752 | `AutoNamerDialog` **690** | ⚠️ **Parcial**: panel de herramientas y tabla son candidatos a widgets propios |
| `ui/views/main_window/controller.py` | 739 | `MainWindowController` **707** | ❌ **Dividir**: también concentra 9 hallazgos de R13 (§2.2) |
| `common/widgets/annotation_item.py` | 712 | `AnnotationGraphicsItem` **622** | ❌ **Dividir**: pintura, edición, serialización y señales en una clase |
| `ui/views/project_editor/annotation_controller.py` | 607 | `AnnotationController` **574** | ❌ **Dividir**: la inspección/estilos pueden salir a su propio módulo |
| `common/styles/style_manager.py` | 520 | `ThemeManager` 170 + 4 componentes | ✅ **Aceptar**: 5 componentes, ninguno grande; denso pero **cohesivo** |
| `common/widgets/project_sidebar.py` | 440 | `ProjectSidebar` 408 | ✅ **Aceptar**: 40 líneas sobre el umbral y una sola responsabilidad |
| `common/pdf/disk_cache.py` | 434 | `DiskPageCache` 412 | ✅ **Aceptar**: caché con una responsabilidad; apenas pasa el umbral |

**Conclusión de la revisión**: **7 dividir** · **2 parciales** · **3 aceptar**. El patrón
es claro: 8 de los 12 tienen **una clase de más de 400 líneas** ("clase-Dios"), y esos son
los que hay que dividir; los 3 aceptados son módulos con varios componentes pequeños.
Por eso el presupuesto no persigue el 0 (decisión D2).

---

### 2.5 Acoplamiento y código muerto (no son reglas, son hechos medidos)

```
ui.views.main_window   -> ui.views.project_editor   ❌ R7 (§2.3)
common.widgets         -> ui.views.auto_namer       ❌ un componente compartido conoce una feature
common.widgets         -> core.project              ⚠️ widget compartido atado al repositorio
common.commands        -> (eliminado en D3)          ✅ resuelto
```

* `common/widgets/page_manager.py:1222` hace `from ui.views.auto_namer import AutoNamerDialog`:
  un componente **compartido** que conoce una **feature**. Es el mismo archivo que
  recibe el `ProjectManager` y el segundo más grande del proyecto: **no es un widget
  compartido, es una feature viviendo en `common/`**.
* ~~`common/commands/global_commands.py`~~: **eliminado por decisión D3**. Nadie lo
  importaba y la aplicación tiene una sola ventana, así que no hay comandos
  compartidos. El spec se corrigió en consecuencia (árbol §1 y §13).

---

## 3. Orden por coste/beneficio

Criterio: primero lo que **cierra reglas completas con poco riesgo**, después lo que
solo baja contadores, y al final lo que mejora la estructura sin tocar contadores.
"Cierra" indica el contador que baja; "no cierra" indica mejora estructural.

| # | Bloque | Cierra | Ficheros | Coste | Riesgo |
|---|---|---|---|---|---|
| ✅ **B0** | Guardas de capacidad redundantes *(hecho)* | R13 −7 | 4 | — | — |
| ✅ **P0** | Romper el ciclo `common ↔ ui` *(hecho)* | ciclos de capas | 3 + **77 refs** | medio | bajo-medio |
| **P1** | Caché única + `DocumentController` recibe sus motores | duplicación **4 → 1** | 4 | medio | medio |
| **P2** | `main.py` raíz de composición (+ repositorio obligatorio, ayudante de tests) | N1 · N2 · N6 · **R7** | `main.py` + 2 + **11 tests** | medio | medio |
| **P3** | Gestor de páginas → pantalla con controller | R4 −1 · R13 −4 · inversión `common→feature` · **bug del vigía** | 1 → 4 archivos | **alto** | alto |
| **P4** | Canvas y widgets de ventana | **R4 → 0** · R13 −5 | 3 | alto | **alto** |
| **P5** | R13 en controllers: tipos explícitos | R13 −16 | 4 | medio | medio |
| **P6** | Cableado por pantalla + paneles suscritos | el hub deja de crecer | varios | medio-alto | medio |
| **P7** | Partir las clases-Dios | presupuesto R8 | 6+ | alto | medio |
| **P8** | R7 alineado con el spec + docstrings de carpeta + mapa de cableado | precisión y trazabilidad | `tools/` + docs | bajo | bajo |

**El orden sale de las dependencias, no del gusto**:

* **P0 antes que nada**: mientras `common/` importe de `ui/`, cualquier movimiento de piezas
  arrastra el ciclo.
* **P1 antes que P3**: el gestor de páginas es tan complejo, en parte, **porque tiene cachés
  propias**; se simplifica antes de tocarlo.
* **P2 antes que P3 y P4**: al mover la composición a `main.py`, los controllers **reciben**
  lo que necesitan y **R7 se cierra solo** (el cableado deja de vivir dentro de la feature),
  sin necesidad de decidir la lectura de la regla.
* **P3 y P4 son los dos bloques caros** (1800 y 1160 líneas, el corazón de la app): van
  separados, cada uno con la suite verde.
* **P6 al final de los movimientos**: se cablea por pantalla cuando las piezas ya están en su
  sitio; hacerlo antes obliga a cablear dos veces.
* **P7 es independiente**: se puede intercalar cuando convenga.

**Resumen**: de los 9 bloques, **7 son de coste bajo o medio**; el trabajo pesado está en
**P3 y P4**, que es donde se concentran los hallazgos de R4/R13 y los dos mayores
acoplamientos.

---

## 4. Plan por bloques

### ✅ B0 — Guardas de capacidad redundantes *(hecho)* · R13 32 → 25

* **Qué**: `style_manager.py:446` (`hasattr(hints, "setColorScheme")`) ·
  `title_bar.py:173,186` y `window_resizer.py:135,186` (`hasattr(handle, "startSystemMove"|"startSystemResize")`) ·
  `main_window/controller.py:449,456` (`hasattr(focus, "copy"|"paste")`, redundante con el `isinstance` de al lado).
* **Por qué es seguro**: `requirements.txt` fija `PySide6>=6.6.0`; `setColorScheme`
  existe desde Qt 6.5 y `startSystemMove`/`startSystemResize` desde Qt 5.15. Comprobado
  ejecutándolo en el entorno.
* **Se cierra cuando**: R13 baja a 25, la app arranca y se cambia de tema sin error.
* **No se toca**: el resto de R13.

### ✅ P0 — Romper el ciclo `common ↔ ui` *(hecho)*

* **Qué se hizo**: `ui/styles/`, `ui/icons/` y `ui/helpers/` se movieron a `common/styles/`,
  `common/icons/` y `common/helpers/`, y se reescribieron **77 referencias en 35 ficheros**
  (imports, docstrings, tests, docs y el propio `theme.qss`).
* **Resultado**: `common/` **ya no importa el soporte de UI** (0 sitios). Queda **un solo** import
  de `common/` hacia `ui/`: el de una **feature** en `page_manager.py:1222`, que es justo lo que
  quita **P3**.
* **Por qué iba primero**: había **15 dependencias** de `common/` hacia `ui/` (13 de
  `ui.styles.ThemeManager`, 1 de `ui.helpers` y 1 de la feature) formando un **ciclo** con las 7
  de `ui/` hacia `common/`. Sin romperlo, mover cualquier pieza arrastraba la dependencia.
* **Verificado**: contadores **sin cambios** (R16/R17 siguen en **0** con la excepción del auditor
  ya apuntando a `common/styles/style_manager.py`) · línea base `exit 0` · `compileall` OK ·
  **cero** referencias viejas.
* **De regalo**: el `theme.qss` viaja con `style_manager` porque localiza la plantilla con
  `Path(__file__).parent`, así que el tema se carga igual sin tocar una línea.

### P1 — Una sola caché · duplicación 4 → 1

* **Qué**: el punto de composición crea **una** `SlidingPageCache` (radio 7 = 15 páginas) y **una**
  `DiskPageCache`, y se las entrega al `DocumentController` y al gestor de páginas. El gestor deja
  de crear la suya. Contrato completo en el spec §23.4.1.
* **Hallazgo que resuelve**: la misma caché construida en 4 sitios con configuraciones distintas, y
  el gestor **copiando** entradas de la compartida a la suya.
* **Se cierra cuando**: `SlidingPageCache(` y `DiskPageCache(` aparecen **una sola vez** en el
  código de la aplicación, y el visor y el gestor comparten ambas.

### P2 — `main.py` como raíz de composición · **cierra R7** y las normas N1/N2/N6

* **Qué**: se mudan a `main.py` la construcción del repositorio, los servicios, la pila de undo y
  la caché; `MainWindowController` recibe sus colaboradores. Además: `ProjectService` **exige** el
  repositorio (no `manager or ProjectManager()`), y se añade un ayudante `build_app()` en
  `tests/support.py` para no repetir la composición en cada prueba.
* **Efecto secundario valioso**: **R7 se cierra solo** — el cableado entre features sale de
  `ui/views/main_window/`, así que deja de importar si R7 se lee como «vistas» o como «features».
* **Coste real medido**: ~11 sitios de test (`ProjectService()` ×5, `MainWindowController(view=…)` ×5,
  `ProjectManager()` ×1).
* **Se cierra cuando**: la app arranca, `main.py` es el único que construye motores compartidos,
  los tests usan el ayudante y R7 = 0.

### P3 — Gestor de páginas → pantalla con controller · R4 −1 · R13 −4 · dos bugs

* **Qué**: `ui/views/page_manager/{view,controller,workers,page_card}.py`. Recibe el **servicio**
  (hoy recibe el repositorio), usa la **caché compartida**, abre el auto-nombrador desde su
  controller, y sus hilos y su vigía tienen dueño.
* **Dos bugs que se corrigen aquí**:
  1. **Deshacer**: hoy hay un historial casero con listas y fotos de estado. Pasa a `QUndoCommand`
     en la **pila propia del diálogo** (decisión A), con la regla de que los comandos tocan la
     lista en memoria y el PDF **solo** se reescribe al guardar.
  2. **Vigía muerto**: `hasattr(parent_win, "pause_file_watcher")` nunca se cumple (el padre es la
     vista), así que al guardar **no** se pausa el vigía, ni se para el indexador, ni se cierra el
     handle del PDF. Pasa a **señales**, que no fallan en silencio.
* **No se toca**: la semántica del guardado (irreversible y advertido) ni el auto-nombrador.
* **Se cierra cuando**: R4/R13 bajan, `common/` ya no importa `ui.views.auto_namer`, el guardado
  pausa el vigía (verificado en ejecución) y el deshacer del diálogo funciona con comandos.

### P4 — Canvas y widgets de ventana · **R4 9 → 0** · R13 −5

* **Qué (canvas)**: el lienzo recibe en el constructor lo que hoy sondea en tiempo de ejecución
  (`self.window()`, `hasattr(mw, "_undo_stack")`, `mw._property_inspector`,
  `mw._clipboard_annotations`).
* **Qué (widgets de ventana)**, los 4 hallazgos de R4 que ningún otro bloque cubría:
  1. `window_resizer.py:183,203` → **la ventana ya está inyectada** en `self._window`: basta con
     usar `self._window` en lugar de `self.window()` (cambio de una línea por sitio).
  2. `app_menu_bar.py:93` (`self.window().close()`) → lo correcto **no** es inyectar la ventana,
     sino **emitir una señal** (`exit_requested`) y que el controller cierre la ventana: eso es
     justo lo que piden R5 y N3 (*la vista emite, el controller actúa*).
* **Se cierra cuando**: `graphics_view.py` no contiene `self.window()` ni `hasattr(mw, …)`, los
  otros dos archivos tampoco contienen `self.window()`, y **R4 = 0** con R13 en 20.

### P5 — R13 en controllers: tipos explícitos · R13 −16

Por archivo (cifras **tras B0**): `main_window/controller` **7** · `annotation_controller` **4** ·
`clipboard` **3** · `project_controller` **2**. El de la ventana necesita un `Protocol` para
«widget que se repinta» y `isinstance` donde el tipo ya se conoce.

Tras P3 (−4), P4 (−5) y P5 (−16), **R13 = 0**.

### P6 — Cableado por pantalla y paneles suscritos · el hub deja de crecer

* **Qué**: partir `_connect_signals` (109 conexiones) por áreas; el cableado de los paneles del
  editor pasa a su controller; `main.py` conecta los controllers entre sí; **los paneles que
  muestran datos se suscriben** (desaparecen `refresh_if_current` e `indexChanged → refresh`).
* **Se cierra cuando**: el controller de la ventana no referencia paneles de otra feature y el
  número de conexiones del hub baja de forma medible.

### P7 — Partir las clases-Dios · presupuesto R8

Según la revisión de §2.4: **7 dividir**, 2 parciales, 3 aceptar. Es independiente del resto y se
puede intercalar.

### P8 — R7 alineado con el spec + docstrings + mapa de cableado

* **Qué**: el chequeo de R7 comprueba **vistas** (que es lo que dice el spec), no features; el
  acoplamiento entre features pasa a **informe** (visible, no violación). Docstrings de 3 líneas en
  cada `__init__.py` de carpeta. Y el auditor genera el **mapa de cableado** desde el AST.
* **Se cierra cuando**: R7 mide lo que el spec dice y el informe muestra el grafo de conexiones.

---

### 4.5 Decisiones resueltas

**Del indicador de tamaño y de las reglas manuales**

| # | Decisión | Resolución |
|---|---|---|
| **D1** | Alcance del indicador de tamaño | ✅ **Medir todos los módulos** (`core/`, `common/`, `ui/`). Los tres mayores estaban en `common/` y no contaban. Efecto: R8 4 → **12** (corrección de medición) |
| **D2** | ¿"R8 = 0" obliga a partir módulos? | ✅ **No**: es un **presupuesto**. La meta es **no crecer** (lo verifica la línea base) y que cada módulo grande tenga una **revisión escrita** (§2.4). Resumen: 7 dividir · 2 parciales · 3 aceptar |
| **D3** | `common/commands/global_commands.py` | ✅ **Eliminado**: una sola ventana, ningún comando compartido. El spec se corrigió (árbol §1, §13) |
| **D4** | R5/R6/R22 manuales | ✅ **R6 pasa a automática** (llamadas a métodos privados de colaboradores desde un controller: **0 hoy**). R5 y R22 siguen en checklist manual (§5.2) |

**De composición y comunicación (nueva §23 del spec)**

| # | Decisión | Resolución |
|---|---|---|
| **D5** | ¿Aceptas que `main.py` crezca como «mapa del software»? | ✅ **Sí**: no es un coste, es el mapa — se abre ahí y se ve todo |
| **D6** | Señales de dominio | ✅ **Se quedan en los controllers**: `core/` no puede usar Qt (R1/R15), así que los servicios son API pura |

**De la revisión de la propuesta contra el código (huecos H1–H13)**

| # | Hueco | Resolución |
|---|---|---|
| **H1** | La caché se indexaba **solo por página**, sin escala | ✅ **Contrato de la caché**: guarda cada página a su **escala óptima del plano** (no depende del zoom) y **la miniatura no necesita escala** → compartirla es seguro (spec §23.4.1) |
| **H2** | Las normas no contemplaban los **globales** (22 archivos) | ✅ `settings` y el tema se declaran **globales aceptados**, con su motivo (spec §23.3) |
| **H3** | El motor de BD **no** es uno global | ✅ Es **uno por proyecto abierto**: cada proyecto tiene su `project.db` y el motor se recrea al abrirlo |
| **H4** | `ProjectService` se fabricaba su repositorio | ✅ **Opción (a)**: el repositorio pasa a ser **obligatorio**; se actualizan los 5 tests |
| **H5** | Hay motores que son **funciones** (OCR, texto, PDF) | ✅ Declarados: se llaman directamente; si alguno guarda estado, pasa a inyectado |
| **H6** | El **auto-namer** no aparecía | ✅ **No se toca por ahora** |
| **H7** | El ciclo `common ↔ ui` no estaba en el plan | ✅ Entra como **P0** (va primero: habilita el resto) |
| **H8** | El deshacer del gestor de páginas | ✅ **Opción A**: pila **propia del diálogo** con `QUndoCommand`; guardar sigue siendo irreversible y advertido |
| **H9** | El protocolo del **vigía** está muerto | ✅ **Se ajusta** en P3: pasa a **señales** (no fallan en silencio) |
| **H10** | Radio de la caché | ✅ **7** → 7 atrás + actual + 7 adelante = **15 páginas en RAM**, en **una constante visible** |
| **H11** | Nombres de las comprobaciones | ✅ Nombres reales (`SlidingPageCache`, `DiskPageCache`, `DatabaseManager`) y excluyendo `tests/` |
| **H12** | Impacto en tests (**~11 sitios**) | ✅ Se incluye un ayudante `build_app()` en `tests/support.py` |
| **H13** | Detalles de alcance | ✅ Undo **por documento activo** (se limpia al cambiar de plano); el vigía es **de la pantalla** |


---

## 5. Lo que las 22 reglas no miden

Se declara para que nadie lea "TOTAL 47" como "todo está bien".

### 5.1 Puntos ciegos conocidos

| Qué | Por qué no se mide |
|---|---|
| **Acoplamiento entre módulos** | Las reglas miran direcciones concretas (R1, R7) y no el grafo de imports. Hoy se mide a mano (§2.5) y hay hallazgos reales |
| **Que la aplicación funcione** | El auditor no ejecuta la suite: eso lo cubre `pytest` (143 + 27 tests) |
| **Cumplimiento de R5 y R22** | No son medibles con análisis estático (spec §22.2): van a checklist |

### 5.2 Checklist de reglas manuales (al cerrar cada bloque)

* **R5** — ¿toda comunicación de una vista hacia arriba (padre, ventana, otra feature)
  ocurre por señal, y no por método directo?
* **R22** — ¿alguna capa/carpeta nueva? Si sí, ¿cuál es la necesidad real y dónde está
  escrita?

*(R6 ya no está aquí: pasó a comprobación automática con la decisión D4.)*

---

## 6. Registro de actualizaciones

| Fecha | Qué | TOTAL |
|---|---|---|
| Creación | Línea base medida con el auditor nuevo; brecha por causa raíz; plan B0…B5 | 47 |
| D1–D4 resueltas | R8 mide todas las capas (+8) · R6 automática · `common/commands/` eliminado · presupuesto de tamaño con revisión por módulo (§2.4) | **55** |
| Composición y comunicación | Propuesta revisada **contra el código** (13 huecos H1–H13) → nueva **§23 del spec** y plan **P0…P8** en este documento. La propuesta suelta se elimina: vive aquí y en el spec | 55 |
| **B0 ejecutado** | 7 guardas de capacidad muertas eliminadas (4 archivos) · línea base regenerada | **48** |
| Revisión de los documentos | Verificación **contra el código** de todo lo escrito: 3 discrepancias corregidas (P0: **29** imports y **15** dependencias, no «~32» ni «14»; P5: R13 **−16** y no −18, porque B0 ya quitó 2 de `main_window/controller`; §23.7: el `DatabaseManager` es por proyecto, no del punto de composición) + **hueco tapado**: los **4 hallazgos de R4** en `app_menu_bar` y `window_resizer` no los cubría ningún bloque → van a **P4**, que ahora cierra R4 entero | 48 |
| **P0 ejecutado** | `ui/styles`, `ui/icons` y `ui/helpers` → `common/` · **77 referencias** reescritas en **35 ficheros** · árbol del spec actualizado · ciclo `common → ui` del soporte de UI **roto** (solo queda el de la feature, que va en P3) · contadores sin cambios | 48 |

> Las subidas de TOTAL registradas aquí son **correcciones de medición** (deuda que
> existía sin medirse), nunca empeoramientos: cuando se mide más, el número sube aunque
> el código no cambie.


