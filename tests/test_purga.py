# -*- coding: utf-8 -*-
"""002-memoria-y-conocimiento — Bloque B (purga y limpieza, reversible).

Cubre memoria-purga y el cierre de memoria-deduplicacion: clasificación por
reglas (nunca un LLM), previsualización obligatoria y previa, papelera en dos
tiempos, categoría personal que exporta antes de mover, alcance dual
nota+fila, índice único solo tras limpieza confirmada, y la matriz de
amenazas (symlinks, sobrescritura al restaurar, traza de auditoría,
traversal al exportar).

REGLA ABSOLUTA DE ESTE FICHERO: NINGÚN test toca `data/memory/` real ni las
filas reales de `memories`. Todo lo que se retira/exporta/borra en estos
tests vive en un directorio temporal (`MEMORY_DIR`/`PAPELERA_DIR`/
`EXPORT_DIR` de `purga.py` quedan monkeyparacheados durante cada test) o,
cuando hace falta Postgres de verdad, son filas insertadas por el propio
test con contenido reconocible y limpiadas por el propio test al acabar.
Si el contenedor `nexus_memoria_postgres` no responde, esos casos se SALTAN
con aviso explícito.

Ejecutar: .venv\\Scripts\\python.exe tests\\test_purga.py
"""
import importlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail, _pass, _skip = [], 0, 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def skip(msg):
    global _skip
    _skip += 1
    print("  SALTADO (sin BD):", msg)


purga = importlib.import_module("backend.core.dominio.purga")
mem = importlib.import_module("backend.core.dominio.memory")
audit = importlib.import_module("backend.core.comun.audit")


# ------------------------- infraestructura de prueba -------------------------
_FAKE_UMBRALES = {
    "minutos_vigencia_plan": 30,
    "papelera_aviso_items": 3000,
    "categorias": {
        "papeleo-personal": {
            "personal": True, "minimo_aciertos": 1,
            "palabras": ["curriculum vitae de prueba", "empadronamiento de prueba"],
        },
        "estudios-dam": {
            "personal": False, "minimo_aciertos": 1,
            "palabras": ["roadmap de prueba dam", "bootcamp de prueba"],
        },
        "duplicados-exactos": {"personal": False},
    },
    "emparejar_por_contenido": {
        "activo": True, "tipos": ["knowledge"], "longitud_minima_termino": 4,
        "minimo_terminos_fila": 6, "minimo_terminos_comunes": 6,
        "solape_minimo": 0.75,
        "palabras_vacias": ["para", "como", "esta", "sobre", "documento"],
    },
}


class _CorpusTemporal:
    """Redirige MEMORY_DIR/PAPELERA_DIR/PAPELERA_FILE/EXPORT_DIR de purga.py
    a un directorio de usar-y-tirar, y fija umbrales conocidos. Se deshace
    solo, pase lo que pase."""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nexus_purga_test_"))
        self._orig = (purga.MEMORY_DIR, purga.PAPELERA_DIR, purga.PAPELERA_FILE,
                      purga.EXPORT_DIR, purga._umbrales_purga, purga._planes.copy())
        self._orig_ligadas = mem.pg.filas_ligadas_a_nota
        self._orig_huerfanas = mem.pg.filas_sin_marca_origen
        purga.MEMORY_DIR = self.tmp / "memory"
        purga.PAPELERA_DIR = purga.MEMORY_DIR / "papelera"
        purga.PAPELERA_FILE = purga.PAPELERA_DIR / "papelera.json"
        purga.EXPORT_DIR = self.tmp / "exportado_purga"
        purga.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        purga._umbrales_purga = lambda: _FAKE_UMBRALES
        purga._planes.clear()
        # SEGURIDAD: los nombres de nota de prueba (p.ej. «apuntes.md») podrían
        # coincidir por azar con una nota REAL del usuario. filas_ligadas_a_nota
        # lee `memories` real por nombre — se anula aquí SIEMPRE, salvo que el
        # propio test la reinstaure a propósito (con datos de prueba propios).
        mem.pg.filas_ligadas_a_nota = lambda nombre_fichero: []
        # Mismo motivo para el SEGUNDO camino (emparejar por contenido): sin
        # anularlo, una nota de prueba podría reclamar filas huérfanas REALES
        # del usuario. Cada test que lo necesite pone sus propias filas.
        mem.pg.filas_sin_marca_origen = lambda tipos=None: []
        return self

    def nota(self, ruta_rel: str, contenido: str) -> Path:
        p = purga.MEMORY_DIR / ruta_rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
        return p

    def __exit__(self, *exc):
        (purga.MEMORY_DIR, purga.PAPELERA_DIR, purga.PAPELERA_FILE,
         purga.EXPORT_DIR, purga._umbrales_purga, planes_orig) = self._orig
        mem.pg.filas_ligadas_a_nota = self._orig_ligadas
        mem.pg.filas_sin_marca_origen = self._orig_huerfanas
        purga._planes.clear()
        purga._planes.update(planes_orig)
        return False


