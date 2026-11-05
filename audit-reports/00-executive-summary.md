# 00 — Resumen ejecutivo

**Sistema**: nexus, un asistente personal de escritorio (FastAPI + pywebview) de un solo usuario. Lo acompañan una app móvil, un bot de Telegram, n8n, varios proveedores LLM (local y en la nube), RAG con pgvector y 30 skills con efectos reales: ficheros, Google, domótica y teléfono.

**Revisión auditada**: `fix/youtube-verification` @ `908924b`.

**Método**: análisis estático en solo lectura con 4 exploradores por dominio, verificación directa de los puntos clave y contraste independiente de los hallazgos Alta y Media. Detalle en `12-audit-coverage.md`.

## 1. Valoración general

Es un proyecto **por encima de la media en disciplina de ingeniería** para su tamaño:

- capas verificadas por un test;
- un aprendizaje automático con puertas que deniegan por defecto;
- una purga en dos pasos;
- honestidad anti-invención aplicada en el código;
- un escáner de secretos antes de subir;
- muchos tests construidos a partir de frases reales.

La auditoría anterior (2026-09-30) cerró sus dos riesgos más graves: el WS sin validar Origin y el shell con texto libre.

El riesgo actual **no está en un fallo puntual**. Está en **tres huecos transversales**:

1. **Autorización por canal**: cada interceptor y cada skill decide por su cuenta. Por eso el canal n8n puede enviar correos y escribir memoria, y Telegram confía en el primero que llega.
2. **Nivel de efecto**: las acciones con efecto externo se confirman de forma asimétrica. El borrado pide «sí»; el envío de correo, no.
3. **Contenido no confiable**: no hay marcado para la web, el correo y las memorias, y la memoria operativa se inyecta como «órdenes».

**Ninguna vulnerabilidad Crítica confirmada. Ningún secreto comprometido en el repositorio ni en su historial.**

## 2. Riesgos principales

| ID | Sev. | Riesgo | Condición |
|----|------|--------|-----------|
| SEC-01 | Alta | `/api/n8n` sin secreto y un flujo de ejemplo con webhook público: texto de WhatsApp de terceros → enviar correos, WhatsApps y escribir memoria persistente | El flujo de ejemplo está importado y accesible |
| SEC-02 | Alta | Telegram: el primer chat que escribe se queda como propietario permanente con control total | Bot sin propietario o `owner.txt` perdido |
| SEC-03 | Media | DNS rebinding sobre la API en loopback (sin validar Host) → robo del token del QR | Navegador sin protección LNA/PNA. No demostrado |
| SEC-04 | Media | `perm_files="todo"` por defecto: amplifica cualquier compromiso hasta la lectura de cualquier archivo | — |
| SEC-05 | Media | `send_email` sin confirmación ni idempotencia, con el cuerpo redactado por el LLM | — |
| SEC-06 | Media | Memoria operativa inyectada como «órdenes», escrita sin confirmación desde cualquier canal. Engram local sin autenticación | Alta si se encadena con SEC-01 o SEC-02 |
| AI-01 | Media | Fallback silencioso de Ollama local a la nube, con prompts cargados de memoria personal | Hay una key de la nube configurada |
| AI-02 | Media | Interacciones crudas sin redactar en disco y enviadas al destilado del perfil | — |

Detalle completo en `03-security-findings.md` y `05-ai-llm-rag-audit.md`.

## 3. Superficies más expuestas

1. El webhook de n8n (si está publicado).
2. El bot de Telegram.
3. El navegador del propietario (rebinding hacia loopback).
4. La WiFi local, por el HTTP en claro del móvil (SEC-08).
5. El contenido de terceros que llega a los prompts (correo, web, YouTube).

## 4. Puntuaciones por dimensión (0-10)

**Criterio**:

- 10 = controles completos, probados y sin hallazgos ≥ Media;
- 7 = controles sólidos con huecos acotados;
- 5 = controles parciales y hallazgos Media significativos;
- 3 = hallazgos Alta sin mitigar;
- 0 = sin controles.

Las puntuaciones se ponderan por la **cobertura** de la auditoría. **No son una certificación.**

