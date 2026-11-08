"""
nexus — Servidor FastAPI: API local + WebSocket en tiempo real + HUD.

Endpoints principales:
  GET  /                  → HUD (frontend)
  WS   /ws                → eventos en tiempo real (logs, métricas, estado…)
  POST /api/command       → {"text": "..."} → respuesta de nexus
  POST /api/voice         → dispara un ciclo de voz completo (como F9)
  GET  /api/skills        → skills cargadas
  GET  /api/status        → estado de todos los subsistemas
  GET/POST /api/config    → leer / cambiar configuración en caliente
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.core.aplicacion import brain
from backend.core.dominio import contentos
from backend.core.infraestructura import stt, tts
from backend.core.infraestructura.app_index import start_background_index
from backend.core.comun import presupuesto, publicvoice
from backend.core.comun.config import FRONTEND_DIR, settings
from backend.core.comun.events import bus
from backend.core.aplicacion.hotkey import start_hotkey
from backend.core.dominio.memory import graph, memory_status
from backend.core.aplicacion.scheduler import scheduler_loop, system_metrics
from backend.core.aplicacion.skills_loader import load_skills, skills_summary
from backend.core.infraestructura.telegram_bridge import (pending_link_code,
                                                          telegram_loop,
                                                          ttl_vinculacion_segundos)
from backend.core.aplicacion.voice_cycle import open_mic_loop, voice_cycle

async def _arranca_runtime_llm() -> None:
    """Verificación inicial del cerebro, tolerante a fallos: si Ollama tarda o
    no está, el arranque sigue igual y el estado queda anotado."""
    try:
        from backend.core.infraestructura import llm_runtime
        await llm_runtime.initialize_llm_runtime()
    except Exception:
        pass


async def _adopta_tunel_superviviente() -> None:
    """Si el túnel del arranque anterior sigue vivo, quedárselo (tarea #12).

    El «quick tunnel» de Cloudflare da una dirección ALEATORIA distinta cada vez,
    así que levantar uno nuevo obliga a re-escanear el QR en el móvil. Cuando el
    cloudflared del arranque anterior sobrevive al reinicio de nexus, la dirección
    de siempre sigue funcionando: se comprueba y se reutiliza.

    Solo RE-ENGANCHA a un túnel que ya estaba abierto; nunca abre uno. Y va en
    segundo plano y tragándose los fallos: esto no puede retrasar ni tumbar el
    arranque del HUD."""
    try:
        from backend.core.infraestructura import remote
        await remote.adopta_tunel_al_arrancar()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque del núcleo (sustituye al deprecado on_event('startup'))."""
    loop = asyncio.get_running_loop()
    bus.attach_loop(loop)
    load_skills()
    start_hotkey(loop)
    start_background_index()   # escanea TODAS las apps instaladas (Windows)
    asyncio.create_task(asyncio.to_thread(stt.preload_model))  # precarga el modelo de voz
    from backend.core.aplicacion.wake import wake_loop
    from backend.core.aplicacion.background import cycle_loop, proactive_loop
    from backend.core.infraestructura import engram_bridge
    tasks = [asyncio.create_task(scheduler_loop()),
             asyncio.create_task(telegram_loop()),   # solo activo con TELEGRAM_BOT_TOKEN
             asyncio.create_task(open_mic_loop()),   # solo activo con open_mic=true
             asyncio.create_task(wake_loop()),       # «di nexus» (wake_enabled=true)
             asyncio.create_task(cycle_loop()),      # reentreno cíclico + reindex del RAG
             asyncio.create_task(proactive_loop()),  # PM proactivo: recordatorios + empujón diario
             # Instala Engram al arrancar si falta (cubre el nexus.exe, que no pasa por run.bat)
             asyncio.create_task(engram_bridge.maybe_install_background({"settings": settings})),
             # Comprueba el cerebro AL ARRANCAR (en segundo plano, no retrasa el HUD):
             # nexus sabe si tiene modelo antes de que le preguntes, en vez de
             # descubrirlo a mitad de la primera respuesta.
             asyncio.create_task(_arranca_runtime_llm()),
             # Tarea #12: recupera el túnel que sobreviviera al reinicio, para que
             # la dirección del móvil NO cambie y no haya que re-escanear el QR.
             asyncio.create_task(_adopta_tunel_superviviente())]
    for line in brain.boot_report():
        await bus.emit("boot", line)
    yield
    for t in tasks:
        t.cancel()
    from backend.core.comun import net
    await net.aclose()   # cierra el pool de conexiones HTTP compartido


app = FastAPI(title="nexus", version="1.0.0", lifespan=lifespan)


# ---------- AUTENTICACIÓN REMOTA (vinculación por QR, fuera de la WiFi) ----------
# El tráfico del túnel cloudflared llega con la cabecera Cf-Connecting-Ip.
# Local/LAN pasa libre; lo remoto necesita el token de vinculación del QR.
# specs v24: el HUD se quedaba con el CSS/JS viejo en caché y Adri no veía los
# cambios (los iconos salían sin color aunque el archivo del disco ya era el
# nuevo). Los estáticos del HUD NO se cachean: siempre la última versión.
@app.middleware("http")
async def no_cache_estaticos(request, call_next):
    resp = await call_next(request)
    try:
        # /m también: es la página del móvil, y el WebView de Android la cachea
        # con ganas. Si se queda con una versión vieja, el móvil sigue con la
        # lógica antigua de una sola dirección y vuelve el «revincula otra vez».
        if request.url.path.startswith("/static/") or request.url.path in ("/m", "/"):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


# ---------- CABECERAS DEL DOCUMENTO DEL HUD (SEC-10, roadmap P2-11) ----------
# El HUD no llevaba NINGUNA cabecera de seguridad: se podía meter en un iframe
# ajeno y pinchar por encima (clickjacking), y cualquier script de un origen
# remoto podía ejecutarse si alguna vez entraba en el HTML.
#
# QUÉ BLOQUEA ESTA CABECERA (de verdad):
#   * `frame-ancestors 'none'` + `X-Frame-Options: DENY` → nadie enmarca el HUD.
#   * `script-src 'self' 'unsafe-inline'` → ningún script de un origen REMOTO
#     (cdn, "https://...") se ejecuta, aunque alguien lo inyectara en el HTML.
#   * `base-uri 'none'` → no se puede secuestrar <base> para que las rutas
#     relativas del HUD apunten a otro sitio.
#   * `form-action 'self'` → un formulario inyectado no puede mandar lo escrito
#     a un dominio de fuera.
#   * `object-src 'none'` → ni <object>/<embed>/<applet> (plugins).
#
# QUÉ **NO** BLOQUEA, y hay que decirlo claro: `script-src` y `style-src`
# llevan `'unsafe-inline'` porque el HUD de hoy depende de ello. En los tres
# documentos hay HOY 21 manejadores en línea (`index.html` 4: onload/onerror de
# los dos logos; `setup.html` 17: 14 onclick, 2 oninput, 1 onchange) más un
# bloque `<script>` en línea en `mobile.html` y otro en `setup.html`. Eso
# significa que un `<script>` o un `onerror=` inyectado por un `innerHTML` sin
# escapar SÍ se ejecuta. Es una cabecera honesta a medias: cierra el enmarcado y
# los orígenes remotos, NO cierra XSS por HTML inyectado. Quitar
# `'unsafe-inline'` es T18b (pasar esos 21 manejadores y los 2 bloques en línea a
# listeners en los módulos), y hasta que eso esté hecho, ponerla más fuerte
# aquí rompería el HUD sin proteger nada más de lo que ya protege `esc()`.
# El test `tests/unit/frontend/test_escapes_y_cabeceras.py` cuenta esos 21/2 y se
# pone rojo si cambian, para que este comentario no se quede mintiendo.
#
# EFECTO CONOCIDO Y A PROPÓSITO: `index.html` y `setup.html` piden la fuente
# Share Tech Mono a fonts.googleapis.com. Con `style-src 'self'` (y sin
# `font-src` externo) esa hoja ya NO se carga y el HUD se pinta con el respaldo
# que el CSS ya declara (`Cascadia Code`/`Consolas`/`Courier New`). Es el precio
# de no pedirle nada a un tercero para pintar la interfaz; si el dueño prefiere
# su fuente, el camino es servirla desde /static (no reabrir el dominio).
#
# Se sirve SOLO en los documentos HTML (`/`, `/m`, `/setup`), que es donde una
# CSP significa algo: no en `/api/*` (un JSON no se renderiza, la CSP no lo
# gobierna; añadírsela sería ruido que además taparía cuáles son documentos) ni
# en `/static/*` (los .js/.css los carga el propio documento, cuya política ya
# manda). `/docs` (Swagger) se queda SIN ella a propósito: carga su interfaz de
# un CDN y con esto se quedaría en blanco.
#
# El `Cache-Control: no-store` del middleware de arriba NO se toca: hubo un
# incidente real con el HUD sirviendo una versión vieja de caché.
# T18d: la hoja de Share Tech Mono que `index.html` y `setup.html` piden a Google
# NO puede quedarse fuera. `d29417a` puso `style-src 'self'` y el HUD pasó a
# pintarse con la monoespaciada del sistema: una interfaz intacta pero DISTINTA,
# cambiada sin que nadie la eligiera. Se abren los DOS hostees que usa la hoja de
# estilos (fonts.googleapis.com para el CSS, fonts.gstatic.com para el woff2) y
# SOLO para `style-src`/`font-src`: siguen sin poder cargar scripts de fuera, que
# es lo que la cabecera protege. El coste real, escrito: cada carga del HUD
# contacta con Google (IP + User-Agent + referer del HUD). Lo limpio es servirla
# en local desde /static, con la licencia OFL del tipo dentro del repo; eso es
# T18d y necesita el fichero de la fuente, no un cambio de cabecera.
_CSP_HUD = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'; object-src 'none'")
_RUTAS_HTML = ("/", "/m", "/setup")


@app.middleware("http")
async def cabeceras_hud(request, call_next):
    resp = await call_next(request)
    try:
        if request.url.path in _RUTAS_HTML:
            resp.headers["Content-Security-Policy"] = _CSP_HUD
            resp.headers["X-Frame-Options"] = "DENY"
    except Exception:
        pass
    return resp


# Lo único que puede pedirse SIN estar vinculado: la página del móvil y sus
# estáticos (si no, el QR llevaría a una pantalla en blanco y no habría forma de
# vincularse nunca). No hay ninguna acción detrás de estas rutas.
# Las rutas públicas son EXACTAS salvo `/static/`, que es un prefijo. Con
# «/m» como prefijo (como estaba) cualquier ruta que empezara por «/m» se
# saltaba el middleware: hoy solo daba un 404 inocuo, pero una ruta futura
# «/movil/...» habría nacido pública sin que nadie lo eligiera (SEC-03, P1-3).
_RUTAS_PUBLICAS_EXACTAS = ("/m", "/favicon.ico", "/manifest.webmanifest", "/sw.js")
_RUTAS_PUBLICAS_PREFIJO = ("/static/",)


def _es_ruta_publica(ruta: str) -> bool:
    return ruta in _RUTAS_PUBLICAS_EXACTAS or ruta.startswith(_RUTAS_PUBLICAS_PREFIJO)

# Autoridades de loopback que SÍ son este equipo (SEC-03, roadmap P1-3).
_LOOPBACK = ("127.0.0.1", "::1", "localhost")

# Ruta que autentica con su PROPIO secreto y por eso no pide el token del QR.
_RUTA_N8N = "/api/n8n"

# Ruta que canjea el CÓDIGO del QR por un token propio (roadmap P3-2 / T21).
# Está exenta del token porque el móvil que llega con el QR TODAVÍA no tiene
# ninguno: la autoridad es el propio handler, que compara el código de un solo
# uso en tiempo constante y lo consume. Es la misma figura que `/api/n8n` (cada
# una exige lo suyo), y la exención es de la ruta EXACTA.
_RUTA_CANJE = "/api/link/pair"

# Un solo mensaje para los tres motivos (no existe, caducado, ya usado): decir
# cuál es darle una pista a quien va probando códigos.
_ERROR_CANJE = ("código de vinculación no válido, caducado o ya usado — saca otro "
                "QR en este equipo y vuelve a escanearlo")


def _valores_cabecera(headers, nombre: str) -> list:
    """Todos los valores de una cabecera: la petición HTTP puede traerla repetida."""
    try:
        return list(headers.getlist(nombre))
    except Exception:                    # dobles de prueba con un dict normal
        valor = headers.get(nombre, "")
        return [valor] if valor else []


def _parsea_host_local(valor: str):
    """Autoridad `host[:puerto]` de loopback → lo parseado; si no, None.

    Las reglas son las MISMAS para HTTP y para el WebSocket, y son estrictas a
    propósito (SEC-03): el `Host` no puede traer userinfo (`127.0.0.1@evil`), ni
    ruta, ni query, ni espacios de más, ni quedarse sin puerto, y lo parseado
    tiene que ser EXACTAMENTE lo que vino. Si no es una autoridad de loopback
    limpia no hay confianza local y hay que presentar el token del QR."""
    if not valor or valor != valor.strip():
        return None
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit("http://" + valor)
        if (parsed.hostname not in _LOOPBACK or parsed.port is None
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or parsed.netloc.lower() != valor.lower()):
            return None
    except ValueError:                   # puerto no numérico, corchetes rotos…
        return None
    return parsed


def _origen_coincide(origin: str, host: str, parsed_host) -> bool:
    """¿El `Origin` es esta misma autoridad? (la regla que ya usaba el WS).

    Esquema `http`, mismo netloc, mismo host y mismo puerto, y nada de userinfo,
    ruta, query ni fragmento: `http://evil.example:8177` no puede decir que es
    el HUD aunque su dominio resuelva a 127.0.0.1 (DNS rebinding, SEC-03)."""
    if not origin or origin != origin.strip():
        return False
    from urllib.parse import urlsplit
    try:
        parsed_origin = urlsplit(origin)
        return (parsed_origin.scheme == "http"
                and parsed_origin.netloc.lower() == host.lower()
                and parsed_origin.hostname == parsed_host.hostname
                and parsed_origin.port == parsed_host.port
                and parsed_origin.username is None and parsed_origin.password is None
                and not parsed_origin.path and not parsed_origin.query
                and not parsed_origin.fragment)
    except ValueError:
        return False


def _es_este_equipo(request) -> bool:
    """¿La petición es del HUD de ESTE PC? (que el peer sea loopback NO basta).

    SEC-03 / roadmap P1-3. Antes bastaba con que el peer fuera 127.0.0.1/::1/
    localhost: una página del navegador que resuelve SU dominio a 127.0.0.1
    (DNS rebinding) entraba como el dueño y leía el token del QR. Ahora, además:

      * no puede traer cabeceras de proxy (`cf-connecting-ip`/`x-forwarded-for`),
      * el peer tiene que ser de loopback,
      * `Host` tiene que ser una autoridad de loopback CON puerto, una sola vez y
        sin adornos (`_parsea_host_local`),
      * si viene `Origin`, tiene que ser exactamente esa autoridad
        (`_origen_coincide`). Sin `Origin` se acepta: los clientes nativos
        (pywebview, curl, scripts) no lo mandan, igual que en el WebSocket.

    Cualquier otra cosa con peer de loopback NO es este equipo y tiene que
    presentar el token del QR por el camino normal."""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        return False                      # viene de fuera por un túnel/proxy
    peer = getattr(getattr(request, "client", None), "host", "") or ""
    if peer not in _LOOPBACK:
        return False
    valores = _valores_cabecera(request.headers, "host")
    if len(valores) != 1:
        return False                      # sin Host o con Host repetido: no se adivina
    host = valores[0]
    parsed_host = _parsea_host_local(host)
    if parsed_host is None:
        return False
    origin = request.headers.get("origin", "")
    if not origin:
        return True                       # cliente nativo: pywebview, curl, scripts
    return _origen_coincide(origin, host, parsed_host)


def _canal_efectivo(conexion, pedido: str | None = None) -> str:
    """Qué canal recibe el cerebro: lo decide la CONEXIÓN, no el cuerpo (T8e).

    POR QUÉ EXISTE (auditoría, roadmap P2-1, verificador de T8c): desde T8c la
    columna de la matriz canal × efecto (`canales.politica`) la decide el canal,
    así que el canal pasó de ser una etiqueta a ser la DECISIÓN. Y `POST
    /api/command` lo leía del cuerpo (`payload["channel"]`): un móvil vinculado —o
    cualquier cliente del túnel— que dijera `"channel": "pc"` obtenía la columna
    LOCAL y se saltaba el «sí» de los envíos externos. La credencial decía «este
    teléfono puede mandar órdenes», no «este teléfono es el PC».

    La regla, y no hay más: si la conexión es este equipo (`_es_este_equipo`, la
    MISMA confianza local de SEC-03: peer de loopback, sin cabeceras de proxy,
    `Host` de loopback limpio y `Origin` coherente), el canal es el que dice el
    cliente (`pedido`, o `pc` si no reclama ninguno). Si NO lo es —token de un
    dispositivo, WiFi, túnel, cualquier cosa de fuera— el canal es `mobile`, diga
    lo que diga el cuerpo.

    El túnel cuenta como fuera aunque cloudflared conecte DESDE loopback: trae
    `cf-connecting-ip`, y esa cabecera es justo lo primero que `_es_este_equipo`
    rechaza. Por eso aquí no se mira «¿el peer es 127.0.0.1?», que daría por
    bueno todo lo que entra por el túnel.

    Vale para peticiones HTTP y para el WebSocket (los dos tienen `headers` y
    `client`). El WS ya autenticó antes de llegar aquí y un WS de loopback sin
    `Origin` solo lo puede abrir un cliente nativo de este equipo; aun así, un WS
    con token de dispositivo o por el túnel entra como `mobile`, que es lo que
    antes NO pasaba (se quedaba en `pc` si no mandaba el «hello» del móvil).

    `pedido=None` es «esta ruta no recibe canal del cliente» (los botones de
    casa): entonces no hay nada que pisar y no se apunta nada. Cuando SI se pisa
    un canal reclamado se escribe UNA línea en el registro, a nivel info, para
    que quede rastro del intento de reclamar el canal local desde fuera. Nunca
    se escribe el token ni ninguna credencial: solo el canal reclamado.
    """
    if _es_este_equipo(conexion):
        return pedido or "pc"
    if pedido and str(pedido).strip().lower() != "mobile":
        try:
            bus.emit_sync("log", {"level": "info", "msg": (
                "Canal: la conexión NO es este equipo, así que el canal pedido "
                f"«{pedido}» cuenta como «mobile» (la matriz canal × efecto se "
                "decide por la conexión, no por el cuerpo de la petición)")})
        except Exception:                                  # noqa: BLE001
            pass
    return "mobile"


# ---------- SECRETO COMPARTIDO DE n8n (auditoría 30/07/2026, SEC-01 / P1-1) ----------
# `/api/n8n` NO se fía del loopback. n8n corre en Docker, y en este equipo
# cualquier proceso puede hablar con 127.0.0.1:8177: la exención «viene de casa»
# valía para el HUD y aquí dejaba que un flujo sin autenticación mandara correos.
# Ahora la cabecera `x-nexus-n8n-secret` se exige SIEMPRE, también desde casa.
_N8N_CABECERA = "x-nexus-n8n-secret"
_ERROR_N8N_SIN_SECRETO = ("no autorizado — el flujo de n8n necesita la cabecera "
                          f"{_N8N_CABECERA}")


def secreto_n8n() -> str:
    """Secreto compartido de `/api/n8n`. Se genera la primera vez que hace falta.

    Se guarda con la API de secretos que ya existe (`settings.set_secret`), así
    que acaba en `config/secrets.json` (que no se sube al repositorio) y NUNCA
    en `settings.json` ni en `GET /api/config`. El orden de precedencia es el de
    siempre en este proyecto: primero lo guardado, y si no hay nada, la variable
    de entorno (`NEXUS_N8N_SECRET`, o `N8N_SECRET` como el resto de secretos)."""
    actual = (settings.secret("n8n_secret")
              or os.getenv("NEXUS_N8N_SECRET", "").strip())
    if actual:
        return actual
    import secrets as _pysecrets
    nuevo = _pysecrets.token_urlsafe(32)
    settings.set_secret("n8n_secret", nuevo)
    return nuevo


def _ficha_del_token(tok: str):
    """La ficha del móvil dueño de este token PROPIO (P3-2), o None.

    Nunca lanza: sin tienda legible no hay tokens de dispositivo válidos (falla
    cerrado) y la petición sigue por el camino del token compartido, que es el de
    siempre.
    """
    from backend.core.infraestructura import remote
    try:
        return remote.device_owner(tok)
    except Exception:                                          # noqa: BLE001
        return None


@app.middleware("http")
async def remote_auth(request, call_next):
    """CERRADO POR DEFECTO: manda órdenes quien está vinculado, y nadie más.

    Antes esto solo pedía el token CUANDO la petición traía la cabecera
    `cf-connecting-ip` (la que añade el túnel). Todo lo demás —cualquier
    dispositivo de la WiFi, o de internet si se reenviaba el puerto 8177 como
    sugería docs/MOBILE.md— entraba SIN NINGUNA CREDENCIAL a /api/command, o sea, a
    dar órdenes al PC. Lo único que protegía era que uvicorn escucha en
    127.0.0.1 (auditoría 30/07/2026).

    Ahora: este mismo equipo pasa; cualquier otro origen necesita el token del
    QR, venga por el túnel, por la WiFi o por donde sea.

    Hay DOS excepciones, y solo dos, además de este equipo:

      * las rutas públicas del QR (`_es_ruta_publica`): la página del móvil y sus
        estáticos, que no tienen ninguna acción detrás;
      * exactamente `/api/n8n` (`_RUTA_N8N`), que NO pide el token del QR porque
        su autoridad es su propio handler: exige `x-nexus-n8n-secret` SIEMPRE,
        también desde este equipo (SEC-01). Sin la exención, el flujo de n8n que
        corre en Docker llega con un peer que no es loopback
        (`host.docker.internal:8177`) y este middleware lo tumbaba con un 401
        ANTES de que su comprobación del secreto llegara a correr: los flujos de
        ejemplo no podían funcionar nunca. `/api/n8n/secret` NO está exenta:
        sigue siendo de este equipo y de nadie más.

    Y desde P3-2 (roadmap P3-2) hay una tercera, del mismo tipo: exactamente
    `/api/link/pair` (`_RUTA_CANJE`). El móvil que escanea el QR no tiene ninguna
    credencial todavía, así que lo que autoriza es el CÓDIGO de un solo uso, y
    quien lo comprueba (y lo consume) es el handler.

    LA CREDENCIAL ACEPTADA SON DOS desde P3-2, y esto es una DECISIÓN DE
    COMPATIBILIDAD, no un descuido: el token PROPIO de cada dispositivo (guardado
    como digesto en `data/dispositivos.json`) y, por el período de gracia, el
    token COMPARTIDO de siempre (`remote.link_token()`), que es el que tienen
    guardado los teléfonos ya instalados. Retirarlo de golpe los dejaría fuera
    sin explicación; se apaga revocándolo (decisión (a), `remote.revoke_device`).
    """
    ruta = request.url.path
    if ruta == _RUTA_N8N:
        return await call_next(request)   # el handler exige su propio secreto
    if ruta == _RUTA_CANJE:
        return await call_next(request)   # el handler exige el código de un solo uso
    if _es_este_equipo(request) or _es_ruta_publica(ruta):
        return await call_next(request)

    from backend.core.infraestructura import remote
    tok = (request.query_params.get("token")
           or request.headers.get("x-nexus-token", "")
           or request.cookies.get("nexus_token", ""))
    import hmac
    # 1) token PROPIO de un dispositivo (P3-2). 2) token COMPARTIDO de siempre.
    if _ficha_del_token(str(tok)) is None:
        esperado = remote.link_token()
        # Comparación en tiempo constante: un `!=` normal deja adivinar el token
        # carácter a carácter midiendo cuánto tarda en responder. En BYTES
        # (`remote.mismo_secreto`): con `str`, un `?token=ñ…` lanzaba TypeError y
        # el middleware devolvía un 500 en vez del 401 que es.
        # En BYTES: con `str`, `hmac.compare_digest` lanza TypeError si alguno
        # trae algo fuera de ASCII, y un `?token=ñ…` de la barra del navegador
        # convertía el 401 en un 500. Mismo tiempo constante, mismo «se llama
        # siempre» (también con el intento vacío, para no dejar un atajo).
        # Autocontenido a propósito: este handler se ejecuta también extraído por
        # AST en `test_host_origin.py`, donde no existen los imports del módulo.
        if not esperado or not hmac.compare_digest(
                str(tok or "").encode("utf-8", "replace"),
                str(esperado).encode("utf-8", "replace")):
            return JSONResponse({"error": "no autorizado — vincula el móvil con el QR de nexus"},
                                status_code=401)
    response = await call_next(request)
    response.set_cookie("nexus_token", tok, max_age=86400 * 365,
                        httponly=True, samesite="lax")
    return response


class Command(BaseModel):
    text: str
    speak: bool = False
    voice: bool = False      # true si el texto es TRANSCRIPCIÓN de voz (móvil)
    channel: str = "pc"      # pc | mobile — quién manda la orden (habla solo ese aparato)


class SayText(BaseModel):
    """Cuerpo de /api/tts_say (la voz del móvil). FALTABA esta clase y el backend
    moría al arrancar con NameError — por eso el último run.bat no levantaba."""
    text: str = ""


def _trusted_local_ws_origin(ws: WebSocket) -> bool:
    """Tokenless browser access requires a loopback Host and its own HTTP Origin.

    Native/non-browser clients omit Origin and must instead supply a QR token.
    Proxy forwarding headers never grant local trust, even with a loopback peer.
    """
    host = ws.headers.get("host", "")
    origin = ws.headers.get("origin", "")
    if not host or not origin:
        return False
    parsed_host = _parsea_host_local(host)
    if parsed_host is None:
        return False
    return _origen_coincide(origin, host, parsed_host)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    from backend.core.infraestructura import remote
    # A tokenless local browser is trusted only with a same-authority loopback
    # Origin. QR-authenticated LAN/tunnel/mobile ?host clients can legitimately
    # connect across origins; do not impose this browser constraint on them.
    _local = (not ws.headers.get("cf-connecting-ip")
              and not ws.headers.get("x-forwarded-for")
              and getattr(getattr(ws, "client", None), "host", "")
              in ("127.0.0.1", "::1", "localhost"))
    # P3-2: por aquí pasan DOS credenciales válidas, el token PROPIO del móvil y
    # el COMPARTIDO de los ya instalados (período de gracia). `via_antigua` es lo
    # que luego permite al HUD enseñar «dispositivo antiguo».
    via_antigua = False
    if not (_local and _trusted_local_ws_origin(ws)):
        import hmac
        intento = str(ws.query_params.get("token", ""))
        try:
            ficha_ws = remote.device_owner(intento)
        except Exception:                                     # noqa: BLE001
            # Sin tienda legible no hay tokens de dispositivo (falla cerrado) y se
            # sigue por el camino del token compartido. Aquí, y no en un ayudante
            # del módulo, porque este handler también se ejecuta aislado en las
            # pruebas (ver `test_host_origin.py` sección 7).
            ficha_ws = None
        if ficha_ws is None:
            esperado = remote.link_token()
            if not esperado or not hmac.compare_digest(
                    str(intento or "").encode("utf-8", "replace"),
                    str(esperado).encode("utf-8", "replace")):
                await ws.close(code=4401)
                return
            via_antigua = True
    await ws.accept()
    bus.register(ws)
    # Reenvía historial reciente para que el HUD reconecte con contexto
    import json
    for evt in bus.replay(30):
        await ws.send_text(json.dumps(evt, ensure_ascii=False, default=str))
    my_device = None      # ficha del móvil si este WS se presenta como tal
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"type": "command", "text": raw}
            mtype = msg.get("type")
            if mtype == "hello" and msg.get("role") == "mobile":
                # El móvil acaba de VINCULARSE: lo registramos, avisamos al HUD
                # (para cerrar el QR y mostrar el dispositivo) y le confirmamos.
                ip = (ws.headers.get("cf-connecting-ip")
                      or (ws.client.host if ws.client else ""))
                my_device = remote.register_device({
                    "id": msg.get("id", ""), "name": msg.get("name", ""),
                    "ua": msg.get("ua", ""), "ip": ip, "antiguo": via_antigua})
                await ws.send_text(json.dumps({"type": "paired_ack", "data": {
                    "pc": settings.get("operator_name", "tu PC"),
                    "name": my_device["name"]}}, ensure_ascii=False))
                await bus.emit("paired", {"name": my_device["name"],
                                          "id": my_device["id"],
                                          "count": len(remote.devices())})
                await bus.emit("log", {"level": "ok",
                                       "msg": f"📱 Móvil vinculado: {my_device['name']}"})
            elif mtype == "command":
                result = await brain.process(
                    msg.get("text", ""),
                    source=("voice" if msg.get("voice") else "text"),
                    # T8e: el canal sale de la CONEXIÓN (ver `_canal_efectivo`),
                    # no de lo que diga el mensaje del cliente. El «hello» del
                    # móvil es lo único que puede pedir `mobile`.
                    channel=_canal_efectivo(ws, "mobile" if my_device else None))
                if msg.get("speak"):
                    asyncio.create_task(tts.speak(result["reply"]))
            elif mtype == "voice":
                asyncio.create_task(voice_cycle())
    except WebSocketDisconnect:
        bus.unregister(ws)
        if my_device:
            # NO se desvincula: móvil bloqueado o app en 2º plano = WS cortado,
            # pero SIGUE vinculado. Se marca «en espera» y solo si no vuelve en
            # 10 min se olvida de verdad (antes el HUD decía «no vinculado» al
            # instante — bug grave reportado por Adri).
            did, name = my_device["id"], my_device["name"]
            remote.mark_offline(did)
            try:
                await bus.emit("log", {"level": "info",
                               "msg": f"📱 {name} en segundo plano — sigue vinculado"})
            except Exception:
                pass

            async def _grace_forget(did=did, name=name):
                await asyncio.sleep(600)
                if not remote.is_online(did):
                    remote.forget_device(did)
                    try:
                        await bus.emit("unpaired", {"id": did, "name": name,
                                                    "count": len(remote.devices())})
                    except Exception:
                        pass
            asyncio.create_task(_grace_forget())


