"""Minion Instagram Reels — análisis de comentarios, dudas, leads e ideas.

Qué hace: baja con la Graph API los comentarios y los insights de TUS reels
(nada de scraping: tu cuenta, tu token) y los interpreta para sacar cuatro
cosas — de qué habla la gente, qué pregunta, quién quiere comprar y qué grabar
después.

LA PIEZA CLAVE ES EL PERFIL. El mismo comentario significa cosas distintas
según quién publique: «¿y con niños?» es una objeción para una cuenta de viajes
en pareja y es EL tema para una de crianza. Por eso el análisis no se hace «en
abstracto»: se hace con el contexto completo de quien tiene la cuenta —su
nicho, sus idiomas, su familia, su tono, sus productos y sus palabras-CTA— que
vive en data/instagram/perfiles.json y lo rellena cada usuario desde ⚙ o
hablando con nexus. NO hay ningún dato de nadie escrito en este código.

El trabajo sucio (paginación completa, replies anidados, throttling y backoff
ante rate limits) lo hace scripts/ig.py contra la Graph API oficial. Este minion
decide QUÉ bajar y convierte el JSON en respuestas útiles.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL = {
    "name": "Instagram Reels",
    "description": ("Analiza los comentarios e insights de tus reels de Instagram: "
                    "temas y sentimiento, dudas repetidas, leads interesados e ideas "
                    "de contenido. Incluye el perfil de contexto del usuario."),
    "intents": {
        "ig_perfil_ver": "enseñar el perfil de contexto del USUARIO (su nicho, su negocio)",
        "ig_perfil_set": "rellenar un campo del perfil del usuario",
        "ig_descubrir": "deducir el nicho del usuario y BUSCAR competidores por internet",
        "ig_manual": "apuntar a mano las cifras de una cuenta que la API no puede ver",
        "ig_competencia": "analizar la cuenta de Instagram DE OTRA PERSONA o marca "
                          "(seguidores, reproducciones, me gusta, comentarios, qué "
                          "publica) y compararla con la del usuario. Úsalo siempre "
                          "que den un nombre de cuenta ajena, con arroba o sin ella",
        "ig_analizar": "analizar a fondo los reels DEL PROPIO USUARIO: comentarios, "
                       "leads, sentimiento, dudas e ideas",
        "ig_listar": "listar las últimas publicaciones del propio usuario",
        "ig_conversion": "apuntar cuántos DM, clics y ventas salieron de un reel",
        "ig_estado": "decir si Instagram está configurado y qué falta",
    },
    "patterns": {
        # Orden: primero lo específico (perfil, estado), luego lo amplio (analizar).
        # El «(?!\s+de\s+\w)» es para que «el perfil de instagram DE WABIKS» no se
        # confunda con «mi perfil de instagram»: uno es de otro, el otro es tuyo.
        "ig_perfil_ver": r"(?:mi\s+)?perfil\s+(?:de\s+)?(?:instagram|ig)\b(?!\s+de\s+\w)"
                         r"|qu[eé]\s+sabes\s+de\s+mi\s+(?:cuenta|perfil)\s+de\s+instagram"
                         r"|contexto\s+(?:de\s+)?(?:mi\s+)?instagram",
        "ig_perfil_set": r"(?:configura|rellena|edita|actualiza|pon|cambia)\s+"
                         r"(?:mi\s+)?(?:perfil|contexto|ficha)\s+(?:de\s+)?(?:instagram|ig)\b"
                         r"|(?:en\s+)?instagram\s+(?:mi\s+)?(?P<campo>nicho|idiomas?|tono|"
                         r"objetivo|hijos?|familia|p[uú]blico|productos?|triggers?|"
                         r"palabras[\s-]cta)\s*(?:=|:|es|son)\s*(?P<valor>.+)",
        "ig_estado": r"(?:estado|c[oó]mo\s+(?:est[aá]|va))\s+(?:de\s+|el\s+|la\s+)?"
                     r"(?:conexi[oó]n\s+(?:de|con)\s+)?instagram\b"
                     r"|(?:est[aá]|tengo)\s+(?:configurad[oa])\s+(?:lo\s+de\s+)?instagram",
        # Descubrimiento: sale a buscar competidores por internet. Va lo primero
        # porque «busca competidores» no es «analiza la cuenta @x».
        "ig_descubrir": r"(?:busca|encuentra|b[uú]scame|descubre|investiga)\s+"
                        r"(?:me\s+)?(?:a\s+)?(?:mis?\s+|la\s+|los\s+)?"
                        r"(?:competencia|competidor\w*|rival\w*|cuentas?\s+(?:como|"
                        r"parecidas?|similares?)|referentes?)"
                        r"|(?:qui[eé]n(?:es)?\s+(?:es|son)\s+mi\s+competencia)"
                        r"|(?:analiza|cual\s+es|deduce)\s+mi\s+nicho"
                        r"|(?:conecta|configura|arranca)\s+mi\s+cuenta\s+de\s+instagram",
        # Cuentas que la API no ve: los números los aporta él.
        "ig_manual": r"(?:apunta|anota|registra|guarda)\s+(?:que\s+)?(?:de\s+)?"
                     r"(?:la\s+)?cuenta\s+(?P<cuenta>@?[\w.]+)\s*:?\s*(?P<cifras>.+)",
        # Competencia: cuentas que NO administras. Va antes que ig_listar y que
        # ig_analizar, porque «analiza la cuenta @x» no es «analiza mis reels».
        # Competencia: cuentas que NO administras.
        # Tres formas de nombrarlas, porque la gente no escribe siempre la arroba:
        #   1) con @              → «analiza @wabiks», «compárame con @a y @b»
        #   2) «cuenta/perfil de» → «analiza la cuenta de instagram de wabiks»
        #   3) comparación        → «compara mi cuenta con wabiks»
        # El fallo que tenía: solo aceptaba la 1. «analiza la cuenta de instagram
        # de wabiks» no casaba con nada, se iba al cerebro y contestaba cualquier
        # cosa. Los lookahead evitan comerse «analiza mis reels» y «mi nicho».
        "ig_competencia":
            r"(?:analiza|mira|revisa|estudia|compara|comp[aá]rame|comp[aá]ralo)\w*\s+"
            r"[^@\n]{0,40}?(?P<cuentas>@[\w.]{2,30}(?:\s*(?:,|y|vs\.?|contra)\s*@?[\w.]{2,30})*)"
            r"|(?:analiza|mira|revisa|estudia|examina)\w*\s+(?:la\s+|el\s+)?"
            r"(?:cuenta|perfil)\s+(?:de\s+)?(?:instagram\s+|ig\s+)?(?:de\s+)?"
            r"(?P<cuentas2>(?!mis?\b|nuestr|[uú]ltim)[\w.]{3,30})"
            r"|(?:compara|comp[aá]rame|comp[aá]ralo)\w*\s+(?:me\s+)?(?:mi\s+cuenta\s+)?"
            r"(?:con|contra|vs\.?)\s+(?:la\s+cuenta\s+(?:de\s+)?)?"
            r"(?P<cuentas3>(?!mis?\b)@?[\w.]{3,30}(?:\s*(?:,|y)\s*@?[\w.]{3,30})*)",
        # Analizar va ANTES que listar: «analiza mis reels» es analizarlos,
        # no enseñar la lista. Al revés, listar se lo comía.
        "ig_analizar": r"analiza(?:me)?\s+(?:mis?\s+)?(?:[uú]ltimos?\s+)?(?P<n2>\d+)?\s*"
                       r"(?:reels?|v[ií]deos?\s+de\s+instagram|publicaciones\s+de\s+instagram)"
                       r"|(?:qu[eé]\s+)?(?:comenta|dice|pregunta)\s+la\s+gente\s+"
                       r"(?:en|de)\s+mis\s+reels?"
                       r"|(?:saca|dame|extrae)\s+(?:los\s+)?(?:leads?|ideas?\s+de\s+contenido|"
                       r"dudas?|preguntas?\s+frecuentes)\s+(?:de\s+)?(?:mis\s+)?reels?",
        "ig_listar": r"(?:lista|list[aá]me|dame|ens[eé][ñn]ame|cu[aá]les\s+son)\s+"
                     r"(?:mis\s+)?(?:[uú]ltimos?\s+)?(?P<n>\d+)?\s*(?:reels?|publicaciones)\b"
                     r"|mis\s+(?:[uú]ltimos\s+)?reels?\b(?!\s*(?:qu[eé]|c[oó]mo))",
        # Va antes que ig_analizar: «apunta … del reel» no es «analiza».
        "ig_conversion": r"(?:apunta|registra|anota|guarda)\s+(?:que\s+)?"
                         r"(?:en\s+|de\s+|del\s+)?(?:el\s+)?reel\s+(?P<rid>[\w.-]+)?\s*:?\s*"
                         r"(?P<datos>.*(?:dm|mensajes?|clics?|clicks?|ventas?|abiert)\w*.*)",
    },
}

_AQUI = Path(__file__).resolve().parent
_SCRIPT = _AQUI / "scripts" / "ig.py"


# ══════════════════════════════════════════════════════════════════════════════
#  EL PERFIL DEL USUARIO — el contexto con el que se interpreta todo
# ══════════════════════════════════════════════════════════════════════════════
# Plantilla VACÍA a propósito. Cada quien mete lo suyo; nexus no trae el perfil
# de nadie de fábrica. Los campos están pensados para que el análisis entienda
# a la persona detrás de la cuenta, no solo su temática.
PERFIL_VACIO: dict = {
    "id": "",                        # identificador interno (p. ej. el usuario de IG)
    "cuenta": {
        "usuario": "",               # @tuusuario
        "nombre_publico": "",
        "business_account_id": "",    # el ID numérico de la cuenta Business/Creator
        "pais": "",
        "zona_horaria": "",
    },
    # Umbrales propios de ESTA cuenta: lo que pongas aquí pisa a
    # config/umbrales.json, y lo que no, se hereda. Una cuenta de recetas y una
    # de consultoría no tienen el mismo listón de guardados.
    # Ej.: {"lecturas": {"guardados_pct_reach_fuerte": 5.0}}
    "umbrales": {},
    # ── de qué va la cuenta ──────────────────────────────────────────────────
    "nicho": "",                     # «cocina sin gluten», «finanzas para autónomos»…
    "subtemas": [],
    "propuesta_valor": "",           # qué se lleva quien te sigue
    "referentes": [],                # cuentas parecidas, para contrastar ángulos
    # ── con quién hablas ─────────────────────────────────────────────────────
    "publico": {
        "descripcion": "",
        "edad": "",
        "paises": [],
        "situacion": "",             # «madres primerizas», «opositores», «pymes»…
        "dolores": [],               # lo que les quita el sueño
        "objeciones_tipicas": [],
    },
    # ── idiomas: en qué te escriben y en qué contestas ───────────────────────
    "idiomas": {
        "comentarios": [],           # ["es", "en"] — en qué idiomas te comentan
        "respuesta": "es",           # en qué idioma quieres el análisis y los guiones
        "variante": "",              # «España», «México», «neutro»…
    },
    # ── QUIÉN ERES ───────────────────────────────────────────────────────────
    # Esto no es relleno: cambia la lectura de los comentarios y, sobre todo,
    # las ideas de contenido. Una cuenta cuyo autor tiene un niño de 3 años
    # puede convertir «¿y si no tengo tiempo?» en un reel que nadie más puede
    # grabar igual. Todo opcional: lo que no se rellena, no se usa.
    "personal": {
        "nombre": "",
        "profesion": "",
        "ubicacion": "",
        "situacion_familiar": "",    # «pareja», «monoparental», «vivo solo»…
        "hijos": [],                 # [{"nombre": "", "edad": "", "notas": ""}]
        "mascotas": [],
        "idiomas_que_habla": [],
        "aficiones": [],
        "historia_personal": "",     # el relato que conecta con tu audiencia
        "temas_que_no_toca": [],     # límites: lo que NO quieres que se proponga
    },
    # ── cómo suenas ──────────────────────────────────────────────────────────
    "tono": {
        "estilo": "",                # «cercano y directo», «técnico», «con humor»…
        "trato": "tu",               # tu | usted
        "emojis": "pocos",           # muchos | pocos | ninguno
        "muletillas": [],
        "palabras_prohibidas": [],
    },
    # ── a qué juegas ─────────────────────────────────────────────────────────
    "negocio": {
        "objetivo": "",              # vender curso | captar clientes | marca | comunidad
        "productos": [],             # [{"nombre","precio","enlace","para_quien"}]
        "lead_magnets": [],          # [{"nombre","palabra_cta","reel"}]
        "web": "",
        "metrica_que_importa": "",   # «leads», «guardados», «ventas»…
    },
    # Palabras-imán propias («comenta GUÍA y te la mando»). Se suman a las que
    # el script trae de serie para contar leads.
    # Competidores que pones TÚ: van primero y no se descartan nunca.
    "competencia": [],
    # Búsquedas extra para el descubrimiento, si las tuyas son mejores.
    "busquedas_extra": [],
    "triggers": [],
    "notas": "",
}

_CAMPOS_SIMPLES = {           # atajos para «instagram nicho: cocina sin gluten»
    "nicho": ("nicho",),
    "idioma": ("idiomas", "respuesta"),
    "idiomas": ("idiomas", "comentarios"),
    "tono": ("tono", "estilo"),
    "objetivo": ("negocio", "objetivo"),
    "publico": ("publico", "descripcion"),
    "público": ("publico", "descripcion"),
    "productos": ("negocio", "productos"),
    "triggers": ("triggers",),
    "palabras-cta": ("triggers",),
    "palabras cta": ("triggers",),
    "hijos": ("personal", "hijos"),
    "hijo": ("personal", "hijos"),
    "familia": ("personal", "situacion_familiar"),
}


def _dir_datos(ctx) -> Path:
    from backend.core.config import DATA_DIR
    d = Path(DATA_DIR) / "instagram"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _archivo_perfiles(ctx) -> Path:
    return _dir_datos(ctx) / "perfiles.json"


def cargar_perfiles(ctx) -> dict:
    f = _archivo_perfiles(ctx)
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(d, dict) and "perfiles" in d:
                return d
        except Exception:
            pass
    return {"activo": "", "perfiles": {}}


def guardar_perfiles(ctx, datos: dict) -> None:
    _archivo_perfiles(ctx).write_text(
        json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def perfil_activo(ctx) -> dict:
    """El perfil en uso. Si no hay ninguno, devuelve la plantilla vacía."""
    d = cargar_perfiles(ctx)
    pid = d.get("activo") or ""
    p = (d.get("perfiles") or {}).get(pid)
    if not isinstance(p, dict):
        p = json.loads(json.dumps(PERFIL_VACIO))
    return p


def guardar_perfil(ctx, perfil: dict) -> None:
    d = cargar_perfiles(ctx)
    pid = perfil.get("id") or (perfil.get("cuenta") or {}).get("usuario") or "principal"
    perfil["id"] = pid
    d.setdefault("perfiles", {})[pid] = perfil
    d["activo"] = pid
    guardar_perfiles(ctx, d)


def _vacio(v) -> bool:
    if isinstance(v, dict):
        return all(_vacio(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return len(v) == 0
    return not str(v or "").strip()


def campos_rellenos(perfil: dict) -> tuple[int, int]:
    """(rellenos, total) contando solo las hojas del perfil."""
    llenos = total = 0

    def _rec(v):
        nonlocal llenos, total
        if isinstance(v, dict):
            for x in v.values():
                _rec(x)
        else:
            total += 1
            if not _vacio(v):
                llenos += 1
    for k, v in perfil.items():
        if k != "id":
            _rec(v)
    return llenos, total


def tiene_contexto(perfil: dict) -> bool:
    """¿Ha rellenado el usuario ALGO de verdad?

    No basta con mirar si hay campos no vacíos: la plantilla ya trae tres
    preferencias puestas (idioma de respuesta, tuteo, emojis). Si el perfil es
    idéntico a la plantilla, contexto no hay ninguno."""
    def _iguales(a, b):
        if isinstance(a, dict) and isinstance(b, dict):
            return all(_iguales(a.get(k), b.get(k)) for k in set(a) | set(b))
        return a == b
    return not _iguales({k: v for k, v in perfil.items() if k != "id"},
                        {k: v for k, v in PERFIL_VACIO.items() if k != "id"})


def perfil_como_texto(perfil: dict) -> str:
    """El perfil en prosa, para meterlo en el prompt del análisis.

    Cadena vacía si no hay nada que contar: mejor que el modelo sepa que no
    tiene contexto a que se crea que sí porque le llega «trata de tú»."""
    if not tiene_contexto(perfil):
        return ""
    p, out = perfil, []
    c = p.get("cuenta") or {}
    if c.get("usuario"):
        out.append(f"Cuenta: @{c['usuario']}" + (f" ({c.get('nombre_publico')})"
                                                 if c.get("nombre_publico") else ""))
    if c.get("pais"):
        out.append(f"País de la cuenta: {c['pais']}")
    if p.get("nicho"):
        out.append(f"Nicho: {p['nicho']}")
    if p.get("subtemas"):
        out.append("Subtemas: " + ", ".join(map(str, p["subtemas"])))
    if p.get("propuesta_valor"):
        out.append(f"Propuesta de valor: {p['propuesta_valor']}")
    pu = p.get("publico") or {}
    if any(pu.values()):
        det = [pu.get("descripcion", ""), f"edad {pu['edad']}" if pu.get("edad") else "",
               "países: " + ", ".join(pu["paises"]) if pu.get("paises") else "",
               pu.get("situacion", "")]
        out.append("Público: " + "; ".join(x for x in det if x))
        if pu.get("dolores"):
            out.append("Lo que les preocupa: " + ", ".join(map(str, pu["dolores"])))
        if pu.get("objeciones_tipicas"):
            out.append("Objeciones típicas: " + ", ".join(map(str, pu["objeciones_tipicas"])))
    idi = p.get("idiomas") or {}
    if idi.get("comentarios"):
        out.append("Los comentarios llegan en: " + ", ".join(map(str, idi["comentarios"])))
    if idi.get("respuesta"):
        out.append(f"Responde y analiza en: {idi['respuesta']}"
                   + (f" ({idi['variante']})" if idi.get("variante") else ""))
    pe = p.get("personal") or {}
    trozos = []
    if pe.get("nombre"):
        trozos.append(f"se llama {pe['nombre']}")
    if pe.get("profesion"):
        trozos.append(f"es {pe['profesion']}")
    if pe.get("ubicacion"):
        trozos.append(f"vive en {pe['ubicacion']}")
    if pe.get("situacion_familiar"):
        trozos.append(pe["situacion_familiar"])
    for h in (pe.get("hijos") or []):
        if isinstance(h, dict):
            trozos.append("tiene un hijo/a" + (f" ({h.get('nombre','')}" if h.get("nombre") else "")
                          + (f", {h.get('edad')} años)" if h.get("edad")
                             else ")" if h.get("nombre") else ""))
        elif str(h).strip():
            trozos.append(f"tiene hijos: {h}")
    if pe.get("idiomas_que_habla"):
        trozos.append("habla " + ", ".join(map(str, pe["idiomas_que_habla"])))
    if pe.get("aficiones"):
        trozos.append("le gusta " + ", ".join(map(str, pe["aficiones"])))
    if trozos:
        out.append("Quién está detrás de la cuenta: " + "; ".join(trozos) + ".")
    if pe.get("historia_personal"):
        out.append(f"Su historia: {pe['historia_personal']}")
    if pe.get("temas_que_no_toca"):
        out.append("NO propongas contenido sobre: " + ", ".join(map(str, pe["temas_que_no_toca"])))
    to = p.get("tono") or {}
    if any(to.values()):
        out.append(f"Tono: {to.get('estilo','')} · trata de "
                   f"{'tú' if to.get('trato') == 'tu' else to.get('trato', 'tú')} · "
                   f"emojis: {to.get('emojis', 'pocos')}")
        if to.get("palabras_prohibidas"):
            out.append("Palabras que no usa: " + ", ".join(map(str, to["palabras_prohibidas"])))
    ne = p.get("negocio") or {}
    if ne.get("objetivo"):
        out.append(f"Objetivo de negocio: {ne['objetivo']}")
    for pr in (ne.get("productos") or []):
        if isinstance(pr, dict):
            out.append(f"Producto: {pr.get('nombre','')} — {pr.get('precio','')} "
                       f"para {pr.get('para_quien','')}")
    for lm in (ne.get("lead_magnets") or []):
        if isinstance(lm, dict):
            out.append(f"Lead magnet: «{lm.get('nombre','')}» se dispara con la palabra "
                       f"«{lm.get('palabra_cta','')}»")
    if ne.get("metrica_que_importa"):
        out.append(f"La métrica que le importa: {ne['metrica_que_importa']}")
    if p.get("triggers"):
        out.append("Palabras-CTA propias: " + ", ".join(map(str, p["triggers"])))
    if p.get("notas"):
        out.append(f"Notas: {p['notas']}")
    return "\n".join(f"- {x}" for x in out) if out else ""


# ══════════════════════════════════════════════════════════════════════════════
#  CREDENCIALES
# ══════════════════════════════════════════════════════════════════════════════
def credenciales(ctx) -> tuple[str, str]:
    """(token, business_account_id). Vacíos si no están puestos.

    El token se guarda como SECRETO de nexus (config/secrets.json, que no se
    sube a ningún repositorio y no sale por la API). El ID de la cuenta puede
    venir del ajuste o del propio perfil."""
    s = ctx.get("settings") if isinstance(ctx, dict) else None
    if s is None:
        from backend.core.config import settings as s          # type: ignore
    token = s.secret("ig_access_token") or ""
    # El MISMO número tenía dos nombres: la skill leía «ig_business_account_id» y
    # Content OS «ig_user_id». Quien rellenaba uno se quedaba sin el otro y la
    # herramienta decía «me falta el ID» teniéndolo puesto. Se acepta cualquiera.
    bid = (str(s.get("ig_business_account_id", "") or "").strip()
           or str(s.get("ig_user_id", "") or "").strip()
           or str((perfil_activo(ctx).get("cuenta") or {}).get("business_account_id") or "").strip())
    return token, bid


_COMO_CONSEGUIRLO = (
    "Para conectarlo hacen falta dos cosas, las dos de Meta:\n"
    "  1. Un TOKEN de la Graph API con permisos instagram_basic, "
    "instagram_manage_comments, instagram_manage_insights y pages_read_engagement.\n"
    "  2. El ID NUMÉRICO de tu cuenta Business/Creator (no el @usuario).\n"
    "Los pones en ⚙ → Instagram, o dime «guarda el token de instagram <valor>». "
    "Mientras tanto, puedes ir rellenando tu perfil: eso no necesita token."
)


def _falta(token: str, bid: str) -> str:
    faltan = []
    if not token:
        faltan.append("el token de acceso")
    if not bid:
        faltan.append("el ID de la cuenta")
    return (f"Todavía me falta {' y '.join(faltan)} para poder mirar tus reels.\n\n"
            + _COMO_CONSEGUIRLO)


# ══════════════════════════════════════════════════════════════════════════════
#  EJECUTAR EL SCRIPT
# ══════════════════════════════════════════════════════════════════════════════
async def ejecutar_ig(ctx, args: list[str], timeout: int = 180) -> tuple[bool, str]:
    """Lanza scripts/ig.py con las credenciales por variables de entorno.

    Por variables y no por línea de comandos a propósito: los argumentos de un
    proceso los ve cualquiera con el administrador de tareas, y ahí iría el
    token."""
    token, bid = credenciales(ctx)
    if not _SCRIPT.exists():
        return False, "No encuentro scripts/ig.py dentro de la skill."
    entorno = dict(os.environ)
    entorno.update({"INSTAGRAM_ACCESS_TOKEN": token,
                    "INSTAGRAM_BUSINESS_ACCOUNT_ID": bid,
                    "PYTHONUTF8": "1"})
    perfil = perfil_activo(ctx)
    if perfil.get("triggers"):
        entorno["IG_TRIGGERS"] = ",".join(str(x) for x in perfil["triggers"])

    def _corre():
        return subprocess.run([sys.executable, str(_SCRIPT), *args],
                              cwd=str(_AQUI), env=entorno, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    try:
        r = await asyncio.to_thread(_corre)
    except subprocess.TimeoutExpired:
        return False, ("La consulta a Instagram ha tardado demasiado. Prueba con menos "
                       "reels o vuelve a intentarlo en un rato.")
    except Exception as exc:                                    # noqa: BLE001
        return False, f"No he podido lanzar la consulta: {type(exc).__name__}"
    if r.returncode != 0:
        detalle = (r.stderr or r.stdout or "").strip().splitlines()
        return False, (detalle[-1][:300] if detalle else "Instagram ha devuelto un error.")
    return True, r.stdout


# ══════════════════════════════════════════════════════════════════════════════
#  EL PROMPT DEL ANÁLISIS — aquí es donde entra el contexto del usuario
# ══════════════════════════════════════════════════════════════════════════════
def prompt_analisis(perfil: dict, datos: str) -> str:
    contexto = perfil_como_texto(perfil) or (
        "- (el usuario todavía no ha rellenado su perfil: haz el análisis en general "
        "y avisa al final de que con el perfil relleno sería mucho más afinado)")
    idioma = ((perfil.get("idiomas") or {}).get("respuesta") or "español")
    return f"""Eres analista de contenido de Instagram. Te doy el CONTEXTO de quien
