# Diseño — `001-honestidad-content-os`

- **Fase**: design · **Almacén**: híbrido (este fichero + Engram `sdd/001-honestidad-content-os/design`)
- **Entra desde**: `proposal.md`, incluida la sección «Decisiones resueltas» (01/08/2026), que manda.
- **Idioma de artefactos**: español con tildes, por decisión explícita del usuario.

## Enfoque técnico

Un solo mecanismo, no parches: **ninguna cifra viaja suelta**. Cada número sale de
`backend/core/contentos.py` dentro de un sobre `dato` con su procedencia, y el HUD
tiene un único pintor que **se niega a pintar** lo que no traiga sobre. Los datos de
demostración dejan de ser un `or` silencioso y pasan a vivir en un módulo propio que
se puede leer, auditar y algún día borrar de un tirón. El vocabulario y los textos
salen de `config/umbrales.json` y viajan en el payload, para que tampoco el
JavaScript tenga nada a fuego.

No hay tabla nueva, ni esquema, ni dependencia. Es superficie.

---

## Decisiones de arquitectura

### D1 · Procedencia: un sobre, no un campo hermano

**Elegido**: módulo nuevo `backend/core/procedencia.py` con la fábrica

```python
def dato(valor, origen, periodo=None, delta=None, n=None, aviso=""):
    """origen ∈ {"medido", "demostración", "sin_datos"}. Valida el origen."""
    return {"valor": valor, "origen": origen, "periodo": periodo,
            "delta": delta, "n": n, "aviso": aviso}
```

`delta` es a su vez un sobre o `None`. Un origen fuera del conjunto **revienta**
(`ValueError`): no se puede marcar mal por descuido, solo dejando de usar la fábrica
—y de eso se ocupa el test de barrido.

| Opción | Coste | Veredicto |
| --- | --- | --- |
| Campo hermano (`retention_origen`) | Se olvida uno y nadie se entera; duplica claves | Rechazada |
| Tipo/dataclass | Al serializar a JSON se pierde el tipo; cero garantía en el HUD | Rechazada |
| **Sobre uniforme** | Un nivel más de anidamiento en el payload | **Elegida** |

**Cómo se hace cumplir, en tres capas**:

1. **Origen**: la fábrica valida el valor de `origen`.
2. **Barrido** (`tests/test_content_os_honestidad.py`): recorre el payload entero y
   falla si encuentra un `int`/`float` fuera de un sobre o de una serie de gráfica,
   salvo lista blanca explícita (`analyzed`, contadores de `evidence`, `n`).
3. **HUD**: `cosDato(d)` es el único camino a la pantalla. Si `d` no trae `origen`,
   pinta `—` y el rótulo «sin procedencia», nunca el número. Fallo cerrado.

`procedencia.py` aloja también el lector de `config/umbrales.json` (sección
`content_os`), siguiendo el patrón ya existente en `backend/core/remote.py:54`
`_carga_umbrales_red()`. **No** se importa `skills/instagram/analisis.py:99`
`cargar_umbrales()`: el backend no depende de una skill (inversión de capas). Se
asume la duplicación consciente de un lector de 15 líneas.

### D2 · Contrato de `/api/contentos` — qué se rompe

Rompe a propósito, y todo lo que rompe está en `frontend/js/command.js`
`mountContentOS()` (`:1477-1605`).

| Clave | Antes | Ahora | Rompe en |
| --- | --- | --- | --- |
| `kpis.followers`, `.reach_month`, `.media_count` | número | sobre `dato` | `:1530-1531` |
| `kpis.retention` | `48.6` a fuego | sobre con `valor: null`, `origen: "sin_datos"`, aviso: la Graph API no da tiempo de visualización sin cuenta | `:1532` |
| `kpis.*_delta` | `18.4`, `4.1` a fuego | `delta` dentro del sobre padre, o `null` | `:1482` `delta()` |
| `kpis.experiments` | `2` | **desaparece** | `:1533` (tarjeta fuera) |
| `evidence.complete_pct` | fórmula sobre strings | `null` si no hay evidencia | `:1540`, `:1545` (anillo) |
| `learnings[]` | `{text, conf}` | `{text, origen, evidencia, conf}`; `conf` solo con evidencia | `:1508-1511`, `confCls` |
| `best` / `worst` | lista plana | `{origen, unidad, filas[]}` | `:1512-1513`, `:1558` |
| `charts.*` | series planas | `{origen, labels, values}` | `:1579-1587` |
| `next_action` | texto sin marca | `+ origen` (en demo, es una recomendación de demostración) | `:1521-1528` |
| `modo`, `vocabulario` | — | **nuevos**, top-level | consumo nuevo |

