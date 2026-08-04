# Informe de verificación — `001-honestidad-content-os`

- **Fecha**: 03/08/2026
- **Fase**: verify (re-verificación tras remediación)
- **Veredicto**: **PASS con avisos**
- **Sustituye a**: la verificación previa del 03/08/2026 (FAIL, 2 CRITICAL),
  sha256 `3c76200506431eaa4390352651ab244547add3a794d6a5d8254ee8f863b2fbc6`,
  conservada en Engram bajo `sdd/001-honestidad-content-os/verify-report`.

## Cómo se verificó, y por qué importa

Esta verificación la ejecutó el orquestador **en línea**, no un actor delegado.
El actor `sdd-verify` se lanzó dos veces y devolvió resultado **vacío** en ambas,
sin ejecutar una sola prueba: el informe anterior quedó intacto byte a byte
(20.936 bytes, mtime 05:15, mismo sha256) y el árbol de trabajo sin cambios. Los
dos intentos están registrados como `interrupted` en el ledger nativo.

Esto no se anota como defecto del actor: el mismo agente funcionó dos veces antes
en la misma sesión. Sin evidencia de fallo determinista, se registra el hecho
observado y no una causa supuesta.

## Ejecución de tests

| Comprobación | Comando | Resultado |
| --- | --- | --- |
| Suite completa | `.venv/Scripts/python.exe tests/run_all.py` | **TODO VERDE** |
| End-to-end | `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/e2e/run_e2e.py` | **9/9 flujos** |

Sin fallos, sin reintentos consumidos, `config/settings.json` intacto.

## CRITICAL-1 — CERRADO

**Era**: en instalación limpia, `_load()` llamaba a `_seed()` y persistía en disco
calendario, ideas e inspiraciones inventados —con hora («Hoy · 19:30») y estado
(«Listo»)—, sin marca de origen y sin pasar por `procedencia.dato()`, tapando
para siempre los estados vacíos honestos de `payload.vacios`.

**Verificado ejecutando**, no leyendo código: se redirigió `contentos.STORE` a un
arenero temporal inexistente y se llamó a `dashboard()`.

| Comprobación | Resultado |
| --- | --- |
| `calendar` persistido en disco | `[]` |
| `ideas` persistido en disco | `[]` |
| `inspirations` persistido en disco | `[]` |
| Estados vacíos honestos presentes | `calendar`, `ideas`, `inspirations`, `learnings` |
| `learnings` conservados | 3 apuntes |
| `learnings` con etiqueta de confianza inventada | ninguno |

**Sobre los `learnings`**: se conservan a propósito y es correcto. La spec dice
literalmente «GIVEN un aprendizaje de `_seed()`», de modo que vaciarlos habría
contradicho el requisito. Entran ahora como apuntes, sin las etiquetas
«consistente» / «prometedora» / «observación» que antes venían tecleadas a mano.

**Nota metodológica**: una primera pasada de esta verificación buscó cadenas
inventadas (`19:30`, `carrusel`) en el JSON crudo completo y las encontró,
concluyendo erróneamente que el fallo seguía abierto. La aserción estaba mal
planteada: esas cadenas viven dentro de `learnings`, que la spec exige mantener.
Acotada la búsqueda a las tres secciones afectadas, no aparece ninguna.

## CRITICAL-2 — CERRADO

**Era**: `tests/test_content_os_honestidad.py:397` contenía
`check(not (ROOT / "data" / "inspiration").exists() or True, …)`. La expresión
`X or True` es siempre cierta, así que la única comprobación que amparaba el
requisito de no borrar datos sin confirmación no podía fallar jamás, y además
sumaba como verde en el recuento.

**Ahora**: la tautología ha desaparecido, sustituida por dos funciones con
aserciones sobre valores calculados —`test_no_borra_heredado()` y
`test_instalacion_limpia()`—, que comparan estado antes y después, exigen
igualdad de contenido y verifican los estados vacíos.

**Falsabilidad demostrada por mutación**: reintroduciendo el fallo original
(un `_seed()` que vuelve a inventar calendario, ideas e inspiraciones), **5
aserciones fallan**:

- `calendar` vacío en disco
- `ideas` vacío en disco
- `inspirations` vacío en disco
- ausencia de `19:30`
- ausencia de `NexusSocks`

Un test que solo se comprueba pasando no demuestra nada. Este falla cuando debe.

## Hallazgo heredado de la remediación

La e2e `flujo_contentos` **pasaba sin sembrar un solo dato**: el plan aparecía
porque el backend se lo inventaba, de modo que la prueba confirmaba que el HUD
sabía pintar una ficción. Al cerrar CRITICAL-1 cayó a 8/9, y se añadió
`_siembra_plan_contenido()` para que sea la prueba quien ponga el dato, como
haría el usuario. La siembra es legítima: no tapa el problema, lo expone.

**Regla que deja este cambio**: si una prueba de extremo a extremo pasa sin
sembrar datos, hay que sospechar de inmediato que los está inventando el código
de producción.

## Sigue abierto (no bloquea el archivado)

Se mantienen sin cambios respecto al informe anterior:

- **WARNING-1** — `best[].eng`, `worst[].eng` y las series de `charts.*` viajan
  fuera del sobre de procedencia; la lista blanca `_LIBRES` lo enmascara. No hay
  mentira en pantalla (el HUD marca el origen a nivel de bloque), pero el
  contrato es desigual.
- **WARNING-2** — La ruta «medido» no tiene test de regresión; verificada a mano.
- **WARNING-3** — El criterio del `?v=NN` en `tasks.md` y `proposal.md` ya no
  describe el código: trabajo posterior y ajeno (`1f749bd`) retiró el
  cache-busting manual con motivo documentado. Artefacto desactualizado, no
  regresión.
- **WARNING-4** — El bloque de aprendizajes no lleva chip de origen. Desviación
  de la tarea, no de la spec.
- **SUGGESTION 1-4** — `_ok = True` muerto; duplicidad de `N_MINIMO`; docstring
  de cabecera de `contentos.py` describiendo el mundo anterior; `_LIBRES` sin
  comentario que la justifique.

## Veredicto

**PASS con avisos.** Los dos hallazgos CRITICAL están cerrados con evidencia de
ejecución, no de lectura. Suite completa en verde y 9/9 flujos e2e. Los cuatro
WARNING y las cuatro SUGGESTION quedan documentados como trabajo posterior y no
bloquean el archivado del cambio.
