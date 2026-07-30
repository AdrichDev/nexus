# SPECS v23 — Tareas pendientes de NEXUS

> Documento de requisitos acordado con Adri el 2026-07-25.
> Origen: incidente «limpia las tareas ya realizadas» → NEXUS borró las 15 tareas
> (completadas y pendientes) y luego fue incapaz de recuperarlas, entrando en bucle.

## Objetivo general

Corregir el funcionamiento de NEXUS para que actúe como asistente principal, utilice
Hermes como ejecutor cuando corresponda, recuerde las decisiones y formas de trabajo
del usuario, gestione correctamente las tareas en segundo plano y pueda trabajar de
forma segura con archivos reales.

---

## FASE 1 — Corregir errores críticos

### TAREA 1. Añadir confirmación obligatoria antes de acciones destructivas

**Problema.** NEXUS puede eliminar información sin validar correctamente qué desea
borrar el usuario. Esto ha provocado que, ante la orden de eliminar las tareas
realizadas, se eliminen todas las tareas.

**Comportamiento requerido.** Antes de realizar cualquier acción destructiva, NEXUS
debe confirmar con el usuario el alcance exacto de la operación.

Se consideran acciones destructivas:

- Eliminar una o varias tareas.
- Eliminar archivos o carpetas.
- Sobrescribir archivos existentes.
- Vaciar listas.
- Borrar recuerdos o entradas de memoria.
- Eliminar eventos, correos, documentos o registros.
- Ejecutar operaciones masivas o difíciles de revertir.

**Ejemplo correcto**

```text
Usuario: Borra las tareas ya realizadas.
NEXUS:   He encontrado 4 tareas completadas y 3 pendientes.
         ¿Confirmas que elimine únicamente las 4 tareas completadas?
```

NEXUS solo debe ejecutar la eliminación después de recibir una confirmación explícita.

**Criterios de aceptación**

- Nunca se ejecuta una operación destructiva sin confirmación previa.
- NEXUS informa de cuántos elementos se eliminarán.
- NEXUS identifica claramente qué elementos están afectados.
- La confirmación distingue entre tareas completadas, pendientes y todas las tareas.
- Las operaciones destructivas quedan registradas en la memoria de actividad.
- Las pruebas deben verificar cancelación, confirmación y selección parcial.

### TAREA 2. Corregir la eliminación selectiva de tareas

**Problema.** La orden «borra las tareas ya realizadas» eliminó todas las tareas,
incluidas las pendientes.

**Comportamiento requerido.** La eliminación debe realizarse utilizando el estado real
de cada tarea:

- `pending`: pendiente.
- `in_progress`: en curso.
- `completed`: completada.
- `cancelled`: cancelada.
- `archived`: archivada.

Cuando el usuario diga «borra las tareas realizadas», solo deben seleccionarse las
tareas con estado `completed`.

**Criterios de aceptación**

- Las tareas pendientes no se eliminan.
- Las tareas en curso no se eliminan.
- NEXUS muestra una previsualización antes de borrar.
- El sistema conserva una copia recuperable de los registros eliminados.
- Se permite restaurar una tarea eliminada accidentalmente.
- La eliminación debe ser lógica o reversible antes de realizar un borrado físico definitivo.

### TAREA 3. Implementar papelera o recuperación de tareas eliminadas

**Problema.** NEXUS no pudo recuperar las tareas que había creado previamente después
de eliminarlas.

**Comportamiento requerido.** Las tareas no deben desaparecer directamente de la base
de datos. Deben pasar primero a una papelera mediante campos como:

```text
deletedAt
deletedBy
deletionReason
previousStatus
```

La papelera debe permitir:

- Consultar las tareas eliminadas.
- Restaurarlas.
- Conservar su contenido original.
- Mantener fecha de creación, estado anterior y contexto.
- Saber qué orden provocó la eliminación.

**Papel de Engram.** Engram debe guardar el contexto de la acción: qué pidió el
usuario, qué interpretó NEXUS, qué elementos se iban a eliminar, qué confirmación
recibió, qué operación terminó ejecutándose y qué resultado tuvo. Engram puede actuar
como respaldo contextual y de auditoría, pero la restauración exacta debe apoyarse
también en persistencia estructurada o una papelera en la base de datos.

