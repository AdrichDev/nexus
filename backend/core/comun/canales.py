"""
nexus — Qué puede ejecutar cada canal de entrada (matriz canal × efecto).

Un canal NO es una persona. El texto que entra por `POST /api/n8n` lo escribe
quien llame al webhook (un flujo de n8n, un nodo de WhatsApp, cualquiera que
tenga el secreto compartido) y no es una orden del operador. Y el enrutador de
nexus es un montón de regexes: cualquier frase que case ejecuta la skill DE
VERDAD — manda un correo, apaga la tele, borra una tarea de Drive. Por eso,
desde la auditoría de seguridad (SEC-01 / SEC-06, roadmap P1-1), cada canal
declara qué efectos permite, y lo que no está declarado NO se ejecuta.

La política es DENEGAR POR DEFECTO. Un canal restringido solo ejecuta los pares
`carpeta/intent` de su lista blanca, y solo por el enrutador de regexes: lo que
no casa con ninguna regex se rechaza en vez de caer al planificador del modelo o
a la delegación de Hermes, que es justo donde nexus se inventa cosas. La memoria
explícita («apunta que…»), las cadenas, la multi-orden y el trabajo en segundo
plano tampoco: son escrituras, y un canal que no es el operador no escribe en su
memoria.

Desde el roadmap P2-1 (ARQ-01 / ARQ-03, task T8) el módulo habla además en el
vocabulario de EFECTOS, que es lo que decide una skill:

    read           lee y contesta (no cambia nada)
    write_local    escribe en el equipo o en los datos del operador
    external_send  manda algo fuera (correo, WhatsApp, Discord, un flujo n8n)
    destructive    borra, apaga o sobrescribe algo que no se puede recuperar

Un intent SIN efecto declarado se trata como `destructive`: si nadie dijo qué
hace, se pregunta o se deniega, pero nunca se ejecuta a ciegas.

Y la decisión se toma en UN sitio, `politica()`, con tres veredictos
(`PERMITIR`, `CONFIRMAR`, `DENEGAR`) y esta matriz (decisiones del dueño,
`odd/tasks/security-audit-remediation.md` L59):

    efecto          local       remoto      restringido (n8n)
    read            permitir    permitir    solo si está en la lista blanca
    write_local     permitir    permitir    denegar
    external_send   permitir    confirmar   denegar
    destructive     confirmar   confirmar   denegar

Donde «local» es el equipo del operador (pc, voz, job, sub, vacío), «remoto» es
el móvil y Telegram, y «restringido» es lo que no es el operador (hoy: n8n). En
el `read` restringido la lista blanca es una INTERSECCIÓN: el par tiene que
estar listado Y declararse de lectura; con la lista sola, un par listado que un
día empiece a escribir seguiría pasando.

Este módulo vive en `comun` a propósito: no importa nada de `core/`, así que la
capa de abajo se puede leer sola y `brain` (aplicación) puede consultarlo sin
crear un ciclo.
"""
from __future__ import annotations

# Canales que NO son el operador y por tanto entran con lista blanca.
#   n8n  — POST /api/n8n: lo dispara un flujo, no una persona.
CANALES_RESTRINGIDOS = ("n8n",)

# Canales REMOTOS: la orden viene del operador, pero desde fuera del equipo
# (móvil, Telegram). Puede leer y escribir lo local, pero lo que sale al mundo
# y lo que borra se pregunta antes (L59).
CANALES_REMOTOS = ("mobile", "telegram")

# ── Vocabulario de efectos (roadmap P2-1, task T8a) ──────────────────────────
# Lo que una skill puede hacer. Se declara por intent; si un intent no declara
# nada, cuenta como `destructive` (EFECTO_POR_DEFECTO): lo prudente cuando nadie
# dijo qué hace.
EFECTOS = ("read", "write_local", "external_send", "destructive")
EFECTO_POR_DEFECTO = "destructive"

# Los tres veredictos de la matriz canal × efecto.
PERMITIR = "permitir"
CONFIRMAR = "confirmar"
DENEGAR = "denegar"

# Clases de canal. El nombre es el que devuelve `clase_de_canal`.
LOCAL = "local"
REMOTO = "remoto"
RESTRINGIDO = "restringido"

# Lista blanca por canal: pares «carpeta_skill/intent» que puede ejecutar.
# Cada entrada está aquí por una razón, y la razón es la de abajo. Si algún día
# una de estas acciones deja de ser de solo lectura, se cae de la lista.
_LISTA_BLANCA: dict[str, frozenset[str]] = {
    "n8n": frozenset({
        # Consulta del estado de la conexión de Instagram: lee la configuración
        # (¿hay token? ¿hay id de cuenta? ¿está el perfil relleno?) y contesta.
        # No habla con la red ni escribe nada. Es lo que usa el informe diario
        # para decidir si hay datos con los que trabajar.
        "instagram/ig_estado",
        # Análisis de los reels DEL PROPIO operador: baja sus métricas por la
        # Graph API y deja el informe en archivos locales. Solo LEE de su cuenta
        # y no publica, no comenta, no toca nada de la cuenta ni de terceros.
        "instagram/ig_analizar",
        # Ideas de contenido: una llamada al modelo que devuelve texto. No
        # escribe en ningún sitio ni sale a la red por su cuenta.
        "content_os/ideas",
    }),
}


