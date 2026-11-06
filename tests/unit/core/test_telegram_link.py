# -*- coding: utf-8 -*-
"""Vinculación de Telegram con código de un solo uso (SEC-02, roadmap P1-2, T3).

Lo que fija esta suite:

  * SIN propietario, un mensaje NO registra a nadie. Antes el primero que
    escribía se quedaba el equipo para siempre (TOFU): quien conociera el
    @usuario del bot ganaba el PC, y al dueño legítimo se le ignoraba.
  * Para vincular hay que mandar el código que SOLO se ve en este equipo
    (`pending_link_code()` y `GET /api/telegram/link`, este último únicamente
    para loopback). El código caduca (`telegram.ttl_vinculacion_segundos` de
    config/umbrales.json, 10 min de reserva) y sirve UNA vez.
  * Con propietario ya registrado NADA cambia: solo ese chat da órdenes, y las
    suyas siguen llegando a `brain.process` como siempre (voz incluida).

TODO va EN PROCESO: cliente httpx de mentira y `httpx.ASGITransport` (que no
ejecuta `lifespan`, así que no arranca Whisper, ni el micrófono, ni el
long-polling de verdad, ni abre puertos). La config y los datos apuntan a
carpetas de usar y tirar, y el token del bot es un señuelo: se comprueba que
NUNCA aparece en una respuesta ni en el log.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\core\\test_telegram_link.py
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import sys
import tempfile
import time
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
_CFG = Path(tempfile.mkdtemp(prefix="nexus_tg_cfg_"))
_DATA = Path(tempfile.mkdtemp(prefix="nexus_tg_data_"))
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
# Señuelo, no un token real: `settings.secret("telegram_bot_token")` cae aquí.
_TOKEN_FALSO = "123456789:NO_ES_UN_TOKEN_REAL_solo_prueba"
os.environ["TELEGRAM_BOT_TOKEN"] = _TOKEN_FALSO

import httpx                                                    # noqa: E402

from backend.core.comun.config import CONFIG_DIR, settings      # noqa: E402
from backend.core.aplicacion import brain                       # noqa: E402
from backend.core.infraestructura import telegram_bridge        # noqa: E402
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
API = "https://api.telegram.org/bot" + _TOKEN_FALSO
# Sin caracteres que se confundan al copiar del HUD al móvil (0/O, 1/I/L).
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
OK_ENLACE = "🟢 nexus enlazado"
PISTA = "no está vinculado"
CODIGO_MALO = "Código incorrecto o caducado"


# ─────────────────────────── dobles de prueba ──────────────────────────────
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


class _Espia:
    """Sustituto de brain.process: apunta la llamada y contesta algo inocuo."""

    def __init__(self):
        self.llamadas = []

    async def __call__(self, text, source="text", **kw):
        self.llamadas.append({"text": text, "source": source, **kw})
        return {"reply": "eco de prueba", "skill": None, "provider": "espia", "data": None}


class _Resp:
    def __init__(self, datos):
        self._datos = datos

    def json(self):
        return self._datos


class _Cli:
    """Cliente httpx de mentira: apunta lo que se envía y no toca la red."""

    def __init__(self):
        self.enviados = []

    async def post(self, url, json=None, **_kw):               # noqa: A002
        self.enviados.append({"url": url, **(json or {})})
        return _Resp({})

    async def get(self, url, **_kw):
        raise AssertionError(f"el puente no debe descargar nada aquí: {url}")

    def textos(self) -> list[str]:
        return [str(e.get("text", "")) for e in self.enviados]

    def ultimo(self) -> str:
        return self.textos()[-1] if self.enviados else ""


def _upd(chat_id: str, texto: str = "", voz: str | None = None, n: int = 1) -> dict:
    msg: dict = {"chat": {"id": int(chat_id)}}
    if texto:
        msg["text"] = texto
    if voz:
        msg["voice"] = {"file_id": voz}
    return {"update_id": n, "message": msg}


def _propietario() -> str:
    f = telegram_bridge.OWNER_FILE
    return f.read_text(encoding="utf-8") if f.is_file() else ""


def _limpiar() -> None:
    for f in (telegram_bridge.OWNER_FILE, telegram_bridge.LINK_CODE_FILE):
        try:
            f.unlink()
        except OSError:
            pass


async def _atender(cli, chat_id: str, texto: str = "", voz: str | None = None,
                   owner: str = "", n: int = 1) -> str:
    return await telegram_bridge.atender_update(
        cli, API, _TOKEN_FALSO, _upd(chat_id, texto, voz, n), owner)


def _cliente(host: str = "127.0.0.1") -> httpx.AsyncClient:
    """Cliente ASGI en proceso con un peer concreto (local o 'de fuera')."""
    transporte = httpx.ASGITransport(app=APP, client=(host, 4321))
    return httpx.AsyncClient(transport=transporte, base_url="http://127.0.0.1:8177")


def _ttl_config(segundos: int | None) -> None:
    """Escribe (o borra) `telegram.ttl_vinculacion_segundos` en la config temporal."""
    f = CONFIG_DIR / "umbrales.json"
    if segundos is None:
        try:
            f.unlink()
        except OSError:
            pass
        return
    f.write_text(json.dumps({"telegram": {"ttl_vinculacion_segundos": segundos}}),
                 encoding="utf-8")


# ══════════════════════════════ los casos ══════════════════════════════════
async def caso_1_sin_propietario_no_registra():
    """Un mensaje cualquiera sin propietario: ni registro, ni orden, ni cerebro."""
    _limpiar()
    cli, espia = _Cli(), _Espia()
    with _Doble(brain, "process", espia):
        nuevo = await _atender(cli, "555", "hola nexus, ¿me oyes?")
    check(nuevo == "", f"sin propietario el chat NO se registra, devolvió {nuevo!r}")
    check(not telegram_bridge.OWNER_FILE.exists(),
          "sin propietario no debe crearse data/telegram_owner.txt")
    check(_propietario() == "", "el propietario guardado debe seguir vacío")
    check(espia.llamadas == [],
          f"un chat no vinculado NUNCA llega a brain.process: {espia.llamadas!r}")
    check(len(cli.textos()) == 1,
          f"se contesta UNA vez con la pista de vinculación, se contestó {cli.textos()!r}")
    check(PISTA in cli.ultimo(), f"la respuesta debe avisar de que no está vinculado: {cli.ultimo()!r}")
    check(_TOKEN_FALSO not in cli.ultimo(), "la pista NO debe llevar el token del bot")


async def caso_2_comando_sin_codigo_vigente():
    """`/start` sin código pendiente: código incorrecto o caducado, sin registro."""
    _limpiar()
    cli = _Cli()
    await _atender(cli, "556", "/start ABCDEFGH")
    check(CODIGO_MALO in cli.ultimo(), f"un código que no toca debe rechazarse: {cli.ultimo()!r}")
    check(not telegram_bridge.OWNER_FILE.exists(),
          "un código incorrecto NO debe registrar propietario")


async def caso_3_el_codigo_es_local_aleatorio_y_de_un_solo_uso():
    """El código: 8 caracteres, alfabeto sin equívocos, `secrets`, y uno nuevo por petición."""
    _limpiar()
    primero = telegram_bridge.pending_link_code()
    segundo = telegram_bridge.pending_link_code()
    check(len(primero) >= 8, f"el código debe tener 8 caracteres o más: {primero!r}")
    check(all(c in ALFABETO for c in primero),
          f"el código solo usa el alfabeto sin equívocos: {primero!r}")
    check(primero != segundo,
          "cada petición genera un código NUEVO (el anterior deja de valer)")
    check(telegram_bridge.LINK_CODE_FILE.is_file(),
          "el código se guarda en data/telegram_link_code.txt")
    check(str(telegram_bridge.LINK_CODE_FILE).startswith(str(_DATA)),
          "el código se guarda en el DATA_DIR configurado, no en otro sitio")
    lineas = telegram_bridge.LINK_CODE_FILE.read_text(encoding="utf-8").split()
    check(lineas and lineas[0] == segundo,
          "el fichero guarda el código vigente")
    check(len(lineas) >= 2 and lineas[1].isdigit(),
          f"el fichero guarda cuándo se creó (para el TTL): {lineas!r}")
    if os.name != "nt":                       # en Windows los modos son otra cosa
        modo = telegram_bridge.LINK_CODE_FILE.stat().st_mode & 0o777
        check(modo & 0o077 == 0,
              f"el código se escribe con permisos de solo el dueño (0600), no {oct(modo)}")
    fuente = inspect.getsource(telegram_bridge)
    check("secrets.choice" in fuente,
          "el código se genera con secrets.choice (no con random)")
    check("import random" not in fuente and "random.choice" not in fuente,
          "el puente no usa random para nada")
    muchos = {telegram_bridge.pending_link_code() for _ in range(200)}
    check(len(muchos) == 200,
          f"200 códigos seguidos deben ser todos distintos, hubo {len(muchos)} distintos")
    check(all(len(c) == len(primero) for c in muchos),
          "todos los códigos tienen la misma longitud")


async def caso_4_el_codigo_exacto_vincula_una_vez():
    """El código correcto registra el chat, se consume y contesta el 🟢 de siempre."""
    _limpiar()
    codigo = telegram_bridge.pending_link_code()
    espia = _Espia()
    cli = _Cli()
    with _Doble(brain, "process", espia):
        nuevo = await _atender(cli, "777", codigo)
    check(nuevo == "777", f"el código correcto debe vincular ese chat, devolvió {nuevo!r}")
    check(_propietario() == "777", f"el propietario guardado debe ser 777: {_propietario()!r}")
    check(not telegram_bridge.LINK_CODE_FILE.exists(),
          "el código es de UN SOLO USO: se consume al vincular")
    check(OK_ENLACE in cli.ultimo(),
          f"hay que contestar el enlace de siempre: {cli.ultimo()!r}")
    check(espia.llamadas == [],
          f"vincular no es dar una orden: brain.process no debe llamarse {espia.llamadas!r}")
    check(_TOKEN_FALSO not in " ".join(cli.textos()),
          "el token del bot no debe viajar en el TEXTO del mensaje de enlace"
          " (en la URL de la Bot API sí va: es donde lo pone Telegram)")
    check(codigo not in json.dumps(cli.enviados),
          "el código no debe repetirse en la respuesta (ya está usado)")


async def caso_5_otro_chat_no_reemplaza_al_propietario():
    """Con propietario, el código desde otro chat no le quita el sitio."""
    _limpiar()
    primer_codigo = telegram_bridge.pending_link_code()
    await _atender(_Cli(), "777", primer_codigo)
    segundo_codigo = telegram_bridge.pending_link_code()
    cli = _Cli()
    espia = _Espia()
    with _Doble(brain, "process", espia):
        nuevo = await _atender(cli, "999", segundo_codigo, owner="777")
    check(nuevo == "777", f"el propietario no cambia: devolvió {nuevo!r}")
    check(_propietario() == "777", "el propietario sigue siendo el primero")
    check(cli.enviados == [],
          f"a un chat desconocido no se le contesta nada (como siempre): {cli.textos()!r}")
    check(espia.llamadas == [], "un chat desconocido nunca llega a brain.process")


async def caso_6_el_ttl_se_lee_de_umbrales():
    """El TTL no está a fuego: cambiando umbrales.json, el código caduca antes."""
    _ttl_config(60)
    _limpiar()
    try:
        check(telegram_bridge.ttl_vinculacion_segundos() == 60,
              "el TTL debe leerse de config/umbrales.json (telegram.ttl_vinculacion_segundos)")
        ahora = time.time()
        codigo = telegram_bridge.pending_link_code()
        cli = _Cli()
        with _Doble(telegram_bridge, "_ahora", lambda: ahora + 59):
            nuevo = await _atender(cli, "888", codigo)
        check(nuevo == "888", "con 60 s de TTL, a los 59 s el código sigue valiendo")
        _limpiar()
        codigo = telegram_bridge.pending_link_code()
        cli = _Cli()
        with _Doble(telegram_bridge, "_ahora", lambda: ahora + 61):
            nuevo = await _atender(cli, "889", codigo)
        check(nuevo == "", "pasado el TTL el código NO vincula")
        check(CODIGO_MALO in cli.ultimo(),
              f"un código caducado debe decir «caducado»: {cli.ultimo()!r}")
        check(not telegram_bridge.OWNER_FILE.exists(),
              "un código caducado no debe dejar propietario")
    finally:
        _ttl_config(None)


async def caso_7_el_ttl_de_reserva_son_diez_minutos():
    """Sin umbrales.json, la reserva son 10 minutos (los de la auditoría)."""
    _ttl_config(None)
    _limpiar()
    check(telegram_bridge.ttl_vinculacion_segundos() == 600,
          "la reserva del TTL son 600 s (10 min)")
    ahora = time.time()
    codigo = telegram_bridge.pending_link_code()
    with _Doble(telegram_bridge, "_ahora", lambda: ahora + 599):
        nuevo = await _atender(_Cli(), "890", codigo)
    check(nuevo == "890", "a los 599 s el código todavía vale")
    _limpiar()
    codigo = telegram_bridge.pending_link_code()
    with _Doble(telegram_bridge, "_ahora", lambda: ahora + 601):
        nuevo = await _atender(_Cli(), "891", codigo)
    check(nuevo == "", "a los 601 s el código ya no vale")
    _limpiar()


async def caso_8_el_propietario_actual_sigue_mandando():
    """REGRESIÓN: con propietario registrado, su orden llega igual que antes."""
    _limpiar()
    telegram_bridge.OWNER_FILE.write_text("111", encoding="utf-8")
    espia = _Espia()
    cli = _Cli()
    with _Doble(brain, "process", espia):
        nuevo = await _atender(cli, "111", "estado del disco", owner="111")
    check(nuevo == "111", "el propietario vigente no cambia al dar una orden")
    check(len(espia.llamadas) == 1, f"esperaba 1 llamada a brain.process, hubo {len(espia.llamadas)}")
    if espia.llamadas:
        llamada = espia.llamadas[0]
        check(llamada["text"] == "estado del disco", f"el texto debe llegar intacto: {llamada!r}")
        check(llamada["source"] == "text", f"source debe seguir siendo 'text': {llamada!r}")
        check(llamada["channel"] == "telegram", f"channel debe seguir siendo 'telegram': {llamada!r}")
    check(cli.ultimo() == "eco de prueba", f"debe contestar la respuesta del cerebro: {cli.ultimo()!r}")
    check(_propietario() == "111", "no se reescribe el propietario por dar una orden")
    check(not telegram_bridge.LINK_CODE_FILE.exists(),
          "dar una orden no genera códigos de vinculación")


async def caso_9_los_demas_chats_se_siguen_ignorando():
    """REGRESIÓN: un chat que no es el propietario no recibe ni respuesta."""
    _limpiar()
    telegram_bridge.OWNER_FILE.write_text("111", encoding="utf-8")
    espia = _Espia()
    cli = _Cli()
    with _Doble(brain, "process", espia):
        nuevo = await _atender(cli, "222", "borra todos mis archivos", owner="111")
    check(nuevo == "111", "el propietario no cambia")
    check(espia.llamadas == [], f"un chat ajeno no da órdenes: {espia.llamadas!r}")
    check(cli.enviados == [], f"a un chat ajeno no se le contesta (como siempre): {cli.textos()!r}")
    _limpiar()


async def caso_10_la_nota_de_voz_del_propietario_sigue_funcionando():
    """REGRESIÓN: la nota de voz del propietario se transcribe y se ejecuta."""
    _limpiar()
    telegram_bridge.OWNER_FILE.write_text("111", encoding="utf-8")
    transcripciones = []

    async def _transcribir(_cli, _api, _token, file_id):
        transcripciones.append(file_id)
        return "pon música"

    espia = _Espia()
    cli = _Cli()
    with _Doble(telegram_bridge, "_transcribe_tg", _transcribir):
        with _Doble(brain, "process", espia):
            await _atender(cli, "111", voz="FILE-ID-1", owner="111")
    check(transcripciones == ["FILE-ID-1"], f"debe transcribir la nota de voz: {transcripciones!r}")
    check(len(espia.llamadas) == 1, f"la transcripción debe ejecutarse: {espia.llamadas!r}")
    if espia.llamadas:
        check(espia.llamadas[0]["text"] == "pon música", "debe pasar el texto transcrito")
    check(any("🎙 Te he entendido" in t for t in cli.textos()),
          f"debe confirmar lo entendido: {cli.textos()!r}")
    check(cli.ultimo() == "eco de prueba", "y después la respuesta del cerebro")
    _limpiar()


async def caso_11_el_bucle_usa_el_mismo_camino():
    """El long-polling de verdad pasa por ahí: un update del bucle vincula."""
    _limpiar()
    codigo = telegram_bridge.pending_link_code()
    enviados: list[dict] = []

    class _ClienteBucle:
        """httpx.AsyncClient de mentira: un getUpdates y se corta el bucle."""

        def __init__(self, *a, **k):
            self.veces = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, params=None, **_kw):
            if url.endswith("/getMe"):
                return _Resp({"result": {"username": "nexus_de_prueba"}})
            if url.endswith("/getUpdates"):
                self.veces += 1
                if self.veces > 1:
                    raise asyncio.CancelledError()   # fin de la prueba
                return _Resp({"result": [_upd("4242", codigo)]})
            raise AssertionError(f"petición inesperada: {url}")

        async def post(self, url, json=None, **_kw):         # noqa: A002
            enviados.append({"url": url, **(json or {})})
            return _Resp({})

    espia = _Espia()
    cortado = False
    with _Doble(httpx, "AsyncClient", _ClienteBucle):
        with _Doble(brain, "process", espia):
            try:
                await telegram_bridge.telegram_loop()
            except asyncio.CancelledError:
                cortado = True
    check(cortado, "la prueba debe poder cortar el bucle (CancelledError no se traga)")
    check(_propietario() == "4242",
          f"el bucle debe vincular con el código pendiente: {_propietario()!r}")
    check(espia.llamadas == [], "vincular desde el bucle tampoco ejecuta el cerebro")
    check(any(OK_ENLACE in str(e.get("text", "")) for e in enviados),
          f"el bucle debe contestar el enlace: {enviados!r}")
    _limpiar()


async def caso_12_el_codigo_solo_se_muestra_en_este_equipo():
    """GET /api/telegram/link: loopback sí, remoto 403, y el token del bot nunca."""
    _ttl_config(None)
    _limpiar()
    async with _cliente() as c:
        r = await c.get("/api/telegram/link")
    check(r.status_code == 200, f"GET /api/telegram/link local debe dar 200, dio {r.status_code}")
    cuerpo = r.json()
    codigo = str(cuerpo.get("codigo") or "")
    check(len(codigo) >= 8 and all(ch in ALFABETO for ch in codigo),
          f"el endpoint debe devolver el código vigente: {codigo!r}")
    check(cuerpo.get("ttl_segundos") == 600,
          f"el endpoint debe decir cuánto vive el código: {cuerpo!r}")
    check(telegram_bridge.LINK_CODE_FILE.is_file()
          and telegram_bridge.LINK_CODE_FILE.read_text(encoding="utf-8").split()[0] == codigo,
          "el código que se muestra es el que se guardó (se puede canjear)")
    check(_TOKEN_FALSO not in r.text,
          "GET /api/telegram/link NO debe devolver el token del bot")

    # El código mostrado en el equipo canjea desde el móvil.
    nuevo = await _atender(_Cli(), "31337", codigo)
    check(nuevo == "31337", "el código mostrado en el HUD debe vincular el chat")
    _limpiar()

    settings.set_secret("link_token", "token-de-prueba-vinculado")
    async with _cliente("203.0.113.9") as c:
        r = await c.get("/api/telegram/link", headers={"x-nexus-token": "token-de-prueba-vinculado"})
    check(r.status_code == 403,
          f"un móvil o el túnel (aun con token válido) debe recibir 403, dio {r.status_code}")
    check(codigo not in r.text, "el remoto NO debe recibir el código")
    check(_TOKEN_FALSO not in r.text, "el remoto NO debe recibir el token del bot")


async def caso_13_nada_de_esto_acaba_en_el_log():
    """Ni el token ni el código pendiente se escriben en data/nexus.log."""
    _limpiar()
    codigo = telegram_bridge.pending_link_code()
    await _atender(_Cli(), "5150", "hola")
    await _atender(_Cli(), "5151", "codigo equivocado")
    registro = _DATA / "nexus.log"
    texto = registro.read_text(encoding="utf-8") if registro.is_file() else ""
    check(_TOKEN_FALSO not in texto, "el token del bot no debe acabar en data/nexus.log")
    check(codigo not in texto, "el código pendiente no debe acabar en data/nexus.log")
    _limpiar()


CASOS = (
    ("1 sin propietario no registra", caso_1_sin_propietario_no_registra),
    ("2 /start sin código vigente", caso_2_comando_sin_codigo_vigente),
    ("3 el código es local, aleatorio y de un solo uso", caso_3_el_codigo_es_local_aleatorio_y_de_un_solo_uso),
    ("4 el código exacto vincula una vez", caso_4_el_codigo_exacto_vincula_una_vez),
    ("5 otro chat no reemplaza al propietario", caso_5_otro_chat_no_reemplaza_al_propietario),
    ("6 el TTL se lee de umbrales", caso_6_el_ttl_se_lee_de_umbrales),
    ("7 el TTL de reserva son 10 minutos", caso_7_el_ttl_de_reserva_son_diez_minutos),
    ("8 el propietario actual sigue mandando", caso_8_el_propietario_actual_sigue_mandando),
    ("9 los demás chats se siguen ignorando", caso_9_los_demas_chats_se_siguen_ignorando),
    ("10 la nota de voz del propietario sigue funcionando", caso_10_la_nota_de_voz_del_propietario_sigue_funcionando),
    ("11 el bucle usa el mismo camino", caso_11_el_bucle_usa_el_mismo_camino),
    ("12 el código solo se muestra en este equipo", caso_12_el_codigo_solo_se_muestra_en_este_equipo),
    ("13 nada de esto acaba en el log", caso_13_nada_de_esto_acaba_en_el_log),
)


async def main() -> None:
    for nombre, caso in CASOS:
        print(f"· {nombre}")
        try:
            await caso()
        except Exception as exc:                   # un fallo se nombra, no se esconde
            check(False, f"{nombre}: ha reventado con {type(exc).__name__}: {exc}")


asyncio.run(main())

print(f"\n{'#' * 54}\ntest_telegram_link: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)

# Las carpetas de usar y tirar se borran al terminar: ni restos en el temporal.
for _d in (_CFG, _DATA):
    shutil.rmtree(_d, ignore_errors=True)

sys.exit(1 if _fail else 0)
