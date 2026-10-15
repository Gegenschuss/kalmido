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
# usage: agent-setup.sh --url URL --code CODE --dir FOLDER [--cmd COMMAND] [--from DIR] [--no-autostart] [--dry-run] [--lang de|en]
#        agent-setup.sh --uninstall --dir FOLDER [--dry-run]
#   --url        your Kalmido address
#   --code       the one-time setup code (15 minutes, works once; make a new one in Kalmido when it expired)
#   --dir        the project folder the agent works in (created when missing)
#   --cmd        the agent command (default claude); it gets --mcp-config with the Kalmido MCP server
#   --from DIR   take the starter files from a local copy of mcp/ instead of downloading them
#   --no-autostart  install everything but the autostart (start agent_launcher.sh yourself)
#   --lang       language of the messages: de or en (Kalmido adds the language of your account; anything else = en)
#   --dry-run    only show what would happen: no code is redeemed, nothing is written, no autostart is loaded
#   --uninstall  stop and remove the autostart, revoke this computer's token in Kalmido, delete the instance folder
# Files: ~/.kalmido/agents/<folder name>-<hash>/ (starter files, kalmido-agent.env with mode 600, mcp.json, agent.log).
set -uo pipefail

URL="" CODE="" DIR="" CMD=claude FROM="" DRY=0 UNINSTALL=0 NOAUTO=0 LANGC=en
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
    --lang) LANGC=${2:-en}; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0" 2>/dev/null || echo "see the comment at the top of agent-setup.sh"; exit 0 ;;
    *) UNKNOWN=$1; break ;;
  esac
