# SPECS v22 — integración opcional con Engram (memoria de proyecto/código)
_2026-07-24 · Feature nueva (no un arreglo de queja): skill + puente HTTP + auto-gestión de
servidor, con su criterio de aceptación y el RESULTADO de la validación. Suite completa:
`python tests/run_all.py` → TODO VERDE, **867 checks**. Consta de TRES partes, cada una con
su ciclo de revisión opus + QA sonnet: (A) nexus enganchado a Engram por HTTP, (B) Hermes
enganchado a Engram por MCP nativo — porque Adri pidió que **«tanto Hermes como NEXUS estén
enganchados a Engram»** — y (C) la INSTALACIÓN del binario de Engram como un paquete más del
instalador de nexus (run.bat y nexus.exe), tras pedir Adri que **«engram sea uno de los
paquetes que el instalador tiene que instalar»** y que **«pueda instalarse también con el
.exe»**.

Parte A — revisión opus: 2 hallazgos confirmados (fuga de "nexus" en la captura de `hecho`,
y un test que no ejercitaba de verdad lo que decía probar), corregidos y cubiertos con test;
QA sonnet: NO APTO en la primera pasada — encontró que el arreglo de opus dejaba dos
variantes más de la misma fuga sin cerrar ("proyecto DE nexus", puntuación antes de "que") y
una inconsistencia en la regex de búsqueda; corregidos y cubiertos con test; 2ª pasada → APTO.

Parte B — revisión opus: 4 hallazgos confirmados de corrupción de YAML en la provisión del
config.yaml de Hermes (indentación de 4 espacios que absorbía servers, BOM que duplicaba la
clave, falso positivo con `engram:` anidado, comentario en la cabecera); corregidos y
cubiertos + un blindaje extra para tabs. QA sonnet: NO APTO en la primera pasada — encontró
2 huecos más de la MISMA clase (comentario en columna 0 dentro del bloque, y sobrescritura
sin backup si el fichero existe pero no se puede leer); corregidos y cubiertos con test; 2ª
pasada → APTO._

## Por qué

