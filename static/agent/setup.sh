#!/usr/bin/env bash
# agent-setup.sh -- set up a Kalmido project agent on macOS or Linux with one command (2.44.0, #1517 / #962).
#
# Kalmido shows the command in Settings > Agents > (agent) > "Set up on a computer", e.g.
#   curl -fsSL https://tasks.example.com/agent-setup.sh | bash -s -- --url https://tasks.example.com --code ks_... --dir ~/projects/site
# It trades the one-time setup code for the agent's token (stored in a file only you can read, never printed), fetches
# the starter files (mcp/starter_files.txt), and starts the agent in event mode at every login and again after a crash:
# a launchd LaunchAgent on macOS, a systemd --user service on Linux. One instance per project folder (several agents on one
# computer = several folders). Needs: bash (3.2 is enough), curl, python3 3.9+, the agent command (default: claude).
#
# usage: agent-setup.sh --url URL --code CODE --dir FOLDER [--cmd COMMAND] [--from DIR] [--no-autostart] [--dry-run]
#        agent-setup.sh --uninstall --dir FOLDER [--dry-run]
#   --url        your Kalmido address
#   --code       the one-time setup code (15 minutes, works once; make a new one in Kalmido when it expired)
#   --dir        the project folder the agent works in (created when missing)
#   --cmd        the agent command (default claude); it gets --mcp-config with the Kalmido MCP server
#   --from DIR   take the starter files from a local copy of mcp/ instead of downloading them
#   --no-autostart  install everything but the autostart (start agent_launcher.sh yourself)
#   --dry-run    only show what would happen: no code is redeemed, nothing is written, no autostart is loaded
#   --uninstall  stop and remove the autostart, revoke this computer's token in Kalmido, delete the instance folder
# Files: ~/.kalmido/agents/<folder name>-<hash>/ (starter files, kalmido-agent.env with mode 600, mcp.json, agent.log).
set -uo pipefail

URL="" CODE="" DIR="" CMD=claude FROM="" DRY=0 UNINSTALL=0 NOAUTO=0
while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL=${2:-}; shift 2 ;;
    --code) CODE=${2:-}; shift 2 ;;
    --dir) DIR=${2:-}; shift 2 ;;
    --cmd) CMD=${2:-}; shift 2 ;;
    --from) FROM=${2:-}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-autostart) NOAUTO=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,21p' "$0" 2>/dev/null || echo "see the comment at the top of agent-setup.sh"; exit 0 ;;
    *) echo "agent-setup: unknown option $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
REDEEMED=0
die() {
  printf 'agent-setup: %s\n' "$*" >&2
  if [ "$REDEEMED" = 1 ]; then revoke; rm -rf "$INST"; printf 'agent-setup: undone (the token is revoked again)\n' >&2; fi
  exit 1
}
run() { if [ "$DRY" = 1 ]; then say "  (dry run) $*"; else "$@"; fi; }

case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  *) die "this script is for macOS and Linux; on Windows use agent-setup.ps1 (Kalmido shows that command when you pick Windows)" ;;
esac

