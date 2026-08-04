"""Minion Archivos — explorar, buscar, leer, resumir (IA), CRUD real y papelera.

v23 (specs v23, TAREAS 18-21):
  * LEE DE VERDAD .md, .txt, .docx y .pdf (y .json/.csv/.xlsx/código). Si un
    formato no es compatible lo dice — jamás afirma haber leído lo que no abrió.
  * ACTUALIZAR archivos existentes: «añade al archivo X…», «actualiza X con…».
  * Sobrescribir EXIGE confirmación y deja copia de la versión anterior, que se
    puede restaurar con «restaura el archivo X».
  * Tras crear o modificar VERIFICA que el archivo existe y devuelve la RUTA REAL.
"""
from __future__ import annotations

from pathlib import Path

from backend.core import files_io as FIO

SKILL = {
    "name": "Archivos",
    "description": "Archivos reales del equipo: crear (con contenido IA), mover, copiar, renombrar, buscar, leer, resumir y papelera recuperable, bajo permisos sandbox/carpetas/todo",
    "patterns": {
        # -- específicos arriba, amplios abajo; TODOS con ancla archivo/carpeta/ruta --
        "trash_confirm": r"confirmo papelera",
        "trash": r"\b(?:b[oó]rra(?:me)?|borra(?:me)?|elimina(?:me)?|qu[ií]ta(?:me)?|destruye)\s+"
                 r"(?:el\s+|la\s+|los\s+|las\s+|ese\s+|esa\s+|este\s+|esta\s+)?"
                 r"(?:archivo|fichero|documento|carpeta|directorio)\s+(?P<path3>\S+)"
                 r"|\b(?:manda|env[ií]a|tira|mueve|m[aá]nda(?:me|le)?)\b[^.\n]{0,25}?\ba\s+la\s+papelera\s+"
                 r"(?:el\s+|la\s+|los\s+|las\s+)?(?:(?:archivo|fichero|documento|carpeta|directorio)\s+(?P<path>\S+)"
                 r"|(?P<path2>\S*[\\/.]\S+))"
                 r"|\b(?:manda|env[ií]a|tira|mueve)\s+(?:el\s+|la\s+)?"
                 r"(?:archivo|fichero|documento|carpeta|directorio)\s+(?P<path4>.+?)\s+a\s+la\s+papelera",
        "make_doc": r"\b(cr[eé]a(?:me|te)?|cr[eé]es|h[aá]z(?:me)?|gen[eé]ra(?:me)?|escr[ií]be(?:me)?|red[aá]cta(?:me)?)\b"
                    r"[^.]{0,45}\b(archivo|documento|word|doc|\.?docx|\.?txt|\.?md|texto|csv|json|markdown)\b[^.]{0,70}\bescritorio\b",
        "move": r"\b(mueve|mu[eé]ve(?:me)?|traslada|trasladar|mover|lleva|ll[eé]va(?:me|te)?|pasa)\b\s+(?:el |la |los |las )?"
                r"(?:archivo|fichero|documento|carpeta|directorio)\s+(?P<src>.+?)\s+(?:a|al|hacia|hasta|dentro de)\s+(?P<dst>.+)",
        "copy": r"\b(c[oó]pia(?:me)?|copiar|duplica(?:me)?|dupl[ií]ca(?:me)?|duplicar|clona|cl[oó]na(?:me)?)\b\s+(?:el |la |los |las )?"
                r"(?:archivo|fichero|documento|carpeta|directorio)\s+(?P<src>.+?)\s+(?:a|al|en|hacia|dentro de)\s+(?P<dst>.+)",
        "rename": r"\b(renombra(?:me)?|renombrar|ren[oó]mbra(?:me)?|cambia(?:le)? el nombre (?:de|del)?)\s+"
                  r"(?:el |la )?(?:archivo |fichero |documento |carpeta |directorio )?(?P<src>.+?)\s+(?:a|por|como)\s+(?P<dst>.+)",
        "mkdir": r"\b(?:cr[eé]a(?:me|r|te)?|h[aá]z(?:me)?|gen[eé]ra(?:me)?|prepara(?:me)?|nueva)\b"
                 r"[^.]{0,18}\b(?:carpeta|directorio|folder)\b\s+(?P<rest>.+)",
        # v23 (T19/T21): actualizar, ver versiones y restaurar. Van ANTES de mkfile
        # porque «actualiza el archivo X» no es crear uno nuevo.
        "update": r"\b(?:actualiza|a[ñn]ade|agrega|corrige|modifica|edita|mete)\b"
                  r"[^.\n]{0,20}\b(?:al\s+|el\s+|la\s+|en\s+el\s+|en\s+la\s+)?"
                  r"(?:archivo|fichero|documento)\s+(?P<path>\S+)"
                  r"(?:\s+(?:que\s+diga|con\s+el\s+(?:texto|contenido)|:|,)\s*(?P<cont>.+))?",
        "versions": r"(?:qu[eé]\s+)?versiones\s+(?:tienes\s+)?(?:de(?:l)?\s+)?"
                    r"(?:archivo|fichero|documento)?\s*(?P<path>\S+)"
                    r"|historial\s+de(?:l)?\s+(?:archivo|fichero)\s+(?P<path2>\S+)",
        "restore_file": r"(?:restaura|recupera|revierte|deshaz\s+los\s+cambios\s+de)\s+"
                        r"(?:el\s+|la\s+)?(?:archivo|fichero|documento|versi[oó]n\s+de(?:l)?)\s+"
                        r"(?P<path>\S+)",
        "mkfile": r"\b(?:cr[eé]a(?:me|r|te)?|h[aá]z(?:me)?|gen[eé]ra(?:me)?|nuevo)\b"
                  r"[^.]{0,18}\b(?:archivo|fichero)\b\s+(?P<rest>.+)",
        "search": r"\b(?:busca|b[uú]scame|encuentra|localiza)\s+(?:archivos?\s+|ficheros?\s+|documentos?\s+)?(?P<pat>\S+)\s+en\s+(?=(?:la\s+carpeta\b|el\s+(?:disco|directorio)\b|mis?\s+(?:documentos|descargas|escritorio|archivos)\b|(?:los\s+)?documentos\b|descargas\b|escritorio\b|[A-Za-z]:[\\/]|[/~.]))(?P<path>.+)",
        "explore": r"\b(?:expl[oó]ra(?:me)?|[aá]bre(?:me)?|ens[eé][ñn]a(?:me)?|mu[eé]stra(?:me)?|lista|l[ií]sta(?:me)?|qu[eé]\s+hay\s+(?:en|dentro\s+de))\b"
                   r"[^.\n]{0,15}?\b(?:la\s+carpeta|el\s+directorio)\s+(?P<path>[^?\n]+)"
                   r"|\b(?:expl[oó]ra(?:me)?|qu[eé]\s+hay\s+(?:en|dentro\s+de))\s+(?:el\s+|la\s+|mis?\s+)?"
                   r"(?P<path2>(?:escritorio|descargas|documentos|im[aá]genes)\b[^?\n]*|[A-Za-z]:[\\/][^?\n]*|[/~.][^?\n]*)",
        "analyze": r"\b(?:anal[ií]za(?:me)?|revisa|audita)\s+(?:el\s+c[oó]digo\s+(?:de(?:l)?\s+)?|el\s+script\s+|el\s+archivo\s+)?"
                   r"(?P<path>\S+\.(?:py|js|ts|jsx|tsx|java|go|rs|c|cpp|h|hpp|cs|php|rb|swift|kt|html|css|sql|sh|ps1|bat))\b",
        "summarize": r"\bres[uú]me(?:me)?\s+(?:el\s+|la\s+)?(?:documento|archivo|fichero)\s+(?P<path>\S+)"
                     r"|\bres[uú]me(?:me)?\s+(?:el\s+)?(?P<path2>\S+\.\w{1,5})\b",
        "read": r"\b(?:l[eé]e(?:me|te|r)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|[aá]bre(?:me)?)\s+(?:el\s+|la\s+)?"
                r"(?:archivo|fichero)\s+(?P<path>\S+)"
                r"|\bl[eé]e(?:me)?\s+(?:el\s+)?(?P<path2>\S+\.\w{1,5})\b",
    },
}

