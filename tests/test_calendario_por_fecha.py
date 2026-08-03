# -*- coding: utf-8 -*-
"""Borrar eventos del calendario POR FECHA, con confirmación y en dd/mm/aaaa.

Los tres fallos que arregla esta suite salieron de una sesión real (03/08/2026):

  1. «quiero que elimines las dos tareas del calendario que hay el miércoles día
     5 y la que hay el domingo, día 9» no llegaba a la skill de Google: se la
     quedaba el tablero interno. Y «borra los eventos del día 5» no la cazaba
     NADIE (el sustantivo iba en singular con \\b detrás, así que el plural
     «eventos» no casaba). El borrado solo sabía buscar por TÍTULO.
  2. Las fechas se cantaban al revés: «2026-08-05» en vez de «05/08/2026».
  3. Tras fallar el borrado, nexus soltaba la agenda entera. Adri: «Por qué lees
     las citas del calendario si no lo he pedido».

REGLA ABSOLUTA: NI UNA llamada real a Google. `_fetch_events`, `_find_events` y
`_delete_event` van pisados con dobles; el calendario de verdad no se toca.

Ejecutar: .venv\\Scripts\\python.exe tests\\test_calendario_por_fecha.py
"""
import asyncio
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_cal_"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

from backend.core import confirm, skills_loader                # noqa: E402

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


skills_loader.load_skills()
GW = skills_loader.get_skills()["google_workspace"].module

HOY = dt.date.today()
DIA5 = GW._proximo_dia_mes(5, HOY)                 # el «día 5» que toque
DIA9 = GW._proximo_dia_mes(9, HOY)


def _iso(d):
    return d.isoformat()


def _ddmmaaaa(d):
    return d.strftime("%d/%m/%Y")


# ─────────────────────── dobles: agenda de MENTIRA ───────────────────────
_BORRADOS: list[str] = []


def _agenda():
    """Tres eventos en las fechas pedidas y uno lejos, para ver que no se cuela."""
    lejos = HOY + dt.timedelta(days=45)
    return [
        {"id": "ev-A", "what": "Dentista", "fecha": _iso(DIA5), "hora": "10:00",
         "hora_fin": "11:00", "fecha_fin": _iso(DIA5), "todo_el_dia": False,
         "when": f"{_iso(DIA5)} 10:00", "desc": "", "lugar": ""},
        {"id": "ev-B", "what": "Revision del coche", "fecha": _iso(DIA5), "hora": "",
         "hora_fin": "", "fecha_fin": _iso(DIA5 + dt.timedelta(days=1)),
         "todo_el_dia": True, "when": _iso(DIA5), "desc": "", "lugar": ""},
        {"id": "ev-C", "what": "Comida con Ana", "fecha": _iso(DIA9), "hora": "14:00",
         "hora_fin": "15:00", "fecha_fin": _iso(DIA9), "todo_el_dia": False,
         "when": f"{_iso(DIA9)} 14:00", "desc": "", "lugar": ""},
        {"id": "ev-Z", "what": "Gimnasio", "fecha": _iso(lejos), "hora": "19:00",
         "hora_fin": "20:00", "fecha_fin": _iso(lejos), "todo_el_dia": False,
         "when": f"{_iso(lejos)} 19:00", "desc": "", "lugar": ""},
    ]


