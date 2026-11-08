# -*- coding: utf-8 -*-
"""UN TOKEN POR DISPOSITIVO, CON REVOCACIÓN INDIVIDUAL (P3-2, task T21).

Qué había antes, y por qué esto existe
--------------------------------------
La vinculación del móvil usaba UN SOLO secreto compartido (`link_token`): el que
llevaba el QR, el que comparaba `remote_auth`, el que miraba el WebSocket y el
que se guardaba en el `localStorage` del teléfono. Consecuencia doble:

  * `POST /api/link/reset` (`rotate_token()`) desvinculaba **todos** los móviles
    a la vez: perder un teléfono obligaba a re-vincular hasta el que estaba en
    la mano.
  * un token filtrado en un móvil valía desde cualquier sitio de la LAN o del
    túnel, y no había forma de acotarlo a ese aparato (auditoría 04 §3).

Ahora: el QR entrega un **código de vinculación** de un solo uso y corto de
vida; el móvil lo canjea UNA vez en `POST /api/link/pair` y recibe un token
**propio**, que se guarda en `data/dispositivos.json` como **digesto sha256**
(nunca en claro: nada que el HUD lea puede devolver la credencial). `POST
/api/link/revoke {id}` mata uno; `/api/link/reset` sigue matando todo y además
rota el código.

DECISIÓN DE COMPATIBILIDAD: (a), con periodo de gracia. El token compartido de
siempre SIGUE valiendo, porque los teléfonos ya instalados lo tienen en su
`localStorage` y el `movil/MainActivity.java` lo lleva pegado en cada dirección
que guarda: cerrarlo de golpe los dejaría fuera sin que nadie pudiera explicarlo.
El HUD lo enseña como «dispositivo antiguo» y el dueño lo apaga revocándolo (o
con «Desvincular»). Está escrito en el comentario de `remote.revoke_device`.

TODO va EN PROCESO (`httpx.ASGITransport`, que NO ejecuta `lifespan`) y con
`config/` y `data/` de usar y tirar puestas ANTES de importar el backend: ni
uvicorn, ni puertos, ni el `settings.json`/`secrets.json` del operador. Ningún
test imprime un token completo: si hay que nombrarlo, va enmascarado.

Ejecutar:  .venv\\Scripts\\python.exe tests\\integration\\http\\test_vinculacion_dispositivos.py
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar backend: ni config ni data del operador.
_CFG = tempfile.mkdtemp(prefix="nexus_vinc_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_vinc_data_")
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
TOK = "token-compartido-de-prueba-P3-2"        # el de siempre (gracia)
settings.set_secret("link_token", TOK)
CERRADO = {"error": "no autorizado — vincula el móvil con el QR de nexus"}
HUD = "127.0.0.1:8177"
TIENDA = Path(_DATA) / "dispositivos.json"
ALFABETO = re.compile(r"^[A-HJ-NP-Z2-9]{8}$")     # sin 0/O/1/I/L: no se confunde
OTRA_RED = "203.0.113.9"                          # peer de fuera, como el túnel


def _mascara(t: str) -> str:
    """Nunca se imprime un token entero: primeros 4 y `***`."""
    t = str(t or "")
    return t[:4] + "***" if t else "(vacío)"


def _cliente(peer: str = "127.0.0.1") -> httpx.AsyncClient:
    transporte = httpx.ASGITransport(app=APP, client=(peer, 4321))
    return httpx.AsyncClient(transport=transporte, base_url=f"http://{HUD}")


def _cab(host: str = "casa.example", token: str = "", extra: dict | None = None) -> dict:
    cab: dict = {"host": host}
    if token:
        cab["x-nexus-token"] = token
    cab.update(extra or {})
    return cab


class _Espia:
    """Sustituto de brain.process: apunta la llamada y contesta algo inocuo."""

    def __init__(self):
        self.llamadas: list = []

    async def __call__(self, text, source="text", **kw):
        self.llamadas.append({"text": text, "source": source, **kw})
        return {"reply": "eco de prueba", "skill": None, "provider": "espia", "data": None}


class _Doble:
    def __init__(self, obj, nombre, valor):
        self.obj, self.nombre, self.valor = obj, nombre, valor

    def __enter__(self):
        self.previo = getattr(self.obj, self.nombre)
        setattr(self.obj, self.nombre, self.valor)
        return self.valor

    def __exit__(self, *_exc):
        setattr(self.obj, self.nombre, self.previo)
        return False


class _Red:
    """`remote.status()` de verdad, sin tocar la red."""

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


async def _estado() -> dict:
    with _Red():
        async with _cliente() as c:
            r = await c.get("/api/link/status", headers={"host": HUD})
    check(r.status_code == 200, f"/api/link/status responde, dio {r.status_code}")
    return r.json() if r.status_code == 200 else {}


def _codigo_del_qr(st: dict) -> str:
    """El código de vinculación que lleva el QR (parámetro `token` del enlace)."""
    enlace = str(st.get("link") or "")
    return parse_qs(urlparse(enlace).query).get("token", [""])[0]


async def _empareja(nombre: str = "Móvil de prueba", did: str = "",
                    codigo: str | None = None) -> dict:
    """Canjea el código vigente por un token propio. Devuelve el JSON."""
    if codigo is None:
        codigo = _codigo_del_qr(await _estado())
    async with _cliente(OTRA_RED) as c:
        r = await c.post("/api/link/pair", headers={"host": "casa.example"},
                         json={"codigo": codigo, "id": did or "", "name": nombre})
    try:
        cuerpo = r.json()
    except Exception:                                          # noqa: BLE001
        cuerpo = {}
    if not isinstance(cuerpo, dict):
        cuerpo = {}
    cuerpo.setdefault("_status", r.status_code)
    cuerpo["_texto"] = r.text[:200]
    return cuerpo


def _fichas() -> list:
    try:
        d = json.loads(TIENDA.read_text(encoding="utf-8")) or {}
        return list(d.get("dispositivos") or [])
    except Exception:                                          # noqa: BLE001
        return []


# ── 1. El CÓDIGO del QR: forma, un solo uso, caducidad, tiempo constante ──────
async def _codigo() -> None:
    st = await _estado()
    codigo = _codigo_del_qr(st)
    check(ALFABETO.match(codigo) is not None,
          f"el QR lleva un código de vinculación de 8 caracteres sin equívocos, "
          f"salió {codigo!r}")
    check(codigo != TOK,
          "el QR ya NO lleva el token compartido de siempre: lleva un código de un solo uso")
    check(codigo == remote.pairing_code(),
          "el código del QR es el vigente (pedirlo otra vez no lo cambia: si cambiara "
          "en cada refresco, el del dueño dejaría de valer solo)")
    check(len(re.findall(re.escape(codigo), json.dumps(st))) == 1,
          "el código aparece UNA vez en el estado: nadie más lo reparte")

    # un código equivocado no vale, y no crea ningún dispositivo
    antes = len(_fichas())
    malo = await _empareja("Intruso", codigo=("ZZZZZZZZ" if codigo != "ZZZZZZZZ" else "YYYYYYYY"))
    check(malo.get("_status") == 403,
          f"un código equivocado se rechaza con 403, dio {malo.get('_status')}")
    check("código" in str(malo.get("error", "")).lower(),
          f"y el error lo explica en español: {malo.get('error')!r}")
    check(len(_fichas()) == antes, "un código equivocado no crea ningún dispositivo")

    # camino de comparación en TIEMPO CONSTANTE (no un `!=`)
    class _HmacEspia:
        def __init__(self):
            import hmac as _real
            self._real, self.llamadas = _real, []

        def compare_digest(self, a, b):
            self.llamadas.append(1)
            return self._real.compare_digest(a, b)

    espia = _HmacEspia()
    # El espía va en `secretos`, no en `remote`: desde T21 la comparación en
    # tiempo constante del código de vinculación vive en
    # `comun/secretos.py::mismo_secreto` (comparar en BYTES para que un código
    # escrito a mano con ñ no tire un 500). Lo que se comprueba sigue siendo lo
    # mismo: que se llama a `hmac.compare_digest` y no a `==`.
    from backend.core.comun import secretos as _secretos_mod
    with _Doble(_secretos_mod, "hmac", espia):
        await _empareja("Intruso 2", codigo="AAAAAAAA")
        await _empareja("Intruso 3", codigo="AAAAAAAB")
    check(len(espia.llamadas) >= 1,
          "el código se compara con hmac.compare_digest, no con == (adivinarlo carácter "
          f"a carácter midiendo el tiempo no debe ser posible; llamadas: {len(espia.llamadas)})")

    # CADUCIDAD: pasada la TTL de config/umbrales.json el código muere y no revive
    codigo2 = _codigo_del_qr(await _estado())
    base = remote._ahora()
    with _Doble(remote, "_ahora", lambda: base + remote.ttl_codigo_segundos() + 1):
        caducado = await _empareja("Tarde", codigo=codigo2)
        check(caducado.get("_status") == 403,
              f"un código caducado se rechaza con 403, dio {caducado.get('_status')}")
        nuevo = remote.pairing_code()
        check(nuevo != codigo2,
              "caducado el código, el siguiente que se saca es DISTINTO (no revive)")
    check(remote.ttl_codigo_segundos() > 0,
          "la TTL del código sale de config/umbrales.json (sección «vinculacion»), "
          "y nunca es 0: sin caducidad no hay código de un solo uso")

    # UN SOLO USO: el mismo código no acuña un segundo token
    ok = await _empareja("Móvil uno")
    check(ok.get("_status") == 200,
          f"el código correcto se canjea (200), dio {ok.get('_status')} {ok.get('_texto', '')}")
    token = str(ok.get("token") or "")
    check(bool(token) and token != codigo,
          f"el canje devuelve un token PROPIO distinto del código ({_mascara(token)})")
    check(len(token) >= 32,
          f"el token propio tiene entropía de token, no de código (largo {len(token)})")
    fichas = _fichas()
    check(len(fichas) == 1, f"queda UN dispositivo vinculado, hay {len(fichas)}")
    otra_vez = await _empareja("Móvil dos", codigo=codigo)
    check(otra_vez.get("_status") == 403,
          f"el MISMO código no se puede canjear dos veces, dio {otra_vez.get('_status')}")
    check(len(_fichas()) == 1,
          f"y no ha acuñado un segundo token: hay {len(_fichas())} dispositivos")
    return token


# ── 2. El token propio autentica HTTP: query, cabecera y cookie ──────────────
async def _http(token: str) -> None:
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente(OTRA_RED) as c:
            por_cabecera = await c.post("/api/command", headers=_cab(token=token),
                                        json={"text": "hola"})
            check(por_cabecera.status_code == 200,
                  f"el token propio autentica POST /api/command por cabecera, "
                  f"dio {por_cabecera.status_code}")
            check(por_cabecera.cookies.get("nexus_token") == token,
                  "y deja la cookie nexus_token de siempre")
            por_cookie = await c.post("/api/command", headers=_cab(), json={"text": "hola"})
            check(por_cookie.status_code == 200,
                  f"la cookie nexus_token con el token propio autentica, "
                  f"dio {por_cookie.status_code}")
            por_query = await c.post(f"/api/command?token={token}", headers=_cab(),
                                     json={"text": "hola"})
            check(por_query.status_code == 200,
                  f"el token propio autentica por ?token= (la forma que usaba el móvil), "
                  f"dio {por_query.status_code}")
            estado = await c.get(f"/api/link/status?token={token}", headers=_cab())
            check(estado.status_code == 200,
                  f"y también /api/link/status, dio {estado.status_code}")
    check(len(espia.llamadas) == 3,
          f"el cerebro se toca una vez por orden autenticada (3), se tocó {len(espia.llamadas)}")


# ── 3. El MISMO token propio autentica el WebSocket ──────────────────────────
def _websocket(token: str) -> None:
    """Handler real cargado sin arrancar nada (no hay servidor ni puerto).

    El módulo `remote` NO se dobla aquí a propósito: lo que se prueba es que el
    token de la tienda de dispositivos entra por el mismo sitio donde antes solo
    entraba el token compartido."""
    from backend.core.comun.events import bus as bus_real

    nombres = ("websocket_endpoint", "_trusted_local_ws_origin",
               "_parsea_host_local", "_origen_coincide",
               # T8e: el handler deriva el canal con estos tres, así que el
               # handler extraído por AST sigue entero (si no, un mensaje
               # «command» daría NameError aquí y no en producción).
               "_es_este_equipo", "_valores_cabecera", "_canal_efectivo")

    def _constante(nodo) -> bool:
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

    class FakeWS:
        def __init__(self, token):
            self.headers = {"host": "casa.example"}
            self.client = types.SimpleNamespace(host=OTRA_RED)
            self.query_params = {"token": token}
            self.accepted = False
            self.closed = None

        async def accept(self):
            self.accepted = True

        async def close(self, code):
            self.closed = code

        async def receive_text(self):
            raise namespace["WebSocketDisconnect"]()

    async def probe(tok):
        ws = FakeWS(tok)
        await namespace["websocket_endpoint"](ws)
        return ws

    async def casos():
        ws = await probe(token)
        check(ws.accepted and ws.closed is None,
              f"el WebSocket del móvil con su token PROPIO entra (token {_mascara(token)})")
        ws = await probe("token-de-dispositivo-que-no-existe")
        check(not ws.accepted and ws.closed == 4401,
              f"un token de dispositivo desconocido se cierra con 4401 "
              f"(aceptado={ws.accepted}, código={ws.closed})")
        # BLOQUEO ENCONTRADO POR EL VERIFICADOR (T21): comparar con `str` lanza
        # TypeError si el intento trae no-ASCII, y el 500 sustituía al 4401.
        ws = await probe("ññññññññ")
        check(not ws.accepted and ws.closed == 4401,
              f"un token NO-ASCII en el WebSocket se cierra con 4401, no revienta "
              f"(aceptado={ws.accepted}, código={ws.closed})")
        ws = await probe("“token”")
        check(not ws.accepted and ws.closed == 4401,
              f"un token con comillas tipográficas se cierra con 4401 (código={ws.closed})")

    asyncio.run(casos())


# ── 4. DECISIÓN (a): el token COMPARTIDO de siempre sigue valiendo ───────────
async def _gracia() -> None:
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente(OTRA_RED) as c:
            r = await c.post("/api/command", headers=_cab(token=TOK), json={"text": "hola"})
            check(r.status_code == 200,
                  f"un móvil ANTIGUO (token compartido) sigue entrando, dio {r.status_code}")
            check(r.cookies.get("nexus_token") == TOK,
                  "y su cookie sigue siendo la de siempre")
            malo = await c.post("/api/command", headers=_cab(token=TOK + "x"),
                                json={"text": "hola"})
            check(malo.status_code == 401,
                  f"un token compartido equivocado sigue sin colar, dio {malo.status_code}")
        # cliente NUEVO sin cookie: lo que se prueba es «sin credencial ninguna»
        async with _cliente(OTRA_RED) as c:
            cerrado = await c.post("/api/command", headers=_cab(), json={"text": "hola"})
            check(cerrado.status_code == 401,
                  f"sin credencial sigue cerrado, dio {cerrado.status_code}")
            check(cerrado.json() == CERRADO,
                  f"y el 401 dice lo mismo de siempre: {cerrado.text[:90]!r}")
    check(len(espia.llamadas) == 1, "solo la orden con credencial válida llega al cerebro")

    st = await _estado()
    check(TOK not in json.dumps(st),
          "/api/link/status NO devuelve el token compartido (SEC-03 sigue cerrado)")
    check("token=" in str(st.get("link", "")),
          "el enlace del QR sigue llevando su credencial en `token=` (el código)")


# ── 5. revoke {id}: mata UNO y deja los demás ────────────────────────────────
async def _revocar(token_a: str) -> None:
    # dos dispositivos, cada uno con su token
    a = await _empareja("Móvil A", did="dev-a")
    b = await _empareja("Móvil B", did="dev-b")
    tok_a, tok_b = str(a.get("token") or ""), str(b.get("token") or "")
    check(a.get("_status") == 200 and b.get("_status") == 200,
          f"los dos móviles se emparejan (A={a.get('_status')}, B={b.get('_status')})")
    check(a.get("id") == "dev-a" and b.get("id") == "dev-b",
          "cada token va atado al id que manda el móvil")

    async def _entra(tok: str) -> int:
        async with _cliente(OTRA_RED) as c:
            r = await c.get("/api/link/status", headers=_cab(token=tok))
        return r.status_code

    check(await _entra(tok_a) == 200 and await _entra(tok_b) == 200,
          "antes de revocar, los dos tokens entran")
    async with _cliente(OTRA_RED) as c:
        r = await c.post("/api/link/revoke", headers=_cab(token=tok_b), json={"id": "dev-a"})
    check(r.status_code == 200,
          f"POST /api/link/revoke responde 200, dio {r.status_code} {r.text[:120]!r}")
    check(r.json().get("revocado") is True, f"y dice que revocó: {r.text[:140]!r}")
    check(await _entra(tok_a) == 401,
          f"el token revocado deja de valer (401), dio {await _entra(tok_a)}")
    check(await _entra(tok_b) == 200,
          f"y el OTRO móvil sigue funcionando, dio {await _entra(tok_b)}")
    check(await _entra(TOK) == 200,
          "el token compartido (móviles antiguos) no se toca al revocar un dispositivo nuevo")
    ids = [str(f.get("id")) for f in _fichas()]
    check("dev-a" not in ids and "dev-b" in ids,
          f"la tienda queda con el que sobrevive: {ids}")

    # un id que no existe NO cambia nada (ni rota el token compartido)
    async with _cliente(OTRA_RED) as c:
        r = await c.post("/api/link/revoke", headers=_cab(token=tok_b),
                         json={"id": "no-existe"})
    check(r.status_code == 404,
          f"revocar un id desconocido da 404, dio {r.status_code}")
    check(await _entra(tok_b) == 200 and await _entra(TOK) == 200,
          "y no ha tocado ni al otro dispositivo ni al token compartido")

    # el «dispositivo antiguo»: se apaga revocándolo (decisión (a))
    remote.register_device({"id": "viejo-1", "name": "Móvil viejo", "antiguo": True})
    st = await _estado()
    fichas = {str(v.get("id")): v for v in (st.get("vinculados") or [])}
    check("viejo-1" in fichas,
          f"/api/link/status enseña el dispositivo antiguo para poder revocarlo: {list(fichas)}")
    check(fichas.get("viejo-1", {}).get("antiguo") is True,
          "y lo marca como «antiguo» (usa el token compartido, no uno propio)")
    async with _cliente(OTRA_RED) as c:
        r = await c.post("/api/link/revoke", headers=_cab(token=tok_b),
                         json={"id": "viejo-1"})
    check(r.status_code == 200, f"revocar el dispositivo antiguo responde 200, dio {r.status_code}")
    check(r.json().get("antiguo") is True,
          f"y dice que era el token COMPARTIDO el que se ha cerrado: {r.text[:160]!r}")
    check(await _entra(TOK) == 401,
          f"el token compartido deja de valer en cuanto el dueño lo revoca, "
          f"dio {await _entra(TOK)}")
    check(await _entra(tok_b) == 200,
          "y los dispositivos con token propio siguen dentro")
    settings.set_secret("link_token", TOK)         # se devuelve el de la prueba


# ── 6. reset: mata TODO y rota el código ────────────────────────────────────
async def _reset() -> None:
    c = await _empareja("Móvil C", did="dev-c")
    tok_c = str(c.get("token") or "")
    codigo_antes = _codigo_del_qr(await _estado())
    check(bool(tok_c), "hay un dispositivo emparejado antes del reset")
    async with _cliente(OTRA_RED) as cx:
        r = await cx.post("/api/link/reset", headers=_cab(token=tok_c))
    check(r.status_code == 200, f"/api/link/reset responde 200, dio {r.status_code}")
    check((r.json() or {}).get("reset", {}).get("ok") is True,
          f"y dice qué ha desvinculado: {r.text[:120]!r}")
    async with _cliente(OTRA_RED) as cx:
        muerto = await cx.get("/api/link/status", headers=_cab(token=tok_c))
    check(muerto.status_code == 401,
          f"tras el reset el token de ese móvil ya no vale, dio {muerto.status_code}")
    check(_fichas() == [], f"la tienda queda vacía, hay {_fichas()}")
    st = await _estado()
    codigo_despues = _codigo_del_qr(st)
    check(codigo_despues != codigo_antes,
          "y el CÓDIGO de vinculación también se rota: el que estaba en el QR ya no vale")
    check(remote.canjear_codigo(codigo_antes) is False,
          "el código anterior al reset no se puede canjear")
    # PRESERVE: el token COMPARTIDO moría con «Desvincular» antes de P3-2 y tiene
    # que seguir muriendo (si no, el botón mentiría: «ya no vale nada»).
    async with _cliente(OTRA_RED) as cx:
        compartido = await cx.get("/api/link/status", headers=_cab(token=TOK))
    check(compartido.status_code == 401,
          f"el token COMPARTIDO de los móviles antiguos también muere con el reset, "
          f"dio {compartido.status_code}")
    check(ALFABETO.match(codigo_despues) is not None,
          f"el código nuevo tiene la misma forma: {codigo_despues!r}")


# ── 7. En disco no queda ningún token recuperable: hay DIGESTO ──────────────
async def _disco() -> None:
    d = await _empareja("Móvil D", did="dev-d")
    token = str(d.get("token") or "")
    check(bool(token), "hay un token que acaba de nacer para inspeccionar el archivo")
    check(TIENDA.is_file(), f"la tienda existe en data/ ({TIENDA.name})")
    crudo = TIENDA.read_bytes() if TIENDA.is_file() else b""
    texto = crudo.decode("utf-8", "replace")
    check(token.encode() not in crudo,
          f"el token NO está en claro en el archivo (token {_mascara(token)})")
    check(token[:12] not in texto,
          "ni siquiera un trozo reconocible del token está en el archivo")
    digesto = hashlib.sha256(token.encode()).hexdigest()
    check(digesto in texto,
          "y SÍ está su digesto sha256: se compara contra el digesto, no contra el token")
    check(re.search(r"[0-9a-f]{64}", texto) is not None,
          "el digesto tiene forma de sha256 hexadecimal")
    st = await _estado()
    check(digesto not in json.dumps(st),
          "el digesto tampoco sale por /api/link/status: el HUD no lee material de credencial")
    check(token not in json.dumps(st),
          "y el token, por supuesto, tampoco")


# ── 8. Un token de dispositivo no vincula; uno desconocido no entra ─────────
async def _fronteras() -> None:
    d = await _empareja("Móvil E", did="dev-e")
    token = str(d.get("token") or "")
    antes = len(_fichas())
    # el token propio NO es un código: no sirve para emparejar otro teléfono
    async with _cliente(OTRA_RED) as c:
        r = await c.post("/api/link/pair", headers={"host": "casa.example"},
                         json={"codigo": token, "id": "dev-x", "name": "Colado"})
    check(r.status_code == 403,
          f"un token de dispositivo no canjea un emparejamiento nuevo, dio {r.status_code}")
    check(len(_fichas()) == antes,
          f"y no ha creado ningún dispositivo ({antes} antes, {len(_fichas())} después)")
    async with _cliente(OTRA_RED) as c:
        r = await c.post("/api/link/pair", headers={"host": "casa.example"}, json={})
    check(r.status_code == 403, f"un canje vacío se rechaza, dio {r.status_code}")

    # el canje es la ÚNICA puerta sin credencial: el resto sigue cerrado
    async with _cliente(OTRA_RED) as c:
        for ruta in ("/api/status", "/api/jobs", "/api/config"):
            r = await c.get(ruta, headers={"host": "casa.example"})
            check(r.status_code == 401,
                  f"{ruta} sin credencial sigue en 401 (el canje no abre nada más), "
                  f"dio {r.status_code}")


# ── 9. El HUD tiene con qué pintar la revocación por dispositivo ────────────
async def _hud() -> None:
    await _empareja("Móvil F", did="dev-f")
    st = await _estado()
    check(isinstance(st.get("vinculados"), list) and st["vinculados"],
          f"/api/link/status trae «vinculados» con los dispositivos revocables: "
          f"{st.get('vinculados')!r}")
    ficha = (st.get("vinculados") or [{}])[0]
    for clave in ("id", "name", "antiguo"):
        check(clave in ficha, f"cada dispositivo trae «{clave}» para que el HUD lo pinte: {ficha}")
    check(all(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
              for v in ficha.values()),
          "y ninguna ficha lleva el digesto")
    # lo de siempre no cambia: `devices` son los conectados AHORA
    for clave in ("devices", "paired", "link", "hosts", "via", "estable", "tailscale", "lan"):
        check(clave in st, f"/api/link/status sigue trayendo «{clave}»")


async def main() -> None:
    token = await _codigo()
    await _http(token)
    await _gracia()
    await _revocar(token)
    await _reset()
    await _disco()
    await _fronteras()
    await _hud()
    await _no_ascii()


# ── ENTRADAS NO-ASCII: 401/403, nunca 500 (bloqueo del verificador de T21) ────
async def _no_ascii() -> None:
    """Un texto raro escrito por un humano no puede tumbar el middleware.

    `hmac.compare_digest` con `str` lanza TypeError fuera de ASCII. El efecto era
    un 500 en `remote_auth` (cualquier ruta), en el canje del QR y en el
    WebSocket: fallaba cerrado, pero una tecla rompía la frontera de toda la app.
    Se compara en BYTES (`secretos.mismo_secreto` / el inline del WS), así que un
    intento raro es simplemente UN INTENTO MÁS: 401 o 403.
    """
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente(OTRA_RED) as c:
            r = await c.get("/api/status", params={"token": "ññññññññ"})
            check(r.status_code == 401,
                  f"un ?token=ñ… debe dar 401, no 500 (dio {r.status_code})")
            r = await c.get("/api/status", params={"token": "“token”"})
            check(r.status_code == 401,
                  f"un token con comillas tipográficas debe dar 401 (dio {r.status_code})")
            r = await c.post("/api/link/pair",
                             json={"codigo": "ÑÑÑÑÑÑÑÑ", "id": "intruso", "name": "y"})
            check(r.status_code == 403,
                  f"un código NO-ASCII en el canje debe dar 403, no 500 (dio {r.status_code})")
            r = await c.post("/api/command", params={"token": "AAAÑ"},
                             json={"text": "hola"})
            check(r.status_code == 401,
                  f"una mezcla ascii/no-ascii debe dar 401 (dio {r.status_code})")
    check(espia.llamadas == [],
          f"ninguna de esas entradas llegó al cerebro, se llamó {espia.llamadas!r}")


asyncio.run(main())


# El WebSocket se prueba aparte: monta su propio bucle de asyncio (el handler se
# ejecuta aislado, como en `test_host_origin.py`), así que no puede colgar de
# `main()`. El token es nuevo porque `_reset()` ha tirado los de antes a propósito.
async def _token_para_el_ws() -> str:
    d = await _empareja("Móvil del WebSocket", did="dev-ws")
    return str(d.get("token") or "")


_websocket(asyncio.run(_token_para_el_ws()))

print(f"\n{'#' * 54}\ntest_vinculacion_dispositivos: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
