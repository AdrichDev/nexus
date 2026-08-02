# Estado de la sesión — 01/08 y 02/08 de 2026

Registro para retomar el trabajo. Se escribe aquí porque este documento sobrevive
en el repositorio.

## Dónde estamos

| Fase | Estado |
| --- | --- |
| 0 — ordenar la raíz | ✅ hecha (`ca865b0`) |
| 1 — auditar las 32 skills | ✅ hecha, 32 de 32 |
| 2 — componentizar el frontend | 🟡 **hecha a medias, y a propósito** |
| 3 — estratificar `backend/core/` | ✅ la regla, escrita y verificada |

**Nada está pusheado.** Todo son commits locales en `main`.

## Lo primero al volver

1. **Reiniciar nexus con `run.bat`.** Se han tocado skills y `skills_loader` solo
   lee las carpetas al arrancar.
2. Probar en el chat las órdenes nuevas: «cierra chrome», «dame ideas»,
   «hazme un guion», «pon el brillo al 80».

## Lo que se ha hecho hoy (02/08)

### Cerrar programas vuelve a ser una orden

En la Fase 1 se le había metido confirmación previa por considerarlo destructivo.
Era una lectura equivocada: «nexus, cierra esto» está hecho para que lo cierre.
**Retirada la confirmación.** Apagar y reiniciar sí la mantienen: ahí se pierde la
sesión entera.

La salvaguarda pasa a ser la puntería, no la pregunta: primero el nombre exacto
(con o sin `.exe`) y solo si no casa ninguno, la subcadena. Antes «cierra el
proceso code» se llevaba también `codecs_host`.

La respuesta no lleva PIDs y **varía entre seis frases**, porque es una orden que
se repite muchas veces al día.

### Órdenes que no llegaban

| Familia | Qué pasaba |
| --- | --- |
| **Cerrar programas** | «cierra chrome», «cierra spotify», «cierra el navegador», «cierra la calculadora» → **al planificador**. El patrón exigía decir «proceso» o «.exe» |
| **Abrir webs** | «abre marca.com» intentaba lanzar un programa llamado así. «ponme la web del as» se lo llevaba la **música** |
| **Aportar ideas** | **8 de 12** formas naturales al planificador: «dame ideas», «proponme ideas», «lluvia de ideas», «qué publico esta semana»… |
| **Guiones** | «hazme un guion» no existía: el tema era obligatorio |
| **Competencia** | Faltaba el singular «qué **hace** mi competencia» y la forma «compara **mi cuenta con** la competencia» |
| **Brillo** | `media/SKILL.md` llevaba tiempo mandándolo a Sistema/PC, y **Sistema/PC no tenía brillo** |
| **Facturas** | «ver facturas» **reventaba** con `UndefinedColumn`: pedía una columna `status` que no existe |

Cada arreglo lleva su límite. «dame ideas» a secas es contenido, pero «dame ideas
de cena» no: si hay complemento, tiene que ser del dominio. El brillo de una
bombilla sigue siendo de `domotica`. Y `_NO_ES_PROGRAMA` protege lo que es de
otras skills al cerrar.

### La e2e no se ejecutaba. Nunca.

`run_e2e.py` imprime `▸` al anunciar cada flujo. La consola de Windows abre en
cp1252, así que reventaba con `UnicodeEncodeError` **antes de la primera
comprobación**. La línea está desde el **primer commit del repo** (`9be234f`,
30/07): no se había ejecutado jamás.

Por eso aquí figuraba «un fallo de la e2e en el indicador de Multitarea,
preexistente». **Ese fallo no existe.** Resultado real: **9/9 flujos verdes**.

Las fases 0 y 1 sí tenían red: `run_all.py`, que no incluye la e2e y siempre ha
funcionado. Cubre backend y skills. La e2e cubre el HUD, que es lo que empieza en
la Fase 2 — y por eso se arregló antes de tocar una línea.

## Fase 2 — el frontend

`command.js` pasa de **3.624 a 1.959 líneas**. Módulos ES nativos: sin
empaquetador, sin framework y sin paso de compilación.

