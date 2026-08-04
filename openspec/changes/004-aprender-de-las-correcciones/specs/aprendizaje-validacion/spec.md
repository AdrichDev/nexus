# Especificación: aprendizaje-validacion

## Propósito

Las cinco puertas que una regla debe cruzar antes de tener el menor efecto. Esta
es la parte del cambio que se ejecuta **en casa del usuario**, donde no hay
repositorio, ni suite, ni nadie que edite un `skill.py` cuando algo se tuerce.

La puerta principal no es una idea nueva: `brain.quien_atiende()` se escribió el
03/08 precisamente para mirar donde de verdad se decide, después de que
`test_lo_prometido` diera por buenas frases que en una conversación real nunca
salían del primer atajo. Aquí esa función es la red.

## Requisitos

### Requisito: Las cinco puertas, o la regla no entra

Una regla DEBE pasar las cinco puertas —campos, existencia, forma, no robo y
suite— para pasar de `propuesta` a `activa`. Si una sola falla, la regla NO DEBE
activarse. La validación DEBE ser **determinista**: ningún modelo participa en
la decisión de activar. Cada fallo DEBE dejar el motivo concreto en la
auditoría (`backend/core/comun/audit.py`) y ser legible por el dueño.

#### Escenario: Una puerta falla y la regla no entra
- GIVEN una regla propuesta que pasa cuatro puertas y falla la de forma
- WHEN se intenta activar
- THEN sigue en estado `propuesta`, no participa en ninguna decisión
- AND la auditoría registra qué puerta falló y por qué

#### Escenario: Validación sin modelo
- GIVEN no hay ningún proveedor de LLM disponible
- WHEN se validan las reglas de una tanda
- THEN las cinco puertas se ejecutan igualmente y el resultado es el mismo

### Requisito: Puerta de campos

La regla DEBE llevar los ocho campos obligatorios definidos en
`aprendizaje-contrato`, con `origen` conteniendo la frase correctiva literal, el
canal y la fecha. Falta uno, no es una regla.

#### Escenario: Campo ausente
- GIVEN una regla propuesta sin `evidencia`
- WHEN se ejecuta la puerta de campos
- THEN falla nombrando el campo que falta

### Requisito: Puerta de existencia

Para una regla `enrutado`, `destino` DEBE corresponder a un `carpeta/intent`
presente en `skills_loader.get_skills()` en el momento de la validación, y esa
skill NO DEBE estar en estado `error`. Para una regla `valor`, `destino` DEBE ser
una clave **ya declarada** en la capa de sobreescritura, y el valor DEBE
respetar su tipo y su rango declarados.

#### Escenario: La skill de destino ya no existe
- GIVEN una regla propuesta apunta a un intent de una skill que se ha desinstalado
- WHEN se ejecuta la puerta de existencia
- THEN falla y la regla no se activa

#### Escenario: Clave de valor no declarada
- GIVEN una regla `valor` cuyo destino no figura en la capa de sobreescritura
- WHEN se ejecuta la puerta de existencia
- THEN falla, porque no se puede aprender sobre lo que está a fuego

#### Escenario: Valor fuera del rango declarado
- GIVEN una clave declarada como entero entre 0 y 100 y una regla que propone 250
- WHEN se ejecuta la puerta de existencia
- THEN falla por rango, sin escribir nada en la capa de sobreescritura

### Requisito: Puerta de forma

Para una regla `enrutado`, el `patron` DEBE compilar como expresión regular, DEBE
estar anclado (no puede ser un fragmento suelto que case en medio de cualquier
frase) y NO DEBE casar sobre el corpus conocido por encima de un tope leído de
`config/umbrales.json` (bloque `aprendizaje`). Un patrón que casa con medio
catálogo no es una forma nueva de decir algo: es una red de arrastre.

#### Escenario: Patrón que no compila
- GIVEN un `patron` con paréntesis sin cerrar
- WHEN se ejecuta la puerta de forma
- THEN falla y la regla no se activa

#### Escenario: Patrón demasiado goloso
- GIVEN un `patron` que casa con más frases del corpus que el tope configurado
- WHEN se ejecuta la puerta de forma
- THEN falla por exceso de alcance

#### Escenario: Patrón sin anclar
- GIVEN un `patron` que no está anclado y casa en mitad de frases largas
- WHEN se ejecuta la puerta de forma
- THEN falla

### Requisito: Puerta de no robo

