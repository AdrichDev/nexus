"""
nexus — Servidor FastAPI: API local + WebSocket en tiempo real + HUD.

Endpoints principales:
  GET  /                  → HUD (frontend)
  WS   /ws                → eventos en tiempo real (logs, métricas, estado…)
  POST /api/command       → {"text": "..."} → respuesta de nexus
  POST /api/voice         → dispara un ciclo de voz completo (como F9)
  GET  /api/skills        → skills cargadas
  GET  /api/status        → estado de todos los subsistemas
  GET/POST /api/config    → leer / cambiar configuración en caliente
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.core import brain, contentos, stt, tts
from backend.core.app_index import start_background_index
from backend.core.config import FRONTEND_DIR, settings
from backend.core.events import bus
from backend.core.hotkey import start_hotkey
from backend.core.memory import graph, memory_status
from backend.core.scheduler import scheduler_loop, system_metrics
from backend.core.skills_loader import load_skills, skills_summary
from backend.core.telegram_bridge import telegram_loop
from backend.core.voice_cycle import open_mic_loop, voice_cycle

async def _arranca_runtime_llm() -> None:
    """Verificación inicial del cerebro, tolerante a fallos: si Ollama tarda o
    no está, el arranque sigue igual y el estado queda anotado."""
    try:
        from backend.core import llm_runtime
        await llm_runtime.initialize_llm_runtime()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque del núcleo (sustituye al deprecado on_event('startup'))."""
    loop = asyncio.get_running_loop()
    bus.attach_loop(loop)
    load_skills()
    start_hotkey(loop)
    start_background_index()   # escanea TODAS las apps instaladas (Windows)
    asyncio.create_task(asyncio.to_thread(stt.preload_model))  # precarga el modelo de voz
    from backend.core.wake import wake_loop
    from backend.core.background import cycle_loop, proactive_loop
    from backend.core import engram_bridge
    tasks = [asyncio.create_task(scheduler_loop()),
             asyncio.create_task(telegram_loop()),   # solo activo con TELEGRAM_BOT_TOKEN
             asyncio.create_task(open_mic_loop()),   # solo activo con open_mic=true
             asyncio.create_task(wake_loop()),       # «di nexus» (wake_enabled=true)
             asyncio.create_task(cycle_loop()),      # reentreno cíclico + reindex del RAG
             asyncio.create_task(proactive_loop()),  # PM proactivo: recordatorios + empujón diario
             # Instala Engram al arrancar si falta (cubre el nexus.exe, que no pasa por run.bat)
             asyncio.create_task(engram_bridge.maybe_install_background({"settings": settings})),
             # Comprueba el cerebro AL ARRANCAR (en segundo plano, no retrasa el HUD):
             # nexus sabe si tiene modelo antes de que le preguntes, en vez de
             # descubrirlo a mitad de la primera respuesta.
             asyncio.create_task(_arranca_runtime_llm())]
    for line in brain.boot_report():
        await bus.emit("boot", line)
    yield
    for t in tasks:
        t.cancel()
    from backend.core import net
    await net.aclose()   # cierra el pool de conexiones HTTP compartido


app = FastAPI(title="nexus", version="1.0.0", lifespan=lifespan)


# ---------- AUTENTICACIÓN REMOTA (vinculación por QR, fuera de la WiFi) ----------
# El tráfico del túnel cloudflared llega con la cabecera Cf-Connecting-Ip.
# Local/LAN pasa libre; lo remoto necesita el token de vinculación del QR.
# specs v24: el HUD se quedaba con el CSS/JS viejo en caché y Adri no veía los
# cambios (los iconos salían sin color aunque el archivo del disco ya era el
# nuevo). Los estáticos del HUD NO se cachean: siempre la última versión.
@app.middleware("http")
async def no_cache_estaticos(request, call_next):
    resp = await call_next(request)
    try:
        if request.url.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


@app.middleware("http")
async def remote_auth(request, call_next):
    if request.headers.get("cf-connecting-ip"):
        from backend.core import remote
        tok = (request.query_params.get("token")
               or request.headers.get("x-nexus-token", "")
               or request.cookies.get("nexus_token", ""))
        if tok != remote.link_token():
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "no autorizado — vincula el móvil con el QR de nexus"},
                                status_code=401)
        response = await call_next(request)
        response.set_cookie("nexus_token", tok, max_age=86400 * 365)
        return response
    return await call_next(request)


class Command(BaseModel):
    text: str
    speak: bool = False
    voice: bool = False      # true si el texto es TRANSCRIPCIÓN de voz (móvil)
    channel: str = "pc"      # pc | mobile — quién manda la orden (habla solo ese aparato)


