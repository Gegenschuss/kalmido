"""2.1050.0 (#5819, decided 12.11.2026): the help of the running version for agents -- the user documentation (docs/*.md, shipped
in the image) searchable and readable through API v1 / MCP, so an agent looks a question about using Kalmido up instead of
guessing a menu path.

- Search: the kind "help" of the one search registry (core/srchreg.py): GET /api/v1/search?kind=help&q= -> {data: [{key, file,
  title, path, snippet}], more}. A plain word search over headings and text (word beginnings, case and accents do not
  matter), no language model. Not part of ?kind=all (that searches the person's data).
- Read: GET /api/v1/help/section?key=<file>#<heading> -> one section up to the next heading of the same or a higher rank,
  at most HELP_READ_MAX characters (then truncated + its sub-sections as parts). The key is looked up in the index built
  from the files on disk: no file name or path of the request ever reaches the file system; an unknown key answers 404.
- Overview: GET /api/v1/help -> the feature list (docs/FEATURES.md) in short form per area and the second-rank headings of
  every area file, so an agent knows what exists before it searches.
- No own scope: every token with read (the documentation is public in the repository). The operator files (HELP_OPERATOR:
  self-hosting, environment, upgrading, single sign-on, architecture, the module glossary, the technical pack catalogue and
  the privacy templates) only for an instance admin (a token also needs admin-read): for anybody else they do not exist (404,
  never in a hit).
The index is built once, on first use, from HELP_DIR (the docs folder next to app.py); docs/dev/ and anything below
docs/ is never read.
"""
import glob
import math
import os
import re
import threading
import unicodedata

from flask import g, jsonify, request

from ..core.config import app, APP_DIR, APP_VERSION
from ..core.errors import BadInput, Denied
from ..core.i18n import lang, LANGS, md_plain, tr
from ..core.srchreg import srch_q, srch_register
from .common import v1_args, v1_view

HELP_DIR = os.path.join(APP_DIR, "docs")  # the image: /app/docs (Dockerfile), a checkout: docs/
# the operator's files: running a server, its settings and internals -- only for an instance admin
HELP_OPERATOR = frozenset(("self-hosting", "env", "upgrading", "oidc", "architecture", "glossar", "packs", "privacy-template",
                           "privacy-assistant-template"))
HELP_READ_MAX = 16000   # characters of one section answer
HELP_HITS = 8           # default hits of a search (?limit 1..20)
HELP_HITS_MAX = 20
HELP_SNIP = 240         # characters of a hit's snippet
HELP_STOP = frozenset("""a an and are as at be by can do does for from how i in into is it its me my of on or the this that to was
    what when where which who why will with you your use using do der die das und ich wie wo was ein eine einen mit für fuer im in
    ist kann man""".split())
_HELP = {"idx": None}
_HELP_LOCK = threading.Lock()
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BOLD_LINE = re.compile(r"^\*\*([^*]{2,80})\*\*\s*$")   # docs/FEATURES.md: an area as a bold line ("**Projects**")
_WORD = re.compile(r"[a-z0-9]+")


def hlp_fold(s):
    """lower case, accents and umlauts folded (ä -> a), the form the index and the query share."""
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss")


def hlp_slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", hlp_fold(md_plain(s)))).strip("-")[:80] or "section"


