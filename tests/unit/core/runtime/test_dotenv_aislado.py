# -*- coding: utf-8 -*-
"""T44: el `.env` del repositorio no entra en un proceso con la config aislada.

`config.py` hacía `load_dotenv(ROOT/".env")` al importarse SIEMPRE, así que
`NEXUS_DB_URL`, `ELEVENLABS_API_KEY`, `CLOUD_LLM_API_KEY` o `TELEGRAM_BOT_TOKEN`
del dueño llegaban a cualquier proceso aunque `NEXUS_CONFIG_DIR` apuntara a una
caja de usar y tirar (una suite llegó a escribir en su Postgres real, L56).

Reglas que se comprueban:
  1. con `NEXUS_CONFIG_DIR` puesto, el `.env` NO se carga;
  2. con `NEXUS_DOTENV=0` (o false/no/off), el `.env` NO se carga;
  3. sin ninguno de los dos, se carga como antes (comportamiento de siempre);
  4. el arranque real del módulo respeta la regla 1 (subproceso);
  5. la batería (`tests/run_all.py`) apaga el `.env` para cada suite.

No lee ni escribe el `.env`, la config ni los datos del operador: el `.env` de
prueba vive en una carpeta temporal y el subproceso arranca con config/datos de
usar y tirar y sin `NEXUS_DB_URL` heredada.

Ejecutar:  python tests/unit/core/runtime/test_dotenv_aislado.py   (desde la carpeta nexus)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

_fail = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


# Este proceso también va aislado antes de importar config: si no, el propio
# import cargaría el `.env` real del dueño.
_CFG = tempfile.mkdtemp(prefix="nexus_t44_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_t44_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA
os.environ.pop("NEXUS_DB_URL", None)

from backend.core.comun import config  # noqa: E402

try:
    import dotenv  # noqa: F401
    _HAY_DOTENV = True
except ImportError:
    _HAY_DOTENV = False

_SENTINELA = "NEXUS_T44_SENTINELA"


def _env_temporal():
    d = Path(tempfile.mkdtemp(prefix="nexus_t44_env_"))
    p = d / ".env"
    p.write_text(f"{_SENTINELA}=del-env-de-prueba\n", encoding="utf-8")
    return p


print("== T44: el .env solo entra cuando la config NO esta aislada ==")

check(hasattr(config, "cargar_dotenv"), "config expone cargar_dotenv(ruta, entorno)")
check(hasattr(config, "DOTENV_CARGADO"), "config expone DOTENV_CARGADO")

if hasattr(config, "cargar_dotenv"):
    # 1) config aislada -> no se carga
    os.environ.pop(_SENTINELA, None)
    r = config.cargar_dotenv(_env_temporal(), {"NEXUS_CONFIG_DIR": "C:/caja"})
    check(r is False, f"con NEXUS_CONFIG_DIR devuelve False (dio {r!r})")
    check(_SENTINELA not in os.environ, "con NEXUS_CONFIG_DIR el .env no toca os.environ")

    # 2) opt-out explicito, en sus formas
    for valor in ("0", "false", "no", "off", "OFF", " 0 "):
        os.environ.pop(_SENTINELA, None)
        r = config.cargar_dotenv(_env_temporal(), {"NEXUS_DOTENV": valor})
        check(r is False, f"NEXUS_DOTENV={valor!r} devuelve False (dio {r!r})")
        check(_SENTINELA not in os.environ, f"NEXUS_DOTENV={valor!r} no toca os.environ")

    # 3) comportamiento de siempre: sin aislamiento ni opt-out, se carga
    os.environ.pop(_SENTINELA, None)
    for entorno in ({}, {"NEXUS_DOTENV": "1"}, {"NEXUS_CONFIG_DIR": "  "}):
        os.environ.pop(_SENTINELA, None)
        r = config.cargar_dotenv(_env_temporal(), entorno)
        if _HAY_DOTENV:
            check(r is True, f"entorno {entorno!r}: el .env se carga (dio {r!r})")
            check(os.environ.get(_SENTINELA) == "del-env-de-prueba",
                  f"entorno {entorno!r}: la variable del .env llega a os.environ")
        else:
            print("  AVISO: python-dotenv no instalado; la regla 3 no se puede probar")
    os.environ.pop(_SENTINELA, None)

    # Un .env que no existe sigue sin romper nada
    r = config.cargar_dotenv(Path(_CFG) / "no-existe.env", {})
    check(r is False, f".env inexistente devuelve False sin excepcion (dio {r!r})")

# 4) el arranque real del modulo, en un proceso nuevo con config aislada
print("== T44: import real de config con NEXUS_CONFIG_DIR aislado ==")
_env = {k: v for k, v in os.environ.items()
        if k not in ("NEXUS_DB_URL", "NEXUS_DOTENV", _SENTINELA)}
_env.update({"NEXUS_CONFIG_DIR": tempfile.mkdtemp(prefix="nexus_t44_sub_cfg_"),
             "NEXUS_DATA_DIR": tempfile.mkdtemp(prefix="nexus_t44_sub_data_"),
             "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
codigo = ("import os, sys; sys.path.insert(0, sys.argv[1]);"
          "from backend.core.comun import config;"
          "print(getattr(config, 'DOTENV_CARGADO', 'SIN-ATRIBUTO'));"
          "print('NEXUS_DB_URL' in os.environ)")
p = subprocess.run([sys.executable, "-c", codigo, str(ROOT)], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", env=_env,
                   cwd=tempfile.gettempdir(), timeout=120)
lineas = p.stdout.strip().splitlines()
check(p.returncode == 0, f"el subproceso importa config sin error (rc={p.returncode}, err={p.stderr[-300:]!r})")
check(lineas[:1] == ["False"], f"DOTENV_CARGADO es False con config aislada (salida {lineas!r})")
check(lineas[1:2] == ["False"], f"NEXUS_DB_URL no aparece en el proceso aislado (salida {lineas!r})")

# 5) la bateria apaga el .env para cada suite
print("== T44: tests/run_all.py apaga el .env ==")
_runner = (ROOT / "tests" / "run_all.py").read_text(encoding="utf-8")
check('"NEXUS_DOTENV": "0"' in _runner, 'run_all.py pasa "NEXUS_DOTENV": "0" a cada suite')
check('os.environ["NEXUS_DOTENV"] = "0"' in _runner, "run_all.py apaga el .env en su propio proceso")

print(f"\n{_pass} OK / {len(_fail)} FALLOS")
sys.exit(1 if _fail else 0)