class SayText(BaseModel):
    """Cuerpo de /api/tts_say (la voz del móvil). FALTABA esta clase y el backend
    moría al arrancar con NameError — por eso el último run.bat no levantaba."""
    text: str = ""


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    from backend.core import remote
    # WS remoto (túnel) → exige el token del QR; local/LAN pasa libre
    if ws.headers.get("cf-connecting-ip"):
        if ws.query_params.get("token", "") != remote.link_token():
            await ws.close(code=4401)
            return
    await ws.accept()
    bus.register(ws)
    # Reenvía historial reciente para que el HUD reconecte con contexto
    import json
    for evt in bus.history[-30:]:
        await ws.send_text(json.dumps(evt, ensure_ascii=False, default=str))
    my_device = None      # ficha del móvil si este WS se presenta como tal
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"type": "command", "text": raw}
            mtype = msg.get("type")
            if mtype == "hello" and msg.get("role") == "mobile":
                # El móvil acaba de VINCULARSE: lo registramos, avisamos al HUD
                # (para cerrar el QR y mostrar el dispositivo) y le confirmamos.
                ip = (ws.headers.get("cf-connecting-ip")
                      or (ws.client.host if ws.client else ""))
                my_device = remote.register_device({
                    "id": msg.get("id", ""), "name": msg.get("name", ""),
                    "ua": msg.get("ua", ""), "ip": ip})
                await ws.send_text(json.dumps({"type": "paired_ack", "data": {
                    "pc": settings.get("operator_name", "tu PC"),
                    "name": my_device["name"]}}, ensure_ascii=False))
                await bus.emit("paired", {"name": my_device["name"],
                                          "id": my_device["id"],
                                          "count": len(remote.devices())})
                await bus.emit("log", {"level": "ok",
                                       "msg": f"📱 Móvil vinculado: {my_device['name']}"})
            elif mtype == "command":
                result = await brain.process(
                    msg.get("text", ""),
                    source=("voice" if msg.get("voice") else "text"),
                    channel=("mobile" if my_device else "pc"))
                if msg.get("speak"):
                    asyncio.create_task(tts.speak(result["reply"]))
            elif mtype == "voice":
                asyncio.create_task(voice_cycle())
    except WebSocketDisconnect:
        bus.unregister(ws)
        if my_device:
            # NO se desvincula: móvil bloqueado o app en 2º plano = WS cortado,
            # pero SIGUE vinculado. Se marca «en espera» y solo si no vuelve en
            # 10 min se olvida de verdad (antes el HUD decía «no vinculado» al
            # instante — bug grave reportado por Adri).
            did, name = my_device["id"], my_device["name"]
            remote.mark_offline(did)
            try:
                await bus.emit("log", {"level": "info",
                               "msg": f"📱 {name} en segundo plano — sigue vinculado"})
            except Exception:
                pass

            async def _grace_forget(did=did, name=name):
                await asyncio.sleep(600)
                if not remote.is_online(did):
                    remote.forget_device(did)
                    try:
                        await bus.emit("unpaired", {"id": did, "name": name,
                                                    "count": len(remote.devices())})
                    except Exception:
                        pass
            asyncio.create_task(_grace_forget())


@app.post("/api/command")
async def api_command(cmd: Command):
    result = await brain.process(cmd.text, source=("voice" if cmd.voice else "text"),
                                 channel=("mobile" if cmd.channel == "mobile" else "pc"))
    if cmd.speak:
        asyncio.create_task(tts.speak(result["reply"]))
    return result


@app.post("/api/voice")
async def api_voice():
    return await voice_cycle()


# ---------------------- MULTITAREA (panel de trabajos concurrentes) ----------------------
@app.get("/api/weather")
async def api_weather():
    """Tiempo actual para el header del HUD (v23 T15). {} si el servicio falla:
    un fallo del servicio meteorológico no puede bloquear el resto de nexus."""
    from backend.core import briefing
    try:
        return await briefing.weather_now()
    except Exception:
        return {}


@app.get("/api/jobs")
async def api_jobs():
    from backend.core.jobs import jobs
    return {"list": jobs.snapshot(), "counts": jobs.counts(), "badge": jobs.badge()}


@app.post("/api/jobs")
async def api_jobs_submit(payload: dict):
    """Lanza una orden como TRABAJO en segundo plano (multitarea).
    v23 (T9): cada ejecución lleva su requestId y los duplicados vivos se bloquean."""
    import uuid as _uuid
    from backend.core.jobs import jobs
    text = str(payload.get("text", "")).strip()
    if not text:
        return {"error": "sin texto"}
    channel = str(payload.get("channel", "pc"))
    dup = jobs.active_duplicate(text, channel)
    if dup:
        return {"ok": False, "duplicate": True, "id": dup["id"], "num": dup["num"],
                "error": f"ese trabajo ya está en marcha (#{dup['num']}, {dup['status']})"}
    rid = str(payload.get("request_id") or _uuid.uuid4().hex[:8])
    jid = await jobs.submit(text, lambda: brain.process(text, source="job",
                                                        channel=channel, request_id=rid),
                            request_id=rid, request=text, channel=channel,
                            dedupe_key=text)
    return {"ok": True, "id": jid, "request_id": rid}


@app.post("/api/jobs/{jid}/cancel")
async def api_jobs_cancel(jid: str):
    from backend.core.jobs import jobs
    return {"ok": await jobs.cancel(jid)}


@app.post("/api/jobs/seen")
async def api_jobs_seen(payload: dict | None = None):
    """Marca los resultados como REVISADOS: limpia el ✓ / ! del sidebar (v23 T10)."""
    from backend.core.jobs import jobs
    jid = str((payload or {}).get("id", ""))
    return {"seen": await jobs.mark_seen(jid), "badge": jobs.badge()}


@app.post("/api/jobs/clear")
async def api_jobs_clear():
    from backend.core.jobs import jobs
    return {"removed": jobs.clear_done()}


# ── GANCHO DE PRUEBAS (v23 T22) ────────────────────────────────────────────────
# Solo existe cuando se arranca con NEXUS_E2E=1 (lo hace el runner de las pruebas
# end-to-end). En un nexus normal esta ruta NO está registrada.
if os.environ.get("NEXUS_E2E") == "1":

    @app.post("/api/_e2e/job")
    async def api_e2e_job(payload: dict):
        """Lanza un trabajo controlado (duerme N segundos) para poder verificar en
        la interfaz real el indicador de Multitarea: En curso → 2 → ✓ / !."""
        from backend.core.jobs import jobs
        secs = float(payload.get("seconds", 2))
        fail = bool(payload.get("fail"))
        title = str(payload.get("title", "Trabajo de prueba"))

        async def _work():
            await asyncio.sleep(secs)
            if fail:
                raise RuntimeError("fallo provocado por la prueba e2e")
            return {"reply": f"{title}: terminado tras {secs}s",
                    "files": [{"path": "e2e/salida.txt", "action": "creado"}]}
        jid = await jobs.submit(title, _work, request=title, channel="pc",
                                dedupe_key=title, notify=bool(payload.get("notify")))
        return {"ok": True, "id": jid}


@app.get("/api/skills")
async def api_skills():
    return skills_summary()


@app.get("/api/skill/{folder}")
async def api_skill_detail(folder: str):
    """Contenido de una skill para la pantalla de nodo: SKILL.md + intents + patrones."""
    from backend.core.skills_loader import get_skills
    from backend.core.config import SKILLS_DIR
    s = get_skills().get(folder)
    if not s:
        return {"error": "not found"}
    doc = ""
    md = SKILLS_DIR / folder / "SKILL.md"
    if md.exists():
        doc = md.read_text(encoding="utf-8", errors="replace")
    return {"folder": folder, "name": s.name, "description": s.description,
            "status": s.status, "calls": s.calls,
            "intents": list(s.patterns.keys()),
            "patterns": {k: v.pattern for k, v in s.patterns.items()},
            "doc": doc}


