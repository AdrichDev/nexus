# ai_media (and datos insight): honest outputs, safe files, real paths

Reproduced through the real command path (Docker harness) or by reading + unit mocks:
- `genera una imagen de <script>alert(1)</script> & R&D` writes an invalid SVG with a raw `<script>`.
- Paths with spaces (quoted or not) are not found, and the error names a truncated path (`/tmp/mi`).
- A non-image file (`notas.txt`) is answered as an image with "0 KB".
- Web search without an LLM drops the 6 results it found and shows only the provider error; sources are only in `data`, which the UI does not render.
- Transcription: ignores `ask_llm` provider `"ninguno"` (the error text would be saved as the analysis), silently truncates (note 15000 chars, DB 2000 chars) while claiming "guardado en memoria", and names the note by the first 36 chars of the file stem (two audios collide).
- `datos` dashboard pastes the LLM error as if it were an observation (open item from the datos audit).

## Tasks
- [ ] T1 Escape the prompt in the placeholder SVG.
- [ ] T2 Path resolver for analyze/transcribe: quotes, spaces, trailing words; errors show the path as typed.
- [ ] T3 `analyze_image`: non-image -> say so; sizes in bytes/KB readable.
- [ ] T4 `web_search`: visible "Fuentes", and when the LLM is unavailable show the results found instead of the error.
- [ ] T5 `transcribe`: no analysis when the LLM is unavailable; full transcript stored (note whole, DB in chunks); unique note name; honest storage line.
- [ ] T6 `datos` dashboard: same LLM-unavailable handling.
- [ ] T7 Review, merge to main, docs.

## Evidence
(append commits and checks here)
