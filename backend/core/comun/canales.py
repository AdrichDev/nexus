"""
nexus — Qué puede ejecutar cada canal de entrada.

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

Este módulo vive en `comun` a propósito: no importa nada de `core/`, así que la
capa de abajo se puede leer sola y `brain` (aplicación) puede consultarlo sin
crear un ciclo.
"""
from __future__ import annotations

# Canales que NO son el operador y por tanto entran con lista blanca.
#   n8n  — POST /api/n8n: lo dispara un flujo, no una persona.
CANALES_RESTRINGIDOS = ("n8n",)

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
