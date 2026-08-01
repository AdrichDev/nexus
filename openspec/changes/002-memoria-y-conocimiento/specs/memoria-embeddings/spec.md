# Especificación: memoria-embeddings

## Propósito

Hoy `backend/core/memory.py:273-282` descarta en silencio todo vector cuya
longitud no coincide con la columna `vector(768)`. Con el modelo activo eso
deja **741 filas de `memories` sin embedding** y todo `recall()` cayendo al
respaldo `ILIKE` (`memory.py:322-333`). Esta especificación cubre detectar la
dimensión real, migrar el esquema sin pérdida, reindexar de forma explícita y
proteger la privacidad del contenido vectorizado.

## Requisitos

### Requisito: Detección de la dimensión real del modelo activo

Al arrancar la verificación del esquema, el sistema DEBE pedir un embedding de
prueba al modelo `embed_model` activo y comparar su longitud con la de la
columna `vector(N)` existente en `_DDL` (`memory.py:191`).

#### Escenario: Dimensión distinta a la columna
- GIVEN la columna está en `vector(768)` y el modelo activo devuelve 1536
- WHEN se ejecuta la verificación de esquema
- THEN el sistema registra "reindexado pendiente" con la dimensión detectada
- AND se lo muestra al usuario, sin aplicar ningún cambio todavía

### Requisito: Migración de la columna sin descarte silencioso

El sistema NO DEBE descartar un vector por longitud sin registrar un aviso y
sumarlo a un contador visible. La migración de columna (soltar índice ivfflat
→ `ALTER COLUMN` a `vector(N)` real → recrear índice ivfflat) DEBE ejecutarse
solo tras confirmación explícita del usuario.

#### Escenario: Migración confirmada con datos existentes
- GIVEN hay filas con embeddings guardados en `vector(768)`
- WHEN el usuario confirma la migración a la dimensión detectada
- THEN el índice ivfflat se suelta, la columna cambia de tipo y el índice se
  recrea sobre la nueva dimensión, sin borrar ninguna fila de `memories`

#### Escenario: Vector de longitud inesperada tras la migración
- GIVEN la columna ya está en la dimensión correcta
- WHEN llega un vector de longitud distinta (fallo del proveedor, por ejemplo)
- THEN se rechaza esa fila con aviso explícito y se incrementa un contador de
  descartes, nunca un `pass` mudo

### Requisito: Reindexado explícito, por lotes y reanudable

El reindexado de las filas sin embedding DEBE ejecutarse por lotes, ser
reanudable tras interrupción, y DEBE lanzarse a mano — nunca automáticamente
en el arranque de nexus.

#### Escenario: Reindexado interrumpido a mitad
- GIVEN 741 filas pendientes y un lote de tamaño configurable ya procesado
  parcialmente
- WHEN el proceso se interrumpe y se relanza
- THEN retoma desde la primera fila sin embedding, sin re-procesar las ya
  reindexadas

#### Escenario: Reindexado completo
- GIVEN el reindexado termina sin errores
- WHEN se consulta `SELECT count(*) FROM memories WHERE embedding IS NULL AND kind <> 'conversation'`
- THEN el resultado es 0

### Requisito: Aislamiento de privacidad del proveedor de embeddings

`embed_provider` (`rag.py`, `auto|ollama|openai|gemini`) DEBE mantenerse en
local (Ollama) por defecto, independiente del cerebro de chat configurado.
Cambiar el cerebro de chat NO DEBE cambiar `embed_provider` como efecto
colateral. Usar un proveedor de nube para vectorizar DEBE exigir un aviso
explícito previo de que el contenido sale del equipo, y confirmación aparte
del usuario para esa operación concreta.

#### Escenario: Cambio de cerebro de chat no afecta a embeddings
- GIVEN `embed_provider` está en `ollama` y el cerebro de chat es `gemini-2.5-flash`
- WHEN el usuario cambia el cerebro de chat a otro modelo de nube
- THEN `embed_provider` sigue en `ollama`, sin preguntar ni cambiar nada

#### Escenario: Reindexado con proveedor de nube
- GIVEN el usuario quiere reindexar con `embed_provider: openai`
- WHEN lanza el reindexado
- THEN el sistema avisa explícitamente que el texto de los documentos sale del
  equipo hacia ese proveedor y exige confirmación antes de enviar la primera
  fila

## Delta de esquema (Postgres/pgvector)

- `memories.embedding`: pasa de `vector(768)` fijo a `vector(N)` donde `N` es
  la dimensión detectada del modelo activo, guardada junto al esquema.
- Índice ivfflat sobre `embedding`: se suelta antes del `ALTER COLUMN` y se
  recrea después, sobre la nueva dimensión.
- Autorreparación (`memory.py:191 _DDL`): al arrancar, si la dimensión
  detectada no coincide con la columna, NO se autorrepara en silencio — se
  marca "reindexado pendiente" y espera confirmación humana.
