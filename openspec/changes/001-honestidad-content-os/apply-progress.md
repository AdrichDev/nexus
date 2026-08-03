# Progreso de aplicación — `001-honestidad-content-os`

- **Fase**: apply (remediación acotada) · **Almacén**: openspec
- **Entra desde**: `verify-report.md` (veredicto FAIL, 2 CRITICAL), `specs/*/spec.md`, `design.md`, `tasks.md`
- **Modo**: Strict TDD · **Fecha**: 03/08/2026
- **Intento**: 2 de 2 (último) · **Presupuesto**: 413 líneas restantes de las 800 del objetivo

> Esto NO es trabajo nuevo. Es la remediación de los dos hallazgos CRITICAL del
> informe de verificación, con el alcance cerrado a esos dos y a lo estrictamente
> necesario para dejar la suite y la e2e en verde.

---

## Qué se ha arreglado

### CRITICAL-1 · El panel dejaba de fingir sobre el papel, pero seguía fingiendo en pantalla

**El problema**: `contentos._load()` llamaba a `_seed()` y **persistía en disco**
un calendario, unas ideas y unas inspiraciones INVENTADAS cuando
`data/contentos.json` no existía. Entradas con hora («Hoy · 19:30») y estado
(«Listo»), presentadas como el plan real del usuario, sin marca de origen y sin
pasar por `cosDato()`. Y a partir de esa primera escritura ya eran, a todos los
efectos, «datos del usuario».

El efecto colateral es lo que lo hacía invisible: los estados vacíos honestos
(`payload.vacios`) estaban bien construidos y el HUD sabía pintarlos
(`contentos.js:108,111,115` ya tienen su `|| <div class="empty">…`), pero **no se
llegaban a mostrar nunca**, porque las listas jamás estaban vacías. La spec lo
prohíbe literalmente: *«AND no se rellena con el contenido de `_seed()`»*.

**La solución**: `_seed()` devuelve `calendar`, `ideas` e `inspirations` vacíos.
No se ha construido ningún mecanismo nuevo: se reutiliza `payload.vacios`, que ya
existía, y el pintor `cosDato()`/`cosPanel()` del HUD, que ya sabía qué hacer.

**Dos decisiones que conviene dejar por escrito**:

1. **Los `learnings` de semilla SE QUEDAN.** No es un descuido. El escenario
   «Aprendizaje de semilla sin evidencia» de `content-os-honestidad` dice
   textualmente *«GIVEN un aprendizaje de `_seed()` sin `n`, periodo ni método»*:
   la spec presupone que existen, y ya salen rotulados «apunte tuyo, sin
   evidencia» con `origen: apunte_manual`, que era el arreglo de la Fase 2.
   Vaciarlos habría contradicho la spec y habría dejado el bucle de
   `test_evidencia_y_aprendizajes` iterando cero veces, o sea muerto.
2. **Lo ya escrito en `data/contentos.json` NO se toca.** La decisión 5 de la
   propuesta acordó no borrar lo ya persistido; no acordó seguir generándolo. Se
   deja de generar, y quien ya tenga el fichero con la semilla vieja lo conserva
   hasta que decida borrarlo él.

### CRITICAL-2 · Un test que no podía fallar

**El problema**: `tests/test_content_os_honestidad.py:397`

```python
check(not (ROOT / "data" / "inspiration").exists()
      or True, "data/inspiration/ no se toca en este cambio")
```

`X or True` evalúa a `True` pase lo que pase. Era la ÚNICA comprobación que
amparaba el requisito «Borrado de material heredado exige confirmación
explícita», y aparecía en el recuento como una de las 122 verdes. Si alguien
metía un `rmtree` en un intent de Content OS, la suite seguía verde.

**La solución**: fuera la tautología, y en su lugar `test_no_borra_heredado()`,
que hace lo que el propio informe pedía: siembra un fichero heredado en un
arenero, apunta el contenido de la carpeta, pasa por encima **los 7 intents de la
skill** (`connect`, `analytics`, `best`, `inspire`, `patterns`, `script`,
`ideas`) **más una orden desconocida** —el borrado accidental se cuela igual de
bien por la rama que nadie mira—, y exige tres cosas:

- el fichero heredado sigue existiendo;
- el conjunto de ficheros de la carpeta es EXACTAMENTE el de antes (ni uno menos,
  lo que cubre el borrado; ni uno más, lo que cubre *«no se crea ningún fichero
  nuevo en `data/inspiration/`»* del otro requisito);
- el contenido del fichero no ha cambiado.

---

## Ficheros tocados

