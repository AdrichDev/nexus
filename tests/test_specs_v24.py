# -*- coding: utf-8 -*-
"""Tests de las specs v24 — FASE 1 a 4 (delegación invisible).

  T1  ni una mención al subagente en las respuestas al usuario
  T2  ni al gateway, puertos, procesos o servicios internos
  T5  acuses variados y contextuales, no la misma frase clavada
  T6  un fallo = UN mensaje final, sin bucles ni un aviso por reintento
  T7  rate limit ≠ saldo ≠ autenticación ≠ modelo ≠ infraestructura
  T17 comprobación automática de términos prohibidos en la voz pública

Ejecutar:  python tests/test_specs_v24.py    (desde la carpeta nexus)
"""
import asyncio
import os
import re
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend.core.comun.publicvoice as pv      # noqa: E402


# ══════════════ T1/T2: nada interno sale al chat ══════════════

def test_frases_prohibidas_de_las_specs():
    casos = [
        "Voy a enviar esta tarea a Hermes.",
        "Hermes se encargará de realizar la consulta.",
        "He delegado la tarea en Hermes.",
        "Esperaré a que Hermes termine.",
        "Hermes no está disponible.",
        "El agente secundario está procesando la solicitud.",
        "El gateway de Hermes está apagado.",
        "No puedo contactar con el gateway.",
        "Debes iniciar el gateway para continuar.",
        "El servicio interno no está levantado.",
        "El puerto 8642 del gateway no responde.",
    ]
    for t in casos:
        limpio = pv.sanitize(t)
        check(not pv.tiene_fugas(limpio),
              f"queda limpio: «{t[:45]}…» → «{limpio[:60]}»")


def test_el_caso_real_de_la_captura():
    ack = ("🪽 Encargo #8 para Hermes, en paralelo: «averigua quiénes son los combates». "
           "Si su gateway está apagado lo levanto yo antes de encargárselo. Sigo contigo "
           "mientras trabaja; al terminar te canto el resultado del #8.")
    fallo = ("✖ Trabajo #2 (Hermes #8: averigua quiénes son los combates) ha FALLADO: "
             "RuntimeError: RuntimeError: API call failed after 3 retries: You've exceeded "
             "the rate limit, please slow down and try again after 46.475435 seconds.. "
             "Mira data/hermes_gateway.log o dime «diagnostica hermes».. No doy nada por hecho.")
    for t in (ack, fallo):
        limpio = pv.sanitize(t)
        check(not pv.tiene_fugas(limpio), f"sin fugas: «{limpio[:70]}…»")
    check("diagnostica el sistema" in pv.sanitize(fallo),
          "y la acción sugerida deja de nombrar al subagente")


def test_el_bus_es_la_ultima_barrera():
    src = Path(ROOT, "backend", "core", "comun", "events.py").read_text(encoding="utf-8")
    check("from .publicvoice import limpia_trabajo, sanitize" in src,
          "el bus de eventos sanea antes de mandar nada al HUD, texto y ejecutor")
    check('"chat", "job_done", "jobs"' in src,
          "se aplica a las respuestas, a los avisos de fin y a la LISTA de "
          "trabajos, que es la que pinta la tarjeta de Multitarea")
    check('not data.get("admin")' in src,
          "el panel de administración sí puede ver el detalle")
    check('if type_ == "log":' in src and "sanitize" in src.split('if type_ == "log":')[0],
          "los LOGS conservan el detalle técnico íntegro")

    async def _t():
        from backend.core.comun.events import bus
        vistos = []

        class _WS:
            async def send_text(self, txt):
                vistos.append(txt)
        ws = _WS()
        bus.register(ws)
        try:
            await bus.emit("chat", {"user": "x", "reply": "El gateway de Hermes está apagado."})
        finally:
            bus.unregister(ws)
        check(vistos and not pv.tiene_fugas(vistos[-1]),
              f"lo que sale por el WebSocket va limpio: {vistos[-1][:80] if vistos else 'nada'}")
    asyncio.get_event_loop().run_until_complete(_t())