`connected`, `calendar`, `ideas`, `inspirations`, `username`, `operator` no cambian.
`POST /api/contentos/generate` y `/add` no cambian de forma.

**Toca en el HUD**: `cosKpi()` (`:1606`) pasa a recibir el sobre entero; se retira la
cuarta tarjeta; cada `cosPanel` recibe un `extra` con la marca de origen (chip
«demostración» / «todavía no lo sé») en la propia cabecera de la sección, que es lo
que exige la decisión 2 del usuario. `frontend/css/command.css` añade `.cos-marca`,
`.cos-marca.demo`, `.cos-marca.nada` y el estado apagado del anillo. **`?v=28` → `?v=29`
en `frontend/index.html:9` y `:126`.**

### D3 · Dónde vive la demostración

**Elegido**: fichero propio `backend/core/contentos_demo.py`, y en `dashboard()` una
rama explícita en vez del `or` silencioso de `contentos.py:245`:

```python
metricas = await _ig_metrics()
origen = MEDIDO if metricas else DEMOSTRACION
metricas = metricas or contentos_demo.metricas()
```

`contentos_demo.metricas()` estampa `origen` en lo que devuelve, así que el sobre no
depende de que alguien se acuerde río abajo. Aislarlo hace posible el criterio
«ningún literal de métrica en `contentos.py`» y deja la retirada futura en un `rm`.
*Rechazado*: eliminarlo en favor de estados vacíos (lo prohíbe la decisión 2 del
usuario: un panel vacío no enseña qué se gana conectando la cuenta).

### D4 · Se reutiliza el vocabulario de `skills/instagram/`, no se inventa otro

`inteligencia.py:312` `radiografia()` ya devuelve `unidad`, `suficiente`, `aviso`, y
`patrones_gancho()` marca `concluyente` por fila. El bloque `evidence` adopta esa
misma forma:

```json
"evidence": {"unidad": "aprendizajes con evidencia", "n": 0, "suficiente": false,
             "aviso": "Ningún aprendizaje tiene muestra detrás: no hay salud de datos que medir.",
             "complete_pct": null, "consistent": 0, "promising": 0,
             "observations": 0, "apuntes": 3}
```

Un aprendizaje solo lleva `conf` si trae `evidencia = {n, periodo, metodo}` completa;
si no, sale con `origen: "apunte"` y el rótulo «apunte tuyo, sin evidencia», y **no
suma** en `complete_pct` (decisión 3). `_seed()` (`contentos.py:55-57`) y
`add_item("learning", …)` (`:87`) dejan de escribir `conf`.

El mínimo de muestra va a `config/umbrales.json` → `content_os.n_minimo: 3`,
espejo del `N_MINIMO` de `inteligencia.py:29`. **Riesgo asumido**: son dos números que
pueden separarse; se documenta en el propio JSON y el test lo comprueba.

### D5 · La `REGLA INVIOLABLE`, extendida y verificada

**Hallazgo**: `backend/core/llm.py:745` hace `base = system or SYSTEM_PROMPT…` pero
la regla se concatena **después** (`:776-805`), así que ya viaja aunque se pase un
`system` a medida. `contentos.generate()` la hereda hoy. Lo que falta es la cláusula
propia y la verificación.

1. `llm.py` expone `REGLA_CONTENT_OS`: «solo puedes usar las cifras del bloque DATOS
   que te llega; si el bloque va vacío, no hables de rendimiento».
   `contentos.generate()` pasa `system=` con esa cláusula y adjunta el bloque DATOS
   calculado (vacío hoy, sin credenciales).
2. **Validador determinista** `procedencia.sin_cifras_inventadas(texto, permitidas)`:
   extrae los números del texto del modelo y rechaza los que no estén en la entrada
   y superen `content_os.validador.magnitud_minima` (umbrales, valor 100) o lleven
   decimal, `%` o separador de millares. Los enteros pequeños («3 pasos», «2 seg»)
   pasan. Si rechaza, la respuesta honesta sustituye al texto; nada se publica a
   medias.
3. **Verificación en suite**: (a) `_build_messages(…, system="lo que sea")` sigue
   conteniendo `REGLA INVIOLABLE` —es la regresión que rompería todo en silencio—;
   (b) el validador tumba `"tus reels tienen 48,6 % de retención"` y deja pasar
   `"3 golpes y un CTA"`.

### D6 · `inspire`, sin romper `patterns` ni `script`

