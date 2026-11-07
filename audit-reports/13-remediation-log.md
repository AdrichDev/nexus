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

| T5 | SEC-05 (+AI-05) | Hecho | `c6e41c1` | gw 255/0, n8n envios 52/0, test_n8n_canal 57/0, v21_fixes 54/0, no_promete_trabajo 41/0, files 139/0, tasks_board 136/0, drive 251/0, inbox 127/0, correcciones 85/0, pequenas_1 353/0, capas 466/0, routing 244/0, perfiles 540/0. Verificador: SHIP | Envío real contra una cuenta de Google de prueba; ventana anti-duplicado en RAM (se olvida al reiniciar, documentado) |
| T6 | AI-01, AI-02, PRIV-01, PRIV-02, AI-07 | Hecho | `eebda43` | fallback_privacidad 61/0, redaccion_logs 47/0, llm_runtime 158/0, research_honesty 57/0, que_sabes_de_mi 25/0, openrouter_privacidad 14/0, umbrales 47/0, secretos 51/0, redaccion_memoria 14/0, capas 469/0; diferencial base/rama en las rutas intactas: sin diferencias | Un `permitir_fallback_nube` con casilla en el HUD (T31); proveedor real recibiendo el prompt (no se hizo por H1/red) |
| T7 | SEC-04, SEC-12 | Hecho | `58606c1` | permisos_ficheros 112/0 (RED 41/71), files 139/0, ingesta 99/0, datos 64/0, secretos 51/0, backup 64/0, specs_v23_files 98/0, apis_config 72/0, memory_graph 61/0, capas 469/0 | La decisión del dueño sobre SU settings.json (`todo` → `carpetas`) sigue abierta; la casilla de aviso en el HUD es T31; sin API Known Folders de Windows (derivación por home/OneDrive) |
| T30 | **SEC-19 (nuevo, hallado en T7)** | Hecho | `0c53de2` | test_drive 305/0 (RED 280/22: se subieron de verdad `secrets.json` y `google_token.json`), permisos_ficheros 112/0, gw 255/0, routing 244/0, capas 469/0. Ademãs: la suite de Drive decidía los permisos con el settings.json REAL del dueño; ahora corre con config desechable y un test estructural falla si el `permissions` vuelve a ser un stub | Upload real a un Drive de prueba |
| T9 | SEC-06, AI-04 | Hecho | `6fcdced` | opmem_candado 87/0 (RED 22/18), engram 124/0, hermes_engram 57/0, aprendizaje_puertas 94/0, no_robo 120/0, reglas_contrato 68/0, reglas_valores 115/0, correcciones_confirmadas 85/0, apunta_no_es_siempre_memoria 23/0, que_sabes_de_mi 25/0, regresion_conversacion 78/0, no_promete_trabajo 41/0, lo_prometido 257/0, n8n_canal 57/0, specs_v23_mem 58/0, capas 469/0; diferencial base/rama: solo las 4 diferencias buscadas | Pintar la procedencia en el HUD (T31); autenticación del servidor Engram (fuera de este repo) |
| T32 | Bug silencioso hallado en T3 | Hecho | `eb49d61` | aprendizaje_ciclo 149/0; RED contra HEAD con 4 fallos, incluido «el perfil destilado no llega al system prompt» | El perfil del operador ahora SÍ entra en todos los prompts: es el riesgo AI-08 hecho real, redactado desde `eebda43` y visible en `selflearn` |
| T16 | ARQ-05 | Hecho | `2f64a65` | escrituras_atomicas 76/0 (RED 43/23), board_keys 17/0, board_kpis 26/0, board_pattern 29/0, inbox_tasks 74/0, resultados_trabajos 12/0, content_os 80/0, tasks_board 136/0, backup 64/0, ingesta 99/0, capas 481/0, specs_v23 132/0, content_os_honestidad 135/0; diferencial base/rama sobre los 6 stores: idéntico | 32 sitios de `write_text` JSON siguen fuera de estas superficies (23 ficheros), congelados con ratchet en el suite nuevo; tres (`vigilancias`, `websearch`, `youtube`) ya se hacían su propio `.tmp` y habría que absorberlos |

| T11 | AI-03 | Hecho (parcial → cerrado por T11b/T11c) | `4fe9972` | datos_no_confiables 59/0 (RED 0/1 y 33/22), capas 490/0, research_honesty 57/0, llm_runtime 158/0, inbox 185/0 + scale 348/0, n8n_canal 57/0, routing 244/0, lo_prometido 257/0, no_robo 120/0; diferencial de los 5 contextos sin dato: sin diferencias | YouTube/fuentes (T11b), escape de cerca y few-shot (T11c) |
| T11b | AI-03 | Hecho | `e70518c` | datos_no_confiables 84/0 (RED 70/14), youtube 35/0, skill_research 75/0, research_honesty 62/0, source_evidence 17/0, google_browser 27/0, ai_media_honesty 49/0, youtube_video_command 16/0. Design (a): el dato sigue crudo en la fuente y la cerca se pone al render, así que los dos candados de tamaño NO se debilitaron. **Incidente declarado en L28**: una petición real de búsqueda pública (sin credencial ni dato personal) por un doble que faltaba | Transcripción de audio local (necesitaría un origen `audio` nuevo en el vocabulario cerrado) |
| T11c | AI-03 | Hecho | `6029266` | datos_no_confiables 157/0 (RED 123/22 + 9/9 marcas literales en sondeo directo del helper), inbox_scale 351/0 con `_REGISTRO_CRUDOS` girado a `escapa: False`, 20 suites verdes; diferencial de 84 combinaciones de origen×contenido: 0 diferencias salvo la neutralización buscada | Un `audio` origin propio; el few-shot del planificador usa cabecera corta (31 chars), no `bloque()` |

