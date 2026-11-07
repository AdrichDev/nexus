# -*- coding: utf-8 -*-
"""PRIV-03 / roadmap P2-8 — SUPRESIÓN COMPLETA: un dato purgado no aparece en
ningún almacén.

Lo que pincha esto. `test_purga.py` demuestra que la retirada está bien hecha
para lo que cubre: nota → papelera, fila con `retirado_en`, borrado duro con
«sí». El hallazgo PRIV-03 es el resto: el texto seguía escrito en
`data/rag/knowledge.jsonl`, en el espejo de la ingesta, en la memoria operativa,
en el servidor de Engram, en `data/webcache.json`, en los JSONL de
interacciones/auditoría/recall y en cada zip de `data/backups/`. El operador
decía «olvida mi divorcio», nexus dejaba de recordarlo, y el divorcio seguía en
el disco seis veces.

Cubre:
  * la previsualización ENSEÑA la lista de almacenes que se van a tocar y los
    que no se pueden tocar, con su motivo, más las copias de seguridad que lo
    conservan y sus fechas;
  * `aplicar()` barre los almacenes de ESA lista: el hecho desaparece del
    almacén vectorial, el espejo del documento va a la MISMA papelera que la
    nota (restaurable), Engram recibe la orden de olvidar, la caché web pierde
    la entrada y la memoria operativa pierde el recuerdo;
  * Engram caído se reporta como NO COMPLETADO, nunca como hecho;
  * los registros de conversación NO se tocan por defecto y, cuando el operador
    los incluye, se van líneas ENTERAS dejando las demás IDÉNTICAS byte a byte;
  * entrar por la puerta del borrado duro sigue exigiendo el «sí» del operador
    (nada nuevo se salta `confirm.request`);
  * restaurar devuelve nota y espejo (no hay media migración);
  * nada de lo que no se pidió se mueve: nota, espejo, registro, caché y regla
    ajenos quedan intactos.

REGLA ABSOLUTA DE ESTE FICHERO: nada toca el `data/`, `config/` ni los backups
reales del operador. Cada caso monta su propio árbol de usar y tirar
(`tempfile.mkdtemp()`) con notas y documentos SINTÉTICOS, y redirige a él las
constantes de cada módulo dueño (rag, ingesta, opmem, selflearn, audit,
websearch, jobs). Postgres se fuerza OFFLINE: estas pruebas no insertan, no
retiran y no borran ninguna fila de `memories`. Engram es un DOBLE en memoria:
no se abre ningún socket.

Ejecutar: .venv\\Scripts\\python.exe tests\\unit\\memory\\test_purga_completa.py
"""
import ast
import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


# ----------------------------- módulos bajo prueba ---------------------------
audit = importlib.import_module("backend.core.comun.audit")
ingesta = importlib.import_module("backend.core.dominio.ingesta")
mem = importlib.import_module("backend.core.dominio.memory")
opmem = importlib.import_module("backend.core.dominio.opmem")
permissions = importlib.import_module("backend.core.comun.permissions")
purga = importlib.import_module("backend.core.dominio.purga")
rag = importlib.import_module("backend.core.dominio.rag")
selflearn = importlib.import_module("backend.core.dominio.selflearn")
websearch = importlib.import_module("backend.core.infraestructura.websearch")
eng = importlib.import_module("backend.core.infraestructura.engram_bridge")


# ------------------------------- datos de prueba -----------------------------
# El texto que el operador quiere olvidar. >120 caracteres a propósito: así se
# ejercitan también las muestras del principio, el medio y el final.
_TEXTO_DIVORCIO = (
    "Mi divorcio con Marta se cerró en 2023 y no quiero que nadie de mi trabajo "
    "lo sepa nunca. El convenio regulador está firmado en el juzgado de "
    "Colmenar y las condiciones económicas se revisan cada mes de enero. Esto "
    "es lo único que quiero que desaparezca de todos los sitios donde lo "
    "guardaste, porque ya no me sirve de nada recordarlo.")
_TEXTO_RECETAS = "Receta de tarta de queso de la abuela, con la base de galleta."
_TEXTO_LUZ = ("Factura de la luz del mes de marzo: el consumo fue de 245 kWh y "
              "el importe total asciende a 61 euros con impuestos.")

_MARCA_PERSONAL = "divorcio-dam"      # palabra de categoría, SOLO en la nota

_FAKE_UMBRALES = {
    "minutos_vigencia_plan": 30,
    "papelera_aviso_items": 3000,
    "categorias": {
        "papeleo-personal": {"personal": False, "minimo_aciertos": 1,
                             "palabras": [_MARCA_PERSONAL]},
    },
}


def _lineas_jsonl(campos):
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in campos)


