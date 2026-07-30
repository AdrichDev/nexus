# SPECS v20 — las 5 pendientes de v19, implementadas: contexto, cadenas, revisión, perfil y panel HOY
_2026-07-24 · Cada spec con su criterio de aceptación y el RESULTADO de la validación
(suite completa: `python tests/run_all.py` → TODO VERDE, 637 checks; revisión de código
adversaria con modelo opus: 4 hallazgos confirmados, todos corregidos y cubiertos con
tests; QA final independiente con modelo sonnet: 184/184 → APTO)._

## SPEC M8 — Contexto multi-turno («llama al segundo»)
**Qué:** backend/core/context.py + integración en el cerebro. Cuando nexus muestra una
LISTA (pestañas, contactos, informes, vigilancias, encargos, tareas), se queda con los
elementos; si la siguiente frase es una referencia («resume la segunda», «llama al
segundo», «borra la 3», «el último»), la traduce a la orden completa ANTES del router
con una plantilla por fuente, y lo explica en el log («🧭 Interpreto X como Y»).
**Salvaguardas (de la revisión opus):** whitelist de VERBOS por fuente, la referencia
debe ir al FINAL de la frase («abre el segundo cajón» NO es una referencia), número
dentro de rango, contexto POR CANAL (la lista del PC no vale para Telegram), frases
≤70 caracteres y TTL de 10 minutos. Si algo no cuadra, no toca nada.
**✔ VALIDADO:** 27 checks propios + QA sonnet con 20 frases cotidianas trampa («pon la
primera de Bad Bunny», «ponme la tercera canción»…) → 0 secuestros, y todas las
referencias legítimas resuelven. Aislamiento pc/telegram/mobile verificado.

## SPEC M4 — Cadenas secuenciales (orquestación multi-paso)
**Qué:** «investiga los precios del algodón y luego crea la tarea comprar muestras y
después envía un whatsapp a Rubén diciendo listo» → nexus la parte por conectores de
ORDEN explícitos («y luego», «después», «, luego», «a continuación», «por último»,
«finalmente») y la ejecuta como UN trabajo numerado en 2º plano (Cadena #N): pasos en
orden, cada paso emite su respuesta al chat, y al final resumen ⛓ con ✔/⚠ por paso
(también por Telegram si vino de ahí). «y» a secas JAMÁS parte («pon rock y jazz»).
Complementa la multi-orden ya existente (órdenes independientes inline).
**✔ VALIDADO:** 6 checks propios + 22 de QA sonnet (8 frases con conector, 8 sin, orden
conservado, límites) + verificación de guards: un paso de cadena (source="job") no
puede re-disparar cadenas, multi-orden ni multitarea — sin recursión posible.

## SPEC M6 — Revisión semanal del tablero
**Qué:** backend/core/review.py. El domingo a las 19:00 (weekly_review_enabled/_day/
_hour en settings) nexus canta el balance ÉL SOLO (HUD + Telegram): completadas de la
semana (por fecha de COMPLETADO — board.move_task ahora sella t["completed"], fix de
la revisión opus), vencidas sin hacer, tareas muertas +14 días («¿las mato o les pongo
fecha?»), informes y encargos de la semana, y propuesta de foco (Eisenhower). A demanda:
«revisión semanal» / «balance de la semana» (skill coach, intent weekly).
**✔ VALIDADO:** 14 checks propios (due con bordes, tablero temporal, sello de
completado) + QA sonnet 27 checks incluida la frontera de año ISO (2026-W53) y el borde
exacto de 14 días.

## SPEC M7 — Perfil del operador + consolidación nocturna
**Qué:** backend/core/profile.py. «mi perfil» / «quién soy» / «háblame de mí» (skill
memoria; «qué sabes de mí» sigue siendo el listado de conocimiento, por contrato de
tests) → retrato con DATOS REALES: configuración, perfil destilado por selflearn,
tablero, agenda, vigilancias, encargos, informes y notas. Y cada madrugada (≥4h) el
diario de AYER se RESUME con el LLM en una nota «resumen AAAA-MM-DD» (+ memoria RAG si
hay DB); el diario queda marcado y no se repite. Guard anti-doble (_busy), timeout 180s
al LLM, escrituras en hilo y disparo como tarea suelta para no retrasar el scheduler.
**✔ VALIDADO:** 13 checks propios + QA sonnet 26 (ciclo completo con LLM falso, guard
_busy bajo concurrencia real con asyncio.gather → solo una consolida, no-repetición).

## SPEC M9 — Panel «HOY» del HUD
**Qué:** nueva vista ☀ Hoy en el HUD (primera del menú tras el centro de mando):
tarjetas con clima, tareas (vencidas/próximas/en marcha), encargos a Hermes con estado,
vigilancias activas e informes recientes; auto-refresco cada 60 s mientras está abierta.
Alimentada por GET /api/today (backend/app.py → briefing.today_payload(), estructurado
y a prueba de fallos por sección). Todo el contenido pasa por esc2 (sin XSS).
**✔ VALIDADO:** 8 checks propios + QA sonnet 39 (estructura, orden, vacíos sin
excepción, endpoint presente, #num escapados). Pendiente solo el vistazo VISUAL en tu
PC (no reproducible en sandbox).

## Revisión y endurecimiento (opus)
Hallazgos corregidos: (1) GRAVE — resolve() secuestraba frases cotidianas con ordinal
(«pon la primera de Bad Bunny» tras una lista → resumía la pestaña 1): whitelist de
verbos + referencia al final + rango; (2) contexto compartido entre canales →
aislamiento por canal; (3) «Completadas esta semana» contaba por fecha de creación →
sello t["completed"] en move_task; (4) referencias fuera de rango («resume la 99») →
rechazadas. Extras: consolidación con guard, timeout y to_thread; #num escapados en el
panel HOY. Observaciones menores documentadas por QA: board.overdue() usa el reloj real
(no el inyectado) en la sección de vencidas del balance; el fallback de perfil vacío es
prácticamente inalcanzable.
