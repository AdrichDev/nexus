# 09 — Roadmap de remediación

**Criterio de orden**: primero la mayor reducción de riesgo con el menor coste razonable.

**Esfuerzo**: XS = menos de 2 h; S = hasta 1 día; M = 2-4 días; L = más de 1 semana.

**Regla para todos los ítems**: cada corrección es un commit propio con su test (RED → GREEN) y su regresión.

## P0 — Inmediato

No hay vulnerabilidades críticas confirmadas, ni secretos comprometidos, ni exposición activa demostrada. **Hay una comprobación inmediata condicional**:

| # | Objetivo | Hallazgo | Acción | Esfuerzo | Aceptación |
|---|----------|----------|--------|----------|------------|
| P0-1 | Cerrar la exposición si el flujo n8n de ejemplo está importado y activo | SEC-01 | Comprobar en n8n si el webhook `nexus` existe y es accesible desde fuera. Si es así, desactivarlo hasta aplicar P1-1 | XS | El webhook está desactivado o tiene autenticación |
| P0-2 | Cerrar la toma de control de Telegram si el bot no tiene propietario | SEC-02 | Comprobar que existe `data/telegram_owner.txt` con el chat propio. Si no, escribir al bot desde el chat propio **ya** o vaciar el token del bot | XS | Propietario = chat del usuario |

## P1 — Alta prioridad

| # | Objetivo | Hallazgo | Motivo | Acción | Dependencias | Esfuerzo | Riesgos de implementación | Prueba de aceptación | Resultado esperado |
|---|----------|----------|--------|--------|--------------|----------|---------------------------|----------------------|--------------------|
| P1-1 | Autenticar n8n y tratarlo como canal no confiable | SEC-01, SEC-06 | Texto externo → acciones | Cabecera secreta en `/api/n8n` (sin exención de loopback) y allowlist de intents para `source="n8n"`. Sin `send_email`, `whatsapp` ni memoria explícita. Corregir `n8n_flujo_ejemplo.json` | — | S | Rompe los flujos actuales hasta añadir la cabecera | Sin secreto → 401. Con secreto, `send_email` → rechazado | Webhook externo sin poder de escritura |
| P1-2 | Vinculación de Telegram con código de un solo uso | SEC-02 | Toma de control persistente | `/start <código>` mostrado en el HUD, con TTL de 10 min | — | S | Hay que volver a vincular los bots existentes (opcional: respetar el propietario actual) | Sin código o con código caducado → no se registra | Sin TOFU |
| P1-3 | Validar Host y Origin en HTTP local y no devolver el token | SEC-03 | Rebinding → robo del token | Reutilizar `_trusted_local_ws_origin` en `remote_auth`. Quitar `token` de `/api/link/status` | Revisar el Origin de pywebview | S | Que el HUD deje de funcionar si pywebview envía un Origin inesperado | `Host: evil:8177` → 401. El HUD funciona (E2E) | Confianza local real |
| P1-4 | Confirmar los envíos externos | SEC-05, AI-05 | Correo o WhatsApp no deseados | `confirm.request` con vista previa para `send_email` y `whatsapp`, más una clave de idempotencia de 5 min | — | S | Un paso más para el usuario | Sin «sí» no se envía. Una orden repetida no duplica | Envíos solo intencionados |
| P1-5 | Privacidad del cerebro | AI-01, AI-02, PRIV-01/02 | Datos personales a la nube | (a) No usar la nube como reserva sin el consentimiento guardado `permitir_fallback_nube`. (b) Aplicar `redactar()` en `record_interaction`, `audit.log` y `distill` | — | S | Menos disponibilidad cuando Ollama cae (es lo correcto) | Ollama caído → `SinCerebro`. `sk-…` → redactado en los JSONL | El contexto no sale sin consentimiento |
| P1-6 | Permisos de ficheros seguros por defecto | SEC-04, SEC-12 | Amplifica cualquier compromiso | Por defecto `carpetas` (Documentos, Escritorio y Descargas), denylist fija (secretos, tokens, `.ssh`) y cambio de permisos solo desde la ventana local | Decidir si se migran los `settings.json` existentes | S | Las órdenes de ficheros fuera de esas carpetas piden activar el permiso | Tabla de rutas permitidas y denegadas | Superficie acotada |

## P2 — Mejora planificada