@app.get("/api/knowledge")
async def api_knowledge_list():
    """Biblioteca de conocimiento importada (openClaw/Gru): lista de SKILL.md."""
    from backend.core.config import ROOT
    kdir = ROOT / "knowledge"
    out = []
    if kdir.is_dir():
        for md in sorted(kdir.rglob("SKILL.md")):
            try:
                txt = md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            title = next((l.lstrip("# ").strip() for l in txt.splitlines() if l.startswith("#")),
                         md.parent.name)
            out.append({"name": md.parent.name, "title": title,
                        "chars": len(txt), "excerpt": txt[:220]})
    return {"count": len(out), "skills": out}


@app.get("/api/status")
async def api_status():
    return {
        "metrics": system_metrics(),
        "memory": memory_status(),
        "stt": stt.stt_status(),
        "tts": tts.tts_status(),
        "llm": {"provider": settings.get("llm_provider"),
                "ollama_model": settings.get("ollama_model"),
                "cloud_model": settings.get("cloud_model")},
        "skills": len(skills_summary()),
    }


@app.get("/api/graph")
async def api_graph():
    """Nodos y enlaces del grafo de memoria (para la vista de nodos del HUD)."""
    return graph.graph()


@app.get("/api/note")
async def api_note(name: str = ""):
    """Contenido de una nota del grafo (para el panel lateral del nodo)."""
    from backend.core.memory import MEMORY_DIR
    for p in MEMORY_DIR.rglob("*.md"):
        if p.stem == name:
            try:
                return {"name": p.stem, "content": p.read_text(encoding="utf-8")[:6000]}
            except Exception:
                break
    return {"name": name, "content": ""}


@app.get("/api/local_models")
async def api_local_models():
    """Modelos LLM locales detectados (Ollama, LM Studio) para el selector de ⚙."""
    from backend.core.llm import scan_local_models
    return await scan_local_models()


# ─── RUNTIME DE MODELOS ───────────────────────────────────────────────────────
# Un solo sitio decide qué cerebro está funcionando, y lo decide PROBÁNDOLO.
# (El HUD ya no clasifica modelos por su cuenta ni deduce el «EN USO» de la
#  configuración guardada: pregunta aquí.)
@app.get("/api/llm/status")
async def api_llm_status(verify: bool = False):
    """Estado REAL del cerebro. `?verify=1` fuerza una comprobación nueva."""
    from backend.core import llm_runtime as rt
    st = await rt.verify_current(force=True) if verify else rt.status()
    if verify or st.checked_at:
        return st.publico()
    return (await rt.verify_current()).publico()


@app.get("/api/llm/status_full")
async def api_llm_status_full():
    """Igual pero con el detalle técnico: para el panel de diagnóstico."""
    from backend.core import llm_runtime as rt
    return (await rt.verify_current()).tecnico()


@app.get("/api/llm/models")
async def api_llm_models():
    """Catálogo YA CLASIFICADO: qué sirve Ollama, qué está solo en disco y qué
    es de embeddings. La interfaz solo pinta."""
    from backend.core import llm_runtime as rt
    return await rt.catalog()


class LLMActivate(BaseModel):
    provider: str = "ollama"
    model: str = ""


@app.post("/api/llm/activate")
async def api_llm_activate(payload: LLMActivate):
    """Activa un cerebro. Solo se guarda si RESPONDE a una inferencia real:
    si falla, la configuración se queda como estaba y se devuelve el motivo."""
    from backend.core import llm_runtime as rt
    st = await rt.activate(payload.provider, payload.model)
    await bus.emit("log", {"level": "ok" if st.active else "warn", "msg": st.resumen()})
    return st.publico()


@app.get("/api/voices")
async def api_voices():
    """Catálogo de voces reales disponibles por motor (para el selector de ⚙)."""
    return tts.all_voices()


@app.get("/api/audio_devices")
async def api_audio_devices():
    """Micrófonos de ENTRADA disponibles (la SALIDA la elige el HUD con setSinkId)."""
    return {"inputs": stt.list_input_devices()}


@app.post("/api/tts_test")
async def api_tts_test():
    st = tts.tts_status()
    can = (st.get("engine") != "off") and bool(
        st.get("edge") or st.get("elevenlabs") or st.get("local"))
    if can:
        asyncio.create_task(tts.speak(
            f"Hola, soy nexus. Esta es mi voz, {settings.get('tts_voice')}."))
    return {"ok": True, "spoke": can}


