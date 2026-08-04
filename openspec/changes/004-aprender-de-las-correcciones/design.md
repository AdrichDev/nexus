# Diseño técnico — 004 Aprender de las correcciones

- **Cambio**: `004-aprender-de-las-correcciones`
- **Fase**: design · **Almacén**: híbrido (este fichero + Engram `sdd/004-aprender-de-las-correcciones/design`)
- **Manda**: la sección «Decisiones del dueño (03/08/2026)» de `proposal.md`
- **Contexto nuevo**: `backend/core/` dejó de ser plano el 03/08. Son cuatro capas y
  `tests/test_capas_backend.py` las verifica en cada ejecución. **Dónde se coloca este
  módulo decide si el diseño es legal**, y por eso es la primera decisión.

## Enfoque técnico

El mecanismo se parte en **dos módulos y dos capas**, no en uno. Abajo, `dominio/reglas.py`:
el contrato, el almacén y todo lo que se puede juzgar sin saber quién enruta. Arriba,
`aplicacion/aprendizaje.py`: las puertas que necesitan el router y el cerebro, la propuesta,
la tanda y la consulta. Entre las dos, la inversión de dependencia que el proyecto ya usa en
`comun/events.registrar_hay_trabajo()`: **la capa de abajo deja el hueco y la de arriba lo
rellena al cargarse**.

Sobre eso, tres invariantes que se sostienen por construcción y no por vigilancia:

1. **Ningún `.py` se escribe.** El único fichero que nexus muta es `data/reglas_aprendidas.json`.
2. **Una regla es inalcanzable si el router ya contestó.** No se comprueba después: la función
   que las consulta recibe el veredicto del router y lo devuelve intacto si no es `None`.
3. **El almacén no otorga autoridad.** `estado: "activa"` escrito a mano no activa nada: la
   validación se recalcula al cargar. El fichero es un registro, no un permiso.

## Decisiones de arquitectura

### 1. Colocación en las capas — dos módulos, y el hueco rellenado desde arriba

El mecanismo necesita `skills_loader.route()` y `brain.quien_atiende()`, ambos en `aplicacion/`.
Un módulo en `comun/` o en `dominio/` que los importe es una dependencia **hacia arriba** y el
test la rechaza.

| Opción | Consecuencia | Decisión |
| --- | --- | --- |
| Todo en `comun/reglas.py` | Ilegal: `comun` no puede importar ni `dominio` (test 3 lo comprueba aparte) | rechazada |
| Todo en `dominio/reglas.py` | Ilegal: `dominio → aplicacion` es hacia arriba; exigiría una `EXCEPCIÓN` nueva, es decir, deuda declarada el primer día | rechazada |
| Todo en `aplicacion/aprendizaje.py` | Legal (misma capa), pero el contrato y el almacén quedan atados al arranque de las skills y no se pueden probar sin cargarlas | rechazada |
| **`dominio/reglas.py` + `aplicacion/aprendizaje.py`, con hueco registrado** | Legal sin excepciones nuevas; el contrato se prueba solo, sin skills ni cerebro | **elegida** |

Cómo queda el grafo, y por qué el test lo acepta:

```
  aplicacion/brain ──importa──► aplicacion/aprendizaje ──importa──► dominio/reglas
        ▲                              │                                  ▲
        └── registra quien_atiende ────┘                                  │
                                       └── registra existe_destino/dueños ┘
```

- `dominio/reglas.py` importa **solo** `comun/config` y `comun/audit`. Hacia abajo. ✔
- `aplicacion/aprendizaje.py` importa `dominio/reglas` (abajo) y `aplicacion/skills_loader`
  (misma capa, y `skills_loader` no importa nada hacia arriba: no hay ciclo). ✔
- `brain` importa `aprendizaje` (misma capa) y **`aprendizaje` no importa `brain`**: es `brain`
  quien se registra al final de su módulo con `aprendizaje.registrar_arbitro(quien_atiende)`.
  Un ciclo entre módulos de la misma capa pasaría el test, pero obligaría a importar dentro de
  la función y eso esconde la dependencia — el propio `CAPAS.md` lo dice de los cuatro ciclos
  que ya arrastra. No se añade el quinto.
