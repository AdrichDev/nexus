# Chat responsividad (A+B)

Make the HUD chat feel fast: measure, remove dead sequential work, and stream text to the HUD.
Branch `fix/security-audit-remediation` (continues the audit branch; owner approves pushes).

## Specs

- S1: «el chat y le hice preguntas y tardaba mucho dudaba» — owner complaint, 2026-11-09.
- S2: Quick wins A (owner: «A + B juntas»): time-log the three sequential brain awaits (plan_action / interpret_command loop / ask_llm), skip the 2nd `interpret_command` retry when the 1st returned empty/light («pido reformulación» path, brain.py:1534), and move `pg.remember` OFF the emit path (emit `chat` first, persist after; brain.py:1103→1133).
- S3: Quick win B (owner: «A + B juntas»): stream text answers to the HUD reusing the existing `ask_llm_stream` (the voice path already streams, brain.py:1971); the HUD renders incrementally or, if the bus cannot chunk a `chat` event without redesign, the smallest honest streaming variant agreed in the task.
- S4: NO over-engineering (owner: «no quiero sobre ingenieria»): no new orchestrator, no speculative config; behaviour change only where S2/S3 name it.

## Tasks

| ID | Specs | Task | Route | Risk | Commit |
|----|-------|------|-------|------|--------|
| T1 | S2 | Timing instrumentation — [x] | worker | none | 23c1cb3 |
| T2 | S2 | «Skip when empty» — NO CHANGE NEEDED: `if not guess: break` already existed (premise false). Pinned: 1 call on empty, 2 attempts when the 2nd matches | worker | none | 23c1cb3 |
| T3 | S2 | Emit-first persistence — [x] (background `_persistir_turno`, restricted channels intact) | worker | item 2 (ordering) | 23c1cb3 |
| T4 | S3 | Stream text-HUD — [x] (`chat_delta` throttled 200 ms / capped 12, sanitized, `chat` still carries full text; text+pc only) | worker | item 3 | 23c1cb3 |
| T5 | S2-S4 | Focused suites (30 green incl. politica_brain 176/0 after parent's `chat_delta`-out-of-replay one-liner in events.py) + differential 304/304 identical — [x] | worker | none | 23c1cb3 |

## Log

- **L1** (owner, 2026-11-09): «y le hice preguntas y tardaba mucho dudaba» (chat slowness complaint) — verbatim from owner message: «porque ayer estuve probando el chat y le hice preguntas y tardaba mucho dudaba».
- **L2** (owner decision, 2026-11-09): chose «A + B juntas» for latency.
- **L3** (owner decision, 2026-11-09): chose Chatterbox TTS «en paralelo» — recorded in voz-chatterbox.md; surfaces overlap forces it after A+B (runtime rule), not a scope change.
- **L4** (evidence, 2026-11-09): diagnosis handoff saved as memory `nexus/chat/diagnostico-latencia` (brain.py 1125/1246/1485/1512/1534/1876/1952/1971/1975/1103; app.py 600/635; llm.py ~1030; llm_runtime ~430; memory.py 755/1097; rag.py 584; command.js 79/478/553).
- **L5** (T1-T5, commit `23c1cb3`): brain.py +144/−16, command.js +21/−1, test_politica_brain +203/−12. RED on a `git archive` base tree: 13 real failures (T3 order, T1 measurements missing, T4 no drafts), T2 pins already green there → proof T2 needed no change: `interpret_command` returning '' already breaks the loop (`if not guess: break`); the actually expensive double is plan_action → interpret_command (two full prompts per instruction), now measured by T1. GREEN 176/0; battery spot list in worker report all green; T5 differential vs HEAD: 304/304 identical decisions (260 prometidas + 34 reglas + 6 charla). Parent added `chat_delta` to `_SIN_HISTORIAL` (events.py:44) so drafts leave the 200-event replay window; policy/log/results suites re-run green after it. LEFT for an owner decision (behaviour change, NOT done): skip `interpret_command` when plan_action already classified the phrase as charla — this would cut one full LLM call per plain chat message. Residual risks: background persistence is not retried (if the process dies right after the last turn, that turn may not reach the DB — previously it would have blocked and lost it anyway); a promise could flash briefly in a draft (sin_progreso_inventado applies to the final message only); voice/mobile/telegram streaming untouched.
