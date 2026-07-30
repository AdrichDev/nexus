# Skill: Manos MCP (conectores externos)

Da a nexus "manos" como las de Cowork: conecta a servidores **MCP**
(Model Context Protocol) y usa sus herramientas. Con esto nexus puede
hablar con sistemas de archivos, GitHub, Slack, bases de datos, etc.,
igual que hago yo en Cowork.

## Configurar

Edita `config/mcp_servers.json` (hay un ejemplo). Cada servidor:
```json
{
  "filesystem": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\Adrian"],
    "enabled": true
  }
}
```
Requiere Node.js (para servidores npx) o Python (uvx). nexus los arranca
por stdio y descubre sus herramientas automáticamente.

## Usar

- "qué manos tienes" / "conectores MCP" → lista servidores y sus herramientas
- "usa <servidor> <herramienta> con <args>" → llama esa herramienta
- "recarga los conectores" → relee la config y reconecta

Servidores MCP recomendados (mismos que usa Cowork):
`@modelcontextprotocol/server-filesystem`, `server-github`, `server-slack`,
`server-postgres`, `server-brave-search`... (npm). El catálogo crece; añade
el que quieras en el JSON.
