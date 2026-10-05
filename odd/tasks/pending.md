# Nexus pending work

Last updated: 2026-10-05 after delivering `research-correction-learning` to `main` at `f742d44ef57b860803998169fd4e7a2880667d45`.

## Recently closed
- `research-correction-learning` is delivered on `main`.
  - R1: preserved research query dates and rejected consent/interstitial evidence.
  - R2: wrong-answer feedback now re-researches with source-backed contrast and does not learn complaints as facts.
  - R3: focused deterministic checks and safe live probes completed.
  - CI `seguridad` run `37299363982` passed.

## Carry-forward annotations
- Google browser search works in the last safe live run, but it can still CAPTCHA later; Nexus must degrade honestly when blocked.
- Chrome search runs as an off-screen browser inside the server process; two processes cannot share the same Google browser profile.
- Correction evidence must not treat a plausible model answer, a URL alone, or a weak quote as PASS.
- Corrections must not persist without explicit user confirmation.
- Historical Moon probe had usable but mixed-quality evidence; INE unemployment and Smithsonian Apollo probes were stronger.
- Known flaky check remains `test_inbox_scale` timing threshold under full battery.
- `rtk` is not available in this shell; use raw commands unless installed later.
- Optional cleanup: delete the merged branch `fix/research-correction-learning` locally/remotely when convenient.

## Active pending work candidates

### 1. Continue use-case verification audit
Source: `odd/tasks/verify-nexus-use-cases.md`.
- P0-01b: hermetic boundary is partial; browser E2E boundary remains open.
- P0-02: runner evidence honesty and native review availability remain pending.
- P0-03: startup/core journey verified in isolated container; real desktop/provider paths remain open.
- P1-06: tests reorganization is still in progress.
- P1-08: external integrations need separate contract/sandbox verification.
- P1-09: local PC/media/voice workflows need controlled verification.
- P2-10: information/product claims need provenance audit.
- P2-11: CU evidence ledger needs continued publication/maintenance.

### 2. Continue inbox / task KPI work
Source: `odd/tasks/inbox-task-kpi.md`.
- T5c/T9 real Gmail path remains partially open.
- Google Tasks API was disabled in the GCP project during the last real run; reply classification was improved later, but real delivery needs explicit sandbox/API setup before claiming end-to-end success.
- Classifier variance and remaining real-provider behavior should be handled with bounded, read-only or sandboxed checks first.

### 3. Continue broader skill audit
Source: `odd/tasks/hermes-empty-response.md` and current audit history.
- Continue isolated public-web/weather/research probes.
- Generic routing/research still needs connector controls before broad live execution.
- External/device/provider claims must remain separated from mocked or handler-only evidence.

## Recommended next slice
Start with `verify-nexus-use-cases` P0-02 / runner evidence honesty, because it reduces false confidence across all later work. Keep it narrow: inspect current runner/E2E evidence labels, choose one misleading claim or unsafe boundary, write a regression/check first when applicable, then update the ledger.
