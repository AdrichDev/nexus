"""P1-07 persistence probe. Run only inside the hermetic container with a DISPOSABLE Postgres.

Usage: probe_persistence.py write | read | purge
Requires NEXUS_DB_URL pointing at the throwaway database and NEXUS_DATA_DIR at a temp dir.
Phase `write` stores data; the orchestrator restarts the Postgres container; `read` checks
it survived with a fresh process; `purge` checks reversible retirement and restore.
No Ollama is reachable, so embeddings are absent and recall uses the keyword fallback.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
assert os.environ.get("NEXUS_DB_URL", "").startswith("postgresql://nexus_probe"), "refusing: not the probe DB"
os.environ.setdefault("NEXUS_DATA_DIR", "/tmp/nexus_data")

from backend.core.dominio.memory import PgMemory  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def check(cond: bool, msg: str) -> None:
    RESULTS.append((bool(cond), msg))
    print(("  OK  " if cond else "  FAIL ") + msg)


def contents(rows):
    return [r["content"] for r in rows]


def phase_write() -> None:
    pg = PgMemory()
    check(pg.online, "fresh database: connects and creates its own schema")
    a = pg.remember("El cliente Zeta paga a 30 dias", kind="fact")
    b = pg.remember("La clave del router es solo de prueba", kind="fact")
    c = pg.remember("El cliente Zeta paga a 30 dias", kind="fact")
    check(a["id"] and not a["duplicado"], "first fact stored")
    check(c["duplicado"] and c["id"] == a["id"], "identical fact is deduplicated, same id")
    check(pg.recall("cliente Zeta"), "recall finds the stored fact before restart")
    pg.add_reminder("Factura Zeta", dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10))
    gid = pg.save_goal("Cerrar trimestre", ["revisar facturas", "enviar informe"])
    check(gid is not None, "goal with steps stored")
    inv = pg.save_invoice("Zeta", "Consultoria", 120.5)
    check(inv is not None, "invoice stored")


def phase_read() -> None:
    pg = PgMemory()
    check(pg.online, "after Postgres restart: new process reconnects")
    rows = pg.recall("cliente Zeta")
    check(any("Zeta paga a 30 dias" in x for x in contents(rows)), "fact survived the restart")
    n = len(pg._rows("SELECT id FROM memories WHERE content ILIKE %s", ("%Zeta paga%",)))
    check(n == 1, f"deduplicated fact is still ONE row (found {n})")
    g = pg.goals()
    check(g and g[0]["total"] == 2, "goal and its 2 steps survived")
    r = pg._rows("SELECT id FROM reminders")
    check(len(r) >= 1, f"reminders survived ({len(r)} rows)")
    inv = pg._rows("SELECT amount FROM invoices")
    check(inv and float(inv[0]["amount"]) == 120.5, "invoice amount exact")
    # schema is idempotent: a second connect does not wipe anything
    pg2 = PgMemory()
    check(pg2.online and pg2.recall("cliente Zeta"), "second connection re-runs DDL without data loss")


def phase_purge() -> None:
    pg = PgMemory()
    ids = [x["id"] for x in pg._rows("SELECT id FROM memories WHERE content ILIKE %s", ("%router%",))]
    check(len(ids) == 1, "target row found")
    check(pg.retirar_filas(ids, "lote-probe") == 1, "retire = UPDATE of 1 row")
    check(not [x for x in contents(pg.recall("router")) if "router" in x], "retired row no longer recalled")
    still = pg._rows("SELECT id, retirado_en FROM memories WHERE id = ANY(%s)", (ids,))
    check(len(still) == 1 and still[0]["retirado_en"] is not None, "row still on disk (not deleted), marked retired")
    again = pg.remember("La clave del router es solo de prueba", kind="fact")
    check(not again["duplicado"], "retiring frees the fingerprint (re-saving makes a new row)")
    check(pg.restaurar_filas("lote-probe") == 1, "restore the batch = UPDATE back")
    check(len(pg._rows("SELECT id FROM memories WHERE retirado_en IS NOT NULL")) == 0, "nothing left retired")


if __name__ == "__main__":
    {"write": phase_write, "read": phase_read, "purge": phase_purge}[sys.argv[1]]()
    bad = [m for ok, m in RESULTS if not ok]
    print(f"\nP1-07 {sys.argv[1]}: {len(RESULTS)-len(bad)} OK, {len(bad)} FAIL")
    sys.exit(1 if bad else 0)
