# -*- coding: utf-8 -*-
"""¿Cuántos correos aguanta de una tirada el modelo que tienes puesto AHORA?

NO forma parte de `run_all.py` a propósito: hace llamadas de verdad al LLM, tarda
y —si estás en un proveedor de nube— cuesta dinero. Es una herramienta para
ejecutar a mano el día que cambies de modelo.

QUÉ MIDE. Monta 30 correos falsos con un «[ALERTA]» enterrado en medio y prueba
varios tamaños de lote. De cada uno mira dos cosas distintas:

  · COBERTURA — ¿ha clasificado los 30, o se ha dejado unos cuantos?
  · ACIERTO   — ¿ha marcado la alerta como urgente por su cuenta?

El acierto se mide **con la red desactivada**. La red de `marcas_urgentes` salva
la alerta pase lo que pase, así que si la dejáramos puesta este banco daría
siempre verde y no mediría nada del modelo.

Historia: el 31/07/2026 los 30 iban en UNA llamada de 22.000 caracteres. Ollama
corta el prompt a 4096 tokens, qwen3:8b contestaba en prosa en vez de JSON, y
nexus respondía «ninguno parece urgente» teniendo una alerta de seguridad dentro.

Ejecutar:  .venv\\Scripts\\python.exe tests\\bench_lotes_correo.py
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_bench_"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TAMANOS = (6, 10, 15, 30)
N_CORREOS = 30
POS_ALERTA = 12

_RELLENO = ("Hola, te escribimos para contarte las novedades de este mes. "
            "Hemos publicado nuevas plantillas, mejorado el rendimiento del panel y "
            "ajustado los precios de los planes. Puedes ver todos los detalles en "
            "nuestro blog. Si no quieres recibir mas correos como este, puedes darte "
            "de baja al final del mensaje. Un saludo del equipo. ") * 3


def _correos() -> list[dict]:
    """La bandeja de mentira: ruido de boletines con UNA alerta real dentro."""
    msgs = []
    for i in range(N_CORREOS):
        if i == POS_ALERTA:
            msgs.append({
                "from": "Alertas Seguridad",
                "subject": "[ALERTA] Plugin nuevo no presente en el baseline en Menopausia Activa",
                "body": "Se detectaron plugins NUEVOS (no estaban en el baseline). NO se "
                        "han tocado; revisa si los instalaste tu o son una intrusion. " + _RELLENO,
            })
        else:
            msgs.append({"from": f"Boletin {i}", "subject": f"Novedades de la semana {i}",
                         "body": _RELLENO[:700]})
    return msgs


async def main() -> int:
    from backend.core.config import settings
    from skills.google_workspace import skill as GW

    prov = settings.get("llm_provider", "ollama")
    modelo = settings.get(f"{prov}_model", "?")
    msgs = _correos()
    chars = sum(len(m["body"][:700]) + len(m["subject"]) + len(m["from"]) for m in msgs)

    print(f"\nproveedor : {prov}   modelo: {modelo}")
    print(f"bandeja   : {N_CORREOS} correos, ~{chars} caracteres en total")
    print(f"la alerta : posicion {POS_ALERTA}\n")
    print(f"{'lote':>5} {'llamadas':>9} {'clasificados':>13} {'alerta':>8} {'tiempo':>8}")
    print("-" * 50)

    # Fuera la red: aquí se mide el MODELO, no el colchón que hay debajo.
    orig_marca, orig_lote = GW._marca_urgente, GW._por_lote
    GW._marca_urgente = lambda _m: ""
    mejor = None
    try:
        for tam in TAMANOS:
            GW._por_lote = lambda t=tam: t
            t0 = time.time()
            try:
                an, sin = await GW._analyze_emails(msgs)
            except Exception as exc:                              # noqa: BLE001
                print(f"{tam:>5} {'—':>9} {'ERROR':>13} {'—':>8}   "
                      f"{type(exc).__name__}: {exc}")
                continue
            seg = time.time() - t0
            llamadas = -(-len(msgs) // tam)                       # techo de la division
            ok_alerta = any(a["i"] == POS_ALERTA and a.get("urgente") for a in an)
            completo = not sin
            print(f"{tam:>5} {llamadas:>9} {len(an):>10}/{N_CORREOS} "
                  f"{('SI' if ok_alerta else 'NO'):>8} {seg:>7.0f}s")
            if completo and ok_alerta and mejor is None:
                mejor = tam                                       # el mayor que aun acierta
    finally:
        GW._marca_urgente, GW._por_lote = orig_marca, orig_lote

    print("-" * 50)
    if mejor is None:
        print("\nNINGUN tamaño ha clasificado los 30 Y pillado la alerta por si solo.")
        print("Deja 'por_lote_por_proveedor' en un numero bajo (6) para este proveedor,")
        print("y sobre todo NO toques 'marcas_urgentes': ahora mismo es lo unico que")
        print("evita que una alerta de seguridad pase por 'nada urgente'.")
        return 1

    # Se recorren de menor a mayor, así que el primero que cuadra es el más fino.
    # Interesa el MAYOR que aún acierte: menos llamadas, menos tiempo y menos gasto.
    buenos = [t for t in TAMANOS if t >= mejor]
    print(f"\nEl mas fino que va bien es {mejor}. Prueba a subir dentro de {buenos}")
    print(f"y quedate con el mayor que siga marcando 'SI' en la columna alerta.")
    print(f"\nSe pone en config/umbrales.json -> correos.por_lote_por_proveedor.{prov}")
    print("No hace falta reiniciar: se lee en cada analisis.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
