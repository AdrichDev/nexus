# -*- coding: utf-8 -*-
"""T5b - SCALE test of the inbox-to-tasks job: 50 unread synthetic mails, REAL code path.

Real: skills/google_workspace/skill.py (_email_actions_job and everything below it) and
backend.core.dominio.board (temp dir). Replaced seams: googleapiclient.discovery.build (the
read-only fake in fake_gmail.py), _get_creds (never reads credentials), llm.ask_llm (a
ground-truth stub that parses the digest the job sends) and bus.emit.
Ground truth: inbox_corpus.py. No network, no credentials, no real data.
Run:  PYTHONUTF8=1 python tests/unit/skills/google_workspace/test_inbox_scale.py

FINDINGS (found by this suite, now FIXED in skill.py; assertions pin the fixed behavior):
  F1 per-run cap `max_por_pasada` (default 100) instead of a hard 30; all unread up to the cap
     are analyzed in successive LLM batches within the run.
  F2 every reply branch states analyzed-vs-total (and already-tasked / cap) when not all were analyzed.
  F3 mails that already have a board task are skipped BEFORE their body is read or the LLM is called.
  F4 a configured urgent mark forces accionable=True and urgencia="critica" (not only `urgente`).
Known limitation (pinned below): mails analyzed but NOT actionable have no task, so they are
re-analyzed on every run and keep occupying the cap window (the job never marks mail read).
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
from inbox_corpus import (ACTIONABLE, CORPUS, NEW5, PROMO, PROMO_LATE, PROMO_MARKED,  # noqa: E402
                          PROMO_NEXT, TODAY)

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

CAP = 30                                   # small cap used by the fault-injection / cap scenarios


def set_lote(n, cap=100):
    """Fixed batch size and per-run cap, default marks (independent of config/umbrales.json)."""
    gw._CORREOS = {"por_lote": n, "por_lote_por_proveedor": {}, "max_por_pasada": cap,
                   "marcas_urgentes": list(gw._CORREOS_RESERVA["marcas_urgentes"])}


def set_real_lote():
    """The shipped defaults resolved by the REAL _por_lote() (provider table included)."""
    gw._CORREOS = {"por_lote": gw._CORREOS_RESERVA["por_lote"],
                   "por_lote_por_proveedor": dict(gw._CORREOS_RESERVA["por_lote_por_proveedor"]),
                   "max_por_pasada": gw._CORREOS_RESERVA.get("max_por_pasada", 100),
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

    def __init__(self, rows, faults=None, force_noaction=False, override=None, omit_promo=False):
        self.omit_promo = omit_promo            # model never emits the "promocional" key
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
        if row.get("promocional") and not self.omit_promo:
            d["promocional"] = True             # non-promo rows emit no key at all (old shape)
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


def body_read_ids(google):
    """Ids whose full body was read through the fake Gmail (call log)."""
    return [kw.get("id") for n, kw in google.calls
            if n == "gmail.messages.get" and kw.get("format") == "full"]


def run_urgent(google, stub):
    CURRENT["google"] = google
    llm.ask_llm = stub
    return asyncio.run(gw._email_urgent_job(None, "api"))["reply"]


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
NONACT_IDS = [r["id"] for r in CORPUS if not r["accionable"]]
T0 = time.perf_counter()

# ═════════════════ 1) healthy run, 50 unread, default cap 100, various batch sizes ═════════════════
print("== 1) healthy run: 50 unread, default cap 100, batch sizes ==")
check(len(ACTIONABLE) == 22 and len(VISIBLE) == 30, "ground truth shape 22 actionable of 50")
check(gw._CORREOS_RESERVA.get("max_por_pasada") == 100, "F1: default max_por_pasada is 100")
healthy = {}
for label, setter, expect_sizes in (
        ("por_lote=6", lambda: set_lote(6), [6] * 8 + [2]),
        ("por_lote=30", lambda: set_lote(30), [30, 20]),
        ("por_lote=7", lambda: set_lote(7), [7] * 7 + [1]),
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
        expect_sizes = [n] * (50 // n) + ([50 % n] if 50 % n else [])
        print(f"   real _por_lote() = {n}")
    check(stub.batch_sizes == expect_sizes, f"{label}: batch sizes {stub.batch_sizes} != {expect_sizes}")
    check(stub.unknown == [], f"{label}: stub saw unknown mails {stub.unknown}")
    analyzed = sum(stub.batch_sizes)
    check(analyzed == 50, f"{label}: analyzed {analyzed}, expected 50 of 50")
    check(sorted(i for _c, _j, i in stub.seen) == sorted(r["id"] for r in CORPUS),
          f"{label}: LLM saw all 50 mails")
    verify_tasks(label, g, CORPUS)
    check(len(board._load()) == 22 and len(g.events) == 8 and len(g.tasks) == 14,
          f"{label}: created {len(board._load())} (events {len(g.events)}, tasks {len(g.tasks)})")
    check(set(tasks_by_source()) == {r["id"] for r in ACTIONABLE},
          f"{label}: task ids match ground truth in ONE run")
    check("22 tarea(s) creadas" in reply and "SIN clasificar" not in reply, f"{label}: reply: {reply[:120]}")
    check("Alcance" not in reply, f"{label}: nothing left out -> no scope caveat: {reply[-120:]}")
    check(not set(tasks_by_source()) & set(NONACT_IDS), f"{label}: no task for non-actionable mail")
    forbidden_guard(label, g)
    healthy[label] = (dt_run, len(board._load()))
    print(f"   {label}: analyzed={analyzed} created={len(board._load())} batches={stub.batch_sizes} "
          f"time={dt_run:.3f}s")

# F2: scope statement in EVERY branch of the actions job when not all unread were analyzed.
print("== 1b) F2 scope wording, every branch (cap 30 of 50) ==")
set_lote(6, 30)
g = make_google(CORPUS)
fresh()
reply_c = run_job(g, StubLLM(CORPUS))
check("13 tarea(s) creadas" in reply_c and "Alcance: analizados 30 de 50 sin leer" in reply_c
      and "20 sin mirar por el tope de 30 por pasada" in reply_c,
      f"F2 created branch states scope + cap: {reply_c[-220:]}")
# (marked mails are excluded here: since F4 a mark forces a task even if the model says "no action")
unmarked = [r for r in CORPUS if not gw._marca_urgente({"from": r["frm"], "subject": r["subject"]})]
check(len(unmarked) == 46, f"4 marked mails in the corpus: {len(unmarked)}")
g = make_google(unmarked)
fresh()
reply_none = run_job(g, StubLLM(CORPUS, force_noaction=True))
check(board._load() == [] and "ninguno pide una acción concreta" in reply_none
      and "Alcance: analizados 30 de 46 sin leer" in reply_none
      and "16 sin mirar por el tope de 30 por pasada" in reply_none,
      f"F2 nothing-actionable branch states scope + cap: {reply_none}")
# skipped branch: 30 unread, 13 already tasked -> 17 analyzed (non-actionable)
g1 = make_google(VISIBLE)
fresh()
run_job(g1, StubLLM(CORPUS))
r_skip = run_job(g1, StubLLM(CORPUS))
check("ninguna tarea nueva, 13 correo(s) ya tenían tarea" in r_skip
      and "analizados 17 de 30 sin leer" in r_skip and "13 ya tenían tarea" in r_skip,
      f"F2 skipped branch states analyzed/total/tasked: {r_skip}")
# every unread already tasked -> nothing analyzed, still honest (not 'could not analyze NONE')
fresh()
g2 = make_google([r for r in CORPUS if r["accionable"]])
run_job(g2, StubLLM(CORPUS))
st = StubLLM(CORPUS)
r_all = run_job(g2, st)
check(st.calls == 0 and "ninguna tarea nueva, 22 correo(s) ya tenían tarea" in r_all
      and "analizados 0 de 22 sin leer" in r_all and "No he podido analizar" not in r_all,
      f"F2/F3 all-skipped branch: calls={st.calls} {r_all}")
# urgent job: scope wording + cap only
set_lote(6, 30)
g = make_google(CORPUS)
ur = run_urgent(g, StubLLM(CORPUS))
check("de tus 50 sin leer" in ur and "Alcance: analizados 30 de 50 sin leer" in ur
      and "20 sin mirar por el tope de 30 por pasada" in ur, f"urgent (urgent branch) scope: {ur[-200:]}")
ur2 = run_urgent(g, StubLLM(CORPUS, override={r["subject"]: {"urgente": False} for r in CORPUS}))
check("Alcance: analizados 30 de 50 sin leer" in ur2 and "20 sin mirar" in ur2,
      f"urgent (nothing urgent) scope: {ur2[-200:]}")
set_lote(6)
g = make_google(CORPUS)
ur4 = run_urgent(g, StubLLM(CORPUS))
check("Alcance" not in ur4 and "de tus 50 sin leer" in ur4, f"urgent: all 50 analyzed at default cap: {ur4[-150:]}")

# ═════════════════ 2) the cap, successive runs, never-read behaviour ═════════════════
print("== 2) per-run cap (F1) + skip already-tasked (F3) ==")
set_lote(6, 20)
g = make_google(CORPUS)
fresh()
stub = StubLLM(CORPUS)
r1 = run_job(g, stub)
first20 = [r["id"] for r in CORPUS[:20]]
check(sorted(i for _c, _j, i in stub.seen) == sorted(first20), "cap 20: run 1 analyzes the 20 newest only")
exp1 = {r["id"] for r in CORPUS[:20] if r["accionable"]}
n1 = len(board._load())
check(set(tasks_by_source()) == exp1 and n1 == len(exp1), f"cap 20: run 1 tasks {sorted(tasks_by_source())}")
check("Alcance: analizados 20 de 50 sin leer" in r1 and "30 sin mirar por el tope de 20 por pasada" in r1,
      f"cap 20: honest reply about the rest: {r1[-200:]}")
check(sorted(set(body_read_ids(g))) == sorted(first20), "cap 20: only the 20 window bodies were read")
# run 2: tasked ones are skipped, but NON-ACTIONABLE ones keep occupying the window (pinned limitation)
reads_before = len(body_read_ids(g))
stub2 = StubLLM(CORPUS)
r2 = run_job(g, stub2)
nonact20 = [r["id"] for r in CORPUS[:20] if not r["accionable"]]
seen2 = sorted(i for _c, _j, i in stub2.seen)
check(seen2 == sorted(nonact20), f"limitation: run 2 re-analyzes only the non-actionable of the window: {seen2}")
check(not (set(seen2) & exp1), "F3: run 2 sends NO already-tasked mail to the LLM")
check(len(body_read_ids(g)) - reads_before == len(nonact20),
      "F3: run 2 read bodies only for the not-yet-tasked mails")
check(len(board._load()) == n1 and set(tasks_by_source()) == exp1,
      "limitation: window never advances past non-actionable mails -> mails 21..50 never reached")
check("ninguna tarea nueva" in r2 and f"{len(exp1)} correo(s) ya tenían tarea" in r2
      and "Alcance: analizados" in r2 and "30 sin mirar por el tope de 20 por pasada" in r2,
      f"run 2 reply honest: {r2[-260:]}")
check(all("UNREAD" in m["labelIds"] for m in g.messages.values()), "job never marks mail read")
forbidden_guard("cap20", g)

print("== 2b) the window moves on once the first ones are handled ==")
human_reads(g, first20)                      # the human reads the 20 newest -> next run reaches the rest
stub3 = StubLLM(CORPUS)
r3 = run_job(g, stub3)
check(sorted(i for _c, _j, i in stub3.seen) == sorted(r["id"] for r in CORPUS[20:40] if True),
      "after the human read the first 20: next 20 analyzed")
check(set(tasks_by_source()) == {r["id"] for r in CORPUS[:40] if r["accionable"]},
      "tasks cover mails 0..39 after run 3")
check("Alcance: analizados 20 de 30 sin leer" in r3 and "10 sin mirar" in r3, f"run 3 scope: {r3[-200:]}")
set_lote(6)                                  # default cap: everything remaining at once
run_job(g, StubLLM(CORPUS))
check(set(tasks_by_source()) == {r["id"] for r in CORPUS if r["accionable"]} and len(board._load()) == 22,
      "default cap: remaining mails get their tasks; 22 total, no duplicates")
check(len(g.events) == 8 and len(g.tasks) == 14, f"no duplicate Google items: {len(g.events)}/{len(g.tasks)}")
forbidden_guard("2b", g)

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
k30 = None   # KPIs of the first-30 run (cap 30)
set_lote(6, 30)
g = make_google(CORPUS)
fresh()
run_job(g, StubLLM(CORPUS))
k30 = board.kpis(today=TODAY)
check(k30 == expected_kpis(VISIBLE) and k30["open"] == 13 and k30["overdue"] == 1
      and k30["due_soon"] == 2, f"first-30 kpis {k30}")

# ═════════════════ 4) fault injection (cap window, por_lote 6 -> 5 batches) ═════════════════
print("== 4) fault injection (cap 30 window, por_lote 6 -> 5 batches) ==")
set_lote(6, 30)
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

# F4: a configured mark forces urgente AND accionable AND urgencia critica over the model.
alert = next(r for r in CORPUS if r["id"] == "m08")
fresh()
g = make_google([alert])
stub = StubLLM([alert], override={alert["subject"]: {"accionable": False}})
reply = run_job(g, stub)
t = board._load()
check(len(t) == 1 and t[0]["urgency"] == "critica" and t[0]["sourceId"] == "m08",
      f"F4: [ALERTA] judged non-actionable by the model still gets a critica task: {t}")
check("1 tarea(s) creadas" in reply, f"F4: reply: {reply[:90]}")
fresh()
g = make_google([alert])
stub = StubLLM([alert], override={alert["subject"]: {"urgente": False, "urgencia": "baja"}})
run_job(g, stub)
t = (board._load() or [{}])[0]
check(t.get("urgency") == "critica", f"F4: urgencia baja overridden by the mark, got {t['urgency']}")
check(t.get("type") == alert["tipo"], f"F4: model's valid tipo kept: {t['type']}")
fresh()
g = make_google([alert])
stub = StubLLM([alert], override={alert["subject"]: {"accionable": False, "urgencia": "baja", "tipo": "???"}})
run_job(g, stub)
t = (board._load() or [{}])[0]
check(t.get("type") == "revisar" and t.get("urgency") == "critica", f"F4: invalid tipo -> revisar: {t.get('type')}/{t.get('urgency')}")
# no mark, model says not actionable -> still no task (mark logic does not leak)
calm = next(r for r in CORPUS if not r["accionable"] and not gw._marca_urgente({"from": r["frm"], "subject": r["subject"]}))
fresh()
g = make_google([calm])
run_job(g, StubLLM([calm]))
check(board._load() == [], "F4: unmarked non-actionable mail still gets no task")

# ═════════════════ 5) rerun idempotence at scale ═════════════════
print("== 5) rerun idempotence at scale (F3) ==")
set_lote(6)
g = make_google(CORPUS)
fresh()
run_job(g, StubLLM(CORPUS))
before = (len(board._load()), len(g.events), len(g.tasks))
ins_before = (len(g.inserts("calendar.events.insert")), len(g.inserts("tasks.tasks.insert")))
reads_before = len(body_read_ids(g))
stub_r = StubLLM(CORPUS)
r2 = run_job(g, stub_r)
after = (len(board._load()), len(g.events), len(g.tasks))
ins_after = (len(g.inserts("calendar.events.insert")), len(g.inserts("tasks.tasks.insert")))
check(before == after == (22, 8, 14) and ins_before == ins_after == (8, 14),
      f"rerun creates nothing: {before} -> {after}, inserts {ins_before} -> {ins_after}")
check("ninguna tarea nueva, 22 correo(s) ya tenían tarea" in r2
      and "Alcance: analizados 28 de 50 sin leer" in r2 and "22 ya tenían tarea" in r2,
      f"rerun reply: {r2[-260:]}")
tasked = {r["id"] for r in ACTIONABLE}
seen_r = sorted(i for _c, _j, i in stub_r.seen)
check(seen_r == sorted(NONACT_IDS), "F3: rerun digest holds ONLY the not-yet-tasked (28 non-actionable) mails")
check(not (set(seen_r) & tasked), "F3: no already-tasked mail was re-sent to the LLM")
check(sum(stub_r.batch_sizes) == 28, f"F3: rerun LLM batches cover 28 mails: {stub_r.batch_sizes}")
new_reads = body_read_ids(g)[reads_before:]
check(sorted(new_reads) == sorted(NONACT_IDS) and not (set(new_reads) & tasked),
      "F3: bodies of already-tasked mails were NOT read again")
# 5 new actionable mails arrive (newest first): only they + the 28 non-actionable are analyzed
new_msgs = {r["id"]: to_mail(r) for r in NEW5}
g.messages = {**new_msgs, **g.messages}
stub3 = StubLLM(CORPUS + NEW5)
r3 = run_job(g, stub3)
check(len(board._load()) == 27 and len(g.events) == 10 and len(g.tasks) == 17,
      f"+5 new: board={len(board._load())} events={len(g.events)} tasks={len(g.tasks)}")
got = tasks_by_source()
check(all(r["id"] in got and got[r["id"]]["title"] == r["title"] for r in NEW5),
      "+5 new: exactly the new mails got their tasks")
check("5 tarea(s) creadas" in r3 and "22 correo(s) ya tenían tarea" in r3
      and "Alcance: analizados 33 de 55 sin leer" in r3, f"+5 new reply: {r3[-230:]}")
check(sum(stub3.batch_sizes) == 33 and stub3.unknown == [], f"+5 new: 33 analyzed {stub3.batch_sizes}")
verify_tasks("+5 new", g, CORPUS + NEW5)
forbidden_guard("rerun", g)

# ═════════════════ 6) robustness (full 50 in ONE run) ═════════════════
print("== 6) robustness ==")
set_lote(6)
g = make_google(CORPUS)
fresh()
s1 = StubLLM(CORPUS)
run_job(g, s1)
digests = list(s1.digests)
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

# ═════════════════ 6b) max_por_pasada config validation (temp config dir only) ═════════════════
print("== 6b) max_por_pasada validation ==")
import pathlib  # noqa: E402
_cfg = pathlib.Path(TMP) / "cfg_cap"
_cfg.mkdir(exist_ok=True)
_old_cfg = gw.CONFIG_DIR
gw.CONFIG_DIR = _cfg
try:
    for val, want in ((250, 250), (1, 1), (500, 500), (0, 100), (501, 100), ("20", 100),
                      (True, 100), (2.5, 100), (None, 100)):
        (_cfg / "umbrales.json").write_text(json.dumps({"correos": {"max_por_pasada": val}}), encoding="utf-8")
        got_cap = gw._carga_correos()["max_por_pasada"]
        check(got_cap == want, f"max_por_pasada {val!r} -> {got_cap}, want {want}")
    (_cfg / "umbrales.json").write_text("{broken", encoding="utf-8")
    check(gw._carga_correos()["max_por_pasada"] == 100, "broken JSON -> default cap 100")
finally:
    gw.CONFIG_DIR = _old_cfg

# ═════════════════ 7) Gmail only read (whole suite) ═════════════════
print("== 7) Gmail read-only ==")
forbidden_guard("full", g)
body_reads = [kw for n, kw in g.calls if n == "gmail.messages.get" and kw.get("format") == "full"]
check(len(body_reads) == 50, f"bodies read once per analysed mail: {len(body_reads)}")
check(len(g.messages) == 50 and sum(1 for m in g.messages.values() if "UNREAD" in m["labelIds"]) == 50,
      "no mail deleted; job never marked read")

T_BASE = time.perf_counter() - T0          # the 5 s budget covers the pre-T5d scenarios
# ═════════════════ 8) T5d: promotional mails are grouped, never one task each ═════════════════
print("== 8) T5d promo grouping ==")
set_lote(6)
PROMO_IDS = [r["id"] for r in PROMO]
ALLP = CORPUS + PROMO + PROMO_LATE + PROMO_NEXT + [PROMO_MARKED]


def groups():
    return [t for t in board._load() if t["sourceId"] == "promociones"]


g = make_google(PROMO + CORPUS)
fresh()
s8 = StubLLM(ALLP)
r8 = run_job(g, s8)
grp = groups()
check(len(grp) == 1 and len(board._load()) == 23, f"T5d: 22 individual + ONE group: {len(board._load())}")
check(not (set(tasks_by_source()) & set(PROMO_IDS)), "T5d: no promo mail has its own task")
t8 = grp[0]
check(t8["title"] == "Revisar promociones (3)" and t8["type"] == "revisar" and t8["urgency"] == "baja"
      and t8["due"] is None and t8["source"] == "correo" and t8["state"] == "pendiente",
      f"T5d: group fields {t8['title']} {t8['type']} {t8['urgency']} {t8['due']}")
check(sorted(t8["sourceIds"]) == sorted(PROMO_IDS), f"T5d: sourceIds {t8['sourceIds']}")
check(all(f"• {sender_name(r['frm'])} — {r['subject']}" in t8["description"].split("\n") for r in PROMO)
      and len(t8["description"].split("\n")) == 3, f"T5d: description {t8['description']!r}")
check(len(g.events) == 8 and len(g.tasks) == 14 and not any("promo" in t["title"].lower() for t in g.tasks),
      f"T5d: NOTHING inserted in Google for the group: {len(g.events)}/{len(g.tasks)}")
check("22 tarea(s) creadas" in r8 and "3 promoción(es) agrupadas en UNA sola tarea" in r8
      and "Revisar promociones (3)" in r8 and "no las he convertido en tareas individuales" in r8
      and "ni las he creado en Google" in r8, f"T5d reply: {r8[-420:]}")
only_indiv = r8.split("tarea(s) creadas:")[1].split("📣")[0]
check(not any(r["subject"] in only_indiv or "directo" in only_indiv for r in PROMO),
      "T5d: reply lists no individual line for promos")
k8 = board.kpis(today=TODAY)
e8 = expected_kpis(CORPUS)
e8["open"] += 1
e8["by_type"]["revisar"] += 1
e8["by_urgency"]["baja"] += 1
e8["by_source"]["correo"] += 1
e8["no_due"] += 1
check(k8 == e8, f"T5d: KPIs count the group as ONE open revisar/baja task: {k8}")
forbidden_guard("T5d healthy", g)

# rerun: skipped BEFORE the body read, no LLM call for grouped mails, nothing new
reads8 = len(body_read_ids(g))
ins8 = (len(g.inserts("calendar.events.insert")), len(g.inserts("tasks.tasks.insert")))
s8b = StubLLM(ALLP)
r8b = run_job(g, s8b)
seen8b = {i for _c, _j, i in s8b.seen}
check(not (seen8b & set(PROMO_IDS)), f"T5d rerun: grouped mails never reach the LLM: {seen8b & set(PROMO_IDS)}")
check(not (set(body_read_ids(g)[reads8:]) & set(PROMO_IDS)), "T5d rerun: grouped bodies not re-read")
check(len(board._load()) == 23 and groups()[0]["title"] == "Revisar promociones (3)"
      and groups()[0]["sourceIds"] == t8["sourceIds"] and groups()[0]["description"] == t8["description"],
      "T5d rerun: group untouched")
check(ins8 == (len(g.inserts("calendar.events.insert")), len(g.inserts("tasks.tasks.insert"))),
      "T5d rerun: no Google inserts")
check("ya tenían tarea" in r8b and "25 ya tenían tarea" in r8b, f"T5d rerun reply: {r8b[-260:]}")

# new promos in a later run append to the SAME open group
g.messages = {**{r["id"]: to_mail(r) for r in PROMO_LATE}, **g.messages}
s8c = StubLLM(ALLP)
r8c = run_job(g, s8c)
grp = groups()
check(len(grp) == 1 and grp[0]["title"] == "Revisar promociones (5)"
      and sorted(grp[0]["sourceIds"]) == sorted(PROMO_IDS + [r["id"] for r in PROMO_LATE]),
      f"T5d append: {[(t['title'], t['sourceIds']) for t in grp]}")
check(len(grp[0]["description"].split("\n")) == 5 and grp[0]["description"].startswith(t8["description"])
      and "Masterclass gratuita este jueves" in grp[0]["description"],
      f"T5d append: description grows: {grp[0]['description']!r}")
check(len(board._load()) == 23 and {i for _c, _j, i in s8c.seen} & set(PROMO_IDS) == set(),
      "T5d append: no extra task; old grouped mails not re-analyzed")
check("2 promoción(es) agrupadas" in r8c and "(5 en total)" in r8c and "ninguna tarea individual nueva" in r8c,
      f"T5d append reply: {r8c[:260]}")
check(len(g.events) == 8 and len(g.tasks) == 14, "T5d append: still nothing in Google")

# group completed -> a later promo starts a NEW group; old ids are not re-added
old_group = groups()[0]
board.move_task(old_group["id"], "completada")
g.messages = {**{r["id"]: to_mail(r) for r in PROMO_NEXT}, **g.messages}
r8d = run_job(g, StubLLM(ALLP))
grp = groups()
open_g = [t for t in grp if t["state"] != "completada"]
check(len(grp) == 2 and len(open_g) == 1 and open_g[0]["title"] == "Revisar promociones (1)"
      and open_g[0]["sourceIds"] == ["m230"], f"T5d completed: new group {[(t['title'], t['state']) for t in grp]}")
done_g = [t for t in grp if t["state"] == "completada"][0]
check(done_g["title"] == "Revisar promociones (5)" and len(done_g["sourceIds"]) == 5,
      "T5d completed: closed group is not touched")
check("1 promoción(es) agrupadas" in r8d, f"T5d completed reply: {r8d[:200]}")
# group trashed -> promos start a new group again (trashed does not count as handled)
board.soft_delete([open_g[0]], reason="test")
run_job(g, StubLLM(ALLP))
grp = groups()
check(len(grp) == 2 and sorted(t["state"] for t in grp) == ["completada", "pendiente"]
      and [t for t in grp if t["state"] == "pendiente"][0]["sourceIds"] == ["m230"],
      f"T5d trashed: a new group replaces the trashed one: {[(t['title'], t['state']) for t in grp]}")
forbidden_guard("T5d lifecycle", g)

# urgent mark wins over promo: the marked promo-looking mail is an individual critica task
fresh()
g = make_google([PROMO_MARKED] + PROMO)
r8f = run_job(g, StubLLM(ALLP))
tm = tasks_by_source()
g8 = (groups() or [{"sourceIds": [], "title": ""}])[0]
check(tm.get("m220", {}).get("urgency") == "critica" and tm["m220"]["title"] == PROMO_MARKED["title"]
      and "m220" not in g8["sourceIds"] and g8["title"] == "Revisar promociones (3)",
      f"T5d mark wins: {tm.get('m220')} group={g8['sourceIds']}")
check(len(g.tasks) == 1 and "1 tarea(s) creadas" in r8f,
      f"T5d mark wins: Google gets only the marked mail: {len(g.tasks)}")
# even when the model returns nothing for it and only the mark net rescues it
fresh()
g = make_google([PROMO_MARKED])
run_job(g, StubLLM([PROMO_MARKED], faults={0: ("garbage",)}))
check([t["sourceId"] for t in board._load()] == ["m220"] and groups() == [], "T5d mark net: individual, no group")

# the model omits the key -> old behavior (one task per mail, nothing grouped)
fresh()
g = make_google(PROMO)
r8g = run_job(g, StubLLM(ALLP, omit_promo=True))
check(groups() == [] and set(tasks_by_source()) == set(PROMO_IDS) and len(g.tasks) + len(g.events) == 3
      and "promoci" not in r8g, f"T5d no key => old behavior: {sorted(tasks_by_source())}")
# a promo the model calls NOT actionable is neither a task nor grouped (it stays re-analyzable)
fresh()
g = make_google(PROMO)
run_job(g, StubLLM(ALLP, override={r["subject"]: {"accionable": False} for r in PROMO}))
check(board._load() == [], "T5d: non-actionable promo makes no task and no group")
check(gw._es_promocional({"promocional": "true"}) and gw._es_promocional({"promocional": True})
      and not gw._es_promocional({}) and not gw._es_promocional({"promocional": "false"})
      and not gw._es_promocional({"promocional": 1}), "T5d: _es_promocional contract")
PROMPTS: list[str] = []


async def _capture(prompt, system=None, **kw):
    PROMPTS.append(system or "")
    return "[]", "fake"


llm.ask_llm = _capture
asyncio.run(gw._analyze_batch([{"from": "a", "subject": "b", "body": "c"}]))
check('"promocional": true|false' in PROMPTS[0] and "NO es promocional" in PROMPTS[0],
      "T5d: prompt carries the promocional key and its definition")

total = T_BASE
print(f"\n   total suite time {total:.2f}s; healthy runs "
      + ", ".join(f"{k}={v[0]:.3f}s" for k, v in healthy.items()))
check(all(v[0] < 5 for v in healthy.values()) and total < 5, f"under 5 s (total {total:.2f}s)")
print(f"test_inbox_scale: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