def test_la_skill_ya_nace_limpia():
    src = Path(ROOT, "skills", "hermes", "skill.py").read_text(encoding="utf-8")
    # La VOZ PÚBLICA (acuse, resultado, listado) no puede filtrar nada; el
    # DIAGNÓSTICO que el operador pide a propósito sí puede (specs v24 T18).
    publico = src[src.find("async def _handle_publico"):]
    replies = re.findall(r'return \{"reply": (?:f?")([^"]{25,})"', publico)
    for r in replies:
        fugas = [p for p in ("hermes", "gateway", "worker") if p in r.lower()]
        check(not fugas, f"voz pública sin fontanería: «{r[:60]}…» {fugas}")
    check('_ADMIN = ("hermes_estado", "hermes_arranca", "hermes_info")' in src,
          "los intents de diagnóstico están declarados como modo administrador")
    check('r["admin"] = True' in src, "y se marcan para que el bus no los sanee")
    brain = Path(ROOT, "backend", "core", "aplicacion", "brain.py").read_text(encoding="utf-8")
    check('"admin": _admin' in brain, "el brain propaga ese permiso al emitir la respuesta")
    check("pv.frase_inicio(orden" in src, "el acuse usa las frases variadas")
    check("pv.mensaje_fallo(" in src, "el fallo usa el mensaje funcional")
    check('f"#{num}: {orden[:44]}"' in src,
          "el nombre del trabajo en Multitarea tampoco delata al subagente")


def test_el_ejecutor_no_se_ve_en_la_tarjeta_de_multitarea():
    """El texto salía limpio, pero el HUD pintaba «hermes» igual (02/08/2026).

    `frontend/js/command.js` escribe el agente de cada trabajo en su tarjeta de
    Multitarea (`jobc-m`). El saneador del bus solo miraba los campos de TEXTO
    —reply, result, error, title—, así que un encargo delegado llegaba con
    `agent: "hermes"` y ahí se leía tal cual. Para el operador el ejecutor es
    siempre nexus.
    """
    import backend.core.comun.publicvoice as pv

    for interno in ("hermes", "HERMES", "gateway", "worker", "subagente"):
        salida = pv.limpia_trabajo({"agent": interno, "num": 7})
        check(salida["agent"] == "nexus",
              f"un trabajo con agent=«{interno}» sigue enseñando el ejecutor")
    check(pv.limpia_trabajo({"agent": "nexus"})["agent"] == "nexus",
          "un trabajo propio no debería cambiar")
    check("agent" not in pv.limpia_trabajo({"num": 1}),
          "un trabajo sin agente no debería estrenar uno")
    # No muta el original: el registro y la auditoría necesitan saber quién fue.
    original = {"agent": "hermes", "num": 9}
    pv.limpia_trabajo(original)
    check(original["agent"] == "hermes",
          "limpia_trabajo ha mutado el original, y la auditoría pierde el ejecutor real")

    # `provider` y `skill` delatan igual: van en cada mensaje de chat.
    for campo in ("provider", "skill"):
        salida = pv.limpia_trabajo({campo: "hermes"})
        check(salida[campo] == "nexus", f"el campo «{campo}» sigue nombrando al ejecutor")

    # Y los textos del propio trabajo, que viajan DENTRO de la lista y por eso
    # se escapaban del saneo de los campos de arriba.
    salida = pv.limpia_trabajo({"title": "encargo a Hermes: investiga",
                                "request": "mándale a hermes que investigue",
                                "progress_note": "hermes está trabajando"})
    for campo, valor in salida.items():
        check("hermes" not in str(valor).lower(),
              f"el campo «{campo}» del trabajo llega con el ejecutor a la vista: {valor!r}")

    # El HUD sigue pintando el agente: si algún día deja de hacerlo, este test
    # sobra, pero mientras lo pinte hace falta.
    from _frontend_js import js_hud
    check("j.agent" in js_hud(),
          "el HUD ya no pinta el agente del trabajo: revisa si este enmascarado "
          "sigue haciendo falta")


