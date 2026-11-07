# -*- coding: utf-8 -*-
"""DESTINO SEGURO — SSRF: ninguna URL de un canal no confiable llega a abrirse.

Hallazgo SEC-11 de la auditoría y fila P3-1 del roadmap (tarea T20). Lo que se
prueba, y por qué:

  1. La guarda (`net.asegurar_destino` / `net.motivo_destino`) rechaza, ANTES de
     abrir nada, todo lo que no sea un destino público por http/https: loopback
     (127.0.0.0/8, ::1), link-local y metadatos de la nube (169.254/16, fe80::),
     RFC1918, CGNAT de Tailscale (100.64/10), multicast, 0.0.0.0/::, nombres
     internos (`localhost`, `metadata.google.internal`, `.local`), nombres que
     RESUELVEN a esas direcciones, esquemas que no son http/https (`file:`) y
     enlaces con `usuario:clave@` dentro.
  2. Una negativa NUNCA enseña credenciales: el mensaje nombra el host, no la
     URL con userinfo.
  3. Las redirecciones se revalidan salto a salto: un host público que responde
     302 hacia 169.254.169.254 no se sigue. `safe_get` pide con
     `follow_redirects=False` y hace su propio bucle; el cliente COMPARTIDO sigue
     como estaba, porque `remote.py` sondea 127.0.0.1:8177 a propósito.
  4. Los llamadores que convierten texto en URL lo aplican: `websearch.fetch_page`
     (y con él research y YouTube-descarga), `vigilancias` al crear (no guarda un
     vigilante imposible) y en cada comprobación (avisa con la verdad).
  5. `datos`: `sqlite://<ruta>` pasa por `permissions.path_allowed()` —incluida la
     denylist de credenciales, también en modo «todo»— y una BD de RED solo se
     acepta desde el equipo del operador (`channel="pc"`), que es donde está la
     base que él declara (su Postgres en 127.0.0.1:5433 sigue funcionando).

TODO en proceso y SIN RED: se dobla el transporte (`net.client`) y el resolutor
(`net._direcciones`) antes de la primera llamada, así que ninguna prueba abre una
conexión ni pregunta un DNS de verdad. Config, datos y PERFIL de usar y tirar.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\core\\test_destino_seguro.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar backend: ni la configuración ni el perfil del operador.
_CFG = Path(tempfile.mkdtemp(prefix="nexus_destino_cfg_"))
_DATA = Path(tempfile.mkdtemp(prefix="nexus_destino_data_"))
_HOME = Path(tempfile.mkdtemp(prefix="nexus_destino_home_"))
_APPDATA = _HOME / "AppData" / "Roaming"
_LOCALAPPDATA = _HOME / "AppData" / "Local"
_PERMITIDA = Path(tempfile.mkdtemp(prefix="nexus_destino_ok_"))   # carpeta autorizada
_FUERA = Path(tempfile.mkdtemp(prefix="nexus_destino_out_"))      # carpeta NO autorizada
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
os.environ["USERPROFILE"] = str(_HOME)
os.environ["HOME"] = str(_HOME)
os.environ["APPDATA"] = str(_APPDATA)
os.environ["LOCALAPPDATA"] = str(_LOCALAPPDATA)
os.environ.pop("OneDrive", None)
os.environ.pop("OneDriveConsumer", None)

from backend.core.aplicacion import skills_loader as sl          # noqa: E402
from backend.core.comun import net                               # noqa: E402
from backend.core.comun.config import DATA_DIR, settings         # noqa: E402
from backend.core.infraestructura import websearch               # noqa: E402

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)
    return bool(cond)


def check_async(coro):
    return asyncio.run(coro)


# ─────────────────────────── dobles: transporte y DNS ───────────────────────────
class Respuesta:
    """Lo que `net.safe_get` necesita de una respuesta de httpx (nada más)."""

    def __init__(self, text: str = "", url: str = "", status_code: int = 200,
                 headers: dict | None = None):
        self.text = text
        self.url = url
        self.status_code = status_code
        self.headers = dict(headers or {})

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text or "{}")


class Transporte:
    """Doble de `net.client()`: apunta cada petición y no abre una sola conexión."""

    DEFECTO = ("<article><p>Texto público de la página de pruebas, con longitud "
               "suficiente para que el extractor lo conserve.</p></article>")

    def __init__(self, respuestas=None):
        self.calls: list[tuple[str, dict]] = []
        self.respuestas = list(respuestas or [])

    async def get(self, url, **kw):
        self.calls.append((url, kw))
        if not self.respuestas:
            return Respuesta(self.DEFECTO, url=str(url))
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r(str(url), kw)
        return r


PUBLICO = "93.184.216.34"          # una dirección pública cualquiera (no se pide)
PUBLICO_2 = "1.1.1.1"


class Red:
    """Dobla el transporte Y el resolutor: en esta suite no hay red de verdad."""

    def __init__(self, respuestas=None, tabla=None):
        self.doble = Transporte(respuestas)
        self.tabla = {"ejemplo-publico.example": [PUBLICO],
                      "publico.example": [PUBLICO],
                      "otro-publico.example": [PUBLICO_2],
                      "resuelve-a-loopback.example": ["127.0.0.1"],
                      "resuelve-a-interno.example": ["10.0.0.5"],
                      **(tabla or {})}

    def _direcciones(self, host: str) -> list[str]:
        if host in self.tabla:
            return self.tabla[host]
        raise OSError(f"nombre fuera de la tabla de la prueba: {host}")

    def __enter__(self):
        self._cli = net.client
        self._dir = net._direcciones
        net.client = lambda: self.doble
        net._direcciones = self._direcciones
        return self

    def __exit__(self, *exc):
        net.client = self._cli
        net._direcciones = self._dir
        return False


class Config:
    """Cambia claves de configuración EN MEMORIA (nunca escribe settings.json)."""

    def __init__(self, **vals):
        self.vals = vals

    def __enter__(self):
        self.previo = dict(settings._json)
        settings._json.update(self.vals)
        return self

    def __exit__(self, *exc):
        settings._json.clear()
        settings._json.update(self.previo)
        return False


def rechazo(url: str, red: Red | None = None) -> tuple[str, str]:
    """(motivo corto, mensaje completo) de una negativa; '' si no la hay."""
    motivo = net.motivo_destino(url)
    if not motivo:
        return "", ""
    try:
        net.asegurar_destino(url)
    except net.DestinoNoPermitido as exc:                      # lo esperado
        return motivo, str(exc)
    return motivo, ""


# ═══════════════════ 1. LA MATRIZ DE DESTINOS ═══════════════════
print("== 1) la guarda clasifica el destino ANTES de pedir nada ==")

PERMITIDAS = [
    f"http://{PUBLICO}/pagina",
    f"https://{PUBLICO}:8443/x?y=1",
    "http://ejemplo-publico.example/pagina",
    "https://EJEMPLO-PUBLICO.example/MAYUSCULAS",
    "   https://ejemplo-publico.example/espacios   ",
]
for url in PERMITIDAS:
    with Red() as red:
        check(net.motivo_destino(url) == "", f"se permite un destino público: {url!r}")
        try:
            devuelta = net.asegurar_destino(url)
            check(bool(devuelta), f"asegurar_destino devuelve la URL que vale ({url!r})")
        except net.DestinoNoPermitido as exc:                  # noqa: PERF203
            check(False, f"NO debería rechazar un destino público {url!r}: {exc}")
        check(red.doble.calls == [], f"la guarda no pide nada por su cuenta ({url!r})")

RECHAZADAS = [
    ("http://127.0.0.1/", "127.0.0.1"),
    ("http://127.0.0.1:8177/api/command", "127.0.0.1"),
    ("http://127.5.5.5/x", "127.5.5.5"),
    ("http://localhost:8177/", "localhost"),
    ("http://[::1]:8177/api/command", "::1"),
    ("http://169.254.169.254/latest/meta-data/", "169.254.169.254"),
    ("http://10.0.0.5/admin", "10.0.0.5"),
    ("http://172.16.0.1/", "172.16.0.1"),
    ("http://192.168.1.10/panel", "192.168.1.10"),
    ("http://100.64.0.1/", "100.64.0.1"),
    ("http://0.0.0.0/", "0.0.0.0"),
    ("http://[::]/", "::"),
    ("http://metadata.google.internal/computeMetadata/v1/", "metadata.google.internal"),
    ("http://nas.local/admin", "nas.local"),
    ("http://resuelve-a-loopback.example/x", "resuelve-a-loopback.example"),
    ("http://resuelve-a-interno.example/x", "resuelve-a-interno.example"),
    ("file:///C:/Windows/win.ini", "file"),
    ("gopher://93.184.216.34/_x", "gopher"),
    ("ftp://93.184.216.34/x", "ftp"),
    # el truco del userinfo: la «IP» va delante de la arroba, no es el destino
    ("http://127.0.0.1@evil.example/", "evil.example"),
    ("HTTP://169.254.169.254/", "169.254.169.254"),
    ("\t http://192.168.1.10/x \n", "192.168.1.10"),
    ("http://127%2e0%2e0%2e1/", "127.0.0.1"),
    ("http://169.254.169.254./", "169.254.169.254"),
    ("http://usuario:clave-secreta@192.168.1.10/x", "192.168.1.10"),
]
for url, visible in RECHAZADAS:
    with Red() as red:
        motivo, mensaje = rechazo(url)
        check(bool(motivo), f"hay motivo de rechazo para {url!r}")
        check(bool(mensaje), f"asegurar_destino lanza la negativa para {url!r}")
        check(mensaje.startswith("No voy a abrir"), f"la negativa empieza como debe ({url!r}): {mensaje[:60]}")
        check(visible in mensaje, f"la negativa nombra el destino ({url!r}): {mensaje[:90]}")
        check("puente" in mensaje, f"y explica por qué no se usa nexus de puente ({url!r})")
        check("clave-secreta" not in mensaje and "usuario:" not in mensaje,
              f"la negativa NUNCA lleva credenciales ({url!r}): {mensaje[:90]}")
        check(red.doble.calls == [], f"ninguna petición para un destino rechazado ({url!r})")

print("· el cliente COMPARTIDO no cambia: los sondeos internos de remote.py siguen igual")
_shared = net.client()
check(getattr(_shared, "follow_redirects", None) is True,
      "net.client() sigue siguiendo redirecciones (remote.py sondea 127.0.0.1 a propósito)")


# ═══════════════════ 2. REDIRECCIONES, SALTO A SALTO ═══════════════════
print("== 2) cada redirección se revalida: público → 302 → metadatos NO se sigue ==")

with Red([Respuesta("", url=f"http://{PUBLICO}/", status_code=302,
                   headers={"location": "http://169.254.169.254/latest/meta-data/"})]) as red:
    _m, mensaje = "", ""
    try:
        check_async(net.safe_get(f"http://{PUBLICO}/"))
        check(False, "sigue una redirección hacia los metadatos de la nube")
    except net.DestinoNoPermitido as exc:
        mensaje = str(exc)
        check(True, "")
    check("169.254.169.254" in mensaje and mensaje.startswith("No voy a abrir"),
          f"la negativa nombra el salto interno: {mensaje[:90]}")
    check(len(red.doble.calls) == 1, f"solo se pidió el primer salto ({len(red.doble.calls)})")
    check(red.doble.calls[0][1].get("follow_redirects") is False,
          "safe_get pide con follow_redirects=False: el bucle de saltos es suyo")

print("· una redirección relativa se resuelve y se sigue si el destino es público")
with Red([Respuesta("", url=f"http://{PUBLICO}/uno", status_code=301,
                    headers={"location": "/dos"}),
          Respuesta("<p>final</p>", url=f"http://{PUBLICO}/dos")]) as red:
    r = check_async(net.safe_get(f"http://{PUBLICO}/uno"))
    check(getattr(r, "text", "") == "<p>final</p>", "dos saltos públicos: devuelve la página final")
    check([c[0] for c in red.doble.calls] == [f"http://{PUBLICO}/uno", f"http://{PUBLICO}/dos"],
          f"las dos peticiones son las esperadas: {[c[0] for c in red.doble.calls]}")

print("· el salto malo puede estar en el SEGUNDO salto")
with Red([Respuesta("", status_code=302, headers={"location": "http://publico.example/a"}),
          Respuesta("", status_code=302, headers={"location": "http://10.0.0.5/b"})]) as red:
    try:
        check_async(net.safe_get("http://publico.example/inicio"))
        check(False, "sigue el segundo salto hacia la red privada")
    except net.DestinoNoPermitido as exc:
        check("10.0.0.5" in str(exc), f"el rechazo nombra el segundo destino: {str(exc)[:80]}")
    check(len(red.doble.calls) == 2, f"se pidieron los dos saltos públicos y nada más ({len(red.doble.calls)})")

print("· una redirección con credenciales no se sigue ni se enseña")
with Red([Respuesta("", status_code=302,
                    headers={"location": "http://usuario:clave-secreta@192.168.1.10/x"})]) as red:
    try:
        check_async(net.safe_get("http://publico.example/x"))
        check(False, "sigue una redirección con usuario:clave dentro")
    except net.DestinoNoPermitido as exc:
        check("clave-secreta" not in str(exc) and "192.168.1.10" in str(exc),
              f"la negativa del salto no lleva credenciales: {str(exc)[:90]}")
    check(len(red.doble.calls) == 1, "no se pidió el salto con credenciales")

print("· un bucle de redirecciones se corta")
with Red([Respuesta("", status_code=302, headers={"location": f"http://{PUBLICO}/otra"}),
          Respuesta("", status_code=302, headers={"location": f"http://{PUBLICO}/otra"})]) as red:
    try:
        check_async(net.safe_get(f"http://{PUBLICO}/x", max_redirecciones=1))
        check(False, "sigue redirecciones sin tope")
    except net.DestinoNoPermitido as exc:
        check("redirec" in str(exc), f"el corte por tope se explica: {str(exc)[:90]}")
    check(len(red.doble.calls) == 2, f"con tope 1 se piden 2 saltos y se para ({len(red.doble.calls)})")


# ═══════════════════ 3. LOS LLAMADORES ═══════════════════
print("== 3) websearch.fetch_page: el texto de un canal no confiable no se abre ==")

with Red() as red:
    txt = check_async(websearch.fetch_page("http://169.254.169.254/latest/meta-data/"))
    check(txt == "", "fetch_page sobre los metadatos devuelve vacío (nunca se pide)")
    check(red.doble.calls == [], "fetch_page no ha pedido NADA")

with Red([Respuesta("<article><p>Texto público ágil de la página de pruebas, con longitud "
                    "suficiente para el extractor.</p></article>", url=f"http://{PUBLICO}/a")]) as red:
    txt = check_async(websearch.fetch_page(f"http://{PUBLICO}/a"))
    check("Texto público" in txt, f"una página pública se sigue leyendo: {txt[:60]}")
    check(len(red.doble.calls) == 1, "y se pide una sola vez")

with Red() as red:
    txt = check_async(websearch.fetch_page("http://127.0.0.1:8177/api/config"))
    check(txt == "" and red.doble.calls == [],
          "fetch_page sobre la API propia de nexus no la abre")

print("== 4) youtube: la pista de subtítulos (URL que elige YouTube) pasa por la guarda ==")
from backend.core.infraestructura import youtube               # noqa: E402

with Red([Respuesta('{"events": []}', url=f"https://{PUBLICO}/json3")]) as red:
    crudo = check_async(youtube._descargar(f"https://{PUBLICO}/json3"))
    check(crudo.startswith("{" ), "una pista de subtítulos pública se sigue descargando")
    check(red.doble.calls[0][1].get("follow_redirects") is False,
          "la descarga de la pista también revalida las redirecciones")

with Red() as red:
    try:
        check_async(youtube._descargar("http://192.168.1.10/sub.json3"))
        check(False, "descarga una pista de subtítulos de la red local")
    except net.DestinoNoPermitido:
        check(True, "")
    check(red.doble.calls == [], "la pista interna no se pide")

sl.load_skills()
VIG = sl.get_skills()["vigilancias"].module
DATOS = sl.get_skills()["datos"].module
CTX = {"settings": settings, "channel": "pc"}


def vigilancias(frase: str) -> str:
    r = sl.route(frase)
    assert r and r[0].folder == "vigilancias", (frase, r and (r[0].folder, r[1]))
    return check_async(r[0].module.handle(r[1], frase, r[2], CTX))["reply"]


print("== 5) vigilancias: no se guarda un vigilante que no se puede abrir ==")
VIG._file = lambda: DATA_DIR / "watchers.json"
(DATA_DIR / "watchers.json").unlink(missing_ok=True)

with Red() as red:
    r = vigilancias("vigila la web http://127.0.0.1:8177/api/command")
    check(r.startswith("No voy a abrir") and "127.0.0.1" in r,
          f"crear un vigilante sobre la API propia se rechaza: {r[:90]}")
    check("puente" in r, "y se explica por qué: no se usa nexus de puente")
    check(VIG._load() == [], "y NO se guarda nada: el vigilante no existe")
    check(red.doble.calls == [], "y no se ha pedido nada")

    r = vigilancias("avísame si baja el precio de http://169.254.169.254/x")
    check(r.startswith("No voy a abrir") and VIG._load() == [],
          f"tampoco un vigilante de precio sobre los metadatos: {r[:90]}")
    check(red.doble.calls == [], "el precio interno no se ha pedido")

print("· un vigilante sobre una web pública se sigue creando")
with Red() as red:
    r = vigilancias("vigila la web https://ejemplo-publico.example/oferta")
    check("Vigilancia #1 activada" in r, f"una web pública se vigila igual: {r[:90]}")
    guardado = VIG._load()
    check(len(guardado) == 1 and guardado[0]["objetivo"] == "https://ejemplo-publico.example/oferta",
          f"y queda guardada entera: {guardado}")
    check(red.doble.calls == [], "crear el vigilante no pide la página")

print("== 6) el tick del scheduler: si el destino se volvió interno, lo dice y no lo abre ==")
VIG._file = lambda: DATA_DIR / "watchers.json"
(DATA_DIR / "watchers.json").write_text(json.dumps([
    {"num": 1, "tipo": "web", "objetivo": "http://192.168.1.10/panel", "estado": {},
     "creado": time.time(), "ultima": 0.0},
    {"num": 2, "tipo": "web", "objetivo": "https://ejemplo-publico.example/oferta", "estado": {},
     "creado": time.time(), "ultima": 0.0},
], ensure_ascii=False), encoding="utf-8")
avisos: list[str] = []
_orig_notify = VIG._notify


async def _captura(msg):
    avisos.append(msg)


VIG._notify = _captura
try:
    with Red([Respuesta("<article><p>Contenido público estable de la oferta, con longitud "
                        "suficiente para el extractor.</p></article>",
                        url="https://ejemplo-publico.example/oferta")]) as red:
        fired = check_async(VIG.check_watchers(force=True))
        urls = [c[0] for c in red.doble.calls]
        check(urls == ["https://ejemplo-publico.example/oferta"],
              f"solo se pide el vigilante público: {urls}")
        check(fired == 1 and len(avisos) == 1,
              f"salta UN aviso, el del vigilante que ya no se puede abrir ({fired}/{avisos})")
        check("192.168.1.10" in avisos[0] and "no la voy a abrir" in avisos[0].lower(),
              f"y lo dice con la verdad: {avisos[0][:120]}")
        estado = {w["num"]: w for w in VIG._load()}
        check(bool(estado[2].get("estado", {}).get("digest")),
              "el vigilante público sigue registrando su contenido")
        check(int(estado[1].get("estado", {}).get("fallos") or 0) == 1,
              f"el interno cuenta el fallo: {estado[1].get('estado')}")
finally:
    VIG._notify = _orig_notify
    (DATA_DIR / "watchers.json").unlink(missing_ok=True)


# ═══════════════════ 7. datos: sqlite y bases de red ═══════════════════
print("== 7) datos: «sqlite://ruta» pasa por path_allowed (denylist incluida) ==")


def conectar(frase: str, canal: str = "pc") -> str:
    r = sl.route(frase)
    assert r and r[0].folder == "datos", (frase, r and (r[0].folder, r[1]))
    return check_async(r[0].module.handle(
        r[1], frase, r[2], {"settings": settings, "channel": canal}))["reply"]


DATOS._conn.update({"url": None, "kind": None, "handle": None})
_bd_ok = _PERMITIDA / "ok.db"
_c = sqlite3.connect(_bd_ok)
_c.execute("CREATE TABLE t (a INTEGER)")
_c.execute("INSERT INTO t VALUES (7)")
_c.commit()
_c.close()
_bd_fuera = _FUERA / "fuera.db"
_c = sqlite3.connect(_bd_fuera)
_c.execute("CREATE TABLE t (a INTEGER)")
_c.commit()
_c.close()
_credencial = _HOME / ".ssh"
_credencial.mkdir(parents=True, exist_ok=True)
(_credencial / "id_rsa").write_text("no-es-una-clave-de-verdad", encoding="utf-8")

with Config(perm_files="carpetas", perm_folders=[str(_PERMITIDA)]):
    r = conectar(f"conéctate a la base de datos sqlite://{_bd_ok.as_posix()}")
    check("Conectado a SQLITE" in r, f"una ruta permitida sigue funcionando: {r[:90]}")
    DATOS._conn.update({"url": None, "kind": None, "handle": None})

    r = conectar(f"conéctate a la base de datos sqlite://{_bd_fuera.as_posix()}")
    check("No tengo permiso" in r, f"una ruta fuera de permisos se rechaza: {r[:90]}")
    check(DATOS._conn["handle"] is None, "y no se abre ninguna conexión")

with Config(perm_files="todo"):
    r = conectar(f"conéctate a la base de datos sqlite://{_bd_fuera.as_posix()}")
    check("Conectado a SQLITE" in r, f"en modo «todo» una ruta normal se abre: {r[:90]}")
    DATOS._conn.update({"url": None, "kind": None, "handle": None})

    r = conectar(f"conéctate a la base de datos sqlite://{(_credencial / 'id_rsa').as_posix()}")
    check("material de credenciales" in r,
          f"pero una credencial se rechaza TAMBIÉN en «todo»: {r[:110]}")
    check(DATOS._conn["handle"] is None, "y la credencial no se abre")

print("== 8) datos: una BD de RED solo la declara el equipo del operador ==")


class _ConnFalsa:
    def __init__(self, dsn):
        self.dsn = dsn
        self.sesion = None

    def set_session(self, **kw):
        self.sesion = kw


class _Psycopg2Falsa(types.ModuleType):
    def __init__(self):
        super().__init__("psycopg2")
        self.dsns: list[str] = []

    def connect(self, dsn, **kw):
        self.dsns.append(dsn)
        return _ConnFalsa(dsn)


class _PymysqlFalsa(types.ModuleType):
    def __init__(self):
        super().__init__("pymysql")
        self.destinos: list[tuple] = []

    def connect(self, **kw):
        self.destinos.append((kw.get("host"), kw.get("port"), kw.get("database")))
        return types.SimpleNamespace(
            cursor=lambda: types.SimpleNamespace(__enter__=lambda s=None: None,
                                                 __exit__=lambda *a: None,
                                                 execute=lambda *a, **k: None))


_psycopg2 = _Psycopg2Falsa()
_pymysql = _PymysqlFalsa()
_previos = {k: sys.modules.get(k) for k in ("psycopg2", "pymysql")}
sys.modules["psycopg2"] = _psycopg2
sys.modules["pymysql"] = _pymysql
try:
    dsn = "postgresql://dueno:secreta@127.0.0.1:5433/nexus"
    r = conectar(f"conéctate a la base de datos {dsn}", canal="pc")
    check("Conectado a POSTGRES" in r, f"tu Postgres de 127.0.0.1:5433 sigue conectando: {r[:90]}")
    check(_psycopg2.dsns == [dsn],
          f"y se conecta EXACTAMENTE a la base declarada: {_psycopg2.dsns}")
    check("secreta" not in r and ":****@" in r, f"la contraseña se tapa en la respuesta: {r[:90]}")
    DATOS._conn.update({"url": None, "kind": None, "handle": None})

    antes = len(_psycopg2.dsns)
    for canal in ("mobile", "telegram", "n8n"):
        r = conectar(f"conéctate a la base de datos {dsn}", canal=canal)
        check(f"desde «{canal}»" in r and "No conecto" in r,
              f"desde «{canal}» no se conecta a una BD de red: {r[:110]}")
        check(len(_psycopg2.dsns) == antes,
              f"desde «{canal}» no se ha intentado la conexión ({_psycopg2.dsns})")

    atacante = "postgresql://u:p@attacker-host.example:5432/x"
    r = conectar(f"conéctate a la base de datos {atacante}", canal="pc")
    check("Conectado a POSTGRES" in r and _psycopg2.dsns[-1] == atacante,
          "en el equipo del operador el destino es la base que él declara: no se filtra por IP")
    DATOS._conn.update({"url": None, "kind": None, "handle": None})

    r = conectar("conéctate a la base de datos mysql://u@10.0.0.5:3306/x", canal="telegram")
    check("No conecto" in r and _pymysql.destinos == [],
          f"mysql desde Telegram: ni se intenta el handshake ({_pymysql.destinos})")
finally:
    for k, v in _previos.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    DATOS._conn.update({"url": None, "kind": None, "handle": None})

print("== 9) no se ha abierto nada de verdad: el resolver y el transporte eran dobles ==")
check(net._direcciones.__name__ == "_direcciones", "el resolutor real queda restaurado al terminar")
check(net.client.__name__ == "client", "el cliente real queda restaurado al terminar")

print(f"\n{'=' * 54}\nDESTINO SEGURO: {_pass} OK, {len(_fail)} FAIL")

# Las carpetas de usar y tirar se van con la suite (fuera del árbol de trabajo).
import gc                                                     # noqa: E402
import shutil                                                 # noqa: E402

try:                                                          # suelta el fichero sqlite (Windows lo bloquea)
    if DATOS._conn.get("handle") is not None:
        DATOS._conn["handle"].close()
except Exception:                                             # noqa: BLE001
    pass
DATOS._conn.update({"url": None, "kind": None, "handle": None})
gc.collect()
for _d in (_CFG, _DATA, _HOME, _PERMITIDA, _FUERA):
    shutil.rmtree(_d, ignore_errors=True)

sys.exit(1 if _fail else 0)
