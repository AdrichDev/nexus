# -*- coding: utf-8 -*-
"""Tests v21 — 3 arreglos reales pedidos por Adri, contra el CÓDIGO REAL del disco:

  1) backend/core/profile.py: «quién soy» ya no es una ficha de estadísticas
     (cubierto en tests/test_specs_v20.py::test_profile_build /
     test_perfil_natural_helper — se dejó ahí porque profile.py es v20).
  2) skills/n8n_flows/skill.py: WhatsApp con webhook de n8n CONFIGURADO PERO
     CAÍDO (404, timeout...) ya NO devuelve un error técnico plano — cae al
     móvil vinculado (estilo Android Auto), igual que cuando no hay n8n.
  3) backend/core/llm.py (plan_action / interpret_command) + brain._recent_context:
     el enrutador de respaldo por LLM ahora recibe las últimas vueltas de la
     conversación, para no interpretar frases cortas y ambiguas («¿está todo
     arrancado?») a ciegas por coincidencia de palabras sueltas con el catálogo
     de skills (el bug real: delegaba en Hermes solo porque su descripción
     menciona "arrancado", sin relación con el WhatsApp que se venía hablando).

Ejecutar:  python tests/test_v21_fixes.py    (desde la carpeta nexus)
"""
import asyncio
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def _stub(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: types.SimpleNamespace()
    sys.modules[name] = m
    return m


def load_skill_module(folder):
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    for _ in range(15):
        spec = importlib.util.spec_from_file_location(f"_v21_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod
        except ModuleNotFoundError as e:
            _stub(e.name)
    raise RuntimeError(folder)


class _FakeMatch:
    """Sustituye a re.Match: solo necesitamos .groupdict()."""
    def __init__(self, gd):
        self._gd = gd

    def groupdict(self):
        return dict(self._gd)


class _FakeGraph:
    def __init__(self):
        self.lines = []

    def append_daily(self, line, section=""):
        self.lines.append((line, section))


# ══════════════ 2) WhatsApp: n8n configurado pero CAÍDO -> cae al móvil ══════════════

def test_whatsapp_n8n_falla_cae_a_movil():
    import backend.core.infraestructura.remote as remote
    n8n = load_skill_module("n8n_flows")

    old_post, old_devices = n8n._post, remote.devices

    async def fake_post_fail(url, payload):
        return False, "HTTP 404"

    async def fake_post_ok(url, payload):
        return True, "HTTP 200"

    async def run():
        gd = {"to": "mami", "body": "voy de camino", "to2": None, "body2": None,
              "to3": None, "body3": None}
        ctx = {"settings": {"n8n_webhook_url": "http://viejo.local/webhook/nexus"},
               "graph": _FakeGraph()}

        # a) n8n configurado pero el POST falla (404 real de Adri) + MÓVIL vinculado
        #    -> NO debe devolver el error técnico de n8n; debe abrir WhatsApp en el móvil.
        n8n._post = fake_post_fail
        remote.devices = lambda: [{"id": "movil-1"}]
        r = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                             _FakeMatch(gd), ctx)
        check("📲" in r["reply"], "whatsapp: n8n caído + móvil vinculado -> respuesta por móvil")
        check("webhook" not in r["reply"].lower() and "404" not in r["reply"],
              "whatsapp: n8n caído + móvil -> NO expone el error técnico de n8n al usuario")

        # b) n8n configurado, POST falla, y NO hay móvil vinculado -> ahora sí el
        #    aviso de que no se pudo (pero ya sin culpar solo a n8n a secas: pide algo accionable)
        remote.devices = lambda: []
        r2 = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                              _FakeMatch(gd), ctx)
        check("404" in r2["reply"] or "HTTP 404" in r2["reply"],
              "whatsapp: n8n caído + sin móvil -> explica el fallo real")
        check("móvil" in r2["reply"].lower(), "whatsapp: n8n caído + sin móvil -> sugiere vincular el móvil")

        # c) n8n configurado y el POST SÍ funciona -> sigue saliendo por n8n (sin regresión)
        n8n._post = fake_post_ok
        remote.devices = lambda: [{"id": "movil-1"}]
        r3 = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                              _FakeMatch(gd), ctx)
        check("n8n" in r3["reply"] and "📲" not in r3["reply"],
              "whatsapp: n8n funcionando -> sigue saliendo por n8n, no se desvía al móvil")

        # d) SIN n8n configurado y CON móvil -> sigue funcionando como antes (regresión)
        ctx_sin_n8n = {"settings": {"n8n_webhook_url": ""}, "graph": _FakeGraph()}
        r4 = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                              _FakeMatch(gd), ctx_sin_n8n)
        check("📲" in r4["reply"], "whatsapp: sin n8n + móvil vinculado -> por móvil (sin regresión)")

        # e) SIN n8n y SIN móvil -> mensaje claro de qué falta
        remote.devices = lambda: []
        r5 = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                              _FakeMatch(gd), ctx_sin_n8n)
        check("n8n" in r5["reply"].lower() and "móvil" in r5["reply"].lower(),
              "whatsapp: sin n8n y sin móvil -> explica las dos vías posibles")

    try:
        asyncio.run(run())
    finally:
        n8n._post = old_post
        remote.devices = old_devices


