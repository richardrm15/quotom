Arquitectura Modular Desacoplada — Proyecto PySide6
1. Estructura del proyecto
mi_proyecto/
│
├── core/                                      # Lógica de negocio pura
│   ├── __init__.py
│   ├── database.py                            # Conexión SQLite / transacciones
│   ├── models.py                              # Dataclasses / modelos de dominio
│   ├── business_rules.py                      # Reglas y cálculos de dominio
│   │
│   └── services/                              # Casos de uso / servicios de dominio
│       ├── __init__.py
│       ├── project_service.py
│       ├── drawing_service.py
│       └── annotation_service.py
│
├── common/                                    # Componentes compartidos y soporte de UI
│   ├── __init__.py
│   │
│   ├── styles/                                # Tema centralizado
│   │   ├── __init__.py
│   │   ├── theme.qss
│   │   └── style_manager.py
│   │
│   ├── icons/                                 # Fábrica de iconos
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── action_icons.py
│   │
│   ├── helpers/                               # Utilidades de UI sin widgets
│   │   └── ...
│   │
│   ├── pdf/                                   # Motores de PDF y caché
│   │   └── ...
│   │
│   └── widgets/                               # Widgets reutilizables
│       ├── __init__.py
│       ├── custom_table.py
│       └── color_picker.py
│
├── ui/                                        # Toda la capa PySide6
│   ├── __init__.py
│   │
│   ├── dialogs/
│   │   └── ...
│   │
│   └── views/
│       ├── __init__.py
│       │
│       ├── main_window/
│       │   ├── __init__.py
│       │   ├── view.py
│       │   ├── controller.py
│       │   └── commands.py
│       │
│       └── project_editor/
│           ├── __init__.py
│           ├── view.py
│           ├── controller.py
│           └── commands.py
│
├── tests/
│   ├── core/
│   │   ├── test_models.py
│   │   ├── test_business_rules.py
│   │   └── test_services.py
│   │
│   ├── commands/
│   │   ├── test_main_window_commands.py
│   │   └── test_project_editor_commands.py
│   │
│   └── controllers/
│       ├── test_main_window_controller.py
│       └── test_project_editor_controller.py
│
├── requirements.txt
└── main.py
2. Principio general de arquitectura

La dirección de dependencias será estrictamente:

┌──────────────────────────────────────────┐
│                   UI                     │
│               PySide6 / Qt               │
│                                          │
│ View ←→ Controller ←→ Commands            │
└───────────────────┬──────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────┐
│                  CORE                    │
│                                          │
│ Services → Business Rules → Models       │
│     │                                    │
│     └──────────────→ Database             │
└──────────────────────────────────────────┘

La regla fundamental es:

UI → Core
Core → NUNCA → UI

core/ no puede importar:

PySide6
PyQt
QWidget
QObject
Signal
QIcon
QGraphicsItem
QApplication

ni ninguna otra dependencia específica de la interfaz.

3. Regla de comunicación: "Methods Down, Signals Up"

Las vistas no deben conocer a sus padres.

Está prohibido:

self.parent()
self.parentWidget()
self.window()

para obtener acceso a otro componente o a la ventana contenedora.

Comunicación descendente

El controller/padre llama métodos públicos de la vista:

self.view.set_project(project)
self.view.set_drawings(drawings)
self.view.show_loading()
self.view.set_status(message)
Comunicación ascendente

La vista comunica eventos mediante señales:

rename_requested = Signal(str, str)
drawing_selected = Signal(int)
delete_requested = Signal(int)
zoom_changed = Signal(float)

El controller escucha:

self.view.delete_requested.connect(
    self._on_delete_requested
)

La vista nunca llama directamente al controller.

4. Responsabilidad de view.py

view.py contiene exclusivamente presentación.

Puede contener:

QWidget
QMainWindow
layouts
botones
tablas
QGraphicsView
QGraphicsScene
eventos visuales
señales
actualización de widgets
construcción de menús y toolbars

No debe contener:

SQL
reglas de negocio
cálculos de dominio
acceso directo a database.py
lógica de persistencia
decisiones de negocio
creación directa de comandos de dominio
referencias a la ventana padre

Ejemplo:

