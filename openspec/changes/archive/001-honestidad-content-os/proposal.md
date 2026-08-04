# Propuesta — Content OS deja de fingir que sabe

- **Cambio**: `content-os-honesty`
- **Fase**: propose · **Almacén**: híbrido (este fichero + Engram `sdd/content-os-honesty/proposal`)
- **Depende de**: nada. Es el cambio 1 de `content-os-ciclo-cerrado`.
- **Presupuesto de revisión**: 800 líneas · **Estimación**: ~450-550

## Intención

Content OS le enseña a Adrian cifras que nadie ha medido y aprendizajes que nadie
ha comprobado, y no se distinguen de los que sí lo estarían. Hoy no hay
credenciales de Instagram (`ig_access_token` ausente, `ig_user_id` vacío), así
que **todo lo que se ve en el panel es semilla o demostración**, presentado con
la misma tipografía que un dato real. Ejemplos vivos: `retention = 48.6`
(`contentos.py:251`), `retention_delta: 4.1` y `reach_delta: 18.4` (`:277-278`),
y una tarjeta **«Experimentos: 2»** (`:279`) cuando en el proyecto no existe
ninguna entidad de experimento. La prueba física está en disco:
`data/contentos.json` guarda una idea que anuncia calcetines deportivos con
`#NexusSocks`.

Importa ahora porque la regla número uno del proyecto es no inventarse cifras
(`REGLA INVIOLABLE`, `backend/core/llm.py:776-799`) y el propio producto la
incumple. Además, cualquier cambio posterior del ciclo cerrado se construiría
encima de una interfaz que ya miente, y heredaría la mentira.

**Este cambio no añade inteligencia: quita la falsa.** El éxito es que el panel
sea aburrido y honesto — que diga «todavía no lo sé» en el estado real de hoy.

## Alcance

### Entra

1. **Cifras a fuego fuera.** Eliminar `retention`, `retention_delta`,
   `reach_delta` y `experiments` como valores literales. Lo que no se pueda
   calcular no se muestra.
2. **Procedencia en cada número.** Todo campo numérico de `/api/contentos` viaja
   con su origen: `medido` (Graph API), `demostración` o `sin_datos`, más el
   periodo cuando aplique.
3. **La demostración se ve a la legua.** El badge de `command.js:1519` es
   insuficiente: es un texto pequeño en la cabecera mientras las tarjetas de KPI,
   las gráficas y los rankings se pintan idénticos a los reales. La marca de
   demostración pasa a acompañar a cada bloque que la use.
4. **Aprendizajes sin evidencia, etiquetados como tales.** Las tres frases de
   `_seed()` (`:55-57`) llevan un `conf` tecleado a mano. Un aprendizaje solo
   puede mostrar confianza si lleva muestra (`n`), periodo y método detrás; si no,
   sale como apunte manual sin evidencia y **no cuenta** para ninguna salud de
   datos. `evidence.complete_pct` (`:259`) deja de ser una fórmula sobre strings.
5. **Estados vacíos honestos**, con el vocabulario que ya funciona en
   `skills/instagram/` (`suficiente`, `aviso`, `concluyente`, «Todavía no hay
   análisis»). Sin datos se dice que no hay datos, no se rellena con semilla.
6. **Regla extendida al generador.** Los prompts de `contentos.generate()`
   heredan la `REGLA INVIOLABLE`, y ninguna afirmación numérica puede salir del
   modelo si el número no venía en la entrada calculada.
7. **`inspire` deja de descargar contenido ajeno**
   (`skills/content_os/skill.py:168`, yt-dlp + whisper). Ver decisión abajo.
8. **Suite propia** `tests/test_content_os_honestidad.py`, registrada en
   `tests/run_all.py`.

### No entra (son cambios posteriores)

- Entidades nuevas (`Observation`, `Hypothesis`, `Experiment`, `BrandProfile`).
- Conectar el motor determinista de `skills/instagram/inteligencia.py`.
- Planificador, banco de oportunidades, guiones persistidos.
- Rediseño visual y automatizaciones con n8n.
- Conseguir credenciales de Instagram. Este cambio debe dejar la app honesta
  **en el estado sin credenciales**, que es el estado real de hoy.
- Purgar `data/contentos.json` sin preguntar (ver R6).

## Reglas de negocio

| # | Regla |
| --- | --- |
| R1 | Ninguna cifra sin procedencia: origen (`medido`/`demostración`/`sin_datos`) y periodo. |
| R2 | Ninguna conclusión sin evidencia: sin `n`, periodo y método no hay etiqueta de confianza. |
| R3 | Un dato de demostración nunca se presenta como medido, en ningún bloque. |
| R4 | Un KPI sin entidad detrás no existe: «Experimentos» se retira hasta que exista `Experiment`. |
| R5 | Umbrales, etiquetas y textos de estado vacío van a `config/umbrales.json`, nunca a fuego. |
| R6 | Solo lectura por defecto: limpiar `data/contentos.json` exige confirmación explícita del usuario y copia previa. |
| R7 | Nada de scraping de terceros; Instagram por Graph API (`business_discovery`). |