# ── CANDADO ANTI-DRIVE (02/08/2026) ─────────────────────────────────────────
# Esta skill toca ficheros LOCALES. Google Drive vive en skills/google_workspace
# y, como skills_loader recorre las carpetas por orden ALFABÉTICO y gana la
# primera regex que case, «files» va ANTES que «google_workspace»: sin esto,
# «borra la carpeta Informes de drive» lo cogía el `trash` de aquí y borraba una
# carpeta del disco. El candado es un lookahead que descarta el patrón cuando la
# frase menciona «drive», y se aplica SOLO a los intents que pueden chocar (los
# que hablan de archivo/carpeta genéricos).
#
# HUECO DEL CANDADO, encontrado el 02/08/2026 al auditar google_workspace: la
# versión anterior decía que «los que exigen una ruta real (analyze, search) no
# lo necesitan». Era FALSO para tres de ellos y se comprobó enrutando de verdad:
#   * «busca contratos en la carpeta Clientes de drive» → caía en `search`, que
#     ve las palabras «la carpeta» en su lookahead y se pone a recorrer el DISCO.
#     Y esa frase es un ejemplo literal del SKILL.md de Google.
#   * «qué versiones tienes de informe.md en drive» → caía en `versions`.
#   * «restaura el archivo informe.md de drive» → caía en `restore_file`.
# `analyze` se queda FUERA a propósito y con la razón escrita: exige una ruta con
# extensión de código (.py/.js/…), es de SOLO LECTURA y no hay ningún intent de
# Drive que analice código, así que meterlo en el candado dejaría la frase sin
# ruta sin ganar nada a cambio.
_SIN_DRIVE = r"(?!.*\b(?:google\s+)?drive\b)"
_INTENTS_QUE_CHOCAN_CON_DRIVE = ("trash", "make_doc", "move", "copy", "rename",
                                 "mkdir", "mkfile", "explore", "update",
                                 "summarize", "read", "search", "versions",
                                 "restore_file")
