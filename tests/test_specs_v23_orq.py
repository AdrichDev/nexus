# -*- coding: utf-8 -*-
"""Tests de las specs v23 — FASE 4 y 5 (orquestación y multitarea).

  T8  flujo NEXUS → Hermes → NEXUS (agente responsable, estado final explícito)
  T9  ejecuciones fantasma: requestId, duplicados bloqueados, cancelación,
      limpieza de colas al reiniciar
  T10 indicador de Multitarea en el sidebar ('' | En curso | N | ✓ | !)
  T11 modelo de estados real y persistido de cada ejecución
  T12 notificación única al terminar, con el estado y los archivos afectados

Ejecutar:  python tests/test_specs_v23_orq.py    (desde la carpeta nexus)
"""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend.core.jobs as jobsmod            # noqa: E402
import backend.core.audit as audit             # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="nexus_v23j_"))
jobsmod.JOBS_FILE = _TMP / "jobs.json"
audit.AUDIT_FILE = _TMP / "logs" / "audit.jsonl"


def _fresh():
    """Gestor limpio (sin tocar el singleton global) apuntando al tmp."""
    jm = jobsmod.JobManager(max_concurrent=4)
    jm._jobs, jm._order, jm._counter = {}, [], 0
    return jm


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ══════════════ T11: modelo de estados ══════════════

def test_estados_de_las_specs():
    check(jobsmod.STATES == ("queued", "running", "waiting_confirmation",
                             "completed", "failed", "cancelled"),
          f"los 6 estados de las specs, en orden ({jobsmod.STATES})")
    check(set(jobsmod.LIVE_STATES) == {"queued", "running", "waiting_confirmation"},
          "estados vivos correctos")
    check(set(jobsmod.FINAL_STATES) == {"completed", "failed", "cancelled"},
          "estados finales correctos")


def test_ciclo_completo_de_un_trabajo():
    async def _t():
        jm = _fresh()

        async def _ok():
            return {"reply": "listo", "files": [{"path": "C:/x/informe.md", "action": "creado"}]}
        jid = await jm.submit("Informe", _ok, request_id="req1", request="haz el informe",
                              channel="pc", agent="nexus")
        j = jm.get(jid)
        check(j["status"] == "queued", "nace en queued")
        check(j["request_id"] == "req1", "guarda el requestId")
        check(j["request"] == "haz el informe", "guarda la petición original")
        check(j["agent"] == "nexus", "guarda el agente responsable")
        check(j["num"] == 1 and bool(j["id"]), "identificador único + número visible")
        await asyncio.sleep(0.15)
        check(j["status"] == "completed", f"termina en completed (está en {j['status']})")
        check(j["progress"] == 100, "progreso al 100")
        check(j["result"] == "listo", "guarda el resultado")
        check(j["started"] and j["ended"], "guarda fecha de inicio y de fin")
        check(j["files"] == [{"path": "C:/x/informe.md", "action": "creado"}],
              "registra los archivos creados o modificados")
        check(j["seen"] is False, "nace sin revisar (para el ✓ del sidebar)")
    _run(_t())


def test_fallo_no_se_disfraza_de_exito():
    async def _t():
        jm = _fresh()

        async def _boom():
            raise RuntimeError("el gateway no responde")
        jid = await jm.submit("Encargo roto", _boom, agent="hermes")
        await asyncio.sleep(0.15)
        j = jm.get(jid)
        check(j["status"] == "failed", f"un error deja el trabajo en failed ({j['status']})")
        check("gateway no responde" in j["error"], "el error real se conserva, no se oculta")
        check(j["result"] == "", "un trabajo fallido no tiene resultado")
    _run(_t())


def test_progreso_y_confirmaciones():
    async def _t():
        jm = _fresh()
        fut = asyncio.Event()

        async def _lento():
            await fut.wait()
            return "hecho"
        jid = await jm.submit("Lento", _lento)
        await asyncio.sleep(0.05)
        await jm.progress(jid, 40, "descargando")
        j = jm.get(jid)
        check(j["progress"] == 40 and j["progress_note"] == "descargando",
              "progreso estructurado")
        await jm.waiting(jid, "¿sobrescribo el archivo?")
        check(j["status"] == "waiting_confirmation", "puede quedarse esperando confirmación")
        check(j["confirmations_requested"][0]["q"] == "¿sobrescribo el archivo?",
              "registra la confirmación solicitada")
        await jm.confirmed(jid, "sí")
        check(j["status"] == "running", "al confirmar vuelve a running")
        check(j["confirmations_received"][0]["a"] == "sí", "registra la confirmación recibida")
        fut.set()
        await asyncio.sleep(0.1)
        check(j["status"] == "completed", "y acaba bien")
    _run(_t())


