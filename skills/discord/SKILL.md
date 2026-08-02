# 💬 Discord (discord)

nexus publica avisos en un canal de tu servidor de Discord por **webhook** (la
vía soportada y segura) y abre la app cuando se la pides.

## Órdenes de ejemplo

- **Abrir la app**: «abre discord», «lanza discord»
- **Publicar en un canal**: «manda a discord: la build está lista»,
  «avisa por discord que llego tarde», «publica en el canal de discord que hay
  reunión a las 5», «en discord escribe que el server ya está arriba»
- **Llamada** («llama a Ana por discord») y **DM** («abre un chat en discord»):
  nexus abre Discord y te explica el límite (ver abajo).

## Configurar el webhook

En tu servidor de Discord → Configuración → Integraciones → Webhooks → Nuevo
webhook, elige el canal, copia la URL y guárdala en ⚙ (campo «Discord
webhook»). Un webhook = un canal; para publicar en otro canal, crea otro
webhook y cambia la URL.

## Lo que Discord NO permite por automatización

Iniciar **llamadas** o abrir un **DM concreto a una persona** no está soportado
por la API ni por deep links para cuentas de usuario. En esos casos nexus abre
Discord y te lo deja a un clic, y ofrece el webhook para avisos a un canal.

## Notas técnicas

- El mensaje se recorta a 1900 caracteres (límite de Discord: 2000).
- Abrir la app usa el esquema `discord://` (Windows); en otros sistemas solo
  funciona la publicación por webhook.
- Si Discord devuelve un error HTTP, casi siempre es que el webhook fue borrado
  o regenerado: crea uno nuevo y actualiza ⚙.