@app.post("/api/command")
async def api_command(cmd: Command, request: Request):
    # T8e: el `channel` del cuerpo solo vale si la conexión es este equipo.
    # Antes un móvil vinculado (o el túnel) que mandara `"channel": "pc"` se
    # quedaba con la columna LOCAL de la matriz canal × efecto.
    canal = _canal_efectivo(request, "mobile" if cmd.channel == "mobile" else "pc")
    result = await brain.process(cmd.text, source=("voice" if cmd.voice else "text"),
                                 channel=canal)
    if cmd.speak:
        asyncio.create_task(tts.speak(result["reply"]))
    return result


@app.post("/api/voice")
async def api_voice():
    return await voice_cycle()


# ---------------------- MULTITAREA (panel de trabajos concurrentes) ----------------------
@app.get("/api/weather")
async def api_weather():
    """Tiempo actual para el header del HUD (v23 T15). {} si el servicio falla:
    un fallo del servicio meteorológico no puede bloquear el resto de nexus."""
    from backend.core.dominio import briefing
    try:
        return await briefing.weather_now()
    except Exception:
        return {}


@app.get("/api/jobs")
async def api_jobs():
    from backend.core.aplicacion.jobs import jobs
    return {"list": jobs.snapshot(), "counts": jobs.counts(), "badge": jobs.badge()}


