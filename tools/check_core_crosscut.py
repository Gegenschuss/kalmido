#!/usr/bin/env python3
"""2.755.0 (#5267, stage Q0a of the cross-cutting core, analysis #3563): links, tags, comments, reactions, read marks, versions
and follow / notify exist once, in the shared core (docs/dev/kern.md, section "Cross-cutting parts"). A new table that builds one
of them for a single area is red. What is there today stands in tools/core_crosscut_allow.json with its reason (the stage that
takes it down, or the area's own logic); the list grows only with a decision of the product owner.

Read: schema.py + the fragments of migrations.d (tools/check_migrations.py schema_src). A table dropped by a fragment
(DROP TABLE IF EXISTS in AFTER) counts as gone. Only CREATE TABLE counts (an ADD COLUMN or an index is no new table).
A table looks like a cross-cutting part when
  - its name ends in _links _tags _comments _notes _reactions _rx _trash_text _reads _seen _versions _hist _notif _watchers
    _bell _follow _subscriptions, or
  - it has an *_id column and one of tag, tag_id, body, seen_id, last_id, read_at, seen_at, emoji, follow, muted, no, or
  - it joins two tables (two *_id columns with REFERENCES to different tables) and holds nothing else but id, created_at,
    created_by, sort
  not: the core's own tables (obj_*), and tables with token_hash, url, base_url or role (share links, address lists, roles).
Code (outside kalmido/core/): a new MENTION_RE, need_*_say( or *_react( definition is red (the core's comment / reaction rules
come once); a new def *_search( / *search_sql( is a hint only (the search stage Q6). Today's ones stand in the same file.
A line of the allow file whose table / definition is gone or no longer looks like one is a finding too: take it out.

usage: python3 tools/check_core_crosscut.py [-v] [--root DIR]      exit 1 on a finding
Standard library only.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from check_migrations import fragments  # noqa: E402

ALLOW = os.path.join("tools", "core_crosscut_allow.json")
SUFFIX = re.compile(r"_(links|tags|comments|notes|reactions|rx|trash_text|reads|seen|versions|hist|notif|watchers|bell|follow|"
                    r"subscriptions)$")
MARK_COLS = {"tag", "tag_id", "body", "seen_id", "last_id", "read_at", "seen_at", "emoji", "follow", "muted", "no"}
JOIN_FREE = {"id", "created_at", "created_by", "sort"}
NOT_COLS = {"token_hash", "url", "base_url", "role"}
CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(", re.I)
DROP = re.compile(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)", re.I)
KIND = {"_links": "a link", "_tags": "tags", "_comments": "a comment", "_notes": "a comment", "_reactions": "a reaction",
        "_rx": "a reaction", "_trash_text": "a comment", "_reads": "a read mark", "_seen": "a read mark",
        "_versions": "a version", "_hist": "a version", "_notif": "following", "_watchers": "following", "_bell": "following",
        "_follow": "following", "_subscriptions": "following"}
COL_KIND = {"tag": "tags", "tag_id": "tags", "body": "a comment", "emoji": "a reaction", "seen_id": "a read mark",
            "last_id": "a read mark", "read_at": "a read mark", "seen_at": "a read mark", "follow": "following",
            "muted": "following", "no": "following"}
CODE_RED = re.compile(r"^[ \t]*(?:MENTION_RE\s*=|def\s+(need_\w*_say|\w*_react)\s*\()", re.M)
CODE_HINT = re.compile(r"^[ \t]*def\s+(\w*_search|\w*search_sql)\s*\(", re.M)


def sources(root=ROOT):
    """[(path relative to root, text)] of schema.py and the fragments."""
    out = []
    for p in [os.path.join(root, "kalmido", "core", "schema.py")] + fragments(root):
        with open(p, encoding="utf-8") as f:
            out.append((os.path.relpath(p, root), f.read()))
    return out


def columns(body):
    """{column: its definition} of a CREATE TABLE body (top level only, constraints left out)."""
    flat, depth = "", 0
    for ch in re.sub(r"--[^\n]*", "", body):  # REFERENCES users(id), NUMERIC(14,2): the brackets' content goes
        depth += (ch == "(") - (ch == ")")
        flat += ch if depth == 0 and ch != ")" else ""
    out = {}
    for part in flat.split(","):
        w = part.split()
        if w and w[0].upper() not in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT", "EXCLUDE"):
            out[w[0].strip('"')] = part
    return out


def tables(srcs):
    """{table: (file, line, {column: definition})} for every CREATE TABLE of srcs, without the tables a fragment drops."""
    out, dropped = {}, set()
    for path, src in srcs:
        for m in CREATE.finditer(src):
            depth, i = 1, m.end()
            while i < len(src) and depth:
                depth += (src[i] == "(") - (src[i] == ")")
                i += 1
            out.setdefault(m.group(1), (path, src.count("\n", 0, m.start()) + 1, columns(src[m.end():i - 1])))
        if "migrations.d" in path:
            dropped |= set(DROP.findall(src))
    return {t: v for t, v in out.items() if t not in dropped}


def looks_like(name, cols):
    """What the table looks like ('a link', 'tags', ...) or None."""
    if name.startswith("obj_") or NOT_COLS & set(cols):
        return None
    m = SUFFIX.search(name)
    if m:
        return KIND["_" + m.group(1)]
    ids = [c for c in cols if c.endswith("_id")]
    hit = sorted(MARK_COLS & set(cols))
    if ids and hit:
        return COL_KIND[hit[0]]
    refs = {r.group(1) for c in ids for r in [re.search(r"REFERENCES\s+(\w+)", cols[c], re.I)] if r}
    if len(refs) >= 2 and not set(cols) - set(ids) - JOIN_FREE:
        return "a link"
    return None


def code_defs(root=ROOT):
    """({'file:name': line} of the red code rule, the same of the search hint) outside kalmido/core/."""
    red, hint = {}, {}
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel.startswith("kalmido/core/"):
            continue
        with open(p, encoding="utf-8") as f:
            src = f.read()
        for rx, into in ((CODE_RED, red), (CODE_HINT, hint)):
            for m in rx.finditer(src):
                into.setdefault(f"{rel}:{m.group(1) or 'MENTION_RE'}", src.count("\n", 0, m.start()) + 1)
    return red, hint


def load_allow(root=ROOT):
    with open(os.path.join(root, ALLOW), encoding="utf-8") as f:
        return json.load(f)


def findings(root=ROOT, srcs=None, allow=None, code=True):
    """(findings, hints) as lines. srcs / allow: texts and an allow dict of their own (the test's fragments)."""
    srcs = sources(root) if srcs is None else srcs
    allow = load_allow(root) if allow is None else allow
    ok_tab, ok_code, ok_search = allow.get("tables", {}), allow.get("code", {}), allow.get("search_functions", {})
    bad, hints, seen = [], [], set()
    for name, (path, line, cols) in sorted(tables(srcs).items()):
        kind = looks_like(name, cols)
        if not kind:
            continue
        seen.add(name)
        if name not in ok_tab:
            bad.append(f"check_core_crosscut: table {name} ({path}:{line}) looks like {kind} - the shared core has it (obj_*, "
                       f"docs/dev/kern.md 'Cross-cutting parts'); an exception only with its reason in {ALLOW}")
    for name in sorted(set(ok_tab) - seen):
        bad.append(f"{ALLOW}: table {name} is gone or no longer looks like a cross-cutting part - take the line out")
    if code:
        red, hint = code_defs(root)
        for k, ln in sorted(red.items()):
            if k not in ok_code:
                f, n = k.rsplit(":", 1)
                bad.append(f"check_core_crosscut: {n} ({f}:{ln}) - mentions, the say rule and reactions come once from the core "
                           f"(docs/dev/kern.md 'Cross-cutting parts'); an exception only with its reason in {ALLOW} code")
        for k in sorted(set(ok_code) - set(red)):
            bad.append(f"{ALLOW}: code {k} is gone - take the line out")
        for k, ln in sorted(hint.items()):
            if k not in ok_search:
                f, n = k.rsplit(":", 1)
                hints.append(f"hint: {n} ({f}:{ln}) is a search of its own - the shared search comes with stage Q6")
        for k in sorted(set(ok_search) - set(hint)):
            bad.append(f"{ALLOW}: search_functions {k} is gone - take the line out")
    return bad, hints


if __name__ == "__main__":
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else ROOT
    out, hints = findings(root)
    for x in hints + out:
        print(x)
    if "-v" in sys.argv or out:
        print(f"check_core_crosscut: {len(load_allow(root).get('tables', {}))} allowed table(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
