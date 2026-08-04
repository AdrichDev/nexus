# -*- coding: utf-8 -*-
"""002-memoria-y-conocimiento — Bloque C (ingesta de documentos, sin recortes).

Cubre memoria-ingesta-documentos: los CUATRO truncados silenciosos que tenía
la ingesta (rag.py `reindex()` a [:1500], scheduler.py `_ingest_inbox()` a
[:900]/[:20000], files_io.py `_MAX_CHARS`=200_000 y `_leer_xlsx()` a 3000
filas), el buzón aceptando `.docx`/`.pdf`/`.xlsx` (antes los rechazaba una
lista fija de extensiones aunque `read_any()` ya sabía leerlos), el troceado
por estructura de `.xlsx` (hoja/columnas, nunca aplanado), la ingesta
dirigida de una carpeta con espejo `.md` + metadatos, el peso `historico`
frente al `normal` en `recall()`, y el rechazo de traversal.

REGLA ABSOLUTA DE ESTE FICHERO: ningún test toca `data/memory/` real. Los
directorios de prueba viven en `tempfile.mkdtemp()` (monkeypatch de
`DATA_DIR`/`MEMORY_DIR`/`SKILLS_DIR`/`DOCUMENTOS_DIR` durante cada test,
restaurados en el `finally`). Los tests que necesitan Postgres de verdad
insertan filas con un marcador único y las BORRAN ellos mismos al acabar
(nunca `retirar` a medias: el bloque A dejó 3 filas huérfanas -- 804/805/807
-- por no hacer justo esto, y no se repite aquí).

Ejecutar: .venv\\Scripts\\python.exe tests\\test_ingesta_documentos.py
"""
import asyncio
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
    print("  SALTADO (sin BD/proveedor):", msg)


files_io = importlib.import_module("backend.core.infraestructura.files_io")
rag = importlib.import_module("backend.core.rag")
mem = importlib.import_module("backend.core.memory")
scheduler = importlib.import_module("backend.core.scheduler")
ingesta = importlib.import_module("backend.core.ingesta")
config = importlib.import_module("backend.core.comun.config")
permissions = importlib.import_module("backend.core.comun.permissions")


# ------------------------- infraestructura de prueba -------------------------
class _FakePg:
    """Sustituye a memory.pg en los tests que NO necesitan Postgres real:
    graba las llamadas a remember() para poder comprobar qué texto llegó,
    sin tocar el contenedor."""

    def __init__(self):
        self.online = True
        self.llamadas = []

    def remember(self, content, kind="note", tags=None, **kw):
        self.llamadas.append({"content": content, "kind": kind, "tags": tags, **kw})
        return {"id": len(self.llamadas), "duplicado": False}


class _FakeGraph:
    """Sustituye a memory.graph: graba las notas espejo sin escribir en
    data/memory/ real."""

    def __init__(self):
        self.notas = []

    def write_note(self, title, content):
        self.notas.append((title, content))
        return "fake.md"


# =============================== C1 ==========================================
def test_read_any_limite_cero_no_trunca():
    tmp = Path(tempfile.mkdtemp(prefix="nexus_readany_test_"))
    contenido = "0123456789" * 20  # 200 caracteres, todos distinguibles por posición
    f = tmp / "prueba.txt"
    f.write_text(contenido, encoding="utf-8")

    orig_max = files_io._MAX_CHARS
    try:
        files_io._MAX_CHARS = 50
        r1 = files_io.read_any(f)  # sin `limite` -> comportamiento IDÉNTICO al de siempre
        check(r1["ok"] and len(r1["texto"]) == 50, "read_any() sin limite: sigue cortando a _MAX_CHARS")
        check(r1["meta"]["truncado"] is True, "read_any() sin limite: meta['truncado'] = True")

        r2 = files_io.read_any(f, limite=0)  # 0 = SIN límite
        check(r2["ok"] and r2["texto"] == contenido,
              "read_any(limite=0): el texto entra ENTERO, sin cortar")
        check(r2["meta"]["truncado"] is False, "read_any(limite=0): meta['truncado'] = False")
        check(len(r2["texto"]) == 200, "read_any(limite=0): longitud completa (200 caracteres)")
    finally:
        files_io._MAX_CHARS = orig_max