class _SinGoogle:
    """Pisa TODO lo que hablaría con Google y aparta las credenciales reales."""

    def __init__(self, agenda=None):
        self.agenda = _agenda() if agenda is None else agenda
        self.lecturas = 0

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="nexus_cal_creds_")
        self.viejo = (GW.CREDS_FILE, GW.TOKEN_FILE, GW._fetch_events,
                      GW._find_events, GW._delete_event)
        GW.CREDS_FILE = Path(self.tmp, "google_credentials.json")
        GW.TOKEN_FILE = Path(self.tmp, "google_token.json")
        GW.CREDS_FILE.write_text(json.dumps(
            {"installed": {"client_id": "prueba", "client_secret": "prueba"}}),
            encoding="utf-8")

        def _fetch(limit=6, tmin=None, tmax=None):
            self.lecturas += 1
            return list(self.agenda)

        def _find(query="", limit=10):
            self.lecturas += 1
            q = (query or "").strip().lower()
            return [{"id": e["id"], "summary": e["what"], "start": e["fecha"],
                     "when": e["when"]} for e in self.agenda
                    if not q or q in e["what"].lower()]

        def _borra(eid):
            _BORRADOS.append(eid)
            return True

        GW._fetch_events, GW._find_events, GW._delete_event = _fetch, _find, _borra
        _BORRADOS.clear()
        confirm.clear()
        return self

    def __exit__(self, *a):
        (GW.CREDS_FILE, GW.TOKEN_FILE, GW._fetch_events,
         GW._find_events, GW._delete_event) = self.viejo
        confirm.clear()
        return False


class _Ajustes:
    def secret(self, k, d=""):
        return ""

    def get(self, k, d=None):
        return d


def _ctx():
    return {"settings": _Ajustes(), "channel": "pc"}


def _ruta(frase):
    r = skills_loader.route(frase)
    return (r[0].folder, r[1], r[2]) if r else (None, None, None)


def _pedir(frase):
    """Enruta la frase de verdad y ejecuta el handler. Devuelve (folder/intent, reply)."""
    folder, intent, m = _ruta(frase)
    if folder != "google_workspace":
        return f"{folder}/{intent}", ""
    r = asyncio.run(GW.handle(intent, frase, m, _ctx()))
    return f"{folder}/{intent}", r.get("reply", "")


# ══════════════ 1. ENRUTADO: la frase real de Adri llega a la skill ══════════
FRASES_DE_FECHA = [
    "quiero que elimines las dos tareas del calendario que hay el miércoles día 5 "
    "y la que hay el domingo, día 9",
    "elimina las dos tareas del calendario que hay el miercoles dia 5 y la que hay "
    "el domingo dia 9",
    "borra los eventos del día 5",
    "borra los eventos del dia 5",
    "cancela el evento del 5 de agosto",
    "borra la cita del miercoles",
    "borra las citas del 5 y del 9",
    "elimina los eventos de mañana",
    "cancela las citas del 5 y del 9",
    "elimina las tareas del calendario del miércoles",
]


def test_borrar_eventos_por_fecha_enruta_a_google_no_al_tablero():
    """El plural y el subjuntivo. «borra los EVENTOS del día 5» no la cazaba
    nadie y «elimines las tareas del CALENDARIO» se la llevaba tasks_board."""
    for frase in FRASES_DE_FECHA:
        folder, intent, _ = _ruta(frase)
        check(folder == "google_workspace" and intent == "delete_event",
              f"«{frase}» → {folder}/{intent} (se esperaba google_workspace/delete_event)")


def test_lo_que_ya_funcionaba_sigue_funcionando():
    """El borrado por TÍTULO no se ha roto al meter el de por fecha."""
    for frase in ("cancela la reunión con el CTO", "borra el evento del jueves",
                  "anúlame la cita del dentista", "quita esa cita"):
        folder, intent, _ = _ruta(frase)
        check(folder == "google_workspace" and intent == "delete_event",
              f"«{frase}» → {folder}/{intent}; era delete_event")