@app.post("/api/jobs")
async def api_jobs_submit(payload: dict, request: Request):
    """Lanza una orden como TRABAJO en segundo plano (multitarea).
    v23 (T9): cada ejecución lleva su requestId y los duplicados vivos se bloquean."""
    import uuid as _uuid
    from backend.core.aplicacion.jobs import jobs
    text = str(payload.get("text", "")).strip()
    if not text:
        return {"error": "sin texto"}
    # T8e: el `channel` del cuerpo solo vale desde este equipo. Del móvil o del
    # túnel, un trabajo es SIEMPRE del canal remoto (y sus efectos se preguntan).
    channel = _canal_efectivo(request, str(payload.get("channel", "pc")))
    dup = jobs.active_duplicate(text, channel)
    if dup:
        return {"ok": False, "duplicate": True, "id": dup["id"], "num": dup["num"],
                "error": f"ese trabajo ya está en marcha (#{dup['num']}, {dup['status']})"}
    rid = str(payload.get("request_id") or _uuid.uuid4().hex[:8])
    jid = await jobs.submit(text, lambda: brain.process(text, source="job",
                                                        channel=channel, request_id=rid),
                            request_id=rid, request=text, channel=channel,
                            dedupe_key=text)
    return {"ok": True, "id": jid, "request_id": rid}


@app.post("/api/jobs/{jid}/cancel")
async def api_jobs_cancel(jid: str):
    from backend.core.aplicacion.jobs import jobs
    return {"ok": await jobs.cancel(jid)}


@app.post("/api/jobs/seen")
async def api_jobs_seen(payload: dict | None = None):
    """Marca los resultados como REVISADOS: limpia el ✓ / ! del sidebar (v23 T10)."""
    from backend.core.aplicacion.jobs import jobs
    jid = str((payload or {}).get("id", ""))
    return {"seen": await jobs.mark_seen(jid), "badge": jobs.badge()}


@app.post("/api/jobs/clear")
async def api_jobs_clear():
    from backend.core.aplicacion.jobs import jobs
    return {"removed": jobs.clear_done()}


# ── GANCHO DE PRUEBAS (v23 T22) ────────────────────────────────────────────────
# Solo existe cuando se arranca con NEXUS_E2E=1 (lo hace el runner de las pruebas
# end-to-end). En un nexus normal esta ruta NO está registrada.
if os.environ.get("NEXUS_E2E") == "1":

    @app.post("/api/_e2e/job")
    async def api_e2e_job(payload: dict):
        """Lanza un trabajo controlado (duerme N segundos) para poder verificar en
        la interfaz real el indicador de Multitarea: En curso → 2 → ✓ / !."""
        from backend.core.aplicacion.jobs import jobs
        secs = float(payload.get("seconds", 2))
        fail = bool(payload.get("fail"))
        title = str(payload.get("title", "Trabajo de prueba"))

        async def _work():
            await asyncio.sleep(secs)
            if fail:
                raise RuntimeError("fallo provocado por la prueba e2e")
            return {"reply": f"{title}: terminado tras {secs}s",
                    "files": [{"path": "e2e/salida.txt", "action": "creado"}]}
        jid = await jobs.submit(title, _work, request=title, channel="pc",
                                dedupe_key=title, notify=bool(payload.get("notify")))
        return {"ok": True, "id": jid}

    @app.post("/api/_e2e/chat")
    async def api_e2e_chat(payload: dict):
        """Emite un evento `chat` con una respuesta de la IA larga y controlada, para
        comprobar en la interfaz real que la ventana del chat no la corta."""
        from backend.core.comun.events import bus
        await bus.emit("chat", {"user": str(payload.get("user", "prueba")),
                                "reply": str(payload.get("reply", "")),
                                "provider": "e2e", "skill": None})
        return {"ok": True}


@app.get("/api/skills")
async def api_skills():
    return skills_summary()


@app.get("/api/skill/{folder}")
async def api_skill_detail(folder: str):
    """Contenido de una skill para la pantalla de nodo: SKILL.md + intents + patrones."""
    from backend.core.aplicacion.skills_loader import get_skills
    from backend.core.comun.config import SKILLS_DIR
    s = get_skills().get(folder)
    if not s:
        return {"error": "not found"}
    doc = ""
    md = SKILLS_DIR / folder / "SKILL.md"
    if md.exists():
        doc = md.read_text(encoding="utf-8", errors="replace")
    return {"folder": folder, "name": s.name, "description": s.description,
            "status": s.status, "calls": s.calls,
            "intents": list(s.patterns.keys()),
            "patterns": {k: v.pattern for k, v in s.patterns.items()},
            "doc": doc}


@app.get("/api/knowledge")
async def api_knowledge_list():
    """Biblioteca de conocimiento importada (openClaw/Gru): lista de SKILL.md."""
    from backend.core.comun.config import ROOT
    kdir = ROOT / "knowledge"
    out = []
    if kdir.is_dir():
        for md in sorted(kdir.rglob("SKILL.md")):
            try:
                txt = md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            title = next((l.lstrip("# ").strip() for l in txt.splitlines() if l.startswith("#")),
                         md.parent.name)
            out.append({"name": md.parent.name, "title": title,
                        "chars": len(txt), "excerpt": txt[:220]})
    return {"count": len(out), "skills": out}


@app.get("/api/status")
async def api_status():
    return {
        "metrics": system_metrics(),
        "memory": memory_status(),
        "stt": stt.stt_status(),
        "tts": tts.tts_status(),
        "llm": {"provider": settings.get("llm_provider"),
                "ollama_model": settings.get("ollama_model"),
                "cloud_model": settings.get("cloud_model")},
        "skills": len(skills_summary()),
        # T13 / SEC-09 (advisory del verificador sobre 562c777): una clave que DPAPI no
        # puede abrir aquí sólo se avisaba por consola AL IMPORTAR, así que sin consola
        # el dueño veía «no hay clave» donde pasa «está y no se abre con esta cuenta».
        # Son NOMBRES, nunca valores: un nombre no es un secreto.
        "secretos_ilegibles": settings.secretos_ilegibles(),
        # T19 / AI-07: lo que nexus lleva gastado HOY de modelo, por proveedor. Son
        # contadores y nombres de proveedor/clase — ni una clave, ni un modelo, ni
        # un fragmento de prompt. Es lo que hace que el techo diario se pueda ver
        # antes de chocar con él.
        "presupuesto": presupuesto.resumen(),
    }


@app.get("/api/graph")
async def api_graph():
    """Nodos y enlaces del grafo de memoria (para la vista de nodos del HUD)."""
    return graph.graph()


@app.get("/api/note")
async def api_note(name: str = ""):
    """Contenido de una nota del grafo (para el panel lateral del nodo)."""
    from backend.core.dominio.memory import MEMORY_DIR
    for p in MEMORY_DIR.rglob("*.md"):
        if p.stem == name:
            try:
                return {"name": p.stem, "content": p.read_text(encoding="utf-8")[:6000]}
            except Exception:
                break
    return {"name": name, "content": ""}


@app.get("/api/local_models")
async def api_local_models():
    """Modelos LLM locales detectados (Ollama, LM Studio) para el selector de ⚙."""
    from backend.core.infraestructura.llm import scan_local_models
    return await scan_local_models()


# ─── RUNTIME DE MODELOS ───────────────────────────────────────────────────────
# Un solo sitio decide qué cerebro está funcionando, y lo decide PROBÁNDOLO.
# (El HUD ya no clasifica modelos por su cuenta ni deduce el «EN USO» de la
#  configuración guardada: pregunta aquí.)
@app.get("/api/llm/status")
async def api_llm_status(verify: bool = False):
    """Estado REAL del cerebro. `?verify=1` fuerza una comprobación nueva."""
    from backend.core.infraestructura import llm_runtime as rt
    st = await rt.verify_current(force=True) if verify else rt.status()
    if verify or st.checked_at:
        return st.publico()
    return (await rt.verify_current()).publico()


@app.get("/api/llm/status_full")
async def api_llm_status_full():
    """Igual pero con el detalle técnico: para el panel de diagnóstico."""
    from backend.core.infraestructura import llm_runtime as rt
    return (await rt.verify_current()).tecnico()


@app.get("/api/llm/models")
async def api_llm_models():
    """Catálogo YA CLASIFICADO: qué sirve Ollama, qué está solo en disco y qué
    es de embeddings. La interfaz solo pinta."""
    from backend.core.infraestructura import llm_runtime as rt
    return await rt.catalog()


