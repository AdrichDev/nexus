"""Minion Tablero — kanban Notion-style con estados, retrasos y Eisenhower.

v23 (specs v23, TAREAS 1-3 — incidente del 25/07/2026: «limpia las tareas ya
realizadas» vació las 15 tareas del tablero y no hubo forma de recuperarlas):
  * NINGÚN borrado se ejecuta sin CONFIRMACIÓN EXPLÍCITA. Antes de borrar,
    nexus enseña cuántas y cuáles se van, y espera un «sí».
  * El ámbito se calcula con el ESTADO REAL: «las ya realizadas / hechas /
    finalizadas / listas» = SOLO las completadas. Vaciar el tablero entero
    exige decirlo con todas las letras («todas las tareas», «el tablero»).
  * Si la orden es ambigua se pregunta, y lo que queda armado es la opción
    SEGURA (solo completadas); jamás el borrado total.
  * Todo lo borrado va a la PAPELERA y se restaura con «recupera las tareas
    borradas» / «deshaz el borrado».

v74 (peticiones de Adri):
  * DIFERENCIA tareas de HACER (🛠 acción: «crear una web») de EVENTOS de
    calendario (📅 «asistir a una reunión», «mentoría») — no es lo mismo.
  * Si la tarea trae FECHA LÍMITE («para el viernes», «antes del 25/07»,
    «deadline 30/07») se guarda en la tarea y se muestra.
  * Si trae HORA («mentoría el jueves a las 18»), se guarda y se dice; los
    EVENTOS con fecha+hora se apuntan también en Google Calendar si está
    autorizado (sin bloquear si no lo está).
  * Mover acepta «mueve/pasa/cambia X a ...» con «en curso», «in progress»,
    «doing», «review»... y los atajos «me pongo/arranco con X» → EN PROGRESO.
"""
from __future__ import annotations

import datetime as dt
import re

from backend.core import board, confirm

