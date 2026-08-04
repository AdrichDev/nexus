# Especificación: aprendizaje-correcciones

## Propósito

Hoy una corrección se detecta y se contesta, y ahí muere. `_NO_ACCION_RX` y
`_META_QUEJA_RX` (`backend/core/aplicacion/brain.py:278-294`) existen desde el
bucle de correos del 25/07 y solo sirven para **no** ejecutar nada. La tarde del
03/08 salieron once fallos de este tipo con la suite entera en verde, y cada uno
se arregló a mano editando un `skill.py`.

Esta especificación convierte esa queja en una **regla propuesta**, con la frase
que la originó pegada, y —tan importante como lo anterior— define cuándo NO hay
nada que aprender porque lo que la corrección delata es un fallo de código.

## Requisitos

### Requisito: Una corrección genera una propuesta, jamás un cambio

Cuando `brain.quien_atiende()` decide `queja` para un mensaje, el sistema DEBE
registrar la señal de corrección y MAY generar una regla en estado `propuesta`.
NO DEBE cambiar ningún comportamiento, ni activar nada, ni reejecutar la skill
que se acaba de corregir.

#### Escenario: Corrección durante una conversación
- GIVEN el operador dice «no, te he dicho que cierres chrome»
- WHEN el cerebro procesa el mensaje
- THEN `quien_atiende()` devuelve `queja` y nexus responde sin ejecutar nada
- AND si hay materia para una regla, queda en estado `propuesta`
- AND ninguna decisión de enrutado cambia en ese mismo turno

#### Escenario: La corrección no interrumpe el trabajo
- GIVEN se genera una regla propuesta
- WHEN nexus responde a la corrección
- THEN no pregunta si aplicarla ni abre ninguna confirmación en ese momento

### Requisito: Sin frase corregida y destino pretendido no hay propuesta

Una propuesta DEBE apoyarse en dos cosas identificables: la **frase que se
enrutó mal** (el turno anterior del operador, no la queja) y el **destino
pretendido** (`carpeta/intent` existente). Si cualquiera de las dos no se puede
determinar, NO DEBE crearse ninguna propuesta; nexus DEBE decirlo y pedir la
forma explícita «aprende que cuando diga X hagas Y».

#### Escenario: Queja suelta sin turno anterior útil
- GIVEN el primer mensaje de la sesión es «por qué has hecho eso»
- WHEN se procesa
- THEN no se crea ninguna propuesta
- AND la respuesta invita a enseñárselo con la fórmula explícita

#### Escenario: Destino no deducible
- GIVEN la frase corregida cayó al planificador y la queja no señala qué debía
  pasar
- WHEN se evalúa la señal
- THEN no se crea propuesta y se pide el destino, sin adivinarlo

### Requisito: La evidencia depende de quién lo diga

Una corrección **mandada** por el dueño con la fórmula explícita de `_TEACH_RX`
(«aprende que cuando diga X hagas Y») DEBE generar una propuesta a la primera:
es una orden, no una sospecha. Lo que nexus **deduce** observando correcciones
DEBE repetirse al menos `N` veces antes de proponerse, con `N` leído de
`config/umbrales.json` (bloque `aprendizaje`), nunca a fuego. `evidencia` DEBE
registrar cuál de los dos caminos fue (`mandado` o `deducido`) y cuántas
ocurrencias distintas lo sostienen.

Pasar el umbral de evidencia NO exime de pasar las cinco puertas de
`aprendizaje-validacion`.

#### Escenario: Orden explícita del dueño
- GIVEN el dueño dice «aprende que cuando diga cierra el navegador hagas cierra
  chrome»
- WHEN se procesa
- THEN se crea una propuesta con `evidencia.origen: mandado` y una sola
  ocurrencia
- AND aparece en la siguiente tanda de aprobación

#### Escenario: Corrección deducida por debajo del umbral
- GIVEN el umbral configurado es 2 y esta forma de decirlo se ha corregido una
  sola vez
- WHEN se evalúa la señal
- THEN se guarda la ocurrencia y NO se crea ninguna propuesta

#### Escenario: La misma corrección repetida en el mismo turno no cuenta dos veces
- GIVEN el operador repite la misma queja dos veces seguidas sobre el mismo turno
- WHEN se contabiliza la evidencia
- THEN cuenta como una sola ocurrencia

### Requisito: Distinguir un hueco de enrutado de un fallo de código

Antes de proponer nada, el sistema DEBE ejecutar `brain.quien_atiende()` sobre
la **frase corregida** y decidir según lo que devuelva:

| Devuelve | Lectura | Qué hace nexus |
| --- | --- | --- |
| `planificador` | Hueco de enrutado: nadie la atiende | Candidata a regla `enrutado` |
| `skill:X/Y` y `X/Y` es el destino pretendido | La frase SÍ llega a quien debe; el fallo está dentro de la skill | Lo dice y NO aprende |
| `skill:X/Y` y el destino pretendido es otro | Enrutado equivocado, no ausente | Lo dice y NO aprende (fuera de alcance) |
| `charla`, `queja` o `memoria` | Se la queda un atajo previo al router | Lo dice y NO aprende |

Solo el primer caso DEBE generar una propuesta de enrutado. En los otros tres,
nexus DEBE explicar cuál es el caso y por qué una regla no lo arreglaría. Una
regla que tapa un fallo de código lo esconde para siempre, y este proyecto no
finge.

#### Escenario: La frase llega a la skill correcta y la skill se comporta mal
- GIVEN «apaga la tele» ya devuelve `skill:domotica/tv_off` y el operador corrige
  porque apagó el aparato equivocado
- WHEN se evalúa la señal
- THEN no se crea ninguna propuesta
- AND la respuesta dice que la frase llega bien y que el fallo está en la skill,
  no en el enrutado

#### Escenario: Hueco real de enrutado
- GIVEN «cierra el navegador» devuelve `planificador`
- WHEN se evalúa la señal con evidencia suficiente
- THEN se crea una propuesta de tipo `enrutado` hacia el intent existente que el
  dueño señaló

#### Escenario: Un atajo previo se queda la frase
- GIVEN la frase corregida devuelve `memoria` porque un atajo la captura antes
  del router
- WHEN se evalúa la señal
- THEN no se crea propuesta
- AND se explica que las reglas van detrás del router y no pueden recuperar esa
  frase

### Requisito: El perfil del operador propone, no decide

`backend/core/dominio/selflearn.py` MAY aportar candidatos a partir de lo que
observa, y el LLM MAY redactar la propuesta. Ninguno de los dos DEBE activar
nada: **el modelo puede proponer una regla; solo código determinista puede
activarla**. Una propuesta de origen LLM DEBE quedar marcada como tal en
`evidencia` y pasar exactamente las mismas puertas.

#### Escenario: Propuesta sugerida por el modelo
- GIVEN el destilado del perfil sugiere una forma nueva de pedir algo
- WHEN se convierte en candidata
- THEN nace en estado `propuesta`, marcada como sugerida por el modelo
- AND no cambia ninguna decisión hasta que el dueño la apruebe y pase las puertas

### Requisito: Nunca proponer escribir una skill

El sistema NO DEBE proponer jamás crear, editar o generar una skill, un intent
nuevo o cualquier fragmento de código, aunque la corrección apunte a algo que
ninguna skill sabe hacer.

#### Escenario: La corrección pide algo que nadie sabe hacer
- GIVEN el operador corrige pidiendo una capacidad que ninguna skill declara
- WHEN se evalúa la señal
- THEN no se crea propuesta
- AND la respuesta dice claramente que eso necesita una skill nueva, que nexus no
  escribe
