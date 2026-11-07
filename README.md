# nexus — COMMAND CENTER

> **W**ide-**B**and **I**ntelligent **K**nowledge **S**ystem
> Asistente personal estilo JARVIS con HUD cyberpunk verde neón, pipeline de
> voz, arquitectura de skills modulares (nexus + minions) y memoria persistente
> de doble capa (grafo Obsidian + Postgres/pgvector).

![estado](https://img.shields.io/badge/estado-demo%20funcional-00ff9c)

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  VENTANA ESCRITORIO (PyWebview, sin marco, arrastrable)     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  HUD  (HTML/CSS/JS + Canvas)                          │  │
│  │  métricas · reactor de partículas · skills · terminal │  │
│  └────────────────────────▲──────────────────────────────┘  │
│            WebSocket + REST│ http://127.0.0.1:8177 (ventana)│
│  ┌────────────────────────┴──────────────────────────────┐  │
│  │  BACKEND FastAPI                                      │  │
│  │  ┌────────┐  ┌──────────────────────────────┐         │  │
│  │  │ nexus │──│ MINIONS (skills modulares)   │         │  │
│  │  │ (brain)│  │ system_pc·files·tools·coach  │         │  │
│  │  └──┬─────┘  │ billing·memoria·google·n8n…  │         │  │
│  │     │        └──────────────────────────────┘         │  │
│  │  STT (faster-whisper) · LLM (Ollama/cloud) · TTS      │  │
│  │  Scheduler (recordatorios escalonados, triggers)      │  │
│  └───────┬───────────────────────────────────────────────┘  │
└──────────┼──────────────────────────────────────────────────┘
           │
   ┌───────▼────────┐      ┌──────────────────────────┐
   │ data/memory/   │      │ Docker nexus        │
   │ grafo markdown │      │ Postgres 16 + pgvector   │
   │ (siempre)      │      │ :5433 (si está levantado)│
   └────────────────┘      └──────────────────────────┘
```

**nexus + minions** (diseño de las sesiones con Rubén): nexus es el orquestador
generalista; cada skill es un minion especializado con SOLO el contexto de su
dominio (evita alucinaciones por exceso de contexto). El router prueba primero
regex por skill; si nada casa, va al LLM conversacional con memoria.

## Instalación y arranque

```bat
git clone <repo> nexus
cd nexus
run.bat          :: prepara dependencias si faltan y ejecuta backend.desktop
```

Como alternativa, con el entorno Python preparado: `.venv\Scripts\python.exe -m backend.desktop`.
La ventana pywebview usa `127.0.0.1:8177`; el servidor escucha en
`0.0.0.0:8177` para permitir clientes en la red. Restringe el acceso a redes
confiables y usa el QR con token para clientes remotos.

Postgres/pgvector es un servicio de apoyo opcional en
`config/docker-compose.yml`, no el motor ni el lanzador del HUD. Si se genera
un archivo Compose nuevo desde la aplicación, Postgres se publica solo en
loopback; un archivo Compose existente puede publicar el puerto de otra forma.
Revisa su configuración y la red antes de levantarlo.

Opcional — voz real:

```bat
:: STT local (descomenta también en requirements.txt)
pip install faster-whisper sounddevice numpy
:: TTS premium: pon ELEVENLABS_API_KEY en .env
```

## Ejecución

```bat
run.bat            :: abre la ventana HUD (o: python -m backend.desktop)
```

* **F9** o botón **◉ MIC** → escuchar → transcribir → nexus → respuesta hablada
* Terminal inferior → órdenes por texto
* **⚙** → cambiar en caliente proveedor LLM (Ollama ⇄ cloud API key), modelo
  razonador, motor y voz TTS

## Permisos de archivos (⚙ → Permisos)

nexus lee y escribe archivos con la skill ARCHIVOS, la memoria y la ingesta de
documentos. **⚙ → Permisos** decide hasta dónde llega, en tres modos:

| Modo | Alcance |
|------|---------|
| `sandbox` | Solo la carpeta propia de nexus (`data/sandbox`). El más cerrado. |
| `carpetas` | Solo tus carpetas autorizadas. **Es el modo por defecto**: Documentos, Escritorio y Descargas de tu perfil (si prefieres otras, se cambian en ⚙ → Permisos → Carpetas permitidas). |
| `todo` | Todo el equipo. Es una elección **deliberada**: con este modo cualquier orden que llegue por un canal (móvil, Telegram, n8n, una inyección de prompt) alcanza cualquier archivo que puedas leer tú. |

Con `carpetas` (el defecto), una orden sobre un archivo de fuera contesta que
no hay permiso y te dice cómo añadir esa carpeta en ⚙ → Permisos. Las carpetas
sembradas se crean la primera vez que hacen falta; no hay que migrar ningún
`settings.json` guardado.

**Siempre vetado, también en `todo`**: el material de credenciales —
`config/secrets.json`, los tokens OAuth (`*token*.json`, `*credential*` de
`config/`), el `.env` de la raíz, `data/telegram_owner.txt` y
`data/telegram_link_code.txt`, `~/.ssh`, `~/.aws`, `~/.gnupg`,
`%APPDATA%\Microsoft\Credentials`, las bases de sesiones del navegador
(`Login Data` de Chrome/Edge, `logins.json` y `key4.db` de Firefox) y los
archivos `*.key`, `*.pem` y `*.p12`. Esos archivos convierten «mi asistente lee
mis archivos» en «cualquiera que hable con mi asistente roba mis credenciales»,
así que no se habilitan desde ⚙. No es protección de Credential Manager ni del
proceso LSASS a nivel de sistema operativo: eso no lo da una lista de rutas, y
lo que sí se hace con DPAPI está en «Secretos en disco», justo debajo.

## Secretos en disco (DPAPI)

`config/secrets.json` guarda las API keys **cifradas con DPAPI** (hallazgo SEC-09
de la auditoría): cada valor es una cadena `dpapi:v1:<base64>` dentro del mismo
JSON, así que el archivo sigue siendo legible por nombres pero no por contenido.
Windows deriva la clave de **tu cuenta**, así que el archivo solo se descifra en
**este equipo con este usuario**; si lo restauras en otro PC (o en otra cuenta de
Windows) nexus avisa en vez de arrancar como si no hubiera ninguna clave, y te
pide volver a pegarla en ⚙ → Claves API. Un `secrets.json` viejo en claro se
cifra solo al arrancar —y antes de reescribirlo se comprueba que cada valor
vuelve igual, de uno en uno—. En Linux/Docker (los contenedores de CI) no hay
DPAPI: allí el almacén se queda en JSON plano y nexus funciona igual.

Esto protege el archivo en disco: una copia de seguridad del perfil, otra sesión
del sistema, un `git add -A` accidental. **No** protege de un programa que se
ejecute como tú — ese lee el archivo y lo descifra igual, y por eso el riesgo
residual sigue escrito en la auditoría.

Siguen en claro, y es un hueco conocido: `config/google_token.json` y
`config/spotify_token.json` (los escriben sus librerías OAuth, así que cerrarlos
obliga a interceptarlas o a pedir una reautorización) y
`config/google_credentials.json` (el JSON que se descarga de Google). Para ver
qué queda en claro, con tamaño y fecha, y cómo limpiarlo:

```bat
.venv\Scripts\python.exe scripts\revisar_antes_de_subir.py --proteger-backups
```

No borra nada: enumera los archivos y dice qué hacer con cada uno.

**Los permisos solo se cambian desde este equipo.** `POST /api/config` rechaza
con un 403 las claves que controlan una guarda (`perm_files`, `perm_folders`,
`perm_hardware`, las URLs de n8n y de Home Assistant, `permitir_fallback_nube`,
`permitir_delegacion_nube`, `llm_local`, `engram_autoinstall`) cuando la petición
no viene de la ventana
local, aunque traiga el token del QR. El resto de la configuración sigue
funcionando desde el móvil y `GET /api/config` sigue contando el modo, para que
el HUD pueda enseñarlo.

## Presupuesto de modelo (⚙ → costes del día)

La auditoría (AI-07; `07` §5 «Costes y consumo») encontró que nexus no contaba
nada: un bucle, un flujo de n8n que reenvía el mismo texto o una tarde de
investigación pesada no tenían techo. El tope de salida (`llm.max_tokens_salida`)
acota **una** respuesta; esto acota **el día**.

nexus apunta, por día y por proveedor: llamadas (chat, streaming, destilado y
embeddings), caracteres de prompt y caracteres de respuesta, en
`data/presupuesto_llm.json`. Se cuentan **caracteres** porque no todos los
proveedores devuelven el uso; donde sí lo devuelven de verdad (OpenAI y
compatibles, Anthropic, Gemini, Ollama) se guardan también **tokens reales**, y
`GET /api/status` dice qué proveedores dieron números de verdad. Nada se estima:
un contador de gasto con cifras inventadas es peor que no tener contador.

El techo vive en `config/umbrales.json` (sección `llm`) y **se entrega con un
valor de seguridad, no medido**: 400 llamadas y 5.000.000 de caracteres al día
para un escritorio de una sola persona. Se cambia ahí o pidiéndoselo a nexus.
Al 80 % avisa una vez por el HUD; al llegar al techo **deja de llamar a la nube
hasta el día siguiente** y lo dice en español: qué ha pasado, qué ha contado y
cómo subirlo. No recorta la respuesta ni se inventa una contestación.

Los modelos **locales** (Ollama, el modo demostración) **no** están dentro del
techo por defecto: el riesgo del que habla la auditoría es el dinero, y un
modelo en tu equipo no cuesta dinero. `llm.presupuesto_incluye_locales: true`
los mete también, si compartes equipo y quieres un límite único. Lo que llevas
gastado hoy se ve en `GET /api/status` → `presupuesto` (contadores y nombres,
ni una clave ni un fragmento de prompt).

Los **embeddings** cuentan igual, y es lo que más se te iba a escapar: cada vez
que nexus vectoriza un documento o un recuerdo hace una llamada al modelo. Los de
nube (OpenAI, Gemini) pasan por el techo como cualquier otra — es dinero y es
texto que sale del equipo —, y los de Ollama (`nomic-embed-text`, el defecto)
no. Cuando el techo corta la vectorización, nexus lo dice con esas palabras («he
parado la vectorización») y la memoria sigue respondiendo por palabra: degrada,
no miente.

## Delegación en un ejecutor externo (⚙ → núcleo IA)

Nexus puede delegar un encargo agéntico (navegar, investigar en varias webs,
rellenar un formulario) en un ejecutor que corre en tu PC y tiene **su propio
modelo, sus herramientas y su internet**. Eso son tres fronteras, y las tres se
ven en el chat:

- **Local o nube.** El cerebro del ejecutor se clasifica con **la misma tabla**
  que el chat (`llm.localidad_delegado`). Si es local (`ollama`, o un endpoint de
  loopback) el trabajo no sale del equipo y no hace falta nada más. Si es de nube,
  quien lo decide es `permitir_delegacion_nube`, una clave **propia de la
delegación** con defecto **`true`**: esa nube la elegiste tú al configurar a
  Hermes, así que el defecto **no apaga la función**. Ponla en `false` si quieres
  una política estricta de «nada sale por la delegación»: entonces **no se hace ni
  una petición** y se dice en el chat cómo se activa (⚙ o `config/settings.json`)
  o la alternativa que no necesita permiso (un modelo local). Es una clave
  **distinta** de `permitir_fallback_nube`, que gobierna otra cosa (que el cerebro
  *de nexus* caiga a la nube si el elegido no responde), y esa no interviene aquí.
  Con `true` se avisa por el log de que el encargo (y lo que el ejecutor decida
  leer) sale hacia ese proveedor, y la propia confirmación lo dice antes del «sí».
- **Confirmación.** La primera entrega arma una confirmación con el texto
  **exacto** que recibirá el ejecutor («sí» / «no», como los envíos). Cambiar de
  tema la desarma. Un encargo ya aprobado no vuelve a preguntar en sus
  reintentos. **El «sí» por orden sigue siendo la frontera real**: el `true` por
  defecto no significa «sin control», significa «la nube que configuraste no se
  apaga sola».
- **Sin reenvíos a ciegas.** Si no se pudo *entregar* (no hubo conexión), nexus
  relanza el servicio y prueba una vez más. Si el ejecutor **contestó con error o
  se cortó después de recibirlo**, no se reenvía: podría ejecutarlo dos veces. La
  respuesta dice que puede haber ocurrido ya y que reintentar es una decisión tuya.

Los tokens que gasta el ejecutor **no los ve nexus**: el contador del día apunta
la delegación (encargos, por proveedor) en su propia sección de
`data/presupuesto_llm.json` y no inventa llamadas, caracteres ni tokens. Se ve en
`GET /api/status` → `presupuesto.delegaciones`.

## Build a .exe

```bat
installer\build_exe.bat      :: → dist\nexus.exe (único ejecutable, sin consola)
```

## Conectar tu cuenta de Google (Gmail + Calendar + Tasks)

Nunca se usa tu contraseña: es OAuth oficial de Google (~5 min, una vez):

1. https://console.cloud.google.com → proyecto nuevo (ej. "nexus")
2. **APIs y servicios → Biblioteca** → habilita *Gmail API*, *Google Calendar API* y *Google Tasks API*
3. **Pantalla de consentimiento OAuth** → tipo *Externo* → añade tu email como usuario de prueba
4. **Credenciales → Crear credenciales → ID de cliente OAuth → App de escritorio** → descarga el JSON y guárdalo como `config/google_credentials.json`
5. Pide en el HUD: `lee mis correos` → se abre el navegador para autorizar y ya queda enlazado (token en `config/google_token.json`)

## Telegram real (control remoto desde el móvil)

1. En Telegram habla con **@BotFather** → `/newbot` → copia el token
2. Pégalo en `.env`: `TELEGRAM_BOT_TOKEN=123456:ABC...`
3. Reinicia nexus y escribe cualquier cosa a tu bot: el primer chat queda
   registrado como propietario y desde ahí puedes darle CUALQUIER orden del HUD

## WhatsApp + n8n

WhatsApp no tiene API abierta gratuita, así que se envía a través de un flujo
de n8n (con Evolution API, Twilio o WhatsApp Cloud según lo que uses):
importa `config/n8n_flujo_ejemplo.json` en n8n, activa el flujo, pon la URL
del webhook en ⚙, y ya funciona `envía un whatsapp a Rubén diciendo hola`.

### El secreto de `/api/n8n` (obligatorio)

Desde la auditoría de seguridad el webhook **no se fía de que la llamada venga
de casa**: n8n corre en Docker y cualquier proceso del equipo puede hablar con
127.0.0.1:8177. Todas las llamadas a `POST /api/n8n` llevan la cabecera
`x-nexus-n8n-secret`, también las locales.

1. Abre en ESTE PC `http://127.0.0.1:8177/api/n8n/secret`. Devuelve el secreto
   (y el nombre de la cabecera). Ese endpoint sólo contesta a este equipo: desde
   el móvil o el túnel responde 403, aunque lleves el token del QR.
2. En n8n crea **una** credencial de tipo *Header Auth* llamada
   `nexus /api/n8n` con Header Name `x-nexus-n8n-secret` y ese valor, y
   selecciónala en los nodos que llaman a nexus (y en el webhook, que también
   exige cabecera).
3. Sin la cabecera correcta la respuesta es `401` y no se ejecuta nada.

El secreto se genera solo la primera vez (`secrets.token_urlsafe(32)`), se
guarda con la API de secretos en `config/secrets.json` —**nunca** en
`settings.json` ni en `GET /api/config`— y se puede fijar a mano con la variable
de entorno `NEXUS_N8N_SECRET` antes de arrancar nexus.

### Lo que n8n puede ordenar (y lo que no)

El texto que entra por `/api/n8n` lo escribe un flujo, no tú. Por eso `n8n` es
un canal de **denegación por defecto** (`backend/core/comun/canales.py`): sólo
ejecuta la lista blanca de órdenes de sólo lectura —«estado de instagram»,
«analiza mis reels» y «dame ideas de contenido»— y todo lo demás se contesta
con «Esa orden no está permitida desde n8n.» y sin efectos: ni correo, ni
WhatsApp, ni memoria, ni Drive, ni cadenas, ni planificador del modelo, ni
Hermes. El chat del HUD, la voz y Telegram no cambian.

Eso incluye lo que llega de WhatsApp hacia dentro: el flujo de ejemplo sólo
**avisa** de que ha llegado un mensaje (queda en el registro de nexus y en el
de n8n); no lo ejecuta. Y el informe diario ya no se sube a Drive ni se manda
por correo: ésas eran órdenes de escritura y ahora se rechazan. El informe se
queda en la salida de los nodos, en el panel de ejecuciones de n8n. Si lo
quieres por correo, se manda desde n8n con credenciales propias de n8n.

Tampoco se puede **delegar en el ejecutor externo** desde n8n: el rechazo del
canal ocurre antes que cualquier delegación. Y cuando la delegación se pide
desde el HUD o la voz, pasa por las tres fronteras de la sección «Delegación en
un ejecutor externo»: localidad y `permitir_delegacion_nube` (true por defecto),
confirmación con el encargo exacto y nada de reenvíos a ciegas.

## Micro abierto (conversación fluida)

Botón **∞ AUTO** del HUD: nexus escucha continuamente, corta cuando dejas de
hablar (detección de silencio), responde con voz y vuelve a escuchar — sin
pulsar F9 cada vez. Requiere voz real instalada (faster-whisper + sounddevice,
ya incluidas en requirements.txt).

## Grafo de conocimiento (◈ NODOS)

Botón **◈ NODOS**: mapa de nodos de colores — nexus en el centro, cada skill en
su órbita con su color, y tus notas de memoria como nodos cian. Pulsa
cualquier nodo y se abre su panel de acciones de un clic.

## Olvidar de verdad (supresión completa)

Cuando le dices a nexus que olvide algo, el hecho está copiado en más de un
sitio. Desde la corrección de PRIV-03 (roadmap P2-8) la purga lo RECORRE todo y
lo DICE, sin prometer de más:

| Almacén | Qué pasa |
|---------|----------|
| `data/memory/` (la nota) | Va a la papelera. Restaurable. |
| `memories` (pgvector) | La fila recibe `retirado_en`: deja de aparecer en las búsquedas. Reversible. |
| `data/rag/knowledge.jsonl` | Los fragmentos de esa fuente SALEN del archivo (se reescribe de forma atómica, y los demás registros quedan idénticos byte a byte). Se puede reconstruir reindexando mientras la nota siga en la papelera. |
| `data/memory/documentos/` (espejo de la ingesta) | Va a la MISMA papelera que la nota y se restaura con ella. |
| Memoria operativa (`data/engram_ops.json`) | El recuerdo de comportamiento que contenga ese texto se olvida. |
| Engram (memoria de proyecto) | Se le pide olvidar por su puerta. Si no responde —o si no expone borrado— el resultado se informa como **NO COMPLETADO**, nunca como hecho. |
| `data/webcache.json` | Se van las entradas de caché cuyo texto o pregunta es eso. |
| `data/interactions.jsonl`, `logs/audit.jsonl`, `logs/recall.jsonl`, `data/jobs.json` | **No se tocan por defecto**: son la traza de lo que pasó. Solo se limpian si lo pides expresamente (`incluir_logs`), y entonces se quitan líneas enteras dejando las demás intactas. |
| `data/backups/*.zip` | **No se reescriben ni se borran**: son tu única red. El informe te dice cuántas copias lo contienen y con qué fechas, y el camino es dejarlas rotar (7 diarias) o borrarlas a mano. |

El orden es siempre el mismo que ya conocías: **previsualizar** (que ahora
enseña esa lista, con lo que se va a tocar, lo que no se puede tocar y por qué)
y después **aplicar** — que actúa sobre esa misma lista, ni una tienda más. Lo
que el borrado definitivo destruye sigue exigiendo tu «sí». Y después de
purificar, la respuesta dice qué se retiró, qué es restaurable y qué sobrevive,
con el motivo.

## Recuperación (copias de seguridad, RPO y RTO)

El detalle honesto de qué se copia, cada cuánto, cuánto puedes perder y qué hace
exactamente una restauración. Esto cierra el hallazgo P2-10 / PRIV-04 de la
auditoría, que anotaba lo peor: la restauración **nunca se había ejecutado**.

| | |
|---|---|
| **Qué entra en la copia** | Todo `data/`: memoria en grafo, tablero, contactos, vigilancias, facturas, informes, RAG y la caché. Compresión zip normal. |
| **Qué NO entra (comprobado en el código, no supuesto)** | `config/` completo — `secrets.json` (las API keys), los tokens de Google y Spotify, `.env` —, `data/backups/` (no se anida) y `data/chrome_nexus/` (el perfil de Chrome). Los archivos de más de 50 MB se quedan fuera. |
| **Cuándo** | Una copia diaria automática (`data/backups/nexus-data-AAAAMMDD.zip`), y otra cuando dices «haz una copia de seguridad». |
| **Cuántas se guardan** | 7 diarias (rotación). Los `baks-*.zip` de mantenimiento no cuentan ni rotan. |
| **RPO** (cuánto puedes perder) | Hasta **24 h** de lo escrito desde la última copia. Si acabas de hacer algo importante, pide «haz una copia de seguridad» y baja el RPO a minutos. |
| **RTO** (cuánto tardas en volver) | Restaurar son **segundos o pocos minutos** (copiar el zip a una carpeta nueva) + el renombrado a mano de la sección siguiente. Depende del tamaño de tus datos y no está cronometrado con tus cifras concretas. |

**La copia se puede verificar, no solo listar.** Cada zip lleva dentro un
`nexus-backup-manifest.json` con la ruta, el tamaño y el sha256 de cada archivo,
así que `«qué copias de seguridad hay»` contesta *«el último backup verificó
OK»* — o dice qué entrada no cuadra, si no cuadra. Eso demuestra integridad
(que el zip no se ha corrompido ni se ha tocado por accidente), **no** que nadie
malintencionado no pueda rehacer zip y manifiesto a la vez: no es una firma.

**Restaurar (lo hace nexus, no tú a mano).** Di «restaura la copia de
seguridad»: nexus te enseña qué lleva la última copia (archivos, tamaños, fecha,
si el manifiesto cuadra) y **te pide un «sí»**. Con el sí, extrae el contenido en
una carpeta **nueva** — `restaurado-AAAA-MM-DD-HHMMSS/`, al lado de `data/` — y
te dice cuántos archivos y bytes ha dejado. Nunca escribe encima de tu `data/`,
ni toca `config/`, ni los zips: si la restauración sale mal, tu nexus sigue
funcionando como estaba y solo hay que borrar esa carpeta. Se niega en firme si
el archivo no es una copia de nexus, si está corrupto o truncado, si lleva rutas
que se saldrían de la carpeta (`..` o rutas absolutas), si el manifiesto no
cuadra o si la carpeta de destino ya tiene algo dentro.

Para **usar** lo restaurado (con nexus cerrado): renombra `data/` a
`data_viejo/` (no lo borres), renombra la carpeta `restaurado-…` a `data/` y
arranca. Si algo no cuadra, `data_viejo/` sigue intacta. Ojo: `config/` **no**
viaja en la copia, así que las claves API siguen siendo las de este equipo; los
tokens de Google/Spotify hay que volver a vincularlos si has cambiado de PC.

**Fuera del disco.** Un backup en el mismo disco que los datos no protege de un
fallo de disco ni de un ransomware. Pon la segunda copia en otro disco físico
(o un NAS montado) con una línea de `config/settings.json`:

```json
"backup_destino_extra": "E:/Copias nexus"
```

Cada copia diaria deja entonces una segunda copia idéntica ahí, y si ese disco
no está disponible la copia local se hace igual y la respuesta te avisa de que
la segunda falló (no se queda callado). No hay nube ni dependencias nuevas: es
una copia de archivo normal.

**Los zips NO van cifrados, y es una decisión, no un olvido.** DPAPI (lo que
cifra `secrets.json`) ata cada blob a *este* equipo y *este* usuario de Windows:
una copia cifrada así no se abriría justo cuando la necesitas (se rompió el
disco, se perdió el equipo). La biblioteca estándar de Python no trae ningún
cifrado autenticado, y montar uno a mano sería peor que no tenerlo. Lo que hay
que cifrar es el **destino**: BitLocker/VeraCrypt en ese segundo disco, o una
carpeta cifrada por el sistema operativo. Mientras tanto, el zip es texto
legible (tu memoria, tu tablero) y así lo dice nexus en cada vista previa.

**Cómo lo pruebas tú mismo** (2 minutos, sin riesgo): di «haz una copia de
seguridad», luego «qué copias de seguridad hay» (tiene que decir *verificó OK*),
y por último «restaura la copia de seguridad» y di «sí». Aparecerá una carpeta
`restaurado-…` con tus archivos y tu `data/` intacto: eso es una restauración
de verdad, ejecutada. Si quieres, compara una nota: el archivo restaurado tiene
que ser byte a byte igual al de `data/`.

## Novedades v3

* **⚙ Configuración pro**: cómo quieres que te llame nexus; check "modelo LOCAL"
  que detecta los modelos instalados (Ollama / LM Studio) y te los da a elegir;
  o proveedor cloud (OpenAI / Anthropic / Gemini / otro compatible) con su API key
  y modelo concreto — cada proveedor con su formato de API correcto. Las keys se
  guardan en `config/secrets.json`, nunca salen por la API.
* **Voces de verdad**: motor Edge-TTS con voces neuronales GRATIS en español
  (Álvaro, Elvira, Dalia, Jorge...), ElevenLabs opcional, y las voces reales de
  Windows. Botón "▶ Probar voz" en ⚙.
* **Devil's Advocate**: `abogado del diablo: <idea>` la destroza con cariño
  (steelman → debilidades → riesgos → veredicto). `activa el modo abogado del
  diablo` añade contrapunto crítico a TODAS las respuestas. Y el prompt base
  ya ordena corregirte cuando te equivocas — compañero, no pelota.
* **Tablero kanban** (▦ TAREAS): pendiente → progreso → revisión → completada.
  `crea la tarea X para el viernes prioridad alta`, `mueve X a revisión`,
  `organiza mis tareas por urgencia` (Eisenhower), `qué tareas van retrasadas`.
  Toques de atención automáticos por HUD y Telegram si te retrasas.
  Encima del kanban, una franja de KPIs (`GET /api/board/kpis`): abiertas, vencidas,
  vencen pronto, sin fecha y desglose por urgencia y tipo. Las tareas que nacen del
  correo guardan tipo, urgencia y el id del correo, y no se duplican al repetir el
  análisis.
* **Project manager**: `planifica el proyecto X` → spec interna (Diseño /
  Propuesta / Tareas / Validaciones) revisada por el abogado del diablo,
  guardada en `data/specs/` y con las tareas metidas en el tablero.
* **Transcripción**: `transcribe el audio C:\ruta\nota.ogg` → texto + ideas
  principales + tareas detectadas + lluvia de ideas, guardado en memoria.
* **RAG auto-aprendiente**: cada conversación y conocimiento se vectoriza con
  embeddings (Ollama `nomic-embed-text`) en pgvector → nexus recuerda por
  SIGNIFICADO, no solo por palabra exacta, y aprende de ti con el uso.
* **Investigación**: `investiga <tema> y hazme un informe` (con fuentes web),
  `tendencias de <nicho>`, `informe económico` (analiza tus facturas/gastos).
* **Datos**: `conéctate a la base de datos postgresql://...` (también MySQL,
  SQLite, Mongo), `consulta: SELECT...`, `dashboard de la tabla X` → dashboards
  oscuros estilo Power BI (Chart.js) abiertos en el navegador. Solo lectura.

## Órdenes de ejemplo

| Di / escribe... | Minion |
|---|---|
| `qué me toca hoy` | Coach — briefing diario |
| `nuevo objetivo: fabricar camisetas en China` | Coach — desglose en pasos |
| `recuérdame pagar al proveedor el viernes` | Coach — avisos 1 sem / 2 días / día D |
| `me ha surgido un imprevisto en la nave` | Coach — replanifica el día |
| `hazle una factura a Ubix por el diseño de 350 euros` | Facturación |
| `estado del sistema` / `lista los procesos` | Sistema/PC |
| `haz una captura de pantalla` | Sistema/PC |
| `apaga el PC` → `confirmo apagado` | Sistema/PC (doble confirmación) |
| `resume el documento C:\docs\plan.txt` | Archivos (IA) |
| `integral de x**2` / `resuelve x**2-4=0` | Herramientas (SymPy) |
| `qué tiempo hace en Madrid` | Herramientas (Open-Meteo real) |
| `recuerda que el proveedor se llama Chen` | Memoria |
| `qué recuerdas de China` | Memoria (DB + grafo) |
| `ver mensajes` → `captura de tareas` | Comunicación (simulada) |
| `genera una imagen de un reactor arc` | IA/Multimedia (mock) |

## Añadir una skill nueva

1. Crea `skills/mi_skill/`
2. `SKILL.md` — describe qué hace (el cerebro lo carga como contexto)
3. `skill.py`:

```python
SKILL = {
    "name": "Mi Skill",
    "description": "Qué hace",
    "patterns": {"saludo": r"salúdame"},
}

async def handle(intent, text, match, ctx) -> dict:
    # ctx: settings, bus (eventos al HUD), pg (DB), graph (notas), history
    return {"reply": "¡Hola desde mi skill!"}
```

4. Reinicia. El router la registra automáticamente y aparece en el HUD.

## Estructura del repo

```
nexus/
├── backend/          # FastAPI + núcleo (nexus, LLM, voz, memoria, scheduler)
│   ├── app.py        # API + WebSocket
│   ├── desktop.py    # lanzador ventana (punto de entrada del .exe)
│   └── core/
├── frontend/         # HUD (index.html, css/, js/)
├── skills/           # 8 minions (carpeta + SKILL.md + skill.py)
├── config/           # settings.json (editable desde el HUD)
├── data/             # memoria grafo, capturas, facturas (runtime)
├── docs/             # SPECS*.md, MOBILE.md, PETICIONES_ANALISIS.md
├── assets/           # logo.png del producto (≠ frontend/logo.png, que sirve el HUD)
├── scripts/          # utilidades: arranque por palmadas, abrir el puerto, revision de secretos
├── installer/        # nexus.spec · build_exe.bat · nexus_installer.nsi · .ico/.bmp
└── requirements.txt · requirements.lock · .env.example · run.bat · INSTALAR_nexus.bat · SUBIR_A_GITHUB.bat
```

## CI: qué cubre y qué no

`.github/workflows/security-ci.yml` es el único workflow y corre en cada
`push`, en cada `pull_request`, los lunes y a mano. Tres jobs en
`ubuntu-24.04`:

| Job | Qué hace |
|-----|----------|
| `dependencias` | `pip-audit` contra OSV/PyPI sobre `requirements.txt`, `requirements-voice.txt` **y** `requirements.lock` (las versiones realmente fijadas). |
| `pruebas` | Instala `requirements.lock` y ejecuta **22 suites** de perfil `safe-unit` de `tests/runner_profiles.py` en Python 3.12. |
| `trivy` | Trivy filesystem (vulnerabilidades + secretos + misconfig) y **falla** ante HIGH/CRITICAL. |

Las tres acciones (`actions/checkout`, `actions/setup-python`,
`aquasecurity/trivy-action`) están fijadas por **SHA de commit**, no por
etiqueta: una etiqueta se puede mover, un commit no. Sólo se usan los eventos
`push`, `pull_request`, `schedule` y manual — **nunca** `pull_request_target`,
que daría al código de un PR de un fork un token de escritura y los secretos
del repo. El workflow no usa ningún secreto y el job de pruebas declara
`permissions: contents: read`.

**Un tick verde NO es prueba global del producto.** Lo que este CI no
ejecuta, y por qué:

* **94 de las 116 suites registradas.** Las que necesitan Windows
  (`unit/skills/system_pc/*` con `pycaw`/`wmi`/`keyboard`, `unit/skills/files/*`,
  `unit/routing/*`, `unit/specs/*`) necesitan un runner de Windows autoalojado.
* Las **2 suites de servidor real** (`test_acceso_remoto`, `test_entrega_real`):
  arrancan un uvicorn de verdad y levantan STT, scheduler, long-poll de
  Telegram y el túnel adoptado. Necesitan Postgres y un runner dedicado.
* Las **suites con base de datos** (`test_purga`, `test_purga_completa`,
  `test_memoria_embeddings`): sin Postgres/pgvector se saltan comprobaciones.
* Las **9 suites `provider-contract`** (Gmail/Calendar/Drive falsos) y la de
  **domótica** (`authorized-device`): excluidas por
  `safe_to_run_in_live_checkout: False`, que significa que importan
  configuración de producción antes de poner sus dobles.
* **E2E de navegador** (`tests/e2e/run_e2e.py`, Playwright) y las **sondas
  herméticas** (`tests/hermetic/*`): otra imagen, otro runner.
* La **auditoría de las 7 dependencias sólo-Windows** (`pycaw`, `comtypes`,
  `pythonnet`, `clr_loader`, `pywin32`, `pypiwin32`, `WMI`): en Linux se saltan
  por marcador, así que su versión fijada no se audita en ningún job todavía.
* **Lint, typecheck, SAST (Bandit/Semgrep), SBOM, CD y firma de código**: no
  existen. El `.exe` y la APK se construyen en local.
* **Protección de ramas**: no verificable desde el repositorio local.

El job imprime esa lista (`PENDIENTE …`) al final de cada ejecución, para que
no haya que deducirla del verde.

### `requirements.lock` (versiones fijadas, todavía sin hashes)

`requirements.txt` sigue siendo el fichero donde se **declaran rangos** (`>=`).
`requirements.lock` es la **foto fijada del venv de desarrollo** (98 paquetes,
Python 3.12, generada offline desde `pip freeze`): sirve para que CI y, cuando
lo aceptes, `run.bat` instalen exactamente lo que ya está probado. Las 7
líneas con `; sys_platform == "win32"` se saltan solas fuera de Windows.

No lleva **hashes** a propósito: fijar por hash exige una resolución contra el
índice (`pip-compile --generate-hashes`) y eso es una decisión deliberada del
dueño, no algo que se cueza en un worker. Mientras tanto protege contra
**deriva de versiones**, no contra un índice comprometido. Instalación prevista:

```bat
.venv\Scripts\python.exe -m pip install --no-deps -r requirements.lock
```

`run.bat` **todavía instala desde `requirements.txt`**: cambiar el instalador
es una decisión aparte (rompería la reparación automática de hoy).

## Qué es real y qué es simulado

| Real | Simulado (arquitectura lista) |
|---|---|
| HUD completo + WS en tiempo real | Generación de imágenes (→ SD/DALL·E) |
| Métricas psutil, procesos, capturas | Visión de imágenes (→ llava) |
| SymPy, clima Open-Meteo, ping, DuckDuckGo | Mensajes WhatsApp/Telegram |
| Memoria grafo + Postgres/pgvector | Calendario y envío de email |
| Recordatorios escalonados, checklists, objetivos | Bot Telegram (→ BotFather + token) |
| Facturas HTML + registro en DB | STT/TTS si faltan libs (fallback mock) |
| Ollama / cloud LLM configurable en caliente | |