**Pregunta de Adri:** *"Verias propicio integrar engram en nexus?"* → tras aclarar cuál de
los varios proyectos llamados "Engram" (hay al menos 8 distintos en GitHub) confirmó
[Gentleman-Programming/engram](https://github.com/Gentleman-Programming/engram) — un
binario Go, MIT, con servidor HTTP local + MCP + CLI + TUI, agnóstico de herramienta
(Claude Code, Cursor, Codex, Windsurf...). Confirmó con *"Lo que quiero seria implementar
engram dentro de nexus"* y, ante dos preguntas de alcance: **solo memoria de
proyecto/código** (no memoria personal — esa se queda intacta en `memory.py`/`profile.py`,
Postgres+RAG+grafo) y **NEXUS lo gestiona solo** (auto-detecta, auto-arranca,
auto-repara — mismo trato que ya recibe el gateway de Hermes).

## Qué se construyó

**`backend/core/engram_bridge.py`** (nuevo) — puente HTTP contra `engram serve`
(127.0.0.1:7437 por defecto). Contrato verificado A MANO contra el binario real v1.20.0
(no adivinado — se descargó y se probó en sandbox hasta encontrar los endpoints reales):
`GET /health`, `POST /sessions {id,project}` (idempotente), `POST /observations
{session_id,title,content,type,project}` (requiere sesión previa), `GET /search?q=&project=`
(devuelve `null`, NO `[]`, sin resultados — cubierto explícitamente), `GET
/context?project=`, `GET /observations?project=` (para contar). Guarda siempre bajo un
proyecto fijo `"nexus"` y una sesión estable reutilizada. Ciclo de vida del servidor
calcado del de Hermes: `installed()` (detecta el binario: ⚙ `engram_exe` → PATH → rutas
típicas de `go install`), `alive_cached()` (caché de 60s), `ensure_up()` (arranca el
proceso oculto en Windows si hace falta, log en `data/engram_serve.log`, no relanza en
ráfaga si ya lo intentó hace <45s, degrada a `False` sin romper nada si no está instalado o
`engram_autostart` está desactivado). `count()` usa la caché en vez de arrancar el servidor
solo para contar.

**`skills/engram/skill.py`** (nueva skill) — 4 intents por regex: `status` («está engram
conectado», «diagnostica engram»), `save` («recuerda/apunta/anota/guarda en el
proyecto/código/engram/nexus que...», con tipo opcional `bug`/`decisión`/`arquitectura`/
`feature`), `context` («contexto del proyecto», «qué sabe engram»), `search` («qué se
decidió sobre...», «busca en el proyecto...»). El ancla `proyecto|código|engram|nexus` es
OBLIGATORIA en `save` — decisión deliberada para blindar contra colisión con la skill de
memoria PERSONAL (que usa los mismos verbos «recuerda»/«apunta»/«guarda» para cosas del
usuario, no del proyecto).

**`backend/core/config.py`** — 3 ajustes nuevos en ⚙, todos con valor por defecto seguro:
`engram_autostart` (True), `engram_exe` (vacío = autodetectar), `engram_port` (7437).

**`skills/engram/SKILL.md`** (nueva) — documentación en el estilo ya establecido: qué es,
por qué es distinto de la memoria personal, ejemplos de órdenes, cómo se gestiona el
servidor, instalación (con el aviso conocido de falso positivo de antivirus en el binario
prebuilt — `go install` lo evita).

**✔ VALIDADO:** 101 checks en `tests/test_engram.py` — detección del binario (⚙/PATH/rutas
típicas), caché de 60s, las 4 ramas de `ensure_up()` (ya vivo, no instalado, autostart
desactivado, arranca+espera+NO relanza en ráfaga — con el mock corregido para que de verdad
ejercite la guarda), `save`/`search`/`context`/`count` con sus casos límite (tipo inválido
→ `note`, HTTP 404/500, excepción de red, `null` de la API tratado como lista vacía, límite
de resultados respetado, `count()` sin arrancar el servidor), `status_sync` puro sin red,
enrutado completo de las 4 intents + `_map_tipo`, contrato duro de anti-colisión con TODAS
las skills cargadas (frases personales como «recuerda que mi madre se llama Pili», «quién
soy», «apunta en la memoria que odio el cilantro» siguen yendo a `memory_graph`, nunca a
`engram`), comportamiento de `handle()` para las 4 intents mockeando `engram_bridge`
directamente, y los 3 valores por defecto en `⚙`.

## Revisión y endurecimiento (opus + sonnet, dos pasadas)

**1ª pasada (opus) — 2 hallazgos confirmados:**
1. La regex de `save` capturaba mal cuando el usuario nombraba el proyecto: *"apunta en el
   proyecto nexus que el login falla"* guardaba `hecho="nexus que el login falla"` en vez
   de `"el login falla"` — el ancla solo casaba UNA palabra y "nexus" se colaba dentro del
   contenido guardado (dato compartido con Claude Code/Cursor/etc. vía Engram). Corregido
   añadiendo un grupo opcional tras el ancla para absorber el nombre del proyecto.
2. El test `test_ensure_up_lanza_y_espera_y_no_relanza_en_rafaga` afirmaba probar la guarda
   anti-ráfaga (<45s) pero el mock de `_alive` devolvía `True` para siempre tras la 2ª
   llamada — la 2ª invocación de `ensure_up()` pasaba por el atajo de `alive_cached==True`
   sin llegar nunca a ejercitar la guarda real. Falso verde. Corregido: el mock vuelve a
   `False` tras esa 2ª llamada, forzando que la guarda de verdad se ejecute (confirmado con
   nuevas aserciones sobre cuántas veces se llama a `/health`).

Además opus verificó y descartó como NO-bug: un supuesto `KeyError` en `ctx["settings"]`
(el operador ternario perezoso nunca llega a evaluarlo sin settings), el uso de
`alive_cached` en `count()` (correcto: fuerza un ping real si la caché está fría), y la
forma del argumento `serve [port]` (confirmado posicional contra el `README.md` real del
proyecto, no `--port`). Señaló una condición de carrera benigna (dos arranques concurrentes
sin lock) idéntica a la ya existente y aceptada en `skills/hermes/skill.py` — se dejó
igual, por consistencia con el patrón ya establecido en el proyecto.

**2ª pasada (sonnet, NO APTO en la primera vuelta) — el arreglo de opus no cerraba el bug
del todo, 3 variantes más de la misma fuga:**
1. *"recuerda en el proyecto DE nexus que..."* (posesivo natural en español) seguía
   dejando `hecho="de nexus que..."` — el grupo opcional de opus solo cubría "nexus"
   pegado directamente, no con "de" en medio.
2. Puntuación ANTES de "que" — *"...proyecto nexus, que..."* / *"...proyecto nexus:
   que..."* dejaba `hecho="que..."` con la palabra "que" pegada al principio — el orden de
   la regex asumía que "que" siempre iba antes que la puntuación.
3. La regex de `search` exigía `\s+` literal tras el ancla, así que *"busca en el
   proyecto: whatsapp"* (con dos puntos) no matcheaba ningún intent — inconsistente con
   `save`, que sí tolera puntuación ahí.

Los 3 se corrigieron ampliando el grupo opcional a `(?:\s+(?:de\s+)?nexus)?`, cambiando el
separador que/puntuación a `[\s,:]*(?:que\s+)?[\s,:]*` (acepta cualquier orden), y
cambiando el `\s+` obligatorio de `search` por `[\s,:]+`. Se añadieron 5 casos de
regresión nuevos en `test_engram_routing` verificando tanto el intent como el `hecho`/`q2`
exacto capturado, y se confirmó contra los 9 casos previos que ninguno se rompió. Segunda
pasada de sonnet tras corregir los 3: **APTO** (con una nota no bloqueante ya preexistente
antes de esta ronda: un input degenerado sin contenido real tras el ancla, tipo *"apunta en
el proyecto de nexus"* a secas, no dispara la pregunta de aclaración — caso de uso
improbable, no introducido por este parche).

## Parte B — Hermes enganchado a Engram por MCP nativo

**Pedido de Adri (verbatim):** *"Tanto hermes, como nexus tienen que estar enganchados a
engram"*. nexus ya usaba Engram por HTTP (Parte A). Hermes es un binario aparte (Nous
Research) que nexus controla por HTTP y cuya config vive en `~/.hermes/`. Engram es agnóstico
pero oficialmente NO soporta Hermes (sí Claude Code, Cursor, Codex, Gemini, Windsurf, VS
Code), así que el enganche no es un `engram setup hermes`. Preguntado el mecanismo, Adri
eligió **«Hermes con Engram nativo (MCP)»**: que Hermes, por su cuenta, use la memoria de
proyecto vía su propio soporte de servidores MCP.

