# Especificación: memoria-purga

## Propósito

84 notas en `data/memory/`, ~95 % irrelevantes (BOE, CV, empadronamiento,
tasas, matrícula), y **no existe ningún endpoint de borrado ni de purga en
todo el proyecto**. Esta especificación nace del incidente real documentado en
`skills/tasks_board/skill.py`: nada se retira sin previsualización y
confirmación explícita, categoría por categoría, y nunca por iniciativa propia
del sistema.

## Requisitos

### Requisito: Clasificación explicable por categorías

El sistema DEBE clasificar cada nota de `data/memory/` y cada fila de
conocimiento en una categoría, usando palabras y umbrales leídos de
`config/umbrales.json` (bloque `purga`) — nunca a fuego en el código. Cada
resultado DEBE incluir qué regla concreta la clasificó.

#### Escenario: Nota sin categoría reconocida
- GIVEN una nota no coincide con ninguna regla de `umbrales.json`
- WHEN se clasifica el conjunto de notas
- THEN la nota queda fuera de toda categoría y no aparece en ninguna
  previsualización de retirada

### Requisito: Previsualización obligatoria y previa

Toda operación de retirada DEBE generar primero una previsualización con
identificador propio, listando qué se llevaría, cuántos elementos y por qué
(regla que los clasificó). Aplicar sin una previsualización vigente DEBE
fallar con un motivo claro, nunca ejecutarse como atajo.

#### Escenario: Previsualizar no cambia nada
- GIVEN 84 notas sin clasificar aún
- WHEN se pide la previsualización de todas las categorías
- THEN el número de ficheros en `data/memory/` y de filas en `knowledge`/
  `memories` es idéntico antes y después

#### Escenario: Aplicar sin previsualización vigente
- GIVEN no existe una previsualización activa (nunca se pidió, o caducó)
- WHEN se llama al endpoint de aplicar sobre una categoría
- THEN la operación falla y devuelve el motivo, sin retirar nada

### Requisito: Confirmación categoría por categoría

No DEBE existir una operación de "purgar todo". Cada categoría DEBE
confirmarse por separado, y ninguna categoría DEBE venir marcada por defecto
en la respuesta de previsualización.

#### Escenario: Confirmar solo una categoría
- GIVEN la previsualización devuelve tres categorías con elementos
- WHEN el usuario confirma solo una de ellas
- THEN únicamente los elementos de esa categoría se retiran a papelera; las
  otras dos quedan intactas

### Requisito: Papelera reversible en dos tiempos

Lo retirado DEBE ir primero a una papelera reversible dentro de
`data/memory/`, conservando ruta original y fecha de retirada. El sistema NO
DEBE vaciar la papelera por su cuenta ni preguntar por iniciativa propia; la
exportación fuera del proyecto o el borrado duro son una segunda acción
explícita que solo el usuario inicia.

#### Escenario: Restaurar desde la papelera
- GIVEN una nota fue retirada a la papelera con su ruta original
- WHEN el usuario pide restaurarla
- THEN vuelve exactamente a esa ruta original

#### Escenario: El sistema nunca vacía la papelera solo
- GIVEN hay elementos en la papelera desde hace tiempo
- WHEN transcurre cualquier cantidad de tiempo sin acción del usuario
- THEN el sistema no borra ni exporta nada de la papelera por su cuenta

### Requisito: Categoría personal — exportar, nunca borrado duro

CV, vida laboral, empadronamiento, tasas, matrícula y BOE forman una categoría
propia marcada como personal. Su acción por defecto DEBE ser exportar una
copia legible fuera de `data/memory/` antes de retirar; el borrado duro NO
DEBE ser jamás la acción por defecto de esta categoría.

#### Escenario: Retirar papeleo personal
- GIVEN la categoría "personal" se confirma para retirada
- WHEN se aplica la operación
- THEN cada nota se exporta primero a una copia legible fuera de la memoria y
  después se mueve a papelera; ningún fichero se destruye

### Requisito: Alcance dual — notas y filas de Postgres

La purga DEBE actuar tanto sobre las notas `.md` de `data/memory/` como sobre
las filas de `knowledge`/`memories` en Postgres que se originaron de ellas,
como una sola operación por categoría.

#### Escenario: Retirar una nota retira también su conocimiento derivado
- GIVEN una nota de `data/memory/` generó filas en `knowledge`
- WHEN se confirma la retirada de la categoría de esa nota
- THEN la nota va a papelera y las filas de `knowledge` derivadas de ella se
  retiran en la misma operación
