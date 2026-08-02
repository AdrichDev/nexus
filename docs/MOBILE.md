# nexus en el móvil (Android e iOS)

La app móvil es el **nodo de nexus**: el mismo círculo del escritorio que se
mueve y se ilumina cuando habla. Tiene las mismas funciones porque **habla con
el backend de tu PC** — no reimplementa nada, manda las órdenes al mismo cerebro.

## Android — APK ya compilado ✔ (`movil/nexus.apk`)

En `movil/nexus.apk` tienes la app **ya compilada y firmada** (~21 KB):

1. Pásala al móvil (WhatsApp a ti mismo, cable, Drive…) y ábrela.
2. Android avisará de «origen desconocido» → **Instalar de todas formas**.
3. La app pide sus permisos (cámara, micro, galería, contactos, ubicación).
4. Botón **«VINCULAR CON nexus»** → se abre la cámara → apunta al **QR**
   que muestra el PC (botón 📱 arriba a la derecha del centro de mando).
5. Vinculado. **Funciona AUNQUE NO estéis en la misma WiFi**: el PC levanta un
   túnel seguro (cloudflared) y el QR lleva la URL + un token de autenticación.
   Sin túnel, el QR lleva la IP local (misma WiFi) como plan B.

Dentro del nodo: ◉ para hablar (voz nativa de Android vía puente `WabiksNative`),
chat de texto, botones 🔊/🔇 IA y 🎙 YO para silenciar a nexus o mutearte,
respuestas por voz (síntesis del móvil) y texto con enlaces que se abren en el
navegador. **Mantén pulsado ◉** ~1 s para re-vincular con otro PC.

> **Firma**: `movil/nexus.keystore` (alias `nexus`, contraseña `nexus2026`).
> GUÁRDALO: las actualizaciones del APK deben firmarse con este mismo keystore
> o Android obligará a desinstalar antes. Reconstruir: ver `movil/` o pedírselo
> al agente (javac + dx + aapt + zipalign + apksigner, sin Android Studio).

## iOS — PWA instalable (no existe .ipa sin Mac)

Apple **no permite** compilar/instalar apps iOS sin un Mac con Xcode y cuenta
de desarrollador (99 €/año). Lo que sí funciona 100 % es la **PWA**, y ya está
preparada con icono y modo app:

1. Ten nexus abierto en el PC y el iPhone en la misma WiFi.
2. Safari → `http://IP-DEL-PC:8177/m`
3. Botón compartir → **«Añadir a pantalla de inicio»**.
4. Aparece el icono de nexus y se abre a pantalla completa como una app,
   con la voz del propio Safari.

> Si algún día quieres el .ipa de verdad: proyecto Capacitor + un Mac
> (o un servicio de build en la nube tipo Ionic Appflow) — el HTML ya vale tal cual.

## Opción sin instalar nada (cualquier móvil)

Navegador → `http://IP-DEL-PC:8177/m` → «Añadir a pantalla de inicio».
El reconocimiento de voz usa el del navegador (Chrome/Safari lo traen).

Para fuera de casa: abre el puerto 8177 en el router hacia el PC, o mejor un
túnel seguro (Tailscale / Cloudflare Tunnel) y entra por esa dirección con
`?host=` → `http://tu-tunel/m?host=tu-tunel`.

## Windows — el .exe

En el PC: doble clic a **`installer\build_exe.bat`** (usa la .venv de run.bat). Genera
`dist\nexus.exe` con su icono, y copia al lado `knowledge\`, `config\` y `.env`
(el exe los lee de su propia carpeta). Para llevarlo a otro PC, copia la carpeta
`dist\` entera. *(PyInstaller no cross-compila: el .exe se genera en Windows.)*

## Encender el PC desde el móvil (Wake-on-LAN)

Sí se puede. Ver la sección "Wake-on-LAN" del README: activas WoL en la BIOS y
en el adaptador de red, guardas la MAC del PC en ⚙, y desde el móvil (u otro PC
de la red) nexus manda el "paquete mágico" que lo enciende. Fuera de casa
necesita abrir un puerto UDP en el router o un relay que ya esté encendido.
