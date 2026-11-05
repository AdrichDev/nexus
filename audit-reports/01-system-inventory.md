# 01 — Inventario del sistema

## 1. Naturaleza del sistema

**nexus** es un asistente personal de escritorio al estilo JARVIS, de **un solo usuario**, que se ejecuta en local sobre Windows. **No es un SaaS**: no hay cuentas de usuario, organizaciones ni tenants. Todo se ejecuta en el equipo del propietario. El acceso remoto se resuelve con un token de vinculación compartido por QR, con un bot de Telegram y con un endpoint para n8n.

## 2. Tecnologías

| Capa | Tecnología | Evidencia |
|------|-----------|-----------|
| Backend | Python 3.12, FastAPI 0.139.2, Starlette 1.3.1, uvicorn 0.51.0 (versiones del `.venv`) | `requirements.txt`, `.venv` |
| Escritorio | pywebview (ventana sin marco) | `backend/desktop.py` |
| Frontend HUD | HTML, CSS y JS vanilla en módulos ES, Canvas y Chart.js | `frontend/` |
| Móvil | PWA (`frontend/mobile.html`, `sw.js`) y APK Android (WebView en Java) | `movil/` |
| Persistencia | Archivos JSON y JSONL en `data/`, grafo markdown en `data/memory/`, Postgres 16 con pgvector opcional en Docker (puerto 5433) | `backend/core/dominio/memory.py`, `skills/autoprovision` |
| ORM | Ninguno. psycopg2 directo, con DDL idempotente | `memory.py:_DDL` |
| Voz | faster-whisper (STT local), edge-tts, pyttsx3 (SAPI), ElevenLabs | `stt.py`, `tts.py` |
| LLM | Ollama (por defecto, `llama3.1`), OpenAI, Anthropic, Gemini, compatibles con OpenAI (OpenRouter, Groq, DeepSeek). LM Studio solo para descubrir modelos | `backend/core/infraestructura/llm.py` |
| Embeddings | Ollama `nomic-embed-text` (por defecto, solo local: `permitir_nube:false`). Hay alternativas de OpenAI y Gemini | `config.py`, `config/umbrales.json` |
| RAG | pgvector (tabla `memories`, `vector(768)`), JSONL local de reserva `data/rag/knowledge.jsonl` | `rag.py`, `memory.py` |
| Agentes externos | Hermes (pasarela de agente en `127.0.0.1:8642`), Engram (binario Go en `127.0.0.1:7437`), servidores MCP por stdio | `skills/hermes`, `engram_bridge.py`, `skills/mcp_hands` |
| Automatización | n8n (externo; webhooks a `/api/n8n`), scheduler interno, JobManager | `config/n8n_*.json`, `scheduler.py`, `jobs.py` |
| Empaquetado | PyInstaller (`installer/nexus.spec`) e instalador NSIS. **Sin firma de código** | `installer/` |
| CI | GitHub Actions: `pip-audit` y Trivy. **No ejecuta los tests** | `.github/workflows/security-ci.yml` |

## 3. Integraciones de terceros

| Servicio | Uso | Credencial | Almacenamiento |
|----------|-----|-----------|----------------|
| Google (Gmail, Calendar, Tasks, Drive) | Leer y **enviar** correo, eventos, tareas, Drive completo | OAuth de escritorio | `config/google_token.json` (en claro) |
| Telegram Bot API | Control remoto | Token del bot | `secrets.json` / env |
| Spotify | Reproducción | OAuth | `config/spotify_token.json` (en claro) |
| Instagram Graph API | Análisis (`business_discovery`) | Token | Pasado por env al subproceso |
| Open-Meteo / wttr.in | Tiempo | — | — |
| DuckDuckGo / Google (navegador) | Búsqueda web | — | Caché en `data/webcache.json` |
| YouTube | Transcripciones (yt-dlp y HTTP) | — | — |
| ElevenLabs | TTS | API key | `secrets.json` |
| Home Assistant / TV Samsung / WoL | Domótica | Tokens de dispositivo | `secrets.json` |
| Discord | Webhook | URL | Configuración |
| GitHub Releases | Instalación automática de Engram (con SHA-256 verificado) | — | — |

