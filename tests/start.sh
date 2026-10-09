#!/usr/bin/env bash
# start.sh [datadir] -- (re)start a FRESH test container with a stub ntfy server inside it.
# The data dir is wiped first unless KEEP=1. Extra docker run arguments: $EXTRA (word-split).
# Settings (environment, all optional):
#   KALMIDO_TEST_IMAGE      image to test                      (default kalmido:test)
#   KALMIDO_TEST_CONTAINER  container name                     (default kalmido-test)
#   KALMIDO_TEST_PORT       host port -> app port 3040          (default 3048, built-in login)
#   KALMIDO_TEST_PROXY_PORT host port -> proxy port 3045        (default 3041, trusts Remote-User)
#   KALMIDO_TEST_DATA       data dir, bind-mounted to /data    (default tests/.data)
#   KALMIDO_ONBOARDING      1 = sample list + welcome tour for new accounts (default 0: suites start from empty accounts)
#   KALMIDO_ADMIN_ALERTS    1 = admin alerts via ntfy on (default 0: they would add pushes to the admin's topic)
#   KALMIDO_TIDY_QUIET_S    seconds a new task waits for its tidy event (default 0 here: at once, as the suites before 2.27 expect)
#   KALMIDO_NOTIF_TEMPLATE  notification template of a share without one (default all here: the suites before 2.33 expect every push; the app itself starts with read)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMG=${KALMIDO_TEST_IMAGE:-kalmido:test}
NAME=${KALMIDO_TEST_CONTAINER:-kalmido-test}
PORT=${KALMIDO_TEST_PORT:-3048}
PPORT=${KALMIDO_TEST_PROXY_PORT:-3041}
D=${1:-${KALMIDO_TEST_DATA:-$HERE/.data}}
[[ -n "${KEEP:-}" ]] || { rm -rf "$D"; }
mkdir -p "$D"
cp "$HERE/stub_ntfy.py" "$D/"
# The app sees the host through the docker bridge gateway (docker-proxy), so that is the "trusted proxy".
GW=$(docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null)
[[ -n "$GW" ]] || { echo "no docker bridge gateway found" >&2; exit 1; }
docker rm -f "$NAME" >/dev/null 2>&1 || true
# shellcheck disable=SC2086
docker run -d --name "$NAME" --network bridge --user "$(id -u):$(id -g)" --security-opt no-new-privileges:true --cap-drop ALL \
  -e TZ=Europe/Berlin -e TASKS_DB=/data/tasks.db -e PUBLIC_URL=https://kalmido.example \
  -e AUTH_PROXY_HEADER=Remote-User -e AUTH_TRUSTED_PROXIES="$GW" -e AUTH_PROXY_PORT=3045 \
  -e KALMIDO_UPDATE_CHECK=0 -e KALMIDO_ONBOARDING="${KALMIDO_ONBOARDING:-0}" -e KALMIDO_ADMIN_ALERTS="${KALMIDO_ADMIN_ALERTS:-0}" -e NTFY_URL=http://127.0.0.1:9999 -e TASKS_PUSH_GAP=3 -e TASKS_WATCHDOG_INTERVAL=1 -e KALMIDO_TIDY_QUIET_S=${KALMIDO_TIDY_QUIET_S:-0} -e KALMIDO_NOTIF_TEMPLATE=${KALMIDO_NOTIF_TEMPLATE:-all} -e TASKS_MAX_FILE_MB=1 \
  -p "127.0.0.1:$PPORT:3045" -p "127.0.0.1:$PORT:3040" -v "$D":/data ${EXTRA:-} "$IMG" >/dev/null || exit 1
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null; then
    docker exec -d "$NAME" python /data/stub_ntfy.py
    sleep 0.7
    exit 0
  fi
  sleep 0.5
done
echo "test container did not come up" >&2
docker logs "$NAME" 2>&1 | tail -20 >&2
exit 1