**Criterios de aceptación**

- Una tarea eliminada puede restaurarse con todos sus datos.
- Reiniciar NEXUS no elimina la papelera.
- Engram conserva el contexto de la eliminación.
- La restauración no depende únicamente de reconstruir la tarea desde un modelo de lenguaje.

---

## FASE 2 — Redefinir la arquitectura de memoria

### TAREA 4. Corregir la definición y el uso de Engram

**Problema.** Engram se ha descrito como una memoria exclusivamente orientada a
proyectos de programación, arquitectura, bugs y código. Esa definición no corresponde
al uso requerido dentro de NEXUS.

**Definición correcta.** Engram debe funcionar como la memoria operativa y de
comportamiento de NEXUS. Debe recordar:

- Órdenes permanentes del usuario.
- Preferencias de funcionamiento.
- Formas de responder.
- Maneras de actuar.
- Decisiones tomadas.
- Procedimientos acordados.
- Restricciones.
- Correcciones realizadas por el usuario.
- Errores que no deben repetirse.
- Reglas de delegación entre NEXUS y Hermes.
- Convenciones de organización.
- Acciones relevantes realizadas anteriormente.
- Contexto necesario para continuar trabajos posteriores.

Engram no debe limitarse al código. Puede recordar decisiones técnicas cuando existan,
pero también cualquier decisión operativa necesaria para que NEXUS trabaje de forma
consistente.

**Ejemplos de recuerdos de Engram**

```text
Antes de borrar tareas, NEXUS debe mostrar los elementos afectados y pedir confirmación.
NEXUS no debe leer en voz alta el texto que escribe el usuario.
Hermes puede ejecutar una tarea, pero NEXUS es quien devuelve la respuesta final.
Los documentos deben guardarse en la carpeta indicada por el usuario.
Cuando haya trabajos en segundo plano, el sidebar debe mostrar su estado.
```

**Criterios de aceptación**

- Engram admite recuerdos técnicos y no técnicos.
- Los recuerdos se clasifican por tipo, relevancia y ámbito.
- NEXUS consulta los recuerdos relevantes antes de ejecutar una acción.
- Las correcciones explícitas del usuario tienen prioridad sobre comportamientos anteriores.
- Los recuerdos no se convierten automáticamente en tareas.
- NEXUS puede explicar qué regla de memoria ha aplicado sin repetir todo el historial.

### TAREA 5. Separar claramente Engram del RAG documental

**Engram** — memoria de comportamiento, decisiones y continuidad: cómo quiere trabajar
el usuario, qué decisiones se tomaron, qué errores deben evitarse, cómo deben
comportarse NEXUS y Hermes, qué preferencias son persistentes, qué contexto operativo
debe mantenerse entre conversaciones.

**RAG vectorial** — conocimiento recuperable procedente de información concreta:
documentos, PDF, DOCX, Markdown, manuales, especificaciones, informes, proyectos,
bases de conocimiento, fragmentos indexados y contenido aportado por el usuario.

**Flujo recomendado**

1. NEXUS interpreta la petición.
2. Consulta Engram para recuperar reglas, decisiones y preferencias relevantes.
3. Consulta el RAG cuando necesita información contenida en documentos.
4. Combina ambos contextos sin mezclarlos.
5. Decide si puede responder o debe delegar la ejecución a Hermes.
6. Devuelve una única respuesta final al usuario.

**Criterios de aceptación**

- Engram no se utiliza como almacén masivo de documentos.
- El RAG no se utiliza como sustituto de las reglas de comportamiento.
- Se puede identificar de dónde procede cada dato recuperado.
- Los recuerdos de Engram tienen categorías y prioridad.
- Los documentos del RAG incluyen metadatos de origen, archivo, fecha y fragmento.
- NEXUS evita introducir toda la memoria y todos los documentos en cada prompt.

### TAREA 6. Mejorar la recuperación de memoria para evitar respuestas repetitivas

**Problema.** NEXUS devuelve con frecuencia la misma respuesta, aunque la petición o el
contexto hayan cambiado.

