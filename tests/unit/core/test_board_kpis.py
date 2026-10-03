# -*- coding: utf-8 -*-
"""Task KPIs: board.kpis() counts, GET /api/board/kpis contract, and the Tareas view strip.

Uses a temporary data dir set BEFORE importing the board, so no real task is touched.
Run:  python tests/unit/core/test_board_kpis.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="nexus_kpis_test_")
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


def fresh():
    for f in (board.BOARD_FILE, board.TRASH_FILE):
        if f.exists():
            f.unlink()


def day(n):
    return (TODAY + dt.timedelta(days=n)).isoformat()


TODAY = dt.date(2026, 5, 10)
KEYS = {"open", "done", "by_type", "by_urgency", "by_source", "overdue", "due_soon", "no_due"}

print("== 1) empty board: full-key, all-zero dict ==")
fresh()
k = board.kpis(today=TODAY)
check(set(k) == KEYS, f"keys: {sorted(k)}")
check(k["open"] == 0 and k["done"] == 0 and k["overdue"] == 0 and k["due_soon"] == 0 and k["no_due"] == 0,
      f"scalars zero: {k}")
check(set(k["by_type"]) == set(board.TYPES) and not any(k["by_type"].values()), f"by_type: {k['by_type']}")
check(set(k["by_urgency"]) == set(board.URGENCIES) and not any(k["by_urgency"].values()),
      f"by_urgency: {k['by_urgency']}")
check(set(k["by_source"]) == set(board.SOURCES) and not any(k["by_source"].values()),
      f"by_source: {k['by_source']}")

print("== 2) mixed fixture ==")
fresh()
mk = board.add_task
mk("a", due=day(-3), task_type="responder", urgency="critica")          # overdue
mk("b", due=day(0), task_type="pagar", urgency="alta")                  # due today -> soon
mk("c", due=day(2), task_type="asistir", urgency="media")               # soon (edge)
mk("d", due=day(3), task_type="revisar", urgency="baja")                # beyond soon
mk("e", task_type="esperar", urgency="media", source="correo", source_id="m1")   # no due, email
mk("f", due="not-a-date", task_type="hacer", urgency="baja")            # invalid due -> no_due
done = mk("g", due=day(-9), task_type="hacer", urgency="alta")          # completed: excluded
canc = mk("h", due=day(-9), task_type="hacer", urgency="alta")          # cancelled: excluded
arch = mk("i", due=day(-9), task_type="hacer", urgency="alta")          # archived: excluded
gone = mk("j", due=day(-9), task_type="hacer", urgency="alta")          # trashed: excluded
board.move_task(done["id"], "completada")
board.move_task(canc["id"], "cancelada")
board.move_task(arch["id"], "archivada")
board.soft_delete([gone], reason="test")
board.move_task("b", "progreso")  # in progress stays open

k = board.kpis(today=TODAY)
check(k["open"] == 6, f"open: {k['open']}")
check(k["done"] == 1, f"done: {k['done']}")
check(k["overdue"] == 1, f"overdue: {k['overdue']}")
check(k["due_soon"] == 2, f"due_soon: {k['due_soon']}")
check(k["no_due"] == 2, f"no_due (none + invalid): {k['no_due']}")
check(k["by_type"] == {"responder": 1, "hacer": 1, "pagar": 1, "asistir": 1, "revisar": 1, "esperar": 1},
      f"by_type: {k['by_type']}")
check(k["by_urgency"] == {"critica": 1, "alta": 1, "media": 2, "baja": 2}, f"by_urgency: {k['by_urgency']}")
check(k["by_source"] == {"manual": 5, "correo": 1}, f"by_source: {k['by_source']}")
check(sum(k["by_type"].values()) == k["open"] and sum(k["by_urgency"].values()) == k["open"],
      "type/urgency sums equal open")

print("== 3) injected today and days_soon ==")
k2 = board.kpis(today=TODAY + dt.timedelta(days=4))
check(k2["overdue"] == 4 and k2["due_soon"] == 0, f"shifted today: overdue={k2['overdue']} soon={k2['due_soon']}")
k3 = board.kpis(days_soon=3, today=TODAY)
check(k3["due_soon"] == 3 and k3["overdue"] == 1, f"days_soon=3: {k3['due_soon']}")
late, soon = board.overdue()
check(isinstance(late, list) and isinstance(soon, list), "overdue() contract kept")

print("== 4) API contract ==")
app_src = open(os.path.join(ROOT, "backend", "app.py"), encoding="utf-8").read()
check('@app.get("/api/board/kpis")' in app_src, "app: GET /api/board/kpis declared")
check('@app.post("/api/board/kpis")' not in app_src, "app: kpis is read-only")
try:
    import backend.app as appmod
    fn = getattr(appmod, "api_board_kpis", None)
    check(fn is not None and inspect.iscoroutinefunction(fn), "app: api_board_kpis is async")
    if fn:
        res = asyncio.run(fn())
        check(set(res) == KEYS and res == board.kpis(), f"endpoint returns board.kpis(): {res}")
except Exception as e:  # app import needs the full dependency set
    check(False, f"app import/call failed: {e!r}")

print("== 5) frontend strip ==")
js = open(os.path.join(ROOT, "frontend", "js", "command.js"), encoding="utf-8").read()
check("/api/board/kpis" in js, "frontend: fetches /api/board/kpis")
check("async function refreshKpis" in js, "frontend: refreshKpis defined")
check('class="kpistrip' in js or "kpistrip" in js, "frontend: view renders the KPI strip")
check(js.count("refreshKpis(") >= 5, f"frontend: refreshKpis wired ({js.count('refreshKpis(')})")
check("esc(" in js[js.index("function kpiStrip"):js.index("function kpiStrip") + 2500]
      if "function kpiStrip" in js else False, "frontend: kpiStrip escapes text")

print(f"\n{_ok} ok, {len(_fail)} fail")
sys.exit(1 if _fail else 0)
