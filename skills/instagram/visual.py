# -*- coding: utf-8 -*-
"""QUÉ SALE EN LOS VÍDEOS — y qué de eso funciona.

Hasta aquí el análisis miraba TEXTO: pies, ganchos, hashtags. Pero un reel es
una imagen, y media decisión editorial está ahí: si sale una persona o el
producto solo, si hay texto en la portada, si es exterior o estudio, si es
primer plano o plano general.

El reparto de trabajo es el mismo de siempre:

  · El MODELO mira la portada y rellena una ficha de atributos. Eso es
    describir, que es lo único que un modelo hace bien aquí.
  · El CÓDIGO cruza esos atributos con las reproducciones y saca qué funciona.
    Contar y comparar no se le pide a un modelo.

Y las mismas reglas de honestidad: mediana en vez de media, cada conclusión con
su n, y por debajo del mínimo se dice «pocos datos» en lugar de sentar cátedra.
Con dos reels no se demuestra que «el primer plano funciona».
"""
from __future__ import annotations

import json
import re
import statistics

N_MINIMO = 3          # por debajo de esto no se concluye nada

# ══════════════════════════════════════════════════════════════════════════════
#  1. LA FICHA QUE SE LE PIDE AL MODELO
# ══════════════════════════════════════════════════════════════════════════════
# Atributos elegidos por dos criterios: que se vean en una portada sin
# ambigüedad, y que sean DECISIONES que se puedan repetir al grabar. «Sale el
# producto» es accionable; «tiene buena estética» no.
#
# Cada atributo dice además lo fiable que es. La cantidad de personas se ve; el
# género aparente es una estimación del modelo y va marcada como tal, porque
# actuar sobre una estimación creyendo que es un dato es cómo salen los informes
# que no valen nada.
ATRIBUTOS = {
    "personas": {"valores": ["ninguna", "una", "dos", "grupo"],
                 "pregunta": "cuántas personas se ven", "fiable": "alta"},
    "genero_aparente": {"valores": ["no aplica", "hombre", "mujer", "mixto"],
                        "pregunta": "género aparente de quien sale, si se ve",
                        "fiable": "baja"},
    "producto": {"valores": ["no", "de fondo", "protagonista"],
                 "pregunta": "si se ve el producto y con qué peso", "fiable": "alta"},
    "texto_en_portada": {"valores": ["no", "poco", "mucho"],
                         "pregunta": "cuánto texto lleva incrustado", "fiable": "alta"},
    "escenario": {"valores": ["exterior", "interior", "estudio", "no se aprecia"],
                  "pregunta": "dónde está grabado", "fiable": "media"},
    "plano": {"valores": ["primer plano", "medio", "general", "detalle"],
              "pregunta": "tipo de plano", "fiable": "media"},
    "accion": {"valores": ["estático", "deporte o movimiento", "hablando a cámara",
                           "proceso o fabricación"],
               "pregunta": "qué está pasando", "fiable": "media"},
}

_ETIQUETAS = {
    "personas": "Cuánta gente sale",
    "genero_aparente": "Género aparente (estimado)",
    "producto": "El producto en pantalla",
    "texto_en_portada": "Texto incrustado",
    "escenario": "Dónde está grabado",
    "plano": "Tipo de plano",
    "accion": "Qué está pasando",
}


def prompt_ficha(caption: str = "") -> str:
    """Lo que se le pide al modelo por cada portada. Cerrado a propósito.

    Se le dan las opciones y solo puede elegir entre ellas: en cuanto se le deja
    describir libre, cada reel sale con palabras distintas y luego no hay nada
    que agrupar. Y se le pide que diga «no se aprecia» cuando no lo vea, que es
    la respuesta que casi nunca dan los modelos si no se les exige."""
    campos = "\n".join(
        f'  "{k}": una de [{", ".join(v["valores"])}]   // {v["pregunta"]}'
        for k, v in ATRIBUTOS.items())
    extra = f"\n\nPie de la publicación (contexto): {caption[:300]}" if caption else ""
    return (
        "Mira la portada de este reel y rellena la ficha. Responde SOLO con un "
        "JSON con estas claves y ningún texto más:\n\n{\n" + campos + "\n}\n\n"
        "Reglas: elige siempre una de las opciones dadas, literalmente. Si algo "
        "no se aprecia con claridad, usa la opción más prudente («ninguna», "
        "«no», «no se aprecia»). No adivines: es preferible un «no se aprecia» "
        "que un dato inventado." + extra)


def lee_ficha(respuesta: str) -> dict:
    """Saca la ficha de lo que conteste el modelo, y descarta lo que no encaje.

    Un modelo devuelve el JSON envuelto en explicaciones la mitad de las veces, y
    se inventa valores que no estaban en la lista la otra mitad. Lo que no sea
    una opción válida se tira: mejor un hueco que un dato que nadie ha visto."""
    txt = (respuesta or "").strip()
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if not m:
        return {}
    try:
        crudo = json.loads(m.group(0))
    except Exception:
        return {}
    ficha = {}
    for k, spec in ATRIBUTOS.items():
        v = str(crudo.get(k, "")).strip().lower()
        if v in spec["valores"]:
            ficha[k] = v
    return ficha