- **Cero entradas nuevas en `EXCEPCIONES`.**

Tarea obligada, o el test falla en su comprobación 1: dar de alta `reglas` en el bloque
`dominio` y `aprendizaje` en el bloque `aplicacion` de `tests/test_capas_backend.py`, y en la
tabla de `backend/core/CAPAS.md` (la comprobación 5 lee el `.md`).

**El valor por defecto del hueco se invierte respecto a `events`.** Allí `_hay_trabajo` contesta
`True` por defecto porque «un candado que se equivoca callando es peor que no tenerlo». Aquí es
al revés: si nadie rellenó el hueco, `existe_destino()` devuelve `False` y el barrido de dueños
devuelve «no lo sé». Sin árbitro no hay activación. Una puerta que se equivoca **aprobando** es
lo único que este cambio no se puede permitir.

### 2. El almacén — un JSON, escritura atómica, y validación en cada carga

`data/reglas_aprendidas.json`, un objeto: `{"esquema": 1, "reglas": [...]}`. No JSONL: los
estados mutan y un fichero de líneas obligaría a compactar.

| Asunto | Decisión | Por qué |
| --- | --- | --- |
| Escritura | `.bak` + `.tmp` + `os.replace`, calcando `config._write_json_atomic()` | Es código de `comun/`, importable, y ya resolvió la truncación de `settings.json` |
| Lectura | Principal → `.bak` → **fábrica** (`{"esquema": 1, "reglas": []}`) | Igual que `config._read_json_safe()`. Corromper el fichero degrada a comportamiento de fábrica; **nunca lanza** |
| Concurrencia | `threading.Lock` de módulo + lectura-modificación-escritura entera dentro del candado | nexus es **un** proceso (puerto 8177, `run.bat` mata al anterior) con varios hilos: scheduler, hotkey, puente de Telegram. No hace falta candado entre procesos y no se inventa uno |
| Versión | `esquema: 1`. Un número **mayor** → el almacén se lee en solo lectura y **ninguna regla activa**, con motivo visible | Un nexus viejo no adivina un formato nuevo. Migrar hacia atrás en silencio es exactamente cómo se pierden datos |
| Regla individual inválida | Se **aísla**: no entra en el conjunto activo, permanece en el fichero con `estado: "invalida"` y `motivo` | Una regla mal escrita a mano no puede invalidar las otras nueve |
| Edición a mano | El `estado` del fichero **no se cree**: al cargar se vuelven a pasar las puertas 1-4 | Es la única defensa real: el fichero vive en la máquina del usuario y es texto plano |

Revalidar en cada carga cuesta un barrido sobre ~250 frases. Se amortiza con una huella:
el almacén guarda `huella_corpus` (número de `SKILL.md`, `mtime` máximo, número de frases) y
`huella_reglas` (sha256 del conjunto activo). Si ambas coinciden con lo validado, el barrido se
salta. Si cambió cualquiera —se instaló una skill, se editó el fichero— se rehace. Y se hace
**perezosamente, en la primera consulta**, no al importar: si las skills no cargan, nexus
arranca igual.

### 3. Dónde se consultan las reglas — y por qué el robo es imposible, no improbable

La posición la fija la propuesta: **detrás del router nativo**. En `brain.process` eso es dentro
de la rama `if routed is None` (hoy línea 1031-1051), después de `_learn_lookup()` y de
`rag.find_task()` —que son recuerdo exacto y semántico de órdenes que ya funcionaron— y
**antes de `llm.plan_action()`**, que es el planificador. El hueco que una regla puede ocupar es
literalmente el que iba al planificador.

La garantía no es una comprobación posterior; es la firma:

```python
def aplica(texto: str, ya_enrutado):
    """Devuelve (enrutado, id_regla). Si el router ya contestó, no toca nada."""
    if ya_enrutado is not None:
        return ya_enrutado, ""          # ← el robo no es que se rechace: es inalcanzable
```

`quien_atiende()` gana el mismo escalón, después de `r = route(t)`, porque
`test_regresion_conversacion` exige que todo atajo previo a la decisión se vea desde ahí. Firma
nueva: `quien_atiende(text, channel="pc", reglas=None)`, donde `reglas=()` significa «ninguna».
Así el barrido antes/después es **una función pura llamada dos veces**, sin mutar globales ni
parchear módulos.

