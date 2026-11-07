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
    "unit/core/test_secretos.py",
    # El almacén de claves deja de estar en claro (SEC-09, roadmap P2-6, T13):
    # cifrado con DPAPI, migración con verificación previa y repliegue a JSON
    # plano donde no hay DPAPI. Carpetas de usar y tirar para config y data ANTES
    # de importar el backend y valores inventados («sk-TEST-VALUE-…»): no se abre
    # ni un byte del material del operador. En Windows llama a la DPAPI DE VERDAD
    # —una llamada local al sistema, sin red y sin efectos fuera del proceso— y en
    # cualquier otra plataforma lo DICE y solo prueba el repliegue, así que allí la
    # evidencia baja a «el modo sin cifrado sigue funcionando» (no es prueba del
    # cifrado). Incluye `GET /api/config` en proceso (httpx.ASGITransport, sin
    # lifespan ni puertos) y la autocomprobación del escáner de antes de subir.
    "unit/core/test_secretos_cifrado.py",
    # Permisos de ficheros seguros por defecto (SEC-04) y cambios de permisos
    # solo desde la ventana local (SEC-12): en proceso, con un PERFIL de mentira
    # y el lector real espiado, sin escribir nada del operador.
    "unit/core/test_permisos_ficheros.py",
    # Redacción de los registros con texto del operador (AI-02/PRIV-01):
    # interactions.jsonl, el prompt del destilado, audit.jsonl y recall.jsonl.
    # En proceso, sin red, con carpetas de usar y tirar.
    "unit/core/test_redaccion_logs.py",
    # Vinculación de Telegram con código de un solo uso (SEC-02): puente y
    # GET /api/telegram/link en proceso (httpx.ASGITransport, sin lifespan ni
    # puertos), cliente de la Bot API de mentira y carpetas de usar y tirar.
    "unit/core/test_telegram_link.py",
    # Escrituras atómicas de los almacenes JSON de runtime (ARQ-05, roadmap
    # P2-9): se dobla os.replace para matar la escritura justo entre el .tmp y
    # el reemplazo, almacén por almacén (tablero, papelera, marca de claves,
    # jobs, Content OS y proactividad), en proceso y con carpetas de usar y
    # tirar. Incluye la guardia estructural sobre write_text() en backend y
    # skills. No arranca servidor ni toca un dato del operador.
    "unit/core/test_escrituras_atomicas.py",
    # Memoria operativa con candado (SEC-06/AI-04): la orden permanente se
    # confirma, apunta de dónde viene y solo la puede fijar el equipo del
    # operador; lo que devuelve Engram se lee como dato citado. En proceso, con
    # Engram, RAG, espejo y modelo doblados y carpetas de usar y tirar.
    "unit/core/learning/test_opmem_candado.py",
    # Contenido no confiable marcado en el prompt (AI-03, roadmap P2-4): el
    # dossier web, el RAG, las memorias, lo que devuelve MCP y el resultado de
    # un trabajo viajan cercados con su origen y fuera de `system`; la pregunta
    # del operador sigue yendo tal cual. Proveedor y cliente HTTP doblados (una
    # petición a un host que la prueba no espera revienta), RAG/web/DB/grafo
    # doblados y carpetas de usar y tirar. No arranca servidor ni toca un dato
    # del operador.
    "unit/core/test_datos_no_confiables.py",
    # Destino seguro contra SSRF (SEC-11, roadmap P3-1): la guarda compartida de
    # `comun/net.py` rechaza loopback, link-local/metadatos, RFC1918, CGNAT,
    # multicast, esquemas que no son http/https, `usuario:clave@` y los nombres
    # que resuelven a esas direcciones; `safe_get` revalida cada redirección. La
    # aplican `websearch.fetch_page`, la descarga de subtítulos de YouTube,
    # `vigilancias` (al crear y en cada tick) y `datos` (sqlite por
    # `path_allowed`, bases de red solo desde el equipo del operador). Transporte
    # y resolutor doblados ANTES de la primera llamada: ni una conexión ni una
    # consulta DNS de verdad, y config/datos/perfil de usar y tirar.
    "unit/core/test_destino_seguro.py",
    "unit/skills/places/test_places_honesty.py",
    "unit/skills/datos/test_datos_honesty.py",
    "unit/skills/vigilancias/test_vigilancias_integrity.py",
    "unit/skills/ai_media/test_ai_media_honesty.py",
    "unit/skills/research/test_research_honesty.py",
    "unit/memory/test_redaccion_memoria.py",
    "unit/frontend/test_modules.py",
    # Escapes y cabeceras del HUD (SEC-10, roadmap P2-11): `esc()` escapa también
    # las comillas (y con ella `linkify`/`mdToHtml` y la ficha de Reels), y el HTML
    # del HUD (`/`, `/m`, `/setup`) sale con CSP `frame-ancestors 'none'` y
    # `X-Frame-Options: DENY`. El JavaScript se EJECUTA con `node` (ESM, sin
    # navegador); si no hay node, esa parte se salta con un aviso explícito y solo
    # se comprueban las cabeceras, así que un verde sin node NO prueba el escape.
    # Las cabeceras van con httpx.ASGITransport (sin lifespan, sin puertos) y
    # config/datos de usar y tirar.
    "unit/frontend/test_escapes_y_cabeceras.py",
    # Restaurar de verdad (P2-10 / PRIV-04): manifiesto con sha256, restauración a
    # una carpeta nueva, rechazo de zip-slip y la copia al segundo disco. En
    # proceso y sobre árboles `mktemp -d`: no lee el data/ ni el config/ del
    # operador (apunta NEXUS_DATA_DIR/NEXUS_CONFIG_DIR antes de importar) y no
    # habla con ningún proveedor.
    "unit/skills/backup/test_restaurar.py",
    "unit/core/runtime/test_log_aislado.py",
    # Reserva del cerebro entre clases de localidad (AI-01/PRIV-02) y tope de
    # tokens de salida (AI-07): cliente HTTP doblado (nada sale a la red) y
    # carpetas de usar y tirar.
    "unit/core/runtime/test_fallback_privacidad.py",
    # Contador diario de llamadas y caracteres por proveedor y techo que frena la
    # nube con un mensaje honesto (AI-07, roadmap P2-12): el cliente HTTP va
    # doblado ANTES de la primera llamada, el reloj se mueve a mano (sin dormir),
    # el corte de escritura se simula doblando `os.replace` y config/datos viven
    # en carpetas de usar y tirar. No arranca servidor (`/api/status` va con
    # httpx.ASGITransport, sin lifespan) ni toca un dato o una clave del operador.
    "unit/core/runtime/test_presupuesto_llm.py",
    # POST /api/n8n en proceso (httpx.ASGITransport, sin lifespan ni puertos):
    # dobles en vez de proveedor/correo y carpetas de usar y tirar.
    "integration/http/test_n8n_canal.py",
    # Host/Origin de la confianza local y el token que ya no sale en
    # /api/link/status (SEC-03): en proceso (httpx.ASGITransport, sin lifespan ni
    # puertos), direcciones de red dobladas y carpetas de usar y tirar.
    "integration/http/test_host_origin.py",
    # Lista blanca de herramientas MCP, «sí» para las de escritura y la salida
    # como dato (SEC-18 / AI-10, roadmap P3-7): `asyncio.create_subprocess_exec`
    # va doblado ANTES de la primera llamada, así que no arranca ni un `npx`, y
    # config/datos viven en carpetas de usar y tirar.
    "unit/skills/mcp/test_mcp_permisos.py",
)

