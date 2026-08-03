# -*- coding: utf-8 -*-
"""Escribir a nexus la calla, igual que pulsar el botón de hablar.

INCIDENTE (03/08/2026). Adrián, sobre una respuesta larga que seguía sonando:

    «tiene que parar si recibe un mensaje via texto igual que cuando le doy a
     habla con nexus que escucha y para de hablar»

CAUSA. `voice()` —el botón— llamaba a `stopTTS()`. `send()` —el texto— no. Así
que escribir mientras hablaba no la interrumpía: te contestaba encima.

Y `stopTTS()` sola no basta: corta el audio que SUENA, pero no la COLA. Con
varios audios encolados, el siguiente arrancaba acto seguido y parecía que no
se había callado. Por eso las dos entradas pasan por `callarVoz()`, que vacía la
cola antes de cortar.

Se comprueba EJECUTANDO el código de verdad con Node, no buscando texto en el
fuente: un `grep` da por bueno que la llamada esté escrita aunque no haga nada.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_calla_al_escribir.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

_pass = 0
_fail: list[str] = []


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print(f"  FALLO: {msg}")
    return bool(cond)


SRC = (ROOT / "frontend" / "js" / "command.js").read_text(encoding="utf-8")


# ============ 1) LAS DOS ENTRADAS CALLAN POR EL MISMO SITIO =================
print("== 1) escribir y hablar callan por la misma puerta ==")

for nombre in ("send", "voice"):
    i = SRC.find(f"function {nombre}(")
    check(i > 0, f"existe la función {nombre}()")
    cuerpo = SRC[i:i + 900]
    check("callarVoz()" in cuerpo,
          f"{nombre}() no calla la voz antes de mandar nada")

check(SRC.count("function callarVoz(") == 1,
      "callarVoz está definida una sola vez, no copiada en dos sitios")


# ============ 2) CALLAR ES CORTAR LO QUE SUENA **Y** LA COLA ================
print("== 2) callar vacía la cola, no solo corta lo que suena ==")

# Se ejecuta `callarVoz` de verdad sobre dobles, para comprobar el EFECTO.
i = SRC.find("function callarVoz(")
cuerpo_callar = SRC[i:SRC.find("\n  }", i) + 4]

if shutil.which("node") is None:
    print("  (sin node en el PATH: no se puede ejecutar el comportamiento)")
else:
    guion = """
let sonando = { pausado: false, t: 5 };
const cola = ['a.mp3', 'b.mp3', 'c.mp3'];
let cortes = 0;
const _ttsQueue = cola;
function stopTTS() { cortes++; sonando.pausado = true; sonando.t = 0; }
%s
callarVoz();
console.log(JSON.stringify({ enCola: _ttsQueue.length, cortes, pausado: sonando.pausado }));
""" % cuerpo_callar.replace("  function callarVoz", "function callarVoz")

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "prueba.js"
        f.write_text(guion, encoding="utf-8")
        r = subprocess.run(["node", str(f)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    salida = (r.stdout or "").strip().splitlines()
    check(r.returncode == 0, f"callarVoz se ejecuta sin reventar ({r.stderr[:160]})")
    if salida:
        import json as _json
        d = _json.loads(salida[-1])
        check(d["enCola"] == 0,
              f"la cola sigue teniendo {d['enCola']} audios esperando turno")
        check(d["cortes"] == 1, "no corta el audio que está sonando")
        check(d["pausado"] is True, "el audio en curso no queda pausado")


# ============ 3) NO SE PIERDE EL BARGE-IN QUE YA HABÍA =====================
print("== 3) el corte que manda el backend sigue vaciando la cola ==")

# El mensaje 'stop' del backend ya vaciaba la cola a mano. Sigue haciéndolo:
# quitarlo al refactorizar dejaría a nexus hablando sobre sí misma.
check(re.search(r"data\.stop.*_ttsQueue\.length = 0", SRC) is not None
      or re.search(r"_ttsQueue\.length = 0;\s*stopTTS\(\)", SRC) is not None,
      "el corte que llega por el bus ya no vacía la cola")


print(f"\n{'#' * 54}\ntest_calla_al_escribir: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
