#!/usr/bin/env bash
# agent-setup.sh -- set up a Kalmido project agent on macOS or Linux with one command (2.44.0, #1517 / #962).
#
# Kalmido shows the command in Settings > Agents > (agent) > "Set up on a computer", e.g.
#   curl -fsSL https://tasks.example.com/agent-setup.sh | KALMIDO_SETUP_CODE=ks_... bash -s -- --url https://tasks.example.com --dir ~/projects/site
# It trades the one-time setup code for the agent's token (stored in a file only you can read, never printed), fetches
# the starter files (mcp/starter_files.txt), and starts the agent in event mode at every login and again after a crash:
# a launchd LaunchAgent on macOS, a systemd --user service on Linux. One instance per project folder (several agents on one
# computer = several folders). Needs: bash (3.2 is enough), curl, python3 3.9+, the agent command (default: claude).
#
# usage: agent-setup.sh --url URL --code CODE --dir FOLDER [--tool claude|codex] [--cmd COMMAND] [--from DIR] [--no-autostart] [--dry-run] [--lang de|en|es|fr|it|nl]
#        [--allow-http]
#        agent-setup.sh --uninstall --dir FOLDER [--dry-run]
#   --url        your Kalmido address
#   --code       the one-time setup code (15 minutes, works once; make a new one in Kalmido when it expired); 2.360.0:
#                better in the environment as KALMIDO_SETUP_CODE (not in the process list of the computer)
#   --allow-http 2.360.0: an http:// address that is not this computer (localhost) -- only for a Kalmido without https
#   --dir        the project folder the agent works in (created when missing)
#   --tool       2.391.0 (#3359): which tool runs the agent: claude (Claude Code, the default) or codex (Codex CLI); without
#                --tool and --cmd the setup asks once on the terminal (Enter = Claude Code; no terminal = Claude Code)
#   --cmd        the agent command (default: the tool's, claude / codex); Claude Code gets --mcp-config with the Kalmido MCP
#                server, Codex CLI the same server with -c mcp_servers.kalmido.command=... (no change of ~/.codex/config.toml)
#   --from DIR   take the starter files from a local copy of mcp/ instead of downloading them
#   --no-autostart  install everything but the autostart (start agent_launcher.sh yourself)
#   --lang       language of the messages: de, en, es, fr, it or nl (Kalmido adds the language of your account; anything else = en)
#   --dry-run    only show what would happen: no code is redeemed, nothing is written, no autostart is loaded
#   --uninstall  stop and remove the autostart, revoke this computer's token in Kalmido, delete the instance folder
# Files: ~/.kalmido/agents/<folder name>-<hash>/ (starter files, kalmido-agent.env with mode 600, mcp.json, agent.log).
set -uo pipefail

URL="" CODE=${KALMIDO_SETUP_CODE:-} DIR="" CMD="" TOOL="" FROM="" DRY=0 UNINSTALL=0 NOAUTO=0 LANGC=en HTTPOK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --url) URL=${2:-}; shift 2 ;;
    --code) CODE=${2:-}; shift 2 ;;
    --dir) DIR=${2:-}; shift 2 ;;
    --cmd) CMD=${2:-}; shift 2 ;;
    --tool) TOOL=${2:-}; shift 2 ;;
    --from) FROM=${2:-}; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-autostart) NOAUTO=1; shift ;;
    --allow-http) HTTPOK=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --lang) LANGC=${2:-en}; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0" 2>/dev/null || echo "see the comment at the top of agent-setup.sh"; exit 0 ;;
    *) UNKNOWN=$1; break ;;
  esac
