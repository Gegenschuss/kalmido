#!/usr/bin/env python3
"""2.513.0 (#4354): publishing in two steps. Without a server (the script of the workflow runs here with stand-ins for gh and docker):
- release.yml builds the image :X.Y.Z and the GitHub release, never "latest"; it does not compare versions any more;
- promote.yml runs only on the tags latest-ok/X.Y.Z, moves :latest to the digest of the release and marks the release, in that order;
- a tag on another commit than vX.Y.Z, a broken digest or a release without a digest moves nothing; a tag below the current latest
  (a fix of an older line) moves nothing; the wait for the release follows the state of the release, not a fixed time;
- the job with write rights runs no third-party action; the version tags stay out of its pattern."""
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
check("--latest=false" in code and code.count("--latest") == 1, "gh release create marks nothing as latest")
check("outputs.latest" not in code and "ls-remote" not in code, "no version comparison left in release.yml")
check("ghcr.io/gegenschuss/kalmido:${{ steps.v.outputs.version }}" in code, "the image with its version stays")

# ------------------------------------------------------------------ promote.yml: the frame
check(re.search(r'^on:\n  push:\n    tags: \["latest-ok/\*\.\*\.\*"\]\n', pro, re.M) is not None, "promote.yml runs only on latest-ok/X.Y.Z")
check('tags: ["v*.*.*"]' in rel and "latest-ok" not in rel, "a latest-ok tag does not start release.yml")
check("uses:" not in pro, "the job with write rights runs no third-party action")
head = pro.split("\njobs:\n", 1)[0]
check(not re.search(r"^\s+\S+: write", head, re.M), "no write right for the whole workflow")
check("contents: write" in pro and "packages: write" in pro, "the job has the two rights it needs")
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
  "release download")
    n=$(cat "$T_DIR/tries" 2>/dev/null || echo 0); echo $((n + 1)) > "$T_DIR/tries"
    if [ "$n" -lt "${T_MISSING:-0}" ]; then exit 1; fi
    printf '%s\n' "$T_DIGEST" > image-digest.txt ;;
  "release view") [ -n "${T_CUR:-}" ] || exit 1; echo "$T_CUR" ;;
  "release edit") [ -z "${T_EDIT_FAILS:-}" ] || exit 1 ;;
esac
'''
for name, body in (("gh", GH), ("docker", '#!/bin/bash\necho "docker $*" >> "$T_LOG"\n'),
                   ("sleep", '#!/bin/bash\necho "sleep $*" >> "$T_LOG"\n')):
    p = os.path.join(BIN, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)


def promote(ref="latest-ok/2.513.0", tag_sha=SHA, digest=DIG, cur="v2.512.0", missing=0, edit_fails=""):
    d = tempfile.mkdtemp(dir=TMP)
    if os.path.exists(LOG):
        os.remove(LOG)
    env = dict(os.environ, PATH=BIN + os.pathsep + os.environ["PATH"], GITHUB_REF_NAME=ref, GITHUB_SHA=SHA, GH_REPO="o/r", GH_TOKEN="t",
               GHCR_USER="u", T_LOG=LOG, T_DIR=d, T_TAG_SHA=tag_sha, T_DIGEST=digest, T_CUR=cur, T_MISSING=str(missing), T_EDIT_FAILS=edit_fails)
    r = subprocess.run(["bash", "-c", script], cwd=d, env=env, capture_output=True, text=True, timeout=60)
    log = ""
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            log = f.read()
    return r.returncode, log, r.stdout + r.stderr


def moved(log):
    return "imagetools" in log or "release edit" in log


rc, log, out = promote()
check(rc == 0, f"the normal case passes ({rc} {out[:200]})")
check(f"imagetools create -t ghcr.io/gegenschuss/kalmido:latest ghcr.io/gegenschuss/kalmido@{DIG}" in log, f":latest goes to the digest of the release: {log}")
check("gh release edit v2.513.0 --latest" in log, "the release becomes latest")
check(log.index("imagetools") < log.index("release edit"), "first the image, then the mark the installers read")
check("--password-stdin" in log, "the token does not stand on the command line")
rc, log, _ = promote(cur="")
check(rc == 0 and moved(log), "no latest release yet: this one becomes it")
rc, log, _ = promote(cur="v2.513.0")
check(rc == 0 and moved(log), "already latest: the same again does no harm (the image may have been missing)")
rc, log, _ = promote(ref="latest-ok/2.10.0", cur="v2.9.0")
check(rc == 0 and moved(log), "version order, not text order (2.10.0 above 2.9.0)")

for what, kw in (("a fix of an older line", dict(ref="latest-ok/2.166.5", cur="v2.223.1")),
                 ("version order", dict(ref="latest-ok/2.9.1", cur="v2.10.0"))):
    rc, log, _ = promote(**kw)
    check(rc == 0 and not moved(log), f"{what}: below the current latest moves nothing ({rc} {log})")

for what, kw in (("another commit than the version tag", dict(tag_sha="d" * 40)), ("a broken digest", dict(digest="sha256:xyz")),
                 ("an empty digest", dict(digest="")), ("a tag without a version", dict(ref="latest-ok/nope.1.2"))):
    rc, log, _ = promote(**kw)
    check(rc == 1 and not moved(log), f"{what}: stops and moves nothing ({rc} {log})")

rc, log, _ = promote(missing=2)
check(rc == 0 and log.count("sleep 30") == 2 and moved(log), f"the release not there yet: waits for it, then goes on ({rc} {log})")
rc, log, out = promote(missing=1000)
check(rc == 1 and not moved(log) and "image-digest.txt" in out, f"the release never comes: stops with a message ({rc} {out[:200]})")
rc, _, _ = promote(edit_fails="1")
check(rc == 1, "a failed mark fails the workflow, so it shows red")

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2513_promote: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
