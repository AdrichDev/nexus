# Skill: Teléfono (llamadas + agenda, estilo Android Auto)

nexus usa tu MÓVIL vinculado como manos para llamar: tú se lo pides (por voz o
texto, desde el PC o desde el propio móvil), nexus manda el evento por
WebSocket y quien marca es tu teléfono, con tu SIM.

## Órdenes

- «llama a 612 345 678» / «marca el 611 22 33 44» → marca directo
- «llama a casa» / «telefonea a Ana» → resuelve el número en la AGENDA de
  nexus; si no está, lo busca en los contactos del móvil (APK reciente)
- «apunta el teléfono de mamá 612 345 678» → guarda el contacto en la agenda
  (data/contacts.json); también sirve para WhatsApp
- «mis contactos» / «qué teléfonos tienes» → lista la agenda
- «borra el contacto de mamá» → lo quita
- «¿puedes hacer llamadas?» → explica la función

## Cómo funciona

- Evento WS `call {to, number, name}` → el móvil marca: puente nativo
  `WabiksNative.dial` (APK reciente) o `tel:` (dialer con el número puesto).
- Números: se normalizan a +34 por defecto (ajustable con `phone_cc` en
  settings). 9 dígitos → se les antepone el prefijo.
- La agenda de nexus hace que «llama a mamá» funcione con CUALQUIER APK o PWA
  y alimenta el WhatsApp por móvil de la skill n8n («envía un whatsapp a mamá
  diciendo …» sin n8n configurado → se abre WhatsApp en el móvil con el chat
  y el texto listos).
