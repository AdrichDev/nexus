# -*- coding: utf-8 -*-
"""Las últimas rutas de `config/` y `data/` montadas a mano obedecen a las variables (T39c).

EL FALLO QUE ESTA SUITE CIERRA. Quedaban restos de la misma clase que T36/T39/
T39b: rutas construidas con `Path(__file__).resolve().parents[2]` o con
`ROOT / "config"`, que IGNORAN `NEXUS_CONFIG_DIR` / `NEXUS_DATA_DIR`, así que una
prueba (o un arranque aislado) seguía leyendo y ESCRIBIENDO en las carpetas
reales del operador:

  * `backend/app.py` escribía `ROOT/config/docker-compose.yml` mientras
    `skills/autoprovision/skill.py` ya lo leía de `CONFIG_DIR` (T39b): el que
    escribe y el que lee se separaban en cuanto se aislaba la config, y
    `/api/setup/docker` acababa levantando el stack con un compose que
    autoprovision no veía.
  * `backend/core/infraestructura/remote.py` buscaba y DESCARGABA el binario de
    cloudflared en `ROOT/config`.
  * seis skills (`billing`, `content_os`, `datos`, `google_workspace` —el
    `REPORTS_DIR` de la línea 2265—, `research` y `system_pc`) escribían sus
    informes, facturas, capturas y guiones en `ROOT/data` ignorando
    `NEXUS_DATA_DIR`.

QUÉ ES DEL OPERADOR Y QUÉ ES ARTEFACTO DE INSTALACIÓN (se decide fichero a
fichero, como en T39b):
  * El `docker-compose.yml` que nexus GENERA es del operador: sigue `CONFIG_DIR`,
    igual que su lector en autoprovision. Sin la variable, `ROOT/config`.
  * Un cloudflared DESCARGADO es un artefacto de instalación (se puede volver a
    bajar cuando haga falta y no es un dato del operador): vive en `DATA_DIR`,
    que es la misma carpeta donde ya se apunta la URL del túnel
    (`_TUNEL_FILE = DATA_DIR / "tunel.json"`). Así una ejecución aislada NUNCA
    deja un `.exe` dentro del repositorio.
  * La copia que un operador ya tenga en `config/cloudflared.exe` (donde nexus se
    la pedía hasta ahora) se sigue ENCONTRANDO, pero solo se lee: nadie la
    reescribe ni se fuerza una descarga de 60 MB a quien ya la tenía. Esa ruta
    sale de `CONFIG_DIR`, no de un `ROOT / "config"` a mano.
  * Informes, facturas, capturas y guiones son datos del operador: `DATA_DIR`.

CÓMO SE PRUEBA (sin red, sin docker, sin bajar ni ejecutar cloudflared):
  1. En ESTE proceso las variables apuntan a una carpeta temporal puesta ANTES
     del import (las rutas se resuelven al importar), y se comprueban las
     constantes de módulo y el destino REAL de cada escritura: el compose de la
     BD se escribe llamando al endpoint con docker y `subprocess.run` DOBLADOS
     (se mira el `-f` del argv y el archivo que aparece en la carpeta temporal),
     y la descarga de cloudflared, con el cliente HTTP doblado (lo que se
     escribe es un `bytes` de mentira: no se ejecuta nada).
  2. El comportamiento de SIEMPRE (sin las variables) se mide en un SUBPROCESO
     que solo IMPRIME las rutas calculadas: se comparan con `ROOT/config` y
     `ROOT/data` carácter a carácter. En el subproceso no se abre ni se escribe
     ningún fichero del operador: importar los módulos solo calcula `Path`.

Ejecutar: .venv\\Scripts\\python.exe tests\\unit\\core\\runtime\\test_rutas_aisladas.py
"""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass

REAL_CONFIG = ROOT / "config"
REAL_DATA = ROOT / "data"

