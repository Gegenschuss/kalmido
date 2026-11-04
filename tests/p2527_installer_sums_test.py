#!/usr/bin/env python3
"""2.527.0 (#4312): the installers say honestly what they check, and a failed fetch of the checksum list of a release stops.
install.sh runs for real (functions only, its last line left out) with a stub for curl; install.ps1 (no PowerShell in the test
environment) is checked as text.
- release 2.277 and newer: SHA256SUMS fetched -> checked; no network, a server error, a 404 or an empty file -> a clear stop
- release before 2.277: only a 404 goes on unchecked (with a note); any other failure stops as well
- branches: no fetch at all
- install.ps1: the Compose 2.20 floor of install.sh, a relative KALMIDO_DIR becomes a full path
- the header of both installers no longer promises a source check on the git way, and the git way says so"""
# kalmido-suite: nodata
import os
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kt import FAILS, OKS, check  # noqa: E402

with open(os.path.join(ROOT, "install.sh"), encoding="utf-8") as f:
    SH = f.read()
with open(os.path.join(ROOT, "install.ps1"), encoding="utf-8") as f:
    PS = f.read()
assert SH.rstrip().endswith('main "$@"')
TMP = tempfile.mkdtemp(prefix="p2527-")
LIB = os.path.join(TMP, "lib.sh")
with open(LIB, "w", encoding="utf-8") as f:
    f.write(SH.rstrip()[:-len('main "$@"')])
STUB = os.path.join(TMP, "bin")
os.makedirs(STUB)
CALLS = os.path.join(TMP, "calls")
# curl stub: writes SUMS_BODY into the -o file, prints CURL_CODE (as -w '%{http_code}' would) and ends with CURL_RC
with open(os.path.join(STUB, "curl"), "w", encoding="utf-8") as f:
    f.write('#!/bin/sh\necho "curl $*" >> "%s"\nout=""; prev=""\n'
            'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
            '[ -n "$out" ] && printf "%%s" "${SUMS_BODY:-}" > "$out"\n'
            'printf "%%s" "${CURL_CODE:-200}"\nexit "${CURL_RC:-0}"\n' % CALLS)
os.chmod(os.path.join(STUB, "curl"), 0o755 | stat.S_IXUSR)


def assets(version, code="200", body="", rc="0"):
    if os.path.exists(CALLS):
        os.remove(CALLS)
    e = {k: v for k, v in os.environ.items() if not k.startswith(("KALMIDO_", "SSH_"))}
    e.update(PATH=STUB + os.pathsep + e["PATH"], CURL_CODE=code, SUMS_BODY=body, CURL_RC=rc)
    r = subprocess.run(["sh", "-c", '. "%s"\nGH=https://github.invalid/x/y\nVERSION=%s\nrelease_assets\n'
                        'if [ -n "$SUMS" ]; then echo SUMS=set; else echo SUMS=none; fi' % (LIB, version)],
                       env=e, capture_output=True, text=True, timeout=60)
    called = open(CALLS, encoding="utf-8").read() if os.path.exists(CALLS) else ""
    return r.returncode, r.stdout + r.stderr, called


SUMS = "abc  kalmido-2.527.0.tar.gz\ndef  image-digest.txt\n"
rc, out, _ = assets("v2.527.0", "200", SUMS)
check(rc == 0 and "SUMS=set" in out, f"#4312: a release with SHA256SUMS is checked ({rc} {out})")
rc, out, _ = assets("v2.527.0", "000", "", "6")
check(rc != 0 and "Could not fetch the checksum list" in out and "SUMS=" not in out,
      f"#4312: no network for a new release stops instead of going on unchecked ({rc} {out})")
rc, out, _ = assets("v2.527.0", "502")
check(rc != 0 and "Could not fetch the checksum list" in out, f"#4312: a server error stops ({rc} {out})")
rc, out, _ = assets("v2.527.0", "404")
check(rc != 0 and "Could not fetch the checksum list" in out, f"#4312: a release from 2.277 on without a list stops ({rc} {out})")
rc, out, _ = assets("v2.527.0", "200", "")
check(rc != 0 and "Could not fetch the checksum list" in out, f"#4312: an empty list stops ({rc} {out})")
rc, out, _ = assets("v2.200.0", "404")
check(rc == 0 and "SUMS=none" in out and "older release" in out, f"#4312: a release before 2.277 without a list goes on with a note ({rc} {out})")
rc, out, _ = assets("v1.9.0", "404")
check(rc == 0 and "SUMS=none" in out, f"#4312: version 1.x counts as before 2.277 ({rc} {out})")
rc, out, _ = assets("v2.200.0", "000", "", "7")
check(rc != 0 and "Could not fetch the checksum list" in out, f"#4312: an old release with no network stops too ({rc} {out})")
check("--max-time 60 -o \"$TMPD/SHA256SUMS\"" in SH and "-TimeoutSec 60 -Uri \"$GH/releases/download/$Version/SHA256SUMS\"" in PS,
      "#4312: the fetch of the checksum list cannot hang for ever")
rc, out, called = assets("main", "000", "", "6")
check(rc == 0 and "SUMS=none" in out and "curl" not in called, f"#4312: a branch fetches no list ({rc} {out})")

# honest texts
for name, src in (("install.sh", SH), ("install.ps1", PS)):
    head = src[:3000]
    check("Release versions are checked against the release's SHA256SUMS (source archive" not in head,
          f"#4312: {name} no longer promises a source check on every way")
    check("with git the tag is fetched from GitHub over HTTPS, without that check" in head,
          f"#4312: {name} names the git way as not checked against SHA256SUMS")
    check("not compared with SHA256SUMS; only the prebuilt image, when used, is pinned to the release digest" in src, f"#4312: {name} says so on the git way")
check("$sumsCode -eq 404 -and $beforeSums" in PS and "Could not fetch the checksum list of release $Version" in PS
      and "catch { }\n    finally" not in PS.split("SHA256SUMS\" -OutFile $sf")[1][:400],
      "#4312: install.ps1 goes on unchecked only on a 404 of a release before 2.277, else stops")
check("Kalmido needs Compose 2.20 or newer" in PS and "compose version --short" in PS and "$cv -notmatch" in PS, "#4312: install.ps1 has the Compose 2.20 floor of install.sh")
check("[IO.Path]::GetFullPath([IO.Path]::Combine((Get-Location).ProviderPath, $Dir))" in PS and "$env:USERPROFILE + $Dir.Substring(1)" in PS and "KALMIDO_DIR is not a usable folder path" in PS, "#4312: install.ps1 turns a relative KALMIDO_DIR into a full path")

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2527_installer_sums: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
