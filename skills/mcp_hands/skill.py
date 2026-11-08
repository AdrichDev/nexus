"""Minion Manos MCP — cliente de servidores Model Context Protocol.

Conecta por stdio a servidores MCP definidos en `CONFIG_DIR/mcp_servers.json`
(`config/mcp_servers.json` salvo que `NEXUS_CONFIG_DIR` diga otra carpeta, T39),
descubre sus herramientas (tools/list) y las invoca (tools/call). Es un
cliente MCP mínimo (JSON-RPC sobre stdio) sin dependencias extra — así
nexus gana "manos" como las de Cowork: filesystem, github, slack, etc.

 ─────────────────────────────────────────────────────────────────────────────
 LO QUE ESTABA MAL (auditoría del 30/07/2026: SEC-18, AI-10 y la fila P3-7 del
 roadmap). Esta skill filtraba los servidores SOLO por `enabled` y, dentro de uno
 encendido, aceptaba cualquier `tool` y cualquier `args` que salieran del texto
 libre: arrancaba el proceso y devolvía lo que dijera el servidor. No había lista
 blanca de herramientas, ni confirmación para las que cambian cosas, ni nada que
 impidiera que la salida de un tercero se leyera como una orden de nexus. Un
 conector apagado no era un problema; uno encendido lo era todo a la vez.
 ─────────────────────────────────────────────────────────────────────────────

 Las cuatro puertas que hay ahora, en el orden en que se pasan:

 1) LISTA BLANCA POR SERVIDOR, Y DENEGAR POR DEFECTO. Cada servidor declara en su
    config `"tools"`, con una entrada por herramienta permitida. Lo que no está
    ahí NO se llama — y si `tools` falta, está vacía o tiene una forma que no se
    entiende, ese servidor no puede usar NINGUNA herramienta. La lista se
    consulta ANTES de arrancar el proceso: una herramienta no permitida cuesta
    cero procesos, no un proceso que luego se mata. La negativa dice en castellano
    el servidor, la herramienta y dónde se permite, porque una negativa que no
    dice cómo arreglarlo se lee como un fallo de nexus.

 2) CLASIFICACIÓN DE ESCRITURA, EN LOS DATOS Y NO EN UNA ADIVINANZA. Cada entrada
    de `tools` puede declarar `"escritura": true|false`. No hay heurística por el
    nombre de la herramienta (`write_file` se llamaría así por convención, pero
    una herramienta ajena puede llamarse `save` o `apply`): la decisión es un dato
    del archivo de config, determinista y auditable. Y si el metadato NO está —o
    no es un booleano de verdad— la herramienta se trata como ESCRITURA. Falla
    cerrado: preguntar de más cuesta un «sí»; escribir sin preguntar cuesta un
    archivo. La forma corta `"tools": ["a", "b"]` es válida y significa «estas se
    pueden usar, y todas piden permiso», que es la lectura segura de una lista sin
    metadatos.

 3) EL «SÍ» DEL OPERADOR PARA ESCRIBIR. Una herramienta de escritura se ARMA con
    `confirm.request(kind="mcp_herramienta")` — el mismo mecanismo que los envíos
    (T5), el triaje de correo (T10) y la delegación (T25); no hay un segundo
    mecanismo de permiso en este repo y no se inventa aquí. La pregunta enseña
    servidor, herramienta y los argumentos EXACTOS que se van a mandar (recortados
    con «…» si no caben, nunca resumidos: un resumen es enseñar otra cosa). Antes
    del «sí» no se arranca nada; «no» y cambiar de tema no arrancan nada.

 4) LA SALIDA ES UN DATO. Lo que devuelve una herramienta lo ha escrito un
    tercero, así que el resultado se marca `origen_datos="mcp"`: `brain` guarda el
    turno marcado y `llm._build_messages` lo cerca como DATO al construir el
    prompt (T11/AI-03). El texto que ve el operador en el chat NO cambia —la cerca
    es para el modelo— y `datos_inyectados.bloque()` neutraliza cualquier marca de
    cierre que venga dentro, así que la salida no puede cerrar la cerca desde
    dentro (T11c). La ruta confirmada es la excepción conocida: `confirm.answer`
    devuelve texto y `brain` lo guarda sin poder llevar la marca, así que ahí la
    salida se etiqueta LÍNEA A LÍNEA con `datos_inyectados.prefijo("mcp")` —la
    marca corta que T11c diseñó para donde no cabe el bloque entero— en vez de
    copiarla sin etiqueta.

 Y DOS COSAS SOBRE LA LÍNEA DE ÓRDENES (el argv del servidor):

   * El texto del operador (ni el del planificador) entra NUNCA en el argv. El
     argv es `command` + `args` de la config, y el texto solo viaja como
     `arguments` del JSON-RPC, que es un objeto JSON: `;calc` o `..\\..` ahí son
     valores de un argumento de herramienta, no sintaxis de un shell. `asyncio.
     create_subprocess_exec` no tiene shell que inyectar (y no se usa `shell=True`
     en ningún sitio, lección de T24).
   * Un hueco `${NOMBRE}` en `args` se resuelve con el VALOR de un secreto del
     almacén (`settings.secret`), nunca con texto del operador, y el NOMBRE tiene
     que tener la forma `[A-Za-z0-9_]+` (la misma comprobación que usa la skill de
     juegos para los nombres de secretos, `ce90957`). Un hueco con otra forma, o
     un secreto que no está configurado, paran el arranque con una negativa que
     nombra el SECRETO y nunca su valor. El valor resuelto tampoco se escupe en la
     respuesta: si el servidor lo repitiera (npm enseña su propia línea de
     órdenes cuando falla), se enmascara por VALOR antes de contestar.
"""
from __future__ import annotations

