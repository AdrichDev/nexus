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

    # ESPERAR AL VEREDICTO, no un rato fijo. La primera versión de esta prueba
    # esperaba 2,5 s y leía el mensaje: en el PC de Adri (30/07/2026) Ollama SÍ
    # estaba sirviendo modelos, así que la prueba real tardaba más y se leía
    # «Probando «qwen3:8b» con una pregunta real…» — el mensaje intermedio. La
    # prueba fallaba por su propia prisa, no por un fallo del programa. Cargar un
    # modelo de 8B la primera vez puede irse a un minuto largo.
    try:
        page.wait_for_function(
            """() => { const e = document.querySelector('#ac-modelmsg');
                       return e && /^[✓✖]/.test(e.textContent.trim()); }""",
            timeout=150_000)
    except Exception:
        pass
    msg = page.eval_on_selector("#ac-modelmsg", "e => e.textContent.trim()")
    clase = page.eval_on_selector("#ac-modelmsg", "e => e.className")
    despues = page.evaluate("() => fetch('/api/config').then((r) => r.json())")
    badges2 = page.evaluate("""() => [...document.querySelectorAll('.ac-used')]
        .map((e) => ({txt: e.textContent.trim(), warn: e.classList.contains('warn')}))""")
    rt2 = page.evaluate("() => fetch('/api/llm/status').then((r) => r.json())")
    en_uso = [b for b in badges2 if not b["warn"]]

    f.check(msg.startswith(("✓", "✖")),
            f"el botón termina y da un veredicto, no se queda «probando» ({msg!r})")
    f.check("Probando" not in msg, "y no deja el mensaje intermedio colgado")

    # LO QUE DE VERDAD SE EXIGE es COHERENCIA, salga bien o salga mal. Que Ollama
    # esté o no en la máquina donde corre la prueba NO puede cambiar el veredicto:
    # cambia la rama, y cada rama tiene su invariante.
    if msg.startswith("✓"):
        f.check(rt2.get("active") is True,
                f"si dice PROBADO, el runtime lo confirma (active={rt2.get('active')})")
        f.check(rt2.get("provider") == "ollama" and rt2.get("verified") is True,
                f"y consta como modelo local verificado ({rt2.get('provider')})")
        f.check(bool(en_uso), f"y la tarjeta pasa a «EN USO» ({badges2})")
        f.check(despues.get("llm_provider") == "ollama",
                "y la configuración SÍ se guarda, porque el modelo respondió")
        f.check("ms" in msg, f"con el tiempo de respuesta como evidencia ({msg!r})")
    else:
        f.check(rt2.get("active") is not True or rt2.get("provider") != "ollama",
                f"si dice que NO, el runtime no lo da por activo ({rt2.get('provider')})")
        f.check(not en_uso, f"ninguna tarjeta se queda diciendo «EN USO» ({badges2})")
        f.check(antes.get("llm_provider") == despues.get("llm_provider"),
                f"y la configuración NO cambia por un intento fallido "
                f"({antes.get('llm_provider')} → {despues.get('llm_provider')})")
        f.check(len(msg) > 25, f"y explica el motivo, no solo una cruz ({msg!r})")
    # esto vale para las dos ramas: al usuario nunca le llega jerga interna
    for termino in ("hermes", "gateway", "endpoint", "localhost", "traceback",
                    "http 4", "http 5", "11434"):
        f.check(termino not in msg.lower(), f"sin jerga interna («{termino}»)")
    f.estado_despues = {"mensaje": msg, "clase": clase, "badges": badges2,
                        "runtime": rt2, "rama": "exito" if msg.startswith("✓") else "fallo"}
    f.shot("02-veredicto-coherente")

    # ── el desplegable clasifica con el criterio del servidor ────────────────
    cat = page.evaluate("() => fetch('/api/llm/models').then((r) => r.json())")
    f.check(isinstance(cat.get("items"), list),
            "el desplegable se llena con el catálogo ya clasificado del servidor")
    f.check(all(("usable" in i and "kind" in i) for i in cat.get("items", [])),
            "cada modelo llega con su tipo y si se puede usar")
    return f


