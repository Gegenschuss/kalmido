#!/usr/bin/env python3
"""Release notes for GitHub from one CHANGELOG.md section (2.277, #3054: readable for people outside the project).

    python3 tools/release_notes.py section.md > notes.md

The CHANGELOG stays as it is; only the text of the GitHub release changes:
- a short summary on top (what the release brings, from the package titles),
- "Package X.Y.Z (Title)." becomes a heading "Title" without the internal package number,
- internal task numbers like (#2742) are dropped, others in the text are set in code font (GitHub would link them to
  unrelated issues of this repository),
- lines about test and CI fixes ("CI of X.Y.Z: ...") move into a folded block at the end,
- a long text folds each area, so the page stays short.
Standard library only (the release job runs it with the runner's python3).
"""
import re
import sys

LONG = 3000  # characters; longer notes fold their areas
PKG = re.compile(r"^Package\s+\d+(?:\.\d+){1,2}[a-z]?\s*\((.+)\)\.?\s*$")
CI = re.compile(r"^(\s*-\s*)?CI of \d+(?:\.\d+){1,2}:\s*")
TASKS = re.compile(r"\s*\((?:#\d+[a-z]?(?:\s*[,;/]\s*|\s+))*#\d+[a-z]?\)")  # "(#12)", "(#12, #34)"
BARE = re.compile(r"(?<![\w`&/])#(\d+[a-z]?)\b")  # a number inside the text: code font, so GitHub links no issue


def clean(line):
    line = BARE.sub(r"`#\1`", TASKS.sub("", line))
    return re.sub(r"[ \t]+([.,;:])", r"\1", line).rstrip()


def parse(text):
    """-> (areas [(title, [lines])], ci [lines]); text before the first package line is an area without title."""
    areas, ci = [["", []]], []
    for raw in text.splitlines():
        m = PKG.match(raw.strip())
        if m:
            areas.append([m.group(1).strip(), []])
            continue
        if CI.match(raw):
            ci.append("- " + clean(CI.sub("", raw)))
            continue
        areas[-1][1].append(clean(raw))
    out = []
    for title, lines in areas:
        while lines and not lines[0].strip():
            lines.pop(0)
        # a section heading left without entries (its lines were CI lines) goes too
        keep = []
        for i, l in enumerate(lines):
            if l.startswith("#") and not any(x.startswith("-") for x in lines[i + 1:next(
                    (j for j in range(i + 1, len(lines)) if lines[j].startswith("#")), len(lines))]):
                continue
            keep.append(l)
        while keep and not keep[-1].strip():
            keep.pop()
        if title or any(x.strip() for x in keep):
            out.append((title, keep))
    return out, ci


def summary(areas, ci):
    titles = [t for t, _ in areas if t]
    if titles:
        cap = [t[:1].upper() + t[1:] for t in titles]
        more = f" (and {len(cap) - 4} more)" if len(cap) > 4 else ""
        s = "**In this release:** " + " · ".join(cap[:4]) + more + "."
    elif areas:
        s = "This release brings the changes listed below."
    else:
        s = "A maintenance release: fixes found by the tests, no new features."
    if ci and (titles or areas):
        s += " Fixes found by the automated tests are folded at the end."
    s += " Update with update.sh / update.ps1 in your install folder; your data and settings are kept."
    return s


def render(text):
    areas, ci = parse(text)
    body = []
    for title, lines in areas:
        sec = [re.sub(r"^###\s", "#### ", l) if title else l for l in lines]
        body.append((title, sec))
    full = sum(len("\n".join(s)) for _, s in body)
    out = [summary(areas, ci), ""]
    for title, sec in body:
        if full > LONG and title:
            out += ["<details>", f"<summary><b>{title[:1].upper() + title[1:]}</b></summary>", "", *sec, "", "</details>", ""]
        else:
            if title:
                out += [f"### {title[:1].upper() + title[1:]}", ""]
            out += [*sec, ""]
    if ci:
        out += ["<details>", "<summary>Test and CI fixes</summary>", "", *ci, "", "</details>", ""]
    out.append("Full list of changes: [CHANGELOG.md](https://github.com/Gegenschuss/kalmido/blob/main/CHANGELOG.md)")
    return "\n".join(out).strip() + "\n"


if __name__ == "__main__":
    src = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    sys.stdout.write(render(src) if src.strip() else "")
