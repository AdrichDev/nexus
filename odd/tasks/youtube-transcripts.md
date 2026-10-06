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
- [x] T1 `youtube.py` module with tests (parse, track choice, errors, windows, cache, no multi-track requests).
- [x] T2 `research` integration.
- [x] T3 `ai_media` `web_search` integration (conditional).
- [x] T4 `ai_media` `video_youtube` command (+ Whisper fallback, shared storage code).
- [x] T5 Docs (SKILL.md x2, CAPAS.md), live probe, layer registry test.
- [ ] T6 Review, merge to main.

## Risks / limits to state to the owner
- Not an official API: YouTube may rate-limit (429) or change; reading public captions for personal use.
- Automatic captions are lower quality and videos can be sensationalist: they are labelled and treated as less reliable than articles.
- Whisper path cannot be exercised end to end in the harness (no model): mocked.

## Evidence
- T1 GREEN 2026-10-06: `.venv/Scripts/python.exe tests/unit/core/test_youtube.py` -> `youtube: 34 OK, 0 FAIL`.
- T1 structural checks 2026-10-06: `.venv/Scripts/python.exe -m compileall -q backend/core/infraestructura/youtube.py` exit 0; `git diff --check` exit 0.
- T2 RED 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/research/test_research_honesty.py` failed because research never called `youtube.fuentes_video` and the prompt lacked `FUENTE [5]`.
- T2 GREEN 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/research/test_research_honesty.py` -> `research honesty: 57 OK, 0 FAIL`.
- T2 youtube regression 2026-10-06: `.venv/Scripts/python.exe tests/unit/core/test_youtube.py` -> `youtube: 34 OK, 0 FAIL`.
- T3 RED 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_ai_media_honesty.py` failed on the new YouTube transcript assertions because `ai_media` did not call `youtube.fuentes_video`, did not append/label video sources, and did not surface omitted videos.
- T3 GREEN 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_ai_media_honesty.py` -> `ai_media: 49 OK, 0 FAIL`.
- T3 youtube regression 2026-10-06: `.venv/Scripts/python.exe tests/unit/core/test_youtube.py` -> `youtube: 34 OK, 0 FAIL`.
- T3 research regression 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/research/test_research_honesty.py` -> `research honesty: 57 OK, 0 FAIL`.
- T3 structural check 2026-10-06: `.venv/Scripts/python.exe -m compileall -q skills/ai_media/skill.py backend/core/infraestructura/youtube.py skills/research/skill.py` exit 0; `git diff --check` exit 0.
- T4 RED 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_youtube_video_command.py` failed because `video_youtube` did not exist/routing stayed absent.
- T4 GREEN 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_youtube_video_command.py` -> `ai_media_youtube: 16 OK, 0 FAIL`.
- T4 ai_media regression 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_ai_media_honesty.py` -> `ai_media: 49 OK, 0 FAIL`.
- T4 youtube regression 2026-10-06: `.venv/Scripts/python.exe tests/unit/core/test_youtube.py` -> `youtube: 34 OK, 0 FAIL`.
- T4 structural/verify 2026-10-06: `.venv/Scripts/python.exe -m compileall -q skills/ai_media/skill.py backend/core/infraestructura/youtube.py` exit 0; `git diff --check` exit 0; independent verifier found no blockers for routing, no-download captions path, fallback-only-on-direct-command, 90-min cap, temp cleanup, and honest no-summary failure paths.
- T5 layer registry 2026-10-06: `.venv/Scripts/python.exe tests/unit/core/runtime/test_capas_backend.py` -> `test_capas_backend: 457 OK, 0 fallos`.
- T5 youtube regression 2026-10-06: `.venv/Scripts/python.exe tests/unit/core/test_youtube.py` -> `youtube: 34 OK, 0 FAIL`.
- T5 ai_media regressions 2026-10-06: `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_ai_media_honesty.py` -> `ai_media: 49 OK, 0 FAIL`; `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_youtube_video_command.py` -> `ai_media_youtube: 16 OK, 0 FAIL`.
- T5 live caption-only probe 2026-10-06: `.venv/Scripts/python.exe -c "import asyncio, importlib; yt=importlib.import_module('backend.core.infraestructura.youtube'); yt._CACHE={}; yt._save_disk_cache=lambda data: None; r=asyncio.run(asyncio.wait_for(yt.transcripcion('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), 45)); print({'ok': r.get('ok'), 'motivo': r.get('motivo'), 'title': r.get('title'), 'tipo': r.get('tipo'), 'idioma': r.get('idioma'), 'lineas': len(r.get('lineas') or [])})"` -> `{'ok': True, 'motivo': None, 'title': 'Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)', 'tipo': 'manual', 'idioma': 'en', 'lineas': 61}`; caption-only through `transcripcion`, one selected manual track, no audio/video download, disk cache disabled for the probe.
- T5 structural check 2026-10-06: `git diff --check` exit 0.
## Resume point
- State: branch `feat/youtube-transcripts`, T1-T5 complete in the working tree. Untracked files `backend/core/infraestructura/youtube.py` and `tests/unit/skills/ai_media/test_youtube_video_command.py` must be included in any review/commit candidate.
- Verified latest commands: `.venv/Scripts/python.exe tests/unit/core/runtime/test_capas_backend.py` -> `test_capas_backend: 457 OK, 0 fallos`; `.venv/Scripts/python.exe tests/unit/core/test_youtube.py` -> `youtube: 34 OK, 0 FAIL`; `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_ai_media_honesty.py` -> `ai_media: 49 OK, 0 FAIL`; `.venv/Scripts/python.exe tests/unit/skills/ai_media/test_youtube_video_command.py` -> `ai_media_youtube: 16 OK, 0 FAIL`; `.venv/Scripts/python.exe tests/unit/skills/research/test_research_honesty.py` -> `research honesty: 57 OK, 0 FAIL`; compileall for changed Python modules exit 0; `git diff --check` exit 0. Live caption-only probe succeeded with one manual `en` track and 61 lines.
- Next step: T6 native review, then ask/obtain explicit owner authorization before any commit or merge to `main`.
- Remember: ONE caption track per video (requesting es.*,en.* gave HTTP 429); research/search skip videos without captions and say so; direct command may use Whisper fallback only after the user explicitly asks for one video and caps fallback at 90 min with temp cleanup.
