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
2. **RDD se activó, sirvió, y se atascó.** Revisó el apagado de las TVs con las
   cuatro lentes y cazó dos cosas de verdad: que el interruptor podía encender
   al apagar, y la regresión del pronombre que los tests no vieron. Ambas
   corregidas.

   Pero **no llega a emitir el recibo**. `gentle-ai` 2.2.4 no sabe calcular la
   transición siguiente cuando la revisión está en `correction_required`, y esa
   es justamente la única puerta: `finalize` la exige, `review start` se declara
   bloqueado, y `recover` e `invalidate` rechazan ese estado. O sea que corregir
   lo que la revisión te pide es lo que te deja atrapado.

   Aislado con una sola variable: con `--projection staged` la misma orden
   funciona, con `workspace` revienta. Descartados el binario viejo, la ruta con
   espacios y un lineage huérfano. La evidencia completa está en engram. Los
   commits de esa tanda van **sin recibo**, a propósito.

**Google ya NO es un bloqueante** (03/08/2026). Aquí figuraba como pendiente de
reautorizar, y era falso: el token está autorizado desde el 02/08 a las 23:59
con los cinco permisos, incluido Drive. Comprobado ejecutando —Gmail contesta
«0 sin leer · 223 en bandeja», Drive lista y Calendar devuelve los próximos
eventos— y comprobado también que el arranque **no** vuelve a pedir nada: la URL
de OAuth salió una sola vez, en el arranque que estaba haciendo la autorización.

Y el refresco automático funciona: forzando un token caducado (sobre una copia,
nunca sobre el real), `_get_creds()` lo renueva y **reescribe el fichero** con
la caducidad nueva. No hay llamadas de más.

## Sesión del 03/08 — lo que se hizo después

Todo verificado con Chromium sobre nexus real, no solo con tests.

- **El grafo de conocimiento**, rehecho. Una sola pantalla (antes había dos
  dibujando lo mismo), el sistema en el centro, árbol de carpetas plegable a la
  izquierda con el ancho ajustable, y **simulación de fuerzas como la de
  Obsidian**: arrastras un nodo y sus vecinos le siguen; lo sueltas y el grafo se
  recoloca. Las cuatro fuerzas se ajustan desde el ⚙ con los rangos de Obsidian.
- **La papelera salía en el grafo.** `NoteGraph` recorría `data/memory/` con
  `rglob()` y la papelera vive dentro. De 93 nodos, 22 eran conocimiento.
  Vaciada de verdad (con copia previa de las 47 notas que no la tenían).
- **El cerebro elegido se perdía al arrancar.** Dos causas: `test_dispositivos`
  escribía `llm_provider=ollama` en el `settings.json` REAL, y la verificación de
  arranque escribía el proveedor en disco aunque no fuera a guardarlo. Hay
  candado nuevo en `run_all.py`: fotografía los ajustes antes y compara al final.
- **El ejecutor interno no sale al chat**, pero sí devuelve el resultado.
- **Agenda**: calendario real con mes / semana / día.
- **Estado del equipo**: en pantalla completa hacía 9 columnas de 240 px.
- **El saludo se repetía** en cada apertura, a todas las ventanas y en voz alta.

## Sesión del 03/08 por la tarde — los pendientes, resueltos

Los cinco primeros puntos de la lista de abajo ya no están. Lo que se hizo:

### Las TVs se apagan (y cuando no, se dice)

La causa no estaba en el apagado: las **IPs guardadas habían caducado por DHCP**.
Encender iba por MAC, que no cambia; apagar iba por IP, que sí. Ahora la IP se
re-resuelve desde la MAC antes de actuar.

Debajo había algo peor: **Tizen acepta `KEY_POWEROFF` y no apaga**. La única
tecla que apaga es `KEY_POWER`, que es un interruptor y sobre una TV en reposo
la **enciende**. Por eso el interruptor solo se pulsa con el estado confirmado
`on`, leído de `device.PowerState`. Sin poder confirmarlo se manda la absoluta:
puede que no apague, pero jamás encenderá lo que estaba apagado.