```
core/dom.js      41   $, $$, esc, linkify, api, flash, mdToHtml
core/state.js    28   el estado compartido
core/catalog.js  68   CATALOG (32 skills) y BOOT
core/log.js      24   el registro del Monitor
core/nav.js      18   cambiar de vista sin importar el router
core/orders.js   19   dar una orden sin importar el arranque
ui/widgets.js    52   ovCard, gauge, kpi, qc, nsBtn, orbHTML
views/devices.js    504   CASA: dispositivos, Home Assistant, mando
views/reels.js      500   Instagram y competencia
views/knowledge.js  242   grafo de nodos y ventanitas flotantes
views/contentos.js  242   plan, ideas, salud, aprendizajes
modals/link.js      145   vincular el móvil: QR y túnel
```

**Los tres huecos con registro** (`nav`, `log`, `orders`) son la pieza que hizo
esto posible. Un modal que necesita `render()` no puede importar el router,
porque el router importa todas las vistas. En vez de eso, el router deja su
función al arrancar y los demás la piden a ciegas. Cinco líneas cada uno, y
convierten un ciclo en una dependencia de una sola dirección.

### Lo que NO se ha extraído, y por qué

**La voz se queda en `command.js`.** Es el único bloque grande que no sale
limpio: exporta quince símbolos y uno de ellos (`_ttsAudio`) es una variable que
el resto del fichero **reasigna**, cosa que un import no permite. Separarla exige
rediseñar su interfaz, y eso ya no es componentizar: es reescribir lo que
funciona, que es justo lo que el plan de esta fase prohíbe.

Lo que queda dentro es el armazón: arranque, WebSocket, router, chat, voz, AI
Core, hardware, memoria, agenda, tablero y el modal de configuración. **El modal
de configuración sí saldría** (267 líneas) en cuanto la voz esté resuelta: es lo
único que lo ata, por `startVoiceTest`/`endVoiceTest`.

### Dos redes nuevas

- `tests/test_frontend_modulos.py` — comprueba en **un segundo y sin navegador**
  que todo símbolo usado está importado, que los imports apuntan a algo que
  existe y lo exporta, y que no hay módulos huérfanos. Nació de un fallo real
  (`reels.js` usaba `$$` sin importarlo) que solo cazaba la e2e, en dos minutos.
- `tests/_frontend_js.py` — `js_hud()` concatena todo `frontend/js`. Catorce
  comprobaciones leían `command.js` directamente y se pusieron rojas al mover
  código sin que nada dejara de funcionar. Ahora son inmunes a los cortes que
  quedan.

## Fase 3 — las capas del backend

`backend/core/` son 43 módulos y 15.000 líneas en una carpeta plana. Las capas
están escritas en `backend/core/CAPAS.md` y las verifica
`tests/test_capas_backend.py`:

```
aplicación → dominio → infraestructura → común
```

**El test corrigió mi primera clasificación**, que es para lo que sirve. Seis
dependencias iban del revés y en cinco casos el error era mío:

- `brain` y `voice_cycle` **no son dominio**: no tienen reglas de negocio,
  deciden **qué se ejecuta**. Igual `wake` y `hotkey`, que son puntos de entrada.
- `publicvoice` **no es infraestructura**: no habla con nadie, es una regla de
  presentación, y la usa `events`, que está por debajo de todo.
- `pm` **no es infraestructura**: convierte lo que hablas en tareas.

Con la clasificación correcta: **235 comprobaciones, cero incumplimientos**.

Los **cuatro ciclos** quedan a la vista con nombre y motivo en la lista de
excepciones (`llm↔llm_runtime`, `llm↔selflearn`, `memory↔rag`,
`brain↔telegram_bridge`). El test comprueba además que **la excepción sigue
haciendo falta**, para que la lista no acabe siendo un cajón.

### Lo que la Fase 3 NO hace, y es deliberado

