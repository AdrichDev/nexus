# -*- coding: utf-8 -*-
"""FASE 2: encontrar competidores por internet y validarlos contra Meta.

Las dos mitades se comprueban por separado, porque son dos cosas distintas:
descubrir es amplio y difuso (páginas web), validar es exacto (API de Meta).
Lo que NO puede pasar nunca es que una cuenta llegue a un informe sin que Meta
la haya confirmado, o que se caiga sin decir por qué.

Ejecutar:  python tests/test_descubrimiento.py    (desde la carpeta nexus)
"""
import importlib.util
import re
import sys
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


def _mod(nombre, ruta):
    sp = importlib.util.spec_from_file_location(nombre, ruta)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


D = _mod("igdesc", ROOT / "skills" / "instagram" / "descubrimiento.py")
A = _mod("iganal2", ROOT / "skills" / "instagram" / "analisis.py")

MIS_POSTS = [
    {"caption": "Receta de pan sin gluten paso a paso #singluten #celiaquia"},
    {"caption": "Masa madre sin gluten, mi truco #singluten"},
    {"caption": "Pan de molde sin gluten para la semana #singluten"},
    {"caption": "Bizcocho sin gluten esponjoso #reposteria #singluten"},
    {"caption": "Mi despensa sin gluten: qué compro #singluten"},
]
MI_PERFIL = {"nicho": "cocina sin gluten", "subtemas": ["reposteria"],
             "negocio": {"productos": [{"nombre": "Curso de panadería sin gluten"}]}}


# ══════════ 1. EL NICHO SALE DE LO QUE PUBLICAS ══════════
def test_deduce_el_nicho_de_lo_que_publicas():
    print("· el nicho se deduce de tus propias publicaciones")
    n = D.deduce_nicho(MIS_POSTS, MI_PERFIL)
    check("gluten" in n["terminos"], f"saca el tema central ({n['terminos']})")
    check("singluten" in n["hashtags"], f"y tus hashtags ({n['hashtags']})")
    check(n["confianza"] == "alta", "con perfil relleno y publicaciones, la confianza es alta")
    check(not n["aviso"], "y no hace falta avisar de nada")
    # sin perfil relleno funciona igual, pero lo dice
    solo = D.deduce_nicho(MIS_POSTS)
    check(solo["terminos"], f"sin perfil también saca algo ({solo['terminos']})")
    check(solo["aviso"], "pero avisa de que afinaría más con el perfil relleno")
    check(solo["confianza"] != "alta", "y no presume de confianza que no tiene")
    # una palabra suelta de UNA publicación no define una cuenta
    ruido = D.deduce_nicho(MIS_POSTS + [{"caption": "hoy llueve muchisimo en madrid"}])
    check("llueve" not in ruido["terminos"],
          f"una palabra de una sola publicación no es tu nicho ({ruido['terminos']})")
    # sin nada, no se inventa un nicho
    vacio = D.deduce_nicho([])
    check(vacio["terminos"] == [] and vacio["confianza"] == "baja",
          "sin publicaciones no se inventa ningún nicho")


# ══════════ 2. LAS BÚSQUEDAS SON LAS QUE SON ══════════
def test_las_consultas_no_se_repiten():
    print("· las búsquedas salen limpias y sin repetirse")
    n = D.deduce_nicho(MIS_POSTS, MI_PERFIL)
    qs = D.consultas(n)
    check(len(qs) == len(set(qs)), "no se repite ninguna búsqueda")
    check(any("cocina sin gluten" in q for q in qs), f"usa el nicho que TÚ declaraste ({qs[0]})")
    # el fallo que tenía: pegar el nicho declarado + las palabras deducidas daba
    # «cocina sin gluten cocina gluten», la misma búsqueda escrita dos veces
    for q in qs:
        palabras = q.lower().split()
        check(len(palabras) == len(set(palabras)) or "instagram" in q.lower(),
              f"«{q}» no repite palabras")
    check(any("Curso de panadería sin gluten" in q for q in qs),
          "y busca también por tu producto")
    check(D.consultas(n) == qs, "mismo nicho, mismas búsquedas: es determinista")


