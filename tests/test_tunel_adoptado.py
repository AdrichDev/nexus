# -*- coding: utf-8 -*-
"""EL TÚNEL QUE SOBREVIVE Y EL BUCLE QUE NO SE PUEDE BLOQUEAR.

Dos incidentes del 01/08/2026, los dos en `backend/core/remote.py`:

1. NEXUS SE CONGELABA 4,3 s CADA 45 s. `/api/link/status` llamaba a
   `remote.status()` —que es SÍNCRONA— directamente sobre el bucle de asyncio.
   Por dentro sondea «TUPC.local:8177», y resolver ese nombre por mDNS tarda
   4,25 s medidos en este equipo (3 de 3 intentos). El `timeout=0.6` del socket
   NO cubre la resolución del nombre. Con el bucle parado NINGUNA petición
   respondía: /api/jobs, /api/hardware, todas se soltaban de golpe al terminar.
   Aquí se comprueba que el endpoint NO para el bucle, con un latido que tiene
   que seguir latiendo mientras la llamada bloquea.

2. HABÍA QUE RE-ESCANEAR EL QR EN CADA REINICIO. `start_tunnel()` mataba el
   cloudflared anterior y abría uno nuevo; el «quick tunnel» da un subdominio
   ALEATORIO distinto cada vez, así que el móvil se quedaba apuntando a una
   dirección muerta. Ahora, si el túnel del arranque anterior sigue vivo Y sigue
   sirviendo NUESTRA página, se adopta y la dirección no cambia.

   Lo que hay que cazar aquí es la adopción ALEGRE: NO vale adoptar porque
   `cloudflared.exe` esté en la lista de procesos. Un cloudflared vivo puede
   estar sirviendo un túnel viejo que ya no apunta aquí, o apuntar a otra cosa.
   La única prueba válida es que la URL guardada conteste nuestra página.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_tunel_adoptado.py
"""
import asyncio
import http.server
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from _frontend_js import js_hud  # el HUD entero, no solo command.js

