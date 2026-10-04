# -*- coding: utf-8 -*-
"""The persistent log must follow the configured data directory.

Regression: events._persist_log wrote to a hardcoded <repo>/data/nexus.log, so
every test that emitted a log event polluted the operator's real log (fake
jobs, fake inbox documents, false "Hermes unavailable" warnings).

Run: .venv\\Scripts\\python.exe tests\\unit\\core\\runtime\\test_log_aislado.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
REAL_LOG = ROOT / "data" / "nexus.log"
RUN_ALL = ROOT / "tests" / "run_all.py"

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


def _real_log_state():
    try:
        st = REAL_LOG.stat()
        return st.st_size, st.st_mtime_ns
    except OSError:
        return None


def main():
    marker = "LOG-ISOLATION-MARKER-7f3a"

    print("== NEXUS_DATA_DIR sandbox receives the log ==")
    tmp = Path(tempfile.mkdtemp(prefix="nexus_log_iso_"))
    before = _real_log_state()
    code = ("from backend.core.comun import events; "
            f"events._persist_log({{'level': 'info', 'msg': '{marker} env'}})")
    env = {**os.environ, "NEXUS_DATA_DIR": str(tmp), "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 0, f"subprocess ran ({r.stderr[-300:]})")
    sand = tmp / "nexus.log"
    check(sand.exists() and marker in sand.read_text(encoding="utf-8"),
          "log written inside NEXUS_DATA_DIR")
    check(_real_log_state() == before, "real data/nexus.log untouched")

    print("== in-process DATA_DIR monkeypatch receives the log ==")
    tmp2 = Path(tempfile.mkdtemp(prefix="nexus_log_iso2_"))
    before = _real_log_state()
    code = ("from pathlib import Path; from backend.core.comun import config, events; "
            f"events._persist_log({{'level': 'info', 'msg': 'warmup'}}); "
            f"config.DATA_DIR = Path(r'{tmp2}'); "
            f"events._persist_log({{'level': 'info', 'msg': '{marker} patched'}})")
    env = {**os.environ, "NEXUS_DATA_DIR": str(tmp), "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    check(r.returncode == 0, f"subprocess ran ({r.stderr[-300:]})")
    sand2 = tmp2 / "nexus.log"
    check(sand2.exists() and f"{marker} patched" in sand2.read_text(encoding="utf-8"),
          "log follows a DATA_DIR changed after the first write (no stale cache)")
    check(_real_log_state() == before, "real data/nexus.log untouched")

    print("== the test runner isolates every suite's data directory ==")
    src = RUN_ALL.read_text(encoding="utf-8")
    check('"NEXUS_DATA_DIR"' in src and "mkdtemp" in src,
          "run_all.py gives suites a sandboxed NEXUS_DATA_DIR")


if __name__ == "__main__":
    main()
    print("\n" + "=" * 50)
    print(f"{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
