# -*- coding: utf-8 -*-
"""Tests de las specs v23 (FASE 1: errores críticos) — contra el CÓDIGO REAL.

Reproducen el incidente del 25/07/2026 («limpia las tareas ya realizadas» vació
las 15 tareas del tablero) y comprueban que ya no puede repetirse:

  T1  confirmación obligatoria antes de cualquier acción destructiva
      (backend/core/confirm.py + integración en brain + skill tasks_board)
  T2  eliminación selectiva por ESTADO REAL (board.select / clear_scope)
  T3  papelera y restauración (board.trash / restore / purge_trash)
  T24 auditoría de las operaciones destructivas (backend/core/audit.py)

Ejecutar:  python tests/test_specs_v23.py    (desde la carpeta nexus)
"""
import ast
import asyncio
import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backend.core.dominio.board as board          # noqa: E402
import backend.core.comun.confirm as confirm      # noqa: E402
import backend.core.comun.audit as audit          # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="nexus_v21_"))
board.BOARD_FILE = _TMP / "board.json"
board.TRASH_FILE = _TMP / "board_trash.json"
audit.AUDIT_FILE = _TMP / "logs" / "audit.jsonl"


def _reset(n_pend=3, n_prog=2, n_comp=4):
    """Tablero de laboratorio: 3 pendientes + 2 en progreso + 4 completadas."""
    board._save([])
    board._save_trash([])
    confirm.clear()
    for i in range(n_pend):
        board.add_task(f"pendiente {i+1}")
    for i in range(n_prog):
        t = board.add_task(f"en curso {i+1}")
        board.move_task(t["id"], "progreso")
    for i in range(n_comp):
        t = board.add_task(f"hecha {i+1}")
        board.move_task(t["id"], "completada")


