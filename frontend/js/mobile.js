/* EL CÓDIGO DEL MÓVIL, EN SU PROPIO FICHERO (T18b, SEC-10).

   Estaba en un bloque `<script>` en línea al final de `frontend/mobile.html`, y
   eso obligaba a que la CSP dijera `script-src 'self' 'unsafe-inline'`: un
   `<script>` inyectado por un `innerHTML` sin escapar se ejecutaba. El bloque se
   movió AQUÍ TAL CUAL, línea por línea, sin tocar una sola sentencia.

   Sigue siendo un script CLÁSICO (no un módulo) y `mobile.html` lo carga
   DESPUÉS de `reactor.js`, que es el que dibuja el canvas: el orden de arranque
   es el de siempre. Se registra el service worker, se canjea el código del QR
   por el token propio del móvil y se conecta el WebSocket.

   La segunda copia a mano de `esc()` que vive en este fichero (`escH`) es
   deliberada y está verificada: `tests/unit/frontend/test_escapes_y_cabeceras.py`
   la extrae, la EJECUTA y la compara vector a vector con `esc()` de
   `frontend/js/core/dom.js`.
*/

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});
// ASÍNCRONA a propósito: antes de conectar hay que canjear el código del QR por
// el token propio de este móvil (P3-2) y eso es una petición. Todo lo demás se
// ejecuta igual, en orden.
(async function () {
  const $ = (id) => document.getElementById(id);
  // El móvil se conecta al backend del PC. Por defecto, el mismo host que sirvió
  // la página; se puede fijar ?host=192.168.1.50:8177 para apuntar al PC en la LAN.
  const params = new URLSearchParams(location.search);
  const HOST = params.get('host') || location.host;
  /* ── EL TOKEN ES TUYO, NO DE TODOS (roadmap P3-2) ────────────────────────
     El QR ya NO trae el token compartido de siempre: trae un CÓDIGO de un solo
     uso y de vida corta (8 caracteres, `vinculacion.ttl_codigo_segundos` de
     config/umbrales.json). Esta página lo canjea UNA vez en
     `POST /api/link/pair` y recibe un token PROPIO de este teléfono, que a
     partir de ahí se usa exactamente donde antes se usaba el del QR: `?token=`,
     la cabecera `x-nexus-token`, la cookie `nexus_token` y el WebSocket.
     En `localStorage` se guarda el token PROPIO, nunca el código: un código ya
     gastado en el almacén dejaría el móvil fuera en cuanto recargara.
     Los móviles que ya estaban vinculados siguen con su token de siempre: nexus
     lo acepta como «dispositivo antiguo» hasta que el dueño lo revoque. ── */
  const CODIGO_RX = /^[A-HJ-NP-Z2-9]{8}$/;
  const TOKEN_QR = params.get('token') || '';
  let TOKEN = CODIGO_RX.test(TOKEN_QR)
    ? '' : (TOKEN_QR || localStorage.getItem('nexus_token') || '');
  if (TOKEN) localStorage.setItem('nexus_token', TOKEN);   // el de siempre, como siempre

  /* ── LA VINCULACIÓN NO CADUCA ────────────────────────────────────────────
     El problema que arregla esto: el móvil guardaba UNA dirección. Si esa era
     la del túnel —que es aleatoria y distinta en cada arranque de nexus—, al
     apagar y encender el PC la dirección guardada ya no existía y había que
     volver a escanear el QR. El token nunca fue el problema; la dirección sí.
     Ahora se guarda una LISTA de direcciones (el nombre del equipo, que no
     cambia nunca; la IP de la WiFi; el túnel del momento) y se refresca sola
     cada vez que se conecta. Así, mientras UNA de ellas conteste, el móvil
     sigue vinculado — sin volver a escanear nada. ───────────────────────── */
  const HOSTS_KEY = 'nexus_hosts';
  function hostsGuardados() {
    try { return JSON.parse(localStorage.getItem(HOSTS_KEY) || '[]'); } catch (_) { return []; }
  }
  function guardaHosts(lista) {
    const limpia = [...new Set(lista.filter(Boolean))].slice(0, 8);
    if (limpia.length) localStorage.setItem(HOSTS_KEY, JSON.stringify(limpia));
  }
  // Al abrir: lo que venga en el QR (host + alt) manda; se suma a lo ya guardado.
  (function () {
    const nuevos = [];
    if (params.get('host')) nuevos.push(`${location.protocol}//${params.get('host')}`);
    (params.get('alt') || '').split(',').forEach((u) => { if (u.trim()) nuevos.push(u.trim()); });
    nuevos.push(`${location.protocol}//${location.host}`);
    guardaHosts([...nuevos, ...hostsGuardados()]);
  })();
  // Y cada vez que conecta, le pide al PC su lista actual: si el túnel cambió,
  // el móvil se entera solo la próxima vez que estén en la misma red.
  async function refrescaHosts(base) {
    try {
      const r = await fetch(`${base}/api/link/status?token=${encodeURIComponent(TOKEN)}`);
      const st = await r.json();
      if (st && Array.isArray(st.hosts)) {
        const bases = st.hosts.map((h) => `${h.esquema}://${h.host}`);
        guardaHosts([...bases, base, ...hostsGuardados()]);
        // Y se la pasamos a la APP: es lo que hace que la vinculación no
        // caduque. La app guarda UNA dirección para arrancar el WebView; si esa
        // muere (el túnel cambia en cada arranque del PC), sin esto habría que
        // reescanear el QR. Con esto, la app se entera del cambio sola.
        try {
          if (window.WabiksNative && window.WabiksNative.saveHosts) {
            const conToken = [...new Set([...bases, ...hostsGuardados()])]
              .map((b) => `${b.replace(/\/+$/, '')}/m?token=${encodeURIComponent(TOKEN)}`);
            window.WabiksNative.saveHosts(conToken.join('|'));
          }
        } catch (_) { /* en el navegador normal no existe el puente */ }
      }
    } catch (_) { /* silencioso */ }
  }
  // Busca cuál de las direcciones conocidas responde AHORA.
  async function buscaPC() {
    const candidatos = [`${location.protocol}//${HOST}`, ...hostsGuardados()];
    for (const base of [...new Set(candidatos)]) {
      try {
        const ctl = new AbortController();
        const t = setTimeout(() => ctl.abort(), 2500);
        const r = await fetch(`${base}/api/jobs?token=${encodeURIComponent(TOKEN)}`,
                              { signal: ctl.signal });
        clearTimeout(t);
        if (r.ok) { guardaHosts([base, ...hostsGuardados()]); return base; }
      } catch (_) { /* la siguiente */ }
    }
    return '';
  }
  window.__nexusBuscaPC = buscaPC;          // lo usa la pantalla de reconexión
  window.__nexusRefrescaHosts = refrescaHosts;

  const HTTP = `${location.protocol}//${HOST}`;
  const WSP = location.protocol === 'https:' ? 'wss' : 'ws';
  let TQ = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';

  // IDENTIDAD del móvil: id persistente + nombre legible (para que el PC muestre
  // «qué dispositivo se ha vinculado»). Se puede renombrar guardando nexus_dev_name.
  const DEV_ID = localStorage.getItem('nexus_dev_id')
    || (Date.now().toString(36) + Math.random().toString(36).slice(2, 7));
  localStorage.setItem('nexus_dev_id', DEV_ID);
  function deviceName() {
    if (localStorage.getItem('nexus_dev_name')) return localStorage.getItem('nexus_dev_name');
    const ua = navigator.userAgent;
    const os = /Android/i.test(ua) ? 'Android'
      : /iPhone|iPad|iPod/i.test(ua) ? 'iPhone/iPad'
      : /Windows/i.test(ua) ? 'PC' : 'Móvil';
    const m = ua.match(/\((?:Linux; )?([^;)]+)/);
    const model = m && /Android/i.test(ua) && m[1] && !/Linux/i.test(m[1]) ? ' · ' + m[1].trim() : '';
    return (os + model).slice(0, 38);
  }

  /* Canjear el código del QR por el token PROPIO. Se llama UNA vez al arrancar,
     antes de conectar. Si el canje no sale (código caducado, ya usado, PC a
     medias) se sigue con el token guardado, si lo hay: no se borra nada por un
     fallo de red. El código NO se guarda nunca. */
  async function canjeaCodigo() {
    if (!CODIGO_RX.test(TOKEN_QR)) return false;
    const base = `${location.protocol}//${location.host}`;
    try {
      const r = await fetch(`${base}/api/link/pair`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ codigo: TOKEN_QR, id: DEV_ID, name: deviceName() }) });
      if (r.ok) {
        const d = await r.json();
        if (d && d.token) {
          TOKEN = d.token;
          TQ = `?token=${encodeURIComponent(TOKEN)}`;
          try { localStorage.setItem('nexus_token', TOKEN); } catch (_) { /* webview sin storage */ }
          return true;
        }
      }
    } catch (_) { /* sin red: se sigue con lo que hubiera guardado */ }
    TOKEN = localStorage.getItem('nexus_token') || '';
    TQ = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : '';
    return false;
  }

  (function buildOrb() {
    const el = $('orb-load'); if (!el) return;
    const N = 12, R = 22;
    let h = '';
    for (let i = 0; i < N; i++) {
      const a = (i / N) * 2 * Math.PI;
      h += `<i style="--tx:${(Math.cos(a)*R).toFixed(1)}px;--ty:${(Math.sin(a)*R).toFixed(1)}px;`
         + `animation-delay:${(-(i/N)*1.1).toFixed(2)}s"></i>`;
    }
    el.innerHTML = h;
  })();
  function setState(s) {
    window.setReactorState && window.setReactorState(s);
    const n = { idle:'STANDBY', listening:'ESCUCHANDO', thinking:'PROCESANDO', speaking:'HABLANDO' };
    $('state').textContent = n[s] || 'STANDBY';
    const orb = $('orb-load'); if (orb) orb.classList.toggle('show', s === 'thinking');
  }

  let ws, paired = false;
  function connect() {
    try { ws = new WebSocket(`${WSP}://${HOST}/ws${TQ}`); } catch (_) { return; }
    ws.onopen = () => {
      $('conn').textContent = 'EN LÍNEA';
      // Presentarse: el PC registra el dispositivo, cierra el QR y lo muestra.
      try { ws.send(JSON.stringify({ type: 'hello', role: 'mobile',
        id: DEV_ID, name: deviceName(), ua: navigator.userAgent })); } catch (_) {}
    };
    ws.onclose = () => { $('conn').textContent = 'sin conexión — ¿PC encendido?'; setTimeout(connect, 2500); };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
      const { type, data } = m;
      if (type === 'paired_ack') {
        paired = true;
        $('conn').textContent = '✔ VINCULADO' + (data && data.pc ? ' ● ' + data.pc : '');
        $('hint').textContent = 'Listo. Habla o escribe para dar órdenes a nexus.';
        return;
      }
      if (type === 'state') setState(data);
      if (type === 'chat') { showReply(data.reply, data.channel || 'pc'); setState('idle'); }
      if (type === 'call' && data) {        // 📞 «llama a X» → marca ESTE móvil
        const n = data.number || '';
        if (window.WabiksNative) {
          if (window.WabiksNative.dial) window.WabiksNative.dial(n || data.name || '');
          else if (n) { location.href = 'tel:' + n; }
          else addMsg('wb', '📞 Para llamar por nombre desde aquí, reinstala el APK actualizado de nexus.');
        } else if (n) { location.href = 'tel:' + n; }
        else { addMsg('wb', '📞 Abre la app de nexus (APK) para llamar por nombre de contacto.'); }
      }
      if (type === 'whatsapp' && data) {    // 📲 «whatsapp a X» → se abre WhatsApp AQUÍ
        // Puente NATIVO (APK v2.6+): abre WhatsApp DIRECTO (com.whatsapp) con el
        // chat y el texto listos, sin selector de navegador. Si el APK es viejo
        // (sin el puente), caemos al enlace wa.me como hasta ahora.
        if (window.WabiksNative && window.WabiksNative.whatsapp && (data.number || data.text)) {
          window.WabiksNative.whatsapp(String(data.number || ''), String(data.text || ''));
          addMsg('wb', '📲 Abriendo WhatsApp' + (data.to ? ' con el chat de ' + escH(data.to) : '') +
                       ' — revisa el mensaje y dale a enviar.');
          return;
        }
        let u = data.url || '';
        if (!u && data.number) {
          u = 'https://wa.me/' + String(data.number).replace(/[^\d]/g, '') +
              (data.text ? '?text=' + encodeURIComponent(data.text) : '');
        }
        if (u) {
          // clic programático en un enlace: el APK lo abre vía Intent (como
          // cualquier enlace externo) sin sacar al nodo de su pantalla.
          const a = document.createElement('a');
          a.href = u; a.target = '_blank'; a.rel = 'noopener';
          document.body.appendChild(a); a.click(); a.remove();
          addMsg('wb', '📲 Abriendo WhatsApp' + (data.to ? ' con el chat de ' + escH(data.to) : '') +
                       ' — revisa el mensaje y dale a enviar. <a href="' + escH(u) +
                       '" target="_blank" rel="noopener">Reabrir</a>');
        } else {
          const txt = data.text ? ('<br>Texto: «' + escH(data.text) + '»') : '';
          addMsg('wb', '📲 No tengo el número de ' + escH(data.to || 'ese contacto') +
                       '. Dile a nexus: «apunta el teléfono de ' + escH(data.to || 'X') +
                       ' 612 345 678» y la próxima abro su chat directo.' + txt);
        }
      }
    };
  }
  await canjeaCodigo();      // el código del QR → token propio de ESTE móvil
  connect();

  // ---- respuesta: texto seleccionable + enlaces clicables + VOZ ----
  // Copia a mano de esc()/linkify() de frontend/js/core/dom.js: esta página no
  // carga módulos, así que no puede importarla. SEC-10 (roadmap P2-11): tiene
  // que escapar `"` y `'` IGUAL que el original, porque aquí también se pinta
  // dentro de atributos (el `href` del enlace «Reabrir»), y su linkify corta la
  // URL en la entidad (`&#34;`) para que una comilla no se cuele en el href.
  const escH = (x) => String(x == null ? '' : x)
    .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                                   '"': '&#34;', "'": '&#39;' }[c]));
  const linkify = (x) => escH(x).replace(/(https?:\/\/(?:&amp;|[^\s<>"'«»)&])+)/g,
    (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
  let muteAI = localStorage.getItem('nexus_m_ai') === '1';
  let muteMe = false;
  let _pend = null;                        // burbuja «…» mientras piensa
  function addMsg(who, html) {
    const r = $('reply');
    const d = document.createElement('div');
    d.className = 'msg ' + who;
    d.innerHTML = html;
    r.appendChild(d);
    while (r.children.length > 40) r.removeChild(r.firstChild);
    r.scrollTop = r.scrollHeight;
    return d;
  }
  // quita emojis/símbolos decorativos: en el chat se ven, pero NUNCA se leen en voz
  function _noEmoji(x) {
    return String(x == null ? '' : x)
      .replace(/[←-➿⬀-⯿︀-️‍⃣∞Ⓜ〰〽]/g, ' ')
      .replace(/[\u{1F000}-\u{1FAFF}]/gu, ' ')
      
      .replace(/\s+/g, ' ').trim();
  }
  /* ==================== MOTOR DE VOZ (empaquetado, v57) ====================
     TODO el audio del móvil vive aquí, en dos mitades claras:
       SALIDA  stopSpeak()/speak(text): voz de nexus — 1ª frase al instante
               (dos trozos generados en paralelo), reproducción encadenada e
               interrumpible. Si el PC no da voz, AVISO visible (nunca mutismo).
       ENTRADA startListening()/stopListening() + modo ∞:
               · ◉ un toque = UN turno (reconocedor nativo del APK si existe;
                 si no, la grabadora).
               · ∞ = MICRO ABIERTO de verdad: getUserMedia se abre UNA sola vez
                 (cancelación de eco) y un vigilante de 60 ms lo hace todo:
                 CALIBRA el ruido ambiente (solo dispara con voz real por encima
                 del suelo), corta el turno a 0,8 s de silencio, e INTERRUMPE a
                 nexus si le hablas mientras suena. Nada de abrir/cerrar el
                 micro por turno: eso era lento y rompía el audio en Android. */

  let convMode = false;      // ∞ activo
  let _ttsAudio = null;      // <audio> sonando ahora
  let _ttsSeq = 0;           // token: al cortar, invalida la cadena de audios
  let _mic = null;           // micro persistente { stream, ctx, an, buf }
  let _monitor = null;       // vigilante (60 ms)
  let _rec = null;           // MediaRecorder del turno en curso
  let _recMeta = null;       // { started, spoke, silence, t0, send }
  let _awaiting = 0;         // ts: enviado y esperando respuesta/voz
  let _noise = 0.02;         // suelo de RUIDO calibrado
  let _calN = 0;
  let _barge = 0;
  let voiceBusy = false;
  let NATIVE_OK = !!(window.WabiksNative && window.WabiksNative.startVoice);
  const talk = $('talk');

  // ------------------------------ SALIDA ------------------------------
  function stopSpeak() {
    _ttsSeq++;
    if (_ttsAudio) { try { _ttsAudio.pause(); _ttsAudio.currentTime = 0; } catch (_) {} _ttsAudio = null; }
    if (window.speechSynthesis) { try { speechSynthesis.cancel(); } catch (_) {} }
  }
  function _splitFirst(t) {
    const m = String(t).match(/^([\s\S]{20,240}?[\.\!\?…])\s+([\s\S]{20,})$/);
    return m ? [m[1], m[2]] : [String(t), ''];
  }
  function _playChain(url, next) {
    const seq = _ttsSeq;
    try {
      const a = new Audio(url);
      _ttsAudio = a;
      const done = () => {
        if (_ttsAudio === a) _ttsAudio = null;
        if (seq !== _ttsSeq) return;
        if (next) next(); else setState('idle');
      };
      a.addEventListener('ended', done);
      a.addEventListener('error', done);
      a.play().then(() => { _awaiting = 0; }).catch(done);
    } catch (_) { if (next) next(); else setState('idle'); }
  }
  async function speak(text) {
    if (muteAI) {                           // silenciado A PROPÓSITO: avisar, no callar sin más
      _awaiting = 0;
      $('hint').textContent = '🔇 Mi voz está silenciada aquí — toca el botón «IA» para oírme.';
      return;
    }
    if (!_noEmoji(text)) { _awaiting = 0; return; }
    stopSpeak();
    const seq = _ttsSeq;
    const parts = _splitFirst(text);
    const ask = (t) => fetch(`${HTTP}/api/tts_say${TQ}`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) })
      .then((r) => r.json()).catch(() => null);
    const f1 = ask(parts[0]);
    const f2 = parts[1] ? ask(parts[1]) : null;
    const d1 = await f1;
    if (seq !== _ttsSeq) return;
    if (d1 && d1.url) {
      setState('speaking');
      _playChain(`${HTTP}${d1.url}${TQ}`, f2 ? (async () => {
        const d2 = await f2;
        if (seq !== _ttsSeq) return;
        if (d2 && d2.url) _playChain(`${HTTP}${d2.url}${TQ}`);
        else setState('idle');
      }) : null);
      return;
    }
    _awaiting = 0;
    if (window.speechSynthesis) {          // respaldo (PWA): voz del navegador
      try {
        const u = new SpeechSynthesisUtterance(_noEmoji(text).slice(0, 400));
        u.lang = 'es-ES';
        speechSynthesis.cancel(); speechSynthesis.speak(u);
        return;
      } catch (_) {}
    }
    $('hint').textContent = '⚠ La voz del PC no responde (/api/tts_say) — ¿backend reiniciado?';
  }

  // ------------------------------ ENTRADA ------------------------------
  function _level() {
    if (!_mic) return 0;
    _mic.an.getByteTimeDomainData(_mic.buf);
    let p = 0;
    for (let k = 0; k < _mic.buf.length; k++) {
      const v = Math.abs(_mic.buf[k] - 128) / 128;
      if (v > p) p = v;
    }
    return p;
  }
  function _gate() { return Math.max(0.05, _noise * 3); }   // VOZ = superar el ruido ×3

  async function _openMic() {
    if (_mic) return true;
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)) {
      $('hint').textContent = 'Aquí no puedo grabar; usa ◉ (voz nativa) o el teclado.';
      return false;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio:
        { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const an = ctx.createAnalyser(); an.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(an);
      _mic = { stream, ctx, an, buf: new Uint8Array(an.fftSize) };
      _noise = 0.02; _calN = 0;
      if (!_monitor) _monitor = setInterval(_tick, 60);
      return true;
    } catch (_) {
      $('hint').textContent = 'Permite el micrófono a la app para poder hablar.';
      return false;
    }
  }
  function _closeMic() {
    _stopTurn(false);
    if (_monitor) { clearInterval(_monitor); _monitor = null; }
    if (_mic) {
      try { _mic.stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
      try { _mic.ctx.close(); } catch (_) {}
      _mic = null;
    }
  }
  function _startTurn() {
    if (!_mic || _rec || muteMe) return;
    try {
      const mr = new MediaRecorder(_mic.stream);
      const chunks = [];
      mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      mr.onstop = () => {
        const meta = _recMeta; _rec = null; _recMeta = null;
        voiceBusy = false; talk.classList.remove('on');
        const blob = (meta && meta.send && meta.started && chunks.length)
          ? new Blob(chunks, { type: mr.mimeType || 'audio/webm' }) : null;
        if (!convMode) _closeMic();
        if (blob) _transcribe(blob);
        else if (!convMode) setState('idle');
      };
      mr.start();
      _rec = mr;
      _recMeta = { started: false, spoke: 0, silence: 0, t0: Date.now(), send: true };
      voiceBusy = true; talk.classList.add('on'); setState('listening');
    } catch (_) { /* sin grabadora */ }
  }
  function _stopTurn(send) {
    if (_recMeta) _recMeta.send = !!send;
    if (_rec) { try { _rec.stop(); } catch (_) {} }
  }
  async function _transcribe(blob) {
    setState('thinking');
    let d = null;
    try {
      d = await (await fetch(`${HTTP}/api/stt_audio${TQ}`, { method: 'POST',
        headers: { 'Content-Type': blob.type || 'application/octet-stream' }, body: blob })).json();
    } catch (_) {}
    if (d && d.text) { _awaiting = Date.now(); send(d.text, true); }
    else {
      $('hint').textContent = 'No te he entendido — repítemelo.';
      if (!convMode) setState('idle');
    }
  }

  // VIGILANTE (60 ms): calibra ruido, detecta VOZ real, corta turnos e interrumpe.
  function _tick() {
    if (!_mic || muteMe) return;
    const lvl = _level();
    if (_calN < 8) { _noise = (_noise * _calN + lvl) / (_calN + 1); _calN++; return; }
    if (lvl < _gate()) _noise = _noise * 0.98 + lvl * 0.02;   // el suelo se adapta solo
    const voiced = lvl >= _gate();
    if (_ttsAudio) {                        // nexus HABLANDO → ¿le interrumpes?
      _barge = voiced ? _barge + 60 : 0;
      if (_barge >= 240) { _barge = 0; stopSpeak(); _startTurn(); }
      return;
    }
    _barge = 0;
    if (_rec && _recMeta) {                 // ESCUCHANDO un turno
      const m = _recMeta;
      if (voiced) { m.started = true; m.spoke += 60; m.silence = 0; }
      else if (m.started) m.silence += 60;
      const t = Date.now() - m.t0;
      if (m.started && m.silence >= 800 && m.spoke >= 200) _stopTurn(true);
      else if (t > 15000) _stopTurn(m.started);
      else if (!m.started && t > 12000) _stopTurn(false);   // reinicio limpio
      return;
    }
    if (!convMode) return;                  // sin ∞ no se rearma solo
    if (_awaiting && Date.now() - _awaiting < 45000) return;  // esperando respuesta
    _awaiting = 0;
    _startTurn();
  }

  // ------------------------------ CONTROLES ------------------------------
  window.wabiksVoiceStart = () => { stopSpeak(); voiceBusy = true; talk.classList.add('on'); setState('listening'); };
  window.wabiksVoiceEnd = (err) => {
    voiceBusy = false; talk.classList.remove('on'); setState('idle');
    if (err === 'sin-reconocimiento') NATIVE_OK = false;   // → grabadora + Whisper del PC
  };
  window.wabiksVoiceResult = (text) => { if (text) send(text, true); };

  async function startListening() {
    if (muteMe || voiceBusy) return;
    stopSpeak();
    if (convMode) { _startTurn(); return; }
    if (NATIVE_OK) { window.WabiksNative.startVoice(); return; }
    if (await _openMic()) _startTurn();     // un turno; al acabar, el micro se cierra
  }
  function stopListening() { _stopTurn(false); }

  talk.addEventListener('click', () => {
    if (muteMe) { $('hint').textContent = 'Estás muteado (🎙⛔) — quítalo para hablar.'; return; }
    if (voiceBusy) { stopListening(); return; }
    startListening();
  });
  if (NATIVE_OK) {                          // mantener pulsado ◉ = cambiar de PC
    let lp = null;
    talk.addEventListener('touchstart', () => { lp = setTimeout(() => window.WabiksNative.resetHost(), 1200); });
    talk.addEventListener('touchend', () => clearTimeout(lp));
  }
  $('hint').textContent = 'Pulsa ◉ para hablar · ∞ = conversación continua';

  const bConv = $('conv');
  bConv.addEventListener('click', async () => {
    if (!convMode) {
      if (!(await _openMic())) return;
      convMode = true;
      bConv.classList.add('conv-on');
      _awaiting = 0;
      $('hint').textContent = 'Micro abierto: habla cuando quieras · ∞ para salir.';
      _startTurn();
    } else {
      convMode = false;
      bConv.classList.remove('conv-on');
      _closeMic(); stopSpeak(); setState('idle');
      $('hint').textContent = 'Pulsa ◉ para hablar · ∞ = conversación continua';
    }
  });

  function showReply(text, channel) {
    if (_pend) { _pend.remove(); _pend = null; }
    if (!text) return;                      // eco ignorado / respuesta vacía: nada que pintar
    addMsg('wb', linkify(text));
    if (channel === undefined || channel === 'mobile') speak(text);   // solo habla LO TUYO
  }
  // ---- MUTE doble ----
  const bAI = $('mute-ai'), bME = $('mute-me');
  function paintMutes() {
    bAI.classList.toggle('on', muteAI);
    bAI.textContent = muteAI ? '🔇 IA' : '🔊 IA';
    bME.classList.toggle('on', muteMe);
    bME.textContent = muteMe ? '🎙⛔' : '🎙 YO';
  }
  bAI.addEventListener('click', () => {
    muteAI = !muteAI;
    localStorage.setItem('nexus_m_ai', muteAI ? '1' : '0');
    if (muteAI) stopSpeak();               // corta lo que esté diciendo (audio o navegador)
    paintMutes();
  });
  bME.addEventListener('click', () => {
    muteMe = !muteMe;
    if (muteMe) { try { stopListening(); } catch (_) {} }
    fetch(`${HTTP}/api/config${TQ}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mic_muted: muteMe }) }).catch(() => {});
    paintMutes();
  });
  paintMutes();

  function send(text, fromVoice) {
    if (!text) return;
    stopSpeak();                            // al mandar una orden nueva, calla la anterior
    addMsg('me', linkify(text));
    if (_pend) _pend.remove();
    _pend = addMsg('wb', '…');
    setState('thinking');
    let sent = false;
    if (ws && ws.readyState === 1) {
      try { ws.send(JSON.stringify({ type: 'command', text, voice: !!fromVoice, channel: 'mobile' })); sent = true; } catch (_) {}
    }
    if (!sent) {
      fetch(`${HTTP}/api/command${TQ}`, { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ text, voice: !!fromVoice, channel: 'mobile' }) })
        .then(r => r.json()).then(d => { showReply(d.reply); setState('idle'); }).catch(() => {
          if (_pend) { _pend.textContent = 'Sin conexión con el PC.'; _pend = null; } });
    }
  }
  $('send').addEventListener('click', () => { send($('term').value.trim()); $('term').value=''; });
  $('term').addEventListener('keydown', e => { if (e.key==='Enter'){ send($('term').value.trim()); $('term').value=''; } });

  // ===== BUSCADOR DE DISPOSITIVOS (tipo «buscar Bluetooth») =====
  let _devScanning = false, _devData = [];
  function devButtons(d) {
    if (d.kind === 'ha') {
      if (d.domain === 'cover') return [['⬆ Abrir', 'on'], ['⬇ Cerrar', 'off']];
      if (d.domain === 'scene' || d.domain === 'script') return [['▸ Activar', 'on']];
      return [['⏻ Encender', 'on'], ['⭘ Apagar', 'off']];
    }
    return [['⏻ Encender', 'on'], ['⭘ Apagar', 'off'], ['🔉 Vol −', 'vol_down'], ['🔊 Vol +', 'vol_up'],
      ['🔇 Silenciar', 'mute'], ['⏮ Canal', 'ch_down'], ['Canal ⏭', 'ch_up'], ['🔗 Emparejar', 'pair', 'wide']];
  }
  function devSub(d) {
    if (d.kind === 'ha') return d.state ? (d.on ? 'encendido' : (d.state === 'off' ? 'apagado' : d.state)) : 'Home Assistant';
    return [d.ip, d.vendor && d.vendor !== d.type ? d.vendor : '', d.mac].filter(Boolean).join(' · ');
  }
  async function devControl(d, action, btn) {
    const msg = btn.closest('.ds-ctrls').querySelector('.ds-msg');
    if (msg) msg.textContent = '⏳ enviando…';
    const body = d.kind === 'ha'
      ? { kind: 'ha', action, entity_id: d.entity_id, name: d.name, domain: d.domain }
      : { kind: 'tv', action, ip: d.ip, brand: d.brand, mac: d.mac, name: d.name };
    let res = null;
    try {
      res = await (await fetch(`${HTTP}/api/home/control${TQ}`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();
    } catch (_) {}
    if (msg) msg.textContent = (res && res.reply) || 'Sin respuesta del dispositivo.';
    if (d.kind === 'ha' && res && res.ok && (action === 'on' || action === 'off')) {
      d.on = action === 'on'; d.state = action;
      const dot = btn.closest('.ds-item').querySelector('.ds-dot');
      if (dot) dot.className = 'ds-dot ' + (d.on ? 'on' : 'off');
    }
  }
  function renderDevs(devices) {
    _devData = devices;
    const list = $('ds-list'); if (!list) return;
    if (!devices.length) { list.innerHTML = '<div class="ds-empty">No he encontrado dispositivos. ¿El PC está en tu WiFi?</div>'; return; }
    const item = (d, i) => {
      const dot = d.kind === 'ha' ? `<span class="ds-dot ${d.on ? 'on' : 'off'}"></span>` : '';
      const btns = d.controllable
        ? devButtons(d).map(([l, a, w]) => `<button data-a="${a}" class="${w || ''}">${l}</button>`).join('') + '<div class="ds-msg"></div>'
        : '';
      return `<div class="ds-item ${d.controllable ? 'ctrl' : 'info'}" data-i="${i}">
        <div class="ds-top"><div class="ds-ic">${d.icon || '📟'}${dot}</div>
          <div class="ds-meta"><b>${escH(d.name || d.type)}</b><span>${escH(d.type || '')}</span><small>${escH(devSub(d))}</small></div>
          ${d.controllable ? '<div class="ds-go">▾</div>' : ''}</div>
        ${d.controllable ? `<div class="ds-ctrls">${btns}</div>` : ''}</div>`;
    };
    const ctrl = devices.filter((d) => d.controllable), info = devices.filter((d) => !d.controllable);
    let html = '';
    if (ctrl.length) html += `<div class="ds-count">🎛️ Controlables (${ctrl.length})</div>` + ctrl.map((d) => item(d, devices.indexOf(d))).join('');
    if (info.length) html += `<div class="ds-count">📡 En la red (${info.length})</div>` + info.map((d) => item(d, devices.indexOf(d))).join('');
    list.innerHTML = html;
    [...list.querySelectorAll('.ds-item.ctrl')].forEach((el) => {
      const d = _devData[+el.dataset.i];
      el.querySelector('.ds-top').addEventListener('click', () => el.classList.toggle('open'));
      el.querySelectorAll('.ds-ctrls button').forEach((b) =>
        b.addEventListener('click', (e) => { e.stopPropagation(); devControl(d, b.dataset.a, b); }));
    });
  }
  async function scanDevs() {
    if (_devScanning) return; _devScanning = true;
    const sb = $('ds-scan'); if (sb) sb.classList.add('busy');
    const cnt = $('ds-count'); if (cnt) cnt.textContent = 'buscando dispositivos en tu red…';
    let res = null;
    try { res = await (await fetch(`${HTTP}/api/home/scan${TQ}`, { method: 'POST' })).json(); } catch (_) {}
    if (sb) sb.classList.remove('busy'); _devScanning = false;
    if (!res || !res.devices) { if (cnt) cnt.textContent = 'no pude rastrear la red — reintenta'; return; }
    const c = res.counts || {};
    if (cnt) cnt.textContent = `${c.controllable || 0} controlables · ${c.total || res.devices.length} en la red`;
    renderDevs(res.devices);
    haNote();
  }
  async function haNote() {
    const note = $('ds-note'); if (!note) return;
    let s = null;
    try { s = await (await fetch(`${HTTP}/api/home/ha_status${TQ}`)).json(); } catch (_) {}
    if (s && s.running && s.has_token) { note.classList.add('hidden'); return; }
    note.innerHTML = '💡 Para manejar <b>luces y enchufes</b> hace falta Home Assistant. Conéctalo desde el PC (Dispositivos → Instalar Home Assistant). Las TVs ya funcionan.';
    note.classList.remove('hidden');
  }
  $('dev-open').addEventListener('click', () => { $('dev-sheet').classList.remove('hidden'); if (!_devData.length) scanDevs(); });
  $('ds-close').addEventListener('click', () => $('dev-sheet').classList.add('hidden'));
  $('ds-scan').addEventListener('click', scanDevs);

  // ---- ⛓ DESVINCULAR (doble toque para confirmar; sin diálogos nativos) ----
  let _unlinkArm = 0;
  $('unlink-btn').addEventListener('click', () => {
    const now = Date.now();
    if (now - _unlinkArm > 3000) {
      _unlinkArm = now;
      $('hint').textContent = '¿Desvincular de este PC? Pulsa ⛓ otra vez para confirmar.';
      return;
    }
    _unlinkArm = 0;
    try { localStorage.removeItem('nexus_token'); } catch (_) {}
    try { if (ws) ws.close(); } catch (_) {}
    if (window.WabiksNative && window.WabiksNative.resetHost) window.WabiksNative.resetHost();
    else { $('conn').textContent = 'desvinculado — escanea el QR del PC para volver'; $('hint').textContent = 'Desvinculado.'; }
  });

  setState('idle');
})();
