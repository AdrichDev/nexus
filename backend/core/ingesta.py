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
import re
from pathlib import Path

from . import files_io, rag
from .comun import permissions
from .comun.config import CONFIG_DIR, DATA_DIR

DOCUMENTOS_DIR = DATA_DIR / "memory" / "documentos"


def _slug(nombre: str) -> str:
    s = nombre.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "sin-clasificar"


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
    """Ingiere TODOS los archivos legibles de una carpeta (recursivo).
    Devuelve {"ok", "dominio", "documentos": [...], "error"}."""
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

    dominio = _slug(base.name)
    marcas = _config_ingesta()["marcas_historico"]
    pesos = _pesos()
    documentos = []
    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        ok, _motivo = files_io.puede_leer(f)
        if not ok:
            continue
        leido = files_io.read_any(f, limite=0)
        if not leido.get("ok") or leido.get("meta", {}).get("truncado"):
            documentos.append({"archivo": f.name, "ok": False,
                                "error": leido.get("error") or "truncado"})
            continue
        texto = leido["texto"]
        historico = any(marca in f.name.lower() for marca in marcas)
        etiqueta = "historico" if historico else "normal"
        peso = pesos["historico"] if historico else pesos["normal"]

        # 1) espejo .md CON cabecera de metadatos — nunca en la carpeta origen
        destino_dir = DOCUMENTOS_DIR / dominio
        destino_dir.mkdir(parents=True, exist_ok=True)
        cabecera = (f"---\norigen: {f}\ndominio: {dominio}\netiqueta: {etiqueta}\n"
                    f"ingerido: {dt.datetime.now(dt.timezone.utc).isoformat()}\n---\n\n")
        destino = destino_dir / f"{f.stem}.md"
        destino.write_text(cabecera + texto, encoding="utf-8")

        # 2) trocear y guardar en Postgres (idempotente por huella — SIN esto
        # ingerir la carpeta dos veces duplicaría cada trozo, como le pasó al
        # bloque A con las 3 filas huérfanas 804/805/807).
        trozos_nuevos, trozos_dup = 0, 0
        if pg.online:
            if f.suffix.lower() == ".xlsx":
                hojas = files_io.leer_xlsx_estructurado(f)
                trozos = rag.trocear_xlsx_estructurado(hojas)
            else:
                trozos = rag.trocear(texto)
            for trozo in trozos:
                res = pg.remember(f"[{f.name}] {trozo['texto']}", kind="knowledge",
                                   tags=[dominio, f.stem], origen=str(f), origen_tipo="documento",
                                   dominio=dominio, etiqueta=etiqueta, peso=peso)
                if res.get("duplicado"):
                    trozos_dup += 1
                else:
                    trozos_nuevos += 1
        documentos.append({"archivo": f.name, "ok": True, "etiqueta": etiqueta,
                            "trozos_nuevos": trozos_nuevos, "trozos_duplicados": trozos_dup,
                            "espejo": str(destino)})
    return {"ok": True, "dominio": dominio, "documentos": documentos, "error": ""}