def test_sanear_no_puede_dejar_la_respuesta_vacia():
    """Un mensaje que era fontanería de arriba abajo se quedaba en NADA.

    `_FRASE_FUERA` se lleva la oración entera cuando habla de infraestructura.
    Con «se lo he delegado a Hermes, el gateway responde en http://127.0.0.1:8642»
    no quedaba ni un carácter, y el operador ve una respuesta vacía: parece que
    nexus se ha colgado, que es peor que la fuga.

    Y el suelo NO puede reclamar progreso: el mensaje original podía ser un fallo.
    """
    import backend.core.comun.publicvoice as pv

    for crudo in ("Se lo he delegado a Hermes, el gateway responde en http://127.0.0.1:8642",
                  "El worker falló con HTTP 500 en el endpoint /v1/chat.",
                  "Traceback (most recent call last): boom"):
        s = pv.sanitize(crudo)
        check(s.strip() != "", f"«{crudo[:40]}…» deja la respuesta VACÍA")
        check(pv.tiene_fugas(s) == [], f"«{crudo[:40]}…» deja fugas: {pv.tiene_fugas(s)}")
    suelo = pv.sanitize("Traceback (most recent call last): boom")
    for reclamo in ("estoy en ello", "ya está", "hecho", "terminado", "listo"):
        check(reclamo not in suelo.lower(),
              f"el mensaje de respaldo reclama «{reclamo}», y el original podía ser un fallo")

    # Una dirección no puede partir la frase por sus puntos.
    s = pv.sanitize("El servicio responde en http://127.0.0.1:8642 y todo bien.")
    check("0.0.1" not in s, f"la IP se ha partido y ha dejado un trozo suelto: {s!r}")
    check("todo bien" in s, f"se ha llevado por delante texto que sí valía: {s!r}")

    # Y lo normal sigue pasando intacto.
    for sano in ("una respuesta normal y corriente",
                 "Ya lo tengo #3 — «investiga el mercado»: el sector crece un 12%."):
        check(pv.sanitize(sano) == sano, f"«{sano[:40]}…» se ha tocado sin motivo")


def test_el_encargo_guardado_en_memoria_no_nombra_al_ejecutor():
    """Lo que se guarda en memoria se recupera con «qué recuerdas de X» y se le
    enseña al operador tal cual. El prefijo era «[Encargo a Hermes]»."""
    src = Path(ROOT, "skills", "hermes", "skill.py").read_text(encoding="utf-8")
    check("[Encargo a Hermes]" not in src,
          "la skill sigue guardando en memoria con el prefijo «[Encargo a Hermes]», "
          "que el operador acaba viendo al preguntar qué recuerdas")
    check('pg.remember, f"[Trabajo]' in src,
          "el encargo debería guardarse con un prefijo neutro")
    check('kind="hermes"' in src or '"hermes")' in src,
          "y seguir marcado por dentro con kind=hermes, que no se pinta nunca")


# ══════════════ T5: acuses variados ══════════════

def test_acuses_variados_y_contextuales():
    pv.reset_frases()
    ordenes = ["investiga los proveedores de algodón", "crea el documento del contrato",
               "analiza estos datos de ventas", "revisa el informe trimestral",
               "busca vuelos a Roma", "prepara el acta de la reunión",
               "compara precios de tres tiendas", "comprueba el estado del pedido",
               "averigua quién juega hoy", "haz el resumen del mes"]
    frases = [pv.frase_inicio(o) for o in ordenes]
    check(len(set(frases)) >= 5,
          f"diez tareas seguidas NO reciben la misma frase ({len(set(frases))} distintas)")
    for i in range(1, len(frases)):
        check(frases[i] != frases[i - 1], "no repite la frase del mensaje anterior")
    check(pv.tipo_tarea("crea el documento del contrato") == "archivo",
          "reconoce que es una tarea de documento")
    check(pv.tipo_tarea("analiza estos datos") == "analisis", "…y de análisis")
    check(pv.tipo_tarea("investiga los precios") == "consulta", "…y de consulta")
    doc = pv.frase_inicio("crea el documento del contrato")
    check("document" in doc.lower() or "prepar" in doc.lower() or "archivo" in doc.lower(),
          f"la frase pega con el tipo de tarea: «{doc}»")
    for f in frases:
        check(not pv.tiene_fugas(f), "ningún acuse menciona componentes internos")
        check(not re.search(r"\benseguida\b|\ben un momento\b|\b\d+\s*(?:min|segundos)\b", f, re.I),
              f"no promete plazos inventados: «{f}»")
    cola = pv.frase_inicio("otra cosa más", activas=2)
    check("otra cosa" in cola.lower() or "lista" in cola.lower() or "marcha" in cola.lower(),
          f"con varias tareas activas lo dice: «{cola}»")


