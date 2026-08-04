# -*- coding: utf-8 -*-
"""Skill VIGILANCIAS — activacion, enrutado, honestidad y limites.

Sin red y sin tocar data/ real: DATA_DIR se apunta a un temporal.
"""
import asyncio
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
    from backend.core import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL (no con importlib a pelo)")
    sk = sl.get_skills().get("vigilancias")
    check(sk is not None and sk.status != "error",
          "vigilancias carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales")
    esperado = {
        "web": ["vigila la web https://ejemplo.com/pagina",
                "vigila https://ejemplo.com",
                "vigilame https://ejemplo.com",
                "vigila esta pagina https://ejemplo.com",
                "avisame si cambia la web https://ejemplo.com",
                "avísame si cambia https://ejemplo.com"],
        "price": ["avisame si baja el precio de https://tienda.com/p",
                  "avísame si baja de precio https://tienda.com/p",
                  "avisame cuando baje el precio de https://tienda.com/p",
                  "vigila el precio de https://tienda.com/p",
                  "avisame si cambia el precio de https://tienda.com/p"],
        "news": ["avisame cuando haya noticias de bitcoin",
                 "avísame cuando salgan noticias sobre el mundial",
                 "vigila las noticias de la bolsa",
                 "avisame cuando haya novedades de python"],
        "list": ["mis vigilancias", "que vigilancias tengo",
                 "cuales son mis vigilancias", "cuantas vigilancias tengo",
                 "que estas vigilando", "muestrame las vigilancias",
                 "listame mis vigilancias"],
        "remove": ["borra la vigilancia 2", "borra la vigilancia #2",
                   "elimina la vigilancia 3", "quita la vigilancia 1",
                   "deja de vigilar https://ejemplo.com",
                   "para de vigilar la bolsa"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "vigilancias" and r[1] == intent,
                  f"«{f}» -> vigilancias/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    print("· «avisame si cambia <url>» es vigilancia de CONTENIDO, no de precio")
    r = sl.route("avísame si cambia https://ejemplo.com")
    check(r and r[1] == "web", "sin la palabra «precio» no se registra un vigilante de precios")

    print("· extraccion de precios (funcion pura)")
    casos = [("Precio: 1.234,56 €", 1234.56), ("€99", 99.0), ("120 euros", 120.0),
             ("$45.50", 45.5), ("cuesta 12 345,00 €", 12345.0), ("45,50 EUR", 45.5)]
    for txt, esperado_v in casos:
        check(mod.extract_price(txt) == esperado_v,
              f"extract_price({txt!r}) == {esperado_v} (da {mod.extract_price(txt)})")
    check(mod.extract_price("no hay ningun precio aqui") is None,
          "sin precio devuelve None, no un numero inventado")
    check(mod.extract_price("") is None, "texto vacio -> None")

    print("· huella y diff de contenido")
    check(mod.text_digest("Hola   MUNDO") == mod.text_digest("hola mundo"),
          "la huella normaliza espacios y mayusculas")
    check(mod.text_digest("uno") != mod.text_digest("dos"), "textos distintos, huellas distintas")
    nuevas = mod.diff_lines("linea vieja bastante larga\n",
                            "linea vieja bastante larga\nlinea nueva de mas de quince\n")
    check(nuevas == ["linea nueva de mas de quince"], f"diff_lines solo lo nuevo: {nuevas}")
    check(mod.diff_lines("a\n", "a\ncorto\n") == [],
          "las lineas cortas no se cuelan como novedad")

    print("· intervalo de comprobacion razonable (no es martilleo)")
    check(mod._CHECK_MIN >= 5, f"_CHECK_MIN = {mod._CHECK_MIN} min, no baja de 5")

    print("· alta, listado y borrado sobre un data/ TEMPORAL")
    tmp = Path(tempfile.mkdtemp())
    old = cfg.DATA_DIR
    cfg.DATA_DIR = tmp
    try:
        ctx = {"settings": {}, "channel": "pc"}
        r1 = asyncio.run(mod.handle("web", "vigila https://ejemplo.com",
                                    sl.route("vigila https://ejemplo.com")[2], ctx))
        check("#1" in r1["reply"], "la primera vigilancia se numera #1")
        r2 = asyncio.run(mod.handle("price", "vigila el precio de https://tienda.com/p",
                                    sl.route("vigila el precio de https://tienda.com/p")[2], ctx))
        check("#2" in r2["reply"], "la segunda es #2")

        lst = asyncio.run(mod.handle("list", "mis vigilancias",
                                     sl.route("mis vigilancias")[2], ctx))["reply"]
        check("#1" in lst and "#2" in lst, "el listado enseña las dos")
        check("sin comprobar" in lst,
              "dice que aun no las ha comprobado en vez de aparentar estado")

        # honestidad: una vigilancia de precio comprobada SIN precio detectado lo dice
        import json
        f = tmp / "watchers.json"
        items = json.loads(f.read_text(encoding="utf-8"))
        items[1]["ultima"] = 1.0
        items[1]["estado"] = {}
        items[0]["ultima"] = 1.0
        items[0]["estado"] = {"digest": "abc"}
        f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        lst2 = asyncio.run(mod.handle("list", "mis vigilancias",
                                      sl.route("mis vigilancias")[2], ctx))["reply"]
        check("no encuentro un precio" in lst2,
              "avisa de que en esa pagina no hay precio y no podra avisar")

        rm = asyncio.run(mod.handle("remove", "borra la vigilancia 2",
                                    sl.route("borra la vigilancia 2")[2], ctx))["reply"]
        check("#2" in rm and "eliminada" in rm, "el borrado dice EXACTAMENTE cual ha quitado")
        rm2 = asyncio.run(mod.handle("remove", "borra la vigilancia 9",
                                     sl.route("borra la vigilancia 9")[2], ctx))["reply"]
        check("No encuentro" in rm2, "una vigilancia que no existe se dice, no se finge")

        vacio = asyncio.run(mod.handle("remove", "borra la vigilancia 1",
                                       sl.route("borra la vigilancia 1")[2], ctx))
        check("#1" in vacio["reply"], "queda vacia")
        nada = asyncio.run(mod.handle("list", "mis vigilancias",
                                      sl.route("mis vigilancias")[2], ctx))["reply"]
        check("No estoy vigilando nada" in nada, "sin vigilancias lo dice y propone ordenes")
    finally:
        cfg.DATA_DIR = old

    print("· intent desconocido no revienta ni se inventa nada")
    r = asyncio.run(mod.handle("inexistente", "loquesea", None, {"settings": {}}))
    check("no reconocida" in r["reply"].lower(), "responde con la ayuda, sin traceback")

    print("· es agnostica: ni nombres propios ni rutas del usuario")
    src = (ROOT / "skills" / "vigilancias" / "skill.py").read_text(encoding="utf-8")
    doc = (ROOT / "skills" / "vigilancias" / "SKILL.md").read_text(encoding="utf-8")
    for prohibido in ("Adri", "achoz", "C:\\Users\\", "D:\\Adrian"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")

    print("· no hay scraping propio: todo pasa por el motor central")
    check("websearch" in src, "usa backend.core.infraestructura.websearch")
    for lib in ("BeautifulSoup", "selenium", "playwright", "requests.get"):
        check(lib not in src, f"no usa {lib} por su cuenta")

    print("· el SKILL.md dice lo que hace, lo que necesita y lo que NO hace")
    for trozo in ("Frases que la disparan", "Qué necesita configurado", "Qué NO hace"):
        check(trozo in doc, f"SKILL.md tiene la seccion «{trozo}»")
    check("scraping" not in doc.lower() or "No hace scraping" in doc or "públicas" in doc,
          "SKILL.md deja claro que solo lee paginas publicas")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
