"""Minion Memoria — recordar, consultar y visualizar el grafo de notas."""
from __future__ import annotations

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
        "list_knowledge": r"(?:qu[eé]\s+sabes|cu[aá]nto\s+sabes|qu[eé]\s+has\s+aprendido|qu[eé]\s+conoces|"
                          r"qu[eé]\s+informaci[oó]n\s+tienes|qu[eé]\s+datos\s+tienes|"
                          r"qu[eé]\s+conocimiento\s+tienes|lista(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dame)"
                          r"\b[^.\n]{0,45}\b(?:de\s+m[ií]|sobre\s+m[ií]|archivos?\s+de\s+conocimiento|"
                          r"conocimiento\s+(?:que\s+tienes\s+)?(?:de|sobre)\s+m[ií])\b"
                          r"|todo\s+lo\s+que\s+(?:sabes|has\s+aprendido|recuerdas)\s+(?:de|sobre)\s+m[ií]",
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
        secciones = []
        # 1) PERFIL destilado
        try:
            from backend.core import selflearn
            prof = selflearn.operator_profile()
            if prof:
                secciones.append("👤 PERFIL (lo que he destilado de ti):\n" + prof[:1200])
        except Exception:
            pass
        # 2) HECHOS en Postgres
        try:
            if pg.online:
                facts = await _a.to_thread(pg.all_knowledge, 60)
                fl = [f"• {r['content'][:180]}" for r in facts if r.get('content')]
                if fl:
                    secciones.append(f"🧠 MEMORIA (Postgres, {len(fl)} entradas):\n" + "\n".join(fl[:30]))
        except Exception:
            pass
        # 3) CONOCIMIENTO RAG
        try:
            from backend.core import rag
            kn = rag.list_knowledge(60)
            kl = [f"• {r['text'][:180]}" for r in kn if r.get('text')]
            if kl:
                secciones.append(f"📚 CONOCIMIENTO (RAG, {len(kl)}):\n" + "\n".join(kl[:30]))
        except Exception:
            pass
        # 4) NOTAS del grafo (títulos)
        try:
            from backend.core.config import DATA_DIR
            notas = sorted((DATA_DIR / "memory").rglob("*.md"))
            if notas:
                secciones.append(f"🗂️ NOTAS del grafo ({len(notas)}):\n" +
                                 "\n".join("• " + n.stem for n in notas[:40]))
        except Exception:
            pass
        wab = "\n\n".join(secciones) if secciones else "De momento no tengo conocimiento guardado sobre ti."
        # 5) lo que sabe HERMES
        her = ""
        try:
            from backend.core.skills_loader import get_skills
            hsk = get_skills().get("hermes")
            if hsk:
                kb = hsk.module.known_about_user()
                if kb:
                    her = "\n\n" + "═" * 3 + " 🪽 Y esto es lo que HERMES sabe de ti " + "═" * 3
                    for fname, txt in kb:
                        her += f"\n\n[{fname}]\n{txt[:900]}"
                else:
                    her = "\n\n🪽 Hermes: no tiene aún ficheros de memoria sobre ti (o no está instalado en la ruta habitual)."
        except Exception:
            pass
        return {"reply": "Esto es TODO lo que sé de ti:\n\n" + wab + her +
                         "\n\n(Di «olvida que…» o edítalo cuando quieras.)"}

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
