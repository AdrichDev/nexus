"""
nexus — MULTITAREA: gestor de trabajos concurrentes.

nexus deja de ser secuencial: puede tener VARIOS trabajos en marcha a la vez
(investigar algo, procesar, una orden larga…) mientras sigues hablando con él.
Cada trabajo corre en su propia tarea asyncio, con un límite de concurrencia, y
su estado se emite en vivo al HUD (evento 'jobs') para el PANEL DE MULTITAREA.

Uso:
    from .jobs import jobs
    await jobs.submit("Investigar proveedores", lambda: brain.process("..."))
El HUD ve la cola en tiempo real y puede cancelar trabajos.

v23 (specs v23, TAREAS 9, 11 y 12):
  * MODELO DE ESTADOS REAL: queued → running → completed | failed | cancelled,
    más waiting_confirmation cuando el trabajo está parado esperando un sí/no.
  * Cada ejecución guarda: id, número, requestId, petición original, agente
    responsable, fechas, progreso, resultado, error, ARCHIVOS creados o
    modificados, confirmaciones pedidas y recibidas.
  * PERSISTENCIA en data/jobs.json: reiniciar la interfaz no pierde nada, y al
    reiniciar nexus los trabajos que quedaron a medias se marcan `failed`
    («interrumpido»), NUNCA como completados (limpieza de colas y estados).
  * ANTI-FANTASMA: un trabajo cancelado no publica resultado, y los duplicados
    (misma petición y canal, todavía activa) se detectan y se bloquean.
  * El resultado se marca como NO VISTO hasta que abres Multitarea: de ahí sale
    el ✓ / ! del sidebar.
"""
from __future__ import annotations

import asyncio
import json
import time
import unicodedata
import uuid

from .config import DATA_DIR
from . import events
from .events import bus

JOBS_FILE = DATA_DIR / "jobs.json"

# Estados de las specs v23. Los tres primeros son "vivos"; los tres últimos, finales.
STATES = ("queued", "running", "waiting_confirmation",
          "completed", "failed", "cancelled")
LIVE_STATES = ("queued", "running", "waiting_confirmation")
FINAL_STATES = ("completed", "failed", "cancelled")

_PERSIST_MAX = 120          # trabajos guardados en disco


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _audit(**kw) -> None:
    try:
        from . import audit as _a
        _a.log(**kw)
    except Exception:
        pass


