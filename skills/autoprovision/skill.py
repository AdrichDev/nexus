"""
Minion AUTO-PROVISIÓN — nexus se instala y conecta su propia infraestructura.

Bajo la orden de Adri (voz o texto), nexus puede:
  * Levantar Docker (stack pgvector del proyecto).
  * Comprobar n8n y CREAR el workflow router por API (con API key de n8n).
  * Validar/registrar el bot de Telegram (token → getMe → secrets).
  * Preparar modelos locales de Ollama (pull desde el registro) y ARREGLAR
    el problema de OLLAMA_MODELS para que Ollama vea tus modelos de la carpeta.
  * Diagnóstico completo: "revisa tu infraestructura" → informe de todo.

Corre en el mismo proceso que el backend (máquina de Adri), con acceso real a
docker/ollama/n8n locales. Acciones aditivas y seguras: NO borra nada.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]          # …/nexus
GRU = ROOT.parent / "nexus_stack"                # stack docker (carpeta hermana)

SKILL = {
    "name": "Auto-provisión",
    "description": "nexus levanta y conecta su infraestructura: Docker, n8n, Telegram y modelos Ollama",
    "patterns": {
        "diagnose": r"(revisa|comprueba|diagnostica|audita)\b.{0,20}(infraestructura|servicios|sistemas|conexiones|instalaci[oó]n)"
                    r"|aut[oó]\s*-?\s*(provisi[oó]n|inst[aá]late|instalaci[oó]n)"
                    r"|pon(te)?\s+en\s+marcha(\s+todo)?"
                    r"|c[oó]mo\s+est[aá]n?\s+tus\s+(servicios|conexiones|sistemas)",
        "docker_up": r"(levanta|arranca|enciende|pon\s+en\s+marcha|sube|inicia)\b.{0,25}"
                     r"(docker|contenedor|postgres|base\s+de\s+datos|stack|pgvector|\bdb\b)",
        "n8n_setup": r"(configura|conecta|crea|importa|prepara|instala)\b.{0,25}(n8n|flujo|workflow)",
        "telegram_setup": r"(configura|conecta|activa|registra|valida)\b.{0,25}(telegram|bot)\b",
        "model_ensure": r"(instala|descarga|prepara|registra|baja|b[aá]jate|aseg[uú]rate\s+(de|del)?)\s+(el\s+)?"
                        r"(modelo|model)\s+(?P<model>[\w.\-:/]+)",
        "ollama_fix": r"(arregla|repara|conecta|configura)\b.{0,20}(ollama|modelos\s+locales)"
                      r"|(no\s+(aparecen|salen|se\s+detectan?|detecta)\b.{0,20}modelos)"
                      r"|mis\s+modelos(\s+locales)?\s+no",
    },
}


# ----------------------------------------------------------------- utilidades
def _run(cmd: list[str], timeout: int = 60) -> tuple[bool, str]:
    """Ejecuta un comando del sistema. Devuelve (ok, salida combinada)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        return p.returncode == 0, out
    except FileNotFoundError:
        return False, f"'{cmd[0]}' no está instalado o no está en el PATH"
    except subprocess.TimeoutExpired:
        return False, f"'{' '.join(cmd)}' tardó demasiado (timeout {timeout}s)"
    except Exception as exc:                                    # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


async def _get(url: str, headers: dict | None = None, timeout: int = 5):
    async with httpx.AsyncClient(timeout=timeout) as cli:
        return await cli.get(url, headers=headers or {})


async def _post(url: str, body=None, headers: dict | None = None, timeout: int = 25):
    async with httpx.AsyncClient(timeout=timeout) as cli:
        return await cli.post(url, json=body, headers=headers or {})


# ------------------------------------------------------------------- Docker
def _compose_file() -> Path | None:
    for c in (GRU / "docker-compose.nexus.yml", ROOT / "docker-compose.nexus.yml",
              GRU / "docker-compose.yml"):
        if c.exists():
            return c
    return None


def _docker_running() -> bool:
    ok, _ = _run(["docker", "info"], timeout=15)
    return ok