De ahí sale el criterio del barrido, que es una sola pasada y compra dos cosas:

| Transición observada en el corpus | Veredicto |
| --- | --- |
| `skill:A/i` → cualquier otra cosa | **robo** → regla descartada |
| `memoria` / `queja` / `charla` → cualquier otra cosa | **robo** → regla descartada (estructuralmente no puede pasar; se comprueba igual) |
| `planificador` → `skill:X/i`, y la frase objetivo está entre ellas | admitida, hasta el tope |
| `planificador` → `skill:X/i` por encima de `tope_frases_arrastradas` | **regex demasiado ancha** → descartada |

**Divergencia declarada.** `quien_atiende()` no modela hoy `_learn_lookup()` ni
`rag.find_task()`, y no se va a añadir: `find_task` es asíncrona y llama a embeddings, y
`quien_atiende` tiene que seguir siendo síncrona, sin red y sin efectos. `_learn_lookup` sí es
determinista, pero lee `data/command_learning.json`, y `test_regresion_conversacion` **no aísla
`NEXUS_DATA_DIR`**: meterlo ahí ataría la suite al estado de la máquina del desarrollador. Se
deja fuera, se apunta como riesgo residual (§ Preguntas) y se arregla el aislamiento del test,
que es un fallo de hermeticidad real que ha aparecido al diseñar esto.

### 4. Las cinco puertas, como código, en orden de coste

`reglas.valida(r, arbitro) -> (bool, motivo)` las ejecuta en este orden y **corta en la primera
que falle**: la puerta 4 es la única que cuesta tiempo real y no se gasta sobre una regex que ni
compila.

| # | Puerta | Qué corre | Coste | ¿En casa del usuario? |
| --- | --- | --- | --- | --- |
| 1 | **Campos** | forma del dict, tipos, `estado` en el enum, `origen.frase` no vacía | µs | **sí** |
| 2 | **Existencia** | `enrutado`: `destino` ∈ `get_skills()` y el intent existe. `valor`: `clave` ∈ la tabla `VALORES` del código, con tipo y rango | µs | **sí** |
| 3 | **Forma** | `re.compile`, anclaje `^…$` **obligatorio**, longitud mínima y máxima, prohibidos `.*` libre y los cuantificadores anidados (`(a+)+`) | µs | **sí** |
| 4 | **No robo** | barrido `quien_atiende()` sobre el corpus entero, antes y después, con la tabla de transiciones de § 3 | decenas de ms | **sí — es la única red que hay** |
| 5 | **Suite** | `.venv\Scripts\python.exe tests\run_all.py` | minutos | **no** |

Y aquí va la afirmación honesta que este diseño no va a maquillar: **en la máquina de un usuario
activan cuatro puertas, no cinco.** La quinta no es una puerta de activación sino de entrega: se
ejecuta en desarrollo, sobre la **tanda completa** y no regla a regla, y lo que bloquea es
integrar el cambio, no aprobar una regla. Decir otra cosa sería fingir.

**El corpus, sin artefacto nuevo que mantener.** La propuesta y el dueño asumían que el catálogo
de frases pasaría a ser un artefacto a mantener al día. No hace falta: `installer/nexus.spec`
**ya empaqueta `skills/` entero**, y las ~250 frases prometidas salen de las listas de activación
de los `SKILL.md`. Así que el extractor de `test_lo_prometido.ordenes_prometidas()` baja a
producción como `reglas.corpus_prometido()`, leyendo `SKILLS_DIR` (que `comun/config` ya resuelve
bien empaquetado y sin empaquetar), y **el test pasa a importarlo**. Un solo extractor, y el
corpus no puede quedarse obsoleto porque se deriva de los mismos bytes que se distribuyen.

Lo que sí falta empaquetar son las frases de regresión de `test_regresion_conversacion.py`, que
no viajan: se extraen a `config/corpus_regresion.json` y **se añade esa línea a
`installer/nexus.spec`** (hoy de `config/` solo van `settings.example.json` y
`n8n_flujo_ejemplo.json`). El test lee ese fichero en vez de su lista literal.

