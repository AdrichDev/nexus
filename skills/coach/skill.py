"""Minion Coach/Secretario — briefing diario, objetivos desglosados en pasos,
checklists, recordatorios escalonados, replanificación y specs de proyecto.

Objetivos y recordatorios se persisten en Postgres cuando está online; sin él,
objetivos van al grafo y recordatorios a los temporizadores en memoria. Los
checklists son SIEMPRE en memoria (se pierden al reiniciar) y las respuestas
lo dicen."""
from __future__ import annotations

import datetime as dt
import re

SKILL = {
    "name": "Coach / Secretario",
    "description": "Briefing diario con empujón de coach, objetivos desglosados en pasos, "
                   "checklists vivos, recordatorios escalonados (semana antes, 2 días antes "
                   "y día D) y replanificación cuando surge un imprevisto",
    "patterns": {
        # OJO con el orden alfabético del router: coach va ANTES que
        # google_workspace, memory_graph y tasks_board. Por eso aquí NO se cazan
        # «qué tengo hoy» (agenda de Google), «recuerda que...» (memoria) ni
        # «organiza mis tareas» (tablero). Anclas propias: hoy+toca/hacer,
        # objetivo, checklist, recuérdame/avísame, imprevisto, spec.
        "weekly": r"revisi[oó]n\s+semanal|balance\s+de\s+(?:la\s+)?semana"
                  r"|c[oó]mo\s+(?:fue|ha\s+ido)\s+la\s+semana|resumen\s+de\s+la\s+semana",
        "briefing": r"qu[eé] (?:me toca|tengo que hacer|toca) hoy|briefing"
                    r"|plan (?:del d[ií]a|de hoy|para hoy)|resumen del d[ií]a"
                    r"|c[oó]mo viene (?:el d[ií]a|hoy)|arrancamos el d[ií]a",
        # El lookahead cede a la skill de instagram los objetivos que hablan de
        # ella («en instagram mi objetivo es vender mi curso»). Solo se excluye
        # lo que otra skill sabe atender: tiktok o youtube seguirían aquí.
        "new_goal": r"^(?![\s\S]*\b(?:instagram|insta|reels?)\b)"
                    r"[\s\S]*?(?:nuevo objetivo|objetivo nuevo|mi objetivo es|me propongo"
                    r"|quiero (?:conseguir|lograr|alcanzar))[:\s]+(?P<goal>.+)",
        "goals": r"(?:mis|ver|lista de?|cu[aá]les son (?:mis|los)|mu[eé]strame (?:mis|los)"
                 r"|ens[eé][ñn]ame (?:mis|los)|c[oó]mo van (?:mis|los)"
                 r"|estado de (?:mis|los)) objetivos|objetivos activos",
        "checklists": r"(?:mis|ver|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|lista(?:me)?|dame|"
                      r"qu[eé]|cu[aá]ntos|cu[aá]les\s+son\s+mis)\s+(?:son\s+)?(?:mis\s+|los\s+)?"
                      r"checklists?\b|checklists?\s+(?:activos|pendientes)",
        "new_checklist": r"(?:crea(?:me)?|cr[eé]ame|hazme|prep[aá]rame|arma) (?:un |una )?"
                         r"(?:checklist|lista de (?:control|comprobaci[oó]n)) ?"
                         r"(?P<rec>semanal|mensual|diari[oa])?\s*(?:de |para )?(?P<name>.+)",
        "add_item": r"(?:a[ñn][aá]de(?:me)?|apunta|mete|suma)\s+(?:al|en el)\s+checklist:?\s+(?P<item>.+)",
        # «recuérdame» exige el clítico -me: «recuerda que...» es de memory_graph.
        # El conector admite «para/el/el día» o directamente «mañana» (lookahead).
        "remind": r"(?:recu[eé]rdame|av[ií]same de(?: que)?|no me dejes olvidar(?:me de)?"
                  r"|ponme un aviso (?:de|para))\s+(?P<what>.+?)\s+"
                  r"(?:el d[ií]a|para el|para|el|(?=pasado ma[ñn]ana|ma[ñn]ana))\s*(?P<when>.+)",
        "reorganize": r"(?:me ha surgido|ha surgido|nos ha surgido) (?:un imprevisto|algo"
                      r"|un problema|un marr[oó]n)|reorganiza|replanifica",
        "coaching": r"estoy (?:agobiad[oa]|perdid[oa]|saturad[oa]|estresad[oa]|desbordad[oa]"
                    r"|quemad[oa]|bloquead[oa])|no me da la vida|no llego|no doy abasto"
                    r"|me siento superad[oa]",
        "spec": r"(?:planifica el proyecto|crea una spec (?:de|para)"
                r"|hazme una spec (?:de|para)|spec[:,])\s*(?P<proj>.+)",
    },
}