def on_delete_clicked(self):
    drawing_id = self.selected_drawing_id()

    if drawing_id is not None:
        self.delete_requested.emit(drawing_id)

La vista comunica el evento.

No decide qué hacer con él.

5. Responsabilidad de controller.py

El controller es el orquestador de la feature.

Responsabilidades:

conectar señales de la vista
llamar servicios del core
coordinar comandos
administrar QUndoStack
transformar resultados del dominio en datos para la vista
manejar errores de aplicación
coordinar estados de UI

No debe convertirse en una segunda capa de negocio.

Evitar:

def calculate_quantity(...):
    # 200 líneas de lógica de negocio

Preferir:

def calculate_quantity(...):
    return self.annotation_service.calculate_quantity(...)
6. Servicios de core

Los servicios contienen operaciones/casos de uso del dominio.

Ejemplo:

class AnnotationService:

    def create_annotation(self, annotation):
        self._validate(annotation)
        return self.repository.create(annotation)

    def update_annotation(self, annotation):
        self._validate(annotation)
        return self.repository.update(annotation)

    def delete_annotation(self, annotation_id):
        return self.repository.delete(annotation_id)

Los servicios:

no conocen widgets
no conocen ventanas
no emiten señales Qt
no dependen de PySide6
pueden ser probados independientemente de la UI
7. Base de datos

Inicialmente se permite:

core/database.py

para mantener el proyecto sencillo.

Si la persistencia crece considerablemente, puede evolucionar a:

core/
└── database/
    ├── __init__.py
    ├── connection.py
    ├── migrations.py
    └── repositories/
        ├── project_repository.py
        ├── drawing_repository.py
        └── annotation_repository.py

No se debe introducir esta complejidad antes de necesitarla.

8. Arquitectura de QUndoCommand

Todos los comandos deben utilizar el comportamiento canónico de Qt.

Está prohibido:

self._applied_once

o cualquier mecanismo equivalente.

También está prohibido ejecutar manualmente la operación antes de:

undo_stack.push(command)

El cambio debe ejecutarse mediante:

redo()

Ejemplo:

class RenameDrawingCommand(QUndoCommand):

    def __init__(
        self,
        drawing_service,
        drawing_id,
        old_name,
        new_name,
    ):
        super().__init__()

        self._service = drawing_service
        self._drawing_id = drawing_id
        self._old_name = old_name
        self._new_name = new_name

    def redo(self):
        self._service.rename(
            self._drawing_id,
            self._new_name,
        )

    def undo(self):
        self._service.rename(
            self._drawing_id,
            self._old_name,
        )

Uso:

command = RenameDrawingCommand(
    self.drawing_service,
    drawing_id,
    old_name,
    new_name,
)

self.undo_stack.push(command)

El primer redo() será ejecutado por QUndoStack.

9. Regla estricta para Commands

Los comandos:

Pueden
modificar modelos mediante servicios
llamar repositorios mediante servicios
almacenar estado necesario para undo/redo
ejecutar redo()
ejecutar undo()
No pueden
modificar QWidget
modificar QMainWindow
modificar QTableWidget
modificar directamente una sidebar
mostrar mensajes de UI
modificar barras de estado
llamar parent()
utilizar hasattr()
utilizar getattr()
inspeccionar dinámicamente targets
"adivinar" qué objeto deben modificar

Las dependencias deben ser explícitas.

10. Signals y Core

El core no utiliza Qt Signals.

Incorrecto:

# core/services/project_service.py

class ProjectService(QObject):
    project_changed = Signal()

Correcto:

Core
  ↓
resultado / excepción / estado
  ↓
Controller
  ↓
Qt Signal
  ↓
View

Esto mantiene el dominio completamente independiente de PySide6.

11. Estilos

Todos los estilos visuales permanentes deben estar centralizados:

common/styles/theme.qss

Las vistas no deben contener:

widget.setStyleSheet("""
    background: #123456;
    ...
""")

Se utilizará:

self.setProperty("state", "error")

cuando sea necesario representar estados dinámicos.

Y el QSS:

QWidget[state="error"] {
    ...
}

Las excepciones dinámicas deben ser justificadas.

12. Iconos

Los iconos deben centralizarse en:

