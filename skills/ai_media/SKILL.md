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
- «busca información sobre python» / «búscame información de la ley de
  teletrabajo» / «consulta datos sobre el IBEX» — el sustantivo
  (información/info/datos/referencias) hace de ancla, así que no hace falta
  decir «en internet». Si la frase termina en «en la carpeta X», «en mis
  notas» o «en el mapa», no es de aquí y se deja pasar.

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

## Detalles que importan

- **Rutas**: admite comillas y espacios en la ruta («analiza la imagen "D:\mis fotos\logo.png"») y
  recorta coletillas («… por favor», «… y guárdala»). Si no la encuentra, te devuelve la ruta tal como la escribiste.
- **Un archivo que no es imagen** se dice tal cual; no se presenta como una imagen con metadatos.
- **Búsqueda web**: la respuesta lleva una línea «Fuentes: dominio1, dominio2…». Si el modelo no está disponible,
  no inventa nada: te enseña los resultados que sí encontró (título y enlace) y dice por qué no redactó la respuesta.
- **Transcripción**: guarda el audio ENTERO (la nota completa y la base de datos en trozos); si el modelo no está
  disponible, guarda la transcripción sin análisis y lo avisa (el mensaje de error nunca se guarda como análisis).
  Cada audio tiene su propia nota (nombre + huella de la ruta), así que dos audios no se pisan.
- **Boceto de imagen**: el texto que pides se escapa antes de ir al SVG; el archivo es siempre un SVG válido.

## Qué NO hace

- **No genera imágenes de verdad**: la tarjeta SVG es un marcador de posición y
  lo dice en la respuesta. No hay Stable Diffusion ni DALL·E conectados.
- **No ve el contenido de una imagen**: sin modelo de visión solo da metadatos
  (tamaño, dimensiones). No describe lo que sale en la foto.
- No hace scraping de nadie: la búsqueda va por Google News RSS y DuckDuckGo.
- No transcribe audio en streaming ni desde una URL: hace falta un archivo local.

## Notas de routing (no robar)

- «haz una foto» (webcam) y «captura de pantalla» son de system_pc.
- «busca X en google maps» es de places (lookahead `google(?!\s*maps)`).
- «investiga X y hazme un informe» es de research (aquí solo búsqueda rápida
  con ancla explícita «en internet / googlea»).
