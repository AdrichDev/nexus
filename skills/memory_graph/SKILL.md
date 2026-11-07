# 🧠 Memoria (memory_graph)

Memoria a largo plazo de **doble capa**: cada hecho se escribe en un grafo de
notas markdown estilo Obsidian (`data/memory/`, con enlaces `[[wiki]]`, sin
base de datos) y, si el Docker de nexus está levantado, también en Postgres
con pgvector para **búsqueda semántica**. Además ingiere documentos y carpetas
enteras (texto/código, PDF y Word) troceándolos en fragmentos consultables.

## Órdenes de ejemplo (los patterns las cazan tal cual)

- **Recordar un hecho**: «recuerda que entrego el jueves» ·
  «acuérdate de que el cliente cobra los viernes» · «no olvides que la clave está en el NAS» ·
  «apúntame que el proveedor responde por Telegram» · «guarda en memoria que uso Python 3.12»
- **Aprender conocimiento**: «aprende que los despliegues se hacen con run.bat»
- **Aprender un documento**: «apréndete el documento C:\Users\usuario\apuntes.pdf» ·
  «indexa el archivo notas.md» · «estudia el pdf D:\facturas\contrato.pdf»
- **Aprender una carpeta**: «apréndete la carpeta D:\apuntes» ·
  «ingiere el directorio C:\proyectos\docs» (máx. 40 archivos < 6 MB por tanda)
- **Consultar**: «qué recuerdas de Ana» · «qué sabes sobre el proyecto Helios» ·
  «qué te he contado de la nave» · «busca en la memoria facturas» ·
  «búscame en mis notas las facturas» · «encuentra en la memoria China»
- **Todo sobre mí**: «qué sabes de mí» · «cuánto sabes de mí» ·
  «lista los archivos de conocimiento que tienes sobre mí» · «todo lo que has aprendido de mí»
- **Perfil**: «mi perfil» · «quién soy» · «háblame de mí» · «perfil del operador»
- «olvida que me divorcié» · «olvídate de la mudanza» → enseña **qué nota** lo dice y
  **en qué almacenes** está copiada, y pide un «sí» antes de tocar nada (ver «Olvidar»)
- «borra el recuerdo de la entrevista» · «no recuerdes el número de la cuenta» → lo mismo,
  con las otras dos formas de pedirlo
- **Grafo**: «muéstrame el grafo» · «enséñame el grafo» · «grafo de notas» · «mapa de memoria»
- **Estado**: «estado de la memoria» · «cómo va tu memoria»

## Olvidar (dos tiempos, y el segundo no lo doy yo)

- La frase tiene que traer **palabras distintivas**: «olvida eso» se rechaza y se pide
  una frase más concreta (el umbral es el mismo que usa la purga para emparejar notas:
  4+ caracteres y fuera de la lista de palabras vacías de `umbrales.json`).
- Si no encuentra nada, lo dice («no encontré nada sobre X en mi memoria») y **no** arma
  ninguna confirmación.
- Si encuentra algo: enseña la nota, las filas de la base de datos y **la lista de
  almacenes** (cuáles se tocan y cuáles no, con su motivo), y espera un «sí».
  Antes del «sí» no se mueve **ni un byte**.
- Con «sí»: la nota y el espejo del documento van a la **papelera** (se restauran), las
  categorías personales dejan antes una **copia legible** en
  `data/exportado_purga/personal/<lote>/`, y se barren el almacén vectorial local, la
  memoria operativa, Engram y la caché web de la lista enseñada.
- Los **registros** de conversación/auditoría/recall y los resultados de trabajos NO se
  tocan desde aquí: son la traza del incidente y solo salen si se piden expresamente
  (`incluir_logs` en la purga, `/api/memoria/purga/*`). Por voz todavía no hay atajo.
- Las **copias de seguridad** tampoco se reescriben: se nombran con sus fechas y el
  camino es dejar que roten solas o borrarlas a mano en `data/backups/`.
- El **borrado definitivo** (`borrar_definitivo`) es otro paso, irreversible, y no lo
  inicia esta skill.

## Notas técnicas

- PDF y Word necesitan `pypdf` y `python-docx` (se instalan con `run.bat`);
  sin ellos, esos archivos se saltan y nexus te lo dice.
- La capa semántica exige la DB del contenedor (se arranca diciendo
  «levanta docker»); offline, todo sigue funcionando solo con el grafo markdown
  y la skill lo avisa en cada respuesta.
- Las rutas de documentos/carpetas pasan por `backend.core.permissions`:
  si una ruta está fuera de lo permitido, nexus responde cómo autorizarla.
- «qué sabes de mí» junta perfil destilado, hechos en Postgres, conocimiento RAG,
  títulos del grafo y lo que sepa Hermes.
- Documentos: nota completa en el grafo (primeros 20.000 caracteres) + fragmentos
  de ~900 caracteres en la DB para el recall.

## Qué NO hace

- No guarda nada que no le hayas dicho: solo escribe el texto literal del hecho
  o el contenido real del archivo. No resume con el LLM ni rellena huecos.
- No borra recuerdos de forma definitiva: el único destructor es `borrar_definitivo` de la
  purga, y solo lo arranca el operador. Aquí «olvida …» deja todo en la papelera,
  restaurable.
- «recuérdame X el viernes» NO es esta skill: es un recordatorio del coach.
  Aquí el disparador es «recuerda QUE …».
