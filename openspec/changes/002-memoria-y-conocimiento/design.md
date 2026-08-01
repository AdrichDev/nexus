# Diseño técnico — 002 Memoria y conocimiento

- **Cambio**: `002-memoria-y-conocimiento` (antes `knowledge-purge-and-ingest`)
- **Fase**: design · **Almacén**: híbrido (este fichero + Engram `sdd/002-memoria-y-conocimiento/design`)
- **Manda**: la sección «Decisiones resueltas con el usuario (01/08/2026)» de `proposal.md`

## Enfoque técnico

Cuatro frentes sobre tres módulos existentes (`memory.py`, `rag.py`, `scheduler.py`) y
uno nuevo (`purga.py`). No se inventa arquitectura: se reutilizan las piezas que el
proyecto ya tiene para lo destructivo — `backend/core/confirm.py` (confirmación con TTL
por canal), `backend/core/audit.py` (traza obligatoria) y el patrón de papelera de
`backend/core/board.py` (borrado lógico con lote, motivo y restauración). El principio
que atraviesa todo el diseño es el mismo de siempre en nexus: **se mide, no se supone;
y nada destructivo pasa a la primera**.

## Decisiones de arquitectura

### 1. Migración de la columna `vector(768)` — renombrar, no `ALTER` in situ

| Opción | Coste | Reversibilidad | Decisión |
| --- | --- | --- | --- |
| `ALTER COLUMN ... TYPE vector(N)` | barato hoy (0 vectores) | mañana, con vectores, exige `USING` que pgvector rechaza entre dimensiones distintas | rechazada |
| Renombrar `embedding` → `embedding_dim{vieja}` + añadir `embedding vector(N)` | una columna extra temporal | revertir = `DROP` de la nueva + renombrar la vieja | **elegida** |
| Recrear la tabla | copia completa | alta | rechazada: 741 filas no justifican el riesgo |

**Elección**: la migración nunca destruye la columna anterior. Secuencia, toda dentro de
`memory.migrar_vector(dim)` y registrada en `audit.log`:

1. `DROP INDEX IF EXISTS memories_embedding_idx`
2. `ALTER TABLE memories RENAME COLUMN embedding TO embedding_dim768`
3. `ALTER TABLE memories ADD COLUMN embedding vector(N)`
4. Índice ivfflat **solo si procede** (ver abajo)
5. `UPDATE`/reindexado por lotes (acción aparte, con su propio presupuesto)

Soltar la columna de respaldo es una **segunda acción explícita**
(`POST /api/memoria/vector/limpiar-respaldo`), igual que vaciar la papelera. Mismo dos
tiempos, misma doctrina.

**Hallazgo sobre el índice**: el `_DDL` actual (`memory.py:218-219`) crea
`ivfflat ... lists = 100` incondicionalmente. Con 741 filas eso son ~7 filas por lista:
la búsqueda pierde recall frente a un recorrido secuencial, que además es exacto. El
índice pasa a crearse solo por encima de `memoria.embedding.filas_minimas_indice`
(reserva 1000) y con `lists = max(1, filas // 1000)`. Por debajo, ninguno.

**Fin del descarte mudo** (`memory.py:273-282`): `_embed()` deja de comparar con `768`
a fuego. Compara con la dimensión real de la columna. Si no encaja: la fila se guarda
sin vector, se incrementa `descartes_por_dimension` (visible en `/api/memoria/estado`) y
se emite **un** aviso por sesión al log — no uno por fila, que sería una riada.

### 2. Dónde vive la dimensión — tres fuentes con papeles distintos, cero duplicación

