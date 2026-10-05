# ai_media: keep only what works, and make it better

Owner request: remove what the skill does not really do, fix it, and optimize the real parts.

## Decision
- REMOVE image generation (`gen_image`: it only wrote a placeholder SVG) and image analysis (`analyze_image`: it only returned file size/dimensions, never the content). Nexus must not offer them. Also remove the frontend action «Generar imagen…» and the routing/tests that expected them.
- KEEP and IMPROVE the two real parts: audio transcription (local Whisper) and web search.
- Folder name stays `ai_media` (router tests, regression corpus and learned commands reference it); display name/description change to what it does now.

## Tasks
- [x] T1 Remove `gen_image`/`analyze_image` (skill, SKILL.md, frontend action/description, tests); name/description updated.
- [x] T2 Web search: read the top pages (parallel, with timeout) instead of answering from snippets; numbered sources cited as [n]; admit when the sources do not answer; compact "Fuentes" list (domain + title).
- [x] T3 Transcription: validate the file type, catch decoder errors honestly, report duration, timestamps in the note, analysis in blocks for long audio (say when something was left out), re-transcribing the same file replaces its previous memory rows.
- [ ] T4 Review, merge to main, docs.

## Risks to watch
- Phrases like «genera una imagen de…» will no longer match any skill and fall through to the conversational model, which could pretend to have done it. Checked and reported at the end.
- Real Whisper is not available in the test harness: transcription keeps being verified with mocks.

## Evidence
(append commits and checks here)
- T1: `gen_image` and `analyze_image` removed from `skills/ai_media/skill.py` (patterns, SVG template, handlers, `OUT_DIR`); skill renamed "Audio y búsqueda web"; `SKILL.md` rewritten (states plainly that it neither generates nor describes images); frontend `catalog.js`: label `AUDIO Y WEB`, no «Generar imagen…» action; `test_skills_pequenas_1/2`: image routes became "must NOT reach ai_media" checks and the vídeo route was added. `llm.py` `SYSTEM_PROMPT` now says Nexus does NOT generate images or describe photos and must not fake it (without a skill those phrases fall to the conversational model: confirmed in the Docker router probe).
- T2: search reads the top 3 pages in parallel (`_leer_paginas`, 8 s per page), numbered sources `[n]` in the prompt, cite-or-admit instruction, today's date, compact "Fuentes: [n] dominio — título"; `_limpiar` drops search-engine ads/redirects (found in the live probe: DuckDuckGo sponsored results took 2 of the 3 page reads) and asks for 8 results to keep 6. Live probe in Docker (real network): pages of ~1.8k chars read, 1.1-2.1 s total.
- T3: transcription validates the extension (audio/video list), turns decoder exceptions into an honest message (before: raw exception), reports duration, note has `[mm:ss]` timestamps (DB chunks are clean text), analysis in blocks of 6000 chars (max 6 blocks + a consolidation call, says when it stopped at 36.000 chars), re-transcribing the same file replaces its previous rows (`pg.filas_por_origen`, read-only SQL; compares redacted content), accepts `transcribe el vídeo …`.
- Checks: `test_ai_media_honesty.py` RED (20+ failures) -> GREEN 41/0; pequenas_1 352, pequenas_2 84, frases_reales 212, routing 244, content_os_honestidad 135, llm_runtime 158, specs_v23 132, research 75, domotica 266, capas_backend 449, frontend modules 147, runner profiles 515.
- Not covered / open: real Whisper never ran (mocked); transcription assumes Spanish (documented); phrases about images now depend on the conversational model honouring the new SYSTEM_PROMPT line (not testable without a model); `filas_por_origen` SQL not run against the live DB yet.
