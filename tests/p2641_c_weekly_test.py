#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.641.0 C (#5011): one GitHub release per ISO week, old releases and images thinned out. Without a server:
- tools/weekly_release.py pick: the newest latest-ok version up to the end of the week, never below the current latest; the
  text holds all CHANGELOG sections since the last weekly release, their "Action needed" sections collected on top under ONE
  level-2 heading (the update hint reads only up to the next one), the change list below it
- tools/weekly_release.py prune: the newest latest-ok version of each ISO week stays, the current latest, everything younger than
  14 days, the newest release of each week before the first latest-ok tag; images only when all tags are X.Y.Z (never :latest,
  never untagged parts); no latest-ok tag or no latest = refusal; the plan holds only release / package version paths, never a
  git ref or tag (safe_path and the delete loop of the workflow)
- the workflows: release.yml makes no release page any more, weekly-release.yml publishes on vX.Y.Z (--verify-tag, latest),
  moves :latest before the mark, calls prune-releases.yml as a dry run unless KALMIDO_PRUNE_APPLY=1; prune-releases.yml is a dry
  run by default; rights per job; inputs reach no shell line as an expression
- install.sh with KALMIDO_VERSION of a version in between (no release page) stops cleanly: 'Nothing was changed', no folder"""
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile

N = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(N)
sys.path.insert(0, N)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from kt import FAILS, OKS, check  # noqa: E402
import weekly_release as wr  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def d(s):
    return wr.when(s)


# ------------------------------------------------------------------ pick
TAGS = wr.read_tags("latest-ok/2.630.0 2026-10-28T10:00:00+01:00\nlatest-ok/2.635.0 2026-11-03T09:00:00+01:00\n"
                    "latest-ok/2.639.0 2026-11-07T15:00:00+01:00\nlatest-ok/2.166.5 2026-11-06T12:00:00+01:00\n"
                    "v2.641.0 2026-11-07\nlatest-ok/nope 2026-11-07\n")
check(sorted(TAGS) == [(2, 166, 5), (2, 630, 0), (2, 635, 0), (2, 639, 0)], f"only latest-ok/X.Y.Z lines count {sorted(TAGS)}")
check(wr.pick(TAGS, "v2.630.0", d("2026-11-08")) == (2, 639, 0), "Sunday: the newest latest-ok version of the week")
check(wr.pick(TAGS, "v2.630.0", d("2026-11-01")) == (2, 630, 0), "a run in an earlier week does not see later tags")
check(wr.pick(TAGS, "v2.639.0", d("2026-11-08")) == (2, 639, 0), "the same again (a re-run): the same version, no harm")
check(wr.pick(TAGS, "v2.700.0", d("2026-11-08")) is None, "never below the current latest (a fix of an older line stays below)")
check(wr.pick(TAGS, "", d("2026-11-08")) == (2, 639, 0), "no latest release yet: the newest one")
check(wr.pick({}, "v2.630.0", d("2026-11-08")) is None, "no latest-ok tag: nothing")
check(wr.week_end(d("2026-11-08")) == d("2026-11-09T00:00:00Z") and wr.week_end(d("2026-11-02")) == d("2026-11-09T00:00:00Z"),
      "the ISO week runs Monday to Sunday")

CL = """# Changelog

## Older versions

- [2.500-2.599](docs/changelog/2.500-2.599.md)

## [2.639.0] - 2026-11-07

