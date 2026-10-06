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
- [ ] T1 LLM-unavailable honesty (report, no-source branch, economy): nothing saved, no "generated" framing; show the sources read / the data found instead.
- [ ] T2 Browser honesty for new and reopened reports.
- [ ] T3 Report files never overwrite an earlier report.
- [ ] T4 Parallel page reads with timeout and ad filtering (shared helpers `websearch.sin_ruido` / `websearch.leer_paginas`, also used by `ai_media`), numbered sources [n], cite-or-admit prompt, numbered "Fuentes".
- [ ] T5 `open_report`: say when several reports match.
- [ ] T6 Economy: label income (issued invoices) vs expenses (notes), no recortes advice without expenses, deterministic totals, state what was read (last 20 / 12).
- [ ] T7 Review, merge to main, docs.

## Evidence
(append commits and checks here)
