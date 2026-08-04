# Propuesta: horarios y automatizaciones

## El problema, en los términos del dueño

«Hazme el informe de X todos los días a las 8 de la mañana» hoy **no se puede
pedir**. No hay nada que lo entienda.

`backend/core/scheduler.py` es el único reloj y no es un reloj: es un contador.
`scheduler_loop()` duerme **5 segundos** (línea 196 — el docstring dice 20 s y
está desfasado) y todo cuelga de `tick % N`: métricas cada tick, recordatorios
cada 4, vigilancias cada 60, copia cada 120. Nada de eso sabe qué hora es. La
**única** noción de hora del programa está en `briefing.briefing_due()`, y sirve
para **una** tarea, el briefing matinal, con su hora en `settings.briefing_hour`.
No hay cron, no hay días de la semana, no cabe una segunda tarea.

Lo de alrededor tampoco lo resuelve. `skills/vigilancias/` repite cada
`_CHECK_MIN = 10` minutos (constante a fuego, línea 43): eso es un intervalo, no
una hora. `pg.add_reminder()` guarda un aviso de **una sola vez**. Y
`skills/autoprovision/` no crea automatizaciones: su intent `n8n_setup` lee un
JSON fijo de `config/` —busca `n8n_flujo_nexus.json` y, como no existe, cae a
`n8n_flujo_ejemplo.json`— y lo crea y activa **preguntando antes** con
`confirm.request()`. `skills/n8n_flows/` solo dispara por webhook flujos que ya
existen.

## Alcance

### Dentro

| Entrega | Qué es |
| --- | --- |
| **Contrato de horario** | Cuándo, qué, en qué canal y qué pasa si se lo pierde. Es dato, como en 004 |
| **Reloj de verdad** | Horas, minutos y días de la semana, sin romper los `tick % N` |
| **Conversación** | «todos los días a las 8», «los lunes y jueves», «qué tienes programado», «quítalo» |
| **Equipo apagado** | Declarado por horario, dicho en claro, nunca fingido |
| **n8n como ejecutor opcional** | Un horario dispara un flujo: uno que ya exista, o uno que nexus cree a peticion |

### Corrección del dueño (03/08/2026)

Esta propuesta dejaba fuera **crear automatizaciones de n8n**, razonando que un
grafo de nodos generado es «código con otro nombre» y que 004 lo prohíbe.

**Es un error, y el dueño lo ha corregido**: lo que quiere es exactamente que
nexus **cree el flujo de n8n o el cron que se le pida**, sea el que sea. El
informe diario a las 8 era un ejemplo, no un requisito.

Y al mirarlo de cerca, la razón que se daba tampoco se sostiene. 004 prohíbe que
nexus escriba **código que nexus ejecuta**: su propio `.py`, en su propio
proceso, sin repositorio ni pruebas para recuperarse. Un workflow de n8n no es
eso. Es **un JSON que ejecuta n8n**, un servicio aparte, en su contenedor, con su
propia interfaz para ver, editar y desactivar lo que haya. Está en la misma
categoría que una regla aprendida: **dato**, no código. Lo mismo vale para un
horario, que es lo que esta propuesta ya aceptaba.

Lo que sí hereda de 004 es la disciplina, y aquí importa más aún porque un flujo
puede llamar al mundo exterior:

- **Nada se activa sin enseñar antes qué va a hacer.** Igual que el borrado por
  fecha enseña qué borra.
- **Deshacer es borrar el flujo**, y nexus tiene que saber cuáles ha creado él.
- **Un flujo que necesite confirmación humana no puede programarse**, porque a
  las 8 de la mañana no hay nadie para confirmarlo. Se rechaza al crearlo, no al
  dispararlo — que ya era la decisión de esta propuesta y sigue valiendo.
- **Sin n8n no se finge**: el usuario que eligió `local` no tiene contenedores, y
  hay que decírselo, no dejar el horario en el aire.

### Fuera

- Mover n8n a un VPS: se diseña para que quepa, no se hace aquí.
- Segundos, expresiones cron completas, festivos.
- Personalidades (→ `006`). Instalador y actualizaciones (→ `007`).

## Capacidades

### Nuevas

- `horarios-contrato`: esquema, almacén, estados y validación
- `horarios-reloj`: cómo el bucle pasa de contar ticks a mirar la hora
- `horarios-conversacion`: crear, listar, pausar y borrar hablando
- `automatizaciones-n8n`: n8n como destino legítimo, y dónde está su frontera

### Modificadas

Ninguna. Ninguna spec de `openspec/specs/` habla del scheduler.

## Enfoque

**El reloj es de nexus; n8n ejecuta los flujos, incluidos los que nexus cree.** Es la decisión que
sostiene el resto, y va contra la tentación de delegarlo todo en n8n.