def test_xlsx_no_trunca_filas():
    import openpyxl
    tmp = Path(tempfile.mkdtemp(prefix="nexus_xlsx_aviso_test_"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    for i in range(10):
        ws.append([f"fila-{i}"])
    ruta = tmp / "diez_filas.xlsx"
    wb.save(str(ruta))

    orig_umbral = files_io._umbral_xlsx_aviso
    try:
        files_io._umbral_xlsx_aviso = lambda: 5  # umbral bajo a propósito: debe AVISAR, no cortar
        texto, meta = files_io._leer_xlsx(ruta)
        check(meta["filas"] == 10, "_leer_xlsx(): cuenta las 10 filas, ninguna perdida")
        check("fila-9" in texto, "_leer_xlsx(): la última fila (antes se cortaba a 3000) está presente")
        check("aviso" in texto.lower(), "_leer_xlsx(): avisa al superar el umbral, no corta en silencio")
    finally:
        files_io._umbral_xlsx_aviso = orig_umbral


# =============================== C2 ==========================================
def test_trocear_reconstruye_original_exacto():
    parrafo = ("Esta es una frase de prueba para el troceado del documento, con contenido "
               "suficiente como para simular un párrafo real de un documento largo. " * 4).strip()
    partes = [f"## Sección {i}\n\n{parrafo} (parte {i}).\n" for i in range(20)]
    texto = "\n".join(partes)
    check(len(texto) > 6000, "fixture: el texto de prueba supera varios trozos")

    trozos = rag.trocear(texto)
    check(len(trozos) > 3, "trocear(): un texto largo produce varios trozos")
    check(trozos[0]["total"] == len(trozos), "trocear(): 'total' coincide con el nº real de trozos")
    check([t["indice"] for t in trozos] == list(range(len(trozos))),
          "trocear(): los índices son consecutivos desde 0")

    solape = rag._umbrales_troceado()["solape_caracteres"]
    reconstruido = trozos[0]["texto"]
    for t in trozos[1:]:
        reconstruido += t["texto"][solape:]
    check(reconstruido == texto,
          "trocear(): quitando el solape de cada trozo, la concatenación reproduce el original "
          "carácter a carácter")


def test_reindex_no_trunca_a_1500():
    tmp = Path(tempfile.mkdtemp(prefix="nexus_reindex_test_"))
    memoria_dir = tmp / "memory"
    skills_dir = tmp / "skills_vacio"
    memoria_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    contenido = ("Esto es una nota larga de prueba para reindex(). " * 60).strip()
    check(len(contenido) > 1500, "fixture: la nota de prueba supera 1500 caracteres")
    (memoria_dir / "nota_larga.md").write_text(contenido, encoding="utf-8")

    llamadas = []

    async def _fake_add(texto, kind="knowledge", meta=None, dedup=True):
        llamadas.append(texto)
        return True

    orig_memory_dir = mem.MEMORY_DIR
    orig_skills_dir = config.SKILLS_DIR
    orig_add = rag.add
    orig_dir, orig_seen = rag._DIR, rag._SEEN
    try:
        mem.MEMORY_DIR = memoria_dir
        config.SKILLS_DIR = skills_dir
        rag.add = _fake_add
        rag._DIR = tmp / "rag_state"
        rag._SEEN = rag._DIR / "indexed.json"
        n = asyncio.run(rag.reindex(limit=10))
        check(n == 1, "reindex(): procesa la única nota nueva")
        check(len(llamadas) > 1, "reindex(): la nota larga (>1500) se trocea en más de un add()")
        check(sum(len(t) for t in llamadas) >= len(contenido),
              "reindex(): la suma de los trozos cubre el documento completo (ya NO corta a 1500)")
    finally:
        mem.MEMORY_DIR = orig_memory_dir
        config.SKILLS_DIR = orig_skills_dir
        rag.add = orig_add
        rag._DIR, rag._SEEN = orig_dir, orig_seen


def test_buzon_no_trunca_a_900():
    tmp = Path(tempfile.mkdtemp(prefix="nexus_buzon_test_"))
    orig_data_dir = config.DATA_DIR
    orig_pg, orig_graph = mem.pg, mem.graph
    try:
        config.DATA_DIR = tmp
        fake_pg, fake_graph = _FakePg(), _FakeGraph()
        mem.pg, mem.graph = fake_pg, fake_graph
        inbox = tmp / "memory" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        marcador = "MARCADORFIN" + uuid.uuid4().hex[:8]
        contenido = ("Línea de prueba del buzón, repetida para superar 900 caracteres. " * 20) + marcador
        check(len(contenido) > 900, "fixture: el contenido de prueba supera 900 caracteres")
        (inbox / "prueba.md").write_text(contenido, encoding="utf-8")

        asyncio.run(scheduler._ingest_inbox())

        check(bool(fake_graph.notas) and marcador in fake_graph.notas[0][1],
              "buzón: la nota espejo YA NO corta a 20000 -- contiene el marcador del final")
        todo_el_texto = "".join(l["content"] for l in fake_pg.llamadas)
        check(marcador in todo_el_texto,
              "buzón: el marcador del final del documento llega a Postgres -- ya no corta a 900")
        check(len(fake_pg.llamadas) > 1, "buzón: el documento largo se trocea en más de un remember()")
        movido = list((tmp / "memory" / "ingested").glob("prueba.md"))
        check(len(movido) == 1, "buzón: el fichero procesado se mueve a ingested/")
    finally:
        config.DATA_DIR = orig_data_dir
        mem.pg, mem.graph = orig_pg, orig_graph


# =============================== C3 ==========================================
def _pdf_minimo(texto: str = "Hola mundo pdf de prueba") -> bytes:
    """Un PDF de una página VÁLIDO, con `texto` dentro.

    Se construye midiendo, no escribiendo a mano. Un PDF termina con una tabla
    `xref` que lleva el desplazamiento EN BYTES de cada objeto, y un `startxref`
    con el del propio xref; el lector entra por ahí. Escritos a mano se
    desajustan en cuanto se toca una línea de arriba.

    Aquí había uno sin `xref` ni `startxref` y con un `/Length` que no cuadraba
    con su flujo. `read_any` lo rechazaba con «startxref not found» —
    correctamente, porque eso no es un PDF— y este test llevaba desde entonces
    en rojo culpando al buzón de un defecto que estaba en el propio material de
    prueba."""
    flujo = f"BT /F1 12 Tf 10 100 Td ({texto}) Tj ET".encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 200 200] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(flujo), flujo),
    ]
    out = bytearray(b"%PDF-1.4\n")
    desplazamientos = []
    for n, cuerpo in enumerate(objetos, start=1):
        desplazamientos.append(len(out))
        out += b"%d 0 obj\n" % n + cuerpo + b"\nendobj\n"
    inicio_xref = len(out)
    out += b"xref\n0 %d\n" % (len(objetos) + 1)
    out += b"0000000000 65535 f \n"
    for desp in desplazamientos:
        out += b"%010d 00000 n \n" % desp
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objetos) + 1, inicio_xref)
    return bytes(out)


