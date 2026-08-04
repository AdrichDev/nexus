# Tareas: 002 — Memoria y conocimiento

Manda `openspec/changes/002-memoria-y-conocimiento/design.md` y, sobre él, la
sección «Decisiones resueltas con el usuario (01/08/2026)» de `proposal.md`.
Entrega en **tres bloques secuenciales A → B → C**, cada uno un commit (o
grupo de commits) directo sobre `main`, verificable por separado con
`.venv\Scripts\python.exe tests\run_all.py` en verde. No hay flujo de PRs en
este repositorio; «PR» abajo es solo la unidad de revisión de una sentada.

## Review Workload Forecast

| Campo | Valor |
|---|---|
| Líneas estimadas (total) | ~1300 (A ~390, B ~490, C ~420) |
| Presupuesto de sesión | 800 líneas |
| Riesgo frente a 800 | Bajo por bloque (ninguno lo alcanza); el conjunto sí lo supera — por eso hay tres entregas |
| Riesgo frente al umbral genérico de 400 líneas | A: Bajo (390) · B: Medio (490) · C: Medio (420) |
| PRs encadenados recomendados | Sí (ya decidido por el usuario) |
| División sugerida | A (embeddings+huella) → B (purga) → C (ingesta) |
| Estrategia de entrega | ask-on-risk |
| Estrategia de cadena | stacked-to-main (commits directos y en orden, no PRs de GitHub) |

```text
Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium
```

### Suggested Work Units

| Unidad | Objetivo | Entrega | Test enfocado | Arnés de ejecución real | Frontera de rollback |
|---|---|---|---|---|---|
| A | Dimensión real, migración de columna, reindexado por lotes, huella + inserción idempotente (sin índice único todavía), informe de solo lectura de duplicados. Cero borrados. | A | `.venv\Scripts\python.exe tests\test_memoria_embeddings.py` | Levantar `nexus_memoria_postgres` (127.0.0.1:5433) y repetir la suite; sin contenedor se salta con aviso y NO cuenta como probado | `git revert`; la columna vieja `embedding_dim{N}` sobrevive intacta, nada de usuario se pierde |
| B | `purga.py` completo, papelera en dos tiempos, limpieza de los 77 duplicados vía protocolo de borrado, índice único `memories_huella_idx` tras confirmación, cierre de migración (`DROP` del respaldo) | B | `.venv\Scripts\python.exe tests\test_purga.py` | Igual que A + confirmar `restaurar()` sobre datos reales de `data/memory/papelera/` antes de dar el bloque por bueno | `git revert`; `restaurar()` sobre todo lote retirado antes de revertir; `DROP INDEX memories_huella_idx` si llegó a crearse |
| C | `read_any(limite=0)` sin truncar, `.xlsx` por hojas/columnas, `trocear()` real, buzón por `puede_leer()`, ingesta dirigida de los 6 documentos de Wabiks Content OS | C | `.venv\Scripts\python.exe tests\test_ingesta_documentos.py` | Igual que A/B; además ingesta real de los 6 ficheros contra el contenedor levantado, no solo mockeada | `git revert`; los `.md` generados en `data/memory/documentos/` quedan huérfanos pero inertes, se pueden borrar a mano |

### Dependencias entre bloques

- **B depende de A**: usa la columna `huella` y la función `rag.huella()` que A crea; el índice único solo se activa si B confirma la limpieza.
- **C depende de A** (para que lo ingerido se vectorice con la dimensión correcta) y **se apoya en B** para inserción idempotente de verdad, pero puede escribir código y trocear **antes** de que exista el índice único — sin él, la idempotencia de la ingesta queda a nivel de aplicación (comprobación de huella antes de insertar), igual que hoy.
- **Estado intermedio legítimo entre A y B**: si el usuario no confirma la limpieza de duplicados, el índice único no existe. `/api/memoria/estado` DEBE decirlo con todas las letras: «la inserción idempotente no está activa: quedan N duplicados por revisar». No es un bug, es el diseño.

### Decisiones de esta fase (preguntas abiertas del diseño, resueltas aquí)