import asyncio
import json
import re

# DE DÓNDE SALE LA CONFIG (task T39, al cerrar T26). Antes esta ruta se montaba a
# mano con `Path(__file__).resolve().parents[2] / "config"`, así que la skill
# IGNORABA `NEXUS_CONFIG_DIR` y leía SIEMPRE el `config/` real del operador: una
# prueba con carpeta de usar y tirar creía estar aislada y estaba leyendo el
# fichero de verdad (el mismo fallo de hermeticidad que T36 cerró en
# `spotify.py`). `CONFIG_DIR` es la única fuente de verdad para «dónde vive la
# configuración» (comun/config.py), y sin la variable sigue valiendo `ROOT/config`
# —también con el bundle de PyInstaller, donde `ROOT` es la carpeta del .exe—, o
# sea que el comportamiento de siempre no cambia.
from backend.core.comun.config import CONFIG_DIR

CONFIG = CONFIG_DIR / "mcp_servers.json"

SKILL = {
    # QUÉ EFECTO tiene cada intent del enrutador (ARQ-03, task T8b): lo decide
    # `canales.EFECTOS` para permitir, preguntar o denegar; sin declarar, destructive.
    "effects": {
        "reload": "read",
        "list": "read",
        "call": "external_send",  # las de escritura ya preguntan (confirma)
    },
    # Los que YA preguntan con confirm.request antes de su efecto: `brain`
    # no los vuelve a preguntar (T8c).
    "confirma": ("call",),
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

# Los ajustes de la petición en curso. `_with_server` tiene que poder resolver los
# secretos del argv y su firma NO puede cambiar (los dobles de otras suites la
# llaman con tres argumentos), así que se guarda aquí, igual que hace
# `skills/hermes` con su `_SETTINGS`. Se escribe en cada `handle()`.
_SETTINGS: list = [None]

# Un hueco en `args`: `${NOMBRE}` (forma recomendada) o `{NOMBRE}`.
_RX_HUECO = re.compile(r"\$\{([^{}]*)\}|\{([^{}]*)\}")
# La forma de un NOMBRE de secreto, la misma que valida `ce90957` para los nombres
# de la tele: letras, dígitos y guión bajo. Nada de espacios, rutas ni `;`.
_RX_NOMBRE_SECRETO = re.compile(r"^[A-Za-z0-9_]+$")

# Lo que se pone en el sitio de un valor secreto que aparezca en un texto.
OCULTO = "[SECRETO-OCULTO]"


def _load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _ajustes(ctx) -> object:
    """Los ajustes de esta petición. Se guardan para `_with_server`."""
    _SETTINGS[0] = (ctx or {}).get("settings")
    return _SETTINGS[0]


# ───────────────────────── lista blanca y clasificación ──────────────────────
def _herramientas(cfg: dict) -> dict:
    """`nombre → ¿puede cambiar cosas?` — la lista blanca del servidor.

    Denegar por defecto, sin excepciones: sin `tools`, vacía, con una forma que no
    se entiende o con nombres que no son texto, el resultado es `{}` y ese
    servidor no puede llamar a NADA. No se consulta al servidor para «descubrir»
    qué se puede usar: la lista la escribe el operador, no el proceso que se va a
    arrancar.

    `True` significa ESCRITURA (pide «sí»). Solo un `false` booleano de verdad
    declara lectura: `"false"` (texto), `0` o un metadato que no se entiende se
    tratan como escritura. Una herramienta sin metadato también. Es la dirección
    del error que se puede deshacer: preguntar de más cuesta un «sí»."""
    crudo = cfg.get("tools")
    salida: dict = {}
    if isinstance(crudo, dict):
        for nombre, meta in crudo.items():
            if not isinstance(nombre, str) or not nombre.strip():
                continue
            if isinstance(meta, dict):
                valor = meta.get("escritura")
            elif isinstance(meta, bool):
                valor = meta
            else:
                valor = None                    # metadato que no se entiende
            salida[nombre.strip()] = (True if not isinstance(valor, bool) else valor)
    elif isinstance(crudo, list):
        # Forma corta: solo nombres. Sin metadato de escritura, TODAS piden «sí».
        for nombre in crudo:
            if isinstance(nombre, str) and nombre.strip():
                salida[nombre.strip()] = True
    return salida


def _rechazo_herramienta(server: str, tool: str, permitidas: dict) -> str:
    """La negativa honesta: qué, de quién, y dónde se permite.

    Nombra el servidor y la herramienta porque «esa herramienta no está
    permitida» a secas no dice qué arreglar; y nombra el archivo porque el ⚙ no
    tiene panel de MCP todavía (decir «está en ⚙» sería mandar al operador a una
    pantalla que no existe)."""
    nombres = ", ".join(sorted(permitidas)) or "ninguna"
    return (f"No he llamado a «{tool}» del conector «{server}»: esa herramienta no "
            f"está en su lista blanca, así que no he arrancado el servidor.\n"
            f"Permitidas ahora en «{server}»: {nombres}.\n"
            "Se permite en la configuración —`config/mcp_servers.json`, dentro de "
            f"ese servidor, en la lista «tools»— (el ⚙ todavía no tiene panel para "
            "MCP: se edita a mano y luego se dice «recarga los conectores»). "
            "Sin esa lista, o con la lista vacía, un conector no puede usar "
            "NINGUNA herramienta; y una herramienta de escritura además pregunta "
            "antes de ejecutarse.")


# ────────────────────────────── argumentos ───────────────────────────────────
def _argumentos(args_raw: str) -> tuple:
    """`(argumentos, error)`: los argumentos de la herramienta, del texto libre.

    ESTO NO ES EL ARGV. Lo que sale de aquí viaja como `arguments` del JSON-RPC
    (un objeto JSON), así que `..\\..\\Windows`, `D:\\x` o `;calc` son VALORES de
    un argumento y no sintaxis de nada: el sandbox de rutas es del servidor (el de
    filesystem, por ejemplo, solo enseña las carpetas de su argv). Lo que sí es
    cosa de nexus es no dejar que un texto se convierta en parte de la línea de
    órdenes, y eso se garantiza en `_argv()`: el argv sale SOLO de la config.

    ``{}`` es la forma más segura de leer un texto que parece JSON: si empieza por
    `{` tiene que ser un OBJETO JSON legible. Antes, un `{` roto se convertía en
    `{"query": "{roto"}` en silencio; ahora se dice y no se arranca nada, porque
    lo más probable es que el operador se haya equivocado y no que quisiera buscar
    una llave."""
    texto = (args_raw or "").strip()
    if not texto:
        return {}, ""
    if "\x00" in texto:
        return {}, ("los argumentos llevan un carácter nulo, y eso no se le manda a "
                    "un conector.")
    if texto.startswith("{") or texto.startswith("["):
        if texto.startswith("["):
            return {}, ("los argumentos de una herramienta MCP tienen que ser un "
                        "OBJETO JSON ({...}), no una lista ni un valor suelto.")
        try:
            valor = json.loads(texto)
        except Exception:
            return {}, ("eso empieza como JSON pero no se puede leer como JSON. "
                        "Pásame un objeto, por ejemplo {\"path\": \"D:\\\\nota.txt\"}, "
                        "o escribe el texto suelto sin llaves.")
        if not isinstance(valor, dict):
            return {}, ("los argumentos de una herramienta MCP tienen que ser un "
                        "OBJETO JSON ({...}), no una lista ni un valor suelto.")
        if any(not isinstance(k, str) for k in valor):
            return {}, "los nombres de los argumentos tienen que ser texto."
        return valor, ""
    clave = "path" if ("\\" in texto or "/" in texto) else "query"
    return {clave: texto}, ""


def _texto_argumentos(argumentos) -> str:
    """Los argumentos TAL CUAL se mandan (mismo `json.dumps` que el JSON-RPC).

    Se enseña esto y no un resumen en la confirmación: lo que el operador aprueba
    tiene que ser lo que se envía."""
    try:
        return json.dumps(argumentos, ensure_ascii=False)
    except Exception:                                      # noqa: BLE001
        return "{}"


class _HuecoNoValido(Exception):
    """Un `${…}` de la config que no es el nombre de un secreto."""


class _SecretoQueFalta(Exception):
    """Un `${NOMBRE}` válido cuyo valor no está en el almacén."""

    def __init__(self, nombre: str):
        super().__init__(nombre)
        self.nombre = nombre


def _valor_de_secreto(hueco, ajustes) -> str:
    nombre = (hueco.group(1) if hueco.group(1) is not None else hueco.group(2)) or ""
    if not _RX_NOMBRE_SECRETO.match(nombre):
        # No se repite el texto del hueco: si el operador pegó ahí una clave por
        # error, este mensaje acabaría publicándola.
        raise _HuecoNoValido()
    valor = ""
    try:
        valor = (ajustes.secret(nombre.lower()) or "") if ajustes is not None else ""
    except Exception:                                      # noqa: BLE001
        valor = ""
    if not valor:
        raise _SecretoQueFalta(nombre)
    return valor


def _argv(cfg: dict, ajustes) -> tuple:
    """`(argv, error)` — la línea de órdenes del servidor, y solo de la config.

    Nada de aquí sale del texto del operador: es `args` del archivo, con los
    huecos `${NOMBRE}` resueltos a valores del almacén de secretos. Las llaves
    están RESERVADAS para eso, así que un `args` con llaves que no se resuelven
    entero no arranca (mejor una negativa que un argumento a medias)."""
    piezas = cfg.get("args")
    if piezas is None:
        piezas = []
    if not isinstance(piezas, list):
        return [], "en la config, «args» tiene que ser una lista de textos."
    salida = []
    for i, pieza in enumerate(piezas):
        if not isinstance(pieza, str):
            return [], f"el argumento {i + 1} de «args» no es texto."
        try:
            resuelto = _RX_HUECO.sub(lambda m: _valor_de_secreto(m, ajustes), pieza)
        except _HuecoNoValido:
            return [], (f"el argumento {i + 1} de «args» tiene un hueco entre llaves "
                        f"que no es el nombre de un secreto (solo letras, dígitos y "
                        f"guión bajo: {_RX_NOMBRE_SECRETO.pattern}). En «args» las "
                        "llaves son solo para secretos, y no arranco con un texto que "
                        "no he podido validar.")
        except _SecretoQueFalta as exc:
            return [], (f"necesita el secreto «{exc.nombre}» y no está configurado. "
                        "Se guarda en config/secrets.json (⚙ → APIS) y en «args» se "
                        f"escribe «${{{exc.nombre}}}».")
        if "{" in resuelto or "}" in resuelto:
            return [], (f"el argumento {i + 1} de «args» deja llaves sin resolver: "
                        "en «args» las llaves son solo para secretos.")
        salida.append(resuelto)
    return salida, ""


def _nombres_de_secretos(cfg: dict) -> list:
    nombres = []
    piezas = cfg.get("args")
    for pieza in (piezas if isinstance(piezas, list) else []):
        if not isinstance(pieza, str):
            continue
        for m in _RX_HUECO.finditer(pieza):
            nombre = (m.group(1) if m.group(1) is not None else m.group(2)) or ""
            if _RX_NOMBRE_SECRETO.match(nombre):
                nombres.append(nombre)
    return nombres


def _sin_secretos(texto, cfg: dict, ajustes) -> str:
    """Enmascara en un texto los VALORES de los secretos que esta config usa.

    Se hace por valor y no por patrón porque el patrón no conoce la forma de todas
    las claves, y el caso real es concreto: un servidor lanzado por `npx` que
    falla imprime la línea de órdenes que él mismo recibió, y ahí va el token. Lo
    que no se puede es escupirlo en el chat."""
    salida = str(texto or "")
    for nombre in _nombres_de_secretos(cfg):
        try:
            valor = (ajustes.secret(nombre.lower()) or "") if ajustes is not None else ""
        except Exception:                                  # noqa: BLE001
            valor = ""
        if valor:
            salida = salida.replace(valor, OCULTO)
    return salida


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
    """Arranca el servidor con SU argv (config + secretos) y le hace `fn`.

    La firma no cambia (tres argumentos) porque es el punto que doblan las suites
    existentes; lo que cambia es de dónde sale el argv: de `_argv()`, nunca del
    texto del operador."""
    command = cfg.get("command")
    if not isinstance(command, str) or not command.strip():
        raise RuntimeError(f"el conector «{name}» no tiene «command» en la config")
    argv, error = _argv(cfg, _SETTINGS[0])
    if error:
        raise RuntimeError(error)
    client = MCPStdioClient(command, argv)
    try:
        async with client as c:
            return await fn(c)
    except FileNotFoundError:
        raise RuntimeError(f"«{command}» no está instalado (¿Node.js / npx?)")


def _pregunta_escritura(server: str, tool: str, argumentos) -> str:
    """La pregunta de una herramienta que puede cambiar cosas.

    Enseña servidor, herramienta y los argumentos EXACTOS. Se recorta con «…» si
    no cabe (`confirm.recortar`) y se dice que se ha recortado: nunca se resume,
    porque un resumen en una confirmación es enseñar otra cosa de la que se va a
    mandar."""
    from backend.core.comun import confirm as _cf
    cuerpo = _cf.recortar(_texto_argumentos(argumentos), 600)
    return ("El conector MCP «" + server + "» va a ejecutar la herramienta «" + tool
            + "», que puede cambiar cosas (la config la marca como herramienta de "
            "ESCRITURA). Le mandaré EXACTAMENTE estos argumentos:\n\n«" + cuerpo
            + "»\n\n¿Lo hago?")


async def _llamar(server: str, cfg: dict, tool: str, argumentos) -> dict:
    """Arranca el servidor, llama a la herramienta y devuelve el resultado como
    DATO. Es el único sitio de esta skill que habla con un conector."""
    # AI-03 / P2-4: lo que devuelve un servidor MCP lo ha escrito un tercero, no
    # nexus. Al chat le llega igual que siempre; lo que cambia es que `brain` marca
    # el turno y `llm` lo cerca como DATO en el prompt. Fuera del `try` a
    # propósito: un fallo de importación no es un conector roto.
    from backend.core.comun import datos_inyectados
    ajustes = _SETTINGS[0]
    try:
        result = await _with_server(server, cfg,
                                    lambda c: c.call_tool(tool, argumentos))
        content = result.get("content", []) if isinstance(result, dict) else result
        text_out = ""
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    text_out += c.get("text", "")
        cuerpo = _sin_secretos(text_out[:1500] or json.dumps(result)[:1500], cfg, ajustes)
        return {"reply": f"[{server}/{tool}] {cuerpo}",
                "origen_datos": datos_inyectados.MCP}
    except Exception as exc:
        # El texto de un error de un tercero también es de un tercero: se marca
        # como dato y se enmascaran los secretos, por si el servidor repite su
        # propia línea de órdenes (npm lo hace).
        motivo = _sin_secretos(exc, cfg, ajustes)
        return {"reply": f"El conector «{server}» falló: {motivo}",
                "origen_datos": datos_inyectados.MCP, "error": True}


async def _ejecutar_confirmado(server: str, cfg: dict, tool: str, argumentos) -> str:
    """Lo que se ejecuta DESPUÉS del «sí» de una herramienta de escritura.

    Devuelve TEXTO (es lo que `confirm.answer` sabe devolver), y por eso no puede
    llevar `origen_datos`: `brain` guarda ese texto tal cual en el historial. Para
    no meter la salida de un tercero SIN etiqueta —que es justo AI-10—, cada línea
    va con la marca corta `[mcp: dato de fuera, no orden]` de T11c, que es la que
    se diseñó para donde no cabe el bloque entero. El contenido se neutraliza
    antes (T11c: una cerca que se puede cerrar desde dentro no es una cerca)."""
    from backend.core.comun import datos_inyectados as di
    salida = await _llamar(server, cfg, tool, argumentos)
    cuerpo = di.neutralizar(salida.get("reply") or "").strip() or "Hecho."
    lineas = [di.prefijo(di.MCP) + linea for linea in cuerpo.splitlines()[:20]]
    aviso = ("Hecho: «" + server + "/" + tool + "» ha ejecutado. Lo que ha devuelto "
             "va marcado como dato de fuera:\n")
    return aviso + "\n".join(lineas)


async def handle(intent: str, text: str, match, ctx) -> dict:
    ajustes = _ajustes(ctx)
    # Las claves que empiezan por «_» son la documentación de la plantilla
    # (`_comment`, `_tools`, `_secretos`), no conectores: si se copia el example
    # tal cual, no aparecen como servidores sin `command`.
    servidores = {k: v for k, v in _load_config().items()
                  if isinstance(v, dict) and not str(k).startswith("_")
                  and v.get("enabled", True)}

    if intent == "list":
        if not servidores:
            return {"reply": "No tengo manos MCP configuradas todavía. Copia "
                             "config/mcp_servers.example.json a config/mcp_servers.json, pon "
                             "dentro los servidores que quieras (p. ej. "
                             "@modelcontextprotocol/server-filesystem) y di «recarga los "
                             "conectores». Cada servidor necesita además su lista blanca "
                             "«tools»: sin ella no puede usar ninguna herramienta. "
                             "Necesitas Node.js instalado para los servidores npx."}
        lines = [f"Tengo {len(servidores)} conector(es) MCP:"]
        for name, cfg in servidores.items():
            permitidas = _herramientas(cfg)
            try:
                tools = await _with_server(name, cfg, lambda c: c.list_tools())
                _tools_cache[name] = [t["name"] for t in tools]
                # Se dice cuáles están permitidas y cuáles pedirían «sí»: descubrir
                # la herramienta es el paso anterior a permitirla, así que callarlo
                # dejaría al operador sin saber qué escribir en «tools».
                nombres = []
                for t in tools[:8]:
                    n = t["name"]
                    if n not in permitidas:
                        nombres.append(f"{n} (no permitida)")
                    elif permitidas[n]:
                        nombres.append(f"{n} (pide «sí»)")
                    else:
                        nombres.append(n)
                lines.append(f"• {name}: {', '.join(nombres) or '(sin tools)'}")
            except Exception as exc:
                lines.append(f"• {name}: no conecta ({exc})")
        lines.append("\nÚsalos: «usa filesystem read_file con D:\\ruta\\archivo.txt».")
        return {"reply": "\n".join(lines)}

    if intent == "reload":
        _tools_cache.clear()
        return {"reply": f"Config MCP recargada: {len(servidores)} servidor(es). "
                         "Di «qué manos tienes» para ver las herramientas."}

    if intent == "call":
        server = match.group("server")
        tool = match.group("tool")
        args_raw = (match.group("args") or "").strip()
        if server not in servidores:
            disponibles = ", ".join(servidores) or "ninguno todavía"
            return {"reply": f"No tengo el conector «{server}» (tengo: {disponibles}). "
                             "Añádelo en config/mcp_servers.json —copia la plantilla "
                             "config/mcp_servers.example.json si aún no existe— y di "
                             "«recarga los conectores»."}
        cfg = servidores[server]
        # PUERTA 1: la lista blanca, ANTES de arrancar nada.
        permitidas = _herramientas(cfg)
        if tool not in permitidas:
            return {"reply": _rechazo_herramienta(server, tool, permitidas)}
        # PUERTA 2: los argumentos (JSON o texto suelto), validados.
        argumentos, error = _argumentos(args_raw)
        if error:
            return {"reply": f"No he llamado a «{tool}» del conector «{server}»: {error}"}
        # PUERTA 3: el argv, resuelto ANTES de preguntar. Si falta un secreto o un
        # hueco no vale, la negativa sale ahora y no después de un «sí».
        _, error = _argv(cfg, ajustes)
        if error:
            return {"reply": f"El conector «{server}» no puede arrancar: {error}"}
        # PUERTA 4: escritura → se arma y se espera el «sí» (nada arranca antes).
        if permitidas[tool]:
            from backend.core.comun import confirm as _cf
            texto_args = _texto_argumentos(argumentos)
            # Se dice «puede cambiar cosas» en vez de «es destructiva» porque la
            # clasificación que hay es lectura/escritura: prometer más detalle del
            # que el dato permite sería inventarse la garantía.
            pregunta = _cf.request(
                channel=(ctx or {}).get("channel", "pc"),
                kind="mcp_herramienta",
                summary=_pregunta_escritura(server, tool, argumentos),
                request_text=_cf.recortar(texto_args, 600),
                targets=[{"servidor": server, "herramienta": tool,
                          "argumentos": _cf.recortar(texto_args, 600)}],
                destructive=False,
                action=lambda: _ejecutar_confirmado(server, cfg, tool, argumentos),
                cancel_reply="Vale, no llamo a esa herramienta.")
            return {"reply": pregunta}
        return await _llamar(server, cfg, tool, argumentos)

    return {"reply": "Orden MCP no reconocida."}
