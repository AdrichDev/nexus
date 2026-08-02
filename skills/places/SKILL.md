# Mapas / Viajes (places)

nexus abre Google Maps, prepara rutas y lanza búsquedas de viaje, todo abriendo
la URL correcta en el navegador (fiable, sin API key).

## Órdenes

- **Maps**: «abre google maps»
- **Rutas**: «cómo llego a Barcelona», «ruta de Madrid a Valencia», «prepara la ruta a Lisboa»
  → Google Maps con la ruta lista (medio por defecto: coche; se cambia en la página)
- **Sitios**: «busca el Corte Inglés en el mapa», «dónde hay una farmacia»
- **Vuelos**: «busca vuelos a París», «viajes a Madrid» → Google Flights (ordena por precio ahí)
- **Hoteles**: «busca hoteles en Roma por menos de 90 €», «hoteles en Sevilla» → Google Hotels
- **Vídeos**: «busca vídeos de X» → YouTube (lista de resultados)

## Necesita configurado

Nada: no usa API keys. Solo hace falta un navegador por defecto en el sistema.

## Qué NO hace

- **No lee los resultados**: abre la página y ahí se acaba su trabajo. No te
  dice precios, ni duración de la ruta, ni cuál es el vuelo más barato — no los
  ve. Si te da una cifra, no es de esta skill.
- No reserva, no compra y no compara nada.
- No hace scraping de Google ni de YouTube: solo construye la URL y la abre.
- «ponme vídeos de X» lo atiende la skill `media` (abre y reproduce); aquí solo
  se abre la lista de resultados con «busca vídeos de X».

## Notas

- Las rutas sin origen usan tu ubicación actual del navegador.
- El filtro de precio de hoteles se pasa en la búsqueda; afínalo en la página.