# kalmido-setup-step: prereq
step "Checking what is needed"
missing=""
PY=${KALMIDO_PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1 || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  if [ "$OS" = mac ]; then missing="$missing\n  - Python 3.9 or newer: run  xcode-select --install  (or install it from python.org)"
  else missing="$missing\n  - Python 3.9 or newer: install python3 with your package manager"; fi
fi
command -v curl >/dev/null 2>&1 || missing="$missing\n  - curl"
AGENT=""
if [ "$UNINSTALL" = 0 ]; then
  AGENT=$(command -v "$CMD" 2>/dev/null || true)
  for p in "$HOME/.local/bin/$CMD" "$HOME/.claude/local/$CMD" "/opt/homebrew/bin/$CMD" "/usr/local/bin/$CMD"; do
    [ -n "$AGENT" ] && break
    [ -x "$p" ] && AGENT=$p
  done
  if [ -z "$AGENT" ]; then
    if [ "$CMD" = claude ]; then missing="$missing\n  - Claude Code: run  curl -fsSL https://claude.ai/install.sh | bash  and then  claude  once to log in"
    else missing="$missing\n  - the agent command $CMD"; fi
  fi
fi
if [ -n "$missing" ]; then
  printf 'agent-setup: missing on this computer:%b\nInstall it and run the same command again (make a new code in Kalmido if 15 minutes have passed).\n' "$missing" >&2
  [ "$DRY" = 1 ] || exit 1
fi
[ -n "$AGENT" ] && say "  agent command: $AGENT"
[ "$CMD" = claude ] && [ -n "$AGENT" ] && [ ! -d "$HOME/.claude" ] && say "  note: Claude Code seems not logged in yet; run  claude  once and log in"

# kalmido-setup-step: instance
[ -n "$DIR" ] || die "--dir FOLDER is missing (the project folder the agent works in)"
case "$DIR" in "~") DIR=$HOME ;; "~/"*) DIR=$HOME/${DIR#"~/"} ;; esac
case "$DIR" in /*) ;; *) DIR=$(pwd)/$DIR ;; esac
DIR=${DIR%/}
base=$(basename "$DIR" | tr -c 'A-Za-z0-9_.\n-' '-' | cut -c1-40)
sum=$(printf '%s' "$DIR" | cksum | cut -d' ' -f1)
SLUG=$base-$sum
INST=$HOME/.kalmido/agents/$SLUG
LABEL=com.kalmido.agent.$SLUG
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
UNIT=kalmido-agent-$SLUG.service
UNITF=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT
ENVF=$INST/kalmido-agent.env
say "  project folder: $DIR"
say "  instance: $INST"

# revoke: this computer's token is revoked in Kalmido (POST /api/agent-setup/remove with the token itself)
revoke() {
  [ -f "$ENVF" ] || return 0
  KALMIDO_SETUP_ENV=$ENVF "$PY" - <<'PYEOF' || say "  Kalmido did not answer: remove the computer in Settings > Agents if it is still listed"
import os, sys, urllib.request
env = {}
for ln in open(os.environ["KALMIDO_SETUP_ENV"], encoding="utf-8"):
    k, _, v = ln.strip().partition("=")
    env[k] = v.strip("'\"")
req = urllib.request.Request(env["KALMIDO_URL"].rstrip("/") + "/api/agent-setup/remove", data=b"{}", method="POST",
                             headers={"Authorization": "Bearer " + env["KALMIDO_TOKEN"], "X-Requested-With": "kalmido",
                                      "Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=20).read()
except Exception as x:  # noqa: BLE001 -- one short line, no traceback
    sys.exit("  cannot revoke the token: %s" % x)
print("  this computer is removed in Kalmido (its token no longer works)")
PYEOF
}

# kalmido-setup-step: autostart_stop
stop_autostart() {
  if [ "$OS" = mac ]; then
    [ -f "$PLIST" ] && run launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
  else
    [ -f "$UNITF" ] && run systemctl --user disable --now "$UNIT" 2>/dev/null
  fi
  return 0
}

if [ "$UNINSTALL" = 1 ]; then
  # kalmido-setup-step: uninstall
  step "Removing the agent of $DIR from this computer"
  stop_autostart
  if [ -f "$ENVF" ]; then
    if [ "$DRY" = 1 ]; then say "  (dry run) revoke this computer's token in Kalmido"
    else
      revoke
    fi
  fi
  [ "$OS" = mac ] && [ -f "$PLIST" ] && run rm -f "$PLIST"
  if [ "$OS" = linux ] && [ -f "$UNITF" ]; then run rm -f "$UNITF"; run systemctl --user daemon-reload; fi
  [ -d "$INST" ] && run rm -rf "$INST"
  say "Done. The project folder itself stays as it is."
  exit 0
fi

[ -n "$URL" ] || die "--url is missing (your Kalmido address)"
[ -n "$CODE" ] || [ "$DRY" = 1 ] || die "--code is missing (the one-time code from Kalmido)"
URL=${URL%/}

# kalmido-setup-step: redeem
step "Connecting to Kalmido"
HOSTN=$(hostname 2>/dev/null || uname -n); HOSTN=${HOSTN%%.*}
STARTER_BASE=""
if [ "$DRY" = 1 ]; then
  say "  (dry run) trade the code for the agent's token at $URL/api/agent-setup/redeem (computer $HOSTN)"
else
  run mkdir -p "$INST" || die "cannot create $INST"
  chmod 700 "$INST"
  # the code goes to python in the environment, the token straight into the env file (mode 600) -- neither is printed
  out=$(KALMIDO_SETUP_CODE=$CODE KALMIDO_SETUP_URL=$URL KALMIDO_SETUP_ENV=$ENVF KALMIDO_SETUP_HOST=$HOSTN \
        KALMIDO_SETUP_DIR=$DIR KALMIDO_SETUP_OS=$OS "$PY" - <<'PYEOF'
import json, os, sys, urllib.error, urllib.request
e = os.environ
body = json.dumps({"code": e["KALMIDO_SETUP_CODE"].strip(), "host": e["KALMIDO_SETUP_HOST"][:80], "folder": e["KALMIDO_SETUP_DIR"][:300],
                   "os": e["KALMIDO_SETUP_OS"]}).encode()
req = urllib.request.Request(e["KALMIDO_SETUP_URL"] + "/api/agent-setup/redeem", data=body, method="POST",
                             headers={"Content-Type": "application/json", "X-Requested-With": "kalmido"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
except urllib.error.HTTPError as x:
    try:
        msg = json.loads(x.read()).get("error") or ""
    except ValueError:
        msg = ""
    sys.exit("Kalmido refused the code (HTTP %s): %s" % (x.code, msg or "invalid, used or expired"))
except (urllib.error.URLError, OSError) as x:
    sys.exit("cannot reach %s: %s" % (e["KALMIDO_SETUP_URL"], x))
old = os.umask(0o077)
with open(e["KALMIDO_SETUP_ENV"] + ".new", "w", encoding="utf-8") as f:
    f.write("# Kalmido agent %s (%s), set up by agent-setup.sh -- keep this file private\n" % (r["agent"]["name"], r["agent"]["username"]))
    f.write("KALMIDO_URL=%s\nKALMIDO_TOKEN=%s\nKALMIDO_EVENTS=1\n" % (e["KALMIDO_SETUP_URL"], r["token"]))  # the address that worked here
    # one state folder per instance (event cursor, approvals, lock): two project folders on one computer never share one
    f.write("KALMIDO_STATE_DIR=%s\n" % os.path.join(os.path.dirname(e["KALMIDO_SETUP_ENV"]), "state"))
os.umask(old)
os.chmod(e["KALMIDO_SETUP_ENV"] + ".new", 0o600)
os.replace(e["KALMIDO_SETUP_ENV"] + ".new", e["KALMIDO_SETUP_ENV"])
print("%s\t%s" % (r["agent"]["name"], r.get("starter_base") or ""))
PYEOF
  ) || die "setup stopped (nothing was installed)"
  IFS=$'\t' read -r AGNAME STARTER_BASE <<< "$out"
  REDEEMED=1
  say "  agent: $AGNAME, token stored in $ENVF (only readable for you)"
fi

# kalmido-setup-step: starter_files
step "Fetching the starter files"
REQUIRED="agent_launcher.sh agent_run.py kalmido_mcp.py"
fetch() {  # fetch NAME DEST -> 0 when it worked
  if [ -n "$FROM" ]; then [ -f "$FROM/$1" ] && cp "$FROM/$1" "$2"; return; fi
  curl -fsSL --max-time 60 "$STARTER_BASE$1" -o "$2" 2>/dev/null
}
if [ "$DRY" = 1 ]; then
  say "  (dry run) the files of ${FROM:-the starter}/starter_files.txt into $INST"
else
  [ -n "$FROM" ] || [ -n "$STARTER_BASE" ] || die "Kalmido sent no address for the starter files; use --from DIR"
  if ! fetch starter_files.txt "$INST/starter_files.txt"; then
    [ -z "$FROM" ] || die "no starter_files.txt in $FROM"
    # 2.44.0 (review): no fallback to another branch -- the starter must match this instance's version
    die "cannot fetch the starter file list (${STARTER_BASE}starter_files.txt); this version may not be published yet - try again later or use --from DIR"
  fi
  while IFS= read -r f || [ -n "$f" ]; do
    f=${f%%#*}; f=$(printf '%s' "$f" | tr -d ' \r')
    [ -n "$f" ] || continue
    case "$f" in */*|..*) say "  skipped $f (no paths allowed)"; continue ;; esac
    if fetch "$f" "$INST/$f.new"; then mv "$INST/$f.new" "$INST/$f"; say "  $f"
    else rm -f "$INST/$f.new"
      case " $REQUIRED " in *" $f "*) die "cannot fetch $f" ;; esac
      say "  $f not available (skipped)"
    fi
  done < "$INST/starter_files.txt"
  chmod +x "$INST/agent_launcher.sh"
