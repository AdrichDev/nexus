# Propuesta: aprender de las correcciones

## El problema, en los términos del dueño

Cuando le dices a nexus «no, te he dicho esto» o «por qué has hecho eso», nexus
**no aprende nada**. Lo detecta —`_META_QUEJA_RX` y `_NO_ACCION_RX` existen en
`backend/core/brain.py:277-293`— y lo único que hace es contestar. La corrección
se pierde.

Y la corrección es exactamente la señal que falta. La tarde del 03/08 el dueño
usó nexus de verdad y salieron **once fallos** de este tipo. `estado.md` registra
dos tandas de esa sesión, nueve y seis. **La suite estaba verde entera** durante
todos ellos. La lección ya está escrita ahí:

> Una prueba que mira un escalón por debajo de donde está el fallo lo declara
> arreglado.

El patrón se repite: la frase no lleva la palabra exacta que exige la regex, el
router no casa, la orden cae al planificador y nunca llega a la skill que sabía
atenderla. «cierra chrome», «dame ideas», «apunta la mentoría el jueves». Cada
uno se arregló **a mano**, uno por uno, editando `skill.py`. Eso no escala, y en
una instalación de otro usuario no hay nadie que lo edite.

Existe la materia prima y no se usa para decidir: `selflearn.operator_profile()`
destila un perfil del operador y se inyecta en el prompt, pero **no enruta**.
`brain._learn_record()` aprende pares frase→orden, y solo desde la fórmula
explícita «aprende que cuando diga X hagas Y». Nadie aprende observando.

## Alcance

### Dentro

| Entrega | Qué es |
| --- | --- |
| **Contrato de regla aprendida** | El esquema, dónde vive, qué la hace válida y cómo se deshace. Es el núcleo de seguridad de todo lo demás |
| **La corrección como señal** | Una queja detectada genera una **regla propuesta**, no un cambio |
| **Validación antes de activar** | Cinco puertas deterministas. Sin las cinco, la regla no entra |
| **Aprobación por tandas** | «qué has aprendido» → lista de propuestas → sí/no. Cero interrupciones mientras se trabaja |
| **Enrutado aprendido** | Las reglas activas participan en la decisión, en una posición declarada |
| **Deshacer** | «olvida lo que aprendiste sobre X» y un interruptor de fábrica |

### Fuera

- **Escribir skills nuevas.** Nunca. Es la línea que el dueño puso y esta
  propuesta la refuerza: nexus no genera código.
- **Reescribir ficheros `.py`.** Ni siquiera los propios. Ver *Enfoque*.
- **Corregir a quién pertenece una frase que ya atiende otra skill.** Deliberado,
  ver *Enfoque*.
- Personalidades y tono (→ `006`).
- Cron real, horarios y creación de automatizaciones n8n (→ `005`).
- Instalador, elección Docker/VPS y canal de actualizaciones (→ `007`).

## El corte recomendado

Los cinco encargos del dueño **no caben en un cambio**, y no por tamaño: por
riesgo. Recomiendo cuatro, en este orden y por este motivo:

| # | Cambio | Por qué ahí |
| --- | --- | --- |
| **004** | **Aprender de las correcciones** (este) | Define **cómo se le permite a nexus cambiarse a sí mismo**. Todo lo demás hereda esa regla. Hacerlo después significa reescribirlo |
| 005 | Horarios y automatizaciones | Mecanismo independiente, riesgo propio. No depende de 004 y podría ir en paralelo |
| 006 | Voz propia y personalidades | Presentación. Barato, aislado, sin dependencias |
| 007 | Distribución y actualizaciones | **El último a propósito.** Enviar a máquinas de terceros un nexus que se automodifica exige que 004 esté probado; y el canal de actualización es lo único que puede romper instalaciones que no controlamos |

«Aprender» e «interpretar mejor» van juntos porque **son el mismo mecanismo**:
aprender sin aplicar es un diario, e interpretar mejor sin aprender es más regex
escrita a mano — justo lo que falló.

## Capacidades

### Nuevas

- `aprendizaje-contrato`: esquema, almacén, estados y ciclo de vida de una regla aprendida
- `aprendizaje-correcciones`: de una queja del operador a una regla propuesta, con evidencia
- `aprendizaje-validacion`: las puertas que una regla debe pasar para activarse
- `aprendizaje-aprobacion`: la conversación por tandas, la auditoría y el deshacer
- `enrutado-aprendido`: cómo y **dónde** participan las reglas activas en la decisión

### Modificadas

Ninguna. `openspec/specs/` está vacío.

## Enfoque

**Los datos se escriben; el código no.** Es la decisión que sostiene el resto.
Una regla aprendida vive en `data/reglas_aprendidas.json` y los valores
declarados en una capa de sobreescritura sobre `config/umbrales.json`. Ningún
`.py` se toca jamás. Consecuencia directa: en una instalación sin repositorio y
sin suite, **deshacer el aprendizaje es borrar un fichero**.

