# -*- coding: utf-8 -*-
"""ERRORES DE API SIN FUGAS Y CALLBACK DE SPOTIFY CON `state` — SEC-16 y SEC-15.

Dos hallazgos de la auditoría del 30/07/2026 (roadmap P3-5, tarea T24):

  SEC-16 — varios handlers devolvían `str(exc)` (o `f"{type}: {exc}"`) dentro del
  JSON de error, así que una ruta del disco o un nombre de host acababan delante
  del cliente. Ahora cada handler contesta un mensaje en cristiano y el TIPO de
  la excepción se queda en el log. Esta suite recorre, endpoint por endpoint, los
  ocho handlers convertidos y comprueba LAS DOS MITADES: el cliente no ve nada
  interno y el log sigue sabiendo qué falló.

    Convertidos: /api/home/scan, /api/home/control, /api/home/install_ha,
    /api/hermes/status, /api/hermes/start, /api/hermes/configure,
    /api/setup/docker, /api/link/qr.
    Fuera A PROPÓSITO: /api/llm_check y /api/llm/status_full (diagnóstico de este
    equipo, es un hallazgo aparte) y /api/home/ha_status (enseña la dirección de
    Home Assistant que configuró el operador, no un texto de excepción).

  SEC-15 — el callback OAuth de Spotify canjeaba el `code` sin mirar `state`
  (login CSRF: se te queda vinculada la cuenta de Spotify de otro). Ahora el
  `state` que genera `spotify.auth_url()` se exige exacto, se compara en tiempo
  constante y se CONSUME antes del intercambio.

TODO EN PROCESO (`httpx.ASGITransport`, que NO ejecuta `lifespan`): ni uvicorn,
ni puertos, ni micrófono, ni Telegram. Config y datos en carpetas de usar y tirar
puestas ANTES de importar el backend. Ni una petición real a Spotify: el
intercambio del código es un espía y el `state` vive en un archivo temporal.

Y `/api/open_url` (SEC-11 / T20b): es la MISMA regla de `net.safe_get` aplicada a
lo que nexus le manda ABRIR al navegador del operador — un `file:///C:/…`, una
ruta UNC, `smb://…`, los metadatos de la nube o la API de este equipo se rechazan
sin llamar al navegador, con la excepción declarada del Home Assistant que el
operador configuró en ⚙. El navegador y el resolutor van doblados: ni se abre
nada ni se pregunta un DNS de verdad.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\core\\test_errores_api.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import types
import urllib.parse
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
_CFG = tempfile.mkdtemp(prefix="nexus_errores_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_errores_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA

import httpx                                                    # noqa: E402

from backend.core.comun import config as cfg                    # noqa: E402
from backend.core.comun import publicvoice as pv                # noqa: E402
from backend.core.comun.events import bus                       # noqa: E402
from backend.core.aplicacion import skills_loader as sl         # noqa: E402
from backend.core.infraestructura import llm as _llm            # noqa: E402
from backend.core.infraestructura import remote, spotify        # noqa: E402
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


# El HUD de verdad: uvicorn escucha en 8177 y la ventana apunta ahí.
HUD = "127.0.0.1:8177"
CAB = {"host": HUD}

# Lo que NO puede salir en un cuerpo de error: una ruta del disco del operador y
# un nombre de host interno, que es justo lo que `str(exc)` arrastraba.
RUTA_LOCAL = r"C:\Users\adrian\AppData\Local\Temp\nexus-ee\estado.json"
HOST_INTERNO = "pc-de-adrian.local:8642"
AGUJAS = (RUTA_LOCAL, "nexus-ee", HOST_INTERNO, "pc-de-adrian", "AppData", "Errno 2")


class _Fallo(RuntimeError):
    """Excepción de mentira con la pinta exacta de una fuga real."""

    def __init__(self):
        super().__init__(f"no pude leer «{RUTA_LOCAL}» contra {HOST_INTERNO}: [Errno 2]")


async def _revienta(*_a, **_k):
    raise _Fallo()


def _revienta_sync(*_a, **_k):
    raise _Fallo()


class _Log:
    """`bus.emit` de mentira: apunta los mensajes que el servidor publica."""

    def __init__(self):
        self.lineas: list[str] = []

    async def __call__(self, tipo: str, data=None) -> None:
        if tipo == "log" and isinstance(data, dict):
            self.lineas.append(str(data.get("msg", "")))

    def texto(self) -> str:
        return "\n".join(self.lineas)


class _Doble:
    """Cambia un atributo y lo devuelve pase lo que pase."""

    def __init__(self, obj, nombre, valor):
        self.obj, self.nombre, self.valor = obj, nombre, valor

    def __enter__(self):
        self.previo = getattr(self.obj, self.nombre)
        setattr(self.obj, self.nombre, self.valor)
        return self.valor

    def __exit__(self, *_exc):
        setattr(self.obj, self.nombre, self.previo)
        return False


def _cliente() -> httpx.AsyncClient:
    """Cliente ASGI en proceso, peer de loopback: el HUD de este equipo."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=servidor.app, client=(HUD.split(":")[0], 4321)),
        base_url=f"http://{HUD}")