fi

# kalmido-setup-step: mcp_config
# the agent command gets the MCP server with --mcp-config (works headless without a trust prompt); the token comes from the
# launcher's environment, so it is in no config file but the env file
MCPJ=$INST/mcp.json
if [ "$DRY" = 1 ]; then say "  (dry run) write $MCPJ (MCP server kalmido: $PY $INST/kalmido_mcp.py)"
else
  "$PY" -c 'import json, sys; json.dump({"mcpServers": {"kalmido": {"command": sys.argv[1], "args": [sys.argv[2]]}}}, open(sys.argv[3], "w"), indent=2)' \
    "$(command -v "$PY")" "$INST/kalmido_mcp.py" "$MCPJ"
fi
run mkdir -p "$DIR"

# kalmido-setup-step: autostart
step "Starting it at every login"
if [ "$NOAUTO" = 1 ]; then
  say "  skipped (--no-autostart); start it with:"
  say "  cd $(printf '%q' "$DIR") && bash $(printf '%q' "$INST/agent_launcher.sh") -e $(printf '%q' "$ENVF") --events -- $(printf '%q' "${AGENT:-$CMD}") --mcp-config $(printf '%q' "$MCPJ")"
fi
APATH="$(dirname "${AGENT:-/usr/bin/$CMD}"):$(dirname "$(command -v "$PY" 2>/dev/null || echo /usr/bin/python3)"):$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
[ "$NOAUTO" = 1 ] || stop_autostart
if [ "$NOAUTO" = 1 ]; then :
elif [ "$OS" = mac ]; then
  plist="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>$(xml "$INST/agent_launcher.sh")</string><string>-e</string><string>$(xml "$ENVF")</string>
    <string>--events</string><string>--</string><string>$(xml "${AGENT:-$CMD}")</string><string>--mcp-config</string><string>$(xml "$MCPJ")</string>
  </array>
  <key>WorkingDirectory</key><string>$(xml "$DIR")</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(xml "$APATH")</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$(xml "$INST/agent.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$INST/agent.log")</string>