# La caja aislada se crea y se declara ANTES de importar nada: `comun/config.py`
# resuelve DATA_DIR/CONFIG_DIR al importar y un import perezoso llegaría tarde.
_TMP = tempfile.TemporaryDirectory(prefix="nexus_rutas_aisladas_")
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
    arrastraría las 32 skills solo para leer seis constantes)."""
    ruta = ROOT / "skills" / carpeta / fichero
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BI = _carga("billing", nombre="bi_rutas")
CO = _carga("content_os", nombre="co_rutas")
DA = _carga("datos", nombre="da_rutas")
RE = _carga("research", nombre="re_rutas")
SP = _carga("system_pc", nombre="sp_rutas")
GW = _carga("google_workspace", nombre="gw_rutas")

from backend.core.infraestructura import remote as REMOTE          # noqa: E402
import backend.app as APP                                          # noqa: E402

# El binario se llama distinto según la plataforma en TODAS las rutas: una sola
# definición aquí y las comprobaciones dicen lo mismo en Windows y en Linux.
_EXE = "cloudflared.exe" if sys.platform == "win32" else "cloudflared"


# ═══════════ 1) las seis skills escriben en DATA_DIR, no en ROOT/data ═══════
def test_las_skills_escriben_en_data_dir():
    print("== 1) las seis skills: sus carpetas de datos salen de DATA_DIR ==")
    esperado = [
        ("billing.INVOICE_DIR", BI.INVOICE_DIR, DATA / "invoices"),
        ("content_os.DATA", CO.DATA, DATA),
        ("content_os.INSP_DIR", CO.INSP_DIR, DATA / "inspiration"),
        ("content_os.SCRIPTS_DIR", CO.SCRIPTS_DIR, DATA / "scripts"),
        ("datos.REPORTS_DIR", DA.REPORTS_DIR, DATA / "reports"),
        ("research.REPORTS_DIR", RE.REPORTS_DIR, DATA / "reports"),
        ("system_pc.SHOTS_DIR", SP.SHOTS_DIR, DATA / "captures"),
        ("google_workspace.REPORTS_DIR", GW.REPORTS_DIR, DATA / "reports"),
    ]
    for nombre, obtenido, ruta in esperado:
        check(Path(obtenido) == ruta,
              f"{nombre} no sale de NEXUS_DATA_DIR: {obtenido} != {ruta}")
        # El fallo de verdad: nombre la carpeta REAL del operador.
        check(str(REAL_DATA) not in str(obtenido),
              f"{nombre} nombra el data/ real del operador: {obtenido}")
    # Las tres carpetas de informes son el MISMO sitio: si una se aislara sola,
    # los informes de una skill serían invisibles para las otras dos.
    check(Path(DA.REPORTS_DIR) == Path(RE.REPORTS_DIR) == Path(GW.REPORTS_DIR),
          "las tres REPORTS_DIR ya no son la misma carpeta")


# ═══════ 2) app.py: el compose de la BD se escribe en CONFIG_DIR ════════════
def test_app_escribe_el_compose_de_la_bd_en_config_dir():
    print("== 2) app.py: el docker-compose.yml de la BD va a CONFIG_DIR ==")
    destino = CFG / "docker-compose.yml"
    check(Path(getattr(APP, "_COMPOSE_BD", REAL_CONFIG / "docker-compose.yml")) == destino,
          f"el compose de la BD no sale de CONFIG_DIR: {getattr(APP, '_COMPOSE_BD', None)}")
    ya_estaba = (REAL_CONFIG / "docker-compose.yml").exists()

    # Docker DOBLADO: `docker compose -f … up -d` no se ejecuta y devuelve un
    # fallo, así que el endpoint no llega a escribir `db_url` en settings.
    capturado = {}

    def _run_falso(argv, **kw):
        capturado["argv"] = list(argv)
        return SimpleNamespace(returncode=1, stdout="", stderr="docker de mentira")

    which_orig, run_orig = shutil.which, subprocess.run
    shutil.which = lambda *a, **k: "docker"
    subprocess.run = _run_falso
    try:
        res = asyncio.run(APP.api_setup_docker())
    finally:
        shutil.which, subprocess.run = which_orig, run_orig

    argv = capturado.get("argv", [])
    check(argv[:2] == ["docker", "compose"],
          f"el endpoint ya no llama a docker compose: {argv[:2]}")
    check(str(destino) in argv,
          f"docker compose no usa el compose de la config aislada: {argv}")
    check(destino.is_file(), f"el compose no se ha escrito en la config aislada: {destino}")
    texto = destino.read_text(encoding="utf-8") if destino.is_file() else ""
    check("POSTGRES_PASSWORD" in texto and "pgvector" in texto,
          "el compose escrito no es el stack de la memoria (pgvector)")
    # Y el `config/` del operador no se ha tocado ni de refilón.
    check((REAL_CONFIG / "docker-compose.yml").exists() == ya_estaba,
          "el endpoint ha escrito o borrado el config/docker-compose.yml real")
    check(res.get("ok") is False, f"el fallo de docker no se cuenta como fallo: {res}")


# ═══════ 3) cloudflared: qué es artefacto y qué es del operador ═════════════
def test_el_binario_de_cloudflared_vive_en_data_dir():
    print("== 3) remote: el binario descargado va a DATA_DIR; config/ solo se lee ==")
    local = Path(getattr(REMOTE, "_CLOUDFLARED_LOCAL", REAL_CONFIG / _EXE))
    heredado = Path(getattr(REMOTE, "_CLOUDFLARED_HEREDADO", REAL_CONFIG / _EXE))
    check(local == DATA / _EXE,
          f"el cloudflared descargado no vive en NEXUS_DATA_DIR: {local}")
    check(heredado == CFG / _EXE,
          f"la copia heredada no se busca en CONFIG_DIR: {heredado}")
    for nombre, ruta in (("_CLOUDFLARED_LOCAL", local), ("_CLOUDFLARED_HEREDADO", heredado)):
        check(str(REAL_CONFIG) not in str(ruta) and str(REAL_DATA) not in str(ruta),
              f"{nombre} nombra una carpeta real del operador: {ruta}")
    # La carpeta de datos ya es la del estado del túnel: una sola fuente.
    check(Path(REMOTE._TUNEL_FILE).parent == DATA,
          f"la URL del túnel no se apunta en DATA_DIR: {REMOTE._TUNEL_FILE}")


def test_cloudflared_se_encuentra_sin_bajar_ni_ejecutar_nada():
    print("== 4) remote: se encuentra en data/ y también la copia heredada de config/ ==")
    local = DATA / _EXE
    heredado = CFG / _EXE
    for ruta in (local, heredado):
        if ruta.exists():
            ruta.unlink()
    which_orig = shutil.which
    shutil.which = lambda *a, **k: None           # sin cloudflared en el PATH
    try:
        check(REMOTE._cloudflared_path() is None,
              "sin binario en ningún sitio no debería encontrar nada")
        # Un `bytes` cualquiera hace de binario: NUNCA se ejecuta.
        local.write_bytes(b"MZ-binario-de-prueba")
        try:
            check(Path(REMOTE._cloudflared_path()) == local,
                  f"no encuentra el binario de data/: {REMOTE._cloudflared_path()}")
        finally:
            local.unlink()
        # Lo de SIEMPRE no se rompe: quien ya lo tenía en config/ sigue servido
        # sin que nexus le obligue a bajarlo otra vez.
        heredado.write_bytes(b"MZ-binario-de-prueba")
        try:
            check(Path(REMOTE._cloudflared_path()) == heredado,
                  f"el binario que ya estaba en config/ deja de verse: "
                  f"{REMOTE._cloudflared_path()}")
        finally:
            heredado.unlink()
    finally:
        shutil.which = which_orig


def test_la_descarga_de_cloudflared_escribe_en_data_dir():
    print("== 5) remote: la descarga escribe en DATA_DIR (y no se baja nada de verdad) ==")
    local = DATA / _EXE
    if local.exists():
        local.unlink()
    pedidas = []

    class _Respuesta:
        content = b"MZ-binario-de-prueba"

        def raise_for_status(self):
            return None

    class _Cliente:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **k):
            pedidas.append(url)
            return _Respuesta()

    class _HttpxFalso:
        AsyncClient = _Cliente

    modulos_orig = sys.modules.get("httpx")
    sys.modules["httpx"] = _HttpxFalso             # nada sale a la red
    try:
        res = asyncio.run(REMOTE._download_cloudflared())
    finally:
        if modulos_orig is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = modulos_orig
    try:
        if sys.platform != "win32":
            # Como siempre: fuera de Windows no se descarga nada.
            check(res is None, f"fuera de Windows la descarga debería rechazarse: {res}")
            check(not local.exists(), "fuera de Windows se ha escrito un binario")
            return
        check(Path(res) == local, f"la descarga no escribe en data/: {res}")
        check(local.is_file() and local.read_bytes() == b"MZ-binario-de-prueba",
              "el binario descargado no ha quedado en data/")
        check(pedidas == [REMOTE.CLOUDFLARED_URL_WIN],
              f"la descarga no ha pedido el binario oficial una sola vez: {pedidas}")
        check(str(REAL_CONFIG) not in str(res),
              f"la descarga apunta al config/ real del operador: {res}")
    finally:
        if local.exists():
            local.unlink()


# ═══ 6) LO DE SIEMPRE: sin las variables, ROOT/config y ROOT/data exactas ══
GUION_SIN_VARIABLES = r'''
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


bi = carga("billing", nombre="bi_sin_variables")
co = carga("content_os", nombre="co_sin_variables")
da = carga("datos", nombre="da_sin_variables")
re_ = carga("research", nombre="re_sin_variables")
sp = carga("system_pc", nombre="sp_sin_variables")
gw = carga("google_workspace", nombre="gw_sin_variables")
from backend.core.infraestructura import remote
import backend.app as app
print(json.dumps({
    "billing_invoices": str(bi.INVOICE_DIR),
    "contentos_data": str(co.DATA),
    "contentos_inspiracion": str(co.INSP_DIR),
    "contentos_guiones": str(co.SCRIPTS_DIR),
    "datos_informes": str(da.REPORTS_DIR),
    "research_informes": str(re_.REPORTS_DIR),
    "system_pc_capturas": str(sp.SHOTS_DIR),
    "google_informes": str(gw.REPORTS_DIR),
    "cloudflared_local": str(remote._CLOUDFLARED_LOCAL),
    "cloudflared_heredado": str(remote._CLOUDFLARED_HEREDADO),
    "app_compose": str(app._COMPOSE_BD),
}))
'''


def _subproceso(guion: str, data_dir: Path | None = None) -> dict:
    """Lanza `guion` SIN las variables: se mide el camino de siempre.

    El `.env` del operador tampoco entra (NEXUS_DOTENV=0) y el subproceso solo
    imprime rutas calculadas: no abre ni escribe ningún fichero del operador.
    Con `data_dir` se mide el camino CON `NEXUS_DATA_DIR` (y sin
    `NEXUS_CONFIG_DIR`), que es lo que necesita el respaldo del apartado 7.
    """
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("NEXUS_CONFIG_DIR", "NEXUS_DATA_DIR", "NEXUS_DOTENV")}
    entorno.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "NEXUS_DOTENV": "0"})
    if data_dir is not None:
        entorno["NEXUS_DATA_DIR"] = str(data_dir)
    r = subprocess.run([sys.executable, "-c", guion, str(ROOT)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=entorno, timeout=150)
    if r.returncode != 0:
        raise RuntimeError(f"subproceso falló ({r.returncode}): "
                           f"{r.stdout[-500:]}{r.stderr[-1500:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_sin_las_variables_las_rutas_son_las_de_siempre():
    print("== 6) sin NEXUS_CONFIG_DIR/NEXUS_DATA_DIR: ROOT/config y ROOT/data exactas ==")
    rutas = _subproceso(GUION_SIN_VARIABLES)
    esperado = {
        "billing_invoices": REAL_DATA / "invoices",
        "contentos_data": REAL_DATA,
        "contentos_inspiracion": REAL_DATA / "inspiration",
        "contentos_guiones": REAL_DATA / "scripts",
        "datos_informes": REAL_DATA / "reports",
        "research_informes": REAL_DATA / "reports",
        "system_pc_capturas": REAL_DATA / "captures",
        "google_informes": REAL_DATA / "reports",
        "cloudflared_local": REAL_DATA / _EXE,
        "cloudflared_heredado": REAL_CONFIG / _EXE,
        "app_compose": REAL_CONFIG / "docker-compose.yml",
    }
    for clave, ruta in esperado.items():
        obtenido = rutas.get(clave)
        # Se comparan cadenas: es la ruta calculada, no se abre ningún fichero.
        check(os.path.normpath(str(obtenido)) == os.path.normpath(str(ruta)),
              f"{clave} cambió sin las variables: {obtenido} != {ruta}")
        check(str(CFG) not in str(obtenido) and str(DATA) not in str(obtenido),
              f"{clave} se contaminó con la caja aislada: {obtenido}")


# ═══ 7) el respaldo que existe para no romper una suite no es MUDO ═════════
GUION_RESEARCH_SIN_BACKEND = r'''
import importlib.util, json, sys
from pathlib import Path
RAIZ = Path(sys.argv[1])
sys.path.insert(0, str(RAIZ))

# Los paquetes `backend.*` doblados, como hace test_source_evidence.py: el
# import directo de `comun.config` falla y entra el respaldo.
sys.modules["backend"] = None
spec = importlib.util.spec_from_file_location(
    "re_sin_backend", RAIZ / "skills" / "research" / "skill.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps({"informes": str(mod.REPORTS_DIR)}))
'''


def test_el_respaldo_de_research_tambien_mira_la_variable():
    print("== 7) research con backend doblado (respaldo): también obedece a la variable ==")
    aparte = Path(tempfile.mkdtemp(prefix="nexus_rutas_respaldo_"))
    try:
        rutas = _subproceso(GUION_RESEARCH_SIN_BACKEND, data_dir=aparte)
        obtenido = Path(rutas["informes"])
        check(obtenido == aparte / "reports",
              f"el respaldo sin backend se fue al data/ real: {obtenido}")
        check(str(REAL_DATA) not in str(obtenido),
              f"el respaldo sin backend nombra el data/ real: {obtenido}")
    finally:
        shutil.rmtree(aparte, ignore_errors=True)


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