done
# 2.46.6 (#1713): messages in German or English (--lang); 2.574.0 (#3759): also es, fr, it, nl; anything else = English. bash 3.2: a case table, no assoc arrays.
LANGC=$(printf '%s' "$LANGC" | tr 'A-Z' 'a-z' | cut -c1-2)
case "$LANGC" in de|es|fr|it|nl) ;; *) LANGC=en ;; esac
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
    codex) echo "\n  - Codex CLI: führe  npm install -g @openai/codex  aus und danach einmal  codex login  zum Anmelden" ;;
    notlogged_codex) echo "  Hinweis: Codex CLI scheint noch nicht angemeldet zu sein; führe  codex login  einmal aus" ;;
    ask_tool) echo "Welches Werkzeug soll den Agenten ausführen? 1 = Claude Code (Vorgabe), 2 = Codex CLI: " ;;
    badtool) echo "unbekanntes Werkzeug %s (--tool claude oder codex)" ;;
    missing) echo "agent-setup: auf diesem Computer fehlt noch:%b\nInstalliere es und führe denselben Befehl noch einmal aus (erzeuge in Kalmido einen neuen Code, wenn 15 Minuten vorbei sind)." ;;
    agentcmd) echo "  Agent-Befehl: %s" ;;
    notlogged) echo "  Hinweis: Claude Code scheint noch nicht angemeldet zu sein; führe  claude  einmal aus und melde dich an" ;;
    nodir) echo "--dir ORDNER fehlt (der Projektordner, in dem der Agent arbeitet)" ;;
    folder) echo "  Projektordner: %s" ;;
    instance) echo "  Instanz: %s" ;;
    rev_fail) echo "  Kalmido hat nicht geantwortet: entferne den Computer unter Einstellungen > Agenten, falls er noch aufgelistet ist" ;;
    rev_ok) echo "  dieser Computer ist in Kalmido entfernt (sein Token funktioniert nicht mehr)" ;;
    rev_gone) echo "  der Schlüssel dieses Computers war in Kalmido schon widerrufen (Agent gelöscht oder Computer entfernt): es wird nur hier aufgeräumt" ;;
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
    perm_you) echo "  Rechte-Fragen beantwortet Konto-Id %s (wer den Code erzeugt hat); ändern: in Kalmido beim Agenten unter Laufzeit > Rechte-Fragen an (oder KALMIDO_PERM_USER in %s)" ;;
    perm_kept) echo "  Rechte-Fragen: wie bisher eingestellt (KALMIDO_PERM_USER / KALMIDO_OWNER_IDS in %s)" ;;
    perm_none) echo "  Rechte-Fragen: niemand eingetragen, jede wird abgelehnt; wähle in Kalmido beim Agenten unter Laufzeit > Rechte-Fragen an eine Person oder trage KALMIDO_PERM_USER=<Konto-Id> in %s ein" ;;
    perm_owner) echo "  Rechte-Fragen beantwortet die Person, der der Agent gehört" ;;
    claude_new) echo "  CLAUDE.md angelegt: %s (aus der Vorlage; eigene Regeln oben ergänzen)" ;;
    claude_kept) echo "  CLAUDE.md vorhanden, bleibt unverändert: %s" ;;
    dry_claude) echo "  (Probelauf) CLAUDE.md aus der Vorlage anlegen, wenn keine da ist: %s" ;;
    s_starter) echo "Lade die Starter-Dateien" ;;
    dry_files) echo "  (Probelauf) die Dateien aus %s/starter_files.txt nach %s" ;;
    nobase) echo "Kalmido hat keine Adresse für die Starter-Dateien geschickt; nimm --from ORDNER" ;;
    nohttp) echo "%s ist eine http://-Adresse: der Code und das Token gingen unverschlüsselt durchs Netz. Nimm die https://-Adresse (oder --allow-http, wenn dein Kalmido kein https hat)" ;;
    basehttp) echo "Kalmido hat für die Starter-Dateien eine Adresse ohne https:// geschickt (%s); nimm --from ORDNER" ;;
    nolist) echo "keine starter_files.txt in %s" ;;
    nolistfetch) echo "die Liste der Starter-Dateien (%sstarter_files.txt) kann nicht geladen werden; diese Version ist vielleicht noch nicht veröffentlicht – versuche es später noch einmal oder nimm --from ORDNER" ;;
    skippath) echo "  %s übersprungen (keine Pfade erlaubt)" ;;
    nofetch) echo "%s kann nicht geladen werden" ;;
    shabad) echo "%s weicht von der Prüfsumme ab, die Kalmido geschickt hat – nicht installiert. Die Download-Adresse liefert eine andere Datei als diese Version; frag deinen Kalmido-Admin" ;;
    shanone) echo "  (Kalmido hat keine Prüfsummen der Starter-Dateien geschickt: ältere Version, nicht geprüft)" ;;
    skipfile) echo "  %s nicht verfügbar (übersprungen)" ;;
    dry_mcp) echo "  (Probelauf) %s schreiben (MCP-Server kalmido: %s %s)" ;;
    s_auto) echo "Starte bei jeder Anmeldung" ;;
    noauto) echo "  übersprungen (--no-autostart); starte es mit:" ;;
    dry_file) echo "  (Probelauf) %s:" ;;
    launchfail) echo "launchctl konnte %s nicht laden" ;;
    launchok) echo "  LaunchAgent %s (startet bei der Anmeldung, startet nach einem Absturz neu; Protokoll: %s)" ;;
    launchbg) echo "  %s ist nicht am Bildschirm angemeldet (z. B. per SSH): der Agent läuft jetzt im Hintergrund bis zum nächsten Neustart; danach startet er, sobald du dich am Mac anmeldest" ;;
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
    codex) echo "\n  - Codex CLI: run  npm install -g @openai/codex  and then  codex login  once to log in" ;;
    notlogged_codex) echo "  note: Codex CLI seems not logged in yet; run  codex login  once" ;;
    ask_tool) echo "Which tool should run the agent? 1 = Claude Code (default), 2 = Codex CLI: " ;;
    badtool) echo "unknown tool %s (--tool claude or codex)" ;;
    missing) echo "agent-setup: missing on this computer:%b\nInstall it and run the same command again (make a new code in Kalmido if 15 minutes have passed)." ;;
    agentcmd) echo "  agent command: %s" ;;
    notlogged) echo "  note: Claude Code seems not logged in yet; run  claude  once and log in" ;;
    nodir) echo "--dir FOLDER is missing (the project folder the agent works in)" ;;
    folder) echo "  project folder: %s" ;;
    instance) echo "  instance: %s" ;;
    rev_fail) echo "  Kalmido did not answer: remove the computer in Settings > Agents if it is still listed" ;;
    rev_ok) echo "  this computer is removed in Kalmido (its token no longer works)" ;;
    rev_gone) echo "  the key of this computer was already revoked in Kalmido (agent deleted or computer removed): cleaning up here only" ;;
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
    perm_you) echo "  permission questions are answered by account id %s (who made the code); change it: in Kalmido, the agent's Runtime > Permission questions go to (or KALMIDO_PERM_USER in %s)" ;;
    perm_kept) echo "  permission questions: as set before (KALMIDO_PERM_USER / KALMIDO_OWNER_IDS in %s)" ;;
    perm_none) echo "  permission questions: nobody set, every one is denied; choose a person in Kalmido (the agent's Runtime > Permission questions go to) or add KALMIDO_PERM_USER=<account id> to %s" ;;
    perm_owner) echo "  permission questions are answered by the agent's owner" ;;
    claude_new) echo "  CLAUDE.md created: %s (from the template; add your own rules on top)" ;;
    claude_kept) echo "  CLAUDE.md exists, left as it is: %s" ;;
    dry_claude) echo "  (dry run) create CLAUDE.md from the template when there is none: %s" ;;
    s_starter) echo "Fetching the starter files" ;;
    dry_files) echo "  (dry run) the files of %s/starter_files.txt into %s" ;;
    nobase) echo "Kalmido sent no address for the starter files; use --from DIR" ;;
    nohttp) echo "%s is an http:// address: the code and the token would cross the network unencrypted. Use the https:// address (or --allow-http when your Kalmido has no https)" ;;
    basehttp) echo "Kalmido sent an address without https:// for the starter files (%s); use --from DIR" ;;
    nolist) echo "no starter_files.txt in %s" ;;
    nolistfetch) echo "cannot fetch the starter file list (%sstarter_files.txt); this version may not be published yet - try again later or use --from DIR" ;;
    skippath) echo "  skipped %s (no paths allowed)" ;;
    nofetch) echo "cannot fetch %s" ;;
    shabad) echo "%s does not match the checksum Kalmido sent - not installed. The download address serves another file than this version; ask your Kalmido admin" ;;
    shanone) echo "  (Kalmido sent no checksums of the starter files: an older version, not checked)" ;;
    skipfile) echo "  %s not available (skipped)" ;;
    dry_mcp) echo "  (dry run) write %s (MCP server kalmido: %s %s)" ;;
    s_auto) echo "Starting it at every login" ;;
    noauto) echo "  skipped (--no-autostart); start it with:" ;;
    dry_file) echo "  (dry run) %s:" ;;
    launchfail) echo "launchctl could not load %s" ;;
    launchok) echo "  LaunchAgent %s (starts at login, restarts after a crash; log: %s)" ;;
    launchbg) echo "  %s is not logged in at the screen (e.g. over SSH): the agent runs in the background now until the next restart; after that it starts as soon as you log in on the Mac" ;;
    sysfail) echo "systemctl --user could not start %s" ;;
    sysok) echo "  systemd --user service %s (log: %s)" ;;
    linger) echo "  it runs while you are logged in; to keep it running after logout: loginctl enable-linger %s" ;;
    s_done) echo "Done" ;;
    done1) echo "Kalmido shows the computer under Settings > Agents within a minute (green dot = connected)." ;;
    done2) echo "Remove it again:  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) echo "$1" ;;
  esac
}
msg_es() {
  case "$1" in
    unknown) echo "agent-setup: opción desconocida %s" ;;
    undone) echo "agent-setup: deshecho (el token vuelve a estar revocado)" ;;
    wrongos) echo "este script es para macOS y Linux; en Windows usa agent-setup.ps1 (Kalmido muestra ese comando cuando eliges Windows)" ;;
    s_prereq) echo "Comprobando lo que hace falta" ;;
    py_mac) echo "\n  - Python 3.9 o más reciente: ejecuta  xcode-select --install  (o instálalo desde python.org)" ;;
    py_linux) echo "\n  - Python 3.9 o más reciente: instala python3 con tu gestor de paquetes" ;;
    curl) echo "\n  - curl" ;;
    claude) echo "\n  - Claude Code: ejecuta  curl -fsSL https://claude.ai/install.sh | bash  y después  claude  una vez para iniciar sesión" ;;
    cmd) echo "\n  - el comando del agente %s" ;;
    codex) echo "\n  - Codex CLI: ejecuta  npm install -g @openai/codex  y después  codex login  una vez para iniciar sesión" ;;
    notlogged_codex) echo "  nota: Codex CLI parece no haber iniciado sesión todavía; ejecuta  codex login  una vez" ;;
    ask_tool) echo "¿Qué herramienta debe ejecutar el agente? 1 = Claude Code (predeterminada), 2 = Codex CLI: " ;;
    badtool) echo "herramienta desconocida %s (--tool claude o codex)" ;;
    missing) echo "agent-setup: falta en este ordenador:%b\nInstálalo y ejecuta el mismo comando otra vez (crea un código nuevo en Kalmido si han pasado 15 minutos)." ;;
    agentcmd) echo "  comando del agente: %s" ;;
    notlogged) echo "  nota: Claude Code parece no haber iniciado sesión todavía; ejecuta  claude  una vez e inicia sesión" ;;
    nodir) echo "falta --dir CARPETA (la carpeta del proyecto en la que trabaja el agente)" ;;
    folder) echo "  carpeta del proyecto: %s" ;;
    instance) echo "  instancia: %s" ;;
    rev_fail) echo "  Kalmido no ha respondido: quita el ordenador en Ajustes > Agentes si todavía aparece en la lista" ;;
    rev_ok) echo "  este ordenador se ha quitado en Kalmido (su token ya no funciona)" ;;
    rev_gone) echo "  la clave de este ordenador ya estaba revocada en Kalmido (agente eliminado u ordenador quitado): solo se limpia aquí" ;;
    rev_err) echo "  no se puede revocar el token: %s" ;;
    s_uninstall) echo "Quitando de este ordenador el agente de %s" ;;
    dry_revoke) echo "  (simulacro) revocar en Kalmido el token de este ordenador" ;;
    uninstalled) echo "Listo. La carpeta del proyecto se queda tal como está." ;;
    nourl) echo "falta --url (tu dirección de Kalmido)" ;;
    nocode) echo "falta --code (el código de un solo uso de Kalmido)" ;;
    s_connect) echo "Conectando con Kalmido" ;;
    dry_redeem) echo "  (simulacro) canjear el código por el token del agente en %s/api/agent-setup/redeem (ordenador %s)" ;;
    nocreate) echo "no se puede crear %s" ;;
    refused) echo "Kalmido ha rechazado el código (HTTP %s): %s" ;;
    refused_def) echo "no válido, ya usado o caducado" ;;
    noreach) echo "no se puede acceder a %s: %s" ;;
    stopped) echo "configuración detenida (no se instaló nada)" ;;
    agent) echo "  agente: %s, token guardado en %s (solo legible para ti)" ;;
    perm_you) echo "  las preguntas de permiso las responde la cuenta con id %s (quien creó el código); cambiarlo: en Kalmido, en el agente, Ejecución > Preguntas de permiso a (o KALMIDO_PERM_USER en %s)" ;;
    perm_kept) echo "  preguntas de permiso: como estaban configuradas (KALMIDO_PERM_USER / KALMIDO_OWNER_IDS en %s)" ;;
    perm_none) echo "  preguntas de permiso: no hay nadie asignado, todas se deniegan; elige una persona en Kalmido (en el agente, Ejecución > Preguntas de permiso a) o añade KALMIDO_PERM_USER=<id de cuenta> a %s" ;;
    perm_owner) echo "  las preguntas de permiso las responde la persona a la que pertenece el agente" ;;
    claude_new) echo "  CLAUDE.md creado: %s (a partir de la plantilla; añade tus propias reglas arriba)" ;;
    claude_kept) echo "  CLAUDE.md ya existe, se deja como está: %s" ;;
    dry_claude) echo "  (simulacro) crear CLAUDE.md a partir de la plantilla si no hay ninguno: %s" ;;
    s_starter) echo "Descargando los archivos de inicio" ;;
    dry_files) echo "  (simulacro) los archivos de %s/starter_files.txt en %s" ;;
    nobase) echo "Kalmido no ha enviado ninguna dirección para los archivos de inicio; usa --from CARPETA" ;;
    nohttp) echo "%s es una dirección http://: el código y el token viajarían sin cifrar por la red. Usa la dirección https:// (o --allow-http si tu Kalmido no tiene https)" ;;
    basehttp) echo "Kalmido ha enviado una dirección sin https:// para los archivos de inicio (%s); usa --from CARPETA" ;;
    nolist) echo "no hay starter_files.txt en %s" ;;
    nolistfetch) echo "no se puede descargar la lista de archivos de inicio (%sstarter_files.txt); puede que esta versión aún no esté publicada - inténtalo más tarde o usa --from CARPETA" ;;
    skippath) echo "  %s omitido (no se permiten rutas)" ;;
    nofetch) echo "no se puede descargar %s" ;;
    shabad) echo "%s no coincide con la suma de verificación que envió Kalmido - no se ha instalado. La dirección de descarga sirve otro archivo distinto al de esta versión; consulta a tu administrador de Kalmido" ;;
    shanone) echo "  (Kalmido no ha enviado sumas de verificación de los archivos de inicio: versión anterior, sin comprobar)" ;;
    skipfile) echo "  %s no disponible (omitido)" ;;
    dry_mcp) echo "  (simulacro) escribir %s (servidor MCP kalmido: %s %s)" ;;
    s_auto) echo "Iniciándolo en cada inicio de sesión" ;;
    noauto) echo "  omitido (--no-autostart); inícialo con:" ;;
    dry_file) echo "  (simulacro) %s:" ;;
    launchfail) echo "launchctl no ha podido cargar %s" ;;
    launchok) echo "  LaunchAgent %s (arranca al iniciar sesión, se reinicia tras un fallo; registro: %s)" ;;
    launchbg) echo "  %s no tiene la sesión iniciada en la pantalla (p. ej. por SSH): el agente se ejecuta ahora en segundo plano hasta el próximo reinicio; después arranca en cuanto inicies sesión en el Mac" ;;
    sysfail) echo "systemctl --user no ha podido iniciar %s" ;;
    sysok) echo "  servicio de usuario de systemd %s (registro: %s)" ;;
    linger) echo "  se ejecuta mientras tengas la sesión iniciada; para que siga tras cerrar sesión: loginctl enable-linger %s" ;;
    s_done) echo "Listo" ;;
    done1) echo "Kalmido muestra el ordenador en Ajustes > Agentes en un minuto (punto verde = conectado)." ;;
    done2) echo "Para quitarlo de nuevo:  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) return 1 ;;
  esac
}
msg_fr() {
  case "$1" in
    unknown) echo "agent-setup : option inconnue %s" ;;
    undone) echo "agent-setup : annulé (le jeton est de nouveau révoqué)" ;;
    wrongos) echo "ce script est pour macOS et Linux ; sous Windows, utilise agent-setup.ps1 (Kalmido affiche cette commande quand tu choisis Windows)" ;;
    s_prereq) echo "Vérification de ce qui est nécessaire" ;;
    py_mac) echo "\n  - Python 3.9 ou plus récent : lance  xcode-select --install  (ou installe-le depuis python.org)" ;;
    py_linux) echo "\n  - Python 3.9 ou plus récent : installe python3 avec ton gestionnaire de paquets" ;;
    curl) echo "\n  - curl" ;;
    claude) echo "\n  - Claude Code : lance  curl -fsSL https://claude.ai/install.sh | bash  puis  claude  une fois pour te connecter" ;;
    cmd) echo "\n  - la commande de l'agent %s" ;;
    codex) echo "\n  - Codex CLI : lance  npm install -g @openai/codex  puis  codex login  une fois pour te connecter" ;;
    notlogged_codex) echo "  remarque : Codex CLI ne semble pas encore connecté ; lance  codex login  une fois" ;;
    ask_tool) echo "Quel outil doit exécuter l'agent ? 1 = Claude Code (par défaut), 2 = Codex CLI : " ;;
    badtool) echo "outil inconnu %s (--tool claude ou codex)" ;;
    missing) echo "agent-setup : il manque sur cet ordinateur :%b\nInstalle-le et relance la même commande (crée un nouveau code dans Kalmido si 15 minutes se sont écoulées)." ;;
    agentcmd) echo "  commande de l'agent : %s" ;;
    notlogged) echo "  remarque : Claude Code ne semble pas encore connecté ; lance  claude  une fois et connecte-toi" ;;
    nodir) echo "--dir DOSSIER manque (le dossier du projet dans lequel l'agent travaille)" ;;
    folder) echo "  dossier du projet : %s" ;;
    instance) echo "  instance : %s" ;;
    rev_fail) echo "  Kalmido n'a pas répondu : retire l'ordinateur sous Paramètres > Agents s'il figure encore dans la liste" ;;
    rev_ok) echo "  cet ordinateur est retiré dans Kalmido (son jeton ne fonctionne plus)" ;;
    rev_gone) echo "  la clé de cet ordinateur était déjà révoquée dans Kalmido (agent supprimé ou ordinateur retiré) : seul le nettoyage local est fait" ;;
    rev_err) echo "  impossible de révoquer le jeton : %s" ;;
    s_uninstall) echo "Suppression de l'agent de %s sur cet ordinateur" ;;
    dry_revoke) echo "  (essai à blanc) révoquer dans Kalmido le jeton de cet ordinateur" ;;
    uninstalled) echo "Terminé. Le dossier du projet reste tel quel." ;;
    nourl) echo "--url manque (ton adresse Kalmido)" ;;
    nocode) echo "--code manque (le code à usage unique de Kalmido)" ;;
    s_connect) echo "Connexion à Kalmido" ;;
    dry_redeem) echo "  (essai à blanc) échanger le code contre le jeton de l'agent sur %s/api/agent-setup/redeem (ordinateur %s)" ;;
    nocreate) echo "impossible de créer %s" ;;
    refused) echo "Kalmido a refusé le code (HTTP %s) : %s" ;;
    refused_def) echo "invalide, déjà utilisé ou expiré" ;;
    noreach) echo "%s est inaccessible : %s" ;;
    stopped) echo "configuration interrompue (rien n'a été installé)" ;;
    agent) echo "  agent : %s, jeton enregistré dans %s (lisible par toi seul)" ;;
    perm_you) echo "  les questions d'autorisation reçoivent leur réponse du compte d'id %s (celui qui a créé le code) ; pour changer : dans Kalmido, sur l'agent, Exécution > Questions d'autorisation à (ou KALMIDO_PERM_USER dans %s)" ;;
    perm_kept) echo "  questions d'autorisation : comme réglées auparavant (KALMIDO_PERM_USER / KALMIDO_OWNER_IDS dans %s)" ;;
    perm_none) echo "  questions d'autorisation : personne n'est défini, toutes sont refusées ; choisis une personne dans Kalmido (sur l'agent, Exécution > Questions d'autorisation à) ou ajoute KALMIDO_PERM_USER=<id du compte> à %s" ;;
    perm_owner) echo "  les questions d'autorisation reçoivent leur réponse de la personne à qui appartient l'agent" ;;
    claude_new) echo "  CLAUDE.md créé : %s (d'après le modèle ; ajoute tes propres règles en haut)" ;;
    claude_kept) echo "  CLAUDE.md existe déjà, laissé tel quel : %s" ;;
    dry_claude) echo "  (essai à blanc) créer CLAUDE.md d'après le modèle s'il n'y en a pas : %s" ;;
    s_starter) echo "Téléchargement des fichiers de démarrage" ;;
    dry_files) echo "  (essai à blanc) les fichiers de %s/starter_files.txt dans %s" ;;
    nobase) echo "Kalmido n'a envoyé aucune adresse pour les fichiers de démarrage ; utilise --from DOSSIER" ;;
    nohttp) echo "%s est une adresse http:// : le code et le jeton circuleraient non chiffrés sur le réseau. Utilise l'adresse https:// (ou --allow-http si ton Kalmido n'a pas https)" ;;
    basehttp) echo "Kalmido a envoyé une adresse sans https:// pour les fichiers de démarrage (%s) ; utilise --from DOSSIER" ;;
    nolist) echo "pas de starter_files.txt dans %s" ;;
    nolistfetch) echo "impossible de télécharger la liste des fichiers de démarrage (%sstarter_files.txt) ; cette version n'est peut-être pas encore publiée - réessaie plus tard ou utilise --from DOSSIER" ;;
    skippath) echo "  %s ignoré (chemins interdits)" ;;
    nofetch) echo "impossible de télécharger %s" ;;
    shabad) echo "%s ne correspond pas à la somme de contrôle envoyée par Kalmido - non installé. L'adresse de téléchargement fournit un autre fichier que celui de cette version ; demande à ton administrateur Kalmido" ;;
    shanone) echo "  (Kalmido n'a pas envoyé de sommes de contrôle des fichiers de démarrage : version plus ancienne, non vérifié)" ;;
    skipfile) echo "  %s indisponible (ignoré)" ;;
    dry_mcp) echo "  (essai à blanc) écrire %s (serveur MCP kalmido : %s %s)" ;;
    s_auto) echo "Démarrage à chaque connexion" ;;
    noauto) echo "  ignoré (--no-autostart) ; démarre-le avec :" ;;
    dry_file) echo "  (essai à blanc) %s :" ;;
    launchfail) echo "launchctl n'a pas pu charger %s" ;;
    launchok) echo "  LaunchAgent %s (démarre à la connexion, redémarre après un plantage ; journal : %s)" ;;
    launchbg) echo "  %s n'est pas connecté à l'écran (p. ex. par SSH) : l'agent tourne maintenant en arrière-plan jusqu'au prochain redémarrage ; ensuite il démarre dès que tu te connectes sur le Mac" ;;
    sysfail) echo "systemctl --user n'a pas pu démarrer %s" ;;
    sysok) echo "  service utilisateur systemd %s (journal : %s)" ;;
    linger) echo "  il tourne tant que tu es connecté ; pour qu'il continue après la déconnexion : loginctl enable-linger %s" ;;
    s_done) echo "Terminé" ;;
    done1) echo "Kalmido affiche l'ordinateur sous Paramètres > Agents en une minute (point vert = connecté)." ;;
    done2) echo "Pour le retirer :  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) return 1 ;;
  esac
}
msg_it() {
  case "$1" in
    unknown) echo "agent-setup: opzione sconosciuta %s" ;;
    undone) echo "agent-setup: annullato (il token è di nuovo revocato)" ;;
    wrongos) echo "questo script è per macOS e Linux; su Windows usa agent-setup.ps1 (Kalmido mostra quel comando quando scegli Windows)" ;;
    s_prereq) echo "Controllo di ciò che serve" ;;
    py_mac) echo "\n  - Python 3.9 o più recente: esegui  xcode-select --install  (oppure installalo da python.org)" ;;
    py_linux) echo "\n  - Python 3.9 o più recente: installa python3 con il tuo gestore di pacchetti" ;;
    curl) echo "\n  - curl" ;;
    claude) echo "\n  - Claude Code: esegui  curl -fsSL https://claude.ai/install.sh | bash  e poi  claude  una volta per accedere" ;;
    cmd) echo "\n  - il comando dell'agente %s" ;;
    codex) echo "\n  - Codex CLI: esegui  npm install -g @openai/codex  e poi  codex login  una volta per accedere" ;;
    notlogged_codex) echo "  nota: Codex CLI sembra non avere ancora effettuato l'accesso; esegui  codex login  una volta" ;;
    ask_tool) echo "Quale strumento deve eseguire l'agente? 1 = Claude Code (predefinito), 2 = Codex CLI: " ;;
    badtool) echo "strumento sconosciuto %s (--tool claude o codex)" ;;
    missing) echo "agent-setup: manca su questo computer:%b\nInstallalo ed esegui di nuovo lo stesso comando (crea un nuovo codice in Kalmido se sono passati 15 minuti)." ;;
    agentcmd) echo "  comando dell'agente: %s" ;;
    notlogged) echo "  nota: Claude Code sembra non avere ancora effettuato l'accesso; esegui  claude  una volta e accedi" ;;
    nodir) echo "manca --dir CARTELLA (la cartella del progetto in cui lavora l'agente)" ;;
    folder) echo "  cartella del progetto: %s" ;;
    instance) echo "  istanza: %s" ;;
    rev_fail) echo "  Kalmido non ha risposto: rimuovi il computer in Impostazioni > Agenti se è ancora elencato" ;;
    rev_ok) echo "  questo computer è stato rimosso in Kalmido (il suo token non funziona più)" ;;
    rev_gone) echo "  la chiave di questo computer era già revocata in Kalmido (agente eliminato o computer rimosso): si pulisce solo qui" ;;
    rev_err) echo "  impossibile revocare il token: %s" ;;
    s_uninstall) echo "Rimozione dell'agente di %s da questo computer" ;;
    dry_revoke) echo "  (prova) revocare in Kalmido il token di questo computer" ;;
    uninstalled) echo "Fatto. La cartella del progetto resta com'è." ;;
    nourl) echo "manca --url (il tuo indirizzo Kalmido)" ;;
    nocode) echo "manca --code (il codice monouso di Kalmido)" ;;
    s_connect) echo "Connessione a Kalmido" ;;
    dry_redeem) echo "  (prova) scambiare il codice con il token dell'agente su %s/api/agent-setup/redeem (computer %s)" ;;
    nocreate) echo "impossibile creare %s" ;;
    refused) echo "Kalmido ha rifiutato il codice (HTTP %s): %s" ;;
    refused_def) echo "non valido, già usato o scaduto" ;;
    noreach) echo "impossibile raggiungere %s: %s" ;;
    stopped) echo "configurazione interrotta (non è stato installato nulla)" ;;
    agent) echo "  agente: %s, token salvato in %s (leggibile solo da te)" ;;
    perm_you) echo "  alle richieste di autorizzazione risponde l'account con id %s (chi ha creato il codice); per cambiarlo: in Kalmido, nell'agente, Runtime > Richieste di autorizzazione a (oppure KALMIDO_PERM_USER in %s)" ;;
    perm_kept) echo "  richieste di autorizzazione: come impostate prima (KALMIDO_PERM_USER / KALMIDO_OWNER_IDS in %s)" ;;
    perm_none) echo "  richieste di autorizzazione: nessuno impostato, ogni richiesta viene negata; scegli una persona in Kalmido (nell'agente, Runtime > Richieste di autorizzazione a) oppure aggiungi KALMIDO_PERM_USER=<id account> a %s" ;;
    perm_owner) echo "  alle richieste di autorizzazione risponde la persona a cui appartiene l'agente" ;;
    claude_new) echo "  CLAUDE.md creato: %s (dal modello; aggiungi le tue regole in alto)" ;;
    claude_kept) echo "  CLAUDE.md esiste già, lasciato com'è: %s" ;;
    dry_claude) echo "  (prova) creare CLAUDE.md dal modello se non ce n'è uno: %s" ;;
    s_starter) echo "Scaricamento dei file di avvio" ;;
    dry_files) echo "  (prova) i file di %s/starter_files.txt in %s" ;;
    nobase) echo "Kalmido non ha inviato alcun indirizzo per i file di avvio; usa --from CARTELLA" ;;
    nohttp) echo "%s è un indirizzo http://: il codice e il token viaggerebbero in rete senza cifratura. Usa l'indirizzo https:// (oppure --allow-http se il tuo Kalmido non ha https)" ;;
    basehttp) echo "Kalmido ha inviato un indirizzo senza https:// per i file di avvio (%s); usa --from CARTELLA" ;;
    nolist) echo "nessun starter_files.txt in %s" ;;
    nolistfetch) echo "impossibile scaricare l'elenco dei file di avvio (%sstarter_files.txt); questa versione potrebbe non essere ancora pubblicata - riprova più tardi o usa --from CARTELLA" ;;
    skippath) echo "  %s saltato (percorsi non consentiti)" ;;
    nofetch) echo "impossibile scaricare %s" ;;
    shabad) echo "%s non corrisponde al checksum inviato da Kalmido - non installato. L'indirizzo di download fornisce un file diverso da quello di questa versione; chiedi al tuo amministratore Kalmido" ;;
    shanone) echo "  (Kalmido non ha inviato i checksum dei file di avvio: versione precedente, non verificato)" ;;
    skipfile) echo "  %s non disponibile (saltato)" ;;
    dry_mcp) echo "  (prova) scrivere %s (server MCP kalmido: %s %s)" ;;
    s_auto) echo "Avvio a ogni accesso" ;;
    noauto) echo "  saltato (--no-autostart); avvialo con:" ;;
    dry_file) echo "  (prova) %s:" ;;
    launchfail) echo "launchctl non è riuscito a caricare %s" ;;
    launchok) echo "  LaunchAgent %s (parte all'accesso, riparte dopo un arresto anomalo; registro: %s)" ;;
    launchbg) echo "  %s non ha effettuato l'accesso allo schermo (ad es. via SSH): l'agente ora gira in background fino al prossimo riavvio; dopo parte non appena accedi al Mac" ;;
    sysfail) echo "systemctl --user non è riuscito ad avviare %s" ;;
    sysok) echo "  servizio utente systemd %s (registro: %s)" ;;
    linger) echo "  gira finché sei connesso; per tenerlo attivo anche dopo la disconnessione: loginctl enable-linger %s" ;;
    s_done) echo "Fatto" ;;
    done1) echo "Kalmido mostra il computer in Impostazioni > Agenti entro un minuto (punto verde = connesso)." ;;
    done2) echo "Per rimuoverlo di nuovo:  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) return 1 ;;
  esac
}
msg_nl() {
  case "$1" in
    unknown) echo "agent-setup: onbekende optie %s" ;;
    undone) echo "agent-setup: ongedaan gemaakt (het token is weer ingetrokken)" ;;
    wrongos) echo "dit script is voor macOS en Linux; gebruik op Windows agent-setup.ps1 (Kalmido toont die opdracht als je Windows kiest)" ;;
    s_prereq) echo "Controleren wat er nodig is" ;;
    py_mac) echo "\n  - Python 3.9 of nieuwer: voer  xcode-select --install  uit (of installeer het via python.org)" ;;
    py_linux) echo "\n  - Python 3.9 of nieuwer: installeer python3 met je pakketbeheerder" ;;
    curl) echo "\n  - curl" ;;
    claude) echo "\n  - Claude Code: voer  curl -fsSL https://claude.ai/install.sh | bash  uit en daarna één keer  claude  om in te loggen" ;;
    cmd) echo "\n  - de agentopdracht %s" ;;
    codex) echo "\n  - Codex CLI: voer  npm install -g @openai/codex  uit en daarna één keer  codex login  om in te loggen" ;;
    notlogged_codex) echo "  let op: Codex CLI lijkt nog niet ingelogd te zijn; voer één keer  codex login  uit" ;;
    ask_tool) echo "Welk hulpmiddel moet de agent uitvoeren? 1 = Claude Code (standaard), 2 = Codex CLI: " ;;
    badtool) echo "onbekend hulpmiddel %s (--tool claude of codex)" ;;
    missing) echo "agent-setup: ontbreekt op deze computer:%b\nInstalleer het en voer dezelfde opdracht opnieuw uit (maak een nieuwe code in Kalmido als er 15 minuten voorbij zijn)." ;;
    agentcmd) echo "  agentopdracht: %s" ;;
    notlogged) echo "  let op: Claude Code lijkt nog niet ingelogd te zijn; voer één keer  claude  uit en log in" ;;
    nodir) echo "--dir MAP ontbreekt (de projectmap waarin de agent werkt)" ;;
    folder) echo "  projectmap: %s" ;;
    instance) echo "  instantie: %s" ;;
    rev_fail) echo "  Kalmido heeft niet geantwoord: verwijder de computer onder Instellingen > Agents als hij nog in de lijst staat" ;;
    rev_ok) echo "  deze computer is verwijderd in Kalmido (zijn token werkt niet meer)" ;;
    rev_gone) echo "  de sleutel van deze computer was in Kalmido al ingetrokken (agent verwijderd of computer verwijderd): alleen hier wordt opgeruimd" ;;
    rev_err) echo "  het token kan niet worden ingetrokken: %s" ;;
    s_uninstall) echo "De agent van %s van deze computer verwijderen" ;;
    dry_revoke) echo "  (proefrun) het token van deze computer in Kalmido intrekken" ;;
    uninstalled) echo "Klaar. De projectmap zelf blijft zoals hij is." ;;
    nourl) echo "--url ontbreekt (je Kalmido-adres)" ;;
    nocode) echo "--code ontbreekt (de eenmalige code uit Kalmido)" ;;
    s_connect) echo "Verbinden met Kalmido" ;;
    dry_redeem) echo "  (proefrun) de code inruilen voor het token van de agent bij %s/api/agent-setup/redeem (computer %s)" ;;
    nocreate) echo "%s kan niet worden aangemaakt" ;;
    refused) echo "Kalmido heeft de code geweigerd (HTTP %s): %s" ;;
    refused_def) echo "ongeldig, al gebruikt of verlopen" ;;
    noreach) echo "%s is niet bereikbaar: %s" ;;
    stopped) echo "installatie gestopt (er is niets geïnstalleerd)" ;;
    agent) echo "  agent: %s, token opgeslagen in %s (alleen voor jou leesbaar)" ;;
    perm_you) echo "  toestemmingsvragen worden beantwoord door het account met id %s (wie de code maakte); wijzigen: in Kalmido, bij de agent, Runtime > Toestemmingsvragen naar (of KALMIDO_PERM_USER in %s)" ;;
    perm_kept) echo "  toestemmingsvragen: zoals eerder ingesteld (KALMIDO_PERM_USER / KALMIDO_OWNER_IDS in %s)" ;;
    perm_none) echo "  toestemmingsvragen: niemand ingesteld, elke vraag wordt geweigerd; kies een persoon in Kalmido (bij de agent, Runtime > Toestemmingsvragen naar) of voeg KALMIDO_PERM_USER=<account-id> toe aan %s" ;;
    perm_owner) echo "  toestemmingsvragen worden beantwoord door de eigenaar van de agent" ;;
    claude_new) echo "  CLAUDE.md aangemaakt: %s (uit de sjabloon; voeg je eigen regels bovenaan toe)" ;;
    claude_kept) echo "  CLAUDE.md bestaat al, blijft zoals het is: %s" ;;
    dry_claude) echo "  (proefrun) CLAUDE.md aanmaken uit de sjabloon als er geen is: %s" ;;
    s_starter) echo "De startbestanden ophalen" ;;
    dry_files) echo "  (proefrun) de bestanden uit %s/starter_files.txt naar %s" ;;
    nobase) echo "Kalmido heeft geen adres voor de startbestanden gestuurd; gebruik --from MAP" ;;
    nohttp) echo "%s is een http://-adres: de code en het token zouden onversleuteld over het netwerk gaan. Gebruik het https://-adres (of --allow-http als je Kalmido geen https heeft)" ;;
    basehttp) echo "Kalmido heeft een adres zonder https:// voor de startbestanden gestuurd (%s); gebruik --from MAP" ;;
    nolist) echo "geen starter_files.txt in %s" ;;
    nolistfetch) echo "de lijst met startbestanden (%sstarter_files.txt) kan niet worden opgehaald; deze versie is misschien nog niet gepubliceerd - probeer het later opnieuw of gebruik --from MAP" ;;
    skippath) echo "  %s overgeslagen (paden niet toegestaan)" ;;
    nofetch) echo "%s kan niet worden opgehaald" ;;
    shabad) echo "%s komt niet overeen met de controlesom die Kalmido stuurde - niet geïnstalleerd. Het downloadadres levert een ander bestand dan deze versie; vraag het aan je Kalmido-beheerder" ;;
    shanone) echo "  (Kalmido stuurde geen controlesommen van de startbestanden: oudere versie, niet gecontroleerd)" ;;
    skipfile) echo "  %s niet beschikbaar (overgeslagen)" ;;
    dry_mcp) echo "  (proefrun) %s schrijven (MCP-server kalmido: %s %s)" ;;
    s_auto) echo "Bij elke aanmelding starten" ;;
    noauto) echo "  overgeslagen (--no-autostart); start het met:" ;;
    dry_file) echo "  (proefrun) %s:" ;;
    launchfail) echo "launchctl kon %s niet laden" ;;
    launchok) echo "  LaunchAgent %s (start bij het aanmelden, start opnieuw na een crash; log: %s)" ;;
    launchbg) echo "  %s is niet aangemeld op het scherm (bijv. via SSH): de agent draait nu op de achtergrond tot de volgende herstart; daarna start hij zodra je op de Mac aanmeldt" ;;
    sysfail) echo "systemctl --user kon %s niet starten" ;;
    sysok) echo "  systemd-gebruikersservice %s (log: %s)" ;;
    linger) echo "  hij draait zolang je bent aangemeld; om hem na het afmelden te laten doorlopen: loginctl enable-linger %s" ;;
    s_done) echo "Klaar" ;;
    done1) echo "Kalmido toont de computer binnen een minuut onder Instellingen > Agents (groene stip = verbonden)." ;;
    done2) echo "Om het weer te verwijderen:  curl -fsSL %s/agent-setup.sh | bash -s -- --uninstall --dir %s" ;;
    *) return 1 ;;
  esac
}
msg() { case "$LANGC" in de|es|fr|it|nl) "msg_$LANGC" "$1" && return 0 ;; esac; msg_en "$1"; }  # a missing text falls back to English, never empty
[ -z "${UNKNOWN:-}" ] || { printf "$(msg unknown)\n" "$UNKNOWN" >&2; exit 2; }
sayf() { local f; f=$(msg "$1"); shift; printf "$f\n" "$@"; }                 # sayf KEY args...
stepf() { local f; f=$(msg "$1"); shift; printf "\n== $f\n" "$@"; }
dief() { local f; f=$(msg "$1"); shift; die "$(printf "$f" "$@")"; }

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
REDEEMED=0 AUTOFILE=""
die() {
  printf 'agent-setup: %s\n' "$*" >&2
  # 2.157.0 (#1517): an autostart file written by this run goes too, else launchd / systemd keep starting a deleted folder
  [ -z "$AUTOFILE" ] || rm -f "$AUTOFILE"
  if [ "$REDEEMED" = 1 ]; then revoke; rm -rf "$INST"; sayf undone >&2; fi
  exit 1
}
run() { if [ "$DRY" = 1 ]; then say "  (dry run) $*"; else "$@"; fi; }

