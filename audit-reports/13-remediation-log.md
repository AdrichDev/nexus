# 13 — Registro de remediación (estado vivo)

Este documento **no** forma parte de la auditoría original: es el registro de qué se está corrigiendo después de ella, con la evidencia de cada corrección. La auditoría queda como fue emitida (`00` a `12`).

Rama: `fix/security-audit-remediation` (sobre `main` @ `908924b`). Plan y evidencia completa: `odd/tasks/security-audit-remediation.md`. Estrategia de entrega acordada: cadena de PRs apilados sobre `main`, con una frontera de revisión por unidad de trabajo.

**Niveles de evidencia**: `in-process` (doble ASGI/unitario), `servidor-real` (uvicorn de verdad en un puerto libre, config y data desechables), `navegador`, `dispositivo-físico`, `túnel`. Nada de esto se ha probado en navegador real ni con dispositivos físicos todavía; está anotado donde corresponde.

| Tarea | Hallazgo | Estado | Commit | Evidencia | Qué queda sin probar |
|-------|----------|--------|--------|-----------|---------------------|
| T0 | — | Hecho | `e927afd` | Solo lectura: 13 informes + documento ODD versionados | — |
| T1 | P0-1, P0-2 | Cerrado por evidencia | — | Telegram ya tiene propietario (confirmado por el dueño: «Sí, es mi chat»); n8n: «No / no lo uso»; nada en `:5678` | Ninguna exposición activa que taponar |
| T2 | SEC-01 (+SEC-06 n8n) | Hecho | `8eb3cf7`, `5d701c4` | `test_n8n_canal` 42/0 → tras el corrección del verificador 53/0 (dos veces); capas 465/0; routing 244/0; secretos 51/0; servidor-real `test_acceso_remoto` 74/0; `test_entrega_real` 30/0; diferencial texto/voz base vs rama idéntico | Flujo n8n importado de verdad en un n8n real; cabecera con el valor puesto a mano por el dueño |
| T3 | SEC-02 | Hecho | `61396b0` | `test_telegram_link` 70/0 (RED 13 fallos); capas 465/0; n8n 53/0; umbrales 47/0; perfiles 530/0. Verificador independiente: SHIP, sin bloqueos. Fuerza bruta del código estimada en ≈7×10⁻¹² por ventana de 600 s | Bot real de Telegram end-to-end (no se toca la cuenta del dueño); sin botón en el HUD para ver el código |
| T4 | SEC-03 (+exposición del token) | Hecho | (pendiente de hash) | `test_host_origin` 115/0 (RED 61 OK/36 fallos); n8n 53/0; telegram 70/0; capas 465/0; routing 244/0; perfiles 535/0; servidor-real 74/0 y 30/0 | Navegador real con rebinding de verdad (`Q-04` sigue abierto); ventana pywebview real |

## Correcciones a la propia auditoría

1. **SEC-02 estaba sobredimensionado en su impacto.** El puente de Telegram hacía `from .. import brain`, que es un `ImportError` (el módulo vive en `core/aplicacion`) tragado por el `except Exception` del bucle: ninguna orden de Telegram llegaba al cerebro. Por eso el secuestro por primer contacto no daba control del PC; daba envenenar el vínculo y bloquear al propietario. Se corrigió en `61396b0`, y a partir de ahora las órdenes por Telegram sí se ejecutan: por eso era obligatorio cerrar antes el TOFU. `03-security-findings.md` se mantiene como se emitió; esta es la nota que lo matiza.
2. **El mismo tipo de fallo vive en `backend/core/infraestructura/llm.py:907`** (`from .. import selflearn`): el perfil destilado nunca se inyectaba. Task aparte (T30).
3. **`/m` se trataba como prefijo público**, así que cualquier ruta que empezara por `/m` saltaba el middleware. Endurecido en T4 (`_es_ruta_publica`: exactas salvo `/static/`).
4. **`remote.status()` devolvía el token del QR** y, además, `link` lo lleva dentro (lo necesita el QR). Queda solo en `link`/`/api/link/qr`, accesible para un cliente ya confiable.

## Decisiones del padre (registradas aquí porque afectan a la lectura de los hallazgos)

- **No se fija el puerto de loopback a 8177** en la regla de confianza local: la herencia es la regla del WebSocket (exige puerto, no cuál) y las suites de servidor real usan un puerto libre. Lo que corta el rebinding es el nombre de host y la autoridad exacta.
- **`/api/n8n` queda exenta del token del QR** en el middleware: su autoridad es el secreto propio. Sin eso, n8n dentro de Docker nunca habría podido llamar (peer no loopback → 401 antes de su propia comprobación). La exención es la ruta exacta y no concede nada por sí sola.
- **El flujo `n8n_informe_diario.json` deja de pedirle a nexus que envíe correo, suba a Drive o apunte memoria**: son escrituras y ahora se rechazan desde ese canal. El informe se lo queda n8n. Si se quiere correo, que lo mande n8n con su propia credencial.
- **La vinculación de Telegram conserva el propietario actual** (decisión del dueño); el código de un solo uso solo aplica a los registros nuevos. Queda pendiente un botón en el HUD para ver el código.

## Cómo se comprueba el estado de remediación

```bat
.venv\Scripts\python.exe tests\integration\http\test_host_origin.py
.venv\Scripts\python.exe tests\integration\http\test_n8n_canal.py
.venv\Scripts\python.exe tests\unit\core\test_telegram_link.py
```

Las suites que levantan el servidor de verdad (`test_acceso_remoto.py`, `test_entrega_real.py`) y la batería completa (`tests/run_all.py`) se ejecutan desde una consola del proyecto, no desde un agente en primer plano: arrancan Whisper, Telegram, micrófono y el scheduler.
