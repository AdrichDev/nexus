# vigilancias skill: no silent data loss, no misleading promises

Found auditing the skill (temp watchers file, no network) and reproduced:
- Race: `check_watchers` loads the list, awaits the network, then `_save(items)` overwrites the file. A watcher removed (or added) while a check is running comes back / is lost.
- `deja de vigilar a` removes the first watcher whose URL merely contains "a" (no ambiguity check).
- The same URL can be watched twice (#1, #2) -> double alerts.
- The reply always promises "HUD y Telegram" even when Telegram is not configured.
- A price/web watcher is only validated by a later `mis vigilancias`: if the page has no price or cannot be read nothing is ever proactively said.
- If a page stops being readable after a first success, nothing is ever said.

## Tasks
- [ ] T1 Race-safe persistence: re-read the file before saving and merge only `estado`/`ultima` into watchers that still exist; atomic write.
- [ ] T2 Duplicates: same tipo+objetivo -> "ya vigilo eso (#N)".
- [ ] T3 Remove by text: unique match removes; several matches -> list them and ask for the number; none -> not found.
- [ ] T4 Honest channels: mention Telegram only when configured.
- [ ] T5 Health notice: at the FIRST check, if a price watcher finds no price or a web watcher cannot read the page, notify once ("no encuentro un precio / no consigo leer ..."); a successful first check stays silent. Creation stays instant and offline (the existing contract: new watchers list as "sin comprobar").
- [ ] T6 Failure streak: after 3 consecutive failed checks (unreadable page, no price, exception) notify once; reset on success so a later streak notifies again.
- [ ] T7 Review, merge to main, update docs.

Out of scope (noted): no guard against internal/loopback URLs in `fetch_page` (may be intended for a personal app); first price on the page may not be the product price (reply says "primer precio que leo").

## Evidence
(append commits and checks here)