**Qué se construyó** — nexus provisiona en `~/.hermes/config.yaml` (bajo `mcp_servers:`) un
servidor MCP `engram` que arranca `engram mcp --project nexus` por stdio. Verificado a mano
contra el binario real: ese comando levanta un servidor MCP que responde el handshake y
expone las tools `mem_save` / `mem_search` / `mem_context` / … sobre `~/.engram` (proyecto
«nexus») — la MISMA base y proyecto que usa nexus por HTTP. Así los dos leen y escriben la
misma memoria de proyecto: lo que Hermes decide/averigua queda registrado, y Hermes ve lo
que decidió nexus. (El formato `mcp_servers` de Hermes —command/args/env/enabled— se verificó
en su doc oficial.)

En `skills/hermes/skill.py`:
- `_yaml_add_mcp_engram(text, cmd, project)` — PURA: inyecta el server `engram` por cirugía
  de texto SIN PyYAML (no es dependencia de nexus, y así no reordena ni borra comentarios del
  resto del `config.yaml`, igual que el `_yaml_set_model` ya existente). Robusta: respeta la
  indentación REAL de los hijos de `mcp_servers` (2/4 espacios) para no absorber servers,
  quita BOM, conserva comentarios de cabecera, y ante formatos que no edita con seguridad
  (mcp_servers inline, tabs) NO toca nada. Idempotente.
- `_has_mcp_engram(text)` / `_strip_bom(text)` — helpers PUROS de detección.
- `provision_engram_mcp(ctx)` — escribe el `config.yaml` solo si engram está instalado, con
  backup `.bak_nexus` (y sin sobrescribir si el fichero existe pero no se puede leer o
  respaldar). Best-effort: NUNCA lanza.
- `ensure_up(ctx)` llama a `provision_engram_mcp` (en un hilo, best-effort) ANTES del
  early-return por salud, para que la config quede en disco tanto en arranque en frío (la
  carga el gateway nuevo) como con un Hermes ya vivo (la carga en su siguiente reinicio o con
  `/reload-mcp`).
- `diagnose(ctx)` gana `engram_installed` / `engram_mcp`, y «diagnostica hermes» muestra una
  línea nueva: «Engram (memoria de proyecto): ✔ enganchado por MCP …» / «… aún sin
  enganchar, lo dejo configurado la próxima vez que lo arranque» / «— no instalado».

**Coherencia comprobada:** ni el puente HTTP de nexus ni el MCP de Hermes fijan
`ENGRAM_DATA_DIR`, así que ambos comparten el default `~/.engram` con proyecto «nexus». No
hay nada que los separe.

