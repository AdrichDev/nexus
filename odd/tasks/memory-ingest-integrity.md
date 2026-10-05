# Memory ingestion integrity

Goal: knowledge that Nexus ingests from folders is safe, unambiguous and never duplicated or stale.
Decision (owner + agent): documents are OVERWRITTEN per source (`origen`): when a file changes, its old chunks are retired to the trash (`retirado_en`/`retirado_lote`, reversible) and the new chunks are stored; files deleted from the folder have their chunks retired. Unchanged chunks are untouched. Free-form facts ("recuerda ...") are NOT overwritten blindly (no stable key); correction learning keeps its explicit user confirmation.

## Tasks
- [x] T1 Read-only scan of already stored memory (`memories` rows + `data/memory/documentos/`) for secret-like content; report masked counts/ids/paths; retire only with owner confirmation via the existing purge/trash flow.
- [x] T2 Mirror filename collisions: mirror name must be unique per source file (relative path + extension).
- [x] T3 Offline Postgres: ingestion must fail loudly (ok=false) and write nothing, not report success.
- [x] T4 Per-file permission/containment check: resolved file must be inside the allowed base (symlink escape) else skipped with a reason.
- [x] T5 Overwrite by source: retire stale chunks of a changed file and of files deleted from the folder; report retired counts; reversible.

## Evidence
- T1 (read-only, masked): 1770 `memories` rows + `data/memory`, `data/rag`, `engram_ops.json` scanned with 9 secret patterns. 3 DB rows (79, 141 retired, 2302) and `memory/daily/2026-07-18.md` matched only the documentation placeholder `postgresql://user:pass@host/db` (false positive). No real secrets found; nothing to purge. Heuristic only.
- T2-T5 (one coupled change in `ingerir_carpeta`): mirror name = full relative path + extension; Postgres offline returns ok=false and writes nothing; per-file resolved-path containment (`omitido: fuera_de_la_carpeta`); overwrite by source: new chunks stored first, then stale chunks of changed/deleted/now-secret files retired with an `ingesta-<UTC>-<dominio>` lote (reversible with `restaurar_filas(lote)`); a file that exists but cannot be read keeps its stored chunks; chunks still present in any file of the run are never retired. New read-only `pg.filas_documento_bajo(prefijo)` (SQL verified read-only against the live DB: 70 rows for a real prefix, 0 for a non-match).
- Checks: `test_ingesta_documentos.py` RED 13 failures -> GREEN 85/0 locally and 86/0 in the Linux hermetic container (symlink test runs there); purga 76/0, graph 61/0, capas_backend 436/0, runner profiles 485/0, pequenas_1 355/0, embeddings 45/0.
- Not done / limits: old-named mirrors (`<stem>.md`) from earlier ingestions stay as orphans; mirrors of deleted sources are kept (they may be the only copy); local `data/rag/knowledge.jsonl` fallback is not overwritten by source; identical chunk text ingested from two different folders can lose its row when the first folder changes; free-form facts are not overwritten (no stable key); real overwrite not exercised against the live DB (no write to production).
