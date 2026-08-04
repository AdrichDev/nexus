# -*- coding: utf-8 -*-
"""QUÉ SALE EN LOS VÍDEOS: la ficha visual y su cruce con las métricas.

El modelo describe la portada; el código cruza. Lo que se comprueba aquí es que
el código NO se cree lo que le den: que descarta valores inventados, que no
concluye con dos publicaciones, que la mediana aguanta un viral, y que el género
aparente sale marcado como lo que es — una estimación, no un dato.

Ejecutar:  python tests/test_visual.py    (desde la carpeta nexus)
"""
import importlib.util
import sys
from pathlib import Path
from _frontend_js import js_hud  # el HUD entero, no solo command.js

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
    "igvisual", ROOT / "skills" / "instagram" / "visual.py")
V = importlib.util.module_from_spec(sp)
sp.loader.exec_module(V)


def reel(i, vistas, **visual):
    return {"id": str(i), "view_count": vistas, "like_count": vistas // 20,
            "media_product_type": "REELS", "visual": visual}


# ══════════ 1. LO QUE DEVUELVE EL MODELO SE FILTRA ══════════
def test_no_se_cree_lo_que_le_den():
    print("· lo que conteste el modelo se filtra, no se traga")
    check(V.lee_ficha('{"personas":"una","producto":"protagonista"}')
          == {"personas": "una", "producto": "protagonista"},
          "lee un JSON limpio")
    envuelto = V.lee_ficha('Claro, aquí tienes:\n{"personas":"dos"}\nespero que sirva')
    check(envuelto == {"personas": "dos"},
          f"y lo saca aunque venga envuelto en verborrea ({envuelto})")
    inventado = V.lee_ficha('{"personas":"tropecientas","producto":"no"}')
    check("personas" not in inventado and inventado.get("producto") == "no",
          f"descarta valores que no estaban en la lista ({inventado})")
    check(V.lee_ficha('{"personas":"UNA"}') == {"personas": "una"},
          "y no se pierde por las mayúsculas")
    check(V.lee_ficha("no he podido ver la imagen") == {},
          "si no contesta un JSON, ficha vacía: no se rellena a ojo")
    check(V.lee_ficha("") == {} and V.lee_ficha("{roto,,,") == {},
          "y con basura tampoco revienta")
    # el prompt le cierra las opciones, que es lo que hace agrupable el resultado
    pr = V.prompt_ficha()
    check("SOLO con un JSON" in pr, "se le pide solo JSON")
    check("no se aprecia" in pr, "y se le da salida para cuando no lo vea claro")
    check(all(v in pr for v in V.ATRIBUTOS["personas"]["valores"]),
          "con las opciones cerradas escritas")


# ══════════ 2. NO SE CONCLUYE CON DOS PUBLICACIONES ══════════
def test_no_concluye_con_casos_sueltos():
    print("· con dos portadas no se dice qué funciona")
    pocos = [reel(1, 10000, personas="una"), reel(2, 30000, personas="ninguna")]
    c = V.cruza(pocos)
    b = [x for x in c["bloques"] if x["atributo"] == "personas"][0]
    check(b["mejor"] is None, f"no corona a nadie ({b['mejor']})")
    check(b["nota"], "y dice por qué")
    check(all(not f["concluyente"] for f in b["filas"]), "cada fila va marcada")

    muchos = ([reel(i, 20000, personas="una") for i in range(4)]
              + [reel(i + 10, 4000, personas="ninguna") for i in range(4)])
    c2 = V.cruza(muchos)
    b2 = [x for x in c2["bloques"] if x["atributo"] == "personas"][0]
    check(b2["mejor"] == "una", f"con muestra sí decide ({b2['mejor']})")
    check(not b2["nota"], "y ya no avisa")
    fila = next(f for f in b2["filas"] if f["valor"] == "una")
    check(fila["concluyente"] and fila["n"] == 4, "marcando cuál tiene muestra")


# ══════════ 3. CADA VALOR, CONTRA LA MEDIANA DE ESA CUENTA ══════════
def test_se_compara_contra_si_misma():
    print("· cada valor se compara con la mediana de esa misma cuenta")
    medios = ([reel(i, 5000, producto="no") for i in range(4)]
              + [reel(i + 10, 20000, producto="protagonista") for i in range(4)])
    c = V.cruza(medios)
    check(c["base"] == 12500.0, f"la base es la mediana de la cuenta ({c['base']})")
    b = [x for x in c["bloques"] if x["atributo"] == "producto"][0]
    prot = next(f for f in b["filas"] if f["valor"] == "protagonista")
    check(prot["vs_mediana"] == 1.6, f"y cada valor sale en múltiplos ({prot['vs_mediana']}×)")
    check(b["mejor"] == "protagonista", "con el producto delante le va mejor")
    # un viral no puede decidir por todos
    con_viral = medios + [reel(99, 900000, producto="no")]
    c2 = V.cruza(con_viral)
    b2 = [x for x in c2["bloques"] if x["atributo"] == "producto"][0]
    check(b2["mejor"] == "protagonista",
          f"un viral suelto no le da la vuelta a la conclusión ({b2['mejor']})")