class Entorno:
    """Árbol de usar y tirar + todas las rutas de almacén apuntadas dentro."""

    def __init__(self, engram_offline=False):
        self.engram_offline = engram_offline
        self.llamadas_forget = []
        self.pg_online_orig = None

    # ------------------------------ ciclo de vida ----------------------------
    def _poner(self, obj, nombre, valor):
        """Parchea un atributo anotando cómo estaba, para deshacerlo al salir.

        Se anota si EXISTÍA: en el código base algunas de estas constantes no
        existen todavía, y crear+restaurar a mano dejaría el módulo con basura."""
        self._parches.append((obj, nombre, hasattr(obj, nombre), getattr(obj, nombre, None)))
        setattr(obj, nombre, valor)

    def __enter__(self):
        self._parches = []
        self.tmp = Path(tempfile.mkdtemp(prefix="nexus_purga_completa_"))
        self.data = self.tmp / "data"
        self.memory = self.data / "memory"
        self.memory.mkdir(parents=True)
        self.documentos = self.memory / "documentos"
        self.documentos.mkdir(parents=True)

        self._poner(purga, "DATA_DIR", self.data)
        self._poner(purga, "MEMORY_DIR", self.memory)
        self._poner(purga, "PAPELERA_DIR", self.memory / "papelera")
        self._poner(purga, "PAPELERA_FILE", self.memory / "papelera" / "papelera.json")
        self._poner(purga, "EXPORT_DIR", self.data / "exportado_purga")
        self._poner(purga, "DOCUMENTOS_DIR", self.documentos)
        self._poner(purga, "_umbrales_purga", lambda: _FAKE_UMBRALES)
        purga._planes.clear()

        self._poner(rag, "_STORE", self.data / "rag" / "knowledge.jsonl")
        self._poner(rag, "_SEEN", self.data / "rag" / "indexed.json")
        self._poner(rag, "_mem", None)
        self._poner(ingesta, "DOCUMENTOS_DIR", self.documentos)
        self._poner(opmem, "OPS_FILE", self.data / "engram_ops.json")
        self._poner(opmem, "RECALL_LOG", self.data / "logs" / "recall.jsonl")
        self._poner(selflearn, "_INTER", self.data / "interactions.jsonl")
        self._poner(audit, "AUDIT_FILE", self.data / "logs" / "audit.jsonl")
        self.webcache = self.data / "webcache.json"
        self._poner(websearch, "_cache_file", lambda: self.webcache)
        self._poner(websearch, "_MEM", None)
        self._poner(websearch, "_MEM_DIR", None)

        # Engram: DOBLE. Ni socket ni proceso.
        self._poner(eng, "status_sync", self._engram_status)
        self._poner(eng, "forget_sync", self._engram_forget)

        # Postgres: OFFLINE a la fuerza. Estas pruebas no tocan ninguna fila.
        self._poner(type(mem.pg), "online", property(lambda self_: False))
        self._poner(mem.pg, "filas_ligadas_a_nota", lambda nombre: [])
        self._poner(mem.pg, "filas_sin_marca_origen", lambda tipos=None: [])
        return self

    def __exit__(self, *exc):
        for obj, nombre, existia, viejo in reversed(self._parches):
            if existia:
                setattr(obj, nombre, viejo)
            else:
                try:
                    delattr(obj, nombre)
                except Exception:                              # noqa: BLE001
                    pass
        self._parches = []
        purga._planes.clear()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    # -------------------------------- dobles --------------------------------
    def _engram_status(self, ctx=None):
        url = "http://127.0.0.1:7437"
        if self.engram_offline:
            return {"installed": True, "exe": "/falso/engram", "url": url,
                    "last_error": "no responde (doble de prueba)", "alive_cached": False}
        return {"installed": True, "exe": "/falso/engram", "url": url,
                "last_error": "", "alive_cached": True}

    def _engram_forget(self, ctx, query, timeout=8):
        self.llamadas_forget.append(query)
        if self.engram_offline:
            return {"ok": False, "no_completado": True, "borrados": 0, "ids": [],
                    "consulta": query,
                    "error": "Engram no responde ahora mismo: no lo cuento como olvidado"}
        return {"ok": True, "no_completado": False, "borrados": 1, "ids": [7],
                "consulta": query, "error": "", "nota": "1 recuerdo borrado"}

    # ------------------------------- fixtures -------------------------------
    def montar(self, backups=3):
        """Nota + espejo + RAG + memoria operativa + caché + JSONL + backups."""
        # 1) la nota que se purga y una nota AJENA que no se debe tocar
        self.nota = self.memory / "divorcio-dam.md"
        self.nota.write_text(_TEXTO_DIVORCIO + "\n", encoding="utf-8")
        self.nota_ajena = self.memory / "recetas.md"
        self.nota_ajena.write_text(_TEXTO_RECETAS + "\n", encoding="utf-8")

        # 2) espejo de la ingesta: el documento del que salió la nota, y otro ajeno
        dominio = self.documentos / "personal"
        dominio.mkdir(parents=True)
        self.espejo = dominio / "divorcio.pdf.9f2a1b3c.md"
        self.espejo.write_text(
            "---\norigen: C:\\documentos\\divorcio.pdf\ndominio: personal\n"
            f"etiqueta: normal\ningerido: 2026-01-01T00:00:00+00:00\n---\n\n{_TEXTO_DIVORCIO}\n",
            encoding="utf-8")
        self.espejo_ajeno = dominio / "factura-luz.pdf.7c1d2e3f.md"
        self.espejo_ajeno.write_text(
            "---\norigen: C:\\documentos\\factura-luz.pdf\ndominio: personal\n"
            f"etiqueta: normal\ningerido: 2026-01-01T00:00:00+00:00\n---\n\n{_TEXTO_LUZ}\n",
            encoding="utf-8")

        # 3) almacén vectorial local: un registro de la nota (por fuente), uno que
        #    la contiene sin `meta.source`, y uno AJENO que debe quedar idéntico.
        self.rag = rag._STORE
        self.rag.parent.mkdir(parents=True, exist_ok=True)
        self.rag_ajeno = {"id": "knowledge:gimnasio", "kind": "knowledge",
                          "text": "El horario del gimnasio es de 7 a 22.",
                          "meta": {"source": "gimnasio.md"}, "vec": None, "ts": 1.0}
        self.rag.parent.joinpath("indexed.json").write_text(
            json.dumps({str(self.nota): 123.0,
                        str(self.data / "memory" / "recetas.md"): 456.0}),
            encoding="utf-8")
        self.rag.write_text(_lineas_jsonl([
            {"id": "knowledge:1", "kind": "knowledge",
             "text": f"[divorcio.pdf] {_TEXTO_DIVORCIO}", "meta": {"source": "divorcio.pdf"},
             "vec": None, "ts": 1.0},
            {"id": "knowledge:2", "kind": "knowledge", "text": _TEXTO_DIVORCIO,
             "meta": {}, "vec": None, "ts": 2.0},
            self.rag_ajeno,
        ]), encoding="utf-8")
        self.rag_linea_ajena = json.dumps(self.rag_ajeno, ensure_ascii=False) + "\n"

        # 4) memoria operativa: una regla con el texto y otra AJENA
        opmem.remember(_TEXTO_DIVORCIO, kind="tecnico", scope="global",
                       source="operador", origen="pc")
        self.regla_ajena = "Antes de borrar algo, enséñame exactamente qué vas a borrar."
        opmem.remember(self.regla_ajena, kind="regla", scope="global",
                       source="operador", origen="pc")

        # 5) caché web: una entrada con el texto y otra AJENA
        self.webcache_ajena = {"ts": time.time(), "data": "El tiempo en Madrid: 24 grados."}
        self.webcache.write_text(json.dumps({
            "p::https://ejemplo/divorcio": {"ts": time.time(),
                                            "data": f"<html>{_TEXTO_DIVORCIO}</html>"},
            "q::el tiempo en madrid": self.webcache_ajena,
        }, ensure_ascii=False), encoding="utf-8")

        # 6) registros: una línea del hecho y otra AJENA en cada uno
        self.logs = {}
        pares = {
            "interacciones": (selflearn._INTER,
                              {"ts": "2026-01-01", "text": _TEXTO_DIVORCIO, "reply": "vale"},
                              {"ts": "2026-01-02", "text": _TEXTO_RECETAS, "reply": "mmm"}),
            "recall": (opmem.RECALL_LOG,
                       {"ts": "2026-01-01", "channel": "pc", "texto": _TEXTO_DIVORCIO,
                        "reglas": [], "documentos": []},
                       {"ts": "2026-01-02", "channel": "pc", "texto": _TEXTO_RECETAS,
                        "reglas": [], "documentos": []}),
            "audit": (audit.AUDIT_FILE,
                      {"ts": "2026-01-01", "action": "recordar",
                       "request": _TEXTO_DIVORCIO, "result": "guardado"},
                      {"ts": "2026-01-02", "action": "recordar",
                       "request": _TEXTO_RECETAS, "result": "guardado"}),
        }
        for clave, (ruta, sucia, limpia) in pares.items():
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(_lineas_jsonl([sucia, limpia]), encoding="utf-8")
            self.logs[clave] = (ruta, sucia, limpia)

        # 7) trabajos: uno con el texto en el resultado y otro AJENO
        self.jobs = self.data / "jobs.json"
        self.job_ajeno = {"id": "j-2", "num": 2, "request": "investiga la receta",
                          "result": _TEXTO_RECETAS, "status": "completed", "seen": True}
        self.jobs.write_text(json.dumps([
            {"id": "j-1", "num": 1, "request": "resume mi divorcio",
             "result": _TEXTO_DIVORCIO, "status": "completed", "seen": True},
            self.job_ajeno,
        ], ensure_ascii=False, indent=1), encoding="utf-8")

        # 8) copias de seguridad: NO se tocan, se nombran con sus fechas. Se crean
        #    zips DE VERDAD para que el barrido pueda comprobar cuáles llevan la
        #    nota dentro (las dos primeras) y cuál no (la última).
        import zipfile
        self.backups_dir = self.data / "backups"
        self.backups_dir.mkdir()
        self.backups = []
        for i in range(backups):
            z = self.backups_dir / f"nexus-data-2026010{i + 1}.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("jobs.json", "[]")
                if i < backups - 1:
                    zf.writestr("memory/divorcio-dam.md", _TEXTO_DIVORCIO)
            os.utime(z, (1_767_225_600 + i * 86400,) * 2)
            self.backups.append(z)
        return self