SKILL = {
    "name": "Tablero",
    "description": "Kanban de tareas y eventos: crea con fecha límite y hora (evento 📅 vs acción 🛠, con volcado a Google Calendar), mueve de estado, avisa de retrasos y prioriza con Eisenhower",
    "patterns": {
        # NOTA: el router prueba los intents EN ESTE ORDEN. «show» va EL ÚLTIMO
        # a propósito: es muy amplio (cualquier mención a ver/consultar tareas)
        # y si fuera antes se tragaría retrasadas/organiza/borra/crea.
        # El cuerpo es OPCIONAL: «crea una tarea» a secas es la forma normal de
        # pedirlo hablando y antes no casaba con nada. Sin cuerpo el handler
        # PREGUNTA de qué va; no crea nada.
        "create": r"(?:cr[eé]a(?:me)?|a[ñn][aá]de(?:me)?|ap[uú]nta(?:me)?|an[oó]ta(?:me)?|agr[eé]ga(?:me)?|mete(?:me)?|pon(?:me)?)\s+"
                  r"(?:la\s+|una\s+|otra\s+|nueva\s+)?tarea\b\s*(?:de\s+|:\s*)?(?P<body>.*)"
                  r"|(?:ap[uú]nta(?:me)?|an[oó]ta(?:me)?|ag[eé]nda(?:me)?)\s+(?:el\s+|la\s+|una\s+|un\s+)?(?P<body2>(?:evento|reuni[oó]n|mentor[ií]a|cita|clase|sesi[oó]n)\s+.+)",
        # v23 (T13): posponer un recordatorio sin tocar la tarea.
        "snooze": r"(?:recu[eé]rdame(?:lo|la)?|av[ií]same|d[ií]melo)\s+"
                  r"(?:m[aá]s\s+tarde|luego|despu[eé]s|en\s+(?P<horas>\d{1,2})\s*(?:h|horas?))"
                  r"(?:\s+(?:lo\s+de\s+|la\s+tarea\s+)?(?P<task3>.+))?"
                  r"|(?:posp[oó]n|aplaza)\s+(?:el\s+)?(?:recordatorio|aviso)"
                  r"(?:\s+de\s+(?P<task4>.+))?"
                  r"|(?:ahora\s+no|d[eé]jame\s+en\s+paz|no\s+me\s+molestes)\s+"
                  r"(?:con\s+(?:las\s+)?tareas)?",
        # «marca la velada como realizada» no casaba con ningún patrón: se iba al
        # cerebro y allí petaba con un NoneType. Es la forma NORMAL de decirlo.
        # «da por hecha la compra» invierte el orden (verbo, estado, tarea), así
        # que va en su propia alternativa: metida en la de arriba capturaba «por»
        # como si fuera el nombre de la tarea.
        "marcar": r"(?:da|dad|d[ae]me)\s+por\s+(?P<state4>realizadas?|hechas?|completadas?|"
                  r"terminadas?|acabadas?|finalizadas?)\s+(?:la\s+|el\s+)?(?:tarea\s+)?"
                  r"(?P<task4>.+)"
                  r"|(?:marca|pon)\s+(?:la\s+|el\s+)?(?:tarea\s+)?"
                  r"(?P<task3>.+?)\s+(?:como\s+|por\s+)?"
                  r"(?P<state3>realizadas?|hechas?|completadas?|terminadas?|acabadas?|"
                  r"finalizadas?|listas?|pendientes?|en\s+progreso|en\s+curso|"
                  r"en\s+revisi[oó]n)\b",
        "move": r"(?:mueve|pasa|cambia)\s+(la tarea\s+)?(?P<task>.+?)\s+a\s+(?P<state>pendientes?|por\s+hacer|"
                r"(en )?progreso|(en )?curso|in\s*progress|doing|"
                r"(en )?revisi[oó]n|review|completadas?|hechas?|terminadas?|done)",
        "start": r"(?:me pongo|empiezo|comienzo|arranco|me lanzo)\s+con\s+(?:la\s+tarea\s+)?(?P<task2>.+)",
        "late": r"qu[eé] tareas (?:van|tengo|hay|llevo) (?:retrasadas|atrasadas|vencidas)"
                r"|tareas? (?:vencidas?|retrasadas?|atrasadas?|fuera de plazo)|voy retrasado|voy atrasado",
        "organize": r"organiza (mis )?tareas( por urgencia| por importancia)?"
                    r"|prioriza (?:mis |las )?tareas|prioriza el tablero"
                    r"|ordena (?:mis|las) tareas(?: por (?:urgencia|importancia|prioridad))?"
                    r"|matriz de eisenhower",
        # v23: RESTAURAR y PAPELERA van ANTES que cualquier borrado, para que
        # «recupera las tareas que has eliminado» no se lea como una orden de borrar.
        # La primera alternativa captura el TÍTULO para restaurar solo esa tarea;
        # sin ella «restaura la tarea X» devolvía el lote borrado entero.
        "restore": r"(?:recup[eé]ra|restaura|restit[uú]ye|rescata)(?:me)?\s+"
                   r"(?:la\s+|el\s+|mi\s+)?tareas?\s+"
                   r"(?!borradas?\b|eliminadas?\b|de\s+la\s+papelera\b)(?P<task>.+)"
                   r"|(?:recup[eé]ra|restaura|restit[uú]ye|devu[eé]lve|rescata)"
                   r"(?:me|las|los|la|lo|melas)?\b[^.\n]{0,30}"
                   r"\b(?:tareas?|papelera|borrad[ao]s?|eliminad[ao]s?)\b"
                   r"|(?:recup[eé]ra|restaura|rescata)(?:melas|las|los)\b"
                   r"|\bdeshaz\b[^.\n]{0,20}\b(?:borrado|eliminaci[oó]n|lo\s+[uú]ltimo)\b"
                   r"|\bdeshacer\s+(?:el\s+)?(?:[uú]ltimo\s+)?borrado\b"
                   r"|\bvuelve\s+a\s+poner\s+las\s+tareas\b",
        # PAPELERA: ver lo borrado (y vaciarla del todo, con confirmación extra).
        "trash": r"\bpapelera\b"
                 r"|\btareas\s+(?:eliminadas|borradas)\b"
                 r"|qu[eé]\s+(?:tareas\s+)?(?:has|hemos)\s+(?:borrado|eliminado)",
        # BORRAR todo / completadas → ANTES que el borrado por título (más específico).
        # v23: «realizadas / finalizadas / listas» también son COMPLETADAS. Ese
        # hueco fue LA causa del incidente: no casaban y caía en el borrado total.
        "clear": r"\b(b[oó]rra(?:me)?|elim[ií]na(?:me)?|elimina|qu[ií]ta(?:me)?|vac[ií]a(?:me)?|limpia(?:me)?)\b[^.\n]{0,25}\b(todas?\s+las\s+tareas|"
                 r"el\s+tablero|las\s+(?:tareas\s+)?(?:ya\s+)?(?:completadas?|hechas?|terminadas?|"
                 r"acabadas?|realizadas?|finalizadas?|listas|pendientes))\b",
        # BORRAR una tarea: acepta borra/elimina/quita/tacha/descarta pero EXIGE la palabra
        # «tarea» (si no, «borra el archivo X» caería aquí por error). El título va después.
        "delete": r"\b(?:b[oó]rra(?:me)?|elim[ií]na(?:me)?|elimina|qu[ií]ta(?:me)?|t[aá]cha(?:me)?|descarta)\b[^.\n]{0,12}\btareas?\b"
                  r"\s*(?:[:,\-]\s*|llamada\s+|titulada\s+|que\s+dice\s+|de\s+)?(?P<task>.+)",
        # VER el tablero: cualquier forma natural de pedir las tareas, no solo
        # «ver tablero» (peticion de Adri: «siempre que le diga algo de tareas
        # tiene que poder verlas»). Los casos especificos de arriba ganan porque
        # se evaluan antes; «tareas de google» tampoco cae aqui porque el skill
        # google_workspace va antes por orden alfabetico.
        "show": r"ver\s+(?:el\s+)?tablero"
                r"|c[oó]mo\s+va\s+el\s+tablero"
                r"|(?:abre|abrir)\s+el\s+tablero"
                r"|(?:ver|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dime|dame|lista|l[ií]stame|l[eé]e(?:me)?|"
                r"revisa|rep[aá]sa(?:me)?|consulta|saca(?:me)?|cu[eé]nta(?:me)?)\b[^.\n]{0,20}\btareas\b"
                r"|(?:qu[eé]|cu[aá]les|cu[aá]ntas)\b[^.\n]{0,15}\btareas\b"
                r"|\bmis\s+tareas\b"
                r"|\btareas\s+(?:pendientes|activas|abiertas|de\s+hoy|de\s+la\s+semana)\b"
                r"|c[oó]mo\s+(?:van|est[aá]n|llevo)\s+(?:mis\s+|las\s+)?tareas"
                r"|lista\s+de\s+tareas"
                r"|qu[eé]\s+tengo\s+pendiente"
                r"|^\s*tareas\s*\??\s*$",
    },
}

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}
DIAS = {"lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3,
        "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6}
STATE_LABEL = {"pendiente": "PENDIENTES", "progreso": "EN PROGRESO",
               "revision": "EN REVISIÓN", "completada": "COMPLETADAS"}

# «para el viernes» / «antes del 25/07» / «fecha límite 30 de julio» / «deadline …»
_PRE = r"(?:para|antes\s+del?|con\s+fecha\s+l[ií]mite(?:\s+de)?|fecha\s+l[ií]mite|deadline)"

# EVENTO de calendario (asistir) vs ACCIÓN (hacer): «no es lo mismo crear una web
# que asistir a una reunión» — Adri.
_EVENT_RX = re.compile(
    r"\b(reuni[oó]n|mentor[ií]a|mentor[ií]as|cita|llamada|entrevista|clase|sesi[oó]n|"
    r"evento|m[eé]dico|dentista|consulta|quedada|asistir|webinar|taller|charla|"
    r"kick-?off|demo|revisi[oó]n\s+con)\b", re.IGNORECASE)

# Lo que queda tras «crea una tarea …» cuando el usuario NO ha dicho el asunto.
# «crea una tarea nueva» dejaba body="nueva" y creaba una tarea titulada «nueva».
_SIN_ASUNTO_RX = re.compile(
    r"^(?:nueva|nuevo|otra|otro|m[aá]s|ya|porfa|por\s+favor|anda|venga)?$", re.IGNORECASE)


def _extract_due(text: str) -> tuple[str, str | None]:
    """Extrae la FECHA LÍMITE («para el viernes», «antes del 25/07», «deadline 30
    de julio») y la quita del título. Para EVENTOS acepta también «el jueves»."""
    low = text.lower()
    today = dt.date.today()
    m = re.search(_PRE + r"\s*(el\s+|ma[ñn]ana|hoy)?\s*(\d{1,2})[/-](\d{1,2})", low)
    if m:
        d, mo = int(m.group(2)), int(m.group(3))
        y = today.year if (mo, d) >= (today.month, today.day) else today.year + 1
        return re.sub(_PRE + r"\s*(el\s*)?\d{1,2}[/-]\d{1,2}", "", text, flags=re.I).strip(), \
            dt.date(y, mo, d).isoformat()
    if re.search(_PRE + r"\s+ma[ñn]ana", low) or "para mañana" in low:
        return re.sub(_PRE + r"\s+ma[ñn]ana", "", text, flags=re.I).strip(), \
            (today + dt.timedelta(days=1)).isoformat()
    if re.search(_PRE + r"\s+hoy", low):
        return re.sub(_PRE + r"\s+hoy", "", text, flags=re.I).strip(), today.isoformat()
    for name, wd in DIAS.items():
        if re.search(_PRE + rf"\s+(?:el\s+)?{name}", low):
            delta = (wd - today.weekday()) % 7 or 7
            return re.sub(_PRE + rf"\s+(?:el\s+)?{name}", "", text, flags=re.I).strip(), \
                (today + dt.timedelta(days=delta)).isoformat()
    m = re.search(_PRE + r"\s+(?:el\s+)?(\d{1,2})\s+de\s+(\w+)", low)
    if m and m.group(2) in MESES:
        d, mo = int(m.group(1)), MESES[m.group(2)]
        y = today.year if (mo, d) >= (today.month, today.day) else today.year + 1
        return re.sub(_PRE + r"\s+(?:el\s+)?\d{1,2}\s+de\s+\w+", "", text, flags=re.I).strip(), \
            dt.date(y, mo, d).isoformat()
    # EVENTOS: «mentoría el jueves a las 18» — el día va sin «para»
    for name, wd in DIAS.items():
        if re.search(rf"\bel\s+{name}\b", low):
            delta = (wd - today.weekday()) % 7 or 7
            return re.sub(rf"\bel\s+{name}\b", "", text, flags=re.I).strip(), \
                (today + dt.timedelta(days=delta)).isoformat()
    # «llamar al fontanero mañana»: el día va SOLO, sin «para» y sin «el». Va al
    # final para que «el lunes por la mañana» lo resuelva antes el bucle de días.
    # El (?<!la\s) deja fuera «de la mañana» y «por la mañana», que son la FRANJA
    # horaria, no el día de mañana.
    if re.search(r"(?<!la\s)\bma[ñn]ana\b", low):
        return re.sub(r"(?<!la\s)\bma[ñn]ana\b", "", text, flags=re.I).strip(), \
            (today + dt.timedelta(days=1)).isoformat()
    if re.search(r"\bhoy\b", low):
        return re.sub(r"\bhoy\b", "", text, flags=re.I).strip(), today.isoformat()
    return text, None


def _extract_time(text: str) -> tuple[str, str | None]:
    """Extrae la HORA («a las 18», «a la 1 y media de la tarde», «a las 9:30»)
    y la quita del título. Devuelve (texto_limpio, 'HH:MM' | None)."""
    m = re.search(r"\ba\s+las?\s+(\d{1,2})(?:[:.h](\d{2}))?"
                  r"(\s+y\s+media)?"
                  r"\s*(?:horas?\b|h\b)?"
                  r"\s*(de\s+la\s+(?:ma[ñn]ana|tarde|noche|madrugada)|am|pm)?",
                  text, re.IGNORECASE)
    if not m:
        return text, None
    h = int(m.group(1))
    mnt = int(m.group(2) or 0)
    if m.group(3) and not m.group(2):     # «y media» sin minutos explícitos
        mnt = 30
    suf = (m.group(4) or "").lower()
    if ("tarde" in suf or "noche" in suf or "pm" in suf) and h < 12:
        h += 12
    if "madrugada" in suf and h == 12:
        h = 0
    if h > 23 or mnt > 59:
        return text, None
    clean = (text[:m.start()] + " " + text[m.end():]).strip(" ,.")
    return re.sub(r"\s{2,}", " ", clean), f"{h:02d}:{mnt:02d}"


# ══════════ EVENTOS DE VARIOS DÍAS: «del miércoles al domingo» ══════════
# Un extremo del rango: día de la semana, número de día, «5 de agosto», «25/07»,
# «mañana» u «hoy». El orden de las alternativas importa: las largas primero o
# «5 de agosto» se partiría en «5».
_DIA_TOKEN = (r"(?:\d{1,2}[/-]\d{1,2}|\d{1,2}\s+de\s+\w+|\d{1,2}|"
              r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|"
              r"ma[ñn]ana|hoy)")
# Coletillas que se cuelan entre el día y el conector: «del miércoles DE ESTA
# SEMANA hasta el domingo».
_COLETILLA_DIA = (r"(?:\s+(?:de\s+esta\s+semana|de\s+la\s+semana\s+que\s+viene|"
                  r"que\s+viene|pr[oó]xim[oa]))?")
_RANGO_RX = re.compile(
    r"\b(?:del|desde\s+el|desde|entre\s+el|entre)\s+(?P<ini>" + _DIA_TOKEN + r")"
    + _COLETILLA_DIA
    + r"\s+(?:al|hasta\s+el|hasta)\s+(?P<fin>" + _DIA_TOKEN + r")"
    + _COLETILLA_DIA, re.IGNORECASE)


def _fecha_token(tok: str, today: dt.date, mes_ref: int | None = None) -> dt.date | None:
    """Convierte un extremo del rango («miércoles», «5», «5 de agosto», «25/07»,
    «mañana», «hoy») en fecha. Siempre hacia adelante: nunca devuelve pasado."""
    t = " ".join((tok or "").lower().split())
    if t == "hoy":
        return today
    if re.fullmatch(r"ma[ñn]ana", t):
        return today + dt.timedelta(days=1)
    if t in DIAS:
        return today + dt.timedelta(days=(DIAS[t] - today.weekday()) % 7 or 7)
    solo_dia = False
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"(\d{1,2})(?:\s+de\s+(\w+))?", t)
        if not m:
            return None
        d = int(m.group(1))
        if m.group(2) and m.group(2) in MESES:
            mo = MESES[m.group(2)]
        elif m.group(2):
            return None                      # «5 de esta» no es una fecha
        else:
            mo, solo_dia = mes_ref or today.month, mes_ref is None
    y = today.year
    for _ in range(13):
        try:
            f = dt.date(y, mo, d)
        except ValueError:
            return None
        if f >= today:
            return f
        if solo_dia:                         # solo el día: se busca en el mes siguiente
            mo += 1
            if mo > 12:
                mo, y = 1, y + 1
        else:                                # con mes explícito: el año que viene
            y += 1
    return None