# ══════════ 4. SIN CIFRAS, SE DESCRIBE PERO NO SE CONCLUYE ══════════
def test_sin_cifras_solo_describe():
    print("· sin reproducciones se puede decir qué usa, no qué le funciona")
    sin = [{"id": str(i), "visual": {"plano": "primer plano"}} for i in range(5)]
    c = V.cruza(sin)
    b = [x for x in c["bloques"] if x["atributo"] == "plano"][0]
    check(b["filas"][0]["n"] == 5, "cuenta cuántas veces lo usa")
    check(b["mejor"] is None, "pero no dice que funcione")
    check("no se puede decir qué funciona" in b["nota"], f"y lo explica ({b['nota'][:50]})")


# ══════════ 5. EL GÉNERO VA MARCADO COMO ESTIMACIÓN ══════════
def test_el_genero_va_marcado():
    print("· el género aparente se marca como estimación, no como dato")
    check(V.ATRIBUTOS["genero_aparente"]["fiable"] == "baja",
          "el atributo se declara de fiabilidad baja")
    check(V.ATRIBUTOS["personas"]["fiable"] == "alta",
          "y contar personas, que sí se ve, de fiabilidad alta")
    medios = [reel(i, 5000, genero_aparente="mujer") for i in range(4)]
    c = V.cruza(medios)
    b = [x for x in c["bloques"] if x["atributo"] == "genero_aparente"][0]
    check(b["fiabilidad"] == "baja", "y llega marcado al informe")
    check("ESTIMACIÓN" in c["aviso_genero"], "con su aviso en mayúsculas")
    md = V.cruza_md(c)
    check(c["aviso_genero"] in md, "que sale escrito en el informe, no escondido")


# ══════════ 6. EL INFORME ══════════
def test_el_informe():
    print("· el informe sale en Markdown y con los avisos dentro")
    medios = ([reel(i, 20000, personas="una", producto="protagonista",
                    texto_en_portada="mucho", escenario="exterior") for i in range(4)]
              + [reel(i + 10, 4000, personas="ninguna", producto="no",
                      texto_en_portada="no", escenario="estudio") for i in range(4)]
              + [{"id": "z", "view_count": 1}])          # una sin ficha
    c = V.cruza(medios)
    check(c["analizadas"] == 8 and c["sin_ficha"] == 1,
          f"cuenta las que ha podido mirar y las que no ({c['analizadas']}/{c['sin_ficha']})")
    md = V.cruza_md(c)
    for t in ("Qué sale en los vídeos", "Cuánta gente sale", "El producto en pantalla",
              "Texto incrustado", "Dónde está grabado"):
        check(t in md, f"el informe tiene «{t}»")
    check("|---|" in md, "con tablas de verdad")
    check("Reproducciones (mediana)" in md, "diciendo de qué es cada número")
    check("Frente a su media" in md, "y contra qué se compara")
    check("sin analizar" in md, "y dice cuántas se ha dejado")
    vacio = V.cruza([{"id": "1", "view_count": 10}])
    check(not vacio["hay"] and "No hay portadas" in V.cruza_md(vacio),
          "sin fichas, lo dice en vez de enseñar tablas vacías")


# ══════════ 7. MIRAR LAS PORTADAS DE VERDAD ══════════
def test_elige_bien_el_modelo_de_vision():
    print("· elige el modelo que ve imágenes, y respeta el que tú pongas")
    check(V.es_de_vision("llava:7b") and V.es_de_vision("llama3.2-vision:11b")
          and V.es_de_vision("moondream"), "reconoce las familias que ven")
    check(not V.es_de_vision("qwen3:8b") and not V.es_de_vision("deepseek-r1"),
          "y no confunde un modelo de texto con uno de visión")
    check(V.elige_modelo(["qwen3:8b", "llava:13b"]) == "llava:13b",
          "de una lista mixta coge el de visión")
    check(V.elige_modelo(["qwen3:8b"], "mi-modelo-nuevo") == "mi-modelo-nuevo",
          "y si TÚ eliges uno, manda el tuyo aunque yo no lo conozca")
    check(V.elige_modelo(["qwen3:8b", "deepseek-r1"]) == "",
          "sin ninguno que vea, no se elige uno a ciegas")


