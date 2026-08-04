"""Minion Memoria — recordar, consultar y visualizar el grafo de notas."""
from __future__ import annotations

import re

# El usuario hablando de SÍ MISMO, distinguido del posesivo «mi <algo>».
#
# Son dos palabras distintas y las separa la tilde: «mí» solo puede ser el
# pronombre, así que detrás puede llevar lo que quiera («qué sabes de mí
# AHORA», «de mí Y de mi familia»). «mi» sin tilde es ambiguo, porque mucha
# gente escribe el pronombre sin ella; ahí decide la gramática: el posesivo
# SIEMPRE lleva un sustantivo detrás, el pronombre no lleva nada.
#
# Sin tilde y con palabra detrás («de mi ahora») haría falta un diccionario para
# saber si esa palabra es un sustantivo poseído. Pero hay un puñado que NUNCA lo
# son —adverbios y conjunciones— y son justo las que aparecen aquí: escribiendo
# deprisa se pierde la tilde, y «que sabes de mi ahora» acababa contestando con
# la base de datos entera sobre un tema llamado «mi ahora».
#
# La lista es cerrada a propósito: cubre lo que se dice de verdad sin tener que
# adivinar. Cualquier otra palabra detrás sigue tratándose como posesivo.
_NO_ES_SUSTANTIVO = (r"ahora|ya|hoy|todav[ií]a|a[uú]n|exactamente|realmente|"
                     r"en\s+concreto|de\s+verdad|y\b|o\b|pero\b|porfa|"
                     r"por\s+favor|eh\b|no\b|s[ií]\b")
_YO = r"(?:mí\b|mi\b(?!\s+\w)|mi\b(?=\s+(?:" + _NO_ES_SUSTANTIVO + r")))"

