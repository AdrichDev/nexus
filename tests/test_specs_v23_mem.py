# -*- coding: utf-8 -*-
"""Tests de las specs v23 — FASE 2 (arquitectura de memoria).

  T4  Engram como MEMORIA OPERATIVA (no solo código): reglas, preferencias,
      procedimientos, restricciones, correcciones, delegación, convenciones…
  T5  separación estricta entre Engram (comportamiento) y RAG (documentos)
  T6  recuperación con relevancia, ámbito, tope y deduplicado → se acabaron las
      respuestas repetitivas; y se puede inspeccionar qué memoria se usó

Ejecutar:  python tests/test_specs_v23_mem.py    (desde la carpeta nexus)
"""
import os
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

import backend.core.opmem as om          # noqa: E402
import backend.core.comun.audit as audit       # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="nexus_v23m_"))
om.OPS_FILE = _TMP / "engram_ops.json"
om.RECALL_LOG = _TMP / "logs" / "recall.jsonl"
audit.AUDIT_FILE = _TMP / "logs" / "audit.jsonl"


def _reset():
    om._save([])
    om._last_applied.clear()


# ══════════════ T4: Engram es memoria operativa ══════════════

def test_admite_recuerdos_no_tecnicos():
    _reset()
    casos = [
        ("antes de borrar tareas enséñame cuáles y pídeme confirmación", "regla"),
        ("nunca me leas en voz alta lo que escribo", "restriccion"),
        ("prefiero que los informes los guardes en la carpeta del proyecto", "preferencia"),
        ("siempre que haya trabajos en segundo plano avísame en el sidebar", "regla"),
        ("no vuelvas a leerme los correos sin que te lo pida", "correccion"),
    ]
    for texto, tipo in casos:
        r = om.remember(texto)
        check(r.get("kind") == tipo,
              f"«{texto[:40]}…» → {r.get('kind')} (esperaba {tipo})")
    # y también técnicos, sin dejar de admitir los de arriba
    r = om.remember("el router prueba los intents en orden de declaración en el código")
    check(r.get("kind") == "tecnico", f"un recuerdo técnico sigue cabiendo ({r.get('kind')})")
    st = om.stats()
    check(st["vivos"] == 6, f"6 recuerdos vivos ({st['vivos']})")
    check(len(st["por_tipo"]) >= 4, "clasificados por tipo")


def test_clasificacion_por_tipo_ambito_y_prioridad():
    _reset()
    r = om.remember("antes de borrar pide confirmación", scope="skill:tasks_board")
    check(r["scope"] == "skill:tasks_board", "el recuerdo tiene ámbito")
    check(r["priority"] >= 4, f"una regla pesa (prioridad {r['priority']})")
    r2 = om.remember("me gusta el resumen breve")
    check(r2["priority"] < r["priority"], "una preferencia pesa menos que una regla")
    r3 = om.remember("no vuelvas a hacerlo así", kind="correccion")
    check(r3["priority"] == 5, "una corrección es lo que más pesa")


def test_la_correccion_manda_sobre_lo_anterior():
    _reset()
    viejo = om.remember("los informes los guardas en la carpeta de descargas")
    nuevo = om.remember("te he dicho que los informes los guardas en la carpeta del proyecto, "
                        "no en descargas", kind="correccion")
    items = om._load()
    v = [i for i in items if i["id"] == viejo["id"]][0]
    check(v.get("superseded_by") == nuevo["id"],
          "la corrección deja obsoleta la regla anterior que chocaba")
    vivos = [r["text"] for r in om.all_rules()]
    check(not any("descargas" in t and "no en descargas" not in t for t in vivos),
          "la regla vieja ya no se aplica")
    check(any("carpeta del proyecto" in t for t in vivos), "la nueva sí")


def test_no_convierte_recuerdos_en_tareas():
    """Criterio de aceptación: los recuerdos NO se convierten en tareas solos."""
    src = Path(ROOT, "backend", "core", "opmem.py").read_text(encoding="utf-8")
    check("board" not in src and "add_task" not in src,
          "la memoria operativa no toca el tablero de tareas")
    brain = Path(ROOT, "backend", "core", "brain.py").read_text(encoding="utf-8")
    i_rem = brain.find("opmem.remember(fact")
    i_ret = brain.find("provider\": \"memoria\"", i_rem)
    check(i_rem > 0 and i_ret > i_rem,
          "«recuerda que…» responde y termina: no sigue hasta la captura de tareas")


