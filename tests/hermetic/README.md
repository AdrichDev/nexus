# Hermetic profile

Runs the Python suites against a clean copy of `HEAD` in a container with no network
(`tests/hermetic/run.sh [suite]`). Last full run: `tests/run_all.py` exit 0, all green.

Notes:
- Host-only behavior is simulated in the tests (Windows registry/paths, generated
  `config/docker-compose.yml`, live Postgres), so the suites do not depend on them.
- `test_skill_system_pc` runs 320 checks here versus 322 on Windows (platform-dependent branches).
- Without Postgres some DB checks are skipped; they remain unproven in this profile.
- This is not proof of device, browser/E2E or provider behavior.

## Startup probe
`docker run ... python tests/hermetic/probe_startup.py` (see script header) starts the real backend inside the container and checks the core journey. Run it through the same clean-copy mechanism as `run.sh`.

## Browser E2E
`Dockerfile.e2e` extends the image with Playwright + Chromium (network only at build time).
Run `tests/e2e/run_e2e.py` from a clean `git archive HEAD` copy with `--network none --read-only
--tmpfs /tmp --tmpfs /work:exec --shm-size=512m`, mounting a volume to collect `data/e2e`.
Last run: 9/9 flows passed in 58 s; the only console error was the blocked Google Fonts stylesheet
(external dependency of `frontend/index.html`, harmless offline). Synthetic jobs/analytics fixtures
apply; this is not provider or device evidence.
