#!/bin/sh
# Kalmido installer for macOS and Linux.
#
#   curl -fsSL https://kalmido.com/install.sh | sh
#
# Source of this script: install.sh in the Kalmido repository (the website serves the same file).
#
# Installs (or updates) Kalmido from GitHub and starts it with Docker Compose. Release versions use
# the prebuilt image ghcr.io/gegenschuss/kalmido:<version> (amd64 / arm64); if that cannot be pulled,
# the image is built locally from the source.
# To update later: run update.sh in the install folder (or this command again). Your .env, data/ and
# secret/ are kept, and the database is backed up to data/backups/ first.
# A new installation prints the one-time setup code from the server log (the setup page asks for it),
# keeps the server key in secret/kalmido.key and backs up daily into data/backups/.
#
# Options (environment variables):
#   KALMIDO_DIR      install folder                        (default: $HOME/kalmido)
#   KALMIDO_PORT     port on 127.0.0.1                     (default: 3040)
#   KALMIDO_VERSION  release tag (vX.Y.Z) or branch        (default: the latest release)
#   KALMIDO_BUILD=1  always build locally instead of pulling the prebuilt image
#
# The script never uses sudo. Source: https://github.com/Gegenschuss/kalmido (AGPL-3.0)

# Everything is inside main(), which is only called on the last line: a download cut off
# halfway through cannot run a partial script.

set -eu

GH="https://github.com/Gegenschuss/kalmido"
GH_API="https://api.github.com/repos/Gegenschuss/kalmido"
IMAGE_REPO="${KALMIDO_IMAGE_REPO:-ghcr.io/gegenschuss/kalmido}"   # override only for mirrors / tests

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33mNote:\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# docker compose (v2 plugin) or docker-compose (v1), chosen in check_docker
dc() {
  if [ "$COMPOSE" = plugin ]; then docker compose "$@"; else docker-compose "$@"; fi
}

check_docker() {
  os=$(uname -s)
  if ! command -v docker >/dev/null 2>&1; then
    case "$os" in
      Darwin) die "Docker is not installed. Install Docker Desktop for Mac:
  https://docs.docker.com/desktop/setup/install/mac-install/
Start it once, then run this installer again." ;;
      *) die "Docker is not installed. Install Docker Engine and the Compose plugin from your
distribution's packages (for example: Debian/Ubuntu 'docker.io docker-compose-v2',
Fedora 'docker docker-compose', Arch 'docker docker-compose') or follow
  https://docs.docker.com/engine/install/
then run this installer again." ;;
    esac
  fi

  if ! err=$(docker info 2>&1 >/dev/null); then
    case "$err" in
      *"permission denied"*)
        die "Docker is installed, but your user may not use it.
Add yourself to the docker group, log out and in again, then rerun this installer:
  sudo usermod -aG docker \"\$USER\"" ;;
      *)
        if [ "$os" = Darwin ]; then
          die "Docker is installed but not running. Start Docker Desktop and run this installer again."
        fi
        die "Docker is installed but not running. Start it (for example: sudo systemctl enable --now docker)
and run this installer again." ;;
    esac
  fi

  if docker compose version >/dev/null 2>&1; then
    COMPOSE=plugin
  elif command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
    COMPOSE=standalone
  else
    die "Docker Compose is missing. Docker Desktop includes it; on Linux install the
Compose plugin (package 'docker-compose-plugin' or 'docker-compose-v2')."
  fi
  say "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'), compose: $COMPOSE"
}

detect_tz() {
  tz="${TZ:-}"
  if [ -z "$tz" ] && [ -r /etc/timezone ]; then tz=$(head -n 1 /etc/timezone); fi
  if [ -z "$tz" ] && [ -L /etc/localtime ]; then
    tz=$(readlink /etc/localtime | sed -n 's|.*zoneinfo/||p')
  fi
  if [ -z "$tz" ] && command -v timedatectl >/dev/null 2>&1; then
    tz=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  fi
  case "$tz" in
    ""|*[!A-Za-z0-9_/+-]*) tz="UTC" ;;
  esac
  printf '%s' "$tz"
}

