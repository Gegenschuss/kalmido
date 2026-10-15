#!/usr/bin/env bash
# agent_launcher.sh -- reference launcher for an agent host (Claude Code) that follows Kalmido's runtime settings (2.4.1; event mode 2.35.0).
#
# Kalmido never runs an agent. An admin only chooses runtime settings in Settings > Agents > (agent) > Runtime and
# Kalmido hands them to the agent: GET /api/v1/agent -> "runtime" {model, autocompact, autocompact_pct, nightly_reset,
# reset_seq, timezone}. This script runs on the agent's host and applies them:
#   - starts the agent command, ALWAYS in a fresh session (Claude Code starts a new conversation unless it gets
#     --continue / --resume, so never pass those here)
#   - model:            appends `--model <model>` (empty = the command's own default)
#   - auto-compact:     on + percentage -> CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=<pct>; off -> DISABLE_AUTO_COMPACT=1
#   - restarts it (fresh session) when the model / auto-compact settings change, when an admin presses "Reset now"
#     (reset_seq goes up; the agent also gets the event `reset`), once a night at nightly_reset (HH:MM in runtime.timezone),
#     and whenever the command exits by itself (after KALMIDO_RESTART_DELAY seconds)
# It polls GET /api/v1/agent every KALMIDO_POLL seconds (default 60): one small request, no events are consumed.
#
# usage: agent_launcher.sh [-e ENV_FILE] [--once] [-- COMMAND ...]
#   ENV_FILE  default ./kalmido-agent.env (chmod 600), shell syntax:
#               KALMIDO_URL=https://tasks.example.com
#               KALMIDO_TOKEN=abk_...            the agent's API token (Settings > Agents)
#             everything in it is exported to the command too (the MCP server mcp/kalmido_mcp.py reads the same two)
#   COMMAND   what to start (default: claude). Example, a headless loop that works through its events:
#               agent_launcher.sh -e ~/.config/kalmido/agent.env -- claude -p "$(cat ~/agent/prompt.md)" --permission-mode acceptEdits
#   --once    print the command line and environment it would use, then exit (a dry run; the token is never printed)
#   --events  event mode (2.35.0, recommended for Claude Code): the launcher starts mcp/agent_run.py, which waits for the
#             agent's events and starts ONE fresh headless run of COMMAND per event (`-p --output-format stream-json
#             --verbose`, the event as prompt on stdin), like a hosted chat service: steps between tool calls, model and
#             permission mode, typing / status, plan usage ring, reply reference, approval cards; the final text of a
#             chat run is posted as the answer. COMMAND then is the plain agent command without -p, e.g.
#               agent_launcher.sh -e ~/.config/kalmido/agent.env --events -- claude --mcp-config ~/agent/.mcp.json
#             Same as KALMIDO_EVENTS=1 in the env file. Optional keys there: KALMIDO_PROMPT_FILE (text in front of every
#             event), KALMIDO_USAGE_LIMIT (pause new runs at this % of the week), KALMIDO_USAGE_FILE (a status line
#             file {at, rate_limits}), KALMIDO_STATE_DIR (event cursor), KALMIDO_APPROVAL_CHECK=0 (2.40.0: no check of
#             chat answers that ask to decide without an ```approval block), KALMIDO_NOTICE_COMPACTED (2.41.0: the notice
#             in the chat when a run compacts its conversation, {0} = the time). Without --events: the command runs as it is.
#   KALMIDO_HOST  the computer name shown in Kalmido (2.44.0; default: hostname without the domain), sent once at start
# Needs: bash (3.2 is enough, the macOS one), curl, python3 (JSON, time zones, a new process group). 2.44.0 (#962): no GNU
# date, setsid or other GNU-only tools any more, so it runs on macOS and Linux alike. /agent-setup.sh of your Kalmido sets it up with an
# autostart (launchd LaunchAgent / systemd --user); see docs/AGENTS.md "Runtime settings" for a hand-made systemd unit.
set -uo pipefail

ENV_FILE=./kalmido-agent.env
ONCE=0
EVENTS=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--env) ENV_FILE=${2:?-e needs a file}; shift 2 ;;
    --once) ONCE=1; shift ;;
    --events) EVENTS=1; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '2,38p' "$0"; exit 0 ;;
    *) break ;;
  esac
