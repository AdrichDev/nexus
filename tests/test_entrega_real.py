# -*- coding: utf-8 -*-
"""PRUEBA DE ENTREGA REAL — lo que el HUD RECIBE, no lo que hay en el disco.

Por qué existe: el 25/07/2026 los iconos del sidebar salían grises en el PC de
Adri mientras TODAS las pruebas daban verde. ¿Motivo? Comprobaban el contenido
del archivo `command.css`, que era correcto — pero el navegador seguía sirviendo
la versión antigua de su caché. Un test que valida el archivo y no la entrega no
prueba nada de lo que le importa al usuario.

Aquí se arranca nexus DE VERDAD y se pide por HTTP exactamente lo que pide el
HUD, comprobando que lo que llega:
  * es el archivo actual (no una copia vieja ni la empaquetada en el .exe),
  * trae lo que se supone que trae (la paleta, los iconos, el chip del tiempo),
  * y no se puede quedar cacheado.

No necesita navegador: son peticiones HTTP. Se ejecuta en la suite normal, así
que corre en el equipo de Adri sin instalar nada.

Ejecutar:  python tests/test_entrega_real.py    (desde la carpeta nexus)
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Cabeceras(dict):
    """Las cabeceras HTTP NO distinguen mayúsculas; un dict normal sí.
    (Este mismo despiste hizo que la prueba diera un falso fallo.)"""

    def get(self, k, default=""):
        for kk, vv in self.items():
            if kk.lower() == str(k).lower():
                return vv
        return default


def _get(url: str):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace"), _Cabeceras(r.headers)


def _post(url: str, obj: dict, timeout: int = 60):
    datos = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=datos, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="nexus_entrega_"))
    (sandbox / "data").mkdir()
    (sandbox / "config").mkdir()
    (sandbox / "config" / "settings.json").write_text(json.dumps({
        "setup_done": True, "llm_provider": "mock", "hermes_auto": False,
        "hermes_autostart": False, "smart_router": False, "tts_enabled": False,
        "open_mic": False, "wake_enabled": False, "engram_enabled": False,
    }), encoding="utf-8")
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, NEXUS_DATA_DIR=str(sandbox / "data"),
               NEXUS_CONFIG_DIR=str(sandbox / "config"), PYTHONUTF8="1")
    log = open(sandbox / "servidor.log", "w", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app",
                            "--host", "127.0.0.1", "--port", str(port),
                            "--log-level", "warning"],
                           cwd=str(ROOT), env=env, stdout=log, stderr=log)
    try:
        # 60 s de margen: con la suite entera corriendo, arrancar el
        # servidor se va más allá de los 32 s de antes y la prueba
        # fallaba por impaciencia, no por un fallo real.
        for _ in range(150):
            time.sleep(0.4)
            try:
                urllib.request.urlopen(base + "/api/jobs", timeout=2).read()
                break
            except (urllib.error.URLError, OSError):
                continue
        else:
            print("  FALLO: nexus no arrancó;", (sandbox / "servidor.log").read_text()[-400:])
            return 1

        # ── 1. EL HTML QUE RECIBE EL NAVEGADOR ────────────────────────────────
        html, _h = _get(base + "/")
        check("<nav id=\"nav\"" in html, "el servidor entrega el HUD (no el asistente de instalación)")
        check(html.count("nav-ic") >= 12, f"llegan los 12 iconos SVG (llegan {html.count('nav-ic')})")
        check('data-view="today"' not in html, "y sin la sección «Hoy», ya retirada")
        check('id="wx"' in html, "llega el chip del tiempo del header")
        check("?v=" in html, "el CSS y el JS piden versión (para que no se cacheen)")

        # ── 2. EL CSS QUE RECIBE EL NAVEGADOR ─────────────────────────────────
        m = re.search(r'href="(/static/css/command\.css[^"]*)"', html)
        check(bool(m), "el HTML enlaza la hoja de estilos")
        css, hdr = _get(base + m.group(1))
        paleta = dict(re.findall(r'#nav a\[data-view="(\w+)"\]\s*\{--ic:(#[0-9a-fA-F]{6})', css))
        check(len(paleta) >= 12,
              f"EL CSS QUE LLEGA trae la paleta de los iconos ({len(paleta)} colores)")
        check(len(set(paleta.values())) == len(paleta), "y cada sección con un color distinto")
        check("drop-shadow" in css, "con su halo de color")
        check("#nav a .nav-ic" in css, "y el estilo base de los iconos")
        cc = hdr.get("Cache-Control").lower()
        check("no-store" in cc or "no-cache" in cc,
              f"el CSS se sirve SIN CACHÉ, para que un cambio se vea al reiniciar (recibí «{cc}»)")

        # ── 3. ¿ES EL ARCHIVO DE VERDAD O UNA COPIA VIEJA? ────────────────────
        # Se comparan los finales de línea NORMALIZADOS. Comparar longitudes a
        # pelo daba un falso rojo: por el cable llegan los CRLF tal cual y
        # `read_text()` los convierte a LF, así que el disco salía siempre más
        # corto — exactamente en el número de líneas del fichero. Lo que se
        # quiere comprobar es que es EL MISMO CONTENIDO, no el mismo recuento de
        # bytes bajo dos decodificadores distintos.
        _n = lambda s: s.replace("\r\n", "\n")             # noqa: E731
        disco = _n((ROOT / "frontend" / "css" / "command.css").read_text(encoding="utf-8"))
        servido = _n(css)
        check(servido == disco,
              f"lo servido ES el archivo del disco, no otra copia "
              f"(servido {len(servido)} · disco {len(disco)})")

        # ── 4. EL JS QUE RECIBE EL NAVEGADOR ──────────────────────────────────
        mj = re.search(r'src="(/static/js/command\.js[^"]*)"', html)
        check(bool(mj), "el HTML enlaza el script del HUD")
        js, hdrj = _get(base + mj.group(1))
        check("paintJobsNav" in js and "job_done" in js,
              "EL JS QUE LLEGA trae el indicador de Multitarea y el aviso de fin")
        check("loadWeather" in js, "y el componente del tiempo")
        ccj = hdrj.get("Cache-Control").lower()
        check("no-store" in ccj or "no-cache" in ccj, "el JS tampoco se cachea")

        # ── 5. LA API QUE USA EL HUD ──────────────────────────────────────────
        for ruta, clave in (("/api/jobs", "badge"), ("/api/board", "pendiente"),
                            ("/api/board/trash", "items")):
            txt, _ = _get(base + ruta)
            check(clave in txt, f"{ruta} responde con lo que el HUD espera ({clave})")

        # ── 6. EL RUNTIME DE MODELOS, POR HTTP ────────────────────────────────
        # Aquí es donde se rompía la coherencia: ⚙ decía «cerebro activo» y el
        # chat decía «ese modelo no existe». Ahora hay UNA fuente y se prueba.
        txt, _ = _get(base + "/api/llm/status")
        est = json.loads(txt)
        for clave in ("active", "provider", "verified", "error"):
            check(clave in est, f"/api/llm/status trae «{clave}»")

        txt, _ = _get(base + "/api/llm/models")
        cat = json.loads(txt)
        check(isinstance(cat.get("items"), list), "/api/llm/models devuelve el catálogo")
        check("ollama_up" in cat, "y dice si Ollama está en marcha")
        check(all(("usable" in i and "kind" in i) for i in cat["items"]),
              "con cada modelo YA clasificado por el servidor")

        antes = json.loads(_get(base + "/api/config")[0]).get("llm_provider")
        r = _post(base + "/api/llm/activate",
                  {"provider": "ollama", "model": "modelo-que-no-existe-jamas"})
        check(r.get("active") is False,
              "activar un modelo inexistente NO se da por bueno")
        check(bool(r.get("error")), f"y se explica por qué ({r.get('error')!r})")
        prohibidos = ("hermes", "gateway", "endpoint", "localhost", "traceback",
                      "http 4", "http 5", "11434")
        fugas = [x for x in prohibidos if x in (r.get("error") or "").lower()]
        check(not fugas, f"sin jerga interna en el aviso ({fugas})")
        despues = json.loads(_get(base + "/api/config")[0]).get("llm_provider")
        check(antes == despues,
              f"y la configuración NO se cambia por un intento fallido "
              f"({antes} → {despues})")
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
        log.close()
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    print("· entrega real (lo que el HUD recibe por HTTP)")
    try:
        main()
    except Exception as e:
        _fail.append(f"EXCEPCIÓN: {type(e).__name__}: {e}")
        print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