**Posibles causas que deben revisarse**

- Recuperación siempre de los mismos recuerdos.
- Umbral de similitud demasiado bajo.
- Falta de diversidad en los resultados vectoriales.
- Prompt del sistema demasiado rígido.
- Respuestas anteriores guardadas incorrectamente como reglas.
- Caché de respuesta mal invalidada.
- Historial duplicado.
- Falta de ponderación por fecha, relevancia o tipo de memoria.
- Recuperación excesiva de fragmentos.
- Engram y RAG mezclados en una única búsqueda.

**Trabajo requerido**

- Separar búsqueda de recuerdos y búsqueda documental.
- Aplicar filtros por usuario, agente, proyecto y ámbito.
- Limitar el número de resultados recuperados.
- Añadir puntuación por relevancia.
- Reducir recuerdos redundantes.
- Evitar almacenar respuestas completas como reglas permanentes.
- Deduplicar resultados similares.
- Invalidar la caché cuando cambie el estado de una tarea o conversación.
- Registrar qué recuerdos y documentos se utilizaron para cada respuesta.

**Criterios de aceptación**

- Preguntas diferentes no reciben automáticamente la misma respuesta.
- NEXUS adapta la respuesta al estado actual.
- Los recuerdos irrelevantes no se inyectan en el contexto.
- Se puede inspeccionar qué memoria provocó una respuesta.
- Las pruebas incluyen conversaciones sucesivas con cambios de contexto.

---

## FASE 3 — Corregir el funcionamiento de voz y chat

### TAREA 7. Evitar que NEXUS lea en voz alta los mensajes del usuario

**Problema.** Cuando el usuario escribe por chat, NEXUS reproduce o lee en voz alta el
mismo texto.

**Comportamiento requerido**

- El texto escrito por el usuario nunca debe enviarse directamente al sistema de síntesis de voz.
- Solo se puede reproducir la respuesta generada por NEXUS.
- La reproducción debe depender de la configuración de voz.
- La entrada por texto y la entrada por voz deben tratarse de forma diferente.
- La transcripción de voz tampoco debe reproducirse como si fuera una respuesta.

**Flujo correcto**

```text
Usuario escribe
    ↓
NEXUS procesa el mensaje
    ↓
NEXUS genera respuesta
    ↓
Solo la respuesta puede enviarse a TTS
```

**Criterios de aceptación**

- Escribir un mensaje no provoca ninguna lectura del mensaje del usuario.
- El TTS recibe exclusivamente mensajes con rol `assistant`.
- La entrada transcrita desde el micrófono no se reproduce.
- Se puede desactivar completamente la respuesta por voz.
- Las pruebas cubren texto, micrófono, interrupción y respuesta cancelada.

---

## FASE 4 — Orquestación entre NEXUS y Hermes

### TAREA 8. Establecer el flujo correcto NEXUS → Hermes → NEXUS

**NEXUS.** Recibe la petición del usuario; interpreta la intención; consulta Engram;
consulta el RAG cuando sea necesario; decide si la tarea puede responderse
directamente; delega en Hermes cuando se requiere ejecución; informa del estado del
trabajo; devuelve el resultado final al usuario.

**Hermes.** Ejecuta las herramientas necesarias; realiza operaciones sobre archivos;
lleva a cabo procesos largos o en segundo plano; informa a NEXUS del progreso; devuelve
un resultado estructurado; no debe mantener una conversación paralela con el usuario
salvo que se diseñe expresamente.

**Flujo esperado**

```text
Usuario
   ↓
NEXUS recibe la petición
   ↓
NEXUS consulta memoria y conocimiento
   ↓
NEXUS delega en Hermes cuando corresponde
   ↓
Hermes ejecuta la operación
   ↓
Hermes devuelve estado y resultado
   ↓
NEXUS presenta la respuesta final
```

**Criterios de aceptación**

- Hermes no inicia tareas que el usuario no ha solicitado.
- NEXUS no devuelve resultados ficticios.
- NEXUS espera un resultado real de Hermes antes de afirmar que algo funciona.
- No se producen dos respuestas finales para la misma petición.
- La respuesta final indica claramente si la tarea terminó, falló o quedó incompleta.
- Cada ejecución tiene un identificador único.
- Se registra qué agente realizó cada acción.

