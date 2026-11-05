# 03 — Hallazgos de seguridad

Rama auditada: `fix/youtube-verification` @ `908924b` (árbol de trabajo con un archivo no rastreado, `odd/tasks/youtube-verification.md`, ajeno a la auditoría).
Modo: estático, solo lectura. Ninguna prueba dinámica contra la aplicación en ejecución.

**Leyenda de estado**

- **Confirmada**: el camino de código existe y se ha leído de punta a punta. Si no se dice lo contrario, la explotación no se ha demostrado de forma dinámica.
- **Potencial**: el código lo permite, pero depende de condiciones externas (navegador, despliegue o configuración del usuario) que no se han verificado.
- **No verificada**: la reportó un subagente y no se ha contrastado de forma independiente.

**Contraste independiente**: los hallazgos Alta y Media se contrastaron con un verificador independiente (`gentle-ai-verify`). Su veredicto y su severidad propuesta están integrados abajo. Cuando la severidad final difiere de la propuesta, se explica el motivo.

**Modelo de despliegue usado para calibrar la severidad**: aplicación de escritorio **monousuario** en Windows. uvicorn escucha en `0.0.0.0:8177` (`backend/desktop.py:43`). El HUD local no lleva token. El móvil, la LAN y el túnel requieren el token del QR. Hay además un puente de Telegram y un endpoint para n8n.

---

## Tabla resumen

| ID | Severidad | Estado | Título |
|----|-----------|--------|--------|
| SEC-01 | **Alta** | Confirmada | `/api/n8n` sin autenticación propia y un flujo de ejemplo con webhook público que inyecta texto externo en `brain.process` |
| SEC-02 | **Alta** | Confirmada | Telegram: el primer chat que escribe al bot queda registrado como propietario permanente (TOFU) |
| SEC-03 | Media | Potencial | DNS rebinding contra la API HTTP en loopback, que no valida Host ni Origin. Permite robar el token del QR |
| SEC-04 | Media | Confirmada | `perm_files="todo"` por defecto: `path_allowed()` siempre devuelve True |
| SEC-05 | Media | Confirmada | `send_email` envía sin confirmación y sin idempotencia, también desde el canal n8n |
| SEC-06 | Media | Confirmada | Envenenamiento persistente de instrucciones: la memoria operativa (opmem) se inyecta como «órdenes» sin confirmación, y Engram es local y sin autenticación |
| SEC-07 | Media | Confirmada | Prompt injection indirecta: el triaje de correo crea tareas y eventos en Google sin confirmación |
| SEC-08 | Media | Confirmada | La app Android permite cleartext y mixed content, y expone un puente JS con `dial` y `whatsapp` |
| SEC-09 | Baja-Media | Confirmada | Secretos y tokens OAuth en texto plano. `CLAUDE.md` afirma que están «cifradas» |
| SEC-10 | Baja | Confirmada | Sin cabeceras de seguridad (CSP, X-Frame-Options). `esc()` no escapa comillas |
| SEC-11 | Baja | Confirmada | SSRF: no se restringen IPs privadas ni esquemas, y se siguen las redirecciones (vigilancias, websearch, datos) |
| SEC-12 | Baja | Confirmada | `POST /api/config` permite cambiar `perm_files` y URLs de integración con el token o desde loopback |
| SEC-13 | Baja | Confirmada | La API key de Gemini viaja como parámetro de query |
| SEC-14 | Baja | Potencial | `games/skill.py:73` interpola `appid` en `os.system` sin validar que sea numérico |
| SEC-15 | Baja | Confirmada | El callback OAuth de Spotify no valida `state` |
| SEC-16 | Baja | Confirmada | Errores de handler devueltos con `str(exc)` en el JSON de varios endpoints |
| SEC-17 | Informativa | Confirmada | Una contraseña de desarrollo histórica (`nexus_dev_****`) es pública en el repositorio como caso del escáner |
| SEC-18 | Informativa | Confirmada | `mcp_hands` no tiene allowlist de herramientas (desactivado por defecto) |

