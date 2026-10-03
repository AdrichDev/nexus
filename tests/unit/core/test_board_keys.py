# -*- coding: utf-8 -*-
"""Stable task keys (NX-<n>): sequential, unique, never reused, migrated deterministically
and idempotently, and resolvable through find_task (case-insensitive).

Uses a temporary data dir set BEFORE importing the board.
Run:  python tests/unit/core/test_board_keys.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="nexus_keys_test_")
os.environ["NEXUS_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["NEXUS_CONFIG_DIR"] = os.path.join(TMP, "config")

from backend.core.dominio import board  # noqa: E402

board.BOARD_FILE = board.DATA_DIR / "board.json"
board.TRASH_FILE = board.DATA_DIR / "board_trash.json"
board.SEQ_FILE = board.DATA_DIR / "board_seq.json"
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
    for f in (board.BOARD_FILE, board.TRASH_FILE, board.SEQ_FILE):
        if f.exists():
            f.unlink()


def raw():
    return json.loads(board.BOARD_FILE.read_text(encoding="utf-8"))


print("== 1) keys are sequential and unique ==")
fresh()
ts = [board.add_task(f"t{i}") for i in range(4)]
check([t["key"] for t in ts] == ["NX-1", "NX-2", "NX-3", "NX-4"], f"{[t.get('key') for t in ts]}")
check(len({t["key"] for t in raw()}) == 4, "unique and persisted")

print("== 2) never reused after trash / delete / purge ==")
board.delete_task(ts[3]["id"])                      # NX-4 goes to the trash
check(board.add_task("after trash")["key"] == "NX-5", "trashed key not reused")
board.purge_trash()                                  # NX-4 destroyed for good
check(board.add_task("after purge")["key"] == "NX-6", "purged key not reused")
board.clear_all()
check(board.add_task("after clear")["key"] == "NX-7", "key continues after clear_all")

print("== 3) restore keeps the original key ==")
fresh()
a = board.add_task("a"); b = board.add_task("b")
board.delete_task(a["id"])
back = board.restore(a["id"])
check(back and back[0]["key"] == "NX-1", f"{back}")
check(board.add_task("c")["key"] == "NX-3", "next key after restore")

print("== 4) migration of keyless tasks: deterministic, idempotent, persisted ==")
fresh()
old = [{"id": "zzz", "title": "newer", "state": "pendiente", "createdAt": "2026-02-01T10:00:00"},
       {"id": "bbb", "title": "older b", "state": "pendiente", "created": "2026-01-01"},
       {"id": "aaa", "title": "older a", "state": "progreso", "created": "2026-01-01"},
       {"id": "kkk", "title": "has key", "state": "pendiente", "key": "NX-9"}]
board.BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
board.BOARD_FILE.write_text(json.dumps(old), encoding="utf-8")
first = {t["id"]: t["key"] for t in board._load()}
check(first == {"aaa": "NX-10", "bbb": "NX-11", "zzz": "NX-12", "kkk": "NX-9"}, f"{first}")
second = {t["id"]: t["key"] for t in board._load()}
check(first == second, "idempotent across loads")
board.add_task("fresh one")
after = {t["id"]: t["key"] for t in raw()}
check(all(after[k] == v for k, v in first.items()), "migrated keys persisted unchanged on save")
check(len(set(after.values())) == 5 and "NX-13" in after.values(), f"{after}")

print("== 5) find_task by key ==")
fresh()
t = board.add_task("buscar por clave")
check(board.find_task("nx-1")["id"] == t["id"], "lowercase key")
check(board.find_task(" NX-1 ")["id"] == t["id"], "padded key")
check(board.find_task("NX-99") is None, "unknown key")
check(board.board()["pendiente"][0]["key"] == "NX-1", "key exposed by board()")
e = board.edit_task(t["id"], title="otro"); m = board.move_task(t["id"], "progreso")
check(e["key"] == m["key"] == "NX-1", "edit/move keep the key")

print()
print(f"test_board_keys: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