for _i in _INTENTS_QUE_CHOCAN_CON_DRIVE:
    if _i in SKILL["patterns"]:
        SKILL["patterns"][_i] = _SIN_DRIVE + "(?:" + SKILL["patterns"][_i] + ")"

def _resolve(raw: str) -> Path:
    return Path(raw.strip().strip('"').strip("'")).expanduser()


def _g(match, *names) -> str:
    """Primer grupo con valor de la lista (los patrones usan path/path2/…)."""
    gd = match.groupdict()
    for n in names:
        if gd.get(n):
            return gd[n]
    return ""


def _known_dir(word: str):
    """Carpeta conocida (Escritorio/Documentos/Descargas/Imágenes) o None."""
    import os
    import re as _re
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    od = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or ""
    od = Path(od) if od else None
    w = (word or "").lower()

    def first(*cs):
        for c in cs:
            if c and Path(c).exists():
                return Path(c)
        return None
    if _re.search(r"escritorio|desktop", w):
        return first(od and od / "Desktop", od and od / "Escritorio",
                     home / "Desktop", home / "Escritorio") or home
    if _re.search(r"documento", w):
        return first(od and od / "Documents", home / "Documents", home / "Documentos") or home
    if _re.search(r"descarga|download", w):
        return first(home / "Downloads", home / "Descargas") or home
    if _re.search(r"imagen|foto|picture", w):
        return first(home / "Pictures", home / "Imagenes", home / "Imágenes") or home
    return None


def _desktop() -> Path:
    return _known_dir("escritorio")


def _carpeta(raw: str) -> Path:
    """Ruta de una carpeta a partir de lo que dijo el usuario. «el escritorio»,
    «mis documentos» o «descargas» son carpetas conocidas del perfil; cualquier
    cosa con separador o unidad se toma como ruta literal."""
    txt = (raw or "").strip().strip('"\'').rstrip(".?!").strip()
    if not any(c in txt for c in "/\\:"):
        conocida = _known_dir(txt)
        if conocida:
            return conocida
    return _resolve(txt)