## Estado de la batería (no era verde antes de nosotros)

`tests/run_all.py` sobre `main` ya tenía 2 bloques rojos: `test_inbox_scale` (aserción de tiempo «under 5 s»; 5.18 s bajo carga de batería, 322/0 sola) y `test_aprendizaje_no_robo` (cifras del corpus fijadas en 259/263 cuando el corpus real era 256/260). El segundo se corrigió en `cdd4d28` **tras comparar frase a frase**: las siete promesas que faltaron se fueron de `skills/ai_media/SKILL.md` a propósito («se eliminaron porque no hacían lo que prometían»), así que el corpus se encogió porque nexus dejó de prometer mentiras. El primero queda como ítem abierto: es una aserción de relojía sensible a la carga y no se ensanchó su umbral en silencio.

## Correcciones a la propia auditoría

| T24 | SEC-13, SEC-14, SEC-15, SEC-16 | Hecho | `ce90957` | Gemini: 3 sitios (no 2) + `_sin_claves()` como segunda barrera en `_explain_error`; RED 175/18 → 193/0. Steam: sin shell y `isdigit`; RED 362/24 → 386/0. Spotify: `state` de un solo uso (antes no existía ningún almacenamiento de flujo); RED por `AttributeError` → media 106/0. Errores: 8 handlers con `publicvoice.fallo()`; `/api/home/scan` se llevaba una ruta de Temp y `pc-de-adrian.local:8177`; RED 2/10 → 129/0. Diferencial de 44 formas de excepción: sin diferencias. | `/api/llm_check` y `/api/llm/status_full` siguen dando detalle técnico (diagnóstico local, finding aparte). El `text[-300:]` de docker en `/api/setup/docker` también queda. **Corrección a la auditoría**: `/api/instagram/qr` NO existe; hay `/analisis` y `/competencia` y ninguno devuelve texto de excepción |
| T20 | SEC-11 | Hecho | `c1af942` | Guarda única (`motivo_destino`/`safe_get`), matriz completa de rangos + userinfo + esquemas + formas porcentuales, saltos revalidados con tope en `umbrales.json → red.max_redirecciones`, vigilancias rechazado en la CREACIÓN y en cada tick, `sqlite://` por `path_allowed` antes de mirar si existe. RED 224/21 → GREEN 245/0; 27 suites verdes, diferencial sin diferencias. | Ventana de rebinding DNS→conexión (cerrarla exige conectar a la IP validada reescribiendo Host/SNI); `yt-dlp` con transporte propio; HA por HUD sin guardar (es la función); T20b para `webbrowser.open()` |
| T18 | SEC-10 | Hecho, parcial por diseño | `d29417a` | `esc()` escapa `"`/`'` (29 sitios en atributo, inventariados por categoría), `linkify` acompañó el cambio, `escH` de `mobile.html` consistentes + cerrado su `href` del servidor; CSP + `X-Frame-Options: DENY` en `/`, `/m`, `/setup`; contadores de `reels.js`. RED 25/27 → GREEN 55/0 (y 30/0 SIN node, declarándolo). | Con `'unsafe-inline'` (21 manejadores + 2 bloques en línea) un payload inline sigue ejecutándose: T18b. Resto de escapes inconsistentes: T18c. Tipografía: T18d |
| T29 | SEC-17 | **Pendiente del dueño** | — | — | Rotar la contraseña si alguna instalación antigua conserva el literal, y verificar que el Compose vigente publica 5433 solo en loopback |
| T27 | firma del instalador | **Pendiente del dueño** | — | — | Necesita certificado; decisión de distribución, no de código |

## Correcciones a la auditoría que salieron al implementar

1. **SEC-02 estaba sobredimensionado.** `telegram_bridge.py` hacía `from .. import brain`, un `ImportError` tragado por el `except Exception` del bucle: ninguna orden de Telegram llegaba al cerebro. El TOFU secuestraba el vínculo y bloqueaba al dueño, pero no daba el PC. Se arreglaron las dos cosas en `61396b0`, y por eso cerrar el TOFU era precondition del fix y no un extra.
2. **`main` no estaba verde.** La batería completa da `exit 1` en dos bloques que se reproducen en una copia `git archive` de `main`: `test_aprendizaje_no_robo` (cifras del corpus fijadas en 259/263 cuando el corpus real era 256/260, por `dfd0b92`) y `test_inbox_scale` (aserción de reloj que pasa sola y falla bajo carga). El primero se realineó en `cdd4d28` tras comparar frase a frase; el segundo queda como ítem abierto.
3. **`/api/instagram/qr` no existe** (lo citado en SEC-16): solo hay `/api/instagram/analisis` y `/competencia`, y ninguno devuelve `str(exc)`.
4. **`spotify.py` usa `ROOT/"config"` en vez de `CONFIG_DIR`**, o sea ignora `NEXUS_CONFIG_DIR`: cualquier prueba que toque el token de Spotify no es hermética.
5. **`skills/memory_graph/skill.py:310` promete un «olvida que…» que no existe en sus `patterns`**: el router no lo atiende, así que la respuesta miente sobre una capacidad.
6. **El escáner previo a la subida neutralizaba «por etiqueta»**, lo que abría un punto ciego para un secreto pegado a la marca. Cerrado en `2569050` neutralizando por FORMA.