class JobManager:
    def __init__(self, max_concurrent: int = 4):
        self.max = max_concurrent
        self._sem: asyncio.Semaphore | None = None
        self._jobs: dict[str, dict] = {}
        self._order: list[str] = []
        self._tasks: dict[str, asyncio.Task] = {}
        self._counter = 0            # numero correlativo visible (#1, #2…)
        self._restore()

    # ────────────────────────── persistencia ──────────────────────────

    def _restore(self) -> None:
        """Recupera el historial del disco. Lo que quedó 'vivo' al cerrar nexus
        NO puede seguir vivo: se marca failed con el motivo real."""
        try:
            data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, list):
            return
        for j in data[-_PERSIST_MAX:]:
            if not isinstance(j, dict) or not j.get("id"):
                continue
            if j.get("status") in LIVE_STATES:
                j["status"] = "failed"
                j["error"] = (j.get("error") or
                              "interrumpido: nexus se reinició mientras corría")
                j["ended"] = j.get("ended") or time.time()
                j["seen"] = False
            self._jobs[j["id"]] = j
            self._order.append(j["id"])
        self._counter = max((int(j.get("num") or 0) for j in self._jobs.values()),
                            default=0)

    def _persist(self) -> None:
        try:
            JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = [{k: v for k, v in self._jobs[jid].items() if not k.startswith("_")}
                    for jid in self._order[-_PERSIST_MAX:] if jid in self._jobs]
            JOBS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        except Exception:
            pass

    # ────────────────────────── lectura ──────────────────────────

    def _sema(self) -> asyncio.Semaphore:
        if self._sem is None:                 # se crea dentro del loop
            self._sem = asyncio.Semaphore(self.max)
        return self._sem

    def get(self, jid: str) -> dict | None:
        return self._jobs.get(jid)

    def snapshot(self) -> list[dict]:
        """Estado serializable de los últimos trabajos (para el panel)."""
        out = []
        for jid in self._order[-60:]:
            j = self._jobs.get(jid)
            if j:
                out.append({k: v for k, v in j.items() if not k.startswith("_")})
        return out

    def counts(self) -> dict:
        s = {k: 0 for k in STATES}
        unseen_ok = unseen_bad = 0
        for j in self._jobs.values():
            s[j["status"]] = s.get(j["status"], 0) + 1
            if j["status"] in FINAL_STATES and not j.get("seen"):
                if j["status"] == "failed":
                    unseen_bad += 1
                elif j["status"] == "completed":
                    unseen_ok += 1
        s["active"] = s["running"] + s["queued"] + s["waiting_confirmation"]
        s["finished_unseen"] = unseen_ok
        s["failed_unseen"] = unseen_bad
        # compatibilidad con lectores antiguos del HUD
        s["done"], s["error"] = s["completed"], s["failed"]
        return s

    def badge(self) -> str:
        """Lo que debe pintar el sidebar junto a «Multitarea» (specs v23 T10):
        '' | 'En curso' | '3' | '✓' | '!'."""
        c = self.counts()
        if c["failed_unseen"]:
            return "!"
        if c["active"] == 1:
            return "En curso"
        if c["active"] > 1:
            return str(c["active"])
        if c["finished_unseen"]:
            return "✓"
        return ""

    def active(self) -> list[dict]:
        return [j for j in self._jobs.values() if j["status"] in LIVE_STATES]

    def active_duplicate(self, dedupe_key: str, channel: str = "") -> dict | None:
        """Trabajo VIVO con la misma petición (y canal). Sirve para bloquear
        duplicados antes de lanzarlos: specs v23 T9."""
        k = _norm(dedupe_key)
        if not k:
            return None
        for j in self._jobs.values():
            if j["status"] in LIVE_STATES and j.get("dedupe_key") == k:
                if not channel or j.get("channel", "") == channel:
                    return j
        return None

    def is_active_request(self, request_id: str) -> bool:
        """¿Sigue viva alguna ejecución de esta petición?"""
        return any(j.get("request_id") == request_id and j["status"] in LIVE_STATES
                   for j in self._jobs.values() if request_id)

    # ────────────────────────── escritura ──────────────────────────

    async def _emit(self) -> None:
        self._persist()
        try:
            await bus.emit("jobs", {"list": self.snapshot(), "counts": self.counts(),
                                    "badge": self.badge()})
        except Exception:
            pass

    async def submit(self, title: str, coro_factory, kind: str = "tarea",
                     request_id: str = "", request: str = "", agent: str = "nexus",
                     channel: str = "pc", dedupe_key: str = "",
                     notify: bool = False) -> str:
        """Encola un trabajo. coro_factory es una función SIN args que devuelve una
        corrutina (se ejecuta al arrancar el trabajo). Devuelve el id del trabajo.

        request_id: identificador de la PETICIÓN del operador que lo originó.
        dedupe_key: por defecto, la petición normalizada (para detectar duplicados).
        notify: si True, el gestor publica el resultado en el chat al terminar.
                Los trabajos que ya cantan su propio resultado deben dejarlo en False
                (specs v23 T12: una única notificación por trabajo)."""
        jid = uuid.uuid4().hex[:8]
        self._counter += 1
        job = {"id": jid, "num": self._counter,
               "title": (title or "Trabajo")[:120], "kind": kind,
               "status": "queued", "progress": 0, "created": time.time(),
               "started": None, "ended": None, "result": "", "error": "",
               # v23: trazabilidad completa de la ejecución
               "request_id": request_id or uuid.uuid4().hex[:8],
               "request": (request or title or "")[:400],
               "agent": agent, "channel": channel,
               "dedupe_key": _norm(dedupe_key or request or title),
               "files": [], "confirmations_requested": [], "confirmations_received": [],
               "progress_note": "", "seen": False, "notify": bool(notify)}
        self._jobs[jid] = job
        self._order.append(jid)
        await self._emit()
        _audit(action="job_submit", actor="operador", agent=agent, destructive=False,
               request=job["request"], run_id=job["request_id"], channel=channel,
               result=f"trabajo #{job['num']} en cola ({kind})")
        self._tasks[jid] = asyncio.create_task(self._run(jid, coro_factory))
        return jid

    async def progress(self, jid: str, pct: int, note: str = "") -> None:
        """Progreso ESTRUCTURADO (lo usa quien ejecuta, p. ej. Hermes)."""
        job = self._jobs.get(jid)
        if not job:
            return
        job["progress"] = max(0, min(100, int(pct)))
        if note:
            job["progress_note"] = note[:200]
        await self._emit()

    async def add_file(self, jid: str, path: str, action: str = "creado") -> None:
        """Apunta un archivo tocado por el trabajo. action: creado | modificado |
        verificado | pendiente_de_verificar (specs v23 T12)."""
        job = self._jobs.get(jid)
        if not job:
            return
        job.setdefault("files", []).append({"path": str(path)[:400], "action": action})
        await self._emit()

    async def waiting(self, jid: str, question: str) -> None:
        """El trabajo se para a esperar una confirmación del operador."""
        job = self._jobs.get(jid)
        if not job:
            return
        job["status"] = "waiting_confirmation"
        job.setdefault("confirmations_requested", []).append(
            {"q": question[:300], "ts": time.time()})
        await self._emit()

    async def confirmed(self, jid: str, answer: str) -> None:
        job = self._jobs.get(jid)
        if not job:
            return
        job.setdefault("confirmations_received", []).append(
            {"a": answer[:120], "ts": time.time()})
        if job["status"] == "waiting_confirmation":
            job["status"] = "running"
        await self._emit()

    async def _run(self, jid: str, coro_factory) -> None:
        job = self._jobs[jid]
        async with self._sema():
            if job["status"] == "cancelled":
                return
            job["status"] = "running"
            job["started"] = time.time()
            await self._emit()
            await bus.emit("log", {"level": "info",
                                   "msg": f"▶ Trabajo #{job['num']}: {job['title']}"})
            try:
                res = await coro_factory()
                if isinstance(res, dict):
                    for f in (res.get("files") or []):
                        job.setdefault("files", []).append(
                            f if isinstance(f, dict) else {"path": str(f), "action": "creado"})
                    res = res.get("reply", "") or "Hecho."
                job["result"] = str(res)[:2000]
                job["status"] = "completed"
                job["progress"] = 100
            except asyncio.CancelledError:
                job["status"] = "cancelled"
            except Exception as exc:            # noqa: BLE001
                job["status"] = "failed"
                job["error"] = f"{type(exc).__name__}: {exc}"[:400]
            job["ended"] = time.time()
            job["seen"] = False
            self._tasks.pop(jid, None)
            await self._emit()
            lvl = "ok" if job["status"] == "completed" else "warn"
            await bus.emit("log", {"level": lvl,
                                   "msg": f"■ Trabajo #{job['num']} ({job['title']}) → {job['status']}"})
            _audit(action=f"job_{job['status']}", agent=job.get("agent", "nexus"),
                   request=job.get("request", ""), run_id=job.get("request_id", ""),
                   channel=job.get("channel", ""), destructive=False,
                   result=job.get("result", "")[:300], error=job.get("error", ""),
                   extra={"files": job.get("files", []), "num": job.get("num")})
            # Un trabajo CANCELADO nunca publica resultado (anti-fantasma, T9).
            if job["status"] == "cancelled":
                return
            await bus.emit("job_done", {
                "id": jid, "num": job["num"], "title": job["title"],
                "status": job["status"], "result": job["result"],
                "error": job["error"], "files": job.get("files", []),
                "agent": job.get("agent", "nexus"), "channel": job.get("channel", "pc"),
                "request_id": job.get("request_id", "")})
            if job.get("notify"):
                await self._notify(job)

    async def _notify(self, job: dict) -> None:
        """Publica el resultado UNA sola vez, para trabajos que no cantan el suyo."""
        if job["status"] == "completed":
            res = job["result"] or ""
            # Si el propio trabajo ya trae su titular (Hermes: «🪽 ESTADO: …»), se
            # publica tal cual: no hace falta ponerle otra cabecera encima.
            texto = res if res[:2] in ("🪽", "✔ ", "⚠ ", "❌") or res.startswith(
                ("🪽", "ESTADO:")) else (
                f"✔ Trabajo #{job['num']} terminado ({job['title']}):\n\n{res}")
        else:
            texto = (f"✖ Trabajo #{job['num']} ({job['title']}) ha FALLADO: "
                     f"{job['error'] or 'sin detalle'}. No doy nada por hecho.")
        if job.get("files"):
            texto += "\n\nArchivos: " + ", ".join(
                f"{f.get('action', 'creado')} → {f.get('path', '')}" for f in job["files"][:8])
        await bus.emit("chat", {"user": f"[trabajo #{job['num']}]", "reply": texto,
                                "provider": "multitarea", "skill": None,
                                "channel": job.get("channel", "pc")})
        if job.get("channel") == "telegram":
            try:
                from .telegram_bridge import send_telegram
                await send_telegram(texto)
            except Exception:
                pass

    async def cancel(self, jid: str) -> bool:
        job = self._jobs.get(jid)
        if not job:
            return False
        if job["status"] in ("queued", "waiting_confirmation"):
            job["status"] = "cancelled"
            job["ended"] = time.time()
        t = self._tasks.get(jid)
        if t and not t.done():
            t.cancel()
        _audit(action="job_cancel", actor="operador", agent=job.get("agent", "nexus"),
               request=job.get("request", ""), run_id=job.get("request_id", ""),
               result="cancelado a petición")
        await self._emit()
        return True

    async def cancel_obsolete(self, channel: str = "", keep_request_id: str = "",
                              kind: str = "") -> int:
        """Cancela los trabajos VIVOS de un canal salvo el de la petición actual.
        Se usa cuando el operador dice «déjalo» o «olvida lo anterior» (T9)."""
        n = 0
        for j in list(self._jobs.values()):
            if j["status"] not in LIVE_STATES:
                continue
            if channel and j.get("channel") != channel:
                continue
            if kind and j.get("kind") != kind:
                continue
            if keep_request_id and j.get("request_id") == keep_request_id:
                continue
            await self.cancel(j["id"])
            n += 1
        return n

    async def mark_seen(self, jid: str = "") -> int:
        """Marca como REVISADOS los resultados (limpia el ✓/! del sidebar)."""
        n = 0
        for j in self._jobs.values():
            if jid and j["id"] != jid:
                continue
            if j["status"] in FINAL_STATES and not j.get("seen"):
                j["seen"] = True
                n += 1
        if n:
            await self._emit()
        return n

    def clear_done(self) -> int:
        """Quita de la lista los trabajos ya terminados (para limpiar el panel)."""
        keep = [j for j in self._order
                if self._jobs.get(j, {}).get("status") in LIVE_STATES]
        removed = len(self._order) - len(keep)
        for j in list(self._jobs):
            if j not in keep:
                self._jobs.pop(j, None)
        self._order = keep
        self._persist()
        return removed


jobs = JobManager(max_concurrent=4)

# El bus necesita saber si hay algo en marcha para no dejar pasar un «estoy en
# ello» cuando no lo hay. Lo sabe este módulo, así que es este el que se ofrece;
# el bus está por debajo y no puede preguntárselo.
events.registrar_hay_trabajo(lambda: bool(jobs.active()))
