# -*- coding: utf-8 -*-
"""secretos.redactar: oculta secretos antes de que lleguen a la memoria.

Solo cadenas sintéticas; sin red, sin BD, sin config de producción. Nivel M.
Ejecutar: python tests/unit/core/test_secretos.py
"""
import importlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


secretos = importlib.import_module("backend.core.comun.secretos")
redactar = secretos.redactar
OCULTO = secretos.OCULTO

# (texto, fragmento secreto que NO debe sobrevivir)
SECRETOS = [
    ("mi clave es sk-abcdefghijklmnopqrstuvwxyz123456", "sk-abcdefghijklmnopqrstuvwxyz123456"),
    ("token de github ghp_abcdefghijklmnopqrstuvwxyz0123456789 ok", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
    ("aws AKIAABCDEFGHIJKLMNOP listo", "AKIAABCDEFGHIJKLMNOP"),
    ("slack xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
    ("google AIzaSyA1234567890abcdefghijklmnopqrstuv", "AIzaSyA1234567890abcdefghijklmnopqrstuv"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"),
    ("conecta a postgresql://admin:Sup3rSecreta99@db.local:5432/app", "Sup3rSecreta99"),
    ("password=Abc12345!x", "Abc12345!x"),
    ("API_KEY: abcdef123456", "abcdef123456"),
    ("la contraseña es hola1234", "hola1234"),
    ("Authorization: Bearer abcdefghijklmnop1234567890", "abcdefghijklmnop1234567890"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA1234\nabcd\n-----END RSA PRIVATE KEY-----", "MIIEowIBAAKCAQEA1234"),
]

# Texto que NO es un secreto y debe quedar IDÉNTICO.
INOCUOS = [
    "la clave es importante para el proyecto",
    "el token de acceso se renueva cada hora",
    "conéctate a postgresql://user:pass@host:5432/db",
    "password: ****",
    "password: <tu-contraseña>",
    "commit 3f786850e387550fdab836ed7e6dc881de23001b arregla el bug",
    "reunión el 12/03 a las 10:30 con Ana, presupuesto 4500 euros",
    "visita https://example.com/docs/guia?pagina=2 para más info",
    "id de pedido 123e4567-e89b-12d3-a456-426614174000",
]

for texto, secreto in SECRETOS:
    limpio, n = redactar(texto)
    check(secreto not in limpio, f"redacta: «{texto[:40]}…» ya no contiene el secreto")
    check(OCULTO in limpio and n >= 1, f"redacta: «{texto[:40]}…» deja la marca y cuenta ≥ 1")

for texto in INOCUOS:
    limpio, n = redactar(texto)
    check(limpio == texto and n == 0, f"no toca: «{texto[:50]}»")

# solo se oculta el VALOR: la clave y el resto de la frase se conservan
limpio, _ = redactar("password=Abc12345!x y luego reiniciar")
check(limpio.startswith("password=") and limpio.endswith("y luego reiniciar"),
      "conserva el nombre del campo y el resto de la frase")
limpio, _ = redactar("conecta a postgresql://admin:Sup3rSecreta99@db.local:5432/app")
check("admin" in limpio and "@db.local:5432/app" in limpio and "Sup3rSecreta99" not in limpio,
      "URL con credenciales: oculta solo la contraseña")

# idempotente: redactar lo ya redactado no cambia nada (la ingesta lo necesita para comparar trozos)
for texto, _s in SECRETOS:
    una, _n = redactar(texto)
    dos, n2 = redactar(una)
    check(una == dos and n2 == 0, f"idempotente: «{texto[:40]}…»")

# varios secretos en un mismo texto
limpio, n = redactar("a=sk-abcdefghijklmnopqrstuvwxyz123456 y password=Abc12345!x")
check(n == 2 and "sk-abc" not in limpio and "Abc12345" not in limpio, "varios secretos: los cuenta y oculta todos")

# entradas raras no rompen
for raro in ("", None, "   "):
    try:
        res = redactar(raro)
        check(res[1] == 0, f"entrada rara {raro!r}: sin error y n = 0")
    except Exception as exc:                           # noqa: BLE001
        check(False, f"entrada rara {raro!r}: lanzó {exc}")

print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
if _fail:
    for f in _fail:
        print(" -", f)
    sys.exit(1)
