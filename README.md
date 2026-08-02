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
│            WebSocket + REST│ http://127.0.0.1:8177          │
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

## Instalación

```bat
git clone <repo> nexus
cd nexus
setup.bat          :: crea .venv, instala deps, copia .env y settings.json
```

Opcional pero recomendado — memoria a largo plazo (Docker):

```bat
cd ..\nexus
nexus_up.bat      :: levanta Postgres+pgvector en :5433 y el engine nexus
```

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
Tus flujos también pueden dar órdenes a nexus llamando a `POST /api/n8n`.

## Micro abierto (conversación fluida)

Botón **∞ AUTO** del HUD: nexus escucha continuamente, corta cuando dejas de
hablar (detección de silencio), responde con voz y vuelve a escuchar — sin
pulsar F9 cada vez. Requiere voz real instalada (faster-whisper + sounddevice,
ya incluidas en requirements.txt).

## Grafo de conocimiento (◈ NODOS)

Botón **◈ NODOS**: mapa de nodos de colores — nexus en el centro, cada skill en
su órbita con su color, y tus notas de memoria como nodos cian. Pulsa
cualquier nodo y se abre su panel de acciones de un clic.

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
└── requirements.txt · .env.example · run.bat · INSTALAR_nexus.bat · SUBIR_A_GITHUB.bat
```

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
