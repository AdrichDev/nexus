# -*- coding: utf-8 -*-
"""T5b - SCALE test of the inbox-to-tasks job: 50 unread synthetic mails, REAL code path.

Real: skills/google_workspace/skill.py (_email_actions_job and everything below it) and
backend.core.dominio.board (temp dir). Replaced seams: googleapiclient.discovery.build (the
read-only fake in fake_gmail.py), _get_creds (never reads credentials), llm.ask_llm (a
ground-truth stub that parses the digest the job sends) and bus.emit.
Ground truth: inbox_corpus.py. No network, no credentials, no real data.
Run:  PYTHONUTF8=1 python tests/unit/skills/google_workspace/test_inbox_scale.py

FINDINGS characterised here (production code is NOT changed, see the report):
  F1 the job only ever looks at the 30 newest unread mails and never marks mail read.
  F2 the reply of the "tasks created" branch says nothing about that cap.
  F3 already-handled mails are re-sent to the LLM on every run (dedupe happens after it).
  F4 a security mark forces urgente but not the board urgency/accionable chosen by the model.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="nexus_inbox_scale_")
os.environ["NEXUS_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["NEXUS_CONFIG_DIR"] = os.path.join(TMP, "config")

from backend.core.dominio import board  # noqa: E402
from fake_gmail import FakeGoogle, GMAIL_READS, mail  # noqa: E402
from inbox_corpus import ACTIONABLE, CORPUS, NEW5, TODAY  # noqa: E402

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


# ───────────────────────────── module under test + seams ─────────────────────────────
_SKILL = os.environ.get("NEXUS_SCALE_SKILL_PATH") or os.path.join(
    ROOT, "skills", "google_workspace", "skill.py")        # override = sabotage harness only
_spec = importlib.util.spec_from_file_location("gw_skill_scale_test", _SKILL)
gw = importlib.util.module_from_spec(_spec)
sys.modules["gw_skill_scale_test"] = gw
_spec.loader.exec_module(gw)
gw._get_creds = lambda: object()          # credentials are never read

CURRENT: dict = {"google": None}
_pkg = types.ModuleType("googleapiclient")
_disc = types.ModuleType("googleapiclient.discovery")
_disc.build = lambda api, version, **kw: CURRENT["google"].build(api, version, **kw)
_pkg.discovery = _disc
sys.modules["googleapiclient"] = _pkg
sys.modules["googleapiclient.discovery"] = _disc

from backend.core.infraestructura import llm  # noqa: E402
from backend.core.comun.events import bus  # noqa: E402


async def _noop_emit(*a, **k):
    return None


bus.emit = _noop_emit

CAP = 30                                   # _load_unread_bodies(30) in _email_actions_job


def set_lote(n):
    """Fixed batch size, default marks (independent of config/umbrales.json)."""
    gw._CORREOS = {"por_lote": n, "por_lote_por_proveedor": {},
                   "marcas_urgentes": list(gw._CORREOS_RESERVA["marcas_urgentes"])}


def set_real_lote():
    """The shipped defaults resolved by the REAL _por_lote() (provider table included)."""
    gw._CORREOS = {"por_lote": gw._CORREOS_RESERVA["por_lote"],
                   "por_lote_por_proveedor": dict(gw._CORREOS_RESERVA["por_lote_por_proveedor"]),
                   "marcas_urgentes": list(gw._CORREOS_RESERVA["marcas_urgentes"])}


# ───────────────────────────── ground-truth LLM stub ─────────────────────────────
def sender_name(frm):
    return re.sub(r"<.*?>", "", frm).strip()      # same stripping the job applies


_ENTRY = re.compile(r"^\[(\d+)\] De: (.*)\nAsunto: (.*)\nContenido: ", re.M)


def parse_digest(digest):
    """[(local_index, sender, subject, content)] from the digest the job sent."""
    ms = list(_ENTRY.finditer(digest))
    out = []
    for k, m in enumerate(ms):
        end = ms[k + 1].start() - 2 if k + 1 < len(ms) else len(digest)   # strip "\n\n"
        out.append((int(m.group(1)), m.group(2), m.group(3), digest[m.end():end]))
    return out


class StubLLM:
    """faults: {call_number: ("garbage",) | ("raise",) | ("omit", j) | ("oor",) | ("oor_shift", j)}"""

    def __init__(self, rows, faults=None, force_noaction=False, override=None):
        self.truth = {(r["subject"], sender_name(r["frm"])): r for r in rows}
        self.faults = faults or {}
        self.force_noaction = force_noaction
        self.override = override or {}          # subject -> dict of key overrides
        self.calls = 0
        self.batch_sizes: list[int] = []
        self.digests: list[str] = []
        self.unknown: list[tuple] = []
        self.seen: list[tuple] = []             # (call, local_i, row id)

    def item(self, j, row):
        d = {"i": j, "urgente": row["urgente"], "importancia": row["importancia"],
             "accionable": row["accionable"] and not self.force_noaction,
             "tarea": row["title"], "fecha": row["fecha"], "motivo": "stub",
             "tipo": row["tipo"], "urgencia": row["urgencia"]}
        d.update(self.override.get(row["subject"], {}))
        return d

    async def __call__(self, prompt, system=None, **kw):
        call = self.calls
        self.calls += 1
        entries = parse_digest(prompt)
        self.batch_sizes.append(len(entries))
        self.digests.append(prompt)
        fault = self.faults.get(call)
        if fault and fault[0] == "raise":
            raise RuntimeError("llm down")
        if fault and fault[0] == "garbage":
            return "Lo siento, no puedo darte un JSON con tantos correos.", "fake"
        items = []
        for j, frm, subject, _content in entries:
            row = self.truth.get((subject, frm))
            if row is None:
                self.unknown.append((subject, frm))
                continue
            self.seen.append((call, j, row["id"]))
            items.append(self.item(j, row))
        if fault and fault[0] == "omit":
            items = [x for x in items if x["i"] != fault[1]]
        elif fault and fault[0] == "oor":
            n = len(entries)
            items += [{**items[0], "i": 99}, {**items[0], "i": -1}, {**items[0], "i": n}]
        elif fault and fault[0] == "oor_shift":
            for x in items:
                if x["i"] == fault[1]:
                    x["i"] = 77
        return "```json\n" + json.dumps(items, ensure_ascii=False) + "\n```", "fake"


# ───────────────────────────── helpers ─────────────────────────────
def to_mail(r):
    return mail(r["id"], r["frm"], r["subject"], r["body"], html_only=r["html_only"],
                multipart=(r["kind"] in ("invoice_soon", "meeting")))


def make_google(rows):
    return FakeGoogle([to_mail(r) for r in rows])


def fresh():
    for f in (board.BOARD_FILE, board.TRASH_FILE):
        if f.exists():
            f.unlink()


def run_job(google, stub):
    CURRENT["google"] = google
    llm.ask_llm = stub
    return asyncio.run(gw._email_actions_job(None, "api"))["reply"]


def human_reads(google, ids):
    """A HUMAN reads these mails (the job never does)."""
    for i in ids:
        google.messages[i]["labelIds"].remove("UNREAD")


def tasks_by_source():
    return {t["sourceId"]: t for t in board._load()}


def verify_tasks(label, google, expected_rows, *, extra_ids=()):
    """Every board task maps to the right mail id with the right fields; Google inserts match."""
    got = tasks_by_source()
    exp = {r["id"]: r for r in expected_rows if r["accionable"]}
    check(set(got) == set(exp) | set(extra_ids),
          f"{label}: task ids {sorted(set(got) ^ (set(exp) | set(extra_ids)))} differ")
    bad = []
    for mid, r in exp.items():
        t = got.get(mid)
        if not t:
            continue
        if (t["title"], t["type"], t["urgency"], t["due"], t["source"]) != (
                r["title"], r["tipo"], r["urgency_expected"] if "urgency_expected" in r else r["urgencia"],
                r["fecha"] or None, "correo"):
            bad.append((mid, t["title"], t["type"], t["urgency"], t["due"]))
        if r["subject"] not in t["description"] or sender_name(r["frm"]) not in t["description"]:
            bad.append((mid, "notes", t["description"]))
    check(not bad, f"{label}: wrong task fields {bad[:3]}")
    n_dated = sum(1 for mid, t in got.items() if t["due"])
    n_undated = len(got) - n_dated
    check(len(google.events) == n_dated and len(google.tasks) == n_undated,
          f"{label}: events/tasks {len(google.events)}/{len(google.tasks)} vs {n_dated}/{n_undated}")
    check(sorted(e["summary"] for e in google.events) == sorted(t["title"] for t in got.values() if t["due"]),
          f"{label}: calendar summaries differ from dated board titles")
    check(sorted(t["title"] for t in google.tasks) == sorted(t["title"] for t in got.values() if not t["due"]),
          f"{label}: Tasks titles differ from undated board titles")
    check(all(set(e["start"]) == {"date"} for e in google.events), f"{label}: all-day events")
    check(not any("due" in t for t in google.tasks), f"{label}: undated Tasks carry no due")


def forbidden_guard(label, google):
    ops = {n for n in google.log if n.startswith("gmail.")}
    check(ops <= GMAIL_READS, f"{label}: gmail ops {ops - GMAIL_READS}")
    check(not [n for n in google.log if n.startswith("FORBIDDEN")], f"{label}: forbidden access")


def expected_kpis(rows, today=TODAY, days_soon=2):
    acts = [r for r in rows if r["accionable"]]
    k = {"open": len(acts), "done": 0,
         "by_type": {k: 0 for k in board.TYPES}, "by_urgency": {k: 0 for k in board.URGENCIES},
         "by_source": {"manual": 0, "correo": len(acts)}, "overdue": 0, "due_soon": 0, "no_due": 0}
    for r in acts:
        k["by_type"][r["tipo"]] += 1
        k["by_urgency"][r["urgencia"]] += 1
        if not r["fecha"]:
            k["no_due"] += 1
            continue
        d = __import__("datetime").date.fromisoformat(r["fecha"])
        if d < today:
            k["overdue"] += 1
        elif (d - today).days <= days_soon:
            k["due_soon"] += 1
    return k


VISIBLE = CORPUS[:CAP]
REST = CORPUS[CAP:]
T0 = time.perf_counter()

# ═════════════════ 1) healthy run, 50 unread, various batch sizes ═════════════════
print("== 1) healthy run: 50 unread, cap 30, batch sizes ==")
exp_visible_actionable = [r for r in VISIBLE if r["accionable"]]
check(len(exp_visible_actionable) == 13 and len(ACTIONABLE) == 22, "ground truth shape 13/22")
healthy = {}
for label, setter, expect_sizes in (
        ("por_lote=6", lambda: set_lote(6), [6, 6, 6, 6, 6]),
        ("por_lote=30", lambda: set_lote(30), [30]),
        ("por_lote=7", lambda: set_lote(7), [7, 7, 7, 7, 2]),
        ("real _por_lote()", set_real_lote, None)):
    setter()
    g = make_google(CORPUS)
    fresh()
    stub = StubLLM(CORPUS)
    t = time.perf_counter()
    reply = run_job(g, stub)
    dt_run = time.perf_counter() - t
    if expect_sizes is None:
        n = gw._por_lote()
        expect_sizes = [n] * (CAP // n) + ([CAP % n] if CAP % n else [])
        print(f"   real _por_lote() = {n}")
    check(stub.batch_sizes == expect_sizes, f"{label}: batch sizes {stub.batch_sizes} != {expect_sizes}")
    check(stub.unknown == [], f"{label}: stub saw unknown mails {stub.unknown}")
    analyzed = sum(stub.batch_sizes)
    check(analyzed == CAP, f"{label}: analyzed {analyzed}, expected {CAP} of 50")
    check(sorted(i for _c, _j, i in stub.seen) == [r["id"] for r in VISIBLE],
          f"{label}: LLM saw exactly the 30 newest")
    verify_tasks(label, g, VISIBLE)
    check(len(board._load()) == 13 and len(g.events) == 6 and len(g.tasks) == 7,
          f"{label}: created {len(board._load())} (events {len(g.events)}, tasks {len(g.tasks)})")
    check("13 tarea(s) creadas" in reply and "SIN clasificar" not in reply, f"{label}: reply: {reply[:120]}")
    # No task for any non-actionable mail, none for mails beyond the cap
    check(not set(tasks_by_source()) & {r["id"] for r in CORPUS if not r["accionable"]},
          f"{label}: no task for non-actionable mail")
    check(not set(tasks_by_source()) & {r["id"] for r in REST}, f"{label}: nothing from beyond the cap")
    forbidden_guard(label, g)
    healthy[label] = (dt_run, len(board._load()))
    print(f"   {label}: analyzed={analyzed} created={len(board._load())} batches={stub.batch_sizes} "
          f"time={dt_run:.3f}s")

# F1/F2: scope statement. Tasks created -> the reply never mentions 50 nor the cap (FINDING F2).
check("50" not in reply and "más recientes" not in reply,
      "F2 (finding): created-branch reply does not mention the 30-of-50 scope")
# ...whereas the no-action branch does disclose it.
set_lote(6)
g = make_google(CORPUS)
fresh()
reply_none = run_job(g, StubLLM(CORPUS, force_noaction=True))
check("tus 50 correos sin leer (los 30 más recientes)" in reply_none and board._load() == [],
      f"no-action branch discloses scope: {reply_none}")

# ═════════════════ 2) never marks read -> the other 20 are never reached ═════════════════
print("== 2) cap + never-read behaviour (FINDING F1) ==")
set_lote(6)
g = make_google(CORPUS)
fresh()
stub = StubLLM(CORPUS)
run_job(g, stub)
n_after_1 = len(board._load())
stub2 = StubLLM(CORPUS)
r2 = run_job(g, stub2)
check(len(board._load()) == n_after_1 == 13, "run 2 creates nothing new")
check(sorted(i for _c, _j, i in stub2.seen) == [r["id"] for r in VISIBLE],
      "F1: run 2 analyzes the SAME 30 mails again")
unreached = [r["id"] for r in REST]
check(not set(tasks_by_source()) & set(unreached), "F1: 20 mails never reached on any run")
check(sum(1 for r in REST if r["accionable"]) == 9, "F1: 9 actionable mails are silently never processed")
check(all("UNREAD" in m["labelIds"] for m in g.messages.values()), "F1: job never marks mail read")
check(stub2.calls == 5, f"F3 (finding): rerun still spends {stub2.calls} LLM calls on handled mails")
forbidden_guard("run2", g)

print("== 2b) 30 unread at a time: second pass processes new, dedupes old ==")
g = make_google(CORPUS)
fresh()
s1 = StubLLM(CORPUS)
run_job(g, s1)
check(len(board._load()) == 13, "pass 1 created 13")
human_reads(g, [r["id"] for r in CORPUS[:20]])                  # human reads the 20 oldest-of-window
unread_now = [m["id"] for m in g.messages.values() if "UNREAD" in m["labelIds"]]
check(len(unread_now) == 30, f"30 unread remain: {len(unread_now)}")
s2 = StubLLM(CORPUS)
r2 = run_job(g, s2)
exp_pass2 = [r["id"] for r in CORPUS[20:50]]
check(sorted(i for _c, _j, i in s2.seen) == exp_pass2, "pass 2 window = mails 20..49")
new_tasks = len(board._load()) - 13
dup_old = [r for r in CORPUS[20:30] if r["accionable"]]
new_rows = [r for r in CORPUS[30:] if r["accionable"]]
check(new_tasks == len(new_rows) == 9, f"pass 2 created {new_tasks} new tasks (expected 9)")
check(f"{len(dup_old)} correo(s) ya tenían tarea" in r2 and len(dup_old) == 5,
      f"pass 2 reply dedupes old (5): {r2[-120:]}")
verify_tasks("2 passes", g, CORPUS[:30] + CORPUS[30:])
check(len(board._load()) == 22 and len(g.events) == 8 and len(g.tasks) == 14,
      f"all 22 actionable of 50 handled: {len(board._load())} ev={len(g.events)} tk={len(g.tasks)}")
forbidden_guard("2 passes", g)

# ═════════════════ 3) KPIs ═════════════════
print("== 3) KPIs ==")
k = board.kpis(today=TODAY)
ek = expected_kpis(CORPUS)
check(k == ek, f"kpis {k} != ground truth {ek}")
check(k["open"] == 22 and k["by_source"] == {"manual": 0, "correo": 22}, "open 22, all from correo")
check(k["overdue"] == 1 and k["due_soon"] == 2 and k["no_due"] == 14, f"due split: {k}")
check(k["by_type"] == {"responder": 5, "hacer": 3, "pagar": 3, "asistir": 3, "revisar": 6, "esperar": 2},
      f"by_type {k['by_type']}")
check(k["by_urgency"] == ek["by_urgency"] and k["by_urgency"]["critica"] == 4, f"by_urgency {k['by_urgency']}")
k30 = None   # KPIs of the first-30 run
set_lote(6)
g = make_google(CORPUS)
fresh()
run_job(g, StubLLM(CORPUS))
k30 = board.kpis(today=TODAY)
check(k30 == expected_kpis(VISIBLE) and k30["open"] == 13 and k30["overdue"] == 1
      and k30["due_soon"] == 2, f"first-30 kpis {k30}")

# ═════════════════ 4) fault injection (cap window, por_lote 6 -> 5 batches) ═════════════════
print("== 4) fault injection ==")
set_lote(6)
ids = [r["id"] for r in VISIBLE]


def faulty(label, faults):
    g = make_google(CORPUS)
    fresh()
    stub = StubLLM(CORPUS, faults=faults)
    reply = run_job(g, stub)
    check(stub.calls == 5 and stub.unknown == [], f"{label}: all 5 batches attempted ({stub.calls})")
    forbidden_guard(label, g)
    return g, stub, reply


# garbage batch 1 = mails 6..11; the only mark inside is m08 [ALERTA]
g, stub, reply = faulty("garbage", {1: ("garbage",)})
got = tasks_by_source()
lost = {"m06", "m11"}                                   # actionable, unmarked, in the failed batch
exp_ids = {r["id"] for r in VISIBLE if r["accionable"]} - lost
check(set(got) == exp_ids, f"garbage: tasks {sorted(set(got) ^ exp_ids)}")
check("5 de 30 se han quedado SIN clasificar" in reply, f"garbage: unclassified count: {reply[-200:]}")
check("11 tarea(s) creadas" in reply, f"garbage: 11 created: {reply[:80]}")
net = got["m08"]
check(net["title"] == "Revisar correo de Monitor Infra: [ALERTA] disco al 98% en srv-db01"
      and net["urgency"] == "critica" and net["type"] == "hacer" and net["due"] is None,
      f"garbage: safety-net task for [ALERTA]: {net}")
check(not (set(got) & {"m07", "m09", "m10"}), "garbage: nothing invented for unclassified")
check(len(g.tasks) == 7 and len(g.events) == 4,
      f"garbage: inserts tasks={len(g.tasks)} events={len(g.events)}")
others = {i: got[i] for i in got if i != "m08"}
check(all(others[i]["title"] == next(r["title"] for r in CORPUS if r["id"] == i) for i in others),
      "garbage: other batches intact and correctly reindexed")

# omitted index: batch 2 = mails 12..17, local 3 = m15 (actionable)
g, stub, reply = faulty("omit", {2: ("omit", 3)})
got = tasks_by_source()
check(set(got) == {r["id"] for r in VISIBLE if r["accionable"]} - {"m15"}, "omit: m15 has no task")
check("1 de 30 se han quedado SIN clasificar" in reply and "12 tarea(s) creadas" in reply,
      f"omit: counted as unclassified: {reply[-170:]}")

# out-of-range extras (99, -1, len(batch)) are ignored; nothing else changes
g, stub, reply = faulty("oor", {3: ("oor",)})
got = tasks_by_source()
check(set(got) == {r["id"] for r in VISIBLE if r["accionable"]}, "oor: identical to healthy run")
check("SIN clasificar" not in reply and "13 tarea(s) creadas" in reply, f"oor: reply {reply[:80]}")
verify_tasks("oor", g, VISIBLE)
# a real answer carrying an out-of-range index = that mail is unclassified (batch 3, local 2 = m20)
g, stub, reply = faulty("oor_shift", {3: ("oor_shift", 2)})
got = tasks_by_source()
check("m20" not in got and len(got) == 12 and "1 de 30 se han quedado SIN clasificar" in reply,
      f"oor_shift: {len(got)} tasks; {reply[-150:]}")

# raising batch 4 = mails 24..29; the mark m26 [factura vencida] is rescued by the net
g, stub, reply = faulty("raise", {4: ("raise",)})
got = tasks_by_source()
exp_ids = {r["id"] for r in VISIBLE if r["accionable"]} - {"m25"}
check(set(got) == exp_ids, f"raise: tasks {sorted(set(got) ^ exp_ids)}")
check("5 de 30 se han quedado SIN clasificar" in reply, f"raise: {reply[-170:]}")
check(got["m26"]["title"].startswith("Revisar correo de Aguas Municipales: Factura vencida")
      and got["m26"]["urgency"] == "critica" and got["m26"]["due"] is None,
      f"raise: net task for m26: {got['m26']}")
check(got["m23"]["title"] == "Asistir a la demo con el cliente", "raise: previous batches survive")

# all four at once
g, stub, reply = faulty("combined", {1: ("garbage",), 2: ("omit", 3), 3: ("oor",), 4: ("raise",)})
got = tasks_by_source()
exp_ids = ({r["id"] for r in VISIBLE if r["accionable"]} - {"m06", "m11", "m15", "m25"})
check(set(got) == exp_ids and len(got) == 9, f"combined: {len(got)} tasks {sorted(set(got) ^ exp_ids)}")
check("11 de 30 se han quedado SIN clasificar" in reply, f"combined: {reply[-170:]}")

# every batch garbage: only marks produce tasks
g, stub, reply = faulty("all-garbage", {i: ("garbage",) for i in range(5)})
check(set(tasks_by_source()) == {"m08", "m21", "m26"}
      and "27 de 30 se han quedado SIN clasificar" in reply, f"all-garbage: {reply[-170:]}")

# F4: the mark forces `urgente` only. Model says not-actionable / calmer -> no task / calmer task.
alert = next(r for r in CORPUS if r["id"] == "m08")
fresh()
g = make_google([alert])
stub = StubLLM([alert], override={alert["subject"]: {"accionable": False}})
reply = run_job(g, stub)
check(board._load() == [] and "ninguno pide una acción concreta" in reply,
      "F4 (finding): [ALERTA] judged non-actionable by the model -> no task in this job")
fresh()
g = make_google([alert])
stub = StubLLM([alert], override={alert["subject"]: {"urgente": False, "urgencia": "baja"}})
run_job(g, stub)
t = board._load()[0]
print(f"   F4: marked [ALERTA] with model urgencia=baja -> board urgency={t['urgency']}")
check(t["urgency"] == "baja", f"F4 (finding): mark does not raise board urgency, got {t['urgency']}")

# ═════════════════ 5) rerun idempotence at scale ═════════════════
print("== 5) rerun idempotence ==")
set_lote(6)
g = make_google(CORPUS)
fresh()
run_job(g, StubLLM(CORPUS))
before = (len(board._load()), len(g.events), len(g.tasks))
ins_before = (len(g.inserts("calendar.events.insert")), len(g.inserts("tasks.tasks.insert")))
r2 = run_job(g, StubLLM(CORPUS))
after = (len(board._load()), len(g.events), len(g.tasks))
ins_after = (len(g.inserts("calendar.events.insert")), len(g.inserts("tasks.tasks.insert")))
check(before == after == (13, 6, 7) and ins_before == ins_after == (6, 7),
      f"rerun creates nothing: {before} -> {after}, inserts {ins_before} -> {ins_after}")
check("ninguna tarea nueva, 13 correo(s) ya tenían tarea" in r2, f"rerun reply: {r2[:100]}")
# 5 new actionable mails arrive (newest first) -> window = 5 new + 25 oldest-of-window
new_msgs = {r["id"]: to_mail(r) for r in NEW5}
g.messages = {**new_msgs, **g.messages}
stub3 = StubLLM(CORPUS + NEW5)
r3 = run_job(g, stub3)
check(len(board._load()) == 18 and len(g.events) == 8 and len(g.tasks) == 10,
      f"+5 new: board={len(board._load())} events={len(g.events)} tasks={len(g.tasks)}")
got = tasks_by_source()
check(all(r["id"] in got and got[r["id"]]["title"] == r["title"] for r in NEW5),
      "+5 new: exactly the new mails got their tasks")
check("5 tarea(s) creadas" in r3 and "11 correo(s) ya tenían tarea" in r3, f"+5 new reply: {r3[-110:]}")
check(sum(stub3.batch_sizes) == CAP and stub3.unknown == [], "+5 new: window still 30")
verify_tasks("+5 new", g, VISIBLE + NEW5)
forbidden_guard("rerun", g)

# ═════════════════ 6) robustness (full 50 via the two-pass flow) ═════════════════
print("== 6) robustness ==")
set_lote(6)
g = make_google(CORPUS)
fresh()
s1 = StubLLM(CORPUS)
run_job(g, s1)
human_reads(g, [r["id"] for r in CORPUS[:20]])
s2 = StubLLM(CORPUS)
run_job(g, s2)
digests = [d for s in (s1, s2) for d in s.digests]
contents = {}
for d in digests:
    for _j, frm, subject, content in parse_digest(d):
        contents[(subject, frm)] = content
check(len(contents) == 50, f"digest covered all 50 mails: {len(contents)}")
check(max(len(c) for c in contents.values()) <= 700, f"max digest content {max(len(c) for c in contents.values())}")
long_c = contents[("Revisión del contrato marco (documento largo)", "Asesoría")]
check(len(long_c) == 700 and long_c.startswith("Hola, adjunto el contrato marco"), f"long body cut to 700: {len(long_c)}")
check(contents[("Llamar a Marta cuando puedas", "Marta Gil")] == "", "empty body -> empty content")
html_c = contents[("Aprobación de vacaciones", "RRHH")]
check(html_c.startswith("Por favor responde") and "<" not in html_c, f"HTML-only falls back to snippet: {html_c!r}")
got = tasks_by_source()
mal = got["m36"]
check(mal["title"] == 'Revisar <script>alert(\'xss\')</script> {"a": [1, 2]} "comillas" {{7*7}}',
      f"malicious title verbatim: {mal['title']!r}")
check("<script>alert('xss')</script>" in mal["description"] and '{"i":0' in mal["description"],
      "malicious subject verbatim in notes")
check(any(t["title"] == mal["title"] for t in g.tasks), "malicious title sent to Tasks verbatim")
check(got["m34"]["title"] == "Responder sobre la propuesta 🚀 提案", "emoji/CJK title intact")
check(got["m42"]["title"] == "Llamar a Marta" and got["m42"]["due"] is None, "empty-body mail handled")
check(got["m38"]["title"] == "Revisar el contrato marco", "long-body mail handled")
check(got["m32"]["due"] == "2026-06-26", "implied-date mail dated by the model")
dups = {t["sourceId"]: t["title"] for t in got.values() if t["sourceId"] in ("m20", "m25")}
check(dups == {"m20": "Responder a Laura Gómez sobre el presupuesto",
               "m25": "Revisar presupuesto enviado por Pedro"},
      f"identical subjects keep separate ids/tasks: {dups}")
check(got["m26"]["due"] == "2026-06-05" and any(e["start"] == {"date": "2026-06-05"} for e in g.events),
      "overdue date still creates a (past) Calendar event")
check(not [x for x in got if x in ("m07",)], "newsletter citing 'alerta de seguridad' in its body is not an alert")
raw = json.loads(board.BOARD_FILE.read_text(encoding="utf-8"))
check(any(t["title"] == mal["title"] for t in raw), "title stored verbatim as text in board.json")

# ═════════════════ 7) Gmail only read (whole suite) ═════════════════
print("== 7) Gmail read-only ==")
forbidden_guard("full", g)
body_reads = [kw for n, kw in g.calls if n == "gmail.messages.get" and kw.get("format") == "full"]
check(len(body_reads) == 60, f"bodies read once per analysed mail per pass: {len(body_reads)}")
check(len(g.messages) == 50 and sum(1 for m in g.messages.values() if "UNREAD" in m["labelIds"]) == 30,
      "no mail deleted; only the human's reads changed labels")

total = time.perf_counter() - T0
print(f"\n   total suite time {total:.2f}s; healthy runs "
      + ", ".join(f"{k}={v[0]:.3f}s" for k, v in healthy.items()))
check(all(v[0] < 5 for v in healthy.values()) and total < 5, f"under 5 s (total {total:.2f}s)")
print(f"test_inbox_scale: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
