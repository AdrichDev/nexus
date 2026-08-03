/* ==========================================================
   nexus — Command Center SPA
   Router + vistas interactivas cableadas al backend real.

   Se carga como modulo ES (<script type="module">): sin empaquetador,
   sin framework y sin paso de compilacion, que es la restriccion dura
   de este frontend. Los estaticos van con Cache-Control: no-store
   (backend/app.py), asi que ningun import se queda cacheado viejo.
   ========================================================== */
import { $, $$, esc, linkify, api, flash, mdToHtml } from './core/dom.js';
import { state } from './core/state.js';
import { CATALOG, BOOT } from './core/catalog.js';
import { ovCard, gauge, kpi, qc, nsBtn, orbHTML } from './ui/widgets.js';
import { mountReels } from './views/reels.js';
import { mountContentOS } from './views/contentos.js';
import { mountHome } from './views/devices.js';
import { pushLog, onLogPainted } from './core/log.js';
import { onNavigate } from './core/nav.js';
import { onSend } from './core/orders.js';
import { computeMemGroups, memGroupColor, mountKnowledge, openNote, openNode,
         closeTopMiniWin, wireNs } from './views/knowledge.js';
import { paintLinkBadge, refreshDevices, onPaired, onUnpaired, openLinkModal }
  from './modals/link.js';

// orbHTML lo usa tambien mobile.html, que no es un modulo.
window.orbHTML = orbHTML;

