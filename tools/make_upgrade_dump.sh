#!/usr/bin/env bash
# 2.192.0 C (#2514): builds the upgrade fixture tests/fixtures/upgrade/<version>.sql.gz (+ .json) from an OLDER release:
# the release's tree (git archive of its tag) is built as its own image, started with ITS tests/start.sh on an empty
# database, filled by tests/upgrade_seed.py (invented data only, addresses @example.com) and dumped with pg_dump.
# The suite p2192_c_upgrade_test.py loads every dump in that folder and starts the current server on it.
#   tools/make_upgrade_dump.sh v2.101.0          (needs docker and git; run from anywhere inside the repo)
# Settings: UPG_PORT (default 3290, the old server's port), UPG_KEEP=1 keeps the temp folder, image and containers.
# Another way without a local docker: copy upgrade_seed.py into the old tree, run it there as a suite with
# P2192C_DUMP_SHOTS=<folder> (it writes <version>.sql.gz + .json into that folder), copy both into tests/fixtures/upgrade/.
set -euo pipefail
TAG=${1:?usage: make_upgrade_dump.sh <tag of an older release, e.g. v2.101.0>}
ROOT=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
OUTD=$ROOT/tests/fixtures/upgrade
VER=$(git -C "$ROOT" show "$TAG:VERSION" | tr -d '[:space:]')
TMP=$(mktemp -d "${TMPDIR:-/tmp}/kalmido-upg.XXXXXX")
IMG=kalmido:upgrade-$VER CT=kalmido-upgrade-dump
cleanup() {
  [[ -n "${UPG_KEEP:-}" ]] && { echo "kept: $TMP, image $IMG, containers $CT $CT-db" >&2; return; }
  docker rm -f "$CT" "$CT-db" >/dev/null 2>&1 || true
  docker image rm "$IMG" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
mkdir -p "$TMP/src" "$OUTD"
git -C "$ROOT" archive "$TAG" | tar -x -C "$TMP/src"
cp "$ROOT/tests/upgrade_seed.py" "$TMP/src/tests/"
echo "building $IMG from $TAG ..." >&2
docker build -q -t "$IMG" "$TMP/src" >/dev/null
docker rm -f "$CT-db" >/dev/null 2>&1 || true
KALMIDO_TEST_IMAGE=$IMG KALMIDO_TEST_CONTAINER=$CT KALMIDO_TEST_PORT=${UPG_PORT:-3290} \
  KALMIDO_TEST_PROXY_PORT=$((${UPG_PORT:-3290} + 1)) bash "$TMP/src/tests/start.sh" "$TMP/data"
( cd "$TMP/src/tests" && KALMIDO_TEST_PORT=${UPG_PORT:-3290} KALMIDO_TEST_CONTAINER=$CT \
    P2192C_DUMP_SHOTS="$OUTD" python3 upgrade_seed.py "$TMP/data" )
ls -l "$OUTD/$VER.sql.gz" "$OUTD/$VER.json"