# ══════════════ T9: ejecuciones fantasma ══════════════

def test_duplicados_bloqueados():
    async def _t():
        jm = _fresh()
        ev = asyncio.Event()

        async def _lento():
            await ev.wait()
            return "ok"
        await jm.submit("Investiga proveedores", _lento, request="investiga proveedores",
                        channel="pc", dedupe_key="investiga proveedores")
        await asyncio.sleep(0.05)
        dup = jm.active_duplicate("Investiga  Proveedores", "pc")
        check(dup is not None, "detecta el duplicado (ignorando mayúsculas y espacios)")
        check(jm.active_duplicate("investiga proveedores", "telegram") is None,
              "el duplicado es POR CANAL")
        ev.set()
        await asyncio.sleep(0.1)
        check(jm.active_duplicate("investiga proveedores", "pc") is None,
              "cuando termina, ya no es duplicado")
    _run(_t())


def test_cancelado_no_publica_resultado():
    async def _t():
        jm = _fresh()
        vistos = []
        from backend.core.events import bus
        ev = asyncio.Event()

        async def _lento():
            await ev.wait()
            return "resultado tardío"
        jid = await jm.submit("Obsoleto", _lento, channel="pc", notify=True)
        await asyncio.sleep(0.05)
        orig = bus.emit

        async def _spy(kind, data=None):
            if kind in ("chat", "job_done"):
                vistos.append(kind)
            return await orig(kind, data)
        bus.emit = _spy
        try:
            await jm.cancel(jid)
            ev.set()
            await asyncio.sleep(0.15)
        finally:
            bus.emit = orig
        check(jm.get(jid)["status"] == "cancelled", "queda cancelado")
        check(vistos == [], f"un trabajo cancelado NO publica nada ({vistos})")
    _run(_t())


def test_cancel_obsolete_respeta_la_peticion_actual():
    async def _t():
        jm = _fresh()
        ev = asyncio.Event()

        async def _lento():
            await ev.wait()
            return "ok"
        await jm.submit("viejo 1", _lento, request_id="viejo", channel="pc")
        await jm.submit("viejo 2", _lento, request_id="viejo", channel="pc")
        await jm.submit("nuevo", _lento, request_id="nuevo", channel="pc")
        await jm.submit("otro canal", _lento, request_id="viejo", channel="telegram")
        await asyncio.sleep(0.05)
        n = await jm.cancel_obsolete(channel="pc", keep_request_id="nuevo")
        check(n == 2, f"cancela los 2 obsoletos del canal (canceló {n})")
        vivos = [j["title"] for j in jm.active()]
        check("nuevo" in vivos, "la petición actual sobrevive")
        check("otro canal" in vivos, "no toca otros canales")
        ev.set()
        await asyncio.sleep(0.1)
    _run(_t())


def test_reinicio_no_deja_trabajos_zombis():
    async def _t():
        jm = _fresh()
        ev = asyncio.Event()

        async def _lento():
            await ev.wait()
            return "ok"
        await jm.submit("a medias", _lento, channel="pc")
        await asyncio.sleep(0.05)
        check(jobsmod.JOBS_FILE.exists(), "el estado se persiste en disco")
        # simula el arranque siguiente de nexus
        jm2 = jobsmod.JobManager()
        j = [x for x in jm2.snapshot() if x["title"] == "a medias"]
        check(bool(j), "al reiniciar se recupera el historial")
        check(j[0]["status"] == "failed", f"lo que quedó vivo se marca failed ({j[0]['status']})")
        check("reinici" in j[0]["error"], "y dice el motivo real")
        check(jm2.active() == [], "no quedan trabajos «activos» fantasma")
        ev.set()
        await asyncio.sleep(0.1)
    _run(_t())


def test_is_active_request():
    async def _t():
        jm = _fresh()
        ev = asyncio.Event()

        async def _lento():
            await ev.wait()
            return "ok"
        await jm.submit("x", _lento, request_id="r9")
        await asyncio.sleep(0.05)
        check(jm.is_active_request("r9"), "la petición está viva")
        check(not jm.is_active_request("otra"), "otra petición no")
        ev.set()
        await asyncio.sleep(0.1)
        check(not jm.is_active_request("r9"), "al terminar deja de estar viva")
    _run(_t())


# ══════════════ T10: indicador del sidebar ══════════════