class LLMActivate(BaseModel):
    provider: str = "ollama"
    model: str = ""


@app.post("/api/llm/activate")
async def api_llm_activate(payload: LLMActivate):
    """Activa un cerebro. Solo se guarda si RESPONDE a una inferencia real:
    si falla, la configuración se queda como estaba y se devuelve el motivo."""
    from backend.core.infraestructura import llm_runtime as rt
    st = await rt.activate(payload.provider, payload.model)
    await bus.emit("log", {"level": "ok" if st.active else "warn", "msg": st.resumen()})
    return st.publico()


@app.get("/api/voices")
async def api_voices():
    """Catálogo de voces reales disponibles por motor (para el selector de ⚙)."""
    return tts.all_voices()


@app.get("/api/audio_devices")
async def api_audio_devices():
    """Micrófonos de ENTRADA disponibles (la SALIDA la elige el HUD con setSinkId)."""
    return {"inputs": stt.list_input_devices()}


@app.post("/api/tts_test")
async def api_tts_test():
    st = tts.tts_status()
    can = (st.get("engine") != "off") and bool(
        st.get("edge") or st.get("elevenlabs") or st.get("local"))
    if can:
        asyncio.create_task(tts.speak(
            f"Hola, soy nexus. Esta es mi voz, {settings.get('tts_voice')}."))
    return {"ok": True, "spoke": can}


_ULTIMO_SALUDO = [0.0]          # marca de tiempo del último saludo REALMENTE dicho


@app.post("/api/greet")
async def api_greet():
    """Saludo al abrir: lo GENERA el modelo y es DISTINTO cada vez (día, fecha,
    tareas de hoy, un toque de ingenio). Si el LLM tarda >10 s o no hay proveedor,
    cae a un saludo local VARIADO (nunca la frase fija de siempre).

    CON DESCANSO. Este endpoint lo llama el HUD al arrancar, y el saludo NO va
    solo a quien lo pidió: se emite al bus (lo ven todas las ventanas) y se dice
    EN VOZ ALTA. Así que cada pestaña que se abría, cada vez que se cerraba y
    reabría la ventana, el móvil, o una prueba automática, saludaba otra vez —y
    a todo el mundo—. Adrián lo vio saludándole tres veces seguidas sin haber
    dicho nada.

    Dentro del descanso se contesta que sí, pero sin emitir ni hablar: quien
    acaba de abrir ya tiene su HUD, y quien estaba mirando no se lleva un saludo
    que no ha provocado.
    """
    import datetime as _dt
    import random
    import time as _t

    from backend.core.infraestructura import llm as _llm
    from backend.core.comun.config import CONFIG_DIR
    minutos = 45.0
    try:                                    # el umbral vive en config/umbrales.json
        _u = json.loads((CONFIG_DIR / "umbrales.json").read_text(encoding="utf-8"))
        minutos = float((_u.get("saludo") or {}).get("minutos_entre_saludos", 45))
    except Exception:                       # un JSON roto no deja a nexus sin saludo
        pass
    if _ULTIMO_SALUDO[0] and _t.monotonic() - _ULTIMO_SALUDO[0] < minutos * 60:
        return {"ok": True, "spoke": False, "text": "", "repetido": True}
    op = settings.get("operator_name", "") or "jefe"
    now = _dt.datetime.now()
    momento = ("buenos días" if now.hour < 13
               else "buenas tardes" if now.hour < 21 else "buenas noches")
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    dia = dias[now.weekday()]
    tareas = []
    try:
        from backend.core.dominio import board
        hoy = _dt.date.today().isoformat()
        tareas = [t.get("title", "") for t in board._load()
                  if t.get("due") == hoy and t.get("state") not in ("hecha", "completada")][:3]
    except Exception:
        tareas = []
    text = ""
    try:
        pista = (" Tareas suyas para HOY: " + "; ".join(tareas) + ".") if tareas else ""
        prompt = (f"Genera el saludo de ARRANQUE de nexus para {op} ({momento}; hoy es "
                  f"{dia} {now.day}). UNA o dos frases, tono JARVIS elegante con algo de "
                  "ingenio, y SIEMPRE DIFERENTE: prohibido «todos los sistemas en línea» "
                  "y cualquier fórmula repetida. Puedes citar el día, la fecha o una de "
                  "sus tareas de hoy." + pista + " Devuelve SOLO el saludo, sin comillas.")
        reply, prov = await asyncio.wait_for(_llm.ask_llm(prompt), timeout=10)
        # «ninguno» = no hubo modelo: ese texto es un aviso, NO un saludo.
        if prov not in ("mock", "ninguno"):
            text = reply.strip().strip('"«»').strip()[:260]
    except Exception:
        text = ""
    if not text:
        base = [
            f"{momento.capitalize()}, {op}. {dia.capitalize()} en marcha y yo al pie del cañón.",
            f"{momento.capitalize()}, {op}. Sistemas afinados; tú pon el café, del resto me encargo yo.",
            f"A sus órdenes, {op}. {dia.capitalize()} {now.day}: todo listo por aquí.",
            f"{momento.capitalize()}, {op}. Motores encendidos, ¿por dónde empezamos hoy?",
            f"Aquí nexus, {op}: despierto, afinado y con ganas de tachar tareas.",
            f"{momento.capitalize()}, {op}. El día es tuyo; la logística, mía.",
        ]
        if tareas:
            base.append(f"{momento.capitalize()}, {op}. Para hoy tienes: {tareas[0]}. "
                        "¿Atacamos con eso?")
        text = random.choice(base)
    st = tts.tts_status()
    can = (st.get("engine") != "off") and bool(
        st.get("edge") or st.get("elevenlabs") or st.get("local"))
    if can:
        asyncio.create_task(tts.speak(text))
    else:
        await bus.emit("log", {"level": "warn",
                               "msg": "Voz: no hay motor TTS instalado — ejecuta run.bat "
                                      "(instala edge-tts) para que nexus te hable."})
    await bus.emit("chat", {"user": "", "reply": text, "provider": "saludo", "skill": None})
    _ULTIMO_SALUDO[0] = _t.monotonic()      # se marca SOLO cuando de verdad ha saludado
    return {"ok": True, "spoke": can, "text": text}


@app.post("/api/tts_say")
async def api_tts_say(payload: SayText):
    """VOZ del MÓVIL: genera el MP3 con la MISMA voz del HUD y devuelve su URL para
    que la app lo reproduzca ella sola (el WebView del APK no trae speechSynthesis).
    La app YA llamaba a este endpoint… que no existía: por eso iba MUDA."""
    url = await tts.synthesize((payload.text or "").strip()[:1500])
    await bus.emit("log", {"level": "info" if url else "warn",
                           "msg": ("\U0001F4F1 tts_say -> audio " + url) if url
                                  else "\U0001F4F1 tts_say -> SIN AUDIO (movil no puede hablar)"})
    return {"url": url}


@app.post("/api/stt_audio")
async def api_stt_audio(request: Request):
    """OÍDO del MÓVIL: recibe el audio grabado en la app (webm/ogg/m4a), lo
    transcribe con el MISMO Whisper local del PC y devuelve el texto. Así el móvil
    tiene voz de calidad aunque no tenga reconocimiento de Google."""
    raw = await request.body()
    if not raw or len(raw) > 15 * 1024 * 1024:
        return {"text": ""}
    ctype = (request.headers.get("content-type") or "").lower()
    ext = (".webm" if "webm" in ctype else ".ogg" if "ogg" in ctype
           else ".m4a" if ("mp4" in ctype or "m4a" in ctype) else ".bin")
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=ext, prefix="wbk_stt_")
    try:
        os.write(fd, raw)
        os.close(fd)
        text = await stt.transcribe_path(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"text": text}


@app.get("/api/tts_audio/{name}")
async def api_tts_audio(name: str):
    """Sirve el audio TTS para que el HUD lo reproduzca DENTRO de la app."""
    from backend.core.infraestructura.tts import TTS_DIR
    f = TTS_DIR / name
    if not f.exists() or "/" in name or "\\" in name:
        return {"error": "not found"}
    mime = "audio/wav" if name.lower().endswith(".wav") else "audio/mpeg"
    return FileResponse(f, media_type=mime)


@app.post("/api/secrets")
async def api_secrets(payload: dict):
    """Guarda API keys desde ⚙ (config/secrets.json). Nunca se devuelven en claro."""
    saved = []
    for k, v in payload.items():
        if k in settings.SECRET_KEYS and isinstance(v, str):
            settings.set_secret(k, v)
            saved.append(k)
    await bus.emit("log", {"level": "ok",
                           "msg": f"Credenciales guardadas: {', '.join(saved) or 'ninguna'}"})
    return {k: bool(settings.secret(k)) for k in settings.SECRET_KEYS}


@app.get("/api/today")
async def api_today():
    """Panel HOY del HUD (v20): agenda del día en JSON estructurado."""
    from backend.core.dominio import briefing
    return await briefing.today_payload()


@app.get("/api/board")
async def api_board():
    from backend.core.dominio import board
    return board.board()


@app.get("/api/board/kpis")
async def api_board_kpis():
    """KPIs de las tareas abiertas: por tipo, urgencia, origen y vencimientos."""
    from backend.core.dominio import board
    return board.kpis()


@app.get("/api/hardware")
async def api_hardware():
    """Inventario completo del equipo: CPU, GPU, RAM, disco, placa, audio, red.
    Respeta el permiso de hardware elegido en la instalación / ⚙."""
    from backend.core.comun import permissions
    if not permissions.hardware_allowed():
        return {"denied": True, "error": permissions.HW_DENIED}
    from backend.core.infraestructura.hardware import hardware_report
    return await asyncio.to_thread(hardware_report)


@app.get("/api/calendar")
async def api_calendar(desde: str = "", hasta: str = ""):
    """Agenda unificada: eventos REALES de Google Calendar (si está conectado)
    + tareas del tablero con fecha. Tolerante: sin Google devuelve solo tareas.

    `desde`/`hasta` (AAAA-MM-DD) acotan el rango. Los pide la vista de agenda
    para traerse el MES entero: sin ellos solo llegaban los 10 próximos eventos,
    y con eso no se puede pintar un calendario."""
    from backend.core.dominio import board
    tasks = [t for col in board.board().values() for t in col if t.get("due")]
    google_events, google_status = [], "no conectado"
    try:
        import importlib.util
        from backend.core.comun.config import SKILLS_DIR
        spec = importlib.util.spec_from_file_location(
            "gws", SKILLS_DIR / "google_workspace" / "skill.py")
        gws = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gws)
        has_token = gws.TOKEN_FILE.exists()
        has_creds = gws.CREDS_FILE.exists() or (settings.secret("google_client_id")
                                                and settings.secret("google_client_secret"))
        if not has_creds:
            google_status = "no conectado"
        elif not has_token:
            # Hay credenciales pero aún no se ha autorizado (haría falta abrir el navegador)
            google_status = "sin autorizar"
        else:
            tmin = f"{desde}T00:00:00Z" if desde else None
            tmax = f"{hasta}T23:59:59Z" if hasta else None
            tope = 250 if desde else 10        # un mes entero cabe de sobra en 250
            google_events = await asyncio.wait_for(
                asyncio.to_thread(gws._fetch_events, tope, tmin, tmax), timeout=20)
            google_status = "ok"
    except Exception:
        google_status = "sin autorizar"
    return {"google": google_events, "google_status": google_status, "tasks": tasks}


@app.get("/api/spotify/callback")
async def api_spotify_callback(code: str = "", state: str = "", error: str = ""):
    """Callback OAuth de Spotify (autorización de una sola vez).

    SEC-15 (auditoría 30/07/2026, roadmap P3-5). Antes canjeaba el `code` sin
    mirar `state`, así que cualquiera podía pegar en el navegador un callback con
    SU código y dejar vinculada a nexus la cuenta de Spotify del atacante
    (login CSRF). Ahora se exige el `state` que generó `spotify.auth_url()`:
    comparación en tiempo constante y gastado ANTES del intercambio, así que un
    callback repetido no canjea nada. Si no cuadra, la página lo dice en
    cristiano y no se toca ni un token."""
    from backend.core.infraestructura import spotify
    from fastapi.responses import HTMLResponse
    page = ("<html><body style='background:#020a06;color:#7fe9f7;"
            "font-family:monospace;text-align:center;padding-top:120px'>"
            "<h1>{msg}</h1><p>{sub}</p></body></html>")
    if error or not code:
        return HTMLResponse(page.format(
            msg="✕ Autorización cancelada",
            sub="Vuelve a nexus y prueba otra vez cuando quieras."))
    if not spotify.consumir_estado(state):
        await bus.emit("log", {"level": "warn",
                               "msg": "Spotify: callback rechazado (state inválido o caducado)"})
        return HTMLResponse(page.format(
            msg="✕ No he podido validar esta autorización",
            sub="Ese enlace no es el que abrí yo, o ya ha caducado. Vuelve a nexus y "
                "pídeme la canción otra vez: te abriré uno nuevo."))
    ok = await spotify.exchange_code(code)
    if ok:
        await bus.emit("log", {"level": "ok",
                               "msg": "Spotify conectado — autoplay real activado ✓"})
        return HTMLResponse(page.format(
            msg="✓ Spotify conectado",
            sub="Ya puedes cerrar esta pestaña. Di «pon una canción en spotify»."))
    return HTMLResponse(page.format(
        msg="✕ No he podido canjear el código",
        sub="Revisa el Client ID/Secret en ⚙ y que el Redirect URI sea "
            "http://127.0.0.1:8177/api/spotify/callback"))