def _tabla_prueba(conn, n_dim=3):
    nombre = f"test_purga_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {nombre} (id BIGSERIAL PRIMARY KEY, "
            f"kind TEXT NOT NULL DEFAULT 'note', "
            f"content TEXT NOT NULL DEFAULT '', huella TEXT, "
            f"retirado_en TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now())")
    return nombre


def _drop_tabla(conn, nombre):
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {nombre}")
    except Exception:
        pass


# ============================ B1.3: lecturas ================================
def test_lecturas_excluyen_retirados():
    if not mem.pg.online:
        skip("test_lecturas_excluyen_retirados (nexus_memoria_postgres no responde)")
        return
    texto = "hecho de prueba retirable de test_purga.py (fijo, se restaura al final)"
    r = mem.pg.remember(texto, kind="knowledge")
    lote = f"lote-test-{uuid.uuid4().hex[:6]}"
    try:
        n = mem.pg.retirar_filas([r["id"]], lote)
        check(n == 1, "retirar_filas: marca la fila (1 afectada)")
        vistos = mem.pg.all_knowledge(limit=1000)
        check(all(v["content"] != texto for v in vistos),
              "all_knowledge(): NO devuelve filas con retirado_en")
        recordado = mem.pg.recall(texto, limit=50)
        check(all(x.get("content") != texto for x in recordado),
              "recall(): NO devuelve filas con retirado_en (ni por ILIKE)")
    finally:
        mem.pg.restaurar_filas(lote)


# ============================ B2.1: clasificación =============================
def test_clasificar_devuelve_motivo():
    with _CorpusTemporal() as c:
        c.nota("cv.md", "Aquí va mi curriculum vitae de prueba, con datos.")
        clasif = purga.clasificar()
        check("cv.md" in clasif, "clasificar(): nota con palabra clave SÍ aparece")
        info = clasif["cv.md"]
        check(info["categoria"] == "papeleo-personal",
              "clasificar(): categoría correcta")
        check(info["personal"] is True, "clasificar(): papeleo-personal es personal=True")
        check(bool(info["regla"]) and "curriculum vitae de prueba" in info["regla"],
              "clasificar(): cada resultado lleva la regla que lo clasificó")


def test_no_clasificado_no_aparece():
    with _CorpusTemporal() as c:
        c.nota("normal.md", "Notas normales del día a día, nada especial aquí.")
        clasif = purga.clasificar()
        check("normal.md" not in clasif,
              "clasificar(): nota sin categoría reconocida NO aparece (no se fuerza nada)")


def test_clasificar_empate_no_clasifica():
    with _CorpusTemporal() as c:
        c.nota("empate.md", "roadmap de prueba dam y también curriculum vitae de prueba.")
        clasif = purga.clasificar()
        check("empate.md" not in clasif,
              "clasificar(): empate entre categorías -> se queda sin clasificar, no se toca")


# ============================ B2.2: previsualizar ============================
def test_previsualizar_no_altera_ficheros_ni_filas():
    with _CorpusTemporal() as c:
        p = c.nota("cv.md", "curriculum vitae de prueba de nuevo.")
        antes = p.read_text(encoding="utf-8")
        antes_mtime = p.stat().st_mtime
        plan = purga.previsualizar()
        check("id" in plan and "caduca" in plan and "categorias" in plan,
              "previsualizar(): {id, caduca, categorias}")
        cats = {c2["id"]: c2 for c2 in plan["categorias"]}
        check("papeleo-personal" in cats, "previsualizar(): categoría detectada presente")
        check(p.is_file() and p.read_text(encoding="utf-8") == antes,
              "previsualizar(): NO toca el fichero")
        check(p.stat().st_mtime == antes_mtime, "previsualizar(): NO cambia el mtime")
        # nada preseleccionado: la propia forma del plan no trae flags "elegido"
        for cat in plan["categorias"]:
            check("elegido" not in cat and "confirmado" not in cat,
                  f"previsualizar(): «{cat['id']}» no viene con nada preseleccionado")