Package 2.385 (Film: document samples).
### Added
- Three film samples (#2293).

## [2.636.0] - 2026-11-05

Package 2.600 (Mail).
### Action needed
- Set `KALMIDO_MAIL_X=1` in your .env
#### Docker
- pull again
### Fixed
- A mail fix (#1).

Package 2.601 (Other).
### Changed
- Other change (#2).

## [2.635.0] - 2026-11-03

### Action needed (self-hosting)
- Run update.sh twice

Package 2.599 (Older).
### Added
- Older thing (#3).

## [2.630.0] - 2026-10-28

### Action needed
- from the week before
"""
secs = wr.sections(CL)
check(sorted(secs) == [(2, 630, 0), (2, 635, 0), (2, 636, 0), (2, 639, 0)], f"CHANGELOG sections by version {sorted(secs)}")
text, vs = wr.weekly_notes(secs, "v2.630.0", (2, 639, 0))
check(vs == [(2, 635, 0), (2, 636, 0), (2, 639, 0)], f"the versions since the last weekly release {vs}")
check(text.startswith("## Action needed\n") and text.count("Action needed") == 1, f"ONE collected section on top {text[:300]!r}")
act = text.split("## Changes", 1)[0]
check("KALMIDO_MAIL_X=1" in act and "update.sh twice" in act and "**2.636.0**" in act and "**2.635.0**" in act,
      f"the action of every version of the week, also of an older one {act!r}")
check("#### Docker" in act and "pull again" in act, "the sub-heading of a section stays inside it")
check("from the week before" not in text and "Other change" not in act and "Older thing" not in act,
      "nothing of the week before, a section ends at the next package")
check(not re.search(r"^#{1,2} ", act.split("\n", 1)[1], re.M), "no level-1/2 heading inside the section (the update hint would end there)")
rest = text.split("## Changes", 1)[1] if "## Changes" in text else ""
check("Three film samples" in rest and "A mail fix" in rest and "Older thing" in rest and "Other change" in rest,
      "all changes of the week below")
check("3 versions, 2.635.0 to 2.639.0" in rest and rest.rstrip().endswith("CHANGELOG.md)"), "the text names the versions, link at the end")
text, vs = wr.weekly_notes({(2, 639, 0): "### Added\n- One (#1).\n"}, "v2.636.0", (2, 639, 0))
check(vs == [(2, 639, 0)] and "Action needed" not in text and "One" in text, "without an action: no empty section")
# the update check of the servers reads the collected section (same rules as kalmido/core/instance.py update_action)
big = wr.weekly_notes({(9, 0, i): f"Package 9.{i} (P{i}).\n### Fixed\n" + "- a long fixed thing to fill the page, word word word\n" * 300
                       for i in range(1, 9)}, "v9.0.0", (9, 0, 8))[0]
check(len(big) < 125000 and "Full list of changes" in big and big.count("a long fixed thing") > 10,
      f"a big week stays below GitHub's limit and keeps entries instead of only the link ({len(big)})")

# ------------------------------------------------------------------ prune
NOW = d("2026-11-08T21:00:00Z")
REL = [{"id": 10 + i, "tag_name": f"v2.{v}.0", "created_at": c}
       for i, (v, c) in enumerate([(630, "2026-10-28T10:00:00Z"), (631, "2026-10-29T10:00:00Z"), (635, "2026-11-03T09:00:00Z"),
                                   (639, "2026-11-07T15:00:00Z"), (500, "2026-09-01T10:00:00Z"), (501, "2026-09-02T10:00:00Z"),
                                   (490, "2026-08-20T10:00:00Z"), (629, "2026-10-20T10:00:00Z")])]
REL += [{"id": 90, "tag_name": "nightly", "created_at": "2026-01-01T00:00:00Z"},
        {"id": 91, "tag_name": "v2.400.0", "created_at": "2026-06-01T00:00:00Z", "draft": True}]
TG = wr.read_tags("latest-ok/2.629.0 2026-10-20T10:00:00Z\nlatest-ok/2.630.0 2026-10-21T10:00:00Z\n"
                  "latest-ok/2.635.0 2026-11-03T09:00:00Z\nlatest-ok/2.639.0 2026-11-07T15:00:00Z\n")
IMG = [{"id": 1, "created_at": "2026-10-20T10:00:00Z", "tags": ["2.629.0"]},
       {"id": 2, "created_at": "2026-10-21T10:00:00Z", "tags": ["2.630.0"]},
       {"id": 3, "created_at": "2026-09-01T10:00:00Z", "tags": ["2.500.0"]},
       {"id": 4, "created_at": "2026-09-01T10:00:00Z", "tags": []},
       {"id": 5, "created_at": "2026-09-01T10:00:00Z", "tags": ["2.501.0", "latest"]},
       {"id": 6, "created_at": "2026-09-02T10:00:00Z", "tags": ["2.501.0"]},
       {"id": 7, "created_at": "2026-11-07T15:00:00Z", "tags": ["2.638.0"]},
       {"id": 8, "created_at": "2026-08-20T10:00:00Z", "tags": ["2.490.0"]}]
keep, plan = wr.prune_plan(TG, "v2.639.0", REL, IMG, "o/r", "users/o/packages/container/kalmido", NOW)
rel_gone = sorted(x[1] for x in plan if x[0] == "release")
img_gone = sorted(x[1] for x in plan if x[0] == "image")
check((2, 630, 0) in keep and (2, 629, 0) not in keep, f"the newest latest-ok of each ISO week stays, an older one of it goes {sorted(keep)}")
check((2, 501, 0) in keep and (2, 500, 0) not in keep and (2, 490, 0) in keep,
      "before the first latest-ok tag: the newest release of each week stays")
check(rel_gone == ["2.500.0", "2.629.0"], f"releases that go {rel_gone}")
check("2.631.0" not in rel_gone and "2.635.0" not in rel_gone, "younger than 14 days stays (even without latest-ok)")
check(img_gone == ["2.500.0", "2.629.0"], f"images that go {img_gone}")
check(not any(p.endswith("/versions/4") or p.endswith("/versions/5") or p.endswith("/versions/7") for _, _, p in plan),
      "untagged parts, :latest and a young image stay")
check(not any("/releases/90" in p or "/releases/91" in p for _, _, p in plan), "a release without a version or a draft is never touched")
check(all(re.fullmatch(r"repos/o/r/releases/\d+|users/o/packages/container/kalmido/versions/\d+", p) for _, _, p in plan),
      f"the plan holds only release and package version paths {plan}")
keep2, plan2 = wr.prune_plan(TG, "v2.629.0", REL, IMG, "o/r", "users/o/packages/container/kalmido", NOW)
check((2, 629, 0) in keep2 and not any(x[1] == "2.629.0" for x in plan2), "the current latest always stays")
# 2.641.0 (#5011, review): a train that stood still for weeks - the live version and the next ones keep their image
IMG3 = IMG + [{"id": 30, "created_at": "2026-11-07T15:00:00Z", "tags": ["2.639.0"]},
              {"id": 31, "created_at": "2026-11-08T10:00:00Z", "tags": ["2.640.0"]}]
REL3 = REL + [{"id": 40, "tag_name": "v2.640.0", "created_at": "2026-11-08T10:00:00Z"}]
_, plan3 = wr.prune_plan(TG, "v2.635.0", REL3, IMG3, "o/r", "users/o/packages/container/kalmido", d("2026-12-30T21:00:00Z"))
gone3 = {x[1] for x in plan3}
check(not gone3 & {"2.639.0", "2.640.0"} and "2.629.0" in gone3,
      f"weeks later: the newest latest-ok version and all above it stay, older ones still go {sorted(gone3)}")
for what, kw in (("no latest-ok tag", dict(tags={})), ("no latest release", dict(latest=""))):
    try:
        wr.prune_plan(kw.get("tags", TG), kw.get("latest", "v2.639.0"), REL, IMG, "o/r", "users/o/packages/container/kalmido", NOW)
        check(False, f"{what}: refused")
    except SystemExit as e:
        check("refusing" in str(e), f"{what}: refused, nothing planned ({e})")
for bad in ("repos/o/r/git/refs/tags/v2.1.0", "repos/o/r/git/refs/tags/latest-ok/2.1.0", "repos/o/r/releases/tags/v2.1.0",
            "repos/o/r/releases/12/assets", "repos/o/r", "users/o/packages/container/kalmido"):
    try:
        wr.safe_path(bad)
        check(False, f"safe_path refuses {bad}")
    except ValueError:
        check(True, f"safe_path refuses {bad}")

# the command line writes the plan file and the lists for the log
TMP = tempfile.mkdtemp(prefix="p2641c-")
with open(os.path.join(TMP, "tags.txt"), "w") as f:
    f.write("latest-ok/2.629.0 2026-10-20T10:00:00Z\nlatest-ok/2.630.0 2026-10-21T10:00:00Z\n")
with open(os.path.join(TMP, "r.jsonl"), "w") as f:
    f.write('{"id": 1, "tag_name": "v2.629.0", "created_at": "2026-10-20T10:00:00Z", "draft": false}\n'
            '{"id": 2, "tag_name": "v2.630.0", "created_at": "2026-10-21T10:00:00Z", "draft": false}\n')
with open(os.path.join(TMP, "i.jsonl"), "w") as f:
    f.write('{"id": 5, "created_at": "2026-10-20T10:00:00Z", "tags": ["2.629.0"]}\n')
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "weekly_release.py"), "prune", "--tags", "tags.txt", "--latest", "v2.630.0",
                    "--releases", "r.jsonl", "--images", "i.jsonl", "--repo", "o/r", "--packages", "users/o/packages/container/kalmido",
                    "--today", "2026-11-20", "--plan", "delete.txt"], cwd=TMP, capture_output=True, text=True)
plan_txt = open(os.path.join(TMP, "delete.txt")).read() if os.path.exists(os.path.join(TMP, "delete.txt")) else ""
check(r.returncode == 0 and plan_txt == "repos/o/r/releases/1\nusers/o/packages/container/kalmido/versions/5\n",
      f"prune on the command line: the plan file {r.returncode} {plan_txt!r} {r.stderr[-300:]}")
check("delete releases (1): 2.629.0" in r.stderr and "delete images (1): 2.629.0" in r.stderr and "keep (" in r.stderr,
      f"the lists for the log {r.stderr[-300:]}")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "weekly_release.py"), "pick", "--tags", "tags.txt", "--latest", "v2.629.0",
                    "--today", "2026-10-25", "--notes", "notes.md", os.path.join(ROOT, "CHANGELOG.md")], cwd=TMP, capture_output=True, text=True)
check(r.returncode == 0 and "version=2.630.0\n" in r.stdout and "prev=2.629.0\n" in r.stdout and os.path.exists(os.path.join(TMP, "notes.md")),
      f"pick on the command line: lines for $GITHUB_OUTPUT and the notes {r.stdout!r} {r.stderr[-200:]}")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "weekly_release.py"), "pick", "--tags", "tags.txt", "--latest", "v2.630.0",
                    "--today", "2026-10-18"], cwd=TMP, capture_output=True, text=True)
check(r.returncode == 0 and "version=\n" in r.stdout, f"nothing new: empty version {r.stdout!r}")

# ------------------------------------------------------------------ workflows
rel = read(".github", "workflows", "release.yml")
wk = read(".github", "workflows", "weekly-release.yml")
pr = read(".github", "workflows", "prune-releases.yml")
pro = read(".github", "workflows", "promote.yml")


def code(t):
    return "\n".join(x for x in t.splitlines() if not x.lstrip().startswith("#"))


def jobs(t):
    j = t.split("\njobs:\n", 1)[1]
    return {m.group(1): m.group(2) for m in re.finditer(r"^  ([a-z-]+):\n((?:    .*\n|\n)+)", j, re.M)}


check("gh release" not in code(rel) and "contents: write" not in rel, "release.yml makes no release page any more")
check("ghcr.io/gegenschuss/kalmido:${{ steps.v.outputs.version }}" in rel, "release.yml still builds the image of every version")
check(re.search(r"^  schedule:\n    - cron: \"[0-9]+ [0-9]+ \* \* 0\"", wk, re.M) is not None and "workflow_dispatch:" in wk,
      "weekly-release.yml runs on Sunday and by hand")
wj = jobs(wk)
check(set(wj) == {"pick", "publish", "prune"}, f"weekly jobs {sorted(wj)}")
check("write" not in wj["pick"] and "tools/weekly_release.py pick" in wj["pick"], "the job pick reads only and runs the script")
check("contents: write" in wj["publish"] and "packages: write" in wj["publish"] and wj["publish"].count("uses:") == 1
      and "actions/download-artifact@" in wj["publish"], "the job that writes runs only download-artifact")
pub = wj["publish"]
check('gh release create "$tag"' in pub and "--verify-tag --latest " in pub and 'tag="v$VER"' in pub and "latest-ok" not in code(pub),
      "the release hangs on vX.Y.Z (never latest-ok/...), never creates a tag, becomes latest")
check(pub.index("imagetools create -t ghcr.io/gegenschuss/kalmido:latest") < pub.index("gh release create"),
      "first :latest, then the mark the installers read")
check("--password-stdin" in pub, "the token does not stand on the command line")
for a in ("SHA256SUMS", "image-digest.txt", "install.sh", "install.ps1", "kalmido-$VER.tar.gz", "kalmido-$VER.zip"):
    check(a in wj["pick"], f"the weekly release carries {a} as before")
check('refs/tags/latest-ok/$ver^{commit}' in wj["pick"] and '[ "$a" = "$b" ]' in wj["pick"], "latest-ok/X.Y.Z must be on the commit of vX.Y.Z")
check("uses: ./.github/workflows/prune-releases.yml" in wj["prune"] and "dry_run: ${{ vars.KALMIDO_PRUNE_APPLY != '1' }}" in wj["prune"],
      "the weekly run calls the prune, a dry run unless KALMIDO_PRUNE_APPLY=1")
check(re.search(r"dry_run:\n(?:        .*\n)*?        default: true", pr) is not None and "workflow_dispatch:" in pr and "workflow_call:" in pr,
      "prune-releases.yml: by hand and called, a dry run by default")
pj = jobs(pr)
check("write" not in pj["plan"] and "tools/weekly_release.py prune" in pj["plan"], "the plan job reads only")
check("inputs.dry_run == false" in pj["delete"] and pj["delete"].count("uses:") == 1 and "actions/download-artifact@" in pj["delete"],
      "the delete job runs only when asked and only download-artifact")
check("gh api -X DELETE" in pj["delete"] and "*refs*|*/git/*|*/tags*" in pj["delete"] and "git push" not in code(pr) and "git tag" not in code(pr)
      and "--cleanup-tag" not in pr, "the delete loop refuses refs and tags; no git tag is ever touched")
for name, t in (("weekly-release.yml", wk), ("prune-releases.yml", pr), ("promote.yml", pro)):
    head = t.split("\njobs:\n", 1)[0]
    check(not re.search(r"^\s+\S+: write", head, re.M), f"{name}: no write right for the whole workflow")
    runs = re.findall(r"^\s+run: [|>]?\n((?:\s{10,}.*\n)+)|^\s+run: (.+)$", t, re.M)
    check(all("inputs." not in (a or b) and "github.event" not in (a or b) for a, b in runs), f"{name}: inputs reach no shell line as an expression")
check(": write" not in pro and "release edit" not in pro and "imagetools create" not in pro and "imagetools inspect" in pro,
      "promote.yml only checks the tag and the image, it moves nothing")

# ------------------------------------------------------------------ install.sh: a version without a release page
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
with open(os.path.join(BIN, "curl"), "w") as f:
    f.write('#!/bin/sh\nout=""; prev=""\nfor a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
            '[ -n "$out" ] && printf "Not Found" > "$out"\nprintf 404\nexit 0\n')
for tool in ("docker", "git"):
    with open(os.path.join(BIN, tool), "w") as f:
        f.write(f'#!/bin/sh\necho "{tool} $*" >> "{TMP}/called"\nexit 1\n')
for p in os.listdir(BIN):
    os.chmod(os.path.join(BIN, p), 0o755)
home = os.path.join(TMP, "home")
os.makedirs(home)
env = {k: v for k, v in os.environ.items() if not k.startswith(("KALMIDO_", "SSH_"))}
env.update(PATH=BIN + os.pathsep + env["PATH"], HOME=home, KALMIDO_VERSION="2.640.0")
r = subprocess.run(["sh", os.path.join(ROOT, "install.sh")], env=env, capture_output=True, text=True, timeout=60)
out = r.stdout + r.stderr
check(r.returncode != 0 and "Nothing was changed" in out and "v2.640.0" in out and "one version per week" in out,
      f"a version in between: a clean stop that says why ({r.returncode} {out[-400:]})")
check(not os.path.exists(os.path.join(home, "kalmido")) and not os.path.exists(os.path.join(TMP, "called")),
      "nothing was made: no folder, no docker, no git")
check("one version per week" in read("install.ps1"), "install.ps1 says the same")

shutil.rmtree(TMP, ignore_errors=True)
print(f"p2641_c_weekly: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