El sistema DEBE ejecutar `brain.quien_atiende(frase, canal)` sobre **todo el
corpus** antes y después de aplicar la regla en memoria, y comparar los dos
resultados frase a frase. La **única** diferencia admitida es que la frase
objetivo pase de `planificador` a la regla. Si una sola frase que no era el
objetivo cambia de dueño —en cualquier dirección, incluida la de dejar de estar
atendida— la regla DEBE descartarse.

El corpus no se inventa: son las órdenes que `tests/test_lo_prometido.py`
extrae de las listas de activación de los `SKILL.md` (hoy 255 distintas) más las
frases reales de `tests/test_regresion_conversacion.py`. Ese catálogo DEBE
viajar con la instalación y estar disponible sin red: es la única red que va a
tener el usuario.

Si el catálogo falta, está vacío o no se puede leer, la puerta DEBE fallar y
NINGUNA regla DEBE activarse. Validar a ciegas es peor que no aprender.

#### Escenario: Una regla le roba una frase a una skill
- GIVEN una regla propuesta cuyo patrón también casa con «apaga la tele»
- WHEN se comparan los resultados de `quien_atiende()` antes y después
- THEN al menos una frase del corpus que no era el objetivo ha cambiado de dueño
- AND la regla se descarta indicando qué frase se veía afectada

#### Escenario: Regla limpia
- GIVEN una regla propuesta para una frase que hoy devuelve `planificador`
- WHEN se comparan los dos barridos del corpus
- THEN todas las frases devuelven exactamente lo mismo salvo la objetivo
- AND la objetivo pasa de `planificador` a la regla

#### Escenario: La regla no aporta nada
- GIVEN una regla propuesta cuya frase objetivo ya no devuelve `planificador`
- WHEN se ejecuta la puerta de no robo
- THEN falla: no hay hueco que ocupar

#### Escenario: Catálogo ausente en la instalación
- GIVEN el catálogo de frases prometidas no está instalado o no se puede leer
- WHEN se intenta validar una tanda
- THEN todas las reglas quedan sin activar y se avisa de que falta el catálogo

#### Escenario: Comparación por resultado, no por razonamiento
- GIVEN cualquier regla candidata
- WHEN se ejecuta la puerta de no robo
- THEN el veredicto sale de ejecutar `quien_atiende()` sobre cada frase, nunca de
  una inspección del patrón ni de una explicación del modelo

### Requisito: Puerta de suite, y qué pasa cuando no hay suite

En un entorno de desarrollo, tras aplicar la tanda la suite completa
(`.venv\Scripts\python.exe tests\run_all.py`) DEBE seguir en verde; si no, la
tanda DEBE revertirse entera. En una instalación de usuario no hay suite: la
puerta DEBE registrarse como **no aplicable**, y NO DEBE registrarse nunca como
superada. En ese entorno, la puerta de no robo es la red y NO DEBE relajarse por
la ausencia de la suite.

#### Escenario: La suite se pone en rojo tras la tanda
- GIVEN un entorno de desarrollo con la suite disponible
- WHEN tras activar la tanda `run_all.py` deja de estar en verde
- THEN todas las reglas de esa tanda vuelven a `propuesta` o pasan a `revertida`
- AND se informa de qué suite se rompió

#### Escenario: Instalación de usuario sin suite
- GIVEN una instalación sin `tests/`
- WHEN se valida una tanda
- THEN la puerta de suite se marca `no aplicable` en la auditoría
- AND las otras cuatro puertas se ejecutan sin ninguna excepción

### Requisito: Revalidación en la activación y tras cambiar el catálogo

Las cinco puertas DEBEN volver a ejecutarse en el instante de activar, no solo al
proponer: entre la propuesta y la aprobación el catálogo de skills puede haber
cambiado. Una regla `activa` cuya `revision` no coincida con la del catálogo
instalado DEBE revalidar antes de volver a aplicarse.

#### Escenario: La skill desaparece entre proponer y aprobar
- GIVEN una propuesta validada ayer contra una skill que hoy ya no está instalada
- WHEN el dueño la aprueba
- THEN la validación falla en la puerta de existencia y la regla no se activa
- AND se explica que la skill de destino ya no existe

#### Escenario: Regla activa tras una actualización de skills
- GIVEN una regla `activa` y un catálogo nuevo con una `revision` distinta
- WHEN nexus arranca
- THEN la regla revalida antes de aplicarse, y si falla cualquier puerta pasa a
  `revertida` y se avisa
