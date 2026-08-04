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
"""
from __future__ import annotations

import asyncio

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