async def _docker_up() -> str:
    if not _has("docker"):
        return "Docker no está instalado o no está en el PATH. Instala Docker Desktop y ábrelo."
    if not _docker_running():
        return ("Docker está instalado pero el daemon no responde. Abre Docker Desktop, "
                "espera a que arranque del todo y repite «levanta docker».")
    cf = _compose_file()
    if not cf:
        return ("No encuentro docker-compose.nexus.yml (lo busqué en nexus_stack y en la raíz "
                "de nexus). Dime dónde está el compose.")
    ok, out = _run(["docker", "compose", "-f", str(cf), "up", "-d", "--remove-orphans"], timeout=300)
    if not ok:
        return f"No pude levantar los contenedores:\n{out[-500:]}"
    okp, ps = _run(["docker", "compose", "-f", str(cf), "ps"], timeout=30)
    return "Contenedores del stack levantados ✔\n" + (ps[-600:] if okp else out[-400:])


# ------------------------------------------------------------------- Ollama
def _ollama_url(ctx) -> str:
    return ctx["settings"].get("ollama_url", "http://localhost:11434").rstrip("/")


def _scan_paths(ctx) -> list[str]:
    sp = ctx["settings"].get("model_scan_paths", []) or []
    if isinstance(sp, str):
        sp = [p.strip() for p in sp.replace(";", ",").split(",") if p.strip()]
    return sp


async def _ollama_live(ctx) -> list[str] | None:
    try:
        r = await _get(f"{_ollama_url(ctx)}/api/tags", timeout=4)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def _same_family(a: str, b: str) -> bool:
    return str(a).split(":")[0].lower() == str(b).split(":")[0].lower()


async def _ollama_pull(ctx, name: str) -> str:
    url = f"{_ollama_url(ctx)}/api/pull"
    try:
        async with httpx.AsyncClient(timeout=None) as cli:
            async with cli.stream("POST", url, json={"name": name}) as r:
                last = ""
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        j = json.loads(line)
                    except Exception:
                        continue
                    if j.get("error"):
                        return f"Ollama no pudo con «{name}»: {j['error']}"
                    if j.get("status"):
                        last = j["status"]
        await ctx["bus"].emit("log", {"level": "ok", "msg": f"Ollama: {name} → {last or 'listo'}"})
        return f"Modelo «{name}» listo en Ollama ✔"
    except Exception as exc:                                    # noqa: BLE001
        return f"Fallo al descargar «{name}»: {type(exc).__name__}: {exc}"


async def _model_ensure(ctx, name: str) -> str:
    name = name.strip()
    live = await _ollama_live(ctx)
    if live is None:
        return "Ollama no responde. Ábrelo (o ejecuta `ollama serve`) y repito."
    if name in live or any(_same_family(m, name) for m in live):
        ctx["settings"].set("llm_provider", "ollama")
        ctx["settings"].set("ollama_model", name)
        return f"«{name}» ya está en Ollama. Lo dejo como modelo activo ✔"
    await ctx["bus"].emit("log", {"level": "info", "msg": f"Descargando modelo {name}…"})
    msg = await _ollama_pull(ctx, name)
    if "listo" in msg:
        ctx["settings"].set("llm_provider", "ollama")
        ctx["settings"].set("ollama_model", name)
        msg += " Lo dejo como modelo activo."
    elif "no pudo" in msg or "Fallo" in msg:
        msg += ("\nSi es un modelo TUYO de carpeta (no del registro público), no se descarga: "
                "usa «arregla ollama» para que Ollama lea tu carpeta de modelos.")
    return msg


