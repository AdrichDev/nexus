"""P0-03 startup/core-journey probe. Run only inside the hermetic container.

Starts the real backend in a child process, then asserts: process start, loaded skills
vs skill folders, HTTP status, a local text command round-trip, WS delivery, failure
behavior (bad origin, empty command) and restart/reconnect. No credentials, no network.
"""
from __future__ import annotations

import asyncio, json, os, signal, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
RESULTS: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    RESULTS.append((bool(ok), msg))
    print(("  OK  " if ok else "  FAIL ") + msg, flush=True)


def start() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, stdout=open("/tmp/server.log", "ab"), stderr=subprocess.STDOUT)


def wait_up(p: subprocess.Popen, secs: int = 90) -> bool:
    t = time.time()
    while time.time() - t < secs and p.poll() is None:
        try:
            urllib.request.urlopen(BASE + "/api/skills", timeout=2).read()
            return True
        except Exception:
            time.sleep(1)
    return False


def get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=20).read())


def post(path: str, body: dict):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
                               {"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(r, timeout=60)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, None


async def ws_frames(origin: str | None, n: int = 3, wait: float = 5.0):
    import websockets
    hdr = {"Origin": origin} if origin else {}
    frames = []
    try:
        async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws", additional_headers=hdr) as w:
            end = time.time() + wait
            while len(frames) < n and time.time() < end:
                try:
                    frames.append(await asyncio.wait_for(w.recv(), timeout=1.0))
                except asyncio.TimeoutError:
                    pass
        return True, frames
    except Exception as e:  # rejected handshake / closed
        return False, [repr(e)[:120]]


def main() -> int:
    srv = start()
    try:
        check(wait_up(srv), "backend process starts and serves HTTP")
        skills = get("/api/skills")
        folders = [d for d in (ROOT / "skills").iterdir() if d.is_dir() and not d.name.startswith("_")]
        loaded = len(skills) if isinstance(skills, list) else len(skills.get("skills", skills))
        print(f"  info skills loaded={loaded} folders={len(folders)}")
        check(loaded > 0, "skills summary is non-empty")
        st = get("/api/status")
        check("metrics" in st and st.get("skills") == loaded, "/api/status coherent with /api/skills")

        code, res = post("/api/command", {"text": "cuanto es 2 mas 2"})
        print(f"  info command reply={str(res)[:160]!r}")
        check(code == 200 and isinstance(res, dict) and res.get("reply"), "text command returns a reply")
        check(res and "4" in str(res.get("reply")), "reply contains the correct local result (4)")
        code, res = post("/api/command", {"text": ""})
        print(f"  info empty command -> HTTP {code} reply={str(res)[:120]!r}")
        check(code in (200, 400, 422) and (res is None or isinstance(res, dict)),
              f"empty command does not crash (HTTP {code})")

        ok, fr = asyncio.run(ws_frames(f"http://127.0.0.1:{PORT}"))
        print(f"  info ws frames={len(fr)} first={str(fr[0])[:120] if fr else None!r}")
        check(ok, "WS accepts same-authority loopback Origin")
        ok, fr = asyncio.run(ws_frames("http://evil.example"))
        print(f"  info foreign-origin ws ok={ok} frames={[str(f)[:100] for f in fr]}")
        check((not ok) or not any('"boot"' in str(f) for f in fr),
              "WS with foreign Origin and no token is refused (no boot/data frames)")

        srv.send_signal(signal.SIGTERM); srv.wait(timeout=30)
        try:
            urllib.request.urlopen(BASE + "/api/skills", timeout=2); down = False
        except Exception:
            down = True
        check(down, "server is really down after SIGTERM (client sees failure)")
        srv = start()
        check(wait_up(srv), "server restarts")
        ok, _ = asyncio.run(ws_frames(f"http://127.0.0.1:{PORT}"))
        check(ok, "WS reconnects after restart")
    finally:
        if srv.poll() is None:
            srv.terminate()
            try: srv.wait(timeout=20)
            except Exception: srv.kill()
    bad = [m for ok, m in RESULTS if not ok]
    print(f"\nP0-03 probe: {len(RESULTS) - len(bad)} OK, {len(bad)} FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
