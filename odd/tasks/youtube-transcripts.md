# YouTube transcripts as a source (research, search, and a direct command)

Owner request: Nexus should be able to look up information in YouTube videos by READING their transcripts (it does not need to understand the video itself).

## Decisions (owner)
- Scope: extra numbered sources in reports and searches **and** a direct command for one video («resume el vídeo <enlace>»).
- Videos without captions: in reports/searches they are skipped and the reply says so (no audio is downloaded unasked). With the direct command, Whisper transcribes the audio (downloaded to a temp dir, deleted afterwards).

## Verified facts (live probe, no media downloaded)
- `yt-dlp` 2026.07.04 (already in `requirements.txt`) lists captions and fetches a single caption track (~4 KB of timestamped text) without the video/audio, and can search videos without an API key.
- Asking for many tracks at once (`es.*,en.*` = ~10 auto-translations) returned HTTP 429: the design requests ONE track (the original language, manual before automatic) and caches results.

## Design
- New `backend/core/infraestructura/youtube.py`: `buscar_videos`, `transcripcion` (json3 track fetched with ONE request, parsed to timed lines), `fuentes_video` (picks the passages most relevant to a query, returns numbered-source dicts with `&t=…s` links), errors as values (no captions / 429 / unavailable), disk cache.
- `research`: up to 2 video sources added after the web pages, marked "VÍDEO (transcripción automática|manual)" and flagged as less reliable in the prompt; skipped videos mentioned.
- `ai_media` `web_search`: videos only when the question mentions vídeo/YouTube or fewer than 2 web pages could be read.
- `ai_media` new intent `video_youtube` (before `transcribe`): transcript summary with minute references; no captions -> Whisper on the audio (temp file, max 90 min), shared memory-saving code with local audio transcription.

## Tasks
- [ ] T1 `youtube.py` module with tests (parse, track choice, errors, windows, cache, no multi-track requests).
- [ ] T2 `research` integration.
- [ ] T3 `ai_media` `web_search` integration (conditional).
- [ ] T4 `ai_media` `video_youtube` command (+ Whisper fallback, shared storage code).
- [ ] T5 Docs (SKILL.md x2, CAPAS.md), live probe, layer registry test.
- [ ] T6 Review, merge to main.

## Risks / limits to state to the owner
- Not an official API: YouTube may rate-limit (429) or change; reading public captions for personal use.
- Automatic captions are lower quality and videos can be sensationalist: they are labelled and treated as less reliable than articles.
- Whisper path cannot be exercised end to end in the harness (no model): mocked.

## Evidence
(append commits and checks here)
## Resume point (saved before a restart)
- State: branch `feat/youtube-transcripts`, T1 in progress. `tests/unit/core/test_youtube.py` is written and committed in RED (the module does not exist yet: `ModuleNotFoundError: backend.core.infraestructura.youtube`).
- Next step: create `backend/core/infraestructura/youtube.py` so that test passes. Required API (from the test): `id_de_url`, `es_url_youtube`, `_parse_json3`, `_elegir_pista(info, idiomas)` (manual of the video language > original `-orig` automatic, never translations, json3 only, returns dict with `url/idioma/tipo`), async `transcripcion(video)` returning `{ok, id, title, canal, idioma, tipo, lineas, texto}` or `{ok: False, motivo: sin_subtitulos|no_disponible|limite|error, title?}`, `class Limite(Exception)`, in-memory cache (positive + negative), 429 cooldown, `_reset_estado()`, `ventanas_relevantes(lineas, query, max_chars) -> (texto, inicio_seg)`, async `buscar_videos(query, n)` (dedupe by id, drop > 4 h), async `fuentes_video(query, n, max_chars) -> (fuentes, omitidos)`. Network seams to be replaced by tests: `_buscar_sync(q, n)`, `_info_sync(video_id)`, async `_descargar(url)`.
- Then T2 (research), T3 (ai_media web_search), T4 (ai_media `video_youtube` intent before `transcribe`, Whisper fallback, shared memory-saving code), T5 (docs, CAPAS.md + `test_capas_backend` entry for `youtube`, live probe), T6 (native review, merge to main).
- Remember: ONE caption track per video (requesting es.*,en.* gave HTTP 429); `main` is clean and pushed (last commit `0806757`); the research follow-ups are merged.