fetch_code() {
  if command -v git >/dev/null 2>&1 && { [ -d "$DIR/.git" ] || [ ! -e "$DIR" ]; }; then
    if [ -d "$DIR/.git" ]; then
      step "Updating $DIR to $VERSION (git)"
      git -C "$DIR" fetch --quiet --depth 1 origin "$VERSION" \
        || die "Could not fetch '$VERSION' from GitHub. Is it an existing tag or branch?"
      git -C "$DIR" checkout --quiet --force FETCH_HEAD 2>/dev/null \
        || die "Could not update the files in $DIR (local changes?). Check 'git -C $DIR status'."
    else
      step "Downloading Kalmido $VERSION (git clone)"
      git clone --quiet --depth 1 --branch "$VERSION" "$GH.git" "$DIR" \
        || die "Could not clone '$VERSION' from GitHub. Is it an existing tag or branch?"
    fi
    REV=$(git -C "$DIR" rev-parse --short HEAD)
  else
    step "Downloading Kalmido $VERSION (tarball)"
    command -v tar >/dev/null 2>&1 || die "Neither git nor tar is available."
    tmp=$(mktemp -d 2>/dev/null || mktemp -d -t kalmido)
    # shellcheck disable=SC2064
    trap "rm -rf '$tmp'" EXIT INT TERM
    curl -fsSL "$GH/archive/$VERSION.tar.gz" -o "$tmp/src.tar.gz" \
      || die "Could not download '$VERSION' from GitHub. Is it an existing tag or branch?"
    mkdir -p "$tmp/src"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp/src" --strip-components 1
    [ -f "$tmp/src/docker-compose.yml" ] || die "The download does not look like Kalmido."
    mkdir -p "$DIR"
    # overwrite the program files, keep .env, data/ and the override file
    cp -R "$tmp/src/." "$DIR/"
    REV="$VERSION (tarball)"
  fi
  printf '%s\n' "$VERSION" > "$DIR/.kalmido-version"
}

# KALMIDO_VERSION unset: the latest GitHub release (falls back to the main branch if there is none)
resolve_version() {
  VERSION="${KALMIDO_VERSION:-}"
  if [ -z "$VERSION" ]; then
    VERSION=$(curl -fsSL -H "Accept: application/vnd.github+json" "$GH_API/releases/latest" 2>/dev/null \
      | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1) || true
    [ -n "$VERSION" ] || VERSION=main
  fi
  case "$VERSION" in
    [0-9]*.[0-9]*.[0-9]*) VERSION="v$VERSION" ;;   # 1.0.0 -> v1.0.0
  esac
  case "$VERSION" in
    ""|-*|*[!A-Za-z0-9._/-]*) die "KALMIDO_VERSION must be a tag or branch name." ;;
  esac
}

# release tags (vX.Y.Z) have a prebuilt image; branches are always built locally
choose_image() {
  IMAGE=""
  if [ "${KALMIDO_BUILD:-0}" = 1 ]; then return 0; fi
  if printf '%s' "$VERSION" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
    IMAGE="$IMAGE_REPO:${VERSION#v}"
  fi
}

