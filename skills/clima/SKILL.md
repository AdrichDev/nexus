# Skill: Clima / Tiempo

Meteorología real de cualquier ciudad usando **wttr.in** (gratis, sin API key).

## Qué entiende
- «¿Qué tiempo hace en Madrid?», «el tiempo», «clima» (a secas)
- «¿Qué temperatura hace?» (usa tu ubicación por IP si no dices ciudad)
- «Temperatura de Barcelona», «el tiempo en Sevilla mañana»
- «¿Va a llover?», «¿nieva en Andorra?», «¿necesito paraguas?»
- «Previsión del tiempo», «pronóstico», «meteorología»

## Días
Por defecto contesta el tiempo de AHORA (más máx/mín de hoy). Si dices «mañana»
o «pasado mañana» usa la previsión de ese día, no la de hoy. wttr.in da 3 días;
más allá, lo dice en vez de inventarlo.

## Qué NO hace
- No responde la temperatura del **hardware** (CPU/GPU/gráfica/procesador): eso
  lo lleva la skill `system_pc`. Los patrones llevan una *lookahead* negativa
  para no pisarse con «temperatura de la CPU».
- No es duración: «cuánto tiempo de espera», «contratiempo», «pasatiempo» y «a
  tiempo de» no son meteorología y no los coge.
- No hay previsión por horas ni a más de 3 días, ni avisos ni alertas.

## Necesita configurado
Nada. wttr.in es gratis y sin API key; solo hace falta conexión a internet.

## Orden en el router
La carpeta se llama `clima` a propósito: alfabéticamente va **antes** que
`system_pc`, así el clima se atiende primero. Aun así, `system_pc` ya no captura
«temperatura» a secas (exige un componente detrás), de modo que ambos conviven.

## Fuente
`https://wttr.in/<ciudad>?format=j1&lang=es` — devuelve JSON con condición
actual, sensación térmica, humedad, viento y máx/mín del día. Sin dependencias
extra (usa httpx, que nexus ya trae).
