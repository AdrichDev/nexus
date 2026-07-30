# 📸 Skill: Content OS (Instagram Intelligence)

El "cerebro de contenido" de nexus, al estilo del panel Content OS: conecta tu
Instagram por la Graph API para métricas reales, aprende de reels públicos de
otros creadores (los descarga y transcribe), detecta los patrones que se
repiten en los ganadores y genera guiones con esos patrones.

## Órdenes de ejemplo (frases que los patrones cazan de verdad)

- "conecta mi instagram" / "vincula mi instagram" → valida token + cuenta y
  te dice seguidores y publicaciones; si falta algo, te guía paso a paso.
- "analítica de instagram" / "cómo va mi instagram" / "métricas de mi ig"
  → seguidores, alcance, impresiones y visitas de perfil (28 días).
- "mis mejores reels" / "qué reels me funcionan mejor" → ranking por
  interacción (likes + comentarios ponderados).
- "inspiración de @creador https://instagram.com/reel/..." /
  "aprende de este reel <url>" / "analiza el reel <url>" → descarga el reel
  público, lo transcribe y lo guarda como conocimiento.
- "analiza los patrones" / "qué ganchos funcionan" → cruza todo lo aprendido:
  ganchos, estructura, temas y CTA que se repiten.
- "genera un guion sobre morning routines" / "hazme un guion de reel para
  captar clientes" → gancho (3 seg) + desarrollo + CTA + texto en pantalla,
  guardado en data/scripts/.
- "dame ideas de contenido" / "qué subo a instagram" → 5 ideas con gancho.

## Notas técnicas

- Cuenta propia: requiere en ⚙ «ig_access_token» (token Graph API con
  instagram_basic + instagram_manage_insights) e «ig_user_id». Se obtienen en
  developers.facebook.com con una cuenta Business/Creator vinculada a una
  página de Facebook. Sin token, la analítica muestra un ejemplo coherente y
  lo dice claramente.
- Inspiración: necesita yt-dlp + faster-whisper instalados
  (`pip install yt-dlp faster-whisper`) y que el reel sea PÚBLICO. Las
  transcripciones se guardan en data/inspiration/*.json y en el grafo.
- Guiones e ideas usan el LLM con los patrones aprendidos como contexto.
- Nota honesta: Instagram solo expone por API los datos de TU cuenta. De
  terceros se trabaja con sus vídeos públicos (transcripción), no con sus
  métricas privadas; para eso haría falta un proveedor externo
  (Apify/Brightdata) vía la skill n8n.
