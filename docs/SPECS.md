# SPECS v18 — instalación agnóstica, permisos, vinculación QR y control de voz
_2026-07-19 · Cada spec incluye su criterio de aceptación y el RESULTADO de la validación
(ejecutada en sandbox con el cerebro/las interfaces reales antes de la entrega)._

## SPEC 1 — Instalador de Windows tipo asistente
**Qué:** instalación como cualquier programa: bienvenida → elegir carpeta → barra de
progreso → acceso directo en escritorio y menú inicio → desinstalador en «Agregar o
quitar programas».
**Cómo:** `installer/nexus_installer.nsi` (NSIS/MUI2, en español) +
`installer/build_installer.bat`.
Flujo en el PC: `installer\build_exe.bat` (crea dist\) → `installer\build_installer.bat` (crea
`nexus-Setup.exe`; si falta NSIS, abre su página de descarga).
**✔ VALIDADO:** compilado con makensis 3.09 sobre una dist de prueba → instalador
generado; contiene nexus.exe + knowledge + config y **excluye `data/`** (0 coincidencias).

## SPEC 2 — Asistente de primera ejecución
**Qué:** al abrir nexus recién instalado (setup_done=false) aparece `setup.html`:
0 bienvenida · 1 nombre · 2 personalidad · 3 permisos · 4 base de datos · 5 Google ·
6 IA/tokens/LLMs locales · 7 resumen. Cada opción con su descripción. Endpoints
`/api/setup/state|save|docker|scan_models|finish` + `/api/personalities`. Reaccesible
en `/setup`.
- **BD:** «Local» (archivos en la carpeta de instalación, sin requisitos) / «Docker»
  (pgvector+n8n; si no está instalado muestra el enlace de descarga de Docker Desktop
  y, si está, botón que CREA los contenedores con un compose generado) / «Servidor»
  (URL Postgres).
- **Google:** 6 pasos + vídeo de YouTube para crear Client ID/Secret.
**✔ VALIDADO (Playwright, recorrido completo):** carpetas visibles al elegir «carpetas»,
Docker detectado como no instalado + enlace de descarga mostrado, vídeo visible, modelos
locales detectados, resumen correcto, payload guardado exacto (nombre/personalidad/
permisos/carpetas/secretos) y finish llamado. 8/8 comprobaciones.

## SPEC 3 — Personalidades reales
**Qué:** 6 personalidades (JARVIS, Profesional, Colega, Sargento, Zen, Canalla) en
`PERSONALITIES` (llm.py). No es cosmético: cada una inyecta un bloque distinto en el
system prompt del modelo. Select en el setup y en ⚙ con descripción.
**✔ VALIDADO:** los 6 prompts generados son distintos entre sí, el bloque «SARGENTO»
solo aparece en sargento, y el nombre del operador se inyecta en todos.

## SPEC 4 — Permisos estilo sandbox
**Qué:** como los permisos de un agente: `perm_hardware` (leer CPU/RAM/placa/discos)
y `perm_files` = `sandbox` (solo data/sandbox) | `carpetas` (lista blanca) | `todo`.
Se eligen en la instalación y se cambian en ⚙ → Permisos. Aplicados en /api/hardware,
skill Sistema (informe/temperaturas), skill Archivos (crear/mover/copiar/renombrar/
explorar/buscar/leer/papelera) y Memoria (aprender documentos/carpetas).
**✔ VALIDADO:** unit tests de path_allowed en los 3 modos (True/False correctos) +
end-to-end con el cerebro real: en sandbox DENIEGA crear en el escritorio con mensaje
claro, PERMITE dentro de data/sandbox, y el toggle de hardware corta el informe en
caliente. El banco de regresión completo sigue 20/20 en modo «todo».

## SPEC 5 — Vinculación QR fuera de la WiFi (IMPORTANTÍSIMO)
**Qué:** botón 📱 en el HUD → arranca un túnel público (cloudflared quick tunnel,
gratis y sin cuenta; se AUTO-DESCARGA al config/ del PC o muestra el enlace) → QR con
`https://xxx.trycloudflare.com/m?host=…&token=…`. El token vive en secrets y protege
TODO acceso remoto: middleware HTTP + WebSocket exigen token solo al tráfico del túnel
(cabecera Cf-Connecting-Ip); lo local/LAN pasa libre. Plan B sin túnel: QR con IP local.
**✔ VALIDADO:** middleware 5/5 (local 200 · remoto sin token 401 · token bueno 200 +
cookie recordada · token malo 401 · solo-cookie 200); QR PNG generado por el backend y
**decodificado por el MISMO motor jsQR que lleva el APK** (roundtrip completo con URL
y token intactos); modal del HUD pinta QR + estado del túnel.

## SPEC 6 — APK: solo interfaz + escáner QR + permisos
**Qué:** la app ya no pide IP al abrir: pantalla con **«VINCULAR CON nexus»** →
escáner de cámara (getUserMedia + jsQR embebido) → guarda URL+token y abre el nodo.
Pide permisos de cámara, micrófono, galería, contactos y ubicación al primer arranque.
Los enlaces externos que da la IA se abren en el navegador del móvil (Intent). Mantener
pulsado ◉ = re-vincular. IP manual como plan B (misma WiFi). v2 firmado con el MISMO
keystore (actualiza sobre v1 sin desinstalar).
**✔ VALIDADO:** badging correcto (v2, 8 permisos, assets del escáner dentro, firma
verificada) + decode jsQR probado con el QR real del backend (SPEC 5).

