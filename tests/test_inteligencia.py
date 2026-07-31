# -*- coding: utf-8 -*-
"""FASE 3: qué está creando una cuenta — ganchos, escritura, ritmo y outliers.

Lo que se comprueba aquí no es que salgan números, sino que los números son
HONESTOS: que con poca muestra no se sienta cátedra, que la mediana aguanta un
viral, y que un «outlier» lo es respecto a la propia cuenta y no respecto a nada
inventado.

Ejecutar:  python tests/test_inteligencia.py    (desde la carpeta nexus)
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


sp = importlib.util.spec_from_file_location(
    "igintel", ROOT / "skills" / "instagram" / "inteligencia.py")
I = importlib.util.module_from_spec(sp)
sp.loader.exec_module(I)


def pub(i, caption, vistas, tipo="REELS", dia=1, hora=10):
    return {"id": str(i), "caption": caption, "media_product_type": tipo,
            "media_type": "VIDEO", "permalink": f"https://ig/{i}",
            "timestamp": f"2026-07-{dia:02d}T{hora:02d}:00:00+0000",
            "view_count": vistas, "like_count": vistas // 20,
            "comments_count": vistas // 200}


# ══════════ 1. EL GANCHO SE CLASIFICA POR LA PRIMERA LÍNEA ══════════
def test_diseca_el_gancho():
    print("· el gancho se saca de la primera línea, que es lo que se lee")
    g = I.gancho("¿Sabías que el pan se puede congelar?\n\nTe cuento cómo #singluten")
    check("pregunta" in g["tipos"], f"reconoce una pregunta ({g['tipos']})")
    check("#singluten" not in g["texto"], "y quita los hashtags del gancho")
    check(g["palabras"] > 0, "cuenta las palabras")
    check("3 errores" in I.gancho("3 errores que arruinan tu masa")["texto"],
          "se queda con la primera línea")
    check("cifra" in I.gancho("3 errores que arruinan tu masa")["tipos"], "y ve la cifra")
    check("negacion" in I.gancho("No uses harina de arroz sola")["tipos"], "y la negación")
    check("historia" in I.gancho("Cuando empecé no sabía ni amasar")["tipos"], "y la historia")
    check("orden" in I.gancho("Mira esto antes de amasar")["tipos"], "y la orden directa")
    check("promesa" in I.gancho("El truco para que no quede seco")["tipos"], "y la promesa")
    check(I.gancho("")["tipos"] == [], "sin pie no se inventa ningún gancho")
    check(I.gancho("Mi receta favorita")["tipos"] == ["llano"],
          "y un gancho sin recurso se llama por su nombre, no se disfraza")
    # el gancho es la PRIMERA línea, no todo el pie
    largo = I.gancho("Mi receta favorita\n¿sabías que se congela?")
    check("pregunta" not in largo["tipos"],
          "lo que va después de la primera línea NO cuenta como gancho")


# ══════════ 2. CON POCA MUESTRA NO SE SIENTA CÁTEDRA ══════════
def test_no_concluye_con_dos_publicaciones():
    print("· con dos publicaciones no se dice qué le funciona")
    pocos = [pub(1, "¿Y esto?", 30000), pub(2, "3 cosas", 90000)]
    p = I.patrones_gancho(pocos)
    check(p["mejor"] is None, f"no elige un ganador ({p['mejor']})")
    check(p["nota"], "y dice por qué no puede")
    check(all(not f["concluyente"] for f in p["filas"]),
          "cada fila va marcada como no concluyente")

    muchos = ([pub(i, f"¿Pregunta {i}?", 30000) for i in range(4)]
              + [pub(i + 10, f"Mi receta {i}", 5000) for i in range(4)])
    p2 = I.patrones_gancho(muchos)
    check(p2["mejor"] == "pregunta", f"con muestra sí decide ({p2['mejor']})")
    check(not p2["nota"], "y ya no hace falta avisar")
    check(next(f for f in p2["filas"] if f["tipo"] == "pregunta")["concluyente"],
          "marcando cuál sí tiene muestra detrás")
    check(all(f["que_es"] for f in p2["filas"]),
          "y cada tipo explica qué es, no solo cómo se llama")


def test_sin_cifras_no_dice_cual_funciona_mejor():
    print("· sin cifras de rendimiento no se elige un ganador")
    # Salió al probar el motor de verdad con pies sacados del buscador: sin
    # métricas detrás, todos los tipos valían 0 y coronaba al primero.
    sin_metricas = [{"id": str(i), "caption": c, "media_product_type": "REELS",
                     "media_type": "VIDEO", "permalink": "", "timestamp": ""}
                    for i, c in enumerate(["Todo empieza con un pensamiento",
                                           "Cada corredor sabe que el impulso",
                                           "Siente la pasion por la carrera",
                                           "¿Nos ayudas a elegir?"])]
    p = I.patrones_gancho(sin_metricas)
    check(p["mejor"] is None, f"no corona a nadie ({p['mejor']})")
    check("no hay cifras" in p["nota"].lower(), f"y dice por qué ({p['nota'][:60]})")
    check(p["filas"], "pero SÍ enseña qué ganchos usa, que eso sí se sabe")
    check(all(f["que_es"] for f in p["filas"]), "con su explicación")
    # y la ficha entera aguanta sin métricas, sin inventarse nada
    r = I.radiografia({"usuario": "x"}, sin_metricas)
    check(r["outliers"]["hay"] is False, "sin cifras no hay picos")
    check("no hay con qué comparar" in r["outliers"]["nota"], "y se dice")
    check(not r["ritmo"]["hay"], "sin fechas no hay ritmo")


# ══════════ 3. UN VIRAL NO DECIDE POR TODOS ══════════
def test_la_mediana_manda():
    print("· un viral no cambia lo que le funciona a una cuenta")
    normales = [pub(i, f"Mi receta {i}", 5000) for i in range(5)]
    con_viral = normales + [pub(99, "Mi receta especial", 900000)]
    a = I.patrones_gancho(normales)["filas"][0]["rendimiento"]
    b = I.patrones_gancho(con_viral)["filas"][0]["rendimiento"]
    check(b < 20000, f"la mediana no se va detrás del viral ({b})")
    check(abs(b - a) < a, f"apenas se mueve respecto a sin viral ({a} → {b})")


# ══════════ 4. OUTLIER = RESPECTO A SÍ MISMO ══════════
def test_los_outliers_son_contra_su_propia_mediana():
    print("· un outlier lo es contra su propia mediana, no contra tu sector")
    posts = [pub(i, f"Mi receta {i}", 5000) for i in range(5)] + \
            [pub(9, "3 errores que arruinan tu masa", 20000)]
    o = I.outliers(posts)
    check(o["hay"], "encuentra el pico")
    check(o["base"] == 5000, f"la base es SU mediana ({o['base']})")
    check(o["lista"][0]["multiplicador"] == 4.0,
          f"y el multiplicador es 4× ({o['lista'][0]['multiplicador']})")
    check("3 errores" in o["lista"][0]["gancho"], "dice con qué gancho lo consiguió")
    check(o["lista"][0]["enlace"], "y deja el enlace para ir a verlo")
    check(o["que_comparten"], f"y qué comparten los picos ({o['que_comparten']})")
    check("mediana de esta misma" in o["nota"], "explicando contra qué se compara")
    # una cuenta regular NO tiene outliers, y eso también se dice
    regular = [pub(i, f"Receta {i}", 5000 + i * 100) for i in range(6)]
    o2 = I.outliers(regular)
    check(not o2["hay"], "una cuenta regular no tiene picos")
    check("sin picos" in o2["nota"], f"y se dice ({o2['nota'][-40:]})")


# ══════════ 5. CÓMO ESCRIBE Y CUÁNDO PUBLICA ══════════
def test_escritura_y_ritmo():
    print("· cómo escribe y cuándo publica salen de datos, no de impresiones")
    posts = [pub(1, "Receta corta", 5000, dia=1, hora=10),
             pub(2, "Otra receta #a #b #c\nComenta GUIA y te la mando", 5000, dia=8, hora=10),
             pub(3, "Tercera receta #a\nLink en bio", 5000, dia=15, hora=21)]
    c = I.anatomia_caption(posts)
    check(c["con_llamada_a_accion"] == 2, f"cuenta las que piden algo ({c['con_llamada_a_accion']})")
    check(abs(c["pct_con_llamada"] - 66.7) < 0.2, f"y su porcentaje ({c['pct_con_llamada']})")
    check("convertir" in c["lectura"], f"con su lectura ({c['lectura'][:40]})")
    check(c["hashtags_mediana"] >= 1, "y cuántos hashtags usa")

    r = I.ritmo(posts)
    check(r["hay"], "el ritmo se calcula")
    check(r["por_semana"] > 0, f"publicaciones por semana ({r['por_semana']})")
    check(r["desde"] and r["hasta"], "diciendo de qué periodo habla")
    # los tres días 1, 8 y 15 de julio de 2026 caen en miércoles: hay muestra
    check(r["mejor_dia"] == "miércoles",
          f"tres publicaciones en el mismo día de la semana SÍ dan para decidir ({r['mejor_dia']})")
    check(not r["nota"], "y entonces no hace falta avisar de nada")
    check(any(f["franja"] == "noche" for f in r["franjas"]), "reparte por franjas del día")
    # pero repartidas en días distintos, ninguno llega al mínimo y se dice
    sueltas = [pub(1, "a", 5000, dia=1), pub(2, "b", 5000, dia=2), pub(3, "c", 5000, dia=3)]
    r2 = I.ritmo(sueltas)
    check(r2["mejor_dia"] is None,
          f"una publicación por día NO da para elegir mejor día ({r2['mejor_dia']})")
    check(r2["nota"], "y se explica por qué")
    check(not I.ritmo([{"caption": "x"}])["hay"], "sin fechas, no se inventa un ritmo")


# ══════════ 6. LA FICHA COMPLETA Y SU INFORME ══════════
def test_la_radiografia_completa():
    print("· la ficha completa sale en Markdown y sin huecos mudos")
    posts = ([pub(i, f"¿Sabías que {i}? #singluten", 20000, dia=i + 1) for i in range(4)]
             + [pub(9, "3 errores del pan sin gluten\nComenta GUIA", 80000, dia=20)])
    r = I.radiografia({"usuario": "panrival"}, posts)
    check(r["suficiente"], "con 5 publicaciones hay para trabajar")
    check(not r["aviso"], "y no hace falta avisar de falta de muestra")
    check(r["gancho"]["mejor"] == "pregunta", f"elige el gancho ({r['gancho']['mejor']})")
    check(r["outliers"]["hay"], "detecta el pico")
    check(r["angulos"], f"y de qué habla ({[a['tema'] for a in r['angulos']]})")

    md = I.radiografia_md(r)
    for trozo in ("Qué está creando", "Cómo engancha", "Cómo escribe",
                  "Cuándo publica", "Lo que se le ha salido de la norma", "De qué habla"):
        check(trozo in md, f"el informe tiene «{trozo}»")
    check("|---|" in md, "con tablas de Markdown de verdad")
    check("panrival" in md, "y dice de quién habla")

    # con una sola publicación, la ficha lo admite en vez de inventarse patrones
    flaca = I.radiografia({"usuario": "poco"}, [pub(1, "Hola", 100)])
    check(not flaca["suficiente"], "con una publicación no da para patrones")
    check("no da para sacar patrones" in flaca["aviso"], "y lo dice claro")
    check("⚠" in I.radiografia_md(flaca) or flaca["aviso"] in I.radiografia_md(flaca),
          "y el informe lo lleva escrito")


# ══════════ 7. DETERMINISTA ══════════
def test_dos_veces_lo_mismo():
    print("· dos análisis de la misma cuenta dan lo mismo")
    posts = [pub(i, f"¿Pregunta {i}? #tema", 10000 + i * 500, dia=i + 1) for i in range(6)]
    a = I.radiografia({"usuario": "x"}, posts)
    b = I.radiografia({"usuario": "x"}, posts)
    check(a == b, "misma entrada, misma salida: sin azar por ningún lado")


def main() -> int:
    for f in (test_diseca_el_gancho, test_no_concluye_con_dos_publicaciones,
              test_sin_cifras_no_dice_cual_funciona_mejor,
              test_la_mediana_manda, test_los_outliers_son_contra_su_propia_mediana,
              test_escritura_y_ritmo, test_la_radiografia_completa,
              test_dos_veces_lo_mismo):
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
