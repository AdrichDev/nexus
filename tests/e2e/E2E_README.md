# Pruebas end-to-end de nexus (Playwright)

> Specs v23, TAREAS 22 y 23. Aquí no vale que «el código compile», que «la API
> responda» ni que «el componente se renderice»: se arranca nexus DE VERDAD, se
> abre el HUD real en Chromium y se hacen los flujos como los haría Adri.

## Cómo se ejecuta

```bat
cd <carpeta del repo>
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\python tests\e2e\run_e2e.py
```

Para verlo con tus ojos, en una ventana de navegador:

```bat
.venv\Scripts\python tests\e2e\run_e2e.py --headed
```

Sale con código 0 solo si TODOS los flujos quedan en `passed`.

## Qué hace por dentro

1. Crea una caja de arena en `data/e2e/sandbox/` y arranca uvicorn con
   `NEXUS_DATA_DIR` y `NEXUS_CONFIG_DIR` apuntando ahí: **jamás toca tu tablero,
   tu memoria ni tu configuración reales**.
2. Escribe una configuración mínima (`setup_done`, modelo `mock`, voz apagada,
   Hermes apagado) para que las pruebas no dependan de ningún servicio externo
   y sean reproducibles en otro equipo.
3. Registra la ruta de pruebas `POST /api/_e2e/job` — que **solo existe** cuando
   el servidor arranca con `NEXUS_E2E=1` — para poder lanzar trabajos de duración
   controlada y comprobar el indicador de Multitarea en la interfaz real.
4. Abre el HUD en Chromium y ejecuta los flujos.
5. Guarda las evidencias en `data/e2e/`.

## Evidencias que deja cada ejecución

| Archivo | Qué es |
|---|---|
| `report.md` / `report.json` | resultado `passed`/`failed` de cada flujo, paso a paso |
| `evidencias/*.png` | capturas de cada hito y de CADA fallo |
| `trace.zip` | traza completa de Playwright (ábrela con `playwright show-trace`) |
| `consola.json` | log de consola del navegador |
| `red.json` | peticiones de red a la API |
| `servidor.log` | salida del nexus arrancado para la prueba |
| `report.json → estado_antes/estado_despues` | estado del tablero y de los trabajos antes y después |

## Flujos cubiertos hoy

- **`tareas-borrado-papelera`** — crear tareas, completar dos, pedir «limpia las
  tareas ya realizadas», comprobar que **pide confirmación** y no borra nada,
  decir que no, volver a pedirlo, confirmar, comprobar que **solo se van las
  completadas**, ver la papelera y **restaurarlas** a su columna. También el
  borrado por título con su confirmación.
- **`multitarea-sidebar`** — lanzar trabajos y ver el indicador del sidebar
  pasar por `En curso` → `2` → `✓` → `!`, que un duplicado se bloquea, que el
  panel muestra el estado real, el progreso y los archivos creados, y que un
  trabajo fallido **nunca** aparece como completado.
- **`orquestacion-requestid`** — cada ejecución nace con su identificador, se
  registra el agente y la petición original, cancelar mata la publicación del
  resultado (nada de respuestas fantasma) y el operador puede consultar y
  cancelar lo que hay en marcha.

## Flujos todavía NO cubiertos

Salen listados al final de `report.md` como **pendientes**, nunca como pasados,
porque su funcionalidad aún no está hecha: memoria de Engram (T4), voz (T7),
color de los iconos del sidebar (T17), archivos reales (T18-T21) y un encargo
real de punta a punta contra el gateway de Hermes.

## Si algo falla

- `nexus no ha llegado a arrancar` → mira `data/e2e/servidor.log`.
- El navegador no carga el HUD → suele ser un proxy; el runner ya arranca
  Chromium con `--proxy-server=direct://`.
- Aviso de WebSocket → falta el paquete `websockets` (`pip install websockets`);
  las pruebas siguen porque el HUD también refresca por API, pero en el uso real
  el indicador tarda más en pintarse.