1. **Dominio por defecto** de filas ya existentes en `memories` sin origen reconstruible: `'sin-clasificar'`, vía `DEFAULT` de la columna nueva (C1.1). Regla B4 de purga: lo no clasificado no se toca nunca automáticamente.
2. **Tope de la papelera**: sin tope numérico (a diferencia de `board.py`/`_TRASH_MAX`). Capar el índice rompería la reversibilidad prometida (B6): una entrada que cae del índice sería un fichero físico irrecuperable por API. En su lugar, `purga.papelera_aviso_items` en `umbrales.json` (reserva 3000) solo dispara un aviso informativo; nada se borra solo.

---

## Bloque A — Embeddings y preparación de deduplicación (puramente aditivo)

Sin una sola línea de `DELETE`/`DROP` sobre datos de usuario. Todo lo de aquí
es columna nueva, función nueva o endpoint de lectura.

### A1. Fundamentos — configuración y estado

- [x] A1.1 `config/umbrales.json`: añadir bloque `memoria.embedding` (`proveedor_preferido: "ollama"`, `permitir_nube: false`, `lote_reindex`, `filas_minimas_indice: 1000`) sin tocar las claves existentes de `memoria`. — *Cubre*: memoria-embeddings, req. «Aislamiento de privacidad»
- [x] A1.2 Crear `data/memoria/estado_embeddings.json` (dimensión medida, modelo, proveedor, fecha) como estado derivado, no configuración. — *Cubre*: diseño §2

### A2. Migración de columna (renombrar, no `ALTER` in situ)

- [x] A2.1 `backend/core/memory.py`: función `detectar_dimension()` — embedding de prueba al `embed_model` activo vs. `format_type()` de la columna real en Postgres. — *Cubre*: memoria-embeddings, escenario «Dimensión distinta a la columna» — *Test*: `test_memoria_embeddings.py::test_detectar_dimension_distinta`
- [x] A2.2 `memory.py`: `migrar_vector(dim)` — `DROP INDEX IF EXISTS memories_embedding_idx` → `ALTER TABLE memories RENAME COLUMN embedding TO embedding_dim{vieja}` → `ALTER TABLE memories ADD COLUMN embedding vector(N)`; cada paso en `audit.log`; exige `confirm.request()` previo. — *Cubre*: memoria-embeddings, escenario «Migración confirmada con datos existentes» — *Test*: `test_memoria_embeddings.py::test_migrar_vector_no_pierde_filas`
- [x] A2.3 `memory.py:218-219` — el índice `ivfflat` deja de crearse incondicionalmente: solo si `filas >= memoria.embedding.filas_minimas_indice`, con `lists = max(1, filas // 1000)`. — *Cubre*: diseño «índice vectorial mal dimensionado» — *Test*: `test_memoria_embeddings.py::test_indice_no_se_crea_bajo_umbral`
- [x] A2.4 `memory.py:273-282 _embed()` — deja de comparar contra `768` a fuego; compara con la dimensión real de la columna. Vector que no encaja: fila se guarda sin vector, contador `descartes_por_dimension` (+1), **un** aviso por sesión, nunca por fila. — *Cubre*: memoria-embeddings, escenario «Vector de longitud inesperada tras la migración» — *Test*: `test_memoria_embeddings.py::test_descarte_avisa_y_cuenta_no_silencioso`
- [x] A2.5 `POST /api/memoria/vector/migrar` en `backend/app.py`, protegido por `confirm.request()`. — *Test*: `test_memoria_embeddings.py::test_endpoint_migrar_exige_confirmacion`

### A3. Reindexado explícito, por lotes, privado por defecto

