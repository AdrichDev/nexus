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


def fake_client(routes):
    """routes: {substring_of_url: status_int | Exception}. Default 200 with empty JSON."""
    calls = []

    class _Resp:
        def __init__(self, url, status):
            self.request = httpx.Request("GET", url)
            self.status_code = status
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
            calls.append(url)
            for key, val in routes.items():
                if key in url:
                    if isinstance(val, Exception): raise val
                    return _Resp(url, val)
            return _Resp(url, 200)
    return _Client, calls


def run(text, routes):
    orig = clima.httpx.AsyncClient
    cls, calls = fake_client(routes)
    clima.httpx.AsyncClient = cls
    try:
        return asyncio.run(clima.handle("weather", text, None, None))["reply"], calls
    finally:
        clima.httpx.AsyncClient = orig


# Unknown city: wttr.in errors for it, but a control city answers -> the city does not exist.
for code in (404, 500):
    r, calls = run("clima en Ciudadinexistentexyz", {"Ciudadinexistentexyz": code})
    low = r.lower()
    check("ciudadinexistentexyz" in low, f"HTTP {code} names the city")
    check("no existe" in low or "no encuentro" in low, f"HTTP {code} says the city does not exist")
    check("red" not in low and "wttr" not in low and "http" not in low,
          f"HTTP {code} exposes no network/provider/status jargon")
    check(len(calls) == 2, f"HTTP {code} does one control request")

# Transient/throttling status on the city request only (control answers): not a verdict on the city.
for code in (429, 502, 503, 504):
    r, calls = run("clima en Sevilla", {"Sevilla": code})
    low = r.lower()
    check("no existe" not in low and "no encuentro" not in low,
          f"HTTP {code} on the city request does not claim the city is unknown")
    check("repítemelo" in low or "repitemelo" in low, f"HTTP {code} asks to retry")
    check(len(calls) == 1, f"HTTP {code} does not need a control request")

# Provider down: city error AND control error -> cannot claim the city is wrong.
r, _ = run("clima en Sevilla", {"wttr.in": 503})
check("no existe" not in r.lower() and "no encuentro" not in r.lower(), "provider down is not reported as unknown city")
check("wttr.in" in r, "provider down is reported as provider problem")

# Network down.
r, _ = run("clima en Sevilla", {"wttr.in": httpx.ConnectError("down")})
check("wttr.in" in r and "cosa de red" in r.lower(), "ConnectError still reports the network")

# No city + HTTP error: no control request, no claim about a name.
r, calls = run("que tiempo hace", {"wttr.in": 500})
check(len(calls) == 1 and "no existe" not in r.lower(), "no-city HTTP error makes no existence claim")

print(f"\nclima errors: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