El motivo es de instalación, no de gusto. `frontend/setup.html` (paso 4) deja
elegir memoria `local`, `docker` o `server`; n8n solo aparece con Docker, y
`n8n_flows` además exige un `n8n_webhook_url` puesto a mano. Un usuario en
`local` **no tiene n8n**: si el horario viviera allí, media instalación se
quedaría sin horarios. Y crear flujos por API para cada horario nos pone a
generar ejecutables en la máquina del usuario, justo lo que 004 cerró.

Un horario es **dato**: vive en `data/horarios.json` y su `destino` es un
`skill/intent` que ya existe —la misma puerta de existencia que 004 valida contra
`skills_loader.get_skills()`—. n8n entra como un destino más, el intent
`n8n_flows/flow`.

**El camino al VPS.** Un horario declara zona horaria y dueño; el bucle solo
pregunta «¿toca?». Mañana ese pulso puede venir de fuera: `POST /api/n8n` ya
existe y acepta `{"text": "..."}` (`skills/n8n_flows/skill.py:132`). Cambiar la
fuente del pulso no cambia el formato del horario, que es lo caro.

**Si el equipo estaba apagado, no hay informe.** Se dice y ya está. El precedente
está escrito: `briefing_due()` es `now >= target and last_sent_date != hoy`, o
sea que a las 11:20 manda el briefing de las 8:30 —tarde, pero lo manda—. Se
generaliza: cada horario declara `al_arrancar` (recupera una vez diciendo la hora
real: «esto es el informe de las 8, son las 11:20») u `omitir` (no se hace y se
avisa). Lo que no se hará nunca es presentarlo como si hubiera salido a su hora.

**Solo destinos desatendidos.** Un horario no puede apuntar a un intent que
necesite `confirm.request()`: nadie contesta a las 8 de la mañana. Se rechaza
**al crear el horario**, con motivo, no al dispararlo.

En el ciclo cerrado de Content OS esto toca solo **medición**: un informe
periódico es una lectura repetida; no genera hipótesis ni experimentos.

## Áreas afectadas

| Área | Impacto | Qué cambia |
| --- | --- | --- |
| `backend/core/scheduler.py` | Modificada | Un paso que consulta horarios vencidos. Los `tick % N` no se tocan |
| `backend/core/` (módulo nuevo) | Nueva | Contrato, almacén, vencimiento y recuperación |
| `data/horarios.json` | Nueva | El almacén. Único fichero que se escribe |
| `skills/<nueva>/` | Nueva | Solo conversación. **Ojo al orden alfabético** del loader |
| `config/umbrales.json` | Modificada | Ventana de recuperación y tope de horarios |
| `tests/` | Nueva | Suites nuevas, registradas en `tests/run_all.py` |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
| --- | --- | --- |
| **Un horario dispara una acción con efectos sin nadie delante** | Alta sin mitigar | Solo destinos desatendidos, comprobado al crear |
| **El bucle se atasca y arrastra métricas, recordatorios y copias** | Media | Disparo en tarea suelta, como ya hace `profile.consolidate_daily()` (línea 179) |
| **Recuperar lo perdido inunda al usuario al encender** | Media | Una recuperación por horario y día, con la hora real dicha |
| **Cambio de hora: se salta o se duplica un día** | Media | Vencimiento por fecha local + marca de último disparo, nunca por resta de horas |
| **n8n caído hace fallar el horario en silencio** | Media | El fallo se dice en el canal del horario, con motivo, sin reintentos infinitos |

## Plan de reversión

1. «pausa todos los horarios» → ninguno vence, nada se pierde.
2. Borrar `data/horarios.json` y reiniciar con `run.bat`: comportamiento de fábrica.
3. En desarrollo, además, `git revert` — pero el plan **no depende de git**: en la
   máquina de un usuario no hay repositorio.

## Dependencias

Ninguna externa. n8n es **opcional** por diseño. Todo se apoya en
`scheduler_loop()`, `briefing_due()`, `confirm.py`, `audit.py` y
`skills_loader.get_skills()`.

## Sigue abierta

- **¿Un horario puede apuntar a un intent aprendido por 004?** Se propone que sí,
  solo si la regla está `activa`; si 004 la revierte, el horario queda huérfano y
  se avisa. Decisión del dueño.

## Criterios de éxito

- [ ] «hazme el informe de X todos los días a las 8» crea un horario y se cumple,
      verificado con el reloj real, no razonando.
- [ ] «los lunes y jueves» funciona; los demás días no dispara.
- [ ] Con el equipo apagado a las 8 y encendido a las 11, o sale con su hora real
      dicha o no sale y se avisa. **Nunca fingiendo que fueron las 8.**
- [ ] Un horario contra un intent que pide confirmación se rechaza al crearlo.
- [ ] Un usuario sin Docker y sin n8n puede crear y cumplir horarios.
- [ ] Borrar `data/horarios.json` devuelve el comportamiento de fábrica.
- [ ] `run_all.py` verde con las suites nuevas registradas.