def hlp_stem(w):
    if len(w) > 5 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _hlp_parse(fkey, fname, text):
    """The sections of one file: [{key, file, fkey, title, level, path, start, end, own_end}] (lines; end = the next heading of
    the same or a higher rank, own_end = the next heading at all). Headings inside code fences do not count."""
    lines = text.split("\n")
    heads, fence, lvl_now = [], False, 0
    for i, ln in enumerate(lines):
        if _FENCE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        m = _HEAD.match(ln)
        if m:
            lvl_now = len(m.group(1))
            heads.append((i, lvl_now, m.group(2).strip()))
            continue
        b = _BOLD_LINE.match(ln)
        if b and lvl_now:
            heads.append((i, min(6, lvl_now + 1), b.group(1).strip()))
    out, seen, stack = [], {}, []
    for n, (i, lvl, title) in enumerate(heads):
        end = next((j for j, l2, _ in heads[n + 1:] if l2 <= lvl), len(lines))
        own_end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        stack.append((lvl, md_plain(title)))
        base = fkey if n == 0 and lvl == 1 else f"{fkey}#{hlp_slug(title)}"
        k = base
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            k = f"{base}-{seen[base]}"
        out.append({"key": k, "file": fname, "fkey": fkey, "title": md_plain(title), "level": lvl, "path": [t for _, t in stack],
                    "start": i, "end": end, "own_end": own_end})
    if not heads:  # a file without any heading: one section, the file
        out.append({"key": fkey, "file": fname, "fkey": fkey, "title": fname, "level": 1, "path": [fname], "start": 0,
                    "end": len(lines), "own_end": len(lines)})
    return lines, out


