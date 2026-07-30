# Skill: Clima / Tiempo

Meteorología real de cualquier ciudad usando **wttr.in** (gratis, sin API key).

## Qué entiende
- «¿Qué tiempo hace en Madrid?»
- «¿Qué temperatura hace?» (usa tu ubicación por IP si no dices ciudad)
- «Temperatura de Barcelona», «el tiempo en Sevilla mañana»
- «¿Va a llover?», «¿nieva en Andorra?»
- «Previsión del tiempo»

## Qué NO toca
No responde a la temperatura del **hardware** (CPU/GPU/gráfica/procesador): eso
lo lleva la skill `system_pc`. Los patrones llevan una *lookahead* negativa para
no pisarse con «temperatura de la CPU».

## Orden en el router
La carpeta se llama `clima` a propósito: alfabéticamente va **antes** que
`system_pc`, así el clima se atiende primero. Aun así, `system_pc` ya no captura
«temperatura» a secas (exige un componente detrás), de modo que ambos conviven.

## Fuente
`https://wttr.in/<ciudad>?format=j1&lang=es` — devuelve JSON con condición
actual, sensación térmica, humedad, viento y máx/mín del día. Sin dependencias
extra (usa httpx, que nexus ya trae).
