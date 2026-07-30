# 🏋️ Skill: Coach / Secretario ("agenda vitaminada")

El corazón de nexus según las sesiones de diseño: no una agenda que solo dice
QUÉ hacer, sino un entrenador que enseña CÓMO hacerlo y no deja que el operador
se pierda. Combina briefing diario, objetivos desglosados por el LLM, checklists
vivos, recordatorios escalonados y replanificación de imprevistos.

## Órdenes de ejemplo (frases que los patrones cazan de verdad)

- "qué me toca hoy" / "plan de hoy" / "resumen del día" → briefing con
  objetivos activos, checklists pendientes y un consejo de coach.
- "nuevo objetivo: fabricar camisetas en China" / "me propongo: correr 10k"
  → lo desgrana en 5-7 pasos accionables y lo guarda (DB + grafo).
- "mis objetivos" / "cómo van mis objetivos" → lista con progreso X/Y pasos.
- "crea un checklist semanal revisar emails" / "hazme una lista de control
  para la mudanza" → checklist vivo (se amplía cuando quieras).
- "añade al checklist llamar al gestor" / "apunta en el checklist comprar cinta".
- "recuérdame renovar el DNI el 3 de agosto" / "avísame de la ITV el viernes" /
  "recuérdame llamar a mamá mañana" → recordatorio ESCALONADO: aviso 1 semana
  antes, 2 días antes y el día D (minion recordador).
- "me ha surgido un imprevisto..." / "replanifica" → reorganiza el día
  (qué pospones, qué mantienes, qué delegas).
- "estoy agobiado" / "no doy abasto" / "no me da la vida" → coaching:
  baja la carga a tierra y prioriza UNA cosa para hoy.
- "planifica el proyecto tienda online" / "crea una spec para el bot de ventas"
  → SPEC interna (diseño/propuesta/tareas/validaciones) revisada por el
  abogado del diablo y con las tareas volcadas al tablero.

## Notas técnicas

- Recordatorios y objetivos persistentes requieren la DB Postgres del Docker de
  memoria; sin ella funcionan en memoria local (se pierden al reiniciar) y la
  skill lo avisa.
- El desglose de objetivos, la replanificación y las specs usan el LLM
  (backend.core.llm.ask_llm); las specs se guardan en data/specs/*.md y sus
  tareas se crean en el tablero (backend.core.board).
- Fechas entendidas: "mañana", "pasado mañana", días de la semana, "25/07",
  "3 de agosto", "en un mes". Hora por defecto de los avisos: 09:00 UTC.
- Cuidado con el orden del router: "qué tengo hoy" es de la agenda de Google,
  "recuerda que..." es de la memoria y "organiza mis tareas" del tablero —
  esta skill no los pisa a propósito.
