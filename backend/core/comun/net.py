"""
nexus — Cliente HTTP compartido (pooling + keep-alive).

Antes CADA petición (LLM, TTS, web, Spotify…) hacía
`async with httpx.AsyncClient(...) as cli:` — es decir, abría una conexión
TCP + handshake TLS NUEVA y la tiraba al terminar. Con las APIs remotas
(OpenAI, Anthropic, Gemini) ese handshake TLS es la mayor parte de la latencia,
y se repetía en cada mensaje.

Aquí mantenemos UN cliente reutilizable por event-loop con un pool de conexiones
persistentes (keep-alive): la segunda llamada al mismo host reaprovecha la
conexión ya abierta. Cada petición sigue pasando su propio `timeout=`, así que
un sondeo rápido (2 s) y una generación larga (180 s) conviven sin problema.

Se cierra limpio al apagar la app (net.aclose() en el lifespan).

DESTINO SEGURO (SEC-11 de la auditoría, roadmap P3-1)
-----------------------------------------------------
Todo lo de arriba son llamadas cuyo destino YA ESTÁ DECIDIDO por nexus: la URL
que el operador tiene en ⚙, la del túnel, el Ollama de su equipo. Ahí no se
toca nada: `remote.py` sondea 127.0.0.1:8177 A PROPÓSITO para saber si nexus
está vivo, y el proveedor local habla con localhost porque es su casa.

El problema es el otro camino: el texto que llega por un canal no confiable
(un flujo de n8n, una web que se acaba de leer, un resultado de búsqueda) puede
convertirse en una URL —`vigila la web http://169.254.169.254/…`— y entonces
nexus pediría ESO con la cara del operador: la API de su propio equipo, los
metadatos del proveedor de la nube, el router, el NAS del vecino.

Por eso las funciones de abajo (`asegurar_destino`, `motivo_destino`,
`rechazo_destino`, `safe_get`) son la ÚNICA puerta para esas URLs:

  * solo http y https (nunca `file:`, `gopher:`, ni transportes raros);
  * nada de llevar `usuario:clave@` dentro del enlace (ver `host_visible`);
  * el destino no puede ser loopback, link-local/metadatos, RFC1918, CGNAT de
    Tailscale (100.64/10), multicast, 0.0.0.0/:: ni ningún rango reservado, y
    un NOMBRE que resuelva a cualquiera de ellos se rechaza igual que la IP;
  * si el nombre no se puede resolver, no se pide: no se sabe a dónde iría;
  * CADA redirección se revalida. `safe_get` pide con `follow_redirects=False`
    y hace su propio bucle de saltos; el cliente compartido de arriba sigue
    siguiendo redirecciones porque sus destinos no vienen de un canal.

Las negativas van en español, se pueden enseñar tal cual al operador y NUNCA
llevan credenciales: solo el host (`host_visible`).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx

# Pool: hasta 20 conexiones vivas en espera, 40 simultáneas; caducan a los 30 s.
_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=40,
                       keepalive_expiry=30.0)

# Un cliente por event-loop (un AsyncClient está atado al loop en que nació).
_clients: "dict[object, httpx.AsyncClient]" = {}


def client() -> httpx.AsyncClient:
    """Cliente httpx compartido y reutilizable para el loop en curso.

    Debe llamarse desde código async (hay un loop corriendo). Cada `.get/.post`
    pasa su propio `timeout=`, que prevalece sobre el del cliente."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    cli = _clients.get(loop)
    if cli is None or cli.is_closed:
        cli = httpx.AsyncClient(limits=_LIMITS, follow_redirects=True,
                                timeout=httpx.Timeout(60.0))
        _clients[loop] = cli
    return cli


async def aclose() -> None:
    """Cierra todas las conexiones del pool (al apagar la app)."""
    for cli in list(_clients.values()):
        try:
            if not cli.is_closed:
                await cli.aclose()
        except Exception:
            pass
    _clients.clear()


# ═══════════════════════════ destino seguro (SEC-11) ═══════════════════════════
_ESQUEMAS = ("http", "https")

