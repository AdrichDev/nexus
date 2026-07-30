# 🎨 Skill: IA / Multimedia

Los sentidos extra de nexus: genera bocetos de imagen, examina archivos de
imagen, transcribe audios a texto con Whisper local (real) y responde
preguntas con búsqueda web real multi-fuente (Google News RSS → DuckDuckGo
Lite → DuckDuckGo HTML, sin API key). Es la PRIMERA skill del router
(orden alfabético), por eso todos sus patrones llevan ancla de dominio.

## Órdenes de ejemplo (todas cazadas por los patterns)

- «genera una imagen de un dragón cyberpunk» / «hazme un cartel para la fiesta»
- «dibuja un logo para la marca de calcetines»
- «analiza la imagen D:\fotos\logo.png» / «describe la foto C:\tmp\stand.jpg»
- «qué ves en la imagen D:\capturas\error.png»
- «transcribe el audio D:\notas\reunion.mp3»
- «pasa a texto la nota de voz D:\audios\idea.ogg y guárdala»
- «busca en internet quién ganó el mundial de clubes»
- «googlea precio del cobre hoy» / «qué dice internet sobre el nuevo iPhone»

## Qué es real y qué no (honesto)

- **Búsqueda web**: REAL, sin API key (backend/core/websearch.py, 3 fuentes
  con fallback). Devuelve respuesta + fuentes.
- **Transcripción**: REAL con faster-whisper (el mismo modelo del STT del HUD);
  guarda transcripción + ideas en la memoria (nota Obsidian + Postgres si hay).
  Si falta la librería: `pip install faster-whisper`.
- **Generar imágenes**: placeholder SVG en `data/captures/` — el hueco para
  conectar Stable Diffusion (API Automatic1111) o DALL·E está marcado en
  `skills/ai_media/skill.py`.
- **Visión (describir contenido)**: solo metadatos (tamaño, dimensiones vía
  Pillow). Para descripción real: `ollama pull llava` y conectarlo en la skill.

## Notas de routing (no robar)

- «haz una foto» (webcam) y «captura de pantalla» son de system_pc.
- «busca X en google maps» es de places (lookahead `google(?!\s*maps)`).
- «investiga X y hazme un informe» es de research (aquí solo búsqueda rápida
  con ancla explícita «en internet / googlea»).
