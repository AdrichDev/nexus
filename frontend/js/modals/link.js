/* ==========================================================
   nexus — vincular el movil: QR, tunel y aparatos emparejados.
   El QR lleva la direccion por la que el movil alcanza a nexus.
   El tunel sobrevive a los reinicios, asi que no hay que volver
   a escanear cada vez.
   ========================================================== */
import { $, esc, api } from '../core/dom.js';
import { state } from '../core/state.js';
import { pushLog } from '../core/log.js';
import { go } from '../core/nav.js';

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
export function paintLinkBadge() {
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
export function refreshDevices() {
  return api('/api/link/status').then((st) => {
    _pairedDevs = (st && st.devices) || [];
    paintLinkBadge(); renderLinkDevices();
    return st;
  }).catch(() => {});
}
export function onPaired(data) {
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
export function onUnpaired(data) {
  refreshDevices().then(() => {
    // sin ningún móvil vinculado → directo a la pantalla de VINCULAR (QR)
    if (!_pairedDevs.length) openLinkModal();
  });
  if (data && data.name) pushLog('info', `📱 ${data.name} desvinculado`);
}

export async function openLinkModal() {
  const m = $('#config-modal');
  // #config-modal se COMPARTE con la configuración: si venía de allí, fuera el pop up
  $('#cfg-pop')?.classList.add('hidden');
  $('#config-body').innerHTML = `<h2>📱 VINCULAR EL MÓVIL</h2>
    <div class="lk-info">En el móvil: app de nexus → «VINCULAR CON nexus» → apunta la cámara a
    este QR. El QR ya vale en tu WiFi al instante; en unos segundos se actualiza para que valga
    <b>desde cualquier red</b>.<br>
    <b style="color:var(--cy)">Para que no haya que revincular nunca más</b>: instala
    <a href="https://tailscale.com/download" class="ext">Tailscale</a> en el PC y en el móvil con
    la misma cuenta. Le da al PC una dirección fija que sobrevive a los reinicios; sin él, la del
    túnel cambia en cada arranque.</div>
    <div id="lk-qr" class="lk-qr"><span class="dots">generando QR</span></div>
    <div id="lk-state" class="lk-state">…</div>
    <div id="lk-devices" class="lk-devices"></div>
    <div class="modal-btns"><button class="ghost" id="lk-close">Cerrar</button>
      <button class="ghost" id="lk-unlink" style="color:#ff5470;border-color:rgba(255,84,112,.5)">⛓ Desvincular</button>
      <button id="lk-refresh">↻ Regenerar QR</button></div>`;
  m.classList.remove('hidden');
  m.onclick = (e) => { if (e.target === m) { m.classList.add('hidden'); _stopLinkPoll(); } };
  $('#lk-close').addEventListener('click', () => { m.classList.add('hidden'); _stopLinkPoll(); });
  $('#lk-refresh').addEventListener('click', () => go(true));
  $('#lk-unlink').addEventListener('click', async () => {
    if (!confirm('¿Desvincular TODOS los móviles? El enlace viejo deja de valer y habrá que escanear el QR nuevo.')) return;
    await api('/api/link/reset', { method: 'POST' });
    _pairedDevs = []; paintLinkBadge(); renderLinkDevices();
    pushLog('info', '📱 Desvinculado: token nuevo. Escanea el QR para volver a vincular.');
    go(true);
  });

  async function go(retry) {
    if (retry) { $('#lk-qr').innerHTML = '<span class="dots">regenerando</span>'; api('/api/link/start', { method: 'POST' }); }
    const st = await api('/api/link/status');
    if (!st || !st.link) { $('#lk-state').textContent = 'Backend sin respuesta — ¿está nexus arrancado?'; return; }
    _drawQR(st.link);
    _pairedDevs = st.devices || _pairedDevs; paintLinkBadge(); renderLinkDevices();
    /* Tres formas de llegar, y NO son equivalentes. La del túnel cambia de
       dirección en cada arranque, así que el móvil se queda colgado en cuanto
       reinicias el PC. La de Tailscale es fija. Que se vea cuál estás usando. */
    const ts = st.tailscale || {};
    if (st.via === 'tailscale') {
      $('#lk-state').innerHTML =
        `<b style="color:var(--ok)">✔ Tailscale — dirección FIJA</b><br>`
        + `<code>${esc(ts.ip || '')}</code> · vale desde cualquier red y <b>no cambia al `
        + `reiniciar</b>. El móvil necesita Tailscale con tu misma cuenta.`;
    } else if (st.tunnel) {
      $('#lk-state').innerHTML =
        `<b style="color:var(--ok)">✔ Túnel activo</b> — el QR vale desde CUALQUIER red<br>`
        + `<code>${esc(st.url)}</code>`
        + `<br><span style="color:var(--warn,#ffd23a)">⚠ Esta dirección CAMBIA cada vez que `
        + `arranca nexus: al reiniciar el PC habrá que volver a escanear el QR. `
        + `Con Tailscale sería fija — <a href="https://tailscale.com/download" class="ext">`
        + `instalarlo</a>${ts.error ? ' (' + esc(ts.error) + ')' : ''}.</span>`;
    } else {
      $('#lk-state').innerHTML =
        `<b style="color:var(--warn,#ffd23a)">⚠ Túnel arrancando…</b> — el QR ya vale en tu WiFi `
        + `(<code>${esc(st.lan)}</code>).`
        + (st.error ? `<br><span style="color:var(--err)">${esc(st.error)}</span>` : '');
    }
  }

  go(false);                         // 1) pinta YA (LAN)
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