| Dimensión | Nota | Cobertura | Justificación |
|-----------|------|-----------|---------------|
| Calidad arquitectónica | 7 | Alta | Monolito modular adecuado y capas con test. `brain.process` y `app.py` son demasiado grandes. Falta una política central (ARQ-01/03) |
| Seguridad de aplicación | 5 | Alta | Buen token, buen WS y sin shell libre. Hay dos Altas condicionales y Host sin validar |
| Gestión de secretos | 6 | Alta | Repositorio limpio y escáner. Secretos en claro en disco, con documentación que dice lo contrario |
| Multitenancy | N/A | — | Monousuario. No está preparado para SaaS (ver `04`) |
| Madurez de IA | 6 | Media-Alta | Excelentes puertas de aprendizaje y honestidad. Faltan límites de agencia, privacidad del fallback y marcado de contenido no confiable |
| Privacidad | 5 | Media | Redacción al persistir y embeddings locales. Logs sin redactar, supresión incompleta y fallback a la nube |
| Fiabilidad y recuperación | 6 | Media | Degradación excelente. JSON no atómicos y restauración nunca probada |
| Escalabilidad | N/A (7 para 1 usuario) | Media | Adecuada a su propósito |
| DevSecOps y testing | 5 | Media | Muchos tests y escáneres en CI, pero los tests no se ejecutan en CI, no hay lockfile y faltan tests en las fronteras de confianza |

## 5. Deuda técnica prioritaria

1. Política de canal y efecto centralizada en `brain` (ARQ-01/03).
2. Escrituras atómicas (ARQ-05).
3. Tests en CI y lockfile.
4. División de `app.py`.

## 6. Recomendaciones principales (ver `09-remediation-roadmap.md`)

- **P0** (horas): comprobar si el webhook de n8n de ejemplo está activo y si el bot de Telegram ya tiene propietario.
- **P1** (≈1 semana en total, cada ítem de esfuerzo S):
  1. secreto y allowlist para n8n;
  2. código de vinculación para Telegram;
  3. validar Host y Origin en HTTP y retirar el token de `/api/link/status`;
  4. confirmación e idempotencia en los envíos;
  5. fallback a la nube solo con consentimiento y redacción de logs;
  6. `perm_files` seguro por defecto con denylist.
- **P2**: política central, opmem con confirmación, triaje de correo con aprobación, Android, cifrado con DPAPI, CI con tests y supresión completa.

---

## 7. Preguntas obligatorias (Fase 10)