def _skills(nombre: str, **metodos):
    """Un registro de skills con UNA skill cuyo módulo son los métodos dobles."""
    return lambda: {nombre: types.SimpleNamespace(module=types.SimpleNamespace(**metodos))}


def _cuerpo(r) -> str:
    return json.dumps(r.json(), ensure_ascii=False, sort_keys=True)


def _exige(nombre: str, r, log: _Log, mensaje: str = "") -> None:
    """Las dos mitades de SEC-16: nada interno al cliente, el tipo en el log."""
    cuerpo = _cuerpo(r)
    for aguja in AGUJAS:
        check(aguja not in cuerpo,
              f"{nombre}: el cliente ve «{aguja}» — {cuerpo[:200]}")
    check(_Fallo.__name__ not in cuerpo,
          f"{nombre}: el cliente ve el tipo de la excepción — {cuerpo[:200]}")
    esperado = mensaje or pv.MENSAJE_ERROR_GENERICO
    check(esperado in cuerpo,
          f"{nombre}: el cliente no recibe el mensaje público ({cuerpo[:200]})")
    check(_Fallo.__name__ in log.texto(),
          f"{nombre}: el log no dice qué falló ({log.texto()[:200]!r})")


# ══════════════════════════════════════════════════════════════════════════════
#  1. LOS OCHO HANDLERS CONVERTIDOS
# ══════════════════════════════════════════════════════════════════════════════
async def _escenarios() -> None:
    # ---- /api/home/scan: la skill de domótica revienta al rastrear la red
    log = _Log()
    with _Doble(bus, "emit", log), _Doble(sl, "get_skills", _skills("domotica", scan_api=_revienta)):
        async with _cliente() as c:
            r = await c.post("/api/home/scan", headers=CAB)
    _exige("POST /api/home/scan", r, log)
    check(r.json().get("devices") == [],
          f"/api/home/scan: la lista de dispositivos debería venir vacía ({r.text[:120]})")

    # ---- /api/home/control: la skill falla al mandar la orden
    log = _Log()
    with _Doble(bus, "emit", log), _Doble(sl, "get_skills", _skills("domotica", control_api=_revienta)):
        async with _cliente() as c:
            r = await c.post("/api/home/control", headers=CAB, json={"ip": "192.168.1.7"})
    _exige("POST /api/home/control", r, log,
           "No he podido enviar la orden. No se ha realizado ningún cambio.")

    # ---- /api/home/install_ha: docker no arranca
    log = _Log()
    with _Doble(bus, "emit", log), _Doble(shutil, "which", lambda *_a, **_k: "/usr/bin/docker"), \
            _Doble(asyncio, "create_subprocess_exec", _revienta):
        async with _cliente() as c:
            r = await c.post("/api/home/install_ha", headers=CAB)
    _exige("POST /api/home/install_ha", r, log)

    # ---- /api/hermes/status | start | configure
    for ruta, metodo, metodos, cuerpo in (
            ("/api/hermes/status", "GET", {"diagnose": _revienta}, None),
            ("/api/hermes/start", "POST", {"ensure_up": _revienta}, None),
            ("/api/hermes/configure", "POST", {"configure_brain": _revienta_sync},
             {"provider": "ollama", "model": "qwen3:8b", "api_key": "x"})):
        log = _Log()
        with _Doble(bus, "emit", log), _Doble(sl, "get_skills", _skills("hermes", **metodos)):
            async with _cliente() as c:
                r = await c.request(metodo, ruta, headers=CAB, json=cuerpo)
        _exige(f"{metodo} {ruta}", r, log)

    # ---- /api/setup/docker: `docker compose` revienta. ROOT a una carpeta de
    # usar y tirar para que el docker-compose.yml del endpoint no toque el repo.
    tmp_root = Path(tempfile.mkdtemp(prefix="nexus_errores_root_"))
    log = _Log()
    try:
        with _Doble(bus, "emit", log), _Doble(cfg, "ROOT", tmp_root), \
                _Doble(shutil, "which", lambda *_a, **_k: "/usr/bin/docker"), \
                _Doble(__import__("subprocess"), "run", _revienta_sync):
            async with _cliente() as c:
                r = await c.post("/api/setup/docker", headers=CAB)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    _exige("POST /api/setup/docker", r, log)

    # ---- /api/link/qr: el estado del vínculo revienta
    log = _Log()
    with _Doble(bus, "emit", log), _Doble(remote, "status", _revienta_sync):
        async with _cliente() as c:
            r = await c.get("/api/link/qr", headers=CAB)
    _exige("GET /api/link/qr", r, log)

    # ---- lo que se queda A PROPÓSITO: el diagnóstico local sigue igual (no se
    # convierte y no se gasta una petición real a ningún proveedor: la lista de
    # proveedores es un doble vacío).
    with _Doble(_llm, "PROVIDERS", {}):
        async with _cliente() as c:
            r = await c.get("/api/llm_check", headers=CAB)
    check(r.status_code == 200,
          f"/api/llm_check (diagnóstico local) ha dejado de contestar: {r.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
#  2. EL CALLBACK DE SPOTIFY EXIGE `state` Y LO CONSUME (SEC-15)
# ══════════════════════════════════════════════════════════════════════════════
class _Espia:
    """El intercambio del `code` por tokens, sin salir a la red."""

    def __init__(self):
        self.codigos: list[str] = []

    async def __call__(self, code: str) -> bool:
        self.codigos.append(code)
        return True


async def _spotify_callback() -> None:
    carpeta = Path(tempfile.mkdtemp(prefix="nexus_spotify_state_"))
    espia = _Espia()
    log = _Log()
    previo = spotify.PENDING_FILE
    spotify.PENDING_FILE = carpeta / "spotify_pending.json"
    try:
        with _Doble(spotify, "exchange_code", espia), _Doble(bus, "emit", log):
            async with _cliente() as c:
                # el `state` que nexus acaba de generar
                consulta = urllib.parse.parse_qs(urllib.parse.urlparse(spotify.auth_url()).query)
                estado = (consulta.get("state") or [""])[0]
                check(bool(estado), f"auth_url() no lleva `state` ({consulta})")

                # sin `state`: ni se canjea ni se cuenta nada de dentro
                r = await c.get("/api/spotify/callback", headers=CAB,
                                params={"code": "codigo-de-prueba"})
                check(espia.codigos == [],
                      f"un callback SIN `state` ha canjeado el código: {espia.codigos}")
                _exige_html("/api/spotify/callback (sin state)", r)

                # `state` equivocado: igual de cerrado, y no quema el pendiente
                r = await c.get("/api/spotify/callback", headers=CAB,
                                params={"code": "codigo-de-prueba", "state": "inventado"})
                check(espia.codigos == [],
                      f"un callback con `state` equivocado ha canjeado: {espia.codigos}")
                _exige_html("/api/spotify/callback (state malo)", r)

                # el bueno: se canjea UNA vez
                r = await c.get("/api/spotify/callback", headers=CAB,
                                params={"code": "codigo-de-prueba", "state": estado})
                check(espia.codigos == ["codigo-de-prueba"],
                      f"el callback legítimo no canjeó el código: {espia.codigos}")
                check("Spotify conectado" in r.text,
                      f"el navegador no ve que se conectó: {r.text[:200]!r}")
                check("cerrar" in r.text.lower(),
                      "la página de éxito ya no invita a cerrar la pestaña")

                # repetido: el `state` ya está gastado
                r = await c.get("/api/spotify/callback", headers=CAB,
                                params={"code": "codigo-repetido", "state": estado})
                check(espia.codigos == ["codigo-de-prueba"],
                      f"un callback REPETIDO ha vuelto a canjear: {espia.codigos}")
                _exige_html("/api/spotify/callback (repetido)", r)
    finally:
        spotify.PENDING_FILE = previo
        shutil.rmtree(carpeta, ignore_errors=True)


def _exige_html(nombre: str, r) -> None:
    """La página del navegador: honesta, en español, sin una traza dentro."""
    check(r.status_code == 200, f"{nombre}: el navegador recibe {r.status_code}")
    check("text/html" in r.headers.get("content-type", ""),
          f"{nombre}: la respuesta ya no es una página ({r.headers.get('content-type')})")
    for aguja in AGUJAS + ("Traceback", "_Fallo", "RuntimeError", "ValueError",
                           "NoneType", "no autorizado"):
        check(aguja not in r.text, f"{nombre}: la página enseña «{aguja}»")
    check(any(t in r.text for t in ("No he podido validar", "no he podido validar",
                                   "No he podido", "cancelada")),
          f"{nombre}: la página no dice en cristiano qué ha pasado ({r.text[:200]!r})")


# ══════════════════════════════════════════════════════════════════════════════
#  4. /api/open_url: UNA regla para «abrir un enlace» (SEC-11 / T20b)
# ══════════════════════════════════════════════════════════════════════════════
# El agujero que cierra T20b no es lo que nexus PIDE (eso lo cerró `c1af942`),
# sino lo que nexus le dice ABRIR al navegador del operador: `file:///…` abre el
# explorador de Windows, una ruta UNC abre un recurso de red y
# `http://127.0.0.1:8177/…` llega a la API de este equipo CON LA CARA DEL
# OPERADOR. Aquí se comprueba contra el servidor de verdad (ASGI, en proceso):
# cero llamadas al navegador y la negativa en español.
#
# La ÚNICA excepción, declarada: el Home Assistant que el operador configuró en ⚙
# (`homeassistant_url`). Es un destino que ya decidió él — Home Assistant es
# interno por definición — y sin esta puerta el botón «Abrir Home Assistant» del
# HUD moriría. Se compara esquema + equipo + puerto, nada más.
class _Navegador:
    """`webbrowser.open` de mentira: apunta qué se manda abrir y no abre nada."""

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url, *_a, **_k):
        self.urls.append(url)
        return True