**✔ VALIDADO:** 57 checks en `tests/test_hermes_engram.py` — `_yaml_add_mcp_engram` en 15+
casos (vacío, con `model:`, con otro server, 2/4 espacios, `{}` inline, inline no editable,
BOM, comentario en cabecera, comentarios en columna 0 en varias posiciones, tabs,
idempotencia en todos), `_has_mcp_engram` (positivos/negativos, sin falso positivo con
`engram:` anidado ni falso negativo con comentario col0), `provision_engram_mcp` (escribe,
backup, idempotente, no actúa sin engram, no sobrescribe si no puede leer, nunca lanza), el
wiring en `ensure_up` (provisiona aunque Hermes ya esté vivo), y `diagnose` (reporta el
estado del enganche). Todas las salidas de la cirugía de texto se validan además parseándolas
con PyYAML (disponible en el entorno de test) para garantizar que el `config.yaml` resultante
es YAML válido con todos los servers intactos.

### Revisión y endurecimiento de la Parte B (opus + sonnet, dos pasadas cada uno)

1ª pasada (opus): 4 hallazgos de corrupción de YAML, todos con config.yaml de entrada
concreto y razonable — (1) `mcp_servers` con hijos a 4 espacios: se insertaba `engram` a 2
espacios y el server previo quedaba anidado DENTRO de engram (pérdida silenciosa); (2) BOM
UTF-8 inicial: no se detectaba `mcp_servers` y se anexaba una clave DUPLICADA (yaml.v3 de Go
la rechaza → Hermes no cargaría ningún MCP); (3) `_has_mcp_engram` daba falso positivo con un
`engram:` anidado (p.ej. dentro del `env:` de otro server) → la feature nunca se aplicaba;
(4) un comentario en la propia línea `mcp_servers:` hacía que no se añadiera nada. Corregidos
detectando la indentación real, quitando BOM, exigiendo hijo directo, y aceptando comentarios
de cabecera; más un blindaje extra: si el bloque usa tabs (YAML inválido de origen), no se
edita.

2ª pasada (sonnet, NO APTO en la primera vuelta): 2 huecos MÁS de la misma clase que las
correcciones de opus no cerraban — (5) un comentario suelto en COLUMNA 0 dentro del bloque
`mcp_servers` (separadores de sección, muy comunes) cerraba el bloque antes de tiempo en
ambas funciones → falso negativo de idempotencia (reinsertaba `engram` duplicado) y, con
hijos a 4 espacios, absorbía el server previo; (6) si el `config.yaml` EXISTÍA pero la lectura
fallaba (lock de Windows, antivirus, permiso transitorio), `old` quedaba `""` y el fichero se
sobrescribía por completo SIN backup, perdiendo el `model:` y los otros servers. Corregidos:
comentario/blanco se saltan ANTES del check de fin-de-bloque en las dos funciones; y la
provisión distingue «no existe» de «existe pero ilegible» (aborta sin tocar), respalda
siempre que el fichero exista, y aborta si no puede respaldar. 2ª pasada de sonnet tras
corregir los 2: **APTO**.

## Parte C — Engram como paquete del instalador de nexus (run.bat + nexus.exe)

**Pedido de Adri:** que no haya que instalar Engram a mano — que sea *un paquete más* del
instalador de nexus, y que funcione en los DOS modos de distribución: por fuente (`run.bat`)
y empaquetado (`nexus.exe`, PyInstaller, que NO pasa por `run.bat`).

**Qué se construyó** — la lógica de instalación vive en Python (`backend/core/engram_bridge.py`),
fuente única reutilizada por los dos puntos de entrada:
- `install(ctx)` — si el binario no está: 1º prueba `go install …@latest` si hay Go en el
  PATH (compila en local y evita el falso positivo de antivirus del binario prebuilt); si no,
  descarga el asset oficial del release de GitHub (naming de goreleaser:
  `engram_<ver>_<os>_<arch>.zip` en Windows, `.tar.gz` en Linux/Mac), **verifica su SHA-256
  contra `checksums.txt`** del mismo release (NO extrae ni ejecuta nada sin verificar) y saca
  solo el binario a `~/.engram/bin`. Best-effort: nunca lanza; devuelve la ruta o «».
- `install_cli()` — punto de entrada de `run.bat` (`python -m backend.core.engram_bridge`):
  respeta `engram_autoinstall`, no reinstala si ya está, e imprime el progreso en la consola.
