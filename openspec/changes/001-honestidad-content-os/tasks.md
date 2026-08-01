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

Si al implementar se supera 800, el corte natural (documentado en `design.md`) es:
**(1)** backend + contrato + suite de contrato, **(2)** HUD + CSS + `?v=NN` + suite
de enrutado y política.

### Unidad de trabajo

| Unidad | Objetivo | PR | Test enfocado | Arnés en tiempo real | Límite de reversión |
| --- | --- | --- | --- | --- | --- |
| 1 | Procedencia + dashboard honesto + generador + enrutado + HUD | único | `.venv\Scripts\python.exe tests\test_content_os_honestidad.py` | `run.bat`, tras reiniciar probar «cómo va el instagram» y «analiza este reel de @x …» | `git revert` del commit + bajar `?v=29`→`?v=28` o recarga dura |

---

## Fase 1: Fundamentos — procedencia, demo, umbrales

- [ ] 1.1 Crear `backend/core/procedencia.py`: `dato(valor, origen, periodo=None, delta=None, n=None, aviso="")`, constantes `MEDIDO/DEMOSTRACION/SIN_DATOS`, `_carga_umbrales_content_os()` (patrón `remote.py:54`), `sin_cifras_inventadas(texto, permitidas)`. Test: `test_content_os_honestidad.py` — `dato()` con origen inválido lanza `ValueError`.
- [ ] 1.2 Añadir sección `content_os` a `config/umbrales.json`: `n_minimo`, `etiquetas` (origen), `textos` (estados vacíos), `validador.magnitud_minima`. Test: cambiar un valor y comprobar que la salida cambia (con `extra`).
- [ ] 1.3 Crear `backend/core/contentos_demo.py`: mover `_demo_metrics()` (`contentos.py:182-200`) a `metricas()`, estampar `origen=DEMOSTRACION` en el retorno. Test: `metricas()["origen"] == DEMOSTRACION`.
- [ ] 1.4 Crear `tests/test_content_os_honestidad.py` con harness `check(cond, msg)`; incluir los tests de 1.1/1.2/1.3 y `sin_cifras_inventadas()` tumba «tus reels tienen 48,6 % de retención» y deja pasar «3 golpes y un CTA».
- [ ] 1.5 Registrar `test_content_os_honestidad.py` en la lista de `tests/run_all.py:61`.

## Fase 2: Dashboard honesto

- [ ] 2.1 `contentos.py` `dashboard()`: `metricas = await _ig_metrics(); origen = MEDIDO if metricas else DEMOSTRACION; metricas = metricas or contentos_demo.metricas()`; envolver `followers`, `reach_month`, `media_count` en `dato()`; `retention` → `dato(None, SIN_DATOS, aviso=…)` (Graph API no da tiempo de visualización sin cuenta); deltas dentro del sobre o `None`; eliminar la clave `experiments`. Test: barrido del payload — ningún número fuera de sobre; `experiments` ausente.
- [ ] 2.2 `_seed()` (`:52-57`) y `add_item("learning", …)` (`:85-87`) sin `conf` tecleado; un learning nuevo entra con `origen: "apunte"` salvo que traiga `evidencia` completa (`n`, periodo, método). Test: aprendizaje de semilla sale sin `conf`.
- [ ] 2.3 Reconstruir `evidence` al estilo `radiografia()` (`inteligencia.py:312`): `{unidad, n, suficiente, aviso, complete_pct: None|int, consistent, promising, observations, apuntes}`; `complete_pct` solo cuenta learnings con evidencia completa. Test: `complete_pct is None` con cero evidencia; nunca `0` como calidad.
- [ ] 2.4 Test de lectura del módulo: `48.6`, `4.1`, `18.4` no aparecen como literales en `backend/core/contentos.py`.

## Fase 3: Generador con la regla extendida

- [ ] 3.1 `backend/core/llm.py`: exportar `REGLA_CONTENT_OS` («solo puedes usar las cifras del bloque DATOS que te llega; si va vacío, no hables de rendimiento») junto al bloque `REGLA INVIOLABLE` (~:776). Test: `_build_messages(..., system="x")` sigue conteniendo `REGLA INVIOLABLE` (regresión silenciosa).
- [ ] 3.2 `contentos.generate()`: pasar `system=REGLA_CONTENT_OS` + bloque DATOS calculado a `ask_llm()`; aplicar `procedencia.sin_cifras_inventadas()` al resultado; si rechaza, sustituir por la respuesta honesta antes de guardar o devolver. Test: una cifra no fundamentada en el texto del modelo se rechaza/filtra.