# ══════════════════════════════════════════════════════════════════════════════
#  2. EL CRUCE — qué atributo va con más reproducciones
# ══════════════════════════════════════════════════════════════════════════════
def _mediana(vals) -> float:
    v = [x for x in vals if isinstance(x, (int, float))]
    return round(statistics.median(v), 1) if v else 0.0


def _rendimiento(m: dict):
    v = m.get("view_count")
    return v if isinstance(v, (int, float)) else (m.get("like_count") or 0)


def cruza(medios: list[dict], minimo: int = N_MINIMO) -> dict:
    """Para cada atributo, qué valor rinde más — con su n y su aviso.

    `medios` son publicaciones con su ficha visual en la clave «visual».
    """
    con_ficha = [m for m in medios if (m.get("visual") or {})]
    base = _mediana([_rendimiento(m) for m in con_ficha])
    hay_cifras = any(_rendimiento(m) for m in con_ficha)
    bloques = []
    for attr, spec in ATRIBUTOS.items():
        por_valor: dict[str, list] = {}
        for m in con_ficha:
            v = (m.get("visual") or {}).get(attr)
            if v:
                por_valor.setdefault(v, []).append(_rendimiento(m))
        if not por_valor:
            continue
        filas = [{"valor": v, "n": len(r), "rendimiento": _mediana(r),
                  "concluyente": len(r) >= minimo,
                  # cuánto por encima o por debajo de la mediana de la cuenta
                  "vs_mediana": (round(_mediana(r) / base, 2) if base else None)}
                 for v, r in por_valor.items()]
        filas.sort(key=lambda d: (-d["concluyente"], -d["rendimiento"]))
        solidas = [f for f in filas if f["concluyente"]]
        bloques.append({
            "atributo": attr,
            "titulo": _ETIQUETAS.get(attr, attr),
            "fiabilidad": spec["fiable"],
            "filas": filas,
            "mejor": solidas[0]["valor"] if (solidas and hay_cifras) else None,
            "nota": ("" if (solidas and hay_cifras) else
                     ("Sin cifras de reproducciones no se puede decir qué funciona "
                      "mejor, solo qué usa." if not hay_cifras else
                      f"Ningún valor llega a {minimo} publicaciones: son casos "
                      f"sueltos, no un patrón.")),
        })
    return {
        "hay": bool(bloques),
        "analizadas": len(con_ficha),
        "sin_ficha": len(medios) - len(con_ficha),
        "base": base,
        "bloques": bloques,
        "metodo": ("La ficha de cada portada la rellena el modelo eligiendo entre "
                   "opciones cerradas; el cruce con las reproducciones lo hace el "
                   "código, con mediana y con el n a la vista. Un valor con menos "
                   f"de {minimo} publicaciones detrás sale marcado: es una "
                   "coincidencia, no un patrón."),
        "aviso_genero": ("El género aparente es una ESTIMACIÓN del modelo mirando "
                         "una imagen, no un dato. Sirve para orientarse, no para "
                         "decidir a quién contratas."),
    }


def cruza_md(c: dict) -> str:
    """El cruce en Markdown (norma de la casa: los informes son .md)."""
    if not c.get("hay"):
        return "## Qué sale en los vídeos\n\nNo hay portadas analizadas todavía.\n"
    p = ["## Qué sale en los vídeos, y qué funciona", "",
         f"Sobre {c['analizadas']} portadas"
         + (f" ({c['sin_ficha']} sin analizar)" if c["sin_ficha"] else "") + ".",
         "", f"_{c['metodo']}_", ""]
    for b in c["bloques"]:
        p += [f"### {b['titulo']}"
              + (f"  ·  fiabilidad {b['fiabilidad']}" if b["fiabilidad"] != "alta" else ""), ""]
        if b["atributo"] == "genero_aparente":
            p += [f"_{c['aviso_genero']}_", ""]
        if b["mejor"]:
            p += [f"Lo que mejor le funciona: **{b['mejor']}**", ""]
        p += ["| Valor | Publicaciones | Reproducciones (mediana) | Frente a su media |",
              "|---|---|---|---|"]
        for f in b["filas"]:
            marca = "" if f["concluyente"] else " ⚠"
            vs = f"{f['vs_mediana']}×" if f["vs_mediana"] is not None else "—"
            p.append(f"| {f['valor']} | {f['n']}{marca} | {f['rendimiento']:g} | {vs} |")
        p += [""]
        if b["nota"]:
            p += [f"_{b['nota']}_", ""]
    return "\n".join(p)


