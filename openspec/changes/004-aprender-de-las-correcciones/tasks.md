# Tareas: 004 — Aprender de las correcciones

Manda `openspec/changes/004-aprender-de-las-correcciones/design.md` y, por encima
de él, la sección «Decisiones del dueño (03/08/2026)» de `proposal.md`. Entrega en
**tres bloques secuenciales A → B → C**, cada uno un commit (o grupo de commits)
directo sobre `main`, verificable por separado con
`.venv\Scripts\python.exe tests\run_all.py` en **TODO VERDE**. `git remote` tiene
un solo `main` y no hay flujo de PRs en este repositorio: «PR» aquí es la unidad
de revisión de una sentada.

**Regla de esta fase, y es la que ha costado dos disgustos hoy**: ninguna tarea
se da por hecha razonando. Cada una dice qué se **ejecuta** para comprobarla, y
cada prueba nueva trae escrito **cómo demostrar que puede ponerse roja**. Una
prueba que no sabes hacer fallar no prueba nada, y una que mira un escalón por
debajo del fallo lo declara arreglado.

## Review Workload Forecast

| Campo | Valor |
|---|---|
| Líneas estimadas (total) | ~1540 (A ~360, B ~620, C ~560) |
| Presupuesto de revisión | 800 líneas por bloque |
| Riesgo frente a 800 | Bajo por bloque (ninguno lo alcanza); el conjunto lo dobla — por eso hay tres |
| Riesgo frente al umbral genérico de 400 | A: Medio (360) · B: Alto (620) · C: Alto (560) |
| PRs encadenados recomendados | Sí |
| División sugerida | A (listas fuera del código) → B (contrato, puertas y corpus) → C (propuesta, tanda y consulta) |
| Estrategia de entrega | auto-chain |
| Estrategia de cadena | stacked-to-main (recomendada, ver abajo) |

```text
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High
```

**Por qué `stacked-to-main` y no `feature-branch-chain`**: A es un refactor puro
con valor propio —saca del código tres listas que ya figuraban como deuda en
`estado.md`— y aporta aunque B y C no lleguen nunca. Una cadena con rama
integradora lo dejaría rehén de C. Además el repositorio tiene una sola rama y el
historial son commits directos sobre `main`: montar un tracker sería inventar un
proceso que aquí no existe. La contrapartida asumida: si B resulta equivocado, A
ya está en `main` y hay que revertirlo aparte — barato, porque A es reversible
solo.

### Suggested Work Units

| Unidad | Objetivo | Entrega | Test enfocado | Arnés de ejecución real | Frontera de rollback |
|---|---|---|---|---|---|
| A | `dominio/reglas.py` mínimo (almacén atómico, `VALORES`, `valor()`, huecos) y las tres listas del dueño leídas desde ahí. Cero aprendizaje. | A | `.venv\Scripts\python.exe tests\test_reglas_valores.py` | **Reinicio obligatorio** (`cmd /c start "" run.bat`) y barrido a mano de «apaga la tele del salón», «cierra chrome», «cierra la sesión» contra nexus en marcha | `git revert` del bloque; sin `reglas.py` las tres listas vuelven al `.py`. Nada de usuario cambia |
| B | Puertas 1-4, `corpus_prometido()`, `corpus_regresion.json` + `nexus.spec`, `quien_atiende(reglas=)`, `aplicacion/aprendizaje.py` que solo sabe **juzgar** | B | `.venv\Scripts\python.exe tests\test_aprendizaje_no_robo.py` | Sin reinicio: nada cambia en marcha. Verificar a mano que `corpus_prometido()` devuelve 255 frases distintas y que `quien_atiende(reglas=())` da el mismo resultado que hoy, frase a frase | `git revert`; sin él `quien_atiende` recupera su firma de un argumento. Ninguna regla activable existe todavía |
| C | `observa()`, avisos de fallo de código, tanda con `confirm`, `aplica()` en `process`, `skills/aprendizaje/` | C | `.venv\Scripts\python.exe tests\test_aprendizaje_ciclo.py` | **Reinicio obligatorio** + barrido contra nexus en marcha: tres de los once fallos del 03/08 resueltos aprendiendo, sin editar un `skill.py` | `git revert`; y sin git, borrar `data/reglas_aprendidas.json` devuelve fábrica exacta |

### Dependencias entre bloques

- **B depende de A**: usa `reglas.py`, su almacén y su tabla `VALORES` como base
  sobre la que añadir el contrato y las puertas.
- **C depende de B**: no se puede proponer nada que no se sepa juzgar. C es el
  único bloque que cambia el comportamiento en marcha, y se revisa con B verde.
- **A no depende de nada** y es la decisión 4 del dueño: no se aprende sobre lo
  que está a fuego.

### Divergencias con el diseño detectadas al planificar (leer antes de aplicar)

1. **`test_regresion_conversacion.py` YA aísla `NEXUS_DATA_DIR`** (línea 37,
   commit `247d517`). El diseño §3 lo daba como pendiente. La tarea B4.4 pasa de
   «arreglar» a «comprobar que sigue aislado y que nadie lo quita».
2. **El corpus prometido son 255 frases distintas de 259 apariciones**, medido
   hoy ejecutando el extractor de `test_lo_prometido.py`. La propuesta dice 244;
   manda la cifra medida.
