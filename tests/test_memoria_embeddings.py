# -*- coding: utf-8 -*-
"""002-memoria-y-conocimiento — Bloque A (embeddings + huella, aditivo).

Cubre memoria-embeddings y memoria-deduplicacion tal como quedan cerradas en
el bloque A: dimensión medida (nunca a fuego), migración sin pérdida de
filas, índice ivfflat gated por umbral, descarte SIEMPRE contado y avisado,
reindexado presupuestado/por lotes/reanudable, aislamiento de privacidad
proveedor-de-memoria vs. cerebro-de-chat, huella NFKC e inserción idempotente
sin borrar nada.

Los tests que MUTAN esquema (migración, índice, reindexado) lo hacen sobre
una tabla DE PRUEBA creada y destruida dentro del propio test — nunca sobre
`memories` real, que tiene datos de verdad del usuario. Si el contenedor
`nexus_memoria_postgres` no está arriba, esos tests se SALTAN con aviso
explícito (no cuentan como probados: hay que repetirlos con el contenedor
encendido antes de dar el bloque por bueno).

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_memoria_embeddings.py
"""
import importlib
import json
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


mem = importlib.import_module("backend.core.dominio.memory")
rag = importlib.import_module("backend.core.dominio.rag")


def _tabla_prueba(conn, cols_extra_sql="", n_dim=3):
    """Crea una tabla desechable con la misma forma mínima que `memories`
    (id, embedding vector(n_dim)) y devuelve su nombre. El propio test la
    destruye en un `finally`."""
    nombre = f"test_mem_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {nombre} (id BIGSERIAL PRIMARY KEY, "
            f"kind TEXT NOT NULL DEFAULT 'note', content TEXT NOT NULL, "
            f"embedding vector({n_dim}))")
    return nombre


def _drop_tabla(conn, nombre):
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {nombre}")
    except Exception:
        pass


# ================== A1/A2: dimensión real y migración ==================
def test_detectar_dimension_distinta():
    # No depende de Postgres real: se monkeypatchea todo lo que mide.
    original_col = mem.pg._dimension_columna
    original_embed = rag._embed_sync
    tmp = Path(tempfile.mkdtemp()) / "estado_embeddings.json"
    original_file = mem.ESTADO_EMBEDDINGS_FILE
    try:
        mem.ESTADO_EMBEDDINGS_FILE = tmp
        mem.pg._dimension_columna = lambda tabla="memories": 768
        rag._embed_sync = lambda text, proveedor=None: [0.1] * 1024
        r = mem.pg.detectar_dimension()
        check(r["columna"] == 768, "detectar_dimension: columna real=768")
        check(r["medida"] == 1024, "detectar_dimension: medida=1024 (el modelo activo)")
        check(r["reindexado_pendiente"] is True,
              "detectar_dimension: 768≠1024 -> reindexado_pendiente=True")
        check(tmp.is_file(), "detectar_dimension: escribe estado_embeddings.json")
        estado = json.loads(tmp.read_text(encoding="utf-8"))
        check(estado["dimension"] == 1024, "estado_embeddings.json guarda la dimensión MEDIDA")
    finally:
        mem.pg._dimension_columna = original_col
        rag._embed_sync = original_embed
        mem.ESTADO_EMBEDDINGS_FILE = original_file


def test_migrar_vector_no_pierde_filas():
    if not mem.pg.online:
        skip("test_migrar_vector_no_pierde_filas (nexus_memoria_postgres no responde)")
        return
    conn = mem.pg.connect()
    tabla = _tabla_prueba(conn, n_dim=3)
    try:
        with conn.cursor() as cur:
            for i in range(5):
                cur.execute(
                    f"INSERT INTO {tabla} (kind, content, embedding) "
                    f"VALUES ('knowledge', %s, %s::vector)",
                    (f"fila {i}", str([0.1, 0.2, 0.3])))
        antes = mem.pg._rows(f"SELECT count(*) AS n FROM {tabla}")[0]["n"]
        r = mem.pg.migrar_vector(5, tabla=tabla)
        check(r["ok"], f"migrar_vector: ok ({r.get('error')})")
        despues = mem.pg._rows(f"SELECT count(*) AS n FROM {tabla}")[0]["n"]
        check(antes == despues == 5, "migrar_vector: ni una fila perdida")
        check(mem.pg._dimension_columna(tabla) == 5, "migrar_vector: columna nueva en vector(5)")
        vieja = r["columna_vieja"]
        cols = mem.pg._rows(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s", (tabla,))
        nombres = {c["column_name"] for c in cols}
        check(vieja in nombres, "migrar_vector: la columna vieja SIGUE existiendo (respaldo)")
    finally:
        _drop_tabla(conn, tabla)


def test_indice_no_se_crea_bajo_umbral():
    if not mem.pg.online:
        skip("test_indice_no_se_crea_bajo_umbral (nexus_memoria_postgres no responde)")
        return
    conn = mem.pg.connect()
    tabla = _tabla_prueba(conn, n_dim=3)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {tabla} (kind, content, embedding) "
                f"VALUES ('knowledge', 'x', %s::vector)", (str([0.1, 0.2, 0.3]),))
        mem.pg._maybe_crear_indice_vector(tabla)
        existe = mem.pg._rows(
            "SELECT 1 AS x FROM pg_indexes WHERE tablename = %s "
            "AND indexname = %s", (tabla, f"{tabla}_embedding_idx"))
        check(not existe, "1 fila << filas_minimas_indice (1000): NO se crea el índice ivfflat")
    finally:
        _drop_tabla(conn, tabla)