### 5. Reglas `valor` — capa declarada en código, superposición en datos

`config/umbrales.json` **no se escribe nunca**, y además **no se empaqueta**: en una instalación
limpia ni siquiera existe, y cada lector ya funciona con su reserva en el código
(`rag._UMBRALES_RESERVA`, `remote._carga_umbrales_red()`, `purga._umbrales_purga()`…). Cualquier
diseño que superponga «sobre el fichero» está superponiendo sobre algo que puede no estar.

| Opción | Coste | Decisión |
| --- | --- | --- |
| Lector central `comun/umbrales.py` con hueco para la capa | Migrar 8 lectores, un módulo nuevo en `comun` y el **tercer** hueco rellenado desde arriba: un framework que nadie pidió | rechazada |
| Escribir `umbrales.json` con lo aprendido | Pisa un fichero que el usuario puede haber tocado y deshacer deja de ser borrar datos | rechazada |
| **Tabla `VALORES` en `dominio/reglas.py` + accesor `reglas.valor(clave)`** | Solo los lectores migrados son aprendibles | **elegida** |

`VALORES` mapea `clave → (tipo, rango, reserva)` y **es código, así que viaja siempre**. Una clave
solo se vuelve aprendible cuando alguien migra su lector a `reglas.valor(clave)`, y esa tabla es
literalmente la lista de lectores migrados. `reglas.valor()` resuelve en tres tiempos:
reserva → `umbrales.json` si existe → superposición activa. Deshacer una regla `valor` es cambiar
su `estado`; el fichero del usuario no se ha tocado en ningún momento.

Consecuencia declarada: los lectores que viven en `comun/` e `infraestructura/` **no pueden**
importar `dominio/reglas`, así que sus claves no son aprendibles en este cambio. Las tres de la
decisión 4 del dueño sí lo son, porque viven en `skills/`, que está por encima de todo:
`_ROOM_WORDS` y `_PORT_HINTS` (`skills/domotica/skill.py`) y `_NO_ES_PROGRAMA`
(`skills/system_pc/skill.py`). Ese traslado es **prerrequisito** y va primero.

### 6. Quién propone y quién activa — la línea, dibujada

| Papel | Quién | Puede |
| --- | --- | --- |
| **Proponente primario (determinista)** | `aplicacion/aprendizaje` | Observar la reparación: queja → siguiente turno que **sí** enruta → ese `skill/intent` es el destino, y el patrón es la frase original anclada literal |
| **Generalizador (LLM)** | `llm` vía `selflearn` | **Solo** ensanchar el patrón más allá de la frase literal. Devuelve una cadena candidata |
| **Activador (determinista)** | `dominio/reglas` | Compilar, pasar las cuatro puertas, mutar el estado, escribir la traza |

El LLM nunca emite un veredicto: su salida es **entrada de las puertas**. Si el modelo está
apagado o su generalización falla la puerta 3 o la 4, se cae al patrón literal anclado, que es más
estrecho pero válido. El aprendizaje degrada; no desaparece. Y ninguna cifra ni descripción sale
del modelo: `origen.frase` es literal del operador y `veces` es un contador.

**Umbral de evidencia** (decisión 2 del dueño): `origen.tipo = "ordenada"` —la frase casó
`brain._TEACH_RX`— entra con `veces >= 1`. `origen.tipo = "observada"` espera a
`aprendizaje.umbral_observada` (reserva **3**) ocurrencias **distintas**, contadas por
`(día, frase normalizada)`, para que repetir la misma queja tres veces seguidas de rabia no cuente
como tres pruebas.

### 7. Fallo de código o hueco de enrutado — cómo se distingue, y qué se hace en cada caso

La corrección no se juzga sola: se juzga **su antecedente**, el turno anterior del operador
(`brain._history`, y `data/interactions.jsonl` de `selflearn` como respaldo). Se calcula
`quien_atiende(frase_antecedente)`:

| Veredicto del antecedente | Lectura | Qué hace nexus |
| --- | --- | --- |
| `planificador` | La frase no llegó a nadie: **hueco de enrutado** | Propone una regla |
| `skill:A/i` | La frase **sí** llega, y la skill se comporta mal: **fallo de código** | **No propone nada.** Registra un `aviso` y lo dice: «esa frase sí llega a A/i; una regla lo taparía» |
| `memoria` / `queja` / `charla` | Se la quedó un atajo **anterior** al router | **No propone nada.** Registra un `aviso`: una regla detrás del router no puede recuperar una frase que un atajo previo se comió |

Esa tercera fila es el precio de la posición, y conviene que esté escrito: es exactamente la clase
del fallo de «apunta la mentoría el jueves», y **este mecanismo no lo arregla**. Los `aviso` viven
en el mismo almacén con `tipo: "aviso"`, se listan en «qué has aprendido» bajo un epígrafe aparte
—«fallos, no aprendizajes»— y **siguen apareciendo hasta que alguien los cierra** («ya está
arreglado»). Molestar hasta que se arregle de verdad es la decisión 3 del dueño, y cuesta lo que
él aceptó que costara.

### 8. Aprobación por tandas — sin inventar otro sí/no

«qué has aprendido» renderiza, por cada propuesta: la **frase literal** que la originó, su tipo
(ordenada/observada) y `veces`, el destino, qué puertas ha pasado, y —lo que convierte la
aprobación en una decisión informada— **la lista exacta de frases del corpus que pasarían de
`planificador` a esa skill** si se aprueba.

La aprobación reutiliza `comun/confirm.request()` **sin tocarlo**. Y ahí hay una restricción real:
`confirm.answer()` solo acepta un sí/no corto y **descarta** ante cualquier otra cosa, así que
«aplica la 1 y la 3» desarmaría la confirmación. En vez de extender el módulo que guarda todas las
acciones destructivas del sistema, se diseña alrededor: **la tanda se aprueba o se descarta
entera**, y para aprobar un subconjunto el operador descarta antes las que no quiere («descarta la
2»), que es una mutación que **nunca activa nada** y por tanto no necesita confirmación. La única
dirección con consecuencias pasa por el sí/no de siempre.

Mutaciones, todas con una línea en `audit.log` y **sin borrar nunca**:

| Acción | Efecto |
| --- | --- |
| Aprobar tanda | Se **re-ejecutan las puertas 1-4** en el momento de aprobar (el corpus pudo cambiar) → `propuesta → activa`, `revision += 1` |
| Descartar propuesta | `propuesta → descartada` |
| «olvida lo que aprendiste sobre X» | `activa → revertida` |
| Interruptor de fábrica | Todas → `revertida`, una sola traza con motivo `interruptor_de_fabrica` |
| Borrar `data/reglas_aprendidas.json` | Comportamiento exacto de fábrica; la auditoría sobrevive |

**Skill nueva y orden alfabético.** `skills/aprendizaje/` cae entre `ai_media` y `autoprovision`:
casi la primera que consulta el router, y el router es primera-que-case. Sus cuatro patrones van
**anclados en `^`** y son largos («qué has aprendido», «olvida lo que aprendiste sobre …»,
«descarta la N», «vuelve de fábrica»), y hay una prueba dedicada a que no le quita ninguna frase a
nadie. Ojo además al solape con `brain._FORGET_RX`, que corre antes del router: solo dispara si la
frase estaba en `command_learning.json`, así que «olvida lo que aprendiste sobre las teles» cae
por debajo — pero eso se comprueba, no se supone.

## Flujo de datos

```
   «no, te he dicho esto»                    ┌─ antecedente → quien_atiende() ─┐
            │                                │                                 │
            ▼                                ▼                                 ▼
   brain: _NO_ACCION_RX / _META_QUEJA_RX   planificador                  skill:A/i
            │  (hoy ya: opmem.correccion)    │  hueco                     fallo de codigo
            ▼                                ▼                                 ▼
     aprendizaje.observa() ──────► propuesta (determinista)              tipo: "aviso"
                                        │  + generalizacion del LLM (opcional)
                                        ▼
                          veces >= umbral (1 si ordenada, 3 si observada)
                                        │
                                        ▼
                    reglas.valida(): 1 campos → 2 existencia → 3 forma → 4 NO ROBO
                                        │                                   │
                                        │                         quien_atiende(reglas=())
                                        │                         quien_atiende(reglas=(r,))
                                        ▼                                   │
                        «que has aprendido» ── confirm.request() ◄──────────┘
                                        │
                        si ────────────►│◄──────────── no
                                        ▼
                              estado: activa   ──► audit.log
                                        │
                                        ▼
   proceso de un mensaje:
     atajos (charla/queja/memoria) → route() ─── casa ──► skill        (intocable)
                                        │
                                    None│
                                        ▼
                     _learn_lookup → rag.find_task → APLICA REGLAS → plan_action (LLM)
                                                          │
                                             aplica(texto, ya_enrutado)
                                             ya_enrutado is not None → se devuelve intacto
```