case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  *) dief wrongos ;;
esac

# 2.391.0 (#3359): the tool (Claude Code by default). Asked once on the terminal when neither --tool nor --cmd names it (curl |
# bash: the answer comes from /dev/tty, stdin is the script); no terminal, a dry run or the uninstall: Claude Code.
if [ -z "$TOOL" ] && [ -n "$CMD" ]; then
  case "$(basename "$CMD")" in codex|codex.*) TOOL=codex ;; *) TOOL=claude ;; esac
fi
if [ -z "$TOOL" ] && [ "$DRY" = 0 ] && [ "$UNINSTALL" = 0 ] && [ -t 2 ] && (: < /dev/tty) 2>/dev/null; then
  printf '%s' "$(msg ask_tool)" >&2
  ans=""; read -r -t 120 ans < /dev/tty || ans=""
  case "$ans" in 2|codex|Codex*) TOOL=codex ;; esac
fi
TOOL=${TOOL:-claude}
case "$TOOL" in claude|codex) ;; *) dief badtool "$TOOL" ;; esac
[ -n "$CMD" ] || CMD=$TOOL

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
    elif [ "$CMD" = codex ]; then missing="$missing$(msg codex)"
    else missing="$missing$(printf "$(msg cmd)" "$CMD")"; fi
  fi
