# -*- coding: utf-8 -*-
"""T8c: `brain` obedece la matriz canal × efecto en UN solo sitio.

T8a dejó la matriz en `comun/canales.py` (`permitir` / `confirmar` / `denegar` por
canal y efecto) y T8b hizo que cada skill declare qué efecto tiene cada intent
(`SKILL["effects"]`) y cuáles ya preguntan por su cuenta (`SKILL["confirma"]`).
Pero nadie la consultaba: el enrutador seguía ejecutando `skill.module.handle(...)`
sin mirar el canal, así que la decisión del dueño (L59) no se cumplía.

Esta suite es la PRUEBA DE ACEPTACIÓN del eslabón que falta: `brain` pregunta a
`canales.politica` en el ÚNICO sitio donde ejecuta un handler y obedece:

    read           permitir    permitir    solo si está en la lista blanca
    write_local    permitir    permitir    denegar
    external_send  permitir    CONFIRMAR   denegar
    destructive    CONFIRMAR   CONFIRMAR   denegar

Lo que se comprueba, caso por caso, contando llamadas al handler y mirando la
confirmación pendiente del canal:

  a) móvil + `external_send` que no pregunta sola → NO se ejecuta, se arma la
     pregunta y, ojo, el «sí» (por `process`, mismo canal) ejecuta UNA vez y el
     «no» no ejecuta nada;
  b) pc + `external_send` → se ejecuta, sin pregunta;
  c) pc + `destructive` sin confirmación propia → pregunta (L59: borrar siempre
     pregunta); pc + `destructive` que ya pregunta sola → una sola vez, sin
     segunda pregunta;
  d) telegram + `read` / `write_local` → se ejecuta directamente;
  e) n8n: el par de la lista blanca declarado `read` pasa; el mismo par declarado
     `write_local` se DENIEGA (la lista es intersección: listado Y de lectura);
     un par no listado se rechaza antes de cualquier efecto;
  f) un intent SIN efecto declarado cuenta como `destructive` y pregunta;
  g) `job` / `sub` con veredicto `confirmar` → no se ejecuta, NO se arma nada (un
     «sí» solo se toma de texto o voz) y se dice la verdad;
  h) los cuatro caminos que acaban en el handler —enrutador, planificador,
     cadena y multi-orden (#multi-orden va por `source="sub"`)— pasan por la
     misma puerta: la llamada a `handle` es UNA en el fuente y va después de la
     autorización (L9: una guarda que solo cubre el enrutador se salta);
  i) y las dos guardas por skill que NO se quitan, porque son más estrictas o de
     otro eje: `datos` no abre sockets desde un canal remoto (la matriz sí lo
     permitiría) y `engram` no fija órdenes permanentes desde el móvil (eso es
     procedencia, no efecto);
  k) T8g (1, R3-multiorden-direct-operator-refused): una frase del OPERADOR con
     varias órdenes sí pregunta. La primera que necesita un «sí» lo arma, la
     segunda no se ejecuta (en el canal solo cabe una pregunta armada) y lo dice,
     y una lectura de la misma frase sigue corriendo; el «sí» ejecuta solo la
     primera;
  l) T8g (2, R3-job-sub-skill-confirma-still-arms): desde un trabajo o un sub sin
     operador, un intent de `SKILL["confirma"]` NO se ejecuta —con cualquier
     veredicto de la matriz (los tres de `_TEXTOS_CONF`)— y no se arma nada en
     ningún canal;
  m) lo que ya funcionaba: una orden directa con un intent de `confirma` se
     ejecuta y pregunta su skill, y una lectura desde un trabajo sigue igual;
  n) T8f: una orden que se ejecuta al decir «sí» recorre la MISMA cola que una
     orden directa —aprendizaje con la orden ORIGINAL, historial/grafo/
     `pg.remember`, `note_reply` y el `data` estructurado del handler— y un «no»,
     una acción que revienta o un handler roto no dejan el rastro de haberse
     hecho. `confirm.answer()` sigue devolviendo solo su cadena (L51/T40).

TODO en proceso y sin efectos reales: la skill es un doble (módulo con `SKILL` y
un `handle` espía), `__db_online` está fuera de línea, no hay red ni LLM, y
config/datos apuntan a carpetas de usar y tirar ANTES de importar el backend
(H2: nada de servidores, puertos ni `.env` del operador).

Ejecutar:  python tests/unit/core/runtime/test_politica_brain.py   (desde nexus)
"""
from __future__ import annotations

import asyncio
import ast
import importlib.util
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

_fail: list[str] = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# Hermetismo ANTES de importar el backend: ni config, ni datos, ni `.env` del
# operador (T44). Carpetas de usar y tirar que se borran al terminar.
_TMP: list[str] = []
for _var in ("NEXUS_CONFIG_DIR", "NEXUS_DATA_DIR"):
    _dir = tempfile.mkdtemp(prefix="nexus_politica_")
    _TMP.append(_dir)
    os.environ[_var] = _dir
os.environ["NEXUS_DOTENV"] = "0"


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


from backend.core.comun import canales, confirm                  # noqa: E402
from backend.core.comun.config import settings                  # noqa: E402
from backend.core.aplicacion import brain, skills_loader        # noqa: E402
from backend.core.dominio import opmem                          # noqa: E402

BRAIN_PY = ROOT / "backend" / "core" / "aplicacion" / "brain.py"
RECHAZO_N8N = "Esa orden no está permitida desde n8n."

# Ajustes en MEMORIA (y en el settings.json de la carpeta de usar y tirar): sin
# planificador, sin web, sin auto-aprendizaje y sin PM. Así cada caso mide solo
# la política y nada más puede intervenir.
for _clave, _valor in (("smart_router", False), ("web_augment", False),
                       ("self_learning", False), ("pm_strong", False),
                       ("hermes_auto", False)):
    settings.set(_clave, _valor)