SKILL = {
    "name": "Memoria",
    "description": ("Memoria a largo plazo de doble capa: graba hechos, aprende documentos "
                    "y carpetas (PDF/Word incluidos) y los recupera con búsqueda semántica "
                    "en Postgres + grafo de notas markdown"),
    # Orden del dict: específicos (aprender carpeta/doc) ANTES que los amplios
    # (recall al final, que ahora acepta «qué sabes de X»).
    "patterns": {
        # v20: perfil del operador — disparadores PROPIOS («qué sabes de mí»
        # sigue siendo de list_knowledge por contrato de tests).
        "profile": r"\bmi\s+perfil\b|qui[eé]n\s+soy\s*(?:yo)?\s*\??\s*$"
                   r"|h[aá]blame\s+de\s+m[ií]\b|perfil\s+del?\s+operador"
                   r"|retrato\s+de\s+m[ií]\b",
        "remember": r"(?:recuerda|acu[eé]rdate(?:\s+de)?|memoriza|no\s+olvides|ten\s+en\s+cuenta|"
                    r"ten\s+presente|ap[uú]ntame|ap[uú]nta(?:me)?\s+en\s+(?:la\s+)?memoria|"
                    r"guarda\s+en\s+(?:la\s+)?memoria)\s+que\s+(?P<fact>.+)",
        "learn_folder": r"(?:apr[eé]nde(?:te)?|est[uú]dia(?:te)?|indexa|ingiere|memoriza)\s+"
                        r"(?:la\s+|el\s+)?(?:carpeta|directorio)\s+(?P<folder>.+)",
        "learn_doc": r"(?:apr[eé]nde(?:te)?|est[uú]dia(?:te)?|indexa|ingiere|memoriza)\s+"
                     r"(?:el\s+|este\s+)?(?:documento|archivo|fichero|pdf|docx?|word)\s+(?P<path>.+)",
        "learn": r"apr[eé]nde(?:te)?\s+que\s+(?P<fact>.+)",
        # «de mí» es el PRONOMBRE (sobre mi persona) y «de mi madre» el POSESIVO,
        # que es otra palabra. Sin separarlos, «dame ideas para el regalo de mi
        # madre» acababa aquí. Los separa `_YO` (ver arriba).
        "list_knowledge": r"(?:qu[eé]\s+sabes|cu[aá]nto\s+sabes|qu[eé]\s+has\s+aprendido|qu[eé]\s+conoces|"
                          r"qu[eé]\s+informaci[oó]n\s+tienes|qu[eé]\s+datos\s+tienes|"
                          r"qu[eé]\s+conocimiento\s+tienes|lista(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dame)"
                          r"\b[^.\n]{0,45}\b(?:(?:de|sobre)\s+" + _YO + r"|archivos?\s+de\s+conocimiento|"
                          r"conocimiento\s+(?:que\s+tienes\s+)?(?:de|sobre)\s+" + _YO + r")"
                          r"|todo\s+lo\s+que\s+(?:sabes|has\s+aprendido|recuerdas)\s+(?:de|sobre)\s+" + _YO,
        "graph": r"(mu[eé]strame|ens[eé][ñn]ame|abre|ver|visualiza) (el )?grafo"
                 r"|grafo de (notas|memoria|conocimiento)|mapa (de (la )?)?memoria",
        "status": r"estado de (la |tu )?memoria|c[oó]mo (va|est[aá]|anda) (la |tu )?memoria"
                  r"|diagn[oó]stico de (la )?memoria",
        # El enclítico («búscame», «encuéntrame») y los artículos («en MIS notas»)
        # son tan habituales como el verbo desnudo.
        "recall": r"qu[eé]\s+(?:recuerdas|sabes|te\s+he\s+contado|te\s+cont[eé]|apuntaste|guardaste)\s+"
                  r"(?:de|sobre|acerca\s+de)\s+(?P<topic>.+)"
                  r"|(?:busca|b[uú]scame|encuentra|encu[eé]ntrame|mira|rebusca)\s+en\s+"
                  r"(?:la\s+|el\s+|mi\s+|mis\s+|tu\s+|tus\s+)?(?:memoria|notas|apuntes|recuerdos|grafo)\s+"
                  r"(?:sobre\s+|de\s+)?(?P<topic2>.+)",
    },
}

CHUNK = 900  # tamaño de fragmento para la ingesta de documentos

TEXT_EXTS = (".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css",
             ".log", ".sql", ".yml", ".yaml", ".ini", ".xml")
DOC_EXTS = (".pdf", ".docx")               # Word y PDF (apuntes, actividades, etc.)
LEARN_EXTS = TEXT_EXTS + DOC_EXTS


def _extract_text(path) -> str:
    """Extrae texto de un archivo. Soporta texto/código, PDF (pypdf) y Word (.docx).
    Devuelve '' si no se puede leer (p.ej. falta la librería)."""
    suf = path.suffix.lower()
    try:
        if suf in TEXT_EXTS:
            return path.read_text(encoding="utf-8", errors="replace")
        if suf == ".pdf":
            try:
                from pypdf import PdfReader
            except Exception:
                try:
                    from PyPDF2 import PdfReader
                except Exception:
                    return ""
            return "\n".join((pagina.extract_text() or "") for pagina in PdfReader(str(path)).pages)
        if suf == ".docx":
            try:
                import docx
            except Exception:
                return ""
            return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    except Exception:
        return ""
    return ""


# ── QUÉ ES «SABER DE TI» Y QUÉ NO ────────────────────────────────────────────
# La memoria guarda tres cosas muy distintas en el mismo cajón:
#
#   1. lo que sabe DE TI          — «me gusta el café solo», «el wifi va lento»
#   2. su propia DOCUMENTACIÓN    — los SKILL.md indexados para poder decidir
#   3. REGISTROS de trabajo       — «[Trabajo] X => RuntimeError: …»
#
# Preguntar «qué sabes de mí» y recibir los tres es lo que hacía hasta ahora, y
# de 200 entradas 60 eran documentación suya y unas cuantas trazas de error.
#
# Lo que distingue una cosa de otra NO hay que adivinarlo: ya está escrito al
# guardarlo. `fact` y `procedure` es lo que TÚ has mandado recordar; `knowledge`
# es documentación indexada para poder decidir, y `hermes` el registro de los
# encargos. Intentar reconocerlo por la forma del texto no funciona: los
# fragmentos de un manual partido por la mitad parecen frases sueltas.
_TUYO = ("fact", "procedure", "preference")