_DIRECCIONES = {"publico.example": ["93.184.216.34"],
                "maps.google.com": ["93.184.216.34"],
                "www.youtube.com": ["93.184.216.34"],
                "resuelve-a-loopback.example": ["127.0.0.1"]}


def _resolver(host: str) -> list[str]:
    """Resolutor de mentira: ni una consulta DNS de verdad en esta suite."""
    if host in _DIRECCIONES:
        return _DIRECCIONES[host]
    raise OSError(f"nombre fuera de la tabla de la prueba: {host}")


ABRIR_RECHAZADAS = [
    "file:///C:/Windows/win.ini",
    "\\\\evil\\share",
    "smb://nas.local/share",
    "http://127.0.0.1:8177/api/command",
    "http://169.254.169.254/latest/meta-data/",
    "http://usuario:clave-secreta@evil.example/",
    "FILE:///C:/Windows/win.ini",
    "  HTTP://169.254.169.254/latest/meta-data/  ",
    "http://127%2e0%2e0%2e1:8177/api/config",
    "http://resuelve-a-loopback.example/x",
]

ABRIR_PERMITIDAS = ["https://publico.example/x",
                    "https://maps.google.com/?q=Madrid",
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


async def _open_url() -> None:
    import webbrowser

    from backend.core.comun import net

    nav = _Navegador()
    previo = cfg.settings._json.get("homeassistant_url")
    cfg.settings._json["homeassistant_url"] = "http://192.168.1.10:8123"
    try:
        with _Doble(net, "_direcciones", _resolver), _Doble(webbrowser, "open", nav):
            async with _cliente() as c:
                for url in ABRIR_RECHAZADAS:
                    nav.urls.clear()
                    r = await c.post("/api/open_url", headers=CAB, json={"url": url})
                    check(r.status_code == 400,
                          f"POST /api/open_url con {url!r} contesta {r.status_code}, no 400")
                    check(nav.urls == [],
                          f"¡se ha abierto {url!r} en el navegador!: {nav.urls}")
                    cuerpo = _cuerpo(r)
                    check("No voy a abrir" in cuerpo,
                          f"la negativa de {url!r} no está en español: {cuerpo[:160]}")
                    check("clave-secreta" not in cuerpo and "usuario:" not in cuerpo,
                          f"la negativa de {url!r} lleva credenciales: {cuerpo[:160]}")

                for url in ABRIR_PERMITIDAS:
                    nav.urls.clear()
                    r = await c.post("/api/open_url", headers=CAB, json={"url": url})
                    check(r.status_code == 200 and r.json().get("ok") is True,
                          f"un enlace normal ya no se abre ({url!r}): {r.status_code} {r.text[:120]}")
                    check(nav.urls == [url],
                          f"un enlace normal se abre MAL ({url!r}): {nav.urls}")

                # La excepción declarada: el Home Assistant CONFIGURADO por el operador.
                for url in ("http://192.168.1.10:8123",
                            "http://192.168.1.10:8123/config/integrations/dashboard",
                            "http://192.168.1.10:8123/lovelace/0"):
                    nav.urls.clear()
                    r = await c.post("/api/open_url", headers=CAB, json={"url": url})
                    check(nav.urls == [url],
                          f"el Home Assistant configurado no se abre ({url!r}): "
                          f"{r.status_code} {nav.urls} {r.text[:120]}")

                # …pero el valor configurado NO se puede reutilizar para abrir OTRO
                # destino interno: otro puerto, otro equipo, otro esquema o una
                # URL que se aprovecha del equipo configurado como userinfo.
                for url in ("http://192.168.1.10:8080/", "http://192.168.1.10:8080/admin",
                            "http://192.168.1.20:8123/", "http://192.168.1.201:8123/",
                            "https://192.168.1.10:8123/",
                            "http://192.168.1.10:8123@evil.example/",
                            "http://127.0.0.1:8177/api/command"):
                    nav.urls.clear()
                    r = await c.post("/api/open_url", headers=CAB, json={"url": url})
                    check(r.status_code == 400 and nav.urls == [],
                          f"el Home Assistant configurado ha dejado pasar {url!r}: "
                          f"{r.status_code} {nav.urls}")

                # El valor guardado tiene que servir por sí solo: uno que no es una
                # URL http(s) con equipo no blanquea nada.
                for basura in ("192.168.1.10:8123", "   ", "file:///C:/Windows",
                               "http://usuario:clave@192.168.1.10:8123"):
                    cfg.settings._json["homeassistant_url"] = basura
                    nav.urls.clear()
                    r = await c.post("/api/open_url", headers=CAB,
                                     json={"url": "http://192.168.1.10:8123"})
                    check(r.status_code == 400 and nav.urls == [],
                          f"un `homeassistant_url` inválido ({basura!r}) blanqueó un destino interno")
                cfg.settings._json["homeassistant_url"] = "http://192.168.1.10:8123"

                # Sin Home Assistant configurado NO hay default: el que el HUD usa
                # cuando no hay nada guardado (`http://localhost:8123`) también se
                # rechaza, con su negativa y sin tocar el navegador.
                cfg.settings._json.pop("homeassistant_url", None)
                for url in ("http://192.168.1.10:8123", "http://localhost:8123",
                            "http://localhost:8123/lovelace/0"):
                    nav.urls.clear()
                    r = await c.post("/api/open_url", headers=CAB, json={"url": url})
                    check(r.status_code == 400 and nav.urls == [],
                          f"sin `homeassistant_url` se abre un destino interno ({url!r}): "
                          f"{r.status_code} {nav.urls}")
                    if url != "http://192.168.1.10:8123":
                        check("No voy a abrir" in _cuerpo(r),
                              f"la negativa de {url!r} no está en español: {_cuerpo(r)[:140]}")
    finally:
        if previo is None:
            cfg.settings._json.pop("homeassistant_url", None)
        else:
            cfg.settings._json["homeassistant_url"] = previo


# ══════════════════════════════════════════════════════════════════════════════
#  5. EL CANDADO ESTRUCTURAL: no vuelve a colarse un `str(exc)`
# ══════════════════════════════════════════════════════════════════════════════
def _candado_estructural() -> None:
    src = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")
    check('"error": str(exc)' not in src,
          "app.py vuelve a devolver `str(exc)` en un cuerpo de error")
    crudo = src.count('f"{type(exc).__name__}: {exc}"')
    check(crudo <= 1,
          f"app.py tiene {crudo} copias de `f\"{{type}}: {{exc}}\"`; sólo se admite la "
          "del diagnóstico local (/api/llm_check), que es un hallazgo aparte")
    usados = src.count("publicvoice.fallo(")
    check(usados >= 8,
          f"sólo {usados} handlers usan el helper público; los convertidos son ocho")


def main() -> int:
    for paso in (_escenarios, _spotify_callback, _open_url):
        try:
            asyncio.run(paso())
        except Exception as e:                                # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCIÓN en {paso.__name__}: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN en", paso.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    try:
        _candado_estructural()
    except Exception as e:                                    # noqa: BLE001
        _fail.append(f"EXCEPCIÓN en el candado estructural: {type(e).__name__}: {e}")
        print("  EXCEPCIÓN en el candado:", type(e).__name__, e)

    print(f"\n{'='*54}\n{_pass} comprobaciones OK, {len(_fail)} fallos")
    for m in _fail:
        print("  -", m)
    return 1 if _fail else 0


if __name__ == "__main__":
    from backend.core.comun import net
    try:
        code = main()
    finally:
        asyncio.run(net.aclose())
        shutil.rmtree(_CFG, ignore_errors=True)
        shutil.rmtree(_DATA, ignore_errors=True)
    sys.exit(code)
