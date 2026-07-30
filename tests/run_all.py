# -*- coding: utf-8 -*-
"""Runner de TODOS los tests de nexus + chequeo de que TODAS las skills cargan.
Ejecutar:  python tests/run_all.py   (desde la carpeta nexus)  ->  exit 0 si OK.
"""
import ast
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 1) py_compile de TODO el backend + skills (bug de sintaxis = fallo)
print("== 1) sintaxis (py_compile) de backend + skills ==")
pyfiles = []
for base in ("backend", "skills"):
    for dp, _, fns in os.walk(os.path.join(ROOT, base)):
        if "__pycache__" in dp or ".bak" in dp:
            continue
        for fn in fns:
            if fn.endswith(".py") and ".bak" not in fn:
                pyfiles.append(os.path.join(dp, fn))
bad = 0
for f in pyfiles:
    try:
        ast.parse(open(f, encoding="utf-8").read())
    except SyntaxError as e:
        print("  SYNTAX ERROR:", os.path.relpath(f, ROOT), e)
        bad += 1
print(f"  {len(pyfiles)} ficheros, {bad} con error de sintaxis")
fails += bad

# 2) que cada skill exponga SKILL{name,description,patterns} y handle()
print("== 2) contrato de cada skill (SKILL + handle) ==")
skdir = os.path.join(ROOT, "skills")
nsk = 0
for folder in sorted(os.listdir(skdir)):
    sp = os.path.join(skdir, folder, "skill.py")
    if not os.path.isfile(sp):
        continue
    nsk += 1
    tree = ast.parse(open(sp, encoding="utf-8").read())
    has_skill = any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "SKILL"
                    for t in n.targets) for n in tree.body)
    has_handle = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "handle"
                     for n in tree.body)
    if not has_skill or not has_handle:
        print(f"  {folder}: SKILL={has_skill} handle={has_handle}  <- INCOMPLETA")
        fails += 1
print(f"  {nsk} skills revisadas")

# 3) lanzar las suites unitarias
for suite in ("test_all.py", "test_routing.py", "test_verificaciones.py",
              "test_renovacion.py", "test_mejoras_v19.py", "test_specs_v20.py",
              "test_v21_fixes.py", "test_specs_v23.py", "test_specs_v23_orq.py", "test_specs_v23_mem.py", "test_specs_v23_files.py", "test_specs_v23_ui.py", "test_specs_v23_hermes.py", "test_specs_v24.py", "test_llm_runtime.py", "test_entrega_real.py", "test_dispositivos.py", "test_engram.py", "test_hermes_engram.py"):
    print(f"== 3) suite {suite} ==")
    # UTF-8 forzado: en la consola de Windows (cp1252) un «✔» en un mensaje
    # reventaba la suite entera con UnicodeEncodeError.
    _env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", suite)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env)
    print("\n".join("  " + l for l in r.stdout.strip().splitlines()[-4:]))
    if r.returncode != 0:
        fails += 1
        print(r.stderr[-500:])

print(f"\n{'#'*54}\nRESULTADO GLOBAL: {'TODO VERDE ✔' if fails == 0 else str(fails)+' bloque(s) con fallos ✖'}")
sys.exit(1 if fails else 0)
