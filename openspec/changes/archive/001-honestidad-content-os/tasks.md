# Tareas — `001-honestidad-content-os`

- **Fase**: tasks · **Almacén**: híbrido (este fichero + Engram `sdd/001-honestidad-content-os/tasks`)
- **Entra desde**: `proposal.md` (Decisiones resueltas 01/08/2026), `specs/*/spec.md`, `design.md`.
- **Entrega**: única, commit directo a `main` vía `SUBIR_A_GITHUB.bat`. Sin flujo de PRs.

## Review Workload Forecast

Presupuesto de esta sesión: **800** líneas (preflight), no las 400 por defecto del
contrato de fase. Estimación de diseño: 600-700, dentro de las 800.

| Campo | Valor |
| --- | --- |
| Líneas cambiadas estimadas | 600-700 (backend ~240, HUD ~130, skill ~60, umbrales ~35, suite ~190, registro+cache-busting ~5) |
| Riesgo sobre presupuesto (800) | Medio |
| PRs encadenadas recomendadas | No |
| División sugerida | Entrega única (ya decidida por el usuario) |
| Estrategia de entrega | ask-on-risk |
| Estrategia de encadenado | pending |

```text
Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium
```

## PARTIDO EN DOS ENTREGAS (decisión del usuario, 01/08/2026)

En los tres bloques del cambio `002` la estimación se quedó corta unas 2,3 veces
(390→1160, 490→1256, 420→938). Con ese patrón, las 600-700 de aquí apuntan a
~1500 sobre un presupuesto de 800. El usuario decidió partirlo antes de empezar,
no a mitad.

**El corte NO es el que sugería `design.md`** («backend+contrato» / «HUD»). Ese
corte deja la aplicación rota entre entregas: la Fase 2 cambia el contrato del
payload de `/api/contentos` y la Fase 5 es quien lo consume, así que entregar el
contrato sin su consumidor deja el HUD pintando objetos donde había números.

Regla del corte real: **el contrato y quien lo consume viajan en la misma
entrega**; lo que no toca el contrato va antes.

| Entrega | Fases | Tareas | Qué consigue | ¿Rompe algo visible? |
| --- | --- | --- | --- | --- |
| **A** | 1, 3, 4 | 11 | Cimientos (`procedencia.py`, umbrales, demo aislada), la regla extendida al generador, y **se acaban las cifras falsas en el chat** | No. Todo aditivo salvo `skill.py`, que solo pasa a decir la verdad |
| **B** | 2, 5, 6 | 12 | Contrato del payload honesto **y** el HUD que lo pinta, juntos | No. Contrato y consumidor entran a la vez |

Cada entrega deja `run_all.py` en **TODO VERDE** por sí sola.

> **ENTREGA A APLICADA (01/08/2026)** — Fases 1, 3 y 4 completas, `run_all.py`
> TODO VERDE, sin commitear. Líneas REALES: **1.032** autoras (321 en ficheros
> ya seguidos + 711 en los tres ficheros nuevos), de las cuales 452 son la suite
> nueva. La estimación de esta entrega eran 400-500: se quedó corta 2,1x, o sea
> justo el patrón medido en el cambio `002`. **La entrega B parte de un
> presupuesto ya consumido**: replantear su tamaño antes de empezar.

La entrega A ataca primero lo que hoy más miente: `skills/content_os/skill.py`
responde en el chat «12.840 seguidores, retención 48,6 %» y, peor, una conclusión
estadística inventada («el gancho de resultado visible va por encima de tu mediana
en 4 de 8 reels») sobre una mediana que nadie ha calculado. Eso sale por el canal
donde el usuario más habla, y no depende de ningún contrato: se puede arreglar ya.

### Unidades de trabajo

| Unidad | Objetivo | Test enfocado | Arnés en tiempo real | Límite de reversión |
| --- | --- | --- | --- | --- |
| A | Procedencia + generador honesto + enrutado | `.venv\Scripts\python.exe tests\test_content_os_honestidad.py` | `run.bat` (obligatorio: `skills_loader` solo lee las carpetas al arrancar) y probar «cómo va el instagram» y «analiza este reel de @x …» | `git revert` del commit |
| B | Contrato del dashboard + HUD + cierre | mismo fichero, casos de contrato | recarga del HUD | `git revert` + bajar `?v=29`→`?v=28` o recarga dura |

---

## Fase 1: Fundamentos — procedencia, demo, umbrales

