# Nexus pending work

Last updated: 2026-10-05 after delivering `research-correction-learning` to `main` at `f742d44ef57b860803998169fd4e7a2880667d45`.

## Recently closed
- `clima` unknown-city reply delivered on `main` at `4e78065`: Nexus now says plainly that a locality does not exist (control-city check), native review approved twice. Follow-up closed: only HTTP 404/500 on the city request can produce the "does not exist" verdict; 429/502/503/504 ask to retry.
- `research-correction-learning` is delivered on `main`.
  - R1: preserved research query dates and rejected consent/interstitial evidence.
  - R2: wrong-answer feedback now re-researches with source-backed contrast and does not learn complaints as facts.
  - R3: focused deterministic checks and safe live probes completed.
  - CI `seguridad` run `37299363982` passed.

## Memory/knowledge audit (2026-10-05)
- Audit findings saved in Engram `odd/memory-knowledge-audit`. Done: folder ingestion now skips secret-looking files (`.env`, SSH keys, `credentials`/`secrets`/`token(s)`/`password(s)`/`api_key(s)` names, `.pem/.key/...`, private-key content) and reports each as `omitido: secreto`.
- Done 2026-10-05 (feature `odd/tasks/memory-ingest-integrity.md`): read-only scan of stored memory found no real secrets (only a doc placeholder); folder ingestion now overwrites by source (stale chunks of changed/deleted/now-secret files are retired to the trash with a reversible `ingesta-<UTC>-<dominio>-<id>` lote), mirrors are unique per file, Postgres offline fails loudly, per-file containment (symlinks), unreadable-but-present files and unconfirmed saves never retire old chunks, empty/inaccessible folder retires nothing.
- Done 2026-10-05 (feature `odd/tasks/secret-redaction.md`): secrets are redacted (`backend/core/comun/secretos.py`, marker `[SECRETO-OCULTO]`) at every memory write point (Postgres, RAG incl. local store, operational memory, Engram, notes, folder ingestion incl. xlsx) and an explicit "recuerda ..." tells the user a secret was hidden. Owner decision: per-user isolation not needed (one user per install).
- Open after redaction: raw user text is still written to logs (`bus` log lines in `brain.process`), `selflearn` `interactions.jsonl`, in-memory `_history`, and external agents' own stores; detection is pattern based (false negatives possible); native review advisory on `secretos.py:64-68` (WARNING, detail not provided) and three suggestions (`secretos.py:84`, `memory.py:208`, `brain.py:1013-1015`).
- Open (review advisories, non-blocking): identical chunk text in two folders is one row owned by the first origin; partial-tree walk errors could retire valid rows; `eliminado` entries are also used for rows whose file vanished vs failed; old-named mirrors (`<stem>.md`) are orphans; local `data/rag/knowledge.jsonl` is not overwritten by source; real overwrite not exercised against the live DB; free-form facts have no stable key; no secret redaction in `remember` paths; global (non-per-user) stores; Engram HTTP without token; pending corrections lost on restart; secret-name regex false negatives/positives.

- Skill audit `places` (2026-10-05, real command path in the Docker harness, no browser available): reproduced and fixed on `fix/places-honesty` — replies claimed "abierto/lista" when `webbrowser.open` returned False (now: honest failure + the link), "90 dólares" was answered as "90 €" (currency now captured; `curr=USD`/`EUR`), "cuánto se tarda de A a B" was answered as a plain route (now says it cannot compute the duration), and "hablemos de viajes a la luna" opened Google Flights (bare «viajes/vuelos a» now only at sentence start or after dame/ponme/muéstrame/enséñame). `places` itself never reads Google results, as its SKILL.md says.

- Skill audit `datos` (2026-10-05, Docker harness + SQLite fixture, Postgres in a throwaway container): the "no escribe en la base de datos" promise was false (`REPLACE INTO` wrote, `ATTACH` created files, `PRAGMA` ran), a string with the word "update" was rejected, a typo path created an empty DB, a 120-row table answered "50 filas", the chart drew 20 of 50 rows without saying so and dashboards claimed "abierto" without opening. Fixed on `fix/datos-readonly-honesty` (see `odd/tasks/datos-readonly-honesty.md`).

## Carry-forward annotations
- Google browser search works in the last safe live run, but it can still CAPTCHA later; Nexus must degrade honestly when blocked.
- Chrome search runs as an off-screen browser inside the server process; two processes cannot share the same Google browser profile.
- Correction evidence must not treat a plausible model answer, a URL alone, or a weak quote as PASS.
- Corrections must not persist without explicit user confirmation.
- Historical Moon probe had usable but mixed-quality evidence; INE unemployment and Smithsonian Apollo probes were stronger.
- Known flaky check remains `test_inbox_scale` timing threshold under full battery.
- `rtk` is not available in this shell; use raw commands unless installed later.
- Optional cleanup: delete the merged branch `fix/research-correction-learning` locally/remotely when convenient.

