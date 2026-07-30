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
import os
import re
from pathlib import Path

from .config import DATA_DIR, settings

try:
    import psycopg2
    import psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

MEMORY_DIR = DATA_DIR / "memory"
DAILY_DIR = MEMORY_DIR / "daily"
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


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
        # índice de similitud (acelera recall semántico); ignora si no hay pgvector
        ("CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories "
         "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"),
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
        self._schema_ready = True
        try:
            from .events import bus
            bus.emit_sync("log", {"level": "ok", "msg": "🧠 Memoria Postgres lista (esquema verificado)."})
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

    # --- Embeddings (RAG auto-aprendiente) -------------------------------
    # Cada recuerdo se vectoriza con Ollama (nomic-embed-text) si está
    # disponible; recall() busca entonces por SIGNIFICADO (coseno pgvector),
    # no solo por palabra exacta. Así nexus aprende de cada conversación.
    def _embed(self, text: str) -> list[float] | None:
        # Usa EL MODELO QUE HAYA (Ollama / OpenAI / Gemini) vía rag._embed_sync, no
        # solo Ollama. La columna pgvector suele ser de 768: si el modelo da otra
        # dimensión, devolvemos None y se guarda sin vector (recuperable por texto).
        try:
            from . import rag
            vec = rag._embed_sync(text)
            return vec if vec and len(vec) == 768 else None
        except Exception:
            return None

    # --- API usada por las skills (todas toleran DB caída → devuelven []) ---
    def remember(self, content: str, kind: str = "note", tags: list | None = None):
        vec = self._embed(content)
        if vec is not None:
            self._rows(
                "INSERT INTO memories (kind, content, tags, embedding) "
                "VALUES (%s,%s,%s,%s::vector) RETURNING id",
                (kind, content, tags or [], str(vec)),
            )
        else:
            self._rows(
                "INSERT INTO memories (kind, content, tags) VALUES (%s,%s,%s) RETURNING id",
                (kind, content, tags or []),
            )

    def all_knowledge(self, limit: int = 300) -> list[dict]:
        """TODO lo que nexus sabe (menos el log de conversación): para AUDITAR qué
        conocimiento tiene guardado sobre el operador."""
        return self._rows(
            "SELECT kind, content, created_at FROM memories "
            "WHERE kind <> 'conversation' ORDER BY created_at DESC LIMIT %s", (limit,))

    def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Recupera CONOCIMIENTO (docs, hechos, procedimientos), NUNCA el log de
        conversación (kind='conversation'), que solo ensucia los resultados."""
        # 1) Búsqueda SEMÁNTICA si hay embeddings (encuentra por significado)
        vec = self._embed(query)
        if vec is not None:
            rows = self._rows(
                "SELECT kind, content, created_at, "
                "1 - (embedding <=> %s::vector) AS score FROM memories "
                "WHERE embedding IS NOT NULL AND kind <> 'conversation' "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (str(vec), str(vec), limit * 3),
            )
            rows = [r for r in rows if r.get("score", 0) > 0.35]
            if rows:
                return rows[:limit]
        # 2) Fallback por SOLAPE de palabras (sin conversación), rankeado
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2] or [query.lower()]
        clauses = " OR ".join(["content ILIKE %s"] * len(words))
        params = [f"%{w}%" for w in words]
        rows = self._rows(
            f"SELECT kind, content, created_at FROM memories "
            f"WHERE kind <> 'conversation' AND ({clauses}) "
            f"ORDER BY created_at DESC LIMIT 80",
            params,
        )
        rows.sort(key=lambda r: sum(1 for w in words if w in r["content"].lower()), reverse=True)
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