- [x] A3.1 `memory.py`: `plan_reindexado()` → `{filas, llamadas, proveedor, destino, sale_del_equipo, aviso, caduca}`. `sale_del_equipo=true` para `openai`/`gemini`/`cloud` **y** para Ollama en URL no-loopback. — *Cubre*: memoria-embeddings, req. «Aislamiento de privacidad» — *Test*: `test_memoria_embeddings.py::test_sale_del_equipo_por_proveedor_y_por_url`
- [x] A3.2 `memory.py`: `reindexar(plan_id, ...)` por lotes de `memoria.embedding.lote_reindex`, reanudable desde la primera fila sin embedding (no re-procesa las ya hechas). Con `permitir_nube:false` y proveedor de nube: falla con motivo claro, sin llegar a la interfaz. Con nube permitida: exige `confirm.request()` nombrando proveedor y nº de llamadas antes de la primera fila. — *Cubre*: memoria-embeddings, escenarios «Reindexado interrumpido a mitad», «Reindexado completo», «Reindexado con proveedor de nube» — *Test*: `test_memoria_embeddings.py::test_reindexado_reanuda_sin_repetir`, `::test_reindexado_nube_exige_confirmacion`
- [x] A3.3 `rag._embed_sync(text, proveedor=None)`: acepta proveedor explícito; `memory.py` le pasa siempre `memoria.embedding.proveedor_preferido`, nunca `embed_provider: auto` que sigue al cerebro. — *Cubre*: memoria-embeddings, escenario «Cambio de cerebro de chat no afecta a embeddings» — *Test*: `test_memoria_embeddings.py::test_cambiar_cerebro_no_cambia_embed_provider`
- [x] A3.4 `POST /api/memoria/reindexar/plan` y `POST /api/memoria/reindexar` en `app.py`. — *Test*: `test_memoria_embeddings.py::test_endpoints_reindexado`

### A4. Huella e inserción idempotente (sin índice único todavía)

- [x] A4.1 `rag.huella(texto) -> str`: normaliza NFKC + espacios, hash estable; misma huella pese a espaciado/mayúsculas, distinta con tildes. — *Cubre*: memoria-deduplicacion, escenario «Normalización antes de la huella» — *Test*: `test_memoria_embeddings.py::test_huella_estable_nfkc`
- [x] A4.2 `memory.py`: `ALTER TABLE memories ADD COLUMN IF NOT EXISTS huella TEXT` (nullable, aditivo) dentro del `_DDL` idempotente. — *Cubre*: memoria-deduplicacion, delta de esquema
- [x] A4.3 `memory.py`: paso de mantenimiento explícito `backfill_huella()` que calcula `huella` para filas históricas sin ella (no se ejecuta en cada arranque). — *Cubre*: memoria-deduplicacion, «Autorreparación»
- [x] A4.4 `remember()`/inserción de conocimiento: si el índice único **no** existe aún, comprueba huella a nivel de aplicación antes de insertar (sustituye al `dedup` O(n) local de `rag.py:263-268`, que solo miraba el almacén local); si existe, usa `INSERT ... ON CONFLICT DO NOTHING RETURNING id` y ausencia de fila = «ya lo sabía». — *Cubre*: memoria-deduplicacion, escenario «Reinserción del mismo hecho» — *Test*: `test_memoria_embeddings.py::test_reinsertar_mismo_hecho_no_duplica`
- [x] A4.5 `memory.py`: `duplicados_exactos() -> list[dict]` — informe de **solo lectura**, agrupa por huella con `count(*) > 1`, lista filas sobrantes y cuál se conservaría (la más antigua). No borra nada; alimenta a `purga.py` en B. — *Cubre*: memoria-deduplicacion, escenario «Previsualización de duplicados antes de limpiar» (parte de lectura) — *Test*: `test_memoria_embeddings.py::test_duplicados_exactos_no_borra_nada`
- [x] A4.6 `GET /api/memoria/estado`: dimensión, `descartes_por_dimension`, y si el índice único no existe aún: «la inserción idempotente no está activa: quedan N duplicados por revisar». — *Test*: `test_memoria_embeddings.py::test_estado_dice_indice_no_activo`

### A5. Tests y alta en `run_all.py`

- [x] A5.1 Crear `tests/test_memoria_embeddings.py` (patrón `check(cond, msg)`, sin pytest) con todos los casos de A1-A4.
- [x] A5.2 Añadir `"test_memoria_embeddings.py"` a la lista de suites de `tests/run_all.py`.
- [x] A5.3 Verificación manual del camino de BD: levantar `nexus_memoria_postgres`, correr la suite, confirmar 0 líneas «SALTADO (sin BD)» en la salida — un `run_all.py` verde con el contenedor caído NO prueba nada de Postgres.

---