fi
if [ -n "$missing" ]; then
  sayf missing "$missing" >&2
  [ "$DRY" = 1 ] || exit 1
fi
[ -n "$AGENT" ] && sayf agentcmd "$AGENT"
[ "$CMD" = claude ] && [ -n "$AGENT" ] && [ ! -d "$HOME/.claude" ] && sayf notlogged
[ "$TOOL" = codex ] && [ -n "$AGENT" ] && [ ! -f "${CODEX_HOME:-$HOME/.codex}/auth.json" ] && sayf notlogged_codex

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
  KALMIDO_SETUP_ENV=$ENVF KALMIDO_M_OK="$(msg rev_ok)" KALMIDO_M_GONE="$(msg rev_gone)" KALMIDO_M_ERR="$(msg rev_err)" "$PY" - <<'PYEOF' || sayf rev_fail
import os, sys, urllib.error, urllib.request
env = {}
for ln in open(os.environ["KALMIDO_SETUP_ENV"], encoding="utf-8"):
    k, _, v = ln.strip().partition("=")
    env[k] = v.strip("'\"")
req = urllib.request.Request(env["KALMIDO_URL"].rstrip("/") + "/api/agent-setup/remove", data=b"{}", method="POST",
                             headers={"Authorization": "Bearer " + env["KALMIDO_TOKEN"], "X-Requested-With": "kalmido",
                                      "Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=20).read()
except urllib.error.HTTPError as x:  # 2.47.3 (#1729): 401 = the key is already revoked (agent deleted): only a hint, the cleanup goes on
    if x.code == 401:
        print(os.environ["KALMIDO_M_GONE"])
        sys.exit(0)
    sys.exit(os.environ["KALMIDO_M_ERR"] % x)
except Exception as x:  # noqa: BLE001 -- one short line, no traceback
    sys.exit(os.environ["KALMIDO_M_ERR"] % x)
print(os.environ["KALMIDO_M_OK"])
PYEOF
}

# kalmido-setup-step: autostart_stop
stop_autostart() {
  if [ "$OS" = mac ]; then
    [ -f "$PLIST" ] && run launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null
    # 2.157.0 (#1517): the background copy of a setup without a screen login (see launch_bg)
    if [ -f "$INST/launchd-now.plist" ]; then
      run launchctl bootout "user/$(id -u)/$LABEL.now" 2>/dev/null
      run rm -f "$INST/launchd-now.plist"
    fi
  else
    [ -f "$UNITF" ] && run systemctl --user disable --now "$UNIT" 2>/dev/null
  fi
  # 2.443.0 (#2940): a launcher of this instance that is still running (started by hand), as in setup.ps1; its TERM trap ends the agent
  stale=$( { ps -A -o pid= -o args= | KALMIDO_INST=$INST awk 'index($0, ENVIRON["KALMIDO_INST"] "/agent_launcher.sh") { print $1 }'; } 2>/dev/null)
  # shellcheck disable=SC2086 -- a list of numbers
  [ -z "$stale" ] || run kill -TERM $stale 2>/dev/null
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
# 2.360.0 C (#2496): https only, except this computer (localhost) or --allow-http for a Kalmido without https
case "$URL" in
  https://*|http://localhost|http://localhost[:/]*|http://127.0.0.1|http://127.0.0.1[:/]*|http://\[::1\]|http://\[::1\][:/]*) ;;
  *) [ "$HTTPOK" = 1 ] || dief nohttp "$URL" ;;
esac

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
import json, os, re, shlex, sys, urllib.error, urllib.request
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
# 2.306.0 E (#2927): who answers permission questions -- kept from an earlier setup of this folder, else (team agent) the
# person who made the code (operator_id), as KALMIDO_PERM_USER; KALMIDO_OWNER_IDS would also narrow who gives orders
keep = []
try:
    with open(e["KALMIDO_SETUP_ENV"], encoding="utf-8") as f:
        keep = [ln.rstrip("\n") for ln in f if ln.startswith(("KALMIDO_PERM_USER=", "KALMIDO_OWNER_IDS="))]
except OSError:
    pass
op = r.get("operator_id")
perm = "kept" if keep else str(int(op)) if isinstance(op, int) else "none" if r["agent"].get("team") else "owner"
if not keep and isinstance(op, int):
    keep = ["KALMIDO_PERM_USER=%d" % op]
# 2.306.0 (#2927): the name goes into a comment line and the tab-separated answer below: no control characters
nm, un = (re.sub(r"[\x00-\x1f\x7f]", " ", str(r["agent"].get(k) or "")) for k in ("name", "username"))
old = os.umask(0o077)
with open(e["KALMIDO_SETUP_ENV"] + ".new", "w", encoding="utf-8") as f:
    f.write("# Kalmido agent %s (%s), set up by agent-setup.sh -- keep this file private\n" % (nm, un))
    f.write("KALMIDO_URL=%s\nKALMIDO_TOKEN=%s\nKALMIDO_EVENTS=1\n" % (e["KALMIDO_SETUP_URL"], r["token"]))  # the address that worked here
    f.write("# KALMIDO_TOOLSETS=tickets,code,chat   # optional (2.391.0): only these MCP tool packages, chat is always on; default: all\n")
    # one state folder per instance (event cursor, approvals, lock): two project folders on one computer never share one
    # 2.443.0 (#2940): quoted, the launcher reads this file as shell (a space in the home folder)
    f.write("KALMIDO_STATE_DIR=%s\n" % shlex.quote(os.path.join(os.path.dirname(e["KALMIDO_SETUP_ENV"]), "state")))
    if e.get("KALMIDO_PYTHON"):  # 2.443.0 (#2940): the autostart runs without this shell's variables
        f.write("KALMIDO_PYTHON=%s\n" % shlex.quote(e["KALMIDO_PYTHON"]))
    f.write("".join(ln + "\n" for ln in keep))
os.umask(old)
os.chmod(e["KALMIDO_SETUP_ENV"] + ".new", 0o600)
os.replace(e["KALMIDO_SETUP_ENV"] + ".new", e["KALMIDO_SETUP_ENV"])
# 2.306.0 (#2927): the server's version next to the starter files (the MCP server reports it; they have no VERSION file)
ver = str(r.get("version") or "")
# 2.380 G (#3390): the checksums of the starter files ("<sha256>  <name>" lines; none from an older Kalmido = no file, no check)
shaf = os.path.join(os.path.dirname(e["KALMIDO_SETUP_ENV"]), "starter_sha256.txt")
sha = r.get("starter_sha256") if isinstance(r.get("starter_sha256"), dict) else {}
sha = {k: v for k, v in sha.items() if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", str(k)) and re.fullmatch(r"[0-9a-f]{64}", str(v))}
if sha:
    with open(shaf, "w", encoding="utf-8") as f:
        f.write("".join("%s  %s\n" % (v, k) for k, v in sorted(sha.items())))
elif os.path.exists(shaf):
    os.remove(shaf)
if re.fullmatch(r"\d+(\.\d+){1,3}", ver):
    with open(os.path.join(os.path.dirname(e["KALMIDO_SETUP_ENV"]), "VERSION"), "w", encoding="utf-8") as f:
        f.write(ver + "\n")
print("%s\t%s\t%s" % (nm, perm, r.get("starter_base") or ""))
PYEOF
  ) || dief stopped
  IFS=$'\t' read -r AGNAME PERM STARTER_BASE <<< "$out"
  REDEEMED=1
  sayf agent "$AGNAME" "$ENVF"
  case "$PERM" in
    kept) sayf perm_kept "$ENVF" ;;
    none) sayf perm_none "$ENVF" ;;
    owner) sayf perm_owner ;;
    *) sayf perm_you "$PERM" "$ENVF" ;;
  esac