### TAREA 9. Evitar ejecuciones fantasma o respuestas no solicitadas

**Trabajo requerido**

- Asociar cada ejecución a un `requestId`.
- Asociar cada petición a una conversación y usuario.
- Cancelar trabajos obsoletos cuando corresponda.
- Evitar que una respuesta antigua se muestre como resultado de una petición nueva.
- Validar que NEXUS solo devuelva resultados relacionados con la solicitud activa.
- Limpiar correctamente colas, estados y listeners al reiniciar la aplicación.

**Criterios de aceptación**

- No se ejecutan tareas sin una petición válida.
- Cada respuesta corresponde al `requestId` correcto.
- Las respuestas de procesos antiguos no aparecen en conversaciones nuevas.
- Los trabajos duplicados se detectan y bloquean.
- El usuario puede consultar qué tarea está ejecutándose.

---

## FASE 5 — Sistema de multitarea y trabajos en segundo plano

### TAREA 10. Mostrar el estado de las tareas en segundo plano en el sidebar

Junto al apartado «Multitarea» del sidebar debe aparecer un indicador dinámico.

Estados posibles: sin indicador (no hay tareas activas ni resultados pendientes);
`En curso` (una única tarea ejecutándose); un número, por ejemplo `3` (tres tareas en
ejecución); una marca de finalización (una o varias tareas han terminado y todavía no
se ha revisado su resultado); indicador de error (alguna tarea ha fallado).

```text
Multitarea       En curso
Multitarea       3
Multitarea       ✓
Multitarea       !
```

**Criterios de aceptación**

- El contador coincide con el número real de tareas activas.
- El indicador se actualiza sin recargar la página.
- Al terminar una tarea se muestra una marca visible.
- NEXUS devuelve automáticamente el resultado final cuando esté disponible.
- Abrir Multitarea muestra el historial y el estado de cada ejecución.
- Una tarea fallida no aparece como completada.
- El indicador se limpia cuando el usuario revisa los resultados.

### TAREA 11. Crear un modelo de estados para las ejecuciones

```text
queued
running
waiting_confirmation
completed
failed
cancelled
```

Cada ejecución debe guardar: identificador, petición original, agente responsable,
fecha de inicio, fecha de finalización, estado actual, progreso, resultado, error,
archivos creados o modificados, confirmaciones solicitadas y confirmaciones recibidas.

**Criterios de aceptación**

- NEXUS puede informar del estado real de cada tarea.
- Hermes actualiza el progreso de forma estructurada.
- El sidebar se alimenta del estado persistido.
- Reiniciar la interfaz no pierde las tareas activas.
- Los errores incluyen información útil y no se ocultan.

### TAREA 12. Notificar correctamente la finalización de trabajos

Cuando Hermes termine una tarea: actualiza su estado a `completed`; envía a NEXUS el
resultado estructurado; el sidebar muestra la marca de finalización; NEXUS devuelve el
resultado al usuario; se indican los archivos creados o modificados; la respuesta no
afirma que algo funciona si no se ha verificado.

**Criterios de aceptación**

- Cada tarea completada genera una única notificación.
- No se notifican trabajos todavía en curso.
- Las tareas fallidas muestran el error real.
- NEXUS diferencia entre «creado», «modificado», «verificado» y «pendiente de verificar».

---

## FASE 6 — Gestión de tareas personales

### TAREA 13. Implementar recordatorios periódicos de las tareas de hoy

Los recordatorios deben tener en cuenta: prioridad, hora límite, tiempo desde el último
recordatorio, estado de la tarea, si el usuario ya la ha pospuesto, si el usuario está
ejecutando otra tarea, y el horario de descanso o modo no molestar.

**Reglas recomendadas**

- No recordar tareas completadas.
- No repetir continuamente el mismo aviso.
- Agrupar tareas relacionadas.
- Priorizar tareas próximas a vencer.
- Permitir posponer un recordatorio.
- Permitir desactivar temporalmente los avisos.
- Registrar cuándo se envió el último recordatorio.