</dict>
</plist>"
  if [ "$DRY" = 1 ]; then say "  (dry run) $PLIST:"; printf '%s\n' "$plist"
  else
    mkdir -p "$(dirname "$PLIST")"
    printf '%s\n' "$plist" > "$PLIST"
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST" || die "launchctl could not load $PLIST"
  fi
  say "  LaunchAgent $LABEL (starts at login, restarts after a crash; log: $INST/agent.log)"
else
  q() { printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"; }
  unit="[Unit]
Description=Kalmido agent for $DIR
After=network-online.target

[Service]
WorkingDirectory=$(q "$DIR")
Environment=$(q "PATH=$APATH")
ExecStart=/usr/bin/env bash $(q "$INST/agent_launcher.sh") -e $(q "$ENVF") --events -- $(q "${AGENT:-$CMD}") --mcp-config $(q "$MCPJ")
Restart=always
RestartSec=30
StandardOutput=append:$INST/agent.log
StandardError=append:$INST/agent.log

[Install]
WantedBy=default.target"
  if [ "$DRY" = 1 ]; then say "  (dry run) $UNITF:"; printf '%s\n' "$unit"
  else
    mkdir -p "$(dirname "$UNITF")"
    printf '%s\n' "$unit" > "$UNITF"
    systemctl --user daemon-reload && systemctl --user enable --now "$UNIT" || die "systemctl --user could not start $UNIT"
  fi
  say "  systemd --user service $UNIT (log: $INST/agent.log)"
  say "  it runs while you are logged in; to keep it running after logout: loginctl enable-linger $(id -un)"
fi

# kalmido-setup-step: done
step "Done"
say "Kalmido shows the computer under Settings > Agents within a minute (green dot = connected)."
say "Remove it again:  curl -fsSL $URL/agent-setup.sh | bash -s -- --uninstall --dir $(printf '%q' "$DIR")"