# Rangos que NO se abren NUNCA desde una URL que viene de un canal. Se nombran
# uno a uno (en vez de confiar solo en `is_global`) para poder decirle al
# operador QUÉ es lo que se ha rechazado; `is_global` queda de red de seguridad
# para los rangos que Python añada en el futuro.
_RANGOS = (
    ("0.0.0.0/8", "la dirección comodín de este equipo (0.0.0.0)"),
    ("10.0.0.0/8", "una dirección de red privada"),
    ("100.64.0.0/10", "una dirección de red privada (CGNAT: Tailscale y compañía)"),
    ("127.0.0.0/8", "tu propio equipo (loopback)"),
    ("169.254.0.0/16", "una dirección de enlace local (metadatos de la nube)"),
    ("172.16.0.0/12", "una dirección de red privada"),
    ("192.0.0.0/24", "una dirección reservada"),
    ("192.168.0.0/16", "una dirección de red privada"),
    ("198.18.0.0/15", "una dirección de pruebas de red"),
    ("224.0.0.0/4", "una dirección de multicast"),
    ("240.0.0.0/4", "una dirección reservada"),
    ("::/128", "la dirección sin especificar (::)"),
    ("::1/128", "tu propio equipo (loopback IPv6)"),
    ("fc00::/7", "una dirección de red privada (IPv6 ULA)"),
    ("fe80::/10", "una dirección de enlace local IPv6"),
    ("ff00::/8", "una dirección de multicast IPv6"),
)
_REDES_NEGADAS = tuple((ipaddress.ip_network(red), motivo) for red, motivo in _RANGOS)

# Nombres que son internos POR DEFINICIÓN: no hace falta resolverlos para saber
# que no se abren (y así la negativa dice la verdad aunque el DNS no conteste).
_NOMBRES_NEGADOS = {
    "localhost": "tu propio equipo (loopback)",
    "localhost.localdomain": "tu propio equipo (loopback)",
    "ip6-localhost": "tu propio equipo (loopback)",
    "ip6-loopback": "tu propio equipo (loopback)",
    "metadata": "un servicio de metadatos interno",
    "metadata.goog": "un servicio de metadatos interno",
    "metadata.google.internal": "un servicio de metadatos interno",
    "instance-data": "un servicio de metadatos interno",
}
# Dominios que solo existen dentro de una red local (mDNS, LAN doméstica).
_SUFIJOS_LOCALES = (".localhost", ".local", ".internal", ".home.arpa",
                    ".lan", ".intranet")

# Sección «red» de config/umbrales.json. Lo de aquí es la reserva: sin archivo
# (o con el JSON roto) el tope es el de siempre y nadie se queda sin abrir nada.
_UMBRALES_RED_RESERVA = {"max_redirecciones": 5}
_REDIRECCIONES = (301, 302, 303, 307, 308)


class DestinoNoPermitido(RuntimeError):
    """La URL (o una redirección suya) no es un destino público http/https.

    El mensaje va en español, se puede enseñar tal cual y NUNCA lleva
    credenciales: solo el host, sin `usuario:clave@`.
    """


def _umbrales_red() -> dict:
    """Lee la sección «red» de config/umbrales.json sobre los valores de reserva."""
    vals = dict(_UMBRALES_RED_RESERVA)
    try:
        from .config import CONFIG_DIR          # import perezoso: net no depende de config
        f = Path(CONFIG_DIR) / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("red") or {}
            v = leido.get("max_redirecciones")
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 20:
                vals["max_redirecciones"] = v
    except Exception:                            # noqa: BLE001
        pass
    return vals


def _direcciones(host: str) -> list[str]:
    """Direcciones a las que resuelve `host` (una sola consulta, sin caché).

    Es la costura que las pruebas doblan: en producción es `getaddrinfo`, que le
    pregunta al resolver del sistema. Sin resultados es una excepción, y quien
    la llama lo trata como negativa (no se pide a ciegas).
    """
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(i[4][0]) for i in infos})


def host_visible(url: str) -> str:
    """El destino de una URL SIN credenciales: nunca `usuario:clave@host`.

    Todo lo que se escribe en un mensaje o en un registro pasa por aquí: una URL
    puede llevar dentro la contraseña de una base de datos (o de un básico HTTP)
    y esa contraseña no se repite ni en una negativa.
    """
    try:
        p = urlsplit(str(url or "").strip())
        host = unquote(p.hostname or "").strip()      # el %2e es un punto para el clasificador
        puerto = p.port
    except Exception:                            # noqa: BLE001
        return "(enlace ilegible)"
    if not host:
        return "(sin destino)"
    return f"{host}:{puerto}" if puerto else host


def _destino_vacio(url: str) -> tuple[str, str]:
    """(esquema, host) normalizados de una URL, sin lanzar por basura."""
    try:
        p = urlsplit(str(url or "").strip())
        return (p.scheme or "").lower(), unquote(p.hostname or "").strip()
    except Exception:                            # noqa: BLE001
        return "", ""


def _motivo_ip(ip) -> str:
    """'' si la dirección es de internet; si no, qué es (para decirlo en español)."""
    for red, motivo in _REDES_NEGADAS:
        if ip.version == red.version and ip in red:
            return motivo
    if ip.is_loopback:
        return "tu propio equipo (loopback)"
    if ip.is_link_local:
        return "una dirección de enlace local (metadatos de la nube)"
    if ip.is_multicast:
        return "una dirección de multicast"
    if not ip.is_global:
        return "una dirección que no es de internet"
    return ""


