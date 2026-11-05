# Security audit remediation

Remediate every finding of the integral audit in `audit-reports/` (P0 → P1 → P2 → P3), one reviewable work-unit commit per task.
Branch `fix/security-audit-remediation`, cut from `main` @ `908924b`. It does not include `fix/security-workflow-actions` (stale, 1 commit) or the untracked `odd/tasks/youtube-verification.md`, which belongs to another feature.
Source of truth for each finding: `audit-reports/03-security-findings.md`, `05-ai-llm-rag-audit.md`, `06-data-privacy-governance.md`, `08-devsecops-testing.md`. Acceptance rows: `audit-reports/09-remediation-roadmap.md`.

## Specs

- **S1** — Version the audit: "Si versiona"
- **S2** — Order: "empieza por P0 y luego P1"
- **S3** — Scope covers every severity: "en verdad creo qeu toda la severidad es importante y ya que estamos, deberiamos de atacarlo"
- **S4** — Isolate the work on its own branch: "Revisa tambien en la rama donde estamos trabajando, para que no se mezcle con otros fixes"
- **S5** — Each task satisfies the "Prueba de aceptación" / "Aceptación" column of its roadmap row in `audit-reports/09-remediation-roadmap.md` (the user authorized implementing that roadmap: "autorizo a implementar").

## Tasks

| ID | Specs | Roadmap / finding | Route | Risk | Commit |
|----|-------|-------------------|-------|------|--------|
| T0 | S1, S4 | Version `audit-reports/` and this document | inline | none | — |
| T1 | S2 | P0-1/P0-2: n8n webhook and Telegram owner checks (operational, owner-side) — [x] closed by L3+L4 | inline | — | n/a |
| T2 | S2, S5 | P1-1 / SEC-01 (+ the n8n part of SEC-06): `/api/n8n` shared secret, untrusted-channel intent allowlist, authenticated example flow | worker | item 2 | — |
| T3 | S2, S5 | P1-2 / SEC-02: Telegram one-time link code | worker | item 2 | — |
| T4 | S2, S5 | P1-3 / SEC-03: HTTP Host/Origin validation for loopback trust; no token in `/api/link/status` | worker | item 2 | — |
| T5 | S2, S5 | P1-4 / SEC-05: confirmation + idempotency for `send_email` and `whatsapp` | worker | item 3 | — |
| T6 | S2, S5 | P1-5 / AI-01, AI-02: cloud fallback only with consent; redact interactions, audit and distill | worker | item 2 | — |
| T7 | S2, S5 | P1-6 / SEC-04, SEC-12: safe `perm_files` default, fixed denylist, permission changes only from the local window | worker | item 2 | — |
| T8 | S3, S5 | P2-1 / ARQ-01, ARQ-03: central channel × effect policy in `brain` | worker | item 2 | — |
| T9 | S3, S5 | P2-2 / SEC-06, AI-04: opmem rules need confirmation and record their origin; Engram content is read as data | worker | item 2 | — |
| T10 | S3, S5 | P2-3 / SEC-07: email triage proposes actions and waits for approval | worker | item 3 | — |
| T11 | S3, S5 | P2-4 / AI-03: delimit untrusted content in prompts | worker | item 6 | — |
| T12 | S3, S5 | P2-5 / SEC-08: Android network config, bridge restriction, native confirmation | worker | item 5 | — |
| T13 | S3, S5 | P2-6 / SEC-09: DPAPI/keyring for secrets and OAuth tokens; fix `CLAUDE.md` | worker | item 1 | — |
| T14 | S3, S5 | P2-7: CI runs tests, lockfile with hashes, actions pinned by SHA | worker | item 5 | — |
| T15 | S3, S5 | P2-8 / PRIV-03: complete deletion across every store | worker | item 1 | — |
| T16 | S3, S5 | P2-9 / ARQ-05: atomic JSON writes (board, jobs, contentos, proactive) | worker | none | — |
| T17 | S3, S5 | P2-10: tested backup restore | worker | item 1 | — |
| T18 | S3, S5 | P2-11 / SEC-10: `esc()` quotes, CSP, `frame-ancestors` | worker | item 2 | — |
| T19 | S3, S5 | P2-12 / AI-07: `max_tokens`/`num_predict`, daily per-provider cap | worker | none | — |
| T20 | S3, S5 | P3-1 / SEC-11: `safe_fetch` for URLs from untrusted channels | worker | item 2 | — |
| T21 | S3, S5 | P3-2: per-device tokens with individual revocation | worker | item 2 | — |
| T22 | S3, S5 | P3-3 / ARQ-02: split `app.py` into routers | worker | item 3 | — |
| T23 | S3, S5 | P3-4 / ARQ-04: explicit routing priority | worker | item 3 | — |
| T24 | S3, S5 | P3-5 / SEC-13..16: Gemini header, Spotify `state`, `games` `isdigit`, generic errors | worker | item 2 | — |
| T25 | S3, S5 | P3-6: Hermes without automatic retry on side effects; confirm delegation | worker | item 6 | — |
| T26 | S3, S5 | P3-7 / SEC-18: MCP tool allowlist | worker | item 2 | — |
| T27 | S3 | P3-8: installer code signing (needs a certificate: owner decision) | — | item 5 | — |
| T28 | S3, S5 | P3-9 / ARQ-08: versioned schema migrations | worker | item 1 | — |
| T29 | S3 | P3-10 / SEC-17: rotate the Postgres password if an install uses the historical literal (operational, owner-side) | — | item 1 | — |

**Boundary tests** (P2-13) live with each task, never as a separate unit.

**Forecast**:

- P1: about 900 authored changed lines.
- P2 + P3: more than 3000.

Commits stay on this branch. Push, PR and merge are the owner's decisions.

## Log

- **L1** (user, verbatim): "Si versiona y autorizo a implementar. empieza por P0 y luego P1, en verdad creo qeu toda la severidad es importante y ya que estamos, deberiamos de atacarlo. Revisa tambien en la rama donde estamos trabajando, para que no se mezcle con otros fixes"
- **L2** (evidence, branch): `fix/youtube-verification` == `main` == `origin/main` @ `908924b` (0 commits ahead). Every other local branch is merged into `main`, except `fix/security-workflow-actions`: 1 stale commit touching only `.github/workflows/security-ci.yml`, based on an older workflow. This branch was cut from `main`. T14 owns the CI changes here, so they do not mix with that stale branch.
- **L3** (evidence, P0, read as booleans only, no values printed):
  - A Telegram bot token is configured and `data/telegram_owner.txt` exists, so an owner is registered. Only the owner can confirm it is their chat.
  - `n8n_base_url` and `n8n_webhook_url` are set in `settings.json`.
  - No n8n process is listening on `:5678` right now. Whether the example flow is imported is known only to the owner.
  - `settings.json` stores `perm_files: "todo"`.
  - `config/mcp_servers.json` does not exist (MCP is off).
- **L4** (user answers):
  - Delivery: "Cadena verificada contra main". So `chain_strategy=stacked-to-main`; default branch verified as `origin/HEAD -> origin/main`.
  - Telegram: "Sí, es mi chat". Keep the registered owner; only new registrations require the link code.
  - n8n: "No / no lo uso". No active exposure, so P0-1 closes without action; T2 still applies.
  - perm_files: "Cual crees que es mejor?". The recommendation is to migrate to `carpetas`. The owner has not yet authorized touching `settings.json`; ask again at T7.