def _skill():
    spec = importlib.util.spec_from_file_location(
        "sk_tasks_board", os.path.join(ROOT, "skills", "tasks_board", "skill.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _route(mod, text):
    """Devuelve (intent, match) del PRIMER patrón que casa, en orden de declaración."""
    for intent, rx in mod.SKILL["patterns"].items():
        m = re.search(rx, text, re.IGNORECASE)
        if m:
            return intent, m
    return None, None


# ══════════════ T2: selección por estado real ══════════════

def test_select_por_estado():
    _reset()
    check(len(board.select("completadas")) == 4, "select(completadas) = 4")
    check(all(t["state"] == "completada" for t in board.select("completadas")),
          "select(completadas) solo trae completadas")
    check(len(board.select("pendientes")) == 3, "select(pendientes) = 3")
    check(len(board.select("activas")) == 5, "select(activas) = pendientes+progreso+revisión")
    check(len(board.select("todas")) == 9, "select(todas) = 9")
    c = board.counts()
    check((c["total"], c["completada"], c["pendiente"], c["progreso"]) == (9, 4, 3, 2),
          f"counts() correcto ({c})")
    check(board.status_of({"state": "completada"}) == "completed",
          "status_of traduce a la nomenclatura de las specs")


def test_clear_completed_no_toca_lo_vivo():
    """EL BUG DEL 25/07: borrar las realizadas NO puede llevarse las pendientes."""
    _reset()
    n = board.clear_completed(reason="test")
    check(n == 4, f"clear_completed borró 4 (borró {n})")
    quedan = board._load()
    check(len(quedan) == 5, f"quedan 5 vivas (quedan {len(quedan)})")
    check(all(t["state"] != "completada" for t in quedan), "no queda ninguna completada")
    check({t["state"] for t in quedan} == {"pendiente", "progreso"},
          "las pendientes y en progreso siguen intactas")
    # y el ámbito por nombre hace lo mismo
    _reset()
    check(board.clear_scope("completadas", reason="test") == 4, "clear_scope(completadas) = 4")
    check(len(board._load()) == 5, "clear_scope(completadas) deja 5 vivas")


def test_alias_realizadas_es_completada():
    check(board.STATE_ALIAS.get("realizadas") == "completada",
          "alias: realizadas → completada")
    for w in ("finalizadas", "acabadas", "hechas", "terminadas", "listas", "completed"):
        check(board.STATE_ALIAS.get(w) == "completada", f"alias: {w} → completada")


# ══════════════ T3: papelera y restauración ══════════════

def test_papelera_y_restauracion():
    _reset()
    board.clear_completed(reason="borra las ya realizadas")
    pap = board.trash()
    check(len(pap) == 4, f"la papelera guarda las 4 borradas (tiene {len(pap)})")
    for t in pap:
        check(t.get("previousStatus") == "completada", "previousStatus guardado")
        check(bool(t.get("deletedAt")), "deletedAt guardado")
        check(bool(t.get("deletedBy")), "deletedBy guardado")
        check("realizadas" in t.get("deletionReason", ""), "deletionReason guarda la orden")
        check(bool(t.get("batch")), "batch (lote) guardado")
    restored = board.restore()                     # último lote entero
    check(len(restored) == 4, f"restauradas las 4 (restauró {len(restored)})")
    check(all(t["state"] == "completada" for t in restored),
          "cada tarea vuelve a SU columna anterior")
    check(len(board._load()) == 9, "el tablero vuelve a tener 9")
    check(board.trash() == [], "la papelera queda vacía tras restaurar el lote")


def test_restaurar_una_sola_por_titulo():
    _reset()
    board.clear_completed(reason="test")
    restored = board.restore(query="hecha 2")
    check(len(restored) == 1 and restored[0]["title"] == "hecha 2",
          "restore por título devuelve solo esa")
    check(len(board.trash()) == 3, "las otras 3 siguen en la papelera")


def test_vaciar_todo_es_recuperable():
    """Lo que le pasó a Adri: aunque se vacíe el tablero entero, vuelve."""
    _reset()
    n = board.clear_all(reason="vacía el tablero")
    check(n == 9, f"clear_all mueve las 9 (movió {n})")
    check(board._load() == [], "el tablero queda vacío")
    restored = board.restore()
    check(len(restored) == 9, "se recuperan las 9")
    estados = sorted(t["state"] for t in restored)
    check(estados == sorted(["pendiente"] * 3 + ["progreso"] * 2 + ["completada"] * 4),
          "cada una a su columna original")


def test_papelera_sobrevive_al_reinicio():
    """Reiniciar nexus NO puede perder la papelera: está en disco."""
    _reset()
    board.clear_completed(reason="test")
    check(board.TRASH_FILE.exists(), "board_trash.json existe en disco")
    import json
    datos = json.loads(board.TRASH_FILE.read_text(encoding="utf-8"))
    check(len(datos) == 4, "el fichero de papelera tiene las 4 tarjetas")


def test_purga_es_explicita():
    _reset()
    board.clear_completed(reason="test")
    check(len(board.trash()) == 4, "hay 4 en la papelera antes de purgar")
    n = board.purge_trash()
    check(n == 4 and board.trash() == [], "purge_trash destruye definitivamente")
    check(board.restore() == [], "tras purgar ya no se puede restaurar")


# ══════════════ T1: confirmación obligatoria ══════════════

def test_confirm_pide_y_ejecuta():
    confirm.clear()
    caja = {"hecho": False}

    def _accion():
        caja["hecho"] = True
        return "Borrado."
    q = confirm.request(channel="pc", kind="test", summary="¿Confirmas?",
                        action=_accion, request_text="borra")
    check("¿Confirmas?" in q, "request devuelve la pregunta")
    check(caja["hecho"] is False, "request NO ejecuta la acción")
    check(confirm.pending("pc") is not None, "queda una confirmación pendiente")
    check(confirm.pending("movil") is None, "la confirmación es POR CANAL")
    r = asyncio.run(confirm.answer("sí", "pc"))
    check(caja["hecho"] is True, "el «sí» ejecuta la acción")
    check(r == "Borrado.", "answer devuelve el resultado de la acción")
    check(confirm.pending("pc") is None, "la confirmación se consume")


def test_confirm_cancela_y_se_desarma():
    confirm.clear()
    caja = {"hecho": False}

    def _accion():
        caja["hecho"] = True
        return "Borrado."
    confirm.request(channel="pc", kind="test", summary="¿Confirmas?",
                    action=_accion, request_text="borra",
                    cancel_reply="No he borrado nada.")
    r = asyncio.run(confirm.answer("no", "pc"))
    check(caja["hecho"] is False, "el «no» NO ejecuta nada")
    check(r == "No he borrado nada.", "answer devuelve el mensaje de cancelación")
    # cambiar de tema DESARMA la confirmación (no se queda esperando un «sí»)
    confirm.request(channel="pc", kind="test", summary="¿Confirmas?",
                    action=_accion, request_text="borra")
    r2 = asyncio.run(confirm.answer("qué tiempo hace en Madrid", "pc"))
    check(r2 is None, "un mensaje que no es sí/no devuelve None (sigue su curso)")
    check(confirm.pending("pc") is None, "…y la confirmación se descarta")
    r3 = asyncio.run(confirm.answer("sí", "pc"))
    check(r3 is None and caja["hecho"] is False,
          "un «sí» posterior YA NO dispara nada (anti-disparo diferido)")


def test_confirm_caduca():
    import time as _t
    confirm.clear()
    caja = {"hecho": False}
    confirm.request(channel="pc", kind="test", summary="¿Confirmas?",
                    action=lambda: caja.update(hecho=True), request_text="borra")
    confirm._pending["pc"]["ts"] = _t.time() - confirm.TTL - 5
    check(confirm.pending("pc") is None, "una confirmación vieja no existe")
    check(asyncio.run(confirm.answer("sí", "pc")) is None and caja["hecho"] is False,
          "una confirmación caducada NUNCA dispara")


def test_confirm_solo_respuestas_cortas():
    confirm.clear()
    confirm.request(channel="pc", kind="test", summary="¿Confirmas?",
                    action=lambda: "ok", request_text="borra")
    check(confirm.is_answer("sí", "pc"), "«sí» es respuesta")
    check(confirm.is_answer("vale, adelante", "pc"), "«vale, adelante» es respuesta")
    check(not confirm.is_answer("sí, pero antes dime cuántas tareas tengo en el "
                                "tablero y en qué columna está cada una", "pc"),
          "una frase larga NO se toma como confirmación")
    check(not confirm.is_answer("borra la tarea del gimnasio", "pc"),
          "una orden nueva NO se toma como confirmación")


# ══════════════ Integración: la skill del tablero ══════════════

def test_router_ambitos():
    mod = _skill()
    casos = [
        ("limpia las tareas ya realizadas", "clear", "completadas"),
        ("borra las tareas completadas", "clear", "completadas"),
        ("elimina las tareas hechas", "clear", "completadas"),
        ("borra las tareas finalizadas", "clear", "completadas"),
        ("vacía el tablero", "clear", "todas"),
        ("borra todas las tareas", "clear", "todas"),
        ("borra todas las tareas completadas", "clear", "completadas"),
    ]
    for texto, intent_esperado, scope_esperado in casos:
        intent, _m = _route(mod, texto)
        check(intent == intent_esperado,
              f"router: «{texto}» → {intent} (esperaba {intent_esperado})")
        check(mod._scope_of(texto) == scope_esperado,
              f"ámbito: «{texto}» → {mod._scope_of(texto)} (esperaba {scope_esperado})")
    # ambiguo → NUNCA 'todas'
    for texto in ("borra tareas", "limpia tareas", "elimina alguna tarea"):
        check(mod._scope_of(texto) != "todas", f"ambiguo «{texto}» no puede ser 'todas'")
    # papelera y restauración se enrutan ANTES que cualquier borrado
    for texto in ("recupera las tareas borradas", "recupéralas",
                  "recupera las tareas que has eliminado", "deshaz el borrado",
                  "restaura las tareas eliminadas"):
        intent, _ = _route(mod, texto)
        check(intent == "restore", f"router: «{texto}» → {intent} (esperaba restore)")
    for texto in ("ver la papelera", "qué tareas has borrado", "tareas eliminadas"):
        intent, _ = _route(mod, texto)
        check(intent == "trash", f"router: «{texto}» → {intent} (esperaba trash)")


def test_skill_no_borra_sin_confirmar():
    """EL TEST QUE IMPORTA: la orden del incidente, de punta a punta."""
    mod = _skill()
    mod.board.BOARD_FILE = board.BOARD_FILE
    mod.board.TRASH_FILE = board.TRASH_FILE
    _reset()
    texto = "limpia las tareas ya realizadas"
    intent, m = _route(mod, texto)
    res = asyncio.run(mod.handle(intent, texto, m, {"channel": "pc"}))
    reply = res["reply"]
    check(len(board._load()) == 9, "TRAS PEDIRLO, el tablero sigue con las 9 (no borra aún)")
    check("4" in reply, "la pregunta dice cuántas se van (4)")
    check(re.search(r"confirm", reply, re.I) is not None, "la respuesta pide confirmación")
    check("hecha 1" in reply, "la pregunta enumera las afectadas")
    check(confirm.pending("pc") is not None, "queda armada la confirmación")
    # ahora el «sí»
    r2 = asyncio.run(confirm.answer("sí", "pc"))
    quedan = board._load()
    check(len(quedan) == 5, f"tras confirmar quedan las 5 vivas (quedan {len(quedan)})")
    check(all(t["state"] != "completada" for t in quedan), "solo se fueron las completadas")
    check("papelera" in (r2 or "").lower(), "la respuesta avisa de que están en la papelera")
    # y se pueden recuperar
    intent, m = _route(mod, "recupera las tareas borradas")
    r3 = asyncio.run(mod.handle(intent, "recupera las tareas borradas", m, {"channel": "pc"}))
    check(len(board._load()) == 9, "tras recuperar vuelven a estar las 9")
    check("4" in r3["reply"], "dice cuántas ha recuperado")


def test_skill_cancelar_no_borra():
    mod = _skill()
    mod.board.BOARD_FILE = board.BOARD_FILE
    mod.board.TRASH_FILE = board.TRASH_FILE
    _reset()
    texto = "borra todas las tareas"
    intent, m = _route(mod, texto)
    res = asyncio.run(mod.handle(intent, texto, m, {"channel": "pc"}))
    check("9" in res["reply"], "avisa de que se va a llevar las 9")
    check(re.search(r"vac[ií]a el tablero ENTERO|ENTERO", res["reply"]) is not None,
          "avisa MUY claro de que es el tablero entero")
    asyncio.run(confirm.answer("no", "pc"))
    check(len(board._load()) == 9, "tras decir «no», no se ha borrado nada")


def test_skill_borrado_por_titulo_confirma():
    mod = _skill()
    mod.board.BOARD_FILE = board.BOARD_FILE
    mod.board.TRASH_FILE = board.TRASH_FILE
    _reset()
    texto = "borra la tarea pendiente 2"
    intent, m = _route(mod, texto)
    check(intent == "delete", f"router: «{texto}» → {intent} (esperaba delete)")
    asyncio.run(mod.handle(intent, texto, m, {"channel": "pc"}))
    check(len(board._load()) == 9, "no borra al pedirlo")
    asyncio.run(confirm.answer("sí", "pc"))
    check(len(board._load()) == 8, "tras confirmar, borra una")
    check(board.find_task("pendiente 2") is None, "borró la correcta")
    check(len(board.trash()) == 1, "y está en la papelera")


def test_skill_sin_nada_que_borrar():
    mod = _skill()
    mod.board.BOARD_FILE = board.BOARD_FILE
    mod.board.TRASH_FILE = board.TRASH_FILE
    _reset(n_comp=0)
    intent, m = _route(mod, "borra las tareas completadas")
    res = asyncio.run(mod.handle(intent, "borra las tareas completadas", m, {"channel": "pc"}))
    check(confirm.pending("pc") is None, "sin víctimas no arma ninguna confirmación")
    check(len(board._load()) == 5, "y no toca nada")
    check("no hay" in res["reply"].lower(), "lo dice claramente")


# ══════════════ T24: auditoría ══════════════

def test_auditoria_de_destructivas():
    _reset()
    board.clear_completed(reason="limpia las tareas ya realizadas")
    regs = audit.tail(20, destructive_only=True)
    check(bool(regs), "la operación destructiva deja registro")
    r = regs[-1]
    check(r["action"] == "clear_completed", f"acción registrada ({r['action']})")
    check(r["destructive"] is True, "marcada como destructiva")
    check(len(r["targets"]) == 4, "registra los 4 elementos afectados")
    check("realizadas" in r["request"], "registra la orden original")
    check(bool(r["ts"]) and bool(r["result"]), "registra fecha/hora y resultado")


# ══════════════ Integración en el brain ══════════════

def test_brain_resuelve_confirmaciones():
    src = Path(ROOT, "backend", "core", "aplicacion", "brain.py").read_text(encoding="utf-8")
    # Se comprueba QUE lo importa, no CÓMO: `confirm` bajó a `backend/core/comun/`
    # con la Fase 3 y una prueba atada a la línea exacta se rompe cada vez que un
    # módulo cambia de carpeta, sin que nada haya dejado de funcionar.
    check(re.search(r"import\s+confirm\s+as\s+_cf", src) is not None,
          "brain importa el módulo de confirmación")
    check("_cf.answer(text, channel)" in src, "brain resuelve la confirmación del canal")
    i_conf = src.find("_cf.answer")
    i_route = src.find("routed = None if _no_accion else route(text)")
    check(0 < i_conf < i_route, "la confirmación se resuelve ANTES del router")
    tree = ast.parse(src)
    check(any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "process"
              for n in tree.body), "brain.process sigue existiendo")


def test_api_papelera():
    src = Path(ROOT, "backend", "app.py").read_text(encoding="utf-8")
    check('"/api/board/trash"' in src, "hay endpoint GET /api/board/trash")
    check('"/api/board/restore"' in src, "hay endpoint POST /api/board/restore")


if __name__ == "__main__":
    tests = [test_select_por_estado, test_clear_completed_no_toca_lo_vivo,
             test_alias_realizadas_es_completada,
             test_papelera_y_restauracion, test_restaurar_una_sola_por_titulo,
             test_vaciar_todo_es_recuperable, test_papelera_sobrevive_al_reinicio,
             test_purga_es_explicita,
             test_confirm_pide_y_ejecuta, test_confirm_cancela_y_se_desarma,
             test_confirm_caduca, test_confirm_solo_respuestas_cortas,
             test_router_ambitos, test_skill_no_borra_sin_confirmar,
             test_skill_cancelar_no_borra, test_skill_borrado_por_titulo_confirma,
             test_skill_sin_nada_que_borrar,
             test_auditoria_de_destructivas,
             test_brain_resuelve_confirmaciones, test_api_papelera]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