def _extract_range(text: str) -> tuple[str, str | None, str | None]:
    """Saca un rango de VARIOS DÍAS («del miércoles al domingo», «desde el 5
    hasta el 9 de agosto») y lo quita del título. Devuelve (texto_limpio,
    inicio, fin) en ISO, o (texto, None, None) si no hay rango."""
    m = _RANGO_RX.search(text or "")
    if not m:
        return text, None, None
    today = dt.date.today()
    fin_tok = " ".join(m.group("fin").lower().split())
    # «del 5 al 9 de agosto»: el mes lo dice el segundo extremo y vale para los dos.
    mm = re.fullmatch(r"\d{1,2}\s+de\s+(\w+)", fin_tok)
    mes_ref = MESES.get(mm.group(1)) if mm else None
    ini = _fecha_token(m.group("ini"), today, mes_ref)
    fin = _fecha_token(fin_tok, today)
    if not ini or not fin:
        return text, None, None
    if fin < ini and fin_tok in DIAS:        # «del domingo al miércoles» cruza semana
        fin += dt.timedelta(days=7)
    if fin < ini:
        return text, None, None
    limpio = text[:m.start()] + " " + text[m.end():]
    return re.sub(r"\s{2,}", " ", limpio).strip(" ,."), ini.isoformat(), fin.isoformat()