common/icons/

La interfaz utiliza:

from common.icons import get_icon

button.setIcon(
    get_icon("save")
)

La vista no debería contener repetidamente código de QPainter.

La fábrica será responsable de:

get_icon(
    name,
    color=None,
    size=None,
)
13. common/

common/ solamente contiene componentes que realmente son compartidos por múltiples features.

Ejemplos válidos:

common/widgets/custom_table.py
common/widgets/color_picker.py

**Los comandos compartidos entre ventanas no tienen hoy sitio aquí**: la aplicación
trabaja con **una sola ventana**, así que no existen comandos comunes. Si algún día
llega el modo multi-ventana, este es el lugar para ellos (`common/commands/`), con las
mismas reglas de R10–R14.

No debe convertirse en un "cajón de sastre".

Si algo pertenece exclusivamente a:

project_editor

se queda dentro de:

ui/views/project_editor/
14. Regla de dependencia entre Views

Las vistas hermanas no deben comunicarse directamente.

Incorrecto:

MainWindowView
      ↓
ProjectEditorView

También está prohibido que:

project_editor_view.some_method(...)

sea llamado directamente desde otra vista.

La coordinación pasa por el controller correspondiente.

15. Regla para objetos gráficos

Los objetos visuales de Qt pertenecen a la UI.

Por ejemplo:

QGraphicsScene
QGraphicsItem
QGraphicsRectItem
QGraphicsTextItem

no deben almacenarse como parte del modelo de dominio.

El modelo debe almacenar datos:

Annotation(
    id=1,
    page_id=5,
    x=100,
    y=200,
    width=50,
    height=30,
    color="#ff0000",
)

Mientras que la UI transforma ese modelo en:

Annotation
      ↓
QGraphicsItem

Esto es especialmente importante para permitir posteriormente:

persistencia SQLite
undo/redo
exportación
testing
serialización
versiones de proyecto
16. Tests

El código de core debe poder probarse sin iniciar Qt.

Prioridad:

core/
├── models
├── business_rules
└── services

Después:

commands/

Los comandos deben poder probar:

redo()
undo()
redo()
undo()

y comprobar que el estado termina correctamente.

17. Regla contra inspección dinámica

Está prohibido utilizar:

hasattr()
getattr()
setattr()

como mecanismo para descubrir dependencias u objetos.

Incorrecto:

target = getattr(self, "_target", None)

Correcto:

def __init__(self, drawing_service):
    self._drawing_service = drawing_service

Las dependencias siempre deben estar declaradas explícitamente.

18. Regla de responsabilidades

Cada componente debe responder a una sola pregunta:

View
¿Qué debe mostrar y qué evento ocurrió?

Controller
¿Qué debe coordinarse como consecuencia del evento?

Command
¿Cómo se ejecuta/revierte una operación mediante undo/redo?

Service
¿Qué operación de negocio debe ejecutarse?

Business Rules
¿Qué reglas/cálculos determinan el resultado?

Model
¿Qué datos representan el dominio?

Database/Repository
¿Cómo se persisten y recuperan los datos?
19. Flujo completo de una operación

Ejemplo: cambiar el nombre de un plano.

Usuario
   │
   ▼
View
   │
   │ rename_requested
   ▼
Controller
   │
   │ crea Command
   ▼
QUndoStack.push()
   │
   ▼
Command.redo()
   │
   ▼
DrawingService
   │
   ▼
Database
   │
   ▼
Controller
   │
   │ actualiza View
   ▼
View

Para undo:

Usuario
   │
   ▼
QUndoStack.undo()
   │
   ▼
Command.undo()
   │
   ▼
DrawingService
   │
   ▼
Database
   │
   ▼
Controller / estado
   │
   ▼
View
20. Reglas obligatorias durante el refactoring

Toda modificación del código deberá respetar las 22 reglas siguientes. **Cada regla
lleva un identificador estable `R1`…`R22`**: es la referencia que usan el auditor
(`tools/audit_rules.py`), la documentación y los comentarios del código.

