# Skill: Vigilancias (webs, precios y noticias) 👁

nexus vigila cosas POR TI mientras haces otra cosa, y te avisa por el HUD
(notificación + chat con voz) y por Telegram cuando algo salta. Cada vigilancia
tiene su número (#1, #2…) como los encargos.

## Órdenes

- «vigila la web https://ejemplo.com/pagina» → avisa si el CONTENIDO cambia,
  con un resumen de las líneas nuevas
- «avísame si baja el precio de https://tienda.com/producto» → extrae el precio
  de la página y avisa en cuanto BAJE (si sube, también lo dice)
- «avísame cuando haya noticias de <tema>» / «vigila las noticias de <tema>»
  → titulares nuevos del tema (Google News)
- «mis vigilancias» / «qué estás vigilando» → lista numerada con estado
- «borra la vigilancia 2» / «deja de vigilar <algo>» → la quita

## Cómo funciona

- Registro en `data/watchers.json`; el scheduler las comprueba cada ~10 min.
- Usa el motor central de búsqueda/lectura (websearch: 3 fuentes + caché).
- Precio: detecta formatos «1.234,56 €», «€99», «120 euros», «$45»…
- Noticias: la primera pasada siembra los titulares ya existentes (no avisa);
  a partir de ahí, solo lo nuevo.
- Cambios web: huella sha256 del texto extraído + diff de líneas nuevas.