# ══════════ 3. SACAR CUENTAS DE LOS RESULTADOS, SIN COLAR BASURA ══════════
def test_saca_cuentas_y_descarta_lo_que_no_lo_es():
    print("· de los resultados salen cuentas, no ruido")
    res = [
        {"title": "Las 10 mejores cuentas sin gluten", "url": "https://blog.es/a",
         "snippet": "Sigue a @panrival y a @singlutenmadrid"},
        {"title": "Cuentas de celiaquía", "url": "https://otro.es/b",
         "snippet": "instagram.com/panrival y instagram.com/otracuenta"},
        {"title": "Ruido", "url": "https://x.es/c",
         "snippet": "escríbenos a info@gmail.com y mira instagram.com/p/ABC123/ "
                    "o instagram.com/explore/tags/pan/"},
    ]
    c = D.candidatos(res, excluir=["micuenta"])
    nombres = [x["usuario"] for x in c]
    check("panrival" in nombres, f"coge las cuentas ({nombres})")
    check("singlutenmadrid" in nombres, "las que van con arroba también")
    check("gmail" not in nombres, "un correo NO es una cuenta")
    check("p" not in nombres and "abc123" not in nombres,
          "un enlace a una publicación NO es una cuenta")
    check("explore" not in nombres, "ni una sección de Instagram")
    check("micuenta" not in nombres, "y la tuya no se busca a sí misma")
    check(nombres[0] == "panrival",
          f"primero la que sale en MÁS páginas distintas ({nombres})")
    check(len(c[0]["fuentes"]) == 2, "y se guarda de dónde ha salido cada una")


# ══════════ 4. ¿ESTA CUENTA COMPITE DE VERDAD CONMIGO? ══════════
def test_filtra_las_que_no_son_de_mi_sector():
    print("· una cuenta que no es de lo tuyo no entra")
    n = D.deduce_nicho(MIS_POSTS, MI_PERFIL)
    buena = D.pertinencia(
        {"bio": "Recetas sin gluten para celiacos", "seguidores": 40000,
         "mejores": [{"caption": "pan sin gluten casero"}]}, n, 12000)
    check(buena["encaja"], f"la del sector encaja ({buena['por_que']})")
    check(buena["liga"] == "tu liga", f"y se dice si es de tu tamaño ({buena['liga']})")
    mala = D.pertinencia(
        {"bio": "Reparación de motos clásicas", "seguidores": 30000,
         "mejores": [{"caption": "restauramos una bultaco del 74"}]}, n, 12000)
    check(not mala["encaja"], "la que no es del sector NO encaja")
    check(mala["por_que"], f"y se dice por qué se cae ({mala['por_que']})")
    gigante = D.pertinencia(
        {"bio": "Recetas sin gluten", "seguidores": 4000000, "mejores": []}, n, 12000)
    check(gigante["liga"] == "mucho más grande",
          "y avisa cuando te comparas con alguien de otra liga")


# ══════════ 5. LO QUE APORTAS TÚ VA MARCADO ══════════
def test_lo_aportado_a_mano_no_se_disfraza_de_verificado():
    print("· lo que apuntas a mano no se mezcla con lo verificado")
    f = D.ficha_manual("@personal", {"seguidores": 8000, "me_gusta": 300,
                                     "comentarios": 20}, "2026-07-30")
    check(f["usuario"] == "personal", "guarda el usuario sin la arroba")
    check(f["fuente"] == "aportado" and f["verificado"] is False,
          "marcado como aportado por ti, NUNCA como verificado")
    check(f["cuando"] == "2026-07-30", "con la fecha de cuándo lo miraste")
    check(f["seguidores"] == 8000 and f["med_me_gusta"] == 300, "con sus cifras")
    check("no verificados" in f["aviso"], f"y con el aviso puesto ({f['aviso'][:50]})")
    vacia = D.ficha_manual("@nadie", {})
    check(not vacia["hay"], "sin cifras, no hay ficha que valga")