STATIC_SAFE_SUITES = (
    "unit/frontend/test_task_cards.py",
    # La app Android deja de fiarse de cualquier página y de cualquier transporte
    # (SEC-08, roadmap P2-5): manifiesto sin `usesCleartextTraffic`, network
    # security config con TLS del sistema, sin `MIXED_CONTENT_ALWAYS_ALLOW`, el
    # puente `WabiksNative` atado al host emparejado, confirmación nativa en
    # `dial`/`whatsapp` y el texto de la voz como literal JSON. Es SOLO lectura
    # del Java, del XML y de las dos HTML: no compila la APK ni arranca un móvil,
    # así que no prueba el comportamiento en el dispositivo (ver el docstring de
    # la suite). Evidencia S, la más baja: texto del fuente, no ejecución.
    "unit/mobile/test_puente_nativo.py",
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
    # Supresión completa (PRIV-03 / P2-8): el dato purgado no queda en ningún
    # almacén. Todo el árbol es de usar y tirar, Engram es un doble en memoria y
    # Postgres se fuerza offline; se etiqueta unsafe-legacy por el mismo motivo
    # honesto que test_purga.py: importa la configuración de producción antes de
    # que sus dobles estén puestos.
    "unit/memory/test_purga_completa.py",
    "unit/memory/test_ingesta_documentos.py",
    "unit/core/runtime/test_openrouter_privacidad.py",
    "unit/skills/content_os/test_content_os_honestidad.py",
    "unit/skills/domotica/test_skill_domotica.py",
    "unit/skills/hermes/test_empty_response.py",
    "unit/skills/hermes/test_skill_hermes.py",
    # Delegación en el ejecutor (T25 / P3-6): localidad del cerebro de Hermes con
    # el consentimiento de nube de T6, confirmación con el encargo exacto y
    # reintentos que no reenvían un encargo que ya pudo ejecutarse. Todo en
    # proceso con el transporte doblado antes de la primera llamada y config/datos
    # en carpetas de usar y tirar; se etiqueta unsafe-legacy por el mismo motivo
    # honesto que sus dos hermanas (importa backend/config antes de armar dobles).
    "unit/skills/hermes/test_delegacion.py",
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
    # T37: la puerta por voz/texto del «olvida...». Previsualiza y arma la
    # confirmación del motor de purga (T15) contra un árbol de usar y tirar, con
    # Postgres offline y Engram doblado; se etiqueta unsafe-legacy por el mismo
    # motivo honesto que sus hermanas: carga TODAS las skills antes de armar sus
    # dobles por caso (aunque config/ y data/ ya vienen redirigidos al importar).
    "unit/skills/memory_graph/test_olvidar.py",
    "unit/skills/coach/test_skill_coach.py",
    "unit/skills/tools/test_skill_tools.py",
    "unit/skills/research/test_skill_research.py",
    "unit/skills/research/test_source_evidence.py",
    "unit/skills/backup/test_skill_backup.py",
    "unit/skills/telefono/test_skill_telefono.py",
    "unit/skills/small_skills/test_skills_pequenas_1.py",
    "unit/skills/small_skills/test_skills_pequenas_2.py",
    # WhatsApp de n8n: se arma, se confirma y no sale dos veces (SEC-05).
    # En proceso, con _post y el móvil doblados y carpetas de usar y tirar.
    "unit/skills/n8n_flows/test_envios.py",
    "unit/core/runtime/test_capas_backend.py",
    "unit/core/test_resultados_trabajos.py",
    # Errores de la API sin fugas (SEC-16) y callback de Spotify con `state` (SEC-15).
    # En proceso (ASGITransport, sin lifespan) y con config/datos de usar y tirar.
    "unit/core/test_errores_api.py",
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