## Ficheros

| Fichero | Acción | Qué cambia |
| --- | --- | --- |
| `backend/core/dominio/reglas.py` | Crear | Contrato, almacén atómico, puertas 1-3, tabla `VALORES`, `valor()`, `corpus_prometido()`, huecos `registrar_arbitro`/`registrar_catalogo` |
| `backend/core/aplicacion/aprendizaje.py` | Crear | Observación de correcciones, propuesta, puerta 4 (barrido), tanda, `aplica(texto, ya_enrutado)`; rellena los huecos al importarse |
| `backend/core/aplicacion/brain.py` | Modificar | Nuevo escalón en `process` (rama `routed is None`, antes de `plan_action`) y en `quien_atiende(…, reglas=None)`; registro del árbitro al final del módulo |
| `backend/core/dominio/selflearn.py` | Modificar | El perfil deja de solo alimentar el prompt: expone la generalización de patrón para el proponente |
| `backend/core/CAPAS.md` | Modificar | Alta de `reglas` (dominio) y `aprendizaje` (aplicación) en la tabla |
| `tests/test_capas_backend.py` | Modificar | Alta de los dos módulos en `CAPAS`; **cero** `EXCEPCIONES` nuevas |
| `tests/test_lo_prometido.py` | Modificar | Importa `reglas.corpus_prometido()` en vez de su extractor propio |
| `tests/test_regresion_conversacion.py` | Modificar | Frases a `config/corpus_regresion.json`; **`NEXUS_DATA_DIR` a carpeta temporal** (hermeticidad) |
| `config/corpus_regresion.json` | Crear | Las frases de aquella tarde, empaquetables |
| `installer/nexus.spec` | Modificar | Añadir `config/corpus_regresion.json` a `datas` |
| `skills/aprendizaje/` | Crear | `SKILL.md` + `skill.py`: solo conversación, patrones anclados |
| `skills/domotica/skill.py` · `skills/system_pc/skill.py` | Modificar | `_ROOM_WORDS`, `_PORT_HINTS`, `_NO_ES_PROGRAMA` → `reglas.valor()` (prerrequisito, decisión 4) |
| `data/reglas_aprendidas.json` | Nueva (ejecución) | El único fichero que nexus escribe |
| `tests/test_reglas_contrato.py` · `test_aprendizaje_puertas.py` · `test_aprendizaje_no_robo.py` | Crear | + **alta en `tests/run_all.py`** |

## Contratos

