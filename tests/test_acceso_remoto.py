# -*- coding: utf-8 -*-
"""QUIÉN PUEDE MANDARLE ÓRDENES AL PC — comprobado contra el servidor de verdad.

Requisito de Adri (30/07/2026): «solo pueden mandar órdenes a mi PC los que
están conectados desde la aplicación».

Antes NO era así. El middleware `remote_auth` solo pedía el token CUANDO la
petición traía la cabecera `cf-connecting-ip` (la que añade el túnel de
Cloudflare). Cualquier otra cosa entraba sin credencial: otro móvil de la WiFi,
el portátil de un invitado, o internet entero si se reenviaba el puerto 8177
como sugería docs/MOBILE.md. Y detrás de `POST /api/command` está el asistente
entero, que abre programas y ejecuta cosas en el equipo.

Aquí se arranca nexus DE VERDAD y se llama por HTTP como lo harían:
  * el HUD del propio PC        → entra sin token (es su dueño delante del teclado)
  * un aparato de la WiFi        → 401 sin token, 200 con el token del QR
  * el móvil por el túnel        → igual: sin token no pasa
  * el QR recién escaneado       → /m tiene que cargar sin token (si no, no habría
                                   forma de vincularse nunca)

Ejecutar:  python tests/test_acceso_remoto.py    (desde la carpeta nexus)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from _frontend_js import js_hud  # el HUD entero, no solo command.js

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


class _Cab(dict):
    """Las cabeceras HTTP no distinguen mayúsculas; un dict normal sí."""

    def get(self, k, default=""):
        for kk, vv in self.items():
            if kk.lower() == str(k).lower():
                return vv
        return default


def _get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode("utf-8", "replace"), _Cab(r.headers)


def _pide(base, ruta, metodo="GET", cuerpo=None, cabeceras=None, token=""):
    """Devuelve (codigo, texto). No lanza: un 401 es un resultado, no un error."""
    url = base + ruta + (f"?token={token}" if token else "")
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    cab.update(cabeceras or {})
    req = urllib.request.Request(url, data=datos, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                                       # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


# Cabeceras que hacen que la petición NO parezca de este equipo. Son las que
# pone un túnel o un proxy delante: es como llega el móvil desde fuera.
DE_FUERA = {"Cf-Connecting-Ip": "203.0.113.9"}
DE_LA_WIFI = {"X-Forwarded-For": "192.168.1.77"}


def main() -> int:
    sandbox = Path(tempfile.mkdtemp(prefix="nexus_auth_"))
    (sandbox / "data").mkdir()
    (sandbox / "config").mkdir()
    (sandbox / "config" / "settings.json").write_text(json.dumps({
        "setup_done": True, "llm_provider": "mock", "tts_enabled": False,
        "engram_enabled": False, "hermes_auto": False, "hermes_autostart": False,
        "smart_router": False, "open_mic": False, "wake_enabled": False,
    }), encoding="utf-8")
    (sandbox / "config" / "secrets.json").write_text(
        json.dumps({"link_token": "Token-de-Prueba-aBcD1234"}), encoding="utf-8")
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
        # 80 intentos × 0,4 s = 32 s. Con la suite entera corriendo (y el índice
        # de aplicaciones escaneando en segundo plano) el arranque se puede ir
        # más allá; una prueba que falla por ir con prisa no vale para nada.
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

        TOK = "Token-de-Prueba-aBcD1234"

        # ── 1. EL DUEÑO, DELANTE DE SU PC ────────────────────────────────────
        cod, _ = _pide(base, "/api/jobs")
        check(cod == 200, f"el HUD del propio PC entra sin token (recibí {cod})")
        cod, _ = _pide(base, "/api/command", "POST", {"text": "hola"})
        check(cod == 200, f"y puede mandar órdenes (recibí {cod})")

        # ── 2. OTRO APARATO DE LA WIFI, SIN VINCULAR ─────────────────────────
        for nombre, cab in (("por la WiFi", DE_LA_WIFI), ("por el túnel", DE_FUERA)):
            cod, _ = _pide(base, "/api/command", "POST", {"text": "abre la calculadora"},
                           cabeceras=cab)
            check(cod == 401,
                  f"un aparato SIN vincular {nombre} NO puede dar órdenes (recibí {cod})")
            cod, _ = _pide(base, "/api/config", cabeceras=cab)
            check(cod == 401, f"ni leer la configuración {nombre} (recibí {cod})")
            cod, _ = _pide(base, "/api/link/start", "POST", {}, cabeceras=cab)
            check(cod == 401, f"ni abrir un túnel público {nombre} (recibí {cod})")

        # ── 3. EL MÓVIL YA VINCULADO ─────────────────────────────────────────
        for nombre, cab in (("por la WiFi", DE_LA_WIFI), ("por el túnel", DE_FUERA)):
            cod, txt = _pide(base, "/api/command", "POST", {"text": "hola"},
                             cabeceras=cab, token=TOK)
            check(cod == 200,
                  f"el móvil VINCULADO sí manda órdenes {nombre} (recibí {cod})")
            check("reply" in txt, f"y recibe la respuesta de nexus {nombre}")
        cod, _ = _pide(base, "/api/command", "POST", {"text": "hola"},
                       cabeceras={**DE_FUERA, "X-Nexus-Token": TOK})
        check(cod == 200, f"el token también vale por cabecera (recibí {cod})")

        # ── 4. UN TOKEN EQUIVOCADO NO CUELA ──────────────────────────────────
        # el .upper() comprueba que la comparación distingue mayúsculas
        for malo in ("", "x", TOK[:-1], TOK + "x", TOK.upper(), TOK.lower()):
            cod, _ = _pide(base, "/api/command", "POST", {"text": "hola"},
                           cabeceras=DE_FUERA, token=malo)
            check(cod == 401, f"token «{malo[:12]}…» rechazado (recibí {cod})")

        # ── 5. LA PÁGINA DEL MÓVIL TIENE QUE CARGAR PARA PODER VINCULARSE ────
        cod, txt = _pide(base, "/m", cabeceras=DE_FUERA)
        check(cod == 200, f"/m carga sin token, si no nadie podría vincularse (recibí {cod})")
        cod, _ = _pide(base, "/static/js/command.js", cabeceras=DE_FUERA)
        check(cod == 200, f"y sus estáticos también (recibí {cod})")
        # ── 6. QUE NO SE HAYA COLADO NINGUNA RUTA DE ACCIÓN COMO PÚBLICA ─────
        for ruta, metodo, cuerpo in (("/api/secrets", "POST", {"openai_api_key": "x"}),
                                     ("/api/jobs", "POST", {"title": "x"}),
                                     ("/api/board/delete", "POST", {"id": "1"}),
                                     ("/api/home/control", "POST", {}),
                                     ("/api/n8n", "POST", {}),
                                     ("/api/config", "POST", {"operator_name": "intruso"}),
                                     ("/api/voice", "POST", {})):
            cod, _ = _pide(base, ruta, metodo, cuerpo, cabeceras=DE_LA_WIFI)
            check(cod == 401, f"{ruta} cerrado a quien no está vinculado (recibí {cod})")

        # ── 7. TAILSCALE: la dirección que NO cambia al reiniciar ────────────
        # El túnel «quick» de Cloudflare da un subdominio aleatorio nuevo cada
        # vez que arranca, y el móvil se guarda el viejo: por eso hay que
        # revincular tras cada reinicio. Tailscale da una IP fija.
        cod, txt = _pide(base, "/api/link/tailscale")
        check(cod == 200, f"/api/link/tailscale responde (recibí {cod})")
        ts = json.loads(txt) if cod == 200 else {}
        for clave in ("instalado", "activo", "ip", "descarga", "siguiente_paso"):
            check(clave in ts, f"el estado de Tailscale trae «{clave}»")
        check("tailscale.com" in (ts.get("descarga") or ""), "y de dónde se descarga")
        if not ts.get("instalado"):
            check("instal" in (ts.get("siguiente_paso") or "").lower(),
                  f"si no está, dice qué hacer: {ts.get('siguiente_paso','')[:60]}")
            check(ts.get("activo") is False, "y no se da por activo")
        cod, txt = _pide(base, "/api/link/status")
        st = json.loads(txt)
        for clave in ("via", "estable", "tailscale", "link"):
            check(clave in st, f"/api/link/status trae «{clave}»")
        check(st["via"] in ("tailscale", "nombre", "tunel", "wifi"),
              f"dice por dónde se llega ({st.get('via')})")
        # «Estable» = sobrevive a apagar el PC. Lo son la IP de Tailscale y el
        # nombre del equipo; NO lo son la IP que reparte el router ni la del
        # túnel, que es distinta en cada arranque.
        check(st["estable"] is (st["via"] in ("tailscale", "nombre")),
              f"y solo llama «estable» a lo que no cambia al reiniciar "
              f"(via={st['via']}, estable={st['estable']})")
        js = js_hud()
        check("dirección FIJA" in js, "el HUD distingue la dirección fija")
        check("CAMBIA cada vez que" in js,
              "y avisa de que la del túnel obliga a revincular tras reiniciar")

        # ── 8. LA VINCULACIÓN NO CADUCA AL REINICIAR ─────────────────────────
        # El fallo de raíz: el móvil guardaba UNA dirección. Si era la del túnel
        # (aleatoria en cada arranque), al reiniciar el PC había que volver a
        # escanear el QR. Ahora el QR lleva VARIAS y el móvil se queda con todas.
        st = json.loads(_pide(base, "/api/link/status")[1])
        check(isinstance(st.get("hosts"), list) and st["hosts"],
              f"el estado ofrece varias direcciones ({len(st.get('hosts') or [])})")
        estables = [h for h in st["hosts"] if h.get("estable")]
        check(bool(estables),
              f"y al menos una NO cambia al reiniciar ({[h['host'] for h in estables]})")
        check(any(h["tipo"] == "nombre" for h in st["hosts"]),
              "entre ellas, el nombre del equipo (no la IP, que la reparte el router)")
        check(st.get("nombre_local", "").endswith(".local"),
              f"con forma «equipo.local» ({st.get('nombre_local')})")
        check(st["hosts"][0].get("estable") is True,
              "y la que se ofrece primero es una estable")
        check("alt=" in st["link"] or len(st["hosts"]) == 1,
              "el QR lleva las direcciones de respaldo")
        check("token=" in st["link"], "y el token, que ese sí es para siempre")

        mob = (ROOT / "frontend" / "mobile.html").read_text(encoding="utf-8")
        check("nexus_hosts" in mob, "el móvil guarda la LISTA de direcciones")
        check("function buscaPC" in mob,
              "y busca cuál responde en vez de rendirse con la primera")
        check("refrescaHosts" in mob,
              "y refresca la lista al conectar, para enterarse de un túnel nuevo")
        check("localStorage.setItem('nexus_token'" in mob,
              "el token se guarda para siempre en el móvil")
        check("localStorage.removeItem('nexus_token')" in mob,
              "y solo se borra al desvincular a propósito")

        # ── 9. EL QR Y LA APP HABLAN EL MISMO IDIOMA ─────────────────────────
        # La app Android guarda la lista y prueba una dirección tras otra. Aquí
        # se reproduce SU parser (desdeQR de MainActivity.java) sobre el enlace
        # que genera el backend: si el formato del QR cambiara, esto lo caza.
        from urllib.parse import urlparse, parse_qs
        enlace = st["link"]
        u = urlparse(enlace)
        q = parse_qs(u.query)
        derivadas = [enlace]
        # OJO con el nombre: `base` es la URL del servidor de la prueba. Usar esa
        # misma variable en el bucle la pisaba y la siguiente petición se iba a
        # un sitio inexistente (me pasó al escribir esto).
        for alterna in (q.get("alt", [""])[0]).split(","):
            alterna = alterna.strip()
            if alterna:
                derivadas.append(alterna.rstrip("/") + "/m?token=" + q.get("token", [""])[0])
        check(len(derivadas) == len(st["hosts"]),
              f"la app deriva una dirección por cada vía ({len(derivadas)} de {len(st['hosts'])})")
        for d in derivadas:
            du = urlparse(d)
            check(du.scheme in ("http", "https") and du.netloc and du.path == "/m",
                  f"«{d[:52]}…» es una dirección utilizable")
            check("token=" in du.query, f"y lleva el token: {d[:52]}…")
        check(any(h["host"] in enlace for h in st["hosts"] if h.get("estable")),
              "y la principal del QR es una de las estables")

        java = (ROOT / "movil" / "MainActivity.java").read_text(encoding="utf-8")
        check("link_urls" in java, "la app guarda la LISTA de direcciones")
        check("siguienteCandidato" in java, "y prueba la siguiente cuando una falla")
        check(java.count("siguienteCandidato()") >= 3,
              "en los dos tipos de error y con su definición")
        i_err = java.find("onReceivedError")
        check("siguienteCandidato" in java[i_err:i_err + 600],
              "al fallar la carga NO se rinde: reintenta por otra vía")
        check("fallbackHome" in java[i_err:i_err + 600],
              "y solo manda a reescanear cuando ya no queda ninguna")
        check("saveHosts" in java and "saveHosts" in mob,
              "la página mantiene al día la lista de la app (sin reescanear el QR)")
        check('remove("link_urls")' in java,
              "y al desvincular a propósito se borra la lista entera")

        # la página del móvil no se puede quedar cacheada con la lógica vieja
        _t, cab = _get(base + "/m")
        cc = cab.get("Cache-Control").lower()
        check("no-store" in cc or "no-cache" in cc,
              f"/m se sirve sin caché, para que el móvil no use una versión vieja (recibí «{cc}»)")

        # ── 10. Y EL CÓDIGO DICE LO QUE HACE ─────────────────────────────────
        src = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")
        check("_es_este_equipo" in src, "la decisión «es mi PC o no» está en una función clara")
        check("hmac.compare_digest" in src,
              "el token se compara en tiempo constante (no se puede adivinar midiendo)")
        check('if request.headers.get("cf-connecting-ip"):\n        from backend.core import remote'
              not in src, "ya no se pide el token SOLO cuando viene por el túnel")
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
    print("· quién puede mandarle órdenes al PC")
    try:
        main()
    except Exception as e:                                       # noqa: BLE001
        _fail.append(f"EXCEPCIÓN: {type(e).__name__}: {e}")
        print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
