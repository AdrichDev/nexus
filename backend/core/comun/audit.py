"""
nexus — REGISTRO DE AUDITORÍA (specs v23, TAREA 24).

Cada acción relevante —y OBLIGATORIAMENTE toda acción destructiva— deja una
línea en data/logs/audit.jsonl con quién la pidió, qué se interpretó, qué
confirmación hubo, qué se ejecutó y con qué resultado.

Reglas fijadas con Adri:
  * Esto NO sustituye a la papelera ni a la base de datos: es la traza de
    «por qué pasó», no el sitio del que se restaura.
  * Tampoco se confunde con los recuerdos de Engram (memoria de comportamiento).
  * Escritura blindada: si el log falla, la operación NO se cae por ello.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading

from .config import DATA_DIR
from . import secretos

AUDIT_FILE = DATA_DIR / "logs" / "audit.jsonl"
_MAX_BYTES = 2_000_000          # ~2 MB → se rota a .1
_lock = threading.Lock()


def _texto_redactado(valor: str, limite: int) -> str:
    """El texto libre del registro: REDACTADO y luego recortado.

    AI-02/PRIV-01 de la auditoría del 30/07/2026: `request`, `interpreted`,
    `result` y `error` se guardaban en crudo, así que una contraseña dictada o
    una cadena de conexión pegada en una orden acababan en un fichero que nadie
    limpia nunca. Ahora pasan por `secretos.redactar()`, la misma función que ya
    protege la memoria y el RAG.

    FAIL CLOSED: si la redacción falla, el campo se guarda VACÍO. Se pierde la
    traza de ese texto —queda el resto del registro: acción, actor, resultado
    destructivo sí/no, run_id— pero no se escribe ni un carácter en crudo. Una
    auditoría que para no perder detalle filtra una clave no es una auditoría.
    """
    limpio = secretos.redactar_seguro(valor or "")
    if limpio is None:
        return ""                 # no se pudo limpiar → no se escribe
    return limpio[:limite]


def _rotate() -> None:
    try:
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > _MAX_BYTES:
            old = AUDIT_FILE.with_suffix(".jsonl.1")
            if old.exists():
                old.unlink()
            os.replace(AUDIT_FILE, old)
    except Exception:
        pass


def log(action: str, *, actor: str = "nexus", request: str = "",
        interpreted: str = "", agent: str = "nexus", destructive: bool = False,
        confirmed: bool | None = None, targets: list | None = None,
        result: str = "", error: str = "", run_id: str = "",
        channel: str = "", extra: dict | None = None) -> dict:
    """Apunta una acción. Devuelve el registro escrito (o el dict aunque falle)."""
    rec = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "actor": actor,                 # quién lo pidió (operador | scheduler | hermes…)
        "agent": agent,                 # quién lo ejecutó (nexus | hermes)
        "request": _texto_redactado(request, 400),
        "interpreted": _texto_redactado(interpreted, 400),
        "destructive": bool(destructive),
        "confirmed": confirmed,
        "targets": (targets or [])[:60],
        "result": _texto_redactado(result, 400),
        "error": _texto_redactado(error, 400),
        "run_id": run_id,
        "channel": channel,
    }
    if extra:
        rec["extra"] = extra
    try:
        with _lock:
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _rotate()
            with AUDIT_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def tail(n: int = 20, destructive_only: bool = False) -> list[dict]:
    """Últimos n registros (los más recientes al final)."""
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for ln in lines[-2000:]:
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        if destructive_only and not rec.get("destructive"):
            continue
        out.append(rec)
    return out[-n:]