def test_no_le_roba_los_borrados_de_otras_skills():
    """El patrón nuevo menciona «calendario» y verbos de borrar: si se pasa de
    ancho se lleva ficheros locales, correos o tareas del tablero de verdad."""
    ajenas = {
        "borra el correo 3": ("google_workspace", "delete_email"),
        "borra informe-viejo.md de drive": ("google_workspace", "drive_delete"),
        "borra el archivo D:/tmp/x.txt": ("files", None),
        "borra la carpeta pruebas": ("files", None),
        "borra la tarea de llamar al banco": ("tasks_board", None),
        "borra todas las tareas": ("tasks_board", None),
    }
    for frase, (folder_ok, intent_ok) in ajenas.items():
        folder, intent, _ = _ruta(frase)
        check(folder == folder_ok and (intent_ok is None or intent == intent_ok),
              f"«{frase}» → {folder}/{intent}; era de {folder_ok}/{intent_ok or '*'}")


# ══════════════════ 2. LAS FECHAS QUE SE LEEN DE LA ORDEN ════════════════════
def test_las_fechas_del_selector_se_entienden():
    casos = {
        "borra los eventos del día 5": [DIA5],
        "borra las citas del 5 y del 9": [DIA5, DIA9],
        "elimina las dos tareas del calendario que hay el miercoles dia 5 y la que "
        "hay el domingo dia 9": [DIA5, DIA9],
        "elimina los eventos de mañana": [HOY + dt.timedelta(days=1)],
        "borra los eventos de hoy": [HOY],
        "borra los eventos de pasado mañana": [HOY + dt.timedelta(days=2)],
    }
    for frase, esperado in casos.items():
        check(GW._fechas_pedidas(frase) == sorted(esperado),
              f"«{frase}» → {[d.isoformat() for d in GW._fechas_pedidas(frase)]}, "
              f"se esperaba {[d.isoformat() for d in sorted(esperado)]}")


def test_el_numero_manda_sobre_el_dia_de_la_semana():
    """«el miércoles día 5»: si se hicieran caso los dos, saldría también el
    PRÓXIMO miércoles y se borrarían eventos que nadie ha pedido borrar."""
    f = GW._fechas_pedidas("borra lo del miercoles dia 5")
    check(f == [DIA5], f"salen {[d.isoformat() for d in f]} en vez de solo {DIA5}")


def test_la_hora_no_se_confunde_con_el_dia_siguiente():
    """«a las 9 de la mañana» es una HORA. Sin el candado, «mañana» sumaba un día."""
    f = GW._fechas_pedidas("borra el evento del día 5 a las 9 de la mañana")
    check(f == [DIA5], f"«de la mañana» se ha leído como el día siguiente: {f}")


def test_el_numero_de_un_evento_no_es_una_fecha():
    """«cancela el evento 2» es el segundo de una lista, no el día 2 del mes."""
    check(GW._fechas_pedidas("cancela el evento 2") == [],
          "«el evento 2» se ha leído como el día 2")


def test_una_frase_sin_fecha_no_inventa_ninguna():
    check(GW._fechas_pedidas("cancela la reunión con el CTO") == [],
          "se ha inventado una fecha donde no la hay")


# ═══════════════ 3. EL HANDLER: qué selecciona y qué pregunta ════════════════
def test_selecciona_los_eventos_de_esos_dias_y_solo_esos():
    with _SinGoogle():
        _, reply = _pedir("elimina las dos tareas del calendario que hay el "
                          "miercoles dia 5 y la que hay el domingo dia 9")
        p = confirm.pending("pc")
        ids = [t["id"] for t in p["targets"]] if p else []
    check(ids == ["ev-A", "ev-B", "ev-C"],
          f"ha seleccionado {ids}; se esperaban los 3 de los días {DIA5} y {DIA9}")
    check("ev-Z" not in ids, "se ha colado un evento de otro día")
    # Ya no dice «3 eventos»: la lista puede mezclar eventos del calendario y
    # tareas del tablero, que es lo que la agenda enseña junto.
    check("Voy a borrar 3" in reply, f"no dice cuántos va a borrar: {reply[:80]}")


