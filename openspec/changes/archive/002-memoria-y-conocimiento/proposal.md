# Propuesta — Memoria y conocimiento: arreglar embeddings, deduplicar, purgar e ingerir

- **Cambio**: `knowledge-purge-and-ingest`
- **Fase**: propose
- **Fecha**: 2026-08-01
- **Almacén**: híbrido (este fichero + Engram `sdd/knowledge-purge-and-ingest/proposal`)
- **Depende de**: nada (paralelo a `content-os-honesty`)

## Intención

La memoria de nexus no es memoria: es un vertedero con un bug. Cuatro hechos medidos:

| Frente | Evidencia en código y en la base real |
| --- | --- |
| pgvector instalado y sin usar | `backend/core/memory.py:273-282` descarta todo vector cuya longitud no sea exactamente 768. `embed_provider: auto` (`config.py:121`) sigue al cerebro: con OpenAI, `rag.py:84` devuelve 1536 → descartado en silencio. **741 filas en `memories`, cero embeddings**; todo `recall()` cae al respaldo por `ILIKE` (`memory.py:322-333`) |
| Duplicados | 287 filas `knowledge` con **39 duplicados exactos** de un hecho y **38** de otro. El `dedup` de `rag.py:263-268` solo mira el almacén local; el camino de Postgres (`rag.py:255-262`) no deduplica nada |
| Ruido | 84 notas en `data/memory/`, ~95 % irrelevantes (BOE, CV, empadronamiento, tasas, matrícula, DAM). **No existe ningún endpoint de borrado ni de purga en todo el proyecto** |
| Documentos rechazados | `scheduler.py:34` filtra por extensión y rechaza `.docx/.pdf/.xlsx`, aunque `files_io.py:134 read_any()` ya sabe leer los tres. Nunca han entrado los documentos del usuario |

**Por qué ahora**: sin base de marca el sistema genera ideas sobre calcetines. Los seis
documentos de `D:\Adrian\22. Proyectos\NEXUS\Wabiks Content OS` (5 `.docx` + 1 `.xlsx`)
son esa base, y hoy no hay forma de meterlos ni sitio limpio donde ponerlos. Este cambio
es el cimiento del resto del SDD de Content OS.

## Resultado esperado

Preguntarle a nexus por Wabiks Content OS devuelve el documento maestro, no papeleo del
ayuntamiento; el conocimiento se busca por significado y no por `ILIKE`; un hecho está
una vez; y el usuario puede ver, exportar y quitar de la memoria lo que sobra sin miedo
a perder sus papeles.

## Alcance

### Entra

1. **Dimensión real del embedding**. Detectar la dimensión que devuelve de verdad el
   modelo activo, guardarla, y adaptar la columna `vector(N)` a ella. **Nunca descartar
   un vector en silencio**: si no encaja, se avisa y se cuenta.
2. **Reindexado explícito** de los 741 registros sin embedding, por lotes y reanudable.
3. **Deduplicación en el camino de Postgres**: identidad canónica del hecho (texto
   normalizado) + índice único, e inserción idempotente. Limpieza única de los duplicados
   ya existentes.
4. **Purga con protocolo de borrado** (ver reglas de negocio): clasificar, previsualizar,
   confirmar categoría por categoría, papelera reversible.
5. **Ingesta de `.docx`/`.pdf`/`.xlsx`** conectando `read_any()` al buzón, más una ingesta
   dirigida de una carpeta concreta (la de Wabiks Content OS) a `.md` con metadatos de
   **origen** y **dominio**.
6. **Troceado real**: nada de truncar. `rag.reindex()` (`rag.py:421`) corta a 1500
   caracteres y el buzón a 900; el tamaño y el solape pasan a `config/umbrales.json`.

### No entra

- Entidades del ciclo cerrado (`Observation`, `Hypothesis`, `Experiment`), motor de
  aprendizaje, planificador, rediseño visual y automatizaciones n8n.
- Cambiar el proveedor de embeddings o el cerebro configurado. `config/settings.json` y
  `config/secrets.json` no se tocan.