No se ha encontrado **ninguna vulnerabilidad Crítica confirmada**. Las dos Altas dependen de una condición de despliegue (n8n expuesto con el flujo de ejemplo; bot de Telegram creado y todavía sin propietario).

---

## SEC-01 — `/api/n8n`: texto externo no confiable → `brain.process` (Alta, Confirmada)

**Evidencia**

- `backend/app.py:1088-1094`
  ```python
  @app.post("/api/n8n")
  async def api_n8n(payload: dict):
      result = await brain.process(payload.get("text", ""), source="n8n")
  ```
- El middleware `remote_auth` (`app.py:142-177`) deja pasar sin token todo lo que llega con peer loopback (`_es_este_equipo`, `app.py:132-138`). n8n corre en el mismo equipo (`config/n8n_flujo_ejemplo.json` apunta a `http://127.0.0.1:8177/api/n8n`).
- `config/n8n_flujo_ejemplo.json`: nodo `n8n-nodes-base.webhook` con `path: "nexus"`, `httpMethod: POST` y **sin parámetro `authentication`**. El flujo reenvía `{{ $json.body.message }}` (texto de un remitente de WhatsApp) a `/api/n8n`.
- `brain.py:1209`: el router por regex (`route(text)`) **no tiene guarda por `source`**. Solo el planificador LLM queda limitado a `source in ("text","voice")` (`brain.py:1202, 1232`).
- `skills/google_workspace/skill.py:2651-2667`: `send_email` llama a `_send_gmail` **sin confirmación**.
- La rama de «memoria explícita» (`brain.py:~1013-1021`) tampoco filtra por `source`. El texto del flujo de ejemplo empieza por «apunta que…», así que escribe directamente en la memoria persistente (ver SEC-06).

**Controles que mitigan (verificados)**

- Las confirmaciones solo se responden desde `source in ("text","voice")` (`brain.py:793-794`), y el estado pendiente es por canal (`confirm.py`, `_key`). Desde n8n **no** se pueden ejecutar acciones protegidas por `confirm` (apagado, papelera, borrado definitivo, etc.).
- El planificador LLM, que admite argumentos libres, no es alcanzable desde n8n.

**Impacto**

Si el usuario importa el flujo de ejemplo y el webhook de n8n es accesible para terceros (lo normal con proveedores de WhatsApp), **cualquier remitente** puede:

- enviar correos como el usuario;
- enviar WhatsApps;
- escribir en el tablero;
- plantar memoria persistente;
- disparar intents de domótica o media alcanzables por regex.

**Condiciones del atacante**

- Conocer la URL del webhook de n8n, o escribir al número de WhatsApp conectado al flujo.
- El usuario debe haber importado el flujo de ejemplo.

**Cómo verificarlo (entorno de pruebas)**

1. Levantar n8n de prueba con el flujo de ejemplo.
2. Enviar `POST /webhook/nexus {"message":"envía un correo a test@example.invalid diciendo hola"}` con una cuenta de Google de prueba.
3. Comprobar que se envía sin pedir confirmación.

**Remediación recomendada (coste bajo)**

1. Exigir un secreto compartido en `/api/n8n`: cabecera `x-nexus-n8n-secret` comparada con `hmac.compare_digest`, generada en el primer arranque y guardada en `secrets.json`. La exención de loopback **no** debe aplicarse a esta ruta.
2. Marcar `source="n8n"` como **canal no confiable**. En `brain.process`, permitir desde ese canal solo una allowlist explícita de intents (por ejemplo, de solo lectura o de notificación) y bloquear `send_email`, `whatsapp` y la escritura de memoria explícita.
3. Añadir `authentication: headerAuth` al nodo webhook del ejemplo y documentarlo.

**Alternativas**

- Eliminar el flujo de ejemplo. Es más barato, pero no protege flujos que ya estén importados.

