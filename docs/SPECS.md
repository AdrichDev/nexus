# SPECS v18 — instalación agnóstica, permisos, vinculación QR y control de voz
_2026-07-19 · Cada spec incluye su criterio de aceptación y el RESULTADO de la validación
(ejecutada en sandbox con el cerebro/las interfaces reales antes de la entrega)._

## SPEC 1 — Instalador de Windows tipo asistente
**Qué:** instalación como cualquier programa: bienvenida → elegir carpeta → barra de
progreso → acceso directo en escritorio y menú inicio → desinstalador en «Agregar o
quitar programas».
**Cómo:** `nexus_installer.nsi` (NSIS/MUI2, en español) + `build_installer.bat`.
Flujo en el PC: `build_exe.bat` (crea dist\) → `build_installer.bat` (crea
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
**✔ VALIDADO (Playwright):** enlace renderizado como `<a class="ext">`, clic → POST
/api/open_url con la URL exacta; user-select:text computado en el chat; instalador sin
`data/` (SPEC 1); respaldo REST ahora también pinta la respuesta en el chat.

---
### Pendiente de probar EN VIVO en tu PC/móvil (no reproducible en sandbox)
1. El túnel cloudflared real (primera vez descarga ~60 MB a config/).
2. La cámara del APK en tu móvil (el decoder está validado; la cámara física no).
3. `build_exe.bat` + `build_installer.bat` en tu Windows.
