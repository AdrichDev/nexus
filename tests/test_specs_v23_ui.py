# -*- coding: utf-8 -*-
"""Tests de las specs v23 — FASES 6, 7, 8 y 11 (tareas personales, HUD y auditoría).

  T13 recordatorios razonables: nada de completadas, nada en horario de descanso,
      posponer, agrupar y registrar cuándo se avisó
  T14 persistencia estructurada de la ficha de cada tarea
  T15 la temperatura vive en el header
  T16 la pantalla «Hoy» desaparece y su ruta redirige
  T17 iconos del sidebar en SVG con currentColor
  T24 auditoría consultable de lo que hacen nexus y Hermes

Ejecutar:  python tests/test_specs_v23_ui.py    (desde la carpeta nexus)
"""
import datetime as dt
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend.core.dominio.board as board       # noqa: E402
import backend.core.comun.audit as audit       # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="nexus_v23u_"))
board.BOARD_FILE = _TMP / "board.json"
board.TRASH_FILE = _TMP / "board_trash.json"
audit.AUDIT_FILE = _TMP / "logs" / "audit.jsonl"


def _reset():
    board._save([])
    board._save_trash([])


# ══════════════ T14: ficha estructurada ══════════════

def test_ficha_completa_de_tarea():
    _reset()
    t = board.add_task("pintar la fachada", due="2026-08-01", priority="alta",
                       description="dos manos de blanco", reminder_at="2026-07-31T09:00",
                       source_conversation_id="conv-7")
    for campo in ("id", "title", "description", "priority", "dueDate", "reminderAt",
                  "createdAt", "updatedAt", "completedAt", "deletedAt",
                  "sourceConversationId"):
        check(campo in t, f"la ficha tiene {campo}")
    check(board.status_of(t) == "pending", "y su status en la nomenclatura de las specs")
    board.move_task(t["id"], "completada")
    t2 = board.find_task(t["id"])
    check(t2["completedAt"] and board.status_of(t2) == "completed",
          "al completarse queda sellada la fecha")


def test_las_tareas_sobreviven_a_reiniciar():
    _reset()
    board.add_task("comprar cemento")
    board._cache = None if False else None       # el store es en disco, no en memoria
    datos = board.BOARD_FILE.read_text(encoding="utf-8")
    check("comprar cemento" in datos, "la tarea está en disco, no solo en la conversación")
    check(any(t["title"] == "comprar cemento" for t in board._load()),
          "y se recupera al volver a leer")


# ══════════════ T13: recordatorios ══════════════

def test_no_recuerda_completadas():
    _reset()
    ayer = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    a = board.add_task("tarea vencida", due=ayer)
    b = board.add_task("tarea hecha", due=ayer)
    board.move_task(b["id"], "completada")
    board._en_silencio = lambda _now: False
    msgs = board.nudges()
    check(any("tarea vencida" in m for m in msgs), "avisa de la vencida")
    check(not any("tarea hecha" in m for m in msgs),
          "una tarea COMPLETADA deja de aparecer en los recordatorios")


def test_posponer_calla_el_aviso():
    _reset()
    ayer = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    t = board.add_task("llamar al arquitecto", due=ayer)
    board._en_silencio = lambda _now: False
    check(any("arquitecto" in m for m in board.nudges()), "primero sí avisa")
    board.snooze(t["id"], hours=3)
    tt = board.find_task(t["id"])
    check(bool(tt.get("snoozedUntil")), "queda apuntado hasta cuándo se pospone")
    tt["nudged"] = None
    board._save([tt])
    check(not any("arquitecto" in m for m in board.nudges()),
          "tras «recuérdamelo más tarde» NO vuelve a dar la lata")


def test_horario_de_descanso():
    _reset()
    ayer = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    board.add_task("cosa urgente", due=ayer)
    board._en_silencio = lambda _now: True
    check(board.nudges() == [], "en horario de descanso no se dan toques")
    board._en_silencio = lambda _now: False
    check(board.nudges() != [], "fuera de ese horario, sí")