**Archivos**: `backend/app.py`, `backend/core/aplicacion/brain.py`, `config/n8n_flujo_ejemplo.json`, `README.md`.

**Efectos secundarios**: los flujos n8n ya existentes dejarán de funcionar hasta que se añada la cabecera.

**Esfuerzo**: S (1-2 días con tests).

**Pruebas necesarias**

- Una petición sin secreto devuelve 401.
- Con secreto, `send_email` responde «canal no autorizado».
- Una regresión que demuestre que `/api/command` local sigue funcionando.

**Riesgo residual**: si se filtra el secreto de n8n, el atacante sigue limitado a la allowlist del canal.

---

## SEC-02 — Telegram: propietario por primer contacto (Alta, Confirmada)

**Evidencia**

`backend/core/infraestructura/telegram_bridge.py:85-95`

```python
if not owner:
    owner = chat_id
    OWNER_FILE.write_text(owner, encoding="utf-8")
    ...
    continue
if chat_id != owner:
    continue  # ignora desconocidos
```

Los mensajes del propietario van a `brain.process(text, source="text", channel="telegram")`. Es la fuente **de máxima confianza**: planificador LLM, confirmaciones y todas las skills.

**Impacto**

Control total del asistente: ficheros (con `perm_files="todo"`), Google (enviar correo, Drive completo), dispositivos y memoria. El propietario legítimo queda **excluido** de forma permanente, porque el bot ignora su chat.

**Condiciones del atacante**

Conocer el `@username` del bot y escribirle antes que el dueño, o hacerlo después de que se pierda `data/telegram_owner.txt` (por una restauración o una limpieza de `data/`).

**Severidad**

Alta. La ventana es estrecha, pero cuando se aprovecha da el control completo y persistente sin que el usuario lo detecte (solo recibe el mensaje «enlazado» el chat del atacante).

**Remediación**

Requerir un código de vinculación de un solo uso como primer mensaje (`/start <código>`), mostrado en el HUD local y con un TTL de 10 minutos. Mientras no haya propietario, el bot no debe aceptar órdenes. Opcionalmente, la vinculación debe notificarse en el HUD local con un botón para revocarla.

**Archivos**: `telegram_bridge.py`, HUD (vista de vinculación).

**Esfuerzo**: S.

**Pruebas**

- Con propietario vacío, un mensaje sin código no registra propietario.
- Un código caducado se rechaza.
- Un código correcto registra el propietario una sola vez.

---

## SEC-03 — DNS rebinding y exposición del token del QR (Media, Potencial)

**Evidencia**

- `app.py:132-177`: la confianza local se basa solo en el peer de loopback y en que falten `cf-connecting-ip` y `x-forwarded-for`. **No se valida `Host` ni `Origin` en HTTP.** El WebSocket sí los valida (`_trusted_local_ws_origin`, `app.py:189-215`).
- No hay `TrustedHostMiddleware` ni CORS en `backend/` (búsqueda con grep).
- `GET /api/link/status` (`app.py:1581-1592`) → `remote.status()` devuelve `"token": link_token()` (`remote.py:642`).

**Verificación realizada**

Se probó en memoria con FastAPI 0.139.2 (`TestClient`, sin importar el backend) que un POST cross-site «simple» (sin `Content-Type`, o con `text/plain`) contra un endpoint con cuerpo Pydantic o `dict` devuelve **422**. El CSRF clásico sin preflight **no** funciona. Solo queda el vector de rebinding (same-origin tras rebind).

**Camino de ataque (no demostrado en navegador)**

1. La víctima visita una página del atacante.
2. El dominio del atacante pasa a resolver a `127.0.0.1` con un puerto 8177 coincidente.
3. La página hace un `GET /api/link/status` same-origin → obtiene el token.
4. Con el token tiene acceso remoto persistente por LAN o túnel, aunque el rebinding se rompa después.

