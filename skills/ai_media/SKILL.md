# 🎙 Skill: Audio y búsqueda web (`ai_media`)

Hace dos cosas, las dos reales: **transcribe audios y vídeos** con Whisper local y
**responde preguntas con búsqueda web** leyendo las páginas y citando las fuentes.
Es la PRIMERA skill del router (orden alfabético), por eso todos sus patrones llevan
ancla de dominio.

## Órdenes de ejemplo

- «transcribe el audio D:\notas\reunion.mp3» · «pasa a texto la nota de voz D:\audios\idea.ogg»
- «transcribe el vídeo D:\clases\tema1.mp4»
- «busca en internet quién ganó el mundial de clubes»
- «googlea precio del cobre hoy» · «qué dice internet sobre el nuevo iPhone»
- «busca información sobre python» · «búscame información de la ley de teletrabajo» ·
  «consulta datos sobre el IBEX» — el sustantivo (información/info/datos/referencias) hace de
  ancla, así que no hace falta decir «en internet». Si la frase termina en «en la carpeta X»,
  «en mis notas» o «en el mapa», no es de aquí y se deja pasar.

## Transcripción (Whisper local)

- Acepta audio (mp3, wav, ogg, opus, m4a, aac, flac, wma) y vídeo (mp4, mkv, webm, mov, avi, m4v).
  Cualquier otro formato se rechaza diciendo cuáles sirven.
- La ruta puede llevar **espacios y comillas**; las coletillas («… y guárdala», «… por favor») se ignoran.
  Si no encuentra el archivo, te devuelve la ruta tal como la escribiste.
- Guarda el audio **ENTERO**: una nota con la transcripción y **marcas de tiempo** (`[mm:ss]`) y la base de
  datos en trozos (sin marcas). Nada se recorta. La respuesta dice dónde quedó y la duración del audio.
- **Análisis**: pide al modelo ideas principales, tareas y lluvia de ideas, **por bloques** para que un audio
  largo no se resuma solo por su principio (hasta unos 36.000 caracteres analizados; si hay más, lo dice y la
  transcripción completa se guarda igualmente).
- **Sin modelo de lenguaje**: guarda la transcripción sin análisis y lo avisa. El mensaje de error del modelo
  nunca se guarda como si fuera un análisis.
- **Retranscribir el mismo archivo SUSTITUYE** lo anterior en la memoria (lo viejo se retira a la papelera,
  no se borra). Dos audios con nombres parecidos no se pisan: cada nota lleva una huella de la ruta.
- Si el decodificador falla (archivo dañado o falta ffmpeg) lo dice; si no hay voz, también.
- Requiere `pip install faster-whisper`. Transcribe asumiendo **español**.

## Búsqueda web (sin API key)

- Busca (Google, DuckDuckGo y otras fuentes con respaldo; Google News para noticias), **lee las 3 primeras
  páginas** (en paralelo, máximo 8 s por página) y pasa su contenido al modelo, no solo los títulos.
- Las fuentes van **numeradas**: la respuesta cita `[1]`, `[2]`… y termina con una lista «dominio — título».
- Si las fuentes **no** contienen la respuesta, el modelo está obligado a decirlo en vez de suponer.
- **Sin modelo de lenguaje**: no puede redactar, así que te enseña los resultados que encontró (título y
  enlace) y el motivo, sin locutar ningún mensaje de error.
- Sin resultados o sin red: lo dice.

## Qué NO hace

- **No genera imágenes ni describe su contenido.** Antes había una tarjeta de relleno y un lector de
  metadatos; se eliminaron porque no hacían lo que prometían. Si en el futuro se conecta un motor de imagen
  o un modelo de visión real, será una skill nueva.
- No transcribe en streaming ni desde una URL: hace falta un archivo local.
- No hace scraping de nadie: la búsqueda va por buscadores públicos y lee páginas abiertas.
- La transcripción no detecta el idioma: un audio en otro idioma saldrá como español mal reconocido.

## Notas de routing (no robar)

- «haz una foto» (webcam) y «captura de pantalla» son de system_pc.
- «busca X en google maps» es de places (lookahead `google(?!\s*maps)`).
- «investiga X y hazme un informe» es de research (aquí solo búsqueda rápida con ancla explícita
  «en internet / googlea»).
