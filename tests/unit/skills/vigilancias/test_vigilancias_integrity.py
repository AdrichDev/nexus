# -*- coding: utf-8 -*-
"""vigilancias: sin pérdida silenciosa de datos y sin promesas falsas.

Encontrado auditando la skill (fichero de vigilancias temporal, sin red):
  * guardar tras una comprobación pisaba el fichero: lo borrado mientras tanto
    resucitaba y lo añadido mientras tanto se perdía;
  * «deja de vigilar a» borraba la primera vigilancia cuya URL contuviera «a»;
  * la misma URL se podía vigilar dos veces (avisos dobles);
  * la respuesta prometía «HUD y Telegram» aunque Telegram no estuviera configurado;
  * una página sin precio o ilegible no avisaba NUNCA, ni al empezar ni después.

websearch, avisos y Telegram simulados. Nivel M.
Ejecutar: python tests/unit/skills/vigilancias/test_vigilancias_integrity.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core.aplicacion import skills_loader as sl  # noqa: E402
from backend.core.infraestructura import telegram_bridge, websearch  # noqa: E402

sl.load_skills()
vig = sl.get_skills()["vigilancias"].module

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def nuevo_entorno():
    tmp = Path(tempfile.mkdtemp(prefix="nexus_vig_test_"))
    vig._file = lambda: tmp / "watchers.json"
    return tmp


async def arun(frase):
    r = sl.route(frase)
    assert r and r[0].folder == "vigilancias", (frase, r and (r[0].folder, r[1]))
    return (await r[0].module.handle(r[1], frase, r[2], None))["reply"]


def run(frase):
    return asyncio.run(arun(frase))


def lista():
    return [(w["num"], w["tipo"], w["objetivo"]) for w in vig._load()]


# 1) carrera: lo borrado/añadido durante una comprobación sobrevive -------------------------
nuevo_entorno()
run("vigila la web https://uno.example/a")
run("vigila la web https://dos.example/b")
run("vigila la web https://tres.example/c")
quitar = [w["num"] for w in vig._load()][-1]


async def lento(url, max_chars=6000):
    await asyncio.sleep(0.3)
    return "contenido de la página " + url


orig_fetch = websearch.fetch_page
websearch.fetch_page = lento


async def escenario():
    tarea = asyncio.create_task(vig.check_watchers(force=True))
    await asyncio.sleep(0.1)                           # la comprobación está esperando a la red
    await arun(f"borra la vigilancia {quitar}")
    await arun("vigila la web https://nueva.example/d")
    await tarea

try:
    asyncio.run(escenario())
finally:
    websearch.fetch_page = orig_fetch
estado = vig._load()
check(not any("tres.example" in w["objetivo"] for w in estado), "carrera: la vigilancia borrada durante la comprobación NO resucita")
check(any("nueva.example" in w["objetivo"] for w in estado), "carrera: la vigilancia añadida durante la comprobación NO se pierde")
check(all(w.get("estado", {}).get("digest") for w in estado if "nueva.example" not in w["objetivo"]),
      "carrera: las comprobaciones que sí terminaron guardaron su estado")

# 2) duplicados --------------------------------------------------------------------------------
nuevo_entorno()
run("vigila la web https://ejemplo.com/a")
r = run("vigila la web https://ejemplo.com/a")
check("ya vigilo" in r.lower() and "#1" in r, "duplicado: dice que ya la vigila y con qué número")
check(len(vig._load()) == 1, "duplicado: no crea una segunda vigilancia")
run("vigila el precio de https://ejemplo.com/a")
check(len(vig._load()) == 2, "duplicado: el mismo enlace con OTRO tipo de vigilancia sí es distinto")

# 3) borrar por texto -------------------------------------------------------------------------
nuevo_entorno()
run("vigila la web https://ejemplo.com/a")
run("vigila la web https://otra.org/b")
r = run("deja de vigilar a")
check(len(vig._load()) == 2, "borrar ambiguo: no borra nada si hay varias coincidencias")
check("#1" in r and "#2" in r and "cuál" in r.lower(), "borrar ambiguo: lista las candidatas y pide el número")
r = run("deja de vigilar otra.org")
check(lista() == [(1, "web", "https://ejemplo.com/a")] and "#2" in r, "borrar con una sola coincidencia: la quita y dice cuál")
r = run("deja de vigilar zzzzz")
check("No encuentro" in r and len(vig._load()) == 1, "borrar sin coincidencias: lo dice y no borra")

# 3b) una URL que termina en dígito NO es «la vigilancia N»
nuevo_entorno()
run("vigila la web https://ejemplo.com/p2")
run("vigila la web https://otra.org/b")
r = run("deja de vigilar https://ejemplo.com/p2")
check(lista() == [(2, "web", "https://otra.org/b")] and "#1" in r,
      "borrar por URL acabada en número: quita la de esa URL (#1), no la #2")

# 4) canales honestos -------------------------------------------------------------------------
nuevo_entorno()
orig_token, orig_owner = telegram_bridge._token, telegram_bridge.OWNER_FILE
try:
    telegram_bridge._token = lambda: None
    r = run("vigila la web https://sintelegram.example/x")
    check("HUD" in r and "Telegram" not in r, "canales: sin Telegram configurado solo promete el HUD")
    dueno = Path(tempfile.mkdtemp(prefix="nexus_vig_owner_")) / "owner"
    dueno.write_text("123", encoding="utf-8")
    telegram_bridge._token = lambda: "token-de-prueba"
    telegram_bridge.OWNER_FILE = dueno
    r = run("vigila la web https://contelegram.example/y")
    check("HUD" in r and "Telegram" in r, "canales: con Telegram configurado lo menciona")
finally:
    telegram_bridge._token, telegram_bridge.OWNER_FILE = orig_token, orig_owner

# 5) aviso de salud ---------------------------------------------------------------------------
avisos = []


async def _captura(msg):
    avisos.append(msg)


orig_notify = vig._notify
vig._notify = _captura


def con_paginas(secuencia):
    """fetch_page que devuelve (o lanza) lo que diga la secuencia, uno por llamada."""
    it = iter(secuencia)

    async def f(url, max_chars=6000):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v
    return f


def comprobar(n=1):
    for _ in range(n):
        asyncio.run(vig.check_watchers(force=True))


try:
    # precio: primera comprobación sin precio -> avisa una vez
    nuevo_entorno(); avisos.clear()
    run("vigila el precio de https://tienda.example/p")
    websearch.fetch_page = con_paginas(["Página sin ningún precio visible"] * 3)
    comprobar(3)
    check(len(avisos) == 1 and "no encuentro un precio" in avisos[0].lower() and "#1" in avisos[0],
          f"salud: precio sin precio avisa UNA vez en la primera comprobación ({len(avisos)} avisos)")

    # web ilegible en la primera comprobación
    nuevo_entorno(); avisos.clear()
    run("vigila la web https://caida.example/w")
    websearch.fetch_page = con_paginas([""] * 2)
    comprobar(2)
    check(len(avisos) == 1 and "no consigo leer" in avisos[0].lower(), "salud: web ilegible avisa una vez al empezar")

    # primera comprobación buena: silencio
    nuevo_entorno(); avisos.clear()
    run("vigila la web https://buena.example/w")
    websearch.fetch_page = con_paginas(["contenido estable de la página"] * 3)
    comprobar(3)
    check(avisos == [], "salud: una vigilancia que funciona no avisa de nada")

    # racha de fallos tras un éxito: avisa al llegar a 3, una sola vez, y se rearma al recuperarse
    nuevo_entorno(); avisos.clear()
    run("vigila la web https://racha.example/w")
    websearch.fetch_page = con_paginas(
        ["contenido estable de la página", "", RuntimeError("red"), "", "", "contenido estable de la página",
         "", "", ""])
    comprobar(4)                                       # éxito, fallo, fallo (excepción), fallo -> 3 seguidos
    check(len(avisos) == 1 and "no consigo leer" in avisos[0].lower(), f"racha: avisa al 3.º fallo seguido ({len(avisos)})")
    comprobar(1)                                       # 4.º fallo seguido: no repite
    check(len(avisos) == 1, "racha: no repite el aviso mientras siga fallando")
    comprobar(1)                                       # éxito: se rearma
    comprobar(3)                                       # nueva racha
    check(len(avisos) == 2, f"racha: tras recuperarse, una nueva racha vuelve a avisar ({len(avisos)})")
finally:
    websearch.fetch_page = orig_fetch
    vig._notify = orig_notify

print(f"\nvigilancias integrity: {_pass} OK, {len(_fail)} FAIL")
sys.exit(1 if _fail else 0)
