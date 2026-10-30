#!/usr/bin/env bash
# start.sh [datadir] -- (re)start a FRESH test container with a stub ntfy server inside it.
# The data dir is wiped first unless KEEP=1. Extra docker run arguments: $EXTRA (word-split).
# 2.45.0 (#1515): KALMIDO_SETUP_CODE=off unless set (the first setup needs no code from the log); KALMIDO_SETUP_CODE= tests the code.
# 2.149.0 D (#2510): KALMIDO_NO_SECRET_KEY=1 unless set (a new server without a server key may start); KALMIDO_NO_SECRET_KEY= tests the refusal.
# 2.190.0 B (#2592): KALMIDO_SECRET_KEY_CHANGED=1 unless set (suites start one data dir with their own random keys); KALMIDO_SECRET_KEY_CHANGED= tests the fingerprint check.
# 2.37.0 (#1150): the database is Postgres. A database container "<container>-db" (postgres:17, data in RAM, no published port)
# is started once and kept; every data dir gets its OWN database in it (name from the path), so a data dir and its database
# belong together like tasks.db did: without KEEP both start empty, with KEEP=1 both stay. The app reaches it via --link
# (no new docker network: address pools can be scarce). <datadir>/.kalmido-db names "<db container> <database>" for tests/dbx.py.
# Settings (environment, all optional):
#   KALMIDO_TEST_IMAGE      image to test                      (default kalmido:test)
#   KALMIDO_TEST_CONTAINER  container name                     (default kalmido-test)
#   KALMIDO_TEST_PORT       host port -> app port 3040          (default 3048, built-in login)
#   KALMIDO_TEST_PROXY_PORT host port -> proxy port 3045        (default 3041, trusts Remote-User)
#   KALMIDO_TEST_DATA       data dir, bind-mounted to /data    (default tests/.data)
#   KALMIDO_ONBOARDING      1 = sample list + welcome tour for new accounts (default 0: suites start from empty accounts)
#   KALMIDO_ADMIN_ALERTS    1 = admin alerts via ntfy on (default 0: they would add pushes to the admin's topic)
#   KALMIDO_TIDY_QUIET_S    seconds a new task waits for its tidy event (default 0 here: at once, as the suites before 2.27 expect)
#   KALMIDO_TEST_NOW        2.149.0 (#2512): ISO instant the server's clock starts at (default unset: the real time); the
#                           clock runs on from there. KALMIDO_TEST_NOW_AT = the real Unix second it stands for (default: now).
#                           The container always gets KALMIDO_TEST=1, without it the app ignores KALMIDO_TEST_NOW
#   KALMIDO_LOGIN_SLOW_S    2.282.0 (#3111): delay of sign-ins above the address limit (default 0.3 here, the app: 2.5)
#   KALMIDO_NOTIF_TEMPLATE  notification template of a share without one (default all here: the suites before 2.33 expect every push; the app itself starts with read)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMG=${KALMIDO_TEST_IMAGE:-kalmido:test}
NAME=${KALMIDO_TEST_CONTAINER:-kalmido-test}
PORT=${KALMIDO_TEST_PORT:-3048}
PPORT=${KALMIDO_TEST_PROXY_PORT:-3041}
D=${1:-${KALMIDO_TEST_DATA:-$HERE/.data}}
# 2.138.4: stop the old container first - it may still write attachments while the data dir is removed (CI shard 15 race)
docker rm -f "$NAME" >/dev/null 2>&1 || true
[[ -n "${KEEP:-}" ]] || { rm -rf "$D"; }
mkdir -p "$D"
cp "$HERE/stub_ntfy.py" "$D/"
# The app sees the host through the docker bridge gateway (docker-proxy), so that is the "trusted proxy".
GW=$(docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null)
[[ -n "$GW" ]] || { echo "no docker bridge gateway found" >&2; exit 1; }
DBC=${KALMIDO_TEST_DB_CONTAINER:-$NAME-db}
DBN=k$(printf '%s' "$(cd "$D" && pwd)" | md5sum | cut -c1-15)
if [[ -z "$(docker ps -q -f "name=^${DBC}$")" ]]; then
  docker rm -f "$DBC" >/dev/null 2>&1 || true
  docker run -d --name "$DBC" --network bridge -e POSTGRES_USER=kalmido -e POSTGRES_PASSWORD=kalmido -e POSTGRES_DB=kalmido \
    --tmpfs /var/lib/postgresql/data postgres:17 -c fsync=off -c synchronous_commit=off -c full_page_writes=off \
    -c max_connections=200 >/dev/null || exit 1
  for _ in $(seq 1 60); do docker exec "$DBC" pg_isready -U kalmido -d kalmido -q 2>/dev/null && break; sleep 0.5; done
  sleep 1  # the image restarts the server once after its first init
  for _ in $(seq 1 60); do docker exec "$DBC" psql -U kalmido -d kalmido -Atqc "SELECT 1" >/dev/null 2>&1 && break; sleep 0.5; done
fi
PSQL=(docker exec "$DBC" psql -U kalmido -d kalmido -v ON_ERROR_STOP=1 -Atq)
# KEEP=1 on a wiped data dir (no .kalmido-db: suites that rm -rf it first) = empty database, as a missing tasks.db was
if [[ -n "${KEEP:-}" && -f "$D/.kalmido-db" ]]; then
  [[ "$("${PSQL[@]}" -c "SELECT 1 FROM pg_database WHERE datname='$DBN'")" == 1 ]] || "${PSQL[@]}" -c "CREATE DATABASE $DBN" >/dev/null || exit 1
