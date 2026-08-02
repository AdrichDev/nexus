"""
nexus — PROCEDENCIA: de dónde sale cada cifra de Content OS.

EL INCIDENTE (01/08/2026). Content OS servía números sin decir de dónde venían.
`dashboard()` mezclaba lo que devolvía la Graph API con un dataset de mentira
mediante un `or` silencioso (`_ig_metrics() or _demo_metrics()`), así que el HUD
pintaba «12.840 seguidores» exactamente igual estuviera conectado o no. Y la
skill contestaba en el chat «retención media 48,6 %» con una coletilla de
«(ejemplo)» que el resto del texto contradecía.

Es el mismo fallo que motivó la REGLA INVIOLABLE de `llm.py`, pero cometido en
nuestro código en vez de por el modelo. La diferencia es que aquí sí se puede
arreglar de raíz: **ninguna cifra viaja suelta**. Cada número sale envuelto en
un sobre con su origen, y quien lo pinta se niega a pintar lo que no lo traiga.

Aquí viven tres cosas:
  * `dato()` — la fábrica del sobre. Valida el origen EN EL SITIO: un origen mal
    escrito es una cifra sin procedencia disfrazada de cifra con procedencia.
  * el lector de la sección `content_os` de `config/umbrales.json`, con la misma
    forma que `remote.py:_carga_umbrales_red()`. NO se importa el
    `cargar_umbrales()` de `skills/instagram/analisis.py`: el backend no puede
    depender de una skill (invertiría las capas). Se asume la duplicación
    consciente de un lector de quince líneas.
  * `sin_cifras_inventadas()` — el cinturón determinista para el texto que
    devuelve un LLM. La regla del prompt es una petición; esto es una comprobación.
"""
from __future__ import annotations

import json
import re

from .config import CONFIG_DIR

# ── Los tres orígenes posibles. No es una lista abierta a propósito: «estimado»,
# «aproximado» o «de referencia» son justo las palabras con las que se cuela una
# cifra inventada.
MEDIDO = "medido"                 # viene de la Graph API, con periodo real
DEMOSTRACION = "demostración"     # dataset de ejemplo, etiquetado como tal
SIN_DATOS = "sin_datos"           # hoy no se puede calcular, y se dice por qué
ORIGENES = (MEDIDO, DEMOSTRACION, SIN_DATOS)

# Valor de reserva por si config/umbrales.json falta o está roto. Nadie se queda
# sin panel por un JSON mal escrito, pero tampoco se relaja el criterio solo:
# la reserva es la política estricta, no la permisiva.
_RESERVA = {
    "n_minimo": 3,
    "etiquetas": {
        "medido": "medido",
        "demostración": "demostración",
        "sin_datos": "todavía no lo sé",
    },
    "textos": {
        "sin_procedencia": "sin procedencia",
        "sin_calendario": "Todavía no hay nada en el calendario.",
        "sin_ideas": "Todavía no hay ideas guardadas.",
        "sin_inspiraciones": "Todavía no hay inspiraciones.",
        "sin_aprendizajes": "Todavía no hay aprendizajes.",
        "apunte_manual": "apunte tuyo, sin evidencia",
        "sin_retencion": ("La Graph API no da el tiempo de visualización de un "
                          "reel, así que la retención no se puede calcular."),
        "unidad_evidencia": "aprendizajes con muestra, periodo y método",
        "sin_evidencia": ("Solo hay {n} aprendizaje(s) con muestra, periodo y "
                          "método (hacen falta {minimo}): todavía no hay nada "
                          "concluyente."),
        "periodo_seguidores": "últimos 30 días",
        "periodo_alcance": "últimos 28 días",
        "periodo_publicaciones": "histórico de la cuenta",
    },
    "validador": {"magnitud_minima": 100},
}

_cache_umbrales: dict | None = None


def _funde(base: dict, encima) -> dict:
    """Copia de `base` con lo de `encima` puesto por arriba.

    Solo se aceptan claves que YA existan en la reserva: así una errata en el
    JSON (`magnitud_minma`) no entra en silencio y se queda sin efecto sin que
    nadie se entere. Las claves que empiezan por «_» son comentarios del propio
    archivo y no son configuración."""
    out = dict(base)
    for k, v in (encima or {}).items():
        if str(k).startswith("_") or k not in out:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _funde(out[k], v)
        else:
            out[k] = v
    return out


def _carga_umbrales_content_os() -> dict:
    """Lee la sección «content_os» de config/umbrales.json sobre la reserva."""
    global _cache_umbrales
    if _cache_umbrales is None:
        leido = {}
        try:
            f = CONFIG_DIR / "umbrales.json"
            if f.is_file():
                leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("content_os") or {}
        except Exception:
            leido = {}                    # un JSON roto no tumba el panel
        _cache_umbrales = _funde(_RESERVA, leido)
    return _cache_umbrales


def umbrales(extra=None) -> dict:
    """Los umbrales vigentes de Content OS: reserva + archivo + lo que pises tú."""
    base = _carga_umbrales_content_os()
    return _funde(base, extra) if extra else dict(base)


