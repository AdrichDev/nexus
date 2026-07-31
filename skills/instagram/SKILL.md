# 📸 Skill: Instagram Reels — comentarios, dudas, leads e ideas

Baja los comentarios y los insights de **tus** reels con **tu** token (Instagram
Graph API oficial, nada de scraping) y saca cuatro cosas: de qué habla la gente,
qué pregunta, quién quiere comprar y **qué grabar después**.

`scripts/ig.py` hace lo aburrido contra la API oficial: paginación completa con
replies anidados, throttling y backoff ante rate limits. Las credenciales las
lee de la configuración de nexus, nunca de la línea de comandos.

## Lo que la hace distinta: EL PERFIL

Un análisis sin contexto es un análisis genérico. «¿Y con niños?» es una
objeción en una cuenta de viajes en pareja y es EL tema en una de crianza. Por
eso el análisis se hace con el contexto completo de quien tiene la cuenta:

- **La cuenta**: usuario, país, nicho, subtemas, propuesta de valor, referentes.
- **El público**: quién es, qué edad, de qué países, qué le duele, qué objeciones pone.
- **Los idiomas**: en cuáles te comentan y en cuál quieres el análisis y los guiones.
- **La persona**: nombre, profesión, dónde vive, situación familiar, **hijos**
  (nombre y edad), idiomas que habla, aficiones, su historia, y los **temas que
  NO quiere tocar**.
- **El tono**: estilo, tuteo o usted, cuántos emojis, palabras prohibidas.
- **El negocio**: objetivo, productos con precio y para quién, lead magnets con
  su palabra-CTA, la métrica que de verdad importa.

Todo es **opcional** y todo lo rellena cada usuario: la plantilla se entrega
**vacía** y no hay ningún dato de nadie escrito en el código. Vive en
`data/instagram/perfiles.json`, admite **varios perfiles** (uno por cuenta) y
tiene uno activo. Lo que no se rellena, no se usa.

## Órdenes que entiende

- «perfil de instagram» / «qué sabes de mi cuenta de instagram» → lo que sabe.
- «instagram nicho: cocina sin gluten» → rellena un campo suelto. También
  `idiomas`, `tono`, `objetivo`, `publico`, `hijos`, `familia`, `productos`,
  `triggers`.
- «configura mi perfil de instagram» → te dice cómo rellenarlo.
- «estado de instagram» → si hay token, ID y cuánto perfil llevas.
- «mis reels» / «lista mis últimos 20 reels» → id, tipo, nº de comentarios y caption.
- «analiza mis últimos 3 reels» → el análisis completo.
- «saca los leads de mis reels» / «qué comenta la gente en mis reels».

## Lo que hace falta (y no viene puesto)

Dos valores de Meta, los dos **vacíos** de fábrica:

| Qué | Dónde se guarda |
|---|---|
| Token de la Graph API | secreto `ig_access_token` (config/secrets.json, no se sube al repo ni sale por la API) |
| ID numérico de la cuenta Business/Creator | ajuste `ig_business_account_id`, o el campo `cuenta.business_account_id` del perfil |

Permisos del token: `instagram_basic`, `instagram_manage_comments`,
`instagram_manage_insights`, `pages_read_engagement`.

El token **nunca** viaja por la línea de comandos (ahí lo vería cualquiera en el
administrador de tareas): se le pasa al script por variables de entorno.

**Python**: no hay que instalar nada. `ig.py` usa solo la librería estándar y se
lanza con el mismo intérprete con el que corre nexus (Python 3.12).

## Cómo trabaja

1. `ig.py bundle --recent N --out <tmp>` escribe un JSON por reel con `media`,
   `insights` y los comentarios ya etiquetados (`is_from_owner`, `is_trigger`,
   `matched_trigger`) y sus contadores.
2. El minion junta esos JSON (con tope para que quepan en el modelo), les pone
   delante el perfil en prosa y se lo pasa al cerebro.
3. Reglas que van en el prompt: para el **sentimiento** se descartan los
   comentarios del dueño y las palabras-CTA sueltas; para los **leads** pasa lo
   contrario, esos son la señal, y además hay que detectar la palabra-imán del
   reel mirando el caption. Sin ese paso, un reel con cientos de leads reporta
   cuatro.

## Qué trae el informe

Los **números los calcula el código**, no el modelo (`analisis.py`). Un modelo no
debe contar comentarios. El modelo entra solo para lo cualitativo: el sentimiento
y las ideas de contenido.

Tres reglas que aquí son ley:

1. **La aritmética cuadra.** Cada comentario cae en UNA de cuatro cestas —tuyo,
   palabra-CTA, con contenido, sin clasificar— y la suma es siempre el total. Si
   los subtotales no llegan al total, el informe lo dice en vez de disimular.
2. **El hueco de leads se reporta.** Si dispararon el gancho más personas que
   mensajes enviaste, esa diferencia se cuenta y se nombra: es dinero sin
   atender, no un redondeo.
3. **El sentimiento lleva su muestra.** Un «93 %» a secas sobre unas decenas de
   comentarios engaña. Cada porcentaje sale con su n y su banda de confianza
   real (Wilson).

Y el informe va completo: **retención** de vídeo, **distribución** del alcance,
**conversión** de negocio y **comparación** con tus reels anteriores. Cuando la
Graph API no da un dato, el informe dice que no está y dónde mirarlo — nunca se
rellena con una estimación disfrazada de medición.

**Erratas en la palabra-CTA**: si tu gancho es «PLANTILLA», también cuentan
«plantila», «plantiya» o «plan tilla» — es el mismo lead. El margen depende de
la longitud: una keyword corta no perdona ninguna, porque se comería medio
diccionario. La palabra la pone cada campaña; nexus no supone ninguna, la
descubre mirando los comentarios.

Sale un `.md` con el informe y un `.csv` con los leads listos para tu CRM, en
`data/instagram/informes/`.

## El informe

Por defecto el análisis se entrega **en un archivo `.md`** (norma de la casa: los
informes se crean en Markdown salvo que pidas expresamente otra cosa — «en word»,
«en pdf», «a csv»…). El criterio lo decide `files_io.formato_pedido()`, que es el
mismo para todas las skills.

## Cuidado

- Los datos que bajas llevan **nombres y comentarios de personas reales**. No los
  publiques. Se escriben en una carpeta temporal y se borran al terminar.
- Los reels con miles de comentarios consumen cuota: empieza por 3 y sube.
- El máximo por análisis son 10 reels, para no reventar el contexto del modelo.
