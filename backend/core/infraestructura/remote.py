"""
nexus — Vinculación remota del móvil (QR + túnel, SIN misma WiFi).

Cómo funciona:
  1. El PC arranca un túnel público con cloudflared («quick tunnel», gratis y
     sin cuenta): https://<algo>.trycloudflare.com → tu nexus local.
  2. nexus tiene un CÓDIGO de vinculación vigente (`pairing_code`): 8 caracteres
     de un alfabeto sin equívocos, de un solo uso y con caducidad
     (`vinculacion.ttl_codigo_segundos` de config/umbrales.json).
  3. El HUD muestra un QR con la URL del túnel + ese código.
  4. El móvil escanea el QR, canjea el código UNA vez (`POST /api/link/pair`) y
     recibe su TOKEN PROPIO, que a partir de ahí usa en cada petición (middleware
     de app.py). Cada móvil tiene el suyo y se puede revocar uno solo
     (`POST /api/link/revoke`).

EL TOKEN COMPARTIDO DE ANTES (`link_token`) NO DESAPARECE, y es a propósito
(roadmap P3-2 / T21): los teléfonos ya instalados lo tienen guardado en su
`localStorage` y el `movil/MainActivity.java` lo lleva pegado en cada dirección
que guarda, así que retirarlo de golpe los dejaría fuera sin que nadie pudiera
explicarlo. Sigue valiendo como PERIODO DE GRACIA, el HUD lo enseña como
«dispositivo antiguo» y el dueño lo apaga revocándolo (o con «Desvincular», que
rota las dos credenciales). Lo que ya NO se reparte es el token compartido: el
QR entrega el código de un solo uso.

Si cloudflared no está: se intenta DESCARGAR solo (GitHub oficial) a la
carpeta `data/` (`DATA_DIR`, o sea que una prueba con `NEXUS_DATA_DIR` aislado
NUNCA ensucia el repositorio); si tampoco se puede, se da el enlace para bajarlo
a mano a `data/` o a `config/` (esa copia heredada se sigue leyendo).
Plan B sin túnel: QR con la IP local (solo misma WiFi).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import re
import secrets as pysecrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..comun.atomicos import escribir_json_atomico
from ..comun.config import CONFIG_DIR, DATA_DIR, settings
from ..comun import secretos as _secretos   # mismo_secreto: comparar material secreto en bytes

CLOUDFLARED_URL_WIN = ("https://github.com/cloudflare/cloudflared/releases/"
                       "latest/download/cloudflared-windows-amd64.exe")
CLOUDFLARED_PAGE = "https://github.com/cloudflare/cloudflared/releases/latest"

_state = {"proc": None, "url": "", "starting": False, "error": "",
          # «adoptado» = el túnel lo abrió un nexus ANTERIOR y este se ha
          # limitado a reutilizarlo, así que no tenemos su proceso. Ver
          # start_tunnel() y status(): sin esta marca, un túnel perfectamente
          # vivo salía como «caído» en el HUD por no tener `proc`.
          "adoptado": False}

# Dónde se apunta la URL del túnel para el arranque siguiente (data/ está en
# .gitignore). Ver `_guarda_tunel` / `start_tunnel`.
_TUNEL_FILE = DATA_DIR / "tunel.json"

# ─────────────────────────────────────────────────────────────────────────────
# Los números de red viven FUERA del código, en config/umbrales.json (sección
# «red»), como el resto de umbrales del proyecto. Lo de aquí abajo es el valor
# de reserva por si el archivo no está o está roto: nadie se queda sin sondeo
# por un JSON mal escrito.
_UMBRALES_RED_RESERVA = {"cache_sondeo_seg": 120.0}


def _carga_umbrales_red() -> dict:
    """Lee la sección «red» de config/umbrales.json sobre los de reserva."""
    vals = dict(_UMBRALES_RED_RESERVA)
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("red") or {}
            for k, v in leido.items():
                if k in vals and isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals[k] = float(v)
    except Exception:
        pass
    return vals


# CUIDADO AL TOCAR ESTE NÚMERO: tiene que ser MAYOR que el intervalo con el que
# el HUD pregunta por los dispositivos (45 s, `setInterval(refreshDevices, 45000)`
# en frontend/js/command.js). Estaba en 30 s, o sea SIEMPRE por debajo: cada
# refresco encontraba la caché caducada y volvía a pagar la resolución mDNS
# entera (4,25 s medidos aquí), que es lo que congelaba nexus. Una caché que dura
# menos que el intervalo de sondeo no cachea nada.
_CACHE_SONDEO = float(_carga_umbrales_red()["cache_sondeo_seg"])


# ------------------------------------------------------------------ dispositivos
# Registro EN MEMORIA de los móviles vinculados y conectados AHORA. El móvil,
# nada más enlazar por WS, se presenta con un «hello» (ver app.py) y aquí queda
# apuntado; al desconectarse se borra. El HUD lo consulta por /api/link/status
# y recibe eventos 'paired'/'unpaired' por el bus para cerrar el QR y mostrarlo.
_devices: dict[str, dict] = {}


def register_device(info: dict) -> dict:
    """Apunta (o refresca) un móvil vinculado. Devuelve la ficha del dispositivo.

    `antiguo` = se ha autenticado con el token COMPARTIDO de siempre, no con uno
    propio (ver el docstring del módulo). No es un detalle cosmético: es lo que
    el HUD necesita para decir «este móvil hay que re-vincularlo» y para saber
    que revocarlo cierra la credencial de todos los antiguos, no de uno."""
    did = (str(info.get("id") or "").strip() or pysecrets.token_hex(4))
    prev = _devices.get(did, {})
    dev = {
        "id": did,
        "name": (str(info.get("name") or "").strip() or "Móvil")[:40],
        "ua": str(info.get("ua") or "")[:200],
        "ip": str(info.get("ip") or "")[:60],
        "since": prev.get("since") or time.strftime("%H:%M"),
        "last": time.strftime("%H:%M"),
        "ts": time.time(),
        "online": True,
        "antiguo": bool(info.get("antiguo", prev.get("antiguo", False))),
    }
    _devices[did] = dev
    return dev


def forget_device(did: str) -> None:
    _devices.pop(str(did), None)


def mark_offline(did: str) -> None:
    """El WS del móvil se ha cortado (pantalla bloqueada / app en 2º plano).
    NO se desvincula: queda «en espera» — antes el HUD decía «no vinculado» en
    cuanto bloqueabas el móvil, y eso es mentira (bug reportado por Adri)."""
    d = _devices.get(str(did))
    if d:
        d["online"] = False
        d["ts_off"] = time.time()


def is_online(did: str) -> bool:
    d = _devices.get(str(did))
    return bool(d and d.get("online", True))


def devices() -> list:
    """Móviles conectados ahora, el más reciente primero."""
    return sorted(_devices.values(), key=lambda d: d.get("ts", 0), reverse=True)


# ─────────────────────────────────────────── código de vinculación (un solo uso)
# POR QUÉ EXISTE (roadmap P3-2 / task T21)
# ---------------------------------------
# Antes el QR llevaba EL token: el mismo para todos los móviles y para siempre.
# De ahí salían dos agujeros de la auditoría (04 §3): revocar un teléfono perdido
# desvinculaba TODOS (`rotate_token`), y un token filtrado en un móvil valía desde
# cualquier sitio de la LAN o del túnel sin forma de acotarlo.
#
# Ahora el QR reparte un CÓDIGO de un solo uso, corto de vida y de 8 caracteres
# (31 símbolos sin 0/O/1/I/L, ≈39,6 bits: no se adivina), y el móvil lo canjea
# UNA vez por un token suyo. Es la misma disciplina que ya está probada en el
# puente de Telegram (61396b0, SEC-02): `secrets` para generar, la TTL en
# config/umbrales.json, `hmac.compare_digest` para comparar y borrado al usarlo.
#
# DIFERENCIA a propósito con el código de Telegram: aquel se REGENERA en cada
# `GET /api/telegram/link`; este NO, porque el QR se repinta cada vez que el HUD
# pregunta por el estado (cada 45 s) y regenerarlo invalidaría el código que el
# dueño tiene en la pantalla. Aquí el código vive hasta que se canjea o caduca.
_ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LARGO_CODIGO = 8            # 8 de 31 símbolos ≈ 39,6 bits
_TTL_CODIGO_RESERVA = 300.0  # 5 min; el valor de verdad está en umbrales.json


def ttl_codigo_segundos() -> float:
    """Cuánto vive el código del QR, desde `config/umbrales.json` («vinculacion»).

    Con reserva si el archivo falta, está roto o el valor no vale: un umbral mal
    escrito no puede dejar la vinculación sin caducidad."""
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("vinculacion") or {}
            valor = leido.get("ttl_codigo_segundos")
            if isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor > 0:
                return float(valor)
    except Exception:                                        # noqa: BLE001
        pass
    return _TTL_CODIGO_RESERVA


def _ahora() -> float:
    """El reloj del módulo (para poder simular la caducidad en las pruebas)."""
    return time.time()


_pendiente: dict = {"codigo": "", "creado": 0.0}


def pairing_code() -> str:
    """El código de vinculación VIGENTE; lo crea si no hay o si ya caducó.

    Es estable a propósito: quien lo tenga en la mano (el QR del HUD) puede
    pedirlo las veces que haga falta sin que deje de valer."""
    ahora = _ahora()
    if _pendiente["codigo"] and (ahora - _pendiente["creado"]) <= ttl_codigo_segundos():
        return str(_pendiente["codigo"])
    nuevo = "".join(pysecrets.choice(_ALFABETO_CODIGO) for _ in range(_LARGO_CODIGO))
    _pendiente.update(codigo=nuevo, creado=ahora)
    return nuevo


def invalidar_codigo() -> None:
    """Tira el código pendiente: no vuelve a valer (desvincular, o caducado)."""
    _pendiente.update(codigo="", creado=0.0)


def _codigo_vigente() -> str:
    if not _pendiente["codigo"]:
        return ""
    if (_ahora() - _pendiente["creado"]) > ttl_codigo_segundos():
        invalidar_codigo()                 # caducado: no revive nunca
        return ""
    return str(_pendiente["codigo"])


def canjear_codigo(intento: str) -> bool:
    """¿Este código es el vigente? Si lo es, se CONSUME (un solo uso)."""
    esperado = _codigo_vigente()
    intento = str(intento or "").strip().upper()
    if not esperado or not intento:
        return False
    # Tiempo constante, como el secreto de n8n y el código de Telegram: adivinar
    # carácter a carácter midiendo lo que tarda no debe ser posible. La llamada
    # se hace SIEMPRE, incluso con el intento vacío, para no abrir un atajo.
    if not _secretos.mismo_secreto(intento, esperado):
        return False
    invalidar_codigo()                     # de un solo uso
    return True


# ─────────────────────────────────────────── token PROPIO por dispositivo
# DÓNDE VIVE EL TOKEN, Y POR QUÉ ES SUFICIENTE ASÍ
# ------------------------------------------------
# En `data/dispositivos.json` se guarda el DIGESTO sha256 del token, nunca el
# token. El archivo NO está en `config/` (que el HUD lee entero por /api/config)
# y `status()` no devuelve ningún digesto, así que lo que el HUD lee no vale
# como credencial. Con un token de 32 bytes al azar (`token_urlsafe(32)`, 256
# bits) el digesto no se puede invertir ni por fuerza bruta, que es justo la
# razón por la que aquí un hash basta y no hace falta un derivador lento (no hay
# contraseña humana que proteger). La comparación es `hmac.compare_digest` del
# digesto, o sea tiempo constante.
#
# LO QUE ESTO **NO** PROTEGE, dicho claro: quien pueda leer el archivo y además
# espiar la red no gana nada (el digesto no da el token), pero un malware que
# corra como este usuario puede leer la memoria del proceso nexus y ahí sí están
# los tokens en claro mientras duran las peticiones. Eso ya era cierto antes con
# el token compartido y es inherente a un asistente local (04 §4).
_DEVICES_FILE = DATA_DIR / "dispositivos.json"
_STORE_VERSION = 1

_fichas_cache: list | None = None


def _huella(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _fichas_guardadas() -> list:
    """Los dispositivos con token propio, leídos del disco una vez.

    Un archivo ilegible devuelve la lista VACÍA (falla cerrado: sin tienda no hay
    tokens válidos), no una lista de dispositivos con digesto vacío."""
    global _fichas_cache
    if _fichas_cache is None:
        lista: list = []
        try:
            if _DEVICES_FILE.is_file():
                disco = json.loads(_DEVICES_FILE.read_text(encoding="utf-8")) or {}
                for f in (disco.get("dispositivos") or []):
                    if isinstance(f, dict) and f.get("id") and f.get("digest"):
                        lista.append(f)
        except Exception:                                    # noqa: BLE001
            lista = []
        _fichas_cache = lista
    return _fichas_cache


def _guarda_fichas(lista: list) -> bool:
    """Escribe la tienda de forma atómica. False si no se pudo (y NO se miente)."""
    global _fichas_cache
    try:
        escribir_json_atomico(_DEVICES_FILE,
                              {"version": _STORE_VERSION,
                               "dispositivos": list(lista)},
                              indent=2)
    except Exception:                                        # noqa: BLE001
        return False
    _fichas_cache = list(lista)
    return True


def pair_device(codigo: str, device_id: str = "", name: str = "") -> dict | None:
    """Canjea el código del QR por un token PROPIO de ese móvil.

    Devuelve `{id, name, token}` o None. El código se consume ANTES de escribir:
    si el disco falla, el código queda gastado y no se entrega ninguna credencial
    que no haya quedado guardada (mejor re-escanear el QR que un token que no
    existe en ningún sitio)."""
    if not canjear_codigo(codigo):
        return None
    token = pysecrets.token_urlsafe(32)
    did = (str(device_id or "").strip() or pysecrets.token_hex(4))[:40]
    nombre = (str(name or "").strip() or "Móvil")[:40]
    fichas = [f for f in _fichas_guardadas() if str(f.get("id")) != did]
    fichas.append({"id": did, "name": nombre, "digest": _huella(token),
                   "creado": _ahora()})
    if not _guarda_fichas(fichas):
        return None
    register_device({"id": did, "name": nombre, "antiguo": False})
    return {"id": did, "name": nombre, "token": token}


def device_owner(token: str) -> dict | None:
    """La ficha del móvil dueño de este token PROPIO, o None.

    Compara digestos con `hmac.compare_digest`; el token en claro no se guarda en
    ningún sitio y por eso no se puede «leer de vuelta»."""
    token = str(token or "")
    if not token:
        return None
    objetivo = _huella(token)
    for ficha in _fichas_guardadas():
        if _secretos.mismo_secreto(objetivo, ficha.get("digest") or ""):
            return ficha
    return None


def revoke_device(did: str) -> dict:
    """Mata el token de UN dispositivo.

    DECISIÓN DE COMPATIBILIDAD (a), escrita aquí porque es donde se ve su precio:
    los móviles que se autentican con el token COMPARTIDO de siempre no tienen
    una credencial propia que apagar, así que revocar uno de ellos cierra esa
    credencial para todos los antiguos (y solo para ellos: los que ya tienen
    token propio siguen dentro). La alternativa era (b), no admitir el token
    compartido desde el primer arranque: más limpia de libro y deja fuera, sin
    explicación posible, a todos los teléfonos ya instalados. Se eligió (a)."""
    did = str(did or "").strip()
    if not did:
        return {"ok": False,
                "error": "no has dicho qué dispositivo revocar (falta el id)"}
    fichas = _fichas_guardadas()
    quedan = [f for f in fichas if str(f.get("id")) != did]
    if len(quedan) != len(fichas):
        nombre = next((str(f.get("name") or "ese móvil")
                       for f in fichas if str(f.get("id")) == did), "ese móvil")
        if not _guarda_fichas(quedan):
            return {"ok": False,
                    "error": "no he podido guardar la lista de dispositivos; no se ha revocado nada"}
        forget_device(did)
        return {"ok": True, "revocado": True, "id": did, "antiguo": False,
                "name": nombre,
                "aviso": f"El token de «{nombre}» ya no vale. Los demás móviles "
                         "siguen vinculados."}
    # No tiene token propio: es uno de los móviles ANTIGUOS (token compartido).
    if did in _devices:
        nombre = str(_devices[did].get("name") or "ese móvil")
        rotate_token()                     # la credencial compartida deja de valer
        for otro, ficha in list(_devices.items()):
            if ficha.get("antiguo"):
                forget_device(otro)
        forget_device(did)
        return {"ok": True, "revocado": True, "id": did, "antiguo": True,
                "name": nombre,
                "aviso": "Ese móvil usaba el token COMPARTIDO de antes, que no se "
                         "puede acotar a un solo aparato: al revocarlo se cierra "
                         "para todos los móviles antiguos. Los que tienen token "
                         "propio siguen vinculados; en los antiguos hay que volver "
                         "a escanear el QR."}
    return {"ok": False,
            "error": "no hay ningún móvil vinculado con ese id (¿ya estaba revocado?)"}


def revoke_all() -> dict:
    """Desvincular TODO: tokens propios, fichas vivas, token compartido y código.

    Es «kill everything and re-pair»: el QR viejo deja de valer (código rotado) y
    ningún móvil conserva acceso."""
    cuantas = len(_fichas_guardadas())
    _guarda_fichas([])
    for did in list(_devices):
        forget_device(did)
    rotate_token()
    invalidar_codigo()
    return {"ok": True, "dispositivos": cuantas}


def vinculados() -> list:
    """Los móviles que el HUD puede revocar, uno por uno.

    Incluye los que YA NO están conectados: un teléfono perdido lleva horas con el
    WebSocket cerrado y sigue teniendo su token, o sea que sigue siendo el que hay
    que poder quitar de la lista."""
    vivos = {str(d.get("id")): d for d in _devices.values()}
    fuera: list = []
    vistos: set[str] = set()
    for f in _fichas_guardadas():
        did = str(f.get("id") or "")
        if not did:
            continue
        vistos.add(did)
        viva = dict(vivos.get(did) or {})
        creado = f.get("creado")
        desde = ""
        try:
            if creado:
                desde = time.strftime("%d/%m/%Y", time.localtime(float(creado)))
        except Exception:                                    # noqa: BLE001
            desde = ""
        fuera.append({
            "id": did,
            "name": str(viva.get("name") or f.get("name") or "Móvil")[:40],
            "ip": str(viva.get("ip") or ""),
            "since": str(viva.get("since") or ""),
            "last": str(viva.get("last") or ""),
            "online": bool(viva.get("online")),
            "antiguo": False,
            "vinculado_desde": desde,
        })
    for did, ficha in vivos.items():
        if did in vistos:
            continue
        fuera.append({
            "id": did,
            "name": str(ficha.get("name") or "Móvil")[:40],
            "ip": str(ficha.get("ip") or ""),
            "since": str(ficha.get("since") or ""),
            "last": str(ficha.get("last") or ""),
            "online": bool(ficha.get("online")),
            "antiguo": bool(ficha.get("antiguo")),
            "vinculado_desde": "",
        })
    return fuera


# ------------------------------------------------- token COMPARTIDO (gracia)
# Sigue existiendo SOLO por los móviles ya instalados (decisión (a), ver
# `revoke_device`). Ya no viaja en el QR: lo que el QR reparte es el código de
# arriba, así que este token solo envejece.
def link_token() -> str:
    tok = settings.secret("link_token")
    if not tok:
        tok = pysecrets.token_urlsafe(18)
        settings.set_secret("link_token", tok)
    return tok


def rotate_token() -> str:
    settings.set_secret("link_token", pysecrets.token_urlsafe(18))
    return settings.secret("link_token")


# ------------------------------------------------------------------ red local
def nombre_local() -> str:
    """El nombre de red de este PC, en forma «equipo.local» (mDNS).

    ES LA DIRECCIÓN QUE NO CAMBIA. La IP de la WiFi la reparte el router y baila
    con cada reinicio; el nombre del equipo no. Windows 10+ responde a mDNS de
    serie y Android lo resuelve, así que «MIPC.local» sigue valiendo dentro de
    casa después de apagar el ordenador mil veces. Sin cuentas, sin servicios,
    sin nada que caduque."""
    try:
        n = socket.gethostname().strip().split(".")[0]
        return f"{n}.local" if n and n.lower() != "localhost" else ""
    except Exception:
        return ""


_alcance_cache: dict = {}


def responde(host_puerto: str, timeout: float = 0.6, cache_seg: float | None = None) -> bool:
    """¿Hay algo escuchando de verdad en «maquina:puerto»?

    OJO CON `timeout` (01/08/2026): NO cubre la resolución del nombre. Aquí
    dentro `create_connection` primero llama a `getaddrinfo`, y resolver
    «TUPC.local» por mDNS tarda 4,25 s medidos en este equipo por muy bajo que
    pongas el timeout. Por eso esta función NO se puede llamar desde el bucle de
    asyncio sin `asyncio.to_thread` (ver /api/link/status en app.py) y por eso la
    caché de abajo importa tanto.

    POR QUÉ EXISTE (31/07/2026). Esta lista prometía direcciones que NO
    aceptaban conexiones: uvicorn estaba atado solo a 127.0.0.1, así que el QR
    llevaba a «MIPC.local:8177» y el móvil se comía un «rechazada» sin más
    explicación. Ofrecer una dirección muerta es peor que no ofrecerla: el móvil
    la prueba, falla, y el usuario no sabe si el fallo es suyo o del PC.

    OJO CON LO QUE ESTO *NO* PRUEBA: se comprueba desde este mismo equipo, y el
    cortafuegos de Windows puede dejar pasar al propio PC y bloquear al móvil.
    Que salga True significa «el puerto está abierto aquí», no «tu móvil llega»."""
    if cache_seg is None:
        cache_seg = _CACHE_SONDEO       # config/umbrales.json → «red»
    ahora = time.time()
    prev = _alcance_cache.get(host_puerto)
    if prev and ahora - prev[0] < cache_seg:
        return prev[1]
    ok = False
    try:
        maquina, _, puerto = host_puerto.rpartition(":")
        with socket.create_connection((maquina, int(puerto)), timeout=timeout):
            ok = True
    except Exception:
        ok = False                          # cerrado, filtrado o nombre que no resuelve
    _alcance_cache[host_puerto] = (ahora, ok)
    return ok


def direcciones() -> list[dict]:
    """TODAS las formas de llegar a este nexus, de más estable a menos.

    El móvil se queda con la lista entera, no con una sola. Ese era el fallo de
    raíz: guardaba UNA dirección (la del túnel, que es aleatoria en cada
    arranque) y al reiniciar el PC se quedaba huérfano y había que revincular.
    Con la lista, prueba una por una y se queda con la que conteste.

    Las direcciones de red se SONDEAN antes de ofrecerlas (ver `responde`) y cada
    una sale marcada con «verificada». La del túnel no se sondea: vive en el borde
    de Cloudflare y comprobarla cuesta una vuelta a internet en cada refresco del
    HUD; que cloudflared haya registrado la conexión ya es señal de que está viva.

    OJO CON EL FILTRO, que casi la lío (31/07/2026). Al principio las no
    verificadas se TIRABAN. Si no contestaba ninguna —nexus levantándose todavía,
    el cortafuegos de por medio— la lista salía VACÍA y el QR se quedaba sin nada
    que ofrecer. Eso es peor que una dirección dudosa: con una dudosa el móvil al
    menos lo intenta; sin ninguna, ni eso, y encima no hay nada que explique por
    qué. Así que la regla es: se descartan las muertas SOLO si queda alguna viva."""
    cand: list[dict] = []
    ts = tailscale_url()
    if ts:
        cand.append({"host": ts, "esquema": "http", "tipo": "tailscale",
                     "estable": True, "desde": "cualquier red",
                     "verificada": responde(ts)})
    nl = nombre_local()
    if nl:
        cand.append({"host": f"{nl}:8177", "esquema": "http", "tipo": "nombre",
                     "estable": True, "desde": "tu casa",
                     "verificada": responde(f"{nl}:8177")})
    ip = lan_ip()
    if ip and ip != "127.0.0.1":
        cand.append({"host": f"{ip}:8177", "esquema": "http", "tipo": "wifi",
                     "estable": False, "desde": "tu casa",
                     "verificada": responde(f"{ip}:8177")})

    vivas = [d for d in cand if d["verificada"]]
    red = vivas if vivas else cand             # nunca vacía por culpa del sondeo

    tunel = []
    if _state["url"]:
        tunel = [{"host": _state["url"].replace("https://", ""), "esquema": "https",
                  "tipo": "tunel", "estable": False, "desde": "cualquier red",
                  "verificada": True}]         # no se sondea: cloudflared ya la registró

    # EL QR ABRE dirs[0]. La primaria tiene que ser alcanzable desde CUALQUIER red,
    # no solo en casa. Orden de esa primera puerta:
    #   1. Tailscale — IP fija, cualquier red, sobrevive reinicios. La buena.
    #   2. Túnel Cloudflare — llega desde fuera (cambia en cada arranque, pero llega).
    #   3. LAN (nombre .local / IP WiFi) — solo casa.
    # Antes la primaria era el nombre «.local»: fuera de casa NO resuelve (y el mDNS
    # de Android falla a menudo), así que el móvil en datos se comía 20-30 s de
    # timeout por cada dirección LAN antes de caer al túnel. De ahí la «pantalla
    # negra que tarda». Las LAN siguen en la lista como respaldo (rápidas en casa).
    ts_dirs = [d for d in red if d["tipo"] == "tailscale"]
    lan_dirs = [d for d in red if d["tipo"] != "tailscale"]
    return ts_dirs + tunel + lan_dirs


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ------------------------------------------------------------------ tailscale
# POR QUÉ EXISTE (decisión de Adri, 30/07/2026)
# ---------------------------------------------
# El túnel «quick» de Cloudflare da una dirección DISTINTA cada vez que arranca
# (https://<algo-aleatorio>.trycloudflare.com). El móvil se guarda esa URL para
# siempre, así que en cuanto se reinicia el PC —o se cae cloudflared— la
# dirección guardada ya no existe y hay que volver a escanear el QR. El token no
# era el problema: la dirección sí.
#
# Tailscale resuelve justo eso: monta una red privada entre TUS aparatos y le da
# a cada uno una IP FIJA (100.x.y.z) que no cambia nunca, ni al reiniciar, ni al
# cambiar de WiFi, ni al salir a 4G. Y además nexus deja de estar publicado en
# internet: solo lo ven los dispositivos de tu propia red de Tailscale.
#
# Requisito honesto: Tailscale tiene que estar instalado y con sesión iniciada
# en LOS DOS aparatos (el PC y el móvil), con la misma cuenta. El plan gratuito
# llega de sobra. Sigue haciendo falta el token del QR: una IP de Tailscale no
# es «este equipo», así que pasa por el mismo control que todo lo demás.
TAILSCALE_WEB = "https://tailscale.com/download"
_ts_cache: dict = {"t": 0.0, "datos": None}


def _tailscale_exe() -> str:
    """Ruta del ejecutable de tailscale, o '' si no está instalado."""
    import shutil
    exe = shutil.which("tailscale")
    if exe:
        return exe
    if sys.platform == "win32":
        for c in (r"C:\Program Files\Tailscale\tailscale.exe",
                  r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
            if Path(c).exists():
                return c
    for c in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale",
              "/usr/bin/tailscale", "/usr/local/bin/tailscale"):
        if Path(c).exists():
            return c
    return ""


def tailscale_status(cache_seg: float = 20.0) -> dict:
    """Estado real de Tailscale en ESTE equipo.

    {instalado, activo, ip, host, dispositivos, error}. Nunca lanza: si algo
    falla, `activo` es False y `error` explica qué pasa en cristiano."""
    ahora = time.time()
    if _ts_cache["datos"] is not None and ahora - _ts_cache["t"] < cache_seg:
        return _ts_cache["datos"]
    info = {"instalado": False, "activo": False, "ip": "", "host": "",
            "dispositivos": 0, "error": ""}
    exe = _tailscale_exe()
    if not exe:
        info["error"] = ("Tailscale no está instalado en este equipo. "
                         f"Se descarga en {TAILSCALE_WEB} (el plan gratis sobra).")
        _ts_cache.update(t=ahora, datos=info)
        return info
    info["instalado"] = True
    try:
        import json as _json
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True,
                           timeout=10,
                           creationflags=(subprocess.CREATE_NO_WINDOW
                                          if sys.platform == "win32" else 0))
        if r.returncode != 0:
            info["error"] = ("Tailscale está instalado pero no ha arrancado sesión. "
                             "Ábrelo e inicia sesión con tu cuenta.")
            _ts_cache.update(t=ahora, datos=info)
            return info
        d = _json.loads(r.stdout or "{}")
        yo = d.get("Self") or {}
        ips = [x for x in (yo.get("TailscaleIPs") or []) if ":" not in x]   # IPv4
        info["ip"] = ips[0] if ips else ""
        info["host"] = (yo.get("DNSName") or "").rstrip(".")
        info["dispositivos"] = len(d.get("Peer") or {})
        estado = (d.get("BackendState") or "").lower()
        info["activo"] = bool(info["ip"]) and estado == "running"
        if not info["activo"]:
            info["error"] = ("Tailscale está instalado pero no conectado "
                             f"(estado: {estado or 'desconocido'}). Ábrelo e inicia sesión.")
    except FileNotFoundError:
        info["error"] = "Tailscale no está instalado en este equipo."
        info["instalado"] = False
    except subprocess.TimeoutExpired:
        info["error"] = "Tailscale ha tardado demasiado en contestar."
    except Exception as exc:                                        # noqa: BLE001
        info["error"] = f"No he podido leer el estado de Tailscale ({type(exc).__name__})."
    _ts_cache.update(t=ahora, datos=info)
    return info


def tailscale_url() -> str:
    """La dirección ESTABLE del PC, o '' si Tailscale no está listo."""
    ts = tailscale_status()
    return f"{ts['ip']}:8177" if ts.get("activo") and ts.get("ip") else ""


# ------------------------------------------------------------------ cloudflared
# DE DÓNDE ES EL BINARIO Y DÓNDE SE BAJA (tarea T39c, hallada al cerrar T39b).
# Antes las dos rutas se montaban a mano con `ROOT / "config"`, que IGNORA
# `NEXUS_CONFIG_DIR`/`NEXUS_DATA_DIR`: una prueba (o un arranque aislado) bajaba
# un `.exe` DENTRO del repositorio y podía acabar lanzando el binario del
# operador. Se decide fichero a fichero, como en T39b:
#   * `_CLOUDFLARED_LOCAL` — un cloudflared DESCARGADO es un ARTEFACTO DE
#     INSTALACIÓN, no un dato del operador: se puede volver a bajar cuando haga
#     falta y no tiene nada que ver con su configuración. Vive en `DATA_DIR`, que
#     es la misma carpeta donde ya se apunta la URL del túnel (`_TUNEL_FILE`). Sin
#     la variable sigue siendo `ROOT/data`, que ya está en `.gitignore`.
#   * `_CLOUDFLARED_HEREDADO` — donde nexus se lo pedía al operador hasta ahora
#     (`config/`, que sí sigue `CONFIG_DIR`). Se sigue BUSCANDO, pero solo se LEE:
#     nadie lo reescribe y a quien ya lo tenía no se le fuerza una descarga de
#     60 MB (ni se le dice «no está instalado» en Linux, donde la descarga
#     automática no existe y la copia del operador era la única forma de tenerlo).
_CLOUDFLARED_LOCAL = DATA_DIR / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")
_CLOUDFLARED_HEREDADO = CONFIG_DIR / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")


def _cloudflared_path() -> Path | None:
    """Busca cloudflared: PATH del sistema, `DATA_DIR` o la copia heredada de `CONFIG_DIR`."""
    import shutil
    exe = shutil.which("cloudflared")
    if exe:
        return Path(exe)
    for local in (_CLOUDFLARED_LOCAL, _CLOUDFLARED_HEREDADO):
        if local.exists():
            return local
    return None


async def _download_cloudflared() -> Path | None:
    """Descarga cloudflared oficial a `DATA_DIR` (Windows). None si no se pudo."""
    if sys.platform != "win32":
        return None
    dest = _CLOUDFLARED_LOCAL
    try:
        import httpx
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as cli:
            r = await cli.get(CLOUDFLARED_URL_WIN)
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
        return dest
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────── túnel adoptado
# POR QUÉ EXISTE (tarea #12, 01/08/2026)
# --------------------------------------
# El «quick tunnel» de Cloudflare da un subdominio ALEATORIO distinto cada vez
# que arranca. Como start_tunnel() empezaba matando el cloudflared anterior y
# abriendo uno nuevo, la dirección cambiaba en CADA reinicio del PC y el móvil se
# quedaba apuntando a un sitio que ya no existe: a re-escanear el QR otra vez.
#
# Si el cloudflared del arranque anterior sigue vivo y sigue apuntando a nuestro
# 127.0.0.1:8177, lo suyo es QUEDÁRSELO. Misma dirección, cero QR.
_ADOPCION_TIMEOUT = 5.0                 # lo que se espera a que conteste la URL vieja
_ADOPCION_MAX_HORAS = 72.0              # más viejo que esto ni se prueba


def _guarda_tunel(url: str) -> None:
    """Apunta la URL del túnel para poder reutilizarla en el arranque siguiente."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _TUNEL_FILE.write_text(json.dumps({"url": url, "ts": time.time()}),
                               encoding="utf-8")
    except Exception:
        pass                            # no poder anotarlo no puede tumbar el túnel


