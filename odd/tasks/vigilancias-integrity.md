# vigilancias skill: no silent data loss, no misleading promises

Found auditing the skill (temp watchers file, no network) and reproduced:
- Race: `check_watchers` loads the list, awaits the network, then `_save(items)` overwrites the file. A watcher removed (or added) while a check is running comes back / is lost.
- `deja de vigilar a` removes the first watcher whose URL merely contains "a" (no ambiguity check).
- The same URL can be watched twice (#1, #2) -> double alerts.
- The reply always promises "HUD y Telegram" even when Telegram is not configured.
- A price/web watcher is only validated by a later `mis vigilancias`: if the page has no price or cannot be read nothing is ever proactively said.
- If a page stops being readable after a first success, nothing is ever said.

## Tasks
- [x] T1 Race-safe persistence: re-read the file before saving and merge only `estado`/`ultima` into watchers that still exist; atomic write.
- [x] T2 Duplicates: same tipo+objetivo -> "ya vigilo eso (#N)".
- [x] T3 Remove by text: unique match removes; several matches -> list them and ask for the number; none -> not found.
- [x] T4 Honest channels: mention Telegram only when configured.
- [x] T5 Health notice: at the FIRST check, if a price watcher finds no price or a web watcher cannot read the page, notify once ("no encuentro un precio / no consigo leer ..."); a successful first check stays silent. Creation stays instant and offline (the existing contract: new watchers list as "sin comprobar").
- [x] T6 Failure streak: after 3 consecutive failed checks (unreadable page, no price, exception) notify once; reset on success so a later streak notifies again.
- [ ] T7 Review, merge to main, update docs.

Out of scope (noted): no guard against internal/loopback URLs in `fetch_page` (may be intended for a personal app); first price on the page may not be the product price (reply says "primer precio que leo").

## Evidence
(append commits and checks here)
- T1-T6 in `skills/vigilancias/skill.py`: `_guardar_estados` merges only `estado`/`ultima` of the checked watchers into the CURRENT file (matching num+tipo+objetivo) and `_save` is atomic (tmp + replace); `_buscar` rejects duplicates (same tipo + normalized objetivo); remove: a number is only `[la vigilancia|web] [#]N` (URLs ending in digits are text), several text matches -> lists candidates and asks; `_canales()` promises Telegram only when `_token()` and `OWNER_FILE` exist; `_salud` notifies once per failure streak (first check, or 3 consecutive failures; exceptions count; success re-arms).
- Also found while testing: the old number rule `#?(\d+)$` made `deja de vigilar https://…/p2` delete watcher #2. Fixed in T3.
- Checks: `test_vigilancias_integrity.py` RED 15 (+1 found later) failures -> GREEN 19/0; existing `test_skill_vigilancias.py` 70/0; mejoras_v19 69, specs_v20 99, pequenas_1 355, frases_reales 212, capas_backend 449, runner profiles 510.
- Not covered / open: no guard against loopback/internal URLs in `fetch_page`; first price found on a page may not be the product price; Google News watcher with zero results is not counted as a failure; new watchers reuse the number of a just-deleted highest one.
