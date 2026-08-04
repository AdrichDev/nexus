# Propuesta: voz propia y personalidades

## El problema, en los términos del dueño

nexus contesta como un volcado de fichero clasificado: secciones, títulos,
viñetas y emojis donde tocaba una conversación.

Eso está arreglado **en un sitio y solo en uno**. `skills/memory_graph/skill.py`,
intent `list_knowledge` (líneas 257-310): reúne únicamente lo que es del
operador, se lo pasa al modelo y le hace narrarlo, con una regla explícita —«usa
ÚNICAMENTE lo que hay aquí abajo. No añadas, no supongas y no rellenes»— y
prohibición de secciones, viñetas y emojis. Cincuenta líneas más abajo, el intent
`recall` del mismo fichero sigue devolviendo `• [DB] …` línea a línea. La cura
existe; está aplicada a una frase.

Y hay un malentendido que conviene deshacer antes de diseñar nada: **las
personalidades ya existen**. `backend/core/llm.py:45` define `PERSONALITIES` con
seis presets (`jarvis`, `profesional`, `colega`, `sargento`, `zen`, `canalla`),
cada uno con su bloque de prompt; `config.py:113` fija `"personality": "jarvis"`;
`frontend/setup.html` las ofrece en su **paso 2**, `backend/app.py:1365` las
sirve por API y `_build_messages()` (línea 831) las inyecta en el hueco
`{personality}` del `SYSTEM_PROMPT`. Ya se eligen en la instalación y ya se
cambian en ⚙.

Lo que falta no es el mecanismo: es **este catálogo y una propia**. Las que pidió
el dueño —técnico/project manager, alegre y sincera, sereno y directo, seguro y
optimista, inteligente y relajada— no son estas seis, y **no hay ninguna manera
de escribir la tuya**.

## Alcance

### Dentro

| Entrega | Qué es |
| --- | --- |
| **Catálogo nuevo** | Las personalidades que pidió el dueño, sobre el contrato de `PERSONALITIES` que ya existe |
| **Personalidad propia** | Escrita a mano o traída en un `.md`. Es un fichero, no código |
| **Puerta de honestidad** | Una personalidad no puede autorizar a inventar. Comprobado por código |
| **Narrar en vez de listar** | La cura de `list_knowledge` extendida a lo que hoy son fichas |
| **Elegir y cambiar** | En la instalación (paso 2, que ya está) y en ⚙ después |

### Fuera

- **Un segundo sistema de personalidades.** Se extiende el que hay.
- Voz TTS, timbre y velocidad: eso es `tts_voice`, otra cosa.
- Tocar el `SYSTEM_PROMPT` fuera del hueco `{personality}`.
- Que la personalidad se aprenda sola (sería 004, y no se pide).
- Horarios (→ `005`). Instalador y actualizaciones (→ `007`).

## Capacidades

### Nuevas

- `voz-personalidades`: el catálogo, su contrato y dónde se declara
- `voz-personalidad-propia`: escribir la tuya, validarla y activarla
- `voz-narrativa`: cuándo se narra y cuándo sigue estando bien listar

### Modificadas

Ninguna. `content-os-honestidad` habla del contenido generado para publicar, no
del tono de la conversación; esta propuesta no la toca y **no puede debilitarla**.

## Enfoque

**El tono es una capa; los hechos son el suelo.** Es la única decisión de verdad
aquí, y la posición en el prompt ya la respalda.

Mírese el orden real de `_build_messages()`: la personalidad entra **arriba**, en
`{personality}` (línea 110 del `SYSTEM_PROMPT`); la REGLA INVIOLABLE de no
inventar cifras se concatena **al final** (línea 869), y el propio comentario del
código explica por qué: «va a lo último del prompt a propósito, que es lo que más
pesa». Ese orden se mantiene intacto. Una personalidad —incluida la propia— entra
**solo** en el hueco de arriba. Nada de texto de usuario detrás de la regla.

**La personalidad propia es dato, no código.** Vive en
`data/personalidad_propia.md` y se activa con `personality: "propia"`, una clave
más del `settings.json` que ya existe. Escribirla a mano o soltar un `.md` es lo
mismo: el fichero. Consecuencia directa, la de 004: deshacerlo es borrar un
fichero, sin repositorio y sin suite.

