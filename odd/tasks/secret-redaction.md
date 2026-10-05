# Secret redaction on memory writes

Goal: a secret typed or pasted into Nexus (API key, token, password, private key, URL credentials) is never persisted in clear text in any memory store, because stored memory is later injected into agent/LLM context.
Decision (owner): per-user isolation is NOT needed (each install has one user and its own memory/embeddings). Only redaction is in scope.
Design: one module `backend/core/comun/secretos.py` with `redactar(texto) -> (texto, n)`; replace only the secret value with `[SECRETO-OCULTO]`; idempotent; documentation placeholders (`user:pass@host`, `password: ****`) and ordinary prose ("la clave es importante") are not touched. Applied at the write choke points; ingestion redacts before comparing chunks so overwrite-by-source stays stable.

## Tasks
- [ ] T1 `secretos.redactar` module with tests (secrets redacted, placeholders/prose kept, idempotent, counted).
- [ ] T2 Apply at write points: `pg.remember`, `rag.add` (local fallback too), `opmem.remember`, Engram `save`, graph `write_note`/`append_daily`; ingestion redacts before overwrite comparison.
- [ ] T3 User-visible notice: explicit "recuerda ..." tells the user a secret was not stored.
- [ ] T4 Review, merge to main, update docs.

## Evidence
(append commits and checks here)