def test_badge_del_sidebar():
    async def _t():
        jm = _fresh()
        check(jm.badge() == "", "sin trabajos → sin indicador")
        ev = asyncio.Event()

        async def _lento():
            await ev.wait()
            return "ok"
        j1 = await jm.submit("uno", _lento)
        await asyncio.sleep(0.05)
        check(jm.badge() == "En curso", f"una tarea → «En curso» (dio «{jm.badge()}»)")
        await jm.submit("dos", _lento)
        await jm.submit("tres", _lento)
        await asyncio.sleep(0.05)
        check(jm.badge() == "3", f"tres tareas → «3» (dio «{jm.badge()}»)")
        ev.set()
        await asyncio.sleep(0.15)
        check(jm.badge() == "✓", f"terminadas sin revisar → «✓» (dio «{jm.badge()}»)")
        check(jm.counts()["finished_unseen"] == 3, "cuenta las no revisadas")
        await jm.mark_seen()
        check(jm.badge() == "", "al revisar, el indicador se limpia")

        async def _boom():
            raise RuntimeError("pum")
        await jm.submit("rota", _boom)
        await asyncio.sleep(0.15)
        check(jm.badge() == "!", f"un fallo sin revisar → «!» (dio «{jm.badge()}»)")
        check(jm.get(j1)["status"] == "completed", "una fallida no marca a las buenas")
    _run(_t())


# ══════════════ T12: notificación única ══════════════

def test_notificacion_unica_y_con_estado():
    async def _t():
        jm = _fresh()
        chats = []
        from backend.core.events import bus
        orig = bus.emit

        async def _spy(kind, data=None):
            if kind == "chat":
                chats.append(data)
            return await orig(kind, data)
        bus.emit = _spy
        try:
            async def _ok():
                return {"reply": "informe hecho",
                        "files": [{"path": "D:/x.md", "action": "creado"}]}
            await jm.submit("Informe", _ok, notify=True, channel="pc")
            await asyncio.sleep(0.15)
        finally:
            bus.emit = orig
        check(len(chats) == 1, f"una sola notificación por trabajo (hubo {len(chats)})")
        check("informe hecho" in chats[0]["reply"], "incluye el resultado")
        check("creado" in chats[0]["reply"] and "D:/x.md" in chats[0]["reply"],
              "dice qué archivos se crearon o modificaron")
    _run(_t())


def test_sin_notify_no_duplica():
    async def _t():
        jm = _fresh()
        chats = []
        from backend.core.events import bus
        orig = bus.emit

        async def _spy(kind, data=None):
            if kind == "chat":
                chats.append(data)
            return await orig(kind, data)
        bus.emit = _spy
        try:
            async def _ok():
                return "ya lo he cantado yo"
            await jm.submit("Encargo Hermes", _ok, notify=False)
            await asyncio.sleep(0.15)
        finally:
            bus.emit = orig
        check(chats == [], "quien canta su propio resultado no recibe 2ª notificación")
    _run(_t())


# ══════════════ Integración: brain, hermes, API y HUD ══════════════

def test_brain_requestid_y_control_de_trabajos():
    src = Path(ROOT, "backend", "core", "brain.py").read_text(encoding="utf-8")
    check("request_id: str = \"\"" in src, "process acepta un request_id")
    check("req_id = request_id or uuid.uuid4().hex[:8]" in src,
          "cada petición genera su identificador único")
    check("request_id=req_id" in src, "el requestId se propaga a lo que se lanza")
    check("job_mgr.active_duplicate(order, channel)" in src,
          "el brain bloquea trabajos duplicados")
    check("cancel_obsolete" in src, "el brain sabe cancelar trabajos obsoletos")
    check("_JOBS_WHAT_RX" in src and "_JOBS_CANCEL_RX" in src,
          "hay patrones para consultar y cancelar los trabajos")
    check("delegate(encargo, hctx, channel, request_id=req_id)" in src
          and "delegate(text, hctx, channel, request_id=req_id)" in src,
          "las dos delegaciones a Hermes llevan el requestId")
    # los patrones cazan lo que dice Adri
    import re as _re
    for t in ("qué estás haciendo", "qué tienes en marcha", "trabajos activos"):
        check(bool(_re.search(r"_JOBS_WHAT_RX", src)), "patrón declarado")
    mod = {}
    exec(compile(_re.search(r"_JOBS_WHAT_RX = re\.compile\((?:.|\n)*?\)\n", src).group(0),
                 "<w>", "exec"), {"re": _re}, mod)
    for t in ("qué estás haciendo", "qué tienes en marcha", "trabajos en curso"):
        check(bool(mod["_JOBS_WHAT_RX"].search(t)), f"«{t}» pregunta por los trabajos")
    mod2 = {}
    exec(compile(_re.search(r"_JOBS_CANCEL_RX = re\.compile\((?:.|\n)*?\)\n", src).group(0),
                 "<c>", "exec"), {"re": _re}, mod2)
    for t in ("cancela los trabajos", "cancela lo que estás haciendo", "déjalo todo"):
        check(bool(mod2["_JOBS_CANCEL_RX"].search(t)), f"«{t}» cancela")
    check(not mod2["_JOBS_CANCEL_RX"].search("cancela la reunión del jueves"),
          "no se lleva por delante otras cancelaciones")