ROOT = Path(__file__).resolve().parents[1]
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


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Servidorcillo(threading.Thread):
    """Un servidor de mentira para hacer de «la otra punta del túnel».

    Sirve en /m lo que se le diga. Así se puede probar la adopción contra algo
    REAL sin depender de que haya un túnel de Cloudflare levantado."""

    daemon = True

    def __init__(self, cuerpo: str, codigo: int = 200):
        super().__init__()
        self.port = _free_port()
        cuerpo_b = cuerpo.encode("utf-8")

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                                    # noqa: N802
                self.send_response(codigo)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo_b)))
                self.end_headers()
                self.wfile.write(cuerpo_b)

            def log_message(self, *a):                           # silencio
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", self.port), H)

    def run(self):
        self.httpd.serve_forever()

    def para(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


PAGINA_NUESTRA = ("<!doctype html><html><head><meta charset='utf-8'>"
                  "<title>nexus</title></head><body>nexus móvil</body></html>")
PAGINA_DE_OTRO = ("<!doctype html><html><head><title>Cloudflare Tunnel error</title>"
                  "</head><body>Error 1033</body></html>")


# ══════════════════════════════════════════════════════════════════════════════
# 1) EL BUCLE DE ASYNCIO NO SE PUEDE QUEDAR PARADO
# ══════════════════════════════════════════════════════════════════════════════
async def _prueba_no_bloquea():
    from backend import app as appmod
    from backend.core.infraestructura import remote

    BLOQUEO = 1.2                       # lo que «tarda el mDNS» en esta prueba
    original = remote.status
    hilos = []

    def status_lento():
        hilos.append(threading.current_thread().name)
        time.sleep(BLOQUEO)             # exactamente lo que hace getaddrinfo
        return {"tunnel": False, "link": "http://x/m", "hosts": []}

    remote.status = status_lento
    try:
        # Un latido cada 20 ms: si el bucle se para, se nota en el hueco entre
        # dos latidos. Es la medida honesta de «el bucle sigue atendiendo».
        tics = []
        parar = False

        async def latido():
            while not parar:
                tics.append(time.perf_counter())
                await asyncio.sleep(0.02)

        t = asyncio.create_task(latido())
        await asyncio.sleep(0.1)
        t0 = time.perf_counter()
        await appmod.api_link_status()
        tardado = time.perf_counter() - t0
        # OJO: hay que dejar latir DESPUÉS de la llamada. Cancelando aquí mismo,
        # el último tic era el de justo antes del bloqueo y el hueco no se veía
        # NUNCA: la prueba pasaba con el bug puesto. El parón solo se mide con un
        # tic a cada lado.
        await asyncio.sleep(0.1)
        parar = True
        t.cancel()

        hueco = max((b - a for a, b in zip(tics, tics[1:])), default=99.0)
        check(tardado >= BLOQUEO * 0.8,
              f"la llamada de verdad hace el trabajo lento ({tardado:.2f} s)")
        check(hueco < 0.5,
              f"/api/link/status NO para el bucle: el mayor parón del latido fue "
              f"{hueco * 1000:.0f} ms mientras status() bloqueaba {BLOQUEO} s")
        check(hilos and not hilos[0].startswith("MainThread"),
              f"y status() corre en un hilo aparte, no en el del bucle (fue «{hilos[0] if hilos else '?'}»)")
    finally:
        remote.status = original


# ══════════════════════════════════════════════════════════════════════════════
# 2) LA ADOPCIÓN DEL TÚNEL
# ══════════════════════════════════════════════════════════════════════════════
async def _prueba_adopcion():
    from backend.core.infraestructura import remote

    # ── la comprobación de «¿sigue siendo nuestro?», contra servidores REALES ──
    nuestro = _Servidorcillo(PAGINA_NUESTRA)
    nuestro.start()
    ajeno = _Servidorcillo(PAGINA_DE_OTRO)
    ajeno.start()
    muerto = f"http://127.0.0.1:{_free_port()}"      # nadie escuchando ahí
    time.sleep(0.2)
    try:
        check(await remote._sigue_siendo_nuestro(nuestro.url),
              "una URL que contesta NUESTRA página del móvil se reconoce como nuestra")
        check(not await remote._sigue_siendo_nuestro(ajeno.url),
              "una que contesta 200 pero con OTRA página (p.ej. el error 1033 de "
              "Cloudflare) NO se adopta")
        check(not await remote._sigue_siendo_nuestro(muerto),
              "y una dirección donde no escucha nadie tampoco")
    finally:
        ajeno.para()

    tmp = Path(tempfile.mkdtemp(prefix="nexus_tunel_"))
    fichero = tmp / "tunel.json"
    orig_file = remote._TUNEL_FILE
    orig_run = remote.subprocess.run
    orig_path = remote._cloudflared_path
    orig_dl = remote._download_cloudflared
    orig_estado = dict(remote._state)
    llamadas = []

    def run_falso(cmd, *a, **k):
        """Nada de matar cloudflared de verdad durante una prueba."""
        llamadas.append(list(cmd))

        class R:
            returncode = 0
            stdout = ""
        return R()

    async def sin_descarga():
        return None

    orig_popen = remote.subprocess.Popen

    def popen_prohibido(cmd, *a, **k):
        raise RuntimeError(f"la prueba ha intentado abrir un proceso de verdad: {cmd}")

    remote._TUNEL_FILE = fichero
    remote.subprocess.run = run_falso
    # Se corta ANTES de abrir nada de verdad. La primera versión de esta prueba
    # solo tapaba `_cloudflared_path`: el código siguió por su camino, se bajó
    # los 54 MB de cloudflared de GitHub y dejó DOS túneles públicos abiertos en
    # el equipo. Una prueba no publica el PC en internet.
    remote._cloudflared_path = lambda: None
    remote._download_cloudflared = sin_descarga
    remote.subprocess.Popen = popen_prohibido        # red de seguridad
    try:
        # ── CASO A: la URL guardada SÍ contesta nuestra página → se adopta ────
        fichero.write_text(json.dumps({"url": nuestro.url, "ts": time.time()}),
                           encoding="utf-8")
        remote._state.update(proc=None, url="", url_pending="", starting=False,
                             adoptado=False, error="")
        # `_tunel_guardado` exige https:// (el túnel real siempre lo es); en la
        # prueba el servidor de mentira es http, así que se salta ESA validación
        # y no la que importa, que es la de la página.
        orig_guardado = remote._tunel_guardado
        remote._tunel_guardado = lambda: nuestro.url
        try:
            await remote.start_tunnel()
        finally:
            remote._tunel_guardado = orig_guardado

        check(remote._state["adoptado"] is True,
              "con la URL viva y sirviendo nuestra página, el túnel se ADOPTA")
        check(remote._state["url"] == nuestro.url,
              f"y la dirección NO cambia ({remote._state['url']})")
        check(not llamadas,
              f"no se mata a nadie ni se abre un túnel nuevo (mandé {llamadas})")
        check(remote._state["proc"] is None,
              "sin proceso propio: el cloudflared es hijo del nexus anterior")

        est = remote.status()
        check(est["tunnel"] is True,
              "el HUD ve el túnel VIVO aunque no tengamos su proceso "
              "(sin la marca «adoptado» decía que no había túnel)")
        check(est.get("adoptado") is True, "y el estado dice que es adoptado")
        check("re-escanear" in (est.get("tunel_nota") or "").lower(),
              f"con su explicación: «{(est.get('tunel_nota') or '')[:70]}»")

        # ── parar un túnel adoptado tiene que pararlo DE VERDAD ───────────────
        llamadas.clear()
        remote.stop_tunnel()
        check(any("cloudflared" in " ".join(c).lower() for c in llamadas),
              f"parar un túnel adoptado lo mata por nombre, que no hay proc "
              f"que terminar (mandé {llamadas})")
        check(remote._state["adoptado"] is False and remote._state["url"] == "",
              "y el estado queda limpio")
        check(not fichero.exists(),
              "y se olvida la URL: si lo paras a propósito, no se readopta al reiniciar")

        # ── CASO B: la URL guardada NO contesta lo nuestro → NADA de adoptar ──
        llamadas.clear()
        fichero.write_text(json.dumps({"url": ajeno.url, "ts": time.time()}),
                           encoding="utf-8")
        remote._state.update(proc=None, url="", url_pending="", starting=False,
                             adoptado=False, error="")
        orig_guardado = remote._tunel_guardado
        remote._tunel_guardado = lambda: ajeno.url   # servidor ya parado: no contesta
        try:
            await remote.start_tunnel()
        finally:
            remote._tunel_guardado = orig_guardado

        check(remote._state["adoptado"] is False,
              "si la URL guardada no contesta NUESTRA página, NO se adopta")
        check(remote._state["url"] == "", "y no se da por bueno ese túnel")
        check(any("taskkill" in " ".join(c).lower() for c in llamadas)
              or sys.platform != "win32",
              f"se sigue el camino normal: matar lo anterior y abrir uno nuevo "
              f"(mandé {llamadas})")
        check(not fichero.exists(),
              "y se tira la URL guardada, que ya no vale para nada")

        # ── una URL guardada rancia ni se prueba ──────────────────────────────
        remote._TUNEL_FILE = fichero
        fichero.write_text(json.dumps(
            {"url": "https://viejo.trycloudflare.com",
             "ts": time.time() - (remote._ADOPCION_MAX_HORAS + 1) * 3600}),
            encoding="utf-8")
        check(remote._tunel_guardado() == "",
              "una URL guardada hace días se descarta sin gastar una petición")
        fichero.write_text(json.dumps({"url": "no-es-una-url", "ts": time.time()}),
                           encoding="utf-8")
        check(remote._tunel_guardado() == "", "y una URL con mala pinta también")
        fichero.write_text("{esto no es json", encoding="utf-8")
        check(remote._tunel_guardado() == "",
              "un fichero roto no puede tumbar el arranque del túnel")
    finally:
        nuestro.para()
        remote._TUNEL_FILE = orig_file
        remote.subprocess.run = orig_run
        remote._cloudflared_path = orig_path
        remote._download_cloudflared = orig_dl
        remote.subprocess.Popen = orig_popen
        remote._state.clear()
        remote._state.update(orig_estado)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# 2 bis) LA ADOPCIÓN **AL ARRANCAR**, QUE ES LA MITAD QUE FALTABA
# ══════════════════════════════════════════════════════════════════════════════
#   La adopción de `start_tunnel()` solo salta cuando el usuario abre el panel
#   del QR. Hasta ese momento nexus creía no tener túnel —y el HUD lo decía—
#   aunque el cloudflared del arranque anterior siguiera sirviendo. Por eso el
#   arranque lo comprueba ahora por su cuenta.
#
#   LO QUE HAY QUE VIGILAR AQUÍ: que esto NO ABRA NADA. Abrir un túnel publica
#   este PC en internet, y eso lo decide el usuario, no el arranque. Adoptar es
#   re-engancharse a algo que YA estaba abierto y YA era público; crear es otra
#   cosa muy distinta. Si alguien «mejora» esto haciendo que levante un túnel
#   cuando no encuentra ninguno, el check del Popen prohibido tiene que saltar.
async def _prueba_adopcion_al_arrancar():
    from backend.core.infraestructura import remote

    print("· al arrancar: se recupera el túnel superviviente, sin abrir nada")

    nuestro = _Servidorcillo(PAGINA_NUESTRA)
    nuestro.start()          # start(), NO run(): run() es serve_forever() y bloquea aquí
    tmp = Path(tempfile.mkdtemp(prefix="nexus-arranque-"))
    fichero = tmp / "tunel.json"
    orig_file, orig_estado = remote._TUNEL_FILE, dict(remote._state)
    orig_popen, orig_run = remote.subprocess.Popen, remote.subprocess.run
    remote._TUNEL_FILE = fichero

    abiertos = []

    def _es_del_tunel(cmd) -> bool:
        """¿Este comando abre o mata el túnel? Consultar Tailscale (lo hace
        `status()`) es lectura inocua y tiene que seguir permitida; lo que no
        puede pasar es que el ARRANQUE levante o mate un cloudflared."""
        txt = " ".join(cmd).lower() if isinstance(cmd, (list, tuple)) else str(cmd).lower()
        return "cloudflared" in txt or "taskkill" in txt or "pkill" in txt

    def popen_prohibido(cmd, *a, **k):      # red de seguridad: NADA de túneles
        abiertos.append(cmd)
        raise AssertionError(f"el arranque ha intentado ABRIR un proceso: {cmd}")

    def run_vigilado(cmd, *a, **k):
        if _es_del_tunel(cmd):
            abiertos.append(cmd)
            raise AssertionError(f"el arranque ha intentado abrir/matar el túnel: {cmd}")
        return orig_run(cmd, *a, **k)       # lo demás (Tailscale) sigue funcionando

    remote.subprocess.Popen = popen_prohibido
    remote.subprocess.run = run_vigilado
    try:
        # ── CASO A: el túnel de antes sigue vivo y sigue siendo nuestro ────────
        fichero.write_text(json.dumps({"url": nuestro.url, "ts": time.time()}),
                           encoding="utf-8")
        remote._state.update(proc=None, url="", url_pending="", starting=False,
                             adoptado=False, error="")
        # el servidor de mentira es http, no https: se salta esa validación
        orig_guardado = remote._tunel_guardado
        remote._tunel_guardado = lambda: nuestro.url
        try:
            adoptado = await remote.adopta_tunel_al_arrancar()
        finally:
            remote._tunel_guardado = orig_guardado

        check(adoptado is True, "el túnel que sigue vivo se adopta al arrancar")
        check(remote._state["url"] == nuestro.url,
              "y se conserva LA MISMA dirección: eso es lo que evita re-escanear el QR")
        check(remote._state["adoptado"] is True,
              "y queda marcado como adoptado, que no hay proc que vigilar")
        check(remote.status().get("tunnel") is True,
              "el HUD lo ve vivo aunque el proceso sea hijo del arranque anterior")
        check(abiertos == [],
              f"y NO se ha abierto ni matado ni un solo proceso (vi {abiertos})")

        # ── CASO B: ya hay túnel en esta sesión → no se toca nada ─────────────
        remote._state.update(url="https://ya-tengo.trycloudflare.com", adoptado=False)
        check(await remote.adopta_tunel_al_arrancar() is False,
              "si ya hay túnel en esta sesión, el arranque no lo pisa")
        check(remote._state["url"] == "https://ya-tengo.trycloudflare.com",
              "y respeta el que había")

        # ── CASO C: la nota apunta a algo que no contesta → ni adopta ni abre ──
        nuestro.para()                      # a partir de aquí ya no contesta nadie
        remote._state.update(proc=None, url="", adoptado=False)
        fichero.write_text(json.dumps({"url": nuestro.url, "ts": time.time()}),
                           encoding="utf-8")
        orig_guardado = remote._tunel_guardado
        remote._tunel_guardado = lambda: nuestro.url
        try:
            adoptado = await remote.adopta_tunel_al_arrancar()
        finally:
            remote._tunel_guardado = orig_guardado

        check(adoptado is False, "si la dirección guardada no contesta, no se adopta")
        check(remote._state["url"] == "",
              "y NO se da por bueno un túnel que ya no existe")
        check(abiertos == [],
              f"y AUN ASÍ no se abre ninguno: crear un túnel lo decide el usuario, "
              f"no el arranque (vi {abiertos})")
        check(not fichero.exists(), "y se tira la nota, que ya no vale")
    finally:
        nuestro.para()
        remote._TUNEL_FILE = orig_file
        remote.subprocess.Popen = orig_popen
        remote.subprocess.run = orig_run
        remote._state.clear()
        remote._state.update(orig_estado)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _prueba_enganchado_al_arranque():
    """De nada sirve la función si nadie la llama al arrancar."""
    print("· y el arranque de nexus la llama de verdad")
    app_py = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")
    check("_adopta_tunel_superviviente" in app_py,
          "backend/app.py tiene la tarea de adopción")
    check("adopta_tunel_al_arrancar" in app_py,
          "y llama a la función de remote.py")
    # Tiene que estar DENTRO del lifespan, no definida y olvidada.
    lifespan = app_py[app_py.find("async def lifespan("):app_py.find("app = FastAPI(")]
    check("_adopta_tunel_superviviente()" in lifespan,
          "y la lanza en el lifespan, no se queda definida sin usar")


# ══════════════════════════════════════════════════════════════════════════════
# 3) LA CACHÉ DEL SONDEO TIENE QUE DURAR MÁS QUE EL INTERVALO DE SONDEO
# ══════════════════════════════════════════════════════════════════════════════
def _prueba_umbral_cache():
    from backend.core.infraestructura import remote

    umbrales = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
    check("red" in umbrales, "config/umbrales.json tiene la sección «red»")
    red = umbrales.get("red") or {}
    check("cache_sondeo_seg" in red, "con «cache_sondeo_seg» dentro")
    check("_que_es" in red, "y su explicación en castellano llano, como el resto")

    # El HUD pregunta cada 45 s (setInterval(refreshDevices, 45000)). Si la caché
    # dura MENOS, siempre está fría y se paga la resolución mDNS entera en cada
    # refresco: es exactamente el bug que congelaba nexus 4,3 s cada 45.
    js = js_hud()
    import re as _re
    m = _re.search(r"setInterval\(\s*refreshDevices\s*,\s*(\d+)\s*\)", js)
    intervalo = int(m.group(1)) / 1000.0 if m else 45.0
    check(m is not None, f"se encuentra cada cuánto sondea el HUD ({intervalo} s)")
    check(remote._CACHE_SONDEO > intervalo,
          f"la caché del sondeo ({remote._CACHE_SONDEO} s) dura MÁS que el "
          f"intervalo del HUD ({intervalo} s); si no, no cachea nada")

    # y el valor sale del archivo, no está a fuego
    check(float(red.get("cache_sondeo_seg", -1)) == remote._CACHE_SONDEO,
          "y el valor que usa el código es el del archivo, no uno escrito a mano")

    # la firma ya no lleva el 30.0 clavado
    src = (ROOT / "backend" / "core" / "infraestructura" / "remote.py").read_text(encoding="utf-8")
    check("cache_seg: float | None = None" in src,
          "responde() ya no trae el umbral clavado en la firma")


def main() -> int:
    asyncio.run(_prueba_no_bloquea())
    asyncio.run(_prueba_adopcion())
    asyncio.run(_prueba_adopcion_al_arrancar())
    _prueba_enganchado_al_arranque()
    _prueba_umbral_cache()
    return 1 if _fail else 0


if __name__ == "__main__":
    print("· el túnel que sobrevive y el bucle que no se puede bloquear")
    try:
        main()
    except Exception as e:                                       # noqa: BLE001
        _fail.append(f"EXCEPCIÓN: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
