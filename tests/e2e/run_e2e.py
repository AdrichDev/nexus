# -*- coding: utf-8 -*-
"""
nexus — PRUEBAS END-TO-END REALES con Playwright (specs v23, TAREAS 22 y 23).

Regla que impone este runner: una funcionalidad NO se declara terminada porque el
código compile, la API responda o el componente se renderice. Aquí se arranca
nexus DE VERDAD (uvicorn), se abre el HUD REAL en Chromium y se hacen los flujos
como los haría Adri, guardando EVIDENCIAS de cada uno.

Qué cubre hoy (P0 de las specs v23):
  * TAREAS + BORRADO: crear tareas, completarlas, pedir «borra las realizadas»,
    comprobar que PIDE CONFIRMACIÓN, cancelar, volver a pedirlo, confirmar,
    comprobar que solo se van las completadas y RESTAURARLAS desde la papelera.
  * ORQUESTACIÓN / MULTITAREA: lanzar trabajos, ver el indicador del sidebar
    (En curso → 2 → ✓ → !), comprobar que no hay ejecuciones duplicadas ni
    respuestas fantasma de trabajos cancelados.

Lo que todavía NO cubre (porque su funcionalidad aún no está hecha) queda listado
al final del informe como PENDIENTE — nunca como «pasado».

Uso:
    python tests/e2e/run_e2e.py              (desde la carpeta nexus)
    python tests/e2e/run_e2e.py --headed     (para verlo con tus ojos)

Requisitos (una sola vez):
    pip install playwright
    python -m playwright install chromium

Nunca toca tus datos: arranca nexus con NEXUS_DATA_DIR y NEXUS_CONFIG_DIR
apuntando a carpetas desechables dentro de data/e2e/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "e2e"
EVID = OUT / "evidencias"

_results: list[dict] = []
_t0 = time.time()


# ───────────────────────── utilidades ─────────────────────────

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def nav(page, view: str) -> None:
    """El HUD no tiene rutas por hash: se cambia de vista CLICANDO el sidebar.
    Recargar la página con #vista rompía la prueba (y perdía el WebSocket)."""
    page.click(f'#nav a[data-view="{view}"]')
    page.wait_for_timeout(700)


class Flow:
    """Un flujo de prueba con sus evidencias (specs v23 T22)."""

    def __init__(self, name: str, page, base: str):
        self.name = name
        self.page = page
        self.base = base
        self.steps: list[dict] = []
        self.shots: list[str] = []
        self.estado_antes = None
        self.estado_despues = None
        self.error = ""

    def check(self, cond: bool, msg: str) -> bool:
        self.steps.append({"ok": bool(cond), "msg": msg})
        print(("    ✔ " if cond else "    ✖ ") + msg)
        if not cond:
            self.shot(f"FALLO-{len(self.steps)}")
        return bool(cond)

    def shot(self, tag: str) -> None:
        EVID.mkdir(parents=True, exist_ok=True)
        f = EVID / f"{self.name}-{tag}.png"
        try:
            self.page.screenshot(path=str(f), full_page=True)
            self.shots.append(f.name)
        except Exception:
            pass

    @property
    def passed(self) -> bool:
        return not self.error and all(s["ok"] for s in self.steps) and bool(self.steps)


