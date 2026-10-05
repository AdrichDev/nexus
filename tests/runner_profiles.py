# -*- coding: utf-8 -*-
"""Static evidence metadata for suites registered by tests/run_all.py.

These labels make the broad runner honest: a green subprocess exit is not the
same as provider, physical-device, or whole-product proof.  Conservative
``unsafe-legacy`` means the suite may still import production config, all skills,
real devices, or provider-shaped code before its doubles apply.
"""

ALLOWED_PROFILES = {
    "safe-unit",
    "isolated-integration",
    "authorized-device",
    "provider-contract",
    "unsafe-legacy",
}
ALLOWED_EVIDENCE_LEVELS = {"S", "M", "I", "P", "F"}


def _meta(profile, evidence_level, side_effects, requires, safe_to_run_in_live_checkout):
    return {
        "profile": profile,
        "evidence_level": evidence_level,
        "side_effects": tuple(side_effects),
        "requires": tuple(requires),
        "safe_to_run_in_live_checkout": safe_to_run_in_live_checkout,
    }


SAFE_UNIT_META = _meta(
    "safe-unit",
    "M",
    ("in-process mocks or temporary files only",),
    ("project Python", "no real provider/device/account"),
    True,
)
STATIC_SAFE_META = _meta(
    "safe-unit",
    "S",
    ("static source inspection only",),
    ("project checkout",),
    True,
)
ISOLATED_INTEGRATION_META = _meta(
    "isolated-integration",
    "I",
    ("temporary subprocess/server state", "temporary NEXUS_DATA_DIR"),
    ("project Python", "ephemeral localhost resources"),
    False,
)
PROVIDER_CONTRACT_META = _meta(
    "provider-contract",
    "M",
    ("provider doubles or fixture data", "temporary NEXUS_DATA_DIR"),
    ("project Python", "no live provider credentials"),
    False,
)
AUTHORIZED_DEVICE_META = _meta(
    "authorized-device",
    "M",
    ("device-control code paths are exercised through doubles", "temporary NEXUS_DATA_DIR"),
    ("explicit owner approval before any physical-device run",),
    False,
)
UNSAFE_LEGACY_META = _meta(
    "unsafe-legacy",
    "S",
    ("may import production config, all skills, or host-coupled modules",),
    ("manual preflight before standalone execution", "do not treat broad-runner green as global proof"),
    False,
)

SAFE_UNIT_SUITES = (
    "unit/skills/domotica/test_tv_power.py",
    "unit/skills/clima/test_clima_errors.py",
    "unit/frontend/test_modules.py",
    "unit/core/runtime/test_log_aislado.py",
)

STATIC_SAFE_SUITES = (
    "unit/frontend/test_task_cards.py",
)

ISOLATED_INTEGRATION_SUITES = (
    "integration/http/test_acceso_remoto.py",
    "integration/http/test_entrega_real.py",
)

PROVIDER_CONTRACT_SUITES = (
    "unit/skills/google_workspace/test_inbox_fake_gmail.py",
    "unit/skills/google_workspace/test_inbox_scale.py",
    "unit/skills/google_workspace/test_drive.py",
    "unit/skills/google_workspace/test_skill_google_workspace.py",
    "unit/skills/google_workspace/test_eventos_varios_dias.py",
    "unit/skills/google_workspace/test_eventos_google_rango.py",
    "unit/skills/google_workspace/test_rangos_semana.py",
    "unit/skills/google_workspace/test_calendario_por_fecha.py",
    "unit/skills/research/test_google_browser.py",
)

AUTHORIZED_DEVICE_SUITES = (
    "unit/skills/domotica/test_dispositivos.py",
)

