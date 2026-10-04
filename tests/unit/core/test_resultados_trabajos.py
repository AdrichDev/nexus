# -*- coding: utf-8 -*-
"""Background job results (Hermes) must reach the operator and the conversation.

Production findings (2026-10-04): Hermes finished with the right answer, but
(1) the result was only broadcast live, so a HUD that reconnected afterwards
lost it among logs/metrics in the 30-event replay; (2) it never entered the
conversation history, so follow-ups ("eso no es correcto") reviewed the
"Voy a ello" placeholder instead of the real answer; (3) long results were cut
at 2000/3500 characters.

Run: .venv\\Scripts\\python.exe tests\\unit\\core\\test_resultados_trabajos.py
"""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_resjob_"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.core.aplicacion.jobs as jobsmod   # noqa: E402
import backend.core.comun.audit as audit         # noqa: E402
from backend.core.comun.events import EventBus, bus   # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="nexus_resjob2_"))
jobsmod.JOBS_FILE = _TMP / "jobs.json"
audit.AUDIT_FILE = _TMP / "logs" / "audit.jsonl"

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


def _fresh():
    jm = jobsmod.JobManager(max_concurrent=4)
    jm._jobs, jm._order, jm._counter = {}, [], 0
    return jm


async def _finish_job(jm, result, request="hermes: dime algo largo"):
    chats, seen = [], []
    orig = bus.emit

    async def _spy(kind, data=None):
        if kind == "chat":
            chats.append(data)
        return await orig(kind, data)
    bus.emit = _spy
    jobsmod.set_result_listener(lambda req, text, ch: seen.append((req, text, ch)))
    try:
        async def _ok():
            return {"reply": result}
        await jm.submit("Hermes #1", _ok, notify=True, channel="pc", request=request,
                        kind="hermes", agent="hermes")
        await asyncio.sleep(0.2)
    finally:
        bus.emit = orig
        jobsmod.set_result_listener(None)
    return chats, seen


def main():
    print("== long results are not truncated ==")
    long_text = "Inicio. " + ("dato " * 1200) + "FINAL-DEL-INFORME"
    chats, seen = asyncio.run(_finish_job(_fresh(), long_text))
    check(len(chats) == 1 and "FINAL-DEL-INFORME" in chats[0]["reply"],
          "a ~6000-char result reaches the chat complete")

    print("== the result enters the conversation ==")
    check(len(seen) == 1, "result listener called once per finished job")
    if seen:
        req, text, ch = seen[0]
        check(req == "hermes: dime algo largo" and "FINAL-DEL-INFORME" in text and ch == "pc",
              "listener receives the original request, full text and channel")

    print("== failed jobs are recorded too (honest state, not silence) ==")

    async def _failing():
        jm = _fresh()
        seen2 = []
        jobsmod.set_result_listener(lambda req, text, ch: seen2.append(text))
        try:
            async def _bad():
                raise RuntimeError("rate limit")
            await jm.submit("Hermes #2", _bad, notify=True, channel="pc", request="hermes: x")
            await asyncio.sleep(0.2)
        finally:
            jobsmod.set_result_listener(None)
        return seen2
    seen2 = asyncio.run(_failing())
    check(seen2 and "FALLADO" in seen2[0], "failure is recorded in the conversation")

    print("== listener errors never break the notification ==")

    async def _boom():
        jm = _fresh()
        chats3 = []
        orig = bus.emit

        async def _spy(kind, data=None):
            if kind == "chat":
                chats3.append(data)
            return await orig(kind, data)
        bus.emit = _spy

        def _explode(*a):
            raise ValueError("listener bug")
        jobsmod.set_result_listener(_explode)
        try:
            async def _ok():
                return "resultado"
            await jm.submit("Hermes #3", _ok, notify=True, channel="pc", request="r")
            await asyncio.sleep(0.2)
        finally:
            bus.emit = orig
            jobsmod.set_result_listener(None)
        return chats3
    check(len(asyncio.run(_boom())) == 1, "chat still published when the listener fails")

    print("== reconnect replay keeps recent chat results ==")
    b = EventBus()
    b.history = ([{"type": "chat", "data": {"user": f"q{i}", "reply": f"r{i}"}, "ts": i}
                  for i in range(3)]
                 + [{"type": "log", "data": {"msg": f"l{i}"}, "ts": 10 + i} for i in range(100)])
    rep = b.replay(30)
    types = [e["type"] for e in rep]
    check(types.count("chat") == 3, "chats older than the 30-event window are replayed")
    check(types.count("log") == 30, "the last 30 events are still replayed")
    check([e["ts"] for e in rep] == sorted(e["ts"] for e in rep), "replay is chronological")
    b.history = [{"type": "chat", "data": {}, "ts": i} for i in range(100)]
    check(len(b.replay(30)) <= 50, "replay stays bounded")

    print("== wiring ==")
    app = (ROOT / "backend/app.py").read_text(encoding="utf-8")
    check("bus.replay(" in app and "bus.history[-30:]" not in app,
          "websocket reconnect uses bus.replay()")
    brain = (ROOT / "backend/core/aplicacion/brain.py").read_text(encoding="utf-8")
    check("set_result_listener(" in brain, "brain records job results in its conversation history")
    hermes = (ROOT / "skills/hermes/skill.py").read_text(encoding="utf-8")
    cuts = [int(n) for n in re.findall(r"(?:\+ out|resultado=out)\[:(\d+)\]", hermes)]
    check(cuts and min(cuts) >= 8000, f"Hermes output is not cut below 8000 chars: {cuts}")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50)
    print(f"{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
