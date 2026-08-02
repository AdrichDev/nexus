# Skill: Herramientas 🧰

Utilidades rápidas que no necesitan credenciales ni internet (salvo el ping).

## Qué hace y con qué frases se dispara

- **Hora y fecha**: «qué hora es» · «dime la hora» · «dame la hora» ·
  «qué día es» · «qué fecha es hoy»
- **Temporizadores**: «temporizador de 10 minutos» · «cuenta atrás de 5 minutos» ·
  «avísame en 10 minutos» · «avísame dentro de 20 minutos»
- **Alarmas**: «alarma a las 7:30» · «despiértame a las 8» · «despertador a las 6»
  (avisa por el HUD; si la hora ya pasó hoy, la pone para mañana)
- **Notas rápidas**: «apunta que ...» → va a la nota diaria del grafo (y a la
  memoria si Postgres está online)
- **Red**: «haz ping a <host>» · «estado de la red» · «hay internet» ·
  «prueba la conexión»
- **Matemáticas** (SymPy): «cuánto es 2+2*8» · «calcula 15*3» ·
  «raíz cuadrada de 16» · «deriva x**3» · «cuál es la derivada de x**3» ·
  «integral de x**2» · «resuelve x**2 - 4 = 0» · «despeja x + 2 = 5»
  También entiende las mates dichas por voz: «x al cuadrado», «raíz de 16»,
  «dos por tres», «equis elevado a 3».

## Qué necesita configurado

- Nada. Las mates piden `sympy` (lo instala `run.bat`); si falta, lo dice y
  explica cómo instalarlo, no responde un número inventado.
- Temporizadores y alarmas viven en el scheduler en memoria: se pierden al
  reiniciar nexus. Para algo con fecha y avisos persistentes, «recuérdame X el
  viernes» (coach).

## Qué NO hace

- **No da el tiempo**: eso es la skill `clima` (wttr.in). Aquí no hay
  meteorología ni datos de relleno de ninguna clase.
- No evalúa código: antes de tocar SymPy hay una lista blanca de caracteres y
  funciones. Lo que no sea una expresión matemática ni se acerca a `sympify()`
  y lo contesta el modelo.
- «apúntame que hay reunión el martes» no es una nota: eso lo coge la agenda
  de Google. Aquí entra «apunta que ...» sin fecha ni cita.