**Factores que mitigan**: Chrome reciente aplica Private/Local Network Access y DNS pinning. Firefox y Safari ofrecen menos protección. No se ha probado con navegadores concretos.

**Remediación**

1. Validar `Host` contra `{127.0.0.1:8177, localhost:8177, [::1]:8177}` para las peticiones tratadas como locales. Si el Host es otro, se exige token. Se puede reutilizar la lógica del WS.
2. Para métodos que no sean GET en local, exigir que `Origin` sea igual al propio origen o que esté ausente (para clientes nativos).
3. No devolver el token en `/api/link/status`. Basta con un booleano `vinculado`, y el QR ya lo genera `/api/link/qr`.

**Esfuerzo**: S.

**Pruebas**

- `Host: evil.example:8177` desde loopback devuelve 401.
- `Origin` ajeno en POST local devuelve 403.
- El HUD local y pywebview siguen funcionando, lo que obliga a revisar el Origin que envía pywebview.

---

## SEC-04 — Permisos de ficheros sin restricción por defecto (Media, Confirmada)

**Evidencia**

- `backend/core/comun/config.py:134`: `"perm_files": "todo"`.
- `permissions.py:31-46`: si el modo es `todo`, `path_allowed()` devuelve `True` de inmediato.
- Los argumentos del planificador LLM son cadenas libres (`brain.py:702-714`, `_LLMMatch`; `brain.py:1213-1220`). Solo se valida que skill e intent existan.

**Hallazgo descartado**: `GET /api/note` **no** permite path traversal. Recorre `MEMORY_DIR.rglob("*.md")` y compara `p.stem == name` (`app.py:477-487`).

**Impacto**

Es un amplificador. Cualquier compromiso de un canal (SEC-01, SEC-02, SEC-03) o una prompt injection que llegue a un canal de confianza puede leer y devolver cualquier archivo del usuario: claves SSH, `config/secrets.json`, `google_token.json`.

**Remediación**

- Poner por defecto `carpetas`, con Documentos, Escritorio y Descargas, o `sandbox`.
- Pasar a `todo` debe ser una elección explícita en ⚙ con aviso.
- Añadir una denylist fija aunque el modo sea `todo`: `config/secrets.json`, `config/*token*.json`, `.env`, `~/.ssh`, almacenes de credenciales del navegador.

**Efectos secundarios**: los usuarios actuales con `settings.json` ya guardado no cambian de modo. Hay que decidir si se migra.

**Esfuerzo**: S.

**Pruebas**

- Con el modo por defecto, leer `C:\Windows\win.ini` → denegado.
- La denylist se aplica en `todo`.
- Hay un test para `..`, enlaces simbólicos y rutas UNC.

---

## SEC-05 — `send_email` sin confirmación ni idempotencia (Media, Confirmada)

**Evidencia**

- `skills/google_workspace/skill.py:2651-2667`: el destinatario se parsea del texto y, si falta el cuerpo, **lo redacta el LLM**. Después se envía directamente con `_send_gmail`.
- El scope OAuth incluye `gmail.send` (`skill.py:26-31`).
- El borrado de eventos y el de Drive sí usan `confirm.request` (`skill.py:2526`, `2879`). La asimetría es evidente.

**Impacto**

Envío de correos no deseados como el usuario, por error de routing o por alucinación del cuerpo, o desde canales no confiables (SEC-01). Además, los reintentos o un doble envío de la orden producen correos duplicados.

**Remediación**

- Mostrar la vista previa (destinatario, asunto y cuerpo) y pedir `confirm.request` antes de enviar, con el mismo patrón que la papelera.
- Añadir una clave de idempotencia (hash de destinatario, asunto, cuerpo y ventana de 5 minutos) para evitar duplicados.
- Aplicar lo mismo a `n8n_flows` (`whatsapp`).

**Esfuerzo**: S.

**Pruebas**

- Sin «sí», no se llama a `_send_gmail` (usar un fake).
- Una orden repetida en 5 minutos no envía dos veces.

