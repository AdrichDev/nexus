# -*- coding: utf-8 -*-
"""COMPETENCIA: analizar cuentas que NO administras.

Lo que se comprueba aquí es sobre todo lo que la herramienta NO puede hacer y
tiene que decir. De una cuenta ajena la API oficial da lo público —seguidores,
reproducciones, me gusta y cuántos comentarios— y nada más. El texto de sus
comentarios, sus compartidos, sus guardados y su alcance son privados.

Un análisis de competencia que enseñe «sentimiento de sus comentarios» se lo
está inventando o lo ha sacado por scraping. Ninguna de las dos cosas vale.

Ejecutar:  python tests/test_instagram_competencia.py   (desde la carpeta nexus)
"""
import importlib.util
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


A = _mod("iganal", ROOT / "skills" / "instagram" / "analisis.py")
IG = _mod("igscript", ROOT / "skills" / "instagram" / "scripts" / "ig.py")


def pub(i, vistas, likes, coment, tipo="REELS", dia=None):
    return {"id": str(i), "caption": f"publicación {i}", "media_type": "VIDEO",
            "media_product_type": tipo, "permalink": f"https://instagram.com/p/{i}/",
            "timestamp": (dia or "2026-07-%02d" % (i % 28 + 1)) + "T10:00:00+0000",
            "view_count": vistas, "like_count": likes, "comments_count": coment}


def cuenta_rival():
    """Diez reels normales y UN vídeo viral: el caso que rompe las medias."""
    return {"username": "rival", "name": "Rival", "biography": "hace lo mismo que tú",
            "followers_count": 50000, "media_count": 420,
            "media": [pub(i, 20000 + i * 900, 900 + i * 20, 40 + i) for i in range(10)]
                     + [pub(99, 900000, 40000, 3000, "FEED", "2026-07-20")]}


def mi_cuenta():
    return A.mi_perfil_publico("yo", 12000,
                               [pub(i, 9000 + i * 300, 400 + i * 10, 30 + i) for i in range(8)])


# ══════════ 1. UN VIRAL NO PUEDE FALSEAR LA COMPARACIÓN ══════════
def test_la_mediana_aguanta_un_viral():
    print("· un vídeo viral no hace parecer que rinden el triple")
    p = A.perfil_publico("rival", cuenta_rival())
    check(p["hay"], "la cuenta se lee")
    media_aritmetica = sum(m["view_count"] for m in cuenta_rival()["media"]) / 11
    check(p["med_reproducciones"] < media_aritmetica / 3,
          f"la mediana ({p['med_reproducciones']}) no se va detrás del viral "
          f"(la media daría {int(media_aritmetica)})")
    check(p["max_reproducciones"] == 900000, "pero el viral se sigue viendo, aparte")
    check(20000 <= p["med_reproducciones"] <= 30000,
          f"la mediana describe una publicación NORMAL suya ({p['med_reproducciones']})")


# ══════════ 2. LAS MÉTRICAS QUE PIDIÓ ADRI ══════════
def test_estan_las_metricas_publicas():
    print("· reproducciones, me gusta y comentarios de una cuenta ajena")
    p = A.perfil_publico("rival", cuenta_rival())
    check(p["med_reproducciones"] is not None, "reproducciones")
    check(p["med_me_gusta"] > 0, "me gusta")
    check(p["med_comentarios"] > 0, "comentarios")
    check(p["seguidores"] == 50000, "seguidores")
    check(p["engagement"] is not None, "y la interacción sobre seguidores, que es lo comparable")
    check(p["conversacion"] is not None, "más cuánto conversa su público")
    check(p["por_semana"] is not None, "y cada cuánto publica")
    # el ritmo sale de fechas reales, no de una constante
    lento = A.perfil_publico("lento", {"username": "lento", "followers_count": 100,
                                       "media_count": 3,
                                       "media": [pub(1, 10, 1, 0, "REELS", "2026-01-01"),
                                                 pub(2, 10, 1, 0, "REELS", "2026-06-01")]})
    check(lento["por_semana"] < p["por_semana"],
          f"quien publica menos, sale con menos ritmo ({lento['por_semana']} vs {p['por_semana']})")


# ══════════ 3. QUÉ FORMATO LE FUNCIONA ══════════
def test_dice_que_le_funciona():
    print("· qué formato le funciona y qué es lo que más le ha volado")
    p = A.perfil_publico("rival", cuenta_rival())
    check(len(p["formatos"]) == 2, f"separa por formato ({[f['formato'] for f in p['formatos']]})")
    check(p["formatos"][0]["reproducciones"] >= p["formatos"][-1]["reproducciones"],
          "ordenado por lo que mejor le funciona")
    check(len(p["mejores"]) == 5, "y saca sus cinco publicaciones más vistas")
    check(p["mejores"][0]["reproducciones"] == 900000, "la primera es la más vista")
    check(all(m["enlace"] for m in p["mejores"]), "cada una con su enlace para ir a verla")


