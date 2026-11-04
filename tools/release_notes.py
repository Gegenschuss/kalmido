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
2.538.0 (#4360): titles of bundles ("Bündel: ...", "Sammelpaket: ...") are internal and dropped (their entries are merged
by heading), lines about main and CI ("Main red after CI ...") are dropped, the top shows three to five real highlights
(first Added / Changed entries), and the whole text stays below MAX_CHARS (GitHub refuses release texts over 125000
characters; the rest is only a link to the CHANGELOG).
Standard library only (the release job runs it with the runner's python3).
"""
import re
import sys

LONG = 3000  # characters; longer notes fold their areas
MAX_CHARS = 20000  # hard limit of the whole text; GitHub's own limit is 125000, a release page nobody reads is no use
HIGHLIGHTS = 5
HIGHLIGHT_LEN = 200
BUNDLE = re.compile(r"^(?:B[üu]ndel|Sammelpaket|Bundle|Collective package)\s*:", re.I)
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
    """-> (areas [(title, [lines])], ci [lines]); text before the first package line is an area without title."""
    areas, ci = [["", []]], []
    for raw in text.splitlines():
        m = PKG.match(raw.strip())
        if m:
            areas.append([m.group(1).strip(), []])
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
        if BUNDLE.match(title):
            title = ""
        if title or any(x.strip() for x in keep):
            out.append((title, keep))
    return merge_untitled(out), ci


def merge_untitled(areas):
    """All areas without a title (bundles, text before the first package) become ONE area, entries merged by heading."""
    heads, order, titled = {}, [], []
    for title, lines in areas:
        if title:
            titled.append((title, lines))
            continue
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
    return ([("", merged)] if merged else []) + titled


def highlights(areas):
    """Up to HIGHLIGHTS real entries: the first Added / Changed lines (tests and internals skipped), shortened."""
    found = []
    for _, lines in sorted(areas, key=lambda a: bool(a[0])):  # merged untitled area first, then titled ones
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
    hl = highlights(areas)
    if hl:
        out += ["**Highlights**", "", *hl, ""]
    foot = f"Full list of changes: [CHANGELOG.md]({CHANGELOG_URL})"
    # room for the rest: the CI block and the footer stay, areas that no longer fit are only a link
    budget = MAX_CHARS - len("\n".join(out)) - len(foot) - 400
    if ci:
        budget -= sum(len(x) + 1 for x in ci) + 100
    skipped = 0
    for title, sec in body:
        cost = len("\n".join(sec)) + 120
        if cost > budget:
            skipped += 1
            continue
        budget -= cost
        if full > LONG and (title or hl):
            label = title[:1].upper() + title[1:] if title else "All changes"
            out += ["<details>", f"<summary><b>{label}</b></summary>", "", *sec, "", "</details>", ""]
        else:
            if title:
                out += [f"### {title[:1].upper() + title[1:]}", ""]
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
