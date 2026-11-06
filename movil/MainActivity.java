package com.nexus.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import org.json.JSONObject;

/**
 * nexus — la app SOLO es la interfaz: todo el cerebro vive en tu PC.
 * Vinculación por QR (funciona FUERA de tu WiFi vía túnel + token) y
 * puente de voz nativo (el WebView no trae la Web Speech API).
 */
public class MainActivity extends Activity {

    private static final String[] PERMS = {
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.READ_CONTACTS,
            Manifest.permission.CALL_PHONE,
            Manifest.permission.ACCESS_FINE_LOCATION,
    };

    private SharedPreferences prefs;
    private WebView web;
    private SpeechRecognizer recognizer;
    private String baseHost = "";

    /* ── SEC-08 (roadmap P2-5) ─────────────────────────────────────────────
       Nombre del puente JavaScript. NO SE RENOMBRA: las paginas ya instaladas
       (frontend/mobile.html y movil/assets/scan.html del APK viejo) y el propio
       manifiesto lo llaman asi; cambiarlo deja sin voz, sin llamada y sin
       WhatsApp a cualquier movil que no reescanee el QR. El hallazgo pide
       acotar el puente, no rebautizarlo. */
    private static final String PUENTE = "WabiksNative";

    /** WebView del escaner (asset local). Se guarda para que el puente sepa con
     *  que pagina esta hablando ahora mismo: el asset es nuestro, el nodo
     *  remoto solo si el host esta emparejado. */
    private WebView escaner;

    /* ── LA VINCULACION NO CADUCA (30/07/2026) ─────────────────────────────
       El fallo que arregla esto: la app guardaba UNA sola direccion. La del
       tunel es aleatoria y distinta en CADA arranque del PC, asi que al apagar
       el ordenador el enlace guardado moria y habia que reescanear el QR. Y la
       del nombre de equipo (MIPC.local) solo vale dentro de casa.
       Ahora se guarda una LISTA: el QR trae varias (nombre del equipo, IP de la
       WiFi, tunel) y, si una no responde, se prueba la siguiente SOLA. Solo se
       manda a reescanear cuando han fallado todas.
       Ademas la propia pagina, ya cargada, llama a WabiksNative.saveHosts(...)
       con la lista al dia: asi, cuando el tunel cambia, la app se entera sin
       que el usuario haga nada. ─────────────────────────────────────────── */
    private java.util.List<String> candidatos = new ArrayList<String>();
    private int candidatoActual = 0;

    private java.util.List<String> hostsGuardados() {
        java.util.List<String> out = new ArrayList<String>();
        String crudo = prefs.getString("link_urls", "");
        for (String u : crudo.split("\\|")) {
            String v = u.trim();
            if (v.length() > 0 && !out.contains(v)) out.add(v);
        }
        String uno = prefs.getString("link_url", "");
        if (uno.length() > 0 && !out.contains(uno)) out.add(uno);
        return out;
    }

    private void guardaHosts(java.util.List<String> lista) {
        StringBuilder sb = new StringBuilder();
        int n = 0;
        for (String u : lista) {
            if (u == null || u.trim().length() == 0) continue;
            if (sb.indexOf(u) >= 0) continue;
            if (n++ > 0) sb.append("|");
            sb.append(u.trim());
            if (n >= 8) break;
        }
        prefs.edit().putString("link_urls", sb.toString()).apply();
    }

    /** Del enlace del QR saca TODAS las direcciones: la principal y las de
     *  respaldo que viajan en &alt=, ya con el token pegado a cada una. */
    private java.util.List<String> desdeQR(String url) {
        java.util.List<String> out = new ArrayList<String>();
        out.add(url);
        try {
            Uri u = Uri.parse(url);
            String alt = u.getQueryParameter("alt");
            String token = u.getQueryParameter("token");
            if (alt != null) {
                for (String base : alt.split(",")) {
                    String b = base.trim();
                    if (b.length() == 0) continue;
                    String sep = b.endsWith("/") ? "" : "/";
                    out.add(b + sep + "m?token=" + (token == null ? "" : token));
                }
            }
        } catch (Exception e) { /* si el QR viene raro, al menos queda el principal */ }
        return out;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("nexus", Context.MODE_PRIVATE);
        askAllPermissions();
        candidatos = hostsGuardados();
        if (candidatos.isEmpty()) {
            showHome();
        } else {
            candidatoActual = 0;
            showWeb(candidatos.get(0));
        }
    }