# ══════════════════════════════════════════════════════════════════════════════
#  3. MIRAR LAS PORTADAS DE VERDAD
# ══════════════════════════════════════════════════════════════════════════════
# Con un modelo de visión en local (Ollama) esto no cuesta nada y no sale de tu
# equipo, que con imágenes de gente importa. Si no hay ninguno instalado NO se
# improvisa con el modelo de texto: se dice que falta y se explica cómo ponerlo.
#
# Familias que ven imágenes. Se compara por prefijo porque cada instalación las
# tiene con una etiqueta distinta (llava:7b, llava:13b-v1.6...).
FAMILIAS_VISION = ("llava", "bakllava", "llama3.2-vision", "llama3.2v",
                   "qwen2-vl", "qwen2.5vl", "qwen2.5-vl", "moondream",
                   "minicpm-v", "gemma3", "granite3.2-vision", "mistral-small3")


def es_de_vision(nombre: str) -> bool:
    n = (nombre or "").lower()
    return any(n.startswith(f) for f in FAMILIAS_VISION)


def elige_modelo(disponibles: list[str], preferido: str = "") -> str:
    """El modelo con el que se van a mirar las portadas.

    Si el usuario ha elegido uno, manda el suyo — aunque no esté en la lista de
    familias conocidas, porque salen modelos nuevos cada mes y no voy a impedirle
    usar uno solo porque yo no lo conozca."""
    if preferido:
        return preferido
    for m in disponibles:
        if es_de_vision(m):
            return m
    return ""


async def _descarga(url: str, timeout: float = 20.0) -> bytes:
    from backend.core import net
    r = await net.client().get(url, timeout=timeout)
    return r.content if getattr(r, "status_code", 0) == 200 else b""


async def ficha_de_portada(url: str, caption: str, modelo: str,
                           base_ollama: str, timeout: float = 90.0) -> dict:
    """Descarga la portada, se la enseña al modelo y devuelve la ficha."""
    import base64
    from backend.core import net
    img = await _descarga(url)
    if not img:
        return {}
    r = await net.client().post(
        f"{base_ollama.rstrip('/')}/api/generate",
        json={"model": modelo, "prompt": prompt_ficha(caption), "stream": False,
              "images": [base64.b64encode(img).decode()],
              "options": {"temperature": 0}, "keep_alive": "10m"},
        timeout=timeout)
    if getattr(r, "status_code", 0) != 200:
        return {}
    return lee_ficha((r.json() or {}).get("response", ""))


async def mira_portadas(medios: list[dict], settings, maximo: int = 12) -> dict:
    """Rellena la ficha visual de las portadas que se puedan mirar.

    Con tope: mirar 300 portadas con un modelo local tarda una eternidad y no
    aporta nada frente a mirar las 12 más recientes. Lo que se deja fuera se
    dice, no se calla."""
    con_portada = [m for m in medios
                   if (m.get("media_url") or m.get("thumbnail_url"))]
    if not con_portada:
        return {"hay": False, "motivo": "sin_portadas", "miradas": 0,
                "texto": "Las publicaciones no traen portada. Si tu versión de la "
                         "API no devuelve «media_url», este bloque no se puede hacer."}
    base = str(settings.get("ollama_url", "http://localhost:11434"))
    preferido = str(settings.get("vision_model", "") or "").strip()
    disponibles: list[str] = []
    try:
        from backend.core import net
        r = await net.client().get(f"{base.rstrip('/')}/api/tags", timeout=5.0)
        if getattr(r, "status_code", 0) == 200:
            disponibles = [m.get("name", "") for m in (r.json() or {}).get("models", [])]
    except Exception:
        disponibles = []
    modelo = elige_modelo(disponibles, preferido)
    if not modelo:
        return {"hay": False, "motivo": "sin_modelo", "miradas": 0,
                "texto": "No hay ningún modelo de visión instalado, así que no "
                         "puedo mirar las portadas. Con Ollama arrancado: "
                         "«ollama pull llava» y listo — corre en tu equipo y las "
                         "imágenes no salen de aquí."}
    miradas, fallos = 0, 0
    for m in con_portada[:maximo]:
        try:
            f = await ficha_de_portada(
                m.get("media_url") or m.get("thumbnail_url"),
                m.get("caption", ""), modelo, base)
        except Exception:
            f = {}
        if f:
            m["visual"] = f
            miradas += 1
        else:
            fallos += 1
    return {
        "hay": miradas > 0, "motivo": "", "modelo": modelo,
        "miradas": miradas, "fallidas": fallos,
        "sin_mirar": max(0, len(con_portada) - maximo),
        "texto": (f"Miradas {miradas} portadas con «{modelo}», en tu equipo."
                  + (f" {fallos} no se han podido leer." if fallos else "")
                  + (f" Quedan {len(con_portada) - maximo} sin mirar (tope por "
                     f"tiempo)." if len(con_portada) > maximo else "")),
    }
