# -*- coding: utf-8 -*-
"""EL CANAL LO DECIDE LA CONEXIÓN, NO EL CUERPO — y los botones de casa (T8d/T8e).

Por qué existe esta suite
-------------------------
Desde T8c (`857eb37`) la columna de la matriz canal × efecto la elige el CANAL:
`canales.politica(source, channel, efecto, …)` permite desde `pc`, pregunta
desde `mobile`/`telegram` y deniega desde n8n. El canal dejó de ser una etiqueta
y pasó a ser la decisión. Dos agujeros que encontró el verificador de T8c:

  * **T8e** — `POST /api/command` leía `channel` del CUERPO. Un móvil vinculado
    (o cualquier cliente del túnel) que dijera `{"channel": "pc"}` obtenía la
    columna LOCAL: mandaba un correo o apagaba la tele sin el «sí» que el dueño
    pidió para los canales remotos (L59). La credencial dice «este teléfono puede
    mandar órdenes», no «este teléfono es el PC». Ahora el canal se deriva de la
    CONEXIÓN (`app._canal_efectivo` → `app._es_este_equipo`, la misma confianza
    local de SEC-03): solo el equipo del operador conserva el canal que pide el
    cliente; el resto entra como `mobile`. Vale para `/api/command`, para
    `/api/jobs` y para el WebSocket del HUD.

    Ojo con el túnel: cloudflared conecta DESDE loopback, así que «el peer es
    127.0.0.1» NO puede contar como local. Lo que lo delata es la cabecera
    `cf-connecting-ip`, que es lo primero que rechaza `_es_este_equipo`.

  * **T8d** — `/api/home/control` y `/api/home/scan` llaman a la skill de
    domótica directamente, fuera de `_autorizar_efecto`. DECISIÓN DEL DUEÑO
    (T8d, escrita también en README y en `docs/MOBILE.md`): un botón de casa NO
    es texto libre que cae en el enrutador de regexes que ARQ-03 vigila, así que
    pincharlo ES la acción explícita del operador — el toque cuenta como el
    «sí» y la llamada sigue siendo directa. Lo que sí se exige y aquí se fija:
    (1) sin confianza local ni token de dispositivo no se llega (401), (2) el
    secreto de n8n NO es una credencial para estas rutas, y (3) CADA llamada
    deja su línea en `data/logs/audit.jsonl` con el canal derivado.

TODO va EN PROCESO: `httpx.ASGITransport` (que NO ejecuta `lifespan`: ni uvicorn,
ni puertos, ni micrófono, ni Telegram) y el WebSocket con el handler REAL llamado
a mano sobre un doble (no abre socket). `brain.process` va doblado y
`domotica.control_api`/`scan_api` son espías: no se toca ninguna TV, ni la red
local, ni Home Assistant. Config y datos viven en carpetas de usar y tirar
puestas ANTES de importar el backend.

Ejecutar:  .venv\\Scripts\\python.exe tests\\integration\\http\\test_canal_conexion.py
"""
from __future__ import annotations

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