# Checklists en RAM si no hay DB (persistidos también en la nota diaria)
_local_checklists: dict[str, list] = {}
_last_checklist: str | None = None

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}
DIAS = {"lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3,
        "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6}


def _parse_date(raw: str) -> dt.datetime | None:
    raw = raw.strip().lower().rstrip(".?¿")
    today = dt.date.today()
    m = re.match(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", raw)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        try:
            date = dt.date(y, mo, d)
            if date < today:
                date = dt.date(y + 1, mo, d)
            return dt.datetime.combine(date, dt.time(9, 0), tzinfo=dt.timezone.utc)
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)", raw)
    if m and m.group(2) in MESES:
        d, mo = int(m.group(1)), MESES[m.group(2)]
        date = dt.date(today.year, mo, d)
        if date < today:
            date = dt.date(today.year + 1, mo, d)
        return dt.datetime.combine(date, dt.time(9, 0), tzinfo=dt.timezone.utc)
    for name, wd in DIAS.items():
        if name in raw:
            delta = (wd - today.weekday()) % 7 or 7
            return dt.datetime.combine(today + dt.timedelta(days=delta),
                                       dt.time(9, 0), tzinfo=dt.timezone.utc)
    if "pasado mañana" in raw or "pasado manana" in raw:
        return dt.datetime.combine(today + dt.timedelta(days=2),
                                   dt.time(9, 0), tzinfo=dt.timezone.utc)
    if "mañana" in raw or "manana" in raw:
        return dt.datetime.combine(today + dt.timedelta(days=1),
                                   dt.time(9, 0), tzinfo=dt.timezone.utc)
    if "mes" in raw:
        return dt.datetime.combine(today + dt.timedelta(days=30),
                                   dt.time(9, 0), tzinfo=dt.timezone.utc)
    return None


async def _llm(prompt: str) -> str:
    from backend.core.llm import ask_llm
    reply, _ = await ask_llm(prompt)
    return reply


async def handle(intent: str, text: str, match, ctx) -> dict:
    global _last_checklist
    pg, graph = ctx["pg"], ctx["graph"]
    op = ctx["settings"].get("operator_name")

    if intent == "weekly":
        from backend.core.review import build_weekly_review
        import asyncio as _a
        return {"reply": await _a.to_thread(build_weekly_review)}

    if intent == "briefing":
        # v19: el parte completo lo arma el módulo central (clima + tablero +
        # hermes + titulares); aquí se añade lo propio del coach: objetivos y
        # checklists. Si el módulo fallara, briefing clásico de respaldo.
        try:
            from backend.core.briefing import build_briefing
            parts = [await build_briefing()]
        except Exception:
            parts = [f"Buenos días, {op}. Plan de hoy ({dt.date.today():%d/%m}):"]
        goals = pg.goals() if pg.online else []
        if goals:
            parts.append("🎯 Objetivos: " + " · ".join(
                f"{g['title']} ({g['hechos']}/{g['total']} pasos)" for g in goals[:4]))
        if _local_checklists:
            for name, items in list(_local_checklists.items())[:2]:
                pend = [i for i in items if not i["done"]]
                parts.append(f"☑ Checklist «{name}»: {len(pend)} pendientes")
        return {"reply": "\n".join(parts)}

    if intent == "new_goal":
        goal = match.group("goal").strip().rstrip(".")
        plan = await _llm(
            f"Desglosa el objetivo «{goal}» en 5-7 pasos pequeños, concretos y accionables, "
            "como haría un coach de productividad experto. SOLO la lista numerada, "
            "una línea por paso, sin introducción.")
        steps = [re.sub(r"^\s*\d+[.)]\s*", "", l).strip()
                 for l in plan.splitlines() if l.strip()][:7]
        if not steps:
            steps = ["Definir el resultado exacto", "Investigar referencias",
                     "Primer borrador / prototipo", "Revisar y ajustar", "Ejecutar"]
        gid = pg.save_goal(goal, steps) if pg.online else None
        graph.write_note(f"objetivo {goal[:40]}",
                         f"Objetivo: {goal}\n\nPasos:\n" +
                         "\n".join(f"- [ ] {s}" for s in steps) +
                         "\n\nEnlaces: [[objetivos]]")
        stored = f" (guardado en DB #{gid})" if gid else " (guardado en el grafo)"
        return {"reply": f"Objetivo registrado{stored}. Así lo desgranamos:\n" +
                         "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)) +
                         "\n\nEmpieza HOY por el paso 1. Mañana te preguntaré cómo va."}

    if intent == "goals":
        goals = pg.goals() if pg.online else []
        if not goals:
            return {"reply": "Cero objetivos activos — y un coach sin objetivos es un coach "
                             "aburrido. Di «nuevo objetivo: ...» y te lo desgrano en pasos "
                             "(si la DB no responde, levanta el Docker de memoria)."}
        lines = [f"• #{g['id']} {g['title']} — {g['hechos']}/{g['total']} pasos" for g in goals]
        return {"reply": "Objetivos activos:\n" + "\n".join(lines) +
                         "\n\nElige uno y dale al siguiente paso hoy. Constancia > intensidad."}

    if intent == "new_checklist":
        name = match.group("name").strip()
        rec = match.group("rec") or "puntual"
        _local_checklists[name] = []
        _last_checklist = name
        graph.append_daily(f"Checklist creado: **{name}** ({rec})", section="Checklists")
        return {"reply": f"Checklist «{name}» ({rec}) creado. Añade items con «añade al "
                         "checklist ...» y míralo con «mis checklists». ⚠ Los items viven "
                         "en memoria y se pierden al reiniciar nexus; en la nota diaria "
                         "queda constancia de que lo creaste. Si quieres algo que no se "
                         "borre, dime «crea la tarea ...» y va al tablero."}

    if intent == "add_item":
        item = match.group("item").strip()
        if not _local_checklists:
            _local_checklists["general"] = []
            _last_checklist = "general"
        name = _last_checklist or next(iter(_local_checklists))
        _local_checklists[name].append({"label": item, "done": False})
        return {"reply": f"Añadido a «{name}»: {item} "
                         f"({len(_local_checklists[name])} items)."}

    if intent == "checklists":
        if not _local_checklists:
            return {"reply": "No tengo ningún checklist abierto. Crea uno con «hazme un "
                             "checklist de la mudanza». (Los checklists viven en memoria "
                             "hasta que reinicies nexus; para algo permanente, «crea la "
                             "tarea ...» y va al tablero.)"}
        bloques = []
        for nombre, items in _local_checklists.items():
            pend = [i for i in items if not i["done"]]
            cuerpo = "\n".join(f"    {'☑' if i['done'] else '☐'} {i['label']}"
                               for i in items) or "    (vacío)"
            bloques.append(f"  ☑ «{nombre}» — {len(pend)}/{len(items)} pendientes\n{cuerpo}")
        return {"reply": f"Checklists abiertos ({len(_local_checklists)}):\n"
                         + "\n".join(bloques)}

    if intent == "remind":
        what = match.group("what").strip()
        when = _parse_date(match.group("when"))
        if not when:
            return {"reply": f"No he entendido la fecha «{match.group('when')}». "
                             "Prueba: «mañana», «el viernes», «el 25/07» o «el 3 de agosto»."}
        if pg.online:
            created = pg.add_reminder(what, when)
            n = len(created)
            return {"reply": f"Anotado: «{what}» para el {when:%d/%m}. "
                             f"Te avisaré {n} veces (semana antes, 2 días antes y el día D). "
                             "No dejaré que se te pase."}
        from backend.core.scheduler import timers
        timers.append({"at": when.replace(tzinfo=None), "label": f"Recordatorio: {what}"})
        return {"reply": f"Anotado «{what}» para el {when:%d/%m}. ⚠ Ahora mismo vive en "
                         "memoria local (se pierde al reiniciar): levanta el Docker de "
                         "memoria y tendrás los 3 avisos escalonados persistentes."}

    if intent == "reorganize":
        plan = await _llm(
            f"Soy {op}. Me ha surgido un imprevisto: «{text}». Reorganiza mi día como un "
            "secretario ejecutivo: qué pospongo, qué mantengo, qué delego. Máximo 5 líneas.")
        graph.append_daily(f"Imprevisto: {text} → replanificado", section="Registro")
        return {"reply": f"Replanificando sobre la marcha:\n{plan}"}

    if intent == "spec":
        # PROJECT MANAGER: spec interna (diseño → propuesta → tareas → validaciones)
        # SIEMPRE revisada por el abogado del diablo antes de darse por buena.
        proj = match.group("proj").strip().rstrip(".")
        spec = await _llm(
            f"Como project manager senior, crea una SPEC interna para: «{proj}». "
            "Usa la base de conocimiento que tengas del operador. Estructura EXACTA:\n"
            "## Diseño\n(contexto, alcance, qué NO incluye)\n"
            "## Propuesta\n(enfoque elegido y por qué, alternativas descartadas)\n"
            "## Tareas\n(lista numerada de 5-8 tareas concretas y ordenadas)\n"
            "## Validaciones\n(cómo sabremos que cada fase está bien: criterios medibles)")
        # Revisión crítica automática
        import importlib.util
        from pathlib import Path as _P
        da_path = _P(__file__).resolve().parents[1] / "devils_advocate" / "skill.py"
        review = ""
        try:
            sp = importlib.util.spec_from_file_location("da", da_path)
            da = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(da)
            review = await da.critique(f"Spec del proyecto «{proj}»:\n{spec[:2500]}")
        except Exception:
            pass
        # Guardar spec + crear tareas en el tablero
        import re as _re
        from backend.core.config import DATA_DIR
        safe = _re.sub(r"[^\w\- ]", "", proj)[:40].strip() or "proyecto"
        out = DATA_DIR / "specs" / f"{safe}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# SPEC: {proj}\n\n{spec}\n\n---\n\n"
                       f"## Revisión del abogado del diablo\n\n{review}\n",
                       encoding="utf-8")
        from backend.core import board
        n_tasks = 0
        for line in spec.splitlines():
            m = _re.match(r"^\s*\d+[.)]\s*(.+)", line)
            if m and n_tasks < 8:
                board.add_task(m.group(1).strip()[:120], tag=safe)
                n_tasks += 1
        graph.write_note(f"spec {safe}", f"Spec de {proj} — ver data/specs/{out.name}\n\n"
                                         "Enlaces: [[proyectos]]")
        return {"reply": f"Spec de «{proj}» creada y revisada por el abogado del diablo "
                         f"(data/specs/{out.name}). He metido {n_tasks} tareas en el tablero "
                         "como pendientes.\n\n--- RESUMEN CRÍTICO ---\n" +
                         (review[:600] if review else "(revisión no disponible)")}

    if intent == "coaching":
        return {"reply": (
            f"Respira, {op}. Vamos a bajarlo a tierra: dime las 3 cosas que más te pesan "
            "ahora mismo y las metemos en un checklist. Regla de oro: solo UNA es para hoy; "
            "las otras dos tienen fecha y aviso, así tu cabeza las puede soltar. "
            "No estás desorganizado: solo te falta un sistema — y para eso estoy yo.")}

    return {"reply": "Esa orden de coach no la tengo. Prueba: «qué me toca hoy», "
                     "«nuevo objetivo: ...», «mis checklists», «recuérdame X el viernes» "
                     "o «estoy agobiado» — para eso estoy."}