    /* -------- permisos de la app: cámara, micro, galería, contactos, ubicación -------- */
    private void askAllPermissions() {
        ArrayList<String> need = new ArrayList<String>();
        for (String p : PERMS) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) need.add(p);
        }
        if (!need.isEmpty()) {
            requestPermissions(need.toArray(new String[0]), 7);
        }
    }

    /* ------------------------- pantalla de inicio ------------------------- */
    private void showHome() {
        escaner = null;
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#070e18"));
        root.setGravity(Gravity.CENTER);
        int pad = (int) (26 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        // El nombre va con espacios entre letras (es el estilo del rotulo). OJO:
        // asi escrito, un grep de «nexus» NO lo encuentra. Aqui puso «W A B I K S»
        // hasta el 31/07/2026, meses despues del cambio de nombre, y ningun
        // buscar-y-reemplazar lo pillo nunca por eso mismo.
        title.setText("◈\n\nn e x u s");
        title.setTextColor(Color.parseColor("#22d3ee"));
        title.setTextSize(30f);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        TextView sub = new TextView(this);
        sub.setText("\nTu asistente vive en tu PC.\nEsta app es su nodo remoto.\n");
        sub.setTextColor(Color.parseColor("#6f8aa8"));
        sub.setTextSize(13f);
        sub.setGravity(Gravity.CENTER);
        root.addView(sub);

        Button link = new Button(this);
        link.setText("▸ VINCULAR CON nexus");
        link.setTextSize(16f);
        link.setTextColor(Color.parseColor("#070e18"));
        link.setBackgroundColor(Color.parseColor("#22d3ee"));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = pad / 2;
        root.addView(link, lp);

        TextView how = new TextView(this);
        how.setText("\nEn el PC: botón 📱 del centro de mando → escanea el QR con la cámara."
                + "\nFunciona aunque NO estés en la misma WiFi.");
        how.setTextColor(Color.parseColor("#6f8aa8"));
        how.setTextSize(11f);
        how.setGravity(Gravity.CENTER);
        root.addView(how);

        // si hay un enlace guardado, ofrecer REINTENTAR (p.ej. el PC estaba arrancando)
        final String saved = prefs.getString("link_url", "");
        if (saved.length() > 0) {
            Button retry = new Button(this);
            retry.setText("↻ REINTENTAR con el último enlace");
            retry.setTextSize(12f);
            retry.setTextColor(Color.parseColor("#22d3ee"));
            retry.setBackgroundColor(Color.TRANSPARENT);
            root.addView(retry);
            retry.setOnClickListener(new View.OnClickListener() {
                @Override public void onClick(View v) { showWeb(saved); }
            });
        }

        Button manual = new Button(this);
        manual.setText("configurar IP a mano (misma WiFi)");
        manual.setTextSize(11f);
        manual.setTextColor(Color.parseColor("#6f8aa8"));
        manual.setBackgroundColor(Color.TRANSPARENT);
        root.addView(manual);

        link.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showScanner(); }
        });
        manual.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showManual(); }
        });
        setContentView(root);
    }

    /* --------------------- escáner QR (jsQR en asset) --------------------- */
    @SuppressWarnings("SetJavaScriptEnabled")
    private void showScanner() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            // diálogo NATIVO de Android; seguimos en onRequestPermissionsResult
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 8);
            return;
        }
        WebView scan = new WebView(this);
        WebSettings s = scan.getSettings();
        s.setJavaScriptEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(true);
        scan.setBackgroundColor(Color.parseColor("#070e18"));
        // El asset es NUESTRO (file:///android_asset/scan.html), asi que aqui el
        // puente es legitimo siempre; lo unico que expone son linked/cancelScan.
        scan.addJavascriptInterface(new Bridge(), PUENTE);
        escaner = scan;
        scan.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override public void run() { request.grant(request.getResources()); }
                });
            }
        });
        setContentView(scan);
        scan.loadUrl("file:///android_asset/scan.html");
    }

    /* ----------------- IP manual (plan B, misma WiFi) ----------------- */
    private void showManual() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#070e18"));
        root.setGravity(Gravity.CENTER);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);
        TextView t = new TextView(this);
        t.setText("IP del PC (ipconfig → IPv4)\n");
        t.setTextColor(Color.parseColor("#22d3ee"));
        t.setGravity(Gravity.CENTER);
        root.addView(t);
        final EditText ip = new EditText(this);
        ip.setHint("192.168.1.50");
        ip.setTextColor(Color.parseColor("#22d3ee"));
        ip.setHintTextColor(Color.parseColor("#2a6b82"));
        ip.setBackgroundColor(Color.parseColor("#0a1524"));
        ip.setGravity(Gravity.CENTER);
        root.addView(ip);
        Button go = new Button(this);
        go.setText("CONECTAR");
        go.setTextColor(Color.parseColor("#070e18"));
        go.setBackgroundColor(Color.parseColor("#22d3ee"));
        root.addView(go);
        Button back = new Button(this);
        back.setText("volver");
        back.setTextColor(Color.parseColor("#6f8aa8"));
        back.setBackgroundColor(Color.TRANSPARENT);
        root.addView(back);
        go.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                String h = ip.getText().toString().trim();
                if (h.length() == 0) return;
                if (!h.contains(":")) h = h + ":8177";
                saveLink("http://" + h + "/m?host=" + h);
            }
        });
        back.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { showHome(); }
        });
        setContentView(root);
    }

    private void saveLink(String url) {
        candidatos = desdeQR(url);
        guardaHosts(candidatos);
        prefs.edit().putString("link_url", url).apply();
        candidatoActual = 0;
        showWeb(url);
    }

    /** Prueba la SIGUIENTE direccion de la lista. true si quedaba alguna. */
    private boolean siguienteCandidato() {
        if (candidatos == null || candidatoActual + 1 >= candidatos.size()) return false;
        candidatoActual++;
        final String siguiente = candidatos.get(candidatoActual);
        runOnUiThread(new Runnable() {
            @Override public void run() {
                Toast.makeText(MainActivity.this,
                        "Probando otra via de conexion con nexus...", Toast.LENGTH_SHORT).show();
                web = null;
                showWeb(siguiente);
            }
        });
        return true;
    }

    /* --------------------------- el nodo (WebView) --------------------------- */
    // ANTI-BLOQUEO: el túnel de cloudflared CAMBIA de URL en cada arranque del PC,
    // así que el enlace guardado puede estar MUERTO → antes la pantalla se quedaba
    // en blanco para siempre (el JS ni cargaba y no había forma de salir). Ahora:
    // si el HUD no carga en 15 s, o el host no existe, o el túnel devuelve error,
    // se vuelve SOLO a la pantalla de inicio para reescanear el QR.
    private boolean webLoaded = false;

    private void fallbackHome(final String msg) {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_LONG).show();
                web = null;
                showHome();
            }
        });
    }

    @SuppressWarnings("SetJavaScriptEnabled")
    private void showWeb(final String url) {
        try {
            baseHost = Uri.parse(url).getHost();
        } catch (Exception e) { baseHost = ""; }
        // SEC-08: en claro SOLO a la red de casa. Una direccion publica en http
        // no se abre ni aunque venga en un QR o en un enlace guardado.
        if (!urlPermitida(url)) {
            fallbackHome("Esa direccion no va cifrada y no es de tu red. nexus no la abre.");
            return;
        }
        escaner = null;
        webLoaded = false;
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        // SEC-08. ANTES: MIXED_CONTENT_ALWAYS_ALLOW, o sea que una pagina https
        // (el tunel) podia cargar y llamar a CUALQUIER cosa http. Ya no.
        // QUE CAMBIA ESTO, DICHO CLARO: en modo TUNEL (pagina https) la propia
        // pagina ya no puede saltar a las direcciones http de la LAN
        // (buscaPC() de mobile.html): eso era contenido mixto permitido a la
        // fuerza. El respaldo NATIVO (siguienteCandidato) sigue igual, porque
        // es una carga nueva de la pagina, no contenido mixto. En modo
        // LAN/Tailscale (pagina http) no cambia absolutamente nada.
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setBackgroundColor(Color.parseColor("#070e18"));
        // SEC-08 (3a): el puente SOLO se inyecta si la pagina que se va a cargar
        // es de un host que el operador emparejo. Ademas, cada metodo del puente
        // vuelve a comprobarlo por su cuenta (3b, ver puentePermitido()).
        aplicaPuente(web, url);
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageStarted(WebView v, String u, android.graphics.Bitmap icono) {
                // Se re-evalua en CADA navegacion: si la pagina se va a un host
                // que el operador no emparejo, ese documento se queda SIN puente.
                aplicaPuente(v, u);
            }

            @Override public WebResourceResponse shouldInterceptRequest(WebView v,
                                                                        WebResourceRequest req) {
                // Aqui se corta el claro fuera de casa tambien para lo que pide
                // la propia pagina (fetch/XHR, imagenes, scripts).
                String u = (req != null && req.getUrl() != null) ? req.getUrl().toString() : null;
                if (u != null && !urlPermitida(u)) return bloqueado();
                return null;    // el resto sigue su curso normal
            }

            @Override public boolean shouldOverrideUrlLoading(WebView v, String u) {
                if (u != null && !urlPermitida(u)) {     // en claro y fuera de casa
                    avisaNoPermitido();
                    return true;                        // no se carga
                }
                // Los ENLACES EXTERNOS que da la IA se abren en el NAVEGADOR del móvil
                try {
                    String h = Uri.parse(u).getHost();
                    if (h != null && baseHost != null && !h.equalsIgnoreCase(baseHost)) {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(u)));
                        return true;
                    }
                } catch (Exception e) { /* dentro del nodo */ }
                return false;
            }
            @Override public void onPageFinished(WebView v, String u) {
                // El unico sitio donde consta que hay conexion: el HUD ha cargado.
                // Solo la primera vez de este showWeb(); despues el HUD navega por
                // dentro y no hace falta anunciar nada en cada pantalla.
                if (!webLoaded) {
                    webLoaded = true;
                    Toast.makeText(MainActivity.this, "✔ Conectado con nexus",
                            Toast.LENGTH_SHORT).show();
                }
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest req,
                                                  WebResourceError err) {
                // solo la PÁGINA principal (no un favicon o un recurso suelto)
                if (req != null && req.isForMainFrame()) {
                    // Antes de rendirse: probar el resto de direcciones guardadas.
                    if (!siguienteCandidato()) {
                        fallbackHome("No llego a nexus por ninguna via. Comprueba que el PC "
                                + "esta encendido; si sigue sin ir, escanea el QR otra vez.");
                    }
                }
            }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest req,
                                                      WebResourceResponse resp) {
                // túnel caído: cloudflare responde con su página de error (530/502…)
                if (req != null && req.isForMainFrame() && resp != null
                        && resp.getStatusCode() >= 500) {
                    if (!siguienteCandidato()) {
                        fallbackHome("nexus no responde por ninguna via. Arrancalo en el PC "
                                + "y, si sigue igual, escanea el QR otra vez.");
                    }
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    @Override public void run() { request.grant(request.getResources()); }
                });
            }
        });
        setContentView(web);
        web.loadUrl(url);
        // WATCHDOG: si en 15 s el HUD no ha cargado, NUNCA te quedas atrapado
        web.postDelayed(new Runnable() {
            @Override public void run() {
                if (!webLoaded && web != null) {
                    fallbackHome("nexus no responde. ¿PC encendido? Escanea el QR otra vez.");
                }
            }
        }, 15000);
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) { web.goBack(); return; }
        super.onBackPressed();
    }

    /* --------- puente JS <-> nativo (QR, voz y utilidades) ---------
       SEC-08: ANTES este objeto se inyectaba en el WebView del nodo remoto sin
       mirar QUE pagina se estaba pintando, asi que cualquier documento que
       acabara ahi (una XSS de la propia pagina, o un MITM de la WiFi que
       inyecte un script en el HTML en claro) podia llamar a dial y whatsapp con
       los argumentos que le diera la gana.

       QUE SE HIZO, Y POR QUE ASI (3a Y 3b A LA VEZ).
       - 3a (acotar la inyeccion): `aplicaPuente()` pone o quita la interfaz
         segun el host, y se vuelve a evaluar en CADA navegacion. El mecanismo
         disponible aqui es `removeJavascriptInterface` (API 11+; el proyecto
         esta en minSdk 23), que RETIRA el objeto pero, segun la documentacion
         de Android, no cambia el documento ya cargado: surte efecto en el
         SIGUIENTE documento. Ademas `addJavascriptInterface` inyecta el objeto
         en TODOS los frames del WebView (tambien en un <iframe> ajeno), cosa
         que no se puede acotar por host desde este API.
       - 3b (comprobar en el propio puente): por eso lo que de verdad ENFORCA es
         esto otro. Cada metodo empieza con `if (!puentePermitido())` y
         `puentePermitido()` compara la URL del documento que hay cargado ahora
         mismo contra los hosts que el operador emparejo en SharedPreferences.
         `web.getUrl()` devuelve la URL YA COMETIDA (la del documento actual), no
         la que esta en vuelo, que es justo lo que se necesita para no dejarse
         enganar por una redireccion.

       LO QUE ESTA COMPROBACION *NO* PUEDE HACER, y hay que decirlo: una pagina
       SERVIDA POR EL HOST EMPAREJADO sigue teniendo el puente, aunque sea un
       MITM en claro que se hace pasar por nexus. Contra eso no hay lista de
       hosts que valga: lo que hay es el dialogo nativo de dial/whatsapp (el
       operador ve el numero y el mensaje) y el hecho de que ya no se pueden
       inyectar scripts desde un tercero sin pasar por ese host. */
    private class Bridge {

        @JavascriptInterface
        public void linked(String qrData) {
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            // El QR trae la URL completa del nodo: https://tunel/m?host=...&token=...
            final String data = qrData == null ? "" : qrData.trim();
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    if (data.startsWith("http://") || data.startsWith("https://")) {
                        // OJO: aqui NO se dice «vinculado». Lo unico que sabemos es que
                        // el texto del QR parece una URL. Antes se cantaba victoria aqui
                        // mismo (31/07/2026) y el usuario leia «✔ Vinculado con nexus»
                        // justo antes de que la carga fallara y le devolviera al inicio.
                        // El «conectado» lo dice onPageFinished, cuando el HUD ha cargado
                        // DE VERDAD. Un QR bien escrito no es una conexion.
                        Toast.makeText(MainActivity.this, "QR leido. Conectando con nexus...",
                                Toast.LENGTH_SHORT).show();
                        saveLink(data);
                    } else {
                        Toast.makeText(MainActivity.this, "Ese QR no es de nexus", Toast.LENGTH_LONG).show();
                        showHome();
                    }
                }
            });
        }

        @JavascriptInterface
        public void cancelScan() {
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            runOnUiThread(new Runnable() { @Override public void run() { showHome(); } });
        }

        @JavascriptInterface
        public void startVoice() {
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            runOnUiThread(new Runnable() { @Override public void run() { startNativeVoice(); } });
        }

        @JavascriptInterface
        public void dial(final String who) {   // LLAMADAS: numero directo o nombre de contacto
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            runOnUiThread(new Runnable() { @Override public void run() { doDial(who); } });
        }

        @JavascriptInterface
        public void whatsapp(final String number, final String text) {   // WHATSAPP directo
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            runOnUiThread(new Runnable() { @Override public void run() { doWhatsApp(number, text); } });
        }

        /** La pagina, ya cargada, le pasa a la app la lista de direcciones que el
         *  PC dice tener AHORA. Es lo que hace que la vinculacion no caduque:
         *  si el tunel cambio, la app se entera la proxima vez que se conecta —
         *  sin volver a escanear nada. Las direcciones llegan separadas por «|». */
        @JavascriptInterface
        public void saveHosts(String lista) {
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            if (lista == null || lista.trim().length() == 0) return;
            java.util.List<String> nueva = new ArrayList<String>();
            String actual = (candidatos != null && candidatoActual < candidatos.size())
                    ? candidatos.get(candidatoActual) : "";
            if (actual.length() > 0) nueva.add(actual);      // la que funciona, primera
            for (String u : lista.split("\\|")) {
                String v = u.trim();
                if (v.length() > 0 && !nueva.contains(v)) nueva.add(v);
            }
            for (String u : hostsGuardados()) if (!nueva.contains(u)) nueva.add(u);
            guardaHosts(nueva);
            candidatos = nueva;
            candidatoActual = 0;
        }

        @JavascriptInterface
        public void resetHost() {   // mantener pulsado ◉ en el nodo → re-vincular
            if (!puentePermitido()) { fueraDeConfianza(); return; }
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    prefs.edit().remove("link_url").remove("link_urls").apply();
                    candidatos = new ArrayList<String>();
                    candidatoActual = 0;
                    showHome();
                }
            });
        }
    }

    private void js(String code) {
        if (web != null) web.evaluateJavascript(code, null);
    }

    /* ---------------- SEC-08: de quien se fia la app (las dos puertas) ---------------- */

    /** Texto convertido en literal de cadena JavaScript, sin escapar a mano.
     *
     *  POR QUE (SEC-08). Antes se hacia `text.replace("\\","").replace("'","\\'")`,
     *  que pierde las barras que SI son del texto y deja fuera comillas dobles,
     *  saltos de linea y todo lo demas: lo que dictara el reconocedor de voz
     *  entraba crudo en una llamada a JavaScript. Ahora se codifica como JSON
     *  (`org.json.JSONObject.quote`, que ya viene en el SDK) y encima se cierran
     *  los caracteres menor-que y mayor-que como su escape unicode (u003C /
     *  u003E): el JSON no los escapa y un `</script>` dentro del texto cerraria
     *  la etiqueta si algun dia esto acaba dentro de un <script> en un HTML.
     *
     *  LO QUE ESTO *NO* PROTEJE: si el codigo que llama metiera el literal fuera
     *  de un contexto de cadena (concatenandolo a un identificador, por
     *  ejemplo), ninguna codificacion de cadena lo salvara. Aqui solo se usa
     *  como ARGUMENTO de una funcion, que es su unico uso. */
    private static String jsLiteral(String texto) {
        String citado;
        try {
            citado = JSONObject.quote(texto == null ? "" : texto);
        } catch (Throwable e) {
            return "\"\"";     // nunca dejamos el literal a medias
        }
        return citado.replace("<", "\\u003C").replace(">", "\\u003E");
    }

    /** El WebView que el operador esta viendo: el escaner (asset) o el nodo. */
    private WebView vistaActual() {
        return escaner != null ? escaner : web;
    }

    /** ¿Puede esta pagina usar el puente? Nuestro asset siempre; una pagina
     *  remota solo si su host es uno de los que el operador emparejo. */
    private boolean puentePermitido() {
        WebView v = vistaActual();
        String url = v == null ? "" : String.valueOf(v.getUrl());
        return url.startsWith("file:///android_asset/") || esHostEmparejado(url);
    }

    /** Se le dice al operador, en vez de fallar en silencio. */
    private void fueraDeConfianza() {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                Toast.makeText(MainActivity.this,
                        "Por seguridad, esta pagina no puede usar la voz, las llamadas "
                        + "ni WhatsApp del movil: no es tu nexus.", Toast.LENGTH_LONG).show();
            }
        });
    }

    /** ¿El host de esta URL es el de alguna direccion emparejada? Las direcciones
     *  emparejadas son las que guardo el QR (link_url / link_urls), nunca una
     *  lista fija en el codigo. */
    private boolean esHostEmparejado(String url) {
        String host;
        try {
            host = Uri.parse(url == null ? "" : url).getHost();
        } catch (Exception e) {
            return false;
        }
        if (host == null || host.length() == 0) return false;
        for (String guardada : hostsGuardados()) {
            try {
                String h = Uri.parse(guardada).getHost();
                if (h != null && h.equalsIgnoreCase(host)) return true;
            } catch (Exception e) { /* entrada rara del QR: se salta */ }
        }
        return false;
    }

    /** Pone el puente si el documento es del host emparejado; lo quita si no.
     *  Se llama en cada navegacion (ver onPageStarted en showWeb). */
    private void aplicaPuente(WebView v, String url) {
        if (v == null) return;
        if (esHostEmparejado(url)) {
            v.addJavascriptInterface(new Bridge(), PUENTE);
        } else {
            v.removeJavascriptInterface(PUENTE);
        }
    }

    /** Respuesta vacia: el WebView no recibe NADA de ese host. */
    private static WebResourceResponse bloqueado() {
        try {
            return new WebResourceResponse("text/plain", "utf-8",
                    new java.io.ByteArrayInputStream(new byte[0]));
        } catch (Exception e) {
            return null;
        }
    }

    private void avisaNoPermitido() {
        Toast.makeText(this, "Esa direccion no va cifrada y no es de tu red. nexus no la abre.",
                Toast.LENGTH_LONG).show();
    }

    /** SEC-08: politica de transporte. https pasa siempre; en claro, SOLO a la
     *  red de casa. Esto es lo que sustituye de verdad al
     *  `usesCleartextTraffic="true"`, porque el network_security_config no
     *  admite rangos y el QR ofrece IPs que solo se conocen al emparejar. */
    private boolean urlPermitida(String url) {
        String esquema;
        String host;
        try {
            Uri u = Uri.parse(url == null ? "" : url);
            esquema = u.getScheme() == null ? "" : u.getScheme().toLowerCase();
            host = u.getHost();
        } catch (Exception e) {
            return false;
        }
        if (host == null || host.length() == 0) {
            // file:, data:, blob:, about:: no salen a la red
            return "file".equals(esquema) || "data".equals(esquema)
                    || "blob".equals(esquema) || "about".equals(esquema);
        }
        // https y wss van cifrados: no hay nada que decidir. (ws:// SÍ se
        // mira: un WebSocket en claro es el mismo agujero que un fetch en claro.)
        if (!"http".equals(esquema) && !"ws".equals(esquema)) return true;
        return esHostLocal(host);
    }

    /** ¿Este host es de la red del operador? Los cinco rangos privados que usa
     *  nexus (loopback, 10/8, 172.16/12, 192.168/16 y el 100.64/10 de Tailscale,
     *  que el QR tambien ofrece en http) y los nombres .local del mDNS. */
    private static boolean esHostLocal(String host) {
        if (host == null) return false;
        String h = host.toLowerCase();
        if ("localhost".equals(h) || h.endsWith(".local")) return true;
        int[] ip = ipDe(h);
        if (ip == null) return false;                // nombre publico en claro: NO
        return ip[0] == 127
                || ip[0] == 10
                || (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31)
                || (ip[0] == 192 && ip[1] == 168)
                || (ip[0] == 100 && ip[1] >= 64 && ip[1] <= 127);   // Tailscale
    }

    /** "1.2.3.4" → {1,2,3,4}; null si no es una IPv4 literal. */
    private static int[] ipDe(String host) {
        String[] trozos = host.split("\\.");
        if (trozos.length != 4) return null;
        int[] fuera = new int[4];
        for (int i = 0; i < 4; i++) {
            String t = trozos[i];
            if (t.length() == 0 || t.length() > 3) return null;
            for (int j = 0; j < t.length(); j++) {
                if (!Character.isDigit(t.charAt(j))) return null;
            }
            fuera[i] = Integer.parseInt(t);
            if (fuera[i] > 255) return null;
        }
        return fuera;
    }

    /** Confirmacion NATIVA (SEC-08). Las dos acciones que salen del telefono
     *  hacia el mundo real no se disparan porque una pagina lo pida: el
     *  operador ve el numero y el mensaje EXACTOS y decide. Es el mismo trato
     *  que nexus da en el PC para los envios (commit c6e41c1): el movil no
     *  puede ser el camino flojo. startVoice/saveHosts/resetHost NO pasan por
     *  aqui a proposito: no sacan nada del telefono. */
    private void confirmaNativo(String titulo, String mensaje, final Runnable si) {
        try {
            new AlertDialog.Builder(this)
                    .setTitle(titulo)
                    .setMessage(mensaje)
                    .setPositiveButton("OK", new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int w) { si.run(); }
                    })
                    .setNegativeButton("Cancelar", new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface d, int w) { d.cancel(); }
                    })
                    .show();
        } catch (Exception e) {
            Toast.makeText(this, "No he podido pedir confirmacion: " + e.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    /* -------- LLAMADAS (estilo Android Auto): numero directo o contacto -------- */
    // SEC-08: antes de marcar, el operador ve el numero EXACTO en un dialogo
    // nativo. Una pagina (o un script inyectado) ya no puede colocar llamadas.
    private void doDial(String who) {
        try {
            String num = who == null ? "" : who.replaceAll("[^0-9+]", "");
            if (num.replaceAll("[^0-9]", "").length() < 7) {
                num = contactNumber(who);
                if (num == null) {
                    Toast.makeText(this, "No encuentro a \u00ab" + who + "\u00bb en tus contactos",
                            Toast.LENGTH_LONG).show();
                    return;
                }
            }
            final String numero = num;
            String quien = (who == null ? "" : who.trim());
            confirmaNativo("Llamar por el movil",
                    "La pagina de nexus pide LLAMAR a:\n\n"
                    + (quien.length() > 0 && !quien.equals(numero) ? quien + "\n" : "")
                    + numero + "\n\nSe marcara desde ESTE movil.",
                    new Runnable() { @Override public void run() { llamaDeVerdad(numero); } });
        } catch (Exception e) {
            Toast.makeText(this, "No he podido llamar: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    /** El Intent de verdad. Solo se llega aqui desde el OK del dialogo. */
    private void llamaDeVerdad(String num) {
        try {
            boolean canCall = checkSelfPermission(Manifest.permission.CALL_PHONE)
                    == PackageManager.PERMISSION_GRANTED;
            Intent call = new Intent(canCall ? Intent.ACTION_CALL : Intent.ACTION_DIAL,
                    Uri.parse("tel:" + Uri.encode(num)));
            call.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(call);
        } catch (Exception e) {
            Toast.makeText(this, "No he podido llamar: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    /* -------- WHATSAPP (v2.6): abre el chat con el texto ya escrito -------- */
    // Antes esto se hacia con un enlace wa.me clicado en el WebView, que a veces
    // sacaba un selector de navegador. Ahora, si nexus resolvio el numero con su
    // agenda, abrimos WhatsApp DIRECTO (com.whatsapp / Business); si no esta
    // instalado o no hay numero, caemos a wa.me / compartir para que elijas.
    private void doWhatsApp(String number, String text) {
        try {
            final String digits = number == null ? "" : number.replaceAll("[^0-9]", "");
            final String msg = text == null ? "" : text;
            String destino = digits.length() >= 7
                    ? "numero +" + digits
                    : "elegir el chat a mano (nexus no dio numero)";
            // SEC-08: igual que la llamada. Se ensenan el destino y el mensaje
            // TAL CUAL (el mensaje puede haberlo redactado el modelo: el
            // operador tiene que poder leerlo antes de que salga).
            confirmaNativo("Enviar por WhatsApp",
                    "La pagina de nexus pide abrir WhatsApp con:\n\nPara: " + destino
                    + "\n\nMensaje:\n" + (msg.length() > 0 ? msg : "(sin texto)")
                    + "\n\nRevisalo y dale a enviar tu mismo.",
                    new Runnable() {
                        @Override public void run() { abreWhatsApp(digits, msg); }
                    });
        } catch (Exception e) {
            Toast.makeText(this, "No he podido abrir WhatsApp: " + e.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    /** Los Intent de WhatsApp. Solo se llega aqui desde el OK del dialogo. */
    private void abreWhatsApp(String digits, String msg) {
        try {
            if (digits.length() >= 7) {
                String url = "https://api.whatsapp.com/send?phone=" + digits
                        + (msg.length() > 0 ? "&text=" + Uri.encode(msg) : "");
                Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                i.setPackage("com.whatsapp");
                try {
                    startActivity(i);
                    return;
                } catch (Exception noWa) {
                    try {   // WhatsApp Business
                        i.setPackage("com.whatsapp.w4b");
                        startActivity(i);
                        return;
                    } catch (Exception noBiz) {
                        // ninguno instalado con ese package → wa.me sin forzar app
                        String wa = "https://wa.me/" + digits
                                + (msg.length() > 0 ? "?text=" + Uri.encode(msg) : "");
                        Intent v = new Intent(Intent.ACTION_VIEW, Uri.parse(wa));
                        v.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(v);
                        return;
                    }
                }
            }
            // sin numero: compartir el texto y que elijas el chat en WhatsApp
            Intent s = new Intent(Intent.ACTION_SEND);
            s.setType("text/plain");
            s.putExtra(Intent.EXTRA_TEXT, msg);
            s.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                s.setPackage("com.whatsapp");
                startActivity(s);
            } catch (Exception noWa) {
                s.setPackage(null);
                startActivity(Intent.createChooser(s, "Enviar por…")
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            }
        } catch (Exception e) {
            Toast.makeText(this, "No he podido abrir WhatsApp: " + e.getMessage(),
                    Toast.LENGTH_LONG).show();
        }
    }

    private String contactNumber(String name) {
        if (checkSelfPermission(Manifest.permission.READ_CONTACTS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.READ_CONTACTS,
                    Manifest.permission.CALL_PHONE}, 9);
            return null;
        }
        android.database.Cursor c = null;
        try {
            c = getContentResolver().query(
                    android.provider.ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                    new String[]{android.provider.ContactsContract.CommonDataKinds.Phone.NUMBER},
                    android.provider.ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " LIKE ?",
                    new String[]{"%" + (name == null ? "" : name.trim()) + "%"}, null);
            if (c != null && c.moveToFirst()) return c.getString(0);
        } catch (Exception e) { /* sin permiso o sin contacto */ }
        finally { if (c != null) c.close(); }
        return null;
    }

    private void startNativeVoice() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 7);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            js("wabiksVoiceEnd && wabiksVoiceEnd('sin-reconocimiento')");
            Toast.makeText(this, "Este móvil no tiene reconocimiento de voz de Google", Toast.LENGTH_LONG).show();
            return;
        }
        if (recognizer != null) { recognizer.destroy(); recognizer = null; }
        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) { js("wabiksVoiceStart && wabiksVoiceStart()"); }
            @Override public void onBeginningOfSpeech() { }
            @Override public void onRmsChanged(float rmsdB) { }
            @Override public void onBufferReceived(byte[] buffer) { }
            @Override public void onEndOfSpeech() { }
            @Override public void onError(int error) { js("wabiksVoiceEnd && wabiksVoiceEnd('err" + error + "')"); }
            @Override public void onResults(Bundle results) {
                ArrayList<String> m = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                String text = (m != null && !m.isEmpty()) ? m.get(0) : "";
                // SEC-08: el texto dictado viaja como literal JSON, no con el
                // escape a mano de antes (que se comia las barras del texto y
                // dejaba pasar comillas dobles, saltos de linea y </script>).
                js("wabiksVoiceResult && wabiksVoiceResult(" + jsLiteral(text) + ")");
                js("wabiksVoiceEnd && wabiksVoiceEnd('')");
            }
            @Override public void onPartialResults(Bundle partialResults) { }
            @Override public void onEvent(int eventType, Bundle params) { }
        });
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-ES");
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
        recognizer.startListening(i);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        if (code == 8) {   // cámara pedida desde el escáner
            boolean ok = res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED;
            if (ok) { showScanner(); return; }   // concedida → ahora sí, cámara
            Toast.makeText(this, "Sin permiso de cámara no puedo leer el QR.", Toast.LENGTH_LONG).show();
            if (!shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) {
                // denegado con «no volver a preguntar» → Ajustes de la app (patrón estándar)
                try {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:" + getPackageName())));
                } catch (Exception e) { /* sin ajustes disponibles */ }
            }
            showHome();
        }
    }

    @Override protected void onDestroy() {
        if (recognizer != null) recognizer.destroy();
        super.onDestroy();
    }
}
