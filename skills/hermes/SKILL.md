# 🪽 Hermes (subagente)

Delega encargos AGÉNTICOS en Hermes Agent (Nous Research, open source MIT):
navegar y automatizar el navegador con visión, investigación multipaso, ejecutar
código aislado, informes de mercado. nexus se lo encarga por la API local de
Hermes (compatible OpenAI, por defecto `http://127.0.0.1:8642`) COMO TRABAJO EN
2º PLANO: nexus sigue libre mientras Hermes trabaja y trae el resultado por el
mismo canal (HUD, móvil o Telegram).

Cada encargo se apunta en `data/hermes_jobs.json` con un número correlativo
(#1, #2…) y su estado: encargado → trabajando → hecho/error. Lo que Hermes
averigua se vuelca además en la memoria Postgres de nexus.

## Qué frases lo disparan

| Intent | Qué hace | Frases |
| --- | --- | --- |
| `hermes` | Encarga el trabajo | «hermes: investiga la competencia y hazme un informe», «dile a hermes que busque proveedores», «pídele a hermes que compare precios», «que hermes rastree la web», «delega en hermes la comparativa» |
| `hermes_tarea` | Igual, cuando la orden nombra la tarea o el encargo | «mándale una tarea a hermes: resume las noticias del día», «dale trabajo a hermes», «asígnale una misión a hermes: …» |
| `hermes_estado` | Radiografía de la conexión | «¿está hermes conectado?», «diagnostica hermes», «diagnostícame hermes», «estado de hermes», «¿qué tal va hermes?», «revísame la conexión con hermes», «¿va bien hermes?» |
| `hermes_arranca` | Levanta o relanza su gateway | «arranca hermes», «arráncame hermes», «reinicia hermes», «reinicia el gateway de hermes», «levántame hermes», «pon hermes en marcha», «enciende hermes» |
| `hermes_resultado` | Devuelve lo que ya está | «¿y la respuesta de hermes?», «¿ha terminado ya hermes?», «¿ya terminó hermes?», «¿qué ha averiguado hermes?», «novedades de hermes», «resultado del encargo 3», «encargo #3» |
| `hermes_info` | Qué sabe hacer (se lo pregunta en vivo a `/v1/capabilities` y `/v1/skills`) | «¿qué sabe hacer hermes?», «¿qué skills tiene hermes?», «para qué sirve hermes», «¿de qué es capaz hermes?» |

`hermes_estado` hace una **prueba real del cerebro interno**: manda un ping de 1
token a `/v1/chat/completions`. Distingue «gateway apagado» de «modelo interno
sin credenciales», pero consume una llamada del proveedor LLM de Hermes.

Todos los patrones exigen la palabra literal «hermes»: esta skill nunca se queda
con una frase que no la mencione. La excepción es la delegación automática (ver
abajo), que la decide el cerebro, no el enrutador.

## Delegación automática

Si ninguna skill local casa Y la frase pinta agéntica (navegar, monitorizar,
comparar precios en varias webs, informe de mercado…), nexus se lo pasa a Hermes
sin que digas «hermes». Solo si Hermes está vivo o instalado. Se desactiva con
⚙ `hermes_auto=false`.

## Tres fronteras antes de delegar (T25 / P3-6)

Delegar es entregar trabajo a **otro agente** con su propio modelo, sus
herramientas y su internet. Por eso ningún encargo sale sin pasar estas tres
puertas, tanto si lo pides tú («hermes: …») como si lo decide la delegación
automática:

### 1. Localidad y permiso: lo que se delega también puede salir del equipo

El cerebro de Hermes puede ser local (`ollama`, o un endpoint de loopback) o de
nube (openai, anthropic, gemini, openrouter…). La clase la decide **la misma
tabla que el chat** (`llm.localidad_delegado`, que reusa `LOCALIDAD`): no hay una
segunda lista de proveedores que se pueda quedar desfasada. Se lee del bloque
`model:` de `~/.hermes/config.yaml` (lo que Hermes carga de verdad) y, si ahí no
hay nada, de ⚙ `hermes_provider`.

- **Local** → el trabajo no sale del equipo: se delega sin pedir ningún permiso.
- **Nube y `permitir_delegacion_nube: true`** (el **defecto**) → se delega. Esa
  nube la elegiste tú al configurar a Hermes, así que el defecto **no apaga la
  función**; se **avisa por el bus** de que el texto del encargo (y lo que el
  ejecutor decida leer para resolverlo) sale hacia ese proveedor, y la
  confirmación lo dice también **antes** del «sí». El «sí» por orden sigue
  siendo la frontera real: `true` significa «la nube que configuraste no se
  apaga sola», no «sin control».
- **Nube y `permitir_delegacion_nube: false`** → **no se delega**: el chat dice
  que la delegación a un cerebro de nube está desactivada, nombra la clave y
  dónde se activa (⚙ o `config/settings.json`) y ofrece la alternativa que no
  necesita permiso (ponerle a Hermes un modelo local). **No se hace ni una
  petición** ni se arma confirmación.

`permitir_delegacion_nube` es una clave **distinta** de `permitir_fallback_nube`,
y esa no interviene en la delegación: `permitir_fallback_nube` gobierna el CAMBIO
del cerebro *de nexus* cuando el elegido no responde (T6). Reutilizarla aquí
apagaba toda delegación de un Hermes configurado a propósito. Las dos son
claves de este equipo: `POST /api/config` remoto las rechaza con 403.

### 2. Confirmación: una vez, con el encargo exacto

La primera entrega de un encargo arma `confirm.request` (tipo
`delegacion_hermes`, **no destructiva**) con el texto **exacto** que recibirá el
ejecutor — recortado con «…» si no cabe, nunca resumido — y solo arranca con un
«sí». «No» no encarga nada, y cambiar de tema lo desarma. La respuesta se acepta
solo desde texto o voz, como todas las confirmaciones.

Un encargo **ya aprobado no vuelve a preguntar**: sus reintentos ocurren dentro
del trabajo y no arman nada.

### 3. Nada de reenviar a ciegas

La posición del fallo decide si se puede reintentar:

- **Antes de entregar** (no hubo conexión: `ConnectError`/`ConnectTimeout`) → el
  encargo no ha llegado a nadie. Nexus relanza el gateway con entorno limpio y
  prueba **una vez más**. No hay nada que duplicar.
- **Después de entregar** (una respuesta con error —5xx, 401 de mi clave—, un
  timeout de lectura, un corte a mitad) → el encargo ya viajó y puede haber
  navegado, escrito o enviado algo. **No se reenvía solo**: la respuesta dice que
  puede haber ocurrido ya, que nexus no lo repite, y que mirar lo que quedó y
  reintentar son decisiones del operador (que volverá a confirmar).

Un 401 «Missing Authentication header» sigue siendo otra cosa (el modelo interno
de Hermes sin credenciales): no se reintenta y se explica cómo arreglarlo.

## El operador NO se entera de que existe esto

Regla de arquitectura: **el usuario solo habla con nexus.** Que un encargo lo
resuelva por dentro un ejecutor secundario es fontanería — va al registro, nunca
al chat ni al panel. Lo que sí tiene que pasar es lo contrario: que el ejecutor
**devuelva el resultado a nexus**, y que nexus lo dé como suyo, en primera
persona.

Dónde se garantiza, y por qué en cada sitio:

- `backend/core/publicvoice.py` · `sanitize()` limpia el TEXTO (respuesta,
  resultado, error, título).
- `backend/core/publicvoice.py` · `limpia_trabajo()` enmascara **quién lo
  ejecutó**: `agent`, `provider` y `skill` pasan a «nexus», y se limpian los
  textos que viajan dentro del trabajo (`title`, `request`, `progress_note`).
  Hace falta porque el HUD pinta el agente en la tarjeta de Multitarea
  (`frontend/js/command.js`, la línea `jobc-m`): el texto salía limpio y ahí se
  leía «hermes» igual.
- `backend/core/events.py` es la última barrera: aplica las dos cosas a los
  eventos `chat`, `job_done` y `jobs` antes de que salgan por el WebSocket. Los
  eventos `log` NO se tocan — ahí sí queremos el detalle.
- Lo que se guarda en memoria va con prefijo neutro (`[Trabajo]`), porque se
  recupera con «qué recuerdas de…» y se le enseña al operador tal cual. Quién lo
  hizo queda en `kind="hermes"`, que es interno.

Y un suelo: si al limpiar un mensaje no queda **nada**, no se manda vacío. Una
respuesta en blanco parece que nexus se ha colgado, y eso es peor que la fuga.

El registro (`data/logs/audit.jsonl`) y la auditoría **sí** guardan el ejecutor
real: sin eso no se puede diagnosticar nada.

## Qué necesita configurado

- **Hermes Agent instalado** (hermes-agent.nousresearch.com). El CLI se
  autodetecta en `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\hermes.exe` o
  `~/.hermes/hermes-agent/venv/bin/hermes`; si está en otra ruta, ponla en
  ⚙ `hermes_exe`. URL del gateway en ⚙ `hermes_url`; autoarranque desactivable
  con ⚙ `hermes_autostart=false`.
- **Clave del gateway**: Bearer `hermes_api_key` en `config/secrets.json`.
  nexus la provisiona él solo: escribe `~/.hermes/.env` con
  `API_SERVER_ENABLED=true` y una `API_SERVER_KEY` fuerte (Hermes se niega a
  abrir el puerto con clave débil), guarda backup `.bak_nexus` y sincroniza la
  clave con `config/secrets.json`. Si el `.env` ya tenía una clave fuerte, la
  adopta en vez de rotarla. Idempotente.
- **Cerebro interno de Hermes** (su propio proveedor LLM). Un 401 «Missing
  Authentication header» NO es la clave del gateway: es su proveedor LLM sin
  credenciales. Se arregla desde el HUD (Núcleo IA → proveedor/modelo/clave,
  que llama a `/api/hermes/configure` y escribe `~/.hermes/.env` y el bloque
  `model:` de `~/.hermes/config.yaml`) o en terminal con `hermes model` +
  `hermes auth add <proveedor>`. Proveedores mapeados: openai, anthropic,
  gemini, openrouter. Ese proveedor decide además si delegar es local o de nube,
  y por tanto si aplica `permitir_delegacion_nube` (true por defecto): ver «Tres
  fronteras» arriba.
- **Dependencia**: `httpx` (ya en `requirements.txt`).

## Autoarranque y resiliencia

Si el gateway está apagado, nexus lo levanta (`hermes gateway run --replace`,
con entorno limpio —sin `PYTHONPATH`/`VIRTUAL_ENV` heredados, que rompían su
Python— y log en `data/hermes_gateway.log`) y espera hasta 60 s.

- No se pudo **entregar** (sin conexión) → relanza limpio y prueba una vez más.
- El ejecutor **contestó con error** (5xx, 401 de mi clave) → NO se reenvía: el
  encargo ya había salido y podría ejecutarse dos veces. Se dice y se para.
- 401 «Missing Authentication header» → no reintenta; explica que falta
  configurar el modelo interno de Hermes.
- Respuesta 200 cuyo TEXTO es un error del proveedor → el encargo consta como
  fallido, no como terminado.

Timeout de encargo: 15 min.

## Contabilidad de los encargos

Los tokens del cerebro de Hermes **no los ve nexus**: los paga y los cuenta el
ejecutor. Por eso el contador del día apunta la **delegación** (un encargo por
proveedor del ejecutor) en su propia sección de `data/presupuesto_llm.json`,
visible en `GET /api/status`, y **no** suma llamadas ni caracteres ni inventa
tokens. Un número inventado en un contador sería peor que no tenerlo.

## Engram (memoria de proyecto compartida)

Si Engram está instalado, nexus engancha a Hermes a la MISMA memoria de proyecto
que usa él: añade un servidor MCP `engram` a `~/.hermes/config.yaml` (bajo
`mcp_servers:`) que arranca `engram mcp --project nexus` por stdio. Hermes
obtiene así sus tools `mem_save` / `mem_search` / `mem_context` sobre la misma
base (`~/.engram`, proyecto «nexus»). Es la memoria de PROYECTO
(decisiones/bugs/features del código), distinta de la memoria PERSONAL.

Se provisiona con cirugía de texto sobre el `config.yaml` (sin tocar el resto,
con backup `.bak_nexus`, idempotente) la próxima vez que arranque el gateway.
Un Hermes ya arrancado lo carga en su siguiente reinicio o con `/reload-mcp`.
Si Engram no está instalado, no se configura nada. Compruébalo con «diagnostica
hermes» (línea «Engram (memoria de proyecto)»).

## Qué NO hace

- **No delega a la nube con la delegación apagada.** Con
  `permitir_delegacion_nube: false` y un cerebro que no es local, no se hace ni
  una petición y se dice dónde se activa (o que un modelo local no necesita
  permiso). Con el defecto `true` lo que nexus delega sí puede salir del equipo,
  y eso lo sabes antes de decir «sí»: el panel de la confirmación lo dice y el
  aviso queda en el log. El «sí» por orden sigue siendo la frontera real.
- **No repite un encargo que pudo ejecutarse.** Un fallo después de entregarlo
  se cuenta tal cual: puede haber hecho parte del trabajo, y reintentarlo a
  ciegas lo duplicaría.
- **No inventa resultados.** Si el gateway no está o el modelo interno de Hermes
  no tiene credenciales, lo dice con la causa concreta; nunca devuelve un
  informe de ejemplo. Un encargo sin verificar no se canta como hecho.
- **No espera al resultado en el chat.** El encargo va a 2º plano; se recupera
  con «¿y la respuesta de hermes?» o «resultado del encargo N».
- **No configura el modelo interno de Hermes por sí solo**: hace falta pasar por
  el HUD (Núcleo IA) o por el CLI de Hermes.
- **No toca `config/settings.json` ni `config/secrets.json` a espaldas del
  usuario** más allá de `hermes_api_key` y del proveedor/modelo que él mismo
  guarda desde el HUD.
