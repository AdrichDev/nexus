# Especificación: enrutado-aprendido

## Propósito

**Dónde** participan las reglas activas en la decisión. Es la pieza que convierte
el riesgo de que una regla aprendida le robe una frase a una skill en algo
imposible por construcción, en vez de en algo que haya que vigilar.

`brain.quien_atiende()` (`backend/core/aplicacion/brain.py:372-403`) refleja el
orden real de `process`: charla → respuesta a pregunta pendiente → queja de
negación → memoria explícita → router → meta-queja → planificador. Las reglas
aprendidas entran en el **último hueco**, el que hoy cae al planificador. Ese es
todo el terreno que se les concede.

El precio queda declarado: corregir un enrutado **equivocado** —no ausente— sigue
siendo trabajo del dueño, no de la máquina.

## Requisitos

### Requisito: Invariante de posición — las reglas van detrás de todo

Las reglas de enrutado activas DEBEN consultarse en `quien_atiende()` y en
`process` **después** de `skills_loader.route()` y **después** de
`_META_QUEJA_RX`, e inmediatamente antes de caer al planificador. Una regla
aprendida NO DEBE evaluarse antes de ningún atajo ni antes del router.

Consecuencia directa y buscada: una regla aprendida solo puede ocupar el hueco
que hoy cae al planificador, así que **estructuralmente no puede quitarle una
frase a una skill que ya la atiende**, ni a los atajos de charla, queja o
memoria.

#### Escenario: Una frase que ya atiende una skill no se ve afectada
- GIVEN «apaga la tele» devuelve `skill:domotica/tv_off`
- WHEN se activa una regla cuyo patrón también casaría con esa frase
- THEN `quien_atiende("apaga la tele")` sigue devolviendo `skill:domotica/tv_off`

#### Escenario: Una queja sigue siendo una queja
- GIVEN una frase que hoy devuelve `queja`
- WHEN hay reglas activas cuyo patrón casaría con ella
- THEN sigue devolviendo `queja`, porque la corrección es la señal y no puede
  perderse

#### Escenario: Un atajo previo gana siempre
- GIVEN una frase que devuelve `charla`, `memoria` o `queja`
- WHEN se evalúa con cualquier conjunto de reglas activas
- THEN el atajo previo se la queda igual que antes

### Requisito: `quien_atiende()` declara el atajo nuevo

`quien_atiende()` DEBE devolver un valor propio para las reglas aprendidas, con
la forma `regla:<id>`, ampliando el contrato documentado
(`charla | queja | memoria | skill:carpeta/intent | planificador`). Ese valor DEBE
permitir recuperar el `destino` real de la regla para inspeccionarlo. La suite
`tests/test_regresion_conversacion.py` DEBE poder ver el atajo nuevo, tal y como
exige la propia función.

#### Escenario: Frase atendida por una regla
- GIVEN una regla activa con id conocido para «cierra el navegador»
- WHEN se llama a `quien_atiende("cierra el navegador")`
- THEN devuelve `regla:<id>` con ese id
- AND el destino declarado por esa regla es el `carpeta/intent` aprobado

#### Escenario: La transición permitida es una y solo una
- GIVEN el resultado de `quien_atiende()` para cada frase del corpus con el
  almacén vacío
- WHEN se activa cualquier conjunto de reglas y se repite el barrido
- THEN toda frase que cambia lo hace de `planificador` a `regla:<id>`
- AND ninguna frase pasa de `skill:…`, `charla`, `queja` o `memoria` a otra cosa

### Requisito: Sin reglas activas, comportamiento idéntico al de fábrica

Con el almacén vacío o con todas las reglas en `propuesta` o `revertida`,
`quien_atiende()` y `process` DEBEN comportarse exactamente igual que antes de
este cambio, sin ninguna diferencia observable.

#### Escenario: Almacén vacío
- GIVEN `data/reglas_aprendidas.json` no existe
- WHEN se barre el corpus completo con `quien_atiende()`
- THEN el resultado es idéntico al del comportamiento de fábrica, frase a frase