# ══════════ 4. LO QUE NO SE PUEDE VER, SE DICE ══════════
def test_declara_lo_que_no_se_puede_ver():
    print("· lo que de una cuenta ajena NO se puede ver, se declara")
    comp = A.competencia([{"usuario": "rival", "datos": cuenta_rival()}], mi_cuenta())
    faltan = {x["que"] for x in comp["no_disponible"]}
    check(any("entimiento" in x for x in faltan),
          f"dice que el sentimiento de sus comentarios NO se puede sacar ({faltan})")
    check("Compartidos" in faltan, "ni los compartidos")
    check("Guardados" in faltan, "ni los guardados")
    check(any("Alcance" in x for x in faltan), "ni el alcance")
    check(all(x["por_que"] and x["donde"] for x in comp["no_disponible"]),
          "y de cada uno, por qué y dónde está")
    # y NO puede aparecer un sentimiento inventado por ninguna parte
    p = A.perfil_publico("rival", cuenta_rival())
    check("sentimiento" not in p and "positivo" not in p,
          f"el perfil ajeno NO trae ningún sentimiento inventado ({list(p)})")
    md = A.competencia_md(comp)
    check("no lo estima" in md or "no se puede ver" in md.lower(),
          "y el informe lo deja escrito")
    panel = A.panel_competencia(comp)
    check(any(s["id"] == "limites" for s in panel["secciones"]),
          "el panel del HUD lleva su bloque de límites, no lo esconde")


# ══════════ 5. LA COMPARACIÓN USA LA MISMA VARA ══════════
def test_compara_con_la_misma_vara():
    print("· tu cuenta se mide igual que las suyas, o no se compara nada")
    comp = A.competencia([{"usuario": "rival", "datos": cuenta_rival()}], mi_cuenta())
    check(comp["hay"] and comp["propia"], "estás tú en la comparación")
    fila_eng = [f for f in comp["comparacion"] if "seguidores" in f["metrica"]][0]
    check(len(fila_eng["valores"]) == 2, "una columna por cuenta, la tuya incluida")
    check(any(v["es_tuya"] for v in fila_eng["valores"]), "y la tuya va marcada")
    check(fila_eng["lider"], "se dice quién va por delante en cada métrica")
    # tu engagement es mayor aunque tengas menos seguidores: eso es lo que hay que ver
    mio = [v["valor"] for v in fila_eng["valores"] if v["es_tuya"]][0]
    suyo = [v["valor"] for v in fila_eng["valores"] if not v["es_tuya"]][0]
    check(mio > suyo and fila_eng["lider"] == "yo",
          f"con menos seguidores puedes ganar en interacción ({mio} vs {suyo})")
    check(comp["brechas"], "y sale dónde estás por debajo")
    peor = comp["brechas"][0]
    check(peor["diferencia"] <= comp["brechas"][-1]["diferencia"],
          "ordenado de lo peor a lo mejor")
    check(peor["que"] == "reproducciones",
          f"lo peor aquí son las reproducciones ({peor['que']} {peor['diferencia']}%)")


# ══════════ 6. UNA CUENTA QUE NO SE PUEDE CONSULTAR ══════════
def test_cuenta_que_no_se_puede_consultar():
    print("· si una cuenta no se puede consultar, se dice por qué")
    comp = A.competencia([
        {"usuario": "rival", "datos": cuenta_rival()},
        {"usuario": "personal", "datos": {"error": "no se ha podido consultar esa cuenta",
                                          "motivos": ["la cuenta no es Business/Creator",
                                                      "la cuenta es privada"]}}], mi_cuenta())
    check(len(comp["cuentas"]) == 1, "la que sí se puede, se analiza")
    check(len(comp["fallidas"]) == 1, "y la que no, no desaparece del informe")
    f = comp["fallidas"][0]
    check(f["motivos"], f"se dan los motivos posibles ({f['motivos']})")
    md = A.competencia_md(comp)
    check("personal" in md and "Business" in md,
          "el informe la nombra y explica por qué no ha salido")
    # sin ninguna cuenta válida, no se finge que hay comparativa
    vacia = A.competencia([{"usuario": "x", "datos": {"error": "nada"}}], None)
    check(not vacia["hay"], "sin ninguna cuenta consultable, no hay comparativa")
    check(A.panel_competencia(vacia)["hay"] is False, "y el HUD tampoco la finge")


# ══════════ 7. LA BAJADA: SOLO LA VÍA OFICIAL ══════════
def test_solo_via_oficial():
    print("· se baja por la API oficial, no por scraping")
    fuente = (ROOT / "skills" / "instagram" / "scripts" / "ig.py").read_text(encoding="utf-8")
    check("business_discovery" in fuente, "usa business_discovery, la vía oficial")
    for prohibido in ("instagram.com/graphql", "__a=1", "BeautifulSoup", "selenium",
                      "www.instagram.com/p/", "scrape"):
        check(prohibido not in fuente, f"nada de «{prohibido}»: eso sería scraping")
    check("graph.facebook.com" in fuente, "todo va contra la Graph API")
    check(len(IG.CAMPOS_MEDIA_AJENA) >= 2,
          "hay juegos de campos de repuesto por si la versión de la API rechaza alguno")
    check("view_count" in IG.CAMPOS_MEDIA_AJENA[0],
          "el juego más completo pide las reproducciones")
    check("view_count" not in IG.CAMPOS_MEDIA_AJENA[-1],
          "y el de repuesto no, para que una versión antigua no tire la petición entera")
    check(all("followers_count" in p for p in IG.CAMPOS_PERFIL_AJENO[:1]),
          "y los seguidores, que son la base de la comparación")
    quees = {l["que"] for l in IG.LIMITES_CUENTAS_AJENAS}
    check(any("comentarios" in q for q in quees),
          "el script ya declara que el texto de los comentarios no viene")


def main() -> int:
    for f in (test_la_mediana_aguanta_un_viral, test_estan_las_metricas_publicas,
              test_dice_que_le_funciona, test_declara_lo_que_no_se_puede_ver,
              test_compara_con_la_misma_vara, test_cuenta_que_no_se_puede_consultar,
              test_solo_via_oficial):
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