def hlp_index():
    """{"files": {fkey: {file, title, lines, sections}}, "by_key": {key: section}, "units": [...], "vocab": set} -- built once."""
    if _HELP["idx"] is not None:
        return _HELP["idx"]
    with _HELP_LOCK:
        if _HELP["idx"] is not None:
            return _HELP["idx"]
        files, by_key, units, vocab = {}, {}, [], set()
        for fn in sorted(glob.glob(os.path.join(HELP_DIR, "*.md"))):
            fname = os.path.basename(fn)
            fkey = hlp_slug(fname[:-3])
            try:
                with open(fn, encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            lines, secs = _hlp_parse(fkey, fname, text)
            files[fkey] = {"file": fname, "key": fkey, "title": secs[0]["title"] if secs else fname, "lines": lines, "sections": secs,
                           "operator": fkey in HELP_OPERATOR}
            for s in secs:
                by_key[s["key"]] = s
                body = "\n".join(lines[s["start"] + 1:s["own_end"]])
                words = {}
                for w in _WORD.findall(hlp_fold(body)):
                    words[w] = words.get(w, 0) + 1
                head = set(_WORD.findall(hlp_fold(" ".join(s["path"]))))
                vocab.update(words)
                vocab.update(head)
                units.append({"s": s, "words": words, "head": head, "own": set(_WORD.findall(hlp_fold(s["title"]))), "body": body})
        _HELP["idx"] = {"files": files, "by_key": by_key, "units": units, "vocab": vocab}
        return _HELP["idx"]


def hlp_admin():
    """True for an instance admin (a token: also with the scope admin-read) -- the reader of the operator files."""
    u = g.get("user")
    if not u or not u["is_admin"]:
        return False
    return g.get("auth_via") != "token" or "admin-read" in (g.get("scopes") or set())


def _hlp_open(s, admin):
    return admin or s["fkey"] not in HELP_OPERATOR


def hlp_terms(q):
    terms = []
    for w in _WORD.findall(hlp_fold(q)):
        if w in HELP_STOP or len(w) < 2:
            continue
        w = hlp_stem(w)
        if w not in terms:
            terms.append(w)
    return terms[:12]


def _hlp_snippet(body, words):
    plain = re.sub(r"\s+", " ", md_plain(body)).strip()
    low = hlp_fold(plain)
    pos = min((p for p in (re.search(r"\b" + re.escape(w), low) for w in words) if p), key=lambda m: m.start(), default=None)
    at = pos.start() if pos else 0
    a = max(0, at - HELP_SNIP // 3)
    s = plain[a:a + HELP_SNIP]
    return ("…" if a else "") + s + ("…" if a + HELP_SNIP < len(plain) else "")


def hlp_search(q, n=HELP_HITS, admin=False):
    """The best n sections for the words of q: [{key, file, title, path, snippet}]. Each word matches word beginnings; a
    section needs most of the words (all of one or two), ranked by how many words it has, then by weight: a rare word
    counts more than a common one (task, project), the section's own heading more than the headings above it and the text."""
    idx = hlp_index()
    terms = hlp_terms(q)
    if not terms:
        return []
    need = len(terms) if len(terms) <= 2 else math.ceil(len(terms) * 0.6)
    match = {t: {w for w in idx["vocab"] if w.startswith(t)} for t in terms}
    units = [u for u in idx["units"] if _hlp_open(u["s"], admin)]
    idf = {t: math.log(1 + len(units) / (1 + sum(1 for u in units if (u["head"] & match[t]) or not match[t].isdisjoint(u["words"]))))
           for t in terms}
    ranked = []
    for u in units:
        got, score, words = 0, 0.0, []
        for t in terms:
            hw = u["head"] & match[t]
            tw = [w for w in match[t] if w in u["words"]]
            if not hw and not tw:
                continue
            got += 1
            score += idf[t] * ((5 if u["own"] & match[t] else 1.5 if hw else 0) + min(5, sum(u["words"][w] for w in tw)) * 0.5)
            words += tw or list(hw)
        if got >= need:
            score /= 1 + 0.5 * max(0.0, math.log(max(1, len(u["body"])) / 3000))  # a long section (a whole route table) weighs less
            ranked.append((-got, -score, u["s"]["level"], u["s"]["key"], u, words))
    ranked.sort(key=lambda x: x[:4])
    return [{"key": u["s"]["key"], "file": u["s"]["file"], "title": u["s"]["title"], "path": u["s"]["path"],
             "snippet": _hlp_snippet(u["body"], words)} for *_, u, words in ranked[:n]]


def hlp_ui_terms(text, lg):
    """{English label: the label in the reader's language} of the interface words a section names (*Label*, the parts of
    "A > B > C" paths), from the app's own translations -- the agent explains the path in the words of the screen."""
    if lg == "en" or lg not in LANGS:
        return {}
    cand = set(re.findall(r"(?<![*\w])\*([^*\n]{2,60})\*(?!\*)", text))
    for m in re.finditer(r"[A-Z][\w &'/-]{1,40}(?:\s+>\s+\*?[A-Za-z][\w &'/:-]{1,40}\*?)+", text):
        cand.update(p.strip(" *") for p in m.group(0).split(">"))
    out = {}
    for c in sorted(cand):
        v = LANGS[lg].get(c)
        if isinstance(v, str) and v != c:
            out[c] = v
        if len(out) >= 60:
            break
    return out


def hlp_section(key, admin=False, lg="en"):
    """One section by its index key (404 for an unknown key or an operator file of a non-admin): {key, file, title, path,
    text, truncated, parts, ui_terms}."""
    idx = hlp_index()
    s = idx["by_key"].get(key) if isinstance(key, str) and len(key) <= 200 else None
    if s is None or not _hlp_open(s, admin):
        raise Denied(404)
    lines = idx["files"][s["fkey"]]["lines"]
    text, cut = "", False
    for ln in lines[s["start"]:s["end"]]:
        if len(text) + len(ln) + 1 > HELP_READ_MAX:
            cut = True
            break
        text += ln + "\n"
    parts = [{"key": x["key"], "title": x["title"]} for x in idx["files"][s["fkey"]]["sections"]
             if s["start"] < x["start"] < s["end"] and x["level"] == s["level"] + 1] if cut else []
    return {"key": s["key"], "file": s["file"], "title": s["title"], "path": s["path"], "text": text.rstrip("\n"),
            "truncated": cut, "parts": parts, "ui_terms": hlp_ui_terms(text, lg)}


def _hlp_short(item):
    s = re.sub(r"\s+", " ", md_plain(item)).strip()
    m = re.match(r"(.{20,140}?)(?::\s|\.\s|\s\(|;\s|$)", s)
    s = m.group(1) if m else s[:140]
    return s if len(s) <= 140 else s[:139] + "…"


def hlp_overview(admin=False):
    """What exists: the feature list in short form per area + the files with their second-rank headings."""
    idx = hlp_index()
    areas = []
    feat = idx["files"].get("features")
    if feat:
        for s in feat["sections"]:
            if s["level"] < 3:
                continue
            items = [ln[2:] for ln in feat["lines"][s["start"] + 1:s["own_end"]] if ln.startswith("- ")]
            areas.append({"area": s["title"], "key": s["key"], "items": [_hlp_short(x) for x in items]})
    files = [{"file": f["file"], "key": f["key"], "title": f["title"],
              "sections": [{"key": s["key"], "title": s["title"]} for s in f["sections"] if s["level"] == 2]}
             for f in idx["files"].values() if admin or not f["operator"]]
    return {"version": APP_VERSION, "features": areas, "files": files,
            "how": "search_help (GET /search?kind=help&q=) finds sections; read_help (GET /help/section?key=) reads one. "
                   "The documentation is English; explain a path in the words of the person's interface (ui_terms of a section)."}


def v1_help_search():
    """GET /api/v1/search?kind=help (the search registry): {data: [hits], more}."""
    a = v1_args(("q", "limit"))
    try:
        n = max(1, min(HELP_HITS_MAX, int(a.get("limit") or HELP_HITS)))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit")) from None
    hits = hlp_search(srch_q(a), n + 1, admin=hlp_admin())
    return jsonify(data=hits[:n], more=len(hits) > n)


srch_register("help", v1=v1_help_search)  # 2.1050.0 (#5819): no v1group -- ?kind=all stays the person's data


@app.get("/api/v1/help")
@v1_view
def v1_help_overview():
    v1_args(())
    return jsonify(hlp_overview(admin=hlp_admin()))


@app.get("/api/v1/help/section")
@v1_view
def v1_help_section():
    a = v1_args(("key", "lang"))
    lg = a.get("lang") or lang()
    if lg not in LANGS:
        raise BadInput(tr("Invalid value: {0}", "lang"))
    return jsonify(hlp_section((a.get("key") or "").strip(), admin=hlp_admin(), lg=lg))


def help_spec(paths, schemas, op, ok, errs, ref, q):
    schemas["HelpHit"] = {"type": "object", "properties": {
        "key": {"type": "string", "description": "The section's key for GET /help/section, e.g. api#scan-inboxes-folder-watcher"},
        "file": {"type": "string"}, "title": {"type": "string"},
        "path": {"type": "array", "items": {"type": "string"}, "description": "The headings from the file's title down to the section"},
        "snippet": {"type": "string", "description": "Plain text around the first hit"}}}
    T = "Help"
    paths["/help"] = {"get": op("Overview of the help (2.1050.0): the feature list per area in short form and the headings of every "
                                "documentation file", T, ok({"type": "object"}) | errs(),
                                desc="Every token with read. The operator files (self-hosting, environment, ...) only for an instance "
                                     "admin with admin-read.")}
    paths["/help/section"] = {"get": op("One section of the help by its key (2.1050.0)", T, ok({"type": "object", "properties": {
        "key": {"type": "string"}, "file": {"type": "string"}, "title": {"type": "string"},
        "path": {"type": "array", "items": {"type": "string"}}, "text": {"type": "string", "description": "Markdown up to the next heading "
                                                                                                            "of the same rank"},
        "truncated": {"type": "boolean"}, "parts": {"type": "array", "items": {"type": "object"}, "description": "truncated: the "
                                                                                                                 "sub-sections to read one by one"},
        "ui_terms": {"type": "object", "description": "English interface labels of the text -> the same label in lang"}}})
        | errs("400", "404"), [{**q("key", "The key of a hit of GET /search?kind=help or of GET /help"), "required": True},
                               q("lang", "Language of ui_terms (default: the token's person)")],
        desc="Only keys of the index: an unknown key (or a file name, a path) answers 404.")}
