# Skill: Manos MCP (conectores externos)

Da a nexus "manos" como las de Cowork: conecta a servidores **MCP**
(Model Context Protocol) y usa sus herramientas. Con esto nexus puede
hablar con sistemas de archivos, GitHub, Slack, bases de datos, etc.,
igual que hago yo en Cowork.

## Necesita configurado

`config/mcp_servers.json` — no viene creado: copia `config/mcp_servers.example.json`.
Cada servidor:
```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\ruta-que-quieras-exponer"],
    "enabled": true,
    "tools": {
      "read_file":      {"escritura": false},
      "list_directory": {"escritura": false},
      "write_file":     {"escritura": true},
      "delete_entry":   {"escritura": true}
    }
  }
}
```
Requiere Node.js (para servidores npx) o Python (uvx). nexus los arranca
por stdio y descubre sus herramientas automáticamente.

`tools` es la **lista blanca** de ese servidor, y lo que no está en ella no se
ejecuta. Las cuatro reglas, porque son las que impiden que un conector se
convierta en un agujero (SEC-18 y AI-10 de la auditoría):

1. **Denegar por defecto.** Si `tools` falta, está vacía o tiene una forma que no
   se entiende, ese conector no puede llamar a NINGUNA herramienta. La lista se
   mira **antes** de arrancar el proceso, así que una herramienta no permitida
   cuesta cero procesos y no deja un servidor vivo a medio usar.
2. **`escritura` decide si hay que preguntar.** `false` = solo lee y se ejecuta
   directa; `true` = puede cambiar cosas y nexus arma la misma confirmación de
   siempre («sí» / «no») enseñando servidor, herramienta y los argumentos
   **exactos**. Hasta el «sí» no se arranca nada. Si a una herramienta le falta
   `escritura`, o el valor no es `true`/`false` de verdad, se trata como
   escritura: fallar cerrado cuesta un «sí» de más; escribir sin preguntar cuesta
   un archivo. Una lista de nombres suelta (`"tools": ["a", "b"]`) también vale y
   significa que todas piden «sí».
3. **El texto del operador nunca entra en la línea de órdenes.** El argv del
   servidor son `command` y `args` de la config y nada más: lo que escribes en la
   orden viaja como argumento JSON de la herramienta (`arguments` del JSON-RPC),
   donde `;calc` o `..\\..` son valores y no sintaxis de un shell. En `args`,
   `${NOMBRE_DEL_SECRETO}` se sustituye por el valor guardado en
   `config/secrets.json` (⚙ → APIS); el nombre solo admite letras, dígitos y guión
   bajo, cualquier otra llave entre `${…}` o `{…}` impide arrancar, y el valor no
   se enseña nunca en el chat ni en los registros.
4. **La salida es un dato, no una orden.** Al chat te llega igual que siempre,
   pero en el prompt viaja dentro de `<datos_no_confiables origen="mcp">` con su
   aviso de que son datos de fuera (lo mismo que el dossier web, el RAG o un
   correo), y cualquier marca de cierre escrita dentro se neutraliza, así que no
   puede cerrar la cerca desde dentro. Cuando la herramienta es de escritura, el
   acuse de la confirmación etiqueta la salida línea a línea con
   `[mcp: dato de fuera, no orden]`, porque ese turno no puede llevar la marca del
   historial.

## Usar

- "qué manos tienes" / "conectores MCP" / "muéstrame los conectores" → lista
  servidores y sus herramientas (marca cuáles piden «sí» y cuáles no están
  permitidas todavía)
- "usa <servidor> <herramienta> con <args>" / "invoca <servidor> <herramienta>" /
  "llama al conector <servidor> <herramienta>" → llama esa herramienta
- "recarga los conectores" / "recárgame los conectores mcp" → relee la config

Los `<args>` son un objeto JSON (`{"path": "D:\\x.txt", "content": "hola"}`). Si
escribes un texto suelto, se manda como `path` (cuando parece una ruta) o como
`query`. Si empieza por `{` o `[` tiene que ser un objeto JSON legible: antes de
arrancar nada se dice si no lo es.

## Qué NO hace

- No ejecuta herramientas que no estén en la lista blanca de su servidor.
- No arranca ni instala Node.js/npx: si falta, el conector no conecta y se dice.
- No inventa el resultado de una herramienta: si el servidor falla, sale el error
  del servidor, no una respuesta plausible.
- No interpola el texto de la orden en la línea de órdenes del servidor, ni
  enseña los valores de los secretos.
- Solo habla MCP por **stdio**; no hay transporte HTTP/SSE.
- No se puede usar desde n8n: el canal externo tiene su propia lista blanca de
  órdenes y ésta no está en ella.

Servidores MCP recomendados (mismos que usa Cowork):
`@modelcontextprotocol/server-filesystem`, `server-github`, `server-slack`,
`server-postgres`, `server-brave-search`... (npm). El catálogo crece; añade
el que quieras en el JSON, con su lista `tools`.
