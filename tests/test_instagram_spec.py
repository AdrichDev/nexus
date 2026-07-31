# -*- coding: utf-8 -*-
"""CRITERIOS DE ACEPTACIÓN de la herramienta de análisis de reels.

Los seis del punto 8 de la especificación, uno por uno, más los módulos que
entraron con ella (objeciones, cola editorial, conversión) y la ingesta.

No comprueban que exista el código: comprueban que el resultado es el que la
especificación exige. Un test que solo mira si un fichero contiene una palabra
no prueba nada.

Ejecutar:  python tests/test_instagram_spec.py   (desde la carpeta nexus)
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


A = _mod("iganal", ROOT / "skills" / "instagram" / "analisis.py")
IG = _mod("igscript", ROOT / "skills" / "instagram" / "scripts" / "ig.py")


def com(user, texto, owner=False):
    return {"username": user, "text": texto, "timestamp": "2026-07-30T10:00:00+0000",
            "is_from_owner": owner, "is_trigger": False, "matched_trigger": None}


KW = ["QUIERO LA PLANTILLA"]


def escenario():
    """Un reel de verdad: leads, erratas, preguntas, objeciones, ruido y odio."""
    flat = ([com("yo", "va para ti", owner=True)] * 6
            + [com(f"u{i}", "QUIERO LA PLANTILLA") for i in range(50)]
            + [com(f"t{i}", "plantila") for i in range(7)]
            + [com("p1", "¿qué micro usas para grabar?"),
               com("p2", "el micro ese de dónde lo has sacado"),
               com("p3", "cómo grabas con ese micro"),
               com("p4", "¿cuánto tiempo lleva montarlo?"),
               com("o1", "me parece caro para empezar"),
               com("o2", "muy caro la verdad"),
               com("o3", "no sé si me sirve en mi caso"),
               com("c1", "me interesa para mi empresa, ¿cuál es el precio?"),
               com("h1", "esto es un timo, menuda estafa")]
            + [com(f"e{i}", "🔥") for i in range(9)])
    clas = A.clasificar(flat, KW)
    sust = clas["cestas"]["sustantivo"]
    met = A.metricas({"insights": {"reach": 24000, "total_interactions": 3100,
                                   "likes": 1900, "saved": 640, "shares": 210}}, clas)
    ld = A.leads(clas, atendidos=51)
    du, ob = A.dudas(sust), A.objeciones(sust)
    return {"media": {"id": "R1", "permalink": "https://instagram.com/p/r1/",
                      "timestamp": "2026-07-30", "media_type": "REELS",
                      "caption": "Comenta PLANTILLA y te la mando"},
            "metricas": met, "clasificacion": clas, "leads": ld,
            "sentimiento": A.sentimiento({"positivo": 5, "neutral": 2, "friccion": 2}, len(sust)),
            "odio": A.cuenta_odio(sust), "dudas": du, "objeciones": ob,
            "cola": A.cola_editorial(du, ob, ld["calientes"]),
            "conversion": A.conversion(ld["unicos"], {"dm_enviados": 51, "dm_abiertos": 38,
                                                      "clics": 14, "ventas": 2}),
            "retencion": A.retencion({"insights": {"ig_reels_avg_watch_time": 7400}}),
            "distribucion": A.distribucion({"insights": {"follows": 34, "profile_visits": 210}}),
            "benchmark": A.benchmark({"reach": 24000, "saved": 640},
                                     [{"reach": 30000, "saved": 400},
                                      {"reach": 26000, "saved": 500}])}


# ══════════ CRITERIO 1: métricas con lectura interpretada y ratios ══════════
def test_c1_metricas_con_lectura_y_ratios():
    print("· 1. la tabla de métricas sale con su lectura y sus ratios")
    ctx = escenario()
    m = ctx["metricas"]
    etiquetas = [f[0] for f in m["filas"]]
    for q in ("Alcance", "Interacciones", "Me gusta", "Comentarios", "Guardados",
              "Compartidos", "Personas que comentaron"):
        check(q in etiquetas, f"está la métrica «{q}»")
    check("Impresiones" in etiquetas, "y las impresiones (aunque sea para decir que no constan)")
    # el ratio es una división de verdad, no un adorno
    fila_guard = [f for f in m["filas"] if f[0] == "Guardados"][0]
    check(abs(fila_guard[2] - round(640 / 24000 * 100, 1)) < 0.05,
          f"el ratio de guardados sobre alcance está bien calculado (dio {fila_guard[2]})")
    check(m["lecturas"].get("Guardados"), "y trae lectura interpretada, no solo el número")
    check(m["comentaristas_unicos"] > 0, "cuenta personas distintas")
    # la lectura cambia con el dato: no es un texto fijo
    fuerte = A.metricas({"insights": {"reach": 24000, "saved": 1900}}, ctx["clasificacion"])
    check(fuerte["lecturas"].get("Guardados") != m["lecturas"].get("Guardados"),
          "y la lectura CAMBIA con la cifra: no es una frase decorativa")


# ══════════ CRITERIO 2: los subtotales cuadran con el total ══════════
def test_c2_los_subtotales_cuadran():
    print("· 2. CTA + sustantivos + sin clasificar + tuyos = total, siempre")
    ctx = escenario()
    clas = ctx["clasificacion"]
    c = clas["conteo"]
    check(sum(c.values()) == clas["total"], "las cuatro cestas suman el total exacto")
    check(clas["cuadra"] and clas["descuadre"] == 0, "y se certifica que cuadra")
    # y si alguna vez NO cuadrara, tiene que verse en el informe
    roto = dict(clas)
    roto["cuadra"], roto["descuadre"], roto["suma"] = False, 15, clas["total"] - 15
    md = A.informe_md({**ctx, "clasificacion": roto})
    check("DESCUADRA" in md, "y si no cuadrara, el informe lo diría en vez de disimular")
    # ningún comentario se cae por el camino
    todos = sum(len(v) for v in clas["cestas"].values())
    check(todos == clas["total"], "ningún comentario se pierde entre cestas")


# ══════════ CRITERIO 3: leads captados vs atendidos, con el hueco ══════════
def test_c3_leads_coherentes_y_hueco():
    print("· 3. leads captados y atendidos cuadran, y el hueco se dice")
    ctx = escenario()
    ld = ctx["leads"]
    check(ld["unicos"] == 57, f"57 personas distintas: 50 + 7 erratas (dio {ld['unicos']})")
    check(ld["con_errata"] == 7, f"las 7 erratas se recogen (dio {ld['con_errata']})")
    check(ld["tasa_variantes"] > 0,
          f"y se dice qué porcentaje se salva por tolerar erratas ({ld['tasa_variantes']} %)")
    check(ld["hueco"] == 6, f"quedan 6 sin atender (dio {ld.get('hueco')})")
    md = A.informe_md(ctx)
    check("6 sin atender" in md, "y el informe lo nombra")
    check(ld["cta_totales"] >= ld["unicos"], "los comentarios CTA nunca son menos que las personas")
    check(any("empresa" in x["comentario"] for x in ld["calientes"]),
          "el lead caliente por intención de negocio se detecta aparte")


# ══════════ CRITERIO 4: el sentimiento lleva tamaño de muestra ══════════
def test_c4_sentimiento_con_muestra():
    print("· 4. cada porcentaje de sentimiento va con su n y su banda")
    ctx = escenario()
    s = ctx["sentimiento"]
    check(s["n"] == len(ctx["clasificacion"]["cestas"]["sustantivo"]),
          "la muestra es el nº real de comentarios con contenido")
    for cat, d in s["categorias"].items():
        check("banda" in d and d["banda"][1] > d["banda"][0],
              f"«{cat}» lleva banda de confianza real")
        check(d["n"] <= s["n"], f"«{cat}» no puede tener más casos que la muestra")
    check(s["aviso"], "con una muestra así, avisa de que son orientativos")
    pa = A.panel(ctx)
    sec = [x for x in pa["secciones"] if x["id"] == "sentimiento"][0]
    check(all("banda" in c for c in sec["categorias"]),
          "y en el panel el porcentaje NUNCA sale sin su banda")


# ══════════ CRITERIO 5: existen retención, distribución, conversión y benchmark ══════════
def test_c5_los_cuatro_modulos_que_faltaban():
    print("· 5. retención, distribución, conversión y benchmark, con datos")
    ctx = escenario()
    r = ctx["retencion"]
    check(any("Tiempo medio" in e for e, _, _ in r["hay"]), "retención usa lo que la API sí da")
    check("3 primeros segundos" in r["nota"], "y declara el gancho de 3 s que la API no da")
    d = ctx["distribucion"]
    check(any("seguidores" in str(e).lower() for e, _, _ in d["hay"]),
          f"distribución trae los nuevos seguidores ({d['hay']})")
    check("seguidores" in d["nota"], "y declara el reparto que la API no da")
    cv = ctx["conversion"]
    check(cv["hay"], "conversión tiene embudo cuando hay datos registrados")
    pasos = {f["paso"]: f for f in cv["filas"]}
    check("DM enviados" in pasos and pasos["DM enviados"]["tasa"] is not None,
          "cada paso lleva su tasa respecto al anterior")
    check(cv["tasa_global"] is not None, "y la tasa global de lead a venta")
    b = ctx["benchmark"]
    check(b["hay"] and b["filas"], "benchmark compara contra los reels anteriores")
    por = {f["metrica"]: f for f in b["filas"]}
    check(por["reach"]["delta"] < 0 < por["saved"]["delta"],
          "y las variaciones tienen el signo correcto")


# ══════════ CRITERIO 6: solo lectura, sin tocar la cuenta ══════════
def test_c6_solo_lectura():
    print("· 6. nada de esto modifica la cuenta")
    fuente = (ROOT / "skills" / "instagram" / "scripts" / "ig.py").read_text(encoding="utf-8")
    check('method="POST"' not in fuente and "method='POST'" not in fuente,
          "el script de ingesta no hace ni un POST")
    check("DELETE" not in fuente, "ni un DELETE")
    check(re.search(r"urlopen\(", fuente), "solo lee (urlopen sobre GET)")
    ctx = escenario()
    check(A.panel(ctx)["solo_lectura"] is True, "el panel lo deja escrito")
    check("solo lectura" in A.informe_md(ctx), "y el informe también")


# ══════════ MÓDULOS NUEVOS: objeciones, cola editorial ══════════
def test_objeciones_son_senal():
    print("· una objeción es una señal, y el odio no es una objeción")
    ctx = escenario()
    tipos = {o["tipo"]: o for o in ctx["objeciones"]}
    check("precio" in tipos and tipos["precio"]["veces"] == 3,
          f"agrupa las tres pegas de precio, incluida la del que quiere comprar "
          f"({tipos.get('precio', {}).get('veces')})")
    check("encaje" in tipos, "y la de «no sé si me sirve a mí»")
    check(all("timo" not in e for o in ctx["objeciones"] for e in o["ejemplos"]),
          "el insulto NO entra como objeción: insultar no es argumentar")
    check(ctx["odio"][0] == 1, f"pero se cuenta aparte como odio (dio {ctx['odio'][0]})")
    check(all(o["lectura"] for o in ctx["objeciones"]), "cada tipo dice qué significa")


def test_cola_editorial_priorizada():
    print("· la cola editorial sale ordenada y con quién lo pidió")
    ctx = escenario()
    cola = ctx["cola"]
    check(len(cola) >= 2, f"hay cola de temas ({len(cola)})")
    prios = [x["prioridad"] for x in cola]
    check(prios == sorted(prios, reverse=True), "ordenada de más a menos prioritaria")
    micro = [x for x in cola if "micro" in x["titulo"]]
    check(micro and micro[0]["veces"] == 3,
          f"la duda del micro la preguntan 3 veces ({micro[0]['veces'] if micro else '-'})")
    check(all(x["gancho"] for x in cola), "cada idea trae gancho")
    check(all(x["por_que"] for x in cola), "y por qué está en la lista")
    check(any(x["usuarios"] for x in cola), "con los usuarios que la justifican")
    # determinista: dos veces el mismo reel, el mismo orden
    otra = A.cola_editorial(ctx["dudas"], ctx["objeciones"], ctx["leads"]["calientes"])
    check([x["titulo"] for x in otra] == [x["titulo"] for x in cola],
          "y el orden es el mismo siempre: es una cuenta, no una opinión")


def test_conversion_no_se_inventa_nada():
    print("· el embudo no rellena lo que no le das")
    vacio = A.conversion(120)
    check(not vacio["hay"], "sin datos registrados no hay embudo")
    check(len(vacio["faltan"]) == 4, f"y dice los 4 pasos que faltan ({len(vacio['faltan'])})")
    check(all(x["de_donde"] for x in vacio["faltan"]), "diciendo de dónde sacar cada uno")
    check(vacio["tasa_global"] is None, "sin ventas registradas NO se inventa una tasa")
    parcial = A.conversion(120, {"dm_enviados": 100})
    check(parcial["filas"][1]["tasa"] == 83.3, "con lo que hay, calcula")
    check(any(x["que"] == "Clics al imán" for x in parcial["faltan"]),
          "y lo que no hay lo sigue declarando")


# ══════════ EL PANEL: cada cifra con su procedencia ══════════
def test_panel_explica_de_donde_sale_cada_cifra():
    print("· el panel dice de dónde sale y cómo se calcula cada número")
    pa = A.panel(escenario())
    ids = [s["id"] for s in pa["secciones"]]
    for q in ("numeros", "reparto", "leads", "sentimiento", "dudas", "objeciones",
              "cola", "conversion", "retencion", "distribucion", "benchmark"):
        check(q in ids, f"el panel trae la sección «{q}»")
    nums = [s for s in pa["secciones"] if s["id"] == "numeros"][0]
    check(all(f["origen"] for f in nums["filas"]),
          "TODA métrica dice de dónde sale, sin excepción")
    check(any("Graph API" in f["origen"] for f in nums["filas"]), "unas vienen de la API")
    check(any("nexus" in f["origen"] for f in nums["filas"]), "y otras las calcula nexus")
    check(all(s.get("metodo") for s in pa["secciones"]),
          "y cada bloque explica con qué método trabaja")
    check(pa["resumen"]["cuadra"] is True, "el resumen de cabecera dice si la suma cuadra")


# ══════════ LA INGESTA ══════════
def test_ingesta_ritmo_y_metricas():
    print("· la ingesta se adapta al volumen y pide lo que el motor necesita")
    c = IG.GraphClient({"INSTAGRAM_ACCESS_TOKEN": "x", "IG_API_VERSION": "v21.0"},
                       verbose=False)
    base = c._ajusta_ritmo()
    c._llamadas = IG.LLAMADAS_VOLUMEN_ALTO + 5
    alto = c._ajusta_ritmo()
    check(alto > base, f"con mucho volumen baja el ritmo ({base}s → {alto}s)")
    frenado = c._ajusta_ritmo(frenados=True)
    check(frenado > alto, f"y si la API nos frena, más todavía ({frenado}s)")
    check(frenado <= IG.THROTTLE_TECHO, "pero con techo: no se queda parado")
    c._llamadas = 2
    check(c._ajusta_ritmo() == base, "y vuelve al ritmo normal cuando pasa el volumen")
    # el motor busca follows/profile_visits: el script tiene que pedirlos
    primero = IG.INSIGHT_SETS[0]
    for m in ("follows", "profile_visits", "reach", "saved", "shares",
              "ig_reels_avg_watch_time"):
        check(m in primero, f"el set más completo pide «{m}»")
    check(any("follows" not in s for s in IG.INSIGHT_SETS),
          "y hay sets de repuesto por si la versión de la API no acepta alguna")


def main() -> int:
    for f in (test_c1_metricas_con_lectura_y_ratios, test_c2_los_subtotales_cuadran,
              test_c3_leads_coherentes_y_hueco, test_c4_sentimiento_con_muestra,
              test_c5_los_cuatro_modulos_que_faltaban, test_c6_solo_lectura,
              test_objeciones_son_senal, test_cola_editorial_priorizada,
              test_conversion_no_se_inventa_nada,
              test_panel_explica_de_donde_sale_cada_cifra,
              test_ingesta_ritmo_y_metricas):
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
