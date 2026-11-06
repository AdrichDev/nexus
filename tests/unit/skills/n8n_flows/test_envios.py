# -*- coding: utf-8 -*-
"""WhatsApp de n8n: se pregunta, se confirma y no sale dos veces (SEC-05 / P1-4).

Lo que había antes: `handle("whatsapp", …)` hacía el POST al webhook de n8n —o
abría WhatsApp en el móvil— en la MISMA llamada, sin que nadie viera el mensaje
antes de que saliera, y sin nada que impidiera que la misma orden repetida
mandara el mensaje dos veces. El correo (skills/google_workspace) tenía
exactamente el mismo agujero. La asimetría era el hallazgo: borrar un evento o
vaciar la papelera de Drive SÍ pedían confirmación; hablar en nombre del
operador, no.

Contrato nuevo, y lo que se comprueba aquí, siempre por la puerta pública
(`handle()` + `confirm.answer()`):

  * la pregunta se arma ANTES de tocar n8n y ENSEÑA el mensaje tal cual;
  * el «sí» ejecuta la cadena de siempre —n8n primero, móvil después— dentro del
    `action`, así que la nota del grafo diario se escribe DESPUÉS del intento;
  * el «no» y cualquier otra frase no mandan nada;
  * la misma orden repetida dentro de la ventana (config/umbrales.json) no sale
    dos veces, y la segunda vez se dice que ya salió;
  * fuera de la ventana vuelve a salir.

Nada de esto habla con n8n, con el móvil ni con un modelo: `_post` y
`_safe_whatsapp_via_movil` son dobles, la auditoría se recoge en memoria y las
carpetas de datos apuntan a un temporal que se borra al terminar.

Ejecutar: .venv\\Scripts\\python.exe tests\\unit\\skills\\n8n_flows\\test_envios.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="nexus_envios_")
os.environ["NEXUS_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["NEXUS_CONFIG_DIR"] = os.path.join(TMP, "config")

from backend.core.comun import confirm  # noqa: E402

_fail: list[str] = []
_ok = 0


def check(cond, msg):
    global _ok
    if cond:
        _ok += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def carga_n8n():
    """El módulo de verdad del disco, sin pasar por el cargador de skills."""
    ruta = os.path.join(ROOT, "skills", "n8n_flows", "skill.py")
    spec = importlib.util.spec_from_file_location("n8n_envios_bajo_prueba", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeMatch:
    def __init__(self, gd):
        self._gd = gd

    def groupdict(self):
        return dict(self._gd)


class _FakeGraph:
    def __init__(self):
        self.lines = []

    def append_daily(self, line, section=""):
        self.lines.append((line, section))


class _Reloj:
    """Reloj de mentira: la ventana se prueba moviendo la hora, nunca durmiendo."""

    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def time(self):
        return self.t


_URL = "http://n8n.local/webhook/nexus"
_ORDEN = "envía un whatsapp a Ana diciendo llego tarde"
_MATCH = _FakeMatch({"to": "Ana", "body": "llego tarde", "to2": None, "body2": None,
                     "to3": None, "body3": None})


class _N8n:
    """Doble de la salida (n8n y móvil) + confirmación limpia."""

    def __init__(self, url=_URL, ok=True, detalle="HTTP 200"):
        self.url, self.ok, self.detalle = url, ok, detalle
        self.posts: list[tuple] = []
        self.movil: list[tuple] = []
        self.respuesta_movil = None
        self.auditorias: list[dict] = []
        self.graph = _FakeGraph()
        self.mod = None
        self._previos = {}

    def __enter__(self):
        self.mod = carga_n8n()
        self._previos = {"post": self.mod._post,
                         "movil": self.mod._safe_whatsapp_via_movil,
                         "audit": confirm._audit,
                         "time": confirm.time}
        confirm.clear()
        confirm.olvidar_envios()
        confirm._audit = lambda **kw: self.auditorias.append(kw)

        async def _post(url, payload):
            self.posts.append((url, payload))
            return self.ok, self.detalle

        async def _via_movil(to, body, ctx):
            self.movil.append((to, body))
            return self.respuesta_movil

        self.mod._post = _post
        self.mod._safe_whatsapp_via_movil = _via_movil
        return self

    def ctx(self):
        return {"settings": {"n8n_webhook_url": self.url}, "graph": self.graph,
                "channel": "pc"}

    def handle(self, frase=_ORDEN, match=None, intent="whatsapp"):
        return asyncio.run(self.mod.handle(intent, frase, match or _MATCH, self.ctx()))

    def responder(self, texto, canal="pc"):
        return asyncio.run(confirm.answer(texto, canal))

    def reloj(self, t=1_800_000_000.0):
        self._reloj = _Reloj(t)
        confirm.time = self._reloj
        return self._reloj

    def __exit__(self, *a):
        self.mod._post = self._previos["post"]
        self.mod._safe_whatsapp_via_movil = self._previos["movil"]
        confirm._audit = self._previos["audit"]
        confirm.time = self._previos["time"]
        confirm.clear()
        confirm.olvidar_envios()
        return False


def acciones(recogidas) -> list[str]:
    return [str(a.get("action", "")) for a in recogidas]


# ══════════════ 1) la pregunta va ANTES de cualquier salida ══════════════════
def test_el_whatsapp_se_pregunta_antes_de_tocar_n8n():
    with _N8n() as n:
        r = n.handle()
        check(n.posts == [], f"ha llamado a n8n ANTES de preguntar: {n.posts!r}")
        check(n.movil == [], f"ha usado el móvil antes de preguntar: {n.movil!r}")
        txt = r["reply"]
        check("Ana" in txt, "la pregunta no dice a QUIÉN va el WhatsApp")
        check("llego tarde" in txt,
              "la pregunta no enseña el MENSAJE que va a salir (lo que se manda se ve)")
        pend = confirm.pending("pc")
        check(pend is not None and pend["kind"] == "envio_whatsapp",
              "no ha quedado armada una confirmación de envío de WhatsApp")
        check(pend is not None and pend["destructive"] is False,
              "un envío no es destructivo: confirm.request debe recibir destructive=False")


def test_un_mensaje_largo_se_recorta_con_puntos_suspensivos():
    with _N8n() as n:
        largo = " ".join(f"palabra {i}" for i in range(400))
        match = _FakeMatch({"to": "Ana", "body": largo, "to2": None, "body2": None,
                            "to3": None, "body3": None})
        txt = n.handle(match=match)["reply"]
        check("…" in txt, "recorta el mensaje sin marcar el corte")
        check("palabra 399" not in txt, "no ha recortado nada")
        check("palabra 0 palabra 1" in txt, "el recorte no empieza por el mensaje de verdad")


# ══════════════════ 2) el «sí» ejecuta la cadena de siempre ═══════════════════
def test_confirmado_el_whatsapp_sale_una_vez_por_n8n():
    with _N8n() as n:
        n.handle()
        respuesta = n.responder("sí") or ""
        check(len(n.posts) == 1, f"confirmar debía hacer UN POST a n8n, hizo {len(n.posts)}")
        if n.posts:
            url, payload = n.posts[0]
            check(url == _URL, f"ha llamado a otra URL: {url!r}")
            check(payload == {"action": "whatsapp", "to": "Ana", "message": "llego tarde"},
                  f"ha mandado otro payload del que enseñó: {payload!r}")
        check("n8n" in respuesta and "Ana" in respuesta,
              f"la respuesta no cuenta lo que ha pasado: {respuesta!r}")
        check("📲" not in respuesta, "con n8n contestando bien no debe desviarse al móvil")


def test_la_nota_del_grafo_se_escribe_despues_del_intento_y_no_antes():
    with _N8n() as n:
        n.handle()
        check(n.graph.lines == [],
              f"escribe la nota del grafo ANTES de enviar: {n.graph.lines!r}")
        n.responder("sí")
        check(len(n.graph.lines) == 1,
              f"el envío confirmado no ha dejado su nota en el grafo: {n.graph.lines!r}")
        if n.graph.lines:
            check("n8n" in n.graph.lines[0][0] and n.graph.lines[0][1] == "Comunicación",
                  f"la nota del grafo no cuenta lo que pasó: {n.graph.lines!r}")


def test_si_n8n_falla_el_cierre_cae_al_movil_como_siempre():
    with _N8n(ok=False, detalle="HTTP 404") as n:
        n.respuesta_movil = {"reply": "📲 Te lo dejo listo en el móvil."}
        n.handle()
        check(n.posts == [] and n.movil == [],
              f"ha intentado salir antes del «sí»: {n.posts!r} {n.movil!r}")
        respuesta = n.responder("sí") or ""
        check(len(n.posts) == 1, f"debía intentar n8n una vez, intentó {len(n.posts)}")
        check(n.movil == [("Ana", "llego tarde")],
              f"al fallar n8n no ha caído al móvil: {n.movil!r}")
        check("📲" in respuesta, f"no contesta lo que ha pasado de verdad: {respuesta!r}")
        check("404" not in respuesta,
              "expone el error técnico de n8n al operador (esto ya estaba arreglado)")


def test_sin_webhook_tambien_pregunta_y_el_cierre_usa_el_movil():
    with _N8n(url="") as n:
        n.respuesta_movil = {"reply": "📲 Te lo dejo listo en el móvil."}
        txt = n.handle()["reply"]
        check(n.movil == [] and n.posts == [], "ha salido algo antes de confirmar")
        check("Ana" in txt and "llego tarde" in txt,
              f"la pregunta no enseña el mensaje: {txt[:200]!r}")
        respuesta = n.responder("sí") or ""
        check(n.posts == [], "sin webhook no hay nada que postear a n8n")
        check(n.movil == [("Ana", "llego tarde")],
              f"sin n8n el móvil es la vía: {n.movil!r}")
        check("📲" in respuesta, f"la respuesta no es la del móvil: {respuesta!r}")


# ═══════════════════ 3) sin «sí» no sale nada, y se dice ═════════════════════
def test_decir_que_no_no_manda_nada_y_lo_dice():
    with _N8n() as n:
        n.handle()
        respuesta = (n.responder("no") or "").lower()
        check(n.posts == [] and n.movil == [], "un «no» ha mandado el WhatsApp")
        check("no he enviado nada" in respuesta,
              f"al cancelar no dice la verdad (no he enviado nada): {respuesta!r}")
        check(n.graph.lines == [], "un envío cancelado ha escrito en el grafo diario")


def test_cambiar_de_tema_desa_rma_el_envio():
    with _N8n() as n:
        n.handle()
        respuesta = n.responder("hablamos de otra cosa luego")
        check(respuesta is None, f"una frase que no es sí/no debía devolver None: {respuesta!r}")
        check(confirm.pending("pc") is None,
              "la confirmación sigue armada tras cambiar de tema")
        check(n.posts == [] and n.movil == [], "ha mandado el WhatsApp al desarmar")


# ═══════════════════ 4) idempotencia: uno, no dos ════════════════════════════
def test_el_mismo_whatsapp_dos_veces_no_sale_dos_veces():
    with _N8n() as n:
        n.handle()
        n.responder("sí")
        segunda = n.handle()
        check(len(n.posts) == 1, f"el mismo WhatsApp ha salido {len(n.posts)} veces")
        check("Ana" in segunda["reply"] and "ya ha salido" in segunda["reply"].lower(),
              f"la segunda vez no dice que ya había salido: {segunda['reply']!r}")
        check(confirm.pending("pc") is None,
              "ha armado otra confirmación para un envío que ya había salido")
        hechas = acciones(n.auditorias)
        check(any(a.startswith("envio_aceptado") for a in hechas),
              f"el envío aceptado no queda en la auditoría: {hechas!r}")
        check(any(a.startswith("envio_duplicado") for a in hechas),
              f"el duplicado rechazado no queda en la auditoría: {hechas!r}")


def test_mayusculas_y_espacios_de_mas_no_abren_un_hueco_en_la_idempotencia():
    with _N8n() as n:
        n.handle()
        n.responder("sí")
        # misma huella escrita de otra forma: «ana»/«Ana», «Llego  tarde»/«llego tarde»
        otro = _FakeMatch({"to": "ana", "body": "Llego   tarde", "to2": None,
                           "body2": None, "to3": None, "body3": None})
        segunda = n.handle(match=otro)
        check(len(n.posts) == 1,
              f"la normalización falla: el mismo mensaje ha salido {len(n.posts)} veces")
        check("ya ha salido" in segunda["reply"].lower(),
              f"no avisa del duplicado escrito distinto: {segunda['reply']!r}")


def test_otro_mensaje_o_otro_destinatario_si_sale():
    with _N8n() as n:
        n.handle()
        n.responder("sí")
        otro = _FakeMatch({"to": "Ana", "body": "llego más tarde", "to2": None,
                           "body2": None, "to3": None, "body3": None})
        check(confirm.pending("pc") is None and
              n.handle(match=otro)["reply"], "otro texto debe volver a preguntar")
        n.responder("sí")
        a_pepe = _FakeMatch({"to": "Pepe", "body": "llego tarde", "to2": None,
                             "body2": None, "to3": None, "body3": None})
        n.handle(match=a_pepe)
        n.responder("sí")
        check(len(n.posts) == 3,
              f"otro texto y otro destinatario son otros envíos: {len(n.posts)}")


def test_pasada_la_ventana_el_mismo_whatsapp_vuelve_a_salir():
    with _N8n() as n:
        reloj = n.reloj()
        ventana = confirm.umbrales_envios()["ventana_idempotencia_seg"]
        check(ventana > 0, "la ventana de idempotencia no está configurada")
        n.handle()
        n.responder("sí")
        reloj.t += ventana + 1
        n.handle()
        n.responder("sí")
        check(len(n.posts) == 2,
              f"fuera de la ventana el mismo WhatsApp debe volver a salir: {len(n.posts)}")


# ═══════════ 5) lo que NO cambia: lanzar un flujo no pide confirmación ═══════
def test_lanzar_un_flujo_sigue_sin_confirmacion():
    with _N8n() as n:
        r = n.handle("lanza el flujo backup diario",
                     _FakeMatch({"flow": "backup diario", "flow2": None}), intent="flow")
        check(len(n.posts) == 1, f"un flujo debe dispararse sin confirmación: {n.posts!r}")
        if n.posts:
            check(n.posts[0][1].get("action") == "flow",
                  f"el flujo ha mandado otro payload: {n.posts[0]!r}")
        check("backup diario" in r["reply"], f"no nombra el flujo: {r['reply']!r}")
        check(confirm.pending("pc") is None,
              "lanzar un flujo ha dejado una confirmación armada que no toca")


def test_el_whatsapp_solo_sale_desde_dentro_de_la_confirmacion():
    """Guardia estructural: ni el POST ni el móvil pueden estar en la rama suelta."""
    ruta = os.path.join(ROOT, "skills", "n8n_flows", "skill.py")
    src = open(ruta, encoding="utf-8").read()
    rama = src.split('if intent == "whatsapp"')[1].split('if not url:')[0]
    check("confirm.request(" in rama, "el WhatsApp ya no pasa por confirm.request()")
    antes_de_enviar = rama.split("async def _enviar(")[0]
    check("async def _enviar(" in rama,
          "el WhatsApp ya no tiene una acción diferida que ejecute el envío")
    check("_post(" not in antes_de_enviar,
          "el POST a n8n está en la rama suelta, fuera del action: saldría sin preguntar")
    check("_safe_whatsapp_via_movil(" not in antes_de_enviar,
          "el móvil se usa fuera del action: saldría sin preguntar")


if __name__ == "__main__":
    try:
        for name, t in sorted(globals().items()):
            if name.startswith("test_") and callable(t):
                print(f"-- {t.__name__}")
                try:
                    t()
                except Exception as exc:                       # noqa: BLE001
                    _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                    print("  EXCEPCIÓN:", exc)
        print(f"\n{_ok} OK, {len(_fail)} fallo(s)")
        if _fail:
            for f in _fail:
                print(" -", f)
            sys.exit(1)
        sys.exit(0)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
