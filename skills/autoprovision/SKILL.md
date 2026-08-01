# Auto-provisión (autoprovision)

nexus levanta y conecta **su propia infraestructura** bajo tu orden, en vez de
que tengas que hacerlo a mano. Todo se ejecuta en tu máquina (mismo proceso que
el backend), con acceso real a Docker, Ollama y n8n locales. Las acciones son
**aditivas y seguras**: no borra nada.

## Qué sabe hacer

- **Diagnóstico completo** — «revisa tu infraestructura», «cómo están tus servicios»,
  «ponte en marcha». Comprueba Docker, la base de datos pgvector, Ollama (y si el
  modelo activo está listo), n8n y el bot de Telegram, y te da un informe claro.

- **Docker** — «levanta docker», «arranca los contenedores», «enciende la base de datos».
  Ejecuta `docker compose -f docker-compose.nexus.yml up -d` (busca el compose en
  `nexus/` y en la raíz) y te muestra el estado.

- **n8n** — «configura n8n», «crea el flujo», «importa el workflow». Si n8n está vivo
  y hay una **API key de n8n** guardada en ⚙, crea y ACTIVA el workflow router por
  API y deja el webhook (`/webhook/nexus`) configurado. Sin API key, te explica en
  un paso cómo generarla (Settings → n8n API → Create API key).

- **Telegram** — «configura telegram <token>». Valida el token con `getMe`, lo guarda
  en `secrets.json` y te dice el @usuario del bot. (Telegram no permite crear el bot
  por API: eso se hace una vez en @BotFather; a partir del token, lo hace nexus.)

- **Modelos Ollama** — «prepara el modelo llama3.1», «descarga el modelo qwen3». Si ya
  está en Ollama lo deja como activo; si no, lo descarga del registro y lo activa.

- **Arreglar Ollama** — «arregla ollama», «mis modelos locales no aparecen». Detecta si
  `OLLAMA_MODELS` no apunta a tu carpeta de modelos (p.ej. `D:\LLMs`), la
  fija con `setx` y te pide reiniciar Ollama una vez para que los lea. Esto resuelve el
  típico «el modelo X no está en Ollama» cuando el modelo existe en tu carpeta pero
  Ollama no lo ve.

## Requisitos y notas

- **Docker Desktop** abierto para las órdenes de contenedores.
- **API key de n8n** en ⚙ para que nexus cree flujos por sí mismo (campo `n8n_api_key`).
- **Ollama** arrancado para preparar/activar modelos.
- Tras «arregla ollama» hay que **reiniciar Ollama** una vez (es la única forma de que
  relea `OLLAMA_MODELS`).

## Roadmap

Registrar un bot de Telegram de cero (sin @BotFather) y orquestar despliegues remotos
quedan fuera del alcance actual por diseño de esas plataformas; el resto lo hace nexus.