Dos tipos de regla, y solo dos:

- **`enrutado`** — una forma de decir algo → un `skill/intent` **que ya existe**.
  Amplía el alcance; jamás inventa un handler.
- **`valor`** — sobreescribe un valor ya declarado (umbral, lista de exclusión,
  texto de respuesta), por clave, con tipo y rango declarados.

**Posición en la decisión.** Las reglas de enrutado se consultan **después** del
router nativo, en `brain.quien_atiende()` / `process`. Una regla aprendida solo
puede ocupar el hueco que hoy cae al planificador. **Estructuralmente no puede
robarle una frase a una skill que ya la atiende.** Eso convierte el riesgo de
robo en imposible por construcción, no en algo que haya que vigilar. El precio,
declarado: corregir un enrutado **equivocado** —no ausente— sigue siendo trabajo
del dueño, no de la máquina.

**Quién es el dueño del mecanismo.** Tres candidatos, y recomiendo el tercero:
una capacidad nueva de «editar skills» pone generación de código dentro de la
máquina y obliga a montar todo el aparato de revisión en cada instalación;
delegar en `hermes` es tentador porque **ya escribe ficheros** (provisiona
`~/.hermes/.env`, `skills/hermes/skill.py:393`), pero hermes es un agente externo
de pago, no determinista, que puede escribir en cualquier sitio y que es
**infraestructura opcional** —un usuario sin hermes se quedaría sin aprender—;
la recomendación es un módulo nuevo y determinista en `backend/core/`, con una
skill fina encima solo para la conversación. **El LLM puede proponer una regla;
solo código determinista puede activarla.**

### El contrato, en claro

Una regla es válida si y solo si:

| Puerta | Qué comprueba |
| --- | --- |
| **Campos** | `id`, `tipo`, `origen` (la frase correctiva literal, canal y fecha), `destino`, `patron`\|`valor`, `evidencia`, `estado`, `revision`. Falta uno, no es una regla |
| **Existencia** | El `destino` es un `skill/intent` real de `skills_loader.get_skills()`, o una clave que ya existe con su tipo y rango |
| **Forma** | La regex compila, está anclada y no casa por encima de un tope sobre el corpus conocido |
| **No robo** | Se ejecuta `brain.quien_atiende()` sobre el corpus completo **antes y después**. Si cambia de dueño una sola frase que no era el objetivo, la regla se descarta |
| **Suite** | En desarrollo, `run_all.py` sigue verde tras aplicar la tanda |

El corpus no hay que inventarlo: son las **244 órdenes** que ya barre
`test_lo_prometido.py` más las frases reales de `test_regresion_conversacion.py`.
`quien_atiende()` se escribió el 03/08 exactamente para mirar donde de verdad se
decide; aquí es la puerta principal.

Estados: `propuesta → activa → revertida`. Nada se borra: `backend/core/audit.py`
deja traza y revertir es cambiar el estado, no perder la historia. La aprobación
reutiliza `backend/core/confirm.py` —TTL de 5 minutos, respuesta corta y
explícita, estado por canal, auditoría— en vez de inventar otro sí/no.

## Áreas afectadas

| Área | Impacto | Qué cambia |
| --- | --- | --- |
| `backend/core/` (módulo nuevo) | Nueva | Contrato, almacén, validación, activación y reversión |
| `backend/core/brain.py` | Modificada | Las reglas activas entran en `quien_atiende()`/`process`, **detrás** del router. Se declara el atajo nuevo, como exige `test_regresion_conversacion` |
| `backend/core/selflearn.py` | Modificada | El perfil pasa de solo alimentar el prompt a también proponer reglas |
| `data/reglas_aprendidas.json` | Nueva | El almacén. Único fichero que nexus escribe |
| `config/umbrales.json` | Modificada | Capa de sobreescritura declarada |
| `skills/<nueva>/` | Nueva | Solo superficie de conversación. **Ojo al orden alfabético** del loader |
| `tests/` | Nueva | Suites nuevas, registradas en `tests/run_all.py` |

`skills_loader` no cambia: ni su orden, ni su primera-que-case. El esquema de
Postgres tampoco. En el ciclo cerrado de Content OS esto toca solo la etapa de
**memoria**: las reglas son un tipo de aprendizaje más, y no alimentan hipótesis
ni experimentos.

## Riesgos