3. **`_PORT_HINTS` no es una lista: es un `dict[int, str]` cuyo ORDEN es la
   prioridad** (`skill.py:538`, «orden de `_PORT_HINTS` = prioridad»). En JSON las
   claves son cadenas. Sacarlo del código sin conservar orden ni el tipo `int`
   rompe el sondeo de puertos **en silencio**: sigue devolviendo una etiqueta,
   solo que la equivocada. Tarea propia: A3.2.
4. **`_NO_ES_PROGRAMA` no es una lista: es un fragmento de regex que se concatena
   en tiempo de importación** (`system_pc/skill.py:170,173`). Hoy **ninguna skill
   importa `backend.core` a nivel de módulo**: todas lo hacen dentro de la
   función. Migrarlo obliga a elegir entre un import de módulo (nuevo en el
   proyecto) o compilar el patrón perezosamente. Tarea propia con decisión
   explícita: A3.3.

---

## Bloque A — Las listas salen del código (prerrequisito, decisión 4 del dueño)

Puramente mecánico. Ni una regla, ni una puerta, ni una propuesta. Lo único que
cambia de comportamiento es **de dónde se lee** un valor, y la prueba de que salió
bien es que nada cambia.

### A1. `dominio/reglas.py` — el almacén, sin contrato todavía

- [x] A1.1 Crear `backend/core/dominio/reglas.py` con `ESQUEMA = 1`, `cargar()` y
      `guardar()`. Lectura: principal → `.bak` → fábrica (`{"esquema":1,"reglas":[]}`),
      **nunca lanza**. Escritura: `.bak` + `.tmp` + `os.replace` calcando
      `comun/config._write_json_atomic()`. `threading.Lock` de módulo alrededor de
      la lectura-modificación-escritura entera. Importa **solo** `comun/config` y
      `comun/audit`. — *Cubre*: aprendizaje-contrato, req. «Almacén único y
      restablecimiento de fábrica» — *Test*: `test_reglas_valores.py::test_almacen_corrupto_degrada_a_fabrica`
- [x] A1.2 Huecos de inversión de dependencia, con el valor por defecto **al revés
      que `events`**: `registrar_arbitro(fn)` y `registrar_catalogo(fn)`; sin
      rellenar, `existe_destino()` devuelve `False` y el barrido devuelve «no lo
      sé». Sin árbitro no hay activación. — *Cubre*: enrutado-aprendido, req. «El
      módulo del aprendizaje respeta las capas» — *Test*: `test_reglas_valores.py::test_sin_arbitro_no_activa_nada`
- [x] A1.3 Dar de alta `reglas` en el bloque `dominio` de la lista `CAPAS` de
      `tests/test_capas_backend.py` **y** en la tabla de `backend/core/CAPAS.md`.
      Cero entradas nuevas en `EXCEPCIONES`. — *Cubre*: enrutado-aprendido, escenario
      «Suite de capas tras añadir el módulo» — *Verificación*:
      `.venv\Scripts\python.exe tests\test_capas_backend.py` sale en 0.
      **Cómo probar que puede fallar**: crea el fichero SIN darlo de alta y ejecuta
      la suite; tiene que decir «`reglas` no está en ninguna capa». Luego dalo de
      alta solo en el test y no en `CAPAS.md`: la comprobación 5 tiene que seguir
      roja.

### A2. La tabla `VALORES` y el accesor

- [x] A2.1 `VALORES: dict[str, tuple[type, tuple, object]]` — `clave → (tipo, rango,
      reserva)`. Es **código**, así que viaja siempre y en una instalación limpia
      funciona sin `umbrales.json`. Tres claves iniciales, y ninguna más:
      `domotica.room_words`, `domotica.port_hints`, `system_pc.no_es_programa`. —
      *Cubre*: aprendizaje-contrato, req. «Dos tipos de regla, y solo dos» (rama `valor`)
- [x] A2.2 `reglas.valor(clave)` resuelve en tres tiempos: **reserva de `VALORES` →
      `config/umbrales.json` si existe → capa de superposición activa**. Clave
      desconocida: lanza, no devuelve `None` en silencio. — *Cubre*:
      aprendizaje-validacion, req. «Puerta de existencia» — *Test*:
      `test_reglas_valores.py::test_valor_resuelve_en_tres_tiempos`
- [x] A2.3 **`umbrales.json` NO se escribe nunca.** Prueba de invariante: `sha256`
      del fichero antes y después de un ciclo completo de `valor()` + superposición
      + reversión. — *Cubre*: aprendizaje-contrato, req. «nexus escribe datos, nunca
      código» — *Test*: `test_reglas_valores.py::test_umbrales_json_no_se_toca`
      **Cómo probar que puede fallar**: mete un `_write_json_atomic(CONFIG_DIR/"umbrales.json", …)`
      temporal dentro de `valor()`; el test tiene que ponerse rojo. Quítalo.
- [x] A2.4 Bloque `aprendizaje` en `config/umbrales.json` (`umbral_observada: 3`,
      `tope_frases_arrastradas: 2`, `dias_caducidad_propuesta`,
      `presupuesto_ms_barrido`), sin tocar ninguna clave existente. **No** se toca
      `config/settings.json` ni `config/secrets.json`. — *Cubre*:
      aprendizaje-correcciones, req. «La evidencia depende de quién lo diga»

### A3. Los tres lectores migrados (uno por tarea: cada uno tiene su trampa)

