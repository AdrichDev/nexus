# SPECS v21 — 3 arreglos reales por queja directa de Adri
_2026-07-24 · Cada arreglo con su criterio de aceptación y el RESULTADO de la validación
(suite completa: `python tests/run_all.py` → TODO VERDE, 687 checks; revisión de código
adversaria con modelo opus: 1 hallazgo confirmado (negrita borrada en `_perfil_natural`),
corregido y cubierto con test; QA final independiente con modelo sonnet: NO APTO en la
primera pasada — encontró que la corrección de opus no cerraba el bug del todo (una
negrita SIN guión de viñeta delante seguía dejando asteriscos sueltos) y un segundo
hallazgo (excepción sin capturar en el respaldo de WhatsApp por móvil); ambos corregidos
y cubiertos con test; segunda pasada → APTO)._

## FIX 1 — «quién soy» ya no es una ficha de estadísticas
**Queja textual:** *"No puede dar estas respuestas cuando se le pregunte que si sabe
quien soy, simplemente tiene que consultar conocimiento si a caso y responder pero ni
mucho menos listar y dictarme todo eso de temas y proyectos recurrentes, optimizacion,
memoria de grafo? que tipo de mierda has construido?"*
**Qué:** `backend/core/profile.py` → `build_profile()` reescrito de raíz. Antes: ficha
con cabecera «🧬 Lo que sé de ti», el perfil markdown completo de `selflearn` (con
cabeceras **X** y viñetas tal cual), y contadores de tablero/agenda/vigilancias/encargos/
informes/notas/objetivos. Ahora: 1-2 frases naturales — «Eres Adri. `<resumen breve>`.» —
usando el nuevo helper `_perfil_natural()`, que convierte el markdown destilado en prosa
corrida: las cabeceras PURAS de sección (sin contenido en su línea) se descartan por ser
solo una etiqueta, pero la negrita DENTRO de una frase se DESENNEGRECE (se conserva el
texto, solo se quitan los `**`) — nunca se borra contenido. Los contadores de actividad
ya NO salen aquí (siguen disponibles por su propia vía: «mis informes», panel ☀ Hoy...);
mezclarlos en «quién soy» era precisamente lo que sonaba a informe robótico.
**✔ VALIDADO:** 21 checks en `tests/test_specs_v20.py::test_profile_build` +
`test_perfil_natural_helper` (nombre+perfil, sin perfil, sin nombre, excepción de
selflearn, negrita a mitad de frase, expresión citada en negrita, cabecera+contenido en
una línea, negrita sin guión delante, truncado sin partir palabras, ausencia de TODOS los
marcadores viejos de ficha).

## FIX 2 — WhatsApp con n8n caído ya no falla en seco: cae al móvil
**Queja textual (con el error real pegado):** *"le eh dicho whatsap a mami y me sale
'No llego al webhook de n8n (HTTP 404)...' ... cuando lo unico que tiene que comprobar
es que tiene la conexion con whatsap."*
**Qué:** `skills/n8n_flows/skill.py` → `handle()` del intent `whatsapp`. Antes: si
`n8n_webhook_url` estaba configurada (aunque estuviera caída/obsoleta/con el flujo
inactivo), el fallo del POST devolvía un error técnico plano — nunca se probaba el móvil
vinculado. Ahora: si hay n8n configurado se intenta primero (envío 100% automático), pero
si falla, cae AUTOMÁTICAMENTE al móvil vinculado (estilo Android Auto) — el WhatsApp se
abre en el teléfono con el chat y el texto ya escritos. Solo si TAMPOCO hay móvil
vinculado se explica qué falta. Nuevo envoltorio `_safe_whatsapp_via_movil()`: si el
propio respaldo por móvil revienta por cualquier motivo, se trata igual que «no hay
móvil» en vez de propagar la excepción al usuario como un error interno en crudo.
**✔ VALIDADO:** 12 checks en `tests/test_v21_fixes.py` (n8n caído+móvil → por móvil sin
exponer el error técnico; n8n caído+sin móvil → explica el fallo real; n8n funcionando →
sin regresión, sigue por n8n; sin n8n+móvil / sin n8n+sin móvil → sin regresión; `flow`
sigue exigiendo n8n tal cual, sin mezclarse con la lógica de móvil; el móvil que revienta
no propaga la excepción).

## FIX 3 — el enrutador de respaldo por LLM ya no interpreta a ciegas
**Queja textual:** *"si le digo que esta todo arrancado me sale con hermes, cuando lo
unico que tiene que comprobar es que tiene la conexion con whatsap... NO ENTIENDO POR QUE
ES TAN ROBOTICO."*
**Causa real:** `plan_action()` e `interpret_command()` (backend/core/llm.py) — el
planificador y el reescritor de respaldo que entran en juego cuando ninguna skill casó
por regex — no recibían NADA de historial de conversación. Una frase corta y ambigua
como «está todo arrancado» se interpretaba SOLO por coincidencia de palabras sueltas con
el catálogo de skills, y el catálogo de Hermes menciona «arrancado/encendido/activo» en
su descripción de estado → delegaba en Hermes sin ninguna relación real con el WhatsApp
que se venía hablando.
**Qué:** ambas funciones ganan un parámetro `recent_context` (últimas 1-2 vueltas de la
conversación), que se añade al prompt SOLO para que el modelo entienda el TEMA real antes
de decidir — nunca como orden a ejecutar (instrucción explícita anti-inyección en ambos
prompts). Nuevo helper `backend/core/brain.py::_recent_context()` que arma ese contexto
desde el historial en RAM, con las frases recortadas a 160 caracteres por línea para no
inflar el prompt. Los dos puntos de llamada en `brain.process()` quedan enganchados.
**✔ VALIDADO:** 11 checks en `tests/test_v21_fixes.py` (helper con historial vacío/
impar/entradas sin contenido/frases largas recortadas; `plan_action` e
`interpret_command` reciben de verdad el contexto en su prompt vía un proveedor LLM
falso — no un mock de la función, sino de `chat()` — y NO lo añaden cuando no hay
contexto; verificación de integración por grep de que `brain.py` pasa
`recent_context=_recent_context()` en LOS DOS sitios).

## Revisión y endurecimiento (opus + sonnet, dos pasadas)
1ª pasada (opus): la limpieza de negrita en `_perfil_natural` borraba CONTENIDO junto con
los `**` cuando la negrita estaba dentro de una viñeta («**"está todo arrancado"**: ...»
perdía justo la frase citada) — corregido: la negrita se desenvuelve conservando el
texto, solo las cabeceras de sección PURAS (sin contenido propio) se descartan.
2ª pasada (sonnet, NO APTO en la primera vuelta): la corrección de opus no cerraba el
bug del todo — una negrita que abre la línea SIN guión de viñeta delante («**Odia**...»)
dejaba un `*Odia**` roto, porque el regex de viñeta también casa con un solo `*` y se
aplicaba ANTES de desenvolver la negrita; se corrigió el ORDEN (negrita primero, viñeta
después). Además: `_whatsapp_via_movil()` sin capturar podía propagar una excepción
interna como el mismo error técnico en crudo que el fix quería eliminar; se blindó con
`_safe_whatsapp_via_movil()`. Segunda pasada de sonnet tras corregir ambos: APTO.
