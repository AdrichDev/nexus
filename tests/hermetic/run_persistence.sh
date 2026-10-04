#!/usr/bin/env bash
# P1-07: persistence probe against a DISPOSABLE pgvector container on an internal
# (no-internet) docker network. Never touches nexus_memoria_postgres or its volume.
# Also runs the DB-dependent memory suites with the database online.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
TMP="$(mktemp -d)"; NET=nexus-probe-net; PG=nexus-probe-pg; VOL=nexus-probe-vol
cleanup() { docker rm -f "$PG" >/dev/null 2>&1; docker volume rm "$VOL" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; rm -rf "$TMP"; }
trap cleanup EXIT
git -C "$ROOT" archive HEAD | tar -x -C "$TMP"
W="$(cd "$TMP" && pwd -W 2>/dev/null || pwd)"
docker network create --internal "$NET" >/dev/null
docker volume create "$VOL" >/dev/null
docker run -d --name "$PG" --network "$NET" -v "$VOL:/var/lib/postgresql/data" \
  -e POSTGRES_USER=nexus_probe -e POSTGRES_PASSWORD=probe -e POSTGRES_DB=probe pgvector/pgvector:pg16 >/dev/null
wait_pg() { for i in $(seq 1 40); do docker exec "$PG" pg_isready -U nexus_probe -d probe >/dev/null 2>&1 && return 0; sleep 1; done; return 1; }
wait_pg || { echo "postgres did not start"; exit 2; }
sleep 2
run() { MSYS_NO_PATHCONV=1 docker run --rm --network "$NET" --read-only --tmpfs /tmp:uid=10001 --tmpfs /work:exec,uid=10001 \
  -e NEXUS_DB_URL="postgresql://nexus_probe:probe@$PG:5432/probe" -e NEXUS_DATA_DIR=/tmp/nexus_data \
  -v "$W:/src:ro" -w /work nexus-hermetic-test sh -c "cp -r /src/. /work/ && $1"; }
rc=0
echo "#### write"; run "python tests/hermetic/probe_persistence.py write" || rc=1
echo "#### restarting postgres"; docker restart "$PG" >/dev/null; wait_pg || { echo "no restart"; exit 2; }; sleep 2
echo "#### read"; run "python tests/hermetic/probe_persistence.py read" || rc=1
echo "#### purge/restore"; run "python tests/hermetic/probe_persistence.py purge" || rc=1
for s in unit/memory/test_purga.py unit/memory/test_memoria_embeddings.py unit/memory/test_ingesta_documentos.py unit/memory/test_skill_memory_graph.py; do
  echo "#### suite $s"; run "python tests/$s" 2>&1 | tail -6; [ "${PIPESTATUS[0]}" -eq 0 ] || rc=1
done
exit $rc