**No mueve los ficheros a subcarpetas.** 85 ficheros importan de `backend.core`,
algunos por `importlib` con el nombre en una cadena. Reescribir todo eso de una
tirada es exactamente el big-bang que el plan prohíbe. La regla ya se cumple y ya
se verifica; el traslado va por grupos y puede esperar.

## Cómo se ha probado la app

- **`run_all.py`**: 21 suites, TODO VERDE. Tres nuevas: `test_frontend_modulos`,
  `test_capas_backend`, `test_lo_prometido`.
- **`run_e2e.py`**: 9/9 flujos con el HUD real en Chromium. Cero errores de
  consola, cero peticiones fallidas.
- **Barrido de lo prometido**: las **244 órdenes** que anuncian los 32 `SKILL.md`
  llegan todas a una skill. Ahora es suite permanente (`test_lo_prometido.py`).
- **Ejecución real de los handlers**: 148 responden bien, 93 se saltaron por
  seguridad (borrar, apagar, enviar, abrir ventanas). El único fallo fue el de
  las facturas, ya arreglado.
- **Competencia e ideas, ejecutando**: ideas devuelve cinco ideas reales del
  modelo; los guiones salen escritos; competencia, sin token, contesta «no puedo
  consultar la Graph API, me falta el token, y no me lo voy a inventar» — que es
  el comportamiento acordado.

## Bloqueantes que siguen abiertos

1. **Credenciales de Instagram.** Sin ellas no hay datos propios ni de
   competencia. Es el primer dominó de todo lo que queda de Content OS.
2. **Reautorización de Google.** El scope de Drive cambió; la primera orden de
   Drive abrirá el navegador una vez.
3. **RDD no es operable desde Claude Code.** Desactivado a petición tuya.

## Dudas y pendientes anotados, no tocados

Lo que he visto y he preferido dejarte a ti, porque no era determinante:

- **«sube el volumen» va a la tele** (`domotica/tv_volume`), no al PC, porque
  `domotica` va antes por orden alfabético. Pero «pon el volumen al 50» sí va al
  PC. Es incoherente, y decidir cuál gana es tuyo: cambiarlo puede romper el
  control de la tele.
- **«dame ideas para el regalo de mi madre»** acaba en `memory_graph/list_knowledge`.
  Content OS lo rechaza bien; el que lo caza de más es `memory_graph`. Preexistente.
- **«crea una tarea»** y **«busca información sobre python»** caen al
  planificador. Parecen órdenes normales que deberían tener dueño.
- **«dámelas»** a secas no llega a ningún sitio. El pronombre enclítico sin
  antecedente es genuinamente ambiguo; haría falta memoria de turno.
- **La voz del frontend** (ver arriba): el bloque que falta por extraer, y el
  modal de configuración que depende de él.
- **Trasladar `core/` a subcarpetas**: la regla está, el movimiento no.

## Deuda anterior, sigue en pie

- El prefijo de numeración de facturas no es agnóstico, pero cambiarlo rompe la
  serie ya emitida.
- La tabla de fabricantes por MAC de `domotica` es heurística con entradas dudosas.
- «recuérdame en el proyecto que…» va a `coach/remind`; la frase es ambigua.
- `_ROOM_WORDS`, `_GENERIC_NAMES` y `_PORT_HINTS` de `domotica` siguen en el
  código en vez de en `umbrales.json`.
- `_probe_brain` de `hermes` gasta una llamada de pago en cada diagnóstico.

## Reglas que quedan establecidas

- Los comentarios en `skill.py` dicen **qué hace el código**. La historia va en el
  mensaje del commit.
- **Nada de datos personales** en código, configuración publicada ni tests.
- El `SKILL.md` es **lo que lee el agente para decidir**, y lo que promete tiene
  que activarse de verdad: `test_lo_prometido.py` lo comprueba.
- **Probar el handler, no solo el enrutado.** El `AttributeError` de los guiones
  solo apareció ejecutando.
- Skill nueva que reclame «cierra \<sustantivo\>»: hay que añadir ese sustantivo a
  `_NO_ES_PROGRAMA` de `system_pc`, o se lo queda él.
