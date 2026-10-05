# -*- coding: utf-8 -*-
"""Runner amplio de suites registradas + chequeo de contrato de skills.
Ejecutar:  python tests/run_all.py   (desde la carpeta nexus)  ->  exit 0 si las suites registradas OK.

Un verde aquí no prueba el producto completo: cada suite tiene perfil, efectos y
nivel de evidencia en tests/runner_profiles.py.
"""
import ast
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from runner_profiles import RUNNER_PROFILES, profile_counts

fails = 0

# The battery never touches the operator's real data directory: the runner and
# every suite get a throwaway NEXUS_DATA_DIR (logs, caches, jobs, inbox...).
# Without it, suites wrote fake jobs and documents into data/nexus.log.
_DATA_SANDBOX = tempfile.mkdtemp(prefix="nexus_suite_data_")
os.environ["NEXUS_DATA_DIR"] = _DATA_SANDBOX

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

print("== perfiles de evidencia registrados (no equivalen a prueba global) ==")
print("  " + ", ".join(f"{k}={v}" for k, v in profile_counts().items()))
print(f"  {len(RUNNER_PROFILES)} suites etiquetadas con efectos/requisitos explícitos")

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
for suite in ("unit/routing/test_all.py", "unit/routing/test_routing.py", "unit/routing/test_verificaciones.py",
              "unit/specs/test_renovacion.py", "unit/specs/test_mejoras_v19.py", "unit/specs/test_specs_v20.py",
              "unit/specs/test_v21_fixes.py", "unit/specs/test_specs_v23.py", "unit/specs/test_specs_v23_orq.py", "unit/specs/test_specs_v23_mem.py", "unit/specs/test_specs_v23_files.py", "unit/specs/test_specs_v23_ui.py", "unit/specs/test_specs_v23_hermes.py", "unit/specs/test_specs_v24.py", "unit/core/runtime/test_llm_runtime.py", "integration/http/test_acceso_remoto.py", "unit/core/runtime/test_tunel_adoptado.py", "unit/skills/instagram/test_instagram.py", "unit/skills/instagram/test_analisis.py", "unit/skills/instagram/test_spec.py", "unit/skills/instagram/test_competencia.py", "unit/skills/instagram/test_skill_instagram_conexion.py", "unit/core/runtime/test_nucleo.py", "unit/core/runtime/test_umbrales.py", "unit/skills/instagram/test_descubrimiento.py", "unit/skills/instagram/test_descubrimiento_flujo.py", "unit/skills/instagram/test_inteligencia.py", "unit/conversation/test_frases_reales.py", "unit/skills/instagram/test_visual.py", "unit/core/runtime/test_apis_config.py", "integration/http/test_entrega_real.py", "unit/skills/domotica/test_dispositivos.py", "unit/skills/domotica/test_tv_power.py", "unit/core/test_board_pattern.py", "unit/core/test_board_kpis.py", "unit/core/test_board_keys.py", "unit/frontend/test_task_cards.py", "unit/core/test_inbox_tasks.py", "unit/skills/google_workspace/test_inbox_fake_gmail.py", "unit/skills/google_workspace/test_inbox_scale.py", "unit/memory/test_engram.py", "unit/memory/test_hermes_engram.py", "unit/memory/test_memoria_embeddings.py", "unit/memory/test_purga.py", "unit/memory/test_ingesta_documentos.py",
              "unit/core/runtime/test_openrouter_privacidad.py", "unit/skills/content_os/test_content_os_honestidad.py", "unit/skills/google_workspace/test_drive.py",
              "unit/skills/google_workspace/test_skill_google_workspace.py", "unit/skills/domotica/test_skill_domotica.py",
              "unit/skills/hermes/test_empty_response.py", "unit/skills/hermes/test_skill_hermes.py", "unit/skills/files/test_skill_files.py",
              "unit/skills/system_pc/test_skill_system_pc.py", "unit/skills/system_pc/test_volumen_destino.py",
              "unit/skills/tasks_board/test_skill_tasks_board.py", "unit/skills/google_workspace/test_eventos_varios_dias.py",
              "unit/skills/google_workspace/test_eventos_google_rango.py", "unit/skills/google_workspace/test_rangos_semana.py",
              "unit/skills/google_workspace/test_calendario_por_fecha.py",
              "unit/skills/autoprovision/test_skill_autoprovision.py", "unit/skills/media/test_skill_media.py",
              "unit/skills/chrome/test_skill_chrome.py", "unit/skills/content_os/test_skill_content_os.py",
              "unit/skills/datos/test_skill_datos.py", "unit/skills/vigilancias/test_skill_vigilancias.py",
              "unit/memory/test_skill_memory_graph.py", "unit/skills/coach/test_skill_coach.py",
              "unit/skills/tools/test_skill_tools.py", "unit/skills/research/test_skill_research.py",
              "unit/skills/research/test_source_evidence.py", "unit/skills/research/test_google_browser.py",
              "unit/skills/backup/test_skill_backup.py", "unit/skills/telefono/test_skill_telefono.py",
              "unit/skills/small_skills/test_skills_pequenas_1.py", "unit/skills/small_skills/test_skills_pequenas_2.py",
              "unit/frontend/test_modules.py", "unit/core/runtime/test_capas_backend.py", "unit/core/runtime/test_log_aislado.py", "unit/core/test_resultados_trabajos.py",
              "unit/core/learning/test_reglas_valores.py", "unit/core/learning/test_reglas_contrato.py",
              "unit/core/learning/test_aprendizaje_puertas.py", "unit/core/learning/test_aprendizaje_no_robo.py",
              "unit/core/learning/test_aprendizaje_ciclo.py", "unit/core/learning/test_correcciones_confirmadas.py",
              "unit/routing/test_lo_prometido.py", "unit/memory/test_grafo_solo_conocimiento.py",
              "unit/conversation/test_saludo_una_vez.py", "unit/conversation/test_calla_al_escribir.py", "unit/conversation/test_no_promete_trabajo.py", "unit/conversation/test_apunta_no_es_siempre_memoria.py", "unit/conversation/test_regresion_conversacion.py", "unit/conversation/test_que_sabes_de_mi.py",
              "unit/memory/test_grafo_vista.py"):
    print(f"== 3) suite {suite} ==")
    # UTF-8 forzado: en la consola de Windows (cp1252) un «✔» en un mensaje
    # reventaba la suite entera con UnicodeEncodeError.
    _env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "NEXUS_DATA_DIR": tempfile.mkdtemp(prefix="nexus_suite_data_")}
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", suite)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_env)
    # SEGUNDA OPORTUNIDAD para las suites que ARRANCAN UN SERVIDOR. Con toda la
    # batería corriendo, uvicorn puede tardar más de la cuenta en levantar y la
    # suite fallaba por impaciencia: un rojo que no era un fallo real y que
    # obligaba a repetir a mano para saber si era verdad. Si falla, se repite una
    # vez; si vuelve a fallar, ES un fallo y cuenta como tal.
    if r.returncode != 0 and suite in ("integration/http/test_entrega_real.py", "integration/http/test_acceso_remoto.py"):
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

print(f"\n{'#'*54}\nRESULTADO RUNNER AMPLIO: {'suites registradas sin fallos observados ✔ (no es prueba global)' if fails == 0 else str(fails)+' bloque(s) con fallos ✖'}")
sys.exit(1 if fails else 0)