# NO HAY «recarga_umbrales()» AQUÍ, Y ES A PROPÓSITO (02/08/2026).
# Se escribió una, copiando el patrón de skills/instagram/analisis.py:93. Un
# analisis de codigo muerto la delato: no la llamaba nadie... y la de analisis.py
# TAMPOCO. O sea que se copio un patron que ya estaba muerto, y asi es como una
# funcion inutil se reproduce por el codigo. Si algun dia hace falta recargar sin
# reiniciar, se escribe entonces y con quien la use delante.


# ────────────────────────────────────────────────────────────── el sobre
def dato(valor, origen: str, periodo=None, delta=None, n=None, aviso: str = "") -> dict:
    """Envuelve una cifra con su procedencia.

    `origen` tiene que ser uno de ORIGENES. Se valida AQUÍ y se lanza
    `ValueError` en vez de dejarlo pasar: si el sobre miente sobre su propio
    origen, todo lo que hay río abajo (el chip del HUD, la auditoría del
    payload) miente con él, y encima con cara de estar verificado."""
    if origen not in ORIGENES:
        raise ValueError(
            f"origen {origen!r} no válido; usa uno de {ORIGENES}. "
            "Una cifra sin procedencia no se envuelve: se deja fuera o se "
            "declara sin_datos con su motivo.")
    return {"valor": valor, "origen": origen, "periodo": periodo,
            "delta": delta, "n": n, "aviso": aviso}


# TAMPOCO HAY «etiqueta(origen)», Y TAMBIEN ES A PROPOSITO (02/08/2026).
# Se escribio para traducir un origen a su nombre de cara al usuario leyendo
# umbrales.json. No la llamaba nadie, y al mirar por que se vio que sobraba: las
# etiquetas VIAJAN DENTRO DEL PAYLOAD (el diccionario `etiquetas`) y quien las
# pinta es cosMarca() en el HUD. Traducirlas tambien aqui seria tener el mismo
# texto en dos sitios, que es como empiezan las incoherencias que nadie entiende
# seis meses despues. Si algun dia hace falta la etiqueta en el backend, se lee
# de umbrales() en el momento y ya.


# ──────────────────────────────────────────── el cinturón para el texto del LLM
# Un número «grande», con decimales, con separador de millares o con % es casi
# siempre una MÉTRICA. Un entero pequeño («3 golpes», «2 segundos», «5 pasos»)
# es casi siempre estructura del guion. Por eso la frontera es la magnitud y la
# forma, no la mera presencia de dígitos: censurar «3 golpes» rompería el
# generador sin ganar nada.
_NUMERO = re.compile(r"(?<![\w.,])([+-]?\d[\d.,]*\d|\d)\s*(%|K|M)?", re.IGNORECASE)


def _analiza(tok: str) -> tuple[float, bool, bool]:
    """(valor, ¿lleva decimal?, ¿lleva separador de millares?).

    Se lee en español: la coma es el decimal y el punto los millares. «12.840»
    son doce mil ochocientos cuarenta, no doce con ochenta y cuatro."""
    t = tok.lstrip("+-")
    decimal = millares = False
    if "," in t:
        ent, _, dec = t.rpartition(",")
        millares = "." in ent
        ent = ent.replace(".", "")
        decimal = bool(dec)
        num = f"{ent or '0'}.{dec or '0'}"
    elif "." in t:
        partes = t.split(".")
        if partes[0] and all(len(p) == 3 for p in partes[1:]):
            millares, num = True, t.replace(".", "")
        else:
            decimal, num = True, partes[0] + "." + "".join(partes[1:])
    else:
        num = t
    try:
        return float(num), decimal, millares
    except ValueError:
        return 0.0, decimal, millares


def _permitidas(permitidas) -> list[float]:
    vals = []
    for p in permitidas or ():
        try:
            vals.append(float(p) if not isinstance(p, str) else _analiza(p)[0])
        except (TypeError, ValueError):
            pass
    return vals


# Alias interno: el parámetro público de las dos funciones de abajo se llama
# «umbrales» (es lo que se lee bien desde fuera) y taparía a la función.
_umbrales_vigentes = umbrales


def cifras_no_fundamentadas(texto: str, permitidas=(), umbrales=None) -> list[str]:
    """Las cifras del texto que NO estaban en la entrada y parecen una métrica."""
    u = umbrales or _umbrales_vigentes()
    minimo = float((u.get("validador") or {}).get("magnitud_minima", 100))
    buenas = _permitidas(permitidas)
    fuera = []
    for m in _NUMERO.finditer(texto or ""):
        tok, sufijo = m.group(1), (m.group(2) or "")
        valor, decimal, millares = _analiza(tok)
        if any(abs(valor - b) < 1e-9 for b in buenas):
            continue                       # venía en los datos: es legítima
        if sufijo or decimal or millares or valor >= minimo:
            fuera.append(tok + (f" {sufijo}" if sufijo else ""))
    return fuera


def sin_cifras_inventadas(texto: str, permitidas=(), umbrales=None) -> bool:
    """True si el texto no trae ninguna cifra que no viniera en la entrada.

    El prompt ya se lo PIDE al modelo (REGLA INVIOLABLE, `llm.py`). Esto lo
    COMPRUEBA. Un asistente que se inventa números es peor que uno que no
    contesta: con el que no contesta buscas el dato, y con este te lo crees."""
    return not cifras_no_fundamentadas(texto, permitidas, umbrales=umbrales)
