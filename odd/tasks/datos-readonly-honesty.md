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
- [ ] T1 SQL validator (allowlist, strips strings/comments) + engine-level read-only on SQLite/Postgres/MySQL.
- [ ] T2 SQLite connect: missing path -> clear error, never creates a file.
- [ ] T3 Honest counts: read cap vs result size in `consulta`; chart says how many rows it draws; KPI = rows read.
- [ ] T4 Honest browser: dashboards/charts only claim "abierto" when the browser opened; otherwise say where the file is.
- [ ] T5 Review, merge to main, update docs.

## Evidence
(append commits and checks here)