- **La regex se queda tal cual** (`skill.py:34-36`). Si se retira, la frase cae al
  planificador de `brain.py`, que es exactamente donde se inventan cosas. El intent
  sigue capturando y ahora explica la política y reencamina: «analiza la cuenta de
  instagram de <cuenta>» → `skills/instagram` `ig_competencia` → `business_discovery`
  (`skills/instagram/scripts/ig.py:336`).
- `_download_and_transcribe` (`:60`) **deja de invocarse** y pasa a fallo cerrado:
  `raise RuntimeError("vía retirada por política; pendiente de borrado con tu confirmación")`
  como primera línea. No se borra —eso es una propuesta aparte, R6—, pero deja de ser
  una vía dormida.
- `patterns` (`:198`) y `script` (`:214`) siguen leyendo `data/inspiration/*.json`.
  Se les antepone `_aviso_origen()`: «esto viene de transcripciones descargadas antes
  de retirar esa vía; no se va a ampliar». `data/inspiration/` **no se toca**.
- Recordatorio operativo: tras tocar la skill hay que reiniciar (`skills_loader` lee
  las carpetas solo al arrancar).

### D7 · Auditoría de colisión de regex — sí hay solape real

`skills_loader.py:83` usa `rx.search` sin anclar, `IGNORECASE`, y `:42` recorre las
carpetas por orden alfabético: **`content_os` gana siempre a `instagram`**.

| Frase | Casa en | Gana | ¿Real? |
| --- | --- | --- | --- |
| «cómo va el instagram» | `content_os.analytics` + `instagram.ig_estado` | `content_os` | **Sí**, preexistente |
| «analiza este reel de @creador …» | `content_os.inspire` + `instagram.ig_competencia` | `content_os` | **Sí**, preexistente |
| «mis mejores reels» | solo `content_os.best` (`ig_listar` exige `mis (últimos)? reels` seguido) | — | No |
| «dame ideas de reels» | solo `content_os.ideas` | — | No |
| «conecta mi instagram» / «conecta mi cuenta de instagram» | `content_os.connect` / `instagram.ig_descubrir` | cada una la suya | No, pero **dos puertas de alta distintas** para la misma intención |
| «analiza los patrones» / «genera un guion sobre …» | solo `content_os` | — | No |

**Consecuencia para este cambio**: ninguna regex se toca, pero los dos solapes reales
obligan a que el cuerpo ganador diga la verdad y ceda el paso.

**Hallazgo nuevo, y va dentro del alcance**: `skills/content_os/skill.py:126-130`, la
rama de `analytics` sin credenciales, escupe **«12.840 seguidores, 184,2K de alcance,
retención media 48,6 %»** como «ejemplo». Es la misma mentira de `contentos.py:251`
pero por el canal de chat, y la propuesta no la había visto. Se sustituye por la
respuesta honesta al estilo `ig_estado`: qué falta y cómo se conecta. Sin este arreglo
el cambio deja la mentira viva justo donde el usuario más habla.

---

## Flujo de datos

```
Graph API ──┐
            ├─► _ig_metrics() ─► ¿hay? ─sí─► origen = medido
contentos_demo.metricas() ◄─no──┘           origen = demostración
            │
            ▼
        dashboard() ──► dato(valor, origen, periodo, delta)  [procedencia.py]
            │                    ▲
   config/umbrales.json ─────────┘ (n_minimo, etiquetas, textos, magnitud_minima)
            │
            ▼
   payload {modo, vocabulario, kpis, evidence, charts, …}
            │
            ▼
   command.js  cosDato(d) ──► ¿d.origen? ─no─► «—  sin procedencia»
                                  └──sí──► valor + chip de origen por bloque

generate(kind) ──► prompt + DATOS + REGLA_CONTENT_OS ──► LLM
                          └─► sin_cifras_inventadas() ─rechaza─► respuesta honesta
```

## Cambios de fichero