def test_no_borra_nada_hasta_que_se_dice_que_si():
    with _SinGoogle():
        _pedir("borra los eventos del día 5")
        check(_BORRADOS == [], f"HA BORRADO SIN PREGUNTAR: {_BORRADOS}")
        check(confirm.pending("pc") is not None, "no ha dejado la confirmación armada")
        salida = asyncio.run(confirm.answer("sí", "pc"))
        check(_BORRADOS == ["ev-A", "ev-B"], f"tras el «sí» ha borrado {_BORRADOS}")
        check("2" in (salida or ""), f"no dice cuántos ha borrado: {salida}")


def test_un_no_no_borra_nada():
    with _SinGoogle():
        _pedir("borra los eventos del día 5")
        salida = asyncio.run(confirm.answer("no", "pc"))
        check(_BORRADOS == [], f"ha borrado después de un NO: {_BORRADOS}")
        check(salida == "Vale, no borro nada.", f"respuesta al no: {salida!r}")


def test_la_confirmacion_dice_exactamente_que_se_va_a_borrar():
    with _SinGoogle():
        _, reply = _pedir("borra los eventos del día 5")
    check("Dentista" in reply and "Revision del coche" in reply,
          f"no enseña los títulos que va a borrar: {reply!r}")
    check(_ddmmaaaa(DIA5) in reply, f"no enseña la fecha en dd/mm/aaaa: {reply!r}")
    check(reply.rstrip().endswith("¿Los borro?"), f"no pide un sí/no: {reply!r}")


def test_si_solo_hay_uno_lo_dice_en_singular_y_corto():
    with _SinGoogle() as g:
        g.agenda = [g.agenda[2]]                    # solo la comida del día 9
        _, reply = _pedir("borra los eventos del día 9")
    check(reply == f"Voy a borrar «Comida con Ana» ({_ddmmaaaa(DIA9)} 14:00). ¿Lo borro?",
          f"la pregunta de un solo evento no es la esperada: {reply!r}")


def test_si_no_hay_nada_ese_dia_lo_dice_corto_y_para():
    with _SinGoogle() as g:
        g.agenda = []
        _, reply = _pedir("borra los eventos del día 5")
    # Nombra los DOS sitios donde ha mirado: decir solo «en tu calendario» era
    # cierto y a la vez inútil con una tarea de ese día en pantalla.
    check(_ddmmaaaa(DIA5) in reply and "no hay nada" in reply.lower(),
          f"respuesta cuando no hay nada: {reply!r}")
    check("tablero" in reply.lower(),
          f"no dice que también ha mirado el tablero: {reply!r}")
    check(confirm.pending("pc") is None, "deja armada una confirmación sin víctimas")
    check(len(reply) < 90, f"se enrolla cuando no hay nada que borrar: {len(reply)} caracteres")


def test_un_evento_de_varios_dias_cuenta_en_todos_ellos():
    """Un evento de día completo del 4 al 6 SÍ está el día 5. Google da el final
    exclusivo, así que hay que recorrer el rango."""
    with _SinGoogle() as g:
        g.agenda = [{"id": "ev-largo", "what": "Vacaciones",
                     "fecha": _iso(DIA5 - dt.timedelta(days=1)), "hora": "",
                     "hora_fin": "", "fecha_fin": _iso(DIA5 + dt.timedelta(days=2)),
                     "todo_el_dia": True, "when": _iso(DIA5 - dt.timedelta(days=1)),
                     "desc": "", "lugar": ""}]
        _pedir("borra los eventos del día 5")
        p = confirm.pending("pc")
    check(p is not None and [t["id"] for t in p["targets"]] == ["ev-largo"],
          "un evento que abarca el día 5 no se ha encontrado")


