# Especificación: aprendizaje-aprobacion

## Propósito

La conversación por la que lo aprendido llega a estar activo, y por la que se
deshace. Nada se aplica solo. El dueño pregunta «qué has aprendido», ve la lista
con la frase literal que originó cada propuesta, y decide.

Que se enseñe la frase literal no es un detalle de presentación: es la mitigación
del riesgo de aprender un parche que tapa un fallo real. Leyendo la frase, el
dueño ve si aquello era un hueco o un error.

## Requisitos

### Requisito: Nada se aplica sin que el dueño lo pida y lo apruebe

Ninguna regla DEBE pasar a `activa` sin una aprobación explícita del dueño. El
sistema NO DEBE proponer, preguntar ni interrumpir por iniciativa propia mientras
se trabaja: las propuestas se acumulan en silencio hasta que se piden.

#### Escenario: Trabajo normal con propuestas pendientes
- GIVEN hay tres reglas en estado `propuesta`
- WHEN el operador mantiene una conversación cualquiera sin mencionarlas
- THEN nexus no las menciona, no pregunta nada y ninguna se activa

#### Escenario: Reinicio con propuestas pendientes
- GIVEN hay propuestas sin aprobar y nexus se reinicia
- WHEN vuelve a arrancar
- THEN siguen en `propuesta` y ninguna se ha activado por el camino

### Requisito: «qué has aprendido» enseña la tanda completa

Ante una petición de listado de lo aprendido, el sistema DEBE mostrar, por cada
regla en estado `propuesta`: la **frase correctiva literal** de `origen`, la
frase que se enrutaba mal, el `tipo`, el `destino`, la evidencia (`mandado` o
`deducido`, y cuántas ocurrencias) y el resultado de las cinco puertas. DEBE
mostrar también las reglas `activa` y `revertida` de forma diferenciada. Si no
hay nada que enseñar, DEBE decirlo con claridad y NO DEBE rellenar con ejemplos.

#### Escenario: Listado con propuestas pendientes
- GIVEN dos reglas en `propuesta`, una `mandado` y otra `deducido`
- WHEN el dueño pide «qué has aprendido»
- THEN cada una aparece con su frase de origen literal, su destino, su tipo, su
  evidencia y el resultado de las puertas

#### Escenario: Nada aprendido todavía
- GIVEN el almacén está vacío
- WHEN el dueño pide «qué has aprendido»
- THEN la respuesta dice que no hay nada y explica cómo enseñárselo, sin inventar
  ninguna propuesta de ejemplo

### Requisito: Aprobación y descarte por tandas

La aprobación DEBE reutilizar `backend/core/comun/confirm.py`: TTL de 5 minutos,
solo se acepta una respuesta corta y explícita de sí/no, estado por canal, y
todo queda en la auditoría. Aprobar DEBE revalidar las cinco puertas y, si pasan,
poner las reglas en `activa`. Descartar NO DEBE activarlas y NO DEBE borrarlas:
quedan en `propuesta`, marcadas como no aprobadas con fecha y motivo, y no se
vuelven a proponer por la misma evidencia.

#### Escenario: El dueño aprueba la tanda
- GIVEN una tanda de dos propuestas presentada para confirmar
- WHEN el dueño responde «sí»
- THEN las cinco puertas se ejecutan de nuevo y las que pasan quedan `activa`
- AND la auditoría registra la aprobación con la frase de origen de cada una

#### Escenario: El dueño descarta la tanda
- GIVEN una tanda presentada para confirmar
- WHEN el dueño responde «no»
- THEN ninguna regla pasa a `activa`, ninguna se borra, y quedan marcadas como no
  aprobadas

#### Escenario: La confirmación caduca
- GIVEN una tanda presentada hace más de 5 minutos
- WHEN llega un «sí» tardío
- THEN no se activa nada, porque la confirmación ya no está viva

#### Escenario: El dueño cambia de tema
- GIVEN una tanda pendiente de confirmar
- WHEN el siguiente mensaje no es un sí/no explícito
- THEN la confirmación se descarta y nada se activa por sorpresa

#### Escenario: Aprobación por canal
- GIVEN una tanda presentada en el canal `pc`
- WHEN llega un «sí» por otro canal
- THEN no activa la tanda del `pc`

### Requisito: Deshacer conversacional

«Olvida lo que aprendiste sobre X» DEBE poner en `revertida` las reglas activas
que correspondan a X, con efecto inmediato en la decisión y sin borrar nada. Si X
no corresponde a ninguna regla, el sistema DEBE decirlo y NO DEBE revertir nada
por aproximación.

#### Escenario: Olvidar una regla concreta
- GIVEN una regla activa para «cierra el navegador»
- WHEN el dueño dice «olvida lo que aprendiste sobre cerrar el navegador»
- THEN esa regla pasa a `revertida`
- AND la frase vuelve a devolver `planificador` en `quien_atiende()` sin reiniciar

#### Escenario: Olvidar algo que no se aprendió
- GIVEN ninguna regla corresponde a lo que se pide olvidar
- WHEN el dueño lo pide
- THEN nexus lo dice y ninguna regla cambia de estado

### Requisito: Interruptor de fábrica

DEBE existir una operación que vacíe el almacén entero de una vez, dejando la
auditoría intacta. Por ser masiva y difícil de revertir, DEBE pasar por
confirmación explícita antes de ejecutarse.

#### Escenario: Volver a fábrica
- GIVEN varias reglas activas y revertidas
- WHEN el dueño acciona el interruptor de fábrica y confirma
- THEN el almacén queda sin reglas y el comportamiento es el de fábrica
- AND la auditoría conserva la traza de todo lo que hubo

#### Escenario: Interruptor sin confirmar
- GIVEN se pide el interruptor de fábrica
- WHEN el dueño no confirma
- THEN el almacén queda intacto

### Requisito: Auditoría obligatoria de todo el ciclo

Proponer, aprobar, descartar, activar, revertir y vaciar DEBEN dejar cada uno su
línea en la auditoría, con la frase de origen, el destino, quién lo pidió y el
resultado. La auditoría NO DEBE borrarse al revertir ni al volver a fábrica.

#### Escenario: Traza completa de una regla
- GIVEN una regla que se propone, se aprueba, se activa y luego se revierte
- WHEN se consulta la auditoría
- THEN aparecen las cuatro acciones en orden, cada una con su frase de origen

### Requisito: La lista no se llena de ruido

Una propuesta `deducido` NO DEBE aparecer en la lista antes de alcanzar el umbral
de evidencia. Una propuesta `mandado` DEBE aparecer siempre, aunque sea la
primera vez. Dos correcciones sobre la misma frase y el mismo destino DEBEN
agruparse en una sola propuesta, sumando evidencia, nunca en dos entradas.

#### Escenario: Correcciones repetidas se agrupan
- GIVEN el dueño corrige la misma frase hacia el mismo destino tres veces
- WHEN pide «qué has aprendido»
- THEN aparece una sola propuesta con tres ocurrencias de evidencia
