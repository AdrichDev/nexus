"""P0-05 probe: task and file journeys driven through real HUD controls. Container only.

Tasks: typed in the chat input, moved with the card arrow buttons, deleted with the trash
button + inline confirmation, restored from the trash via chat. Files: created, updated,
versioned and restored by typing commands in the chat; disk state is asserted directly.
Everything lives in a disposable data dir; SANDBOX permission is enforced and probed.
"""
from __future__ import annotations

import json, os, shutil, socket, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = Path(os.environ.get("P05_DIR", "/work/d"))
SB = D / "data" / "sandbox"
RES: list[tuple[bool, str]] = []


def check(ok, msg):
    RES.append((bool(ok), msg)); print(("  OK  " if ok else "  FAIL ") + msg, flush=True)


def api(base, path, body=None):
    r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                               {"Content-Type": "application/json"} if body is not None else {})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())


def main() -> int:
    from playwright.sync_api import sync_playwright
    shutil.rmtree(D, ignore_errors=True)
    (D / "data").mkdir(parents=True); (D / "config").mkdir(parents=True)
    json.dump({"setup_done": True, "operator_name": "Adri", "llm_provider": "mock", "llm_local": True,
               "voice_enabled": False, "tts_enabled": False, "open_mic": False, "wake_enabled": False,
               "hermes_auto": False, "hermes_autostart": False, "smart_router": False,
               "web_augment": False, "self_learning": False, "engram_enabled": False,
               "perm_files": "sandbox"}, open(D / "config" / "settings.json", "w"))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, NEXUS_DATA_DIR=str(D / "data"), NEXUS_CONFIG_DIR=str(D / "config"),
               NEXUS_E2E="1", PYTHONUTF8="1")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1",
                            "--port", str(port), "--log-level", "warning"], cwd=ROOT, env=env)
    try:
        for _ in range(90):
            try: api(base, "/api/jobs"); break
            except Exception: time.sleep(1)
        with sync_playwright() as pw:
            br = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage",
                                          "--proxy-server=direct://", "--proxy-bypass-list=*"])
            page = br.new_context(viewport={"width": 1500, "height": 950}).new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)[:200]))
            page.goto(base, wait_until="domcontentloaded"); page.wait_for_timeout(2000)

            def nav(v):
                page.click(f'#nav a[data-view="{v}"]'); page.wait_for_timeout(700)

            def say(text):
                nav("command")
                last = lambda: (page.locator("#cc-chat .ccm.ai").last.inner_text()
                                if page.locator("#cc-chat .ccm.ai").count() else "")
                before = last()
                page.fill("#cc-chat-input", text); page.click("#cc-chat-send")
                page.wait_for_function(
                    "b => { const e=[...document.querySelectorAll('#cc-chat .ccm.ai')].pop();"
                    " return e && e.innerText !== b; }", arg=before, timeout=30000)
                return last()

            FINDINGS: list[str] = []

            def ui_has(col, title):
                return page.locator(f'.kcol[data-s="{col}"] .kcard', has_text=title).count() == 1

            def stale_probe(col, title, label):
                """A task changed by a chat command must be visible in the Tareas view without reloading."""
                nav("tasks"); page.wait_for_timeout(800)
                ok = ui_has(col, title)
                if not ok:
                    page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(2500); nav("tasks")
                    FINDINGS.append(f"{label}: only visible after a page reload: {ui_has(col, title)}")
                    print("  FINDING", FINDINGS[-1])
                check(ok, f"{label}: visible in the Tareas view without reloading")

            # ---------------- tasks ----------------
            T = "P05 pintar valla"
            r = say(f"crea la tarea {T}")
            stale_probe("pendiente", T, "task created by chat")
            check(any(t["title"] == T for t in api(base, "/api/board")["pendiente"]), "API board agrees (pendiente)")
            for _ in range(3):
                page.locator('.kcard', has_text=T).locator('.mv button:has-text("▶")').click()
                page.wait_for_timeout(500)
            check(page.locator('.kcol[data-s="completada"] .kcard', has_text=T).count() == 1,
                  "3 arrow clicks move it to DONE in the UI")
            check(any(t["title"] == T for t in api(base, "/api/board")["completada"]), "API board agrees (completada)")
            page.locator('.kcard', has_text=T).locator(".kdel").click()
            check(page.locator('.kcard', has_text=T).locator(".kconfirm").count() == 1, "trash button asks inline confirmation")
            page.locator('.kcard', has_text=T).locator(".kno").click(); page.wait_for_timeout(500)
            check(any(t["title"] == T for t in api(base, "/api/board")["completada"]), "answering No deletes nothing")
            page.locator('.kcard', has_text=T).locator(".kdel").click()
            page.locator('.kcard', has_text=T).locator(".kyes").click(); page.wait_for_timeout(800)
            check(page.locator('.kcard', has_text=T).count() == 0, "after confirming the card leaves the UI")
            board = api(base, "/api/board")
            check(not any(t["title"] == T for v in board.values() for t in v), "API board no longer has it")
            trash = json.dumps(api(base, "/api/board/trash"), ensure_ascii=False)
            check(T in trash, "task is in the trash (logical delete)")
            r = say(f"restaura la tarea {T}")
            print("  info restore reply:", r[:160].replace("\n", " "))
            stale_probe("completada", T, "task restored from trash by chat")
            check(any(t["title"] == T for t in api(base, "/api/board")["completada"]), "API board agrees after restore")

            # ---------------- files ----------------
            SB.mkdir(parents=True, exist_ok=True)
            f = SB / "p05.md"
            r = say(f"crea el archivo p05.md en {SB} que diga version uno")
            check("creado" in r.lower() and f.exists() and f.read_text().strip() == "version uno",
                  "file created from chat; disk content is 'version uno'")
            r = say(f"actualiza el archivo {f} con el texto version dos")
            check(f.read_text().strip() == "version dos" and "versi" in r.lower(),
                  "file updated from chat; disk is 'version dos' and previous version saved")
            r = say(f"qué versiones tienes de {f}")
            check(".bak" in r or "p05." in r, "versions listed in chat")
            vd = D / "data" / "file_versions"
            baks = [x for x in vd.rglob("*") if x.is_file()] if vd.exists() else []
            check(len(baks) >= 1, f"a version file exists on disk under file_versions ({len(baks)})")
            r = say(f"restaura el archivo {f}")
            check("sí" in r.lower() and f.read_text().strip() == "version dos", "restore asks confirmation first; disk unchanged")
            r = say("sí")
            check(f.read_text().strip() == "version uno", "after 'sí' disk is back to 'version uno'")
            r = say("crea el archivo p05_fuera.md en /etc que diga hola")
            check(not Path("/etc/p05_fuera.md").exists() and "permiso" in r.lower(),
                  "write outside the sandbox is refused and nothing is written")
            # Chat window must never cut what the AI returns (was sliced to 220 chars).
            long_reply = "\n".join(f"Parrafo {i:02d}: " + "texto de la respuesta de la IA " * 8 for i in range(25)) + "\nFINAL_DEL_TEXTO"
            nav("command")
            api(base, "/api/_e2e/chat", {"user": "pregunta larga", "reply": long_reply})
            page.wait_for_function("() => [...document.querySelectorAll('#cc-chat .ccm.ai')].some(e => e.innerText.includes('Parrafo 00'))", timeout=15000)
            shown = page.locator("#cc-chat .ccm.ai").last.inner_text()
            check(len(long_reply) > 5000 and "FINAL_DEL_TEXTO" in shown and "Parrafo 24" in shown,
                  f"compact chat holds the whole {len(long_reply)}-char reply, last words included ({len(shown)} shown)")
            box = page.evaluate("() => { const e=document.querySelector('#cc-chat'); const r=e.getBoundingClientRect();"
                                " return {h:Math.round(r.height), sh:e.scrollHeight, oy:getComputedStyle(e).overflowY}; }")
            check(box["h"] >= 240 and box["oy"] in ("auto", "scroll") and box["sh"] > box["h"],
                  f"chat window is tall, and scrolls to reach the rest ({box})")
            page.evaluate("() => { const e=document.querySelector('#cc-chat'); e.scrollTop = e.scrollHeight; }")
            vis = page.evaluate("() => { const e=document.querySelector('#cc-chat'); const last=[...e.querySelectorAll('.ccm.ai')].pop();"
                                " const a=last.getBoundingClientRect(), b=e.getBoundingClientRect(); return a.bottom <= b.bottom + 2; }")
            check(vis, "scrolled to the bottom, the end of the reply is inside the window")
            page.click('.cc-chat-panel .link[data-view="chat"]'); page.wait_for_timeout(700)
            full = page.locator("#chat-log .msg.ai").last.inner_text()
            check("FINAL_DEL_TEXTO" in full and "Parrafo 24" in full, "full chat view also shows the whole reply")
            check(not errs, f"no page errors ({errs[:2]})")
            print("  FINDINGS:", len(FINDINGS))
            br.close()
    finally:
        srv.terminate()
        try: srv.wait(timeout=20)
        except Exception: srv.kill()
        shutil.rmtree(D, ignore_errors=True)
    check(not D.exists(), "cleanup: disposable data dir removed")
    bad = [m for ok, m in RES if not ok]
    print(f"\nP0-05 probe: {len(RES) - len(bad)} OK, {len(bad)} FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
