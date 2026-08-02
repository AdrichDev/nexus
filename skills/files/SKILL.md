# 📁 Skill: Archivos

Gestión de archivos y carpetas **del disco local**. Explora, busca, lee de
verdad (.txt/.md/.docx/.pdf/.xlsx/.csv/.json/código), resume y analiza con el
modelo, crea, actualiza, mueve, copia, renombra, guarda versiones y manda cosas
a la papelera del sistema. Todo pasa por `backend.core.permissions`
(sandbox / carpetas concretas / todo el disco).

## Órdenes de ejemplo (frases que los patrones cazan de verdad)

- **Explorar**: «explora la carpeta Descargas» · «explórame la carpeta X» ·
  «ábreme la carpeta Documentos» · «qué hay en el escritorio»
- **Buscar**: «busca informe en mis documentos» · «búscame factura en la carpeta Descargas»
- **Leer**: «lee el archivo notas.txt» · «léeme acta.pdf» — abre el fichero de
  verdad y enseña las primeras líneas con formato, bytes y páginas/párrafos
- **Resumir**: «resume el documento acta.pdf» · «resúmeme acta.pdf» (usa el LLM configurado)
- **Analizar código**: «analiza el código skill.py» · «analízame el script main.py»
- **Crear carpeta**: «crea una carpeta llamada Proyectos en Documentos»
- **Crear archivo**: «crea el archivo notas.md que diga hola» · «créame un archivo lista.txt»
- **Documento en el escritorio**: «hazme un documento word en el escritorio» ·
  «crea un documento en el escritorio que se llame acta y dentro haya un poema»
  (el contenido lo redacta el modelo si se describe en vez de dictarlo)
- **Actualizar**: «añade al archivo notas.md que diga hola» ·
  «actualiza el archivo notas.md con el texto ...» (añadir o sustituir según el verbo)
- **Versiones**: «qué versiones tienes de notas.md» · «restaura el archivo notas.md»
- **Mover / copiar / renombrar**: «mueve el archivo x.txt a Documentos» ·
  «cópiame el archivo x.txt a Documentos» · «renombra el archivo x.txt a y.txt»
- **Papelera**: «borra el archivo notas.txt» · «bórrame la carpeta Pruebas» ·
  «manda a la papelera C:/tmp/x.txt»

## Seguridad de los borrados

- **Nada se borra sin confirmación explícita.** `trash` NO borra: arma la acción
  en `backend/core/confirm.py` y devuelve la pregunta con la **ficha de lo que se
  lleva** (archivo con su tamaño, o carpeta con cuántos elementos hay dentro,
  subcarpetas incluidas) y la ruta completa. El brain resuelve el «sí»/«no» antes
  que ningún router; si el operador contesta otra cosa la confirmación se
  descarta, y caduca a los 5 minutos.
- **Nunca borra de verdad**: usa `send2trash`, así que va a la papelera del
  sistema y se recupera desde ahí. Si `send2trash` no está instalado lo dice y
  **no toca el fichero**.
- **Sobrescribir** un archivo existente (`mkfile` sobre uno que ya está) también
  exige confirmación, avisa del tamaño y la fecha del actual, y guarda copia de la
  versión anterior antes de pisarla.
- **Restaurar** una versión anterior también pide confirmación.

## Lo que NO hace

- **No toca Google Drive.** Drive es de `skills/google_workspace`. Como el router
  recorre las carpetas por orden alfabético, `files` se evaluaría antes; por eso
  14 de los 16 intents llevan el candado `_SIN_DRIVE`, un lookahead que los
  desactiva en cuanto la frase menciona «drive». «borra la carpeta Informes **de
  drive**» va a Drive, no al disco. La única excepción a propósito es `analyze`
  (solo lectura, exige una ruta con extensión de código y no hay intent de Drive
  que analice código).
- No borra de forma irreversible: no hay borrado directo, todo pasa por la papelera.
- No sube ni descarga nada de internet.
- No sale del ámbito permitido en ⚙: si el permiso es «sandbox» o «carpetas
  concretas», responde con el motivo en vez de tocar la ruta.

## Notas técnicas

- Lectura real de formatos en `backend/core/files_io.py` (`read_any`); si un
  formato no es compatible lo dice, jamás afirma haber leído lo que no abrió.
- Tras crear o modificar **verifica que el archivo existe** y devuelve la ruta real.
- «escritorio», «documentos», «descargas» e «imágenes» se resuelven a las carpetas
  del perfil (con la redirección de OneDrive de Windows tenida en cuenta).
- Dependencias opcionales: `send2trash` (papelera), `python-docx` (.docx real).
  Sin ellas responde explicando qué instalar, sin fingir que hizo el trabajo.
