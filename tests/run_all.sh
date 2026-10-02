#!/usr/bin/env bash
# run_all.sh -- every suite, each group against a fresh test container (see start.sh for the settings).
#   BUILD=1 tests/run_all.sh     build the image from the repo first (docker build -t $KALMIDO_TEST_IMAGE .)
#   tests/run_all.sh --shard 2/4  only the second of the 4 shards (CI runs the shards as parallel jobs, see ci.yml).
#                                The `shard N` lines below split the groups; each group (a `fresh` container and the
#                                suites after it) stays whole. Keep the shards about equal (~14 min each on CI) by moving
#                                a marker when one grows; new suites go at the end (shard 3).
# Needs: docker, python3 with tests/requirements.txt, node 18+ with `npm ci` done in tests/.
# Exit code 0 = everything passed.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export KALMIDO_TEST_IMAGE=${KALMIDO_TEST_IMAGE:-kalmido:test}
export KALMIDO_TEST_DATA=${KALMIDO_TEST_DATA:-$HERE/.data}
PY=${PYTHON:-python3}
SHARDS_DEFINED=4
SHARD=0; CUR=1
if [[ "${1:-}" == "--shard" ]]; then
  [[ "${2:-}" =~ ^([0-9]+)/([0-9]+)$ ]] || { echo "usage: run_all.sh [--shard N/$SHARDS_DEFINED]"; exit 2; }
  SHARD=${BASH_REMATCH[1]}
  [[ ${BASH_REMATCH[2]} -eq $SHARDS_DEFINED && $SHARD -ge 1 && $SHARD -le $SHARDS_DEFINED ]] \
    || { echo "run_all.sh: the markers define $SHARDS_DEFINED shards (--shard 1/$SHARDS_DEFINED .. $SHARDS_DEFINED/$SHARDS_DEFINED)"; exit 2; }
fi
shard() { CUR=$1; }
mine() { [[ $SHARD -eq 0 || $CUR -eq $SHARD ]]; }
if [[ -n "${BUILD:-}" ]]; then docker build -q -t "$KALMIDO_TEST_IMAGE" "$HERE/.." >/dev/null || exit 1; fi
FAILED=()
run() {  # run <name> <cmd...>: prints the summary line, remembers failures
  mine || return 0
  local name=$1; shift
  # ONLY="a b" tests/run_all.sh: just these suites (2.7.2; the containers of their groups are still started)
  [[ -n "${ONLY:-}" && " $ONLY " != *" $name "* ]] && return 0
  local out rc
  out=$("$@" 2>&1); rc=$?
  echo "$out" | grep -E "^FAIL|ok, [0-9]+ failed|Error|Traceback" | head -40
  if [[ $rc -ne 0 ]]; then FAILED+=("$name"); echo "== $name: FAILED (exit $rc)"; echo "$out" | tail -15
    # GitHub Actions: an annotation, readable on the run page (and via the API) without the full log
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
      echo "::error title=suite $name failed::$( { echo "$out" | grep -E "^FAIL|Error|Traceback|failed" | head -8; echo "$out" | tail -3; } | tr '\n' ' ' | sed 's/%/%25/g' | cut -c1-900)"
    fi
  else echo "== $name: passed"; fi
}
fresh() { mine || return 0; bash "$HERE/start.sh" >/dev/null || { echo "container start failed"; exit 1; }; }
fresh; run api "$PY" api_test.py "$KALMIDO_TEST_DATA"
       run ui node ui_test.js
       run settings_ui node settings_ui.js
       run news_ui node news_ui.js
       run offline node offline_test.js
fresh; run news "$PY" news_test.py "$KALMIDO_TEST_DATA"
fresh; run p1_api "$PY" p1_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p1_ui node p1_ui_test.js
fresh; run time_api "$PY" time_api_test.py "$KALMIDO_TEST_DATA"
fresh; run time_ui node time_ui_test.js
fresh; run p3_api "$PY" p3_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p3_ui node p3_ui_test.js
fresh; run setup_ui node setup_ui.js
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
shard 2  # ---------------------------------------------------------------- shard 2 of 4
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
fresh; run gantt_ui node gantt_ui.js
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
fresh; run p151_ui node p151_ui.js
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
shard 3  # ---------------------------------------------------------------- shard 3 of 4
fresh; run p190_api "$PY" p190_api_test.py "$KALMIDO_TEST_DATA"
fresh; run p190_ui node p190_ui.js
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
# UI in jsdom; the Claude Code Stop hook against a stub API (no container)
       run p211_api "$PY" p211_api_test.py "$KALMIDO_TEST_DATA"
       run p211_ui node p211_ui.js "$KALMIDO_TEST_DATA"
       run usage_hook "$PY" usage_hook_test.py
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
shard 4  # ---------------------------------------------------------------- shard 4 of 4 (2.7.1: shard 3 had reached the 30 min job limit)
# 2.3.0: agent proposals (#260 project from a briefing, #261 break down, #262 sort the inbox, #263 tasks from notes): who may ask
# which agent, requests with exactly the sent input, validation per kind, apply as the person with one undo step, inbox
# consent, discard, retention (own containers); then the entry points, request + review dialogs in jsdom and Firefox
       run p230_api "$PY" p230_api_test.py "$KALMIDO_TEST_DATA"
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
# 2.7.2: the list option "Show completed at the bottom" instead of the checklist type (#414: aliases, migration), personal
# agents (#420: policy, owner-only sharing / chat, admin pause / delete), reactions in the agent chat (#421) and delivered_at
# (#422), project files leave the disk with the sample / an import undo (own container); then the robot before the bell
# (#417), person cards (#418), breadcrumbs (#424), Sent / Delivered / typing dots, Settings > Agents > Set up, the viewport
# fix (the keyboard never flips the layout while typing) in jsdom, and in Firefox at 360 / 390 (touch) and 1280 / 1920
       run p272_api "$PY" p272_api_test.py "$KALMIDO_TEST_DATA"
       run p272_ui node p272_ui.js "$KALMIDO_TEST_DATA"
# 2.7.2 (#420): the Windows launcher agent_launcher.ps1 against a stub API (skipped without pwsh)
       run launcher_ps1 "$PY" launcher_ps1_test.py
docker rm -f "${KALMIDO_TEST_CONTAINER:-kalmido-test}" >/dev/null 2>&1
if [[ ${#FAILED[@]} -gt 0 ]]; then echo "FAILED suites: ${FAILED[*]}"; exit 1; fi
echo "ALL SUITES PASSED$([[ $SHARD -gt 0 ]] && echo " (shard $SHARD/$SHARDS_DEFINED)")"