@app.post("/api/greet")
async def api_greet():
    """Saludo al abrir: lo GENERA el modelo y es DISTINTO cada vez (día, fecha,
    tareas de hoy, un toque de ingenio). Si el LLM tarda >10 s o no hay proveedor,
    cae a un saludo local VARIADO (nunca la frase fija de siempre)."""
    import datetime as _dt
    import random
    from backend.core import llm as _llm
    op = settings.get("operator_name", "") or "jefe"
    now = _dt.datetime.now()
    momento = ("buenos días" if now.hour < 13
               else "buenas tardes" if now.hour < 21 else "buenas noches")
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    dia = dias[now.weekday()]
    tareas = []
    try:
        from backend.core import board
        hoy = _dt.date.today().isoformat()
        tareas = [t.get("title", "") for t in board._load()
                  if t.get("due") == hoy and t.get("state") not in ("hecha", "completada")][:3]
    except Exception:
        tareas = []
    text = ""
    try:
        pista = (" Tareas suyas para HOY: " + "; ".join(tareas) + ".") if tareas else ""
        prompt = (f"Genera el saludo de ARRANQUE de nexus para {op} ({momento}; hoy es "
                  f"{dia} {now.day}). UNA o dos frases, tono JARVIS elegante con algo de "
                  "ingenio, y SIEMPRE DIFERENTE: prohibido «todos los sistemas en línea» "
                  "y cualquier fórmula repetida. Puedes citar el día, la fecha o una de "
                  "sus tareas de hoy." + pista + " Devuelve SOLO el saludo, sin comillas.")
        reply, prov = await asyncio.wait_for(_llm.ask_llm(prompt), timeout=10)
        # «ninguno» = no hubo modelo: ese texto es un aviso, NO un saludo.
        if prov not in ("mock", "ninguno"):
            text = reply.strip().strip('"«»').strip()[:260]
    except Exception:
        text = ""
    if not text:
        base = [
            f"{momento.capitalize()}, {op}. {dia.capitalize()} en marcha y yo al pie del cañón.",
            f"{momento.capitalize()}, {op}. Sistemas afinados; tú pon el café, del resto me encargo yo.",
            f"A sus órdenes, {op}. {dia.capitalize()} {now.day}: todo listo por aquí.",
            f"{momento.capitalize()}, {op}. Motores encendidos, ¿por dónde empezamos hoy?",
            f"Aquí nexus, {op}: despierto, afinado y con ganas de tachar tareas.",
            f"{momento.capitalize()}, {op}. El día es tuyo; la logística, mía.",
        ]
        if tareas:
            base.append(f"{momento.capitalize()}, {op}. Para hoy tienes: {tareas[0]}. "
                        "¿Atacamos con eso?")
        text = random.choice(base)
    st = tts.tts_status()
    can = (st.get("engine") != "off") and bool(
        st.get("edge") or st.get("elevenlabs") or st.get("local"))
    if can:
        asyncio.create_task(tts.speak(text))
    else:
        await bus.emit("log", {"level": "warn",
                               "msg": "Voz: no hay motor TTS instalado — ejecuta run.bat "
                                      "(instala edge-tts) para que nexus te hable."})
    await bus.emit("chat", {"user": "", "reply": text, "provider": "saludo", "skill": None})
    return {"ok": True, "spoke": can, "text": text}


@app.post("/api/tts_say")
async def api_tts_say(payload: SayText):
    """VOZ del MÓVIL: genera el MP3 con la MISMA voz del HUD y devuelve su URL para
    que la app lo reproduzca ella sola (el WebView del APK no trae speechSynthesis).
    La app YA llamaba a este endpoint… que no existía: por eso iba MUDA."""
    url = await tts.synthesize((payload.text or "").strip()[:1500])
    await bus.emit("log", {"level": "info" if url else "warn",
                           "msg": ("\U0001F4F1 tts_say -> audio " + url) if url
                                  else "\U0001F4F1 tts_say -> SIN AUDIO (movil no puede hablar)"})
    return {"url": url}


@app.post("/api/stt_audio")
async def api_stt_audio(request: Request):
    """OÍDO del MÓVIL: recibe el audio grabado en la app (webm/ogg/m4a), lo
    transcribe con el MISMO Whisper local del PC y devuelve el texto. Así el móvil
    tiene voz de calidad aunque no tenga reconocimiento de Google."""
    raw = await request.body()
    if not raw or len(raw) > 15 * 1024 * 1024:
        return {"text": ""}
    ctype = (request.headers.get("content-type") or "").lower()
    ext = (".webm" if "webm" in ctype else ".ogg" if "ogg" in ctype
           else ".m4a" if ("mp4" in ctype or "m4a" in ctype) else ".bin")
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=ext, prefix="wbk_stt_")
    try:
        os.write(fd, raw)
        os.close(fd)
        text = await stt.transcribe_path(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"text": text}


@app.get("/api/tts_audio/{name}")
async def api_tts_audio(name: str):
    """Sirve el audio TTS para que el HUD lo reproduzca DENTRO de la app."""
    from backend.core.tts import TTS_DIR
    f = TTS_DIR / name
    if not f.exists() or "/" in name or "\\" in name:
        return {"error": "not found"}
    mime = "audio/wav" if name.lower().endswith(".wav") else "audio/mpeg"
    return FileResponse(f, media_type=mime)


@app.post("/api/secrets")
async def api_secrets(payload: dict):
    """Guarda API keys desde ⚙ (config/secrets.json). Nunca se devuelven en claro."""
    saved = []
    for k, v in payload.items():
        if k in settings.SECRET_KEYS and isinstance(v, str):
            settings.set_secret(k, v)
            saved.append(k)
    await bus.emit("log", {"level": "ok",
                           "msg": f"Credenciales guardadas: {', '.join(saved) or 'ninguna'}"})
    return {k: bool(settings.secret(k)) for k in settings.SECRET_KEYS}


@app.get("/api/today")
async def api_today():
    """Panel HOY del HUD (v20): agenda del día en JSON estructurado."""
    from backend.core import briefing
    return await briefing.today_payload()


@app.get("/api/board")
async def api_board():
    from backend.core import board
    return board.board()


@app.get("/api/hardware")
async def api_hardware():
    """Inventario completo del equipo: CPU, GPU, RAM, disco, placa, audio, red.
    Respeta el permiso de hardware elegido en la instalación / ⚙."""
    from backend.core import permissions
    if not permissions.hardware_allowed():
        return {"denied": True, "error": permissions.HW_DENIED}
    from backend.core.hardware import hardware_report
    return await asyncio.to_thread(hardware_report)


@app.get("/api/calendar")
async def api_calendar():
    """Agenda unificada: eventos REALES de Google Calendar (si está conectado)
    + tareas del tablero con fecha. Tolerante: sin Google devuelve solo tareas."""
    from backend.core import board
    tasks = [t for col in board.board().values() for t in col if t.get("due")]
    google_events, google_status = [], "no conectado"
    try:
        import importlib.util
        from backend.core.config import SKILLS_DIR
        spec = importlib.util.spec_from_file_location(
            "gws", SKILLS_DIR / "google_workspace" / "skill.py")
        gws = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gws)
        has_token = gws.TOKEN_FILE.exists()
        has_creds = gws.CREDS_FILE.exists() or (settings.secret("google_client_id")
                                                and settings.secret("google_client_secret"))
        if not has_creds:
            google_status = "no conectado"
        elif not has_token:
            # Hay credenciales pero aún no se ha autorizado (haría falta abrir el navegador)
            google_status = "sin autorizar"
        else:
            google_events = await asyncio.wait_for(
                asyncio.to_thread(gws._fetch_events, 10), timeout=15)
            google_status = "ok"
    except Exception:
        google_status = "sin autorizar"
    return {"google": google_events, "google_status": google_status, "tasks": tasks}


