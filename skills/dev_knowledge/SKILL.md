# Skill: Biblioteca de conocimiento (openClaw / Gru)

Importa las ~21 skills de Gru-Orchestrator/openClaw como CONOCIMIENTO que
nexus carga bajo demanda para tareas de desarrollo (no ejecuta código: son
guías/prompts que inyecta en el contexto del LLM).

Incluye: metodología SDD completa (sdd-init, sdd-explore, sdd-propose,
sdd-spec, sdd-design, sdd-tasks, sdd-apply, sdd-verify, sdd-archive),
judgment-day (revisión crítica), skill-creator, skill-improver,
branch-pr, chained-pr, comment-writer, go-testing, issue-creation,
work-unit-commits, cognitive-doc-design, skill-registry.

- "qué skills de desarrollo tienes" / "biblioteca de skills" → lista
- "aplica la skill <nombre> a <tarea>" → carga esa SKILL.md como guía y
  responde siguiéndola (ej: "aplica la skill sdd-spec a mi login")
- "cómo hago un PR" / "revisa esto como judgment-day" → detecta la skill
  relevante por palabras clave y la aplica

Las skills viven en la carpeta `knowledge/` del repo. Añade más metiendo
carpetas con su SKILL.md ahí dentro.