| Fuente | Qué guarda | Por qué ahí |
| --- | --- | --- |
| La propia BD (`format_type(atttypid, atttypmod)` sobre `memories.embedding`) | verdad del **almacén** | es el único sitio que no puede mentir; si la columna es `vector(1024)`, lo es |
| `data/memoria/estado_embeddings.json` | verdad del **modelo**: dimensión medida, modelo, proveedor, fecha | es estado derivado y medido, no configuración: `data/`, no `config/` |
| `config/umbrales.json` → `memoria.embedding` | **política**: `proveedor_preferido`, `permitir_nube`, `lote_reindex`, `filas_minimas_indice`, `dimension_esperada_por_modelo` (solo para avisar antes de medir) | la regla del proyecto es umbrales al JSON; una política es un umbral, un hecho no |

**Rationale**: escribir `768` (o `1024`) en `umbrales.json` reproduce el bug actual en
otra dirección — el día que el modelo devuelva otra cosa, el JSON mentiría igual que
miente hoy el literal del código. Los hechos se **miden**; lo que se **configura** es la
política. La medición (`rag._embed_sync("nexus")`) se hace **bajo demanda** —al
comprobar o al migrar—, nunca en el arranque: si Ollama está apagado, nexus arranca.

### 3. Coste y privacidad del reindexado — presupuesto previo con dos cerrojos

Ningún reindexado se lanza sin un **plan** vigente. `POST /api/memoria/reindexar/plan`
devuelve, antes de gastar una sola llamada:

```json
{"id": "plan-20260801-1200", "filas": 741, "llamadas": 741,
 "proveedor": "ollama", "modelo": "nomic-embed-text",
 "destino": "http://127.0.0.1:11434", "sale_del_equipo": false,
 "aviso": "741 llamadas a Ollama en este equipo. El texto no sale de aqui.",
 "caduca": "2026-08-01T12:30:00"}
```

`sale_del_equipo` es `true` para `openai`/`gemini`/`cloud` **y también** para un Ollama
cuya URL no sea loopback: un Ollama remoto tampoco es local. Los dos cerrojos para el
caso de nube:

1. `config/umbrales.json` → `memoria.embedding.permitir_nube` (reserva **false**). En
   false, el reindexado con proveedor de nube falla con motivo claro y dice qué campo
   cambiar. No hay forma de lanzarlo desde la interfaz.
2. Con `permitir_nube: true`, además hace falta `confirm.request()` con un texto que
   nombra el proveedor, las llamadas y la frase «el contenido de tus documentos sale de
   este equipo».

**Independencia del cerebro** (decisión 1 del usuario): el camino de memoria no usa
`embed_provider: auto`. `rag._embed_sync(text, proveedor=None)` acepta proveedor
explícito y `memory` le pasa siempre el resuelto por
`memoria.embedding.proveedor_preferido` (reserva `"ollama"`). Cambiar el cerebro de chat
a Gemini deja de arrastrar los embeddings: un solo punto, un solo cambio de firma.

Ejecución por lotes de `lote_reindex` (reserva 32) sobre
`WHERE embedding IS NULL AND retirado_en IS NULL ORDER BY id`, con `commit` por lote:
reanudable por construcción (si se corta, la siguiente pasada retoma donde estaba) y
cancelable con una bandera. Progreso al `bus` por lote.

### 4. Deduplicación — huella canónica, en escritura **y** en pasada de limpieza

**Clave**: `huella = sha256(kind + "\n" + normalizado(texto))`, calculada en Python
(función `rag.huella()`, compartida por el camino de Postgres y el almacén local).
Normalización: NFKC → `casefold()` → colapso de espacios → `strip()`. **No** se quitan
tildes (en español «año» y «ano» no son el mismo hecho) ni puntuación.

Actúa en los dos sitios, y no es redundante:

- **Escritura** (idempotencia, regla C1): columna `huella TEXT`, `INSERT ... ON CONFLICT
  DO NOTHING RETURNING id`. Retorno vacío = «ya lo sabía», y eso es lo que se contesta.
  Sustituye también al `dedup` O(n) de `rag.py:263-268`, que además solo miraba el
  almacén local.