# ══════════ EL TÍTULO ES EL ASUNTO, NO LA FRASE ENTERA ══════════
# Dónde se apunta no es de qué va: «como una entrada de google calendar» es el
# destino, no el título del evento.
_DESTINO_RX = re.compile(
    r"\bcomo\s+(?:una?\s+)?(?:entrada|evento|cita|apunte)\s+(?:de|en)\s+"
    r"(?:el\s+|mi\s+)?(?:google\s+)?calendari[oa]\b"
    r"|\bcomo\s+(?:una?\s+)?(?:entrada|evento|cita|apunte)\s+(?:de|en)\s+google\s+calendar\b"
    r"|\ben\s+(?:el\s+|mi\s+)?(?:google\s+)?calendari[oa]\b"
    r"|\ben\s+google\s+calendar\b"
    r"|\bcomo\s+(?:una?\s+)?(?:entrada|evento)\b"
    r"|\ben\s+(?:la\s+|mi\s+)?agenda\b", re.IGNORECASE)

# El asunto puede venir DETRÁS de las fechas: «…hasta el domingo QUE SEA Festival
# Sonorama». Lo que va después del marcador es el título entero.
_ASUNTO_RX = re.compile(
    r"\b(?:que\s+se\s+(?:llama|titula)|que\s+sea|que\s+es|y\s+es|"
    r"llamad[oa]|titulad[oa])\b\s*[:,]?\s*"
    r"|\s*:\s*", re.IGNORECASE)

# Relleno de duración: no aporta nada al título.
_DURACION_RX = re.compile(
    r"\bque\s+(?:dure|dura|durar[aá]|vaya|va)\b(?:\s+desde)?", re.IGNORECASE)

# Conectores que quedan colgando al arrancar la fecha del medio de la frase.
_COLGADOS_RX = re.compile(
    r"^(?:\s*(?:desde|hasta|del|al|de|entre|y|a)\b)+"
    r"|(?:\b(?:desde|hasta|del|al|de|entre|y|a)\s*)+$", re.IGNORECASE)

