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
Shares and rights (2.846.0, #5522): who may do what exists once too (docs/dev/kern.md section 3: obj_role / obj_need,
fs_shares). A table is red as a share of its own when
  - its name ends in _shares, or
  - it has an *_id column on users / orgs / groups / agents (user_id, org_id, group_id, agent_id, owner_id, or REFERENCES one
    of them) and a role or perm* column (also one added later with ALTER TABLE ... ADD COLUMN); NOT_COLS do not count here.
Code (outside kalmido/core/): a new MENTION_RE, need_*_say( or *_react( definition is red (the core's comment / reaction rules
come once); a new def need_*( / *_role( / *_can( is red as a rights check of its own (allow section "rights"); a new
def *_search( / *search_sql( is a hint only: since stage Q6c (2.1026.0, #5280) an area registers its search with the one
registry (kalmido/core/srchreg.py srch_register) instead of a route of its own. Today's ones stand in the same file.
Filters (2.857.0, #5523): conditions are read once, by the core's filter (kalmido/core/filters.py, static/js/fltkern.js,
static/js/fltdlg.js; docs/dev/kern.md section "Filter"). Outside them a definition named like a filter evaluator or a condition
dialog is red (allow section "filter") -- Python: def *filter(s)_sql / _where / _match / _rules / _cond(s), *_cond_ok,
*_match_rule(s), *_filters; browser (static/js/*.js, function NAME( and const NAME = (...) =>): *filterMatch,
*_filter_match, *Cond(s) / *_cond(s), *CondOk / *_cond_ok, *FilterDlg / *FilterDialog / *CondDlg / *CondRows / *_cond_rows /
*FilterRows (either case of the first letter). Green, because it only USES the core: a definition whose top-level block calls
kflt_*, and one whose name stands in such a block or in a catalog (a block with two of has: / cond: / old: / text: / what: /
ops: / vals:) -- the cnd function handed to kflt_where, a catalog's cond / old.
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
SHARE_ON = {"users", "orgs", "groups", "agents"}
SHARE_IDS = {"user_id", "org_id", "group_id", "agent_id", "owner_id"}
ADD_COL = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
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
CODE_RIGHTS = re.compile(r"^[ \t]*def\s+(need_\w+|\w+_role|\w+_can)\s*\(", re.M)
CODE_HINT = re.compile(r"^[ \t]*def\s+(\w*_search|\w*search_sql)\s*\(", re.M)
# 2.857.0 (#5523): a filter evaluator / condition dialog of its own (the core's filter: FLT_CORE)
FLT_CORE = ("kalmido/core/filters.py", "static/js/fltkern.js", "static/js/fltdlg.js")
FLT_PY = re.compile(r"^([ \t]*)def\s+(\w*(?:filters?_(?:sql|where|match|rules|conds?)|_cond_ok|_match_rules?|\w_filters))\s*\(",
                    re.M)
FLT_JS = re.compile(r"^([ \t]*)(?:(?:async\s+)?function\s*\*?\s*|(?:const|let|var)\s+)(\w*(?:[Ff]ilter[Mm]atch|_filter_match|[a-z]Conds?|"
                    r"_conds?|[Cc]ond[Oo]k|_cond_ok|[Ff]ilter(?:Dlg|Dialog|Rows)|[Cc]ond(?:Dlg|Rows)|_cond_rows))"
                    r"(?:\s*\(|\s*=\s*(?:async\s+)?(?:\([^)\n]*\)|\w+)\s*=>)", re.M)
FLT_CAT = re.compile(r"\b(has|cond|old|text|what|ops|vals)\s*:")


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
    body = re.sub(r"'(?:[^'\n]|'')*'", "''", re.sub(r"--[^\n]*", "", body))  # a DEFAULT 'a,b' is no second column
    for ch in body:  # REFERENCES users(id), NUMERIC(14,2): the brackets' content goes
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


def added_cols(srcs):
    """{table: {column}} of the ALTER TABLE ... ADD COLUMN of srcs (the share rule reads a role added later too)."""
    out = {}
    for _path, src in srcs:
        for t, col in ADD_COL.findall(src):
            out.setdefault(t, set()).add(col)
    return out


def looks_like_share(name, cols, added=()):
    """'a share' when the table holds who may do what of its own (#5522), else None. NOT_COLS do not count here."""
    if name.startswith("obj_"):
        return None
    if name.endswith("_shares"):
        return "a share"
    holder = [c for c in cols if c.endswith("_id") and (c in SHARE_IDS or (
        (r := re.search(r"REFERENCES\s+(\w+)", cols[c], re.I)) and r.group(1) in SHARE_ON))]
    right = [c for c in list(cols) + sorted(added) if c == "role" or c.startswith("perm")]
    return "a share" if holder and right else None


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
    """({'file:name': line} of the red code rule, the same of the search hint, the same of the rights checks) outside
    kalmido/core/. A need_*_say( counts once, under the red code rule."""
    red, hint, rights = {}, {}, {}
    for p in sorted(glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel.startswith("kalmido/core/"):
            continue
        with open(p, encoding="utf-8") as f:
            src = f.read()
        for rx, into in ((CODE_RED, red), (CODE_HINT, hint), (CODE_RIGHTS, rights)):
            for m in rx.finditer(src):
                k = f"{rel}:{m.group(1) or 'MENTION_RE'}"
                if into is not rights or k not in red:
                    into.setdefault(k, src.count("\n", 0, m.start()) + 1)
    return red, hint, rights


def blocks(src):
    """[(start, end)] of the top-level statements of a file: a block runs from a line that starts in column 0 (no comment, no
    closing bracket) to the next one."""
    starts = [m.start() for m in re.finditer(r"^(?![ \t\n#/)\]}*@])", src, re.M)] + [len(src)]
    return list(zip(starts, starts[1:]))


def filter_defs(rel, src):
    """{'file:name': line} of the filter evaluators / condition dialogs of a file that do not use the core's filter (#5523)."""
    rx = FLT_PY if rel.endswith(".py") else FLT_JS
    bl = blocks(src)
    cut = lambda b: re.sub(r"(?m)(#|//)[^\n]*$", "", src[b[0]:b[1]])  # noqa: E731 - a comment naming kflt_ uses nothing
    users = [b for b in bl if "kflt_" in cut(b) or len(set(FLT_CAT.findall(cut(b)))) >= 2]
    out = {}
    for m in rx.finditer(src):
        name = m.group(2)
        own = next((b for b in bl if b[0] <= m.start() < b[1]), (0, 0))
        if own in users and "kflt_" in cut(own):
            continue  # its block calls the core
        word = re.compile(r"(?<![\w.$])" + re.escape(name) + r"\b")
        if sum(len(word.findall(cut(b))) for b in users) > (own in users):
            continue  # handed to the core (kflt_where's cnd, a catalog's cond / old): named once more than its definition
        out.setdefault(f"{rel}:{name}", src.count("\n", 0, m.start()) + 1)
    return out


def filter_code(root=ROOT):
    """{'file:name': line} of the filter rule (#5523) over kalmido/**/*.py and static/js/*.js, without the core's filter."""
    out = {}
    paths = glob.glob(os.path.join(root, "kalmido", "**", "*.py"), recursive=True) + glob.glob(os.path.join(root, "static", "js", "*.js"))
    for p in sorted(paths):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel in FLT_CORE:
            continue
        with open(p, encoding="utf-8") as f:
            out.update(filter_defs(rel, f.read()))
    return out


def load_allow(root=ROOT):
    with open(os.path.join(root, ALLOW), encoding="utf-8") as f:
        return json.load(f)


def findings(root=ROOT, srcs=None, allow=None, code=True):
    """(findings, hints) as lines. srcs / allow: texts and an allow dict of their own (the test's fragments)."""
    srcs = sources(root) if srcs is None else srcs
    allow = load_allow(root) if allow is None else allow
    ok_tab, ok_code, ok_search = allow.get("tables", {}), allow.get("code", {}), allow.get("search_functions", {})
    ok_rights = allow.get("rights", {})
    bad, hints, seen = [], [], set()
    added = added_cols(srcs)
    for name, (path, line, cols) in sorted(tables(srcs).items()):
        kind = looks_like_share(name, cols, added.get(name, ())) or looks_like(name, cols)
        if kind == "a share":
            seen.add(name)
            if name not in ok_tab:
                bad.append(f"check_core_crosscut: table {name} ({path}:{line}) looks like a share or role table of its own - who "
                           f"may do what is the shared core's (fs_shares, obj_role / obj_share, docs/dev/kern.md section 3); an "
                           f"exception only with its reason in {ALLOW}")
            continue
        if not kind:
            continue
        seen.add(name)
        if name not in ok_tab:
            bad.append(f"check_core_crosscut: table {name} ({path}:{line}) looks like {kind} - the shared core has it (obj_*, "
                       f"docs/dev/kern.md 'Cross-cutting parts'); an exception only with its reason in {ALLOW}")
    for name in sorted(set(ok_tab) - seen):
        bad.append(f"{ALLOW}: table {name} is gone or no longer looks like a cross-cutting part or a share - take the line out")
    if code:
        red, hint, rights = code_defs(root)
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
                hints.append(f"hint: {n} ({f}:{ln}) is a search of its own - register it with the one search (kalmido/core/srchreg.py srch_register)")
        for k in sorted(set(ok_search) - set(hint)):
            bad.append(f"{ALLOW}: search_functions {k} is gone - take the line out")
        for k, ln in sorted(rights.items()):
            if k not in ok_rights:
                f, n = k.rsplit(":", 1)
                bad.append(f"check_core_crosscut: {n} ({f}:{ln}) is a rights check of its own - who may do what comes from the "
                           f"core (core/access.py AccessCtx, obj_role / obj_need, docs/dev/kern.md section 3); an exception only "
                           f"with its reason in {ALLOW} rights")
        for k in sorted(set(ok_rights) - set(rights)):
            bad.append(f"{ALLOW}: rights {k} is gone - take the line out")
        flt, ok_flt = filter_code(root), allow.get("filter", {})
        for k, ln in sorted(flt.items()):
            if k not in ok_flt:
                f, n = k.rsplit(":", 1)
                bad.append(f"check_core_crosscut: {n} ({f}:{ln}) looks like a filter of its own - conditions are read once, by the "
                           f"core's filter (kalmido/core/filters.py kflt_where / kflt_match, static/js/fltkern.js + fltdlg.js, "
                           f"docs/dev/kern.md 'Filter'): describe the fields in a catalog / a cnd function and hand them to "
                           f"kflt_*; an exception only with its reason in {ALLOW} filter")
        for k in sorted(set(ok_flt) - set(flt)):
            bad.append(f"{ALLOW}: filter {k} is gone or uses the core's filter now - take the line out")
    return bad, hints


if __name__ == "__main__":
    root = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else ROOT
    out, hints = findings(root)
    for x in hints + out:
        print(x)
    if "-v" in sys.argv or out:
        print(f"check_core_crosscut: {len(load_allow(root).get('tables', {}))} allowed table(s), {len(out)} finding(s)")
    sys.exit(1 if out else 0)
