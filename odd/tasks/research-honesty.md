# research skill: honest reports, no overwritten reports, real sources

Found by reading `skills/research/skill.py` (and `billing` for the economy part); behaviours below are covered by unit tests with mocks.
- If `ask_llm` returns provider `"ninguno"` (no real model answer) the error text is saved as the report (`data/reports`, + .docx), announced as "Informe generado con N fuentes" and enters the history.
- No-source branch: the model error is labelled "conocimiento general del modelo".
- `webbrowser.open` result ignored: "abierto en tu editor/navegador" is always claimed.
- Report file = `<tema[:40]>-<fecha>.md`: a second report on the same topic the same day silently OVERWRITES the first (also topics sharing the first 40 chars).
- Search reads up to 4 pages one after another (slow) and search-engine ads can take those reads and be cited as sources. Sources are cited "por título" with no numbering.
- `open_report` opens the first partial match without saying others exist.
- Economy: the invoices table holds invoices ISSUED to clients (income, see `billing`), but they are handed to a "recortar gastos" prompt as if they were expenses, mixed unlabeled with expense notes; the header says "apuntes reales" although only the last 20 invoices / 12 notes are read.

## Tasks
- [x] T1 LLM-unavailable honesty (report, no-source branch, economy): nothing saved, no "generated" framing; show the sources read / the data found instead.
- [x] T2 Browser honesty for new and reopened reports.
- [x] T3 Report files never overwrite an earlier report.
- [x] T4 Parallel page reads with timeout and ad filtering (shared helpers `websearch.sin_ruido` / `websearch.leer_paginas`, also used by `ai_media`), numbered sources [n], cite-or-admit prompt, numbered "Fuentes".
- [x] T5 `open_report`: say when several reports match.
- [x] T6 Economy: label income (issued invoices) vs expenses (notes), no recortes advice without expenses, deterministic totals, state what was read (last 20 / 12).
- [ ] T7 Review, merge to main, docs.

## Evidence
(append commits and checks here)
- T1-T6 in `skills/research/skill.py`: provider `ninguno` -> nothing saved, sources shown, no "generated" framing (also no-source branch and economy); `_abrir` honest browser result (new and reopened reports); `_save_report` never overwrites (`…-2`, `…-3`); `websearch.sin_ruido` + `websearch.leer_paginas` (shared with `ai_media`, which now delegates to them): 5 pages in parallel, 8 s each, 4 cited, ads dropped, numbered `[n]` sources and cite-or-admit prompt, numbered "Fuentes" in the saved report; `open_report` opens the most recent match and names the others; economy: income (issued invoices) vs expense notes labelled, no recorte advice without expenses (deterministic income total + breakdown by status, no LLM call), header states what was read.
- Checks: `test_research_honesty.py` RED (15+ failures) -> GREEN 31/0; existing `test_skill_research` 75/0 and `test_source_evidence` 17/0; ai_media 41/0 after delegating to the shared helpers; pequenas_1 352, pequenas_2 84, frases_reales 212, routing 244, capas_backend 449.
- Not covered / open: the saved `.docx` path (python-docx) not exercised with the new numbered sources; economy keyword search ("gasto"/"pago") can still pick unrelated notes; amounts in expense notes are not parsed (no totals for expenses); real LLM report quality not evaluated.
