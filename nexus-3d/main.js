/* ═══════════════════════════════════════════════════════════════
   nexus — Experiencia 3D scroll-driven · enfoque realista
   Fotografía real de producto (CDN Shopify de nexus.com) sobre
   tarjetas 3D flotantes. Sin geometría cartoon: galería fotográfica
   espacial con luz de estudio y tone mapping fílmico.
   Stack 100% gratuito: Three.js 0.160 · GSAP ScrollTrigger · Lenis
   ═══════════════════════════════════════════════════════════════ */

import * as THREE from "three";

/* ── Brand Core ── */
const BG = 0x171717;
const TRACK = 0xc84b31;

/* ── Imágenes reales de producto (CDN público de nexus.com) ── */
const CDN = "https://www.nexus.com/cdn/shop/files/";
const IMG = {
  heroMain: CDN + "DES_AMARILLO.jpg?v=1773040503&width=800", // Do Epic Shit
  heroL: CDN + "SMILE_PRODUCTO_PRINCIPAL_06.jpg?v=1782112894&width=600", // S-miles Azul
  heroR: CDN + "born_to_run_1_4f452ff1-6a05-4ded-8c8f-16daef484586.jpg?v=1758537478&width=600", // Born To Run
  carousel: [
    CDN + "DES_AMARILLO.jpg?v=1773040503&width=600",
    CDN + "FADE2.jpg?v=1779364805&width=600",
    CDN + "smallsteps1_af95a8cf-3df7-43e6-aa29-8699be24375e.jpg?v=1775737556&width=600",
    CDN + "PUSH_YOUR_LIMITS_1.jpg?v=1773040520&width=600",
    CDN + "RunMockup.jpg?v=1730983799&width=600", // Storm Run
    CDN + "FSH_TUR_WEB.jpg?v=1779874710&width=600", // Faster Stronger Harder
    CDN + "born_to_run_1_4f452ff1-6a05-4ded-8c8f-16daef484586.jpg?v=1758537478&width=600",
    CDN + "SMILE_PRODUCTO_PRINCIPAL_06.jpg?v=1782112894&width=600",
  ],
  trail: [
    CDN + "TR01_4.jpg?v=1776835631&width=600", // TR01 Negro
    CDN + "TR01_6.jpg?v=1776835631&width=600", // TR01 Verde
    CDN + "TR01_2.jpg?v=1776835631&width=600", // TR01 Granate
    CDN + "TR01_1.jpg?v=1776835631&width=600", // TR01 Amarillo
  ],
};

/* ── Señal de arranque para la guardia de index.html ── */
window.__WB_BOOTED = true;

/* ── Detección de capacidades ── */
const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const isMobile = window.innerWidth < 768 || /Android|iPhone|iPad/i.test(navigator.userAgent);

function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

const canvas = document.getElementById("scene");
const hasWebGL = webglAvailable();

if (!hasWebGL) {
  document.body.classList.add("no-webgl");
  canvas.remove();
}

/* ── Scroll suave + reveals (también sin WebGL) ── */
gsap.registerPlugin(ScrollTrigger);

let lenis = null;
if (!prefersReduced) {
  document.body.classList.add("motion-ok");
  lenis = new Lenis({ lerp: 0.09, smoothWheel: true });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);

  gsap.utils.toArray(".reveal").forEach((el) => {
    gsap.to(el, {
      opacity: 1,
      y: 0,
      duration: 0.9,
      ease: "power3.out",
      scrollTrigger: { trigger: el, start: "top 88%", once: true },
    });
  });
}