def flujo_apis(page, base: str) -> Flow:
    """Configuración: el apartado APIS con todas las claves en un sitio."""
    f = Flow("config-apis", page, base)
    nav(page, "command")
    page.click("#btn-config")
    page.wait_for_selector("#config-body", timeout=8000)
    page.wait_for_timeout(700)

    leyendas = page.evaluate(
        "() => [...document.querySelectorAll('#config-body fieldset legend')].map(e => e.textContent.trim())")
    f.estado_antes = {"secciones": leyendas}
    f.check(any("APIS" in l for l in leyendas), f"existe el apartado APIS ({leyendas})")
    f.check(leyendas.index([l for l in leyendas if "APIS" in l][0]) <= 1,
            "y está arriba, no enterrado al final")

    # el apartado viene plegado: se abre pulsando su título, como los demás
    page.evaluate("""() => {
        const fs = [...document.querySelectorAll('#config-body fieldset')]
            .find(x => (x.querySelector('legend')||{}).textContent.includes('APIS'));
        fs.classList.remove('cfg-collapsed'); }""")
    page.wait_for_timeout(300)

    campos = page.evaluate("""() => [...document.querySelectorAll('[id^="api-"]')].map(e => ({
        id: e.id.replace('api-',''), tipo: e.type,
        visible: !!(e.offsetWidth || e.offsetHeight),
        valor: e.value }))""")
    f.check(len(campos) >= 15, f"se pintan todas las claves ({len(campos)} campos)")
    f.check(all(c["visible"] for c in campos), "y se ven de verdad en pantalla")
    claves = {c["id"] for c in campos}
    for k in ("openai_api_key", "anthropic_api_key", "gemini_api_key", "elevenlabs_api_key",
              "ig_access_token", "ig_business_account_id", "telegram_bot_token",
              "spotify_client_id", "homeassistant_token", "n8n_api_key"):
        f.check(k in claves, f"está el campo de {k}")
    secretas = [c for c in campos if c["id"].endswith(("_key", "_token", "_secret", "_url"))
                and c["id"] != "ig_business_account_id"]
    f.check(all(c["tipo"] == "password" for c in secretas),
            "las claves son campos de contraseña, no texto plano")
    f.check(all(c["valor"] == "" for c in secretas),
            "y NINGUNA muestra su valor, ni siquiera las guardadas")
    grupos = page.evaluate(
        "() => [...document.querySelectorAll('#config-body .api-grupo')].map(e => e.textContent.trim())")
    f.check(len(grupos) >= 5, f"están agrupadas por servicio ({grupos})")
    f.estado_despues = {"campos": len(campos), "grupos": grupos}
    f.shot("01-apartado-apis")

    # y las claves ya no andan sueltas por otras secciones
    viejos = page.evaluate("""() => ['m-gid','m-igtok','m-tg','m-n8nkey','m-hatok','m-spid']
        .filter(id => !!document.getElementById(id))""")
    f.check(not viejos, f"ningún campo de clave suelto en otras secciones ({viejos})")
    page.click("#m-cancel")
    return f