| Fichero | Acción | Qué |
| --- | --- | --- |
| `backend/core/procedencia.py` | Crear | `dato()`, constantes de origen, lector de umbrales, `sin_cifras_inventadas()` |
| `backend/core/contentos_demo.py` | Crear | `_demo_metrics()` movido y estampado con su origen |
| `backend/core/contentos.py` | Modificar | `dashboard()` con sobres; fuera `48.6`/`4.1`/`18.4`/`experiments`; `_seed()` y `add_item()` sin `conf`; `evidence` al estilo `radiografia()`; `generate()` con `system` y validador |
| `backend/core/llm.py` | Modificar | `REGLA_CONTENT_OS` exportada junto a la regla existente |
| `skills/content_os/skill.py` | Modificar | `analytics` sin cifras inventadas; `inspire` reencamina; `_download_and_transcribe` a fallo cerrado; aviso de origen en `patterns`/`script` |
| `frontend/js/command.js` | Modificar | `cosDato()`, `cosKpi()` con sobre, marca por bloque, estados vacíos, anillo apagado, tarjeta «Experimentos» fuera |
| `frontend/css/command.css` | Modificar | `.cos-marca`, `.cos-marca.demo`, `.cos-marca.nada`, anillo sin dato |
| `frontend/index.html` | Modificar | `?v=28` → `?v=29` en `:9` y `:126` |
| `config/umbrales.json` | Modificar | Sección `content_os`: `n_minimo`, `etiquetas`, `textos`, `validador.magnitud_minima` |
| `tests/test_content_os_honestidad.py` | Crear | Suite propia con `check(cond, msg)` |
| `tests/run_all.py` | Modificar | Registro en la lista de `:61` |

## Estrategia de prueba

Scripts propios con `check(cond, msg)`, **nunca pytest**, ejecutados con
`.venv\Scripts\python.exe`.

| Capa | Qué se prueba | Cómo |
| --- | --- | --- |
| Unidad | `dato()` rechaza un origen inválido | `try/except ValueError` |
| Unidad | `sin_cifras_inventadas()` tumba «48,6 %» y deja pasar «3 golpes» | Cadenas fijas |
| Unidad | Un aprendizaje sin `evidencia` no lleva `conf` ni suma en `complete_pct` | `dashboard()` con `_seed()` |
| Contrato | Barrido del payload: ningún número fuera de sobre; `experiments` ausente; `complete_pct is None` | `asyncio.run(dashboard())` |
| Contrato | `48.6`, `4.1`, `18.4` no aparecen en el texto de `contentos.py` | Lectura del módulo |
| Prompt | `_build_messages(…, system=…)` conserva `REGLA INVIOLABLE` | Inspección de mensajes |
| Enrutado | «cómo va el instagram» y «analiza este reel …» caen en `content_os`, y la respuesta cita la vía Graph API | `skills_loader.route()` |
| Política | Cero llamadas a `_download_and_transcribe` desde `handle()`; invocarla lanza `RuntimeError` | AST + llamada directa |
| Umbrales | `content_os` existe en `umbrales.json` y cambiarlo cambia la salida | Carga con `extra` |
| E2E | La pestaña sigue teniendo ≥6 secciones plegables | `tests/e2e/run_e2e.py` `flujo_contentos` (sin cambios: no afirma nada sobre KPIs) |

## Matriz de amenazas

Aplica solo la fila de **enrutado**: `skills_loader` decide qué skill contesta y una
regex ganadora de más puede secuestrar frases ajenas. Cubierta por D7 y por la prueba
de enrutado (dos frases con solape real verificadas). Sin shell nuevo, sin subproceso
nuevo —al contrario, se retira la invocación de `yt-dlp`—, sin automatización de
VCS/PR, sin clasificación de ficheros ejecutables.

## Migración y despliegue

Sin migración. `data/contentos.json` y `data/inspiration/` no se tocan (R6). Revertir
es `git revert` **más** bajar el `?v=29` o forzar recarga dura del HUD. Hay que
reiniciar nexus con `run.bat` tras tocar la skill.

## Presupuesto de revisión

**Estimación revisada: 600-700 líneas cambiadas** (backend ~240, HUD ~130, skill ~60,
umbrales ~35, suite ~190, registro y cache-busting ~5). Sigue **por debajo de las 800**
acordadas, pero **por encima del 450-550 que estimaba la propuesta**: lo añaden el
módulo `procedencia.py`, el aislamiento de la demostración y el arreglo de
`skill.py:126-130` que la propuesta no había detectado. Si al implementar se pasa de
800, el corte natural son dos entregas encadenadas: **(1)** backend + contrato + suite
de contrato, **(2)** HUD + CSS + `?v=NN` + suite de enrutado y política.

## Preguntas abiertas

- [ ] `retention` se queda como tarjeta con «—» y motivo (decisión 4 del usuario). Si
      al verla vacía prefieres que desaparezca como «Experimentos», es un ajuste de
      dos líneas en el HUD, no de diseño.
- [ ] `content_os.n_minimo` duplica el `N_MINIMO = 3` de `inteligencia.py:29`.
      Unificarlos exige tocar `skills/instagram`, que está fuera de alcance; se propone
      para `learning-engine`.