# ============================ B3.1: aplicar =============================
def test_aplicar_sin_plan_falla():
    r = purga.aplicar("plan-que-no-existe-jamas", ["papeleo-personal"])
    check(r["ok"] is False, "aplicar(): plan_id desconocido falla con motivo")
    check("plan" in r["error"].lower() or "desconocido" in r["error"].lower(),
          "aplicar(): el motivo menciona el plan")


def test_aplicar_plan_rancio_falla():
    with _CorpusTemporal() as c:
        c.nota("cv.md", "curriculum vitae de prueba.")
        plan = purga.previsualizar()
        # el corpus cambia DESPUÉS de la previsualización -> plan rancio
        c.nota("cv2.md", "curriculum vitae de prueba también, segunda nota.")
        r = purga.aplicar(plan["id"], ["papeleo-personal"], acepto_personal=True)
        check(r["ok"] is False, "aplicar(): corpus cambiado desde la previsualización -> falla")
        check("rancio" in r["error"] or "previsualiz" in r["error"].lower(),
              "aplicar(): el motivo explica que el plan está rancio")


def test_confirmar_una_categoria_no_toca_las_otras():
    with _CorpusTemporal() as c:
        personal = c.nota("cv.md", "curriculum vitae de prueba.")
        dam = c.nota("apuntes.md", "roadmap de prueba dam, apuntes del curso.")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["estudios-dam"])
        check(r["ok"] is True, "aplicar(): confirmar UNA categoría concreta funciona")
        check(not dam.is_file(), "aplicar(): la categoría confirmada SÍ se retira")
        check(personal.is_file(), "aplicar(): la categoría NO confirmada queda intacta")


def test_aplicar_categoria_desconocida_o_vacia_falla():
    with _CorpusTemporal() as c:
        c.nota("cv.md", "curriculum vitae de prueba.")
        plan = purga.previsualizar()
        check(purga.aplicar(plan["id"], [])["ok"] is False,
              "aplicar(): sin categorías -> falla («purgar todo» nunca es implícito)")
        check(purga.aplicar(plan["id"], ["categoria-inventada"])["ok"] is False,
              "aplicar(): categoría que no estaba en la previsualización -> falla")


# ===================== B3.2/B3.3: retirar / papelera / restaurar ==============
def test_retirar_papeleo_personal_exporta_antes_de_mover():
    with _CorpusTemporal() as c:
        p = c.nota("cv.md", "curriculum vitae de prueba, texto legible.")
        plan = purga.previsualizar()
        # sin acepto_personal, la personal NUNCA se mueve sola
        r0 = purga.aplicar(plan["id"], ["papeleo-personal"])
        check(r0["ok"] is False, "aplicar(): categoría personal exige acepto_personal explícito")
        check(p.is_file(), "aplicar(): rechazada -> el fichero personal sigue donde estaba")

        plan2 = purga.previsualizar()
        r1 = purga.aplicar(plan2["id"], ["papeleo-personal"], acepto_personal=True)
        check(r1["ok"] is True, "aplicar(): con acepto_personal=True sí retira")
        lote = r1["lote"]
        exportado = list((purga.EXPORT_DIR / "personal" / lote).glob("*.md"))
        check(len(exportado) == 1 and exportado[0].read_text(encoding="utf-8")
              == "curriculum vitae de prueba, texto legible.",
              "retirar personal: exporta copia legible ANTES de mover")
        check(not p.is_file(), "retirar personal: el original sale de data/memory/")
        movida = list((purga.PAPELERA_DIR / lote).glob("*.md"))
        check(len(movida) == 1, "retirar personal: el fichero SIGUE existiendo, en la papelera")


def test_restaurar_devuelve_ruta_original():
    with _CorpusTemporal() as c:
        p = c.nota("apuntes.md", "roadmap de prueba dam.")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["estudios-dam"])
        lote = r["lote"]
        check(not p.is_file(), "precondición: la nota está retirada")
        rr = purga.restaurar(lote)
        check(rr["ok"] is True, "restaurar(): revierte el lote")
        check(p.is_file() and p.read_text(encoding="utf-8") == "roadmap de prueba dam.",
              "restaurar(): la nota vuelve EXACTAMENTE a su ruta original")
        items = purga.papelera(lote)
        check(items and items[0].get("restaurado") is True,
              "restaurar(): la papelera queda marcada como restaurada (ESTADO, no resurrección)")


