# -*- coding: utf-8 -*-
"""Eventos de VARIOS DÍAS en Google Calendar y títulos sin relleno.

Los dos fallos que ya se arreglaron en el tablero seguían vivos en
`google_workspace/create_event`, que es OTRO camino: «apunta la reunión…»,
«apunta el evento…» y «crea un evento…» los caza esa skill, no el tablero.
Medido el 03/08/2026:

  1) «apunta el evento Festival Sonorama del miercoles al domingo» creaba un
     evento de UN día (miércoles) porque `_parse_when` devolvía una sola fecha
     con fin a las 24 horas. El domingo no se pintaba.
  2) «crea un evento que dure del 5 al 9 que sea Feria del libro» no sacaba
     NINGUNA fecha, y el título se quedaba con el relleno entero
     («que dure del 5 al 9 que sea Feria del libro»).

NO habla con Google: se inyecta un `googleapiclient.discovery` de mentira que
apunta el cuerpo que se le habría mandado, y el tablero se desvía a un temporal.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_eventos_google_rango.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


TMP = Path(tempfile.mkdtemp(prefix="nexus_gcal_rango_"))
from backend.core import skills_loader as sl
from backend.core.dominio import board  # noqa: E402

board.BOARD_FILE = TMP / "board.json"
board.TRASH_FILE = TMP / "board_trash.json"
board._save([])

REG = sl.load_skills()
GWS = REG.get("google_workspace")
GW = GWS.module if GWS else None
check(GW is not None, "la skill google_workspace no carga")

HOY = dt.date.today()
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4,
        "sabado": 5, "domingo": 6}


def _dia(nombre: str) -> str:
    """El próximo día de la semana con ese nombre (nunca hoy), en ISO."""
    return (HOY + dt.timedelta(days=(DIAS[nombre] - HOY.weekday()) % 7 or 7)).isoformat()


def _suma(iso: str, dias: int) -> str:
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=dias)).isoformat()


# ═══════════ 1) estas frases son de Google Calendar, no del tablero ═══════════
print("== 1) el router las manda a google_workspace/create_event ==")
FRASES = ("apunta el evento Festival Sonorama del miercoles al domingo",
          "crea un evento que dure del 5 al 9 que sea Feria del libro",
          "apunta la reunion con el gestor el jueves a las 10")
for f in FRASES:
    r = sl.route(f)
    destino = f"{r[0].folder}/{r[1]}" if r else "SIN RUTA"
    check(destino == "google_workspace/create_event",
          f"«{f}» no llega a create_event: {destino}")

# ═══════════ 2) título, fechas y tipo de evento ═══════════
print("== 2) el título es el asunto y el rango son VARIOS días ==")

tit, start, end, all_day, ultimo = GW._datos_evento(
    "apunta el evento Festival Sonorama del miercoles al domingo")
check(tit == "Festival Sonorama", f"el título sale con relleno: {tit!r}")
check(start == _dia("miercoles"), f"el evento no empieza el miércoles: {start}")
check(ultimo == _dia("domingo"), f"el evento no termina el domingo: {ultimo}")
check(end == _suma(_dia("domingo"), 1),
      f"Google quiere el fin EXCLUSIVO (+1 día) en los de día completo: {end}")
check(all_day is True, "un rango de días pelados es de día completo")

tit, start, end, all_day, ultimo = GW._datos_evento(
    "crea un evento que dure del 5 al 9 que sea Feria del libro")
check(tit == "Feria del libro", f"«que dure» y «que sea» siguen en el título: {tit!r}")
check(bool(start) and bool(ultimo) and ultimo > start,
      f"«del 5 al 9» no da un rango de varios días: {start} → {ultimo}")
check(dt.date.fromisoformat(ultimo) - dt.date.fromisoformat(start) == dt.timedelta(days=4),
      f"del 5 al 9 son 5 días: {start} → {ultimo}")
check(all_day is True, "un rango sin hora es de día completo")

# el rango también se entiende con el mes dicho una sola vez y con hora
tit, start, end, all_day, ultimo = GW._datos_evento(
    "crea un evento del 5 al 9 de agosto que sea Feria del libro")
check((tit, start, ultimo, all_day) == ("Feria del libro", "2026-08-05", "2026-08-09", True),
      f"«del 5 al 9 de agosto» sale mal: {tit!r} {start} → {ultimo} (all_day={all_day})")

tit, start, end, all_day, ultimo = GW._datos_evento(
    "apunta el evento Sonorama desde el miercoles a las 15 hasta el domingo")
check(tit == "Sonorama", f"el título del rango con hora sale mal: {tit!r}")
check((start, end, all_day) == (f"{_dia('miercoles')}T15:00:00",
                                f"{_dia('domingo')}T23:59:00", False),
      f"el rango con hora arranca a esa hora y acaba con el último día: {start} → {end}")

# el asunto detrás de las fechas, con cada marcador
for frase, esperado in (
        ("apunta el evento del miercoles al domingo llamado Sonorama", "Sonorama"),
        ("apunta el evento del miercoles al domingo titulado Sonorama", "Sonorama"),
        ("apunta el evento del miercoles al domingo: Sonorama", "Sonorama"),
        ("crea un evento del miercoles al domingo que es Sonorama", "Sonorama")):
    tit, start, _e, _a, ultimo = GW._datos_evento(frase)
    check(tit == esperado, f"«{frase}» → título {tit!r}, esperaba {esperado!r}")
    check(bool(start) and bool(ultimo) and ultimo > start,
          f"«{frase}» no saca un rango de varios días: {start} → {ultimo}")

# ═══════════ 3) sin regresiones en las fechas sueltas ═══════════
print("== 3) las fechas sueltas siguen igual ==")
tit, start, end, all_day, ultimo = GW._datos_evento(
    "apunta la reunion con el gestor el jueves a las 10")
check(tit == "reunion con el gestor", f"la reunión con el gestor sale como {tit!r}")
check((start, end, all_day, ultimo) == (f"{_dia('jueves')}T10:00:00",
                                        f"{_dia('jueves')}T11:00:00", False, ""),
      f"la reunión del jueves a las 10 sale mal: {start} → {end} "
      f"(all_day={all_day}, ultimo={ultimo!r})")

tit, start, end, all_day, ultimo = GW._datos_evento(
    "crea un evento reunión con Ana el viernes a las 17:00")
check(tit == "reunión con Ana", f"la reunión con Ana sale como {tit!r}")
check((start, end, all_day) == (f"{_dia('viernes')}T17:00:00",
                                f"{_dia('viernes')}T18:00:00", False),
      f"la reunión con Ana sale mal: {start} → {end} (all_day={all_day})")

tit, start, end, all_day, ultimo = GW._datos_evento("crea un evento mañana a las 10")
manana = (HOY + dt.timedelta(days=1)).isoformat()
check((start, end, all_day) == (f"{manana}T10:00:00", f"{manana}T11:00:00", False),
      f"«mañana a las 10» sale mal: {start} → {end}")

tit, start, end, all_day, ultimo = GW._datos_evento("crea un evento cumpleaños el 25/12")
check(all_day is True and end == _suma(start, 1),
      f"un evento sin hora ocupa su día entero (fin exclusivo): {start} → {end}")
check(ultimo == "", f"una fecha suelta no tiene último día de rango: {ultimo!r}")

# «la cita CON el dentista»: ahí «cita» SÍ es parte del asunto
tit, _s, _e, _a, _u = GW._datos_evento("apunta la cita con el dentista el martes")
check(tit == "cita con el dentista", f"la cita con el dentista sale como {tit!r}")

# sin fecha no se inventa nada: se pregunta
tit, start, _e, _a, _u = GW._datos_evento("crea un evento Feria del libro")
check(start is None, f"sin fecha no puede salir una fecha: {start}")

# ═══════════ 4) el handler REAL, con Google de mentira ═══════════
print("== 4) el handler y el cuerpo EXACTO que recibiría Google ==")
ENVIADOS: list[dict] = []


class _Insert:
    def __init__(self, body):
        self._body = body

    def execute(self):
        ENVIADOS.append(self._body)
        return {"htmlLink": "https://example.invalid/evento"}


class _Events:
    def insert(self, calendarId=None, body=None):           # noqa: N803
        return _Insert(body)


class _Servicio:
    def events(self):
        return _Events()


_disc = types.ModuleType("googleapiclient.discovery")
_disc.build = lambda *a, **k: _Servicio()
sys.modules.setdefault("googleapiclient", types.ModuleType("googleapiclient"))
sys.modules["googleapiclient.discovery"] = _disc
sys.modules.setdefault("google_auth_oauthlib", types.ModuleType("google_auth_oauthlib"))
GW._get_creds = lambda: "credenciales-de-mentira"
GW._ensure_credentials = lambda ctx: True                   # nadie va a autorizar nada


def _handle(frase: str) -> dict:
    r = sl.route(frase)
    assert r and r[0].folder == "google_workspace", f"«{frase}» no llega a Google: {r}"
    return asyncio.run(GW.handle(r[1], frase, r[2], {"channel": "pc"}))


board._save([])
res = _handle("apunta el evento Festival Sonorama del miercoles al domingo")
reply = res.get("reply", "")
check(len(ENVIADOS) == 1, f"a Google le habría llegado {len(ENVIADOS)} evento(s), esperaba 1")
if ENVIADOS:
    ev = ENVIADOS[0]
    print("   cuerpo enviado a Google:", json.dumps(ev, ensure_ascii=False))
    check(ev.get("summary") == "Festival Sonorama",
          f"el evento va con el título sucio: {ev.get('summary')!r}")
    check(ev.get("start") == {"date": _dia("miercoles")},
          f"el evento no empieza el miércoles: {ev.get('start')}")
    check(ev.get("end") == {"date": _suma(_dia("domingo"), 1)},
          f"el evento no abarca hasta el domingo (fin exclusivo): {ev.get('end')}")
    check("dateTime" not in json.dumps(ev),
          "un rango de días pelados no lleva hora, va como día completo")

tareas = board._load()
check(len(tareas) == 1, f"el espejo del tablero ha creado {len(tareas)} tareas, esperaba 1")
t = tareas[0] if tareas else {}
check(t.get("title") == "Festival Sonorama",
      f"el tablero guarda el título con relleno: {t.get('title')!r}")
check(t.get("due") == _dia("miercoles") and t.get("dueEnd") == _dia("domingo"),
      f"el tablero no guarda el rango entero (último día INCLUSIVE): "
      f"{t.get('due')} → {t.get('dueEnd')}")
check(t.get("kind") == "evento", f"un evento de calendario no es {t.get('kind')!r}")
check(_dia("domingo")[8:10] in reply or "/" in reply,
      f"la respuesta no dice hasta cuándo dura: {reply!r}")

ENVIADOS.clear()
board._save([])
res = _handle("apunta la reunion con el gestor el jueves a las 10")
if check(len(ENVIADOS) == 1, "la reunión suelta no ha llegado a Google"):
    ev = ENVIADOS[0]
    print("   cuerpo enviado a Google:", json.dumps(ev, ensure_ascii=False))
    check(ev.get("summary") == "reunion con el gestor",
          f"el título de la reunión sale sucio: {ev.get('summary')!r}")
    check(ev.get("start", {}).get("dateTime") == f"{_dia('jueves')}T10:00:00",
          f"la reunión no empieza el jueves a las 10: {ev.get('start')}")
    check(ev.get("end", {}).get("dateTime") == f"{_dia('jueves')}T11:00:00",
          f"la reunión suelta debe durar una hora: {ev.get('end')}")
t = (board._load() or [{}])[0]
check(t.get("dueEnd") is None, f"una reunión de un día no tiene rango: {t.get('dueEnd')}")

# ═══════════ 5) nada personal dentro ═══════════
print("== 5) el código no lleva datos del usuario ==")
_PROPIOS = re.compile(r"\b(achoz|adri[aá]n|C:\\Users\\a)\b", re.I)
for rel in ("skills/google_workspace/skill.py", "skills/google_workspace/SKILL.md"):
    check(not _PROPIOS.search((ROOT / rel).read_text(encoding="utf-8")),
          f"{rel} lleva dentro datos del usuario")

# ═══════════ 6) sin asunto se pregunta, no se inventa ═══════════
print("== 6) un evento sin nombre se pregunta, no se titula «Evento» ==")

# El tablero ya lo hacía así con las tareas; aquí se titulaba «Evento» y se
# creaba igual. Un evento llamado «Evento» en el calendario es peor que no
# crearlo: dentro de una semana no dice nada, y hay que abrirlo para saber qué
# era. Es el mismo fallo que dejó títulos basura en la agenda del usuario.
_antes = list(ENVIADOS)
_res = _handle("apunta un evento el jueves a las 10")
check("¿" in _res.get("reply", ""),
      f"no pregunta de qué es el evento: {_res.get('reply', '')[:90]}")
check(ENVIADOS == _antes,
      f"ha creado un evento sin nombre: {ENVIADOS[len(_antes):]}")
check("evento de qué" in _res.get("reply", "").lower(),
      f"no dice qué le falta: {_res.get('reply', '')[:90]}")


print(f"\n{'#' * 54}\ntest_eventos_google_rango: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail:
        print("  - " + f)
sys.exit(1 if _fail else 0)
