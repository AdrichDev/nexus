# Especificación: memoria-deduplicacion

## Propósito

287 filas `knowledge` contienen **39 duplicados exactos** de un hecho y **38**
de otro. El `dedup` de `rag.py:263-268` solo mira el almacén local; el camino
de Postgres (`rag.py:255-262`) inserta sin comprobar nada. Esta especificación
cubre la identidad canónica de un hecho, la inserción idempotente y la
limpieza única de lo ya duplicado.

## Requisitos

### Requisito: Identidad canónica del hecho

El sistema DEBE calcular una huella (hash) del texto normalizado de cada hecho
antes de insertarlo en `knowledge`, y DEBE guardar esa huella en una columna
dedicada.

#### Escenario: Normalización antes de la huella
- GIVEN dos hechos con el mismo contenido pero distinto espaciado o mayúsculas
- WHEN se calcula la huella de cada uno
- THEN ambas huellas son idénticas

### Requisito: Inserción idempotente

Un índice único sobre la huella DEBE existir en `knowledge`. La inserción DEBE
usar `ON CONFLICT DO NOTHING` (o equivalente) sobre ese índice, de forma que
reingerir el mismo hecho no cree una fila nueva.

#### Escenario: Reinserción del mismo hecho
- GIVEN un hecho ya existe en `knowledge` con su huella
- WHEN se intenta insertar el mismo hecho de nuevo
- THEN no se crea ninguna fila nueva y el sistema informa "ya lo sabía"

#### Escenario: Consulta de duplicados exactos vacía
- GIVEN la deduplicación está activa
- WHEN se consulta `knowledge` agrupando por huella con `HAVING count(*) > 1`
- THEN el resultado está vacío

### Requisito: Limpieza única de duplicados existentes

La limpieza de los duplicados ya presentes en `knowledge` DEBE conservar la
fila más antigua de cada grupo y DEBE pasar por el protocolo de purga (ver
`memoria-purga`) bajo la categoría "duplicados exactos" — previsualización y
confirmación antes de retirar nada.

#### Escenario: Previsualización de duplicados antes de limpiar
- GIVEN existen grupos de filas con la misma huella
- WHEN se previsualiza la categoría "duplicados exactos"
- THEN se listan los grupos, cuántas filas sobran por grupo y cuál se
  conservaría, sin borrar nada todavía

#### Escenario: Limpieza conserva la fila más antigua
- GIVEN un grupo de 39 filas duplicadas del mismo hecho
- WHEN el usuario confirma la categoría "duplicados exactos"
- THEN se retira a papelera todo el grupo salvo la fila con la fecha de
  creación más antigua

## Delta de esquema (Postgres/pgvector)

- `knowledge.huella` (o `content_hash`): columna nueva, texto normalizado
  hasheado, no nula para filas nuevas.
- Índice único sobre `knowledge.huella`.
- Autorreparación (`memory.py:191 _DDL`): si la columna o el índice no
  existen al arrancar, se crean; si ya existen filas sin huella (histórico),
  se calcula en un paso de mantenimiento explícito, no en cada arranque.