def flujo_contentos(page, base: str) -> Flow:
    """Content OS: colores por sección, sin negritas y todo desplegable."""
    f = Flow("content-os", page, base)
    nav(page, "contentos")
    page.wait_for_selector(".cos-sec", timeout=10000)
    page.wait_for_timeout(600)

    secs = page.evaluate("""() => [...document.querySelectorAll('.cos-sec')].map((s) => ({
        id: s.dataset.sec,
        titulo: (s.querySelector('.cos-sec-t')||{}).textContent,
        color: getComputedStyle(s.querySelector('.cos-sec-ic')).color,
        borde: getComputedStyle(s).borderLeftColor,
        abierta: s.classList.contains('abierta'),
        cuerpoVisible: !!(s.querySelector('.cos-sec-b').offsetHeight) }))""")
    f.estado_antes = {"secciones": [s["id"] for s in secs]}
    f.check(len(secs) >= 6, f"Content OS está partido en secciones ({len(secs)})")
    colores = {s["id"]: s["color"] for s in secs}
    f.check(len(set(colores.values())) == len(colores),
            f"cada sección tiene SU color, ninguno repetido ({len(set(colores.values()))} de {len(colores)})")
    vivos = 0
    for c in colores.values():
        n = [int(x) for x in re.findall(r"\d+", c)[:3]]
        if n and max(n) >= 200 and (max(n) - min(n)) >= 80:
            vivos += 1
    f.check(vivos >= 5, f"y son colores flúor, no grises ({vivos} de {len(colores)})")
    f.check(all(s["borde"] == s["color"] for s in secs),
            "el color se lleva también al borde de la tarjeta")
    f.shot("01-secciones")

    # ── plegar y desplegar de verdad ─────────────────────────────────────────
    abiertas = [s for s in secs if s["abierta"]]
    f.check(bool(abiertas), f"arranca con algo abierto, no todo cerrado ({len(abiertas)})")
    f.check(any(not s["abierta"] for s in secs),
            "y con algo cerrado: no es un muro con todo desplegado")
    for s in secs:
        f.check(s["cuerpoVisible"] == s["abierta"],
                f"«{s['id']}»: lo cerrado no ocupa sitio, lo abierto se ve")

    antes = page.evaluate("() => document.querySelector('.cos-sec[data-sec=\"inspira\"] .cos-sec-b').offsetHeight")
    page.click('.cos-sec[data-sec="inspira"] .cos-sec-h')
    page.wait_for_timeout(450)
    despues = page.evaluate("() => document.querySelector('.cos-sec[data-sec=\"inspira\"] .cos-sec-b').offsetHeight")
    f.check((antes == 0) != (despues == 0),
            f"al pulsar el título, la sección se abre o se cierra ({antes} → {despues})")
    aria = page.eval_on_selector('.cos-sec[data-sec="inspira"] .cos-sec-h', "e => e.getAttribute('aria-expanded')")
    f.check(aria in ("true", "false") and (aria == "true") == (despues > 0),
            "y lo dice también para lectores de pantalla")
    f.shot("02-desplegado")

    # ── el plan de contenido: cada publicación se abre ────────────────────────
    if not page.evaluate("() => document.querySelector('.cos-sec[data-sec=\"plan\"]').classList.contains('abierta')"):
        page.click('.cos-sec[data-sec="plan"] .cos-sec-h')
        page.wait_for_timeout(350)
    n_items = page.evaluate("() => document.querySelectorAll('.cos-cal-item').length")
    f.check(n_items > 0, f"el plan lista publicaciones ({n_items})")
    alto0 = page.evaluate("() => document.querySelector('.cos-cal-item .cos-cal-d').offsetHeight")
    page.click(".cos-cal-item .cos-cal-h")
    page.wait_for_timeout(400)
    alto1 = page.evaluate("() => document.querySelector('.cos-cal-item .cos-cal-d').offsetHeight")
    f.check(alto0 == 0 and alto1 > 0,
            f"y cada publicación se despliega con su ficha ({alto0} → {alto1})")
    detalle = page.eval_on_selector(".cos-cal-item .cos-cal-d", "e => e.innerText")
    f.check("CUÁNDO" in detalle.upper() and "ESTADO" in detalle.upper(),
            f"con cuándo, formato y estado ({detalle[:60]!r})")

    # ── se acabaron las negritas ─────────────────────────────────────────────
    negritas = page.evaluate("""() => [...document.querySelectorAll('.cos-secs b, .cos-secs strong')]
        .map((e) => e.textContent.trim()).filter(Boolean)""")
    f.check(len(negritas) <= 1, f"sin negritas repartidas por el contenido ({negritas})")
    f.estado_despues = {"colores": colores, "items_plan": n_items, "negritas": negritas}
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