| # | Pregunta | Respuesta | Evidencia / estado |
|---|----------|-----------|--------------------|
| 1 | ¿Podría un usuario acceder a datos de otro usuario o empresa? | **No aplica**: hay un único usuario. Sí podría hacerlo un **tercero no autorizado** por SEC-01 (n8n), SEC-02 (Telegram) o SEC-03 (rebinding) | `04`, `03` |
| 2 | ¿Podría una API devolver datos sin permiso? | Sí, con condiciones: `GET /api/link/status` entrega el token a cualquier llamante en loopback, incluidos procesos locales y páginas tras un rebinding. `/api/note` **no** es vulnerable a traversal (verificado) | SEC-03 |
| 3 | ¿Hay secretos expuestos? | **No en el repositorio ni en el historial** (comprobado). **Sí en claro en disco** (`secrets.json`, tokens OAuth), aunque `CLAUDE.md` diga «cifradas» | `08` §4, SEC-09 |
| 4 | ¿Podrían filtrarse datos sensibles por logs, errores, cachés o backups? | Sí: `interactions.jsonl` y `audit.jsonl` sin redactar; backups zip sin cifrar en el mismo disco; `str(exc)` en algunos endpoints. El chat sí se limpia | AI-02, PRIV-01/04, SEC-16 |
| 5 | ¿Podría un agente de IA realizar una operación no autorizada? | El planificador solo elige skills e intents existentes y solo desde canales de confianza. Pero sus argumentos no se validan, `perm_files` es `todo` y hay acciones externas sin confirmar (correo, Google desde correos, Hermes) | AI-05/06, SEC-05/07 |
| 6 | ¿Podría un documento malicioso manipular el RAG o el agente? | Sí, en la **respuesta** (no hay marcado de contenido no confiable) y en la **creación de tareas y eventos** desde correos. Para escribir **reglas persistentes** hace falta que el texto entre por un canal que llegue a `brain.process` (n8n o Telegram) | AI-03, SEC-06/07 |
| 7 | ¿Podría un proveedor LLM recibir datos que no debería? | Sí: por el fallback silencioso a la nube y por el destilado de interacciones crudas | AI-01/02 |
| 8 | ¿Las automatizaciones podrían ejecutar acciones duplicadas? | Envíos (correo, WhatsApp, Telegram): sí, no hay idempotencia. Hermes reintenta en 5xx/401. Los jobs y el triaje de correo sí deduplican | `07` §4 |
| 9 | ¿Riesgo de pérdida o corrupción de datos? | Sí, si el proceso cae a mitad de escribir `board.json` o `jobs.json` (escritura no atómica). La configuración está protegida. La restauración de backups no está probada | ARQ-05, `07` §3 |
| 10 | ¿Qué pasa si la BD deja de responder? | Degradación ordenada al grafo markdown (verificado en el código) | C-memoria, `07` |
| 11 | ¿Y si cae el proveedor principal de IA? | Si hay keys de la nube, cambio **silencioso** a la nube (problema de privacidad). Si no, `SinCerebro` con un mensaje honesto, sin respuestas enlatadas | AI-01 |
| 12 | ¿Qué no escalaría? | Estado global (historial, confirmaciones, opmem), una sola conexión a Postgres, el LLM local en serie y los JSON en disco. Es adecuado para un usuario | `07` §2 |
| 13 | ¿Qué podría provocar costes inesperados? | El fallback a la nube, la falta de `max_tokens` y de presupuesto, y los canales no confiables que disparan LLM (n8n, Telegram secuestrado) | `07` §5 |
| 14 | ¿Podría un usuario manipular su `tenant_id`? | No existe `tenant_id`. El `channel` del body solo decide qué aparato habla | `04` |
| 15 | ¿Hay separación real entre desarrollo y producción? | **No.** Es una aplicación local: desarrollo y uso real comparten equipo, `data/` y cuentas. Las sondas herméticas en Docker sin red sí ofrecen un entorno aislado para pruebas | `08` |
| 16 | ¿Se pueden reconstruir los incidentes con los logs? | Parcialmente: `audit.jsonl` (con `run_id`), `jobs.json`, `nexus.log` y `/why`. Pero la rotación es de una sola generación de 1-2 MB, no hay un id de correlación HTTP, no se registra la IP o el dispositivo en cada acción, y no hay integridad de los logs | `06`, `07` |
| 17 | ¿Se puede restaurar y verificar la integridad? | Hay backups, pero **la restauración no está automatizada ni probada** y no hay verificación de integridad | `07` §3 |
| 18 | ¿Están protegidas las integraciones OAuth y los webhooks? | Google: OAuth de escritorio con loopback, pero tokens en claro y scopes amplios (`drive` completo, `gmail.send`). Spotify sin `state`. **Webhook de n8n sin autenticación** | SEC-01/09/15 |
| 19 | ¿Qué pruebas críticas faltan? | Las fronteras de confianza: Host en HTTP, n8n, Telegram, `confirm.py`, `path_allowed`, fallback LLM, inyección de prompts y restauración. Además, **los tests no se ejecutan en CI** | `08` §5 |
| 20 | ¿Qué decisiones arquitectónicas conviene replantear? | La autorización distribuida por skill → política central por canal y efecto. La inyección de opmem como «órdenes». Por defecto `perm_files=todo`. El fallback entre proveedores. **No** hace falta replantear el monolito | `02` |
| 21 | ¿Qué está bien y debe conservarse? | Ver `10` §«Qué conservar»: compare_digest, WS con Origin, ausencia de shell libre, `datos` de solo lectura en dos capas, `confirm.py`, `as_dict()`, escritura atómica de la configuración, redacción al persistir, escáner de secretos, privacidad de OpenRouter, embeddings locales, puertas de aprendizaje, `correcciones`, purga en dos pasos, `_restore` de jobs y límites anti-bucle | `10` |
| 22 | ¿Qué vulnerabilidades aparecerían al convertirlo en SaaS? | Prácticamente todas las del borde: confianza por loopback, token compartido, skills de sistema que serían RCE entre clientes, RAG y opmem globales, cachés sin clave de tenant, secretos en claro y ausencia de cuotas | `04` §4 |
| 23 | ¿Riesgos con ×100 usuarios? | Sin multitenancy no es posible de forma segura. Con ×100 dispositivos: contención del LLM y del broadcast del bus | `07` §2 |
| 24 | ¿Qué depende demasiado de la IA? | Redactar correos que se envían sin revisión, crear tareas y eventos desde correos, el perfil destilado que se inyecta siempre y el planificador como último recurso del routing (la propia documentación lo señala como fuente de invenciones) | `05` |
| 25 | ¿Qué riesgos importantes no cubre la lista? | (a) **Agentes de desarrollo con acceso al repositorio y a Engram compartido**: Claude Code, Pi y Cursor pueden leer y escribir la memoria que nexus trata como órdenes. (b) **La app Android y su puente JS** (llamadas y WhatsApp forzados por MITM en WiFi). (c) **El ecosistema `knowledge/`** de 390 archivos de terceros que agentes pueden cargar como instrucciones. (d) **Distribución sin firmar** del `.exe`. (e) **Ransomware o pérdida del disco**: los backups están en el mismo disco | `05`, SEC-08, `08` |

---

**Índice de informes**: `01` inventario · `02` arquitectura · `03` hallazgos · `04` multitenancy · `05` IA/RAG · `06` privacidad · `07` fiabilidad y costes · `08` DevSecOps y tests · `09` roadmap · `10` controles verificados · `11` preguntas abiertas · `12` cobertura.