# before an update: consistent copy of the database (SQLite backup API inside the running container,
# or a plain copy when it is stopped); the last 10 copies are kept in data/backups/
backup_db() {
  db="$DIR/data/tasks.db"
  if [ ! -f "$db" ]; then
    # 2.37+: PostgreSQL in the db service -> pg_dump (custom format) into data/backups/
    (cd "$DIR" && dc ps -q db 2>/dev/null | grep -q .) || return 0
    step "Backing up your database"
    mkdir -p "$DIR/data/backups"
    name="kalmido-$(date +%Y%m%d-%H%M%S).dump"
    (cd "$DIR" && dc exec -T db sh -c 'PGOPTIONS="-c app.role=system" pg_dump -Fc --enable-row-security -U "$POSTGRES_USER" -d "$POSTGRES_DB"') \
      > "$DIR/data/backups/$name" && [ -s "$DIR/data/backups/$name" ] \
      || { rm -f "$DIR/data/backups/$name"; die "Could not back up the database. Nothing was changed."; }
    say "Saved data/backups/$name"
    # shellcheck disable=SC2012
    ls -1t "$DIR"/data/backups/kalmido-*.dump 2>/dev/null | tail -n +11 | while IFS= read -r old; do rm -f "$old"; done
    return 0
  fi
  step "Backing up your database"
  mkdir -p "$DIR/data/backups"
  name="tasks-$(date +%Y%m%d-%H%M%S).db"
  if (cd "$DIR" && dc exec -T kalmido python -c "import sqlite3; s = sqlite3.connect('/data/tasks.db'); d = sqlite3.connect('/data/backups/$name'); s.backup(d); d.close()") >/dev/null 2>&1 \
     && [ -s "$DIR/data/backups/$name" ]; then
    say "Saved data/backups/$name (copy of the running database)"
  else
    cp "$db" "$DIR/data/backups/$name" || die "Could not back up $db. Nothing was changed."
    if [ -f "$db-wal" ]; then cp "$db-wal" "$DIR/data/backups/$name-wal"; fi
    say "Saved data/backups/$name"
  fi
  # shellcheck disable=SC2012
  ls -1t "$DIR"/data/backups/tasks-*.db 2>/dev/null | tail -n +11 | while IFS= read -r old; do
    rm -f "$old" "$old-wal"
  done
}

write_update_script() {
  cat > "$DIR/update.sh" <<'UPD'
#!/bin/sh
# Updates this Kalmido installation (written by the Kalmido installer):
# backs up the database to data/backups/, fetches the latest release (or KALMIDO_VERSION=v1.2.3),
# pulls the prebuilt image (or builds it) and restarts. Your .env, data/ and secret/ are kept.
set -eu
cd "$(dirname "$0")"
KALMIDO_DIR=$(pwd)
export KALMIDO_DIR
curl -fsSL "${KALMIDO_INSTALLER_URL:-https://kalmido.com/install.sh}" | sh
UPD
  chmod 755 "$DIR/update.sh"
}

