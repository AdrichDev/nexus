# Source-grounded research and verified correction learning

## Objective
Fix research retrieval and make repeated wrong-answer feedback lead to explicit review, not blind factual memorization. Owner authorized removing the forced year and rejecting consent pages, then selected verified correction learning (option 1).

## Scope and safety
- R1: preserve user query temporal intent in skills/research; reject Google consent/interstitial pages as source evidence including cached entries in central websearch.
- R2: map and implement the smallest correction flow reusing existing conversation/operational-memory boundaries. Wrong-answer feedback is not a fact. Ask for a concrete correction or re-check evidence, distinguish pending from verified, associate correction with context/source, and acknowledge repeated unresolved feedback. Do not train model weights or make learned rules steal native routes.
- Do not change provider selection, personal credentials, device state, or unrelated feature behavior.
- Tests use fake providers and disposable data/config. Live proof only in clean disposable containers with no private mounts, local Ollama and public web; never generic host routing into Google/Hermes.
- Branch: fix/research-correction-learning, base 304fd64e9fddb297a439dd90e21ca38744d52b7a. Previous Hermes fix remains unchanged.
- Delivery: ask-on-risk; initial forecast 250–400 authored diff lines for retrieval and correction slices, revise after bounded learning mapping. No push/merge without fresh decision.

## Tasks and acceptance
- [ ] R1 — Remove forced year; filter consent URLs/redirects/content and cached consent pages; deterministic RED/GREEN, ordinary content negative controls, no-source behavior remains honest. Delegated writer (multi-file/preparation trigger). Commit as one retrieval work unit.
- [ ] R2 — Map existing feedback context/persistence and implement verified correction learning with isolated deterministic regressions. Delegated exploration then writer. Pending feedback must never count as verified; repetition must not trigger action/route theft.
- [ ] R3 — Independently verify applicable checks, repeat the historical/current factual probes once under safe boundaries and record unresolved evidence gaps. Delegated verifier. No plausible-answer-only PASS.

## Evidence
Earlier real skill audit: voting-age debate had relevant nonprimary sources; historical FIFA2022/2023 query was polluted by forced2026 and Google consent pages; latest unemployment report lacked official publication-date evidence. These are retrieval evidence, not proof all resulting factual claims were false.
R1 writer observed RED (6 failures/5 passes), then GREEN (11 passes). Independent verifier confirmed 11/0, existing research suite 75/0 and v19 suite 69/0 in a no-network Docker snapshot containing current candidate bytes. Several verification setup attempts failed (missing temp directory, MSYS path conversion, copy timestamp permissions) before the successful isolated checks. A sibling verification scratch directory named `nexus-r1-verify.yepVbI;C` was reported left behind; do not delete arbitrary temporary paths.
R1 authored estimate approximately 226 diff lines plus task documentation; broader correction-learning estimate would exceed the initial combined 400-line forecast, so delivery strategy must be resolved before a larger next slice.
R2 mapping: pending feedback can reuse selflearn storage but must not be saved as global factual/operational correction. Full verified promotion requires a concrete source-support rule (human-confirmed vs excerpt-supported); do not silently label any URL or model judgment verified.
Native review/risk, work-unit commits and live recheck: pending.

## Next step
R1 implemented and independently checked, awaiting native review and work-unit commit. R2 is blocked on how source-supported verification is confirmed; keep it pending rather than mislabel user claims verified. Live R3 recheck remains pending.