**Una personalidad no puede dar permiso para inventar.** Aquí está el riesgo
real. Un texto propio que diga «nunca digas que no sabes algo» o «si no tienes el
dato, estima» desmonta en una línea lo que costó el incidente del 31/07 —un
perfil de Instagram entero inventado, 1,2M de seguidores cuando eran 78.500—. Por
eso una puerta determinista rechaza el texto propio si intenta autorizar
invención, simular trabajo hecho o suprimir el «no lo sé», y la respuesta dice
**qué línea** lo tumbó. El LLM no participa en esa decisión.

Detrás siguen, sin tocarse, los dos cinturones que ya hay:
`publicvoice.sanitize()` como última barrera antes del chat, y la REGLA
INVIOLABLE al final del prompt. El tono cambia; lo que se puede afirmar, no.

**Narrar no es narrarlo todo.** Se narra lo que es conversación —lo que sabe de
ti, un resumen, una explicación—. Un listado de tareas, un informe con cifras o
un diagnóstico de servicios siguen siendo listas: convertirlos en prosa esconde
datos. La spec dirá cuáles, uno por uno.

En el ciclo cerrado de Content OS esto no toca ninguna etapa: es presentación.

## Áreas afectadas

| Área | Impacto | Qué cambia |
| --- | --- | --- |
| `backend/core/llm.py` | Modificada | Catálogo `PERSONALITIES` y carga de la propia. El orden del prompt **no se toca** |
| `backend/core/` (pieza nueva) | Nueva | La puerta determinista de la personalidad propia |
| `data/personalidad_propia.md` | Nueva | El texto del usuario. Único fichero que se escribe |
| `frontend/setup.html` | Modificada | Paso 2: las nuevas + «la mía». Cuidado con `?v=NN` |
| `frontend/js/command.js` | Modificada | El selector de ⚙ (línea 1856) ya lee `/api/personalities`; solo cambia el catálogo |
| `backend/app.py` | Modificada | `/api/personalities` y `/api/setup/state` exponen también la propia |
| `skills/memory_graph/skill.py` | Modificada | `recall` y hermanos pasan de fichas a conversación |
| `tests/` | Nueva | Suites nuevas, registradas en `tests/run_all.py` |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
| --- | --- | --- |
| **Una personalidad propia hostil desactiva la honestidad** | Alta sin mitigar | Puerta determinista + la regla sigue siendo lo último del prompt + sondas de invención contra **todas** las personalidades |
| **Narrar esconde datos que el usuario necesitaba ver** | Media | La spec enumera qué se narra y qué se lista. Ante la duda, se lista |
| **Cambiar el catálogo deja huérfanas instalaciones con `personality` viejo** | Media | `PERSONALITIES.get(k, ...)` ya cae a la de por defecto; se declara cuál es y se avisa |
| **El texto propio infla el prompt y se come el contexto** | Media | Tope en `config/umbrales.json`, con recorte dicho en claro |
| **Un dato personal se cuela en un preset y viaja en el instalador** | Baja, alta si pasa | Presets en segunda persona, sin nombres. La guarda de `test_skill_domotica.py:372` se extiende (ver `007`) |

## Plan de reversión

1. En ⚙, volver a una personalidad del catálogo: efecto inmediato, sin reinicio.
2. Borrar `data/personalidad_propia.md`: cae sola a la de por defecto.
3. `settings.json` → `personality` a su valor de fábrica.
4. En desarrollo, además, `git revert` — pero el plan **no depende de git**.

## Dependencias

Ninguna externa. Se apoya en `PERSONALITIES`, `SYSTEM_PROMPT`,
`_build_messages()`, `publicvoice.sanitize()`, `selflearn.operator_profile()` y
el asistente de `frontend/setup.html`.

## Sigue abierta

- **¿La personalidad propia se puede editar hablando** («sé más breve conmigo»),
  o solo tocando el fichero? Editarla hablando la acerca a una regla aprendida de
  004 y debería heredar su aprobación por tandas. Decisión del dueño.

## Criterios de éxito

- [ ] Las personalidades pedidas se eligen en la instalación y en ⚙, y **se nota**.
- [ ] Un `.md` propio se activa y cambia el tono sin tocar una línea de código.
- [ ] Una personalidad propia que pide inventar o afirmar trabajo no hecho se
      rechaza, diciendo qué línea.
- [ ] Las sondas de invención de cifras pasan con **todas** las personalidades,
      no solo con la de por defecto.
- [ ] «qué sabes de mí» y «qué recuerdas de X» se contestan hablando; el tablero
      y los informes con cifras siguen listando.
- [ ] Borrar el fichero propio devuelve el comportamiento de fábrica.
- [ ] `run_all.py` verde con las suites nuevas registradas.
