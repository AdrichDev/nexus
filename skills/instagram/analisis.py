# -*- coding: utf-8 -*-
"""
MOTOR DE ANÁLISIS DE REELS — la parte que NO puede improvisar un modelo.

Aquí se calculan los números. Todo lo de este archivo es determinista: con el
mismo bundle salen exactamente las mismas cifras, siempre. El modelo entra
DESPUÉS, y solo para lo cualitativo (por qué un lead está caliente, qué reel
grabar). Un modelo no debe contar comentarios: los cuenta el código.

Tres reglas que aquí son ley, porque son las que suele saltarse un informe
generado a ojo:

  1. LA ARITMÉTICA CUADRA. Todo comentario cae en UNA de cuatro cestas —autor,
     CTA, sustantivo o sin clasificar— y la suma es SIEMPRE el total. Si los
     subtotales no llegan al total, el informe lo dice en vez de disimular: unos
     cientos de leads y unas decenas de opiniones que no suman lo declarado son
     comentarios sin explicar, no un detalle.
  2. EL HUECO DE LEADS SE REPORTA. Si más gente disparó el gancho que mensajes
     se enviaron, esa diferencia no se pierde en el resumen: se cuenta y se
     nombra, porque es dinero sin atender.
  3. EL SENTIMIENTO LLEVA SU MUESTRA. Un «93 %» a secas sobre unas pocas decenas
     de comentarios engaña. Cada porcentaje sale con su n y su banda de
     confianza (Wilson).

Y el informe va completo: retención de vídeo, alcance por origen, conversión de
negocio y comparación con reels anteriores. Cuando la Graph API no dé un dato,
se dice QUE NO ESTÁ y por qué — nunca se rellena con una estimación disfrazada
de medición.
"""
from __future__ import annotations

import csv
import io
import math
import re
import statistics
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  0. LOS UMBRALES — fuera del código
# ══════════════════════════════════════════════════════════════════════════════
# Todo número con el que nexus DECIDE algo («¿esto es un engagement alto?»,
# «¿este racimo de comentarios es una campaña?») vive en config/umbrales.json.
# Aquí solo quedan los valores de reserva, que son EXACTAMENTE los que había
# escritos a mano antes: si el archivo no existe o le falta una clave, el
# comportamiento es el de siempre. Nadie se queda sin informe por un JSON mal
# puesto.
#
# Además, cada cuenta puede pisar cualquier valor desde su perfil: una cuenta de
# recetas y una de consultoría no tienen el mismo listón de guardados.
_POR_DEFECTO = {
    "lecturas": {"guardados_pct_reach_fuerte": 3.0,
                 "interacciones_pct_reach_alto": 10.0},
    "sentimiento": {"n_minimo_fiable": 30, "n_sin_aviso": 100, "confianza_z": 1.96},
    "gancho": {"min_personas": 5, "min_pct": 2.0, "max_palabras": 3,
               "max_caracteres": 24, "min_pct_mayusculas": 25.0},
    "erratas": {"sin_margen_hasta": 4, "margen_1_hasta": 6, "margen_2_hasta": 9,
                "margen_maximo": 3},
    "dudas": {"solape_minimo": 0.4, "veces_para_ser_recurrente": 2},
    "comentarios": {"min_palabras_sustantivo": 2, "min_caracteres_sustantivo": 8},
    "cola_editorial": {"peso_veces": 2, "peso_personas": 1,
                       "peso_intencion_compra": 3, "peso_objecion": 2},
}

_cache_archivo = None


def ruta_umbrales() -> Path:
    """config/umbrales.json, respetando NEXUS_CONFIG_DIR si está puesto."""
    try:
        from backend.core.comun.config import CONFIG_DIR          # type: ignore
        return Path(CONFIG_DIR) / "umbrales.json"
    except Exception:
        return Path(__file__).resolve().parents[2] / "config" / "umbrales.json"


def _fusiona(base: dict, encima) -> dict:
    """Mezcla por bloques: lo que no pises, lo heredas."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
    for k, v in (encima or {}).items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update({a: b for a, b in v.items() if not str(a).startswith("_")})
        else:
            out[k] = v
    return out


# NO HAY «recarga_umbrales()» AQUÍ, Y ES A PROPÓSITO (02/08/2026).
# Vaciaba `_cache_archivo` para releer config/umbrales.json sin reiniciar. No la
# llamaba nadie — y aun así alguien copió el patrón a backend/core/procedencia.py,
# donde tampoco lo llamaba nadie (ver la nota de allí). Una función muerta
# replicada es peor que una sola, así que se van las dos. nexus relee los umbrales
# al arrancar, y tras tocar una skill HAY QUE REINICIAR de todos modos.
def cargar_umbrales(extra=None) -> dict:
    """Los umbrales vigentes: reserva + archivo + lo que pise esta cuenta."""
    global _cache_archivo
    if _cache_archivo is None:
        leido = {}
        try:
            f = ruta_umbrales()
            if f.is_file():
                import json as _json
                leido = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            leido = {}                      # un JSON roto no tumba el análisis
        _cache_archivo = _fusiona(_POR_DEFECTO, leido)
    u = _fusiona(_cache_archivo, extra) if extra else dict(_cache_archivo)
    u["_resuelto"] = True
    return u


def _u(umbrales) -> dict:
    """Resuelve una vez y no vuelve a fusionar en cada comentario."""
    if isinstance(umbrales, dict) and umbrales.get("_resuelto"):
        return umbrales
    return cargar_umbrales(umbrales)

# ══════════════════════════════════════════════════════════════════════════════
#  1. TOLERANCIA A ERRORES DE TECLEO EN LA PALABRA-CTA
# ══════════════════════════════════════════════════════════════════════════════
# La gente escribe la palabra-imán a toda prisa desde el móvil, y le baila:
# «RECETA» acaba en «receta», «rezeta», «recet», «re ceta». Si solo se busca
# la palabra exacta, esos leads se pierden — y son leads de verdad. La
# palabra en sí la pone cada campaña; nexus no supone ninguna.


def _normaliza(texto: str) -> str:
    """minúsculas, sin tildes y sin signos: para comparar peras con peras."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", t)


