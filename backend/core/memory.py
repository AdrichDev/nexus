"""
nexus — Memoria persistente de doble capa.

Capa 1 (siempre activa): grafo de notas markdown estilo Obsidian en data/memory/.
  * Notas diarias  data/memory/daily/2026-07-18.md
  * Enlaces [[wiki]] entre notas → grafo consultable, sin base de datos.

Capa 2 (si Docker está levantado): Postgres + pgvector (contenedor nexus,
  puerto 5433, DB nexus_core). Guarda memorias, objetivos, checklists,
  recordatorios y facturas.  Si la DB no responde, TODO sigue funcionando
  con la capa 1 — degradación automática y transparente.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from .config import CONFIG_DIR, DATA_DIR, settings

try:
    import psycopg2
    import psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

MEMORY_DIR = DATA_DIR / "memory"
DAILY_DIR = MEMORY_DIR / "daily"
WIKILINK = re.compile(r"\[\[([^\]|#]+)")

# ---------------------------------------------------------------------
#  002-memoria-y-conocimiento (bloque A): política y estado de embeddings
# ---------------------------------------------------------------------
# La dimensión del vector NO se configura a mano en ningún sitio (eso
# reproduciría el bug de origen — 741 filas sin vector por un 768 fijo — en
# otra dirección). Tres fuentes, tres papeles (diseño §2):
#   * la propia columna Postgres (`format_type`)      → verdad del ALMACÉN
#   * data/memoria/estado_embeddings.json (aquí abajo) → verdad del MODELO,
#     medida BAJO DEMANDA (nunca en el arranque), no configuración
#   * config/umbrales.json → memoria.embedding          → solo POLÍTICA
ESTADO_EMBEDDINGS_FILE = DATA_DIR / "memoria" / "estado_embeddings.json"

_UMBRALES_EMBEDDING_RESERVA = {
    "proveedor_preferido": "ollama",
    "permitir_nube": False,
    "lote_reindex": 20,
    "filas_minimas_indice": 1000,
}


def _cargar_umbrales_embedding() -> dict:
    """Lee `memoria.embedding` de config/umbrales.json con reserva del código
    si el archivo falta o está roto (mismo patrón que rag.py/skills de
    Instagram): un umbral mal escrito no debe tumbar la memoria."""
    vals = dict(_UMBRALES_EMBEDDING_RESERVA)
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            crudo = json.loads(f.read_text(encoding="utf-8")) or {}
            leido = (crudo.get("memoria") or {}).get("embedding") or {}
            for k, v in leido.items():
                if k in vals and not str(k).startswith("_"):
                    vals[k] = v
    except Exception:
        pass
    return vals


def _leer_estado_embeddings() -> dict | None:
    """Última medición REAL guardada por `detectar_dimension()`. Se lee (no se
    mide) en cada consulta de estado — medir es una llamada al modelo y NO se
    hace como efecto colateral de un simple GET."""
    try:
        if ESTADO_EMBEDDINGS_FILE.is_file():
            return json.loads(ESTADO_EMBEDDINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _escribir_estado_embeddings(dimension: int, modelo: str, proveedor: str) -> None:
    """Estado DERIVADO (medido), nunca configuración: vive en data/, no en
    config/. Solo lo escribe una medición real de `detectar_dimension()`."""
    try:
        ESTADO_EMBEDDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ESTADO_EMBEDDINGS_FILE.write_text(json.dumps({
            "dimension": dimension, "modelo": modelo, "proveedor": proveedor,
            "medido_en": dt.datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _es_loopback(url: str) -> bool:
    """¿Esta URL apunta al propio equipo? Un Ollama en una URL que NO sea
    loopback tampoco es "local" a efectos de privacidad (memoria-embeddings,
    req. «Aislamiento de privacidad»)."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False


def _sale_del_equipo(proveedor: str, destino: str) -> bool:
    """`True` para cualquier proveedor de nube (openai/gemini/cloud) Y TAMBIÉN
    para un Ollama cuya URL no sea loopback — ver `_es_loopback`."""
    prov = (proveedor or "").lower()
    if prov == "ollama":
        return not _es_loopback(destino)
    if prov in ("openai", "gemini", "cloud"):
        return True
    return True  # proveedor desconocido: por precaución, se asume que sale


