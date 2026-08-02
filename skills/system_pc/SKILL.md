# 🖥 Skill: Sistema / PC

Minion de control del equipo local. Lee CPU/RAM/GPU/disco y temperaturas reales
(psutil + nvidia-smi + LibreHardwareMonitor por WMI en Windows), gestiona procesos,
abre aplicaciones instaladas (índice del Menú Inicio/registro/Store con verificación
real de arranque), juegos de Steam ya instalados, webs (con URL razonada por el
modelo y memorizada en `data/web_urls.json`), hace capturas y fotos de webcam, y
apaga o reinicia el PC SIEMPRE con confirmación previa.

## Órdenes de ejemplo (todas cazadas por los patterns)

- «estado del sistema» / «cómo anda mi pc» / «uso de la cpu» / «cuánta ram queda»
- «qué temperatura tiene la cpu» / «cómo van las temperaturas» / «está muy caliente la gpu»
- «lista los procesos» / «lístame los procesos» / «qué procesos hay» /
  «qué se está comiendo la ram»
- **Cerrar cualquier programa, con o sin ancla**: «cierra chrome» / «ciérrame
  spotify» / «cierra el navegador» / «termina discord» / «mata spotify», y también
  las formas largas «cierra el proceso chrome» / «cierra el programa spotify» /
  «termina discord.exe». **Lo cierra en el acto**, sin preguntar, y contesta con
  una línea que varía («Chrome cerrado», «Listo, Chrome fuera», …)
- «abre spotify» / «ábreme la calculadora» / «arranca el bloc de notas»
- **Abrir cualquier web**, no hay lista de sitios: «abre la web de marca» /
  «ábreme la página de renfe» / «ponme la web del as» / «entra en la web de X» /
  «abre marca.com» / «métete en elmundo.es» / «abre https://…»
- «abre youtube y busca lofi»
- «pon el volumen al 40» / «volumen al 75%»
- «haz una captura de pantalla» / «hazme un pantallazo»
- «haz una foto con la webcam» / «sácame una foto»
- «guarda la mac aa:bb:cc:dd:ee:ff» → deja la MAC en ajustes para Wake-on-LAN
- «apaga el pc» / «reinicia el ordenador» → arman la acción y **no ejecutan nada**
  hasta un «sí» (o la frase exacta «confirmo apagado» / «confirmo reinicio»)

## Fronteras (para no pisar a otras skills)

- «¿qué temperatura hace en Madrid?» → clima. Aquí solo temperaturas de hardware.
- «sube el volumen» a secas → domotica lo manda a la tele; aquí el volumen del PC con número.
- «abre el tablero», «abre el correo 2», «abre X en chrome» → tasks_board,
  google_workspace y navegador. El lookahead de `open_app` los deja pasar.
- **«enciende el pc» / «despierta el ordenador» → domotica**, que va antes por orden
  alfabético y ya hace el Wake-on-LAN. Lo que sí sirve de aquí es «guarda la mac …»:
  escribe `wol_mac` en ajustes, que es justo lo que domotica lee. El intent `wake`
  de esta skill solo queda alcanzable por la frase literal «wake on lan».
- **«instala X en steam» → games**, que va antes y tiene el catálogo real.
  Aquí solo se LANZAN juegos ya instalados, desde «abre <juego>».
- **«lanza discord» → la skill discord**, que va antes por alfabeto.
- **«cierra X» a secas SÍ es de aquí**, porque es como se dice de verdad. La
  acotación no la pone un ancla, la pone una lista de exclusión (`_NO_ES_PROGRAMA`)
  con lo que es de otros: la pestaña es de `chrome`, el tablero y las tareas de
  `tasks_board`, la persiana y la tele de `domotica`, los correos de
  `google_workspace`. Y con lo que no es un programa: la sesión, la ventana, el
  trato, el tema, la boca. **Skill nueva que reclame «cierra <sustantivo>»: hay
  que añadir ese sustantivo a la lista**, o system_pc se lo queda —va antes que
  `tasks_board`, `telefono`, `tools` y `vigilancias` por orden alfabético.
- Los nombres coloquiales se traducen al ejecutable con `_ALIAS_PROCESO`:
  «el navegador» → `chrome`, «la calculadora» → `calc`, «las notas» → `notepad`.

## Seguridad

- **Apagar y reiniciar pasan por `backend/core/confirm.py`.** El handler arma la
  acción y devuelve la pregunta con lo que se va a llevar por delante (cuántos
  programas hay abiertos). El brain resuelve el «sí»/«no» antes que ningún router;
  si el operador contesta otra cosa la confirmación se descarta, y caduca a los
  5 minutos. Todo queda en `data/logs/audit.jsonl`.
- **Cerrar programas NO pide confirmación, y es deliberado**: «cierra X» es una
  orden directa y se ejecuta como tal. La salvaguarda es la puntería, no la
  pregunta: primero se busca el nombre exacto (con o sin `.exe`) y solo si no casa
  ninguno se cae a la coincidencia por subcadena, para que «cierra el proceso code»
  no se lleve por delante a `codecs_host`. Si no hay nada abierto con ese nombre,
  lo dice y no toca nada.
- El apagado y el reinicio se lanzan con 15 s de margen (`shutdown /s|/r /t 15`),
  cancelables desde una consola con `shutdown /a`.

## Lo que NO hace

- No inventa cifras: sin `psutil` **no** da un informe de ejemplo, dice qué falta.
- No afirma haber abierto una app sin comprobarlo: compara la lista de procesos
  antes y después y distingue «arrancó», «arrancó otra cosa» y «no arrancó».
- No abre juegos de Steam que no estén instalados; lo dice y ofrece instalarlos.
- No borra archivos (eso es `files`) ni toca dispositivos de casa (eso es `domotica`).

## Notas técnicas

- Dependencias opcionales: `psutil` (hardware/procesos y verificación de arranque),
  `mss` (capturas), `opencv-python` (webcam), `nircmd` en el PATH (volumen real en
  Windows), `wmi` + LibreHardwareMonitor abierto (temperatura de CPU en Windows),
  `nvidia-smi` (GPU NVIDIA). Sin ellas, responde explicando qué instalar.
- El informe de hardware pasa por `backend.core.permissions` (se puede denegar en ⚙).
- Capturas y fotos quedan en `data/captures/` con marca de fecha y hora.