## SPEC 7 — Mute doble (PC y móvil)
**Qué:** dos botones en ambos lados: 🔇 IA (nexus sigue «hablando» — impulsos del
núcleo incluidos — pero sin sonido; en móvil corta la síntesis) y 🎙 YO (`mic_muted`
en backend: micro abierto, wake word y ciclo de voz dejan de oírte; en móvil bloquea
el botón de hablar). La respuesta llega SIEMPRE por texto y, si no está muteada, por voz
(TTS del PC / speechSynthesis del móvil).
**✔ VALIDADO (Playwright):** HUD — mute IA se enciende y persiste (localStorage), mute
YO envía `mic_muted:true` al backend; móvil — ambos toggles OK. Backend: voice_cycle
responde «estás muteado», open_mic_loop y wake_loop saltan mientras mic_muted.

## SPEC 8 — Texto seleccionable + URLs clicables + memoria virgen
**Qué:** todo lo que muestra la IA (chat, centro de mando, mini-ventanas, móvil) es
seleccionable para copiar; toda URL en sus respuestas se convierte en enlace que abre
el NAVEGADOR real (PC: /api/open_url + webbrowser; móvil: Intent al navegador).
Instalación desde cero SIN memoria: ni el .exe ni el instalador llevan `data/` — solo
los nodos de conocimiento predefinidos (knowledge/).
**Guardas (SEC-11 / T20b):** `/api/open_url` y «abre la web de …» solo abren destinos
públicos por `http`/`https`. Un `file:///…`, una ruta de red UNC, `smb://…`, un enlace
con `usuario:clave@` dentro o un destino interno (loopback, red local, CGNAT,
metadatos de la nube) se rechazan con la negativa en español y **sin llamar al
navegador**, porque el que abre es el navegador del operador con su sesión. Única
excepción: el Home Assistant declarado en ⚙ (`homeassistant_url`), comparado por
esquema + equipo + puerto exactos y **sin valor por defecto**.
**✔ VALIDADO (Playwright):** enlace renderizado como `<a class="ext">`, clic → POST
/api/open_url con la URL exacta; user-select:text computado en el chat; instalador sin
`data/` (SPEC 1); respaldo REST ahora también pinta la respuesta en el chat.

## SPEC 9 — Supresión completa (un dato purgado no queda en ningún almacén)
**Qué:** «olvida X» deja de ser una promesa parcial. `POST
/api/memoria/purga/previsualizar` devuelve, además del plan de siempre, la lista
`almacenes`: cada sitio donde el hecho está copiado, con qué se va a hacer con
él, cuántos elementos lleva lo purgado (por categoría), qué se declara fuera de
alcance y por qué. `POST /api/memoria/purga/aplicar` actúa sobre ESA lista.

Alcance por almacén: la nota y las filas de `memories` a la papelera/retiradas
(como hasta ahora); los fragmentos de `data/rag/knowledge.jsonl` salen del
almacén local; el espejo de `data/memory/documentos/` va a la MISMA papelera y
se restaura con la nota; la memoria operativa (`data/engram_ops.json`) y Engram
reciben la orden de olvidar; `data/webcache.json` pierde la entrada. Los
registros (`interactions.jsonl`, `logs/audit.jsonl`, `logs/recall.jsonl`) y
`data/jobs.json` son un alcance APARTE (`incluir_logs`, por defecto apagado): se
quitan líneas enteras y las demás quedan intactas byte a byte. Los zips de
`data/backups/` NO se reescriben ni se borran: el informe dice cuántos son y con
qué fechas, y el camino es la rotación (7 diarias) o el borrado a mano.

Honestidad obligatoria: si Engram no responde, no está instalado o no expone
borrado, el resultado es **no completado** (y aparece en «sobrevive» con su
motivo), nunca «hecho». Igual si el plan no incluye los registros y se pide
incluirlos al aplicar: se rechaza y se pide una previsualización nueva.
El candado del borrado duro no cambia: `borrar_definitivo` sigue exigiendo el
«sí» del operador y es el único que destruye ficheros.
**✔ VALIDADO (suite):** `tests/unit/memory/test_purga_completa.py` (116
comprobaciones) — previsualización con todos los almacenes y las fechas de los
backups; barrido real con Engram doblado, caché invalidada en RAM y resto de
registros intactos byte a byte; Engram caído y Engram sin endpoint de borrado
reportados como no completados; restaurar devuelve nota Y espejo; nada de lo
ajeno se mueve; el barrido se niega cuando la carpeta de memoria no está dentro
del `data/` que le toca.

---
### Pendiente de probar EN VIVO en tu PC/móvil (no reproducible en sandbox)
1. El túnel cloudflared real (primera vez descarga ~60 MB a config/).
2. La cámara del APK en tu móvil (el decoder está validado; la cámara física no).
3. `installer\build_exe.bat` + `installer\build_installer.bat` en tu Windows.