def motivo_destino(url: str) -> str:
    """'' si esa URL se puede pedir; si no, QUÉ le pasa (frase corta, en español).

    No lanza y no pide nada: clasifica. Es lo que usan los llamadores que solo
    quieren explicar el motivo (`vigilancias` al avisar de un vigilante roto).
    """
    texto = str(url or "").strip()
    if not texto:
        return "el enlace está vacío"
    esquema, host = _destino_vacio(texto)
    if esquema not in _ESQUEMAS:
        return f"el esquema «{esquema or 'ninguno'}» no es http ni https"
    try:
        if "@" in urlsplit(texto).netloc:
            return ("lleva un usuario y una contraseña dentro del enlace, "
                    "y un enlace así no se abre")
    except Exception:                            # noqa: BLE001
        return "no es un enlace que se pueda leer"
    host = host.rstrip(".")
    if not host:
        return "no dice a qué equipo hay que pedírselo"
    nombre = host.casefold()
    if nombre in _NOMBRES_NEGADOS:
        return _NOMBRES_NEGADOS[nombre]
    if any(nombre.endswith(sufijo) for sufijo in _SUFIJOS_LOCALES):
        return "un nombre que solo existe dentro de una red local"
    try:
        ip = ipaddress.ip_address(nombre)
    except ValueError:
        ip = None
    if ip is not None:
        return _motivo_ip(ip)
    try:
        direcciones = _direcciones(nombre)
    except Exception:                            # noqa: BLE001
        return "no consigo resolver ese dominio ahora mismo"
    if not direcciones:
        return "no consigo resolver ese dominio ahora mismo"
    for texto_ip in direcciones:
        try:
            ip = ipaddress.ip_address(str(texto_ip).split("%")[0])   # sin la zona «%eth0»
        except ValueError:
            return "una dirección que no sé leer"
        motivo = _motivo_ip(ip)
        if motivo:
            return motivo
    return ""


def rechazo_destino(url: str) -> str:
    """La negativa completa (mensaje en español) o '' si esa URL se puede pedir."""
    motivo = motivo_destino(url)
    if not motivo:
        return ""
    return (
        f"No voy a abrir «{host_visible(url)}»: {motivo}. Solo abro enlaces públicos "
        "por http/https: tu propio equipo, tu red local y los servicios internos se "
        "quedan fuera, porque si el enlace viene de una web, de un resultado de "
        "búsqueda o de un mensaje, abrirlo sería usar nexus como puente hacia ellos."
    )


def asegurar_destino(url: str) -> str:
    """Valida una URL antes de pedirla; devuelve la URL tal cual si vale.

    Lanza `DestinoNoPermitido` si el esquema no es http/https, si el enlace lleva
    usuario:contraseña o si el destino (o CUALQUIERA de las direcciones a las que
    resuelve un nombre) es el propio equipo, la red local, un rango reservado o
    un servicio de metadatos.
    """
    motivo = motivo_destino(url)
    if motivo:
        raise DestinoNoPermitido(rechazo_destino(url))
    return url


async def safe_get(url: str, *, headers=None, timeout=None,
                   max_redirecciones: int | None = None) -> httpx.Response:
    """GET a una URL que viene de fuera, con la guarda revalidada en CADA salto.

    Se pide con `follow_redirects=False` y el bucle de saltos es explícito a
    propósito: el cliente compartido sigue redirecciones por su cuenta, así que
    dejar que él las siguiera abriría el destino final sin que esta función lo
    viera (un host público que responde 302 hacia 169.254.169.254 es el ataque
    de manual). El tope de saltos sale de config/umbrales.json («red».
    `max_redirecciones`, 5 por defecto).
    """
    tope = (_umbrales_red()["max_redirecciones"] if max_redirecciones is None
            else max(0, int(max_redirecciones)))
    actual = str(url or "").strip()
    for _salto in range(tope + 1):
        await asyncio.to_thread(asegurar_destino, actual)   # el DNS no bloquea el loop
        kw: dict = {"follow_redirects": False}
        if headers is not None:
            kw["headers"] = headers
        if timeout is not None:
            kw["timeout"] = timeout
        r = await client().get(actual, **kw)
        siguiente = ""
        if r.status_code in _REDIRECCIONES:
            siguiente = str(r.headers.get("location") or "").strip()
        if not siguiente:
            return r
        actual = urljoin(actual, siguiente)
    raise DestinoNoPermitido(
        f"No voy a abrir «{host_visible(url)}»: me manda de redirección en redirección "
        f"más de {tope} veces, y eso no es una página que se pueda leer."
    )