@app.get("/api/spotify/status")
async def api_spotify_status():
    from backend.core.infraestructura import spotify
    return {"configured": spotify.is_configured(),
            "authorized": spotify.is_authorized()}


@app.post("/api/board/move")
async def api_board_move(payload: dict):
    from backend.core.dominio import board
    t = board.move_task(payload.get("id", ""), payload.get("state", ""))
    if t:
        await bus.emit("log", {"level": "ok",
                               "msg": f"Tablero: «{t['title']}» → {t['state']}"})
    return t or {"error": "not found"}


@app.post("/api/board/delete")
async def api_board_delete(payload: dict):
    """Borra una tarea por id (botón 🗑 del HUD) o por título (voz).
    v23: el borrado es LÓGICO — la tarea va a la papelera y se puede restaurar."""
    from backend.core.dominio import board
    t = board.delete_task(payload.get("id", "") or payload.get("query", ""),
                          reason=payload.get("reason", "botón 🗑 del HUD"),
                          by=payload.get("by", "operador"))
    if t:
        n = t.get("count", 1)
        await bus.emit("log", {"level": "ok",
                               "msg": f"Tablero: «{t['title']}» a la papelera" +
                                      (f" (+{n-1} duplicada(s))" if n > 1 else "")})
    return t or {"error": "not found"}


@app.get("/api/board/trash")
async def api_board_trash(limit: int = 50):
    """Papelera de tareas (v23 TAREA 3): lo último borrado primero."""
    from backend.core.dominio import board
    return {"items": board.trash(limit=limit), "last_batch": board.last_batch()}


@app.post("/api/board/restore")
async def api_board_restore(payload: dict):
    """Restaura tareas de la papelera a su columna anterior. Sin argumentos,
    devuelve el ÚLTIMO lote borrado entero."""
    from backend.core.dominio import board
    restored = board.restore(query=payload.get("query", "") or payload.get("id", ""),
                             batch=payload.get("batch", ""))
    if restored:
        await bus.emit("log", {"level": "ok",
                               "msg": f"Tablero: {len(restored)} tarea(s) restaurada(s)"})
    return {"restored": restored, "count": len(restored)}


@app.post("/api/board/edit")
async def api_board_edit(payload: dict):
    """Edita una tarea (botón ✎ del HUD): título, fecha, prioridad o estado."""
    from backend.core.dominio import board
    t = board.edit_task(payload.get("id", ""), title=payload.get("title"),
                        due=payload.get("due"), priority=payload.get("priority"),
                        state=payload.get("state"),
                        task_type=payload.get("type"), urgency=payload.get("urgency"))
    if t:
        await bus.emit("log", {"level": "ok", "msg": f"Tablero: editada «{t['title']}»"})
    return t or {"error": "not found"}


def _audita_casa(canal: str, accion: str, *, request: str = "", result: str = "",
                 ok: bool | None = None, confirmed: bool | None = None,
                 targets: list | None = None) -> None:
    """Deja en `data/logs/audit.jsonl` el botón de casa que se ha pulsado (T8d).

    POR QUÉ EXISTE: `/api/home/control` y `/api/home/scan` llaman a la skill de
    domótica directamente, sin pasar por `brain._autorizar_efecto` ni por la
    matriz canal × efecto. Y se quedan así A PROPÓSITO (decisión del dueño,
    `odd/tasks/security-audit-remediation.md` T8d): un botón de casa no es texto
    libre que cae en el enrutador de regexes que ARQ-03 vigila — pincharlo ES la
    acción explícita del operador, así que no hay nada que preguntar dos veces.
    Lo que sí hace falta es que quede RASTRO: quién, qué dispositivo, por qué
    canal y con qué resultado. Sin esta línea, un móvil vinculado podía encender
    o apagar la tele sin que el registro de auditoría supiera nada.

    El canal es el de la CONEXIÓN (`_canal_efectivo`), igual que en el cerebro:
    `pc` desde este equipo, `mobile` desde el teléfono o el túnel.
    """
    from backend.core.comun import audit
    try:
        audit.log(action=accion, actor="operador", destructive=False,
                  confirmed=confirmed, channel=canal, request=request,
                  result=result, targets=targets or [],
                  extra={"ok": ok})
    except Exception:                                      # noqa: BLE001
        pass        # la auditoría no puede tumbar la orden que ya se ha dado


@app.post("/api/home/scan")
async def api_home_scan(request: Request):
    """Rastrea la red — buscador visual de dispositivos (HUD/movil)."""
    from backend.core.aplicacion.skills_loader import get_skills
    canal = _canal_efectivo(request)
    sk = get_skills().get("domotica")
    if not sk or not getattr(sk, "module", None):
        return {"devices": [], "error": "domotica no disponible"}
    try:
        salida = await sk.module.scan_api({"settings": settings, "bus": bus, "graph": graph})
    except Exception as exc:  # noqa: BLE001
        # SEC-16: el cliente recibe un mensaje y el TIPO se queda en el log.
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error",
                               "msg": f"Escaneo de red: {tecnico}: {exc}"})
        _audita_casa(canal, "domotica_escanear", request="escanear la red",
                     result=publico, ok=False)
        return {"devices": [], "error": publico}
    cuantos = len(salida.get("devices") or []) if isinstance(salida, dict) else 0
    _audita_casa(canal, "domotica_escanear", request="escanear la red", ok=True,
                 result=f"{cuantos} dispositivo(s)")
    return salida


@app.post("/api/home/control")
async def api_home_control(payload: dict, request: Request):
    """Accion al pinchar/conectar un dispositivo del buscador (TV / Home Assistant)."""
    from backend.core.aplicacion.skills_loader import get_skills
    canal = _canal_efectivo(request)
    sk = get_skills().get("domotica")
    if not sk or not getattr(sk, "module", None):
        return {"ok": False, "reply": "La domotica no esta disponible ahora mismo."}
    # Lo que identifica la acción en el registro: sin el token ni nada más.
    nombre = payload.get("name") or payload.get("entity_id") or payload.get("ip") or ""
    etiqueta = f"{payload.get('kind', '')}:{payload.get('action', '')} {nombre}".strip()
    objetivo = str(payload.get("entity_id") or payload.get("ip") or "")[:200]
    try:
        salida = await sk.module.control_api(
            {"settings": settings, "bus": bus, "graph": graph}, payload)
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(
            exc, mensaje="No he podido enviar la orden. No se ha realizado ningún cambio.")
        await bus.emit("log", {"level": "error", "msg": f"Domótica, orden: {tecnico}: {exc}"})
        _audita_casa(canal, "domotica_control", request=etiqueta, result=publico,
                     ok=False, confirmed=True, targets=[objetivo] if objetivo else [])
        return {"ok": False, "reply": publico}
    bien = bool(salida.get("ok")) if isinstance(salida, dict) else False
    respuesta = str(salida.get("reply", "")) if isinstance(salida, dict) else ""
    _audita_casa(canal, "domotica_control", request=etiqueta, result=respuesta,
                 ok=bien, confirmed=True, targets=[objetivo] if objetivo else [])
    return salida


@app.get("/api/home/ha_status")
async def api_home_ha_status():
    """Estado de Home Assistant para el panel de Dispositivos."""
    import shutil
    import httpx
    from backend.core.aplicacion.skills_loader import get_skills
    url = (settings.get("homeassistant_url", "") or "").rstrip("/")
    has_token = bool(settings.secret("homeassistant_token"))
    docker = shutil.which("docker") is not None
    running, entities = False, 0
    if url:
        try:
            async with httpx.AsyncClient(timeout=1.5) as cl:
                r = await cl.get(url + "/")
                running = r.status_code < 500
        except Exception:
            running = False
    if running and has_token:
        try:
            sk = get_skills().get("domotica")
            if sk and getattr(sk, "module", None):
                entities = len(await sk.module._ha_states({"settings": settings, "bus": bus}))
        except Exception:
            entities = 0
    return {"running": running, "has_token": has_token, "entities": entities,
            "url": url or "http://localhost:8123", "docker": docker}


@app.post("/api/home/ha_test")
async def api_home_ha_test(payload: dict):
    """Prueba una URL + token de Home Assistant SIN guardarlos aún, y devuelve un
    diagnóstico CLARO para el asistente: ¿se alcanza HA? ¿el token vale? ¿cuántas
    entidades controlables hay? Así el usuario sabe EXACTAMENTE qué falta."""
    import httpx
    url = (str(payload.get("url", "")).strip() or "http://localhost:8123").rstrip("/")
    token = str(payload.get("token", "")).strip()
    out = {"url": url, "reachable": False, "token_valid": False, "entities": 0,
           "controllable": 0, "error": ""}
    # 1) ¿se alcanza HA?
    try:
        async with httpx.AsyncClient(timeout=4) as cl:
            r = await cl.get(url + "/", follow_redirects=True)
            out["reachable"] = r.status_code < 500
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"no llego a {url} ({type(exc).__name__}). ¿Está encendido y la dirección es correcta?"
        return out
    if not out["reachable"]:
        out["error"] = f"{url} responde pero no como Home Assistant. Revisa la dirección/puerto (por defecto 8123)."
        return out
    # 2) ¿el token vale? (probamos /api/states con él)
    if not token:
        out["error"] = "falta el token de acceso de larga duración."
        return out
    try:
        async with httpx.AsyncClient(timeout=6) as cl:
            r = await cl.get(url + "/api/states", headers={"Authorization": f"Bearer {token}"})
        if r.status_code in (401, 403):
            out["error"] = "el token no es válido o ha caducado. Crea uno nuevo en tu perfil de HA (pestaña Seguridad)."
            return out
        r.raise_for_status()
        states = r.json()
        out["token_valid"] = True
        out["entities"] = len(states)
        ctrl_domains = ("light", "switch", "fan", "cover", "climate", "media_player",
                        "input_boolean", "scene", "script")
        out["controllable"] = sum(1 for s in states
                                  if str(s.get("entity_id", "")).split(".")[0] in ctrl_domains)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"HA respondió con un error al usar el token ({type(exc).__name__})."
    return out


@app.post("/api/home/install_ha")
async def api_home_install_ha():
    """Levanta Home Assistant en Docker (mando universal de domotica)."""
    import shutil
    if not shutil.which("docker"):
        return {"ok": False, "error": "No encuentro Docker. Abre Docker Desktop e intentalo otra vez."}
    from backend.core.comun.config import assistant_slug
    slug = assistant_slug()
    ha_vol = f"{slug}_home_assistant_config"
    run_cmd = ["docker", "run", "-d", "--name", "home_assistant", "--restart", "unless-stopped",
               "-p", "8123:8123", "-v", f"{ha_vol}:/config",
               "ghcr.io/home-assistant/home-assistant:stable"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *run_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=240)
        text = (out or b"").decode("utf-8", "replace")
        if proc.returncode == 0:
            return {"ok": True, "url": "http://localhost:8123", "out": text[-300:]}
        low = text.lower()
        if "already in use" in low or "conflict" in low or "is already" in low:
            p2 = await asyncio.create_subprocess_exec("docker", "start", "home_assistant",
                                                      stdout=asyncio.subprocess.DEVNULL,
                                                      stderr=asyncio.subprocess.DEVNULL)
            await p2.communicate()
            return {"ok": True, "url": "http://localhost:8123", "out": "Home Assistant ya existia; lo he arrancado."}
        return {"ok": False, "error": text[-300:] or "docker run fallo"}
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error", "msg": f"Home Assistant: {tecnico}: {exc}"})
        return {"ok": False, "error": publico}


@app.get("/api/hermes/status")
async def api_hermes_status():
    """Radiografia de la conexion con Hermes (exe, .env, puerto, salud, encargos)."""
    from backend.core.aplicacion.skills_loader import get_skills
    sk = get_skills().get("hermes")
    if not sk or not getattr(sk, "module", None):
        return {"error": "skill hermes no disponible"}
    try:
        return await sk.module.diagnose({"settings": settings, "bus": bus})
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error",
                               "msg": f"Hermes, diagnóstico: {tecnico}: {exc}"})
        return {"error": publico}


@app.post("/api/hermes/start")
async def api_hermes_start():
    """Arranca (y auto-provisiona) el gateway de Hermes desde el HUD."""
    from backend.core.aplicacion.skills_loader import get_skills
    sk = get_skills().get("hermes")
    if not sk or not getattr(sk, "module", None):
        return {"ok": False, "error": "skill hermes no disponible"}
    try:
        ok = await sk.module.ensure_up({"settings": settings, "bus": bus})
        diag = await sk.module.diagnose({"settings": settings, "bus": bus})
        return {"ok": bool(ok), "diag": diag}
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error", "msg": f"Hermes, arranque: {tecnico}: {exc}"})
        return {"ok": False, "error": publico}