def distancia(a: str, b: str) -> int:
    """Distancia de edición (Levenshtein). Cuántos retoques hay de «a» a «b»."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1,
                              previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def _margen(palabra: str, umbrales=None) -> int:
    """Cuántos errores se le perdonan a una palabra según lo larga que sea."""
    e = _u(umbrales)["erratas"]
    n = len(palabra)
    if n <= e["sin_margen_hasta"]:
        return 0            # «guia» no puede tolerar erratas: chocaría con todo
    if n <= e["margen_1_hasta"]:
        return 1
    if n <= e["margen_2_hasta"]:
        return 2
    return int(e["margen_maximo"])


# Palabras de relleno de una keyword de campaña: «QUIERO MI GUÍA» se comenta
# casi siempre como «GUÍA» a secas, así que la parte distintiva también cuenta.
_RELLENO = {"quiero", "quiere", "dame", "damelo", "envia", "enviame", "manda",
            "mandame", "mandamelo", "mi", "me", "el", "la", "los", "las", "un",
            "una", "por", "favor", "porfa", "want", "my", "send", "the", "info"}


def formas_de(keyword: str) -> list[str]:
    """La keyword y sus formas comentables, de más larga a más corta.

    De «QUIERO MI GUÍA» salen «quieromiguia» (la frase entera) y «guia» (lo
    distintivo), que es como la escribe casi todo el mundo. La palabra la pone
    cada campaña: aquí no hay ninguna dada por supuesta."""
    n = _normaliza(keyword).strip()
    if not n:
        return []
    formas = [n.replace(" ", "")]
    for palabra in n.split():
        if len(palabra) >= 5 and palabra not in _RELLENO and palabra not in formas:
            formas.append(palabra)
    return formas


def casa_cta(texto: str, keywords, umbrales=None) -> tuple[bool, str, str]:
    """¿Este comentario dispara alguna palabra-CTA?

    Devuelve (sí/no, keyword que casó, cómo lo escribió el usuario). Prueba la
    frase entera y su parte distintiva, comparando palabra a palabra —y también
    pares seguidos, para las palabras partidas en dos— con margen de erratas.
    El margen depende de lo larga que sea la palabra: una keyword corta no
    tolera ninguna, porque se comería medio diccionario."""
    u = _u(umbrales)
    t = _normaliza(texto)
    palabras = t.split()
    pares = [f"{palabras[i]}{palabras[i+1]}" for i in range(len(palabras) - 1)]
    sin_espacios = t.replace(" ", "")
    for kw in keywords:
        for k in formas_de(kw):
            if k in sin_espacios:
                return True, kw, k
            m = _margen(k, u)
            if not m:
                continue
            for cand in palabras + pares:
                if abs(len(cand) - len(k)) <= m and distancia(cand, k) <= m:
                    return True, kw, cand
    return False, "", ""


# ══════════════════════════════════════════════════════════════════════════════
#  1bis. DESCUBRIR LA PALABRA-CTA SOLO, SEA LA QUE SEA
# ══════════════════════════════════════════════════════════════════════════════
# nexus NO da por supuesta ninguna palabra. Cada campaña usa la suya («GUÍA»,
# «PLAN», «RECETA», «LO QUIERO»…) y cambia de un reel al siguiente, así que
# hardcodear cualquiera sería inútil.
#
# La señal fiable NO está en el pie del reel: está en los COMENTARIOS. Cuando
# hay un gancho, aparece un racimo de comentarios cortos casi idénticos escritos
# por mucha gente distinta. Eso es un patrón que se detecta sin saber de
# antemano qué palabra es. El pie sirve para confirmar, no para adivinar.
#
# (Antes esto cogía cualquier palabra en MAYÚSCULAS del pie. Con un pie tipo
#  «NUEVO vídeo GRATIS sobre IA» habría inventado tres campañas inexistentes y
#  contado como leads a quien escribiera «gratis».)
_REACCIONES = {
    "top", "crack", "genial", "grande", "brutal", "increible", "espectacular",
    "gracias", "graciasss", "bravo", "wow", "guau", "fuego", "maquina", "maestro",
    "bien", "muy bueno", "buenisimo", "excelente", "perfecto", "me encanta",
    "enhorabuena", "felicidades", "vamos", "eso es", "gran video", "gran reel",
    "nice", "amazing", "great", "love it", "awesome", "thanks", "cool",
}


def detecta_cta(flat: list[dict], caption: str = "",
                min_personas: int | None = None, min_pct: float | None = None,
                umbrales=None) -> list[dict]:
    """Encuentra la(s) palabra-gancho de ESTE reel mirando los comentarios.

    Devuelve [{palabra, personas, pct, en_el_pie}] ordenado por uso. Vacío si no
    hay ningún racimo claro — que es la respuesta correcta cuando el reel no
    llevaba gancho, en vez de inventarse uno.
    """
    g = _u(umbrales)["gancho"]
    min_personas = g["min_personas"] if min_personas is None else min_personas
    min_pct = g["min_pct"] if min_pct is None else min_pct
    max_pal, max_car = g["max_palabras"], g["max_caracteres"]
    min_grito = g["min_pct_mayusculas"] / 100.0
    audiencia = [c for c in flat if not c.get("is_from_owner")]
    if not audiencia:
        return []
    porforma: dict[str, set] = {}
    gritado: dict[str, int] = {}
    for c in audiencia:
        texto = (c.get("text") or "").strip()
        limpio = _normaliza(texto).strip()
        # Un gancho se comenta CORTO — una palabra o dos, tres a lo sumo. Con un
        # margen más ancho, una frase natural que mucha gente repite («vaya nivel
        # el montaje») se colaba como si fuera una campaña.
        if not limpio or len(limpio) > max_car or len(limpio.split()) > max_pal:
            continue
        if limpio in _REACCIONES or len(limpio) < 3:
            continue
        porforma.setdefault(limpio, set()).add((c.get("username") or "").lower())
        # Un gancho SE GRITA: la gente lo copia tal cual del pie, en mayúsculas.
        letras = [x for x in texto if x.isalpha()]
        if letras and sum(1 for x in letras if x.isupper()) / len(letras) >= 0.8:
            gritado[limpio] = gritado.get(limpio, 0) + 1
    cap = _normaliza(caption)
    total = len(audiencia)
    salida = []
    for forma, usuarios in porforma.items():
        n = len(usuarios)
        pct = n / total * 100
        en_pie = forma in cap
        # Hace falta MASA y, además, una de dos pruebas: o lo pide el pie, o una
        # parte de la gente lo escribió en mayúsculas. Sin eso, sería adivinar.
        if n >= min_personas and pct >= min_pct and (en_pie or gritado.get(forma, 0) / n >= min_grito):
            salida.append({"palabra": forma.upper(), "personas": n,
                           "pct": round(pct, 1), "en_el_pie": en_pie})
    # el que además sale en el pie del reel es el más probable: primero
    salida.sort(key=lambda d: (-d["en_el_pie"], -d["personas"]))
    return salida[:3]


# El verbo va sin distinguir mayusculas ("Comenta" / "comenta"); la palabra-iman
# SI: es lo que separa un gancho de una palabra normal del pie.
_PIDE = (r"(?i:\b(?:comenta|comentad|coment[a\u00e1]me|escribe|escribid|"
         r"escr[i\u00ed]be(?:me|nos)?|pon|poned|ponme|responde|respondan|"
         r"manda|mandad|m[a\u00e1]nda(?:me|nos)|env[i\u00ed]a|env[i\u00ed]ame|"
         r"deja|d[i\u00ed]jame|dime|di|comment|write|send|type|drop)\b)")
# una palabra del gancho: MAYUSCULAS o digitos, 2+ (el total exige 3+)
_TOKEN = r"[A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00dc\u00d10-9]{2,}"
_PIE_RX = re.compile(
    _PIDE + r"\s+(?:la\s+palabra\s+|el\s+c[o\u00f3]digo\s+|me\s+|the\s+word\s+)?"
    + "[\u00ab\"'\u201c]?(" + _TOKEN + r"(?:\s+" + _TOKEN + r"){0,2})")


def cta_del_pie(caption: str) -> list[str]:
    """La palabra que el propio pie del reel pide comentar.

    SOLO el patron explicito ("comenta X", "escribeme X"). Nada de coger
    mayusculas sueltas: un pie normal lleva media docena -marcas, "NUEVO",
    "PARTE 2"- y ninguna es un gancho. Cogerlas todas era inventarse campanas.
    """
    if not caption:
        return []
    out: list[str] = []
    for m in _PIE_RX.finditer(caption):
        cand = " ".join(m.group(1).split())
        # dos letras nunca son un gancho: "DM", "YA", "SI"
        if len(cand.replace(" ", "")) < 3:
            continue
        if cand not in out:
            out.append(cand)
    return out[:3]


# ══════════════════════════════════════════════════════════════════════════════
#  2. CLASIFICACIÓN: CUATRO CESTAS Y LA SUMA CUADRA
# ══════════════════════════════════════════════════════════════════════════════
# Una pregunta se reconoce por el signo, por empezar con interrogativo... o por
# llevar un interrogativo CON TILDE en medio: en español la tilde diacrítica es
# justo lo que separa «donde vivo» de «de dónde lo has sacado». Sin esta tercera
# vía, media pregunta escrita del tirón se contaba como simple opinión y su duda
# no llegaba nunca a la cola editorial.
_PREGUNTA = re.compile(
    r"\?|^\s*(?:que|qué|cual|cuál|como|cómo|cuando|cuándo|donde|dónde|cuanto|cuánto|"
    r"por que|por qué|se puede|sirve|funciona|hay|tienes|puedo|podria|podría|"
    r"what|how|where|when|which|does|can|is it)\b"
    r"|\b(?:dónde|cómo|cuánto|cuánta|cuántos|cuántas|cuándo|cuál|quién|qué)\b",
    re.IGNORECASE)

_COMPRA = re.compile(
    r"\b(precio|cuanto cuesta|cuánto cuesta|comprar|compro|lo quiero|me interesa|"
    r"contratar|presupuesto|factura|pagar|tarjeta|invertir|rentab|clientes?|"
    r"para mi (?:negocio|empresa)|empresa|facturaci[oó]n|roi|monetiz)\b", re.IGNORECASE)

_ODIO = re.compile(
    r"\b(estafa|timo|fraude|mentira|basura|asco|idiota|tonto|imb[eé]cil|est[uú]pido|"
    r"pat[eé]tico|verg[uü]enza|payaso|scam|fake)\b", re.IGNORECASE)


def clasificar(flat: list[dict], keywords: list[str], umbrales=None) -> dict:
    """Reparte TODOS los comentarios en cuatro cestas que suman el total.

    - autor: los escribió el dueño de la cuenta (responder no es opinar).
    - cta: contienen la palabra-imán (o una errata de ella). SON los leads.
    - sustantivo: dicen algo — una pregunta, una opinión, una objeción.
    - sin_clasificar: emojis sueltos, «🔥», «top», un nombre etiquetado. Ni
      opinan ni son leads. NO se esconden: se cuentan y se reportan.
    """
    u = _u(umbrales)
    minpal = u["comentarios"]["min_palabras_sustantivo"]
    mincar = u["comentarios"]["min_caracteres_sustantivo"]
    cestas = {"autor": [], "cta": [], "sustantivo": [], "sin_clasificar": []}
    for c in flat:
        texto = (c.get("text") or "").strip()
        if c.get("is_from_owner"):
            cestas["autor"].append(c)
            continue
        casa, kw, escrito = casa_cta(texto, keywords, u)
        if casa or c.get("is_trigger"):
            d = dict(c)
            d["keyword"] = kw or c.get("matched_trigger") or ""
            d["escrito_como"] = escrito or d["keyword"]
            # «errata» = lo escribió de una forma que NO es ninguna de las
            # legítimas. Escribir «GUÍA» cuando la campaña es «QUIERO MI GUÍA»
            # es correcto, no una errata: es como comenta casi todo el
            # mundo. Sin esta distinción, el informe decía que el 100 % de los
            # leads había escrito mal la palabra.
            d["typo"] = bool(escrito and kw and
                             _normaliza(escrito).replace(" ", "") not in formas_de(kw))
            d["umbrales"] = None
            cestas["cta"].append(d)
            continue
        limpio = _normaliza(texto).strip()
        # «sustantivo» = aporta contenido: 2+ palabras, o una pregunta clara
        if (len(limpio.split()) >= minpal and len(limpio) >= mincar) or _PREGUNTA.search(texto):
            cestas["sustantivo"].append(c)
        else:
            cestas["sin_clasificar"].append(c)
    total = len(flat)
    suma = sum(len(v) for v in cestas.values())
    return {
        "cestas": cestas,
        "conteo": {k: len(v) for k, v in cestas.items()},
        "total": total,
        "suma": suma,
        "cuadra": suma == total,
        "descuadre": total - suma,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  3. MÉTRICAS, CON SU LECTURA
# ══════════════════════════════════════════════════════════════════════════════
def _ratio(parte, total):
    return round(parte / total * 100, 1) if total else None


def metricas(bundle: dict, clas: dict, umbrales=None) -> dict:
    ins = bundle.get("insights") or {}
    media = bundle.get("media") or {}
    reach = ins.get("reach") or 0
    inter = ins.get("total_interactions")
    likes = ins.get("likes", media.get("like_count", 0)) or 0
    guardados = ins.get("saved") or 0
    compartidos = ins.get("shares") or 0
    coment_total = clas["total"]
    reales = coment_total - clas["conteo"]["autor"]
    # Los comentaristas únicos salen de la CLASIFICACIÓN, no del bundle crudo:
    # la clasificación siempre está, y así este número no depende de que el
    # bundle traiga o no la lista aplanada (en una prueba salió «0» por eso).
    unicos = len({(c.get("username") or "").lower()
                  for cesta in ("cta", "sustantivo", "sin_clasificar")
                  for c in clas["cestas"][cesta]} - {""})
    if inter is None:
        inter = likes + reales + guardados + compartidos
    impresiones = ins.get("impressions")
    filas = [
        ("Alcance", reach, None),
        ("Impresiones", impresiones, _ratio(impresiones, reach)) if impresiones
        else ("Impresiones", "no consta",
              "la API ya no la expone para reels en versiones recientes"),
        ("Interacciones", inter, _ratio(inter, reach)),
        ("Me gusta", likes, _ratio(likes, reach)),
        ("Comentarios", coment_total,
         f"{reales} de la audiencia + {clas['conteo']['autor']} respuestas tuyas"),
        ("Guardados", guardados, _ratio(guardados, reach)),
        ("Compartidos", compartidos, _ratio(compartidos, reach)),
        ("Personas que comentaron", unicos, _ratio(unicos, reach)),
    ]
    lec = _u(umbrales)["lecturas"]
    lecturas = {}
    r_guard = _ratio(guardados, reach)
    if r_guard is not None:
        lecturas["Guardados"] = ("señal fuerte de «esto lo voy a hacer»"
                                 if r_guard >= lec["guardados_pct_reach_fuerte"]
                                 else "poca intención de volver al contenido")
    r_int = _ratio(inter, reach)
    if r_int is not None:
        lecturas["Interacciones"] = ("engagement alto para el alcance que ha tenido"
                                     if r_int >= lec["interacciones_pct_reach_alto"]
                                     else "engagement normal")
    return {"filas": filas, "lecturas": lecturas, "reach": reach,
            "comentarios_totales": coment_total, "comentarios_audiencia": reales,
            "comentaristas_unicos": unicos}


# ══════════════════════════════════════════════════════════════════════════════
#  4. RETENCIÓN Y DISTRIBUCIÓN — lo que a la referencia le falta
# ══════════════════════════════════════════════════════════════════════════════
# Sin esto, decir «el alcance es bajo» es una hipótesis, no un diagnóstico: lo
# que explica el alcance de un reel es cuánta gente se queda en los 3 primeros
# segundos. Si la Graph API no lo da en esta versión, SE DICE — no se inventa.
_RETENCION = [
    ("ig_reels_avg_watch_time", "Tiempo medio de visionado", "ms"),
    ("ig_reels_video_view_total_time", "Tiempo total visto", "ms"),
    ("clips_replays_count", "Re-visionados", ""),
    ("ig_reels_aggregated_all_plays_count", "Reproducciones", ""),
    ("video_views", "Reproducciones", ""),
]
_DISTRIBUCION = [
    ("follows", "Nuevos seguidores desde el reel", ""),
    ("profile_visits", "Visitas al perfil", ""),
    ("profile_activity", "Acciones en el perfil", ""),
]


def _bloque(ins: dict, definicion, duracion_ms=0) -> dict:
    hay, faltan = [], []
    for clave, etiqueta, unidad in definicion:
        v = ins.get(clave)
        if v in (None, ""):
            if not any(e == etiqueta for _, e in [(x[0], x[1]) for x in definicion if ins.get(x[0])]):
                faltan.append(etiqueta)
            continue
        if unidad == "ms" and isinstance(v, (int, float)):
            hay.append((etiqueta, f"{v / 1000:.1f} s", v))
        else:
            hay.append((etiqueta, v, v))
    return {"hay": hay, "faltan": sorted(set(faltan))}


def retencion(bundle: dict) -> dict:
    ins = bundle.get("insights") or {}
    b = _bloque(ins, _RETENCION)
    medio = ins.get("ig_reels_avg_watch_time")
    dur = (bundle.get("media") or {}).get("video_duration") or 0
    if medio and dur:
        b["porcentaje_visto"] = round(medio / (dur * 1000) * 100, 1)
    b["nota"] = ("El gancho de los 3 primeros segundos y el % de reproducción completa "
                 "no los expone la Graph API para reels: se ven en la app de Instagram "
                 "(Estadísticas → Retención). Sin ellos, «alcance bajo» es una hipótesis, "
                 "no un diagnóstico.")
    return b


def distribucion(bundle: dict) -> dict:
    b = _bloque(bundle.get("insights") or {}, _DISTRIBUCION)
    b["nota"] = ("El reparto seguidores / no seguidores y la fuente de tráfico (feed, "
                 "explorar, audio, perfil) tampoco los da la API a nivel de publicación. "
                 "Están en la app; conviene anotarlos a mano si se van a usar para decidir.")
    return b


# ══════════════════════════════════════════════════════════════════════════════
#  5. LEADS — y el hueco entre captados y atendidos
# ══════════════════════════════════════════════════════════════════════════════
def leads(clas: dict, atendidos: int | None = None) -> dict:
    cta = clas["cestas"]["cta"]
    porusuario: dict[str, dict] = {}
    for c in cta:
        u = (c.get("username") or "").lower()
        if not u:
            continue
        if u not in porusuario:
            porusuario[u] = {"usuario": c.get("username"), "comentario": c.get("text", ""),
                             "keyword": c.get("keyword", ""), "escrito_como": c.get("escrito_como", ""),
                             "typo": c.get("typo", False), "cuando": c.get("timestamp", ""),
                             "veces": 0}
        porusuario[u]["veces"] += 1
    calientes = []
    for c in clas["cestas"]["sustantivo"]:
        if _COMPRA.search(c.get("text") or ""):
            calientes.append({"usuario": c.get("username"), "comentario": (c.get("text") or "").strip(),
                              "motivo": "intención de negocio explícita, más allá de la palabra-CTA"})
    con_errata = sum(1 for v in porusuario.values() if v["typo"])
    out = {
        "unicos": len(porusuario),
        "cta_totales": len(cta),
        "con_errata": con_errata,
        # Cuánto trabajo hace la tolerancia a erratas. Si sale 0 %, la keyword es
        # tan corta que no perdona ninguna; si sale alto, sin este módulo esos
        # leads se habrían perdido en silencio.
        "tasa_variantes": (round(con_errata / len(porusuario) * 100, 1)
                           if porusuario else 0.0),
        "lista": sorted(porusuario.values(), key=lambda d: d["cuando"] or ""),
        "calientes": calientes,
        "keywords": sorted({v["keyword"] for v in porusuario.values() if v["keyword"]}),
    }
    if atendidos is not None:
        out["atendidos"] = atendidos
        out["hueco"] = len(porusuario) - atendidos
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  6. SENTIMIENTO — porcentajes que no engañan
# ══════════════════════════════════════════════════════════════════════════════
def wilson(exitos: int, n: int, z: float | None = None, umbrales=None) -> tuple[float, float]:
    """Intervalo de confianza al 95 % (Wilson). Con muestras pequeñas, la
    fórmula de toda la vida da bandas absurdas; esta no."""
    if n == 0:
        return (0.0, 0.0)
    p = exitos / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centro - margen) * 100, 1),
            round(min(1.0, centro + margen) * 100, 1))


def sentimiento(conteos: dict, n: int, umbrales=None) -> dict:
    """Toma los conteos (que clasifica el modelo) y les pone rigor encima."""
    st = _u(umbrales)["sentimiento"]
    out = {"n": n, "categorias": {}, "fiable": n >= st["n_minimo_fiable"]}
    for cat, k in conteos.items():
        lo, hi = wilson(k, n, st["confianza_z"])
        out["categorias"][cat] = {"n": k, "pct": round(k / n * 100, 1) if n else 0.0,
                                  "banda": (lo, hi)}
    out["aviso"] = ("" if n >= st["n_sin_aviso"] else
                    f"Muestra pequeña (n={n}): los porcentajes son orientativos. "
                    "La banda entre paréntesis es el margen real al 95 %.")
    return out


def cuenta_odio(comentarios: list[dict]) -> tuple[int, list]:
    hits = [c for c in comentarios if _ODIO.search(c.get("text") or "")]
    return len(hits), [c.get("text", "")[:90] for c in hits[:5]]


# ══════════════════════════════════════════════════════════════════════════════
#  7. DUDAS REPETIDAS → COLA EDITORIAL
# ══════════════════════════════════════════════════════════════════════════════
_VACIAS = {"que", "como", "para", "esto", "eso", "con", "por", "una", "uno", "los",
           "las", "del", "the", "and", "you", "your", "hola", "gracias", "pero",
           "muy", "mas", "más", "tiene", "hace", "puede", "todo", "sobre"}


def dudas(sustantivos: list[dict], minimo: int | None = None, umbrales=None) -> list[dict]:
    """Agrupa las preguntas por parecido y las ordena por frecuencia.

    Agrupar por palabras clave compartidas, no por texto exacto: «¿qué monitor
    usas?» y «cómo es el panel ese» son la misma duda escrita de dos formas."""
    preguntas = [c for c in sustantivos if _PREGUNTA.search(c.get("text") or "")]
    tokens_de = []
    for c in preguntas:
        tokens_de.append({w for w in _normaliza(c.get("text", "")).split()
                          if len(w) > 3 and w not in _VACIAS})
    # Palabras que aparecen en VARIAS preguntas: eso es el tema del que habla la
    # gente. Antes solo se miraba el % de palabras compartidas, y una pregunta
    # corta contra una larga no llegaba al umbral aunque las dos hablaran de lo
    # mismo: «¿qué micro usas?» y «el micro ese de dónde lo has sacado» acababan
    # en grupos distintos, o sea, la misma duda contada dos veces.
    ud = _u(umbrales)["dudas"]
    solape = ud["solape_minimo"]
    frecuencia = Counter(w for toks in tokens_de for w in toks)
    temas = {w for w, n in frecuencia.items() if n >= ud["veces_para_ser_recurrente"]}
    grupos: list[dict] = []
    for c, toks in zip(preguntas, tokens_de):
        if not toks:
            continue
        destino = None
        for g in grupos:
            comunes = toks & g["tokens"]
            if not comunes:
                continue
            # o comparten buena parte del vocabulario, o comparten EL tema
            if (len(comunes) / min(len(toks), len(g["tokens"])) >= solape
                    or (comunes & temas)):
                destino = g
                break
        if destino is None:
            grupos.append({"tokens": set(toks), "ejemplos": [], "usuarios": []})
            destino = grupos[-1]
        destino["tokens"] |= toks
        destino["ejemplos"].append((c.get("text") or "").strip())
        if c.get("username"):
            destino["usuarios"].append(c["username"])
    salida = []
    for g in grupos:
        salida.append({"veces": len(g["ejemplos"]), "ejemplo": g["ejemplos"][0],
                       "otros": g["ejemplos"][1:4],
                       "usuarios": sorted(set(g["usuarios"]))[:8],
                       "tema": ", ".join(sorted(g["tokens"])[:4])})
    salida.sort(key=lambda d: -d["veces"])
    return salida


# ══════════════════════════════════════════════════════════════════════════════
#  8. COMPARACIÓN CON TUS REELS ANTERIORES
# ══════════════════════════════════════════════════════════════════════════════
def benchmark(actual: dict, anteriores: list[dict]) -> dict:
    """Sin línea base, «brutal» y «flojo» son adjetivos sueltos."""
    if not anteriores:
        return {"hay": False,
                "nota": "Es el primer reel analizado: todavía no hay con qué comparar. "
                        "A partir del segundo, cada cifra saldrá con su variación."}
    claves = ("reach", "total_interactions", "saved", "shares", "comentarios_audiencia")
    out = {"hay": True, "n": len(anteriores), "filas": []}
    for k in claves:
        vals = [a.get(k) for a in anteriores if isinstance(a.get(k), (int, float))]
        v = actual.get(k)
        if not vals or not isinstance(v, (int, float)):
            continue
        media = sum(vals) / len(vals)
        delta = round((v - media) / media * 100, 1) if media else None
        out["filas"].append({"metrica": k, "valor": v, "media": round(media, 1),
                             "delta": delta})
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  8bis. OBJECIONES: una objeción es una señal, no un no
# ══════════════════════════════════════════════════════════════════════════════
# Quien pone una pega está diciendo que le interesa lo bastante como para
# molestarse en discutirlo. Casi siempre es presupuesto, tiempo o «esto no me
# vale a mí» — y las tres se responden con contenido. Tratarlas como rechazo es
# tirar a la basura la mejor lista de temas que vas a tener.
_OBJECIONES = [
    ("precio", re.compile(
        r"\b(caro|carisimo|car[ií]simo|precio|presupuesto|no me lo puedo permitir|"
        r"cuesta mucho|muy caro|no tengo dinero|inversi[oó]n alta|expensive)\b",
        re.IGNORECASE),
     "Presupuesto: no lo ven caro, lo ven caro PARA LO QUE CREEN que da."),
    ("tiempo", re.compile(
        r"\b(no tengo tiempo|lleva mucho tiempo|muy lento|tarda mucho|"
        r"cu[aá]nto se tarda|cuanto tiempo lleva)\b", re.IGNORECASE),
     "Tiempo: creen que es un proyecto largo. Enseña el resultado rápido."),
    ("dificultad", re.compile(
        r"\b(muy dif[ií]cil|complicad[oa]|no s[eé] nada|soy novato|soy nueva|"
        r"no tengo ni idea|demasiado t[eé]cnico|no me aclaro)\b", re.IGNORECASE),
     "Dificultad: se ven incapaces. Un primer paso pequeño desmonta esto."),
    ("encaje", re.compile(
        r"\b(no s[eé] si me sirve|no s[eé] si vale para|para mi caso|en mi caso|"
        r"sirve para|funciona en|y si soy|y con ni[nñ]os|y si no tengo)\b",
        re.IGNORECASE),
     "Encaje: no dudan de ti, dudan de que valga para SU situación."),
    ("desconfianza", re.compile(
        r"\b(no me f[ií]o|ser[aá] verdad|suena demasiado bien|todos dicen lo mismo|"
        r"lo he probado y no)\b", re.IGNORECASE),
     "Desconfianza: han probado algo parecido y les falló. Enseña el fallo."),
]


def objeciones(sustantivos: list[dict]) -> list[dict]:
    """Las pegas, agrupadas por TIPO, con quién las puso y qué significan.

    Ojo con el orden: el odio no es una objeción y no entra aquí. Una objeción
    argumenta; un insulto no."""
    out = []
    for tipo, rx, lectura in _OBJECIONES:
        hits = [c for c in sustantivos
                if rx.search(c.get("text") or "") and not _ODIO.search(c.get("text") or "")]
        if not hits:
            continue
        out.append({
            "tipo": tipo, "veces": len(hits), "lectura": lectura,
            "usuarios": sorted({c.get("username") for c in hits if c.get("username")})[:8],
            "ejemplos": [(c.get("text") or "").strip()[:120] for c in hits[:3]],
        })
    out.sort(key=lambda d: -d["veces"])
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  8ter. COLA EDITORIAL: la voz de la audiencia convertida en calendario
# ══════════════════════════════════════════════════════════════════════════════
# Es la salida de más valor de todo esto: deja de adivinar qué grabar. Cada tema
# sale de algo que alguien preguntó de verdad, con su nombre al lado, y ordenado
# por cuánta gente lo pidió. La prioridad la calcula el código —es una cuenta,
# no una opinión— para que dos análisis del mismo reel den el mismo orden.
def _gancho(texto: str) -> str:
    """Un primer segundo a partir de la pregunta real de alguien.

    Sin florituras: la propia duda, en boca de la audiencia, es el mejor gancho
    que hay. El modelo puede pulirlo después; esto siempre está."""
    t = " ".join((texto or "").split()).strip(" ¿?¡!.,")
    if not t:
        return ""
    return f"«{t[:90]}» — me lo preguntáis en cada reel, así que vamos"


def cola_editorial(dudas_grupos: list[dict], objs: list[dict] | None = None,
                   leads_calientes: list[dict] | None = None,
                   umbrales=None) -> list[dict]:
    """Ideas priorizadas: qué grabar, por qué, y quién lo pidió.

    Prioridad = cuánta gente lo pregunta + si además es una objeción de compra.
    Una duda que repiten cinco personas vale más que una ocurrencia, y una que
    además bloquea la venta vale más todavía."""
    calientes = {(x.get("usuario") or "").lower()
                 for x in (leads_calientes or []) if x.get("usuario")}
    pesos = _u(umbrales)["cola_editorial"]
    por_obj = {o["tipo"]: o for o in (objs or [])}
    salida = []
    for g in dudas_grupos:
        gente = list(g.get("usuarios") or [])
        # una duda que hace alguien con intención de compra pesa el doble
        con_intencion = sum(1 for u in gente if (u or "").lower() in calientes)
        prioridad = (g["veces"] * pesos["peso_veces"]
                     + len(gente) * pesos["peso_personas"]
                     + con_intencion * pesos["peso_intencion_compra"])
        salida.append({
            # El titulo es la pregunta que hizo alguien, no la bolsa de palabras
            # con la que el motor agrupa: «donde, grabar, grabas, micro» no le
            # dice nada a nadie mirando la pantalla.
            "titulo": " ".join((g["ejemplo"] or g.get("tema") or "").split())[:70],
            "gancho": _gancho(g["ejemplo"]),
            "responde_a": [g["ejemplo"]] + list(g.get("otros") or [])[:2],
            "usuarios": gente[:8],
            "veces": g["veces"],
            "con_intencion_de_compra": con_intencion,
            "prioridad": prioridad,
            "por_que": f"lo preguntan {g['veces']} veces"
                       + (f" y {con_intencion} son leads con intención de compra"
                          if con_intencion else ""),
        })
    # las objeciones también son temas, y de los que más venden
    for tipo, o in por_obj.items():
        salida.append({
            "titulo": f"Responder la objeción de {tipo}",
            "gancho": _gancho(o["ejemplos"][0]) if o.get("ejemplos") else "",
            "responde_a": o.get("ejemplos", []),
            "usuarios": o.get("usuarios", []),
            "veces": o["veces"],
            "con_intencion_de_compra": 0,
            "prioridad": (o["veces"] * pesos["peso_veces"]
                          + len(o.get("usuarios") or []) * pesos["peso_personas"]
                          + pesos["peso_objecion"]),
            "por_que": o["lectura"],
        })
    salida.sort(key=lambda d: (-d["prioridad"], d["titulo"]))
    return salida


# ══════════════════════════════════════════════════════════════════════════════
#  8quater. CONVERSIÓN: donde el lead deja de ser un número
# ══════════════════════════════════════════════════════════════════════════════
# NADA de esto lo da la Graph API: ni si abrieron el DM, ni si pincharon, ni si
# compraron. Vive fuera de Instagram. Así que aquí NO se estima: se declara qué
# falta y de dónde tiene que venir. Lo que el usuario registre, se calcula; lo
# que no, se dice que no consta. Un embudo inventado es peor que no tener embudo.
_EMBUDO = [
    ("leads", "Personas que pidieron el imán", None),
    ("dm_enviados", "DM enviados", "leads"),
    ("dm_abiertos", "DM abiertos", "dm_enviados"),
    ("clics", "Clics al imán", "dm_abiertos"),
    ("ventas", "Convertidos a producto", "clics"),
]
_DE_DONDE = {
    "dm_enviados": "de tu herramienta de DM o del propio Instagram",
    "dm_abiertos": "de tu herramienta de DM (Instagram no lo expone)",
    "clics": "del acortador o del enlace con UTM que mandas en el DM",
    "ventas": "de tu pasarela de pago o tu CRM",
}


def conversion(leads_unicos: int, registro: dict | None = None) -> dict:
    """El embudo de leads a venta, con lo que haya y sin rellenar huecos.

    `registro` es lo que apunta el usuario (o su CRM). Sin registro no hay
    embudo, y eso se dice: es exactamente donde la mayoría de informes se
    inventan una tasa de conversión."""
    reg = dict(registro or {})
    reg["leads"] = leads_unicos
    filas, faltan = [], []
    previo_valor = None
    for clave, etiqueta, respecto_a in _EMBUDO:
        v = reg.get(clave)
        if v in (None, ""):
            if clave != "leads":
                faltan.append({"que": etiqueta, "de_donde": _DE_DONDE.get(clave, "")})
            continue
        v = int(v)
        tasa = None
        base = reg.get(respecto_a) if respecto_a else None
        if isinstance(base, (int, float)) and base:
            tasa = round(v / base * 100, 1)
        filas.append({"paso": etiqueta, "valor": v, "tasa": tasa,
                      "respecto_a": respecto_a or ""})
        previo_valor = v
    total = None
    if isinstance(reg.get("ventas"), int) and leads_unicos:
        total = round(reg["ventas"] / leads_unicos * 100, 1)
    return {
        "hay": len(filas) > 1,
        "filas": filas,
        "faltan": faltan,
        "tasa_global": total,
        "nota": ("La Graph API no da nada de este bloque: aperturas de DM, clics y "
                 "ventas ocurren fuera de Instagram. nexus solo calcula sobre lo "
                 "que registres; lo que no esté, se queda en «no consta» en vez de "
                 "estimarse."),
    }

# ══════════════════════════════════════════════════════════════════════════════
#  9. SALIDAS: informe .md y CSV de leads
# ══════════════════════════════════════════════════════════════════════════════
def leads_csv(datos: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["usuario", "keyword", "escrito_como", "con_errata", "veces",
                "cuando", "comentario"])
    for l in datos["lista"]:
        w.writerow([l["usuario"], l["keyword"], l["escrito_como"],
                    "si" if l["typo"] else "no", l["veces"], l["cuando"],
                    (l["comentario"] or "").replace("\n", " ")[:200]])
    return buf.getvalue()


def _tabla(cabeceras, filas) -> str:
    out = ["| " + " | ".join(cabeceras) + " |",
           "|" + "|".join(["---"] * len(cabeceras)) + "|"]
    for f in filas:
        out.append("| " + " | ".join("" if x is None else str(x) for x in f) + " |")
    return "\n".join(out)


def informe_md(ctx: dict) -> str:
    """El informe completo en Markdown (norma de la casa: los informes son .md)."""
    m, clas, ld = ctx["metricas"], ctx["clasificacion"], ctx["leads"]
    media = ctx.get("media") or {}
    p = ["# Análisis de reel",
         "", f"**{media.get('permalink') or media.get('id', '')}**  ",
         f"{media.get('timestamp', '')} · {media.get('media_type', '')}", ""]
    cap = (media.get("caption") or "").strip().replace("\n", " ")
    if cap:
        p += [f"> {cap[:180]}{'…' if len(cap) > 180 else ''}", ""]

    p += ["## Los números", ""]
    filas = []
    for etiqueta, valor, extra in m["filas"]:
        lectura = m["lecturas"].get(etiqueta, "")
        pista = (f"{extra}% del alcance" if isinstance(extra, (int, float)) else (extra or ""))
        filas.append([etiqueta, f"{valor:,}".replace(",", ".") if isinstance(valor, int) else valor,
                      " · ".join(x for x in (pista, lectura) if x)])
    p += [_tabla(["Métrica", "Valor", "Lectura"], filas), ""]

    p += ["## De dónde sale cada comentario", "",
          "Todo comentario cae en una sola cesta y la suma es el total: si algo no "
          "cuadrara, aparecería aquí en vez de disimularse.", ""]
    c = clas["conteo"]
    p += [_tabla(["Cesta", "Cuántos", "Qué es"], [
        ["Respuestas tuyas", c["autor"], "las escribiste tú: no opinan ni son leads"],
        ["Palabra-CTA", c["cta"], "dispararon tu gancho — son el pipeline"],
        ["Con contenido", c["sustantivo"], "preguntas, opiniones y objeciones"],
        ["Sin clasificar", c["sin_clasificar"], "emojis sueltos, «top», etiquetas"],
        ["**TOTAL**", clas["total"], "✔ cuadra" if clas["cuadra"]
         else f"✖ DESCUADRA en {clas['descuadre']}"]]), ""]

    p += ["## Leads", "",
          f"- **{ld['unicos']}** personas distintas con intención "
          f"({ld['cta_totales']} comentarios con la palabra-CTA)"]
    if ld["con_errata"]:
        p.append(f"- **{ld['con_errata']}** la escribieron mal y aun así se han "
                 f"recogido (si solo buscaras la palabra exacta, los perderías)")
    if ld.get("keywords"):
        p.append(f"- Palabras que la dispararon: {', '.join(ld['keywords'])}")
    if "hueco" in ld:
        h = ld["hueco"]
        if h > 0:
            estado = f"**quedan {h} sin atender** — conviene cerrarlos antes de dar la cifra por buena"
        elif h == 0:
            estado = "cuadra ✔"
        else:
            estado = (f"hay **{abs(h)} respuestas de más** que personas con intención: "
                      "probablemente envíos repetidos, conviene revisarlo")
        p.append(f"- Atendidos: **{ld['atendidos']}** · {estado}")
    else:
        p.append("- _Cuántos recibieron respuesta: no consta. Sin ese dato, «leads "
                 "captados» y «leads atendidos» no se pueden cuadrar._")
    if ld["calientes"]:
        p += ["", "### Los más calientes", ""]
        p += [_tabla(["Usuario", "Qué dijo", "Por qué"],
                     [[x["usuario"], f"«{x['comentario'][:70]}»", x["motivo"]]
                      for x in ld["calientes"][:15]])]
    p.append("")

    s = ctx.get("sentimiento")
    if s:
        p += ["## Sentimiento", "",
              f"Sobre **{s['n']}** comentarios con contenido "
              f"(los de la palabra-CTA no opinan, así que quedan fuera).", ""]
        p += [_tabla(["", "Comentarios", "%", "Margen real (95 %)"],
                     [[k.capitalize(), v["n"], f"{v['pct']}%", f"{v['banda'][0]}–{v['banda'][1]}%"]
                      for k, v in s["categorias"].items()])]
        if s.get("aviso"):
            p += ["", f"_{s['aviso']}_"]
        p.append("")
    if ctx.get("odio") is not None:
        n_odio, ej = ctx["odio"]
        p += [f"**Comentarios de odio: {n_odio}**"
              + (f" — ejemplos: {'; '.join(ej)}" if n_odio else " ✔"), ""]

    d = ctx.get("dudas") or []
    if d:
        p += ["## Lo que más preguntan", ""]
        p += [_tabla(["Veces", "La duda", "Quién la hizo"],
                     [[x["veces"], f"«{x['ejemplo'][:80]}»", ", ".join(x["usuarios"][:4])]
                      for x in d[:12]]), ""]

    r = ctx.get("retencion") or {}
    p += ["## Retención de vídeo", ""]
    if r.get("hay"):
        p += [_tabla(["Métrica", "Valor"], [[e, v] for e, v, _ in r["hay"]]), ""]
    if r.get("faltan"):
        p += [f"No disponibles: {', '.join(r['faltan'])}.", ""]
    p += [f"_{r.get('nota', '')}_", ""]

    dis = ctx.get("distribucion") or {}
    p += ["## Distribución", ""]
    if dis.get("hay"):
        p += [_tabla(["Métrica", "Valor"], [[e, v] for e, v, _ in dis["hay"]]), ""]
    p += [f"_{dis.get('nota', '')}_", ""]

    b = ctx.get("benchmark") or {}
    p += ["## Comparado con tus reels anteriores", ""]
    if b.get("hay"):
        p += [_tabla(["Métrica", "Este reel", f"Media de {b['n']}", "Variación"],
                     [[f["metrica"], f["valor"], f["media"],
                       (f"{f['delta']:+}%" if f["delta"] is not None else "—")]
                      for f in b["filas"]]), ""]
    else:
        p += [f"_{b.get('nota', '')}_", ""]

    objs = ctx.get("objeciones") or []
    if objs:
        p += ["## Objeciones (que son señal)", "",
              "Quien discute el precio está diciendo que le interesa. Estas son las "
              "pegas reales, agrupadas por tipo, y cada una es un tema que grabar.", ""]
        p += [_tabla(["Tipo", "Veces", "Qué significa", "Quién"],
                     [[o["tipo"], o["veces"], o["lectura"],
                       ", ".join("@" + u for u in o["usuarios"][:4]) or "—"]
                      for o in objs]), ""]

    cola = ctx.get("cola") or []
    if cola:
        p += ["## Qué grabar, por orden", "",
              "La prioridad es una cuenta, no una opinión: cuánta gente lo pregunta "
              "más el peso extra de quien ya tiene intención de compra.", ""]
        for i, idea in enumerate(cola[:10], 1):
            p += [f"{i}. **{idea['titulo']}** — prioridad {idea['prioridad']}",
                  f"   - Gancho: {idea['gancho']}",
                  f"   - Por qué: {idea['por_que']}",
                  f"   - Lo piden: " + (", ".join("@" + u for u in idea["usuarios"][:6])
                                        or "—")]
        p += [""]

    cv = ctx.get("conversion")
    if cv:
        p += ["## Conversión", ""]
        if cv["filas"] and len(cv["filas"]) > 1:
            p += [_tabla(["Paso", "Cuántos", "Tasa"],
                         [[f["paso"], f["valor"],
                           (f"{f['tasa']}%" if f["tasa"] is not None else "—")]
                          for f in cv["filas"]]), ""]
            if cv["tasa_global"] is not None:
                p += [f"De cada 100 leads, **{cv['tasa_global']}** acaban comprando.", ""]
        if cv["faltan"]:
            p += ["Falta por registrar (y por eso NO se estima):", ""]
            p += [f"- {x['que']} — {x['de_donde']}" for x in cv["faltan"]] + [""]
        p += [f"_{cv['nota']}_", ""]

    if ctx.get("ideas"):
        p += ["## Ideas del modelo", "", str(ctx["ideas"]), ""]

    p += ["---", "",
          "Generado por nexus en modo **solo lectura**: no se ha publicado, respondido "
          "ni modificado nada en la cuenta.", ""]
    if not (ctx.get("conversion") or {}).get("hay"):
        p += ["> **Lo que falta para cerrar el círculo:** apertura de los mensajes, "
              "clics al lead magnet y cuántos de estos leads acaban comprando. Ahí es "
              "donde un número de leads se convierte en dinero; la API de Instagram no "
              "lo da, sale de tu CRM cruzando el CSV de leads.", ""]
    return "\n".join(p)


# ══════════════════════════════════════════════════════════════════════════════
#  10. EL PANEL — las mismas cifras, pero para verlas en nexus
# ══════════════════════════════════════════════════════════════════════════════
# El .md sirve para archivar y para el CRM. Para MIRAR el análisis está el HUD,
# y ahí no vale un muro de texto: hace falta saber, de un vistazo, qué número es,
# de dónde sale y cómo se ha calculado. Por eso cada fila lleva su ORIGEN (qué
# campo de la Graph API) y su CÓMO (la cuenta exacta), y cada bloque dice con qué
# método trabaja. Nada de cifras que aparecen sin explicación.
#
# Este diccionario es la trazabilidad de cada métrica: sin él, «Alcance: 19.395»
# es un número que hay que creerse.
_ORIGEN = {
    "Alcance": ("Graph API · insights.reach",
                "Tal cual lo da Instagram. nexus no lo toca."),
    "Impresiones": ("Graph API · insights.impressions",
                    "Si la versión de la API ya no la expone para reels, se dice "
                    "que no consta en vez de estimarla desde el alcance."),
    "Interacciones": ("Graph API · insights.total_interactions",
                      "Si la API no la trae, se reconstruye: me gusta + comentarios "
                      "de la audiencia + guardados + compartidos."),
    "Me gusta": ("Graph API · insights.likes (o media.like_count)",
                 "Tal cual lo da Instagram."),
    "Comentarios": ("Graph API · comments, paginados con sus respuestas anidadas",
                    "Todo lo bajado, incluidas TUS respuestas: se separan al "
                    "clasificar para que no inflen el dato."),
    "Guardados": ("Graph API · insights.saved", "Tal cual lo da Instagram."),
    "Compartidos": ("Graph API · insights.shares", "Tal cual lo da Instagram."),
    "Personas que comentaron": (
        "Calculado por nexus",
        "Usuarios distintos entre los comentarios de la audiencia. La API no da "
        "este número: se cuenta aquí, y por eso no depende de qué traiga el "
        "bundle."),
}

# Cómo trabaja cada bloque. Es lo que se enseña al desplegar la sección — y va
# con los NÚMEROS QUE HAY CONFIGURADOS, no con unos fijos escritos aquí. Si
# cambias un umbral en config/umbrales.json, el texto del panel lo dice. Un
# «cómo se calcula» que miente es peor que no tenerlo.
def _metodos(u: dict) -> dict:
    lec, st = u["lecturas"], u["sentimiento"]
    err, pes = u["erratas"], u["cola_editorial"]
    return {
        "numeros": ("Cifras de la Graph API en modo solo lectura. Lo que la API no da "
                    "no se estima: se marca como que no consta. Umbrales de lectura: "
                    f"guardados por encima del {lec['guardados_pct_reach_fuerte']} % del "
                    f"alcance se leen como señal fuerte, e interacciones por encima del "
                    f"{lec['interacciones_pct_reach_alto']} % como engagement alto."),
        "reparto": "Cada comentario cae en UNA cesta y solo una. La suma tiene que ser "
                   "el total; si no lo es, aquí se ve el descuadre en vez de taparlo.",
        "leads": ("Una persona = un lead, aunque comente cinco veces. Se tolera que "
                  "escriban mal la palabra-gancho, con un margen que depende de lo "
                  f"larga que sea: hasta {err['sin_margen_hasta']} letras no se "
                  f"perdona ninguna errata, y a partir de ahí hasta "
                  f"{err['margen_maximo']}."),
        "sentimiento": ("Lo único que interpreta el modelo. El código le pone encima el "
                        "tamaño de muestra y la banda de confianza (Wilson): un "
                        "porcentaje sin su n no dice nada. Por debajo de "
                        f"n={st['n_minimo_fiable']} no se considera fiable, y hasta "
                        f"n={st['n_sin_aviso']} sale con aviso."),
        "dudas": "Las preguntas se agrupan por palabras clave compartidas, no por texto "
                 "exacto: la misma duda escrita de dos formas es una sola duda.",
        "retencion": "Solo lo que expone la API. El gancho de los 3 primeros segundos "
                     "no lo da: se dice y se apunta dónde mirarlo.",
        "distribucion": "Igual: lo que da la API se muestra; lo que no, se declara.",
        "benchmark": "Cada cifra contra la media de tus reels ya analizados. Sin línea "
                     "base no hay comparación, y se dice.",
        "ideas": "Lo cualitativo, con tu perfil delante: qué grabar después.",
        "objeciones": "Una objeción es una señal, no un no: quien discute el precio "
                      "está diciendo que le interesa. Se agrupan por tipo, con quién "
                      "la puso. El odio no entra aquí: insultar no es argumentar.",
        "cola": ("La prioridad es una cuenta, no una opinión: cada vez que lo preguntan "
                 f"suma {pes['peso_veces']}, cada persona distinta {pes['peso_personas']}, "
                 f"y quien además tiene intención de compra {pes['peso_intencion_compra']}. "
                 "Dos análisis del mismo reel dan el mismo orden."),
        "conversion": "Nada de este bloque lo da la Graph API — pasa fuera de "
                      "Instagram. Se calcula solo sobre lo que registres; lo que falte "
                      "se queda en «no consta».",
    }


def _num(v):
    """19395 -> «19.395». Para leerlo de un vistazo, que es de lo que se trata."""
    return f"{v:,}".replace(",", ".") if isinstance(v, int) else v


def panel(ctx: dict, umbrales=None) -> dict:
    """El análisis en la forma que espera el HUD: secciones con su método.

    Mismos números que el .md —salen de las mismas funciones— pero estructurados
    para pintarlos: cada sección trae su recuento para el plegado, y cada fila su
    origen y su cómo, que es lo que convierte una cifra en una cifra fiable.
    """
    _METODO = _metodos(_u(umbrales))
    m, clas = ctx["metricas"], ctx["clasificacion"]
    ld = ctx.get("leads") or {}
    media = ctx.get("media") or {}
    secs = []

    # ── los números, cada uno con su procedencia ─────────────────────────────
    filas = []
    for etiqueta, valor, extra in m["filas"]:
        origen, como = _ORIGEN.get(etiqueta, ("Calculado por nexus", ""))
        pista = (f"{extra} % del alcance" if isinstance(extra, (int, float))
                 else (extra or ""))
        filas.append({"metrica": etiqueta, "valor": valor, "valor_txt": _num(valor),
                      "pista": pista, "lectura": m["lecturas"].get(etiqueta, ""),
                      "origen": origen, "como": como})
    secs.append({"id": "numeros", "titulo": "Los números", "n": len(filas),
                 "metodo": _METODO["numeros"], "filas": filas})

    # ── el reparto: cuatro cestas que tienen que sumar el total ──────────────
    c = clas["conteo"]
    cestas = [
        {"cesta": "Tuyos", "n": c["autor"],
         "que_es": "los escribiste tú respondiendo. No son opinión de nadie."},
        {"cesta": "Palabra-gancho", "n": c["cta"],
         "que_es": "pidieron lo que ofrecías. Son los leads."},
        {"cesta": "Con contenido", "n": c["sustantivo"],
         "que_es": "dicen algo: una pregunta, una opinión, una objeción."},
        {"cesta": "Sin clasificar", "n": c["sin_clasificar"],
         "que_es": "emojis, «top», una etiqueta. Ni opinan ni son leads — pero se "
                   "cuentan, para que la suma cuadre."},
    ]
    secs.append({"id": "reparto", "titulo": "De dónde sale cada comentario",
                 "n": clas["total"], "metodo": _METODO["reparto"],
                 "cestas": cestas, "total": clas["total"], "suma": clas["suma"],
                 "cuadra": clas["cuadra"], "descuadre": clas["descuadre"]})

    # ── leads ────────────────────────────────────────────────────────────────
    if ld:
        secs.append({
            "id": "leads", "titulo": "Leads", "n": ld.get("unicos", 0),
            "metodo": _METODO["leads"],
            "unicos": ld.get("unicos", 0), "cta_totales": ld.get("cta_totales", 0),
            "con_errata": ld.get("con_errata", 0),
            "tasa_variantes": ld.get("tasa_variantes", 0.0),
            "atendidos": ld.get("atendidos"), "hueco": ld.get("hueco"),
            "keywords": ld.get("keywords", []),
            "calientes": ld.get("calientes", [])[:8],
            # Se enseña lo que ESCRIBIO la persona, no la forma normalizada con
            # la que casa el motor: «quierolaplantilla» no lo ha escrito nadie.
            "muestra": [{"usuario": x["usuario"],
                         "escrito_como": " ".join((x.get("comentario") or
                                                   x["escrito_como"]).split())[:40],
                         "typo": x["typo"], "veces": x["veces"]}
                        for x in ld.get("lista", [])[:12]],
        })

    # ── sentimiento con su muestra ───────────────────────────────────────────
    sn = ctx.get("sentimiento")
    if sn:
        cats = []
        for cat, d in sn["categorias"].items():
            lo, hi = d["banda"]
            cats.append({"categoria": cat, "n": d["n"], "pct": d["pct"],
                         "banda": [lo, hi], "ancho": round(hi - lo, 1)})
        cats.sort(key=lambda d: -d["pct"])
        secs.append({"id": "sentimiento", "titulo": "Sentimiento", "n": sn["n"],
                     "metodo": _METODO["sentimiento"], "categorias": cats,
                     "muestra": sn["n"], "fiable": sn["fiable"],
                     "aviso": sn["aviso"]})

    # ── lo que más preguntan ─────────────────────────────────────────────────
    dd = ctx.get("dudas") or []
    if dd:
        secs.append({"id": "dudas", "titulo": "Lo que más preguntan", "n": len(dd),
                     "metodo": _METODO["dudas"],
                     "grupos": [{"veces": g["veces"], "ejemplo": g["ejemplo"],
                                 "otros": g["otros"], "usuarios": g["usuarios"]}
                                for g in dd[:10]]})

    # ── retención y distribución: lo que hay y lo que NO ─────────────────────
    for cual, titulo in (("retencion", "Retención de vídeo"),
                         ("distribucion", "Distribución")):
        b = ctx.get(cual)
        if not b:
            continue
        secs.append({"id": cual, "titulo": titulo, "n": len(b["hay"]),
                     "metodo": _METODO[cual],
                     "hay": [{"que": e, "valor": _num(v)} for e, v, _ in b["hay"]],
                     "faltan": b.get("faltan", []),
                     "porcentaje_visto": b.get("porcentaje_visto"),
                     "nota": b.get("nota", "")})

    # ── objeciones: lo que bloquea la venta, dicho por ellos ─────────────────
    objs = ctx.get("objeciones") or []
    if objs:
        secs.append({"id": "objeciones", "titulo": "Objeciones (que son señal)",
                     "n": sum(o["veces"] for o in objs),
                     "metodo": _METODO["objeciones"], "tipos": objs})

    # ── la cola editorial: qué grabar y por qué ──────────────────────────────
    cola = ctx.get("cola") or []
    if cola:
        secs.append({"id": "cola", "titulo": "Qué grabar, por orden", "n": len(cola),
                     "metodo": _METODO["cola"], "ideas": cola[:12]})

    # ── el embudo, con los huecos a la vista ─────────────────────────────────
    cv = ctx.get("conversion")
    if cv:
        secs.append({"id": "conversion", "titulo": "Conversión",
                     "n": len(cv["filas"]), "metodo": _METODO["conversion"],
                     "hay": cv["hay"], "filas": cv["filas"],
                     "faltan": cv["faltan"], "tasa_global": cv["tasa_global"],
                     "nota": cv["nota"]})

    # ── comparación con reels anteriores ─────────────────────────────────────
    bm = ctx.get("benchmark")
    if bm:
        nombres = {"reach": "Alcance", "total_interactions": "Interacciones",
                   "saved": "Guardados", "shares": "Compartidos",
                   "comentarios_audiencia": "Comentarios de la audiencia"}
        secs.append({"id": "benchmark", "titulo": "Comparado con tus reels anteriores",
                     "n": len(bm.get("filas", [])), "metodo": _METODO["benchmark"],
                     "hay": bm["hay"], "base": bm.get("n", 0),
                     "nota": bm.get("nota", ""),
                     "filas": [{"metrica": nombres.get(f["metrica"], f["metrica"]),
                                "valor": _num(f["valor"]), "media": _num(f["media"]),
                                "delta": f["delta"]} for f in bm.get("filas", [])]})

    # ── ideas ────────────────────────────────────────────────────────────────
    ideas = ctx.get("ideas") or []
    if ideas:
        secs.append({"id": "ideas", "titulo": "Qué grabar después", "n": len(ideas),
                     "metodo": _METODO["ideas"],
                     "lista": [str(x) for x in ideas[:10]]})

    odio_n, odio_ej = ctx.get("odio") or (0, [])
    return {
        "hay": True,
        "reel": {"id": media.get("id", ""), "permalink": media.get("permalink", ""),
                 "cuando": media.get("timestamp", ""), "tipo": media.get("media_type", ""),
                 "caption": (media.get("caption") or "").strip()[:220]},
        "resumen": {"comentarios": clas["total"], "leads": ld.get("unicos", 0),
                    "con_contenido": c["sustantivo"], "cuadra": clas["cuadra"],
                    "alcance": _num(m.get("reach", 0))},
        "odio": {"n": odio_n, "ejemplos": odio_ej},
        "solo_lectura": True,
        "secciones": secs,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  11. COMPETENCIA — cuentas que no administras
# ══════════════════════════════════════════════════════════════════════════════
# Con la API oficial (business_discovery) de una cuenta ajena se ve lo PÚBLICO:
# seguidores, publicaciones, reproducciones, me gusta y CUÁNTOS comentarios.
#
# Lo que NO se puede ver, y aquí se dice en vez de disimularse:
#   · El TEXTO de los comentarios → sin texto no hay sentimiento. Ni estimado ni
#     inventado: no se puede saber si la gente le habla bien o mal.
#   · Compartidos, guardados, alcance e impresiones → son métricas privadas de
#     esa cuenta. Ni Instagram ni nadie las expone a terceros.
# Sacarlas por scraping violaría los términos de Instagram y te quemaría el
# token, así que nexus no lo hace.
#
# Y una decisión de método que cambia las conclusiones: aquí se usa la MEDIANA,
# no la media. En Instagram un solo vídeo viral multiplica la media por diez y
# hace parecer que una cuenta rinde el triple de lo que rinde. La mediana dice
# cómo le va a una publicación NORMAL suya, que es contra lo que te comparas.
LIMITES_AJENAS = [
    ("Sentimiento de sus comentarios",
     "la API da el número de comentarios de cuentas ajenas, nunca su texto",
     "hay que leerlos a mano en la publicación"),
    ("Compartidos", "métrica privada de esa cuenta", "solo lo ve quien la administra"),
    ("Guardados", "métrica privada de esa cuenta", "solo lo ve quien la administra"),
    ("Alcance e impresiones", "métricas privadas de esa cuenta",
     "solo lo ve quien la administra"),
]


def _mediana(valores) -> float:
    vals = [v for v in valores if isinstance(v, (int, float))]
    return round(statistics.median(vals), 1) if vals else 0.0


def _fecha(ts: str):
    try:
        return datetime.strptime((ts or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _formato(m: dict) -> str:
    t = (m.get("media_product_type") or m.get("media_type") or "").upper()
    return {"REELS": "Reel", "FEED": "Publicación", "VIDEO": "Vídeo",
            "CAROUSEL_ALBUM": "Carrusel", "IMAGE": "Imagen",
            "STORY": "Historia"}.get(t, t.title() or "Otro")


def perfil_publico(usuario: str, datos: dict) -> dict:
    """Las cifras de UNA cuenta ajena a partir de lo que da business_discovery."""
    if not datos or datos.get("error"):
        return {"usuario": usuario, "hay": False,
                "error": (datos or {}).get("error", "sin datos"),
                "motivos": (datos or {}).get("motivos", [])}
    media = datos.get("media") or []
    seguidores = datos.get("followers_count") or 0
    reproducciones = [m.get("view_count") for m in media
                      if isinstance(m.get("view_count"), (int, float))]
    likes = [m.get("like_count") or 0 for m in media]
    coments = [m.get("comments_count") or 0 for m in media]

    # ritmo de publicación: de la más antigua a la más nueva que hemos bajado
    fechas = sorted(f for f in (_fecha(m.get("timestamp")) for m in media) if f)
    por_semana = None
    if len(fechas) >= 2:
        dias = max(1.0, (fechas[-1] - fechas[0]).total_seconds() / 86400)
        por_semana = round(len(fechas) / dias * 7, 1)

    # qué formato le funciona: mediana de reproducciones (o de me gusta) por tipo
    porform: dict = {}
    for m in media:
        f = _formato(m)
        porform.setdefault(f, {"n": 0, "vistas": [], "likes": [], "coment": []})
        porform[f]["n"] += 1
        if isinstance(m.get("view_count"), (int, float)):
            porform[f]["vistas"].append(m["view_count"])
        porform[f]["likes"].append(m.get("like_count") or 0)
        porform[f]["coment"].append(m.get("comments_count") or 0)
    formatos = [{"formato": f, "n": d["n"],
                 "reproducciones": _mediana(d["vistas"]) or None,
                 "me_gusta": _mediana(d["likes"]),
                 "comentarios": _mediana(d["coment"])}
                for f, d in porform.items()]
    formatos.sort(key=lambda d: -(d["reproducciones"] or d["me_gusta"]))

    med_likes, med_com = _mediana(likes), _mediana(coments)
    # engagement sobre SEGUIDORES: es lo comparable entre cuentas de tamaños
    # distintos. Sobre alcance sería mejor, pero el alcance ajeno no se ve.
    engagement = (round((med_likes + med_com) / seguidores * 100, 2)
                  if seguidores else None)
    # cuánto CONVERSA su público: comentar cuesta más que dar a me gusta, así que
    # este ratio distingue una audiencia que responde de una que solo pasa.
    conversacion = round(med_com / med_likes * 100, 2) if med_likes else None

    mejores = sorted(
        media,
        key=lambda m: (m.get("view_count") if isinstance(m.get("view_count"), (int, float))
                       else (m.get("like_count") or 0)),
        reverse=True)[:5]
    return {
        "usuario": datos.get("username") or usuario,
        "hay": True,
        "nombre": datos.get("name", ""),
        "bio": (datos.get("biography") or "").strip()[:200],
        "seguidores": seguidores,
        "publicaciones_totales": datos.get("media_count") or 0,
        "analizadas": len(media),
        "tiene_reproducciones": bool(reproducciones),
        "med_reproducciones": _mediana(reproducciones) if reproducciones else None,
        "max_reproducciones": max(reproducciones) if reproducciones else None,
        "med_me_gusta": med_likes,
        "med_comentarios": med_com,
        "engagement": engagement,
        "conversacion": conversacion,
        "por_semana": por_semana,
        "formatos": formatos,
        "mejores": [{"caption": " ".join((m.get("caption") or "").split())[:90],
                     "formato": _formato(m),
                     "reproducciones": m.get("view_count"),
                     "me_gusta": m.get("like_count") or 0,
                     "comentarios": m.get("comments_count") or 0,
                     "cuando": (m.get("timestamp") or "")[:10],
                     "enlace": m.get("permalink", "")} for m in mejores],
    }


def mi_perfil_publico(usuario: str, seguidores: int, medios: list) -> dict:
    """Tu cuenta medida con la MISMA vara que las ajenas.

    Sin esto la comparación es tramposa: tú tienes alcance y guardados de tus
    reels y de ellos no, así que comparar «tu engagement sobre alcance» contra
    «su engagement sobre seguidores» no compara nada."""
    return perfil_publico(usuario, {"username": usuario, "followers_count": seguidores,
                                    "media_count": len(medios), "media": medios})


def competencia(cuentas: list[dict], propia: dict | None = None) -> dict:
    """Compara tu cuenta con las que le digas, con lo que la API deja ver."""
    perfiles = [perfil_publico(c.get("usuario", ""), c.get("datos") or {})
                for c in cuentas]
    validos = [p for p in perfiles if p["hay"]]
    fallidos = [p for p in perfiles if not p["hay"]]
    todos = ([dict(propia, es_tuya=True)] if propia and propia.get("hay") else []) + [
        dict(p, es_tuya=False) for p in validos]

    filas = []
    for campo, etiqueta, unidad in (
            ("seguidores", "Seguidores", ""),
            ("med_reproducciones", "Reproducciones (mediana)", ""),
            ("med_me_gusta", "Me gusta (mediana)", ""),
            ("med_comentarios", "Comentarios (mediana)", ""),
            ("engagement", "Interacción sobre seguidores", "%"),
            ("conversacion", "Comentarios por cada 100 me gusta", ""),
            ("por_semana", "Publicaciones por semana", "")):
        valores = [{"usuario": p["usuario"], "valor": p.get(campo),
                    # el numero para comparar, y el texto para leerlo
                    "valor_txt": (None if p.get(campo) is None
                                  else _num(int(p[campo]) if float(p[campo]).is_integer()
                                            else p[campo])),
                    "es_tuya": p["es_tuya"]} for p in todos]
        numericos = [v["valor"] for v in valores
                     if isinstance(v["valor"], (int, float))]
        mejor = max(numericos) if numericos else None
        filas.append({"metrica": etiqueta, "unidad": unidad, "valores": valores,
                      "lider": next((v["usuario"] for v in valores
                                     if v["valor"] == mejor and mejor is not None), "")})

    # dónde estás por debajo: solo con datos, sin adjetivos
    brechas = []
    if propia and propia.get("hay") and validos:
        for campo, etiqueta in (("engagement", "interacción sobre seguidores"),
                                ("med_reproducciones", "reproducciones"),
                                ("conversacion", "conversación en comentarios"),
                                ("por_semana", "ritmo de publicación")):
            mio = propia.get(campo)
            ajenos = [p.get(campo) for p in validos
                      if isinstance(p.get(campo), (int, float))]
            if not isinstance(mio, (int, float)) or not ajenos:
                continue
            ref = _mediana(ajenos)
            if not ref:
                continue
            dif = round((mio - ref) / ref * 100, 1)
            brechas.append({"que": etiqueta, "tuyo": mio, "de_ellos": ref,
                            "diferencia": dif,
                            "lectura": ("por encima de la mediana del sector"
                                        if dif >= 0 else
                                        "por debajo de la mediana del sector")})
        brechas.sort(key=lambda d: d["diferencia"])

    return {
        "hay": bool(validos),
        "cuentas": validos,
        "propia": propia if (propia or {}).get("hay") else None,
        "fallidas": fallidos,
        "comparacion": filas,
        "brechas": brechas,
        "metodo": ("Mediana, no media: en Instagram un solo vídeo viral dispara la "
                   "media y hace parecer que una cuenta rinde el triple de lo que "
                   "rinde. La mediana dice cómo le va a una publicación normal, que "
                   "es contra lo que te comparas de verdad."),
        "no_disponible": [{"que": q, "por_que": p, "donde": d}
                          for q, p, d in LIMITES_AJENAS],
    }


def panel_competencia(comp: dict) -> dict:
    """La comparativa en la forma que espera el HUD."""
    secs = []
    if comp.get("comparacion"):
        secs.append({"id": "tabla", "titulo": "Cara a cara",
                     "n": len(comp["comparacion"]),
                     "metodo": comp["metodo"], "filas": comp["comparacion"]})
    if comp.get("brechas"):
        secs.append({"id": "brechas", "titulo": "Frente a ellos, de lo peor a lo mejor",
                     "n": len(comp["brechas"]),
                     "metodo": "Tu cifra contra la mediana de las cuentas que has "
                               "elegido. Sin adjetivos: la diferencia en %.",
                     "filas": comp["brechas"]})
    if comp.get("cuentas"):
        secs.append({"id": "cuentas", "titulo": "Qué publica cada una",
                     "n": len(comp["cuentas"]),
                     "metodo": "Sus formatos ordenados por lo que mejor le funciona, "
                               "y sus cinco publicaciones más vistas.",
                     "cuentas": comp["cuentas"]})
    secs.append({"id": "limites", "titulo": "Lo que de una cuenta ajena NO se puede ver",
                 "n": len(comp.get("no_disponible", [])),
                 "metodo": "La API oficial no expone estos datos de cuentas que no "
                           "administras. nexus no los estima ni los saca por otra "
                           "vía: bajarlos por scraping violaría los términos de "
                           "Instagram.",
                 "limites": comp.get("no_disponible", [])})
    return {"hay": comp.get("hay", False), "secciones": secs,
            "fallidas": comp.get("fallidas", []), "solo_lectura": True}


def competencia_md(comp: dict) -> str:
    """La comparativa en Markdown (norma de la casa: los informes son .md)."""
    p = ["# Competencia", ""]
    if not comp.get("hay"):
        p += ["No se ha podido consultar ninguna cuenta.", ""]
    else:
        p += ["## Cara a cara", "", comp["metodo"], ""]
        nombres = [v["usuario"] for v in comp["comparacion"][0]["valores"]]
        filas = []
        for f in comp["comparacion"]:
            fila = [f["metrica"] + (f" ({f['unidad']})" if f["unidad"] else "")]
            for v in f["valores"]:
                fila.append("no consta" if v["valor"] is None else str(v["valor"]))
            filas.append(fila)
        p += [_tabla(["Métrica"] + [("TÚ · " + n) if comp.get("propia") and
                                    n == comp["propia"]["usuario"] else n
                                    for n in nombres], filas), ""]
    if comp.get("brechas"):
        p += ["## Dónde estás por debajo", ""]
        p += [_tabla(["Qué", "Tú", "Mediana de ellos", "Diferencia"],
                     [[b["que"], b["tuyo"], b["de_ellos"], f"{b['diferencia']:+}%"]
                      for b in comp["brechas"]]), ""]
    for c in comp.get("cuentas", []):
        p += [f"## @{c['usuario']}", "",
              f"- {c['seguidores']:,} seguidores · {c['publicaciones_totales']} "
              f"publicaciones · analizadas {c['analizadas']}".replace(",", "."), ""]
        if c["formatos"]:
            p += [_tabla(["Formato", "Cuántas", "Reproducciones", "Me gusta", "Comentarios"],
                         [[f["formato"], f["n"],
                           "no consta" if f["reproducciones"] is None else f["reproducciones"],
                           f["me_gusta"], f["comentarios"]] for f in c["formatos"]]), ""]
        if c["mejores"]:
            p += ["Lo que más le ha funcionado:", ""]
            for m in c["mejores"]:
                cifra = (f"{m['reproducciones']} reproducciones"
                         if m["reproducciones"] is not None
                         else f"{m['me_gusta']} me gusta")
                p += [f"- {m['cuando']} · {m['formato']} · {cifra} — {m['caption']}"]
            p += [""]
    if comp.get("fallidas"):
        p += ["## Cuentas que no se han podido consultar", ""]
        for f in comp["fallidas"]:
            p += [f"- **@{f['usuario']}**: {f.get('error', '')}"]
            p += [f"  - {m}" for m in f.get("motivos", [])]
        p += [""]
    p += ["## Lo que de una cuenta ajena NO se puede ver", "",
          "La API oficial no lo expone y nexus no lo estima ni lo saca por otra vía:", ""]
    p += [_tabla(["Qué", "Por qué", "Dónde está"],
                 [[x["que"], x["por_que"], x["donde"]]
                  for x in comp.get("no_disponible", [])]), ""]
    p += ["---", "", "Consultado en modo **solo lectura** con la API oficial de "
          "Instagram (business_discovery). No se ha tocado ninguna cuenta.", ""]
    return "\n".join(p)
