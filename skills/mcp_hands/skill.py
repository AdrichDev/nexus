"""Minion Manos MCP — cliente de servidores Model Context Protocol.

Conecta por stdio a servidores MCP definidos en config/mcp_servers.json,
descubre sus herramientas (tools/list) y las invoca (tools/call). Es un
cliente MCP mínimo (JSON-RPC sobre stdio) sin dependencias extra — así
nexus gana "manos" como las de Cowork: filesystem, github, slack, etc.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config" / "mcp_servers.json"

SKILL = {
    "name": "Manos MCP",
    "description": "Conectores MCP externos por stdio (filesystem, github, slack, postgres…): descubre sus herramientas y las invoca, como Cowork",
    "patterns": {
        # «reload» va ANTES que «list»: si no, «recárgame los conectores mcp» lo
        # atrapa el «conectores mcp» de list.
        "reload": r"\brec[aá]rga(?:me)?\s+(?:los\s+|la\s+)?(?:conectores?|config(?:uraci[oó]n)?)(?:\s+(?:de\s+)?mcp)?"
                  r"|\b(?:rec[aá]rga(?:me)?|recon[eé]ctate?\s+a?|reinicia)\s+(?:el\s+|los\s+)?mcp",
        "list": r"qu[eé]\s+manos\s+(?:tienes|tengo|hay)|conectores?\s+mcp|servidores?\s+mcp|"
                r"qu[eé]\s+herramientas\s+externas|qu[eé]\s+mcp\s+(?:tienes|hay)|"
                r"qu[eé]\s+conectores?\s+(?:tienes|tengo|hay)|"
                r"(?:l[ií]sta(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|ver)\s+"
                r"(?:los\s+|las\s+)?(?:conectores?|manos)(?:\s+mcp)?",
        # Solo usa/invoca, o verbo + ancla explícita: verbos sin ancla robaban
        # frases ajenas («llama a 612…» del teléfono, «ejecuta el flujo X» de n8n).
        # El \b inicial evita casar dentro de otra palabra («pa-usa la música»).
        # El $ final evita quedarse con «usa el navegador para abrir la web»:
        # tras <servidor> <herramienta> solo cabe «con <args>» o el fin de la orden.
        "call": r"\b(?:usa|invoca|(?:llama|ejecuta)\s+(?=a?l?\s*(?:el\s+)?(?:conector|mcp|la\s+herramienta|herramienta)))\s*"
                r"(?:a?l?\s*(?:el\s+)?(?:conector|mcp|la\s+herramienta|herramienta)\s+)?"
                r"(?P<server>[\w\-]+)\s+(?P<tool>[\w\-\.]+)"
                r"(?:\s+con\s+(?P<args>.+))?\s*$",
    },
}

# Cache de herramientas por servidor (descubiertas al listar)
_tools_cache: dict = {}


def _load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


class MCPStdioClient:
    """Cliente MCP mínimo por stdio (JSON-RPC 2.0)."""

    def __init__(self, command: str, args: list):
        self.command = command
        self.args = args
        self.proc = None
        self._id = 0

    async def __aenter__(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "nexus", "version": "1.0"}})
        await self._notify("notifications/initialized", {})
        return self

    async def __aexit__(self, *a):
        if self.proc:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except Exception:
                pass

    async def _send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def _notify(self, method, params):
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _rpc(self, method, params):
        self._id += 1
        rid = self._id
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=30)
            if not line:
                raise RuntimeError("el servidor MCP cerró la conexión")
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "error MCP"))
                return msg.get("result")

    async def list_tools(self):
        return (await self._rpc("tools/list", {})).get("tools", [])

    async def call_tool(self, name, arguments):
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})


async def _with_server(name: str, cfg: dict, fn):
    client = MCPStdioClient(cfg["command"], cfg.get("args", []))
    try:
        async with client as c:
            return await fn(c)
    except FileNotFoundError:
        raise RuntimeError(f"«{cfg['command']}» no está instalado (¿Node.js / npx?)")


async def handle(intent: str, text: str, match, ctx) -> dict:
    servers = {k: v for k, v in _load_config().items() if v.get("enabled", True)}

    if intent == "list":
        if not servers:
            return {"reply": "No tengo manos MCP configuradas todavía. Copia "
                             "config/mcp_servers.example.json a config/mcp_servers.json, pon "
                             "dentro los servidores que quieras (p. ej. "
                             "@modelcontextprotocol/server-filesystem) y di «recarga los "
                             "conectores». Necesitas Node.js instalado para los servidores npx."}
        lines = [f"Tengo {len(servers)} conector(es) MCP:"]
        for name, cfg in servers.items():
            try:
                tools = await _with_server(name, cfg, lambda c: c.list_tools())
                _tools_cache[name] = [t["name"] for t in tools]
                lines.append(f"• {name}: {', '.join(t['name'] for t in tools[:8]) or '(sin tools)'}")
            except Exception as exc:
                lines.append(f"• {name}: no conecta ({exc})")
        lines.append("\nÚsalos: «usa filesystem read_file con D:\\ruta\\archivo.txt».")
        return {"reply": "\n".join(lines)}

    if intent == "reload":
        _tools_cache.clear()
        return {"reply": f"Config MCP recargada: {len(servers)} servidor(es). "
                         "Di «qué manos tienes» para ver las herramientas."}

    if intent == "call":
        server = match.group("server")
        tool = match.group("tool")
        args_raw = (match.group("args") or "").strip()
        if server not in servers:
            disponibles = ", ".join(servers) or "ninguno todavía"
            return {"reply": f"No tengo el conector «{server}» (tengo: {disponibles}). "
                             "Añádelo en config/mcp_servers.json —copia la plantilla "
                             "config/mcp_servers.example.json si aún no existe— y di "
                             "«recarga los conectores»."}
        # argumentos: JSON si lo parece, si no lo mete como {"path"/"query": ...}
        try:
            arguments = json.loads(args_raw) if args_raw.startswith("{") else None
        except Exception:
            arguments = None
        if arguments is None:
            key = "path" if "\\" in args_raw or "/" in args_raw else "query"
            arguments = {key: args_raw} if args_raw else {}
        try:
            result = await _with_server(server, servers[server],
                                        lambda c: c.call_tool(tool, arguments))
            content = result.get("content", []) if isinstance(result, dict) else result
            text_out = ""
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text_out += c.get("text", "")
            return {"reply": f"[{server}/{tool}] {text_out[:1500] or json.dumps(result)[:1500]}"}
        except Exception as exc:
            return {"reply": f"El conector «{server}» falló: {exc}"}

    return {"reply": "Orden MCP no reconocida."}