## Decisión sobre `inspire` — recomendación

**Desactivar la descarga, conservar lo ya guardado, preguntar la purga.**

- *Aislar tras confirmación* se descarta: la regla del proyecto no es de
  seguridad sino de política. Que el usuario diga «sí» no convierte en legítimo
  descargar el reel de otra persona; solo traslada la responsabilidad.
- *Retirar código y datos de golpe* se descarta como acción unilateral: las
  transcripciones de `data/inspirations/` son datos en disco, y borrarlas cae de
  lleno en R6.
- Por tanto: `inspire` responde explicando la política y reencamina a la vía
  legal (`business_discovery`); `_download_and_transcribe` deja de invocarse;
  `patterns` y `script` siguen leyendo lo heredado pero avisan de su origen; la
  retirada del código muerto y la purga se proponen al usuario, no se ejecutan.

## Enfoque

Cambio de superficie, no de arquitectura. `contentos.dashboard()` pasa de
ensamblar un payload plano a devolver cada métrica con su procedencia; el HUD
aprende a pintar tres estados por bloque (medido / demostración / sin datos) en
vez de uno. Ninguna tabla nueva, ningún esquema nuevo, ninguna dependencia nueva.
Todo el vocabulario y los umbrales salen de `config/umbrales.json`.

## Áreas afectadas

| Área | Impacto | Qué cambia |
| --- | --- | --- |
| `backend/core/contentos.py` | Modificado | KPIs a fuego fuera; procedencia por métrica; `_seed()` sin `conf` inventado; `complete_pct` con evidencia real; prompts con la regla |
| `frontend/js/command.js` | Modificado | Tarjeta «Experimentos» fuera; marca de demostración por bloque; estados vacíos honestos |
| `frontend/css/command.css` | Modificado | Estilos de estado vacío y de bloque en demostración |
| `frontend/index.html` | Modificado | Subir `?v=NN` en líneas 9 y 126 (cache-busting manual) |
| `config/umbrales.json` | Modificado | Sección `content_os`: etiquetas de origen, mínimos de muestra, textos de estado vacío |
| `skills/content_os/skill.py` | Modificado | `inspire` sin descarga; aviso de origen en `patterns`/`script` |
| `tests/test_content_os_honestidad.py` | Nuevo | Suite de honestidad |
| `tests/run_all.py` | Modificado | Registro de la suite |

## Capacidades

`openspec/specs/` está vacío: todo es nuevo.

### Capacidades nuevas
- `content-os-honestidad`: qué puede afirmar el panel, con qué procedencia y qué
  debe callar cuando no hay datos.
- `content-os-origen-contenido`: de dónde puede venir el material de inspiración
  (Graph API y aportación del usuario; nunca descarga de terceros).

### Capacidades modificadas
- Ninguna.

## Criterios de aceptación (verificables)

- [ ] Sin credenciales, `GET /api/contentos` no devuelve **ningún** número sin
      su campo de origen; `origen` ∈ {`medido`, `demostración`, `sin_datos`}.
- [ ] Los literales `48.6`, `4.1` y `18.4` no aparecen en `backend/core/contentos.py`
      (comprobación por lectura del módulo en la suite).
- [ ] La clave `experiments` no existe en el payload y la tarjeta no existe en el HUD.
- [ ] Con cero aprendizajes con evidencia, `evidence.complete_pct` devuelve `null`
      (o desaparece), nunca `0` presentado como porcentaje de calidad.
- [ ] Ningún aprendizaje sale con etiqueta de confianza sin `n`, periodo y método.
- [ ] Cada sección del HUD sin datos muestra un texto de «todavía no hay…» en vez
      de contenido de semilla.
- [ ] `inspire` no ejecuta yt-dlp en ningún camino, y su respuesta cita la vía Graph API.
- [ ] `tests/test_content_os_honestidad.py` existe, está listado en `tests/run_all.py`
      y `.venv\Scripts\python.exe tests\run_all.py` sale TODO VERDE.
- [ ] Ningún umbral ni etiqueta nueva escrito a fuego: todo en `config/umbrales.json`.
- [ ] `frontend/index.html` con `?v=NN` incrementado en las líneas 9 y 126.

## Riesgos

