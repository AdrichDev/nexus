# -*- coding: utf-8 -*-
"""T37 — «olvida que…» llega a la purga de verdad, o no se promete.

EL HALLAZGO (declarado en el cierre de T15, `db5f1b8`). `skills/memory_graph`
contestaba «Si algo no cuadra, dime «olvida que…» y lo quito» y su tabla de
`patterns` no tenía NINGÚN intent que casara esa frase: caía al planificador del
cerebro, que contestaba algo plausible y NO TOCABA NADA. Es exactamente el bug
que CLAUDE.md prohíbe («cada vez que una frase normal acaba en el planificador,
es un bug») y dejaba el barrido de ocho almacenes de T15 inalcanzable para una
persona hablando.

Lo que se prueba aquí, y nada más que eso:
  * RED del enrutado: la frase NO llegaba a `memory_graph` (se comprueba contra
    el router REAL, no contra una copia de las regexes);
  * el intent `olvidar` enseña la previsualización del motor de purga y ARMA una
    confirmación `purga_memoria` — y antes del «sí» no se toca NI UN almacén;
  * el «sí» barre exactamente los almacenes que la previsualización enseñó, deja
    byte a byte lo ajeno y contesta con la misma honestidad que T15 (papelera,
    registros que NO se tocan, copias de seguridad intactas);
  * el «no» no barre nada y desarma;
  * sin nada que casar, se dice y NO se arma una confirmación;
  * una consulta sin ninguna palabra distintiva se rechaza con el umbral que ya
    está escrito (`longitud_minima_termino` + `palabras_vacias`), sin tocar nada;
  * este camino NO puede encender `incluir_logs`: los registros son un alcance
    aparte y solo salen si el operador lo pide expresamente;
  * anti-robo: el patrón nuevo no casa NINGUNA frase de otro SKILL.md.

REGLA ABSOLUTA DE ESTE FICHERO: no se toca el `data/` ni el `config/` del
operador. `NEXUS_DATA_DIR`/`NEXUS_CONFIG_DIR` se apuntan a una carpeta temporal
ANTES de importar backend, y además cada caso monta su propio árbol con notas y
documentos SINTÉTICOS y redirige las constantes de cada módulo dueño. Postgres se
fuerza OFFLINE (no se inserta, no se retira y no se borra ninguna fila real) y
Engram es un doble en memoria: no se abre ningún socket.

Ejecutar: .venv\\Scripts\\python.exe tests\\unit\\skills\\memory_graph\\test_olvidar.py
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

# ANTES de importar nada de backend: los datos y la configuración son de usar y
# tirar. La configuración del operador NUNCA se lee como si fuera la de la prueba
# (solo se copia el corpus de regresión, que viaja en el instalador).
_RAIZ_TMP = Path(tempfile.mkdtemp(prefix="nexus_olvidar_"))
os.environ["NEXUS_DATA_DIR"] = str(_RAIZ_TMP / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_RAIZ_TMP / "config")
(_RAIZ_TMP / "data").mkdir(parents=True, exist_ok=True)
(_RAIZ_TMP / "config").mkdir(parents=True, exist_ok=True)
try:
    shutil.copy2(ROOT / "config" / "corpus_regresion.json",
                 _RAIZ_TMP / "config" / "corpus_regresion.json")
except Exception:                                          # noqa: BLE001
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
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
confirm = importlib.import_module("backend.core.comun.confirm")
ingesta = importlib.import_module("backend.core.dominio.ingesta")
mem = importlib.import_module("backend.core.dominio.memory")
opmem = importlib.import_module("backend.core.dominio.opmem")
purga = importlib.import_module("backend.core.dominio.purga")
rag = importlib.import_module("backend.core.dominio.rag")
reglas = importlib.import_module("backend.core.dominio.reglas")
selflearn = importlib.import_module("backend.core.dominio.selflearn")
sl = importlib.import_module("backend.core.aplicacion.skills_loader")
websearch = importlib.import_module("backend.core.infraestructura.websearch")
eng = importlib.import_module("backend.core.infraestructura.engram_bridge")

sl.load_skills()

# ------------------------------- datos de prueba -----------------------------
# >120 caracteres a propósito: así se ejercitan las tres muestras (principio,
# medio y final) que usa el barrido de los demás almacenes.
_TEXTO_DIVORCIO = (
    "Mi divorcio con Marta se cerró en 2023 y no quiero que nadie de mi trabajo "
    "lo sepa nunca. El convenio regulador está firmado en el juzgado de "
    "Colmenar y las condiciones económicas se revisan cada mes de enero. Esto "
    "es lo único que quiero que desaparezca de todos los sitios donde lo "
    "guardaste, porque ya no me sirve de nada recordarlo.")
_TEXTO_RECETAS = ("Receta de tarta de queso de la abuela, con la base de "
                  "galleta y un poco de mermelada de fresa por encima.")

_FAKE_UMBRALES = {
    "minutos_vigencia_plan": 30,
    "papelera_aviso_items": 3000,
    # Sin categorías cerradas a propósito: lo que selecciona aquí es la CONSULTA
    # del operador, no el vocabulario de `umbrales.json`.
    "categorias": {},
    "emparejar_por_contenido": {
        "activo": True, "tipos": ["knowledge"],
        "longitud_minima_termino": 4, "minimo_terminos_fila": 6,
        "minimo_terminos_comunes": 6, "solape_minimo": 0.75,
        "palabras_vacias": ["para", "sobre", "todo", "cosa", "esto", "eso"],
    },
}


def _lineas_jsonl(campos):
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in campos)


class Entorno:
    """Árbol de usar y tirar + todas las rutas de almacén apuntadas dentro + espías."""

    def __init__(self):
        self.llamadas_forget = []
        self.espia = {"rag.purgar_fuentes": 0, "opmem.forget": 0,
                      "engram.forget_sync": 0, "webcache.escritor": 0,
                      "purga.retirar_nota": 0, "purga._exportar_copia_personal": 0,
                      "previsualizar.kwargs": [], "aplicar.kwargs": []}

    # ------------------------------ ciclo de vida ----------------------------
    def _poner(self, obj, nombre, valor):
        self._parches.append((obj, nombre, hasattr(obj, nombre), getattr(obj, nombre, None)))
        setattr(obj, nombre, valor)

    def _espiar(self, obj, nombre, etiqueta):
        """Envuelve un escritor real: cuenta la llamada y DELEGA en el original.

        Si existe la clave «<etiqueta>.kwargs», se apuntan además los argumentos
        con los que se llamó: así se demuestra que este camino no enciende
        `incluir_logs`."""
        original = getattr(obj, nombre)
        self.espia[f"_{etiqueta}_orig"] = original

        def _envuelto(*a, **kw):
            self.espia[etiqueta] = self.espia.get(etiqueta, 0) + 1
            cubo = self.espia.get(f"{etiqueta}.kwargs")
            if isinstance(cubo, list):
                cubo.append(dict(kw))
            return original(*a, **kw)

        self._poner(obj, nombre, _envuelto)

    def __enter__(self):
        self._parches = []
        self.tmp = Path(tempfile.mkdtemp(prefix="nexus_olvidar_caso_", dir=str(_RAIZ_TMP)))
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

        # ESPÍAS de los escritores de cada almacén: antes del «sí», CERO.
        self._espiar(rag, "purgar_fuentes", "rag.purgar_fuentes")
        self._espiar(opmem, "forget", "opmem.forget")
        self._espiar(purga, "retirar_nota", "purga.retirar_nota")
        self._espiar(purga, "_exportar_copia_personal", "purga._exportar_copia_personal")
        self._espiar(purga, "_barrer_webcache", "webcache.escritor")
        self._espiar(purga, "previsualizar", "previsualizar")
        self._espiar(purga, "aplicar", "aplicar")
        self.espia["engram.forget_sync"] = 0
        confirm.clear()
        return self

    def __exit__(self, *exc):
        confirm.clear()
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
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    # -------------------------------- dobles --------------------------------
    def _engram_status(self, ctx=None):
        return {"installed": True, "exe": "/falso/engram",
                "url": "http://127.0.0.1:7437", "last_error": "", "alive_cached": True}

    def _engram_forget(self, ctx, query, timeout=8):
        self.espia["engram.forget_sync"] = self.espia.get("engram.forget_sync", 0) + 1
        self.llamadas_forget.append(query)
        return {"ok": True, "no_completado": False, "borrados": 1, "ids": [7],
                "consulta": query, "error": "", "nota": "1 recuerdo borrado"}

    # ------------------------------- fixtures -------------------------------
    def montar(self, logs_en_el_plan=False):
        self.nota = self.memory / "divorcio-marta.md"
        self.nota.write_text(_TEXTO_DIVORCIO + "\n", encoding="utf-8")
        self.nota_ajena = self.memory / "recetas.md"
        self.nota_ajena.write_text(_TEXTO_RECETAS + "\n", encoding="utf-8")

        dominio = self.documentos / "personal"
        dominio.mkdir(parents=True)
        self.espejo = dominio / "divorcio.pdf.9f2a1b3c.md"
        self.espejo.write_text(
            "---\norigen: C:\\documentos\\divorcio.pdf\ndominio: personal\n"
            f"etiqueta: normal\ningerido: 2026-01-01T00:00:00+00:00\n---\n\n{_TEXTO_DIVORCIO}\n",
            encoding="utf-8")
        self.espejo_ajeno = dominio / "recetas.pdf.7c1d2e3f.md"
        self.espejo_ajeno.write_text(
            "---\norigen: C:\\documentos\\recetas.pdf\ndominio: personal\n"
            f"etiqueta: normal\ningerido: 2026-01-01T00:00:00+00:00\n---\n\n{_TEXTO_RECETAS}\n",
            encoding="utf-8")

        self.rag = rag._STORE
        self.rag.parent.mkdir(parents=True, exist_ok=True)
        self.rag_ajeno = {"id": "knowledge:gimnasio", "kind": "knowledge",
                          "text": "El horario del gimnasio es de 7 a 22.",
                          "meta": {"source": "gimnasio.md"}, "vec": None, "ts": 1.0}
        self.rag.write_text(_lineas_jsonl([
            {"id": "knowledge:1", "kind": "knowledge",
             "text": f"[divorcio.pdf] {_TEXTO_DIVORCIO}",
             "meta": {"source": "divorcio.pdf"}, "vec": None, "ts": 1.0},
            self.rag_ajeno,
        ]), encoding="utf-8")
        self.rag_linea_ajena = json.dumps(self.rag_ajeno, ensure_ascii=False) + "\n"

        opmem.remember(_TEXTO_DIVORCIO, kind="tecnico", scope="global",
                       source="operador", origen="pc")
        self.regla_ajena = "Antes de borrar algo, enséñame exactamente qué vas a borrar."
        opmem.remember(self.regla_ajena, kind="regla", scope="global",
                       source="operador", origen="pc")

        self.webcache_ajena = {"ts": time.time(), "data": "El tiempo en Madrid: 24 grados."}
        self.webcache.write_text(json.dumps({
            "p::https://ejemplo/divorcio": {"ts": time.time(),
                                            "data": f"<html>{_TEXTO_DIVORCIO}</html>"},
            "q::el tiempo en madrid": self.webcache_ajena,
        }, ensure_ascii=False), encoding="utf-8")

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

        self.jobs = self.data / "jobs.json"
        self.jobs.write_text(json.dumps([
            {"id": "j-1", "num": 1, "request": "resume mi divorcio",
             "result": _TEXTO_DIVORCIO, "status": "completed", "seen": True},
            {"id": "j-2", "num": 2, "request": "investiga la receta",
             "result": _TEXTO_RECETAS, "status": "completed", "seen": True},
        ], ensure_ascii=False, indent=1), encoding="utf-8")

        import zipfile
        self.backups_dir = self.data / "backups"
        self.backups_dir.mkdir()
        self.backups = []
        for i in range(2):
            z = self.backups_dir / f"nexus-data-2026010{i + 1}.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("jobs.json", "[]")
                if i == 0:
                    zf.writestr("memory/divorcio-marta.md", _TEXTO_DIVORCIO)
            os.utime(z, (1_767_225_600 + i * 86400,) * 2)
            self.backups.append(z)
        return self

    # ------------------------------ lo que se vigila --------------------------
    def ficheros_de_almacen(self):
        """Los almacenes cuyo CONTENIDO no puede cambiar antes del «sí».

        `audit.jsonl` NO entra en la foto, y no es una excepción cómoda: armar una
        confirmación deja su traza en la auditoría (`confirm_request:…`), que es
        justo lo que se exige de una acción destructiva. Lo que sí se comprueba, en
        cada caso, es que la línea del incidente SIGUE ahí (nadie la ha quitado).
        """
        rutas = [self.rag, self.data / "rag" / "indexed.json", opmem.OPS_FILE,
                 self.webcache, self.jobs, selflearn._INTER, opmem.RECALL_LOG,
                 self.nota, self.nota_ajena]
        return {p: (p.read_bytes() if p.is_file() else None) for p in rutas}

    def linea_del_incidente_sigue_en_auditoria(self):
        ruta, sucia, _limpia = self.logs["audit"]
        try:
            return json.dumps(sucia, ensure_ascii=False) in ruta.read_text(encoding="utf-8")
        except Exception:                                      # noqa: BLE001
            return False

    def ctx(self):
        return {"pg": mem.pg, "graph": _GrafoDoble(), "channel": "pc"}


class _GrafoDoble:
    """Grafo de notas de mentira: la purga no lo usa para barrer (solo escribe la
    papelera de `data/memory/`), pero `handle()` lo recibe en el contexto."""

    def append_daily(self, *a, **k):
        return "diaria.md"

    def write_note(self, *a, **k):
        return "nota.md"

    def search(self, *a, **k):
        return []

    def graph(self):
        return {"nodes": [], "edges": []}


# -------------------------------- utilidades ---------------------------------
def _ruta(texto):
    obj = sl.route(texto)
    if obj is None:
        return None, None, None
    return obj[0].folder, obj[1], obj[2]


def _skill():
    sk = sl.get_skills().get("memory_graph")
    assert sk is not None and sk.status != "error", "memory_graph no carga"
    return sk


def _armar(texto, env):
    """Ejecuta el intent como lo haría el cerebro y devuelve (reply, data)."""
    folder, intent, match = _ruta(texto)
    r = asyncio.run(_skill().module.handle(intent, texto, match, env.ctx()))
    return r


def _si():
    return asyncio.run(confirm.answer("sí", "pc"))


def _no():
    return asyncio.run(confirm.answer("no", "pc"))


# ============================== 1) RED del enrutado ==========================
def test_la_frase_prometida_llega_al_intent_y_no_al_planificador():
    """El bug declarado: la skill prometía «olvida que…» y nadie la cazaba."""
    print("== 1) «olvida que me divorcié» tiene dueño ==")
    for frase in ("olvida que me divorcié",
                  "olvida el divorcio con Marta",
                  "olvídate de la mudanza",
                  "borra el recuerdo de la entrevista",
                  "no recuerdes el número de la cuenta"):
        folder, intent, match = _ruta(frase)
        check(folder == "memory_graph" and intent == "olvidar",
              f"«{frase}» acaba en el planificador o en otra skill "
              f"({folder}/{intent}): la skill promete olvidarla y no la atiende nadie")
        if folder == "memory_graph" and intent == "olvidar":
            check(bool((match.group("q") or "").strip()),
                  f"«{frase}» no captura QUÉ hay que olvidar")
    # Y la frontera con la vecina, escrita: las reglas son de engram.
    folder, intent, _ = _ruta("olvida la regla de trabajar de noche")
    check((folder, intent) == ("engram", "forget_rule"),
          f"«olvida la regla …» no es de esta skill: la atiende {folder}/{intent}")


# ========================== 2) antes del «sí» no se toca nada =================
def test_el_preview_ensena_y_arma_sin_tocar_ningun_almacen():
    print("== 2) la previsualización enseña y arma la confirmación; nada se toca ==")
    with Entorno() as e:
        e.montar()
        antes = e.ficheros_de_almacen()
        reply = _armar("olvida que me divorcié", e)
        texto = reply.get("reply") or ""
        check(bool(texto), "el intent no contesta nada")
        check("divorcio-marta.md" in texto,
              f"la previsualización no nombra la nota que ha encontrado: «{texto[:200]}»")
        check(reply.get("data", {}).get("confirm") is True,
              "el intent no declara que ha armado una confirmación")
        p = confirm.pending("pc")
        check(p is not None and p.get("kind") == "purga_memoria",
              f"no hay confirmación «purga_memoria» armada ({p and p.get('kind')})")
        check(p is not None and p.get("summary") == texto,
              "la pregunta armada no es lo que el operador lee")
        for etiqueta in ("rag.purgar_fuentes", "opmem.forget", "engram.forget_sync",
                         "webcache.escritor", "purga.retirar_nota"):
            check(e.espia.get(etiqueta, 0) == 0,
                  f"antes del «sí» ya se llamó a {etiqueta} ({e.espia.get(etiqueta)})")
        despues = e.ficheros_de_almacen()
        for ruta, contenido in antes.items():
            check(despues.get(ruta) == contenido,
                  f"antes del «sí» cambió un almacén: {ruta}")
        check(e.linea_del_incidente_sigue_en_auditoria(),
              "antes del «sí» se quitó de la auditoría la línea del incidente")
        check(e.nota.is_file(), "la nota se movió antes de confirmar")
        # El alcance opt-in NO se pide desde aquí.
        kw = e.espia["previsualizar.kwargs"]
        check(kw and all(k.get("incluir_logs") in (None, False) for k in kw),
              f"la previsualización de este camino pidió incluir_logs: {kw}")


# ============================== 3) el «sí» barre =============================
def test_el_si_barre_los_almacenes_que_enseno_y_respeta_lo_ajeno():
    print("== 3) el «sí» barre exactamente lo enseñado ==")
    with Entorno() as e:
        e.montar()
        _armar("olvida que me divorcié", e)
        plan = list(purga._planes.values())[-1]
        almacenes_plan = {a["id"]: a for a in plan["almacenes"]}

        respuesta = _si()
        check(isinstance(respuesta, str) and bool(respuesta),
              f"el «sí» no devolvió respuesta: {respuesta!r}")

        # 1) la nota va a la PAPELERA (restaurable), no se destruye
        check(not e.nota.is_file(), "la nota purgada sigue en data/memory")
        en_papelera = list(purga.PAPELERA_DIR.rglob("divorcio-marta.md"))
        check(len(en_papelera) == 1,
              "la nota no está en la papelera: no sería restaurable")
        check(e.nota_ajena.read_text(encoding="utf-8") == _TEXTO_RECETAS + "\n",
              "la nota AJENA cambió")

        # 2) sólo se tocaron los almacenes que la previsualización marcó incl.
        aplicar_kw = e.espia["aplicar.kwargs"]
        check(aplicar_kw and aplicar_kw[-1].get("incluir_logs") in (None, False),
              f"el «sí» pidió incluir_logs: {aplicar_kw}")

        # 3) el almacén vectorial: fuera el hecho, idéntico lo ajeno
        texto_rag = e.rag.read_text(encoding="utf-8")
        check("Marta" not in texto_rag, "el texto purgado sigue en knowledge.jsonl")
        check(e.rag_linea_ajena in texto_rag.splitlines(keepends=True),
              "el registro AJENO del almacén vectorial cambió")
        check(e.espia["rag.purgar_fuentes"] == 1,
              "no se barrió el almacén vectorial exactamente una vez")

        # 4) el espejo del documento va a la misma papelera
        check(not e.espejo.is_file(), "el espejo del documento sigue en su sitio")
        check(e.espejo_ajeno.is_file(), "el espejo AJENO se movió")

        # 5) memoria operativa y Engram
        textos = [it.get("text", "") for it in opmem._load()]
        check(not any("Marta" in t for t in textos),
              "el recuerdo de la memoria operativa sigue vivo")
        check(e.regla_ajena in textos, "la regla AJENA de la memoria operativa se perdió")
        check(e.espia["engram.forget_sync"] == 1,
              "no se le pidió a Engram olvidar exactamente una vez")
        check(e.llamadas_forget and "divorcio" in e.llamadas_forget[0].lower(),
              f"la consulta de olvido a Engram no nombra el tema: {e.llamadas_forget}")

        # 6) la caché web pierde la entrada y conserva la ajena
        cache = json.loads(e.webcache.read_text(encoding="utf-8"))
        check("q::el tiempo en madrid" in cache and len(cache) == 1,
              "la caché web no quedó con la entrada ajena y sin la purgada")

        # 7) registros y copias de seguridad: NO se tocan
        for clave, (ruta, sucia, limpia) in e.logs.items():
            contenido = ruta.read_text(encoding="utf-8")
            check(json.dumps(sucia, ensure_ascii=False) in contenido,
                  f"{clave}: este camino tocó los registros de conversación")
            check(json.dumps(limpia, ensure_ascii=False) in contenido,
                  f"{clave}: la línea ajena de los registros cambió")
        check(json.loads(e.jobs.read_text(encoding="utf-8"))[0]["id"] == "j-1",
              "jobs.json se tocó desde este camino (es alcance opt-in)")
        for z in e.backups:
            check(z.is_file(), f"se borró una copia de seguridad: {z.name}")

        # 8) el informe es el de T15 y la respuesta lo cuenta con la misma honestidad
        plan_ids = set(almacenes_plan)
        check("resumen" in respuesta or "lote" in respuesta.lower(),
              f"la respuesta no es el informe del motor de purga: «{respuesta[:200]}»")
        check("papelera" in respuesta.lower(),
              "la respuesta no dice que las notas están en la papelera (restaurables)")
        check("registro" in respuesta.lower(),
              "la respuesta no dice qué pasa con los registros de conversación")
        check("copia" in respuesta.lower() or "backup" in respuesta.lower(),
              "la respuesta no dice qué pasa con las copias de seguridad")
        check(plan_ids, "sanity: el plan tenía almacenes")
        # «exactamente los de la previsualización»: nada tocado fuera de la lista
        r_almacenes = {a["id"] for a in plan["almacenes"]}
        check("backups" in r_almacenes, "sanity: las copias se listan en el plan")
        check(almacenes_plan["logs"]["estado"] == "no_incluido",
              "la previsualización no declaró los registros como NO incluidos")
        check(almacenes_plan["backups"]["accion"] == "no_se_toca",
              "la previsualización no declaró las copias como intocables")


# ============================== 4) el «no» ==================================
def test_el_no_no_barre_nada_y_desarma():
    print("== 4) el «no» no barre nada y desarma ==")
    with Entorno() as e:
        e.montar()
        antes = e.ficheros_de_almacen()
        _armar("olvida que me divorcié", e)
        respuesta = _no()
        check(isinstance(respuesta, str) and respuesta,
              "el «no» no contesta nada al operador")
        check(confirm.pending("pc") is None, "el «no» dejó la confirmación armada")
        for etiqueta in ("rag.purgar_fuentes", "opmem.forget", "engram.forget_sync",
                         "webcache.escritor", "purga.retirar_nota"):
            check(e.espia.get(etiqueta, 0) == 0,
                  f"el «no» llamó a {etiqueta} ({e.espia.get(etiqueta)})")
        for ruta, contenido in antes.items():
            check((ruta.read_bytes() if ruta.is_file() else None) == contenido,
                  f"el «no» cambió un almacén: {ruta}")
        check(e.linea_del_incidente_sigue_en_auditoria(),
              "el «no» quitó de la auditoría la línea del incidente")


# ======================= 5) nada que casar: se dice y no se arma =============
def test_sin_nada_que_casar_lo_dice_y_no_arma_confirmacion():
    print("== 5) sin nada que casar: mensaje honesto y NADA armado ==")
    with Entorno() as e:
        e.montar()
        antes = e.ficheros_de_almacen()
        reply = _armar("olvida que tengo un yate en Cerdeña", e)
        texto = reply.get("reply") or ""
        check("no encontr" in texto.lower(),
              f"sin nada que casar no lo dice: «{texto[:200]}»")
        check("yate" in texto.lower() or "cerde" in texto.lower(),
              "no repite lo que el operador pidió olvidar")
        check(confirm.pending("pc") is None,
              "sin nada que casar se armó una confirmación igualmente")
        check(reply.get("data", {}).get("confirm") in (None, False),
              "el intent dice haber armado una confirmación sin nada que borrar")
        for ruta, contenido in antes.items():
            check((ruta.read_bytes() if ruta.is_file() else None) == contenido,
                  f"sin nada que casar se tocó {ruta}")


# ==================== 6) consulta sin palabras distintivas ===================
def test_la_consulta_vaga_se_rechaza_con_el_umbral_escrito():
    print("== 6) consulta vaga: se rechaza con el umbral que ya existe ==")
    with Entorno() as e:
        e.montar()
        antes = e.ficheros_de_almacen()
        for frase in ("olvida eso", "olvida la cosa"):
            reply = _armar(frase, e)
            texto = reply.get("reply") or ""
            check("no voy a" in texto.lower() or "más concreta" in texto.lower(),
                  f"«{frase}» no se rechaza con un motivo: «{texto[:200]}»")
            check("4" in texto,
                  f"«{frase}»: el motivo no nombra el umbral documentado (4 caracteres)")
            check(confirm.pending("pc") is None,
                  f"«{frase}» armó una confirmación con una consulta vaga")
        for etiqueta in ("rag.purgar_fuentes", "opmem.forget", "engram.forget_sync",
                         "webcache.escritor", "purga.retirar_nota"):
            check(e.espia.get(etiqueta, 0) == 0,
                  f"una consulta vaga llamó a {etiqueta}")
        for ruta, contenido in antes.items():
            check((ruta.read_bytes() if ruta.is_file() else None) == contenido,
                  f"una consulta vaga tocó {ruta}")
        check(confirm.pending("pc") is None, "quedó algo armado tras una consulta vaga")


# ===================== 7) incluir_logs no se enciende por aquí ==============
def test_incluir_logs_no_se_puede_encender_por_este_camino():
    print("== 7) los registros siguen siendo un alcance aparte ==")
    with Entorno() as e:
        e.montar()
        reply = _armar("olvida que me divorcié", e)
        plan = list(purga._planes.values())[-1]
        check(plan["incluir_logs"] is False,
              "el plan nació con incluir_logs encendido")
        logs = [a for a in plan["almacenes"] if a["id"] == "logs"][0]
        check(logs["estado"] == "no_incluido" and logs["incluido"] is False,
              "la previsualización de este camino incluyó los registros")
        check("registro" in (reply.get("reply") or "").lower(),
              "la previsualización no avisa de que los registros no se tocan")
        # Y lo que se dice, se cumple: tras el «sí» los registros siguen ahí.
        _si()
        for clave, (ruta, sucia, _limpia) in e.logs.items():
            check(json.dumps(sucia, ensure_ascii=False) in ruta.read_text(encoding="utf-8"),
                  f"{clave}: los registros se barrieron sin que nadie lo pidiera")


# ============================== 8) anti-robo ================================
def test_el_patron_nuevo_no_roba_frases_de_otras_skills():
    """La prueba de no-robo, medida contra el corpus REAL de los SKILL.md."""
    print("== 8) el patrón nuevo no casa ninguna frase ajena ==")
    rx = _skill().patterns["olvidar"]
    pares = reglas.corpus_prometido(con_origen=True)
    regresion = [str(e.get("frase") or "") for e in reglas.corpus_regresion()]
    check(len(pares) > 250, f"el corpus solo tiene {len(pares)} apariciones: no sirve")
    check(len(regresion) >= 30,
          f"el corpus de regresión solo tiene {len(regresion)} frases: el barrido "
          "anti-robo mediría contra menos de lo que cree")
    robadas = []
    for carpeta, frase in pares:
        if carpeta == "memory_graph":
            continue
        if rx.search(frase):
            robadas.append(f"{carpeta}: «{frase}»")
    for frase in regresion:
        if frase and rx.search(frase):
            robadas.append(f"corpus_regresion: «{frase}»")
    check(not robadas,
          "el patrón «olvidar» se lleva frases que no son suyas: " + "; ".join(robadas[:5]))

    # La frontera práctica: «borra» a secas es de tasks_board, y «olvida la
    # regla» de engram. Se comprueba ejecutando el router, no leyendo la regex.
    for frase, dueno in (("borra la tarea de comprar pan", "tasks_board"),
                         ("olvida la regla de no escribir por la noche", "engram")):
        folder, _intent, _m = _ruta(frase)
        check(folder == dueno,
              f"«{frase}» ya no la atiende {dueno}: ahora {folder}")

    # Y las cuatro formas prometidas SÍ son suyas (si no, el caso de arriba
    # pasaría por no casar nada en absoluto).
    check(all(rx.search(f) for f in
              ("olvida que me divorcié", "olvídate de la mudanza",
               "borra el recuerdo de la entrevista", "no recuerdes el número de la cuenta")),
          "el patrón no casa alguna de las formas que la skill promete")


# =================================== runner ==================================
if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                          # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", type(exc).__name__, exc)
    shutil.rmtree(_RAIZ_TMP, ignore_errors=True)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
