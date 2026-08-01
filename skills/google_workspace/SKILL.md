# 📧 Google Workspace — Gmail + Calendar + Tasks + Drive (REALES)

Habla con tu cuenta de Google de verdad, vía OAuth2 (nunca con tu contraseña).
Lee, cuenta, resume, envía y borra correos; hace triaje con IA de lo urgente y lo
accionable (y lo convierte en tareas en Google y en el tablero interno); crea,
mueve y cancela eventos de Calendar; y gestiona tu lista de Google Tasks (To-Do).
Las llamadas a Google son síncronas y corren en un hilo aparte; los análisis
pesados («urgentes», «triaje») van en **segundo plano** con acuse inmediato y
aviso al terminar por el canal que lo pidió (PC con voz, Telegram si vino de ahí).

## Órdenes de ejemplo (cada una hace algo DISTINTO)

Gmail — consultar:
- «cuántos correos tengo sin leer» → **solo números**: sin leer + total de bandeja
  (cuenta CONVERSACIONES, el mismo número que ves en tu app de Gmail)
- «de quién son los correos» / «cuáles correos tengo» / «dime los remitentes»
  → **solo remitente + asunto** de los NO leídos (nunca el cuerpo)
- «lee mis correos» / «échale un ojo a mis correos» / «qué tengo en la bandeja»
  → lista los NO leídos (los ya leídos solo si dices «leídos» o «todos»)
- «abre el correo 2» / «ábreme el mail 4» → cuerpo completo del N de la última lista
- «resume mis correos» → resumen con IA de la bandeja · «resume el correo 2» → de ese

Gmail — triaje con IA (en segundo plano, avisa al acabar):
- «¿tengo correos urgentes?» / «hay algo urgente en gmail» → detecta por CONTEXTO
  cuáles corren prisa
- «analiza los correos» / «haz triaje de los correos» / «crea tareas de lo urgente»
  → detecta lo accionable y **crea tareas**: Google Calendar si implica fecha,
  Google Tasks si no, y espejo en el tablero interno

Gmail — actuar:
- «envía un correo a nombre@dominio.com con asunto X diciendo Y» → **ENVÍA de
  verdad** desde tu cuenta (si no das el texto, nexus redacta el cuerpo)
- «pon los correos como leídos» / «márcalos como leídos» / «marca el correo 2 como
  no leído»
- «borra el correo 3» / «elimina los correos de Amazon» / «manda a la papelera los
  correos de más de 30 días» → a la **papelera** (recuperables 30 días, nunca
  borrado permanente)

Calendar:
- «qué tengo en el calendario» / «qué tengo esta semana» → próximos eventos
- «crea un evento reunión con Rubén el viernes a las 17:00» /
  «resérvame una cita con el dentista el martes» → evento REAL (entiende «mañana»,
  «el jueves», «25/07», «a las 9:30 de la mañana»; sin hora = todo el día)
- «mueve la reunión al viernes a las 17» / «reprograma la cita del médico»
- «cancela la reunión con el CTO» / «borra el evento del jueves» /
  «anúlame la cita del dentista»

Tasks (To-Do):
- «tareas de google» / «qué tengo en el to-do» → lista de pendientes
- «crea una tarea en el to-do: pagar al proveedor el viernes» → tarea REAL

Drive:
- «sube el informe a drive» → sube el .md más reciente de `data/reports` y
  devuelve el enlace
- «sube informe-2026-08-02.md a drive» → sube ESE fichero (con espacios en el
  nombre, entre comillas: «sube "mi informe.md" a drive»)
- «sube el informe a la carpeta Clientes de drive» → a ESA carpeta, no a la de siempre
- «qué hay en mi drive» / «qué hay en la carpeta Clientes de drive» → lista esa carpeta
- «dame el enlace de drive» → el enlace de lo último subido
- «crea la carpeta Informes en drive» / «crea la carpeta Clientes/2026/agosto en
  drive» → crea la ruta entera, los tramos que falten
- «mueve informe.md a la carpeta Clientes en drive» / «…a la raíz de drive»
- «renombra informe.md a informe-final.md en drive»
- «busca contratos en drive» / «busca los pdf de 2026 en drive»
- «descarga informe.md de drive» → lo deja en `data/drive` (los Google
  Docs/Sheets/Slides se exportan a `.md`, `.csv` y `.pdf`)
- «borra informe-viejo.md de drive» → **a la PAPELERA de Drive**, se recupera
- «borra definitivamente informe-viejo.md de drive» → **te pide confirmación**

Para qué sirve: el informe diario de competencia se genera en `.md`, se manda por
correo y se sube a Drive, para que después ChatGPT o Claude —conectados a ese
Drive— trabajen sobre él sin que nadie suba nada a mano.