fi

# kalmido-setup-step: starter_files
stepf s_starter
REQUIRED="agent_launcher.sh agent_run.py kalmido_mcp.py"
fetch() {  # fetch NAME DEST -> 0 when it worked
  if [ -n "$FROM" ]; then [ -f "$FROM/$1" ] && cp "$FROM/$1" "$2"; return; fi
  curl -fsSL --max-time 60 "$STARTER_BASE$1" -o "$2" 2>/dev/null
}
# 2.380 G (#3390): a downloaded starter file must have the checksum Kalmido sent with the token (starter_sha256.txt); a file
# that differs or is not in the list stops the setup before it is installed. --from DIR (a local copy) and an older Kalmido
# without checksums are not checked
SHAF=$INST/starter_sha256.txt
shaok() {  # shaok NAME FILE -> 0 when FILE may be installed as NAME
  [ -z "$FROM" ] && [ -s "$SHAF" ] || return 0
  "$PY" -c 'import hashlib, sys
want = dict(reversed(ln.split()) for ln in open(sys.argv[1], encoding="utf-8") if len(ln.split()) == 2)
sys.exit(0 if want.get(sys.argv[2]) == hashlib.sha256(open(sys.argv[3], "rb").read()).hexdigest() else 1)' "$SHAF" "$1" "$2" 2>/dev/null
}
if [ "$DRY" = 1 ]; then
  sayf dry_files "${FROM:-starter}" "$INST"
