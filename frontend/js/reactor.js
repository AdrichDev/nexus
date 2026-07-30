/* ==========================================================
   nexus — Reactor: red neuronal de partículas (canvas)
   Núcleo tipo arc-reactor que PULSA según el estado.
   Fábrica multi-instancia: attach(canvas) → {setState}.
   window.setReactorState(s) afecta a TODAS las instancias.
   Auto-attach de #reactor si existe al cargar (compat móvil).
   ========================================================== */
(function () {
  const HUE = window.NEXUS_HUE || '0,229,255';   // cian por defecto
  const TARGET_ENERGY = { idle: 0.18, listening: 0.78, thinking: 0.5, speaking: 1.0 };
  const instances = [];

  function attach(canvas, opts) {
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    const DPR = Math.min(window.devicePixelRatio || 1, 1.25);
    const N = (opts && opts.particles) || 60;
    const LINK = (opts && opts.link) || 110;
    const particles = [];
    let W = 0, H = 0, CX = 0, CY = 0, state = 'idle', energy = 0, t = 0, last = 0;

    function resize() {
      W = canvas.width = canvas.offsetWidth * DPR;
      H = canvas.height = canvas.offsetHeight * DPR;
      CX = W / 2; CY = H / 2;
    }
    function init() {
      resize(); particles.length = 0;
      for (let i = 0; i < N; i++) {
        particles.push({
          ang: Math.random() * Math.PI * 2,
          baseRad: (0.12 + Math.random() * 0.33) * Math.min(W, H),
          speed: (0.0018 + Math.random() * 0.004) * (Math.random() < 0.5 ? 1 : -1),
          size: 1 + Math.random() * 2.2, wob: Math.random() * Math.PI * 2,
        });
      }
    }
    function frame(now) {
      inst._raf = requestAnimationFrame(frame);
      if (document.hidden || now - last < 33) return;
      last = now;
      if (canvas.offsetWidth * DPR !== W) resize();
      t += 0.033;
      energy += (TARGET_ENERGY[state] - energy) * 0.05;
      ctx.clearRect(0, 0, W, H);
      const pulse = 1 + Math.sin(t * (2 + energy * 6)) * 0.05 * (0.4 + energy);
      const coreR = Math.min(W, H) * 0.085 * pulse;
      for (let i = 3; i >= 1; i--) {
        ctx.beginPath(); ctx.arc(CX, CY, coreR * (0.55 + i * 0.35), 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${HUE},${0.12 * i * (0.4 + energy)})`;
        ctx.lineWidth = (i === 1 ? 2.5 : 1) * DPR; ctx.stroke();
      }
      const g = ctx.createRadialGradient(CX, CY, 0, CX, CY, coreR);
      g.addColorStop(0, `rgba(${HUE},${0.55 + energy * 0.45})`);
      g.addColorStop(0.6, `rgba(${HUE},${0.18 + energy * 0.2})`);
      g.addColorStop(1, `rgba(${HUE},0)`);
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(CX, CY, coreR, 0, Math.PI * 2); ctx.fill();
      ctx.save(); ctx.translate(CX, CY); ctx.rotate(t * (0.4 + energy * 1.6));
      for (let k = 0; k < 10; k++) {
        ctx.rotate(Math.PI / 5); ctx.beginPath(); ctx.arc(0, 0, coreR * 1.55, -0.22, 0.22);
        ctx.strokeStyle = `rgba(${HUE},${0.35 + energy * 0.5})`; ctx.lineWidth = 3 * DPR; ctx.stroke();
      }
      ctx.restore();
      const pts = [];
      for (const p of particles) {
        p.ang += p.speed * (1 + energy * 2.2); p.wob += 0.02;
        const r = p.baseRad + Math.sin(p.wob) * 10 * (0.5 + energy) + energy * 18 * Math.sin(t * 3 + p.wob);
        pts.push({ x: CX + Math.cos(p.ang) * r, y: CY + Math.sin(p.ang) * r * 0.86, size: p.size });
      }
      ctx.lineWidth = 1 * DPR;
      const linkD = LINK * DPR * (1 + energy * 0.35);
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
          if (d < linkD) {
            ctx.strokeStyle = `rgba(${HUE},${(1 - d / linkD) * (0.16 + energy * 0.3)})`;
            ctx.beginPath(); ctx.moveTo(pts[i].x, pts[i].y); ctx.lineTo(pts[j].x, pts[j].y); ctx.stroke();
          }
        }
      }
      for (const p of pts) {
        ctx.fillStyle = `rgba(${HUE},${0.6 + energy * 0.4})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.size * DPR * (1 + energy * 0.5), 0, Math.PI * 2); ctx.fill();
      }
    }
    const inst = {
      _raf: 0,
      setState: (s) => { state = (s in TARGET_ENERGY) ? s : 'idle'; },
      destroy: () => { cancelAnimationFrame(inst._raf); const i = instances.indexOf(inst); if (i >= 0) instances.splice(i, 1); },
    };
    init();
    inst._raf = requestAnimationFrame(frame);
    instances.push(inst);
    return inst;
  }

  window.WABIKS_REACTOR = { attach };
  window.setReactorState = (s) => instances.forEach((i) => i.setState(s));
  // Compat: auto-attach si ya existe #reactor (móvil)
  document.addEventListener('DOMContentLoaded', () => {
    const c = document.getElementById('reactor');
    if (c && !c._attached) { c._attached = true; attach(c); }
  });
})();