def test_agrupa_y_registra():
    _reset()
    ayer = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    for i in range(6):
        board.add_task(f"pendiente {i}", due=ayer)
    board._en_silencio = lambda _now: False
    msgs = board.nudges()
    check(len(msgs) <= 3, f"agrupa en vez de soltar 6 avisos ({len(msgs)})")
    check(any("más" in m for m in msgs), "y dice cuántas quedan")
    t = board._load()[0]
    check(bool(t.get("lastReminder")), "registra cuándo se envió el último recordatorio")


def test_snooze_general():
    _reset()
    board.add_task("una")
    board.add_task("dos")
    check(board.snooze_all(1) == 2, "se pueden desactivar temporalmente todos los avisos")


# ══════════════ T15/T16/T17: HUD ══════════════

def test_temperatura_en_el_header():
    idx = Path(ROOT, "frontend", "index.html").read_text(encoding="utf-8")
    js = Path(ROOT, "frontend", "js", "command.js").read_text(encoding="utf-8")
    css = Path(ROOT, "frontend", "css", "command.css").read_text(encoding="utf-8")
    app = Path(ROOT, "backend", "app.py").read_text(encoding="utf-8")
    brf = Path(ROOT, "backend", "core", "dominio", "briefing.py").read_text(encoding="utf-8")
    i_head = idx.find("<header")
    i_wx = idx.find('id="wx"')
    i_endhead = idx.find("</header>")
    check(0 < i_head < i_wx < i_endhead, "el componente del tiempo está DENTRO del header")
    check("loadWeather" in js and "15 * 60 * 1000" in js, "se refresca solo, sin recargar")
    check("máx" in js and "mín" in js, "al desplegarlo enseña máxima y mínima")
    check('"/api/weather"' in app, "hay endpoint de tiempo")
    check("async def weather_now" in brf, "devuelve datos estructurados (no un texto)")
    check("except Exception:\n        return {}" in brf,
          "si el servicio meteorológico falla, devuelve vacío y no rompe nada")
    check("el.classList.add('hidden')" in js,
          "y el HUD simplemente esconde el componente")
    check(".wx{" in css and "@media" in css, "tiene estilo y el HUD sigue siendo adaptable")


def test_pantalla_hoy_eliminada():
    idx = Path(ROOT, "frontend", "index.html").read_text(encoding="utf-8")
    js = Path(ROOT, "frontend", "js", "command.js").read_text(encoding="utf-8")
    app = Path(ROOT, "backend", "app.py").read_text(encoding="utf-8")
    check('data-view="today"' not in idx, "el sidebar ya no tiene la sección «Hoy»")
    check("if (view === 'today') view = 'command';" in js,
          "la ruta antigua redirige en vez de romperse")
    check('"/api/today"' in app,
          "el payload sigue existiendo para el móvil y el briefing (nada duplicado en el HUD)")