async def _sin_db() -> bool:
    """La base de datos, fuera de línea: nada de red, nada de Postgres."""
    return False


brain._db_online = _sin_db          # type: ignore[assignment]

_REGISTRO_ORIGINAL = dict(skills_loader._registry)


# ── Skills de mentira: módulo con SKILL + handle espía ───────────────────────
class _Mod:
    """Lo único que `brain` y el cargador necesitan de una skill."""

    def __init__(self, folder: str, effects: dict, confirma, calls: list,
                 arma: bool = False, datos: dict | None = None,
                 revienta: bool = False):
        self.SKILL = {"name": folder,
                      "description": "doble de prueba (T8c)",
                      "effects": dict(effects),
                      "confirma": tuple(confirma)}

        async def handle(intent, text, match, ctx):
            calls.append({"folder": folder, "intent": intent, "text": text,
                          "channel": (ctx or {}).get("channel")})
            if revienta:
                # T8f (d): un handler que revienta antes de devolver nada.
                raise RuntimeError("handler de prueba que revienta")
            if arma:
                # Como las skills REALES de `SKILL["confirma"]` (T8b): el propio
                # handler arma su pregunta y deja su acción para el «sí».
                confirm.request(channel=(ctx or {}).get("channel") or "pc",
                                kind=f"{folder}/{intent}",
                                summary="¿Lo hago? (sí/no)",
                                action=lambda: "hecho tras el sí",
                                request_text=text)
            res = {"reply": f"hecho:{folder}/{intent}"}
            if datos is not None:
                # T8f: el dato ESTRUCTURADO del handler, que antes se perdía.
                res["data"] = datos
            return res

        self.handle = handle


def _skill(folder: str, effects: dict, confirma, patrones: dict, calls: list,
           arma: bool = False, datos: dict | None = None,
           revienta: bool = False):
    mod = _Mod(folder, effects, confirma, calls, arma=arma, datos=datos,
               revienta=revienta)
    return skills_loader.Skill(
        name=folder, folder=folder, description="doble de prueba (T8c)",
        patterns={i: re.compile(rx, re.IGNORECASE) for i, rx in patrones.items()},
        module=mod)


def _montar(*skills) -> None:
    """Deja el registro con SOLO estas skills de mentira y sin nada armado."""
    confirm.clear()
    skills_loader._registry = {s.folder: s for s in skills}


# La skill de casi todos los casos. «raro» NO está en `effects` a propósito:
# un intent sin efecto declarado cuenta como `destructive` (EFECTO_POR_DEFECTO).
_PATRONES = {
    "env": r"^manda el informe de prueba",
    "env2": r"^manda el parte de prueba",
    "borra": r"^borra el recibo de prueba",
    "borra_conf": r"^borra confirmando el recibo de prueba",
    "lee": r"^lee el tablon de prueba",
    "escribe": r"^escribe en el tablon de prueba",
    "raro": r"^ordena el asunto raro de prueba",
}
_EFECTOS = {"env": "external_send", "env2": "external_send",
            "borra": "destructive", "borra_conf": "destructive",
            "lee": "read", "escribe": "write_local"}
_CONFIESA = ("borra_conf",)

_TEXTOS = {"env": "manda el informe de prueba tal cual",
           "env2": "manda el parte de prueba",
           "borra": "borra el recibo de prueba",
           "borra_conf": "borra confirmando el recibo de prueba",
           "lee": "lee el tablon de prueba",
           "escribe": "escribe en el tablon de prueba",
           "raro": "ordena el asunto raro de prueba"}


# Una skill que PREGUNTA SOLA (T8b) de verdad: su `handle` arma `confirm.request`.
# Tres intents con los tres veredictos posibles desde un trabajo: `read` y
# `external_send` los PERMITE la matriz en local, `destructive` la hace CONFIRMAR.
_PATRONES_CONF = {"lee_conf": r"^lee el tablon confirmando",
                  "envia_conf": r"^manda el informe confirmando",
                  "escribe_conf": r"^escribe confirmando en el tablon",
                  "borra_conf": r"^borra confirmando el recibo de prueba"}
_EFECTOS_CONF = {"lee_conf": "read", "envia_conf": "external_send",
                 "escribe_conf": "write_local", "borra_conf": "destructive"}
_TEXTOS_CONF = {"lee_conf": "lee el tablon confirmando",
                "envia_conf": "manda el informe confirmando",
                "escribe_conf": "escribe confirmando en el tablon",
                "borra_conf": "borra confirmando el recibo de prueba"}


def _img(calls: list, datos: dict | None = None, revienta: bool = False):
    return _skill("img", _EFECTOS, _CONFIESA, _PATRONES, calls, datos=datos,
                  revienta=revienta)


def _preguntona(calls: list):
    # Carpeta propia (`img2`) para poder montarla JUNTO a `_img` en la misma
    # multi-orden: el registro va por carpeta y compartirla sustituiría una.
    return _skill("img2", _EFECTOS_CONF, tuple(_PATRONES_CONF), _PATRONES_CONF,
                  calls, arma=True)


# ── T8f: la COLA de una orden ejecutada ─────────────────────────────────────
# `confirm.answer()` devuelve SOLO la cadena de la respuesta (contrato que no se
# toca: L51/T40). Antes, una orden ejecutada al decir «sí» corría por `note_reply`
# y nada más: ni aprendizaje, ni grafo/`pg.remember`, ni historial, ni el `data`
# estructurado del handler. Aquí se espía la cola ENTERA y se exige que la orden
# confirmada deje exactamente el mismo rastro que la directa.
_COLA = {"learn": [], "graph": [], "pg": [], "self": [], "note": [], "chat": []}


