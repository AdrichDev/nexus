# Pruebas E2E de nexus (Playwright)

**No ejecutar este runner en un checkout activo con datos o configuración reales.** El código define nueve flujos; en esta actualización no se han ejecutado. Un resultado `passed` solo respaldaría las comprobaciones concretas del flujo en el entorno utilizado, no el funcionamiento de todas las integraciones.

## Antes de cualquier ejecución

El runner inicia uvicorn y Chromium, crea y borra `data/e2e/sandbox/` y `data/e2e/evidencias/`, y escribe informes en `data/e2e/`. Define `NEXUS_DATA_DIR`, `NEXUS_CONFIG_DIR` y `NEXUS_E2E=1`, pero **no garantiza aislamiento**: la configuración del backend puede importar el `.env` de la raíz y el arranque puede acceder a otros recursos o servicios. No se puede afirmar que nunca toque configuración o datos reales. Solo considerar instalación de dependencias y ejecución tras aprobación específica, en una copia aislada y un entorno controlado, sin credenciales, datos ni servicios reales expuestos. No hay una receta universal segura para ejecutar este runner tal como está.

## Alcance del código (no resultado de esta sesión)

| Flujo | Qué comprueba y con qué evidencia |
|---|---|
| `tareas-borrado-papelera` | Crea, completa, borra con confirmación y restaura tareas; órdenes y estados mediante API, con capturas del tablero HUD. No demuestra todo el recorrido mediante controles de interfaz. |
| `multitarea-sidebar` | Trabajos sintéticos por `POST /api/_e2e/job`, indicador y panel HUD; exige recibir en `/ws` una trama `jobs` que contenga el ID del primer trabajo creado, además de las comprobaciones de interfaz. La API también se usa para duplicados y estados. |
| `orquestacion-requestid` | Identidad, cancelación y consulta de trabajos mediante API; no acredita la ejecución de un proveedor externo. |
| `sidebar-iconos` | SVG, colores, estados activo/hover y temas mediante comprobaciones DOM del HUD. |
| `cerebro-modelo` | Coherencia entre mensajes, estado de runtime y configuración del modelo; puede intentar consultar el runtime disponible en el entorno. No certifica disponibilidad universal del modelo. |
| `config-apis` | Menú y campos de configuración visibles en el HUD; no valida claves ni llamadas reales a proveedores. |
| `content-os` | Secciones y fichas desplegables con un plan sembrado por la prueba, no publicaciones obtenidas de un servicio externo. |
| `reels` | Visualización de un análisis calculado con datos sintéticos; no consulta Instagram en vivo. |
| `competencia` | Pestaña, comparativas, límites y fichas con rivales sintéticos; no valida descubrimiento ni consultas reales a Meta. |

La ruta `_e2e/job` se registra solo cuando `NEXUS_E2E=1`. Una petición WebSocket emitida por el navegador no demuestra conexión: el flujo Multitarea requiere una trama entrante `jobs` con el ID recién creado. Las comprobaciones de tareas y orquestación son en gran parte **asistidas por API**; capturas o texto DOM no convierten esas órdenes en interacciones completas de usuario.

## Evidencias y límites

Si se ejecuta en un entorno autorizado, el runner deja `report.md`, `report.json`, `evidencias/*.png`, `trace.zip`, `consola.json`, `red.json` y `servidor.log` bajo `data/e2e/`. El código de salida es 0 cuando todos los flujos registrados pasan, y distinto de 0 si falla alguno. Los pendientes del informe significan **cobertura E2E ausente**, no que la función no exista: memoria tras reinicio, voz con audio del navegador, archivos por interfaz y encargo real contra Hermes. TV funciona según el propietario, pero **no está cubierta** por estos flujos. Tampoco se validan efectos reales de proveedores ni dispositivos mediante las fixtures.

Un fallo de WebSocket puede tener varias causas; no presuponga que solo falta un paquete. Consultar `servidor.log`, `consola.json` y `report.json` únicamente en el entorno aislado autorizado; un refresco por API no sustituye la recepción de una trama `jobs`.