| Riesgo | Probabilidad | Mitigación |
| --- | --- | --- |
| **La automodificación rompe la instalación de un usuario que no tiene repositorio ni tests para recuperarse** | Media | Solo se escriben datos, nunca código. Borrar `data/reglas_aprendidas.json` devuelve el comportamiento de fábrica. El corpus de validación viaja con la instalación (ver *Preguntas*) |
| **El canal de actualización empuja código a máquinas de terceros** | Alta si se hace mal | Fuera de este cambio, pero 004 lo condiciona: lo aprendido es **local y del usuario**, jamás se sube ni se distribuye. La separación `fact`/`procedure`/`preference` (del usuario) frente a `knowledge` ya existe en `opmem.py` |
| **Una regla aprendida le roba frases a otra skill en silencio** | Alta sin mitigar | Imposible por construcción: las reglas van **detrás** del router. Y aun así se comprueba con `quien_atiende()` sobre el corpus antes y después |
| **Aprender un parche que tapa un fallo real del código** | Media | La regla guarda `origen` literal. Al aprobar se enseña la frase que la originó, para que el dueño vea si aquello era un hueco o un error |
| **Ruido: reglas de una sola vez, mal escritas** | Media | Umbral de evidencia (≥N ocurrencias reales) antes de que una corrección llegue siquiera a proponerse |
| **Un dato personal del dueño se cuela en una regla y viaja en el instalador** | Baja, alta si pasa | Lo aprendido va a `data/`, que no se empaqueta. La guarda de `test_skill_domotica.py:372` se extiende a los ficheros nuevos |

## Plan de reversión

1. `«olvida lo que aprendiste sobre X»` → la regla pasa a `revertida`.
2. Interruptor de fábrica: vacía el almacén entero, deja la auditoría.
3. Recuperación total: borrar `data/reglas_aprendidas.json` y la capa de
   sobreescritura, y reiniciar con `run.bat`.
4. En desarrollo, además, `git revert` — pero **el plan no depende de git**,
   porque en la máquina de un usuario no hay git.

## Dependencias

- Ninguna externa. Todo se apoya en piezas ya en el repositorio:
  `brain.quien_atiende()`, `confirm.request()`, `audit`, `selflearn`,
  `test_lo_prometido.py` y `test_regresion_conversacion.py`.

## Decisiones del dueño (03/08/2026)

Cuatro de las cinco preguntas están respondidas. Van aquí y no en un chat porque
condicionan el diseño entero, y quien retome esto tiene que encontrarlas.

1. **El catálogo de frases VIAJA con el instalador.** La puerta de «no robo»
   corre en casa del usuario antes de aplicar cualquier regla. Es la única red
   que va a tener: sin ella aprendería a ciegas. Contrapartida asumida: ese
   catálogo pasa a ser un artefacto que hay que mantener al día, y quedarse
   obsoleto significa validar contra una foto vieja.

2. **La evidencia depende de quién lo diga.** Si el dueño lo ordena
   explícitamente («aprende que cuando diga X hagas Y»), entra a la primera: es
   una orden, no una sospecha. Lo que nexus deduce solo de verle corregir espera
   a repetirse. Distinguir lo mandado de lo intuido es lo que evita que la lista
   de «qué has aprendido» se llene de ruido sin dejar fuera lo que sí se pidió.

3. **Si la corrección delata un fallo de código, se dice y NO se aprende.** Si la
   frase llega a la skill correcta y es esa skill la que se comporta mal, una
   regla no arregla nada: lo tapa, y nadie lo ve nunca. nexus avisa de que eso es
   un fallo. Cuesta que la molestia siga hasta que se arregle de verdad, y es
   coherente con lo único que este proyecto no negocia: no fingir.

4. **Antes de que las reglas de `valor` toquen nada, las listas salen del
   código.** `_ROOM_WORDS`, `_NO_ES_PROGRAMA` y `_PORT_HINTS` se mueven a
   `umbrales.json` — ya figuraban como deuda en `estado.md` — porque son justo
   las que más han fallado y no se puede aprender sobre lo que está a fuego. Esto
   añade trabajo por delante y ataca la causa, no el síntoma.

### Sigue abierta

- **¿Qué gana cuando una actualización del canal choca con una regla
  aprendida?** Es de 007 y allí se decide. Lo que 004 sí fija, y 007 hereda: lo
  aprendido es local y del usuario, y **jamás se sube**.

## Criterios de éxito

- [ ] Una corrección real del dueño («no, te he dicho esto») genera una regla
      **propuesta**, sin cambiar nada por su cuenta.
- [ ] «qué has aprendido» lista las propuestas con la frase que las originó, y
      solo se aplican las aprobadas.
- [ ] Ninguna regla activa cambia el dueño de ninguna de las 244 órdenes
      prometidas. Verificado ejecutando `quien_atiende()`, no razonando.
- [ ] Al menos tres de los once fallos del 03/08 se resuelven **aprendiendo**, en
      un barrido contra nexus en marcha, sin editar una línea de `skill.py`.
- [ ] Borrar el almacén devuelve el comportamiento exacto de fábrica.
- [ ] `run_all.py` verde con las suites nuevas registradas.
- [ ] Ningún fichero `.py` es escrito por nexus. Comprobado por una suite.