## Bloque B — La purga entera (único bloque que toca datos personales)

Depende de A (columna `huella`, función `rag.huella()`, `duplicados_exactos()`).
Todo lo destructivo vive aquí, en un solo diff que se revisa de una sentada.

### B1. Esquema y configuración

- [x] B1.1 `config/umbrales.json`: bloque `purga` completo (`minutos_vigencia_plan`, `categorias` con `papeleo-personal`/`estudios-dam`/`duplicados-exactos`/etc., `papelera_aviso_items: 3000`). — *Cubre*: memoria-purga, req. «Clasificación explicable»
- [x] B1.2 `memory.py`: `ALTER TABLE memories ADD COLUMN IF NOT EXISTS retirado_en TIMESTAMPTZ`, `retirado_lote TEXT` en el `_DDL` idempotente. — *Cubre*: memoria-purga, «Papelera reversible»
- [x] B1.3 `memory.py`: `recall()`, `all_knowledge()` y el camino de respaldo `ILIKE` añaden `AND retirado_en IS NULL` a **todas** las lecturas. — *Cubre*: memoria-purga, req. «Alcance dual» — *Test*: `test_purga.py::test_lecturas_excluyen_retirados`

### B2. `backend/core/purga.py` — clasificación explicable

- [x] B2.1 Crear `backend/core/purga.py`: `clasificar()` recorre `.md` de `data/memory/` + filas de `memories`, motor de reglas leído de `umbrales.json.purga.categorias` (palabras + `minimo_aciertos`), **ningún LLM decide**. Cada resultado lleva la regla que lo clasificó. — *Cubre*: memoria-purga, req. «Clasificación explicable», escenario «Nota sin categoría reconocida» — *Test*: `test_purga.py::test_clasificar_devuelve_motivo`, `::test_no_clasificado_no_aparece`
- [x] B2.2 `previsualizar() -> dict {id, caduca, categorias:[{id, personal, items:[{ruta, motivo, filas_pg}]}]}`, guarda huella del corpus (nº `.md`, `mtime` máximo, nº filas) junto al plan. Ninguna categoría viene marcada. — *Cubre*: memoria-purga, req. «Previsualización obligatoria y previa», escenario «Previsualizar no cambia nada» — *Test*: `test_purga.py::test_previsualizar_no_altera_ficheros_ni_filas`

### B3. `aplicar` / papelera / restaurar / exportar / borrado definitivo

- [x] B3.1 `aplicar(plan_id, categorias, acepto_personal=False)`: rechaza plan desconocido, caducado (TTL `minutos_vigencia_plan`), categoría fuera del plan, lista vacía, y **plan rancio** (huella del corpus cambió). Categoría `personal:true` exige `acepto_personal:true`. — *Cubre*: memoria-purga, escenario «Aplicar sin previsualización vigente», «Confirmar solo una categoría» — *Test*: `test_purga.py::test_aplicar_sin_plan_falla`, `::test_aplicar_plan_rancio_falla`, `::test_confirmar_una_categoria_no_toca_las_otras`
- [x] B3.2 Retirada: nota `.md` se mueve a `data/memory/papelera/{lote}/` con `sha256` + ruta original en `papelera.json` (sin tope, ver decisión 2); fila Postgres: `UPDATE memories SET retirado_en=now(), retirado_lote=%s`. Categoría personal: exporta copia legible **antes** de mover. — *Cubre*: memoria-purga, req. «Papelera reversible», «Categoría personal — exportar, nunca borrado duro» — *Test*: `test_purga.py::test_retirar_papeleo_personal_exporta_antes_de_mover`
- [x] B3.3 `papelera()`, `restaurar(lote)` — vuelve a la ruta original; si está ocupada, entra como `… (restaurado).md` y se dice; fila Postgres: `retirado_en=NULL`. — *Cubre*: memoria-purga, escenario «Restaurar desde la papelera» — *Test*: `test_purga.py::test_restaurar_devuelve_ruta_original`
- [x] B3.4 `exportar(lote, destino=None)`, `borrar_definitivo(lote)` — paso 2, confirmación propia, **lo inicia el usuario**; nexus nunca vacía la papelera ni pregunta por iniciativa propia. `scheduler.py` no la toca. — *Cubre*: memoria-purga, escenario «El sistema nunca vacía la papelera solo» — *Test*: `test_purga.py::test_scheduler_no_toca_papelera` (lee el fichero de `scheduler.py`, no solo el comportamiento en runtime)

