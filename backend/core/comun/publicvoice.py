"""
nexus — LA VOZ PÚBLICA (specs v24, FASES 1-4).

Regla de arquitectura fijada con Adri: **el usuario solo interactúa con nexus.**
No tiene por qué enterarse de si por dentro hay un subagente, un gateway, una
cola, un proveedor o un modelo distinto. Todo eso es fontanería: va a los logs
y al panel de diagnóstico, nunca al chat.

Este módulo hace tres cosas:

  1. `sanitize()` — última barrera antes de que un texto llegue al chat. Traduce
     o elimina lo interno (Hermes, gateway, worker, endpoint, puerto, HTTP 429,
     stack traces, claves…). Se aplica en el bus de eventos, así que da igual qué
     módulo emita: no se escapa nada.
  2. `clasificar_error()` — un 401 NO es un rate limit y un 404 de modelo NO es
     «el gateway está apagado». Cada familia de error tiene su categoría, si se
     puede reintentar y QUÉ se le dice al usuario en cristiano.
  3. `frase_inicio()` — el acuse de recibo cuando algo se pone en marcha, con
     variedad real: la misma frase repetida sonaba a robot.
"""
from __future__ import annotations

import hashlib
import re

# ── 1. TÉRMINOS QUE NUNCA SALEN AL CHAT ───────────────────────────────────────
# (orden importante: primero las frases largas, luego las palabras sueltas)
_REEMPLAZOS: list[tuple[str, str]] = [
    # Delegación: nexus habla SIEMPRE en primera persona
    (r"\b(?:se\s+lo\s+)?(?:he\s+|voy\s+a\s+)?deleg(?:o|ado|ar)\b[^.\n]{0,25}\b(?:en\s+|a\s+)?hermes\b",
     "me pongo con ello"),
    (r"\bhermes\s+(?:se\s+encargar[aá]|lo\s+har[aá]|est[aá]\s+trabajando|est[aá]\s+en\s+ello)\b",
     "estoy en ello"),
    (r"\b(?:esperar[eé]|espero)\s+a\s+que\s+hermes\s+termine\b", "te aviso al terminar"),
    (r"\bhermes\s+ha\s+(?:terminado|completado)\s+el\s+encargo\b", "he terminado"),
    (r"\bel\s+(?:agente\s+)?(?:secundario|subagente|ejecutor)\b", "el trabajo"),
    (r"«?diagn[oó]stica\s+(?:a\s+)?hermes»?", "«diagnostica el sistema»"),
    (r"\bencargos?\s+a\s+hermes\b", "trabajos"),
    (r"\bencargo\b", "trabajo"),
    (r"\bhermes\s+#(\d+)", r"#\1"),
    (r"\bhermes\b", "el sistema"),
    # Infraestructura
    (r"\bel\s+gateway\s+de\s+\w+\b", "el servicio"),
    (r"\bgateways?\b", "el servicio"),
    (r"\bworkers?\b", "el proceso"),
    (r"\bcolas?\s+internas?\b", "la lista de trabajos"),
    (r"\bendpoints?\b", "el servicio"),
    (r"\blocalhost(?::\d+)?\b", "el equipo"),
    (r"\bhttp://127\.0\.0\.1:\d+\b", "el equipo"),
    (r"\bpuerto\s+\d+\b", "el equipo"),
    (r"\bapi[\s_-]?keys?\b", "la configuración"),
    (r"\b(?:rpm|tpm)\b", "el límite"),
    # Errores crudos
    (r"\bHTTP\s+\d{3}\b", "un problema"),
    (r"\b(?:Runtime|Value|Type|Key|Connection|Timeout)Error\b", "un fallo"),
    (r"\bTraceback\s+\(most\s+recent\s+call\s+last\)[\s\S]*", "un fallo interno"),
    (r"\bdata[\\/][\w\\/.-]*\.log\b", "el registro"),
]
_RX = [(re.compile(p, re.IGNORECASE), r) for p, r in _REEMPLAZOS]

# Términos que NUNCA deben aparecer (los usa la prueba automática, T17)
PROHIBIDOS = ("hermes", "gateway", "worker", "cola interna", "endpoint",
              "localhost", "api key", "traceback", "rpm", "tpm", "http 4", "http 5")


