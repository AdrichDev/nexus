# -*- coding: utf-8 -*-
"""QUÉ ESTÁN CREANDO — anatomía del contenido de una cuenta.

Esto es lo que de verdad sirve para decidir qué grabar: no cuántos seguidores
tiene alguien, sino CÓMO construye lo que publica y qué le funciona a él.

Todo sale de datos públicos que da la API oficial: el caption, el formato, la
fecha y las cifras de cada publicación. Nada de comentarios ajenos, que no se
pueden leer, ni de métricas privadas, que no se exponen.

Tres reglas de método, las mismas que en el resto de la casa:

  1. **Mediana, no media.** Un viral dispara la media y hace parecer que un
     formato funciona cuando lo que pasó es que sonó la flauta una vez.
  2. **Nada se concluye con una publicación.** Cada patrón sale con su n, y por
     debajo del mínimo se dice «pocos datos» en vez de sentar cátedra.
  3. **Todo comparado consigo mismo.** Que un reel tenga 20.000 reproducciones
     no dice nada; que tenga 3 veces la mediana DE ESA CUENTA lo dice todo.

Determinista: mismo conjunto de publicaciones, mismas conclusiones.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter

N_MINIMO = 3          # por debajo de esto no se concluye nada


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s#]", " ", t)


def _mediana(vals) -> float:
    v = [x for x in vals if isinstance(x, (int, float))]
    return round(statistics.median(v), 1) if v else 0.0


def _rendimiento(m: dict):
    """La cifra con la que se mide una publicación: reproducciones si las hay,
    y si no me gusta. Mezclar las dos en una misma comparación no vale."""
    v = m.get("view_count")
    return v if isinstance(v, (int, float)) else (m.get("like_count") or 0)


# ══════════════════════════════════════════════════════════════════════════════
#  1. EL GANCHO — la primera línea, que es donde se gana o se pierde
# ══════════════════════════════════════════════════════════════════════════════
# Un pie de Instagram se lee truncado: se ve la primera línea y «... más». Así
# que la primera línea ES el gancho, y su forma se puede clasificar sin modelo.
_TIPOS = [
    ("pregunta", re.compile(
        r"\?|^\s*(?:que|qu[eé]|c[oó]mo|como|por qu[eé]|cu[aá]l|cu[aá]nto|sab[ií]as|"
        r"y si|te ha pasado|what|how|why)\b", re.IGNORECASE),
     "Abre con una pregunta: obliga a contestarse mentalmente antes de deslizar."),
    ("cifra", re.compile(r"(?<!\w)\d{1,4}(?!\w)", re.IGNORECASE),
     "Lleva un número: promete algo contable y acotado."),
    ("negacion", re.compile(
        r"\b(no |nunca|jam[aá]s|deja de|para de|evita|el error|los errores|"
        r"stop |don't|never)\b", re.IGNORECASE),
     "Empieza negando: rompe una creencia y por eso frena el dedo."),
    ("promesa", re.compile(
        r"\b(el truco|el secreto|la clave|la forma|as[ií] es como|te ensen|"
        r"te enseñ|aprende|en \d+ (?:minutos|dias|d[ií]as|segundos))\b", re.IGNORECASE),
     "Promete un resultado concreto: dice qué te llevas si te quedas."),
    ("contraste", re.compile(
        r"\b(antes y despu[eé]s|en vez de|frente a|\bvs\b|versus|la diferencia)\b",
        re.IGNORECASE),
     "Enfrenta dos cosas: la comparación se entiende sola."),
    ("historia", re.compile(
        r"^\s*(?:cuando|hace \d|el d[ií]a que|llevo|me pas[oó]|un cliente|ayer)\b",
        re.IGNORECASE),
     "Arranca contando algo que pasó: se sigue por curiosidad, no por interés."),
    ("orden", re.compile(
        r"^\s*(?:mira|escucha|apunta|guarda|prueba|haz|deja|coge|abre|para|ven|"
        r"toma|fíjate|fijate)\b", re.IGNORECASE),
     "Empieza mandando: da una instrucción directa desde la primera palabra."),
]


def gancho(caption: str) -> dict:
    """La primera línea del pie, diseccionada."""
    primera = ""
    for linea in (caption or "").splitlines():
        if linea.strip():
            primera = linea.strip()
            break
    if not primera:
        return {"texto": "", "tipos": [], "palabras": 0, "caracteres": 0,
                "mayusculas": False, "emoji": False}
    sin_tags = re.sub(r"#\w+", "", primera).strip()
    tipos = [nombre for nombre, rx, _ in _TIPOS if rx.search(sin_tags)]
    letras = [c for c in sin_tags if c.isalpha()]
    return {
        "texto": sin_tags[:120],
        "tipos": tipos or ["llano"],
        "palabras": len(sin_tags.split()),
        "caracteres": len(sin_tags),
        "mayusculas": bool(letras) and sum(c.isupper() for c in letras) / len(letras) > 0.4,
        "emoji": bool(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", primera)),
    }


_EXPLICA = {n: t for n, _, t in _TIPOS}
_EXPLICA["llano"] = "Entra directo, sin recurso: solo funciona si el tema ya interesa."


def patrones_gancho(medios: list[dict], minimo: int = N_MINIMO) -> dict:
    """Qué tipo de gancho usa, y cuál le funciona MEJOR A ÉL."""
    por_tipo: dict[str, list] = {}
    longitudes = []
    for m in medios:
        g = gancho(m.get("caption") or "")
        if not g["texto"]:
            continue
        longitudes.append(g["palabras"])
        for t in g["tipos"]:
            por_tipo.setdefault(t, []).append(_rendimiento(m))
    filas = []
    for t, vals in por_tipo.items():
        filas.append({"tipo": t, "n": len(vals), "rendimiento": _mediana(vals),
                      "que_es": _EXPLICA.get(t, ""),
                      "concluyente": len(vals) >= minimo})
    filas.sort(key=lambda d: (-d["concluyente"], -d["rendimiento"]))
    solidas = [f for f in filas if f["concluyente"]]
    # Sin NINGUNA cifra de rendimiento no se puede decir qué gancho funciona
    # mejor: todos valdrían cero y ganaría el primero por orden alfabético. Salió
    # al probar el motor con pies sacados del buscador, sin métricas detrás.
    hay_cifras = any(f["rendimiento"] for f in filas)
    return {
        "filas": filas,
        "mejor": solidas[0]["tipo"] if (solidas and hay_cifras) else None,
        "palabras_mediana": _mediana(longitudes),
        "nota": ("" if (solidas and hay_cifras) else
                 ("No hay cifras de rendimiento de estas publicaciones, así que se "
                  "puede ver QUÉ ganchos usa pero no cuál le funciona mejor."
                  if not hay_cifras else
                  f"Con menos de {minimo} publicaciones por tipo no se puede decir "
                  f"qué gancho le funciona mejor: son coincidencias, no patrones.")),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  2. EL PIE ENTERO — longitud, hashtags y llamadas a la acción
# ══════════════════════════════════════════════════════════════════════════════
_CTA = re.compile(
    r"\b(comenta|escribe|mándame|mandame|escríbeme|escribeme|link en bio|"
    r"enlace en bio|gu[aá]rdalo|guarda este|comparte|s[ií]gueme|sigueme|"
    r"suscr[ií]bete|apúntate|apuntate|reserva|comment|dm me|link in bio)\b",
    re.IGNORECASE)


def anatomia_caption(medios: list[dict]) -> dict:
    """Cómo escribe: cuánto, con cuántos hashtags y si pide algo."""
    largos, tags, con_cta, lineas = [], [], 0, []
    for m in medios:
        cap = m.get("caption") or ""
        largos.append(len(cap))
        tags.append(len(re.findall(r"#\w+", cap)))
        lineas.append(len([x for x in cap.splitlines() if x.strip()]))
        if _CTA.search(cap):
            con_cta += 1
    n = len(medios) or 1
    return {
        "caracteres_mediana": _mediana(largos),
        "hashtags_mediana": _mediana(tags),
        "lineas_mediana": _mediana(lineas),
        "con_llamada_a_accion": con_cta,
        "pct_con_llamada": round(con_cta / n * 100, 1),
        "lectura": ("Pide algo en casi todas: es una cuenta que trabaja para "
                    "convertir, no solo para gustar."
                    if con_cta / n >= 0.5 else
                    "Casi nunca pide nada: publica para alcance, no para captar."),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  3. EL RITMO — cuándo publica y si le sale a cuenta
# ══════════════════════════════════════════════════════════════════════════════
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _fecha(ts: str):
    from datetime import datetime
    try:
        return datetime.strptime((ts or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def ritmo(medios: list[dict], minimo: int = N_MINIMO) -> dict:
    """Cada cuánto publica, qué día, y qué día le funciona."""
    fechas, por_dia, por_franja = [], {}, {}
    for m in medios:
        f = _fecha(m.get("timestamp"))
        if not f:
            continue
        fechas.append(f)
        por_dia.setdefault(_DIAS[f.weekday()], []).append(_rendimiento(m))
        franja = ("madrugada" if f.hour < 7 else "mañana" if f.hour < 13
                  else "tarde" if f.hour < 20 else "noche")
        por_franja.setdefault(franja, []).append(_rendimiento(m))
    if not fechas:
        return {"hay": False, "nota": "Las publicaciones no traen fecha utilizable."}
    fechas.sort()
    dias = max(1.0, (fechas[-1] - fechas[0]).total_seconds() / 86400)
    dias_tabla = [{"dia": d, "n": len(v), "rendimiento": _mediana(v),
                   "concluyente": len(v) >= minimo}
                  for d, v in por_dia.items()]
    dias_tabla.sort(key=lambda x: (-x["concluyente"], -x["rendimiento"]))
    solidos = [d for d in dias_tabla if d["concluyente"]]
    return {
        "hay": True,
        "por_semana": round(len(fechas) / dias * 7, 1),
        "dias": dias_tabla,
        "franjas": sorted(
            [{"franja": k, "n": len(v), "rendimiento": _mediana(v)}
             for k, v in por_franja.items()], key=lambda x: -x["rendimiento"]),
        "mejor_dia": solidos[0]["dia"] if solidos else None,
        "desde": fechas[0].strftime("%Y-%m-%d"),
        "hasta": fechas[-1].strftime("%Y-%m-%d"),
        "nota": ("" if solidos else
                 f"Hacen falta al menos {minimo} publicaciones en un mismo día de "
                 f"la semana para decir que ese día le funciona."),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  4. LOS OUTLIERS — lo que se le ha salido de su propia norma
# ══════════════════════════════════════════════════════════════════════════════
# Aquí está el oro. Una publicación con 3 veces la mediana DE ESA CUENTA hizo
# algo distinto, y ese algo se puede mirar: qué gancho usó, qué formato, de qué
# hablaba. Es la diferencia entre «le funciona el vídeo» y «le funciona ESTO».
def outliers(medios: list[dict], multiplicador: float = 2.0) -> dict:
    vals = [_rendimiento(m) for m in medios]
    base = _mediana(vals)
    if not base:
        return {"hay": False, "base": 0, "lista": [],
                "nota": "Sin cifras de rendimiento no hay con qué comparar."}
    lista = []
    for m in medios:
        r = _rendimiento(m)
        mult = round(r / base, 2) if base else 0
        if mult >= multiplicador:
            g = gancho(m.get("caption") or "")
            lista.append({
                "multiplicador": mult, "rendimiento": r,
                "unidad": ("reproducciones" if isinstance(m.get("view_count"), (int, float))
                           else "me gusta"),
                "me_gusta": m.get("like_count") or 0,
                "comentarios": m.get("comments_count") or 0,
                "formato": (m.get("media_product_type") or m.get("media_type") or ""),
                "gancho": g["texto"], "tipos_de_gancho": g["tipos"],
                "cuando": (m.get("timestamp") or "")[:10],
                "enlace": m.get("permalink", ""),
            })
    lista.sort(key=lambda d: -d["multiplicador"])
    comun = Counter(t for x in lista for t in x["tipos_de_gancho"])
    return {
        "hay": bool(lista),
        "base": base,
        "umbral": multiplicador,
        "lista": lista[:8],
        "que_comparten": [{"tipo": t, "veces": n} for t, n in comun.most_common(3)],
        "nota": (f"«Outlier» = al menos {multiplicador}× la mediana de esta misma "
                 f"cuenta ({base:g}), no de tu sector. Compararse con uno mismo es "
                 "lo único que aísla qué hizo distinto ese día."
                 if lista else
                 f"Ninguna publicación llega a {multiplicador}× su propia mediana: "
                 "es una cuenta regular, sin picos que estudiar."),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  5. LOS ÁNGULOS — de qué habla, agrupado
# ══════════════════════════════════════════════════════════════════════════════
_VACIAS = {"para", "como", "esto", "eso", "con", "por", "una", "uno", "los", "las",
           "del", "que", "mas", "muy", "todo", "cuando", "donde", "porque", "pero",
           "sin", "sobre", "entre", "hasta", "desde", "cada", "este", "esta", "hay",
           "the", "and", "you", "your", "for", "with", "this", "that", "from"}


def angulos(medios: list[dict], minimo: int = 2) -> list[dict]:
    """Los temas que repite, con lo que le rinde cada uno."""
    docs = []
    for m in medios:
        toks = {w for w in _norm(m.get("caption") or "").split()
                if len(w) > 4 and w not in _VACIAS and not w.isdigit()}
        if toks:
            docs.append((toks, m))
    frec = Counter(w for toks, _ in docs for w in toks)
    temas = [w for w, n in frec.most_common(12) if n >= minimo]
    salida = []
    for t in temas:
        suyos = [m for toks, m in docs if t in toks]
        salida.append({
            "tema": t, "n": len(suyos),
            "rendimiento": _mediana([_rendimiento(m) for m in suyos]),
            "ejemplo": " ".join((suyos[0].get("caption") or "").split())[:90],
        })
    salida.sort(key=lambda d: -d["rendimiento"])
    return salida[:8]


# ══════════════════════════════════════════════════════════════════════════════
#  6. TODO JUNTO
# ══════════════════════════════════════════════════════════════════════════════
def radiografia(perfil_ajeno: dict, medios: list[dict]) -> dict:
    """La ficha completa de qué está creando una cuenta."""
    con_vistas = sum(1 for m in medios if isinstance(m.get("view_count"), (int, float)))
    return {
        "usuario": perfil_ajeno.get("usuario", ""),
        # Con qué se está midiendo el rendimiento en TODA esta ficha. Sin decirlo,
        # un número suelto al lado de «pregunta» no significa nada.
        "unidad": ("reproducciones" if con_vistas >= len(medios) / 2 else "me gusta"),
        "desde": min([(m.get("timestamp") or "")[:10] for m in medios] or [""]),
        "hasta": max([(m.get("timestamp") or "")[:10] for m in medios] or [""]),
        "publicaciones": len(medios),
        "suficiente": len(medios) >= N_MINIMO,
        "gancho": patrones_gancho(medios),
        "caption": anatomia_caption(medios),
        "ritmo": ritmo(medios),
        "outliers": outliers(medios),
        "angulos": angulos(medios),
        "aviso": ("" if len(medios) >= N_MINIMO else
                  f"Solo hay {len(medios)} publicación(es): no da para sacar "
                  "patrones. Baja más publicaciones de esa cuenta."),
    }


def radiografia_md(r: dict) -> str:
    """La radiografía en Markdown (norma de la casa: los informes son .md)."""
    p = [f"## Qué está creando @{r['usuario']}", "",
         f"Sobre {r['publicaciones']} publicaciones.", ""]
    if r["aviso"]:
        p += [f"_{r['aviso']}_", ""]
    g = r["gancho"]
    p += ["### Cómo engancha", ""]
    if g["mejor"]:
        p += [f"Lo que mejor le funciona: **{g['mejor']}** — {_EXPLICA.get(g['mejor'], '')}", ""]
    p += ["| Tipo de gancho | Cuántas | Rendimiento | Qué es |", "|---|---|---|---|"]
    for f in g["filas"]:
        p.append(f"| {f['tipo']} | {f['n']}{'' if f['concluyente'] else ' ⚠'} | "
                 f"{f['rendimiento']:g} | {f['que_es']} |")
    p += ["", f"Sus ganchos tienen {g['palabras_mediana']:g} palabras de mediana.", ""]
    if g["nota"]:
        p += [f"_{g['nota']}_", ""]

    c = r["caption"]
    p += ["### Cómo escribe", "",
          f"- {c['caracteres_mediana']:g} caracteres y {c['lineas_mediana']:g} líneas de mediana",
          f"- {c['hashtags_mediana']:g} hashtags por publicación",
          f"- Pide algo en {c['con_llamada_a_accion']} de {r['publicaciones']} "
          f"({c['pct_con_llamada']} %) — {c['lectura']}", ""]

    rm = r["ritmo"]
    if rm.get("hay"):
        p += ["### Cuándo publica", "",
              f"- {rm['por_semana']:g} publicaciones por semana ({rm['desde']} → {rm['hasta']})"]
        if rm["mejor_dia"]:
            p.append(f"- El día que mejor le sale: **{rm['mejor_dia']}**")
        if rm["franjas"]:
            p.append(f"- Franja con mejor rendimiento: {rm['franjas'][0]['franja']}")
        if rm["nota"]:
            p.append(f"- _{rm['nota']}_")
        p += [""]

    o = r["outliers"]
    p += ["### Lo que se le ha salido de la norma", "", f"_{o['nota']}_", ""]
    for x in o.get("lista", []):
        p.append(f"- **{x['multiplicador']}×** · {x['cuando']} · {x['formato']} — "
                 f"«{x['gancho']}»")
    if o.get("que_comparten"):
        p += ["", "Lo que comparten: "
              + ", ".join(f"{x['tipo']} ({x['veces']})" for x in o["que_comparten"]), ""]

    if r["angulos"]:
        p += ["### De qué habla", "", "| Tema | Veces | Rendimiento |", "|---|---|---|"]
        p += [f"| {a['tema']} | {a['n']} | {a['rendimiento']:g} |" for a in r["angulos"]]
        p += [""]
    return "\n".join(p)