def _limpia_cola() -> None:
    for _v in _COLA.values():
        _v.clear()


def _cuenta_cola() -> dict:
    return {k: len(v) for k, v in _COLA.items()}


def _espia_cola() -> dict:
    """Pone los espías de la cola y devuelve lo que hay que restaurar."""
    from backend.core.comun import context as _ctxmod
    from backend.core.dominio import selflearn as _selfmod

    real = {"learn": brain._learn_record,
            "graph": brain.graph.append_daily,
            "pg": brain.pg.remember,
            "self": _selfmod.record_interaction,
            "note": _ctxmod.note_reply,
            "emit": brain.bus.emit}

    def _learn(*a, **_k):
        _COLA["learn"].append(a)

    def _graph(*a, **_k):
        # Sincrona a proposito: `brain` la llama con `asyncio.to_thread`.
        _COLA["graph"].append(a)

    def _pg(*a, **_k):
        _COLA["pg"].append(a)

    def _self(*a, **_k):
        _COLA["self"].append(a)
        return False            # nunca dispara el reentrenamiento de verdad

    def _note(*a, **_k):
        _COLA["note"].append(a)

    async def _emit(tipo, data=None):
        if tipo == "chat":
            _COLA["chat"].append(dict(data or {}))
        await real["emit"](tipo, data)

    brain._learn_record = _learn                  # type: ignore[assignment]
    brain.graph.append_daily = _graph             # type: ignore[assignment]
    brain.pg.remember = _pg                       # type: ignore[assignment]
    _selfmod.record_interaction = _self           # type: ignore[assignment]
    _ctxmod.note_reply = _note                    # type: ignore[assignment]
    brain.bus.emit = _emit                        # type: ignore[assignment]
    return real


def _restaura_cola(real: dict) -> None:
    from backend.core.comun import context as _ctxmod
    from backend.core.dominio import selflearn as _selfmod
    brain._learn_record = real["learn"]           # type: ignore[assignment]
    brain.graph.append_daily = real["graph"]      # type: ignore[assignment]
    brain.pg.remember = real["pg"]                # type: ignore[assignment]
    _selfmod.record_interaction = real["self"]    # type: ignore[assignment]
    _ctxmod.note_reply = real["note"]             # type: ignore[assignment]
    brain.bus.emit = real["emit"]                 # type: ignore[assignment]


