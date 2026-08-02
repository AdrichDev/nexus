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
    "enabled": true
  }
}
```
Requiere Node.js (para servidores npx) o Python (uvx). nexus los arranca
por stdio y descubre sus herramientas automáticamente.

## Usar

- "qué manos tienes" / "conectores MCP" / "muéstrame los conectores" → lista
  servidores y sus herramientas
- "usa <servidor> <herramienta> con <args>" / "invoca <servidor> <herramienta>" /
  "llama al conector <servidor> <herramienta>" → llama esa herramienta
- "recarga los conectores" / "recárgame los conectores mcp" → relee la config

## Qué NO hace

- No arranca ni instala Node.js/npx: si falta, el conector no conecta y se dice.
- No inventa el resultado de una herramienta: si el servidor falla, sale el error
  del servidor, no una respuesta plausible.
- Solo habla MCP por **stdio**; no hay transporte HTTP/SSE.

Servidores MCP recomendados (mismos que usa Cowork):
`@modelcontextprotocol/server-filesystem`, `server-github`, `server-slack`,
`server-postgres`, `server-brave-search`... (npm). El catálogo crece; añade
el que quieras en el JSON.
