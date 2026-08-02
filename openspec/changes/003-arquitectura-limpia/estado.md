# Estado de la sesión — 01/08 y 02/08 de 2026

Registro para retomar el trabajo. Se escribe aquí porque la memoria
persistente (Engram) se desconectó a mitad de sesión y este documento sí
sobrevive en el repositorio.

## Dónde estamos

| Fase | Estado |
| --- | --- |
| 0 — ordenar la raíz | ✅ hecha (`ca865b0`) |
| 1 — auditar las 32 skills | ✅ **hecha, 32 de 32** |
| 2 — componentizar el frontend | ⏳ siguiente |
| 3 — estratificar `backend/core/` | ⏳ pendiente |

**Nada está pusheado.** Todo son commits locales en `main`.

## Lo que hay que hacer nada más volver

1. **Reiniciar nexus con `run.bat`.** Se han modificado las 32 skills y
   `skills_loader` solo lee las carpetas al arrancar: la instancia viva sigue
   sirviendo el código anterior.
2. Comprobar en el chat que la analítica de Instagram ya no suelta cifras
   inventadas y que «cómo va el instagram» llega a la skill correcta.

## Fase 1 — lo que apareció

Ocho tandas, 32 skills, ~2.500 comprobaciones nuevas repartidas en 18 suites.
Agrupado por familia de fallo:

| Patrón | Veces | Ejemplo |
| --- | --- | --- |
| Pronombre enclítico | las 8 tandas, ~100 frases | `apaga` funcionaba, `apágalo` no |
| Regex sin `\b` | 4 | «pa-**usa** la música» la robaba `mcp_hands`; «contra**tiempo**» disparaba el parte meteorológico |
| Robos entre skills por orden alfabético | ~15 | «ponme hermes en marcha» → `media/play` |
| Instrucciones de arreglo imposibles | 4 | `memory_graph` mandaba ejecutar `nexus_up.bat`, que no existe |
| Datos inventados con formato de reales | 9 skills | `system_pc`: «CPU 17% · RAM 52% · 44°C» sin poder medirlo |
| Destructivo sin confirmación | 5 | matar procesos, archivar copias, borrar recuerdos, `--remove-orphans`, crear flujos n8n |

### Los cinco más graves

1. **`instagram` reventaba con `ImportError`** en cuatro intents: usaba
   `from . import <hermano>` y el cargador la carga como `skills.instagram`,
   así que el punto apuntaba un nivel por encima. Los tests no lo veían porque
   importan con `importlib`: **la prueba pasaba y el usuario recibía un
   traceback**.
2. **`files.trash` fallaba con `AttributeError`** en tres de sus cuatro
   formas. Borrar ficheros llevaba roto sin que nadie lo notara.
3. **El modo abogado del diablo no existía.** La instrucción estaba definida
   y nunca se concatenaba a ningún prompt; el interruptor no lo leía nadie.
   Mientras tanto el HUD y la configuración prometían «SIEMPRE ACTIVO».
4. **`system_pc` mataba procesos sin confirmar**, por coincidencia de
   subcadena en el nombre.
5. **`comms` servía una bandeja de mensajes inventada** con nombres del
   entorno del usuario, y «captura de tareas» los **escribía en su memoria
   real**.

### Reglas que quedan establecidas

- Los comentarios en `skill.py` dicen **qué hace el código**. La historia va
  en el mensaje del commit.
- **Nada de datos personales** en código, configuración publicada ni tests: lo
  instala cualquiera. `umbrales.json` lleva solo tipos genéricos; lo que
  identifica va a `purga_local.json`, ignorado por git.
- El `SKILL.md` es **lo que lee el agente para decidir**: al grano, completo, y
  con un apartado de lo que la skill **no** hace.

## Otras cosas resueltas en la sesión

- Memoria con vectores por primera vez: pgvector llevaba meses instalado con
  741 filas y **cero** vectores, porque el modelo configurado no estaba
  descargado y el fallo era silencioso. Ahora `bge-m3` local, 715 filas
  vectorizadas, búsqueda semántica funcionando.
- Los 6 documentos de marca ingeridos (746 → 917 filas).
- Purga estrenada: FP y papeleo personal fuera de la memoria, 338 duplicados
  limpiados. **Nada borrado**: todo en `data/memory/papelera/`, reversible.
- `nexus` se congelaba 4,3 s cada 45 (mDNS síncrono sobre el bucle de
  asyncio). Arreglado.
- Túnel superviviente: ya no obliga a reescanear el QR en cada reinicio.
- Content OS deja de mentir, en el panel y en el chat.
- OpenRouter: se pide expresamente que ningún proveedor entrene con los
  prompts.
- Google Drive construido, con control total y el borrado tras confirmación.
- Flujo de n8n para el informe diario de las 08:00, con el nodo de competencia
  listo para enchufar.

## Bloqueantes que siguen abiertos

1. **Credenciales de Instagram.** Sin ellas no hay datos ni propios ni de
   competencia, y el ciclo cerrado no tiene materia prima. Es el primer
   dominó de todo lo que queda de Content OS.
2. **Reautorización de Google.** El scope de Drive cambió; la primera orden de
   Drive abrirá el navegador una vez.
3. **RDD no es operable desde Claude Code**: las lentes de revisión necesitan
   un contexto que inyecta el proveedor de OpenCode. Se desactivó a petición
   del usuario. Para revisión con recibo real hay que trabajar desde OpenCode.

## Deuda anotada, no tocada

- El prefijo de numeración de facturas no es agnóstico, pero cambiarlo rompe
  la serie ya emitida.
- La tabla de fabricantes por MAC de `domotica` es heurística con entradas
  dudosas.
- «recuérdame en el proyecto que…» va a `coach/remind`; la frase es
  genuinamente ambigua.
- `_ROOM_WORDS`, `_GENERIC_NAMES` y `_PORT_HINTS` de `domotica` siguen en el
  código en vez de en `umbrales.json`.
- `_probe_brain` de `hermes` gasta una llamada de pago en cada diagnóstico.
- Un fallo de la e2e en el indicador de Multitarea, preexistente.
