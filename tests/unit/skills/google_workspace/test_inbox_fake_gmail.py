# -*- coding: utf-8 -*-
"""Inbox job contract test against a FAKE Gmail/Calendar/Tasks provider.
The only Gmail write the fake accepts is batchModify removing UNREAD (T8: mark CONVERTED mails read).

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


from fake_gmail import (FakeGoogle, GMAIL_READS, GMAIL_WRITES, HttpError, b64, mail)  # noqa: E402,F401


# ───────────────────────────── module under test ─────────────────────────────
_spec = importlib.util.spec_from_file_location(
    "gw_skill_fake_gmail_test", os.environ.get("NEXUS_SCALE_SKILL_PATH") or os.path.join(
        ROOT, "skills", "google_workspace", "skill.py"))
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

LLM = {"raw": "", "calls": 0, "boom": False, "prompts": [], "systems": []}


async def _fake_ask_llm(prompt, system=None, **kw):
    LLM["calls"] += 1
    LLM["prompts"].append(prompt)
    LLM["systems"].append(system or "")
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
    LLM.update(raw=raw, calls=0, boom=boom, prompts=[], systems=[])


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
          '"resumen": "Pide el informe trimestral antes del 15/09.", '
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
GM = "https://mail.google.com/mail/u/0/#all/"
check(act.get("description") == chr(10).join([
    "Qué pide: Pide el informe trimestral antes del 15/09.", "Plazo: 15/09/2026",
    "Urgencia: ALTA — plazo", "De: Ana Gomez", "Asunto: Entrega informe",
    "Recibido: 03/10/2026 09:30", "Correo: " + GM + "m-act"]), f"J3 description: {act.get('description')!r}")
check(act.get("sourceUrl") == GM + "m-act" and alert.get("sourceUrl") == GM + "m-alert",
      f"J3 sourceUrl: {act.get('sourceUrl')} {alert.get('sourceUrl')}")
check(alert.get("title") == "Revisar alerta urgente: [ALERTA] disco al 98% (Monitor)"
      and "Qué pide: marca «[alerta]» en el asunto" in alert.get("description", "")
      and "Plazo: sin plazo indicado" in alert.get("description", "")
      and "Urgencia: CRÍTICA — marca" in alert.get("description", "")
      and alert.get("description", "").endswith("Correo: " + GM + "m-alert"),
      f"J3 safety-net title/description: {alert.get('title')!r} {alert.get('description')!r}")
check(g.events[0]["description"] == act["description"] and g.tasks[0]["notes"] == alert["description"],
      f"J3 Google notes carry the same description: {g.events[0].get('description')!r} {g.tasks[0]}")
sysp = LLM["systems"][0]
check('"resumen"' in sysp and "verbo en imperativo + objeto concreto" in sysp and "90 caracteres" in sysp
      and "NUNCA genérico" in sysp, "J3: classifier prompt asks for a concrete title and a summary")
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

# ── (f) Gmail: reads + ONLY "remove UNREAD" from the converted ids (same run) ──
print("== f) Gmail: only removes UNREAD from converted mails ==")
gmail_ops = {n for n in g.log if n.startswith("gmail.")}
check(bool(gmail_ops) and gmail_ops <= GMAIL_READS | GMAIL_WRITES, f"gmail ops: {gmail_ops}")
check("gmail.messages.batchModify" in gmail_ops and len(g.inserts("gmail.messages.batchModify")) == 1,
      "marking is ONE batchModify call")
check(not [n for n in g.log if n.startswith("FORBIDDEN")], f"forbidden access: {g.log}")
check(sorted(g.marked()) == ["m-act", "m-alert"], f"marked = the 2 converted mails: {g.marked()}")
check(g.inserts("gmail.messages.batchModify")[0] == {
    "userId": "me", "body": {"ids": g.marked(), "removeLabelIds": ["UNREAD"]}}, "exact batchModify request")
check(g.unread_ids() == ["m-news"], f"only the non-actionable newsletter stays unread: {g.unread_ids()}")
check(all("INBOX" in m["labelIds"] for m in g.messages.values()) and len(g.messages) == 3,
      "no label added, no mail deleted")
check("He marcado como leídos 2 correo(s)" in r, f"reply says how many were marked: {r}")

# ── (c0) natural rerun: marked mails are gone from the unread list ───────────
print("== c0) rerun after marking ==")
marks_before = len(g.marked())
LLM.update(raw='[{"i": 0, "urgente": false, "importancia": "baja", "accionable": false, '
                '"tarea": "", "fecha": "", "motivo": "boletin"}]', calls=0, prompts=[])
r0 = run_job()
check(LLM["calls"] == 1 and "Ofertas de la semana" in LLM["prompts"][0]
      and "Entrega informe" not in LLM["prompts"][0] and "[ALERTA]" not in LLM["prompts"][0],
      f"c0: LLM sees only the unread newsletter: {LLM['prompts']}")
check("ninguno pide una acción concreta" in r0 and "Alcance" not in r0 and "marcado" not in r0.lower(),
      f"c0 reply: {r0}")
check(len(g.marked()) == marks_before and g.unread_ids() == ["m-news"], "c0: nothing new marked")
# Simulate an EARLIER run whose marking failed: the 2 tasked mails are unread again.
for _i in ("m-alert", "m-act"):
    g.messages[_i]["labelIds"].append("UNREAD")

# ── (c) rerun: dedupe ────────────────────────────────────────────────────────
print("== c) rerun dedupes ==")
before = (len(board._load()), len(g.events), len(g.tasks))
reads_before = len([1 for n, kw in g.calls if n == "gmail.messages.get" and kw.get("format") == "full"])
# Rerun: the 2 mails that already have a task are skipped BEFORE reading/LLM; the model only
# sees the newsletter (local index 0), which has no task because it is not actionable.
LLM.update(raw='[{"i": 0, "urgente": false, "importancia": "baja", "accionable": false, '
                '"tarea": "", "fecha": "", "motivo": "boletin"}]', calls=0, prompts=[])
r2 = run_job()
after = (len(board._load()), len(g.events), len(g.tasks))
check(after == before, f"rerun created nothing: {before} -> {after}")
check("ya tenían tarea" in r2 and "ninguna tarea nueva" in r2, f"rerun reply: {r2}")
check("Alcance: analizados 1 de 3 sin leer" in r2 and "2 ya tenían tarea" in r2, f"rerun scope: {r2}")
check(LLM["calls"] == 1 and "Ofertas de la semana" in LLM["prompts"][0]
      and "Entrega informe" not in LLM["prompts"][0] and "[ALERTA]" not in LLM["prompts"][0],
      f"rerun: only the not-yet-tasked mail reaches the LLM: {LLM['prompts']}")
reads_after = len([1 for n, kw in g.calls if n == "gmail.messages.get" and kw.get("format") == "full"])
check(reads_after - reads_before == 1, f"rerun: only 1 body read ({reads_after - reads_before})")
check("❌" not in r2 and "falló" not in r2, f"rerun is not an error: {r2}")
check(sorted(g.marked()[marks_before:]) == ["m-act", "m-alert"] and g.unread_ids() == ["m-news"],
      f"previously tasked mails are marked now (not the newsletter): {g.marked()}")
check("He marcado como leídos 2 correo(s)" in r2, f"rerun reply states the marking: {r2}")

# ── (b2) J3 fallbacks: model omits tarea/resumen/fecha; mail without Date header ───────────
print("== b2) J3 fallbacks stay honest ==")
g = FakeGoogle([mail("m-fb", '"Ana Gomez" <ana@corp.example>', "Contrato", "Firma el contrato.", date="")])
fresh(g, '[{"i": 0, "urgente": false, "importancia": "media", "accionable": true, "tarea": "", '
         '"fecha": "", "tipo": "hacer"}]')
r = run_job()
fb = board._load()[0]
check(fb["title"] == "Atender correo de Ana Gomez: Contrato",
      f"J3 fallback title: {fb['title']!r}")
lines = fb["description"].split(chr(10))
check(lines[0] == "Qué pide: el modelo no dio resumen; abre el correo para ver qué se pide"
      and lines[1] == "Plazo: sin plazo indicado" and lines[2] == "Urgencia: MEDIA — sin motivo indicado"
      and lines[3] == "De: Ana Gomez" and lines[4] == "Asunto: Contrato" and lines[-1] == "Correo: " + GM + "m-fb",
      f"J3 fallback description: {lines}")
import re as _re  # noqa: E402
check(any(_re.fullmatch(r"Recibido: 2[12]/09/2026 \d\d:\d\d", ln) for ln in lines),
      f"J3 date falls back to internalDate when no Date header: {lines}")
check(fb["sourceUrl"] == GM + "m-fb", "J3 fallback keeps sourceUrl")
# motivo is used as the summary when only the summary is missing
g = FakeGoogle([mail("m-mo", "Ana <a@b.example>", "Pago", "Paga.")])
fresh(g, '[{"i": 0, "accionable": true, "tarea": "Pagar cuota", "fecha": "2026-09-01", "motivo": "vence pronto", "urgencia": "baja"}]')
run_job()
mo = board._load()[0]
check(mo["description"].split(chr(10))[0] == "Qué pide: vence pronto"
      and "Plazo: 01/09/2026" in mo["description"], f"J3 motivo as summary fallback: {mo['description']!r}")

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
check(g.marked() == ["m-alert"] and sorted(g.unread_ids()) == ["m-act", "m-news"],
      f"garbage: only the converted alert is marked; unclassified stay unread: {g.marked()}")

g = FakeGoogle([m for m in inbox() if m["id"] != "m-alert"])
fresh(g, "not json at all")
r = run_job()
check("No he podido analizar NINGUNO" in r and "no he creado ninguna tarea" in r,
      f"all unclassified: {r}")
check("ninguno pide" not in r and "tarea(s) creadas" not in r, f"no false reassurance: {r}")
check(board._load() == [] and g.events == [] and g.tasks == [], "garbage: nothing created")
check(g.marked() == [] and "gmail.messages.batchModify" not in g.log and len(g.unread_ids()) == 2
      and "marcado" not in r.lower(), f"all unclassified: nothing marked, no API call: {g.log}")

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
check(not [n for n in g.log if n.startswith("FORBIDDEN")], "no forbidden access after errors")
check(sorted(g.marked()) == ["m-act", "m-alert"], f"snippet fallback still marks the converted: {g.marked()}")

# API errors on the first reads: nothing was converted, so nothing is marked.
for op in ("gmail.labels.get", "gmail.messages.list"):
    g = FakeGoogle(inbox(), fail_on=lambda n, op=op: n == op)
    fresh(g, CANNED)
    run_job()
    check(g.marked() == [] and "gmail.messages.batchModify" not in g.log, f"{op}: nothing marked")

# ── (g) batchModify raising: honest warning, tasks still reported ────────────
print("== g) marking failure ==")
g = FakeGoogle(inbox(), fail_on=lambda n: n == "gmail.messages.batchModify")
fresh(g, CANNED)
r = run_job()
check("2 tarea(s) creadas" in r and not r.startswith("El análisis de correos ha fallado"),
      f"g: created tasks still reported: {r}")
check("⚠️ No he podido marcar como leídos 2 correos: HttpError" in r and "He marcado" not in r,
      f"g: honest warning, no false 'marked': {r}")
check(len(board._load()) == 2 and len(g.events) == 1 and len(g.tasks) == 1, "g: board + Google intact")
check(sorted(g.unread_ids()) == ["m-act", "m-alert", "m-news"], "g: nothing marked in Gmail")

# ── (h) failed creation is not marked; Google failure with board OK is ───────
print("== h) failed creation vs Google-only failure ==")
g = FakeGoogle(inbox(), fail_on=lambda n: n in ("calendar.events.insert", "tasks.tasks.insert"))
fresh(g, CANNED)
_real_add = board.add_task
board.add_task = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
try:
    r = run_job()
finally:
    board.add_task = _real_add
check("NO pude GUARDAR ninguna" in r, f"h: nothing saved anywhere: {r}")
check(g.marked() == [] and "gmail.messages.batchModify" not in g.log and len(g.unread_ids()) == 3,
      f"h: failed creation is NEVER marked read: {g.marked()}")
check("marcado" not in r.lower(), f"h: no marking claim: {r}")
g = FakeGoogle(inbox(), fail_on=lambda n: n in ("calendar.events.insert", "tasks.tasks.insert"))
fresh(g, CANNED)
r = run_job()
check("En Google no pude guardarlas" in r and len(board._load()) == 2, f"h2: board only: {r}")
check(sorted(g.marked()) == ["m-act", "m-alert"] and g.unread_ids() == ["m-news"],
      f"h2: board saved -> converted -> marked: {g.marked()}")

# ── (i) the urgent job never writes to Gmail ─────────────────────────────────
print("== i) urgent job is read-only ==")
g = FakeGoogle(inbox())
fresh(g, CANNED)
ur = asyncio.run(gw._email_urgent_job(None, "api"))["reply"]
check(ur and "gmail.messages.batchModify" not in g.log and g.marked() == []
      and not [n for n in g.log if n.startswith("FORBIDDEN")], f"i: urgent job wrote to Gmail: {g.log}")
check(len(g.unread_ids()) == 3, "i: every mail still unread after the urgent job")
check({n for n in g.log if n.startswith("gmail.")} <= GMAIL_READS, "i: only Gmail reads")

# ── (j) _mark_read helper ────────────────────────────────────────────────────
print("== j) _mark_read helper ==")
g = FakeGoogle(inbox())
CURRENT["google"] = g
check(gw._mark_read([]) == 0 and g.log == [] and g.calls == [], "j: empty list -> no API call")
check(asyncio.run(gw._mark_converted_read([])) == "" and g.calls == [], "j: nothing to mark -> no call, no text")
n_one = gw._mark_read(["m-act"])
check(n_one == 1, "j: returns how many were marked")
check(g.inserts("gmail.messages.batchModify") == [
    {"userId": "me", "body": {"ids": ["m-act"], "removeLabelIds": ["UNREAD"]}}], "j: exact body")
check(sorted(g.unread_ids()) == ["m-alert", "m-news"], "j: only that mail was marked read")
txt = asyncio.run(gw._mark_converted_read(["m-alert", "m-alert", "", "m-news", "m-alert"]))
check(g.marked()[1:] == ["m-alert", "m-news"] and "marcado como leídos 2" in txt,
      f"j: ids deduped, blanks dropped: {g.marked()} {txt!r}")
g = FakeGoogle(inbox())
CURRENT["google"] = g
big = ["x" + str(i) for i in range(2500)]
check(gw._mark_read(big) == 2500, "j: big list returns total")
sizes = [len(kw["body"]["ids"]) for n, kw in g.calls if n == "gmail.messages.batchModify"]
check(len(sizes) >= 3 and max(sizes) <= 1000 and sum(sizes) == 2500 and sorted(g.marked()) == sorted(big),
      f"j: chunked to <=1000 per call: {sizes}")

# ── (k) the fake itself: only "remove UNREAD" is allowed ─────────────────────
print("== k) fake allows nothing else on Gmail ==")
g = FakeGoogle(inbox())


def api():
    return g.build("gmail", "v1").users().messages()


def bm(**body):
    return lambda: api().batchModify(userId="me", body=body).execute()


bad = [
    lambda: api().modify(userId="me", id="m-act", body={}).execute(),
    lambda: api().trash(userId="me", id="m-act").execute(),
    lambda: api().delete(userId="me", id="m-act").execute(),
    lambda: api().send(userId="me", body={}).execute(),
    lambda: api().batchDelete(userId="me", body={"ids": ["m-act"]}).execute(),
    bm(ids=["m-act"], addLabelIds=["UNREAD"]),
    bm(ids=["m-act"], removeLabelIds=["INBOX"]),
    bm(ids=["m-act"], removeLabelIds=["UNREAD", "INBOX"]),
    bm(ids=["m-act"], removeLabelIds=["UNREAD"], addLabelIds=["TRASH"]),
    bm(ids=[], removeLabelIds=["UNREAD"]),
    bm(removeLabelIds=["UNREAD"]),
]
raised = 0
for fn in bad:
    try:
        fn()
    except AttributeError:
        raised += 1
check(raised == len(bad), f"k: every non-'remove UNREAD' Gmail write raises ({raised}/{len(bad)})")
check(len([n for n in g.log if n.startswith("FORBIDDEN")]) == len(bad), f"k: each one logged FORBIDDEN: {g.log}")
check(sorted(g.unread_ids()) == ["m-act", "m-alert", "m-news"] and all(
    m["labelIds"] == ["INBOX", "UNREAD"] for m in g.messages.values()), "k: state untouched by forbidden calls")

# ── (r1) real Google failure causes are reported, not a fake "authorization" diagnosis ──
print("== r1) Google error classification ==")
import json as _json  # noqa: E402

PROJECT = "519934480123"


class _Resp:
    def __init__(self, status):
        self.status, self.reason = status, "x"


class GErr(Exception):
    """googleapiclient HttpError shape: resp.status, content (JSON bytes), error_details."""

    def __init__(self, status, reason=None, gstatus=None, api="Tasks", details=None):
        msg = (f"Google {api} API has not been used in project {PROJECT} before or it is disabled. "
               f"Enable it by visiting https://console.developers.google.com/apis/api/x?project={PROJECT}"
               if reason == "accessNotConfigured" or (details and details[0]["reason"] == "SERVICE_DISABLED") else f"Request failed for project {PROJECT}")
        body = {"error": {"code": status, "message": msg, "status": gstatus or "",
                          "errors": [{"reason": reason}] if reason else []}}
        super().__init__(f'<HttpError {status} "{msg}">')
        self.resp = _Resp(status)
        self.content = _json.dumps(body).encode()
        self.error_details = details


def cause(e, api=""):
    return gw._google_error_cause(e, api)


check(cause(GErr(403, "accessNotConfigured"), "Tasks")[0] == "api_disabled", "r1: accessNotConfigured")
check(cause(GErr(403, None, "PERMISSION_DENIED", details=[{"reason": "SERVICE_DISABLED"}]))[0] == "api_disabled",
      "r1: SERVICE_DISABLED via error_details")
check("Calendar" in cause(GErr(403, "accessNotConfigured"), "Calendar")[1], "r1: names Calendar")
check("Tasks" in cause(GErr(403, "accessNotConfigured"), "Tasks")[1]
      and "consola" in cause(GErr(403, "accessNotConfigured"), "Tasks")[1], "r1: names Tasks + console")
check(cause(GErr(403, "insufficientPermissions"))[0] == "auth", "r1: insufficientPermissions")
check(cause(GErr(403, None, details=[{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]))[0] == "auth",
      "r1: scope insufficient")
check(cause(GErr(401))[0] == "auth", "r1: 401")
check(cause(type("RefreshError", (Exception,), {})("invalid_grant: Bad Request"))[0] == "auth", "r1: invalid_grant")
check(cause(GErr(429))[0] == "quota" and cause(GErr(403, "rateLimitExceeded"))[0] == "quota"
      and cause(GErr(403, "quotaExceeded"))[0] == "quota", "r1: quota")
check(cause(GErr(500))[0] == "server" and cause(GErr(503))[0] == "server", "r1: 5xx")
code, txt = cause(ValueError("boom"))
check(code == "other" and "ValueError" in txt, f"r1: other keeps type: {txt}")
check(cause(GErr(404))[0] == "other", "r1: generic 404")
check(cause(HttpError())[0] == "server", "r1: fake_gmail HttpError (status attr only)")
check(all(PROJECT not in cause(GErr(403, "accessNotConfigured"), a)[1] and "http" not in cause(
    GErr(403, "accessNotConfigured"), a)[1] for a in ("Tasks", "Calendar", "")), "r1: no project/url leak")


def run_failing(make_err):
    g2 = FakeGoogle(inbox())

    def boom(kw):
        raise make_err()
    g2._insert_event = boom
    g2._insert_task = boom
    fresh(g2, CANNED)
    return run_job(), g2


r1, g2 = run_failing(lambda: GErr(403, "accessNotConfigured"))
check("autorización" not in r1 and "Casi seguro" not in r1, f"r1: api_disabled has no auth text: {r1}")
check("no está activada" in r1 and "consola" in r1 and "API de Tasks desactivada" in r1
      and "API de Calendar desactivada" in r1, f"r1: api_disabled cause shown: {r1}")
check(PROJECT not in r1 and "http" not in r1, "r1: no project number/url in reply")
check("tablero interno" in r1 and len(board._load()) == 2, "r1: board still saves (T8 literal)")
check(r1.count("la API de Google Tasks no está activada") == 1, f"r1: causes deduped: {r1}")

r2, _ = run_failing(lambda: GErr(403, "insufficientPermissions"))
check("autorización" in r2, f"r1: auth keeps advice: {r2}")
for mk, needle in ((lambda: GErr(429), "cuota"), (lambda: GErr(500), "servidor de Google"),
                   (lambda: ValueError("x"), "ValueError")):
    rr, _ = run_failing(mk)
    check(needle in rr and "autorización" not in rr, f"r1: {needle} reply: {rr}")

# all-Google-and-board-failed branch: "nothing could be saved" uses the real cause too
_real_add = board.add_task
board.add_task = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("board down"))
try:
    r3, _ = run_failing(lambda: GErr(403, "accessNotConfigured"))
finally:
    board.add_task = _real_add
check("NO pude" in r3 and "no está activada" in r3 and "autorización" not in r3 and PROJECT not in r3,
      f"r1: nothing-saved branch uses real cause: {r3}")

# positional callers keep working; causes is an optional out-param
fresh(FakeGoogle([]))
out = gw._create_everywhere("t", None, "n", "alta")
check("Google Tasks" in out and "tablero interno" in out, f"r1: positional contract: {out}")

# ── J6: sender cleaning, title cap and contextual titles ──
for raw_from, want in (("Ana Gomez <ana@corp.example>", "Ana Gomez"),
                       ('"Alerta de empleo InfoJobs" <no-reply@infojobs.net>', "Alerta de empleo InfoJobs"),
                       ("<solo@corp.example>", "solo@corp.example"),
                       ("solo@corp.example", "solo@corp.example")):
    got = gw._remitente({"from": raw_from})
    check(got == want and "<" not in got and ">" not in got, f"j6: _remitente({raw_from!r}) = {got!r}")

long_t = "Responder al cliente sobre la renovación del contrato de mantenimiento anual de la plataforma interna"
capped = gw._cap_title(long_t)
check(len(capped) <= 90 and capped.endswith("…") and long_t.startswith(capped[:-1]) and
      long_t[len(capped) - 1] == " ", f"j6: cap on word boundary: {capped!r}")
check(gw._cap_title("Titulo corto") == "Titulo corto", "j6: short title untouched")

ctx = gw._contextual_title("Revisa la oferta laboral sugerida",
                           {"from": "Alerta de empleo InfoJobs <a@infojobs.net>",
                            "subject": "1 oferta de empleo en Madrid"})
check(ctx.startswith("Revisa la oferta laboral sugerida — 1 oferta de empleo en Madrid (Alerta de")
      and len(ctx) <= 90, f"j6: generic title gets context: {ctx!r}")
spec = gw._contextual_title("Pagar la factura de Iberdrola",
                            {"from": "Iberdrola <x@i.es>", "subject": "Factura disponible"})
check(spec == "Pagar la factura de Iberdrola", f"j6: specific title kept: {spec!r}")
acc = gw._contextual_title("Revisar éxito", {"from": "X <x@y.es>", "subject": "EXITO total"})
check("—" not in acc, f"j6: accent/case-insensitive token match: {acc!r}")
check(len(gw._alerta_titulo({"from": "x@y.es", "subject": "palabra " * 30}, "seguridad")) <= 90,
      "j6: safety-net title capped")

fresh(FakeGoogle([mail("m-j6", "Alerta de empleo InfoJobs <n@infojobs.net>",
                       "1 oferta de empleo en Madrid", "Hay una oferta nueva para ti.")]),
      raw='[{"i":0,"urgente":false,"importancia":"media","accionable":true,'
          '"tarea":"Revisa la oferta laboral sugerida","fecha":"","resumen":"","motivo":""}]')
run_job()
j6_titles = [x.get("title", "") for x in board._load()]
check(any(x.startswith("Revisa la oferta laboral sugerida — 1 oferta de empleo en Madrid")
          and len(x) <= 90 for x in j6_titles), f"j6: job title end-to-end: {j6_titles}")

print()
for k, v in _saved_mods.items():
    if v is None:
        sys.modules.pop(k, None)
    else:
        sys.modules[k] = v
print(f"test_inbox_fake_gmail: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