### B4. Limpieza de duplicados e índice único (orden obligado)

- [x] B4.1 Categoría `duplicados-exactos` en `previsualizar()` consume `memory.duplicados_exactos()` de A4.5; conserva el `id` más bajo por grupo. — *Cubre*: memoria-deduplicacion, escenario «Limpieza conserva la fila más antigua» — *Test*: `test_purga.py::test_duplicados_exactos_conserva_mas_antigua`
- [x] B4.2 Tras `aplicar("duplicados-exactos", ...)` confirmado y sin duplicados restantes: `CREATE UNIQUE INDEX IF NOT EXISTS memories_huella_idx ON memories(huella) WHERE retirado_en IS NULL`. Si el usuario no confirma, el índice **no** se crea. — *Cubre*: memoria-deduplicacion, req. «Inserción idempotente», escenario «Consulta de duplicados exactos vacía» — *Test*: `test_purga.py::test_indice_unico_solo_tras_limpieza_confirmada`
- [x] B4.3 Cierre de la migración A2: endpoint `POST /api/memoria/vector/limpiar-respaldo` con `confirm.request()` propio, `DROP COLUMN embedding_dim{vieja}` — segunda acción explícita, nunca automática ni encadenada a A2.2. — *Cubre*: diseño §1 «soltar el respaldo es una segunda acción explícita» — *Test*: `test_purga.py::test_limpiar_respaldo_exige_confirmacion_propia`

### B5. Endpoints `app.py`

- [x] B5.1 `GET /api/memoria/purga/previsualizar`, `POST /api/memoria/purga/aplicar`, `GET /api/memoria/purga/papelera`, `POST /api/memoria/purga/restaurar`, `POST /api/memoria/purga/exportar`, `POST /api/memoria/purga/borrar-definitivo`. — *Test*: `test_purga.py::test_endpoints_purga_smoke`

### B6. Matriz de amenazas — RED antes que producción

- [x] B6.1 **RED** `test_purga.py::test_symlink_no_se_mueve_a_papelera` — enlace simbólico dentro de `data/memory/`: `is_symlink()` → no se mueve, se lista aparte. Escribir el test primero (falla contra el código actual, que no existe). — *Cubre*: matriz de amenazas «Escape por enlace simbólico»
- [x] B6.2 **GREEN** implementar la comprobación `is_symlink()` en B3.2 que hace pasar B6.1.
- [x] B6.3 **RED** `test_purga.py::test_restaurar_no_sobrescribe` — ruta ocupada al restaurar. — *Cubre*: matriz de amenazas «Sobrescritura al restaurar»
- [x] B6.4 **GREEN** el renombrado `… (restaurado).md` de B3.3 hace pasar B6.3.
- [x] B6.5 **RED** `test_purga.py::test_borrado_sin_traza_falla` — toda retirada y todo borrado definitivo escriben en `audit.log` con lote, categoría y motivo; si `audit.log` no recibe la entrada, el test falla. — *Cubre*: matriz de amenazas «Borrado sin traza»
- [x] B6.6 **GREEN** llamada a `audit.log()` en B3.2/B3.4 que hace pasar B6.5.
- [x] B6.7 **RED** `test_purga.py::test_exportar_traversal_rechazado` — `destino` fuera de las carpetas permitidas por `perm_folders` se rechaza, no se recorta en silencio. — *Cubre*: matriz de amenazas «Traversal en exportar»
- [x] B6.8 **GREEN** `Path.resolve()` + comprobación de pertenencia en B3.4 que hace pasar B6.7.

### B7. Tests, alta en `run_all.py` y verificación manual