**Criterios de aceptación**

- NEXUS recuerda únicamente tareas pendientes o en curso.
- Los recordatorios no son excesivos.
- Una tarea completada deja de aparecer.
- El usuario puede indicar «recuérdamelo más tarde».
- El sistema no depende de mantener abierta la pantalla «Hoy».

### TAREA 14. Mejorar la persistencia de tareas personales

Las tareas deben almacenarse de forma estructurada y no depender únicamente del
contexto conversacional. Cada tarea debe incluir:

```text
id
title
description
status
priority
dueDate
reminderAt
createdAt
updatedAt
completedAt
deletedAt
sourceConversationId
```

Engram debe recordar decisiones relacionadas con la gestión de tareas, pero la base de
datos debe conservar el contenido exacto de cada tarea.

**Criterios de aceptación**

- Las tareas sobreviven a reinicios.
- NEXUS puede recuperar las tareas creadas anteriormente.
- Las tareas no desaparecen al resumir o limpiar la conversación.
- Engram conserva las preferencias de gestión.
- La base de datos conserva los registros exactos.

---

## FASE 7 — Simplificación de la pantalla «Hoy»

### TAREA 15. Mover la temperatura al header

Mostrar en el header: icono meteorológico, temperatura actual, opcionalmente ubicación
y, opcionalmente, máxima y mínima al desplegar el componente.

```text
Madrid · 27 °C
```

**Criterios de aceptación**

- La temperatura aparece en el header.
- No ocupa una pantalla completa.
- El componente se adapta a escritorio y móvil.
- Un fallo del servicio meteorológico no bloquea el resto de NEXUS.

### TAREA 16. Eliminar o simplificar la pantalla «Hoy»

Eliminar la pantalla independiente si su única función era mostrar la temperatura y un
resumen mínimo. La información útil debe redistribuirse: temperatura al header; tareas
al módulo de tareas; trabajos activos a Multitarea; agenda al módulo de calendario;
recordatorios a las notificaciones de NEXUS.

**Criterios de aceptación**

- No se duplica información entre pantallas.
- El sidebar deja de mostrar una sección innecesaria.
- Las funcionalidades existentes siguen accesibles desde sus módulos correspondientes.
- Las rutas antiguas se eliminan o redirigen correctamente.

---

## FASE 8 — Corrección visual del sidebar

### TAREA 17. Sustituir los iconos no coloreables por SVG compatibles

**Problema.** Hay tres iconos del sidebar que no reciben correctamente el color activo
o inactivo.

**Trabajo requerido**

- Localizar los tres iconos afectados.
- Sustituir imágenes, emojis o SVG con colores fijos.
- Usar SVG con `currentColor`.
- Aplicar el color desde CSS.
- Unificar tamaño, grosor y alineación.
- Verificar estados normal, hover, activo, foco y deshabilitado.

```svg
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
  ...
</svg>
```

**Criterios de aceptación**

- Todos los iconos reciben el color del texto.
- Ningún icono contiene colores incrustados que impidan personalizarlo.
- El estado activo es visualmente consistente.
- Los iconos funcionan en tema claro y oscuro.
- Los iconos tienen nombre accesible cuando sea necesario.
- Las pruebas visuales cubren todas las entradas del sidebar.

---

## FASE 9 — Operaciones sobre archivos

### TAREA 18. Permitir que NEXUS y Hermes lean archivos reales

**Formatos mínimos:** `.md`, `.txt`, `.docx`, `.pdf`.
**Opcionalmente:** `.json`, `.csv`, `.xlsx`, imágenes, código fuente.

NEXUS y Hermes deben poder abrir archivos, leer su contenido, buscar información,
resumirlos, compararlos, extraer datos, utilizar su contenido como contexto y consultar
el RAG documental cuando estén indexados.

**Criterios de aceptación**

- Se informa cuando un formato no es compatible.
- Los PDF con texto se leen correctamente.
- Los DOCX conservan el contenido textual y la estructura básica.
- No se afirma que un archivo se ha leído sin haberlo abierto realmente.
- Los errores de permisos o rutas se muestran claramente.