- [x] A3.1 `skills/domotica/skill.py:1677` — `_ROOM_WORDS` pasa a
      `reglas.valor("domotica.room_words")`, reserva = el `set` literal de hoy. Es
      el caso fácil: se lee dentro de `_resolve_named_device()`, así que el import
      va dentro de la función, como hace el resto de skills. — *Cubre*:
      enrutado-aprendido, req. «Las listas salen del código antes que las reglas de
      valor» — *Test*: `test_reglas_valores.py::test_room_words_sale_de_reglas`
      **⚠ Reinicio**: `cmd /c start "" run.bat` antes de probar comportamiento.
- [x] A3.2 `skills/domotica/skill.py:506` — `_PORT_HINTS` pasa a
      `reglas.valor("domotica.port_hints")` **conservando el orden** (es la
      prioridad del sondeo, `skill.py:538`) y **reconvirtiendo las claves a `int`**
      al leerlas de JSON. — *Cubre*: enrutado-aprendido, mismo requisito — *Test*:
      `test_reglas_valores.py::test_port_hints_conserva_orden_y_claves_int`
      **Cómo probar que puede fallar**: el test compara `list(valor(...).keys())`
      con la lista literal esperada **en orden** y afirma `all(isinstance(k,int))`.
      Rómpelo a propósito envolviendo el resultado en `dict(sorted(...))` y en
      claves `str`: tiene que dar rojo por las dos razones, por separado.
      **⚠ Reinicio**.
- [x] A3.3 `skills/system_pc/skill.py:43` — `_NO_ES_PROGRAMA` es un fragmento de
      regex usado **al importar el módulo** (líneas 170 y 173). Decidir y dejar
      escrito en un comentario cuál de las dos: (a) import de
      `backend.core.dominio.reglas` a nivel de módulo —nuevo en este proyecto, hoy
      todas las skills importan dentro de la función— o (b) compilar los patrones
      de `kill` perezosamente en el primer uso. Recomendada (a) por ser menos
      código, con la comprobación de A3.4 como red. — *Cubre*: enrutado-aprendido,
      mismo requisito — *Test*: `test_reglas_valores.py::test_no_es_programa_sale_de_reglas`
      **⚠ Reinicio**.
- [x] A3.4 Comprobar que ninguna skill se queda en `status: error` al arrancar por
      un import circular o un import de módulo nuevo: `load_skills()` y afirmar que
      las 32 cargan. — *Verificación*:
      `.venv\Scripts\python.exe tests\run_all.py` bloque «2) contrato de cada skill»
      sin fallos, **y** el arranque real sin skills en rojo en el HUD.
      **Cómo probar que puede fallar**: mete un `import backend.core.aplicacion.brain`
      a nivel de módulo en `system_pc/skill.py`; el arranque tiene que quejarse.
      Quítalo.

### A4. Que nada haya cambiado — la única prueba que importa en A

- [x] A4.1 Crear `tests/test_reglas_valores.py` (patrón `check(cond, msg)`, sin
      pytest, `NEXUS_DATA_DIR` a carpeta temporal como hace `test_lo_prometido.py`)
      con todos los casos de A1-A3.
- [x] A4.2 Añadir `"test_reglas_valores.py"` a la tupla de suites de
      `tests/run_all.py`. Una suite sin dar de alta **no se ejecuta nunca**. —
      *Cubre*: enrutado-aprendido, escenario «Suites nuevas registradas»
      **Cómo probar que puede fallar**: rompe una comprobación de la suite a
      propósito y ejecuta `run_all.py`; si sale verde, no la diste de alta.
- [x] A4.3 **Equivalencia antes/después, ejecutada**: guardar la salida de
      `quien_atiende()` sobre las 255 frases prometidas **antes** de tocar nada
      (`git stash` incluido si hace falta), repetir después, y comparar frase a
      frase. Cero diferencias. — *Cubre*: enrutado-aprendido, req. «Sin reglas
      activas, comportamiento idéntico al de fábrica» — *Verificación*:
      `.venv\Scripts\python.exe tests\test_lo_prometido.py` y
      `tests\test_regresion_conversacion.py`, los dos en 0, más el diff de las dos
      salidas vacío.
- [x] A4.4 **⚠ Reinicio + barrido a mano** contra nexus en marcha: «apaga la tele
      del salón», «cierra chrome», «cierra la sesión», «quítale el silencio al pc» y
      un descubrimiento de red que llegue a `_probe_ports`. Un `run_all.py` verde
      **no** prueba el sondeo de puertos: ahí no hay red.

---

## Bloque B — Contrato, puertas y corpus (sabe juzgar, no activa nada)

Al terminar B, nexus sabe decir de cualquier regla si es válida y a quién le
robaría. Sigue sin poder proponer ni activar ninguna. Ese es el corte: se puede
revisar entero sin skill nueva y sin cambiar el comportamiento en marcha.

### B1. El contrato y las puertas 1-3, en `dominio/reglas.py`

- [x] B1.1 `ESTADOS = ("propuesta","activa","revertida","descartada","invalida")`,
      `TIPOS = ("enrutado","valor","aviso")`, y `transitar(rid, estado, motivo)` que
      **rechaza** `revertida → activa`. Nada se borra. — *Cubre*:
      aprendizaje-contrato, req. «Estados y transiciones permitidas» — *Test*:
      `test_reglas_contrato.py::test_revertida_no_vuelve_a_activa`