# -------------------------------- utilidades ---------------------------------
def _bytes(ruta: Path):
    try:
        return ruta.read_bytes()
    except Exception:
        return None


def _lineas(ruta: Path):
    try:
        return ruta.read_text(encoding="utf-8").splitlines(keepends=True)
    except Exception:
        return []


def _buscar(plan, aid):
    for a in plan.get("almacenes") or []:
        if a.get("id") == aid:
            return a
    return {}


# =============================== 1) previsualización =========================
def test_previsualizacion_lista_todos_los_almacenes():
    with Entorno() as e:
        e.montar()
        antes = {p: (_bytes(p), p.stat().st_mtime if p.exists() else None)
                 for p in (e.rag, e.nota, e.webcache, e.jobs, e.espejo)}
        plan = purga.previsualizar()
        ids = [a["id"] for a in plan["almacenes"]]
        for esperado in ("rag", "documentos", "opmem", "engram", "webcache",
                         "logs", "jobs", "backups"):
            check(esperado in ids, f"previsualizar(): el almacén «{esperado}» aparece en la lista")
        check(ids[-1] == "backups", "previsualizar(): las copias de seguridad se listan al final")

        check(_buscar(plan, "rag")["elementos"] >= 2,
              "previsualizar(): cuenta los registros del RAG que se van (fuente + contenido)")
        check(_buscar(plan, "documentos")["elementos"] == 1,
              "previsualizar(): cuenta el espejo del documento, y solo ese")
        check(_buscar(plan, "webcache")["elementos"] == 1,
              "previsualizar(): cuenta la entrada de caché con el texto")
        check(_buscar(plan, "opmem")["elementos"] >= 1,
              "previsualizar(): cuenta el recuerdo de la memoria operativa")

        logs = _buscar(plan, "logs")
        check(logs["estado"] == "no_incluido" and logs["incluido"] is False,
              "previsualizar(): los registros NO vienen incluidos por defecto")
        check(logs["elementos"] == 3,
              "previsualizar(): aun así ENSEÑA cuántas líneas casarían (3: una por fichero)")

        bk = _buscar(plan, "backups")
        check(bk["accion"] == "no_se_toca" and bk["elementos"] == 2,
              "previsualizar(): las copias que CONTIENEN la nota se cuentan y NO se tocan")
        check(bk.get("revisadas") == 3,
              "previsualizar(): dice cuántos zips se revisaron (3), no solo cuántos valen")
        check(len(bk["fechas"]) == 2 and all(len(f) == 10 for f in bk["fechas"]),
              "previsualizar(): las copias que la llevan se nombran CON SUS FECHAS (AAAA-MM-DD)")
        check("nexus-data-20260103.zip" not in bk["nombres"],
              "previsualizar(): el zip que NO lleva la nota no se anuncia como si la llevara")
        check("no las reescribo" in bk["motivo"] or "NO las reescribo" in bk["motivo"],
              "previsualizar(): el motivo dice por qué no se tocan y cuál es el camino")

        con_logs = purga.previsualizar(incluir_logs=True)
        check(_buscar(con_logs, "logs")["incluido"] is True
              and _buscar(con_logs, "jobs")["incluido"] is True,
              "previsualizar(incluir_logs=True): los registros y los trabajos pasan a incluidos")

        intactos = all(_bytes(p) == b and (no_m == 0 or p.stat().st_mtime == no_m)
                       for p, (b, no_m) in antes.items())
        check(intactos, "previsualizar(): NO cambia ni un byte ni un mtime")
    return None