def test_whatsapp_movil_revienta_no_expone_error_tecnico():
    # (hallazgo QA sonnet) si _whatsapp_via_movil() revienta por lo que sea
    # (agenda corrupta, bus caído...), el usuario NO debe recibir el mensaje
    # crudo "El minion 'n8n / WhatsApp' ha fallado: ..." — precisamente el
    # tipo de error técnico que esta corrección quería eliminar. Debe
    # degradar con gracia al mensaje normal de "no puedo mandarlo ahora".
    n8n = load_skill_module("n8n_flows")
    old_post, old_via_movil = n8n._post, n8n._whatsapp_via_movil

    async def fake_post_fail(url, payload):
        return False, "HTTP 404"

    async def fake_via_movil_boom(to, body, ctx):
        raise RuntimeError("agenda corrupta")

    async def run():
        n8n._post = fake_post_fail
        n8n._whatsapp_via_movil = fake_via_movil_boom
        gd = {"to": "mami", "body": "voy de camino", "to2": None, "body2": None,
              "to3": None, "body3": None}

        # con n8n configurado (falla) + móvil que revienta -> no debe propagar
        ctx = {"settings": {"n8n_webhook_url": "http://viejo.local/webhook"},
               "graph": _FakeGraph()}
        r = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                             _FakeMatch(gd), ctx)
        check(isinstance(r, dict) and "reply" in r,
              "whatsapp: móvil que revienta -> handle() no propaga la excepción, devuelve dict")
        check("RuntimeError" not in r["reply"] and "agenda corrupta" not in r["reply"],
              "whatsapp: móvil que revienta -> el error interno no se expone al usuario")

        # sin n8n configurado + móvil que revienta -> tampoco debe propagar
        ctx2 = {"settings": {"n8n_webhook_url": ""}, "graph": _FakeGraph()}
        r2 = await n8n.handle("whatsapp", "envía un whatsapp a mami diciendo voy de camino",
                              _FakeMatch(gd), ctx2)
        check(isinstance(r2, dict) and "reply" in r2,
              "whatsapp: sin n8n + móvil que revienta -> tampoco propaga")

    try:
        asyncio.run(run())
    finally:
        n8n._post = old_post
        n8n._whatsapp_via_movil = old_via_movil


def test_flow_sigue_exigiendo_n8n():
    # «lanza el flujo X» no tiene equivalente por móvil: sigue exigiendo n8n
    # configurado y sigue reportando el fallo tal cual (sin regresión).
    n8n = load_skill_module("n8n_flows")
    old_post = n8n._post

    async def fake_post_fail(url, payload):
        return False, "HTTP 500"

    async def run():
        n8n._post = fake_post_fail
        ctx = {"settings": {"n8n_webhook_url": ""}, "graph": _FakeGraph()}
        r = await n8n.handle("flow", "lanza el flujo backup", _FakeMatch({"flow": "backup", "flow2": None}), ctx)
        check("n8n" in r["reply"].lower(), "flow: sin n8n -> pide configurarlo")

        ctx2 = {"settings": {"n8n_webhook_url": "http://x/webhook"}, "graph": _FakeGraph()}
        r2 = await n8n.handle("flow", "lanza el flujo backup", _FakeMatch({"flow": "backup", "flow2": None}), ctx2)
        check("no responde" in r2["reply"].lower(), "flow: n8n caído -> sigue reportando el fallo (sin móvil, no aplica)")

    try:
        asyncio.run(run())
    finally:
        n8n._post = old_post


# ══════════ 3) contexto reciente para el enrutador LLM de respaldo ══════════