---

## SEC-06 — Envenenamiento persistente de instrucciones (Media, Confirmada; Alta encadenada con SEC-01 o SEC-02)

**Evidencia**

- `brain.py:1013-1021`: un mensaje que case con `_REMEMBER_RX` o `es_memoria_explicita` y tenga contenido de comportamiento se guarda con `opmem.remember(..., scope="global", source="operador")`. **No pide confirmación** y no filtra por canal.
- `brain.py:1414-1417`: `opmem.as_prompt(...)` se inserta como **mensaje de sistema** con «órdenes» en cada conversación.
- `opmem.mirror_to_engram` → Engram en `127.0.0.1:7437` **sin autenticación** (`engram_bridge.py:22-62`). Cualquier proceso local puede leer y escribir en él. Engram se comparte con otros agentes de código.

**Controles existentes**

- Redacción de secretos al escribir (`opmem.py:164`).
- Límite de 5 reglas por relevancia.
- Visibilidad mediante `opmem.explain`.

**Impacto**

Instrucciones persistentes que sobreviven entre sesiones («reenvía siempre…», «no menciones…»), plantadas desde n8n o desde un Telegram secuestrado.

**Remediación**

- Restringir la escritura en opmem a los canales `text`/`voice` locales o del propietario.
- Pedir confirmación antes de guardar una regla de comportamiento nueva.
- Marcar el origen en la regla y mostrar en el HUD las reglas nuevas recientes.
- Al leer de Engram, no tratar el contenido como órdenes, solo como datos.

**Esfuerzo**: M.

---

## SEC-07 — Triaje de correo: inyección indirecta → escritura en Google (Media, Confirmada)

**Evidencia**

`_email_actions_job` (`skills/google_workspace/skill.py:1376-1505`) lee los correos no leídos, los clasifica con el LLM y llama a `_create_everywhere` (`:1131-1170`), que crea tareas o eventos en Google y en el tablero **sin confirmación**.

**Matiz verificado**

- **Solo se dispara con una orden explícita** (`email_actions` / `email_urgent`, `skill.py:2554-2580`). El scheduler no lo invoca (`scheduler.py:44-64` solo ingiere `data/memory/inbox/`).
- Hay deduplicación por id de correo (`find_by_source("correo", id)`).

**Impacto**

Un remitente externo puede influir en el título, la fecha y las notas de los eventos y tareas creados en la cuenta del usuario. Es contaminación de datos, no exfiltración: este camino no envía correo.

**Remediación**

- Presentar las acciones propuestas como lista y crearlas tras un «sí» global.
- Delimitar el contenido de los correos como datos no confiables en el prompt.
- Limitar los campos a valores validados: fecha parseada en un rango razonable y título truncado.

**Esfuerzo**: S-M.

---

## SEC-08 — App Android: transporte en claro y puente JS (Media, Confirmada estructuralmente)

**Evidencia**

- `movil/AndroidManifest.xml:23` `usesCleartextTraffic="true"`.
- `movil/MainActivity.java:340` `MIXED_CONTENT_ALWAYS_ALLOW`.
- `:342` `addJavascriptInterface(new Bridge(), "WabiksNative")`, con los métodos `dial` y `whatsapp` (`:415-447`).
- `evaluateJavascript` con escape débil (`:492-495`).
- `remote.py:633`: en modo WiFi, el QR ofrece `http://<ip-lan>:8177/m?...&token=...`.

**Camino de ataque**

Un atacante en la misma WiFi hace MITM sobre el HTTP en claro. Así puede:

- leer el token, que viaja en la URL y en las peticiones;
- inyectar JS que llame a `WabiksNative.dial` o `WabiksNative.whatsapp`.

`doDial` filtra a `[0-9+]` (`:~499`), así que el abuso queda limitado a llamadas o WhatsApps forzados.

**Remediación**

