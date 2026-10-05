# ai_media (and datos insight): honest outputs, safe files, real paths

Reproduced through the real command path (Docker harness) or by reading + unit mocks:
- `genera una imagen de <script>alert(1)</script> & R&D` writes an invalid SVG with a raw `<script>`.
- Paths with spaces (quoted or not) are not found, and the error names a truncated path (`/tmp/mi`).
- A non-image file (`notas.txt`) is answered as an image with "0 KB".
- Web search without an LLM drops the 6 results it found and shows only the provider error; sources are only in `data`, which the UI does not render.
- Transcription: ignores `ask_llm` provider `"ninguno"` (the error text would be saved as the analysis), silently truncates (note 15000 chars, DB 2000 chars) while claiming "guardado en memoria", and names the note by the first 36 chars of the file stem (two audios collide).
- `datos` dashboard pastes the LLM error as if it were an observation (open item from the datos audit).

## Tasks
- [x] T1 Escape the prompt in the placeholder SVG.
- [x] T2 Path resolver for analyze/transcribe: quotes, spaces, trailing words; errors show the path as typed.
- [x] T3 `analyze_image`: non-image -> say so; sizes in bytes/KB readable.
- [x] T4 `web_search`: visible "Fuentes", and when the LLM is unavailable show the results found instead of the error.
- [x] T5 `transcribe`: no analysis when the LLM is unavailable; full transcript stored (note whole, DB in chunks); unique note name; honest storage line.
- [x] T6 `datos` dashboard: same LLM-unavailable handling.
- [ ] T7 Review, merge to main, docs.

## Evidence
(append commits and checks here)
- T1-T5 in `skills/ai_media/skill.py`: `html.escape` on the SVG prompt; `_resolver_ruta` (quotes, spaces, trailing words dropped until a file exists; error shows the path as typed) with path groups now `(?P<path>.+)`; `_tam` (bytes/KB/MB); non-image files: a `.txt` is reported as not an image, a corrupt file WITH an image extension keeps the metadata + vision-model message and says it could not open it (the existing `test_skills_pequenas_2` contract); `web_search` appends `Fuentes: <domains>` and, when `ask_llm` returns provider `ninguno`, shows the found results (title + link) and the reason instead of the bare error; `transcribe` keeps the whole transcript (note whole, DB in `rag.trocear` chunks), skips the analysis and says so when the LLM is unavailable, note title `audio <stem[:28]> <sha1(path)[:6]>`, honest storage line.
- T6 `datos` dashboard: provider `ninguno` -> "No pude generar observaciones (el modelo no está disponible): ..." instead of presenting the error as an observation.
- Checks: `test_ai_media_honesty.py` RED 20 failures -> GREEN 24/0; `test_datos_honesty.py` 36/0 (+1 case RED->GREEN), `test_skill_datos` 64/0; pequenas_1 355, pequenas_2 89 (a first version of T3 broke 3 checks there and was adjusted), frases_reales 212, research 75, domotica 266, capas_backend 449, runner profiles 515.
- Not covered / open: real Whisper transcription not run (no model in the harness; Whisper and memory are mocked); image generation is still a placeholder SVG and vision is metadata-only (as documented); `speak` is not read by `brain.py`, so the new `Fuentes:` line may be spoken by TTS.
