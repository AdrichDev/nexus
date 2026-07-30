# Skill: Chrome (pestañas abiertas, contexto en vivo)

nexus se conecta a Google Chrome por el **protocolo DevTools (CDP)** — la misma
técnica que usa `chrome-devtools-mcp` de Google, pero nativa, sin Node.

## El «modo nexus» de Chrome (imprescindible)

Desde Chrome 136 (2025) el perfil por defecto **no admite** depuración remota,
así que nexus usa una ventana de Chrome con **perfil propio** (`data/chrome_nexus`)
y el puerto 9222 abierto:

- «**conecta con chrome**» → nexus arranca esa ventana y queda vinculado.
- La primera vez, inicia sesión en Google en esa ventana y activa la
  sincronización: tendrás tus marcadores, contraseñas e historial de siempre.
- Lo que navegues **en esa ventana** es lo que nexus puede ver y leer.

## Órdenes

- «qué pestañas tengo abiertas» → lista numerada
- «resume la pestaña 2» / «lee la pestaña de youtube» / «qué estoy viendo en
  chrome» → extrae el TEXTO REAL de la página y lo analiza el LLM (resumir,
  explicar, traducir, responder preguntas sobre ella…)
- «cambia a la pestaña de gmail» → la trae al frente
- «abre una pestaña con el tiempo en madrid» / «abre marca.com en chrome»
- «cierra la pestaña de twitter»

## Notas técnicas

- Puerto CDP: `127.0.0.1:9222` (solo local; nada sale de tu PC).
- Lectura de contenido: `Runtime.evaluate` → `document.body.innerText`
  (máx ~12k caracteres pasados al LLM). Requiere la librería `websockets`
  (run.bat la instala solo).
- Alternativa avanzada: el conector MCP `chrome-devtools-mcp` puede engancharse
  por la skill `mcp_hands` si algún día hace falta (requiere Node/npx); para
  leer pestañas, esta skill nativa hace lo mismo con menos piezas.