# =============================== 2) el barrido ===============================
def test_aplicar_barre_todos_los_almacenes():
    with Entorno() as e:
        e.montar()
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        check(r["ok"] is True, "aplicar(): el barrido se completa")

        # almacén vectorial local: el hecho YA NO ESTÁ y lo ajeno sigue idéntico
        texto_rag = e.rag.read_text(encoding="utf-8")
        check("Marta" not in texto_rag, "knowledge.jsonl: el texto purgado ya no está")
        check(e.rag_linea_ajena in texto_rag.splitlines(keepends=True),
              "knowledge.jsonl: el registro AJENO queda IDÉNTICO byte a byte")
        check(r["almacenes"]["rag"]["elementos"] == 2,
              "knowledge.jsonl: se llevó los 2 registros del hecho (fuente y contenido)")
        indice = json.loads((e.rag.parent / "indexed.json").read_text(encoding="utf-8"))
        check(str(e.nota) not in indice and len(indice) == 1,
              "indexed.json: la ruta de la nota purgada tampoco se queda apuntada")

        # espejo del documento: a la MISMA papelera, restaurable
        check(not e.espejo.is_file(), "documentos: el espejo ya no está en su sitio")
        en_papelera = list((purga.PAPELERA_DIR / r["lote"]).glob("*.md"))
        nombres = {p.name for p in en_papelera}
        check(e.espejo.name in nombres,
              "documentos: el espejo está EN LA PAPELERA (no se ha destruido)")
        check(e.espejo_ajeno.is_file(),
              "documentos: el espejo AJENO no se ha movido")
        check(e.nota_ajena.is_file(), "memoria: la nota AJENA no se ha movido")

        # Engram: recibió la orden de olvidar
        check(e.llamadas_forget, "Engram: se le pidió olvidar (doble de prueba)")
        check(any("divorcio" in c.lower() for c in e.llamadas_forget),
              "Engram: la consulta de olvido es el nombre de la nota, no basura")
        check(r["almacenes"]["engram"]["resultado"] in ("olvidado", "sin_cambios"),
              "Engram: el resultado del doble se reporta tal cual")

        # caché web
        cache = json.loads(e.webcache.read_text(encoding="utf-8"))
        check("q::el tiempo en madrid" in cache and len(cache) == 1,
              "webcache: la entrada con el texto se va y la AJENA se queda")
        check(websearch._MEM is None,
              "webcache: la copia en RAM se invalida (si no, volvería al disco)")

        # memoria operativa
        reglas = [it.get("text", "") for it in opmem._load()]
        check(not any("Marta" in t for t in reglas),
              "opmem: el recuerdo con el texto purgado ya no está")
        check(any(t == e.regla_ajena for t in reglas),
              "opmem: la regla AJENA sigue exactamente igual")

        # registros: NO tocados por defecto
        for clave, (ruta, sucia, _limpia) in e.logs.items():
            texto = ruta.read_text(encoding="utf-8")
            check(json.dumps(sucia, ensure_ascii=False) in texto,
                  f"{clave}: la línea del hecho SIGUE ahí (los registros no se tocan por defecto)")
        trabajos = json.loads(e.jobs.read_text(encoding="utf-8"))
        check(any(j.get("id") == "j-1" for j in trabajos),
              "jobs.json: el trabajo con el texto SIGUE ahí (alcance opt-in)")
        check(r["almacenes"]["logs"]["resultado"] == "no_incluido",
              "informe: los registros se reportan como NO incluidos")
        check(r["almacenes"]["jobs"]["resultado"] == "no_incluido",
              "informe: los trabajos se reportan como NO incluidos")

        # copias de seguridad: intactas
        check(all(z.is_file() for z in e.backups),
              "backups: las copias siguen ahí (no se reescriben ni se borran)")
        check(r["almacenes"]["backups"]["resultado"] == "no_se_toca",
              "informe: las copias se reportan como intactas a propósito")
        check(len(r["almacenes"]["backups"]["fechas"]) == 2,
              "informe: el resultado del barrido vuelve a nombrar las fechas")

        # el informe es honesto y concreto
        check("Sobrevive" in r["resumen"] and "Retirado" in r["resumen"],
              "informe: dice qué se retiró Y qué sobrevive (nunca un «borrado» a secas)")
        check(any("backups" in s["que"] or "seguridad" in s["que"] for s in r["sobrevive"]),
              "informe: las copias de seguridad aparecen en «sobrevive» con su motivo")
        check(any("papelera" in x.lower() for x in r["restaurable"]) or
              any("restaura" in x.lower() for x in r["restaurable"]),
              "informe: dice qué es restaurable")


