"""
Comandos globales compartidos por más de una ventana.

Este módulo se reserva para comandos ``QUndoCommand`` que necesiten ser usados por
**más de una ventana** de la aplicación. Los comandos específicos de una pantalla
deben vivir en ``ui/views/<feature>/commands.py``.

Alcance actual (MVP de una sola ventana)
----------------------------------------
La aplicación muestra **un único documento/ventana activa a la vez**, por lo que hoy
no existe ningún comando compartido entre ventanas. Este módulo queda como contrato
documentado para cuando se implemente el modo multi-ventana.

Ejemplos previstos cuando eso ocurra:

* ``SetActiveDrawingCommand`` — cambiar el plano activo desde varias ventanas.
* ``AddRecentProjectCommand`` — mantener sincronizada la lista de proyectos recientes.

Contrato obligatorio para todo comando que se añada aquí
--------------------------------------------------------
1. Hereda de ``QUndoCommand`` y **ejecuta el cambio en ``redo()``**.
2. Recibe **dependencias explícitas** (servicios del dominio); nunca una ``QUndoStack``
   ni widgets. Así el mismo comando podrá usarse con una pila por ventana.
3. No inspecciona dinámicamente su destino: las dependencias se declaran en el
   constructor y quedan explícitas.
4. No manipula widgets: solo modifica el modelo/servicio; las vistas reaccionan a señales.
"""
from __future__ import annotations

__all__: list[str] = []