def _tunel_guardado() -> str:
    """La URL del arranque anterior, o '' si no hay o es demasiado vieja."""
    try:
        if not _TUNEL_FILE.is_file():
            return ""
        d = json.loads(_TUNEL_FILE.read_text(encoding="utf-8")) or {}
        url = str(d.get("url") or "").strip()
        ts = float(d.get("ts") or 0)
        if not url.startswith("https://"):
            return ""
        if ts and (time.time() - ts) > _ADOPCION_MAX_HORAS * 3600:
            return ""
        return url
    except Exception:
        return ""


def _olvida_tunel() -> None:
    try:
        _TUNEL_FILE.unlink()
    except Exception:
        pass


async def _sigue_siendo_nuestro(url: str) -> bool:
    """¿La URL guardada sigue viva Y sigue sirviendo NUESTRA página del móvil?

    NO vale con mirar si `cloudflared.exe` está en la lista de procesos: un
    cloudflared vivo puede estar sirviendo un túnel viejo que ya no apunta aquí,
    o apuntar a otra cosa completamente. La única prueba que vale es pedirle la
    página y reconocerla.

    Se pide `/m`, que es ruta PÚBLICA (`_es_ruta_publica` en app.py): no hace
    falta token y no se enseña ningún secreto por el camino."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_ADOPCION_TIMEOUT,
                                     follow_redirects=True) as cli:
            r = await cli.get(url.rstrip("/") + "/m")
        # El marcador tiene que ser ESTABLE: el <title> de la página del móvil.
        # Un 200 pelado no basta — Cloudflare devuelve 200 en sus propias
        # páginas de error, y otro servicio cualquiera detrás del mismo túnel
        # también contestaría 200.
        return r.status_code == 200 and "<title>nexus</title>" in r.text.lower()
    except Exception:
        return False                    # túnel muerto, lento o apuntando a otro sitio


async def _log(nivel: str, msg: str) -> None:
    """Deja constancia en el monitor del HUD. Si el bus no está, no pasa nada."""
    try:
        from ..comun.events import bus
        await bus.emit("log", {"level": nivel, "msg": msg})
    except Exception:
        pass


async def adopta_tunel_al_arrancar() -> bool:
    """AL ARRANCAR nexus: quedarse el túnel que siguiera vivo. Devuelve si adoptó.

    Esto es la mitad que faltaba de la tarea #12. La adopción dentro de
    `start_tunnel()` solo salta cuando el usuario abre el panel del QR; hasta ese
    momento nexus creía no tener túnel, y el HUD lo decía, aunque el cloudflared
    del arranque anterior siguiera sirviendo perfectamente. Ahora se comprueba
    nada más levantar el núcleo.

    NO ABRE NADA. Si no hay un túnel vivo que ya apunte aquí, se va de vacío y
    deja las cosas como estaban. Abrir un túnel es publicar este PC en internet y
    eso lo decide el usuario, no el arranque: aquí como mucho se RE-ENGANCHA a
    uno que YA estaba abierto y YA era público."""
    if _state["url"]:
        return False                    # ya hay túnel en esta sesión: nada que adoptar
    viejo = _tunel_guardado()
    if not viejo:
        return False
    if not await _sigue_siendo_nuestro(viejo):
        _olvida_tunel()                 # murió o apunta a otro sitio: fuera la nota
        return False
    _state.update(url=viejo, proc=None, adoptado=True, error="")
    _guarda_tunel(viejo)                # refresca la marca de tiempo
    await _log("ok", f"🔗 El túnel del arranque anterior sigue vivo ({viejo}): "
                     "me lo quedo. La dirección no cambia y el móvil sigue "
                     "vinculado, NO hace falta re-escanear el QR.")
    return True


async def start_tunnel() -> dict:
    """Arranca el quick tunnel (si no está ya). Devuelve el estado."""
    if _state["url"] and _state["proc"] and _state["proc"].poll() is None:
        return status()
    if _state["url"] and _state["adoptado"]:
        return status()
    if _state["starting"]:
        return status()
    _state.update(starting=True, error="", url_pending="")
    try:
        # ADOPCIÓN ANTES DEL TASKKILL. Si el túnel del arranque anterior sigue
        # vivo y sigue siendo nuestro, se reutiliza: así la dirección NO cambia y
        # el móvil no tiene que volver a escanear el QR.
        viejo = _tunel_guardado()
        if viejo and await _sigue_siendo_nuestro(viejo):
            _state.update(url=viejo, proc=None, adoptado=True, error="")
            _guarda_tunel(viejo)        # refresca la marca de tiempo
            await _log("ok", f"🔗 Reutilizo el túnel que seguía vivo ({viejo}): "
                             "la dirección no cambia, NO hace falta re-escanear el QR.")
            return status()

        # LIMPIEZA: cada reinicio del PC con taskkill deja el cloudflared anterior
        # VIVO (es un proceso hijo aparte) con un túnel viejo colgando. Se matan
        # antes de abrir el nuevo para que no se acumulen ni confundan.
        _state["adoptado"] = False
        _olvida_tunel()                 # la guardada ya no vale: no contestó
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                               capture_output=True, timeout=8,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
        exe = _cloudflared_path()
        if exe is None:
            exe = await _download_cloudflared()
        if exe is None:
            _state["error"] = ("cloudflared no está instalado y no he podido descargarlo. "
                               f"Bájalo aquí y déjalo en data/: {CLOUDFLARED_PAGE}")
            return status()
        proc = subprocess.Popen(
            [str(exe), "tunnel", "--url", "http://127.0.0.1:8177", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
        _state["proc"] = proc

        def _read_url():
            pend = ""
            for line in proc.stdout:                      # type: ignore[union-attr]
                if not pend:
                    m = re.search(r"https://[\w\-]+\.trycloudflare\.com", line)
                    if m:
                        pend = m.group(0)
                        _state["url_pending"] = pend
                        continue
                # el túnel FUNCIONA cuando cloudflared registra la conexión con el
                # borde («Registered tunnel connection»); hasta entonces la URL
                # existe pero devuelve 530 y el móvil dice «túnel caído».
                if pend and ("Registered tunnel connection" in line
                             or "registered connIndex" in line.lower()):
                    _state["url"] = pend
                    _guarda_tunel(pend)   # para poder adoptarlo en el arranque siguiente
                    return

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, _read_url), timeout=30)
        except asyncio.TimeoutError:
            if _state.get("url_pending"):
                # URL impresa pero sin ver el registro en el log: úsala igualmente
                _state["url"] = _state["url_pending"]
                _guarda_tunel(_state["url_pending"])
            else:
                _state["error"] = "El túnel no ha dado URL en 30 s (¿internet caído?)."
    finally:
        _state["starting"] = False
    if _state["url"] and not _state["adoptado"]:
        await _log("warn", f"🔗 Túnel NUEVO ({_state['url']}): la dirección ha cambiado, "
                           "hay que volver a escanear el QR en el móvil.")
    return status()


def stop_tunnel() -> None:
    if _state["proc"] and _state["proc"].poll() is None:
        try:
            _state["proc"].terminate()
        except Exception:
            pass
    elif _state["adoptado"] and _state["url"]:
        # TÚNEL ADOPTADO: el cloudflared es hijo del nexus ANTERIOR, no nuestro,
        # así que no hay `proc` que terminar. Sin esto, «parar el túnel» no
        # paraba nada y el usuario se quedaba publicado en internet creyendo que
        # lo había cerrado. Se mata por nombre.
        if sys.platform == "win32":
            try:
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                               capture_output=True, timeout=8,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
        else:
            try:
                subprocess.run(["pkill", "-f", "cloudflared"],
                               capture_output=True, timeout=8)
            except Exception:
                pass
    _olvida_tunel()          # si se para a propósito, no se readopta al reiniciar
    _state.update(proc=None, url="", url_pending="", starting=False, adoptado=False)


def status() -> dict:
    """Estado de la vinculación, con la MEJOR dirección disponible.

    Orden de preferencia, y el porqué:
      1. TAILSCALE — IP fija (100.x.y.z). Sobrevive a reinicios y a cambios de
         red, y no publica nada en internet. Es la buena.
      2. TÚNEL de Cloudflare — llega desde fuera, pero la dirección cambia en
         cada arranque, así que el móvil hay que revincularlo cada vez.
      3. IP de la WiFi — solo sirve dentro de casa.

    EL TOKEN NO SALE DE AQUÍ (SEC-03 / roadmap P1-3). `GET /api/link/status`
    devuelve este diccionario ENTERO, y con el token cualquiera que lo leyera
    (bastaba una página que resolviera su dominio a 127.0.0.1) entraba desde la
    WiFi o el túnel para siempre. Quien de verdad lo necesita es el QR, que es
    lo que se escanea: va dentro de `link` y lo dibuja `/api/link/qr` (y el HUD
    con `frontend/js/modals/link.js`). Para saber si hay móviles vinculados está
    `paired`, que es lo único que hace falta saber sin el token en la mano.

    Y desde P3-2 lo que `link` lleva es un CÓDIGO de un solo uso, no una
    credencial permanente: leerlo sirve para vincular un móvil, no para entrar
    para siempre. Los tokens propios y sus digestos NO salen de aquí (`vinculados`
    trae id, nombre y estado, nada de material de credencial).
    """
    # OJO CON `alive`: un túnel ADOPTADO no tiene `proc` (lo abrió el nexus
    # anterior y su cloudflared es hijo de aquel proceso). Sin contar la marca,
    # el HUD decía «no hay túnel» con el túnel funcionando perfectamente.
    alive = bool(_state["url"]) and (
        _state["adoptado"] or bool(_state["proc"] and _state["proc"].poll() is None))
    dirs = direcciones()
    # La PRIMERA es la que abre el móvil; el resto van en el QR como respaldo,
    # para que el enlace sobreviva a que una de ellas deje de valer.
    principal = dirs[0] if dirs else {"host": f"{lan_ip()}:8177", "esquema": "http",
                                      "tipo": "wifi", "estable": False}
    host, esquema, via = principal["host"], principal["esquema"], principal["tipo"]
    alternativas = ",".join(f"{d['esquema']}://{d['host']}" for d in dirs[1:])
    # El `token=` del QR es el CÓDIGO de un solo uso, no el token compartido: el
    # móvil lo canjea por el suyo (`POST /api/link/pair`). La FORMA del enlace no
    # cambia a propósito —`movil/MainActivity.java` copia el valor de `token` a
    # cada dirección de respaldo y la página lo lee igual—, solo cambia QUÉ es.
    link = (f"{esquema}://{host}/m?host={host}&token={pairing_code()}"
            + (f"&alt={alternativas}" if alternativas else ""))
    return {"tunnel": alive, "url": _state["url"], "error": _state["error"],
            "adoptado": bool(_state["adoptado"]),
            "tunel_nota": ("Reutilizo el túnel que seguía vivo del arranque anterior: "
                           "la dirección NO ha cambiado, no hace falta re-escanear el QR."
                           if _state["adoptado"] and _state["url"]
                           else ("Túnel nuevo: la dirección ha cambiado, hay que "
                                 "re-escanear el QR." if _state["url"] else "")),
            "lan": f"{lan_ip()}:8177", "link": link,
            "devices": devices(), "paired": len(_devices),
            # Los revocables, uno por uno (incluye los apagados y los «antiguos»).
            # `devices`/`paired` se quedan como estaban: son «los conectados ahora»
            # y el HUD ya los usa para el contador del botón 📱.
            "vinculados": vinculados(),
            "via": via, "estable": bool(principal.get("estable")),
            "hosts": dirs, "nombre_local": nombre_local(),
            "tailscale": tailscale_status()}


# ------------------------------------------------------------------ QR
def qr_png(data: str) -> bytes:
    """PNG del QR (qrcode + pillow; run.bat los instala)."""
    import qrcode
    img = qrcode.make(data, box_size=9, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
