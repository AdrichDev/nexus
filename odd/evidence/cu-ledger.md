# Nexus use-case evidence ledger

Verified at commit `9904803` (main), 2026-10-04. Evidence levels: **S** source exists, **M** mocked behavior passed, **I** real isolated process/HTTP/WS/browser in a no-network container, **P** provider acknowledged, **F** physical effect observed, **R** owner report. A level not listed for a family has NOT been proven.

## Commands run on this commit (clean `git archive HEAD`, `--network none`, read-only root)
| Check | Result |
|---|---|
| `tests/hermetic/run.sh` (`run_all.py`, 89 suites) | exit 0, all green, pass counts identical to pre-relocation baseline |
| `probe_startup.py` | 11 OK / 0 FAIL: 32/32 skills load, `2 mas 2` → `= 4` via `tools`, WS boot frames, foreign Origin refused (403), SIGTERM/restart/WS reconnect |
| `probe_user_journeys.py` | 20 OK / 0 FAIL, 0 findings: tasks created/moved/deleted/restored via HUD and chat; files created/versioned/restored; sandbox refusal |
| `tests/e2e/run_e2e.py` | 9/9 flows passed (synthetic jobs/analytics fixtures) |

## Classification
| Family | Works (evidence) | Not proven / known limits |
|---|---|---|
| Startup, HUD, commands, routing | Works: I (startup, command round-trip, WS, restart) + M (routing suites) | LLM/provider failure behavior; desktop window |
| Tasks board | Works: I (HUD create/move/delete/restore, stale-view defect fixed in 4b3a063) | drag-and-drop, in-place edit, other permission modes |
| Files and versions | Works: I (create/update/versions/restore, sandbox refusal) | real OS trash; `crea el archivo /ruta/x.md` mangles absolute paths (use `x.md en /ruta`) |
| Inbox → tasks / KPIs | Works: M + real read-only Gmail dry run (board side) | Google Tasks API disabled in the GCP project (HTTP 403): Google-side creation fails until the owner enables it |
| TV / home | Works for one TV: M + F (Habitación Maqueda on/off, owner present) | other TV and Roku, unreachable/timeout on hardware; `on?` state is ambiguous by design |
| Memory, knowledge graph, learning rules | Works: I against a disposable pgvector DB (store, dedup, restart survival, retire/restore, schema idempotent) + M (suites, DB checks no longer skipped) | real embeddings (no Ollama), migration of a populated DB, backups |
| Google mail/calendar/drive | M (fake provider contracts) | real provider results beyond the read-only mail run; no mail is sent by default |
| Instagram, Content OS | I for UI rendering with synthetic data; M for analysis | real Graph API results; third-party reel ingestion is unsupported |
| PC, media, Chrome, voice | M (app-launch decisions) | real desktop launch, audio, browser control |
| Messaging/automation (Telegram, n8n, phone, Discord) | M | accepted webhook ≠ delivered message; none verified live |
| Research, weather, places, watches, billing | M | live data provenance; billing produces a draft only, no email delivery |

## Open
P1-08 external integrations, P1-09 local PC/media/voice, P2-10 product-claim audit. Each needs an owner-approved scope (sandbox accounts, devices, or a disposable database) before it can move past M.