- [x] 1.1 Crear `backend/core/procedencia.py`: `dato(valor, origen, periodo=None, delta=None, n=None, aviso="")`, constantes `MEDIDO/DEMOSTRACION/SIN_DATOS`, `_carga_umbrales_content_os()` (patrón `remote.py:54`), `sin_cifras_inventadas(texto, permitidas)`. Test: `test_content_os_honestidad.py` — `dato()` con origen inválido lanza `ValueError`.
- [x] 1.2 Añadir sección `content_os` a `config/umbrales.json`: `n_minimo`, `etiquetas` (origen), `textos` (estados vacíos), `validador.magnitud_minima`. Test: cambiar un valor y comprobar que la salida cambia (con `extra`).
- [x] 1.3 Crear `backend/core/contentos_demo.py`: mover `_demo_metrics()` (`contentos.py:182-200`) a `metricas()`, estampar `origen=DEMOSTRACION` en el retorno. Test: `metricas()["origen"] == DEMOSTRACION`.
- [x] 1.4 Crear `tests/test_content_os_honestidad.py` con harness `check(cond, msg)`; incluir los tests de 1.1/1.2/1.3 y `sin_cifras_inventadas()` tumba «tus reels tienen 48,6 % de retención» y deja pasar «3 golpes y un CTA».
- [x] 1.5 Registrar `test_content_os_honestidad.py` en la lista de `tests/run_all.py:61`.

## Fase 2: Dashboard honesto

- [x] 2.1 `contentos.py` `dashboard()`: `metricas = await _ig_metrics(); origen = MEDIDO if metricas else DEMOSTRACION; metricas = metricas or contentos_demo.metricas()`; envolver `followers`, `reach_month`, `media_count` en `dato()`; `retention` → `dato(None, SIN_DATOS, aviso=…)` (Graph API no da tiempo de visualización sin cuenta); deltas dentro del sobre o `None`; eliminar la clave `experiments`. Test: barrido del payload — ningún número fuera de sobre; `experiments` ausente.
- [x] 2.2 `_seed()` (`:52-57`) y `add_item("learning", …)` (`:85-87`) sin `conf` tecleado; un learning nuevo entra con `origen: "apunte"` salvo que traiga `evidencia` completa (`n`, periodo, método). Test: aprendizaje de semilla sale sin `conf`.
- [x] 2.3 Reconstruir `evidence` al estilo `radiografia()` (`inteligencia.py:312`): `{unidad, n, suficiente, aviso, complete_pct: None|int, consistent, promising, observations, apuntes}`; `complete_pct` solo cuenta learnings con evidencia completa. Test: `complete_pct is None` con cero evidencia; nunca `0` como calidad.
- [x] 2.4 Test de lectura del módulo: `48.6`, `4.1`, `18.4` no aparecen como literales en `backend/core/contentos.py`.

## Fase 3: Generador con la regla extendida

- [x] 3.1 `backend/core/llm.py`: exportar `REGLA_CONTENT_OS` («solo puedes usar las cifras del bloque DATOS que te llega; si va vacío, no hables de rendimiento») junto al bloque `REGLA INVIOLABLE` (~:776). Test: `_build_messages(..., system="x")` sigue conteniendo `REGLA INVIOLABLE` (regresión silenciosa).
- [x] 3.2 `contentos.generate()`: pasar `system=REGLA_CONTENT_OS` + bloque DATOS calculado a `ask_llm()`; aplicar `procedencia.sin_cifras_inventadas()` al resultado; si rechaza, sustituir por la respuesta honesta antes de guardar o devolver. Test: una cifra no fundamentada en el texto del modelo se rechaza/filtra.

## Fase 4: Enrutado honesto (colisión D7 — matriz de amenazas)

- [x] 4.1 **RED**: en `test_content_os_honestidad.py`, test de enrutado — «cómo va el instagram» y «analiza este reel de @x …» caen en `content_os` vía `skills_loader.route()`, y la respuesta debe citar la vía Graph API / `business_discovery`. Debe **fallar** contra el código actual (cifras de ejemplo en `analytics`, descarga en `inspire`).
- [x] 4.2 `skills/content_os/skill.py` `analytics` (`:126-130`): sustituir las cifras de ejemplo («12.840 seguidores», «184,2K», «retención 48,6 %», la conclusión de «4 de 8 reels») por una respuesta honesta al estilo `ig_estado` (qué falta, cómo conectar). Hace pasar la mitad `analytics` del RED de 4.1.
- [x] 4.3 `skill.py` `inspire`: explica la política, reencamina a `business_discovery` (`skills/instagram/scripts/ig.py:336`); `_download_and_transcribe` pasa a fallo cerrado — primera línea `raise RuntimeError("vía retirada por política; pendiente de borrado con tu confirmación")`. Hace pasar la mitad `inspire` del RED de 4.1. Test adicional: cero llamadas a `_download_and_transcribe` desde `handle()` (AST + llamada directa).
- [x] 4.4 `skill.py` `patterns`/`script`: anteponer `_aviso_origen()` — «transcripción heredada anterior a este cambio» — cuando lean `data/inspiration/`. Test: la respuesta incluye el aviso de origen heredado.

## Fase 5: HUD

