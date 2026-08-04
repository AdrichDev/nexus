# -*- coding: utf-8 -*-
"""Eventos de VARIOS DÍAS y títulos sin relleno.

Dos fallos reales, medidos el 03/08/2026 con frases del operador:

  1) «créame una tarea que dure del miércoles de esta semana hasta el domingo
     que sea Festival Sonorama Aranda de Duero» creaba una tarea titulada
     «que dure del miercoles de esta semana hasta que sea Festival Sonorama
     Aranda de Duero». El asunto va DETRÁS de las fechas y el relleno se
     quedaba dentro del título.
  2) De «del miércoles al domingo» solo se guardaba el domingo. Por eso el
     calendario pintaba un punto el día 5 en vez de una franja del 5 al 9.

No toca el tablero del usuario (se desvía a un temporal) y NO llama a Google:
`SKILLS_DIR` apunta a una google_workspace de mentira que se limita a apuntar
en un JSON el cuerpo del evento que se le habría mandado.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_eventos_varios_dias.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
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


TMP = Path(tempfile.mkdtemp(prefix="nexus_rangos_"))
from backend.core import skills_loader as sl
from backend.core.dominio import board
from backend.core.comun import config  # noqa: E402

board.BOARD_FILE = TMP / "board.json"
board.TRASH_FILE = TMP / "board_trash.json"
board._save([])

REG = sl.load_skills()
TSK = REG.get("tasks_board")
TB = TSK.module if TSK else None
check(TB is not None, "la skill tasks_board no carga")

HOY = dt.date.today()


def _dia(nombre: str) -> str:
    """El próximo día de la semana con ese nombre (nunca hoy), en ISO."""
    wd = TB.DIAS[nombre]
    return (HOY + dt.timedelta(days=(wd - HOY.weekday()) % 7 or 7)).isoformat()


# ═══════════ 1) el título es el ASUNTO, no la frase entera ═══════════
print("== 1) el título es el asunto, aunque venga detrás de las fechas ==")


def _extrae(frase: str) -> tuple[str, str | None, str | None, str | None]:
    """Lo mismo que hace el handler: hora → rango → fecha suelta → limpieza."""
    r = sl.route(frase)
    assert r and r[0].folder == "tasks_board", f"«{frase}» no llega al tablero: {r}"
    body = ""
    for g in ("body", "body2"):
        try:
            body = (r[2].group(g) or "").strip().rstrip(".")
        except Exception:                                  # noqa: BLE001
            body = ""
        if body:
            break
    if re.search(r"prioridad alta|urgente|importante", body, re.I):
        body = re.sub(r"(con )?prioridad alta|urgente", "", body, flags=re.I).strip()
    body, hora = TB._extract_time(body)
    body, ini, fin = TB._extract_range(body)
    if not ini:
        body, ini = TB._extract_due(body)
    return TB._limpia_titulo(body), ini, fin, hora


F1 = ("Creame una tarea que dure del miercoles de esta semana hasta el domingo "
      "que sea Festival Sonorama Aranda de Duero")
tit, ini, fin, hora = _extrae(F1)
check(tit == "Festival Sonorama Aranda de Duero",
      f"el título del festival sale con relleno: {tit!r}")
check(ini == _dia("miercoles"), f"el rango no empieza el miércoles: {ini}")
check(fin == _dia("domingo"), f"el rango no termina el domingo: {fin}")
check(hora is None, f"un rango de días pelados no lleva hora y ha sacado {hora}")

F2 = ("Anotame la tarea como una entrada de google calendar que dure desde el "
      "miercoles a las 15 de la tarde hasta el domingo")
tit, ini, fin, hora = _extrae(F2)
check(tit == "", f"«como una entrada de google calendar que dure» no es un título: {tit!r}")
check((ini, fin, hora) == (_dia("miercoles"), _dia("domingo"), "15:00"),
      f"el rango con hora sale mal: {ini} → {fin} a las {hora}")

for frase, esperado in (
        ("crea una tarea del 5 al 9 que sea Feria del libro", "Feria del libro"),
        ("crea una tarea desde el miércoles hasta el domingo que sea Sonorama", "Sonorama"),
        ("crea una tarea del miércoles al domingo llamada Sonorama", "Sonorama"),
        ("crea una tarea del miércoles al domingo: Sonorama", "Sonorama")):
    tit, ini, fin, _h = _extrae(frase)
    check(tit == esperado, f"«{frase}» → título {tit!r}, esperaba {esperado!r}")
    check(bool(ini) and bool(fin) and fin > ini,
          f"«{frase}» no saca un rango de varios días: {ini} → {fin}")

# NO REGRESIÓN: lo sencillo que ya funcionaba tiene que seguir igual
print("== 2) sin regresiones en las frases sencillas ==")
tit, ini, fin, hora = _extrae("crea una tarea de llamar al fontanero mañana a las 10")
check(tit == "llamar al fontanero", f"«llamar al fontanero» sale como {tit!r}")
check(ini == (HOY + dt.timedelta(days=1)).isoformat(),
      f"«mañana» no es mañana: {ini}")
check(fin is None, f"una fecha suelta no puede tener fin de rango: {fin}")
check(hora == "10:00", f"la hora se ha perdido: {hora}")

tit, ini, fin, hora = _extrae("apunta la mentoría el jueves a las 18")
check((tit, ini, fin, hora) == ("mentoría", _dia("jueves"), None, "18:00"),
      f"la mentoría del jueves sale mal: {tit!r} {ini} {fin} {hora}")

tit, ini, fin, _h = _extrae("crea la tarea diseñar calcetines para el viernes prioridad alta")
check((tit, ini, fin) == ("diseñar calcetines", _dia("viernes"), None),
      f"los calcetines del viernes salen mal: {tit!r} {ini} {fin}")

tit, ini, _f, _h = _extrae("crea la tarea diseñar logo")
check((tit, ini) == ("diseñar logo", None), f"una tarea sin fecha sale mal: {tit!r} {ini}")

# «de la mañana» / «por la mañana» son la FRANJA, no el día de mañana
_t, due = TB._extract_due("reunión el lunes por la mañana")
check(due == _dia("lunes"),
      f"«el lunes por la mañana» debería ser el lunes y ha dado {due}")

# ═══════════ 3) el cuerpo que se le manda a Google ═══════════
print("== 3) el cuerpo del evento que recibiría Google ==")
start, end, todo_el_dia = TB._cuerpo_evento("2026-08-05", "", "2026-08-09")
check((start, end, todo_el_dia) == ("2026-08-05", "2026-08-10", True),
      f"rango de día completo: Google quiere el fin EXCLUSIVO (+1 día), dio {start}→{end}")
start, end, todo_el_dia = TB._cuerpo_evento("2026-08-05", "15:00", "2026-08-09")
check((start, end, todo_el_dia) == ("2026-08-05T15:00:00", "2026-08-09T23:59:00", False),
      f"rango con hora: arranca a esa hora y acaba con el último día, dio {start}→{end}")
start, end, todo_el_dia = TB._cuerpo_evento("2026-08-05", "15:00", "")
check((start, end, todo_el_dia) == ("2026-08-05T15:00:00", "2026-08-05T16:00:00", False),
      f"un evento suelto con hora sigue durando una hora, dio {start}→{end}")

# ═══════════ 4) el handler REAL, con Google de mentira ═══════════
print("== 4) el handler crea el evento de varios días (Google simulado) ==")
FALSA = TMP / "skills" / "google_workspace"
FALSA.mkdir(parents=True, exist_ok=True)
(FALSA / "token.json").write_text("{}", encoding="utf-8")
REGISTRO = FALSA / "eventos.json"
(FALSA / "skill.py").write_text(
    "import json, pathlib\n"
    "TOKEN_FILE = pathlib.Path(__file__).with_name('token.json')\n"
    "_REG = pathlib.Path(__file__).with_name('eventos.json')\n"
    "def _create_event(summary, start, end=None, description='', all_day=False):\n"
    "    datos = json.loads(_REG.read_text(encoding='utf-8')) if _REG.exists() else []\n"
    "    datos.append({'summary': summary, 'start': start, 'end': end,\n"
    "                  'all_day': all_day})\n"
    "    _REG.write_text(json.dumps(datos, ensure_ascii=False), encoding='utf-8')\n"
    "    return 'https://example.invalid/evento'\n",
    encoding="utf-8")
config.SKILLS_DIR = TMP / "skills"          # nadie va a hablar con Google de verdad


def _handle(frase: str) -> dict:
    r = sl.route(frase)
    assert r and r[0].folder == "tasks_board", f"«{frase}» no llega al tablero: {r}"
    return asyncio.run(TB.handle(r[1], frase, r[2], {"channel": "pc"}))


board._save([])
res = _handle(F1)
reply = res.get("reply", "")
tareas = board._load()
check(len(tareas) == 1, f"el handler no ha creado una tarea: {len(tareas)}")
t = tareas[0] if tareas else {}
check(t.get("title") == "Festival Sonorama Aranda de Duero",
      f"el tablero guarda el título con relleno: {t.get('title')!r}")
check(t.get("due") == _dia("miercoles") and t.get("dueEnd") == _dia("domingo"),
      f"el tablero no guarda el rango entero: {t.get('due')} → {t.get('dueEnd')}")
check(t.get("kind") == "evento", f"un rango de días es un evento, no {t.get('kind')!r}")
check("Google Calendar" in reply, f"no dice que haya ido a Google Calendar: {reply!r}")

evs = json.loads(REGISTRO.read_text(encoding="utf-8")) if REGISTRO.exists() else []
check(len(evs) == 1, f"a Google le habría llegado {len(evs)} evento(s), esperaba 1")
if evs:
    ev = evs[0]
    print("   cuerpo enviado a Google:", json.dumps(ev, ensure_ascii=False))
    check(ev["summary"] == "Festival Sonorama Aranda de Duero",
          f"el evento de Google va con el título sucio: {ev['summary']!r}")
    check(ev["all_day"] is True, "un rango de días pelados es de día completo")
    check(ev["start"] == _dia("miercoles"), f"el evento no empieza el miércoles: {ev['start']}")
    esperado_fin = (dt.date.fromisoformat(_dia("domingo")) + dt.timedelta(days=1)).isoformat()
    check(ev["end"] == esperado_fin,
          f"el evento no abarca hasta el domingo (fin exclusivo {esperado_fin}): {ev['end']}")

# sin asunto NO se inventa un título: se pregunta y se dicen las fechas
REGISTRO.unlink(missing_ok=True)
board._save([])
res = _handle(F2)
check(not board._load(), "ha creado una tarea SIN asunto en vez de preguntar")
check(not REGISTRO.exists(), "ha mandado a Google un evento sin asunto")
check("asunto" in res.get("reply", "").lower(),
      f"no pregunta por el asunto: {res.get('reply')!r}")
check(_dia("miercoles") in res.get("reply", "") and _dia("domingo") in res.get("reply", ""),
      f"al preguntar tira las fechas que ya había entendido: {res.get('reply')!r}")

# ═══════════ 5) la agenda del HUD pinta TODOS los días del evento ═══════════
print("== 5) la agenda del HUD reparte el evento por todos sus días ==")
from _frontend_js import js_hud                            # noqa: E402

JS = js_hud()
check("calAbarca" in JS, "la agenda no tiene el reparto por rango (calAbarca)")
check(not re.search(r"\.filter\(\(t\) => t\.due === iso\)", JS),
      "la agenda sigue clavando cada tarea a un solo día (t.due === iso)")

_m = re.search(r"function calAbarca\([^)]*\)\s*\{.*?\n  \}", JS, re.S)
check(bool(_m), "no encuentro el cuerpo de calAbarca para ejecutarlo")
if _m:
    casos = [
        # (ini, fin, dia, finExclusivo, esperado)
        ("2026-08-05", "2026-08-10", "2026-08-05", True, True),    # 1er día, todo el día
        ("2026-08-05", "2026-08-10", "2026-08-07", True, True),    # día de en medio
        ("2026-08-05", "2026-08-10", "2026-08-09", True, True),    # ÚLTIMO día real
        ("2026-08-05", "2026-08-10", "2026-08-10", True, False),   # el fin es exclusivo
        ("2026-08-05", "2026-08-10", "2026-08-04", True, False),   # antes de empezar
        ("2026-08-05", "2026-08-09", "2026-08-09", False, True),   # con hora: fin inclusivo
        ("2026-08-05", "2026-08-05", "2026-08-05", False, True),   # evento de un solo día
        ("2026-08-05", "", "2026-08-06", False, False),            # sin fin: solo su día
    ]
    guion = (_m.group(0) + "\nconst casos = " + json.dumps(casos) + ";\n"
             "console.log(JSON.stringify(casos.map("
             "(c) => calAbarca(c[0], c[1], c[2], c[3]))));\n")
    try:
        out = subprocess.run(["node", "-e", guion], capture_output=True, text=True,
                             timeout=30)
        obtenido = json.loads(out.stdout.strip() or "[]")
        for caso, real in zip(casos, obtenido):
            check(real is caso[4],
                  f"calAbarca({caso[0]}, {caso[1]}, {caso[2]}, excl={caso[3]}) "
                  f"= {real}, esperaba {caso[4]}")
        check(len(obtenido) == len(casos),
              f"node solo ha evaluado {len(obtenido)} casos: {out.stderr[-300:]}")
    except FileNotFoundError:
        print("  (sin node instalado: calAbarca no se ha podido EJECUTAR)")
        _fail.append("no hay node para ejecutar calAbarca; la agenda queda sin probar")

# ═══════════ 6) nada personal dentro ═══════════
print("== 6) el código no lleva datos del usuario ==")
_PROPIOS = re.compile(r"\b(achoz|adri[aá]n|C:\\Users\\a)\b", re.I)
for rel in ("skills/tasks_board/skill.py", "skills/tasks_board/SKILL.md",
            "backend/core/dominio/board.py"):
    check(not _PROPIOS.search((ROOT / rel).read_text(encoding="utf-8")),
          f"{rel} lleva dentro datos del usuario")

print(f"\n{'#' * 54}\ntest_eventos_varios_dias: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail:
        print("  - " + f)
sys.exit(1 if _fail else 0)
