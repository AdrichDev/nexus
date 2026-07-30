"""Minion Herramientas — hora, alarmas, notas, clima, red y matemáticas SymPy."""
from __future__ import annotations

import datetime as dt
import platform
import re
import subprocess

import httpx

SKILL = {
    "name": "Herramientas",
    "description": ("Hora y fecha, temporizadores y alarmas por voz, notas a la diaria, "
                    "ping de red y matemáticas SymPy (deriva, integra, resuelve)"),
    # Orden del dict: específico arriba, amplio abajo ('calc' es el más amplio).
    "patterns": {
        "time": r"qu[eé] hora (es|tenemos)|dime la hora|dame la hora|qu[eé] (d[ií]a|fecha) es",
        "timer": r"(?:temporizador|cuenta\s+atr[aá]s)\s*(?:de\s+)?(?P<n>\d+)\s*(?P<unit>segundos?|minutos?|horas?)"
                 r"|av[ií]sa(?:me)?\s+(?:en|dentro\s+de)\s+(?P<n2>\d+)\s*(?P<unit2>segundos?|minutos?|horas?)",
        "alarm": r"(?:alarma|despi[eé]rtame|despertador)\s*(?:a\s+las?|para\s+las?)?\s*"
                 r"(?P<h>\d{1,2})(?:[:.h](?P<m>\d{2}))?",
        "note": r"\bap[uú]nta(?:me)?\s+(que\s+)?(?P<body>.+)",
        "weather": r"(qu[eé] tiempo|clima).*(en\s+(?P<city>[\wáéíóúñ ]+))?$",
        "ping": r"haz ping a\s+(?P<host>\S+)|estado de (la )?red"
                r"|(hay|tenemos|funciona|va)\s+(el\s+)?internet\b|prueba\s+la\s+conexi[oó]n",
        "derive": r"(?:deriva(?:me|r)?|(?:cu[aá]l\s+es\s+)?la\s+derivada\s+de)\s+(?P<expr>.+)",
        "integrate": r"(?:integra(?:me|l)?(?:\s+de)?|(?:cu[aá]l\s+es\s+)?la\s+integral\s+de)\s+(?P<expr>.+)",
        "solve": r"(?:resuelve(?:me)?|despeja)\s+(?P<expr>.+)",
        "calc": r"cu[aá]nto (es|vale|da)\s+(?P<expr>.+)|^\s*(?P<expr2>ra[ií]z (cuadrada )?de\s+.+)"
                r"|calc[uú]la(?:me)?\s+(?P<expr3>.+)",
    },
}

# Números dichos en palabras (la voz transcribe "dos", no "2")
_NUM_WORDS = {
    "cero": "0", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
    "once": "11", "doce": "12", "quince": "15", "veinte": "20", "treinta": "30",
    "cuarenta": "40", "cincuenta": "50", "sesenta": "60", "setenta": "70",
    "ochenta": "80", "noventa": "90", "cien": "100", "mil": "1000",
}


# ── ¿ES ESTO UNA EXPRESIÓN MATEMÁTICA DE VERDAD? ─────────────────────────────
# Lista BLANCA, no negra: se enumera lo que SÍ vale y se rechaza todo lo demás.
# Una lista negra de palabras peligrosas siempre se puede rodear; una lista
# blanca de «dígitos, x, paréntesis y estas 15 funciones» no.
_FUNCIONES_OK = {
    "sqrt", "cbrt", "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
    "tanh", "log", "ln", "exp", "abs", "floor", "ceiling", "factorial", "gcd",
    "lcm", "mod", "root", "pi", "e", "x", "y", "n", "oo", "inf", "deg", "rad",
}
# Solo estos caracteres. Sin comillas (mata los literales de texto), sin
# guion bajo (mata __import__ y cualquier atributo interno), sin corchetes,
# llaves, dos puntos, comas, punto y coma, arroba ni barra invertida.
_CARACTERES_OK = re.compile(r"^[0-9a-z+\-*/().^ =<>!%\t]*$")
_IDENTIFICADOR = re.compile(r"[a-z]+")


