# -*- coding: utf-8 -*-
"""clima: error replies must name the real cause (unknown city vs. network down).

Mocked httpx only: no network, no production config. Evidence level M.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from skills.clima import skill as clima  # noqa: E402

_fail = []; _pass = 0
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def check(c, m):
    global _pass
    if c: _pass += 1
    else: _fail.append(m); print("  FALLO:", m)


def fake_client(status=None, exc=None):
    class _Resp:
        def __init__(self, url):
            self.request = httpx.Request("GET", url)
            self.status_code = status or 200
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "err", request=self.request,
                    response=httpx.Response(self.status_code, request=self.request))
        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            if exc: raise exc
            return _Resp(url)
    return _Client


def run(text, **kw):
    orig = clima.httpx.AsyncClient
    clima.httpx.AsyncClient = fake_client(**kw)
    try:
        return asyncio.run(clima.handle("weather", text, None, None))["reply"]
    finally:
        clima.httpx.AsyncClient = orig


for code in (404, 500):
    r = run("clima en Ciudadinexistentexyz", status=code)
    check("ciudadinexistentexyz" in r.lower(), f"HTTP {code} names the city")
    check(str(code) in r, f"HTTP {code} reports the status code")
    check("nombre" in r.lower(), f"HTTP {code} suggests checking the city name")
    check("cosa de red" not in r.lower(), f"HTTP {code} does not blame the network")

r = run("que tiempo hace", status=500)
check("wttr.in" in r and "nombre" not in r.lower(), "HTTP error without city does not ask about a name")

r = run("clima en Sevilla", exc=httpx.ConnectError("down"))
check("wttr.in" in r and "cosa de red" in r.lower(), "ConnectError still reports the network")

print(f"\nclima errors: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