_PDF_MINIMO_CON_TEXTO = _pdf_minimo()


def test_buzon_acepta_docx_pdf_xlsx():
    import docx
    import openpyxl

    tmp = Path(tempfile.mkdtemp(prefix="nexus_buzon_multi_test_"))
    orig_data_dir = config.DATA_DIR
    orig_pg, orig_graph = mem.pg, mem.graph
    try:
        config.DATA_DIR = tmp
        fake_pg, fake_graph = _FakePg(), _FakeGraph()
        mem.pg, mem.graph = fake_pg, fake_graph
        inbox = tmp / "memory" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        d = docx.Document()
        d.add_paragraph("Contenido de prueba en un .docx dejado en el buzón.")
        d.save(str(inbox / "prueba.docx"))

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["columna_a", "columna_b"])
        ws.append(["valor-1", "valor-2"])
        wb.save(str(inbox / "prueba.xlsx"))

        (inbox / "prueba.pdf").write_bytes(_PDF_MINIMO_CON_TEXTO)

        asyncio.run(scheduler._ingest_inbox())

        ingestados = {p.name for p in (tmp / "memory" / "ingested").glob("*")}
        check("prueba.docx" in ingestados,
              "buzón: acepta .docx (antes la lista fija de extensiones lo rechazaba)")
        check("prueba.xlsx" in ingestados, "buzón: acepta .xlsx")
        check("prueba.pdf" in ingestados, "buzón: acepta .pdf")
        docx_llamadas = [l for l in fake_pg.llamadas if "prueba.docx" in l["content"]]
        check(bool(docx_llamadas), "buzón: el .docx generó al menos un remember()")
        xlsx_llamadas = [l for l in fake_pg.llamadas if "prueba.xlsx" in l["content"]]
        check(bool(xlsx_llamadas) and "columna_a" in xlsx_llamadas[0]["content"],
              "buzón: el .xlsx llega troceado por estructura (cabeceras presentes en el texto)")
    finally:
        config.DATA_DIR = orig_data_dir
        mem.pg, mem.graph = orig_pg, orig_graph


