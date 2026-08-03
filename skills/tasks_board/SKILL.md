# ▦ Skill: Tablero de tareas (kanban estilo Notion / Lumi)

Kanban con 4 estados: **pendiente → en progreso → en revisión → completada**.
nexus distingue tareas de HACER (🛠 «crear una web») de EVENTOS de calendario
(📅 «mentoría el jueves a las 18»), extrae fecha límite y hora del texto, mueve
tareas por voz/texto, avisa de retrasos y prioriza con la matriz de Eisenhower.

## Órdenes de ejemplo (frases que los patrones cazan de verdad)

- "crea la tarea diseñar calcetines para el viernes prioridad alta" → 🛠 acción
  con fecha límite y prioridad.
- "crea una tarea" / "créame una tarea" / "ponme otra tarea" → no crea nada:
  PREGUNTA de qué va. Sin asunto no hay tarea, porque una titulada «nueva» es
  peor que ninguna.
- "apunta la mentoría el jueves a las 18" / "anótame la clase de inglés el
  martes a las 5 de la tarde" → 📅 evento con fecha+hora; si Google Calendar
  ya está autorizado, se apunta también allí (nunca dispara el OAuth desde
  aquí). Ojo: «apunta la reunión/cita/evento...» lo captura antes la skill de
  Google Calendar (va antes en el router) — mismo resultado para el operador.
- "crea una tarea del miércoles al domingo que sea Festival Sonorama" /
  "crea una tarea del 5 al 9 de agosto que sea Feria del libro" → 📅 evento de
  VARIOS DÍAS: se guardan las dos fechas y en Google Calendar ocupa la franja
  entera, no un punto suelto. La agenda del HUD lo pinta en todos sus días.
- "crea una tarea desde el miércoles a las 15 hasta el domingo que sea Sonorama"
  → el rango con hora arranca a esa hora y termina al acabar el último día; un
  rango de días pelados es evento de día completo.
- El asunto puede ir DETRÁS de las fechas, con «que sea», «que es», «y es»,
  «llamada/titulada» o dos puntos: el título es lo que va después. El relleno
  («que dure», «como una entrada de google calendar», «en el calendario») no
  entra en el título. Si al quitarlo no queda asunto, PREGUNTA en vez de
  inventarse uno — y te dice qué fechas ya ha entendido.
- "mueve diseñar calcetines a en progreso" / "pasa el informe a review" /
  "cambia la web a completadas" — acepta también «en curso», «doing», «done».
- "me pongo con la web del cliente" / "arranco con el logo" → atajo directo
  a EN PROGRESO.
- "ver tablero" / "muéstrame mis tareas" / "qué tengo pendiente" — cualquier
  frase natural de consultar tareas enseña el resumen por columnas (también
  con el botón ▦ TAREAS del HUD).
- "qué tareas van retrasadas" / "tareas fuera de plazo" → 🔴 vencidas y
  🟡 a punto de vencer.
- "organiza mis tareas por urgencia" / "prioriza el tablero" → matriz
  Eisenhower (hacer ya / planificar / delegar / revisar).
- "borra la tarea diseñar logo" / "bórrame la tarea X" / "elimíname la tarea X"
  → PREVISUALIZA las coincidencias (duplicados incluidos) y PIDE CONFIRMACIÓN
  antes de tocar nada.
- "borra las tareas completadas" / "bórrame las ya realizadas" / "limpia las ya
  realizadas" / "vacía el tablero" → limpieza masiva, siempre con confirmación
  previa y con el recuento de qué se va y qué se queda.
- "recupera las tareas borradas" / "deshaz el borrado" → devuelve el ÚLTIMO lote
  borrado, cada tarea a su columna anterior. "restaura la tarea X" devuelve solo
  la que casa con ese título.
- "ver la papelera" / "qué tareas has borrado" → contenido de la papelera.
  "vacía la papelera" → borrado FÍSICO, con una confirmación extra.

## Seguridad de los borrados (specs v23, TAREAS 1-3)

Motivo: el 25/07/2026 la orden «limpia las tareas ya realizadas» vació las 15
tareas del tablero (completadas Y pendientes) y no hubo forma de recuperarlas.

- **Nada se borra sin confirmación explícita.** El handler NUNCA ejecuta el
  borrado: arma la acción en `backend/core/confirm.py` y devuelve la pregunta
  con el recuento y la lista de afectadas. El brain resuelve el «sí»/«no»
  antes que ningún router. Si el operador contesta otra cosa, la confirmación
  se DESCARTA (no se queda armada esperando un «sí» suelto más tarde) y caduca
  a los 5 minutos.
- **El ámbito sale del estado real** (`board.select`): «ya realizadas /
  hechas / finalizadas / listas» = SOLO `completada`. Para vaciar el tablero
  entero hay que decirlo con esas palabras («todas las tareas», «el tablero»).
  Si la orden es ambigua, se arma la opción SEGURA (solo completadas) y se
  avisa de ello — jamás el borrado total.
- **Borrado lógico:** todo va a `data/board_trash.json` con `deletedAt`,
  `deletedBy`, `deletionReason`, `previousStatus` y un `batch` por lote, para
  poder deshacer el último borrado entero. `purge_trash()` (borrado físico)
  exige una confirmación adicional.
- **Auditoría:** cada operación destructiva deja línea en
  `data/logs/audit.jsonl` (qué se pidió, qué se interpretó, qué confirmación
  hubo, qué se ejecutó y con qué resultado).

## Notas técnicas

- Fechas entendidas: «para el 25/07», «antes del viernes», «fecha límite 30 de
  julio», «para mañana»; en eventos también «el jueves» sin «para», y «mañana»
  u «hoy» sueltos («llamar al fontanero mañana»). «de la mañana» / «por la
  mañana» siguen siendo la franja horaria, no el día. Horas: «a las 18»,
  «a las 9:30», «a la 1 y media de la tarde».
- RANGOS de varios días: «del miércoles al domingo», «desde el miércoles hasta
  el domingo», «del 5 al 9», «del 5 al 9 de agosto». Se guardan `due` (primer
  día) y `dueEnd` (último, inclusive). Al mandarlo a Google, los eventos de día
  completo llevan el fin +1 día porque Google trata `end.date` como EXCLUSIVO:
  sin ese ajuste el último día del festival no se pintaba.
- El estado vive en backend.core.board; el volcado a Google Calendar reutiliza
  la skill google_workspace y solo actúa si su token OAuth ya existe.
- Toques de atención automáticos: el scheduler revisa el tablero y avisa por el
  HUD (y Telegram si está conectado) cuando una tarea vence o se pudre en
  pendientes — máximo un toque por tarea cada 4 horas.
- Ojo al orden de intents: «show» es amplísimo adrede (petición de Adri:
  «siempre que le diga algo de tareas tiene que poder verlas») y DEBE quedarse
  el ÚLTIMO del dict; los intents específicos ganan por evaluarse antes.
