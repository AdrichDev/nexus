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
5. Tras vincular con el QR (URL + token de autenticación), usa la IP local
   en la misma WiFi. Fuera de ella, solo funcionará si el túnel está configurado,
   disponible y accesible desde el móvil; no se ha validado aquí con hardware
   ni con un túnel público.

Dentro del nodo: ◉ para hablar (voz nativa de Android vía puente `WabiksNative`),
chat de texto, botones 🔊/🔇 IA y 🎙 YO para silenciar a nexus o mutearte,
respuestas por voz (síntesis del móvil) y texto con enlaces que se abren en el
navegador. **Mantén pulsado ◉** ~1 s para re-vincular con otro PC.

> **Firma de actualizaciones:** conserva el mismo keystore para actualizar la app.
> Guarda el keystore y sus contraseñas fuera del repositorio; proporciona las
> credenciales mediante variables de entorno locales al compilar, nunca en guías.

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

Para acceder fuera de casa, evita publicar directamente el puerto 8177
del router: expondría el servidor en Internet. Prefiere un túnel con control
de acceso (Tailscale / Cloudflare Tunnel), configurado y comprobado antes
de usarlo. Entra por la URL del túnel y vincula el cliente con el QR y su
token; `?host=` solo indica el host y no sustituye la autenticación.

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
