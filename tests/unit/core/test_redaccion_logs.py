# -*- coding: utf-8 -*-
"""NADA DE LO QUE ESCRIBE NEXUS GUARDA UN SECRETO EN CLARO (AI-02 / PRIV-01).

El fallo que se prueba aquí (auditoría del 30/07/2026, P1-5):

    «la contraseña de la base es <pegada aquí>»
    → data/interactions.jsonl lo guardaba tal cual,
    → data/logs/audit.jsonl lo guardaba tal cual,
    → y de interactions.jsonl salen los 120 ejemplos que se mandan a
      `llm.distill`, que puede ser un proveedor de NUBE.

O sea: lo que el operador dicta acaba en disco para siempre y, además, puede
salir del equipo. Lo que se comprueba:

  * un texto con pinta de secreto (`sk-…`, un JWT, `postgres://u:p@host`) sale
    REDACTADO en `interactions.jsonl`, en lo que se manda al destilado, en
    `audit.jsonl` y en `recall.jsonl`;
  * el formato de los ficheros no cambia: los consumidores (`_recent`,
    `ultima_orden`, `audit.tail`) siguen leyéndolos igual, y el recorte a 400
    caracteres del registro de auditoría sigue ahí;
  * FAIL CLOSED: si la redacción revienta, los campos de texto libre se quedan
    VACÍOS. Se pierde la traza, no la privacidad.

Todo con cadenas sintéticas y carpetas de usar y tirar; sin red, sin base de
datos, sin configuración de producción. Nivel M.
Ejecutar: python tests/unit/core/test_redaccion_logs.py
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

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


# Caja de arena ANTES de importar el backend: los módulos atan sus rutas
# (interactions.jsonl, audit.jsonl, recall.jsonl) al importarse.
_SANDBOX = Path(tempfile.mkdtemp(prefix="nexus_redaccion_"))
(_SANDBOX / "data").mkdir()
(_SANDBOX / "config").mkdir()
(_SANDBOX / "config" / "settings.json").write_text(json.dumps({
    "setup_done": True, "operator_name": "Operador de Prueba",
    "llm_provider": "ollama", "self_learning": False,
}), encoding="utf-8")
os.environ["NEXUS_DATA_DIR"] = str(_SANDBOX / "data")
os.environ["NEXUS_CONFIG_DIR"] = str(_SANDBOX / "config")

from backend.core.comun import audit, secretos          # noqa: E402
from backend.core.dominio import opmem, selflearn      # noqa: E402
from backend.core.infraestructura import llm           # noqa: E402

OCULTO = secretos.OCULTO

# Secretos SINTÉTICOS: no son de nadie y no sirven en ningún sitio.
SK = "sk-" + "q7Wr3nT5yU8iO1pA4sD6fG"
JWT = ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
       "abcdefghijklmnop")
PG = "postgres://operador:Cl4v3S3cr3t4@db.local:5432/nexus"
TEXTO = f"apunta que la clave del servidor es {SK} y mi sesión es {JWT}, la base {PG}"
RESPUESTA = f"Anotado. He guardado {SK} en el sitio de siempre."


def _lineas(path: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []


def _sin_secretos(texto: str) -> bool:
    return not any(s in (texto or "") for s in (SK, JWT, "Cl4v3S3cr3t4", JWT[-16:]))


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
#  1. interactions.jsonl — se redacta AL ESCRIBIR
# ══════════════════════════════════════════════════════════════════════════════
def test_interacciones_redactadas():
    print("· data/interactions.jsonl")
    toca = selflearn.record_interaction(TEXTO, RESPUESTA, "files")
    check(toca is False or toca is True, "record_interaction sigue devolviendo su booleano")
    filas = _lineas(selflearn._INTER)
    check(bool(filas), "la interacción se ha escrito")
    fila = filas[-1]
    check(set(fila) >= {"t", "r", "skill", "ok"},
          f"el FORMATO no cambia: mismas claves de siempre ({sorted(fila)})")
    check(_sin_secretos(fila["t"]),
          "el texto del operador ya no lleva el secreto")
    check(_sin_secretos(fila["r"]),
          "ni la respuesta del asistente")
    check(OCULTO in fila["t"] and OCULTO in fila["r"],
          "y queda la marca de que ALGO se ocultó, no un hueco silencioso")
    check("apunta que la clave del servidor es" in fila["t"],
          "el resto de la frase se conserva: la redacción no destroza el texto")
    check(fila["skill"] == "files" and fila["ok"] is True,
          "los demás campos siguen intactos")

    # Consumidores: el fichero se sigue leyendo igual.
    check(len(selflearn._recent(10)) == len(filas),
          "selflearn._recent sigue parseando todas las líneas")
    ultima = selflearn.ultima_orden()
    check(ultima and _sin_secretos(ultima),
          "y ultima_orden (la que usa aprendizaje) devuelve la versión limpia")


# ══════════════════════════════════════════════════════════════════════════════
#  2. EL DESTILADO — lo que sale del equipo va limpio por construcción
# ══════════════════════════════════════════════════════════════════════════════
def test_destilado_limpio():
    print("· el prompt del auto-reentrenamiento")
    for i in range(4):                       # hace falta muestra suficiente
        selflearn.record_interaction(f"frase {i} sobre {SK}", f"respuesta {i}", "files")

    capturado = {}

    async def _distill(system, user, max_tokens=900):
        capturado["system"] = system
        capturado["user"] = user
        # El modelo DEVUELVE el secreto que ha visto: el perfil no puede quedárselo.
        return ("**Tono y estilo**\n- directo y sin florituras\n"
                f"**Temas**\n- la clave era {SK}\n")

    original = llm.distill
    llm.distill = _distill
    try:
        perfil = run(selflearn.retrain(force=True))
    finally:
        llm.distill = original
    check(bool(capturado.get("user")), "se ha llamado al destilado")
    check(_sin_secretos(capturado["user"]),
          "las interacciones que se mandan al destilado ya no llevan el secreto")
    check(OCULTO in capturado["user"], "con su marca de ocultación")
    check(bool(perfil), "el perfil se ha generado")
    check(_sin_secretos(perfil),
          "y lo que devuelve el modelo también se redacta antes de guardarlo")
    check(_sin_secretos(selflearn.operator_profile()),
          "operator_profile() (que se inyecta en TODOS los prompts) está limpio")


# ══════════════════════════════════════════════════════════════════════════════
#  3. audit.jsonl — redactado, recortado y rotable
# ══════════════════════════════════════════════════════════════════════════════
def test_auditoria_redactada():
    print("· data/logs/audit.jsonl")
    audit.log(action="prueba_redaccion", actor="operador", request=TEXTO,
              interpreted=TEXTO, result=RESPUESTA, destructive=True, confirmed=True)
    registros = _lineas(audit.AUDIT_FILE)
    check(bool(registros), "el registro se ha escrito")
    rec = registros[-1]
    for campo in ("request", "interpreted", "result"):
        check(_sin_secretos(rec.get(campo, "")),
              f"«{campo}» ya no lleva el secreto")
        check(OCULTO in (rec.get(campo) or ""),
              f"«{campo}» deja la marca de lo ocultado")
    check(rec["destructive"] is True and rec["confirmed"] is True,
          "lo que NO es texto libre sigue igual (para eso está la auditoría)")
    check(rec["action"] == "prueba_redaccion" and rec["actor"] == "operador",
          "la acción y el actor siguen ahí")

    # El recorte a 400 caracteres no se pierde por redactar antes.
    largo = "revisa la carpeta de facturas " * 40          # 1120 caracteres, sin secretos
    audit.log(action="prueba_recorte", request=largo)
    rec = _lineas(audit.AUDIT_FILE)[-1]
    check(len(rec["request"]) == 400,
          f"el recorte a 400 caracteres sigue igual ({len(rec['request'])})")

    # tail() sigue sirviendo para leerla.
    ultimos = audit.tail(5)
    check(len(ultimos) == len(_lineas(audit.AUDIT_FILE)),
          f"audit.tail sigue leyendo ({len(ultimos)})")
    check(all(_sin_secretos(r.get("request", "")) for r in ultimos),
          "y lo que devuelve está limpio")


# ══════════════════════════════════════════════════════════════════════════════
#  4. recall.jsonl — la frase que se usó para responder
# ══════════════════════════════════════════════════════════════════════════════
def test_recall_redactado():
    print("· data/logs/recall.jsonl")
    opmem.note_use([], TEXTO, channel="pc")
    filas = _lineas(opmem.RECALL_LOG)
    check(bool(filas), "el registro de recall se ha escrito")
    rec = filas[-1]
    check(_sin_secretos(rec.get("texto", "")),
          "la frase del operador ya no lleva el secreto")
    check(OCULTO in (rec.get("texto") or ""),
          "con su marca de ocultación")
    check(set(rec) >= {"ts", "channel", "texto", "reglas", "documentos"},
          f"el FORMATO no cambia ({sorted(rec)})")
    check(len(rec["texto"]) <= 200, "y sigue recortada a 200 caracteres")
    check(_sin_secretos(opmem._last_applied["pc"]["texto"]),
          "tampoco en la copia que se usa para «¿por qué has hecho eso?»")


# ══════════════════════════════════════════════════════════════════════════════
#  5. FAIL CLOSED — si la redacción revienta, no se escribe en crudo
# ══════════════════════════════════════════════════════════════════════════════
def test_redaccion_rota_no_escribe_en_crudo():
    print("· si la redacción falla, los campos se quedan vacíos")

    def _rompe(_texto):
        raise RuntimeError("redacción rota (doble de prueba)")

    antes_audit = len(_lineas(audit.AUDIT_FILE))
    antes_inter = len(_lineas(selflearn._INTER))
    antes_recall = len(_lineas(opmem.RECALL_LOG))

    original = secretos.redactar
    secretos.redactar = _rompe
    try:
        audit.log(action="prueba_fallo", request=TEXTO, interpreted=TEXTO,
                  result=RESPUESTA, error=TEXTO)
        selflearn.record_interaction(TEXTO, RESPUESTA, "files")
        opmem.note_use([], TEXTO, channel="fallo")
    finally:
        secretos.redactar = original

    rec = _lineas(audit.AUDIT_FILE)[-1]
    check(len(_lineas(audit.AUDIT_FILE)) == antes_audit + 1, "la traza se sigue apuntando")
    for campo in ("request", "interpreted", "result", "error"):
        check(rec.get(campo) == "",
              f"«{campo}» se cae ENTERO en vez de escribirse en crudo")
    check(rec["action"] == "prueba_fallo",
          "pero la acción queda: hay rastro de que pasó algo")

    fila = _lineas(selflearn._INTER)[-1]
    check(len(_lineas(selflearn._INTER)) == antes_inter + 1,
          "la interacción tampoco desaparece sin más")
    check(fila["t"] == "" and fila["r"] == "",
          "con los campos de texto vacíos")

    rec = _lineas(opmem.RECALL_LOG)[-1]
    check(len(_lineas(opmem.RECALL_LOG)) == antes_recall + 1, "el recall se apunta")
    check(rec["texto"] == "", "con la frase vacía")

    for ruta in (audit.AUDIT_FILE, selflearn._INTER, opmem.RECALL_LOG):
        crudo = ruta.read_text(encoding="utf-8")
        check(_sin_secretos(crudo),
              f"y ni un secreto en crudo en {ruta.name}")


def main() -> int:
    for f in (test_interacciones_redactadas, test_destilado_limpio,
              test_auditoria_redactada, test_recall_redactado,
              test_redaccion_rota_no_escribe_en_crudo):
        try:
            f()
        except Exception as e:                               # noqa: BLE001
            import traceback
            _fail.append(f"EXCEPCIÓN en {f.__name__}: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN en", f.__name__, ":", type(e).__name__, e)
            traceback.print_exc()
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(code)
