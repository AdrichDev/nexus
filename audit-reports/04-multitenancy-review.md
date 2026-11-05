# 04 — Multitenancy y aislamiento

## 1. Aplicabilidad

**No aplica en el estado actual.** nexus es **monousuario** y se ejecuta en local:

- No existen las entidades usuario, tenant, empresa ni organización en el código.
- La única identidad es «el propietario», que se establece de tres formas:
  - por loopback (el propio equipo);
  - por un token compartido único (`link_token`, `remote.py`), igual para todos los dispositivos vinculados;
  - por el `chat_id` de Telegram (TOFU).
- La tabla `memories` (pgvector) no tiene `tenant_id` ni `user_id`. Toda recuperación RAG se hace sobre un único espacio de nombres (`memory.py:1096-1140`).
- No hay RLS, esquemas por cliente ni bases por cliente.

Esto **no es un defecto** en el modelo actual. Sí es un límite de diseño que conviene conocer antes de cualquier evolución.

## 2. Respuesta a los 18 puntos obligatorios (estado actual)

| # | Pregunta | Respuesta | Evidencia |
|---|----------|-----------|-----------|
| 1 | ¿Cómo se identifica el tenant? | No existe. Hay un único propietario | `remote.py` (`link_token`), `telegram_bridge.py` |
| 2 | ¿Quién establece el contexto? | Nadie: es implícito y global | — |
| 3 | ¿Se puede manipular desde headers, parámetros, JWT o body? | No hay tenant que manipular. El **canal** (`channel="mobile"/"pc"`) sí viene del body (`Command.channel`, `app.py:178-183`) y solo decide por qué aparato se habla | `app.py:306-309` |
| 4 | ¿Se verifica la pertenencia? | Se verifica tener el token (comparación en tiempo constante). No hay identidad por dispositivo: todos comparten el mismo token | `app.py:165-173` |
| 5 | ¿Roles dentro del tenant? | No hay roles. Todo canal autenticado tiene todos los privilegios | — |
| 6 | ¿Las consultas filtran por tenant? | No (no aplica) | `memory.py:1096-1140` |
| 7 | ¿RLS? | No | — |
| 8 | ¿Protección ante consultas sin filtro? | No aplica | — |
| 9 | ¿Administradores limitados y auditados? | El propietario es el administrador. `audit.jsonl` registra acciones sin redacción (ver `06`) | `audit.py` |
| 10 | ¿Archivos aislados? | Un solo `data/`. Los permisos de ficheros son globales (`perm_files`) | `permissions.py` |
| 11 | ¿Cachés con contexto? | Cachés globales (`webcache.json`, proveedor LLM, índice de apps) | `websearch.py`, `llm.py` |
| 12 | ¿Jobs y colas aislados? | `JobManager` es global | `jobs.py` |
| 13 | ¿Búsquedas vectoriales filtran por tenant? | No | `memory.py` |
| 14 | ¿Las herramientas de IA respetan el ámbito? | Respetan `perm_files`, que por defecto es `todo` (SEC-04) | `permissions.py:31-46` |
| 15 | ¿Backups preservan el aislamiento? | Es un único zip de `data/` | `skills/backup/skill.py` |
| 16 | ¿Webhooks validan a qué tenant pertenece el evento? | `/api/n8n` no valida nada (SEC-01) | `app.py:1088` |
| 17 | ¿Logs que mezclan clientes? | Un solo cliente | — |
| 18 | ¿Unicidad y claves foráneas compatibles? | No aplica | — |

## 3. Escenario obligatorio: Tenant A → recurso de Tenant B

No hay tenants. El escenario equivalente es: **¿puede un dispositivo o canal acceder a algo que no debería?**

- Un dispositivo vinculado con el token tiene **exactamente el mismo poder** que el propietario en el PC. No hay ninguna protección que lo limite, y eso es por diseño.
- Revocar un solo dispositivo no es posible: `/api/link/reset` rota el token y desvincula **todos** (`app.py:~1560`).
- Recomendación: un token **por dispositivo**, con revocación individual y lista en el HUD. Esfuerzo M. Es también el primer paso si algún día hubiera varios usuarios.

## 4. Riesgos si se convirtiera en SaaS (pregunta 22)

Convertirlo en SaaS **no es una evolución incremental**: el modelo de seguridad entero se apoya en «loopback = propietario». Habría que resolver como mínimo:

1. **Identidad**: OIDC por usuario, sesiones y revocación. Eliminar la confianza por loopback.
2. **Aislamiento de datos**: `tenant_id` obligatorio en `memories` y en todas las tablas, con **RLS en Postgres** (`USING tenant_id = current_setting('app.tenant')`), además de filtros en el código.
3. **Ficheros**: `data/` por tenant, y nada de `perm_files` sobre el sistema de archivos del servidor. Las skills de sistema (`system_pc`, `files`, `games`, `domotica`, `chrome`) **no tienen sentido** en un servidor compartido y serían RCE entre clientes.
4. **RAG**: filtro por tenant en la consulta vectorial **antes** del ranking, y namespaces separados en Engram y opmem. Hoy opmem inyecta «órdenes» globales: en multiusuario, una regla de un usuario afectaría a otro.
5. **Cachés** (`webcache`, proveedor, índice) con clave por tenant.
6. **Jobs**: cuotas y concurrencia por tenant. Hoy hay un semáforo global de 4.
7. **Costes de LLM**: presupuesto y límite de velocidad por tenant (hoy no hay ninguno, ver `07`).
8. **Secretos**: un gestor de secretos con cifrado por tenant (hoy, JSON en claro).
9. **Webhooks**: firma HMAC por tenant y mapeo evento → tenant.

**Conclusión**: el código actual **no está preparado** para multitenancy. No hay que intentarlo con parches; habría que rediseñar el borde (identidad y autorización) y la capa de datos. Mientras siga siendo monousuario, la inversión no está justificada.