- [x] B1.2 **Puerta 1 (campos)**: los ocho campos, `origen.frase` literal y no
      vacía, `origen` con canal y fecha. Falla nombrando el campo que falta. —
      *Cubre*: aprendizaje-validacion, req. «Puerta de campos» — *Test*:
      `test_reglas_contrato.py::test_puerta_campos_nombra_el_que_falta`
- [x] B1.3 **Puerta 2 (existencia)**: `enrutado` → `destino` ∈ `get_skills()` con el
      intent presente y la skill no en `error`; `valor` → clave en `VALORES`, con
      tipo y rango. Usa el hueco `registrar_catalogo`, así que sin árbitro deniega.
      — *Cubre*: aprendizaje-validacion, req. «Puerta de existencia» — *Test*:
      `test_reglas_contrato.py::test_destino_inexistente_y_rango_fuera`
- [x] B1.4 **RED — ReDoS**: `test_reglas_contrato.py::test_puerta_forma_rechaza_cuantificador_anidado`
      con `^(a+)+$` y con `^.*$`. Escribir el test **antes**; contra el código de
      hoy no existe `valida()` y tiene que fallar por eso. — *Cubre*: matriz de
      amenazas, «ReDoS»
- [x] B1.5 **GREEN — Puerta 3 (forma)**: `re.compile`, anclaje `^…$` **obligatorio**,
      longitud mínima y máxima, prohibidos `.*` libre y los cuantificadores
      anidados. Hace pasar B1.4. — *Cubre*: aprendizaje-validacion, req. «Puerta de forma»
- [x] B1.6 **RED — regla inyectada a mano**:
      `test_reglas_contrato.py::test_estado_activa_escrito_a_mano_no_activa` —
      fabricar `data/reglas_aprendidas.json` con una regla podrida en
      `estado: "activa"` y comprobar que `activas()` no la devuelve. — *Cubre*:
      matriz de amenazas, «Regla inyectada»
- [x] B1.7 **GREEN — revalidación en cada carga**: `activas()` vuelve a pasar 1-4
      sobre cada regla; la que falla queda aislada como `invalida` con `motivo` y
      **no tumba a las sanas**. `esquema` mayor que `ESQUEMA` → almacén en solo
      lectura, cero activas, motivo visible. — *Cubre*: aprendizaje-contrato, req.
      «`revision` ata la regla al catálogo» y matriz de amenazas, «Destino que
      desaparece» — *Test*: `test_reglas_contrato.py::test_una_regla_podrida_no_invalida_las_sanas`,
      `::test_esquema_futuro_no_activa_nada`
- [x] B1.8 Huella de revalidación perezosa: `huella_corpus` (nº de `SKILL.md`,
      `mtime` máximo, nº de frases) + `huella_reglas` (sha256 del conjunto activo).
      Si coinciden, se salta el barrido; si cambia cualquiera, se rehace. **En la
      primera consulta, nunca al importar**: si las skills no cargan, nexus arranca
      igual. — *Test*: `test_reglas_contrato.py::test_cambiar_el_corpus_fuerza_revalidacion`
      **Cómo probar que puede fallar**: toca el `mtime` de un `SKILL.md` y afirma
      que el contador de barridos sube. Sin el cambio, el test miraría solo el
      resultado —que es idéntico— y no vería nada: **cuenta barridos, no
      resultados**.

### B2. El corpus, sin artefacto nuevo que mantener

- [x] B2.1 `reglas.corpus_prometido() -> list[str]` — el extractor de
      `test_lo_prometido.ordenes_prometidas()` baja a producción leyendo
      `config.SKILLS_DIR`, que ya resuelve bien empaquetado y sin empaquetar.
      Devuelve las **255 frases distintas** medidas hoy. — *Cubre*:
      aprendizaje-validacion, req. «Puerta de no robo» (el corpus) — *Test*:
      `test_aprendizaje_no_robo.py::test_corpus_prometido_255_distintas`
- [x] B2.2 `tests/test_lo_prometido.py` **importa** `reglas.corpus_prometido()` en
      vez de su extractor propio. Un solo extractor, y el corpus no puede quedarse
      obsoleto porque sale de los mismos bytes que se distribuyen. — *Verificación*:
      la suite sigue en 0 y sigue diciendo «255 ordenes distintas».
- [x] B2.3 Crear `config/corpus_regresion.json` con las frases de
      `test_regresion_conversacion.py` (bloques 1 y 2) y su dueño esperado.
      `test_regresion_conversacion.py` lee ese fichero en vez de su lista literal. —
      *Cubre*: aprendizaje-validacion, req. «Puerta de no robo» (el catálogo viaja)
- [x] B2.4 Añadir `config/corpus_regresion.json` a `datas` en
      `installer/nexus.spec` (hoy de `config/` solo van `settings.example.json` y
      `n8n_flujo_ejemplo.json`). — *Cubre*: decisión 1 del dueño — *Test*:
      `test_aprendizaje_no_robo.py::test_corpus_regresion_esta_en_el_spec`
      **Cómo probar que puede fallar**: el test lee `installer/nexus.spec` y busca
      la ruta. Quita la línea del spec: rojo. Y `data/` **no** puede aparecer en
      `datas` — el mismo test lo afirma.
