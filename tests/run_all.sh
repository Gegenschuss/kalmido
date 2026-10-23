#!/usr/bin/env bash
# run_all.sh -- every suite, each group against a fresh test container (see start.sh for the settings).
#   BUILD=1 tests/run_all.sh     build the image from the repo first (docker build -t $KALMIDO_TEST_IMAGE .)
#   tests/run_all.sh --shard 2/6  only the second of the 6 shards (CI runs the shards as parallel jobs, see ci.yml).
#                                The `shard N` lines below split the groups; each group (a `fresh` container and the
#                                suites after it) stays whole. Keep the shards about equal (~14 min each on CI) by moving
#                                a marker when one grows; new suites go at the end (the last shard).
#   ONLY="a b" tests/run_all.sh   just these suites (the containers of their groups are still started)
#   ONLY_GROUPS="a b" tests/run_all.sh  2.149.0 (#2514): the whole groups of these suites (every suite of each group, in order;
#                                the other groups start no container) - the CI rerun: a suite that needs the state of the
#                                one before it (news_ui after api) passes alone too
#   now wed 10:00; fresh; run ...  2.149.0 (#2512): this group runs at that test time (an ISO instant, HH:MM today or
#                                mon..sun HH:MM of this week, Berlin): KALMIDO_TEST_NOW for the server (start.sh) and for the
#                                suites (testclock), the clock runs on from there; the other groups run at the real time (or at
#                                a KALMIDO_TEST_NOW set for the whole run)
#                                2.192.0 A (#2512): the JS suites too - tests/boot.js shifts Date in Node and in every jsdom window
#                                (JSDOM.fromURL; own `new JSDOM` windows: testClock(w)) by the same offset, testNow() for suites
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
  "$HERE/run_all.sh")
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
now() { NEXT_NOW="$*"; }  # now <when>: the test time of the next group (#2512), see _now_iso
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
    if [[ -n "${NEXT_NOW:-$BASE_NOW}" ]]; then
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
run() {  # run <name> <cmd...>: prints the summary line, remembers failures
  mine || return 0
  local name=$1; shift
  # ONLY="a b" tests/run_all.sh: just these suites (2.7.2; the containers of their groups are still started, 2.180.0: before the first one that runs)
  [[ -n "${ONLY:-}" && " $ONLY " != *" $name "* ]] && return 0
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
fresh; run api "$PY" api_test.py "$KALMIDO_TEST_DATA"
       run ui node ui_test.js
       run settings_ui node settings_ui.js
       run news_ui node news_ui.js
       run offline node offline_test.js
fresh; run news "$PY" news_test.py "$KALMIDO_TEST_DATA"
# 2.149.0 (#2512): p1_api and p294_b_api at a fixed day time (they failed at night / on Sundays: UTC day, week start)
now wed 10:00; fresh; run p1_api "$PY" p1_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p1_ui node p1_ui_test.js
now wed 10:00; fresh; run time_api "$PY" time_api_test.py "$KALMIDO_TEST_DATA"  # 2.192.0 A (#2512): test time
now wed 10:00; fresh; run time_ui node time_ui_test.js
fresh; run p3_api "$PY" p3_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p3_ui node p3_ui_test.js
fresh; run setup_ui node setup_ui.js
shard 21  # 22.10.2026 (2.165.5): the v1 ... p290 group moves to the short last shard (shard 1 ran into the 45 min CI limit in 2.165.2-2.165.4)
fresh; run v1 "$PY" v1_test.py "$KALMIDO_TEST_DATA"
       run v1_ui node v1_ui.js "$KALMIDO_TEST_DATA"
       run md node md_test.js
       run security "$PY" security_test.py "$KALMIDO_TEST_DATA"
# 1.1: onboarding (own containers with KALMIDO_ONBOARDING=1), palette, shortcuts, tour, density, celebration
       run v11_api "$PY" v11_api_test.py "$KALMIDO_TEST_DATA"
       run v11_ui node v11_ui.js "$KALMIDO_TEST_DATA"
# 1.2: Settings > Appearance (own container): font size, font, accent, theme, density, palette, contrast
       run appearance_ui node appearance_ui.js "$KALMIDO_TEST_DATA"
# 1.1.3: Web Push (own container with a fake push service inside): VAPID, allow-list, encryption, routing, then SW + settings UI
       run webpush "$PY" webpush_test.py "$KALMIDO_TEST_DATA"
       run webpush_ui node webpush_ui.js "$KALMIDO_TEST_DATA"
# 1.1.4: admin alerts via ntfy (own containers with KALMIDO_ADMIN_ALERTS=1): kinds, recipients, privacy, cooldown, cap,
# summary, toggles, env overrides, disk / integrity checks, then Settings > Users > Admin alerts
       run admin_alerts "$PY" admin_alerts_test.py "$KALMIDO_TEST_DATA"
       run admin_alerts_ui node admin_alerts_ui.js "$KALMIDO_TEST_DATA"
# 1.2: calendar subscriptions (own containers with a fake ICS / CalDAV server inside, internal host names, the allow-list):
# expansion, SSRF guard, secrets, sync, alerts, isolation, then the calendar views, Today, popover and settings in jsdom
       run calendars "$PY" calendars_test.py "$KALMIDO_TEST_DATA"
       run calendars_ui node calendars_ui.js
# package A: backups + restore (own containers), two-factor + passkeys (software authenticator), OIDC (fake provider inside
# the container), then the sign-in / backup UI in jsdom (own container, page on http://localhost for WebAuthn)
       run backup "$PY" backup_test.py "$KALMIDO_TEST_DATA"
# 2.9.0: CalDAV for tasks (#435: app passwords, discovery, PROPFIND / REPORT / sync-collection, PUT / GET / DELETE round trips
# with VTODOs as Reminders, Thunderbird and Tasks.org write them, ETags, roles, lockout, http refused) and the OIDC settings
# in the database (#438) (own containers); then the settings UI in jsdom and Firefox (360 / 390 touch, 1280 mouse). Shard 1:
# it was the shortest (15.4 min on CI after 2.8.0)
       run p290_dav "$PY" p290_dav_test.py "$KALMIDO_TEST_DATA"
       run p290_ui node p290_ui.js "$KALMIDO_TEST_DATA"
shard 2  # ---------------------------------------------------------------- shard 2 of 5
fresh; run twofa "$PY" twofa_test.py "$KALMIDO_TEST_DATA"
       run oidc "$PY" oidc_test.py "$KALMIDO_TEST_DATA"
       run signin_ui node signin_ui.js "$KALMIDO_TEST_DATA"
# package B: REST API + personal access tokens, webhooks (fake receiver inside the container), public list links + checklist
# mode (own containers each), then checklist mode, the public link section, API tokens and webhooks in the UI (jsdom)
       run api_v1 "$PY" api_v1_test.py "$KALMIDO_TEST_DATA"
       run webhooks "$PY" webhooks_test.py "$KALMIDO_TEST_DATA"
       run public_link "$PY" public_link_test.py "$KALMIDO_TEST_DATA"
       run checklist_ui node checklist_ui.js "$KALMIDO_TEST_DATA"
# package C: importers (own containers): Todoist, Trello, Asana, Microsoft To Do / Outlook, ICS; preview, idempotency, undo, limits,
# malicious files, the API, then Settings > Data > Import in jsdom
       run import "$PY" import_test.py "$KALMIDO_TEST_DATA"
       run import_ui node import_ui.js "$KALMIDO_TEST_DATA"
# package D2: Gantt timeline (dependency arrows, drag-to-link, touch + keyboard paths, auto-shift + undo, view-only), the opt-in
# modules "deps" / "fields" (per user, migration of existing users after a restart), the three setup presets
fresh; run d2_api "$PY" d2_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run gantt_ui node gantt_ui.js
fresh; run run_ui node run_ui.js
# package D3: the roadmap ("All" as a timeline): GET /api/roadmap, moving a whole project (one transaction, cap, rights,
# month ends / DST), the token API; then grouping, collapse, filters, summary drag + undo, view-only, arrows, zoom, phone
fresh; run roadmap_api "$PY" roadmap_api_test.py "$KALMIDO_TEST_DATA"
fresh; run roadmap_ui node roadmap_ui.js
# D3 additions: section drag and drop, sidebar touch drag and drop, switched-off modules leave no trace, touch tablets
fresh; run sections_dnd_ui node sections_dnd_ui.js
fresh; run sidebar_touch_ui node sidebar_touch_ui.js
fresh; run modules_gating_ui node modules_gating_ui.js
fresh; run tablet_ui node tablet_ui.js
# package D4: the undo / redo history (batch conflicts, expect / guard, sections and lists with _prev; the buttons, keys,
# text grouping, conflicts, offline queue, view-only refusal, history menu)
fresh; run undo_api "$PY" undo_api_test.py "$KALMIDO_TEST_DATA"
fresh; run undo_ui node undo_ui.js
# 1.5 (UX1): lists archived first and deleted for good only from the archive; settings saved one by one; the usability UI
# (autosave + undo of settings, Modules page, slim checklist panel, comments in private lists (2.0.6), archive, own dialogs,
# own date / time pickers, phone undo in "…", Fold layout, touch-target rules)
fresh; run ux1_api "$PY" ux1_api_test.py "$KALMIDO_TEST_DATA"
fresh; run ux1_ui node ux1_ui.js
fresh; run p151_api "$PY" p151_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p151_ui node p151_ui.js
# 1.7.0: Flow sort, overdue in one click, the smart list "Now doable"
fresh; run p170_ui node p170_ui.js
# 1.7.1: every view scrolls on a phone (Firefox headless, skipped without firefox): last line clears the tab bar and +, no touch blocker
fresh; run scroll_ui node scroll_ui.js
# 1.8.0: the sample project (create / idempotent / private / quiet / German / without project modules / remove exactly it),
# then setup + Settings > Data + palette + the welcome tour offer (restarts the container itself, also with KALMIDO_ONBOARDING=1)
fresh; run p180_api "$PY" p180_api_test.py "$KALMIDO_TEST_DATA"
       run p180_ui node p180_ui.js
fresh; run p181_ui node p181_ui.js
# 1.9.0: share from the phone (HTTP Shortcuts import, iPhone guide), profile pictures (presets, photo resized + EXIF
# stripped, access), delete a tag, News inbox (dismiss, filter, which events), stale update check; then the UI (refresh
# of shared lists, live comments, Fold dialogs, users first in Administration)
# 2.8.0 "Leitstand" (#434, here in shard 2: shard 4 was already at 18 min on CI): no icon rail, the grouped sidebar
# reaches every module (switched-off ones gone), command bar, agent band (approve / reject, folds per device, no duplicate
# header dots), ticket gutter rows, the icon set "Punkt", the raspberry accent + migration; Firefox at 360 / 390 / 904
# (touch) and 1280 / 1440 / 1920 (mouse): layout, 44 px, contrast
       run p280_ui node p280_ui.js "$KALMIDO_TEST_DATA"
shard 3  # ---------------------------------------------------------------- shard 3 of 5
fresh; run p190_api "$PY" p190_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p190_ui node p190_ui.js
# 1.10.0: list roles (admin / member / participant / viewer): leak tests of every read path for a participant against an
# admin, a member and a viewer (own container with the webhook stub), then the members dialog, the assignee column
# (desktop + phone, subtasks, hide per list) and the participant's view in jsdom
       run p1100_api "$PY" p1100_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p1100_ui node p1100_ui.js
# 2.0.0: agents (create / convert, kill switch, never admin / Paperless, only shared lists incl. participant role), events via
# signed webhook + polling + long-polling, wake, reactions + approvals, status, jobs, chat, shared list tags, tidy (own
# container with the webhook stub); then the UI in jsdom; the MCP server against a stub API (no container)
       run p200_api "$PY" p200_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p200_ui node p200_ui.js
       run mcp "$PY" mcp_test.py
# 2.0.0 (#279): never a new empty database on top of existing data (own container, restarted with broken data dirs)
       run p200_guard "$PY" p200_guard_test.py "$KALMIDO_TEST_DATA"
# 2.0.2: own list icons (presets, upload: square PNG without metadata, who may see / change it), /drop/drop, the task an
# agent works on; then the comment list (2.0.6: at the end of the panel), inline title edit, keyboard, recently viewed, section "+",
# collapse all, drag autoscroll, iOS gap, share from the phone, "Claude is writing …" in jsdom
fresh; run p202_api "$PY" p202_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p202_ui node p202_ui.js
fresh; run p203_ui node p203_ui.js
fresh; run p204_ui node p204_ui.js
# 2.0.5: admins also empty the trash of shared lists they edit, {deleted, kept} (#310); notifications handled on one device
# are closed on the others: tags, dismiss push with debounce + caps, never silent to Apple (piggyback), device header (#311,
# own container with the fake push service); then Settings > AI colleague (#313), the trash marks and the service worker
       run p205_api "$PY" p205_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p205_ui node p205_ui.js
# 2.0.6: comments as personal notes (without collaboration, private lists, the Comments module, no News / pushes for who
# switched it off, the migration after a restart), roadmap "No date" prefs; then the UI: portrait tablets (composer), "No
# date" in the roadmap / calendar timeline, the focus card, calendar + multi-select keys, the rail = the tab bar, comments
# at the end of the panel with the sticky box, the menu above a dialog (#318)
fresh; run p206_api "$PY" p206_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p206_ui node p206_ui.js
# 2.0.8: push buttons Reply + Done on comment / mention pushes (own container with the fake push service), agent task events
# with the newest comments + the list's sections, /api/v1/lists with sections, compact task pages; then the UI: sort
# "Created", the chat keyboard on phones, Settings > AI colleague lists table, the select sheet on phones, #reply/<id>,
# the badge and the service worker
       run p208_api "$PY" p208_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p208_ui node p208_ui.js
# 2.1.0: the notification matrix + list bells (News and pushes filtered in one place), Paperless connections (legacy / server
# with each user's own token / personal; write-only encrypted tokens, isolation, SSRF guard, without the key), waiting on
# external with the follow-up day (own containers with the fake Paperless + push service); then the UI in jsdom
       run p210_api "$PY" p210_api_test.py "$KALMIDO_TEST_DATA"
       run p210_ui node p210_ui.js "$KALMIDO_TEST_DATA"
# 2.1.1 (#326): model usage of agents: reporting (validation, visibility), the agent's own view, the dashboard (admins / members /
# participants, nameless for what the viewer cannot see), ai_usage on tasks, limits (soft alerts once per period, hard = 429
# except usage / status, raising it, cost, month), the notification row (own container with the fake push service); then the
# UI in jsdom; the Claude Code Stop / SubagentStop hook against a stub API (no container)
       run p211_api "$PY" p211_api_test.py "$KALMIDO_TEST_DATA"
       run p211_ui node p211_ui.js "$KALMIDO_TEST_DATA"
       run usage_hook "$PY" usage_hook_test.py
# 2.11.0 (#439): every translation file complete (100 % of the keys, none unused, placeholders, plurals, HTML tags,
# _meta + beta marks) and the server's per-language number / date / plural helpers (no container)
       run i18n "$PY" i18n_test.py
# 2.12.0 (#436): the browser demo (tools/build_demo.py -> jsdom: boot on the in-browser API, quick add, reload, reset, the
# simulated agent, notices for server features, no network; Firefox 390 touch / 1280, light + dark) and quick add in all six
# languages (#436, parseQuick on the demo build) (no container)
       run demo node demo_test.js
       run quick_lang node quick_lang_test.js
# 2.1.2: transfer list ownership (#349: owner -> person, admin takeover of lists of agents / disabled users, history, News, the
# token API) + agents' username / picture and the agents in the user list (#346); then the UI in jsdom
       run p212_api "$PY" p212_api_test.py "$KALMIDO_TEST_DATA"
       run p212_ui node p212_ui.js "$KALMIDO_TEST_DATA"
# 2.2.0: Git integration (#271: connecting, write-only sealed tokens, SSRF guard, the poller with ETag / rate limits / back-off,
# matching by #id and branch names, CI, "fixes #id" once + undo, the inbound webhook) and merge requests of agents (#339)
# against a fake GitHub + Gitea inside the container (fake_git.py); then the UI in jsdom
       run p220_api "$PY" p220_api_test.py "$KALMIDO_TEST_DATA"
       run p220_ui node p220_ui.js "$KALMIDO_TEST_DATA"
# 2.2.1: the agents' audit log (#358: route templates, ids, denied calls, filters, paging, CSV, admin-read token, retention
# with KALMIDO_AUDIT_DAYS, own containers) and unknown fields (#359: v1 400 unknown_field + aliases, web header + one log
# warning); then Settings > AI colleague > Activity log in jsdom and Firefox (390 x 844, 1280 x 800), and a check that the
# app itself sends no unknown fields
       run p221_api "$PY" p221_api_test.py "$KALMIDO_TEST_DATA"
       run p221_ui node p221_ui.js "$KALMIDO_TEST_DATA"
# 2.10.0: trusted proxies (#445: forwarded client address, lockouts per name + address, https for cookies / CalDAV,
# "none"), groups (#441: admin CRUD, list / folder shares with roles, membership changes, group assignment + take,
# participants, CalDAV, API + OpenAPI) and day planning (#440: working hours, the built-in plan, the dayplan proposal of an
# agent, the daily review + push) (own containers); then the UI in jsdom and Firefox (360 / 390 touch, 1280 mouse, light +
# dark). Shard 3: it was the shortest (15.4 min on CI after 2.9.0)
       run p2100_api "$PY" p2100_api_test.py "$KALMIDO_TEST_DATA"
       run p2100_ui node p2100_ui.js "$KALMIDO_TEST_DATA"
shard 4  # ---------------------------------------------------------------- shard 4 of 5 (2.7.1: shard 3 had reached the 30 min job limit)
# 2.3.0: agent proposals (#260 project from a briefing, #261 break down, #262 sort the inbox, #263 tasks from notes): who may ask
# which agent, requests with exactly the sent input, validation per kind, apply as the person with one undo step, inbox
# consent, discard, retention (own containers); then the entry points, request + review dialogs in jsdom and Firefox
fresh; run p230_api "$PY" p230_api_test.py "$KALMIDO_TEST_DATA"
       run p230_ui node p230_ui.js "$KALMIDO_TEST_DATA"
# 2.4.0: subfolders, project types, project templates with relative dates, ticket types, quick capture (own containers)
       run p240_api "$PY" p240_api_test.py "$KALMIDO_TEST_DATA"
       run p240_ui node p240_ui.js "$KALMIDO_TEST_DATA"
# 2.4.1: agent runtime settings (#377), one tidy agent per list (#379), the agent's state in the chat header + typing (#375),
# no Wake button (#376) (own containers); then the UI in jsdom and Firefox (390 x 844, 1280 x 800)
       run p241_api "$PY" p241_api_test.py "$KALMIDO_TEST_DATA"
       run p241_ui node p241_ui.js "$KALMIDO_TEST_DATA"
# 2.4.2: comment order (#386), usernames for @mentions (#389), sharing with an agent in bulk (#391) (own containers); then
# the UI: comment order, the Code section (#387), mention cards, the folder matrix (#390), the share block, the setup guide
# (#392) in jsdom and Firefox (390 x 844, 1280 x 800)
       run p242_api "$PY" p242_api_test.py "$KALMIDO_TEST_DATA"
       run p242_ui node p242_ui.js "$KALMIDO_TEST_DATA"
# 2.5.0: the app name Kalmido in the web app, the API, backups and the KALMIDO_* configuration (own containers)
       run p250_rename "$PY" p250_rename_test.py "$KALMIDO_TEST_DATA"
# 2.5.1: the agents' log for the sub-tab Log (hide_poll, today's summary, titles only where visible) and the branch suggestion
# kalmido-<id> against the fake GitHub (own container); then Settings > AI colleague in sub-tabs (#393) and clickable comment
# avatars (#395) in jsdom and Firefox (390 x 844, 1280 x 800)
       run p251_api "$PY" p251_api_test.py "$KALMIDO_TEST_DATA"
       run p251_ui node p251_ui.js "$KALMIDO_TEST_DATA"
# 2.5.2 (UX audit 2 hotfix): admin alerts never to the public ntfy.sh unless chosen (own containers, ntfy.sh unreachable);
# then the review dialog, tour, notification hints, panel header, file buttons, plurals + chart labels, error text in jsdom and
# Firefox (360 x 780, 390 x 844, 904 x 1080, 1280 x 800: "…" and the bell in view while an agent works and a timer runs)
       run p252_api "$PY" p252_api_test.py "$KALMIDO_TEST_DATA"
       run p252_ui node p252_ui.js "$KALMIDO_TEST_DATA"
# 2.6.0 (UX2): the agents' contact age + webhook flag, the refused test alert in plain words (own container); then the header
# levels + status chip, "not connected", one term "Agents", the assignee circle, one date format, the usage table, the week
# title, the Share dialog in jsdom, and in Firefox at 360 / 390 / 904 (touch) and 1280 / 1920, dark + light: title, "…" and
# bell, toast, date column, week title, contrast and the 44 px touch targets
       run p260_api "$PY" p260_api_test.py "$KALMIDO_TEST_DATA"
       run p260_ui node p260_ui.js "$KALMIDO_TEST_DATA"
# 2.6.1: the settings date_confirm + agents_hidden, the list bell "custom" (validation, kept across modes, News per event, the
# token API) (own container); then the date popover that saves at once (+ Undo / the OK setting), a status dot per agent in the
# header, the bell's dropdown, the News filter chips and the custom bell dialog in jsdom, and in Firefox at 360 / 390 (touch)
# and 1280 / 1920: "…", the bell and the dots in view, the bell's sheet / dropdown inside the viewport, 44 px targets
       run p261_api "$PY" p261_api_test.py "$KALMIDO_TEST_DATA"
       run p261_ui node p261_ui.js "$KALMIDO_TEST_DATA"
# 2.7.0: reminders up to a year ahead + deadlines (#412), nags with quiet hours, the list default, dedupe and stop rules, the
# token API (#413), hours per day + time sums (#407) (own container, the isolated test database aged for the intervals); then
# the date popover, deadlines on Today, the list dialog (nag, hours per day, "Shopping & packing list"), the IA fixes of #405,
# the setup's start, the resizable bell in jsdom, and in Firefox at 360 / 390 / 904 (touch) and 1280 / 1920: two-line rows in
# a narrow list column, the popover, the time sum, timeline labels, dragging the bell's grip / the sheet's handle
       run p270_api "$PY" p270_api_test.py "$KALMIDO_TEST_DATA"
       run p270_ui node p270_ui.js "$KALMIDO_TEST_DATA"
# 2.7.1 (#410): the overview of a project list: description, key links, milestones, project files (attachment rules), Paperless
# documents of the list, task files per role, the token API + OpenAPI (own container with the fake Paperless); then the tab,
# the sections, German wording and roles in jsdom, and in Firefox at 360 / 390 (touch) and 1280 / 1920: no overflow, columns,
# 44 px targets, the milestone date picker and the timeline markers
       run p271_api "$PY" p271_api_test.py "$KALMIDO_TEST_DATA"
       run p271_ui node p271_ui.js "$KALMIDO_TEST_DATA"
shard 5  # ---------------------------------------------------------------- shard 5 of 6 (2.15.1: shard 4 had reached the 30 min job limit)
# 2.7.2: the list option "Show completed at the bottom" instead of the checklist type (#414: aliases, migration), personal
# agents (#420: policy, owner-only sharing / chat, admin pause / delete), reactions in the agent chat (#421) and delivered_at
# (#422), project files leave the disk with the sample / an import undo (own container); then the robot before the bell
# (#417), person cards (#418), breadcrumbs (#424), Sent / Delivered / typing dots, Settings > Agents > Set up, the viewport
# fix (the keyboard never flips the layout while typing) in jsdom, and in Firefox at 360 / 390 (touch) and 1280 / 1920
fresh; run p272_api "$PY" p272_api_test.py "$KALMIDO_TEST_DATA"
       run p272_ui node p272_ui.js "$KALMIDO_TEST_DATA"
# 2.7.2 (#420): the Windows launcher agent_launcher.ps1 against a stub API (skipped without pwsh)
       run launcher_ps1 "$PY" launcher_ps1_test.py
       run launcher_parity "$PY" launcher_parity_test.py
       run agent_docs_coverage "$PY" agent_docs_coverage_test.py
# 2.12.2 (#451): the agent chat while typing: paged chat API, the box keeps its node, focus and text through Delivered /
# typing / answers / status changes, the list is only patched; in Firefox at 390 (touch) and 1280: pinned to the bottom,
# scrolled up the place is kept + "New message", "Load older messages" keeps the message in view
       run p2122_ui node p2122_ui.js "$KALMIDO_TEST_DATA"
# 2.13.0 (#453): the polish round: one regression check per review finding (chat reactions + approvals, waiting jobs in
# the pill / Today, Kanban touch edge, keyboard focus / skip link / sidebar as one tab stop, the bell, the view switch,
# day plan, offline in words, selection bar, setup step 2, helper texts behind (i), …) in jsdom and Firefox at 390 touch
# (light, German), Fold 904 touch (dark, French) and 1440 (light + dark)
       run p2130_ui node p2130_ui.js "$KALMIDO_TEST_DATA"
# 2.13.1 (#465 #469 #471): files in the agent chat (limits, rights, removal, /drop to an agent), agents read task / comment /
# chat files (API v1, never lists they do not see), "Agent reads every comment" (events, rights, default = the tidy agent);
# then the UI: chat thumbnails + lightbox, the box with waiting files (paste, drag and drop, file input, the share sheet's
# "Send to agent"), the rules block in both setup guides, the list dialog's checkboxes, in jsdom and Firefox at 390 touch / 1280
       run p2131_api "$PY" p2131_api_test.py "$KALMIDO_TEST_DATA"
       run p2131_ui node p2131_ui.js "$KALMIDO_TEST_DATA"
# 2.13.2 (#478): the fixes of the independent re-review: list | task | chat side by side (the task takes the chat's place
# where all three do not fit), re-renders keep the keyboard focus (morph), the quick add through fold / unfold, Markdown in
# comments + chat, font size 75-150 %, 0-byte files refused, one approval in Today, the iOS keyboard pushing the page, the
# pill / Send keep the keyboard, the chat panel at the bottom on resize, the "Feinschliff" items and fewer inline helper
# texts; jsdom + Firefox at 390 / 428 touch (iOS keyboard), Fold 904 (fold / unfold), 1100 / 1440 / 1920 mouse + keyboard
       run p2132_ui node p2132_ui.js "$KALMIDO_TEST_DATA"
# 2.13.3 (#478 follow-up, Fold): one search entry per layout (the command-bar field in the sidebar / drawer), no + button in the
# tablet / Fold-portrait layout after rotating, "No date" removes date + time + reminders + repeat reminder and closes the popover
       run p2133_ui node p2133_ui.js "$KALMIDO_TEST_DATA"
# 2.13.4 (phone round): real touch gestures in Firefox: the section "+" opens the quick sheet above the keyboard, no
# drag ghost after a lost touchend / Escape / background / re-render, auto-scroll at the edges, "Move to list" while
# dragging, the phone chat does not scroll beside the box, Markdown lists keep counting
       run p2134_ui node p2134_ui.js "$KALMIDO_TEST_DATA"
# 2.14.0 (#425): list columns (the list setting for every member, owner / list admins, API v1 + MCP), the Columns dialog,
# rows with cells in the list's order (two on narrow widths, the rest in line 2), and the heron in empty states and error
# pages; jsdom + Firefox at 380 / 390 / 428 touch, Fold 904 (fold / unfold / rotate) + 880 touch, 1100 / 1440 / 1920 mouse
       run p2140_ui node p2140_ui.js "$KALMIDO_TEST_DATA"
# 2.15.0 (#479 #632): fine scopes for tokens and agents (every operation of the OpenAPI document enforced as documented),
# the admin's limit, address restrictions, approvals of an agent's dangerous requests (replayed as the agent), the new
# routes (sections, move, batch, trash, dependencies, fields, templates, files, folders, members, filters, News, habits,
# timer), the inbox in the new person's language, MCP tools by scope; the permission dialogs in jsdom and Firefox at 390
# touch / 1440 mouse; parity: every app route has an API route and every API route an MCP tool (or a documented reason)
       run parity "$PY" parity_test.py
       run p2150_api "$PY" p2150_api_test.py "$KALMIDO_TEST_DATA"
       run p2150_ui node p2150_ui.js "$KALMIDO_TEST_DATA"
# 2.15.1 (#636 #633): Today / Tomorrow in the task header on phones (second row), the matrix folds on phones, Search and the
# palette focused on touch, sticky dialog footers (new token: Expires + Create), the week view on phones; jsdom + Firefox touch
fresh; run p2151_ui node p2151_ui.js "$KALMIDO_TEST_DATA"
shard 6  # ---------------------------------------------------------------- shard 6 of 6 (2.16.0: the accessibility suite alone takes ~12 min)
# 2.16.0 (#473): accessibility: axe-core (WCAG 2.2 A + AA rules, bundled in tests/node_modules) over the main views, dialogs,
# the task panel, the chat, the palette and the sign-in page in Firefox at 1280 (mouse) and 390 (touch), light + dark, and
# every accent colour (own container)
fresh; run p2160_a11y node p2160_a11y.js "$KALMIDO_TEST_DATA"
# 2.16.0 (#639 #641 #634 #642 #643 #644 #645 #447): the grips between list | task | chat and in the column titles (keys,
# per device, standard width), the account picture in the Kalmido row, density "Custom", the reaction button on every chat
# message, the command field (hints, "Ask <agent>", "Create as task"), the sun icons, the heron's sun; jsdom + Firefox at
# 1440 (mouse drags), 2560 / 1920 (four columns), 390 / 412 (touch taps)
       run p2160_ui node p2160_ui.js "$KALMIDO_TEST_DATA"
# 2.17.0 package B "Communication" (#452 #419 #442 #443 #475): notes (roles, search, conflicts, API + scopes), team chat (channels,
# DMs, mentions, rights, reactions, read state, pushes, the agent), tasks by e-mail and the summary (own container with the
# IMAP / SMTP stubs of stub_mail.py), the dashboard setting; then the UI in jsdom and Firefox (390 touch / 1440 mouse)
       run p2170_api "$PY" p2170_api_test.py "$KALMIDO_TEST_DATA"
       run p2170_ui node p2170_ui.js "$KALMIDO_TEST_DATA"
# 2.17.0 (#649): 5000 generated tasks: /api/state, search, the API, and in Firefox start, views, "All" with "Show more",
# re-render, the command field, keyboard (generous limits; PERF_BIG=1 adds 20000)
       run perf_ui node perf_ui.js "$KALMIDO_TEST_DATA"
shard 7  # ---------------------------------------------------------------- shard 7 of 7 (2.18.0: shard 6 with a11y + perf was near 25 min on CI)
# 2.18.0 package A "Software & Planning" (#462): GitLab + Bitbucket, tags, error reports -> tickets (fake providers in the container)
fresh; run p2180_git_api "$PY" p2180_git_api_test.py "$KALMIDO_TEST_DATA"
# 2.18.0 (#408): the project type of a list, the software section of the list dialog, code highlighting, file:line links
       run p2180_soft_ui node p2180_soft_ui.js "$KALMIDO_TEST_DATA"
# 2.18.0 (#430): milestones as tasks (migration, API, MCP), tasks of a milestone, progress, burndown, release notes
       run p2180_ms_api "$PY" p2180_ms_api_test.py "$KALMIDO_TEST_DATA"
       run p2180_ms_ui node p2180_ms_ui.js "$KALMIDO_TEST_DATA"
# 2.18.0 (#431): the timeline: sections, creating tasks right in it (drag / double-click / +, touch long-press), milestones
       run p2180_tl_ui node p2180_tl_ui.js "$KALMIDO_TEST_DATA"
# 2.18.0 (#394): the new icon set (manifest, sizes, maskable safe zone, one-colour badge, favicons, no old mascot wording,
# tools/make_icons.py reproducible); no container
       run p2180_icons "$PY" p2180_icons_test.py
# 2.152.3 (#2667): the app icon on the dark macOS tile (light antenna, violet eyes); static, no container
       run p21523_c_icons "$PY" p21523_c_icons.py
# 2.18.0 (#651 #652): the search icon on phones, reactions at every chat message, News headings, 44 px view switch, empty edits
       run p2180_ride_ui node p2180_ride_ui.js "$KALMIDO_TEST_DATA"
# 2.19.0 package "Family" (#653): "What do you use Kalmido for?", birthdays + anniversaries (CardDAV import against the fake
# server in the container), household rotation, who comes along, kid accounts with stars + rewards, shopping lists with
# areas, meal plan -> shopping list, deadlines, packing templates, API v1 + OpenAPI; then the UI in jsdom and Firefox (360 /
# 390 / 412 / Fold touch, 1440 / 1920 mouse, axe) and the ride-alongs (heron profile pictures, the magnifier next to the open
# drawer, "+" for more reactions in the chats)
       run p2190_family_api "$PY" p2190_family_api_test.py "$KALMIDO_TEST_DATA"
       run p2190_family_ui node p2190_family_ui.js "$KALMIDO_TEST_DATA"
       run p2190_ride_ui node p2190_ride_ui.js "$KALMIDO_TEST_DATA"
       run p2190_fixes_ui node p2190_fixes_ui.js "$KALMIDO_TEST_DATA"
# 2.21.0 package "Events & contacts" (#659 #658, #671 #673): calendars, events (time zones, repeat rules with changed / left-out
# dates, invitations, reminders, the migration of the family events), ICS import, CalDAV for events with iOS / DAVx5 /
# Thunderbird requests, contacts, CardDAV (vCard 3 / 4), links to tasks, scopes calendar / contacts; then the UI in jsdom and
# Firefox (390 touch, the Fold 690 x 829 upright + across, 1440 mouse, axe, a drag over free time) and a server that is down
       run p2210_api "$PY" p2210_api_test.py "$KALMIDO_TEST_DATA"
       run p2210_ui node p2210_ui.js "$KALMIDO_TEST_DATA"
# 2.22.0 package "Home & life" (#663 #662): contracts, devices + upkeep, staying in touch, health (private: agents, tokens
# without the scope "private", webhooks), review + journal, trips, read later from Karakeep (fake server in the container),
# API v1 + OpenAPI; then the UI in jsdom and Firefox (390 / Fold 690 touch, 1440 mouse, axe) and the ride-alongs #678-#692
       run p2220_api "$PY" p2220_api_test.py "$KALMIDO_TEST_DATA"
       run p2220_ui node p2220_ui.js "$KALMIDO_TEST_DATA"
# 2.23.0 package "Team, family, clients" (#463) + #711 #444 #794 #795 #799: clients (organisation only, rates, budget, estimate
# vs. actual, timesheet), workload, approvals, forms -> tasks, sign-in links, self-registration, the agent event task_added,
# the kind of instance (restarts of the container with KALMIDO_INSTANCE_MODE); then the UI in jsdom and Firefox (390 / Fold 690
# touch, 1440 mouse, axe, the sidebar folder gaps of #794)
       run p2230_api "$PY" p2230_api_test.py "$KALMIDO_TEST_DATA"
       run p2230_ui node p2230_ui.js "$KALMIDO_TEST_DATA"
# 2.24.0 "Usability": storage quota (#910), the notice / maintenance banner + API + command (#907), mail limits (#899), agents'
# provider + the News when one joins (#896), a hosted server (#905, a restart with KALMIDO_HOSTED); then the UI in jsdom:
# Fold / DeX layout + keyboard (#908 #832), direct messages (#906), Administration sub-tabs (#826), the settings search, the
# crop dialog (#825), the sidebar, Today, the task menu and panel, the tab bar and the setup (UX-01 ... UX-41)
       run p2240_api "$PY" p2240_api_test.py "$KALMIDO_TEST_DATA"
       run p2240_ui node p2240_ui.js "$KALMIDO_TEST_DATA"
# 2.25.0 "Usability, part 2": lists in a shared folder on every path + the one-time repair (#931, restarts its container),
# the sidebar setting (UX-03), the lean start of added accounts (UX-26), the Team package (UX-25)
       run p2250_api "$PY" p2250_api_test.py "$KALMIDO_TEST_DATA"
# 2.26.0 "Agents in a team & usability": who may address a list's agent (#928, agent -> agent, actor.kind), one agent per list, approval
# requests without a pull request + pause with a reason + a proposal to another topic (#949), "no service" (#933); then the
# UI: resizable sidebar (#932), multi-select + multi-edit in the task panel (#936), the iOS keyboard (#937)
       run p2260_api "$PY" p2260_api_test.py "$KALMIDO_TEST_DATA"
       run p2260_ui node p2260_ui.js "$KALMIDO_TEST_DATA"
# 2.27.0 "Bugs & polish": the version of the code (#968), projects without sections (#972), the share target assigns to me
# (#1001), the owner's arrangement mirrored + the list's sort (#988), tidy-up waits for quiet (#999, restarts its container
# with KALMIDO_TIDY_QUIET_S=2); then the UI: the new-version bar, the task panel, the list dialog, sections, agents per folder,
# the team chat, the grips under menus, typing with the list scrolled (#958)
       run p2270_api "$PY" p2270_api_test.py "$KALMIDO_TEST_DATA"
       run p2270_ui node p2270_ui.js "$KALMIDO_TEST_DATA"
# 2.28.0 "Work and private apart, messages": workspaces (#935: lists / agents of a workspace, the mode workspaces with several
# organisations, organisation admins, leaving, the cross-tenant matrix, the migration; restarts its container), admins reach
# agents only through lists + personal agents (#965 #970 #1011), News "For you" / "Activity" (#987), chat answer buttons
# (#1005); then the UI: the workspace switch, the list dialog, the News tabs and the bell, the agent cards and dialog, the
# buttons in the chat, the robot badge (#985), the grips under a right-click menu (#976) in Firefox
       run p2280_api "$PY" p2280_api_test.py "$KALMIDO_TEST_DATA"
       run p2280_ui node p2280_ui.js "$KALMIDO_TEST_DATA"
# 2.29.0 "Folders like lists, calm agents": folder settings (#1030 / #929: workspace, agent, tidy for the lists of a folder,
# differing lists, Back to the folder, folder people with every role, a member's new list in a shared folder), no backlog
# storm (#1031: since=latest, the 'missed' summary, one tasks_added for a bulk), the permission mode (#1029), noindex (#1026);
# then the UI: the folder settings dialog, the chat pop-up (#363), the permission badge, Settings > Agents (#1024 / #345),
# the code block in a chat bubble (#1028) in Firefox
       run p2290_api "$PY" p2290_api_test.py "$KALMIDO_TEST_DATA"
       run p2290_ui node p2290_ui.js "$KALMIDO_TEST_DATA"
shard 8  # ---------------------------------------------------------------- shard 8 of 8 (2.30.0: the 2.30 suites)
# 2.30.0 "Clear boundaries, calmer agents": the tenant guard (every route in the cross-tenant matrix or listed with a
# reason, static), the cross-tenant matrix for calendars, address books, groups, forms and the rest (#1036, the suite
# restarts its container in the modes it needs), agent chat (#1037 expiring answer buttons, #1041 Allow / Deny, #1039
# status only where the agent writes, #1034 listening by project type), the file viewer and agents' text files
# (#1035 / #380), agent hardening (#919 bridges, list limits, access log, #920 Use safely) and the phone fixes
# (#1033 #1042 #1043 #1044)
fresh; run tenant_coverage "$PY" tenant_coverage_test.py
       run freelancer_coverage "$PY" freelancer_coverage_test.py  # 2.87.9 (#1919): the freelancer parity guard (static)
       run selfstart "$PY" selfstart_test.py  # 2.180.0 C (#2695): the suites in selfstart.txt start their own container first thing (static)
fresh; run p2300_tenant "$PY" p2300_tenant_test.py "$KALMIDO_TEST_DATA"
fresh; run p2300_chat_api "$PY" p2300_chat_api_test.py "$KALMIDO_TEST_DATA"
       run p2300_chat_ui node p2300_chat_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2300_files_api "$PY" p2300_files_api_test.py "$KALMIDO_TEST_DATA"
       run p2300_files_ui node p2300_files_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2300_agentsafe_api "$PY" p2300_agentsafe_api_test.py "$KALMIDO_TEST_DATA"
       run p2300_agentsafe_ui node p2300_agentsafe_ui.js "$KALMIDO_TEST_DATA"
       run p2300_ui_fixes node p2300_ui_fixes.js "$KALMIDO_TEST_DATA"
# 2.31.0 "Phone everyday" (UX round part 1): the task row, Today and the list head (#1051 #1052 #1053), the task panel
# (#1054 phone without tabs, #344 the comments area on a desktop with a draggable split), file tiles and tables
# (#1050 #1048), grouped menus, one search and the agent sub-tabs (#1056 #1057 #1046), sorting by a column title and
# the connection dot on your picture (#354 #378); each suite starts its own container
fresh; run p2310_a_ui node p2310_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2310_b_api "$PY" p2310_b_api_test.py "$KALMIDO_TEST_DATA"
       run p2310_b_ui node p2310_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2310_c_ui node p2310_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2310_d_ui node p2310_d_ui.js "$KALMIDO_TEST_DATA"
# 2.32.0 "Shorter ways" (UX round part 2) + agent chat: the view kit and the project page (#1063 #983 #1061), agent
# chat steps, host model / mode and thumbs approvals (#1079 #1081 #1082 #1062), phone selection mode, swiping in the
# task panel, settings on a phone and the comment box scroll (#1055 #1071 #1060 #1074), share dialog, quick add, list
# icons, logo variants and dropping files on a list (#1058 #1059 #1062 #1077 #1070 #362); each suite starts its own container
fresh; run p2320_a_api "$PY" p2320_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2320_a_ui node p2320_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2320_b_api "$PY" p2320_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2320_b_ui node p2320_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2320_c_ui node p2320_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2320_d_ui node p2320_d_ui.js "$KALMIDO_TEST_DATA"
# 2.33.0 "Agents and notifications": replies to one message and the jump to it, iPhone comment focus (#1076 #1087),
# search in chats and comments (#1080), notification templates per list and folder, the client IP check (#927 #834),
# the agents' plan usage ring, a repository on a folder and the sticky Done bar (#1045 #934 #1086); each suite starts
# its own container
fresh; run p2330_a_api "$PY" p2330_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2330_a_ui node p2330_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2330_b_api "$PY" p2330_b_api_test.py "$KALMIDO_TEST_DATA"
       run p2330_b_ui node p2330_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2330_c_api "$PY" p2330_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2330_c_ui node p2330_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2330_d_api "$PY" p2330_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2330_d_ui node p2330_d_ui.js "$KALMIDO_TEST_DATA"
shard 9  # ---------------------------------------------------------------- shard 9 of 9 (2.37.1: shard 8 had reached the 30 min job limit)
# 2.34.0: agents in everyday work (briefing, project status, idle tasks, time gaps, planned jobs, attachment text)
fresh; run p2340_b_api "$PY" p2340_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2340_b_ui node p2340_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2340_a_api "$PY" p2340_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2340_a_ui node p2340_a_ui.js "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p2340_c_api "$PY" p2340_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2340_c_ui node p2340_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2340_d_api "$PY" p2340_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2340_d_ui node p2340_d_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2350_a_api "$PY" p2350_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2350_b_api "$PY" p2350_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2350_b_ui node p2350_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2350_c_api "$PY" p2350_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2350_c_ui node p2350_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2350_d_api "$PY" p2350_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2350_d_ui node p2350_d_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2360_b_api "$PY" p2360_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2360_b_ui node p2360_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2360_c_api "$PY" p2360_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2360_a_ui node p2360_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2360_d_ui node p2360_d_ui.js "$KALMIDO_TEST_DATA"
       run office_calc "$PY" office_calc_test.py
fresh; run p2361_c_api "$PY" p2361_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2361_c_ui node p2361_c_ui.js "$KALMIDO_TEST_DATA"
       run office_pdf "$PY" office_pdf_test.py
fresh; run p2361_d_api "$PY" p2361_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2361_b_api "$PY" p2361_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2361_b_ui node p2361_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2361_a_api "$PY" p2361_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2361_a_ui node p2361_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2362_b_api "$PY" p2362_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2362_b_ui node p2362_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2362_c_api "$PY" p2362_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2362_c_ui node p2362_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2362_a_api "$PY" p2362_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2362_d_api "$PY" p2362_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2362_d_ui node p2362_d_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2362_e_api "$PY" p2362_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2362_e_ui node p2362_e_ui.js "$KALMIDO_TEST_DATA"
# 2.37.0 (#1150): the Postgres driver layer and the static dialect guard
fresh; run pg_layer "$PY" pg_layer_test.py "$KALMIDO_TEST_DATA"
       run pg_dialect "$PY" pg_dialect_test.py
       run pg_prepare "$PY" pg_prepare_test.py "$KALMIDO_TEST_DATA"
# 2.37.0 (#1150): the message search on Postgres (kalmido_fold + trigram indexes)
fresh; run p2370_c_api "$PY" p2370_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.37.0 (#1158 / #1159): folder settings of a folder with only lists of others; a chat message saved as a task
fresh; run p2370_u_api "$PY" p2370_u_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2370_u_ui node p2370_u_ui.js "$KALMIDO_TEST_DATA"
# 2.37.0 part 2 (#1150): literal task search (LIKE escaping), database errors as 400
fresh; run p2370_k_api "$PY" p2370_k_api_test.py "$KALMIDO_TEST_DATA"
# 2.37.0 part 2 (#1150): row-level security per organisation (static guard + the policies against the test database)
       run rls_static "$PY" rls_static_test.py
fresh; run rls_direct "$PY" rls_direct_test.py "$KALMIDO_TEST_DATA"
# 2.37.0 part 3 (#1161 / #1165): the jobs list follows the end of a job; copy a whole chat message
fresh; run p2370_j_ui node p2370_j_ui.js "$KALMIDO_TEST_DATA"
# 2.37.0 part 3 (#1150): the move from SQLite (migrate-sqlite): new install, big synthetic 2.36 database, broken values, --check,
# second start, an old backup zip through the restore, private agents in organisation lists (K2-3); own containers
fresh; run p2370_m_api "$PY" p2370_m_api_test.py "$KALMIDO_TEST_DATA"
# 2.37.0 part 3 (review W2-4 / W2-2 / K2-1): row-level security with a login role that owns the database without superuser /
# BYPASSRLS (policies, backup + restore), and a role that bypasses it without kalmido_app (exit 3 / alert); own database container
fresh; run rls_owner "$PY" rls_owner_test.py "$KALMIDO_TEST_DATA"
# 2.38.0 (#1021, F1): invoices, credit notes, payments, reminders of Office & finance
fresh; run p2380_a_api "$PY" p2380_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2380_a_ui node p2380_a_ui.js "$KALMIDO_TEST_DATA"
# 2.38.0 (#1021 P5, F2): e-invoice XML (EN 16931 / XRechnung) + PDF/A-3 writer without a server; stored PDF / XML at finalising
       run office_einvoice "$PY" office_einvoice_test.py
fresh; run p2380_b_api "$PY" p2380_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.38.0 U1 (#1178 #1177 #1173 #1170 #1155): long press = selection on touch, list picker + sheet head, zoom lock in the app
fresh; run p2380_u1_ui node p2380_u1_ui.js "$KALMIDO_TEST_DATA"
# 2.38.0 U2 (#1132 #1169 #1155 #1174 #1171): locked tasks skipped in a batch, search with only special characters, office log
# reads pruned, IPs masked; list icons in the list colour, multi-edit skips locked tasks, part mark in italics, palette folding
fresh; run p2380_u2_api "$PY" p2380_u2_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2380_u2_ui node p2380_u2_ui.js "$KALMIDO_TEST_DATA"
# 2.39.0 (#1168): the Playbook of a list / folder in the list and folder dialogs (editor, versions, proposals, regular checks)
fresh; run p2390_u_ui node p2390_u_ui.js "$KALMIDO_TEST_DATA"
# 2.39.0 (#1179): a person edits their own messages in the agent chat (only the sender, delivered / answered -> the event
# message_edited only to that agent, also for edited comments and team messages the agent had), then the UI (Edit, "edited", versions)
fresh; run p2390_c_api "$PY" p2390_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2390_c_ui node p2390_c_ui.js "$KALMIDO_TEST_DATA"
# 2.39.0 (#1151): "Tidy up the list": the request (rights, the tidy agent, health list, limits, packages of 50), the agent's
# cleanup proposal (validation), applying merge / rename / move / close as the person with skipped tasks (editing, changed,
# completed), one undo step + redo; then the UI on a phone (list menu, selection, dialog, review sheet, result, undo)
fresh; run p2390_b_api "$PY" p2390_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2390_b_ui node p2390_b_ui.js "$KALMIDO_TEST_DATA"
# 2.39.0 (#1168): the Playbook of lists / folders (versions, agent API, proposals, events, scheduled list checks, templates, backup)
fresh; run p2390_a_api "$PY" p2390_a_api_test.py "$KALMIDO_TEST_DATA"
shard 6  # 2.43.1: the 2.39.1 suites run in shard 6 (shard 9 reached the 30 min CI job limit, shard 6 took 11 min)
fresh; run p2391_m_ui node p2391_m_ui.js "$KALMIDO_TEST_DATA"
# 2.39.1 (#1219 basket + Sort, My tasks; #1221 group headers with their path + own order; #1185 sidebar Views / Areas, fold all)
fresh; run p2391_k_api "$PY" p2391_k_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2391_k_ui node p2391_k_ui.js "$KALMIDO_TEST_DATA"
# 2.39.1 (#1182): Office & finance legacy import -- an invented DATA.xlsx (clients with split addresses, duplicates, services,
# equipment), the archive of old PDFs (file names, magic bytes, 0600 files), numbers without collision, undo of a run, rights
fresh; run p2391_f_api "$PY" p2391_f_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2391_f_ui node p2391_f_ui.js "$KALMIDO_TEST_DATA"
# 2.39.1 (#1188 list admins delete, Lists of the organisation, folder defaults on a move; #1291 menu texts; #1214 Hide completed default)
fresh; run p2391_l_api "$PY" p2391_l_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2391_l_ui node p2391_l_ui.js "$KALMIDO_TEST_DATA"
# 2.39.1 (#1217 / #1327 / #1293): lists like a table: custom fields in plain lists, column lines / widths / moving, cell editing, the API switches the module on
fresh; run p2391_t_api "$PY" p2391_t_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2391_t_ui node p2391_t_ui.js "$KALMIDO_TEST_DATA"
# 2.39.1 part R: office audit rest (#1210: manual numbers under a lock + reason for a gap, payments admins only, NOT NULL
# org_id of positions, own-text mails per day, office folder rights after restore / start), dialog backdrop (#1220), loading
# screen (#1213), celebration (#1292)
fresh; run p2391_r_api "$PY" p2391_r_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2391_r_ui node p2391_r_ui.js "$KALMIDO_TEST_DATA"
shard 10  # --------------------------------------------------------------- shard 10 of 10 (2.40.0: the 2.40 suites, shard 9 is full)
# 2.40.0 T (#1430): render time of a 300-row table with two fields, 50 live changes (prints the numbers)
fresh; run p2400_t_perf node p2400_t_perf.js "$KALMIDO_TEST_DATA"
# 2.40.0 T (#1430 #1203 #1415 #1191 #1416 #1409): guide lines / bundled renders, description tap while scrolling + pen,
# empty states, list columns from 600 px, priority as background, Markdown in titles (md_plain, checklist -> subtasks + Restore)
fresh; run p2400_t_api "$PY" p2400_t_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_t_ui node p2400_t_ui.js "$KALMIDO_TEST_DATA"
# 2.40.0 A (#1432): "Load more" for jobs, completed, trash and news (cursors without doubles / gaps, open jobs on top, counters over all)
fresh; run p2400_a_api "$PY" p2400_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_a_ui node p2400_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2400_l_api "$PY" p2400_l_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_l_ui node p2400_l_ui.js "$KALMIDO_TEST_DATA"
# 2.40.0 D (#1368 #1381 #1363 #1364 #1366 #1336): e-invoice address from free lines, closing / reminder texts, fee as an open item,
# settled reminders, language switch of drafts, PDF inline + download, send / reminder dialogs
fresh; run p2400_d_api "$PY" p2400_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_d_ui node p2400_d_ui.js "$KALMIDO_TEST_DATA"
# 2.40.0 V (#1190 #1334 #1361 #1344 #1345): progress bar off by default, group_order bounds, favourites, My tasks in an own order, org line
fresh; run p2400_v_api "$PY" p2400_v_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_v_ui node p2400_v_ui.js "$KALMIDO_TEST_DATA"
# 2.40.0 K (#1380 #1372 #1421 #1335): contact persons of a client (migration, list, documents, BT-56, import, undo), the
# country as an ISO code / choice, the address of an archived PDF with its proposals, the archive file after the commit
fresh; run p2400_k_api "$PY" p2400_k_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_k_ui node p2400_k_ui.js "$KALMIDO_TEST_DATA"
# 2.40.0 part E (office settings): #1378 fetch() writes carry the CSRF header (static check), logo + import; #1371 unsaved input
# survives view changes and live events (formguard.js); #1379 producing / raw data switches + start migration; #1377 the word
# before the management's names; #1382 number scheme building blocks, previews, plain errors, (i) of the terms
fresh; run p2400_e_api "$PY" p2400_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2400_e_ui node p2400_e_ui.js "$KALMIDO_TEST_DATA"
# 2.41.0 part A (small fixes): #1476 scope names, #1477 hover dot, #1479 job log stays open, #1439 submenu place, #1475 Link row only with a link
fresh; run p2410_a_ui node p2410_a_ui.js "$KALMIDO_TEST_DATA"
# 2.41.0 part E (chat): #1374 copy with formatting, #1206 notices in the agent chat
fresh; run p2410_e_api "$PY" p2410_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2410_e_ui node p2410_e_ui.js "$KALMIDO_TEST_DATA"
# 2.41.0 part F: #1437 vCard import in batches / background, #1383 choice cards in comments, #1376 live updates per area
fresh; run p2410_f_api "$PY" p2410_f_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2410_f_ui node p2410_f_ui.js "$KALMIDO_TEST_DATA"
# 2.41.0 part D: #1365 My tasks per list (Hidden group), #1471 time tracking as a switch of every list, #1205 Waiting-on suggestions
fresh; run p2410_d_api "$PY" p2410_d_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p2410_d_ui node p2410_d_ui.js "$KALMIDO_TEST_DATA"
# 2.41.0 part C: #1420 one Share dialog for folders (several agents, public links, ownership), #1423 folder settings like a list's, #1428 share symbols on folders
fresh; run p2410_c_api "$PY" p2410_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2410_c_ui node p2410_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2412_ui node p2412_ui.js "$KALMIDO_TEST_DATA"  # 2.41.2 (#1501): the UI answers at once
# 2.42.0 part C: #833 organisation export (encrypted archive, decrypt tool), own container with KALMIDO_SECRET_KEY
fresh; run p2420_c_api "$PY" p2420_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.42.0 part D: #1376 delta state (only changed tasks), #1383 save an agent's comment as a task
fresh; run p2420_d_api "$PY" p2420_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2420_d_ui node p2420_d_ui.js "$KALMIDO_TEST_DATA"
# 2.42.0 part A: #828 encrypted task note + files, #909 encrypted direct messages (end-to-end, in the browser)
fresh; run p2420_a_api "$PY" p2420_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2420_a_ui node p2420_a_ui.js "$KALMIDO_TEST_DATA"
# 2.42.0 part B: #828 keys per organisation (office fields, purchase prices, stored files encrypted at rest; orgcrypt_cli), own container with KALMIDO_SECRET_KEY
fresh; run p2420_b_api "$PY" p2420_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.43.0 part D: #1434 delete all times of a project (preview, delete, restore), tracked-time window; #1500 a task in its own window
fresh; run p2430_d_api "$PY" p2430_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2430_d_ui node p2430_d_ui.js "$KALMIDO_TEST_DATA"
# 2.43.0 part B: #1330 dependencies by dragging (Alt + drop, drop fields in the task panel), #1003 several tasks at once (subtasks, out of the parent, block)
fresh; run p2430_b_api "$PY" p2430_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2430_b_ui node p2430_b_ui.js
# 2.43.0 part C: #1452 widgets changed right in the view (menu, sizes, standard for everyone), #1346 pin board (colours, notepads), #1504 agents card
fresh; run p2430_c_api "$PY" p2430_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2430_c_ui node p2430_c_ui.js "$KALMIDO_TEST_DATA"
# 2.43.0 part A: #1328 formula fields, sum row, key figures; #1331 a list like a spreadsheet
fresh; run p2430_a_api "$PY" p2430_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2430_a_ui node p2430_a_ui.js "$KALMIDO_TEST_DATA"
shard 6  # 2.46.3: the 2.44 / 2.45 suites run in shard 6 (shard 10 reached the 30 min CI job limit, shard 6 took 14 min)
# 2.44.0 part B: #1443 outbox + looked-at images, #1445 jobs (agent_job.py), #1447 task events bundled (starter modules, no server)
fresh; run p2440_b_launcher "$PY" p2440_b_launcher_test.py
# 2.44.0 part A: the launcher's event runner core (approval-done, permission questions, approval lifecycle, resumed
# conversations, robust runs) against a stub API and a fake command (pure Python: no container needed)
run p2440_a_launcher "$PY" p2440_a_launcher_test.py
# 2.44.0 part C: #1517 set up an agent on a computer with one command (one-time code, computers, setup scripts), #962 agent_launcher.sh on macOS
fresh; run p2440_c_api "$PY" p2440_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2440_c_ui node p2440_c_ui.js "$KALMIDO_TEST_DATA"
       run p2440_c_setup "$PY" p2440_c_setup_test.py
# 2.44.0 part D: #1187 areas (Office, Time, Review, Home): sidebar, tabs, old links, one switch per area, setup
fresh; run p2440_d_ui node p2440_d_ui.js "$KALMIDO_TEST_DATA"
# 2.45.0 part C: #1529 reload safety: service worker 5xx / cache fallback, reload guard (no server needed)
fresh; run p2450_c_ui node p2450_c_ui.js "$KALMIDO_TEST_DATA"
# 2.45.0 part D: #1504 the start page as in the draft (sentence, Today with a box, compact News, active projects, slim empty cards, two columns)
fresh; run p2450_d_ui node p2450_d_ui.js "$KALMIDO_TEST_DATA"
# 2.45.0 part A: #1502 #1503 #1509 #1516 the sidebar (group More, the order, the messenger, the notes of all lists)
fresh; run p2450_a_ui node p2450_a_ui.js "$KALMIDO_TEST_DATA"
# 2.45.0 part B: #1515 self-hosting (one-time setup code, server key file, backups on for a new server; install script,
# docker-compose and proxy templates linted without a container)
fresh; run p2450_b_api "$PY" p2450_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2450_b_ui node p2450_b_ui.js "$KALMIDO_TEST_DATA"
       run p2450_b_lint "$PY" p2450_b_lint_test.py
       run p2450_l_secretfile "$PY" p2450_l_secretfile_test.py  # 2.45.0 (#1515): review: key file edge cases (no server)
# 2.45.1 part A: vCard import with ß / quoted-printable (#1555)
fresh; run p2451_a_api "$PY" p2451_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.45.1 part B: #1556 devices with a German and an English name (master data, legacy import Device DE / Device EN, undo)
fresh; run p2451_b_api "$PY" p2451_b_api_test.py "$KALMIDO_TEST_DATA"
shard 8  # 2.46.3: the 2.46 suites (and new ones after them) run in shard 8 (shard 10 full, shard 8 took 15 min)
# 2.46.1 lead: #1634 subtasks typed fast (queue, the rebuilt field keeps the text)
fresh; run p2461_l_ui node p2461_l_ui.js "$KALMIDO_TEST_DATA"
# 2.46.1 part C: #1554 several contacts at once (delete / move in one request, rights, birthdays, CardDAV, token API; the selection)
fresh; run p2461_c_api "$PY" p2461_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2461_c_ui node p2461_c_ui.js "$KALMIDO_TEST_DATA"
# 2.46.1 part C: #1557 legacy import per area (import only some areas, undo one area, the whole undo after it)
fresh; run p2461_c_import_api "$PY" p2461_c_import_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2461_c_import_ui node p2461_c_import_ui.js "$KALMIDO_TEST_DATA"
# 2.46.1 part D: #1639 list channel for agents that listen in, #1361 favourites 4-7, #1422 folder default "Hide completed"
fresh; run p2461_d_api "$PY" p2461_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2461_d_ui node p2461_d_ui.js "$KALMIDO_TEST_DATA"
# 2.46.1 part A: #1607 #1643 the folder row like a list row, #1612 a list to the very end, #1635 sections to the end / long press on a phone, #1636 the cart
fresh; run p2461_a_ui node p2461_a_ui.js "$KALMIDO_TEST_DATA"
# 2.46.1 part B: #1591 "Switch on all modules", #1602 sample project off, #1615 the list Family, #1641 encryption lists
fresh; run p2461_b_api "$PY" p2461_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2461_b_ui node p2461_b_ui.js "$KALMIDO_TEST_DATA"
# 2.46.1 part E: phone animations (#1558 #1559 #1560), inline title field (#1622), Office tabs / empty states (#1637)
fresh; run p2461_e_ui node p2461_e_ui.js "$KALMIDO_TEST_DATA"
# 2.46.0 part D: #1604 Back between the Share dialog and the settings (folder, list), #1563 encryption block + boundary check details
fresh; run p2460_d_api "$PY" p2460_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2460_d_ui node p2460_d_ui.js "$KALMIDO_TEST_DATA"
# 2.46.0 part C: #1606 a changed folder role asks before it replaces roles set per list, #1605 group pictures (+ backups hold the pictures)
fresh; run p2460_c_api "$PY" p2460_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2460_c_ui node p2460_c_ui.js "$KALMIDO_TEST_DATA"
# 2.46.0 part B: "Everyone in the organisation" (#1603)
fresh; run p2460_b_api "$PY" p2460_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2460_b_ui node p2460_b_ui.js "$KALMIDO_TEST_DATA"
# 2.46.0 part A: #1592 #1562 #1561 one kind of instance (organisations + private spaces), no automatic memberships, the
# organisation and role when an admin adds a person (restarts its container)
fresh; run p2460_a_api "$PY" p2460_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2460_a_ui node p2460_a_ui.js "$KALMIDO_TEST_DATA"
# 2.46.2 part B: #1665 dialogs move by their header on the desktop, #1719 a chat in its own window
fresh; run p2462_b_ui node p2462_b_ui.js "$KALMIDO_TEST_DATA"
# 2.46.2 part C: #1712 #1651 #1666 #1726 #1660 button, autofill, copy comments, dismissible note, fade-in + pills
fresh; run p2462_c_ui node p2462_c_ui.js "$KALMIDO_TEST_DATA"
# 2.46.2 part D: #1472 #1662 #1663 #1664 #1647 #1646 client month, empty section drop, locked note, subfolder to top level, import bar, PDF address block
fresh; run p2462_d_api "$PY" p2462_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2462_d_ui node p2462_d_ui.js "$KALMIDO_TEST_DATA"
# 2.46.2 part A: #1718 no flicker (the view is morphed on a redraw of the same route)
fresh; run p2462_a_ui node p2462_a_ui.js "$KALMIDO_TEST_DATA"
# 2.46.4 part A: #1732 the contacts of a deleted address book leave the list at once (dialog, filter, live update)
fresh; run p246d_a_ui node p246d_a_ui.js "$KALMIDO_TEST_DATA"
# 2.46.4 part B: #1751 the list switch "Tap does not open details" (a tap ticks off; on for shopping / packing lists)
fresh; run p246d_b_api "$PY" p246d_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p246d_b_ui node p246d_b_ui.js "$KALMIDO_TEST_DATA"
# 2.46.4 part C: #1737 workspace line + greyed-out people in the Share dialogs, #1755 one-line Undo message above the keyboard
fresh; run p246d_c_ui node p246d_c_ui.js "$KALMIDO_TEST_DATA"
# 2.46.6 part D: #1711 pen on approval cards, #1713 setup command in the account language
fresh; run p2466_d_ui node p2466_d_ui.js "$KALMIDO_TEST_DATA"
# 2.46.6 part A: #1722 #1714 #1715 #1717 #1445 the reference launcher: cut buttons, one suggestion, the fixed rules block,
# WORKFLOW-KALMIDO.md, a wake run after a job and a lost job resumed once (pure Python, no server)
run p2466_a_launcher "$PY" p2466_a_launcher_test.py
# 2.46.6 part B: #1680 #1708 #1709 #1716 personal agent hint at the members switch, an agent's lists, setup offer, which agent when
fresh; run p2466_b_api "$PY" p2466_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2466_b_ui node p2466_b_ui.js "$KALMIDO_TEST_DATA"
# 2.46.6 part C: #1710 Settings: the admin parts gathered under Administration ("Admin"), mark "Admin · applies to everyone"
fresh; run p2466_c_ui node p2466_c_ui.js "$KALMIDO_TEST_DATA"
shard 5  # 2.47.0: the 2.47 suites run in shard 5 (shard 8 with the 2.46 suites took 24 min, shard 5 17 min)
# 2.47.0 part C: #1216 shoot calculation sheet (core without server; API + UI need the part routes of #1215)
fresh; run p2470_c_sheet "$PY" p2470_c_sheet_test.py
fresh; run p2470_c_sheet_api "$PY" p2470_c_sheet_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2470_c_sheet_ui node p2470_c_sheet_ui.js "$KALMIDO_TEST_DATA"
# 2.47.0 part E: #1654 account node survives renderSide, sidebar avatar not lazy
fresh; run p2470_e_avatar_ui node p2470_e_avatar_ui.js "$KALMIDO_TEST_DATA"
# 2.47.0 part D: #1645 producing / raw data per quotation (default, migration), #1649 purchase from the role, surplus per position (admins only), percent position, purchases of accepted quotations
fresh; run p2470_d_cost_api "$PY" p2470_d_cost_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2470_d_cost_ui node p2470_d_cost_ui.js "$KALMIDO_TEST_DATA"
# 2.47.0 part A: #1648 fill instead of skip, #1649 masters Freelancer-Rollen / Drehpersonal + their import, #1645 import columns
fresh; run p2470_a_import_api "$PY" p2470_a_import_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2470_a_roles_ui node p2470_a_roles_ui.js "$KALMIDO_TEST_DATA"
# 2.47.0 part B: #1215 parts of a quotation (title page calculation, rights, PDF pages, invoice forms; the editor)
fresh; run p2470_b_parts_api "$PY" p2470_b_parts_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2470_b_parts_ui node p2470_b_parts_ui.js "$KALMIDO_TEST_DATA"
# 2.47.0 part F: review follow-ups (#1216 no purchase in the cached shoot totals, #1649 percent positions in invoices from parts)
fresh; run p2470_f_review_api "$PY" p2470_f_review_api_test.py "$KALMIDO_TEST_DATA"
# 2.47.1 part B: fixed colour per account (#1721)
fresh; run p247c_b_api "$PY" p247c_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p247c_b_ui node p247c_b_ui.js "$KALMIDO_TEST_DATA"
# 2.47.1 part A: several chats in the chat panel (#1720)
fresh; run p247c_a_ui node p247c_a_ui.js "$KALMIDO_TEST_DATA"
# 2.49.0 lead: the fixed sign Private / organisation in the list header, the filter follows the list (#1770)
fresh; run p249_l_ui node p249_l_ui.js "$KALMIDO_TEST_DATA"
# 2.49.0 part A: Forgot your password? (#1531), the login page (#1553)
fresh; run p249_a_api "$PY" p249_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p249_a_ui node p249_a_ui.js "$KALMIDO_TEST_DATA"
# 2.49.0 part B: child accounts - start without errors, parent PIN, child tour (#1537, #1551, #1533)
fresh; run p249_b_api "$PY" p249_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p249_b_ui node p249_b_ui.js "$KALMIDO_TEST_DATA"
# 2.49.0 part C: knowledge pages (#1199: rights, organisation boundary, links, backlinks, export / import) and the mind map (#1201)
fresh; run p249_c_api "$PY" p249_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p249_c_ui node p249_c_ui.js "$KALMIDO_TEST_DATA"
# 2.49.0 part E: #1106 find people by e-mail (opt-in, confirmed), address book check, connection requests, blocks
fresh; run p249_e_api "$PY" p249_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p249_e_ui node p249_e_ui.js "$KALMIDO_TEST_DATA"
# 2.49.0 part D: ticking off softly (#1766), x in the toast (#1769), completed hidden in new lists (#1535), forwarded mails shortened (#971)
run p249_d_mailtrim "$PY" p249_d_mailtrim_test.py
fresh; run p249_d_api "$PY" p249_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p249_d_ui node p249_d_ui.js "$KALMIDO_TEST_DATA"
shard 6  # 2.49.1: the 2.48 suites run in shard 6 (shard 5 reached the 30 min CI job limit, shard 6 took 17 min)
# 2.48.0 part C: the PDF preview (#1367)
fresh; run p248_c_pdf_ui node p248_c_pdf_ui.js "$KALMIDO_TEST_DATA"
# 2.48.0 part C: lock a note with one's own password (#1642)
fresh; run p248_c_lock_api "$PY" p248_c_lock_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p248_c_lock_ui node p248_c_lock_ui.js "$KALMIDO_TEST_DATA"
# 2.48.0 part A: the file store "Ablage" (#1207): rights, organisation boundary, agents, versions, trash, links, backup; the UI
fresh; run p248_a_api "$PY" p248_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p248_a_ui node p248_a_ui.js "$KALMIDO_TEST_DATA"
# 2.48.0 part D: #1152 Paperless-ngx connection + import (fake Paperless-ngx in the container), #1356 agents suggest project / category of receipts
fresh; run p248_d_paperless_api "$PY" p248_d_paperless_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p248_d_receipts_api "$PY" p248_d_receipts_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p248_d_ui node p248_d_ui.js "$KALMIDO_TEST_DATA"
# 2.48.0 part B: #1111 documents (recognition without a server; API with OCR, mail, agents, the boundary; the area)
       run p248_b_unit "$PY" p248_b_unit_test.py
fresh; run p248_b_api "$PY" p248_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p248_b_ui node p248_b_ui.js "$KALMIDO_TEST_DATA"
shard 3  # 2.49.1: the 2.47.3 suites run in shard 3 (shard 5 reached the 30 min CI job limit, shard 3 took 19 min)
# 2.47.3 part C: contacts / clients several at once, the clients page like the contacts (#1731, #1733, #1734)
fresh; run p2473_c_api "$PY" p2473_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2473_c_ui node p2473_c_ui.js "$KALMIDO_TEST_DATA"
# 2.47.3 part D: Google photo links at the vCard import (#1738), job_parent on chat messages (#1764); uninstall command dialogs (#1729), job colours, (i) texts (#1382)
fresh; run p2473_d_api "$PY" p2473_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2473_d_ui node p2473_d_ui.js "$KALMIDO_TEST_DATA"
# 2.47.3 part B: travel expenses (#1022) + cash flow (#1652) in the office
fresh; run p2473_b_api "$PY" p2473_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2473_b_ui node p2473_b_ui.js "$KALMIDO_TEST_DATA"
# 2.95.0 (#1932): the per diem of a trip (BMF rates per year), its report (PDF / Excel / CSV), the spreadsheet import
fresh; run p295_a_api "$PY" p295_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p295_a_ui node p295_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p295_b_api "$PY" p295_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p295_b_ui node p295_b_ui.js "$KALMIDO_TEST_DATA"
# 2.47.3 part A: Office & finance without an organisation (#1360)
fresh; run p2473_a_api "$PY" p2473_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2473_a_ui node p2473_a_ui.js "$KALMIDO_TEST_DATA"
# 2.47.3 part E: DATEV booking batch (#1460), archive several lists (#1727)
fresh; run p2473_e_api "$PY" p2473_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2473_e_ui node p2473_e_ui.js "$KALMIDO_TEST_DATA"
shard 2  # 2.50.0: the 2.50 suites run in shard 2 (shard 3 took 23 min with the 2.47.3 suites, shard 2 18 min)
# 2.50.0 part B: sales pipeline (#1196) + business figures (#1197)
fresh; run p250_b_api "$PY" p250_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p250_b_ui node p250_b_ui.js "$KALMIDO_TEST_DATA"
# 2.50.0 part A: absences (#1195), resources and disposition (#1194)
fresh; run p250_a_api "$PY" p250_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p250_a_ui node p250_a_ui.js "$KALMIDO_TEST_DATA"
# 2.50.0 part C: customer view of public links (#329), approval links with a simple electronic signature (#1200)
fresh; run p250_c_api "$PY" p250_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p250_c_ui node p250_c_ui.js "$KALMIDO_TEST_DATA"
# 2.51.0 part B: an inquiry becomes a project (#1351), the setup assistant (#1358)
fresh; run p251_b_api "$PY" p251_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p251_b_ui node p251_b_ui.js "$KALMIDO_TEST_DATA"
# 2.51.0 part A: agents in the office (#1348 quotation drafts, #1350 invoice / reminder drafts, payment suggestions)
fresh; run p251_a_api "$PY" p251_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p251_a_ui node p251_a_ui.js "$KALMIDO_TEST_DATA"
# 2.51.0 part C: agents on the pin board + weekly status (#1352), time check + proposals (#1353), shoot planning (#1355)
now wed 10:00; fresh; run p251_c_api "$PY" p251_c_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p251_c_ui node p251_c_ui.js "$KALMIDO_TEST_DATA"
# 2.52.0 part B: writing events into subscribed CalDAV calendars (#1128), fake CalDAV server inside the container
fresh; run p252_b_api "$PY" p252_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p252_b_ui node p252_b_ui.js "$KALMIDO_TEST_DATA"
# 2.52.0 part A: the calendar like macOS - drag to create, move, resize, all-day and month ranges, touch (#1016)
fresh; run p252_a_ui node p252_a_ui.js "$KALMIDO_TEST_DATA"
shard 10  # 2.53.0: the 2.53 suites (and 2.52 C) run in shard 10 (shard 2 reached the 30 min CI job limit, shard 10 took 18 min)
# 2.53.0 part D: references by dragging into comment / description, reference cards, the preview card (#1449 #1440)
fresh; run p253_d_ui node p253_d_ui.js "$KALMIDO_TEST_DATA"
# 2.53.0 part E: agent tone for comments / News / chat (#1451) + tags overview (#446)
now wed 10:00; fresh; run p253_e_ui node p253_e_ui.js "$KALMIDO_TEST_DATA"
# 2.53.0 part B: list colours as accent, folder colours, card edges, "only as a dot" (#1426); workspace colours (#1474)
fresh; run p253_b_ui node p253_b_ui.js "$KALMIDO_TEST_DATA"
# 2.53.0 part C: the bell of one task - as the list / muted / urgent, set for others by list admins (#1424)
fresh; run p253_c_api "$PY" p253_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p253_c_ui node p253_c_ui.js "$KALMIDO_TEST_DATA"
# 2.53.0 part A: modules loaded on demand (#1410)
fresh; run p253_a_ui node p253_a_ui.js "$KALMIDO_TEST_DATA"
# 2.52.0 part C: #1438 address books an organisation owns (hand-over, roles, leaving / account deletion, CardDAV, way back)
fresh; run p252_c_api "$PY" p252_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p252_c_ui node p252_c_ui.js "$KALMIDO_TEST_DATA"
shard 11  # 2.80.2: the 2.55-2.62 suites run in shard 11 (shard 10 took 42 min on CI, over the 45 min limit with the rerun)
# 2.55.0 part E: the newsletter connection (#1455): fake listmonk / Brevo / CleverReach inside the container
fresh; run p255_e_api "$PY" p255_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p255_e_ui node p255_e_ui.js "$KALMIDO_TEST_DATA"
# 2.55.0 part C: #1065 settings per block (gear in Customize, popover / sheet, time tracking per client, numbers)
now wed 10:00; fresh; run p255_c_ui node p255_c_ui.js "$KALMIDO_TEST_DATA"
# 2.55.0 part A: saved arrangements per view (#1069) and arrangements sent as templates (#1068)
fresh; run p255_a_api "$PY" p255_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p255_a_ui node p255_a_ui.js "$KALMIDO_TEST_DATA"
# 2.55.0 part B: agents propose arrangements of views, the person accepts / declines (#1066)
fresh; run p255_b_api "$PY" p255_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p255_b_ui node p255_b_ui.js "$KALMIDO_TEST_DATA"
# 2.55.0 part D: statistics, client card and family on the view builder (#1067)
fresh; run p255_d_ui node p255_d_ui.js "$KALMIDO_TEST_DATA"
# 2.57.0 part B: my own colour per workspace (#1807)
fresh; run p257_b_ui node p257_b_ui.js "$KALMIDO_TEST_DATA"
# 2.57.0 part A: the sidebar's fixed head and favourites of every kind as tiles (#1798)
fresh; run p257_a_ui node p257_a_ui.js "$KALMIDO_TEST_DATA"
# 2.56.0 part C: the sidebar's share symbols in fixed columns (#1797)
fresh; run p256_c_ui node p256_c_ui.js "$KALMIDO_TEST_DATA"
# 2.56.0 part B: organisation admins change name, icon and colour of the organisation's lists (#1795)
fresh; run p256_b_api "$PY" p256_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p256_b_ui node p256_b_ui.js "$KALMIDO_TEST_DATA"
# 2.56.0 part A: a message to a job from its card, a job's own chat history (#1791 #1793)
fresh; run p256_a_api "$PY" p256_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p256_a_ui node p256_a_ui.js "$KALMIDO_TEST_DATA"
# 2.56.1 part A: #1813 the archive import finds the recipient address on the whole first page
fresh; run p2561_a_api "$PY" p2561_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.56.1 part B: symbols in the task row and the sidebar can be switched off (#1799)
fresh; run p2561_b_ui node p2561_b_ui.js "$KALMIDO_TEST_DATA"
# 2.58.0 part A: password reset / sent requests / organisation clean-up and group pictures (#1792, #1724)
fresh; run p258_a_api "$PY" p258_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.58.0 part C: an agent's list limit only for the people who manage it (#1761)
fresh; run p258_c_api "$PY" p258_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.58.0 part B: imported address books refuse moves, birthday tasks on CardDAV delete / foreign lists, part lines to the cent (#1656, #1759)
fresh; run p258_b_api "$PY" p258_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.58.0 part F: a job's own name, one news item per list edit, sealed list pictures (#1803, #1804, #1805)
fresh; run p258_f_api "$PY" p258_f_api_test.py "$KALMIDO_TEST_DATA"
# 2.58.0 part D: Office search focus, pill morph, Esc in number field, privacy switch order, Back closes dialogs (touch)
fresh; run p258_d_ui node p258_d_ui.js "$KALMIDO_TEST_DATA"
# 2.59.0 part C: #1827 job names and colours (job_name / job_parent / job_parent_name, agent_jobs.parent_id, tag + colour from the name)
fresh; run p259_c_api "$PY" p259_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p259_c_ui node p259_c_ui.js "$KALMIDO_TEST_DATA"
# 2.59.0 part A: client contact persons linked to address book contacts (#1735)
fresh; run p259_a_api "$PY" p259_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p259_a_ui node p259_a_ui.js "$KALMIDO_TEST_DATA"
# 2.59.0 part B: related tasks (#1375): the embedding service's stub mode inside the container, boundaries, switch, outage
fresh; run p259_b_api "$PY" p259_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p259_b_ui node p259_b_ui.js "$KALMIDO_TEST_DATA"
# 2.59.0 (#1375): the real embedding image (embed/Dockerfile, pinned model) builds and answers without network
run p259_b_embed "$PY" p259_b_embed_test.py
# 2.60.0 part D: environments of a project (Staging, Live), deploy webhook, deployed event (#1514), Office tabs that wrap (#1830)
fresh; run p260_d_api "$PY" p260_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p260_d_ui node p260_d_ui.js "$KALMIDO_TEST_DATA"
# 2.60.0 part C: the review step - reviewer, done only after approval, git pull requests count (#1512)
fresh; run p260_c_api "$PY" p260_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p260_c_ui node p260_c_ui.js "$KALMIDO_TEST_DATA"
shard 11  # 2.84.0: from the 2.60 B suites on in shard 11 (shard 10 had grown past the 30 min CI job limit)
# 2.60.0 part B: WIP limits per kanban column (#1510), story points and velocity (#1511)
fresh; run p260_b_api "$PY" p260_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p260_b_ui node p260_b_ui.js "$KALMIDO_TEST_DATA"
# 2.60.0 part A: sprints of project lists with burndown and review (#343)
fresh; run p260_a_api "$PY" p260_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p260_a_ui node p260_a_ui.js "$KALMIDO_TEST_DATA"
# 2.61.0 part B: photo metadata (GPS, camera) removed on upload, the capture date of documents (#1819)
fresh; run p261_b_api "$PY" p261_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p261_b_ui node p261_b_ui.js "$KALMIDO_TEST_DATA"
# 2.61.0 part A: virus scan of uploads with a fake clamd, unchecked marks, the later scan, the type from the content (#1818)
fresh; run p261_a_api "$PY" p261_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p261_a_ui node p261_a_ui.js "$KALMIDO_TEST_DATA"
# 2.61.0 part C: text recognition of task, project and Ablage files in the background, search, catch-up (#1820)
fresh; run p261_c_api "$PY" p261_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p261_c_ui node p261_c_ui.js "$KALMIDO_TEST_DATA"
# 2.62.0 part C: "Change position…" submenu, sticky settings head, Documents reload on open (#1853 #1485 #1844)
fresh; run p262_c_ui node p262_c_ui.js "$KALMIDO_TEST_DATA"
# 2.62.0 part B: #1854 comments by agents in the bell: all / only replies to me
fresh; run p262_b_api "$PY" p262_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.62.0 part A: sending once in the chats (#1530), pinned chat messages (#1848)
fresh; run p262_a_api "$PY" p262_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p262_a_ui node p262_a_ui.js "$KALMIDO_TEST_DATA"
shard 14  # 2.124.2: the 2.63-2.66 suites (was shard 2: shard 2 ran into the 45 min CI limit)
# 2.63.0 part D: one space list for knowledge pages, conversation on the job card (#1857 #1482)
fresh; run p263_d_ui node p263_d_ui.js "$KALMIDO_TEST_DATA"
# 2.63.0 part A: the public report form - type, file, spam guard, status link (#1513)
fresh; run p263_a_api "$PY" p263_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p263_a_ui node p263_a_ui.js "$KALMIDO_TEST_DATA"
# 2.63.0 part C: undo of "delete all times" keeps client_id, templates carry notepads + colours, own times only for editors (#1523)
fresh; run p263_c_api "$PY" p263_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p263_c_ui node p263_c_ui.js "$KALMIDO_TEST_DATA"
# 2.63.0 part B: #1513 the customer portal (status page, answers, sign-in, mails, agents) and the task panel's customer report
fresh; run p263_b_api "$PY" p263_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p263_b_ui node p263_b_ui.js "$KALMIDO_TEST_DATA"
# 2.64.0: #1864 private files encrypted at rest (account keys), own container with KALMIDO_SECRET_KEY
fresh; run p264_api "$PY" p264_api_test.py "$KALMIDO_TEST_DATA"
# 2.65.0 part C: start-up performance budget (static tool, deliberately oversized state turns it red) + start time in the browser
       run perf_budget "$PY" perf_budget_test.py
# 2.65.0 part A: GET /api/state with 5000 tasks: time, size, gzip, the same state for every viewer (#1505)
fresh; run p265_a_api "$PY" p265_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.65.0 part D: long lists draw only the rows near the visible part (#1825)
fresh; run p265_d_ui node p265_d_ui.js "$KALMIDO_TEST_DATA"
# 2.65.0 part B: more areas load on demand (agent chat, calendar, statistics, knowledge pages, mind maps, PDF, documents) + their stylesheets
fresh; run p265_b_ui node p265_b_ui.js "$KALMIDO_TEST_DATA"
# 2.66.0 part B: merging duplicate clients (#1835): dry overview, move + undo, locked invoices, billed time, rights
fresh; run p266_b_api "$PY" p266_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p266_b_ui node p266_b_ui.js "$KALMIDO_TEST_DATA"
# 2.66.0 part A: merging duplicate contacts (#1835): links, CardDAV, undo, rights
fresh; run p266_a_api "$PY" p266_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p266_a_ui node p266_a_ui.js "$KALMIDO_TEST_DATA"
shard 12  # 2.80.3: the 2.64.1-2.64.3 suites run in shard 12 (2.80.0: shard 4; shard 4 took 38 min on CI with them)
# 2.64.1 part C: #1817 lock per list - client data layer
fresh; run p264a_c_ui node p264a_c_ui.js "$KALMIDO_TEST_DATA"
# 2.64.1 part D: #1817 lock per list - dialogs and display, #1518
fresh; run p264a_d_ui node p264a_d_ui.js "$KALMIDO_TEST_DATA"
# 2.64.1 part A: #1817 lock per list - server core
fresh; run p264a_a_api "$PY" p264a_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.64.1 part B: #1817 lock per list - other ways, neutral texts, copies
fresh; run p264a_b_api "$PY" p264a_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.64.2 parts C + D: #1817 lock per list stage 2 - the list channel, pushes in the recipient's language
fresh; run p264b_c_api "$PY" p264b_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.64.2 parts C + D: #1817 lock per list stage 2 - the list channel in the web app, safety numbers
fresh; run p264b_c_ui node p264b_c_ui.js "$KALMIDO_TEST_DATA"
# 2.64.2 part A: #1817 lock per list stage 2 - key change and re-encryption
fresh; run p264b_a_api "$PY" p264b_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p264b_a_ui node p264b_a_ui.js "$KALMIDO_TEST_DATA"
# 2.64.2 part B: #1817 lock per list stage 2 - list files (server)
fresh; run p264b_b_api "$PY" p264b_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.64.2 part B: #1817 lock per list stage 2 - list files (web app)
fresh; run p264b_b_ui node p264b_b_ui.js "$KALMIDO_TEST_DATA"
# 2.64.3 part A: #1817 lock per knowledge space - server routes, guard of the page routes, members, rotation
fresh; run p264c_a_api "$PY" p264c_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.64.3 part B: #1817 lock per knowledge space - client (encrypted wiki space in the browser)
fresh; run p264c_b_ui node p264c_b_ui.js "$KALMIDO_TEST_DATA"
shard 13  # 2.84.0: from the 2.67 suites on in their own shard (shard 10 with every suite since 2.53 reached 45 min in a full run; 13 since the merge with 2.80.3)
# 2.67.0 part A: fixed costs from a spreadsheet in the cash flow, net / gross, the monthly check task (#1838)
fresh; run p267_a_api "$PY" p267_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p267_a_ui node p267_a_ui.js "$KALMIDO_TEST_DATA"
# 2.67.0 part B: the dependency chain moves along, Pull the chain in (#1865)
fresh; run p267_b_api "$PY" p267_b_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p267_b_ui node p267_b_ui.js "$KALMIDO_TEST_DATA"
# 2.68.0 part A: old data into the office with the person's own agent (import proposals, fixed costs; #1839)
fresh; run p268_a_api "$PY" p268_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p268_a_ui node p268_a_ui.js "$KALMIDO_TEST_DATA"
# 2.69.0 part B: a Paperless-ngx import takes over the matching rules (any / all / literal / regex / fuzzy, auto reported) and
# trains the classifier once per run (#1847)
fresh; run p269_b_api "$PY" p269_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.69.0 part A: Paperless-ngx import on a hosted server (public HTTPS), quota, queue, export ZIP upload + import
fresh; run p269_a_api "$PY" p269_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p269_a_ui node p269_a_ui.js "$KALMIDO_TEST_DATA"
# 2.70.0 part A: a meeting becomes tasks (#1354): photos, list choice, the chat's card, part apply, freelancer
fresh; run p270_a_api "$PY" p270_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p270_a_ui node p270_a_ui.js "$KALMIDO_TEST_DATA"
# 2.70.0 part B: tidy up contacts - an agent proposes duplicates, the person merges them (#1357)
fresh; run p270_b_api "$PY" p270_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p270_b_ui node p270_b_ui.js "$KALMIDO_TEST_DATA"
# 2.70.0 part C: contracts in view (#1359): contract_notice, the proposal kind notice, health lists and the journal stay closed
fresh; run p270_c_api "$PY" p270_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p270_c_ui node p270_c_ui.js "$KALMIDO_TEST_DATA"
shard 1  # 2.80.0: the 2.71-2.73 suites run in shard 1 (shard 10 full)
# 2.71.0 part B: a task in several lists without a copy (#1459)
fresh; run p271_b_api "$PY" p271_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p271_b_ui node p271_b_ui.js "$KALMIDO_TEST_DATA"
# 2.71.0 part A: rules of a list (When ... then ...), run as their creator, agents propose (#1457)
fresh; run p271_a_api "$PY" p271_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p271_a_ui node p271_a_ui.js "$KALMIDO_TEST_DATA"
# 2.72.0 part A: #1333 the household budget (server), own container with KALMIDO_SECRET_KEY
fresh; run p272_a_budget_api "$PY" p272_a_budget_api_test.py "$KALMIDO_TEST_DATA"
# 2.72.0 part B: the household budget in the app (#1333)
fresh; run p272_b_budget_ui node p272_b_budget_ui.js "$KALMIDO_TEST_DATA"
# 2.73.0 part A: several Kalmido servers in one app (#661): server accounts, connection code, the other server's API (the
# test server connects to itself; a misbehaving stub server inside the container), SSRF guard, hosted = https only
fresh; run p273_a_api "$PY" p273_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p273_a_ui node p273_a_ui.js "$KALMIDO_TEST_DATA"
# 2.73.0 part C: several servers in one app, the merged view (#661)
fresh; run p273_c_ui node p273_c_ui.js "$KALMIDO_TEST_DATA"
# 2.73.0 release: part A's server routes with part C's merged view (#661), the test server as "the other server"
fresh; run p273_l_ui node p273_l_ui.js "$KALMIDO_TEST_DATA"
# 2.73.0 part B: moving an account -- account export + import with the mapping of people (#1473)
fresh; run p273_b_api "$PY" p273_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p273_b_ui node p273_b_ui.js "$KALMIDO_TEST_DATA"
shard 21  # 22.10.2026 (2.161.2 CI): was shard 3 (shard 3 ran into the 45 min CI limit in most runs since 2.151.1); 2.80.0: the 2.74-2.80 suites run here (shard 10 ran past the 45 min Mac limit with the 2.6x/2.7x suites)
# 2.74.0 part A: the supporter licence (#338; own key pair in a temp folder, a hosted restart)
fresh; run p274_a_api "$PY" p274_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p274_a_ui node p274_a_ui.js "$KALMIDO_TEST_DATA"
# 2.74.0 part B (#1653): Office & finance in the browser demo (client, service, quotation, invoice, payments, sums / VAT like the
# server, the print view instead of the PDF, no network) (no container)
fresh; run p274_b_demo node p274_b_demo_test.js
# 2.75.0 part A: built-in assistant (#1411)
fresh; run p275_a_api "$PY" p275_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.75.0 part B: assistant UI (#1411)
fresh; run p275_b_ui node p275_b_ui.js "$KALMIDO_TEST_DATA"
# 2.76.0 part A: the pack catalogue (fake catalogue in the container, install / update / uninstall per office area)
fresh; run p276_a_packs_api "$PY" p276_a_packs_api_test.py "$KALMIDO_TEST_DATA"
# 2.76.0 part B: Office settings > Packs: catalogue search, badges, install / uninstall, undo (#1023)
fresh; run p276_b_ui node p276_b_ui.js "$KALMIDO_TEST_DATA"
# 2.78.0: "Duplicate list" - the copy with sections, tasks, dates, notepads; done optional; who may; REST API (#1881)
fresh; run p278_dup_api "$PY" p278_dup_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p278_dup_ui node p278_dup_ui.js "$KALMIDO_TEST_DATA"
# 2.79.0: security fixes of audit #476 part 1 (H1 ICS attendees, M1 app passwords, M2 admin scopes, M4 link lock, M5 child accounts, M6 health time, M8 backup folders, M9 proxy default)
fresh; run p279_sec_api "$PY" p279_sec_api_test.py "$KALMIDO_TEST_DATA"
shard 16  # 2.124.2: the 2.81 suites (was shard 13: over 45 min with the 2.99-2.125 suites)
# 2.81.0 part B: correct archived office documents (client, tax lines, paid, history, #1834), DATEV customer number of locked invoices (#1867)
fresh; run p281_b_api "$PY" p281_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.81.0 part A: #1852 stale contact link, #1466 agent contact persons
fresh; run p281_a_api "$PY" p281_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.81.0 part D: Paperless ZIP checked in the background (#1874), runs that lost their claim, one key per export (#1875)
fresh; run p281_d_api "$PY" p281_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.83.0 part A: the organisation's view hides the private modules (#1845)
fresh; run p283_a_ui node p283_a_ui.js "$KALMIDO_TEST_DATA"
# 2.83.0 part A: organisation-wide lists - assigned without joining: assignable with org_edit, Today, calendar feed, CalDAV (#1725)
fresh; run p283_a_api "$PY" p283_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.83.0 part C: themes, header strips of lists and folders, progress rings, tick animation, the K on empty pages (#1427)
fresh; run p283_c_api "$PY" p283_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p283_c_ui node p283_c_ui.js "$KALMIDO_TEST_DATA"
# 2.84.0 part A: e-mail as an input of the hub, mails filed with clients / projects (#1198)
fresh; run p284_a_api "$PY" p284_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p284_a_ui node p284_a_ui.js "$KALMIDO_TEST_DATA"
# 2.85.0 part A: test clock gives the Berlin calendar day (#1863)
fresh; run testclock "$PY" testclock_test.py
# 2.85.0 part B: feeds (#1162) - follow, RSS/Atom/RDF, SSRF guard, DTD refused, read later, OPML, rights; the view (fake feed server in the container)
fresh; run p285_b_api "$PY" p285_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p285_b_ui node p285_b_ui.js "$KALMIDO_TEST_DATA"
# 2.87.9 part C: the office menu with four groups (#1917), computer + phone
fresh; run p287b_c_ui node p287b_c_ui.js "$KALMIDO_TEST_DATA"
# 2.88.0 part A: offers (quotes) with versions in the cash flow plan (#1915)
fresh; run p288_a_api "$PY" p288_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p288_a_ui node p288_a_ui.js "$KALMIDO_TEST_DATA"
# 2.88.0 part B: user admin for hundreds of accounts, delete with list hand-over (#1980)
fresh; run p288_b_api "$PY" p288_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p288_b_ui node p288_b_ui.js "$KALMIDO_TEST_DATA"
# 2.89.0 (#1916): Tabellen - A engine/API, B screen, C import/export + agent tools, D step 2
fresh; run p289_a_api "$PY" p289_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p289_b_api "$PY" p289_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p289_b_ui node p289_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p289_c_api "$PY" p289_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p289_c_ui node p289_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p289_d_api "$PY" p289_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p289_d_ui node p289_d_ui.js "$KALMIDO_TEST_DATA"
# 2.92.0 (#1925 #1926 #1931 #2008-#2010): business contracts, file preview, equipment value, fixes from 2.88
fresh; run p292_a_api "$PY" p292_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p292_a_ui node p292_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p292_b_api "$PY" p292_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p292_b_ui node p292_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p292_c_api "$PY" p292_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p292_c_ui node p292_c_ui.js "$KALMIDO_TEST_DATA"
fresh; run p292_d_ui node p292_d_ui.js "$KALMIDO_TEST_DATA"
# 2.94.0 (#1929, #1930, #2024): appointment booking, leads, chat Enter
fresh; run p294_a_api "$PY" p294_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p294_a_ui node p294_a_ui.js "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p294_b_api "$PY" p294_b_api_test.py "$KALMIDO_TEST_DATA"  # 2.149.0 (#2512)
fresh; run p294_b_ui node p294_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p294_c_ui node p294_c_ui.js "$KALMIDO_TEST_DATA"
shard 4  # 2.99.0: the 2.99 suites run in shard 4 (23 min in run 212; shard 12 got the 2.98 suites, shard 13 ran past the 45 min CI limit)
# 2.99.0 part A: wiki ZIP import keeps PDFs and images as page attachments (#2182)
fresh; run p299_a_api "$PY" p299_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.99.0 part B: one ... menu on wiki pages, chat composer icons aligned (#2183 #2185)
fresh; run p299_b_ui node p299_b_ui.js "$KALMIDO_TEST_DATA"
# 2.99.0 part C: the quotation PDF after the online acceptance carries the acceptance note (#2195)
fresh; run p299_c_api "$PY" p299_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.99.0 part D: office documents - fixed recipient fields rest (name addition, own company fields, 3-line company name), 44 px fields (#2188 #2025)
fresh; run p299_d_api "$PY" p299_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p299_d_ui node p299_d_ui.js "$KALMIDO_TEST_DATA"
# 2.99.0 part E: the sidebar group Exchange stays short (recent chats, pinned people / agents, "All people") (#2187)
fresh; run p299_e_ui node p299_e_ui.js "$KALMIDO_TEST_DATA"
shard 13  # back to shard 13 for the suites after this block
# 2.86.0 (#1896): hardening from audit #476 part 1, groups A-E
fresh; run p286_a_api "$PY" p286_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p286_b_api "$PY" p286_b_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p286_c_api "$PY" p286_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p286_d_api "$PY" p286_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p286_e_api "$PY" p286_e_api_test.py "$KALMIDO_TEST_DATA"
# 2.66.1 part B: the workspace switch reloads every open view with a workspace link (#1945), the guard list of those views
fresh; run p2661_b_ui node p2661_b_ui.js "$KALMIDO_TEST_DATA"
# 2.87.0 (#1983 #1984): organisation boundary of event invitations and list hand-overs (audit T3 H1 + H2)
fresh; run p287_a_api "$PY" p287_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.87.9 part D (#1965): drags run once per frame, stored on release
fresh; run p287b_d_ui node p287b_d_ui.js "$KALMIDO_TEST_DATA"
# 2.87.9 part A (#1919 / #1918): every area as a person without an organisation (the freelancer parity sweep)
fresh; run p287b_a_freelancer_api "$PY" p287b_a_freelancer_api_test.py "$KALMIDO_TEST_DATA"
# 2.87.9 part A (#1913): an organisation's own picture as its symbol (admins set it, members get it, sealed)
fresh; run p287b_a_api "$PY" p287b_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.87.9 part B (#1940 #1938 #1936 #1935 #1934): import target confirmation, Paperless in the settings, search
fresh; run p287b_b_api "$PY" p287b_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p287b_b_ui node p287b_b_ui.js "$KALMIDO_TEST_DATA"
# 2.96.0 part A (#1941): files, folders and documents between the private space and an organisation
fresh; run p296_a_api "$PY" p296_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p296_a_ui node p296_a_ui.js "$KALMIDO_TEST_DATA"
# 2.96.0 part B (#1941): wiki pages / folders and tables between the private space and an organisation
fresh; run p296_b_api "$PY" p296_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p296_b_ui node p296_b_ui.js "$KALMIDO_TEST_DATA"
# 2.96.0 part C (#2015): one thread card per job in the agent chat, the chat filter
fresh; run p296_c_api "$PY" p296_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p296_c_ui node p296_c_ui.js "$KALMIDO_TEST_DATA"
# 2.153.0 part A: correspondence -- letters, PDF, signature, status (#2028)
now wed 10:00; fresh; run p2106_a_api "$PY" p2106_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2106_a_ui node p2106_a_ui.js "$KALMIDO_TEST_DATA"
# 2.153.0 part B: letter <-> document links, history, deadline task, follow-up, reference line (#2028)
fresh; run p2106_b_api "$PY" p2106_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2106_b_ui node p2106_b_ui.js "$KALMIDO_TEST_DATA"
# 2.153.0 part C: letters by e-mail with the answer linked, text blocks (#2029 #2030)
fresh; run p2106_c_api "$PY" p2106_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2106_c_ui node p2106_c_ui.js "$KALMIDO_TEST_DATA"
# 2.153.0 part D: agents draft letters (#2031)
fresh; run p2106_d_api "$PY" p2106_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2106_d_ui node p2106_d_ui.js "$KALMIDO_TEST_DATA"
# 2.153.0 (#1962): a chat of its own per job (job_id on a person's message, start line, progress in the job's chat)
fresh; run p2107_api "$PY" p2107_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2107_ui node p2107_ui.js "$KALMIDO_TEST_DATA"
# 2.96.0 part D (#1941 / #1918): an organisation's export into the private space, the own absence area in "Private"
fresh; run p296_d_api "$PY" p296_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.96.0 part E (#1941): the separation after a move between private and organisation; moved documents are learned by the target
fresh; run p296_e_api "$PY" p296_e_api_test.py "$KALMIDO_TEST_DATA"
shard 4  # 2.102.0: the 2.102 suites run in shard 4 (shard 13 near the 45 min limit, shard 4 took 18 min)
# 2.102.0 part A (#1988 #2003 #2006): organisation trash for deleted lists, calendar invitations
fresh; run p2102_a_api "$PY" p2102_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2102_a_ui node p2102_a_ui.js "$KALMIDO_TEST_DATA"
# 2.102.0 part B (#2197 #2204 #2206): news bundles and counts, chat send hint, selection bar padding
fresh; run p2102_b_ui node p2102_b_ui.js "$KALMIDO_TEST_DATA"
# 2.102.0 part C (#2201 #2208 #2210): questionnaire customer link, polls/forms on demand, pin agents
fresh; run p2102_c_api "$PY" p2102_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2102_c_ui node p2102_c_ui.js "$KALMIDO_TEST_DATA"
# 2.102.0 part D (#1994 #1996 #1997): pool from env + health, migrations table, background worker
fresh; run p2102_d_api "$PY" p2102_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.102.0 part E (#1995 #1998 #1999): type check, drag library, layer linter + client error report
fresh; run p2102_e_api "$PY" p2102_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2102_e_ui node p2102_e_ui.js "$KALMIDO_TEST_DATA"
# 2.119.1 part A: contacts - CSV import/export, more than 500 contacts, duplicate hint, manage groups (#2080 #2081 #2084 #2085)
fresh; run p21191_a_api "$PY" p21191_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21191_a_ui node p21191_a_ui.js "$KALMIDO_TEST_DATA"
# 2.119.1 part B: contact card - client from contact, history, address as map link (#2082 #2083 #2086)
fresh; run p21191_b_api "$PY" p21191_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21191_b_ui node p21191_b_ui.js "$KALMIDO_TEST_DATA"
# 2.119.1 part C: framework contracts between workspaces, undo of a list delete keeps the list active (#2298 #2304)
fresh; run p21191_c_api "$PY" p21191_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21191_c_ui node p21191_c_ui.js "$KALMIDO_TEST_DATA"
# 2.119.1 part D: live panel window redraw flake, 44 px select marks in documents (#2310 #2206)
fresh; run p21191_d_ui node p21191_d_ui.js "$KALMIDO_TEST_DATA"
shard 13  # back to shard 13 for the 2.97 suites
# 2.97.0 part A: bookmarks (#1950)
fresh; run p297_a_api "$PY" p297_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p297_a_ui node p297_a_ui.js "$KALMIDO_TEST_DATA"
# 2.97.0 part B: customer display name, address from the customer (#1951)
fresh; run p297_b_api "$PY" p297_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p297_b_ui node p297_b_ui.js "$KALMIDO_TEST_DATA"
# 2.97.1: the sender line with the company name (#2224)
fresh; run p2971_api "$PY" p2971_api_test.py "$KALMIDO_TEST_DATA"
# 2.97.0 part C: office data between the personal office and an organisation (#2049)
fresh; run p297_c_api "$PY" p297_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p297_c_ui node p297_c_ui.js "$KALMIDO_TEST_DATA"
# 2.97.0 part D: locked wiki spaces re-keyed in the browser on a move, orphan clean-up (#2050 #2051)
fresh; run p297_d_api "$PY" p297_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p297_d_ui node p297_d_ui.js "$KALMIDO_TEST_DATA"
shard 12  # 2.98.1: the 2.98 suites run in shard 12 (shard 13 ran past the 45 min CI job limit with them, shard 12 took 18 min)
# 2.98.0 part A: scheduling polls (#1953)
fresh; run p298_a_api "$PY" p298_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p298_a_ui node p298_a_ui.js "$KALMIDO_TEST_DATA"
# 2.98.0 part B: questionnaires (#1954)
fresh; run p298_b_api "$PY" p298_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p298_b_ui node p298_b_ui.js "$KALMIDO_TEST_DATA"
# 2.98.0 part C: office menu as a rail on the left, resizable tables + own window (#2180 #2181)
fresh; run p298_c_ui node p298_c_ui.js "$KALMIDO_TEST_DATA"
# 2.98.0 part D: longer tick / create animation, document guesses only where they fit, comment names (#2163 #2178 #2184)
fresh; run p298_d_api "$PY" p298_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.153.0: custom fields of documents (#2179)
fresh; run p2108_a_api "$PY" p2108_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2108_a_ui node p2108_a_ui.js "$KALMIDO_TEST_DATA"
# 2.152.0 (#2165): retention switch + GET /api/admin/retention (leader)
fresh; run p2103_r_api "$PY" p2103_r_api_test.py "$KALMIDO_TEST_DATA"
# 2.152.0 part A (#2164 #2167 #2174): account purge, organisation delete with retention, foreign keys
fresh; run p2103_a_api "$PY" p2103_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2103_a_ui node p2103_a_ui.js "$KALMIDO_TEST_DATA"
# 2.152.0 part B (#2165 #2172): trash periods, backups (age limit, deletion journal, list heads)
now wed 10:00; fresh; run p2103_b_api "$PY" p2103_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2103_b_ui node p2103_b_ui.js "$KALMIDO_TEST_DATA"
# 2.152.0 part C (#2168 #2169): office locks for taxable records, logbook closing + visible change log
fresh; run p2103_c_api "$PY" p2103_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2103_c_ui node p2103_c_ui.js "$KALMIDO_TEST_DATA"
# 2.152.0 part D (#2170 #2171 #2173 #2175): newsletter suppression, log/session periods, file orphans, agent chat delete
fresh; run p2103_d_api "$PY" p2103_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2103_d_ui node p2103_d_ui.js "$KALMIDO_TEST_DATA"
# 2.87.9 part E (#1914 #1920 #1909 #1933 #1937 #1952 #1963): polish
fresh; run p287b_e_ui node p287b_e_ui.js "$KALMIDO_TEST_DATA"
shard 15  # 2.124.2: the 2.90-2.93 and 2.99.1 suites (was shard 11: over 45 min)
# 2.90.0 part A (#1921): bookkeeping light (EUeR, VAT return figures, tax reserve, receipt photo)
fresh; run p290_a_api "$PY" p290_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p290_a_ui node p290_a_ui.js "$KALMIDO_TEST_DATA"
# 2.90.0 part B (#1921): bank reconciliation (CSV / CAMT import, matching)
fresh; run p290_b_api "$PY" p290_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p290_b_ui node p290_b_ui.js "$KALMIDO_TEST_DATA"
# 2.90.0 part C (#1922): tax dates as recurring tasks
fresh; run p290_c_api "$PY" p290_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p290_c_ui node p290_c_ui.js "$KALMIDO_TEST_DATA"
# 2.91.0 part A (#1923): invoice series (recurring invoices, drafts or sent, cash flow)
fresh; run p291_a_api "$PY" p291_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p291_a_ui node p291_a_ui.js "$KALMIDO_TEST_DATA"
# 2.91.0 part B (#1924): subscriptions and tools (notice period, users, renewal reminder, hardly used)
fresh; run p291_b_api "$PY" p291_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p291_b_ui node p291_b_ui.js "$KALMIDO_TEST_DATA"
# 2.99.1 part A: video review with comments at the time code, links only (#1959)
fresh; run p2991_a_api "$PY" p2991_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2991_a_ui node p2991_a_ui.js "$KALMIDO_TEST_DATA"
# 2.99.1 part C: video sign-offs for agents (API v1 + MCP, #1959)
fresh; run p2991_c_api "$PY" p2991_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.99.1 part B: contributing national e-invoice formats by pull request (#1961)
fresh; run p2991_b "$PY" p2991_b_test.py "$KALMIDO_TEST_DATA"
# 2.93.0 (#1927 #1928): document templates with signature, logbook
fresh; run p293_a_api "$PY" p293_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p293_a_ui node p293_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p293_b_api "$PY" p293_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p293_b_ui node p293_b_ui.js "$KALMIDO_TEST_DATA"
# 2.114.2 part A (#2263): a finalised quotation that was never sent can be deleted by an admin
fresh; run p21142_a_api "$PY" p21142_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21142_a_ui node p21142_a_ui.js "$KALMIDO_TEST_DATA"
# 2.114.2 part B (#2264): settings field errors below the field, the field keeps its width
fresh; run p21142_b_ui node p21142_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21143_a_ui node p21143_a_ui.js "$KALMIDO_TEST_DATA"
# 2.114.4 part A: quotation / document PDF layout - footer, phone, page line, VAT note, option sum, producing row (#2271-#2277 #2282 #2284)
fresh; run p21144_a_api "$PY" p21144_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.114.4 part B (#2270): order confirmation block in the quotation optional (setting + per quotation)
fresh; run p21144_b_api "$PY" p21144_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21144_b_ui node p21144_b_ui.js "$KALMIDO_TEST_DATA"
# 2.114.5 (#2300 #2270): quotation PDF page 1 tightened - order confirmation at the end, VAT column, option rows, footer
fresh; run p21145_api "$PY" p21145_api_test.py "$KALMIDO_TEST_DATA"
# 2.114.4 part C: documents - PDF preview, variable buttons, finish with empty variables (#2278 #2280 #2281)
fresh; run p21144_c_api "$PY" p21144_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21144_c_ui node p21144_c_ui.js "$KALMIDO_TEST_DATA"
# 2.114.4 part D: invoice from quotation dialog texts, travel costs allowance as main amount (#2269 #2286)
fresh; run p21144_d_ui node p21144_d_ui.js "$KALMIDO_TEST_DATA"
# 2.117.0 part A: travel costs - to-date calendar anchor, row menu with delete, person filter, own purposes (#2290 #2287 #2291 #2292)
fresh; run p2117_a_api "$PY" p2117_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2117_a_ui node p2117_a_ui.js "$KALMIDO_TEST_DATA"
# 2.117.0 part B: documents sample templates, framework contract PDF attachments (#2283 #2285)
fresh; run p2117_b_api "$PY" p2117_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2117_b_ui node p2117_b_ui.js "$KALMIDO_TEST_DATA"
# 2.117.0 part C: PDF metadata "Kalmido v<version>", agent chat filter compact on phones (#2262 #2260)
fresh; run p2117_c_api "$PY" p2117_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.118.0 part A (#2265): quotation counter per client / project, building block {version}
fresh; run p2118_a_api "$PY" p2118_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2118_a_ui node p2118_a_ui.js "$KALMIDO_TEST_DATA"
# 2.118.0 part B (#2297): one switch for progress (line + ring) in the sidebar, kept in the account
fresh; run p2118_b_ui node p2118_b_ui.js "$KALMIDO_TEST_DATA"
# 2.119.0 part A: entertainment receipts as office module (#2288)
fresh; run p2119_a_api "$PY" p2119_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2119_a_ui node p2119_a_ui.js "$KALMIDO_TEST_DATA"
# 2.119.0 part B: filled active icon buttons, send-key hint in the agent chat side window, pin agents in "All people" (#2301 #2302 #2210)
fresh; run p2119_b_ui node p2119_b_ui.js "$KALMIDO_TEST_DATA"
shard 13  # 2.98.1: the 2.99-2.123 C suites (new ones go to shard 17 below)
# 2.114.1 part A: bank button "Match" wording + 44 px buttons, empty heading, producing checkbox (#2017 #2254 #2255)
fresh; run p21141_a_ui node p21141_a_ui.js "$KALMIDO_TEST_DATA"
# 2.114.1 part B: books reload after bank match, matched receipts in the cash flow (#2016 #2018)
fresh; run p21141_b_api "$PY" p21141_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21141_b_ui node p21141_b_ui.js "$KALMIDO_TEST_DATA"
# 2.114.1 part C: transfer of rights on its own last page of the quotation PDF (#2258)
fresh; run p21141_c_api "$PY" p21141_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.122.4 part A: rights - org overview for the instance admin, edit right, feeds once, video sign-off rests (#1724 #1906 #2215 #2217)
fresh; run p21224_a_api "$PY" p21224_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.122.4 part B: office - rights once in the quotation PDF, storage counts meal/contract PDFs, CSV formula guard (#2261 #2316 #2317)
fresh; run p21224_b_api "$PY" p21224_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.122.4 part C: phone sizes - office settings selects, contact import notice, video sign-off targets, bookmarks (#2326 #2348 #2217 #2223)
fresh; run p21224_c_ui node p21224_c_ui.js "$KALMIDO_TEST_DATA"
# 2.120.0 part A: progress and final invoices, cash discount (#2087)
now wed 10:00; fresh; run p2120_a_api "$PY" p2120_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2120_a_ui node p2120_a_ui.js "$KALMIDO_TEST_DATA"
# 2.120.0 part B: client portal with quotations, invoices and payment state (#2088)
fresh; run p2120_b_api "$PY" p2120_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2120_b_ui node p2120_b_ui.js "$KALMIDO_TEST_DATA"
# 2.120.0 part C: DATEV export with incoming receipts and travel costs (#2090)
fresh; run p2120_c_api "$PY" p2120_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2120_c_ui node p2120_c_ui.js "$KALMIDO_TEST_DATA"
# 2.120.0 part D: delivery note / proof of work, timesheet as invoice attachment (#2089)
fresh; run p2120_d_api "$PY" p2120_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2120_d_ui node p2120_d_ui.js "$KALMIDO_TEST_DATA"
# 2.120.0 part E: own letterhead as background PDF (#2091)
fresh; run p2120_e_api "$PY" p2120_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2120_e_ui node p2120_e_ui.js "$KALMIDO_TEST_DATA"
# 2.121.0 part A: receipt extraction: supplier, VAT rate, net / gross, invoice number (#2092)
fresh; run p2121_a_api "$PY" p2121_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2121_a_ui node p2121_a_ui.js "$KALMIDO_TEST_DATA"
# 2.121.0 part B: cash book (#2095)
fresh; run p2121_b_api "$PY" p2121_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2121_b_ui node p2121_b_ui.js "$KALMIDO_TEST_DATA"
# 2.121.0 part C: bill a receipt on to a client (#2094), agents suggest amount and VAT (#2096)
fresh; run p2121_c_api "$PY" p2121_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2121_c_ui node p2121_c_ui.js "$KALMIDO_TEST_DATA"
# 2.121.0 lead: receipt categories with an SKR03 / SKR04 account (#2093)
fresh; run p2121_d_api "$PY" p2121_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.123.0 part A: page text sealed at rest (#2105), page history (#2102), search with word index (#2106)
fresh; run p2123_a_api "$PY" p2123_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2123_a_ui node p2123_a_ui.js "$KALMIDO_TEST_DATA"
# 2.123.0 part B: share a page / folder: read only, guest, public link (#2104)
fresh; run p2123_b_api "$PY" p2123_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2123_b_ui node p2123_b_ui.js "$KALMIDO_TEST_DATA"
# 2.123.0 part C: pictures from the Ablage in pages (#2103), [[datei:]] / [[tabelle:]] links (#2107), checkboxes as tasks (#2108)
fresh; run p2123_c_api "$PY" p2123_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2123_c_ui node p2123_c_ui.js "$KALMIDO_TEST_DATA"
shard 17  # 2.124.2: new suites go here (shard 13 keeps the 2.99-2.123 C suites above)
# 2.126.2 part A: page suggestions above the phone keyboard, checkbox "+" without overlap, search edge case (#2363), "Mentioned in" on sheets (#2357)
fresh; run p21262_a_api "$PY" p21262_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21262_a_ui node p21262_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2172_a_edit_ui node p2172_a_edit_ui.js "$KALMIDO_TEST_DATA"
# 2.126.2 part B: link of a gone creator shown as ended, unreadable sealed text is an error (#2358), news entry for shared pages (#2355)
fresh; run p21262_b_api "$PY" p21262_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21262_b_ui node p21262_b_ui.js "$KALMIDO_TEST_DATA"
# 2.123.0 part D: cash flow: opening balance, manual corrections, reconciliation (#2341); installment list number format (#2351)
fresh; run p2123_d_api "$PY" p2123_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2123_d_ui node p2123_d_ui.js "$KALMIDO_TEST_DATA"
# 2.122.0 part A: file request link, clients upload documents (#2097)
fresh; run p2122_a_api "$PY" p2122_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2122_a_ui node p2122_a_ui.js "$KALMIDO_TEST_DATA"
# 2.122.0 part B: tags in the file store (#2099), document search with several filters + ZIP (#2294), shift-click ranges (#2295)
fresh; run p2122_b_api "$PY" p2122_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2122_b_ui node p2122_b_ui.js "$KALMIDO_TEST_DATA"
# 2.122.0 part C: create documents via API (#2098), CSV of the document list (#2100), OCR languages (#2101), swipe in news (#2314)
fresh; run p2122_c_api "$PY" p2122_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2122_c_ui node p2122_c_ui.js "$KALMIDO_TEST_DATA"
# 2.122.0 part D: yearly VAT return only (#2315)
fresh; run p2122_d_api "$PY" p2122_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2122_d_ui node p2122_d_ui.js "$KALMIDO_TEST_DATA"
# 2.122.3 part A: office - one amount at 0 % VAT, import/export on the settings page, empty areas link there (#2333 #2335)
fresh; run p21223_a_api "$PY" p21223_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21223_a_ui node p21223_a_ui.js "$KALMIDO_TEST_DATA"
# 2.122.3 part B: drag a single task onto another = subtask (#2334)
fresh; run p21223_b_ui node p21223_b_ui.js "$KALMIDO_TEST_DATA"
# 2.122.3 part C: chat - "Show more" right under the shortened message (#2340)
fresh; run p21223_c_ui node p21223_c_ui.js "$KALMIDO_TEST_DATA"
# 2.126.0 part A: office + documents fixes (#1966 #1967 #1970 #1971 #1979)
fresh; run p2126_a_api "$PY" p2126_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.126.0 part B: agent fixes (#1973 #1974 #1975 #1978 #1979)
fresh; run p2126_b_api "$PY" p2126_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.126.0 part C: rate limits, sync, push subscriptions (#1976 #1977 #1985 #1986 #1991 #1979 #1992)
fresh; run p2126_c_api "$PY" p2126_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.126.0 part D: tasks + offline queue (#1987 #1989 #1990 #1992)
fresh; run p2126_d_api "$PY" p2126_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2126_d_ui node p2126_d_ui.js "$KALMIDO_TEST_DATA"
# 2.126.0 part E: ESLint in CI (#1993)
fresh; run p2126_e_api "$PY" p2126_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2126_e_ui node p2126_e_ui.js "$KALMIDO_TEST_DATA"
# 2.126.1 part A: agent drafts - office texts, receipt summary, client report (#2123 #2124)
fresh; run p21261_a_api "$PY" p21261_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21261_a_ui node p21261_a_ui.js "$KALMIDO_TEST_DATA"
# 2.126.1 part B: table rows -> tasks as an agent proposal, planned inbox sorting (#2125 #2126)
fresh; run p21261_b_api "$PY" p21261_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21261_b_ui node p21261_b_ui.js "$KALMIDO_TEST_DATA"
# 2.137.0 part A: organisation import - office + clients (#2344)
fresh; run p2137_a_api "$PY" p2137_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.137.0 part B: organisation import - file store, documents, knowledge pages, tables, videos (#2344)
fresh; run p2137_b_api "$PY" p2137_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.137.0 part C: organisation import - chat, absences, forms, notes, time entries, round trip (#2344)
fresh; run p2137_c_api "$PY" p2137_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.137.0 part D: personal office into an organisation (#1981)
fresh; run p2137_d_api "$PY" p2137_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.124.0 part A: formulas, chart (#2109 #2115)
now wed 10:00; fresh; run p2124_a_api "$PY" p2124_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2124_a_ui node p2124_a_ui.js "$KALMIDO_TEST_DATA"
# 2.124.0 part B: column kinds, freeze + print, change history (#2110 #2111 #2112)
fresh; run p2124_b_api "$PY" p2124_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2124_b_ui node p2124_b_ui.js "$KALMIDO_TEST_DATA"
# 2.124.0 part C: share single tables, tables in Mod+K (#2113 #2114)
fresh; run p2124_c_api "$PY" p2124_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2124_c_ui node p2124_c_ui.js "$KALMIDO_TEST_DATA"
# 2.124.0 part D: cash flow balance from the bank import (#2342)
fresh; run p2124_d_api "$PY" p2124_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2124_d_ui node p2124_d_ui.js "$KALMIDO_TEST_DATA"
# 2.124.0 part E: several sheets per table (#2116)
fresh; run p2124_e_api "$PY" p2124_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2124_e_ui node p2124_e_ui.js "$KALMIDO_TEST_DATA"
# 2.125.0 part A: leave requests + leave balance, working days + weekly hours per person (#2117 #2118)
now wed 10:00; fresh; run p2125_a_api "$PY" p2125_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2125_a_ui node p2125_a_ui.js "$KALMIDO_TEST_DATA"
# 2.125.0 part B: monthly timesheet close + approval, entries across midnight, time zone per person (#2119 #2120)
now wed 10:00; fresh; run p2125_b_api "$PY" p2125_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2125_b_ui node p2125_b_ui.js "$KALMIDO_TEST_DATA"
# 2.125.0 part C: timer as app shortcut, XLSX export of time + workload (#2121 #2122)
fresh; run p2125_c_api "$PY" p2125_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2125_c_ui node p2125_c_ui.js "$KALMIDO_TEST_DATA"
# 2.125.0 part D: browser demo like a new account, all modules (#1653) (no container)
       run p2125_d_demo node p2125_d_demo_test.js
# 2.151.0 part A: the task knows its build state - first version, branch not in main, package field vs released versions (#2558)
fresh; run p2151_a_api "$PY" p2151_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2151_a_ui node p2151_a_ui.js "$KALMIDO_TEST_DATA"
# 2.151.0 part B: rule for software agents - the task list is the truth for tickets and releases (#2560)
fresh; run p2151_b_api "$PY" p2151_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.161.2 part B: bot moments - a nod for the last task ticked off, the bot at work in the agent chat and beside long jobs (#2609 #2610 #2611)
fresh; run p21521_b_ui node p21521_b_ui.js "$KALMIDO_TEST_DATA"
shard 18  # 2.142.2: shard 17 hit the 45 min CI limit - the 2.138-2.142 groups moved here; 20.10.2026 (job #692): the parked releases 2.111-2.113.0 (new suites still go to shard 17 above)
# 2.138.0 part A: office quotations - unit in percent rows, part rename on the title page, wrapped part headings, unit words by quantity; service worker other origins (#2236 #2239 #2240 #2249 #2257)
fresh; run p2138_a_api "$PY" p2138_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2138_a_ui node p2138_a_ui.js "$KALMIDO_TEST_DATA"
# 2.138.0 part B: sidebar search docked at the bottom, head with the workspace button (#2161)
fresh; run p2138_b_ui node p2138_b_ui.js "$KALMIDO_TEST_DATA"
# 2.138.0 part C: security fixes - upload / calendar tokens, organisation recovery key (#1907 #1972)
fresh; run p2138_c_api "$PY" p2138_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2138_c_ui node p2138_c_ui.js "$KALMIDO_TEST_DATA"
# 2.138.0 part D: office number ranges with a start number; more rule triggers / actions, Kanban swimlanes (#2256 #2060)
fresh; run p2138_d_api "$PY" p2138_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2138_d_ui node p2138_d_ui.js "$KALMIDO_TEST_DATA"
# 2.138.0 part E: resizable dialogs, quotation next step, service import order, PDF closing together, import undo archives, GbR partners (#2234 #2235 #2237 #2238 #2241 #2242)
fresh; run p2138_e_api "$PY" p2138_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2138_e_ui node p2138_e_ui.js "$KALMIDO_TEST_DATA"
# 2.138.2 part A: office documents - PDF of a draft asks to finalise, DRAFT watermark, no e-invoice from drafts; number scheme {isodate} (#2393 #2391)
fresh; run p21381_a_api "$PY" p21381_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21381_a_ui node p21381_a_ui.js "$KALMIDO_TEST_DATA"
# 2.138.2 part B: office PDF layout - rights annex spacing and sizes, multi-line company name bold in the footer; company name field grows (#2388 #2397 #2395)
fresh; run p21381_b_api "$PY" p21381_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21381_b_ui node p21381_b_ui.js "$KALMIDO_TEST_DATA"
# 2.138.2 part C: sidebar head with the workspace on top, workspace colour stripe (#2392 #2389)
fresh; run p21381_c_ui node p21381_c_ui.js "$KALMIDO_TEST_DATA"
# 2.138.2 part D: notifications - read entries muted, open ones on top, counters match (#2405)
fresh; run p21381_d_ui node p21381_d_ui.js "$KALMIDO_TEST_DATA"
# 2.138.3 part A: a decided approval marks its notifications read (#2406)
fresh; run p21382_a_api "$PY" p21382_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.138.3 part B: edit organisation - members as a searchable list with member / admin boxes (#2407)
fresh; run p21382_b_ui node p21382_b_ui.js "$KALMIDO_TEST_DATA"
# 2.138.4 part A: mobile UI fixes (#2359 #2372 #2370 #2362 #2367); B: sheet checkbox cells, agent chat edit (#2371 #2189); C: hardening (#2377-#2382)
fresh; run p21383_a_ui node p21383_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21383_b_api "$PY" p21383_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21383_b_ui node p21383_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21383_c_api "$PY" p21383_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.139.0 part A: team chat threads, "read by" (#2127 #2129)
fresh; run p2139_a_api "$PY" p2139_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2139_a_ui node p2139_a_ui.js "$KALMIDO_TEST_DATA"
# 2.139.0 part B: voice messages in the team chat (#2128)
fresh; run p2139_b_api "$PY" p2139_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2139_b_ui node p2139_b_ui.js "$KALMIDO_TEST_DATA"
# 2.139.0 part C: pages - an unreadable page back in the search once its key returns, error names the way out (#2386)
fresh; run p2139_c_api "$PY" p2139_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2139_c_ui node p2139_c_ui.js "$KALMIDO_TEST_DATA"
# 2.139.0 part D: comment -> task, proposal cards with the app thumb and larger check boxes (#2130 #2401)
fresh; run p2139_d_api "$PY" p2139_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2139_d_ui node p2139_d_ui.js "$KALMIDO_TEST_DATA"
# 2.142.0 part A: notification channels Slack/Matrix/Telegram/Signal, e-mail on single events (#2145 #2146)
fresh; run p2142_a_api "$PY" p2142_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2142_a_ui node p2142_a_ui.js "$KALMIDO_TEST_DATA"
# 2.142.0 part B: importers Notion, Google Tasks, ClickUp, Jira, generic CSV / Markdown (#2147)
fresh; run p2142_b_api "$PY" p2142_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2142_b_ui node p2142_b_ui.js "$KALMIDO_TEST_DATA"
# 2.142.0 part C: export to Todoist CSV / Markdown, admin "fetch mail now", ntfy share inbox per person (#2148 #2149 #2150)
fresh; run p2142_c_api "$PY" p2142_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2142_c_ui node p2142_c_ui.js "$KALMIDO_TEST_DATA"
# 2.144.1 part A: office side bar stays put in tablet mode (#2445)
fresh; run p21441_a_ui node p21441_a_ui.js "$KALMIDO_TEST_DATA"
# 2.144.1 part B: bank import - format hint, several files or a ZIP in one import (#2446 #2450)
fresh; run p21441_b_api "$PY" p21441_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21441_b_ui node p21441_b_ui.js "$KALMIDO_TEST_DATA"
# 2.146.0 part A: e-invoices received: XRechnung / ZUGFeRD read from XML (#2451)
fresh; run p2146_a_api "$PY" p2146_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2146_a_ui node p2146_a_ui.js "$KALMIDO_TEST_DATA"
# 2.146.0 part B: receipts: duplicates, several files / ZIP / pages to one receipt, HEIC photos (#2452 #2453 #2454)
fresh; run p2146_b_api "$PY" p2146_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2146_b_ui node p2146_b_ui.js "$KALMIDO_TEST_DATA"
# 2.146.0 part C: household + bank import: debit/credit column, several files / ZIP, undo an import, CAMT.052 pending entries and duplicates by reference (#2455 #2469)
fresh; run p2146_c_api "$PY" p2146_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2146_c_ui node p2146_c_ui.js "$KALMIDO_TEST_DATA"
# 2.146.0 part D: retention export before deleting an account / organisation (#2468)
fresh; run p2146_d_api "$PY" p2146_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2146_d_ui node p2146_d_ui.js "$KALMIDO_TEST_DATA"
# 2.146.0 part E: legacy import with address columns, CSV and .xls; contacts from several .vcf files or a ZIP (#2456 #2457)
fresh; run p2146_e_api "$PY" p2146_e_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2146_e_ui node p2146_e_ui.js "$KALMIDO_TEST_DATA"
# 2.111.0: Buero-Rueckgaengig (a), Termin-Einladungen + Abo-Link (b), Schnellerfassung (c)
fresh; run p2111_a_api "$PY" p2111_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2111_a_ui node p2111_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2111_b_api "$PY" p2111_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2111_b_ui node p2111_b_ui.js "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p2111_c_api "$PY" p2111_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2111_c_ui node p2111_c_ui.js "$KALMIDO_TEST_DATA"
# 2.112.1 part A (#2058): file store multi-select (move, trash, ZIP download) and phone scan into a PDF
fresh; run p21121_a_api "$PY" p21121_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21121_a_ui node p21121_a_ui.js "$KALMIDO_TEST_DATA"
# 2.112.1 part B (#2058): external share links for files and folders
fresh; run p21121_b_api "$PY" p21121_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21121_b_ui node p21121_b_ui.js "$KALMIDO_TEST_DATA"
# 2.113.0 part A: office settings in sections, autosave, industry pack switch (#2247 #2246)
fresh; run p2113_a_api "$PY" p2113_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2113_a_ui node p2113_a_ui.js "$KALMIDO_TEST_DATA"
# 2.147.0 part A: the country pack decides the office functions, switches, base pack XX + export, country choice (#2459-#2462)
fresh; run p2147_a_api "$PY" p2147_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2147_a_ui node p2147_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2189_l_settings "$PY" p2189_l_settings_test.py "$KALMIDO_TEST_DATA"  # 2.189.0 (#2475)
# 2.113.0 part B: offer parts fold open on the title page with a colour each (#2248)
fresh; run p2113_b_ui node p2113_b_ui.js "$KALMIDO_TEST_DATA"
shard 19  # 20.10.2026 (job #692): the parked releases 2.113.1-2.116
# 2.113.1 part A: producing from the net amount, factor quotient, only in the film pack (#2251)
fresh; run p2113b_a_api "$PY" p2113b_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2113b_a_ui node p2113b_a_ui.js "$KALMIDO_TEST_DATA"
# 2.113.1 part B: team chat attachments, free channels, group DMs (#2059)
fresh; run p2113b_b_api "$PY" p2113b_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2113b_b_ui node p2113b_b_ui.js "$KALMIDO_TEST_DATA"
# 2.113.2: terms (AGB) as a PDF with quotations (#2253)
fresh; run p2113c_a_api "$PY" p2113c_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2113c_a_ui node p2113c_a_ui.js "$KALMIDO_TEST_DATA"
# 2.115.0 part A (#2061): incoming webhook per list, outgoing webhooks for organisations + more events
fresh; run p2115_a_api "$PY" p2115_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2115_a_ui node p2115_a_ui.js "$KALMIDO_TEST_DATA"
# 2.115.0 part B (#2062): active sessions, sign out everywhere, organisation admins invite accounts
fresh; run p2115_b_api "$PY" p2115_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2115_b_ui node p2115_b_ui.js "$KALMIDO_TEST_DATA"
# 2.116.0 part A (#2063: trash period)
fresh; run p2116_a_api "$PY" p2116_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2116_a_ui node p2116_a_ui.js "$KALMIDO_TEST_DATA"
# 2.116.0 part B (#2065: full-text search)
fresh; run p2116_b_api "$PY" p2116_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2116_b_ui node p2116_b_ui.js "$KALMIDO_TEST_DATA"
# 2.116.0 part C (#2064 #2068: list CSV/print, snippets in the UI)
fresh; run p2116_c_api "$PY" p2116_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2116_c_ui node p2116_c_ui.js "$KALMIDO_TEST_DATA"
# 2.116.0 part D (#2066 #2067: several times a day, focus/habits in API v1)
now wed 10:00; fresh; run p2116_d_api "$PY" p2116_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2116_d_ui node p2116_d_ui.js "$KALMIDO_TEST_DATA"
# 2.143.0 part A (#2151: organisation roles guest / read-only / accounting)
fresh; run p2143_a_api "$PY" p2143_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2143_a_ui node p2143_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21472_a_ui node p21472_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21472_b_ui node p21472_b_ui.js "$KALMIDO_TEST_DATA"
# 2.143.0 part B (#2152 #2211: off-site backup target, wiki trash emptied for good)
fresh; run p2143_b_api "$PY" p2143_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2143_b_ui node p2143_b_ui.js "$KALMIDO_TEST_DATA"
# 2.143.0 part C (#2153 #2154: offline PWA outbox, share target for all file types)
fresh; run p2143_c_api "$PY" p2143_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2143_c_ui node p2143_c_ui.js "$KALMIDO_TEST_DATA"
# 2.143.0 part D (#2155 #2156 #2259: appearance across devices, activity per organisation, unused terms PDFs)
fresh; run p2143_d_api "$PY" p2143_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2143_d_ui node p2143_d_ui.js "$KALMIDO_TEST_DATA"
# 2.145.0 part A: sidebar logo purple + footer logo, workspace head aligned, news hint for other workspaces (#2433 #2437 #2438 #2444)
fresh; run p2145_a_api "$PY" p2145_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2145_a_ui node p2145_a_ui.js "$KALMIDO_TEST_DATA"
# 2.145.0 part B: own window (mini mode) starts fast (#2424)
fresh; run p2145_b_api "$PY" p2145_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2145_b_ui node p2145_b_ui.js "$KALMIDO_TEST_DATA"
# 2.145.0 part C: list CSV more columns, print view project head (#2431 #2432)
fresh; run p2145_c_api "$PY" p2145_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2145_c_ui node p2145_c_ui.js "$KALMIDO_TEST_DATA"
# 2.140.0 part A: shopping list quantity / price + offline in the shop, recipes -> shopping list, meal plan beyond 7 days (#2131 #2132)
fresh; run p2140_a_api "$PY" p2140_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2140_a_ui node p2140_a_ui.js "$KALMIDO_TEST_DATA"
# 2.140.0 part B: budget month comparison + one CSV importer with office bank import, devices <-> office equipment (#2134 #2136)
fresh; run p2140_b_api "$PY" p2140_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2140_b_ui node p2140_b_ui.js "$KALMIDO_TEST_DATA"
# 2.140.0 part C: journal history / search / export / mood stats, habits with several reminder times + weekly goal (#2133 #2135)
now wed 10:00; fresh; run p2140_c_api "$PY" p2140_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2140_c_ui node p2140_c_ui.js "$KALMIDO_TEST_DATA"
# 2.140.0 part D: birthdays written back to CardDAV (#2137)
fresh; run p2140_d_api "$PY" p2140_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2140_d_ui node p2140_d_ui.js "$KALMIDO_TEST_DATA"
# 2.141.0 part A: mailbox (IMAP + SMTP) per workspace, reply / send from the mail store (#2141 #2138)
fresh; run p2141_a_api "$PY" p2141_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2141_a_ui node p2141_a_ui.js "$KALMIDO_TEST_DATA"
# 2.141.0 part B: HTML mails in a sandbox, mail -> task / event with a link back (#2140 #2139)
fresh; run p2141_b_api "$PY" p2141_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2141_b_ui node p2141_b_ui.js "$KALMIDO_TEST_DATA"
# 2.141.0 part C: dispatch export CSV / ICS, newsletter consent import (#2142 #2143)
fresh; run p2141_c_api "$PY" p2141_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2141_c_ui node p2141_c_ui.js "$KALMIDO_TEST_DATA"
# 2.144.11 part A: cash book review points - log SET NULL, fewer decryptions, error state, receipt hint gate (#2354)
fresh; run p214411_a_api "$PY" p214411_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p214411_a_ui node p214411_a_ui.js "$KALMIDO_TEST_DATA"
# 2.144.0 part A: agent chat - filter only as the header icon, filter "only me" hides job results, stop a running answer (#2416 #2419 #2412)
fresh; run p2144_a_api "$PY" p2144_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2144_a_ui node p2144_a_ui.js "$KALMIDO_TEST_DATA"
# 2.144.0 part B: agent chat - collapse long messages for all, job card with only the result, agent colours (#2417 #2365 #2411)
fresh; run p2144_b_api "$PY" p2144_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2144_b_ui node p2144_b_ui.js "$KALMIDO_TEST_DATA"
# 2.144.0 part C: home block Today with today's events, header counts jobs; group a list by a custom field (#2418 #2414)
fresh; run p2144_c_api "$PY" p2144_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2144_c_ui node p2144_c_ui.js "$KALMIDO_TEST_DATA"
# 2.144.0 part D: hosting - operator role without content access, supporter licence purchase link (#797 #2158)
fresh; run p2144_d_api "$PY" p2144_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2144_d_ui node p2144_d_ui.js "$KALMIDO_TEST_DATA"
# 2.144.2 part A: small UI fixes (touch targets, labels, focus, setup dialog) (#2447 #2448 #2352 #2375 #2435 #2441 #2369 #1730)
fresh; run p21442_a_ui node p21442_a_ui.js "$KALMIDO_TEST_DATA"
# 2.144.2 part B: optimistic subtasks, calendar draft popup, sheet print, focus, receipts account row (#2467 #1811 #2370 #1644 #2352 #2372 #2375)
fresh; run p21442_b_ui node p21442_b_ui.js "$KALMIDO_TEST_DATA"
# 2.147.1 part A: drag tasks into the chats as references (#2523)
fresh; run p21443_a_api "$PY" p21443_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21443_a_ui node p21443_a_ui.js "$KALMIDO_TEST_DATA"
# 2.147.1 part B: payment reminder suggestions + GiroCode, batch space move with progress, agent chat colours (#2054 #2230 #2231 #2411)
fresh; run p21443_b_api "$PY" p21443_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21443_b_ui node p21443_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21443_b2_ui node p21443_b2_ui.js "$KALMIDO_TEST_DATA"
shard 20  # 22.10.2026 (2.161.2 CI): the second half of shard 19 (shard 19 ran into the 45 min CI limit in every run since 2.151.1); new suites go here, at the end
# 2.147.1 part C: bell "Read" section, approvals in the bell count, org card members, Mac icon (#2405 #2420 #2396)
fresh; run p21443_c_api "$PY" p21443_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21443_c_ui node p21443_c_ui.js "$KALMIDO_TEST_DATA"
# 2.144.5 part A: recovery key step-up with a real SSO re-login, approval cards only for approvers (#2387 #2001)
fresh; run p21445_a_api "$PY" p21445_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21445_a_ui node p21445_a_ui.js "$KALMIDO_TEST_DATA"
# 2.144.5 part B: workspace mailbox in org move/export/tenancy, CalDAV keeps attendees, import target defaults (#2410 #2379 #2002)
fresh; run p21445_b_api "$PY" p21445_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21445_b_ui node p21445_b_ui.js "$KALMIDO_TEST_DATA"
# 2.144.5 part C: formula depth, invoice lines with list_id, own time in the list header, series names and missed notice dates (#1523 #2021)
fresh; run p21445_c_api "$PY" p21445_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21445_c_ui node p21445_c_ui.js "$KALMIDO_TEST_DATA"
# 2.144.5 part D: phone - search closes animated, sheet cell editor and suggestions, freeze button (#1560 #2011)
fresh; run p21445_d_ui node p21445_d_ui.js "$KALMIDO_TEST_DATA"
# 2.144.6 part A: billable / billed time entries, invoice from time binds them, no double billing (#2053)
fresh; run p21446_a_api "$PY" p21446_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21446_a_ui node p21446_a_ui.js "$KALMIDO_TEST_DATA"
# 2.144.6 part B: office fixes from the 2.138 review - legacy counter reason, import order undo, approval rule, archive rest (#2400)
fresh; run p21446_b_api "$PY" p21446_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21446_b_ui node p21446_b_ui.js "$KALMIDO_TEST_DATA"
# 2.144.6 part C: office settings - one "transfer into an organisation" section (#2436)
# 2.144.9: office PDF - number without a leading separator, invoice label on the rights page, quotation reference, part name one source, option row on part pages (#2575)
fresh; run p21449_api "$PY" p21449_api_test.py "$KALMIDO_TEST_DATA"
# 2.144.10 (#2576): trial documents (A core, B exclusions, C UI)
fresh; run p214410_a_api "$PY" p214410_a_api_test.py "$KALMIDO_TEST_DATA"
now wed 10:00; fresh; run p214410_b_api "$PY" p214410_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p214410_c_ui node p214410_c_ui.js "$KALMIDO_TEST_DATA"
# 2.148.0 part A: lock periods + auditor export GoBD (#2471)
fresh; run p2148_a_api "$PY" p2148_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2148_a_ui node p2148_a_ui.js "$KALMIDO_TEST_DATA"
# 2.148.0 part B: receipt images with the DATEV batch (#2470)
fresh; run p2148_b_api "$PY" p2148_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2148_b_ui node p2148_b_ui.js "$KALMIDO_TEST_DATA"
# 2.148.0 part C: procedure documentation template GoBD (#2472)
fresh; run p2148_c_api "$PY" p2148_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2148_c_ui node p2148_c_ui.js "$KALMIDO_TEST_DATA"
# 2.148.0 part D: DATEV import of master data + opening balances (#2458)
fresh; run p2148_d_api "$PY" p2148_d_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2148_d_ui node p2148_d_ui.js "$KALMIDO_TEST_DATA"
# 2.148.1 part A: security fixes - organisation membership, invitations, public links (#2478 #2480 #2486 #2490)
fresh; run p21481_a_api "$PY" p21481_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p21481_a_ui node p21481_a_ui.js "$KALMIDO_TEST_DATA"
# 2.148.1 part B: security fixes - organisation boundary, account deletion, clients (#2479 #2483 #2484 #2491)
fresh; run p21481_b_api "$PY" p21481_b_api_test.py "$KALMIDO_TEST_DATA"
# 2.148.1 part C: security fixes - encryption, backup, retention, account import/export (#2481 #2482 #2487 #2492 #2493 #2494)
fresh; run p21481_c_api "$PY" p21481_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.148.1 part D: security fixes - resource limits, mail filing, assistant, agents (#2485 #2488 #2489 #2495)
fresh; run p21481_d_api "$PY" p21481_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.148.1 part E: hardening (#2496)
fresh; run p21481_e_api "$PY" p21481_e_api_test.py "$KALMIDO_TEST_DATA"
# 2.149.0 part A: office - web and agent paths aligned (offer status, locks, log lines), invoice texts via tr() (#2521 #2520)
fresh; run p2149_a_api "$PY" p2149_a_api_test.py "$KALMIDO_TEST_DATA"
# 2.149.0 part B: request timing / SQL count / Server-Timing, static files without session, service worker hash manifest (#2504 #2505 #2506)
fresh; run p2149_b_api "$PY" p2149_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2149_b_ui node p2149_b_ui.js "$KALMIDO_TEST_DATA"
# 2.149.0 part C: version poll signatures, request context cache, hot indexes, watchdog (#2507 #2508 #2515 #2516)
fresh; run p2149_c_api "$PY" p2149_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.149.0 part D: downgrade / restore guard, self-hosting defaults, environment variable registry (#2509 #2510 #2511)
fresh; run p2149_d_api "$PY" p2149_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.190.0 part B: server key fingerprint, recovery key only when stored, private approvals in the encryption passes, live texts of encrypted organisations, team chat files of a deleted organisation (#2592 #2496 #2561)
fresh; run p2190_b_crypto "$PY" p2190_b_crypto_test.py "$KALMIDO_TEST_DATA"
# 2.149.0 part E: test clock into the server, wait for state instead of sleeps, shards by timing (#2512 #2513 #2514)
fresh; run p2149_e_api "$PY" p2149_e_api_test.py "$KALMIDO_TEST_DATA"
# 2.149.0 part F: module start files loaded lazily, guarded lazy calls, missing CSS variables (#2518 #2519)
fresh; run p2149_f_ui node p2149_f_ui.js "$KALMIDO_TEST_DATA"
_group_end
# 2.153.0 part C: receipt list with filters, its CSV + ZIP for the tax adviser; e-invoice becomes a receipt (#2055)
fresh; run p2110_b_api "$PY" p2110_b_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2110_b_ui node p2110_b_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2153_c_api "$PY" p2153_c_api_test.py "$KALMIDO_TEST_DATA"
# 2.153.0 part A2: review fixes of the correspondence (office move with signature + letter links, accounting role)
fresh; run p2153_a2_api "$PY" p2153_a2_api_test.py "$KALMIDO_TEST_DATA"
# 2.154.0 part D: duplicating an invoice made from times (#2567)
fresh; run p2154_d_dup "$PY" p2154_d_dup_test.py "$KALMIDO_TEST_DATA"
# 2.154.0 part D: industry pack chosen per calculation part (#1876)
fresh; run p2154_d_pack "$PY" p2154_d_pack_test.py "$KALMIDO_TEST_DATA"
# 2.154.0 part C: data protection sheets of a client - DPA, privacy information, consent; mail, signed back by link / upload / reply mail (#2192)
fresh; run p2154_c_api "$PY" p2154_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2154_c_ui node p2154_c_ui.js "$KALMIDO_TEST_DATA"
# 2.154.0 part A: stack scans split by archive number codes, documents linked with existing tasks, receipt confirmations (#1111 #1356)
fresh; run p2154_a_api "$PY" p2154_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2154_a_ui node p2154_a_ui.js "$KALMIDO_TEST_DATA"
# 2.154.0 part B: Peppol dispatch of e-invoices - UBL (Peppol BIS 3.0) without a server, Peppol ids, provider connection, send + status (#1960)
       run p2154_b_ubl "$PY" p2154_b_ubl_test.py
fresh; run p2154_b_api "$PY" p2154_b_peppol_test.py "$KALMIDO_TEST_DATA"
fresh; run p2154_b_ui node p2154_b_ui.js "$KALMIDO_TEST_DATA"
# 2.155.0 part A: CalDAV - answers to invitations from the phone, calendars created on the device (#2074 #2079)
fresh; run p2155_a_caldav "$PY" p2155_a_caldav_test.py "$KALMIDO_TEST_DATA"
# 2.155.0 part C: own repeat rules in the event editor, the calendar year view (#2075 #2078)
fresh; run p2155_c_cal_ui node p2155_c_cal_ui.js "$KALMIDO_TEST_DATA"
# 2.155.0 part B: holidays + absences in the calendar, their subscription link, free / busy of invited people (#2076 #2077)
now wed 10:00; fresh; run p2155_b_absence_cal "$PY" p2155_b_absence_cal_test.py "$KALMIDO_TEST_DATA"
fresh; run p2155_b_ui node p2155_b_ui.js "$KALMIDO_TEST_DATA"
# 2.156.0 part D: saved views of the sidebar as tiles, "Others (N)", the active view on every device (#2186)
fresh; run p2156_d_sideviews_api "$PY" p2156_d_sideviews_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2156_d_sideviews_ui node p2156_d_sideviews_ui.js "$KALMIDO_TEST_DATA"
# 2.156.0 part B: list fields multiselect / currency / rating / task link, formulas with WENN / SUMME / RUNDEN (#2069 #2070)
fresh; run p2156_b_fields "$PY" p2156_b_fields_test.py "$KALMIDO_TEST_DATA"
fresh; run p2156_b_ui node p2156_b_ui.js "$KALMIDO_TEST_DATA"
# 2.156.0 part A: tasks and mind map with five levels, mind map properties on demand, "Add ideas" by an agent (#1949 #1948 #1201)
fresh; run p2156_a_api "$PY" p2156_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2156_a_ui node p2156_a_ui.js "$KALMIDO_TEST_DATA"
# 2.156.0 part C: calendar view per list, My tasks as a board, folded sections on every device + section templates (#2071 #2072 #2073)
fresh; run p2156_c_api "$PY" p2156_c_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2156_c_ui node p2156_c_ui.js "$KALMIDO_TEST_DATA"
# 2.161.0 part A: the own organisation picture also in the admin dialog "Edit organisation" (#2594)
fresh; run p2161_a_ui node p2161_a_ui.js "$KALMIDO_TEST_DATA"
# 2.162.0 part A (#2603): test phase - an admin deletes a finalised / sent invoice (typed number, cash book on request)
fresh; run p2162_a_api "$PY" p2162_a_invoice_delete_test.py "$KALMIDO_TEST_DATA"
fresh; run p2162_a_ui node p2162_a_ui.js "$KALMIDO_TEST_DATA"
# 2.161.2 part C: #2626 one News number, #2615 grip only for growing dialogs, #2616 office order + entry
fresh; run p2152a_c_ui node p2152a_c_ui.js "$KALMIDO_TEST_DATA"
# 2.161.2 part A: the sidebar brand is the workspace switch, the bot figure stays alive (#2607 #2608)
fresh; run p2152a_ui node p2152a_ui.js "$KALMIDO_TEST_DATA"
# 2.152.2 part C: #2627 chat header = search + menu (filter / long messages / steps in the menu), #2660 brand line whole in the drawer
fresh; run p21522_c_ui node p21522_c_ui.js "$KALMIDO_TEST_DATA"
# 2.152.2 part A: sidebar B on a computer - bar of the areas + one panel, office / time panels, fixed office points (#2622 #2617 #2618 #2632)
fresh; run p21522_a_ui node p21522_a_ui.js "$KALMIDO_TEST_DATA"
# 2.152.2 part B: every list is a project; the type became the switch "Progress and status" (#2624)
fresh; run p21522_b_ui node p21522_b_ui.js "$KALMIDO_TEST_DATA"
# 2.152.3 part B: the panels of tables, knowledge and the file store (folders lazily, folder lists with their path, drag onto a panel folder) (#2619 #2620 #2621)
fresh; run p21523_b_ui node p21523_b_ui.js "$KALMIDO_TEST_DATA"
# 2.152.3 part A: one head bar over everything on a computer - brand + workspace menu, search, bell, account; panel head with fold all / hide (#2619)
fresh; run p21523_a_ui node p21523_a_ui.js "$KALMIDO_TEST_DATA"
# 2.165.0: the bot greets once on the first start, looks startled on errors / offline, hops on pull to refresh (#2612 #2613 #2614)
fresh; run p2165_ui node p2165_ui.js "$KALMIDO_TEST_DATA"
# 2.172.0 part B: feeds - a 403 of the website is not a wrong password, own sender (#2678)
fresh; run p2172_b_feeds "$PY" p2172_b_feeds_test.py "$KALMIDO_TEST_DATA"
# 2.172.0 part B: Reading per space - feeds and read later private or per organisation, rights, no mixed view (#2677 #2679)
fresh; run p2172_b_reading_scope "$PY" p2172_b_reading_scope_test.py "$KALMIDO_TEST_DATA"
# 2.172.0 part B: the area Reading - read later view, feeds of the shown workspace, share sheet, old links (#2679 #2677)
fresh; run p2172_b_ui node p2172_b_ui.js "$KALMIDO_TEST_DATA"
# 2.173.0 part A: trips and staying in touch private or per organisation, rights, agents, travel expenses from a trip (#2680)
now wed 10:00; fresh; run p2173_a_travel_care_scope "$PY" p2173_a_travel_care_scope_test.py "$KALMIDO_TEST_DATA"
# 2.173.0 part A: Home in an organisation's view as "Travel & contacts", the view per workspace, the travel expenses button (#2680)
fresh; run p2173_a_ui node p2173_a_ui.js "$KALMIDO_TEST_DATA"
# 2.174.0 part A: agent chat bubbles in the agent colour, workspace name in the header (#2681)
fresh; run p2174_a_bubbles_ui node p2174_a_bubbles_ui.js "$KALMIDO_TEST_DATA"
# 2.152.5: the knowledge tree on a phone keeps folders opened by hand and its place after a page and Back (#2699)
fresh; run p21525_a_ui node p21525_a_ui.js "$KALMIDO_TEST_DATA"
# 2.152.6 (#2709): phone: the circle of a task with subtasks lines up with the other tasks, the arrow sits right of it (Firefox)
fresh; run p21526_a_ui node p21526_a_ui.js "$KALMIDO_TEST_DATA"
# 2.152.7 (#2710): phone: picking a priority in the task panel keeps the panel open (Firefox, touch)
fresh; run p21527_a_ui node p21527_a_ui.js "$KALMIDO_TEST_DATA"
fresh; run p21528_ui node p21528_ui.js "$KALMIDO_TEST_DATA"
# 2.177.0: knowledge ZIP import of large archives in pieces, unpacked in the background with progress; 100 MB per file (#2685)
fresh; run p2177_a_api "$PY" p2177_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2177_a_ui node p2177_a_ui.js "$KALMIDO_TEST_DATA"
# 2.168.0 part A (#2665): quotations / invoices bound to a project, the project page's documents (only with office rights)
fresh; run p2168_a_api "$PY" p2168_a_docproject_test.py "$KALMIDO_TEST_DATA"
fresh; run p2168_a_ui node p2168_a_ui.js "$KALMIDO_TEST_DATA"
# 2.169.0 part A: knowledge pages offline - the copy per space, sync of changed texts, offline edits via the outbox, conflicts (#2671)
fresh; run p2169_a_api "$PY" p2169_a_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p2169_a_ui node p2169_a_ui.js "$KALMIDO_TEST_DATA"
# 2.172.1 part A: read later never for agents / API tokens / webhooks, organisation bookmarks stay, feeds of active organisations, one read-later project (#2689 #2690)
fresh; run p21721_a_reading_guard "$PY" p21721_a_reading_guard_test.py "$KALMIDO_TEST_DATA"
# 2.164.0 (#2625): the calendar on the phone - swipe to turn the page, pinch to zoom the hours / change the view, trackpad, double tap
fresh; run p21640_ui node p21640_ui.js "$KALMIDO_TEST_DATA"
# 2.188.0 part B (#2498): duplicate global names of the classic client scripts are found by tools/eslint_globals.py
run p2188_b_globals_dup "$PY" p2188_b_globals_dup_test.py
# 2.188.0 part A (#2498): DTD in the auditor ZIP, kept DATEV receipt GUIDs, office move / import without doubles, folder lock check in one query
fresh; run p2188_a_office "$PY" p2188_a_office_test.py "$KALMIDO_TEST_DATA"
# 2.166.0 (#2633): settings save themselves (organisation), Settings > Access (API tokens, webhooks, agent tokens), also without organisation
fresh; run p2166_ui node p2166_ui.js "$KALMIDO_TEST_DATA"
# 2.185.0 part B (#2598): legacy import of old Excel files (.xls) like CSV / .xlsx, broken / protected .xls = 400
fresh; run p2185_b_xls "$PY" p2185_b_xls_test.py "$KALMIDO_TEST_DATA"
# 2.185.0 part A (#2583): possible duplicates marked in the receipts lists; e-invoices read before become receipts (new run, move, button)
fresh; run p2185_a_receipts "$PY" p2185_a_receipts_test.py "$KALMIDO_TEST_DATA"
# 2.185.0 part C (#2520): office documents in every app language (nl / fr / es / it), de / en words unchanged, e-invoice texts
fresh; run p2185_c_doclang "$PY" p2185_c_doclang_test.py "$KALMIDO_TEST_DATA"
# 2.184.0 part C (#2581 #2582): the own letterhead under letters, a refused mail leaves no filed PDF
fresh; run p2184_c_letters "$PY" p2184_c_letters_test.py "$KALMIDO_TEST_DATA"
# 2.184.0 part A (#2579 #2628): organisation export / import of letters and document custom fields, sent letters in the retention export
fresh; run p2184_a_export "$PY" p2184_a_export_test.py "$KALMIDO_TEST_DATA"
# 2.184.0 part B (#2580 #2585): custom fields made only by admins (move, Paperless import, rest as text lines), letters of a moved client
fresh; run p2184_b_fields "$PY" p2184_b_fields_test.py "$KALMIDO_TEST_DATA"
# 2.186.0 part A (#2599): a retired organisation - export only for its former admins, no waiver on retirement, deletion after the period, trashed folders
fresh; run p2186_a_retire "$PY" p2186_a_retire_test.py "$KALMIDO_TEST_DATA"
# 2.186.0 part B: the lock of booked receipts (move, cash book, equipment, billed, versions), the logbook closing (#2600 #2601)
fresh; run p2186_b_lock "$PY" p2186_b_lock_test.py "$KALMIDO_TEST_DATA"
# 2.186.0 part C (#2602): clean-up runs - orphan sweep in batches + resume, weekly backups cap only with the switch, suppression list, chat day limit, portal history row
fresh; run p2186_c_retention "$PY" p2186_c_retention_test.py "$KALMIDO_TEST_DATA"
# 2.183.0 part A: the top bars stay inside their boxes with long texts (#2661)
fresh; run p2183_a_topbar_ui node p2183_a_topbar_ui.js "$KALMIDO_TEST_DATA"
# 2.189.0 part B (#2475): books, receipt list, export, cash flow, key figures, bank and travel in the home currency (GBP office, without organisation too)
fresh; run p2189_b_books "$PY" p2189_b_books_test.py "$KALMIDO_TEST_DATA"
# 2.183.0 B (#2666): a start next to the running server skips policies / indexes that are in place (catalog check)
fresh; run p2183_b_rls_skip "$PY" p2183_b_rls_skip_test.py "$KALMIDO_TEST_DATA"
# 2.190.0 part D (#2496 #2561): hardening - office (negative totals, credit notes, cash book opening, agents), files (names, TIFF GPS, later scan), webhook cap, mailbox, event feed, export
fresh; run p2190_d_hardening "$PY" p2190_d_hardening_test.py "$KALMIDO_TEST_DATA"
# 2.190.0 part A (#1991 #2496 #2561): sessions end with their push subscriptions, reset revokes app passwords, sign-in tickets per address, passkey origins, sign-in link asks, keyed log name
fresh; run p2190_a_sessions "$PY" p2190_a_sessions_test.py "$KALMIDO_TEST_DATA"
fresh; run p2190_a_ui node p2190_a_ui.js "$KALMIDO_TEST_DATA"
# 2.190.0 part C (#2496 #2561): boundary checks, health list links, read-only agent channel, agent API checks, git https, batch approvals, bridge on opening to the organisation
fresh; run p2190_c_tenancy "$PY" p2190_c_tenancy_test.py "$KALMIDO_TEST_DATA"
# 2.191.0 part A (#1410 #2518): the language files split per module (core at start, a module's texts with the module)
fresh; run p2191_a_i18nsplit "$PY" p2191_a_i18nsplit_test.py "$KALMIDO_TEST_DATA"
fresh; run p2191_a_i18nsplit_ui node p2191_a_i18nsplit_ui.js "$KALMIDO_TEST_DATA"
fresh; run p2191_f2_i18nrobust "$PY" p2191_f2_i18nrobust_test.py "$KALMIDO_TEST_DATA"  # 2.191.0 F2 (#2518)
fresh; run p2191_f2_i18nrobust_ui node p2191_f2_i18nrobust_ui.js "$KALMIDO_TEST_DATA"
# 2.191.0 part C (#2593 #2516 #2507): linked task titles per list, the watchdog skips what is not due, the lean delta
fresh; run p2191_c_perf "$PY" p2191_c_perf_test.py "$KALMIDO_TEST_DATA"
# 2.191.0 part B (#1824 #2505): JS / CSS go out without comments (line numbers kept, hash of the served bytes), start scripts with defer
fresh; run p2191_b_strip "$PY" p2191_b_strip_test.py "$KALMIDO_TEST_DATA"
# 2.189.0 part A (#2475): documents in the home currency (GBP / CHF / any code with its rate), tax line and e-invoice BT-6 in it, lock after bookings
fresh; run p2189_a_docs "$PY" p2189_a_docs_test.py "$KALMIDO_TEST_DATA"
# 2.187.0 part C (#2476): office rights outside the office - contacts, project documents, acceptance links, dispo, receipt files, agents, export
fresh; run p2187_c_rights "$PY" p2187_c_rights_test.py "$KALMIDO_TEST_DATA"
# 2.187.0 part B (#2476): office rights in the office routes - every route has an area (static), own entries, specials, the rights log in the auditor export
run p2187_b_guard "$PY" p2187_b_guard_test.py
fresh; run p2187_b_rights "$PY" p2187_b_rights_test.py "$KALMIDO_TEST_DATA"
# 2.187.0 part A (#2476): the office's page "Rights" (people, groups, log, my rights), the office menu follows the rights
fresh; run p2187_a_rights_ui node p2187_a_rights_ui.js "$KALMIDO_TEST_DATA"
# 2.187.1 part A (#2735): clients' invoicing fields = quotes & invoices, sets / roles / crew = equipment, agents' receipts need the area, import maps the rights log
fresh; run p2187_1_a_rights "$PY" p2187_1_a_rights_test.py "$KALMIDO_TEST_DATA"
# 2.187.1 part B (#2735): the level "own" usable - own times without a client, entries entered for the person (read only), own reports, logbook hints, only the host confirms
fresh; run p2187_1_b_own "$PY" p2187_1_b_own_test.py "$KALMIDO_TEST_DATA"
# 2.193.0 part D (#2220): the queue bg_jobs (back up now, role web, SKIP LOCKED, a lost run taken again), incoming mail once per mailbox
fresh; run p2193_d_api "$PY" p2193_d_api_test.py "$KALMIDO_TEST_DATA"
# 2.196.0 part A (#2737): the phone's drawer like sidebar B (fixed top, the row of area icons, one panel, fixed bottom)
fresh; run p2196_a_mside_ui node p2196_a_mside_ui.js "$KALMIDO_TEST_DATA"
# 2.192.0 C (#2514): the current server on the database of an older release (tests/fixtures/upgrade), replaces the group database
fresh; run p2192_c_upgrade "$PY" p2192_c_upgrade_test.py "$KALMIDO_TEST_DATA"
# 2.192.0 A (#2512): the test clock on the JS side - Node and the jsdom windows follow KALMIDO_TEST_NOW (Berlin midnight, week start)
now sun 23:50; fresh; run p2192_a_clock_ui node p2192_a_clock_ui.js "$KALMIDO_TEST_DATA"
# 2.193.0 part A (#2219): the calendar and the mind map drag through drag.js (finger hold, mouse, Esc, zoom, pinch)
fresh; run p2193_a_ui node p2193_a_ui.js "$KALMIDO_TEST_DATA"
# 2.193.0 part C (#2219): task rows drag on drag.js (long press = hold), a drop in the bottom auto-scroll strip keeps its place
fresh; run p2193_c_ui node p2193_c_ui.js "$KALMIDO_TEST_DATA"
# 2.193.0 part B (#2219): the timeline and the roadmap drag on drag.js (finger, mouse, sideways auto-scroll, Esc)
fresh; run p2193_b_ui node p2193_b_ui.js "$KALMIDO_TEST_DATA"
# 2.207.0 part A (#2763): scan inboxes (upload-only keys for the folder watcher), the downloads, the setup in the document settings
fresh; run p2207_a_scan_keys "$PY" p2207_a_scan_keys_test.py "$KALMIDO_TEST_DATA"
fresh; run p2207_a_scan_ui node p2207_a_scan_ui.js "$KALMIDO_TEST_DATA"
# 2.207.0 B (#2763): the folder watcher (folderwatch/ -> /app/folderwatch) uploads a finished scan with an upload-only key, a revoked key pauses it
fresh; run p2207_b_watcher "$PY" p2207_b_watcher_test.py "$KALMIDO_TEST_DATA"
# 2.209.0 part D (#1856): archived office PDFs marked unchecked, file-text search pre-filter, text rows before an organisation's deletion, locked files out of exports, GIF / TIFF / HEIF metadata, type check of older files
fresh; run p2209_d_uploads "$PY" p2209_d_uploads_test.py "$KALMIDO_TEST_DATA"
docker rm -f "${KALMIDO_TEST_CONTAINER:-kalmido-test}" "${KALMIDO_TEST_DB_CONTAINER:-${KALMIDO_TEST_CONTAINER:-kalmido-test}-db}" >/dev/null 2>&1  # 2.37.0: + its Postgres
if [[ ${#FAILED[@]} -gt 0 ]]; then echo "FAILED suites: ${FAILED[*]}"; exit 1; fi
echo "ALL SUITES PASSED$([[ $SHARD -gt 0 ]] && echo " (shard $SHARD/$SHARDS_DEFINED)")"
