# Exploración — Content OS como sistema de inteligencia de contenido de ciclo cerrado

- **Cambio**: `content-os-ciclo-cerrado`
- **Fase**: explore
- **Fecha**: 2026-08-01
- **Almacén de artefactos**: híbrido (este fichero + Engram `sdd/content-os-ciclo-cerrado/explore`)
- **Estado**: completa

## El problema

Content OS parece un producto de inteligencia de contenido, pero se comporta como
una carcasa con tema visual alrededor de texto libre de un LLM. Los módulos no
tienen relación causal entre ellos: el plan no nace de una estrategia, las ideas
no nacen de los datos, los aprendizajes no llevan evidencia, el guion no hereda
nada de la idea, y las métricas nunca cambian lo que el sistema cree.

Ciclo objetivo:

```
analizar datos -> detectar patrones -> crear hipótesis -> diseñar experimentos
-> generar contenido -> publicar y medir -> validar o descartar
-> actualizar la memoria -> replanificar
```

## Estado actual verificado

Todo lo de abajo se leyó en el código durante la exploración.

### Content OS es un cascarón alimentado con datos de demostración

| Qué | Evidencia |
| --- | --- |
| El plan de contenido es una semilla escrita a mano | `backend/core/contentos.py:32` `_seed()` |
| Ideas y guiones son un prompt suelto al LLM con solo un `topic` | `backend/core/contentos.py:292` `generate()` |
| La salida es texto libre, y encima truncado | `text.strip().split("\n")[0][:160]` |
| Los guiones no se persisten en absoluto | `/api/contentos/generate` devuelve `{ok, kind, text}` |
| Cifras a fuego presentadas como medidas | `retention = 48.6` (`:251`), `retention_delta: 4.1`, `reach_delta: 18.4` (`:277-278`), `experiments: 2` (`:279`) |
| Cae a datos de demostración de forma permanente | `_ig_creds()` (`:97`) no encuentra credenciales, así que `dashboard()` usa `_demo_metrics()` (`:245`) |
| Los «aprendizajes» son frases de la semilla con un campo `conf` tecleado a mano | `contentos.py:55-57`; `evidence.complete_pct` (`:259`) es una fórmula sobre esos strings |

Prueba física de generación sin fundamento: `data/contentos.json` contiene una
idea que anuncia calcetines deportivos (`#NexusSocks`), producida por
`generate("idea")` sin ningún anclaje de marca.

### El motor determinista ya existe — y está desconectado

`skills/instagram/` es la parte madura del proyecto, y `contentos.py` no importa
nada de ella.

- `skills/instagram/inteligencia.py` — sin LLM en absoluto. `patrones_gancho()`
  (`:112`) clasifica ocho tipos de gancho por regex y devuelve `{tipo, n,
  rendimiento (mediana), concluyente: n >= N_MINIMO}`; `outliers()` (`:238`) usa
  ≥ 2× la mediana de la propia cuenta; `ritmo()` (`:195`); `radiografia()`
  (`:312`) informa de `unidad`, `suficiente` y `aviso`. `N_MINIMO = 3` (`:29`).
- `skills/instagram/analisis.py` — intervalo de confianza de Wilson (`:559`) con
  `n_minimo_fiable: 30` y `confianza_z: 1.96` en `config/umbrales.json`.
  `panel()` (`:1122`) devuelve JSON estructurado por secciones.
- `analisis.py` tiene además una **cola editorial** determinista
  (`cola_editorial`) que ordena ideas por peso (veces preguntado, personas
  distintas, intención de compra, objeción). Eso ya cubre buena parte de lo que
  necesitaría un banco de oportunidades.
- Los competidores son legales y están implementados:
  `skills/instagram/scripts/ig.py:336` `business_discovery()` sobre la Graph API
  oficial.

**Matiz estadístico:** Wilson sirve para evidencia de proporción (sentimiento).
El par mediana + outlier es un instrumento distinto, para evidencia de
rendimiento. Una misma hipótesis no debe mezclar los dos.