else
  [ -n "$FROM" ] || [ -n "$STARTER_BASE" ] || dief nobase
  # 2.360.0 C (#2496): the starter files (they run here) only over https or from this Kalmido itself
  case "$STARTER_BASE" in ""|https://*|"$URL"/*) ;; *) [ -n "$FROM" ] || dief basehttp "$STARTER_BASE" ;; esac
  [ -n "$FROM" ] || [ -s "$SHAF" ] || sayf shanone
  rm -f "$INST"/*.new  # 2.443.0 (#2940): what a broken earlier setup left, as in setup.ps1
  if ! fetch starter_files.txt "$INST/starter_files.txt.new"; then
    rm -f "$INST/starter_files.txt.new"
    [ -z "$FROM" ] || dief nolist "$FROM"
    # 2.44.0 (review): no fallback to another branch -- the starter must match this instance's version
    dief nolistfetch "$STARTER_BASE"
  fi
  shaok starter_files.txt "$INST/starter_files.txt.new" || { rm -f "$INST/starter_files.txt.new"; dief shabad starter_files.txt; }
  mv "$INST/starter_files.txt.new" "$INST/starter_files.txt"
  while IFS= read -r f || [ -n "$f" ]; do
    f=${f%%#*}; f=$(printf '%s' "$f" | tr -d ' \r')
    [ -n "$f" ] || continue
    case "$f" in */*|..*) sayf skippath "$f"; continue ;; esac
    if fetch "$f" "$INST/$f.new"; then
      shaok "$f" "$INST/$f.new" || { rm -f "$INST/$f.new"; dief shabad "$f"; }
      mv "$INST/$f.new" "$INST/$f"; say "  $f"
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
MCPARGS=(--mcp-config "$MCPJ")
if [ "$TOOL" = codex ]; then
  # 2.391.0 (#3359): Codex CLI takes the same server per run (-c, nothing written into ~/.codex/config.toml); Codex hands MCP
  # servers only a few environment variables, so a small wrapper next to the env file reads it and starts the server
  MCPJ=$INST/kalmido_mcp_run.sh
  MCPARGS=(--skip-git-repo-check -c "mcp_servers.kalmido.command=\"$MCPJ\"")