- [x] 5.1 `frontend/js/command.js`: `cosDato(d)` — único pintor de cifras; sin `d.origen` pinta `—` y «sin procedencia», nunca el número.
- [x] 5.2 `command.js` `cosKpi()` (`:1606`) recibe el sobre completo; retirar la 4ª tarjeta «Experimentos» (`:1533`).
- [x] 5.3 `command.js` `cosPanel()`: parámetro `extra` con chip de origen (demo/nada) en la cabecera de cada bloque (KPIs, gráficas, ranking, próxima acción, aprendizajes).
- [x] 5.4 `frontend/css/command.css`: `.cos-marca`, `.cos-marca.demo`, `.cos-marca.nada`, estado apagado del anillo de datos.
- [x] 5.5 `frontend/index.html`: `?v=28` → `?v=29` en `:9` y `:126` (cache-busting manual, obligatorio si se toca CSS/JS).

Test: `tests/e2e/run_e2e.py` `flujo_contentos` sigue con ≥6 secciones plegables (no
afirma nada sobre KPIs, así que no requiere cambio).

## Fase 6: Cierre y verificación

- [x] 6.1 Completar `test_content_os_honestidad.py` con el caso de contrato restante: `learnings[]` con `conf` solo si trae `n`+periodo+método.
- [x] 6.2 Reiniciar nexus (`run.bat`) — obligatorio tras tocar `skills/content_os/skill.py` (`skills_loader` solo lee carpetas al arrancar) — y ejecutar `.venv\Scripts\python.exe tests\run_all.py` → **TODO VERDE**.
- [x] 6.3 (si procede) `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/e2e/run_e2e.py` → objetivo 9/9.

> **ENTREGA B APLICADA (01/08/2026)** — Fases 2, 5 y 6 completas: 23/23 tareas.
> `run_all.py` TODO VERDE, e2e 9/9, sin commitear. Líneas REALES de la entrega B:
> **462** autoras (`git diff --stat` sobre ficheros ya seguidos; ningún fichero
> nuevo). Estimación 450-550: por primera vez en esta sesión, dentro.
>
> **Salvedad de la 6.2**: NO se ha reiniciado la instancia de nexus del usuario
> (PID 59748, puerto 8177): sigue con el código viejo cargado y hay que cerrarla
> y volver a abrirla con `run.bat` para ver el panel nuevo. La verificación de
> runtime se hizo contra un PROCESO NUEVO en el puerto 8178, y la e2e levanta su
> propio uvicorn con datos de arenero.

## Fase 7: Remediación de los CRITICAL del informe de verificación (03/08/2026)

Alcance ACOTADO a los dos CRITICAL de `verify-report.md`. Nada más: el WARNING-1
(`best[]/worst[].eng` y `charts.*` fuera del sobre), la lista blanca `_LIBRES` y
el desfase del `?v=NN` en los artefactos quedan FUERA a propósito.

- [x] 7.1 **CRITICAL-1** · `backend/core/contentos.py` `_seed()`: `calendar`, `ideas`
  e `inspirations` nacen VACÍOS. Dejaban de existir los estados vacíos honestos
  porque `_load()` escribía la ficción en disco la primera vez. Los `learnings`
  de semilla SE QUEDAN: el escenario «Aprendizaje de semilla sin evidencia» de la
  spec los exige, y ya salen rotulados como apuntes. Lo ya escrito en
  `data/contentos.json` NO se toca (borrar exige confirmación explícita).
  Test: `test_instalacion_limpia()` — las tres secciones vacías, sus textos
  «Todavía no hay…» presentes, la ficción ausente del fichero persistido, y
  triangulación con `add_item()` para probar que el vacío no es un payload roto.
- [x] 7.2 **CRITICAL-2** · `tests/test_content_os_honestidad.py`: fuera la
  tautología `check(not path.exists() or True, …)` (`X or True` nunca falla).
  La sustituye `test_no_borra_heredado()`: siembra material heredado en un
  arenero, pasa los 7 intents de la skill MÁS una orden desconocida, y exige que
  la carpeta quede idéntica (ni un fichero menos, ni uno más) y con el mismo
  contenido. Verificada por mutación: inyectando un `rmtree` en el intent
  `ideas` la aserción FALLA (3 fallos); revertido, pasa.
- [x] 7.3 `tests/e2e/run_e2e.py`: nuevo `_siembra_plan_contenido()`. El flujo
  `flujo_contentos` comprobaba el despliegue de fichas sobre las publicaciones
  que se inventaba el backend; ahora el plan lo pone la PRUEBA, como haría el
  usuario. Sin esto, arreglar 7.1 dejaba la e2e en 8/9.

## Orden de dependencia

Fase 1 (sin dependencias) → Fase 2 y 3 dependen de 1.1/1.3 → Fase 4 es independiente
de 2/3 pero su RED (4.1) debe preceder a 4.2/4.3 → Fase 5 depende del contrato fijado
en Fase 2 → Fase 6 cierra y exige reinicio antes de validar el enrutado de Fase 4.
No hay paralelismo real entre fases por ser una sola persona/sesión implementando;
dentro de la Fase 1, 1.1-1.3 son paralelizables entre sí (ficheros distintos).