- `networkSecurityConfig` que permita cleartext solo hacia rangos LAN privados.
- Eliminar `MIXED_CONTENT_ALWAYS_ALLOW`.
- Exponer el puente solo cuando la URL cargada pertenezca a un host emparejado.
- Pedir confirmación nativa en `dial` y `whatsapp`.
- Mover el token de la query a una cabecera.

**Esfuerzo**: M (requiere recompilar la APK).

---

## SEC-09 — Secretos en texto plano y documentación incorrecta (Baja-Media, Confirmada)

**Evidencia**

- `config.py:54, 205, 262-270`: `secrets.json` se lee y escribe como JSON plano (con escritura atómica, pero sin cifrar).
- `CLAUDE.md` dice «config/secrets.json (claves, cifradas)», lo cual es **falso**.
- `google_token.json` en claro (`skill.py:398-438`), con scopes `gmail.modify`, `gmail.send`, `calendar.events`, `tasks` y `drive` completo.
- `spotify_token.json` en claro (`spotify.py:30,59`).

**Controles correctos**: los tres archivos están en `.gitignore` y no aparecen en el historial de git (comprobado por nombre y por patrones; ver `12-audit-coverage.md`). `as_dict()` elimina los secretos de `/api/config`.

**Impacto**: cualquier proceso del usuario, malware o copia de seguridad sin cifrar (SEC: `07`, backups zip) obtiene credenciales de larga duración con acceso de escritura al correo.

**Remediación**

- Cifrar con DPAPI (`win32crypt.CryptProtectData`, ligado al usuario de Windows) o guardar en Windows Credential Manager (`keyring`).
- Corregir `CLAUDE.md` en cualquier caso.
- Valorar reducir los scopes de Google: `drive.file` en lugar de `drive`.

**Esfuerzo**: M.

---

## SEC-10 — Cabeceras de seguridad y escape en atributos (Baja, Confirmada)

**Evidencia**

- No hay CSP, `X-Frame-Options` ni `frame-ancestors` (`app.py`, solo `Cache-Control`).
- `frontend/js/core/dom.js:14-15`: `esc()` escapa `& < >`, pero **no `"` ni `'`**.
- `linkify` excluye `"` del patrón de URL, así que su `href` es seguro.
- Cualquier uso de `esc()` dentro de un atributo (`href="${esc(x)}"`) es inyectable.
- `reels.js:487-489` interpola contadores sin `esc()`. Son números del servidor, con un riesgo bajo.

**No se ha encontrado** un XSS explotable de punta a punta (no hay `eval` ni `new Function`).

**Remediación**

- Añadir las comillas a `esc()`. Es un cambio de una línea, compatible.
- Añadir `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'` al HTML servido.
- Comprobar antes los scripts inline.

**Esfuerzo**: S.

---

## SEC-11 — SSRF sin restricción de destino (Baja, Confirmada)

**Evidencia**

- `backend/core/comun/net.py:42`: `follow_redirects=True` sin ninguna comprobación de IP privada ni de esquema.
- `skills/vigilancias/skill.py:197` descarga periódicamente una URL que proporciona el usuario.
- `datos._connect` acepta cualquier host o `sqlite://<ruta>`.
- `youtube.py:225` y `websearch.fetch_page` aceptan URLs arbitrarias.

**Calibración**: en un sistema monousuario, el usuario ya puede acceder a su loopback. El riesgo real aparece cuando el texto llega por un canal no confiable (SEC-01): `vigila la web http://127.0.0.1:...` es alcanzable por regex desde n8n. El impacto sigue siendo limitado, porque solo se informa del hash o de un cambio de precio.

**Remediación**: añadir a `net` una función `safe_fetch` que resuelva el host, rechace `127.0.0.0/8`, `169.254.0.0/16`, RFC1918 y `::1` cuando la URL no venga de un canal local de confianza, y que revalide cada redirección.

**Esfuerzo**: S-M.

---

