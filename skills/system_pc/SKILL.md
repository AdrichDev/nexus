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
- «cierra el proceso chrome» / «ciérrame el proceso chrome» / «mata spotify» /
  «termina discord.exe» / «cierra el programa spotify» → previsualiza qué procesos
  casan (nombre y PID) y **pide confirmación** antes de terminarlos
- «abre spotify» / «ábreme la calculadora» / «arranca el bloc de notas»
- «abre la web de marca» / «ábreme la página de renfe»
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
- Cerrar procesos exige ancla: la palabra «proceso», un «.exe», «la app/el programa X»
  o el verbo «mata». Un «cierra X» a secas no dispara nada aquí.

## Seguridad

- **Apagar, reiniciar y matar procesos pasan por `backend/core/confirm.py`.** El
  handler arma la acción y devuelve la pregunta con lo que se va a llevar por
  delante (cuántos programas hay abiertos; qué procesos casan, con su PID). El
  brain resuelve el «sí»/«no» antes que ningún router; si el operador contesta
  otra cosa la confirmación se descarta, y caduca a los 5 minutos. Todo queda en
  `data/logs/audit.jsonl`.
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
