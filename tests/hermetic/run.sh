#!/usr/bin/env bash
# Run the Python suite from a clean `git archive HEAD` copy inside a throwaway
# container: no network, read-only root, no .env/settings/data (they are not in git).
# Usage: tests/hermetic/run.sh [tests/some_suite.py]   (default: tests/run_all.py)
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git -C "$ROOT" archive HEAD | tar -x -C "$TMP"
docker build -q -t nexus-hermetic-test -f "$ROOT/tests/hermetic/Dockerfile" "$ROOT/tests/hermetic"
MSYS_NO_PATHCONV=1 docker run --rm --network none --read-only --tmpfs /tmp \
  --tmpfs /work:exec -v "$(cd "$TMP" && pwd -W 2>/dev/null || pwd):/src:ro" -w /work \
  nexus-hermetic-test sh -c "cp -r /src/. /work/ && python ${1:-tests/run_all.py}"
