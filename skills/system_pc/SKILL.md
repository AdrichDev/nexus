# 🖥 Skill: Sistema / PC

Minion de control del equipo local. Lee CPU/RAM/GPU/disco y temperaturas reales
(psutil + nvidia-smi + LibreHardwareMonitor por WMI en Windows), gestiona procesos,
abre aplicaciones instaladas (índice del Menú Inicio/registro/Store con verificación
real de arranque), juegos de Steam instalados, webs (con URL razonada por el modelo
y memorizada en `data/web_urls.json`), hace capturas y fotos de webcam, enciende
otro equipo por Wake-on-LAN y apaga el PC SIEMPRE en dos pasos.

## Órdenes de ejemplo (todas cazadas por los patterns)

- «estado del sistema» / «cómo anda mi pc» / «uso de la cpu» / «cuánta ram queda»
- «qué temperatura tiene la cpu» / «cómo van las temperaturas» / «está muy caliente la gpu»
- «lista los procesos» / «qué procesos hay» / «qué se está comiendo la ram»
- «cierra el proceso chrome» / «mata spotify» / «termina discord.exe»
- «abre spotify» / «lanza discord» / «arranca la calculadora»
- «abre la web de marca» / «ábreme la página de renfe»
- «abre youtube y busca lofi» / «instala rust en steam»
- «pon el volumen al 40» / «volumen al 75%»
- «haz una captura de pantalla» / «hazme un pantallazo»
- «haz una foto con la webcam» / «sácame una foto»
- «guarda la mac aa:bb:cc:dd:ee:ff» → luego «enciende el ordenador» (Wake-on-LAN)
- «apaga el pc» → arma el protocolo; SOLO se ejecuta al decir «confirmo apagado»

## Fronteras (para no pisar a otras skills)

- «¿qué temperatura hace en Madrid?» → clima. Aquí solo temperaturas de hardware.
- «sube el volumen» a secas → domotica lo manda a la tele; aquí el volumen del PC con número.
- «abre el tablero», «abre el correo 2», «abre X en chrome» → tasks_board,
  google_workspace y navegador. El lookahead de `open_app` los deja pasar.
- Cerrar procesos exige ancla: la palabra «proceso», un «.exe», «la app/el programa X»
  o el verbo «mata». Un «cierra X» a secas no dispara nada aquí.

## Notas técnicas

- Dependencias opcionales: `psutil` (hardware/procesos y verificación de arranque),
  `mss` (capturas), `opencv-python` (webcam), `nircmd` en el PATH (volumen real en
  Windows), `wmi` + LibreHardwareMonitor abierto (temperatura de CPU en Windows),
  `nvidia-smi` (GPU NVIDIA). Sin ellas, responde explicando qué instalar.
- El informe de hardware pasa por `backend.core.permissions` (se puede denegar en ⚙).
- Wake-on-LAN: guarda la MAC con «guarda la mac …» (settings `wol_mac`,
  broadcast opcional en `wol_broadcast`) y activa WoL en la BIOS y el adaptador.
- SEGURIDAD del apagado: doble confirmación obligatoria. «apaga el pc» solo arma
  el protocolo 60 s; el `shutdown /s /t 15` únicamente se lanza tras la frase
  EXACTA «confirmo apagado» (cancelable con `shutdown /a`).
- Capturas y fotos quedan en `data/captures/` con marca de fecha y hora.
