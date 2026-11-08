# -*- coding: utf-8 -*-
"""CEREBRO ABIERTO DE HERMES + NaN COMO PROVEEDOR (T42, specs S3 y S5).

Lo que pidió el dueño (07/11/2026, literal): «A Hermes también se le ha de poner
cualquier LLM incluido NaN». Lo que había era una lista CERRADA de cuatro nombres
en `skills/hermes/skill.py` (`_PROV_MAP`): cualquier otro endpoint contestaba
«proveedor no soportado» aunque Hermes hable `/chat/completions` con
`Authorization: Bearer` — es decir, aunque sea compatible OpenAI.

Lo que se comprueba aquí:

  1. LOS CUATRO PRESETS NO CAMBIAN. `openai`, `anthropic`, `gemini` y
     `openrouter` escriben EXACTAMENTE los mismos bytes que antes (misma variable
     del `.env`, mismo `provider`, misma `base_url`, mismos cambios en la lista):
     hay `~/.hermes/config.yaml` de usuarios y pruebas que dependen de ellos.
  2. NaN ES UN PRESET. `provider="nan"` deja el `.env` y el `config.yaml` con la
     base de NaN Builders, y guarda la clave en nexus bajo `nan_api_key` — NO bajo
     `openai_api_key`, que es la que `llm.OpenAIProvider` manda a api.openai.com.
  3. CAMINO ABIERTO. Cualquier etiqueta CON una `base_url` vale (Groq, DeepSeek,
     un llama.cpp de casa), y esa base se VALIDA antes de escribir nada con la
     guarda de destinos de SEC-11: solo http/https, sin `usuario:clave@`, con
     host, y loopback permitido (un gateway local es legítimo). `file://`, un
     userinfo, una dirección de metadatos o un dominio que no resuelve se
     rechazan en español y NO se escribe NADA (ni `.env`, ni `config.yaml`, ni
     los ajustes).
  4. LA CLAVE NO SE FILTRA. `nan_api_key` y `hermes_custom_api_key` están en
     `Settings.SECRET_KEYS`: `GET /api/config` los quita siempre y publica solo
     `has_…`.
  5. NEXUS HABLA CON UN ENDPOINT CON FORMA DE NaN. Con `llm_provider="cloud"` y
     `cloud_base_url` apuntando a NaN: la ruta es `/chat/completions`, la clave va
     en `Authorization: Bearer`, el cuerpo lleva el modelo y el tope de salida de
     T6 — y NO lleva el bloque `provider.data_collection` de OpenRouter (eso se
     decide por la URL, no por el nombre) ni ningún campo inventado. La clave no
     aparece en la URL (la lección de `ce90957`) ni en el cuerpo.

TODO EN PROCESO Y SIN RED: `NEXUS_CONFIG_DIR`/`NEXUS_DATA_DIR`/`HERMES_HOME` en
carpetas de usar y tirar puestas ANTES de importar el backend, `net.client()`
doblado antes de la primera llamada, `net._direcciones` (el DNS) doblado también
—la validación de la base resuelve el nombre, y aquí no se sale a internet— y
claves sintéticas (`sk-TEST-SINTETICA-…`). No se lee `config/`, ni `data/`, ni
`~/.hermes` del operador, y no se arranca ningún gateway (H1/H2 del ODD).

Ejecutar:  .venv\\Scripts\\python.exe tests/unit/core/runtime/test_proovedor_abierto.py
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

# ── 0) CAJA DE ARENA ANTES DE IMPORTAR NADA DEL BACKEND ─────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="nexus_prov_abierto_"))
_CFG = _TMP / "config"
_DATA = _TMP / "data"
_HERMES = _TMP / "hermes_home"
for _d in (_CFG, _DATA, _HERMES):
    _d.mkdir(parents=True, exist_ok=True)

# El tope de salida (T6) se lee de aquí: con un valor distinto del de reserva se
# prueba que viaja en el cuerpo el número de `umbrales.json`, no una constante.
(_CFG / "umbrales.json").write_text(
    json.dumps({"llm": {"max_tokens_salida": 1234}}), encoding="utf-8")
(_CFG / "settings.json").write_text(json.dumps({
    "setup_done": True,
    "llm_provider": "cloud",
    "permitir_fallback_nube": True,
    "cloud_base_url": "https://api.nan.builders/v1",
    "cloud_model": "deepseek-v4-flash",
    "tts_engine": "off",
}), encoding="utf-8")
(_CFG / "secrets.json").write_text(json.dumps({
    "cloud_llm_api_key": "sk-TEST-SINTETICA-cloud",
}), encoding="utf-8")
os.environ["NEXUS_CONFIG_DIR"] = str(_CFG)
os.environ["NEXUS_DATA_DIR"] = str(_DATA)
os.environ["HERMES_HOME"] = str(_HERMES)

import httpx  # noqa: E402

from backend.core.comun import net  # noqa: E402
from backend.core.comun.config import Settings, settings  # noqa: E402
from backend.core.infraestructura import llm  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
#  EL DNS, DOBLADO: la validación de la base resuelve el nombre
# ══════════════════════════════════════════════════════════════════════════════
# Nada de `getaddrinfo` de verdad. Los hosts públicos devuelven una dirección de
# internet cualquiera (93.184.216.34 es la de example.com: la usa la RFC 2606 y no
# es de nadie); «no-resuelve.invalid» levanta, que es el caso del dominio que no
# existe (`.invalid` está reservado por la RFC 2606 justo para esto).
_DNS: dict[str, list[str]] = {}
_DNS_ROTO: set[str] = {"no-resuelve.invalid"}


def _direcciones_dobles(host: str) -> list[str]:
    if host in _DNS_ROTO:
        raise OSError("no resuelve (doble de prueba, sin red)")
    return _DNS.get(host, ["93.184.216.34"])


net._direcciones = _direcciones_dobles


# ══════════════════════════════════════════════════════════════════════════════
#  EL CLIENTE HTTP, DOBLADO ANTES DE LA PRIMERA LLAMADA
# ══════════════════════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, obj=None, status: int = 200):
        self._obj = obj if obj is not None else {}
        self.status_code = status
        self.text = json.dumps(self._obj)

    def json(self):
        return self._obj

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://doble-de-prueba"),
                response=httpx.Response(self.status_code))


class _Cliente:
    """`net.client()` doblado: apunta URL, cabeceras y cuerpo de cada POST."""

    def __init__(self):
        self.llamadas: list[dict] = []

    async def post(self, url, headers=None, json=None, **kw):   # noqa: A002
        self.llamadas.append({"url": url, "headers": dict(headers or {}),
                              "json": json})
        return _Resp({"choices": [{"message": {"content": "RESPUESTA-NAN"}}],
                      "usage": {"prompt_tokens": 11, "completion_tokens": 7}})

    async def get(self, url, **kw):
        self.llamadas.append({"url": url, "headers": {}, "json": None})
        return _Resp({})

    def stream(self, method, url, **kw):        # noqa: A002
        raise AssertionError("streaming inesperado en esta prueba")

    def aclose(self):
        return None


_CLI = _Cliente()
_ORIG_CLIENT = net.client
net.client = lambda: _CLI

# La skill, cargada como la carga el cargador de nexus (sin `from . import`).
_spec = importlib.util.spec_from_file_location("hermes_skill_abierta", SKILL_PY)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CTX = {"settings": settings, "channel": "pc"}

_CLAVE_NAN = "sk-TEST-SINTETICA-nan-000"
_CLAVE_ABIERTA = "sk-TEST-SINTETICA-abierta-111"
_CLAVE_PRESET = "sk-TEST-SINTETICA-preset-222"


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
#  HERRAMIENTAS: leer lo que configure_brain dejó en disco / en los ajustes
# ══════════════════════════════════════════════════════════════════════════════
def env_path() -> Path:
    return _HERMES / ".env"


def cfg_path() -> Path:
    return _HERMES / "config.yaml"


def limpiar(carpeta: Path | None = None) -> None:
    """Deja HERMES_HOME como recién creado (y los ajustes sin cerebro)."""
    base = carpeta or _HERMES
    for f in ("", ".env", "config.yaml"):
        p = base / f if f else base
        if p.is_dir():
            for hijo in p.iterdir():
                if hijo.is_file():
                    hijo.unlink()
    for clave in ("hermes_provider", "hermes_model", "hermes_base_url"):
        settings._json.pop(clave, None)
    for clave in ("nan_api_key", "hermes_custom_api_key", "openai_api_key",
                  "anthropic_api_key", "gemini_api_key", "openrouter_api_key"):
        settings.set_secret(clave, "")


def escribir_linea(base: Path, texto: str) -> None:
    (base / "config.yaml").write_text(texto, encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  1. LOS CUATRO PRESETS, BYTE A BYTE
# ══════════════════════════════════════════════════════════════════════════════
# Lo que `configure_brain` tiene que escribir para cada preset. Estas cadenas son
# las de ANTES de T42 (`_yaml_set_model` con `hp` y `base`, `_env_set_var` con la
# variable de cada proveedor): si alguien las toca, esto se pone rojo.
_PRESETS = {
    "openai": ("OPENAI_API_KEY", "custom", "https://api.openai.com/v1",
               "openai_api_key"),
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic", "", "anthropic_api_key"),
    "gemini": ("GEMINI_API_KEY", "gemini", "", "gemini_api_key"),
    "openrouter": ("OPENROUTER_API_KEY", "openrouter", "", "openrouter_api_key"),
}


def test_los_cuatro_presets_no_cambian():
    print("· los cuatro presets escriben los mismos bytes que antes de T42")
    for provider, (env_var, hp, base, secret) in _PRESETS.items():
        limpiar()
        mod.configure_brain(CTX, provider, "modelo-de-prueba", _CLAVE_PRESET)

        esperado_env = f"{env_var}={_CLAVE_PRESET}\n"
        real_env = env_path().read_text(encoding="utf-8") if env_path().exists() else ""
        check(real_env == esperado_env,
              f"{provider}: el .env cambió (esperado {esperado_env!r}, vi {real_env!r})")

        esperado_cfg = ('model:\n  default: "modelo-de-prueba"\n'
                        f'  provider: "{hp}"\n'
                        + (f'  base_url: "{base}"\n' if base else ""))
        real_cfg = cfg_path().read_text(encoding="utf-8") if cfg_path().exists() else ""
        check(real_cfg == esperado_cfg,
              f"{provider}: el bloque model: cambió (esperado {esperado_cfg!r}, "
              f"vi {real_cfg!r})")
        check(settings.secret(secret) == _CLAVE_PRESET,
              f"{provider}: la clave no se guardó en «{secret}»")
        check(settings.get("hermes_provider") == provider,
              f"{provider}: hermes_provider no quedó apuntado")
        check(settings.get("hermes_base_url") == base,
              f"{provider}: hermes_base_url no quedó apuntado ({base!r})")


def test_el_resumen_del_preset_es_el_de_siempre():
    print("· la lista de cambios de un preset sigue diciendo lo mismo")
    limpiar()
    res = mod.configure_brain(CTX, "openai", "modelo-de-prueba", _CLAVE_PRESET)
    check(res.get("ok") is True, f"el preset openai falló: {res}")
    check(res.get("changes") == [
        "OPENAI_API_KEY escrita en ~/.hermes/.env",
        "clave recordada en nexus (openai_api_key)",
        "modelo «modelo-de-prueba» (provider custom) en config.yaml",
    ], f"la lista de cambios cambió: {res.get('changes')}")


# ══════════════════════════════════════════════════════════════════════════════
#  2. NaN, PRESET DE PRIMERA
# ══════════════════════════════════════════════════════════════════════════════
def test_nan_es_un_preset_documentado():
    print("· provider=«nan» deja el cerebro de Hermes apuntando a NaN Builders")
    limpiar()
    limpiar()
    res = mod.configure_brain(CTX, "nan", "deepseek-v4-flash", _CLAVE_NAN)
    check(res.get("ok") is True, f"el preset nan falló: {res}")
    check(res.get("hermes_provider") == "custom",
          f"NaN tiene que usar el proveedor «custom» de Hermes ({res.get('hermes_provider')})")
    check(res.get("base_url") == "https://api.nan.builders/v1",
          f"la base de NaN no es la documentada ({res.get('base_url')!r})")

    real_env = env_path().read_text(encoding="utf-8")
    check(real_env == f"OPENAI_API_KEY={_CLAVE_NAN}\n",
          f"la clave de NaN no se escribió en la variable que lee su proveedor "
          f"«custom» ({real_env!r})")
    real_cfg = cfg_path().read_text(encoding="utf-8")
    for trozo in ('provider: "custom"', 'base_url: "https://api.nan.builders/v1"',
                  'default: "deepseek-v4-flash"'):
        check(trozo in real_cfg,
              f"el config.yaml de NaN no tiene {trozo!r}: {real_cfg!r}")

    print("· la clave de NaN va a SU secreto, no al de OpenAI")
    check(settings.secret("nan_api_key") == _CLAVE_NAN,
          "la clave de NaN no está en nexus bajo «nan_api_key»")
    check(settings.secret("openai_api_key") == "",
          "la clave de NaN NO puede guardarse como openai_api_key: esa es la que "
          "nexus manda a api.openai.com")
    check(settings.get("hermes_base_url") == "https://api.nan.builders/v1",
          "la base de NaN no quedó en los ajustes (⚙ no podría enseñarla)")

    print("· y su cerebro se clasifica por el ENDPOINT: público = nube")
    cerebro = mod.cerebro_de_hermes(CTX)
    check(cerebro["proveedor"] == "nan",
          f"el cerebro no se llama «nan» (sale {cerebro['proveedor']!r})")
    check(cerebro["clase"] == "nube",
          f"un endpoint público tiene que ser nube ({cerebro['clase']!r})")
    check(cerebro["base_url"] == "https://api.nan.builders/v1",
          "la base leída del config.yaml no es la de NaN")


def test_cambiar_de_cerebro_sin_teclar_clave_no_deja_la_clave_ajena():
    """T42-C1 (lo encontró el padre al releer el camino de la clave).

    `configure_brain` escribía la clave SOLO si venía tecleada, pero el paso 3
    reescribía el `config.yaml` con la base NUEVA siempre. Como Hermes guarda la
    clave de su proveedor `custom` en UNA sola variable (`OPENAI_API_KEY`), pasar
    de OpenAI a NaN dejando el campo de la clave vacío dejaba: base de NaN +
    `Authorization: Bearer <clave de OpenAI>`. O sea una credencial enviada al
    host equivocado, que es justo lo que el comentario de este módulo prometía
    que no podía pasar.

    La regla nueva: o nexus tiene una clave para ESE endpoint (la que teclea el
    dueño ahora, o la suya guardada en `config/secrets.json` desde T13) y la
    escribe junto a la base, o NO cambia nada y lo dice.
    """
    print("· cambiar de proveedor sin teclear clave no puede dejar la clave del anterior")
    limpiar()
    res = mod.configure_brain(CTX, "openai", "modelo-de-prueba", _CLAVE_PRESET)
    check(res.get("ok") is True, f"preset openai: {res}")
    check(env_path().read_text(encoding="utf-8") == f"OPENAI_API_KEY={_CLAVE_PRESET}\n",
          "el preset openai no dejó su clave en la variable")

    print("· 1) NaN con su clave GUARDADA: la variable tiene que pasar a ser la de NaN")
    settings.set_secret("nan_api_key", _CLAVE_NAN)
    res = mod.configure_brain(CTX, "nan", "deepseek-v4-flash", "")
    check(res.get("ok") is True, f"nan sin clave tecleada debería valer con la guardada: {res}")
    env = env_path().read_text(encoding="utf-8")
    check(env == f"OPENAI_API_KEY={_CLAVE_NAN}\n",
          f"la variable de Hermes conserva la clave del proveedor ANTERIOR: {env!r}")
    cfg = cfg_path().read_text(encoding="utf-8")
    check('base_url: "https://api.nan.builders/v1"' in cfg,
          f"el config.yaml no quedó con la base de NaN: {cfg!r}")

    print("· 2) endpoint nuevo SIN clave guardada: se rechaza y NO se toca nada")
    env_antes, cfg_antes = env_path().read_text(encoding="utf-8"), cfg_path().read_text(encoding="utf-8")
    base_antes = settings.get("hermes_base_url")
    res = mod.configure_brain(CTX, "groq", "llama-3.3-70b", "",
                              base_url="https://api.groq.com/openai/v1")
    check(res.get("ok") is False,
          f"configurar un endpoint sin ninguna clave disponible no puede dar ok: {res}")
    error = str(res.get("error") or "")
    check("clave" in error.lower(),
          f"la negativa tiene que decir qué falta («clave»): {error!r}")
    check(env_path().read_text(encoding="utf-8") == env_antes,
          "el rechazo no debe tocar la variable de Hermes")
    check(cfg_path().read_text(encoding="utf-8") == cfg_antes,
          "el rechazo no debe tocar el config.yaml (la base seguiría siendo NaN)")
    check(settings.get("hermes_base_url") == base_antes,
          "el rechazo no debe mover hermes_base_url")

    print("· 3) y con la clave tecleada, esa SÍ entra y la anterior sale de la variable")
    res = mod.configure_brain(CTX, "groq", "llama-3.3-70b", _CLAVE_ABIERTA,
                              base_url="https://api.groq.com/openai/v1")
    check(res.get("ok") is True, f"groq con clave y base: {res}")
    env = env_path().read_text(encoding="utf-8")
    check(env == f"OPENAI_API_KEY={_CLAVE_ABIERTA}\n",
          f"la clave de groq no sustituyó a la anterior: {env!r}")
    check(_CLAVE_NAN not in env and _CLAVE_PRESET not in env,
          f"una clave ajena sigue conviviendo con la nueva en el .env: {env!r}")
    cerebro = mod.cerebro_de_hermes(CTX)
    check(cerebro["proveedor"] == "groq" and cerebro["clase"] == "nube",
          f"el cerebro no refleja el endpoint elegido ({cerebro})")


# ══════════════════════════════════════════════════════════════════════════════
#  3. EL CAMINO ABIERTO
# ══════════════════════════════════════════════════════════════════════════════
def test_cualquier_endpoint_compatible_openai():
    print("· una etiqueta + base_url pública se configura (Groq, DeepSeek…)")
    limpiar()
    res = mod.configure_brain(CTX, "groq", "llama-3.3-70b",
                              _CLAVE_ABIERTA, base_url="https://api.groq.com/openai/v1")
    check(res.get("ok") is True, f"el camino abierto falló: {res}")
    check(res.get("hermes_provider") == "custom",
          "un endpoint abierto usa el proveedor «custom» de Hermes")
    check(res.get("base_url") == "https://api.groq.com/openai/v1",
          f"la base escrita no es la tecleada ({res.get('base_url')!r})")
    check('base_url: "https://api.groq.com/openai/v1"' in cfg_path().read_text(encoding="utf-8"),
          "el config.yaml no apunta a la base tecleada")
    check(settings.secret("hermes_custom_api_key") == _CLAVE_ABIERTA,
          "la clave del endpoint abierto no está en «hermes_custom_api_key»")
    check(settings.secret("openai_api_key") == "",
          "la clave de un endpoint abierto NO puede guardarse como openai_api_key")
    check(settings.get("hermes_provider") == "groq",
          f"la etiqueta elegida no se guardó ({settings.get('hermes_provider')!r})")
    cerebro = mod.cerebro_de_hermes(CTX)
    check(cerebro["proveedor"] == "groq",
          f"el cerebro no conserva la etiqueta del operador ({cerebro['proveedor']!r})")
    check(cerebro["clase"] == "nube", "un endpoint público es nube")

    print("· y con etiqueta «custom» también (el nombre genérico)")
    limpiar()
    res = mod.configure_brain(CTX, "custom", "qwen3:8b", _CLAVE_ABIERTA,
                              base_url="http://127.0.0.1:11434/v1")
    check(res.get("ok") is True, f"el camino abierto con loopback falló: {res}")
    cerebro = mod.cerebro_de_hermes(CTX)
    check(cerebro["proveedor"] == "custom",
          f"la etiqueta «custom» se perdió ({cerebro['proveedor']!r})")
    check(cerebro["clase"] == "local",
          f"un endpoint de loopback tiene que ser local ({cerebro['clase']!r})")


def test_la_base_loopback_se_normaliza():
    print("· la barra final sobrante no se guarda (dos formas de la misma base)")
    limpiar()
    res = mod.configure_brain(CTX, "custom", "qwen3:8b", "",
                              base_url="http://localhost:8080/v1/")
    check(res.get("ok") is True, f"loopback con barra final rechazado: {res}")
    check(res.get("base_url") == "http://localhost:8080/v1",
          f"la base no se normalizó ({res.get('base_url')!r})")
    check(settings.get("hermes_base_url") == "http://localhost:8080/v1",
          "los ajustes guardaron la base con barra final")


def test_un_gateway_local_sin_clave_no_deja_la_clave_de_otro():
    """T42-C1, la otra mitad: un endpoint de casa no tiene clave, y la variable
    de Hermes no puede seguir guardando la del proveedor público anterior."""
    print("· cambiar a un gateway local sin clave VACÍA la variable ajena")
    limpiar()
    mod.configure_brain(CTX, "openai", "modelo-de-prueba", _CLAVE_PRESET)
    check(_CLAVE_PRESET in env_path().read_text(encoding="utf-8"),
          "el preset openai no dejó su clave")
    res = mod.configure_brain(CTX, "custom", "qwen3:8b", "",
                              base_url="http://127.0.0.1:8080/v1")
    check(res.get("ok") is True, f"un gateway local sin clave debe poder configurarse: {res}")
    env = env_path().read_text(encoding="utf-8")
    check(_CLAVE_PRESET not in env,
          f"la clave de OpenAI sigue en el .env apuntando al gateway de casa: {env!r}")
    check("OPENAI_API_KEY=" in env,
          f"la variable no quedó escrita (vacía) para el endpoint local: {env!r}")
    check(any("VACÍA" in c for c in res.get("changes", [])),
          f"el resumen tiene que decir que la dejó vacía: {res.get('changes')}")
    cerebro = mod.cerebro_de_hermes(CTX)
    check(cerebro["clase"] == "local",
          f"un gateway de casa no puede contar como nube ({cerebro['clase']!r})")


# ══════════════════════════════════════════════════════════════════════════════
#  4. UNA BASE QUE NO VALE NO ESCRIBE NADA
# ══════════════════════════════════════════════════════════════════════════════
def test_una_base_invalida_no_escribe_nada():
    print("· file://, userinfo, metadatos, red privada y dominio caído: NO")
    casos = [
        ("file:///C:/Windows/win.ini", "file", "esquema"),
        ("ftp://api.nan.builders/v1", "ftp", "esquema"),
        ("https://usuario:clave@api.openai.com/v1", "userinfo", "usuario"),
        ("http://169.254.169.254/latest/meta-data", "metadatos", "enlace local"),
        ("http://10.0.0.5:8000/v1", "red privada", "red privada"),
        ("http://casa.local:8080/v1", "nombre doméstico", "red local"),
        ("https://no-resuelve.invalid/v1", "sin DNS", "resolver"),
        ("", "vacía", "dirección base"),
        ("https://api.groq.com/open ai/v1", "con espacio", "espacios"),
    ]
    for base, etiqueta, aguja in casos:
        limpiar()
        res = mod.configure_brain(CTX, "custom", "modelo-x", _CLAVE_ABIERTA,
                                  base_url=base)
        check(res.get("ok") is False, f"{etiqueta}: se aceptó una base inválida ({base!r})")
        error = str(res.get("error") or "")
        check(aguja in error,
              f"{etiqueta}: el rechazo no usa el vocabulario de la guarda "
              f"({error!r})")
        check(not env_path().exists(),
              f"{etiqueta}: se escribió el .env de Hermes con una base rechazada")
        check(not cfg_path().exists(),
              f"{etiqueta}: se escribió el config.yaml con una base rechazada")
        check(settings.secret("hermes_custom_api_key") == "",
              f"{etiqueta}: se guardó una clave con una base rechazada")
        check(not settings.get("hermes_base_url"),
              f"{etiqueta}: se apuntó una base rechazada en los ajustes")
        check(not res.get("provider"),
              f"{etiqueta}: la respuesta da por configurado un cerebro que no existe")

    print("· un nombre sin endpoint tampoco (no hay nada que configurar)")
    limpiar()
    res = mod.configure_brain(CTX, "proveedor-inventado", "modelo-x", _CLAVE_ABIERTA)
    check(res.get("ok") is False and "no soportado" in str(res.get("error")),
          f"un proveedor desconocido sin base debe seguir diciendo «no soportado» ({res})")
    check(not env_path().exists() and not cfg_path().exists(),
          "no se escribe nada para un proveedor que no se puede configurar")

    print("· un preset no acepta un endpoint escrito a mano (no se ignora en silencio)")
    limpiar()
    res = mod.configure_brain(CTX, "nan", "deepseek-v4-flash", _CLAVE_NAN,
                              base_url="https://api.groq.com/openai/v1")
    check(res.get("ok") is False, "un preset con otra base tiene que rechazarse")
    check("Otro endpoint compatible OpenAI" in str(res.get("error")),
          f"el rechazo no dice cómo hacerlo bien ({res.get('error')!r})")
    check(not env_path().exists() and not cfg_path().exists(),
          "un preset con base tecleada no puede escribir nada")

    print("· un endpoint abierto sin modelo tampoco (nexus no se lo inventa)")
    limpiar()
    res = mod.configure_brain(CTX, "custom", "", _CLAVE_ABIERTA,
                              base_url="https://api.groq.com/openai/v1")
    check(res.get("ok") is False and "modelo" in str(res.get("error")),
          f"sin modelo debería rechazarse con motivo ({res})")
    check(not env_path().exists() and not cfg_path().exists(),
          "sin modelo no se escribe nada")


def test_una_base_rechazada_conserva_el_cerebro_anterior():
    print("· un rechazo no deja el cerebro a medio cambiar")
    limpiar()
    mod.configure_brain(CTX, "nan", "deepseek-v4-flash", _CLAVE_NAN)
    antes_env = env_path().read_text(encoding="utf-8")
    antes_cfg = cfg_path().read_text(encoding="utf-8")
    res = mod.configure_brain(CTX, "custom", "modelo-x", _CLAVE_ABIERTA,
                              base_url="http://169.254.169.254/v1")
    check(res.get("ok") is False, "el rechazo tiene que ser un error")
    check(env_path().read_text(encoding="utf-8") == antes_env,
          "el .env de Hermes se tocó en una configuración rechazada")
    check(cfg_path().read_text(encoding="utf-8") == antes_cfg,
          "el config.yaml de Hermes se tocó en una configuración rechazada")
    check(settings.get("hermes_provider") == "nan",
          "los ajustes cambiaron de proveedor en una configuración rechazada")


# ══════════════════════════════════════════════════════════════════════════════
#  5. LAS CLAVES NUEVAS SON SECRETOS (GET /api/config no las publica)
# ══════════════════════════════════════════════════════════════════════════════
def test_las_claves_nuevas_son_secretos_de_primera():
    print("· nan_api_key y hermes_custom_api_key están en SECRET_KEYS")
    for clave in ("nan_api_key", "hermes_custom_api_key"):
        check(clave in Settings.SECRET_KEYS,
              f"«{clave}» no está en Settings.SECRET_KEYS: viajaría en claro por "
              "/api/config y set_secret la tiraría en silencio")
    settings.set_secret("nan_api_key", _CLAVE_NAN)
    settings.set_secret("hermes_custom_api_key", _CLAVE_ABIERTA)
    fuera = settings.as_dict()
    check("nan_api_key" not in fuera and "hermes_custom_api_key" not in fuera,
          "as_dict() publica el nombre de la clave nueva como si fuera un ajuste")
    check(fuera.get("has_nan_api_key") is True,
          "as_dict() no marca has_nan_api_key (⚙ no diría que está puesta)")
    check(fuera.get("has_hermes_custom_api_key") is True,
          "as_dict() no marca has_hermes_custom_api_key")
    texto = json.dumps(fuera)
    check(_CLAVE_NAN not in texto and _CLAVE_ABIERTA not in texto,
          "as_dict() filtra el VALOR de una clave nueva")

    print("· y GET /api/config tampoco las devuelve (HTTP de verdad, en proceso)")
    real = httpx.AsyncClient
    httpx.AsyncClient = _REAL_ASYNC_CLIENT
    try:
        import backend.app as servidor

        async def _pide():
            transporte = httpx.ASGITransport(app=servidor.app,
                                             client=("127.0.0.1", 4321))
            async with httpx.AsyncClient(transport=transporte,
                                         base_url="http://127.0.0.1:8177") as cliente:
                return await cliente.get("/api/config", headers={"host": "127.0.0.1:8177"})

        respuesta = run(_pide())
        cuerpo = respuesta.text
        check(respuesta.status_code == 200,
              f"GET /api/config contestó {respuesta.status_code}")
        check(_CLAVE_NAN not in cuerpo and _CLAVE_ABIERTA not in cuerpo,
              "GET /api/config publica una de las claves nuevas")
        datos = respuesta.json()
        check(datos.get("has_nan_api_key") is True,
              "GET /api/config no publica has_nan_api_key")
        check("hermes_base_url" in datos,
              "GET /api/config no publica hermes_base_url (⚙ no podría enseñar el "
              "endpoint guardado)")
    finally:
        httpx.AsyncClient = real


_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ══════════════════════════════════════════════════════════════════════════════
#  6. NEXUS CONTRA UN ENDPOINT CON FORMA DE NaN
# ══════════════════════════════════════════════════════════════════════════════
def _conversacion() -> list[dict]:
    return [{"role": "system", "content": "eres nexus"},
            {"role": "user", "content": "hola"}]


def test_nexus_habla_con_un_endpoint_como_nan():
    print("· llm_provider=cloud contra la base de NaN: ruta, cabecera y cuerpo")
    # CINTURÓN ANTES DE LA PRIMERA LLAMADA: si el transporte no está doblado, esta
    # prueba NO sale a la red (la primera versión de este fichero restauraba
    # `net.client` antes de `main()` y se llevó un 401 real de un endpoint real
    # con una clave sintética: H2 del ODD, declarado en el informe de la tarea).
    check(net.client is not _ORIG_CLIENT,
          "el transporte HTTP no está doblado: esta prueba se niega a salir a la red")
    if net.client is _ORIG_CLIENT:
        return
    llm.invalidate_provider()
    settings.set("llm_provider", "cloud")
    settings.set("cloud_base_url", "https://api.nan.builders/v1")
    settings.set("cloud_model", "deepseek-v4-flash")
    settings.set_secret("cloud_llm_api_key", "sk-TEST-SINTETICA-cloud")
    _CLI.llamadas.clear()

    try:
        prov = run(llm.get_provider())
        check(getattr(prov, "name", "") == "cloud",
              f"con llm_provider=cloud no se eligió el proveedor cloud ({prov!r})")
        texto = run(prov.chat(_conversacion()))
        check("RESPUESTA-NAN" in texto, f"la respuesta se perdió ({texto!r})")
    finally:
        llm.invalidate_provider()

    check(len(_CLI.llamadas) == 1, f"debía ser UNA petición ({len(_CLI.llamadas)})")
    llamada = _CLI.llamadas[0] if _CLI.llamadas else {"url": "", "headers": {}, "json": {}}
    url = str(llamada["url"])
    check(url == "https://api.nan.builders/v1/chat/completions",
          f"la ruta no es la de un endpoint compatible OpenAI ({url!r})")
    check(llamada["headers"].get("Authorization") == "Bearer sk-TEST-SINTETICA-cloud",
          f"la clave no viaja en Authorization: Bearer ({llamada['headers']})")
    cuerpo = llamada["json"] or {}
    check(cuerpo.get("model") == "deepseek-v4-flash",
          f"el cuerpo no lleva el modelo de NaN ({cuerpo.get('model')!r})")
    check(cuerpo.get("max_tokens") == 1234,
          f"el tope de salida (T6) no sale de umbrales.json ({cuerpo.get('max_tokens')!r})")
    check("provider" not in cuerpo,
          f"se le manda el bloque de política de OpenRouter a NaN ({cuerpo})")
    check("data_collection" not in json.dumps(cuerpo),
          "data_collection (política de OpenRouter) no puede ir a un endpoint ajeno")
    check("sk-TEST-SINTETICA" not in url,
          "la clave aparece en la URL: es la lección de ce90957 y no se repite")
    check(set(cuerpo) == {"model", "messages", "max_tokens"},
          f"el cuerpo lleva campos que nadie pidió (no se inventan campos): "
          f"{sorted(cuerpo)}")

    print("· y contra OpenRouter SÍ va la política: la decisión es por la URL")
    settings.set("cloud_base_url", "https://openrouter.ai/api/v1")
    _CLI.llamadas.clear()
    try:
        proveedor = run(llm.get_provider())
        run(proveedor.chat(_conversacion()))
    finally:
        llm.invalidate_provider()
    cuerpo = (_CLI.llamadas[0]["json"] if _CLI.llamadas else {}) or {}
    check((cuerpo.get("provider") or {}).get("data_collection") == "deny",
          f"con OpenRouter se perdió la política de datos ({cuerpo})")
    settings.set("cloud_base_url", "https://api.nan.builders/v1")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    for prueba in (test_los_cuatro_presets_no_cambian,
                   test_el_resumen_del_preset_es_el_de_siempre,
                   test_nan_es_un_preset_documentado,
                   test_cambiar_de_cerebro_sin_teclar_clave_no_deja_la_clave_ajena,
                   test_cualquier_endpoint_compatible_openai,
                   test_la_base_loopback_se_normaliza,
                   test_un_gateway_local_sin_clave_no_deja_la_clave_de_otro,
                   test_una_base_invalida_no_escribe_nada,
                   test_una_base_rechazada_conserva_el_cerebro_anterior,
                   test_las_claves_nuevas_son_secretos_de_primera,
                   test_nexus_habla_con_un_endpoint_como_nan):
        try:
            prueba()
        except Exception as exc:                           # noqa: BLE001
            check(False, f"{prueba.__name__} revienta: {type(exc).__name__}: {exc}")
    print(f"\n{'#' * 54}\ntest_proovedor_abierto: {_pass} OK, {len(_fail)} fallos")
    for f in _fail:
        print("  - " + f)
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        codigo = main()
    finally:
        net.client = _ORIG_CLIENT
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(codigo)