def _siembra_analisis(sandbox) -> None:
    """Deja un analisis REAL en los datos desechables.

    Importante: no se escribe un JSON a mano. Se llama al motor de verdad
    (analisis.panel) con un reel de mentira, asi que lo que pinta el HUD en esta
    prueba es exactamente lo que pintaria con datos de Instagram. Un fixture
    escrito a mano probaria el CSS y nada mas."""
    import importlib.util
    sp = importlib.util.spec_from_file_location(
        "iganal", ROOT / "skills" / "instagram" / "analisis.py")
    A = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(A)

    def com(u, t, owner=False):
        return {"username": u, "text": t, "timestamp": "2026-07-30T10:00:00+0000",
                "is_from_owner": owner, "is_trigger": False, "matched_trigger": None}

    kw = ["QUIERO LA PLANTILLA"]
    flat = ([com("cuenta", "va para ti", owner=True)] * 5
            + [com(f"u{i}", "QUIERO LA PLANTILLA") for i in range(48)]
            + [com(f"t{i}", "plantila") for i in range(6)]
            + [com("p1", "¿qué micro usas para grabar?"),
               com("p2", "el micro ese de dónde lo has sacado"),
               com("p3", "cómo grabas con ese micro"),
               com("o1", "me parece caro para empezar"),
               com("o2", "muy caro la verdad"),
               com("c1", "me interesa para mi empresa, ¿cuál es el precio?")]
            + [com(f"e{i}", "🔥") for i in range(11)])
    clas = A.clasificar(flat, kw)
    sust = clas["cestas"]["sustantivo"]
    bundle = {"insights": {"reach": 24000, "total_interactions": 3100, "likes": 1900,
                           "saved": 640, "shares": 210, "follows": 34,
                           "profile_visits": 210, "ig_reels_avg_watch_time": 7400}}
    met = A.metricas(bundle, clas)
    ld = A.leads(clas, atendidos=48)
    du, ob = A.dudas(sust), A.objeciones(sust)
    panel = A.panel({
        "media": {"id": "R1", "permalink": "https://instagram.com/p/r1/",
                  "timestamp": "2026-07-30", "media_type": "REELS",
                  "caption": "Comenta PLANTILLA y te la mando"},
        "metricas": met, "clasificacion": clas, "leads": ld,
        "sentimiento": A.sentimiento({"positivo": 4, "neutral": 1, "friccion": 2}, len(sust)),
        "odio": A.cuenta_odio(sust), "dudas": du, "objeciones": ob,
        "cola": A.cola_editorial(du, ob, ld["calientes"]),
        "conversion": A.conversion(ld["unicos"], {"dm_enviados": 48, "dm_abiertos": 35,
                                                  "clics": 12}),
        "retencion": A.retencion(bundle), "distribucion": A.distribucion(bundle),
        "benchmark": A.benchmark({"reach": 24000, "saved": 640},
                                 [{"reach": 30000, "saved": 400},
                                  {"reach": 26000, "saved": 500}])})
    d = sandbox / "data" / "instagram"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ultimo_analisis.json").write_text(
        json.dumps({"cuando": "2026-07-30T12:00:00", "reels": [panel]},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    # Competencia: tambien generada por el motor de verdad. Un rival con diez
    # publicaciones normales y UN viral, que es el caso que rompe las medias.
    # Pies variados a proposito: con todos iguales solo saldria un tipo de gancho
    # y no se veria lo que importa, que es que los tipos con poca muestra van
    # marcados como «pocos datos» en vez de colar como conclusion.
    _PIES = [
        "\u00bfSab\u00edas que el pan sin gluten se congela? #singluten",
        "3 errores que arruinan tu masa madre\nComenta GUIA",
        "No uses harina de arroz sola. Nunca.",
        "Mi receta de bizcocho sin gluten",
        "\u00bfPor qu\u00e9 tu pan queda seco?",
        "Cuando empec\u00e9 no sab\u00eda ni amasar",
        "\u00bfCu\u00e1l es tu harina favorita?",
        "El truco para que suba la masa",
        "\u00bfHarina de trigo sarraceno o de arroz?",
        "5 panes sin gluten en 5 minutos",
        "\u00bfTe ha pasado que se desmorona?",
    ]

    def pub(i, v_, l_, c_, tipo="REELS", dia=None):
        return {"id": str(i), "caption": _PIES[i % len(_PIES)], "media_type": "VIDEO",
                "media_product_type": tipo,
                "permalink": f"https://instagram.com/p/{i}/",
                "timestamp": (dia or "2026-07-%02d" % (i % 28 + 1)) + "T10:00:00+0000",
                "view_count": v_, "like_count": l_, "comments_count": c_}
    rival = {"username": "rival", "name": "Rival", "biography": "hace lo mismo que tu",
             "followers_count": 50000, "media_count": 420,
             "media": [pub(i, 20000 + i * 900, 900 + i * 20, 40 + i) for i in range(10)]
                      + [pub(99, 900000, 40000, 3000, "FEED", "2026-07-20")]}
    mia = A.mi_perfil_publico("micuenta", 12000,
                              [pub(i, 9000 + i * 300, 400 + i * 10, 30 + i) for i in range(8)])
    comp = A.competencia([{"usuario": "rival", "datos": rival},
                          {"usuario": "personal",
                           "datos": {"error": "no se ha podido consultar esa cuenta",
                                     "motivos": ["la cuenta no es Business/Creator"]}}], mia)
    # la radiografía del rival, generada por el motor real
    sp3 = importlib.util.spec_from_file_location(
        "igintel_e2e", ROOT / "skills" / "instagram" / "inteligencia.py")
    Ie = importlib.util.module_from_spec(sp3)
    sp3.loader.exec_module(Ie)
    for c in comp.get("cuentas", []):
        c["radiografia"] = Ie.radiografia(c, rival["media"])
    pan = A.panel_competencia(comp)
    # el bloque de descubrimiento, tal cual lo deja el flujo real
    sp2 = importlib.util.spec_from_file_location(
        "igdesc_e2e", ROOT / "skills" / "instagram" / "descubrimiento.py")
    De = importlib.util.module_from_spec(sp2)
    sp2.loader.exec_module(De)
    nicho = De.deduce_nicho([{"caption": "Receta de pan sin gluten #singluten"},
                             {"caption": "Masa madre sin gluten #singluten"},
                             {"caption": "Bizcocho sin gluten #reposteria"}],
                            {"nicho": "cocina sin gluten"})
    pan["descubrimiento"] = {
        "nicho": nicho, "consultas": De.consultas(nicho),
        "candidatos": 7, "validados": 1,
        "descartados": [{"usuario": "personal",
                         "motivo": "la API no la puede consultar (cuenta personal)"},
                        {"usuario": "motosclasicas",
                         "motivo": "no se le ha encontrado ningun tema en comun"}]}
    (d / "competencia.json").write_text(
        json.dumps({"cuando": "2026-07-30T12:30:00", "panel": pan},
                   ensure_ascii=False, indent=1), encoding="utf-8")


def flujo_reels(page, base: str) -> Flow:
    """Reels: cada cifra con su origen, secciones de color y todo desplegable."""
    f = Flow("reels", page, base)
    nav(page, "reels")
    page.wait_for_selector(".ig-sec", timeout=10000)
    page.wait_for_timeout(600)

    secs = page.evaluate("""() => [...document.querySelectorAll('.ig-sec')].map((s) => ({
        id: s.dataset.sec,
        titulo: (s.querySelector('.cos-sec-t')||{}).textContent,
        color: getComputedStyle(s.querySelector('.cos-sec-ic')).color,
        borde: getComputedStyle(s).borderLeftColor,
        abierta: s.classList.contains('abierta'),
        metodo: !!s.querySelector('.ig-metodo'),
        cuerpoVisible: !!(s.querySelector('.cos-sec-b').offsetHeight) }))""")
    ids = [s["id"] for s in secs]
    f.estado_antes = {"secciones": ids}
    for q in ("numeros", "reparto", "leads", "conversion", "sentimiento", "dudas",
              "objeciones", "cola", "retencion", "distribucion", "benchmark"):
        f.check(q in ids, f"está la sección «{q}»")

    colores = {s["id"]: s["color"] for s in secs}
    f.check(len(set(colores.values())) == len(colores),
            f"cada sección tiene SU color, ninguno repetido ({len(set(colores.values()))} de {len(colores)})")
    vivos = 0
    for c in colores.values():
        n = [int(x) for x in re.findall(r"\d+", c)[:3]]
        if n and max(n) >= 200 and (max(n) - min(n)) >= 80:
            vivos += 1
    f.check(vivos >= len(colores) - 1, f"y son colores flúor, no grises ({vivos} de {len(colores)})")
    f.check(all(s["borde"] == s["color"] for s in secs), "el color llega al borde de la tarjeta")
    f.check(all(s["metodo"] for s in secs), "TODA sección explica cómo se calcula lo que enseña")
    f.shot("01-secciones")

    # ── lo que de verdad pidió Adri: de dónde sale cada número ───────────────
    kpis = page.evaluate("""() => [...document.querySelectorAll('.ig-kpi')].map((k) => ({
        metrica: (k.querySelector('.ig-kpi-m')||{}).textContent,
        valor: (k.querySelector('.ig-kpi-n')||{}).textContent,
        origen: (k.querySelector('.ig-fuente')||{}).textContent }))""")
    f.check(len(kpis) >= 7, f"están las métricas del reel ({len(kpis)})")
    f.check(all(k["origen"] and k["origen"].strip() for k in kpis),
            "NINGUNA métrica se enseña sin decir de dónde sale")
    f.check(any("Graph API" in (k["origen"] or "") for k in kpis), "unas vienen de la API")
    f.check(any("nexus" in (k["origen"] or "") for k in kpis), "y otras las calcula nexus")
    f.check(any("19" in (k["valor"] or "") or "24.000" in (k["valor"] or "") for k in kpis),
            f"las cifras salen formateadas ({[k['valor'] for k in kpis][:3]})")

    # ── la aritmética, a la vista ────────────────────────────────────────────
    suma = page.evaluate("""() => { const s = document.querySelector('.ig-suma');
        return s ? {txt: s.textContent.trim(), ok: s.classList.contains('ok')} : null; }""")
    f.check(bool(suma) and suma["ok"], f"el HUD certifica que la suma cuadra ({suma})")
    f.check("de" in (suma or {}).get("txt", ""), "diciendo cuántos de cuántos")

    # ── el embudo y lo que NO se sabe ────────────────────────────────────────
    conv = page.evaluate("""() => {
        const s = document.querySelector('.ig-sec[data-sec="conversion"]');
        if (!s) return null;
        if (!s.classList.contains('abierta')) s.querySelector('.cos-sec-h').click();
        return {pasos: s.querySelectorAll('.ig-paso').length,
                faltan: [...s.querySelectorAll('.ig-faltan li')].map(x => x.textContent.trim())}; }""")
    page.wait_for_timeout(300)
    f.check(conv and conv["pasos"] >= 3, f"el embudo pinta sus pasos ({conv})")
    f.check(conv and any("Convertidos" in x or "venta" in x.lower() for x in conv["faltan"]),
            f"y lo que no se ha registrado se declara, no se estima ({(conv or {}).get('faltan')})")

    # ── plegar y desplegar de verdad ─────────────────────────────────────────
    f.check(any(s["abierta"] for s in secs), "arranca con algo abierto")
    f.check(any(not s["abierta"] for s in secs), "y con algo cerrado: no es un muro")
    for s in secs:
        f.check(s["cuerpoVisible"] == s["abierta"],
                f"«{s['id']}»: lo cerrado no ocupa sitio, lo abierto se ve")
    antes = page.evaluate("() => document.querySelector('.ig-sec[data-sec=\"objeciones\"] .cos-sec-b').offsetHeight")
    page.click('.ig-sec[data-sec="objeciones"] .cos-sec-h')
    page.wait_for_timeout(450)
    despues = page.evaluate("() => document.querySelector('.ig-sec[data-sec=\"objeciones\"] .cos-sec-b').offsetHeight")
    f.check(despues != antes, f"al pulsar el título, la sección se abre o se cierra ({antes} → {despues})")
    f.check(page.evaluate("() => document.querySelector('.ig-sec[data-sec=\"objeciones\"] .cos-sec-h').getAttribute('aria-expanded')") in ("true", "false"),
            "y lo dice también para lectores de pantalla")
    f.shot("02-desplegado")

    # ── la cola editorial: cada idea con su ficha ────────────────────────────
    ideas = page.evaluate("""() => {
        const s = document.querySelector('.ig-sec[data-sec="cola"]');
        if (s && !s.classList.contains('abierta')) s.querySelector('.cos-sec-h').click();
        return document.querySelectorAll('.ig-idea').length; }""")
    page.wait_for_timeout(350)
    f.check(ideas >= 2, f"la cola editorial lista temas ({ideas})")
    alto0 = page.evaluate("() => document.querySelector('.ig-idea .cos-cal-d').offsetHeight")
    page.click('.ig-idea .cos-cal-h')
    page.wait_for_timeout(400)
    alto1 = page.evaluate("() => document.querySelector('.ig-idea .cos-cal-d').offsetHeight")
    f.check(alto1 > alto0, f"y cada idea se despliega con su gancho y quién la pidió ({alto0} → {alto1})")
    ficha = page.evaluate("() => document.querySelector('.ig-idea.abierta .cos-cal-d').textContent")
    f.check("Gancho" in ficha and "Por qué" in ficha, "con gancho y motivo, no solo el título")

    # ── sin negritas repartidas (la queja de Adri en Content OS) ─────────────
    negritas = page.evaluate("""() => [...document.querySelectorAll('#ig .cos-sec-b b, #ig .cos-sec-b strong')]
        .map(b => b.textContent.trim()).filter(t => t.length > 24)""")
    f.check(not negritas, f"sin negritas repartidas por el texto ({negritas[:3]})")
    f.shot("03-cola")
    return f


def _abre(page, sec: str) -> None:
    """Abre una seccion con un clic de verdad (no desde JS) si esta cerrada."""
    sel = f'.ig-sec[data-sec="{sec}"]'
    page.wait_for_selector(sel, timeout=8000)
    if "abierta" not in (page.get_attribute(sel, "class") or ""):
        page.click(sel + " .cos-sec-h")
    page.wait_for_timeout(400)


def flujo_competencia(page, base: str) -> Flow:
    """Competencia: cuentas ajenas, con lo que la API deja ver y lo que no."""
    f = Flow("competencia", page, base)
    nav(page, "reels")
    page.wait_for_selector(".ig-tab", timeout=10000)
    pestanas = page.evaluate("() => [...document.querySelectorAll('.ig-tab')].map(b => b.textContent.trim())")
    f.check(len(pestanas) == 2, f"la vista Reels tiene dos pestañas ({pestanas})")
    page.click('.ig-tab[data-tab="competencia"]')
    page.wait_for_selector('.ig-sec[data-sec="tabla"]', timeout=10000)
    page.wait_for_timeout(500)
    f.check(page.evaluate("() => document.querySelector('.ig-tab[data-tab=\"competencia\"]').classList.contains('activa')"),
            "al pulsarla se marca como activa")

    secs = page.evaluate("""() => [...document.querySelectorAll('.ig-sec')].map((s) => ({
        id: s.dataset.sec, metodo: !!s.querySelector('.ig-metodo'),
        color: getComputedStyle(s.querySelector('.cos-sec-ic')).color }))""")
    ids = [s["id"] for s in secs]
    for q in ("descubrimiento", "tabla", "brechas", "cuentas", "limites"):
        f.check(q in ids, f"está la sección «{q}»")

    # ── de dónde han salido las cuentas: el nicho, lo buscado y lo descartado ─
    _abre(page, "descubrimiento")
    des = page.evaluate("""() => {
        const s = document.querySelector('.ig-sec[data-sec="descubrimiento"]');
        return {tags: [...s.querySelectorAll('.ig-tag')].map(x => x.textContent.trim()),
                consultas: [...s.querySelectorAll('.ig-otra')].map(x => x.textContent.trim()),
                caidas: [...s.querySelectorAll('.ig-cita')].map(x => x.textContent.trim()),
                chips: [...s.querySelectorAll('.ig-chip')].map(x => x.textContent.trim())}; }""")
    f.check(any("gluten" in t for t in des["tags"]),
            f"enseña el nicho que ha deducido ({des['tags']})")
    f.check(len(des["consultas"]) >= 3,
            f"y qué ha buscado por internet ({len(des['consultas'])} búsquedas)")
    f.check(any("instagram" in q.lower() for q in des["consultas"]),
            "con las búsquedas reales, no un resumen")
    f.check(len(des["caidas"]) == 2, f"dice qué cuentas se han caído ({len(des['caidas'])})")
    f.check(any("personal" in c for c in des["caidas"]), "nombrando cuál")
    f.check(any("cuenta personal" in c for c in des["caidas"]), "y por qué se ha caído")
    f.check(any("confirmadas por Meta" in c for c in des["chips"]),
            f"y cuántas ha confirmado Meta ({des['chips']})")
    f.shot("00-descubrimiento")
    f.check(all(s["metodo"] for s in secs), "cada bloque explica su método")
    f.check(len({s["color"] for s in secs}) == len(secs), "cada uno con su color")

    # ── la tabla cara a cara ─────────────────────────────────────────────────
    tabla = page.evaluate("""() => {
        const t = document.querySelector('.ig-tabla'); if (!t) return null;
        return {cabeceras: [...t.querySelectorAll('thead th')].map(x => x.textContent.trim()),
                filas: [...t.querySelectorAll('tbody tr')].map(tr => tr.querySelector('th').textContent.trim()),
                tuyas: t.querySelectorAll('.tuya').length,
                lideres: t.querySelectorAll('td.lider').length}; }""")
    f.check(tabla and tabla["tuyas"] > 0, f"tu columna va marcada ({tabla})")
    f.check(any("TÚ" in c for c in (tabla or {}).get("cabeceras", [])), "y se ve que es la tuya")
    for q in ("Reproducciones", "Me gusta", "Comentarios", "Seguidores"):
        f.check(any(q in x for x in (tabla or {}).get("filas", [])),
                f"la tabla compara «{q}»")
    f.check((tabla or {}).get("lideres", 0) > 0, "y marca quién va por delante en cada fila")
    f.shot("01-cara-a-cara")

    # ── LO IMPORTANTE: lo que NO se puede ver, se ve ─────────────────────────
    _abre(page, "limites")
    lim = page.evaluate("""() => [...document.querySelectorAll('.ig-sec[data-sec="limites"] .ig-limite')]
        .map(x => ({que: (x.querySelector('.ig-limite-t')||{}).textContent.trim(),
                    por: (x.querySelector('.ig-limite-p')||{}).textContent.trim()}))""")
    f.check(page.is_visible('.ig-sec[data-sec="limites"] .ig-limite'),
            "el bloque de limites se abre con un clic, como cualquier otro")
    quees = " ".join(x["que"] for x in (lim or []))
    f.check("entimiento" in quees, f"dice que el sentimiento de sus comentarios NO se puede ver ({quees})")
    f.check("Compartidos" in quees, "ni los compartidos")
    f.check("Guardados" in quees, "ni los guardados")
    f.check("Alcance" in quees, "ni el alcance")
    f.check(all(x["por"] for x in (lim or [])), "y de cada uno, por qué")
    metodo_lim = page.evaluate("() => document.querySelector('.ig-sec[data-sec=\"limites\"] .ig-metodo').textContent")
    f.check("scraping" in metodo_lim, "dejando claro que no se saca por scraping")

    # ── la cuenta que no se ha podido consultar, tampoco se esconde ──────────
    aviso = page.evaluate("() => (document.querySelector('#ig .ig-aviso.mal')||{}).textContent || ''")
    f.check("personal" in aviso, f"la cuenta que no se ha podido consultar se nombra ({aviso[:70]})")

    # ── el detalle de cada cuenta se despliega ───────────────────────────────
    _abre(page, "cuentas")
    alto0 = page.evaluate("() => document.querySelector('.ig-cuenta .cos-cal-d').offsetHeight")
    page.click('.ig-cuenta .cos-cal-h')
    page.wait_for_timeout(400)
    alto1 = page.evaluate("() => document.querySelector('.ig-cuenta .cos-cal-d').offsetHeight")
    f.check(alto1 > alto0, f"cada cuenta se despliega con su ficha ({alto0} → {alto1})")
    ficha = page.evaluate("() => document.querySelector('.ig-cuenta.abierta .cos-cal-d').textContent")
    f.check("formato le funciona" in ficha, "con qué formato le funciona")
    f.check("más le ha funcionado" in ficha, "y sus publicaciones más vistas")
    # ── fase 3: qué está creando ─────────────────────────────────────────────
    f.check("Cómo engancha" in ficha, "cómo engancha")
    f.check("Cómo escribe" in ficha, "cómo escribe")
    f.check("Cuándo publica" in ficha, "cuándo publica")
    f.check("salido de la norma" in ficha, "y qué se le ha salido de su propia norma")
    radio = page.evaluate("""() => {
        const r = document.querySelector('.ig-cuenta.abierta .ig-radio');
        if (!r) return null;
        return {cabecera: (r.querySelector('.ig-radio-cab')||{}).textContent || '',
                hooks: [...r.querySelectorAll('.ig-hook')].map(h => ({
                    t: (h.querySelector('.ig-hook-t')||{}).textContent.trim(),
                    n: (h.querySelector('.ig-hook-n')||{}).textContent.trim(),
                    q: (h.querySelector('.ig-hook-q')||{}).textContent.trim()})),
                gana: r.querySelectorAll('.ig-hook-gana').length,
                pocos: r.querySelectorAll('.ig-hook-poco').length,
                picos: [...r.querySelectorAll('.ig-pico')].map(p => ({
                    m: (p.querySelector('.ig-pico-m')||{}).textContent.trim(),
                    cifras: (p.querySelector('.ig-pico-cifras')||{}).textContent.trim(),
                    g: (p.querySelector('.ig-pico-g')||{}).textContent.trim()})),
                notas: [...r.querySelectorAll('.ig-nota')].map(x => x.textContent.trim()),
                chips: [...r.querySelectorAll('.ig-chip span')].map(x => x.textContent.trim())}; }""")
    # ── lo que pidió Adri: que se entienda QUÉ es cada cosa ──────────────────
    f.check(radio and "@" in radio["cabecera"] and "analizadas" in radio["cabecera"],
            f"dice de quién es la ficha y sobre cuántas publicaciones ({(radio or {}).get('cabecera')})")
    f.check(radio and radio["hooks"], "lista los tipos de gancho")
    f.check(all(h["q"] for h in (radio or {}).get("hooks", [])),
            "y CADA UNO explica qué es, no solo cómo se llama")
    f.check(all(("publicaci" in h["n"]) and "mediana" in h["n"]
                for h in (radio or {}).get("hooks", [])),
            f"con cuántas publicaciones y de qué es el número ({(radio or {}).get('hooks', [{}])[0].get('n')})")
    f.check((radio or {}).get("gana") == 1, "y solo uno marcado como el que mejor le funciona")
    f.check((radio or {}).get("pocos", 0) > 0,
            f"marcando «pocos datos» donde no hay muestra ({(radio or {}).get('pocos')})")
    f.check(any("piden algo" in c for c in (radio or {}).get("chips", [])),
            f"las cifras de escritura dicen qué son ({(radio or {}).get('chips')})")
    picos = (radio or {}).get("picos", [])
    f.check(picos, "enseña los picos de rendimiento")
    f.check(all("@" in p["m"] and "-" in p["m"] for p in picos),
            f"cada uno con usuario y fecha ({picos[0]['m'] if picos else None})")
    f.check(all("me gusta" in p["cifras"] and "comentarios" in p["cifras"] for p in picos),
            f"y sus métricas completas ({picos[0]['cifras'] if picos else None})")
    f.check(all("gancho" in p["g"].lower() for p in picos),
            "y con qué gancho lo consiguió")
    try:
        page.locator(".ig-radio").first.scroll_into_view_if_needed()
        page.wait_for_timeout(350)
    except Exception:
        pass
    f.shot("03-radiografia")
    f.shot("02-cuentas")

    # ── la pestaña se recuerda, y se puede volver ───────────────────────────
    nav(page, "command")
    nav(page, "reels")
    page.wait_for_timeout(700)
    f.check(page.evaluate("() => !!document.querySelector('.ig-sec[data-sec=\"tabla\"]')"),
            "al volver, sigue en la pestaña donde estabas")
    page.click('.ig-tab[data-tab="mios"]')
    page.wait_for_selector('.ig-sec[data-sec="numeros"]', timeout=8000)
    f.check(True, "y se puede volver a tus reels")
    return f

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

    _siembra_analisis(sandbox)

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
                   flujo_cerebro, flujo_apis, flujo_contentos, flujo_reels, flujo_competencia):
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