| Fichero | Acción | Qué |
| --- | --- | --- |
| `backend/core/contentos.py` | Modificar | `_seed()`: `calendar`/`ideas`/`inspirations` vacíos y un docstring que explica por qué. `learnings` intactos |
| `tests/test_content_os_honestidad.py` | Modificar | Fuera la tautología de `:397`. Nuevos `test_instalacion_limpia()` y `test_no_borra_heredado()`, ambos registrados en `main()` |
| `tests/e2e/run_e2e.py` | Modificar | Nuevo `_siembra_plan_contenido()`, llamado desde `main()` |
| `openspec/changes/001-honestidad-content-os/tasks.md` | Modificar | Fase 7 con las tres tareas de remediación |
| `openspec/changes/001-honestidad-content-os/apply-progress.md` | Crear | Este documento |

### Por qué hubo que tocar la e2e

`flujo_contentos` comprobaba que cada publicación del plan se despliega con su
ficha de cuándo/formato/estado. Nunca sembraba `data/contentos.json`: el plan
salía **porque el backend se lo inventaba**. Es decir, la prueba verificaba que
el HUD sabe pintar una ficción. Al arreglar CRITICAL-1 la e2e cayó a 8/9 con
`el plan lista publicaciones (0)` y una excepción al buscar `.cos-cal-item`.

El arreglo honesto es que el plan lo ponga la PRUEBA, como haría el usuario:
`_siembra_plan_contenido()` escribe dos entradas de calendario en el arenero
desechable. Lo que se verifica sigue siendo lo mismo —el despliegue de la
ficha—, pero ahora sobre datos que alguien ha puesto a propósito.

---

## Evidencia del ciclo TDD

| Tarea | Fichero de test | Capa | Red de seguridad | RED | GREEN | TRIANGULACIÓN | REFACTOR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 7.1 CRITICAL-1 | `tests/test_content_os_honestidad.py` | Contrato | ✅ 122/122 antes de tocar nada | ✅ 8 fallos reales | ✅ 133 OK, 0 fallos | ✅ `add_item()` prueba que el vacío no es un payload roto | ➖ No hacía falta |
| 7.2 CRITICAL-2 | `tests/test_content_os_honestidad.py` | Integración | ✅ 133/133 | ✅ Por mutación: 3 fallos | ✅ 135 OK, 0 fallos | ✅ 7 intents + orden desconocida | ➖ No hacía falta |
| 7.3 e2e | `tests/e2e/run_e2e.py` | E2E | ✅ 9/9 antes de 7.1 | ✅ 8/9 tras 7.1 | ✅ 9/9 | ➖ Fixture, un solo camino | ➖ No hacía falta |

### RED de 7.1 (antes de tocar `contentos.py`)

```text
.venv/Scripts/python.exe tests/test_content_os_honestidad.py
· en una instalación limpia el panel dice que no hay nada, no se lo inventa
  FALLO: «calendar» llega relleno de semilla en una instalación limpia: [{'n': 1, 'title': 'El error que hace que tus automatizaciones fallen', …}]
  FALLO: «ideas» llega relleno de semilla en una instalación limpia: ['Gancho: «el error de automatización que te cuesta clientes»', …]
  FALLO: «inspirations» llega relleno de semilla en una instalación limpia: [{'src': '@creador.automatiza', …}]
  FALLO: data/contentos.json nace con contenido inventado: 'Hoy · 19:30'
  FALLO: data/contentos.json nace con contenido inventado: '@creador.automatiza'
  FALLO: data/contentos.json nace con contenido inventado: '5 flujos de n8n que todo negocio debería tener'
  FALLO: lo que escribe el usuario no llega al panel: ['Gancho: esto sí lo ha escrito el usuario', 'Gancho: «el error…», …]
  FALLO: y las demás secciones siguen vacías, que es la verdad
125 OK, 8 fallo(s)
```

### RED de 7.2 — verificación por mutación

Una aserción que sustituye a una tautología tiene que demostrar que puede fallar,
no basta con que pase. Se inyectó a propósito un borrado en el intent `ideas` de
`skills/content_os/skill.py`:

```python
if intent == "ideas":
    import shutil as _mutante_shutil
    _mutante_shutil.rmtree(INSP_DIR, ignore_errors=True)   # MUTACIÓN
```

```text
  FALLO: un intent de Content OS ha BORRADO el material heredado de data/inspiration/ sin pedir confirmación
  FALLO: data/inspiration/ ha cambiado de contenido al pasar los intents: ['creador-1.json'] → []
  FALLO: el fichero heredado sigue ahí, pero alguien le ha cambiado el contenido
132 OK, 3 fallo(s)
```

La mutación se revirtió acto seguido. `git diff -- skills/content_os/skill.py`
sale VACÍO: ese fichero queda exactamente como estaba.

### GREEN — estado final

