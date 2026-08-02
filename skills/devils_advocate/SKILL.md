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

## Modo permanente: ya está puesto, y no se apaga

`DEVIL_INSTRUCTION` (backend/core/llm.py) se concatena al prompt de sistema de
TODA respuesta: el modelo cuestiona sus propias suposiciones y corrige al
operador cuando parte de un dato equivocado. Es lo que ⚙ Configuración anuncia
como «SIEMPRE ACTIVO, no apagable».

Por eso «activa/desactiva el modo abogado del diablo» no conmuta nada: contestan
explicando que ya va puesto y que lo opcional es el informe en 4 partes, que sale
solo cuando lo pides.

## Qué NO hace

- No añade un contrapunto crítico visible al final de cada respuesta: la
  instrucción actúa en el razonamiento del modelo, no como texto pegado.
- No se puede desactivar por voz ni desde ⚙.
- No analiza nada por su cuenta: el informe en 4 partes sale solo si lo pides.

## Necesita configurado

Un proveedor y modelo en ⚙ Núcleo IA. Sin eso no hay análisis y nexus te dice
qué revisar (no se inventa la crítica).

## Notas técnicas

- La idea se recorta a 3000 caracteres antes de enviarla al modelo.
- Las specs internas del project manager (skill coach) pasan SIEMPRE por
  `critique()` antes de darse por buenas.