def _expr_matematica(txt: str) -> bool:
    """True solo si `txt` es una expresión matemática inofensiva.

    Se ejecuta ANTES de que sympy vea el texto. `sympify()` evalúa código Python,
    así que esta función es la única barrera entre el chat y un `eval()`.
    """
    t = (txt or "").strip().lower()
    if not t or len(t) > 200:
        return False
    if not _CARACTERES_OK.match(t):
        return False                       # hay algo que no pinta nada aquí
    if "_" in t or "'" in t or '"' in t:
        return False                       # (redundante, pero explícito)
    for nombre in set(_IDENTIFICADOR.findall(t)):
        if nombre not in _FUNCIONES_OK:
            return False                   # cualquier nombre desconocido: fuera
    return True


def _es2math(raw: str) -> str:
    """Traduce matemáticas dichas en español natural a sintaxis SymPy.
    «x cuadrado» → x**2 · «dos por tres» no (números en cifra) · «raíz de 16» → sqrt(16)
    Imprescindible para la VOZ: whisper transcribe 'x cuadrado', no 'x**2'."""
    t = f" {raw.lower().strip()} ".replace("^", "**").replace(",", ".")
    subs = [
        (r"\bal cuadrado\b", "**2"), (r"\bcuadrado\b", "**2"),
        (r"\bal cubo\b", "**3"), (r"\bcubo\b", "**3"),
        (r"\belevado a la\b", "**"), (r"\belevado a\b", "**"),
        (r"\bra[ií]z (cuadrada )?de\b", "sqrt"),
        (r"\bseno de\b", "sin"), (r"\bcoseno de\b", "cos"), (r"\btangente de\b", "tan"),
        (r"\blogaritmo de\b", "log"),
        (r"\bpor\b", "*"), (r"\bentre\b", "/"), (r"\bdividido (por |entre )?", "/"),
        (r"\bm[aá]s\b", "+"), (r"\bmenos\b", "-"),
        (r"\bequis\b", "x"), (r"\bpi\b", "pi"),
    ]
    for pat, rep in subs:
        t = re.sub(pat, rep, t)
    for word, num in _NUM_WORDS.items():
        t = re.sub(rf"\b{word}\b", num, t)
    # sqrt 16 → sqrt(16) · sin x → sin(x)
    t = re.sub(r"\b(sqrt|sin|cos|tan|log)\s+([\w.]+)", r"\1(\2)", t)
    return t.strip()


