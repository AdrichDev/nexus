# -*- coding: utf-8 -*-
"""Skill de Instagram Reels — que esté MAQUETADA, no a medias.

Lo que se exige aquí:
  * el minion carga y respeta el contrato de nexus (SKILL + handle)
  * NO trae ningún dato personal de nadie: la plantilla se entrega vacía
  * el perfil admite el contexto COMPLETO del usuario (nicho, idiomas, tono,
    negocio y quién es —profesión, familia, hijos, temas que no toca—) y admite
    VARIOS perfiles, uno por cuenta
  * sin token no se inventa nada: dice qué falta y cómo conseguirlo
  * el token NUNCA viaja por la línea de comandos (ahí lo vería cualquiera)
  * el prompt del análisis lleva el contexto dentro y las reglas correctas
    (sentimiento sin triggers; leads CON triggers)
  * sus patrones no le roban órdenes a las demás skills

Ejecutar:  python tests/test_instagram.py    (desde la carpeta nexus)
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_fail = []
_pass = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SAND = Path(tempfile.mkdtemp(prefix="nexus_ig_"))
(_SAND / "data").mkdir()
(_SAND / "config").mkdir()
(_SAND / "config" / "settings.json").write_text(json.dumps({
    "setup_done": True, "llm_provider": "mock"}), encoding="utf-8")
os.environ["NEXUS_DATA_DIR"] = str(_SAND / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_SAND / "config")

import importlib.util                                            # noqa: E402
_spec = importlib.util.spec_from_file_location("igskill", ROOT / "skills" / "instagram" / "skill.py")
ig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ig)
from backend.core.config import settings                         # noqa: E402
from backend.core.skills_loader import load_skills, route        # noqa: E402

CTX = {"settings": settings, "bus": None}


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


# ══════════════ 1. Está instalada de verdad ══════════════
def test_instalada():
    print("· la skill está instalada y cumple el contrato")
    d = ROOT / "skills" / "instagram"
    for f in ("skill.py", "SKILL.md", "scripts/ig.py", "perfil.plantilla.json"):
        check((d / f).exists(), f"existe skills/instagram/{f}")
    check(isinstance(ig.SKILL, dict) and ig.SKILL.get("patterns"), "expone SKILL con patrones")
    check(asyncio.iscoroutinefunction(ig.handle), "expone handle() asíncrono")
    load_skills()
    r = route("analiza mis últimos 3 reels")
    check(r is not None and r[0].folder == "instagram",
          f"el router la encuentra ({r[0].folder if r else 'nada'})")
    check(r[1] == "ig_analizar", f"y con el intent correcto ({r[1] if r else '-'})")


# ══════════════ 2. No trae datos de nadie ══════════════
def test_plantilla_vacia():
    print("· la plantilla no lleva datos de ninguna persona")
    llenos, total = ig.campos_rellenos(ig.PERFIL_VACIO)
    check(total >= 30, f"el perfil tiene {total} campos (contexto completo)")
    check(llenos <= 3, f"y viene prácticamente vacío ({llenos} rellenos, solo preferencias)")
    crudo = json.dumps(ig.PERFIL_VACIO, ensure_ascii=False).lower()
    src = (ROOT / "skills" / "instagram" / "skill.py").read_text(encoding="utf-8").lower()
    # La plantilla se instala tal cual en la maquina de cualquiera: no puede
    # llevar datos de nadie. Se comprueba la PROPIEDAD (ningun correo, ninguna
    # arroba) en vez de una lista de cadenas concretas, que ademas obligaria a
    # escribir esos datos aqui.
    import re as _re
    correo = _re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", _re.I)
    arroba = _re.compile(r"@[a-z0-9._]{3,}", _re.I)
    for donde, texto in (("la plantilla", crudo), ("el código", src)):
        check(not correo.search(texto), f"{donde} no lleva ninguna direccion de correo")
    check(not arroba.search(crudo), "la plantilla no lleva ninguna cuenta con arroba")
    check(ig.perfil_como_texto(ig.PERFIL_VACIO) == "",
          "un perfil vacío no aporta contexto (no se inventa nada)")


# ══════════════ 3. El contexto COMPLETO del usuario ══════════════
def test_contexto_completo():
    print("· el perfil admite el contexto completo de quien tenga la cuenta")
    p = ig.PERFIL_VACIO
    for camino in (("nicho",), ("publico", "dolores"), ("idiomas", "comentarios"),
                   ("idiomas", "respuesta"), ("personal", "hijos"),
                   ("personal", "profesion"), ("personal", "situacion_familiar"),
                   ("personal", "idiomas_que_habla"), ("personal", "temas_que_no_toca"),
                   ("tono", "estilo"), ("negocio", "objetivo"), ("negocio", "productos"),
                   ("negocio", "lead_magnets"), ("cuenta", "business_account_id")):
        d = p
        ok = True
        for k in camino:
            if not isinstance(d, dict) or k not in d:
                ok = False
                break
            d = d[k]
        check(ok, "el perfil contempla " + " → ".join(camino))

    # el ejemplo del disco se lee y se convierte en contexto legible
    ej = json.loads((ROOT / "skills" / "instagram" / "perfil.ejemplo.json")
                    .read_text(encoding="utf-8"))
    txt = ig.perfil_como_texto(ej)
    for trozo in ("Nicho:", "Responde y analiza en:", "Quién está detrás de la cuenta:",
                  "hijo", "NO propongas contenido sobre:", "Lead magnet:"):
        check(trozo in txt, f"el contexto en prosa incluye «{trozo}»")
    check("años" in txt, "y la edad de los hijos, que cambia las ideas de contenido")


# ══════════════ 4. Varios perfiles, uno por cuenta ══════════════
def test_varios_perfiles():
    print("· admite varias cuentas, no solo la de uno")
    a = json.loads(json.dumps(ig.PERFIL_VACIO)); a["id"] = "cuenta_a"; a["nicho"] = "viajes"
    b = json.loads(json.dumps(ig.PERFIL_VACIO)); b["id"] = "cuenta_b"; b["nicho"] = "finanzas"
    ig.guardar_perfil(CTX, a)
    ig.guardar_perfil(CTX, b)
    d = ig.cargar_perfiles(CTX)
    check(set(d["perfiles"]) == {"cuenta_a", "cuenta_b"}, "guarda los dos perfiles")
    check(d["activo"] == "cuenta_b", "y recuerda cuál está activo")
    check(ig.perfil_activo(CTX)["nicho"] == "finanzas", "el activo es el que se usa")
    ig.guardar_perfil(CTX, a)
    check(ig.perfil_activo(CTX)["nicho"] == "viajes", "se puede cambiar de cuenta")


# ══════════════ 5. Editar por chat ══════════════
def test_editar_por_chat():
    print("· se rellena hablando, campo a campo")
    load_skills()
    casos = [("instagram nicho: cocina sin gluten", "nicho", "cocina sin gluten"),
             ("instagram idiomas: es, en, pt", "idiomas", ["es", "en", "pt"]),
             ("instagram objetivo: vender mi curso", "objetivo", "vender mi curso")]
    for orden, campo, esperado in casos:
        r = route(orden)
        check(r is not None and r[0].folder == "instagram" and r[1] == "ig_perfil_set",
              f"«{orden}» enruta al perfil ({r[1] if r else 'nada'})")
        if r:
            res = run(ig.handle(r[1], orden, r[2], CTX))
            check("✔" in res["reply"], f"y confirma el cambio: {res['reply'][:60]}")
    p = ig.perfil_activo(CTX)
    check(p.get("nicho") == "cocina sin gluten", f"el nicho quedó guardado ({p.get('nicho')})")
    check(p["idiomas"]["comentarios"] == ["es", "en", "pt"],
          f"los idiomas se guardan como lista ({p['idiomas']['comentarios']})")
    r = route("instagram hijos: Leo (3 años), Vera (7)")
    if r:
        run(ig.handle(r[1], "instagram hijos: Leo (3 años), Vera (7)", r[2], CTX))
    hijos = ig.perfil_activo(CTX)["personal"]["hijos"]
    check(len(hijos) == 2 and hijos[0]["nombre"] == "Leo" and hijos[0]["edad"] == "3",
          f"«hijos: Leo (3 años), Vera (7)» se guarda con nombre y edad ({hijos})")


# ══════════════ 6. Sin credenciales no se inventa nada ══════════════
def test_sin_credenciales():
    print("· sin token, dice qué falta en vez de fallar")
    settings.set_secret("ig_access_token", "")
    settings.set("ig_business_account_id", "")
    tok, bid = ig.credenciales(CTX)
    check(not tok and not bid, "de fábrica no hay credenciales puestas")
    load_skills()
    r = route("analiza mis últimos 3 reels")
    res = run(ig.handle(r[1], "analiza mis últimos 3 reels", r[2], CTX))
    for trozo in ("token", "ID", "instagram_manage_comments"):
        check(trozo in res["reply"], f"explica que falta «{trozo}»")
    check("⚙" in res["reply"], "y dónde ponerlo")
    r = route("estado de instagram")
    res = run(ig.handle(r[1], "estado de instagram", r[2], CTX))
    check("✖" in res["reply"] and "Token" in res["reply"],
          f"el estado lo dice claro: {res['reply'][:70]}")
    # el perfil SÍ se puede trabajar sin token
    r = route("perfil de instagram")
    res = run(ig.handle(r[1], "perfil de instagram", r[2], CTX))
    check("cocina sin gluten" in res["reply"], "el perfil se consulta sin necesitar token")


# ══════════════ 7. El token no se pasea por la línea de comandos ══════════════
def test_token_no_se_expone():
    print("· el token no viaja donde pueda verse")
    src = (ROOT / "skills" / "instagram" / "skill.py").read_text(encoding="utf-8")
    check("INSTAGRAM_ACCESS_TOKEN" in src and "entorno" in src,
          "las credenciales van por variables de entorno")
    i_args = src.find("subprocess.run([sys.executable")
    trozo = src[i_args:i_args + 400]
    check("token" not in trozo, "y NO como argumento del proceso")
    check('secret("ig_access_token")' in src, "el token sale del almacén de secretos de nexus")
    igpy = (ROOT / "skills" / "instagram" / "scripts" / "ig.py").read_text(encoding="utf-8")
    check("os.environ.get(\"INSTAGRAM_ACCESS_TOKEN\")" in igpy,
          "el script lee las credenciales del entorno")
    check("redact" in igpy, "y el script tapa el token en sus errores")
    # nada de .env con el token dentro de la carpeta de la skill
    check(not (ROOT / "skills" / "instagram" / ".env").exists(),
          "no se ha dejado ningún .env con credenciales")


# ══════════════ 8. El prompt del análisis ══════════════
def test_prompt():
    print("· el análisis se hace CON el contexto y con las reglas correctas")
    ej = json.loads((ROOT / "skills" / "instagram" / "perfil.ejemplo.json")
                    .read_text(encoding="utf-8"))
    p = ig.prompt_analisis(ej, '{"comentarios": []}')
    check("cocina sin gluten" in p, "el nicho del usuario entra en el prompt")
    check("hijo" in p.lower(), "y su situación personal")
    check("NO propongas contenido sobre" in p, "y los temas vetados")
    check("is_from_owner=true" in p and "is_trigger=true" in p,
          "el sentimiento excluye los comentarios del dueño y las palabras-CTA")
    check("INVIERTE" in p or "invierte" in p, "y para leads la lógica se invierte")
    check("caption" in p, "recuerda buscar la palabra-imán de cada reel")
    check("no inventes" in p.lower() or "No inventes" in p or "no inventes ninguno" in p.lower(),
          "prohíbe inventar comentarios")
    vacio = ig.prompt_analisis(ig.PERFIL_VACIO, "{}")
    check("todavía no ha rellenado su perfil" in vacio,
          "sin perfil, el prompt lo dice en vez de inventarse el contexto")


# ══════════════ 9. No le roba órdenes a nadie ══════════════
def test_no_secuestra():
    print("· sus patrones no pisan a las demás skills")
    load_skills()
    ajenas = ["qué hora es", "pon música", "enciende la tele", "apaga el ordenador",
              "qué tiempo hace en Madrid", "crea una tarea nueva", "lee el archivo notas.md",
              "cuánto es 2+2", "abre spotify", "manda un whatsapp a Ana",
              "analiza este documento", "resume mis correos", "haz una copia de seguridad"]
    for orden in ajenas:
        r = route(orden)
        folder = r[0].folder if r else None
        check(folder != "instagram", f"«{orden}» NO va a instagram (va a {folder})")
    for orden in ("analiza mis reels", "mis últimos reels", "perfil de instagram",
                  "estado de instagram", "saca los leads de mis reels"):
        r = route(orden)
        check(r is not None and r[0].folder == "instagram",
              f"«{orden}» sí va a instagram (fue a {r[0].folder if r else 'nada'})")


def main() -> int:
    for f in (test_instalada, test_plantilla_vacia, test_contexto_completo,
              test_varios_perfiles, test_editar_por_chat, test_sin_credenciales,
              test_token_no_se_expone, test_prompt, test_no_secuestra):
        try:
            f()
        except Exception as e:                                    # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCIÓN en {f.__name__}: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_SAND, ignore_errors=True)
    sys.exit(code)
