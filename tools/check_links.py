#!/usr/bin/env python3
"""Check the links between the repository's Markdown pages (2.277, #3055): every relative link points to an existing
file, every #anchor to a heading (GitHub's anchor rules) or an explicit id / name of that page.

    python3 tools/check_links.py [-v] [FILE.md ...]      exit 1 on a dead link

Default files: the top-level *.md pages, docs/*.md and examples/**/*.md, not the CHANGELOG (old entries keep their old
links). Code blocks and inline code are skipped; external links (http, mailto) are not fetched - CI stays offline.
Standard library only (the CI lint job runs plain Python).
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {"CHANGELOG.md"}
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEAD = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML = re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']""")
IDS = re.compile(r"""<[a-zA-Z][^>]*?\s(?:id|name)\s*=\s*["']([^"']+)["']""")


def prose(text):
    """The text without fenced code blocks (lines inside them become empty, so line numbers stay)."""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)):]:
                fence = None
            out.append("")
            continue
        if m:
            fence = m.group(1)
            out.append("")
            continue
        out.append(line)
    return out


def slug(title):
    """GitHub's heading anchor: markup out, lower case, letters / digits / space / - / _ kept, spaces become -."""
    t = re.sub(r"<[^>]+>", "", title)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[`*]", "", t).strip().lower()
    t = "".join(c for c in t if c.isalnum() or c in " -_")
    return t.replace(" ", "-")


def anchors(path, cache={}):
    if path not in cache:
        lines = prose(open(path, encoding="utf-8").read())
        seen, res = {}, set()
        for line in lines:
            m = HEAD.match(line)
            if m:
                b = slug(m.group(2))
                n = seen.get(b, 0)
                seen[b] = n + 1
                res.add(b if n == 0 else f"{b}-{n}")
            res.update(IDS.findall(line))
        cache[path] = res
    return cache[path]


def check(rel):
    path = os.path.join(ROOT, rel)
    bad = []
    for no, line in enumerate(prose(open(path, encoding="utf-8").read()), 1):
        line = re.sub(r"``[^`]*``|`[^`]*`", "", line)
        for target in LINK.findall(line) + HTML.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
                continue  # http(s), mailto, data ...
            file, _, anchor = target.partition("#")
            dest = os.path.normpath(os.path.join(os.path.dirname(path), file)) if file else path
            if not os.path.exists(dest):
                bad.append(f"{rel}:{no}: missing file {target}")
            elif anchor and dest.endswith(".md") and anchor not in anchors(dest) and anchor.lower() not in anchors(dest):
                bad.append(f"{rel}:{no}: missing anchor {target}")
    return bad


def default_files():
    files = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.md"))]
    files += [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "docs", "*.md"))]
    files += [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "examples", "**", "*.md"), recursive=True)]
    return sorted(f for f in files if os.path.basename(f) not in SKIP)


def main(argv):
    verbose = "-v" in argv
    files = [a for a in argv if a != "-v"] or default_files()
    bad = [b for f in files for b in check(f)]
    for b in bad:
        print(b)
    if verbose or bad:
        print(f"check_links: {len(files)} pages, {len(bad)} dead link(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