def test_descarte_avisa_y_cuenta_no_silencioso():
    original_col = mem.pg._dimension_columna
    original_embed = rag._embed_sync
    original_contador = mem.pg.descartes_por_dimension
    original_avisado = mem.pg._avisado_descarte
    avisos = []
    try:
        from backend.core.comun.events import bus
        original_emit = bus.emit_sync
        bus.emit_sync = lambda tipo, data=None: avisos.append((tipo, data))
        mem.pg._dimension_columna = lambda tabla="memories": 768
        rag._embed_sync = lambda text, proveedor=None: [0.1] * 5   # no encaja con 768
        mem.pg.descartes_por_dimension = 0
        mem.pg._avisado_descarte = False
        v1 = mem.pg._embed("hecho uno")
        v2 = mem.pg._embed("hecho dos")
        check(v1 is None and v2 is None, "_embed: descarta silenciosamente NADA (guarda sin vector)")
        check(mem.pg.descartes_por_dimension == 2, "_embed: contador de descartes suma, no se pierde")
        check(len(avisos) == 1, "_embed: UN aviso por sesión, no uno por fila")
    finally:
        mem.pg._dimension_columna = original_col
        rag._embed_sync = original_embed
        mem.pg.descartes_por_dimension = original_contador
        mem.pg._avisado_descarte = original_avisado
        bus.emit_sync = original_emit


# ================== A3: reindexado explícito, por lotes ==================
def test_sale_del_equipo_por_proveedor_y_por_url():
    check(mem._sale_del_equipo("openai", "https://api.openai.com/v1") is True,
          "openai: sale del equipo")
    check(mem._sale_del_equipo("gemini", "https://generativelanguage.googleapis.com") is True,
          "gemini: sale del equipo")
    check(mem._sale_del_equipo("ollama", "http://127.0.0.1:11434") is False,
          "ollama loopback: NO sale del equipo")
    check(mem._sale_del_equipo("ollama", "http://192.168.1.50:11434") is True,
          "ollama en URL remota (no loopback): SÍ sale del equipo")
    check(mem._es_loopback("http://localhost:11434") is True, "_es_loopback: localhost")
    check(mem._es_loopback("http://192.168.1.50:11434") is False, "_es_loopback: LAN no es loopback")


def test_cambiar_cerebro_no_cambia_embed_provider():
    from backend.core.comun.config import settings
    original = settings.get("llm_provider", "gemini")
    umbral_antes = mem._cargar_umbrales_embedding().get("proveedor_preferido")
    try:
        settings.set("llm_provider", "gemini-2.5-flash")
        umbral_despues_gemini = mem._cargar_umbrales_embedding().get("proveedor_preferido")
        settings.set("llm_provider", "otro-cerebro-cualquiera")
        umbral_despues_otro = mem._cargar_umbrales_embedding().get("proveedor_preferido")
        check(umbral_antes == umbral_despues_gemini == umbral_despues_otro,
              "cambiar llm_provider (cerebro de chat) NO cambia memoria.embedding.proveedor_preferido")
    finally:
        settings.set("llm_provider", original)