- [x] B2.5 **RED — catálogo ausente**:
      `test_aprendizaje_no_robo.py::test_sin_catalogo_ninguna_regla_activa` — con
      `SKILLS_DIR` apuntando a una carpeta vacía, la puerta 4 falla y **ninguna**
      regla se activa. Validar a ciegas es peor que no aprender. — *Cubre*:
      aprendizaje-validacion, escenario «Catálogo ausente en la instalación»

### B3. `aplicacion/aprendizaje.py` — la puerta 4 y nada más

- [x] B3.1 Crear `backend/core/aplicacion/aprendizaje.py`. Importa
      `dominio/reglas` (abajo) y `aplicacion/skills_loader` (misma capa). **No
      importa `brain`**: es `brain` quien se registra al final de su módulo con
      `aprendizaje.registrar_arbitro(quien_atiende)`. Cero ciclos nuevos. — *Cubre*:
      enrutado-aprendido, req. «El módulo del aprendizaje respeta las capas»
- [x] B3.2 Dar de alta `aprendizaje` en el bloque `aplicacion` de `CAPAS` en
      `tests/test_capas_backend.py` y en la tabla de `backend/core/CAPAS.md`. **Cero
      entradas nuevas en `EXCEPCIONES`.** — *Verificación*:
      `.venv\Scripts\python.exe tests\test_capas_backend.py` en 0, y `EXCEPCIONES`
      con las cuatro de siempre, ni una más.
- [x] B3.3 `aprendizaje.barrido(regla) -> {"robadas": [...], "arrastradas": [...]}`:
      `quien_atiende(f, reglas=())` vs `quien_atiende(f, reglas=(r,))` sobre el
      corpus entero. Tabla de veredictos del diseño §3: cualquier transición que no
      sea `planificador → regla:<id>` es **robo**. — *Cubre*: aprendizaje-validacion,
      req. «Puerta de no robo» — *Test*: `test_aprendizaje_no_robo.py::test_regla_ladrona_se_descarta_nombrando_la_frase`
- [x] B3.4 **RED — regla ancha**:
      `test_aprendizaje_no_robo.py::test_arrastre_por_encima_del_tope_se_descarta` —
      regla que arrastra más frases que `tope_frases_arrastradas`; se descarta **con
      el listado del arrastre**, no con un booleano. — *Cubre*: matriz de amenazas,
      «Regla ancha»
- [x] B3.5 **RED — presupuesto de tiempo**:
      `test_aprendizaje_no_robo.py::test_barrido_lento_descarta_la_regla` — el
      barrido se mide y, por encima de `presupuesto_ms_barrido`, la regla se
      descarta. No hay módulo `regex` con timeout en el proyecto, así que esta es
      la única defensa en ejecución contra un retroceso catastrófico. — *Cubre*:
      matriz de amenazas, «ReDoS» (segunda mitad)
- [x] B3.6 **GREEN** implementar el tope y la medida de B3.4/B3.5.
- [x] B3.7 **La puerta 5 no se ejecuta aquí y no se marca como superada.** En
      instalación de usuario se registra `no_aplicable` en la auditoría; en
      desarrollo la ejecuta el humano sobre la **tanda entera**, no regla a regla. —
      *Cubre*: aprendizaje-validacion, req. «Puerta de suite» — *Test*:
      `test_aprendizaje_puertas.py::test_puerta_suite_nunca_se_marca_superada_sola`
      **Cómo probar que puede fallar**: escribe `"suite": True` a mano en la
      evidencia de una regla y comprueba que la auditoría sigue diciendo
      `no_aplicable`. Si el test lee la evidencia en vez de la auditoría, mira un
      escalón por debajo.

### B4. `quien_atiende(reglas=)` y la hermeticidad que ya estaba

- [x] B4.1 `brain.quien_atiende(text, channel="pc", reglas=None)`. `reglas=()`
      significa «ninguna» y `reglas=None` «las activas del almacén». Función
      **pura**: sin mutar globales ni parchear módulos, para que el barrido sea la
      misma función llamada dos veces. — *Cubre*: enrutado-aprendido, req.
      «`quien_atiende()` declara el atajo nuevo»
- [x] B4.2 El escalón nuevo va **después de `r = route(t)`** y después de
      `_META_QUEJA_RX`, justo antes de devolver `planificador`. Devuelve
      `regla:<id>`. — *Cubre*: enrutado-aprendido, req. «Invariante de posición» —
      *Test*: `test_aprendizaje_no_robo.py::test_solo_transicion_planificador_a_regla`
- [x] B4.3 Añadir el atajo nuevo a la lista de guardas que vigila
      `test_regresion_conversacion.py:174` (`_SMALLTALK_RX`, `_NO_ACCION_RX`,
      `es_memoria_explicita`, `_META_QUEJA_RX`, `route(`). Si aparece un atajo y no
      se declara ahí, esa prueba vuelve a mirar un escalón por debajo — que es
      exactamente cómo se coló el de «apunta». — *Cubre*: enrutado-aprendido, req.
      «`quien_atiende()` declara el atajo nuevo»
