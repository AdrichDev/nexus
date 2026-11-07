# -*- coding: utf-8 -*-
"""DELEGACIÓN EN EL EJECUTOR: localidad, consentimiento y reintentos — T25/P3-6.

Lo que se prueba aquí (auditoría del 30/07/2026: `05` §5 y AI-05/AI-06, `07` §4,
roadmap P3-6, y el hueco que dejó abierto L38 del ODD):

  1. LOCALIDAD Y PERMISO. Un encargo delegado lo resuelve un ejecutor externo con
     SU proveedor, y esa nube la eligió el dueño a propósito al configurar a
     Hermes: por eso la clave es **`permitir_delegacion_nube` (true por defecto)**
     y NO `permitir_fallback_nube` (T6), que gobierna el CAMBIO de cerebro de
     nexus cuando el elegido no responde. Con la delegación a la nube en false:
     se rechaza en castellano, se dice dónde se activa y NO se hace ni una
     petición ni se arma confirmación. Con true (el defecto): se sigue, el panel
     de la confirmación avisa de que el encargo sale del equipo y se publica el
     aviso por el bus. Con un cerebro local (ollama, o un endpoint de loopback):
     no hace falta ningún permiso. La frontera real sigue siendo el «sí» por
     orden.
  2. CONFIRMACIÓN. La primera entrega de un encargo arma `confirm.request`
     (`delegacion_hermes`, NO destructiva) con el texto EXACTO que recibirá el
     ejecutor. «Sí» lo encarga una vez; «no» no encarga nada; cambiar de tema
     desarma. Un encargo ya aprobado NO vuelve a preguntar en sus reintentos.
  3. REINTENTOS. Un fallo ANTES de entregar el encargo (no hay conexión) puede
     relanzar el servicio y probar UNA vez más. Un fallo DESPUÉS de entregarlo
     (5xx, 401, timeout, corte a mitad) NO se reenvía nunca solo: se dice que
     puede haber ocurrido ya y cómo seguir.
  4. CONTADOR. La delegación queda apuntada en el contador del día por proveedor
     del ejecutor, SIN tokens (nexus no los ve) y SIN sumarse a las llamadas de
     nexus. `/api/status` lo publica sin ninguna clave. `permitir_delegacion_nube`
     está además entre las claves que solo se cambian desde este equipo
     (`_CLAVES_SOLO_LOCALES`): un POST remoto la rechaza con 403.
  5. REGRESIONES que no se pueden tocar: el rechazo de canal (n8n) sigue
     ocurriendo antes que cualquier delegación, y la confirmación se responde
     solo desde текст/voz.

TODO EN PROCESO: `httpx.AsyncClient` doblado ANTES de la primera llamada (nada
sale a la red), `NEXUS_CONFIG_DIR`/`NEXUS_DATA_DIR`/`HERMES_HOME` en carpetas de
usar y tirar puestas antes de importar el backend, y valores sintéticos: no se
lee la configuración del operador ni `~/.hermes`, y no se arranca ningún
gateway (H1/H2 del ODD).

Ejecutar:  .venv\\Scripts\\python.exe tests/unit/skills/hermes/test_delegacion.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖ " + msg)
    return bool(cond)


SKILL_PY = os.path.join(ROOT, "skills", "hermes", "skill.py")
BRAIN_PY = os.path.join(ROOT, "backend", "core", "aplicacion", "brain.py")

# ── 0) CARPETAS DE USAR Y TIRAR, ANTES DE IMPORTAR NADA DEL BACKEND ──────────
_TMP = Path(tempfile.mkdtemp(prefix="nexus_hermes_deleg_"))
_CFG = _TMP / "config"
_DATA = _TMP / "data"
_HERMES_HOME = _TMP / "hermes_home"
for _d in (_CFG, _DATA, _HERMES_HOME):
    _d.mkdir(parents=True, exist_ok=True)
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
os.environ["HERMES_HOME"] = str(_HERMES_HOME)

import httpx  # noqa: E402

_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ══════════════════════════════════════════════════════════════════════════════
#  EL TRANSPORTE, DOBLADO ANTES DE LA PRIMERA LLAMADA
# ══════════════════════════════════════════════════════════════════════════════
class _Respuesta:
    def __init__(self, status: int = 200, payload=None, texto: str = ""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = texto or json.dumps(self._payload)

    def json(self):
        return self._payload


def _ok(texto: str = "LISTO") -> _Respuesta:
    return _Respuesta(200, {"choices": [{"message": {"content": texto}}]})


class _ClienteFalso:
    """`httpx.AsyncClient` doblado. Cada instancia nueva comparte el guion y el
    registro: lo que importa es QUÉ se pidió y CUÁNTAS veces, no el objeto."""

    guion: list = []
    llamadas: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _siguiente(self, defecto):
        if _ClienteFalso.guion:
            nxt = _ClienteFalso.guion.pop(0)
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt
        return defecto

    async def post(self, url, **kw):
        _ClienteFalso.llamadas.append(("POST", url))
        return await self._siguiente(_ok())

    async def get(self, url, **kw):
        _ClienteFalso.llamadas.append(("GET", url))
        return await self._siguiente(_Respuesta(200, {}))

    def stream(self, method, url, **kw):               # no lo usa Hermes; por si acaso
        raise AssertionError("streaming inesperado en esta prueba")


httpx.AsyncClient = _ClienteFalso

from backend.core.aplicacion.jobs import jobs as job_mgr  # noqa: E402
from backend.core.comun import canales, confirm, net, presupuesto  # noqa: E402
from backend.core.comun.config import settings  # noqa: E402
from backend.core.comun.events import bus  # noqa: E402
from backend.core.dominio.memory import pg  # noqa: E402
from backend.core.infraestructura import llm  # noqa: E402


def _cargar_skill():
    spec = importlib.util.spec_from_file_location(
        "hermes_skill_de_delegacion", SKILL_PY)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


mod = _cargar_skill()


# ══════════════════════════════════════════════════════════════════════════════
#  DOBLES: ni gateway, ni Hermes instalado de verdad, ni Postgres, ni jobs
# ══════════════════════════════════════════════════════════════════════════════
class _Ajustes:
    """Doble de `settings`: datos sintéticos, en memoria. Nada del operador."""

    def __init__(self, datos=None):
        self.data = {"hermes_url": "http://127.0.0.1:8642",
                     "hermes_autostart": False,
                     "permitir_fallback_nube": False,
                     "permitir_delegacion_nube": True,
                     "hermes_provider": "gemini",
                     "hermes_model": "modelo-de-prueba"}
        self.data.update(datos or {})

    def get(self, k, d=None):
        return self.data.get(k, d)

    def set(self, k, v):
        self.data[k] = v

    def secret(self, k):
        return ""

    def set_secret(self, k, v):
        self.data["secret:" + k] = v


CTX = {"settings": _Ajustes(), "channel": "pc"}

_ARMADOS: list = []        # cada confirm.request()
_ENTREGADOS: list = []     # cada trabajo encargado
_FABRICAS: list = []       # la corrutina de cada trabajo (para poder ejecutarla)
_CAPTURADO: list = []      # eventos del bus
_ARRANQUES: list = []      # cada ensure_up() con su force
_REMEMBERS: list = []      # lo que se habría guardado en Postgres


async def _submit(titulo, fabrica, **kw):
    _ENTREGADOS.append({"titulo": titulo, **kw})
    _FABRICAS.append(fabrica)
    return "job-de-prueba"


async def _ensure(ctx, force=False):
    _ARRANQUES.append(bool(force))
    return True


async def _emit_espia(tipo, data=None):
    _CAPTURADO.append((tipo, data))


_ORIG_REQUEST = confirm.request


def _request_espia(*a, **kw):
    _ARMADOS.append(dict(kw))
    return _ORIG_REQUEST(*a, **kw)


_ORIG_NET_CLIENT = net.client


def _instalar_dobles() -> None:
    async def _no(*a, **k):
        return False

    async def _si(*a, **k):
        return True

    async def _cerebro(ctx):
        return "ok", ""

    mod._alive = _si                 # el gateway "vive": no se sondea de verdad
    mod._port_open = _si
    mod._auth_ok = _si
    mod.installed = lambda ctx: True
    mod._hermes_exe = lambda ctx: "C:/hermes-de-prueba/hermes.exe"
    mod.ensure_up = _ensure
    mod.provision_env = lambda ctx: (False, [])
    mod.provision_engram_mcp = lambda ctx: (False, "doble de prueba")
    mod._gateway_log_tail = lambda n=12: ""
    mod._probe_brain = _cerebro
    job_mgr.submit = _submit
    bus.emit = _emit_espia
    confirm.request = _request_espia
    pg.remember = lambda *a, **k: _REMEMBERS.append(a)


_instalar_dobles()


# ══════════════════════════════════════════════════════════════════════════════
#  ESTADO LIMPIO ENTRE ESCENARIOS
# ══════════════════════════════════════════════════════════════════════════════
_ORDEN = "busca proveedores de cajas de cartón y hazme un informe comparativo"


def _ajustes(proveedor: str = "gemini", delegacion_nube: bool = True,
             fallback_nube: bool = False) -> _Ajustes:
    """Los DOS consentimientos son claves distintas y se fijan por separado:
    `permitir_delegacion_nube` (entregar un encargo a un cerebro de nube) y
    `permitir_fallback_nube` (que el cerebro de NEXUS caiga a la nube)."""
    ajustes = _Ajustes({"hermes_provider": proveedor,
                        "permitir_delegacion_nube": delegacion_nube,
                        "permitir_fallback_nube": fallback_nube})
    CTX["settings"] = ajustes
    mod._SETTINGS[0] = ajustes
    return ajustes


def _yaml(contenido: str | None) -> None:
    ruta = _HERMES_HOME / "config.yaml"
    if contenido is None:
        try:
            ruta.unlink()
        except OSError:
            pass
    else:
        ruta.write_text(contenido, encoding="utf-8")


def _reset(proveedor: str = "gemini", delegacion_nube: bool = True,
           yaml: str | None = None, fallback_nube: bool = False) -> None:
    for lista in (_ARMADOS, _ENTREGADOS, _FABRICAS, _CAPTURADO, _ARRANQUES,
                  _REMEMBERS, _ClienteFalso.llamadas, _ClienteFalso.guion):
        lista.clear()
    confirm.clear()
    _yaml(yaml)
    _ajustes(proveedor, delegacion_nube, fallback_nube)
    presupuesto._DOC = None
    try:
        presupuesto.ruta_archivo().unlink()
    except OSError:
        pass


def run(coro):
    return asyncio.run(coro)


def _posts() -> list:
    return [c for c in _ClienteFalso.llamadas if c[0] == "POST"]


# ══════════════════════════════════════════════════════════════════════════════
#  1. LA CLASE DEL CEREBRO DEL EJECUTOR SALE DE `llm.localidad_delegado`
# ══════════════════════════════════════════════════════════════════════════════
def test_la_localidad_reusa_la_tabla_de_llm():
    print("· el cerebro del ejecutor se clasifica con la MISMA tabla que el chat")
    fuente = Path(SKILL_PY).read_text(encoding="utf-8")
    check("localidad_delegado" in fuente,
          "hermes/skill.py no usa la clasificación de localidad de llm.py")
    check("LOCALIDAD = {" not in fuente and "LOCALIDAD: dict" not in fuente,
          "hermes/skill.py mantiene una SEGUNDA tabla de proveedores")
    check("def localidad" not in fuente,
          "hermes/skill.py reimplementa la clasificación de localidad")

    # la clasificación en sí
    check(llm.localidad_delegado("ollama") == "local", "ollama debe ser local")
    check(llm.localidad_delegado("mock") == "local", "mock debe ser local")
    for nube in ("openai", "anthropic", "gemini", "cloud", "openrouter", ""):
        check(llm.localidad_delegado(nube) == "nube",
              f"«{nube or '<sin configurar>'}» debe tratarse como nube")
    # un nombre que la tabla no conoce solo es local si su endpoint es de casa
    check(llm.localidad_delegado("custom", "http://127.0.0.1:11434/v1") == "local",
          "un endpoint de loopback debe poder ser local")
    check(llm.localidad_delegado("custom", "https://api.openai.com/v1") == "nube",
          "«custom» contra internet es nube")
    check(llm.localidad_delegado("custom", "") == "nube",
          "ante la duda (sin endpoint) se trata como nube")


# ══════════════════════════════════════════════════════════════════════════════
#  2. CEREBRO EN LA NUBE CON LA DELEGACIÓN APAGADA: CERO PETICIONES
# ══════════════════════════════════════════════════════════════════════════════
def test_nube_con_delegacion_apagada_rechaza_sin_una_sola_peticion():
    print("· nube + permitir_delegacion_nube=false → rechazo y CERO peticiones")
    _reset("gemini", delegacion_nube=False)
    respuesta = run(mod.delegate(_ORDEN, CTX, "pc"))
    texto = respuesta.get("reply", "")
    check(bool(texto.strip()), "el rechazo no puede quedarse sin respuesta")
    check("desactivada" in texto,
          f"el rechazo no dice que la delegación a la nube está desactivada ({texto!r})")
    check("permitir_delegacion_nube" in texto,
          f"el rechazo no nombra la clave que lo decide ({texto!r})")
    check("config/settings.json" in texto,
          "el rechazo no dice DÓNDE se activa")
    check("modelo local" in texto,
          "el rechazo no ofrece la alternativa sin permiso (modelo local)")
    check(not _ClienteFalso.llamadas,
          f"no debe salir ni una petición ({_ClienteFalso.llamadas})")
    check(not _ENTREGADOS, "no debe crearse ningún trabajo")
    check(confirm.pending("pc") is None,
          "un rechazo no debe dejar una confirmación armada")
    check(not _ARMADOS, "no se arma confirmación para algo que no se va a hacer")

    print("· `permitir_fallback_nube` NO interviene: true no desbloquea la delegación")
    _reset("gemini", delegacion_nube=False, fallback_nube=True)
    run(mod.delegate(_ORDEN, CTX, "pc"))
    check(not _ENTREGADOS and confirm.pending("pc") is None,
          "el consentimiento de la RESERVA del cerebro no debe abrir la delegación")
    check(not _ClienteFalso.llamadas, "ni debe hacer peticiones")

    # un cerebro que Hermes va a usar con un endpoint de internet es nube igual
    _reset("", delegacion_nube=False,
           yaml='model:\n  default: "gpt-x"\n  provider: "custom"\n'
                '  base_url: "https://api.openai.com/v1"\n')
    run(mod.delegate(_ORDEN, CTX, "pc"))
    check(not _ClienteFalso.llamadas, "«custom» contra internet: cero peticiones")


def test_nube_permitida_sigue_y_avisa_por_el_bus():
    print("· nube + permitir_delegacion_nube=true (el defecto) → sigue y avisa")
    # La configuración REAL del dueño: cerebro de Hermes en la nube (gemini) y
    # `permitir_fallback_nube` SIN poner (False). Antes esto apagaba la función.
    _reset("gemini", delegacion_nube=True, fallback_nube=False)
    respuesta = run(mod.delegate(_ORDEN, CTX, "pc"))
    check(confirm.pending("pc") is not None,
          "con el permiso de delegación, lo siguiente es la confirmación")
    check(_ORDEN in respuesta.get("reply", ""),
          f"la pregunta enseña el encargo exacto ({respuesta.get('reply')!r})")
    check(not _ClienteFalso.llamadas, "armar la confirmación no hace peticiones")
    avisos = [d.get("msg", "") for t, d in _CAPTURADO
              if t == "log" and isinstance(d, dict)]
    nube = [m for m in avisos if "nube" in m.lower()]
    check(bool(nube), f"no se avisa por el bus de que el trabajo sale a la nube ({avisos})")
    check(any("permitir_delegacion_nube" in m for m in nube),
          "el aviso no dice con qué clave se apaga")
    check(any("gemini" in m for m in nube), "el aviso no dice a qué proveedor va")
    check("sk-" not in " ".join(avisos).lower(),
          "el aviso no puede llevar una clave")
    # El operador tiene que saber que sale del equipo ANTES de decir «sí».
    texto = respuesta.get("reply", "")
    check("está en la nube" in texto and "saldrán de este equipo" in texto,
          f"la confirmación no avisa de que el encargo sale a la nube ({texto!r})")
    check("permitir_delegacion_nube" in texto,
          "la confirmación no dice cómo dejar de sacar encargos a la nube")


# ══════════════════════════════════════════════════════════════════════════════
#  3. CEREBRO LOCAL: NO NECESITA NINGÚN PERMISO DE NUBE
# ══════════════════════════════════════════════════════════════════════════════
def test_cerebro_local_no_necesita_permiso():
    print("· ollama local → procede aunque la delegación a la nube esté apagada")
    _reset("ollama", delegacion_nube=False)
    run(mod.delegate(_ORDEN, CTX, "pc"))
    check(confirm.pending("pc") is not None,
          "un cerebro local no debe rechazarse: toca confirmar y seguir")
    avisos = [d.get("msg", "") for t, d in _CAPTURADO
              if t == "log" and isinstance(d, dict)]
    check(not [m for m in avisos if "nube" in m.lower()],
          f"no debe avisarse de nube con un cerebro local ({avisos})")

    print("· un endpoint de casa, con nombre que la tabla no conoce, también es local")
    _reset("", delegacion_nube=False,
           yaml='model:\n  default: "qwen3:8b"\n  provider: "custom"\n'
                '  base_url: "http://127.0.0.1:11434/v1"\n')
    run(mod.delegate(_ORDEN, CTX, "pc"))
    check(confirm.pending("pc") is not None,
          "un Hermes apuntado a loopback es local aunque su proveedor se llame «custom»")
    check(not _ENTREGADOS, "armar la confirmación no ejecuta el encargo")


# ══════════════════════════════════════════════════════════════════════════════
#  4. CONFIRMACIÓN: UNA VEZ, Y SOLO CON «SÍ»
# ══════════════════════════════════════════════════════════════════════════════
def test_la_primera_delegacion_pregunta_y_solo_ejecuta_con_si():
    print("· la primera entrega arma confirm.request y NO ejecuta")
    _reset("ollama")
    pregunta = run(mod.delegate(_ORDEN, CTX, "pc", request_id="req-1"))
    pendiente = confirm.pending("pc")
    check(pendiente is not None, "no se armó ninguna confirmación")
    check(bool(pendiente) and pendiente.get("kind") == "delegacion_hermes",
          f"el tipo de confirmación no es delegacion_hermes ({pendiente})")
    check(bool(pendiente) and pendiente.get("destructive") is False,
          "delegar no es destructivo: destructive debe ser False")
    check(_ORDEN in pregunta.get("reply", ""),
          "la pregunta no enseña el texto EXACTO que recibirá el ejecutor")
    check(not _ENTREGADOS, "armar la confirmación no puede encargar nada")
    check(not _posts(), "armar la confirmación no hace ninguna petición")
    check(len(_ARMADOS) == 1, f"se armó {len(_ARMADOS)} vez/veces")

    print("· «sí» encarga UNA vez")
    respuesta = run(confirm.answer("sí", "pc"))
    check(len(_ENTREGADOS) == 1,
          f"con «sí» debe encargarse UNA vez ({len(_ENTREGADOS)})")
    check(bool(respuesta) and "ya lo tengo en marcha" not in respuesta.lower(),
          f"el «sí» no devolvió el acuse ({respuesta!r})")
    check(_ENTREGADOS and _ENTREGADOS[0].get("kind") == "hermes",
          "el trabajo encargado no queda marcado como hermes")
    check("req-1" in str(_ENTREGADOS[0].get("request_id", "")),
          "el requestId del operador no llega al trabajo")

    print("· «no» no encarga nada")
    _reset("ollama")
    run(mod.delegate(_ORDEN, CTX, "pc"))
    respuesta = run(confirm.answer("no", "pc"))
    check(not _ENTREGADOS, "con «no» no se encarga nada")
    check(bool(respuesta), "el «no» debe contestarse algo al operador")

    print("· cambiar de tema DESARMA (no se dispara tres mensajes después)")
    _reset("ollama")
    run(mod.delegate(_ORDEN, CTX, "pc"))
    respuesta = run(confirm.answer("explícame otra cosa del tablero", "pc"))
    check(respuesta is None, f"un cambio de tema no debe responder «sí/no» ({respuesta!r})")
    check(confirm.pending("pc") is None, "la confirmación debe quedar desarmada")
    check(not _ENTREGADOS, "un cambio de tema no puede encargar nada")


def test_la_confirmacion_solo_se_responde_desde_texto_o_voz():
    print("· la respuesta a la confirmación sigue siendo solo de texto/voz")
    fuente = Path(BRAIN_PY).read_text(encoding="utf-8")
    corte = fuente.index("_cf.answer(text, channel)")
    bloque = fuente[max(0, corte - 500):corte]
    check('if source in ("text", "voice")' in bloque,
          "la confirmación se resolvería desde canales que no son texto/voz")

    print("· n8n sigue rechazando antes de llegar a Hermes")
    from backend.core.aplicacion import skills_loader as sl
    ruta = sl.route("hermes: investiga la competencia y hazme un informe")
    check(bool(ruta) and ruta[0].folder == "hermes",
          "la frase de prueba ya no enruta a hermes")
    check(canales.es_restringido("n8n"), "n8n debe seguir siendo un canal restringido")
    check(not canales.permitido("n8n", ruta),
          "n8n no puede delegar en el ejecutor")
    check("no está permitida" in canales.rechazo("n8n").get("reply", ""),
          "el rechazo de canal debe seguir siendo el mismo")


# ══════════════════════════════════════════════════════════════════════════════
#  5. REINTENTOS: ANTES DE ENTREGAR ≠ DESPUÉS DE ENTREGAR
# ══════════════════════════════════════════════════════════════════════════════
def _correr_encargo(texto_bueno: str = "Informe listo"):
    _ClienteFalso.guion.append(_ok(texto_bueno))
    return run(mod._run_hermes(_ORDEN, "http://127.0.0.1:8642", {}, "pc", "", 1))


def test_fallo_antes_de_entregar_reintenta_una_vez():
    print("· no se pudo conectar → relanza y prueba UNA vez más (2 entregas)")
    _reset("ollama")
    _ClienteFalso.guion.append(httpx.ConnectError("conexión rechazada (doble)"))
    resultado = _correr_encargo("Informe de prueba")
    check(len(_posts()) == 2,
          f"debían ser exactamente 2 entregas ({len(_posts())})")
    check(True in _ARRANQUES,
          "no se relanzó el servicio antes de reintentar")
    check("Informe de prueba" in resultado.get("reply", ""),
          f"el encargo bueno no se canta como hecho ({resultado.get('reply')!r})")

    print("· si el relanzamiento falla, no se finge un reintento")
    _reset("ollama")

    async def _no_arranca(ctx, force=False):
        # el primer arranque sí (el servicio estaba «vivo»); el RELANZAMIENTO no
        _ARRANQUES.append(bool(force))
        return not force

    mod.ensure_up = _no_arranca
    _ClienteFalso.guion.append(httpx.ConnectError("conexión rechazada (doble)"))
    try:
        _correr_encargo()
        fallo = ""
    except RuntimeError as exc:                            # noqa: BLE001
        fallo = str(exc)
    finally:
        mod.ensure_up = _ensure
    check(len(_posts()) == 1, f"no se reintenta sin servicio ({len(_posts())})")
    check("No pude entregar" in fallo,
          f"el mensaje debe decir que no se entregó ({fallo!r})")
    check("puede haber" not in fallo.lower(),
          "si no se entregó, no puede decirse que pudo ejecutarse")


def test_fallo_despues_de_entregar_no_se_reenvia():
    print("· 5xx DESPUÉS de entregar → 1 sola entrega y mensaje honesto")
    for status, cuerpo in ((500, "boom"), (502, "bad gateway"),
                           (401, '{"error":"invalid_api_key"}')):
        _reset("ollama")
        _ClienteFalso.guion.append(_Respuesta(status, {}, cuerpo))
        try:
            _correr_encargo()
            fallo = ""
        except RuntimeError as exc:                        # noqa: BLE001
            fallo = str(exc)
        check(len(_posts()) == 1,
              f"con HTTP {status} se reenvió el encargo ({len(_posts())})")
        check(True not in _ARRANQUES,
              f"con HTTP {status} no debe relanzarse nada")
        check("puede haber hecho" in fallo,
              f"con HTTP {status} no se avisa de que pudo ejecutarse ({fallo!r})")
        check("NO lo repito" in fallo,
              f"con HTTP {status} no se dice que no se repite")
        check("trabajo" in fallo,
              f"con HTTP {status} no se dice cómo seguir ({fallo!r})")
        check(fallo.rstrip().endswith("confirmación."),
              f"con HTTP {status} el mensaje se corta antes de decir cómo seguir "
              f"({fallo!r})")

    print("· timeout DESPUÉS de enviar → misma familia: no se reenvía")
    _reset("ollama")
    _ClienteFalso.guion.append(httpx.ReadTimeout("el modelo tardó demasiado"))
    try:
        _correr_encargo()
        fallo = ""
    except RuntimeError as exc:                            # noqa: BLE001
        fallo = str(exc)
    check(len(_posts()) == 1, f"un timeout no puede reenviar ({len(_posts())})")
    check("puede haber hecho" in fallo,
          f"un timeout tras enviar tampoco se da por no ocurrido ({fallo!r})")
    check(True not in _ARRANQUES, "un timeout no debe relanzar el servicio")

    print("· un 401 del cerebro interno conserva su mensaje de siempre")
    _reset("ollama")
    _ClienteFalso.guion.append(_Respuesta(401, {}, "Missing Authentication header"))
    try:
        _correr_encargo()
        fallo = ""
    except RuntimeError as exc:                            # noqa: BLE001
        fallo = str(exc)
    check(len(_posts()) == 1, "el 401 del cerebro interno tampoco se reenvía")
    check("MODELO DE IA" in fallo,
          f"se perdió el mensaje accionable del cerebro sin credenciales ({fallo!r})")
    check("NO lo repito" not in fallo,
          "un cerebro sin credenciales no ha ejecutado nada: no debe decir que sí")


def test_un_encargo_ya_aprobado_no_vuelve_a_preguntar():
    print("· tras el «sí», sus reintentos NO arman otra confirmación")
    _reset("ollama")
    _ClienteFalso.guion.append(httpx.ConnectError("conexión rechazada (doble)"))
    _ClienteFalso.guion.append(_ok("Informe listo"))

    async def _flujo():
        await mod.delegate(_ORDEN, CTX, "pc", request_id="req-9")
        await confirm.answer("sí", "pc")
        return await _FABRICAS[-1]()

    resultado = run(_flujo())
    check(len(_ENTREGADOS) == 1, "el trabajo se encarga una sola vez")
    check(len(_ARMADOS) == 1,
          f"el reintento volvió a preguntar ({len(_ARMADOS)} confirmaciones)")
    check(confirm.pending("pc") is None,
          "no debe quedar nada armado después de reintentar")
    check(len(_posts()) == 2, f"el reintento legítimo son 2 entregas ({len(_posts())})")
    check("Informe listo" in resultado.get("reply", ""),
          "el trabajo aprobado termina bien tras el reintento")


# ══════════════════════════════════════════════════════════════════════════════
#  6. EL CONTADOR DEL DÍA: DELEGACIONES, NO TOKENS
# ══════════════════════════════════════════════════════════════════════════════
def _disco() -> dict:
    """El archivo del contador tal cual está en disco ({} si aún no existe)."""
    try:
        return json.loads(presupuesto.ruta_archivo().read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return {}


def test_el_contador_apunta_la_delegacion_sin_tokens():
    print("· el encargo queda en el contador del día, por proveedor y sin tokens")
    _reset("ollama")
    run(mod.delegate(_ORDEN, CTX, "pc"))
    run(confirm.answer("sí", "pc"))

    resumen = presupuesto.resumen()
    check(resumen.get("delegaciones", {}).get("ollama") == 1,
          f"la delegación no queda contada ({resumen.get('delegaciones')})")
    check(resumen.get("delegaciones_total") == 1,
          f"el total de delegaciones no cuadra ({resumen.get('delegaciones_total')})")
    check(resumen.get("llamadas") == 0,
          f"una delegación NO es una llamada de nexus ({resumen.get('llamadas')})")
    check(resumen.get("caracteres") == 0,
          f"una delegación no puede inventar caracteres ({resumen.get('caracteres')})")
    check(resumen.get("por_proveedor", {}) == {},
          f"la delegación no puede colarse como proveedor del chat "
          f"({resumen.get('por_proveedor')})")

    disco = _disco()
    check(disco.get("delegaciones", {}).get(presupuesto._hoy(), {}).get("ollama") == 1,
          "la delegación no está en el archivo del día")
    crudo = json.dumps(disco.get("delegaciones"))
    check("tokens" not in crudo,
          f"el contador de delegaciones no puede fingir tokens ({crudo})")

    print("· un rechazo por localidad NO cuenta como delegación")
    _reset("gemini", delegacion_nube=False)
    run(mod.delegate(_ORDEN, CTX, "pc"))
    check(presupuesto.resumen().get("delegaciones", {}) == {},
          "lo que no se delega no puede contarse como delegado")


def test_api_status_publica_las_delegaciones_sin_claves():
    print("· GET /api/status publica las delegaciones del día, sin claves")
    _reset("ollama")
    run(mod.delegate(_ORDEN, CTX, "pc"))
    run(confirm.answer("sí", "pc"))

    # Para ESTA prueba se necesita el cliente HTTP real (ASGITransport), pero el
    # cliente compartido de nexus sigue doblado: ningún endpoint sale a la red.
    httpx.AsyncClient = _REAL_ASYNC_CLIENT
    net.client = lambda: _ClienteFalso()
    try:
        import backend.app as servidor

        async def _pide():
            transporte = httpx.ASGITransport(app=servidor.app,
                                             client=("127.0.0.1", 4321))
            async with httpx.AsyncClient(transport=transporte,
                                         base_url="http://127.0.0.1:8177") as cliente:
                return await cliente.get("/api/status",
                                         headers={"host": "127.0.0.1:8177"})

        respuesta = run(_pide())
        check(respuesta.status_code == 200,
              f"/api/status contesta bien ({respuesta.status_code})")
        cuerpo = respuesta.json()
        datos = cuerpo.get("presupuesto", {})
        check(datos.get("delegaciones", {}).get("ollama") == 1,
              f"/api/status no publica las delegaciones ({datos.get('delegaciones')})")
        check(datos.get("delegaciones_total") == 1,
              f"/api/status no publica el total ({datos.get('delegaciones_total')})")
        texto = respuesta.text
        check("dpapi:" not in texto, "el estado no puede publicar el almacén cifrado")
        clave = settings.secret("hermes_api_key") or ""
        check(not clave or clave not in texto,
              "el estado no puede publicar la clave del ejecutor")
    finally:
        net.client = _ORIG_NET_CLIENT
        httpx.AsyncClient = _ClienteFalso


def test_el_endpoint_rechaza_la_clave_desde_fuera():
    """`permitir_delegacion_nube` es guarda de privacidad: 403 fuera, y no cambia."""
    print("· POST /api/config remoto de permitir_delegacion_nube → 403 y nada cambia")
    _reset("ollama")
    httpx.AsyncClient = _REAL_ASYNC_CLIENT
    net.client = lambda: _ClienteFalso()
    try:
        import backend.app as servidor

        token = "token-de-prueba-de-delegacion"
        settings.set_secret("link_token", token)
        check("permitir_delegacion_nube" in servidor._CLAVES_SOLO_LOCALES,
              "la clave nueva no está entre las que solo se cambian en local")

        def _post(clave, valor, peer):
            async def _pide():
                transporte = httpx.ASGITransport(app=servidor.app, client=(peer, 4321))
                async with httpx.AsyncClient(transport=transporte,
                                             base_url="http://127.0.0.1:8177") as c:
                    return await c.post("/api/config", json={clave: valor},
                                        headers={"x-nexus-token": token})
            return run(_pide())

        def _get(clave):
            async def _pide():
                transporte = httpx.ASGITransport(app=servidor.app, client=("127.0.0.1", 4321))
                async with httpx.AsyncClient(transport=transporte,
                                             base_url="http://127.0.0.1:8177") as c:
                    return await c.get("/api/config", headers={"host": "127.0.0.1:8177"})
            return run(_pide()).json()

        # La clave nueva es una guarda de privacidad: sale en ⚙ (GET) con su
        # defecto true, que NO corta la función.
        check(settings.get("permitir_delegacion_nube") is True,
              "el defecto de permitir_delegacion_nube debe ser true")
        check(_get("permitir_delegacion_nube").get("permitir_delegacion_nube") is True,
              "GET /api/config debe publicar el defecto true de la delegación a la nube")

        antes = settings.get("permitir_delegacion_nube")
        remoto = _post("permitir_delegacion_nube", False, "192.168.1.77")
        check(remoto.status_code == 403,
              f"un POST remoto de la clave debe dar 403, dio {remoto.status_code}")
        check("permitir_delegacion_nube" in str((remoto.json() or {}).get("error", "")),
              "el 403 debe nombrar la clave rechazada")
        check(settings.get("permitir_delegacion_nube") == antes,
              "el 403 no debe cambiar el valor")
        # y desde la ventana local sí se puede apagar (es la salida del dueño)
        local = _post("permitir_delegacion_nube", False, "127.0.0.1")
        check(local.status_code == 200,
              f"desde este equipo debe poder cambiarse, dio {local.status_code}")
        check(settings.get("permitir_delegacion_nube") is False,
              "desde este equipo el cambio debe aplicarse")
        settings.set("permitir_delegacion_nube", True)   # dejar el defecto
    finally:
        net.client = _ORIG_NET_CLIENT
        httpx.AsyncClient = _ClienteFalso


# ══════════════════════════════════════════════════════════════════════════════
#  7. LA HONESTIDAD DEL MENSAJE FINAL SIGUE EN PIE (`304fd64`)
# ══════════════════════════════════════════════════════════════════════════════
def test_la_clasificacion_vacia_sigue_siendo_un_error():
    print("· una respuesta 200 con contenido vacío no se canta como hecha")
    _reset("ollama")
    try:
        _correr_encargo("")
        fallo = ""
    except RuntimeError as exc:                            # noqa: BLE001
        fallo = str(exc)
    check(bool(fallo.strip()), "el contenido vacío debe seguir siendo un fallo")
    check(mod.respuesta_es_error("") != "",
          "el clasificador puro de contenido vacío se ha tocado")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    for prueba in (test_la_localidad_reusa_la_tabla_de_llm,
                   test_nube_con_delegacion_apagada_rechaza_sin_una_sola_peticion,
                   test_nube_permitida_sigue_y_avisa_por_el_bus,
                   test_cerebro_local_no_necesita_permiso,
                   test_la_primera_delegacion_pregunta_y_solo_ejecuta_con_si,
                   test_la_confirmacion_solo_se_responde_desde_texto_o_voz,
                   test_fallo_antes_de_entregar_reintenta_una_vez,
                   test_fallo_despues_de_entregar_no_se_reenvia,
                   test_un_encargo_ya_aprobado_no_vuelve_a_preguntar,
                   test_el_contador_apunta_la_delegacion_sin_tokens,
                   test_api_status_publica_las_delegaciones_sin_claves,
                   test_el_endpoint_rechaza_la_clave_desde_fuera,
                   test_la_clasificacion_vacia_sigue_siendo_un_error):
        try:
            prueba()
        except Exception as exc:                            # noqa: BLE001
            # Una prueba que revienta cuenta como fallo SUYO y no esconde las demás.
            check(False, f"{prueba.__name__} revienta: {type(exc).__name__}: {exc}")
    print(f"\n{'#' * 54}\ntest_delegacion: {_pass} OK, {len(_fail)} fallos")
    for f in _fail:
        print("  - " + f)
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        codigo = main()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(codigo)