| # | Objetivo | Hallazgo | Acción | Esfuerzo | Aceptación |
|---|----------|----------|--------|----------|------------|
| P2-1 | Política central de canal y efecto | ARQ-01, ARQ-03 | Declarar `efecto` por intent en `SKILL`. `brain` aplica la confirmación y la allowlist según canal y efecto. Absorbe P1-1 y P1-4 de forma estructural | M | Test de matriz canal × efecto |
| P2-2 | Opmem con confirmación y origen | SEC-06, AI-04 | Confirmar las reglas nuevas, guardar el canal de origen y no aceptar escrituras desde canales no confiables. Leer Engram como datos | M | n8n/Telegram «apunta que siempre…» → pide confirmación o se rechaza |
| P2-3 | Triaje de correo con aprobación | SEC-07 | Proponer la lista de acciones → «sí» → crear. Validar fechas y títulos | S-M | Fake de Gmail con inyección → nada se crea sin «sí» |
| P2-4 | Marcar el contenido no confiable | AI-03 | Delimitadores (`<datos_no_confiables origen=…>`) en un mensaje `user` en lugar de `system`. Las memorias también | S | Corpus de inyección (ver `05` §6) |
| P2-5 | Android: transporte y puente | SEC-08 | `networkSecurityConfig` solo para LAN, sin mixed content, puente solo en hosts emparejados, confirmación nativa para `dial` y `whatsapp`, token en cabecera | M | Revisión del manifiesto y prueba manual |
| P2-6 | Secretos cifrados | SEC-09 | DPAPI o `keyring` para `secrets.json` y los tokens OAuth, con migración transparente. Corregir `CLAUDE.md` (inmediato, XS) | M | El archivo en disco no contiene la key legible. La aplicación arranca |
| P2-7 | CI con tests y lockfile | 08 | Job de `run_all.py` (rápidas en PR, lentas por la noche), `requirements.lock` con hashes y actions fijadas por SHA | S | PR con un test roto → CI en rojo |
| P2-8 | Supresión completa | PRIV-03 | `borrar_definitivo` recorre `knowledge.jsonl`, documentos, Engram, logs y caché | M | Test: un dato purgado no aparece en ningún almacén |
| P2-9 | Escrituras atómicas | ARQ-05 | `_write_json_atomic` en `board`, `jobs`, `contentos` y `proactive` | S | Test de interrupción |
| P2-10 | Backups: restauración probada y fuera del disco | 07 §3 | Prueba de restauración hermética, copia opcional a otro disco o a la nube con cifrado | S-M | La restauración en el entorno hermético arranca y los datos cuadran |
| P2-11 | Cabeceras y escape | SEC-10 | `esc()` con comillas, CSP y `frame-ancestors 'none'` | S | Test de `esc`. El HUD funciona con la CSP |
| P2-12 | Límites de consumo de LLM | AI-07 | `max_tokens`/`num_predict`, contador diario por proveedor y límite configurable | S | El límite alcanzado da un mensaje honesto |
| P2-13 | Tests de frontera | 08 §5 | Los de la tabla de huecos críticos | M | Registrados en `run_all.py` |

## P3 — Evolución futura

| # | Acción | Hallazgo | Esfuerzo |
|---|--------|----------|----------|
| P3-1 | SSRF: `safe_fetch` con bloqueo de rangos privados para URLs de canales no confiables | SEC-11 | S-M |
| P3-2 | Token por dispositivo con revocación individual | 04 §3 | M |
| P3-3 | Dividir `app.py` en `APIRouter`s | ARQ-02 | S-M |
| P3-4 | Prioridad explícita del routing | ARQ-04 | M |
| P3-5 | Gemini con cabecera `x-goog-api-key`, `state` en OAuth de Spotify, `isdigit` en `games`, errores genéricos | SEC-13/14/15/16 | XS cada uno |
| P3-6 | Hermes: sin reintento automático en métodos con efecto, y confirmación de la delegación | 05 §5 | S |
| P3-7 | Allowlist de herramientas MCP antes de activarlo | SEC-18 | S |
| P3-8 | Firma de código del instalador si se distribuye | 08 §3 | S + coste del certificado |
| P3-9 | Migraciones versionadas | ARQ-08 | S |
| P3-10 | Rotar la contraseña de Postgres si alguna instalación usa el literal histórico | SEC-17 | XS |

## Riesgo residual tras P0 + P1

- El modelo «loopback = propietario» sigue en pie: un malware local tiene el control total. Es **inherente a un asistente local**. La mitigación pasa por el sistema operativo, no por nexus.
- La prompt injection por contenido web o de correo sigue siendo posible en el **texto** de las respuestas, pero sin camino a acciones con efecto externo (gracias a P1-4 y P2-1).
- Datos en claro en disco hasta P2-6.
