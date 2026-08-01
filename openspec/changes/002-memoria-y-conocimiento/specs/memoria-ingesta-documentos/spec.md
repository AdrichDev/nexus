# Especificación: memoria-ingesta-documentos

## Propósito

`backend/core/scheduler.py:34 _ingest_inbox()` filtra por extensión y rechaza
`.docx/.pdf/.xlsx`, aunque `backend/core/files_io.py:134 read_any()` ya sabe
leerlos. Están desconectados, y por eso los seis documentos de
`D:\Adrian\22. Proyectos\NEXUS\Wabiks Content OS` nunca han entrado en la
memoria. Esta especificación conecta la lectura, evita truncar, y añade
metadatos de origen y dominio para poder filtrar y purgar después.

## Requisitos

### Requisito: El buzón acepta lo que `read_any()` sabe leer

`_ingest_inbox()` NO DEBE filtrar por una lista fija de extensiones. DEBE
preguntar a una función tipo `files_io.puede_leer()` si el fichero es legible,
y en tal caso extraer su texto con `read_any()`.

#### Escenario: `.docx`, `.pdf` y `.xlsx` en el buzón
- GIVEN un `.docx`, un `.pdf` y un `.xlsx` se dejan en el buzón de ingesta
- WHEN corre el ciclo de ingesta
- THEN los tres se leen con `read_any()` y su contenido entra en la memoria

### Requisito: Metadatos de origen y dominio

Todo lo ingerido DEBE guardar la ruta de origen y un dominio (etiqueta de
carpeta o tema), de forma que se pueda filtrar y purgar por dominio sin
inspeccionar fichero a fichero.

#### Escenario: Filtrar por dominio
- GIVEN documentos ingeridos con dominio `wabiks-content-os`
- WHEN se consulta el conocimiento filtrando por ese dominio
- THEN solo aparecen filas que vinieron de esos ficheros

### Requisito: Troceado sin truncar

El sistema NO DEBE truncar el texto de un documento. `rag.reindex()` (hoy
corta a 1500 caracteres) y el buzón (hoy a 900) DEBEN trocear en fragmentos
con tamaño y solape leídos de `config/umbrales.json` (bloque `memoria`),
cubriendo el texto completo.

#### Escenario: Documento maestro completo
- GIVEN "Wabiks Content OS — Documento maestro.docx" supera el límite anterior
  de 1500 caracteres
- WHEN se ingiere y trocea
- THEN la suma de los trozos reconstruye la longitud del texto original y el
  último trozo está presente

### Requisito: Ingesta dirigida de una carpeta

DEBE existir una operación que ingiera todos los ficheros legibles de una
carpeta señalada por el usuario, escribiendo una nota `.md` por documento con
cabecera de metadatos (origen, dominio, fecha) antes de trocear.

#### Escenario: Ingesta de la carpeta Wabiks Content OS
- GIVEN la carpeta contiene 5 `.docx` y 1 `.xlsx`
- WHEN el usuario dirige la ingesta a esa carpeta
- THEN los 6 documentos quedan ingeridos con origen y dominio, y el documento
  maestro entra completo

### Requisito: `.xlsx` por hojas y columnas

Una hoja de cálculo NO DEBE aplanarse a texto plano trocedo por caracteres.
El sistema DEBE recorrer hoja por hoja y fila por fila, conservando a qué
columna pertenece cada valor.

#### Escenario: "Wabiks Content Intelligence" ingerido por estructura
- GIVEN el `.xlsx` tiene varias hojas con columnas con nombre
- WHEN se ingiere
- THEN el conocimiento resultante conserva la asociación valor-columna-hoja,
  sin filas partidas a la mitad

### Requisito: Documento histórico marcado y con menos peso

El fichero "ANTIGUO — …Manual de conversaciones…" DEBE ingerirse por defecto,
etiquetado como histórico, y DEBE pesar menos que el manual definitivo en las
búsquedas cuando ambos compiten por el mismo tema.

#### Escenario: Búsqueda desempata a favor del manual definitivo
- GIVEN el manual definitivo y el histórico contienen contenido relacionado
- WHEN se busca ese tema
- THEN el manual definitivo aparece con mayor relevancia que el histórico
  etiquetado

### Requisito: Un hecho entra una vez desde la ingesta

La ingesta de documentos DEBE apoyarse en la inserción idempotente de
`memoria-deduplicacion`: reingerir el mismo fichero o el mismo fragmento NO
DEBE crear filas nuevas.

#### Escenario: Reingesta del mismo `.docx`
- GIVEN un documento ya fue ingerido
- WHEN se deja de nuevo en el buzón sin cambios
- THEN no se crean filas nuevas de conocimiento para ese contenido