def test_reindexado_reanuda_sin_repetir():
    # reindexar() procesa TODO lo pendiente en lotes internos de
    # `lote_reindex` (comete progreso fila a fila, no espera al final) —
    # eso es lo que hace REANUDABLE una interrupción real (proceso que
    # muere a mitad): lo ya escrito con UPDATE queda, y la siguiente
    # llamada solo ve `WHERE embedding IS NULL`. Se simula la interrupción
    # con DOS tandas de filas: la segunda tanda NO debe re-tocar las filas
    # que la primera ya dejó con vector.
    if not mem.pg.online:
        skip("test_reindexado_reanuda_sin_repetir (nexus_memoria_postgres no responde)")
        return
    conn = mem.pg.connect()
    tabla = _tabla_prueba(conn, n_dim=3)
    original_embed = rag._embed_sync
    llamadas = []
    try:
        with conn.cursor() as cur:
            for i in range(3):
                cur.execute(
                    f"INSERT INTO {tabla} (kind, content) VALUES ('knowledge', %s)", (f"tanda1-{i}",))

        def _fake_embed(text, proveedor=None):
            llamadas.append(text)
            return [0.1, 0.2, 0.3]

        rag._embed_sync = _fake_embed
        plan_id = "plan-test"

        def _plan():
            mem.pg._planes_reindexado[plan_id] = {
                "id": plan_id, "proveedor": "ollama", "sale_del_equipo": False,
                "_caduca_dt": __import__("datetime").datetime.now()
                             + __import__("datetime").timedelta(minutes=5)}

        _plan()
        r1 = mem.pg.reindexar(plan_id, tabla=tabla)
        check(r1["ok"] and r1["procesadas"] == 3, "reindexar: procesa toda la primera tanda (3)")
        with conn.cursor() as cur:
            for i in range(3):
                cur.execute(
                    f"INSERT INTO {tabla} (kind, content) VALUES ('knowledge', %s)", (f"tanda2-{i}",))
        _plan()
        r2 = mem.pg.reindexar(plan_id, tabla=tabla)
        check(r2["ok"] and r2["procesadas"] == 3, "reindexar: segunda llamada solo procesa las NUEVAS (3)")
        check(len(llamadas) == 6, "reindexar: 6 llamadas totales, ninguna fila de la tanda1 repetida")
        check(all("tanda1" in t for t in llamadas[:3]) and all("tanda2" in t for t in llamadas[3:]),
              "reindexar: la segunda llamada no volvió a tocar la tanda1")
        pendientes_final = mem.pg._rows(f"SELECT count(*) AS n FROM {tabla} WHERE embedding IS NULL")[0]["n"]
        check(pendientes_final == 0, "reindexar: al final, 0 filas sin vector")
    finally:
        rag._embed_sync = original_embed
        _drop_tabla(conn, tabla)


def test_reindexado_nube_exige_confirmacion():
    umbral_original = mem._cargar_umbrales_embedding
    try:
        mem._cargar_umbrales_embedding = lambda: {**umbral_original(), "permitir_nube": False}
        plan_id = "plan-nube-test"
        mem.pg._planes_reindexado[plan_id] = {
            "id": plan_id, "proveedor": "openai", "sale_del_equipo": True, "llamadas": 3,
            "_caduca_dt": __import__("datetime").datetime.now() + __import__("datetime").timedelta(minutes=5)}
        r = mem.pg.reindexar(plan_id)
        check(r["ok"] is False, "reindexar a nube con permitir_nube:false FALLA")
        check("permitir_nube" in r.get("error", ""), "el motivo del fallo es legible/explícito")

        mem._cargar_umbrales_embedding = lambda: {**umbral_original(), "permitir_nube": True}
        mem.pg._planes_reindexado[plan_id] = {
            "id": plan_id, "proveedor": "openai", "sale_del_equipo": True, "llamadas": 3,
            "_caduca_dt": __import__("datetime").datetime.now() + __import__("datetime").timedelta(minutes=5)}
        r2 = mem.pg.reindexar(plan_id, confirmar_nube=False)
        check(r2["ok"] is False, "con permitir_nube:true pero SIN confirmar_nube, sigue fallando")
    finally:
        mem._cargar_umbrales_embedding = umbral_original


def test_endpoints_reindexado():
    import asyncio
    import backend.app as app
    plan = asyncio.run(app.api_memoria_reindexar_plan({}))
    check("filas" in plan and "proveedor" in plan and "aviso" in plan,
          "POST /api/memoria/reindexar/plan -> {filas, proveedor, aviso, ...}")
    check(plan["proveedor"] == "ollama", "el plan usa memoria.embedding.proveedor_preferido")
    r = asyncio.run(app.api_memoria_reindexar({"plan_id": "no-existe-jamas"}))
    check(r.get("ok") is False, "reindexar con plan_id inexistente falla con motivo, no revienta")