- [x] B7.1 Crear `tests/test_purga.py` con todos los casos de B1-B6 (incluye los RED de B6 ya en verde tras el GREEN correspondiente).
- [x] B7.2 Añadir `"test_purga.py"` a `tests/run_all.py`.
- [x] B7.3 Verificación manual con `nexus_memoria_postgres` arriba: previsualizar de verdad sobre las 84 notas reales de `data/memory/`, confirmar solo `duplicados-exactos`, comprobar en Postgres que las otras categorías no se tocaron, y `restaurar()` un lote real antes de dar el bloque por cerrado.
  **DESVIACIÓN DELIBERADA (registrada, no oculta):** solo se ejecutó la mitad de SOLO LECTURA de esta verificación: `previsualizar()` real confirmó 84 notas y 3 categorías (`estudios-dam`: 35, `papeleo-personal`: 12, `duplicados-exactos`: 34 grupos / 338 filas «sobran»; los ids 804/805/807 no están en ningún grupo). **NO se llamó a `aplicar()` contra datos reales**: la regla absoluta fijada en esta sesión («CONSTRUYE EL MECANISMO DE PURGA. NO PURGUES NADA... la ejecución real la autoriza el usuario más tarde») tiene prioridad sobre la redacción literal de esta tarea. Motivo técnico adicional: confirmar `duplicados-exactos` de verdad dispararía `crear_indice_huella()` sobre la tabla `memories` real (cambio de esquema, no solo de datos) y, si luego se restaura ese mismo lote, el índice único parcial recién creado haría fallar el `UPDATE` de restauración (mismo huella + `retirado_en IS NULL` dos veces) — el propio mecanismo garantiza que un duplicado confirmado y indexado no se puede «des-purgar» sin datos, así que restaurar deja de tener sentido en ese momento. El mecanismo en sí (clasificar/previsualizar/aplicar/papelera/restaurar/exportar/borrar_definitivo/índice/limpiar_respaldo) está cubierto por 64 comprobaciones GREEN en `test_purga.py`, incluida `test_indice_unico_solo_tras_limpieza_confirmada` sobre una tabla de usar-y-tirar. Queda pendiente que el usuario ejecute la confirmación real cuando lo decida.

---

## Bloque C — Ingesta de los documentos de Wabiks Content OS

Depende de A (vectorización correcta); se apoya en B para idempotencia a
nivel de índice, pero no bloquea si B aún no está confirmado (usa la
comprobación de huella en aplicación, igual que A4.4).

Documentos exactos en `D:\Adrian\22. Proyectos\NEXUS\Wabiks Content OS`
(5 `.docx` + 1 `.xlsx`, verificados en disco):

1. `Wabiks Content OS — Manual definitivo de conversaciones e instrucciones.docx` (raíz) — manual definitivo, peso normal
2. `ANTIGUO — Wabiks Content OS — Manual de conversaciones e instrucciones.docx` (raíz) — histórico, se ingiere con menos peso (regla C4)
3. `00 — Fuentes oficiales\Wabiks Content OS — Documento maestro.docx` — documento maestro, entra completo
4. `00 — Fuentes oficiales\Wabiks Content Intelligence.xlsx` — por hojas y columnas, no aplanado
5. `01 — Configuración IA\Guía de configuración — Claude para Wabiks Content OS.docx`
6. `02 — Contenidos en producción\Carrusel — Más de 150 modelos.docx`

### C1. Fundamentos — cuatro truncados, no dos

- [x] C1.1 `config/umbrales.json`: bloques `memoria.troceado` (`tamano_caracteres:1200`, `solape_caracteres:200`, `minimo_caracteres:120`), `memoria.ingesta` (`max_bytes` buzón, `marcas_historico`, `filas_por_trozo:25`), `memoria.pesos` (peso normal vs. histórico).
- [x] C1.2 `memory.py`: `ALTER TABLE memories ADD COLUMN IF NOT EXISTS origen TEXT, origen_tipo TEXT, dominio TEXT NOT NULL DEFAULT 'sin-clasificar', etiqueta TEXT, peso REAL NOT NULL DEFAULT 1.0`. El `DEFAULT 'sin-clasificar'` resuelve la pregunta abierta del diseño para filas históricas sin origen. — *Cubre*: memoria-ingesta-documentos, req. «Metadatos de origen y dominio»
- [x] C1.3 `files_io.py:36` — `_MAX_CHARS` deja de cortar el texto devuelto por `read_any()`; nuevo parámetro `read_any(path, limite=0)` donde `0` = sin límite (llamador decide). — *Cubre*: memoria-ingesta-documentos, req. «Troceado sin truncar» (1/4 truncados) — *Test*: `test_ingesta_documentos.py::test_read_any_limite_cero_no_trunca`
- [x] C1.4 `files_io.py:114 _leer_xlsx()` — el corte a 3000 filas por hoja se sustituye por lectura completa (con aviso si supera un tope configurable, no un corte mudo). — *Cubre*: memoria-ingesta-documentos, req. «`.xlsx` por hojas y columnas» (2/4 truncados) — *Test*: `test_ingesta_documentos.py::test_xlsx_no_trunca_filas`

