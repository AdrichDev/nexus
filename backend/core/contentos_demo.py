"""
nexus — CONTENT OS: los datos de MENTIRA, aparte y con su nombre en la puerta.

POR QUÉ ESTÁ ESTO EN UN FICHERO PROPIO (01/08/2026). Vivía dentro de
`contentos.py` como `_demo_metrics()`, y `dashboard()` lo enchufaba con un `or`
silencioso: `await _ig_metrics() or _demo_metrics()`. Resultado: los 12.840
seguidores de aquí abajo salían por el HUD exactamente igual que si vinieran de
la Graph API, sin ninguna marca. Nadie mentía a propósito; simplemente no había
manera de distinguirlo mirando el payload.

Sacarlo aquí compra tres cosas:
  * `contentos.py` se queda sin un solo literal de métrica, así que un test
    puede leer el módulo y comprobarlo (nadie los mete de vuelta sin que salte);
  * `metricas()` estampa el origen EN EL PROPIO RETORNO, así que el sobre no
    depende de que alguien se acuerde río abajo;
  * el día que sobre, se retira de un tirón: `rm` de este fichero y la rama que
    lo llama.

NO se borra hoy: un panel vacío no enseña qué se gana conectando la cuenta.
Se enseña, pero DICIENDO que es de mentira.
"""
from __future__ import annotations

from .procedencia import DEMOSTRACION


def metricas() -> dict:
    """El dataset de demostración, etiquetado como tal desde el origen."""
    base = 12840
    series = [base - 420 + int(420 * (i / 29) + 55 * ((i * 7) % 5 - 2)) for i in range(30)]
    reels = [
        {"name": "El error que mata tus automatizaciones", "type": "REELS", "eng": 1840,
         "likes": 1620, "comments": 220, "when": "07-12", "hour": 19, "reach": 24100},
        {"name": "3 tareas que NO deberías automatizar", "type": "CAROUSEL", "eng": 1210,
         "likes": 1090, "comments": 120, "when": "07-09", "hour": 13, "reach": 15600},
        {"name": "POV: la IA gestiona tu agenda", "type": "REELS", "eng": 2260,
         "likes": 1980, "comments": 280, "when": "07-06", "hour": 20, "reach": 31200},
        {"name": "Lo que aprendí automatizando mi negocio", "type": "REELS", "eng": 980,
         "likes": 860, "comments": 120, "when": "07-03", "hour": 12, "reach": 12800},
        {"name": "Mi stack de herramientas 2026", "type": "CAROUSEL", "eng": 1520,
         "likes": 1360, "comments": 160, "when": "06-30", "hour": 19, "reach": 18900},
        {"name": "Automatiza tu Instagram en 5 pasos", "type": "REELS", "eng": 1680,
         "likes": 1490, "comments": 190, "when": "06-27", "hour": 21, "reach": 22400},
    ]
    return {"username": "marca.personal", "followers": base, "media_count": 214,
            "reach_month": 184200, "followers_series": series, "posts": reels,
            # `real` es el campo histórico que mira `dashboard()`; `origen` es el
            # que viaja hasta el sobre. Se mantienen los dos hasta que la Fase 2
            # (entrega B) rehaga el contrato del payload.
            "real": False, "origen": DEMOSTRACION}
