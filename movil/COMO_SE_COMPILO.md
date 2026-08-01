# Cómo se compila nexus.apk

## Lo normal: doble clic

```
movil\COMPILAR_APK.bat
```

Compila, firma con `nexus.keystore` y, si el móvil está enchufado por USB, lo
instala. **No pregunta ninguna contraseña.** La primera vez que no existe
`movil/nexus.keystore` se crea uno nuevo con una clave al azar, guardada en
`movil/keystore.pass` (gitignored, no sale de tu máquina). De ahí en adelante
lee esa clave de ese archivo. Tú nunca tecleas nada.

```
movil\COMPILAR_APK.bat    REM compila, firma e instala; no pregunta nada
```

**La primera instalación desinstala la app vieja una vez** (ver «Firma» más
abajo): perderás la vinculación con el PC, así que reescanea el QR después. A
partir de esa instalación la firma ya es estable y se instala encima sin
desinstalar.

Necesita el SDK de Android en `%LOCALAPPDATA%\Android\Sdk` (build-tools y una
platform con `android.jar`) y un JDK con `javac` — 17 y 21 valen los dos.

## Por qué existe ese .bat (31/07/2026)

Antes esto se compilaba a mano en una máquina Debian, y el binario del repo se
quedó congelado el **24/07** mientras `MainActivity.java` seguía cambiando. El
**31/07** se instaló en el móvil un APK de siete días antes: le faltaba toda la
vinculación multi-dirección (`siguienteCandidato()`, el `&alt=` del QR). La app
funcionaba «mal» sin que nada lo delatara, porque no dice qué versión lleva.

Si compilar cuesta media tarde y una máquina que no es la tuya, no se compila.
De ahí el script.

## Qué hace por dentro

1. `aapt package` — recursos y manifest → `base.apk`, y genera `R.java`
2. `javac -source 8 -target 8 -bootclasspath android.jar` — el bytecode de
   Android no admite versiones más nuevas; `-encoding UTF-8` porque los
   comentarios del fuente llevan tildes
3. `d8 --min-api 23` → `classes.dex`
4. `aapt add` + `zipalign -f -p 4`
5. `apksigner sign --ks nexus.keystore --ks-key-alias nexus`

Dos trampas de `cmd` que costaron un rato:

- **`d8.bat` y `apksigner.bat` se llaman con `call`.** Sin `call`, cmd salta al
  otro `.bat` y NO vuelve: el script padre muere en silencio y con código 0,
  como si hubiera ido bien.
- **Las clases van en la línea de comandos, no en un fichero `@lista`.** La ruta
  de este proyecto lleva espacios y un punto (`22. Proyectos`) y `d8.bat` se
  atraganta con el `@` entrecomillado.

## Firma

Android obliga a firmar **todos** los APK; sin firma no se instala nada. Para
instalar ENCIMA de una app ya puesta (`adb install -r`), el APK nuevo tiene que
llevar el **mismo certificado** que el instalado. Si el certificado cambia, hay
que desinstalar primero.

**Por qué cambia aquí (01/08/2026).** La app que había en el móvil (24/07) se
firmó con el `nexus.keystore` original, y **su clave se perdió**. Sin esa clave
no se puede volver a firmar con ese mismo certificado (`9b88f6b3…`), así que
`install -r` sobre la app vieja falla siempre. La única salida es un keystore
nuevo — y con firma nueva, la primera instalación exige desinstalar la vieja una
vez. (El keystore viejo queda en `nexus.keystore.viejo-sin-clave`, inservible
por no tener clave; se guarda solo como rastro.)

`COMPILAR_APK.bat` genera ese keystore nuevo automáticamente con una clave al
azar en `movil/keystore.pass` (gitignored). No hay contraseña que teclear ni que
recordar: la firma es local, sirve para instalar en tu móvil y no sale de aquí.
Si algún día quieres poner una clave conocida a mano, está `GUARDAR_CLAVE.bat`,
pero para el uso normal no hace falta.

En la instalación, si `install -r` falla por certificado distinto, el script
desinstala la app vieja y pone la nueva. Eso pasa **una sola vez**: a partir de
ahí siempre es el mismo `nexus.keystore` nuevo y ya instala encima sin más.

## Recursos

`movil/res/` tiene los iconos y `values/styles.xml`. Estuvieron perdidos: el
árbol `res/` nunca se subió y los PNG solo existían dentro de `nexus.apk`. Se
recuperaron del propio APK el 31/07/2026. `movil/res-values/` es el resto de
aquello y ya no lo usa nadie.

## Versiones

| versión | versionCode | qué cambió |
|---------|-------------|------------|
| 2.5 | 7 | llamadas nativas `dial()` + contactos, voz, QR |
| 2.6 | 8 | puente `WabiksNative.whatsapp(number, text)`: abre WhatsApp directo (`com.whatsapp` / `com.whatsapp.w4b`), fallback a `wa.me` |
| 2.7 | 9 | el «✔ Conectado» ya no se canta al leer el QR, sino cuando el HUD ha cargado de verdad (`onPageFinished`). Antes decía «Vinculado con nexus» solo porque el texto del QR empezaba por `http`, y acto seguido te devolvía a la pantalla de inicio. Primera versión compilada desde Windows. |

Para comprobar qué versión hay puesta en el móvil: **Ajustes › Aplicaciones ›
nexus**. O por USB:

```
adb shell dumpsys package com.nexus.app | findstr versionName
```