# Oraciones ENTERAS que se caen: si una frase habla de infraestructura, no se
# parchea palabra a palabra (quedaban engendros tipo «su el servicio está
# apagado») — se quita la frase completa.
_FRASE_FUERA = re.compile(
    r"[^.\n]*\b(?:gateway|worker|endpoint|localhost|puerto\s+\d+|api[\s_-]?key|"
    r"traceback|stack\s*trace|\brpm\b|\btpm\b|hermes_gateway)\b[^.\n]*\.?",
    re.IGNORECASE)
# Sintagmas de delegación: « a Hermes», « para Hermes», « de Hermes»…
# Lo que se contesta cuando el mensaje era fontanería de arriba abajo y no queda
# nada que enseñar. Ni inventa un resultado ni deja al operador sin respuesta.
# No dice «estoy en ello» ni «ya está»: el mensaje original podía ser un fallo,
# y reclamar progreso donde hubo error es justo lo que este proyecto no hace.
_SIN_NADA_QUE_ENSEÑAR = ("De esto no te puedo enseñar el detalle: es interno y "
                         "queda en el registro. Dime «diagnostica el sistema» "
                         "si quieres que lo revise.")

_SINTAGMA_HERMES = re.compile(
    r"\s*(?:,\s*)?\b(?:a|al|para|de|del|con|en|por)\s+hermes\b", re.IGNORECASE)

# Direcciones enteras, de una pieza. Van ANTES que nada porque sus puntos
# rompen el recorte por oraciones (`_FRASE_FUERA` usa `[^.\n]*`).
_RX_DIRECCION = re.compile(
    r"\b(?:https?://)?(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d+)?(?:/\S*)?",
    re.IGNORECASE)