@app.get("/api/spotify/callback")
async def api_spotify_callback(code: str = "", error: str = ""):
    """Callback OAuth de Spotify (autorización de una sola vez)."""
    from backend.core import spotify
    from fastapi.responses import HTMLResponse
    page = ("<html><body style='background:#020a06;color:#7fe9f7;"
            "font-family:monospace;text-align:center;padding-top:120px'>"
            "<h1>{msg}</h1><p>{sub}</p></body></html>")
    if error or not code:
        return HTMLResponse(page.format(
            msg="✕ Autorización cancelada",
            sub="Vuelve a nexus y prueba otra vez cuando quieras."))
    ok = await spotify.exchange_code(code)
    if ok:
        await bus.emit("log", {"level": "ok",
                               "msg": "Spotify conectado — autoplay real activado ✓"})
        return HTMLResponse(page.format(
            msg="✓ Spotify conectado",
            sub="Ya puedes cerrar esta pestaña. Di «pon una canción en spotify»."))
    return HTMLResponse(page.format(
        msg="✕ No he podido canjear el código",
        sub="Revisa el Client ID/Secret en ⚙ y que el Redirect URI sea "
            "http://127.0.0.1:8177/api/spotify/callback"))


@app.get("/api/spotify/status")
async def api_spotify_status():
    from backend.core import spotify
    return {"configured": spotify.is_configured(),
            "authorized": spotify.is_authorized()}


@app.post("/api/board/move")
async def api_board_move(payload: dict):
    from backend.core import board
    t = board.move_task(payload.get("id", ""), payload.get("state", ""))
    if t:
        await bus.emit("log", {"level": "ok",
                               "msg": f"Tablero: «{t['title']}» → {t['state']}"})
    return t or {"error": "not found"}


@app.post("/api/board/delete")
async def api_board_delete(payload: dict):
    """Borra una tarea por id (botón 🗑 del HUD) o por título (voz).
    v23: el borrado es LÓGICO — la tarea va a la papelera y se puede restaurar."""
    from backend.core import board
    t = board.delete_task(payload.get("id", "") or payload.get("query", ""),
                          reason=payload.get("reason", "botón 🗑 del HUD"),
                          by=payload.get("by", "operador"))
    if t:
        n = t.get("count", 1)
        await bus.emit("log", {"level": "ok",
                               "msg": f"Tablero: «{t['title']}» a la papelera" +
                                      (f" (+{n-1} duplicada(s))" if n > 1 else "")})
    return t or {"error": "not found"}


@app.get("/api/board/trash")
async def api_board_trash(limit: int = 50):
    """Papelera de tareas (v23 TAREA 3): lo último borrado primero."""
    from backend.core import board
    return {"items": board.trash(limit=limit), "last_batch": board.last_batch()}


@app.post("/api/board/restore")
async def api_board_restore(payload: dict):
    """Restaura tareas de la papelera a su columna anterior. Sin argumentos,
    devuelve el ÚLTIMO lote borrado entero."""
    from backend.core import board
    restored = board.restore(query=payload.get("query", "") or payload.get("id", ""),
                             batch=payload.get("batch", ""))
    if restored:
        await bus.emit("log", {"level": "ok",
                               "msg": f"Tablero: {len(restored)} tarea(s) restaurada(s)"})
    return {"restored": restored, "count": len(restored)}


@app.post("/api/board/edit")
async def api_board_edit(payload: dict):
    """Edita una tarea (botón ✎ del HUD): título, fecha, prioridad o estado."""
    from backend.core import board
    t = board.edit_task(payload.get("id", ""), title=payload.get("title"),
                        due=payload.get("due"), priority=payload.get("priority"),
                        state=payload.get("state"))
    if t:
        await bus.emit("log", {"level": "ok", "msg": f"Tablero: editada «{t['title']}»"})
    return t or {"error": "not found"}


@app.post("/api/home/scan")
async def api_home_scan():
    """Rastrea la red — buscador visual de dispositivos (HUD/movil)."""
    from backend.core.skills_loader import get_skills
    sk = get_skills().get("domotica")
    if not sk or not getattr(sk, "module", None):
        return {"devices": [], "error": "domotica no disponible"}
    try:
        return await sk.module.scan_api({"settings": settings, "bus": bus, "graph": graph})
    except Exception as exc:  # noqa: BLE001
        await bus.emit("log", {"level": "error", "msg": f"Escaneo de red: {type(exc).__name__}: {exc}"})
        return {"devices": [], "error": str(exc)}


@app.post("/api/home/control")
async def api_home_control(payload: dict):
    """Accion al pinchar/conectar un dispositivo del buscador (TV / Home Assistant)."""
    from backend.core.skills_loader import get_skills
    sk = get_skills().get("domotica")
    if not sk or not getattr(sk, "module", None):
        return {"ok": False, "reply": "La domotica no esta disponible ahora mismo."}
    try:
        return await sk.module.control_api({"settings": settings, "bus": bus, "graph": graph}, payload)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reply": f"No pude enviar la orden: {type(exc).__name__}: {exc}"}


@app.get("/api/home/ha_status")
async def api_home_ha_status():
    """Estado de Home Assistant para el panel de Dispositivos."""
    import shutil
    import httpx
    from backend.core.skills_loader import get_skills
    url = (settings.get("homeassistant_url", "") or "").rstrip("/")
    has_token = bool(settings.secret("homeassistant_token"))
    docker = shutil.which("docker") is not None
    running, entities = False, 0
    if url:
        try:
            async with httpx.AsyncClient(timeout=1.5) as cl:
                r = await cl.get(url + "/")
                running = r.status_code < 500
        except Exception:
            running = False
    if running and has_token:
        try:
            sk = get_skills().get("domotica")
            if sk and getattr(sk, "module", None):
                entities = len(await sk.module._ha_states({"settings": settings, "bus": bus}))
        except Exception:
            entities = 0
    return {"running": running, "has_token": has_token, "entities": entities,
            "url": url or "http://localhost:8123", "docker": docker}


