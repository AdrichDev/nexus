# ai_media: keep only what works, and make it better

Owner request: remove what the skill does not really do, fix it, and optimize the real parts.

## Decision
- REMOVE image generation (`gen_image`: it only wrote a placeholder SVG) and image analysis (`analyze_image`: it only returned file size/dimensions, never the content). Nexus must not offer them. Also remove the frontend action «Generar imagen…» and the routing/tests that expected them.
- KEEP and IMPROVE the two real parts: audio transcription (local Whisper) and web search.
- Folder name stays `ai_media` (router tests, regression corpus and learned commands reference it); display name/description change to what it does now.

## Tasks
- [ ] T1 Remove `gen_image`/`analyze_image` (skill, SKILL.md, frontend action/description, tests); name/description updated.
- [ ] T2 Web search: read the top pages (parallel, with timeout) instead of answering from snippets; numbered sources cited as [n]; admit when the sources do not answer; compact "Fuentes" list (domain + title).
- [ ] T3 Transcription: validate the file type, catch decoder errors honestly, report duration, timestamps in the note, analysis in blocks for long audio (say when something was left out), re-transcribing the same file replaces its previous memory rows.
- [ ] T4 Review, merge to main, docs.

## Risks to watch
- Phrases like «genera una imagen de…» will no longer match any skill and fall through to the conversational model, which could pretend to have done it. Checked and reported at the end.
- Real Whisper is not available in the test harness: transcription keeps being verified with mocks.

## Evidence
(append commits and checks here)
