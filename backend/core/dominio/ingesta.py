"""
nexus — Ingesta dirigida de carpetas (002-memoria-y-conocimiento, bloque C).

`ingerir_carpeta(ruta)` recorre TODOS los archivos que `files_io.puede_leer()`
sepa leer dentro de una carpeta, uno a uno:

  1. Los lee ENTEROS (`read_any(f, limite=0)`); si algo sale truncado se
     rechaza ESE archivo (no se mete a medias).
  2. Escribe un espejo `.md` en `data/memory/documentos/{dominio}/` con una
     cabecera de metadatos (origen, dominio, etiqueta, fecha) — NUNCA
     escribe en la carpeta origen (regla: solo lectura por defecto).
  3. Trocea (`rag.trocear()`, o `rag.trocear_xlsx_estructurado()` para
     `.xlsx`) y guarda cada trozo en Postgres vía `memory.pg.remember()`,
     que ya es IDEMPOTENTE por huella — ingerir la misma carpeta dos veces
     no duplica nada (memoria-deduplicacion, ya cubierto por el bloque A).

`dominio` sale del nombre de la carpeta (slugificado): «Wabiks Content OS»
→ «wabiks-content-os». `etiqueta`/`peso`: si el NOMBRE del archivo contiene
alguna de `memoria.ingesta.marcas_historico` ("antiguo", "historico",
"obsoleto"), se marca 'historico' con `memoria.pesos.historico` (0.6);
si no, 'normal' con `memoria.pesos.normal` (1.0) — así un documento marcado
histórico nunca gana al definitivo en `recall()` (decisión de diseño 6).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from . import rag
from ..infraestructura import files_io
from ..comun import permissions
from ..comun.config import CONFIG_DIR, DATA_DIR

DOCUMENTOS_DIR = DATA_DIR / "memory" / "documentos"


def _slug(nombre: str) -> str:
    s = nombre.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "sin-clasificar"


# Archivos que casi seguro contienen secretos: NUNCA entran en la memoria ni en el espejo,
# porque lo guardado se inyecta después en el contexto de los agentes.
_EXT_SECRETA = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk", ".gpg", ".asc"}
_NOMBRE_SECRETO = re.compile(
    r"^("
    r"\.env(\..*)?|.*\.env|"                                    # .env, .env.local, prod.env
    r"id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|"                       # claves SSH
    r"\.netrc|\.npmrc|\.pypirc|\.htpasswd|"
    r"(credentials?|secrets?|tokens?|passwords?|api[_-]?keys?)(\..*)?|"   # nombre = palabra
    r".*[_-](credentials?|secrets?|tokens?|passwords?|api[_-]?keys?)(\..*)?"  # prod_secrets.txt
    r")$", re.IGNORECASE)
_CLAVE_PRIVADA = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")


def _motivo_secreto(f: Path, texto: str | None = None) -> str:
    """'' si el archivo parece inocuo; si no, el motivo por el que se omite."""
    if f.suffix.lower() in _EXT_SECRETA or _NOMBRE_SECRETO.match(f.name):
        return f"«{f.name}» parece contener secretos (claves, tokens o credenciales)."
    if texto is not None and _CLAVE_PRIVADA.search(texto):
        return f"«{f.name}» contiene una clave privada."
    return ""


def _config_ingesta() -> dict:
    reserva = {"marcas_historico": ["antiguo", "historico", "obsoleto"]}
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get(
                "memoria", {}).get("ingesta") or {}
            if isinstance(leido.get("marcas_historico"), list):
                reserva["marcas_historico"] = [str(m).lower() for m in leido["marcas_historico"]]
    except Exception:
        pass
    return reserva


def _pesos() -> dict:
    reserva = {"normal": 1.0, "historico": 0.6}
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("memoria", {}).get("pesos") or {}
            for k in reserva:
                v = leido.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    reserva[k] = float(v)
    except Exception:
        pass
    return reserva


def ingerir_carpeta(ruta: str) -> dict:
    """Ingiere TODOS los archivos legibles de una carpeta (recursivo) y deja la
    memoria IGUAL que la carpeta: lo que cambió se SOBRESCRIBE por origen (los
    trozos viejos de ese archivo se retiran a la papelera, reversible) y lo que
    se borró de la carpeta también se retira. Los trozos sin cambios no se tocan.
    Devuelve {"ok", "dominio", "documentos": [...], "retirados", "lote", "error"}."""
    if not ruta:
        return {"ok": False, "error": "falta «ruta»", "documentos": []}
    if not permissions.path_allowed(ruta):
        return {"ok": False, "error": permissions.deny_msg(ruta), "documentos": []}
    try:
        base = Path(ruta).expanduser().resolve()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "documentos": []}
    if not base.is_dir():
        return {"ok": False, "error": f"«{ruta}» no es una carpeta.", "documentos": []}

    from .memory import pg  # import diferido: evita ciclo de import al cargar el módulo

    if not pg.online:
        # Sin memoria no hay ingesta: escribir solo el espejo y decir «ok» sería mentir.
        return {"ok": False, "documentos": [],
                "error": "La memoria (Postgres) no está disponible: no ingerí nada. "
                         "Arranca la base de datos y repite."}

    dominio = _slug(base.name)
    marcas = _config_ingesta()["marcas_historico"]
    pesos = _pesos()
    documentos = []
    existentes: set[str] = set()                 # archivos que siguen en la carpeta y no son secretos
    contenidos: dict[str, set[str]] = {}         # origen -> trozos vigentes (solo si se procesó bien)
    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        # Contención POR ARCHIVO: un enlace simbólico dentro de la carpeta puede
        # apuntar fuera; se comprueba la ruta REAL, no la que se ve.
        try:
            real = f.resolve()
            real.relative_to(base)
            dentro = permissions.path_allowed(real)
        except (ValueError, OSError):
            dentro = False
        if not dentro:
            documentos.append({"archivo": f.name, "ok": False, "omitido": "fuera_de_la_carpeta",
                                "error": f"«{f.name}» apunta fuera de la carpeta o de lo permitido. "
                                         "No lo leí."})
            continue
        motivo_secreto = _motivo_secreto(f)
        if motivo_secreto:
            documentos.append({"archivo": f.name, "ok": False, "omitido": "secreto",
                                "error": motivo_secreto + " No lo guardé en memoria."})
            continue
        ok, _motivo = files_io.puede_leer(f)
        if not ok:
            continue
        existentes.add(str(f))
        leido = files_io.read_any(f, limite=0)
        if not leido.get("ok") or leido.get("meta", {}).get("truncado"):
            documentos.append({"archivo": f.name, "ok": False,
                                "error": leido.get("error") or "truncado"})
            continue
        texto = leido["texto"]
        motivo_secreto = _motivo_secreto(f, texto)
        if motivo_secreto:
            existentes.discard(str(f))           # pasó a ser secreto: lo ya guardado se retira
            documentos.append({"archivo": f.name, "ok": False, "omitido": "secreto",
                                "error": motivo_secreto + " No lo guardé en memoria."})
            continue
        historico = any(marca in f.name.lower() for marca in marcas)
        etiqueta = "historico" if historico else "normal"
        peso = pesos["historico"] if historico else pesos["normal"]

        # 1) espejo .md CON cabecera de metadatos — nunca en la carpeta origen.
        # El nombre sale de la ruta relativa COMPLETA (con extensión): dos archivos
        # distintos nunca comparten espejo (antes `f.stem` hacía que se pisaran).
        destino_dir = DOCUMENTOS_DIR / dominio
        destino_dir.mkdir(parents=True, exist_ok=True)
        cabecera = (f"---\norigen: {f}\ndominio: {dominio}\netiqueta: {etiqueta}\n"
                    f"ingerido: {dt.datetime.now(dt.timezone.utc).isoformat()}\n---\n\n")
        destino = destino_dir / (f.relative_to(base).as_posix().replace("/", "__") + ".md")
        destino.write_text(cabecera + texto, encoding="utf-8")

        # 2) trocear y guardar en Postgres (idempotente por huella — SIN esto
        # ingerir la carpeta dos veces duplicaría cada trozo, como le pasó al
        # bloque A con las 3 filas huérfanas 804/805/807).
        trozos_nuevos, trozos_dup = 0, 0
        if f.suffix.lower() == ".xlsx":
            hojas = files_io.leer_xlsx_estructurado(f)
            trozos = rag.trocear_xlsx_estructurado(hojas)
        else:
            trozos = rag.trocear(texto)
        vigentes_f: set[str] = set()
        for trozo in trozos:
            contenido = f"[{f.name}] {trozo['texto']}"
            vigentes_f.add(contenido)
            res = pg.remember(contenido, kind="knowledge",
                               tags=[dominio, f.stem], origen=str(f), origen_tipo="documento",
                               dominio=dominio, etiqueta=etiqueta, peso=peso)
            if res.get("duplicado"):
                trozos_dup += 1
            else:
                trozos_nuevos += 1
        contenidos[str(f)] = vigentes_f
        documentos.append({"archivo": f.name, "ok": True, "etiqueta": etiqueta,
                            "trozos_nuevos": trozos_nuevos, "trozos_duplicados": trozos_dup,
                            "trozos_retirados": 0, "espejo": str(destino)})

    # 3) SOBRESCRIBIR por origen. Se hace DESPUÉS de guardar lo nuevo (si algo falla
    # antes, lo viejo sigue ahí) y retira, nunca borra: `restaurar_filas(lote)` lo revierte.
    # Se retira un trozo si (a) su archivo ya no existe / pasó a ser secreto, o (b) su
    # archivo se procesó bien y ese trozo ya no está en su contenido NI en el de ningún
    # otro archivo de esta ingesta. Un archivo que existe pero no se pudo leer NO se toca.
    vigentes_todos = set().union(*contenidos.values()) if contenidos else set()
    prefijo = str(base) + os.sep
    obsoletas: list[int] = []
    por_origen: dict[str, int] = {}
    for fila in pg.filas_documento_bajo(prefijo):
        origen = fila["origen"]
        sigue = origen in existentes
        if sigue and (origen not in contenidos or fila["content"] in contenidos[origen]
                      or fila["content"] in vigentes_todos):
            continue
        obsoletas.append(fila["id"])
        por_origen[origen] = por_origen.get(origen, 0) + 1
    lote = ""
    retirados = 0
    if obsoletas:
        lote = f"ingesta-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}-{dominio}"
        retirados = pg.retirar_filas(obsoletas, lote)
        por_nombre = {d["archivo"]: d for d in documentos if d.get("ok")}
        for origen, n in por_origen.items():
            nombre = Path(origen).name
            if origen in contenidos and nombre in por_nombre:
                por_nombre[nombre]["trozos_retirados"] += n
            else:
                documentos.append({"archivo": nombre, "ok": True, "eliminado": True,
                                    "trozos_retirados": n})
    return {"ok": True, "dominio": dominio, "documentos": documentos,
            "retirados": retirados, "lote": lote, "error": ""}