def test_explica_que_regla_aplico():
    _reset()
    r = om.remember("antes de borrar pide confirmación", scope="global")
    om.note_use([{**r, "score": 0.9}], "borra las tareas", "pc")
    txt = om.explain("pc")
    check("confirmación" in txt, "sabe decir qué regla aplicó")
    check("historial" not in txt.lower() or len(txt) < 400,
          "lo explica sin soltar todo el historial")
    check(om.explain("movil").startswith("En la última respuesta no apliqué"),
          "y no se inventa reglas en un canal donde no aplicó ninguna")


# ══════════════ T5: Engram ≠ RAG ══════════════

def test_separacion_engram_rag():
    _reset()
    check(om.es_comportamiento("nunca me leas lo que escribo") is True,
          "una manera de trabajar es memoria operativa")
    check(om.es_comportamiento("a partir de ahora guarda los informes en docs") is True,
          "una orden permanente también")
    check(om.es_comportamiento("la reunión con Ana fue el martes") is False,
          "un hecho del mundo NO es memoria operativa (va al RAG)")
    check(om.es_comportamiento("el presupuesto de la obra son 12.000 euros") is False,
          "un dato tampoco")
    brain = Path(ROOT, "backend", "core", "brain.py").read_text(encoding="utf-8")
    check("if opmem.es_comportamiento(fact):" in brain,
          "el brain decide a qué memoria va cada cosa")
    check("CONOCIMIENTO DOCUMENTAL" in brain and "REGLAS Y PREFERENCIAS" in om.as_prompt(
        [{"kind": "regla", "text": "x"}]),
        "los dos contextos van en bloques SEPARADOS y etiquetados")
    check("origen:" in brain, "cada dato del RAG dice de dónde sale")
    check(not any(hasattr(om, n) for n in ("add_document", "index", "ingest", "embed")),
          "la memoria operativa no tiene API para almacenar documentos")
    largo = om.remember("x" * 2000)
    check(len(largo["text"]) <= 600,
          "un recuerdo operativo es una regla corta, no un documento entero")


def test_no_guarda_respuestas_completas_como_reglas():
    _reset()
    brain = Path(ROOT, "backend", "core", "brain.py").read_text(encoding="utf-8")
    check("opmem.remember(reply" not in brain and "opmem.remember(result" not in brain,
          "nunca se guarda una respuesta de nexus como regla")
    check(brain.count("opmem.remember(") <= 3,
          "solo se recuerda en los puntos controlados (petición explícita y corrección)")


# ══════════════ T6: recuperación sin loros ══════════════

def test_relevancia_ambito_y_tope():
    _reset()
    om.remember("los informes van a la carpeta del proyecto", scope="global")
    om.remember("las tareas completadas se archivan el domingo", scope="skill:tasks_board")
    om.remember("el navegador siempre en modo incógnito", scope="skill:chrome")
    for i in range(8):
        om.remember(f"regla de relleno número {i} sobre informes y carpetas", scope="global")

    hits = om.relevant("guarda el informe", scope="global", limit=3)
    check(len(hits) <= 3, f"respeta el tope de resultados ({len(hits)})")
    check(all(h["scope"] == "global" for h in hits), "no cuela reglas de otro ámbito")

    hits = om.relevant("archiva las tareas", scope="skill:tasks_board", limit=5)
    check(any("domingo" in h["text"] for h in hits), "encuentra la regla de su ámbito")
    check(not any("incógnito" in h["text"] for h in hits),
          "la regla del navegador NO se inyecta en el tablero")

    check(om.relevant("qué tiempo hace en Madrid", scope="global") == []
          or all(h["priority"] == 5 for h in om.relevant("qué tiempo hace en Madrid", "global")),
          "una pregunta sin relación no arrastra recuerdos irrelevantes")


def test_deduplica_y_ordena():
    _reset()
    om.remember("guarda los informes en la carpeta del proyecto")
    om.remember("guarda los informes en la carpeta del proyecto")   # idéntica
    om.remember("guarda  los   informes  en la carpeta del proyecto ")  # casi idéntica
    check(len(om.all_rules()) == 1, f"no duplica lo mismo ({len(om.all_rules())})")
    om.remember("nunca borres sin preguntar", kind="restriccion")
    hits = om.relevant("borra los informes", scope="global", limit=5)
    check(hits and hits[0]["priority"] >= 4, "lo más importante va primero")


