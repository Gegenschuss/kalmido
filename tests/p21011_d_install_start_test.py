#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.1011.0 D (#5713): the nightly CI job install-upgrade, as far as it runs without network and server:
 - tools/install_upgrade_check.py pick_start: the start is the live version (newest tag latest-ok/X.Y.Z below the candidate),
   not the latest release (2.502.0 for 490 versions); with a release page it is installed as a release, without one from the tag
 - --prev: vX.Y.Z / X.Y.Z = a release, latest-ok/X.Y.Z = the tag; anything else is refused
 - .dockerignore: the install folder is the build context of docker-compose.yml (build: .) - pgdata/ (postgres, 0700) made
   docker compose build stop with "permission denied"; data/, secret/, .env never go to the build either, and the Dockerfile
   copies none of them"""
import os
import re
import sys

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import install_upgrade_check as iuc  # noqa: E402
from kt import FAILS, OKS, check  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


# ---- the start: the live version
REFS = ["v2.502.0", "v2.940.0", "v2.941.0", "v2.996.0", "latest-ok/2.910.0", "latest-ok/2.941.0", "latest-ok/2.99.0",
        "latest-ok/2.998.0", "latest-ok/x", "main"]
asked = []


def none_released(t):
    asked.append(t)
    return False


check(iuc.pick_start("2.998.0", REFS, latest="v2.502.0", released=none_released) == ("latest-ok/2.941.0", "tag"),
      "pick_start: the newest live version below the candidate (2.941 above 2.99, numbers not text), not the release 2.502.0; "
      "without a release page: from its tag")
check(asked == ["v2.941.0"], f"pick_start: asks GitHub only for the release of the live version ({asked})")
check(iuc.pick_start("2.998.0", REFS, latest="v2.502.0") == ("v2.941.0", "release"),
      "pick_start: a live version with a release page is installed as a self-hoster does (its release)")
check(iuc.pick_start("2.998.0", REFS, latest="v2.996.0", released=lambda t: t == "v2.996.0") == ("v2.996.0", "release"),
      "pick_start: a latest release above the live version but below the candidate wins")
check(iuc.pick_start("2.998.0", REFS, latest="v2.999.0", released=lambda t: False) == ("latest-ok/2.941.0", "tag"),
      "pick_start: a latest release above the candidate is not taken")
check(iuc.pick_start("2.941.0", REFS, released=lambda t: False) == ("latest-ok/2.910.0", "tag"),
      "pick_start: never the candidate itself")
check(iuc.pick_start("2.997.0", ["v2.995.0", "v2.996.0", "main"], latest="v2.502.0") == ("v2.502.0", "release"),
      "pick_start: no latest-ok tag -> the old search over the releases (pick)")
check(iuc.pick_start("main", REFS) is None and iuc.pick_start("2.0.0", REFS) is None, "pick_start: no version / nothing older -> None")
check(iuc.live_v("latest-ok/2.941.0") == (2, 941, 0) and iuc.live_v("v2.941.0") is None and iuc.live_v("latest-ok/x") is None,
      "live_v reads only latest-ok/X.Y.Z")

# ---- --prev
check(iuc.start_of("2.941.0") == ("v2.941.0", "release") and iuc.start_of("v2.941.0") == ("v2.941.0", "release"),
      "--prev X.Y.Z / vX.Y.Z = a release")
check(iuc.start_of("latest-ok/2.941.0") == ("latest-ok/2.941.0", "tag") and iuc.start_of("main") is None,
      "--prev latest-ok/X.Y.Z = the tag, a branch is refused")

# ---- run: the tag way installs with the tag's own install.sh and names the version without prefix
src = read("tools", "install_upgrade_check.py")
check('"git", "-C", ROOT, "show", f"{prev}:install.sh"' in src and 'if how == "release":' in src,
      "run: a release fetches install.sh of the release, a tag takes install.sh of the tag from the checkout")
check("pv = \".\".join(map(str, live_v(prev) or vt(prev)))" in src, "run: UPG_VERSION is X.Y.Z for both ways")
check('"latest-ok/" + E["version"]' in read("tests", "install_upgrade_verify.py"),
      "install_upgrade_verify: .kalmido-version.prev may be the tag latest-ok/X.Y.Z")

# ---- .dockerignore: the install folder as build context
ign = [ln.strip() for ln in read(".dockerignore").splitlines() if ln.strip() and not ln.startswith("#")]
for name in ("pgdata", "data", "secret", ".env"):
    check(name in ign, f".dockerignore: {name} stays out of the build context")
check(not any(ln.startswith("!") or ln in ("*", "**") for ln in ign), ".dockerignore: no re-include, nothing global")
copies = re.findall(r"^COPY (?!--from)(.+?) \S+$", read("Dockerfile"), re.M)
srcs = [s.strip("/") for c in copies for s in c.split()]
check(srcs and not [s for s in srcs if s.split("/")[0].rstrip("[]") in ign],
      f"Dockerfile copies nothing .dockerignore leaves out ({srcs})")
check("build: ." in read("docker-compose.yml"), "docker-compose.yml builds from its own folder (the install folder)")

print(f"p21011_d_install_start: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