# ----------------------------------------------------------------------
#  Capa 1 — Grafo de notas markdown
# ----------------------------------------------------------------------
class NoteGraph:
    def __init__(self):
        DAILY_DIR.mkdir(parents=True, exist_ok=True)

    def _daily_path(self, day: dt.date | None = None) -> Path:
        day = day or dt.date.today()
        return DAILY_DIR / f"{day.isoformat()}.md"

    def append_daily(self, text: str, section: str = "Registro") -> str:
        """Añade una entrada a la nota diaria (la crea si no existe)."""
        path = self._daily_path()
        stamp = dt.datetime.now().strftime("%H:%M")
        if not path.exists():
            path.write_text(
                f"# {dt.date.today().isoformat()}\n\n"
                f"Enlaces: [[objetivos]] · [[ideas]]\n\n## {section}\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- **{stamp}** {text}\n")
        return str(path.name)

    def write_note(self, title: str, content: str) -> str:
        safe = re.sub(r"[^\w\- áéíóúñÁÉÍÓÚÑ]", "", title).strip() or "nota"
        path = MEMORY_DIR / f"{safe}.md"
        path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        return str(path.name)

    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Búsqueda por SOLAPE de palabras en las notas de conocimiento.

        Excluye el log de conversación (daily/ y líneas «→ **nexus:**») para no
        devolver como 'memoria' lo que en realidad es la charla anterior."""
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2] or [query.lower()]
        scored: list[tuple] = []
        for path in MEMORY_DIR.rglob("*.md"):
            if path.parent.name == "daily":          # el diario es log, no conocimiento
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in text.splitlines():
                low = line.lower()
                if not line.strip() or "→ **nexus:**" in low or low.startswith("- **"):
                    continue
                hits = sum(1 for w in words if w in low)
                if hits:
                    scored.append((hits, {"file": path.name, "line": line.strip()}))
        scored.sort(key=lambda x: -x[0])
        seen, out = set(), []
        for _, d in scored:
            if d["line"] in seen:
                continue
            seen.add(d["line"])
            out.append(d)
            if len(out) >= limit:
                break
        return out

    def graph(self) -> dict:
        """Nodos (notas) y aristas (wikilinks [[...]]) — el 'grafo Obsidian'.

        Los DESTINOS de los enlaces también entran como nodos (hubs como
        [[conocimiento]] o [[documentos]]) aunque no exista su .md: así todas
        las notas que dependen del MISMO conocimiento quedan CONECTADAS entre
        sí y comparten grupo/color en el HUD."""
        nodes, edges = [], []
        for path in MEMORY_DIR.rglob("*.md"):
            name = path.stem
            nodes.append(name)
            try:
                for target in WIKILINK.findall(path.read_text(encoding="utf-8")):
                    edges.append([name, target.strip()])
            except Exception:
                pass
        known = set(nodes)
        for _a, b in edges:              # hubs virtuales → nodos de pleno derecho
            if b not in known:
                known.add(b)
                nodes.append(b)
        return {"nodes": nodes, "edges": edges}


# ----------------------------------------------------------------------
#  Capa 2 — Postgres + pgvector (contenedor nexus)
# ----------------------------------------------------------------------
class PgMemory:
    def __init__(self):
        self._conn = None
        self._schema_ready = False
        # 002-memoria-y-conocimiento (bloque A):
        self._planes_reindexado: dict[str, dict] = {}   # plan_reindexado() en vuelo
        self.descartes_por_dimension = 0                # contador visible en /api/memoria/estado
        self._avisado_descarte = False                  # UN aviso por sesión, no uno por fila

    @property
    def dsn(self) -> str:
        # Orden: NEXUS_DB_URL (.env) → settings.json → nada. Ninguno de los dos
        # archivos se sube al repositorio, así que la contraseña no se publica.
        return (os.environ.get("NEXUS_DB_URL", "").strip()
                or settings.get("db_url", ""))

    def connect(self):
        if not HAS_PG:
            return None
        if self._conn is not None:
            try:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return self._conn
            except Exception:
                self._conn = None
        try:
            self._conn = psycopg2.connect(self.dsn, connect_timeout=2)
            self._conn.autocommit = True
            self._ensure_schema()
            self._warned = False
        except Exception as exc:                           # noqa: BLE001
            self._conn = None
            self._log_conn_error(exc)
        return self._conn

    _warned = False

    def _log_conn_error(self, exc) -> None:
        """Explica en el log POR QUÉ no conecta la memoria (antes se tragaba el
        error y parecía «sin memoria» sin motivo). Un aviso por fallo, no en bucle."""
        if getattr(self, "_warned", False):
            return
        self._warned = True
        msg = str(exc).lower()
        if "authentication failed" in msg or "password" in msg:
            hint = ("el usuario/clave de NEXUS_DB_URL no coincide con los del contenedor "
                    "nexus_memoria_postgres. Ejecuta data\\CENTRALIZAR_DOCKER_nexus.bat o "
                    "corrige NEXUS_DB_URL en .env.")
        elif "does not exist" in msg and "database" in msg:
            hint = ("la base 'nexus_core' no existe en el contenedor. Ejecuta "
                    "data\\CENTRALIZAR_DOCKER_nexus.bat (la crea).")
        elif "could not connect" in msg or "connection refused" in msg or "timeout" in msg:
            hint = ("el contenedor Postgres no responde en el puerto 5433. Arráncalo: "
                    "docker start nexus_memoria_postgres (o ejecuta "
                    "data\\CENTRALIZAR_DOCKER_nexus.bat).")
        else:
            hint = "revisa el contenedor nexus_memoria_postgres y NEXUS_DB_URL en .env."
        try:
            from .events import bus
            bus.emit_sync("log", {"level": "warn",
                                  "msg": f"🧠 Memoria Postgres OFFLINE: {type(exc).__name__}. {hint}"})
        except Exception:
            pass

    # --- AUTO-REPARACIÓN del esquema: nexus crea SU PROPIA memoria ------------
    # Antes las tablas las creaba un init.sql del contenedor; si el contenedor se
    # recreaba vacío (como openClaw_Nexus_db), TODA consulta fallaba y nexus se
    # quedaba «sin memoria». Ahora, en cuanto conecta, se asegura de tener sus
    # tablas + la extensión pgvector. Idempotente (IF NOT EXISTS) y tolerante:
    # cada sentencia va en su try para que un fallo suelto no tumbe el resto.
    _DDL = [
        "CREATE EXTENSION IF NOT EXISTS vector",
        ("CREATE TABLE IF NOT EXISTS memories (id BIGSERIAL PRIMARY KEY, "
         "kind TEXT NOT NULL DEFAULT 'note', content TEXT NOT NULL, "
         "tags TEXT[] DEFAULT '{}', embedding vector(768), "
         "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"),
        # respaldo si NO hubiera pgvector: la tabla sin columna de embedding
        ("CREATE TABLE IF NOT EXISTS memories (id BIGSERIAL PRIMARY KEY, "
         "kind TEXT NOT NULL DEFAULT 'note', content TEXT NOT NULL, "
         "tags TEXT[] DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())"),
        ("CREATE TABLE IF NOT EXISTS reminders (id BIGSERIAL PRIMARY KEY, "
         "task_title TEXT NOT NULL, due_at TIMESTAMPTZ, notify_at TIMESTAMPTZ, "
         "fired BOOLEAN NOT NULL DEFAULT FALSE)"),
        ("CREATE TABLE IF NOT EXISTS goals (id BIGSERIAL PRIMARY KEY, "
         "title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', "
         "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"),
        ("CREATE TABLE IF NOT EXISTS goal_steps (id BIGSERIAL PRIMARY KEY, "
         "goal_id BIGINT REFERENCES goals(id) ON DELETE CASCADE, "
         "position INT NOT NULL DEFAULT 0, title TEXT NOT NULL, "
         "done BOOLEAN NOT NULL DEFAULT FALSE)"),
        ("CREATE TABLE IF NOT EXISTS clients (id BIGSERIAL PRIMARY KEY, "
         "name TEXT UNIQUE NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"),
        ("CREATE TABLE IF NOT EXISTS invoices (id BIGSERIAL PRIMARY KEY, "
         "client_id BIGINT REFERENCES clients(id) ON DELETE SET NULL, "
         "number TEXT, concept TEXT, amount NUMERIC(12,2), "
         "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"),
        # 002-memoria-y-conocimiento (A4.2): huella de deduplicación. Columna
        # NUEVA, nullable, aditiva — nada que ya exista pierde nada. El índice
        # ÚNICO sobre esta columna NO se crea aquí: eso exige que la limpieza
        # de duplicados esté confirmada primero (bloque B, ver
        # _maybe_crear_indice_vector / _indice_huella_existe más abajo para el
        # equivalente del vector, y purga.py para la huella).
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS huella TEXT",
        # 002-memoria-y-conocimiento (bloque B): papelera como ESTADO, no
        # destrucción — retirar una fila es un UPDATE, nunca un DELETE.
        # Columnas nuevas, nullable, aditivas. Ver purga.py.
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS retirado_en TIMESTAMPTZ",
        "ALTER TABLE memories ADD COLUMN IF NOT EXISTS retirado_lote TEXT",
        # 002-memoria-y-conocimiento (bloque C, C1.2): metadatos de origen
        # para la ingesta de documentos. DEFAULT 'sin-clasificar' en dominio
        # resuelve la pregunta abierta del diseño para filas históricas sin
        # origen (no hace falta backfill: ya cumplen el NOT NULL solas).
        # Columnas nuevas, nullable salvo dominio/peso, aditivas.
        ("ALTER TABLE memories ADD COLUMN IF NOT EXISTS origen TEXT, "
         "ADD COLUMN IF NOT EXISTS origen_tipo TEXT, "
         "ADD COLUMN IF NOT EXISTS dominio TEXT NOT NULL DEFAULT 'sin-clasificar', "
         "ADD COLUMN IF NOT EXISTS etiqueta TEXT, "
         "ADD COLUMN IF NOT EXISTS peso REAL NOT NULL DEFAULT 1.0"),
        # El índice de similitud (ivfflat) YA NO se crea aquí incondicional:
        # con pocas filas (741/lists=100 → ~7 filas por lista) pierde recall
        # frente a un recorrido secuencial, que además es EXACTO. Ver
        # _maybe_crear_indice_vector(), que solo lo crea por encima de
        # memoria.embedding.filas_minimas_indice (A2.3).
    ]

    def _ensure_schema(self) -> None:
        if self._schema_ready or self._conn is None:
            return
        has_vector = True
        for i, ddl in enumerate(self._DDL):
            # la 3ª sentencia es el respaldo sin-pgvector: solo si la extensión falló
            if i == 2 and has_vector:
                continue
            try:
                with self._conn.cursor() as cur:
                    cur.execute(ddl)
            except Exception as exc:                       # noqa: BLE001
                if i == 0:
                    has_vector = False                      # sin pgvector → usar respaldo
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                try:
                    from .events import bus
                    bus.emit_sync("log", {"level": "warn",
                                          "msg": f"Memoria: DDL {i} no aplicó ({type(exc).__name__})."})
                except Exception:
                    pass
        self._maybe_crear_indice_vector()
        self._schema_ready = True
        try:
            from .events import bus
            bus.emit_sync("log", {"level": "ok", "msg": "🧠 Memoria Postgres lista (esquema verificado)."})
        except Exception:
            pass

    def _maybe_crear_indice_vector(self, tabla: str = "memories") -> None:
        """El índice ivfflat con `lists=100` a fuego perdía sentido con pocas
        filas: 741 filas / 100 listas = ~7 filas por lista, PEOR que un
        recorrido secuencial (que además es exacto, no aproximado). Solo se
        crea por encima de `memoria.embedding.filas_minimas_indice` (reserva
        1000), y con `lists = max(1, filas // 1000)` (diseño §1, «índice
        vectorial mal dimensionado»). `tabla` es parametrizable para poder
        probar esto contra una tabla de prueba sin tocar `memories` real."""
        if self._conn is None:
            return
        umbral = _cargar_umbrales_embedding()
        minimo = int(umbral.get("filas_minimas_indice", 1000))
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {tabla}")
                filas = cur.fetchone()[0]
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass
            return
        if filas < minimo:
            return
        lists = max(1, filas // 1000)
        idx = f"{tabla}_embedding_idx"
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx} ON {tabla} "
                    f"USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})")
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass

    @property
    def online(self) -> bool:
        if settings.get("memory_backend") == "files":
            return False
        return self.connect() is not None

    def _rows(self, sql: str, params=()) -> list[dict]:
        conn = self.connect()
        if conn is None:
            return []
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return [dict(r) for r in cur.fetchall()]
        return []

    # --- Dimensión real: se MIDE, nunca se supone (memoria-embeddings) ---
    def _dimension_columna(self, tabla: str = "memories") -> int | None:
        """Dimensión REAL de `{tabla}.embedding` según Postgres
        (`format_type`) — es la única fuente que no puede mentir: si la
        columna es `vector(1024)`, lo es (diseño §2)."""
        conn = self.connect()
        if conn is None:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = %s::regclass AND attname = 'embedding' "
                    "AND NOT attisdropped", (tabla,))
                row = cur.fetchone()
            if row and row[0]:
                m = re.search(r"vector\((\d+)\)", row[0])
                if m:
                    return int(m.group(1))
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        return None

    def detectar_dimension(self) -> dict:
        """Pide un embedding DE PRUEBA al modelo activo (política de memoria,
        `memoria.embedding.proveedor_preferido`) y lo compara con la
        dimensión real de la columna. NO cambia nada — solo mide y avisa
        (memoria-embeddings, escenario «Dimensión distinta a la columna»).
        Escribe la medición en estado_embeddings.json: es la ÚNICA función
        de este módulo que hace una llamada real de embedding, así que solo
        se invoca bajo demanda (nunca en el arranque ni en un simple GET)."""
        from . import rag
        umbral = _cargar_umbrales_embedding()
        proveedor = umbral.get("proveedor_preferido", "ollama")
        modelo = settings.get("embed_model", "nomic-embed-text")
        columna = self._dimension_columna()
        medida = None
        try:
            vec = rag._embed_sync("nexus", proveedor=proveedor)
            medida = len(vec) if vec else None
        except Exception:
            medida = None
        if medida is not None:
            _escribir_estado_embeddings(medida, modelo, proveedor)
        pendiente = medida is not None and columna is not None and medida != columna
        if pendiente:
            try:
                from .events import bus
                bus.emit_sync("log", {"level": "warn",
                    "msg": f"🧠 Memoria: reindexado pendiente — la columna está en "
                           f"vector({columna}) pero el modelo activo («{modelo}») da "
                           f"{medida}."})
            except Exception:
                pass
        return {"columna": columna, "medida": medida, "modelo": modelo,
                "proveedor": proveedor, "reindexado_pendiente": pendiente}

    def migrar_vector(self, dim: int, tabla: str = "memories") -> dict:
        """Migra `embedding` a `vector(dim)` SIN PERDER NI UNA FILA: renombra
        la columna vieja a `{tabla}_dim{N}` en vez de un `ALTER COLUMN ...
        TYPE`, que pgvector RECHAZA entre dimensiones distintas en cuanto hay
        vectores guardados (diseño §1). Cada paso queda en audit.log. Quien
        llama a esto YA tiene el «sí» del usuario — ver
        `POST /api/memoria/vector/migrar`, que pasa por `confirm.request()`
        antes de invocar esta función.
        `tabla` es parametrizable para poder probar la migración de verdad
        (contra Postgres real) sin tocar la tabla `memories` de producción."""
        from . import audit
        conn = self.connect()
        if conn is None:
            return {"ok": False, "error": "sin conexión a Postgres"}
        actual = self._dimension_columna(tabla)
        if actual == dim:
            return {"ok": False, "error": f"«{tabla}» ya está en vector({dim})"}
        nombre_vieja = f"{'embedding' if tabla == 'memories' else tabla}_dim{actual or 'legacy'}"
        pasos = []
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP INDEX IF EXISTS {tabla}_embedding_idx")
            pasos.append(f"DROP INDEX IF EXISTS {tabla}_embedding_idx")
            audit.log(action="memoria_migrar_vector", destructive=True, confirmed=True,
                      result=pasos[-1], extra={"paso": 1, "tabla": tabla})

            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {tabla} RENAME COLUMN embedding TO {nombre_vieja}")
            pasos.append(f"ALTER TABLE {tabla} RENAME COLUMN embedding TO {nombre_vieja}")
            audit.log(action="memoria_migrar_vector", destructive=True, confirmed=True,
                      result=pasos[-1], extra={"paso": 2, "tabla": tabla})

            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {tabla} ADD COLUMN embedding vector({int(dim)})")
            pasos.append(f"ALTER TABLE {tabla} ADD COLUMN embedding vector({dim})")
            audit.log(action="memoria_migrar_vector", destructive=True, confirmed=True,
                      result=pasos[-1], extra={"paso": 3, "tabla": tabla})
        except Exception as exc:                                  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:
                pass
            audit.log(action="memoria_migrar_vector", destructive=True, confirmed=True,
                      error=f"{type(exc).__name__}: {exc}", result="FALLÓ",
                      extra={"tabla": tabla})
            return {"ok": False, "error": str(exc), "pasos": pasos}
        if tabla == "memories":
            self._schema_ready = False
            self._maybe_crear_indice_vector(tabla)
        return {"ok": True, "pasos": pasos, "columna_vieja": nombre_vieja,
                "columna_nueva_dim": dim}

    # --- Reindexado explícito, por lotes, privado por defecto ------------
    def plan_reindexado(self, proveedor: str | None = None) -> dict:
        """Presupuesto del reindexado ANTES de lanzarlo: cuántas filas,
        cuántas llamadas, a qué proveedor/destino, y si el contenido SALE del
        equipo. Solo MIDE — no reindexa nada (memoria-embeddings, req.
        «Aislamiento de privacidad»)."""
        umbral = _cargar_umbrales_embedding()
        prov = (proveedor or umbral.get("proveedor_preferido", "ollama")).lower()
        filas = 0
        conn = self.connect()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM memories WHERE embedding IS NULL "
                        "AND kind <> 'conversation'")
                    filas = cur.fetchone()[0]
            except Exception:
                filas = 0
        if prov == "ollama":
            destino = settings.get("ollama_url", "http://localhost:11434")
        elif prov in ("openai", "cloud"):
            destino = settings.get("cloud_base_url", "https://api.openai.com/v1")
        elif prov == "gemini":
            destino = "https://generativelanguage.googleapis.com"
        else:
            destino = ""
        sale = _sale_del_equipo(prov, destino)
        modelo = settings.get("embed_model", "nomic-embed-text")
        aviso = (f"{filas} llamadas a «{prov}» ({destino or 'desconocido'}). " + (
            "El contenido de tus documentos SALE de este equipo hacia ese proveedor."
            if sale else "El texto no sale de este equipo."))
        plan_id = f"plan-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        caduca_dt = dt.datetime.now() + dt.timedelta(minutes=30)
        plan = {"id": plan_id, "filas": filas, "llamadas": filas, "proveedor": prov,
                "modelo": modelo, "destino": destino, "sale_del_equipo": sale,
                "aviso": aviso, "caduca": caduca_dt.isoformat(timespec="seconds")}
        self._planes_reindexado[plan_id] = {**plan, "_caduca_dt": caduca_dt}
        return plan

    def reindexar(self, plan_id: str, confirmar_nube: bool = False,
                  tabla: str = "memories") -> dict:
        """Ejecuta el plan por lotes (`memoria.embedding.lote_reindex`),
        REANUDABLE: siempre coge las primeras filas SIN embedding, así una
        llamada interrumpida no reprocesa lo que ya quedó reindexado
        (memoria-embeddings, escenario «Reindexado interrumpido a mitad»).
        Con `permitir_nube:false` y proveedor de nube, falla con motivo claro
        SIN llegar a la interfaz. Con nube permitida, exige que quien llama YA
        haya confirmado (`confirmar_nube=True`) — la interfaz solo puede
        marcarlo tras mostrar el aviso de `plan_reindexado()`.
        `tabla` es parametrizable (igual que `migrar_vector`/
        `_maybe_crear_indice_vector`) para poder probar el reanudado con
        embeddings simulados SIN escribir vectores falsos encima de
        `memories` real."""
        plan = self._planes_reindexado.get(plan_id)
        if not plan:
            return {"ok": False, "error": f"plan «{plan_id}» desconocido o caducado"}
        if dt.datetime.now() > plan["_caduca_dt"]:
            self._planes_reindexado.pop(plan_id, None)
            return {"ok": False, "error": "el plan ha caducado, pide uno nuevo"}
        umbral = _cargar_umbrales_embedding()
        proveedor = plan["proveedor"]
        if plan["sale_del_equipo"]:
            if not umbral.get("permitir_nube", False):
                return {"ok": False, "error": (
                    f"«{proveedor}» hace que el contenido salga del equipo y "
                    f"memoria.embedding.permitir_nube está en false en "
                    f"config/umbrales.json.")}
            if not confirmar_nube:
                return {"ok": False, "error": (
                    f"reindexado a «{proveedor}» ({plan['llamadas']} llamadas) exige "
                    f"confirmación explícita: el contenido sale de este equipo.")}
        conn = self.connect()
        if conn is None:
            return {"ok": False, "error": "sin conexión a Postgres"}
        from . import rag, audit
        lote = max(1, int(umbral.get("lote_reindex", 20)))
        procesadas = fallidas = 0
        fallidos_ids: list[int] = []
        filtro_kind = "AND kind <> 'conversation' " if tabla == "memories" else ""
        while True:
            if fallidos_ids:
                rows = self._rows(
                    f"SELECT id, content FROM {tabla} WHERE embedding IS NULL "
                    f"{filtro_kind}AND id <> ALL(%s) ORDER BY id LIMIT %s",
                    (fallidos_ids, lote))
            else:
                rows = self._rows(
                    f"SELECT id, content FROM {tabla} WHERE embedding IS NULL "
                    f"{filtro_kind}ORDER BY id LIMIT %s", (lote,))
            if not rows:
                break
            for r in rows:
                try:
                    vec = rag._embed_sync(r["content"], proveedor=proveedor)
                except Exception:
                    vec = None
                if vec:
                    self._rows(
                        f"UPDATE {tabla} SET embedding = %s WHERE id = %s RETURNING id",
                        (str(vec), r["id"]))
                    procesadas += 1
                else:
                    fallidas += 1
                    fallidos_ids.append(r["id"])
        audit.log(action="memoria_reindexar", destructive=False, confirmed=True,
                  result=f"{procesadas} reindexadas, {fallidas} fallidas",
                  extra={"plan_id": plan_id, "proveedor": proveedor, "tabla": tabla})
        self._planes_reindexado.pop(plan_id, None)
        if tabla == "memories":
            self._schema_ready = False
            self._maybe_crear_indice_vector()
        return {"ok": True, "procesadas": procesadas, "fallidas": fallidas}

    # --- Embeddings (RAG auto-aprendiente) -------------------------------
    # Cada recuerdo se vectoriza con el proveedor de POLÍTICA DE MEMORIA
    # (memoria.embedding.proveedor_preferido), NUNCA con embed_provider:auto
    # (que sigue al cerebro de chat) — así cambiar el cerebro de Gemini a
    # otra nube no arrastra los embeddings (memoria-embeddings, escenario
    # «Cambio de cerebro de chat no afecta a embeddings»). recall() busca
    # entonces por SIGNIFICADO (coseno pgvector), no solo por palabra exacta.
    def _embed(self, text: str) -> list[float] | None:
        # ANTES: comparaba contra 768 a fuego (memory.py:273-282) y descartaba
        # en silencio — 741 filas se quedaron sin vector por esto. AHORA
        # compara con la dimensión REAL de la columna, y todo descarte suma a
        # un contador visible en /api/memoria/estado con UN aviso por sesión
        # (nunca uno por fila, que sería una riada de log).
        try:
            from . import rag
            proveedor = _cargar_umbrales_embedding().get("proveedor_preferido", "ollama")
            vec = rag._embed_sync(text, proveedor=proveedor)
            if not vec:
                return None
            dim = self._dimension_columna()
            if dim is not None and len(vec) != dim:
                self.descartes_por_dimension += 1
                if not self._avisado_descarte:
                    self._avisado_descarte = True
                    try:
                        from .events import bus
                        bus.emit_sync("log", {"level": "warn",
                            "msg": f"🧠 Memoria: vector de {len(vec)} no encaja con la "
                                   f"columna vector({dim}) — fila(s) sin vector, "
                                   f"recuperable(s) por texto. Reindexado pendiente."})
                    except Exception:
                        pass
                return None
            return vec
        except Exception:
            return None

    # --- Huella / deduplicación (memoria-deduplicacion) -------------------
    def _indice_huella_existe(self, tabla: str = "memories") -> bool:
        """¿Existe ya `{tabla}_huella_idx`? En el bloque A nunca existe — se
        crea solo tras confirmar la limpieza de duplicados (bloque B, orden
        obligado del diseño §4). `tabla` parametrizable SOLO para que
        `test_purga.py` pueda probar la creación real del índice sobre una
        tabla de usar-y-tirar, nunca sobre `memories`."""
        conn = self.connect()
        if conn is None:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE tablename = %s "
                    "AND indexname = %s", (tabla, f"{tabla}_huella_idx"))
                return cur.fetchone() is not None
        except Exception:
            return False

    def backfill_huella(self) -> dict:
        """Calcula la huella para filas HISTÓRICAS que no la tienen. Paso de
        MANTENIMIENTO EXPLÍCITO — no se ejecuta en cada arranque
        (memoria-deduplicacion, «Autorreparación»)."""
        conn = self.connect()
        if conn is None:
            return {"ok": False, "error": "sin conexión a Postgres"}
        from . import rag
        rows = self._rows("SELECT id, kind, content FROM memories WHERE huella IS NULL")
        n = 0
        for r in rows:
            h = rag.huella(f"{r['kind']}\n{r['content']}")
            self._rows("UPDATE memories SET huella = %s WHERE id = %s RETURNING id",
                       (h, r["id"]))
            n += 1
        return {"ok": True, "actualizadas": n}

    def duplicados_exactos(self, tabla: str = "memories") -> list[dict]:
        """Informe de SOLO LECTURA: agrupa por huella con `count(*) > 1`, dice
        qué fila se conservaría (la más antigua) y cuáles sobran. NO BORRA
        NADA — alimenta a `purga.py` (categoría `duplicados-exactos`) en el
        bloque B (memoria-deduplicacion, escenario «Previsualización de
        duplicados antes de limpiar»).

        `tabla` es parametrizable por el mismo motivo que en
        `crear_indice_huella()`: desde que la purga real creó
        `memories_huella_idx`, `test_purga.py` YA NO PUEDE meter dos filas
        con la misma huella en `memories` para probar el agrupado — el
        índice único se lo impide, que es justo lo que se quería. En
        producción siempre es `memories`."""
        conn = self.connect()
        if conn is None:
            return []
        # AND retirado_en IS NULL en ambas consultas (bloque B): una fila ya
        # retirada por purga.py no debe seguir contando como «duplicado
        # pendiente» — si no, B4.2 nunca vería la limpieza como confirmada.
        grupos = self._rows(
            f"SELECT huella, count(*) AS n FROM {tabla} "
            "WHERE huella IS NOT NULL AND retirado_en IS NULL "
            "GROUP BY huella HAVING count(*) > 1 ORDER BY n DESC")
        out = []
        for g in grupos:
            filas = self._rows(
                f"SELECT id, kind, content, created_at FROM {tabla} "
                "WHERE huella = %s AND retirado_en IS NULL "
                "ORDER BY created_at ASC, id ASC", (g["huella"],))
            if len(filas) < 2:
                continue
            out.append({"huella": g["huella"], "total": len(filas),
                        "conservar": filas[0], "sobran": filas[1:]})
        return out

    # --- Purga (bloque B): vínculo nota↔filas, retirar/restaurar, cierre --
    def filas_ligadas_a_nota(self, nombre_fichero: str) -> list[dict]:
        """Filas cuyo contenido lleva el prefijo `[nombre]` — el ÚNICO
        vínculo nota↔fila que existe hasta que el bloque C añada
        `origen`/`dominio` (lo pone `scheduler.py:45` al ingerir el buzón).
        Las filas SIN ese prefijo no se ligan a ninguna nota; purga.py no
        las toca por retirar la nota (memoria-purga, «Alcance dual»)."""
        return self._rows(
            "SELECT id FROM memories WHERE content LIKE %s AND retirado_en IS NULL",
            (f"[{nombre_fichero}]%",))

    def filas_de_carpeta(self, carpeta: str, incluir_retiradas: bool = False) -> list[dict]:
        """Filas que declaran venir de esa carpeta, la lleven marcada o no.

        SEGUNDO vínculo, y el que faltaba. Al ingerir una carpeta, cada
        fragmento escribe en su propio texto la línea `Carpeta: <nombre>`. Eso
        es procedencia declarada, y estaba ahí sin que nadie la usara.

        INCIDENTE que obliga a esto (02/08/2026): tras purgar la carpeta
        «20. FP DAM Euroformac» quedaron **32 filas vivas y buscables**. Las
        notas `.md` sí se fueron a la papelera, pero `filas_ligadas_a_nota()`
        solo ve las que empiezan por `[fichero]`, y estas empiezan por
        `# doc <título>`. Sin dueño y sin marca, nadie las reclamaba: se
        quedaban en la memoria vectorial contestando a las búsquedas.

        Se busca por la marca entera para no confundir carpetas cuyo nombre es
        prefijo de otra («20. FP» no puede llevarse «20. FP DAM Euroformac»).

        Se mira por las TRES vías, porque cada ingesta dejó una marca distinta:
          * `origen` — lo pone la ingesta desde 02/08/2026, en cada fragmento.
          * el prefijo `[carpeta › archivo]` del texto — desde antes.
          * la línea `Carpeta: <nombre>` — solo en el PRIMER trozo de cada
            documento, que es justo por lo que hacían falta las otras dos.
        """
        cond = ["origen LIKE %s", "content LIKE %s", "content LIKE %s"]
        params = [f"{carpeta}/%", f"[{carpeta} › %", f"%Carpeta: {carpeta}\n%"]
        sql = "SELECT id FROM memories WHERE (" + " OR ".join(cond) + ")"
        if not incluir_retiradas:
            sql += " AND retirado_en IS NULL"
        return self._rows(sql + " ORDER BY id", tuple(params))

    def filas_sin_marca_origen(self, tipos: list[str] | None = None) -> list[dict]:
        """Filas HUÉRFANAS: ni marca `[fichero]` en el texto ni columna
        `origen` (que el bloque C añadió a todo lo ingerido). Son las 464 de
        697 filas `knowledge` anteriores al bloque C.

        INCIDENTE que obliga a esto: `previsualizar()` devolvía `filas_pg: 0`
        en todas las categorías porque `filas_ligadas_a_nota()` solo ve las
        233 filas con marca. Retirar las 35 notas de la FP habría dejado 10
        filas de tablespaces / actividades / 2DAM vivas y buscables en la
        memoria vectorial, justo lo contrario de lo que se pidió.

        Excluye a propósito las filas que YA tienen dueño (marca u `origen`):
        esas se ligan por el camino de siempre y nadie más puede reclamarlas.
        `purga.py` las casa por CONTENIDO; aquí solo se sacan del almacén."""
        tipos = list(tipos or ["knowledge"])
        return self._rows(
            "SELECT id, content FROM memories "
            "WHERE retirado_en IS NULL AND origen IS NULL "
            "AND content NOT LIKE '[%%' AND kind = ANY(%s) ORDER BY id",
            (tipos,))

    def retirar_filas(self, ids: list[int], lote: str) -> int:
        """`UPDATE`, nunca `DELETE`: retirar es un cambio de estado
        reversible (memoria-purga, «Papelera reversible en dos tiempos»)."""
        if not ids:
            return 0
        rows = self._rows(
            "UPDATE memories SET retirado_en = now(), retirado_lote = %s "
            "WHERE id = ANY(%s) AND retirado_en IS NULL RETURNING id",
            (lote, ids))
        return len(rows)

    def restaurar_filas(self, lote: str) -> int:
        """Revertir un lote entero es OTRO `UPDATE` — nunca hace falta
        reconstruir nada (memoria-purga, escenario «Restaurar desde la
        papelera»)."""
        rows = self._rows(
            "UPDATE memories SET retirado_en = NULL, retirado_lote = NULL "
            "WHERE retirado_lote = %s RETURNING id", (lote,))
        return len(rows)

    def crear_indice_huella(self, tabla: str = "memories") -> dict:
        """Índice ÚNICO y PARCIAL sobre `huella` — SOLO tras confirmar la
        limpieza de duplicados (orden obligado, diseño §4). Si quedan
        grupos duplicados sin retirar, NO se crea (memoria-deduplicacion,
        «Consulta de duplicados exactos vacía»). `tabla` parametrizable
        SOLO para que `test_purga.py` ejercite la creación real del índice
        sobre una tabla de usar-y-tirar — en producción siempre es
        `memories` (valor por defecto, el único que usa `aplicar()`)."""
        idx = f"{tabla}_huella_idx"
        if self._indice_huella_existe(tabla):
            return {"ok": True, "ya_existia": True}
        dups = self.duplicados_exactos() if tabla == "memories" else []
        if dups:
            return {"ok": False, "error": (
                f"quedan {len(dups)} grupo(s) de duplicados sin limpiar: "
                f"confirma la categoría «duplicados-exactos» primero.")}
        conn = self.connect()
        if conn is None:
            return {"ok": False, "error": "sin conexión a Postgres"}
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {idx} "
                    f"ON {tabla}(huella) WHERE retirado_en IS NULL")
        except Exception as exc:                                  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:
                pass
            return {"ok": False, "error": str(exc)}
        from . import audit
        audit.log(action="memoria_crear_indice_huella", destructive=False,
                  confirmed=True, result=f"{idx} creado", extra={"tabla": tabla})
        return {"ok": True, "ya_existia": False}

    def limpiar_respaldo(self, tabla: str = "memories") -> dict:
        """Cierra la migración A2: suelta la columna de respaldo
        `{tabla}_dim{N}` que dejó `migrar_vector()`. SEGUNDA acción
        explícita — nunca automática ni encadenada a la migración (diseño
        §1, «soltar el respaldo es una segunda acción explícita»)."""
        conn = self.connect()
        if conn is None:
            return {"ok": False, "error": "sin conexión a Postgres"}
        prefijo = "embedding_dim" if tabla == "memories" else f"{tabla}_dim"
        cols = self._rows(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND column_name LIKE %s",
            (tabla, f"{prefijo}%"))
        if not cols:
            return {"ok": False, "error": "no hay columna de respaldo que soltar"}
        nombre = cols[0]["column_name"]
        try:
            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {tabla} DROP COLUMN {nombre}")
        except Exception as exc:                                  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:
                pass
            return {"ok": False, "error": str(exc)}
        from . import audit
        audit.log(action="memoria_limpiar_respaldo", destructive=True,
                  confirmed=True, result=f"DROP COLUMN {nombre}",
                  extra={"tabla": tabla})
        return {"ok": True, "columna_eliminada": nombre}

    # --- API usada por las skills (todas toleran DB caída → devuelven []) ---
    def remember(self, content: str, kind: str = "note", tags: list | None = None, *,
                 origen: str | None = None, origen_tipo: str | None = None,
                 dominio: str | None = None, etiqueta: str | None = None,
                 peso: float | None = None) -> dict:
        """Guarda un recuerdo. Inserción IDEMPOTENTE por huella
        (memoria-deduplicacion):
          * Si `memories_huella_idx` YA existe (bloque B confirmado):
            `INSERT ... ON CONFLICT DO NOTHING RETURNING id` — sin fila
            devuelta = «ya lo sabía».
          * Si NO existe todavía (bloque A, o B sin confirmar): comprobación a
            nivel de APLICACIÓN antes de insertar. Mismo criterio, sin
            depender del índice — sustituye al `dedup` O(n) que había en
            rag.py y que solo miraba el almacén local, dejando pasar
            cualquier cosa por el camino de Postgres.
        `origen`/`origen_tipo`/`dominio`/`etiqueta`/`peso` (002-memoria-y-
        conocimiento, bloque C, C1.2/C4.1): metadatos de PROCEDENCIA. TODOS
        opcionales — si no se pasan, la columna se omite del INSERT y queda
        el DEFAULT de la tabla (dominio='sin-clasificar', peso=1.0): el SQL
        generado es BYTE A BYTE el mismo que antes de este bloque para
        cualquier llamador que no los use.
        Devuelve `{"id": int|None, "duplicado": bool}`."""
        from . import rag
        h = rag.huella(f"{kind}\n{content}")
        vec = self._embed(content)
        campos: list[tuple[str, object, str | None]] = [
            ("kind", kind, None), ("content", content, None), ("tags", tags or [], None),
        ]
        if vec is not None:
            campos.append(("embedding", str(vec), "vector"))
        campos.append(("huella", h, None))
        for col, val in (("origen", origen), ("origen_tipo", origen_tipo),
                         ("dominio", dominio), ("etiqueta", etiqueta), ("peso", peso)):
            if val is not None:
                campos.append((col, val, None))
        cols_sql = ", ".join(c for c, _, _ in campos)
        place_sql = ", ".join(f"%s::{cast}" if cast else "%s" for _, _, cast in campos)
        vals_sql = [v for _, v, _ in campos]
        if self._indice_huella_existe():
            # `memories_huella_idx` es PARCIAL (`WHERE retirado_en IS NULL`,
            # creado por B4.2): el ON CONFLICT lleva el MISMO predicado, si
            # no Postgres no puede inferir el índice y la insercion falla.
            # Efecto colateral correcto: si la única fila con esa huella
            # está retirada (papelera), esto YA NO cuenta como conflicto y
            # se inserta una fila nueva — retirar algo libera su huella.
            rows = self._rows(
                f"INSERT INTO memories ({cols_sql}) VALUES ({place_sql}) "
                "ON CONFLICT (huella) WHERE retirado_en IS NULL DO NOTHING "
                "RETURNING id", vals_sql)
            if rows:
                return {"id": rows[0]["id"], "duplicado": False}
            existe = self._rows(
                "SELECT id FROM memories WHERE huella = %s AND retirado_en IS NULL "
                "LIMIT 1", (h,))
            return {"id": existe[0]["id"] if existe else None, "duplicado": True}
        existe = self._rows(
            "SELECT id FROM memories WHERE huella = %s AND retirado_en IS NULL "
            "LIMIT 1", (h,))
        if existe:
            return {"id": existe[0]["id"], "duplicado": True}
        rows = self._rows(
            f"INSERT INTO memories ({cols_sql}) VALUES ({place_sql}) RETURNING id",
            vals_sql)
        return {"id": rows[0]["id"] if rows else None, "duplicado": False}

    def all_knowledge(self, limit: int = 300) -> list[dict]:
        """TODO lo que nexus sabe (menos el log de conversación): para AUDITAR qué
        conocimiento tiene guardado sobre el operador."""
        # AND retirado_en IS NULL (bloque B, memoria-purga «Alcance dual»):
        # TODAS las lecturas excluyen lo retirado a papelera.
        return self._rows(
            "SELECT kind, content, created_at FROM memories "
            "WHERE kind <> 'conversation' AND retirado_en IS NULL "
            "ORDER BY created_at DESC LIMIT %s", (limit,))

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Recupera CONOCIMIENTO (docs, hechos, procedimientos), NUNCA el log de
        conversación (kind='conversation'), que solo ensucia los resultados."""
        # 1) Búsqueda SEMÁNTICA si hay embeddings (encuentra por significado)
        vec = self._embed(query)
        if vec is not None:
            rows = self._rows(
                "SELECT kind, content, created_at, peso, "
                "1 - (embedding <=> %s::vector) AS score FROM memories "
                "WHERE embedding IS NOT NULL AND kind <> 'conversation' "
                "AND retirado_en IS NULL "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (str(vec), str(vec), limit * 3),
            )
            # 002-memoria-y-conocimiento (bloque C, decisión de diseño 6):
            # score * peso ANTES del umbral -- un documento etiquetado
            # 'historico' (peso 0.6) nunca gana al definitivo aunque hablen
            # de lo mismo, y puede quedar por debajo del umbral aunque su
            # score en bruto lo hubiera pasado.
            for r in rows:
                r["score"] = r.get("score", 0) * (r.get("peso") or 1.0)
            rows = [r for r in rows if r.get("score", 0) > 0.35]
            if rows:
                rows.sort(key=lambda r: r["score"], reverse=True)
                return rows[:limit]
        # 2) Fallback por SOLAPE de palabras (sin conversación), rankeado.
        # 002-memoria-y-conocimiento (bloque C): mismo criterio peso que el
        # camino vectorial de arriba -- sin proveedor de embeddings local
        # disponible, recall() sigue sin dejar que un documento 'historico'
        # gane al 'normal' hablando de lo mismo.
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2] or [query.lower()]
        clauses = " OR ".join(["content ILIKE %s"] * len(words))
        params = [f"%{w}%" for w in words]
        rows = self._rows(
            f"SELECT kind, content, created_at, peso FROM memories "
            f"WHERE kind <> 'conversation' AND retirado_en IS NULL AND ({clauses}) "
            f"ORDER BY created_at DESC LIMIT 80",
            params,
        )
        rows.sort(key=lambda r: sum(1 for w in words if w in r["content"].lower())
                  * (r.get("peso") or 1.0), reverse=True)
        return rows[:limit]

    def add_reminder(self, title: str, due_at: dt.datetime) -> list[dict]:
        """Recordatorios ESCALONADOS: 1 semana antes, 2 días antes y al vencer."""
        offsets = [dt.timedelta(days=7), dt.timedelta(days=2), dt.timedelta(0)]
        created = []
        now = dt.datetime.now(dt.timezone.utc)
        for off in offsets:
            notify = due_at - off
            if notify >= now - dt.timedelta(minutes=1):
                created += self._rows(
                    "INSERT INTO reminders (task_title, due_at, notify_at) "
                    "VALUES (%s,%s,%s) RETURNING id, notify_at",
                    (title, due_at, notify),
                )
        return created

    def due_reminders(self) -> list[dict]:
        rows = self._rows(
            "SELECT id, task_title, due_at FROM reminders "
            "WHERE NOT fired AND notify_at <= now() ORDER BY notify_at"
        )
        for r in rows:
            self._rows("UPDATE reminders SET fired = TRUE WHERE id = %s RETURNING id", (r["id"],))
        return rows

    def save_goal(self, title: str, steps: list[str]) -> int | None:
        rows = self._rows("INSERT INTO goals (title) VALUES (%s) RETURNING id", (title,))
        if not rows:
            return None
        gid = rows[0]["id"]
        for i, step in enumerate(steps):
            self._rows(
                "INSERT INTO goal_steps (goal_id, position, title) VALUES (%s,%s,%s) RETURNING id",
                (gid, i, step),
            )
        return gid

    def goals(self) -> list[dict]:
        return self._rows(
            "SELECT g.id, g.title, g.status, "
            "count(s.id) FILTER (WHERE s.done) AS hechos, count(s.id) AS total "
            "FROM goals g LEFT JOIN goal_steps s ON s.goal_id = g.id "
            "WHERE g.status = 'active' GROUP BY g.id ORDER BY g.id DESC LIMIT 10"
        )

    def save_invoice(self, client: str, concept: str, amount: float) -> dict | None:
        cid = self._rows(
            "INSERT INTO clients (name) VALUES (%s) "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
            (client,),
        )
        if not cid:
            return None
        num = self._rows("SELECT count(*) + 1 AS n FROM invoices")[0]["n"]
        number = f"WBK-{dt.date.today().year}-{num:04d}"
        rows = self._rows(
            "INSERT INTO invoices (client_id, number, concept, amount) "
            "VALUES (%s,%s,%s,%s) RETURNING number, amount",
            (cid[0]["id"], number, concept, amount),
        )
        return rows[0] if rows else None


