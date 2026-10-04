# Reject false Hermes completion and resume safe skill auditing

## Objective and authorization
The owner approved correcting Hermes false completion and checking probe isolation before more live skill queries. Do not change provider selection, citations policy, or external accounts as part of this fix. No push or merge in this work unit without a fresh delivery decision.

## Confirmed problem
The pure `respuesta_es_error()` classifier returns an empty reason for the observed provider failure `⚠️ No reply: the model returned empty content after retries and any fallback providers. Try \`continue\`, switch model/provider, or inspect the tool output above.` Hermes wraps it as success, and JobManager marks a normal return completed. An independent AST-only verifier reproduced this before implementation.

## Scope and constraints
- Allowed behavior changes: `skills/hermes/skill.py`, with focused regression coverage under `tests/unit/skills/hermes/` and runner registration if a new standalone suite is needed.
- Never import host configuration for the pure classifier test; no live Hermes, Google, database, accounts, devices, or cloud calls.
- Preserve successful prose, recognized authentication errors, and JobManager lifecycle semantics.
- Existing connector hazards: Google tokens use repository config; Hermes may use host home irrespective of NEXUS_CONFIG_DIR. No further broad live probes until boundaries are verified.
- Branch: `fix/hermes-empty-response`; base: `cdff971`.
- Delivery strategy: ask-on-risk; forecast 80–180 authored diff lines; one coherent fix commit expected.

## Tasks
- [x] H1 — Reject provider empty-content failures; deterministic regression RED (2 failures), GREEN (4 tests), negative controls and focused Hermes suite (202 OK/0 failures). Route: delegated writer, multi-file/preparation trigger. Work-unit commit: `b71d301`.
- [x] H2 — Independent verification completed; mapped the smallest safe probe boundary read-only. Route: delegated verifier. This closes verification/mapping, not broad live skill testing. Included evidence in `b71d301`; final ledger follows as passive documentation.

## Acceptance
Observed warning must produce a nonempty error reason and enter existing failed path rather than success wrapping. Successful answers must not be rejected merely for discussing empty responses. Check both classifier behavior and admission-path wiring. No real provider error text may be reported as successfully completed.

## Evidence and progress
- Before implementation: independent AST-only check gave warning => `''`, success => `''`, auth error => nonempty.
- H1 implementation: precise provider-failure patterns added; removed the success-like fallback that masked truly empty content. New AST-only regression suite registered once in run_all.
- Writer observed RED (2 intended failures), then GREEN (4 tests); successful prose and existing auth/quota controls passed.
- Independent verifier: 4 regression tests passed; existing Hermes suite 202 OK/0 failures in a no-network Docker snapshot containing the current candidate. First verification mount was read-only and failed to create data; adding only a disposable data tmpfs resolved that environmental setup failure. Python AST/whitespace checks passed.
- H2 mapping: city-specific public weather uses wttr.in without Google/Hermes; research additionally invokes configured LLM and writes reports. Further broad live queries remain paused; do not claim full connector isolation.
- Assessment initially unassessable because untracked selection was undeclared; independent verification therefore ran. Native review tier: medium, one reliability reviewer, consent granted through the host. `review-aebb9c4e660d48ad` approved and exact acknowledgement burned authority for the candidate committed as `b71d301`.
- Native nonblocking advisories: R3-001 at skills/hermes/skill.py:918 and R3-002 at tests/unit/skills/hermes/test_empty_response.py:79-99. The closure exposed IDs/locations only, not finding prose; no cause or remediation is invented. No correction was requested.
- No whole-suite run, live Hermes/provider trial, push or merge occurred in this work unit.
- Isolated restart/file-backup/persistence work and earlier CI/chat fixes are outside this candidate.

## Next step
Correction complete on the feature branch. Continue the larger skill audit using isolated public-web/weather probes; generic routing/research requires additional connector controls before live execution. Push/merge remains a separate owner decision.
