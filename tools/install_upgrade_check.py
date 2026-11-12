#!/usr/bin/env python3
"""2.589.0 (#4359, audit #2480 finding 6): the way of a self-hoster, end to end - the nightly CI job "install-upgrade" (ci.yml).

  1. the version before the candidate (VERSION) is installed with ITS install.sh from the GitHub release (the same file
     kalmido.com/install.sh forwards to; prebuilt image pinned to the release digest, like on a real machine).
     2.1011.0 (#5713): that version is the live one - the newest tag latest-ok/X.Y.Z below VERSION (pick_start); without a
     release page its install.sh comes from the tag and installs KALMIDO_VERSION=latest-ok/X.Y.Z (cloned, built locally)
  2. tests/upgrade_seed.py fills it (with the one-time setup code from the server log, as the setup page asks for it) and
     writes <version>.sql.gz + <version>.json: the old database and what the old release showed
  3. the update.sh that installer wrote updates it to the candidate: KALMIDO_VERSION=<commit> and KALMIDO_INSTALLER_URL = the
     candidate's install.sh (a released installation fetches the newest release's installer; the candidate has no release yet)
  4. tests/install_upgrade_verify.py: candidate version, sign-in, the data as before, a write, the database copy of update.sh

  python3 tools/install_upgrade_check.py prev                  the start before the candidate: "<ref> (release|tag)" (stdout)
  python3 tools/install_upgrade_check.py setup-code CONTAINER  the newest one-time setup code in the container's log
  python3 tools/install_upgrade_check.py run [--prev TAG] [--ref REF] [--dir DIR] [--out DIR] [--port N]
                                                               steps 1-4 (needs docker + compose, git, curl, network to GitHub)

--prev = that start instead of the search (vX.Y.Z = a release, latest-ok/X.Y.Z = the tag); --ref = what update.sh updates to (default: the commit of HEAD; it must be on GitHub,
install.sh fetches it from there); --dir = the install folder (default <tmp>/kalmido-install, must not exist yet); --port (3040);
--out = the folder for <version>.sql.gz + .json (default <tmp>/upgrade-fixture). The dump is the quarterly fixture of
tests/fixtures/upgrade/ (README there). The start is looked up at run time: once a newer version is live, the check
starts from it by itself. Python standard library only."""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = "https://github.com/Gegenschuss/kalmido"
CODE_RE = re.compile(r"Setup code: *([a-z0-9-]+)")  # the same pattern as setup_code() of install.sh


def vt(tag):
    """'v2.588.0' / '2.588.0' -> (2, 588, 0); None for anything else (branches, pre-releases)."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (tag or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def pick(version, tags, latest=None, released=lambda t: True, limit=10):
    """The release to start from: the latest release (what update.sh of a self-hoster fetches) when it is older than the
    candidate, else the newest tag below the candidate that has a GitHub release (a tag whose CI was red has none,
    tools/ci_gate.py); at most `limit` tags are asked. None: nothing older."""
    cur = vt(version)
    if cur is None:
        return None
    if vt(latest) and vt(latest) < cur:
        return "v" + ".".join(map(str, vt(latest)))
    older = sorted({t for t in tags if vt(t) and vt(t) < cur}, key=vt, reverse=True)
    for t in older[:limit]:
        if released(t):
            return t
    return None


LIVE_PREFIX = "latest-ok/"  # 2.1011.0 (#5713): the tag the live train pushes after the device test (kalmido-livezug.py latest)


def live_v(ref):
    """'latest-ok/2.941.0' -> (2, 941, 0); None for anything else."""
    return vt(ref[len(LIVE_PREFIX):]) if (ref or "").startswith(LIVE_PREFIX) else None


def pick_start(version, refs, latest=None, released=lambda t: True, limit=10):
    """2.1011.0 (#5713): the version to start from = what runs live: the newest latest-ok/X.Y.Z below the candidate (the live
    train sets it after the device test; one of them becomes the weekly release, tools/weekly_release.py). Since the train
    there were no releases for 490 versions, so the latest release (2.502.0) missed every trap of the jumps live makes.
    -> ("vX.Y.Z", "release") when that version has a GitHub release (install.sh of the release, prebuilt image pinned to its
    digest - the way of a self-hoster), ("latest-ok/X.Y.Z", "tag") when not (install.sh of that tag, the code cloned from the
    tag, built locally; a version without a release page has no checksum list for install.sh). A latest release above the
    live version (never normally) wins. No latest-ok tag: the old search of pick() over the release tags. None: nothing older."""
    cur = vt(version)
    if cur is None:
        return None
    live = sorted({live_v(r) for r in refs if live_v(r) and live_v(r) < cur}, reverse=True)
    lat = vt(latest)
    if live and not (lat and live[0] < lat < cur):
        v = "v" + ".".join(map(str, live[0]))
        return (v, "release") if released(v) else (LIVE_PREFIX + v[1:], "tag")
    t = pick(version, [r for r in refs if vt(r)], latest, released, limit)
    return (t, "release") if t else None


def _head(url):
    """The final address of a HEAD request (redirects followed), None on any error."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:  # noqa: S310 - fixed https address
            return r.geturl() if r.status == 200 else None
    except Exception:  # noqa: BLE001 - no answer = not there
        return None


def latest_release():
    url = _head(GH + "/releases/latest") or ""
    return url.rsplit("/releases/tag/", 1)[1] if "/releases/tag/" in url else None


def has_release(tag):
    return _head(f"{GH}/releases/download/{tag}/install.sh") is not None


