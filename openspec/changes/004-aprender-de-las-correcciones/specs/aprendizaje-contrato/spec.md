# Especificación: aprendizaje-contrato

## Propósito

Qué es exactamente una regla aprendida, dónde vive, en qué estados puede estar y
cómo se deshace. Es el núcleo de seguridad del cambio 004: todo lo demás
—correcciones, validación, aprobación y enrutado— manipula el objeto que aquí se
define.

Importa más de lo que parece porque esto se instala en la máquina de otra
persona. Allí no hay repositorio, ni `git revert`, ni suite que avise. La única
red que queda es que **nexus solo escriba datos** y que borrar esos datos
devuelva el comportamiento de fábrica.

## Requisitos

### Requisito: Campos obligatorios de una regla

Una regla aprendida DEBE llevar los ocho campos siguientes, todos presentes y no
vacíos: `id`, `tipo`, `origen`, `destino`, `patron` o `valor` (según el tipo),
`evidencia`, `estado` y `revision`. `origen` DEBE ser un objeto con la **frase
correctiva literal** tal y como la dijo el operador, el canal y la fecha. Si
falta uno solo de los campos, el objeto NO ES una regla: NO DEBE guardarse, NO
DEBE proponerse y NO DEBE activarse.

#### Escenario: Regla sin la frase que la originó
- GIVEN un candidato a regla con `id`, `tipo`, `destino`, `patron`, `evidencia`,
  `estado` y `revision`, pero con `origen` vacío
- WHEN se intenta guardarlo en el almacén
- THEN se rechaza indicando qué campo falta
- AND el almacén queda exactamente igual que antes

#### Escenario: La frase correctiva se guarda literal
- GIVEN el operador corrige con «no, te he dicho que cierres chrome»
- WHEN esa corrección genera una regla propuesta
- THEN `origen.frase` contiene esa frase carácter a carácter, sin reescribir,
  resumir ni normalizar
- AND `origen` incluye el canal y la fecha de la corrección

### Requisito: Dos tipos de regla, y solo dos

`tipo` DEBE ser `enrutado` o `valor`. Cualquier otro valor DEBE rechazarse.

- `enrutado`: `patron` es una expresión regular y `destino` es un
  `carpeta/intent` **que ya existe** en `skills_loader.get_skills()`. Una regla
  de enrutado amplía el alcance de un handler existente y NO DEBE jamás declarar
  un handler nuevo.
- `valor`: `destino` es una clave ya declarada en la capa de sobreescritura sobre
  `config/umbrales.json`, y `valor` DEBE respetar el tipo y el rango declarados
  para esa clave.

#### Escenario: Tipo desconocido
- GIVEN un candidato con `tipo: "prompt"`
- WHEN se valida
- THEN se rechaza por tipo no admitido y no se guarda

#### Escenario: Enrutado a un handler inexistente
- GIVEN un candidato de tipo `enrutado` con `destino: "agenda/crear_reunion"` y
  ninguna skill declara ese intent
- WHEN se valida
- THEN se rechaza y la respuesta explica que nexus no inventa handlers

### Requisito: nexus escribe datos, nunca código

nexus NO DEBE escribir, reescribir ni generar ningún fichero `.py`, ni siquiera
los suyos, como consecuencia del aprendizaje. Los únicos artefactos que el
aprendizaje escribe son `data/reglas_aprendidas.json`, la capa de sobreescritura
sobre `config/umbrales.json` y la traza de `backend/core/comun/audit.py`.

#### Escenario: Barrido tras una tanda de aprendizaje
- GIVEN se aprueban y activan varias reglas
- WHEN se comparan las fechas de modificación de todos los `.py` del proyecto
  antes y después
- THEN ninguna ha cambiado

#### Escenario: Una regla no puede apuntar a un fichero de código
- GIVEN un candidato de tipo `valor` cuyo `destino` es una ruta a un `.py`
- WHEN se valida
- THEN se rechaza: el destino no es una clave declarada de la capa de
  sobreescritura

