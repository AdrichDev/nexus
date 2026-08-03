# -*- coding: utf-8 -*-
"""nexus saluda al abrir, pero no cada vez que alguien abre algo.

INCIDENTE (03/08/2026). Adrián vio tres saludos seguidos sin haber dicho nada:

    nexus  Buenos días, Adri. Es lunes 3 de agosto y nexus ya está preparada…
    nexus  Buenos días, Adri. nexus conectada y lista para otro lunes…
    nexus  Buenos días, Adri. nexus, con los circuitos a punto para este lunes…

CAUSA. `afterBoot()` llama a `/api/greet` un segundo después de cargar el HUD, y
ese endpoint NO le contesta solo a quien pregunta: emite el saludo al bus —lo
ven TODAS las ventanas conectadas— y además lo dice EN VOZ ALTA. Así que cada
pestaña nueva, cada cierre y reapertura de la ventana, el móvil, o una prueba
automática con navegador, saludaba otra vez y a todo el mundo. Aquella mañana
fueron mis capturas de pantalla las que le saludaron.

LA REGLA. Un saludo, y descanso. El umbral vive en `config/umbrales.json`
(`saludo.minutos_entre_saludos`), no a fuego en el código.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_saludo_una_vez.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


APP = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")

print("== 1) el saludo tiene descanso, y el umbral no está a fuego ==")

check("_ULTIMO_SALUDO" in APP, "no se recuerda cuándo fue el último saludo")
check("minutos_entre_saludos" in APP,
      "el descanso no se lee de config/umbrales.json")
check('"repetido": True' in APP,
      "dentro del descanso debería contestar sin emitir ni hablar")

# El sello se pone SOLO cuando de verdad ha saludado. Si se pusiera al entrar,
# un fallo del modelo dejaría el descanso corriendo sin haber saludado nadie.
i_emit = APP.find('"provider": "saludo"')
i_sello = APP.find("_ULTIMO_SALUDO[0] = ")
check(i_emit != -1 and i_sello != -1 and i_sello > i_emit,
      "el sello de tiempo se pone antes de emitir: si el saludo falla, se traga "
      "el turno igualmente")

print("== 2) el umbral está en config/umbrales.json y explicado ==")

U = json.loads((ROOT / "config" / "umbrales.json").read_text(encoding="utf-8"))
check("saludo" in U, "falta la sección «saludo» en config/umbrales.json")
sal = U.get("saludo", {})
check(isinstance(sal.get("minutos_entre_saludos"), (int, float)),
      "«minutos_entre_saludos» no es un número")
check(sal.get("minutos_entre_saludos", 0) > 0,
      "un descanso de 0 minutos deja el problema igual que estaba")
check(len(str(sal.get("_que_es", ""))) > 40,
      "el umbral no explica qué hace: el resto del fichero sí lo hace")

print("== 3) el saludo sigue saliendo a las pantallas y por voz ==")

# El descanso no puede haberse llevado por delante el saludo en sí.
check('bus.emit("chat"' in APP and '"provider": "saludo"' in APP,
      "el saludo ya no se publica en el chat")
check(re.search(r"tts\.speak\(text\)", APP) is not None,
      "el saludo ya no se dice en voz alta")

print("== 4) lo llama el HUD una sola vez, al arrancar ==")

SPA = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")
check(SPA.count("/api/greet") == 1,
      f"el HUD llama a /api/greet {SPA.count('/api/greet')} veces; con una basta")
check("function afterBoot" in SPA and "/api/greet" in SPA,
      "el saludo debería colgar del arranque, no de un evento que se repite")

print(f"\n{'#' * 54}\ntest_saludo_una_vez: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
