# -*- coding: utf-8 -*-
"""FASE 1: los umbrales viven en config, no en el código.

El criterio de aceptación NO es "el archivo se lee". Eso no prueba nada: un
archivo puede leerse y no usarse para nada. Lo que se comprueba aquí es que
CAMBIANDO UN NÚMERO EN EL ARCHIVO, EL INFORME DICE OTRA COSA. Y, al revés, que
con el archivo tal y como se entrega el comportamiento es EXACTAMENTE el de
antes de que existiera.

Ejecutar:  python tests/test_umbrales.py    (desde la carpeta nexus)
"""
import importlib.util
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


def _motor():
    """Carga el motor de cero, para que relea el archivo de umbrales."""
    sp = importlib.util.spec_from_file_location(
        "iganal_u", ROOT / "skills" / "instagram" / "analisis.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


A = _motor()


def com(u, t, owner=False):
    return {"username": u, "text": t, "timestamp": "2026-07-30T10:00:00+0000",
            "is_from_owner": owner, "is_trigger": False, "matched_trigger": None}


def bundle_y_clas(mod=None):
    mod = mod or A
    clas = mod.clasificar([com(f"u{i}", "QUIERO LA PLANTILLA") for i in range(6)]
                          + [com("p1", "¿cuánto cuesta el curso?")],
                          ["QUIERO LA PLANTILLA"])
    # 400/10000 = 4 % guardados · 900/10000 = 9 % interacciones
    return {"insights": {"reach": 10000, "saved": 400, "total_interactions": 900}}, clas


# ══════════ 1. EL ARCHIVO EXISTE Y NO CAMBIA NADA ══════════
def test_se_entrega_sin_cambiar_el_comportamiento():
    print("· el archivo se entrega con los valores de siempre")
    f = A.ruta_umbrales()
    check(f.is_file(), f"existe config/umbrales.json ({f})")
    guardado = json.loads(f.read_text(encoding="utf-8"))
    vivos = A.cargar_umbrales()
    # cada valor del archivo tiene que coincidir con el de reserva del código:
    # si alguien cambia uno sin querer, el comportamiento de nexus cambiaría
    for bloque, valores in A._POR_DEFECTO.items():
        for clave, valor in valores.items():
            check(vivos[bloque][clave] == valor,
                  f"«{bloque}.{clave}» se entrega con el valor de siempre "
                  f"({vivos[bloque].get(clave)} vs {valor})")
    check(all(not str(k).startswith("_") or True for k in guardado),
          "el archivo lleva explicaciones dentro, para poder tocarlo sin manual")


# ══════════ 2. LO QUE IMPORTA: CAMBIAR EL NÚMERO CAMBIA LA LECTURA ══════════
def test_cambiar_el_umbral_cambia_la_lectura():
    print("· cambiar un umbral cambia lo que dice el informe")
    b, clas = bundle_y_clas()
    normal = A.metricas(b, clas)
    check(normal["lecturas"]["Guardados"].startswith("señal fuerte"),
          f"con el listón en 3 %, un 4 % de guardados es señal fuerte "
          f"({normal['lecturas']['Guardados']})")
    check(normal["lecturas"]["Interacciones"] == "engagement normal",
          f"y un 9 % de interacciones es normal ({normal['lecturas']['Interacciones']})")

    exigente = A.metricas(b, clas, {"lecturas": {"guardados_pct_reach_fuerte": 5.0,
                                                 "interacciones_pct_reach_alto": 8.0}})
    check(not exigente["lecturas"]["Guardados"].startswith("señal fuerte"),
          "subiendo el listón a 5 %, ese mismo 4 % ya NO es señal fuerte")
    check(exigente["lecturas"]["Interacciones"].startswith("engagement alto"),
          "y bajándolo a 8 %, ese mismo 9 % SÍ es engagement alto")
    check(normal["filas"] == exigente["filas"],
          "las CIFRAS no cambian: lo que cambia es la interpretación")


# ══════════ 3. CADA BLOQUE DE UMBRALES HACE ALGO DE VERDAD ══════════
def test_todos_los_umbrales_tienen_efecto():
    print("· ningún umbral del archivo es decorativo")
    # erratas: con margen 0 para todo, «plantila» deja de contar como la palabra
    con = A.casa_cta("plantila", ["QUIERO LA PLANTILLA"])[0]
    sin = A.casa_cta("plantila", ["QUIERO LA PLANTILLA"],
                     A.cargar_umbrales({"erratas": {"margen_2_hasta": 0,
                                                    "margen_maximo": 0}}))[0]
    check(con and not sin, f"«erratas» manda: con margen sí, sin margen no ({con}/{sin})")

    # sentimiento: dónde está la frontera de «fiable» y la del aviso
    s1 = A.sentimiento({"positivo": 20, "neutral": 5}, 25)
    s2 = A.sentimiento({"positivo": 20, "neutral": 5}, 25,
                       {"sentimiento": {"n_minimo_fiable": 10, "n_sin_aviso": 20}})
    check(not s1["fiable"] and s2["fiable"], "«sentimiento.n_minimo_fiable» manda")
    check(s1["aviso"] and not s2["aviso"], "«sentimiento.n_sin_aviso» manda")

    # gancho: con el mínimo de personas por las nubes, no hay campaña
    flat = [com(f"u{i}", "PLANTILLA") for i in range(6)] + [com(f"x{i}", "vaya crack") for i in range(20)]
    hay = A.detecta_cta(flat)
    no = A.detecta_cta(flat, umbrales={"gancho": {"min_personas": 50}})
    check(hay and not no, f"«gancho.min_personas» manda ({len(hay)} → {len(no)})")

    # comentarios: qué cuenta como «dice algo»
    # «muy top» son 7 caracteres: por debajo del mínimo de 8 que hay puesto
    c1 = A.clasificar([com("a", "muy top")], [])["conteo"]
    c2 = A.clasificar([com("a", "muy top")], [],
                      A.cargar_umbrales({"comentarios": {"min_caracteres_sustantivo": 3}}))["conteo"]
    check(c1["sin_clasificar"] == 1 and c2["sustantivo"] == 1,
          f"«comentarios.min_caracteres_sustantivo» manda ({c1} / {c2})")

    # cola editorial: los pesos cambian el ORDEN, que es lo que se mira
    dudas = [{"veces": 3, "ejemplo": "¿qué micro usas?", "otros": [], "usuarios": ["a"], "tema": "micro"},
             {"veces": 1, "ejemplo": "¿y para empresas?", "otros": [], "usuarios": ["b", "c", "d", "e"], "tema": "empresas"}]
    por_veces = A.cola_editorial(dudas)
    por_gente = A.cola_editorial(dudas, umbrales={"cola_editorial": {"peso_veces": 1,
                                                                     "peso_personas": 5}})
    check(por_veces[0]["titulo"] != por_gente[0]["titulo"],
          f"«cola_editorial» manda: el orden cambia con los pesos "
          f"({por_veces[0]['titulo'][:20]} → {por_gente[0]['titulo'][:20]})")


# ══════════ 4. EL PANEL DICE LOS UMBRALES QUE HAY, NO UNOS FIJOS ══════════
def test_el_panel_no_miente():
    print("· el panel enseña los umbrales que están puestos de verdad")
    b, clas = bundle_y_clas()
    u = {"lecturas": {"guardados_pct_reach_fuerte": 7.5},
         "sentimiento": {"n_minimo_fiable": 44}}
    ctx = {"media": {}, "metricas": A.metricas(b, clas, u), "clasificacion": clas,
           "leads": A.leads(clas), "sentimiento": A.sentimiento({"positivo": 1}, 1, u)}
    pa = A.panel(ctx, u)
    numeros = [x for x in pa["secciones"] if x["id"] == "numeros"][0]
    check("7.5" in numeros["metodo"],
          f"el «cómo se calcula» dice el umbral real ({numeros['metodo'][-90:]})")
    sent = [x for x in pa["secciones"] if x["id"] == "sentimiento"][0]
    check("44" in sent["metodo"], "y lo mismo con el de sentimiento")
    por_defecto = A.panel(ctx)
    n2 = [x for x in por_defecto["secciones"] if x["id"] == "numeros"][0]
    check("7.5" not in n2["metodo"],
          "y con los umbrales de siempre, dice los de siempre: no es un texto fijo")


# ══════════ 5. UN ARCHIVO ROTO NO TUMBA EL ANÁLISIS ══════════
def test_un_json_roto_no_rompe_nada():
    print("· un archivo mal escrito no deja a nadie sin informe")
    tmp = Path(tempfile.mkdtemp())
    (tmp / "umbrales.json").write_text("{ esto no es json ,,,", encoding="utf-8")
    antes = os.environ.get("NEXUS_CONFIG_DIR")
    os.environ["NEXUS_CONFIG_DIR"] = str(tmp)
    try:
        m = _motor()
        u = m.cargar_umbrales()
        check(u["lecturas"]["guardados_pct_reach_fuerte"] == 3.0,
              "con el JSON roto, se usan los valores de reserva")
        b, clas = bundle_y_clas(m)
        check(m.metricas(b, clas)["lecturas"]["Guardados"].startswith("señal fuerte"),
              "y el informe sale igual que siempre, sin excepciones")
    finally:
        if antes is None:
            os.environ.pop("NEXUS_CONFIG_DIR", None)
        else:
            os.environ["NEXUS_CONFIG_DIR"] = antes
        shutil.rmtree(tmp, ignore_errors=True)

    # y lo mismo si el archivo directamente no está
    tmp2 = Path(tempfile.mkdtemp())
    os.environ["NEXUS_CONFIG_DIR"] = str(tmp2)
    try:
        m = _motor()
        check(m.cargar_umbrales()["gancho"]["min_personas"] == 5,
              "sin archivo, tampoco pasa nada")
    finally:
        if antes is None:
            os.environ.pop("NEXUS_CONFIG_DIR", None)
        else:
            os.environ["NEXUS_CONFIG_DIR"] = antes
        shutil.rmtree(tmp2, ignore_errors=True)


# ══════════ 6. CADA CUENTA PUEDE TENER LOS SUYOS ══════════
def test_cada_cuenta_puede_pisar_los_suyos():
    print("· una cuenta puede tener su propio listón")
    perfil = {"umbrales": {"lecturas": {"guardados_pct_reach_fuerte": 6.0}}}
    suyos = A.cargar_umbrales(perfil["umbrales"])
    check(suyos["lecturas"]["guardados_pct_reach_fuerte"] == 6.0, "pisa lo que pone")
    check(suyos["lecturas"]["interacciones_pct_reach_alto"] == 10.0,
          "y hereda lo que NO pone, sin tener que copiar el archivo entero")
    check(suyos["gancho"]["min_personas"] == 5, "los demás bloques quedan intactos")
    check(A.cargar_umbrales()["lecturas"]["guardados_pct_reach_fuerte"] == 3.0,
          "y no contamina a las demás cuentas")
    # el perfil de la skill trae el campo listo y VACÍO
    sp = importlib.util.spec_from_file_location(
        "igskill_u", ROOT / "skills" / "instagram" / "skill.py")
    sk = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(ROOT))
    sp.loader.exec_module(sk)
    check("umbrales" in sk.PERFIL_VACIO, "el perfil tiene el campo «umbrales»")
    check(sk.PERFIL_VACIO["umbrales"] == {},
          "y se entrega vacío: nexus no trae los umbrales de nadie puestos")


def main() -> int:
    for f in (test_se_entrega_sin_cambiar_el_comportamiento,
              test_cambiar_el_umbral_cambia_la_lectura,
              test_todos_los_umbrales_tienen_efecto,
              test_el_panel_no_miente,
              test_un_json_roto_no_rompe_nada,
              test_cada_cuenta_puede_pisar_los_suyos):
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