# ══════════════ T7: cada error, en su sitio ══════════════

def test_clasificacion_de_errores():
    casos = [
        (429, "You've exceeded the rate limit, please slow down", "rate_limit", True),
        (401, "invalid_api_key: Incorrect API key provided", "auth", False),
        (403, "Your organization must be verified", "auth", False),
        (402, "payment required", "saldo", False),
        (404, "model_not_found: gpt-5.9 does not exist", "modelo", False),
        (500, "internal server error", "proveedor", True),
        (503, "service unavailable", "proveedor", True),
        (0, "insufficient_quota: you exceeded your current quota", "saldo", False),
        (0, "connection refused a 127.0.0.1:8642", "infra", True),
    ]
    for status, detalle, cat, reint in casos:
        r = pv.clasificar_error(detalle, status)
        check(r["categoria"] == cat,
              f"{status or '—'} «{detalle[:35]}…» → {r['categoria']} (esperaba {cat})")
        check(r["reintentable"] is reint, f"…y reintentable={r['reintentable']}")
    # los dos casos que las specs señalan expresamente
    check(pv.clasificar_error("rate limit mentioned in body", 401)["categoria"] == "auth",
          "un 401 NO se etiqueta como rate limit aunque el cuerpo diga «rate limit»")
    check(pv.clasificar_error("model_not_found", 404)["categoria"] != "infra",
          "un 404 de modelo NO se confunde con el servicio caído")


def test_mensaje_de_fallo_unico_y_funcional():
    m = pv.mensaje_fallo("You've exceeded the rate limit", 429, intentos=3)
    check(not pv.tiene_fugas(m), f"el mensaje de fallo va limpio: «{m}»")
    check("varios intentos" in m, "dice que lo ha intentado varias veces, sin detallarlos")
    check("ningún cambio" in m, "y deja claro que no ha tocado nada")
    m2 = pv.mensaje_fallo("invalid api key", 401)
    check("configuración" in m2 or "acceso" in m2,
          f"un problema de acceso se explica como tal: «{m2}»")
    check(not pv.tiene_fugas(m2), "sin tecnicismos")
    for status in (429, 401, 402, 404, 500, 0):
        check(not pv.tiene_fugas(pv.mensaje_fallo("x", status)),
              f"ningún mensaje de fallo ({status}) filtra nada")
    check("HTTP" not in m and "429" not in m, "el usuario no ve códigos HTTP")


# ══════════════ T17: el guardián no se puede desactivar sin enterarse ══════════

def test_lista_de_terminos_prohibidos():
    for termino in ("hermes", "gateway", "worker", "endpoint", "localhost", "api key"):
        check(termino in pv.PROHIBIDOS, f"«{termino}» está en la lista de prohibidos")
    check(pv.tiene_fugas("esto menciona el Gateway") == ["gateway"],
          "el detector no distingue mayúsculas")
    check(pv.tiene_fugas("una respuesta normal y corriente") == [],
          "y no da falsos positivos")


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    tests = [test_frases_prohibidas_de_las_specs, test_el_caso_real_de_la_captura,
             test_el_bus_es_la_ultima_barrera, test_la_skill_ya_nace_limpia,
             test_el_ejecutor_no_se_ve_en_la_tarjeta_de_multitarea,
             test_sanear_no_puede_dejar_la_respuesta_vacia,
             test_el_encargo_guardado_en_memoria_no_nombra_al_ejecutor,
             test_acuses_variados_y_contextuales, test_clasificacion_de_errores,
             test_mensaje_de_fallo_unico_y_funcional, test_lista_de_terminos_prohibidos]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
