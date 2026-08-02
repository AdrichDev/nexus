# 🔁 n8n / WhatsApp (automatizaciones)

Conecta nexus con tus flujos de n8n en ambas direcciones: nexus dispara tus
workflows por webhook (y manda WhatsApp a través de ellos), y tus flujos pueden
darle órdenes a nexus por HTTP.

## Salida (nexus → n8n) — órdenes de ejemplo

- «lanza el flujo backup diario» / «dispara el flujo informes» /
  «en n8n ejecuta el flujo scraping» → POST al webhook con `{action: "flow", flow, text}`
- «envía un whatsapp a Ana diciendo que llego en 10» →
  POST con `{action: "whatsapp", to, message}`
- «dile a Marta por whatsapp que la reunión se mueve a las 5»
- «whatsapp a Juan: nos vemos a las 8»

El WhatsApp lo envía TU flujo con el nodo que uses (Evolution API, Twilio,
WhatsApp Cloud API...); nexus le entrega destinatario y mensaje.

## Configuración

URL del webhook en ⚙ (campo n8n) o en `config/settings.json` →
`n8n_webhook_url` (ej.: `http://localhost:5678/webhook/nexus`). El flujo debe
estar ACTIVO en n8n (interruptor verde) o solo responderá el webhook de test.

## Entrada (n8n → nexus)

Tu flujo puede llamar a `POST http://127.0.0.1:8177/api/n8n` con
`{"text": "recuérdame X el viernes", "speak": true}` — nexus procesa la orden
como si la hubieras dicho tú y devuelve `{"reply": ...}`. Con `speak: true`
además la dice en voz alta por el HUD.

## Ejemplo de flujo (importable)

`config/n8n_flujo_ejemplo.json`: webhook que recibe el whatsapp de nexus y lo
reenvía; cámbiale el último nodo por tu proveedor de WhatsApp real.

## Qué NO hace

- Sin URL de webhook configurada no dispara ningún flujo: te dice dónde ponerla.
- **No envía el WhatsApp él**: se lo entrega a tu flujo (que lo manda con
  Evolution/Twilio/Cloud API) o lo deja escrito en tu móvil para que le des a
  enviar. Que diga «entregado a tu flujo» no significa que haya llegado.
- No lee respuestas de WhatsApp ni conversaciones.
- No lista los flujos que tienes en n8n ni comprueba que existan: dispara el
  webhook con el nombre que le des y es tu flujo quien decide qué hacer.
- Por la vía n8n el destinatario es un nombre/token que resuelve tu flujo; por
  la vía móvil el número lo pone la agenda de la skill `telefono`.

## WhatsApp sin n8n: por tu móvil (estilo Android Auto)

Si NO hay webhook de n8n configurado pero SÍ un móvil vinculado, «envía un
whatsapp a mamá diciendo hola» sale por tu propio teléfono: nexus resuelve el
número con su agenda (skill teléfono — «apunta el teléfono de mamá 612…»),
manda el evento `whatsapp` al móvil y allí se abre WhatsApp con el chat y el
texto ya escritos; solo le das a enviar. Con n8n configurado, el envío es 100%
automático por tu nodo (Evolution/Twilio/Cloud API), sin tocar el móvil.