done
CMD=("$@")
[[ ${#CMD[@]} -gt 0 ]] || CMD=(claude)
AGENT0=${CMD[0]}  # the agent command itself (event mode puts python3 agent_run.py in front)
[[ -r "$ENV_FILE" ]] || { echo "agent_launcher: cannot read $ENV_FILE" >&2; exit 2; }
[[ "$ENV_FILE" == */* ]] || ENV_FILE=./$ENV_FILE  # "." would search PATH for a bare name
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
: "${KALMIDO_URL:?KALMIDO_URL missing in $ENV_FILE}" "${KALMIDO_TOKEN:?KALMIDO_TOKEN missing in $ENV_FILE}"
[[ "${KALMIDO_EVENTS:-0}" == 1 ]] && EVENTS=1
# kalmido-capability: steps, model, permission_mode, quota, reply_ref, status_typing, approval, old_server, proposals, message_edited, playbook, approval_check, notice, comment_answer, comment_blocks
# kalmido-capability: outbox, jobs, event_bundling (2.44.0: mcp/agent_extras.py and mcp/agent_job.py, loaded by agent_run.py)
# kalmido-capability: approval_closed, perm_relay, approval_lifecycle, session_resume, robust_runs
# kalmido-capability: team_listen (2.46.1: team chat messages of lists the agent listens in on, in mcp/agent_run.py)
# kalmido-capability: rules_block (2.46.6: the fixed rules of mcp/agent_rules.md in front of every prompt, in mcp/agent_run.py)
# (2.44.0: agent_run.py; perm_relay and session_resume only when COMMAND is Claude Code)
# (event mode: mcp/agent_run.py does them for both launchers, so .sh and .ps1 cannot drift apart)
if [[ $EVENTS == 1 ]]; then
  RUNNER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agent_run.py"
  [[ -r "$RUNNER" ]] || { echo "agent_launcher: $RUNNER missing (event mode)" >&2; exit 2; }
  CMD=("${KALMIDO_PYTHON:-python3}" "$RUNNER" -- "${CMD[@]}")
fi
PY=${KALMIDO_PYTHON:-python3}
# 2.44.0 (#962): an own process group without util-linux setsid (macOS has none): python3 starts a new session and
# replaces itself with the command (same pid, so "kill -- -PID" ends all of it)
if command -v setsid >/dev/null 2>&1; then NEWSESS=(setsid)
else NEWSESS=("$PY" -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])'); fi
POLL=${KALMIDO_POLL:-60}
RESTART_DELAY=${KALMIDO_RESTART_DELAY:-10}
log() { printf '%s agent_launcher: %s\n' "$(date '+%F %T')" "$*" >&2; }

# GET /api/v1/agent -> one tab-separated line: model autocompact pct nightly reset_seq timezone enabled. A paused agent's
# token is refused (403): that prints "- - - - - - 0" (stop the agent). The token goes to curl on stdin, never on its
# command line. Exit 1: Kalmido not reachable (or another error).
fetch() {
  local out code
  out=$(printf 'header = "Authorization: Bearer %s"\n' "$KALMIDO_TOKEN" |
        curl -sS --max-time 20 --config - -w '\n%{http_code}' "${KALMIDO_URL%/}/api/v1/agent") || return 1
  code=${out##*$'\n'}
  if [[ "$code" == 403 ]]; then printf -- '-\t-\t-\t-\t%s\tUTC\t0\n' "${SEQ:-0}"; return 0; fi
  [[ "$code" == 200 ]] || { log "GET /api/v1/agent: HTTP $code"; return 1; }
  printf '%s' "${out%$'\n'*}" | python3 -c '
import json, sys
a = json.load(sys.stdin)
r = a.get("runtime") or {}
pct = r.get("autocompact_pct")
print("\t".join(str(x) for x in (r.get("model") or "-", "1" if r.get("autocompact", True) else "0", pct if pct else "-",
                                  r.get("nightly_reset") or "-", int(r.get("reset_seq") or 0), r.get("timezone") or "UTC",
                                  "1" if a.get("enabled", True) else "0")))'
}

PID=""
# kalmido-capability: runtime (model, auto-compact, fresh session, restart on change / reset / nightly, pause)
start() {  # start the command with the current settings (its own process group, so a restart ends all of it)
  local args=("${CMD[@]}") envs=()
  [[ "$MODEL" != "-" ]] && args+=(--model "$MODEL")
  if [[ "$AC" == "0" ]]; then envs+=(DISABLE_AUTO_COMPACT=1)
  elif [[ "$PCT" != "-" ]]; then envs+=(CLAUDE_AUTOCOMPACT_PCT_OVERRIDE="$PCT"); fi
  if [[ $ONCE == 1 ]]; then echo "env ${envs[*]:-} ${args[*]}"; return; fi
  local acs=off; [[ "$AC" == 1 ]] && acs="on at ${PCT/#-/the default }%"
  log "starting (fresh session): ${args[0]}, model ${MODEL/#-/default}, auto-compact $acs"
  # ${envs[@]+...}: bash 3.2 calls an empty array unbound under set -u
  env -u DISABLE_AUTO_COMPACT -u CLAUDE_AUTOCOMPACT_PCT_OVERRIDE ${envs[@]+"${envs[@]}"} "${NEWSESS[@]}" "${args[@]}" &
  PID=$!
  STARTED=$(date +%s)
}
stop() {
  [[ -n "$PID" ]] || return 0
  kill -TERM -- "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null
  for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  kill -KILL -- "-$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null
  PID=""
}
trap 'stop; exit 0' TERM INT

# epoch_at DAY HH:MM ZONE -> unix time of that wall-clock time in the IANA zone (2.44.0 #962: python3 instead of GNU date -d)
epoch_at() {
  "$PY" -c 'import sys, datetime
from zoneinfo import ZoneInfo
y, m, d = (int(x) for x in sys.argv[1].split("-")); hh, mm = (int(x) for x in sys.argv[2].split(":")[:2])
print(int(datetime.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(sys.argv[3])).timestamp()))' "$1" "$2" "$3" 2>/dev/null
}

# kalmido-capability: host_name
# 2.44.0 (#1517): which computer this is (PUT /api/v1/agent/status {status: idle, host}); a missing agent command is
# reported as the agent's error. Older servers refuse the field (400): nothing happens.
report_host() {
  local h=${KALMIDO_HOST:-$(hostname 2>/dev/null || uname -n)} st=idle txt=""
  h=${h%%.*}
  if ! command -v "$AGENT0" >/dev/null 2>&1; then st=error; txt="agent command not found on ${h:-this computer}: $AGENT0"; log "$txt"; fi
  printf 'header = "Authorization: Bearer %s"\n' "$KALMIDO_TOKEN" |
    curl -sS --max-time 20 --config - -o /dev/null -X PUT -H 'Content-Type: application/json' \
      --data "$("$PY" -c 'import json, sys; print(json.dumps({"status": sys.argv[1], "text": sys.argv[2], "host": sys.argv[3][:80]}))' "$st" "$txt" "$h")" \
      "${KALMIDO_URL%/}/api/v1/agent/status" 2>/dev/null || true
}

line=$(fetch) || { log "cannot read the runtime settings from $KALMIDO_URL"; exit 1; }
IFS=$'\t' read -r MODEL AC PCT NIGHTLY SEQ TZNAME ENABLED <<< "$line"
if [[ $ONCE == 1 ]]; then start; exit 0; fi
SIG="$MODEL|$AC|$PCT"
DONE_DAY=""  # the day whose nightly restart is done (a start after that time counts)
nightly_due() {
  [[ "$NIGHTLY" != "-" ]] || return 1
  local day at
  day=$(TZ="$TZNAME" date +%F)
  [[ "$DONE_DAY" != "$day" ]] || return 1
  at=$(epoch_at "$day" "$NIGHTLY" "$TZNAME") || return 1
  [[ -n "$at" ]] || return 1
  (( $(date +%s) >= at )) || return 1
  DONE_DAY=$day
  (( STARTED < at ))  # started before tonight's time -> restart now
}
[[ "$ENABLED" == 1 ]] && report_host
[[ "$ENABLED" == 1 ]] && start || log "the agent is paused in Kalmido; waiting"
STARTED=${STARTED:-$(date +%s)}
nightly_due >/dev/null || true  # a start after tonight's time already counts as the nightly restart
while true; do
  sleep "$POLL" & wait $!
  if [[ -n "$PID" ]] && ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null; PID=""
    log "the command ended; restarting in ${RESTART_DELAY}s"; sleep "$RESTART_DELAY"
  fi
  if ! line=$(fetch); then log "Kalmido not reachable; keeping the agent as it is"; continue; fi
  IFS=$'\t' read -r MODEL AC PCT NIGHTLY NSEQ TZNAME ENABLED <<< "$line"
  why=""
  [[ "$NSEQ" != "$SEQ" ]] && why="reset now ($SEQ -> $NSEQ)"
  [[ -z "$why" && "$MODEL|$AC|$PCT" != "$SIG" ]] && why="runtime settings changed"
  [[ -z "$why" ]] && nightly_due && why="nightly fresh restart ($NIGHTLY $TZNAME)"
  SEQ=$NSEQ; SIG="$MODEL|$AC|$PCT"
  if [[ "$ENABLED" != 1 ]]; then
    [[ -n "$PID" ]] && { log "paused in Kalmido: stopping"; stop; }
    continue
  fi
  if [[ -n "$why" && -n "$PID" ]]; then log "restart: $why"; stop; fi
  [[ -n "$PID" ]] || start
done