@app.post("/api/home/ha_test")
async def api_home_ha_test(payload: dict):
    """Prueba una URL + token de Home Assistant SIN guardarlos aún, y devuelve un
    diagnóstico CLARO para el asistente: ¿se alcanza HA? ¿el token vale? ¿cuántas
    entidades controlables hay? Así el usuario sabe EXACTAMENTE qué falta."""
    import httpx
    url = (str(payload.get("url", "")).strip() or "http://localhost:8123").rstrip("/")
    token = str(payload.get("token", "")).strip()
    out = {"url": url, "reachable": False, "token_valid": False, "entities": 0,
           "controllable": 0, "error": ""}
    # 1) ¿se alcanza HA?
    try:
        async with httpx.AsyncClient(timeout=4) as cl:
            r = await cl.get(url + "/", follow_redirects=True)
            out["reachable"] = r.status_code < 500
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"no llego a {url} ({type(exc).__name__}). ¿Está encendido y la dirección es correcta?"
        return out
    if not out["reachable"]:
        out["error"] = f"{url} responde pero no como Home Assistant. Revisa la dirección/puerto (por defecto 8123)."
        return out
    # 2) ¿el token vale? (probamos /api/states con él)
    if not token:
        out["error"] = "falta el token de acceso de larga duración."
        return out
    try:
        async with httpx.AsyncClient(timeout=6) as cl:
            r = await cl.get(url + "/api/states", headers={"Authorization": f"Bearer {token}"})
        if r.status_code in (401, 403):
            out["error"] = "el token no es válido o ha caducado. Crea uno nuevo en tu perfil de HA (pestaña Seguridad)."
            return out
        r.raise_for_status()
        states = r.json()
        out["token_valid"] = True
        out["entities"] = len(states)
        ctrl_domains = ("light", "switch", "fan", "cover", "climate", "media_player",
                        "input_boolean", "scene", "script")
        out["controllable"] = sum(1 for s in states
                                  if str(s.get("entity_id", "")).split(".")[0] in ctrl_domains)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"HA respondió con un error al usar el token ({type(exc).__name__})."
    return out


