"""
nexus — Permisos estilo sandbox (se eligen en la instalación y en ⚙).

* perm_hardware  → ¿puede leer CPU/RAM/placa/discos/temperaturas del equipo?
* perm_files     → alcance del acceso a archivos:
      'sandbox'  : SOLO su propia carpeta (data/sandbox junto a la instalación)
      'carpetas' : solo las carpetas de la lista perm_folders
      'todo'     : todo el equipo (como hasta ahora)

Las skills de archivos/memoria pasan cada ruta por path_allowed() antes de
tocar nada, y el informe de hardware se corta si perm_hardware está apagado.
"""
from __future__ import annotations

from pathlib import Path

from .config import DATA_DIR, settings

SANDBOX_DIR = DATA_DIR / "sandbox"


def hardware_allowed() -> bool:
    return bool(settings.get("perm_hardware", True))


HW_DENIED = ("No tengo permiso para leer el hardware de este equipo. "
             "Actívalo en ⚙ → Permisos si quieres que lo vea.")


def files_mode() -> str:
    m = str(settings.get("perm_files", "todo")).lower()
    return m if m in ("sandbox", "carpetas", "todo") else "todo"


def _allowed_roots() -> list[Path]:
    roots = [SANDBOX_DIR]
    if files_mode() == "carpetas":
        for raw in settings.get("perm_folders", []) or []:
            try:
                roots.append(Path(str(raw)).expanduser().resolve())
            except Exception:
                continue
    return roots


def path_allowed(p) -> bool:
    """¿Puede nexus leer/escribir en esta ruta con los permisos actuales?"""
    mode = files_mode()
    if mode == "todo":
        return True
    try:
        rp = Path(p).expanduser().resolve()
    except Exception:
        return False
    for root in _allowed_roots():
        try:
            rp.relative_to(root.resolve())
            return True
        except Exception:
            continue
    return False


def deny_msg(p) -> str:
    mode = files_mode()
    if mode == "sandbox":
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        return (f"No tengo permiso para tocar «{p}»: estoy en modo SANDBOX y solo "
                f"puedo trabajar dentro de {SANDBOX_DIR}. Cambia el alcance en ⚙ → Permisos.")
    return (f"No tengo permiso para tocar «{p}»: solo puedo trabajar en las carpetas "
            "autorizadas. Añádela en ⚙ → Permisos → Carpetas permitidas.")
