"""
nexus — Redacción de secretos antes de guardar en memoria.

Lo que Nexus guarda (RAG, Postgres, memoria operativa, Engram, notas) se inyecta
después en el contexto de los agentes y de los modelos. Una clave pegada en una
conversación NO debe sobrevivir ahí en claro.

`redactar(texto) -> (texto_limpio, n)` sustituye SOLO el valor secreto por
`OCULTO` y deja intacto el resto (el nombre del campo, la frase, el usuario de
una URL). Reglas de diseño:

  * Idempotente: redactar lo ya redactado no cambia nada y devuelve n = 0. La
    ingesta lo necesita para comparar trozos por contenido (sobrescritura por
    origen) sin retirar y volver a guardar filas idénticas.
  * Conservadora con la prosa: «la clave es importante» no se toca; un valor
    tras «clave/token/password…» solo se oculta si PARECE un secreto (≥ 8
    caracteres y con dígito o símbolo, o ≥ 20 caracteres).
  * Los marcadores de documentación (`user:pass@host`, `password: ****`,
    `<tu-clave>`) no son secretos y se respetan.
  * No es un detector exhaustivo: cubre formatos conocidos y pares clave=valor.
    Mejor un falso negativo ocasional que destrozar conocimiento legítimo.
"""
from __future__ import annotations

import re

OCULTO = "[SECRETO-OCULTO]"

_MARCADORES = {"pass", "password", "passwd", "pwd", "contraseña", "contrasena", "clave",
               "secret", "secreto", "token", "xxxx", "xxxxxxxx", "changeme", "ejemplo",
               "example", "tupassword", "tuclave", "tucontraseña", "yourpassword"}


def _es_marcador(valor: str) -> bool:
    v = valor.strip().lower()
    return (OCULTO.lower() in v or v in _MARCADORES
            or re.fullmatch(r"[*xX•.\-_#]+", valor) is not None
            or valor[:1] in "<[{$%")


def _parece_secreto(valor: str) -> bool:
    if len(valor) < 8:
        return False
    return len(valor) >= 20 or any(c.isdigit() for c in valor) or any(not c.isalnum() for c in valor)


_BLOQUE_CLAVE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----",
    re.DOTALL)
_CABECERA_CLAVE_SUELTA = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*", re.DOTALL)

# Formatos con prefijo reconocible: el token entero es el secreto.
_FORMATOS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]

_BEARER = re.compile(r"(\bBearer\s+)([A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE)
_URL_CREDENCIALES = re.compile(r"([a-z][a-z0-9+.\-]*://[^\s/:@]{1,40}:)([^\s/@]{3,})(@)", re.IGNORECASE)
_CLAVE_VALOR = re.compile(
    r"\b(api[_-]?key|apikey|client[_-]?secret|secret|access[_-]?token|refresh[_-]?token|token|"
    r"password|passwd|pwd|contrase[ñn]a|clave)\b"
    r"(\s*(?:[:=]|\bes\b|\bis\b)\s*)([\"']?)([^\s\"'<>,;]{8,})",
    re.IGNORECASE)


def redactar(texto) -> tuple[str, int]:
    """Devuelve (texto sin secretos, nº de secretos ocultados)."""
    if not texto:
        return ("", 0)
    cuenta = 0

    def sub_total(_m):
        nonlocal cuenta
        cuenta += 1
        return OCULTO

    t = str(texto)
    t = _BLOQUE_CLAVE.sub(sub_total, t)
    t = _CABECERA_CLAVE_SUELTA.sub(sub_total, t)        # clave cortada: se oculta hasta el final
    for patron in _FORMATOS:
        t = patron.sub(sub_total, t)

    def sub_bearer(m):
        nonlocal cuenta
        if _es_marcador(m.group(2)):
            return m.group(0)
        cuenta += 1
        return m.group(1) + OCULTO

    t = _BEARER.sub(sub_bearer, t)

    def sub_url(m):
        nonlocal cuenta
        if _es_marcador(m.group(2)):
            return m.group(0)
        cuenta += 1
        return m.group(1) + OCULTO + m.group(3)

    t = _URL_CREDENCIALES.sub(sub_url, t)

    def sub_kv(m):
        nonlocal cuenta
        valor = m.group(4)
        if _es_marcador(valor) or not _parece_secreto(valor):
            return m.group(0)
        cuenta += 1
        return m.group(1) + m.group(2) + m.group(3) + OCULTO

    t = _CLAVE_VALOR.sub(sub_kv, t)
    return (t, cuenta)
