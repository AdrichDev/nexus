# Content OS — Honestidad Specification

## Purpose

Qué puede afirmar el panel de Content OS, con qué procedencia, y qué debe callar
cuando no hay datos. Sin credenciales de Instagram configuradas (estado real de
hoy), el panel MUST quedar honesto aunque quede casi vacío.

## Requirements

### Requirement: Procedencia obligatoria en cada cifra

Todo campo numérico devuelto por `GET /api/contentos` MUST viajar con su origen:
`medido` (Graph API), `demostración` (dataset ficticio etiquetado) o `sin_datos`
(no calculable hoy), y con el periodo cuando aplique.

#### Scenario: Sin credenciales configuradas

- GIVEN `ig_access_token` ausente e `ig_user_id` vacío
- WHEN se pide `GET /api/contentos`
- THEN cada campo numérico viaja como `{valor, origen, periodo}`
- AND `origen` es `demostración` o `sin_datos`, nunca `medido`

#### Scenario: Con Instagram conectado

- GIVEN credenciales válidas y la cuenta conectada
- WHEN se pide el payload
- THEN los campos que llegan de Graph API declaran `origen: medido` con periodo real
- AND los que no se pueden calcular (p. ej. retención sin duración de reel) declaran `sin_datos`

### Requirement: Ninguna cifra a fuego enmascarada como calculada

Ningún valor de `backend/core/contentos.py` MUST ser una constante literal
presentada como resultado calculado.

#### Scenario: Auditoría de literales

- GIVEN se audita `backend/core/contentos.py`
- WHEN se buscan los literales `48.6`, `4.1` y `18.4`
- THEN no aparecen en el módulo
- AND `retention`, `retention_delta`, `reach_delta` se calculan de datos reales o demo, o quedan `sin_datos`

### Requirement: KPI sin entidad no existe

El KPI «Experimentos» MUST desaparecer del payload y del HUD porque no existe
entidad `Experiment` en el proyecto. Cualquier otro KPI sin dato disponible MUST
mostrarse con `—` y un motivo textual, nunca omitirse en silencio ni sustituirse
por cero.

#### Scenario: Experimentos retirado

- GIVEN el payload de `/api/contentos`
- WHEN se inspecciona `kpis`
- THEN la clave `experiments` no existe
- AND la tarjeta «Experimentos» no se renderiza en el HUD

#### Scenario: KPI sin dato disponible

- GIVEN un KPI sin dato hoy (p. ej. `reach_delta` sin periodo previo)
- WHEN se renderiza el HUD
- THEN se muestra `—` junto al motivo
- AND nunca se muestra `0` como si fuera una medida

### Requirement: Ninguna conclusión sin evidencia

Un aprendizaje MUST NOT mostrar etiqueta de confianza (`consistente`,
`prometedora`, `observación`) salvo que lleve muestra (`n`), periodo y método.
Sin esos tres, se marca como apunte manual sin evidencia y no cuenta para
`evidence.complete_pct`.

#### Scenario: Aprendizaje de semilla sin evidencia

- GIVEN un aprendizaje de `_seed()` sin `n`, periodo ni método
- WHEN se sirve en el payload
- THEN aparece etiquetado «apunte tuyo, sin evidencia»
- AND no participa en el cálculo de `evidence.complete_pct`

#### Scenario: Salud de datos sin evidencia real

- GIVEN cero aprendizajes con evidencia completa
- WHEN se calcula `evidence.complete_pct`
- THEN el valor es `null` (o el campo se omite)
- AND nunca se presenta `0` como porcentaje de calidad de datos

### Requirement: Modo demostración marcado en cada bloque

Todo bloque del HUD que muestre datos de demostración (KPIs, gráficas, ranking,
próxima acción) MUST llevar su propia marca visible de demostración, no solo un
indicador en la cabecera.

#### Scenario: Panel sin conexión real

- GIVEN `connected: false`
- WHEN se pinta cada bloque del HUD
- THEN cada bloque (KPIs, gráficas, ranking, próxima acción) incluye su propia etiqueta de demostración

### Requirement: Estados vacíos honestos con vocabulario existente

Cuando no hay datos suficientes, el sistema MUST usar el vocabulario ya
establecido en `skills/instagram/` (`suficiente`, `aviso`, `concluyente`,
«Todavía no hay análisis») en vez de rellenar con contenido de semilla o
inventar términos nuevos.

#### Scenario: Secciones vacías en disco

- GIVEN `calendar`, `ideas` o `inspirations` vacíos en `data/contentos.json`
- WHEN se sirve el payload
- THEN cada sección vacía trae un texto «Todavía no hay…» leído de `config/umbrales.json`
- AND no se rellena con el contenido de `_seed()`

### Requirement: Regla inviolable extendida al generador

Los prompts de `contentos.generate()` MUST heredar la REGLA INVIOLABLE
(`backend/core/llm.py:776-799`): ninguna cifra puede salir del modelo si no
venía en la entrada calculada.

#### Scenario: Generación con cifra no fundamentada

- GIVEN una llamada a `generate("idea")` o `generate("script")`
- WHEN el LLM devuelve texto con una cifra que no estaba en el contexto pasado
- THEN esa respuesta se rechaza o se filtra antes de guardarse o mostrarse

### Requirement: Umbrales y textos configurables, no a fuego

Las etiquetas de origen, los mínimos de muestra y los textos de estado vacío de
Content OS MUST vivir en `config/umbrales.json` (sección `content_os`), nunca a
fuego en el código.

#### Scenario: Cambio de umbral sin tocar código

- GIVEN se edita un texto o umbral en `config/umbrales.json` y se reinicia nexus
- WHEN se sirve el payload o el HUD
- THEN el nuevo valor se refleja sin cambiar `contentos.py` ni `command.js`

### Requirement: Contrato del payload de `/api/contentos`

El payload MUST exponer: `connected` (bool), y por cada métrica de `kpis` un
objeto `{valor, origen, periodo}`; `learnings[]` con `{text, origen: medido|apunte_manual, n?, periodo?, metodo?, conf?}` donde `conf` solo aparece si `n`,
`periodo` y `metodo` están presentes; `evidence.complete_pct` nulable; y cada
sección vacía (`calendar`, `ideas`, `inspirations`) con su texto de estado vacío
cuando no tiene elementos. El HUD (`frontend/js/command.js`) MUST leer este
contrato para KPIs, gráficas, rankings y el anillo de datos.

#### Scenario: Contrato mínimo servido

- GIVEN cualquier estado de conexión
- WHEN se pide `GET /api/contentos`
- THEN el payload cumple la forma anterior sin campos numéricos sueltos sin envolver

#### Scenario: HUD consume el contrato nuevo

- GIVEN el payload con procedencia por métrica
- WHEN el HUD renderiza KPIs, gráficas y rankings
- THEN cada valor mostrado refleja su `origen`, y el bloque de demostración se marca si `origen: demostración`