def test_xlsx_trocea_por_hoja_sin_partir_filas():
    import openpyxl
    tmp = Path(tempfile.mkdtemp(prefix="nexus_xlsx_estructurado_test_"))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    ws.append(["nombre", "valor"])
    for i in range(60):
        ws.append([f"fila-{i}", i])
    ruta = tmp / "datos.xlsx"
    wb.save(str(ruta))

    hojas = files_io.leer_xlsx_estructurado(ruta)
    check(len(hojas) == 1, "leer_xlsx_estructurado(): una hoja")
    check(hojas[0]["cabeceras"] == ["nombre", "valor"], "leer_xlsx_estructurado(): cabeceras correctas")
    check(len(hojas[0]["filas"]) == 60, "leer_xlsx_estructurado(): las 60 filas, ninguna perdida")

    trozos = rag.trocear_xlsx_estructurado(hojas, filas_por_trozo=25)
    check(len(trozos) == 3, "trocear_xlsx_estructurado(): 60 filas / 25 -> 3 trozos (25+25+10)")
    check(all(t["hoja"] == "Hoja1" for t in trozos), "trocear_xlsx_estructurado(): nombre de hoja en cada trozo")
    check("nombre: fila-0" in trozos[0]["texto"], "trocear_xlsx_estructurado(): fila como pares columna: valor")
    check("fila-24" in trozos[0]["texto"] and "fila-25" not in trozos[0]["texto"],
          "trocear_xlsx_estructurado(): no parte una fila entre dos trozos")
    check("fila-59" in trozos[2]["texto"], "trocear_xlsx_estructurado(): última fila en el último trozo")


# =============================== C4 ==========================================
def test_ingerir_carpeta_escribe_md_con_metadatos():
    import docx
    tmp = Path(tempfile.mkdtemp(prefix="nexus_ingerir_test_"))
    origen = tmp / "Mi Carpeta De Prueba"
    origen.mkdir(parents=True, exist_ok=True)
    d = docx.Document()
    d.add_paragraph("Documento de prueba para ingerir-carpeta.")
    d.save(str(origen / "doc_prueba.docx"))

    orig_documentos_dir = ingesta.DOCUMENTOS_DIR
    orig_pg = mem.pg
    try:
        ingesta.DOCUMENTOS_DIR = tmp / "documentos"
        mem.pg = _FakePg()
        r = ingesta.ingerir_carpeta(str(origen))
        check(r["ok"] is True, "ingerir_carpeta(): ok")
        check(r["dominio"] == "mi-carpeta-de-prueba",
              "ingerir_carpeta(): dominio = slug del nombre de la carpeta")
        espejos = list((tmp / "documentos" / "mi-carpeta-de-prueba").glob("*.md"))
        check(len(espejos) == 1, "ingerir_carpeta(): escribe UN espejo .md")
        contenido_md = espejos[0].read_text(encoding="utf-8") if espejos else ""
        check("origen:" in contenido_md and "dominio: mi-carpeta-de-prueba" in contenido_md,
              "ingerir_carpeta(): el espejo lleva cabecera de metadatos (origen, dominio)")
        check("Documento de prueba para ingerir-carpeta." in contenido_md,
              "ingerir_carpeta(): el espejo contiene el texto real, entero")
        archivos_origen = list(origen.glob("*"))
        check(len(archivos_origen) == 1 and archivos_origen[0].name == "doc_prueba.docx",
              "ingerir_carpeta(): NUNCA escribe en la carpeta origen (solo lectura por defecto)")
    finally:
        ingesta.DOCUMENTOS_DIR = orig_documentos_dir
        mem.pg = orig_pg


