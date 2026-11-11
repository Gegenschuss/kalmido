#!/usr/bin/env python3
"""Release notes for GitHub from one CHANGELOG.md section (2.277, #3054: readable for people outside the project).

    python3 tools/release_notes.py section.md > notes.md

The CHANGELOG stays as it is; only the text of the GitHub release changes:
- a short summary on top,
- "Package X.Y.Z (Title)." lines are dropped (2.940.0, #5636: package titles are internal and often German; the entries
  of all packages are merged by heading into one area),
- internal task numbers like (#2742) are dropped, others in the text are set in code font (GitHub would link them to
  unrelated issues of this repository),
- lines about test and CI fixes ("CI of X.Y.Z: ...") move into a folded block at the end,
- a long text folds each area, so the page stays short.
2.538.0 (#4360): titles of bundles ("Bündel: ...", "Sammelpaket: ...") are internal and dropped (their entries are merged
by heading), lines about main and CI ("Main red after CI ...") are dropped, the top shows three to five real highlights
(first Added / Changed entries), and the whole text stays below MAX_CHARS (GitHub refuses release texts over 125000
characters; the rest is only a link to the CHANGELOG).
2.940.0 (#5636): no package title at all reaches the public text (not only bundles: "Teil 3/4: ...", "Neubau von ...",
"Start pflegen: ..." slipped through the word filter) - the summary line "In this release" is gone, the top shows only the
English highlights.
Standard library only (the release job runs it with the runner's python3).
"""
import re
import sys

LONG = 3000  # characters; longer notes fold their areas
MAX_CHARS = 20000  # hard limit of the whole text; GitHub's own limit is 125000, a release page nobody reads is no use
HIGHLIGHTS = 5
HIGHLIGHT_LEN = 200
MAINCI = re.compile(r"^\s*(?:-\s*)?(?:main\s+(?:red|is red)|CI\s+red|CI-only\s+red)\b|^\s*(?:-\s*)?Main red after CI", re.I)
CHANGELOG_URL = "https://github.com/Gegenschuss/kalmido/blob/main/CHANGELOG.md"
PKG = re.compile(r"^Package\s+\d+(?:\.\d+){1,2}[a-z]?\s*\((.+)\)\.?\s*$")
CI = re.compile(r"^(\s*-\s*)?CI of \d+(?:\.\d+){1,2}:\s*")
TASKS = re.compile(r"\s*\((?:#\d+[a-z]?(?:\s*[,;/]\s*|\s+))*#\d+[a-z]?\)")  # "(#12)", "(#12, #34)"
BARE = re.compile(r"(?<![\w`&/])#(\d+[a-z]?)\b")  # a number inside the text: code font, so GitHub links no issue


def clean(line):
    line = BARE.sub(r"`#\1`", TASKS.sub("", line))
    return re.sub(r"[ \t]+([.,;:])", r"\1", line).rstrip()


def parse(text):
    """-> (areas [("", [lines])], ci [lines]): one merged area (or none); a package line only starts the next part."""
    areas, ci = [["", []]], []
    for raw in text.splitlines():
        if PKG.match(raw.strip()):  # 2.940.0 (#5636): the title is internal, the line goes
            areas.append(["", []])
            continue
        if MAINCI.search(raw):
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
        if any(x.strip() for x in keep):
            out.append((title, keep))
    return merge_untitled(out), ci


def merge_untitled(areas):
    """All package parts become ONE area without title, entries merged by heading."""
    heads, order = {}, []
    for _, lines in areas:
        cur = ""
        for l in lines:
            if l.startswith("#"):
                cur = l
                continue
            if not l.strip():
                continue
            if cur not in heads:
                heads[cur] = []
                order.append(cur)
            heads[cur].append(l)
    merged = []
    for h in order:
        merged += ([h] if h else []) + heads[h] + [""]
    while merged and not merged[-1].strip():
        merged.pop()
    return [("", merged)] if merged else []


def highlights(areas):
    """Up to HIGHLIGHTS real entries: the first Added / Changed lines (tests and internals skipped), shortened."""
    found = []
    for _, lines in areas:
        sec = ""
        for l in lines:
            if l.startswith("#"):
                sec = l.lstrip("# ").strip().lower()
            elif sec in ("added", "changed") and l.startswith("- ") and not re.match(r"- (Tests?|CI)\b", l):
                t = l[2:].strip()
                if len(t) > HIGHLIGHT_LEN:
                    t = t[:HIGHLIGHT_LEN].rsplit(" ", 1)[0].rstrip(".,;: ") + " ..."
                found.append("- " + t)
    return found[:HIGHLIGHTS]


def summary(areas, ci):
    if areas:
        s = "This release brings the changes listed below."
    else:
        s = "A maintenance release: fixes found by the tests, no new features."
    if ci and areas:
        s += " Fixes found by the automated tests are folded at the end."
    s += " Update with update.sh / update.ps1 in your install folder; your data and settings are kept."
    return s


def render(text):
    areas, ci = parse(text)
    body = [sec for _, sec in areas]
    full = sum(len("\n".join(s)) for s in body)
    out = [summary(areas, ci), ""]
    hl = highlights(areas)
    if hl:
        out += ["**Highlights**", "", *hl, ""]
    foot = f"Full list of changes: [CHANGELOG.md]({CHANGELOG_URL})"
    # room for the rest: the CI block and the footer stay, areas that no longer fit are only a link
    budget = MAX_CHARS - len("\n".join(out)) - len(foot) - 400
    if ci:
        budget -= sum(len(x) + 1 for x in ci) + 100
    skipped = 0
    for sec in body:
        cost = len("\n".join(sec)) + 120
        if cost > budget:
            skipped += 1
            # 2.641.0 (#5011): a weekly release merges many versions into one big area; it keeps the entries that fit
            # (at line ends, no heading left without entries) instead of vanishing behind the link
            part, used = [], 120
            for l in sec:
                if used + len(l) + 1 > budget:
                    break
                part.append(l)
                used += len(l) + 1
            while part and (not part[-1].strip() or part[-1].startswith("#")):
                part.pop()
            if not any(x.startswith("- ") for x in part):
                continue
            sec, cost = part, used
        budget -= cost
        if full > LONG and hl:
            out += ["<details>", "<summary><b>All changes</b></summary>", "", *sec, "", "</details>", ""]
        else:
            out += [*sec, ""]
    if skipped:
        out += ["The rest of the changes is too long for this page; see the CHANGELOG.", ""]
    if ci:
        out += ["<details>", "<summary>Test and CI fixes</summary>", "", *ci, "", "</details>", ""]
    out.append(foot)
    text = "\n".join(out).strip() + "\n"
    if len(text) > MAX_CHARS:  # only a giant CI block gets here: cut hard, keep the link
        text = text[:MAX_CHARS - len(foot) - 40].rsplit("\n", 1)[0] + "\n\n</details>\n\n" + foot + "\n"
    return text


if __name__ == "__main__":
    src = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    sys.stdout.write(render(src) if src.strip() else "")