R1. core/ no importa PySide6.
R2. view.py no contiene SQL.
R3. view.py no accede directamente a database.py.
R4. Las vistas no llaman parent(), parentWidget() ni window() para comunicarse.
R5. Las vistas emiten señales para eventos.
R6. Los padres/controllers llaman métodos públicos de las vistas.
R7. Las vistas hermanas no se conocen entre sí.
R8. Los controllers orquestan, pero no contienen lógica de negocio compleja.
R9. La lógica de negocio pertenece a core/services y business_rules.
R10. Los QUndoCommand reciben dependencias explícitas.
R11. QUndoCommand.redo() realiza la operación.
R12. No se utilizan hacks como _applied_once.
R13. No se utilizan hasattr()/getattr() para descubrir targets.
R14. Los commands no manipulan widgets.
R15. core no utiliza Signals de Qt.
R16. Los estilos permanentes viven en theme.qss.
R17. No se utilizan setStyleSheet() dispersos por las vistas.
R18. Los iconos se generan mediante common/icons/get_icon().
R19. common/ solamente contiene componentes realmente compartidos.
R20. La lógica de dominio debe poder probarse sin iniciar Qt.
R21. Los objetos gráficos de Qt no forman parte de los modelos de dominio.
R22. No se introduce una capa arquitectónica adicional salvo que exista una necesidad real.
21. Objetivo final

La arquitectura debe permitir que:

┌─────────────────────────────┐
│         PySide6 UI          │
│                             │
│ View / Controller / Command │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│            Core             │
│                             │
│ Services                    │
│ Business Rules              │
│ Models                      │
│ Database                    │
└─────────────────────────────┘

sea mantenible y extensible sin convertir el proyecto en una arquitectura excesivamente compleja.

La prioridad será:

desacoplamiento → claridad → testabilidad → mantenibilidad → extensibilidad

y no añadir abstracciones simplemente por cumplir una arquitectura teórica.

22. Auditoría: alcance y método

El cumplimiento de las reglas R1…R22 se comprueba con `tools/audit_rules.py`. Esta
sección define **qué se audita y cómo**, para que el resultado sea interpretable y
para que nadie confunda "no medido" con "cumple".

### 22.1 Alcance

Rutas auditadas:

```
core/            lógica de dominio
common/          componentes compartidos
ui/              toda la capa PySide6
main.py          punto de entrada
tests/           solo organización (R20) y que core se pruebe sin Qt
```

Rutas **excluidas** (no son código de la aplicación):

```
tools/           utilidades de desarrollo, incluido el propio auditor
docs/            documentación
env/  __pycache__/  .cache/  .git/  .pytest_cache/  build/  dist/
```

Nota sobre `tests/tools/`: contiene las pruebas **del propio auditor**
(`tests/tools/test_audit_rules.py`). Queda fuera del alcance de R1…R21 por la misma
razón que `tools/`: es instrumental de desarrollo, no código de la aplicación. Sus
pruebas se ejecutan con el resto de la suite.

### 22.2 Tipos de verificación

| Tipo | Significado |
|---|---|
| **automática** | El auditor la mide sobre el código (texto o AST) y da un número |
| **informativa** | El auditor comprueba existencia o uso, pero no puede contar violaciones con objetividad |
| **manual** | No es medible con análisis estático: se revisa al cerrar cada hito y se deja constancia del resultado y la fecha |

| Regla | Tipo | Qué mira |
|---|---|---|
| R1, R15 | automática | imports y nombres de Qt en `core/` |
| R2, R3 | automática | SQL y acceso a `database` en `view.py` |
| R4 | automática | `parent()` / `parentWidget()` / `window()` en `common/` y `ui/` |
| R5 | **manual** | Que toda comunicación de una vista hacia arriba sea por señal |
| R6 | automática | Llamadas a métodos **privados** de un colaborador desde un controller |
| R7 | automática | imports entre features de `ui/views/` |
| R8 | automática | Acceso a BD desde controllers + **presupuesto de tamaño** de todos los módulos |
| R9 | informativa | Existencia de servicios de dominio en `core/services/` |
| R10, R11, R12 | automática | Estructura y dependencias de los `QUndoCommand` |
| R13 | automática (con criterio, ver 22.4) | `hasattr`/`getattr`/`setattr` |
| R14 | automática | Uso de widgets desde `commands.py` |
| R16, R17 | automática | `setStyleSheet` fuera de `common/styles/` |
| R18 | informativa | Uso de `common/icons.get_icon` |
| R19 | informativa | Uso real de cada subcarpeta de `common/` |
| R20 | automática | `tests/core/` sin Qt |
| R21 | automática | Objetos gráficos de Qt en `core/` |
| R22 | **manual** | Que cada capa nueva tenga una necesidad real declarada |

