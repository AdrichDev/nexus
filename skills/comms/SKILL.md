# Skill: Comunicación (bandeja unificada + captura de tareas)

Reúne en una sola bandeja los mensajes que te llegan por WhatsApp, Telegram y
email, y — lo importante — los convierte en tareas del tablero con una orden.
El envío real y la bandeja en vivo se conectan a través del bot de Telegram y
de n8n; mientras no estén conectados, nexus muestra una bandeja de ejemplo
coherente para que veas exactamente cómo quedará el flujo.

## Órdenes

- «ver mensajes» / «mi bandeja» / «qué mensajes tengo» → bandeja unificada
- «envía un mensaje a <nombre> diciendo <texto>» → prepara el envío (sale de
  verdad cuando el canal está conectado)
- «captura de tareas» / «saca tareas de mis mensajes» → detecta lo accionable
  de la bandeja («hay que…», «acuérdate…», un pago pendiente) y lo anota en
  memoria como tareas
- «ver notificaciones» → pendientes sin leer
- «estado del bot» → estado del puente de Telegram y cómo activarlo

## Conectar de verdad

- **Telegram** (control remoto + bandeja/envío reales): @BotFather → /newbot →
  token en ⚙ o `.env` (`TELEGRAM_BOT_TOKEN`), o di «configura telegram <token>».
- **WhatsApp**: no tiene API abierta gratuita → se envía por un flujo de n8n
  (Evolution API, Twilio o WhatsApp Cloud). Importa el flujo, activa el webhook
  en ⚙ y funciona «envía un whatsapp a <nombre> diciendo …» (skill n8n).

Del diseño original: las conversaciones («esto para el lunes») se convierten
solas en tareas; «captura de tareas» es ese flujo aplicado a la bandeja.