- [x] B4.4 **Comprobar, no rehacer**: `test_regresion_conversacion.py` **ya aísla**
      `NEXUS_DATA_DIR` (línea 37, commit `247d517`); el diseño lo daba como
      pendiente. Añadir una comprobación que afirme que el aislamiento sigue ahí,
      para que quitarlo ponga la suite en rojo. — *Test*:
      `test_aprendizaje_no_robo.py::test_las_suites_de_enrutado_aislan_data_dir`
      **Cómo probar que puede fallar**: quita la línea 37 y ejecuta; rojo. Devuélvela.
- [x] B4.5 **Divergencia declarada y escrita en la propia suite**: el barrido no
      modela `_learn_lookup()` ni `rag.find_task()` (`brain.py:1036-1049`), así que
      una frase puede cambiar de destino por ahí sin que la puerta 4 lo vea. Es
      literalmente «una prueba que mira un escalón por debajo». Se deja fuera —
      `find_task` es asíncrona y llama a embeddings, y `quien_atiende` tiene que
      seguir siendo síncrona y sin red— y se documenta en el docstring de
      `test_aprendizaje_no_robo.py`, no en un fichero aparte que nadie abra. —
      *Cubre*: design, «Preguntas abiertas» (riesgo residual, confirmado aquí)
- [x] B4.6 **RED — datos personales**:
      `test_aprendizaje_puertas.py::test_ficheros_nuevos_sin_datos_personales` —
      extiende la guarda de `test_skill_domotica.py:372` («adri», «maqueda»,
      «achoz», IPs completas, MACs) a `reglas.py`, `aprendizaje.py`,
      `corpus_regresion.json` y las suites nuevas. — *Cubre*: aprendizaje-contrato,
      req. «Nada personal viaja en el instalador»

### B5. Suites de B y alta en `run_all.py`

- [x] B5.1 Crear `tests/test_reglas_contrato.py`, `tests/test_aprendizaje_puertas.py`
      y `tests/test_aprendizaje_no_robo.py`, las tres con `NEXUS_DATA_DIR` a carpeta
      temporal.
- [x] B5.2 Añadir las tres a la tupla de suites de `tests/run_all.py`. — *Cubre*:
      enrutado-aprendido, escenario «Suites nuevas registradas»
- [x] B5.3 `.venv\Scripts\python.exe tests\run_all.py` → `RESULTADO GLOBAL: TODO
      VERDE`. **Sin reinicio**: B no toca ninguna skill y nada cambia en marcha.

---

## Bloque C — Propuesta, tanda y consulta (el único que cambia el comportamiento)

Se revisa con B ya verde. Aquí nexus empieza a proponer, y aquí es donde se puede
hacer daño.

### C1. Observar la corrección y distinguir el hueco del fallo

- [x] C1.1 `aprendizaje.observa(correccion, antecedente, canal) -> propuesta | aviso | {}`.
      Juzga el **antecedente** —el turno anterior del operador, de `brain._history`
      y `data/interactions.jsonl` como respaldo— con `quien_atiende()`, no la queja.
      — *Cubre*: aprendizaje-correcciones, req. «Distinguir un hueco de enrutado de
      un fallo de código»
- [x] C1.2 **RED — no tapar un fallo de código**:
      `test_aprendizaje_ciclo.py::test_antecedente_que_llega_a_una_skill_no_propone_nada`
      — antecedente que devuelve `skill:X/Y` → **cero propuestas** y un registro
      `tipo: "aviso"`. Decisión 3 del dueño. — *Cubre*: aprendizaje-correcciones,
      escenario «La frase llega a la skill correcta y la skill se comporta mal»
      **Cómo probar que puede fallar**: haz que `observa()` devuelva una propuesta
      siempre; el test tiene que dar rojo por las dos afirmaciones (cero propuestas
      **y** aviso presente), no por una.
- [x] C1.3 **RED — atajo previo**:
      `test_aprendizaje_ciclo.py::test_antecedente_capturado_por_un_atajo_no_propone`
      — antecedente que devuelve `memoria`, `charla` o `queja` → aviso, no propuesta.
      Es la clase del fallo de «apunta la mentoría el jueves», y este mecanismo
      **no lo arregla**: que quede escrito en el mensaje del aviso. — *Cubre*:
      aprendizaje-correcciones, escenario «Un atajo previo se queda la frase»
- [x] C1.4 **GREEN** implementar la tabla de veredictos de C1.2/C1.3 en `observa()`.
- [x] C1.5 Umbral de evidencia: `origen.tipo = "ordenada"` (casó `brain._TEACH_RX`)
      entra con `veces >= 1`; `"observada"` espera `aprendizaje.umbral_observada`
      ocurrencias **distintas**, contadas por `(día, frase normalizada)` para que
      repetir la misma queja tres veces de rabia no cuente como tres pruebas. —
      *Cubre*: aprendizaje-correcciones, req. «La evidencia depende de quién lo
      diga»; aprendizaje-aprobacion, req. «La lista no se llena de ruido» — *Test*:
      `test_aprendizaje_ciclo.py::test_misma_queja_repetida_cuenta_una_vez`
- [x] C1.6 **RED — nunca proponer escribir una skill**:
      `test_aprendizaje_ciclo.py::test_capacidad_inexistente_no_genera_propuesta` —
      corrección que pide algo que ninguna skill declara → sin propuesta, y la
      respuesta dice que eso necesita una skill nueva, que nexus no escribe. —
      *Cubre*: aprendizaje-correcciones, req. «Nunca proponer escribir una skill»
