#!/usr/bin/env python3
"""One GitHub release per ISO week and the thinning of old releases and images (2.641.0, #5011).

    python3 tools/weekly_release.py pick  --tags TAGS --latest vX.Y.Z [--today YYYY-MM-DD] [--notes notes.md] [CHANGELOG ...]
    python3 tools/weekly_release.py prune --tags TAGS --latest vX.Y.Z --releases R.jsonl --images I.jsonl
                                          --repo OWNER/NAME --packages users/OWNER/packages/container/NAME
                                          [--today YYYY-MM-DD] [--days 14] [--plan delete.txt]

TAGS: one line per tag "latest-ok/X.Y.Z <ISO date>" (git for-each-ref --format '%(refname:strip=2) %(creatordate:iso-strict)').
The tag latest-ok/X.Y.Z (pushed by the live train after the device test) only CHOOSES a version; the release itself hangs on
the tag vX.Y.Z (the update check of the servers and install.sh accept only vX.Y.Z).

pick: the newest latest-ok version up to the end of the ISO week of --today that is above the current latest release. Prints
  version=X.Y.Z / prev=X.Y.Z / count=N (for $GITHUB_OUTPUT; version= empty = nothing to publish). --notes writes the text of
  the release: the section "Action needed" of ALL versions since the last weekly release, collected on top (the update hint
  of the servers reads only that section of the latest release), then all CHANGELOG sections of these versions, made
  readable by tools/release_notes.py.
prune: which GitHub release objects and ghcr image versions go. A version stays when it is the newest latest-ok version of
  its ISO week (weeks before the first latest-ok tag: the newest release of the week), the current latest release, or the
  object is younger than --days days. Images: only tagged versions whose tags are all plain X.Y.Z go (never :latest, never
  the untagged platform parts of a kept image). Prints the lists for the log; --plan writes the API paths to DELETE, one
  per line. Only release objects and package versions: git tags are NEVER deleted or moved (safe_path refuses everything
  else). No latest-ok tag or no latest release (a failed listing) = exit 2, nothing is planned.
Standard library only (the workflows run it with the runner's python3).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_notes  # noqa: E402

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
HEAD = re.compile(r"^## \[(\d+\.\d+\.\d+)\]")
ACTION = re.compile(r"^\s{0,3}(#{1,6})\s*action needed\b.*$", re.I)
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")
KEEP_DAYS = 14
SAFE = (re.compile(r"^repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/\d+$"),
        re.compile(r"^(?:users|orgs)/[A-Za-z0-9_.-]+/packages/container/[A-Za-z0-9_.-]+/versions/\d+$"))


def ver(s):
    m = SEMVER.match(str(s or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def vstr(v):
    return ".".join(map(str, v))


def when(s):
    """ISO date / instant -> aware datetime in UTC (a plain date = midnight UTC)."""
    s = str(s or "").strip().replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def week(d):
    y, w, _ = d.isocalendar()
    return (y, w)


def week_end(day):
    """The end of the ISO week (Sunday 24:00 UTC) of the date DAY."""
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc) - dt.timedelta(days=day.isoweekday() - 1)
    return start + dt.timedelta(days=7)


def read_tags(text):
    """'latest-ok/X.Y.Z <date>' lines -> {version: datetime} (other lines are skipped)."""
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("latest-ok/"):
            continue
        v = ver(parts[0][len("latest-ok/"):])
        if v:
            try:
                out[v] = when(parts[1])
            except ValueError:
                continue
    return out


def sections(text):
    """CHANGELOG text -> {version: section text without its heading}."""
    out, cur, buf = {}, None, []
    for line in text.splitlines():
        m = HEAD.match(line)
        if m or line.startswith("## ") or re.match(r"^\[[^]]+\]: http", line):
            if cur:
                out[cur] = "\n".join(buf).strip("\n")
            cur, buf = (ver(m.group(1)) if m else None), []
            continue
        if cur:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip("\n")
    return out


def split_action(body):
    """-> (body without its "Action needed" sections, [lines of those sections]). A section ends at the next heading of the
    same or a higher level, or at the next "Package X.Y.Z (...)." line (the start of another package's entries)."""
    rest, action, level = [], [], 0
    for line in body.splitlines():
        h = HEADING.match(line)
        if level and (h and len(h.group(1)) <= level or release_notes.PKG.match(line.strip())):
            level = 0
        if level:
            action.append(line)
            continue
        m = ACTION.match(line)
        if m:
            level = len(m.group(1))
            continue
        rest.append(line)
    while action and not action[-1].strip():
        action.pop()
    while action and not action[0].strip():
        action.pop(0)
    return "\n".join(rest), action


def pick(tags, latest, today):
    """-> the version to publish (None: nothing new), from the latest-ok tags up to the end of the week of TODAY."""
    end = week_end(today)
    cand = [v for v, d in tags.items() if d < end]
    if not cand:
        return None
    best = max(cand)
    cur = ver(latest)
    if cur and best < cur:
        return None  # a fix of an older line never becomes latest
    return best


def weekly_notes(secs, prev, target):
    """The text of the weekly release for the versions in (prev, target]."""
    cur = ver(prev)
    vs = sorted(v for v in secs if v <= target and (cur is None or v > cur))
    if target not in vs:
        vs.append(target)
    bodies, actions = [], []
    for v in sorted(vs, reverse=True):  # newest first, like the CHANGELOG
        body, act = split_action(secs.get(v, ""))
        if body.strip():
            bodies.append(body)
        if act:
            actions.append((v, act))
    out = []
    if actions:
        # a level-2 heading: the update hint (kalmido/core/instance.py update_action) reads up to the next one
        out += ["## Action needed", ""]
        for v, act in actions:
            out += [f"**{vstr(v)}**", "", *act, ""]  # its own sub-headings are deeper than level 2, so they stay inside
        out += ["## Changes", ""]
    if len(vs) > 1:
        out += [f"This weekly release combines {len(vs)} versions, {vstr(min(vs))} to {vstr(max(vs))}.", ""]
    text = "\n\n".join(bodies)
    out.append(release_notes.render(text) if text.strip() else "See CHANGELOG.md.\n")
    return "\n".join(out).rstrip() + "\n", vs


def keep_set(tags, releases, latest):
    """Versions that stay: newest latest-ok of each ISO week, the newest release of each week before the first latest-ok tag,
    the current latest release."""
    keep = set()
    by_week = {}
    for v, d in tags.items():
        k = week(d)
        if k not in by_week or v > by_week[k]:
            by_week[k] = v
    keep |= set(by_week.values())
    first = min(tags) if tags else None
    old = {}
    for r in releases:
        v = ver(r.get("tag_name"))
        if not v or (first and v >= first) or not r.get("created_at"):
            continue
        k = week(when(r["created_at"]))
        if k not in old or v > old[k]:
            old[k] = v
    keep |= set(old.values())
    if ver(latest):
        keep.add(ver(latest))
    return keep


def safe_path(p):
    """Only a release object or a container package version may be deleted; never a git ref / tag."""
    if "/git/" in p or "refs" in p or "/tags" in p or not any(r.match(p) for r in SAFE):
        raise ValueError(f"refused to delete {p!r}: only release objects and package versions")
    return p


def prune_plan(tags, latest, releases, images, repo, packages, now, days=KEEP_DAYS):
    """-> (keep versions, [(kind, version text, api path)]) - kind 'release' or 'image'."""
    if not tags:
        raise SystemExit("no latest-ok tag listed: refusing to plan (a failed listing must not delete anything)")
    if not ver(latest):
        raise SystemExit(f"no current latest release ({latest!r}): refusing to plan")
    keep = keep_set(tags, releases, latest)
    young = now - dt.timedelta(days=days)
    out = []
    for r in releases:
        v = ver(r.get("tag_name"))
        if not v or v in keep or r.get("draft") or not r.get("id") or not r.get("created_at"):
            continue
        if when(r["created_at"]) >= young:
            continue
        out.append(("release", vstr(v), safe_path(f"repos/{repo}/releases/{int(r['id'])}")))
    for im in images:
        tl = [str(t) for t in (im.get("tags") or [])]
        vs = [ver(t) for t in tl]
        if not tl or any(v is None or t.startswith("v") for v, t in zip(vs, tl)) or any(v in keep for v in vs):
            continue  # untagged parts of a kept image, :latest or another name, a kept version
        if not im.get("id") or not im.get("created_at") or when(im["created_at"]) >= young:
            continue
        out.append(("image", ",".join(tl), safe_path(f"{packages}/versions/{int(im['id'])}")))
    return keep, out


def read_json_lines(path):
    """A JSON array, or one JSON object per line (gh api --paginate --jq '.[] | {...}')."""
    with open(path, encoding="utf-8") as f:
        txt = f.read().strip()
    if not txt:
        return []
    if txt.startswith("["):
        return json.loads(txt)
    return [json.loads(x) for x in txt.splitlines() if x.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("pick", "prune"):
        p = sub.add_parser(name)
        p.add_argument("--tags", required=True)
        p.add_argument("--latest", default="")
        p.add_argument("--today", default="")
    p = sub.choices["pick"]
    p.add_argument("--notes", default="")
    p.add_argument("changelog", nargs="*")
    p = sub.choices["prune"]
    p.add_argument("--releases", required=True)
    p.add_argument("--images", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--packages", required=True)
    p.add_argument("--days", type=int, default=KEEP_DAYS)
    p.add_argument("--plan", default="")
    a = ap.parse_args(argv)
    with open(a.tags, encoding="utf-8") as f:
        tags = read_tags(f.read())
    now = when(a.today) if a.today else dt.datetime.now(dt.timezone.utc)
    if a.cmd == "pick":
        v = pick(tags, a.latest, now)
        if not v:
            print("version=")
            print(f"prev={(a.latest or '').lstrip('v')}")
            print("count=0")
            return 0
        secs = {}
        for path in a.changelog:
            with open(path, encoding="utf-8") as f:
                for k, s in sections(f.read()).items():
                    secs.setdefault(k, s)
        text, vs = weekly_notes(secs, a.latest, v)
        if a.notes:
            with open(a.notes, "w", encoding="utf-8") as f:
                f.write(text)
        print(f"version={vstr(v)}")
        print(f"prev={(a.latest or '').lstrip('v')}")
        print(f"count={len(vs)}")
        return 0
    keep, plan = prune_plan(tags, a.latest, read_json_lines(a.releases), read_json_lines(a.images), a.repo, a.packages, now, a.days)
    print(f"keep ({len(keep)}): " + " ".join(vstr(v) for v in sorted(keep)), file=sys.stderr)
    for kind in ("release", "image"):
        rows = [x for x in plan if x[0] == kind]
        print(f"delete {kind}s ({len(rows)}): " + " ".join(x[1] for x in rows), file=sys.stderr)
    if a.plan:
        with open(a.plan, "w", encoding="utf-8") as f:
            f.write("".join(x[2] + "\n" for x in plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
