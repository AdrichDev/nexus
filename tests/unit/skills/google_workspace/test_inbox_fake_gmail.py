# -*- coding: utf-8 -*-
"""Inbox job contract test against a FAKE Gmail/Calendar/Tasks provider.

The real functions of skills/google_workspace/skill.py run (_count_unread, _fetch_emails,
_read_email, _load_unread_bodies, _analyze_emails, _create_everywhere, _create_event,
_create_task, _email_actions_job). Only two seams are replaced:
  * googleapiclient.discovery.build -> returns a fake object graph with Google client shapes
    (resource chaining ending in .execute()),
  * backend.core.infraestructura.llm.ask_llm -> canned text.
No network, no credentials; board data dir is temporary.
Run:  python tests/unit/skills/google_workspace/test_inbox_fake_gmail.py
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="nexus_inbox_fake_gmail_")
os.environ["NEXUS_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["NEXUS_CONFIG_DIR"] = os.path.join(TMP, "config")

from backend.core.dominio import board  # noqa: E402

board.BOARD_FILE = board.DATA_DIR / "board.json"
board.TRASH_FILE = board.DATA_DIR / "board_trash.json"
assert str(board.BOARD_FILE).startswith(TMP), "board must point at the temp dir"

_fail: list[str] = []
_ok = 0


def check(cond, msg):
    global _ok
    if cond:
        _ok += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


# ───────────────────────────── fake Google API ─────────────────────────────
class HttpError(Exception):
    """Stand-in for googleapiclient.errors.HttpError (status + reason)."""

    def __init__(self, status=500, reason="backendError"):
        super().__init__(f"<HttpError {status} \"{reason}\">")
        self.status = status


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def mail(mid, sender, subject, plain, *, multipart=False, unread=True):
    """A Gmail `users.messages` resource as the API returns it for format=full."""
    if multipart:
        payload = {"mimeType": "multipart/alternative", "body": {"size": 0}, "parts": [
            {"mimeType": "text/html", "body": {"data": b64("<p>" + plain + "</p>")}},
            {"mimeType": "multipart/related", "body": {"size": 0}, "parts": [
                {"mimeType": "text/plain", "body": {"data": b64(plain)}}]}]}
    else:
        payload = {"mimeType": "text/plain", "body": {"data": b64(plain)}}
    payload["headers"] = [{"name": "From", "value": sender},
                          {"name": "Subject", "value": subject}]
    return {"id": mid, "threadId": "t" + mid, "snippet": plain[:100],
            "labelIds": ["INBOX"] + (["UNREAD"] if unread else []), "payload": payload}


class _Call:
    """The request object returned by every API method; nothing happens until .execute()."""

    def __init__(self, fake, name, result):
        self.fake, self.name, self.result = fake, name, result

    def execute(self):
        self.fake.log.append(self.name)
        if self.fake.fail_on and self.fake.fail_on(self.name):
            raise HttpError()
        return self.result()


class _Res:
    """A Google resource exposing only the methods in `ops`. Any other attribute (modify,
    trash, send, delete, ...) is recorded as FORBIDDEN and raises."""

    def __init__(self, fake, prefix, ops):
        self._fake, self._prefix, self._ops = fake, prefix, ops

    def __getattr__(self, name):
        full = f"{self._prefix}.{name}"
        if name not in self._ops:
            self._fake.log.append("FORBIDDEN:" + full)
            raise AttributeError(full)

        def method(**kw):
            self._fake.calls.append((full, kw))
            return _Call(self._fake, full, lambda: self._ops[name](kw))
        return method


class FakeGoogle:
    """Fake Gmail v1 / Calendar v3 / Tasks v1 service objects over one in-memory mailbox."""

    def __init__(self, messages=(), fail_on=None):
        self.messages = {m["id"]: m for m in messages}
        self.fail_on = fail_on          # callable(op_name) -> bool
        self.log: list[str] = []        # executed operations, in order
        self.calls: list[tuple] = []    # (operation, kwargs) as received
        self.events: list[dict] = []
        self.tasks: list[dict] = []

    def inserts(self, op):
        return [kw for name, kw in self.calls if name == op]

    def _labels_get(self, kw):
        unread = [m for m in self.messages.values() if "UNREAD" in m["labelIds"]]
        return {"id": kw["id"], "threadsUnread": len(unread),
                "threadsTotal": len(self.messages)}

    def _list(self, kw):
        want_unread = "is:unread" in kw.get("q", "")
        out = [m for m in self.messages.values()
               if kw["labelIds"][0] in m["labelIds"]
               and (not want_unread or "UNREAD" in m["labelIds"])]
        return {"messages": [{"id": m["id"], "threadId": m["threadId"]}
                             for m in out[:kw.get("maxResults", 100)]],
                "resultSizeEstimate": len(out)}          # single page: no nextPageToken

    def _get(self, kw):
        m = self.messages[kw["id"]]
        if kw.get("format", "full") == "metadata":
            keep = set(kw.get("metadataHeaders") or [])
            hdrs = [h for h in m["payload"]["headers"] if h["name"] in keep]
            return {"id": m["id"], "snippet": m["snippet"], "labelIds": m["labelIds"],
                    "payload": {"headers": hdrs}}
        return m

    def _insert_event(self, kw):
        self.events.append(kw["body"])
        return {"id": f"ev{len(self.events)}", "htmlLink": f"https://fake/ev{len(self.events)}"}

    def _insert_task(self, kw):
        self.tasks.append(kw["body"])
        return {"id": f"tk{len(self.tasks)}"}

    def build(self, api, version, **_kw):
        f = self
        if api == "gmail":
            class Users:
                def messages(_s):
                    return _Res(f, "gmail.messages", {"list": f._list, "get": f._get})

                def labels(_s):
                    return _Res(f, "gmail.labels", {"get": f._labels_get})

            class Svc:
                def users(_s):
                    return Users()
            return Svc()
        if api == "calendar":
            class Svc:
                def events(_s):
                    return _Res(f, "calendar.events", {"insert": f._insert_event})
            return Svc()
        if api == "tasks":
            class Svc:
                def tasks(_s):
                    return _Res(f, "tasks.tasks", {"insert": f._insert_task})
            return Svc()
        raise AssertionError("unexpected API " + api)


GMAIL_READS = {"gmail.labels.get", "gmail.messages.list", "gmail.messages.get"}


# ───────────────────────────── module under test ─────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "gw_skill_fake_gmail_test", os.path.join(ROOT, "skills", "google_workspace", "skill.py"))
gw = importlib.util.module_from_spec(_spec)
sys.modules["gw_skill_fake_gmail_test"] = gw
_spec.loader.exec_module(gw)

# Deterministic classifier config (not dependent on config/umbrales.json): one batch, default marks.
gw._CORREOS = {"por_lote": 30, "por_lote_por_proveedor": {},
               "marcas_urgentes": list(gw._CORREOS_RESERVA["marcas_urgentes"])}
gw._get_creds = lambda: object()          # credentials are never read

CURRENT: dict = {"google": None}


def _fake_build(api, version, **kw):
    return CURRENT["google"].build(api, version, **kw)


# Seam 1: the lazy `from googleapiclient.discovery import build` inside each function.
_saved_mods = {k: sys.modules.get(k) for k in ("googleapiclient", "googleapiclient.discovery")}
_pkg = types.ModuleType("googleapiclient")
_disc = types.ModuleType("googleapiclient.discovery")
_disc.build = _fake_build
_pkg.discovery = _disc
sys.modules["googleapiclient"] = _pkg
sys.modules["googleapiclient.discovery"] = _disc

# Seam 2: the LLM. Only ask_llm is replaced.
from backend.core.infraestructura import llm  # noqa: E402
from backend.core.comun.events import bus  # noqa: E402

LLM = {"raw": "", "calls": 0, "boom": False}


async def _fake_ask_llm(prompt, system=None, **kw):
    LLM["calls"] += 1
    if LLM["boom"]:
        raise RuntimeError("llm down")
    return LLM["raw"], "fake"


async def _noop_emit(*a, **k):
    return None


llm.ask_llm = _fake_ask_llm
bus.emit = _noop_emit


def fresh(google, raw="", boom=False):
    for f in (board.BOARD_FILE, board.TRASH_FILE):
        if f.exists():
            f.unlink()
    CURRENT["google"] = google
    LLM.update(raw=raw, calls=0, boom=boom)


def run_job():
    return asyncio.run(gw._email_actions_job(None, "api"))["reply"]


def inbox():
    return [
        mail("m-alert", "Monitor <alerts@infra.example>", "[ALERTA] disco al 98%",
             "El volumen /data esta casi lleno."),
        mail("m-act", "Ana Gomez <ana@corp.example>", "Entrega informe",
             "Hola, necesito el informe trimestral antes del 2026-09-15. Gracias.",
             multipart=True),
        mail("m-news", "Boletin <news@shop.example>", "Ofertas de la semana",
             "Descuentos en todo. Date de baja aqui."),
    ]


# The model classifies mails 1 and 2 only; the alert (index 0) is left to the mark-based net.
CANNED = ('Aqui va: ```json\n[{"i": 1, "urgente": false, "importancia": "media", '
          '"accionable": true, "tarea": "Entregar informe trimestral", "fecha": "2026-09-15", '
          '"tipo": "hacer", "urgencia": "alta", "motivo": "plazo"},'
          '{"i": 2, "urgente": false, "importancia": "baja", "accionable": false, '
          '"tarea": "", "fecha": "", "motivo": "boletin"}]\n```')

# ── (a) empty inbox ──────────────────────────────────────────────────────────
print("== a) empty inbox ==")
g = FakeGoogle([])
fresh(g)
r = run_job()
check("nada que convertir" in r, f"empty reply: {r}")
check(board._load() == [] and g.events == [] and g.tasks == [], "empty: nothing created")
check(LLM["calls"] == 0, "empty: LLM not called")
check(set(g.log) <= {"gmail.labels.get"}, f"empty: only unread count read: {g.log}")

# ── (b) three unread mails ───────────────────────────────────────────────────
print("== b) alert + actionable multipart + newsletter ==")
g = FakeGoogle(inbox())
fresh(g, CANNED)
r = run_job()
rows = {t["sourceId"]: t for t in board._load()}
check(set(rows) == {"m-alert", "m-act"}, f"board has alert+actionable only: {set(rows)}")
act, alert = rows.get("m-act", {}), rows.get("m-alert", {})
check(act.get("source") == "correo" and act.get("type") == "hacer" and act.get("urgency") == "alta",
      f"actionable pattern: {act}")
check(act.get("title") == "Entregar informe trimestral" and act.get("due") == "2026-09-15",
      f"actionable title/due: {act}")
check("Ana Gomez" in act.get("description", "") and "Entrega informe" in act.get("description", ""),
      f"actionable notes (From without <addr>, Subject): {act.get('description')!r}")
check("<" not in act.get("description", ""), "address part stripped from notes")
check(alert.get("source") == "correo" and alert.get("urgency") == "critica",
      f"alert mark forces critica: {alert}")
check("[ALERTA]" in alert.get("title", ""), f"alert title built from mail: {alert.get('title')!r}")
check(len(g.events) == 1 and g.events[0]["summary"] == "Entregar informe trimestral"
      and g.events[0]["start"] == {"date": "2026-09-15"}
      and g.events[0]["end"] == {"date": "2026-09-16"}
      and "Ana Gomez" in g.events[0]["description"], f"calendar inserts: {g.events}")
check(g.inserts("calendar.events.insert")[0]["calendarId"] == "primary", "calendar id primary")
check(len(g.tasks) == 1 and "[ALERTA]" in g.tasks[0]["title"] and "due" not in g.tasks[0],
      f"tasks inserts (alert has no date): {g.tasks}")
check(g.inserts("tasks.tasks.insert")[0]["tasklist"] == "@default", "default task list")
check("2 tarea(s) creadas" in r and "SIN clasificar" not in r, f"reply: {r}")
check(LLM["calls"] == 1, f"one LLM batch: {LLM['calls']}")
body_reads = [kw for n, kw in g.calls if n == "gmail.messages.get" and kw.get("format") == "full"]
check(len(body_reads) == 3, f"bodies read for all 3 unread: {len(body_reads)}")

# ── (f) read-only on Gmail (same run) ────────────────────────────────────────
print("== f) Gmail is only read ==")
gmail_ops = {n for n in g.log if n.startswith("gmail.")}
check(bool(gmail_ops) and gmail_ops <= GMAIL_READS, f"gmail ops: {gmail_ops}")
check(not [n for n in g.log if n.startswith("FORBIDDEN")], f"forbidden access: {g.log}")
check(all("UNREAD" in m["labelIds"] for m in g.messages.values()), "mails still unread")
check(len(g.messages) == 3, "no mail deleted")

# ── (c) rerun: dedupe ────────────────────────────────────────────────────────
print("== c) rerun dedupes ==")
before = (len(board._load()), len(g.events), len(g.tasks))
r2 = run_job()
after = (len(board._load()), len(g.events), len(g.tasks))
check(after == before, f"rerun created nothing: {before} -> {after}")
check("ya tenían tarea" in r2 and "ninguna tarea nueva" in r2, f"rerun reply: {r2}")
check("❌" not in r2 and "falló" not in r2, f"rerun is not an error: {r2}")

# ── (d) garbage LLM ──────────────────────────────────────────────────────────
print("== d) garbage LLM ==")
g = FakeGoogle(inbox())
fresh(g, "Lo siento, no puedo ayudar con eso en formato JSON.")
r = run_job()
rows = {t["sourceId"]: t for t in board._load()}
check(set(rows) == {"m-alert"}, f"only the mark-based safety net creates: {set(rows)}")
check("SIN clasificar" in r and "2 de 3" in r, f"reply admits unclassified: {r}")
check("1 tarea(s) creadas" in r, f"reply claims only the alert task: {r}")
check(len(g.events) == 0 and len(g.tasks) == 1, f"inserts: events={g.events} tasks={g.tasks}")

g = FakeGoogle([m for m in inbox() if m["id"] != "m-alert"])
fresh(g, "not json at all")
r = run_job()
check("No he podido analizar NINGUNO" in r and "no he creado ninguna tarea" in r,
      f"all unclassified: {r}")
check("ninguno pide" not in r and "tarea(s) creadas" not in r, f"no false reassurance: {r}")
check(board._load() == [] and g.events == [] and g.tasks == [], "garbage: nothing created")

g = FakeGoogle(inbox())
fresh(g, boom=True)
r = run_job()
check(set(t["sourceId"] for t in board._load()) == {"m-alert"} and "SIN clasificar" in r,
      f"LLM exception behaves like garbage: {r}")

# ── (e) Gmail API error ──────────────────────────────────────────────────────
print("== e) Gmail API error ==")
for op in ("gmail.labels.get", "gmail.messages.list"):
    g = FakeGoogle(inbox(), fail_on=lambda n, op=op: n == op)
    fresh(g, CANNED)
    r = run_job()
    check(r.startswith("El análisis de correos ha fallado: HttpError"), f"{op}: honest failure: {r}")
    check("creadas" not in r and "no he creado" not in r.lower(), f"{op}: no claims: {r}")
    check(board._load() == [] and g.events == [] and g.tasks == [], f"{op}: nothing created")

# A body read failing degrades to the snippet (existing behaviour): the job still completes
# honestly and never touches Gmail beyond reads.
g = FakeGoogle(inbox(), fail_on=lambda n: False)
real_get = g._get
g._get = lambda kw: (_ for _ in ()).throw(HttpError()) if kw.get("format") == "full" else real_get(kw)
fresh(g, CANNED)
r = run_job()
check("creadas" in r and not r.startswith("El análisis de correos ha fallado"),
      f"body read failure degrades to snippet: {r}")
check(not [n for n in g.log if n.startswith("FORBIDDEN")], "still read-only after errors")

print()
for k, v in _saved_mods.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v
print(f"test_inbox_fake_gmail: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
