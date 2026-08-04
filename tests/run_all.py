# -*- coding: utf-8 -*-
"""Runner de TODOS los tests de nexus + chequeo de que TODAS las skills cargan.
Ejecutar:  python tests/run_all.py   (desde la carpeta nexus)  ->  exit 0 si OK.
"""
import ast
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

# LA SUITE NO PUEDE TOCAR LA CONFIGURACIÓN DE VERDAD.
# `test_dispositivos.py` hacía `settings.set("llm_provider","ollama")` sobre el
# config/settings.json REAL y no lo devolvía. Resultado: cada pasada de los tests
# le cambiaba el cerebro a Adrián — elegía Gemini, corría la suite, y al arrancar
# nexus salía qwen3. Tardó en verse porque el síntoma aparecía mucho después y
# lejos de la causa. Se fotografía antes y se compara al final.
_CFG = os.path.join(ROOT, "config", "settings.json")
try:
    _cfg_antes = open(_CFG, encoding="utf-8").read()
except Exception:
    _cfg_antes = None

# 3) lanzar las suites unitarias
for suite in ("test_all.py", "test_routing.py", "test_verificaciones.py",
              "test_renovacion.py", "test_mejoras_v19.py", "test_specs_v20.py",
              "test_v21_fixes.py", "test_specs_v23.py", "test_specs_v23_orq.py", "test_specs_v23_mem.py", "test_specs_v23_files.py", "test_specs_v23_ui.py", "test_specs_v23_hermes.py", "test_specs_v24.py", "test_llm_runtime.py", "test_acceso_remoto.py", "test_tunel_adoptado.py", "test_instagram.py", "test_instagram_analisis.py", "test_instagram_spec.py", "test_instagram_competencia.py", "test_skill_instagram_conexion.py", "test_nucleo.py", "test_umbrales.py", "test_descubrimiento.py", "test_descubrimiento_flujo.py", "test_inteligencia.py", "test_frases_reales.py", "test_visual.py", "test_apis_config.py", "test_entrega_real.py", "test_dispositivos.py", "test_engram.py", "test_hermes_engram.py", "test_memoria_embeddings.py", "test_purga.py", "test_ingesta_documentos.py",
              "test_openrouter_privacidad.py", "test_content_os_honestidad.py", "test_drive.py",
              "test_skill_google_workspace.py", "test_skill_domotica.py",
              "test_skill_hermes.py", "test_skill_files.py",
              "test_skill_system_pc.py", "test_volumen_destino.py",
              "test_skill_tasks_board.py", "test_eventos_varios_dias.py",
              "test_eventos_google_rango.py",
              "test_calendario_por_fecha.py",
              "test_skill_autoprovision.py", "test_skill_media.py",
              "test_skill_chrome.py", "test_skill_content_os.py",
              "test_skill_datos.py", "test_skill_vigilancias.py",
              "test_skill_memory_graph.py", "test_skill_coach.py",
              "test_skill_tools.py", "test_skill_research.py",
              "test_skill_backup.py", "test_skill_telefono.py",
              "test_skills_pequenas_1.py", "test_skills_pequenas_2.py",
              "test_frontend_modulos.py", "test_capas_backend.py",
              "test_lo_prometido.py", "test_grafo_solo_conocimiento.py",
              "test_saludo_una_vez.py", "test_calla_al_escribir.py", "test_no_promete_trabajo.py", "test_apunta_no_es_siempre_memoria.py",
              "test_grafo_vista.py"):
    print(f"== 3) suite {suite} ==")
    # UTF-8 forzado: en la consola de Windows (cp1252) un «✔» en un mensaje
    # reventaba la suite entera con UnicodeEncodeError.
    _env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", suite)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env)
    # SEGUNDA OPORTUNIDAD para las suites que ARRANCAN UN SERVIDOR. Con toda la
    # batería corriendo, uvicorn puede tardar más de la cuenta en levantar y la
    # suite fallaba por impaciencia: un rojo que no era un fallo real y que
    # obligaba a repetir a mano para saber si era verdad. Si falla, se repite una
    # vez; si vuelve a fallar, ES un fallo y cuenta como tal.
    if r.returncode != 0 and suite in ("test_entrega_real.py", "test_acceso_remoto.py"):
        print("  (arranca un servidor y ha fallado; repito una vez por si fue lentitud)")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", suite)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=_env)
    print("\n".join("  " + l for l in r.stdout.strip().splitlines()[-4:]))
    if r.returncode != 0:
        fails += 1
        print(r.stderr[-500:])

print("== 4) la suite no ha tocado config/settings.json ==")
if _cfg_antes is None:
    print("  (no había settings.json que vigilar)")
else:
    try:
        _cfg_ahora = open(_CFG, encoding="utf-8").read()
    except Exception:
        _cfg_ahora = ""
    if _cfg_ahora == _cfg_antes:
        print("  intacto ✔")
    else:
        import json as _json
        try:
            a, b = _json.loads(_cfg_antes), _json.loads(_cfg_ahora)
            cambios = sorted({k for k in set(a) | set(b) if a.get(k) != b.get(k)})
        except Exception:
            cambios = ["(no he podido comparar clave a clave)"]
        print("  ✖ LA SUITE HA CAMBIADO LOS AJUSTES DE VERDAD:", ", ".join(cambios))
        print("    Un test está escribiendo en config/settings.json en vez de en su")
        print("    sandbox. Aísla NEXUS_CONFIG_DIR o parchea settings.get, pero no")
        print("    dejes escrito nada: esto le cambia la configuración al usuario.")
        try:                                     # se devuelve lo que había
            open(_CFG, "w", encoding="utf-8").write(_cfg_antes)
            print("    (he restaurado el fichero a como estaba)")
        except Exception:
            pass
        fails += 1

print(f"\n{'#'*54}\nRESULTADO GLOBAL: {'TODO VERDE ✔' if fails == 0 else str(fails)+' bloque(s) con fallos ✖'}")
sys.exit(1 if fails else 0)