- [x] C1.7 `dominio/selflearn.py` expone la **generalización de patrón** para el
      proponente. El LLM solo puede **ensanchar** el patrón; su salida es entrada de
      las puertas, nunca un veredicto. Modelo apagado o generalización que falla la
      puerta 3 o la 4 → se cae al patrón literal anclado. El aprendizaje degrada, no
      desaparece. — *Cubre*: aprendizaje-correcciones, req. «El perfil del operador
      propone, no decide» — *Test*: `test_aprendizaje_ciclo.py::test_sin_modelo_cae_al_patron_literal`

### C2. La tanda, con `confirm` sin tocarlo

- [ ] C2.1 `pendientes()` devuelve, por propuesta: frase literal de `origen`, frase
      que se enrutaba mal, tipo, destino, evidencia (`ordenada`/`observada` y
      `veces`), resultado de las puertas **y la lista exacta de frases del corpus
      que pasarían de `planificador` a esa skill**. Los `aviso` van en epígrafe
      aparte, «fallos, no aprendizajes». — *Cubre*: aprendizaje-aprobacion, req.
      «"qué has aprendido" enseña la tanda completa»
- [ ] C2.2 `aprobar_tanda(canal)` vía `comun/confirm.request()` **sin modificar
      `confirm.py`**: TTL de 5 minutos, sí/no corto, estado por canal, auditoría. La
      tanda se aprueba o se descarta **entera**; para aprobar un subconjunto, el
      operador descarta antes las que no quiere («descarta la 2»), que es una
      mutación que nunca activa nada. — *Cubre*: aprendizaje-aprobacion, req.
      «Aprobación y descarte por tandas» — *Test*:
      `test_aprendizaje_ciclo.py::test_si_por_otro_canal_no_activa_la_tanda`,
      `::test_confirmacion_caducada_no_activa_nada`
- [ ] C2.3 Al aprobar se **re-ejecutan las puertas 1-4** (el corpus pudo cambiar
      entre proponer y aprobar) → `propuesta → activa`, `revision += 1`. — *Cubre*:
      aprendizaje-validacion, req. «Revalidación en la activación» — *Test*:
      `test_aprendizaje_ciclo.py::test_skill_desaparecida_entre_proponer_y_aprobar`
- [ ] C2.4 `descartar(rid)`, `olvidar(consulta)` y `de_fabrica()`. El interruptor de
      fábrica pasa por `confirm` propio y deja la auditoría intacta. Nada se borra
      nunca. — *Cubre*: aprendizaje-aprobacion, req. «Deshacer conversacional» e
      «Interruptor de fábrica» — *Test*: `test_aprendizaje_ciclo.py::test_olvidar_devuelve_planificador_sin_reiniciar`
- [ ] C2.5 Cada mutación —proponer, aprobar, descartar, activar, revertir, vaciar—
      deja su línea en `comun/audit.py` con la frase de origen. — *Cubre*:
      aprendizaje-aprobacion, req. «Auditoría obligatoria de todo el ciclo» —
      *Test*: `test_aprendizaje_ciclo.py::test_traza_completa_de_una_regla`
      **Cómo probar que puede fallar**: el test lee `audit.log` y exige las cuatro
      acciones **en orden**. Quita una llamada a `audit.log()`: rojo.

### C3. El escalón en `process` y la skill de conversación

- [ ] C3.1 `aprendizaje.aplica(texto, ya_enrutado)`: **si `ya_enrutado is not None`
      devuelve el mismo objeto, intacto**. El robo no se rechaza: es inalcanzable. —
      *Cubre*: enrutado-aprendido, req. «Invariante de posición» — *Test*:
      `test_aprendizaje_ciclo.py::test_aplica_devuelve_el_mismo_objeto` — la
      comprobación es **identidad (`is`), no igualdad**.
- [ ] C3.2 Escalón en `brain.process`, dentro de la rama `routed is None`
      (`brain.py:1036-1051`), **después** de `_learn_lookup()`/`rag.find_task()` y
      **antes** de `llm.plan_action()` (`brain.py:1055`). — *Cubre*:
      enrutado-aprendido, req. «El planificador sigue siendo el respaldo»
- [ ] C3.3 `brain` registra su árbitro al final del módulo:
      `aprendizaje.registrar_arbitro(quien_atiende)`. `aprendizaje` **no importa
      `brain`**. — *Verificación*: `.venv\Scripts\python.exe tests\test_capas_backend.py`
      en 0 y `EXCEPCIONES` sin entradas nuevas.
- [ ] C3.4 Orden determinista entre reglas activas: gana la de **activación más
      reciente**, sin depender del orden de lectura del fichero ni del diccionario.
      — *Cubre*: enrutado-aprendido, req. «Orden determinista entre reglas activas» —
      *Test*: `test_aprendizaje_ciclo.py::test_dos_barridos_en_procesos_distintos_coinciden`
      **Cómo probar que puede fallar**: el test lanza el barrido en **dos procesos
      distintos** (`subprocess`) y compara. Dentro del mismo proceso el orden del
      diccionario es estable y el test no vería nada.
- [ ] C3.5 Crear `skills/aprendizaje/` (`SKILL.md` + `skill.py`), **solo
      conversación**. Cae entre `ai_media` y `autoprovision`, casi la primera que
      consulta el router, que es primera-que-case. Cuatro patrones **anclados en
      `^`** y largos. — *Cubre*: aprendizaje-aprobacion, req. «"qué has aprendido"
      enseña la tanda completa» **⚠ Reinicio**: `skills_loader` solo lee carpetas al
      arrancar.