### La memoria es un vertedero, y tiene un bug

- Postgres 16 + pgvector en el 5433 (`nexus_memoria_postgres`, BD `nexus_core`),
  esquema en `backend/core/memory.py:191` `_DDL`.
- **741 filas en `memories`, cero embeddings.** `memory.py:273-282` descarta todo
  vector cuya longitud no sea exactamente 768, y el `embed_model` configurado no
  produce 768. pgvector está instalado y sin usar; cada `recall()` cae al
  respaldo por `ILIKE`.
- 287 filas `knowledge`, con **39 duplicados exactos** de un hecho y **38** de
  otro. No hay deduplicación en el camino de Postgres.
- `data/memory/` tiene 84 notas, en torno al 95 % irrelevantes (BOE, CV, papeleo
  del ayuntamiento, apuntes de clase). Solo un fichero trata de Content OS.
- **No existe ningún endpoint de borrado ni de purga.**
- La ingesta filtra por extensión (`backend/core/scheduler.py:34`) y rechaza
  `.docx/.pdf/.xlsx`, aunque `backend/core/files_io.py:134` `read_any()` ya sabe
  leer los tres. Simplemente no están conectados entre sí.
- `/api/knowledge` (`backend/app.py:395`) no es la memoria: lista ficheros
  `SKILL.md`.

### Automatización

- **No hay cron.** Solo bucles de intervalo fijo: `scheduler_loop()`
  (`backend/core/scheduler.py:70`, tic de 5 s), `cycle_loop()` y
  `proactive_loop()` (`backend/core/background.py:66,87`). No existe ninguna
  entidad de tarea programada con `next_run`.
- n8n corre en localhost:5678 con `n8n_api_key` puesta.
  `skills/n8n_flows/skill.py` solo dispara webhooks (`:85`).
  `skills/autoprovision/skill.py:242` sí crea y activa un workflow por la API —
  un patrón reutilizable.
- `skills/google_workspace/skill.py` envía correo de verdad (`_send_gmail`,
  `:457`), además de Calendar y Tasks. **Google Drive no existe: ni scope, ni
  código, en ninguna parte del repositorio.**
- **Las credenciales de Instagram no están configuradas** (`ig_access_token`
  ausente, `ig_user_id` vacío). Hoy nada puede analizar datos reales.

### Incumplimiento de política ya en producción

`skills/content_os/skill.py:168` `inspire` descarga reels de terceros con yt-dlp
y los transcribe. Eso es scraping, y contradice la regla del propio proyecto que
`skills/instagram/` sí respeta. Está vivo hoy, al margen de este rediseño.

## Modelo de dominio

**Imprescindibles para el ciclo mínimo**: `BrandProfile` (hoy inexistente, que es
justo por lo que las ideas generadas se van a productos que no vienen a cuento),
`ContentItem`, `ContentBrief`, `Script` (persistido), `Publication`,
`MetricSnapshot`, `Observation`, `Hypothesis`, `Evidence`; más reparar el
`MemoryEntry` que ya existe.

**Pueden esperar o degradarse a atributo**: `AudienceSegment`, `ContentPillar`,
`ContentVariant`, `Offer`, `Insight`, `Recommendation`, `UserFeedback`.

### Estados del aprendizaje

| Estado | Cómo se calcula |
| --- | --- |
| OBSERVACIÓN | `concluyente: false` — ya lo produce `inteligencia.py` |
| HIPÓTESIS | se promueve cuando `n >= N_MINIMO` — ya está calculado |
| PROMETEDOR | hueco real hoy: un patrón minado sin experimento prospectivo |
| VALIDADO | exige `Experiment`, que no existe en ninguna parte del código |
| CONTRADICHO | computable con la misma comparación de mediana y outlier |
| OBSOLETO | necesita una política de caducidad, que irá a `config/umbrales.json` |

### Frontera con el LLM

