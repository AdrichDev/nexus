# 📸 Content OS (content_os)

Cerebro de contenido de Instagram: métricas reales de **tu** cuenta por la Graph
API, ranking de tus reels, patrones sobre material propio y guiones
gancho + desarrollo + CTA.

## Qué hace y con qué frases

- **Conectar** — «conecta mi instagram», «conéctame el instagram», «vincúlame mi
  instagram», «configúrame mi instagram». Valida token + cuenta y te dice
  seguidores y publicaciones.

- **Analítica** — «analítica de instagram», «cómo va mi instagram», «qué tal va
  mi instagram», «mis métricas de ig», «alcance de mi ig». Seguidores, alcance,
  impresiones y visitas de perfil de los últimos 28 días.

- **Mejores reels** — «mis mejores reels», «reels ganadores», «qué reels me
  funcionan mejor», «top de reels», «ranking de reels». Ordena tus últimas 25
  publicaciones por likes + comentarios ponderados.

- **Patrones** — «analiza los patrones», «analízame los patrones», «qué ganchos
  funcionan», «qué estructuras se repiten». Cruza las transcripciones que ya hay
  en `data/inspiration/` y dice de dónde salen.

- **Guiones** — «genera un guion sobre morning routines», «escríbeme un guion
  sobre café», «créame un guion de reel sobre viajes», «hazme un guion para
  captar clientes». Se guarda en `data/scripts/`.

- **Ideas** — «dame ideas de contenido», «ideas para reels», «qué subo a
  instagram».

## Necesita configurado

En ⚙: **`ig_access_token`** (token de la Graph API con `instagram_basic` +
`instagram_manage_insights`) e **`ig_user_id`**. Se sacan en
developers.facebook.com con una cuenta Business/Creator vinculada a una página
de Facebook.

Sin esas dos cosas, la analítica y el ranking **dicen exactamente qué falta y
cómo conseguirlo**. No enseñan cifras de ejemplo: no hay números inventados en
ningún camino de esta skill.

## Qué NO hace

- **No descarga ni transcribe reels de nadie.** La vía de yt-dlp + whisper está
  retirada: era scraping de contenido de terceros. «aprende de este reel <url>»
  sigue casando a propósito, pero contesta que esa vía no existe y ofrece la
  legítima (`business_discovery`) o que le pegues tú el texto del reel.
- No lee métricas privadas de cuentas ajenas: la API solo expone las tuyas.
- No publica, ni programa, ni borra nada en Instagram.
- Las transcripciones antiguas de `data/inspiration/` no se borran (borrar exige
  confirmación) y ya no crecen; todo análisis que las use lo avisa.

## Fronteras con la skill `instagram`

`content_os` va antes por orden alfabético, así que se queda solo lo que lleva
«mi/mis»: «cómo va **mi** instagram» es esta skill (tu cuenta); «cómo va **el**
instagram» es `instagram.ig_estado` (la integración). El análisis de cuentas
ajenas y de competencia es siempre de `instagram`.
