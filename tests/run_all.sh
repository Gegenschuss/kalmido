#!/usr/bin/env bash
# run_all.sh -- every suite, each group against a fresh test container (see start.sh for the settings).
#   BUILD=1 tests/run_all.sh     build the image from the repo first (docker build -t $KALMIDO_TEST_IMAGE .)
#   tests/run_all.sh --shard 2/6  only the second of the 6 shards (CI runs the shards as parallel jobs, see ci.yml).
#                                The `shard N` lines below split the groups; each group (a `fresh` container and the
#                                suites after it) stays whole. Keep the shards about equal (~14 min each on CI) by moving
#                                a marker when one grows; new suites go at the end (the last shard).
#   ONLY="a b" tests/run_all.sh   just these suites (the containers of their groups are still started)
#   The suite list (2.321, #1368): tests/suites.txt holds the old `run` lines; a NEW suite only needs a marker line in its
#                                test file (`# kalmido-suite: ...` / `// kalmido-suite: ...`, see tests/suites.py) - no list
#                                to append to, so parallel packages no longer conflict here.
#   ONLY_GROUPS="a b" tests/run_all.sh  2.149.0 (#2514): the whole groups of these suites (every suite of each group, in order;
#                                the other groups start no container) - the CI rerun: a suite that needs the state of the
#                                one before it (news_ui after api) passes alone too
#   now wed 10:00; fresh; run ...  2.149.0 (#2512): this group runs at that test time (an ISO instant, HH:MM today or
#                                mon..sun HH:MM of this week, Berlin): KALMIDO_TEST_NOW for the server (start.sh) and for the
#                                suites (testclock), the clock runs on from there; the other groups run at the real time (or at
#                                a KALMIDO_TEST_NOW set for the whole run)
#                                2.192.0 A (#2512): the JS suites too - tests/boot.js shifts Date in Node and in every jsdom window
#                                (JSDOM.fromURL; own `new JSDOM` windows: testClock(w)) by the same offset, testNow() for suites
#                                2.206.0 A (#2512): `now real; fresh; run ...` = this group always at the real time (TOTP, fake
#                                services with their own clock, real-time JWTs), also when KALMIDO_TEST_NOW is set for the whole run
#   Timings: every suite and every group (container start included) -> $KALMIDO_TIMINGS (default tests/timings.csv, appended:
#                                shard,group,suite,seconds,rc; group = its first suite, suite "*" = the whole group); tools/shards.py
# Needs: docker, python3 with tests/requirements.txt, node 18+ with `npm ci` done in tests/.
# Exit code 0 = everything passed.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export KALMIDO_TEST_IMAGE=${KALMIDO_TEST_IMAGE:-kalmido:test}
export KALMIDO_TEST_DATA=${KALMIDO_TEST_DATA:-$HERE/.data}
PY=${PYTHON:-python3}
SHARDS_DEFINED=21
# 2.179 (#2691): KALMIDO_SHARD_PLAN=<file> replaces the `shard N` markers: one line "<first suite of a group> <shard>" per
#   group (tools/shards.py --assign, CI builds it from the suite times of the last run, see ci.yml job "plan"); the number of
#   shards is the highest one in the file. Every group must be in it (else exit 2), the markers are ignored then.
#   KALMIDO_LIST_ONLY=1: only print the suites a shard would run (no container, nothing run) - to check a plan
#   2.180.0 A (#2695): a plan that starts with the line "# stage push" (tools/shards.py --only, the push stage) holds only the
#   chosen groups: the groups not in it run in no shard. Without that line a missing group still stops the run (exit 2).
#   CI of 2.166.1 (job #945): a group ends only at the next `fresh`, a `shard N` marker does not end it - six markers without
#   `fresh` after them glued 54 suites into the group p208_ui (> 45 min, shard 2 cancelled in every run) and 38 into p2151_ui;
#   every marker is followed by `fresh` now (tools/shards.py warns when one is not)
#   CI of 2.168.4 (job #1052): the group p2180_git_api still held 29 suites (2.18-2.29, > 50 min, shard 1 cancelled in 2.168.3
#   and 2.168.4); every API suite there restarts its own container, so each starts its own group now (`fresh`)
# 2.321 (#1368): the suite list = tests/suites.txt + the test files with a `kalmido-suite:` marker (tests/suites.py --bash)
LIST=$("$PY" "$HERE/suites.py" --bash) || { echo "run_all.sh: tests/suites.py failed (python3 tests/suites.py --check)"; exit 2; }
declare -A PLAN=(); PLAN_STAGE=
if [[ -n "${KALMIDO_SHARD_PLAN:-}" ]]; then
  [[ -s "$KALMIDO_SHARD_PLAN" ]] || { echo "run_all.sh: KALMIDO_SHARD_PLAN $KALMIDO_SHARD_PLAN is missing or empty"; exit 2; }
  SHARDS_DEFINED=0
  while read -r g n; do
    [[ "$g $n" == "# stage push" ]] && PLAN_STAGE=push
    [[ -n "$g" && "$g" != \#* ]] || continue
    [[ "$n" =~ ^[0-9]+$ && $n -ge 1 ]] || { echo "run_all.sh: bad line in $KALMIDO_SHARD_PLAN: $g $n"; exit 2; }
    PLAN[$g]=$n; (( n > SHARDS_DEFINED )) && SHARDS_DEFINED=$n
  done < "$KALMIDO_SHARD_PLAN"
  [[ ${#PLAN[@]} -gt 0 ]] || { echo "run_all.sh: no group in $KALMIDO_SHARD_PLAN"; exit 2; }
fi
# the list mode starts no container, so the clean-up at the end must not hit a real one either
[[ -n "${KALMIDO_LIST_ONLY:-}" ]] && export KALMIDO_TEST_CONTAINER=kalmido-list-only-none KALMIDO_TEST_DB_CONTAINER=kalmido-list-only-none-db
SHARD=0; CUR=1
if [[ "${1:-}" == "--shard" ]]; then
  [[ "${2:-}" =~ ^([0-9]+)/([0-9]+)$ ]] || { echo "usage: run_all.sh [--shard N/$SHARDS_DEFINED]"; exit 2; }
  SHARD=${BASH_REMATCH[1]}
  [[ ${BASH_REMATCH[2]} -eq $SHARDS_DEFINED && $SHARD -ge 1 && $SHARD -le $SHARDS_DEFINED ]] \
    || { echo "run_all.sh: the markers (or KALMIDO_SHARD_PLAN) define $SHARDS_DEFINED shards (--shard 1/$SHARDS_DEFINED .. $SHARDS_DEFINED/$SHARDS_DEFINED)"; exit 2; }
fi
shard() { [[ ${#PLAN[@]} -gt 0 ]] || CUR=$1; }
# 2.149.0 E (#2514): groups by number (one per `fresh` line, the same count as tools/shards.py): GFIRST = first suite of each,
# WANT_G = the groups ONLY_GROUPS asks for. Called from fresh, mine() opens the next group (timing, test time).
GI=0; GT0=0; GRAN=; NEXT_NOW=; BASE_NOW=${KALMIDO_TEST_NOW:-}; GFIRST=(); WANT_G=
TIMINGS=${KALMIDO_TIMINGS:-$HERE/timings.csv}
while read -r g n; do
  [[ -n "${GFIRST[$g]:-}" ]] || GFIRST[$g]=$n
  [[ -n "${ONLY_GROUPS:-}" && " $ONLY_GROUPS " == *" $n "* && "$WANT_G " != *" $g "* ]] && WANT_G+=" $g"
done < <(awk '/^(now [^;]*; *)?fresh;/ {g++}
  /^(now [^;]*; *)?(fresh;)?[ \t]*run [A-Za-z0-9_]+ / {s = $0; sub(/^(now [^;]*; *)?(fresh;)?[ \t]*run /, "", s); sub(/ .*/, "", s); print g, s}' \
  <<< "$LIST")
if [[ ${#PLAN[@]} -gt 0 && -z "$PLAN_STAGE" ]]; then
  for g in "${!GFIRST[@]}"; do
    [[ -n "${PLAN[${GFIRST[$g]}]:-}" ]] || { echo "run_all.sh: group ${GFIRST[$g]} is not in $KALMIDO_SHARD_PLAN (plan older than run_all.sh?)"; exit 2; }
  done
fi
if [[ -n "${ONLY_GROUPS:-}" ]]; then [[ -n "$WANT_G" ]] || { echo "ONLY_GROUPS: no such suite in run_all.sh"; exit 2; }; WANT_G+=" "; fi
_ms() { local t=${EPOCHREALTIME:-}; [[ -n "$t" ]] || { echo $((SECONDS * 1000)); return; }; t=${t/,/.}; local f=${t#*.}000
  echo $(( ${t%.*} * 1000 + 10#${f:0:3} )); }
_timing() {  # _timing <suite> <ms> <rc>
  [[ -f "$TIMINGS" ]] || echo "shard,group,suite,seconds,rc" > "$TIMINGS" 2>/dev/null || return 0
  printf '%s,%s,%s,%d.%03d,%s\n' "$SHARD" "${GFIRST[$GI]:-g$GI}" "$1" $(($2 / 1000)) $(($2 % 1000)) "$3" >> "$TIMINGS" 2>/dev/null || true
}
_group_end() { [[ -n "$GRAN" ]] && _timing "*" $(( $(_ms) - GT0 )) ""; GRAN=; }
now() { NEXT_NOW="$*"; }  # now <when>: the test time of the next group (#2512), see _now_iso; `now real`: the real time (2.206.0 A)
_now_iso() {  # <ISO instant> | HH:MM (today in Berlin) | mon..sun HH:MM (that day of this Monday-Sunday week in Berlin)
  [[ "$*" == *T* ]] && { echo "$*"; return 0; }
  "$PY" - "$@" <<'PY'
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
a, tz = sys.argv[1:], ZoneInfo("Europe/Berlin")
d = datetime.now(tz).date()
if len(a) == 2:
    d += timedelta(days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(a[0].lower()[:3]) - d.weekday())
h, m = (int(x) for x in a[-1].split(":"))
print(datetime(d.year, d.month, d.day, h, m, tzinfo=tz).isoformat())
PY
}
mine() {
  if [[ "${FUNCNAME[1]:-}" == fresh ]]; then
    _group_end; GI=$((GI + 1)); GT0=$(_ms)
    if [[ "$NEXT_NOW" == real ]]; then unset KALMIDO_TEST_NOW KALMIDO_TEST_NOW_AT  # 2.206.0 A (#2512): real time, also under a run-wide test time
    elif [[ -n "${NEXT_NOW:-$BASE_NOW}" ]]; then
      KALMIDO_TEST_NOW=$(_now_iso ${NEXT_NOW:-$BASE_NOW}) || { echo "run_all.sh: now ${NEXT_NOW:-$BASE_NOW}: not a time"; exit 2; }
      export KALMIDO_TEST_NOW KALMIDO_TEST_NOW_AT=$(date +%s)
    else unset KALMIDO_TEST_NOW KALMIDO_TEST_NOW_AT; fi
    NEXT_NOW=
    [[ ${#PLAN[@]} -gt 0 ]] && CUR=${PLAN[${GFIRST[$GI]}]:-0}  # 0: not in a push stage plan (#2695)
    [[ -n "${KALMIDO_LIST_ONLY:-}" ]] && return 1  # no container in the list mode
  fi
  [[ $CUR -gt 0 ]] && [[ $SHARD -eq 0 || $CUR -eq $SHARD ]] && [[ -z "$WANT_G" || "$WANT_G" == *" $GI "* ]]
}
if [[ -n "${BUILD:-}" ]]; then docker build -q -t "$KALMIDO_TEST_IMAGE" "$HERE/.." >/dev/null || exit 1; fi
FAILED=()
SKIPS=" $(awk -v d="$(TZ=Europe/Berlin date +%F)" '!/^#/ && NF >= 3 && $2 >= d {printf "%s ", $1}' "$HERE/skip.txt" 2>/dev/null) "
run() {  # run <name> <cmd...>: prints the summary line, remembers failures
  mine || return 0
  local name=$1; shift
  # ONLY="a b" tests/run_all.sh: just these suites (2.7.2; the containers of their groups are still started, 2.180.0: before the first one that runs)
  [[ -n "${ONLY:-}" && " $ONLY " != *" $name "* ]] && return 0
  # #1315: a proven flaky suite is skipped until the date of its line in skip.txt (tests/skip_test.py: CI red after it);
  # a run naming it (ONLY, kalmido-mactest.sh run SUITE) runs it - that is how it gets fixed
  [[ -z "${ONLY:-}" && "$SKIPS" == *" $name "* ]] && { echo "== $name: SKIPPED (wackelt, tests/skip.txt)"; return 0; }
  [[ -n "${KALMIDO_LIST_ONLY:-}" ]] && { echo "$name"; return 0; }
  [[ -n "${FRESH_DUE:-}" ]] && _fresh_start "$name"
  local out rc t0
  t0=$(_ms); GRAN=1
  out=$("$@" 2>&1); rc=$?
  _timing "$name" $(( $(_ms) - t0 )) $rc  # 2.149.0 E (#2514)
  echo "$out" | grep -E "^FAIL|^PERF|ok, [0-9]+ failed|Error|Traceback" | head -40
  if [[ $rc -ne 0 ]]; then FAILED+=("$name"); echo "== $name: FAILED (exit $rc)"; echo "$out" | tail -15
    # GitHub Actions: an annotation, readable on the run page (and via the API) without the full log
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
      echo "::error title=suite $name failed::$( { echo "$out" | grep -E "^FAIL|Error|Traceback|failed" | head -8; echo "$out" | tail -3; } | tr '\n' ' ' | sed 's/%/%25/g' | cut -c1-900)"
    fi
  else echo "== $name: passed"; fi
}
# 2.180.0 C (#2695): the start is lazy - right before the group's first suite that runs; a suite in selfstart.txt starts its own
# container first thing (tests/selfstart_test.py guards that), for it the old container is only removed (no second start)
fresh() { mine || return 0; FRESH_DUE=1; }
_fresh_start() {  # _fresh_start <suite>
  FRESH_DUE=
  [[ -n "${SELFSTART+x}" ]] || SELFSTART=" $(grep -v '^#' "$HERE/selfstart.txt" 2>/dev/null | tr '\n' ' ') "
  if [[ "$SELFSTART" == *" $1 "* ]]; then docker rm -f "${KALMIDO_TEST_CONTAINER:-kalmido-test}" >/dev/null 2>&1; return 0; fi
  bash "$HERE/start.sh" >/dev/null || { echo "container start failed"; exit 1; }
}
# 2.321 (#1368): the suites come from tests/suites.py - tests/suites.txt (the old lines of this file) plus every test file
# with a `kalmido-suite:` marker (a new suite needs no list entry: no more conflicts of parallel packages in this file)
eval "$LIST"
_group_end
docker rm -f "${KALMIDO_TEST_CONTAINER:-kalmido-test}" "${KALMIDO_TEST_DB_CONTAINER:-${KALMIDO_TEST_CONTAINER:-kalmido-test}-db}" >/dev/null 2>&1  # 2.37.0: + its Postgres
if [[ ${#FAILED[@]} -gt 0 ]]; then echo "FAILED suites: ${FAILED[*]}"; exit 1; fi
echo "ALL SUITES PASSED$([[ $SHARD -gt 0 ]] && echo " (shard $SHARD/$SHARDS_DEFINED)")"
