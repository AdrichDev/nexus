# datos skill: real read-only guarantee and honest numbers

Found auditing the real command path in the Docker harness (SQLite fixture, no network):
- `consulta: REPLACE INTO ...` writes (count 120 -> 121); `ATTACH DATABASE` creates a file; `PRAGMA` runs. The regex denylist (`insert|update|delete|drop|truncate|alter|create|grant`) misses REPLACE/ATTACH/PRAGMA/COPY/SELECT INTO/LOAD etc. SKILL.md promises "no escribe en la base de datos".
- `SELECT 'please update me'` is rejected (false positive on a string literal).
- A typo path `sqlite:///tmp/nope.db` creates an empty DB file and replies "Conectado".
- `SELECT * FROM t` on 120 rows replies "50 filas:" (the read cap presented as the result size).
- Chart: KPI says 50 rows, the chart only draws 20 labels, nothing says so.
- Dashboards/charts say "abierto en el navegador" even when the browser did not open.

Design: defense in depth. (1) engine-level read-only: SQLite `file:...?mode=ro` + `PRAGMA query_only=ON`; Postgres `set_session(readonly=True, autocommit=True)`; MySQL `SET SESSION TRANSACTION READ ONLY`. (2) statement allowlist: one statement, first keyword in select/with/show/explain/values/table/describe, no write/side-effect keywords outside string literals and comments, no INTO.

## Tasks
- [x] T1 SQL validator (allowlist, strips strings/comments) + engine-level read-only on SQLite/Postgres/MySQL.
- [x] T2 SQLite connect: missing path -> clear error, never creates a file.
- [x] T3 Honest counts: read cap vs result size in `consulta`; chart says how many rows it draws; KPI = rows read.
- [x] T4 Honest browser: dashboards/charts only claim "abierto" when the browser opened; otherwise say where the file is.
- [ ] T5 Review, merge to main, update docs.

## Evidence
(append commits and checks here)
- T1-T4 (one coupled change in `skills/datos/skill.py`): `_validar_sql` allowlist (one statement, first keyword select/with/show/explain/values/table/describe, no write/side-effect keywords outside strings/comments, no INTO/set_config/pg_read_file/lo_*/dblink); engine-level read-only (SQLite `file:...?mode=ro` + `PRAGMA query_only`, Postgres `set_session(readonly=True, autocommit=True)`, MySQL `SET SESSION TRANSACTION READ ONLY`); SQLite missing path -> error, never creates; `consulta` says "Hay más de 50 filas" / "primeras 12"; chart title/reply say "primeras 20 de N" and KPI is "Filas leídas"; `_build_dashboard` returns (file, opened) and replies only say "abierto" when it opened.
- Checks: `test_datos_honesty.py` RED 19 failures -> GREEN 34/0; existing `test_skill_datos.py` 64/0; places 42/0; pequenas_1 355, pequenas_2 89, frases_reales 212, capas_backend 449, runner profiles 505. Postgres verified for real in a throwaway `pgvector/pgvector:pg16` container (validator and engine both block INSERT/CREATE/DELETE/COPY TO PROGRAM/SELECT INTO/set_config/DO; table intact, no tables created); container stopped.
- Not verified / open: MySQL read-only session (no server available), Mongo (pymongo not installed; its dashboard samples 100 docs without saying so and `estimated_document_count` is not exact), the LLM insight pastes the provider error text when Ollama is down, password typed in the connect command is still written raw to logs/history (pending log redaction), Postgres lists only the `public` schema.