## 4. Puntos de entrada

| Entrada | Quién | Autenticación |
|---------|-------|---------------|
| HUD local (pywebview → `127.0.0.1:8177`) | Propietario | **Ninguna** (confianza por loopback) |
| `WS /ws` | HUD, móvil | Loopback con Host y Origin validados, o token del QR |
| 88 rutas HTTP en `backend/app.py` | HUD, móvil | Loopback sin token, o token del QR (query, cabecera o cookie) |
| LAN y túnel (cloudflared, Tailscale) | Móvil | Token del QR |
| Bot de Telegram (long polling) | Propietario por TOFU | `chat_id` del primer contacto (SEC-02) |
| `POST /api/n8n` | Flujos n8n | Solo confianza por loopback (SEC-01) |
| Micrófono / palabra de activación / palmadas / F9 | Propietario físico | — |
| Scheduler y background loops | Sistema | — |
| Contenido externo hacia los prompts: web, correo, transcripciones, documentos ingeridos, MCP, Engram | Terceros | **Contenido no confiable** |

## 5. Mapa de componentes y límites de confianza

```
 [Navegador/otros procesos locales] --(loopback, sin token)--+
 [HUD pywebview] --(loopback)-----------------------------------+--> FastAPI app.py (88 rutas + /ws)
 [Móvil LAN/túnel] --(token QR, HTTP en claro en WiFi)---------+          |
 [n8n local] --(loopback, sin secreto)--------------------------+          v
 [Telegram] --(TOFU chat_id)--> telegram_bridge -------------------> brain.process (orquestador)
                                                                         |  regex route (skills_loader)
                                                                         |  -> planificador LLM (solo text/voice)
                                                                         v
                                   30 skills (ficheros, shell restringido, Google, domótica, datos...)
                                                                         |
               +-------------------+------------------+-----------------+------------------+
               v                   v                  v                 v                  v
        data/*.json(l)       Postgres+pgvector    Ollama local    LLM en la nube     Engram/Hermes/MCP
        grafo markdown       (Docker :5433)       (:11434)        (OpenAI/Anthropic/  (loopback, sin auth)
        logs, backups zip                                         Gemini/OpenRouter)
```

**Límites de confianza principales**

1. **Loopback ↔ resto de la red.** Todo lo que llega por loopback se trata como el propietario.
2. **Equipo ↔ proveedores LLM en la nube.** El contexto personal sale del equipo (ver `05`).
3. **Contenido de terceros ↔ prompt.** No hay marcado de contenido no confiable.
4. **Canales remotos (móvil, Telegram, n8n) ↔ skills con efectos.**

## 6. Skills (30)

`ai_media, autoprovision, backup, billing, chrome, clima, coach, comms, content_os, datos, dev_knowledge, devils_advocate, discord, domotica, engram, files, games, google_workspace, hermes, instagram, mcp_hands, media, memory_graph, n8n_flows, nucleo, places, research, system_pc, tasks_board, telefono, tools, vigilancias`

En `02-architecture-review.md` y en el informe de skills (sección 3) se resume qué efectos laterales tiene cada una y si piden confirmación.

## 7. Workers y procesos de fondo

- `scheduler_loop` (tick de 5 s): métricas, recordatorios, ingesta de `inbox/`, avisos del tablero, briefing, vigilancias, consolidación y backup diario (`scheduler.py:122-195`).
- `cycle_loop` (cada 6 h): reindexado RAG (≤40) y reentrenamiento del perfil (`background.py:67-82`).
- `proactive_loop` (cada 30 min) (`background.py:85-97`).
- `JobManager`: hasta 4 trabajos concurrentes, persistidos en `data/jobs.json` (`jobs.py`).

## 8. Dependencias entre proyectos

- `knowledge/` contiene 390 archivos de skills de terceros (`awesome-copilot`). Es material de contexto, no código que se ejecute.
- `openspec/` y `odd/` son artefactos de proceso.
- No se han encontrado dependencias de código con otros repositorios.