/* ════════════════════════ ESCENA 3D ════════════════════════ */
if (hasWebGL) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, isMobile ? 1.5 : 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; // look fílmico realista
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.FogExp2(BG, 0.02);

  const camera = new THREE.PerspectiveCamera(48, window.innerWidth / window.innerHeight, 0.1, 140);
  const basePos = new THREE.Vector3(0, 1.7, 6.5);
  const lookTarget = new THREE.Vector3(0, 1.8, 0);
  camera.position.copy(basePos);

  /* ── Luz de estudio (afecta al suelo/pista; las fotos van sin tonemapear) ── */
  scene.add(new THREE.HemisphereLight(0xffffff, 0x242424, 0.8));
  const key = new THREE.DirectionalLight(0xfff2d9, 1.1);
  key.position.set(5, 8, 4);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xbfd8ff, 0.25);
  fill.position.set(-6, 3, -4);
  scene.add(fill);

  /* ── Tarjeta fotográfica: foto real con esquinas redondeadas ──
     La imagen se recorta en un canvas (CORS: Shopify CDN sirve
     Access-Control-Allow-Origin:*). Si falla, placa neutra. */
  function roundedPath(ctx, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(r, 0);
    ctx.arcTo(w, 0, w, h, r);
    ctx.arcTo(w, h, 0, h, r);
    ctx.arcTo(0, h, 0, 0, r);
    ctx.arcTo(0, 0, w, 0, r);
    ctx.closePath();
  }

  const photoCards = []; // todas hacen billboard hacia la cámara
  function createCard(url, width = 3) {
    const mat = new THREE.MeshBasicMaterial({
      color: 0x232323,
      toneMapped: false, // color fiel de la fotografía
      transparent: true,
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, width), mat);

    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const aspect = img.height / img.width;
      const cw = 512;
      const ch = Math.round(cw * aspect);
      const c = document.createElement("canvas");
      c.width = cw;
      c.height = ch;
      const ctx = c.getContext("2d");
      roundedPath(ctx, cw, ch, 26);
      ctx.clip();
      ctx.drawImage(img, 0, 0, cw, ch);
      const tex = new THREE.CanvasTexture(c);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 8;
      mat.map = tex;
      mat.color.set(0xffffff);
      mat.needsUpdate = true;
      // Aspecto real vía geometría (deja mesh.scale libre para animaciones)
      mesh.geometry.dispose();
      mesh.geometry = new THREE.PlaneGeometry(width, width * aspect);
    };
    img.onerror = () => mat.color.set(0x2e2e2e); // placa neutra si el CDN falla
    img.src = url;

    photoCards.push(mesh);
    return mesh;
  }

  /* ── Suelo + pista de atletismo (contexto runner, sobrio) ── */
  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(70, 48),
    new THREE.MeshStandardMaterial({ color: 0x121212, roughness: 1 })
  );
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);

  const trackRing = new THREE.Mesh(
    new THREE.RingGeometry(7.4, 11.4, 96),
    new THREE.MeshStandardMaterial({ color: TRACK, roughness: 0.95 })
  );
  trackRing.rotation.x = -Math.PI / 2;
  trackRing.position.y = 0.01;
  scene.add(trackRing);

  for (let i = 0; i < 4; i++) {
    const lane = new THREE.Mesh(
      new THREE.RingGeometry(8.3 + i * 0.8, 8.33 + i * 0.8, 96),
      new THREE.MeshBasicMaterial({ color: 0xf2f0ea, transparent: true, opacity: 0.22 })
    );
    lane.rotation.x = -Math.PI / 2;
    lane.position.y = 0.02;
    scene.add(lane);
  }

  /* ── HERO: tríptico de fotografía real flotante ── */
  const heroMain = createCard(IMG.heroMain, 3.4);
  heroMain.position.set(0, 2.0, 0);
  scene.add(heroMain);

  const heroL = createCard(IMG.heroL, 1.9);
  heroL.position.set(-3.1, 1.35, -1.4);
  scene.add(heroL);

  const heroR = createCard(IMG.heroR, 1.9);
  heroR.position.set(3.2, 2.5, -1.7);
  scene.add(heroR);

  /* ── CARRUSEL DE COLECCIONES: 8 fotos reales orbitando la pista ── */
  const carousel = [];
  IMG.carousel.forEach((url, i) => {
    const card = createCard(url, 2.2);
    card.userData.angle = (i / IMG.carousel.length) * Math.PI * 2;
    card.userData.radius = 8.9;
    card.userData.baseY = 1.7;
    card.scale.setScalar(0.001); // entran al llegar a Colecciones
    card.userData.targetScale = 1;
    scene.add(card);
    carousel.push(card);
  });

  /* ── SENDERO TRAIL (Kilómetros): fotos TR01 reales como hitos ── */
  const trailCurve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(13, 0.05, 3.5),
    new THREE.Vector3(19, 0.05, -2.5),
    new THREE.Vector3(25, 0.05, 3.0),
    new THREE.Vector3(31, 0.05, -2.0),
    new THREE.Vector3(37, 0.05, 2.0),
  ]);
  const trail = new THREE.Mesh(
    new THREE.TubeGeometry(trailCurve, 80, 0.06, 8, false),
    new THREE.MeshStandardMaterial({ color: TRACK, roughness: 0.9 })
  );
  scene.add(trail);

  const trailCards = [];
  IMG.trail.forEach((url, i) => {
    const t = 0.14 + i * 0.24;
    const p = trailCurve.getPoint(t);
    const card = createCard(url, 1.9);
    card.position.set(p.x, 1.65, p.z);
    card.userData.baseY = 1.65;
    scene.add(card);
    trailCards.push(card);
  });

  /* ── Polvo/aire en suspensión (realismo sutil, no neón) ── */
  const N = isMobile ? 180 : 380;
  const airPos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    airPos[i * 3] = (Math.random() - 0.5) * 40 + 8;
    airPos[i * 3 + 1] = Math.random() * 5;
    airPos[i * 3 + 2] = (Math.random() - 0.5) * 24;
  }
  const airGeo = new THREE.BufferGeometry();
  airGeo.setAttribute("position", new THREE.BufferAttribute(airPos, 3));
  const air = new THREE.Points(
    airGeo,
    new THREE.PointsMaterial({
      color: 0xcfcfc8,
      size: 0.035,
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    })
  );
  scene.add(air);

  /* ── Parallax de ratón amortiguado ── */
  const mouse = { x: 0, y: 0 };
  const parallax = { x: 0, y: 0 };
  if (!prefersReduced) {
    window.addEventListener("pointermove", (e) => {
      mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
      mouse.y = (e.clientY / window.innerHeight) * 2 - 1;
    });
  }

  /* ── COREOGRAFÍA DE CÁMARA ──
     Hero (tríptico) → vista de pista con carrusel (Colecciones)
     → macro de la foto principal (Tecnología) → vuelo por el sendero
     de hitos TR01 (Kilómetros) → retorno al producto (CTA) */
  if (!prefersReduced) {
    const tl = gsap.timeline({
      defaults: { ease: "none" },
      scrollTrigger: {
        trigger: "main",
        start: "top top",
        end: "bottom bottom",
        scrub: 1.2,
      },
    });

    // 1 → Colecciones: vista elevada de la pista, el carrusel rodea a la cámara
    tl.to(basePos, { x: 3, y: 7.5, z: 13.5, duration: 1 }, 0);
    tl.to(lookTarget, { x: 0, y: 1.2, z: 0, duration: 1 }, 0);

    // 2 → Tecnología: plano macro de la fotografía principal
    tl.to(basePos, { x: 0.9, y: 2.1, z: 2.7, duration: 1 }, 1);
    tl.to(lookTarget, { x: 0, y: 2.0, z: 0, duration: 1 }, 1);

    // 3 → Kilómetros: vuelo rasante entre los hitos fotográficos TR01
    tl.to(basePos, { x: 11, y: 2.0, z: 6, duration: 1 }, 2);
    tl.to(lookTarget, { x: 16, y: 1.4, z: 0, duration: 1 }, 2);
    tl.to(basePos, { x: 33, y: 2.2, z: 6, duration: 1.3 }, 3);
    tl.to(lookTarget, { x: 39, y: 1.2, z: 0, duration: 1.3 }, 3);

    // 4 → CTA final: plano de venta del producto estrella
    tl.to(basePos, { x: 0, y: 1.9, z: 4.3, duration: 1.2 }, 4.3);
    tl.to(lookTarget, { x: 0, y: 2.0, z: 0, duration: 1.2 }, 4.3);

    // El carrusel entra al llegar a Colecciones
    carousel.forEach((card, i) => {
      gsap.to(card.scale, {
        x: 1,
        y: 1,
        z: 1,
        ease: "back.out(1.6)",
        duration: 0.7,
        delay: i * 0.07,
        scrollTrigger: { trigger: "#colecciones", start: "top 70%", once: true },
        onComplete: () => (card.userData.entered = true),
      });
    });
  } else {
    carousel.forEach((c) => {
      c.scale.setScalar(1);
      c.userData.entered = true;
    });
  }

  /* ── Bucle de render ── */
  const clock = new THREE.Clock();
  let rafId = null;

  function frame() {
    const t = clock.getElapsedTime();

    if (!prefersReduced) {
      // Flotación suave del tríptico hero
      heroMain.position.y = 2.0 + Math.sin(t * 0.9) * 0.07;
      heroL.position.y = 1.35 + Math.sin(t * 1.1 + 1.4) * 0.06;
      heroR.position.y = 2.5 + Math.sin(t * 0.8 + 2.8) * 0.06;

      // El carrusel orbita la pista lentamente
      carousel.forEach((card, i) => {
        const a = card.userData.angle + t * 0.06;
        card.position.set(
          Math.cos(a) * card.userData.radius,
          card.userData.baseY + Math.sin(t * 1.2 + i) * 0.08,
          Math.sin(a) * card.userData.radius
        );
      });

      // Hitos del sendero: flotación mínima
      trailCards.forEach((card, i) => {
        card.position.y = card.userData.baseY + Math.sin(t * 1.0 + i * 1.7) * 0.06;
      });

      // Polvo en suspensión, deriva lenta
      const pos = airGeo.attributes.position;
      for (let i = 0; i < N; i++) {
        let y = pos.getY(i) + 0.0035;
        if (y > 5) y = 0;
        pos.setY(i, y);
      }
      pos.needsUpdate = true;

      // Parallax amortiguado
      parallax.x += (mouse.x * 0.35 - parallax.x) * 0.04;
      parallax.y += (-mouse.y * 0.22 - parallax.y) * 0.04;
    }

    camera.position.set(basePos.x + parallax.x, basePos.y + parallax.y, basePos.z);
    camera.lookAt(lookTarget);

    // Billboard: cada fotografía encara siempre a la cámara
    photoCards.forEach((card) => card.lookAt(camera.position));

    renderer.render(scene, camera);
    if (!prefersReduced) rafId = requestAnimationFrame(frame);
  }
  frame();
  if (prefersReduced) window.addEventListener("scroll", frame, { passive: true });

  /* ── Resize ── */
  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
    if (prefersReduced) frame();
  });

  /* ── Pausa en pestaña oculta ── */
  document.addEventListener("visibilitychange", () => {
    if (prefersReduced) return;
    if (document.hidden && rafId) {
      cancelAnimationFrame(rafId);
      rafId = null;
    } else if (!document.hidden && !rafId) {
      clock.getDelta();
      rafId = requestAnimationFrame(frame);
    }
  });

  /* ── Dispose al descargar ── */
  window.addEventListener("beforeunload", () => {
    scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach((m) => {
          if (m.map) m.map.dispose();
          m.dispose();
        });
      }
    });
    renderer.dispose();
  });
}