### TAREA 19. Implementar CRUD real sobre archivos

**Crear:** archivos `.md`, `.docx`, `.txt` y otros formatos compatibles; carpetas cuando
sea necesario y esté autorizado.
**Leer:** archivos existentes; detectar codificación y formato.
**Actualizar:** modificar contenido, añadir secciones, corregir texto, renombrar
archivos, convertir formatos cuando sea posible.
**Eliminar:** solicitar confirmación obligatoria; mover primero a papelera o crear copia
de seguridad; registrar la operación.

**Criterios de aceptación**

- NEXUS y Hermes pueden trabajar sobre archivos existentes.
- La actualización no destruye accidentalmente el documento original.
- Antes de sobrescribir se pide confirmación o se crea una copia versionada.
- Se informa de la ruta final.
- Se verifica que el archivo realmente existe después de crearlo.

### TAREA 20. Permitir guardar archivos en la ubicación indicada por el usuario

Ubicaciones posibles: escritorio, Documentos, Descargas, una carpeta específica, una
ruta absoluta, la carpeta de un proyecto o una carpeta nueva creada para la tarea.

```text
Guárdalo en el escritorio.
Crea el documento en D:\Proyectos\Nexus\docs.
Actualiza el archivo requisitos.md de esta carpeta.
```

**Comportamiento requerido:** resolver la ruta solicitada; validar que existe o
solicitar autorización para crearla; comprobar permisos de escritura; evitar
sobrescrituras accidentales; crear o modificar el archivo; verificar físicamente que
existe; devolver la ruta real del archivo.

**Criterios de aceptación**

- Se respeta la ubicación solicitada.
- NEXUS no inventa una ruta.
- La respuesta incluye la ruta final exacta.
- Los nombres duplicados se gestionan mediante confirmación o versionado.
- Si la ruta no existe, NEXUS lo indica claramente.

### TAREA 21. Añadir versionado y copias de seguridad de archivos

Antes de modificar un archivo existente: crear una copia temporal o versión anterior;
registrar el cambio; permitir restaurarlo; mantener relación entre archivo original y
versiones; no indexar versiones temporales duplicadas en el RAG sin control.

**Criterios de aceptación**

- Se puede restaurar la versión anterior.
- El sistema indica qué versión se modificó.
- Las copias no sobrescriben el original.
- La eliminación definitiva requiere confirmación adicional.

---

## FASE 10 — Pruebas reales y validación

### TAREA 22. Crear pruebas end-to-end reales con Playwright

**Regla obligatoria.** No se puede declarar una funcionalidad como terminada únicamente
porque el código compila, la API responde, el componente se renderiza, no aparecen
errores TypeScript o la implementación parece correcta. Debe comprobarse el flujo real
con Playwright.

**Flujos mínimos**

- *Memoria*: guardar una preferencia en Engram; reiniciar la sesión; comprobar que
  NEXUS sigue aplicándola; verificar que no recupera recuerdos irrelevantes.
- *Tareas*: crear varias tareas; marcar algunas como completadas; pedir que se eliminen
  las realizadas; verificar que solicita confirmación; confirmar; comprobar que solo
  elimina las completadas; restaurar una tarea desde la papelera.
- *Voz*: escribir un mensaje; comprobar que no se reproduce por voz; recibir una
  respuesta; comprobar que únicamente la respuesta se envía al TTS.
- *Multitarea*: iniciar una tarea larga; comprobar `En curso`; iniciar una segunda;
  comprobar el número `2`; finalizar una; verificar el contador; finalizar todas;
  verificar la marca de completado y la respuesta de NEXUS.
- *Sidebar*: comprobar todos los iconos; verificar color normal, activo y hover; probar
  tema claro y oscuro.
- *Archivos*: crear un archivo Markdown; crear un DOCX; leer un PDF; modificar un
  archivo existente; guardarlo en una carpeta concreta; verificar físicamente que
  existe; intentar sobrescribirlo y comprobar la confirmación; eliminarlo y restaurarlo.