done
# 2.46.6 (#1713): messages in German or English (--lang); anything else = English. bash 3.2: a case table, no assoc arrays.
LANGC=$(printf '%s' "$LANGC" | tr 'A-Z' 'a-z' | cut -c1-2)
[ "$LANGC" = de ] || LANGC=en
msg_de() {
  case "$1" in
    unknown) echo "agent-setup: unbekannte Option %s" ;;
    undone) echo "agent-setup: rückgängig gemacht (das Token ist wieder gesperrt)" ;;
    wrongos) echo "dieses Skript ist für macOS und Linux; unter Windows nimm agent-setup.ps1 (Kalmido zeigt den Befehl, wenn du Windows wählst)" ;;
    s_prereq) echo "Prüfe, was gebraucht wird" ;;
    py_mac) echo "\n  - Python 3.9 oder neuer: führe  xcode-select --install  aus (oder installiere es von python.org)" ;;
    py_linux) echo "\n  - Python 3.9 oder neuer: installiere python3 mit deiner Paketverwaltung" ;;
    curl) echo "\n  - curl" ;;
    claude) echo "\n  - Claude Code: führe  curl -fsSL https://claude.ai/install.sh | bash  aus und danach einmal  claude  zum Anmelden" ;;
    cmd) echo "\n  - der Agent-Befehl %s" ;;
    missing) echo "agent-setup: auf diesem Computer fehlt noch:%b\nInstalliere es und führe denselben Befehl noch einmal aus (erzeuge in Kalmido einen neuen Code, wenn 15 Minuten vorbei sind)." ;;
    agentcmd) echo "  Agent-Befehl: %s" ;;
    notlogged) echo "  Hinweis: Claude Code scheint noch nicht angemeldet zu sein; führe  claude  einmal aus und melde dich an" ;;
    nodir) echo "--dir ORDNER fehlt (der Projektordner, in dem der Agent arbeitet)" ;;
    folder) echo "  Projektordner: %s" ;;
    instance) echo "  Instanz: %s" ;;
    rev_fail) echo "  Kalmido hat nicht geantwortet: entferne den Computer unter Einstellungen > Agenten, falls er noch aufgelistet ist" ;;
    rev_ok) echo "  dieser Computer ist in Kalmido entfernt (sein Token funktioniert nicht mehr)" ;;
    rev_err) echo "  das Token kann nicht gesperrt werden: %s" ;;
    s_uninstall) echo "Entferne den Agenten von %s von diesem Computer" ;;
    dry_revoke) echo "  (Probelauf) das Token dieses Computers in Kalmido sperren" ;;
    uninstalled) echo "Fertig. Der Projektordner selbst bleibt unverändert." ;;
    nourl) echo "--url fehlt (deine Kalmido-Adresse)" ;;
    nocode) echo "--code fehlt (der einmalige Code aus Kalmido)" ;;
    s_connect) echo "Verbinde mit Kalmido" ;;
    dry_redeem) echo "  (Probelauf) den Code gegen das Token des Agenten tauschen unter %s/api/agent-setup/redeem (Computer %s)" ;;
    nocreate) echo "%s kann nicht angelegt werden" ;;
    refused) echo "Kalmido hat den Code abgelehnt (HTTP %s): %s" ;;
    refused_def) echo "ungültig, schon benutzt oder abgelaufen" ;;
    noreach) echo "%s ist nicht erreichbar: %s" ;;
    stopped) echo "Einrichtung abgebrochen (es wurde nichts installiert)" ;;
    agent) echo "  Agent: %s, Token gespeichert in %s (nur für dich lesbar)" ;;
    s_starter) echo "Lade die Starter-Dateien" ;;
    dry_files) echo "  (Probelauf) die Dateien aus %s/starter_files.txt nach %s" ;;
    nobase) echo "Kalmido hat keine Adresse für die Starter-Dateien geschickt; nimm --from ORDNER" ;;
    nolist) echo "keine starter_files.txt in %s" ;;
    nolistfetch) echo "die Liste der Starter-Dateien (%sstarter_files.txt) kann nicht geladen werden; diese Version ist vielleicht noch nicht veröffentlicht – versuche es später noch einmal oder nimm --from ORDNER" ;;
    skippath) echo "  %s übersprungen (keine Pfade erlaubt)" ;;
    nofetch) echo "%s kann nicht geladen werden" ;;
    skipfile) echo "  %s nicht verfügbar (übersprungen)" ;;
    dry_mcp) echo "  (Probelauf) %s schreiben (MCP-Server kalmido: %s %s)" ;;
    s_auto) echo "Starte bei jeder Anmeldung" ;;
    noauto) echo "  übersprungen (--no-autostart); starte es mit:" ;;
    dry_file) echo "  (Probelauf) %s:" ;;
    launchfail) echo "launchctl konnte %s nicht laden" ;;
    launchok) echo "  LaunchAgent %s (startet bei der Anmeldung, startet nach einem Absturz neu; Protokoll: %s)" ;;
    sysfail) echo "systemctl --user konnte %s nicht starten" ;;
    sysok) echo "  systemd-Benutzerdienst %s (Protokoll: %s)" ;;
    linger) echo "  er läuft, solange du angemeldet bist; damit er auch nach dem Abmelden läuft: loginctl enable-linger %s" ;;
    s_done) echo "Fertig" ;;
    done1) echo "Kalmido zeigt den Computer innerhalb einer Minute unter Einstellungen > Agenten (grüner Punkt = verbunden)." ;;
    done2) echo "Wieder entfernen:  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) return 1 ;;
  esac
}
msg_en() {
  case "$1" in
    unknown) echo "agent-setup: unknown option %s" ;;
    undone) echo "agent-setup: undone (the token is revoked again)" ;;
    wrongos) echo "this script is for macOS and Linux; on Windows use agent-setup.ps1 (Kalmido shows that command when you pick Windows)" ;;
    s_prereq) echo "Checking what is needed" ;;
    py_mac) echo "\n  - Python 3.9 or newer: run  xcode-select --install  (or install it from python.org)" ;;
    py_linux) echo "\n  - Python 3.9 or newer: install python3 with your package manager" ;;
    curl) echo "\n  - curl" ;;
    claude) echo "\n  - Claude Code: run  curl -fsSL https://claude.ai/install.sh | bash  and then  claude  once to log in" ;;
    cmd) echo "\n  - the agent command %s" ;;
    missing) echo "agent-setup: missing on this computer:%b\nInstall it and run the same command again (make a new code in Kalmido if 15 minutes have passed)." ;;
    agentcmd) echo "  agent command: %s" ;;
    notlogged) echo "  note: Claude Code seems not logged in yet; run  claude  once and log in" ;;
    nodir) echo "--dir FOLDER is missing (the project folder the agent works in)" ;;
    folder) echo "  project folder: %s" ;;
    instance) echo "  instance: %s" ;;
    rev_fail) echo "  Kalmido did not answer: remove the computer in Settings > Agents if it is still listed" ;;
    rev_ok) echo "  this computer is removed in Kalmido (its token no longer works)" ;;
    rev_err) echo "  cannot revoke the token: %s" ;;
    s_uninstall) echo "Removing the agent of %s from this computer" ;;
    dry_revoke) echo "  (dry run) revoke this computer's token in Kalmido" ;;
    uninstalled) echo "Done. The project folder itself stays as it is." ;;
    nourl) echo "--url is missing (your Kalmido address)" ;;
    nocode) echo "--code is missing (the one-time code from Kalmido)" ;;
    s_connect) echo "Connecting to Kalmido" ;;
    dry_redeem) echo "  (dry run) trade the code for the agent's token at %s/api/agent-setup/redeem (computer %s)" ;;
    nocreate) echo "cannot create %s" ;;
    refused) echo "Kalmido refused the code (HTTP %s): %s" ;;
    refused_def) echo "invalid, used or expired" ;;
    noreach) echo "cannot reach %s: %s" ;;
    stopped) echo "setup stopped (nothing was installed)" ;;
    agent) echo "  agent: %s, token stored in %s (only readable for you)" ;;
    s_starter) echo "Fetching the starter files" ;;
    dry_files) echo "  (dry run) the files of %s/starter_files.txt into %s" ;;
    nobase) echo "Kalmido sent no address for the starter files; use --from DIR" ;;
    nolist) echo "no starter_files.txt in %s" ;;
    nolistfetch) echo "cannot fetch the starter file list (%sstarter_files.txt); this version may not be published yet - try again later or use --from DIR" ;;
    skippath) echo "  skipped %s (no paths allowed)" ;;
    nofetch) echo "cannot fetch %s" ;;
    skipfile) echo "  %s not available (skipped)" ;;
    dry_mcp) echo "  (dry run) write %s (MCP server kalmido: %s %s)" ;;
    s_auto) echo "Starting it at every login" ;;
    noauto) echo "  skipped (--no-autostart); start it with:" ;;
    dry_file) echo "  (dry run) %s:" ;;
    launchfail) echo "launchctl could not load %s" ;;
    launchok) echo "  LaunchAgent %s (starts at login, restarts after a crash; log: %s)" ;;
    sysfail) echo "systemctl --user could not start %s" ;;
    sysok) echo "  systemd --user service %s (log: %s)" ;;
    linger) echo "  it runs while you are logged in; to keep it running after logout: loginctl enable-linger %s" ;;
    s_done) echo "Done" ;;
    done1) echo "Kalmido shows the computer under Settings > Agents within a minute (green dot = connected)." ;;
    done2) echo "Remove it again:  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) echo "$1" ;;
  esac
}
msg() { if [ "$LANGC" = de ]; then msg_de "$1" && return 0; fi; msg_en "$1"; }
[ -z "${UNKNOWN:-}" ] || { printf "$(msg unknown)\n" "$UNKNOWN" >&2; exit 2; }
sayf() { local f; f=$(msg "$1"); shift; printf "$f\n" "$@"; }                 # sayf KEY args...
stepf() { local f; f=$(msg "$1"); shift; printf "\n== $f\n" "$@"; }
dief() { local f; f=$(msg "$1"); shift; die "$(printf "$f" "$@")"; }

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
REDEEMED=0
die() {
  printf 'agent-setup: %s\n' "$*" >&2
  if [ "$REDEEMED" = 1 ]; then revoke; rm -rf "$INST"; sayf undone >&2; fi
  exit 1
}
run() { if [ "$DRY" = 1 ]; then say "  (dry run) $*"; else "$@"; fi; }

