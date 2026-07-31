# -*- coding: utf-8 -*-
"""MOTOR DE ANÁLISIS DE REELS — criterios de aceptación.

Tres reglas duras, que son las que separan un informe fiable de uno bonito:

  1. LOS SUBTOTALES CUADRAN CON EL TOTAL. Cada comentario cae en UNA cesta y la
     suma es siempre el total; si sobran o faltan, el informe lo dice.
  2. EL HUECO ENTRE LEADS CAPTADOS Y ATENDIDOS SE REPORTA, no se redondea.
  3. EL SENTIMIENTO LLEVA TAMAÑO DE MUESTRA Y BANDA DE CONFIANZA: un porcentaje
     a secas sobre una muestra pequeña engaña.

Y los módulos completos: retención, distribución, conversión y comparación con
reels anteriores. Cuando la API no da un dato, el informe tiene que DECIRLO, no
rellenarlo.

Ejecutar:  python tests/test_instagram_analisis.py    (desde la carpeta nexus)
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


_spec = importlib.util.spec_from_file_location(
    "iganal", ROOT / "skills" / "instagram" / "analisis.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def com(user, texto, owner=False, trigger=False):
    return {"username": user, "text": texto, "timestamp": "2026-07-30T10:00:00+0000",
            "is_from_owner": owner, "is_trigger": trigger, "matched_trigger": None}


# ══════════════ 1. Erratas en la palabra-CTA ══════════════
def test_tolera_erratas():
    print("· la palabra-CTA se reconoce aunque la escriban mal")
    kw = ["QUIERO LA PLANTILLA"]
    # cómo la escribe la gente de verdad, a toda prisa y desde el móvil
    for escrito in ("QUIERO LA PLANTILLA", "quiero la plantilla", "plantilla",
                    "PLANTILLA!!", "plantila", "plantiya", "plantillas",
                    "plan tilla", "Plantilla porfa"):
        casa, k, como = A.casa_cta(escrito, kw)
        check(casa, f"«{escrito}» se reconoce como la palabra-CTA (dio {casa})")
    # y NO puede tragarse cualquier cosa
    for ajeno in ("qué monitor usas", "enhorabuena crack", "esto es un timo",
                  "me encanta tu contenido", "cuánto cuesta el curso",
                  "la planta que sale detrás es preciosa"):
        casa, _, _ = A.casa_cta(ajeno, kw)
        check(not casa, f"«{ajeno}» NO es un CTA (dio {casa})")
    # una palabra corta no perdona erratas: se comería medio diccionario
    check(not A.casa_cta("mapa", ["PLAN"])[0], "una keyword corta no tolera erratas")
    check(A.casa_cta("dame el plan", ["PLAN"])[0], "pero sí casa exacta")


# ══════════════ 2. LA ARITMÉTICA CUADRA ══════════════
def test_los_numeros_cuadran():
    print("· todo comentario cae en una cesta y la suma es el total")
    flat = ([com("autor", "gracias!", owner=True)] * 20
            + [com(f"u{i}", "QUIERO LA PLANTILLA") for i in range(40)]
            + [com(f"t{i}", "plantila") for i in range(5)]
            + [com(f"p{i}", "¿qué monitor usas para el panel?") for i in range(8)]
            + [com(f"o{i}", "me parece caro para empezar") for i in range(4)]
            + [com(f"e{i}", "🔥") for i in range(12)]
            + [com(f"x{i}", "top") for i in range(6)])
    clas = A.clasificar(flat, ["QUIERO LA PLANTILLA"])
    c = clas["conteo"]
    check(clas["cuadra"], f"la suma cuadra con el total ({clas['suma']} de {clas['total']})")
    check(clas["descuadre"] == 0, f"sin descuadre (dio {clas['descuadre']})")
    check(sum(c.values()) == len(flat), "las cuatro cestas suman exactamente el total")
    check(c["autor"] == 20, f"20 respuestas del autor (dio {c['autor']})")
    check(c["cta"] == 45, f"45 CTA, erratas incluidas (dio {c['cta']})")
    check(c["sustantivo"] == 12, f"12 con contenido (dio {c['sustantivo']})")
    check(c["sin_clasificar"] == 18, f"18 sin clasificar, y NO se ocultan (dio {c['sin_clasificar']})")
    # el fallo clásico: subtotales que no llegan al total y nadie lo dice
    check(c["cta"] + c["sustantivo"] != clas["total"] - c["autor"] or c["sin_clasificar"] == 0,
          "si CTA+sustantivos no llegan al total, la diferencia está en «sin clasificar»")


# ══════════════ 3. EL HUECO DE LEADS SE REPORTA ══════════════
def test_hueco_de_leads():
    print("· el hueco entre leads captados y atendidos se dice")
    flat = [com(f"u{i}", "QUIERO LA PLANTILLA") for i in range(240)]
    clas = A.clasificar(flat, ["QUIERO LA PLANTILLA"])
    ld = A.leads(clas, atendidos=217)
    check(ld["unicos"] == 240, f"240 personas distintas (dio {ld['unicos']})")
    check(ld["hueco"] == 23, f"y 23 sin atender, contados (dio {ld.get('hueco')})")
    check(ld["con_errata"] == 0,
          f"escribir la palabra bien NO cuenta como errata (dio {ld['con_errata']})")
    clas_t = A.clasificar([com("a", "QUIERO LA PLANTILLA"), com("b", "plantila"),
                           com("c", "plantilla")], ["QUIERO LA PLANTILLA"])
    lt = A.leads(clas_t)
    check(lt["con_errata"] == 1,
          f"solo «plantila» cuenta como errata; «plantilla» es la forma corta "
          f"legítima (dio {lt['con_errata']})")
    md = A.informe_md({"metricas": A.metricas({}, clas), "clasificacion": clas,
                       "leads": ld, "media": {}})
    check("23 sin atender" in md, "el informe lo dice con todas las letras")
    # sin el dato, se admite que no se sabe en vez de dar por bueno el número
    ld2 = A.leads(clas)
    md2 = A.informe_md({"metricas": A.metricas({}, clas), "clasificacion": clas,
                        "leads": ld2, "media": {}})
    check("no consta" in md2, "y si no se sabe, se dice que no consta")
    # un hueco NEGATIVO (más respuestas que personas) también se explica
    md3 = A.informe_md({"metricas": A.metricas({}, clas), "clasificacion": clas,
                        "leads": A.leads(clas, atendidos=1000), "media": {}})
    check("de más" in md3, "y si hay respuestas de más, se dice también")
    # deduplicación: 3 comentarios de la misma persona = 1 lead
    clas3 = A.clasificar([com("ana", "PLANTILLA")] * 3, ["PLANTILLA"])
    check(A.leads(clas3)["unicos"] == 1, "una persona que comenta 3 veces es UN lead")


# ══════════════ 4. SENTIMIENTO CON MUESTRA Y BANDA ══════════════
def test_sentimiento_honesto():
    print("· los porcentajes de sentimiento van con su margen")
    s = A.sentimiento({"positivo": 82, "neutral": 4, "friccion": 2}, n=88)
    check(s["n"] == 88, "guarda el tamaño de muestra")
    pos = s["categorias"]["positivo"]
    check(abs(pos["pct"] - 93.2) < 0.2, f"93,2% positivo (dio {pos['pct']})")
    lo, hi = pos["banda"]
    check(lo < pos["pct"] < hi, f"con una banda real alrededor ({lo}–{hi})")
    check(hi - lo > 4, f"con una muestra así la banda es ancha, no un dato exacto ({hi - lo} puntos)")
    check("orientativos" in s["aviso"], "y avisa de que con esa muestra son orientativos")
    grande = A.sentimiento({"positivo": 900, "neutral": 100}, n=1000)
    check(grande["aviso"] == "", "con muestra grande no molesta con el aviso")
    l2, h2 = grande["categorias"]["positivo"]["banda"]
    check(h2 - l2 < 4, f"y la banda se estrecha ({h2 - l2} puntos)")
    check(A.wilson(0, 0) == (0.0, 0.0), "sin datos no revienta")


# ══════════════ 5. DUDAS AGRUPADAS ══════════════
def test_dudas_agrupadas():
    print("· las mismas dudas escritas distinto se agrupan")
    sust = [com("a", "¿qué monitor usas en el panel?"),
            com("b", "cómo has montado el panel del monitor"),
            com("c", "el monitor ese del panel de dónde es?"),
            com("d", "¿cuánto consume de luz al mes?"),
            com("e", "qué gasto eléctrico tiene eso"),
            com("f", "¿sirve para una empresa pequeña?")]
    d = A.dudas(sust)
    check(len(d) >= 2, f"agrupa en temas ({len(d)} grupos)")
    check(d[0]["veces"] == 3, f"la duda del panel/monitor sale 3 veces (dio {d[0]['veces']})")
    check(len(d[0]["usuarios"]) == 3, "y con quién la hizo")
    check(all("veces" in x and "ejemplo" in x for x in d), "cada grupo lleva su ejemplo real")


# ══════════════ 6. LO QUE LA API NO DA, SE DICE ══════════════
def test_lo_que_falta_se_declara():
    print("· lo que la API no da, se declara en vez de inventarse")
    r = A.retencion({"insights": {"ig_reels_avg_watch_time": 8200}})
    check(any("Tiempo medio" in e for e, _, _ in r["hay"]), "usa lo que sí hay")
    check("8.2 s" in str(r["hay"]), f"convertido a segundos ({r['hay']})")
    check("3 primeros segundos" in r["nota"], "y avisa del gancho de 3 s que no da la API")
    check("hipótesis" in r["nota"], "diciendo que sin eso «alcance bajo» es una hipótesis")
    d = A.distribucion({"insights": {}})
    check("seguidores" in d["nota"], "lo mismo con seguidores vs no seguidores")
    vacio = A.retencion({"insights": {}})
    check(vacio["hay"] == [], "sin datos no se inventa ninguna cifra")


# ══════════════ 7. COMPARACIÓN CON REELS ANTERIORES ══════════════
def test_benchmark():
    print("· cada cifra se compara con tus reels anteriores")
    b = A.benchmark({"reach": 19395, "saved": 826},
                    [{"reach": 30000, "saved": 400}, {"reach": 26000, "saved": 500}])
    check(b["hay"], "hay comparación cuando hay histórico")
    por = {f["metrica"]: f for f in b["filas"]}
    check(por["reach"]["delta"] < 0, f"el alcance sale por debajo de la media ({por['reach']['delta']}%)")
    check(por["saved"]["delta"] > 0, f"y los guardados por encima ({por['saved']['delta']}%)")
    solo = A.benchmark({"reach": 100}, [])
    check(not solo["hay"] and "primer reel" in solo["nota"],
          "con un solo reel se admite que no hay línea base")


# ══════════════ 8. EL INFORME ══════════════
def test_informe():
    print("· el informe sale completo y en Markdown")
    flat = ([com("yo", "gracias", owner=True)] * 3
            + [com(f"u{i}", "PLANTILLA") for i in range(10)]
            + [com("p1", "¿qué monitor usas?"), com("p2", "cuanto cuesta montarlo?"),
               com("c1", "me interesa para mi empresa, cuál es el precio")]
            + [com("e1", "🔥")])
    clas = A.clasificar(flat, ["PLANTILLA"])
    ld = A.leads(clas, atendidos=10)
    ctx = {"media": {"id": "123", "permalink": "https://instagram.com/p/x/",
                     "timestamp": "2026-07-30", "media_type": "REELS",
                     "caption": "Comenta PLANTILLA y te la mando"},
           "metricas": A.metricas({"insights": {"reach": 19395, "saved": 826, "shares": 353,
                                                "likes": 1692, "total_interactions": 4951}}, clas),
           "clasificacion": clas, "leads": ld,
           "sentimiento": A.sentimiento({"positivo": 2, "neutral": 1}, n=3),
           "odio": A.cuenta_odio(clas["cestas"]["sustantivo"]),
           "dudas": A.dudas(clas["cestas"]["sustantivo"]),
           "retencion": A.retencion({"insights": {}}),
           "distribucion": A.distribucion({"insights": {}}),
           "benchmark": A.benchmark({"reach": 19395}, [{"reach": 25000}])}
    md = A.informe_md(ctx)
    for seccion in ("# Análisis de reel", "## Los números", "## De dónde sale cada comentario",
                    "## Leads", "## Sentimiento", "## Lo que más preguntan",
                    "## Retención de vídeo", "## Distribución",
                    "## Comparado con tus reels anteriores"):
        check(seccion in md, f"el informe tiene «{seccion}»")
    check("✔ cuadra" in md, "y certifica que los números cuadran")
    check("| Métrica | Valor | Lectura |" in md, "con tablas de Markdown de verdad")
    check("19.395" in md, "y las cifras formateadas")
    # el nº de personas distintas NO puede depender de que el bundle traiga
    # la lista aplanada: sale de la clasificación, que siempre está
    check(ctx["metricas"]["comentaristas_unicos"] == 14,
          f"cuenta 14 personas distintas (dio {ctx['metricas']['comentaristas_unicos']})")
    check("| Personas que comentaron | 14 |" in md, "y aparece en la tabla")
    check("solo lectura" in md, "deja constancia de que no se ha tocado la cuenta")
    check("CRM" in md, "y apunta al siguiente paso: cruzar los leads con el CRM")
    check(len(md) > 1200, f"es un informe, no cuatro líneas ({len(md)} caracteres)")
    # los leads exportables
    csv_txt = A.leads_csv(ld)
    check(csv_txt.count("\n") == 11, f"el CSV trae cabecera + 10 leads ({csv_txt.count(chr(10))})")
    check("usuario;keyword" in csv_txt, "con las columnas que espera un CRM")
    # el lead caliente detectado por intención de negocio
    check(any("empresa" in x["comentario"] for x in ld["calientes"]),
          f"detecta el lead caliente por intención de negocio ({ld['calientes']})")


# ══════════════ 9. LA PALABRA-GANCHO SE DESCUBRE SOLA ══════════════
# No hay una palabra-gancho «de siempre»: cada campaña usa la suya y cambia de
# un reel al siguiente. nexus no da ninguna por supuesta — la encuentra.
def test_descubre_la_palabra_sola():
    print("· la palabra-gancho se descubre sola, sea la que sea")
    # una campaña cualquiera, con una palabra que nexus no ha visto nunca
    flat = ([com(f"u{i}", "PLANTILLA NOTION") for i in range(60)]
            + [com(f"r{i}", "top") for i in range(15)]
            + [com(f"q{i}", "¿esto sirve para equipos grandes?") for i in range(6)]
            + [com("dueño", "te la mando ahora", owner=True)])
    hallado = A.detecta_cta(flat, caption="Comenta PLANTILLA NOTION y te la mando")
    check(hallado, "encuentra el gancho sin que nadie se lo diga")
    check(hallado[0]["palabra"] == "PLANTILLA NOTION",
          f"y es el correcto: {hallado[0]['palabra']}")
    check(hallado[0]["personas"] == 60, f"con 60 personas detrás (dio {hallado[0]['personas']})")
    check(hallado[0]["en_el_pie"], "confirmado además por el pie del reel")

    # otra campaña completamente distinta: mismo comportamiento
    otra = A.detecta_cta([com(f"x{i}", "RECETA") for i in range(30)]
                         + [com(f"y{i}", "qué pinta tiene todo") for i in range(20)])
    check(otra and otra[0]["palabra"] == "RECETA",
          f"funciona igual con cualquier otra palabra ({otra})")

    # SIN gancho: no se inventa ninguno
    sin = A.detecta_cta([com(f"a{i}", "me ha encantado el vídeo de hoy") for i in range(40)]
                        + [com(f"b{i}", "top") for i in range(30)])
    check(sin == [], f"si el reel no llevaba gancho, no se inventa uno ({sin})")

    # las reacciones de siempre NO son un gancho por mucho que se repitan
    react = A.detecta_cta([com(f"c{i}", "🔥🔥") for i in range(50)]
                          + [com(f"d{i}", "crack") for i in range(40)]
                          + [com(f"e{i}", "gracias") for i in range(30)])
    check(react == [], f"«crack», «gracias» y los emojis no son ganchos ({react})")

    # y hace falta MASA: cuatro personas no son una campaña
    poco = A.detecta_cta([com(f"f{i}", "DOSSIER") for i in range(4)]
                         + [com(f"g{i}", "vaya nivel el montaje") for i in range(96)])
    check(poco == [], f"cuatro comentarios sueltos no son una campaña ({poco})")


# ══════════════ 10. EL PIE SOLO CUENTA SI LO PIDE EXPRESAMENTE ══════════════
def test_el_pie_no_se_inventa_ganchos():
    print("· del pie solo se saca lo que pide comentar de verdad")
    check(A.cta_del_pie("Comenta GUIA y te la mando") == ["GUIA"],
          "coge la palabra que el pie pide comentar")
    check(A.cta_del_pie("escribe LO QUIERO en comentarios")[0].startswith("LO"),
          "también si son dos palabras")
    # el fallo que tenía: un pie normal lleva mayúsculas que NO son ganchos
    for pie in ("NUEVO vídeo GRATIS sobre IA y automatización",
                "Mi setup de 2026 · PARTE 2 · sígueme para más",
                "Lo que aprendí con NOTION, SLACK y ZAPIER este año"):
        check(A.cta_del_pie(pie) == [],
              f"«{pie[:34]}…» no tiene gancho y no se inventa ({A.cta_del_pie(pie)})")


def main() -> int:
    for f in (test_tolera_erratas, test_los_numeros_cuadran, test_hueco_de_leads,
              test_sentimiento_honesto, test_dudas_agrupadas,
              test_lo_que_falta_se_declara, test_benchmark, test_informe,
              test_descubre_la_palabra_sola, test_el_pie_no_se_inventa_ganchos):
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
