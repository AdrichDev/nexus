# -*- coding: utf-8 -*-
"""Email-to-tasks job: tasks follow the task pattern (type, urgency, source=correo,
sourceId=email id), reruns do not duplicate, and notes stay on the board.

No network, no credentials: Google and mail loaders are monkeypatched; data dir is temporary.
Run:  python tests/unit/core/test_inbox_tasks.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="nexus_inbox_test_")
os.environ["NEXUS_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["NEXUS_CONFIG_DIR"] = os.path.join(TMP, "config")

from backend.core.dominio import board  # noqa: E402

board.BOARD_FILE = board.DATA_DIR / "board.json"
board.TRASH_FILE = board.DATA_DIR / "board_trash.json"
assert str(board.BOARD_FILE).startswith(TMP), "board must point at the temp dir"

_spec = importlib.util.spec_from_file_location(
    "gw_skill_inbox_test", os.path.join(ROOT, "skills", "google_workspace", "skill.py"))
gw = importlib.util.module_from_spec(_spec)
sys.modules["gw_skill_inbox_test"] = gw
_spec.loader.exec_module(gw)

_fail: list[str] = []
_ok = 0


def check(cond, msg):
    global _ok
    if cond:
        _ok += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


def fresh():
    for f in (board.BOARD_FILE, board.TRASH_FILE):
        if f.exists():
            f.unlink()


print("== 1) find_by_source ==")
fresh()
t = board.add_task("pagar luz", source="correo", source_id="m1")
check((board.find_by_source("correo", "m1") or {}).get("id") == t["id"], "hit")
check(board.find_by_source("correo", "zzz") is None, "miss: other id")
check(board.find_by_source("manual", "m1") is None, "miss: other source")
check(board.find_by_source("correo", "") is None, "empty id never matches")
board.add_task("sin id", source="correo")
check(board.find_by_source("correo", "") is None, "empty sourceId task is not a match")
board.move_task(t["id"], "hecho")
done = board.find_by_source("correo", "m1")
check(done is not None, "done task still matches")
tasks = board._load()
for x in tasks:
    if x["id"] == t["id"]:
        x["deletedAt"] = "2026-01-01T00:00:00"
board._save(tasks)
check(board.find_by_source("correo", "m1") is None, "trashed (deletedAt) task ignored")

print("== 2) classifier output -> type/urgency ==")
f = gw._email_task_fields
check(f({"tipo": "pagar", "urgencia": "critica"}) == ("pagar", "critica"), "explicit")
check(f({"tipo": "Responder", "urgencia": "Alta"}) == ("responder", "alta"), "normalized")
check(f({"urgente": True, "importancia": "baja"}) == ("hacer", "critica"), "urgente -> critica, default type")
check(f({"importancia": "alta"}) == ("hacer", "alta"), "importancia alta")
check(f({"importancia": "media"}) == ("hacer", "media"), "importancia media")
check(f({"importancia": "baja"}) == ("hacer", "baja"), "importancia baja")
check(f({}) == ("hacer", "media"), "nothing given -> defaults")
check(f({"tipo": "inventado", "urgencia": "xx", "importancia": "baja"}) == ("hacer", "baja"),
      "invalid values fall back")

print("== 3) job: create once, dedupe on rerun ==")
fresh()
calls = {"event": 0, "task": 0}
emails = [
    {"id": "e1", "from": "a@x.com", "subject": "Factura", "body": "paga"},
    {"id": "e2", "from": "b@x.com", "subject": "Reunion", "body": "ven"},
    {"id": "e3", "from": "c@x.com", "subject": "Spam", "body": "nada"},
]
analysis = [
    {"i": 0, "accionable": True, "tarea": "Pagar factura", "fecha": "2026-08-01",
     "tipo": "pagar", "urgencia": "critica", "urgente": True, "importancia": "alta"},
    {"i": 1, "accionable": True, "tarea": "Responder a B", "fecha": "",
     "importancia": "media"},
    {"i": 2, "accionable": False},
]


load_calls = []


async def fake_load(n=30, skip=None):
    """Same contract as gw._load_unread_scope: skip() runs on metadata, skipped mails are
    returned apart and their body would never be read."""
    load_calls.append(n)
    fetched = [dict(m) for m in emails]
    skipped = [m for m in fetched if skip and skip(m)]
    keep = [m for m in fetched if m not in skipped]
    return keep, skipped, len(fetched), len(fetched)


analyzed_ids = []


async def fake_analyze(msgs):
    """Classify only the mails the job actually sends (canned verdicts keyed by mail id)."""
    analyzed_ids.append([m["id"] for m in msgs])
    by_id = {emails[a["i"]]["id"]: a for a in analysis}
    return [{**by_id[m["id"]], "i": k} for k, m in enumerate(msgs) if m["id"] in by_id], []


def fake_event(*a, **k):
    calls["event"] += 1


def fake_task(*a, **k):
    calls["task"] += 1


gw._load_unread_scope = fake_load
gw._analyze_emails = fake_analyze
gw._create_event = fake_event
gw._create_task = fake_task

from backend.core.comun.events import bus  # noqa: E402


async def _noop_emit(*a, **k):
    return None


bus.emit = _noop_emit

r1 = asyncio.run(gw._email_actions_job(None, "api"))["reply"]
rows = board._load()
check(len(rows) == 2, f"first run creates 2 tasks, got {len(rows)}")
by = {t["sourceId"]: t for t in rows}
a1, a2 = by.get("e1", {}), by.get("e2", {})
check(a1.get("source") == "correo" and a1.get("type") == "pagar" and a1.get("urgency") == "critica",
      f"e1 pattern: {a1}")
check("Factura" in a1.get("description", "") and "a@x.com" in a1.get("description", ""),
      f"e1 notes kept: {a1.get('description')!r}")
check(a2.get("type") == "hacer" and a2.get("urgency") == "media" and a2.get("source") == "correo",
      f"e2 defaults/derived: {a2}")
check(calls == {"event": 1, "task": 1}, f"google calls first run: {calls}")
check("2 tarea(s) creadas" in r1, f"reply first run: {r1}")

r2 = asyncio.run(gw._email_actions_job(None, "api"))["reply"]
check(len(board._load()) == 2, "second run creates 0 new tasks")
check(calls == {"event": 1, "task": 1}, f"google NOT called again: {calls}")
check("ya tenían tarea" in r2 and "creadas" not in r2.replace("ninguna tarea nueva", ""),
      f"second reply reports skipped, not created: {r2}")
check("falló" not in r2 and "NO pude" not in r2 and "❌" not in r2, f"all-skipped is not an error: {r2}")
check(analyzed_ids[-1] == ["e3"], f"F3: only the not-yet-tasked mail is analyzed on rerun: {analyzed_ids[-1]}")
check("Alcance: analizados 1 de 3 sin leer" in r2 and "2 ya tenían tarea" in r2, f"F2 scope in all-skipped branch: {r2}")

print("== 4) partial: one new email among known ones ==")
emails.append({"id": "e4", "from": "d@x.com", "subject": "Nuevo", "body": "x"})
analysis.append({"i": 3, "accionable": True, "tarea": "Revisar D", "tipo": "revisar", "importancia": "baja"})
r3 = asyncio.run(gw._email_actions_job(None, "api"))["reply"]
check(len(board._load()) == 3, "only the new email creates a task")
check(calls["event"] + calls["task"] == 3, f"google called once more: {calls}")
check("1 tarea(s) creadas" in r3 and "ya tenían tarea" in r3, f"partial reply: {r3}")
check(analyzed_ids[-1] == ["e3", "e4"], f"F3: partial run analyzes only untasked mails: {analyzed_ids[-1]}")
check("Alcance: analizados 2 de 4 sin leer" in r3, f"F2 scope in created branch: {r3}")

print("== 5) T5d: grouped tasks (sourceIds, add_to_group) ==")
import json  # noqa: E402

fresh()
# migration: a stored task from before sourceIds existed loads with []
old = {"id": "old1", "title": "viejo", "state": "pendiente", "tag": "correo", "priority": "media",
       "source": "correo", "sourceId": "m9"}
board.BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
board.BOARD_FILE.write_text(json.dumps([old, {**old, "id": "old2", "sourceIds": "garbage"}]), encoding="utf-8")
loaded = board._load()
check(all(t["sourceIds"] == [] for t in loaded), f"old tasks migrate to sourceIds=[]: {loaded}")
check((board.find_by_source("correo", "m9") or {}).get("id") == "old1", "old tasks still match by sourceId")
check(board.add_task("x", source="correo", source_id="z")["sourceIds"] == [], "add_task default sourceIds []")

fresh()
G, T = "promociones", "Revisar promociones"
t, n = board.add_to_group("correo", G, [("p1", "• A — uno"), ("p2", "• B — dos"), ("", "• sin id"), ("p1", "dup")],
                          T, task_type="revisar", urgency="baja", tag="correo")
check(n == 2 and t["title"] == "Revisar promociones (2)" and t["sourceIds"] == ["p1", "p2"]
      and t["description"] == "• A — uno\n• B — dos" and t["sourceId"] == G and t["source"] == "correo",
      f"create: {n} {t}")
check(t["type"] == "revisar" and t["urgency"] == "baja" and t["priority"] == "baja" and t["due"] is None,
      "group fields revisar/baja, no due")
check(len(board._load()) == 1, "one stored group")
check((board.find_by_source("correo", "p2") or {}).get("id") == t["id"], "find_by_source matches a grouped id")
check(board.find_by_source("correo", "p3") is None, "find_by_source: id not in group misses")
check(board.find_by_source("manual", "p2") is None, "find_by_source: other source misses")
t2, n2 = board.add_to_group("correo", G, [("p2", "dup"), ("p3", "• C — tres")], T, task_type="revisar",
                            urgency="baja")
check(n2 == 1 and t2["id"] == t["id"] and t2["title"] == "Revisar promociones (3)"
      and t2["sourceIds"] == ["p1", "p2", "p3"] and t2["description"].endswith("• C — tres")
      and len(board._load()) == 1, f"append: {n2} {t2['title']} {t2['sourceIds']}")
_, n3 = board.add_to_group("correo", G, [("p1", "dup"), ("p3", "dup")], T)
check(n3 == 0 and board._load()[0]["title"] == "Revisar promociones (3)", "nothing new: no change")
_, n4 = board.add_to_group("correo", "otro", [], T)
check(n4 == 0 and len(board._load()) == 1, "empty entries never create a group")
# a closed group (completada) is not appended to; ids stay handled; a NEW group starts
board.move_task(t["id"], "completada")
check(board.find_by_source("correo", "p1") is not None, "done group still counts as handled")
t5, n5 = board.add_to_group("correo", G, [("p4", "• D — cuatro")], T, task_type="revisar", urgency="baja")
check(n5 == 1 and t5["id"] != t["id"] and t5["title"] == "Revisar promociones (1)"
      and len(board._load()) == 2 and [x for x in board._load() if x["id"] == t["id"]][0]["sourceIds"] == ["p1", "p2", "p3"],
      "completed group untouched, new group created")
for st in ("cancelada", "archivada"):
    tasks = board._load()
    for x in tasks:
        if x["id"] == t5["id"]:
            x["state"] = st
    board._save(tasks)
    t6, n6 = board.add_to_group("correo", G, [("p9", "• Z — nueve")], T)
    check(n6 == 1 and t6["id"] != t5["id"], f"{st} group is closed too")
    board.soft_delete([t6], reason="test")
# trashed group is ignored: not matched, not appended to
fresh()
t7, _ = board.add_to_group("correo", G, [("q1", "• Q — uno")], T)
board.soft_delete([t7], reason="test")
check(board.find_by_source("correo", "q1") is None, "trashed group: ids no longer count as handled")
t8, n8 = board.add_to_group("correo", G, [("q1", "• Q — uno")], T, task_type="revisar", urgency="baja")
check(n8 == 1 and t8["id"] != t7["id"] and t8["title"] == "Revisar promociones (1)", "trashed group ignored: new group")
# KPIs: the group is ONE open revisar/baja task
k = board.kpis()
check(k["open"] == 1 and k["by_type"]["revisar"] == 1 and k["by_urgency"]["baja"] == 1, f"kpis: {k}")

print()
print(f"test_inbox_tasks: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
