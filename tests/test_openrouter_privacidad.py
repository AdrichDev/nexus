# -*- coding: utf-8 -*-
"""POLÍTICA DE DATOS CON OPENROUTER — que los prompts no acaben de material de
entrenamiento de un tercero.

EL INCIDENTE (01/08/2026). Al revisar la documentación de OpenRouter se vio que
su valor POR DEFECTO es «allow», que en sus palabras significa permitir
proveedores que guardan los datos y PUEDEN ENTRENAR CON ELLOS. Y nexus mandaba
solo {"model", "messages"}: ninguna preferencia.

Eso pesa más aquí que en otro proyecto cualquiera. En el prompt de nexus viaja lo
que recupera de la memoria, y ese mismo día la memoria pasó a contener el
documento maestro de marca, el manual de conversaciones y notas personales. Se
había blindado el vectorizado para que no saliera del equipo; mandarlo por el
chat a un proveedor que entrena con ello habría sido la misma fuga por la otra
puerta.

Lo que se comprueba aquí es lo que se puede romper sin darse cuenta:
  · que a OpenRouter se le manda la política,
  · que a OpenAI (y a cualquier otro) NO se le manda, porque «provider» es un
    campo suyo y a los demás les llega como campo desconocido y responden error,
  · y que si umbrales.json falta o está roto, la política NO se relaja sola.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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


def main() -> int:
    from backend.core import llm
    from backend.core.comun.config import settings

    original = settings.get("cloud_base_url")

    print("· a OpenRouter SÍ se le manda la política de datos")
    try:
        settings.set("cloud_base_url", "https://openrouter.ai/api/v1")
        prov = llm.CloudProvider()
        extra = prov._extra_payload()
        check("provider" in extra,
              "con OpenRouter se manda el bloque «provider»")
        prefs = extra.get("provider", {})
        check(prefs.get("data_collection") == "deny",
              f"y pide data_collection=deny (vi {prefs.get('data_collection')!r})")

        # El nombre del campo NO es cosa nuestra: es el de la API de OpenRouter.
        # Si alguien lo «arregla» a data-collection o dataCollection, OpenRouter
        # lo ignora en silencio y la fuga vuelve sin que falle nada.
        check("data-collection" not in prefs and "dataCollection" not in prefs,
              "con el nombre EXACTO de la API, no una variante que OpenRouter ignoraría")

        print("· y el endpoint se reconoce por la URL, no por el nombre del proveedor")
        settings.set("cloud_base_url", "https://OpenRouter.ai/API/v1")
        check(llm.CloudProvider()._es_openrouter(),
              "se reconoce aunque la URL venga en mayúsculas")

        print("· a un endpoint que NO es OpenRouter no se le manda nada")
        for otro in ("https://api.openai.com/v1",
                     "https://api.groq.com/openai/v1",
                     "https://api.deepseek.com/v1"):
            settings.set("cloud_base_url", otro)
            check(llm.CloudProvider()._extra_payload() == {},
                  f"a {otro} no se le cuela «provider», que le daría error")

        print("· OpenAI de verdad tampoco lo manda nunca")
        check(llm.OpenAIProvider()._extra_payload() == {},
              "el proveedor OpenAI no manda campos que OpenAI no conoce")

        print("· si umbrales.json falta o está roto, la política NO se relaja")
        # Una política de privacidad que se abre sola cuando algo falla no es una
        # política. Se apunta a una carpeta vacía para simular el archivo ausente.
        import backend.core.llm as _llm
        cfg_orig = _llm.CONFIG_DIR
        try:
            _llm.CONFIG_DIR = ROOT / "no-existe-esta-carpeta"
            vals = _llm._umbrales_openrouter()
            check(vals["data_collection"] == "deny",
                  "sin archivo de umbrales sigue en «deny», no en «allow»")
            check(vals["zdr"] is False,
                  "y zdr sigue en su valor de reserva")
        finally:
            _llm.CONFIG_DIR = cfg_orig

        print("· el archivo de umbrales real trae la sección y es coherente")
        datos = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
        orj = datos.get("openrouter") or {}
        check(bool(orj), "config/umbrales.json tiene la sección «openrouter»")
        check(orj.get("data_collection") in ("deny", "allow"),
              "con un data_collection que la API acepta")
        check(isinstance(orj.get("zdr"), bool), "y un zdr booleano")
        check("_lee_esto" in orj or "_que_es" in orj,
              "y explicado, como el resto del archivo")
    finally:
        settings.set("cloud_base_url", original)

    print()
    print("=" * 50)
    print(f"{_pass} OK, {len(_fail)} fallo(s)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