**R8 — el tamaño no es una violación, es un presupuesto.** El indicador de tamaño se
mide sobre **todos** los módulos de la aplicación (`core/`, `common/`, `ui/`) y su meta
**no es 0**: un módulo grande puede ser perfectamente cohesivo. Lo que se exige es que
**no crezca** (la línea base lo verifica) y que cada módulo por encima del umbral tenga
una **revisión escrita** en `docs/BRECHA.md`: dividirlo, o aceptarlo con motivo.

### 22.3 Excepciones justificadas

Una violación puede declararse **excepción justificada**, y entonces no cuenta. La
excepción se escribe **junto al chequeo** que la aplica, dentro de `tools/audit_rules.py`,
con dos datos obligatorios: **qué** se exceptúa y **por qué**. Una excepción sin motivo
no es una excepción: es deuda escondida.

### 22.4 R13 — criterio de aplicación

La regla prohíbe `hasattr`/`getattr`/`setattr` **como mecanismo para descubrir
dependencias u objetos**. El auditor distingue tres casos:

| Caso | Trato |
|---|---|
| Se descubre el estado, la capacidad o la identidad de **otro** objeto (`hasattr(mw, "_undo_stack")`, `hasattr(item, "annot_id")`, `hasattr(widget, "apply_theme")`) | **violación** |
| Se consulta el **estado propio** (`hasattr(self, "_table_view")`) | **cuenta aparte**: es inicialización descargada y se corrige inicializando en `__init__` |
| Se resuelve un **nombre que solo existe en ejecución** (`getattr(tokens, token_name)`) | **excepción justificada** (§22.3): el nombre del token es un dato, no una dependencia |

**Las guardas de capacidad no son excepción.** `hasattr(obj, "metodo")` para averiguar
si la versión de Qt soporta una función parece legítima, pero este proyecto fija
`PySide6 >= 6.6` en `requirements.txt`, y las capacidades que se comprueban existen desde
mucho antes (`setColorScheme` desde Qt 6.5; `startSystemMove` desde Qt 5.15). Son código
muerto: se cuentan como violación.

23. Composición y comunicación

Esta sección dice **de dónde salen las dependencias, quién construye qué y cómo hablan las
piezas entre sí**. La base de datos sigue siendo **SQLite** (`core/database.py`) y sigue
siendo la **fuente única de la verdad**: aquí no se cambia eso.

### 23.1 Los tres problemas, que no son el mismo

| Problema | Qué es | Cómo se resuelve |
|---|---|---|
| **Intenciones** | Un evento sin estado: «el usuario pulsó X» | **Señal**, conectada donde vive el emisor |
| **Estado** | Un dato que muestran varios paneles y debe estar en sincronía | **Suscripción**: el que lo muestra se suscribe |
| **Acciones** | Un cambio que debe poder deshacerse | **Comando + servicio + pila de undo** |

Tratar el estado como si fuera un evento produce parches de sincronía manual
(«refresca la tabla», «recarga si es la actual»). Eso es lo que hay que evitar.

### 23.2 Normas

> **N1. Composición única.** Los motores se construyen **una sola vez**, en `main.py`.
> Ningún otro archivo construye motores compartidos.
>
> **N2. Dependencias explícitas.** Cada controller declara en su **constructor** lo que
> usa. Prohibido buscarlo: contenedores, globales de servicio, `get_servicio()`.
>
> **N3. Dirección.** Vista → controller por **señales**. Controller → vista por señales o
> métodos **públicos**. Controller → motores por **llamada directa** (ya los tiene).
>
> **N4. Sin hub.** No hay despachador central: **decide el controller de la pantalla**,
> que conoce su flujo y tiene sus motores en la mano.
>
> **N5. Instancia única o por pantalla.** Criterio: *¿dos partes necesitan ver lo mismo?*
> Sí → **una** instancia, creada en `main.py`. No → puede vivir en su pantalla.
>
> **N6. La UI no toca la base de datos.** Ni vistas, ni widgets, ni diálogos: solo los
> servicios (`core/services/`), que son la API del repositorio.