Y se comprueba el resultado. `_samsung` devolvía `True` tras el envío —o sea
«salió», nunca «obedeció»— y el llamante escribía «Apagando» sin mirar nada.

### El volumen ya no adivina destino

«sube el volumen» iba a la tele y «pon el volumen al 50» al PC, y ninguna de las
dos cosas estaba decidida: salía del orden alfabético. Ahora **el destino lo
dice siempre quien da la orden**, y sin destino se pregunta.

Destino nuevo: **la aplicación**. «sube el volumen de spotify», «silencia
chrome». Y de paso se descubrió que **el volumen del PC no funcionaba**:
dependía de `nircmd` en el PATH, que no está puesto, así que respondía «Volumen
subido… en teoría». Ahora va por `pycaw` contra la Core Audio de Windows.

### Tres órdenes que no llegaban a nadie

«busca información sobre python», «crea una tarea» a secas (que ahora pregunta
el asunto en vez de crear una titulada «nueva») y «dame ideas para el regalo de
mi madre», que se lo llevaba `memory_graph` confundiendo el pronombre «de mí»
con el posesivo «de mi madre». Los separa la tilde.

### Lo que enseñó la revisión

El primer arreglo del pronombre era **demasiado bruto** —descartar si había
cualquier palabra detrás— y rompía «qué sabes de mí ahora». Los tests solo
cubrían las formas desnudas, por eso salieron verdes con la regresión dentro.

Y apagar la tele podía **tardar medio minuto**: sondeos en serie, uno duplicado
y ninguno con tope. Ahora los puertos se prueban a la vez, la sonda duplicada no
está y hay un límite total contado desde que entra la orden.

### nexus arrancaba con el Python equivocado

Lo más importante del día, y salió por casualidad. El volumen respondía «falta
pycaw» con pycaw instalado. El proceso que escuchaba en el 8177 era
`C:\Python314\python.exe`: **el Python del sistema, no el 3.12 del `.venv`**.

El `activate.bat` de un venv guarda la ruta **absoluta** con la que se creó, y
el nuestro sigue diciendo `D:\Adrian\22. Proyectos\WBKS\WABIKS\.venv` — el
nombre viejo del proyecto. Esa carpeta no existe, la activación falla, `PATH` se
llena con un directorio inexistente y `python` cae al del sistema.

**Por qué nadie lo notó:** el Python del sistema tiene `fastapi` y `uvicorn`
instalados, así que nexus arrancaba sin quejarse. Lo que declara
`requirements.txt` no era lo que corría, y cualquier dependencia nueva tenía el
mismo destino.

`run.bat` ya no depende de la activación: fija la ruta del ejecutable del venv y
la usa para arrancar y para cada `pip`.

Para diagnosticarlo, el comando que lo destapó:

```
netstat -ano | findstr ":8177 " | findstr LISTENING
Get-CimInstance Win32_Process -Filter 'ProcessId = <PID>' | Select ExecutablePath
```

Y al probar: **`python tests/run_all.py` usa el Python del sistema**. Para las
suites que dependen de las dependencias del proyecto hay que lanzar
`.venv\Scripts\python.exe tests\run_all.py`.

### El único test rojo del repo no era del código

`test_ingesta_documentos` llevaba días acusando al buzón de rechazar los `.pdf`.
El buzón no tenía nada: **el PDF del propio test estaba mal formado**, sin tabla
`xref` ni `startxref`. `read_any` lo rechazaba diciendo exactamente eso, que es
lo correcto — un lector que aceptase eso sería el defecto.

**La suite entera queda en verde**, 21 bloques sin un fallo. Antes de dar un
fallo por preexistente, conviene comprobar que el material de prueba es válido.

### Lo que salió de usarlo de verdad (03/08, tarde)

Adrián probó todo en el chat y mandó la conversación entera. Nueve fallos, y
ninguno lo habrían visto los tests:

- **Actuaba sobre la TV equivocada.** `_resolve_tv` no recibía la frase:
  devolvía la primera de la lista. «La de la habitación» encendía la del salón.
- **La de la habitación no se apagaba.** No publica `PowerState`, así que nunca
  se confirmaba «encendida» y nunca se usaba la única tecla que la apaga. La
  señal que faltaba la da **UPnP `GetMute` en el 9197**: 0 encendida, 1 en
  reposo. Medido con verdad conocida.