- Aislar `inspire` (scraping): va en `content-os-honesty`.
- Borrado automático de nada, jamás. Ni por caducidad, ni por «obvio».

## Capacidades

### Capacidades nuevas
- `memoria-embeddings`: dimensión detectada del modelo activo, reindexado explícito, cero descartes silenciosos.
- `memoria-deduplicacion`: identidad canónica de un hecho e inserción idempotente.
- `memoria-purga`: clasificación explicable, previsualización, confirmación por categoría y papelera reversible.
- `memoria-ingesta-documentos`: `.docx`/`.pdf`/`.xlsx`, troceado sin truncar, metadatos de origen y dominio.

### Capacidades modificadas
- Ninguna. `openspec/specs/` está vacío: este es el primer cambio que deja especificación.

## Reglas de negocio

**Borrado (innegociable, viene del incidente del tablero en `skills/tasks_board/skill.py`)**

| # | Regla |
| --- | --- |
| B1 | Solo lectura por defecto. Ninguna ruta del código borra sin una confirmación explícita del usuario para esa operación concreta. |
| B2 | Previsualización obligatoria y previa: qué se llevaría por delante, cuántos, y **por qué** (qué regla lo clasificó). Aplicar sin una previsualización vigente es un error, no un atajo. |
| B3 | Confirmación **categoría por categoría**. No existe «purgar todo». Nada viene marcado por defecto. |
| B4 | Lo no clasificado no se toca. Si una nota no encaja en ninguna categoría, se queda. |
| B5 | El papeleo personal (CV, vida laboral, empadronamiento, tasas, BOE, matrícula) es una categoría propia, marcada como personal, y su acción por defecto es **exportar fuera de la memoria**, no borrar. |
| B6 | Reversible: lo retirado va a papelera con su ruta original y su fecha. El borrado duro es una segunda acción explícita sobre la papelera. |
| B7 | Exportación antes de retirar: el usuario se queda con una copia legible fuera de `data/memory/`. |
| B8 | Las palabras y umbrales de clasificación viven en `config/umbrales.json` (bloque `purga`), nunca a fuego en el código. |

**Conocimiento e ingesta**

| # | Regla |
| --- | --- |
| C1 | Un hecho está una vez. Reingerir lo mismo dice «ya lo sabía» y no crea fila. |
| C2 | Todo lo ingerido lleva origen (ruta) y dominio, para poder filtrar y purgar por dominio sin volver a mirar fichero a fichero. |
| C3 | Un documento maestro no entra truncado. Si no cabe entero, se trocea; nunca se corta. |
| C4 | Dos versiones del mismo documento envenenan la base de marca: el fichero `ANTIGUO — …Manual de conversaciones…` se excluye por defecto y solo entra si el usuario lo pide, marcado como histórico. |
| C5 | Nada de scraping. Solo ficheros que el usuario señala en su propio disco. |

## Enfoque

1. **Dimensión**: al verificar el esquema, se pide un embedding de prueba al modelo activo
   y se compara su longitud con la de la columna. Si difiere, no se degrada en silencio:
   se registra como «reindexado pendiente» y se le enseña al usuario. La migración
   (soltar índice ivfflat → `ALTER` de la columna → recrear índice → re-embeber por lotes)
   se ejecuta con confirmación. **Hoy esa migración es gratis: hay cero vectores guardados,
   así que no se pierde nada.** Mañana no lo será, y por eso nace ya con confirmación.
2. **Dedup**: columna de huella del contenido normalizado + índice único + `ON CONFLICT
   DO NOTHING`. La limpieza de los duplicados existentes conserva la fila más antigua y
   pasa por el mismo protocolo de previsualización y confirmación (categoría
   «duplicados exactos»).
3. **Purga**: módulo nuevo de clasificación + endpoints `previsualizar` / `exportar` /
   `aplicar` / `papelera` / `restaurar`. `aplicar` exige el identificador de una
   previsualización vigente y la lista de categorías aceptadas.
4. **Ingesta**: el buzón deja de filtrar por lista de extensiones y pregunta a
   `files_io.puede_leer()`; el texto sale de `read_any()`. Ingesta dirigida de carpeta que
   escribe `.md` con cabecera de metadatos y trocea con los valores de `umbrales.json`.