# ══════════ 4. FECHAS EN dd/mm/aaaa (mostrar), ISO por dentro (datos) ════════
def test_las_fechas_se_muestran_dd_mm_aaaa():
    casos = {"2026-08-05": "05/08/2026",
             "2026-08-05T10:00:00": "05/08/2026 10:00",
             "2026-08-05 10:00": "05/08/2026 10:00",
             "2026-12-31": "31/12/2026"}
    for iso, esperado in casos.items():
        check(GW._fmt_cuando(iso) == esperado,
              f"_fmt_cuando({iso!r}) = {GW._fmt_cuando(iso)!r}, se esperaba {esperado!r}")
    check(GW._fmt_cuando("") == "", "con la cadena vacía debería devolver vacío")
    check(GW._fmt_cuando("mañana") == "mañana", "lo que no es ISO se deja como está")


def test_el_listado_del_calendario_tambien_va_en_dd_mm_aaaa():
    with _SinGoogle():
        r = asyncio.run(GW.handle("gcal", "qué tengo en el calendario", None, _ctx()))
    reply = r["reply"]
    check(_ddmmaaaa(DIA5) in reply, f"el listado sigue en ISO: {reply[:120]}")
    check(_iso(DIA5) not in reply, f"el listado enseña la fecha ISO al usuario: {reply[:120]}")


def test_por_dentro_las_fechas_siguen_en_iso():
    """Lo que se le manda a Google y lo que viaja al frontend NO puede cambiar:
    la API solo entiende ISO y la vista de agenda parte `fecha` por guiones."""
    src = Path(ROOT, "skills", "google_workspace", "skill.py").read_text(encoding="utf-8")
    check('"fecha": start[:10]' in src,
          "el dato `fecha` de un evento ya no es ISO; la vista de agenda se rompe")
    check('{"date": start}' in src,
          "a Google se le está mandando algo que no es la fecha ISO")


# ═════════ 5. UN BORRADO QUE FALLA NO SE CONVIERTE EN UN LISTADO ═════════════
def test_una_orden_de_borrar_nunca_lista_el_calendario():
    """El fallo de la sesión: la frase caía al planificador del cerebro, que la
    mandaba a `gcal`, y nexus soltaba la agenda entera sin que nadie la pidiera."""
    for frase in ("borra los eventos del día 5",
                  "elimina las dos tareas del calendario del miércoles",
                  "cancela las citas del domingo"):
        with _SinGoogle() as g:
            r = asyncio.run(GW.handle("gcal", frase, None, _ctx()))
        reply = r["reply"]
        check(g.lecturas == 0,
              f"«{frase}» ha leído la agenda ({g.lecturas} veces) para listarla")
        check("Dentista" not in reply and "Próximos eventos" not in reply,
              f"«{frase}» ha listado el calendario: {reply[:120]}")
        check(len(reply) < 160, f"se enrolla al rechazar: {len(reply)} caracteres")


def test_consultar_el_calendario_sigue_listando():
    """El candado no puede pasarse de listo: preguntar SÍ lista."""
    with _SinGoogle() as g:
        r = asyncio.run(GW.handle("gcal", "qué tengo en el calendario", None, _ctx()))
    check("Dentista" in r["reply"], f"ya no lista cuando se le pide: {r['reply'][:120]}")
    check(g.lecturas >= 1, "no ha llegado a leer la agenda")


# ═════════════════════ 6. TONO: respuestas cortas ════════════════════════════
def test_las_respuestas_del_borrado_son_cortas():
    with _SinGoogle():
        _, uno = _pedir("borra los eventos del día 5")
    check(len(uno.splitlines()) <= 6, f"la confirmación tiene {len(uno.splitlines())} líneas")
    for linea in uno.splitlines():
        check(len(linea) <= 80, f"línea larga en la confirmación: {linea!r}")