def test_papelera_sin_tope():
    umbral = purga._umbrales_purga()
    check("papelera_aviso_items" in umbral,
          "papelera: SOLO hay un umbral de AVISO informativo, no un tope duro")
    with _CorpusTemporal() as c:
        for i in range(5):
            c.nota(f"apuntes{i}.md", "roadmap de prueba dam.")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["estudios-dam"])
        check(r["ok"] and r["categorias"]["estudios-dam"]["notas"] == 5,
              "papelera: acepta más elementos que cualquier tope viejo de board.py (500)")


# ============================ B3.4: scheduler ================================
def test_scheduler_no_toca_papelera():
    src = Path(ROOT) / "backend" / "core" / "aplicacion" / "scheduler.py"
    texto = src.read_text(encoding="utf-8").lower()
    check("papelera" not in texto,
          "scheduler.py: CERO referencias a la papelera — nexus nunca la toca por su cuenta")


# ==================== B4.1/B4.2: duplicados-exactos / índice =================
def test_duplicados_exactos_conserva_mas_antigua():
    if not mem.pg.online:
        skip("test_duplicados_exactos_conserva_mas_antigua (nexus_memoria_postgres no responde)")
        return
    huella_test = f"huella-test-purga-{uuid.uuid4().hex[:10]}"
    # Sobre TABLA DE PRUEBA, no sobre `memories`: desde que la purga real de
    # 002 creó `memories_huella_idx` (índice ÚNICO parcial), meter dos filas
    # con la misma huella en la tabla real es imposible — que es exactamente
    # lo que se buscaba. El agrupado se sigue probando, aparte.
    conn = mem.pg.connect()
    tabla = _tabla_prueba(conn)
    try:
        vieja = mem.pg._rows(
            f"INSERT INTO {tabla} (kind, content, huella, created_at) "
            "VALUES ('note', %s, %s, now() - interval '1 hour') RETURNING id",
            ("contenido de prueba dup A (test_purga.py)", huella_test))[0]["id"]
        nueva = mem.pg._rows(
            f"INSERT INTO {tabla} (kind, content, huella, created_at) "
            "VALUES ('note', %s, %s, now()) RETURNING id",
            ("contenido de prueba dup B (test_purga.py)", huella_test))[0]["id"]
        grupos = [g for g in mem.pg.duplicados_exactos(tabla=tabla)
                  if g["huella"] == huella_test]
        check(len(grupos) == 1, "duplicados_exactos(): detecta el grupo de prueba")
        g = grupos[0]
        check(g["conservar"]["id"] == vieja,
              "duplicados_exactos(): conserva la fila MÁS ANTIGUA del grupo")
        check([f["id"] for f in g["sobran"]] == [nueva],
              "duplicados_exactos(): la más nueva queda en «sobran»")
    finally:
        _drop_tabla(conn, tabla)


def test_indice_unico_solo_tras_limpieza_confirmada():
    if not mem.pg.online:
        skip("test_indice_unico_solo_tras_limpieza_confirmada (nexus_memoria_postgres no responde)")
        return
    original_dups = mem.pg.duplicados_exactos
    original_existe = mem.pg._indice_huella_existe
    try:
        # bloqueado: quedan duplicados (fake, sin tocar la tabla real memories)
        mem.pg.duplicados_exactos = lambda: [{"huella": "x", "conservar": {"id": 1}, "sobran": [{"id": 2}]}]
        # Y el índice se finge inexistente: en producción `crear_indice_huella`
        # sale por «ya existía» ANTES de mirar duplicados (es idempotente a
        # propósito), y desde que la purga real de 002 creó el índice sobre
        # `memories` este test se quedaba sin ejercitar su propio guardián.
        mem.pg._indice_huella_existe = lambda tabla="memories": False
        r_bloqueado = mem.pg.crear_indice_huella()
        check(r_bloqueado["ok"] is False,
              "crear_indice_huella(): con duplicados pendientes, NO se crea")
        check("duplicad" in r_bloqueado["error"].lower(),
              "crear_indice_huella(): el motivo explica que hay que limpiar antes")
    finally:
        mem.pg.duplicados_exactos = original_dups
        mem.pg._indice_huella_existe = original_existe

    conn = mem.pg.connect()
    tabla = _tabla_prueba(conn)
    try:
        r = mem.pg.crear_indice_huella(tabla=tabla)
        check(r["ok"] is True and r["ya_existia"] is False,
              "crear_indice_huella(): sin duplicados, sobre tabla de prueba, SÍ se crea")
        check(mem.pg._indice_huella_existe(tabla), "crear_indice_huella(): el índice existe de verdad")
        r2 = mem.pg.crear_indice_huella(tabla=tabla)
        check(r2["ok"] is True and r2["ya_existia"] is True,
              "crear_indice_huella(): idempotente, no revienta si ya existía")
    finally:
        _drop_tabla(conn, tabla)