- *Orquestación*: realizar una petición a NEXUS; verificar que crea una ejecución;
  comprobar que Hermes recibe la misma petición; verificar que la ejecuta; confirmar
  que NEXUS devuelve el resultado real; comprobar que no existen respuestas duplicadas
  ni ejecuciones fantasma.

**Evidencias obligatorias.** Cada prueba debe generar: resultado `passed` o `failed`;
capturas de pantalla cuando fallen; vídeo o trace en flujos críticos; log de consola;
peticiones de red relevantes; ruta de los archivos creados; estado antes y después de
la operación.

**Criterios de aceptación**

- Las pruebas se ejecutan contra la aplicación real.
- No se utilizan mocks para afirmar que una integración real funciona.
- Una funcionalidad no se marca como completada mientras sus pruebas fallen.
- Los errores encontrados se documentan como tareas independientes.
- Los resultados pueden reproducirse en otro equipo.

### TAREA 23. Cambiar el criterio utilizado para afirmar que algo funciona

Estados permitidos por funcionalidad:

```text
Implementado, sin verificar
Verificado mediante prueba unitaria
Verificado mediante integración
Verificado mediante Playwright
Verificado manualmente
Bloqueado
Fallido
```

**Regla.** NEXUS no debe responder «funciona correctamente» salvo que exista una prueba
real superada.

**Criterios de aceptación**

- Cada afirmación de funcionamiento incluye el tipo de validación.
- Los fallos no se ocultan.
- Los resultados de Playwright quedan vinculados a la funcionalidad.
- Las pruebas manuales y automáticas se diferencian claramente.

---

## FASE 11 — Auditoría y trazabilidad

### TAREA 24. Registrar las acciones realizadas por NEXUS y Hermes

**Datos mínimos:** usuario que solicitó la acción, petición original, agente que la
ejecutó, herramientas utilizadas, confirmaciones solicitadas, archivos afectados,
resultado, error (cuando exista), fecha y hora, identificador de ejecución.

**Criterios de aceptación**

- Se puede reconstruir qué ocurrió.
- Se puede saber por qué se eliminó o modificó algo.
- Las operaciones destructivas quedan especialmente señaladas.
- Los registros no se confunden con los recuerdos de Engram.
- La auditoría no se usa como sustituto de la base de datos o la papelera.

---

## Orden recomendado de implementación

**Prioridad crítica — P0**

1. Confirmación obligatoria antes de acciones destructivas.
2. Corrección de la eliminación selectiva de tareas.
3. Papelera y restauración de tareas.
4. Evitar ejecuciones fantasma.
5. Flujo correcto NEXUS → Hermes → NEXUS.
6. Estados reales de las tareas en segundo plano.
7. Pruebas Playwright de tareas, eliminación y orquestación.

**Prioridad alta — P1**

8. Redefinición de Engram.
9. Separación entre Engram y RAG.
10. Corrección de las respuestas repetitivas.
11. Persistencia estructurada de tareas.
12. CRUD real sobre archivos.
13. Guardado en rutas seleccionadas por el usuario.
14. Versionado y copias de seguridad.
15. Corrección del comportamiento de voz.

**Prioridad media — P2**

16. Indicador de Multitarea en el sidebar.
17. Notificación de trabajos terminados.
18. Recordatorios periódicos de tareas.
19. Sustitución de iconos por SVG coloreables.
20. Temperatura en el header.
21. Eliminación o simplificación de la pantalla «Hoy».
22. Auditoría completa de acciones.

---

## Decisiones de arquitectura fijadas

1. Engram no es exclusivamente una memoria de código. Es la memoria operativa de NEXUS:
   decisiones, reglas, preferencias y maneras de trabajar.
2. El RAG vectorial almacena y recupera conocimiento documental. Se utiliza para PDF,
   DOCX, Markdown, especificaciones y otros documentos.
3. Las tareas se almacenan en una base de datos estructurada. Engram recuerda cómo deben
   gestionarse, pero no sustituye al almacenamiento exacto.
4. Engram puede servir como respaldo contextual, pero la recuperación exacta de tareas y
   archivos requiere papelera, historial o versionado.