fi
if [ "$DRY" = 1 ]; then sayf dry_mcp "$MCPJ" "$PY" "$INST/kalmido_mcp.py"
elif [ "$TOOL" = codex ]; then
  printf '#!/usr/bin/env bash\n# 2.391.0 (#3359): the Kalmido MCP server for Codex CLI, with the env file of this agent\nset -a\n. %q\nset +a\nexec %q %q\n' \
    "$ENVF" "$(command -v "$PY")" "$INST/kalmido_mcp.py" > "$MCPJ"
  chmod 700 "$MCPJ"
else
  "$PY" -c 'import json, sys; json.dump({"mcpServers": {"kalmido": {"command": sys.argv[1], "args": [sys.argv[2]]}}}, open(sys.argv[3], "w"), indent=2)' \
    "$(command -v "$PY")" "$INST/kalmido_mcp.py" "$MCPJ"
fi
run mkdir -p "$DIR"

# kalmido-setup-step: claude_md
# 2.306.0 E (#2927): a CLAUDE.md for the project folder from mcp/CLAUDE.template.md (the rules between its markers) when the
# folder has none yet -- never overwritten
if [ -e "$DIR/CLAUDE.md" ] || [ -e "$DIR/.claude/CLAUDE.md" ]; then sayf claude_kept "$DIR/CLAUDE.md"
elif [ "$DRY" = 1 ]; then sayf dry_claude "$DIR/CLAUDE.md"
elif [ -f "$INST/CLAUDE.template.md" ] && "$PY" - "$INST/CLAUDE.template.md" "$DIR/CLAUDE.md" <<'PYEOF'
import sys
t = open(sys.argv[1], encoding="utf-8").read()
a, b = t.find("<!-- kalmido-agent-rules:start -->"), t.find("<!-- kalmido-agent-rules:end -->")
if a < 0 or b < a:
    sys.exit(1)
