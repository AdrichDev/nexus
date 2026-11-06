# -*- coding: utf-8 -*-
"""LA CONFIANZA LOCAL DEJA DE SER «EL PEER ES LOOPBACK» — Host, Origin y el token.

Auditoría de seguridad, SEC-03 (roadmap P1-3, task T4). Tres cierres:

  1. `_es_este_equipo` daba por bueno CUALQUIER peer 127.0.0.1/::1/localhost sin
     mirar `Host` ni `Origin`. Una página del navegador que resuelve SU dominio a
     127.0.0.1 (DNS rebinding) llamaba a `/api/command` como si fuera el dueño.
     Ahora la confianza local exige `Host` de loopback CON puerto y, si viene
     `Origin`, que sea exactamente esa misma autoridad (las mismas reglas que el
     WebSocket ya aplicaba en `_trusted_local_ws_origin`).
  2. `remote.status()` devolvía `"token"`, así que `/api/link/status` entregaba
     el token del QR y con él se entraba desde la WiFi o el túnel para siempre.
     El token ya no sale en el estado; el QR (`/api/link/qr` y el campo `link`
     que dibuja el HUD) sigue llevándolo, que es su único trabajo.
  3. `/api/n8n` autentica con su propio secreto (`x-nexus-n8n-secret`), pero el
     middleware lo tumbaba antes con un 401 cuando la petición viene de Docker
     (`host.docker.internal:8177`, peer que no es loopback): los flujos de
     ejemplo no podían funcionar nunca. El middleware exime SOLO esa ruta; el
     handler sigue siendo la autoridad y sigue exigiendo el secreto.

TODO va EN PROCESO (httpx.ASGITransport, que NO ejecuta `lifespan`): ni uvicorn,
ni puertos, ni micrófono, ni Telegram. La configuración y los datos se apuntan a
carpetas de usar y tirar con NEXUS_CONFIG_DIR / NEXUS_DATA_DIR antes de importar
el backend, para no tocar los del operador.

Ejecutar:  .venv\\Scripts\\python.exe tests\\integration\\http\\test_host_origin.py
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar backend: ni config/settings.json ni config/secrets.json del
# operador se leen ni se escriben desde aquí.
_CFG = tempfile.mkdtemp(prefix="nexus_host_origin_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_host_origin_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA
for _env in ("NEXUS_N8N_SECRET", "N8N_SECRET"):
    os.environ.pop(_env, None)

import httpx                                                    # noqa: E402

from backend.core.comun.config import settings                  # noqa: E402
from backend.core.aplicacion import brain                       # noqa: E402
from backend.core.infraestructura import remote                 # noqa: E402
import backend.app as servidor                                  # noqa: E402

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


APP = servidor.app
# Token de vinculación de mentira, en la config de usar y tirar.
TOK = "token-de-prueba-del-qr"
CERRADO = {"error": "no autorizado — vincula el móvil con el QR de nexus"}
SIN_SECRETO_N8N = ("no autorizado — el flujo de n8n necesita la cabecera "
                   "x-nexus-n8n-secret")
CABECERA_N8N = "x-nexus-n8n-secret"
# Host del HUD de verdad: uvicorn escucha en 8177 y la ventana apunta ahí
# (backend/desktop.py: BIND/HOST/PORT).
HUD = "127.0.0.1:8177"
settings.set_secret("link_token", TOK)


def _cliente(peer: str = "127.0.0.1") -> httpx.AsyncClient:
    """Cliente ASGI en proceso con un peer concreto (el de casa o uno de fuera)."""
    transporte = httpx.ASGITransport(app=APP, client=(peer, 4321))
    return httpx.AsyncClient(transport=transporte, base_url=f"http://{HUD}")


def _cab(host: str | None = HUD, origin: str | None = None,
         token: str = "", extra: dict | None = None) -> dict:
    """Cabeceras de una petición. `host=None` → la pone httpx a partir de la URL."""
    cab = {}
    if host is not None:
        cab["host"] = host
    if origin is not None:
        cab["origin"] = origin
    if token:
        cab["x-nexus-token"] = token
    cab.update(extra or {})
    return cab


class _Espia:
    """Sustituto de brain.process: apunta la llamada y contesta algo inocuo."""

    def __init__(self):
        self.llamadas = []

    async def __call__(self, text, source="text", **kw):
        self.llamadas.append({"text": text, "source": source, **kw})
        return {"reply": "eco de prueba", "skill": None, "provider": "espia", "data": None}


class _Doble:
    """Contexto que cambia un atributo y lo devuelve pase lo que pase."""

    def __init__(self, obj, nombre, valor):
        self.obj, self.nombre, self.valor, self.previo = obj, nombre, valor, None

    def __enter__(self):
        self.previo = getattr(self.obj, self.nombre)
        setattr(self.obj, self.nombre, self.valor)
        return self.valor

    def __exit__(self, *_exc):
        setattr(self.obj, self.nombre, self.previo)
        return False


class _Red:
    """`remote.status()` de verdad, sin tocar la red: direcciones y Tailscale fijos."""

    def __enter__(self):
        self._previos = [
            (remote, "direcciones",
             lambda: [{"host": "192.168.1.50:8177", "esquema": "http",
                       "tipo": "wifi", "estable": False}]),
            (remote, "tailscale_status",
             lambda cache_seg=20.0: {"instalado": False, "activo": False,
                                     "ip": "", "error": ""}),
            (remote, "lan_ip", lambda: "192.168.1.50"),
            (remote, "nombre_local", lambda: "pc-de-prueba.local"),
        ]
        self._guardados = [(obj, nom, getattr(obj, nom)) for obj, nom, _ in self._previos]
        for obj, nom, valor in self._previos:
            setattr(obj, nom, valor)
        return self

    def __exit__(self, *_exc):
        for obj, nom, valor in self._guardados:
            setattr(obj, nom, valor)
        return False


# ── 1. HOST: un peer de loopback con Host ajeno NO es este equipo ─────────────
async def _host_ajeno() -> None:
    for ruta, metodo, cuerpo in (("/api/command", "POST", {"text": "hola"}),
                                 ("/api/status", "GET", None)):
        espia = _Espia()
        with _Doble(brain, "process", espia):
            async with _cliente() as c:
                if cuerpo is None:
                    r = await c.request(metodo, ruta, headers=_cab(host="evil.example:8177"))
                else:
                    r = await c.request(metodo, ruta, headers=_cab(host="evil.example:8177"),
                                        json=cuerpo)
        check(r.status_code == 401,
              f"{metodo} {ruta} con Host: evil.example:8177 desde loopback da 401, dio {r.status_code}")
        check(r.json() == CERRADO,
              f"{metodo} {ruta} con Host ajeno: cuerpo de error exacto, salió {r.text[:120]!r}")
        check(espia.llamadas == [],
              f"{metodo} {ruta} con Host ajeno: el cerebro NO se toca, se llamó {espia.llamadas!r}")

    # Y con el Host de verdad, sí entra: el HUD del propio PC sigue funcionando.
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente() as c:
            r = await c.post("/api/command", headers=_cab(host=HUD), json={"text": "hola"})
            st = await c.get("/api/status", headers=_cab(host=HUD))
    check(r.status_code == 200, f"el HUD (Host {HUD}) manda órdenes, dio {r.status_code}")
    check(len(espia.llamadas) == 1,
          f"el HUD (Host {HUD}) llega al cerebro una vez, llegó {len(espia.llamadas)}")
    check(st.status_code == 200, f"y lee /api/status sin token, dio {st.status_code}")
    check(st.json().get("skills") is not None,
          f"/api/status devuelve el estado de verdad, salió {st.text[:120]!r}")

    # Las tres formas de llamar a loopback valen: 127.0.0.1, localhost y [::1].
    # El puerto NO se fija (misma regla que el WebSocket, que exige que haya
    # puerto pero no que sea 8177): lo que no puede faltar es el puerto.
    for host in ("127.0.0.1:8177", "localhost:8177", "[::1]:8177", "127.0.0.1:8199"):
        async with _cliente() as c:
            r = await c.get("/api/status", headers=_cab(host=host))
        check(r.status_code == 200, f"Host de loopback {host!r} es este equipo, dio {r.status_code}")

    # Host sin puerto, con ruta, con userinfo, con espacios o repetido: NO.
    for host, etiqueta in (
            ("127.0.0.1", "sin puerto"),
            ("127.0.0.1:8177/", "con ruta"),
            ("127.0.0.1:8177/x", "con ruta y más"),
            ("127.0.0.1:8177@evil.example:8177", "con userinfo"),
            ("http://127.0.0.1@evil/", "con esquema y userinfo"),
            (" 127.0.0.1:8177", "con espacio delante"),
            ("127.0.0.1:8177 ", "con espacio detrás"),
            ("", "vacío")):
        async with _cliente() as c:
            r = await c.get("/api/status", headers=_cab(host=host))
        check(r.status_code == 401,
              f"Host {etiqueta} ({host!r}) NO da confianza local, dio {r.status_code}")

    # Un `Host:` repetido es la ambigüedad clásica proxy/servidor: no se adivina.
    async with _cliente() as c:
        r = await c.get("/api/status",
                        headers=[("host", HUD), ("host", "evil.example:8177")])
    check(r.status_code == 401,
          f"un Host repetido (válido + ajeno) NO da confianza local, dio {r.status_code}")
    async with _cliente() as c:
        r = await c.get("/api/status",
                        headers=[("host", "evil.example:8177"), ("host", HUD)])
    check(r.status_code == 401,
          f"un Host repetido (ajeno + válido) NO da confianza local, dio {r.status_code}")

    # Las otras formas de escribir 127.0.0.1 que usa un rebindeo real: ninguna es
    # una autoridad de loopback limpia, así que ninguna cuela como «este equipo».
    for host in ("2130706433:8177", "127.1:8177", "0x7f.0.0.1:8177",
                 "127.0.0.1:8177.evil.com", "127.0.0.1.", "[::1]:8177]"):
        async with _cliente() as c:
            r = await c.get("/api/status", headers=_cab(host=host))
        check(r.status_code == 401,
              f"Host {host!r} (rebindeo/ambigua) NO da confianza local, dio {r.status_code}")


# ── 2. ORIGIN: si viene, tiene que ser esta misma autoridad ───────────────────
async def _origin() -> None:
    casos = [
        ("http://127.0.0.1:8177", 200, "el Origin del HUD"),
        ("http://localhost:8177", 401, "un Origin de OTRA autoridad de loopback"),
        ("https://127.0.0.1:8177", 401, "el mismo Host con otro esquema"),
        ("http://127.0.0.1:9999", 401, "el mismo host con otro puerto"),
        ("http://evil.example:8177", 401, "un Origin ajeno"),
        ("null", 401, "el Origin «null» de un iframe/sandbox"),
        ("http://127.0.0.1:8177/", 401, "un Origin con ruta"),
        ("http://127.0.0.1:8177:8177", 401, "un Origin con dos puertos"),
        ("http://127.0.0.1:8177#recorte", 401, "un Origin con fragmento"),
        ("http://[::1]:8177", 401, "otra autoridad de loopback (IPv6)"),
        ("bogus", 401, "un Origin que no es una URL"),
    ]
    for origin, esperado, etiqueta in casos:
        espia = _Espia()
        with _Doble(brain, "process", espia):
            async with _cliente() as c:
                r = await c.post("/api/command", headers=_cab(host=HUD, origin=origin),
                                 json={"text": "hola"})
        check(r.status_code == esperado,
              f"{etiqueta} ({origin!r}) → {esperado}, dio {r.status_code}")
        if esperado == 401:
            check(espia.llamadas == [],
                  f"{etiqueta} ({origin!r}): el cerebro NO se toca")
        else:
            check(len(espia.llamadas) == 1, f"{etiqueta} ({origin!r}): llega al cerebro")

    # Sin Origin (pywebview, curl, scripts nativos) se acepta: igual que el WS.
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente() as c:
            r = await c.post("/api/command", headers=_cab(host=HUD), json={"text": "hola"})
    check(r.status_code == 200,
          f"sin cabecera Origin (cliente nativo) el HUD sigue entrando, dio {r.status_code}")

    # Un Origin ajeno en una lectura tampoco cuela: el rebinding también pide GET.
    async with _cliente() as c:
        r = await c.get("/api/jobs", headers=_cab(host=HUD, origin="http://evil.example:8177"))
    check(r.status_code == 401, f"lectura con Origin ajeno → 401, dio {r.status_code}")


# ── 3. Cabeceras de proxy: siguen quitando la confianza local (sin cambios) ───
async def _proxy() -> None:
    for extra, etiqueta in (({"x-forwarded-for": "192.0.2.9"}, "x-forwarded-for"),
                            ({"cf-connecting-ip": "203.0.113.9"}, "cf-connecting-ip")):
        async with _cliente() as c:
            r = await c.get("/api/status", headers=_cab(host=HUD, extra=extra))
        check(r.status_code == 401,
              f"con {etiqueta} y peer de loopback no hay confianza local, dio {r.status_code}")


# ── 4. REGRESIÓN: el móvil/túnel con el token del QR sigue entrando ──────────
async def _token() -> None:
    espia = _Espia()
    with _Doble(brain, "process", espia):
        # 1) sin credencial ninguna, no pasa
        async with _cliente("203.0.113.9") as c:
            sin = await c.post("/api/command", headers=_cab(host="casa.example"),
                               json={"text": "hola"})
        check(sin.status_code == 401,
              f"el móvil por el túnel SIN token no pasa, dio {sin.status_code}")

        # 2) con el token del QR, sí; y deja la cookie de siempre
        async with _cliente("203.0.113.9") as c:
            r = await c.post("/api/command", headers=_cab(host="casa.example", token=TOK),
                             json={"text": "hola"})
            check(r.status_code == 200,
                  f"el móvil VINCULADO por el túnel manda órdenes, dio {r.status_code}")
            check(r.cookies.get("nexus_token") == TOK,
                  "el token validado se guarda en la cookie de siempre")
            # la cookie que dejó esa petición también autentica
            solo_cookie = await c.post("/api/command", headers=_cab(host="casa.example"),
                                       json={"text": "hola"})
        check(solo_cookie.status_code == 200,
              f"la cookie nexus_token sigue autenticando al móvil, dio {solo_cookie.status_code}")

        # 3) un token equivocado no cuela
        async with _cliente("203.0.113.9") as c:
            malo = await c.post("/api/command",
                                headers=_cab(host="casa.example", token=TOK + "x"),
                                json={"text": "hola"})
        check(malo.status_code == 401, f"un token equivocado no cuela, dio {malo.status_code}")
    check(len(espia.llamadas) == 2,
          f"el móvil vinculado llegó al cerebro 2 veces, llegó {len(espia.llamadas)}")

    # y el token no se puede leer ya desde el estado de vinculación
    with _Red():
        async with _cliente() as c:
            r = await c.get("/api/link/status", headers=_cab(host=HUD))
            qr = await c.get("/api/link/qr", headers=_cab(host=HUD))
    check(r.status_code == 200, f"/api/link/status sigue respondiendo, dio {r.status_code}")
    st = r.json()
    check("token" not in st,
          f"/api/link/status ya NO entrega el token (claves: {sorted(st)})")
    check(all(not (isinstance(v, str) and v == TOK) for v in st.values()),
          "ningún campo de /api/link/status devuelve el token en claro")
    # el HUD (frontend/js/modals/link.js) pinta el QR con «link»: sigue estando
    check("link" in st, "el HUD sigue teniendo el enlace del QR (link)")
    check("token=" in str(st.get("link", "")),
          "el enlace del QR lleva el token, que es su único trabajo")
    for clave in ("devices", "via", "hosts", "estable", "tailscale", "lan"):
        check(clave in st, f"/api/link/status sigue trayendo «{clave}» para el HUD")
    check(qr.status_code == 200, f"/api/link/qr sigue respondiendo, dio {qr.status_code}")
    check(qr.content[:8] == b"\x89PNG\r\n\x1a\n",
          f"/api/link/qr sigue devolviendo un PNG, salió {qr.content[:16]!r}")


# ── 5. /api/n8n: exento del token del QR, pero con su propio secreto ─────────
async def _n8n() -> None:
    secreto = servidor.secreto_n8n()
    check(bool(secreto), "el secreto de n8n se genera al primer uso")
    # peer de Docker (no loopback), como lo ve nexus cuando n8n llama desde un
    # contenedor: no hay token del QR y el Host no es de loopback.
    DOCKER = {"host": "host.docker.internal:8177"}
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente("192.168.65.254") as c:
            r = await c.post("/api/n8n", headers={**DOCKER, CABECERA_N8N: secreto},
                             json={"text": "estado de instagram"})
        check(r.status_code == 200,
              f"n8n desde Docker con su secreto pasa (200), dio {r.status_code}")
        check(len(espia.llamadas) == 1,
              f"n8n desde Docker llega al cerebro una vez, llegó {len(espia.llamadas)}")
        if espia.llamadas:
            check(espia.llamadas[0]["source"] == "n8n",
                  f"n8n sigue entrando con source='n8n', entró {espia.llamadas[0]!r}")

        async with _cliente("192.168.65.254") as c:
            sin = await c.post("/api/n8n", headers=DOCKER,
                               json={"text": "estado de instagram"})
        check(sin.status_code == 401,
              f"n8n desde Docker SIN secreto → 401, dio {sin.status_code}")
        check(sin.json() == {"error": SIN_SECRETO_N8N},
              f"n8n sin secreto: cuerpo de error exacto, salió {sin.text[:120]!r}")
        check(len(espia.llamadas) == 1, "n8n sin secreto NO llega al cerebro")

        # el secreto no se sirve a quien no es este equipo, aunque tenga token
        async with _cliente("192.168.65.254") as c:
            s1 = await c.get("/api/n8n/secret", headers={**DOCKER, "x-nexus-token": TOK})
        check(s1.status_code == 403,
              f"/api/n8n/secret desde fuera (con token válido) → 403, dio {s1.status_code}")
        check(secreto not in s1.text,
              "/api/n8n/secret desde fuera NO filtra el secreto")

        async with _cliente("192.168.65.254") as c:
            s2 = await c.get("/api/n8n/secret", headers=DOCKER)
        check(s2.status_code == 401,
              f"/api/n8n/secret sin token ni secreto → 401, dio {s2.status_code}")

        # la exención es SOLO de /api/n8n: el resto sigue pidiendo el QR
        async with _cliente("192.168.65.254") as c:
            otra = await c.get("/api/status", headers=DOCKER)
            con_token = await c.get("/api/status", headers={**DOCKER, "x-nexus-token": TOK})
        check(otra.status_code == 401,
              f"la exención no se contagia: /api/status desde fuera → 401, dio {otra.status_code}")
        check(con_token.status_code == 200,
              f"y con el token del QR sigue entrando, dio {con_token.status_code}")

    # desde loopback el handler sigue siendo la autoridad: el secreto se exige igual
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente() as c:
            local = await c.post("/api/n8n", headers={CABECERA_N8N: secreto},
                                 json={"text": "estado de instagram"})
            check(local.status_code == 200,
                  f"/api/n8n desde este equipo con secreto → 200, dio {local.status_code}")
            sin_local = await c.post("/api/n8n", json={"text": "estado de instagram"})
            check(sin_local.status_code == 401,
                  f"/api/n8n desde este equipo SIN secreto → 401, dio {sin_local.status_code}")
            # Host ajeno + loopback: la ruta sigue exenta, el secreto decide
            ajeno = await c.post("/api/n8n", headers={"host": "evil.example:8177",
                                                      CABECERA_N8N: secreto},
                                 json={"text": "estado de instagram"})
            check(ajeno.status_code == 200,
                  f"/api/n8n con Host ajeno y secreto correcto → 200, dio {ajeno.status_code}")
            # La exención es la ruta EXACTA: con barra final no se hereda.
            barra = await c.post("/api/n8n/", headers={CABECERA_N8N: secreto},
                                 json={"text": "estado de instagram"})
            check(barra.status_code != 200,
                  f"/api/n8n/ no debe heredar la exención, dio {barra.status_code}")


# ── 6. Rutas públicas: el QR tiene que poder vincularse desde cualquier Host ──
async def _publicas() -> None:
    for peer, host, etiqueta in (("127.0.0.1", "evil.example:8177", "loopback con Host ajeno"),
                                 ("203.0.113.9", "casa.example", "un aparato de fuera")):
        async with _cliente(peer) as c:
            for ruta in ("/m", "/static/js/command.js", "/sw.js"):
                r = await c.get(ruta, headers=_cab(host=host))
                check(r.status_code == 200,
                      f"{ruta} sigue siendo público ({etiqueta}), dio {r.status_code}")

    # «Pública» es la ruta EXACTA, no un prefijo. Con «/m» como prefijo cualquier
    # «/m…» se saltaba el middleware: hoy sería un 404 inofensivo, pero una ruta
    # futura «/movil/…» habría nacido sin autenticar sin que nadie lo eligiera.
    async with _cliente("203.0.113.9") as c:
        for ruta in ("/mnada", "/movil/algo", "/static"):
            r = await c.get(ruta, headers=_cab(host="casa.example"))
            check(r.status_code == 401,
                  f"{ruta} NO es pública ({r.status_code})")


# ── 7. El WebSocket no cambia: mismo Host/Origin, mismo token ────────────────
def _websocket() -> None:
    from unittest.mock import patch

    # Se carga el handler de verdad sin arrancar nada: mismo truco que
    # test_acceso_remoto.py (no hay servidor ni puerto).
    nombres = ("websocket_endpoint", "_trusted_local_ws_origin",
               "_parsea_host_local", "_origen_coincide")

    def _constante(nodo) -> bool:
        """Constantes de módulo (`_LOOPBACK` y compañía), sin ejecutar el módulo."""
        if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
            return False
        objetivo = nodo.targets[0]
        return (isinstance(objetivo, ast.Name) and objetivo.id.startswith("_")
                and isinstance(nodo.value, (ast.Constant, ast.List, ast.Tuple, ast.Set)))

    tree = ast.parse((ROOT / "backend" / "app.py").read_text(encoding="utf-8"))
    nodos = [n for n in tree.body
             if ((isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in nombres)
                 or _constante(n))]
    endpoint = next((n for n in nodos if getattr(n, "name", "") == "websocket_endpoint"), None)
    if not check(endpoint is not None, "no encuentro websocket_endpoint en backend/app.py"):
        return
    endpoint.decorator_list = []

    class FakeBus:
        history: list = []

        def __init__(self):
            self.clients = set()

        def register(self, ws):
            self.clients.add(ws)

        def unregister(self, ws):
            self.clients.discard(ws)

        def replay(self, n=30, chats=20):
            return []

    namespace = {"asyncio": asyncio, "json": json, "WebSocket": object,
                 "WebSocketDisconnect": type("WebSocketDisconnect", (Exception,), {}),
                 "bus": FakeBus()}
    exec(compile(ast.Module(body=nodos, type_ignores=[]), "backend/app.py", "exec"), namespace)

    remote_falso = types.ModuleType("backend.core.infraestructura.remote")
    remote_falso.link_token = lambda: "fixture-qr-token"
    paquetes = {}
    for nombre in ("backend", "backend.core", "backend.core.infraestructura"):
        paquete = types.ModuleType(nombre)
        paquete.__path__ = []
        paquetes[nombre] = paquete

    class Cab(dict):
        def get(self, k, default=""):
            for kk, vv in self.items():
                if kk.lower() == str(k).lower():
                    return vv
            return default

    class FakeWS:
        def __init__(self, host, origin, *, client="127.0.0.1", token="", forwarded=None):
            cab = {"host": host}
            if origin is not None:
                cab["origin"] = origin
            cab.update(forwarded or {})
            self.headers = Cab(cab)
            self.client = types.SimpleNamespace(host=client)
            self.query_params = {"token": token}
            self.accepted = False
            self.closed = None

        async def accept(self):
            self.accepted = True

        async def close(self, code):
            self.closed = code

        async def receive_text(self):
            raise namespace["WebSocketDisconnect"]()

    async def probe(host, origin, **kw):
        ws = FakeWS(host, origin, **kw)
        with patch.dict(sys.modules, {**paquetes,
                                      "backend.core.infraestructura.remote": remote_falso}):
            await namespace["websocket_endpoint"](ws)
        return ws

    async def casos():
        # Origin ajeno desde loopback: cerrado antes del accept (igual que antes)
        for host, origin in (("127.0.0.1:8177", "https://evil.example"),
                             ("127.0.0.1:8177", "http://evil.example:8177"),
                             ("evil.example:8177", "http://evil.example:8177"),
                             ("127.0.0.1:8177@evil.example:8177", "http://127.0.0.1:8177"),
                             ("127.0.0.1:8177", "http://127.0.0.1:9999")):
            ws = await probe(host, origin)
            check(not ws.accepted and ws.closed is not None,
                  f"WS sin token: Host/Origin {host!r}/{origin!r} se rechaza antes del accept")
        # el HUD de verdad
        for host, origin in (("127.0.0.1:8177", "http://127.0.0.1:8177"),
                             ("localhost:8177", "http://localhost:8177"),
                             ("[::1]:8177", "http://[::1]:8177")):
            ws = await probe(host, origin)
            check(ws.accepted, f"WS del HUD con Origin {origin!r} entra")
        # cliente nativo local sin Origin: necesita token, y con él entra
        ws = await probe("127.0.0.1:8177", None)
        check(not ws.accepted and ws.closed is not None,
              "WS local sin Origin y sin token se rechaza (cliente nativo)")
        ws = await probe("127.0.0.1:8177", None, token="fixture-qr-token")
        check(ws.accepted, "WS local sin Origin pero con token entra")
        ws = await probe("127.0.0.1:8177", None, token="malo")
        check(not ws.accepted and ws.closed is not None,
              "WS local sin Origin y con token inválido se rechaza")
        # móvil por túnel / LAN con su token
        ws = await probe("tunnel.example", "https://mobile.example",
                         token="fixture-qr-token",
                         forwarded={"Cf-Connecting-Ip": "203.0.113.9"})
        check(ws.accepted, "WS del móvil por el túnel con token entra")
        ws = await probe("192.168.1.5:8177", "http://mobile.example",
                         client="192.168.1.77", token="fixture-qr-token")
        check(ws.accepted, "WS del móvil por la WiFi con token entra")
        ws = await probe("127.0.0.1:8177", "http://127.0.0.1:8177",
                         forwarded={"X-Forwarded-For": "192.0.2.9"})
        check(not ws.accepted and ws.closed is not None,
              "WS con cabecera de proxy no se cree local")

    asyncio.run(casos())


async def main() -> None:
    await _host_ajeno()
    await _origin()
    await _proxy()
    await _token()
    await _n8n()
    await _publicas()


asyncio.run(main())
_websocket()

print(f"\n{'#' * 54}\ntest_host_origin: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