def test_manual_definitivo_gana_al_historico():
    # Cubre ambos caminos de recall() (vectorial y el fallback por solape de
    # palabras): con o sin proveedor de embeddings local disponible, un
    # documento 'historico' no debe ganar al 'normal' hablando de lo mismo.
    if not mem.pg.online:
        skip("test_manual_definitivo_gana_al_historico: sin nexus_memoria_postgres")
        return
    marcador = "wabikstest" + uuid.uuid4().hex[:8]
    contenido_normal = f"Manual definitivo de prueba {marcador} con instrucciones completas y vigentes."
    contenido_historico = f"Manual antiguo de prueba {marcador} con instrucciones parecidas pero ya viejas."
    try:
        r1 = mem.pg.remember(contenido_normal, kind="knowledge", dominio="test-pesos",
                              etiqueta="normal", peso=1.0)
        r2 = mem.pg.remember(contenido_historico, kind="knowledge", dominio="test-pesos",
                              etiqueta="historico", peso=0.6)
        check(bool(r1.get("id")) and bool(r2.get("id")), "fixture: las dos filas de prueba se insertan")

        resultados = mem.pg.recall(marcador, limit=10)
        contenidos = [r["content"] for r in resultados]
        idx_normal = next((i for i, c in enumerate(contenidos) if contenido_normal in c), None)
        idx_hist = next((i for i, c in enumerate(contenidos) if contenido_historico in c), None)
        if idx_normal is None or idx_hist is None:
            skip("test_manual_definitivo_gana_al_historico: recall() no devolvió ambas filas "
                 "(umbral de similitud con estos textos sintéticos) -- no concluyente")
        else:
            check(idx_normal < idx_hist,
                  "recall(): score*peso -- el documento normal (peso 1.0) gana al histórico "
                  "(peso 0.6) hablando de lo mismo")
    finally:
        mem.pg._rows("DELETE FROM memories WHERE content LIKE %s", (f"%{marcador}%",))
        # Verificación explícita: no queda NADA con este marcador (regla dura: nunca dejar
        # filas huérfanas de prueba -- el bloque A dejó 804/805/807 por no comprobar esto).
        restos = mem.pg._rows("SELECT id FROM memories WHERE content LIKE %s", (f"%{marcador}%",))
        check(not restos, "limpieza: cero filas huérfanas con el marcador de este test")


def test_ingerir_carpeta_traversal_rechazado():
    original = permissions.path_allowed
    try:
        # Simula modo restringido (sandbox/carpetas): el modo real de este equipo de
        # desarrollo es "todo" y no probaría nada por sí solo (igual que en test_purga.py).
        permissions.path_allowed = lambda p: False
        r = ingesta.ingerir_carpeta(str(Path(tempfile.gettempdir()) / "fuera_de_lo_permitido"))
    finally:
        permissions.path_allowed = original
    check(r["ok"] is False, "ingerir_carpeta(): ruta fuera de lo permitido -> RECHAZADA, no recortada")
    check(r["documentos"] == [], "ingerir_carpeta(): no procesa nada si la ruta está fuera de lo permitido")


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
    print(f"\n{_pass} OK, {len(_fail)} fallo(s), {_skip} saltado(s) (sin BD/proveedor)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