## Fase 4: Enrutado honesto (colisión D7 — matriz de amenazas)

- [ ] 4.1 **RED**: en `test_content_os_honestidad.py`, test de enrutado — «cómo va el instagram» y «analiza este reel de @x …» caen en `content_os` vía `skills_loader.route()`, y la respuesta debe citar la vía Graph API / `business_discovery`. Debe **fallar** contra el código actual (cifras de ejemplo en `analytics`, descarga en `inspire`).
- [ ] 4.2 `skills/content_os/skill.py` `analytics` (`:126-130`): sustituir las cifras de ejemplo («12.840 seguidores», «184,2K», «retención 48,6 %», la conclusión de «4 de 8 reels») por una respuesta honesta al estilo `ig_estado` (qué falta, cómo conectar). Hace pasar la mitad `analytics` del RED de 4.1.
- [ ] 4.3 `skill.py` `inspire`: explica la política, reencamina a `business_discovery` (`skills/instagram/scripts/ig.py:336`); `_download_and_transcribe` pasa a fallo cerrado — primera línea `raise RuntimeError("vía retirada por política; pendiente de borrado con tu confirmación")`. Hace pasar la mitad `inspire` del RED de 4.1. Test adicional: cero llamadas a `_download_and_transcribe` desde `handle()` (AST + llamada directa).
- [ ] 4.4 `skill.py` `patterns`/`script`: anteponer `_aviso_origen()` — «transcripción heredada anterior a este cambio» — cuando lean `data/inspiration/`. Test: la respuesta incluye el aviso de origen heredado.

## Fase 5: HUD

- [ ] 5.1 `frontend/js/command.js`: `cosDato(d)` — único pintor de cifras; sin `d.origen` pinta `—` y «sin procedencia», nunca el número.
- [ ] 5.2 `command.js` `cosKpi()` (`:1606`) recibe el sobre completo; retirar la 4ª tarjeta «Experimentos» (`:1533`).
- [ ] 5.3 `command.js` `cosPanel()`: parámetro `extra` con chip de origen (demo/nada) en la cabecera de cada bloque (KPIs, gráficas, ranking, próxima acción, aprendizajes).
- [ ] 5.4 `frontend/css/command.css`: `.cos-marca`, `.cos-marca.demo`, `.cos-marca.nada`, estado apagado del anillo de datos.
- [ ] 5.5 `frontend/index.html`: `?v=28` → `?v=29` en `:9` y `:126` (cache-busting manual, obligatorio si se toca CSS/JS).

Test: `tests/e2e/run_e2e.py` `flujo_contentos` sigue con ≥6 secciones plegables (no
afirma nada sobre KPIs, así que no requiere cambio).

## Fase 6: Cierre y verificación

- [ ] 6.1 Completar `test_content_os_honestidad.py` con el caso de contrato restante: `learnings[]` con `conf` solo si trae `n`+periodo+método.
- [ ] 6.2 Reiniciar nexus (`run.bat`) — obligatorio tras tocar `skills/content_os/skill.py` (`skills_loader` solo lee carpetas al arrancar) — y ejecutar `.venv\Scripts\python.exe tests\run_all.py` → **TODO VERDE**.
- [ ] 6.3 (si procede) `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/e2e/run_e2e.py` → objetivo 9/9.

## Orden de dependencia

Fase 1 (sin dependencias) → Fase 2 y 3 dependen de 1.1/1.3 → Fase 4 es independiente
de 2/3 pero su RED (4.1) debe preceder a 4.2/4.3 → Fase 5 depende del contrato fijado
en Fase 2 → Fase 6 cierra y exige reinicio antes de validar el enrutado de Fase 4.
No hay paralelismo real entre fases por ser una sola persona/sesión implementando;
dentro de la Fase 1, 1.1-1.3 son paralelizables entre sí (ficheros distintos).
