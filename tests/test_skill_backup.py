# -*- coding: utf-8 -*-
"""Skill BACKUP — activacion, rotacion y sobre todo: NADA se borra sin un «si».

Todo ocurre en directorios temporales; ni data/ real ni el proyecto se tocan.
"""
import asyncio
import sys
import tempfile
import zipfile
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
    from backend.core.comun import confirm
    from backend.core.aplicacion import skills_loader as sl
    sl.load_skills()

    print("· la skill carga con el cargador REAL")
    sk = sl.get_skills().get("backup")
    check(sk is not None and sk.status != "error",
          "backup carga sin error: " + (sk.description if sk else "no existe"))
    mod = sk.module

    print("· cada intent se activa con frases naturales")
    esperado = {
        "make": ["haz una copia de seguridad", "hazme una copia de seguridad",
                 "haz copia de seguridad", "crea una copia de seguridad",
                 "creame una copia de seguridad", "genera una copia de seguridad",
                 "haz un backup", "hazme un backup", "haz backup", "backup ahora"],
        "list": ["que copias de seguridad hay", "cuantas copias de seguridad tengo",
                 "lista las copias de seguridad", "muestrame los backups",
                 "mis backups", "ver backups"],
        "baks": ["archiva los bak", "limpia los bak", "recoge los backups manuales",
                 "empaqueta los archivos bak"],
        "restore": ["restaura la copia de seguridad", "restaurame el backup de ayer",
                    "recupera la copia de seguridad", "recupera el backup",
                    "restablece la copia de seguridad",
                    "vuelve a la copia de seguridad de ayer"],
    }
    for intent, frases in esperado.items():
        for f in frases:
            r = sl.route(f)
            check(bool(r) and r[0].folder == "backup" and r[1] == intent,
                  f"«{f}» -> backup/{intent}"
                  + (f" (se la queda {r[0].folder}/{r[1]})" if r else " (no casa: al cerebro)"))

    tmp = Path(tempfile.mkdtemp())
    old = cfg.DATA_DIR
    cfg.DATA_DIR = tmp
    try:
        print("· la copia dice el numero REAL de archivos, no uno redondo")
        (tmp / "memory").mkdir(parents=True)
        (tmp / "memory" / "nota.md").write_text("hola", encoding="utf-8")
        (tmp / "board.json").write_text("{}", encoding="utf-8")
        (tmp / "chrome_nexus").mkdir()
        (tmp / "chrome_nexus" / "perfil.bin").write_text("x", encoding="utf-8")
        out, n = mod.make_backup()
        check(n == 2, f"2 archivos contados, ni uno mas (perfil de Chrome fuera): n={n}")
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        check("memory/nota.md" in names and "board.json" in names, "el zip lleva lo que dice")
        check(not any("chrome_nexus" in x for x in names), "y NO lleva el perfil de Chrome")

        print("· la rotacion deja exactamente KEEP copias diarias")
        dest = tmp / "backups"
        for i in range(10):
            (dest / f"nexus-data-2026010{i}.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        mod.rotate_backups(keep=mod.KEEP)
        check(len(list(dest.glob("nexus-data-*.zip"))) == mod.KEEP,
              f"quedan {mod.KEEP}")

        print("· los baks-*.zip NO entran en la rotacion de las diarias")
        (dest / "baks-20260101.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        mod.rotate_backups(keep=1)
        check((dest / "baks-20260101.zip").exists(), "el archivo de .bak sigue ahi")

        print("· «restaura» NO restaura nada: explica como hacerlo a mano")
        ficheros_antes = sorted(p.name for p in tmp.rglob("*"))
        f = "restaura la copia de seguridad"
        r = asyncio.run(mod.handle("restore", f, sl.route(f)[2], {"channel": "pc"}))
        check("Restaurar NO lo hago yo" in r["reply"], "lo dice claramente")
        check("Cierra nexus" in r["reply"], "y da los pasos")
        check("data_viejo" in r["reply"], "renombrar en vez de borrar")
        check(sorted(p.name for p in tmp.rglob("*")) == ficheros_antes,
              "y no ha tocado un solo archivo")

        print("· ARCHIVAR .bak pide confirmacion ANTES de borrar nada")
        proj = Path(tempfile.mkdtemp())
        (proj / "data").mkdir()
        (proj / "skills" / "x").mkdir(parents=True)
        victima1 = proj / "skills" / "x" / "skill.py.bak_v9"
        victima2 = proj / "app.py.bak_v2"
        victima1.write_text("viejo1", encoding="utf-8")
        victima2.write_text("viejo2", encoding="utf-8")
        inocente = proj / "receta.baking.md"
        inocente.write_text("no soy un backup", encoding="utf-8")
        cfg.DATA_DIR = proj / "data"

        encontrados = mod.find_baks(proj)
        check(len(encontrados) == 2, f"encuentra los 2 .bak de verdad: {encontrados}")
        check(inocente not in encontrados, "y no confunde «receta.baking.md» con un backup")

        confirm._pending.clear()
        f = "archiva los bak"
        r = asyncio.run(mod.handle("baks", f, sl.route(f)[2], {"channel": "pc"}))
        check("¿Lo confirmas?" in r["reply"], "pregunta antes de nada")
        check("skill.py.bak_v9" in r["reply"], "y enseña QUE va a borrar")
        check(victima1.exists() and victima2.exists(),
              "NADA borrado mientras no haya respuesta")
        check(bool(confirm.pending("pc")), "la accion queda armada, sin ejecutar")

        print("· si dices que NO, no se borra nada")
        no = asyncio.run(confirm.answer("no", "pc"))
        check(no is not None and "no toco" in no.lower(), f"lo confirma: {no}")
        check(victima1.exists() and victima2.exists(), "los .bak siguen ahi")

        print("· si dices que SI, se archiva y se verifica antes de borrar")
        confirm._pending.clear()
        r = asyncio.run(mod.handle("baks", "archiva los bak",
                                   sl.route("archiva los bak")[2], {"channel": "pc"}))
        si = asyncio.run(confirm.answer("sí", "pc"))
        check(si is not None and "archivados" in si, f"informa del resultado: {si}")
        check(not victima1.exists() and not victima2.exists(), "ahora si se han borrado")
        check(inocente.exists(), "y «receta.baking.md» sigue intacto")
        zips = list((proj / "data" / "backups").glob("baks-*.zip"))
        check(len(zips) == 1, "hay un zip de baks")
        with zipfile.ZipFile(zips[0]) as z:
            check(z.testzip() is None and len(z.namelist()) == 2,
                  "el zip esta integro y lleva los 2")

        print("· sin .bak sueltos lo dice y no pregunta por gusto")
        confirm._pending.clear()
        r = asyncio.run(mod.handle("baks", "archiva los bak",
                                   sl.route("archiva los bak")[2], {"channel": "pc"}))
        check("está limpio" in r["reply"], "dice que no hay nada que archivar")
        check(not confirm.pending("pc"), "y no deja una confirmacion armada de mentira")
    finally:
        cfg.DATA_DIR = old
        confirm._pending.clear()

    print("· intent desconocido no revienta")
    r = asyncio.run(mod.handle("inexistente", "loquesea", None, {"channel": "pc"}))
    check("no reconocida" in r["reply"].lower(), "responde con la ayuda, sin traceback")

    print("· el scheduler sigue enganchando la copia diaria")
    sch = (ROOT / "backend" / "core" / "aplicacion" / "scheduler.py").read_text(encoding="utf-8")
    check("auto_backup" in sch, "scheduler llama a auto_backup")

    print("· es agnostica")
    src = (ROOT / "skills" / "backup" / "skill.py").read_text(encoding="utf-8")
    doc = (ROOT / "skills" / "backup" / "SKILL.md").read_text(encoding="utf-8")
    for prohibido in ("Adri", "achoz", "D:\\Adrian", "C:\\Users\\"):
        check(prohibido not in src, f"skill.py no lleva «{prohibido}»")
        check(prohibido not in doc, f"SKILL.md no lleva «{prohibido}»")

    print("· el SKILL.md dice que no restaura y que pide confirmacion")
    check("Qué NO hace" in doc, "SKILL.md tiene la seccion «Qué NO hace»")
    check("No restaura nada por su cuenta" in doc, "documenta que no restaura")
    check("sin confirmación" in doc, "documenta que no borra sin confirmar")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