def test_hermes_orquestacion():
    src = Path(ROOT, "skills", "hermes", "skill.py").read_text(encoding="utf-8")
    check("async def delegate(orden: str, ctx, channel: str, request_id: str = \"\")" in src,
          "delegate acepta el requestId")
    check("agent=\"hermes\"" in src, "el trabajo queda marcado con el agente Hermes")
    check("active_duplicate(f\"hermes::{orden}\", channel)" in src,
          "Hermes no acepta dos veces el mismo encargo vivo")
    # v24 (T1/T2): el estado se sigue diciendo, pero en cristiano y en primera
    # persona — nada de marcas internas tipo «ESTADO: TERMINADO» ni del nombre
    # del subagente. El detalle técnico se queda en el log.
    check("Ya lo tengo" in src, "cuando termina bien, lo dice en primera persona")
    check("pv.mensaje_fallo(" in src,
          "cuando falla, un único mensaje funcional (sin tecnicismos)")
    check("No lo doy por hecho" in src,
          "si vuelve vacío, no lo da por hecho")
    check('bus.emit("log", {"level": "error"' in src,
          "y el detalle técnico va al LOG, no al chat")


def test_api_jobs():
    src = Path(ROOT, "backend", "app.py").read_text(encoding="utf-8")
    check('"/api/jobs/seen"' in src, "hay endpoint para marcar los resultados revisados")
    check('"badge": jobs.badge()' in src, "/api/jobs devuelve el indicador del sidebar")
    check("active_duplicate(text, channel)" in src, "la API bloquea duplicados")
    check("request_id=rid" in src, "la API asigna requestId a cada trabajo")


def test_billing_no_secuestra_el_tablero():
    """Hallazgo de la prueba end-to-end del 25/07: «mueve enviar la factura a
    completadas» EMITÍA UNA FACTURA (la skill billing va antes por orden
    alfabético y «factura a completadas» casaba con su patrón)."""
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_renovacion import global_route
    for t, skill, intent in [
        ("mueve enviar la factura a completadas", "tasks_board", "move"),
        ("mueve la factura de julio a pendientes", "tasks_board", "move"),
        ("hazme una factura a Movistar por 300 euros", "billing", "invoice"),
        ("factúrale al cliente Acme 500 euros", "billing", "invoice"),
    ]:
        f, i = global_route(t)
        check((f, i) == (skill, intent),
              f"routing: '{t}' -> {f}/{i} (esperaba {skill}/{intent})")


def test_hud_multitarea():
    js = Path(ROOT, "frontend", "js", "command.js").read_text(encoding="utf-8")
    css = Path(ROOT, "frontend", "css", "command.css").read_text(encoding="utf-8")
    check("waiting_confirmation: 'esperando confirmación'" in js,
          "el HUD conoce el estado waiting_confirmation")
    check("completed: 'completado'" in js and "failed: 'fallido'" in js,
          "el HUD usa los estados de las specs")
    check("job_done" in js, "el HUD escucha la notificación de fin de trabajo")
    check("'/api/jobs/seen'" in js, "abrir Multitarea limpia el indicador")
    check("state.jobs && state.jobs.badge" in js, "el indicador viene del backend")
    check("jobc-p" in js and "jobc-f" in js, "pinta progreso y archivos afectados")
    check(".jobc.completed" in css and ".jobc.failed" in css,
          "hay estilos para los estados nuevos")
    check("#nav-jobs.errmark" in css, "hay estilo para el indicador de error")


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    tests = [test_estados_de_las_specs, test_ciclo_completo_de_un_trabajo,
             test_fallo_no_se_disfraza_de_exito, test_progreso_y_confirmaciones,
             test_duplicados_bloqueados, test_cancelado_no_publica_resultado,
             test_cancel_obsolete_respeta_la_peticion_actual,
             test_reinicio_no_deja_trabajos_zombis, test_is_active_request,
             test_badge_del_sidebar, test_notificacion_unica_y_con_estado,
             test_sin_notify_no_duplica,
             test_brain_requestid_y_control_de_trabajos, test_hermes_orquestacion,
             test_api_jobs, test_billing_no_secuestra_el_tablero,
             test_hud_multitarea]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