def _pares(canal: str) -> frozenset[str] | None:
    """Lista blanca del canal, o None si el canal no está restringido."""
    return _LISTA_BLANCA.get((canal or "").strip().lower())


def es_restringido(canal: str) -> bool:
    """¿Este canal entra con lista blanca (no es una orden del operador)?"""
    return _pares(canal) is not None


def _efecto_normalizado(efecto) -> str:
    """Efecto en el vocabulario; lo que no está en la lista cae en el de fábrica."""
    if isinstance(efecto, str):
        limpio = efecto.strip().lower()
        if limpio in EFECTOS:
            return limpio
    return EFECTO_POR_DEFECTO


def clase_de_canal(source, channel) -> str:
    """Clase del canal por el que entra la orden: `local`, `remoto` o `restringido`.

    Restringido es lo que no es el operador: hoy solo n8n, y da igual si llega
    en `source` (POST /api/n8n) o en `channel`. Remoto es el móvil y Telegram;
    todo lo demás (pc, voz, job, sub, un canal vacío) es el equipo del operador.
    Mayúsculas y espacios no cuentan.
    """
    if es_restringido(source) or es_restringido(channel):
        return RESTRINGIDO
    if (channel or "").strip().lower() in CANALES_REMOTOS:
        return REMOTO
    return LOCAL


def _canal_restringido(source, channel) -> str:
    """Con qué nombre de `_LISTA_BLANCA` se busca un canal restringido."""
    for candidato in (source, channel):
        limpio = (candidato or "").strip().lower()
        if limpio in _LISTA_BLANCA:
            return limpio
    return ""


def _par(carpeta, intent) -> str:
    """El par «carpeta_skill/intent» de la lista blanca, con o sin carpeta."""
    izq = (carpeta or "").strip().strip("/")
    der = (intent or "").strip().strip("/")
    return f"{izq}/{der}".strip("/")


def politica(source, channel, efecto, carpeta: str = "", intent: str = "") -> str:
    """Veredicto de la matriz canal × efecto: `permitir`, `confirmar` o `denegar`.

    Es la decisión ÚNICA del vocabulario de efectos (L59). El llamante no vuelve
    a razonar sobre canales: pregunta aquí y obedece el veredicto.

      - `read`         se permite en local y remoto; en un canal restringido solo
                       si el par «carpeta/intent» está en su lista blanca (la
                       lista es una INTERSECCIÓN: listado Y de lectura).
      - `write_local`  se permite en local y remoto; denegado en restringido.
      - `external_send` se permite en local, se pregunta desde remoto y se
                       deniega en restringido.
      - `destructive`  se pregunta en local y remoto, y se deniega en restringido.

    Un `efecto` desconocido, vacío o None cuenta como `EFECTO_POR_DEFECTO`.
    """
    clase = clase_de_canal(source, channel)
    ef = _efecto_normalizado(efecto)

    if clase == RESTRINGIDO:
        pares = _pares(_canal_restringido(source, channel))
        if ef == "read" and pares and _par(carpeta, intent) in pares:
            return PERMITIR
        return DENEGAR

    if ef in ("read", "write_local"):
        return PERMITIR
    if ef == "external_send":
        return PERMITIR if clase == LOCAL else CONFIRMAR
    # destructive: desde el equipo del operador también se pregunta, porque no
    # hay vuelta atrás (L59).
    return CONFIRMAR


def permitido(canal: str, routed) -> bool:
    """¿Puede este canal ejecutar lo que ha devuelto el enrutador?

    `routed` es la tupla `(skill, intent, match)` de `skills_loader.route`, o
    None si ninguna regex casó. Un canal no restringido puede con todo (como
    siempre); uno restringido, solo con su lista y solo si hay ruta."""
    pares = _pares(canal)
    if pares is None:
        return True
    if not routed:
        return False
    try:
        skill, intent = routed[0], routed[1]
        return f"{skill.folder}/{intent}" in pares
    except Exception:                                       # noqa: BLE001
        return False


def rechazo(canal: str) -> dict:
    """Respuesta de nexus cuando el canal no tiene permiso para esa orden."""
    return {"reply": f"Esa orden no está permitida desde {canal}.",
            "skill": None, "provider": "canal", "data": None}
