# Voz Chatterbox es-es (C)

Add Chatterbox Multilingual `es-es` as an optional TTS engine; Elvira/edge-tts stays the default until the owner compares and decides. Owner chose: «Chatterbox es-es (recomendado)».

## Specs

- S1: «tendriamos que revisar las voz porque no suena muy real» — owner, 2026-11-09.
- S2: Chatterbox es-es (Castilian checkpoint, MIT code+weights) becomes an optional engine value in `tts_engine`; existing auto/edge/elevenlabs/local/off behaviour is byte-identical; edge stays default (`auto` resolves as today).
- S3: The engine appears in the HUD selector (`#m-tts`, command.js:2156), in `all_voices()` (tts.py:730) and `tts_status()` (tts.py:744); a voice/label for es-es is listed.
- S4: Lazy one-time model load (mirror `_pyttsx3_engine` caching, tts.py:254); synthesis runs in an executor thread, never blocks the loop; sentence chunking reuse.
- S5: NO over-engineering (owner constraint): no queue server, no clone pipeline, no redesign of the three callers' branch shape — add `_chatterbox_bytes` next to `_edge_bytes`/`_eleven_bytes` + the three dispatch branches + registrations.
- S6: Dependency reality (item 5, delivery): pip install chatterbox-tts (+torch) happens ONLY with the owner present for the multi-GB download; requirements.txt/requirements.lock update and CI pip-audit consequences run as part of this unit.

## Tasks

| ID | Specs | Task | Route | Risk | Commit |
|----|-------|------|-------|------|--------|
| T1 | S2,S4,S5 | `_chatterbox_wav`+`_chatterbox_bytes` — [x] (lazy import, memoized model, to_thread, never raises) | worker | item 5 (deps) | fb4151a |
| T2 | S2,S5 | Dispatch ×3 — [x] (worker's acked deviation: auto = chatterbox→edge→elevenlabs→local, keeps the edge/elevenlabs pair byte-identical; premium-first would flip every current key-holder to paid ElevenLabs) | worker | item 2 | fb4151a |
| T3 | S3 | Voices/status + HUD — [x] («Cuentista (España, local)», available via find_spec, note carries the pip hint; `_audio_ext` RIFF→wav added for correct MIME) | worker | none | fb4151a |
| T4 | S2-S5 | 43 new checks in test_specs_v23_files (registered) — RED 111/20 on base tree, GREEN 141/0; preserve pins for edge/elevenlabs/local/off | worker | none | fb4151a + parent app.py/config.py one-liners |
| T5 | S6 | Owner-approved install + requirements-voice.txt lock + CI triage | inline w/ owner | item 5 | - |

## Log

- **L1** (owner, 2026-11-09): «tendriamos que revisar las voz porque no suena muy real. Igual podriamos mirar algun repo de codigo abierto en el que haya voces algo mas reales» — verbatim.
- **L2** (evidence): research handoff saved as memory `nexus/tts/investigacion-voces-reales`: seam `_edge_bytes` tts.py:289, `_eleven_bytes` :308, callers :330/:507/:583, all_voices :730, HUD command.js:2156; Chatterbox es-es = only commercial-clean native-Castilian pick (retired upstream Aug 2026 — accepted by owner knowing this), Kokoro = LatAm only, XTTS/F5 non-commercial.
- **L3** (owner decision, 2026-11-09): «Chatterbox es-es (recomendado)» chosen; launch planned parallel but ordered after chat-responsividad due to disjoint-surface rule (app.py/command.js shared).
- **L4** (T1-T4, commits `fb4151a` + parent one-liners inside it): engine shipped and degrading-clean without the lib (exactly the T4 target). Parent accepted the worker's dispatch-order deviation (reason above) and applied the two one-liners left outside its surfaces: `app.py` `can` gate now includes `st.get("chatterbox")` (both /api/tts_test and the greeting) and the stale `config.py:142` comment now lists the new value. Validation rerun by parent: 141/0 and 132/0. Residual: upstream API shape (`from_pretrained(device=...)+generate(language_id="es")+sr`) is the documented multilingual call, never executed here — if the installed version differs, `_chatterbox_wav` is the 5-line local fix; CPU synthesis may feel slower than edge on long replies (device=cuda is the knob if a GPU exists); the auto-failure warn text does not mention chatterbox yet (extends in T5 if wanted). T5 pending owner presence: pip install into the 3.12 venv (multi-GB torch), add chatterbox-tts + pinned torch/torchaudio to requirements-voice.txt (NOT requirements.txt; installed by run.bat), regenerate requirements.lock in the same commit, expect pip-audit triage noise from torch metadata on the first CI run, restart backend (HAS_CHATTERBOX is import-time), verify the checkpoint API and device, then decide default vs edge by ear.
