# Pruebas E2E de nexus (Playwright)

**No ejecutar este runner completo en un checkout activo con datos o configuración reales.** El código define diez flujos; en esta actualización se ha ejecutado **uno**, `config-guardado`, con `--sin-servidor` (backend en proceso: sin uvicorn, sin puertos, sin `lifespan` y sin nada que salga de la máquina). Los otros nueve siguen sin ejecutarse aquí. Un resultado `passed` solo respalda las comprobaciones concretas del flujo en el entorno utilizado, no el funcionamiento de todas las integraciones.

## Modo hermético: `--sin-servidor`

```
.venv\Scripts\python.exe tests\e2eun_e2e.py --sin-servidor
```

Corre **solo** el flujo del guardado de ⚙ y no arranca servidor:

- El backend es el REAL, en el mismo proceso, con `httpx.ASGITransport`, que **no ejecuta `lifespan`**: no se enciende el micrófono, ni Telegram, ni el programador de ciclos, ni el adoptador de túnel. Es la misma regla que siguen las suites del repo.
- El navegador (Chromium de Playwright) carga el HUD desde `http://127.0.0.1:1/`, un origen **que no existe**: cada petición la sirve el backend de este proceso y cualquier URL de otro origen se **aborta**. Nada sale de la máquina (ni las hojas de fuentes de Google, que se cuentan y se cortan).
- `NEXUS_CONFIG_DIR` y `NEXUS_DATA_DIR` apuntan a una carpeta temporal **fuera del repo** que se borra al terminar; `NEXUS_DOTENV=0`.
- Código de salida 0 solo si todas las comprobaciones del flujo pasan. Deja `report.md`, `report.json`, `consola.json` y `red.json` en `data/e2e/`.

## Antes de cualquier ejecución completa

El runner completo inicia uvicorn y Chromium, crea y borra `data/e2e/sandbox/` y `data/e2e/evidencias/`, y escribe informes en `data/e2e/`. Define `NEXUS_DATA_DIR`, `NEXUS_CONFIG_DIR` y `NEXUS_E2E=1`, pero **no garantiza aislamiento**: el `.env` de la raíz ya no se carga cuando hay `NEXUS_CONFIG_DIR` (T44), pero el arranque puede acceder a otros recursos o servicios. No se puede afirmar que nunca toque configuración o datos reales. Solo considerar instalación de dependencias y ejecución tras aprobación específica, en una copia aislada y un entorno controlado, sin credenciales, datos ni servicios reales expuestos. No hay una receta universal segura para ejecutar este runner tal como está.

## Alcance del código

| Flujo | Qué comprueba y con qué evidencia |
|---|---|
| `tareas-borrado-papelera` | Crea, completa, borra con confirmación y restaura tareas; órdenes y estados mediante API, con capturas del tablero HUD. No demuestra todo el recorrido mediante controles de interfaz. |
| `multitarea-sidebar` | Trabajos sintéticos por `POST /api/_e2e/job`, indicador y panel HUD; exige recibir en `/ws` una trama `jobs` que contenga el ID del primer trabajo creado, además de las comprobaciones de interfaz. La API también se usa para duplicados y estados. |
| `orquestacion-requestid` | Identidad, cancelación y consulta de trabajos mediante API; no acredita la ejecución de un proveedor externo. |
| `sidebar-iconos` | SVG, colores, estados activo/hover y temas mediante comprobaciones DOM del HUD. |
| `cerebro-modelo` | Coherencia entre mensajes, estado de runtime y configuración del modelo; puede intentar consultar el runtime disponible en el entorno. No certifica disponibilidad universal del modelo. |
| `config-apis` | Menú y campos de configuración visibles en el HUD; no valida claves ni llamadas reales a proveedores. |
| `config-guardado` | **Guardar de ⚙ de punta a punta (T31c):** cambia un valor en «Operador» y tres en «Permisos», pulsa el «Guardar» real del pop up y comprueba que la petición sale hacia `/api/config`, que el payload de guardas es exactamente el que construye `payloadGuardas()` y que el cambio queda escrito en `settings.json` y en `GET /api/config`, sin tocar los ajustes no editados. Después quita un control del DOM (el escenario del defecto de T31) y verifica que su clave NO viaja y que el valor guardado no se borra. Ejecutado en modo `--sin-servidor`; el panel sigue con sus **seis** secciones (mover «Consumo y estado» no es asunto de esta prueba). |
| `content-os` | Secciones y fichas desplegables con un plan sembrado por la prueba, no publicaciones obtenidas de un servicio externo. |
| `reels` | Visualización de un análisis calculado con datos sintéticos; no consulta Instagram en vivo. |
| `competencia` | Pestaña, comparativas, límites y fichas con rivales sintéticos; no valida descubrimiento ni consultas reales a Meta. |

La ruta `_e2e/job` se registra solo cuando `NEXUS_E2E=1`. Una petición WebSocket emitida por el navegador no demuestra conexión: el flujo Multitarea requiere una trama entrante `jobs` con el ID recién creado. Las comprobaciones de tareas y orquestación son en gran parte **asistidas por API**; capturas o texto DOM no convierten esas órdenes en interacciones completas de usuario.

## Evidencias y límites

Si se ejecuta en un entorno autorizado, el runner deja `report.md`, `report.json`, `evidencias/*.png`, `trace.zip`, `consola.json`, `red.json` y `servidor.log` bajo `data/e2e/`. El código de salida es 0 cuando todos los flujos registrados pasan, y distinto de 0 si falla alguno. Los pendientes del informe significan **cobertura E2E ausente**, no que la función no exista: memoria tras reinicio, voz con audio del navegador, archivos por interfaz y encargo real contra Hermes. TV funciona según el propietario, pero **no está cubierta** por estos flujos. Tampoco se validan efectos reales de proveedores ni dispositivos mediante las fixtures.

Un fallo de WebSocket puede tener varias causas; no presuponga que solo falta un paquete. Consultar `servidor.log`, `consola.json` y `report.json` únicamente en el entorno aislado autorizado; un refresco por API no sustituye la recepción de una trama `jobs`.
