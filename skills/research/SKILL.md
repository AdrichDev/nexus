# Skill: Investigación / Informes 📚

Busca en la web, lee las mejores fuentes y redacta informes estructurados con
las fuentes citadas. Guarda el histórico y sabe reabrir uno viejo.

## Qué hace y con qué frases se dispara

- **Informe de investigación**: «investiga <tema>» · «investígame <tema>» ·
  «investiga sobre <tema> y hazme un informe» · «indaga sobre <tema>» ·
  «documéntame sobre <tema>» · «hazme un informe sobre <tema>» ·
  «redáctame/escríbeme/prepárame un informe de <tema>»
  → busca, lee hasta 4 páginas, redacta (resumen ejecutivo, hallazgos,
  oportunidades, recomendación), guarda `data/reports/<tema>-<fecha>.md`
  (+ `.docx` si hay `python-docx`) y lo abre.
- **Tendencias**: «tendencias de <nicho>» · «tendencias en <nicho>» ·
  «qué se lleva ahora en <nicho>»
- **Económico**: «informe económico» · «dónde puedo apurar» · «dónde puedo
  recortar gastos» · «optimiza los gastos» · «análisis de mis gastos» ·
  «cómo van mis gastos»
  → analiza SOLO las facturas de la DB y los apuntes de gasto del grafo, y
  dice sobre cuántos apuntes reales trabaja.
- **Histórico**: «mis informes» · «qué informes tienes» · «historial de
  informes» · «muéstrame los informes»
- **Reabrir**: «abre el informe de <tema>» · «reabre el informe de <tema>» ·
  «enséñame el informe de <tema>»

## Qué necesita configurado

- Un LLM configurado (`config/settings.json`) para redactar.
- Salida a internet. Sin API keys: usa el motor central de nexus
  (`backend/core/websearch.py`): Google News RSS, DDG Lite y DDG HTML.
- `python-docx` (lo instala `run.bat`) solo si quieres el `.docx` además del
  `.md`; sin él sale el `.md` igual y no se anuncia un Word que no existe.
- Lo económico necesita datos ya cargados: facturas (skill billing) o apuntes
  de gasto en la memoria.

## Qué NO hace

- **No hace scraping.** Solo lee páginas públicas por el motor central, con su
  caché. No entra en zonas con login ni recoge datos de audiencias ajenas.
- **No inventa un informe sin fuentes.** Si no consigue leer ninguna, lo dice
  en la primera línea, marca la respuesta como conocimiento general no
  contrastado y NO la guarda en el histórico.
- **No inventa cifras económicas**: lo que no esté en tus facturas o tus
  apuntes no aparece.
- No trae datos nativos de Instagram/TikTok: no tienen API pública gratuita de
  tendencias. Para eso está la skill `instagram` (Graph API oficial).
- «dile a hermes: investiga esto» no es de aquí: eso lo lleva `hermes`, y
  «busca en internet ...» lo lleva `ai_media`.
