# 07 — Fiabilidad, escalabilidad, disponibilidad y costes

> **No se ha medido nada.** Todas las cifras de carga son escenarios hipotéticos y estimaciones cualitativas a partir del código. No se han hecho pruebas de carga.

## 1. Modelo de ejecución

- Un proceso uvicorn con un bucle asyncio, en un PC de escritorio.
- Estado en memoria y en archivos de `data/`. Postgres es opcional, con **una sola conexión** (sin pool, `connect_timeout=2s`, autocommit; `memory.py:198-210`).
- Cliente HTTP compartido con un timeout de 60 s y redirecciones (`net.py:42`).
- `JobManager` con un semáforo de 4 (`jobs.py`).

## 2. Escalado (pregunta: 10 / 100 / 1.000 / 10.000 usuarios simultáneos)

El sistema está diseñado para **1 usuario y unos pocos dispositivos vinculados**. Los escenarios sirven para identificar cuellos de botella, no como objetivo.

| Escenario | Estimación teórica | Primer cuello de botella |
|-----------|-------------------|--------------------------|
| 10 clientes (dispositivos o WS) | Viable. El bus de eventos reenvía a todos los WS | Llamadas síncronas en el bucle (la auditoría anterior señaló `get_index()` con hasta 25 s; `remote.status()` ya se movió a `to_thread`) |
| 100 | Degradación. Las órdenes concurrentes compiten por un único LLM local (Ollama atiende en serie por defecto) y por una sola conexión psycopg2 síncrona | LLM local, conexión a la BD, escrituras JSON no atómicas (`board.json`, `jobs.json`) |
| 1.000 | No viable. El estado es global (historial de conversación, confirmaciones pendientes por canal, opmem). No hay aislamiento de sesión | Arquitectura: estado compartido, sin identidad por usuario |
| 10.000 | No aplica sin rediseño (ver `04`, SaaS) | — |

**Si la base de usuarios se multiplicara por 100** (pregunta 23): sin multitenancy no tiene sentido. Con 100 dispositivos de un mismo usuario, los problemas serían la contención del LLM y el broadcast del bus.

## 3. Disponibilidad y degradación

| Fallo | Comportamiento observado en el código | Evaluación |
|-------|----------------------------------------|------------|
| Postgres caído | `pg.online=False` → todo funciona con el grafo markdown. El scheduler omite las tareas que dependen de la BD | Bien diseñado (verificado en el código) |
| Ollama caído | **Fallback silencioso a la nube si hay key** (AI-01). Sin key → `SinCerebro`, con un mensaje honesto | Disponibilidad a costa de la privacidad |
| Proveedor en la nube caído | Los errores se convierten en mensajes públicos (`llm_runtime.py:148-215`). Sin circuit breaker ni backoff | Aceptable para un solo usuario |
| API de Google o Telegram caída | Errores por llamada. El bucle de Telegram sigue vivo | No verificado en detalle |
| Engram o Hermes caídos | Caché de salud de 60 s. Funciones opcionales | Correcto |
| Cierre brusco del proceso | `settings`/`secrets` son atómicos. **`board.json`, `jobs.json`, `contentos` y `proactive.json` no lo son** (ARQ-05) | Riesgo de corrupción |
| Reinicio a mitad de un trabajo | `_restore()` marca los trabajos en curso como `failed` («nexus se reinició») | Correcto: no se reejecuta a ciegas |
| Reinicio y recordatorios | La auditoría de exploración no encontró en el scheduler una marca de «último disparo» (`scheduler.py:138-145`). Posible duplicado o pérdida de avisos alrededor de un reinicio | Potencial, no verificado |

**Puntos únicos de fallo**: el PC (todo es local), Ollama si es el único proveedor y Docker para Postgres. Es aceptable para el dominio.

**Health checks**: `GET /api/status` (métricas, backend de memoria, STT, TTS y LLM). No hay readiness ni liveness separados, pero no hace falta fuera de un orquestador.

**DR, RPO y RTO**:

- Backup zip diario de `data/` con 7 copias (`skills/backup`). RPO ≈ 24 h.
- **La restauración no está automatizada ni probada.** La skill explica cómo restaurar, pero no restaura (`skills/backup/skill.py:12`).
- Los backups están en el **mismo disco** que los datos: un fallo de disco o un ransomware se llevaría ambos.
- RTO desconocido.
- `config/` (secretos y tokens) no forma parte del backup (no verificado del todo). Tras perder el equipo hay que volver a vincular OAuth.

## 4. Automatizaciones e idempotencia

| Proceso | Duplicados | Evidencia |
|---------|------------|-----------|
| Jobs | Deduplicación de los activos (`active_duplicate`, `request_id`) | `jobs.py` |
| Triaje de correo → Google | Deduplicación por id de correo | `skill.py:1387,1406` |
| Backup diario | Una vez al día (comprueba si existe el de hoy) | `scheduler.py:191-195` |
| `send_email`, WhatsApp, Telegram | **Sin idempotencia** | SEC-05 |
| Hermes | **Reintenta en 5xx/401**: puede duplicar efectos | `hermes/skill.py:995-1010` |
| Scheduler | Todo dentro de un único `try/except`: el bucle sobrevive. Sin DLQ (no hace falta) | `scheduler.py:122-195` |

## 5. Costes y consumo

| Riesgo | Evidencia | Mitigación existente | Recomendación |
|--------|-----------|---------------------|---------------|
| Llamadas a la nube sin presupuesto | No hay contador de tokens ni límite diario | Cachés (web 30/5/60 min, proveedor 30 s), lotes de correo (6 en Ollama / 30 en la nube, ≤100 por pasada) | Contador diario de llamadas y tokens por proveedor, con un límite configurable y un aviso al 80 % |
| Sin `max_tokens` (salvo Anthropic) | `llm.py:244-257` y siguientes | — | Fijar `max_tokens` (por ejemplo, 1024-2048) y `num_predict` en Ollama |
| Fallback a la nube no previsto | AI-01 | — | Consentimiento |
| Canales no confiables que disparan LLM (n8n o Telegram secuestrado) | SEC-01 y SEC-02 | n8n no llega al planificador | Corregir SEC-01 y SEC-02 y añadir un límite de velocidad por canal |
| Bucles de fondo | `cycle_loop` cada 6 h (1 destilado y ≤40 embeddings), proactivo cada 30 min sin LLM | Autolimitados (verificado) | — |
| Descarga de modelos de Ollama con `timeout=None` | `autoprovision/skill.py:154` | Iniciada por el usuario | Aceptable |
| Logs y backups | Rotación de 1-2 MB; 7 zips de hasta 50 MB por archivo | — | Vigilar el tamaño del zip |

## 6. Pruebas de carga seguras (si se desea)

- **Solo en una copia aislada** (sin cuentas reales y con un LLM `mock` explícito), con Locust o k6 contra `127.0.0.1:8177`.
- `POST /api/command` con frases de solo lectura («qué hora es»), 1 → 20 usuarios virtuales. Medir p50/p95 y la latencia del bucle de eventos (un endpoint `/api/status` en paralelo).
- Hacer lo mismo con 20 conexiones WS para medir el broadcast del bus.
- Criterio: p95 de `/api/status` por debajo de 200 ms mientras hay carga (detecta llamadas que bloquean el bucle).
