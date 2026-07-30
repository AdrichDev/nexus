/* ==========================================================
   nexus — Command Center SPA
   Router + vistas interactivas cableadas al backend real.
   ========================================================== */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  // Texto de la IA → HTML con URLs CLICABLES (se abren en el navegador real del PC)
  const linkify = (s) => esc(s).replace(/(https?:\/\/[^\s<>"«»)]+)/g,
    (u) => `<a href="${u}" class="ext" title="Abrir en el navegador">${u}</a>`);
  const api = (p, o) => fetch(p, o).then((r) => r.json()).catch(() => null);

  const state = { status: null, skills: [], config: {}, board: null, logs: [], chat: [], graph: null, metrics: {},
    llm: {}, llmCatalog: null };   // v24: estado REAL del cerebro + catálogo ya clasificado
  let ws, coreReactor = null, miniReactor = null, interactions = 0;

  /* ---------- catálogo de nodos/skills (para vista Skills y Nodos) ---------- */
  const CATALOG = {
    autoprovision: { label: 'AUTO-PROV', color: '#7cf6c0', ic: '🛠', desc: 'nexus levanta y conecta su propia infraestructura: Docker, n8n, Telegram y modelos Ollama.',
      actions: [['Revisar infraestructura', 'revisa tu infraestructura'], ['Levantar Docker', 'levanta docker'], ['Configurar n8n', 'configura n8n'], ['Preparar modelo…', 'prepara el modelo llama3.1', 1], ['Arreglar Ollama (modelos)', 'arregla ollama']] },
    media: { label: 'MÚSICA', color: '#1db954', ic: '🎵', desc: 'Reproduce canciones (YouTube/Spotify/Apple) y controla la música por voz.',
      actions: [['Poner una canción…', 'pon CANCION', 1], ['Pausa / Reanuda', 'pausa'], ['Siguiente canción', 'siguiente canción'], ['Canción anterior', 'canción anterior'], ['Parar música', 'para la música']] },
    games: { label: 'JUEGOS', color: '#66c0f4', ic: '🎮', desc: 'Steam: abrir, instalar, descargar y actualizar juegos, y abrir launchers.',
      actions: [['Jugar a…', 'juega a JUEGO', 1], ['Instalar en Steam…', 'instala JUEGO en steam', 1], ['Actualizar juego…', 'actualiza el juego JUEGO', 1], ['Abrir Steam', 'abre steam']] },
    places: { label: 'MAPAS/VIAJES', color: '#34a853', ic: '🗺', desc: 'Google Maps, rutas y búsquedas de vuelos, hoteles y vídeos.',
      actions: [['Cómo llego a…', 'cómo llego a DESTINO', 1], ['Ruta A → B…', 'ruta de ORIGEN a DESTINO', 1], ['Buscar vuelos…', 'busca vuelos a DESTINO', 1], ['Buscar hoteles…', 'busca hoteles en LUGAR por menos de 100 euros', 1], ['Abrir Maps', 'abre google maps']] },
    discord: { label: 'DISCORD', color: '#5865f2', ic: '💬', desc: 'Abrir Discord y publicar mensajes en un canal por webhook.',
      actions: [['Abrir Discord', 'abre discord'], ['Avisar en Discord…', 'manda a discord: MENSAJE', 1]] },
    domotica: { label: 'CASA', color: '#ffd23a', ic: '🏠', desc: 'Descubre y controla los dispositivos de tu red: TV (encender/apagar/volumen/canal/apps), Wake-on-LAN y toda tu domótica vía Home Assistant.',
      actions: [['Escanear la red', 'escanea la red'], ['Apagar la tele', 'apaga la tele'], ['Encender la tele', 'enciende la tele'], ['Subir volumen TV', 'sube el volumen'], ['Poner Netflix', 'pon netflix en la tele'], ['Encender el PC (WoL)', 'enciende el pc'], ['Luz del salón', 'enciende la luz del salón']] },
    coach: { label: 'COACH', color: '#22d3ee', ic: '◈', desc: 'Secretario/coach/PM: briefing, objetivos, checklists, recordatorios.',
      actions: [['Briefing del día', 'qué me toca hoy'], ['Mis objetivos', 'mis objetivos'], ['Planificar proyecto…', 'planifica el proyecto PROYECTO', 1], ['Estoy agobiado…', 'estoy agobiado']] },
    content_os: { label: 'CONTENT OS', color: '#ff7ac0', ic: '▶', desc: 'Instagram: analítica, inspiración, patrones y guiones.',
      actions: [['Analítica Instagram', 'analítica de instagram'], ['Inspiración de reel…', 'inspiración de @creador URL', 1], ['Analizar patrones', 'analiza los patrones'], ['Generar guion…', 'genera un guion sobre TEMA', 1], ['Ideas de contenido', 'dame ideas de contenido']] },
    google_workspace: { label: 'GOOGLE', color: '#ff5e5e', ic: '✉', desc: 'Gmail, Calendar y Tasks reales (OAuth).',
      actions: [['Leer mis correos', 'lee mis correos'], ['Calendario Google', 'qué tengo en el calendario de google'], ['Tareas de Google', 'mis tareas de google']] },
    system_pc: { label: 'SISTEMA', color: '#59ff9c', ic: '🖥', desc: 'Control total del PC: apps instaladas, procesos, capturas, WoL.',
      actions: [['Abrir aplicación…', 'abre APP', 1], ['Estado del sistema', 'estado del sistema'], ['Top procesos', 'lista los procesos'], ['Encender el PC (WoL)', 'enciende el ordenador']] },
    tasks_board: { label: 'TABLERO', color: '#ffb14d', ic: '▦', desc: 'Kanban con toques de atención y matriz de urgencia.',
      actions: [['Ver tablero', 'ver tablero'], ['Crear tarea…', 'crea la tarea TITULO para el viernes', 1], ['¿Voy retrasado?', 'qué tareas van retrasadas'], ['Organizar por urgencia', 'organiza mis tareas por urgencia']] },
    devils_advocate: { label: 'DEVIL', color: '#ff3355', ic: '😈', desc: 'Abogado del diablo: SIEMPRE activo. Cuestiona, señala riesgos y depura el razonamiento antes de responder.',
      actions: [['Criticar una idea…', 'abogado del diablo: IDEA', 1]] },
    research: { label: 'RESEARCH', color: '#4dffd8', ic: '🔎', desc: 'Investigación web con fuentes, tendencias y economía.',
      actions: [['Investigar…', 'investiga TEMA y hazme un informe', 1], ['Tendencias…', 'tendencias de NICHO', 1], ['Informe económico', 'informe económico']] },
    datos: { label: 'DATOS', color: '#7d9dff', ic: '📊', desc: 'BDs externas y dashboards estilo Power BI.',
      actions: [['Conectar BD…', 'conéctate a la base de datos postgresql://user:pass@host:5432/db', 1], ['¿Qué tablas hay?', 'qué tablas hay'], ['Dashboard de tabla…', 'dashboard de la tabla TABLA', 1]] },
    memory_graph: { label: 'MEMORIA', color: '#4dd8ff', ic: '▣', desc: 'Grafo de notas + Postgres/pgvector con RAG semántico.',
      actions: [['Estado de la memoria', 'estado de la memoria'], ['Aprender documento…', 'aprende el documento RUTA', 1], ['Aprender carpeta…', 'aprende la carpeta RUTA', 1]] },
    files: { label: 'ARCHIVOS', color: '#b07dff', ic: '🗂', desc: 'Explorar, buscar, leer, resumir, crear carpetas/archivos.',
      actions: [['Explorar carpeta…', 'explora la carpeta RUTA', 1], ['Crear carpeta…', 'crea la carpeta RUTA', 1], ['Resumir documento…', 'resume el documento RUTA', 1]] },
    billing: { label: 'FACTURAS', color: '#ffe74d', ic: '🧾', desc: 'Facturación por voz con datos en memoria.',
      actions: [['Ver facturas', 'ver facturas'], ['Nueva factura…', 'hazle una factura a CLIENTE por CONCEPTO de 100 euros', 1]] },
    ai_media: { label: 'IA MEDIA', color: '#d84dff', ic: '✦', desc: 'Imágenes, transcripción de audios y búsqueda web.',
      actions: [['Transcribir audio…', 'transcribe el audio RUTA', 1], ['Buscar en internet…', 'busca en internet TEMA', 1], ['Generar imagen…', 'genera una imagen de TEMA', 1]] },
    tools: { label: 'TOOLS', color: '#7fe9f7', ic: '⚗', desc: 'Clima, alarmas, matemáticas SymPy, ping.',
      actions: [['Tiempo en Madrid', 'qué tiempo hace en Madrid'], ['Estado de la red', 'estado de la red'], ['¿Qué hora es?', 'qué hora es']] },
    comms: { label: 'COMMS', color: '#ffd23e', ic: '💬', desc: 'Mensajes, agenda y captura de tareas.',
      actions: [['Ver mensajes', 'ver mensajes'], ['Capturar tareas', 'captura de tareas']] },
    n8n_flows: { label: 'N8N', color: '#ff8c42', ic: '⚡', desc: 'Flujos n8n y WhatsApp a través de ellos.',
      actions: [['Enviar WhatsApp…', 'envía un whatsapp a NOMBRE diciendo MENSAJE', 1], ['Lanzar flujo…', 'lanza el flujo NOMBRE', 1]] },
    dev_knowledge: { label: 'DEV LIB', color: '#00e0b8', ic: '📚', desc: 'Biblioteca de skills de openClaw/Gru (SDD, PR, judgment-day...).',
      actions: [['Ver biblioteca', 'qué skills de desarrollo tienes'], ['Aplicar skill…', 'aplica la skill sdd-spec a TAREA', 1]] },
    mcp_hands: { label: 'MANOS MCP', color: '#a0ffcc', ic: '🖐', desc: 'Conectores MCP externos (filesystem, github...) como Cowork.',
      actions: [['Qué manos tengo', 'qué manos tienes'], ['Recargar conectores', 'recarga los conectores'], ['Usar conector…', 'usa filesystem read_file con RUTA', 1]] },
  };

  /* ---------------- boot ---------------- */
  const BOOT = [
    'nexus BIOS v1.0 — Wide-Band Intelligent Knowledge System',
    '> Arranque de reactor ............ [ONLINE]',
    '> Núcleo orquestador ............. [OK]',
    '> Minions (skills) cargados ...... [OK]',
    '> Memoria pgvector + grafo ....... [OK]',
    '> Índice de aplicaciones ......... [OK]',
    '> Pipeline de voz STT/LLM/TTS .... [OK]',
    '> Enlaces cifrados ............... [SECURE]',
    '> Command Center ................. [EN LÍNEA]',
    '', '  TODOS LOS SISTEMAS NOMINALES. A SUS ÓRDENES, OPERADOR.',
  ];
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
  function pushLog(level, msg) {
    state.logs.push({ t: new Date().toTimeString().slice(0, 8), level, msg });
    state.logs = state.logs.slice(-200);
    if (current === 'monitor' || current === 'command') renderLogsInto();
  }
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
    else if (current && current !== 'chat' && current !== 'memory' && current !== 'knowledge') render(current);
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
    if (rt.active) {
      el.className = 'ac-rt';
      el.innerHTML = `<b>✓ Probado</b> · ${esc(rt.display || rt.model || '')} respondió en ${rt.latency_ms || 0} ms`;
    } else if (rt.checked_at) {
      el.className = 'ac-rt bad';
      el.innerHTML = `<b>⚠ Sin funcionar</b> · ${esc(rt.error || 'no ha respondido a la prueba')}`;
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
  function orbHTML(big) {
    // 12 puntos en anillo + núcleo; cada punto con su posición y desfase → onda.
    const N = 12, R = big ? 24 : 10;
    let dots = '';
    for (let i = 0; i < N; i++) {
      const a = (i / N) * 2 * Math.PI;
      const tx = (Math.cos(a) * R).toFixed(1) + 'px';
      const ty = (Math.sin(a) * R).toFixed(1) + 'px';
      const d = (-(i / N) * 1.1).toFixed(2) + 's';
      dots += `<i style="--tx:${tx};--ty:${ty};animation-delay:${d}"></i>`;
    }
    return `<span class="orb-load${big ? ' big' : ''}"><b></b>${dots}</span>`;
  }
  window.orbHTML = orbHTML;

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
    // Catálogos REALES (julio 2026) sacados de las docs oficiales de cada API.
    openai: ['gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.5-pro', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5-mini', 'o3-pro', 'o3', 'gpt-4.1', 'gpt-4.1-mini'],
    anthropic: ['claude-fable-5', 'claude-opus-4-8', 'claude-sonnet-5', 'claude-haiku-4-5'],
    gemini: ['gemini-3.5-flash', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite', 'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'],
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

  async function mountContentOS() {
    const box = $('#cos'); if (!box) return;
    const d = await api('/api/contentos');
    if (!d) { box.innerHTML = '<div class="empty">No he podido cargar Content OS.</div>'; return; }
    const k = d.kpis || {}, na = d.next_action || {}, ev = d.evidence || {};
    const delta = (v) => `<span class="cos-delta ${v >= 0 ? 'up' : 'dn'}">${v >= 0 ? '▲' : '▼'} ${Math.abs(v)}%</span>`;
    const confCls = { 'consistente': 'c', 'prometedora': 'p', 'observación': 'o' };
    const cal = (d.calendar || []).map((p) => `<div class="cos-cal-item">
        <span class="cos-cal-n">${String(p.n).padStart(2, '0')}</span>
        <div class="cos-cal-body"><b>${esc(p.title)}</b><small>${esc(p.type)}</small></div>
        <div class="cos-cal-meta"><span>${esc(p.when)}</span><em class="cos-badge">${esc(p.status)}</em></div>
      </div>`).join('') || '<div class="empty">Sin publicaciones planificadas.</div>';
    const ideas = (d.ideas || []).map((i) => `<div class="cos-idea">✦ ${esc(i)}</div>`).join('');
    const insp = (d.inspirations || []).map((i) => `<div class="cos-insp"><b>${esc(i.src || '')}</b> ${esc(i.note || '')}</div>`).join('') || '<div class="empty">—</div>';
    const learn = (d.learnings || []).map((l) => `<div class="cos-learn ${confCls[l.conf] || 'o'}"><span class="cos-dot"></span><div>${esc(l.text)}<em>${esc(l.conf)}</em></div></div>`).join('');
    const best = (d.best || []).map((b) => `<div class="cos-rank up">▲ ${esc(b.name)} <span>${b.eng}</span></div>`).join('');
    const worst = (d.worst || []).map((b) => `<div class="cos-rank dn">▼ ${esc(b.name)} <span>${b.eng}</span></div>`).join('');
    box.innerHTML = `
      <div class="cos-head">
        <div><div class="cos-hello">Hola, ${esc(d.username || d.operator || 'Ruben')}.</div>
          <div class="cos-sub">Content OS · Inteligencia de Instagram</div></div>
        <span class="cos-conn ${d.connected ? 'ok' : 'demo'}">${d.connected ? '● Instagram conectado' : '○ demo (conecta IG en ⚙)'}</span>
      </div>
      <div class="cos-next">
        <div class="cos-next-ic">✦</div>
        <div class="cos-next-body">
          <div class="cos-tag">${esc(na.signal || 'Señal')}</div>
          <h3>${esc(na.title || '')}</h3><p>${esc(na.detail || '')}</p>
          <span class="cos-mini">${na.analyzed || 0} publicaciones analizadas</span>
        </div>
      </div>
      <div class="cos-kpis">
        ${cosKpi('Seguidores', fmtN(k.followers), delta(k.followers_delta || 0), 'últimos 30 días')}
        ${cosKpi('Alcance mensual', fmtN(k.reach_month), delta(k.reach_delta || 0), 'vs. periodo previo')}
        ${cosKpi('Retención media', (k.retention || 0) + '%', delta(k.retention_delta || 0), 'reels')}
        ${cosKpi('Experimentos', String(k.experiments || 0), '<span class="cos-mini2">activos</span>', 'en curso')}
      </div>
      <div class="cos-grid">
        <div class="panel cos-panel"><h2>Plan de contenido</h2><div class="cos-cal">${cal}</div></div>
        <div class="panel cos-panel"><h2>Salud del sistema</h2>
          <div class="cos-health">
            <div class="cos-ring" style="--p:${ev.complete_pct || 0}"><b>${ev.complete_pct || 0}%</b><small>datos</small></div>
            <div class="cos-ev">
              <div><span class="cos-dot c"></span><b>${ev.consistent || 0}</b> consistentes</div>
              <div><span class="cos-dot p"></span><b>${ev.promising || 0}</b> prometedoras</div>
              <div><span class="cos-dot o"></span><b>${ev.observations || 0}</b> observaciones</div>
            </div>
          </div>
        </div>
        <div class="panel cos-panel"><h2>Lluvia de ideas</h2>
          <div class="cos-gen"><input id="cos-idea-in" placeholder="tema (opcional)…"><button id="cos-idea-btn">✦ Generar idea IA</button></div>
          <div id="cos-ideas" class="cos-ideas">${ideas}</div>
        </div>
        <div class="panel cos-panel"><h2>Aprendizajes <span class="cos-h2sub">evidencia acumulada</span></h2><div class="cos-learns">${learn}</div></div>
        <div class="panel cos-panel"><h2>Inspiraciones</h2><div class="cos-insps">${insp}</div></div>
        <div class="panel cos-panel"><h2>Guion con IA</h2>
          <div class="cos-gen"><input id="cos-script-in" placeholder="tema del reel…"><button id="cos-script-btn">▶ Generar guion</button></div>
          <div id="cos-script" class="cos-script"></div>
        </div>
      </div>
      <div class="cos-charts">
        ${cosChart('Seguidores (30 días)', 'ch-foll')}
        ${cosChart('Alcance por publicación', 'ch-reach')}
        ${cosChart('Rendimiento vs. mediana (desviación)', 'ch-dev')}
        ${cosChart('Mezcla de contenido', 'ch-pie')}
        ${cosChart('Correlación · hora de publicación vs. engagement', 'ch-scatter')}
        <div class="panel cos-chart"><h2>Mejores y peores</h2><div class="cos-ranks">${best}${worst}</div></div>
      </div>`;
    // dibujar gráficos (tras el layout)
    const C = window.WABIKS_CHARTS, ch = d.charts || {};
    requestAnimationFrame(() => {
      try {
        C.line($('#ch-foll'), ch.followers || {});
        C.bars($('#ch-reach'), ch.reach || {});
        C.deviation($('#ch-dev'), ch.deviation || []);
        C.pie($('#ch-pie'), ch.pie || []);
        C.scatter($('#ch-scatter'), ch.scatter || [], { xlabel: 'hora del día' });
      } catch (e) { /* noop */ }
    });
    // generar idea
    $('#cos-idea-btn').addEventListener('click', async () => {
      const btn = $('#cos-idea-btn'); btn.disabled = true; btn.textContent = '…pensando';
      const r = await api('/api/contentos/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'idea', topic: $('#cos-idea-in').value }) });
      if (r && r.text) $('#cos-ideas').insertAdjacentHTML('afterbegin', `<div class="cos-idea new">✦ ${esc(r.text)}</div>`);
      btn.disabled = false; btn.textContent = '✦ Generar idea IA'; $('#cos-idea-in').value = '';
    });
    // generar guion
    $('#cos-script-btn').addEventListener('click', async () => {
      const btn = $('#cos-script-btn'), out = $('#cos-script');
      btn.disabled = true; btn.textContent = '…escribiendo'; out.textContent = '';
      const r = await api('/api/contentos/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: 'script', topic: $('#cos-script-in').value }) });
      out.textContent = (r && r.text) || 'No pude generar el guion.';
      btn.disabled = false; btn.textContent = '▶ Generar guion';
    });
  }
  const cosKpi = (lbl, val, delta, sub) => `<div class="cos-kpi"><div class="cos-kpi-l">${lbl}</div><div class="cos-kpi-v">${val}</div><div class="cos-kpi-d">${delta} ${sub}</div></div>`;
  const cosChart = (title, id) => `<div class="panel cos-chart"><h2>${title}</h2><canvas id="${id}"></canvas></div>`;
  const fmtN = (n) => { n = Number(n) || 0; return n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n); };

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

  views.knowledge = () => `<div class="section-title">Nodos de conocimiento</div>
    <div class="section-sub">nexus en el centro, cada skill en su órbita, y tus notas de memoria como nodos. Pulsa varios: cada uno abre su mini-ventana (✕ para cerrar, arrástralas donde quieras).</div>
    <div id="kn-stage"><canvas id="kn-links"></canvas></div>`;

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

  views.calendar = () => `<div class="section-title">Agenda</div>
    <div class="section-sub">Google Calendar real + tareas del tablero con fecha.</div>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:14px">
      <div class="panel"><h2>Google Calendar <span class="link" id="cal-refresh">actualizar</span></h2>
        <div id="cal-google"><div class="empty">cargando…</div></div></div>
      <div class="panel"><h2>Tareas con fecha</h2><div id="cal-tasks"><div class="empty">cargando…</div></div></div>
    </div>`;

  async function loadCalendar() {
    const data = await api('/api/calendar');
    const g = $('#cal-google'), t = $('#cal-tasks');
    if (!g || !data) return;
    if (data.google_status === 'ok') {
      g.innerHTML = data.google.length
        ? data.google.map((e) => `<div class="mnote"><span>◉ ${esc(e.what)}</span><span>${esc(e.when)}</span></div>`).join('')
        : '<div class="empty">Calendario despejado — sin eventos próximos.</div>';
    } else if (data.google_status === 'no conectado') {
      g.innerHTML = '<div class="empty">Google no conectado.<br>Pon el Client ID y Secret en ⚙ (sección Google),<br>luego pide «qué tengo en el calendario de google»<br>y autoriza en el navegador (solo una vez).</div>';
    } else if (data.google_status === 'sin autorizar') {
      g.innerHTML = '<div class="empty">Credenciales puestas, falta autorizar.<br>Di «qué tengo en el calendario de google»<br>y se abrirá el navegador para dar permiso (una vez).</div>';
    } else {
      g.innerHTML = `<div class="empty">Calendario no disponible ahora mismo.<br>Reintenta con «Actualizar».</div>`;
    }
    const today = new Date().toISOString().slice(0, 10);
    const tasks = (data.tasks || []).sort((a, c) => a.due.localeCompare(c.due));
    t.innerHTML = tasks.length
      ? tasks.map((x) => `<div class="mnote"><span style="color:${x.due < today && x.state !== 'completada' ? 'var(--err)' : 'var(--txt)'}">${x.state === 'completada' ? '✓ ' : '○ '}${esc(x.title)}</span><span>${x.due}${x.priority === 'alta' ? ' · ⚡' : ''}</span></div>`).join('')
      : '<div class="empty">Sin tareas con fecha. «crea la tarea X para el viernes».</div>';
  }

  views.memory = () => {
    const m = state.status?.memory || {};
    return `<div class="section-title">Memoria</div><div class="section-sub">Grafo de notas (interactivo, estilo Graphify) + Postgres/pgvector con RAG semántico.</div>
      <div class="grid" style="grid-template-columns:200px 200px 1fr;gap:14px">
        <div class="panel"><h2>Vector store</h2>
          <div style="font-size:24px;color:${m.db_online ? 'var(--ok)' : 'var(--txt-dim)'};font-weight:600">${m.db_online ? 'ONLINE' : 'OFFLINE'}</div>
          <div style="color:var(--txt-dim);font-size:11px;margin-top:6px">${esc(m.backend || '')}<br>${m.graph_notes || 0} notas</div>
        </div>
        <div class="panel"><h2>Operador</h2>
          <div style="font-size:13px;color:var(--cy-soft)">${esc(state.config.operator_name || 'Operador')}</div>
          <div style="color:var(--txt-dim);font-size:11px;margin-top:6px">${interactions} interacciones<br>${esc(state.config.llm_provider || '')}</div>
        </div>
        <div class="panel"><h2>Consultar / alimentar memoria</h2>
          <div style="display:flex;gap:8px"><input id="mem-q" placeholder="qué recuerdas de…" style="flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--txt);font-family:inherit;padding:9px;border-radius:6px;outline:none"><button id="mem-go" style="background:var(--cy);border:none;color:#04121a;font-weight:700;padding:0 16px;border-radius:6px;cursor:pointer">▶</button></div>
          <div style="display:flex;gap:8px;margin-top:8px"><input id="mem-learn" placeholder="ruta de un archivo o carpeta a aprender…" style="flex:1;background:var(--panel2);border:1px solid var(--line);color:var(--txt);font-family:inherit;padding:9px;border-radius:6px;outline:none"><button id="mem-learn-go" style="background:transparent;border:1px solid var(--cy);color:var(--cy);font-weight:700;font-family:inherit;padding:0 12px;border-radius:6px;cursor:pointer">Aprender</button></div>
          <div id="mem-answer" style="font-size:12px;color:var(--cy-soft);margin-top:8px;line-height:1.5;max-height:60px;overflow:auto"></div>
          <div style="font-size:10.5px;color:var(--txt-dim);margin-top:6px">💡 Buzón automático: deja archivos (.txt/.md/.pdf→texto/código) en <b>data/memory/inbox/</b> y los aprende solo.</div>
        </div>
      </div>
      <div class="panel" style="margin-top:14px"><h2>Grafo de conocimiento <span class="link" id="mem-reload">recargar</span></h2>
        <div id="mem-graph-wrap"><canvas id="mem-graph"></canvas><div id="mem-tip"></div></div></div>`;
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
    // Grafo interactivo con GRUPOS: cada grupo de notas enlazadas comparte
    // COLOR y se mueve EN BLOQUE al arrastrar cualquiera de sus nodos.
    const g = await api('/api/graph') || { nodes: [], edges: [] };
    const canvas = $('#mem-graph'); if (!canvas) return;
    if (!g.nodes.length) { $('#mem-tip').textContent = 'Memoria vacía — enséñale algo: «recuerda que…» o «aprende el documento…».'; return; }
    cancelAnimationFrame(memGraphRaf);
    const W = canvas.width = canvas.offsetWidth, H = canvas.height = 380;
    const groupOf = computeMemGroups(g.nodes, g.edges);
    const nodes = g.nodes.map((n, i) => ({ id: n, group: groupOf[n], color: memGroupColor[n] || '#22d3ee',
      x: W / 2 + Math.cos(i) * 120 + (i * 37 % 200 - 100), y: H / 2 + Math.sin(i) * 90 + (i * 53 % 160 - 80), vx: 0, vy: 0 }));
    const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
    const edges = (g.edges || []).filter((e) => idx[e[0]] != null && idx[e[1]] != null).map((e) => [idx[e[0]], idx[e[1]]]);
    const ctx = canvas.getContext('2d');
    let hover = -1, dragI = -1, dragMoved = false, lx = 0, ly = 0, iter = 0;
    const mpos = (ev) => { const r = canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
    canvas.onmousedown = (ev) => {
      const [mx, my] = mpos(ev);
      dragI = nodes.findIndex((n) => Math.hypot(n.x - mx, n.y - my) < 16);
      dragMoved = false; lx = mx; ly = my;
      if (dragI >= 0) { ev.preventDefault(); canvas.style.cursor = 'grabbing'; }
    };
    canvas.onmousemove = (ev) => {
      const [mx, my] = mpos(ev);
      if (dragI >= 0) {                        // arrastre: TODO su grupo le sigue
        const dx = mx - lx, dy = my - ly; lx = mx; ly = my;
        if (dx || dy) dragMoved = true;
        const grp = nodes[dragI].group;
        for (const n of nodes) {
          if (n.group === grp) {
            n.x = Math.max(12, Math.min(W - 12, n.x + dx));
            n.y = Math.max(12, Math.min(H - 12, n.y + dy));
            n.vx = n.vy = 0;
          }
        }
        return;
      }
      hover = nodes.findIndex((n) => Math.hypot(n.x - mx, n.y - my) < 16);
      $('#mem-tip').textContent = hover >= 0
        ? `«${nodes[hover].id}» — clic: su ventana · arrastra: mueve todo su grupo` : '';
      canvas.style.cursor = hover >= 0 ? 'grab' : 'default';
    };
    canvas.onmouseup = () => { dragI = -1; };
    canvas.onmouseleave = () => { dragI = -1; hover = -1; };
    canvas.onclick = () => { if (hover >= 0 && !dragMoved) openNote(nodes[hover].id); dragMoved = false; };
    function step() {
      // física SOLO mientras se asienta (y nunca durante un arrastre)
      if (iter < 400 && dragI < 0) {
        iter++;
        for (let i = 0; i < nodes.length; i++) {
          let fx = 0, fy = 0;
          for (let j = 0; j < nodes.length; j++) { if (i === j) continue;
            const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y, d = Math.hypot(dx, dy) || 1;
            const rep = 1400 / (d * d); fx += dx / d * rep; fy += dy / d * rep; }
          fx += (W / 2 - nodes[i].x) * 0.008; fy += (H / 2 - nodes[i].y) * 0.008;
          nodes[i].vx = (nodes[i].vx + fx) * 0.82; nodes[i].vy = (nodes[i].vy + fy) * 0.82;
        }
        for (const [a, b] of edges) {
          const dx = nodes[b].x - nodes[a].x, dy = nodes[b].y - nodes[a].y;
          nodes[a].vx += dx * 0.01; nodes[a].vy += dy * 0.01; nodes[b].vx -= dx * 0.01; nodes[b].vy -= dy * 0.01;
        }
        for (const n of nodes) { n.x = Math.max(20, Math.min(W - 20, n.x + n.vx)); n.y = Math.max(20, Math.min(H - 20, n.y + n.vy)); }
      }
      ctx.clearRect(0, 0, W, H);
      ctx.lineWidth = 1.2;
      for (const [a, b] of edges) {           // arista del color de su grupo
        ctx.strokeStyle = nodes[a].color + '66';
        ctx.beginPath(); ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y); ctx.stroke();
      }
      nodes.forEach((n, i) => {
        ctx.beginPath(); ctx.arc(n.x, n.y, i === hover ? 9 : 6, 0, Math.PI * 2);
        ctx.fillStyle = n.color; ctx.shadowColor = n.color; ctx.shadowBlur = i === hover ? 14 : 8;
        ctx.fill(); ctx.shadowBlur = 0;
        if (i === hover) { ctx.strokeStyle = '#eafcff'; ctx.lineWidth = 1.4; ctx.stroke(); }
        ctx.fillStyle = 'rgba(207,228,245,.85)'; ctx.font = '10px monospace'; ctx.textAlign = 'center';
        ctx.fillText(n.id.length > 16 ? n.id.slice(0, 15) + '…' : n.id, n.x, n.y - 11);
      });
      memGraphRaf = requestAnimationFrame(step);   // bucle continuo (arrastre fluido)
    }
    step();
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
  const ovCard = (ic, name, sub, on) => `<div class="ov-card"><div class="ov-ic">${ic}</div><div><b>${name}</b><small>${esc(sub)}</small></div><span class="st ${on ? 'on' : 'off'}">${on ? 'ON' : 'OFF'}</span></div>`;
  const GCOL = { cpu: '#22e6ff', ram: '#4d9bff', disk: '#ffd23a', gpu: '#4dff9e' };
  const gauge = (k, label) => `<div class="gauge"><div class="ring" id="g-${k}" style="--gc:${GCOL[k] || '#22d3ee'}"><b id="gv-${k}" style="color:${GCOL[k] || '#eaf6ff'}">0%</b></div><div class="glabel">${label}</div></div>`;
  const kpi = (lbl, val, delta, cy) => `<div class="kpi"><div class="lbl">${lbl}</div><div class="val ${cy ? 'cy' : ''}">${val}</div><div class="delta">${delta}</div></div>`;
  const qc = (i, label, cmd, isPrompt, view) => `<div class="qc" data-cmd="${cmd ? esc(cmd) : ''}" data-prompt="${isPrompt ? 1 : ''}" data-view="${view || ''}"><i>${i}</i> ${label}</div>`;

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

  /* ---------------- CASA · Dispositivos (Mis dispositivos / Detectados / En la red) ----------------
     UI según el mockup aprobado por Adri: una acción clara por tarjeta (+ Añadir / ★ / ⏻),
     nombre EDITABLE (para que la voz lo entienda), chatarra técnica (IP·MAC) tras un
     interruptor, y NADA de doble-clic oculto. «Detectados» = controlable aún sin añadir;
     «En la red» = informativo y plegado. Mis dispositivos PERSISTEN en settings (my_devices). */
  let _devList = [];            // dispositivos del último escaneo (índice → objeto)
  let _devOpen = null;          // dispositivo cuyo panel de control está abierto
  let _devScanning = false;
  let _devTech = false;         // interruptor «detalles técnicos (IP · MAC)»
  try { _devTech = localStorage.getItem('wbk_devtech') === '1'; } catch (e) { /* webview sin storage */ }

  const myDevices = () => (state.config && Array.isArray(state.config.my_devices)) ? state.config.my_devices : [];
  const devKey = (d) => d.entity_id || ((d.mac || '').toUpperCase()) || d.ip || (d.name || '');
  async function saveMyDevices(list) {
    state.config.my_devices = list;
    await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ my_devices: list }) });
  }
  function mineEntry(key) { return myDevices().find((m) => m.key === key); }
  async function addToMine(d) {
    if (!d || mineEntry(devKey(d))) return;
    const list = myDevices().slice();
    list.push({ key: devKey(d), name: d.name || d.type || 'Dispositivo', icon: d.icon || '📟',
                kind: d.kind || 'other', brand: d.brand || '', ip: d.ip || '', mac: d.mac || '',
                entity_id: d.entity_id || '', domain: d.domain || '' });
    await saveMyDevices(list);
    devToast(`★ «${(d.name || d.type)}» añadido a Mis dispositivos — nexus ya lo controla por voz.`);
    renderDevGrid(_devList);
  }
  async function removeFromMine(key, name) {
    await saveMyDevices(myDevices().filter((m) => m.key !== key));
    devToast(`Quitado de Mis dispositivos: «${name || key}». Sigue en Detectados si el escáner lo ve.`);
    renderDevGrid(_devList);
  }
  function devToast(txt) { const el = $('#dev-msg'); if (el) { el.textContent = txt; el.classList.add('show'); clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove('show'), 6000); } }

  function mountHome() {
    const btn = $('#dev-scan');
    if (btn && !btn._w) { btn._w = 1; btn.addEventListener('click', scanDevices); }
    const cl = $('#dev-mclose');
    if (cl && !cl._w) { cl._w = 1; cl.addEventListener('click', closeDevModal); }
    const md = $('#dev-modal');
    if (md && !md._w) { md._w = 1; md.addEventListener('click', (e) => { if (e.target === md) closeDevModal(); }); }
    const tg = $('#dev-tech-toggle');
    if (tg) {
      tg.checked = _devTech;
      if (!tg._w) { tg._w = 1; tg.addEventListener('change', () => { _devTech = tg.checked; try { localStorage.setItem('wbk_devtech', _devTech ? '1' : '0'); } catch (e) { /* */ } renderDevGrid(_devList); }); }
    }
    renderHA();                                        // panel de Home Assistant (luces/enchufes)
    if (state.devices) renderDevGrid(state.devices);   // pinta lo último escaneado
    else scanDevices();                                // primera vez: rastrea solo
  }

  /* ---- Home Assistant: instalar / conectar / estado ---- */
  async function renderHA() {
    const box = $('#dev-ha'); if (!box) return;
    box.innerHTML = '<div class="ha-card"><span class="dots">comprobando Home Assistant</span></div>';
    let s = null;
    try { s = await api('/api/home/ha_status'); } catch (e) { /* */ }
    if (!s) { box.innerHTML = ''; return; }
    const connected = s.running && s.has_token;
    if (connected) {
      box.innerHTML = `<div class="ha-card ok">
        <span class="ha-ic">🏠</span>
        <div class="ha-tx"><b>Home Assistant conectado ✓</b><span>${s.entities} ${s.entities === 1 ? 'aparato controlable' : 'aparatos controlables'} · ${esc(s.url)}</span></div>
        <button class="ha-btn ghost" id="ha-add">+ Añadir aparatos</button>
        <button class="ha-btn ghost" id="ha-open">Abrir</button>
        <button class="ha-btn ghost" id="ha-edit">Reconfigurar</button></div>`;
      $('#ha-add')?.addEventListener('click', () => openHAPath('/config/integrations/dashboard'));
      $('#ha-open')?.addEventListener('click', () => openHAPath(''));
      $('#ha-edit')?.addEventListener('click', () => renderHAForm(s));
      return;
    }
    if (s.running && !s.has_token) { renderHAForm(s, 'running'); return; }
    // no está en marcha
    box.innerHTML = `<div class="ha-card warn">
      <span class="ha-ic">💡</span>
      <div class="ha-tx"><b>Las luces y enchufes necesitan Home Assistant</b>
        <span>Es el mando universal de la domótica (gratis). Las TVs ya funcionan sin él.</span></div>
      ${s.docker
        ? '<button class="ha-btn" id="ha-install">⬇ Instalar Home Assistant</button>'
        : '<a class="ha-btn" href="https://www.docker.com/products/docker-desktop/" target="_blank">Instalar Docker</a>'}
      <button class="ha-btn ghost" id="ha-manual">Ya lo tengo</button></div>
      <div id="ha-out" class="ha-out"></div>`;
    $('#ha-install')?.addEventListener('click', installHA);
    $('#ha-manual')?.addEventListener('click', () => renderHAForm(s, 'manual'));
  }
  // Abre una URL (o una sub-ruta de HA) en el navegador real del PC.
  function haBase() {
    const v = ($('#ha-url')?.value || '').trim() || (state.config && state.config.homeassistant_url) || 'http://localhost:8123';
    return v.replace(/\/+$/, '');
  }
  async function openHAPath(path) {
    const url = haBase() + (path || '');
    try { await api('/api/open_url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) }); } catch (e) { /* */ }
  }
  // ASISTENTE GUIADO (3 pasos) — claro y a prueba de perderse.
  function renderHAForm(s, mode) {
    const box = $('#dev-ha'); if (!box) return;
    box.innerHTML = `<div class="ha-wiz">
      <div class="ha-wiz-head"><span class="ha-ic">🏠</span>
        <div><b>Conectar Home Assistant</b><span>Es el mando universal de tus luces, enchufes y persianas. Sigue estos 3 pasos — te llevo de la mano.</span></div>
      </div>

      <div class="ha-step">
        <div class="ha-num">1</div>
        <div class="ha-body">
          <b>Abre Home Assistant y añade tus aparatos</b>
          <p>Se abre en tu navegador. Ve a <b>Ajustes → Dispositivos y servicios → Añadir integración</b> y busca tu marca (Philips Hue, Tuya, Shelly, Sonoff, Xiaomi…). Muchos se detectan solos.</p>
          <div class="ha-row">
            <button class="ha-btn" id="ha-open-dev">↗ Abrir «Añadir integración»</button>
            <button class="ha-btn ghost" id="ha-open-home">Abrir Home Assistant</button>
          </div>
        </div>
      </div>

      <div class="ha-step">
        <div class="ha-num">2</div>
        <div class="ha-body">
          <b>Crea un «token de acceso de larga duración»</b>
          <p>Es la llave para que nexus controle HA. En Home Assistant: pincha en <b>tu nombre</b> (abajo a la izquierda) → pestaña <b>Seguridad</b> → baja del todo hasta <b>«Tokens de acceso de larga duración»</b> → <b>Crear token</b> → ponle un nombre (p. ej. nexus) → <b>cópialo</b> (solo se muestra una vez).</p>
          <div class="ha-row"><button class="ha-btn ghost" id="ha-open-prof">↗ Abrir mi perfil (Seguridad)</button></div>
        </div>
      </div>

      <div class="ha-step">
        <div class="ha-num">3</div>
        <div class="ha-body">
          <b>Pega el token aquí</b>
          <label class="ha-lbl">Dirección de Home Assistant</label>
          <input id="ha-url" class="ha-in" placeholder="http://localhost:8123" value="${esc((s && s.url) || 'http://localhost:8123')}">
          <label class="ha-lbl">Token de acceso de larga duración</label>
          <textarea id="ha-token" class="ha-in" rows="3" placeholder="pega aquí el token largo que copiaste" autocomplete="off"></textarea>
          <div class="ha-row">
            <button class="ha-btn" id="ha-save">Conectar</button>
            <button class="ha-btn ghost" id="ha-cancel">Cancelar</button>
          </div>
          <div id="ha-msg" class="ha-out"></div>
        </div>
      </div>
    </div>`;
    $('#ha-open-home')?.addEventListener('click', () => openHAPath(''));
    $('#ha-open-dev')?.addEventListener('click', () => openHAPath('/config/integrations/dashboard'));
    $('#ha-open-prof')?.addEventListener('click', () => openHAPath('/profile/security'));
    $('#ha-cancel')?.addEventListener('click', renderHA);
    $('#ha-save')?.addEventListener('click', saveHAConn);
  }
  async function openHA() { return openHAPath(''); }
  async function installHA() {
    const btn = $('#ha-install'), out = $('#ha-out');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Instalando… (descarga la 1ª vez, puede tardar unos minutos)'; }
    if (out) out.textContent = 'Levantando Home Assistant en Docker…';
    let res = null;
    try { res = await api('/api/home/install_ha', { method: 'POST' }); } catch (e) { /* */ }
    if (!res || !res.ok) {
      if (out) out.textContent = (res && (res.error || res.out)) || 'No pude instalar Home Assistant. ¿Docker Desktop está abierto?';
      if (btn) { btn.disabled = false; btn.textContent = '⬇ Reintentar instalación'; }
      return;
    }
    if (out) out.textContent = '✓ Home Assistant levantado. Ábrelo para crear tu usuario y tus aparatos, luego pega el token.';
    setTimeout(() => renderHAForm({ url: res.url || 'http://localhost:8123' }, 'running'), 1200);
  }
  async function saveHAConn() {
    const url = ($('#ha-url')?.value || '').trim() || 'http://localhost:8123';
    const token = ($('#ha-token')?.value || '').trim();
    const msg = $('#ha-msg'), btn = $('#ha-save');
    if (msg) { msg.className = 'ha-out'; }
    if (!token) { if (msg) { msg.className = 'ha-out err'; msg.textContent = 'Falta el token (paso 2). Cópialo de tu perfil de HA → Seguridad.'; } return; }
    if (btn) { btn.disabled = true; }
    if (msg) msg.textContent = '⏳ probando la conexión…';
    // 1) PROBAR antes de guardar → feedback exacto de qué falla
    let t = null;
    try { t = await api('/api/home/ha_test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, token }) }); } catch (e) { /* */ }
    if (btn) { btn.disabled = false; }
    if (!t || !t.reachable) {
      if (msg) { msg.className = 'ha-out err'; msg.textContent = '✕ ' + ((t && t.error) || `No llego a Home Assistant en ${url}. Comprueba que está encendido y la dirección (por defecto http://localhost:8123).`); }
      return;
    }
    if (!t.token_valid) {
      if (msg) { msg.className = 'ha-out err'; msg.textContent = '✕ ' + (t.error || 'El token no es válido. Crea uno nuevo en tu perfil de HA (Seguridad) y pégalo entero.'); }
      return;
    }
    // 2) todo OK → guardar de verdad
    try {
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ homeassistant_url: url }) });
      await api('/api/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ homeassistant_token: token }) });
    } catch (e) { /* */ }
    if (msg) {
      msg.className = 'ha-out ok';
      msg.textContent = t.controllable
        ? `✓ ¡Conectado! ${t.controllable} aparatos controlables (de ${t.entities} entidades). Rastreando…`
        : `✓ Conectado, pero HA aún no tiene aparatos controlables. Vuelve al paso 1 y añade tus integraciones (luces, enchufes…).`;
    }
    state.devices = null;
    setTimeout(() => { renderHA(); scanDevices(); }, 700);
  }

  async function scanDevices() {
    if (_devScanning) return;
    _devScanning = true;
    const btn = $('#dev-scan'), radar = $('#dev-radar'), grid = $('#dev-grid');
    if (btn) { btn.disabled = true; btn.textContent = '◎ Buscando…'; }
    if (radar) radar.classList.remove('hidden');
    if (grid && !state.devices) grid.innerHTML = '';
    let res = null;
    try { res = await api('/api/home/scan', { method: 'POST' }); } catch (e) { /* */ }
    if (radar) radar.classList.add('hidden');
    if (btn) { btn.disabled = false; btn.textContent = '◎ Buscar dispositivos'; }
    _devScanning = false;
    if (!res || !res.devices) {
      if (grid) grid.innerHTML = '<div class="empty">No pude rastrear la red ahora mismo. Reintenta en unos segundos.</div>';
      return;
    }
    state.devices = res.devices;
    renderDevGrid(res.devices);
  }

  function _devSub(d) {
    // Subtítulo LIMPIO: tipo/estado. La chatarra técnica (IP · MAC) solo con el interruptor.
    const parts = [];
    if (d.kind === 'ha') {
      parts.push(d.state ? (d.on ? 'encendida' : (d.state === 'off' ? 'apagada' : d.state)) : 'Home Assistant');
    } else {
      if (d.type && d.type !== d.name) parts.push(d.type);
      // Estado HONESTO de una TV: solo decimos «encendida» si TÚ la encendiste.
      // Si no, «en red» (visible) o «no responde» — nunca fingimos que está on.
      if (d.on === true) parts.push('encendida');
      else if (d.live === false) parts.push('no responde ahora');
      else parts.push('en red · estado no confirmado');
    }
    if (_devTech) {
      if (d.ip) parts.push(d.ip);
      if (d.mac) parts.push(d.mac);
    }
    return parts.map(esc).join(' · ');
  }

  // Botón de ACCIÓN principal por tarjeta: uno solo, claro, según el aparato.
  function _mainAction(d) {
    if (d.kind === 'ha') {
      if (d.domain === 'cover') return d.on ? { a: 'off', t: '⬇ Cerrar', c: 'bad' } : { a: 'on', t: '⬆ Abrir', c: 'good' };
      if (d.domain === 'scene' || d.domain === 'script') return { a: 'on', t: '▸ Activar', c: 'good' };
      return d.on ? { a: 'off', t: '⭘ Apagar', c: 'bad' } : { a: 'on', t: '⏻ Encender', c: 'good' };
    }
    return d.on ? { a: 'off', t: '⭘ Apagar', c: 'bad' } : { a: 'on', t: '⏻ Encender', c: 'good' };
  }

  // Punto de estado HONESTO: verde = ENCENDIDO de verdad. Para una TV solo lo
  // sabemos si TÚ la has encendido en esta sesión (d.on===true); estar «en red»
  // o «guardada» NO es estar encendida (bug: salía verde solo por añadirla).
  function _stateDot(d) {
    if (d.kind === 'ha') return `<span class="dev-state ${d.on ? 'on' : 'off'}"></span>`;
    if (d.on === true) return '<span class="dev-state on"></span>';       // encendida (confirmado por ti)
    if (d.live !== false) return '<span class="dev-state net"></span>';   // en la red, estado desconocido
    return '<span class="dev-state off"></span>';                          // guardada, no responde ahora
  }
  function mineCardHtml(d, i) {
    const act = _mainAction(d);
    const muteBtn = d.kind !== 'ha' ? `<button class="dev-mini" data-i="${i}" data-a="mute" title="Silenciar">🔇</button>` : '';
    const offline = (d.live === false && d.kind !== 'ha') ? ' offline' : '';
    return `<div class="dev-card mine${offline}" data-idx="${i}">
      <div class="dev-ic">${esc(d.icon || '📟')}${_stateDot(d)}</div>
      <div class="dev-meta">
        <b class="dev-name" data-i="${i}">${esc(d.name || d.type || 'Dispositivo')}</b>
        <button class="dev-mini dev-edit" data-i="${i}" title="Renombrar (la voz usará este nombre)">✎</button>
        <span class="dev-sub">${_devSub(d)}</span>
      </div>
      <div class="dev-actions">
        <button class="dev-act ${act.c}" data-i="${i}" data-a="${act.a}">${act.t}</button>
        ${muteBtn}
        <button class="dev-mini star on" data-i="${i}" data-a="unstar" title="Quitar de Mis dispositivos">★</button>
        <button class="dev-mini" data-i="${i}" data-a="remote" title="Mando completo">🎛</button>
      </div>
    </div>`;
  }
  function detCardHtml(d, i) {
    return `<div class="dev-card det" data-idx="${i}">
      <div class="dev-ic">${esc(d.icon || '📟')}</div>
      <div class="dev-meta"><b>${esc(d.name || d.type || 'Dispositivo')}</b>
        <span class="dev-sub">${_devSub(d)}</span></div>
      <div class="dev-actions">
        <button class="dev-act good" data-i="${i}" data-a="add">＋ Añadir</button>
        <button class="dev-mini" data-i="${i}" data-a="remote" title="Probar el mando">🎛</button>
      </div>
    </div>`;
  }
  function netCardHtml(d, i) {
    return `<div class="dev-card info" data-idx="${i}" data-a="info" tabindex="0">
      <div class="dev-ic">${esc(d.icon || '📟')}</div>
      <div class="dev-meta"><b>${esc(d.name || d.type || 'Dispositivo')}</b>
        <span class="dev-sub">${_devSub(d)}</span></div>
      <span class="dev-go">ficha ▸</span>
    </div>`;
  }

  function renderDevGrid(devices) {
    const grid = $('#dev-grid'); if (!grid) return;
    devices = Array.isArray(devices) ? devices : [];
    // Mis dispositivos: lo guardado, ENRIQUECIDO con lo que vea el escáner ahora.
    const byKey = {};
    devices.forEach((d) => { byKey[devKey(d)] = d; });
    const mine = myDevices().map((m) => {
      const live = byKey[m.key];
      if (live) { if (m.name && !live.entity_id) live.name = m.name; return live; }
      // guardado pero no visto ahora: tarjeta igualmente (TV con MAC enciende por WoL)
      return { ...m, controllable: true, live: false, on: false, type: m.kind === 'ha' ? 'Home Assistant' : 'guardado', services: [] };
    });
    const mineKeys = new Set(myDevices().map((m) => m.key));
    const det = [], net = [];
    devices.forEach((d) => {
      if (mineKeys.has(devKey(d))) return;
      (d.controllable ? det : net).push(d);
    });
    _devList = mine.concat(det, net);
    const idx = (d) => _devList.indexOf(d);
    const dc = $('#dev-count');
    if (dc) dc.textContent = `${devices.length} en la red · ${devices.filter((d) => d.controllable).length} controlables`;
    let html = `<div class="dev-sech mine">★ MIS DISPOSITIVOS (${mine.length})</div>`;
    html += mine.length
      ? `<div class="dev-row">${mine.map((d) => mineCardHtml(d, idx(d))).join('')}</div>`
      : '<div class="dev-empty">Aún no tienes dispositivos guardados. Añade abajo los que uses (＋) y nexus los recordará y los manejará por voz.</div>';
    html += `<div class="dev-sech det">◎ DETECTADOS · LISTOS PARA AÑADIR</div>`;
    html += det.length
      ? `<div class="dev-row">${det.map((d) => detCardHtml(d, idx(d))).join('')}</div>`
      : '<div class="dev-empty ok">Todo lo controlable ya está en tus dispositivos ✓</div>';
    html += `<details class="dev-net"><summary>📡 EN LA RED (${net.length}) — solo informativo</summary>
      <div class="dev-row">${net.map((d) => netCardHtml(d, idx(d))).join('')}</div></details>`;
    grid.innerHTML = html;
    // UN SOLO listener DELEGADO en el contenedor, enganchado UNA vez para toda la
    // vida del grid. Antes se añadía un listener por botón EN CADA render y, como
    // el grid se repinta al añadir/controlar, el mismo clic se disparaba DOS veces
    // la primera vez (el bug de «lo hace dos veces»). La delegación no se acumula.
    if (!grid._deleg) {
      grid._deleg = 1;
      grid.addEventListener('click', (ev) => {
        const edit = ev.target.closest('.dev-edit');
        if (edit) { ev.stopPropagation(); startRename(+edit.dataset.i); return; }
        const el = ev.target.closest('[data-a]');
        if (!el || !grid.contains(el)) return;
        ev.stopPropagation();
        const d = _devList[+(el.dataset.i ?? el.dataset.idx)];
        if (!d) return;
        const a = el.dataset.a;
        if (a === 'add') addToMine(d);
        else if (a === 'unstar') removeFromMine(devKey(d), d.name);
        else if (a === 'remote') openDevControl(d);
        else if (a === 'info') infoDevControl(d);
        else controlDevice(d, a, el);
      });
    }
  }

  function startRename(i) {
    const d = _devList[i]; if (!d) return;
    const nameEl = document.querySelector(`.dev-name[data-i="${i}"]`); if (!nameEl) return;
    const inp = document.createElement('input');
    inp.className = 'dev-rename'; inp.value = d.name || ''; inp.maxLength = 60;
    nameEl.replaceWith(inp); inp.focus(); inp.select();
    let done = false;
    const save = async () => {
      if (done) return; done = true;
      const name = inp.value.trim();
      if (name && name !== d.name) {
        d.name = name;
        await api('/api/home/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, ip: d.ip || '', mac: d.mac || '', entity_id: d.entity_id || '', brand: d.brand || '' }) });
        const list = myDevices().slice();
        const m = list.find((x) => x.key === devKey(d)); if (m) m.name = name;
        state.config.my_devices = list;
        devToast(`🏷️ Renombrado a «${name}» — di «enciende ${name}» y nexus sabrá cuál es.`);
      }
      renderDevGrid(state.devices || []);
    };
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { done = true; renderDevGrid(state.devices || []); } });
    inp.addEventListener('blur', save);
  }

  function _controlBody(d, action) {
    return d.kind === 'ha'
      ? { kind: 'ha', action, entity_id: d.entity_id, name: d.name, domain: d.domain }
      : { kind: 'tv', action, ip: d.ip, brand: d.brand, mac: d.mac, name: d.name };
  }
  let _ctrlBusy = null;              // candado anti-doble-envío (device+acción en curso)
  async function controlDevice(d, action, btn) {
    const lock = devKey(d) + ':' + action;
    if (_ctrlBusy === lock) return;   // ya hay un envío idéntico en vuelo → se ignora
    _ctrlBusy = lock;
    if (btn) { btn.disabled = true; btn.dataset.t = btn.textContent; btn.textContent = '⏳'; }
    let res = null;
    try {
      res = await api('/api/home/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(_controlBody(d, action)) });
    } catch (e) { /* */ }
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.t || '⏻'; }
    _ctrlBusy = null;
    devToast((res && res.reply) ? res.reply : 'No hubo respuesta del dispositivo.');
    if (res && res.ok) {
      // v24: manda el estado que DEVUELVE el backend (ya persistido allí); si no
      // viene, se cae al optimista de siempre. Antes el botón se quedaba en
      // «Encender» aunque la orden hubiera ido bien — queja de Adri del 25/07.
      if (res.state === 'on') d.on = true;
      else if (res.state === 'off') d.on = false;
      else if (action === 'on') d.on = true;
      else if (action === 'off') d.on = false;
      // el objeto de la rejilla puede ser otra copia: se sincroniza por clave
      const _k = devKey(d);
      (state.devices || []).forEach((x) => { if (devKey(x) === _k) x.on = d.on; });
      (_devList || []).forEach((x) => { if (devKey(x) === _k) x.on = d.on; });
      if (d.kind !== 'ha') d.controllable = true;   // NO tocamos d.connected: eso es «emparejada», no «encendida»
      if (!mineEntry(devKey(d))) await addToMine(d);   // «añade lo que uses»: si lo usas, se guarda
      renderDevGrid(state.devices || []);
    }
  }

  /* ---- Mando completo (modal) — se abre SOLO con el botón 🎛, nada oculto ---- */
  const _DEV_BTN = (label, action, cls) => `<button class="dev-act ${cls || ''}" data-a="${action}">${label}</button>`;
  const _pwBtn = (d) => d.on ? _DEV_BTN('⭘ Apagar', 'off', 'bad') : _DEV_BTN('⏻ Encender', 'on', 'good');
  function _devButtons(d) {
    if (d.kind === 'ha') {
      if (d.domain === 'cover') return _DEV_BTN('⬆ Abrir', 'on', 'good') + _DEV_BTN('⬇ Cerrar', 'off', 'bad');
      if (d.domain === 'scene' || d.domain === 'script') return _DEV_BTN('▸ Activar', 'on', 'good');
      return _pwBtn(d);
    }
    return (d.connected
        ? _DEV_BTN('✓ Conectado', 'pair', 'wide connected')
        : _DEV_BTN('🔗 Conectar', 'pair', 'wide'))
      + _pwBtn(d)
      + _DEV_BTN('🔉 Vol -', 'vol_down') + _DEV_BTN('🔊 Vol +', 'vol_up') + _DEV_BTN('🔇 Silenciar', 'mute')
      + _DEV_BTN('⏮ Canal', 'ch_down') + _DEV_BTN('Canal ⏭', 'ch_up');
  }
  function _renderDevBody(d) {
    $('#dev-mbody').innerHTML = _devButtons(d);
    $('#dev-mbody').querySelectorAll('.dev-act').forEach((b) =>
      b.addEventListener('click', () => sendDevControl(b.dataset.a, b)));
  }
  function openDevControl(d) {
    _devOpen = d;
    $('#dev-mic').textContent = d.icon || '📟';
    $('#dev-mtitle').textContent = d.name || d.type;
    $('#dev-msub').textContent = d.kind === 'ha'
      ? `${d.type} · Home Assistant`
      : `${d.type}${d.brand && d.brand !== 'generic' ? ' · ' + d.brand : ''}${d.ip ? ' · ' + d.ip : ''}`;
    _renderDevBody(d);
    $('#dev-mmsg').textContent = d.kind === 'ha' ? '' : 'La primera vez, algunas TVs (Samsung) piden permiso en su pantalla: acéptalo.';
    $('#dev-modal').classList.remove('hidden');
  }
  function infoDevControl(d) {
    // dispositivo no controlable: su ficha (aquí SÍ vive la chatarra técnica completa)
    _devOpen = null;
    $('#dev-mic').textContent = d.icon || '📟';
    $('#dev-mtitle').textContent = d.name || d.type;
    $('#dev-msub').textContent = d.type || '';
    $('#dev-mbody').innerHTML = `<div class="dev-info-rows">
      ${d.ip ? `<div><span>IP</span><b>${esc(d.ip)}</b></div>` : ''}
      ${d.mac ? `<div><span>MAC</span><b>${esc(d.mac)}</b></div>` : ''}
      ${d.vendor ? `<div><span>Fabricante</span><b>${esc(d.vendor)}</b></div>` : ''}
      ${(d.services || []).length ? `<div><span>Servicios</span><b>${esc(d.services.join(', '))}</b></div>` : ''}
    </div>`;
    $('#dev-mmsg').textContent = 'Este aparato solo se lista. Para manejarlo, conéctalo a Home Assistant (arriba).';
    $('#dev-modal').classList.remove('hidden');
  }
  let _sendBusy = null;             // mismo candado anti-doble-envío en el modal
  async function sendDevControl(action, btn) {
    if (!_devOpen) return;
    const d = _devOpen;
    if (action && action.indexOf('brand:') === 0) {
      d.brand = action.split(':')[1]; d.kind = 'tv'; d.controllable = true;
      openDevControl(d); sendDevControl('pair'); return;
    }
    const lock = devKey(d) + ':' + action;
    if (_sendBusy === lock) return;
    _sendBusy = lock;
    const msg = $('#dev-mmsg');
    if (btn) { btn.disabled = true; }
    if (msg) msg.textContent = '⏳ enviando…';
    let res = null;
    try {
      res = await api('/api/home/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(_controlBody(d, action)) });
    } catch (e) { /* */ }
    if (btn) btn.disabled = false;
    _sendBusy = null;
    if (msg) msg.textContent = (res && res.reply) ? res.reply : 'No hubo respuesta del dispositivo.';
    if (d.kind === 'ha' && res && res.ok && (action === 'on' || action === 'off')) {
      d.on = (res.state ? res.state === 'on' : action === 'on'); d.state = action;
    }
    if (d.kind !== 'ha' && res && res.ok) {
      // «pair» = emparejar (conectar), NO encender: solo entonces marcamos connected.
      if (action === 'pair') d.connected = true;
      d.controllable = true;
      if (action === 'on') d.on = true;
      else if (action === 'off') d.on = false;
      if (_devOpen === d) _renderDevBody(d);
    }
    if (res && res.ok && !mineEntry(devKey(d))) await addToMine(d);  // lo usas → se guarda
    renderDevGrid(state.devices || []);
  }
  function closeDevModal() { $('#dev-modal')?.classList.add('hidden'); _devOpen = null; }

  /* ---------------- router ---------------- */
  const SCROLL_VIEWS = new Set(['skills', 'hardware', 'aicore', 'monitor', 'memory', 'calendar', 'tasks', 'contentos', 'jobs', 'home']);
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
    if (view === 'skills') {
      $$('.agent').forEach((el) => el.addEventListener('click', () => openNode(el.dataset.skill)));
      api('/api/knowledge').then((k) => { const c = $('#kn-count'); if (c) c.textContent = (k?.count || 0).toLocaleString('es'); });
    }
    if (view === 'knowledge') mountKnowledge();
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
  function flash(el) { el.style.background = 'rgba(34,211,238,.2)'; setTimeout(() => { el.style.background = ''; }, 400); }

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

  /* ---------------- Nodos de conocimiento (grafo arrastrable) ---------------- */
  let knRaf = 0, knDrag = null, knStageEl = null, knNodes = [];
  /* GRUPOS de memoria: las notas enlazadas entre sí ([[wikilinks]]) forman un
     grupo que comparte COLOR y se mueve EN BLOQUE. Se calcula con union-find
     sobre el grafo y el resultado se comparte entre las vistas Memoria y Nodos. */
  const GROUP_PALETTE = ['#22d3ee', '#7cf6c0', '#ff7ac0', '#ffd23a', '#c77dff', '#4d9bff',
    '#ff5e5e', '#59ff9c', '#ffb14d', '#4dffd8', '#f97316', '#a3e635'];
  let memGroupColor = {};                      // nota → color de su grupo
  function computeMemGroups(names, edges) {
    const idx = Object.fromEntries(names.map((n, i) => [n, i]));
    const parent = names.map((_, i) => i);
    const find = (a) => (parent[a] === a ? a : (parent[a] = find(parent[a])));
    (edges || []).forEach(([a, b]) => {
      if (idx[a] != null && idx[b] != null) parent[find(idx[a])] = find(idx[b]);
    });
    const comps = {};
    names.forEach((n, i) => { const r = find(i); (comps[r] = comps[r] || []).push(n); });
    // orden estable (por su primer miembro alfabético) → mismos colores siempre
    const ordered = Object.values(comps).sort(
      (A, B) => A.slice().sort()[0].localeCompare(B.slice().sort()[0]));
    memGroupColor = {}; const groupOf = {};
    ordered.forEach((members, gi) => {
      const col = GROUP_PALETTE[gi % GROUP_PALETTE.length];
      members.forEach((m) => { memGroupColor[m] = col; groupOf[m] = gi; });
    });
    return groupOf;
  }
  function knNoteColor(nm) {
    const l = nm.toLowerCase();
    if (l.startsWith('doc')) return '#4dd8ff';
    if (l.includes('objetiv')) return '#ffb14d';
    if (l.includes('conocimiento') || l.includes('procedim')) return '#7cf6c0';
    if (l.includes('idea')) return '#ff7ac0';
    if (l.includes('factura') || l.includes('cliente')) return '#ffe74d';
    return '#9d7dff';
  }
  function mountKnowledge() {
    cancelAnimationFrame(knRaf);
    const stage = $('#kn-stage'), links = $('#kn-links');
    knStageEl = stage;
    const dpr = window.devicePixelRatio || 1;
    const W = stage.clientWidth, H = stage.clientHeight;
    links.width = W * dpr; links.height = H * dpr; links.style.width = W + 'px'; links.style.height = H + 'px';
    const ctx = links.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    stage.querySelectorAll('.knode').forEach((e) => e.remove());
    const cx = W / 2, cy = H / 2, nodes = [], byKey = {};
    knNodes = nodes;
    let edges = [];
    const place = (data) => {
      const el = document.createElement('div');
      el.className = 'knode' + (data.core ? ' core' : '') + (data.note ? ' note' : '');
      el.style.setProperty('--c', data.color);
      const sz = data.core ? 90 : data.note ? 34 : 56;
      el.style.width = el.style.height = sz + 'px';
      el.innerHTML = `<span>${esc(data.label)}</span>`;
      stage.appendChild(el);
      const n = Object.assign({ el, sz, x: data.x0 ?? cx, y: data.y0 ?? cy, vx: 0, vy: 0, moved: false }, data);
      nodes.push(n); if (data.key) byKey[data.key] = n;
      el.addEventListener('mousedown', (e) => { e.preventDefault(); knDrag = n; n.moved = false; n._sx = e.clientX; n._sy = e.clientY; });
      el.addEventListener('click', () => {
        if (n.moved) return;
        if (n.core) return openNode('__core__');
        if (n.note) return openNote(n.raw);
        return openNode(n.folder);
      });
      return n;
    };
    const core = place({ core: 1, key: 'nexus', label: 'nexus', color: '#22d3ee', x0: cx, y0: cy });
    core.fixed = true;
    const keys = Object.keys(CATALOG), R = Math.min(W, H) * 0.30;
    keys.forEach((k, i) => { const a = i / keys.length * Math.PI * 2 - Math.PI / 2;
      place({ folder: k, key: 'skill:' + k, label: CATALOG[k].label, color: CATALOG[k].color,
        x0: cx + Math.cos(a) * R * 1.3, y0: cy + Math.sin(a) * R }); });
    api('/api/graph').then((g) => {
      const gn = (g?.nodes || []), ge = (g?.edges || []);
      const groupOf = computeMemGroups(gn, ge);   // notas enlazadas = mismo color/grupo
      const notes = gn.slice(0, 26), R2 = Math.min(W, H) * 0.44;
      notes.forEach((nm, i) => { const a = i / Math.max(1, notes.length) * Math.PI * 2 + 0.4;
        place({ note: 1, key: 'note:' + nm, raw: nm, group: groupOf[nm],
          label: nm.length > 13 ? nm.slice(0, 12) + '…' : nm,
          color: memGroupColor[nm] || knNoteColor(nm),
          x0: cx + Math.cos(a) * R2 * 1.3, y0: cy + Math.sin(a) * R2 }); });
      edges = ge.map(([f, t]) => [byKey['note:' + f], byKey['note:' + t]]).filter(([a, b]) => a && b);
    });
    // Nodos QUIETOS: se quedan donde están; solo se mueven si los arrastras.
    // El bucle solo redibuja las líneas y coloca los nodos (sin física ni deriva).
    function frame() {
      ctx.clearRect(0, 0, W, H);
      const coreN = nodes.find((n) => n.core); if (coreN) { coreN.x = cx; coreN.y = cy; }
      for (const n of nodes) { if (n.core) continue;
        ctx.strokeStyle = n.color + (n.note ? '22' : '38'); ctx.lineWidth = n.note ? 1 : 1.5;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(n.x, n.y); ctx.stroke(); }
      ctx.lineWidth = 1.2;
      for (const [a, b] of edges) { ctx.strokeStyle = (a.color || '#7cf6c0') + '66';
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
      for (const n of nodes) { n.el.style.left = (n.x - n.sz / 2) + 'px'; n.el.style.top = (n.y - n.sz / 2) + 'px'; }
      knRaf = requestAnimationFrame(frame);
    }
    frame();
  }
  // arrastre global de nodos
  document.addEventListener('mousemove', (e) => {
    if (!knDrag || !knStageEl) return;
    const r = knStageEl.getBoundingClientRect();
    if (Math.hypot(e.clientX - knDrag._sx, e.clientY - knDrag._sy) > 4) knDrag.moved = true;
    const nx = e.clientX - r.left, ny = e.clientY - r.top;
    // En «Nodos de conocimiento» cada nodo se mueve INDIVIDUALMENTE (no en bloque).
    // (El movimiento en bloque por grupo se mantiene en la vista Memoria.)
    knDrag.x = nx; knDrag.y = ny; knDrag.x0 = nx; knDrag.y0 = ny; knDrag.vx = 0; knDrag.vy = 0;
  });
  document.addEventListener('mouseup', () => {
    if (knDrag) { knDrag.x0 = knDrag.x; knDrag.y0 = knDrag.y; }   // se queda donde lo sueltas
    knDrag = null;
  });
  /* ============ MINI-VENTANAS flotantes (nodos de conocimiento y memoria) ============
     Cada nodo se abre en su propia ventanita con ✕; puedes abrir varias a la vez
     y van RELLENANDO la pantalla en rejilla (cuando se llena, en cascada).
     Se arrastran desde su cabecera y el clic las trae al frente. Sobreviven al
     cambiar de vista, así puedes comparar nodos de memoria y de conocimiento. */
  let _mwZ = 300, _mwCount = 0, _mwDrag = null;
  function miniWinLayer() {
    let c = $('#mini-wins');
    if (!c) { c = document.createElement('div'); c.id = 'mini-wins'; $('#main').appendChild(c); }
    return c;
  }
  function openMiniWin(id, title, color, loadingHtml) {
    const layer = miniWinLayer();
    const prev = layer.querySelector(`.mini-win[data-mwid="${CSS.escape(id)}"]`);
    if (prev) {                                  // ya abierta → al frente y un destello
      prev.style.zIndex = ++_mwZ;
      prev.classList.remove('flash'); void prev.offsetWidth; prev.classList.add('flash');
      return null;
    }
    const w = document.createElement('div');
    w.className = 'mini-win'; w.dataset.mwid = id;
    w.style.setProperty('--c', color || '#22d3ee');
    // posición ALEATORIA dentro del área útil: cada ventana cae donde quiere
    // y la pantalla se va llenando de forma orgánica (luego las arrastras).
    const area = $('#main').getBoundingClientRect();
    const MW = 324, MH = 300, X0 = 18, Y0 = 62;
    const maxX = Math.max(X0, area.width - MW - 22);
    const maxY = Math.max(Y0, area.height - MH - 46);
    _mwCount++;
    w.style.left = Math.round(X0 + Math.random() * (maxX - X0)) + 'px';
    w.style.top = Math.round(Y0 + Math.random() * (maxY - Y0)) + 'px';
    w.style.zIndex = ++_mwZ;
    w.innerHTML = `<div class="mw-head"><span class="mw-title">${esc(title)}</span>
        <button class="mw-close" title="Cerrar">✕</button></div>
      <div class="mw-body">${loadingHtml || '<div class="empty"><span class="dots">cargando</span></div>'}</div>`;
    layer.appendChild(w);
    w.querySelector('.mw-close').addEventListener('click', (e) => { e.stopPropagation(); w.remove(); });
    w.addEventListener('mousedown', () => { w.style.zIndex = ++_mwZ; });
    const head = w.querySelector('.mw-head');
    head.addEventListener('mousedown', (e) => {
      if (e.target.classList.contains('mw-close')) return;
      const r = w.getBoundingClientRect();
      _mwDrag = { w, dx: e.clientX - r.left, dy: e.clientY - r.top };
      e.preventDefault();
    });
    return w.querySelector('.mw-body');
  }
  document.addEventListener('mousemove', (e) => {
    if (!_mwDrag) return;
    const a = $('#main').getBoundingClientRect();
    _mwDrag.w.style.left = Math.max(0, Math.min(a.width - 60, e.clientX - a.left - _mwDrag.dx)) + 'px';
    _mwDrag.w.style.top = Math.max(0, Math.min(a.height - 40, e.clientY - a.top - _mwDrag.dy)) + 'px';
  });
  document.addEventListener('mouseup', () => { _mwDrag = null; });
  function closeTopMiniWin() {
    const wins = $$('#mini-wins .mini-win');
    if (!wins.length) return false;
    wins.sort((a, b) => (+b.style.zIndex || 0) - (+a.style.zIndex || 0))[0].remove();
    return true;
  }

  // Nodo de MEMORIA → mini-ventana con el contenido de la nota
  async function openNote(name) {
    const color = memGroupColor[name] || knNoteColor(name);
    const body = openMiniWin('note:' + name, '▣ ' + name, color, null);
    if (!body) return;                            // ya estaba abierta
    const d = await api('/api/note?name=' + encodeURIComponent(name));
    const content = (d?.content || '').trim();
    body.innerHTML = `
      <div class="ns-sec"><h4>NODO DE MEMORIA</h4><p>${esc(name)}</p></div>
      <div class="ns-sec"><h4>CONTENIDO</h4><div class="ns-doc">${content ? mdToHtml(content.slice(0, 4000)) : '<p class="empty">Nota vacía o no encontrada.</p>'}</div></div>
      <div class="ns-sec"><h4>ACCIONES</h4><div class="ns-acts">
        ${nsBtn('Preguntar sobre esto', 'qué recuerdas de ' + name)}
        ${nsBtn('Ver memoria', null, 0, 'memory')}
      </div></div>`;
    wireNs(body);
  }

  // Nodo de CONOCIMIENTO (skill o núcleo) → mini-ventana con su ficha
  async function openNode(folder) {
    const color = folder === '__core__' ? '#22d3ee' : (CATALOG[folder]?.color || '#22d3ee');
    const title = folder === '__core__' ? 'nexus · núcleo' : (CATALOG[folder]?.label || folder);
    const body = openMiniWin('node:' + folder, '◈ ' + title, color, null);
    if (!body) return;
    if (folder === '__core__') {
      body.innerHTML = `
        <div class="ns-sec"><h4>FUNCIÓN</h4><p>Orquestador central. Recibe tus órdenes por voz o texto, decide qué minion las resuelve y coordina la respuesta.</p></div>
        <div class="ns-sec"><h4>ACCIONES</h4><div class="ns-acts">
          ${nsBtn('¿Qué me toca hoy?', 'qué me toca hoy')}${nsBtn('Estado del equipo', null, 0, 'hardware')}
          ${nsBtn('Estado de la memoria', 'estado de la memoria')}${nsBtn('Qué manos tengo', 'qué manos tienes')}
        </div></div>`;
      wireNs(body);
      return;
    }
    const cat = CATALOG[folder];
    const d = await api('/api/skill/' + folder);
    const actions = (cat?.actions || []).map(([l, c, pr]) => nsBtn(l, c, pr)).join('');
    const intents = (d?.intents || []).map((i) => `<span class="ns-chip">${esc(i)}</span>`).join('');
    const docHtml = d?.doc ? mdToHtml(d.doc) : '<p class="empty">Sin SKILL.md.</p>';
    body.innerHTML = `
      <div class="ns-sec"><h4>DESCRIPCIÓN</h4><p>${esc(d?.description || cat?.desc || '')}</p>
        <div class="ns-stat">estado <b>${esc(d?.status || 'ready')}</b> · usos <b>${d?.calls || 0}</b> · ${(d?.intents || []).length} acciones</div></div>
      <div class="ns-sec"><h4>ACCIONES</h4><div class="ns-acts">${actions || '<span class="empty">—</span>'}</div></div>
      <div class="ns-sec"><h4>CAPACIDADES</h4><div class="ns-chips">${intents}</div></div>
      <div class="ns-sec"><h4>MÓDULO · SKILL.md</h4><div class="ns-doc">${docHtml}</div></div>`;
    wireNs(body);
  }
  function nsBtn(label, cmd, isP, view) { return `<button class="ns-act" data-cmd="${cmd ? esc(cmd) : ''}" data-p="${isP ? 1 : ''}" data-v="${view || ''}">▸ ${esc(label)}</button>`; }
  function wireNs(scope) {
    (scope || document).querySelectorAll('.ns-act').forEach((b) => b.addEventListener('click', () => {
      if (b.dataset.v) return render(b.dataset.v);
      const cmd = b.dataset.cmd;
      if (b.dataset.p) { render('chat'); setTimeout(() => { $('#chat-in').value = cmd; $('#chat-in').focus(); }, 50); }
      else { send(cmd); flash(b); }
    }));
  }
  function mdToHtml(md) {
    return esc(md)
      .replace(/^#### (.+)$/gm, '<h5>$1</h5>')
      .replace(/^### (.+)$/gm, '<h5>$1</h5>')
      .replace(/^## (.+)$/gm, '<h4>$1</h4>')
      .replace(/^# (.+)$/gm, '<h3>$1</h3>')
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/^- (.+)$/gm, '• $1')
      .replace(/\n/g, '<br>');
  }
  $('#np-close').addEventListener('click', () => $('#node-panel').classList.add('hidden'));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#node-panel')?.classList.add('hidden'); });

  /* ---------------- vincular móvil (QR + túnel) ---------------- */
  function _stopLinkPoll() { if (window.__linkPoll) { clearInterval(window.__linkPoll); window.__linkPoll = 0; } }
  // Dibuja el QR EN EL NAVEGADOR (sin depender del backend/qrcode de Python).
  function _drawQR(link) {
    const box = $('#lk-qr'); if (!box) return;
    try {
      const q = window.qrcode(0, 'M'); q.addData(link); q.make();
      box.innerHTML = `<img src="${q.createDataURL(6, 12)}" width="240" height="240" alt="QR de nexus">`;
    } catch (e) {
      box.innerHTML = `<div class="lk-fallback">No pude dibujar el QR. Abre esto en el móvil:<br>
        <code>${esc(link)}</code></div>`;
    }
  }
  // ---- móviles vinculados (los alimentan los eventos WS 'paired'/'unpaired') ----
  let _pairedDevs = [];
  function paintLinkBadge() {
    const b = $('#btn-link'); if (!b) return;
    const n = _pairedDevs.length;
    b.classList.toggle('on', n > 0);
    b.setAttribute('data-n', n ? String(n) : '');
    b.title = n ? `${n} móvil(es) vinculado(s): ${_pairedDevs.map((d) => d.name).join(', ')}`
                : 'Vincular el móvil (QR)';
  }
  function renderLinkDevices() {
    const box = $('#lk-devices'); if (!box) return;
    box.innerHTML = _pairedDevs.length
      ? '<div class="lk-dev-h">📱 Vinculados ahora</div>' + _pairedDevs.map((d) =>
          `<div class="lk-dev"><b>${esc(d.name)}</b><span>${esc(d.ip || '—')} · ${esc(d.since || '')}</span></div>`).join('')
      : '';
  }
  function refreshDevices() {
    return api('/api/link/status').then((st) => {
      _pairedDevs = (st && st.devices) || [];
      paintLinkBadge(); renderLinkDevices();
      return st;
    }).catch(() => {});
  }
  function onPaired(data) {
    const name = (data && data.name) || 'Móvil';
    refreshDevices();
    pushLog('ok', `📱 ${name} vinculado ✓`);
    const modal = $('#config-modal');
    if ($('#lk-qr') && modal && !modal.classList.contains('hidden')) {
      _stopLinkPoll();                       // ya está: deja de buscar túnel
      $('#lk-qr').innerHTML = '<div class="lk-ok">✔</div>';
      $('#lk-state').innerHTML = `<b style="color:var(--ok)">📱 ${esc(name)} vinculado</b><br>`
        + 'Ya puedes hablar con nexus desde el móvil.';
      setTimeout(() => { if (!modal.classList.contains('hidden')) modal.classList.add('hidden'); }, 1900);
    }
  }
  function onUnpaired(data) {
    refreshDevices().then(() => {
      // sin ningún móvil vinculado → directo a la pantalla de VINCULAR (QR)
      if (!_pairedDevs.length) openLinkModal();
    });
    if (data && data.name) pushLog('info', `📱 ${data.name} desvinculado`);
  }

  async function openLinkModal() {
    const m = $('#config-modal');
    $('#config-body').innerHTML = `<h2>📱 VINCULAR EL MÓVIL</h2>
      <div class="lk-info">En el móvil: app de nexus → «VINCULAR CON nexus» → apunta la cámara a
      este QR. El QR ya vale en tu WiFi al instante; en unos segundos se actualiza para que valga
      <b>desde cualquier red</b> (túnel seguro con token).</div>
      <div id="lk-qr" class="lk-qr"><span class="dots">generando QR</span></div>
      <div id="lk-state" class="lk-state">…</div>
      <div id="lk-devices" class="lk-devices"></div>
      <div class="modal-btns"><button class="ghost" id="lk-close">Cerrar</button>
        <button class="ghost" id="lk-unlink" style="color:#ff5470;border-color:rgba(255,84,112,.5)">⛓ Desvincular</button>
        <button id="lk-refresh">↻ Regenerar QR</button></div>`;
    m.classList.remove('hidden');
    m.onclick = (e) => { if (e.target === m) { m.classList.add('hidden'); _stopLinkPoll(); } };
    $('#lk-close').addEventListener('click', () => { m.classList.add('hidden'); _stopLinkPoll(); });
    $('#lk-refresh').addEventListener('click', () => render(true));
    $('#lk-unlink').addEventListener('click', async () => {
      if (!confirm('¿Desvincular TODOS los móviles? El enlace viejo deja de valer y habrá que escanear el QR nuevo.')) return;
      await api('/api/link/reset', { method: 'POST' });
      _pairedDevs = []; paintLinkBadge(); renderLinkDevices();
      pushLog('info', '📱 Desvinculado: token nuevo. Escanea el QR para volver a vincular.');
      render(true);
    });

    async function render(retry) {
      if (retry) { $('#lk-qr').innerHTML = '<span class="dots">regenerando</span>'; api('/api/link/start', { method: 'POST' }); }
      const st = await api('/api/link/status');
      if (!st || !st.link) { $('#lk-state').textContent = 'Backend sin respuesta — ¿está nexus arrancado?'; return; }
      _drawQR(st.link);
      _pairedDevs = st.devices || _pairedDevs; paintLinkBadge(); renderLinkDevices();
      $('#lk-state').innerHTML = st.tunnel
        ? `<b style="color:var(--ok)">✔ Túnel activo</b> — el QR vale desde CUALQUIER red<br><code>${esc(st.url)}</code>`
        : `<b style="color:var(--warn,#ffd23a)">⚠ Túnel arrancando…</b> — el QR ya vale en tu WiFi `
          + `(<code>${esc(st.lan)}</code>).` + (st.error ? `<br><span style="color:var(--err)">${esc(st.error)}</span>` : '');
    }

    render(false);                         // 1) pinta YA (LAN)
    api('/api/link/start', { method: 'POST' });   // 2) levanta el túnel en segundo plano
    _stopLinkPoll();                       // 3) cuando el túnel esté, actualiza el QR solo
    let tries = 0;
    window.__linkPoll = setInterval(async () => {
      if ($('#config-modal').classList.contains('hidden')) return _stopLinkPoll();
      const st = await api('/api/link/status');
      if (st && st.tunnel) {
        _drawQR(st.link);
        $('#lk-state').innerHTML = `<b style="color:var(--ok)">✔ Túnel activo</b> — el QR vale desde CUALQUIER red<br><code>${esc(st.url)}</code>`;
        _stopLinkPoll();
      }
      if (++tries > 24) _stopLinkPoll();
    }, 2500);
  }

  /* ---------------- config modal ---------------- */
  function configModal() {
    const c = state.config;
    $('#config-body').innerHTML = `<h2>▚ CONFIGURACIÓN</h2>
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
        <div class="chk" style="font-size:12px;color:var(--txt-dim);line-height:1.5">😈 <b style="color:var(--cy)">Modo abogado del diablo: SIEMPRE ACTIVO</b><br>Skill propia de nexus — el modelo cuestiona y depura su propio razonamiento antes de responderte. No es apagable.</div></fieldset>
      <fieldset><legend>PROACTIVIDAD · PROJECT MANAGER</legend>
        <label class="chk"><input type="checkbox" id="m-proactive" ${c.proactive !== false ? 'checked' : ''}> Toma la iniciativa: recordatorios y empujón diario sin que le hables</label>
        <label class="chk"><input type="checkbox" id="m-proactivespeak" ${c.proactive_speak !== false ? 'checked' : ''}> Que los avisos me los diga en voz alta</label>
        <label class="chk"><input type="checkbox" id="m-pmstrong" ${c.pm_strong !== false ? 'checked' : ''}> <b style="color:var(--cy)">Modo PM fuerte</b>: crea tareas de lo que hablo y las mueve según le respondo</label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Con el modo fuerte, si dices «tengo que llamar al proveedor» te lo apunta como tarea solo; y cuando te pregunte «¿cómo vas con X?», tu respuesta («ya está», «a medias», «aún no») mueve la tarea en el tablero. Apágalo si prefieres que no toque nada sin pedírselo.</div></fieldset>
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
        <label>Palabra de activación<input id="m-wakeword" value="${esc(c.wake_word || ('despierta ' + (c.assistant_name || 'nexus').toLowerCase()))}"></label></fieldset>
      <fieldset><legend>PERMISOS (estilo sandbox)</legend>
        <label class="chk"><input type="checkbox" id="m-hw" ${c.perm_hardware !== false ? 'checked' : ''}> Leer hardware (CPU/RAM/placa/discos/temps)</label>
        <label>Acceso a archivos<select id="m-permfiles">${['sandbox', 'carpetas', 'todo'].map((o) => `<option ${c.perm_files === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
        <label>Carpetas permitidas (una por línea, solo modo «carpetas»)<textarea id="m-permfolders" rows="2" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--txt);font-family:inherit;padding:8px;border-radius:6px">${esc((c.perm_folders || []).join('\n'))}</textarea></label></fieldset>
      <fieldset><legend>GOOGLE / INSTAGRAM / TELEGRAM</legend>
        <label>Google Client ID<input id="m-gid" type="password" placeholder="${c.has_google_client_id ? '•••• guardado' : ''}"></label>
        <label>Google Client Secret<input id="m-gsec" type="password" placeholder="${c.has_google_client_secret ? '•••• guardado' : ''}"></label>
        <label>Instagram user id<input id="m-iguser" value="${esc(c.ig_user_id || '')}"></label>
        <label>Instagram token<input id="m-igtok" type="password" placeholder="${c.has_ig_access_token ? '•••• guardado' : ''}"></label>
        <label>Token Telegram<input id="m-tg" type="password" placeholder="${c.has_telegram_bot_token ? '•••• guardado' : ''}"></label></fieldset>
      <fieldset><legend>SPOTIFY (autoplay real)</legend>
        <label>Spotify Client ID<input id="m-spid" type="password" placeholder="${c.has_spotify_client_id ? '•••• guardado' : 'developer.spotify.com → tu app'}"></label>
        <label>Spotify Client Secret<input id="m-spsec" type="password" placeholder="${c.has_spotify_client_secret ? '•••• guardado' : ''}"></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Requiere cuenta <b>Premium</b>. En developer.spotify.com crea una app y añade este Redirect URI:<br><b style="color:var(--cy)">http://127.0.0.1:8177/api/spotify/callback</b><br>Después di «pon una canción en spotify»: autorizas una vez y ya suena sola.</div></fieldset>
      <fieldset><legend>RED / AUTOMATIZACIÓN</legend>
        <label>n8n · URL base<input id="m-n8nbase" value="${esc(c.n8n_base_url || 'http://localhost:5678')}"></label>
        <label>n8n · Webhook<input id="m-n8n" value="${esc(c.n8n_webhook_url || '')}"></label>
        <label>n8n · API key<input id="m-n8nkey" type="password" placeholder="${c.has_n8n_api_key ? '•••• guardada' : 'para que nexus cree flujos solo'}"></label>
        <label>Discord · Webhook<input id="m-dcwh" type="password" placeholder="${c.has_discord_webhook_url ? '•••• guardado' : 'para publicar en un canal'}"></label>
        <label>MAC del PC (Wake-on-LAN)<input id="m-wol" value="${esc(c.wol_mac || '')}"></label></fieldset>
      <fieldset class="cfg-domotica"><legend>DOMÓTICA</legend>
        <button type="button" id="m-scan-open" class="cfg-scanbtn">◎ Buscar dispositivos en la red</button>
        <label>Home Assistant · URL<input id="m-haurl" value="${esc(c.homeassistant_url || '')}" placeholder="http://homeassistant.local:8123"></label>
        <label>Home Assistant · Token<input id="m-hatok" type="password" placeholder="${c.has_homeassistant_token ? '•••• guardado' : 'token de acceso de larga duración'}"></label>
        <label>Dispositivos conocidos (uno por línea: Nombre | IP | MAC | marca)<textarea id="m-devs" rows="3" style="width:100%;background:var(--panel2);border:1px solid var(--line);color:var(--txt);font-family:inherit;padding:8px;border-radius:6px" placeholder="Tele salón | 192.168.1.40 | AA:BB:CC:DD:EE:FF | samsung">${esc((c.known_devices || []).map((d) => [d.name, d.ip, d.mac, d.brand].filter(Boolean).join(' | ')).join('\n'))}</textarea></label>
        <div class="chk" style="font-size:11px;color:var(--txt-dim);line-height:1.5">Con Home Assistant controlas TODO (luces, enchufes, persianas, teles…). Sin él, di «escanea la red» y manejo TVs por Roku/Samsung/Wake-on-LAN.</div></fieldset>
      <div class="modal-btns"><button class="ghost" id="m-cancel">Cancelar</button><button id="m-save">Guardar</button></div>`;
    $('#config-modal').classList.remove('hidden');
    // panel plegable: cada seccion se abre/cierra al pulsar su titulo (deja abierta solo la 1a)
    $$('#config-modal fieldset').forEach((fs, i) => {
      if (i > 0) fs.classList.add('cfg-collapsed');
      const lg = fs.querySelector('legend');
      if (lg) lg.addEventListener('click', () => fs.classList.toggle('cfg-collapsed'));
    });
    $('#m-scan-open')?.addEventListener('click', () => { $('#config-modal').classList.add('hidden'); render('home'); });
    // cerrar pulsando fuera del recuadro (en el fondo oscuro)
    $('#config-modal').onclick = (e) => { if (e.target === $('#config-modal')) $('#config-modal').classList.add('hidden'); };
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
    $('#m-cancel').addEventListener('click', () => $('#config-modal').classList.add('hidden'));
    $('#m-save').addEventListener('click', async () => {
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
        ig_user_id: $('#m-iguser').value, n8n_webhook_url: $('#m-n8n').value,
        n8n_base_url: $('#m-n8nbase').value || 'http://localhost:5678', wol_mac: $('#m-wol').value,
        homeassistant_url: $('#m-haurl') ? $('#m-haurl').value.trim() : '',
        known_devices: $('#m-devs') ? $('#m-devs').value.split('\n').map((l) => {
          const p = l.split('|').map((x) => x.trim()); if (!p[0]) return null;
          return { name: p[0], ip: p[1] || '', mac: p[2] || '', brand: (p[3] || '').toLowerCase() };
        }).filter(Boolean) : [] };
      window.__sinkId = cfg.output_sink_id || '';   // aplica la salida al instante
      await api('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cfg) });
      const sec = {}; const add = (id, k) => { const v = $(id).value; if (v) sec[k] = v; };
      add('#m-gid', 'google_client_id'); add('#m-gsec', 'google_client_secret'); add('#m-iguser', ''); add('#m-igtok', 'ig_access_token'); add('#m-tg', 'telegram_bot_token'); add('#m-n8nkey', 'n8n_api_key'); add('#m-dcwh', 'discord_webhook_url'); add('#m-spid', 'spotify_client_id'); add('#m-spsec', 'spotify_client_secret'); add('#m-hatok', 'homeassistant_token');
      delete sec['']; if (Object.keys(sec).length) await api('/api/secrets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sec) });
      $('#config-modal').classList.add('hidden'); await fetchAll(); pushLog('ok', 'Configuración actualizada');
    });
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
