/* EL ASISTENTE DE INSTALACIÓN, EN SU PROPIO FICHERO (T18b, SEC-10).
 *
 * Estaba en un bloque `<script>` en línea al final de `frontend/setup.html` y
 * sus 17 manejadores (14 `onclick="go(n)"`, 2 `oninput`, 1 `onchange`) estaban
 * en ATRIBUTOS del HTML. Las dos cosas obligaban a `script-src 'self'
 * 'unsafe-inline'`: un manejador en línea inyectado en esta página se ejecutaba.
 *
 * El código se movió tal cual. Lo único que cambia es CÓMO se llama:
 *   · `go(n)` es una función de este fichero y los 14 botones solo dicen su
 *     destino en `data-go`; un ÚNICO clic delegado en el documento los atiende
 *     (los destinos son los mismos 14: 1,0, 2,1, 3,2, 4,3, 5,4, 6,5, 7,6).
 *   · `onSysName()` y `onLogoPick()` se llaman desde sendos listeners de
 *     `input`/`change`, no desde un atributo.
 *
 * Se carga como MÓDULO (`<script type="module">`), así que va diferido: se
 * ejecuta cuando el documento ya está parseado, y el paso 0 se pinta igual.
 */

(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const api = (p, o) => fetch(p, o).then((r) => r.json()).catch(() => null);
  const state = { personality: 'jarvis', perm: 'todo', db: 'local', profile: 'nexus' };
  const N = 8;
  $('#steps').innerHTML = Array.from({length: N}, (_, i) => `<b data-i="${i}">${i}</b>`).join('');

  function go(n) {
    $$('.step').forEach((s) => s.classList.toggle('on', +s.dataset.s === n));
    $$('#steps b').forEach((b) => {
      b.classList.toggle('on', +b.dataset.i === n);
      b.classList.toggle('done', +b.dataset.i < n);
    });
    if (n === 7) resumen();
    window.scrollTo(0, 0);
  }

  // T18b: los 14 botones de la navegación ya NO llevan `onclick` en el HTML.
  // UN solo clic delegado en el documento; cada botón dice su destino en
  // `data-go`. Un clic en cualquier otro sitio (o en algo sin `closest`, que es
  // lo que pasa al llamar al listener a mano) no navega y no revienta.
  document.addEventListener('click', (ev) => {
    const b = ev.target && ev.target.closest ? ev.target.closest('[data-go]') : null;
    if (b) go(+b.dataset.go);
  });

  function wireCards(sel, cb) {
    $$(sel + ' .card').forEach((c) => c.addEventListener('click', () => {
      $$(sel + ' .card').forEach((x) => x.classList.remove('sel'));
      c.classList.add('sel'); cb(c.dataset.v);
    }));
  }

  // personalidades desde el backend (afectan al prompt de verdad)
  api('/api/setup/state').then((st) => {
    if (!st) return;
    const p = st.personalities || {};
    $('#pers-cards').innerHTML = Object.entries(p).map(([k, v]) =>
      `<div class="card ${k === 'jarvis' ? 'sel' : ''}" data-v="${k}"><b>${v.name}</b><p>${v.desc}</p></div>`).join('');
    wireCards('#pers-cards', (v) => state.personality = v);
    $('#docker-state').innerHTML = st.docker
      ? `<span class="ok">✔ Docker detectado: ${st.docker_version}</span>`
      : '<span class="bad">✕ Docker NO detectado en este equipo.</span>';
    if (st.config && st.config.operator_name) $('#f-name').value = st.config.operator_name;
    const c = st.config || {};
    const savedName = (c.assistant_name || '').trim();
    const savedLogo = (c.assistant_logo || '').trim();
    // Si ya había un perfil propio guardado (nombre distinto de «nexus» o logo), reábrelo en modo custom.
    if ((savedName && savedName.toLowerCase() !== 'nexus') || savedLogo) {
      setProfile('custom');
      if (savedName) { $('#f-sysname').value = savedName; onSysName(); }
      if (savedLogo) { $('#f-syslogo').value = savedLogo; const p = $('#logo-prev'); if (p) { p.src = savedLogo; p.style.display = ''; } }
    }
  });

  // Elige el perfil: «nexus» (por defecto) o «custom» (nombre + logo propios).
  function setProfile(v) {
    state.profile = v;
    $$('#prof-cards .card').forEach((x) => x.classList.toggle('sel', x.dataset.v === v));
    const box = $('#prof-fields'); if (box) box.style.display = v === 'custom' ? 'block' : 'none';
  }
  wireCards('#prof-cards', setProfile);

  // Muestra en vivo cómo quedará la wake word al nombrar el sistema. La llama el
  // listener de `input` de #f-sysname (T18b: el HTML ya no lleva `oninput`).
  function onSysName() {
    const n = ($('#f-sysname').value.trim() || 'nexus');
    const h = $('#sysname-hint');
    if (h) h.textContent = `Para despertarlo por voz dirás: «despierta ${n.toLowerCase()}».`;
  }
  $('#f-sysname').addEventListener('input', onSysName);

  // Adjuntar imagen de logo: se lee, se reescala a máx 256 px y se guarda como data-URL en #f-syslogo.
  function onLogoPick(ev) {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const nm = $('#logo-name'); if (nm) nm.textContent = file.name;
    const reader = new FileReader();
    reader.onload = () => {
      const raw = String(reader.result || '');
      const img = new Image();
      img.onload = () => {
        const max = 256;
        let w = img.width || max, h = img.height || max;
        const scale = Math.min(1, max / Math.max(w, h));
        w = Math.max(1, Math.round(w * scale)); h = Math.max(1, Math.round(h * scale));
        let data = raw;
        try {
          const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
          cv.getContext('2d').drawImage(img, 0, 0, w, h);
          data = cv.toDataURL('image/png');
        } catch (e) { data = raw; }   // SVG u otros: guarda el original tal cual
        $('#f-syslogo').value = data;
        const p = $('#logo-prev'); if (p) { p.src = data; p.style.display = ''; }
      };
      img.onerror = () => { $('#f-syslogo').value = raw; const p = $('#logo-prev'); if (p) { p.src = raw; p.style.display = ''; } };
      img.src = raw;
    };
    reader.readAsDataURL(file);
  }
  $('#f-syslogo-file').addEventListener('change', onLogoPick);

  wireCards('#perm-cards', (v) => { state.perm = v;
    $('#perm-folders-box').style.display = v === 'carpetas' ? 'block' : 'none'; });
  wireCards('#db-cards', (v) => { state.db = v;
    $('#db-docker-box').style.display = v === 'docker' ? 'block' : 'none';
    $('#db-server-box').style.display = v === 'server' ? 'block' : 'none'; });

  // INICIO bloque de escape del wizard — lo ejecuta tests/unit/frontend/test_escapes_y_cabeceras.py
  /* SEC-10, cola (task T18c): este wizard pintaba `href="${r.download}"`,
     `${r.out}` y `${r.error}` TAL CUAL salían de /api/setup/docker. Es el mismo
     fallo que se cerró en el HUD, pero en el asistente de primer arranque, que
     se sirve con la CSP nueva… y con `script-src 'unsafe-inline'`, así que un
     manejador en línea inyectado aquí SÍ se ejecutaría.

     T18b movió este script a `frontend/js/setup.js` (la CSP se queda con
     `script-src 'self'`), pero el escape SIGUE siendo una copia a mano de
     `esc()` de frontend/js/core/dom.js — LA FUENTE DE VERDAD — y tiene que
     escapar exactamente lo mismo: `& < > " '`. Si `esc()` cambia allí, cambia
     aquí: esta suite extrae ESTE bloque entre sus dos marcadores, lo EJECUTA y
     lo compara vector a vector con el `esc()` de verdad. Cambiarlo por un
     `import` sin reescribir esa comparación dejaría el wizard sin prueba.

     Y solo `http:`/`https:` llegan a un `href`. ¿Por qué hace falta la
     comprobación en un wizard local? Porque el `download` no lo elige el
     operador: viene de la RESPUESTA del backend, y un enlace que el operador
     pulsa es exactamente el gesto que un `javascript:` necesita. Con esquema
     validado, un valor raro se enseña como texto y no se convierte en botón. */
  const _escapeHtml = (x) => String(x == null ? '' : x)
    .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                                   '"': '&#34;', "'": '&#39;' }[c]));
  /** La URL si es http(s); cadena vacía si no. Nada más llega a un href. */
  const _urlSegura = (u) => (/^https?:\/\//i.test(String(u == null ? '' : u)) ? String(u) : '');

  // HTML del resultado de «crear contenedores». Va en su propia función (y no
  // dentro del clic) para poder ejecutarlo sin navegador.
  function htmlDocker(r) {
    if (!r) return '';
    if (r.ok) return '<span class="ok">✔ Contenedores creados: BD semántica y n8n en marcha.</span>';
    let html = `<span class="bad">✕ ${_escapeHtml(r.error)}</span>\n${_escapeHtml(r.out)}`;
    if (r.download) {
      const u = _urlSegura(r.download);
      html += u
        ? `\nDescarga Docker aquí: <a href="${_escapeHtml(u)}" target="_blank" rel="noopener">${_escapeHtml(u)}</a>`
        : `\nDescarga Docker aquí: <code>${_escapeHtml(r.download)}</code> (no es http(s): no la abro)`;
    }
    return html;
  }
  // FIN bloque de escape del wizard

  $('#btn-docker').addEventListener('click', async () => {
    $('#out-docker').textContent = 'Creando contenedores (puede tardar la primera vez)…';
    const r = await api('/api/setup/docker', { method: 'POST' });
    if (!r) { $('#out-docker').textContent = '✕ sin respuesta del backend'; return; }
    $('#out-docker').innerHTML = htmlDocker(r);
  });

  $('#btn-scan').addEventListener('click', async () => {
    $('#out-models').textContent = 'Buscando modelos…';
    const r = await api('/api/setup/scan_models', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: $('#f-models').value.trim() }) });
    const models = (r && (r.models || r.ollama || [])) || [];
    const list = Array.isArray(models) ? models : Object.values(models).flat();
    $('#out-models').innerHTML = list.length
      ? `<span class="ok">✔ ${list.length} modelo(s):</span> ` + list.slice(0, 12).map((m) => m.name || m).join(' · ')
      : '<span class="bad">No he encontrado modelos ahí. ¿Es la carpeta de Ollama/LM Studio?</span>';
  });

  function resumen() {
    const name = $('#f-name').value.trim() || 'Operador';
    const dbTxt = { local: 'Local (archivos en la instalación)', docker: 'Docker (Postgres+pgvector)',
      server: 'Servidor externo' }[state.db];
    const permTxt = { sandbox: 'Sandbox (solo su carpeta)', carpetas: 'Carpetas concretas',
      todo: 'Todo el equipo' }[state.perm];
    const sys = state.profile === 'custom' ? ($('#f-sysname').value.trim() || 'nexus') : 'nexus';
    const logoTxt = (state.profile === 'custom' && $('#f-syslogo').value.trim()) ? ' (con logo propio)' : '';
    $('#resumen').innerHTML = `Sistema: <b>${sys}</b>${logoTxt} · Operador: <b>${name}</b><br>Personalidad: <b>${state.personality}</b><br>` +
      `Hardware: <b>${$('#f-hw').checked ? 'permitido' : 'bloqueado'}</b> · Archivos: <b>${permTxt}</b><br>` +
      `Memoria: <b>${dbTxt}</b><br><br>Al pulsar TERMINAR se guarda todo y arranca el centro de mando.` +
      `<br>La memoria empieza VACÍA (solo nodos de conocimiento predefinidos).`;
  }

  $('#btn-finish').addEventListener('click', async () => {
    $('#btn-finish').disabled = true;
    // Perfil «nexus» → nombre y logo por defecto; «custom» → los que haya puesto el usuario.
    const custom = state.profile === 'custom';
    const sysName = custom ? ($('#f-sysname').value.trim() || 'nexus') : 'nexus';
    const sysLogo = custom ? $('#f-syslogo').value.trim() : '';
    const cfg = {
      operator_name: $('#f-name').value.trim() || 'Operador',
      assistant_name: sysName,
      assistant_logo: sysLogo,
      wake_word: 'despierta ' + sysName.toLowerCase(),   // se despierta con su propio nombre
      personality: state.personality,
      perm_hardware: $('#f-hw').checked,
      perm_files: state.perm,
      perm_folders: $('#f-folders').value.split('\n').map((x) => x.trim()).filter(Boolean),
      memory_backend: state.db === 'local' ? 'files' : 'auto',
      embed_provider: $('#f-embed') ? $('#f-embed').value : 'auto',
    };
    if (state.db === 'server' && $('#f-dburl').value.trim()) cfg.db_url = $('#f-dburl').value.trim();
    const sec = {};
    const add = (id, k) => { const v = $(id).value.trim(); if (v) sec[k] = v; };
    add('#f-gid', 'google_client_id'); add('#f-gsec', 'google_client_secret');
    add('#f-openai', 'openai_api_key'); add('#f-anthropic', 'anthropic_api_key');
    add('#f-gemini', 'gemini_api_key'); add('#f-eleven', 'elevenlabs_api_key');
    await api('/api/setup/save', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: cfg, secrets: sec }) });
    await api('/api/setup/finish', { method: 'POST' });
    location.href = '/';
  });

  // Aviso de EMBEDDINGS: si el modelo elegido para la memoria semántica no puede
  // generar embeddings (p.ej. solo Anthropic), lo avisa para que no se quede a medias.
  function embedWarn() {
    const w = $('#embed-warn'); if (!w) return;
    const has = (id) => (($(id) && $(id).value) || '').trim().length > 0;
    const embed = $('#f-embed') ? $('#f-embed').value : 'auto';
    const openai = has('#f-openai'), gemini = has('#f-gemini'),
      anthropic = has('#f-anthropic'), ollama = has('#f-models');
    let msg = '';
    if (embed === 'openai' && !openai) msg = 'Has elegido OpenAI para la memoria, pero no has puesto su token arriba.';
    else if (embed === 'gemini' && !gemini) msg = 'Has elegido Gemini para la memoria, pero no has puesto su token arriba.';
    else if (embed === 'ollama' && !ollama) msg = 'Has elegido Ollama para la memoria: ten Ollama instalado (o indica la carpeta de modelos).';
    else if (embed === 'auto' && anthropic && !openai && !gemini && !ollama)
      msg = '⚠ Solo has puesto Anthropic (Claude/Fable), que NO genera embeddings. Para memoria semántica añade Ollama o una key de OpenAI/Gemini; si no, nexus recordará por palabras clave.';
    w.textContent = msg; w.style.display = msg ? 'block' : 'none';
  }
  ['#f-openai', '#f-anthropic', '#f-gemini', '#f-models', '#f-embed'].forEach((id) => {
    const el = $(id); if (el) { el.addEventListener('input', embedWarn); el.addEventListener('change', embedWarn); }
  });

  go(0);
})();