**Restricción que se mantiene (R1/R15):** `core/` **no usa Qt**. Por eso los avisos de
cambio («cambiaron las anotaciones») los emiten los **controllers** de la capa UI; los
servicios son API pura, sin señales.

### 23.3 Excepciones declaradas

| Excepción | Motivo |
|---|---|
| **`settings` (ajustes) y el tema** se importan directamente, no se inyectan | Son **globales de aplicación** (preferencias y apariencia). Inyectarlos en cada widget añadiría ruido sin beneficio. Se documentan aquí para que la norma N2 no sea papel mojado |
| **Motores funcionales** (OCR, extracción de texto, utilidades PDF) se llaman como **funciones** | No tienen estado ni hay que sustituirlos en pruebas. Si alguno empieza a guardar estado, pasa a motor inyectado |
| **`DatabaseManager` es uno por proyecto abierto** | Cada proyecto tiene su propio `project.db`: el motor se recrea al abrir o crear proyecto. No es una instancia global de la aplicación |
### 23.4 La raíz de composición y los motores

`main.py` es el **único** que construye motores compartidos: al abrirlo se ve el software
entero y quién usa qué.

```python
# main.py
db        = DatabaseManager(...)          # (por proyecto; ver 23.3)
proyecto  = ProjectManager(db)            # repositorio
servicios = ProjectService(proyecto)      # dominio: planos, anotaciones, mediciones
pdf       = PdfEngine()                   # render PDF
cache     = SlidingPageCache(radius=7)    # UNA caché (ver 23.4.1)
undo      = QUndoStack()

view       = MainWindowView(...)
doc_ctrl   = DocumentController(pdf=pdf, cache=cache)      # ← recibe, no fabrica (P1)
annot_ctrl = AnnotationController(viewer=view.viewer, project_service=servicios, undo_stack=undo)
main_ctrl  = MainWindowController(view=view, doc_ctrl=doc_ctrl,
                                  annot_ctrl=annot_ctrl, project_service=servicios,
                                  undo_stack=undo)          # ← recibe, no construye (P2)
```

*(Los parámetros que aún no existen —`pdf`, `cache`, `doc_ctrl`, `annot_ctrl`— son el objetivo de
P1 y P2: hoy `DocumentController` fabrica sus motores y `MainWindowController` construye los
subcontroladores.)*

**Qué motor es único y qué no**: el criterio de N5, aplicado a los motores actuales.

| Motor | Instancia correcta |
|---|---|
| Repositorio y servicios de dominio | **1** (la construcción es tarea de `main.py`) |
| Pila de undo | **1** para el documento activo (se limpia al cambiar de plano) |
| Caché de páginas (RAM y disco) | **1** compartida (ver 23.4.1) |
| Motor de render PDF | **1**; su *worker* puede ser de la pantalla |
| Vigía de archivos (`QFileSystemWatcher`) | **de la pantalla** (avisa del cambio externo del plano) |
| Indexador en segundo plano | **de la pantalla** (rellena la caché compartida) |

**Ningún servicio se fabrica su repositorio.** Un constructor de servicio **exige** el
repositorio; no vale `manager or ProjectManager()`, porque eso crea un segundo objeto con
su propio estado de proyecto («¿cómo que no hay plano abierto?») y esconde la dependencia.

#### 23.4.1 Contrato de la caché

* **Guarda cada página a su escala óptima del plano** (la calcula el motor de render; **no
  depende del zoom**). Eso es lo que hace segura la compartición.
* **La miniatura no necesita escala**: el gestor de páginas puede usar la misma caché
  aunque su previsualización sea más pequeña.
* **Radio**: `radius=7` → 7 páginas atrás + la actual + 7 adelante = **15 páginas en RAM**.
  El valor vive en **un solo sitio visible** (`main.py`, en la creación de la caché) para
  poder ajustarlo sin buscarlo por el código. *Nota*: el valor por defecto del motor es 3
  (7 páginas); se elige 7 por margen de desplazamiento en planos grandes.