case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  *) dief wrongos ;;
esac

# kalmido-setup-step: prereq
stepf s_prereq
missing=""
PY=${KALMIDO_PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1 || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
  if [ "$OS" = mac ]; then missing="$missing$(msg py_mac)"
  else missing="$missing$(msg py_linux)"; fi
fi
command -v curl >/dev/null 2>&1 || missing="$missing$(msg curl)"
AGENT=""
if [ "$UNINSTALL" = 0 ]; then
  AGENT=$(command -v "$CMD" 2>/dev/null || true)
  for p in "$HOME/.local/bin/$CMD" "$HOME/.claude/local/$CMD" "/opt/homebrew/bin/$CMD" "/usr/local/bin/$CMD"; do
    [ -n "$AGENT" ] && break
    [ -x "$p" ] && AGENT=$p
  done
  if [ -z "$AGENT" ]; then
    if [ "$CMD" = claude ]; then missing="$missing$(msg claude)"
    else missing="$missing$(printf "$(msg cmd)" "$CMD")"; fi
  fi
fi
if [ -n "$missing" ]; then
  sayf missing "$missing" >&2
  [ "$DRY" = 1 ] || exit 1
fi
[ -n "$AGENT" ] && sayf agentcmd "$AGENT"
[ "$CMD" = claude ] && [ -n "$AGENT" ] && [ ! -d "$HOME/.claude" ] && sayf notlogged

# kalmido-setup-step: instance
[ -n "$DIR" ] || dief nodir
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
sayf folder "$DIR"
sayf instance "$INST"

# revoke: this computer's token is revoked in Kalmido (POST /api/agent-setup/remove with the token itself)
revoke() {
  [ -f "$ENVF" ] || return 0
  KALMIDO_SETUP_ENV=$ENVF KALMIDO_M_OK="$(msg rev_ok)" KALMIDO_M_ERR="$(msg rev_err)" "$PY" - <<'PYEOF' || sayf rev_fail
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
    sys.exit(os.environ["KALMIDO_M_ERR"] % x)
print(os.environ["KALMIDO_M_OK"])
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
  stepf s_uninstall "$DIR"
  stop_autostart
  if [ -f "$ENVF" ]; then
    if [ "$DRY" = 1 ]; then sayf dry_revoke
    else
      revoke
    fi
  fi
  [ "$OS" = mac ] && [ -f "$PLIST" ] && run rm -f "$PLIST"
  if [ "$OS" = linux ] && [ -f "$UNITF" ]; then run rm -f "$UNITF"; run systemctl --user daemon-reload; fi
  [ -d "$INST" ] && run rm -rf "$INST"
  sayf uninstalled
  exit 0
fi

[ -n "$URL" ] || dief nourl
[ -n "$CODE" ] || [ "$DRY" = 1 ] || dief nocode
URL=${URL%/}

# kalmido-setup-step: redeem
stepf s_connect
HOSTN=$(hostname 2>/dev/null || uname -n); HOSTN=${HOSTN%%.*}
STARTER_BASE=""
if [ "$DRY" = 1 ]; then
  sayf dry_redeem "$URL" "$HOSTN"
else
  run mkdir -p "$INST" || dief nocreate "$INST"
  chmod 700 "$INST"
  # the code goes to python in the environment, the token straight into the env file (mode 600) -- neither is printed
  out=$(KALMIDO_SETUP_CODE=$CODE KALMIDO_SETUP_URL=$URL KALMIDO_SETUP_ENV=$ENVF KALMIDO_SETUP_HOST=$HOSTN \
        KALMIDO_SETUP_DIR=$DIR KALMIDO_SETUP_OS=$OS KALMIDO_M_REF="$(msg refused)" KALMIDO_M_DEF="$(msg refused_def)" KALMIDO_M_REACH="$(msg noreach)" "$PY" - <<'PYEOF'
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
    sys.exit(e["KALMIDO_M_REF"] % (x.code, msg or e["KALMIDO_M_DEF"]))
except (urllib.error.URLError, OSError) as x:
    sys.exit(e["KALMIDO_M_REACH"] % (e["KALMIDO_SETUP_URL"], x))
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
  ) || dief stopped
  IFS=$'\t' read -r AGNAME STARTER_BASE <<< "$out"
  REDEEMED=1
  sayf agent "$AGNAME" "$ENVF"
fi

# kalmido-setup-step: starter_files
stepf s_starter
REQUIRED="agent_launcher.sh agent_run.py kalmido_mcp.py"
fetch() {  # fetch NAME DEST -> 0 when it worked
  if [ -n "$FROM" ]; then [ -f "$FROM/$1" ] && cp "$FROM/$1" "$2"; return; fi
  curl -fsSL --max-time 60 "$STARTER_BASE$1" -o "$2" 2>/dev/null
}
if [ "$DRY" = 1 ]; then
  sayf dry_files "${FROM:-starter}" "$INST"
else
  [ -n "$FROM" ] || [ -n "$STARTER_BASE" ] || dief nobase
  if ! fetch starter_files.txt "$INST/starter_files.txt"; then
    [ -z "$FROM" ] || dief nolist "$FROM"
    # 2.44.0 (review): no fallback to another branch -- the starter must match this instance's version
    dief nolistfetch "$STARTER_BASE"
  fi
  while IFS= read -r f || [ -n "$f" ]; do
    f=${f%%#*}; f=$(printf '%s' "$f" | tr -d ' \r')
    [ -n "$f" ] || continue
    case "$f" in */*|..*) sayf skippath "$f"; continue ;; esac
    if fetch "$f" "$INST/$f.new"; then mv "$INST/$f.new" "$INST/$f"; say "  $f"
    else rm -f "$INST/$f.new"
      case " $REQUIRED " in *" $f "*) dief nofetch "$f" ;; esac
      sayf skipfile "$f"
    fi
  done < "$INST/starter_files.txt"
  chmod +x "$INST/agent_launcher.sh"
fi

# kalmido-setup-step: mcp_config
# the agent command gets the MCP server with --mcp-config (works headless without a trust prompt); the token comes from the
# launcher's environment, so it is in no config file but the env file
MCPJ=$INST/mcp.json
if [ "$DRY" = 1 ]; then sayf dry_mcp "$MCPJ" "$PY" "$INST/kalmido_mcp.py"
else
  "$PY" -c 'import json, sys; json.dump({"mcpServers": {"kalmido": {"command": sys.argv[1], "args": [sys.argv[2]]}}}, open(sys.argv[3], "w"), indent=2)' \
    "$(command -v "$PY")" "$INST/kalmido_mcp.py" "$MCPJ"
fi
run mkdir -p "$DIR"

# kalmido-setup-step: autostart
stepf s_auto
if [ "$NOAUTO" = 1 ]; then
  sayf noauto
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
  if [ "$DRY" = 1 ]; then sayf dry_file "$PLIST"; printf '%s\n' "$plist"
  else
    mkdir -p "$(dirname "$PLIST")"
    printf '%s\n' "$plist" > "$PLIST"
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST" || dief launchfail "$PLIST"
  fi
  sayf launchok "$LABEL" "$INST/agent.log"
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
  if [ "$DRY" = 1 ]; then sayf dry_file "$UNITF"; printf '%s\n' "$unit"
  else
    mkdir -p "$(dirname "$UNITF")"
    printf '%s\n' "$unit" > "$UNITF"
    systemctl --user daemon-reload && systemctl --user enable --now "$UNIT" || dief sysfail "$UNIT"
  fi
  sayf sysok "$UNIT" "$INST/agent.log"
  sayf linger "$(id -un)"
fi

# kalmido-setup-step: done
stepf s_done
sayf done1
sayf done2 "$URL" "$(printf '%q' "$DIR")"