- **Limpieza** de los 39+38 duplicados existentes: **es un borrado**, así que va por el
  protocolo de purga (categoría `duplicados-exactos`, conserva el `id` más bajo). No hay
  `DELETE` silencioso en ninguna parte.

**Orden obligado**: la creación del índice único `memories_huella_idx` solo puede ocurrir
**después** de la limpieza. Si el usuario no confirma la limpieza, el índice no se crea y
`/api/memoria/estado` lo dice con todas las letras («la insercion idempotente no esta
activa: quedan N duplicados por revisar»). Honesto antes que cómodo — y esto condiciona
el orden de entrega (decisión 7).

### 5. Purga — reglas legibles, nunca un LLM

`backend/core/purga.py` clasifica con un motor de reglas alimentado por
`config/umbrales.json` → bloque `purga`. **Ningún LLM decide qué es irrelevante**: el
criterio tiene que poder enseñarse, y un modelo no sabe explicar por qué.

```jsonc
"purga": {
  "minutos_vigencia_plan": 30,
  "categorias": [
    {"id": "papeleo-personal", "personal": true, "minimo_aciertos": 1,
     "palabras": ["vida laboral", "empadronamiento", "irpf", "tasa", "matricula",
                  "curriculum", "cv", "boe"]},
    {"id": "estudios-dam", "minimo_aciertos": 2, "palabras": ["dam", "matricula", "..."]},
    {"id": "duplicados-exactos", "regla": "huella"}
  ]
}
```

Cada elemento clasificado lleva su **motivo**: categoría, regla que disparó, las
coincidencias literales y la línea donde estaban. Empate entre categorías → `sin-clasificar`.
Sin coincidencia → **no se toca** (B4). Nada viene marcado (B3).

**Nota `.md` ↔ filas de Postgres.** Hoy el vínculo es débil (`tags=["buzon", stem]`,
`meta.source`). Se añaden columnas `origen TEXT` y `dominio TEXT` a `memories` y se hace
un relleno retroactivo por el prefijo `[fichero]` que ya escribe `scheduler.py:45`. Las
filas que no se puedan vincular **no se retiran junto a la nota**: aparecen en el plan en
su propia sección para que el usuario las vea y decida. Preferible una fila visible a una
fila huérfana o a un borrado por inercia.

**Papelera: un estado, no una destrucción.**

| Medio | Retirada (paso 1) | Restauración |
| --- | --- | --- |
| Nota `.md` | se mueve a `data/memory/papelera/{lote}/`, con `sha256` y ruta original en `papelera.json` | vuelve a su ruta; si está ocupada, entra como `… (restaurado).md` y se dice |
| Fila de Postgres | `UPDATE memories SET retirado_en = now(), retirado_lote = %s` | `UPDATE ... SET retirado_en = NULL` |

Todas las lecturas (`recall`, `all_knowledge`, camino semántico y de respaldo) añaden
`AND retirado_en IS NULL`. El **paso 2** (exportar fuera del proyecto, o borrar de
verdad) es otro endpoint, con su propia confirmación, y **lo inicia el usuario**: nexus
no vacía la papelera ni pregunta por ella por iniciativa propia. El `scheduler` no la
toca — y hay un test que lo comprueba leyendo el fichero.

`aplicar` rechaza: plan desconocido, plan caducado, categoría que no venga en el plan,
lista de categorías vacía, y **plan rancio** (se guarda una huella del corpus —número de
`.md`, `mtime` máximo, número de filas— y si cambió, el plan ya no vale). Una categoría
con `personal: true` exige además `acepto_personal: true` en el cuerpo.

### 6. Ingesta — trocear de verdad, y estructura para el `.xlsx`

**Buzón**: `scheduler.py:34` cambia la lista de extensiones por
`files_io.puede_leer(f)` + `read_any()`. El tope de tamaño sube a
`memoria.ingesta.max_bytes` (reserva 5 MB): 500 KB no da ni para un `.docx` con imágenes.