@app.post("/api/hermes/configure")
async def api_hermes_configure(payload: dict):
    """Configura el CEREBRO de Hermes desde Núcleo IA: proveedor + modelo + API key.
    Escribe la clave en ~/.hermes/.env y el modelo en config.yaml, y REINICIA su
    gateway para que lo cargue. Así el modelo interno de Hermes deja de dar 401."""
    from backend.core.aplicacion.skills_loader import get_skills
    sk = get_skills().get("hermes")
    if not sk or not getattr(sk, "module", None):
        return {"ok": False, "error": "skill hermes no disponible"}
    provider = str(payload.get("provider", "")).strip().lower()
    model = str(payload.get("model", "")).strip()
    api_key = str(payload.get("api_key", "")).strip()
    # T42: la dirección base del endpoint compatible OpenAI que escribe el
    # operador (vacía para los presets). `configure_brain` la valida con la guarda
    # de destinos ANTES de escribir nada, así que aquí solo se transporta.
    base_url = str(payload.get("base_url", "")).strip()
    try:
        res = await asyncio.to_thread(sk.module.configure_brain,
                                      {"settings": settings, "bus": bus}, provider, model,
                                      api_key, base_url)
        if res.get("ok"):
            await bus.emit("log", {"level": "ok",
                                   "msg": f"🪽 Cerebro de Hermes: {provider} · {model} configurado"})
            # reiniciar el gateway con el modelo nuevo (no bloquea la respuesta)
            asyncio.create_task(sk.module.ensure_up({"settings": settings, "bus": bus}, force=True))
        return res
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error",
                               "msg": f"Hermes, configuración: {tecnico}: {exc}"})
        return {"ok": False, "error": publico}


@app.post("/api/home/rename")
async def api_home_rename(payload: dict):
    """Renombra un dispositivo desde la UI (nombre EDITABLE para que la voz lo
    entienda). Persiste en known_devices (ip/mac) y en my_devices (todos)."""
    name = str(payload.get("name", "")).strip()[:60]
    ip = str(payload.get("ip", "")).strip()
    mac = str(payload.get("mac", "")).strip().upper()
    eid = str(payload.get("entity_id", "")).strip()
    if not name or not (ip or mac or eid):
        return {"ok": False, "error": "faltan nombre o identificador"}
    if ip or mac:
        known = list(settings.get("known_devices", []) or [])
        hit = False
        for kd in known:
            if (ip and kd.get("ip") == ip) or (mac and (kd.get("mac") or "").upper() == mac):
                kd["name"] = name
                hit = True
        if not hit:
            known.append({"name": name, "ip": ip, "mac": mac, "brand": payload.get("brand", "")})
        settings.set("known_devices", known)
    mine = list(settings.get("my_devices", []) or [])
    key = eid or mac or ip
    for md in mine:
        if md.get("key") == key:
            md["name"] = name
    settings.set("my_devices", mine)
    await bus.emit("log", {"level": "ok", "msg": f"\U0001F3F7\uFE0F Dispositivo renombrado: \u00AB{name}\u00BB"})
    return {"ok": True, "name": name}


@app.post("/api/n8n")
async def api_n8n(request: Request, payload: dict):
    """Entrada desde flujos n8n: {"text": "...", "speak": false} → respuesta de nexus.

    Autenticación (SEC-01): `n8n` no es el operador, así que no vale «viene de
    casa». Se exige la cabecera `x-nexus-n8n-secret` SIEMPRE, también desde
    127.0.0.1, y se compara en tiempo constante (`hmac.compare_digest`): un `!=`
    deja adivinar el secreto carácter a carácter midiendo lo que tarda. Sin
    secreto o con el secreto mal no se llama al cerebro, así que no hay ningún
    efecto que un flujo sin autenticar pueda provocar."""
    import hmac
    recibido = request.headers.get(_N8N_CABECERA, "")
    # Se comparan BYTES: `compare_digest` con `str` lanza TypeError si la cabecera
    # trae algo no ASCII, y eso devolvería un 500 en vez del 401 que toca.
    if not recibido or not hmac.compare_digest(recibido.encode("utf-8", "replace"),
                                               secreto_n8n().encode("utf-8", "replace")):
        return JSONResponse({"error": _ERROR_N8N_SIN_SECRETO}, status_code=401)
    result = await brain.process(payload.get("text", ""), source="n8n")
    if payload.get("speak"):
        asyncio.create_task(tts.speak(result["reply"]))
    return result


@app.get("/api/n8n/secret")
async def api_n8n_secret(request: Request):
    """Devuelve el secreto de `/api/n8n`, SOLO a este equipo.

    Sirve para configurar el flujo (o la credencial de cabecera de n8n) sin ir
    a abrir `config/secrets.json` a mano. Una petición remota —aunque venga con
    el token del QR ya validado por el middleware— NO lo recibe: el móvil y el
    túnel no tienen por qué conocer el secreto que da órdenes a los flujos."""
    if not _es_este_equipo(request):
        return JSONResponse({"error": "el secreto de n8n solo se entrega a este equipo"},
                            status_code=403)
    return {"secret": secreto_n8n(), "header": _N8N_CABECERA}


@app.get("/api/telegram/link")
async def api_telegram_link(request: Request):
    """Muestra el código de vinculación de Telegram, SOLO en este equipo.

    SEC-02 (roadmap P1-2): el primer chat que escribía al bot se quedaba el equipo
    para siempre. Ahora hay que mandarle este código desde el chat que quieras
    vincular, y el código solo se puede leer desde el propio PC: ni el móvil ni el
    túnel lo reciben —quien lo recibiera podría vincular SU chat y dar órdenes—.
    Cada petición genera uno nuevo y anula el anterior, y caduca según
    `telegram.ttl_vinculacion_segundos` de config/umbrales.json. El token del bot
    no sale nunca por aquí."""
    if not _es_este_equipo(request):
        return JSONResponse({"error": "el código de vinculación de Telegram solo se "
                                       "muestra en este equipo"},
                            status_code=403)
    return {"codigo": pending_link_code(),
            "ttl_segundos": ttl_vinculacion_segundos()}


@app.get("/api/contentos")
async def api_contentos():
    """Panel Content OS: KPIs, calendario, ideas, aprendizajes, métricas y gráficos."""
    return await contentos.dashboard()


@app.post("/api/contentos/generate")
async def api_contentos_generate(payload: dict):
    """Genera idea o guion con IA. body: {kind: idea|script, topic: str}."""
    kind = payload.get("kind", "idea")
    text = await contentos.generate(kind, payload.get("topic", ""))
    return {"ok": True, "kind": kind, "text": text}


@app.post("/api/contentos/add")
async def api_contentos_add(payload: dict):
    """Añade idea/inspiración/aprendizaje/publicación. body: {kind, value}."""
    ok = contentos.add_item(payload.get("kind", ""), payload.get("value"))
    return {"ok": ok}


@app.get("/api/instagram/analisis")
async def api_instagram_analisis():
    """El ultimo analisis de reels, tal cual lo pinta la pestana Reels.

    Se sirve de disco a proposito: mirar el panel NO puede gastar cuota de la
    Graph API ni depender de que Instagram este disponible. Y si nunca se ha
    analizado nada, se dice por que, en vez de devolver un panel vacio."""
    from backend.core.comun.config import DATA_DIR
    f = Path(DATA_DIR) / "instagram" / "ultimo_analisis.json"
    if not f.exists():
        hay_token = bool(settings.secret("ig_access_token"))
        hay_id = bool(str(settings.get("ig_business_account_id", "") or "").strip())
        if not (hay_token and hay_id):
            falta = []
            if not hay_token:
                falta.append("el token de la Graph API")
            if not hay_id:
                falta.append("el ID de la cuenta Business")
            return {"hay": False, "motivo": "sin_credenciales",
                    "texto": "Falta " + " y ".join(falta)
                             + ". Se rellena en Configuracion -> APIS."}
        return {"hay": False, "motivo": "sin_analisis",
                "texto": "Todavia no has analizado ningun reel. Dile a nexus "
                         "\u00abanaliza mis ultimos 3 reels\u00bb."}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"hay": False, "motivo": "ilegible",
                "texto": "El ultimo analisis guardado no se puede leer. "
                         "Vuelve a lanzarlo."}
    return {"hay": True, "cuando": d.get("cuando", ""), "reels": d.get("reels", [])}


@app.get("/api/instagram/competencia")
async def api_instagram_competencia():
    """La ultima comparativa con cuentas ajenas, servida de disco.

    Igual que el analisis: mirar la pestana no puede gastar cuota de la API."""
    from backend.core.comun.config import DATA_DIR
    f = Path(DATA_DIR) / "instagram" / "competencia.json"
    if not f.exists():
        return {"hay": False, "motivo": "sin_competencia",
                "texto": "Todavia no has comparado ninguna cuenta. Dile a nexus "
                         "\u00abanaliza la cuenta @sucuenta\u00bb. Solo funciona con "
                         "cuentas profesionales publicas: de una cuenta personal la "
                         "API no deja ver nada."}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"hay": False, "motivo": "ilegible",
                "texto": "La ultima comparativa guardada no se puede leer. "
                         "Vuelve a lanzarla."}
    panel = d.get("panel") or {}
    return {"hay": bool(panel.get("hay")), "cuando": d.get("cuando", ""),
            "panel": panel}


@app.get("/api/config")
async def api_config_get():
    # El MODO de permisos sale aquí para que el HUD pueda enseñarlo (⚙ → Permisos).
    # Cambiarlo ya no basta con tener el token: ver _CLAVES_SOLO_LOCALES.
    return settings.as_dict()


# Claves que SOLO se cambian desde ESTE equipo (SEC-12 / roadmap P1-6).
#
# Antes, quien tuviera el token del QR —o colara una petición por el hueco de
# SEC-03— podía poner `perm_files: "todo"` y desactivar en silencio el único
# control de alcance que tiene nexus, o apuntar los webhooks a su propia máquina
# y quedarse con lo que nexus envía. La regla no es «quién eres» sino «dónde
# estás»: los permisos se tocan con las manos en el teclado, en la ventana de
# nexus (pywebview, loopback), nunca desde el móvil ni desde un flujo.
_CLAVES_SOLO_LOCALES = {
    # ---- el propio control de alcance ----
    "perm_files": "es el alcance de archivos que SEC-04 acota",
    "perm_folders": "son las carpetas que ese alcance permite",
    "perm_hardware": "mismo control (⚙ → Permisos), mismo riesgo",
    # ---- a dónde sale lo que nexus sabe ----
    "n8n_webhook_url": "apuntarlo a otro sitio se lleva lo que nexus envía",
    "n8n_base_url": "mismo destino de salida por API",
    "homeassistant_url": "URL de integración: recibe la orden con su token",
    "backup_destino_extra": "a dónde sale la copia de TODO data/ (conversaciones, "
                            "notas, tablero): apuntarlo a otra carpeta local es una "
                            "exfiltración, la misma clase de agujero que SEC-19",
    # ---- guardas de privacidad del cerebro ----
    "permitir_fallback_nube": "es el consentimiento para sacar el prompt a la nube (AI-01)",
    "llm_local": "decide si el cerebro es local o de nube",
    # T25/P3-6: no es el mismo consentimiento que `permitir_fallback_nube` (aquel
    # cubre un cambio de cerebro no pedido; este, entregar un ENCARGO a un
    # ejecutor cuya nube el dueño eligió). Apagarlo decide si lo que nexus delega
    # puede salir del equipo, así que se toca con las manos en el teclado.
    "permitir_delegacion_nube": ("decide si un encargo delegado puede salir a un "
                                 "cerebro de nube (T25)"),
    # T42: es la dirección base del cerebro de Hermes cuando no es un preset.
    # Decide a dónde viaja el encargo y, con ella, si la delegación cuenta como
    # local (loopback) o de nube (consentimiento + contador). Misma clase que
    # `n8n_webhook_url`: apuntarla a otro sitio cambia a dónde sale lo que nexus
    # delega, así que se toca con las manos en el teclado.
    "hermes_base_url": ("es el endpoint del cerebro del ejecutor: decide si lo que "
                        "nexus delega sale del equipo"),
    # ---- ejecución de software en el equipo ----
    "engram_autoinstall": "instala un binario en el equipo sin preguntar",
}
_ERROR_SOLO_LOCAL = ("no autorizado — los permisos y las direcciones de integración "
                     "solo se cambian desde este equipo, en ⚙ de la ventana de nexus. "
                     "Nada se ha cambiado. (Claves rechazadas: {claves})")


@app.post("/api/config")
async def api_config_set(request: Request, payload: dict):
    # SEC-12: si el cuerpo toca alguna clave que controla una guarda y la petición
    # NO viene de la ventana local, se rechaza ENTERA (403) y no se aplica nada:
    # aplicar «lo demás» dejaría al HUD remoto creyendo que su cambio entró.
    locales = sorted(k for k in payload if k in _CLAVES_SOLO_LOCALES)
    if locales and not _es_este_equipo(request):
        return JSONResponse(
            {"error": _ERROR_SOLO_LOCAL.format(claves=", ".join(locales))},
            status_code=403)
    # Los secretos NO entran por aquí: van a /api/secrets, que los guarda en
    # secrets.json. Antes esta lista («has_elevenlabs_key»…) no coincidía con
    # ningún nombre real, así que no protegía nada: un POST con una API key la
    # dejaba en settings.json y el siguiente GET la devolvía en claro.
    rechazados = [k for k in payload if k in settings.SECRET_KEYS or k.startswith("has_")]
    for k, v in payload.items():
        if k not in rechazados:
            settings.set(k, v)
    # si has cambiado el cerebro, invalida la caché del proveedor (efecto inmediato)
    if any(k in payload for k in ("llm_provider", "llm_local", "ollama_model")):
        from backend.core.infraestructura.llm import invalidate_provider
        invalidate_provider()
        # y el runtime deja de dar por bueno lo anterior: se volverá a PROBAR.
        try:
            from backend.core.infraestructura import llm_runtime as _rt
            _rt._STATUS = _rt.LLMRuntimeStatus()
        except Exception:
            pass
    aplicados = [k for k in payload if k not in rechazados]
    await bus.emit("log", {"level": "ok",
                           "msg": f"Configuración actualizada: {', '.join(aplicados)}"
                                  + (f" (ignorados por ser secretos: {', '.join(rechazados)})"
                                     if rechazados else "")})
    return settings.as_dict()


