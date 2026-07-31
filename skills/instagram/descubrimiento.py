# -*- coding: utf-8 -*-
"""DESCUBRIR COMPETIDORES — la parte que NO toca Instagram.

El descubrimiento y la validación son dos cosas distintas a propósito:

  · DESCUBRIR es amplio y difuso. Se busca por internet —rankings del sector,
    listados, artículos, directorios— porque de lo que se trata es de no
    dejarse a nadie fuera. Aquí sobran candidatos malos: se filtran después.
  · VALIDAR es exacto. Cada candidato pasa por la API oficial de Meta. Si
    responde, es una cuenta profesional real y tenemos sus cifras de verdad.
    Si no responde, se descarta DICIENDO POR QUÉ.

Ninguna cuenta entra en un informe sin que Meta la haya confirmado. Ni una
estimación, ni un nombre sacado de un titular que nadie ha comprobado.

Aquí no se raspa Instagram: se leen resultados de búsqueda, que es texto público
de páginas web, y se sacan de ahí NOMBRES DE CUENTA. Los datos vienen luego, y
vienen de Meta.

Todo este módulo es determinista salvo la llamada al buscador: con los mismos
resultados web salen los mismos candidatos, en el mismo orden.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

# ══════════════════════════════════════════════════════════════════════════════
#  1. QUÉ ES ESTA CUENTA — el nicho, deducido de lo que publica
# ══════════════════════════════════════════════════════════════════════════════
# No se le pregunta al usuario «¿cuál es tu nicho?» y ya. Se mira lo que publica:
# las palabras que repite en sus pies y los hashtags que usa. Lo que él haya
# rellenado en su perfil pesa MÁS, porque lo sabe él mejor que nadie, pero si no
# ha rellenado nada la herramienta no se queda parada.

# Palabras que aparecen en cualquier pie y no dicen nada del nicho.
_VACIAS = {
    "para", "como", "esto", "eso", "con", "por", "una", "uno", "los", "las",
    "del", "que", "mas", "muy", "todo", "todos", "toda", "cuando", "donde",
    "porque", "pero", "sin", "sobre", "entre", "hasta", "desde", "cada", "este",
    "esta", "estos", "estas", "hay", "ser", "estar", "tener", "hacer", "puedes",
    "puede", "vamos", "aqui", "asi", "ahora", "hoy", "dia", "dias", "ano", "anos",
    "nuevo", "nueva", "mejor", "mejores", "gratis", "link", "bio", "comenta",
    "sigueme", "guarda", "comparte", "video", "reel", "parte", "the", "and",
    "you", "your", "for", "with", "this", "that", "from", "new", "best", "how",
}
_HASHTAG = re.compile(r"#(\w{3,30})", re.UNICODE)


def _normaliza(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s#]", " ", t)


def deduce_nicho(medios: list[dict], perfil: dict | None = None,
                 top: int = 8) -> dict:
    """De qué va esta cuenta, según lo que publica y lo que su dueño haya dicho.

    Devuelve los términos con los que luego se sale a buscar competidores. Si el
    usuario ha rellenado su perfil, sus palabras van PRIMERO: nadie describe su
    negocio mejor que quien lo lleva.
    """
    perfil = perfil or {}
    suyas: list[str] = []
    for clave in ("nicho", "propuesta_valor"):
        v = str(perfil.get(clave) or "").strip()
        if v:
            suyas += [w for w in _normaliza(v).split() if len(w) > 3 and w not in _VACIAS]
    for v in (perfil.get("subtemas") or []):
        suyas += [w for w in _normaliza(str(v)).split() if len(w) > 3 and w not in _VACIAS]

    palabras, etiquetas = Counter(), Counter()
    for m in medios:
        cap = m.get("caption") or ""
        for h in _HASHTAG.findall(cap):
            etiquetas[_normaliza(h).strip()] += 1
        for w in _normaliza(_HASHTAG.sub(" ", cap)).split():
            if len(w) > 3 and w not in _VACIAS and not w.isdigit():
                palabras[w] += 1

    # Una palabra que sale en UNA sola publicación no describe la cuenta.
    minimo = 2 if len(medios) >= 4 else 1
    frecuentes = [w for w, n in palabras.most_common(40) if n >= minimo]

    terminos, vistos = [], set()
    for w in suyas + frecuentes:
        if w not in vistos:
            vistos.add(w)
            terminos.append(w)

    productos = []
    for p in ((perfil.get("negocio") or {}).get("productos") or []):
        nombre = p.get("nombre") if isinstance(p, dict) else str(p)
        if nombre:
            productos.append(str(nombre).strip())

    return {
        "terminos": terminos[:top],
        "hashtags": [h for h, _ in etiquetas.most_common(10)],
        "productos": productos[:5],
        "declarado": str(perfil.get("nicho") or "").strip(),
        "de_su_perfil": bool(suyas),
        "publicaciones_miradas": len(medios),
        "confianza": ("alta" if suyas and len(medios) >= 5 else
                      "media" if suyas or len(medios) >= 5 else "baja"),
        "aviso": ("" if suyas else
                  "El nicho está deducido solo de tus pies de publicación. Si "
                  "rellenas «nicho» y «subtemas» en tu perfil, la búsqueda de "
                  "competidores afina mucho más."),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  2. LAS CONSULTAS — cómo se busca a la competencia
# ══════════════════════════════════════════════════════════════════════════════
# La gente no publica listas de "competidores de X". Publica rankings, listados
# de cuentas a seguir, comparativas y artículos de sector. Esas son las páginas
# donde aparecen varios nombres de cuenta juntos, que es justo lo que hace falta.
_PLANTILLAS = [
    'mejores cuentas de instagram de {t}',
    'cuentas de instagram que seguir sobre {t}',
    '{t} instagram creadores referentes',
    'instagram.com {t} perfil',
]
_PLANTILLAS_PRODUCTO = [
    '"{p}" instagram cuenta',
    'quien vende {p} instagram',
]


def consultas(nicho: dict, extra: list[str] | None = None, maximo: int = 8) -> list[str]:
    """Las búsquedas que se van a lanzar. Deterministas: mismo nicho, mismas."""
    terminos = list(nicho.get("terminos") or [])
    declarado = (nicho.get("declarado") or "").strip()
    # Si él ha declarado su nicho, esa frase manda y va SOLA: pegarle detrás las
    # palabras deducidas daba consultas como «cocina sin gluten cocina gluten»,
    # que es la misma búsqueda escrita dos veces y con peores resultados.
    base = declarado or " ".join(terminos[:3]).strip()
    out: list[str] = []
    if base:
        out += [p.format(t=base) for p in _PLANTILLAS]
    # y un par de búsquedas más estrechas con los términos sueltos
    sueltos = [t for t in terminos[:3] if t and t.lower() not in base.lower()]
    for t in sueltos[:2]:
        out.append(_PLANTILLAS[0].format(t=t))
    for p in (nicho.get("productos") or [])[:2]:
        out += [q.format(p=p) for q in _PLANTILLAS_PRODUCTO]
    for e in (extra or []):
        if e.strip():
            out.append(e.strip())
    limpio, vistos = [], set()
    for q in out:
        q = " ".join(q.split())
        if q and q.lower() not in vistos:
            vistos.add(q.lower())
            limpio.append(q)
    return limpio[:maximo]


# ══════════════════════════════════════════════════════════════════════════════
#  3. SACAR NOMBRES DE CUENTA DE LOS RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════
# Dos formas: enlaces a instagram.com/usuario y arrobas sueltas en el texto. Hay
# que filtrar bastante: instagram.com/p/ es una publicación, /explore/ es una
# sección, y "@gmail" no es una cuenta.
_URL_IG = re.compile(
    r"instagram\.com/(?!p/|reel/|reels/|tv/|stories/|explore/|accounts/|directory/)"
    r"([A-Za-z0-9._]{2,30})", re.IGNORECASE)
_ARROBA = re.compile(r"(?<![\w.])@([A-Za-z0-9._]{3,30})")
# Cuentas de la propia plataforma y correos disfrazados de usuario.
_NO_SON_CUENTAS = {
    "instagram", "explore", "accounts", "about", "developer", "legal", "privacy",
    "help", "meta", "facebook", "creators", "business", "shop", "gmail", "hotmail",
    "outlook", "yahoo", "icloud", "email", "correo",
}


def candidatos(resultados: list[dict], excluir: list[str] | None = None,
               maximo: int = 25) -> list[dict]:
    """Nombres de cuenta que aparecen en los resultados, de más citado a menos.

    Que una cuenta salga en VARIAS páginas distintas es la mejor señal de que es
    del sector: significa que más de una fuente la considera referente. Por eso
    se ordena por número de fuentes, no por posición en el buscador.
    """
    fuera = {str(x).lstrip("@").lower() for x in (excluir or [])} | _NO_SON_CUENTAS
    hallados: dict[str, dict] = {}
    for r in resultados:
        texto = " ".join(str(r.get(k) or "") for k in ("title", "snippet", "url"))
        origen = str(r.get("url") or "")
        vistos_aqui = set()
        for rx in (_URL_IG, _ARROBA):
            for m in rx.finditer(texto):
                u = m.group(1).strip(".").lower()
                if (len(u) < 3 or u in fuera or u in vistos_aqui
                        or u.isdigit() or "." in u and u.split(".")[-1] in
                        ("com", "es", "net", "org", "io")):
                    continue
                vistos_aqui.add(u)
                d = hallados.setdefault(u, {"usuario": u, "veces": 0, "fuentes": []})
                d["veces"] += 1
                if origen and origen not in d["fuentes"]:
                    d["fuentes"].append(origen)
    salida = sorted(hallados.values(),
                    key=lambda d: (-len(d["fuentes"]), -d["veces"], d["usuario"]))
    return salida[:maximo]


# ══════════════════════════════════════════════════════════════════════════════
#  4. ¿ESTE CANDIDATO ES DE VERDAD DE MI SECTOR?
# ══════════════════════════════════════════════════════════════════════════════
# Que una cuenta salga en un ranking no significa que compita contigo. Se cruza
# lo que publica con tus términos, y se mira su tamaño: compararte con alguien
# de tu liga dice mucho más que compararte con una cuenta de cuatro millones.
def pertinencia(perfil_ajeno: dict, nicho: dict, seguidores_propios: int = 0,
                min_coincidencias: int = 1) -> dict:
    """Cuánto se parece esta cuenta a la tuya, con el porqué escrito."""
    terminos = {t for t in (nicho.get("terminos") or []) if len(t) > 3}
    etiquetas = {h for h in (nicho.get("hashtags") or [])}
    texto = _normaliza(" ".join(
        [perfil_ajeno.get("bio", "")]
        + [m.get("caption", "") for m in (perfil_ajeno.get("mejores") or [])]))
    palabras = set(texto.split())
    coinciden = sorted((terminos | etiquetas) & palabras)

    seg = perfil_ajeno.get("seguidores") or 0
    liga = "sin referencia"
    if seguidores_propios and seg:
        razon = seg / seguidores_propios
        liga = ("tu liga" if 0.2 <= razon <= 5
                else "mucho más grande" if razon > 5 else "mucho más pequeña")

    return {
        "encaja": len(coinciden) >= min_coincidencias,
        "coincidencias": coinciden,
        "liga": liga,
        "por_que": (f"comparte {len(coinciden)} tema(s) contigo: "
                    + ", ".join(coinciden[:5]) if coinciden else
                    "no se le ha encontrado ningún tema en común con tu cuenta"),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  5. CUENTAS QUE LA API NO VE — lo que aportas tú
# ══════════════════════════════════════════════════════════════════════════════
# Una cuenta personal no la puede consultar nadie por la API. Tú sí puedes
# mirarla y apuntar los números. Se guardan con su fecha y MARCADOS como
# aportados, nunca mezclados con los verificados: dentro de tres meses tienes
# que poder saber qué parte era exacta y qué parte era una foto de un día.
_CAMPOS_MANUALES = ("seguidores", "seguidos", "publicaciones",
                    "me_gusta", "comentarios", "reproducciones")


def ficha_manual(usuario: str, datos: dict, cuando: str = "") -> dict:
    """Una cuenta apuntada a mano, con la trazabilidad puesta."""
    limpio = {}
    for k in _CAMPOS_MANUALES:
        v = datos.get(k)
        if isinstance(v, (int, float)):
            limpio[k] = int(v)
    return {
        "usuario": str(usuario).lstrip("@").strip().lower(),
        "hay": bool(limpio),
        "fuente": "aportado",
        "verificado": False,
        "cuando": cuando,
        "seguidores": limpio.get("seguidores", 0),
        "seguidos": limpio.get("seguidos"),
        "publicaciones_totales": limpio.get("publicaciones", 0),
        "med_me_gusta": limpio.get("me_gusta", 0),
        "med_comentarios": limpio.get("comentarios", 0),
        "med_reproducciones": limpio.get("reproducciones"),
        "analizadas": 0,
        "formatos": [],
        "mejores": [],
        "aviso": ("Datos que has apuntado tú mirando la cuenta, no verificados "
                  "por la API: son una foto de ese día, no una media."),
    }