#### Escenario: Todas las reglas revertidas
- GIVEN todas las reglas del almacén están en `revertida`
- WHEN se barre el corpus
- THEN el resultado es idéntico al del almacén vacío

### Requisito: Orden determinista entre reglas activas

Cuando varias reglas activas casan con la misma frase, DEBE ganar la de
activación más reciente. El resultado NO DEBE depender del orden de lectura del
fichero, del sistema de ficheros ni del orden de inserción en un diccionario:
dos ejecuciones con el mismo almacén DEBEN dar el mismo resultado.

#### Escenario: Dos reglas casan con la misma frase
- GIVEN dos reglas activas cuyo patrón casa con la misma frase, activadas en
  fechas distintas
- WHEN se llama a `quien_atiende()` con esa frase
- THEN gana la activada más recientemente, de forma repetible

#### Escenario: Repetibilidad
- GIVEN el mismo almacén de reglas
- WHEN se barre el corpus dos veces en procesos distintos
- THEN ambos barridos devuelven exactamente lo mismo

### Requisito: El planificador sigue siendo el respaldo

Si ninguna regla activa casa, `quien_atiende()` DEBE devolver `planificador`,
igual que hoy. Este cambio NO DEBE eliminar ni reducir el respaldo del
planificador para las frases que nadie atiende.

#### Escenario: Frase que no casa con nada
- GIVEN una frase que ninguna skill ni ninguna regla activa atiende
- WHEN se llama a `quien_atiende()`
- THEN devuelve `planificador`

### Requisito: Una regla `valor` no enruta

Una regla de tipo `valor` NO DEBE participar en la decisión de quién atiende una
frase. Solo sobreescribe valores ya declarados en la capa de sobreescritura sobre
`config/umbrales.json`. Activar reglas `valor` NO DEBE cambiar el resultado de
`quien_atiende()` para ninguna frase del corpus.

#### Escenario: Activar una regla de valor no mueve a nadie
- GIVEN se activa una regla `valor` sobre un umbral declarado
- WHEN se barre el corpus con `quien_atiende()` antes y después
- THEN el resultado es idéntico frase a frase

### Requisito: Las listas salen del código antes que las reglas de valor

Ninguna regla `valor` DEBE poder tocar una lista o un umbral que siga escrito a
fuego en un `.py`. Las listas señaladas por el dueño —`_ROOM_WORDS`
(`skills/domotica/skill.py:1677`), `_PORT_HINTS` (`skills/domotica/skill.py:506`)
y `_NO_ES_PROGRAMA` (`skills/system_pc/skill.py:43`)— DEBEN estar declaradas en
`config/umbrales.json` antes de que ninguna regla `valor` las alcance. Ese
traslado es un **cambio aparte** y una dependencia previa de esta capacidad; aquí
solo se fija la condición.

#### Escenario: Regla de valor sobre una lista todavía a fuego
- GIVEN `_ROOM_WORDS` sigue escrita en `skills/domotica/skill.py`
- WHEN se propone una regla `valor` sobre las palabras de habitación
- THEN falla la puerta de existencia porque esa clave no está declarada en la
  capa de sobreescritura
- AND la respuesta explica que primero hay que sacar la lista del código

### Requisito: El módulo del aprendizaje respeta las capas

El módulo nuevo DEBE colocarse en una capa de `backend/core/` que
`tests/test_capas_backend.py` acepte, y DEBE registrarse en la lista `CAPAS` de
esa suite y en `backend/core/CAPAS.md`. La parte que necesita
`brain.quien_atiende()` —la puerta de no robo y la consulta de reglas— pertenece
a la capa de aplicación o recibe la función de decisión desde fuera; el contrato
y el almacén NO DEBEN importar de `aplicacion/`.

#### Escenario: Suite de capas tras añadir el módulo
- GIVEN los módulos nuevos de este cambio
- WHEN se ejecuta `tests/test_capas_backend.py`
- THEN pasa sin nuevas excepciones aceptadas

#### Escenario: Suites nuevas registradas
- GIVEN las suites nuevas de este cambio
- WHEN se inspecciona la tupla de suites de `tests/run_all.py`
- THEN todas figuran en ella, porque una suite no registrada nunca se ejecuta