def _parse_loc_name(rest: str, default_base: Path):
    """De «llamada Proyectos dentro de Documentos» → (base_path, "Proyectos").
    Entiende la ubicación (en/dentro de + escritorio/documentos/descargas/ruta/subcarpeta)
    y limpia los cualificadores del nombre (una, la, nueva, llamada, que se llame…)."""
    import re as _re
    s = (rest or "").strip().strip(".?!").strip()
    base = None
    m = _re.search(r"\s+(?:dentro\s+de|en|hacia|hasta|al?)\s+"
                   r"(?:la\s+carpeta\s+|el\s+directorio\s+|mi\s+|el\s+|la\s+)?(?P<loc>.+)$",
                   s, _re.I)
    if m:
        loc = m.group("loc").strip().strip('"\'')
        s = s[:m.start()].strip()
        kd = _known_dir(loc)
        if kd:
            base = kd
        elif _re.search(r"[\\/]|^[a-zA-Z]:", loc):
            base = Path(loc).expanduser()               # ruta explícita
        else:
            base = _desktop() / loc                     # subcarpeta del escritorio
    # limpia cualificadores del principio (una, la, nueva, carpeta, archivo…), varios seguidos
    s = _re.sub(r"^(?:(?:una?|unos|unas|la|el|los|las|mi|nueva|nuevo)\s+|"
                r"(?:carpeta|directorio|folder|archivo|fichero)\s+)+", "", s, flags=_re.I)
    s = _re.sub(r"^(?:llamad[oa]|titulad[oa]|de\s+nombre|con\s+nombre|"
                r"que\s+se\s+llame|de)\s+", "", s, flags=_re.I)
    name = _re.sub(r'[<>:"/\\|?*\n\r]', "", s.strip().strip('"\'')).strip()
    return (base or default_base), name


async def _ai_summary(text: str, prompt: str) -> str:
    from backend.core.llm import ask_llm
    reply, _prov = await ask_llm(f"{prompt}\n\n---\n{text[:6000]}")
    return reply


def _perm():
    from backend.core.comun import permissions
    return permissions


def _ficha_papelera(path: Path) -> str:
    """Describe QUÉ se lleva la papelera: tipo, ruta completa y tamaño/contenido."""
    if path.is_dir():
        try:
            dentro = sum(1 for _ in path.rglob("*"))
        except OSError:
            dentro = 0
        return (f"la CARPETA «{path.name}» ({path}) con {dentro} elemento(s) dentro "
                "(subcarpetas incluidas)")
    try:
        kb = path.stat().st_size / 1024
        return f"el archivo «{path.name}» ({path}, {kb:.1f} KB)"
    except OSError:
        return f"«{path.name}» ({path})"