```python
# backend/core/dominio/reglas.py           (capa: dominio)
ESQUEMA = 1
ESTADOS = ("propuesta", "activa", "revertida", "descartada", "invalida")
TIPOS   = ("enrutado", "valor", "aviso")
VALORES: dict[str, tuple[type, tuple, object]]   # clave -> (tipo, rango, reserva)

def registrar_arbitro(quien_atiende) -> None: ...      # lo rellena aplicacion
def registrar_catalogo(existe_destino) -> None: ...    # idem; por defecto: deniega

def cargar() -> dict:        # {"esquema", "reglas": [...]}; corrupto -> fabrica, nunca lanza
def activas() -> list[dict]  # solo las que vuelven a pasar 1-4 en esta carga
def valida(r: dict) -> tuple[bool, str]                # puertas 1-3 (+4 si hay arbitro)
def guardar(r: dict) -> str                            # atomico, bajo candado; devuelve id
def transitar(rid: str, estado: str, motivo: str) -> bool
def valor(clave: str):                                 # reserva -> umbrales.json -> capa
def corpus_prometido() -> list[str]                    # de skills/*/SKILL.md (empaquetados)

# Una regla, en claro
{"id": "r-8f2a1c", "esquema": 1, "tipo": "enrutado", "revision": 1,
 "origen": {"frase": "cierra chrome", "canal": "pc", "fecha": "2026-08-03T19:12:00",
            "tipo": "observada", "veces": 3},
 "destino": "system_pc/kill_app",
 "patron": r"^\s*cierra\s+(?P<proc>chrome|firefox)\s*$",
 "evidencia": {"arrastradas": ["cierra chrome", "cierra firefox"], "suite": None},
 "estado": "propuesta"}

# backend/core/aplicacion/aprendizaje.py   (capa: aplicacion)
def aplica(texto: str, ya_enrutado):        # -> (enrutado, id_regla); intacto si no es None
def observa(correccion: str, antecedente: str, canal: str) -> dict   # propuesta | aviso | {}
def barrido(regla: dict) -> dict            # {"robadas": [...], "arrastradas": [...]}
def pendientes() -> list[dict]              # lo que renderiza «que has aprendido»
def aprobar_tanda(canal: str) -> str        # via confirm.request(); revalida antes
def descartar(rid: str) -> bool
def olvidar(consulta: str) -> int
def de_fabrica() -> int

# backend/core/aplicacion/brain.py
def quien_atiende(text: str, channel: str = "pc", reglas=None) -> str
```

## Estrategia de pruebas

| Capa | Qué se prueba | Cómo |
| --- | --- | --- |
| Arquitectura | `reglas` y `aprendizaje` están en su capa y **no añaden excepciones** | `test_capas_backend.py`, sin tocar `EXCEPCIONES` |
| Unidad | Fichero corrupto / truncado / con `esquema: 9` → fábrica, sin excepción; una regla podrida no tumba a las sanas | carpeta temporal, `NEXUS_DATA_DIR` |
| Unidad | `estado: "activa"` escrito a mano **no** activa: se revalida al cargar | fichero fabricado a mano |
| Unidad | Puertas 1-3 rechazan: campo ausente, destino inexistente, regex sin anclar, `.*` libre, cuantificador anidado | `check()` sin skills |
| Unidad | `valor()` resuelve reserva → fichero → capa, y revertir devuelve el valor original **sin escribir `umbrales.json`** | `sha256` del fichero antes y después |
| Integración | **No robo**: ninguna de las ~250 frases cambia de dueño con cualquier regla activa; solo se admite `planificador → skill:*` | `quien_atiende(reglas=())` vs `quien_atiende(reglas=(r,))` |
| Integración | `aplica(texto, ya_enrutado)` con `ya_enrutado` no nulo devuelve **el mismo objeto** | identidad, no igualdad |
| Integración | Antecedente que ya llega a una skill → **cero propuestas** y un `aviso` | corrección simulada |
| Integración | `propuesta` no enruta; solo tras `confirm` con sí; un «no» deja todo igual | ciclo completo con `confirm` |
| Invariante | **Ningún `.py` es escrito por nexus**: `mtime` de todos los `.py` del proyecto antes y después de un ciclo completo | recorrido del árbol |
| Invariante | Ninguna ruta del código de aprendizaje escribe fuera de `DATA_DIR` | lectura del propio fichero + `Path.resolve()` |
| Invariante | Cero datos personales en los ficheros nuevos | se extiende la guarda de `test_skill_domotica.py:372` |
| Aceptación | Al menos **3 de los once fallos del 03/08** se resuelven aprendiendo, sin editar `skill.py` | barrido contra nexus en marcha |

## Matriz de amenazas (lo aplicable)

Sí hay frontera de **enrutado**; no hay shell, subprocesos, automatización de VCS/PR,
clasificación de ejecutables ni integración de procesos.