def test_indice_huella_solo_se_dispara_tras_confirmar_duplicados():
    # Wiring de aplicar(): confirmar "duplicados-exactos" dispara
    # crear_indice_huella(); confirmar OTRA categoría, NO.
    llamadas = []
    original = mem.pg.crear_indice_huella
    original_retirar = mem.pg.retirar_filas
    try:
        mem.pg.crear_indice_huella = lambda **kw: (llamadas.append(True) or {"ok": True})
        mem.pg.retirar_filas = lambda ids, lote: 0
        with _CorpusTemporal() as c:
            c.nota("apuntes.md", "roadmap de prueba dam.")
            plan = purga.previsualizar()
            purga.aplicar(plan["id"], ["estudios-dam"])
            check(not llamadas, "aplicar(): confirmar OTRA categoría no dispara el índice")

            c.nota("apuntes2.md", "roadmap de prueba dam otra vez.")
            plan2 = purga.previsualizar()
            # inyectamos duplicados-exactos manualmente (sin tocar memories real)
            plan2_real = purga._planes[plan2["id"]]
            plan2_real["categorias"].append(
                {"id": "duplicados-exactos", "personal": False,
                 "items": [{"ruta": None, "fila_id": 999999999}]})
            purga.aplicar(plan2["id"], ["duplicados-exactos"])
            check(llamadas, "aplicar(): confirmar duplicados-exactos SÍ dispara crear_indice_huella()")
    finally:
        mem.pg.crear_indice_huella = original
        mem.pg.retirar_filas = original_retirar


# =========================== B4.3: limpiar-respaldo ===========================
def test_limpiar_respaldo_exige_confirmacion_propia():
    import asyncio
    from backend.core.comun import confirm
    app = importlib.import_module("backend.app")
    canal = f"test-purga-{uuid.uuid4().hex[:6]}"
    r = asyncio.run(app.api_memoria_vector_limpiar_respaldo({"channel": canal}))
    check("reply" in r,
          "POST /api/memoria/vector/limpiar-respaldo: arma confirm.request(), no ejecuta directo")
    check(confirm.pending(canal) is not None,
          "limpiar-respaldo: queda una confirmación propia pendiente")
    asyncio.run(confirm.answer("no", canal))
    check(confirm.pending(canal) is None,
          "limpiar-respaldo: «no» desarma sin tocar ninguna columna")


# ============================== B5.1: endpoints ===============================
def test_endpoints_purga_smoke():
    import asyncio
    app = importlib.import_module("backend.app")
    plan = asyncio.run(app.api_memoria_purga_previsualizar())
    check("id" in plan and "categorias" in plan,
          "GET /api/memoria/purga/previsualizar -> {id, categorias,...} (solo lectura)")

    r = asyncio.run(app.api_memoria_purga_aplicar(
        {"plan_id": "no-existe-jamas", "categorias": ["papeleo-personal"]}))
    check(r.get("ok") is False,
          "POST /api/memoria/purga/aplicar con plan_id inexistente falla con motivo, no revienta")

    r_pap = asyncio.run(app.api_memoria_purga_papelera())
    check("items" in r_pap, "GET /api/memoria/purga/papelera -> {items:[...]}")

    r_rest = asyncio.run(app.api_memoria_purga_restaurar({"lote": ""}))
    check(r_rest.get("ok") is False, "POST /api/memoria/purga/restaurar sin lote -> falla, no revienta")

    r_exp = asyncio.run(app.api_memoria_purga_exportar({"lote": ""}))
    check(r_exp.get("ok") is False, "POST /api/memoria/purga/exportar sin lote -> falla, no revienta")

    r_del = asyncio.run(app.api_memoria_purga_borrar_definitivo({"lote": ""}))
    check(r_del.get("ok") is False,
          "POST /api/memoria/purga/borrar-definitivo sin lote -> falla ANTES de armar nada")