def test_recent_context_helper():
    import backend.core.brain as brain
    old_hist = list(brain._history)
    try:
        brain._history.clear()
        check(brain._recent_context() == "", "_recent_context: sin historial -> vacío")

        brain._history.extend([
            {"role": "user", "content": "envía un whatsapp a mami diciendo voy tarde"},
            {"role": "assistant", "content": "No llego al webhook de n8n (HTTP 404). "
                                             "Comprueba que n8n esté arrancado..."},
        ])
        ctx = brain._recent_context()
        check("whatsapp" in ctx.lower(), "_recent_context: conserva el turno del usuario")
        check("n8n" in ctx.lower(), "_recent_context: conserva el turno de nexus")
        check(len(ctx.splitlines()) == 2, "_recent_context: 1 par -> 2 líneas")

        # frases largas se recortan (no explota el prompt)
        brain._history.append({"role": "user", "content": "x" * 500})
        brain._history.append({"role": "assistant", "content": "y" * 500})
        ctx2 = brain._recent_context()
        check(all(len(l) < 200 for l in ctx2.splitlines()),
              "_recent_context: recorta frases largas por línea")
    finally:
        brain._history.clear()
        brain._history.extend(old_hist)


def test_plan_action_recibe_contexto():
    import backend.core.infraestructura.llm as llm

    captured = {}

    class _FakeProvider:
        name = "fake-test"

        async def chat(self, messages):
            captured["messages"] = messages
            return '{"skill":null}'

    old_get_provider = llm.get_provider

    async def fake_get_provider():
        return _FakeProvider()

    async def run():
        llm.get_provider = fake_get_provider
        plan = await llm.plan_action(
            "está todo arrancado", "[hermes] delega en Hermes...",
            recent_context="Adri: envía un whatsapp a mami\nnexus: no llego al webhook de n8n")
        check(plan is None, "plan_action: 'skill:null' -> None")
        sys_msg = captured["messages"][0]["content"]
        check("CONTEXTO RECIENTE" in sys_msg, "plan_action: el prompt incluye el contexto reciente")
        check("webhook de n8n" in sys_msg, "plan_action: el contexto reciente real llega al prompt")

        # sin contexto (primera frase de la sesión) no se añade el BLOQUE con las
        # frases reales (las instrucciones base SÍ pueden mencionar "CONTEXTO
        # RECIENTE" en genérico; lo que no debe pasar es que aparezca el bloque
        # con contenido real de una conversación anterior)
        captured.clear()
        await llm.plan_action("está todo arrancado", "[hermes] ...", recent_context="")
        sys_msg2 = captured["messages"][0]["content"]
        check("webhook de n8n" not in sys_msg2 and "ultimas frases de esta conversacion" not in sys_msg2,
              "plan_action: sin contexto no añade el bloque con frases reales (no ensucia el prompt)")

    try:
        asyncio.run(run())
    finally:
        llm.get_provider = old_get_provider


def test_interpret_command_recibe_contexto():
    import backend.core.infraestructura.llm as llm

    captured = {}

    class _FakeProvider:
        name = "fake-test"

        async def chat(self, messages):
            captured["messages"] = messages
            return "CHARLA"

    old_get_provider = llm.get_provider

    async def fake_get_provider():
        return _FakeProvider()

    async def run():
        llm.get_provider = fake_get_provider
        guess = await llm.interpret_command(
            "está todo arrancado", "[hermes] delega en Hermes...",
            recent_context="Adri: envía un whatsapp a mami\nnexus: no llego al webhook de n8n")
        check(guess == "", "interpret_command: 'CHARLA' -> '' (no ejecuta nada)")
        sys_msg = captured["messages"][0]["content"]
        check("CONTEXTO RECIENTE" in sys_msg, "interpret_command: el prompt incluye el contexto")
        check("webhook de n8n" in sys_msg, "interpret_command: el contexto real llega al prompt")

    try:
        asyncio.run(run())
    finally:
        llm.get_provider = old_get_provider


def test_brain_pasa_recent_context_a_llm():
    # Verificación de INTEGRACIÓN (no solo de las funciones sueltas): brain.py
    # de verdad llama a plan_action/interpret_command CON recent_context=... —
    # si alguien quita el argumento en una refactorización futura, esto lo pilla.
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    check("plan_action(text, _skills_plan_catalog(), _learn_examples(),\n"
         "                                        recent_context=_recent_context())" in src
         or "recent_context=_recent_context()" in src,
         "brain: plan_action se llama con recent_context=_recent_context()")
    check(src.count("recent_context=_recent_context()") >= 2,
         "brain: TANTO plan_action COMO interpret_command reciben el contexto reciente")


if __name__ == "__main__":
    tests = [test_whatsapp_n8n_falla_cae_a_movil,
             test_whatsapp_movil_revienta_no_expone_error_tecnico,
             test_flow_sigue_exigiendo_n8n,
             test_recent_context_helper, test_plan_action_recibe_contexto,
             test_interpret_command_recibe_contexto, test_brain_pasa_recent_context_a_llm]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