def sanitize(texto: str) -> str:
    """Deja el texto listo para el chat: sin arquitectura interna a la vista.

    Es una RED DE SEGURIDAD, no la solución: cada mensaje debería nacer ya
    limpio. Pero si a alguien se le escapa, aquí no pasa."""
    if not texto:
        return texto
    out = str(texto)
    # PRIMERO las direcciones. `_FRASE_FUERA` corta la oración con `[^.\n]*`, y
    # los puntos de una IP la parten por la mitad: «el gateway responde en
    # http://127.0.0.1:8642» se quedaba en «0.0.1:8642», que es peor que la
    # frase entera porque parece un dato y no lo es.
    out = _RX_DIRECCION.sub("el equipo", out)
    for rx, rep in _RX[:5]:            # luego las frases de delegación
        out = rx.sub(rep, out)
    out = _FRASE_FUERA.sub("", out)    # fuera las oraciones de fontanería
    out = _SINTAGMA_HERMES.sub("", out)
    for rx, rep in _RX[5:]:
        out = rx.sub(rep, out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    out = re.sub(r"\(\s*\)|«\s*»", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = out.strip()
    # SUELO. Si el mensaje entero hablaba de fontanería, `_FRASE_FUERA` se lo
    # lleva todo y el operador se queda mirando una respuesta VACÍA, que es peor
    # que la fuga: parece que nexus se ha colgado. Pasó con «se lo he delegado a
    # Hermes, el gateway responde en http://127.0.0.1:8642»: no quedaba nada.
    if not out and str(texto).strip():
        return _SIN_NADA_QUE_ENSEÑAR
    return out


def tiene_fugas(texto: str) -> list[str]:
    """Qué términos internos se han colado (para las pruebas y el linter de voz)."""
    t = (texto or "").lower()
    return [p for p in PROHIBIDOS if p in t]


# ── 2. CLASIFICACIÓN DE ERRORES ───────────────────────────────────────────────
# categoría → (reintentable, mensaje para el usuario)
_CATS: dict[str, tuple[bool, str]] = {
    "rate_limit": (True, "He tenido que esperar más de la cuenta y no he podido terminar "
                         "la consulta. Puedes volver a pedírmelo en un minuto."),
    "saldo": (False, "No he podido completar la consulta: la cuenta que uso para esto no "
                     "tiene crédito disponible ahora mismo."),
    "auth": (False, "No he podido completar la consulta porque me falta acceso al servicio "
                    "que necesito. Revísalo en la configuración cuando puedas."),
    "modelo": (False, "No he podido completar la consulta con la configuración actual. "
                      "Prueba a elegir otra opción en los ajustes."),
    "proveedor": (True, "El servicio que necesitaba está dando problemas ahora mismo. "
                        "No he podido terminarlo; puedes volver a intentarlo."),
    "infra": (True, "No he podido poner en marcha lo que hacía falta para esta tarea. "
                    "Inténtalo otra vez, por favor."),
    "config": (False, "No he podido completar la tarea: algo de mi configuración no está "
                      "bien puesto. Dime «diagnostica el sistema» y lo miro."),
    "desconocido": (True, "No he podido completar la operación. No se ha realizado ningún "
                          "cambio."),
}

_PISTAS = [
    ("saldo", r"insufficient[_\s]quota|exceeded\s+your\s+current\s+quota|billing|"
              r"payment\s+required|no\s+credit|saldo"),
    ("auth", r"\b401\b|\b403\b|invalid[_\s]api[_\s]key|incorrect\s+api\s+key|"
             r"unauthorized|missing\s+authentication|must\s+be\s+verified|"
             r"permission|revoked"),
    ("modelo", r"\b404\b|model[_\s]not[_\s]found|does\s+not\s+exist|"
               r"unsupported[_\s]model|deprecated|no\s+such\s+model"),
    ("rate_limit", r"\b429\b|rate[_\s]?limit|too\s+many\s+requests|"
                   r"slow\s+down|requests\s+per\s+(?:minute|second)"),
    ("proveedor", r"\b5\d\d\b|bad\s+gateway|service\s+unavailable|overloaded|"
                  r"internal\s+server\s+error"),
    ("infra", r"connection\s+(?:refused|reset|aborted)|no\s+pude\s+arrancar|"
              r"not\s+running|timed?\s*out|timeout|winerror\s+10061"),
    ("config", r"config|yaml|settings|no\s+configurad|falta\s+la\s+clave"),
]
_PISTAS_RX = [(c, re.compile(p, re.IGNORECASE)) for c, p in _PISTAS]


def clasificar_error(detalle: str, status: int = 0) -> dict:
    """Traduce un error técnico a algo accionable.

    Devuelve {categoria, reintentable, mensaje, tecnico}. El campo `tecnico` es
    para el LOG y el panel de diagnóstico: JAMÁS para el chat."""
    texto = f"{status or ''} {detalle or ''}".strip()
    cat = "desconocido"
    # El código HTTP manda sobre el texto: un 401 no puede leerse como rate limit
    # solo porque el cuerpo mencione «limit» (specs v24, T7).
    if status == 429:
        cat = "rate_limit"
    elif status in (401, 403):
        cat = "auth"
    elif status == 402:
        cat = "saldo"
    elif status == 404:
        cat = "modelo"
    elif status and 500 <= status < 600:
        cat = "proveedor"
    else:
        for c, rx in _PISTAS_RX:
            if rx.search(texto):
                cat = c
                break
    reintentable, mensaje = _CATS[cat]
    return {"categoria": cat, "reintentable": reintentable, "mensaje": mensaje,
            "tecnico": texto[:500]}


def mensaje_fallo(detalle: str, status: int = 0, intentos: int = 0) -> str:
    """El ÚNICO mensaje que ve el usuario cuando algo no ha salido (T6/T8)."""
    info = clasificar_error(detalle, status)
    extra = (" No se ha realizado ningún cambio."
             if "ningún cambio" not in info["mensaje"] else "")
    if intentos > 1 and info["reintentable"]:
        return (f"No he podido completar la consulta después de varios intentos."
                f"{extra}")
    return info["mensaje"] + extra


# ── 3. ACUSES DE RECIBO VARIADOS ──────────────────────────────────────────────
_FRASES: dict[str, tuple[str, ...]] = {
    "consulta": (
        "Voy a hacer la consulta. Mientras tanto, puedes pedirme otra cosa.",
        "Me pongo a buscarlo. Sigue a lo tuyo, que te aviso al terminar.",
        "Estoy con la consulta. Te devuelvo el resultado en cuanto lo tenga.",
        "Ya estoy mirándolo. Puedes seguir preguntándome lo que necesites.",
    ),
    "revision": (
        "Estoy revisándolo. Te aviso cuando tenga el resultado.",
        "Me pongo a repasarlo. Sigue usándome mientras tanto.",
        "Lo estoy comprobando. Te lo cuento en cuanto termine.",
    ),
    "archivo": (
        "Me pongo con el documento. Puedes seguir usándome mientras lo preparo.",
        "Empiezo a prepararlo. Te digo dónde lo dejo cuando esté.",
        "Ya estoy con el archivo. Te aviso al guardarlo.",
    ),
    "analisis": (
        "Ya estoy analizando la información. Cuando termine te muestro las conclusiones.",
        "Me pongo con el análisis. Te lo resumo al acabar.",
        "Estoy con ello. En cuanto tenga las conclusiones te las paso.",
    ),
    "generico": (
        "Me pongo con ello. ¿Necesitas que te ayude con alguna otra cosa mientras tanto?",
        "Ya está en marcha. Mientras tanto, puedes pedirme otra cosa.",
        "Voy a ello. Te aviso en cuanto lo tenga.",
        "Empiezo ahora mismo. Sigue a lo tuyo, que yo te canto el resultado.",
    ),
}
_COLA: tuple[str, ...] = (
    "Lo añado a lo que ya tengo en marcha. Puedes continuar con otra cosa.",
    "Va a la lista, que ya estoy con otras cosas. Te aviso según terminen.",
    "Lo apunto con el resto de trabajos en curso. Sigue tú a lo tuyo.",
)

_RX_TIPO = [
    ("archivo", r"\b(documento|archivo|fichero|informe|docx|pdf|md|escrib|redact|guarda)\b"),
    ("analisis", r"\b(analiza|an[aá]lisis|compara|comparativa|eval[uú]a|revisa\s+los\s+datos)\b"),
    ("revision", r"\b(revisa|comprueba|verifica|audita|repasa)\b"),
    ("consulta", r"\b(busca|investiga|consulta|averigua|mira|ent[eé]rate|encuentra)\b"),
]
_RX_TIPO = [(t, re.compile(p, re.IGNORECASE)) for t, p in _RX_TIPO]

_ultimas: list[str] = []          # para no repetir la frase de hace dos mensajes


def tipo_tarea(orden: str) -> str:
    for t, rx in _RX_TIPO:
        if rx.search(orden or ""):
            return t
    return "generico"


def frase_inicio(orden: str, activas: int = 0) -> str:
    """Acuse variado y honesto: sin plazos inventados y sin fontanería."""
    if activas >= 1:
        pool = _COLA
    else:
        pool = _FRASES.get(tipo_tarea(orden), _FRASES["generico"])
    libres = [f for f in pool if f not in _ultimas] or list(pool)
    # Determinista pero repartido: depende de la orden, no del azar (así los
    # tests son reproducibles y aun así no sale siempre la primera plantilla).
    idx = int(hashlib.sha1((orden or "").encode("utf-8")).hexdigest(), 16) % len(libres)
    frase = libres[idx]
    _ultimas.append(frase)
    del _ultimas[:-3]
    return frase


# ── PROGRESO INVENTADO ────────────────────────────────────────────────────────
# Lo que dice alguien que está trabajando: «estoy en ello», «dame un segundo»,
# «ahora mismo lo hago», «en cuanto lo tenga te digo». Dicho por el modelo cuando
# NO hay ningún trabajo en marcha, es mentira, y de la peor clase: el operador
# espera. En una sesión real esto tuvo a Adrián diez minutos esperando algo que
# nadie estaba haciendo, con la respuesta cambiando de excusa cada vez.
#
# Prometer trabajo es un acto, no una forma de hablar: solo puede decirlo quien
# tiene un trabajo encolado de verdad.
_PROMESA_DE_TRABAJO = re.compile(
    r"\b(?:estoy\s+en\s+ello|estoy\s+(?:recopilando|reuniendo|revisando|repasando|"
    r"buscando|localizando|mirando|preparando|comprobando)\b|"
    r"dame\s+un\s+(?:segundo|momento|instante|minuto|nanosegundo)|"
    r"ahora\s+mismo\s+(?:lo\s+|los\s+|las\s+|te\s+)?(?:hago|busco|miro|reviso|lo\s+veo)|"
    r"en\s+cuanto\s+(?:\w+\s+){0,2}tenga\b|"
    r"enseguida\s+te\s+(?:lo|los|las|la)\s+(?:digo|paso|cuento)|"
    r"voy\s+a\s+(?:ir\s+)?(?:mirar|buscar|revisar|repasar)(?:lo|los|las)?\b|"
    r"te\s+(?:lo|los|las)\s+digo\s+en\s+(?:un|nada))",
    re.IGNORECASE)

_NO_LO_ESTOY_HACIENDO = ("No lo estoy haciendo: esa orden no me ha llegado a "
                         "nada que sepa ejecutar. Dímelo de otra forma.")


def promete_trabajo(texto: str) -> bool:
    """¿El texto dice que está trabajando en algo?"""
    return bool(_PROMESA_DE_TRABAJO.search(texto or ""))


def sin_progreso_inventado(texto: str, hay_trabajo: bool) -> str:
    """Deja el texto tal cual si hay un trabajo de verdad; si no lo hay, quita la
    promesa y dice la verdad.

    Se recortan las FRASES que prometen, no el mensaje entero: lo que el modelo
    haya contestado además puede ser útil. Si al quitarlas no queda nada, se
    contesta que no lo está haciendo."""
    if hay_trabajo or not texto or not promete_trabajo(texto):
        return texto
    frases = re.split(r"(?<=[.!?\n])\s+", texto)
    limpio = " ".join(f for f in frases if not promete_trabajo(f)).strip()
    return limpio or _NO_LO_ESTOY_HACIENDO


def reset_frases() -> None:
    _ultimas.clear()


# ── 4. EL EJECUTOR TAMBIÉN ES FONTANERÍA ──────────────────────────────────────
# Para el operador, el agente es SIEMPRE nexus. Que por dentro un encargo lo
# resuelva un ejecutor secundario es arquitectura, y la arquitectura no sale al
# chat ni al panel.
#
# INCIDENTE (02/08/2026): el texto salía limpio, pero la tarjeta de Multitarea
# del HUD pinta el agente de cada trabajo —`frontend/js/command.js`, la línea
# `jobc-m`— y ahí se leía «hermes» tal cual. El saneador solo miraba los campos
# de texto (reply, result, error, title), no quién lo ejecutaba.
_EJECUTORES_INTERNOS = {"hermes", "gateway", "worker", "subagente", "sub"}


def limpia_trabajo(job: dict) -> dict:
    """Devuelve el trabajo listo para el panel: ejecutor enmascarado y textos limpios.

    Tres campos delatan al ejecutor y ninguno es texto de respuesta, así que el
    saneador de siempre no los miraba:
      * `agent`    — lo pinta la tarjeta de Multitarea del HUD.
      * `provider` — acompaña a cada mensaje de chat.
      * `skill`    — igual, y además marca el módulo en el panel de nodos.

    Y los textos del propio trabajo (`title`, `request`, `progress_note`), que
    van dentro de la lista y por eso se escapaban del saneo de arriba.

    No toca el original: el registro y la auditoría siguen guardando quién lo
    hizo de verdad, que para diagnosticar hace falta.
    """
    if not isinstance(job, dict):
        return job
    salida = None
    for campo in ("agent", "provider", "skill"):
        if str(job.get(campo) or "").strip().lower() in _EJECUTORES_INTERNOS:
            salida = salida if salida is not None else dict(job)
            salida[campo] = "nexus"
    for campo in ("title", "request", "progress_note"):
        crudo = job.get(campo)
        if crudo:
            limpio = sanitize(str(crudo))
            if limpio != crudo:
                salida = salida if salida is not None else dict(job)
                salida[campo] = limpio
    return salida if salida is not None else job