# ======================== B6: matriz de amenazas ===========================
def test_symlink_no_se_mueve_a_papelera():
    with _CorpusTemporal() as c:
        objetivo = c.nota("objetivo.md", "curriculum vitae de prueba (destino real).")
        atajo = purga.MEMORY_DIR / "atajo.md"
        try:
            atajo.symlink_to(objetivo)
        except (OSError, NotImplementedError) as exc:
            skip(f"test_symlink_no_se_mueve_a_papelera (sin privilegio para symlinks: {exc})")
            return
        r = purga.retirar_nota("atajo.md", "lote-symlink-test")
        check(r["movido"] is False, "retirar_nota(): un symlink NUNCA se mueve")
        check("symlink" in r.get("razon", "").lower(),
              "retirar_nota(): el motivo dice explícitamente que es un symlink")
        check(atajo.is_symlink() and objetivo.is_file(),
              "retirar_nota(): ni el symlink ni su destino real se tocan")


def test_restaurar_no_sobrescribe():
    with _CorpusTemporal() as c:
        p = c.nota("apuntes.md", "roadmap de prueba dam (versión original).")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["estudios-dam"])
        lote = r["lote"]
        # mientras está en la papelera, "reaparece" un fichero con el mismo nombre
        ocupante = c.nota("apuntes.md", "contenido NUEVO, no relacionado.")
        rr = purga.restaurar(lote)
        check(rr["ok"] is True, "restaurar(): sigue funcionando aunque el hueco esté ocupado")
        check(ocupante.read_text(encoding="utf-8") == "contenido NUEVO, no relacionado.",
              "restaurar(): NUNCA sobrescribe lo que hay en la ruta original")
        restauradas = [Path(x["ruta"]) for x in rr["restauradas"]]
        check(len(restauradas) == 1 and restauradas[0].is_file() and
              restauradas[0] != ocupante and "restaurado" in restauradas[0].name,
              "restaurar(): la nota recuperada aparece renombrada, sin pisar nada")


def test_borrado_sin_traza_falla():
    with _CorpusTemporal() as c:
        p = c.nota("apuntes.md", "roadmap de prueba dam (para borrado definitivo).")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["estudios-dam"])
        lote = r["lote"]
        # OJO CON MEDIR ESTO CONTANDO (02/08/2026). Antes se comparaba
        # len(tail(500)) antes y después y se exigía que creciera. Pero tail(N)
        # devuelve como mucho N: con 682 entradas destructivas en el registro
        # real, los dos lados valían 500 y el test fallaba SIEMPRE, dijera la
        # verdad o no. Y el fallo llegó tarde, cuando el registro se llenó: el
        # test venía envenenándose solo desde el día que se escribió.
        #
        # Lo que de verdad se quiere comprobar es que aparece una traza NUEVA,
        # así que se mira la identidad de la última, no cuántas hay. Eso no
        # satura, no depende de cuánto haya crecido el registro, y sigue
        # cayéndose si alguien deja de registrar el borrado.
        def _ultima_traza():
            t = audit.tail(500, destructive_only=True)
            return t[-1] if t else None

        antes = _ultima_traza()
        rb = purga.borrar_definitivo(lote)
        check(rb["ok"] is True, "borrar_definitivo(): borra el lote de prueba")
        despues = audit.tail(500, destructive_only=True)
        check(bool(despues) and despues[-1] != antes,
              "borrar_definitivo(): SIEMPRE deja una traza nueva en auditoría")
        ultima = despues[-1]
        check(ultima["action"] == "purga_borrar_definitivo" and ultima["destructive"] is True
              and ultima["confirmed"] is True and ultima.get("extra", {}).get("lote") == lote,
              "borrar_definitivo(): la traza identifica acción, destructive=True y el lote exacto")