def test_borrar_por_fecha_alcanza_tambien_las_tareas_del_tablero():
    """LO QUE PASÓ DE VERDAD (03/08/2026). Adrián borró el evento del día 5 y en
    la agenda seguía viendo algo el 5 y algo el 9. Pidió borrarlos y nexus
    contestó «no hay nada en tu calendario el 05 y el 09» — cierto, y a la vez
    inútil: lo que veía eran TAREAS DEL TABLERO con fecha.

    La agenda del HUD pinta las dos cosas juntas. Quien mira la pantalla no
    distingue, y no tiene por qué: «borra lo que haya el día 5» se refiere a lo
    que se VE. Mirar solo el calendario es contestar a otra pregunta."""
    from backend.core import board
    tareas = [{"id": "t5", "due": _iso(HOY + dt.timedelta(days=2)),
               "title": "tarea del dia del evento", "state": "pendiente"},
              {"id": "t9", "due": _iso(HOY + dt.timedelta(days=6)),
               "title": "tarea de otro dia", "state": "pendiente"},
              {"id": "tx", "due": _iso(HOY + dt.timedelta(days=20)),
               "title": "esta no se toca", "state": "pendiente"}]
    borradas = []
    viejo_load, viejo_del = board._load, board.delete_task
    board._load = lambda: list(tareas)
    board.delete_task = lambda q, reason="", by="": (borradas.append(q)
                                                     or {"id": q, "count": 1, "batch": "b"})
    try:
        dia = (HOY + dt.timedelta(days=2)).day
        with _SinGoogle():
            _ruta_r, r = _pedir(f"borra lo que haya el dia {dia}")
            check("Voy a borrar" in r, f"no propone borrar nada teniendo tarea: {r[:90]}")
            check(not borradas, "borra la tarea ANTES de que se confirme")
            asyncio.run(confirm.answer("si", "pc"))
            check("t5" in borradas,
                   f"la tarea del tablero de ese día no se borra ({borradas})")
            check("tx" not in borradas, "se lleva por delante una tarea de otro día")
    finally:
        board._load, board.delete_task = viejo_load, viejo_del


def test_un_dia_de_letra_es_un_dia():
    """«borra también la del día NUEVE». Hablando se dicen los días en letra, y
    por voz el dictado los escribe así casi siempre. El router mira el texto
    crudo, así que tiene que reconocerlos ÉL: cuando llega al parser de fechas
    ya sería tarde."""
    for palabra, numero in (("cinco", 5), ("nueve", 9), ("veintitres", 23)):
        folder, intent, _m = _ruta(f"borra los del dia {palabra}")
        check((folder, intent) == ("google_workspace", "delete_event"),
               f"«del día {palabra}» no llega al borrado ({folder}/{intent})")
        fechas = GW._fechas_pedidas(f"borra los del dia {palabra}")
        check(fechas and fechas[0].day == numero,
               f"«{palabra}» no se entiende como día {numero} ({fechas})")


def test_si_ya_lo_ha_comprobado_el_no_se_le_pregunta():
    """«bórrala directamente, ya lo he comprobado yo», «no preguntes más».

    La confirmación está para que nadie borre a ciegas, no para hacer repetir al
    operador. Si dice que ya lo ha mirado, ya está mirado — y todo va a la
    papelera, así que tampoco es irreversible."""
    with _SinGoogle() as g:
        dia = dt.date.fromisoformat(g.agenda[0]["fecha"]).day
        _ruta_r, r = _pedir(f"borra los del dia {dia} directamente, ya lo he comprobado yo")
        check("¿" not in r, f"sigue preguntando cuando le han dicho que no ({r[:80]})")
        check(_BORRADOS, f"no ha borrado nada pese a la orden directa ({r[:80]})")

    # Y sin esa coletilla, SIGUE preguntando: el atajo es explícito, no el modo
    # por defecto.
    with _SinGoogle() as g:
        dia = dt.date.fromisoformat(g.agenda[0]["fecha"]).day
        _ruta_r, r = _pedir(f"borra los del dia {dia}")
        check("¿" in r, f"ha dejado de preguntar cuando nadie se lo ha pedido ({r[:80]})")
        check(not _BORRADOS, "borra sin confirmación cuando no se la han quitado")


# =============================== runner =====================================
if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                           # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