### Requisito: Estados y transiciones permitidas

`estado` DEBE ser uno de `propuesta`, `activa` o `revertida`. Las únicas
transiciones permitidas son `propuesta → activa` (tras aprobación explícita del
dueño) y `activa → revertida`. Una regla NO DEBE pasar de `revertida` a `activa`
sin volver a proponerse y aprobarse. **Nada se borra**: revertir es cambiar el
estado, no perder la historia.

#### Escenario: Revertir conserva la regla
- GIVEN una regla `activa`
- WHEN el dueño la revierte
- THEN su `estado` pasa a `revertida`, sigue en el almacén con su `origen`
  intacto, y deja de tener efecto en la decisión

#### Escenario: Transición prohibida
- GIVEN una regla en estado `revertida`
- WHEN algo intenta ponerla en `activa` sin una aprobación nueva
- THEN la transición se rechaza y el estado no cambia

### Requisito: `revision` ata la regla al catálogo con el que se validó

`revision` DEBE identificar la foto del catálogo de skills y de frases prometidas
contra la que la regla pasó sus puertas. Si al arrancar la `revision` de una
regla `activa` no coincide con la del catálogo instalado, esa regla NO DEBE
aplicarse hasta volver a pasar la validación completa.

Esto existe porque el dueño aceptó que el catálogo viaja con el instalador y que
mantenerlo al día es trabajo: sin `revision`, una actualización de skills dejaría
reglas validadas contra una foto vieja aplicándose en silencio.

#### Escenario: El catálogo cambió bajo una regla activa
- GIVEN una regla `activa` con `revision` de una versión anterior del catálogo
- WHEN nexus arranca con un catálogo distinto
- THEN la regla no participa en ninguna decisión mientras no revalide
- AND si al revalidar falla cualquier puerta, pasa a `revertida` y se avisa

### Requisito: Almacén único y restablecimiento de fábrica

Todas las reglas DEBEN vivir en `data/reglas_aprendidas.json` y, para las de
tipo `valor`, en la capa de sobreescritura declarada sobre
`config/umbrales.json`. Borrar esos ficheros DEBE devolver el comportamiento
**exacto** de fábrica, sin dejar ningún resto en el código ni en la configuración
base.

#### Escenario: Borrar el almacén devuelve el comportamiento de fábrica
- GIVEN un conjunto de frases y su resultado de `brain.quien_atiende()` con el
  almacén vacío, anotado antes de aprender nada
- WHEN se activan reglas, se borra `data/reglas_aprendidas.json` y la capa de
  sobreescritura, y se reinicia nexus
- THEN `quien_atiende()` devuelve para cada frase exactamente el mismo valor que
  se anotó al principio

#### Escenario: Almacén ausente o ilegible
- GIVEN `data/reglas_aprendidas.json` no existe o está corrupto
- WHEN nexus arranca
- THEN funciona con cero reglas activas, avisa del problema y no se cae

### Requisito: Nada personal viaja en el instalador

El almacén vive en `data/`, que NO se empaqueta (está excluido en `.gitignore`,
línea 28). Lo aprendido es **local y del usuario**: NO DEBE subirse, sincronizarse
ni distribuirse. Ningún módulo, prueba o fichero de ejemplo de este cambio DEBE
contener nombres, direcciones, IPs o frases reales del dueño, en la misma línea
que ya guarda `tests/test_skill_domotica.py`.

#### Escenario: Guarda de datos personales en los ficheros nuevos
- GIVEN los módulos y suites nuevos de este cambio
- WHEN se buscan nombres propios del dueño o datos personales
- THEN no aparece ninguno

#### Escenario: Lo aprendido no sale del equipo
- GIVEN hay reglas activas en el almacén
- WHEN se ejecuta cualquier operación de empaquetado, actualización o
  sincronización
- THEN el contenido de `data/reglas_aprendidas.json` no se incluye ni se envía a
  ningún destino remoto