def test_sin_modelo_lo_dice_y_no_revienta():
    print("· sin modelo de visión se explica, no se rompe ni se inventa")
    import asyncio

    class Ajustes:
        def get(self, k, d=None):
            return {"ollama_url": "http://127.0.0.1:1", "vision_model": ""}.get(k, d)

    # Ollama apagado: la llamada falla y no hay modelos
    medios = [{"id": "1", "media_url": "https://x/1.jpg", "caption": "a"}]
    r = asyncio.run(V.mira_portadas(medios, Ajustes()))
    check(r["hay"] is False, "no dice que haya mirado nada")
    check(r["motivo"] == "sin_modelo", f"y da el motivo ({r['motivo']})")
    check("ollama pull llava" in r["texto"], "diciendo cómo arreglarlo")
    check("no salen de aquí" in r["texto"], "y que las imágenes se quedan en tu equipo")
    check("visual" not in medios[0], "y NO deja una ficha inventada en la publicación")

    # y si las publicaciones ni siquiera traen portada
    r2 = asyncio.run(V.mira_portadas([{"id": "1", "caption": "a"}], Ajustes()))
    check(r2["motivo"] == "sin_portadas", "distingue «no hay portada» de «no hay modelo»")
    check("media_url" in r2["texto"], "y dice qué campo falta")


def test_el_flujo_engancha_lo_visual():
    print("· el análisis de cuentas llama al paso visual")
    fuente = (ROOT / "skills" / "instagram" / "skill.py").read_text(encoding="utf-8")
    check("_visual_de" in fuente, "existe el paso visual en la skill")
    check(fuente.count("await _visual_de") == 2,
          f"y se llama en los DOS sitios que analizan cuentas "
          f"({fuente.count('await _visual_de')})")
    check("visual_estado" in fuente, "guardando el estado aunque no se pueda mirar")
    ig = (ROOT / "skills" / "instagram" / "scripts" / "ig.py").read_text(encoding="utf-8")
    check("media_url" in ig, "y la ingesta pide la portada")
    js = js_hud()
    check("igVisual" in js, "el HUD lo pinta")
    check("vision_model" in js, "y se puede elegir el modelo desde APIS")
    cfg = (ROOT / "backend" / "core" / "comun" / "config.py").read_text(encoding="utf-8")
    check('"vision_model"' in cfg, "con su ajuste en la configuración")


# ══════════ 8. Y QUE TODO ESTO SE INSTALE ══════════
def test_el_instalador_lo_comprueba():
    print("· el instalador comprueba que lo instalado arranca")
    bat = (ROOT / "INSTALAR_nexus.bat").read_text(encoding="utf-8", errors="replace")
    check("Comprobando la instalacion" in bat, "el instalador hace una comprobación")
    for pieza in ("analisis", "descubrimiento", "inteligencia", "visual"):
        check(pieza in bat, f"que carga «{pieza}.py»")
    check("umbrales.json" in bat, "y que los umbrales se leen")
    check("comprobacion de instalacion FALLIDA" in bat.lower()
          or "comprobacion ha fallado" in bat.lower(),
          "y si falla, lo dice en vez de arrancar como si nada")
    # las piezas nuevas existen de verdad donde el instalador las busca
    for f in ("analisis.py", "descubrimiento.py", "inteligencia.py", "visual.py"):
        ruta = ROOT / "skills" / "instagram" / f
        check(ruta.is_file() and ruta.stat().st_size > 1000,
              f"skills/instagram/{f} existe y no está vacío")
    check((ROOT / "config" / "umbrales.json").is_file(),
          "config/umbrales.json viaja con el proyecto")
    # y nada de esto añade dependencias nuevas que instalar
    fuente = (ROOT / "skills" / "instagram" / "visual.py").read_text(encoding="utf-8")
    for prohibida in ("import cv2", "import PIL", "from PIL", "import numpy",
                      "import torch", "import requests"):
        check(prohibida not in fuente,
              f"«{prohibida}» no hace falta: nada nuevo que instalar")


def main() -> int:
    for f in (test_no_se_cree_lo_que_le_den, test_no_concluye_con_casos_sueltos,
              test_se_compara_contra_si_misma, test_sin_cifras_solo_describe,
              test_el_genero_va_marcado, test_el_informe,
              test_elige_bien_el_modelo_de_vision,
              test_sin_modelo_lo_dice_y_no_revienta,
              test_el_flujo_engancha_lo_visual,
              test_el_instalador_lo_comprueba):
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