# Determinante de arranque, SOLO en minúscula: así «La Vuelta a España» conserva
# su nombre y «la reunión con Ana» se queda en «reunión con Ana».
_DETERMINANTE_RX = re.compile(r"^(?:el|la|los|las|un|una|unos|unas)\s+")


def _limpia_titulo(text: str) -> str:
    """Deja SOLO el asunto. Quita el destino («como una entrada de google
    calendar»), el relleno de duración («que dure») y los conectores que quedan
    sueltos al sacar las fechas. Si el asunto va detrás de «que sea», «que es»,
    «y es», «llamada/titulada» o «:», el título es lo que viene después."""
    t = _DESTINO_RX.sub(" ", text or "")
    m = _ASUNTO_RX.search(t)
    if m and t[m.end():].strip(" ,.:;-"):
        t = t[m.end():]
    else:
        t = _DURACION_RX.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.:;-")
    previo = None
    while previo != t:                       # el relleno se apila: «que dure desde»
        previo = t
        t = _COLGADOS_RX.sub("", t).strip(" ,.:;-")
    t = _DETERMINANTE_RX.sub("", t, count=1)
    return re.sub(r"\s{2,}", " ", t).strip(" ,.:;-")


def _maybe_gcal_event(title: str, due: str, hora: str, due_end: str = "") -> str:
    """EVENTO a Google Calendar, SOLO si ya hay token autorizado (jamás dispara
    el OAuth desde aquí). Con `due_end` el evento ABARCA todos los días del rango.
    Devuelve '' o ' + Google Calendar'."""
    try:
        import importlib.util
        from backend.core.config import SKILLS_DIR
        spec = importlib.util.spec_from_file_location(
            "gws_board", SKILLS_DIR / "google_workspace" / "skill.py")
        gws = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gws)
        if not gws.TOKEN_FILE.exists():
            return ""
        start, end, todo_el_dia = _cuerpo_evento(due, hora, due_end)
        gws._create_event(title, start, end, "Creado por nexus desde el tablero",
                          all_day=todo_el_dia)
        return " + Google Calendar"
    except Exception:
        return ""


def _cuerpo_evento(due: str, hora: str, due_end: str = "") -> tuple[str, str, bool]:
    """Fechas que se le mandan a Google: (start, end, all_day).

    Con hora, el rango arranca a esa hora y termina al acabar el último día.
    Sin hora es de día completo, y ahí Google trata `end.date` como EXCLUSIVO:
    hay que sumarle un día o el evento se queda corto y no pinta el último."""
    if hora:
        start = f"{due}T{hora}:00"
        if due_end and due_end > due:
            return start, f"{due_end}T23:59:00", False
        fin = dt.datetime.fromisoformat(start) + dt.timedelta(hours=1)
        return start, fin.isoformat(timespec="seconds"), False
    ultimo = dt.date.fromisoformat(due_end or due) + dt.timedelta(days=1)
    return due, ultimo.isoformat(), True


# ══════════ v23: ÁMBITO DE UN BORRADO MASIVO (TAREA 2) ══════════
# «ya realizadas», «hechas», «finalizadas», «listas» = COMPLETADAS. Se comprueba
# ANTES que el ámbito total: «borra todas las tareas completadas» son las
# completadas, no el tablero entero.
_SCOPE_COMPLETED_RX = re.compile(
    r"\b(?:completad[ao]s?|hech[ao]s?|terminad[ao]s?|acabad[ao]s?|realizad[ao]s?|"
    r"finalizad[ao]s?|list[ao]s|cerrad[ao]s?|done|completed)\b", re.IGNORECASE)
_SCOPE_PENDING_RX = re.compile(r"\b(?:pendientes?|por\s+hacer|sin\s+hacer|pending)\b",
                               re.IGNORECASE)
_SCOPE_PROGRESS_RX = re.compile(r"\b(?:en\s+progreso|en\s+curso|in\s*progress|doing)\b",
                                re.IGNORECASE)
_SCOPE_ALL_RX = re.compile(
    r"\btodas?\s+(?:las\s+)?tareas\b|\btodo\s+el\s+tablero\b"
    r"|\bel\s+tablero\s+(?:entero|completo)\b|\btablero\s+al\s+completo\b"
    r"|\b(?:vac[ií]a(?:me)?|limpia(?:me)?|borra(?:me)?|elimina(?:me)?)\s+(?:el\s+)?tablero\b"
    r"|\bde\s+cero\b|\bempezar\s+de\s+cero\b", re.IGNORECASE)

# El "título" que llega a `delete` es un ÁMBITO solo si NO es nada más que eso:
# «borra la tarea pendiente 2» es un TÍTULO, no «todas las pendientes».
_SCOPE_ONLY_RX = re.compile(
    r"^(?:las?\s+|los\s+|mis\s+|ya\s+|todas?\s+|todos?\s+|el\s+|tareas?\s+)*"
    r"(?:completad[ao]s?|hech[ao]s?|terminad[ao]s?|acabad[ao]s?|realizad[ao]s?|"
    r"finalizad[ao]s?|list[ao]s|cerrad[ao]s?|pendientes?|en\s+progreso|en\s+curso|"
    r"tablero|tareas?)\s*$", re.IGNORECASE)

_SCOPE_LABEL = {"completadas": "completadas", "pendientes": "pendientes",
                "progreso": "en progreso", "revision": "en revisión",
                "todas": "TODAS las tareas del tablero"}


def _scope_of(text: str) -> str | None:
    """Ámbito de un borrado masivo a partir de la orden. None = ambiguo.
    REGLA DE ORO v23: ante la duda NUNCA se devuelve 'todas'."""
    if _SCOPE_COMPLETED_RX.search(text or ""):
        return "completadas"
    if _SCOPE_ALL_RX.search(text or ""):
        return "todas"
    if _SCOPE_PENDING_RX.search(text or ""):
        return "pendientes"
    if _SCOPE_PROGRESS_RX.search(text or ""):
        return "progreso"
    return None