@app.post("/api/home/install_ha")
async def api_home_install_ha():
    """Levanta Home Assistant en Docker (mando universal de domotica)."""
    import shutil
    if not shutil.which("docker"):
        return {"ok": False, "error": "No encuentro Docker. Abre Docker Desktop e intentalo otra vez."}
    from backend.core.config import assistant_slug
    slug = assistant_slug()
    ha_vol = f"{slug}_home_assistant_config"
    run_cmd = ["docker", "run", "-d", "--name", "home_assistant", "--restart", "unless-stopped",
               "-p", "8123:8123", "-v", f"{ha_vol}:/config",
               "ghcr.io/home-assistant/home-assistant:stable"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *run_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=240)
        text = (out or b"").decode("utf-8", "replace")
        if proc.returncode == 0:
            return {"ok": True, "url": "http://localhost:8123", "out": text[-300:]}
        low = text.lower()
        if "already in use" in low or "conflict" in low or "is already" in low:
            p2 = await asyncio.create_subprocess_exec("docker", "start", "home_assistant",
                                                      stdout=asyncio.subprocess.DEVNULL,
                                                      stderr=asyncio.subprocess.DEVNULL)
            await p2.communicate()
            return {"ok": True, "url": "http://localhost:8123", "out": "Home Assistant ya existia; lo he arrancado."}
        return {"ok": False, "error": text[-300:] or "docker run fallo"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/hermes/status")
async def api_hermes_status():
    """Radiografia de la conexion con Hermes (exe, .env, puerto, salud, encargos)."""
    from backend.core.skills_loader import get_skills
    sk = get_skills().get("hermes")
    if not sk or not getattr(sk, "module", None):
        return {"error": "skill hermes no disponible"}
    try:
        return await sk.module.diagnose({"settings": settings, "bus": bus})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/hermes/start")
async def api_hermes_start():
    """Arranca (y auto-provisiona) el gateway de Hermes desde el HUD."""
    from backend.core.skills_loader import get_skills
    sk = get_skills().get("hermes")
    if not sk or not getattr(sk, "module", None):
        return {"ok": False, "error": "skill hermes no disponible"}
    try:
        ok = await sk.module.ensure_up({"settings": settings, "bus": bus})
        diag = await sk.module.diagnose({"settings": settings, "bus": bus})
        return {"ok": bool(ok), "diag": diag}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/hermes/configure")
async def api_hermes_configure(payload: dict):
    """Configura el CEREBRO de Hermes desde Núcleo IA: proveedor + modelo + API key.
    Escribe la clave en ~/.hermes/.env y el modelo en config.yaml, y REINICIA su
    gateway para que lo cargue. Así el modelo interno de Hermes deja de dar 401."""
    from backend.core.skills_loader import get_skills
    sk = get_skills().get("hermes")
    if not sk or not getattr(sk, "module", None):
        return {"ok": False, "error": "skill hermes no disponible"}
    provider = str(payload.get("provider", "")).strip().lower()
    model = str(payload.get("model", "")).strip()
    api_key = str(payload.get("api_key", "")).strip()
    try:
        res = await asyncio.to_thread(sk.module.configure_brain,
                                      {"settings": settings, "bus": bus}, provider, model, api_key)
        if res.get("ok"):
            await bus.emit("log", {"level": "ok",
                                   "msg": f"🪽 Cerebro de Hermes: {provider} · {model} configurado"})
            # reiniciar el gateway con el modelo nuevo (no bloquea la respuesta)
            asyncio.create_task(sk.module.ensure_up({"settings": settings, "bus": bus}, force=True))
        return res
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.post("/api/home/rename")
async def api_home_rename(payload: dict):
    """Renombra un dispositivo desde la UI (nombre EDITABLE para que la voz lo
    entienda). Persiste en known_devices (ip/mac) y en my_devices (todos)."""
    name = str(payload.get("name", "")).strip()[:60]
    ip = str(payload.get("ip", "")).strip()
    mac = str(payload.get("mac", "")).strip().upper()
    eid = str(payload.get("entity_id", "")).strip()
    if not name or not (ip or mac or eid):
        return {"ok": False, "error": "faltan nombre o identificador"}
    if ip or mac:
        known = list(settings.get("known_devices", []) or [])
        hit = False
        for kd in known:
            if (ip and kd.get("ip") == ip) or (mac and (kd.get("mac") or "").upper() == mac):
                kd["name"] = name
                hit = True
        if not hit:
            known.append({"name": name, "ip": ip, "mac": mac, "brand": payload.get("brand", "")})
        settings.set("known_devices", known)
    mine = list(settings.get("my_devices", []) or [])
    key = eid or mac or ip
    for md in mine:
        if md.get("key") == key:
            md["name"] = name
    settings.set("my_devices", mine)
    await bus.emit("log", {"level": "ok", "msg": f"\U0001F3F7\uFE0F Dispositivo renombrado: \u00AB{name}\u00BB"})
    return {"ok": True, "name": name}


@app.post("/api/n8n")
async def api_n8n(payload: dict):
    """Entrada desde flujos n8n: {"text": "...", "speak": false} → respuesta de nexus."""
    result = await brain.process(payload.get("text", ""), source="n8n")
    if payload.get("speak"):
        asyncio.create_task(tts.speak(result["reply"]))
    return result


@app.get("/api/contentos")
async def api_contentos():
    """Panel Content OS: KPIs, calendario, ideas, aprendizajes, métricas y gráficos."""
    return await contentos.dashboard()


@app.post("/api/contentos/generate")
async def api_contentos_generate(payload: dict):
    """Genera idea o guion con IA. body: {kind: idea|script, topic: str}."""
    kind = payload.get("kind", "idea")
    text = await contentos.generate(kind, payload.get("topic", ""))
    return {"ok": True, "kind": kind, "text": text}


@app.post("/api/contentos/add")
async def api_contentos_add(payload: dict):
    """Añade idea/inspiración/aprendizaje/publicación. body: {kind, value}."""
    ok = contentos.add_item(payload.get("kind", ""), payload.get("value"))
    return {"ok": ok}


@app.get("/api/config")
async def api_config_get():
    return settings.as_dict()


@app.post("/api/config")
async def api_config_set(payload: dict):
    # Los secretos NO entran por aquí: van a /api/secrets, que los guarda en
    # secrets.json. Antes esta lista («has_elevenlabs_key»…) no coincidía con
    # ningún nombre real, así que no protegía nada: un POST con una API key la
    # dejaba en settings.json y el siguiente GET la devolvía en claro.
    rechazados = [k for k in payload if k in settings.SECRET_KEYS or k.startswith("has_")]
    for k, v in payload.items():
        if k not in rechazados:
            settings.set(k, v)
    # si has cambiado el cerebro, invalida la caché del proveedor (efecto inmediato)
    if any(k in payload for k in ("llm_provider", "llm_local", "ollama_model")):
        from backend.core.llm import invalidate_provider
        invalidate_provider()
        # y el runtime deja de dar por bueno lo anterior: se volverá a PROBAR.
        try:
            from backend.core import llm_runtime as _rt
            _rt._STATUS = _rt.LLMRuntimeStatus()
        except Exception:
            pass
    aplicados = [k for k in payload if k not in rechazados]
    await bus.emit("log", {"level": "ok",
                           "msg": f"Configuración actualizada: {', '.join(aplicados)}"
                                  + (f" (ignorados por ser secretos: {', '.join(rechazados)})"
                                     if rechazados else "")})
    return settings.as_dict()


@app.get("/")
async def index():
    if not settings.get("setup_done", False):
        return FileResponse(FRONTEND_DIR / "setup.html")   # asistente de 1ª ejecución
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/setup")
async def setup_page():
    """Asistente de instalación (accesible también después, para reconfigurar)."""
    return FileResponse(FRONTEND_DIR / "setup.html")


# ---------------------- API del asistente de instalación ----------------------
@app.get("/api/personalities")
async def api_personalities():
    from backend.core.llm import PERSONALITIES
    return {k: {"name": v["name"], "desc": v["desc"]} for k, v in PERSONALITIES.items()}


@app.get("/api/setup/state")
async def api_setup_state():
    import shutil
    docker = shutil.which("docker")
    version = ""
    if docker:
        try:
            import subprocess
            version = subprocess.run(["docker", "--version"], capture_output=True,
                                     text=True, timeout=6).stdout.strip()
        except Exception:
            docker = None
    from backend.core.llm import PERSONALITIES
    return {"setup_done": bool(settings.get("setup_done", False)),
            "docker": bool(docker), "docker_version": version,
            "config": settings.as_dict(),
            "personalities": {k: {"name": v["name"], "desc": v["desc"]}
                              for k, v in PERSONALITIES.items()}}


@app.post("/api/setup/save")
async def api_setup_save(payload: dict):
    """Guarda ajustes y secretos del asistente. body: {settings:{}, secrets:{}}."""
    for k, v in (payload.get("settings") or {}).items():
        settings.set(k, v)
    for k, v in (payload.get("secrets") or {}).items():
        if k in settings.SECRET_KEYS and isinstance(v, str) and v.strip():
            settings.set_secret(k, v)
    return {"ok": True}


@app.post("/api/setup/docker")
async def api_setup_docker():
    """Crea los contenedores de la BD (Postgres+pgvector) y n8n con Docker."""
    import shutil
    import subprocess
    if not shutil.which("docker"):
        return {"ok": False, "error": "Docker no está instalado",
                "download": "https://www.docker.com/products/docker-desktop/"}
    from backend.core.config import ROOT, assistant_slug
    # WHITE-LABEL: los nombres de proyecto/contenedor/volumen/BD salen del NOMBRE del
    # sistema (slug). Por defecto «nexus» → nexus_*, nexus_core, etc.; para cualquier
    # otro nombre, nombres limpios «<slug>_…».
    slug = assistant_slug()
    proj = slug
    vol = f"{slug}_memoria_datos"
    pg = f"{slug}_memoria_postgres"
    # La contraseña NO se deriva del nombre del asistente. Antes era
    # antes se construia con el slug y un sufijo fijo, asi que salia IGUAL en
    # todas las instalaciones y encima quedaba publicada en el repositorio
    # (auditoria 30/07/2026). Ni el valor viejo se escribe aqui.
    # Ahora se genera al azar la primera vez y se reutiliza la del compose ya creado.
    import re as _re
    import secrets as _secrets
    user, db = f"{slug}_admin", f"{slug}_core"
    compose = ROOT / "config" / "docker-compose.yml"
    pwd = ""
    if compose.exists():
        m = _re.search(r"POSTGRES_PASSWORD:\s*(\S+)", compose.read_text(encoding="utf-8"))
        pwd = m.group(1) if m else ""
    if not pwd:
        pwd = _secrets.token_urlsafe(24)
    compose.parent.mkdir(parents=True, exist_ok=True)
    if not compose.exists():
        compose.write_text(
            f"name: {proj}\n"
            "services:\n"
            f"  {pg}:\n"
            "    image: pgvector/pgvector:pg16\n"
            f"    container_name: {pg}\n"
            "    restart: unless-stopped\n"
            "    environment:\n"
            f"      POSTGRES_USER: {user}\n"
            f"      POSTGRES_PASSWORD: {pwd}\n"
            f"      POSTGRES_DB: {db}\n"
            # Solo accesible desde ESTE equipo: antes se publicaba en todas las
            # interfaces y cualquiera de la red podía conectarse a la memoria.
            "    ports: ['127.0.0.1:5433:5432']\n"
            f"    volumes: ['{vol}:/var/lib/postgresql/data']\n"
            f"volumes:\n  {vol}:\n", encoding="utf-8")
    try:
        out = await asyncio.to_thread(lambda: subprocess.run(
            ["docker", "compose", "-f", str(compose), "up", "-d"],
            capture_output=True, text=True, timeout=300))
        ok = out.returncode == 0
        if ok:
            settings.set("db_url", f"postgresql://{user}:{pwd}@localhost:5433/{db}")
        return {"ok": ok, "out": (out.stdout + out.stderr)[-800:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/setup/scan_models")
async def api_setup_scan_models(payload: dict):
    """Añade una carpeta de modelos locales y devuelve lo que encuentra."""
    folder = str(payload.get("path", "")).strip()
    if folder:
        paths = list(settings.get("model_scan_paths", []) or [])
        if folder not in paths:
            paths.append(folder)
            settings.set("model_scan_paths", paths)
    from backend.core.llm import scan_local_models
    return await scan_local_models()


@app.post("/api/setup/finish")
async def api_setup_finish():
    settings.set("setup_done", True)
    return {"ok": True}


# ---------------------- Vinculación del móvil (QR + túnel) ----------------------
@app.get("/api/llm_check")
async def api_llm_check():
    """DIAGNÓSTICO LLM: prueba CADA proveedor con un ping mínimo y devuelve su estado
    real (clave, modelo y el error EXACTO). Abrir en el navegador:
    http://localhost:8177/api/llm_check — y todo queda también en data/nexus.log."""
    from backend.core import llm as _llm
    out = {"_activo": settings.get("llm_provider", "?")}
    msgs = [{"role": "user", "content": "Responde solo: OK"}]
    for name, prov in _llm.PROVIDERS.items():
        if name == "mock":
            continue
        info = {"disponible": False, "modelo": "", "error": ""}
        try:
            info["modelo"] = prov._model() if hasattr(prov, "_model") else ""
        except Exception:
            pass
        try:
            if not await prov.available():
                info["error"] = "no disponible (falta API key o el servicio está apagado)"
            else:
                r = await asyncio.wait_for(prov.chat(msgs), timeout=25)
                info["disponible"] = True
                info["respuesta"] = str(r)[:80]
        except Exception as exc:                               # noqa: BLE001
            try:
                info["error"] = _llm._explain_error(prov, exc)
            except Exception:
                info["error"] = f"{type(exc).__name__}: {exc}"
        out[name] = info
        await bus.emit("log", {"level": "ok" if info["disponible"] else "warn",
                               "msg": f"LLM {name} ({info['modelo'] or 'sin modelo'}): "
                                      + ("✔ responde" if info["disponible"]
                                         else f"✖ {info['error']}")})
    return out


@app.post("/api/link/start")
async def api_link_start():
    from backend.core import remote
    return await remote.start_tunnel()


@app.get("/api/link/status")
async def api_link_status():
    from backend.core import remote
    return remote.status()


@app.get("/api/link/qr")
async def api_link_qr():
    from backend.core import remote
    from fastapi.responses import Response
    try:
        png = remote.qr_png(remote.status()["link"])
        return Response(content=png, media_type="image/png")
    except Exception as exc:
        return {"error": f"instala qrcode (run.bat): {exc}"}


@app.post("/api/link/reset")
async def api_link_reset():
    """DESVINCULAR: rota el token (QRs y enlaces viejos DEJAN de valer) y olvida los
    móviles registrados. Cada móvil tendrá que escanear el QR nuevo para volver."""
    from backend.core import remote
    remote.rotate_token()
    for d in list(remote.devices()):
        try:
            remote.forget_device(d.get("id", ""))
        except Exception:
            pass
    await bus.emit("unpaired", {"name": "todos los móviles", "id": "*", "count": 0})
    await bus.emit("log", {"level": "info",
                           "msg": "📱 Desvinculación: token rotado; los enlaces antiguos ya no valen."})
    return remote.status()


@app.post("/api/link/stop")
async def api_link_stop():
    from backend.core import remote
    remote.stop_tunnel()
    return remote.status()


@app.post("/api/open_url")
async def api_open_url(payload: dict):
    """Abre una URL en el navegador REAL del PC (los enlaces del chat)."""
    url = str(payload.get("url", "")).strip()
    if url.startswith("http://") or url.startswith("https://"):
        import webbrowser
        webbrowser.open(url)
        return {"ok": True}
    return {"ok": False, "error": "solo http/https"}


@app.get("/m")
async def mobile():
    """Interfaz móvil (PWA): el nodo nexus. Ábrela desde el móvil apuntando
    al PC en la LAN: http://IP-DEL-PC:8177/m"""
    # SIN CACHÉ: el WebView del móvil guardaba la página días y NO pedía la nueva
    # versión al PC (parecía que los cambios «no llegaban»). no-store = siempre fresca.
    return FileResponse(FRONTEND_DIR / "mobile.html",
                        headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/sw.js")
async def service_worker():
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store, max-age=0"})


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