@app.get("/api/memoria/estado")
async def api_memoria_estado():
    # 002-memoria-y-conocimiento (A4.6): NUNCA llama al proveedor de
    # embeddings — solo lee la columna (catálogo) y lo ya medido en disco.
    # Sin esto, dejar el HUD abierto haría una llamada real por cada poll.
    from backend.core.dominio import memory
    return memory.estado_memoria()


@app.post("/api/memoria/vector/migrar")
async def api_memoria_vector_migrar(payload: dict):
    # A2.5: protegido por confirm.request(), igual que vaciar la papelera
    # (tasks_board/skill.py) — el «sí» llega por chat, resuelto en
    # brain.process() ANTES de cualquier router.
    from backend.core.dominio import memory
    from backend.core.comun import confirm
    canal = payload.get("channel") or "pc"
    dim = payload.get("dim")
    if dim is None:
        medida = memory.pg.detectar_dimension()
        dim = medida.get("medida")
        if dim is None:
            return {"ok": False, "error": (
                "no he podido medir la dimensión del modelo activo (¿Ollama "
                "encendido?); pásame «dim» a mano si ya la conoces.")}
    dim = int(dim)
    actual = memory.pg._dimension_columna()
    if actual == dim:
        return {"ok": False, "error": f"la columna ya está en vector({dim})"}

    def _migrar():
        r = memory.pg.migrar_vector(dim)
        if r.get("ok"):
            return (f"Columna migrada a vector({dim}). La columna anterior "
                    f"sigue intacta como «{r.get('columna_vieja')}» — no se "
                    f"ha perdido ni una fila.")
        return f"No he podido migrar: {r.get('error')}"

    pregunta = confirm.request(
        channel=canal, kind="memoria_migrar_vector",
        summary=(f"⚠️ Voy a migrar memories.embedding de vector({actual}) a "
                 f"vector({dim}). No se borra ninguna fila: la columna vieja "
                 f"queda renombrada como respaldo. ¿Lo confirmas? «sí» o «no»."),
        action=_migrar, request_text=str(payload),
        cancel_reply="Vale, dejo la columna como está.")
    return {"reply": pregunta}


@app.post("/api/memoria/reindexar/plan")
async def api_memoria_reindexar_plan(payload: dict | None = None):
    # A3.4: solo PRESUPUESTA — cero llamadas al proveedor todavía.
    from backend.core.dominio import memory
    proveedor = (payload or {}).get("proveedor")
    return memory.pg.plan_reindexado(proveedor)


@app.post("/api/memoria/reindexar")
async def api_memoria_reindexar(payload: dict):
    # A3.4: con proveedor local, reindexa directo. Con nube, exige
    # confirm.request() nombrando proveedor y nº de llamadas (diseño §3,
    # «cerrojo 2») ANTES de la primera fila — el «sí» llega por chat.
    from backend.core.dominio import memory
    from backend.core.comun import confirm
    plan_id = payload.get("plan_id", "")
    canal = payload.get("channel") or "pc"
    plan = memory.pg._planes_reindexado.get(plan_id)
    if not plan:
        return {"ok": False, "error": f"plan «{plan_id}» desconocido o caducado"}
    if plan["sale_del_equipo"]:

        def _reindexar():
            r = memory.pg.reindexar(plan_id, confirmar_nube=True)
            if r.get("ok"):
                return f"Reindexado: {r['procesadas']} fila(s), {r['fallidas']} fallida(s)."
            return f"No he podido reindexar: {r.get('error')}"

        pregunta = confirm.request(
            channel=canal, kind="memoria_reindexar_nube",
            summary=plan["aviso"] + " ¿Confirmas?", action=_reindexar,
            request_text=str(payload),
            cancel_reply="Vale, no reindexo con ese proveedor.")
        return {"reply": pregunta}
    return memory.pg.reindexar(plan_id, confirmar_nube=False)


@app.post("/api/memoria/vector/limpiar-respaldo")
async def api_memoria_vector_limpiar_respaldo(payload: dict | None = None):
    # B4.3: cierra la migración A2. Segunda acción EXPLÍCITA — nunca
    # encadenada a migrar_vector(). Irreversible (DROP COLUMN): confirm.request() propio.
    from backend.core.dominio import memory
    from backend.core.comun import confirm
    canal = (payload or {}).get("channel") or "pc"

    def _limpiar():
        r = memory.pg.limpiar_respaldo()
        if r.get("ok"):
            return f"Columna de respaldo «{r['columna_eliminada']}» eliminada."
        return f"No he podido soltar la columna de respaldo: {r.get('error')}"

    pregunta = confirm.request(
        channel=canal, kind="memoria_limpiar_respaldo",
        summary=("⚠️ Voy a ELIMINAR la columna de respaldo que dejó la "
                 "migración de vector (irreversible). ¿Lo confirmas? «sí» o «no»."),
        action=_limpiar, request_text=str(payload or {}),
        cancel_reply="Vale, dejo la columna de respaldo donde está.")
    return {"reply": pregunta}


@app.post("/api/memoria/purga/previsualizar")
async def api_memoria_purga_previsualizar(payload: dict | None = None):
    # B5.1: SIEMPRE lo primero — nada se mueve ni se toca aquí.
    # PRIV-03 / P2-8: el plan trae además `almacenes`, la lista de TODOS los
    # sitios donde el hecho está copiado (lo que se va a tocar, lo que no se
    # puede tocar y por qué, y las copias de seguridad que lo conservan con sus
    # fechas). Campo ADITIVO: quien no lo mire, no se entera y sigue igual.
    # `incluir_logs` es el alcance opt-in de los registros (por defecto NO).
    from backend.core.dominio import purga
    return purga.previsualizar(incluir_logs=bool((payload or {}).get("incluir_logs", False)))


@app.post("/api/memoria/purga/aplicar")
async def api_memoria_purga_aplicar(payload: dict):
    # B5.1: confirmación propia del protocolo de purga (plan_id + categorías
    # explícitas + acepto_personal) — NO usa confirm.request() de chat porque
    # ya exige una previsualización previa y una selección explícita.
    # PRIV-03: `incluir_logs` solo puede CONFIRMAR lo que la previsualización ya
    # enseñó; pedirlo cuando el plan no lo incluía se rechaza dentro de
    # `purga.aplicar()` (no se amplía en silencio lo prometido).
    from backend.core.dominio import purga
    plan_id = payload.get("plan_id", "")
    categorias = payload.get("categorias") or []
    acepto_personal = bool(payload.get("acepto_personal", False))
    incluir_logs = bool(payload.get("incluir_logs", False))
    return purga.aplicar(plan_id, categorias, acepto_personal=acepto_personal,
                         incluir_logs=incluir_logs)


@app.get("/api/memoria/purga/papelera")
async def api_memoria_purga_papelera(lote: str = ""):
    from backend.core.dominio import purga
    return {"items": purga.papelera(lote)}


@app.post("/api/memoria/purga/restaurar")
async def api_memoria_purga_restaurar(payload: dict):
    # B5.1: restaurar es una UPDATE reversible — no destructiva, no exige
    # confirm.request() de chat (misma lógica que board.restore()).
    from backend.core.dominio import purga
    lote = payload.get("lote", "")
    if not lote:
        return {"ok": False, "error": "falta «lote»"}
    return purga.restaurar(lote)


@app.post("/api/memoria/purga/exportar")
async def api_memoria_purga_exportar(payload: dict):
    # B5.1: no destructiva (copia), pero puede escribir fuera del sandbox si
    # se pide «destino» — protegido por permissions.path_allowed() dentro.
    from backend.core.dominio import purga
    lote = payload.get("lote", "")
    destino = payload.get("destino")
    if not lote:
        return {"ok": False, "error": "falta «lote»"}
    return purga.exportar(lote, destino)


@app.post("/api/memoria/purga/borrar-definitivo")
async def api_memoria_purga_borrar_definitivo(payload: dict):
    # B5.1: IRREVERSIBLE (unlink + DELETE FROM memories). El «sí» llega por
    # chat, igual que migrar_vector — nexus nunca lo dispara solo.
    from backend.core.dominio import purga
    from backend.core.comun import confirm
    canal = payload.get("channel") or "pc"
    lote = payload.get("lote", "")
    if not lote:
        return {"ok": False, "error": "falta «lote»"}

    def _borrar():
        r = purga.borrar_definitivo(lote)
        if r.get("ok"):
            return (f"Borrado definitivo del lote «{lote}»: {len(r['borrados'])} "
                    f"fichero(s), {r['filas']} fila(s). No hay vuelta atrás.")
        return f"No he podido borrar el lote: {r.get('error')}"

    pregunta = confirm.request(
        channel=canal, kind="memoria_purga_borrar_definitivo",
        summary=(f"⚠️ Voy a BORRAR PARA SIEMPRE el lote «{lote}» de la papelera "
                 f"(ficheros y filas). Es irreversible. ¿Lo confirmas? «sí» o «no»."),
        action=_borrar, request_text=str(payload),
        cancel_reply="Vale, el lote se queda en la papelera.")
    return {"reply": pregunta}


@app.post("/api/memoria/ingerir-carpeta")
async def api_memoria_ingerir_carpeta(payload: dict):
    # C4.1: aditivo y SOLO LECTURA sobre el origen (escribe espejos .md
    # aparte, en data/memory/documentos/). No destructivo -> sin
    # confirm.request(). permissions.path_allowed() dentro de
    # ingesta.ingerir_carpeta() corta cualquier intento de traversal (C4.4).
    from backend.core.dominio import ingesta
    from backend.core.comun import audit
    ruta = str(payload.get("ruta", "")).strip()
    resultado = ingesta.ingerir_carpeta(ruta)
    audit.log(action="memoria_ingerir_carpeta", destructive=False, confirmed=True,
               result=f"{resultado.get('dominio')}: {len(resultado.get('documentos', []))} archivo(s)",
               extra={"ruta": ruta, "ok": resultado.get("ok")})
    return resultado


@app.get("/")
async def index():
    if not settings.get("setup_done", False):
        return FileResponse(FRONTEND_DIR / "setup.html")   # asistente de 1ª ejecución
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/setup")
async def setup_page():
    """Asistente de instalación (accesible también después, para reconfigurar)."""
    return FileResponse(FRONTEND_DIR / "setup.html")


# ---------------------- API del asistente de instalación ----------------------
@app.get("/api/personalities")
async def api_personalities():
    from backend.core.infraestructura.llm import PERSONALITIES
    return {k: {"name": v["name"], "desc": v["desc"]} for k, v in PERSONALITIES.items()}


@app.get("/api/setup/state")
async def api_setup_state():
    import shutil
    docker = shutil.which("docker")
    version = ""
    if docker:
        try:
            import subprocess
            version = subprocess.run(["docker", "--version"], capture_output=True,
                                     text=True, timeout=6).stdout.strip()
        except Exception:
            docker = None
    from backend.core.infraestructura.llm import PERSONALITIES
    return {"setup_done": bool(settings.get("setup_done", False)),
            "docker": bool(docker), "docker_version": version,
            "config": settings.as_dict(),
            "personalities": {k: {"name": v["name"], "desc": v["desc"]}
                              for k, v in PERSONALITIES.items()}}


@app.post("/api/setup/save")
async def api_setup_save(payload: dict):
    """Guarda ajustes y secretos del asistente. body: {settings:{}, secrets:{}}."""
    for k, v in (payload.get("settings") or {}).items():
        settings.set(k, v)
    for k, v in (payload.get("secrets") or {}).items():
        if k in settings.SECRET_KEYS and isinstance(v, str) and v.strip():
            settings.set_secret(k, v)
    return {"ok": True}


@app.post("/api/setup/docker")
async def api_setup_docker():
    """Crea los contenedores de la BD (Postgres+pgvector) y n8n con Docker."""
    import shutil
    import subprocess
    if not shutil.which("docker"):
        return {"ok": False, "error": "Docker no está instalado",
                "download": "https://www.docker.com/products/docker-desktop/"}
    from backend.core.comun.config import ROOT, assistant_slug
    # WHITE-LABEL: los nombres de proyecto/contenedor/volumen/BD salen del NOMBRE del
    # sistema (slug). Por defecto «nexus» → nexus_*, nexus_core, etc.; para cualquier
    # otro nombre, nombres limpios «<slug>_…».
    slug = assistant_slug()
    proj = slug
    vol = f"{slug}_memoria_datos"
    pg = f"{slug}_memoria_postgres"
    # La contraseña NO se deriva del nombre del asistente. Antes era
    # antes se construia con el slug y un sufijo fijo, asi que salia IGUAL en
    # todas las instalaciones y encima quedaba publicada en el repositorio
    # (auditoria 30/07/2026). Ni el valor viejo se escribe aqui.
    # Ahora se genera al azar la primera vez y se reutiliza la del compose ya creado.
    import re as _re
    import secrets as _secrets
    user, db = f"{slug}_admin", f"{slug}_core"
    compose = ROOT / "config" / "docker-compose.yml"
    pwd = ""
    if compose.exists():
        m = _re.search(r"POSTGRES_PASSWORD:\s*(\S+)", compose.read_text(encoding="utf-8"))
        pwd = m.group(1) if m else ""
    if not pwd:
        pwd = _secrets.token_urlsafe(24)
    compose.parent.mkdir(parents=True, exist_ok=True)
    if not compose.exists():
        compose.write_text(
            f"name: {proj}\n"
            "services:\n"
            f"  {pg}:\n"
            "    image: pgvector/pgvector:pg16\n"
            f"    container_name: {pg}\n"
            "    restart: unless-stopped\n"
            "    environment:\n"
            f"      POSTGRES_USER: {user}\n"
            f"      POSTGRES_PASSWORD: {pwd}\n"
            f"      POSTGRES_DB: {db}\n"
            # Solo accesible desde ESTE equipo: antes se publicaba en todas las
            # interfaces y cualquiera de la red podía conectarse a la memoria.
            "    ports: ['127.0.0.1:5433:5432']\n"
            f"    volumes: ['{vol}:/var/lib/postgresql/data']\n"
            f"volumes:\n  {vol}:\n", encoding="utf-8")
    try:
        out = await asyncio.to_thread(lambda: subprocess.run(
            ["docker", "compose", "-f", str(compose), "up", "-d"],
            capture_output=True, text=True, timeout=300))
        ok = out.returncode == 0
        if ok:
            settings.set("db_url", f"postgresql://{user}:{pwd}@localhost:5433/{db}")
        return {"ok": ok, "out": (out.stdout + out.stderr)[-800:]}
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error",
                               "msg": f"Docker (base de datos): {tecnico}: {exc}"})
        return {"ok": False, "error": publico}


