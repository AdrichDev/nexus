# 🏠 Skill: Casa / Domótica (red local + Home Assistant)

Rastrea la red local como el «buscar dispositivos» del Bluetooth y controla lo que
encuentra: TVs por su nombre real, PCs por Wake-on-LAN y la domótica (luces,
enchufes, persianas, termostatos…) a través de Home Assistant. Sin instalar nada
extra: usa estándares (ARP, SSDP/UPnP, mDNS, NetBIOS, Roku ECP, Samsung Tizen, WoL).

## Qué hace y con qué frases se dispara

- **`descubrir` — rastrear la red**: «escanea la red», «escanéame la red», «rastrea
  la red local», «qué dispositivos hay conectados», «cuántos aparatos hay en el
  wifi», «quién está conectado al wifi», «mira qué aparatos hay». Barrido ACTIVO de
  la subred: despierta cada IP, lee su MAC, deduce el fabricante por el OUI, pregunta
  por mDNS/Bonjour y SSDP/UPnP el nombre y el tipo, hace DNS inverso, NetBIOS y
  sondeo de puertos. Lista cada aparato con IP, nombre, tipo, fabricante y MAC —
  **todo leído de la red en ese momento, nada de listas de ejemplo**.
- **`tv_on` / `tv_off`**: «enciende la tele», «ponme la televisión», «enciéndeme la
  tv», «apaga el televisor», «apágame la tele», «quita la tele».
- **`tv_mute`**: «silencia la tele», «quita el sonido de la tele», «pon la tele en
  silencio», «quítale el volumen a la tv».
- **`tv_volume`**: «sube el volumen de la tele», «bájale el volumen a la tv», «más
  volumen en la televisión». **Exige nombrar la tele**, igual que `tv_mute`: el
  destino lo dice siempre quien da la orden. El volumen sin tele no es de aquí — lo
  recoge `system_pc`, que pregunta a qué aparato en vez de adivinar. Si la orden
  nombra otro destino («sube el volumen de Spotify», «…del PC») la atienden
  `media` / `system_pc`.
- **`tv_channel`**: «pon el canal 5», «pon el canal cinco», «cámbiame al canal 3»,
  «canal siguiente», «canal anterior».
- **`tv_app`**: «pon Netflix en la tele», «quiero ver YouTube en la tv». Apps
  directas solo en Roku (ver límites).
- **`wol`**: «enciende el pc», «arranca el servidor», «despierta el ordenador»,
  «levanta la torre». Necesita la MAC guardada.
- **`casa` (Home Assistant)**: «enciende la luz del salón», «apaga el enchufe de la
  cocina», «sube la persiana del dormitorio», «pon la calefacción», «cierra el toldo
  de la terraza», «quita la luz del pasillo». Se busca la entidad por su nombre
  amigable y se acciona.
- **Por NOMBRE propio**: si la frase ya entra por un intent de arriba y además nombra
  un aparato tuyo (⚙ → dispositivos conocidos), se controla ESE aparato aunque su
  nombre lleve una palabra de estancia. «Enciende la TV del estudio» actúa sobre esa
  TV, no sobre las luces del estudio en Home Assistant. **Límite**: el nombre por sí
  solo no dispara la skill — «enciende estudio» no la activa; hace falta la palabra
  «tele/tv» o una estancia/aparato de la lista de `casa`.

## Qué necesita configurado

- **Nada** para `descubrir`: el escaneo funciona en seco.
- **Home Assistant** para `casa`: en HA, tu perfil → *Tokens de acceso de larga
  duración* → crea uno. En ⚙ → sección **CASA**, pega la **URL** (p. ej.
  `http://homeassistant.local:8123`) y el **token**. El asistente por pasos del HUD
  valida ambos en vivo (`POST /api/home/ha_test`) antes de guardarlos.
  Dominios controlables: `light`, `switch`, `fan`, `cover`, `climate`,
  `media_player`, `input_boolean`, `scene` y `script`.
- **TVs a mano** (opcional): en ⚙ → CASA, lista de dispositivos conocidos, uno por
  línea, con el formato `Nombre | IP | MAC | marca(samsung/roku/lg)`. La MAC permite
  encenderla por WoL incluso apagada. El nombre que tú pongas manda sobre el que
  difunde el aparato.
- **Wake-on-LAN** para `wol`: la MAC del equipo en ⚙ (*MAC del PC / Wake-on-LAN*) o
  el equipo en la lista de dispositivos conocidos con su MAC.
- Los secretos (`homeassistant_token`, tokens de TV) van a `config/secrets.json`, que
  gestiona ⚙; no se editan a mano.

## Qué NO hace

- **No inventa dispositivos ni estados**: si la red no contesta, lo dice; no rellena
  con ejemplos. Si falta HA, la URL o el token, dice cuál falta y dónde ponerlo.
- **No apaga ni reinicia este PC** (eso es `system_pc`) ni controla el volumen de
  aplicaciones (eso es `media` / `system_pc`).
- **No abre apps en TVs Samsung/LG/Sony** directamente: solo en Roku. Para el resto,
  vía Home Assistant.
- **No lee ni escribe en la nube de ningún fabricante**: todo es LAN, contra el
  propio aparato o contra tu Home Assistant.

## Notas técnicas / límites

- **Roku / TCL / Hisense (Roku TV)**: control por HTTP (ECP), sin emparejar. Lo mejor
  soportado, incluidas apps directas (Netflix, YouTube, Prime, Disney+, HBO…).
- **Samsung (Tizen, 2016+)**: la primera orden hace que la TV pida permiso en
  pantalla; acéptalo y el token queda guardado POR TV (dos Samsung no se pisan).
  Enciende (WoL), apaga, volumen y canales.
- **LG / Sony / otras**: a través de Home Assistant.
- El encendido en frío usa una ráfaga WoL (broadcast global + subred + unicast a su
  IP): el aparato debe tener activado el «encendido por red» (WoL/WoWLAN) y no colgar
  de una regleta apagada.
- El fabricante deducido de la MAC es una **pista** (tabla OUI incorporada), no un
  dato certificado: una MAC desconocida sale sin fabricante, nunca con uno inventado.
- Si la red bloquea el multicast (redes de invitados, algunas de empresa), el
  descubrimiento UPnP/mDNS puede venir vacío: usa la lista de dispositivos conocidos
  de ⚙ o Home Assistant.
