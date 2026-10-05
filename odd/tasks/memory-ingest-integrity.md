# Memory ingestion integrity

Goal: knowledge that Nexus ingests from folders is safe, unambiguous and never duplicated or stale.
Decision (owner + agent): documents are OVERWRITTEN per source (`origen`): when a file changes, its old chunks are retired to the trash (`retirado_en`/`retirado_lote`, reversible) and the new chunks are stored; files deleted from the folder have their chunks retired. Unchanged chunks are untouched. Free-form facts ("recuerda ...") are NOT overwritten blindly (no stable key); correction learning keeps its explicit user confirmation.

## Tasks
- [ ] T1 Read-only scan of already stored memory (`memories` rows + `data/memory/documentos/`) for secret-like content; report masked counts/ids/paths; retire only with owner confirmation via the existing purge/trash flow.
- [ ] T2 Mirror filename collisions: mirror name must be unique per source file (relative path + extension).
- [ ] T3 Offline Postgres: ingestion must fail loudly (ok=false) and write nothing, not report success.
- [ ] T4 Per-file permission/containment check: resolved file must be inside the allowed base (symlink escape) else skipped with a reason.
- [ ] T5 Overwrite by source: retire stale chunks of a changed file and of files deleted from the folder; report retired counts; reversible.

## Evidence
(append commits and checks here)
