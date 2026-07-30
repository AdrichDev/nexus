/* ============================================================
   WABIKS_CHARTS — gráficos en canvas, cian, sin dependencias.
   Tipos: line, bars (histograma), pie/donut, scatter (correlación),
   deviation (barras vs mediana). Todo se dibuja con la paleta del HUD.
   ============================================================ */
(function () {
  const CY = '#22d3ee', CY2 = '#7cf6c0', BLUE = '#3b82f6', WARN = '#ffb14d',
    PINK = '#ff7ac0', TXT = 'rgba(207,228,245,.72)', GRID = 'rgba(120,170,190,.14)';
  const PIE_COLORS = [CY, CY2, BLUE, PINK, WARN, '#9d7dff', '#4dffd8'];

  function ctxOf(cv) {
    const dpr = window.devicePixelRatio || 1;
    const r = cv.getBoundingClientRect();
    const w = Math.max(80, r.width || cv.clientWidth || 300);
    const h = Math.max(60, r.height || cv.clientHeight || 160);
    cv.width = w * dpr; cv.height = h * dpr;
    const c = cv.getContext('2d');
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, w, h);
    return { c, w, h };
  }
  const fmt = (n) => {
    n = Number(n) || 0;
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(Math.round(n));
  };

  function line(cv, data) {
    const { c, w, h } = ctxOf(cv);
    const vals = (data.values || []).map(Number);
    if (!vals.length) return;
    const pad = { l: 40, r: 10, t: 12, b: 18 };
    const min = Math.min(...vals), max = Math.max(...vals);
    const rng = (max - min) || 1;
    const X = (i) => pad.l + (w - pad.l - pad.r) * (i / Math.max(1, vals.length - 1));
    const Y = (v) => pad.t + (h - pad.t - pad.b) * (1 - (v - min) / rng);
    c.strokeStyle = GRID; c.lineWidth = 1; c.fillStyle = TXT; c.font = '10px monospace';
    for (let g = 0; g <= 3; g++) {
      const y = pad.t + (h - pad.t - pad.b) * g / 3;
      c.beginPath(); c.moveTo(pad.l, y); c.lineTo(w - pad.r, y); c.stroke();
      c.fillText(fmt(max - rng * g / 3), 2, y + 3);
    }
    const grad = c.createLinearGradient(0, pad.t, 0, h - pad.b);
    grad.addColorStop(0, 'rgba(34,211,238,.28)'); grad.addColorStop(1, 'rgba(34,211,238,0)');
    c.beginPath(); c.moveTo(X(0), Y(vals[0]));
    vals.forEach((v, i) => c.lineTo(X(i), Y(v)));
    c.lineTo(X(vals.length - 1), h - pad.b); c.lineTo(X(0), h - pad.b); c.closePath();
    c.fillStyle = grad; c.fill();
    c.beginPath(); c.moveTo(X(0), Y(vals[0]));
    vals.forEach((v, i) => c.lineTo(X(i), Y(v)));
    c.strokeStyle = CY; c.lineWidth = 2; c.shadowColor = CY; c.shadowBlur = 6; c.stroke();
    c.shadowBlur = 0;
    const li = vals.length - 1;
    c.beginPath(); c.arc(X(li), Y(vals[li]), 3, 0, 7); c.fillStyle = CY2; c.fill();
  }

  function bars(cv, data, color) {
    const { c, w, h } = ctxOf(cv);
    const vals = (data.values || []).map(Number), labels = data.labels || [];
    if (!vals.length) return;
    const pad = { l: 38, r: 8, t: 12, b: 34 };
    const max = Math.max(...vals, 1);
    const bw = (w - pad.l - pad.r) / vals.length;
    c.strokeStyle = GRID; c.fillStyle = TXT; c.font = '10px monospace';
    for (let g = 0; g <= 3; g++) {
      const y = pad.t + (h - pad.t - pad.b) * g / 3;
      c.beginPath(); c.moveTo(pad.l, y); c.lineTo(w - pad.r, y); c.stroke();
      c.fillText(fmt(max - max * g / 3), 2, y + 3);
    }
    vals.forEach((v, i) => {
      const bh = (h - pad.t - pad.b) * (v / max);
      const x = pad.l + bw * i + bw * 0.15, y = h - pad.b - bh;
      const g = c.createLinearGradient(0, y, 0, h - pad.b);
      g.addColorStop(0, color || CY); g.addColorStop(1, 'rgba(34,211,238,.15)');
      c.fillStyle = g; c.fillRect(x, y, bw * 0.7, bh);
      c.save(); c.translate(x + bw * 0.35, h - pad.b + 4); c.rotate(-Math.PI / 5);
      c.fillStyle = TXT; c.font = '9px monospace'; c.textAlign = 'right';
      c.fillText(String(labels[i] || '').slice(0, 14), 0, 0); c.restore();
    });
  }

  function deviation(cv, data) {
    const { c, w, h } = ctxOf(cv);
    const items = data || [];
    if (!items.length) return;
    const median = items[0].median || 0;
    const pad = { l: 38, r: 8, t: 12, b: 34 };
    const max = Math.max(...items.map((d) => d.value), median, 1);
    const bw = (w - pad.l - pad.r) / items.length;
    const Y = (v) => pad.t + (h - pad.t - pad.b) * (1 - v / max);
    items.forEach((d, i) => {
      const up = d.value >= median;
      const x = pad.l + bw * i + bw * 0.15;
      const y = Y(d.value), base = Y(median);
      c.fillStyle = up ? CY2 : WARN;
      c.fillRect(x, Math.min(y, base), bw * 0.7, Math.abs(base - y) || 2);
      c.save(); c.translate(x + bw * 0.35, h - pad.b + 4); c.rotate(-Math.PI / 5);
      c.fillStyle = TXT; c.font = '9px monospace'; c.textAlign = 'right';
      c.fillText(String(d.label || '').slice(0, 14), 0, 0); c.restore();
    });
    const my = Y(median);
    c.strokeStyle = CY; c.setLineDash([4, 3]); c.lineWidth = 1;
    c.beginPath(); c.moveTo(pad.l, my); c.lineTo(w - pad.r, my); c.stroke(); c.setLineDash([]);
    c.fillStyle = CY; c.font = '9px monospace'; c.fillText('mediana ' + fmt(median), pad.l + 2, my - 3);
  }

  function pie(cv, data) {
    const { c, w, h } = ctxOf(cv);
    const items = (data || []).filter((d) => d.value > 0);
    const total = items.reduce((a, d) => a + d.value, 0) || 1;
    const cx = h / 2 + 6, cy = h / 2, R = Math.min(cx, cy) - 10;
    let a0 = -Math.PI / 2;
    items.forEach((d, i) => {
      const a1 = a0 + (d.value / total) * Math.PI * 2;
      c.beginPath(); c.moveTo(cx, cy); c.arc(cx, cy, R, a0, a1); c.closePath();
      c.fillStyle = PIE_COLORS[i % PIE_COLORS.length]; c.fill();
      a0 = a1;
    });
    c.beginPath(); c.arc(cx, cy, R * 0.55, 0, 7); c.fillStyle = '#0a1520'; c.fill();
    // leyenda
    c.font = '11px monospace'; c.textAlign = 'left';
    items.forEach((d, i) => {
      const y = 16 + i * 18;
      c.fillStyle = PIE_COLORS[i % PIE_COLORS.length]; c.fillRect(cx + R + 12, y - 8, 10, 10);
      c.fillStyle = TXT;
      c.fillText(`${d.label} · ${Math.round(d.value / total * 100)}%`, cx + R + 28, y);
    });
  }

  function scatter(cv, pts, opts) {
    const { c, w, h } = ctxOf(cv);
    const P = pts || [];
    if (!P.length) return;
    const pad = { l: 40, r: 10, t: 12, b: 24 };
    const xs = P.map((p) => p.x), ys = P.map((p) => p.y);
    const xmin = Math.min(...xs), xmax = Math.max(...xs) || 1;
    const ymin = Math.min(...ys), ymax = Math.max(...ys) || 1;
    const xr = (xmax - xmin) || 1, yr = (ymax - ymin) || 1;
    const X = (x) => pad.l + (w - pad.l - pad.r) * (x - xmin) / xr;
    const Y = (y) => pad.t + (h - pad.t - pad.b) * (1 - (y - ymin) / yr);
    c.strokeStyle = GRID; c.fillStyle = TXT; c.font = '10px monospace';
    for (let g = 0; g <= 3; g++) {
      const y = pad.t + (h - pad.t - pad.b) * g / 3;
      c.beginPath(); c.moveTo(pad.l, y); c.lineTo(w - pad.r, y); c.stroke();
      c.fillText(fmt(ymax - yr * g / 3), 2, y + 3);
    }
    // recta de tendencia (mínimos cuadrados) → correlación visible
    const n = P.length, sx = xs.reduce((a, b) => a + b, 0), sy = ys.reduce((a, b) => a + b, 0);
    const sxy = P.reduce((a, p) => a + p.x * p.y, 0), sxx = xs.reduce((a, b) => a + b * b, 0);
    const den = (n * sxx - sx * sx) || 1;
    const m = (n * sxy - sx * sy) / den, b = (sy - m * sx) / n;
    c.strokeStyle = 'rgba(124,246,192,.7)'; c.lineWidth = 1.5;
    c.beginPath(); c.moveTo(X(xmin), Y(m * xmin + b)); c.lineTo(X(xmax), Y(m * xmax + b)); c.stroke();
    P.forEach((p) => {
      c.beginPath(); c.arc(X(p.x), Y(p.y), 4, 0, 7);
      c.fillStyle = CY; c.shadowColor = CY; c.shadowBlur = 6; c.fill(); c.shadowBlur = 0;
    });
    if (opts && opts.xlabel) { c.fillStyle = TXT; c.font = '10px monospace'; c.textAlign = 'center'; c.fillText(opts.xlabel, w / 2, h - 4); }
  }

  window.WABIKS_CHARTS = { line, bars, pie, scatter, deviation };
})();