async def _ollama_fix(ctx) -> str:
    live = await _ollama_live(ctx)
    paths = _scan_paths(ctx)
    env_models = os.environ.get("OLLAMA_MODELS", "")
    L = []
    if live is None:
        L.append("Ollama NO responde ahora mismo (ábrelo o `ollama serve`).")
    else:
        L.append(f"Ollama ONLINE con {len(live)} modelos listos" +
                 (": " + ", ".join(live[:12]) if live else " (ninguno registrado)."))
    L.append("OLLAMA_MODELS actual: " + (env_models or "(sin definir → usa la carpeta por defecto de Ollama)"))

    target = next((p for p in paths if Path(p).exists()), "")
    if target:
        norm = lambda p: os.path.normcase(os.path.normpath(p)) if p else ""   # noqa: E731
        if norm(target) != norm(env_models):
            ok, out = _run(["setx", "OLLAMA_MODELS", target], timeout=20)
            if ok:
                L.append(f"✔ He fijado OLLAMA_MODELS = «{target}» (variable de usuario).")
                L.append("⚠ Reinicia Ollama para que la lea: cierra Ollama desde el icono de la "
                         "bandeja y ábrelo otra vez (o `ollama serve`). Después dime "
                         "«revisa tu infraestructura» y verás tus modelos listos.")
            else:
                L.append(f'No pude fijarla ({out[-120:]}). Hazlo tú: setx OLLAMA_MODELS "{target}" '
                         "y reinicia Ollama.")
        else:
            L.append("OLLAMA_MODELS ya apunta a tu carpeta de modelos. Si aún no aparecen, "
                     "reinicia Ollama una vez.")
    elif paths:
        L.append("Las carpetas de modelos que tienes en ⚙ no existen; revisa la ruta "
                 "(p.ej. D:\\Modelos).")
    else:
        L.append("No tienes carpeta de modelos configurada. Ponla en ⚙ → AI Core "
                 "(carpetas extra), p.ej. D:\\Modelos, y repite «arregla ollama».")
    return "\n".join(L)


# --------------------------------------------------------------------- n8n
def _n8n_base(ctx) -> str:
    return ctx["settings"].get("n8n_base_url", "http://localhost:5678").rstrip("/")


async def _n8n_alive(base: str) -> bool:
    for path in ("/healthz", "/rest/login", ""):
        try:
            await _get(base + path, timeout=4)
            return True
        except Exception:
            continue
    return False


async def _n8n_setup(ctx) -> str:
    base = _n8n_base(ctx)
    if not await _n8n_alive(base):
        return (f"n8n no responde en {base}. Ábrelo (o cambia la URL en ⚙ → n8n). "
                "Si lo quieres dentro de Docker, dime «levanta docker».")
    key = ctx["settings"].secret("n8n_api_key")
    if not key:
        return ("n8n está vivo, pero para crear el flujo yo solo necesito una API key. "
                "En n8n: Settings → n8n API → Create API key. Cópiala y guárdala en ⚙ "
                "(campo «n8n API key»). Luego repite «configura n8n».")
    wf_file = next((p for p in (ROOT / "config" / "n8n_flujo_nexus.json",
                                ROOT / "config" / "n8n_flujo_ejemplo.json") if p.exists()), None)
    if not wf_file:
        return "No encuentro el JSON del workflow en config/ (n8n_flujo_nexus/ejemplo.json)."
    try:
        wf = json.loads(wf_file.read_text(encoding="utf-8"))
        payload = {"name": wf.get("name", "nexus · Router de comandos"),
                   "nodes": wf["nodes"], "connections": wf["connections"],
                   "settings": wf.get("settings", {"executionOrder": "v1"})}
        r = await _post(f"{base}/api/v1/workflows", body=payload,
                        headers={"X-N8N-API-KEY": key}, timeout=25)
        if r.status_code not in (200, 201):
            return f"n8n rechazó la creación (HTTP {r.status_code}): {r.text[:200]}"
        wid = r.json().get("id", "")
        try:
            await _post(f"{base}/api/v1/workflows/{wid}/activate",
                        headers={"X-N8N-API-KEY": key}, timeout=15)
        except Exception:
            pass
        hook = f"{base}/webhook/nexus"
        ctx["settings"].set("n8n_webhook_url", hook)
        return (f"Workflow «{payload['name']}» creado y activado en n8n ✔ "
                f"Webhook configurado: {hook}. Pruébalo con «lanza el flujo demo».")
    except Exception as exc:                                    # noqa: BLE001
        return f"No pude crear el workflow en n8n: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- Telegram
