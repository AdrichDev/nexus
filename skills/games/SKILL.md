# Juegos / Steam (games)

nexus juega, instala, descarga y valida juegos, y abre launchers. Resuelve el
**AppID de Steam por nombre** (búsqueda en la tienda de Steam, sin API key) y
usa los esquemas `steam://` para actuar de verdad — no hace falta que sepas el ID.

## Órdenes

- **Jugar / lanzar**: «juega a Elden Ring», «quiero jugar a Rust», «pon a jugar a
  Hades», «échate una partida a Valorant», «abre el juego Battlefield» → `steam://run/<id>`
- **Instalar / descargar**: «instala Rust en steam», «descárgate Hades en steam»,
  «en steam bájame Stardew Valley» → `steam://install/<id>`
- **Actualizar / validar**: «actualiza el juego Valheim», «valida Rust en steam»,
  «repara el juego X» → `steam://validate/<id>` (valida = descarga lo que falte)
- **Launchers**: «abre steam / epic / gog / battle.net / ea app / uplay / xbox game pass»

«abre battlefield» a secas lo maneja el minion **Sistema/PC**: si el juego no está
en el índice de apps instaladas, lo lanza por Steam por nombre.

## Notas

- El control real de Steam va en Windows (esquemas `steam://`); fuera de Windows
  nexus te dice el AppID que encontró.
- Si no encuentra el juego en Steam, abre la búsqueda de la tienda para que lo elijas.
- «actualizar» usa validar archivos: Steam no expone un «forzar update» por URL, y
  validar es lo más cercano y seguro (baja lo que falte o esté corrupto).