La aritmética se queda en código determinista; el modelo solo puede interpretar y
redactar lo que el código ha calculado. El proyecto ya tiene una `REGLA
INVIOLABLE` en `backend/core/llm.py:776-799` que prohíbe inventarse cifras: hay
que extenderla a los prompts de Content OS. Un validador rechaza cualquier
conclusión cuyos números de respaldo no estén en la entrada calculada.

## Solape con un roadmap ya acordado

`docs/PETICIONES_ANALISIS.md` (30/07/2026; estaba en la raíz hasta que la fase 0
de `003-arquitectura-limpia` lo movió a `docs/`) es una orden de
trabajo que el usuario ya aceptó para `skills/instagram`. La fase 1 está hecha;
quedan las fases 2 a 6: onboarding y búsqueda de competidores, inteligencia de
competencia, histórico mensual y anual, **plan mensual con las ideas ya
desarrolladas (gancho, guion y CTA)**, e informes en PDF y PPT.

Su fase 5 es el mismo entregable que `planner` + `brief-and-script` de aquí, y su
fase 3 es la entrada que necesita el trabajo diario de competencia. Dos ediciones
independientes del mismo motor determinista es un riesgo real.

**DECISIÓN TOMADA (01/08/2026): el usuario eligió absorber ese roadmap dentro de
este SDD.** Las fases 2 a 6 pasan a ser cambios de este trabajo; el documento
queda como histórico. Una sola fuente de verdad y un solo motor.

## Descomposición recomendada

Regla de frontera: algo es P0 cuando **hoy es deshonesto**, no por el fichero en
el que vive. Por eso los KPI a fuego van a `content-os-honesty`, y no al rediseño
visual.

| Orden | Cambio | Depende de |
| --- | --- | --- |
| 1 | `content-os-honesty` — fuera cifras inventadas, estados vacíos honestos, aislar `inspire` | nada |
| 2 | `knowledge-purge-and-ingest` — arreglar el bug de los 768, deduplicar, purgar, conectar `read_any` al buzón, ingerir los documentos de Content OS | nada (paralelo) |
| 3 | `strategy-foundations` — BrandProfile y el brief estratégico persistente | 1 |
| 4 | `evidence-memory` — Observation/Hypothesis/Evidence con estados y caducidad | 3 |
| 5 | `learning-engine` — conectar el motor determinista a las observaciones; validador | 4 |
| 6 | `opportunity-bank` (absorbe la fase 2-3 del roadmap) | 5 |
| 7 | `planner` (absorbe la fase 5 del roadmap) | 6 |
| 8 | `brief-and-script` | 7 |
| 9 | `ux-redesign` | 8 |
| 10 | `automations-n8n` — trabajo diario, Drive, correo | 5, 8, credenciales IG |

## Riesgos

| Riesgo | Impacto |
| --- | --- |
| Sin credenciales de Instagram | No hay `Publication` ni `MetricSnapshot` reales. P0 debe funcionar en un modo de demostración etiquetado como tal, nunca presentado como medido. |
| `inspire` hace scraping y está vivo | Incumplimiento de política funcionando hoy, independiente de este trabajo. |
| Embeddings rotos | No bloquea el núcleo relacional, pero pgvector sigue decorativo hasta arreglarlo. |
| No hay cron | El trabajo diario debe reutilizar el patrón `tick % N == offset` o delegar la programación en n8n. |
| Colisión de regex en `skills_loader` entre `content_os` e `instagram` | Comparten vocabulario de Instagram y gana la primera que case. Auditar en `sdd-design`. |
| Purga de conocimiento | Entre las notas hay papeleo personal del usuario (CV, vida laboral, empadronamiento, tasas). Borrar exige confirmación explícita categoría por categoría. |

## Listo para propuesta

- **Sí**: `content-os-honesty`, `knowledge-purge-and-ingest`, `strategy-foundations`.
- El resto queda encadenado a sus dependencias según la tabla de arriba.
