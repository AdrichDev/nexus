# Secret redaction on memory writes

Goal: a secret typed or pasted into Nexus (API key, token, password, private key, URL credentials) is never persisted in clear text in any memory store, because stored memory is later injected into agent/LLM context.
Decision (owner): per-user isolation is NOT needed (each install has one user and its own memory/embeddings). Only redaction is in scope.
Design: one module `backend/core/comun/secretos.py` with `redactar(texto) -> (texto, n)`; replace only the secret value with `[SECRETO-OCULTO]`; idempotent; documentation placeholders (`user:pass@host`, `password: ****`) and ordinary prose ("la clave es importante") are not touched. Applied at the write choke points; ingestion redacts before comparing chunks so overwrite-by-source stays stable.

## Tasks
- [x] T1 `secretos.redactar` module with tests (secrets redacted, placeholders/prose kept, idempotent, counted).
- [x] T2 Apply at write points: `pg.remember`, `rag.add` (local fallback too), `opmem.remember`, Engram `save`, graph `write_note`/`append_daily`; ingestion redacts before overwrite comparison.
- [x] T3 User-visible notice: explicit "recuerda ..." tells the user a secret was not stored.
- [ ] T4 Review, merge to main, update docs.

## Evidence
- T1: `backend/core/comun/secretos.py` + `tests/unit/core/test_secretos.py` (RED = module missing -> GREEN 51/0); registered in run_all/runner_profiles (runner profiles 490/0).
(append commits and checks here)
- T2: redaction applied in `pg.remember`, `rag.add` (Postgres and local store), `opmem.remember`, Engram `save` (title+content), `graph.write_note`/`append_daily`; ingestion redacts `texto` (mirror + chunks) and each chunk (covers `.xlsx`) so overwrite-by-source stays stable. `tests/unit/memory/test_redaccion_memoria.py` RED 10/10 -> GREEN; ingestion tests RED 2 then 1 -> GREEN 101/0.
- T3: explicit `recuerda ...` redacts before storing/echoing and appends a notice ("He ocultado un secreto: no guardo claves ni contraseñas en la memoria."); RED 3 -> GREEN, redaccion suite 14/0.
- Layer registry: `secretos` classified in `comun` (`test_capas_backend` 449/0, `backend/core/CAPAS.md`).
- Live check on the real DB (marker row, deleted afterwards): stored `password=[SECRETO-OCULTO]`; table unchanged 1770/1431.
- Other suites green: engram 124, hermes_engram 57, memory_graph 61, specs_v23_mem 58, v21_fixes 26, frases_reales 212, hermes 202, tools 92, pequenas_2 89, purga 76, runner profiles 495.
- Not covered (open): raw user text is still written to logs (`bus` log lines in `brain.process`), `selflearn` `interactions.jsonl`, in-memory `_history` and Hermes/other external agents' own stores; detection is pattern-based (false negatives possible); secrets stored BEFORE this change are not rewritten (live scan earlier found none).