async def handle(intent: str, text: str, match, ctx) -> dict:
    now = dt.datetime.now()

    if intent == "time":
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        return {"reply": f"🕐 Son las {now:%H:%M:%S} del {dias[now.weekday()]} "
                         f"{now.day}/{now.month}/{now.year}."}

    if intent == "timer":
        gd = match.groupdict()
        n = int(gd.get("n") or gd.get("n2"))
        unit = gd.get("unit") or gd.get("unit2")
        secs = n * (3600 if unit.startswith("hora") else 60 if unit.startswith("min") else 1)
        from backend.core.scheduler import timers
        timers.append({"at": now + dt.timedelta(seconds=secs),
                       "label": f"Temporizador de {n} {unit} cumplido"})
        return {"reply": f"⏱ Temporizador de {n} {unit} armado; te aviso por el HUD. "
                         "Si prefieres hora fija, di «alarma a las <hh:mm>»."}

    if intent == "alarm":
        h, m = int(match.group("h")), int(match.group("m") or 0)
        if h > 23 or m > 59:
            return {"reply": f"⚠ {h:02d}:{m:02d} no es una hora válida. "
                             "Di «alarma a las 07:30», por ejemplo."}
        at = now.replace(hour=h, minute=m, second=0)
        if at <= now:
            at += dt.timedelta(days=1)
        from backend.core.scheduler import timers
        timers.append({"at": at, "label": f"Alarma de las {h:02d}:{m:02d}"})
        return {"reply": f"⏰ Alarma fijada a las {h:02d}:{m:02d} ({at:%d/%m}). "
                         "Te aviso por el HUD."}

    if intent == "note":
        body = match.group("body").strip()
        fname = ctx["graph"].append_daily(body, section="Notas")
        if ctx["pg"].online:
            ctx["pg"].remember(body, kind="note")
        return {"reply": f"✔ Apuntado en la nota diaria ({fname}). "
                         "Di «qué sabes de mí» si quieres repasar lo guardado."}

    if intent == "weather":
        city = (match.group("city") or "Madrid").strip().title()
        try:
            async with httpx.AsyncClient(timeout=6) as cli:
                geo = await cli.get("https://geocoding-api.open-meteo.com/v1/search",
                                    params={"name": city, "count": 1, "language": "es"})
                loc = geo.json()["results"][0]
                wx = await cli.get("https://api.open-meteo.com/v1/forecast",
                                   params={"latitude": loc["latitude"],
                                           "longitude": loc["longitude"],
                                           "current": "temperature_2m,wind_speed_10m,"
                                                      "relative_humidity_2m"})
                cur = wx.json()["current"]
            return {"reply": f"🌤 En {loc['name']}: {cur['temperature_2m']}°C, humedad "
                             f"{cur['relative_humidity_2m']}%, viento {cur['wind_speed_10m']} km/h."}
        except Exception:
            return {"reply": f"⚠ No llego a Open-Meteo para consultar {city} (parece cosa "
                             "de red). Di «estado de la red» para comprobarla y repítemelo."}

    if intent == "ping":
        host = match.group("host") or "8.8.8.8"
        flag = "-n" if platform.system() == "Windows" else "-c"
        try:
            out = subprocess.run(["ping", flag, "2", host], capture_output=True,
                                 text=True, timeout=8)
            times = re.findall(r"[t]ie?m[epo]+[=<]\s*(\d+)", out.stdout) or \
                re.findall(r"time[=<]([\d.]+)", out.stdout)
            if out.returncode == 0:
                avg = f" (~{times[-1]} ms)" if times else ""
                return {"reply": f"✔ Enlace con {host} operativo{avg}."}
            return {"reply": f"✖ {host} no responde al ping. Revisa cable/wifi o el router; "
                             "luego di «estado de la red» y lo compruebo otra vez."}
        except Exception:
            return {"reply": f"⚠ No he podido lanzar el ping a {host} desde este equipo "
                             "(¿comando ping no disponible o sin permisos?). Pruébalo a mano "
                             f"en una terminal: `ping {host}`."}

    # ---- Matemáticas con SymPy ----
    if intent in ("derive", "integrate", "solve", "calc"):
        gd = match.groupdict()
        raw = (gd.get("expr") or gd.get("expr2") or gd.get("expr3") or "").strip().rstrip("?¿.")
        try:
            import sympy as sp
            x = sp.symbols("x")
            expr_txt = _es2math(raw)
            # ── PUERTA DE SEGURIDAD (auditoría 30/07/2026) ──────────────────
            # `sympy.sympify()` hace `eval()` por dentro. Comprobado: escribir
            # «calcula __import__('os').system('...')» EJECUTABA el comando en el
            # PC, y nexus contestaba una frase inocente como si nada. Aquí se
            # exige que lo que llega sea de verdad una expresión matemática; si
            # no lo es, no se toca sympy y contesta el modelo, igual que antes
            # con «cuánto es el IVA en España».
            if not _expr_matematica(expr_txt):
                raise ValueError("no es una expresión matemática")
            if intent == "solve" and "=" in expr_txt:
                lhs, rhs = expr_txt.split("=", 1)
                sols = sp.solve(sp.Eq(sp.sympify(lhs), sp.sympify(rhs)), x)
                return {"reply": f"🧮 Soluciones de {raw}: {', '.join(map(str, sols))}"}
            expr = sp.sympify(expr_txt)
            if intent == "derive":
                return {"reply": f"🧮 d/dx({raw}) = {sp.diff(expr, x)}"}
            if intent == "integrate":
                return {"reply": f"🧮 ∫({raw})dx = {sp.integrate(expr, x)} + C"}
            val = expr.evalf()
            pretty = int(val) if float(val).is_integer() else round(float(val), 6)
            return {"reply": f"🧮 {raw} = {pretty}"}
        except ImportError:
            return {"reply": "⚠ Me falta SymPy para las mates. Instálalo con "
                             "`pip install sympy` (en el venv de nexus) y repítemelo."}
        except Exception:
            # No es una expresión matemática parseable → que responda el LLM
            # («cuánto es el IVA en España» no es para SymPy)
            from backend.core.llm import ask_llm
            reply, _ = await ask_llm(text)
            return {"reply": reply}

    return {"reply": "No he pillado esa herramienta. Tengo: hora, «temporizador de N minutos», "
                     "«alarma a las hh:mm», «apunta que...», «haz ping a <host>» y mates "
                     "(«deriva x**3», «cuánto es 2+2»)."}