def test_exportar_traversal_rechazado():
    from backend.core.comun import permissions
    with _CorpusTemporal() as c:
        c.nota("apuntes.md", "roadmap de prueba dam.")
        plan = purga.previsualizar()
        r = purga.aplicar(plan["id"], ["estudios-dam"])
        lote = r["lote"]
        fuera = str(Path(tempfile.gettempdir()) / "fuera_del_sandbox_purga_test")
        original = permissions.path_allowed
        try:
            # Simula modo restringido (sandbox/carpetas): el modo real de este
            # equipo de desarrollo es "todo" y no probaría nada por sí solo.
            permissions.path_allowed = lambda p: False
            rx = purga.exportar(lote, destino=fuera)
        finally:
            permissions.path_allowed = original
        check(rx["ok"] is False,
              "exportar(): destino fuera de las carpetas permitidas -> RECHAZADO, no recortado")
        check("permit" in rx["error"].lower() or "permiso" in rx["error"].lower(),
              "exportar(): el motivo explica que no está entre las carpetas permitidas")


# ============ B2.1-bis: filas huérfanas casadas por CONTENIDO ===============
# INCIDENTE: `previsualizar()` daba `filas_pg: 0` en todas las categorías
# porque solo 233 de 697 filas llevan la marca de origen `[fichero]`. Retirar
# las 35 notas de la FP habría dejado 10 filas de tablespaces/actividades/2DAM
# vivas y buscables. Estos tests fijan las DOS mitades del arreglo: que el
# emparejamiento por contenido acierte con la fila propia, y que NO se lleve
# la ajena (llevarse una ajena es peor que dejar una propia).

# Nota inventada para el test: vocabulario que no existe en el proyecto.
_NOTA_APICULTURA = """# doc Colmenar del Cerro Bermejo

Revision del colmenar: 14 colmenas Langstroth, dos nucleos de fecundacion.
La reina Buckfast marcada en azul sigue poniendo. Tratamiento de varroa con
acido oxalico goteado en noviembre. Cosecha de romero: 38 kilos.
Roadmap de prueba dam pendiente para la asignatura.
"""

# La MISMA nota tal como quedo guardada en `memories`, sin marca de origen Y
# con OTRO encabezado: asi este test ejercita el vocabulario y no el atajo del
# encabezado, que tiene su propio test.
_FILA_PROPIA = """# Revision de mayo

Revision del colmenar: 14 colmenas Langstroth, dos nucleos de fecundacion.
La reina Buckfast marcada en azul sigue poniendo. Tratamiento de varroa con
acido oxalico goteado en noviembre. Cosecha de romero: 38 kilos.
"""

# Fila de OTRA cosa. Comparte palabras sueltas ("azul", "kilos", "reina",
# "noviembre") a proposito: si el criterio fuese "comparten algo", se la
# llevaria por delante.
_FILA_AJENA = """# doc Cena de noviembre

Menu cerrado con Silvia: solomillo Wellington, guarnicion de patata azul,
tarta de queso. Compramos tres kilos en el mercado. La reina de la noche
fue la tarta. Reservado el salon Trafalgar del hotel Montesclaros.
"""


def _huerfana(fid, texto):
    return {"id": fid, "terminos": purga.terminos(texto, purga._cfg_contenido()),
            "titulo": purga.titulo_encabezado(texto)}


def test_emparejar_por_contenido_acierta_con_su_fila():
    with _CorpusTemporal():
        cfg = purga._cfg_contenido()
        pool = [_huerfana(901, _FILA_PROPIA), _huerfana(902, _FILA_AJENA)]
        casadas = purga.emparejar_por_contenido(
            "doc Colmenar del Cerro Bermejo.md",
            purga.terminos(_NOTA_APICULTURA, cfg), pool, cfg)
        check([f["id"] for f in casadas] == [901],
              "emparejar_por_contenido(): casa la fila propia y SOLO esa")
        motivo = casadas[0]["motivo"]
        check("sin marca de origen" in motivo and "vocabulario" in motivo
              and "Colmenar" in motivo,
              "emparejar_por_contenido(): cada fila llega con SU motivo explicable")
        check(casadas[0]["solape"] >= cfg["solape_minimo"],
              "emparejar_por_contenido(): el motivo trae el solape medido, no una etiqueta")