- **Hablaba de más.** Cuatro líneas para preguntar cuál de dos televisiones.
- **No se acordaba.** Le decías cuál, y a la orden siguiente volvía a preguntar.
- **«quítale el silencio» volvía a silenciar**, y la cadena decía ✔ sin hacer nada.
- **No callaba al escribir**, solo al pulsar el botón de hablar.
- **Los títulos guardaban la paja** («que dure del miércoles hasta que sea…»).
- **Los eventos de varios días no existían.**
- **No se podía borrar en el calendario por fecha**, y borraba sin preguntar.

**La lección**: todo esto pasó los tests. Lo cazó usarlo. Y varias respuestas
largas las había escrito yo el mismo día «por honestidad»: explicar el mecanismo
no es ser honesto, es no callarse.

### La segunda tanda, y el fallo que explica a los demás

Siguió probando y salieron seis más. Uno enseña más que el resto:

- **«apunta» se lo comía la memoria.** El cerebro tiene un atajo para guardar
  hechos («recuerda que…», «apunta que…») que corre **antes del router**, y su
  «que» era opcional. Así que «apunta la mentoría el jueves» nunca llegaba al
  tablero, ni «apunta el evento X» al calendario.

  **Y `test_lo_prometido` decía que sí llegaban.** Era verdad… del **router**.
  El router ni se ejecutaba.

  > Una prueba que mira un escalón por debajo de donde está el fallo
  > lo declara arreglado.

  Por eso ahora existe `brain.quien_atiende()`: responde **quién se queda** una
  frase, con los atajos por delante y en su orden, sin ejecutar nada. Y
  `tests/test_regresion_conversacion.py` comprueba **esa** decisión con las
  frases reales de estas dos tandas. Vigila además que no aparezca un atajo
  nuevo antes del router sin declararlo, que es como se coló este.

- **Borrar el día 5 es borrar lo que se VE ese día.** La agenda pinta el
  calendario de Google **y** las tareas del tablero; el borrado solo entendía
  uno. «No hay nada en tu calendario» era cierto y a la vez inútil.
- **El dictado no escribe los nombres propios.** Ahora se comparan los
  **sonidos**, no las letras. De regalo, deja de importar que un nombre guardado
  tenga una errata.
- **Contestar a «¿cuál?» es una orden.** Suelto no significa nada; pegado a la
  pregunta, sí. Ojo: **caduca con el mensaje siguiente**, o contamina todo lo que
  venga detrás — regresión propia, cazada en un barrido contra nexus real.
- `create_event` tenía los mismos dos fallos ya curados en el tablero: títulos
  con paja y sin rangos de varios días.

**Cómo se prueba esto de ahora en adelante**: suite (`run_all.py`), e2e
(`run_e2e.py`) **y un barrido de frases reales contra nexus en marcha**. Las dos
primeras estaban verdes mientras todo esto fallaba; la tercera es la que lo cazó.

## Dudas y pendientes anotados, no tocados

- **«dámelas»** a secas no llega a ningún sitio. El pronombre enclítico sin
  antecedente es genuinamente ambiguo; haría falta memoria de turno.
- **La voz del frontend** (ver arriba): el bloque que falta por extraer, y el
  modal de configuración que depende de él.
- **Trasladar `core/` a subcarpetas**: la regla está, el movimiento no.
- **El `.venv` sigue caducado por dentro**: los `.exe` de `Scripts` (`pip`,
  `bottle`…) llevan la ruta vieja embebida igual que el `activate.bat`.
  `run.bat` ya es inmune, pero la limpieza de fondo es recrearlo — la subrutina
  `:recreate_venv` está ahí, y reinstala todo desde `requirements.txt`.
- **El HUD pinta encendida una TV en estado ambiguo**: al no poder confirmar el
  apagado no se persiste «apagada». Deliberado: no dar por hecho lo que no se ha
  comprobado es justo lo que se arregló.
- **Credenciales de Instagram**: sigue siendo el único bloqueante de verdad.

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
