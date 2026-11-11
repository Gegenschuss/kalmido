#!/usr/bin/env python3
"""2.513.0 (#4354): publishing in two steps. Without a server (the script of the workflow runs here with stand-ins for gh and docker):
- release.yml builds the image :X.Y.Z and the GitHub release, never "latest"; it does not compare versions any more;
- promote.yml runs only on the tags latest-ok/X.Y.Z, moves :latest to the digest of the release and marks the release, in that order;
- a tag on another commit than vX.Y.Z, a broken digest or a release without a digest moves nothing; a tag below the current latest
  (a fix of an older line) moves nothing; the wait for the release follows the state of the release, not a fixed time;
- the job with write rights runs no third-party action; the version tags stay out of its pattern.
2.641.0 (#5011): latest moves only with the weekly release (weekly-release.yml, tests/p2641_c_weekly_test.py): release.yml makes
no release page, promote.yml only checks the tag and waits for the image :X.Y.Z, it moves nothing and writes nothing."""
# kalmido-suite: nodata
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import FAILS, OKS, check  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


rel = read(".github", "workflows", "release.yml")
pro = read(".github", "workflows", "promote.yml")

# ------------------------------------------------------------------ release.yml: never latest
code = "\n".join(line for line in rel.splitlines() if not line.lstrip().startswith("#"))
check("kalmido:latest" not in code, "release.yml does not touch the image :latest")
check("gh release" not in code and "--latest" not in code, "2.641.0 (#5011): release.yml makes no release page, so marks nothing as latest")
check("outputs.latest" not in code and "ls-remote" not in code, "no version comparison left in release.yml")
check("${{ steps.v.outputs.image }}:${{ steps.v.outputs.version }}" in code, "the image with its version stays")

# ------------------------------------------------------------------ promote.yml: the frame
check(re.search(r'^on:\n  push:\n    tags: \["latest-ok/\*\.\*\.\*"\]\n', pro, re.M) is not None, "promote.yml runs only on latest-ok/X.Y.Z")
check('tags: ["v*.*.*"]' in rel and "latest-ok" not in rel, "a latest-ok tag does not start release.yml")
check("uses:" not in pro, "the job with write rights runs no third-party action")
head = pro.split("\njobs:\n", 1)[0]
check(not re.search(r"^\s+\S+: write", head, re.M), "no write right for the whole workflow")
check(": write" not in pro, "2.641.0 (#5011): promote.yml writes nothing any more (latest moves with the weekly release)")
step = re.search(r"        run: \|\n((?:          .*\n|\n)+)", pro)
script = "\n".join(line[10:] for line in step.group(1).splitlines()) if step else ""
check(script.startswith("set -euo pipefail"), "the script stops at the first error")

# ------------------------------------------------------------------ the script with stand-ins
TMP = tempfile.mkdtemp(prefix="p2513p-")
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
LOG = os.path.join(TMP, "log")
DIG = "sha256:" + "a" * 64
SHA = "c" * 40
GH = r'''#!/bin/bash
echo "gh $*" >> "$T_LOG"
case "$1 $2" in
  "api repos/"*) echo "$T_TAG_SHA" ;;
esac
'''
# 2.641.0 (#5011): the image :X.Y.Z is asked for, not the release (there is none per tag any more)
DOCKER = r'''#!/bin/bash
echo "docker $*" >> "$T_LOG"
if [ "$1 $2 $3" = "buildx imagetools inspect" ]; then
  n=$(cat "$T_DIR/tries" 2>/dev/null || echo 0); echo $((n + 1)) > "$T_DIR/tries"
  if [ "$n" -lt "${T_MISSING:-0}" ]; then exit 1; fi
  printf '%s\n' "$T_DIGEST"
fi
'''
for name, body in (("gh", GH), ("docker", DOCKER),
                   ("sleep", '#!/bin/bash\necho "sleep $*" >> "$T_LOG"\n')):
    p = os.path.join(BIN, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)


def promote(ref="latest-ok/2.513.0", tag_sha=SHA, digest=DIG, cur="v2.512.0", missing=0):
    d = tempfile.mkdtemp(dir=TMP)
    if os.path.exists(LOG):
        os.remove(LOG)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"], GITHUB_REF_NAME=ref, GITHUB_SHA=SHA, GH_REPO="Gegen/Kalm", GITHUB_REPOSITORY="Gegen/Kalm", GH_TOKEN="t",
               GHCR_USER="u", T_LOG=LOG, T_DIR=d, T_TAG_SHA=tag_sha, T_DIGEST=digest, T_CUR=cur, T_MISSING=str(missing))
    r = subprocess.run(["bash", "-c", script], cwd=d, env=env, capture_output=True, text=True, timeout=60)
    log = ""
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            log = f.read()
    return r.returncode, log, r.stdout + r.stderr


def moved(log):
    return "imagetools create" in log or "release edit" in log or "docker login" in log


# 2.641.0 (#5011): the checks stay, the moves went to weekly-release.yml
rc, log, out = promote()
check(rc == 0 and not moved(log), f"the normal case passes and moves nothing ({rc} {out[:200]} {log})")
# 2.995.0 (#5686): the image name comes from the repository in lower case (GitHub move #4007), not from a fixed name
check("imagetools inspect ghcr.io/gegen/kalm:2.513.0" in log, f"it asks for the image of the version, named after the repository: {log}")
check("ready for the weekly release" in out and DIG in out, f"it says the version is ready for the weekly release: {out[:300]}")
rc, log, _ = promote(ref="latest-ok/2.166.5", cur="v2.223.1")
check(rc == 0 and not moved(log), f"a fix of an older line: checked, nothing moves ({rc} {log})")

for what, kw in (("another commit than the version tag", dict(tag_sha="d" * 40)), ("a broken digest", dict(digest="sha256:xyz")),
                 ("an empty digest", dict(digest="")), ("a tag without a version", dict(ref="latest-ok/nope.1.2"))):
    rc, log, _ = promote(**kw)
    check(rc == 1 and not moved(log), f"{what}: stops and moves nothing ({rc} {log})")

rc, log, _ = promote(missing=2)
check(rc == 0 and log.count("sleep 30") == 2, f"the image not there yet: waits for it, then goes on ({rc} {log})")
rc, log, out = promote(missing=1000)
check(rc == 1 and not moved(log) and "image :2.513.0" in out, f"the image never comes: stops with a message ({rc} {out[:200]})")

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2513_promote: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