# ============================ 3) Engram no completado ========================
def test_engram_offline_no_se_cuenta_como_hecho():
    with Entorno(engram_offline=True) as e:
        e.montar()
        plan = purga.previsualizar()
        check(_buscar(plan, "engram")["estado"] == "no_disponible",
              "previsualizar(): con Engram caído, el almacén se lista como NO DISPONIBLE")
        check("no responde" in _buscar(plan, "engram")["motivo"],
              "previsualizar(): y dice por qué (el error real, no un «no se pudo»)")
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        check(r["ok"] is True, "aplicar(): el resto del barrido se hace igual")
        check(r["almacenes"]["engram"]["resultado"] == "no_completado",
              "Engram caído: el resultado es NO COMPLETADO, no «hecho»")
        check("Engram" in r["resumen"],
              "informe: el resumen nombra a Engram entre lo que sobrevive")
        check(any("Engram" in s["que"] for s in r["sobrevive"]),
              "informe: Engram aparece en «sobrevive» con su motivo")
        check("Marta" not in e.rag.read_text(encoding="utf-8"),
              "Engram caído NO impide el resto: el RAG se barrió igual")


def test_engram_sin_endpoint_de_borrado_se_reporta():
    """El servidor que responde pero NO sabe borrar: falso «hecho» prohibido."""
    with Entorno() as e:
        e.montar()
        eng.forget_sync = lambda ctx, query, timeout=8: {
            "ok": False, "no_completado": True, "borrados": 0, "ids": [],
            "consulta": query,
            "error": "este Engram no expone borrado de recuerdos (HTTP 405)"}
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        engr = r["almacenes"]["engram"]
        check(engr["resultado"] == "no_completado",
              "Engram sin borrado: se reporta NO COMPLETADO (nunca «olvidado»)")
        check("405" in (engr.get("error") or ""),
              "Engram sin borrado: el motivo dice qué contestó el servidor")