| Riesgo | Prob. | Mitigación |
| --- | --- | --- |
| El panel queda casi vacío y parece roto | Alta | Es el resultado buscado; los estados vacíos explican qué falta (conectar Instagram) y qué se sabrá al conectarlo |
| Se rompe el HUD por cambio de contrato del payload | Media | La suite comprueba el payload completo; e2e de la pestaña Content OS |
| Olvidar el `?v=NN` y creer que el cambio no funciona | Media | Criterio de aceptación explícito |
| Tentación de borrar `data/contentos.json` para «limpiar» | Media | R6: confirmación explícita y copia previa; no entra en alcance |
| Colisión de regex entre `content_os` e `instagram` al tocar `skill.py` | Baja | Solo se cambia el cuerpo del intent, no su patrón; se audita en `sdd-design` |
| Perder la vía de inspiración sin sustituto | Media | Se conserva lo heredado y se reencamina a `business_discovery`; la vía nueva llega en `opportunity-bank` |

## Plan de reversión

Cambio en ficheros, sin migración ni esquema: `git revert` del commit deja el
comportamiento anterior intacto. `data/contentos.json` no se toca en este cambio,
así que no hay datos que restaurar. Si se revierte, hay que bajar también el
`?v=NN` de `frontend/index.html` o forzar recarga dura del HUD.

## Dependencias

- Ninguna externa. No requiere credenciales de Instagram, ni Postgres, ni n8n.
- Reiniciar nexus tras tocar `skills/content_os/skill.py` (`skills_loader` lee las
  carpetas solo al arrancar).

## Ronda de preguntas de propuesta

No he podido preguntar directamente (soy fase delegada). Estas decisiones son de
producto y cambian el alcance; la suposición por defecto va marcada.

1. **`inspire`**: ¿confirmas la recomendación (desactivar la descarga, conservar
   lo ya transcrito con aviso de origen) o prefieres retirar el intent y purgar
   `data/inspirations/` ahora, con tu confirmación explícita?
   *Por defecto: desactivar y conservar.*
2. **Modo demostración**: ¿lo mantenemos con marca visible en cada bloque, o
   preferís que sin credenciales el panel salga completamente vacío y solo
   explique cómo conectar Instagram? *Por defecto: mantener, marcado.*
3. **Aprendizajes de semilla**: ¿los dejamos visibles etiquetados como «apunte
   tuyo, sin evidencia», o `_seed()` deja de traer aprendizajes y la sección
   arranca vacía? *Por defecto: dejarlos etiquetados, sin contar para la salud
   de datos.*
4. **KPIs sin dato**: ¿la tarjeta desaparece o se queda con un «—» y el motivo?
   *Por defecto: «Experimentos» desaparece (no existe la entidad); el resto se
   queda con «—» y motivo.*
5. **`data/contentos.json`**: la idea de los calcetines sigue ahí. ¿Quieres que
   un cambio posterior te ofrezca revisarla y borrarla una a una, o la dejamos
   como testigo del problema? *Por defecto: se deja; nada se borra aquí.*

---

## Decisiones resueltas (01/08/2026)

Las cinco quedan **confirmadas en su valor por defecto**. Se resolvieron en la
conversación con el usuario, que delegó estas cinco por tener respuesta razonable.
Ya no son suposiciones: son el alcance acordado.

| # | Decisión |
| --- | --- |
| 1 | `inspire`: se desactiva la descarga y se conserva lo ya transcrito, con aviso de origen. **No se borra nada** en este cambio. |
| 2 | Modo demostración: se mantiene, pero **marcado en cada bloque**, no solo con un badge en la cabecera. Un panel vacío no enseña al usuario qué ganaría conectando la cuenta. |
| 3 | Aprendizajes de semilla: visibles, etiquetados como «apunte tuyo, sin evidencia», y **sin contar para la salud de datos**. |
| 4 | KPIs sin dato: **«Experimentos» desaparece** —no existe la entidad, así que el número era ficción entera—; el resto se queda con «—» y el motivo. |
| 5 | `data/contentos.json`: se deja como testigo. Aquí no se borra nada. |

### Sobre `inspire`, que es la única con carga política

Se acepta el razonamiento de la fase de propuesta: **«nada de scraping» es una
política del proyecto, no una salvaguarda técnica que el usuario pueda levantar.**
Que el dueño del proyecto autorice descargar el reel de otra persona no lo
convierte en legítimo; solo traslada la responsabilidad. Por eso la opción de
«aislarlo tras confirmación» se descarta: no existe una confirmación que haga
correcto el scraping.

El intent pasa a explicar la política y reencaminar a `business_discovery`, que es
la vía oficial y ya está implementada en `skills/instagram/scripts/ig.py:336`.

El material heredado en `data/inspiration/` **no se toca**: retirarlo cae bajo la
regla de borrado con confirmación explícita, y se propondrá aparte. Mientras
exista, `patterns` y `script` seguirán pudiendo leerlo, pero avisando de su
origen.