# ANTES de importar backend: ni config/settings.json, ni config/secrets.json, ni
# data/ del operador. Y sin `.env` (T44), para que no entren claves ni NEXUS_DB_URL.
_CFG = tempfile.mkdtemp(prefix="nexus_canal_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_canal_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA
os.environ["NEXUS_DOTENV"] = "0"
for _env in ("NEXUS_N8N_SECRET", "N8N_SECRET"):
    os.environ.pop(_env, None)

import httpx                                                    # noqa: E402
from fastapi import WebSocketDisconnect                         # noqa: E402

from backend.core.comun import audit                            # noqa: E402
from backend.core.comun import events                           # noqa: E402
from backend.core.comun.config import settings                  # noqa: E402
from backend.core.aplicacion import brain                       # noqa: E402
from backend.core.aplicacion import skills_loader               # noqa: E402
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
BUS = events.bus
HUD = "127.0.0.1:8177"          # el HUD de verdad (backend/desktop.py)
CASA = "192.168.1.50:8177"
PUBLICO = "nexus-de-prueba.trycloudflare.com"
OTRA_RED = "203.0.113.9"        # peer de fuera / WiFi / Docker
CERRADO = {"error": "no autorizado — vincula el móvil con el QR de nexus"}

# Credenciales de mentira, en la config de usar y tirar: el token COMPARTIDO del
# período de gracia (lo que llevan los teléfonos ya instalados) y el token PROPIO
# de un dispositivo emparejado por el camino real.
TOK_COMPARTIDO = "token-compartido-de-prueba-T8e"
settings.set_secret("link_token", TOK_COMPARTIDO)
_FICHA = remote.pair_device(remote.pairing_code(), "d-T8e", "Móvil de prueba")
TOK_DEV = (_FICHA or {}).get("token", "")
check(bool(TOK_DEV), "se puede emparejar un dispositivo de prueba (token propio)")


def _mascara(t: str) -> str:
    """Ningún token se imprime entero: primeros 4 y `***`."""
    t = str(t or "")
    return t[:4] + "***" if t else "(vacío)"


def _cliente(peer: str = "127.0.0.1") -> httpx.AsyncClient:
    """Cliente ASGI en proceso con un peer concreto (el de casa o uno de fuera)."""
    transporte = httpx.ASGITransport(app=APP, client=(peer, 4321))
    return httpx.AsyncClient(transport=transporte, base_url=f"http://{HUD}")


def _cab(host: str = HUD, *, origin: str | None = None, token: str = "",
         extra: dict | None = None) -> dict:
    cab: dict = {"host": host}
    if origin is not None:
        cab["origin"] = origin
    if token:
        cab["x-nexus-token"] = token
    cab.update(extra or {})
    return cab


class _Espia:
    """Sustituto de `brain.process`: apunta (text, source, channel) y contesta algo
    inocuo. Es lo que deja ver QUÉ canal recibe el cerebro."""

    def __init__(self):
        self.llamadas: list = []

    async def __call__(self, text, source="text", **kw):
        self.llamadas.append({"text": text, "source": source, **kw})
        return {"reply": "eco de prueba", "skill": None, "provider": "espia", "data": None}

    @property
    def canales(self) -> list:
        return [c.get("channel") for c in self.llamadas]


class _EspiaCasa:
    """Espía de `domotica.control_api` / `scan_api`: cuenta llamadas, no toca nada."""

    def __init__(self, respuesta: dict | None = None):
        self.llamadas: list = []
        self.respuesta = respuesta or {"ok": True, "reply": "hecho de prueba"}

    async def __call__(self, ctx, payload=None):
        self.llamadas.append(payload if payload is not None else dict(ctx or {}))
        return self.respuesta


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


def _skills_domotica(**metodos):
    """Registro de skills con UNA domótica cuyos métodos son los espías."""
    modulo = types.SimpleNamespace(**metodos)

    def _get_skills(_cache={}):
        return {"domotica": types.SimpleNamespace(module=modulo)}
    return _get_skills


def _lineas_audit() -> list[dict]:
    """Lo escrito en el registro de auditoría (el de la carpeta de usar y tirar)."""
    try:
        crudo = audit.AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:                                          # noqa: BLE001
        return []
    fuera = []
    for linea in crudo:
        try:
            fuera.append(json.loads(linea))
        except Exception:                                      # noqa: BLE001
            continue
    return fuera


# ══════════════════════════════════════════════════════════════════════════════
#  1. POST /api/command — el canal sale de la CONEXIÓN (T8e)
# ══════════════════════════════════════════════════════════════════════════════
async def _manda(peer: str, host: str, *, token: str = "", canal: str,
                 extra: dict | None = None) -> tuple[int, _Espia, str]:
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente(peer) as c:
            r = await c.post("/api/command",
                             headers=_cab(host, token=token, extra=extra),
                             json={"text": "hola", "channel": canal})
    return r.status_code, espia, r.text[:200]


async def _command() -> None:
    # ── Este equipo: el canal que pide el cliente se respeta (comportamiento de
    #    siempre: el HUD del PC no cambia).
    for canal, esperado in (("pc", "pc"), ("mobile", "mobile")):
        st, espia, txt = await _manda("127.0.0.1", HUD, canal=canal)
        check(st == 200, f"/api/command local con channel={canal}: 200, dio {st} ({txt})")
        check(espia.canales == [esperado],
              f"/api/command local con channel={canal}: el cerebro recibe «{esperado}», "
              f"recibió {espia.canales}")
    # Y con `Origin` de la misma autoridad (lo que manda un navegador de verdad).
    st, espia, txt = await _manda("127.0.0.1", HUD, canal="pc",
                                  extra={"origin": f"http://{HUD}"})
    check(st == 200 and espia.canales == ["pc"],
          f"/api/command local con Origin propio: 200 y «pc», dio {st} {espia.canales} ({txt})")

    # ── Token PROPIO de un dispositivo (WiFi o túnel): diga lo que diga el
    #    cuerpo, el canal es el remoto.
    for canal in ("pc", "telegram"):
        st, espia, txt = await _manda(OTRA_RED, CASA, token=TOK_DEV, canal=canal)
        check(st == 200, f"/api/command con token de dispositivo ({_mascara(TOK_DEV)}) "
                          f"y channel={canal}: 200, dio {st} ({txt})")
        check(espia.canales == ["mobile"],
              f"/api/command con token de dispositivo y channel={canal}: el cerebro "
              f"recibe «mobile», recibió {espia.canales}")

    # ── Token COMPARTIDO del período de gracia (el móvil antiguo): igual.
    st, espia, _txt = await _manda(OTRA_RED, CASA, token=TOK_COMPARTIDO, canal="pc")
    check(st == 200 and espia.canales == ["mobile"],
          f"/api/command con el token compartido y channel=pc: «mobile», "
          f"dio {st} {espia.canales}")

    # ── Forma del TÚNEL: cloudflared conecta DESDE loopback y añade
    #    `cf-connecting-ip`. Ese peer no puede contar como este equipo.
    espia = _Espia()
    doble_log = _Espia_log()
    with _Doble(brain, "process", espia), _Doble(BUS, "emit_sync", doble_log):
        async with _cliente("127.0.0.1") as c:
            r = await c.post("/api/command",
                             headers=_cab(PUBLICO, token=TOK_COMPARTIDO,
                                          extra={"cf-connecting-ip": OTRA_RED}),
                             json={"text": "hola", "channel": "pc"})
    check(r.status_code == 200, f"/api/command por el túnel con token: 200, dio {r.status_code}")
    check(espia.canales == ["mobile"],
          f"/api/command por el túnel (peer loopback + cf-connecting-ip) con "
          f"channel=pc: «mobile», recibió {espia.canales}")
    check(len(doble_log.llamadas) == 1,
          f"se apunta UNA vez que se pisa el canal reclamado, se apuntó "
          f"{len(doble_log.llamadas)}")
    texto = json.dumps(doble_log.llamadas, ensure_ascii=False)
    check(TOK_COMPARTIDO not in texto and (TOK_DEV or "x") not in texto,
          "el aviso del canal no lleva ningún token dentro")
    check("mobile" in texto,
          f"el aviso del canal dice a qué canal se ha pasado ({texto[:160]})")

    # ── El túnel SIN token: el middleware corta antes (401) y el cerebro no se
    #    toca. Es la otra mitad del mismo agujero.
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente("127.0.0.1") as c:
            r = await c.post("/api/command",
                             headers=_cab(PUBLICO, extra={"cf-connecting-ip": OTRA_RED}),
                             json={"text": "hola", "channel": "pc"})
    check(r.status_code == 401,
          f"/api/command por el túnel SIN token: 401, dio {r.status_code}")
    check(r.json() == CERRADO,
          f"/api/command por el túnel SIN token: cuerpo exacto, salió {r.text[:120]!r}")
    check(espia.llamadas == [],
          f"/api/command por el túnel SIN token: el cerebro NO se toca, se llamó "
          f"{espia.llamadas!r}")

    # ── Peer de loopback pero `Host` público y sin token: NO es este equipo
    #    (mismo caso que SEC-03), así que tampoco entra.
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente("127.0.0.1") as c:
            r = await c.post("/api/command", headers=_cab(PUBLICO),
                             json={"text": "hola", "channel": "pc"})
    check(r.status_code == 401,
          f"/api/command desde loopback con Host público y sin token: 401, "
          f"dio {r.status_code}")
    check(espia.llamadas == [], "y el cerebro no se toca")


class _Espia_log:
    """Espía de `bus.emit_sync`: apunta los eventos que se publican."""

    def __init__(self):
        self.llamadas: list = []

    def __call__(self, tipo, data=None):
        self.llamadas.append({"type": tipo, "data": data})


# ══════════════════════════════════════════════════════════════════════════════
#  2. POST /api/jobs — el canal del trabajo sale de la CONEXIÓN (T8e)
# ══════════════════════════════════════════════════════════════════════════════
async def _trabajo(peer: str, host: str, *, token: str = "", canal: str,
                   texto: str, extra: dict | None = None) -> dict:
    """Lanza un trabajo y espera a que el espía del cerebro lo haya visto."""
    espia = _Espia()
    with _Doble(brain, "process", espia):
        async with _cliente(peer) as c:
            r = await c.post("/api/jobs", headers=_cab(host, token=token, extra=extra),
                             json={"text": texto, "channel": canal})
            cuerpo = r.json() if r.status_code == 200 else {}
            jid = str(cuerpo.get("id", ""))
            for _ in range(100):                 # el trabajo corre en una tarea
                if espia.llamadas:
                    break
                await asyncio.sleep(0.01)
            fila = {}
            if jid:
                listado = await c.get("/api/jobs", headers=_cab(host, token=token,
                                                                extra=extra))
                for trabajo in (listado.json() or {}).get("list", []):
                    if trabajo.get("id") == jid:
                        fila = trabajo
                        break
    return {"status": r.status_code, "espia": espia, "ficha": fila,
            "texto": r.text[:200]}


async def _jobs() -> None:
    caso = await _trabajo("127.0.0.1", HUD, canal="pc", texto="orden local T8e")
    check(caso["status"] == 200,
          f"/api/jobs local con channel=pc: 200, dio {caso['status']} ({caso['texto']})")
    check(caso["espia"].canales == ["pc"],
          f"/api/jobs local: el cerebro recibe «pc», recibió {caso['espia'].canales}")
    check(caso["ficha"].get("channel") == "pc",
          f"/api/jobs local: el trabajo queda con canal «pc», quedó "
          f"{caso['ficha'].get('channel')!r}")

    caso = await _trabajo(OTRA_RED, CASA, token=TOK_DEV, canal="pc",
                          texto="orden remota T8e")
    check(caso["status"] == 200,
          f"/api/jobs con token de dispositivo: 200, dio {caso['status']} ({caso['texto']})")
    check(caso["espia"].canales == ["mobile"],
          f"/api/jobs con token de dispositivo y channel=pc: el cerebro recibe "
          f"«mobile», recibió {caso['espia'].canales}")
    check(caso["ficha"].get("channel") == "mobile",
          f"/api/jobs con token de dispositivo: el trabajo queda con canal «mobile», "
          f"quedó {caso['ficha'].get('channel')!r}")

    caso = await _trabajo("127.0.0.1", PUBLICO, token=TOK_COMPARTIDO, canal="pc",
                          texto="orden por el tunel T8e",
                          extra={"cf-connecting-ip": OTRA_RED})
    check(caso["status"] == 200,
          f"/api/jobs por el túnel con token: 200, dio {caso['status']} ({caso['texto']})")
    check(caso["espia"].canales == ["mobile"],
          f"/api/jobs por el túnel con channel=pc: «mobile», recibió "
          f"{caso['espia'].canales}")


# ══════════════════════════════════════════════════════════════════════════════
#  3. El WebSocket del HUD — mismo criterio (T8e)
# ══════════════════════════════════════════════════════════════════════════════
class _FakeWS:
    """Un WebSocket de mentira para llamar al handler REAL (no abre socket)."""

    def __init__(self, host: str, *, origin: str | None = None, client: str = "127.0.0.1",
                 token: str = "", extra: dict | None = None):
        cabeceras = {"host": host}
        if origin is not None:
            cabeceras["origin"] = origin
        cabeceras.update(extra or {})
        self.headers = _Cabeceras(cabeceras)
        self.client = types.SimpleNamespace(host=client)
        self.query_params = {"token": token}
        self.accepted = False
        self.closed = None
        self.enviados: list = []
        self._cola: list = []

    def encola(self, mensaje: dict) -> None:
        self._cola.append(json.dumps(mensaje))

    async def accept(self):
        self.accepted = True

    async def close(self, code):
        self.closed = code

    async def send_text(self, texto):
        self.enviados.append(texto)

    async def receive_text(self):
        if not self._cola:
            raise WebSocketDisconnect()
        return self._cola.pop(0)


class _Cabeceras(dict):
    """Cabeceras sin `getlist`: `_valores_cabecera` cae al camino simple."""

    def get(self, clave, default=""):
        for k, v in self.items():
            if k.lower() == str(clave).lower():
                return v
        return default


async def _ws(host: str, *, origin: str | None = None, client: str = "127.0.0.1",
              token: str = "", extra: dict | None = None,
              mensajes: list | None = None) -> tuple[_FakeWS, _Espia]:
    """Abre el WS de verdad (handler real) y le manda los mensajes dados."""
    espia = _Espia()
    ws = _FakeWS(host, origin=origin, client=client, token=token, extra=extra)
    for m in mensajes or [{"type": "command", "text": "hola"}]:
        ws.encola(m)
    with _Doble(brain, "process", espia):
        await servidor.websocket_endpoint(ws)
    BUS.unregister(ws)                      # por si el handler no llegó a ello
    return ws, espia


async def _websocket() -> None:
    # El HUD de este equipo: navegador local (con Origin propio) y sin token.
    ws, espia = await _ws(HUD, origin=f"http://{HUD}")
    check(ws.accepted and ws.closed is None,
          f"WS del HUD local entra sin token (aceptado={ws.accepted}, código={ws.closed})")
    check(espia.canales == ["pc"],
          f"WS del HUD local: el cerebro recibe «pc», recibió {espia.canales}")

    # Cliente nativo de este equipo (sin Origin) con su token: sigue siendo «pc».
    ws, espia = await _ws(HUD, token=TOK_COMPARTIDO)
    check(ws.accepted and espia.canales == ["pc"],
          f"WS nativo de este equipo con token: «pc», recibió {espia.canales} "
          f"(aceptado={ws.accepted})")

    # Móvil con su token PROPIO por la WiFi: «mobile», mande lo que mande.
    ws, espia = await _ws(CASA, client=OTRA_RED, token=TOK_DEV,
                          mensajes=[{"type": "command", "text": "hola",
                                     "channel": "pc"}])
    check(ws.accepted, f"WS del móvil con su token propio entra (código={ws.closed})")
    check(espia.canales == ["mobile"],
          f"WS del móvil con token propio: el cerebro recibe «mobile», recibió "
          f"{espia.canales}")

    # Forma del túnel: peer de loopback + `cf-connecting-ip` + token compartido.
    ws, espia = await _ws(PUBLICO, origin="https://" + PUBLICO, token=TOK_COMPARTIDO,
                          extra={"cf-connecting-ip": OTRA_RED})
    check(ws.accepted, f"WS por el túnel con token entra (código={ws.closed})")
    check(espia.canales == ["mobile"],
          f"WS por el túnel con token compartido: el cerebro recibe «mobile», "
          f"recibió {espia.canales} (antes se quedaba en «pc» si no mandaba el hello)")

    # Y sin token, el túnel se cierra como siempre (4401), sin tocar el cerebro.
    ws, espia = await _ws(PUBLICO, origin="https://" + PUBLICO,
                          extra={"cf-connecting-ip": OTRA_RED})
    check(not ws.accepted and ws.closed == 4401,
          f"WS por el túnel SIN token se cierra con 4401 "
          f"(aceptado={ws.accepted}, código={ws.closed})")
    check(espia.llamadas == [], "y el cerebro no se toca")

    # Móvil que se presenta con «hello»: sigue siendo «mobile» (de antes).
    ws, espia = await _ws(CASA, client=OTRA_RED, token=TOK_DEV,
                          mensajes=[{"type": "hello", "role": "mobile",
                                     "id": "d-hello", "name": "Móvil T8e"},
                                    {"type": "command", "text": "hola"}])
    check(ws.accepted and espia.canales == ["mobile"],
          f"WS del móvil tras el hello: «mobile», recibió {espia.canales}")


# ══════════════════════════════════════════════════════════════════════════════
#  4. Los botones de casa: 401 sin credencial, y cada toque a la auditoría (T8d)
# ══════════════════════════════════════════════════════════════════════════════
async def _casa(ruta: str, peer: str, host: str, *, token: str = "",
                cabecera_n8n: str = "", extra: dict | None = None) -> httpx.Response:
    cab = _cab(host, token=token, extra=extra)
    if cabecera_n8n:
        cab["x-nexus-n8n-secret"] = cabecera_n8n
    async with _cliente(peer) as c:
        return await c.post(ruta, headers=cab, json={"kind": "tv", "action": "off",
                                                     "ip": "192.168.1.7", "name": "la TV"})


async def _casa_sin_permiso() -> None:
    control = _EspiaCasa()
    scan = _EspiaCasa({"devices": [], "n_ha": 0})
    secreto = servidor.secreto_n8n()
    with _Doble(skills_loader, "get_skills", _skills_domotica(control_api=control,
                                                              scan_api=scan)):
        antes = len(_lineas_audit())
        for ruta, etiqueta in (("/api/home/control", "/api/home/control"),
                               ("/api/home/scan", "/api/home/scan")):
            # (1) sin credencial desde fuera: 401 y la skill no se toca.
            r = await _casa(ruta, OTRA_RED, CASA)
            check(r.status_code == 401,
                  f"{etiqueta} sin token desde la WiFi: 401, dio {r.status_code}")
            check(r.json() == CERRADO,
                  f"{etiqueta} sin token: cuerpo exacto, salió {r.text[:120]!r}")
            # (2) el secreto de n8n NO es una credencial para estas rutas.
            r = await _casa(ruta, OTRA_RED, CASA, cabecera_n8n=secreto)
            check(r.status_code == 401,
                  f"{etiqueta} con el secreto de n8n desde fuera: 401, dio {r.status_code}")
            # (3) tampoco desde el túnel sin token.
            r = await _casa(ruta, "127.0.0.1", PUBLICO,
                            extra={"cf-connecting-ip": OTRA_RED})
            check(r.status_code == 401,
                  f"{etiqueta} por el túnel sin token: 401, dio {r.status_code}")
        check(control.llamadas == [],
              f"sin credencial la domótica NO se llama, se llamó {len(control.llamadas)} vez/veces")
        check(scan.llamadas == [],
              f"sin credencial el escaneo NO se llama, se llamó {len(scan.llamadas)} vez/veces")
        check(len(_lineas_audit()) == antes,
              f"una petición rechazada no escribe auditoría "
              f"({antes} → {len(_lineas_audit())})")


async def _casa_con_token() -> None:
    control = _EspiaCasa()
    scan = _EspiaCasa({"devices": [{"ip": "192.168.1.7"}, {"ip": "192.168.1.8"}],
                       "n_ha": 0})
    with _Doble(skills_loader, "get_skills", _skills_domotica(control_api=control,
                                                              scan_api=scan)):
        # El móvil vinculado pulsa el botón: se ejecuta UNA vez y se audita.
        antes = len(_lineas_audit())
        r = await _casa("/api/home/control", OTRA_RED, CASA, token=TOK_DEV)
        check(r.status_code == 200,
              f"/api/home/control con token de dispositivo: 200, dio {r.status_code}")
        check(len(control.llamadas) == 1,
              f"/api/home/control con token: la domótica se llama UNA vez, se llamó "
              f"{len(control.llamadas)}")
        nuevas = _lineas_audit()[antes:]
        check(len(nuevas) == 1,
              f"/api/home/control deja UNA línea de auditoría, dejó {len(nuevas)}")
        if nuevas:
            reg = nuevas[-1]
            check(reg.get("channel") == "mobile",
                  f"la auditoría del botón de casa lleva el canal derivado («mobile»), "
                  f"lleva {reg.get('channel')!r}")
            check(reg.get("action") == "domotica_control",
                  f"la acción auditada es «domotica_control», es {reg.get('action')!r}")
            check(reg.get("actor") == "operador",
                  f"la auditoría dice quién lo pidió («operador»), dice {reg.get('actor')!r}")
            check("192.168.1.7" in (reg.get("targets") or []),
                  f"la auditoría dice sobre qué dispositivo ({reg.get('targets')!r})")
            check(TOK_DEV not in json.dumps(reg, ensure_ascii=False),
                  "la línea de auditoría NO lleva el token del dispositivo")

        # El PC de casa: mismo botón, canal local y su línea también.
        antes = len(_lineas_audit())
        r = await _casa("/api/home/control", "127.0.0.1", HUD)
        check(r.status_code == 200,
              f"/api/home/control desde este equipo: 200, dio {r.status_code}")
        check(len(control.llamadas) == 2,
              f"/api/home/control local llama a la domótica una vez más, van "
              f"{len(control.llamadas)}")
        nuevas = _lineas_audit()[antes:]
        check(len(nuevas) == 1 and nuevas[-1].get("channel") == "pc",
              f"la auditoría del botón local lleva canal «pc», lleva "
              f"{[n.get('channel') for n in nuevas]!r}")

        # El escaneo de red: una línea con el número de dispositivos.
        antes = len(_lineas_audit())
        r = await _casa("/api/home/scan", OTRA_RED, CASA, token=TOK_DEV)
        check(r.status_code == 200,
              f"/api/home/scan con token de dispositivo: 200, dio {r.status_code}")
        check(len(scan.llamadas) == 1,
              f"/api/home/scan con token: el escaneo se llama UNA vez, se llamó "
              f"{len(scan.llamadas)}")
        nuevas = _lineas_audit()[antes:]
        check(len(nuevas) == 1,
              f"/api/home/scan deja UNA línea de auditoría, dejó {len(nuevas)}")
        if nuevas:
            reg = nuevas[-1]
            check(reg.get("action") == "domotica_escanear",
                  f"la acción auditada es «domotica_escanear», es {reg.get('action')!r}")
            check(reg.get("channel") == "mobile",
                  f"la auditoría del escaneo remoto lleva «mobile», lleva "
                  f"{reg.get('channel')!r}")
            check("2 dispositivo" in str(reg.get("result", "")),
                  f"la auditoría dice cuántos dispositivos salieron "
                  f"({reg.get('result')!r})")

        # Y el escaneo desde este equipo se audita como local.
        antes = len(_lineas_audit())
        r = await _casa("/api/home/scan", "127.0.0.1", HUD)
        nuevas = _lineas_audit()[antes:]
        check(r.status_code == 200 and len(nuevas) == 1
              and nuevas[-1].get("channel") == "pc",
              f"/api/home/scan local: 200 y canal «pc», dio {r.status_code} "
              f"{[n.get('channel') for n in nuevas]!r}")

        # Estas rutas NO reciben canal del cliente, así que no hay «canal
        # reclamado» que pisar: no deben llenar el registro de avisos.
        avisos = _Espia_log()
        with _Doble(BUS, "emit_sync", avisos):
            r = await _casa("/api/home/control", OTRA_RED, CASA, token=TOK_DEV)
        check(r.status_code == 200 and avisos.llamadas == [],
              f"el botón de casa no apunta un «canal reclamado» que nadie reclamó "
              f"({avisos.llamadas!r})")


async def _casa_error() -> None:
    """La skill revienta: el cliente no ve nada interno (SEC-16) y SÍ queda la
    línea de auditoría del intento fallido."""
    async def _revienta(*_a, **_k):
        raise RuntimeError("la tele no contesta")

    with _Doble(skills_loader, "get_skills", _skills_domotica(control_api=_revienta,
                                                              scan_api=_revienta)):
        antes = len(_lineas_audit())
        r = await _casa("/api/home/control", OTRA_RED, CASA, token=TOK_DEV)
        nuevas = _lineas_audit()[antes:]
        check(r.status_code == 200 and r.json().get("ok") is False,
              f"si la domótica falla, el cliente recibe ok:false ({r.text[:120]})")
        check(len(nuevas) == 1 and nuevas[-1].get("extra", {}).get("ok") is False,
              f"y la auditoría del intento fallido dice que no salió "
              f"({[n.get('extra') for n in nuevas]!r})")


async def main() -> None:
    await _command()
    await _jobs()
    await _websocket()
    await _casa_sin_permiso()
    await _casa_con_token()
    await _casa_error()


asyncio.run(main())

# Limpieza: las carpetas de usar y tirar se borran al terminar (fuera del
# repositorio, en el temporal del sistema). Si algo las tiene cogidas, se quedan:
# borrarlas es cortesía, no parte de la prueba.
import shutil                                                   # noqa: E402
for _dir in (_CFG, _DATA):
    shutil.rmtree(_dir, ignore_errors=True)

print(f"\n{'#' * 54}\ntest_canal_conexion: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
