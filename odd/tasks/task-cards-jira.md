# Feature: Jira-like task cards and explicit mail-born tasks

Branch: harden-nexus-boundaries. Owner request (2026-10-03): tasks must be descriptive; critical urgency shows as
"alta" and other urgencies show nothing; behave similar to Jira; the promo group must not say just "Revisar promociones".

## Owner decisions
- Scope 1: rich card + detail panel (no filters/swimlanes/activity history yet).
- Promo group: ONE task, title with count and per-sender breakdown, e.g. "8 correos promocionales sin leer: AIlink (7),
  NaN Community (1)"; description lists each mail with sender, subject, date and Gmail link.
- Mail tasks: concrete title (verb + object + context/sender) and full description: what the mail asks, deadline,
  reason for urgency, sender, subject, date and Gmail link.

## Context (explored)
- frontend/js/command.js `views.tasks`: card shows `⚡ ALTA` only when legacy `priority === 'alta'` (critica maps to alta);
  media/baja/type/source/description are never shown.
- backend/core/dominio/board.py: tasks carry type, urgency, source, sourceId, sourceIds, description; no stable key.
- skills/google_workspace/skill.py: classifier prompt (tarea, motivo, tipo, urgencia, promocional), `_email_actions_job`
  builds notes "De X — Asunto: Y"; `board.add_to_group` sets title "Revisar promociones (N)".

## Tasks
- [x] J1 (commit ae1f755) — Stable task key (NX-<n>) assigned on creation and migrated for existing tasks; card shows key, type icon,
  urgency badge for all four levels (colors), source, due; uses `urgency`, not `priority`.
- [x] J2 (commit ae1f755) — Detail panel on card click: all fields, full description, mail sender/subject/date and Gmail link; existing
  edit/delete/move keep working; escaped output.
- [x] J3 (commit 680a9c8) — Mail tasks: classifier returns a concrete title and a short summary; description includes summary, deadline,
  urgency reason, sender, subject, date and Gmail link (`sourceUrl`).
- [x] J4 (commit 680a9c8) — Promo group title with count and per-sender breakdown, updated on append; description lines per mail with
  sender, subject, date, link.
- [x] J6 (commit cdd6e69; native review review-08360a59381fb4a1 approved+acknowledged, medium, 1 lens, warnings skill.py:1217 and test_inbox_scale.py:256-257; verifier: run_all green, hermetic E2E 9/9 twice, journeys 20/0, browser keyboard/panel check incl. refresh keeps panel open after a caught regression) — Minor follow-ups (owner, 2026-10-03): word-boundary title cap (~90 chars, ellipsis); `_remitente` cleans 'Name <addr>'; detail panel closes on view change; cards keyboard-focusable (Enter/Space opens panel); generic mail titles made explicit deterministically (append subject/sender when the title names neither).
- [ ] J5 — Docs, independent verification (run_all, hermetic E2E), native review per commit.

## Evidence
- Independent verifier: run_all green; hermetic container python green, E2E 9/9, user journeys 20/0; throwaway browser probe 20/20 (badges CRÍTICA/ALTA/MEDIA/BAJA, keys NX-1..7 unique, panel opens on card click and not on buttons, Escape/✕ close, line breaks kept, only http(s) links, javascript: URL rejected, XSS title inert).
- Real board enriched once (backup D:/tmp/nexus_dryrun/board.before-enrich.json): promo group NX-371 rebuilt from Gmail metadata ("8 correos promocionales sin leer: Agustín AILINK (7), Cristian de NaN (1)"), 3 individual tasks re-analyzed (concrete title for the security alert, structured descriptions, sourceUrl) and their Google Tasks copies patched.
- Follow-ups (minor): title cut at 120 chars mid-word (prompt asks 90, not enforced); `_remitente` returns raw text when it contains '@'; panel stays open on view change; cards not keyboard-focusable; InfoJobs titles still generic (model ignored the concreteness instruction).