## Áreas afectadas

| Área | Impacto | Qué cambia |
| --- | --- | --- |
| `backend/core/memory.py` | Modificado | Dimensión detectada, huella y dedup, reindexado, operaciones de retirada |
| `backend/core/rag.py` | Modificado | Troceado en vez de truncar, dedup también en el camino de Postgres |
| `backend/core/scheduler.py` | Modificado | El buzón acepta lo que `read_any()` sabe leer |
| `backend/core/purga.py` | Nuevo | Clasificación explicable, papelera, exportación |
| `backend/app.py` | Modificado | Endpoints de previsualización, exportación, aplicación, papelera y reindexado |
| `config/umbrales.json` | Modificado | Bloques `purga` (categorías y palabras) y `memoria` (troceado, solape) |
| `tests/` | Nuevo | `test_memoria_embeddings.py`, `test_purga.py`, `test_ingesta_documentos.py` + alta en `tests/run_all.py` |

## Criterios de aceptación

- [ ] `SELECT count(*) FROM memories WHERE embedding IS NULL AND kind <> 'conversation'` = 0 tras el reindexado.
- [ ] `recall()` devuelve filas con `score` (camino semántico), no solo el respaldo por palabras.
- [ ] Un vector de longitud distinta a la columna produce aviso y contador, nunca un descarte mudo.
- [ ] La consulta de duplicados exactos sobre `knowledge` devuelve vacío; insertar dos veces el mismo hecho deja una fila.
- [ ] Previsualizar no borra nada: el número de ficheros y de filas es idéntico antes y después.
- [ ] Aplicar sin previsualización vigente, o con categorías no confirmadas, falla con motivo claro.
- [ ] Lo retirado aparece en la papelera y se restaura a su ruta original.
- [ ] La categoría personal nunca se incluye sin marcarla a mano, y su acción por defecto es exportar.
- [ ] Los 6 documentos de Wabiks Content OS quedan ingeridos con origen y dominio; el documento maestro entra **completo** (suma de trozos = longitud del texto original, último trozo presente).
- [ ] Un `.docx`, un `.pdf` y un `.xlsx` dejados en el buzón se ingieren.
- [ ] Buscar «wabiks content os» devuelve material de marca, no papeleo.
- [ ] `.venv\Scripts\python.exe tests\run_all.py` sale TODO VERDE con las tres suites nuevas dadas de alta.

## Riesgos

| Riesgo | Probabilidad | Mitigación |
| --- | --- | --- |
| **Pérdida irreversible de papeles personales** del usuario | Media | B1–B7: previsualización, confirmación por categoría, exportación previa y papelera. Nunca borrado duro a la primera |
| **Migración de la columna `vector(768)`** con datos dentro | Baja hoy | Hoy hay cero vectores: la migración no destruye nada. El código nace con confirmación y con recreación del índice ivfflat para cuando sí los haya |
| Reindexar 741 filas cuesta llamadas al proveedor de embeddings | Media | Por lotes, reanudable, lanzado a mano y no en el arranque |
| Clasificar mal y proponer borrar algo útil | Media | Criterio explicable por nota, nada marcado por defecto, lo no clasificado se queda |
| Los seis documentos de marca contienen datos de negocio sensibles | Media | Se quedan en local, en Postgres local; nada sale del equipo salvo el embedding si el proveedor es de nube — decirlo claro antes de reindexar |
| Presupuesto de 800 líneas | Alta | Trocear en PRs encadenados: (A) embeddings + dedup, (B) purga, (C) ingesta. Lo decide `sdd-tasks` |

**Estimación de líneas cambiadas**: ~700–800 (memoria ~180, purga nueva ~180, tests ~150, app ~90, rag ~80, scheduler ~60, umbrales ~60). Al límite del presupuesto: se recomiendan tres PRs encadenados.

## Plan de reversión