def test_preguntas_distintas_respuestas_distintas():
    """La causa del bucle: recuperar SIEMPRE los mismos recuerdos."""
    _reset()
    om.remember("las tareas completadas se borran solo con confirmación",
                scope="skill:tasks_board")
    om.remember("el navegador siempre en modo incógnito", scope="skill:chrome")
    om.remember("los correos no se leen en voz alta", scope="skill:comms")
    a = [h["id"] for h in om.relevant("borra las tareas", scope="skill:tasks_board")]
    b = [h["id"] for h in om.relevant("abre una pestaña", scope="skill:chrome")]
    c = [h["id"] for h in om.relevant("lee los correos", scope="skill:comms")]
    check(a and b and c, "cada pregunta recupera algo")
    check(a != b and b != c and a != c,
          "peticiones distintas NO reciben el mismo contexto de memoria")


def test_registra_que_memoria_uso_cada_respuesta():
    _reset()
    r = om.remember("guarda los informes en el proyecto")
    om.note_use([{**r, "score": 0.8}], "guarda el informe", "pc",
                documentos=["contrato.pdf"])
    check(om.RECALL_LOG.exists(), "queda registro de qué se usó para responder")
    linea = om.RECALL_LOG.read_text(encoding="utf-8").strip().splitlines()[-1]
    check(r["id"] in linea, "el registro dice qué recuerdo se usó")
    check("contrato.pdf" in linea, "y qué documento")
    check(om._load()[0]["hits"] == 1, "el recuerdo cuenta sus usos")


def test_sobrevive_al_reinicio():
    _reset()
    om.remember("antes de sobrescribir un archivo, haz copia")
    om._cache.update(items=None, mtime=0.0)      # simula proceso nuevo
    check(any("copia" in r["text"] for r in om.all_rules()),
          "la memoria operativa sobrevive a reiniciar nexus")


# ══════════════ Integración: brain y skill ══════════════

def test_brain_consulta_memoria_antes_de_actuar():
    brain = Path(ROOT, "backend", "core", "brain.py").read_text(encoding="utf-8")
    i_rel = brain.find("opmem.relevant(cmd_text")
    i_handle = brain.find("await skill.module.handle(intent, cmd_text, match, ctx)")
    check(0 < i_rel < i_handle, "consulta las reglas ANTES de ejecutar la skill")
    check('"reglas": _reglas' in brain, "y se las pasa al minion en el contexto")
    check("_WHY_RX" in brain and "opmem.explain(channel)" in brain,
          "sabe explicar qué regla aplicó")
    check('kind="correccion"' in brain,
          "una queja explícita del operador se guarda como corrección")


def test_skill_engram_operativa():
    src = Path(ROOT, "skills", "engram", "skill.py").read_text(encoding="utf-8")
    check("MEMORIA OPERATIVA" in src, "la skill ya no se describe como memoria de código")
    check('"rules"' in src and '"forget_rule"' in src,
          "se pueden consultar y olvidar reglas de viva voz")
    check("opmem.remember(" in src, "lo guardado va a la memoria operativa local")
    check("servidor de Engram no está disponible" in src,
          "si Engram no está levantado, nexus lo guarda igual y lo dice")
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_renovacion import global_route
    for t, intent in [("mis reglas", "rules"), ("qué reglas tienes", "rules"),
                      ("olvida la regla de los informes", "forget_rule"),
                      ("contexto del proyecto", "context"),
                      ("está engram conectado", "status")]:
        f, i = global_route(t)
        check((f, i) == ("engram", intent), f"routing: '{t}' -> {f}/{i} (esperaba engram/{intent})")


if __name__ == "__main__":
    tests = [test_admite_recuerdos_no_tecnicos,
             test_clasificacion_por_tipo_ambito_y_prioridad,
             test_la_correccion_manda_sobre_lo_anterior,
             test_no_convierte_recuerdos_en_tareas,
             test_explica_que_regla_aplico,
             test_separacion_engram_rag,
             test_no_guarda_respuestas_completas_como_reglas,
             test_relevancia_ambito_y_tope, test_deduplica_y_ordena,
             test_preguntas_distintas_respuestas_distintas,
             test_registra_que_memoria_uso_cada_respuesta,
             test_sobrevive_al_reinicio,
             test_brain_consulta_memoria_antes_de_actuar,
             test_skill_engram_operativa]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