- `maybe_install_background(ctx)` — se lanza desde el `lifespan` de la app (arranca en
  `python -m backend.desktop` Y en el `nexus.exe` congelado): si falta y `engram_autoinstall`
  está activo, instala en un HILO sin bloquear la apertura del HUD. Este es el que cubre el
  `.exe`, donde `run.bat` no llega a ejecutarse.
- `_engram_exe()` ahora también busca en `~/.engram/bin` (donde nexus instala el binario), y
  hay un ajuste nuevo `engram_autoinstall` (por defecto True) para poder desactivarlo.

Integración: paso nuevo en `run.bat` (junto a edge-tts/pypdf/wmi, best-effort, sin abortar el
arranque) y una `asyncio.create_task(engram_bridge.maybe_install_background(...))` en el
`lifespan` de `backend/app.py`. Los dos comprueban `installed()` antes de nada, así que no se
descarga dos veces. NO se instala desde el camino de CHAT (`ensure_up`): habría metido una
descarga de varios MB a mitad de conversación; la instalación es cosa del instalador/arranque.

**✔ VALIDADO:** checks nuevos en `tests/test_engram.py` (118 en total) — naming del asset por
plataforma (`_plat_asset`), verificación de checksum (`_sha256_ok`: coincide / no coincide /
asset ausente / vacío), extracción del binario de un `tar.gz` y de un `zip` descartando
README/LICENSE (`_extract_engram`), el flujo completo de `install()` con la descarga mockeada
(baja + verifica + extrae; **aborta si el checksum no cuadra**, sin dejar binario; idempotente
si ya está instalado, sin descargar), `install_cli()` respeta `engram_autoinstall=false`,
`maybe_install_background()` no instala si ya está o si el autoinstall está desactivado, y
`_engram_exe()` encuentra el binario en `~/.engram/bin`. Además se probó la instalación REAL de
punta a punta en el sandbox (descargó el release v1.20.0 de verdad, verificó el checksum,
extrajo el binario y este respondió «engram 1.20.0»).

### Revisión y endurecimiento de la Parte C (opus + sonnet)

1ª pasada (opus): sin bugs de seguridad ni de correctitud (verificó que la extracción es
inmune a zip-slip porque nunca usa `extract()`/`extractall()` —lee los bytes del miembro y
los escribe a una ruta fija—, que nada se extrae/ejecuta sin pasar por `_sha256_ok`, y que la
descarga va por HTTPS con verificación de certificado). Sí señaló 4 fragilidades, todas
corregidas: (1) el bloque `if __name__=="__main__"` estaba A MITAD del fichero — **bug real**:
por `run.bat` (`python -m …`), si había Go, `_go_install()` llamaba a `_win_hidden_kw()` aún
sin definir → NameError capturado → el camino go-install quedaba roto EN SILENCIO; movido al
final; (2) tests que solo cubrían los caminos negativos → añadidos los positivos (que
`install()` SÍ se llama cuando toca); (3) `_sha256_ok` ahora tolera el formato binario de
`sha256sum` (`<hash> *<asset>`) sin abrir ningún falso positivo (nombre exacto, hash exacto);
(4) `install()` reintenta con `_KNOWN_VERSION` si el asset de la última versión falla (404/red),
pasando igualmente por la verificación de checksum.

2ª pasada (sonnet, APTO con un hallazgo menor): `install_cli()` y el chequeo de `run.bat`
usaban `installed({})` con ctx VACÍO → un usuario con `engram_exe` ⚙ personalizado (fuera de
las rutas típicas) sufriría una reinstalación redundante en cada arranque. Corregido: ambos
pasan settings reales (`{"settings": settings}`). Además, al probarlo se destapó una fragilidad
de hermeticidad en los tests: varios de "no instalado" hacían un `/health` REAL a 7437 y
dependían de que no hubiera binario en las rutas de `_engram_exe` — y como ahora esas rutas
incluyen `~/.engram/bin` (donde nexus instala) y nexus arranca `engram serve`, la suite habría
FALLADO en la máquina de Adri justo después de instalar. Se hicieron herméticos (mock de
`_alive` y de `os.path.expanduser("~")`), y se verificó la corrección con la prueba decisiva:
instalar un engram real en `~/.engram/bin` + arrancar `engram serve 7437` y correr la suite
entera → TODO VERDE. Como remate, `_extract_engram` pasó a escribir de forma atómica (temp
`.part` + `os.replace`). 2ª verificación de sonnet del delta → **APTO**.
