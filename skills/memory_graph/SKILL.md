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
  «qué te he contado de la nave» · «busca en la memoria facturas» · «busca en tus notas China»
- **Todo sobre mí**: «qué sabes de mí» · «cuánto sabes de mí» ·
  «lista los archivos de conocimiento que tienes sobre mí» · «todo lo que has aprendido de mí»
- **Grafo**: «muéstrame el grafo» · «enséñame el grafo» · «grafo de notas» · «mapa de memoria»
- **Estado**: «estado de la memoria» · «cómo va tu memoria»

## Notas técnicas

- PDF y Word necesitan `pypdf` y `python-docx` (se instalan con `run.bat`);
  sin ellos, esos archivos se saltan y nexus te lo dice.
- La capa semántica exige la DB del contenedor (arranca con `nexus_up.bat`);
  offline, todo sigue funcionando solo con el grafo markdown.
- Las rutas de documentos/carpetas pasan por `backend.core.permissions`:
  si una ruta está fuera de lo permitido, nexus responde cómo autorizarla.
- «qué sabes de mí» junta perfil destilado, hechos en Postgres, conocimiento RAG,
  títulos del grafo y lo que sepa Hermes.
- Documentos: nota completa en el grafo (primeros 20.000 caracteres) + fragmentos
  de ~900 caracteres en la DB para el recall.
