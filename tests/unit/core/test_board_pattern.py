# -*- coding: utf-8 -*-
"""Task pattern: closed `type` and `urgency` vocabularies, legacy `priority` compatibility,
source fields, and migration of tasks saved before the pattern existed.

Uses a temporary data dir set BEFORE importing the board, so no real task is touched.
Run:  python tests/unit/core/test_board_pattern.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="nexus_pattern_test_")
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


print("== 1) vocabularies are closed and exported ==")
check(board.TYPES == ("responder", "hacer", "pagar", "asistir", "revisar", "esperar"),
      f"TYPES: {getattr(board, 'TYPES', None)}")
check(board.URGENCIES == ("critica", "alta", "media", "baja"),
      f"URGENCIES: {getattr(board, 'URGENCIES', None)}")

print("== 2) defaults ==")
fresh()
t = board.add_task("llamar al cliente")
check(t.get("type") == "hacer", f"default type: {t.get('type')}")
check(t.get("urgency") == "media", f"default urgency: {t.get('urgency')}")
check(t.get("priority") == "media", f"default priority: {t.get('priority')}")
check(t.get("source") == "manual" and t.get("sourceId") == "", f"source defaults: {t.get('source')!r} {t.get('sourceId')!r}")

print("== 3) explicit values are normalized (case, accents, synonyms) ==")
t = board.add_task("pagar factura luz", task_type="Pagar", urgency="Crítica")
check(t["type"] == "pagar" and t["urgency"] == "critica", f"{t['type']} {t['urgency']}")
t = board.add_task("contestar a ana", task_type="RESPONDER", urgency="urgente")
check(t["type"] == "responder" and t["urgency"] == "critica", f"urgente → critica: {t['urgency']}")
t = board.add_task("ir a la reunión", task_type="asistir", urgency="normal")
check(t["urgency"] == "media", f"normal → media: {t['urgency']}")

print("== 4) invalid values never raise and fall back to defaults ==")
t = board.add_task("x", task_type="inventado", urgency="ultra")
check(t["type"] == "hacer" and t["urgency"] == "media", f"{t['type']} {t['urgency']}")
t = board.add_task("y", task_type=None, urgency=None)  # type: ignore[arg-type]
check(t["type"] == "hacer" and t["urgency"] == "media", "None falls back")

print("== 5) legacy `priority` stays coherent with `urgency` ==")
for urg, prio in (("critica", "alta"), ("alta", "alta"), ("media", "media"), ("baja", "baja")):
    t = board.add_task("p " + urg, urgency=urg)
    check(t["priority"] == prio, f"urgency {urg} → priority {t['priority']} (want {prio})")
t = board.add_task("legacy caller", priority="alta")
check(t["urgency"] == "alta" and t["priority"] == "alta", f"priority-only caller: {t['urgency']}/{t['priority']}")
t = board.add_task("legacy baja", priority="baja")
check(t["urgency"] == "baja", f"priority baja → urgency {t['urgency']}")
t = board.add_task("both", priority="baja", urgency="critica")
check(t["urgency"] == "critica" and t["priority"] == "alta", "urgency wins over priority")

print("== 6) source fields ==")
t = board.add_task("de correo", source="correo", source_id="msg-123")
check(t["source"] == "correo" and t["sourceId"] == "msg-123", f"{t['source']} {t['sourceId']}")
t = board.add_task("fuente rara", source="otra")
check(t["source"] == "manual", f"unknown source → manual: {t['source']}")

print("== 7) tasks saved before the pattern are migrated on load ==")
fresh()
legacy = [
    {"id": "aaaa1111", "title": "vieja alta", "state": "pendiente", "due": None, "priority": "alta",
     "tag": "", "time": None, "kind": "accion", "created": "2026-01-01"},
    {"id": "bbbb2222", "title": "vieja cita", "state": "pendiente", "due": "2026-02-01", "priority": "media",
     "tag": "", "time": "10:00", "kind": "evento", "created": "2026-01-01"},
    {"id": "cccc3333", "title": "vieja baja", "state": "completada", "due": None, "priority": "baja",
     "tag": "correo", "time": None, "kind": "accion", "created": "2026-01-01"},
]
board.BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
board.BOARD_FILE.write_text(json.dumps(legacy), encoding="utf-8")
b = {t["id"]: t for s in board.board().values() for t in s}
check(b["aaaa1111"]["urgency"] == "alta" and b["aaaa1111"]["type"] == "hacer", f"{b['aaaa1111']}")
check(b["bbbb2222"]["type"] == "asistir", f"evento → asistir: {b['bbbb2222'].get('type')}")
check(b["cccc3333"]["urgency"] == "baja", f"{b['cccc3333'].get('urgency')}")
check(b["cccc3333"]["source"] == "correo", f"tag correo → source correo: {b['cccc3333'].get('source')}")
check(b["aaaa1111"]["source"] == "manual", f"{b['aaaa1111'].get('source')}")
check(b["aaaa1111"]["title"] == "vieja alta" and b["aaaa1111"]["id"] == "aaaa1111", "legacy data preserved")

print("== 8) edit_task changes type/urgency and keeps priority coherent ==")
fresh()
t = board.add_task("editable")
e = board.edit_task(t["id"], task_type="revisar", urgency="critica")
check(e and e["type"] == "revisar" and e["urgency"] == "critica" and e["priority"] == "alta", f"{e}")
e = board.edit_task(t["id"], urgency="inventada")
check(e["urgency"] == "critica", "invalid edit value is ignored")
e = board.edit_task(t["id"], priority="baja")
check(e["urgency"] == "baja" and e["priority"] == "baja", f"legacy priority edit: {e['urgency']}")

print()
print(f"test_board_pattern: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