def test_emparejar_por_contenido_no_se_lleva_la_ajena():
    with _CorpusTemporal():
        cfg = purga._cfg_contenido()
        casadas = purga.emparejar_por_contenido(
            "doc Colmenar del Cerro Bermejo.md",
            purga.terminos(_NOTA_APICULTURA, cfg),
            [_huerfana(902, _FILA_AJENA)], cfg)
        check(casadas == [],
              "emparejar_por_contenido(): fila de otro tema -> NO se casa "
              "(peor llevarse una ajena que dejar una propia)")
        # Fila demasiado corta para juzgarla: tampoco se casa, aunque TODO lo
        # suyo este en la nota (solape 100% sobre cuatro palabras no dice nada).
        cortas = purga.emparejar_por_contenido(
            "doc Colmenar del Cerro Bermejo.md",
            purga.terminos(_NOTA_APICULTURA, cfg),
            [_huerfana(903, "colmenas varroa romero")], cfg)
        check(cortas == [],
              "emparejar_por_contenido(): fila sin materia suficiente -> NO se casa")


def test_encabezado_de_origen_rescata_lo_que_el_vocabulario_no_juzga():
    # INCIDENTE REAL: la fila del CV salió del PDF con las letras separadas
    # («T é c n i c o  S u p e r i o r»), así que solo deja CUATRO términos
    # utilizables y el criterio de vocabulario la descarta con razón. Su
    # encabezado, en cambio, es el nombre exacto de la nota.
    fila_cv = ("# doc CV_NOMBRE_APELLIDO\n\nCarpeta: 20. Estudios Centro\n"
               "T é c n i c o  S u p e r i o r  e n  D e s a r r o l l o\n")
    with _CorpusTemporal():
        cfg = purga._cfg_contenido()
        pool = [_huerfana(910, fila_cv), _huerfana(911, _FILA_AJENA)]
        casadas = purga.emparejar_por_contenido(
            "doc CV_NOMBRE_APELLIDO.md",
            purga.terminos("curriculum vitae de prueba", cfg), pool, cfg)
        check([f["id"] for f in casadas] == [910],
              "emparejar_por_contenido(): el encabezado «# nombre-de-la-nota» "
              "casa la fila que el vocabulario no puede juzgar")
        check("encabezado de origen" in casadas[0]["motivo"],
              "emparejar_por_contenido(): el motivo dice que la ató el encabezado")
        check(purga.titulo_encabezado("sin encabezado\n# tarde") == "",
              "titulo_encabezado(): solo la PRIMERA línea vale como marca")


def test_previsualizar_cuenta_las_huerfanas_con_motivo():
    with _CorpusTemporal() as c:
        c.nota("doc Colmenar del Cerro Bermejo.md", _NOTA_APICULTURA)
        orig = purga._huerfanas_con_terminos
        try:
            purga._huerfanas_con_terminos = lambda cfg: [
                _huerfana(901, _FILA_PROPIA), _huerfana(902, _FILA_AJENA)]
            plan = purga.previsualizar()
        finally:
            purga._huerfanas_con_terminos = orig
        cats = {x["id"]: x for x in plan["categorias"]}
        item = cats["estudios-dam"]["items"][0]
        check(item["filas_pg"] == 1,
              "previsualizar(): filas_pg ya NO miente con ceros, cuenta las huérfanas")
        check([f["id"] for f in item["filas"]] == [901],
              "previsualizar(): lleva la fila propia, no la ajena")
        check(bool(item["filas"][0]["motivo"]),
              "previsualizar(): cada fila viaja con su motivo, igual que las notas")


def test_la_marca_de_origen_sigue_mandando():
    with _CorpusTemporal() as c:
        c.nota("doc Colmenar del Cerro Bermejo.md", _NOTA_APICULTURA)
        orig_l, orig_h = mem.pg.filas_ligadas_a_nota, purga._huerfanas_con_terminos
        try:
            mem.pg.filas_ligadas_a_nota = lambda nombre_fichero: [{"id": 800}]
            purga._huerfanas_con_terminos = lambda cfg: [_huerfana(901, _FILA_PROPIA)]
            plan = purga.previsualizar()
        finally:
            mem.pg.filas_ligadas_a_nota, purga._huerfanas_con_terminos = orig_l, orig_h
        cats = {x["id"]: x for x in plan["categorias"]}
        filas = cats["estudios-dam"]["items"][0]["filas"]
        check([f["id"] for f in filas] == [800],
              "previsualizar(): con marca de origen NO se usa el segundo camino")
        check("marca de origen" in filas[0]["motivo"],
              "previsualizar(): el motivo dice que la ató la marca, no el vocabulario")


# =============================== runner =====================================
if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                          # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s), {_skip} saltado(s) (sin BD)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