### 23.5 Cableado y contextos de deshacer

**El cableado se centraliza por pantalla**, no por aplicación:

| Quién cablea | Qué cablea |
|---|---|
| `main.py` | los controllers **entre sí** |
| controller de cada **pantalla** | su **vista**, sus **paneles** y sus **subcontroladores** |
| nadie | las hojas de otra feature: un controller no cablea paneles ajenos |

**Un panel que muestra datos se suscribe** a la señal que los lleva (estado), en lugar de
que alguien se los empuje desde arriba.

**Dos contextos de deshacer, un solo mecanismo (`QUndoCommand`):**

| Contexto | Pila | Alcance |
|---|---|---|
| **Documento** | la del aplicativo | El documento activo; se limpia al cambiar de plano |
| **Sesión del diálogo** (gestor de páginas) | propia del diálogo | Solo mientras el diálogo está abierto; se descarta al cerrar |

Regla del gestor de páginas: **sus comandos modifican la lista de páginas en memoria; el
PDF se reescribe solo al guardar**, y ese acto es **irreversible y advertido** al usuario.
El diálogo nunca «deshace» un archivo ya reescrito.

**El aviso de cambio externo se hace con señales, no con `hasattr`.** Cuando la aplicación
va a reescribir un plano, avisa (`a punto de reescribir` / `reescrito`) y el controller del
documento pausa su vigía y su indexador. Un `hasattr` a un método que no existe **falla en
silencio** (ya ha pasado en este proyecto); una señal sin oyentes lo dice el mapa de
cableado.

### 23.6 Estructura de carpetas

```
core/                 LA VERDAD: datos y reglas. SIN Qt.
  database.py · project.py · services/
common/               SOPORTE Y PIEZAS DE UI: una por archivo
  styles/ icons/ helpers/ · pdf/ · widgets/
ui/views/<pantalla>/  UNA pantalla: view + controller + commands (+ sus paneles)
main.py               construye y conecta todo
tools/ · docs/        instrumentos y documentación
```

**Regla de lectura**: verdad o cálculo → `core/` · soporte técnico o pieza de UI → `common/` ·
una pantalla y quién la gobierna → `ui/views/<pantalla>/` · construye el software → `main.py`.

* **`common/` puede alojar piezas de una sola pantalla**, siempre que **cada una viva en su propio
  archivo** y sea autocontenida. Lo que `common/` **no puede** es depender de `ui/` ni de las
  features (dirección de dependencias, §23.2).
* **Una pieza de UI = un archivo.** Una toolbar es un archivo; el view de cada pantalla es un
  archivo; sus paneles, sus propios archivos.
* **Jerarquía de vistas**: cada vista es hija de alguien y hay **una sola raíz** (la ventana
  principal). Cuando un widget no sabe quién es su padre y lo busca en tiempo de ejecución, eso es
  justo lo que cuentan R4 y R13.

Cada `__init__.py` de carpeta lleva un **docstring de 3 líneas** diciendo qué hay ahí y qué
no debe haber, para que al abrir el repositorio se entienda sin leer código.

### 23.7 Cómo se audita

Comprobaciones previstas (se implementan con el plan de `docs/BRECHA.md`):

| Comprobación | Medición |
|---|---|
| Sin ciclo de capas | `common/` no importa de `ui/` ni de features; `core/` no importa de `ui/` ni de `common/` |
| La UI no toca la BD | ningún `view.py` ni widget importa `core.database` / `core.project` |
| Motores compartidos = 1 instancia | `SlidingPageCache(` / `DiskPageCache(` construidos **fuera del punto de composición** → 0. *(El `DatabaseManager` se construye dentro del repositorio, uno por proyecto abierto: ver 23.3)* |
| Sin búsqueda de servicios | ningún contenedor global ni `get_*service()` |
| Cableado por pantalla | un controller no referencia widgets de otra feature |
| Mapa de cableado | informe generado desde el AST con las conexiones señal → receptor |

**Convención de pruebas**: el cableado de la aplicación se monta con un **ayudante**
(`tests/support.py`) para no repetir la composición en cada prueba.