def version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def prev_tag():
    """(ref, how) of pick_start() over the tags of the checkout (v* and latest-ok/*), None when nothing is older."""
    tags = subprocess.run(["git", "-C", ROOT, "tag", "-l", "v*", LIVE_PREFIX + "*"], capture_output=True, text=True,
                          check=True).stdout.split()
    return pick_start(version(), tags, latest_release(), has_release)


def start_of(ref):
    """--prev: 'v2.941.0' / '2.941.0' = a release, 'latest-ok/2.941.0' = the tag without release page; None for anything else."""
    if live_v(ref):
        return (ref, "tag")
    return ("v" + ".".join(map(str, vt(ref))), "release") if vt(ref) else None


def setup_code(log):
    """The newest code of the log text ('' when none): only the newest line counts, a restart prints a new one."""
    codes = CODE_RE.findall(log or "")
    return codes[-1] if codes else ""


def container_log(ct):
    r = subprocess.run(["docker", "logs", ct], capture_output=True, text=True)
    return r.stdout + r.stderr


def step(text):
    print(f"\n==> install-upgrade: {text}", flush=True)


def sh(args, **kw):
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, check=True, **kw)


def compose_id(d, service):
    r = subprocess.run(["docker", "compose", "ps", "-q", service], cwd=d, capture_output=True, text=True, check=True)
    ids = r.stdout.split()
    if not ids:
        sys.exit(f"install-upgrade: no running container of the service {service} in {d}")
    return ids[0]


def run(argv):
    tmp = tempfile.gettempdir()
    ap = argparse.ArgumentParser(prog="install_upgrade_check.py run")
    ap.add_argument("--prev")
    ap.add_argument("--ref")
    ap.add_argument("--dir", default=os.path.join(tmp, "kalmido-install"))
    ap.add_argument("--out", default=os.path.join(tmp, "upgrade-fixture"))
    ap.add_argument("--port", type=int, default=3040)
    a = ap.parse_args(argv)
    d, out, port = os.path.abspath(a.dir), os.path.abspath(a.out), str(a.port)
    ref = a.ref or subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    cand = version()
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
        sys.exit(f"install-upgrade: --ref must be a commit, tag or branch ({ref!r})")
    if os.path.exists(d):
        sys.exit(f"install-upgrade: {d} exists already - the check starts from an empty folder")
    start = start_of(a.prev) if a.prev else prev_tag()
    if not start:
        sys.exit(f"install-upgrade: no live version or release before {cand} found")
    prev, how = start
    pv = ".".join(map(str, live_v(prev) or vt(prev)))
    print(f"install-upgrade: {prev} (install.sh of that {how}) -> {cand} ({ref}) in {d}, port {port}", flush=True)
    work = tempfile.mkdtemp(prefix="iuc-")
    base = dict(os.environ, KALMIDO_DIR=d, KALMIDO_PORT=port)
    for k in ("KALMIDO_VERSION", "KALMIDO_BUILD", "KALMIDO_URL", "KALMIDO_IMAGE_REPO", "KALMIDO_INSTALLER_URL"):
        base.pop(k, None)

    step(f"1. install {prev} with its own install.sh")
    inst = os.path.join(work, "install-prev.sh")
    if how == "release":
        sh(["curl", "-fsSL", "--retry", "3", "-o", inst, f"{GH}/releases/download/{prev}/install.sh"])
    else:  # 2.1011.0 (#5713): the tag's own install.sh from the checkout (fetch-depth 0); it clones the tag and builds it
        with open(inst, "wb") as f:
            f.write(subprocess.run(["git", "-C", ROOT, "show", f"{prev}:install.sh"], capture_output=True, check=True).stdout)
    sh(["sh", inst], env=dict(base, KALMIDO_VERSION=prev))
    app = compose_id(d, "kalmido")
    code = setup_code(container_log(app))
    print(f"install-upgrade: setup code from the log: {'found' if code else 'none (the setup is tried without)'}", flush=True)

    step(f"2. fill {prev} with tests/upgrade_seed.py, dump into {out}")
    data = os.path.join(work, "data")
    os.makedirs(data)
    with open(os.path.join(data, ".kalmido-db"), "w", encoding="utf-8") as f:
        f.write(f"{compose_id(d, 'db')} kalmido\n")  # tests/dbx.py: "<db container> <database>" (docker-compose.yml: POSTGRES_DB)
    tenv = dict(os.environ, KALMIDO_TEST_PORT=port, KALMIDO_TEST_CONTAINER=app, P2192C_DUMP_SHOTS=out, UPG_VERSION=pv,
                UPG_SETUP_CODE=code)
    sh([sys.executable, "upgrade_seed.py", data], cwd=os.path.join(ROOT, "tests"), env=tenv)

    step(f"3. update to {ref} with the update.sh of the installation")
    sh([os.path.join(d, "update.sh")], env=dict(base, KALMIDO_VERSION=ref, KALMIDO_INSTALLER_URL="file://" + os.path.join(ROOT, "install.sh")))
    app = compose_id(d, "kalmido")  # compose made a new container

    step("4. sign-in, data, version (tests/install_upgrade_verify.py)")
    r = subprocess.run([sys.executable, "install_upgrade_verify.py", data, os.path.join(out, pv + ".json"), cand, d, ref],
                       cwd=os.path.join(ROOT, "tests"), env=dict(tenv, KALMIDO_TEST_CONTAINER=app))
    return r.returncode


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "prev":
        t = prev_tag()
        if not t:
            print(f"no live version or release before {version()}", file=sys.stderr)
            return 1
        print(f"{t[0]} ({t[1]})")
        return 0
    if cmd == "setup-code" and len(argv) == 3:
        c = setup_code(container_log(argv[2]))
        print(c)
        return 0 if c else 1
    if cmd == "run":
        return run(argv[2:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