## SEC-12 — `POST /api/config` puede desactivar controles (Baja, Confirmada)

`app.py:1189-1215` rechaza los secretos (`:1194`), pero acepta `perm_files`, `perm_folders` y URLs de integración. Quien tenga el token (o el acceso local de SEC-03) puede poner `perm_files="todo"`.

**Remediación**: los cambios de permisos solo deben hacerse desde la ventana local (pywebview), nunca desde canales remotos, con una lista de claves sensibles.

---

## SEC-13 — API key de Gemini en la query (Baja, Confirmada)

`llm.py:513-514, 743-745`: `params={"key": ...}`. Va cifrada en TLS, pero las URLs aparecen en los mensajes de excepción de httpx y en proxies corporativos.

El detalle técnico de `_clasifica_excepcion` usa el cuerpo de la respuesta para errores HTTP (`llm_runtime.py:~199-207`), así que la exposición del key por `/api/llm/status_full` **no está demostrada**.

**Remediación**: usar la cabecera `x-goog-api-key`. Cambia dos líneas.

---

## SEC-14 — `games` interpola `appid` en `os.system` (Baja, Potencial)

`skills/games/skill.py:73` hace `os.system(f'start "" steam://{action}/{appid}')`, y `appid` sale del JSON de la tienda de Steam (`:53`). Si ese dato no fuera numérico, habría inyección de shell.

**Remediación**: validar con `str(appid).isdigit()` y usar `os.startfile(f"steam://...")`.

---

## SEC-15 — OAuth de Spotify sin `state` (Baja, Confirmada)

El callback `GET /api/spotify/callback` (`app.py:784`) acepta `code` sin validar `state`. Esto permite un login CSRF: vincular la cuenta de Spotify del atacante. El impacto es bajo.

**Remediación**: generar un `state` aleatorio y validarlo.

---

## SEC-16 — Errores internos devueltos al cliente (Baja, Confirmada)

Varios endpoints devuelven `str(exc)` o `f"{type}: {exc}"` (`/api/home/scan`, `/api/hermes/*`, `/api/instagram/qr`). Pueden revelar rutas o nombres de host. En el chat, `publicvoice.sanitize()` sí limpia las trazas (control verificado).

**Remediación**: usar un helper común que devuelva un mensaje público y registre el detalle en el log.

---

## SEC-17 — Contraseña de desarrollo histórica pública (Informativa)

El literal `nexus_dev_****` aparece en `scripts/revisar_antes_de_subir.py` como caso que el escáner debe detectar. El código actual genera la contraseña de Postgres con `secrets.token_urlsafe(24)` (`app.py:~1475-1488`).

Si alguna instalación antigua conserva un `docker-compose.yml` con esa contraseña, conviene rotarla:

1. Ejecutar `ALTER USER ... PASSWORD` y actualizar `db_url`.
2. Verificar que Postgres solo está publicado en `127.0.0.1`.

---

## SEC-18 — `mcp_hands` sin allowlist de herramientas (Informativa)

`skills/mcp_hands/skill.py:56-174` lanza los servidores MCP configurados y acepta `tool` y `args` libres del texto. Además, la salida de las herramientas vuelve al historial (es un canal de prompt injection). Todos los servidores de ejemplo vienen con `enabled:false`.

**Remediación**, si se activa:

- allowlist de herramientas por servidor;
- confirmación para las herramientas de escritura;
- etiquetar la salida como no confiable.

---

## Ítems de la auditoría anterior (AUDIT_2026-09-30) no reverificados en esta pasada

- A2 «respuesta "guardado" tras un fallo silenciado» (`brain.py`): no se ha reverificado.
- P8 `get_index()` bloqueante: no se ha reverificado.
- P1 y P2 (WS y `open_app`): el WS está corregido y verificado en `app.py:189-240`. El subagente confirma que en `system_pc` ya no hay `os.system` con texto libre (`skill.py:1236-1279`, `Popen(shell=False)` y una regex de basename).