def _cargar_skill(nombre: str):
    """Carga una skill REAL por ruta (sin pasar por el registro global)."""
    py = ROOT / "skills" / nombre / "skill.py"
    spec = importlib.util.spec_from_file_location(f"prueba_{nombre}", py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════════
async def main() -> None:
    print("· a) móvil + external_send: pregunta, y el sí/no manda")
    calls: list = []
    _montar(_img(calls))
    r = await brain.process(_TEXTOS["env"], source="text", channel="mobile")
    pend = confirm.pending("mobile")
    check(calls == [], f"a) móvil: el handler NO puede ejecutarse antes del «sí» ({calls!r})")
    check("¿Lo hago? (sí/no)" in (r.get("reply") or ""),
          f"a) móvil: la respuesta debe ser la pregunta de confirmación, fue {r.get('reply')!r}")
    check(_TEXTOS["env"] in (r.get("reply") or ""),
          f"a) móvil: la pregunta tiene que CITAR la orden, fue {r.get('reply')!r}")
    check(bool(pend) and pend.get("kind") == "img/env",
          f"a) móvil: la confirmación debe quedar armada como img/env ({pend!r})")
    check(bool(pend) and pend.get("request_text") == _TEXTOS["env"],
          f"a) móvil: la confirmación debe llevar la orden original ({pend!r})")

    r = await brain.process("sí", source="text", channel="mobile")
    check(len(calls) == 1 and calls[0]["intent"] == "env",
          f"a) móvil + «sí»: el handler debe ejecutarse UNA vez ({calls!r})")
    check(calls and calls[0]["channel"] == "mobile",
          f"a) móvil + «sí»: el handler recibe el mismo ctx/canal ({calls!r})")
    check("hecho:img/env" in (r.get("reply") or ""),
          f"a) móvil + «sí»: la respuesta es la del handler, fue {r.get('reply')!r}")
    check(confirm.pending("mobile") is None,
          "a) móvil + «sí»: no puede quedar nada armado después")

    calls.clear()
    await brain.process(_TEXTOS["env"], source="text", channel="mobile")
    check(len(calls) == 0 and confirm.pending("mobile") is not None,
          "a) móvil: la segunda vez también pregunta")
    r = await brain.process("no", source="text", channel="mobile")
    check(calls == [], f"a) móvil + «no»: el handler NO se ejecuta ({calls!r})")
    check(confirm.pending("mobile") is None,
          "a) móvil + «no»: la confirmación queda desarmada")
    check(bool(r.get("reply")), "a) móvil + «no»: hay que contestar algo al operador")

    print("· b) pc + external_send: se ejecuta, sin preguntas")
    calls.clear()
    _montar(_img(calls))
    r = await brain.process(_TEXTOS["env"], source="text", channel="pc")
    check(len(calls) == 1, f"b) pc: el handler debe ejecutarse una vez ({calls!r})")
    check(confirm.pending("pc") is None, "b) pc: no se arma ninguna confirmación")
    check(r.get("reply") == "hecho:img/env",
          f"b) pc: la respuesta es la del handler, fue {r.get('reply')!r}")

    print("· c) pc + destructive: pregunta salvo que la skill ya pregunte")
    calls.clear()
    _montar(_img(calls))
    await brain.process(_TEXTOS["borra"], source="text", channel="pc")
    pend = confirm.pending("pc")
    check(calls == [], f"c) pc destructivo: no se ejecuta sin el «sí» ({calls!r})")
    check(bool(pend) and pend.get("destructive") is True,
          f"c) pc destructivo: la confirmación se marca destructiva ({pend!r})")
    confirm.clear()

    calls.clear()
    _montar(_img(calls))
    await brain.process(_TEXTOS["borra_conf"], source="text", channel="pc")
    check(len(calls) == 1,
          f"c) pc destructivo que YA pregunta solo: se ejecuta directo ({calls!r})")
    check(confirm.pending("pc") is None,
          "c) pc destructivo que ya pregunta: brain no puede preguntar una segunda vez")

    print("· d) telegram + read / write_local: se ejecuta directamente")
    for intent in ("lee", "escribe"):
        calls.clear()
        _montar(_img(calls))
        await brain.process(_TEXTOS[intent], source="text", channel="telegram")
        check(len(calls) == 1,
              f"d) telegram/{intent}: el handler debe ejecutarse ({calls!r})")
        check(confirm.pending("telegram") is None,
              f"d) telegram/{intent}: nada que confirmar")

    print("· e) n8n: intersección de la lista blanca (listado Y de lectura)")
    calls.clear()
    _montar(_skill("instagram", {"ig_estado": "read"}, (),
                   {"ig_estado": r"estado de instagram"}, calls))
    r = await brain.process("estado de instagram", source="n8n")
    check(len(calls) == 1, f"e) n8n: el par listado y de lectura se ejecuta ({calls!r})")
    check(r.get("skill") == "instagram",
          f"e) n8n: la respuesta es de instagram, fue {r.get('skill')!r}")

    calls.clear()
    _montar(_skill("instagram", {"ig_estado": "write_local"}, (),
                   {"ig_estado": r"estado de instagram"}, calls))
    r = await brain.process("estado de instagram", source="n8n")
    check(calls == [],
          f"e) n8n: un par listado que ESCRIBE no se ejecuta ({calls!r})")
    check(r.get("reply") == RECHAZO_N8N,
          f"e) n8n: rechazo con el texto exacto, salió {r.get('reply')!r}")

    calls.clear()
    _montar(_skill("instagram", {"ig_publica": "read"}, (),
                   {"ig_publica": r"^publica en instagram"}, calls))
    r = await brain.process("publica en instagram", source="n8n")
    check(calls == [], f"e) n8n: un par NO listado no se ejecuta ({calls!r})")
    check(r.get("reply") == RECHAZO_N8N,
          f"e) n8n: rechazo antes de cualquier efecto, salió {r.get('reply')!r}")

    # La MISMA intersección, pero preguntándole a la puerta directamente: si
    # alguien quitara la guarda previa al enrutador, esto sigue denegando.
    async def _ejecutar_falso():
        calls.append({"folder": "instagram", "intent": "ig_publica"})
        return {"reply": "hecho"}

    calls.clear()
    _montar()
    sk_publica = _skill("instagram", {"ig_publica": "read"}, (),
                        {"ig_publica": r"^publica"}, calls)
    res, ejecutado = await brain._autorizar_efecto(
        sk_publica, "ig_publica", "publica", "n8n", "pc", _ejecutar_falso)
    check(ejecutado is False and calls == [],
          f"e) puerta n8n: no ejecuta lo no listado ({ejecutado!r}, {calls!r})")
    check(res.get("reply") == RECHAZO_N8N,
          f"e) puerta n8n: rechazo exacto, salió {res.get('reply')!r}")

    sk_escribe = _skill("instagram", {"ig_estado": "write_local"}, (),
                        {"ig_estado": r"^estado"}, calls)
    res, ejecutado = await brain._autorizar_efecto(
        sk_escribe, "ig_estado", "estado de instagram", "n8n", "pc",
        _ejecutar_falso)
    check(ejecutado is False and calls == [],
          f"e) puerta n8n: listado pero escribiendo, no ejecuta ({ejecutado!r})")
    check(res.get("reply") == RECHAZO_N8N,
          f"e) puerta n8n: rechazo exacto, salió {res.get('reply')!r}")

    print("· f) intent sin efecto declarado = destructive (pregunta)")
    calls.clear()
    _montar(_img(calls))
    r = await brain.process(_TEXTOS["raro"], source="text", channel="pc")
    check(calls == [], f"f) sin declarar: no se ejecuta a ciegas ({calls!r})")
    check(bool(confirm.pending("pc")),
          "f) sin declarar: cuenta como destructivo y pregunta")
    check("«destructive»" in (r.get("reply") or ""),
          f"f) sin declarar: la pregunta dice el efecto, fue {r.get('reply')!r}")
    confirm.clear()

    print("· g) job / sub: veredicto confirmar sin nadie a quien preguntar")
    for fuente in ("job", "sub"):
        calls.clear()
        _montar(_img(calls))
        r = await brain.process(_TEXTOS["borra"], source=fuente, channel="pc")
        texto = r.get("reply") or ""
        check(calls == [], f"g) {fuente}: no se ejecuta ({calls!r})")
        check(confirm.pending("pc") is None,
              f"g) {fuente}: NO se arma nada (el «sí» no se puede tomar de ahí)")
        check("¿Lo hago?" not in texto,
              f"g) {fuente}: no se le hace al operador una pregunta imposible: {texto!r}")
        check("«sí»" in texto and fuente in texto,
              f"g) {fuente}: hay que decir la verdad (necesita un «sí» y desde dónde "
              f"no se puede), dijo {texto!r}")

    print("· h) una sola puerta: la llamada a handle va detrás de la política")
    fuente = BRAIN_PY.read_text(encoding="utf-8")
    # Se lee con `ast`, no a ojo: UNA llamada a `<algo>.module.handle(...)` en todo
    # `brain`, dentro de la corrutina `_ejecutar`, y esa corrutina es el argumento
    # que recibe `_autorizar_efecto`. Cualquier camino nuevo que ejecute un
    # handler sin pasar por ahí pone esta prueba en rojo (L9).
    arbol = ast.parse(fuente)
    handle = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "handle"
              and isinstance(n.func.value, ast.Attribute)
              and n.func.value.attr == "module"]
    check(len(handle) == 1,
          f"h) hay {len(handle)} sitios que ejecutan `skill.module.handle(`: una guarda "
          "que solo cubre un camino se salta por el otro (L9)")
    ejecutar = [n for n in ast.walk(arbol)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "_ejecutar"]
    check(len(ejecutar) == 1, "h) falta (o sobra) la corrutina que ejecuta el handler")
    dentro = bool(handle and ejecutar and
                  ejecutar[0].lineno <= handle[0].lineno <= (ejecutar[0].end_lineno or 0))
    check(dentro, "h) el handler se ejecuta fuera de `_ejecutar`: la política no lo "
                  "autoriza")
    autoriza = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_autorizar_efecto"]
    check(len(autoriza) == 1,
          "h) la autorización por política debe aplicarse en UN solo sitio")
    check(bool(autoriza) and [getattr(a, "id", None) for a in autoriza[0].args][-1:]
          == ["_ejecutar"],
          "h) el handler tiene que ser justo lo que autoriza la política")

    # PLANIFICADOR: el modelo elige skill+intent (nada casa con una regex) y la
    # orden sigue pasando por la misma puerta.
    calls.clear()
    _montar(_img(calls))
    plan_previo = brain.llm.plan_action

    async def _plan_falso(*_a, **_k):
        return {"skill": "img", "intent": "raro", "args": {}}

    settings.set("smart_router", True)
    brain.llm.plan_action = _plan_falso        # type: ignore[assignment]
    try:
        r = await brain.process("esto no casa con ninguna regex de prueba",
                                source="text", channel="pc")
    finally:
        brain.llm.plan_action = plan_previo     # type: ignore[assignment]
        settings.set("smart_router", False)
    check(calls == [], f"h) planificador: no ejecuta lo destructivo a ciegas ({calls!r})")
    check("¿Lo hago? (sí/no)" in (r.get("reply") or ""),
          f"h) planificador: pregunta igual que el enrutador, dijo {r.get('reply')!r}")
    check(bool(confirm.pending("pc")),
          "h) planificador: la confirmación queda armada igual")
    confirm.clear()

    # CADENA y MULTI-ORDEN: los dos trocean la frase y llaman a `process` con
    # `source="sub"`/`"job"`, que es el camino probado en g). Se comprueba que de
    # verdad lo hacen así (si un día pasaran `source="text"`, la pregunta se
    # armaría desde dentro de un trabajo y nadie la contestaría).
    check('source="sub", channel=channel' in fuente
          and 'source="job", channel=ch' in fuente,
          "h) la multi-orden y la cadena tienen que seguir entrando por job/sub")

    print("· k) T8g (1): una multi-orden del OPERADOR sí pregunta (una sola vez)")
    # R3-multiorden-direct-operator-refused: «manda A y manda B y lee C» tecleada
    # por el operador se trocea en `source="sub"`, y antes un «confirmar» dentro
    # de la frase se RECHAZABA aunque el operador estuviera delante. Ahora el
    # sub-orden hereda que su padre era interactivo: la primera que pregunta arma
    # la confirmación como una orden directa, la segunda NO se ejecuta (en el
    # canal solo cabe una pregunta armada) y lo dice, y la de lectura sigue.
    calls.clear()
    _montar(_img(calls))
    frase = (_TEXTOS["env"] + " y " + _TEXTOS["env2"] + " y " + _TEXTOS["lee"])
    r = await brain.process(frase, source="text", channel="mobile")
    texto = r.get("reply") or ""
    pend = confirm.pending("mobile")
    check([c["intent"] for c in calls] == ["lee"],
          f"k) móvil multi-orden: solo corre la de lectura, sin «sí» ({calls!r})")
    check(bool(pend) and pend.get("kind") == "img/env",
          f"k) móvil multi-orden: la primera que pregunta arma img/env ({pend!r})")
    check(texto.count("¿Lo hago? (sí/no)") == 1,
          f"k) móvil multi-orden: UNA sola pregunta en la respuesta, dijo {texto!r}")
    check("«sí»" in texto and "aparte" in texto,
          f"k) móvil multi-orden: la segunda dice que necesita su propio «sí» ({texto!r})")
    check("hecho:img/lee" in texto,
          f"k) móvil multi-orden: la de lectura contesta igual ({texto!r})")
    r = await brain.process("sí", source="text", channel="mobile")
    check([c["intent"] for c in calls] == ["lee", "env"],
          f"k) móvil multi-orden + «sí»: se ejecuta SOLO la que se armó ({calls!r})")
    check("hecho:img/env" in (r.get("reply") or ""),
          f"k) móvil multi-orden + «sí»: contesta el handler, fue {r.get('reply')!r}")
    check(confirm.pending("mobile") is None,
          "k) móvil multi-orden + «sí»: no queda nada armado")

    calls.clear()
    _montar(_img(calls))
    r = await brain.process(_TEXTOS["borra"] + " y " + _TEXTOS["escribe"],
                            source="text", channel="pc")
    texto = r.get("reply") or ""
    pend = confirm.pending("pc")
    check([c["intent"] for c in calls] == ["escribe"],
          f"k) pc multi-orden: lo destructivo no corre, lo local sí ({calls!r})")
    check(bool(pend) and pend.get("kind") == "img/borra",
          f"k) pc multi-orden: lo destructivo arma su pregunta ({pend!r})")
    check("¿Lo hago? (sí/no)" in texto and "hecho:img/escribe" in texto,
          f"k) pc multi-orden: pregunta y contesta lo demás, dijo {texto!r}")
    confirm.clear()

    # La orden que PREGUNTA SOLA (T8b) también respeta el «no sobrescribas»
    # aunque la matriz la PERMITA (`write_local` en el PC): su `confirm.request`
    # sustituiría la pregunta anterior y el «sí» del operador dispararía ESTA
    # segunda, perdiendo la primera en silencio. Se mide el id de lo armado.
    calls.clear()
    _montar(_img(calls), _preguntona(calls))
    _armados: list = []
    _pedir_original = confirm.request

    def _pedir_espia(*a, **k):
        r = _pedir_original(*a, **k)
        _armados.append({"kind": k.get("kind"),
                         "id": (confirm.pending(k.get("channel") or "pc") or {}).get("id")})
        return r

    confirm.request = _pedir_espia       # type: ignore[assignment]
    try:
        r = await brain.process(_TEXTOS["borra"] + " y " + _TEXTOS_CONF["escribe_conf"],
                                source="text", channel="pc")
    finally:
        confirm.request = _pedir_original   # type: ignore[assignment]
    texto = r.get("reply") or ""
    pend = confirm.pending("pc")
    check([c["intent"] for c in calls] == [],
          f"k) pc multi-orden: la que pregunta sola tampoco corre ({calls!r})")
    check(len(_armados) == 1 and bool(pend) and _armados[0]["kind"] == "img/borra",
          f"k) pc multi-orden: se arma UNA sola pregunta, la primera ({_armados!r})")
    check(bool(pend) and pend.get("id") == _armados[0]["id"],
          f"k) pc multi-orden: la pregunta armada NO se sustituye ({pend!r} vs {_armados!r})")
    check("«sí»" in texto and "aparte" in texto and "¿Lo hago?" in texto,
          f"k) pc multi-orden: la segunda dice que necesita su propia orden ({texto!r})")
    confirm.clear()

    print("· l) T8g (2): sin nadie a quien contestar, la skill que pregunta NO corre")
    # R3-job-sub-skill-confirma-still-arms: un intent de `SKILL["confirma"]` que
    # llegara por un trabajo armaba su «sí» en un canal mudo (pc) y el siguiente
    # «sí» del operador disparaba lo que preparó el trabajo. Desde un canal sin
    # operador no se ejecuta NADA, sea cual sea el veredicto de la matriz.
    for fuente in ("job", "sub"):
        for intent, orden in _TEXTOS_CONF.items():
            calls.clear()
            _montar(_preguntona(calls))
            r = await brain.process(orden, source=fuente, channel="pc")
            texto = r.get("reply") or ""
            check(calls == [],
                  f"l) {fuente}/{intent}: el handler NO puede ejecutarse ({calls!r})")
            check(all(confirm.pending(c) is None
                      for c in ("pc", "mobile", "telegram")),
                  f"l) {fuente}/{intent}: no se arma nada en ningún canal")
            check("¿Lo hago?" not in texto,
                  f"l) {fuente}/{intent}: nada de preguntas imposibles: {texto!r}")
            check("«sí»" in texto and fuente in texto,
                  f"l) {fuente}/{intent}: hay que decir la verdad, dijo {texto!r}")

    print("· m) lo que ya funcionaba sigue igual")
    # (1) Una orden DIRECTA con un intent de `confirma` se ejecuta y pregunta su
    #     skill: el operador está delante y la pregunta se arma una sola vez.
    calls.clear()
    _montar(_preguntona(calls))
    r = await brain.process(_TEXTOS_CONF["borra_conf"], source="text", channel="pc")
    pend = confirm.pending("pc")
    check(len(calls) == 1 and calls[0]["intent"] == "borra_conf",
          f"m) pc: la skill que pregunta sola se ejecuta ({calls!r})")
    check(bool(pend) and pend.get("kind") == "img2/borra_conf",
          f"m) pc: la pregunta es la de la skill, sin segunda pregunta ({pend!r})")
    check("¿Lo hago?" not in (r.get("reply") or "")
          or (r.get("reply") or "").count("¿Lo hago?") == 1,
          f"m) pc: brain no pregunta por encima de la skill, dijo {r.get('reply')!r}")
    confirm.clear()
    # (2) Un trabajo de LECTURA sigue corriendo como siempre.
    calls.clear()
    _montar(_img(calls))
    r = await brain.process(_TEXTOS["lee"], source="job", channel="pc")
    check([c["intent"] for c in calls] == ["lee"],
          f"m) job: una lectura sigue ejecutándose ({calls!r})")
    check(confirm.pending("pc") is None, "m) job: una lectura no arma nada")
    check(r.get("reply") == "hecho:img/lee",
          f"m) job: contesta el handler, fue {r.get('reply')!r}")

    print("· i) las dos guardas por skill que NO se quitan")
    # `datos`: `connect` es write_local, así que la matriz PERMITE desde el móvil;
    # la skill es MÁS estricta (no abre sockets desde un canal remoto). Quitarla
    # abriría la red interna desde Telegram: se queda.
    mod_datos = _cargar_skill("datos")
    check(canales.politica("text", "mobile", mod_datos.SKILL["effects"]["connect"],
                           "datos", "connect") == canales.PERMITIR,
          "i) datos/connect: la matriz por sí sola permitiría desde el móvil")
    orden = "conéctate a la base de datos postgresql://127.0.0.1:5433/nexus"
    match = re.compile(mod_datos.SKILL["patterns"]["connect"], re.I).search(orden)

    def _sin_socket(*_a, **_k):
        raise AssertionError("ha intentado abrir una conexión de red")

    mod_datos._connect = _sin_socket            # type: ignore[assignment]
    res = await mod_datos.handle("connect", orden, match, {"channel": "mobile"})
    check("No conecto a una base de datos de red" in (res.get("reply") or ""),
          f"i) datos: la guarda por canal sigue negando desde el móvil ({res!r})")
    res = await mod_datos.handle("connect", orden, match, {"channel": "pc"})
    check("conexión de red" in (res.get("reply") or ""),
          "i) datos: desde el equipo del operador sí se intenta conectar")

    # `engram`: `save` es write_local (la matriz permite desde el móvil), pero
    # fijar una ORDEN PERMANENTE es procedencia, no efecto: eso lo sigue
    # decidiendo `opmem`, que solo acepta el equipo del operador (T9 / SEC-06).
    mod_engram = _cargar_skill("engram")
    check(canales.politica("text", "mobile", mod_engram.SKILL["effects"]["save"],
                           "engram", "save") == canales.PERMITIR,
          "i) engram/save: la matriz por sí sola permitiría desde el móvil")
    check(opmem.puede_fijar_orden(opmem.origen_de("mobile", "text")) is False,
          "i) engram: fijar una orden permanente desde el móvil sigue prohibido")
    check(opmem.puede_fijar_orden(opmem.origen_de("pc", "text")) is True,
          "i) engram: desde el equipo del operador sí se puede fijar")

    print("· j) los dos destructivos que el dueño nombró (L59) preguntan en el equipo")
    # Con las skills DE VERDAD (no dobles): son las dos únicas que declaran
    # `destructive` sin preguntar por su cuenta, así que son las dos únicas que
    # cambian de comportamiento en el PC. Y como no se dice «sí», su handler no
    # llega a ejecutarse: ninguna sale a la red.
    skills_loader._registry = skills_loader.load_skills()
    confirm.clear()
    r = await brain.process("borra el correo 3", source="text", channel="pc")
    pend = confirm.pending("pc")
    check("¿Lo hago? (sí/no)" in (r.get("reply") or ""),
          f"j) delete_email: en el equipo también pregunta, dijo {r.get('reply')!r}")
    check(bool(pend) and pend.get("kind") == "google_workspace/delete_email",
          f"j) delete_email: queda armado como google_workspace/delete_email ({pend!r})")
    confirm.clear()
    r = await brain.process("borra el contacto de mamá", source="text", channel="pc")
    pend = confirm.pending("pc")
    check("¿Lo hago? (sí/no)" in (r.get("reply") or ""),
          f"j) del_contact: en el equipo también pregunta, dijo {r.get('reply')!r}")
    check(bool(pend) and pend.get("kind") == "telefono/del_contact",
          f"j) del_contact: queda armado como telefono/del_contact ({pend!r})")
    confirm.clear()

    print("· n) T8f: el «sí» recorre la MISMA cola que una orden directa")
    real = _espia_cola()
    try:
        # (a) lo que ya pasaba, como pin: una orden directa deja TODO el rastro.
        calls.clear()
        _limpia_cola()
        _montar(_img(calls, datos={"x": 1}))
        r = await brain.process(_TEXTOS["env"], source="text", channel="pc")
        check(len(calls) == 1, f"n) a) directa: el handler corre una vez ({calls!r})")
        check(r.get("data") == {"x": 1},
              f"n) a) directa: la respuesta lleva el `data` del handler ({r.get('data')!r})")
        check(r.get("skill") == "img" and r.get("provider") == "minion:img",
              f"n) a) directa: se etiqueta con la skill ({r.get('skill')!r}/{r.get('provider')!r})")
        check(_COLA["learn"] == [(_TEXTOS["env"], _TEXTOS["env"], "img")],
              f"n) a) directa: se aprende la orden del operador ({_COLA['learn']!r})")
        check(len(_COLA["graph"]) == 1,
              f"n) a) directa: el turno queda en el grafo ({_COLA['graph']!r})")
        check(len(_COLA["note"]) == 1,
              f"n) a) directa: `note_reply` apunta la respuesta ({_COLA['note']!r})")
        check(len(_COLA["pg"]) == 0 and len(_COLA["self"]) == 0,
              f"n) a) directa: DB fuera de línea y auto-aprendizaje apagado ({_cuenta_cola()})")

        # (b) móvil + external_send: la pregunta no deja rastro; el «sí» sí.
        calls.clear()
        _limpia_cola()
        _montar(_img(calls, datos={"x": 1}))
        await brain.process(_TEXTOS["env"], source="text", channel="mobile")
        check(_COLA["learn"] == [] and _COLA["graph"] == [] and _COLA["note"] == []
              and _COLA["self"] == [],
              f"n) b) el turno de la pregunta NO deja rastro de haberse hecho ({_cuenta_cola()})")
        r = await brain.process("sí", source="text", channel="mobile")
        check(len(calls) == 1 and calls[0]["intent"] == "env",
              f"n) b) el «sí» ejecuta el handler UNA vez ({calls!r})")
        check(_COLA["learn"] == [(_TEXTOS["env"], _TEXTOS["env"], "img")],
              "n) b) tras el «sí» se aprende con la ORDEN original (no con «sí»): "
              f"{_COLA['learn']!r}")
        check(len(_COLA["graph"]) == 1,
              f"n) b) el «sí» deja el turno en el grafo ({_COLA['graph']!r})")
        check(len(_COLA["note"]) == 1,
              f"n) b) `note_reply` sigue apuntando la respuesta ({_COLA['note']!r})")
        check(r.get("data") == {"x": 1},
              f"n) b) la respuesta del «sí» lleva el `data` estructurado ({r.get('data')!r})")
        check(r.get("skill") == "img" and r.get("provider") == "minion:img",
              "n) b) la respuesta del «sí» se etiqueta como la skill ejecutada "
              f"({r.get('skill')!r}/{r.get('provider')!r})")
        check(r.get("reply") == "hecho:img/env",
              f"n) b) la respuesta es la del handler ({r.get('reply')!r})")
        _chat = _COLA["chat"][-1] if _COLA["chat"] else {}
        check(_chat.get("user") == _TEXTOS["env"],
              f"n) b) el evento de chat del «sí» habla de la ORDEN ({_chat!r})")
        check(_chat.get("skill") == "img" and _chat.get("provider") == "minion:img",
              f"n) b) y lo etiqueta como la skill de verdad, no «confirmacion» ({_chat!r})")
        check(confirm.pending("mobile") is None,
              "n) b) y no queda nada armado")

        # (c) un «no» no ejecuta ni deja rastro.
        calls.clear()
        _limpia_cola()
        _montar(_img(calls, datos={"x": 1}))
        await brain.process(_TEXTOS["env"], source="text", channel="mobile")
        _limpia_cola()               # se mide SOLO el turno del «no»
        r = await brain.process("no", source="text", channel="mobile")
        check(calls == [], f"n) c) el «no» no ejecuta el handler ({calls!r})")
        check(_cuenta_cola()["learn"] == 0 and _cuenta_cola()["graph"] == 0
              and _cuenta_cola()["self"] == 0 and _cuenta_cola()["note"] == 0,
              f"n) c) el «no» deja la cola en CERO ({_cuenta_cola()})")
        check(r.get("reply") and r.get("data") is None,
              f"n) c) se contesta la cancelación sin datos inventados ({r!r})")

        # (d) una acción armada que revienta: nada de cola, y se dice la verdad.
        calls.clear()
        _limpia_cola()
        _montar(_img(calls, datos={"x": 1}))
        await brain.process(_TEXTOS["env"], source="text", channel="mobile")
        _pend = confirm.pending("mobile")
        check(bool(_pend), "n) d) hay una confirmación armada que se va a romper")

        async def _revienta():
            raise RuntimeError("acción armada de prueba que revienta")

        if _pend:
            _pend["action"] = _revienta
        r = await brain.process("sí", source="text", channel="mobile")
        check(calls == [], f"n) d) si la acción revienta, no se ejecuta nada ({calls!r})")
        check("ha fallado" in (r.get("reply") or ""),
              f"n) d) y se contesta el fallo con la verdad ({r.get('reply')!r})")
        check(_cuenta_cola()["learn"] == 0 and _cuenta_cola()["graph"] == 0
              and _cuenta_cola()["self"] == 0,
              f"n) d) una acción que falla NO deja rastro de haberse hecho ({_cuenta_cola()})")
        check(r.get("data") is None,
              f"n) d) ni datos de algo que no llegó a ejecutarse ({r.get('data')!r})")

        # (d bis) un handler ROTO (no la acción): la cola obedece la misma guarda
        # que una orden directa — no se aprende, pero el turno SÍ queda apuntado.
        conteos: dict = {}
        for canal in ("pc", "mobile"):
            calls.clear()
            _limpia_cola()
            _montar(_img(calls, datos={"x": 1}, revienta=True))
            if canal == "mobile":
                await brain.process(_TEXTOS["env"], source="text", channel=canal)
                _limpia_cola()
            r = await brain.process("sí" if canal == "mobile" else _TEXTOS["env"],
                                    source="text", channel=canal)
            conteos[canal] = _cuenta_cola()
            check("ha fallado" in (r.get("reply") or ""),
                  f"n) d bis) {canal}: un handler roto se confiesa ({r.get('reply')!r})")
        check(conteos["pc"] == conteos["mobile"],
              f"n) d bis) un handler roto deja la MISMA cola directa y confirmada ({conteos})")
        check(conteos["pc"]["learn"] == 0 and conteos["pc"]["graph"] == 1,
              "n) d bis) y esa cola es «no se aprende, pero el turno se guarda»: "
              f"{conteos['pc']}")

        # (e) las GUARDAS de la cola son las mismas. Se encienden las dos que la
        # dejan en cero (DB en línea y auto-aprendizaje) y se mide el MISMO texto
        # por el PC (directo) y por el móvil (confirmado): contador a contador.
        async def _con_db() -> bool:
            return True

        _db_previo = brain._db_online
        brain._db_online = _con_db          # type: ignore[assignment]
        settings.set("self_learning", True)
        try:
            calls.clear()
            _limpia_cola()
            _montar(_img(calls, datos={"x": 1}))
            await brain.process(_TEXTOS["env"], source="text", channel="pc")
            directo = _cuenta_cola()
            calls.clear()
            _limpia_cola()
            await brain.process(_TEXTOS["env"], source="text", channel="mobile")
            _limpia_cola()
            await brain.process("sí", source="text", channel="mobile")
            confirmado = _cuenta_cola()
        finally:
            brain._db_online = _db_previo   # type: ignore[assignment]
            settings.set("self_learning", False)
        check(directo == confirmado,
              f"n) e) la cola confirmada obedece las MISMAS guardas ({directo} vs {confirmado})")
        check(directo["pg"] == 1 and directo["self"] == 1,
              f"n) e) con DB y auto-aprendizaje en línea los dos caminos registran ({directo})")
    finally:
        _restaura_cola(real)
        settings.set("self_learning", False)
        confirm.clear()


def _limpiar() -> None:
    confirm.clear()
    skills_loader._registry = _REGISTRO_ORIGINAL
    for d in _TMP:
        shutil.rmtree(d, ignore_errors=True)


try:
    asyncio.run(main())
finally:
    _limpiar()

print(f"\n{'#' * 54}\ntest_politica_brain: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
