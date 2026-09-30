#!/usr/bin/env bash
# agent_launcher.sh -- reference launcher for an agent host (Claude Code) that follows Kalmido's runtime settings (2.4.1).
#
# Kalmido never runs an agent. An admin only chooses runtime settings in Settings > AI colleague > (agent) > Runtime and
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
#               KALMIDO_TOKEN=abk_...            the agent's API token (Settings > AI colleague > Agents)
#             everything in it is exported to the command too (the MCP server mcp/kalmido_mcp.py reads the same two)
#   COMMAND   what to start (default: claude). Example, a headless loop that works through its events:
#               agent_launcher.sh -e ~/.config/kalmido/agent.env -- claude -p "$(cat ~/agent/prompt.md)" --permission-mode acceptEdits
#   --once    print the command line and environment it would use, then exit (a dry run; the token is never printed)
# Needs: bash, curl, python3 (JSON), GNU date, setsid (util-linux). See docs/AGENTS.md "Runtime settings" for a systemd unit.
set -uo pipefail

ENV_FILE=./kalmido-agent.env
ONCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -e|--env) ENV_FILE=${2:?-e needs a file}; shift 2 ;;
    --once) ONCE=1; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) break ;;
  esac
done
CMD=("$@")
[[ ${#CMD[@]} -gt 0 ]] || CMD=(claude)
[[ -r "$ENV_FILE" ]] || { echo "agent_launcher: cannot read $ENV_FILE" >&2; exit 2; }
[[ "$ENV_FILE" == */* ]] || ENV_FILE=./$ENV_FILE  # "." would search PATH for a bare name
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
: "${KALMIDO_URL:?KALMIDO_URL missing in $ENV_FILE}" "${KALMIDO_TOKEN:?KALMIDO_TOKEN missing in $ENV_FILE}"
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
start() {  # start the command with the current settings (its own process group, so a restart ends all of it)
  local args=("${CMD[@]}") envs=()
  [[ "$MODEL" != "-" ]] && args+=(--model "$MODEL")
  if [[ "$AC" == "0" ]]; then envs+=(DISABLE_AUTO_COMPACT=1)
  elif [[ "$PCT" != "-" ]]; then envs+=(CLAUDE_AUTOCOMPACT_PCT_OVERRIDE="$PCT"); fi
  if [[ $ONCE == 1 ]]; then echo "env ${envs[*]:-} ${args[*]}"; return; fi
  local acs=off; [[ "$AC" == 1 ]] && acs="on at ${PCT/#-/the default }%"
  log "starting (fresh session): ${args[0]}, model ${MODEL/#-/default}, auto-compact $acs"
  env -u DISABLE_AUTO_COMPACT -u CLAUDE_AUTOCOMPACT_PCT_OVERRIDE "${envs[@]}" setsid "${args[@]}" &
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
  at=$(TZ="$TZNAME" date -d "$day $NIGHTLY" +%s 2>/dev/null) || return 1
  (( $(date +%s) >= at )) || return 1
  DONE_DAY=$day
  (( STARTED < at ))  # started before tonight's time -> restart now
}
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