# ================== A2.5: endpoint de migración protegido ==================
def test_endpoint_migrar_exige_confirmacion():
    import asyncio
    from backend.core.comun import confirm
    canal = f"test-{uuid.uuid4().hex[:6]}"
    r = asyncio.run(app_migrar({"dim": 5, "channel": canal}))
    check("reply" in r, "POST /api/memoria/vector/migrar arma confirm.request() (no ejecuta directo)")
    check(confirm.pending(canal) is not None, "hay una confirmación viva en el canal")
    # se cancela (nunca se confirma en un test): no debe migrar nada de verdad
    respuesta = asyncio.run(confirm.answer("no", canal))
    check(respuesta is not None, "responder «no» cancela limpio")
    check(confirm.pending(canal) is None, "tras «no», no queda nada armado")


def app_migrar(payload):
    import backend.app as app
    return app.api_memoria_vector_migrar(payload)


# ================== A4: huella y deduplicación (sin borrar nada) ==================
def test_huella_estable_nfkc():
    h1 = rag.huella("Hola   Mundo")
    h2 = rag.huella("hola mundo")
    check(h1 == h2, "huella: mayúsculas/espacios no cambian la huella")
    h3 = rag.huella("año")
    h4 = rag.huella("ano")
    check(h3 != h4, "huella: las tildes SÍ se respetan (año ≠ ano)")
    h5 = rag.huella("café")
    h6 = rag.huella("café")   # café con acento combinante (NFD)
    check(h5 == h6, "huella: NFKC normaliza formas combinantes equivalentes")


def test_reinsertar_mismo_hecho_no_duplica():
    # Contenido FIJO (sin uuid): así, ejecutar esta suite mil veces sigue
    # dejando UNA sola fila en `memories` real — nunca litter creciente. No
    # se borra nada (Bloque A es aditivo): la reinserción es la propia
    # prueba de que la huella funciona.
    if not mem.pg.online:
        skip("test_reinsertar_mismo_hecho_no_duplica (nexus_memoria_postgres no responde)")
        return
    original_embed_method = mem.PgMemory._embed
    try:
        mem.PgMemory._embed = lambda self, text: None  # sin depender de un proveedor real
        texto = "hecho de prueba idempotente de test_memoria_embeddings.py (fijo, no crece)"
        # r1 solo es "no duplicado" la PRIMERISIMA vez que corre esta suite en
        # este Postgres; a partir de ahí, la huella ya existe y r1 TAMBIÉN
        # sale "duplicado" — eso es exactamente la garantía que se prueba.
        r1 = mem.pg.remember(texto, kind="knowledge")
        check(isinstance(r1["id"], int) and isinstance(r1["duplicado"], bool),
              "remember(): siempre devuelve {id, duplicado}")
        r2 = mem.pg.remember(texto, kind="knowledge")
        check(r2["duplicado"] is True, "reinsertar el MISMO hecho: 'ya lo sabía', no crea fila")
        check(r2["id"] == r1["id"], "reinsertar el MISMO hecho: mismo id, no uno nuevo")
        filas = mem.pg._rows(
            "SELECT count(*) AS n FROM memories WHERE huella = %s",
            (rag.huella(f"knowledge\n{texto}"),))
        check(filas[0]["n"] == 1, "en la tabla real solo hay UNA fila con esa huella")
    finally:
        mem.PgMemory._embed = original_embed_method


def test_duplicados_exactos_no_borra_nada():
    if not mem.pg.online:
        skip("test_duplicados_exactos_no_borra_nada (nexus_memoria_postgres no responde)")
        return
    antes = mem.pg._rows("SELECT count(*) AS n FROM memories")[0]["n"]
    dups = mem.pg.duplicados_exactos()
    despues = mem.pg._rows("SELECT count(*) AS n FROM memories")[0]["n"]
    check(antes == despues, "duplicados_exactos(): SOLO LECTURA, ni una fila cambia")
    check(isinstance(dups, list), "duplicados_exactos(): devuelve una lista de grupos")
    for g in dups[:3]:
        check(g["total"] >= 2, "cada grupo listado tiene 2+ filas")
        check("conservar" in g and "sobran" in g, "cada grupo dice qué se conservaría y qué sobra")


def test_estado_dice_indice_no_activo():
    estado = mem.estado_memoria()
    if not estado.get("db_online"):
        skip("test_estado_dice_indice_no_activo (nexus_memoria_postgres no responde)")
        return
    if not estado["indice_huella_activo"]:
        check("no está activa" in estado["mensaje_huella"] or "NO está activa" in estado["mensaje_huella"],
              "estado_memoria(): sin índice único, lo dice con todas las letras (no es un bug)")
    check("descartes_por_dimension" in estado, "estado_memoria(): expone el contador de descartes")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"-- {t.__name__}")
        try:
            t()
        except Exception as exc:                              # noqa: BLE001
            _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
            print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s), {_skip} saltado(s) (sin BD)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