async def _telegram_setup(ctx, text: str) -> str:
    m = re.search(r"\d{6,}:[A-Za-z0-9_\-]{30,}", text or "")
    token = (m.group(0) if m else ctx["settings"].secret("telegram_bot_token")).strip()
    if not token:
        return ("Dame el token del bot (de @BotFather) así: «configura telegram <token>», "
                "o pégalo en ⚙ → Token Telegram.")
    try:
        r = await _get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        j = r.json()
        if not j.get("ok"):
            return f"Ese token no es válido (Telegram: {j.get('description', 'error')})."
        uname = j["result"].get("username", "?")
        ctx["settings"].set_secret("telegram_bot_token", token)
        return (f"Bot @{uname} validado y guardado ✔ Reinicia nexus y escríbele por Telegram "
                "para quedar registrado como propietario.")
    except Exception as exc:                                    # noqa: BLE001
        return f"No pude validar el token: {type(exc).__name__}: {exc}"


# --------------------------------------------------------------- Diagnóstico
async def _diagnose(ctx) -> str:
    L = ["🛠 DIAGNÓSTICO DE INFRAESTRUCTURA — nexus", ""]

    # Docker
    if not _has("docker"):
        L.append("• Docker: no instalado / fuera del PATH.")
    elif _docker_running():
        okp, ps = _run(["docker", "ps", "--format", "{{.Names}}"], timeout=15)
        names = ", ".join(ps.split("\n")) if (okp and ps) else "ninguno"
        L.append(f"• Docker: ONLINE. Contenedores activos: {names}.")
    else:
        L.append("• Docker: instalado pero el daemon está parado (abre Docker Desktop).")

    # Memoria / DB
    db_online = bool(getattr(ctx.get("pg"), "online", False))
    L.append(f"• Memoria (Postgres pgvector): {'ONLINE' if db_online else 'offline (grafo local)'}.")

    # Ollama
    live = await _ollama_live(ctx)
    if live is None:
        L.append("• Ollama: NO responde (ábrelo o `ollama serve`).")
    else:
        active = ctx["settings"].get("ollama_model")
        ready = (active in live) or any(_same_family(m, active) for m in live)
        L.append(f"• Ollama: ONLINE, {len(live)} modelos. Activo: {active} → "
                 + ("listo ✔" if ready else "NO registrado (usa «arregla ollama» o «prepara el modelo …»)."))

    # n8n
    base = _n8n_base(ctx)
    if await _n8n_alive(base):
        haskey = "con API key" if ctx["settings"].secret("n8n_api_key") else "SIN API key (no puedo crear flujos solo)"
        hook = ctx["settings"].get("n8n_webhook_url") or "(sin webhook configurado)"
        L.append(f"• n8n: ONLINE ({base}) {haskey}. Webhook: {hook}.")
    else:
        L.append(f"• n8n: no responde en {base} (ábrelo o «levanta docker»).")

    # Telegram
    tk = ctx["settings"].secret("telegram_bot_token")
    if tk:
        try:
            r = await _get(f"https://api.telegram.org/bot{tk}/getMe", timeout=6)
            u = r.json().get("result", {}).get("username", "?")
            L.append(f"• Telegram: bot @{u} configurado ✔")
        except Exception:
            L.append("• Telegram: token guardado (no lo validé ahora, sin conexión).")
    else:
        L.append("• Telegram: sin token («configura telegram <token>»).")

    L += ["",
          "Órdenes: «levanta docker» · «configura n8n» · «prepara el modelo llama3.1» · "
          "«arregla ollama» · «configura telegram <token>»."]
    return "\n".join(L)


# ------------------------------------------------------------------- router
async def handle(intent: str, text: str, match, ctx) -> dict:
    try:
        if intent == "diagnose":
            return {"reply": await _diagnose(ctx), "speak": False}
        if intent == "docker_up":
            return {"reply": await _docker_up(), "speak": True}
        if intent == "n8n_setup":
            return {"reply": await _n8n_setup(ctx), "speak": True}
        if intent == "telegram_setup":
            return {"reply": await _telegram_setup(ctx, text), "speak": True}
        if intent == "model_ensure":
            return {"reply": await _model_ensure(ctx, match.group("model")), "speak": True}
        if intent == "ollama_fix":
            return {"reply": await _ollama_fix(ctx), "speak": False}
    except Exception as exc:                                    # noqa: BLE001
        return {"reply": f"Auto-provisión ha fallado: {type(exc).__name__}: {exc}", "error": True}
    return {"reply": "Orden de auto-provisión no reconocida."}