# ================================ 4) registros ===============================
def test_logs_intactos_por_defecto_y_opt_in_byte_identico():
    with Entorno() as e:
        e.montar()
        antes = {k: _lineas(v[0]) for k, v in e.logs.items()}
        plan = purga.previsualizar()          # sin incluir_logs
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        for clave, (ruta, _sucia, limpia) in e.logs.items():
            despues = _lineas(ruta)
            linea_limpia = json.dumps(limpia, ensure_ascii=False) + "\n"
            check(all(l in despues for l in antes[clave]),
                  f"{clave}: por defecto las líneas de antes siguen TODAS (nada se borró)")
            check(linea_limpia in despues,
                  f"{clave}: la línea ajena sigue IDÉNTICA byte a byte")
        check(r["almacenes"]["logs"]["resultado"] == "no_incluido",
              "logs: el informe dice que no se incluyeron")

    with Entorno() as e:
        e.montar()
        antes = {k: _lineas(v[0]) for k, v in e.logs.items()}
        plan = purga.previsualizar(incluir_logs=True)
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        for clave, (ruta, sucia, limpia) in e.logs.items():
            despues = _lineas(ruta)
            linea_sucia = json.dumps(sucia, ensure_ascii=False) + "\n"
            linea_limpia = json.dumps(limpia, ensure_ascii=False) + "\n"
            check(linea_sucia not in despues,
                  f"{clave}: con incluir_logs la línea del hecho SÍ se va")
            check(linea_limpia in despues,
                  f"{clave}: la línea ajena sigue IDÉNTICA byte a byte")
            check(all(l in despues for l in antes[clave] if l != linea_sucia),
                  f"{clave}: no se toca ninguna otra línea")
        check(r["almacenes"]["logs"]["elementos"] == 3,
              "logs: el informe cuenta 3 líneas retiradas (una por fichero)")
        trabajos = json.loads(e.jobs.read_text(encoding="utf-8"))
        check([j["id"] for j in trabajos] == ["j-2"],
              "jobs.json: con incluir_logs se va el trabajo del hecho y el ajeno se queda")
        check(trabajos[0].get("result") == _TEXTO_RECETAS,
              "jobs.json: el trabajo ajeno queda con su texto intacto")
        check(e.nota.is_file() is False and e.nota_ajena.is_file(),
              "sanity: la nota se retiró y la ajena sigue")


def test_no_se_puede_ampliar_lo_que_la_previsualizacion_no_enseno():
    with Entorno() as e:
        e.montar()
        plan = purga.previsualizar()             # SIN registros
        r = purga.aplicar(plan["id"], ["papeleo-personal"], incluir_logs=True)
        check(r["ok"] is False,
              "aplicar(incluir_logs=True) con un plan sin registros: se RECHAZA")
        check("previsualiz" in r.get("error", "").lower(),
              "y el motivo pide una previsualización nueva (no amplía en silencio)")
        check(e.nota.is_file(),
              "rechazado: no se movió NADA (ni la nota), porque el plan sigue vivo")
        texto = selflearn._INTER.read_text(encoding="utf-8")
        check(json.dumps(e.logs["interacciones"][1], ensure_ascii=False) in texto,
              "rechazado: la línea del hecho sigue en interactions.jsonl")


# =============================== 5) restaurar ================================
def test_restaurar_devuelve_nota_y_espejo():
    with Entorno() as e:
        e.montar()
        contenido_nota = e.nota.read_text(encoding="utf-8")
        contenido_espejo = e.espejo.read_text(encoding="utf-8")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        check(not e.nota.is_file() and not e.espejo.is_file(),
              "precondición: tras aplicar, ni la nota ni el espejo están en su sitio")
        rr = purga.restaurar(r["lote"])
        check(rr["ok"] is True, "restaurar(): revierte el lote")
        check(e.nota.is_file() and e.nota.read_text(encoding="utf-8") == contenido_nota,
              "restaurar(): la NOTA vuelve a su ruta original, idéntica")
        check(e.espejo.is_file() and e.espejo.read_text(encoding="utf-8") == contenido_espejo,
              "restaurar(): el ESPEJO vuelve también (no hay media migración)")
        items = purga.papelera(r["lote"])
        check(len(items) == 2 and all(i.get("restaurado") for i in items),
              "restaurar(): la papelera registra los DOS ficheros como restaurados")


# ====================== 6) el candado del borrado duro =======================
def _funciones_con_unlink(ruta: Path) -> set:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    fuera = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(nodo):
            if isinstance(sub, ast.Attribute) and sub.attr == "unlink":
                fuera.add(nodo.name)
    return fuera


def _llamadas_a(ruta: Path, nombres: set) -> set:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    fuera = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(nodo):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    nombre = getattr(f, "attr", None) or getattr(f, "id", None)
                    if nombre in nombres:
                        fuera.add(nodo.name)
    return fuera