```text
.venv/Scripts/python.exe tests/test_content_os_honestidad.py
→ 135 OK, 0 fallo(s)      (eran 122 antes de la remediación: +13 comprobaciones)

.venv/Scripts/python.exe tests/run_all.py
→ RESULTADO GLOBAL: TODO VERDE ✔

PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/e2e/run_e2e.py
→ RESULTADO E2E: 9/9 flujos passed — TODO VERDE ✔
    ✔ el plan lista publicaciones (2)
    ✔ y cada publicación se despliega con su ficha (0 → 65)
    ✔ con cuándo, formato y estado ('CUÁNDO\nHoy · 19:30\nFORMATO\nReel\nESTADO\nListo')

.venv/Scripts/python.exe -m compileall -q backend skills \
    tests/test_content_os_honestidad.py tests/e2e/run_e2e.py
→ exit 0
```

El único aviso de `compileall` es un `SyntaxWarning: invalid escape sequence '\('`
en `tests/e2e/run_e2e.py:347`, **preexistente** y ajeno a esta remediación: está
muy por encima de la única zona que se ha tocado (`:654` en adelante).

---

## Evidencia de unidad de trabajo

| Evidencia | Valor |
| --- | --- |
| Test enfocado y resultado exacto | `.venv/Scripts/python.exe tests/test_content_os_honestidad.py` → 135 OK, 0 fallos |
| Arnés en tiempo real y resultado exacto | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/e2e/run_e2e.py` → 9/9 flujos, uvicorn real sobre arenero desechable |
| Límite de reversión | Revertir `backend/core/contentos.py`, `tests/test_content_os_honestidad.py` y `tests/e2e/run_e2e.py` deja el cambio exactamente como lo dejó la entrega B. Nada más depende de esto |

---

## Líneas cambiadas

Contadas SOLO sobre los ficheros de esta remediación. El árbol de trabajo trae
además cambios sin commitear AJENOS a este cambio (`.gitignore`,
`skills/ai_media/`, `skills/tasks_board/`, `tests/test_frases_reales.py`) que
**no** se han tocado y **no** se cuentan aquí.

| Fichero | Añadidas | Borradas |
| --- | --- | --- |
| `backend/core/contentos.py` | 17 | 18 |
| `tests/e2e/run_e2e.py` | 25 | 0 |
| `tests/test_content_os_honestidad.py` | 108 | 2 |
| **Total** | **150** | **20** |

**Total real: 170 líneas** sobre las 413 disponibles. Quedan 243 sin consumir.
Por primera vez en este cambio la estimación no se ha quedado corta, y el motivo
es aburrido: el alcance estaba cerrado por escrito antes de empezar.

---

## Desviaciones del diseño

Ninguna. `design.md` no llegó a bajar el estado vacío honesto a una decisión de
implementación —de ahí el hueco que encontró la verificación—, así que no había
nada de lo que desviarse. La solución aplicada respeta D1 (la procedencia sigue
siendo el único camino), D3 (la demostración sigue viviendo en
`contentos_demo.py` y solo cubre MÉTRICAS, nunca contenido del usuario) y D4 (el
vocabulario de los estados vacíos sale de `config/umbrales.json`).

---

## Lo que queda FUERA a propósito

Estaba explícitamente fuera del alcance de esta remediación y sigue abierto en
`verify-report.md`:

- **WARNING-1** · `best[]/worst[].eng` y las series de `charts.*` viajan fuera
  del sobre; la lista blanca `_LIBRES` es la puerta por la que pasa.
- **WARNING-2** · La ruta «medido» no tiene test de regresión.
- **WARNING-3** · `tasks.md` (5.5) y `proposal.md` siguen pidiendo el `?v=NN`,
  que trabajo posterior y ajeno retiró con motivo documentado.
- **WARNING-4** · El bloque de aprendizajes no lleva chip `cosMarca()`.
- **SUGGESTION 1** · `_ok = True` muerto en `test_content_os_honestidad.py:130`.
- **SUGGESTIONS 2-4** · Duplicación de `n_minimo`, docstring de cabecera de
  `contentos.py` desactualizado, y `_LIBRES` sin comentario que la justifique.

---

## Estado

23/23 tareas originales + 3/3 de la Fase 7 de remediación. Suite completa en
verde, e2e 9/9, build limpio. **Sin commitear**: lo decide el usuario, y en este
proyecto las subidas van solo por `SUBIR_A_GITHUB.bat`.

> **Recordatorio operativo**: no se ha reiniciado la instancia de nexus del
> usuario. Esta remediación NO toca ningún `skill.py` (la mutación de prueba se
> revirtió y `git diff` de ese fichero sale vacío), así que `skills_loader` no
> necesita releer nada; pero sí toca `backend/core/contentos.py`, o sea que para
> ver el panel honesto en el puerto 8177 hay que reiniciar con `run.bat`.