- [ ] C3.6 **RED — la skill nueva no le quita nada a nadie**:
      `test_aprendizaje_ciclo.py::test_skill_aprendizaje_no_roba_ninguna_frase` —
      barrido de `quien_atiende()` sobre las 255 frases **sin** y **con**
      `skills/aprendizaje/` cargada: idéntico frase a frase. Y el solape con
      `brain._FORGET_RX` (`brain.py:528`), que corre antes del router y solo dispara
      si la frase estaba en `command_learning.json`: «olvida lo que aprendiste sobre
      las teles» tiene que llegar a la skill nueva. **Se comprueba, no se supone.**
      — *Cubre*: enrutado-aprendido, req. «Invariante de posición»
- [ ] C3.7 **RED — ningún `.py` es escrito por nexus**:
      `test_aprendizaje_ciclo.py::test_ningun_py_cambia_de_mtime` — `mtime` de
      **todos** los `.py` del proyecto antes y después de un ciclo completo
      (observar → proponer → aprobar → activar → revertir). — *Cubre*:
      aprendizaje-contrato, req. «nexus escribe datos, nunca código»
      **Cómo probar que puede fallar**: mete un `Path("backend/core/dominio/reglas.py").touch()`
      dentro de `aprobar_tanda()`; rojo. Quítalo.
- [ ] C3.8 **RED — nada se escribe fuera de `DATA_DIR`**:
      `test_aprendizaje_ciclo.py::test_no_escribe_fuera_de_data_dir` — con
      `NEXUS_DATA_DIR` en carpeta temporal, tras el ciclo completo el único fichero
      nuevo es `reglas_aprendidas.json` (+ `.bak`), comprobado con `Path.resolve()`.
      — *Cubre*: matriz de amenazas, «Dato personal en `origen.frase`»
- [ ] C3.9 Caducidad de propuestas a `dias_caducidad_propuesta`. Las **activas no se
      podan**: un tope sería un borrado automático, y aquí no hay ninguno. —
      *Cubre*: matriz de amenazas, «Crecimiento sin límite» — *Test*:
      `test_aprendizaje_ciclo.py::test_propuestas_caducan_y_las_activas_no`

### C4. Suites de C, alta en `run_all.py` y aceptación real

- [ ] C4.1 Crear `tests/test_aprendizaje_ciclo.py` con todos los casos de C1-C3.
- [ ] C4.2 Añadir `"test_aprendizaje_ciclo.py"` a la tupla de suites de
      `tests/run_all.py`.
- [ ] C4.3 **⚠ Reinicio + aceptación contra nexus en marcha**: reproducir tres de
      los once fallos del 03/08 —«cierra chrome», «dame ideas», «busca información
      sobre python» o los equivalentes que hoy caigan al planificador—, corregir a
      nexus, pedir «qué has aprendido», aprobar, y comprobar que la frase pasa a
      `regla:<id>` **sin haber editado una línea de `skill.py`**. — *Cubre*:
      `proposal.md`, criterio de éxito «Al menos tres de los once fallos se resuelven
      aprendiendo»
- [ ] C4.4 **Reversión real, ejecutada**: anotar `quien_atiende()` sobre las 255
      frases con el almacén vacío, activar reglas, borrar
      `data/reglas_aprendidas.json`, reiniciar, y comprobar que la salida es
      **idéntica** a la anotada. — *Cubre*: aprendizaje-contrato, escenario «Borrar
      el almacén devuelve el comportamiento de fábrica»
- [ ] C4.5 `.venv\Scripts\python.exe tests\run_all.py` → `RESULTADO GLOBAL: TODO
      VERDE` y `tests\e2e\run_e2e.py` → 9/9 con nexus en marcha y
      `PYTHONIOENCODING=utf-8`.

---

## Regla transversal para los tres bloques

`.venv\Scripts\python.exe tests\run_all.py` sale **TODO VERDE** al cierre de cada
bloque, con las suites nuevas de ese bloque ya dadas de alta en la tupla de
`run_all.py` — una suite sin registrar no se ejecuta nunca. Los bloques A y C
exigen además **reinicio** (`cmd /c start "" run.bat`) y su barrido a mano contra
nexus en marcha antes de darse por cerrados: `skills_loader` solo lee las carpetas
al arrancar, y un verde de la suite no prueba ni el sondeo de puertos ni el ciclo
conversacional. No se toca `config/settings.json` ni `config/secrets.json` en
ningún bloque; todo umbral nuevo va a `config/umbrales.json` y toda reserva a la
tabla `VALORES` de `backend/core/dominio/reglas.py`.

## Lo que este plan NO deja verificable por ejecución

Una sola cosa, y va declarada en vez de disimulada: **la puerta 5 (suite) en la
máquina de un usuario**. Allí no hay `tests/`, así que no se ejecuta y no se puede
ejecutar. Lo que sí se verifica ejecutando es que **nunca se marca como superada**
(B3.7): en esa instalación activan cuatro puertas, no cinco, y la auditoría lo
dice con esas palabras. La puerta de no robo es la única red que va a tener el
usuario, y por eso B2.5 exige que sin catálogo **ninguna** regla se active.