def test_el_candado_del_borrado_duro_sigue_intacto():
    fuente_purga = Path(ROOT) / "backend" / "core" / "dominio" / "purga.py"
    con_unlink = _funciones_con_unlink(fuente_purga)
    check(con_unlink <= {"borrar_definitivo", "_escribir_texto_atomico"},
          f"purga.py: solo el borrado definitivo destruye ficheros de datos "
          f"(encontrado: {sorted(con_unlink)})")
    llama_borrado = _llamadas_a(fuente_purga, {"borrar_definitivo", "borrar_carpeta_definitivo"})
    check(not (llama_borrado & {"_barrer_rag", "_barrer_documentos", "_barrer_opmem",
                                "_barrer_engram", "_barrer_webcache", "_barrer_logs",
                                "_barrer_jobs", "_barrer_almacenes", "_retirar_categoria"}),
          f"el barrido NO llama al borrado duro (encontrado: {sorted(llama_borrado)})")

    # El endpoint que borra de verdad sigue pasando por confirm.request().
    app = Path(ROOT) / "backend" / "app.py"
    arbol = ast.parse(app.read_text(encoding="utf-8"))
    manejador = None
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                nodo.name == "api_memoria_purga_borrar_definitivo":
            manejador = nodo
    check(manejador is not None, "app.py: existe el endpoint de borrado definitivo")
    if manejador is not None:
        nombres = set()
        for sub in ast.walk(manejador):
            if isinstance(sub, ast.Call):
                f = sub.func
                nombres.add(getattr(f, "attr", None) or getattr(f, "id", None))
        check("request" in nombres,
              "app.py: el borrado definitivo pasa por confirm.request() (el «sí» del operador)")
        anidado = [n for n in ast.walk(manejador)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not manejador]
        llamadas_directas = []
        for sub in ast.walk(manejador):
            if isinstance(sub, ast.Call):
                f = sub.func
                if (getattr(f, "attr", None) or "") == "borrar_definitivo":
                    dentro_de_anidada = any(any(x is sub for x in ast.walk(a)) for a in anidado)
                    if not dentro_de_anidada:
                        llamadas_directas.append(getattr(sub, "lineno", 0))
        check(not llamadas_directas,
              "app.py: borrar_definitivo SOLO se llama dentro de la acción confirmada")

    # Y el dominio se niega sin lote, como siempre.
    with Entorno() as e:
        e.montar()
        r = purga.borrar_definitivo("lote-que-no-existe-jamas")
        check(r["ok"] is False and "papelera" in r.get("error", "").lower(),
              "borrar_definitivo(): un lote inexistente se rechaza con motivo")


# ============================ 7) alcance del barrido =========================
def test_barrido_fuera_de_data_no_toca_ningun_almacen():
    with Entorno() as e:
        e.montar()
        # La carpeta de memoria deja de estar dentro de `data/`: es el caso de una
        # prueba con su propio árbol, o de un NEXUS_DATA_DIR mal puesto.
        ajeno = Path(tempfile.mkdtemp(prefix="nexus_memoria_suelta_"))
        try:
            (ajeno / "divorcio-dam.md").write_text(_TEXTO_DIVORCIO + "\n", encoding="utf-8")
            purga.MEMORY_DIR = ajeno
            purga.PAPELERA_DIR = ajeno / "papelera"
            purga.PAPELERA_FILE = purga.PAPELERA_DIR / "papelera.json"
            antes = _bytes(e.rag)
            plan = purga.previsualizar()
            check(all(a["estado"] == "fuera_de_alcance"
                      for a in plan["almacenes"] if a["id"] != "backups"),
                  "fuera de data/: TODOS los almacenes se declaran fuera de alcance")
            check("no está dentro de" in _buscar(plan, "rag")["motivo"],
                  "fuera de data/: el motivo lo dice y no se adivina")
            r = purga.aplicar(plan["id"], ["papeleo-personal"])
            check(r["ok"] is True, "fuera de data/: la retirada de la nota sigue funcionando")
            check(_bytes(e.rag) == antes,
                  "fuera de data/: el almacén vectorial NO se toca (ni un byte)")
            check(r["almacenes"]["rag"]["resultado"] == "fuera_de_alcance",
                  "fuera de data/: el informe dice que no se barrió y por qué")
        finally:
            import shutil
            shutil.rmtree(ajeno, ignore_errors=True)


# ======================= 8) anti-colateral y path_allowed ====================
def test_anti_colateral_de_todo_lo_ajeno():
    with Entorno() as e:
        e.montar()
        antes = {
            "nota_ajena": _bytes(e.nota_ajena),
            "espejo_ajeno": _bytes(e.espejo_ajeno),
            "cache_ajena": json.dumps(e.webcache_ajena, ensure_ascii=False),
            "regla_ajena": e.regla_ajena,
            "rag_ajeno": e.rag_linea_ajena,
        }
        plan = purga.previsualizar(incluir_logs=True)
        purga.aplicar(plan["id"], ["papeleo-personal"])
        check(_bytes(e.nota_ajena) == antes["nota_ajena"],
              "anti-colateral: la nota ajena queda idéntica")
        check(_bytes(e.espejo_ajeno) == antes["espejo_ajeno"],
              "anti-colateral: el espejo ajeno queda idéntico")
        cache = json.loads(e.webcache.read_text(encoding="utf-8"))
        check(json.dumps(cache.get("q::el tiempo en madrid"), ensure_ascii=False)
              == antes["cache_ajena"], "anti-colateral: la entrada de caché ajena queda idéntica")
        textos = [it.get("text", "") for it in opmem._load()]
        check(antes["regla_ajena"] in textos, "anti-colateral: la regla ajena sigue ahí")
        check(antes["rag_ajeno"] in e.rag.read_text(encoding="utf-8"),
              "anti-colateral: el registro ajeno del RAG queda idéntico")
        check(any("tarta de queso" in l for l in _lineas(selflearn._INTER)),
              "anti-colateral: la línea ajena con la receta sigue en interactions.jsonl")


