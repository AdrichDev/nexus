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
    # QUÉ EFECTO tiene cada intent del enrutador (ARQ-03, task T8b): lo decide
    # `canales.EFECTOS` para permitir, preguntar o denegar; sin declarar, destructive.
    "effects": {
        "olvidar": "destructive",
        "profile": "read",
        "remember": "write_local",
        "learn_folder": "write_local",
        "learn_doc": "write_local",
        "learn": "write_local",
        "list_knowledge": "read",
        "graph": "read",
        "status": "read",
        "recall": "read",
    },
    # Los que YA preguntan con confirm.request antes de su efecto: `brain`
    # no los vuelve a preguntar (T8c).
    "confirma": ("olvidar",),
    "name": "Memoria",
    "description": ("Memoria a largo plazo de doble capa: graba hechos, aprende documentos "
                    "y carpetas (PDF/Word incluidos) y los recupera con búsqueda semántica "
                    "en Postgres + grafo de notas markdown"),
    # Orden del dict: específicos (aprender carpeta/doc) ANTES que los amplios
    # (recall al final, que ahora acepta «qué sabes de X»).
    "patterns": {
        # «OLVIDA QUE …» (T37) — la promesa que esta skill YA hacía al final de
        # «qué sabes de mí» («dime «olvida que…» y lo quito») y que nadie cazaba:
        # la frase caía al planificador del cerebro, que contestaba algo plausible
        # y NO tocaba nada. El trabajo de borrado existe desde T15 (barrido de
        # ocho almacenes); aquí solo se le da una puerta por voz y texto.
        #
        # Anclado al principio (^) y con las CUATRO formas que se dicen de verdad,
        # para no quitarle frases a nadie: el router es primera coincidencia sobre
        # las carpetas en orden alfabético, y «borra la tarea», «borra el fichero»
        # o «olvida la regla …» (engram) ya tienen dueño. Por eso «borra» solo
        # entra como «borra el recuerdo de», y «olvida» lleva un lookahead que
        # deja fuera los sustantivos de regla aunque engram vaya antes.
        "olvidar": r"^\s*(?:olv[ií]da(?:te)?|borra\s+(?:el|ese|este)\s+recuerdo"
                   r"|no\s+recuerdes)"
                   r"(?!\s+(?:la|esa|esta|mi|una)\s+(?:regla|norma|preferencia|"
                   r"restricci[oó]n|correcci[oó]n|orden)\b)"
                   r"(?:\s+(?:de|que|lo\s+que|todo\s+lo\s+que|lo\s+de))?"
                   r"\s+(?P<q>.+?)\s*$",
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


# ── OLVIDAR: LA PUERTA QUE FALTABA (T37) ────────────────────────────────────
# T15 (`db5f1b8`) dejó el borrado completo hecho: `purga.previsualizar()` enseña
# TODOS los almacenes donde el hecho está copiado —y los que no se pueden tocar,
# con su motivo— y `aplicar()` barre esa lista. Lo que no había era forma de
# llegar desde una frase: esta skill prometía «dime «olvida que…» y lo quito» y
# su router no tenía el intent, así que la frase acababa en el planificador, que
# contestaba algo plausible y no tocaba nada. Esto NO reimplementa nada: pide la
# previsualización al motor, la enseña y arma el «sí» con el MISMO plan.
#
# DOS COSAS QUE ESTE CAMINO NO HACE, a propósito:
#   * `incluir_logs` NO se pasa nunca: los registros de conversación/auditoría son
#     la traza del incidente y solo salen si el operador lo pide expresamente;
#   * el borrado duro (`borrar_definitivo`) tampoco: este paso deja todo en la
#     papelera, restaurable, y el segundo tiempo lo da el operador.


def _canal(ctx) -> str:
    try:
        return str((ctx or {}).get("channel") or "pc")
    except Exception:                                          # noqa: BLE001
        return "pc"


def _recorte(texto, limite: int = 150) -> str:
    """Un motivo, cortado y diciendo que se ha cortado. No resume: recorta."""
    t = " ".join(str(texto or "").split())
    return t if len(t) <= limite else t[:limite].rstrip() + "…"


def _linea_almacen(a: dict) -> str:
    """Una línea del inventario de almacenes, en el idioma del operador."""
    que = a.get("que") or a.get("id") or "almacén"
    estado = a.get("estado")
    n = int(a.get("elementos") or 0)
    if estado == "incluido":
        accion = {"retirar": "se retira", "papelera": "va a la papelera",
                  "olvidar": "se le pide olvidar"}.get(str(a.get("accion") or ""),
                                                          "se toca")
        return f"   · {que}: {n} elemento(s) — {accion}"
    if estado == "no_incluido":
        return (f"   · {que}: NO incluido ({n} casarían) — no los toco si no me lo "
                f"pides expresamente")
    if estado == "no_disponible":
        return (f"   · {que}: ahora mismo no se puede ({_recorte(a.get('motivo'))}) — "
                f"se dirá NO COMPLETADO, nunca «hecho»")
    if estado == "no_se_toca":
        return (f"   · {que}: INTACTAS a propósito — {n} contienen lo que vas a olvidar "
                f"y no se reescriben ni se borran")
    return f"   · {que}: fuera de alcance — {_recorte(a.get('motivo'))}"


def _resumen_previsualizacion(consulta: str, plan: dict, export_dir) -> str:
    """Lo que el operador LEE antes de decir «sí»: qué se ha encontrado, qué
    almacén se toca y cuál no, y qué se queda."""
    lineas = [f"🧠 Voy a olvidar lo que case con «{consulta}». Esto es lo que he "
              f"encontrado — NADA se ha tocado todavía:", ""]
    personal = False
    for cat in plan.get("categorias") or []:
        personal = personal or bool(cat.get("personal"))
        for it in cat.get("items") or []:
            if not it.get("ruta"):
                continue
            filas = int(it.get("filas_pg") or 0)
            extra = f" y {filas} fila(s) de la base de datos" if filas else ""
            lineas.append(f"   · «{it['ruta']}»{extra}")
    lineas.append("")
    lineas.append("Almacenes (esta lista es la que voy a ejecutar, ni uno más):")
    for a in plan.get("almacenes") or []:
        lineas.append(_linea_almacen(a))
    lineas.append("")
    if personal:
        # La regla de las categorías personales: copia legible ANTES de mover.
        lineas.append("Las notas van a la PAPELERA (se restauran) y antes dejo una copia "
                      f"legible en {export_dir} — es la regla para lo personal: nada se "
                      "mueve sin copia, y el borrado definitivo no lo hago yo.")
    else:
        lineas.append("Las notas van a la PAPELERA: se restauran cuando quieras y el "
                      "borrado definitivo no lo hago yo.")
    lineas.append("Los REGISTROS de conversación y auditoría NO se tocan: son la traza del "
                  "incidente y solo salen si lo pides expresamente. Las COPIAS DE "
                  "SEGURIDAD tampoco se reescriben.")
    lineas.append("")
    lineas.append("¿Lo hago? «sí» o «no».")
    return "\n".join(lineas)


def _respuesta_aplicada(r: dict) -> str:
    """El informe de T15, más lo que este camino tiene que decir por su cuenta:
    qué NO se tocó y cómo se pide, para que nadie crea que se ha borrado todo."""
    lote = r.get("lote") or ""
    backups = (r.get("almacenes") or {}).get("backups") or {}
    fechas = ", ".join(backups.get("fechas") or [])
    lineas = [f"🧠 Hecho (lote «{lote}»).", r.get("resumen") or ""]
    lineas.append("")
    lineas.append("Los REGISTROS de conversación, auditoría y recall NO se han tocado: son "
                  "la traza del incidente y solo salen si lo pides expresamente "
                  "(`incluir_logs` en la purga, /api/memoria/purga/previsualizar). Por "
                  "voz todavía no hay atajo para eso, así que no lo he pedido yo por ti.")
    if backups.get("resultado") == "no_se_toca":
        lineas.append("Las COPIAS DE SEGURIDAD siguen intactas"
                      + (f" ({fechas})" if fechas else "")
                      + ": no las reescribo ni las borro — son tu única red. El camino "
                        "documentado es dejar que roten solas o borrarlas a mano en "
                        "data/backups/.")
    lineas.append("Si te arrepientes, «restaurar» devuelve el lote desde la papelera. El "
                  "borrado definitivo es otro paso y solo lo das tú.")
    return "\n".join(l for l in lineas if l)


def _aplicar_purga(plan: dict, categorias: list) -> str:
    """Lo que corre SOLO si el operador dice «sí» (`confirm.request`).

    `acepto_personal=True` no salta ninguna guarda: lo que hace es EXPORTAR la
    copia legible antes de mover, y el operador ya lo autorizó al decir «sí» a una
    previsualización que lo enseña. `incluir_logs` no se pasa: por defecto."""
    from backend.core.dominio import purga
    r = purga.aplicar(plan["id"], categorias, acepto_personal=True)
    if not r.get("ok"):
        return (f"No he podido completarlo: {r.get('error') or 'sin motivo'}. No doy nada "
                f"por olvidado; vuelve a pedírmelo y te enseño el plan nuevo.")
    return _respuesta_aplicada(r)


def _olvidar(text: str, match, ctx) -> dict:
    """Previsualiza y arma. Nada se mueve hasta el «sí»."""
    from backend.core.dominio import purga
    gd = match.groupdict() if match else {}
    q = (gd.get("q") or "").strip().strip("«»\"'").strip().rstrip(".")
    if not q:
        return {"reply": "¿Qué quieres que olvide? Dímelo con una frase: «olvida que…»."}
    # La consulta tiene que ser barrible: el mínimo no se inventa aquí, lo decide
    # el motor de purga con su propio umbral (`longitud_minima_termino` +
    # `palabras_vacias`), el mismo que usa para emparejar notas.
    ok, motivo = purga.consulta_util(q)
    if not ok:
        return {"reply": (f"No voy a vaciar la memoria con eso: {motivo}. Dime una frase "
                          f"más concreta —«olvida que me divorcié»— y te enseño "
                          f"exactamente qué se va ANTES de tocar nada.")}
    plan = purga.previsualizar(consulta=q)        # incluir_logs NUNCA desde aquí
    cats = [c["id"] for c in plan.get("categorias") or []]
    if not cats:
        return {"reply": (f"No encontré nada sobre «{q}» en mi memoria, así que no hay "
                          f"nada que quitar ni que confirmar. Si está guardado con otras "
                          f"palabras, dímelo como lo apunté («qué recuerdas de…» lo enseña).")}
    targets = [{"id": cat.get("id", ""), "title": it.get("ruta") or "",
                "state": cat.get("id", "")}
               for cat in plan["categorias"] for it in cat.get("items") or []
               if it.get("ruta")]
    from backend.core.comun import confirm
    pregunta = confirm.request(
        channel=_canal(ctx), kind="purga_memoria",
        summary=_resumen_previsualizacion(q, plan, purga.EXPORT_DIR / "personal"),
        request_text=text, targets=targets,
        action=lambda: _aplicar_purga(plan, cats),
        cancel_reply="Vale: no he tocado nada. Tus recuerdos siguen como estaban.")
    return {"reply": pregunta,
            "data": {"confirm": True, "plan_id": plan["id"], "categorias": cats,
                     "almacenes": [{k: a.get(k) for k in ("id", "estado", "elementos")}
                                   for a in plan.get("almacenes") or []]}}


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "profile":
        from backend.core.dominio.profile import build_profile
        import asyncio as _a
        return {"reply": await _a.to_thread(build_profile)}

    pg, graph = ctx["pg"], ctx["graph"]

    if intent == "olvidar":
        # La puerta del «olvida …»: previsualiza el motor de purga y ARMA el «sí».
        return _olvidar(text, match, ctx)

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
        from backend.core.comun import permissions as P
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
        from backend.core.comun import permissions as P
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
            from backend.core.dominio import selflearn
            maneras = (selflearn.operator_profile() or "")[:1500]
        except Exception:
            pass

        if not datos and not maneras:
            return {"reply": "Todavía no sé gran cosa de ti. Cuéntame cosas con "
                             "«recuerda que…» y las voy guardando."}

        # Y se cuenta HABLANDO, no en fichas. Un listado con secciones y emojis
        # es un volcado de base de datos, no una respuesta: el modelo lo redacta
        # usando SOLO esto, sin añadir nada de su cosecha.
        from backend.core.infraestructura.llm import ask_llm
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
                         "\n\nSi algo no cuadra, dime «olvida que…»: te enseño qué hay y "
                         "qué se quita, y no toco nada hasta que digas «sí»."}

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
        from backend.core.dominio.memory import memory_status
        st = memory_status()
        db_txt = "ONLINE ✔" if st["db_online"] else "OFFLINE ✖ (di «levanta docker»)"
        return {"reply": f"Memoria: backend {st['backend']} — {st['graph_notes']} notas "
                         f"en el grafo — DB {db_txt}"}

    return {"reply": "🧠 Esa orden de memoria no la tengo. Prueba «recuerda que …», "
                     "«qué recuerdas de …», «aprende el documento <ruta>», "
                     "«olvida que …» o «muéstrame el grafo»."}
