# -*- coding: utf-8 -*-
"""LA APP ANDROID DEJA DE FIARSE DE CUALQUIER PAGINA Y DE CUALQUIER TRANSPORTE.

Auditoría de seguridad, SEC-08 (roadmap P2-5, task T12). Se comprueban, sobre el
texto del proyecto (Java, XML y las dos HTML que usan el puente), las cinco
cosas que pidió el hallazgo:

  1. `usesCleartextTraffic="true"` desaparece del manifiesto y lo sustituye un
     `network_security_config` de verdad, referenciado desde el manifiesto.
  2. Se acabó `MIXED_CONTENT_ALWAYS_ALLOW`: una página https ya no puede cargar
     ni llamar a nada http.
  3. El puente `WabiksNative` solo se inyecta en hosts EMPAREJADOS y, además,
     cada método del puente vuelve a comprobar la página actual (3a + 3b; el
     porqué de las dos está en MainActivity).
  4. `dial` y `whatsapp` no disparan nada sin un diálogo nativo con el número y
     el mensaje exactos y OK/Cancelar. `startVoice`/`saveHosts`/`resetHost`
     siguen sin ceremonia.
  5. El texto que va a `evaluateJavascript` viaja como literal JSON, no con el
     escape a mano de antes, y se prueba con una cadena que contiene `"`, `'`,
     `\\`, un salto de línea y `</script>`.

LO QUE ESTA SUITE **NO** PRUEBA (leerlo antes de dar nada por bueno):

  - No compila la APK y no arranca un móvil. Nadie de esta suite ha visto un
    WebView funcionando, ni un diálogo nativo, ni una llamada.
  - El literal JavaScript se prueba contra una REIMPLEMENTACIÓN en Python de la
    regla de escapado (JSON de `org.json.JSONObject.quote` + cerrar `<`/`>`) y
    contra la FORMA del código Java (que llame a esas piezas). Eso demuestra el
    contrato del escapado y que el fuente usa el mecanismo correcto; NO
    demuestra lo que hace el runtime de Android. Para eso hace falta compilar y
    un dispositivo.
  - La política de transporte tiene un límite real de la plataforma: Android NO
    admite rangos CIDR en `network_security_config` (solo nombres/IP sueltas) y
    el QR ofrece `http://<ip-lan>:8177`, que solo se conoce al emparejar. Por eso
    el XML no puede, él solo, «permitir claro únicamente a la LAN»: lo que el
    XML sí hace (TLS anclado al sistema, túnel sin claro, el claro del hogar
    documentado) y lo que hace el guardián de `MainActivity.urlPermitida()` se
    comprueban por separado. Quien lea solo el XML verá
    `cleartextTrafficPermitted="true"` y creerá que no se arregló nada: la
    puerta que impide hablar en claro con internet está en el Java, y esta suite
    comprueba que existe, que cubre los cinco rangos y que se aplica a la página
    principal, a las peticiones de la página y a las navegaciones.
  - Necesitan build + móvil (NO comprobado aquí): que `aapt` acepte el atributo
    `android:networkSecurityConfig` contra el android.jar que use el operador;
    que el WebView respete de verdad el rechazo del claro; que `AlertDialog` se
    vea; que `removeJavascriptInterface` surta efecto en el siguiente documento;
    y que el literal escapado llegue entero a `wabiksVoiceResult`.

Estilo: igual que `tests/unit/frontend/test_task_cards.py` (leer el fichero y
afirmar cosas sobre su texto), porque los activos no son Python.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\mobile\\test_puente_nativo.py
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MOVIL = ROOT / "movil"
JAVA_PATH = MOVIL / "MainActivity.java"
MANIFIESTO_PATH = MOVIL / "AndroidManifest.xml"
NSC_PATH = MOVIL / "res" / "xml" / "network_security_config.xml"
SCAN_HTML_PATH = MOVIL / "assets" / "scan.html"
MOBILE_HTML_PATH = ROOT / "frontend" / "mobile.html"

JAVA = JAVA_PATH.read_text(encoding="utf-8")
MANIFIESTO = MANIFIESTO_PATH.read_text(encoding="utf-8")
NSC_TXT = NSC_PATH.read_text(encoding="utf-8") if NSC_PATH.is_file() else ""
SCAN_HTML = SCAN_HTML_PATH.read_text(encoding="utf-8")
MOBILE_HTML = MOBILE_HTML_PATH.read_text(encoding="utf-8")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - consola cp1252 de Windows
    pass

_ok = 0
_fail: list[str] = []


def check(cond, msg: str) -> bool:
    global _ok
    if cond:
        _ok += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)
    return bool(cond)


def cuerpo(nombre: str, fuente: str | None = None) -> str:
    """El cuerpo de `nombre(...) { ... }` contando llaves, o "" si no está."""
    fuente = JAVA if fuente is None else fuente
    m = re.search(rf"\b{re.escape(nombre)}\s*\([^)]*\)\s*\{{", fuente)
    if not m:
        return ""
    i = m.end() - 1
    nivel = 0
    for j in range(i, len(fuente)):
        if fuente[j] == "{":
            nivel += 1
        elif fuente[j] == "}":
            nivel -= 1
            if nivel == 0:
                return fuente[i:j + 1]
    return ""


def primera_instruccion(texto: str) -> str:
    """El método sin la llave de apertura ni los comentarios de cabecera."""
    t = texto.lstrip("{").strip()
    while t.startswith("//"):
        t = t.split("\n", 1)[1].lstrip() if "\n" in t else ""
    return t


def metodos_del_puente() -> dict[str, str]:
    """Nombre → cuerpo de cada método anotado con @JavascriptInterface."""
    fuera: dict[str, str] = {}
    for m in re.finditer(r"@JavascriptInterface\s*\n\s*public\s+void\s+(\w+)\s*\(", JAVA):
        fuera[m.group(1)] = cuerpo(m.group(1))
    return fuera


# ─────────────────────────── 1. transporte: manifiesto ───────────────────────
print("== 1) manifiesto: se acabó el claro a cualquier host ==")
check("usesCleartextTraffic" not in MANIFIESTO,
      'el manifiesto ya no lleva usesCleartextTraffic (era una barra libre a cualquier host)')
check('android:networkSecurityConfig="@xml/network_security_config"' in MANIFIESTO,
      "el manifiesto referencia @xml/network_security_config")
check("android:networkSecurityConfig" in MANIFIESTO
      and MANIFIESTO.index("android:networkSecurityConfig") < MANIFIESTO.index("</application>"),
      "el atributo está dentro de <application>")
check('android:minSdkVersion="23"' in MANIFIESTO and 'android:targetSdkVersion="28"' in MANIFIESTO,
      "minSdk 23 / targetSdk 28 siguen siendo los que justifican los APIs elegidos")
check("android.permission.INTERNET" in MANIFIESTO, "INTERNET sigue declarado (el nodo lo necesita)")

# ─────────────────────── 2. transporte: network security config ──────────────
print("== 2) network_security_config ==")
check(NSC_PATH.is_file(), f"existe {NSC_PATH.relative_to(ROOT).as_posix()}")
raiz = None
if NSC_TXT:
    try:
        raiz = ET.fromstring(NSC_TXT)
    except ET.ParseError as exc:
        check(False, f"el XML del network_security_config parsea ({exc})")
if raiz is not None:
    check(raiz.tag == "network-security-config", "la raíz es <network-security-config>")
    base = raiz.find("base-config")
    check(base is not None, "hay <base-config> explícito (no se deja al defecto de la versión)")
    if base is not None:
        check(base.get("cleartextTrafficPermitted") in ("true", "false"),
              "base-config declara cleartextTrafficPermitted de forma explícita")
        anclas = base.find("trust-anchors")
        check(anclas is not None and any(c.get("src") == "system"
                                        for c in anclas.findall("certificates")),
              "las anclas de confianza son SOLO las del sistema (una CA instalada por el usuario es un MITM)")
    dominios_tunel = [d.text for cfg in raiz.findall("domain-config")
                      if cfg.get("cleartextTrafficPermitted") == "false"
                      for d in cfg.findall("domain")]
    check(any((d or "").endswith("trycloudflare.com") for d in dominios_tunel),
          "el túnel público (trycloudflare.com) tiene prohibido el claro de forma explícita")

# El XML documenta por qué queda claro en casa y qué se escapa todavía.
for pieza, motivo in (
    ("8177", "el QR ofrece http://<ip-lan>:8177"),
    ("http://", "se nombra el esquema que se sigue permitiendo en la LAN"),
    ("192.168", "se enumeran los rangos privados que sí se usan"),
    ("172.16", "se enumera 172.16/12"),
    ("100.64", "se enumera el rango de Tailscale (el QR también lo ofrece en http)"),
    ("MainActivity", "se dice DÓNDE vive la puerta real (el XML no puede con CIDR)"),
    ("token", "se dice lo que todavía se escapa en claro en la LAN (el token)"),
    ("MITM", "se nombra el ataque que queda vivo en la LAN"),
):
    check(pieza in NSC_TXT, f"el comentario del XML explica {motivo}")

print("== 3) el claro, solo a la red de casa (el XML no puede con CIDR) ==")
check("urlPermitida" in JAVA, "existe urlPermitida(): la política de transporte de verdad")
check("esHostLocal" in JAVA, "existe esHostLocal(): los rangos privados, en código")
rangos = cuerpo("esHostLocal")
for pieza, motivo in (("127", "127.0.0.0/8"), ("10", "10.0.0.0/8"),
                      ("172", "172.16.0.0/12"), ("192", "192.168.0.0/16"),
                      ("168", "192.168.0.0/16"), ("100", "100.64.0.0/10 (Tailscale)"),
                      ("64", "100.64.0.0/10 (Tailscale)"),
                      (".local", "los nombres .local del QR")):
    check(pieza in rangos, f"el guardián cubre {motivo}")
check("esHostLocal" in cuerpo("urlPermitida"),
      "urlPermitida() delega el «¿es de casa?» en esHostLocal()")
check('"https".equals' in cuerpo("urlPermitida") or "https" in cuerpo("urlPermitida"),
      "urlPermitida() deja pasar https siempre (el túnel va cifrado)")
check('"ws".equals' in cuerpo("urlPermitida"),
      "urlPermitida() también cierra el ws:// en claro (mismo agujero que un fetch)")
check("ByteArrayInputStream" in JAVA or "bloqueado" in JAVA,
      "hay una respuesta vacía para cortar el claro fuera de casa")
peticion = ""
if "shouldInterceptRequest" in JAVA:
    _i = JAVA.index("shouldInterceptRequest")
    peticion = JAVA[_i:_i + 700]
check("urlPermitida" in peticion,
      "las peticiones de la propia página (fetch/XHR) también pasan por urlPermitida()")
navegar = ""
if "shouldOverrideUrlLoading(WebView v, String u)" in JAVA:
    _i = JAVA.index("shouldOverrideUrlLoading(WebView v, String u)")
    navegar = JAVA[_i:_i + 500]
check("urlPermitida" in navegar, "las navegaciones de la página pasan por urlPermitida()")
sin_puente = cuerpo("showWeb")
sin_puente = sin_puente[:sin_puente.index("new WebView")] if "new WebView" in sin_puente else sin_puente
check("urlPermitida" in sin_puente,
      "la dirección inicial se comprueba ANTES de crear el WebView")

print("== 4) mixed content ==")
check("setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW)" not in JAVA,
      "ya no se fuerza mixed content ALWAYS_ALLOW")
check("WebSettings.MIXED_CONTENT_NEVER_ALLOW" in JAVA,
      "el modo de contenido mixto se fija explícitamente en NEVER_ALLOW")
check("MIXED_CONTENT_NEVER_ALLOW" in cuerpo("showWeb"),
      "NEVER_ALLOW se aplica al WebView del nodo remoto")
check("setMixedContentMode" not in cuerpo("showScanner"),
      "el escáner local (asset file://) no necesita política de mixed content")

# ───────────────────── 5. el puente, solo con quien emparejó ─────────────────
print("== 5) puente: solo para el host emparejado ==")
check("removeJavascriptInterface" in JAVA,
      "se retira el puente cuando la página no es del host emparejado")
check('private static final String PUENTE = "WabiksNative";' in JAVA,
      "el nombre del puente es una constante y sigue siendo WabiksNative (renombrar rompe APKs ya instaladas)")
check(JAVA.count('"WabiksNative"') == 1,
      "WabiksNative no se escribe a mano en ningún otro sitio")
check("aplicaPuente(" in JAVA, "existe aplicaPuente(): pone o quita el puente según el host")
check("aplicaPuente(v, u)" in JAVA or "aplicaPuente(v,u)" in JAVA,
      "se re-evalúa en cada navegación (onPageStarted), no solo al crear el WebView")
check("onPageStarted" in JAVA and "aplicaPuente" in cuerpo("showWeb"),
      "el WebViewClient del nodo revisa el host en cada navegación")
check("esHostEmparejado" in JAVA, "existe esHostEmparejado()")
check("hostsGuardados()" in cuerpo("esHostEmparejado"),
      "el host se compara con lo que el operador emparejó (SharedPreferences), no con una lista fija")
check("puentePermitido" in JAVA, "existe puentePermitido(): la comprobación dentro del puente (3b)")
check("file:///android_asset/" in JAVA,
      "el escáner local (asset propio) sigue pudiendo usar el puente para leer el QR")

metodos = metodos_del_puente()
esperados = {"linked", "cancelScan", "startVoice", "dial", "whatsapp", "saveHosts", "resetHost"}
check(set(metodos) == esperados,
      f"el puente expone exactamente los 7 métodos de siempre (faltan={sorted(esperados - set(metodos))}, "
      f"sobran={sorted(set(metodos) - esperados)})")
for nombre, texto in metodos.items():
    check(primera_instruccion(texto).startswith("if (!puentePermitido())"),
          f"{nombre}(): lo PRIMERO que hace es comprobar la página actual")
check("Toast" in cuerpo("fueraDeConfianza") or "Toast" in JAVA,
      "el rechazo se le dice al operador (no se falla en silencio)")
aviso = cuerpo("fueraDeConfianza") + cuerpo("puentePermitido")
check("seguridad" in aviso.lower() or "esta pagina" in aviso.lower() or "página" in aviso,
      "el rechazo del puente está en español y se entiende")

# ─────────────────────── 5. confirmación nativa de dial/whatsapp ─────────────
print("== 6) dial y whatsapp: confirmación nativa ==")
check("AlertDialog" in JAVA, "se usa un diálogo nativo (AlertDialog)")
conf = cuerpo("confirmaNativo")
check('setPositiveButton("OK"' in conf.replace("'", '"') or '"OK"' in conf,
      "el diálogo tiene un botón OK")
check("Cancelar" in conf, "el diálogo tiene un botón Cancelar")
check("setMessage" in conf, "el diálogo ENSEÑA el número/mensaje, no solo pregunta «¿seguro?»")

dial = cuerpo("doDial")
whats = cuerpo("doWhatsApp")
check("confirmaNativo(" in dial, "dial pide confirmación antes de nada")
check("confirmaNativo(" in whats, "whatsapp pide confirmación antes de nada")
check("startActivity" not in dial,
      "dial NO dispara el Intent antes de que el operador acepte")
check("startActivity" not in whats,
      "whatsapp NO dispara el Intent antes de que el operador acepte")
check("llamaDeVerdad" in dial and "run()" in dial,
      "dial deja el Intent en una acción que solo se ejecuta desde el OK")
check("abreWhatsApp" in whats and "run()" in whats,
      "whatsapp deja el Intent en una acción que solo se ejecuta desde el OK")
check("startActivity" in cuerpo("llamaDeVerdad") and "tel:" in cuerpo("llamaDeVerdad"),
      "llamaDeVerdad() es quien marca de verdad (tel:)")
check("startActivity" in cuerpo("abreWhatsApp") and "com.whatsapp" in cuerpo("abreWhatsApp"),
      "abreWhatsApp() es quien abre WhatsApp de verdad")
check("numero" in conf or "numero" in dial,
      "la confirmación de llamada lleva el NÚMERO exacto")
check("msg" in whats or "Mensaje" in whats,
      "la confirmación de WhatsApp lleva el MENSAJE exacto")
for ligero in ("startVoice", "saveHosts", "resetHost"):
    check("confirmaNativo" not in metodos.get(ligero, ""),
          f"{ligero} sigue funcionando sin ceremonia (no pide confirmación)")

# ───────────────────────── 6. el literal JS, sin escape a mano ───────────────
print("== 7) evaluateJavascript: literal JSON, no escape a mano ==")
check("JSONObject.quote" in JAVA, "el texto se codifica con org.json.JSONObject.quote")
check('replace("\\\\", "")' not in JAVA, "ya no se «escapa» el texto quitándole las barras")
check("replace(\"'\", \"\\\\'\")" not in JAVA, "ya no se «escapa» el texto a mano con la comilla simple")
lit = cuerpo("jsLiteral")
check(bool(lit), "existe jsLiteral()")
check("JSONObject.quote" in lit, "jsLiteral() delega en JSONObject.quote")
check("<" in lit and ">" in lit and "u003C" in lit,
      "jsLiteral() cierra además </script> (el JSON no escapa < ni >)")
check("jsLiteral(" in JAVA and "wabiksVoiceResult(" in JAVA,
      "la voz del móvil se manda con jsLiteral()")
voz = ""
if "wabiksVoiceResult(" in JAVA:
    _i = JAVA.index("wabiksVoiceResult(")
    voz = JAVA[_i:_i + 160]
check("jsLiteral(text)" in voz, "wabiksVoiceResult recibe el literal de jsLiteral(text)")

# ── la prueba de fuga, con la MISMA regla que jsLiteral() ────────────────────
FIXTURE = "di \"hola\" y 'adios' con \\ y salto\nde linea </script><img onerror=x>"


def _json_quote(texto: str) -> str:
    """org.json.JSONObject.quote tal como lo implementa Android."""
    salida = ['"']
    for c in texto:
        if c in ('"', "\\"):
            salida.append("\\" + c)
        elif c == "\t":
            salida.append("\\t")
        elif c == "\n":
            salida.append("\\n")
        elif c == "\r":
            salida.append("\\r")
        elif c == "\b":
            salida.append("\\b")
        elif c == "\f":
            salida.append("\\f")
        elif ord(c) < 0x20:
            salida.append("\\u%04x" % ord(c))
        else:
            salida.append(c)
    salida.append('"')
    return "".join(salida)


def js_literal(texto: str) -> str:
    """El mismo resultado que MainActivity.jsLiteral()."""
    return _json_quote(texto).replace("<", "\\u003C").replace(">", "\\u003E")


_ESC = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
        "n": "\n", "r": "\r", "t": "\t"}


def lee_literal(js: str, i: int = 0) -> tuple[str, int]:
    """Lee un literal de cadena JS de comilla doble y devuelve (valor, fin)."""
    if js[i] != '"':
        raise AssertionError("el literal no empieza por comilla")
    i += 1
    fuera: list[str] = []
    while i < len(js):
        c = js[i]
        if c == '"':
            return "".join(fuera), i + 1
        if c == "\\":
            i += 1
            e = js[i]
            if e == "u":
                fuera.append(chr(int(js[i + 1:i + 5], 16)))
                i += 5
                continue
            fuera.append(_ESC[e])
            i += 1
            continue
        if c == "\n":
            raise AssertionError("salto de línea crudo: el literal se rompe")
        fuera.append(c)
        i += 1
    raise AssertionError("literal sin cerrar")


print("== 8) intento de fuga con \" ' \\ salto y </script> ==")
for pieza, motivo in (('"', "comilla doble"), ("'", "comilla simple"), ("\\", "barra"),
                      ("\n", "salto de línea"), ("</script>", "cierre de script")):
    check(pieza in FIXTURE, f"el fixture lleva {motivo}")

codificado = js_literal(FIXTURE)
check(codificado.startswith('"') and codificado.endswith('"'),
      "el resultado es un literal entre comillas")
check(codificado.replace('\\"', "").count('"') == 2,
      "no queda ninguna comilla doble sin escapar (solo la que abre y la que cierra)")
check("\n" not in codificado, "no queda ningún salto de línea crudo")
check("</script>" not in codificado, "</script> no sobrevive: no puede cerrar el <script>")
valor, fin = lee_literal(codificado)
check(valor == FIXTURE, "el literal se lee entero y devuelve EXACTAMENTE el texto original")

llamada = "wabiksVoiceResult && wabiksVoiceResult(" + codificado + ")"
prefijo = "wabiksVoiceResult && wabiksVoiceResult("
check(llamada.startswith(prefijo), "la llamada empieza como debe")
valor2, fin2 = lee_literal(llamada, len(prefijo))
check(valor2 == FIXTURE, "dentro de la llamada el argumento sigue siendo el texto original")
check(llamada[fin2:] == ")", "después del argumento SOLO queda el cierre: no se puede inyectar código")

# La regla vieja SÍ se rompía con este mismo texto: así el fixture prueba algo.
viejo = ("wabiksVoiceResult && wabiksVoiceResult('"
         + FIXTURE.replace("\\", "").replace("'", "\\'") + "')")
roto = False
try:
    valor3, fin3 = lee_literal(viejo, len("wabiksVoiceResult && wabiksVoiceResult("))
    roto = valor3 != FIXTURE or viejo[fin3:] != ")"
except AssertionError:
    roto = True
check(roto, "con el escape viejo el mismo texto se salía del literal (el fixture no es decorativo)")

# ─────────────── 8. las dos páginas que usan el puente lo llaman igual ──────
print("== 9) contrato con las páginas que llaman al puente ==")
usados_mobile = set(re.findall(r"WabiksNative\.(\w+)", MOBILE_HTML))
usados_scan = set(re.findall(r"WabiksNative\.(\w+)", SCAN_HTML))
check("WabiksNative" in MOBILE_HTML, "mobile.html sigue llamando a WabiksNative")
check("WabiksNative" in SCAN_HTML, "scan.html sigue llamando a WabiksNative")
check(usados_mobile <= set(metodos),
      f"todo lo que llama mobile.html existe en el puente (sobra={sorted(usados_mobile - set(metodos))})")
check(usados_scan <= set(metodos),
      f"todo lo que llama scan.html existe en el puente (sobra={sorted(usados_scan - set(metodos))})")
check({"dial", "whatsapp"} <= usados_mobile,
      "mobile.html sigue pidiendo dial y whatsapp (los dos que ahora confirman)")

# ──────────── 10. lo que ya funcionaba sigue funcionando (PRESERVE) ─────────
print("== 10) PRESERVE: el flujo de siempre sigue en pie ==")
check('scan.loadUrl("file:///android_asset/scan.html")' in JAVA,
      "el escáner sigue cargando el asset local (la vinculación por QR no cambia)")
check("addJavascriptInterface" in cuerpo("showScanner"),
      "el escáner sigue teniendo puente: es lo que lee el QR")
check("web.loadUrl(url)" in cuerpo("showWeb"),
      "el nodo sigue cargando la dirección emparejada")
check("postDelayed" in cuerpo("showWeb") and "15000" in cuerpo("showWeb"),
      "sigue el vigilante de 15 s contra la pantalla en negro")
check("Conectado con nexus" in cuerpo("showWeb"),
      "sigue el «✔ Conectado» cuando el HUD carga de verdad")
check("onReceivedError" in cuerpo("showWeb") and "siguienteCandidato" in cuerpo("showWeb"),
      "sigue el respaldo de direcciones cuando una vía falla")
check("setDomStorageEnabled(true)" in cuerpo("showWeb") and "setJavaScriptEnabled(true)" in cuerpo("showWeb"),
      "el nodo sigue con JavaScript y localStorage (sin eso el HUD no arranca)")
check('prefs.getString("link_urls", "")' in JAVA and 'putString("link_urls"' in JAVA,
      "se siguen leyendo/grabando las direcciones emparejadas en el mismo sitio")
check("ACTION_DIAL" in cuerpo("llamaDeVerdad") and "ACTION_CALL" in cuerpo("llamaDeVerdad"),
      "se mantiene la elección marcar/abrir marcador según el permiso")
check("com.whatsapp.w4b" in cuerpo("abreWhatsApp") and "wa.me" in cuerpo("abreWhatsApp"),
      "se mantienen WhatsApp Business y el respaldo wa.me")
check("contactNumber(who)" in cuerpo("doDial"),
      "sigue resolviéndose el nombre de contacto antes de confirmar")
check("ACTION_SEND" in cuerpo("abreWhatsApp"),
      "sigue el camino de compartir cuando no hay número")

print()
print(f"test_puente_nativo: {_ok} OK, {len(_fail)} fallos")
print("  (estructural: NO compila la APK ni arranca un móvil — ver el docstring)")
sys.exit(1 if _fail else 0)
