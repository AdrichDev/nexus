# Skill: Vigilancias (webs, precios y noticias) 👁

nexus comprueba cosas por ti en segundo plano y avisa por el HUD (notificación
+ chat con voz) y por Telegram cuando algo salta. Cada vigilancia lleva su
número (#1, #2…) como los encargos.

## Qué hace

- **Cambios en una web**: guarda una huella del texto de la página y avisa
  cuando cambia, con un resumen de las líneas nuevas.
- **Bajadas de precio**: extrae el precio de la página y avisa cuando BAJA
  (si sube, también lo dice).
- **Noticias de un tema**: titulares nuevos vía Google News.

## Frases que la disparan

- «vigila la web https://ejemplo.com/pagina» · «vigila https://ejemplo.com» ·
  «vigílame https://ejemplo.com» · «avísame si cambia la web https://ejemplo.com»
- «avísame si baja el precio de https://tienda.com/producto» ·
  «avísame cuando baje el precio de https://…» · «vigila el precio de https://…»
- «avísame cuando haya noticias de <tema>» · «avísame cuando salgan noticias
  sobre <tema>» · «vigila las noticias de <tema>»
- «mis vigilancias» · «qué vigilancias tengo» · «qué estás vigilando» ·
  «muéstrame las vigilancias»
- «borra la vigilancia 2» · «elimina la vigilancia 3» · «deja de vigilar <algo>»

Ojo: «avísame si cambia https://…» (sin la palabra *precio*) es vigilancia de
CONTENIDO, no de precio. Para precio hay que nombrarlo.

## Qué necesita configurado

- Nada obligatorio: funciona solo con salida a internet.
- Telegram (`config/settings.json`) solo si además quieres el aviso al móvil;
  sin él, el aviso sale igualmente por el HUD.

## Cómo funciona

- Registro en `data/watchers.json`; el scheduler comprueba cada ~10 min.
- Lectura y búsqueda por el motor central (`backend/core/websearch.py`).
- Precio: reconoce «1.234,56 €», «€99», «120 euros», «$45».
- Noticias: la primera pasada solo siembra los titulares existentes; a partir
  de ahí avisa solo de lo nuevo.
- «mis vigilancias» dice el estado real de cada una: si aún no se ha
  comprobado, o si en esa página NO se encuentra precio (entonces no habrá
  aviso nunca, y lo avisa en vez de dejarte esperando).

## Qué NO hace

- No rellena formularios ni entra en zonas con login: solo lee páginas públicas.
- No compra ni reserva nada cuando el precio baja: solo avisa.
- No consulta redes sociales ni datos de audiencias de terceros.
- No baja de ~10 min entre comprobaciones de una misma vigilancia.
