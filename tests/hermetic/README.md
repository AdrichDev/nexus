# Hermetic profile

Runs the Python suites against a clean copy of `HEAD` in a container with no network.

Known failures in this profile (environment, not product defects; open work):
- `test_skill_system_pc` (3): Windows registry / App Paths Chrome fallback.
- `test_skill_autoprovision` (1): needs the generated, git-ignored `config/docker-compose.yml`.
- `test_purga` (1): cause not yet confirmed; Postgres is absent here (other checks are skipped).
