# 02 — Revisión de arquitectura

## 1. Estilo arquitectónico

Es un **monolito modular** en un solo proceso, con asyncio, y una arquitectura de plugins (skills):

- `backend/core/` se organiza en capas: `aplicacion/` (orquestación), `dominio/` (reglas), `infraestructura/` (I/O externo) y `comun/` (transversal). Las capas están documentadas en `backend/core/CAPAS.md`.
- Hay un test ejecutable de capas (`tests/unit/core/runtime/test_capas_backend.py`). Declara **cuatro ciclos conocidos**: `llm↔llm_runtime`, `llm↔selflearn`, `rag↔memory` y `telegram_bridge↔brain`. La deuda está declarada, no oculta.
- Las skills siguen un contrato uniforme: `SKILL = {...}` + `async handle(intent, text, match, ctx)`. Ninguna skill importa `brain`.

**Valoración**: el estilo es **adecuado al tamaño real** (un usuario y un equipo). Microservicios, colas externas o CQRS **no** aportarían nada aquí; solo añadirían coste operativo. Las recomendaciones de abajo son locales.

## 2. Puntos fuertes (conservar)

| Aspecto | Evidencia |
|---------|-----------|
| Capas verificadas por un test | `test_capas_backend.py` |
| Contrato de skills aislado | `skills_loader.py`, `README.md` |
| Aprender de correcciones **escribiendo datos, nunca código**, con 4 puertas (campos, existencia, forma con anti-ReDoS y no-robo) y denegación por defecto | `reglas.py`, `aprendizaje.py` |
| Degradación ordenada: Postgres → grafo markdown, pgvector → JSONL → solapamiento de palabras, CUDA → CPU | `memory.py`, `rag.py`, `stt.py` |
| Escritura atómica de configuración (`.tmp` + `os.replace` + `.bak`) | `config.py:155-190` |
| Purga en dos pasos (vista previa → papelera → borrado definitivo con confirmación) | `purga.py` |
| Cancelación cooperativa de turnos de voz (épocas) | `voice_cycle.py` |
| Honestidad del LLM: reglas anti-invención y validador determinista de cifras | `llm.py:871-930`, `procedencia.py`, `contentos.py:401-420` |

## 3. Debilidades

| ID | Severidad | Hallazgo | Evidencia | Recomendación | Coste / inconvenientes |
|----|-----------|----------|-----------|---------------|------------------------|
| ARQ-01 | Media | `brain.process` es una función de unas 750 líneas con más de 15 interceptores en secuencia. El orden de las guardas (`source`, confirmación, memoria explícita) es implícito, y por eso SEC-01 y SEC-06 existen: cada interceptor decide por su cuenta si filtra por canal | `brain.py` (1532 líneas) | Extraer un **pipeline ordenado** de interceptores con una **política de canal centralizada** (`ChannelPolicy`: qué intents admite cada `source`/`channel`) | M. Riesgo de regresión en el routing. Exige primero los tests de `test_frases_reales.py` (ya existen) |
| ARQ-02 | Media | `app.py` concentra 88 rutas, middlewares, la lógica de setup (Docker), Hermes, Instagram y domótica | `backend/app.py` (1678 líneas) | Dividir con `APIRouter` por dominio (link, memoria, setup, integraciones). No cambia el comportamiento | S-M. Bajo riesgo |
| ARQ-03 | Media | No existe una **capa de autorización de acciones**. La confirmación (`confirm.py`) se aplica skill a skill, así que hay asimetrías: borrar un evento pide confirmación, enviar un correo no (SEC-05) | `skills/*/skill.py` | Declarar en `SKILL` un nivel de efecto por intent (`read`, `write_local`, `external_send`, `destructive`) y hacer que `brain` exija confirmación según el nivel y el canal | M. Es la mejora con mayor reducción de riesgo por línea |
| ARQ-04 | Baja | Routing por la primera regex que casa, en orden alfabético de carpeta | `skills_loader.py`, `CLAUDE.md` | Prioridad explícita por intent. No conviene reescribirlo | M |
| ARQ-05 | Baja | Persistencia JSON no atómica en `board.py`, `jobs.py` y `contentos.py` (`write_text` directo), mientras `config.py` ya tiene `_write_json_atomic` | `board.py:221-226`, `jobs.py:95-100` | Reutilizar `_write_json_atomic` | S. Ganancia clara contra la corrupción por cierres bruscos |
| ARQ-06 | Baja | 660 apariciones de `except Exception` (dato de la auditoría anterior). Es una política deliberada de fallo blando; el problema real es «excepción tragada seguida de un mensaje de éxito» | Toda la base | Revisar con grep solo el patrón problemático | S |
| ARQ-07 | Baja | Varios `_norm()` casi duplicados | `opmem.py`, `board.py`, `jobs.py`, `app_index.py`, `vigilancias` | Un helper en `comun/` | S |
| ARQ-08 | Info | Esquema evolucionado con `ALTER TABLE ... IF NOT EXISTS`, sin versionado | `memory.py:213-260` | Una tabla `schema_version` y migraciones numeradas cuando cambie el esquema | S. No es urgente con un solo usuario |

## 4. Validación y contratos

- Hay modelos Pydantic para unos pocos endpoints (`Command`, `SayText`, `LLMActivate`). Muchos otros aceptan `payload: dict` (por ejemplo `/api/n8n`, `/api/config`). Son cómodos, pero dejan sin validar los campos y su tipo.
- Los argumentos del planificador LLM se pasan como cadenas libres (`_LLMMatch`) sin un esquema por intent (ver `05`).

## 5. Gestión de errores

- Hay un buen saneado en la cara pública del chat (`publicvoice.sanitize`).
- Algunos endpoints devuelven `str(exc)` (SEC-16).
- Falta un handler global de excepciones con un id de correlación.

## 6. ¿Es adecuada la arquitectura?

Sí, para su propósito actual. El riesgo no está en la forma macro, sino en tres huecos **transversales** que hoy se resuelven skill a skill:

1. autorización por canal;
2. nivel de efecto y confirmación;
3. marcado de contenido no confiable.

Centralizar esos tres aspectos en `brain` (ARQ-01 y ARQ-03) tiene un coste moderado y elimina la causa común de SEC-01, SEC-05, SEC-06 y SEC-07.