head = ("# Rules for this project\n\n"
        "<!-- Created by the Kalmido agent setup. Add your own rules here: what this agent works on, and, to narrow it\n"
        "further, the Kalmido account ids allowed to give it orders. The launcher's fixed rules come first in every run and\n"
        "this file cannot weaken them. -->\n\n")
with open(sys.argv[2], "x", encoding="utf-8") as f:
    f.write(head + t[a:b + len("<!-- kalmido-agent-rules:end -->")] + "\n")
PYEOF
then sayf claude_new "$DIR/CLAUDE.md"
fi

# kalmido-setup-step: autostart
stepf s_auto
if [ "$NOAUTO" = 1 ]; then
  sayf noauto
  say "  cd $(printf '%q' "$DIR") && bash $(printf '%q' "$INST/agent_launcher.sh") -e $(printf '%q' "$ENVF") --events -- $(printf '%q' "${AGENT:-$CMD}")$(printf ' %q' "${MCPARGS[@]}")"
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
    <string>--events</string><string>--</string><string>$(xml "${AGENT:-$CMD}")</string>$(for a in "${MCPARGS[@]}"; do printf '<string>%s</string>' "$(xml "$a")"; done)
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
    printf '%s\n' "$plist" > "$PLIST"; AUTOFILE=$PLIST
    # 2.157.0 (#1517): without a screen login of this user (setup over SSH) there is no gui domain: the LaunchAgent above
    # starts at the next login; until then a copy runs in the user's background domain (until the next restart). The
    # runner lock (#1448) keeps the two from working at the same time once the person logs in.
    launch_bg() {
      launchctl print "gui/$(id -u)" >/dev/null 2>&1 && return 1
      printf '%s\n' "$plist" | sed -e "s#<string>$LABEL</string>#<string>$LABEL.now</string>#" \
        -e 's#<key>RunAtLoad</key>#<key>LimitLoadToSessionType</key><string>Background</string><key>RunAtLoad</key>#' > "$INST/launchd-now.plist"
      launchctl bootstrap "user/$(id -u)" "$INST/launchd-now.plist" 2>/dev/null || return 1
      sayf launchbg "$(id -un)"
    }
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launch_bg || launchctl load -w "$PLIST" || dief launchfail "$PLIST"
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
ExecStart=/usr/bin/env bash $(q "$INST/agent_launcher.sh") -e $(q "$ENVF") --events -- $(q "${AGENT:-$CMD}")$(for a in "${MCPARGS[@]}"; do printf ' %s' "$(q "$a")"; done)
Restart=always
RestartSec=30
StandardOutput=append:$INST/agent.log
StandardError=append:$INST/agent.log

[Install]
WantedBy=default.target"
  if [ "$DRY" = 1 ]; then sayf dry_file "$UNITF"; printf '%s\n' "$unit"
  else
    mkdir -p "$(dirname "$UNITF")"
    printf '%s\n' "$unit" > "$UNITF"; AUTOFILE=$UNITF
    systemctl --user daemon-reload && systemctl --user enable --now "$UNIT" || dief sysfail "$UNIT"
  fi
  sayf sysok "$UNIT" "$INST/agent.log"
  sayf linger "$(id -un)"
fi

# kalmido-setup-step: done
stepf s_done
sayf done1
sayf done2 "$URL" "$(printf '%q' "$DIR")"