def test_iconos_svg_coloreables():
    idx = Path(ROOT, "frontend", "index.html").read_text(encoding="utf-8")
    css = Path(ROOT, "frontend", "css", "command.css").read_text(encoding="utf-8")
    nav = idx[idx.find('<nav id="nav">'):idx.find("</nav>")]
    enlaces = re.findall(r"<a data-view=\"(\w+)\"[^>]*>(.*?)</a>", nav, re.S)
    check(len(enlaces) >= 11, f"el sidebar tiene sus entradas ({len(enlaces)})")
    for view, html in enlaces:
        check("<svg" in html, f"«{view}» usa SVG, no un glifo")
        check('stroke="currentColor"' in html,
              f"«{view}» hereda el color del texto (currentColor)")
        check('aria-hidden="true"' in html, f"«{view}» marca el icono como decorativo")
        check(not re.search(r'(?:fill|stroke)="#|rgb\(', html),
              f"«{view}» no lleva colores incrustados")
        check("<i>" not in html, f"«{view}» ya no usa el glifo de texto antiguo")
    check("#nav a .nav-ic" in css, "hay estilo para los iconos")
    check("var(--ic" in css.split("#nav a .nav-ic")[1][:260],
          "el color se aplica desde CSS (variable --ic), no desde el SVG")
    # v24: paleta FLÚOR, un color por sección, definida SOLO en el CSS
    vistas = [v for v, _ in enlaces]
    paleta = dict(re.findall(r'#nav a\[data-view="(\w+)"\]\s*\{--ic:(#[0-9a-fA-F]{6})', css))
    for v in vistas:
        check(v in paleta, f"«{v}» tiene su color propio en la paleta")
    check(len(set(paleta.values())) == len(paleta),
          f"cada sección tiene un color DISTINTO ({len(set(paleta.values()))} de {len(paleta)})")
    for v, c in paleta.items():
        r, g, b_ = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        check(max(r, g, b_) >= 0xE0, f"«{v}» ({c}) es un color vivo, de flúor")
        check(max(r, g, b_) - min(r, g, b_) >= 0x60, f"«{v}» ({c}) es saturado, no un gris")
    check("drop-shadow(0 0" in css, "los iconos brillan (halo de color)")
    check("#nav a.active .nav-ic" in css and "brightness(1.35)" in css,
          "y en la sección activa brillan más")
    for estado in ("a:hover", "a.active", "a:focus-visible"):
        check(estado in css.split("/* ── specs v23")[-1] or estado in css,
              f"el estado {estado} está contemplado")


# ══════════════ T24: auditoría ══════════════

def test_auditoria_consultable():
    audit.AUDIT_FILE.unlink(missing_ok=True)
    audit.log(action="clear_completed", actor="operador", agent="nexus",
              destructive=True, confirmed=True, request="borra las realizadas",
              targets=[{"id": "1", "title": "x"}], result="1 tarea a la papelera",
              run_id="req1")
    audit.log(action="file_read", actor="operador", agent="hermes",
              destructive=False, request="lee informe.md", result="ok")
    regs = audit.tail(10)
    check(len(regs) == 2, "se registran las acciones")
    d = audit.tail(10, destructive_only=True)
    check(len(d) == 1 and d[0]["action"] == "clear_completed",
          "las destructivas se pueden aislar")
    r = d[0]
    for campo in ("ts", "actor", "agent", "request", "targets", "result", "run_id"):
        check(campo in r and r[campo] not in (None, ""), f"el registro guarda {campo}")
    check(r["confirmed"] is True, "y si hubo confirmación")
    check(audit.tail(10)[-1]["agent"] == "hermes", "se registra qué agente actuó")

    brain = Path(ROOT, "backend", "core", "brain.py").read_text(encoding="utf-8")
    check("_AUDIT_RX" in brain, "se puede preguntar por el registro de actividad")
    mod = {}
    exec(compile(re.search(r"_AUDIT_RX = re\.compile\((?:.|\n)*?\)\n", brain).group(0),
                 "<a>", "exec"), {"re": re}, mod)
    for t in ("qué has hecho hoy", "qué has borrado", "por qué se borró",
              "registro de actividad"):
        check(bool(mod["_AUDIT_RX"].search(t)), f"«{t}» consulta la auditoría")
    check("destructive_only=solo_destructivas" in brain,
          "y puede filtrar solo lo destructivo")
    opm = Path(ROOT, "backend", "core", "dominio", "opmem.py").read_text(encoding="utf-8")
    check("audit" in opm and "RECALL_LOG" in opm,
          "la auditoría y los recuerdos de Engram son cosas distintas y separadas")


if __name__ == "__main__":
    tests = [test_ficha_completa_de_tarea, test_las_tareas_sobreviven_a_reiniciar,
             test_no_recuerda_completadas, test_posponer_calla_el_aviso,
             test_horario_de_descanso, test_agrupa_y_registra, test_snooze_general,
             test_temperatura_en_el_header, test_pantalla_hoy_eliminada,
             test_iconos_svg_coloreables, test_auditoria_consultable]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