def test_el_espejo_no_sigue_enlaces_ni_sale_de_su_carpeta():
    with Entorno() as e:
        e.montar()
        fuera = Path(tempfile.mkdtemp(prefix="nexus_fuera_del_espejo_"))
        try:
            externo = fuera / "divorcio-copia.md"
            externo.write_text(_TEXTO_DIVORCIO + "\n", encoding="utf-8")
            enlace = e.documentos / "personal" / "enlace-divorcio.md"
            try:
                os.symlink(externo, enlace)
            except (OSError, NotImplementedError):
                print("  SALTADO: este sistema no permite crear symlinks (sin privilegio)")
                enlace = None
            # Un fichero que NO es un espejo: el barrido solo mira `*.md`, así que
            # ni lo abre ni lo mueve.
            extra = e.documentos / "personal" / "notas.txt"
            extra.write_text(_TEXTO_DIVORCIO + "\n", encoding="utf-8")
            plan = purga.previsualizar()
            motivos = " ".join(o.get("motivo", "")
                              for o in (_buscar(plan, "documentos").get("omitidos") or []))
            if enlace is not None:
                check("symlink" in motivos,
                      "documentos: el enlace simbólico se LISTA como omitido, no se sigue")
            r = purga.aplicar(plan["id"], ["papeleo-personal"])
            if enlace is not None:
                check(enlace.is_symlink() and externo.is_file(),
                      "documentos: el symlink sigue en su sitio y su destino también")
            check(extra.is_file() and extra.read_text(encoding="utf-8") == _TEXTO_DIVORCIO + "\n",
                  "documentos: lo que no es un espejo `.md` no se abre ni se mueve")
            check(r["almacenes"]["documentos"]["elementos"] == 1,
                  "documentos: solo se movió el espejo legítimo")

            # El barrido comprueba la CONTENCIÓN y la denylist de credenciales por
            # fichero antes de mover nada (no se fía del nombre ni de la carpeta).
            fuente = (Path(ROOT) / "backend" / "core" / "dominio" / "purga.py").read_text(
                encoding="utf-8")
            check("_dentro(resuelto, raiz)" in fuente,
                  "purga.py: cada espejo se comprueba contra la raíz del espejo (contención)")
            check("permissions.denied(resuelto)" in fuente,
                  "purga.py: la denylist de credenciales se aplica también a los espejos")
        finally:
            import shutil
            shutil.rmtree(fuera, ignore_errors=True)


def test_path_allowed_sigue_mandando_en_exportar():
    with Entorno() as e:
        e.montar()
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["papeleo-personal"])
        # La denylist de credenciales es la única regla que vale en los tres modos
        # de perm_files: ni siquiera el exportar del operador la salta.
        destino = e.tmp / "id_rsa.pem"
        rr = purga.exportar(r["lote"], str(destino))
        check(rr["ok"] is False and "no exporto ahí" in rr.get("error", ""),
              "exportar(): path_allowed/denylist sigue rechazando un destino de credenciales")
        check(not destino.exists(),
              "exportar(): rechazado → no se creó ni se copió nada en ese destino")


def test_rutas_de_los_almacenes_no_divergen():
    """Fuera del árbol de prueba: las rutas que usa la purga son las del dueño."""
    check(purga.DOCUMENTOS_DIR == ingesta.DOCUMENTOS_DIR,
          "purga.DOCUMENTOS_DIR es EXACTAMENTE ingesta.DOCUMENTOS_DIR (no una copia)")
    r = purga.rutas_almacenes()
    check(r["rag"] == rag._STORE, "rutas_almacenes(): el almacén del RAG es rag._STORE")
    check(r["opmem"] == opmem.OPS_FILE, "rutas_almacenes(): opmem es opmem.OPS_FILE")
    check(r["interacciones"] == selflearn._INTER,
          "rutas_almacenes(): interacciones es selflearn._INTER")
    check(r["audit"] == audit.AUDIT_FILE, "rutas_almacenes(): auditoría es audit.AUDIT_FILE")
    check(r["recall"] == opmem.RECALL_LOG, "rutas_almacenes(): recall es opmem.RECALL_LOG")
    check(r["webcache"] == websearch._cache_file(),
          "rutas_almacenes(): la caché web es la del dueño (websearch._cache_file())")


# =================================== runner ==================================
if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                          # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
