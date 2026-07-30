# 🪽 Hermes (subagente)

Delega encargos AGÉNTICOS en Hermes Agent (Nous Research, open source MIT):
navegar y automatizar el navegador con visión, investigación multipaso,
ejecutar código aislado, informes de mercado… Se lo pides a nexus y él se lo
encarga por la API local de Hermes (compatible OpenAI, por defecto
http://127.0.0.1:8642) COMO TRABAJO EN 2º PLANO: nexus sigue libre mientras
Hermes trabaja y te trae el resultado por el mismo canal (HUD, móvil o
Telegram). Cada encargo queda apuntado en `data/hermes_jobs.json`
(encargado → trabajando → hecho/error) y lo averiguado se vuelca también en
la memoria Postgres de nexus.

Además, nexus cuida la conexión él solo: si el gateway de Hermes está apagado
lo arranca (`hermes gateway run --replace`, con entorno limpio y log en
`data/hermes_gateway.log`), provisiona `~/.hermes/.env` (API_SERVER_ENABLED
más una API_SERVER_KEY fuerte, con backup `.bak_nexus`) y sincroniza la clave
con `config/secrets.json` (`hermes_api_key`). También puede delegar SOLO, sin
que digas «hermes», cuando el encargo pinta agéntico y ninguna skill local
casa.

## Enganchado a Engram (memoria de proyecto compartida con nexus)

Si tienes Engram instalado, nexus engancha a Hermes a la MISMA memoria de
proyecto que usa él, por la vía nativa de Hermes: añade un servidor **MCP
'engram'** a `~/.hermes/config.yaml` (bajo `mcp_servers:`) que arranca
`engram mcp --project nexus` por stdio. Así Hermes obtiene sus tools
`mem_save` / `mem_search` / `mem_context` sobre la misma base (`~/.engram`,
proyecto «nexus»): lo que Hermes decide o averigua queda en la memoria de
proyecto, y Hermes ve lo que decidió nexus. Esto es la memoria de PROYECTO
(decisiones/bugs/features del código), distinta de tu memoria PERSONAL.

nexus lo provisiona solo la próxima vez que arranca el gateway (cirugía de
texto sobre el `config.yaml`, sin tocar el resto, con backup `.bak_nexus`, e
idempotente). Un Hermes ya arrancado lo carga en su siguiente reinicio (o con
`/reload-mcp` dentro de su chat). Si Engram no está instalado, no se configura
nada. Compruébalo con «diagnostica hermes» (línea «Engram (memoria de
proyecto)»).

## Órdenes de ejemplo (los patterns las cazan tal cual)

- «hermes: investiga la competencia y hazme un informe»
- «dile a hermes que busque proveedores»
- «mándale una tarea a hermes: resume las noticias de El País»
- «mándale a hermes que compare precios de portátiles»
- «¿está hermes conectado?» / «¿qué tal va hermes?»
- «diagnostica hermes» (radiografía completa: instalación, puerto, .env,
  clave y prueba real del cerebro interno)
- «arranca hermes» / «reinicia hermes» / «relanza hermes»
- «¿y la respuesta de hermes?» / «¿ha terminado ya hermes?»
- «¿qué ha averiguado hermes?» / «novedades de hermes»
- «¿qué sabe hacer hermes?» / «¿qué skills tiene hermes?» (se lo pregunta en
  vivo a su API: /v1/capabilities y /v1/skills)

## Notas técnicas

- Requiere Hermes Agent instalado (hermes-agent.nousresearch.com). El CLI se
  autodetecta en `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\hermes.exe`
  (o `~/.hermes/hermes-agent/venv/bin/hermes`); si está en otra ruta, ponla
  en ⚙ `hermes_exe`. URL del gateway en ⚙ `hermes_url`; autoarranque
  desactivable con ⚙ `hermes_autostart=false`.
- Clave del gateway: Bearer `hermes_api_key` en `config/secrets.json`. Si el
  `.env` de Hermes tiene clave fuerte se adopta; si no, nexus la genera y la
  escribe en ambos lados (idempotente: si ya está bien, no toca nada).
- Cerebro interno de Hermes: un 401 «Missing Authentication header» NO es la
  clave del gateway — es su proveedor LLM sin credenciales. Se arregla desde
  el HUD (Núcleo IA → guarda proveedor/modelo/clave; llama a
  `/api/hermes/configure`, que escribe `~/.hermes/.env` y el bloque `model:`
  de `~/.hermes/config.yaml`) o en terminal con «hermes model» + «hermes auth
  add <proveedor>». Proveedores mapeados: openai, anthropic, gemini,
  openrouter.
- Resiliencia de encargos: 5xx → relanza el gateway con entorno limpio (sin
  PYTHONPATH/VIRTUAL_ENV heredados, que lo rompían) y reintenta una vez;
  401 «invalid_api_key» → re-provisiona la clave y reintenta una vez.
- Dependencia: `httpx` (ya en requirements.txt). Timeout de encargo: 15 min.