**El permiso que pide es `auth/drive` COMPLETO desde el 02/08/2026**, por decisión
explícita del dueño de la cuenta, que pidió «control total». Antes era `drive.file`
(solo lo que creaba nexus), y con eso no se podía tocar ninguna carpeta creada a
mano. Lo que implica, dicho claro: **nexus puede leer, modificar, mover, renombrar
y borrar cualquier documento de tu cuenta**, no solo los suyos.

Por eso, y no por burocracia, lo destructivo lleva cinturón:
- **borrar = papelera de Drive** (`trashed`), recuperable en drive.google.com/drive/trash;
- **el borrado definitivo pide confirmación** («sí»/«no») antes de tocar nada;
- **borrar una carpeta con cosas dentro dice cuántas** y pide confirmación;
- mover y renombrar no destruyen nada: van directos.

El nombre de la carpeta por defecto está en `config/umbrales.json` →
`drive.carpeta` (por defecto `nexus`). Es solo el DEFECTO: cualquier orden puede
apuntar a otra carpeta o a la raíz si se lo dices.

**La primera vez que uses una orden de Drive se abrirá el navegador** para
reautorizar: el token que tienes guardado no incluye el permiso de Drive.

## Configuración (una sola vez, ~5 minutos)

1. https://console.cloud.google.com → proyecto nuevo (ej. «nexus»).
2. **APIs y servicios → Biblioteca**: habilita *Gmail API*, *Google Calendar API*,
   *Google Tasks API* y *Google Drive API*.
3. **Pantalla de consentimiento OAuth**: tipo *Externo*, modo «Prueba», y en
   **Usuarios de prueba** añade TU cuenta (si no, Google bloquea el acceso).
4. **Credenciales → ID de cliente OAuth → «App de escritorio»**. ⚠ NO «Aplicación
   web»: la de escritorio acepta cualquier loopback sin registrar redirecciones.
   Pega el Client ID y el Client Secret en ⚙ (sección Google) y nexus genera
   `config/google_credentials.json` solo — o descarga tú el JSON con ese nombre.
5. `pip install google-api-python-client google-auth-oauthlib` (run.bat ya lo
   instala solo).
6. La primera orden de Google abre el navegador para autorizar; el token queda en
   `config/google_token.json`.

## Notas técnicas y límites

- Scopes: `gmail.modify`, `gmail.send`, `calendar.events`, `tasks`, `drive`. Si el token
  guardado no cubre los scopes actuales (p. ej. tras añadir ESCRITURA), nexus lo
  borra y relanza la autorización UNA vez — es normal que el navegador se abra.
- Redirect OAuth con puerto FIJO: `http://127.0.0.1:8765/` (127.0.0.1, no
  «localhost»; Google lo rechaza para loopback).
- Si cambias de cliente en ⚙ (otro Client ID), nexus regenera las credenciales y
  fuerza reautorización sola.
- El triaje analiza hasta 30 no-leídos con cuerpo; el total reportado es siempre
  el REAL de la bandeja (threads, como tu app de Gmail).
- El análisis va **por lotes** (`correos.por_lote` en `config/umbrales.json`, 6 por
  defecto). No es un capricho: mandando los 30 de golpe son 22.000 caracteres,
  ollama corta el prompt a 4096 tokens y el modelo contesta en prosa en vez de
  JSON. Medido con qwen3:8b: con 6 clasifica los 30 y pilla la alerta; con 10
  solo clasifica 21; con 30 no clasifica ninguno. Con un modelo de más contexto
  puedes subir el número.
- Debajo del modelo hay una **red determinista**: si el remitente o el asunto
  contienen alguna de las `correos.marcas_urgentes` de `config/umbrales.json`
  (`[alerta]`, `alerta de seguridad`, `pago rechazado`…), el correo sale urgente
  aunque el modelo diga que no y aunque el modelo no conteste. Se compara sin
  tildes y sin distinguir mayúsculas.
- Y lo que **no se ha podido clasificar se dice**. Antes, si el modelo fallaba,
  se respondía «ninguno parece urgente» — que es mentira: no se había mirado
  nada. Ahora se avisa de cuántos se quedaron fuera.
- Zona horaria de eventos: Europe/Madrid.

## Si ves «Acceso bloqueado: la solicitud de esta app no es válida»

Es **Error 400: redirect_uri_mismatch** — configuración del cliente OAuth, no de
nexus. Por orden de facilidad:

1. **(Recomendado)** Crea un cliente NUEVO tipo **«App de escritorio»**, pega su
   Client ID/Secret en ⚙ y borra `config/google_token.json`.
2. Si insistes con «Aplicación web»: Credenciales → tu cliente → **URIs de
   redirección autorizadas** (NO «Orígenes de JavaScript») añade EXACTAMENTE, con
   barra final: `http://127.0.0.1:8765/`. Guarda y espera 1-2 min.
3. Comprueba que tu cuenta está en **Usuarios de prueba**.

Después borra `config/google_token.json` y vuelve a pedir «lee mis correos».