# Red para lo que se guardó mal etiquetado antes de que esto existiera.
_NO_ES_SOBRE_TI = re.compile(
    r"^\s*\[Trabajo\]|^\s*\[[^\]]*›[^\]]*\]|^\s*#{1,3}\s|\bSkill:\s"
    r"|=>\s*(?:RuntimeError|Traceback|Exception|Error)", re.IGNORECASE)


def es_sobre_el_usuario(entrada) -> bool:
    """¿Esta entrada es un dato SOBRE EL OPERADOR, o fontanería del sistema?

    Acepta la fila entera (con su `kind`) o solo el texto. Con la fila decide el
    `kind`, que es la verdad; con el texto suelto solo puede aplicar la red de
    las mal etiquetadas."""
    if isinstance(entrada, dict):
        if (entrada.get("kind") or "") not in _TUYO:
            return False
        texto = entrada.get("content") or entrada.get("text") or ""
    else:
        texto = entrada or ""
    t = texto.strip()
    return len(t) >= 8 and not _NO_ES_SOBRE_TI.search(t)


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "profile":
        from backend.core.profile import build_profile
        import asyncio as _a
        return {"reply": await _a.to_thread(build_profile)}

    pg, graph = ctx["pg"], ctx["graph"]

    if intent == "remember":
        fact = match.group("fact").strip().rstrip(".")
        graph.append_daily(fact, section="Memoria")
        if pg.online:
            pg.remember(fact, kind="fact")
            return {"reply": f"✔ Grabado en memoria a largo plazo (DB + grafo): «{fact}». "
                             "Recupéralo cuando quieras con «qué recuerdas de …»."}
        return {"reply": f"✔ Grabado en el grafo de notas: «{fact}». "
                         "⚠ La DB está offline: di «levanta docker» y tendrás "
                         "también búsqueda semántica."}

    if intent == "learn":
        fact = match.group("fact").strip().rstrip(".")
        graph.write_note(f"conocimiento {fact[:36]}", fact + "\n\nEnlaces: [[conocimiento]]")
        if pg.online:
            pg.remember(fact, kind="procedure", tags=["conocimiento"])
        return {"reply": f"Aprendido: «{fact[:120]}». Lo usaré como contexto cuando venga al caso."}

    if intent == "learn_folder":
        # Ingesta masiva: texto, código, PDF y Word de una carpeta → conocimiento
        from pathlib import Path
        raw = match.group("folder").strip().strip('"').strip("'").rstrip(".")
        base = Path(raw).expanduser()
        from backend.core import permissions as P
        if not P.path_allowed(base):
            return {"reply": P.deny_msg(base)}
        if not base.is_dir():
            return {"reply": f"No encuentro la carpeta {base}."}
        cands = [p for p in base.rglob("*") if p.suffix.lower() in LEARN_EXTS
                 and p.is_file() and p.stat().st_size < 6_000_000][:40]
        if not cands:
            return {"reply": f"En «{base.name}» no hay archivos que pueda aprender "
                             "(txt/md/código, PDF o Word; máx. 40 por tanda)."}
        folder = base.name
        learned, chunks, skipped = 0, 0, 0
        for f in cands:
            text = _extract_text(f)
            if not text.strip():
                skipped += 1
                continue
            graph.write_note(f"doc {f.stem[:40]}",
                             f"Carpeta: {folder}\nArchivo: {f.name}\n\n" + text[:20000]
                             + "\n\nEnlaces: [[conocimiento]] [[documentos]]")
            learned += 1
            if pg.online:
                for i in range(0, min(len(text), 40000), CHUNK):
                    frag = text[i:i + CHUNK].strip()
                    if frag:
                        # `origen` en CADA fragmento, no solo en el primero. La
                        # cabecera «Carpeta:» va únicamente en el trozo inicial,
                        # así que sin esto los fragmentos de continuación quedan
                        # huérfanos: al purgar la carpeta nadie los reclama y se
                        # quedan vivos contestando búsquedas. Pasó de verdad con
                        # «20. FP DAM Euroformac» (02/08/2026).
                        pg.remember(f"[{folder} › {f.name}] {frag}",
                                    kind="knowledge", tags=["doc", f.stem, folder],
                                    origen=f"{folder}/{f.name}", origen_tipo="carpeta")
                        chunks += 1
        db_txt = f", {chunks} fragmentos indexados en la DB" if chunks else " (DB offline)"
        skip_txt = (f" Salté {skipped} (PDF/Word sin librería: instala pypdf y python-docx "
                    "con run.bat).") if skipped else ""
        return {"reply": f"Carpeta «{folder}» aprendida: {learned} archivos{db_txt}.{skip_txt} "
                         "Pregúntame con «qué recuerdas de ...»."}

    if intent == "learn_doc":
        # Ingesta de un documento entero a la memoria (troceado en fragmentos)
        from pathlib import Path
        raw = match.group("path").strip().strip('"').strip("'").rstrip(".")
        path = Path(raw).expanduser()
        from backend.core import permissions as P
        if not P.path_allowed(path):
            return {"reply": P.deny_msg(path)}
        if not path.is_file():
            return {"reply": f"No encuentro el documento {path}. Dame la ruta completa "
                             "(admite comillas si tiene espacios)."}
        if path.suffix.lower() not in LEARN_EXTS:
            return {"reply": f"Formato {path.suffix} no soportado (usa txt/md/código, PDF o Word)."}
        text = _extract_text(path)
        if not text.strip():
            return {"reply": f"No pude extraer texto de {path.name}. Si es PDF o Word, "
                             "instala las librerías con run.bat (pypdf y python-docx)."}
        # Nota completa en el grafo (consultable con «qué recuerdas de...»)
        graph.write_note(f"doc {path.stem[:40]}",
                         text[:20000] + "\n\nEnlaces: [[conocimiento]] [[documentos]]")
        # Fragmentos a la DB para el recall
        chunks = 0
        if pg.online:
            paragraphs, buf = [], ""
            for para in text.split("\n\n"):
                if len(buf) + len(para) > CHUNK and buf:
                    paragraphs.append(buf); buf = para
                else:
                    buf = f"{buf}\n\n{para}" if buf else para
            if buf:
                paragraphs.append(buf)
            for ch in paragraphs[:200]:
                pg.remember(f"[{path.name}] {ch.strip()}", kind="knowledge",
                            tags=["doc", path.stem])
                chunks += 1
        db_txt = f" y {chunks} fragmentos en la DB" if chunks else \
                 " (DB offline: solo en el grafo; levanta el Docker para búsqueda completa)"
        return {"reply": f"Documento «{path.name}» aprendido: {len(text):,} caracteres "
                         f"en el grafo{db_txt}. Pregúntame con «qué recuerdas de ...»."}

    if intent == "list_knowledge":
        import asyncio as _a
        # Se reúne SOLO lo que es sobre el operador: sus datos y cómo le gusta
        # que se hagan las cosas. La documentación del sistema y los registros de
        # trabajo se quedan fuera — no son suyos, son míos.
        datos: list[str] = []
        try:
            if pg.online:
                for r in await _a.to_thread(pg.all_knowledge, 300):
                    if es_sobre_el_usuario(r):
                        c = (r.get("content") or "").strip()[:200]
                        if c not in datos:
                            datos.append(c)
        except Exception:
            pass

        # Cómo le gusta que se le hable y que se trabaje: eso también es «de él»,
        # y es lo que más se nota si se olvida.
        maneras = ""
        try:
            from backend.core import selflearn
            maneras = (selflearn.operator_profile() or "")[:1500]
        except Exception:
            pass

        if not datos and not maneras:
            return {"reply": "Todavía no sé gran cosa de ti. Cuéntame cosas con "
                             "«recuerda que…» y las voy guardando."}

        # Y se cuenta HABLANDO, no en fichas. Un listado con secciones y emojis
        # es un volcado de base de datos, no una respuesta: el modelo lo redacta
        # usando SOLO esto, sin añadir nada de su cosecha.
        from backend.core.llm import ask_llm
        material = ""
        if maneras:
            material += "CÓMO LE GUSTA QUE TRABAJES:\n" + maneras + "\n\n"
        if datos:
            material += "LO QUE SÉ DE ÉL:\n" + "\n".join(f"- {d}" for d in datos[:40])
        # Se le habla de TÚ, sin nombre: el nombre del operador es un dato suyo,
        # no una constante del programa. Esto se instala en el equipo de otra
        # gente.
        texto, _ = await ask_llm(
            "Cuéntale lo que sabes de él, hablándole de tú, como en una "
            "conversación. Sin secciones, sin títulos, sin viñetas y sin emojis: "
            "párrafos cortos y naturales, como se lo contarías de viva voz. "
            "Agrupa lo que vaya junto y ve a lo concreto.\n\n"
            "REGLA QUE NO SE SALTA: usa ÚNICAMENTE lo que hay aquí abajo. No "
            "añadas, no supongas y no rellenes. Si algo no está, no está.\n\n"
            + material)
        if not (texto or "").strip():
            # Sin modelo no se calla: se enseña lo que hay, tal cual.
            texto = "Esto es lo que tengo tuyo:\n" + "\n".join(f"· {d}" for d in datos[:25])
        return {"reply": texto.strip() +
                         "\n\nSi algo no cuadra, dime «olvida que…» y lo quito."}

    if intent == "recall":
        topic = (match.group("topic") or match.group("topic2") or "").strip().rstrip("?¿.")
        db_hits = pg.recall(topic, 4) if pg.online else []
        file_hits = graph.search(topic, 4)
        if not db_hits and not file_hits:
            return {"reply": f"No tengo nada sobre «{topic}» en memoria... todavía. "
                             "Di «recuerda que …» o «aprende el documento <ruta>» y lo fijo."}
        lines = [f"Esto es lo que recuerdo sobre «{topic}»:"]
        for r in db_hits:
            lines.append(f"• [DB] {r['content'][:120]}")
        for r in file_hits:
            lines.append(f"• [{r['file']}] {r['line'][:120]}")
        return {"reply": "\n".join(lines[:8])}

    if intent == "graph":
        g = graph.graph()
        sample = " · ".join(g["nodes"][:12])
        return {"reply": f"🕸 Grafo de memoria: {len(g['nodes'])} notas, "
                         f"{len(g['edges'])} enlaces. Nodos: {sample}. "
                         "Di «qué recuerdas de <nota>» y te la abro.",
                "data": g}

    if intent == "status":
        from backend.core.memory import memory_status
        st = memory_status()
        db_txt = "ONLINE ✔" if st["db_online"] else "OFFLINE ✖ (di «levanta docker»)"
        return {"reply": f"Memoria: backend {st['backend']} — {st['graph_notes']} notas "
                         f"en el grafo — DB {db_txt}"}

    return {"reply": "🧠 Esa orden de memoria no la tengo. Prueba «recuerda que …», "
                     "«qué recuerdas de …», «aprende el documento <ruta>» o «muéstrame el grafo»."}
