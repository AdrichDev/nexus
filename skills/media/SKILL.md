# 🎵 Media / Música (media)

nexus **reproduce** y **controla** música por voz o texto. Abrir las apps
(Spotify, iTunes, YouTube…) ya lo hace el minion «Sistema/PC» con tu índice de
aplicaciones; esta skill pone canciones y maneja la reproducción. Si pides
música sin decir dónde, te pregunta «¿Spotify o YouTube?» y tu siguiente
respuesta corta («spotify», «en youtube», «mejor en itunes») la resuelve.

## Reproducir con nombre

- «pon Bohemian Rhapsody» · «reproduce Shape of You»
- «pon La Raja de tu Falda **en spotify**» · «reproduce Imagine **en youtube**»
- «pon Columbia **en itunes**» (o «en apple music»)
- «quiero oír la canción Thunderstruck» · «escucha la canción Rosas en youtube»

## Reproducir AL AZAR (elige la IA)

- «pon algo» · «pon música» · «sorpréndeme» · «pon algo **al azar**»
- «pon algo **de rock**» · «pon una canción **de Quevedo**» · «pon música de los 80»
- «pon cualquier cosa en spotify» · «pon lo que quieras» · «ponme una musiquita»
- «quiero escuchar algo de jazz» · «me apetece algo de música tranquila»

El LLM elige UNA canción real distinta cada vez (guarda las últimas en
`data/music_history.json` para no repetirse). Sin LLM, tira de un pool interno.

## Servicios

- **YouTube (por defecto)** — busca y abre el **primer resultado con autoplay real**,
  sin API key (lee el `videoId` del HTML de resultados). Suena al momento.
- **Spotify** — **AUTOPLAY REAL** vía Web API: pon el Client ID/Secret en ⚙
  (developer.spotify.com, Redirect URI `http://127.0.0.1:8177/api/spotify/callback`,
  cuenta Premium). Autorizas una vez en el navegador y a partir de ahí nexus
  busca la canción y le da al play él solo (incluso abre Spotify si está cerrado).
  Sin API configurada: abre la app en la búsqueda (plan B).
- **Apple Music / iTunes** — abre la búsqueda en music.apple.com (tienda ES).

El servicio por defecto se cambia en config (`music_service`: `youtube` | `spotify`).

## Controlar (sobre cualquier reproductor activo, vía teclas multimedia de Windows)

- «pausa» / «reanuda» / «sigue con la música» / «dale pausa» → play/pausa
- «siguiente canción» / «salta esta» / «sáltate este» / «pon la siguiente» → siguiente
- «canción anterior» / «vuelve a la anterior» / «repíteme la canción» → anterior
- «para la música» / «quita esa canción» / «fuera música» → stop

Funciona con Spotify, YouTube en el navegador, reproductores locales, etc., porque
usa las teclas de medios del sistema, no una API concreta.

## Notas

- El control multimedia usa teclas de Windows; en otros sistemas nexus lo avisa
  y ofrece lanzar la música por YouTube directamente.
- No colisiona con «pon el volumen al 50» (eso sigue siendo del minion Sistema).
- «pon otra canción» = siguiente (control), no reproducir otra cosa.
- Tolera transcripciones de Whisper: «espotifai», «yutub», «aitunes»…
