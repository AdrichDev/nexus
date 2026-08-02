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

## Necesita configurado

La carpeta `knowledge/` con una subcarpeta por skill, cada una con su
`SKILL.md`. Si está vacía, la skill lo dice y no responde nada más. Y un
proveedor en ⚙ Núcleo IA: la respuesta la redacta el LLM siguiendo la guía.

## Qué NO hace

- **No ejecuta las skills**: no crea ramas, ni PRs, ni ficheros de spec. Son
  guías que se le inyectan al modelo para que conteste siguiéndolas.
- No inventa metodologías: si el nombre que pides no está en `knowledge/`, te
  lista las que sí hay.
- Solo lee los primeros 6000 caracteres de cada guía.
- No sale a internet a buscar skills nuevas: se añaden a mano en `knowledge/`.