def _report(flows: list[Flow], console: list, network: list, pendientes: list) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data = {
        "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duracion_s": round(time.time() - _t0, 1),
        "flujos": [{"nombre": f.name, "resultado": "passed" if f.passed else "failed",
                    "pasos": f.steps, "capturas": f.shots, "error": f.error,
                    "estado_antes": f.estado_antes, "estado_despues": f.estado_despues}
                   for f in flows],
        "consola": console[-200:],
        "red": network[-200:],
        "pendientes": pendientes,
    }
    (OUT / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    ok = sum(1 for f in flows if f.passed)
    md = [f"# Pruebas end-to-end de nexus (Playwright)\n",
          f"_{data['generado']} · {data['duracion_s']} s · "
          f"**{ok}/{len(flows)} flujos passed**_\n"]
    for f in flows:
        md.append(f"\n## {f.name} — **{'passed' if f.passed else 'FAILED'}**\n")
        for s in f.steps:
            md.append(f"- {'✔' if s['ok'] else '✖'} {s['msg']}")
        if f.error:
            md.append(f"\n> Error: `{f.error}`")
        if f.estado_antes is not None:
            md.append(f"\n<details><summary>Estado antes / después</summary>\n\n"
                      f"```json\n{json.dumps(f.estado_antes, ensure_ascii=False)}\n"
                      f"{json.dumps(f.estado_despues, ensure_ascii=False)}\n```\n</details>")
        if f.shots:
            md.append("\nCapturas: " + ", ".join(f"`{s}`" for s in f.shots))
    md.append("\n## Pendiente de cubrir (su funcionalidad aún no está hecha)\n")
    md += [f"- {p}" for p in pendientes]
    (OUT / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nEvidencias en: {OUT}")
    return 0 if ok == len(flows) else 1


# ───────────────────────── flujos ─────────────────────────

def flujo_tareas(page, base: str) -> Flow:
    """Crear → completar → borrar las realizadas (con confirmación) → restaurar."""
    f = Flow("tareas-borrado-papelera", page, base)
    say = lambda t: _post(f"{base}/api/command", {"text": t})     # noqa: E731

    say("crea la tarea comprar pintura")
    say("crea la tarea llamar al cliente")
    say("crea la tarea enviar la factura")
    say("crea la tarea preparar el pedido")
    say("mueve enviar la factura a completadas")
    say("mueve preparar el pedido a completadas")

    board = _get(f"{base}/api/board")
    f.estado_antes = {k: [t["title"] for t in v] for k, v in board.items()}
    f.check(len(board["completada"]) == 2 and len(board["pendiente"]) == 2,
            "punto de partida: 2 completadas y 2 pendientes")

    nav(page, "tasks")
    f.shot("01-tablero")

    # 1) la orden del incidente: NO puede borrar sin preguntar
    r = say("limpia las tareas ya realizadas")
    reply = r.get("reply", "")
    f.check("confirm" in reply.lower(), "pide confirmación antes de borrar")
    f.check("2" in reply, "dice cuántas se van (2)")
    f.check("enviar la factura" in reply, "enumera las tareas afectadas")
    board = _get(f"{base}/api/board")
    f.check(sum(len(v) for v in board.values()) == 4,
            "mientras espera confirmación NO ha borrado nada")

    # 2) cancelar → sigue todo
    say("no")
    board = _get(f"{base}/api/board")
    f.check(sum(len(v) for v in board.values()) == 4, "al decir «no» no se borra nada")

    # 3) confirmar → solo las completadas
    say("borra las tareas completadas")
    r = say("sí")
    board = _get(f"{base}/api/board")
    f.check(len(board["completada"]) == 0, "tras confirmar, no quedan completadas")
    f.check(len(board["pendiente"]) == 2, "las PENDIENTES siguen ahí (el bug del 25/07)")
    f.check("papelera" in r.get("reply", "").lower(), "avisa de que están en la papelera")
    nav(page, "tasks")
    f.shot("02-tras-borrar")

    # 4) papelera y restauración
    pap = _get(f"{base}/api/board/trash")
    f.check(len(pap["items"]) == 2, "la papelera tiene las 2 borradas")
    f.check(all(i.get("previousStatus") == "completada" for i in pap["items"]),
            "la papelera recuerda su estado anterior")
    r = say("recupera las tareas borradas")
    board = _get(f"{base}/api/board")
    f.check(len(board["completada"]) == 2, "restauradas a su columna original")
    f.estado_despues = {k: [t["title"] for t in v] for k, v in board.items()}
    nav(page, "tasks")
    f.shot("03-restauradas")

    # 5) borrado por título, también con confirmación
    say("borra la tarea comprar pintura")
    board = _get(f"{base}/api/board")
    f.check(sum(len(v) for v in board.values()) == 4, "borrar por título tampoco borra sin confirmar")
    say("sí")
    board = _get(f"{base}/api/board")
    f.check(sum(len(v) for v in board.values()) == 3, "tras confirmar, borra solo esa")
    return f


def flujo_multitarea(page, base: str) -> Flow:
    """Indicador del sidebar y trabajos concurrentes, vistos en el HUD real."""
    f = Flow("multitarea-sidebar", page, base)
    badge = lambda: page.eval_on_selector("#nav-jobs", "e => e.textContent")  # noqa: E731

    f.estado_antes = _get(f"{base}/api/jobs")["counts"]
    nav(page, "jobs")
    _post(f"{base}/api/_e2e/job", {"seconds": 12, "title": "trabajo largo A"})
    page.wait_for_timeout(1200)
    f.check(badge().strip() == "En curso", f"1 trabajo → «En curso» (vi «{badge()}»)")
    f.shot("01-en-curso")

    _post(f"{base}/api/_e2e/job", {"seconds": 12, "title": "trabajo largo B"})
    page.wait_for_timeout(1200)
    f.check(badge().strip() == "2", f"2 trabajos → «2» (vi «{badge()}»)")
    f.shot("02-dos")

    # duplicado: la misma petición viva no se lanza dos veces
    dup = _post(f"{base}/api/jobs", {"text": "trabajo largo A"})
    f.check(dup.get("duplicate") is True, "un trabajo duplicado se detecta y se bloquea")

    # El operador se va a otra pantalla mientras trabajan (que es lo normal): al
    # terminar tiene que quedar la MARCA de revisar pendiente.
    nav(page, "command")
    page.wait_for_timeout(12000)
    f.check(badge().strip() == "✓", f"al terminar → «✓» sin revisar (vi «{badge()}»)")
    f.shot("03-terminado")

    nav(page, "jobs")
    page.wait_for_timeout(1000)
    f.check(badge().strip() == "", f"al revisar Multitarea el indicador se limpia (vi «{badge()}»)")
    txt = page.eval_on_selector("#job-list", "e => e.innerText")
    f.check("completado" in txt.lower(), "el panel muestra el estado real «completado»")
    f.check("salida.txt" in txt, "el panel muestra los archivos creados")
    f.shot("04-panel")

    # un fallo NO puede aparecer como completado, y avisa con «!»
    nav(page, "command")
    _post(f"{base}/api/_e2e/job", {"seconds": 1, "title": "trabajo que falla", "fail": True})
    page.wait_for_timeout(3000)
    f.check(badge().strip() == "!", f"un trabajo fallido → «!» (vi «{badge()}»)")
    f.shot("05-fallo")
    nav(page, "jobs")
    page.wait_for_timeout(800)
    txt = page.eval_on_selector("#job-list", "e => e.innerText")
    f.check("fallido" in txt.lower(), "se muestra como FALLIDO, no como completado")
    f.check("fallo provocado" in txt, "muestra el error real")
    cls = page.evaluate("""() => {
        const c = [...document.querySelectorAll('.jobc')]
          .find(e => e.innerText.includes('trabajo que falla'));
        return c ? c.className : 'sin-tarjeta'; }""")
    f.check("failed" in cls, f"la tarjeta de la fallida está marcada como failed (clase «{cls}»)")
    f.check("completed" not in cls, "y NUNCA como completada")
    f.estado_despues = _get(f"{base}/api/jobs")["counts"]
    return f


def flujo_orquestacion(page, base: str) -> Flow:
    """Una petición → una ejecución con su identificador; cancelar mata el resultado."""
    f = Flow("orquestacion-requestid", page, base)
    r = _post(f"{base}/api/jobs", {"text": "investiga proveedores de algodón"})
    f.check(bool(r.get("request_id")), "cada ejecución nace con su identificador único")
    jid = r.get("id")
    snap = _get(f"{base}/api/jobs")
    job = [j for j in snap["list"] if j["id"] == jid][0]
    f.estado_antes = {"status": job["status"], "agent": job["agent"],
                      "request_id": job["request_id"]}
    f.check(job["agent"] == "nexus", "se registra qué agente ejecuta")
    f.check(job["request"] == "investiga proveedores de algodón",
            "se guarda la petición original")

    _post(f"{base}/api/jobs/{jid}/cancel", {})
    page.wait_for_timeout(1200)
    snap = _get(f"{base}/api/jobs")
    job = [j for j in snap["list"] if j["id"] == jid][0]
    f.check(job["status"] == "cancelled", "el trabajo queda cancelado")
    f.check(not job["result"], "un trabajo cancelado NO publica resultado (anti-fantasma)")
    f.estado_despues = {"status": job["status"], "result": job["result"]}

    # consultar qué está ejecutándose
    _post(f"{base}/api/_e2e/job", {"seconds": 3, "title": "informe de mercado"})
    page.wait_for_timeout(700)
    r = _post(f"{base}/api/command", {"text": "qué tienes en marcha"})
    f.check("informe de mercado" in r.get("reply", ""),
            "el operador puede consultar qué tarea se está ejecutando")
    r = _post(f"{base}/api/command", {"text": "cancela los trabajos"})
    f.check("cancelad" in r.get("reply", "").lower(), "y puede cancelarlos")
    page.wait_for_timeout(600)
    f.check(_get(f"{base}/api/jobs")["counts"]["active"] == 0, "no queda nada activo")
    f.shot("01-final")
    return f


def flujo_sidebar(page, base: str) -> Flow:
    """Iconos del sidebar: color normal, activo y hover, en claro y en oscuro."""
    f = Flow("sidebar-iconos", page, base)
    nav(page, "command")
    datos = page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('#nav a').forEach((a) => {
            const ic = a.querySelector('svg.nav-ic');
            out.push({view: a.dataset.view, svg: !!ic,
                      stroke: ic ? getComputedStyle(ic).stroke : '',
                      color: getComputedStyle(a).color,
                      duro: ic ? /(#|rgb\()/.test(ic.getAttribute('stroke') || '') : true});
        });
        return out; }""")
    f.estado_antes = {"entradas": len(datos)}
    f.check(len(datos) >= 11, f"el sidebar tiene sus entradas ({len(datos)})")
    f.check(all(d["svg"] for d in datos), "todas las entradas usan SVG")
    f.check(not any(d["duro"] for d in datos), "ningún icono lleva un color incrustado")
    # v24: cada sección tiene su color FLÚOR propio, puesto desde el CSS
    colores = {d["view"]: d["stroke"] for d in datos if d["stroke"]}
    f.check(len(set(colores.values())) >= 10,
            f"cada sección luce un color distinto ({len(set(colores.values()))} colores)")
    vivos = 0
    for v, c in colores.items():
        nums = [int(x) for x in re.findall(r"\d+", c)[:3]]
        if nums and max(nums) >= 200 and (max(nums) - min(nums)) >= 90:
            vivos += 1
    f.check(vivos >= 10, f"y son colores vivos, de flúor ({vivos} de {len(colores)})")
    f.check(not any(d["view"] == "today" for d in datos),
            "la sección «Hoy» ya no está en el sidebar")
    f.shot("01-sidebar")

    inactivo = page.eval_on_selector('#nav a[data-view="tasks"] svg', "e => getComputedStyle(e).filter")
    nav(page, "tasks")
    activo = page.eval_on_selector('#nav a[data-view="tasks"] svg', "e => getComputedStyle(e).filter")
    f.check(activo != inactivo, "la sección activa se distingue (brilla más)")
    f.check("drop-shadow" in activo, f"y lo hace con halo de su color ({activo[:60]})")
    page.hover('#nav a[data-view="memory"]')
    page.wait_for_timeout(350)
    hover = page.eval_on_selector('#nav a[data-view="memory"] svg', "e => getComputedStyle(e).filter")
    normal = page.eval_on_selector('#nav a[data-view="calendar"] svg', "e => getComputedStyle(e).filter")
    f.check(hover != normal, "el hover también se nota")
    f.shot("02-activo-hover")

    # tema claro: los iconos siguen el color del texto, sea cual sea
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(400)
    claro = page.evaluate("""() => {
        const ic = document.querySelector('#nav a[data-view="memory"] svg.nav-ic');
        return getComputedStyle(ic).stroke; }""")
    f.check(claro == colores.get("memory"),
            "en tema claro conservan su color de sección")
    page.emulate_media(color_scheme="dark")
    f.shot("03-tema-claro")

    # el tiempo del header no puede tumbar el HUD aunque no haya red
    existe = page.evaluate("() => !!document.querySelector('#wx')")
    f.check(existe, "el componente del tiempo está en el header")
    f.check(page.evaluate("() => document.querySelectorAll('#nav a').length") >= 11,
            "y un fallo del servicio meteorológico no rompe el resto del HUD")
    f.estado_despues = {"activo": activo, "hover": hover}
    return f


def flujo_cerebro(page, base: str) -> Flow:
    """Núcleo IA: «EN USO» solo si el modelo ha contestado de verdad."""
    f = Flow("cerebro-modelo", page, base)
    nav(page, "aicore")
    page.wait_for_timeout(900)

    # ── LA INVARIANTE ────────────────────────────────────────────────────────
    # Lo que se rompía: la tarjeta cantaba «EN USO» mirando la preferencia
    # guardada, mientras el chat decía que ese modelo no existía. Ahora las dos
    # cosas salen del mismo sitio, así que TIENEN que coincidir.
    estado = page.evaluate("() => fetch('/api/llm/status').then((r) => r.json())")
    badges = page.evaluate("""() => [...document.querySelectorAll('.ac-used')]
        .map((e) => ({txt: e.textContent.trim(), warn: e.classList.contains('warn')}))""")
    f.estado_antes = {"status": estado, "badges": badges}
    en_uso = [b for b in badges if not b["warn"]]
    f.check(bool(estado) and "active" in estado, "el HUD consulta el estado real del cerebro")
    f.check(not en_uso or estado.get("active") is True,
            f"si algo dice «EN USO», el runtime lo confirma (badges={badges}, "
            f"activo={estado.get('active')})")
    f.check(all(b["warn"] for b in badges) or estado.get("active"),
            "y si no está probado, se ve como «SIN PROBAR»")
    f.shot("01-nucleo-ia")

    # ── EL CASO DE ADRI: elegir un modelo que no está servido ────────────────
    page.evaluate("""() => {
        const sel = document.querySelector('#ac-localmodel');
        sel.innerHTML = '<option value="qwen3:8b">qwen3:8b</option>';
        sel.value = 'qwen3:8b'; }""")
    antes = page.evaluate("() => fetch('/api/config').then((r) => r.json())")
    page.click("#ac-savemodel")
    page.wait_for_timeout(2500)
    msg = page.eval_on_selector("#ac-modelmsg", "e => e.textContent.trim()")
    clase = page.eval_on_selector("#ac-modelmsg", "e => e.className")
    despues = page.evaluate("() => fetch('/api/config').then((r) => r.json())")
    f.check(msg.startswith("✖") or "err" in clase,
            f"con Ollama apagado el botón NO dice «activo» ({msg!r})")
    f.check("ollama" in msg.lower(),
            f"dice qué hay que hacer, en cristiano ({msg!r})")
    for termino in ("hermes", "gateway", "endpoint", "localhost", "traceback",
                    "http 4", "http 5", "11434"):
        f.check(termino not in msg.lower(), f"sin jerga interna («{termino}»)")
    f.check(antes.get("llm_provider") == despues.get("llm_provider"),
            f"y la configuración NO cambia por un intento fallido "
            f"({antes.get('llm_provider')} → {despues.get('llm_provider')})")
    badges2 = page.evaluate("""() => [...document.querySelectorAll('.ac-used')]
        .map((e) => ({txt: e.textContent.trim(), warn: e.classList.contains('warn')}))""")
    f.check(not [b for b in badges2 if not b["warn"]],
            f"ninguna tarjeta se queda diciendo «EN USO» tras fallar ({badges2})")
    f.estado_despues = {"mensaje": msg, "badges": badges2}
    f.shot("02-fallo-coherente")

    # ── el desplegable clasifica con el criterio del servidor ────────────────
    cat = page.evaluate("() => fetch('/api/llm/models').then((r) => r.json())")
    f.check(isinstance(cat.get("items"), list),
            "el desplegable se llena con el catálogo ya clasificado del servidor")
    f.check(all(("usable" in i and "kind" in i) for i in cat.get("items", [])),
            "cada modelo llega con su tipo y si se puede usar")
    return f


PENDIENTES = [
    "Memoria (Engram): guardar una preferencia, reiniciar y comprobar que se aplica "
    "— pendiente de la TAREA 4 (Engram como memoria operativa).",
    "Voz: el filtro está hecho y probado en unitarias (tests/test_specs_v23_files.py); "
    "falta la comprobación e2e con audio real del navegador.",
    "Archivos: cubierto en unitarias (crear, leer .docx/.pdf, sobrescribir con "
    "confirmación, versionar y restaurar); falta el flujo por la interfaz.",
    "Hermes real: encargo de punta a punta contra su gateway — necesita Hermes "
    "instalado y arrancado en la máquina donde se ejecuten las pruebas.",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true", help="ver el navegador")
    ap.add_argument("--keep", action="store_true", help="no borrar los datos de la prueba")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Falta Playwright. Instálalo con:\n"
              "    pip install playwright\n"
              "    python -m playwright install chromium")
        return 2

    # Datos DESECHABLES: las pruebas jamás tocan el tablero real de Adri.
    sandbox = OUT / "sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox, ignore_errors=True)
    shutil.rmtree(EVID, ignore_errors=True)      # evidencias SOLO de esta ejecución
    (sandbox / "data").mkdir(parents=True, exist_ok=True)
    (sandbox / "config").mkdir(parents=True, exist_ok=True)
    # Config mínima: sin esto el servidor sirve el ASISTENTE DE INSTALACIÓN
    # (setup.html) en vez del HUD y no hay nada que probar. Modelo 'mock' para
    # que ninguna prueba dependa de un LLM externo.
    (sandbox / "config" / "settings.json").write_text(json.dumps({
        "setup_done": True, "operator_name": "Adri", "assistant_name": "nexus",
        "llm_provider": "mock", "llm_local": True, "voice_enabled": False,
        "tts_enabled": False, "open_mic": False, "wake_enabled": False,
        "hermes_auto": False, "hermes_autostart": False, "smart_router": False,
        "web_augment": False, "self_learning": False, "engram_enabled": False,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env.update({"NEXUS_DATA_DIR": str(sandbox / "data"),
                "NEXUS_CONFIG_DIR": str(sandbox / "config"),
                "NEXUS_E2E": "1", "PYTHONUTF8": "1"})
    srv_log = open(OUT / "servidor.log", "w", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app",
                            "--host", "127.0.0.1", "--port", str(port),
                            "--log-level", "warning"],
                           cwd=str(ROOT), env=env, stdout=srv_log, stderr=srv_log)
    print(f"· Arrancando nexus REAL en {base} (datos desechables en {sandbox})")
    for _ in range(90):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(base + "/api/jobs", timeout=2).read()
            break
        except (urllib.error.URLError, OSError):
            continue
    else:
        srv.kill()
        print("✖ nexus no ha llegado a arrancar. Mira data/e2e/servidor.log")
        return 1

    console: list = []
    network: list = []
    flows: list[Flow] = []
    with sync_playwright() as pw:
        # Sin proxy: el HUD es 127.0.0.1 y un proxy corporativo/del entorno lo
        # tumbaría con ERR_TUNNEL_CONNECTION_FAILED.
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--proxy-server=direct://", "--proxy-bypass-list=*"])
        ctx = browser.new_context(viewport={"width": 1500, "height": 950})
        ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        page.on("console", lambda m: console.append({"type": m.type, "text": m.text[:300]}))
        page.on("requestfinished", lambda r: network.append(
            {"method": r.method, "url": r.url.replace(base, ""), "ok": True})
            if "/api/" in r.url else None)
        page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": str(e)[:300]}))
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        if any("WebSocket" in c["text"] for c in console):
            print("  ⚠ El WebSocket del HUD no conecta (¿falta el paquete «websockets»?).\n"
                  "    Las pruebas siguen: el HUD también refresca por API, pero en vivo\n"
                  "    el indicador tardaría más en pintarse.")

        for fn in (flujo_tareas, flujo_multitarea, flujo_orquestacion, flujo_sidebar,
                   flujo_cerebro):
            print(f"\n▸ Flujo: {fn.__doc__.splitlines()[0]}")
            try:
                flows.append(fn(page, base))
            except Exception as exc:                      # noqa: BLE001
                f = Flow(fn.__name__, page, base)
                f.error = f"{type(exc).__name__}: {exc}"
                f.steps.append({"ok": False, "msg": f.error})
                f.shot("EXCEPCION")
                flows.append(f)
                print("    ✖ EXCEPCIÓN:", f.error)

        EVID.mkdir(parents=True, exist_ok=True)
        ctx.tracing.stop(path=str(OUT / "trace.zip"))
        ctx.close()
        browser.close()

    srv.terminate()
    try:
        srv.wait(timeout=10)
    except Exception:
        srv.kill()
    srv_log.close()
    (OUT / "consola.json").write_text(json.dumps(console, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    (OUT / "red.json").write_text(json.dumps(network, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    if not args.keep:
        shutil.rmtree(sandbox, ignore_errors=True)
    code = _report(flows, console, network, PENDIENTES)
    ok = sum(1 for f in flows if f.passed)
    print(f"\n{'='*54}\nRESULTADO E2E: {ok}/{len(flows)} flujos passed"
          f" — {'TODO VERDE ✔' if code == 0 else 'HAY FALLOS ✖'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
