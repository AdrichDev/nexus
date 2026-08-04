# Propuesta: distribución y actualizaciones

## El problema, en los términos del dueño

Esto sale en un `.exe` para otra gente. Y lo que hoy sale no se puede mantener.

El empaquetado existe y funciona: `build_exe.bat` construye `dist\nexus.exe` con
PyInstaller (`nexus.spec`) y `build_installer.bat` genera `nexus-Setup.exe` con
NSIS (`nexus_installer.nsi`). La higiene está pensada: el `.spec` no empaqueta
`data/`, el `.bat` borra `settings.json`, `secrets.json` y `.env` de `dist\`, y
el NSIS los vuelve a excluir con `/x` (línea 66). Memoria virgen garantizada.

Lo que no hay es **nada más**. Ninguna versión: el registro solo guarda
`InstallDir`. Ninguna firma: `build_installer.bat` llama a `makensis` y termina.
Ni canal, ni comprobación, ni vuelta atrás. Y hay dos cosas que ya son un
problema hoy:

1. **Desinstalar borra la memoria del usuario.** `nexus_installer.nsi:103` hace
   `RMDir /r "$INSTDIR"`, y `data/` vive dentro de `$INSTDIR`. Todo lo que ese
   nexus aprendió de su dueño se va sin preguntar.

   **Decisión del dueño (03/08/2026)**: al desinstalar se **pregunta** si borrar
   también los datos o conservarlos, como hace cualquier programa serio. No se
   elige por él en ninguna de las dos direcciones: ni arrasar sin avisar, ni
   dejar carpetas huérfanas en un equipo del que se quiso ir. Y lo que se
   conserve tiene que ser encontrable si reinstala — datos que sobreviven pero
   que nadie vuelve a leer son basura con otro nombre.
2. **La superficie de actualización ya está abierta, y es código.**
   `build_exe.bat` copia `knowledge/`, `frontend/` y `skills/` **al lado** del
   exe y lo llama, literalmente, «recursos ACTUALIZABLES sin recompilar»
   (línea 19). Y `config.py:_prefer_external()` hace que esas carpetas **ganen**
   a las del bundle. Dejar un `skills/*.py` distinto junto al exe cambia el
   comportamiento en el siguiente arranque: es ejecución de código remoto por
   diseño en cuanto alguien lo automatice.

Y la guarda de datos personales es más pequeña de lo que parece:
`tests/test_skill_domotica.py:372` solo mira `skills/domotica/skill.py` y su
`SKILL.md`. **Hoy hay un nombre propio de una persona en un `echo` de
`installer/build_installer.bat` y ninguna prueba lo ve.**

## Alcance

### Dentro

| Entrega | Qué es |
| --- | --- |
| **Elección obligatoria Docker o VPS** | Sin elegir no se sigue; con Docker se avisa en claro de qué se pierde |
| **Versión y manifiesto** | Una versión de verdad, en el registro y visible desde el HUD |
| **Canal firmado** | Manifiesto + `sha256` por artefacto + firma contra una clave **dentro** del exe |
| **Aplicar y volver atrás** | Preparar aparte, verificar, cambiar, arrancar; si no responde, revertir solo |
| **Lo del usuario, intocable** | `data/`, `settings.json` y `secrets.json` fuera del canal, en ambos sentidos; y desinstalar deja de arrasar `data/` |
| **Guarda de datos personales ampliada** | De `domotica` a todo lo que se empaqueta |

### Fuera

- Montar el VPS: máquina, proveedor y coste. Aquí se define el **contrato**.
- Actualización silenciosa; actualizar el Docker, Postgres, n8n u Ollama del
  usuario; multiusuario, cuentas y telemetría (ninguno cabe con 004).

## Capacidades

### Nuevas

- `distribucion-instalador`: la elección obligatoria, sus avisos y qué se empaqueta
- `distribucion-version`: qué es una versión, dónde se escribe, cómo se compara
- `distribucion-canal`: manifiesto, firma, verificación y qué se permite enviar
- `distribucion-aplicacion`: aplicar, arrancar, comprobar y revertir
- `distribucion-recuperacion`: cómo sale un usuario de una instalación rota

### Modificadas

Ninguna. Ninguna spec de `openspec/specs/` habla de empaquetado.

## Enfoque

**Este es el cambio de más riesgo del corte, y conviene decirlo sin adornos: un
servidor del dueño empujando ficheros ejecutables a ordenadores de terceros.** Si
el canal se equivoca, se equivoca en máquinas que no controlamos, sin repositorio
y sin suite para recuperarse. Todo lo de abajo existe para estrechar eso.

**Se envía un paquete entero, firmado y versionado. Nunca ficheros sueltos.**
Dejar caer un `skill.py` en una instalación en marcha es la vía rápida a un nexus
mitad viejo mitad nuevo, y `skills_loader` solo lee las carpetas al arrancar, así
que ni se notaría hasta el siguiente reinicio. El paquete trae manifiesto,
`sha256` por artefacto y firma. La clave pública viaja **dentro** del exe, no al
lado: al lado se sustituye igual que todo lo demás. El precedente de verificación
ya está escrito en casa: `engram_bridge._sha256_ok()` compara el hash del binario
descargado contra el `checksums.txt` del release antes de ejecutarlo.

**Aplicar es preparar aparte y cambiar de golpe.** Se descarga a una carpeta de
preparación, se verifica, se para, se cambian `skills/` y `frontend/` guardando
las anteriores, se arranca y **se comprueba que responde en 8177**. Si no
responde, vuelve solo a la versión anterior y lo cuenta. Sin esa comprobación,
una actualización mala deja a un usuario con un icono que no abre nada.

**Lo aprendido es local y es suyo, y jamás se sube.** Heredado de 004 y no
negociable. El canal es de un solo sentido: baja mejoras generales, no sube nada.
Ni reglas aprendidas, ni memoria, ni métricas, ni «para mejorar el producto».

**Cuando una actualización choca con una regla aprendida** —la pregunta que 004
dejó abierta— la respuesta es: **el código lo decide la actualización; el dato lo
decide el usuario.** Una actualización nunca modifica ni borra `data/`. Si al
cambiar el código desaparece el `skill/intent` al que apuntaba una regla
aprendida, esa regla pasa a **huérfana** —no se borra, no se reescribe— y se le
dice al usuario qué dejó de funcionar y por qué. El mecanismo ya existe: es
volver a pasar la puerta de existencia de 004 contra
`skills_loader.get_skills()` después de actualizar.

**La elección Docker o VPS va donde ya se pregunta todo lo demás.**
`frontend/setup.html` tiene un paso 4 de memoria con `local`, `docker` y
`server`, y hoy viene `local` preseleccionado. Se quita la preselección: hay que
elegir. Y con Docker se dice sin rodeos que **el equipo tiene que quedarse
encendido**, o los horarios de `005` no se cumplen y la memoria semántica no
está.

## Áreas afectadas

| Área | Impacto | Qué cambia |
| --- | --- | --- |
| `installer/nexus_installer.nsi` | Modificada | Versión en el registro; desinstalar deja de arrasar `data/` |
| `installer/build_installer.bat` | Modificada | Firma; **y fuera el nombre propio del `echo` final** |
| `installer/nexus.spec` | Modificada | Clave pública dentro del bundle; revisar qué falta (`config/umbrales.json` hoy **no** se empaqueta) |
| `frontend/setup.html` | Modificada | Paso 4 sin preselección + aviso de equipo encendido. Cuidado con `?v=NN` |
| `backend/core/` (módulo nuevo) | Nueva | Manifiesto, verificación, aplicación y reversión |
| `backend/app.py` | Modificada | Estado del canal y disparo manual de la actualización |
| `data/` | Sin cambios | Intocable por el canal, en los dos sentidos |
| `tests/` | Nueva | Guarda de datos personales ampliada + suites del canal, en `run_all.py` |

## Riesgos

| Riesgo | Probabilidad | Mitigación |
| --- | --- | --- |
| **El canal empuja código a máquinas de terceros; un VPS comprometido las toma todas** | Baja, catastrófica si pasa | Firma verificada contra clave dentro del exe; sin firma válida no se aplica nada. La clave privada no vive en el repositorio |
| **Una actualización mala deja instalaciones que no arrancan** | Media | Versión anterior guardada + comprobación de arranque + reversión automática |
| **Desinstalar destruye la memoria del usuario** | Alta, ya pasa hoy | Se arregla aquí: `data/` se pregunta, no se borra |
| **Un dato personal del dueño viaja en el instalador** | Alta, ya pasa hoy | La guarda de `test_skill_domotica.py:372` se extiende a todo lo empaquetado, `installer/*.bat` incluidos |
| **Mezcla de versión vieja y nueva a mitad de actualización** | Media | Paquete entero, cambio de golpe; `skills_loader` solo lee al arrancar, nunca en caliente |
| **El antivirus bloquea el exe sin firmar** | Alta sin firma | Firma de código; precedente del falso positivo en `engram_bridge._go_install()` |
| **Alguien mete lo aprendido en el canal «para mejorar»** | Baja | Prohibido por spec y comprobado por una suite: el canal solo baja |

## Plan de reversión

1. Desde el HUD: volver a la versión anterior, que está guardada al lado.
2. Automática: si tras actualizar no responde en 8177, revierte sola y lo dice.
3. Apagar el canal: sin comprobaciones ni descargas, la instalación sigue igual.
   **Actualizar es opcional, siempre.**
4. Reinstalar `nexus-Setup.exe` por encima conservando `data/`.
5. En desarrollo, además, `git revert` — pero el plan **no depende de git**.

## Dependencias

- **004 probado.** Enviar a máquinas de terceros un nexus que se automodifica sin
  su contrato cerrado es lo que este orden evita.
- `005` para el aviso de «el equipo tiene que estar encendido»; sin `005`, el
  aviso se queda en la memoria semántica.
- Un servidor del dueño y un certificado de firma: ambos **fuera** de este
  cambio, ambos requisito para publicar.

## Sigue abierta

- **¿Actualizar es automático con aviso, o siempre lo pide el usuario?** Con
  automático se arregla a quien nunca actualizaría; con manual, nada entra sin
  permiso. Es la decisión más cara de este cambio y es del dueño.

## Criterios de éxito

- [ ] El asistente no deja continuar sin elegir Docker o VPS, y con Docker dice
      en claro qué deja de funcionar con el equipo apagado.
- [ ] Un paquete con firma inválida o `sha256` que no cuadra **no se aplica**, y
      se dice por qué.
- [ ] Una actualización que rompe el arranque revierte sola y la instalación
      sigue usable.
- [ ] Actualizar no toca `data/`, `settings.json` ni `secrets.json`. Comprobado
      por una suite.
- [ ] El canal no sube nada. Comprobado por una suite.
- [ ] Desinstalar no borra la memoria del usuario sin preguntar.
- [ ] Ningún dato personal en nada de lo que se empaqueta, `.bat` incluidos.
- [ ] `run_all.py` verde con las suites nuevas registradas.
