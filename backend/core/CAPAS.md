# Las capas de `backend/core/`

`core/` son 43 módulos y unas 15.000 líneas. Estaban en **una sola carpeta
plana**, donde nada impedía que el módulo que habla con la API de Google llamara
a las reglas del tablero, ni al revés.

Ahora cada módulo vive en la carpeta de su capa, así que **la arquitectura se ve
abriendo `core/`**: cuatro carpetas en vez de cuarenta y dos ficheros. Antes la
capa de un módulo era una lista dentro de una prueba — se podía leer el fichero
sin enterarse de dónde estaba.

`tests/test_capas_backend.py` comprueba en cada ejecución que lo escrito aquí, lo
que hay en disco y lo que importa cada módulo dicen lo mismo. Y que nadie deje un
módulo suelto en la raíz: volver a la carpeta plana por la puerta de atrás no se
notaría hasta tener veinte otra vez.

## La regla

Las dependencias van **hacia abajo, nunca hacia arriba**:

```
  aplicación      orquesta: decide qué se ejecuta y cuándo
       ↓
    dominio       las reglas del negocio: tablero, memoria, contenido
       ↓
 infraestructura  habla con el mundo: modelos, red, disco, APIs
       ↓
     común        lo que usa todo el mundo y no depende de nadie
```

Una capa puede importar de la suya y de las de abajo. **Nunca de las de arriba.**

Por qué importa: la capa común se puede leer sin saber nada del resto. El dominio
se puede probar sin levantar la red. Y cuando algo de infraestructura necesita
llamar al dominio, eso es una señal de que la dependencia está del revés — no un
detalle de estilo.

## Quién está en cada capa

| Capa | Módulos |
| --- | --- |
| **común** | `config`, `events`, `audit`, `permissions`, `confirm`, `procedencia`, `context`, `net`, `publicvoice` |
| **infraestructura** | `llm`, `llm_runtime`, `tts`, `stt`, `remote`, `files_io`, `engram_bridge`, `websearch`, `telegram_bridge`, `spotify`, `hardware`, `app_index` |
| **dominio** | `board`, `purga`, `contentos`, `contentos_demo`, `rag`, `memory`, `selflearn`, `opmem`, `briefing`, `profile`, `review`, `ingesta`, `pm`, `reglas` |
| **aplicación** | `brain`, `skills_loader`, `scheduler`, `background`, `jobs`, `wake`, `hotkey`, `voice_cycle` |

Cuatro colocaciones que no son obvias, y el test fue quien las señaló:

- **`events` en común**, aunque sea un bus. Lo usan veinte módulos de todas las
  capas, incluida la más baja. Un bus al que solo puede escribir la capa de
  arriba no sirve de nada.
- **`publicvoice` en común**, no en infraestructura. No habla con nadie: es una
  regla de presentación (`sanitize` quita la fontanería interna de lo que se le
  enseña al usuario). La usa `events`, que está por debajo de todo.
- **`brain` y `voice_cycle` en aplicación**, no en dominio. No contienen reglas
  de negocio: deciden **qué se ejecuta**. `brain` elige skill e intent y lanza
  trabajos; `voice_cycle` escucha, transcribe y se lo pasa al cerebro. Eso es
  orquestación. Lo mismo con `wake` y `hotkey`, que son puntos de entrada.
- **`pm` en dominio**, no en infraestructura. Detecta compromisos en lo que
  hablas y los convierte en tareas: eso son reglas del negocio.
- **`reglas` en dominio**, aunque lo que aprende sea enrutado. Guarda el almacén
  de reglas aprendidas y la tabla de listas y umbrales que han salido del código.
  Quien sabe enrutar (`brain`) y quién sabe qué destinos existen
  (`skills_loader`) están en aplicación, así que no se importan: se registran
  desde arriba, como hace `events`. Sin ese registro no se activa nada.

## Deuda aceptada, con nombre y apellidos

Estas dependencias incumplen la regla. Están en la lista de excepciones del test,
así que no rompen la suite, pero **cada una es un pendiente, no una licencia**.
Añadir una nueva exige tocar el test a mano, que es justo la fricción que se
busca.

Los cuatro ciclos directos que hay hoy en `core/`:

- `llm ↔ llm_runtime` — el runtime elige el modelo y `llm` le pregunta cuál hay.
- `llm ↔ selflearn` — `selflearn` pide al modelo, y `llm` consulta lo aprendido.
- `memory ↔ rag` — la memoria busca por vectores y el RAG guarda en la memoria.
- `brain ↔ telegram_bridge` — el puente entrega al cerebro y el cerebro contesta
  por el puente.

Un ciclo no es fatal en Python, pero obliga a importar dentro de la función para
que no reviente al cargar, y eso esconde la dependencia. Romperlos es trabajo
para otro día, y lo primero es que se vean.
