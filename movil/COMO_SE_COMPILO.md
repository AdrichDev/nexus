# Cómo se compiló nexus.apk v2.6 (sin Android Studio)

Toolchain (Debian/Ubuntu, todo por apt — sin descargas de Google):
    apt-get install aapt aapt2 apksigner zipalign dalvik-exchange \
                    android-sdk-build-tools libandroid-23-java android-sdk-platform-23

Pasos (ANDROID_JAR = /usr/lib/android-sdk/platforms/android-23/android.jar):
    1. aapt package -f -m -M AndroidManifest.xml -S res -A assets -I $ANDROID_JAR -J gen -F base.apk
    2. javac -source 8 -target 8 -bootclasspath $ANDROID_JAR -d classes -sourcepath src:gen \
             src/com/nexus/app/MainActivity.java gen/com/nexus/app/R.java
       (OBLIGATORIO -source/-target 8: dx no acepta bytecode Java 9+)
    3. dalvik-exchange --dex --output=classes.dex classes
    4. aapt add base.apk classes.dex   (renombra base.apk → nexus-unsigned.apk antes)
    5. zipalign -f -p 4 nexus-unsigned.apk nexus-aligned.apk
    6. apksigner sign --ks nexus.keystore --ks-key-alias nexus --ks-pass env:KS_PASS \
                 --key-pass env:KEY_PASS --out nexus.apk nexus-aligned.apk

Firma: MISMO keystore (la contrasena va en las variables de entorno
KS_PASS y KEY_PASS; NUNCA escrita aqui: este archivo se sube al repo)
MISMO keystore que v2.5 (mismo SHA-256) → se instala ENCIMA sin desinstalar.

Cambio de v2.6 respecto a v2.5:
  - Nuevo puente JS→nativo WabiksNative.whatsapp(number, text): abre WhatsApp
    DIRECTO (com.whatsapp / com.whatsapp.w4b) con chat + texto; fallback a wa.me.
  - versionCode 7→8, versionName 2.5→2.6.
  - Todo lo demás (llamadas nativas dial()+contactos, voz, QR) intacto.
