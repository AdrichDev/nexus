package com.nexus.app;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
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
        scan.addJavascriptInterface(new Bridge(), "WabiksNative");
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
        webLoaded = false;
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        web.setBackgroundColor(Color.parseColor("#070e18"));
        web.addJavascriptInterface(new Bridge(), "WabiksNative");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView v, String u) {
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

    /* --------- puente JS <-> nativo (QR, voz y utilidades) --------- */
    private class Bridge {

        @JavascriptInterface
        public void linked(String qrData) {
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
            runOnUiThread(new Runnable() { @Override public void run() { showHome(); } });
        }

        @JavascriptInterface
        public void startVoice() {
            runOnUiThread(new Runnable() { @Override public void run() { startNativeVoice(); } });
        }

        @JavascriptInterface
        public void dial(final String who) {   // LLAMADAS: numero directo o nombre de contacto
            runOnUiThread(new Runnable() { @Override public void run() { doDial(who); } });
        }

        @JavascriptInterface
        public void whatsapp(final String number, final String text) {   // WHATSAPP directo
            runOnUiThread(new Runnable() { @Override public void run() { doWhatsApp(number, text); } });
        }

        /** La pagina, ya cargada, le pasa a la app la lista de direcciones que el
         *  PC dice tener AHORA. Es lo que hace que la vinculacion no caduque:
         *  si el tunel cambio, la app se entera la proxima vez que se conecta —
         *  sin volver a escanear nada. Las direcciones llegan separadas por «|». */
        @JavascriptInterface
        public void saveHosts(String lista) {
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

    /* -------- LLAMADAS (estilo Android Auto): numero directo o contacto -------- */
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
            String digits = number == null ? "" : number.replaceAll("[^0-9]", "");
            String msg = text == null ? "" : text;
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
                text = text.replace("\\", "").replace("'", "\\'");
                js("wabiksVoiceResult && wabiksVoiceResult('" + text + "')");
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
