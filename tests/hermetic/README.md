# Hermetic profile

Runs the Python suites against a clean copy of `HEAD` in a container with no network
(`tests/hermetic/run.sh [suite]`). Last full run: `tests/run_all.py` exit 0, all green.

Notes:
- Host-only behavior is simulated in the tests (Windows registry/paths, generated
  `config/docker-compose.yml`, live Postgres), so the suites do not depend on them.
- `test_skill_system_pc` runs 320 checks here versus 322 on Windows (platform-dependent branches).
- Without Postgres some DB checks are skipped; they remain unproven in this profile.
- This is not proof of device, browser/E2E or provider behavior.