**Truncado — dos sitios, no uno.** Además del `[:1500]` de `rag.reindex()` y el `900` del
buzón, `read_any()` corta a `_MAX_CHARS = 200_000` (`files_io.py:36`) y `_leer_xlsx()` a
3.000 filas. Un documento maestro no puede entrar por ahí (regla C3). Se añade
`read_any(path, limite=None)` — comportamiento idéntico para los llamadores actuales — y
`meta["truncado"]`. La ingesta pasa `limite=0` y **rechaza** cualquier fichero que
vuelva con `truncado: true`, diciendo por qué. Mejor no ingerir que ingerir a medias.

**Troceado** (`rag.trocear()`, valores en `memoria.troceado`): `tamano_caracteres` 1200,
`solape_caracteres` 200, `minimo_caracteres` 120 (una cola más corta se funde con el
trozo anterior en vez de convertirse en un trozo inútil). Corte por prioridad de
frontera: encabezado markdown → línea en blanco → fin de frase → corte duro. **Invariante
comprobable**: concatenar los trozos quitando el solape reproduce el texto original
carácter a carácter. Ese es el criterio de aceptación «suma de trozos = longitud del
original», y es un test, no una promesa.

**`.xlsx` por hojas y columnas** (decisión 5): `files_io.leer_xlsx_estructurado()`
devuelve `[{hoja, cabeceras, filas}]`. El troceado emite un trozo cada
`memoria.troceado.filas_por_trozo` (reserva 25) **por hoja**, con el nombre de la hoja y
las cabeceras repetidas en cada trozo, y cada fila como pares `columna: valor` en vez de
`a | b | c`. Así cada trozo se explica solo y ninguna fila se parte por la mitad.

**Metadatos de origen y dominio** (regla C2, y lo que hará posible purgar por dominio):

| Columna nueva en `memories` | Para qué |
| --- | --- |
| `origen`, `origen_tipo` | ruta real y procedencia (`documento`/`buzon`/`nota`/`skill`) |
| `dominio` | `marca-wabiks`, `personal`, `sistema` — el eje de purga futuro |
| `etiqueta`, `peso` | `historico` con `peso` 0.6 para el documento `ANTIGUO — …` |
| `huella` | dedup |
| `embed_model`, `embed_dim` | de qué modelo salió cada vector |
| `trozo_indice`, `trozo_total` | recomponer el documento |
| `retirado_en`, `retirado_lote` | papelera |

`recall()` multiplica `score * peso` **antes** del umbral: el manual antiguo se ingiere
(decisión 4) pero nunca gana al definitivo. Las marcas que disparan `historico`
(`memoria.ingesta.marcas_historico`) viven en el JSON y el plan de ingesta enseña qué
ficheros ha etiquetado así **antes** de ingerir, para poder corregirlo.

Ingesta dirigida: `POST /api/memoria/ingerir-carpeta` escribe espejos `.md` en
`data/memory/documentos/{dominio}/` con cabecera de metadatos. **Nunca escribe en la
carpeta de origen**: `Wabiks Content OS` es de solo lectura para nexus.

### 7. Orden de entrega — respaldo la partición en tres, con un ajuste

**Respaldo A → B → C**, con una corrección que la mejora: tal y como está propuesta, (A)
no puede terminar. Limpiar los 77 duplicados es un borrado, y el protocolo de borrado
(previsualizar / confirmar / papelera) nace en (B). (A) tendría que inventarse un borrado
propio — exactamente lo que este cambio existe para evitar.

