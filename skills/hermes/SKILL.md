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
  gemini, openrouter.
- **Dependencia**: `httpx` (ya en `requirements.txt`).

## Autoarranque y resiliencia

Si el gateway está apagado, nexus lo levanta (`hermes gateway run --replace`,
con entorno limpio —sin `PYTHONPATH`/`VIRTUAL_ENV` heredados, que rompían su
Python— y log en `data/hermes_gateway.log`) y espera hasta 60 s.

- 5xx → relanza el gateway limpio y reintenta una vez.
- 401 `invalid_api_key` → re-provisiona la clave y reintenta una vez.
- 401 «Missing Authentication header» → no reintenta; explica que falta
  configurar el modelo interno de Hermes.
- Respuesta 200 cuyo TEXTO es un error del proveedor → el encargo consta como
  fallido, no como terminado.

Timeout de encargo: 15 min.

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
