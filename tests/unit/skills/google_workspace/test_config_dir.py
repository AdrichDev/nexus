# -*- coding: utf-8 -*-
"""Las rutas de `config/` de tres skills obedecen a `NEXUS_CONFIG_DIR` (T39b).

EL FALLO QUE ESTA SUITE CIERRA. `skills/google_workspace/skill.py`,
`skills/autoprovision/skill.py` y el respaldo de `skills/instagram/analisis.py`
montaban sus rutas a mano con `Path(__file__).resolve().parents[2] / "config"`.
Eso IGNORA `NEXUS_CONFIG_DIR`, así que una prueba (o un arranque aislado) con
carpeta de usar y tirar seguía mirando el `config/` REAL del operador. En
google_workspace no es solo lectura: `google_token.json` se ESCRIBE ahí
(`TOKEN_FILE.write_text(...)`, al refrescar y al autorizar), o sea que un proceso
aislado podía sobrescribir el token del dueño. Es el mismo fallo de hermeticidad
que T36 cerró en `spotify.py` y T39 en `skills/mcp_hands/skill.py`: la ruta sale
de `backend.core.comun.config.CONFIG_DIR`, única fuente de verdad.

QUÉ ES DEL OPERADOR Y QUÉ ES PLANTILLA (se decide fichero a fichero en
autoprovision, y aquí se comprueba esa decisión):
  * `config/docker-compose.yml` — NO versionado (`git ls-files config/` no lo
    lista; lo genera nexus en la config del operador). Sigue `CONFIG_DIR`.
  * `config/n8n_flujo_nexus.json` — NO versionado: lo deja el operador. Sigue
    `CONFIG_DIR`.
  * `config/n8n_flujo_ejemplo.json` — SÍ versionado: plantilla de solo lectura
    que viaja con el repo. Tiene que seguir resolviéndose a la copia del repo
    aunque `NEXUS_CONFIG_DIR` apunte a otra carpeta, o la skill se queda sin
    workflow que importar.

CÓMO SE PRUEBA, y por qué hay un subproceso:
  1. En ESTE proceso las tres skills se cargan con `NEXUS_CONFIG_DIR` y
     `NEXUS_DATA_DIR` apuntando a una carpeta temporal puesta ANTES del import
     (las rutas se resuelven al importar, igual que en `comun/config.py`), y se
     comprueba que ni una ruta cae en el `config/` del operador.
  2. El comportamiento de SIEMPRE (sin la variable) se mide en un SUBPROCESO con
     `NEXUS_CONFIG_DIR` borrada: allí solo se imprimen las rutas calculadas y se
     comparan con `ROOT/config/…` carácter a carácter. No se abre ningún fichero
     real: el subproceso no lee ni escribe el `config/` del dueño.
  3. El respaldo de instagram se prueba igual de aislado, con `backend`
     bloqueado a propósito (que es lo que hacen `test_analisis`, `test_spec`,
     `test_competencia` y `test_inteligencia`): el respaldo NO puede ser mudo.

SIN RED, SIN GOOGLE, SIN DOCKER, SIN N8N. No se llama a ninguna API: solo se
miran las rutas y se leen umbrales de la carpeta temporal.

Ejecutar: .venv\\Scripts\\python.exe tests\\unit\\skills\\google_workspace\\test_config_dir.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REAL_CONFIG = ROOT / "config"

# La caja aislada se crea y se declara ANTES de importar ninguna skill: las
# rutas se resuelven al importar, y un import perezoso llegaría tarde.
_TMP = tempfile.TemporaryDirectory(prefix="nexus_config_dir_")
CFG = Path(_TMP.name) / "config"
DATA = Path(_TMP.name) / "data"
CFG.mkdir()
DATA.mkdir()
os.environ["NEXUS_CONFIG_DIR"] = str(CFG)
os.environ["NEXUS_DATA_DIR"] = str(DATA)
os.environ["NEXUS_DOTENV"] = "0"

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def _carga(carpeta, fichero="skill.py", nombre="mod"):
    """Carga `skills/<carpeta>/<fichero>` del disco, sin `skills_loader` (que
    arrastraría las 32 skills solo para leer tres rutas)."""
    ruta = ROOT / "skills" / carpeta / fichero
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GW = _carga("google_workspace", nombre="gw_config_dir")
AP = _carga("autoprovision", nombre="ap_config_dir")
IG = _carga("instagram", "analisis.py", nombre="ig_config_dir")


# ═══════════ 1) google_workspace: credenciales, token y umbrales ════════════
def test_google_workspace_usa_la_config_aislada():
    print("== 1) google_workspace: credenciales, token y umbrales en la caja aislada ==")
    check(Path(GW.CONFIG_DIR) == CFG,
          f"CONFIG_DIR sigue fuera de NEXUS_CONFIG_DIR: {GW.CONFIG_DIR}")
    check(Path(GW.CREDS_FILE) == CFG / "google_credentials.json",
          f"CREDS_FILE no sale de CONFIG_DIR: {GW.CREDS_FILE}")
    check(Path(GW.TOKEN_FILE) == CFG / "google_token.json",
          f"TOKEN_FILE no sale de CONFIG_DIR: {GW.TOKEN_FILE}")
    # El token se ESCRIBE: si apunta al config/ real, un proceso aislado pisa el
    # del operador (el fallo exacto de T36 en spotify.py).
    check(Path(GW.TOKEN_FILE).parent == CFG,
          f"el token se escribiría en el config/ del operador: {GW.TOKEN_FILE}")
    for nombre, ruta in (("CONFIG_DIR", GW.CONFIG_DIR), ("CREDS_FILE", GW.CREDS_FILE),
                         ("TOKEN_FILE", GW.TOKEN_FILE)):
        check(str(REAL_CONFIG) not in str(ruta),
              f"{nombre} nombra el config/ real del operador: {ruta}")

    # Los umbrales se leen EN CADA LLAMADA por CONFIG_DIR (no están a fuego).
    (CFG / "umbrales.json").write_text(json.dumps(
        {"correos": {"max_por_pasada": 7}, "drive": {"carpeta": "CARPETA-DE-PRUEBA"}}),
        encoding="utf-8")
    check(GW._carga_correos()["max_por_pasada"] == 7,
          f"los correos no se leen de la config aislada: {GW._carga_correos()['max_por_pasada']}")
    check(GW._umbrales_drive()["carpeta"] == "CARPETA-DE-PRUEBA",
          f"Drive no lee umbrales.json de la config aislada: {GW._umbrales_drive()}")


# ═══ 2) autoprovision: qué escribe el operador y qué es plantilla del repo ══
def test_autoprovision_separa_operador_de_plantilla():
    print("== 2) autoprovision: compose y flujo del operador vs plantilla versionada ==")
    check(Path(getattr(AP, "_COMPOSE_OPERADOR", CFG / "?")) == CFG / "docker-compose.yml",
          f"el docker-compose del operador no sale de CONFIG_DIR: "
          f"{getattr(AP, '_COMPOSE_OPERADOR', None)}")
    check(Path(getattr(AP, "N8N_FLUJO_OPERADOR", CFG / "?")) == CFG / "n8n_flujo_nexus.json",
          f"el flujo n8n del operador no sale de CONFIG_DIR: "
          f"{getattr(AP, 'N8N_FLUJO_OPERADOR', None)}")
    # La plantilla SÍ versionada sigue siendo la que viaja con el repo.
    plantilla = getattr(AP, "N8N_FLUJO_PLANTILLA", None)
    check(plantilla is not None and Path(plantilla) == REAL_CONFIG / "n8n_flujo_ejemplo.json",
          f"la plantilla versionada dejó de resolver al repo: {plantilla}")
    check(plantilla is not None and Path(plantilla).is_file(),
          f"la plantilla versionada no existe: {plantilla}")

    # Sin flujo propio, `_n8n_workflow_file()` cae en la plantilla del repo.
    elegido = AP._n8n_workflow_file() if hasattr(AP, "_n8n_workflow_file") else None
    check(elegido is not None and Path(elegido) == REAL_CONFIG / "n8n_flujo_ejemplo.json",
          f"sin flujo propio no se usa la plantilla versionada: {elegido}")

    # Con un flujo propio en la carpeta temporal, se usa ESE y no la plantilla.
    propio = CFG / "n8n_flujo_nexus.json"
    propio.write_text("{}", encoding="utf-8")
    try:
        elegido = AP._n8n_workflow_file() if hasattr(AP, "_n8n_workflow_file") else None
        check(elegido is not None and Path(elegido) == propio,
              f"el flujo del operador no se lee de su config: {elegido}")
    finally:
        propio.unlink()

    # Y el compose: el del operador es el primero de la lista de preferencia.
    compose = CFG / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")
    try:
        elegido = AP._compose_file()
        check(elegido is not None and Path(elegido) == compose,
              f"no prefiere el compose del operador: {elegido}")
    finally:
        compose.unlink()


# ═══════════ 3) instagram: los umbrales del motor de análisis ═══════════════
def test_instagram_lee_umbrales_de_la_config_aislada():
    print("== 3) instagram: ruta_umbrales() honra NEXUS_CONFIG_DIR ==")
    check(Path(IG.ruta_umbrales()) == CFG / "umbrales.json",
          f"ruta_umbrales() sigue en el config/ real: {IG.ruta_umbrales()}")
    check(str(REAL_CONFIG) not in str(IG.ruta_umbrales()),
          f"ruta_umbrales() nombra el config/ real: {IG.ruta_umbrales()}")
    (CFG / "umbrales.json").write_text(json.dumps(
        {"gancho": {"max_palabras": 9}}), encoding="utf-8")
    IG._cache_archivo = None                     # releer el fichero de la caja
    check(IG.cargar_umbrales()["gancho"]["max_palabras"] == 9,
          "el análisis no lee los umbrales de la config aislada")


# ═══ 4) LO DE SIEMPRE: sin NEXUS_CONFIG_DIR la ruta es ROOT/config exacta ═══
GUION_SIN_VARIABLE = r'''
import importlib.util, json, sys
from pathlib import Path
RAIZ = Path(sys.argv[1])
sys.path.insert(0, str(RAIZ))


def carga(carpeta, fichero="skill.py", nombre="mod"):
    spec = importlib.util.spec_from_file_location(
        nombre, RAIZ / "skills" / carpeta / fichero)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gw = carga("google_workspace", nombre="gw_sin_variable")
ap = carga("autoprovision", nombre="ap_sin_variable")
ig = carga("instagram", "analisis.py", nombre="ig_sin_variable")
print(json.dumps({
    "gw_config": str(getattr(gw, "CONFIG_DIR", "")),
    "gw_creds": str(getattr(gw, "CREDS_FILE", "")),
    "gw_token": str(getattr(gw, "TOKEN_FILE", "")),
    "ap_compose": str(getattr(ap, "_COMPOSE_OPERADOR", "")),
    "ap_flujo_operador": str(getattr(ap, "N8N_FLUJO_OPERADOR", "")),
    "ap_flujo_plantilla": str(getattr(ap, "N8N_FLUJO_PLANTILLA", "")),
    "ig_umbrales": str(ig.ruta_umbrales()),
}))
'''

# El respaldo de instagram con `backend` bloqueado (lo que hacen cuatro suites
# del repo). También aislado: si el respaldo fuera mudo, esto leería el
# config/umbrales.json del operador.
GUION_SIN_BACKEND = r'''
import importlib.util, json, sys
from pathlib import Path
RAIZ = Path(sys.argv[1])
sys.path.insert(0, str(RAIZ))
sys.modules["backend"] = None
spec = importlib.util.spec_from_file_location(
    "ig_sin_backend", RAIZ / "skills" / "instagram" / "analisis.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps({"umbrales": str(mod.ruta_umbrales())}))
'''


def _subproceso(guion: str, *extra, con_config: bool) -> dict:
    """Lanza `guion` con un entorno SIN el `.env` del operador. Con
    `con_config=False` se borra `NEXUS_CONFIG_DIR` para medir el camino de
    siempre; el `NEXUS_DATA_DIR` es siempre una carpeta de usar y tirar."""
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("NEXUS_CONFIG_DIR", "NEXUS_DATA_DIR", "NEXUS_DOTENV")}
    entorno.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                    "NEXUS_DOTENV": "0",
                    "NEXUS_DATA_DIR": tempfile.mkdtemp(prefix="nexus_cfg_sub_data_")})
    if con_config:
        entorno["NEXUS_CONFIG_DIR"] = str(CFG)
    r = subprocess.run([sys.executable, "-c", guion, str(ROOT), *extra],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=entorno, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"subproceso falló ({r.returncode}): {r.stdout[-500:]}{r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_sin_la_variable_las_rutas_son_las_de_siempre():
    print("== 4) sin NEXUS_CONFIG_DIR: ROOT/config, carácter a carácter ==")
    rutas = _subproceso(GUION_SIN_VARIABLE, con_config=False)
    esperado = {
        "gw_config": REAL_CONFIG,
        "gw_creds": REAL_CONFIG / "google_credentials.json",
        "gw_token": REAL_CONFIG / "google_token.json",
        "ap_compose": REAL_CONFIG / "docker-compose.yml",
        "ap_flujo_operador": REAL_CONFIG / "n8n_flujo_nexus.json",
        "ap_flujo_plantilla": REAL_CONFIG / "n8n_flujo_ejemplo.json",
        "ig_umbrales": REAL_CONFIG / "umbrales.json",
    }
    for clave, ruta in esperado.items():
        obtenido = rutas.get(clave)
        # Se comparan cadenas: es la ruta calculada, no se abre ningún fichero.
        check(os.path.normpath(str(obtenido)) == os.path.normpath(str(ruta)),
              f"{clave} cambió sin la variable: {obtenido} != {ruta}")
        check(str(CFG) not in str(obtenido),
              f"{clave} se contaminó con la caja aislada: {obtenido}")


def test_el_respaldo_de_instagram_honra_la_variable():
    print("== 5) instagram sin backend (respaldo): también obedece a la variable ==")
    rutas = _subproceso(GUION_SIN_BACKEND, con_config=True)
    obtenido = Path(rutas["umbrales"])
    check(obtenido == CFG / "umbrales.json",
          f"el respaldo sin backend se fue al config/ real: {obtenido}")
    check(str(REAL_CONFIG) not in str(obtenido),
          f"el respaldo sin backend nombra el config/ real: {obtenido}")


# =============================== runner =====================================
if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                          # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
