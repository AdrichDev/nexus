# 🏠 Skill: Casa / Domótica (red local + Home Assistant)

Rastrea tu red local como el «buscar dispositivos» del Bluetooth y controla lo que
encuentra: TVs por su nombre real, PCs por Wake-on-LAN y toda la domótica (luces,
enchufes, persianas, termostatos…) a través de Home Assistant. Sin instalar nada
extra: usa los estándares (ARP, SSDP/UPnP, mDNS, NetBIOS, Roku ECP, Samsung Tizen, WoL).

## Órdenes de ejemplo (todas cazadas por los patterns)

- **Rastrear la red** — «escanea la red», «qué dispositivos hay conectados»,
  «cuántos aparatos hay en el wifi», «muéstrame los dispositivos de la red»,
  «rastrea la red local». Barrido ACTIVO de la subred: despierta cada IP, lee su
  MAC y deduce el fabricante (Apple, Samsung, LG, Google, Amazon, Xiaomi,
  Espressif/Tuya para enchufes y bombillas…), pregunta por mDNS/Bonjour y
  SSDP/UPnP el nombre y el tipo, hace DNS inverso, NetBIOS y sondeo de puertos.
  Lista cada aparato con IP, nombre, tipo, fabricante y MAC.
- **TV** (Samsung Tizen y Roku en directo; cualquier marca vía Home Assistant):
  - «enciende la tele», «ponme la tele», «apágame la televisión»
  - «sube el volumen», «bájale al volumen», «silencia la tele», «quita el ruido de la tele»
  - «pon el canal 5», «cámbiame al canal 3», «canal siguiente/anterior»
  - «pon Netflix en la tele», «quiero ver YouTube en la tv» (apps directas en Roku)
  - por NOMBRE propio: si tu TV se llama «Habitación Maqueda», «enciende habitación
    Maqueda» (o solo «enciende maqueda») controla ESA TV, no Home Assistant.
- **Wake-on-LAN** — «enciende el pc», «arranca el servidor», «despierta el ordenador»,
  «levanta la torre» (necesita la MAC guardada).
- **Casa vía Home Assistant** — «enciende la luz del salón», «apaga el enchufe de la
  cocina», «sube la persiana del dormitorio», «pon la calefacción», «cierra el toldo
  de la terraza». Se busca la entidad por su nombre amigable y se acciona.

## Control TOTAL de domótica → Home Assistant (recomendado)

1. En HA: tu perfil (abajo izq.) → **Tokens de acceso de larga duración** → crea uno.
2. En ⚙ → sección **CASA**: pega la **URL de HA** (ej. `http://homeassistant.local:8123`)
   y el **token**. También puedes seguir el asistente por pasos del HUD, que valida
   el token en vivo (endpoint `/api/home/ha_test`) antes de guardarlo.
3. Dominios controlables: light, switch, fan, cover, climate, media_player,
   input_boolean, scene y script.

## Configurar tus TVs a mano (opcional, para ir más fino)

En ⚙ → CASA, lista de dispositivos conocidos (uno por línea):
`Nombre | IP | MAC | marca(samsung/roku/lg)` — la MAC permite encenderla por WoL
incluso apagada. El nombre que TÚ pongas manda sobre el que difunde el aparato.

## Notas técnicas / límites

- **Roku / TCL / Hisense (Roku TV)**: control por HTTP (ECP), sin emparejar. Lo mejor
  soportado, incluidas apps directas (Netflix, YouTube, Prime, Disney+, HBO…).
- **Samsung (Tizen, 2016+)**: la primera orden hace que la TV pida permiso en pantalla;
  acéptalo y el token queda guardado POR TV (dos Samsung no se pisan). Enciende (WoL),
  apaga, volumen y canales; abrir apps directas, mejor vía Home Assistant.
- **LG / Sony / otras**: a través de Home Assistant.
- El encendido en frío usa una ráfaga WoL (broadcast global + subred + unicast a su IP):
  la TV debe tener activado el «encendido por red» (WoL/WoWLAN) y no colgar de una
  regleta apagada.
- Si tu red bloquea el multicast (redes de invitados, algunas de empresa), el
  descubrimiento UPnP/mDNS puede venir vacío: usa la lista de dispositivos conocidos
  en ⚙ o Home Assistant.
- Secretos: `homeassistant_token` y los tokens de TV van en `config/secrets.json`
  (los gestiona ⚙, no hace falta editarlo a mano).
