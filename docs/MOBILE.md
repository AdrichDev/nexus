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
5. Tras vincular con el QR, usa la IP local
   en la misma WiFi. Fuera de ella, solo funcionará si el túnel está configurado,
   disponible y accesible desde el móvil; no se ha validado aquí con hardware
   ni con un túnel público.

### Qué cambia en la vinculación desde la 2.8 (roadmap P3-2 · task T21)

**En la app: nada.** El QR ya no lleva el token compartido: lleva un **código de
vinculación** de 8 caracteres, de **un solo uso** y con caducidad
(`vinculacion.ttl_codigo_segundos` en `config/umbrales.json`). El `MainActivity`
no cambia ni una línea, porque no interpreta el token: copia el valor de `token`
a cada dirección de respaldo que guarda (`desdeQR`) y carga la página `/m` con
ella. **Quién canjea el código es la propia página `/m`** (la sirve nexus, no la
app): `POST /api/link/pair` una vez, y a partir de ahí usa el token **propio de
ese teléfono** donde usaba el del QR (`?token=`, `x-nexus-token`, la cookie
`nexus_token` y el WebSocket). En `localStorage` se guarda ese token propio,
nunca el código: un código gastado dejaría el móvil fuera al recargar.

Consecuencias para el APK ya instalado:

- **No hay que reinstalar nada.** Un APK de la 2.8 (o anterior) sigue vinculando
  igual y el botón «REINTENTAR con el último enlace» sigue funcionando. Lo único
  que cambia es que las direcciones que guarda llevan el token de ESE móvil.
- **Los móviles que se vincularon antes siguen entrando** con su token viejo
  («dispositivo antiguo» en el HUD) hasta que el dueño lo revoque. No se quedan
  fuera por actualizar el PC, que es justo lo que no puede pasar sin avisar.
- **Borrar datos de la app** (`resetHost`) sigue siendo el mismo doble toque; para
  volver a vincular, escanea un QR **nuevo** (un código gastado no vale).

> **Sigue pendiente, y es decisión del dueño:** el token viaja en la URL
> (`/m?host=…&token=…`) y por eso, en la LAN, un MITM lo puede leer. Pasar el token
> a una cabecera rompe los APK que ya están instalados, así que no se toca hasta que
> el dueño decida (anotado en `odd/tasks/security-audit-remediation.md`, T12). Lo que
> P3-2 sí cambia es **qué** viaja ahí: un código de un solo uso en el QR, y desde
> ese momento el token de un solo aparato (revocable) en lugar de una credencial
> compartida por todos y para siempre.

Dentro del nodo: ◉ para hablar (voz nativa de Android vía puente `WabiksNative`),
chat de texto, botones 🔊/🔇 IA y 🎙 YO para silenciar a nexus o mutearte,
respuestas por voz (síntesis del móvil) y texto con enlaces que se abren en el
navegador. **Mantén pulsado ◉** ~1 s para re-vincular con otro PC.

### Qué NO hace la app desde la 2.8 (SEC-08 · roadmap P2-5)

Esto vale para el **APK 2.8** (`versionCode` 10). Si en el móvil pone 2.7 o
menos, no lo tiene: hay que recompilar (`movil\COMPILAR_APK.bat`) e instalar.

- **No habla en claro con cualquier sitio.** Antes el manifiesto llevaba
  `usesCleartextTraffic="true"`, que es barra libre: cualquier host de internet,
  en HTTP sin cifrar. Ahora hay `movil/res/xml/network_security_config.xml`
  (TLS anclado solo al almacén del sistema, túnel público obligado a cifrar) y,
  sobre todo, el guardián `urlPermitida()` de `MainActivity`: el WebView
  **rechaza** toda petición en claro cuyo host no sea de tu red — 127/8, 10/8,
  172.16/12, 192.168/16, el 100.64/10 de Tailscale o un nombre `.local`.
  Se aplica a la página, a sus navegaciones y a lo que pide la propia página.
  - **Por qué el XML no lo hace él solo:** Android no admite rangos (CIDR) en
    `network_security_config`, y las direcciones del QR (`http://<ip-lan>:8177`,
    el nombre `.local`, la IP de Tailscale) solo se conocen al emparejar. El
    motivo y lo que todavía se escapa están escritos en ese mismo fichero.
- **No carga contenido mixto.** Una página https (el túnel) ya no puede llamar a
  nada http. Efecto concreto: en modo túnel, la página ya no puede saltar por su
  cuenta a las direcciones http de la LAN; el respaldo **nativo** del APK (carga
  la siguiente dirección guardada) sigue funcionando igual. En modo LAN o
  Tailscale (página http) no cambia nada, y el escáner del QR tampoco.
- **El puente `WabiksNative` solo atiende a tu nexus.** Solo se inyecta cuando el
  host es el que emparejaste con el QR, y además cada método vuelve a comparar la
  dirección cargada con la emparejada antes de hacer nada. Si una página no es la
  tuya, contesta «Por seguridad, esta página no puede usar la voz, las llamadas
  ni WhatsApp del móvil». El nombre del puente NO cambia (renombrarlo rompería
  los APK ya instalados).
- **Llamar y WhatsApp piden permiso en el móvil.** `dial` y `whatsapp` ya no
  disparan nada: sale un diálogo nativo con el número y el mensaje **exactos** y
  botones OK/Cancelar. Es el mismo trato que nexus da en el PC para los envíos.
  La voz (`startVoice`), reenviar la lista de direcciones (`saveHosts`) y
  re-vincular (`resetHost`) siguen sin ceremonia: no sacan nada del teléfono.

> **Sigue pendiente, y es decisión del dueño:** el token de vinculación viaja en
> la URL (`/m?host=…&token=…`) y por eso, en la LAN, un MITM lo puede leer. Pasar
> el token a una cabecera rompe los APK que ya están instalados, así que no se
> toca hasta que el dueño decida (anotado en `odd/tasks/security-audit-remediation.md`, T12).
> Desde P3-2 eso que viaja es el código de un solo uso (en el QR) y luego el token
> propio de cada móvil, revocable uno a uno; la superficie no cambia, la
> credencial sí.

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
de usarlo. Entra por la URL del túnel y vincula el cliente con el QR; `?host=`
solo indica el host y no sustituye la autenticación.

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