| PR | Contenido | Líneas est. | Por qué es autónomo |
| --- | --- | --- | --- |
| **A — embeddings y huella** | dimensión detectada, migración de columna, plan+presupuesto de reindexado, reindexado por lotes, `huella` + inserción idempotente, **informe de solo lectura** de duplicados | ~390 | Puramente **aditivo**: no borra nada. Revertible con `git revert` + `DROP COLUMN` |
| **B — purga** | `purga.py`, papelera, restaurar, exportar, borrado definitivo, categoría `duplicados-exactos`, e índice único al terminar la limpieza | ~490 | Es el que toca datos personales. Va **solo**, para que se revise sin 800 líneas encima |
| **C — ingesta** | `read_any(limite)`, xlsx estructurado, `trocear()`, buzón por `puede_leer()`, ingesta dirigida, metadatos | ~420 | No depende de B; depende de A solo para que lo ingerido se vectorice bien |

El argumento de aislar (B) es el bueno y lo hago mío: es el único PR que puede perder
papeles del usuario. Con este ajuste, **(A) no contiene ni una línea de borrado** y (B)
concentra todo lo destructivo en un diff que se puede leer entero de una sentada.

**Aviso de estimación**: mi cuenta da ~1.300 líneas, no las 700-800 de la propuesta —
las columnas nuevas, el troceado con invariante y las tres suites cuestan más de lo
estimado. Cada PR sigue por debajo del presupuesto de 800; el conjunto no. Sin la
partición, este cambio es inentregable.

## Flujo de datos

```
    fichero (.docx/.pdf/.xlsx)
            │  files_io.read_any(limite=0) ─── truncado? → se RECHAZA y se dice
            ▼
      rag.trocear()  ── umbrales: tamano / solape / filas_por_trozo
            │  trozos + {origen, dominio, etiqueta, peso, trozo_i/n}
            ▼
      rag.huella() ──► ON CONFLICT DO NOTHING ──► «ya lo sabia»
            │
            ▼
   memory.remember()  ── proveedor = politica de memoria (NO el cerebro)
            │              dim != columna → sin vector + contador + 1 aviso
            ▼
        memories (Postgres) ──► recall(): score * peso, AND retirado_en IS NULL


   purga.previsualizar() ──► plan (reglas + motivo) ──► confirm.request()
            │                                                 │
            │  nada se toca                                   ▼
            └────────────────────────────────► papelera: .md movido
                                                + UPDATE retirado_en
                                                        │
                                        restaurar ◄─────┤
                                        exportar  ◄─────┤  (paso 2:
                                        borrar    ◄─────┘   lo inicia el usuario)
```

## Ficheros

| Fichero | Acción | Qué cambia |
| --- | --- | --- |
| `backend/core/memory.py` | Modificar | dimensión real, migración, reindexado por lotes, huella, columnas nuevas, `retirado_en` en todas las lecturas |
| `backend/core/purga.py` | Crear | clasificación explicable, planes, papelera, restaurar, exportar, borrado definitivo |
| `backend/core/rag.py` | Modificar | `huella()`, `trocear()`, `_embed_sync(text, proveedor)`, `reindex()` deja de truncar |
| `backend/core/scheduler.py` | Modificar | buzón por `puede_leer()`/`read_any()`, troceado real, metadatos |
| `backend/core/files_io.py` | Modificar | `read_any(path, limite)`, `meta["truncado"]`, `leer_xlsx_estructurado()` |
| `backend/app.py` | Modificar | 14 endpoints finos bajo `/api/memoria/…` (delegan, no deciden) |
| `config/umbrales.json` | Modificar | bloques `memoria.embedding`, `memoria.troceado`, `memoria.ingesta`, `memoria.pesos`, `purga` |
| `tests/test_memoria_embeddings.py` · `test_purga.py` · `test_ingesta_documentos.py` | Crear | + alta en `tests/run_all.py` |

## Contratos

