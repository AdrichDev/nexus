# -*- coding: utf-8 -*-
"""Static checks (no browser) of the Jira-like task card and the detail panel in command.js.
Run:  python tests/unit/frontend/test_task_cards.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JS = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "command.css").read_text(encoding="utf-8")

_fail: list[str] = []
_ok = 0


def check(cond, msg):
    global _ok
    if cond:
        _ok += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)


def body_of(name: str) -> str:
    """Source of `function name(...) {...}` or `const name = ...` up to the next top-level blank-line item."""
    m = re.search(rf"(?:function {name}\b|const {name} =)", JS)
    if not m:
        return ""
    return JS[m.start(): m.start() + 6000]


tasks_view = JS[JS.index("views.tasks = () =>"): JS.index("async function refreshBoard")]

print("== card ==")
check("priority === 'alta'" not in tasks_view and 'priority === "alta"' not in tasks_view,
      "card must not badge on legacy priority === 'alta'")
check("taskUrgency(t)" in tasks_view and "t.urgency" in body_of("taskUrgency"),
      "card derives its badge from urgency (priority only as fallback)")
for lvl, label in (("critica", "CRÍTICA"), ("alta", "ALTA"), ("media", "MEDIA"), ("baja", "BAJA")):
    check(label in JS, f"label {label} present")
    check(f"badge-u-{lvl}" in CSS or f".u-{lvl}" in CSS, f"css class for urgency {lvl}")
check("t.key" in tasks_view, "card shows the key")
check("TASK_TYPE_ICON" in JS and all(ic in JS for ic in ("✉", "🛠", "💳", "📅", "🔎", "⏳")),
      "type icon map covers the six types")
check("'evento'" in JS and "asistir" in JS, "legacy kind=evento maps to asistir")
check("correo" in tasks_view, "source chip for correo")

print("== detail panel ==")
check("function openTaskDetail" in JS, "openTaskDetail exists")
det = body_of("openTaskDetail") + body_of("taskDetailHtml")
check("esc(" in det, "detail panel escapes dynamic text")
check("sourceUrl" in det, "detail panel shows sourceUrl")
check("sourceIds" in det, "detail panel shows grouped mail count")
check("Escape" in JS and "closeTaskDetail" in JS, "Escape closes the detail panel")
check("function linkifyText" in JS, "linkifyText exists")
lk = body_of("linkifyText")
check("https?" in lk and "noopener noreferrer" in lk and 'target="_blank"' in lk,
      "links restricted to http(s) with rel/target")
check("javascript" not in lk.lower(), "no javascript: scheme handling")
check("white-space:pre-wrap" in CSS.replace(" ", "") or "white-space:pre-wrap" in CSS, "description keeps line breaks")
check("#task-detail" in CSS, "css for #task-detail")
check("closest('button, input, a')" in JS, "card click ignores its buttons")

print()
print(f"test_task_cards: {_ok} OK, {len(_fail)} fallos")
sys.exit(1 if _fail else 0)