### C2. `rag.py` — troceado real (3er y 4º truncado)

- [x] C2.1 `rag.trocear(texto) -> list[dict]`: corte por prioridad de frontera (encabezado markdown → línea en blanco → fin de frase → corte duro); `minimo_caracteres` funde colas cortas con el trozo anterior. Invariante comprobable: concatenar trozos quitando el solape reproduce el original carácter a carácter. — *Cubre*: memoria-ingesta-documentos, req. «Troceado sin truncar», escenario «Documento maestro completo» — *Test*: `test_ingesta_documentos.py::test_trocear_reconstruye_original_exacto`
- [x] C2.2 `rag.py:421 reindex()` — quita el corte `[:1500]`; usa `rag.trocear()` sobre el texto completo. (3er truncado) — *Test*: `test_ingesta_documentos.py::test_reindex_no_trunca_a_1500`
- [x] C2.3 `scheduler.py:44-45 _ingest_inbox()` — quita el corte a `900`/`20000`; usa `rag.trocear()`. (4º truncado) — *Test*: `test_ingesta_documentos.py::test_buzon_no_trunca_a_900`

### C3. Buzón — acepta lo que `read_any()` sabe leer

- [x] C3.1 `scheduler.py:34` — la lista fija de extensiones se sustituye por `files_io.puede_leer(f)`; texto vía `read_any(f, limite=0)`. — *Cubre*: memoria-ingesta-documentos, escenario «`.docx`, `.pdf` y `.xlsx` en el buzón» — *Test*: `test_ingesta_documentos.py::test_buzon_acepta_docx_pdf_xlsx`
- [x] C3.2 `.xlsx` en el buzón: un trozo por cada `memoria.troceado.filas_por_trozo` filas **por hoja**, con nombre de hoja y cabeceras repetidas, cada fila como `columna: valor`. — *Cubre*: memoria-ingesta-documentos, req. «`.xlsx` por hojas y columnas», escenario «"Wabiks Content Intelligence" ingerido por estructura» — *Test*: `test_ingesta_documentos.py::test_xlsx_trocea_por_hoja_sin_partir_filas`

### C4. Ingesta dirigida de carpeta

- [x] C4.1 `POST /api/memoria/ingerir-carpeta {ruta}` en `app.py`: recorre ficheros legibles, escribe `.md` en `data/memory/documentos/{dominio}/` con cabecera de metadatos (origen, dominio, fecha) antes de trocear. — *Cubre*: memoria-ingesta-documentos, req. «Ingesta dirigida de una carpeta» — *Test*: `test_ingesta_documentos.py::test_ingerir_carpeta_escribe_md_con_metadatos`
- [x] C4.2 `ANTIGUO — …Manual de conversaciones…` se ingiere por defecto, etiqueta `historico`, `peso` = valor bajo de `memoria.pesos`; el manual definitivo desempata por encima de él en `recall()` (`score * peso`). — *Cubre*: memoria-ingesta-documentos, req. «Documento histórico marcado y con menos peso» — *Test*: `test_ingesta_documentos.py::test_manual_definitivo_gana_al_historico`
- [x] C4.3 **RED** `test_ingesta_documentos.py::test_ingerir_carpeta_traversal_rechazado` — `ruta` fuera de `perm_folders` se rechaza con `Path.resolve()`, no se recorta en silencio. — *Cubre*: matriz de amenazas «Traversal en `ingerir-carpeta`»
- [x] C4.4 **GREEN** comprobación de pertenencia en C4.1 que hace pasar C4.3.