5. Toda acción destructiva requiere confirmación previa.
6. NEXUS es el punto de entrada y salida. Hermes ejecuta cuando sea necesario y NEXUS
   devuelve el resultado final.
7. Los trabajos en segundo plano deben ser visibles. Multitarea mostrará estado,
   contador, finalización o error.
8. NEXUS no debe leer en voz alta lo escrito por el usuario. Solo puede reproducir su
   propia respuesta.
9. NEXUS y Hermes deben poder leer, crear, actualizar y eliminar archivos reales,
   respetando las rutas indicadas y aplicando confirmaciones y copias de seguridad.
10. No se afirmará que algo funciona sin pruebas reales. Los flujos críticos deben
    validarse mediante Playwright y conservar evidencias.

---

## Estado de implementación (actualizado 2026-07-25)

Se usa la nomenclatura de la TAREA 23: nada se declara «funciona» sin decir CÓMO
se ha validado.

| Tarea | Estado |
|---|---|
| T1 · Confirmación obligatoria antes de acciones destructivas | **Verificado mediante Playwright** (tareas) + unitarias |
| T2 · Eliminación selectiva por estado real | **Verificado mediante Playwright** |
| T3 · Papelera y restauración de tareas | **Verificado mediante Playwright** |
| T4 · Engram como memoria operativa | **Verificado mediante prueba unitaria** |
| T5 · Separación Engram / RAG | **Verificado mediante prueba unitaria** |
| T6 · Recuperación sin respuestas repetitivas | **Verificado mediante prueba unitaria** |
| T7 · La voz no lee lo que escribe el operador | **Verificado mediante prueba unitaria** (falta e2e con audio real) |
| T8 · Flujo NEXUS → Hermes → NEXUS | **Verificado mediante prueba unitaria** (un encargo real necesita Hermes arrancado) |
| T9 · Ejecuciones fantasma y `requestId` | **Verificado mediante Playwright** |
| T10 · Indicador de Multitarea en el sidebar | **Verificado mediante Playwright** |
| T11 · Modelo de estados de las ejecuciones | **Verificado mediante Playwright** |
| T12 · Notificación de trabajos terminados | **Verificado mediante Playwright** |
| T13 · Recordatorios periódicos | **Verificado mediante prueba unitaria** |
| T14 · Persistencia estructurada de tareas | **Verificado mediante prueba unitaria** |
| T15 · Temperatura en el header | **Verificado mediante Playwright** |
| T16 · Pantalla «Hoy» eliminada | **Verificado mediante Playwright** |
| T17 · Iconos del sidebar en SVG coloreables | **Verificado mediante Playwright** |
| T18 · Lectura real de archivos (.md/.txt/.docx/.pdf) | **Verificado mediante prueba unitaria** |
| T19 · CRUD real sobre archivos | **Verificado mediante prueba unitaria** |
| T20 · Guardar en la ubicación indicada | **Verificado mediante prueba unitaria** |
| T21 · Versionado y copias de seguridad | **Verificado mediante prueba unitaria** |
| T22 · Pruebas end-to-end con Playwright | **Verificado**: 4 flujos, evidencias en `data/e2e/` |
| T23 · Criterio para afirmar que algo funciona | Esta tabla ES el criterio, y se actualiza con cada cambio |
| T24 · Auditoría y trazabilidad | **Verificado mediante prueba unitaria** |

Pendiente de cubrir con Playwright (su lógica sí está probada en unitarias):
el flujo de archivos por la interfaz, la voz con audio real del navegador y un
encargo real de punta a punta contra el gateway de Hermes.

### Módulos nuevos

- `backend/core/confirm.py` — puerta de confirmación por canal (T1).
- `backend/core/audit.py` — `data/logs/audit.jsonl` (T24).
- `backend/core/opmem.py` — memoria operativa de Engram (T4-T6).
- `backend/core/files_io.py` — lectura/escritura real y versionado (T18-T21).
- `tests/e2e/run_e2e.py` — pruebas end-to-end reales con evidencias (T22).

### Cómo se comprueba todo

```bat
python tests/run_all.py          REM contrato: TODO VERDE
python tests/e2e/run_e2e.py      REM interfaz real: 4/4 flujos passed
```