(function () {
  let ws, coreReactor = null, miniReactor = null, interactions = 0;

  function bootSound() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
      const ac = new AC(), n = ac.currentTime, o = ac.createOscillator(), g = ac.createGain();
      o.type = 'sawtooth'; o.frequency.setValueAtTime(90, n); o.frequency.exponentialRampToValueAtTime(760, n + 1.5);
      g.gain.setValueAtTime(0.0001, n); g.gain.exponentialRampToValueAtTime(0.08, n + 1.3);
      g.gain.exponentialRampToValueAtTime(0.0001, n + 2.0); o.connect(g); g.connect(ac.destination);
      o.start(n); o.stop(n + 2.0);
    } catch (e) {}
  }
  function boot() {
    bootSound(); const log = $('#boot-log'), fill = $('#boot-fill'), pct = $('#boot-pct'); let i = 0;
    const iv = setInterval(() => {
      if (i < BOOT.length) {
        log.textContent += BOOT[i] + '\n';
        const p = Math.round((i + 1) / BOOT.length * 100);
        fill.style.width = p + '%'; if (pct) pct.textContent = p + '%';
        i++;
      } else {
        clearInterval(iv); const ov = $('#boot-overlay'); ov.classList.add('flash');
        setTimeout(() => { ov.classList.add('done'); $('#app').classList.remove('hidden'); afterBoot(); }, 750);
        setTimeout(() => { ov.style.display = 'none'; }, 1600);
      }
    }, 240);
  }

  /* ---------------- clock ---------------- */
  function clock() {
    setInterval(() => {
      const n = new Date(), p = (x) => String(x).padStart(2, '0');
      $('#clock').textContent = `${p(n.getHours())}:${p(n.getMinutes())}:${p(n.getSeconds())}`;
      $('#date').textContent = n.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
    }, 1000);
  }

  /* ---------------- WS ---------------- */
  // El log vive en core/log.js; aqui solo se dice quien lo repinta.
  onLogPainted(() => {
    if (current === 'monitor' || current === 'command') renderLogsInto();
  });
  let _wsConnecting = false, _wsEverOpen = false;
  function wsReady() { return !!ws && ws.readyState === 1; }
  function ensureWS() {   // reconecta si el enlace murió (p.ej. al volver de otra app)
    if (!ws || ws.readyState === 2 || ws.readyState === 3) connectWS();
  }
  function connectWS() {
    if (_wsConnecting || (ws && (ws.readyState === 0 || ws.readyState === 1))) return;
    _wsConnecting = true;
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => { _wsConnecting = false;
      pushLog('ok', _wsEverOpen ? 'Enlace con el núcleo restablecido' : 'Enlace con el núcleo establecido');
      _wsEverOpen = true; };
    ws.onerror = () => { try { ws.close(); } catch (e) { /* */ } };
    ws.onclose = () => { _wsConnecting = false; setTimeout(connectWS, 2000); };
    ws.onmessage = (ev) => {
      const { type, data } = JSON.parse(ev.data);
      if (type === 'log') pushLog(data.level || 'info', data.msg);
      else if (type === 'boot') pushLog('ok', data);
      else if (type === 'alert') pushLog('alert', data.msg || JSON.stringify(data));
      else if (type === 'state') setVoiceState(data);
      else if (type === 'vu') setVU(typeof data === 'object' ? (data.level || 0) : data);
      else if (type === 'metrics') { state.metrics = data; updateMetrics(); }
      else if (type === 'skill') { markSkill(data.folder); }
      else if (type === 'chat') {
        interactions++; const ki = $('#kpi-inter'); if (ki) ki.textContent = interactions;
        pulseCore();                          // el núcleo «nexus» late con CADA respuesta
        state.chat.push({ who: 'user', text: data.user }); state.chat.push({ who: 'ai', text: data.reply });
        if (current === 'chat') renderChatLog();
        if (current === 'command') renderCCChat();
        const ma = $('#mem-answer'); if (ma && current === 'memory') ma.innerHTML = linkify(data.reply);
        pushLog('info', `nexus: ${String(data.reply).slice(0, 140)}`);
        armTTSFallback(data.reply);           // habla el navegador si el backend no manda audio
        /* specs v23 (T7): lo que escribe el operador NUNCA se manda al TTS; solo
           la respuesta con rol assistant. */
      }
      else if (type === 'jobs') { state.jobs = data; if (current === 'jobs') renderJobs(); paintJobsNav(); }
      else if (type === 'job_done') {
        /* specs v23 (T12): UNA notificación por trabajo terminado, con su estado real */
        pushLog(data.status === 'completed' ? 'ok' : 'warn',
          `■ Trabajo #${data.num} (${data.title}) → ${data.status === 'completed' ? 'completado' : 'FALLIDO'}` +
          (data.error ? `: ${data.error}` : ''));
        if (current === 'jobs') api('/api/jobs/seen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      }
      else if (type === 'notification' || type === 'reminder') pushLog('alert', `🔔 ${data.title || ''} ${data.body || data.when || ''}`);
      else if (type === 'openmic') { const b = $('#btn-auto'); if (b) b.classList.toggle('on', !!data); }
      else if (type === 'audio') {
        // VOZ EN COLA: los trozos (streaming por frases) se reproducen uno tras otro.
        // Antes cada audio nuevo CORTABA al anterior → el troceo de v47 tartamudeaba.
        if (data && data.stop) { _ttsQueue.length = 0; stopTTS(); }
        else if (data && data.url) { _ttsQueue.push(data.url); if (!_ttsAudio) playNextTTS(); }
      }
      else if (type === 'paired') onPaired(data);
      else if (type === 'unpaired') onUnpaired(data);
      // 'speaking' del backend → arranca el latido del núcleo (aunque la voz
      // suene por Windows/SAPI y no llegue audio al frontend).
      if (type === 'state' && data === 'speaking') driveCoreGlow(1400);
    };
  }

  /* ---------------- data ---------------- */
  async function fetchAll() {
    const [status, skills, config, board] = await Promise.all([
      api('/api/status'), api('/api/skills'), api('/api/config'), api('/api/board')]);
    state.status = status || {}; state.skills = skills || []; state.config = config || {}; state.board = board || {};
    applyBranding();                                        // white-label: nombre y logo del sistema
    window.__sinkId = state.config.output_sink_id || '';   // dispositivo de salida elegido
    if (status?.metrics) { state.metrics = status.metrics; updateMetrics(); }
    $('#nav-skills').textContent = state.skills.length;
    const tot = board ? Object.values(board).reduce((a, v) => a + v.length, 0) : 0;
    $('#nav-tasks').textContent = tot || '';
    $('#op-name').textContent = state.config.operator_name || 'Operador';
    // sincronizar botón de micro abierto con el estado real del backend
    const ba = $('#btn-auto');
    if (ba) ba.classList.toggle('on', !!state.config.open_mic);
    if (window.__paintMuteMe) window.__paintMuteMe();
    // subtítulo del TALK honesto según el oído disponible
    const sub = $('#talk-sub');
    if (sub && state.status?.stt) {
      const wake = state.config.wake_word || ('despierta ' + (state.config.assistant_name || 'nexus').toLowerCase());
      sub.textContent = state.status.stt.engine === 'whisper'
        ? (state.config.wake_enabled ? `pulsa o di «${wake}»` : 'pulsa para hablar')
        : 'pulsa (voz real no instalada)';
    }
    fillModelBadge();
    // NO re-renderizar el Command Center en cada refresco (destruía el núcleo
    // y causaba el "parón" cada 30 s). Actualizamos solo los datos en su sitio.
    if (current === 'command') { updateOverviewCounts(); renderLLM(); }
    else if (current && current !== 'chat' && current !== 'memory') render(current);
  }
  function updateOverviewCounts() {
    const ns = $('#nav-skills'); if (ns) ns.textContent = state.skills.length;
    const ki = $('#kpi-notes'); if (ki) ki.textContent = state.status?.memory?.graph_notes ?? '—';
    const ks = document.querySelector('.kpis .kpi:nth-child(2) .val'); if (ks) ks.textContent = state.skills.length;
  }
  // WHITE-LABEL: nombre del sistema (para marca, plantillas y wake word).
  function _sysName() { const c = state.config || {}; return ((c.assistant_name || 'nexus').trim()) || 'nexus'; }
  function _sysLow() { return _sysName().toLowerCase(); }
  function _wakeWord() { const c = state.config || {}; return c.wake_word || ('despierta ' + _sysLow()); }
  // WHITE-LABEL: aplica el NOMBRE (y logo) del sistema a toda la marca de la interfaz.
  function applyBranding() {
    const c = state.config || {};
    const name = _sysName();
    const low = _sysLow();
    try { document.title = `${low} — centro de mando`; } catch (e) { /* */ }
    const bt = document.querySelector('.boot-title'); if (bt) bt.textContent = name;
    const h1 = document.querySelector('.brand h1'); if (h1) h1.textContent = low;
    const ct = document.querySelector('#core-title h1'); if (ct) ct.textContent = low;
    const ci = document.getElementById('cc-chat-input'); if (ci) ci.placeholder = 'di algo a ' + low + '…';
    const tb = document.querySelector('.tb-txt b'); if (tb) tb.textContent = 'HABLA CON ' + name.toUpperCase();
    const mute = document.getElementById('btn-mute-ai'); if (mute) mute.title = 'Silenciar a ' + low;
    // logo propio (si se ha configurado uno): reemplaza el logo y el W geométrico
    if (c.assistant_logo) {
      document.querySelectorAll('.brand-logo-img, .boot-logo-img').forEach((img) => { img.src = c.assistant_logo; img.style.display = ''; });
      document.querySelectorAll('.wlogo').forEach((el) => { el.style.display = 'none'; });
    }
  }
  function fillModelBadge() {
    const sel = $('#model-badge'); if (!sel) return;
    const c = state.config, rt = state.llm || {}, opts = [];
    if (c.llm_provider === 'ollama') opts.push(c.ollama_model);
    else opts.push(c[`${c.llm_provider}_model`] || c.cloud_model || c.llm_provider);
    /* v24: el badge cantaba el modelo CONFIGURADO aunque no funcionara. Ahora
       distingue PROBADO (✓) de solo elegido (⚠), que es justo la diferencia que
       hacía que el HUD y el chat dijeran cosas distintas. */
    const marca = rt.checked_at ? (rt.active ? ' ✓' : ' ⚠') : '';
    sel.title = rt.checked_at
      ? (rt.active ? `Probado: responde en ${rt.latency_ms} ms`
                   : (rt.error || 'elegido, pero sin responder'))
      : 'sin comprobar todavía';
    sel.innerHTML = opts.map((o) => `<option>${esc(o)}${marca}</option>`).join('');
  }

  /* Estado REAL del cerebro (una sola fuente: el runtime del backend). */
  async function refreshLlmStatus(verify) {
    try {
      const s = await api('/api/llm/status' + (verify ? '?verify=1' : ''));
      if (s && typeof s === 'object' && 'active' in s) {
        state.llm = s;
        fillModelBadge();
        pintaRuntimeAICore();
      }
      return s;
    } catch (e) { return null; }
  }
  // Línea de estado dentro de la tarjeta «Modelo local» (sin repintar la vista).
  function pintaRuntimeAICore() {
    const el = $('#ac-rt'); if (!el) return;
    const rt = state.llm || {};
    /* v26: esta línea repetía PALABRA POR PALABRA el mensaje de arriba, así que
       el mismo error salía dos veces seguidas y parecía que habían fallado dos
       cosas distintas. Ahora resume el ESTADO; el motivo lo cuenta el mensaje. */
    const msg = $('#ac-modelmsg');
    const yaDicho = msg && rt.error && msg.textContent.includes((rt.error || '').slice(0, 30));
    if (rt.active) {
      el.className = 'ac-rt';
      el.innerHTML = `<b>✓ En uso</b> · ${esc(rt.display || rt.model || '')}`
        + (rt.latency_ms ? ` · respondió en ${rt.latency_ms} ms` : '');
    } else if (rt.checked_at) {
      el.className = 'ac-rt bad';
      el.innerHTML = '<b>⚠ Sin cerebro activo</b>'
        + (yaDicho ? '' : ` · ${esc(rt.error || 'no ha respondido a la prueba')}`);
    } else {
      el.className = 'ac-rt';
      el.textContent = 'Comprobando el modelo…';
    }
  }

  /* ---------------- métricas / gauges ---------------- */
  function updateMetrics() {
    const m = state.metrics; if (!m) return;
    ['cpu', 'ram', 'disk'].forEach((k) => {
      const el = $(`#g-${k}`); if (el) { el.style.setProperty('--p', (m[k] || 0) + '%'); $(`#gv-${k}`).textContent = Math.round(m[k] || 0) + '%'; }
    });
    const pr = $('#kpi-procs'); if (pr) pr.textContent = m.procs || '—';
  }

  /* ---------------- voz ---------------- */
  let _ttsAudio = null;                 // audio TTS en curso → permite INTERRUMPIR a la IA
  window.__muteAI = localStorage.getItem('nexus_mute_ai') === '1';   // 🔇 nexus en silencio
  function stopTTS() {                  // barge-in: corta la voz de la IA al instante
    if (_ttsAudio) { try { _ttsAudio.pause(); _ttsAudio.currentTime = 0; } catch (e) { /* */ } _ttsAudio = null; }
    cancelTTSFallback();
    if (window.speechSynthesis) { try { speechSynthesis.cancel(); } catch (e) { /* */ } }
    stopTTSGlow();
  }
  // ---- VOZ DE RESPALDO del navegador (Web Speech / SAPI) ----------------------
  // GARANTIZA que nexus HABLA aunque el TTS del backend (edge-tts) falle, no esté
  // instalado o el audio quede mudo. Se dispara solo si el backend NO manda audio.
  let _ttsFallback = null;
  function _voiceClean(t) {
    return String(t || '')
      .replace(/```[\s\S]*?```/g, ' ').replace(/`([^`]*)`/g, '$1')
      .replace(/\*\*([^*]+)\*\*/g, '$1').replace(/\*([^*]+)\*/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/^\s*#{1,6}\s*/gm, '').replace(/^\s*[>*\-•]\s*/gm, '')
      // EMOJIS y símbolos decorativos → NUNCA se leen (aunque salgan en el chat)
      .replace(/[←-➿⬀-⯿︀-️‍⃣∞Ⓜ〰〽]/g, ' ')
      .replace(/[\u{1F000}-\u{1FAFF}]/gu, ' ')
      .replace(/https?:\/\/\S+/g, ' un enlace ')     // no deletrear URLs enteras
      
      .replace(/\s+/g, ' ').trim();
  }
  // género de la voz configurada (Álvaro/Jorge = hombre; Elvira/Elena… = mujer) para
  // que el respaldo del navegador use la MISMA voz y NO se cruce hombre/mujer.
  const _VOZ_M = ['álvaro', 'alvaro', 'jorge', 'tomás', 'tomas', 'pablo', 'adam', 'antoni', 'raul', 'raúl', 'diego', 'miguel', 'carlos', 'enrique'];
  const _VOZ_F = ['elvira', 'dalia', 'elena', 'salomé', 'salome', 'bella', 'rachel', 'helena', 'sabina', 'laura', 'marisol', 'paulina', 'mónica', 'monica', 'lucía', 'lucia', 'sara'];
  function _wantFemaleVoice() {
    const v = ((state.config && state.config.tts_voice) || '').toLowerCase();
    if (_VOZ_M.some((n) => v.includes(n))) return false;
    if (_VOZ_F.some((n) => v.includes(n))) return true;
    return null;                            // desconocido → lo que haya
  }
  // UNA voz del navegador elegida UNA sola vez (getVoices() está vacío al arrancar y
  // se llena async → si se elegía en cada llamada, el saludo salía con una voz y las
  // respuestas con otra: ESE era el «cambia de voz»). Se cachea con voiceschanged.
  let _cachedVoice = null, _voiceReady = false;
  function _initBrowserVoice() {
    if (!window.speechSynthesis) return;
    const vs = speechSynthesis.getVoices() || [];
    if (!vs.length) return;                 // aún no cargadas; voiceschanged reintenta
    const esV = vs.filter((v) => /^es(-|_)/i.test(v.lang) || /spanish|españ/i.test(v.name));
    const wantF = _wantFemaleVoice();
    let pick = null;
    if (wantF !== null && esV.length) {
      const reF = /female|mujer|helena|elvira|sabina|laura|mónica|monica|paulina|marisol|luc[ií]a|sara/i;
      const reM = /male|hombre|pablo|jorge|raul|raúl|diego|miguel|enrique|[áa]lvaro|carlos/i;
      pick = esV.find((v) => (wantF ? reF : reM).test(v.name) && !(wantF ? reM : reF).test(v.name));
    }
    _cachedVoice = pick || esV[0] || null;   // determinista y FIJA para toda la sesión
    _voiceReady = true;
  }
  function _backendCanSpeak() {
    const t = state.status && state.status.tts;
    return !!(t && t.engine !== 'off' && (t.edge || t.elevenlabs || t.local));
  }
  function _sameAsUser(text) {
    /* specs v23 (T7): el navegador tampoco puede leer en voz alta lo que Adri
       acaba de escribir — solo la RESPUESTA de nexus. */
    const n = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9áéíóúñü ]/gi, ' ')
      .replace(/\s+/g, ' ').trim();
    const u = n(window.__lastUserText); const t = n(text);
    return !!(u && t && (t === u || (u.length >= 8 && (t.startsWith(u) || u.startsWith(t)))));
  }
  function speakBrowser(text) {
    // NUNCA hablamos por el navegador si el backend tiene motor (edge/eleven/SAPI):
    // así SIEMPRE suena la misma voz configurada y jamás cambia a mitad/entre frases.
    if (window.__muteAI || !window.speechSynthesis || _backendCanSpeak()) return;
    if (_sameAsUser(text)) return;                 // v23 (T7)
    const t = _voiceClean(text); if (!t) return;
    try {
      if (!_voiceReady) _initBrowserVoice();
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(t.slice(0, 600));
      u.lang = 'es-ES'; u.rate = 1.02;
      if (_cachedVoice) u.voice = _cachedVoice;   // SIEMPRE la misma voz cacheada
      driveCoreGlow(Math.min(15000, 1400 + t.length * 42));   // el núcleo late mientras habla
      u.onend = u.onerror = () => stopTTSGlow();
      speechSynthesis.speak(u);
    } catch (e) { /* sin voz de navegador */ }
  }
  function armTTSFallback(text) {
    // Solo se arma el respaldo cuando el backend NO puede hablar. Si SÍ puede,
    // confiamos 100% en su voz (nunca dispara el navegador → nunca cambia de voz).
    if (window.__muteAI || _backendCanSpeak()) return;
    clearTimeout(_ttsFallback);
    _ttsFallback = setTimeout(() => speakBrowser(text), 600);
  }
  function cancelTTSFallback() { clearTimeout(_ttsFallback); _ttsFallback = null; }
  function setVoiceState(s) {
    window.__vstate = s;                 // estado actual (para recuperar el botón si se atasca)
    window.__vstateTs = Date.now();      // cuándo cambió (para detectar cuelgues al volver)
    window.setReactorState && window.setReactorState(s);
    // Si empezamos a ESCUCHAR mientras la IA hablaba, la cortamos (barge-in).
    if (s === 'listening') stopTTS();
    const names = { idle: 'Toca para hablar', listening: 'Escuchando…', thinking: 'Procesando…', speaking: 'Hablando…' };
    const el = $('#vs-state');
    if (el) {
      const lbl = { idle: 'Toca para hablar', listening: 'Escuchando', thinking: 'Procesando', speaking: 'Hablando' }[s] || 'Toca para hablar';
      el.innerHTML = esc(lbl) + (s === 'idle' ? '' : '<span class="dots"></span>');
    }
    // ORBE «ESTADO DE VOZ»: late SOLO con TU voz (al escucharte). Los impulsos
    // reales los pone setVU con el nivel del micro. La IA brilla en el núcleo.
    const orb = $('#orb');
    if (orb) {
      orb.classList.toggle('listening', s === 'listening');
      orb.classList.remove('ai-speaking');       // el orbe SOLO late con la voz del operador
      if (s !== 'listening') orb.classList.remove('voice');
    }
    const vs = $('#voice-status'); if (vs) vs.classList.toggle('active', s === 'listening');
    // botón HABLA CON nexus: rayas de vúmetro SOLO con tu voz
    const tb = $('#talk-btn'); if (tb) { tb.classList.toggle('on', s === 'listening'); tb.classList.toggle('vu', s === 'listening'); }
    // NÚCLEO «nexus»: su latido lo gobierna EN EXCLUSIVA driveCoreGlow() (abajo),
    // que decide por sí mismo si la IA está hablando (por estado o por audio).
    // Aquí solo quitamos 'listening'. Si el backend dice 'speaking', lo arrancamos.
    const ct = $('#core-title'); if (ct) ct.classList.remove('listening');
    if (s === 'speaking') driveCoreGlow();
    const sub = $('#talk-sub'); if (sub) sub.textContent = s === 'idle' ? ('pulsa o di «' + _wakeWord() + '»') : (names[s] || '');
    setThinking(s === 'thinking');
    setVU(0);   // al cambiar de estado, sensores a cero; solo suben con tu voz real
    // WATCHDOG: si nos quedamos en «Escuchando/Procesando» sin respuesta (p.ej. un
    // cuelgue), recuperamos el control solos para que el botón no quede muerto.
    clearTimeout(window.__stateWatch);
    if (s === 'thinking' || s === 'listening') {
      window.__stateWatch = setTimeout(() => {
        pushLog('warn', 'La voz tardaba demasiado; recupero el control.');
        setVoiceState('idle');
      }, 32000);
    }
  }
  // Vúmetro REAL de TU voz: mueve las barras del botón y el ORBE con el nivel del micro
  // (evento 'vu' del backend). NO toca el núcleo «nexus» (ese solo lo enciende la IA).
  function setVU(level) {
    const l = Math.max(0, Math.min(1, level || 0));
    $$('.tb-wave b').forEach((b, i) => {
      let h = 9;
      if (l > 0.03) { const w = 0.55 + 0.45 * Math.abs(Math.sin(i * 1.6 + l * 7)); h = Math.min(100, 14 + l * 86 * w); }
      b.style.height = h + '%';
    });
    const tb = $('#talk-btn'); if (tb) tb.classList.toggle('vu-live', l > 0.06);
    const orb = $('#orb'); if (orb) { orb.style.setProperty('--vu', l.toFixed(2)); orb.classList.toggle('voice', l > 0.06); }
  }
  // Reproduce el audio de la IA y hace que «nexus» se ilumine con CADA SÍLABA
  // (analiza la amplitud del audio en tiempo real, como un vúmetro de salida).
  let _ttsRaf = 0;
  // ============ CONTROLADOR ÚNICO del latido del núcleo «nexus» ============
  // El núcleo LATE mientras la IA habla, y se decide SOLO por dos señales:
  //   (a) el backend está en estado 'speaking'  (cubre voz por Windows/SAPI sin audio)
  //   (b) hay audio TTS sonando en el frontend  (edge-tts / elevenlabs)
  // Así el aura nunca se congela por el 'idle' que el backend manda al EMPEZAR el
  // audio, y se apaga limpio en cuanto la IA calla de verdad. El analizador de
  // amplitud (si hay audio) da el detalle por sílaba; si no, onda sintética.
  let _glowT0 = 0, _glowUntil = 0, _glowAnalyser = null;
  function _aiSpeaking() {
    if (window.__vstate === 'speaking') return true;
    if (_ttsAudio && !_ttsAudio.ended && !_ttsAudio.paused) return true;
    if (Date.now() < _glowUntil) return true;   // colchón mínimo (destello de respuesta)
    return false;
  }
  function driveCoreGlow(minMs) {
    const core = $('#core-title'); if (!core) return;
    if (minMs) _glowUntil = Math.max(_glowUntil, Date.now() + minMs);
    if (window.__glowRaf) return;               // ya hay un bucle en marcha
    const buf = new Uint8Array(256);
    const loop = (ts) => {
      if (!_aiSpeaking()) {                      // la IA ha callado → apagar y salir
        core.classList.remove('speaking'); core.style.setProperty('--vu', 0);
        window.__glowRaf = 0; return;
      }
      core.classList.add('speaking');            // aura/anillo/texto laten por CSS
      let vu;
      if (_glowAnalyser) {                        // amplitud REAL del audio (por sílaba)
        try { _glowAnalyser.getByteTimeDomainData(buf);
          let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
          vu = Math.min(1, Math.sqrt(sum / buf.length) * 3.6);
        } catch (e) { vu = 0.5; }
      } else {                                    // onda SINTÉTICA tipo habla
        const t = (ts - (_glowT0 || (_glowT0 = ts))) / 1000;
        vu = Math.abs(0.34 + 0.30 * Math.sin(t * 12) + 0.18 * Math.sin(t * 23 + 1) + 0.10 * Math.sin(t * 37 + 2));
      }
      core.style.setProperty('--vu', Math.max(0.15, Math.min(1, vu)).toFixed(2));
      window.__glowRaf = requestAnimationFrame(loop);
    };
    window.__glowRaf = requestAnimationFrame(loop);
  }
  // compatibilidad: pulseCore = destello de «respuesta recibida»; stopTTSGlow = apagar ya
  function pulseCore(ms = 1400) { driveCoreGlow(ms); }
  function stopTTSGlow() {
    _glowUntil = 0; _glowAnalyser = null;
    if (window.__glowRaf) { cancelAnimationFrame(window.__glowRaf); window.__glowRaf = 0; }
    const core = $('#core-title'); if (core) { core.classList.remove('speaking'); core.style.setProperty('--vu', 0); }
    const orb = $('#orb'); if (orb) { orb.classList.remove('ai-speaking'); orb.style.setProperty('--vu', 0); }
  }
  // Reproduce el audio TTS de la IA. El LATIDO del núcleo lo lleva driveCoreGlow():
  // aquí solo montamos el analizador de amplitud (si se puede) y lo conectamos.
  const _ttsQueue = [];
  function playNextTTS() {
    const u = _ttsQueue.shift();
    if (u) playTTSWithGlow(u);
  }
  function playTTSWithGlow(url) {
    try {
      stopTTS();                        // corta cualquier voz previa antes de empezar otra
      const a = new Audio(url);
      a.crossOrigin = 'anonymous';
      a.muted = !!window.__muteAI;      // 🔇 muteado: sigue «hablando» (impulsos) pero sin sonido
      _ttsAudio = a;                    // referencia → se puede INTERRUMPIR (barge-in)
      if (window.__sinkId && a.setSinkId) { a.setSinkId(window.__sinkId).catch(() => {}); }
      const done = () => { _ttsAudio = null; _glowAnalyser = null; stopTTSGlow(); endVoiceTest(); playNextTTS(); };
      a.addEventListener('ended', done);
      a.addEventListener('error', done);
      // cuando SUENA de verdad, ya no hace falta la voz de respaldo del navegador
      a.addEventListener('playing', () => {
        cancelTTSFallback();
        if (window.speechSynthesis) { try { speechSynthesis.cancel(); } catch (e) { /* */ } }
        // PRECARGA el siguiente trozo mientras suena este → sin hueco de descarga al
        // encadenar (elimina las pausas robóticas entre frases). El navegador lo cachea
        // y playNextTTS lo reproduce al instante.
        if (_ttsQueue.length) { try { const _p = new Audio(_ttsQueue[0]); _p.preload = 'auto'; _p.load(); } catch (e) { /* */ } }
      });
      // analizador de amplitud real (impulsos por sílaba) — opcional
      _glowAnalyser = null;
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        const ac = AC ? (window.__ttsAC || (window.__ttsAC = new AC())) : null;
        if (ac && ac.state === 'suspended') { try { ac.resume(); } catch (e) { /* */ } }
        // SOLO enchufamos el analizador si el contexto YA está activo. Si está
        // suspendido (autoplay sin gesto, p.ej. el saludo), NO lo enchufamos: así
        // el <audio> SUENA directo por el altavoz (con onda sintética) en vez de
        // quedar MUDO enrutado a un AudioContext parado — este era el bug de «no habla».
        if (ac && ac.state === 'running') {
          const src = ac.createMediaElementSource(a);
          const an = ac.createAnalyser(); an.fftSize = 256;
          src.connect(an); an.connect(ac.destination);
          _glowAnalyser = an;
        }
      } catch (e) { _glowAnalyser = null; }   // sin analizador → onda sintética
      driveCoreGlow();                  // ← el núcleo late mientras el audio suene
      // si el navegador bloquea el autoplay del <audio>, el respaldo armado (Web Speech) hablará solo
      Promise.resolve(a.play()).catch(() => { /* autoplay bloqueado → habla el respaldo del navegador */ });
    } catch (e) { _ttsAudio = null; _glowAnalyser = null; stopTTSGlow(); endVoiceTest(); }
  }

  function setThinking(on) {
    ['#cc-chat', '#chat-log'].forEach((sel) => {
      const el = $(sel); if (!el) return;
      let t = el.querySelector('.thinking-row');
      if (on) {
        if (!t) { t = document.createElement('div'); t.className = 'thinking-row'; t.innerHTML = orbHTML(false) + '<span class="dots" style="margin-left:8px">nexus pensando</span>'; el.appendChild(t); el.scrollTop = el.scrollHeight; }
      } else if (t) { t.remove(); }
    });
  }

  /* ---------------- probar voz (focus + pause + vúmetro) ---------------- */
  let voiceTestBtn = null, voiceTestTO = 0;
  function startVoiceTest(btn) {
    voiceTestBtn = btn;
    btn.classList.add('testing');
    btn.innerHTML = '❚❚ <span class="vt-vu"><b></b><b></b><b></b><b></b><b></b></span> Sonando…';
    clearTimeout(voiceTestTO);
    voiceTestTO = setTimeout(endVoiceTest, 9000);   // salvaguarda si no llega audio
  }
  function endVoiceTest() {
    clearTimeout(voiceTestTO);
    if (!voiceTestBtn) return;
    voiceTestBtn.classList.remove('testing');
    voiceTestBtn.innerHTML = '▶ Probar voz';
    voiceTestBtn = null;
  }

  /* ---------------- envío de órdenes ---------------- */
  function send(text) {
    if (!text) return;
    window.__lastUserText = text;      // v23 (T7): el TTS jamás repetirá esto
    if (wsReady()) {
      // speak=true → el backend genera la voz (edge-tts) y la manda por 'audio';
      // si falla, el respaldo del navegador (armado al llegar 'chat') hablará igual.
      try { ws.send(JSON.stringify({ type: 'command', text, speak: !window.__muteAI })); return; } catch (e) { /* → REST */ }
    }
    ensureWS();   // reconecta para la próxima, pero ESTA orden sale YA por la API
    api('/api/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, speak: false }) })
      .then((d) => {   // sin WS también se PINTA la respuesta (chat + núcleo)
        if (!d || d.reply == null) return;
        state.chat.push({ who: 'user', text }); state.chat.push({ who: 'ai', text: d.reply });
        pulseCore();
        if (current === 'chat') renderChatLog();
        if (current === 'command') renderCCChat();
        pushLog('info', `nexus: ${String(d.reply).slice(0, 140)}`);
        speakBrowser(d.reply);   // sin WS no llega 'audio' → habla el navegador
      });
  }
  function voice() {
    stopTTS();
    // Si el estado se quedó atascado (Procesando/Escuchando), lo recuperamos al
    // instante para que el botón nunca parezca muerto, y reintentamos.
    if (window.__vstate === 'thinking' || window.__vstate === 'listening') setVoiceState('idle');
    if (wsReady()) {
      try { ws.send(JSON.stringify({ type: 'voice' })); return; } catch (e) { /* → REST */ }
    }
    ensureWS();   // el botón NUNCA muere: sin WS, el ciclo de voz va por la API
    api('/api/voice', { method: 'POST' });
  }

  /* ==========================================================
     VISTAS
     ========================================================== */
  let current = 'command';
  let core3d = null;
  const views = {};

  views.command = () => `
    <div class="cc-grid">
      <div class="cc-col">
        <div class="panel cc-ov"><h2>Resumen del núcleo</h2>
          ${ovCard('◈', 'Núcleo IA', state.status?.llm?.provider || '—', true)}
          ${ovCard('▣', 'Memoria', (state.status?.memory?.graph_notes || 0) + ' notas', state.status?.memory?.db_online)}
          ${ovCard('🎙', 'Voz', state.status?.tts?.engine || '—', true)}
          ${ovCard('⚙', 'Habilidades', state.skills.length + ' activas', true)}
        </div>
        <div class="panel cc-gauges"><h2>Recursos <span class="link" data-view="hardware">ver equipo</span></h2>
          <div id="cc-sensors" class="cc-sensors"><div class="empty"><span class="dots">leyendo sensores</span></div></div>
        </div>
      </div>
      <div class="cc-mid">
        <div class="cc-core"><div id="core3d"></div>
          <div class="core-title" id="core-title"><div class="core-aura"></div><div class="core-ring"></div><h1>${_sysLow()}</h1></div>
        </div>
        <div class="kpis">
          ${kpi('Interacciones', `<span id="kpi-inter">${interactions}</span>`, 'sesión')}
          ${kpi('Habilidades', String(state.skills.length || '—'), 'activas', 1)}
          ${kpi('Memoria', `<span id="kpi-notes">${state.status?.memory?.graph_notes ?? '—'}</span>`, 'notas')}
          ${kpi('Procesos', '<span id="kpi-procs">—</span>', 'sistema')}
        </div>
      </div>
      <div class="cc-col">
        <div class="panel feed cc-feed"><h2>Actividad en vivo <span class="tag LIVE">VIVO</span></h2>
          <div id="cc-feed"></div>
        </div>
        <div class="panel chat-bucket cc-chat-panel"><h2>Conversación <span class="link" data-view="chat">ampliar</span></h2>
          <div id="cc-chat"></div>
          <div class="cc-chat-in"><input id="cc-chat-input" placeholder="di algo a ${_sysLow()}…"><button id="cc-chat-send">▶</button></div>
        </div>
      </div>
    </div>`;

  views.today = () => `<div class="section-title">Hoy</div>
    <div class="section-sub" id="today-sub">Tu día de un vistazo — agenda, tareas, encargos y vigilancias.</div>
    <div id="today-grid" class="grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px">
      <div class="empty"><span class="dots">cargando el día</span></div>
    </div>`;

  let todayTimer = null;
  async function loadToday() {
    const grid = $('#today-grid'); if (!grid) return;
    const d = await api('/api/today');
    if (!d) { grid.innerHTML = '<div class="empty">No he podido cargar el día.</div>'; return; }
    const sub = $('#today-sub');
    if (sub) sub.textContent = `${d.fecha} · ${d.hora} — a sus órdenes, ${d.operador}.`;
    const esc2 = (x) => String(x == null ? '' : x).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    const cards = [];
    if (d.clima) cards.push(`<div class="panel"><h2>Clima</h2><div style="font-size:14px;line-height:1.6">${esc2(d.clima)}</div></div>`);
    const t = d.tareas || {};
    const tRows = []
      .concat((t.vencidas || []).map((x) => `<div>🔴 ${esc2(x.title)} <small style="color:var(--txt-dim)">${esc2(x.due)}</small></div>`))
      .concat((t.proximas || []).map((x) => `<div>🟡 ${esc2(x.title)} <small style="color:var(--txt-dim)">${esc2(x.due)}</small></div>`))
      .concat((t.en_marcha || []).map((x) => `<div>▶ ${esc2(x.title)}</div>`));
    cards.push(`<div class="panel"><h2>Tareas <span class="link" data-view="tasks">tablero</span></h2>
      <div style="display:flex;flex-direction:column;gap:6px;font-size:13px">${tRows.join('') || '<div style="color:var(--txt-dim)">Nada urgente. ' + ((t.pendientes || 0) + ' pendientes en el tablero.') + '</div>'}</div></div>`);
    if ((d.hermes || []).length) {
      const hs = d.hermes.map((j) => `<div>${j.estado === 'hecho' ? '✔' : j.estado === 'error' ? '✖' : '⏳'} <b>#${esc2(j.num)}</b> ${esc2(j.orden)}</div>`).join('');
      cards.push(`<div class="panel"><h2>Encargos a Hermes</h2><div style="display:flex;flex-direction:column;gap:6px;font-size:13px">${hs}</div></div>`);
    }
    if ((d.vigilancias || []).length) {
      const vs = d.vigilancias.map((w) => `<div>👁 <b>#${esc2(w.num)}</b> ${esc2(w.tipo)}: ${esc2(w.objetivo)}</div>`).join('');
      cards.push(`<div class="panel"><h2>Vigilancias</h2><div style="display:flex;flex-direction:column;gap:6px;font-size:13px">${vs}</div></div>`);
    }
    if ((d.informes || []).length) {
      const ifs = d.informes.map((n) => `<div>📚 ${esc2(n)}</div>`).join('');
      cards.push(`<div class="panel"><h2>Informes recientes</h2><div style="display:flex;flex-direction:column;gap:6px;font-size:13px">${ifs}</div></div>`);
    }
    grid.innerHTML = cards.join('');
    $$('#today-grid [data-view]').forEach((el) => el.addEventListener('click', () => render(el.dataset.view)));
  }

  views.hardware = () => `<div class="section-title">Estado del equipo</div>
    <div class="section-sub">Inventario completo del hardware — CPU, GPU, RAM, disco, placa base, audio y red.</div>
    <div id="hw-body"><div class="empty"><span class="dots">leyendo hardware</span></div></div>`;

  views.home = () => `<div class="section-title">Dispositivos</div>
    <div class="section-sub">Añade lo que uses a <b>Mis dispositivos</b> — se guardan, se controlan con un toque y nexus los maneja por voz. El resto queda listado, sin ruido.</div>
    <div id="dev-ha" class="dev-ha"></div>
    <div class="dev-toolbar">
      <button id="dev-scan" class="dev-scanbtn">◎ Buscar dispositivos</button>
      <span id="dev-count" class="dev-count"></span>
      <label class="dev-tech" title="Mostrar IP y MAC en las tarjetas"><input type="checkbox" id="dev-tech-toggle"><span class="dev-tech-sw"></span> detalles técnicos (IP · MAC)</label>
    </div>
    <div id="dev-msg" class="dev-msg"></div>
    <div id="dev-radar" class="dev-radar hidden"><span></span><span></span><span></span><em>buscando dispositivos en tu red…</em></div>
    <div id="dev-grid" class="dev-grid"><div class="empty">Pulsa <b>Buscar dispositivos</b> para rastrear tu red.</div></div>`;

  async function mountHardware() {
    const el = $('#hw-body'); if (!el) return;
    const hw = await api('/api/hardware');
    if (!hw) { el.innerHTML = '<div class="empty">No he podido leer el hardware.</div>'; return; }
    if (hw.denied) { el.innerHTML = `<div class="empty">🔒 ${esc(hw.error)}</div>`; return; }
    const s = hw.static || {}, d = hw.dynamic || {};
    const gpu = (s.gpu || []).map((g) => `${esc(g.name)}${g.vram_gb ? ' · ' + g.vram_gb + ' GB' : ''}`).join('<br>') || '—';
    const audio = (s.audio || []).map(esc).join('<br>') || '—';
    const ram = (s.ram_slots || []).map((m) => `${m.gb} GB${m.speed ? ' @ ' + m.speed + ' MHz' : ''}`).join(' · ') || (d.ram ? d.ram.total_gb + ' GB' : '—');
    const bar = (p, c) => `<div class="hw-bar"><div style="width:${Math.min(100, Math.max(0, p || 0))}%;background:${c}"></div></div>`;
    // Cada recurso con SU color (como un OSD de MSI Afterburner)
    const COL = { cpu: '#22e6ff', gpu: '#4dff9e', ram: '#4d9bff', disk: '#ffd23a', vram: '#c77dff', temp: '#ff5470' };
    const g0 = (d.gpus && d.gpus[0]) || null;
    const cpuTemp = (d.cpu_temp_c != null ? d.cpu_temp_c : d.temp_c);
    const sens = (label, val, col, sub) => `<div class="hw-sens" style="--sc:${col}"><span>${label}</span><b>${val}</b>${sub ? `<i>${sub}</i>` : ''}</div>`;
    const sensors = `<div class="hw-sensors">
      ${sens('CPU', Math.round(d.cpu_percent || 0) + '%', COL.cpu, cpuTemp != null ? cpuTemp + '°C' : 'temp n/d')}
      ${g0 ? sens('GPU', g0.util + '%', COL.gpu, g0.temp_c + '°C') : sens('GPU', '—', COL.gpu, 'sin NVIDIA')}
      ${sens('RAM', Math.round(d.ram?.percent || 0) + '%', COL.ram, d.ram ? d.ram.usado_gb + '/' + d.ram.total_gb + ' GB' : '')}
      ${g0 ? sens('VRAM', (g0.mem_used_mb / 1024).toFixed(1) + '/' + (g0.mem_total_mb / 1024).toFixed(1) + ' GB', COL.vram, '') : ''}
      ${d.disco?.percent != null ? sens('DISCO', Math.round(d.disco.percent) + '%', COL.disk, d.disco.unidad || '') : ''}
    </div>`;
    el.innerHTML = sensors + `
      <div class="hw-grid">
        <div class="panel hw-card"><h2>Procesador</h2>
          <div class="hw-name">${esc(s.cpu?.name || '—')}</div>
          <div class="hw-meta">${s.cpu?.cores_fisicos || '?'} núcleos · ${s.cpu?.cores_logicos || '?'} hilos${s.cpu?.freq_max_mhz ? ' · ' + (s.cpu.freq_max_mhz / 1000).toFixed(1) + ' GHz' : ''}</div>
          <div class="hw-use">Uso: <b>${Math.round(d.cpu_percent || 0)}%</b></div>${bar(d.cpu_percent, COL.cpu)}
          ${cpuTemp != null ? `<div class="hw-meta">Temperatura: <b style="color:${COL.temp}">${cpuTemp}°C</b></div>`
            : '<div class="hw-meta">Temperatura: n/d (abre LibreHardwareMonitor para leerla)</div>'}
        </div>
        <div class="panel hw-card"><h2>Memoria RAM</h2>
          <div class="hw-name">${esc(ram)}</div>
          <div class="hw-use">${d.ram ? d.ram.usado_gb + ' / ' + d.ram.total_gb + ' GB' : '—'} · <b>${Math.round(d.ram?.percent || 0)}%</b></div>${bar(d.ram?.percent, COL.ram)}
        </div>
        <div class="panel hw-card"><h2>Tarjeta gráfica (GPU)</h2>
          <div class="hw-name">${(s.gpu || []).map((g) => `${esc(g.name)}${g.vram_gb ? ' · <b style="color:' + COL.gpu + '">' + g.vram_gb + ' GB</b>' : ''}`).join('<br>') || '—'}</div>
          ${g0 ? `<div class="hw-use">Uso: <b>${g0.util}%</b> · Temp: <b style="color:${COL.temp}">${g0.temp_c}°C</b></div>${bar(g0.util, COL.gpu)}
            <div class="hw-use">VRAM: ${(g0.mem_used_mb / 1024).toFixed(1)} / ${(g0.mem_total_mb / 1024).toFixed(1)} GB</div>${bar(100 * g0.mem_used_mb / g0.mem_total_mb, COL.vram)}`
            : '<div class="hw-meta">Sin datos en vivo (nvidia-smi no disponible)</div>'}</div>
        <div class="panel hw-card" style="grid-column:span 2"><h2>Almacenamiento (todos los discos)</h2>
          ${(d.discos && d.discos.length ? d.discos : (d.disco?.total_gb ? [d.disco] : [])).map((k) => `
            <div style="margin-bottom:9px">
              <div class="hw-use"><b>${esc(k.unidad || 'disco')}</b> — ${k.usado_gb} / ${k.total_gb} GB (${k.libre_gb ?? '?'} GB libres) · <b>${Math.round(k.percent || 0)}%</b></div>
              ${bar(k.percent, COL.disk)}</div>`).join('') || '<div class="hw-name">—</div>'}</div>
        <div class="panel hw-card"><h2>Placa base</h2>
          <div class="hw-name">${esc(s.board?.fabricante || '—')} ${esc(s.board?.modelo || '')}</div>
          <div class="hw-meta">${s.board?.bios ? 'BIOS ' + esc(s.board.bios) : ''}</div></div>
        <div class="panel hw-card"><h2>Audio</h2>
          <div class="hw-name" style="font-size:13px">${audio}</div></div>
        <div class="panel hw-card"><h2>Red</h2>
          <div class="hw-meta">↑ ${d.red?.enviado_mb || 0} MB · ↓ ${d.red?.recibido_mb || 0} MB</div>
          <div class="hw-meta">${d.procesos || '?'} procesos activos</div></div>
        <div class="panel hw-card"><h2>Sistema operativo</h2>
          <div class="hw-name">${esc(s.os?.system || '')} ${esc(s.os?.release || '')}</div>
          <div class="hw-meta">Equipo: ${esc(s.os?.node || '')} · ${esc(s.os?.machine || '')}</div>
          ${d.bateria ? `<div class="hw-meta">Batería: ${d.bateria.percent}% ${d.bateria.enchufado ? '🔌' : ''}</div>` : ''}</div>
      </div>`;
  }

  // Modelos por proveedor: cada uno tiene SU desplegable (<select>) con varias
  // opciones. Con «✎ otro (escribir)…» aparece un campo para poner cualquier modelo.
  const AC_MODELS = {
    // Catálogos REALES (revisados el 31/07/2026 contra las docs oficiales de cada API).
    // Si sale uno nuevo y aún no está aquí, usa «otro (escribir)» y ponlo a mano.
    openai: ['gpt-5.6-sol', 'gpt-5.6-sol-pro', 'gpt-5.6-terra', 'gpt-5.6-terra-pro', 'gpt-5.6-luna', 'gpt-5.6-luna-pro', 'gpt-5.5', 'gpt-5.5-pro', 'gpt-5.4', 'gpt-5.4-pro', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.3-chat', 'gpt-5.3-codex', 'gpt-5', 'gpt-5-pro', 'gpt-5-mini', 'gpt-5-nano', 'gpt-5-codex', 'o3-pro', 'o3', 'o3-mini', 'gpt-4.1', 'gpt-4.1-mini'],
    anthropic: ['claude-fable-5', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'],
    gemini: ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'],
    openrouter: ['deepseek/deepseek-r1:free', 'openai/gpt-oss-20b:free', 'deepseek/deepseek-chat-v3-0324:free', 'openai/gpt-4o', 'openai/gpt-4o-mini', 'anthropic/claude-sonnet-5', 'google/gemini-2.5-flash', 'meta-llama/llama-3.3-70b-instruct', 'deepseek/deepseek-chat'],
  };
  // Proveedores cloud (para el cerebro de nexus). Cada uno mapea a su provider real
  // del backend (openai/anthropic/gemini/cloud) con su campo de modelo y de clave.
  const CLOUD_PROVS = {
    openai:     { name: 'OpenAI (GPT)',       prov: 'openai',    keyField: 'openai_api_key',    modelField: 'openai_model',    models: AC_MODELS.openai },
    anthropic:  { name: 'Anthropic (Claude)', prov: 'anthropic', keyField: 'anthropic_api_key', modelField: 'anthropic_model', models: AC_MODELS.anthropic },
    gemini:     { name: 'Google Gemini',      prov: 'gemini',    keyField: 'gemini_api_key',    modelField: 'gemini_model',    models: AC_MODELS.gemini },
    openrouter: { name: 'OpenRouter',         prov: 'cloud',     keyField: 'cloud_llm_api_key', modelField: 'cloud_model',     models: AC_MODELS.openrouter, base: 'https://openrouter.ai/api/v1' },
  };
  // Proveedores para el CEREBRO de Hermes (mismos 4 principales).
  const HERMES_PROVS = {
    openai:     { name: 'OpenAI (GPT)',       keyField: 'openai_api_key',    models: AC_MODELS.openai },
    anthropic:  { name: 'Anthropic (Claude)', keyField: 'anthropic_api_key', models: AC_MODELS.anthropic },
    gemini:     { name: 'Google Gemini',      keyField: 'gemini_api_key',    models: AC_MODELS.gemini },
    openrouter: { name: 'OpenRouter',         keyField: 'openrouter_api_key', models: AC_MODELS.openrouter },
  };
  /* ─────────────────────────────────────────────────────────────────────────
     APARTADO «APIS» DE LA CONFIGURACIÓN — el único sitio donde van las claves.
     Antes estaban repartidas por media configuración: unas en «Google /
     Instagram / Telegram», otras en «Spotify», la de n8n en «Red», la de Home
     Assistant en «Domótica» y las de los modelos en otra pantalla distinta
     (Núcleo IA). Para saber si tenías puesta una clave había que ir a buscarla.
     Ahora se declaran AQUÍ y la pantalla se genera sola: añadir una API nueva
     es añadir una línea a esta lista, no tocar el HTML ni el guardado.
     tipo: 'secreto' (va a secrets.json, nunca se muestra) | 'ajuste' (no es
     una clave: un id, un identificador…). ───────────────────────────────── */
  const APIS = [
    { g: 'Modelos de lenguaje', k: 'openai_api_key', l: 'OpenAI', web: 'platform.openai.com/api-keys' },
    { g: 'Modelos de lenguaje', k: 'anthropic_api_key', l: 'Anthropic (Claude)', web: 'console.anthropic.com' },
    { g: 'Modelos de lenguaje', k: 'gemini_api_key', l: 'Google Gemini', web: 'aistudio.google.com/apikey' },
    { g: 'Modelos de lenguaje', k: 'cloud_llm_api_key', l: 'OpenRouter', web: 'openrouter.ai/keys' },
    { g: 'Voz', k: 'elevenlabs_api_key', l: 'ElevenLabs (voz premium)', web: 'elevenlabs.io' },
    { g: 'Voz', k: 'picovoice_key', l: 'Picovoice (palabra de activación)', web: 'console.picovoice.ai' },
    { g: 'Instagram', k: 'ig_access_token', l: 'Token de la Graph API', web: 'developers.facebook.com/tools/explorer',
      ayuda: 'Permisos: instagram_basic, instagram_manage_comments, instagram_manage_insights, pages_read_engagement' },
    { g: 'Instagram', k: 'vision_model', tipo: 'ajuste', l: 'Modelo que mira las portadas de los reels (vacío = el primero de visión que tengas en Ollama)' },
    { g: 'Instagram', k: 'ig_business_account_id', tipo: 'ajuste', l: 'ID de la cuenta Business/Creator (vale para todo: análisis y Content OS)',
      ayuda: 'El número, no el @usuario. Lo usa la skill de análisis de reels.' },
    { g: 'Google', k: 'google_client_id', l: 'Client ID', web: 'console.cloud.google.com' },
    { g: 'Google', k: 'google_client_secret', l: 'Client Secret' },
    { g: 'Mensajería', k: 'telegram_bot_token', l: 'Telegram · token del bot', web: 't.me/BotFather' },
    { g: 'Mensajería', k: 'discord_webhook_url', l: 'Discord · webhook de canal' },
    { g: 'Música', k: 'spotify_client_id', l: 'Spotify · Client ID', web: 'developer.spotify.com',
      ayuda: 'Requiere Premium. Redirect URI: http://127.0.0.1:8177/api/spotify/callback' },
    { g: 'Música', k: 'spotify_client_secret', l: 'Spotify · Client Secret' },
    { g: 'Casa y automatización', k: 'homeassistant_token', l: 'Home Assistant · token de larga duración' },
    { g: 'Casa y automatización', k: 'n8n_api_key', l: 'n8n · API key' },
    { g: 'Casa y automatización', k: 'hermes_api_key', l: 'Hermes · API key' },
    { g: 'Casa y automatización', k: 'openrouter_api_key', l: 'OpenRouter (cerebro de Hermes)',
      web: 'openrouter.ai/keys' },
  ];

  function apisHTML(c) {
    const grupos = [];
    APIS.forEach((a) => {
      const g = grupos.find((x) => x.g === a.g) || (grupos.push({ g: a.g, items: [] }), grupos[grupos.length - 1]);
      g.items.push(a);
    });
    return grupos.map((gr) => `<div class="api-grupo">${esc(gr.g)}</div>` + gr.items.map((a) => {
      const puesta = a.tipo === 'ajuste' ? !!(c[a.k] || '') : !!c['has_' + a.k];
      const marca = `<span class="api-estado ${puesta ? 'si' : 'no'}">${puesta ? '✔ guardada' : '— sin poner'}</span>`;
      const campo = a.tipo === 'ajuste'
        ? `<input id="api-${a.k}" value="${esc(c[a.k] || '')}" placeholder="${esc(a.l)}">`
        : `<input id="api-${a.k}" type="password" autocomplete="off" placeholder="${puesta ? '•••• guardada (escribe para cambiarla)' : 'pega aquí la clave…'}">`;
      const pie = [a.ayuda ? esc(a.ayuda) : '', a.web ? `se saca en ${esc(a.web)}` : '']
        .filter(Boolean).join(' · ');
      return `<label class="api-fila"><span class="api-lbl">${esc(a.l)} ${marca}</span>${campo}
        ${pie ? `<span class="api-pie">${pie}</span>` : ''}</label>`;
    }).join('')).join('');
  }

  const acModelOpts = (models, sel) =>
    models.map((m) => `<option ${m === sel ? 'selected' : ''}>${esc(m)}</option>`).join('')
    + ((sel && !models.includes(sel)) ? `<option selected>${esc(sel)}</option>` : '')
    + '<option value="__custom__">✎ otro (escribir)…</option>';

  views.aicore = () => {
    const c = state.config;
    // proveedor cloud activo actual (según llm_provider del backend)
    let curCloud = 'openai';
    if (['openai', 'anthropic', 'gemini'].includes(c.llm_provider)) curCloud = c.llm_provider;
    else if (c.llm_provider === 'cloud') curCloud = 'openrouter';
    const isLocal = c.llm_provider === 'ollama';
    const cp = CLOUD_PROVS[curCloud];
    const cloudModel = c[cp.modelField] || cp.models[0];
    // Hermes
    const curH = HERMES_PROVS[c.hermes_provider] ? c.hermes_provider : 'openai';
    const hp = HERMES_PROVS[curH];
    const hModel = c.hermes_model || hp.models[0];
    /* v24 · «EN USO» ya NO sale de la preferencia guardada: sale del runtime,
       que solo lo pone a true si el modelo ha CONTESTADO a una prueba real. */
    const rt = state.llm || {};
    const usedBadge = '<span class="ac-used">● EN USO</span>';
    const sinProbar = '<span class="ac-used warn">● SIN PROBAR</span>';
    const localUsed = !!(rt.active && rt.provider === 'ollama');
    const cloudUsed = !!(rt.active && rt.provider && rt.provider !== 'ollama'
      && rt.provider !== 'mock');   // el modo demostración no es «en uso»
    const nModels = (state.localModels && state.localModels.length) ? state.localModels.length : 0;

    return `<div class="section-title">Núcleo IA</div>
      <div class="section-sub">El cerebro de nexus (local o cloud) y, aparte, el cerebro de Hermes. Elige proveedor, modelo y pega la API key en cada uno.</div>
      <div class="ac-cards">

        <div class="ac-card ${isLocal ? 'on' : ''}">
          <div class="ac-h"><span class="ac-ic">💻</span><b>Modelo local</b>${isLocal ? (localUsed ? usedBadge : sinProbar) : ''}</div>
          <div class="ac-desc">Ollama o LM Studio en tu PC. Privado y gratis.</div>
          <label class="ac-lbl">Modelo detectado</label>
          <select id="ac-localmodel" class="ac-sel">${nModels
            ? state.localModels.map((m) => `<option ${m.name === c.ollama_model ? 'selected' : ''}>${esc(m.name)}</option>`).join('')
            : '<option>— pulsa detectar —</option>'}</select>
          <button class="ac-btn ghost" id="ac-scan">🔍 Detectar modelos locales${nModels ? ` (${nModels})` : ''}</button>
          <label class="ac-lbl">Carpetas extra de modelos (una por línea)</label>
          <textarea id="ac-scanpaths" class="ac-in" rows="2" placeholder="D:\\Modelos">${(c.model_scan_paths || []).join('\n')}</textarea>
          <button class="ac-btn" id="ac-savemodel">Probar y usar como cerebro</button>
          <div id="ac-modelmsg" class="ac-msg"></div>
          <div id="ac-rt" class="ac-rt"></div>
        </div>

        <div class="ac-card ${!isLocal ? 'on' : ''}">
          <div class="ac-h"><span class="ac-ic">☁️</span><b>Proveedor Cloud</b>${!isLocal ? (cloudUsed ? usedBadge : sinProbar) : ''}</div>
          <div class="ac-desc">El cerebro principal de nexus en la nube.</div>
          <label class="ac-lbl">Proveedor</label>
          <select id="ac-cloudprov" class="ac-sel" data-target="cloud">
            ${Object.entries(CLOUD_PROVS).map(([id, p]) => `<option value="${id}" ${id === curCloud ? 'selected' : ''}>${p.name}</option>`).join('')}
          </select>
          <label class="ac-lbl">Modelo</label>
          <select id="ac-cloudmodel" class="ac-sel">${acModelOpts(cp.models, cloudModel)}</select>
          <input id="ac-cloudcustom" class="ac-in" style="display:none" placeholder="escribe el modelo exacto…">
          <label class="ac-lbl">API key ${c['has_' + cp.keyField] ? '<span class="ac-conn">conectada ✓</span>' : ''}</label>
          <input id="ac-cloudkey" class="ac-in" type="password" autocomplete="off" placeholder="${c['has_' + cp.keyField] ? '•••• guardada (escribe para cambiarla)' : 'pega la API key…'}">
          <button class="ac-btn" id="ac-savecloud">Guardar y usar como cerebro</button>
          <div id="ac-cloudmsg" class="ac-msg"></div>
        </div>

        <div class="ac-card ac-herm">
          <div class="ac-h"><span class="ac-ic">🪽</span><b>Hermes (subagente)</b></div>
          <div class="ac-desc">El cerebro del subagente agéntico. Es aparte del de nexus.</div>
          <label class="ac-lbl">Proveedor</label>
          <select id="ac-hprov" class="ac-sel" data-target="hermes">
            ${Object.entries(HERMES_PROVS).map(([id, p]) => `<option value="${id}" ${id === curH ? 'selected' : ''}>${p.name}</option>`).join('')}
          </select>
          <label class="ac-lbl">Modelo</label>
          <select id="ac-hmodel" class="ac-sel">${acModelOpts(hp.models, hModel)}</select>
          <input id="ac-hcustom" class="ac-in" style="display:none" placeholder="escribe el modelo exacto…">
          <label class="ac-lbl">API key ${c['has_' + hp.keyField] ? '<span class="ac-conn">conectada ✓</span>' : ''}</label>
          <input id="ac-hkey" class="ac-in" type="password" autocomplete="off" placeholder="${c['has_' + hp.keyField] ? '•••• guardada (escribe para cambiarla)' : 'pega la API key…'}">
          <button class="ac-btn" id="ac-savehermes">Guardar cerebro de Hermes</button>
          <div id="ac-hmsg" class="ac-msg"></div>
        </div>

      </div>`;
  };

  views.contentos = () => `<div id="cos" class="cos-wrap"><div class="empty"><span class="dots">cargando Content OS</span></div></div>`;

  views.reels = () => `<div class="ig-wrap">
    <div class="ig-tabs" role="tablist">
      <button class="ig-tab" type="button" role="tab" data-tab="mios">Mis reels</button>
      <button class="ig-tab" type="button" role="tab" data-tab="competencia">Competencia</button>
    </div>
    <div id="ig" class="cos-wrap"><div class="empty"><span class="dots">cargando</span></div></div>
  </div>`;



  views.skills = () => `<div class="section-title">Habilidades <span style="color:var(--skill)">${state.skills.length}</span></div>
    <div class="section-sub">${state.skills.length} minions <b>ejecutables</b> (hacen cosas de verdad). Además, <b><span id="kn-count">…</span> guías de conocimiento</b> viven dentro del minion «Biblioteca dev» — se aplican con «aplica la skill …». Pulsa un minion para ver y ejecutar sus acciones.</div>
    <div class="grid agents-grid">
      ${state.skills.map((s) => {
    const cat = CATALOG[s.folder] || { color: '#22d3ee', ic: '⚙', desc: s.description };
    return `<div class="agent" data-skill="${s.folder}">
        <div class="ah"><div class="aic" style="color:${cat.color}">${cat.ic}</div><b>${esc(s.name)}</b>
          <span class="astate ${s.status === 'error' ? '' : 'active'}" style="margin-left:auto"><span class="dot"></span>${s.status === 'error' ? 'error' : 'lista'}</span></div>
        <div class="desc">${esc(cat.desc || s.description)}</div>
        <div style="font-size:10px;color:var(--txt-dim);margin-top:8px">${(s.intents || []).length} acciones · ${s.calls || 0} usos</div>
      </div>`; }).join('')}
    </div>`;

  views.tasks = () => {
    const b = state.board || {}, S = [['pendiente', 'TO DO'], ['progreso', 'IN PROGRESS'], ['revision', 'REVIEW'], ['completada', 'DONE']];
    const today = new Date().toISOString().slice(0, 10);
    return `<div class="section-title">Tareas</div><div class="section-sub">Kanban con toques de atención. <b>Arrastra una tarjeta a otra columna</b>, usa las flechas, o muévelas por voz.</div>
      <div class="kanban" style="height:calc(100vh - 250px)">
        ${S.map(([s, label], idx) => `<div class="kcol" data-s="${s}"><h3>${label}<span>${(b[s] || []).length}</span></h3>
          <div class="cards" data-s="${s}">${(b[s] || []).map((t) => {
      const late = t.due && t.due < today && s !== 'completada';
      const pr = t.priority === 'alta' ? '<span class="badge-alta">⚡ ALTA</span>' : '';
      const kindIcon = t.kind === 'evento' ? '📅' : '🛠';
      const hora = t.time ? ` ${t.time}` : '';
      return `<div class="kcard" data-id="${t.id}" draggable="true"><div class="kti">${kindIcon} ${esc(t.title)}</div>
              <div class="tags">${t.tag ? `<span>${esc(t.tag)}</span>` : ''}${t.due ? `<span style="${late ? 'color:var(--err)' : ''}">📅 ${t.due}${hora}</span>` : (hora ? `<span>🕐${hora}</span>` : '')}</div>
              <div class="km">${pr}<span class="mv">${idx > 0 ? `<button data-id="${t.id}" data-to="${S[idx - 1][0]}">◀</button>` : ''}${idx < 3 ? `<button data-id="${t.id}" data-to="${S[idx + 1][0]}">▶</button>` : ''}</span><span class="kact"><button class="kedit" data-id="${t.id}" title="Editar tarea">✎</button><button class="kdel" data-id="${t.id}" title="Eliminar tarea">🗑</button></span></div></div>`;
    }).join('')}</div></div>`).join('')}
      </div>`;
  };

  // Mueve una tarea de columna (drag&drop o flechas) → persiste en el backend y repinta.
  async function moveTask(id, state_) {
    if (!id || !state_) return;
    try {
      await api('/api/board/move', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, state: state_ }) });
      state.board = await api('/api/board');
      render('tasks');
    } catch (e) { /* */ }
  }

  // Busca una tarea por id en el tablero cargado (state.board = {estado:[tareas]}).
  function findBoardTask(id) {
    const b = state.board || {};
    for (const s of Object.keys(b)) {
      const hit = (b[s] || []).find((t) => t.id === id);
      if (hit) return hit;
    }
    return null;
  }

  // 🗑 Eliminar con confirmación INLINE (sin diálogos del navegador).
  function confirmDeleteTask(btn) {
    const card = btn.closest('.kcard'); if (!card) return;
    const km = card.querySelector('.km');
    km.innerHTML = `<span class="kconfirm" style="display:flex;gap:6px;align-items:center;font-size:11px;color:var(--err)">¿Borrar?
      <button class="kyes" style="background:var(--err);border:none;color:#fff;border-radius:6px;padding:2px 8px;cursor:pointer">Sí</button>
      <button class="kno" style="background:#0b1420;border:1px solid #ffffff33;color:#cfe;border-radius:6px;padding:2px 8px;cursor:pointer">No</button></span>`;
    km.querySelector('.kno').addEventListener('click', () => render('tasks'));
    km.querySelector('.kyes').addEventListener('click', async () => {
      await api('/api/board/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: card.dataset.id }) });
      state.board = await api('/api/board'); render('tasks');
    });
  }

  // ✎ Editar título y fecha en la propia tarjeta (inline).
  function startEditTask(id) {
    const card = document.querySelector(`.kcard[data-id="${id}"]`); if (!card) return;
    const t = findBoardTask(id); if (!t) return;
    const inp = 'width:100%;background:#0b1420;border:1px solid #22d3ee66;color:#dff;padding:5px 7px;border-radius:6px;margin-bottom:5px;font-size:12px';
    card.innerHTML = `<input class="ket" style="${inp}" placeholder="título">
      <input class="ked" type="date" style="${inp}">
      <div class="km"><button class="kesave" style="background:var(--acc,#22d3ee);border:none;color:#04121a;border-radius:6px;padding:3px 10px;cursor:pointer;font-weight:600">Guardar</button>
      <button class="kecancel" style="background:#0b1420;border:1px solid #ffffff33;color:#cfe;border-radius:6px;padding:3px 10px;cursor:pointer">Cancelar</button></div>`;
    const ti = card.querySelector('.ket'), de = card.querySelector('.ked');
    ti.value = t.title || ''; de.value = t.due || '';
    card.querySelector('.kecancel').addEventListener('click', () => render('tasks'));
    ti.addEventListener('keydown', (e) => { if (e.key === 'Enter') card.querySelector('.kesave').click(); });
    card.querySelector('.kesave').addEventListener('click', async () => {
      const title = ti.value.trim(); if (!title) { ti.focus(); return; }
      await api('/api/board/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, title, due: de.value || '' }) });
      state.board = await api('/api/board'); render('tasks');
    });
    ti.focus();
  }

  /* ================== AGENDA — un calendario de verdad ==================
     Antes esto eran dos listas: «los 10 próximos eventos» y «tareas con fecha».
     No se podía ver un mes, ni saber qué cae en qué día. Ahora hay rejilla de
     MES, tira de SEMANA y detalle de DÍA, y al pulsar un día salen sus citas
     con su hora y su descripción —que el backend ni siquiera traía—. */
  let calVista = 'mes', calRef = new Date(), calSel = null, calDatos = null;

  const CAL_DIAS = ['LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB', 'DOM'];
  const CAL_MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

  /* Fecha local en AAAA-MM-DD. NO vale toISOString(): convierte a UTC y en
     España adelanta o atrasa un día según la hora, con lo que un evento de las
     23:30 aparecía en el día siguiente. */
  const calISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const calLunes = (d) => { const x = new Date(d); const j = (x.getDay() + 6) % 7; x.setDate(x.getDate() - j); return x; };
  const calSuma = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

  views.calendar = () => `<div class="section-title">Agenda</div>
    <div class="section-sub">Tu Google Calendar y las tareas del tablero con fecha, en el mismo sitio. Pulsa un día para ver todo lo que tiene.</div>
    <div class="panel cal-panel">
      <div class="cal-bar">
        <button class="cal-nav" id="cal-prev" title="Anterior">‹</button>
        <button class="cal-nav" id="cal-hoy">Hoy</button>
        <button class="cal-nav" id="cal-next" title="Siguiente">›</button>
        <b id="cal-titulo"></b>
        <span class="cal-modos">
          <button class="cal-modo" data-v="mes">Mes</button>
          <button class="cal-modo" data-v="semana">Semana</button>
          <button class="cal-modo" data-v="dia">Día</button>
        </span>
        <span class="link" id="cal-refresh">actualizar</span>
      </div>
      <div class="cal-split">
        <div id="cal-cuerpo" class="cal-cuerpo"><div class="empty"><span class="dots">cargando</span></div></div>
        <aside id="cal-detalle" class="cal-detalle"></aside>
      </div>
    </div>`;

  /** ¿Cae `iso` dentro del tramo [ini, fin]? Un evento de varios días tiene que
     salir en TODOS sus días, no solo en el primero. Ojo al final EXCLUSIVO: en
     los eventos de día completo Google manda como fin el día SIGUIENTE al
     último, así que ahí el último día se compara con «<» y no con «<=». */
  function calAbarca(ini, fin, iso, finExclusivo) {
    if (!ini || iso < ini) return false;
    if (!fin || fin <= ini) return iso === ini;
    return finExclusivo ? iso < fin : iso <= fin;
  }

  /** Todo lo que cae un día: eventos de Google + tareas del tablero con fecha. */
  function calDelDia(iso) {
    const d = calDatos || {};
    const evs = (d.google || []).filter((e) => calAbarca(
      (e.fecha || e.when || '').slice(0, 10), (e.fecha_fin || '').slice(0, 10),
      iso, !!e.todo_el_dia))
      .map((e) => ({ tipo: 'evento', hora: e.hora || '', fin: e.hora_fin || '',
        titulo: e.what, desc: e.desc || '', lugar: e.lugar || '', dia: !!e.todo_el_dia }));
    const tks = (d.tasks || []).filter((t) => calAbarca(t.due, t.dueEnd || '', iso, false))
      .map((t) => ({ tipo: 'tarea', hora: t.time || '', fin: '', titulo: t.title,
        desc: t.notes || '', lugar: '', dia: !!t.dueEnd,
        hecha: t.state === 'completada', prio: t.priority }));
    // Lo que tiene hora, en orden; lo de todo el día no la tiene y sube arriba.
    return [...evs, ...tks].sort((a, b) => (a.hora || '').localeCompare(b.hora || ''));
  }

  /** Una cita, con su hora, su sitio y su descripción entera. */
  const calFicha = (x) => `
    <div class="cal-item ${x.tipo}${x.hecha ? ' hecha' : ''}">
      <div class="cal-it-h">${x.dia ? 'todo el día' : (x.hora ? esc(x.hora) + (x.fin ? '–' + esc(x.fin) : '') : '—')}</div>
      <div class="cal-it-c">
        <div class="cal-it-t">${x.tipo === 'tarea' ? (x.hecha ? '✓ ' : '○ ') : '◉ '}${esc(x.titulo)}${x.prio === 'alta' ? ' <span class="badge-alta">⚡ ALTA</span>' : ''}</div>
        ${x.lugar ? `<div class="cal-it-l">📍 ${esc(x.lugar)}</div>` : ''}
        ${x.desc ? `<div class="cal-it-d">${linkify(x.desc)}</div>` : ''}
      </div>
    </div>`;

  function calPintaDetalle(iso) {
    const el = $('#cal-detalle');
    if (!el) return;
    if (!iso) { el.innerHTML = '<div class="empty">Pulsa un día para ver sus citas.</div>'; return; }
    const [a, m, d] = iso.split('-');
    const items = calDelDia(iso);
    el.innerHTML = `<div class="cal-dh">${d} de ${CAL_MESES[+m - 1]} de ${a}<b>${items.length}</b></div>`
      + (items.length ? items.map(calFicha).join('')
        : '<div class="empty">Nada este día.</div>');
  }

  function calPinta() {
    const cuerpo = $('#cal-cuerpo'), tit = $('#cal-titulo');
    if (!cuerpo) return;
    $$('.cal-modo').forEach((b) => b.classList.toggle('on', b.dataset.v === calVista));
    const hoy = calISO(new Date());
    const celda = (d, fuera) => {
      const iso = calISO(d), items = calDelDia(iso);
      const chips = items.slice(0, 3).map((x) =>
        `<div class="cal-chip ${x.tipo}">${x.hora ? `<b>${esc(x.hora)}</b> ` : ''}${esc(x.titulo)}</div>`).join('');
      return `<div class="cal-dia${fuera ? ' fuera' : ''}${iso === hoy ? ' hoy' : ''}${iso === calSel ? ' sel' : ''}" data-d="${iso}">
          <div class="cal-num">${d.getDate()}</div>${chips}
          ${items.length > 3 ? `<div class="cal-mas">+${items.length - 3} más</div>` : ''}
        </div>`;
    };
    if (calVista === 'mes') {
      const y = calRef.getFullYear(), m = calRef.getMonth();
      tit.textContent = `${CAL_MESES[m]} de ${y}`;
      let d = calLunes(new Date(y, m, 1));
      let html = CAL_DIAS.map((x) => `<div class="cal-cab">${x}</div>`).join('');
      for (let i = 0; i < 42; i++) { html += celda(d, d.getMonth() !== m); d = calSuma(d, 1); }
      cuerpo.className = 'cal-cuerpo mes';
      cuerpo.innerHTML = html;
    } else if (calVista === 'semana') {
      const l = calLunes(calRef);
      tit.textContent = `semana del ${l.getDate()} de ${CAL_MESES[l.getMonth()]}`;
      let html = '';
      for (let i = 0; i < 7; i++) {
        const d = calSuma(l, i);
        html += `<div class="cal-cab">${CAL_DIAS[i]} ${d.getDate()}</div>`;
      }
      for (let i = 0; i < 7; i++) html += celda(calSuma(l, i), false);
      cuerpo.className = 'cal-cuerpo semana';
      cuerpo.innerHTML = html;
    } else {
      const iso = calSel || calISO(calRef);
      const [a, m2, d2] = iso.split('-');
      tit.textContent = `${d2} de ${CAL_MESES[+m2 - 1]} de ${a}`;
      const items = calDelDia(iso);
      cuerpo.className = 'cal-cuerpo dia';
      cuerpo.innerHTML = items.length ? items.map(calFicha).join('')
        : '<div class="empty">Nada este día.</div>';
    }
    // Pulsar un día lo abre en el lateral, ESTÉS EN LA VISTA QUE ESTÉS.
    $$('#cal-cuerpo .cal-dia').forEach((c) => c.addEventListener('click', () => {
      calSel = c.dataset.d;
      calPinta();
      calPintaDetalle(calSel);
    }));
    calPintaDetalle(calSel);
  }

  async function loadCalendar() {
    if (!$('#cal-cuerpo')) return;
    // Se pide el RANGO COMPLETO que se va a pintar, con margen a los lados para
    // los días de otro mes que asoman en la rejilla. Sin esto llegaban los 10
    // próximos eventos y el resto del mes salía vacío aunque tuviera citas.
    const y = calRef.getFullYear(), m = calRef.getMonth();
    const desde = calISO(calSuma(calLunes(new Date(y, m, 1)), -7));
    const hasta = calISO(calSuma(calLunes(new Date(y, m + 1, 0)), 14));
    calDatos = await api(`/api/calendar?desde=${desde}&hasta=${hasta}`) || {};
    calPinta();

    const est = calDatos.google_status;
    if (est && est !== 'ok') {
      // Sin Google se sigue pintando el calendario con las tareas del tablero:
      // decir solo «no conectado» y dejar la pantalla vacía sería peor.
      const txt = est === 'no conectado'
        ? 'Google no conectado. Pon el Client ID y el Secret en ⚙ (sección Google) y luego pide «qué tengo en el calendario de google».'
        : est === 'sin autorizar'
          ? 'Credenciales puestas, falta autorizar. Di «qué tengo en el calendario de google» y se abrirá el navegador una vez.'
          : 'El calendario de Google no responde ahora mismo. Las tareas del tablero sí se ven.';
      const el = $('#cal-detalle');
      if (el) el.insertAdjacentHTML('afterbegin', `<div class="cal-aviso">${esc(txt)}</div>`);
    }

    const salto = (n) => {
      if (calVista === 'mes') calRef = new Date(calRef.getFullYear(), calRef.getMonth() + n, 1);
      else if (calVista === 'semana') calRef = calSuma(calRef, 7 * n);
      else {
        calRef = calSuma(calSel ? new Date(calSel + 'T12:00') : calRef, n);
        calSel = calISO(calRef);
      }
      loadCalendar();
    };
    $('#cal-prev').onclick = () => salto(-1);
    $('#cal-next').onclick = () => salto(1);
    $('#cal-hoy').onclick = () => { calRef = new Date(); calSel = calISO(calRef); loadCalendar(); };
    $('#cal-refresh').onclick = () => loadCalendar();
    $$('.cal-modo').forEach((b) => { b.onclick = () => {
      calVista = b.dataset.v;
      if (calVista === 'dia' && !calSel) calSel = calISO(new Date());
      calPinta();
    }; });
  }

  views.memory = () => {
    const m = state.status?.memory || {};
    /* Una sola caja, y toda la pantalla para el grafo. Antes esto eran tres
       paneles arriba (vector store, operador, consultar) y el grafo debajo, con
       lo que el grafo se quedaba con media pantalla. El estado del almacén cabe
       en un piloto de la cabecera, el operador ya sale en la barra superior, y
       los campos de consultar/aprender se van al lateral. */
    return `<div class="panel kn-panel">
        <h2>Grafo de conocimiento
          <span class="vs-pill ${m.db_online ? 'on' : 'off'}"
                title="${esc(m.backend || '')} · ${m.graph_notes || 0} notas">
            vector store ${m.db_online ? 'ONLINE' : 'OFFLINE'}</span>
          <span class="link" id="mem-reload">recargar</span></h2>
        <div id="kn-split">
          <aside id="kn-tree">
            <div class="kn-tools">
              <div class="kn-row"><input id="mem-q" placeholder="qué recuerdas de…"><button id="mem-go">▶</button></div>
              <div class="kn-row"><input id="mem-learn" placeholder="ruta de un archivo o carpeta…"><button id="mem-learn-go" class="ghost">Aprender</button></div>
              <div id="mem-answer"></div>
              <div class="kn-hint">💡 Deja archivos en <b>data/memory/inbox/</b> y los aprende solo.</div>
            </div>
            <div id="kn-arbol"><div class="empty"><span class="dots">leyendo</span></div></div>
          </aside>
          <div id="kn-resize" title="Arrastra para cambiar el ancho"></div>
          <div id="kn-stage">
            <div id="kn-world"><canvas id="kn-links"></canvas></div>
            <div id="mem-tip"></div>
            <div id="kn-zoom">
              <button class="kn-zbtn" data-z="out" title="Alejar">−</button>
              <button class="kn-zbtn" data-z="fit" title="Ajustar a la pantalla">⤢</button>
              <button class="kn-zbtn" data-z="in" title="Acercar">+</button>
              <span id="kn-zlabel">100%</span>
            </div>
            <!-- Las mismas cuatro fuerzas que ajusta Obsidian, con sus rangos -->
            <button id="kn-cog" title="Fuerzas del grafo">⚙</button>
            <div id="kn-fuerzas" class="hidden">
              <h4>Fuerzas</h4>
              <label>Centro <b data-v="centro"></b>
                <input type="range" data-f="centro" min="0" max="1" step="0.01"></label>
              <label>Repulsión <b data-v="repulsion"></b>
                <input type="range" data-f="repulsion" min="0" max="20" step="0.1"></label>
              <label>Enlace <b data-v="enlace"></b>
                <input type="range" data-f="enlace" min="0" max="1" step="0.01"></label>
              <label>Distancia <b data-v="distancia"></b>
                <input type="range" data-f="distancia" min="30" max="500" step="1"></label>
              <button id="kn-reset">Restaurar</button>
            </div>
          </div>
        </div>
        <div class="mem-ayuda"><b>Rueda</b> (o Ctrl + rueda) para acercar y alejar · arrastra el fondo para moverte · arrastra un nodo y el resto le sigue · pasa el ratón para ver sus conexiones · ⚙ ajusta las fuerzas</div>
      </div>`;
  };

  let memGraphRaf = 0, hwTimer = null, ccSensTimer = null;
  // Sensores (CPU/GPU/RAM/VRAM/DISCO con temperatura) del panel «Recursos» del Centro de mando.
  async function renderMainSensors() {
    const box = document.getElementById('cc-sensors'); if (!box) return;
    const hw = await api('/api/hardware'); if (!hw) return;
    if (hw.denied) { box.innerHTML = `<div class="empty" style="font-size:11px">🔒 ${esc(hw.error)}</div>`; return; }
    const d = hw.dynamic || {};
    const COL = { cpu: '#22e6ff', gpu: '#4dff9e', ram: '#4d9bff', disk: '#ffd23a', vram: '#c77dff', temp: '#ff5470' };
    const g0 = (d.gpus && d.gpus[0]) || null;
    const cpuTemp = (d.cpu_temp_c != null ? d.cpu_temp_c : d.temp_c);
    const sens = (label, val, col, sub) => `<div class="hw-sens" style="--sc:${col}"><span>${label}</span><b>${val}</b>${sub ? `<i>${sub}</i>` : ''}</div>`;
    // TODOS los discos que detecta el sistema (C:, D:, E:…), uno por cada uno
    const disks = (d.discos && d.discos.length ? d.discos : (d.disco?.total_gb ? [d.disco] : []));
    const diskChips = disks.map((k) => sens('DISCO ' + (k.unidad || ''), Math.round(k.percent || 0) + '%', COL.disk,
      `${k.usado_gb}/${k.total_gb} GB`)).join('');
    box.innerHTML = `
      ${sens('CPU', Math.round(d.cpu_percent || 0) + '%', COL.cpu, cpuTemp != null ? cpuTemp + '°C' : 'temp n/d')}
      ${g0 ? sens('GPU', g0.util + '%', COL.gpu, g0.temp_c + '°C') : sens('GPU', '—', COL.gpu, 'sin NVIDIA')}
      ${sens('RAM', Math.round(d.ram?.percent || 0) + '%', COL.ram, d.ram ? d.ram.usado_gb + '/' + d.ram.total_gb + ' GB' : '')}
      ${g0 ? sens('VRAM', (g0.mem_used_mb / 1024).toFixed(1) + '/' + (g0.mem_total_mb / 1024).toFixed(1) + ' GB', COL.vram, '') : ''}
      ${diskChips}`;
  }
  async function mountMemory() {
    // consulta directa
    const go = () => { const q = $('#mem-q').value.trim(); if (!q) return; $('#mem-answer').innerHTML = '<span class="dots">consultando</span>'; send('qué recuerdas de ' + q); };
    $('#mem-go').addEventListener('click', go);
    $('#mem-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    const learn = () => { const p = $('#mem-learn').value.trim(); if (!p) return;
      $('#mem-answer').innerHTML = '<span class="dots">aprendiendo</span>';
      const isDir = !/\.\w{1,5}$/.test(p);
      send((isDir ? 'aprende la carpeta ' : 'aprende el documento ') + p); $('#mem-learn').value = ''; };
    $('#mem-learn-go').addEventListener('click', learn);
    $('#mem-learn').addEventListener('keydown', (e) => { if (e.key === 'Enter') learn(); });
    $('#mem-reload').addEventListener('click', mountMemory);
    // EL GRAFO. El motor vive en views/knowledge.js: nodos arrastrables, zoom con
    // Ctrl+rueda y ventanitas al pulsar. Antes esta pantalla tenia su propio
    // grafo de canvas, distinto, y habia DOS pantallas dibujando lo mismo de dos
    // maneras. Se queda una: esta.
    await mountKnowledge();
  }


  views.chat = () => `<div class="chat-wrap">
      <div class="mode-chips">
        <div class="chip" data-p="Redáctame ">✍ Compose</div>
        <div class="chip" data-p="investiga ">🔎 Research</div>
        <div class="chip" data-p="abogado del diablo: ">😈 Devil</div>
        <div class="chip" data-p="genera un guion sobre ">▶ Guion</div>
        <div class="chip" data-p="planifica el proyecto ">◈ Plan</div>
      </div>
      <div class="chat-log" id="chat-log"></div>
      <div class="chat-input"><input id="chat-in" placeholder="Escribe o pregunta lo que sea…"><button id="chat-send">▶</button></div>
    </div>`;

  views.monitor = () => `<div class="section-title">System Monitor</div><div class="section-sub">Registro en vivo de turnos, tools, LLM y eventos.</div>
    <div class="panel" style="flex:1;min-height:280px;display:flex;flex-direction:column"><h2>Recent Logs <span class="link" id="clear-logs">limpiar</span></h2><div class="logbox" id="logbox"></div></div>`;

  views.jobs = () => `<div class="section-title">Multitarea</div>
    <div class="section-sub">nexus trabaja en varias cosas A LA VEZ. Lanza un trabajo en segundo plano y sigue a lo tuyo; también puedes decir «haz X en segundo plano».</div>
    <div class="jobbar">
      <input id="job-in" placeholder="Lanzar un trabajo… (p.ej. investiga proveedores de algodón en España)">
      <button id="job-run">▶ Lanzar</button>
      <button class="ghost" id="job-clear">Limpiar terminados</button>
    </div>
    <div id="job-list" class="job-list"><div class="empty">Sin trabajos aún.</div></div>`;

  /* specs v23 (T11): estados reales de una ejecución. Se mantienen done/error por
     compatibilidad con trabajos antiguos guardados en data/jobs.json. */
  const _JOB_IC = { queued: '⏳', running: '▶', waiting_confirmation: '❓',
    completed: '✔', failed: '✕', cancelled: '∅', done: '✔', error: '✕' };
  const _JOB_ES = { queued: 'en cola', running: 'ejecutando',
    waiting_confirmation: 'esperando confirmación', completed: 'completado',
    failed: 'fallido', cancelled: 'cancelado', done: 'completado', error: 'fallido' };
  function renderJobs() {
    const box = $('#job-list'); if (!box) return;
    const list = (state.jobs && state.jobs.list) || [];
    if (!list.length) { box.innerHTML = '<div class="empty">Sin trabajos. Lanza uno arriba o di «haz X en segundo plano».</div>'; return; }
    box.innerHTML = list.slice().reverse().map((j) => `
      <div class="jobc ${j.status}">
        <div class="jobc-h"><span class="jst">${_JOB_IC[j.status] || '•'} ${_JOB_ES[j.status] || j.status}</span>
          <b>${esc(j.title)}</b>
          ${(j.status === 'running' || j.status === 'queued') ? `<button class="job-x" data-jid="${j.id}">Cancelar</button>` : ''}</div>
        ${(j.status === 'running' || j.status === 'waiting_confirmation')
          ? `<div class="jobc-p"><i style="width:${Math.max(3, j.progress || 0)}%"></i></div>
             <div class="jobc-m">${esc(j.progress_note || '')} · ${esc(j.agent || 'nexus')} · #${j.num}</div>` : ''}
        ${j.result ? `<div class="jobc-r">${linkify(String(j.result).slice(0, 700))}</div>` : ''}
        ${(j.files && j.files.length) ? `<div class="jobc-f">${j.files.map((f) =>
            `<span>${esc(f.action || 'creado')}: ${esc(f.path || '')}</span>`).join('')}</div>` : ''}
        ${j.error ? `<div class="jobc-e">✕ ${esc(j.error)}</div>` : ''}
      </div>`).join('');
    box.querySelectorAll('.job-x').forEach((b) => b.addEventListener('click',
      () => api(`/api/jobs/${b.dataset.jid}/cancel`, { method: 'POST' })));
  }
  /* specs v23 (T10): indicador dinámico junto a «Multitarea».
       sin nada = nada en marcha · «En curso» = 1 · «3» = 3 · «✓» = terminado sin
       revisar · «!» = alguno ha fallado. Lo calcula el backend (jobs.badge()) para
       que HUD y móvil digan exactamente lo mismo. */
  /* specs v23 (T15): la temperatura vive en el HEADER. Si el servicio falla, el
     componente se esconde y no bloquea absolutamente nada del resto del HUD. */
  let _wxOpen = false, _wxData = null;
  async function loadWeather() {
    const el = $('#wx'); if (!el) return;
    let d = null;
    try { d = await api('/api/weather'); } catch (e) { d = null; }
    _wxData = d;
    if (!d || !d.temp) { el.classList.add('hidden'); return; }
    el.classList.remove('hidden');
    paintWeather();
    if (!el._w) {
      el._w = 1;
      el.addEventListener('click', () => { _wxOpen = !_wxOpen; paintWeather(); });
    }
  }
  function paintWeather() {
    const el = $('#wx'); const d = _wxData; if (!el || !d) return;
    const ciudad = d.ciudad ? `${esc(d.ciudad)} · ` : '';
    const mm = (_wxOpen && d.max) ? ` <small>máx ${esc(d.max)}° / mín ${esc(d.min)}°</small>` : '';
    el.innerHTML = `<span class="wx-ic">${esc(d.icono || '🌤')}</span>${ciudad}${esc(d.temp)} °C${mm}`;
    el.title = `${d.desc || 'Tiempo'} · sensación ${d.sensacion || d.temp}°`;
  }

  function paintJobsNav() {
    const b = $('#nav-jobs'); if (!b) return;
    const c = (state.jobs && state.jobs.counts) || {};
    const n = c.active || 0;
    let badge = (state.jobs && state.jobs.badge);
    if (badge === undefined || badge === null) {
      badge = (c.failed_unseen ? '!' : n === 1 ? 'En curso' : n > 1 ? String(n)
        : c.finished_unseen ? '✓' : '');
    }
    b.textContent = badge;
    b.classList.toggle('busy', n > 0);
    b.classList.toggle('okmark', !n && badge === '✓');
    b.classList.toggle('errmark', badge === '!');
  }
  function launchJob() {
    const i = $('#job-in'); if (!i) return;
    const t = i.value.trim(); if (!t) return; i.value = '';
    api('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: t }) });
  }

  /* ---------- helpers de render ---------- */

  function renderLogsInto() {
    const box = $('#logbox');
    if (box) box.innerHTML = state.logs.slice(-120).map((l) => `<div><span class="t">${l.t}</span><span class="${l.level}">${esc(l.msg)}</span></div>`).join('');
    const feed = $('#cc-feed');
    const TAGES = { WARN: 'AVISO', LIVE: 'VIVO', INFO: 'INFO' };
    if (feed) feed.innerHTML = state.logs.slice(-8).reverse().map((l) => {
      const tag = l.level === 'alert' || l.level === 'error' ? 'WARN' : l.level === 'ok' ? 'LIVE' : 'INFO';
      return `<div class="fi"><span>${esc(l.msg).slice(0, 80)}</span><span class="tag ${tag}">${TAGES[tag]}</span></div>`;
    }).join('');
    if (box) box.scrollTop = box.scrollHeight;
  }
  function renderLLM() {
    const el = $('#cc-llm'); if (!el) return;
    const c = state.config;
    const items = [['Ollama', c.llm_provider === 'ollama'], ['OpenAI', c.has_openai_api_key], ['Anthropic', c.has_anthropic_api_key],
      ['Gemini', c.has_gemini_api_key], ['ElevenLabs', c.has_elevenlabs_api_key], ['Telegram', c.has_telegram_bot_token]];
    el.innerHTML = items.map(([n, on]) => `<div class="llm"><div class="lic">◆</div>${n}<span class="lst ${on ? 'c' : 'n'}">${on ? 'Conectado' : '—'}</span></div>`).join('');
  }
  function markSkill(folder) {
    const el = $(`.agent[data-skill="${folder}"]`);
    if (el) { el.style.borderColor = 'var(--cy)'; setTimeout(() => { el.style.borderColor = ''; }, 1500); }
  }


  /* ---------------- router ---------------- */
  const SCROLL_VIEWS = new Set(['skills', 'hardware', 'aicore', 'monitor', 'calendar', 'tasks', 'contentos', 'reels', 'jobs', 'home']);
  function render(view) {
    /* specs v23 (T16): la pantalla «Hoy» ya no existe como sección propia — su
       información vive donde toca (tiempo en el header, tareas en Tareas,
       trabajos en Multitarea, agenda en Agenda). La ruta antigua redirige. */
    if (view === 'today') view = 'command';
    current = view;
    $('#node-panel')?.classList.add('hidden');   // al cambiar de panel, cierra la info del nodo
    $('#mini-wins')?.replaceChildren();          // y TODAS las ventanitas emergentes
    $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.view === view));
    $('#views').classList.toggle('scrolls', SCROLL_VIEWS.has(view));
    $('#views').innerHTML = (views[view] || views.command)();
    mount(view);
  }
  // Los modulos que solo necesitan cambiar de pantalla piden go(); asi no
  // importan el router, que a su vez los importa a ellos.
  onNavigate(render);

  function mount(view) {
    if (view === 'command') {
      // Núcleo 2D (reactor de partículas) — el que le gusta a Adri
      const box = $('#core3d');
      if (box) {
        const cv = document.createElement('canvas');
        cv.id = 'reactor'; cv.style.cssText = 'position:absolute;inset:0;width:100%;height:100%';
        box.appendChild(cv);
        if (coreReactor) coreReactor.destroy();
        coreReactor = window.WABIKS_REACTOR.attach(cv, { particles: 90 });
      }
      updateMetrics(); renderLogsInto(); renderLLM(); renderCCChat();
      renderMainSensors();
      if (ccSensTimer) clearInterval(ccSensTimer);
      ccSensTimer = setInterval(() => { if (current === 'command') renderMainSensors(); }, 4000);
      const cs = $('#cc-chat-send'), ci = $('#cc-chat-input');
      const ccSend = () => { const t = ci.value.trim(); if (!t) return; ci.value = ''; send(t); };
      if (cs) cs.addEventListener('click', ccSend);
      if (ci) ci.addEventListener('keydown', (e) => { if (e.key === 'Enter') ccSend(); });
    }
    if (view === 'today') {
      loadToday();
      if (todayTimer) clearInterval(todayTimer);
      todayTimer = setInterval(() => { if (current === 'today') loadToday(); else { clearInterval(todayTimer); todayTimer = null; } }, 60000);
    }
    if (view === 'aicore') mountAICore();
    if (view === 'contentos') mountContentOS();
    if (view === 'reels') mountReels();
    if (view === 'skills') {
      $$('.agent').forEach((el) => el.addEventListener('click', () => openNode(el.dataset.skill)));
      api('/api/knowledge').then((k) => { const c = $('#kn-count'); if (c) c.textContent = (k?.count || 0).toLocaleString('es'); });
    }
    if (view === 'tasks') {
      $$('.kcard .mv button').forEach((b) => b.addEventListener('click', (ev) => {
        ev.stopPropagation(); moveTask(b.dataset.id, b.dataset.to);
      }));
      $$('.kcard .kdel').forEach((b) => b.addEventListener('click', () => confirmDeleteTask(b)));
      $$('.kcard .kedit').forEach((b) => b.addEventListener('click', () => startEditTask(b.dataset.id)));
      // DRAG & DROP: arrastrar una tarjeta a otra columna la mueve (petición de Adri).
      let _dragId = null;
      $$('.kcard').forEach((card) => {
        card.addEventListener('dragstart', (e) => {
          _dragId = card.dataset.id;
          card.classList.add('dragging');
          try { e.dataTransfer.setData('text/plain', card.dataset.id); e.dataTransfer.effectAllowed = 'move'; } catch (err) { /* */ }
        });
        card.addEventListener('dragend', () => { card.classList.remove('dragging'); $$('.cards.drop-hint').forEach((c) => c.classList.remove('drop-hint')); });
      });
      $$('.kanban .cards').forEach((col) => {
        col.addEventListener('dragover', (e) => { e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (err) { /* */ } col.classList.add('drop-hint'); });
        col.addEventListener('dragleave', () => col.classList.remove('drop-hint'));
        col.addEventListener('drop', (e) => {
          e.preventDefault();
          col.classList.remove('drop-hint');
          const id = _dragId || (e.dataTransfer && e.dataTransfer.getData('text/plain'));
          const to = col.dataset.s;
          _dragId = null;
          if (id && to) moveTask(id, to);
        });
      });
    }
    if (view === 'calendar') { loadCalendar(); const r = $('#cal-refresh'); if (r) r.addEventListener('click', loadCalendar); }
    if (view === 'home') mountHome();
    if (view === 'hardware') { mountHardware(); if (hwTimer) clearInterval(hwTimer); hwTimer = setInterval(() => { if (current === 'hardware') mountHardware(); }, 4000); }
    if (view !== 'hardware' && hwTimer) { clearInterval(hwTimer); hwTimer = null; }
    if (view !== 'command' && ccSensTimer) { clearInterval(ccSensTimer); ccSensTimer = null; }
    if (view === 'memory') mountMemory();
    if (view === 'chat') { renderChatLog(); $('#chat-send').addEventListener('click', chatSend); $('#chat-in').addEventListener('keydown', (e) => { if (e.key === 'Enter') chatSend(); });
      $$('.chip').forEach((c) => c.addEventListener('click', () => { $('#chat-in').value = c.dataset.p; $('#chat-in').focus(); })); }
    if (view === 'monitor') { renderLogsInto(); $('#clear-logs').addEventListener('click', () => { state.logs = []; renderLogsInto(); }); }
    if (view === 'jobs') {
      api('/api/jobs').then((d) => { state.jobs = d || { list: [], counts: {} }; renderJobs(); paintJobsNav(); })
        .then(() => api('/api/jobs/seen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }))
        // El backend YA devuelve el indicador recalculado ({seen, badge}). Antes se
        // tiraba la respuesta y el «✓» solo se limpiaba cuando llegaba el aviso por
        // WebSocket: con el WS caído se quedaba pegado para siempre aunque hubieras
        // revisado. Ahora se hace caso a lo que contesta el servidor.
        .then((r) => { if (r && r.badge !== undefined && state.jobs) { state.jobs.badge = r.badge; paintJobsNav(); } })
        .catch(() => {});
      $('#job-run')?.addEventListener('click', launchJob);
      $('#job-in')?.addEventListener('keydown', (e) => { if (e.key === 'Enter') launchJob(); });
      $('#job-clear')?.addEventListener('click', () => api('/api/jobs/clear', { method: 'POST' }));
    }
    // quick commands / links genéricos
    $$('[data-cmd]').forEach((el) => {
      if (el._w) return; el._w = 1;
      el.addEventListener('click', () => {
        if (el.dataset.view) return render(el.dataset.view);
        const cmd = el.dataset.cmd;
        if (cmd === '__voice__') return voice();
        if (el.dataset.prompt) { render('chat'); setTimeout(() => { $('#chat-in').value = cmd; $('#chat-in').focus(); }, 50); }
        else if (cmd) { send(cmd); flash(el); }
      });
    });
    $$('[data-view]').forEach((el) => { if (el._wv || el.dataset.cmd) return; el._wv = 1; if (el.tagName === 'A') return; el.addEventListener('click', () => render(el.dataset.view)); });
  }

  /* ---------------- chat ---------------- */
  function renderChatLog() {
    const el = $('#chat-log'); if (!el) return;
    el.innerHTML = state.chat.slice(-40).map((m) => `<div class="msg ${m.who}"><div class="who">${m.who === 'user' ? (state.config.operator_name || 'TÚ') : 'nexus'}</div>${linkify(m.text)}</div>`).join('');
    el.scrollTop = el.scrollHeight;
  }
  function chatSend() { const i = $('#chat-in'); const t = i.value.trim(); if (!t) return; i.value = ''; window.__lastUserText = t; send(t); }
  function renderCCChat() {
    const el = $('#cc-chat'); if (!el) return;
    const msgs = state.chat.slice(-6);
    el.innerHTML = msgs.length
      ? msgs.map((m) => `<div class="ccm ${m.who}"><b>${m.who === 'user' ? (state.config.operator_name || 'TÚ') : 'nexus'}</b> ${linkify(String(m.text).slice(0, 220))}</div>`).join('')
      : '<div class="ccm ai"><b>nexus</b> A sus órdenes. Di algo o pulsa TALK.</div>';
    el.scrollTop = el.scrollHeight;
  }

  /* ---------------- AI Core ---------------- */
  // Rellena el selector de modelo local desde la caché en memoria (state.localModels)
  // para que NO se pierdan al cambiar de pantalla.
  function fillLocalModelSelect() {
    const sel = $('#ac-localmodel'); if (!sel) return;
    const cat = state.llmCatalog || {};
    const models = cat.items || state.localModels || [];
    /* v24: la clasificación (¿sirve de cerebro?, ¿lo está sirviendo Ollama?) la
       hace AHORA el backend y llega ya hecha. Antes el navegador la deducía con
       un regex suyo: dos criterios distintos para la misma pregunta, y de ahí
       los mensajes contradictorios que reportó Adri el 25/07. */
    const usables = models.filter((m) => m.usable);
    if (models.length) {
      sel.innerHTML = models.map((m) => {
        const nota = m.note ? ` — ${m.note}` : '';
        return `<option value="${esc(m.name)}"${m.usable ? '' : ' disabled'}>${esc(m.name)}${esc(nota)}</option>`;
      }).join('');
      const cur = state.config.ollama_model;
      if (cur && [...sel.options].some((o) => o.value === cur && !o.disabled)) sel.value = cur;
      else if (usables.length) sel.value = usables[0].name;
    }
    const aviso = $('#ac-modelmsg');
    if (aviso && cat.aviso) { aviso.className = 'ac-msg warn'; aviso.textContent = cat.aviso; }
    const btn = $('#ac-scan');
    if (btn && models.length) {
      btn.textContent = usables.length
        ? `🔍 Detectar modelos locales (${usables.length} utilizables de ${models.length})`
        : `🔍 Detectar modelos locales (${models.length}, ninguno utilizable)`;
    }
  }
  // Detección en segundo plano (se llama al arrancar la app y al abrir el AI Core).
  async function refreshLocalModels() {
    try {
      const cat = await api('/api/llm/models');
      if (cat && Array.isArray(cat.items)) {
        state.llmCatalog = cat;
        state.localModels = cat.items;          // el resto del HUD sigue igual
        if (cat.active && 'active' in cat.active) state.llm = cat.active;
        fillModelBadge();
        if (current === 'aicore') { fillLocalModelSelect(); pintaRuntimeAICore(); }
      }
    } catch (e) { /* silencioso */ }
  }
  // Un <select> de modelo con la opción «✎ otro» revela su input personalizado.
  function _acModelValue(selId, customId) {
    const sel = $('#' + selId); if (!sel) return '';
    if (sel.value === '__custom__') { const ci = $('#' + customId); return ci ? ci.value.trim() : ''; }
    return sel.value;
  }
  function mountAICore() {
    // ---- Card 1: Modelo local ----
    fillLocalModelSelect();
    pintaRuntimeAICore();
    refreshLlmStatus();          // estado REAL del cerebro al abrir la pantalla
    $('#ac-scan')?.addEventListener('click', async () => {
      const btn = $('#ac-scan'); btn.textContent = '⏳ buscando…'; btn.disabled = true;
      const paths = $('#ac-scanpaths').value.split('\n').map((s) => s.trim()).filter(Boolean);
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_scan_paths: paths }) });
      const cat = await api('/api/llm/models') || {};
      const models = cat.items || [];
      state.llmCatalog = cat; state.localModels = models;
      fillLocalModelSelect();
      btn.disabled = false;
      if (!models.length) { const sel = $('#ac-localmodel'); if (sel) sel.innerHTML = '<option value="">sin modelos locales</option>'; btn.textContent = '🔍 Detectar modelos locales (0)'; }
    });
    $('#ac-savemodel')?.addEventListener('click', async () => {
      const m = $('#ac-localmodel').value;
      const msg = $('#ac-modelmsg');
      if (!m || m.startsWith('—') || m.startsWith('sin')) { if (msg) msg.textContent = 'Primero detecta y elige un modelo.'; return; }
      const paths = $('#ac-scanpaths').value.split('\n').map((s) => s.trim()).filter(Boolean);
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_scan_paths: paths }) });
      /* v24: este botón decía «✓ Cerebro activo» sin haber hablado con el modelo
         ni una vez. Ahora ESPERA a que conteste: se guarda solo si funciona. */
      const btn = $('#ac-savemodel'); const antes = btn.textContent;
      btn.disabled = true; btn.textContent = '⏳ probando el modelo…';
      if (msg) { msg.className = 'ac-msg'; msg.textContent = `Probando «${m}» con una pregunta real…`; }
      let r = null;
      try {
        r = await api('/api/llm/activate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: 'ollama', model: m }) });
      } catch (e) { r = null; }
      btn.disabled = false; btn.textContent = antes;
      const ok = !!(r && r.active);
      state.llm = r || {};
      const texto = ok ? `✓ Probado y en uso: ${m} — respondió en ${r.latency_ms} ms`
        : `✖ ${(r && r.error) || 'No he podido dejarlo funcionando. Sigue el cerebro anterior.'}`;
      pushLog(ok ? 'ok' : 'warn', ok ? `Cerebro local probado: ${m}` : `Cerebro local NO activado: ${m}`);
      await fetchAll(); fillModelBadge();
      await refreshLocalModels();
      render('aicore');
      const msg2 = $('#ac-modelmsg');
      if (msg2) { msg2.className = 'ac-msg ' + (ok ? 'ok' : 'err'); msg2.textContent = texto; }
    });

    // ---- Card 2: Proveedor Cloud (provider select → model select → key) ----
    $('#ac-cloudprov')?.addEventListener('change', () => {
      const id = $('#ac-cloudprov').value; const p = CLOUD_PROVS[id];
      const cur = state.config[p.modelField] || p.models[0];
      $('#ac-cloudmodel').innerHTML = acModelOpts(p.models, cur);
      $('#ac-cloudcustom').style.display = 'none';
      $('#ac-cloudkey').placeholder = state.config['has_' + p.keyField] ? '•••• guardada (escribe para cambiarla)' : 'pega la API key…';
    });
    $('#ac-cloudmodel')?.addEventListener('change', () => {
      const ci = $('#ac-cloudcustom'); const cus = $('#ac-cloudmodel').value === '__custom__';
      ci.style.display = cus ? 'block' : 'none'; if (cus) ci.focus();
    });
    $('#ac-savecloud')?.addEventListener('click', async () => {
      const id = $('#ac-cloudprov').value; const p = CLOUD_PROVS[id];
      const model = _acModelValue('ac-cloudmodel', 'ac-cloudcustom');
      const key = $('#ac-cloudkey').value.trim();
      const msg = $('#ac-cloudmsg');
      // La clave y la URL base sí se guardan antes (hacen falta para PROBAR);
      // el proveedor y el modelo los fija el runtime, y solo si la prueba pasa.
      if (p.base) await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cloud_base_url: p.base }) });
      if (key) await api('/api/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [p.keyField]: key }) });
      /* Igual que el local: se comprueba con una llamada real. Si no responde,
         la configuración NO se cambia (specs v24, T13). */
      const bC = $('#ac-savecloud'); const antesC = bC ? bC.textContent : '';
      if (bC) { bC.disabled = true; bC.textContent = '⏳ probando…'; }
      if (msg) { msg.className = 'ac-msg'; msg.textContent = 'Probando el modelo con una llamada real…'; }
      let rc = null;
      try {
        rc = await api('/api/llm/activate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: p.prov, model: model || '' }) });
      } catch (e) { rc = null; }
      if (bC) { bC.disabled = false; bC.textContent = antesC; }
      const okC = !!(rc && rc.active);
      state.llm = rc || {};
      const textoC = okC ? `✓ Probado y en uso: ${p.name} · ${model || '(modelo por defecto)'}`
        : `✖ ${(rc && rc.error) || 'No he podido dejarlo funcionando. Sigue el cerebro anterior.'}`;
      pushLog(okC ? 'ok' : 'warn', okC ? `Cerebro cloud probado: ${p.name} (${model})` : `Cerebro cloud NO activado: ${p.name}`);
      await fetchAll(); fillModelBadge();
      render('aicore');
      const msgC = $('#ac-cloudmsg');
      if (msgC) { msgC.className = 'ac-msg ' + (okC ? 'ok' : 'err'); msgC.textContent = textoC; }
    });

    // ---- Card 3: Hermes (provider select → model select → key → configura Hermes) ----
    $('#ac-hprov')?.addEventListener('change', () => {
      const id = $('#ac-hprov').value; const p = HERMES_PROVS[id];
      const cur = (state.config.hermes_provider === id ? state.config.hermes_model : '') || p.models[0];
      $('#ac-hmodel').innerHTML = acModelOpts(p.models, cur);
      $('#ac-hcustom').style.display = 'none';
      $('#ac-hkey').placeholder = state.config['has_' + p.keyField] ? '•••• guardada (escribe para cambiarla)' : 'pega la API key…';
    });
    $('#ac-hmodel')?.addEventListener('change', () => {
      const ci = $('#ac-hcustom'); const cus = $('#ac-hmodel').value === '__custom__';
      ci.style.display = cus ? 'block' : 'none'; if (cus) ci.focus();
    });
    $('#ac-savehermes')?.addEventListener('click', async () => {
      const provider = $('#ac-hprov').value;
      const model = _acModelValue('ac-hmodel', 'ac-hcustom');
      const key = $('#ac-hkey').value.trim();
      const msg = $('#ac-hmsg');
      if (msg) { msg.className = 'ac-msg'; msg.textContent = '⏳ configurando el cerebro de Hermes…'; }
      let res = null;
      try {
        res = await api('/api/hermes/configure', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider, model, api_key: key }) });
      } catch (e) { /* */ }
      await fetchAll();
      if (res && res.ok) {
        if (msg) { msg.className = 'ac-msg ok'; msg.textContent = `✓ Hermes: ${provider} · ${model}. Reinicio su gateway para cargarlo.`; }
        pushLog('ok', `Cerebro de Hermes: ${provider} (${model})`);
      } else {
        if (msg) { msg.className = 'ac-msg err'; msg.textContent = '✕ ' + ((res && res.error) || 'no pude configurar Hermes'); }
      }
      render('aicore');
    });
  }

  $('#np-close').addEventListener('click', () => $('#node-panel').classList.add('hidden'));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#node-panel')?.classList.add('hidden'); });


  /* ---------------- CONFIGURACIÓN: menú de 6 opciones + pop up por sección ----------------
     El botón ⚙ ya no vuelca un formulario kilométrico de nueve apartados plegados:
     despliega un MENÚ de seis opciones —cada una con su icono y su COLOR— sobre el
     fondo desenfocado, y al pulsar una se abre un POP UP pintado con ESE mismo color
     (misma mecánica `--c` que las mini-ventanas de los nodos).

     CUIDADO al tocar esto: los seis paneles se pintan A LA VEZ dentro del pop up y
     solo se MUESTRA el de la sección activa. El guardado lee de golpe campos de
     todas las secciones (#m-op, #m-tts, #m-permfiles, #m-devs…); si únicamente
     existiera en el DOM la sección abierta, guardar escribiría vacíos y se cargaría
     la configuración del usuario. Los paneles ocultos siguen en el DOM con sus
     valores intactos: NO renderices solo la sección activa. */
  const CFG_SECCIONES = [
    { id: 'operador', titulo: 'Operador', icono: '👤', color: '#22d3ee', html: (c) => `
      <fieldset><legend>OPERADOR</legend>
        <label>¿Cómo quieres que te llame?<input id="m-op" value="${esc(c.operator_name || '')}"></label>
        <label>Personalidad de nexus<select id="m-pers"></select></label>
        <div class="chk" id="m-pers-desc" style="font-size:11px;color:var(--txt-dim);line-height:1.5"></div>
        <label>Nivel de razonamiento<select id="m-reason">${[['rapido', 'Rápido (directo y breve)'], ['equilibrado', 'Equilibrado (por defecto)'], ['profundo', 'Profundo (piensa más, mejor)']].map(([v, t]) => `<option value="${v}" ${(c.reasoning_level || 'equilibrado') === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
        <label class="chk"><input type="checkbox" id="m-selflearn" ${c.self_learning !== false ? 'checked' : ''}> Auto-reentrenamiento (aprende de ti solo, en ciclo)</label>
        <label>Modelo para reentrenar<select id="m-retrain">${(() => {
          const cur = c.retrain_model || 'auto';
          const groups = [['— Automático —', [['auto', 'Automático (tu cerebro activo) — sin gasto extra']]],
            ['Económicos / rápidos', [['gpt-5.6-luna', 'gpt-5.6-luna (OpenAI)'], ['claude-haiku-4-5', 'claude-haiku-4-5 (Anthropic)'], ['gemini-2.5-flash-lite', 'gemini-2.5-flash-lite (Google)'], ['gpt-5-mini', 'gpt-5-mini (OpenAI)']]],
            ['Equilibrados', [['claude-sonnet-5', 'claude-sonnet-5 (Anthropic)'], ['gpt-5.5', 'gpt-5.5 (OpenAI)'], ['gemini-2.5-flash', 'gemini-2.5-flash (Google)']]],
            ['Potentes (más caros)', [['claude-fable-5', 'claude-fable-5 (Anthropic)'], ['gpt-5.6-sol', 'gpt-5.6-sol (OpenAI)'], ['gemini-3.5-flash', 'gemini-3.5-flash (Google)']]]];
          let html = groups.map(([g, opts]) => `<optgroup label="${g}">${opts.map(([v, t]) => `<option value="${v}" ${cur === v ? 'selected' : ''}>${t}</option>`).join('')}</optgroup>`).join('');
          if (cur && cur !== 'auto' && !/luna|haiku|flash-lite|mini|sonnet|5\.5|fable|sol|3\.5/.test(cur)) html += `<optgroup label="Actual"><option value="${esc(cur)}" selected>${esc(cur)}</option></optgroup>`;
          return html;
        })()}</select></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Destila un perfil tuyo en ciclo (y cada pocas órdenes) para atinar con tu estilo — no hace falta pedírselo. «Automático» usa el cerebro que ya tienes activo (no consume de más). Puedes elegir otro modelo para el reentreno: usa su API si tienes la key.</div>
        <div class="chk" style="font-size:12px;color:var(--txt-dim);line-height:1.5">😈 <b style="color:var(--cy)">Modo abogado del diablo: SIEMPRE ACTIVO</b><br>Skill propia de nexus — el modelo cuestiona y depura su propio razonamiento antes de responderte. No es apagable.</div></fieldset>` },

    { id: 'apis', titulo: 'Claves API', icono: '🔑', color: '#ffd23a', html: (c) => `
      <fieldset><legend>APIS · CLAVES DE ACCESO</legend>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">
          Todas las claves que usa nexus, en un solo sitio. Se guardan cifradas en
          config/secrets.json: no se suben a ningún repositorio, no salen por la API
          y no se muestran nunca — solo si están puestas o no. Deja en blanco lo que
          no uses.</div>
        ${apisHTML(c)}</fieldset>` },

    { id: 'voz', titulo: 'Voz y audio', icono: '🎙', color: '#ff7ac0', html: (c) => `
      <fieldset><legend>VOZ</legend>
        <label>Motor de voz<select id="m-tts">${['auto', 'edge', 'elevenlabs', 'local', 'off'].map((o) => `<option ${c.tts_engine === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
        <label>Voz<select id="m-voice"></select></label>
        <button class="mini" id="m-voicetest">▶ Probar voz</button>
        <label>Precisión Whisper<select id="m-whisper">${['tiny', 'small', 'medium'].map((o) => `<option ${c.whisper_model === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label></fieldset>
      <fieldset><legend>AUDIO · ENTRADA / SALIDA</legend>
        <label>Micrófono (entrada)<select id="m-indev"><option value="">— predeterminado del sistema —</option></select></label>
        <label>Altavoces / salida<select id="m-outdev"><option value="">— predeterminado del sistema —</option></select></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Metes el audio por el micrófono que elijas y nexus te habla por la salida que elijas.</div></fieldset>
      <fieldset><legend>APERTURA POR VOZ</legend>
        <label class="chk"><input type="checkbox" id="m-wake" ${c.wake_enabled ? 'checked' : ''}> Escuchar palabra de activación</label>
        <label>Palabra de activación<input id="m-wakeword" value="${esc(c.wake_word || ('despierta ' + (c.assistant_name || 'nexus').toLowerCase()))}"></label></fieldset>` },

    { id: 'proactividad', titulo: 'Proactividad', icono: '⚡', color: '#7cf6c0', html: (c) => `
      <fieldset><legend>PROACTIVIDAD · PROJECT MANAGER</legend>
        <label class="chk"><input type="checkbox" id="m-proactive" ${c.proactive !== false ? 'checked' : ''}> Toma la iniciativa: recordatorios y empujón diario sin que le hables</label>
        <label class="chk"><input type="checkbox" id="m-proactivespeak" ${c.proactive_speak !== false ? 'checked' : ''}> Que los avisos me los diga en voz alta</label>
        <label class="chk"><input type="checkbox" id="m-pmstrong" ${c.pm_strong !== false ? 'checked' : ''}> <b style="color:var(--cy)">Modo PM fuerte</b>: crea tareas de lo que hablo y las mueve según le respondo</label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Con el modo fuerte, si dices «tengo que llamar al proveedor» te lo apunta como tarea solo; y cuando te pregunte «¿cómo vas con X?», tu respuesta («ya está», «a medias», «aún no») mueve la tarea en el tablero. Apágalo si prefieres que no toque nada sin pedírselo.</div></fieldset>` },

    { id: 'permisos', titulo: 'Permisos', icono: '🛡', color: '#ff5e5e', html: (c) => `
      <fieldset><legend>PERMISOS (estilo sandbox)</legend>
        <label class="chk"><input type="checkbox" id="m-hw" ${c.perm_hardware !== false ? 'checked' : ''}> Leer hardware (CPU/RAM/placa/discos/temps)</label>
        <label>Acceso a archivos<select id="m-permfiles">${['sandbox', 'carpetas', 'todo'].map((o) => `<option ${c.perm_files === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
        <label>Carpetas permitidas (una por línea, solo modo «carpetas»)<textarea id="m-permfolders" rows="2" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--txt);font-family:inherit;padding:8px;border-radius:6px">${esc((c.perm_folders || []).join('\n'))}</textarea></label></fieldset>` },

    { id: 'red', titulo: 'Red y casa', icono: '🏠', color: '#c77dff', html: (c) => `
      <fieldset><legend>RED / AUTOMATIZACIÓN</legend>
        <label>n8n · URL base<input id="m-n8nbase" value="${esc(c.n8n_base_url || 'http://localhost:5678')}"></label>
        <label>n8n · Webhook<input id="m-n8n" value="${esc(c.n8n_webhook_url || '')}"></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Las claves de n8n y Discord están en el apartado <b style="color:#ffd23a">CLAVES API</b>.</div>
        <label>MAC del PC (Wake-on-LAN)<input id="m-wol" value="${esc(c.wol_mac || '')}"></label></fieldset>
      <fieldset><legend>DOMÓTICA</legend>
        <button type="button" id="m-scan-open" class="cfg-scanbtn">◎ Buscar dispositivos en la red</button>
        <label>Home Assistant · URL<input id="m-haurl" value="${esc(c.homeassistant_url || '')}" placeholder="http://homeassistant.local:8123"></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">El token de Home Assistant está en el apartado <b style="color:#ffd23a">CLAVES API</b>.</div>
        <label>Dispositivos conocidos (uno por línea: Nombre | IP | MAC | marca)<textarea id="m-devs" rows="3" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--txt);font-family:inherit;padding:8px;border-radius:6px" placeholder="Tele salón | 192.168.1.40 | AA:BB:CC:DD:EE:FF | samsung">${esc((c.known_devices || []).map((d) => [d.name, d.ip, d.mac, d.brand].filter(Boolean).join(' | ')).join('\n'))}</textarea></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Con Home Assistant controlas TODO (luces, enchufes, persianas, teles…). Sin él, di «escanea la red» y manejo TVs por Roku/Samsung/Wake-on-LAN.</div></fieldset>` },
  ];

  /* Capa del pop up de sección. Vive fuera de #config-modal (que se COMPARTE con
     la pantalla de vincular el móvil) para que aquella pueda reescribir
     #config-body sin llevarse por delante los campos de la configuración. */
  function cfgPopLayer() {
    let p = $('#cfg-pop');
    if (p) return p;
    p = document.createElement('div');
    p.id = 'cfg-pop'; p.className = 'hidden';
    p.innerHTML = `<div class="modal-box cfg-popbox">
        <div class="cfg-pophead"><span class="cfg-popic" id="cfg-popic"></span>
          <h2 id="cfg-poptitle">—</h2>
          <button type="button" class="cfg-popx" id="cfg-popx" title="Volver al menú">✕</button></div>
        <div id="cfg-pop-body"></div>
        <div class="modal-btns"><button type="button" class="ghost" id="cfg-popback">‹ Volver</button>
          <button type="button" id="cfg-popsave">Guardar</button></div>
      </div>`;
    document.body.appendChild(p);
    // clic en el fondo desenfocado o en ✕/Volver → al menú, nunca a la nada
    p.addEventListener('click', (e) => { if (e.target === p) cerrarSeccionConfig(); });
    $('#cfg-popx', p).addEventListener('click', cerrarSeccionConfig);
    $('#cfg-popback', p).addEventListener('click', cerrarSeccionConfig);
    return p;
  }
  function abrirSeccionConfig(id) {
    const s = CFG_SECCIONES.find((x) => x.id === id);
    if (!s) return;
    const p = cfgPopLayer(), box = p.querySelector('.cfg-popbox');
    box.style.setProperty('--c', s.color);          // borde, glow, título y acentos
    $('#cfg-popic').textContent = s.icono;
    $('#cfg-poptitle').textContent = s.titulo.toUpperCase();
    // se MUESTRA una, pero las seis siguen en el DOM (el guardado las necesita)
    $$('#cfg-pop-body .cfg-panel').forEach((el) => el.classList.toggle('hidden', el.dataset.sec !== id));
    p.classList.remove('hidden');
    $('#cfg-pop-body').scrollTop = 0;
  }
  function cerrarSeccionConfig() {
    const p = $('#cfg-pop');
    if (!p || p.classList.contains('hidden')) return false;
    p.classList.add('hidden');
    return true;                                    // true = «he cerrado algo»
  }
  function cerrarConfig() {
    cerrarSeccionConfig();
    $('#config-modal').classList.add('hidden');
  }

  function configModal() {
    const c = state.config;
    $('#config-body').innerHTML = `<h2>▚ CONFIGURACIÓN</h2>
      <div class="cfg-menu">${CFG_SECCIONES.map((s) => `<button type="button" class="cfg-op" data-sec="${s.id}" style="--c:${s.color}">
        <span class="cfg-op-ic">${s.icono}</span><span class="cfg-op-tx">${esc(s.titulo)}</span><span class="cfg-op-go">›</span></button>`).join('')}</div>
      <div class="cfg-menu-pie">Elige un apartado. «Guardar» guarda TODA la configuración, estés en la sección que estés.</div>
      <div class="modal-btns"><button class="ghost" id="m-cancel">Cancelar</button><button id="m-save">Guardar</button></div>`;
    // LOS SEIS PANELES, DE UNA VEZ. No lo cambies a «solo el activo»: el guardado
    // de abajo lee campos de todas las secciones y los vacíos borrarían ajustes.
    cfgPopLayer();
    $('#cfg-pop-body').innerHTML = CFG_SECCIONES.map((s) =>
      `<section class="cfg-panel hidden" data-sec="${s.id}">${s.html(c)}</section>`).join('');
    $('#cfg-pop').classList.add('hidden');           // se abre siempre por el menú
    $('#config-modal').classList.remove('hidden');
    $$('#config-body .cfg-op').forEach((b) =>
      b.addEventListener('click', () => abrirSeccionConfig(b.dataset.sec)));
    $('#m-scan-open')?.addEventListener('click', () => { cerrarConfig(); render('home'); });
    // cerrar pulsando fuera del recuadro (en el fondo oscuro)
    $('#config-modal').onclick = (e) => { if (e.target === $('#config-modal')) cerrarConfig(); };
    // voces: filtradas por motor, sin duplicados, solo motores disponibles
    let voiceCat = null;
    function paintModalVoices() {
      const sel = $('#m-voice'), eng = $('#m-tts').value;
      if (!voiceCat) return;
      // en modo auto, solo motores realmente disponibles
      const groups = eng === 'auto'
        ? ['edge', 'elevenlabs', 'local'].filter((g) => voiceCat[g] && voiceCat[g].available)
        : [eng];
      const seen = new Set(); sel.innerHTML = '';
      groups.forEach((g) => (voiceCat[g]?.voices || []).forEach((v) => {
        const key = v.toLowerCase(); if (seen.has(key)) return; seen.add(key);
        const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o);
      }));
      if (!sel.children.length) { const o = document.createElement('option'); o.textContent = 'sin voces (instala el motor)'; sel.appendChild(o); }
      if (c.tts_voice && [...sel.options].some((o) => o.value === c.tts_voice)) sel.value = c.tts_voice;
    }
    api('/api/personalities').then((pers) => {
      const sel = $('#m-pers'); if (!sel || !pers) return;
      sel.innerHTML = Object.entries(pers).map(([k, v]) =>
        `<option value="${k}" ${c.personality === k ? 'selected' : ''}>${esc(v.name)}</option>`).join('');
      const paintDesc = () => { const d = pers[sel.value];
        $('#m-pers-desc').textContent = d ? d.desc : ''; };
      sel.onchange = paintDesc; paintDesc();
    });
    api('/api/voices').then((cat) => { voiceCat = cat; paintModalVoices(); });
    $('#m-tts').onchange = paintModalVoices;
    // Dispositivos de AUDIO: entrada (micros) del backend; salida del navegador.
    api('/api/audio_devices').then((r) => {
      const sel = $('#m-indev'); if (!sel || !r) return;
      (r.inputs || []).forEach((d) => {
        const o = document.createElement('option');
        o.value = d.name; o.textContent = d.name + (d.default ? ' · predeterminado' : '');
        sel.appendChild(o);
      });
      if (c.input_device) sel.value = c.input_device;
    });
    (async () => {
      const sel = $('#m-outdev');
      if (!sel || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      // pedir permiso de micro desbloquea las ETIQUETAS de los dispositivos de salida
      try { const st = await navigator.mediaDevices.getUserMedia({ audio: true }); st.getTracks().forEach((t) => t.stop()); } catch (e) { /* sin etiquetas, seguimos */ }
      try {
        const devs = await navigator.mediaDevices.enumerateDevices();
        const _seenOut = new Set();
        devs.filter((d) => d.kind === 'audiooutput')
          .filter((d) => d.deviceId !== 'default' && d.deviceId !== 'communications')
          .forEach((d, i) => {
            const key = d.groupId || d.label || d.deviceId;
            if (_seenOut.has(key)) return; _seenOut.add(key);
            const o = document.createElement('option');
            o.value = d.deviceId; o.textContent = d.label || ('Salida ' + (i + 1));
            sel.appendChild(o);
          });
        if (c.output_sink_id) sel.value = c.output_sink_id;
      } catch (e) { /* algunos webviews no exponen salidas */ }
    })();
    $('#m-voicetest').addEventListener('click', async () => {
      const btn = $('#m-voicetest');
      if (btn.classList.contains('testing')) return;   // ya está sonando
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tts_engine: $('#m-tts').value, tts_voice: $('#m-voice').value }) });
      startVoiceTest(btn);
      const r = await api('/api/tts_test', { method: 'POST' });
      if (r && r.spoke === false) { endVoiceTest(); pushLog('warn', 'No hay motor de voz TTS instalado. Ejecuta run.bat otra vez (instala edge-tts) o pon una voz «local».'); }
    });
    /* GUARDADO: uno solo para el botón del menú y el del pop up. Lee campos de las
       SEIS secciones a la vez — por eso los seis paneles están siempre en el DOM. */
    const guardar = async () => {
      const cfgApis = {};          // identificadores del apartado APIS (no son claves)
      const cfg = { operator_name: $('#m-op').value || 'Operador', devil_mode: true,
        personality: $('#m-pers') ? $('#m-pers').value : 'jarvis',
        reasoning_level: $('#m-reason') ? $('#m-reason').value : 'equilibrado',
        self_learning: $('#m-selflearn') ? $('#m-selflearn').checked : true,
        proactive: $('#m-proactive') ? $('#m-proactive').checked : true,
        proactive_speak: $('#m-proactivespeak') ? $('#m-proactivespeak').checked : true,
        pm_strong: $('#m-pmstrong') ? $('#m-pmstrong').checked : true,
        retrain_model: $('#m-retrain') ? $('#m-retrain').value : 'auto',
        perm_hardware: $('#m-hw') ? $('#m-hw').checked : true,
        perm_files: $('#m-permfiles') ? $('#m-permfiles').value : 'todo',
        perm_folders: $('#m-permfolders') ? $('#m-permfolders').value.split('\n').map((x) => x.trim()).filter(Boolean) : [],
        tts_engine: $('#m-tts').value, tts_voice: $('#m-voice').value, whisper_model: $('#m-whisper').value,
        input_device: $('#m-indev') ? $('#m-indev').value : '', output_sink_id: $('#m-outdev') ? $('#m-outdev').value : '',
        wake_enabled: $('#m-wake').checked, wake_word: $('#m-wakeword').value || ('despierta ' + ((state.config.assistant_name||'nexus').toLowerCase())),
        n8n_webhook_url: $('#m-n8n').value,
        n8n_base_url: $('#m-n8nbase').value || 'http://localhost:5678', wol_mac: $('#m-wol').value,
        homeassistant_url: $('#m-haurl') ? $('#m-haurl').value.trim() : '',
        known_devices: $('#m-devs') ? $('#m-devs').value.split('\n').map((l) => {
          const p = l.split('|').map((x) => x.trim()); if (!p[0]) return null;
          return { name: p[0], ip: p[1] || '', mac: p[2] || '', brand: (p[3] || '').toLowerCase() };
        }).filter(Boolean) : [] };
      window.__sinkId = cfg.output_sink_id || '';   // aplica la salida al instante
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) });
      // APARTADO APIS: se recorre la tabla, no hay una línea por clave. Los
      // secretos van a /api/secrets (secrets.json); los identificadores, a la
      // configuración normal. Un campo de clave vacío NO borra la guardada:
      // para quitarla se escribe un espacio.
      const sec = {};
      APIS.forEach((a) => {
        const el = $('#api-' + a.k); if (!el) return;
        const v = el.value.trim();
        if (a.tipo === 'ajuste') { cfgApis[a.k] = v; } else if (el.value !== '') { sec[a.k] = v; }
      });
      if (Object.keys(cfgApis).length) await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfgApis) });
      if (Object.keys(sec).length) await api('/api/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sec) });
      cerrarConfig(); await fetchAll(); pushLog('ok', 'Configuración actualizada');
    };
    $('#m-cancel').addEventListener('click', cerrarConfig);
    $('#m-save').addEventListener('click', guardar);
    $('#cfg-popsave').onclick = guardar;   // onclick: el pop up se reutiliza entre aperturas
  }

  // Cualquier enlace .ext (del chat, ventanitas, logs) → navegador REAL del PC
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a.ext');
    if (!a) return;
    e.preventDefault();
    api('/api/open_url', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: a.href }) });
  });

  /* ---------------- arranque ---------------- */
  function afterBoot() {
    clock(); connectWS(); fetchAll(); render('command');
    loadWeather(); setInterval(loadWeather, 15 * 60 * 1000);   // v23 (T15)
    refreshLocalModels();   // detecta modelos locales al inicio (queda en caché)
    refreshLlmStatus();     // ¿hay cerebro DE VERDAD? (probado, no supuesto)
    // saludo hablado al abrir; si el backend no tiene motor TTS, lo dice el navegador
    setTimeout(() => api('/api/greet', { method: 'POST' }).then((d) => {
      if (d && d.spoke === false && d.text) speakBrowser(d.text);
    }), 1000);
    miniReactor = window.WABIKS_REACTOR.attach($('#reactor-mini'), { particles: 30, link: 60 });
    setInterval(fetchAll, 30000);
    // nav
    $$('#nav a').forEach((a) => a.addEventListener('click', () => render(a.dataset.view)));
    // voz
    $('#orb').addEventListener('click', voice);
    $('#talk-btn').addEventListener('click', voice);
    // BLINDAJE: aunque la ventana pierda el foco (otra app, clic fuera), HABLA
    // CON nexus y MICRO ABIERTO siguen vivos SIEMPRE. Al volver: se reconecta
    // el enlace, se re-sincroniza el micro abierto y se libera un estado colgado.
    const reviveUI = () => {
      ensureWS();
      api('/api/config').then((c) => {
        if (!c) return; state.config = c;
        const b = $('#btn-auto'); if (b) b.classList.toggle('on', !!c.open_mic);
      });
      const stale = Date.now() - (window.__vstateTs || 0) > 15000;
      if (stale && (window.__vstate === 'thinking' || window.__vstate === 'listening')) setVoiceState('idle');
    };
    window.addEventListener('focus', reviveUI);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) reviveUI(); });
    document.addEventListener('pointerdown', ensureWS, true);  // el primer clic ya reconecta
    setInterval(ensureWS, 5000);                               // latido anti-caídas del enlace
    // Calentar la voz del navegador (respaldo): se elige UNA vez y se fija.
    if (window.speechSynthesis) {
      _initBrowserVoice();
      speechSynthesis.onvoiceschanged = _initBrowserVoice;
    }
    // Watchdog del estado «hablando»: si el backend deja el estado 'speaking' colgado
    // (audio que no llega) y no hay audio sonando, se libera para no quedar «Hablando…».
    setInterval(() => {
      if (window.__vstate === 'speaking'
          && Date.now() - (window.__vstateTs || 0) > 25000
          && !(_ttsAudio && !_ttsAudio.paused && !_ttsAudio.ended)) {
        setVoiceState('idle'); stopTTSGlow();
      }
    }, 5000);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'F9') { e.preventDefault(); voice(); }
      if (e.key === 'Escape') {
        if (closeTopMiniWin()) return;             // cierra la ventanita de arriba
        if (cerrarSeccionConfig()) return;         // del pop up de sección, al menú
        $('#node-panel').classList.add('hidden'); $('#config-modal').classList.add('hidden');
      }
    });
    // ---- MUTE doble ----
    // 🔇 IA: nexus sigue «hablando» (impulsos y todo) pero sin sonido
    const paintMuteAI = () => { const b = $('#btn-mute-ai');
      if (b) { b.classList.toggle('on', !!window.__muteAI);
        b.title = window.__muteAI ? 'nexus está en silencio — pulsa para oírle' : 'Silenciar a nexus'; } };
    $('#btn-mute-ai')?.addEventListener('click', () => {
      window.__muteAI = !window.__muteAI;
      localStorage.setItem('nexus_mute_ai', window.__muteAI ? '1' : '0');
      if (_ttsAudio) _ttsAudio.muted = window.__muteAI;   // aplica al audio EN CURSO
      paintMuteAI();
    });
    paintMuteAI();
    // 🎙⛔ YO: el micro abierto / wake deja de oírte (backend mic_muted)
    const paintMuteMe = () => { const b = $('#btn-mute-me');
      if (b) { b.classList.toggle('on', !!state.config.mic_muted);
        b.title = state.config.mic_muted ? 'Estás muteado — nexus no te oye' : 'Mutearme (que no me oiga)'; } };
    $('#btn-mute-me')?.addEventListener('click', async () => {
      const on = !state.config.mic_muted;
      state.config.mic_muted = on; paintMuteMe();
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mic_muted: on }) });
      pushLog(on ? 'warn' : 'ok', on ? 'Muteado: nexus NO te oye (ni micro abierto ni wake word)'
                                     : 'Mute quitado: nexus vuelve a oírte');
    });
    window.__paintMuteMe = paintMuteMe;
    paintMuteMe();

    // ---- VINCULAR MÓVIL (QR, funciona fuera de tu WiFi) ----
    $('#btn-link')?.addEventListener('click', openLinkModal);
    refreshDevices();   // pinta el badge si ya hay un móvil conectado al arrancar
    setInterval(refreshDevices, 45000);   // y se RE-SINCRONIZA solo (antes se quedaba desfasado)
    api('/api/jobs').then((d) => { state.jobs = d; paintJobsNav(); }).catch(() => {});

    // micro abierto — sincronizado con el estado real y honesto si no hay STT
    $('#btn-auto').addEventListener('click', async () => {
      const sttReal = state.status?.stt?.engine === 'whisper';
      if (!sttReal) {
        pushLog('warn', 'Micro abierto: necesita la voz real instalada (STT whisper). '
          + 'Ejecuta INSTALAR_nexus.bat o pip install -r requirements-voice.txt');
        $('#btn-auto').textContent = '∞ SIN VOZ REAL';
        setTimeout(() => { $('#btn-auto').textContent = '∞ MICRO ABIERTO'; }, 2500);
        return;
      }
      const on = !$('#btn-auto').classList.contains('on');
      $('#btn-auto').classList.toggle('on', on);
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ open_mic: on }) });
      pushLog(on ? 'ok' : 'info', on ? 'MICRO ABIERTO: habla cuando quieras, corto al silencio' : 'Micro abierto desactivado');
    });
    // config
    $('#btn-config').addEventListener('click', configModal);
    $('#btn-briefing').addEventListener('click', () => send('qué me toca hoy'));
    // botones de ventana (min / max / cerrar) — usan la API de pywebview del .exe
    const winApi = () => (window.pywebview && window.pywebview.api) || null;
    $('#btn-min').addEventListener('click', () => { const a = winApi(); if (a && a.minimize) a.minimize(); });
    $('#btn-max').addEventListener('click', () => { const a = winApi(); if (a && a.maximize) a.maximize(); });
    $('#btn-close').addEventListener('click', () => { const a = winApi(); if (a && a.close) a.close(); else window.close(); });
    setVoiceState('idle');
  }

  boot();
})();