```python
# rag.py
def huella(texto: str, kind: str = "knowledge") -> str: ...
def trocear(texto: str, *, fuente: str = "texto") -> list[dict]:
    """[{'texto','indice','total','titulo'}] — sin perder un caracter."""

# memory.py
def dimension_columna() -> int | None:        # format_type() sobre pg_attribute
def dimension_modelo(medir: bool = False) -> dict
def plan_migracion_vector() -> dict           # {columna, modelo, vectores, destruye, id}
def migrar_vector(plan_id: str) -> dict       # exige plan vigente + confirmación
def plan_reindexado() -> dict                 # {filas, llamadas, proveedor, sale_del_equipo}

# purga.py
def previsualizar() -> dict                   # {id, caduca, categorias:[{id, personal, items:[{ruta, motivo, filas_pg}]}]}
def aplicar(plan_id: str, categorias: list[str], acepto_personal: bool = False) -> dict
def papelera() -> list[dict]
def restaurar(lote: str) -> dict
def exportar(lote: str, destino: str | None = None) -> dict
def borrar_definitivo(lote: str) -> dict      # paso 2, confirmación propia
```

## Estrategia de pruebas

| Capa | Qué se prueba | Cómo |
| --- | --- | --- |
| Unidad | `trocear()` no pierde un carácter; `huella()` estable ante NFKC/espacios y distinta con tildes; clasificación devuelve motivo legible; `sale_del_equipo` por proveedor y por URL | scripts con `check(cond, msg)`, sin BD |
| Unidad | cambiar `umbrales.json` **cambia el resultado** (patrón de `test_umbrales.py`), y con el fichero tal cual se entrega el comportamiento no cambia | módulo recargado de cero |
| Integración | previsualizar no altera ni un fichero ni una fila; aplicar sin plan / caducado / con categoría no confirmada falla con motivo; restaurar devuelve a la ruta original | carpeta temporal + BD si está online, si no se salta con aviso |
| Integración | reindexar con `permitir_nube: false` y proveedor de nube **falla**; con Ollama local no pide confirmación de salida de datos | proveedor simulado, cero llamadas reales |
| Invariante | el `scheduler` no menciona la papelera ni el borrado | lectura del propio fichero |
| E2E | los 6 documentos de Wabiks entran con origen y dominio; el maestro completo; buscar «wabiks content os» devuelve marca | `tests/e2e/` |

## Matriz de amenazas (lo aplicable)

No hay enrutado nuevo, ni shell, ni subprocesos, ni automatización de VCS/PR, ni
clasificación de ejecutables. Sí hay frontera de **sistema de ficheros y borrado**:

| Amenaza | Requisito de diseño (pasa a tareas y a test RED) |
| --- | --- |
| Traversal en `ingerir-carpeta {ruta}` y `exportar {destino}` | `Path.resolve()` y comprobación de que cae dentro de las carpetas permitidas por `perm_files`/`perm_folders`; ruta fuera → error, no recorte silencioso |
| Escape por enlace simbólico al mover a la papelera | `is_symlink()` → no se mueve, se lista aparte |
| Sobrescritura al restaurar | ruta ocupada → se restaura renombrado y se dice; jamás se pisa |
| Aplicar sin previsualización vigente | plan con TTL + huella del corpus; rancio = rechazo |
| Borrado sin traza | toda retirada y todo borrado definitivo escriben en `audit.log` con lote, categoría y motivo |

## Migración y despliegue

Columnas nuevas por `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` dentro del `_DDL`
idempotente que ya existe: sin ellas, nexus sigue arrancando (cada sentencia va en su
`try`). Nada se ejecuta en el arranque salvo el DDL: migración de vector, reindexado,
purga e ingesta dirigida son todas acciones a petición. Reversión por PR con `git revert`;
la columna `embedding_dim768` sobrevive a la reversión y devuelve los vectores viejos.

## Preguntas abiertas

- [ ] Dominio por defecto de lo que ya está en `memories` sin `origen` reconstruible: se
      propone `sin-clasificar` y no tocarlo nunca. Confirmar en `sdd-tasks`.
- [ ] ¿La papelera tiene tope (como `_TRASH_MAX = 500` del tablero) o crece sin límite?
      Se propone **sin límite**: un tope es un borrado automático, y aquí no hay ninguno.