async def handle(intent: str, text: str, match, ctx) -> dict:
    P = _perm()
    if intent == "make_doc":
        import os
        import re as _re
        low = text.lower()
        home = Path(os.environ.get("USERPROFILE") or Path.home())
        onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or ""
        cands = [home / "Desktop", home / "Escritorio"]
        if onedrive:                          # Windows suele redirigir el Escritorio a OneDrive
            cands = [Path(onedrive) / "Desktop", Path(onedrive) / "Escritorio"] + cands
        desktop = next((d for d in cands if d.exists()), home)
        if not P.path_allowed(desktop):
            return {"reply": P.deny_msg(desktop)}
        # NOMBRE: se corta en el primer conector (y/con/que/donde/dentro/en el escritorio)
        mn = _re.search(
            r"(?:se\s+llame|llamad[oa]|titulad[oa]|con\s+nombre|de\s+nombre)\s+"
            r"[\"']?(?P<n>[\wáéíóúüñ.\- ]+?)[\"']?"
            r"(?=\s+(?:y|con|que|donde|dentro|en\s+el\s+escritorio|en\s+escritorio)\b|[.,;]|$)",
            text, _re.I)
        name = (mn.group("n").strip() if mn else "documento nexus")
        # CONTENIDO: literal («que diga X») o DESCRIPCIÓN a redactar con IA
        # («dentro haya un mensaje romántico», «un poema», «sobre X»…)
        content = ""
        mc = _re.search(r"(?:que\s+diga|con\s+el\s+texto|con\s+el\s+contenido)\s+(?P<c>.+)$", text, _re.I)
        if mc:
            content = mc.group("c").strip().strip('"').strip("'")
        else:
            md = _re.search(
                r"(?:dentro\s+(?:haya|ponga|pon|vaya|va|quiero|quieras|escribe|escribas|metas?|incluye|coloca|ponme)\s+"
                r"|con\s+(?:un|una|el|la)\s+(?:mensaje|texto|poema|carta|nota|frase|chiste|receta|resumen|contenido|dedicatoria)\b\s*"
                r"|(?:un|una|el|la)\s+(?:mensaje|poema|carta|nota|frase|chiste|receta|dedicatoria)\b\s+"
                r"|sobre\s+|acerca\s+de\s+|que\s+hable\s+de\s+)"
                r"(?P<d>.+?)(?:\s+en\s+(?:el\s+)?escritorio.*)?$", text, _re.I)
            desc = (md.group("d").strip() if md else "")
            if desc and "escritorio" not in desc.lower():
                try:
                    from backend.core.llm import ask_llm
                    content, _p = await ask_llm(
                        f"Redacta en español el CONTENIDO de un documento pedido así: «{desc}». "
                        "Devuelve solo el texto del documento, bien escrito, con calidez si procede, "
                        "sin preámbulos, sin comillas y sin explicaciones. Máx 300 palabras.")
                    content = content.strip().strip('"')
                except Exception:
                    content = ""
        name = _re.sub(r'[<>:"/\\|?*\n\r]', "", name).strip() or "documento nexus"
        # EXTENSIÓN: la que se pida; si no se pide ninguna, .md. El criterio vive
        # en backend/core/files_io.formato_pedido para que lo compartan todas las
        # skills que escriben ficheros.
        KNOWN = ("docx", "txt", "md", "csv", "json", "html", "py", "log", "xml", "ini", "yaml", "yml")
        from backend.core.files_io import formato_pedido
        ext = formato_pedido(low)
        me = _re.search(r"\.(py|log|xml|ini|yaml|yml)\b", low)
        if me:
            ext = "." + me.group(1)
        if "." in name and name.rsplit(".", 1)[-1].lower() in KNOWN:   # nombre ya trae extensión
            ext = "." + name.rsplit(".", 1)[-1].lower()
            name = name.rsplit(".", 1)[0].strip() or "documento nexus"
        if not content:
            content = "Documento creado por nexus."
        try:
            desktop.mkdir(parents=True, exist_ok=True)
            if ext == ".docx":
                try:
                    import docx
                    d = docx.Document()
                    d.add_heading(name, level=1)
                    for para in content.split("\n"):
                        d.add_paragraph(para)
                    out = desktop / f"{name}.docx"
                    d.save(str(out))
                    return {"reply": f"Documento de Word creado en el escritorio: {out.name} ✔"}
                except Exception:
                    out = desktop / f"{name}.txt"
                    out.write_text(content + "\n", encoding="utf-8")
                    return {"reply": f"Creé «{out.name}» en el escritorio (texto). Para .docx real, "
                                     "instala python-docx (ejecuta run.bat) y repite."}
            out = desktop / f"{name}{ext}"
            out.write_text(content + "\n", encoding="utf-8")
            return {"reply": f"Archivo creado en el escritorio: {out.name} ✔"}
        except Exception as exc:
            return {"reply": f"No pude crear el documento en el escritorio: {exc}"}

    if intent == "move":
        import shutil
        src, dst = _resolve(match.group("src")), _resolve(match.group("dst"))
        if not P.path_allowed(src) or not P.path_allowed(dst):
            return {"reply": P.deny_msg(src if not P.path_allowed(src) else dst)}
        if not src.exists():
            return {"reply": f"No encuentro «{src}»."}
        try:
            if dst.is_dir():
                dst = dst / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return {"reply": f"Movido: «{src.name}» → {dst} ✔"}
        except Exception as exc:
            return {"reply": f"No pude mover «{src.name}»: {exc}"}

    if intent == "copy":
        import shutil
        src, dst = _resolve(match.group("src")), _resolve(match.group("dst"))
        if not P.path_allowed(src) or not P.path_allowed(dst):
            return {"reply": P.deny_msg(src if not P.path_allowed(src) else dst)}
        if not src.exists():
            return {"reply": f"No encuentro «{src}»."}
        try:
            if dst.is_dir():
                dst = dst / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(dst))
            return {"reply": f"Copiado: «{src.name}» → {dst} ✔"}
        except Exception as exc:
            return {"reply": f"No pude copiar «{src.name}»: {exc}"}

    if intent == "rename":
        src = _resolve(match.group("src"))
        if not P.path_allowed(src):
            return {"reply": P.deny_msg(src)}
        dst_raw = match.group("dst").strip().strip('"').strip("'").rstrip(".?!")
        if not src.exists():
            return {"reply": f"No encuentro «{src}»."}
        target = _resolve(dst_raw) if ("/" in dst_raw or "\\" in dst_raw) else src.parent / dst_raw
        try:
            src.rename(target)
            return {"reply": f"Renombrado: «{src.name}» → «{target.name}» ✔"}
        except Exception as exc:
            return {"reply": f"No pude renombrar «{src.name}»: {exc}"}

    if intent == "mkdir":
        base, name = _parse_loc_name(match.group("rest"), _desktop())
        if not name:
            return {"reply": "¿Qué nombre le pongo a la carpeta?"}
        target = base / name
        if not P.path_allowed(target):
            return {"reply": P.deny_msg(target)}
        try:
            target.mkdir(parents=True, exist_ok=True)
            return {"reply": f"Carpeta creada: {target} ✔"}
        except Exception as exc:
            return {"reply": f"No he podido crear la carpeta «{name}»: {exc}"}

    if intent == "update":
        path = _resolve(match.group("path"))
        cont = (match.groupdict().get("cont") or "").strip().strip('"\'')
        if not P.path_allowed(path):
            return {"reply": P.deny_msg(path)}
        if not path.is_file():
            return {"reply": f"No encuentro el archivo {path}. Si quieres que lo cree, "
                             f"dime «crea el archivo {path.name}»."}
        if not cont:
            return {"reply": f"¿Qué le añado a «{path.name}»? Dímelo así: "
                             f"«añade al archivo {path.name} que diga ...»."}
        import re as _re
        pisa = bool(_re.search(r"\b(?:actualiza|corrige|modifica|sustituye|reemplaza)\b",
                               text, _re.I)) and not _re.search(r"\b(?:a[ñn]ade|agrega)\b",
                                                                text, _re.I)
        res = FIO.write_text(path, cont, overwrite=pisa, append=not pisa, reason=text)
        if not res["ok"]:
            return {"reply": f"No he podido modificar {path.name}: {res['error']}"}
        que = "reescrito" if pisa else "ampliado"
        return {"reply": f"Archivo {que} y verificado ✔: {res['ruta']} ({res['bytes']} bytes). "
                         f"Guardé la versión anterior — «restaura el archivo {path.name}» "
                         "la devuelve.",
                "files": [{"path": res["ruta"], "action": "modificado"}]}

    if intent == "versions":
        path = _resolve(_g(match, "path", "path2"))
        vs = FIO.versions(path)
        if not vs:
            return {"reply": f"No tengo versiones guardadas de {path.name}. Guardo una copia "
                             "automáticamente cada vez que modifico o sobrescribo un archivo."}
        lines = [f"🗂 Versiones de {path.name}:"]
        lines += [f"   · {v['version']} · {v.get('guardada', '?')} · {v.get('bytes', 0)} bytes"
                  for v in vs[:10]]
        lines.append(f"Para volver a la última: «restaura el archivo {path.name}».")
        return {"reply": "\n".join(lines), "data": {"versions": vs}}

    if intent == "restore_file":
        path = _resolve(match.group("path"))
        if not P.path_allowed(path):
            return {"reply": P.deny_msg(path)}
        vs = FIO.versions(path)
        if not vs:
            return {"reply": f"No tengo ninguna versión anterior de {path.name} que restaurar."}
        from backend.core.comun import confirm
        canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"

        def _restaurar(_p=path):
            r = FIO.restore_version(_p)
            if not r["ok"]:
                return r["error"]
            return (f"Restaurado {r['ruta']} a la versión de {r.get('guardada', '?')}. "
                    "Del estado que tenía justo antes también guardé copia, por si acaso.")
        pregunta = (f"Voy a devolver «{path.name}» a la versión de {vs[0].get('guardada', '?')} "
                    f"({vs[0].get('bytes', 0)} bytes). El contenido de ahora se guarda como copia. "
                    "¿Lo hago? «sí» o «no».")
        return {"reply": confirm.request(channel=canal, kind="restaurar_archivo",
                                         summary=pregunta, action=_restaurar,
                                         request_text=text, targets=[{"path": str(path)}],
                                         cancel_reply=f"Vale, dejo «{path.name}» como está.")}

    if intent == "mkfile":
        import re as _re
        rest = match.group("rest")
        # el CONTENIDO se separa primero («que diga X» / «con el texto X»)
        content = ""
        mc = _re.search(r"\s+(?:que\s+diga|con\s+el\s+(?:texto|contenido))\s+(?P<c>.+)$", rest, _re.I)
        if mc:
            content = mc.group("c").strip().strip('"\'')
            rest = rest[:mc.start()].strip()
        base, name = _parse_loc_name(rest, _desktop())
        if not name:
            return {"reply": "¿Qué nombre le pongo al archivo?"}
        if "." not in name:
            name += ".txt"                       # sin extensión → .txt
        target = base / name
        if not P.path_allowed(target):
            return {"reply": P.deny_msg(target)}
        # v23 (T19/T20/T21): si ya existe NO se pisa a la brava — se pregunta, y al
        # confirmar se guarda antes la versión anterior. Y al crear se VERIFICA.
        res = FIO.write_text(target, content, reason=text)
        if res.get("necesita_confirmacion"):
            from backend.core.comun import confirm
            canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
            actual = res.get("actual", {})

            def _sobrescribir(_t=target, _c=content, _txt=text):
                r2 = FIO.write_text(_t, _c, overwrite=True, reason=_txt)
                if not r2["ok"]:
                    return f"No he podido sobrescribirlo: {r2['error']}"
                return (f"Sobrescrito {r2['ruta']} ({r2['bytes']} bytes, verificado ✔). "
                        f"La versión anterior está a salvo: «restaura el archivo {_t.name}».")
            pregunta = (f"⚠ «{target.name}» YA EXISTE en {target.parent} "
                        f"({actual.get('bytes', '?')} bytes, modificado {actual.get('modificado', '?')}).\n"
                        "Si lo sobrescribo pierdes su contenido actual (guardo copia antes). "
                        "¿Lo sobrescribo? «sí» o «no».")
            return {"reply": confirm.request(channel=canal, kind="sobrescribir_archivo",
                                             summary=pregunta, action=_sobrescribir,
                                             request_text=text,
                                             targets=[{"path": str(target)}],
                                             cancel_reply=f"Vale, dejo «{target.name}» como está."),
                    "data": {"confirm": True}}
        if not res["ok"]:
            return {"reply": f"No he podido crear el archivo «{name}»: {res['error']}"}
        return {"reply": f"Archivo creado y verificado ✔: {res['ruta']}"
                         + (f" ({res['bytes']} bytes)." if content else " (vacío)."),
                "files": [{"path": res["ruta"], "action": "creado"}]}

    if intent == "explore":
        # «qué hay en el escritorio» llena path2, no path
        path = _carpeta(_g(match, "path", "path2"))
        if not P.path_allowed(path):
            return {"reply": P.deny_msg(path)}
        if not path.is_dir():
            return {"reply": f"No encuentro la carpeta {path}. Dime la ruta completa "
                             "o una carpeta conocida (escritorio, documentos, descargas)."}
        items = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:25]
        listing = " · ".join(("📁" if p.is_dir() else "📄") + p.name for p in items)
        return {"reply": f"Contenido de {path.name}/ ({len(items)} mostrados): {listing}"}

    if intent == "search":
        import re as _re
        # el patrón deja pasar el determinante: «en la carpeta Descargas», «en mis documentos»
        base = _carpeta(_re.sub(r"^(?:la\s+carpeta|el\s+(?:disco|directorio)|mis?)\s+", "",
                                match.group("path").strip(), flags=_re.I))
        if not P.path_allowed(base):
            return {"reply": P.deny_msg(base)}
        pat = match.group("pat")
        if not base.is_dir():
            return {"reply": f"No encuentro la carpeta {base}. Dime la ruta completa "
                             "o una carpeta conocida (escritorio, documentos, descargas)."}
        hits = [str(p.relative_to(base)) for p in base.rglob(f"*{pat}*")][:15]
        return {"reply": f"{len(hits)} coincidencias con «{pat}»: " + " · ".join(hits)
                if hits else f"Sin coincidencias con «{pat}» en {base.name}."}

    if intent in ("read", "summarize", "analyze"):
        path = _resolve(_g(match, "path", "path2"))
        if not P.path_allowed(path):
            return {"reply": P.deny_msg(path)}
        if not path.is_file():
            return {"reply": f"No encuentro el archivo {path}."}
        # v23 (T18): lector real — .docx, .pdf, .xlsx y texto. Si no sabe, lo dice.
        res = FIO.read_any(path)
        if not res["ok"]:
            return {"reply": res["error"]}
        content = res["texto"]
        m = res["meta"]
        ficha = (f"{path.name} · {m.get('formato')} · {m.get('bytes', 0)} bytes"
                 + (f" · {m['paginas']} páginas" if m.get("paginas") else "")
                 + (f" · {m['parrafos']} párrafos" if m.get("parrafos") else ""))

        if intent == "read":
            head = "\n".join(content.splitlines()[:20])
            return {"reply": f"Leído {ficha}.\nPrimeras líneas:\n{head}",
                    "data": {"meta": m}}
        if intent == "summarize":
            summary = await _ai_summary(content, "Resume este documento en 4-5 frases en español:")
            return {"reply": f"Resumen de {ficha}:\n{summary}", "data": {"meta": m}}
        # analyze
        lines = content.splitlines()
        loc = len([l for l in lines if l.strip()])
        summary = await _ai_summary(
            content, "Analiza este código: qué hace, calidad y 2 mejoras concretas. Breve:")
        return {"reply": f"{path.name}: {len(lines)} líneas ({loc} con código). {summary}"}

    if intent == "trash":
        # el patrón reparte la ruta entre path/path2/path3/path4 según la forma
        # de la frase; con match.group("path") a secas las tres cuartas partes
        # de las órdenes llegaban con None
        path = _resolve(_g(match, "path", "path2", "path3", "path4"))
        if not P.path_allowed(path):
            return {"reply": P.deny_msg(path)}
        if not path.exists():
            return {"reply": f"No existe {path}. No he borrado nada."}
        from backend.core.comun import confirm
        canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"

        def _a_la_papelera(_p=path):
            try:
                from send2trash import send2trash
            except ImportError:
                return ("Falta send2trash (ejecuta run.bat o «pip install send2trash»). "
                        f"«{_p.name}» sigue donde estaba: no he borrado nada.")
            try:
                send2trash(str(_p))
            except Exception as exc:                       # noqa: BLE001
                return f"No he podido moverlo: {exc}. «{_p.name}» sigue donde estaba."
            return (f"«{_p.name}» está en la papelera del sistema. "
                    "Se recupera desde ahí con «Restaurar».")

        pregunta = (f"🗑 Voy a mandar a la papelera {_ficha_papelera(path)}.\n"
                    "Es recuperable desde la papelera del sistema, pero no lo toco sin tu "
                    "visto bueno. ¿Lo mando? Responde «sí» o «no».")
        return {"reply": confirm.request(
            channel=canal, kind="papelera_archivo", summary=pregunta,
            action=_a_la_papelera, request_text=text,
            targets=[{"path": str(path)}],
            cancel_reply=f"Vale, dejo «{path.name}» donde está."),
            "data": {"confirm": True}}

    if intent == "trash_confirm":
        # el «sí»/«no» lo resuelve backend.core.comun.confirm ANTES del router: si la
        # frase llega hasta aquí es que ya no hay nada armado
        return {"reply": "No hay nada pendiente de mandar a la papelera. "
                         "Dime «borra el archivo <ruta>» y te enseño qué se lleva antes "
                         "de tocar nada."}

    return {"reply": "Orden de archivos no reconocida."}