| Amenaza | Aplic. | Requisito de diseño (pasa a tareas y a test RED) |
| --- | --- | --- |
| **ReDoS**: una regex aprendida corre en **cada** mensaje; un retroceso catastrófico cuelga nexus | Sí | Puerta 3 prohíbe cuantificadores anidados y `.*` libre y acota la longitud; la puerta 4 mide el barrido y **descarta si excede el presupuesto de tiempo** (no hay módulo `regex` con timeout en el proyecto) |
| **Regla inyectada** editando el JSON a mano | Sí | Revalidación de puertas 1-4 en cada carga; el `estado` del fichero no otorga permiso |
| **Regla ancha** que arrastra frases que no eran el objetivo | Sí | `tope_frases_arrastradas` en el barrido; por encima, descartada con el listado del arrastre |
| **Destino que desaparece** (skill desinstalada o renombrada) | Sí | Puerta 2 al cargar → regla aislada como `invalida`, nexus arranca |
| **Dato personal en `origen.frase`** que acabe distribuido | Sí | Vive en `data/`, que **no** se empaqueta (verificado en `nexus.spec`); nunca se sube ni se sincroniza; guarda de contenido en la suite |
| **Crecimiento sin límite** del almacén | Sí | Las **propuestas** caducan a los `dias_caducidad_propuesta` (nunca estuvieron activas); las activas **no se podan** — un tope sería un borrado automático, y aquí no hay ninguno |
| Shell / subprocesos / VCS-PR / ejecutables / integración de procesos | N/A | El mecanismo no ejecuta nada: elige un `skill/intent` que ya existía |

## Migración y despliegue

No hay migración: el almacén nace vacío y su ausencia es el estado de fábrica. Nada se ejecuta al
arrancar — la carga y la revalidación son perezosas, en la primera consulta. Orden de entrega
obligado, y la razón por la que no se puede alterar:

| PR | Contenido | Líneas est. | Por qué es autónomo |
| --- | --- | --- | --- |
| **A — listas fuera del código** | `_ROOM_WORDS`, `_PORT_HINTS`, `_NO_ES_PROGRAMA` → `reglas.valor()`; `reglas.py` mínimo con `VALORES` y almacén | ~300 | Decisión 4 del dueño: no se aprende sobre lo que está a fuego. Puramente refactor, revertible solo |
| **B — contrato, puertas y corpus** | Puertas 1-4, `corpus_prometido()`, `corpus_regresion.json` + `nexus.spec`, `quien_atiende(reglas=)`, hermeticidad del test de regresión | ~450 | No activa nada: solo sabe **juzgar**. Verificable sin skill nueva |
| **C — propuesta, tanda y consulta** | `aprendizaje.py`, escalón en `process`, `skills/aprendizaje/`, avisos de fallo de código | ~430 | Es el único que cambia el comportamiento en marcha, y se revisa con B ya verde |

Reversión, sin depender de git (en la máquina del usuario no lo hay): «olvida lo que aprendiste
sobre X» → `revertida`; interruptor de fábrica → toda la tanda; borrar
`data/reglas_aprendidas.json` → comportamiento exacto de fábrica. En desarrollo, además,
`git revert` por PR.

**Aviso de estimación**: ~1.180 líneas en total. Cada PR queda por debajo del presupuesto de 400
líneas revisables solo si se respetan los tres cortes; el conjunto no cabe en uno.

## Preguntas abiertas

- [ ] **Riesgo residual declarado**: `rag.find_task()` puede cambiar el destino de una frase y el
      barrido no lo ve, porque `quien_atiende()` no lo modela (es asíncrono y usa embeddings).
      Es literalmente «una prueba que mira un escalón por debajo». Se propone dejarlo fuera y
      documentarlo en la propia suite; confirmar en `sdd-tasks`.
- [ ] Coexisten dos almacenes de enrutado aprendido (`command_learning.json`, sin puertas, y
      `reglas_aprendidas.json`, con ellas). Se propone **no** migrar en 004 —el primero solo
      casa frases exactas y tampoco puede robarle al router— y consolidarlos en un cambio propio.
- [ ] Valor de reserva de `umbral_observada` (propuesto **3**) y de `tope_frases_arrastradas`
      (propuesto **2**): se fijan en `VALORES` y se ajustan con los once fallos del 03/08 como
      banco de pruebas.
- [ ] ¿El `aviso` de «esto es un fallo de código» debe además abrir una tarea en el tablero?
      Se propone **no** por ahora: molestar en «qué has aprendido» ya cumple la decisión 3 sin
      meter ruido en el tablero del operador.