## Improvement backlog (not the main work queue)

These are non-blocking review/advisory items. Do not treat them as the next product tasks unless explicitly selected.
- `R3-live-checkout-flag-unenforced`: `tests/runner_profiles.py:65-71` records live-checkout safety as metadata only; future improvement can add stronger enforcement where useful.
- `R3-parity-guard-not-in-battery`: `tests/run_all.py:30-32` exposes runner-profile loading, but the parity guard lives in a focused test and is not yet part of a regular safe battery.
- Browser-flow profile inventory: this means labeling the nine browser E2E flows by what they actually prove and what they depend on; it is documentation/evidence hygiene, not a feature by itself.

## Main work queue

The actual queue is not the review-advisory backlog above. The main work is these three lanes, with the same standard for all of them: a CU or skill counts only when it actually works under observed evidence, not because a mock, queue, README, or provider claim says so.

### 1. Gmail / tasks real workflow
Source: `odd/tasks/inbox-task-kpi.md`.
- Continue T5c/T9 real Gmail path.
- Last real run: read-only Gmail dry run classified 13/13 unread mails and found 9 actionable, 4 urgent; later run created local board tasks and marked selected mails read.
- Open issue: Google Tasks API was disabled in the GCP project (`accessNotConfigured`), so actual Google Tasks delivery is not proven.
- Next proof boundary: explicit sandbox/API setup, then observe real delivery or a correctly classified failure. No real-account write without scoped approval.

### 2. Broader skill audit / capabilities
Source: `odd/tasks/hermes-empty-response.md` and current audit history.
- Continue isolated public-web/weather/research probes and other skill capability checks.
- Generic routing/research still needs connector controls before broad live execution.
- External/device/provider claims must remain separated from mocked or handler-only evidence.
- Clima proof started 2026-10-05: direct handler call for explicit city `Sevilla` reached `https://wttr.in/Sevilla?format=j1&lang=es` with HTTP 200 and parsed concrete fields (`temp_C=28`, `FeelsLikeC=28`, `humidity=41`, `windspeedKmph=20`, `maxtempC=29`, `mintempC=20`, `desc=Cubierto de nubes`). The skill reply matched those fields. Madrid is not counted as proof because the first probe lost captured output to Windows encoding. This proves the direct skill path for one public city, not full Nexus routing/UI.
  - Command-path proof 2026-10-05: clean `git archive HEAD` copy in a Docker container (read-only root, bridge network, no `.env`/data), real uvicorn backend, `POST /api/command`. `que tiempo hace en Sevilla` -> skill `clima`, provider `minion:clima`, reply matched wttr fields (28°C, humedad 41%, viento 20 km/h, max 29/min 20); `clima en Madrid hoy` -> same path, 23°C, humedad 51%, lluvia localizada. Level I (live public wttr.in, no mocks). Not proven: HUD/browser UI render, voice, spoken output.
  - Failure-path proof 2026-10-05 (same container harness): no-city `que tiempo hace` -> Madrid by IP with an honest note (works). Network down (`--network none`) -> honest `No llego a wttr.in (ConnectError)` message for all three (works). **Defect reproduced:** unknown city `clima en Ciudadinexistentexyz` with network up returns the same `No llego a wttr.in ... Suele ser cosa de red` (HTTPStatusError), blaming the network instead of saying the city was not found. Deceptive-reply class (P2-10); fixed on branch `fix/clima-unknown-city`: on a wttr.in HTTP error with an explicit city, the skill makes one control request (Madrid); if the service answers, Nexus tells the user plainly that the locality does not exist (no provider/network jargon); if the control also fails, it reports a provider error without claiming anything about the city. Live wttr.in returns HTTP 500 (not 404) for unknown cities.

### 3. CU verification: prove Nexus really works
Source: `odd/tasks/verify-nexus-use-cases.md`.
- Continue proving customer/user journeys end-to-end by evidence level: S/M/I/P/F.
- P0-03: startup/core journey is verified in isolated container; real desktop/provider paths remain open.
- P1-08: external integrations need separate contract/sandbox verification.
- P1-09: local PC/media/voice workflows need controlled verification.
- P2-10: information/product claims need provenance audit.
- P2-11: CU evidence ledger needs continued publication/maintenance.

## Recommended next slice
Resume the real-work queue by picking the next smallest proof boundary from the three lanes above. Prefer work that proves an actual user-visible CU works, or records precisely why it does not, without turning unverified mocks/provider claims into delivery evidence.