graph = NoteGraph()
pg = PgMemory()


def memory_status() -> dict:
    return {
        "graph_notes": len(list(MEMORY_DIR.rglob("*.md"))),
        "db_online": pg.online,
        "backend": "postgres+grafo" if pg.online else "grafo (archivos)",
    }


def estado_memoria() -> dict:
    """Foto de solo lectura para `GET /api/memoria/estado`. NUNCA llama al
    proveedor de embeddings (eso es `detectar_dimension()`, bajo demanda) —
    solo lee la columna (catálogo, barato) y el estado ya medido en disco.
    Dice CON TODAS LAS LETRAS cuando la inserción idempotente no está activa
    todavía (diseño §4, «orden obligado»): no es un bug, es el estado
    intermedio esperado del bloque A."""
    if not pg.online:
        return {"db_online": False}
    columna = pg._dimension_columna()
    medido = _leer_estado_embeddings()
    indice_huella = pg._indice_huella_existe()
    dups = pg.duplicados_exactos() if indice_huella is False else []
    n_dup_filas = sum(g["total"] - 1 for g in dups)
    if indice_huella:
        mensaje_huella = "inserción idempotente activa."
    elif n_dup_filas:
        mensaje_huella = (
            f"la inserción idempotente NO está activa todavía: quedan "
            f"{n_dup_filas} fila(s) duplicada(s) por revisar en el bloque B.")
    else:
        mensaje_huella = (
            "la inserción idempotente NO está activa todavía (índice único "
            "pendiente del bloque B), pero por ahora no hay duplicados exactos.")
    return {
        "db_online": True,
        "columna_dim": columna,
        "modelo_medido": medido,
        "reindexado_pendiente": bool(
            medido and columna and medido.get("dimension") != columna),
        "descartes_por_dimension": pg.descartes_por_dimension,
        "indice_huella_activo": indice_huella,
        "duplicados_exactos_grupos": len(dups),
        "duplicados_exactos_filas_sobrantes": n_dup_filas,
        "mensaje_huella": mensaje_huella,
    }