# ══════════ 6. NADIE ENTRA AL INFORME SIN QUE META LO CONFIRME ══════════
def test_sin_validar_no_entra_nadie():
    print("· una cuenta sin confirmar por Meta no llega al informe")
    # así es como el flujo mete lo validado en la comparativa
    rival = {"username": "panrival", "followers_count": 40000, "media_count": 300,
             "biography": "recetas sin gluten",
             "media": [{"id": "1", "caption": "pan sin gluten", "media_type": "VIDEO",
                        "media_product_type": "REELS", "permalink": "https://x/1",
                        "timestamp": "2026-07-10T10:00:00+0000", "view_count": 20000,
                        "like_count": 900, "comments_count": 40}]}
    comp = A.competencia([{"usuario": "panrival", "datos": rival},
                          {"usuario": "fantasma", "datos": {"error": "no consultable",
                                                            "motivos": ["es personal"]}}],
                         None)
    check(len(comp["cuentas"]) == 1, "solo entra la que Meta confirma")
    check(len(comp["fallidas"]) == 1, "y la otra no desaparece: se reporta")
    check(comp["fallidas"][0]["motivos"], "con el motivo por el que se ha caído")
    md = A.competencia_md(comp)
    check("fantasma" in md, "el informe la nombra igualmente")
    check("no lo estima" in md or "NO se puede ver" in md,
          "y sigue declarando lo que no se puede ver de una cuenta ajena")


# ══════════ 7. LAS ÓRDENES NUEVAS NO PISAN A LAS DE ANTES ══════════
def test_las_ordenes_no_se_pisan():
    print("· las órdenes nuevas no se comen a las que ya había")
    sys.path.insert(0, str(ROOT))
    sk = _mod("igskill2", ROOT / "skills" / "instagram" / "skill.py")
    pats = sk.SKILL["patterns"]

    def cual(t):
        for nombre, rx in pats.items():
            if re.search(rx, t, re.IGNORECASE):
                return nombre
        return None

    casos = [("busca competidores", "ig_descubrir"),
             ("quiénes son mi competencia", "ig_descubrir"),
             ("analiza mi nicho", "ig_descubrir"),
             ("conecta mi cuenta de instagram", "ig_descubrir"),
             ("apunta la cuenta @personal: 8000 seguidores", "ig_manual"),
             ("analiza la cuenta @rival", "ig_competencia"),
             ("apunta en el reel 17: 40 dm enviados", "ig_conversion"),
             ("analiza mis últimos 3 reels", "ig_analizar"),
             ("mis reels", "ig_listar"),
             ("perfil de instagram", "ig_perfil_ver")]
    for texto, esperado in casos:
        check(cual(texto) == esperado,
              f"«{texto}» → {esperado} (dio {cual(texto)})")
    check("competencia" in sk.PERFIL_VACIO and sk.PERFIL_VACIO["competencia"] == [],
          "el perfil admite competidores tuyos, y se entrega vacío")
    check("busquedas_extra" in sk.PERFIL_VACIO,
          "y búsquedas propias por si las tuyas son mejores")


def main() -> int:
    for f in (test_deduce_el_nicho_de_lo_que_publicas,
              test_las_consultas_no_se_repiten,
              test_saca_cuentas_y_descarta_lo_que_no_lo_es,
              test_filtra_las_que_no_son_de_mi_sector,
              test_lo_aportado_a_mano_no_se_disfraza_de_verificado,
              test_sin_validar_no_entra_nadie,
              test_las_ordenes_no_se_pisan):
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
    sys.exit(main())