- Código: los cuatro frentes son independientes; `git revert` por PR.
- Papelera: `restaurar` devuelve las notas a su ruta original.
- Columna vector: volver a `vector(768)` es el mismo camino de migración al revés; con embeddings dentro exige re-embeber, que es coste, no pérdida.
- Dedup: el índice único se suelta con un `DROP INDEX`; las filas conservadas son las originales más antiguas.

## Dependencias

- Contenedor `nexus_memoria_postgres` (Postgres 16 + pgvector, 127.0.0.1:5433, BD `nexus_core`) en marcha.
- Un proveedor de embeddings alcanzable (Ollama local, u OpenAI/Gemini con clave).
- `python-docx`, `pdfplumber`/`pypdf` y `openpyxl`, ya usados por `files_io.py`.

## Decisiones asumidas (pendientes de confirmación del usuario)

1. La dimensión se adapta al modelo activo (se cambia la columna), en vez de fijar el proveedor de embeddings a uno de 768.
2. La retirada por defecto es a papelera reversible dentro de `data/memory/`, no borrado duro.
3. El papeleo personal se exporta fuera de la memoria en vez de borrarse.
4. El fichero `ANTIGUO — …` no se ingiere salvo petición expresa.
5. La purga actúa sobre las notas de `data/memory/` **y** sobre las filas de Postgres que salieron de ellas.

---

## Decisiones resueltas con el usuario (01/08/2026)

Estas cinco suposiciones se elevaron y ya están decididas. Mandan sobre lo escrito
arriba.

### 1. Dimensión del embedding — ADAPTAR LA COLUMNA (confirmado)

Se detecta la dimensión real del modelo activo y se migra la columna. Confirmado
por el usuario frente a la alternativa de fijar el proveedor a uno de 768.

**Consecuencia de privacidad, y su mitigación obligatoria.** El cerebro activo
hoy es `gemini-2.5-flash` (nube). Si el proveedor de embeddings siguiera al
cerebro, re-vectorizar las 741 filas mandaría a Google el texto de los documentos
de marca y de las notas personales. `backend/core/rag.py` ya admite
`embed_provider` (`auto | ollama | openai | gemini`) **independiente del cerebro
de chat**.

> **Regla**: la columna se adapta al modelo, pero `embed_provider` se deja en
> local (Ollama) por defecto. Vectorizar con un proveedor de nube exige avisar
> antes de forma explícita de que ese contenido sale del equipo, y confirmación
> del usuario. Nunca como efecto colateral de cambiar el cerebro de chat.

### 2. Destino de lo purgado — PAPELERA Y DESPUÉS DECIDIR

Dos tiempos, no uno:

1. Todo lo retirado va primero a la papelera reversible dentro de `data/memory/`.
2. Cuando el usuario ha revisado que la clasificación es correcta, decide en un
   segundo paso qué exportar fuera del proyecto y qué borrar del todo.

nexus **nunca** vacía la papelera por su cuenta ni pregunta por iniciativa
propia; el segundo paso lo inicia el usuario.

### 3. Papeleo personal — FUERA DE LA MEMORIA, PERO CONSERVADO

CV, vida laboral, empadronamiento, tasas, matrícula y BOE salen de la memoria de
nexus: dejan de contaminar las búsquedas y de gastar contexto. **Ningún fichero se
destruye**: siguen el flujo de dos tiempos del punto 2. La acción por defecto para
esta categoría nunca puede ser el borrado duro.

### 4. Documento `ANTIGUO — …` — SÍ SE INGIERE, MARCADO COMO HISTÓRICO

Corrige la suposición 4 de arriba. Se ingiere etiquetado como histórico y con
menos peso en las búsquedas que el manual definitivo. Motivo: puede contener
contexto que el documento definitivo dé por sabido, y descartarlo pierde
información que no cuesta nada conservar bien etiquetada.

### 5. El `.xlsx` — POR HOJAS Y COLUMNAS, NO APLANADO

«Wabiks Content Intelligence» se ingiere respetando su estructura de hojas y
columnas. Una hoja de cálculo pasada a texto plano y troceada cada 900 caracteres
queda inservible para búsqueda semántica: parte filas por la mitad y pierde a qué
columna pertenece cada valor.