tiene la cuenta y los DATOS crudos de sus reels (comentarios ya etiquetados e
insights). Interpreta los datos A LA LUZ del contexto: el mismo comentario
significa cosas distintas según quién publique.

=== CONTEXTO DE LA CUENTA Y DE LA PERSONA ===
{contexto}

=== DATOS DE LOS REELS (JSON) ===
{datos}

=== QUÉ TIENES QUE DEVOLVER (en {idioma}) ===
1. TEMAS Y SENTIMIENTO. Agrupa los comentarios REALES por tema y da el % de
   positivo/neutral/negativo. EXCLUYE del sentimiento los que tengan
   is_from_owner=true (los escribió el dueño) y is_trigger=true (una palabra-CTA
   suelta no es una opinión). Cita comentarios literales; no inventes ninguno.

2. DUDAS REPETIDAS. Las preguntas agrupadas por parecido y ordenadas por
   frecuencia, con el número de veces que aparecen.

3. LEADS. Aquí la lógica se INVIERTE: los triggers SÍ cuentan, son la señal.
   Antes de contarlos, mira el caption de cada reel y busca el grupo de
   comentarios cortos casi idénticos: esa palabra es el gancho de ESE reel
   aunque no esté en la lista. Devuelve una tabla: usuario, comentario, reel,
   qué lo disparó y si es interés explícito o genérico. Sin repetir usuarios.

