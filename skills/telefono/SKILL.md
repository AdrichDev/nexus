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

Variantes que también cazan los patrones: «llámale a Ana», «llámame a mamá»,
«márcale a mamá», «hazle una llamada a Ana», «ponle una llamada a Ana»,
«guárdame el móvil de Juan 612 345 678», «quítame el número de Luis».

## Qué necesita configurado

- La app de nexus instalada en el móvil y con ✔ VINCULADO. Sin ningún móvil
  vinculado, nexus **no intenta llamar**: dice que no lo tiene y cómo
  arreglarlo.
- Para «llama a <nombre>» sin agenda propia, un APK con el puente de llamadas;
  si es viejo, la respuesta ya avisa de que hay que actualizarlo.
- `phone_cc` en `config/settings.json` si tu prefijo no es +34.

## Cómo funciona

- Evento WS `call {to, number, name}` → el móvil marca: puente nativo
  `WabiksNative.dial` (APK reciente) o `tel:` (dialer con el número puesto).
- Números: se normalizan a +34 por defecto (ajustable con `phone_cc` en
  settings). 9 dígitos → se les antepone el prefijo.
- La agenda vive en `data/contacts.json` (fuera de git). Hace que «llama a
  mamá» funcione con CUALQUIER APK o PWA y alimenta el WhatsApp por móvil de
  la skill n8n.

## Qué NO hace

- **nexus no llama: llama tu teléfono.** No hay SIM ni VoIP aquí; solo se
  manda el evento al móvil vinculado y marca él, con tu línea.
- No llama sin que se lo pidas: no hay llamadas automáticas, programadas ni
  disparadas por otra skill.
- No lee ni copia la agenda del móvil: solo pasa el nombre para que la busque
  el propio teléfono.
- No manda WhatsApp: eso es la skill `n8n_flows` (usa esta agenda).