def _resumen_tablero() -> str:
    c = board.counts()
    trozos = [f"{c['completada']} completada(s)", f"{c['pendiente']} pendiente(s)",
              f"{c['progreso']} en progreso", f"{c['revision']} en revisión"]
    return ", ".join(p for p in trozos if not p.startswith("0 ")) or "ninguna tarea"


def _lista_afectadas(victims: list, tope: int = 8) -> str:
    lineas = [f"   • {t.get('title', '?')}" for t in victims[:tope]]
    if len(victims) > tope:
        lineas.append(f"   • …y {len(victims) - tope} más")
    return "\n".join(lineas)


def _pedir_confirmacion(ctx, texto: str, scope: str, victims: list,
                        aviso: str = "") -> dict:
    """Arma el borrado y DEVUELVE LA PREGUNTA. Aquí no se borra nada."""
    canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
    n = len(victims)
    etiqueta = _SCOPE_LABEL.get(scope, scope)
    cabecera = ("⚠️ OJO, esto vacía el tablero ENTERO.\n" if scope == "todas" else "🗑 ")
    pregunta = (
        f"{cabecera}En el tablero hay {_resumen_tablero()}.\n"
        f"Voy a borrar {n} tarea(s) — {etiqueta}:\n"
        f"{_lista_afectadas(victims)}\n"
        + (f"{aviso}\n" if aviso else "")
        + ("El resto NO lo toco. " if scope != "todas" else "")
        + "¿Lo confirmas? Responde «sí» o «no». "
        "Van a la papelera, así que podré devolvértelas con «recupera las tareas borradas»."
    )

    def _ejecutar(_scope=scope, _texto=texto, _n=n):
        borradas = board.clear_scope(_scope, reason=_texto, by="operador")
        if _scope == "todas":
            return (f"Tablero vaciado: {borradas} tarea(s) a la papelera. "
                    "Si me he pasado, dime «recupera las tareas borradas».")
        return (f"Listo: {borradas} tarea(s) {_SCOPE_LABEL.get(_scope, _scope)} a la papelera. "
                "El resto sigue intacto. Se recuperan con «recupera las tareas borradas».")

    reply = confirm.request(
        channel=canal, kind=f"borrar_tareas:{scope}", summary=pregunta,
        action=_ejecutar, request_text=texto,
        targets=[{"id": t.get("id"), "title": t.get("title"), "state": t.get("state")}
                 for t in victims],
        cancel_reply="Perfecto, no he borrado nada. El tablero sigue igual.")
    return {"reply": reply, "data": {"confirm": True, "scope": scope, "count": n}}


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "create":
        body = ""
        for g in ("body", "body2"):
            try:
                body = (match.group(g) or "").strip().rstrip(".")
            except Exception:
                body = ""
            if body:
                break
        # Sin asunto no se crea nada: se pregunta. Crear una tarea titulada
        # «nueva» es peor que no crearla.
        if _SIN_ASUNTO_RX.match(body.strip(" ,.:;¡!¿?")):
            return {"reply": "¿Tarea de qué? Dime el asunto y la apunto. Por ejemplo: "
                             "«crea una tarea de llamar al fontanero mañana a las 10» "
                             "o «crea una tarea de revisar las facturas para el viernes».",
                    "speak": True}
        prio = "media"
        if re.search(r"prioridad alta|urgente|importante", body, re.I):
            prio = "alta"
            body = re.sub(r"(con )?prioridad alta|urgente", "", body, flags=re.I).strip()
        body, hora = _extract_time(body)
        # El rango («del miércoles al domingo») se prueba ANTES que la fecha
        # suelta: si no, se quedaba solo con el último día y un festival de cinco
        # días se pintaba como un punto en el calendario.
        body, due, due_fin = _extract_range(body)
        if not due:
            body, due = _extract_due(body)
        body = _limpia_titulo(body)
        # Segundo filtro de asunto: al quitar fechas y relleno puede no quedar
        # nada («anótame la tarea como una entrada de calendar del X al Y»).
        # Se pregunta, y se dice qué fechas SÍ se han entendido para no perderlas.
        if not body or _SIN_ASUNTO_RX.match(body):
            cuando = ""
            if due and due_fin and due_fin != due:
                cuando = f" Las fechas ya las tengo: del {due} al {due_fin}."
            elif due:
                cuando = f" La fecha ya la tengo: {due}."
            return {"reply": "Me falta el asunto: no sé de qué va." + cuando
                             + " Dímelo con el nombre, por ejemplo: «crea una tarea "
                               "del miércoles al domingo que sea Festival Sonorama».",
                    "speak": True}
        kind = "evento" if (hora or due_fin or _EVENT_RX.search(text)) else "accion"
        t = board.add_task(body, due=due, priority=prio, time_at=hora or "",
                           kind=kind, due_end=due_fin or "")
        rango = f" → {due_fin}" if due_fin and due_fin != due else ""
        fecha = f" · {due}{rango}" if due else ""
        hh = f" · a las {hora}" if hora else ""
        if kind == "evento":
            import asyncio as _a
            gcal = ""
            if due and (hora or due_fin):
                gcal = await _a.to_thread(_maybe_gcal_event, t["title"], due,
                                          hora or "", due_fin or "")
            dias = ""
            if due_fin and due_fin != due:
                n = (dt.date.fromisoformat(due_fin) - dt.date.fromisoformat(due)).days + 1
                dias = f" Ocupa {n} días seguidos."
            return {"reply": f"📅 Evento apuntado: «{t['title']}»{fecha}{hh} "
                             f"(tablero{gcal}, id {t['id']}).{dias} Te lo recordaré."}
        extra = f" con fecha límite {due}{rango}" if due else ""
        return {"reply": f"🛠 Tarea creada en PENDIENTES: «{t['title']}»{extra}{hh} "
                         f"(prioridad {prio}, id {t['id']}). "
                         "Muévela con «mueve … a en progreso»."}

    if intent == "snooze":
        gd = match.groupdict() if match else {}
        horas = float(gd.get("horas") or 2)
        objetivo = (gd.get("task3") or gd.get("task4") or "").strip(" .,;:¡!¿?")
        if objetivo:
            t = board.snooze(objetivo, horas)
            if not t:
                return {"reply": f"No encuentro la tarea «{objetivo}». Di «ver tablero» "
                                 "para ver los títulos exactos."}
            return {"reply": f"Vale: no te doy la lata con «{t['title']}» hasta dentro de "
                             f"{horas:g} h. Sigue en el tablero, tranquilo."}
        n = board.snooze_all(horas)
        return {"reply": (f"Hecho: silencio los recordatorios de {n} tarea(s) durante "
                          f"{horas:g} h. Las tareas siguen ahí, solo dejo de recordártelas."
                          if n else "No hay tareas activas que posponer.")}

    if intent in ("move", "start", "marcar"):
        # Defensivo a propósito: este handler lo puede invocar el cerebro con un
        # match que no traiga los grupos, y antes reventaba con un NoneType en la
        # cara del usuario en vez de decir qué le falta.
        def _g(nombre):
            try:
                return (match.group(nombre) or "").strip() if match else ""
            except Exception:
                return ""
        if intent == "start":
            q, state_raw = _g("task2"), "progreso"
        elif intent == "marcar":
            q = _g("task3") or _g("task4")
            state_raw = _g("state3") or _g("state4")
        else:
            q, state_raw = _g("task"), _g("state")
        if not q or not state_raw:
            return {"reply": "No he entendido qué tarea ni a qué estado. Dímelo así: "
                             "«marca la compra como hecha» o «mueve la compra a hechas». "
                             "Con «ver tablero» te enseño los títulos exactos."}
        t = board.move_task(q, state_raw)
        if not t:
            return {"reply": "No encuentro esa tarea (o el estado no existe). "
                             "Di «ver tablero» para ver los títulos exactos."}
        done = t["state"] == "completada"
        cheer = " 🎉 Buen trabajo." if done else ""
        return {"reply": f"«{t['title']}» → {STATE_LABEL[t['state']]}.{cheer}"}

    if intent == "show":
        b = board.board()
        lines = []
        for state, label in STATE_LABEL.items():
            items = b.get(state, [])
            lines.append(f"▸ {label} ({len(items)})")
            for t in items[:6]:
                icon = "📅" if t.get("kind") == "evento" else "🛠"
                due = f" · {t['due']}" if t.get("due") else ""
                hh = f" a las {t['time']}" if t.get("time") else ""
                pr = " · ⚡alta" if t.get("priority") == "alta" else ""
                lines.append(f"   {icon} {t['title']}{due}{hh}{pr}")
        total = sum(len(v) for v in b.values())
        if not total:
            return {"reply": "Tablero vacío. Crea la primera: «crea la tarea ... para el viernes»."}
        return {"reply": "\n".join(lines), "data": b}

    if intent == "late":
        late, soon = board.overdue()
        if not late and not soon:
            return {"reply": "Vas al día: nada vencido ni a punto de vencer. Así me gusta."}
        lines = []
        for t in late:
            hh = f" a las {t['time']}" if t.get("time") else ""
            lines.append(f"🔴 VENCIDA: «{t['title']}» (venció {t['due']}{hh}, está en {t['state']})")
        for t in soon:
            hh = f" a las {t['time']}" if t.get("time") else ""
            lines.append(f"🟡 A PUNTO: «{t['title']}» vence {t['due']}{hh}")
        lines.append("Mi consejo: coge la vencida más antigua y dale 25 minutos AHORA.")
        return {"reply": "\n".join(lines)}

    if intent == "organize":
        quad = board.eisenhower()
        labels = {"hacer_ya": "🔥 HACER YA (urgente + importante)",
                  "planificar": "📅 PLANIFICAR (importante, no urgente)",
                  "delegar": "🤝 DELEGAR/RÁPIDO (urgente, no importante)",
                  "descartar": "🗑 REVISAR SI APORTAN (ni urgente ni importante)"}
        lines = ["Matriz urgencia × importancia:"]
        for key, label in labels.items():
            items = quad[key]
            if items:
                lines.append(f"{label}:")
                lines += [f"   • {t['title']}" + (f" (vence {t['due']})" if t.get("due") else "")
                          for t in items[:5]]
        if len(lines) == 1:
            return {"reply": "No hay tareas activas que organizar. Tablero limpio."}
        lines.append("Empieza por la primera de HACER YA. Solo esa. Luego hablamos.")
        return {"reply": "\n".join(lines)}

    # ══════════ v23 TAREA 3: papelera y restauración ══════════
    if intent == "trash":
        low = text.lower()
        if re.search(r"\b(vac[ií]a|vaciar|borra|elimina|purga|destruye)\b[^.\n]{0,20}"
                     r"\bpapelera\b", low):
            canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
            pend = board.trash(limit=500)
            if not pend:
                return {"reply": "La papelera ya está vacía."}

            def _purgar():
                n = board.purge_trash()
                return (f"Papelera vaciada: {n} tarjeta(s) destruida(s) para siempre. "
                        "Esas ya no vuelven.")
            return {"reply": confirm.request(
                channel=canal, kind="purgar_papelera",
                summary=(f"⚠️ Vaciar la papelera es DEFINITIVO: se destruyen {len(pend)} "
                         "tarjeta(s) y ya no se podrán restaurar. ¿Lo confirmas? «sí» o «no»."),
                action=_purgar, request_text=text,
                targets=[{"id": t.get("id"), "title": t.get("title")} for t in pend],
                cancel_reply="Vale, dejo la papelera como está.")}
        items = board.trash(limit=15)
        if not items:
            return {"reply": "La papelera está vacía: no he borrado ninguna tarea."}
        lineas = [f"🗑 Papelera ({len(items)} de las últimas borradas):"]
        for t in items:
            lineas.append(f"   • {t.get('title', '?')} · estaba en "
                          f"{t.get('previousStatus', '?')} · borrada {t.get('deletedAt', '?')[:16]}")
        lineas.append("Para devolverlas: «recupera las tareas borradas».")
        return {"reply": "\n".join(lineas), "data": {"trash": items}}

    if intent == "restore":
        q = ""
        try:
            q = (match.group("task") or "").strip() if match else ""
        except Exception:
            q = ""
        restored = board.restore(query=q)
        if not restored:
            if not board.trash(limit=1):
                return {"reply": "No hay nada en la papelera que recuperar. "
                                 "Si borraste algo antes de la v23, ya no hay copia: "
                                 "desde ahora TODO borrado pasa por la papelera."}
            return {"reply": f"En la papelera no encuentro nada que case con «{q}». "
                             "Di «ver la papelera» para verlo todo."}
        lineas = [f"♻️ Recuperadas {len(restored)} tarea(s), cada una a su columna de antes:"]
        lineas += [f"   • {t['title']} → {STATE_LABEL.get(t['state'], t['state'])}"
                   for t in restored[:10]]
        return {"reply": "\n".join(lineas), "data": {"restored": restored}}

    # ══════════ v23 TAREAS 1 y 2: borrado masivo CON confirmación ══════════
    if intent == "clear":
        scope = _scope_of(text)
        aviso = ""
        if scope is None:
            # Ambiguo («limpia el tablero de tareas», «borra tareas»): NO se
            # asume el borrado total. Se arma la opción segura y se pregunta.
            scope = "completadas"
            aviso = ("(No me has dicho cuáles, así que asumo SOLO las completadas. "
                     "Si querías vaciarlo entero, dímelo con esas palabras: "
                     "«borra TODAS las tareas».)")
        victims = board.select(scope)
        if not victims:
            c = board.counts()
            if not c["total"]:
                return {"reply": "El tablero ya está vacío, no hay nada que borrar."}
            return {"reply": f"No hay ninguna tarea {_SCOPE_LABEL.get(scope, scope)} que borrar. "
                             f"Ahora mismo tienes {_resumen_tablero()}."}
        return _pedir_confirmacion(ctx, text, scope, victims, aviso)

    if intent == "delete":
        try:
            q = (match.group("task") or "").strip(" .,;:¡!¿?").strip() if match else ""
        except Exception:
            q = ""
        if not q:
            return {"reply": "¿Qué tarea quieres que borre? Dime el título (o «ver tablero» "
                             "para verlos). No borro nada a ciegas."}
        # Si el título que me dan es en realidad un ÁMBITO («borra las tareas
        # completadas»), se trata como borrado masivo, no como título literal.
        # Ojo: solo si el texto es SOLO el ámbito («las completadas»); «pendiente 2»
        # es un título de tarea, no la columna de pendientes.
        scope = _scope_of(q) if _SCOPE_ONLY_RX.match(q) else None
        if scope:
            victims = board.select(scope)
            if not victims:
                return {"reply": f"No hay ninguna tarea {_SCOPE_LABEL.get(scope, scope)} que borrar. "
                                 f"Ahora mismo tienes {_resumen_tablero()}."}
            return _pedir_confirmacion(ctx, text, scope, victims)
        victims = board.find_all(q)
        if not victims:
            return {"reply": f"No encuentro ninguna tarea que se llame «{q}». "
                             "Di «ver tablero» para ver los títulos exactos, o bórrala "
                             "con el botón 🗑 de la tarjeta."}
        canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
        ids = [t["id"] for t in victims]

        def _ejecutar(_ids=tuple(ids), _texto=text, _q=q):
            vivos = [t for t in board._load() if t["id"] in _ids]
            res = board.soft_delete(vivos, reason=_texto, by="operador",
                                    action="delete_task")
            if res["count"] > 1:
                return (f"Borradas {res['count']} tareas que coincidían con «{_q}» "
                        "(duplicados incluidos). Están en la papelera.")
            return (f"Tarea «{vivos[0]['title']}» a la papelera. "
                    "La devuelvo con «recupera las tareas borradas»." if vivos
                    else "Ya no quedaba nada que borrar.")

        pregunta = (f"🗑 Voy a borrar {len(victims)} tarea(s) que casan con «{q}»:\n"
                    f"{_lista_afectadas(victims)}\n"
                    "¿Lo confirmas? «sí» o «no». Van a la papelera, se pueden recuperar.")
        return {"reply": confirm.request(
            channel=canal, kind="borrar_tareas:titulo", summary=pregunta,
            action=_ejecutar, request_text=text,
            targets=[{"id": t["id"], "title": t.get("title"), "state": t.get("state")}
                     for t in victims],
            cancel_reply="Vale, no borro nada."),
            "data": {"confirm": True, "count": len(victims)}}

    return {"reply": "Esa orden del tablero no la tengo. Prueba: «crea la tarea ... para el "
                     "viernes», «mueve ... a en progreso», «qué tareas van retrasadas», "
                     "«ver tablero», «borra las tareas completadas» (te pido confirmación) "
                     "o «recupera las tareas borradas»."}
