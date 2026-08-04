# -*- coding: utf-8 -*-
"""Skill TELEFONO — activacion, agenda y NINGUNA llamada real.

El bus y el registro de dispositivos se sustituyen por dobles: aqui no sale
ni un solo evento 'call' hacia un movil de verdad, y la agenda vive en un
directorio temporal.
"""
import asyncio
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail = []
_pass = 0


def check(c, m):
    global _pass
    if c:
        _pass += 1
    else:
        _fail.append(m)
        print("  FALLO:", m)


def main():
    from backend.core.comun import config as cfg
    from backend.core.infraestructura import remote
    from backend.core.comun import events
    from backend.core.aplicacion import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL")
    sk = sl.get_skills().get("telefono")
    check(sk is not None and sk.status != "error",
          "telefono carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales (clitico incluido)")
    esperado = {
        "llamar": ["llama a 612 345 678", "llama a mama", "llama a mamá",
                   "llamame a mama", "llamale a mama", "llámale a Ana",
                   "marca el 611 22 33 44", "marca a casa", "marcale a mama",
                   "telefonea a ana", "hazle una llamada a ana",
                   "ponle una llamada a ana", "llama por telefono a ana"],
        "info": ["puedes hacer llamadas", "sabes hacer llamadas",
                 "podrias hacer llamadas", "como funcionan las llamadas",
                 "como activo las llamadas", "como llamo por telefono",
                 "que necesito para llamar"],
        "save_contact": ["apunta el telefono de mama 612 345 678",
                         "apuntame el telefono de mama 612 345 678",
                         "guarda el numero de ana 611223344",
                         "guardame el movil de juan 600111222",
                         "añade el contacto de luis 699887766",
                         "el telefono de ana es 612345678"],
        "list_contacts": ["mis contactos", "que telefonos tienes",
                          "cuales son mis contactos", "cuantos contactos tengo",
                          "muestrame mis contactos", "enseñame los contactos",
                          "agenda de contactos", "listame los contactos"],
        "del_contact": ["borra el contacto de mama", "elimina el telefono de ana",
                        "quitame el numero de luis"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "telefono" and r[1] == intent,
                  f"«{f}» -> telefono/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    print("· normalizacion de numeros")
    casos = [("612 34 56 78", "+34", "+34612345678"),
             ("+34612345678", "+34", "+34612345678"),
             ("0034612345678", "+34", "+34612345678"),
             ("611-22-33-44", "+34", "+34611223344"),
             ("612345678", "+351", "+351612345678")]
    for raw, cc, esperado_n in casos:
        got = mod.normalize_number(raw, cc)
        check(got == esperado_n, f"normalize_number({raw!r}, {cc!r}) == {esperado_n} (da {got})")
    check(mod.normalize_number("", "+34") == "", "sin numero no se inventa uno")

    print("· el prefijo sale de la configuracion, no esta a fuego")
    src = (ROOT / "skills" / "telefono" / "skill.py").read_text(encoding="utf-8")
    check('phone_cc' in src, "se lee phone_cc de settings")

    tmp = Path(tempfile.mkdtemp())
    old = cfg.DATA_DIR
    cfg.DATA_DIR = tmp

    emitidos = []

    async def _emit_falso(evento, payload=None):
        emitidos.append((evento, payload))

    orig_emit = events.bus.emit
    orig_devices = remote.devices
    try:
        events.bus.emit = _emit_falso
        ctx = {"settings": {"phone_cc": "+34"}, "channel": "pc"}

        print("· agenda vacia: se dice, no se inventa un contacto")
        f = "mis contactos"
        r = asyncio.run(mod.handle("list_contacts", f, sl.route(f)[2], ctx))
        check("Agenda vacía" in r["reply"], "agenda vacia, honesto")

        print("· guardar y listar un contacto")
        f = "apunta el telefono de mama 612 345 678"
        r = asyncio.run(mod.handle("save_contact", f, sl.route(f)[2], ctx))
        check("+34612345678" in r["reply"], f"guardado y normalizado: {r['reply']}")
        check(mod.load_contacts() == {"mama": "+34612345678"},
              f"la agenda tiene lo que se guardo: {mod.load_contacts()}")
        r = asyncio.run(mod.handle("list_contacts", "mis contactos",
                                   sl.route("mis contactos")[2], ctx))
        check("mama" in r["reply"] and "(1)" in r["reply"], "listado con el contador real")

        print("· resolucion por nombre, con y sin acento")
        name, num = mod.resolve_contact("Mamá")
        check(num == "+34612345678", f"«Mamá» encuentra «mama»: {name} {num}")
        check(mod.resolve_contact("zzzz") == ("", ""), "un nombre que no esta devuelve vacio")

        print("· SIN movil vinculado NO se emite ninguna llamada")
        remote.devices = lambda: []
        emitidos.clear()
        f = "llama a mama"
        r = asyncio.run(mod.handle("llamar", f, sl.route(f)[2], ctx))
        check(not any(e[0] == "call" for e in emitidos),
              "cero eventos 'call': no se marca a nadie")
        check("No tengo ningún móvil vinculado" in r["reply"], "lo dice claramente")
        check("VINCULADO" in r["reply"], "y explica como arreglarlo")

        print("· CON movil vinculado se emite el evento con el numero de la agenda")
        remote.devices = lambda: [{"id": "movil-doble"}]
        emitidos.clear()
        r = asyncio.run(mod.handle("llamar", "llama a mama",
                                   sl.route("llama a mama")[2], ctx))
        llamadas = [e for e in emitidos if e[0] == "call"]
        check(len(llamadas) == 1, "un solo evento 'call'")
        check(llamadas[0][1]["number"] == "+34612345678",
              f"con el numero de la agenda: {llamadas[0][1]}")
        check("de mi agenda" in r["reply"], "y lo dice en la respuesta")

        print("· un numero suelto se marca tal cual, sin buscar en la agenda")
        emitidos.clear()
        f = "llama a 611 22 33 44"
        r = asyncio.run(mod.handle("llamar", f, sl.route(f)[2], ctx))
        llamadas = [e for e in emitidos if e[0] == "call"]
        check(llamadas and llamadas[0][1]["number"] == "+34611223344",
              f"numero normalizado: {llamadas}")

        print("· un nombre que NO esta en la agenda no se inventa un numero")
        emitidos.clear()
        f = "llama a zzzz"
        r = asyncio.run(mod.handle("llamar", f, sl.route(f)[2], ctx))
        llamadas = [e for e in emitidos if e[0] == "call"]
        check(llamadas and llamadas[0][1]["number"] == "",
              f"va sin numero, para que lo busque el movil: {llamadas}")
        check("no lo tengo en mi agenda" in r["reply"], "y avisa de que no lo tiene")

        print("· borrar un contacto que no existe no borra otro")
        f = "borra el contacto de zzzz"
        r = asyncio.run(mod.handle("del_contact", f, sl.route(f)[2], ctx))
        check("No tengo a" in r["reply"], "lo dice")
        check(mod.load_contacts() == {"mama": "+34612345678"}, "la agenda sigue igual")

        f = "borra el contacto de mama"
        r = asyncio.run(mod.handle("del_contact", f, sl.route(f)[2], ctx))
        check("borrado" in r["reply"] and "mama" in r["reply"],
              "el borrado dice EXACTAMENTE a quien ha quitado")
        check(mod.load_contacts() == {}, "y la agenda queda vacia")

        print("· un numero de mentira no se guarda")
        emitidos.clear()
        r = asyncio.run(mod.handle("save_contact", "x", None, ctx))
        check("No he pillado el nombre" in r["reply"], "sin match responde, no revienta")

        print("· 'info' no marca nada")
        emitidos.clear()
        r = asyncio.run(mod.handle("info", "puedes hacer llamadas",
                                   sl.route("puedes hacer llamadas")[2], ctx))
        check(not emitidos, "explicar no dispara ningun evento")
        check("móvil vinculado" in r["reply"], "y explica el requisito")

        print("· sin 'who' no se marca a ciegas")
        emitidos.clear()
        r = asyncio.run(mod.handle("llamar", "llama", None, ctx))
        check(not emitidos, "cero eventos")
        check("¿A quién llamo?" in r["reply"], "pregunta a quien")
    finally:
        events.bus.emit = orig_emit
        remote.devices = orig_devices
        cfg.DATA_DIR = old

    print("· es agnostica: ni nombres reales ni telefonos de nadie")
    doc = (ROOT / "skills" / "telefono" / "SKILL.md").read_text(encoding="utf-8")
    for prohibido in ("Adri", "achoz", "D:\\Adrian", "C:\\Users\\"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")
    # Los unicos numeros que pueden aparecer son los de ejemplo de la documentacion.
    EJEMPLOS = {"612345678", "611223344", "34"}
    for texto, nombre in ((src, "skill.py"), (doc, "SKILL.md")):
        for n in re.findall(r"[+\d][\d .\-]{7,}\d", texto):
            solo = re.sub(r"\D", "", n)
            check(solo.lstrip("34") in EJEMPLOS or solo in EJEMPLOS,
                  f"{nombre}: «{n}» no es un numero de ejemplo conocido")

    print("· la agenda real no esta en git")
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("data/" in gi or "data" in gi, "data/ esta ignorado (la agenda vive ahi)")

    print("· el SKILL.md dice lo que necesita y lo que NO hace")
    for trozo in ("Qué necesita configurado", "Qué NO hace", "no llama"):
        check(trozo in doc, f"SKILL.md menciona «{trozo}»")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