4. IDEAS DE CONTENIDO (lo más importante). Para cada idea: gancho concreto,
   formato, y QUÉ COMENTARIO la respalda. Aprovecha el contexto personal cuando
   encaje de verdad —si hay hijos, idiomas, profesión o una historia detrás, hay
   ángulos que solo esta persona puede grabar— pero sin forzarlo y respetando
   los temas que ha dicho que no toca. Ordena por impacto estimado.

Sé concreto y honesto: si los datos no dan para una conclusión, dilo. No cites
ningún comentario que no esté en el JSON.

Formato: Markdown bien estructurado, con encabezados y tablas donde toque — el
informe se guarda como archivo .md salvo que se haya pedido otro formato."""


# ══════════════════════════════════════════════════════════════════════════════
#  HANDLE
# ══════════════════════════════════════════════════════════════════════════════
async def handle(intent: str, text: str, match, ctx) -> dict:
    perfil = perfil_activo(ctx)
    token, bid = credenciales(ctx)

    # ── ESTADO ──────────────────────────────────────────────────────────────
    if intent == "ig_estado":
        llenos, total = campos_rellenos(perfil)
        lineas = [
            f"{'✔' if token else '✖'} Token de acceso: "
            + ("guardado" if token else "sin poner"),
            f"{'✔' if bid else '✖'} ID de la cuenta: " + (bid if bid else "sin poner"),
            f"{'✔' if llenos else '✖'} Perfil de contexto: {llenos} de {total} campos",
        ]
        pie = ("\n\nYa puedo analizar tus reels: dime «analiza mis últimos 3 reels»."
               if token and bid else "\n\n" + _COMO_CONSEGUIRLO)
        return {"reply": "📸 Instagram\n" + "\n".join(lineas) + pie}

    # ── VER EL PERFIL ───────────────────────────────────────────────────────
    if intent == "ig_perfil_ver":
        texto = perfil_como_texto(perfil)
        llenos, total = campos_rellenos(perfil)
        if not texto:
            return {"reply":
                    "Tu perfil de Instagram está vacío. Es lo que hace que el análisis "
                    "sea tuyo y no genérico: con el nicho, el público, los idiomas, tu "
                    "situación (profesión, familia, hijos si los hay) y tus productos, "
                    "las ideas de contenido salen a tu medida.\n\n"
                    "Puedes rellenarlo en ⚙ → Instagram, o a trozos hablando: "
                    "«instagram nicho: cocina sin gluten», «instagram idiomas: es, en», "
                    "«instagram objetivo: vender mi curso»."}
        return {"reply": f"📸 Tu perfil de Instagram ({llenos}/{total} campos):\n{texto}"}

    # ── EDITAR EL PERFIL POR CHAT ───────────────────────────────────────────
    if intent == "ig_perfil_set":
        gd = match.groupdict() if match else {}
        campo = (gd.get("campo") or "").strip().lower()
        valor = (gd.get("valor") or "").strip()
        if not campo or not valor:
            return {"reply":
                    "Dime qué campo y con qué valor. Por ejemplo:\n"
                    "  · «instagram nicho: finanzas para autónomos»\n"
                    "  · «instagram idiomas: es, en»\n"
                    "  · «instagram objetivo: vender mi curso»\n"
                    "  · «instagram hijos: Leo (3 años)»\n"
                    "El perfil completo, con todos los campos, se edita en ⚙ → Instagram."}
        ruta = _CAMPOS_SIMPLES.get(campo)
        if not ruta:
            return {"reply": f"No conozco el campo «{campo}». Los que entiendo por chat: "
                             + ", ".join(sorted(_CAMPOS_SIMPLES)) + "."}
        # listas separadas por comas para los campos que son lista
        destino = perfil
        for k in ruta[:-1]:
            destino = destino.setdefault(k, {})
        clave = ruta[-1]
        actual = destino.get(clave)
        if isinstance(actual, list) or clave in ("comentarios", "triggers", "hijos"):
            trozos = [x.strip() for x in re.split(r"[,;]| y ", valor) if x.strip()]
            if clave == "hijos":
                destino[clave] = [{"nombre": t.split("(")[0].strip(),
                                   "edad": (re.search(r"(\d+)", t).group(1)
                                            if re.search(r"(\d+)", t) else ""),
                                   "notas": ""} for t in trozos]
            else:
                destino[clave] = trozos
        else:
            destino[clave] = valor
        guardar_perfil(ctx, perfil)
        llenos, total = campos_rellenos(perfil)
        return {"reply": f"✔ Apuntado en tu perfil de Instagram: {campo} → {valor}\n"
                         f"Llevas {llenos} de {total} campos."}

    # Apuntar una cuenta a mano NO necesita conexión con Instagram: los números
    # los estás poniendo tú mirando el perfil. Estaba después del control de
    # credenciales, así que sin token te contestaba «me falta el token» a algo
    # que no lo usa para nada.
    # ── UNA CUENTA QUE LA API NO VE: los números los pones tú ────────────────
    if intent == "ig_manual":
        from datetime import datetime
        from . import descubrimiento as D

        gd = match.groupdict() if match else {}
        crudo = (gd.get("cifras") or "").lower()
        campos = {"seguidores": r"([\d.\s]+)\s*seguidor",
                  "seguidos": r"([\d.\s]+)\s*seguid[oa]s\b",
                  "publicaciones": r"([\d.\s]+)\s*publicacion",
                  "me_gusta": r"([\d.\s]+)\s*(?:me\s*gusta|likes?)",
                  "comentarios": r"([\d.\s]+)\s*comentario",
                  "reproducciones": r"([\d.\s]+)\s*(?:reproduccion|visualizacion|views?)"}
        datos = {}
        for k, rx in campos.items():
            m2 = re.search(rx, crudo)
            if m2:
                try:
                    datos[k] = int(re.sub(r"[^\d]", "", m2.group(1)))
                except ValueError:
                    pass
        if not datos:
            return {"reply": "No he pillado ninguna cifra. Dímelo así: «apunta la "
                             "cuenta @suusuario: 8000 seguidores, 300 me gusta, "
                             "20 comentarios»."}
        ficha = D.ficha_manual(gd.get("cuenta") or "", datos,
                               f"{datetime.now():%Y-%m-%d}")
        _guarda_manual(ctx, ficha)
        leidos = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in datos.items())
        return {"reply": f"Apuntado de @{ficha['usuario']} → {leidos}.\n"
                         "Va a las comparativas marcado como aportado por ti, no "
                         "como verificado por la API: es una foto de hoy, no una "
                         "media. Así dentro de tres meses sabrás qué parte era exacta."}

    # ── A PARTIR DE AQUÍ HACE FALTA CONEXIÓN ────────────────────────────────
    if not token or not bid:
        return {"reply": _falta(token, bid)}

    # ── LISTAR REELS ────────────────────────────────────────────────────────
    if intent == "ig_listar":
        n = (match.groupdict().get("n") if match else None) or "15"
        ok, salida = await ejecutar_ig(ctx, ["list", "--limit", str(min(int(n), 50))])
        if not ok:
            return {"reply": f"No he podido leer tus publicaciones. {salida}"}
        try:
            datos = json.loads(salida)
            items = datos if isinstance(datos, list) else datos.get("data", [])
        except Exception:
            return {"reply": "Instagram ha contestado algo que no he sabido leer."}
        if not items:
            return {"reply": "No veo publicaciones recientes en esa cuenta."}
        lineas = []
        for m in items[:20]:
            cap = (m.get("caption") or "").replace("\n", " ")[:60]
            lineas.append(f"  · {m.get('id','')} — {m.get('media_type','')} · "
                          f"{m.get('comments_count', 0)} comentarios · {cap}")
        return {"reply": f"📸 Tus {len(lineas)} publicaciones más recientes:\n"
                         + "\n".join(lineas)
                         + "\n\nDime «analiza mis últimos 3 reels» para entrar al detalle."}

    # ── DESCUBRIR COMPETIDORES (el onboarding) ──────────────────────────────
    if intent == "ig_descubrir":
        import shutil
        import tempfile
        from datetime import datetime
        from backend.core import websearch
        from . import analisis as A
        from . import descubrimiento as D

        # 1) MI CUENTA: qué publico yo
        salida_dir = Path(tempfile.mkdtemp(prefix="ig_desc_"))
        destino = salida_dir / "perfil.json"
        ok, err = await ejecutar_ig(ctx, ["perfil", "--recent", "25",
                                          "--out", str(destino)], timeout=300)
        if not ok or not destino.exists():
            shutil.rmtree(salida_dir, ignore_errors=True)
            return {"reply": f"No he podido leer tu propia cuenta. {err}"}
        mio = json.loads(destino.read_text(encoding="utf-8", errors="replace"))
        shutil.rmtree(salida_dir, ignore_errors=True)
        if mio.get("error"):
            return {"reply": f"No he podido leer tu propia cuenta: {mio['error']}"}

        medios = mio.get("media") or []
        nicho = D.deduce_nicho(medios, perfil)
        yo = A.perfil_publico(mio.get("username") or "tu cuenta", mio)

        # 2) BUSCAR por internet (esto no toca Instagram: son páginas web)
        preguntas = D.consultas(nicho, extra=[str(x) for x in (perfil.get("busquedas_extra") or [])])
        resultados = []
        for q in preguntas:
            try:
                resultados += await websearch.search(q, n=8)
            except Exception:
                continue
        propios = [mio.get("username") or "", (perfil.get("cuenta") or {}).get("usuario", "")]
        dados = [str(x) for x in (perfil.get("competencia") or [])]
        cands = D.candidatos(resultados, excluir=propios)
        # los que TÚ hayas puesto en tu perfil van primero y no se descartan
        orden = [{"usuario": str(x).lstrip("@").lower(), "veces": 99, "fuentes": ["tu perfil"]}
                 for x in dados] + [c for c in cands
                                    if c["usuario"] not in {str(x).lstrip("@").lower() for x in dados}]
        if not orden:
            return {"reply":
                    "No he encontrado ninguna cuenta buscando por internet.\n"
                    f"He buscado esto: {'; '.join(preguntas[:3])}…\n\n"
                    + (nicho["aviso"] or "Dime tú alguna cuenta: «analiza la cuenta @x».")}

        # 3) VALIDAR contra Meta: sin esto no entra nadie al informe
        a_validar = [c["usuario"] for c in orden[:12]]
        dir2 = Path(tempfile.mkdtemp(prefix="ig_val_"))
        dest2 = dir2 / "competencia.json"
        ok2, err2 = await ejecutar_ig(ctx, ["competencia", ",".join(a_validar),
                                            "--recent", "25", "--out", str(dest2)],
                                      timeout=900)
        if not ok2 or not dest2.exists():
            shutil.rmtree(dir2, ignore_errors=True)
            return {"reply": f"He encontrado candidatos pero no he podido validarlos. {err2}"}
        crudo = json.loads(dest2.read_text(encoding="utf-8", errors="replace"))
        shutil.rmtree(dir2, ignore_errors=True)

        # 4) FILTRAR por pertinencia y guardar
        validados, descartados = [], []
        for c in (crudo.get("cuentas") or []):
            pp = A.perfil_publico(c.get("usuario", ""), c.get("datos") or {})
            if not pp["hay"]:
                descartados.append({"usuario": pp["usuario"],
                                    "motivo": "la API no la puede consultar "
                                              "(¿cuenta personal o privada?)"})
                continue
            per = D.pertinencia(pp, nicho, yo.get("seguidores") or 0)
            pp["pertinencia"] = per
            (validados if per["encaja"] else descartados).append(
                pp if per["encaja"] else {"usuario": pp["usuario"],
                                          "motivo": per["por_que"]})
        comp = A.competencia(
            [{"usuario": v["usuario"],
              "datos": next((c.get("datos") for c in (crudo.get("cuentas") or [])
                             if c.get("usuario") == v["usuario"]), {})}
             for v in validados], yo if yo.get("hay") else None)
        radios = _radiografia_de(comp, crudo)
        radios += "\n" + await _visual_de(comp, crudo, ctx.get("settings"))
        pan = A.panel_competencia(comp)
        pan["descubrimiento"] = {"nicho": nicho, "consultas": preguntas,
                                 "candidatos": len(orden), "validados": len(validados),
                                 "descartados": descartados}
        _guarda_competencia(ctx, pan)
        _guarda_nicho(ctx, nicho)

        base = _dir_datos(ctx) / "informes"
        base.mkdir(parents=True, exist_ok=True)
        ruta = base / f"{datetime.now():%Y-%m-%d}-competencia.md"
        ruta.write_text(A.competencia_md(comp) + "\n" + radios, encoding="utf-8")

        lineas = [f"· @{v['usuario']}: {v['seguidores']:,} seguidores".replace(",", ".")
                  + f" — {v['pertinencia']['por_que'][:70]}" for v in validados[:8]]
        return {"reply":
                f"🔎 Tu nicho, deducido de tus {len(medios)} últimas publicaciones: "
                + (", ".join(nicho["terminos"][:5]) or "no he sacado nada claro")
                + f" (confianza {nicho['confianza']}).\n"
                + f"He buscado por internet y he encontrado {len(orden)} cuentas; "
                + f"Meta ha confirmado {len(validados)}.\n"
                + ("\n".join(lineas) if lineas else "· ninguna encaja con tu nicho")
                + (f"\n\nDescartadas ({len(descartados)}): "
                   + ", ".join(f"@{d['usuario']}" for d in descartados[:6])
                   if descartados else "")
                + (f"\n\n{nicho['aviso']}" if nicho["aviso"] else "")
                + "\n\nSi falta alguien: «analiza la cuenta @quien-sea». Si es una "
                  "cuenta personal, la API no la ve: «apunta la cuenta @quien-sea: "
                  "8000 seguidores, 300 me gusta, 20 comentarios»."
                  f"\nLo tienes en Reels → Competencia. Informe: {ruta.name}",
                "data": {"nicho": nicho, "validados": len(validados)}}

    # ── COMPETENCIA: cuentas que NO administras ─────────────────────────────
    if intent == "ig_competencia":
        import shutil
        import tempfile
        from datetime import datetime
        from backend.core.files_io import formato_pedido
        from . import analisis as A

        gd = match.groupdict() if match else {}
        crudo_cuentas = " ".join(str(gd.get(k) or "")
                                 for k in ("cuentas", "cuentas2", "cuentas3")).strip()
        usuarios = re.findall(r"@([\w.]+)", crudo_cuentas)
        if not usuarios and crudo_cuentas:
            # sin arroba: los nombres van sueltos, separados por comas o «y»
            usuarios = [x for x in re.split(r"[,\s]+|\by\b", crudo_cuentas)
                        if x and x.lower() not in ("y", "de", "la", "el", "con")]
        if not usuarios:
            usuarios = [str(x).lstrip("@") for x in (perfil.get("competencia") or [])]
        if not usuarios:
            return {"reply":
                    "Dime a quién miro: «analiza la cuenta @sucuenta» (puedes darme "
                    "varias: «@una y @otra»).\n\n"
                    "Aviso de lo que se puede y lo que no: de una cuenta que no "
                    "administras la API oficial deja ver seguidores, reproducciones, "
                    "me gusta y CUÁNTOS comentarios. El TEXTO de sus comentarios no, "
                    "así que de sus reels no se puede sacar si le hablan bien o mal. "
                    "Sus compartidos, guardados y alcance tampoco: son privados. Eso "
                    "no me lo invento ni lo saco por scraping."}
        usuarios = usuarios[:6]

        salida_dir = Path(tempfile.mkdtemp(prefix="igcomp_"))
        destino = salida_dir / "competencia.json"
        ok, err = await ejecutar_ig(ctx, ["competencia", ",".join(usuarios),
                                          "--recent", "25", "--out", str(destino)],
                                    timeout=600)
        try:
            if not ok or not destino.exists():
                return {"reply": f"No he podido consultar esas cuentas. {err}"}
            crudo = json.loads(destino.read_text(encoding="utf-8", errors="replace"))
        finally:
            if not destino.exists():
                shutil.rmtree(salida_dir, ignore_errors=True)

        # Si algún nombre no existía tal cual, se busca por internet y se
        # reintenta con el que sí existe. Antes se limitaba a preguntar «¿querías
        # decir…?» y te dejaba el trabajo a ti.
        resueltos: dict[str, str] = {}
        fallidos = [(c.get("usuario") or "") for c in (crudo.get("cuentas") or [])
                    if (c.get("datos") or {}).get("error")]
        if fallidos:
            reintentar: dict[str, str] = {}
            for u in fallidos[:3]:
                for cand in await _busca_la_cuenta(u):
                    if cand.lower() != u.lower():
                        reintentar[cand] = u
                        break
            if reintentar:
                d2 = Path(tempfile.mkdtemp(prefix="igcomp2_"))
                dest2 = d2 / "competencia.json"
                ok2, _ = await ejecutar_ig(
                    ctx, ["competencia", ",".join(reintentar), "--recent", "25",
                          "--out", str(dest2)], timeout=600)
                if ok2 and dest2.exists():
                    extra = json.loads(dest2.read_text(encoding="utf-8", errors="replace"))
                    buenas = [c for c in (extra.get("cuentas") or [])
                              if not (c.get("datos") or {}).get("error")]
                    ok_nombres = {(c.get("usuario") or "").lower() for c in buenas}
                    # fuera los nombres que no existían, dentro los que sí
                    crudo["cuentas"] = [c for c in (crudo.get("cuentas") or [])
                                        if not ((c.get("datos") or {}).get("error")
                                                and reintentar.get(c.get("usuario"), "") == ""
                                                or (c.get("usuario") or "") in
                                                {v for k, v in reintentar.items()
                                                 if k.lower() in ok_nombres})] + buenas
                    for k, v in reintentar.items():
                        if k.lower() in ok_nombres:
                            resueltos[v] = k
                shutil.rmtree(d2, ignore_errors=True)

        prop = crudo.get("propia") or {}
        propia = None
        if prop and not prop.get("error"):
            propia = A.perfil_publico(prop.get("username") or "tu cuenta", prop)
        comp = A.competencia(crudo.get("cuentas") or [], propia)
        radios = _radiografia_de(comp, crudo)
        radios += "\n" + await _visual_de(comp, crudo, ctx.get("settings"))
        shutil.rmtree(salida_dir, ignore_errors=True)

        _guarda_competencia(ctx, A.panel_competencia(comp))
        ext = formato_pedido(text)                # .md salvo que pidas otra cosa
        base = _dir_datos(ctx) / "informes"
        base.mkdir(parents=True, exist_ok=True)
        ruta = base / (f"{datetime.now():%Y-%m-%d}-competencia"
                       f"{ext if ext in ('.md', '.txt') else '.md'}")
        ruta.write_text(A.competencia_md(comp) + "\n" + radios, encoding="utf-8")

        lineas = []
        for c in comp["cuentas"]:
            rep_txt = ("reproducciones no constan" if c["med_reproducciones"] is None
                       else f"{int(c['med_reproducciones']):,} reproducciones".replace(",", "."))
            lineas.append(f"· @{c['usuario']}: {c['seguidores']:,} seguidores".replace(",", ".")
                          + f", {rep_txt} de mediana, {int(c['med_me_gusta'])} me gusta, "
                          + f"{int(c['med_comentarios'])} comentarios")
        for f in comp["fallidas"]:
            lineas.append(f"· @{f['usuario']}: no se ha podido consultar "
                          f"(¿cuenta personal o privada?)")
        for original, real in resueltos.items():
            lineas.insert(0, f"· «{original}» no existe tal cual: he buscado por "
                             f"internet y la cuenta es @{real}.")
        pistas = await _quisiste_decir(
            [f for f in (comp.get("fallidas") or [])
             if f.get("usuario") not in resueltos])
        if pistas:
            for u, opciones in pistas.items():
                lineas.append(f"  De «{u}» no he encontrado la cuenta. ¿Es "
                              + " o ".join(f"@{o}" for o in opciones) + "?")
        peor = comp["brechas"][0] if comp["brechas"] else None
        cierre = (f"\n\nDonde más te sacan ventaja: {peor['que']} "
                  f"({peor['diferencia']:+}% frente a la mediana de ellos)."
                  if peor and peor["diferencia"] < 0 else "")
        return {"reply":
                f"📊 Comparado con {len(comp['cuentas'])} cuenta(s), en solo lectura.\n"
                + "\n".join(lineas) + cierre
                + "\n\nDe sus cuentas NO se puede ver el texto de sus comentarios "
                  "(o sea, ni su sentimiento), ni sus compartidos, guardados o "
                  "alcance: son privados y la API no los da.\n"
                + f"Informe: {ruta.name}\nLo tienes desglosado en Reels → Competencia.",
                "data": {"informe": str(ruta)}}

    # ── APUNTAR EL EMBUDO (lo que Instagram no sabe) ────────────────────────
    if intent == "ig_conversion":
        gd = match.groupdict() if match else {}
        crudo = (gd.get("datos") or text or "").lower()
        datos = {}
        for campo, rx in _CAMPOS_EMBUDO:
            m2 = re.search(rx, crudo)
            if m2:
                datos[campo] = int(m2.group(1))
        if not datos:
            return {"reply": "No he pillado ninguna cifra. Dímelo así: «apunta en el "
                             "reel 17… 40 dm enviados, 31 abiertos, 12 clics y 2 ventas»."}
        rid = (gd.get("rid") or "").strip()
        if not rid:
            ult = _ultimo_reel_analizado(ctx)
            if not ult:
                return {"reply": "Dime de qué reel: «apunta en el reel <id>…». Todavía "
                                 "no hay ningún análisis del que deducirlo."}
            rid = ult
        fila = _apunta_conversion(ctx, rid, datos)
        leidos = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in fila.items())
        return {"reply": f"Apuntado en el reel {rid} → {leidos}.\n"
                         "Entra en el análisis y ya lo verás en Conversión, con su "
                         "tasa paso a paso. Lo que no me des, seguirá como «no consta»: "
                         "no me lo invento."}

    # ── ANALIZAR ────────────────────────────────────────────────────────────
    if intent == "ig_analizar":
        import shutil
        import tempfile
        from datetime import datetime
        from backend.core.files_io import formato_pedido
        from . import analisis as A                      # motor determinista

        gd = match.groupdict() if match else {}
        n = max(1, min(int(gd.get("n2") or 3), 10))
        salida_dir = Path(tempfile.mkdtemp(prefix="ig_"))
        ok, salida = await ejecutar_ig(
            ctx, ["bundle", "--recent", str(n), "--out", str(salida_dir)], timeout=900)
        if not ok:
            shutil.rmtree(salida_dir, ignore_errors=True)
            return {"reply": f"No he podido bajar los datos de tus reels. {salida}"}

        # Los umbrales de ESTA cuenta (lo que no pise, lo hereda del archivo).
        umbrales = A.cargar_umbrales(perfil.get("umbrales") or None)
        keywords = [str(x) for x in (perfil.get("triggers") or [])]
        for lm in ((perfil.get("negocio") or {}).get("lead_magnets") or []):
            if isinstance(lm, dict) and lm.get("palabra_cta"):
                keywords.append(str(lm["palabra_cta"]))
        historial = _historial(ctx)
        informes, resumen, paneles = [], [], []
        try:
            for f in sorted(salida_dir.glob("*.json")):
                if f.name == "index.json":
                    continue
                bundle = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                media = bundle.get("media") or {}
                # la palabra-imán DE ESTE reel puede estar solo en su caption
                kws = keywords + _palabras_gancho(bundle, keywords, umbrales)
                clas = A.clasificar(bundle.get("flat") or [], kws, umbrales)
                met = A.metricas(bundle, clas, umbrales)
                ld = A.leads(clas)
                sust = clas["cestas"]["sustantivo"]

                # LO ÚNICO que hace el modelo: interpretar. Contar, no.
                sent, ideas = await _cualitativo(perfil, sust, A.dudas(sust, umbrales=umbrales), media)

                ins = bundle.get("insights") or {}
                actual = {"reach": ins.get("reach"), "total_interactions": ins.get("total_interactions"),
                          "saved": ins.get("saved"), "shares": ins.get("shares"),
                          "comentarios_audiencia": met["comentarios_audiencia"]}
                # UN solo contexto para las DOS salidas: el .md que se archiva y
                # el panel que se pinta en el HUD. Si se calcularan por separado
                # acabarian diciendo cosas distintas del mismo reel.
                du = A.dudas(sust, umbrales=umbrales)
                obj = A.objeciones(sust)
                ctx_inf = {
                    "media": media, "metricas": met, "clasificacion": clas, "leads": ld,
                    "sentimiento": A.sentimiento(sent, len(sust), umbrales) if sent else None,
                    "odio": A.cuenta_odio(sust), "dudas": du, "objeciones": obj,
                    "cola": A.cola_editorial(du, obj, ld.get("calientes"), umbrales),
                    "conversion": A.conversion(
                        ld["unicos"], _registro_conversion(ctx).get(str(media.get("id", "")))),
                    "retencion": A.retencion(bundle), "distribucion": A.distribucion(bundle),
                    "benchmark": A.benchmark(actual, historial), "ideas": ideas}
                md = A.informe_md(ctx_inf)
                paneles.append(A.panel(ctx_inf, umbrales))
                ext = formato_pedido(text)           # .md salvo que pidas otra cosa
                base = _dir_datos(ctx) / "informes"
                base.mkdir(parents=True, exist_ok=True)
                nombre = f"{datetime.now():%Y-%m-%d}-reel-{media.get('id', 'sin-id')}"
                ruta = base / f"{nombre}{ext if ext in ('.md', '.txt') else '.md'}"
                ruta.write_text(md, encoding="utf-8")
                (base / f"{nombre}-leads.csv").write_text(A.leads_csv(ld), encoding="utf-8")
                informes.append(ruta)
                historial.append(actual)
                resumen.append(
                    f"· {(media.get('caption') or media.get('id', ''))[:44]}… → "
                    f"{ld['unicos']} leads, {clas['conteo']['sustantivo']} comentarios con "
                    f"contenido, {clas['total']} en total"
                    + ("" if clas["cuadra"] else "  ⚠ los números NO cuadran"))
            _guarda_historial(ctx, historial)
            _guarda_panel(ctx, paneles)
        finally:
            shutil.rmtree(salida_dir, ignore_errors=True)

        if not informes:
            return {"reply": "He podido conectar, pero no he sacado datos de esos reels."}
        aviso = ("" if tiene_contexto(perfil) else
                 "\n\n💡 Con tu perfil relleno (nicho, público, idiomas, tu situación) las "
                 "ideas de contenido salen a tu medida. Dime «configura mi perfil de instagram».")
        return {"reply":
                f"📸 Analizados {len(informes)} reel(s), en modo solo lectura — no he "
                f"publicado ni respondido nada.\n" + "\n".join(resumen)
                + f"\n\nInforme: {informes[0].parent}\n"
                + "\n".join(f"  · {r.name}" for r in informes)
                + "\n  · …-leads.csv (para cruzarlo con tu CRM)"
                + "\n\nLo tienes desglosado en la pestaña «Reels»." + aviso,
                "data": {"informes": [str(r) for r in informes], "paneles": paneles}}

    return {"reply": "No he entendido qué quieres de tus reels. Prueba con «analiza mis "
                     "últimos 3 reels», «mis reels» o «perfil de instagram»."}


# ══════════════════════════════════════════════════════════════════════════════
#  APOYOS DEL ANÁLISIS
# ══════════════════════════════════════════════════════════════════════════════
def _historial(ctx) -> list:
    """Las métricas de los reels ya analizados: sin esto no hay con qué comparar
    y «alcance bajo» se queda en un adjetivo."""
    f = _dir_datos(ctx) / "historial.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            pass
    return []


_CAMPOS_EMBUDO = [
    ("dm_enviados", r"(\d+)\s*(?:dm|mensajes?)\s*(?:enviad|mandad)"),
    ("dm_abiertos", r"(\d+)\s*(?:dm|mensajes?)?\s*abiert"),
    ("clics", r"(\d+)\s*(?:clics?|clicks?)"),
    ("ventas", r"(\d+)\s*(?:ventas?|compras?|convertid)"),
]


async def _busca_la_cuenta(nombre: str, maximo: int = 3) -> list[str]:
    """De un nombre suelto al nombre de cuenta real, buscando por internet.

    Cuando dices «analiza la cuenta de lamarca», ese nombre casi nunca es el
    usuario exacto: las marcas llevan sufijos («lamarcaco», «lamarca_oficial»).
    Así que se busca el nombre en la web, se sacan los enlaces a instagram.com
    que aparezcan y se devuelven ordenados por en cuántas páginas salen — que es
    la señal de cuál es la cuenta buena y cuál un reel donde la mencionan."""
    from backend.core import websearch
    from . import descubrimiento as D
    n = (nombre or "").strip().lstrip("@")
    if not n:
        return []
    res = []
    for q in (f"{n} instagram", f'"{n}" instagram cuenta oficial'):
        try:
            res += await websearch.search(q, n=8)
        except Exception:
            continue
    raiz = n.lower()[:5]
    fuera = {"reel", "reels", "explore", "stories"}
    cerca, otros = [], []
    for c in D.candidatos(res, maximo=12):
        u = c["usuario"]
        if u in fuera:
            continue
        (cerca if raiz and raiz in u else otros).append(u)
    return (cerca + otros)[:maximo]


async def _quisiste_decir(fallidas: list[dict]) -> dict:
    """Cuando un nombre de cuenta no existe, buscar el que sí.

    Las marcas casi nunca tienen el nombre a secas: escribes «lamarca» y la
    cuenta es «@lamarcaco». La API contesta «no se puede consultar» y parece que
    la herramienta está rota, cuando solo falta un sufijo. Se busca el nombre por
    internet y se ofrecen las cuentas parecidas que aparezcan."""
    from backend.core import websearch
    from . import descubrimiento as D
    sugerencias: dict[str, list[str]] = {}
    for f in fallidas[:3]:
        u = (f.get("usuario") or "").strip()
        if not u:
            continue
        try:
            res = await websearch.search(f"{u} instagram", n=8)
        except Exception:
            continue
        cerca = [c["usuario"] for c in D.candidatos(res, maximo=6)
                 if c["usuario"] != u.lower() and u.lower()[:5] in c["usuario"]]
        if cerca:
            sugerencias[u] = cerca[:3]
    return sugerencias


async def _visual_de(comp: dict, crudo: dict, settings) -> str:
    """Mira las portadas de cada cuenta validada y cruza con sus cifras.

    Va DESPUÉS de la radiografía porque tarda: cada portada es una inferencia
    local. Si no hay modelo de visión, cada cuenta se queda con el motivo escrito
    en vez de con un bloque vacío que nadie entiende."""
    from . import visual as V
    trozos = []
    for c in comp.get("cuentas", []):
        datos = next((x.get("datos") for x in (crudo.get("cuentas") or [])
                      if (x.get("usuario") or "").lower() == c["usuario"].lower()), None)
        medios = (datos or {}).get("media") or []
        if not medios:
            continue
        estado = await V.mira_portadas(medios, settings)
        c["visual_estado"] = estado
        if not estado["hay"]:
            continue
        c["visual"] = V.cruza(medios)
        trozos.append(V.cruza_md(c["visual"]))
    return "\n".join(trozos)


def _radiografia_de(comp: dict, crudo: dict) -> str:
    """Añade a cada cuenta validada la anatomía de lo que publica.

    Se hace aquí, sobre los medios que ya se han bajado, para no volver a
    llamar a la API: la radiografía sale del MISMO caption y las MISMAS cifras
    que ya están en la comparativa."""
    from . import inteligencia as I
    trozos = []
    for c in comp.get("cuentas", []):
        datos = next((x.get("datos") for x in (crudo.get("cuentas") or [])
                      if (x.get("usuario") or "").lower() == c["usuario"].lower()), None)
        medios = (datos or {}).get("media") or []
        if not medios:
            continue
        c["radiografia"] = I.radiografia(c, medios)
        trozos.append(I.radiografia_md(c["radiografia"]))
    return "\n".join(trozos)


def _guarda_nicho(ctx, nicho: dict) -> None:
    (_dir_datos(ctx) / "nicho.json").write_text(
        json.dumps({"cuando": _ahora_iso(), "nicho": nicho},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def _guarda_manual(ctx, ficha: dict) -> None:
    """Las cuentas que la API no ve, apuntadas a mano. Se guarda el historico
    completo: cada foto con su fecha, sin pisar la anterior."""
    f = _dir_datos(ctx) / "cuentas_manuales.json"
    todo = {}
    if f.exists():
        try:
            todo = json.loads(f.read_text(encoding="utf-8")) or {}
        except Exception:
            todo = {}
    todo.setdefault(ficha["usuario"], []).append(ficha)
    todo[ficha["usuario"]] = todo[ficha["usuario"]][-30:]
    f.write_text(json.dumps(todo, ensure_ascii=False, indent=1), encoding="utf-8")


def _guarda_competencia(ctx, panel: dict) -> None:
    """La ultima comparativa, para que la pestana la enseñe sin volver a gastar
    cuota de la API ni depender de que Instagram este disponible."""
    (_dir_datos(ctx) / "competencia.json").write_text(
        json.dumps({"cuando": _ahora_iso(), "panel": panel},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def _ultimo_reel_analizado(ctx) -> str:
    """El id del reel del ultimo analisis, para no tener que teclearlo."""
    f = _dir_datos(ctx) / "ultimo_analisis.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            reels = d.get("reels") or []
            if reels:
                return str((reels[0].get("reel") or {}).get("id") or "")
        except Exception:
            pass
    return ""


def _registro_conversion(ctx) -> dict:
    """Lo que el usuario ha apuntado del embudo, por reel.

    Nada de esto lo da Instagram: sale de su herramienta de DM, de su acortador
    y de su pasarela. Si no hay nada apuntado, el informe lo dice; no estima."""
    f = _dir_datos(ctx) / "conversion.json"
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            pass
    return {}


def _apunta_conversion(ctx, reel_id: str, datos: dict) -> dict:
    reg = _registro_conversion(ctx)
    fila = dict(reg.get(reel_id) or {})
    fila.update(datos)
    reg[reel_id] = fila
    (_dir_datos(ctx) / "conversion.json").write_text(
        json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    return fila


def _guarda_panel(ctx, paneles: list) -> None:
    """El ultimo analisis, tal cual lo pinta el HUD.

    Se guarda en disco para que la pestana Reels tenga algo que enseñar sin
    volver a llamar a la API de Instagram (que cuesta cuota) y para que siga
    ahi despues de reiniciar el equipo."""
    if not paneles:
        return
    (_dir_datos(ctx) / "ultimo_analisis.json").write_text(
        json.dumps({"cuando": _ahora_iso(), "reels": paneles},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def _ahora_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _guarda_historial(ctx, datos: list) -> None:
    (_dir_datos(ctx) / "historial.json").write_text(
        json.dumps(datos[-50:], ensure_ascii=False, indent=1), encoding="utf-8")


def _palabras_gancho(bundle: dict, ya: list, umbrales=None) -> list:
    """La(s) palabra-gancho DE ESTE reel, sin dar ninguna por supuesta.

    Tres fuentes, de más fiable a menos:
      1. Lo que TÚ hayas puesto en tu perfil (`triggers`, lead magnets).
      2. El racimo de comentarios cortos idénticos — la señal de verdad, porque
         un gancho se comenta en masa. Funciona con cualquier palabra.
      3. El patrón explícito del pie: «comenta X y te lo mando».
    Si no hay racimo ni patrón, no se inventa ninguna: el reel no llevaba gancho.
    """
    from . import analisis as A
    fuera = {str(w).upper() for w in ya}
    out = []
    for d in A.detecta_cta(bundle.get("flat") or [],
                           (bundle.get("media") or {}).get("caption", ""),
                           umbrales=umbrales):
        if d["palabra"] not in fuera:
            out.append(d["palabra"])
    for w in A.cta_del_pie((bundle.get("media") or {}).get("caption", "")):
        if w.upper() not in fuera and w not in out:
            out.append(w)
    return out


async def _cualitativo(perfil: dict, sustantivos: list, dudas: list, media: dict):
    """Lo ÚNICO que decide el modelo: sentimiento e ideas. Los conteos ya están
    hechos; aquí solo se interpreta. Si no hay cerebro, se devuelve vacío y el
    informe sale igual con toda su parte numérica."""
    if not sustantivos:
        return {}, ""
    from backend.core.llm import ask_llm
    muestra = [f"- {(c.get('text') or '').strip()[:160]}" for c in sustantivos[:120]]
    contexto = perfil_como_texto(perfil) or "(sin perfil configurado)"
    p1 = ("Clasifica CADA comentario como positivo, neutral o friccion. Devuelve SOLO "
          "una linea con tres numeros separados por comas: positivos,neutrales,friccion. "
          "Nada mas, sin texto.\n\n" + "\n".join(muestra))
    sent = {}
    try:
        r, prov = await ask_llm(p1)
        if prov != "ninguno":
            nums = [int(x) for x in re.findall(r"\d+", r)[:3]]
            if len(nums) == 3 and sum(nums) > 0:
                # se reescala a la muestra real: el modelo puede descontar alguno
                total = sum(nums)
                n = len(sustantivos)
                sent = {"positivo": round(nums[0] / total * n),
                        "neutral": round(nums[1] / total * n),
                        "friccion": n - round(nums[0] / total * n) - round(nums[1] / total * n)}
    except Exception:
        sent = {}
    ideas = ""
    try:
        p2 = ("Eres estratega de contenido. Con el CONTEXTO de la cuenta y las DUDAS "
              "reales de su audiencia, propon 6 ideas de contenido en Markdown. Para cada "
              "una: titulo, gancho concreto para los 3 primeros segundos, formato y QUE "
              "DUDA responde (citandola). Ordena por impacto. Respeta los temas vetados y "
              "no inventes dudas que no esten en la lista.\n\n"
              f"=== CONTEXTO ===\n{contexto}\n\n=== PIE DEL REEL ===\n"
              f"{(media.get('caption') or '')[:400]}\n\n=== DUDAS (con cuantas veces) ===\n"
              + "\n".join(f"- ({d['veces']}x) {d['ejemplo'][:120]}" for d in dudas[:15]))
        r2, prov2 = await ask_llm(p2)
        ideas = r2 if prov2 != "ninguno" else ""
    except Exception:
        ideas = ""
    return sent, ideas
