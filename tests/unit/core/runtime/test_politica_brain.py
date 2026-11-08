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
     procedencia, no efecto).

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

    def __init__(self, folder: str, effects: dict, confirma, calls: list):
        self.SKILL = {"name": folder,
                      "description": "doble de prueba (T8c)",
                      "effects": dict(effects),
                      "confirma": tuple(confirma)}

        async def handle(intent, text, match, ctx):
            calls.append({"folder": folder, "intent": intent, "text": text,
                          "channel": (ctx or {}).get("channel")})
            return {"reply": f"hecho:{folder}/{intent}"}

        self.handle = handle


def _skill(folder: str, effects: dict, confirma, patrones: dict, calls: list):
    mod = _Mod(folder, effects, confirma, calls)
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
    "borra": r"^borra el recibo de prueba",
    "borra_conf": r"^borra confirmando el recibo de prueba",
    "lee": r"^lee el tablon de prueba",
    "escribe": r"^escribe en el tablon de prueba",
    "raro": r"^ordena el asunto raro de prueba",
}
_EFECTOS = {"env": "external_send", "borra": "destructive",
            "borra_conf": "destructive", "lee": "read", "escribe": "write_local"}
_CONFIESA = ("borra_conf",)

_TEXTOS = {"env": "manda el informe de prueba tal cual",
           "borra": "borra el recibo de prueba",
           "borra_conf": "borra confirmando el recibo de prueba",
           "lee": "lee el tablon de prueba",
           "escribe": "escribe en el tablon de prueba",
           "raro": "ordena el asunto raro de prueba"}


def _img(calls: list):
    return _skill("img", _EFECTOS, _CONFIESA, _PATRONES, calls)


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