UNSAFE_LEGACY_SUITES = (
    "unit/routing/test_all.py",
    "unit/routing/test_routing.py",
    "unit/routing/test_verificaciones.py",
    "unit/specs/test_renovacion.py",
    "unit/specs/test_mejoras_v19.py",
    "unit/specs/test_specs_v20.py",
    "unit/specs/test_v21_fixes.py",
    "unit/specs/test_specs_v23.py",
    "unit/specs/test_specs_v23_orq.py",
    "unit/specs/test_specs_v23_mem.py",
    "unit/specs/test_specs_v23_files.py",
    "unit/specs/test_specs_v23_ui.py",
    "unit/specs/test_specs_v23_hermes.py",
    "unit/specs/test_specs_v24.py",
    "unit/core/runtime/test_llm_runtime.py",
    "unit/core/runtime/test_tunel_adoptado.py",
    "unit/skills/instagram/test_instagram.py",
    "unit/skills/instagram/test_analisis.py",
    "unit/skills/instagram/test_spec.py",
    "unit/skills/instagram/test_competencia.py",
    "unit/skills/instagram/test_skill_instagram_conexion.py",
    "unit/core/runtime/test_nucleo.py",
    "unit/core/runtime/test_umbrales.py",
    "unit/skills/instagram/test_descubrimiento.py",
    "unit/skills/instagram/test_descubrimiento_flujo.py",
    "unit/skills/instagram/test_inteligencia.py",
    "unit/conversation/test_frases_reales.py",
    "unit/skills/instagram/test_visual.py",
    "unit/core/runtime/test_apis_config.py",
    "unit/core/test_board_pattern.py",
    "unit/core/test_board_kpis.py",
    "unit/core/test_board_keys.py",
    "unit/core/test_inbox_tasks.py",
    "unit/memory/test_engram.py",
    "unit/memory/test_hermes_engram.py",
    "unit/memory/test_memoria_embeddings.py",
    "unit/memory/test_purga.py",
    "unit/memory/test_ingesta_documentos.py",
    "unit/core/runtime/test_openrouter_privacidad.py",
    "unit/skills/content_os/test_content_os_honestidad.py",
    "unit/skills/domotica/test_skill_domotica.py",
    "unit/skills/hermes/test_empty_response.py",
    "unit/skills/hermes/test_skill_hermes.py",
    "unit/skills/files/test_skill_files.py",
    "unit/skills/system_pc/test_skill_system_pc.py",
    "unit/skills/system_pc/test_volumen_destino.py",
    "unit/skills/tasks_board/test_skill_tasks_board.py",
    "unit/skills/autoprovision/test_skill_autoprovision.py",
    "unit/skills/media/test_skill_media.py",
    "unit/skills/chrome/test_skill_chrome.py",
    "unit/skills/content_os/test_skill_content_os.py",
    "unit/skills/datos/test_skill_datos.py",
    "unit/skills/vigilancias/test_skill_vigilancias.py",
    "unit/memory/test_skill_memory_graph.py",
    "unit/skills/coach/test_skill_coach.py",
    "unit/skills/tools/test_skill_tools.py",
    "unit/skills/research/test_skill_research.py",
    "unit/skills/research/test_source_evidence.py",
    "unit/skills/backup/test_skill_backup.py",
    "unit/skills/telefono/test_skill_telefono.py",
    "unit/skills/clima/test_clima_errors.py",
    "unit/skills/small_skills/test_skills_pequenas_1.py",
    "unit/skills/small_skills/test_skills_pequenas_2.py",
    "unit/core/runtime/test_capas_backend.py",
    "unit/core/test_resultados_trabajos.py",
    "unit/core/learning/test_reglas_valores.py",
    "unit/core/learning/test_reglas_contrato.py",
    "unit/core/learning/test_aprendizaje_puertas.py",
    "unit/core/learning/test_aprendizaje_no_robo.py",
    "unit/core/learning/test_aprendizaje_ciclo.py",
    "unit/core/learning/test_correcciones_confirmadas.py",
    "unit/routing/test_lo_prometido.py",
    "unit/memory/test_grafo_solo_conocimiento.py",
    "unit/conversation/test_saludo_una_vez.py",
    "unit/conversation/test_calla_al_escribir.py",
    "unit/conversation/test_no_promete_trabajo.py",
    "unit/conversation/test_apunta_no_es_siempre_memoria.py",
    "unit/conversation/test_regresion_conversacion.py",
    "unit/conversation/test_que_sabes_de_mi.py",
    "unit/memory/test_grafo_vista.py",
)

RUNNER_PROFILES = {
    **{path: SAFE_UNIT_META for path in SAFE_UNIT_SUITES},
    **{path: STATIC_SAFE_META for path in STATIC_SAFE_SUITES},
    **{path: ISOLATED_INTEGRATION_META for path in ISOLATED_INTEGRATION_SUITES},
    **{path: PROVIDER_CONTRACT_META for path in PROVIDER_CONTRACT_SUITES},
    **{path: AUTHORIZED_DEVICE_META for path in AUTHORIZED_DEVICE_SUITES},
    **{path: UNSAFE_LEGACY_META for path in UNSAFE_LEGACY_SUITES},
}


def profile_counts():
    counts = {profile: 0 for profile in sorted(ALLOWED_PROFILES)}
    for meta in RUNNER_PROFILES.values():
        counts[meta["profile"]] += 1
    return counts