# 2.37: PostgreSQL needs a password in .env (new and existing installations); generated once, never shown
ensure_pg_password() {
  grep -q '^POSTGRES_PASSWORD=.' "$DIR/.env" 2>/dev/null && return 0
  pw=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 32)
  [ ${#pw} = 32 ] || die "Could not generate a database password."
  if grep -q '^POSTGRES_PASSWORD=' "$DIR/.env"; then
    sed -i.bak "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$pw|" "$DIR/.env" && rm -f "$DIR/.env.bak"
  else
    printf '\n# PostgreSQL password (generated by the installer)\nPOSTGRES_PASSWORD=%s\n' "$pw" >> "$DIR/.env"
  fi
  chmod 600 "$DIR/.env"
  say "Added a database password to .env (POSTGRES_PASSWORD)"
}

write_env() {
  if [ -f "$DIR/.env" ]; then
    say "Keeping your existing .env"
    ensure_pg_password
    return
  fi
  tz=$(detect_tz)
  sed -e "s|^TZ=.*|TZ=$tz|" -e "s|^PUBLIC_URL=.*|PUBLIC_URL=http://localhost:$PORT|" \
    "$DIR/.env.example" > "$DIR/.env"
  chmod 600 "$DIR/.env"
  say "Created .env (TZ=$tz, PUBLIC_URL=http://localhost:$PORT)"
  ensure_pg_password
}

# The tracked docker-compose.yml publishes 127.0.0.1:3040. Anything else goes into a generated
# docker-compose.override.yml, which Compose reads automatically.
OVR_MARK="# generated by the Kalmido installer"
write_override() {
  ovr="$DIR/docker-compose.override.yml"
  netmode="${1:-}"
  if [ -f "$ovr" ] && ! head -n 1 "$ovr" | grep -q "^$OVR_MARK"; then
    warn "Keeping your own docker-compose.override.yml (not written by this installer)."
    [ "$PORT" = 3040 ] || warn "KALMIDO_PORT=$PORT is ignored; set the port in that file yourself."
    if [ -n "$IMAGE" ]; then
      warn "Building locally instead of using the prebuilt image (set KALMIDO_IMAGE in .env to use it)."
      IMAGE=""
    fi
    return
  fi
  if [ -z "$netmode" ] && [ -f "$ovr" ] && grep -q '^    network_mode: bridge' "$ovr"; then
    netmode=bridge
  fi
  uidline=""
  if [ "$(uname -s)" = Linux ] && [ "$(id -u)" != 1000 ]; then
    # the image runs as 1000:1000 by default; use your own user so it can write ./data
    uidline="    user: \"$(id -u):$(id -g)\""
  fi
  if [ "$PORT" = 3040 ] && [ -z "$netmode" ] && [ -z "$uidline" ] && [ -z "$IMAGE" ]; then
    rm -f "$ovr"
    return
  fi
  {
    printf '%s (safe to edit: remove the first line and it is left alone)\n' "$OVR_MARK"
    printf 'services:\n  kalmido:\n'
    if [ -n "$IMAGE" ]; then printf '    image: %s\n' "$IMAGE"; fi
    if [ "$PORT" != 3040 ]; then
      printf '    ports: !override\n      - "127.0.0.1:%s:3040"\n' "$PORT"
    fi
    if [ -n "$uidline" ]; then printf '%s\n' "$uidline"; fi
    if [ -n "$netmode" ]; then printf '    network_mode: bridge\n'; fi
  } > "$ovr"
  if [ "$PORT" != 3040 ] && [ "$COMPOSE" = standalone ]; then
    warn "docker-compose v1 may not understand '!override'. If the port is wrong, install the Compose v2 plugin."
  fi
}

compose_up() {
  UPFLAGS="--build"
  if [ -n "$IMAGE" ]; then
    step "Downloading the prebuilt image $IMAGE"
    if docker pull "$IMAGE"; then
      UPFLAGS=""
    else
      warn "The prebuilt image could not be downloaded. Building it locally instead (takes a minute)."
      IMAGE=""
      write_override
    fi
  fi
  step "Starting"
  log="$DIR/.install.log"
  rcf="$DIR/.install.rc"
  # shellcheck disable=SC2086
  (cd "$DIR" && { dc up -d $UPFLAGS 2>&1 && echo 0 > "$rcf" || echo $? > "$rcf"; } | tee "$log")
  rc=$(cat "$rcf"); rm -f "$rcf"
  if [ "$rc" != 0 ] && grep -qi "address pool" "$log"; then
    warn "Docker has no free address range for a new network. Retrying on Docker's default
bridge network (written to docker-compose.override.yml)."
    write_override bridge
    # shellcheck disable=SC2086
    (cd "$DIR" && { dc up -d $UPFLAGS 2>&1 && echo 0 > "$rcf" || echo $? > "$rcf"; } | tee "$log")
    rc=$(cat "$rcf"); rm -f "$rcf"
  fi
  if [ "$rc" != 0 ] && grep -qi "address already in use\|port is already allocated" "$log"; then
    die "Port $PORT is already in use. Pick another one, for example: KALMIDO_PORT=3050"
  fi
  [ "$rc" = 0 ] || die "docker compose up failed (see above, log in $log)."
  rm -f "$log"
}

wait_health() {
  step "Waiting for Kalmido to start"
  i=0
  while [ "$i" -lt 60 ]; do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then
      say "Healthy."
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  die "Kalmido did not answer on http://127.0.0.1:$PORT within 2 minutes.
Check the logs: cd \"$DIR\" && docker compose logs --tail 50"
}

# the one-time setup code the server printed (only while no account exists); empty otherwise
setup_code() {
  (cd "$DIR" && dc logs --no-color kalmido 2>/dev/null) | sed -n 's/.*Setup code: *\([a-z0-9-]*\).*/\1/p' | tail -n 1
}

detect_port() {
  # keep a port chosen on an earlier run unless KALMIDO_PORT is given
  if [ -n "${KALMIDO_PORT:-}" ]; then PORT="$KALMIDO_PORT"; return; fi
  PORT=3040
  ovr="$DIR/docker-compose.override.yml"
  if [ -f "$ovr" ] && head -n 1 "$ovr" | grep -q "^$OVR_MARK"; then
    p=$(sed -n 's/.*"127\.0\.0\.1:\([0-9][0-9]*\):3040".*/\1/p' "$ovr" | head -n 1)
    if [ -n "$p" ]; then PORT="$p"; fi
  fi
  return 0
}

main() {
  command -v curl >/dev/null 2>&1 || die "curl is required."
  [ -n "${HOME:-}" ] || die "HOME is not set."
  DIR="${KALMIDO_DIR:-$HOME/kalmido}"
  resolve_version
  detect_port
  case "$PORT" in
    ""|*[!0-9]*) die "KALMIDO_PORT must be a number." ;;
  esac

  printf '\n\033[1mKalmido installer\033[0m\n'
  if [ -n "${KALMIDO_VERSION:-}" ]; then
    say "Installs version $VERSION from GitHub into $DIR"
  elif [ "$VERSION" = main ]; then
    say "Installs the development version from GitHub (branch main, no release found) into $DIR"
  else
    say "Installs the latest release ($VERSION) from GitHub into $DIR"
  fi
  UPDATE=""
  if [ -f "$DIR/docker-compose.yml" ]; then
    UPDATE=1
    say "Existing installation found: updating (your .env and data/ are kept, the database is backed up first)."
  elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
    die "$DIR exists and is not an Kalmido installation. Choose another folder with KALMIDO_DIR."
  fi

  step "Checking Docker"
  check_docker

  if [ -n "$UPDATE" ]; then backup_db; fi
  fetch_code
  mkdir -p "$DIR/data" "$DIR/secret"
  chmod 700 "$DIR/secret" 2>/dev/null || true  # the server key (secret/kalmido.key), apart from data/ and its backups
  write_env
  choose_image
  write_override
  compose_up
  wait_health
  write_update_script

  url="http://localhost:$PORT"
  printf '\n\033[1;32mKalmido is running:\033[0m \033[1m%s\033[0m  (version %s)\n\n' "$url" "$REV"
  code=$(setup_code)
  if [ -n "$code" ]; then
    say "Open it now and create the first account (it becomes the admin) with this one-time setup code:"
    printf '\n    \033[1m%s\033[0m\n\n' "$code"
    say "(It is also in the log of the running container: cd \"$DIR\" && docker compose logs kalmido. Only the newest Setup code line counts; a restart prints a new one.)"
  else
    say "Open it now and log in."
  fi
  say ""
  say "Folder:     $DIR (settings in .env, your data in data/)"
  say "Server key: $DIR/secret/kalmido.key  (keep a copy somewhere safe, it is not part of the backups)"
  say "Backups:    daily into data/backups/ (Settings > Users > Whole server > Backups); copy them to another disk too"
  if [ -n "$IMAGE" ]; then say "Image:      $IMAGE (prebuilt)"; else say "Image:      kalmido:local (built on this computer)"; fi
  say "Update:     \"$DIR/update.sh\"  (backs up the database first; admins also see new versions in Settings > Help)"
  say "Virus scan: ClamAV checks every upload (about 1-1.5 GB RAM); small server: KALMIDO_CLAMD= in .env, see docs/SELF-HOSTING.md"  # 2.61.0
  say "Stop:       cd \"$DIR\" && docker compose down"
  say "Uninstall:  cd \"$DIR\" && docker compose down && docker image rm ${IMAGE:-kalmido:local}"
  say "            then delete the folder (this deletes your tasks)"
  say "Use it from other devices: put it behind a reverse proxy with HTTPS, see"
  say "            $GH#reverse-proxy (templates for Caddy, nginx, Traefik in examples/)"
}

main "$@"