else
  "${PSQL[@]}" -c "DROP DATABASE IF EXISTS $DBN WITH (FORCE)" -c "CREATE DATABASE $DBN" >/dev/null || exit 1
fi
echo "$DBC $DBN" > "$D/.kalmido-db"
# 2.37.0 (review W2-4 / W2-2): KALMIDO_TEST_DB_LOGIN=owner|bypass -- the app logs in as its own role instead of the image's
# superuser: "owner" = owner of the database without superuser / BYPASSRLS (the policies hold for it through FORCE),
# "bypass" = owner with BYPASSRLS but without the right to create roles. Unset: the superuser (every standard run).
DBU=kalmido
if [[ -n "${KALMIDO_TEST_DB_LOGIN:-}" ]]; then
  case "$KALMIDO_TEST_DB_LOGIN" in
    owner) ATTR="NOSUPERUSER NOBYPASSRLS NOCREATEROLE" ;;
    bypass) ATTR="NOSUPERUSER BYPASSRLS NOCREATEROLE" ;;
    *) echo "KALMIDO_TEST_DB_LOGIN: owner or bypass" >&2; exit 1 ;;
  esac
  DBU=k_$KALMIDO_TEST_DB_LOGIN
  "${PSQL[@]}" -c "DO \$\$BEGIN CREATE ROLE $DBU LOGIN PASSWORD 'kalmido'; EXCEPTION WHEN duplicate_object THEN NULL; END\$\$" \
    -c "ALTER ROLE $DBU LOGIN $ATTR" -c "ALTER DATABASE $DBN OWNER TO $DBU" >/dev/null || exit 1
fi
# 2.149.0 E (#2512): the test clock (run_all.sh `now <instant>; fresh`)
TNOW=(-e KALMIDO_TEST=1)
# 2.235.0 A (#2891): a new agent of the test container has no control level (works as before); the control suites ask for approve_all
TNOW+=(-e "KALMIDO_AGENT_CONTROL_NEW=${KALMIDO_AGENT_CONTROL_NEW:-legacy}")
[[ -z "${KALMIDO_TEST_NOW:-}" ]] || TNOW+=(-e "KALMIDO_TEST_NOW=$KALMIDO_TEST_NOW" -e "KALMIDO_TEST_NOW_AT=${KALMIDO_TEST_NOW_AT:-$(date +%s)}")
# shellcheck disable=SC2086
docker run -d --name "$NAME" --network bridge --user "$(id -u):$(id -g)" --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp \
  -e TZ=Europe/Berlin "${TNOW[@]}" -e TASKS_DB=/data/tasks.db -e PUBLIC_URL=https://kalmido.example \
  --link "$DBC:db" -e DATABASE_URL="postgresql://$DBU:kalmido@db/$DBN" \
  -e AUTH_PROXY_HEADER=Remote-User -e AUTH_TRUSTED_PROXIES="$GW" -e AUTH_PROXY_PORT=3045 \
  -e KALMIDO_SETUP_CODE="${KALMIDO_SETUP_CODE-off}" -e KALMIDO_NO_SECRET_KEY="${KALMIDO_NO_SECRET_KEY-1}" -e KALMIDO_SECRET_KEY_CHANGED="${KALMIDO_SECRET_KEY_CHANGED-1}" \
  -e KALMIDO_UPDATE_CHECK=0 -e KALMIDO_ONBOARDING="${KALMIDO_ONBOARDING:-0}" -e KALMIDO_ADMIN_ALERTS="${KALMIDO_ADMIN_ALERTS:-0}" -e NTFY_URL=http://127.0.0.1:9999 -e TASKS_PUSH_GAP=3 -e TASKS_WATCHDOG_INTERVAL=1 -e KALMIDO_TIDY_QUIET_S=${KALMIDO_TIDY_QUIET_S:-0} -e KALMIDO_LOGIN_SLOW_S=${KALMIDO_LOGIN_SLOW_S:-0.3} -e KALMIDO_NOTIF_TEMPLATE=${KALMIDO_NOTIF_TEMPLATE:-all} -e TASKS_MAX_FILE_MB=1 \
  -p "127.0.0.1:$PPORT:3045" -p "127.0.0.1:$PORT:3040" -v "$D":/data ${EXTRA:-} "$IMG" 2>&1 >/dev/null | { grep -v "Links on the default bridge" >&2 || true; }
[[ ${PIPESTATUS[0]} -eq 0 ]] || exit 1  # (the --link deprecation warning is noise here)
# START_WAIT_S (#3506): an upgrade from an old dump runs every migration at the first start - it may take longer than 30 s
for _ in $(seq 1 $(( ${START_WAIT_S:-30} * 2 ))); do
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null; then
    docker exec -d "$NAME" python /data/stub_ntfy.py
    sleep 0.7
    exit 0
  fi
  sleep 0.5
done
echo "test container did not come up (${START_WAIT_S:-30} s)" >&2
docker logs "$NAME" 2>&1 | tail -20 >&2
docker top "$NAME" 2>&1 | tail -5 >&2
exit 1