@app.post("/api/setup/scan_models")
async def api_setup_scan_models(payload: dict):
    """Añade una carpeta de modelos locales y devuelve lo que encuentra."""
    folder = str(payload.get("path", "")).strip()
    if folder:
        paths = list(settings.get("model_scan_paths", []) or [])
        if folder not in paths:
            paths.append(folder)
            settings.set("model_scan_paths", paths)
    from backend.core.infraestructura.llm import scan_local_models
    return await scan_local_models()


@app.post("/api/setup/finish")
async def api_setup_finish():
    settings.set("setup_done", True)
    return {"ok": True}


# ---------------------- Vinculación del móvil (QR + túnel) ----------------------
@app.get("/api/llm_check")
async def api_llm_check():
    """DIAGNÓSTICO LLM: prueba CADA proveedor con un ping mínimo y devuelve su estado
    real (clave, modelo y el error EXACTO). Abrir en el navegador:
    http://localhost:8177/api/llm_check — y todo queda también en data/nexus.log."""
    from backend.core.infraestructura import llm as _llm
    out = {"_activo": settings.get("llm_provider", "?")}
    msgs = [{"role": "user", "content": "Responde solo: OK"}]
    for name, prov in _llm.PROVIDERS.items():
        if name == "mock":
            continue
        info = {"disponible": False, "modelo": "", "error": ""}
        try:
            info["modelo"] = prov._model() if hasattr(prov, "_model") else ""
        except Exception:
            pass
        try:
            if not await prov.available():
                info["error"] = "no disponible (falta API key o el servicio está apagado)"
            else:
                r = await asyncio.wait_for(prov.chat(msgs), timeout=25)
                info["disponible"] = True
                info["respuesta"] = str(r)[:80]
        except Exception as exc:                               # noqa: BLE001
            try:
                info["error"] = _llm._explain_error(prov, exc)
            except Exception:
                # SEC-16 NO toca este `{type}: {exc}`: `/api/llm_check` es el
                # diagnóstico de ESTE equipo (se abre en el navegador de casa),
                # igual que `/api/llm/status_full`. Los dos son un hallazgo
                # aparte, no el «errores devueltos al cliente» de la API.
                info["error"] = f"{type(exc).__name__}: {exc}"
        out[name] = info
        await bus.emit("log", {"level": "ok" if info["disponible"] else "warn",
                               "msg": f"LLM {name} ({info['modelo'] or 'sin modelo'}): "
                                      + ("✔ responde" if info["disponible"]
                                         else f"✖ {info['error']}")})
    return out


@app.post("/api/link/start")
async def api_link_start():
    from backend.core.infraestructura import remote
    return await remote.start_tunnel()


@app.get("/api/link/status")
async def api_link_status():
    """POR QUÉ VA EN OTRO HILO (01/08/2026). `remote.status()` es SÍNCRONA y por
    dentro sondea direcciones de red: resolver el nombre mDNS «PC_ADRI.local»
    tarda 4,25 s medidos en este equipo, y el `timeout` del socket NO cubre esa
    resolución. Llamándola directamente, el bucle de asyncio se quedaba parado
    esos 4 s y NINGUNA petición respondía: el HUD entero se congelaba cada 45 s
    (que es cada cuánto refresca los dispositivos). Con `to_thread` el bloqueo se
    queda en un hilo del pool y el bucle sigue atendiendo."""
    from backend.core.infraestructura import remote
    return await asyncio.to_thread(remote.status)


@app.get("/api/link/qr")
async def api_link_qr():
    from backend.core.infraestructura import remote
    from fastapi.responses import Response
    try:
        # status() bloquea (DNS/socket): fuera del bucle, como en /api/link/status.
        est = await asyncio.to_thread(remote.status)
        png = await asyncio.to_thread(remote.qr_png, est["link"])
        return Response(content=png, media_type="image/png")
    except Exception as exc:  # noqa: BLE001
        publico, tecnico = publicvoice.fallo(exc)
        await bus.emit("log", {"level": "error", "msg": f"QR del móvil: {tecnico}: {exc}"})
        return {"error": publico}


@app.get("/api/link/tailscale")
async def api_link_tailscale():
    """Estado de Tailscale: la vía ESTABLE para llegar al PC desde fuera.

    El túnel de Cloudflare cambia de dirección en cada arranque y obliga a
    revincular el móvil; una IP de Tailscale (100.x.y.z) no cambia nunca."""
    from backend.core.infraestructura import remote
    # `tailscale status --json` es un SUBPROCESO (hasta 10 s de timeout): igual
    # que status(), fuera del bucle o se congela el HUD entero.
    ts = await asyncio.to_thread(remote.tailscale_status)
    url = await asyncio.to_thread(remote.tailscale_url)
    return {**ts, "descarga": remote.TAILSCALE_WEB,
            "url": url,
            "siguiente_paso": (
                "Listo: el QR ya usa la dirección fija." if ts.get("activo")
                else "Instala Tailscale en este PC y en el móvil con la MISMA cuenta, "
                     f"inicia sesión en los dos y vuelve a abrir el QR. {remote.TAILSCALE_WEB}")}


@app.post("/api/link/pair")
async def api_link_pair(payload: dict):
    """El móvil canjea el CÓDIGO del QR por un token PROPIO (roadmap P3-2 / T21).

    Por qué existe: el QR lleva un código de un solo uso, no una credencial
    permanente. El móvil lo cambia UNA vez por un token suyo, que a partir de ahí
    usa como siempre (`?token=`, `x-nexus-token`, cookie `nexus_token` y el
    WebSocket). Así revocar un teléfono perdido deja de obligar a re-vincular
    todos los demás.

    Esta ruta está exenta del token en `remote_auth` (`_RUTA_CANJE`) porque quien
    llega todavía no tiene ninguno: la autoridad es el código, que se compara en
    tiempo constante y se consume aquí (`remote.pair_device`).
    """
    from backend.core.infraestructura import remote
    # En el bucle, no en un hilo: esto es un canje en memoria + una escritura
    # corta, y `register_device` toca el registro de dispositivos que el resto de
    # handlers tocan desde el bucle. Moverlo a un hilo sería mezclar quién escribe
    # ese registro por ahorrar milisegundos.
    ficha = remote.pair_device(str(payload.get("codigo") or ""),
                               str(payload.get("id") or ""),
                               str(payload.get("name") or ""))
    if not ficha:
        # Mismo mensaje para «no existe», «caducado» y «ya usado»: decir cuál de
        # los tres es darle una pista a quien va probando.
        return JSONResponse({"error": _ERROR_CANJE}, status_code=403)
    await bus.emit("log", {"level": "ok", "msg": f"📱 Vinculado: {ficha['name']} "
                                                      "(token propio de ese móvil)"})
    return {"ok": True, "id": ficha["id"], "name": ficha["name"],
            "token": ficha["token"]}


@app.post("/api/link/revoke")
async def api_link_revoke(payload: dict):
    """Mata el token de UN dispositivo (roadmap P3-2 / T21).

    Si ese móvil usa un token PROPIO, mueren solo el suyo. Si es un «dispositivo
    antiguo» (el token COMPARTIDO de antes), no hay credencial propia que apagar:
    se cierra la compartida y el HUD lo dice en su `aviso` (decisión (a)).
    """
    from backend.core.infraestructura import remote
    did = str(payload.get("id") or "")
    r = remote.revoke_device(did)
    if not r.get("ok"):
        return JSONResponse({"error": str(r.get("error") or "no he podido revocar ese móvil")},
                            status_code=404)
    await bus.emit("unpaired", {"id": did, "name": r.get("name", ""),
                                "count": len(remote.devices())})
    await bus.emit("log", {"level": "info",
                           "msg": f"📱 {r.get('name') or 'Móvil'} desvinculado"
                                  + (" (usaba el token compartido)" if r.get("antiguo") else "")})
    return r


@app.post("/api/link/reset")
async def api_link_reset():
    """DESVINCULAR TODO: rota el token compartido, tira los tokens propios, olvida
    los móviles registrados y rota el código del QR. Cada móvil tendrá que
    escanear el QR nuevo para volver."""
    from backend.core.infraestructura import remote
    # `revoke_all()` hace las cuatro cosas (P3-2): la lista de tokens propios, las
    # fichas vivas, el token COMPARTIDO de antes y el código del QR. Antes esto
    # era `rotate_token()` + olvidar las fichas; ahora hay más credenciales y
    # dejarse una sería justo el agujero que cierra esta tarea.
    r = remote.revoke_all()
    await bus.emit("unpaired", {"name": "todos los móviles", "id": "*", "count": 0})
    await bus.emit("log", {"level": "info",
                           "msg": "📱 Desvinculación: tokens y código rotados; los "
                                  "enlaces antiguos ya no valen."})
    estado = await asyncio.to_thread(remote.status)
    return {**estado, "reset": r}


@app.post("/api/link/stop")
async def api_link_stop():
    from backend.core.infraestructura import remote
    # stop_tunnel() puede lanzar un taskkill (túnel adoptado): también bloquea.
    await asyncio.to_thread(remote.stop_tunnel)
    return await asyncio.to_thread(remote.status)


def _permitidos_para_abrir() -> tuple:
    """El destino que el OPERADOR declaró en ⚙, y SOLO ese (hoy: Home Assistant).

    Home Assistant es un aparato que el operador declara (`homeassistant_url`), así
    que su dirección es configuración suya y no texto de un canal: es el mismo
    argumento de confianza que ya usa `remote.py` al sondear 127.0.0.1:8177.

    Tres cosas a propósito:
      * SIN DEFAULT. Si `homeassistant_url` está vacío o no vale, no se permite
        nada: el `http://localhost:8123` que el HUD usa cuando no hay nada
        configurado NO es configuración, y se rechaza con su negativa.
      * Se valida al leerlo (http/https, con equipo, sin `usuario:clave@`): un
        valor guardado que no es una URL no blanquea nada.
      * La comparación (esquema + equipo + puerto, en `net._cubierto_por`) es
        exacta, así que este valor no sirve para abrir OTRO destino interno.
    """
    from urllib.parse import urlsplit

    base = str(settings.get("homeassistant_url", "") or "").strip()
    if not base:
        return ()
    try:
        partes = urlsplit(base)
        if (partes.scheme or "").lower() not in ("http", "https"):
            return ()
        if "@" in partes.netloc or not (partes.hostname or "").strip():
            return ()
        _ = partes.port                       # un puerto ilegible no es una base válida
    except Exception:                        # noqa: BLE001
        return ()
    return (base,)


@app.post("/api/open_url")
async def api_open_url(payload: dict):
    """Abre una URL en el navegador REAL del PC (los enlaces del chat).

    UNA sola regla para «abrir un enlace» (SEC-11 / T20b), la misma de
    `net.safe_get`: solo destinos públicos http/https, sin `usuario:clave@`
    dentro y sin loopback, red local ni metadatos de la nube. Si nexus no puede
    pedir una URL, tampoco se le manda abrir al navegador — que además la abriría
    con la SESIÓN y las COOKIES del operador, así que
    `http://127.0.0.1:8177/api/command` llegaría a la API de este equipo como si
    fuera él. Un `file:///C:/…`, una ruta UNC o un `smb://…` se rechazan con la
    negativa en español y sin llamar al navegador.
    """
    from backend.core.comun import net
    url = str(payload.get("url", "")).strip()
    error = net.rechazo_abrible(url, permitidos=_permitidos_para_abrir())
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    import webbrowser
    webbrowser.open(url)
    return {"ok": True}


@app.get("/m")
async def mobile():
    """Interfaz móvil (PWA): el nodo nexus. Ábrela desde el móvil apuntando
    al PC en la LAN: http://IP-DEL-PC:8177/m"""
    # SIN CACHÉ: el WebView del móvil guardaba la página días y NO pedía la nueva
    # versión al PC (parecía que los cambios «no llegaban»). no-store = siempre fresca.
    return FileResponse(FRONTEND_DIR / "mobile.html",
                        headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/sw.js")
async def service_worker():
    return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store, max-age=0"})


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
