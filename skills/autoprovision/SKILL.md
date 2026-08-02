# Auto-provisión (autoprovision)

nexus levanta y conecta **su propia infraestructura local** bajo tu orden: Docker,
Ollama, n8n y el bot de Telegram. Todo se ejecuta en tu máquina, en el mismo
proceso que el backend.

## Qué hace y con qué frases

- **Diagnóstico** — «revisa tu infraestructura», «revísame la infraestructura»,
  «comprueba tus servicios», «cómo están tus conexiones», «ponte en marcha».
  Informe de Docker, la memoria pgvector, Ollama (con el modelo activo), n8n y
  Telegram. Solo lectura.

- **Docker** — «levanta docker», «levántame los contenedores», «arranca la bd»,
  «enciéndeme la base de datos», «pon en marcha el docker». Ejecuta
  `docker compose up -d` sobre el primer compose que encuentre por este orden:
  `config/docker-compose.yml` (el que genera nexus), `docker-compose.nexus.yml`
  en la raíz, y los dos de la carpeta hermana `nexus_stack/`.

- **n8n** — «configura n8n», «configúrame n8n», «crea el flujo», «importa el
  workflow». Si n8n responde y hay una API key guardada en ⚙, **te pregunta antes**
  y solo entonces crea y activa el workflow router y guarda el webhook
  `/webhook/nexus`. Sin API key te explica cómo generarla
  (Settings → n8n API → Create API key).

- **Telegram** — «configura telegram <token>», «actívame el bot». Valida el token
  con `getMe`, lo guarda en `secrets.json` y te dice el @usuario del bot.

- **Modelos Ollama** — «prepara el modelo llama3.1», «descárgame el modelo qwen3»,
  «bájate el modelo gemma2». Si ya está en Ollama lo deja como modelo activo; si
  no, lo descarga del registro público y lo activa.

- **Arreglar Ollama** — «arregla ollama», «arréglame ollama», «mis modelos locales
  no aparecen». Compara `OLLAMA_MODELS` con las carpetas de modelos de ⚙. Si la
  variable está vacía la fija con `setx`; si ya apuntaba a otra ruta, **pregunta
  antes de sobrescribirla**. Después hay que reiniciar Ollama una vez.

## Necesita configurado

- **Docker Desktop** abierto para las órdenes de contenedores.
- **`n8n_api_key`** en ⚙ para crear flujos.
- **Ollama** arrancado para preparar o activar modelos.
- **`model_scan_paths`** en ⚙ → AI Core para que «arregla ollama» sepa a qué
  carpeta apuntar.

## Qué NO hace

- No borra contenedores, imágenes, volúmenes ni ficheros. `docker compose up`
  se lanza **sin** `--remove-orphans`.
- No crea el bot de Telegram: eso se hace una vez en @BotFather y aquí se parte
  del token.
- No genera el `docker-compose.yml`: lo escribe `backend/app.py`.
- No despliega nada en máquinas remotas.
