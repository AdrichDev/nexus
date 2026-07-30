# ⚖ Devil's Advocate (abogado del diablo)

nexus no es un asistente que te dé la razón: es un compañero honesto que
cuestiona, detecta fallos y corrige. Esta skill lo hace explícito: le pasas una
idea o un plan y te devuelve un análisis en 4 partes — **Steelman** (la versión
más fuerte de tu idea), **Puntos débiles**, **Riesgos ocultos** y **Veredicto**
sincero (adelante / adelante con condiciones / repensar).

## Órdenes de ejemplo

- «abogado del diablo: quiero invertir todos mis ahorros en cripto»
- «critica mi plan de lanzar la web en una semana»
- «cuestiona este razonamiento: si bajo los precios venderé más»
- «búscale pegas a mi propuesta de precios»
- «pon a prueba mi idea de abrir un segundo local»
- «destroza esta idea: vender cursos sin tener audiencia»
- «activa el modo abogado del diablo» / «desactiva el modo abogado del diablo»
- «sé más crítico conmigo» / «deja de ser tan crítico»

## Modo permanente

«activa el modo abogado del diablo» guarda el flag `devil_mode` en settings:
mientras esté activo, TODAS las respuestas conversacionales llevan un
contrapunto crítico al final. Se quita con «desactiva el modo abogado del
diablo» (o «modo crítico off»).

## Notas técnicas

- La crítica la genera el LLM del núcleo IA (⚙): sin proveedor y clave
  configurados no hay análisis — nexus te dirá qué revisar.
- La idea se recorta a 3000 caracteres antes de enviarla al modelo.
- Además, el prompt del sistema de nexus le ordena corregir errores del
  operador con respeto y argumentos aunque no se lo pidan — no complacencia.
- Las specs internas del project manager (skill coach) pasan SIEMPRE por
  `critique()` antes de darse por buenas.