### C5. Ingesta real de los 6 documentos de Wabiks Content OS

- [x] C5.1 Ejecutar `ingerir-carpeta` contra `D:\Adrian\22. Proyectos\NEXUS\Wabiks Content OS` con el contenedor levantado; verificar en Postgres que los 6 quedan con `origen`, `dominio='wabiks-content-os'`, y que el documento maestro reconstruye longitud completa (suma de trozos = longitud original, último trozo presente). — *Cubre*: criterio de aceptación de `proposal.md` «Los 6 documentos de Wabiks Content OS quedan ingeridos con origen y dominio»
- [x] C5.2 Verificación manual de negocio: buscar «wabiks content os» vía `recall()`/endpoint de búsqueda y confirmar que devuelve el documento maestro/manual definitivo, no papeleo del ayuntamiento (regla del criterio de aceptación de `proposal.md`).

### C6. Tests, alta en `run_all.py` y verificación manual

- [x] C6.1 Crear `tests/test_ingesta_documentos.py` con todos los casos de C1-C5 (RED de C4.3 en verde tras C4.4).
- [x] C6.2 Añadir `"test_ingesta_documentos.py"` a `tests/run_all.py`.
- [x] C6.3 Verificación manual: dejar un `.docx`, un `.pdf` y un `.xlsx` reales en `data/memory/inbox/`, correr el ciclo del scheduler contra el contenedor levantado, confirmar que los tres entran sin truncar y con metadatos.

---

## Regla transversal para las tres entregas

`.venv\Scripts\python.exe tests\run_all.py` debe salir **TODO VERDE** al
cierre de cada bloque, con la suite nueva de ese bloque ya dada de alta. Un
verde con `nexus_memoria_postgres` caído solo prueba sintaxis y camino de
respaldo por ficheros: cada bloque exige además su paso de «verificación
manual» (A5.3, B7.3, C6.3) con el contenedor arriba antes de considerarse
cerrado. No se toca `config/settings.json` ni `config/secrets.json` en
ningún bloque; todo umbral nuevo va a `config/umbrales.json`.

---

## Bloque B-bis — alcance real de la purga sobre las filas huérfanas

Añadido tras medir la base real: `previsualizar()` daba `filas_pg: 0` en todas
las categorías porque `filas_ligadas_a_nota()` ata fila y nota por la marca
`[fichero]` y solo 233 de 697 filas `knowledge` la llevan. Retirar las 35 notas
de la FP habría dejado 10 filas vivas y buscables.

- [x] B8.1 `memory.filas_sin_marca_origen()`: filas activas sin marca `[fichero]` ni columna `origen` (las 464 anteriores al bloque C).
- [x] B8.2 `purga.terminos()` + `purga.emparejar_por_contenido()`: segundo camino por vocabulario, sin LLM, umbrales en `config/umbrales.json` → `purga.emparejar_por_contenido`. Solo entra cuando la nota no tiene NINGUNA fila con marca; ante la duda, no casa.
- [x] B8.3 `purga.titulo_encabezado()`: la otra marca de origen (`# nombre-de-la-nota` en la primera línea), exacta y sin umbral — rescata filas que el vocabulario no puede juzgar (el CV salió del PDF con las letras separadas y solo deja cuatro términos).
- [x] B8.4 Cada fila llega a `previsualizar()` con SU motivo y cuenta en `filas_pg`; `aplicar()` retira exactamente los ids que se enseñaron. Arbitraje: se la queda la nota que mejor la explica.
- [x] B8.5 Tests en `tests/test_purga.py`: acierta con la fila propia, NO se lleva la ajena, no juzga filas sin materia, el encabezado rescata el CV, y la marca de origen sigue mandando.
- [x] B8.6 Purga ejecutada con las decisiones del usuario: `estudios-dam` (35 notas + 37 filas), `papeleo-personal` (12 notas + 12 filas, a la papelera, NO borrado definitivo) y `duplicados-exactos` (338 filas). Índice único `memories_huella_idx` creado tras confirmar la limpieza. Reversibilidad demostrada restaurando y volviendo a retirar un lote completo.
