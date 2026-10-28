"""2.371 (#3150): tags of knowledge pages and the ```abfrage block (a live query over the pages of a space).

A tag is a word after "#" in the text that starts with a letter (#projekt, #kunde/nord; #123 stays a task reference, a #
inside a word, an address, code or a [[link]] is no tag) or an entry of "tags:" / "tag:" in the frontmatter ([a, b], "a, b"
or "a b", the # optional). Tags are compared in lower case; the first spelling found is the one shown.

The server keeps no tag in plain text: the word index (wksearch.py wiki_words) gets one HMAC hash per tag ('t:' + the
same keyed hash as the words, per space) on every save, so "pages with tag X" is found without opening a text. The names
of the tag list are read from the texts of the pages that have a tag hash, in memory only (like the search's snippets),
never stored or logged. Pages whose index is older than the page (or older than this release: the row 'tv:1' is missing)
are read at once and indexed again by the background job (wks_job_add). Spaces with the lock: the server has neither
texts nor hashes -- the browser does the same with the texts it opened (wktags.js, same rules).

The ```abfrage block (English ```query): one "key: value" per line, nothing else (no scripting):
    tag: projekt, kunde          pages with every tag named (several lines: all of them)
    ordner: Kunden               pages in that folder (and below)
    eigenschaft: status = offen  frontmatter key with that value (a list: one of its entries); without "= …": has the key
    zeige: seiten | aufgaben     the pages (default) or the open checkboxes "- [ ] …" of those pages
    sortiere: name | geändert | erstellt | <key> [absteigend]
    grenze: 20                   at most this many rows (default 50, at most 200)
    als: liste | tabelle         a list (default) or a table; spalten: status, kunde = the table's columns
English keys: tag, folder, property, show (pages | tasks), sort (name | updated | created | <key> [desc]), limit, as (list |
table), columns. The page holding the block and the templates are never in its result. The reader sees only pages they
may read (wkf_visible_sql: the space's pages, through a share only the shared ones).
"""
import re

from flask import jsonify, request

from ..accounts.session import me
from ..core.access import Denied
from ..core.config import app
from ..core.db import db
from ..core.errors import BadInput
from ..core.i18n import tr
from ..collab.liste2e import le2e_is_cipher
from .pages import WIKI_INDEX_MAX, WIKI_TEMPLATES, wiki_dict, wiki_frontmatter, wiki_need, wiki_space, wiki_space_key
from .wikie2e import wke_mode, wke_page_mode
from .wkhist import wsb_body_or
from .wksearch import wks_job_add, wks_key_state, wks_unindexed, wks_ws

WKT_MAX = 50            # tags per page
WKT_LIST_MAX = 300      # tags in the list of a space
WKQ_LIMIT, WKQ_LIMIT_MAX = 50, 200
WKQ_OPEN_MAX = 500      # pages whose text a query with "zeige: aufgaben" opens
WKT_ONE = re.compile(r"[^\W\d_][\w/-]{0,59}")
WKT_RE = re.compile(r"(?<![\w&/#\\])#([^\W\d_][\w/-]{0,59})")
_WKT_CUT = (re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S),             # the frontmatter
            re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[ \t]*$|\Z)", re.S | re.M),  # code blocks (also ```abfrage)
            re.compile(r"`[^`\n]*`"),                                                          # inline code
            re.compile(r"\[\[[^\[\]\n]*\]\]"),                                                 # [[links]] (Page#Section)
            re.compile(r"\]\([^()\s]*\)"),                                                     # [label](address#anchor)
            re.compile(r"<[^<>\n]{1,500}>"))                                                   # html, <address>
WKQ_TASK = re.compile(r"^[ \t]*(?:>[ \t]?)*[-*+][ \t]+\[ \][ \t]+(.+?)[ \t]*$", re.M)
_WKQ_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\1[ \t]*$|\Z)", re.S | re.M)
WKQ_KEYS = {"tag": "tag", "tags": "tag", "ordner": "folder", "folder": "folder", "eigenschaft": "prop", "property": "prop",
            "zeige": "show", "show": "show", "sortiere": "sort", "sort": "sort", "grenze": "limit", "limit": "limit",
            "als": "as", "as": "as", "spalten": "cols", "columns": "cols"}
WKQ_SHOW = {"seiten": "pages", "pages": "pages", "aufgaben": "tasks", "tasks": "tasks", "checkboxen": "tasks"}
WKQ_AS = {"liste": "list", "list": "list", "tabelle": "table", "table": "table"}
WKQ_SORT = {"name": "name", "geändert": "updated", "geaendert": "updated", "updated": "updated", "erstellt": "created",
            "created": "created"}
WKQ_DESC = {"absteigend": True, "desc": True, "aufsteigend": False, "asc": False}


def wkt_tags(text):
    """[(key, shown)] of a text in the order found: the frontmatter's tags first, then the #tags of the text (WKT_MAX)."""
    out = {}

    def add(t):
        t = t.strip().lstrip("#").rstrip("/-")
        if t and WKT_ONE.fullmatch(t) and len(out) < WKT_MAX:
            out.setdefault(t.lower(), t)
    text = str(text or "")
    fm = wiki_frontmatter(text)
    for k in ("tags", "tag"):
        v = fm.get(k)
        for x in (v if isinstance(v, list) else re.split(r"[,\s]+", v or "")):
            add(x)
    s = text[:500_000]
    for rx in _WKT_CUT:
        s = rx.sub(" ", s)
    for m in WKT_RE.finditer(s):
        add(m.group(1))
    return list(out.items())


def wkt_hash(c, ws, key):
    from ..docs.store import _h, _index_key
    return "t:" + _h(_index_key(c, ws), "t:" + key)


def wkt_hashes(c, ws, text):
    """The index rows of the tags of a text (wksearch.wks_index adds them to the words)."""
    return {wkt_hash(c, ws, k) for k, _ in wkt_tags(text)}


def _space_w(oid, uid):
    return ("p.org_id=?", [oid]) if oid else ("p.org_id IS NULL AND p.owner_id=?", [uid])


def _late(c, oid, owner):
    """{page id: row} of the space's pages whose index (words + tags) is not current: read now, indexed in the background."""
    w, a = _space_w(oid, owner)
    rows = {r["id"]: r for r in wks_unindexed(c, w, a, wks_key_state(c, oid, None if oid else owner))}
    if rows:
        wks_job_add(oid, None if oid else owner)
    return rows


def _text(c, r):
    t = wsb_body_or(c, r)
    return "" if le2e_is_cipher(t) else t


def wkt_space_rows(c, oid, owner, uid, keys=None):
    """(rows, texts): the page rows (p.*) of a space (oid, or the private one of owner) that uid may read and that have every
    tag of keys (None: every page that has a tag at all), without the templates and pages of the lock; texts = {page id:
    text} of the pages read now (not indexed yet)."""
    from .wkfolder import wkf_visible_sql
    w, a = _space_w(oid, owner)
    late = _late(c, oid, owner)
    ws = wks_ws(oid, None if oid else owner)
    if keys:
        hs = [wkt_hash(c, ws, k) for k in keys]
        cond = " AND ".join(["EXISTS (SELECT 1 FROM wiki_words x WHERE x.page_id=p.id AND x.h=?)"] * len(hs))
    else:
        hs, cond = [], "EXISTS (SELECT 1 FROM wiki_words x WHERE x.page_id=p.id AND x.h LIKE 't:%')"
    vis = wkf_visible_sql(c, uid)
    sql = (f"SELECT p.* FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} AND left(p.path, 5)<>'e2e1:' AND {vis} AND ")
    rows = {r["id"]: r for r in c.execute(sql + f"({cond}) ORDER BY lower(p.path) LIMIT {WIKI_INDEX_MAX}", [*a, *hs])
            if r["id"] not in late}
    if late:  # the pages not indexed yet: their tags from the text read now
        ids = sorted(late)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            for r in c.execute(sql + f"p.id IN ({','.join('?' * len(part))})", [*a, *part]):
                t = _text(c, r)
                have = {k for k, _ in wkt_tags(t)}
                if (have >= set(keys)) if keys else have:
                    rows[r["id"]] = r
                    late[r["id"]] = t
    out = [r for r in rows.values() if not r["path"].lower().startswith(WIKI_TEMPLATES)]
    return out, {i: t for i, t in late.items() if isinstance(t, str)}


@app.get("/api/wiki/tags")
def wkt_list():
    """?space=private|org:<id> -- {tags: [{tag, n}]} the tags of the space's pages (most used first); with &tag=<name> the
    pages that have it instead: {tag, pages: [{id, path, updated_at}]}. A space with the lock: {e2e: true} (the browser)."""
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"))
    if wke_mode(c, oid, uid)[0]:
        return jsonify(space=wiki_space_key(oid), e2e=True, tags=[], pages=[])
    tag = str(request.args.get("tag") or "").strip().lstrip("#")[:60]
    if tag:
        if not WKT_ONE.fullmatch(tag):
            raise BadInput(tr("Invalid value: {0}", "tag"))
        rows, _ = wkt_space_rows(c, oid, uid, uid, [tag.lower()])
        rows.sort(key=lambda r: r["path"].lower())
        return jsonify(space=wiki_space_key(oid), tag=tag, pages=[{"id": r["id"], "path": r["path"], "updated_at": r["updated_at"]} for r in rows])
    rows, texts = wkt_space_rows(c, oid, uid, uid)
    n, shown = {}, {}
    for r in rows:  # the names: from the texts, in memory only
        for k, t in wkt_tags(texts[r["id"]] if r["id"] in texts else _text(c, r)):
            n[k] = n.get(k, 0) + 1
            shown.setdefault(k, t)
    tags = sorted(n, key=lambda k: (-n[k], k))[:WKT_LIST_MAX]
    return jsonify(space=wiki_space_key(oid), tags=[{"tag": shown[k], "n": n[k]} for k in tags])


# ---- the ```abfrage block
def wkq_parse(text):
    """The query of a block: {tags, folder, props: [(key, value | None)], show, sort, desc, limit, as, cols, errors}."""
    q = {"tags": [], "folder": "", "props": [], "show": "pages", "sort": "name", "desc": False, "limit": WKQ_LIMIT,
         "as": "list", "cols": [], "errors": []}
    for ln in str(text or "").splitlines()[:40]:
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        m = re.match(r"^([^\W\d_]\w*)\s*:\s*(.*)$", s)
        k = WKQ_KEYS.get(m.group(1).lower()) if m else None
        if not k:
            q["errors"].append(s[:80])
            continue
        v = m.group(2).strip()
        if k == "tag":
            for x in re.split(r"[,\s]+", v):
                x = x.strip().lstrip("#").rstrip("/-")
                if x and WKT_ONE.fullmatch(x) and x.lower() not in q["tags"]:
                    q["tags"].append(x.lower())
        elif k == "folder":
            q["folder"] = v.strip("/ ").lower()
        elif k == "prop":
            pk, eq, pv = v.partition("=")
            if pk.strip():
                q["props"].append((pk.strip()[:40], pv.strip().strip("\"'").lower() if eq else None))
        elif k == "show" and v.lower() in WKQ_SHOW:
            q["show"] = WKQ_SHOW[v.lower()]
        elif k == "as" and v.lower() in WKQ_AS:
            q["as"] = WKQ_AS[v.lower()]
        elif k == "sort" and v:
            parts = v.split()
            if len(parts) > 1 and parts[-1].lower() in WKQ_DESC:
                q["desc"] = WKQ_DESC[parts.pop().lower()]
            w = " ".join(parts)
            q["sort"] = WKQ_SORT.get(w.lower(), "p:" + w[:40])
        elif k == "limit":
            try:
                q["limit"] = max(1, min(WKQ_LIMIT_MAX, int(v)))
            except ValueError:
                q["errors"].append(s[:80])
        elif k == "cols":
            q["cols"] = [x.strip()[:40] for x in v.split(",") if x.strip()][:8]
        else:
            q["errors"].append(s[:80])
    return q


def _attr(attrs, key):
    """The value of a frontmatter key (case of the key ignored)."""
    for k, v in (attrs or {}).items():
        if k.lower() == key.lower():
            return v
    return None


def wkq_match(q, path, attrs):
    """Does a page (path, attrs) pass the folder and the properties of q (the tags are checked by the caller)?"""
    lp = path.lower()
    if q["folder"] and not lp.startswith(q["folder"] + "/"):
        return False
    for k, v in q["props"]:
        a = _attr(attrs, k)
        if a in (None, "", []):
            return False
        if v is not None and v not in ([str(x).lower() for x in a] if isinstance(a, list) else [str(a).lower()]):
            return False
    return True


def wkq_sort_key(q, d):
    s = q["sort"]
    if s == "name":
        return (0, d["path"].lower())
    if s in ("updated", "created"):
        return (0, d[s + "_at"] or "")
    a = _attr(d["attrs"], s[2:])
    a = ", ".join(map(str, a)) if isinstance(a, list) else a
    return (1, "") if a in (None, "") else (0, str(a).lower())  # without the key: at the end


def wkq_tasks(text):
    """[(line number, text)] of the open checkboxes of a text (not in code blocks)."""
    t = _WKQ_FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), str(text or ""))
    return [(t.count("\n", 0, m.start()) + 1, m.group(1)[:300]) for m in WKQ_TASK.finditer(t)]


@app.get("/api/wiki/query")
def wkq_route():
    """?page=<id of the page with the block>&q=<the block's text> -- its result (module docstring):
    {show, as, cols, pages: [{id, path, updated_at, created_at, attrs}], tasks: [{page_id, path, line, text}], total, more,
    errors}; a page of a space with the lock: {e2e: true} (the browser runs the query)."""
    c = db()
    uid = me()
    try:
        pid = int(request.args.get("page") or 0)
    except ValueError:
        pid = 0
    if not pid:
        raise Denied(404)
    r = wiki_need(c, pid)
    if wke_page_mode(c, r) or r["path"].startswith("e2e1:"):
        return jsonify(e2e=True, pages=[], tasks=[], total=0, more=False, errors=[])
    q = wkq_parse(str(request.args.get("q") or "")[:2000])
    oid = r["org_id"]
    if q["tags"]:
        rows, texts = wkt_space_rows(c, oid, r["owner_id"], uid, q["tags"])
    else:
        from .wkfolder import wkf_visible_sql
        w, a = _space_w(oid, r["owner_id"] or uid)
        rows = [x for x in c.execute(f"SELECT p.* FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} AND left(p.path, 5)<>'e2e1:' "
                                     f"AND {wkf_visible_sql(c, uid)} ORDER BY lower(p.path) LIMIT {WIKI_INDEX_MAX}", a)
                if not x["path"].lower().startswith(WIKI_TEMPLATES)]
        texts = {}
    ds = [d for d in (wiki_dict(x, full=False) for x in rows if x["id"] != pid) if wkq_match(q, d["path"], d["attrs"])]
    from .wkfolder import wkf_base, wkf_shared, wkf_shown_path
    if wkf_base(c, uid, r) is None:  # read through a share: the paths from the share down (wiki_get)
        info = wkf_shared(c, uid)
        byid = {x["id"]: x for x in rows}
        for d in ds:
            d["path"] = wkf_shown_path(c, uid, byid[d["id"]], info)
    ds.sort(key=lambda d: (wkq_sort_key(q, d), d["path"].lower()), reverse=q["desc"])
    if q["desc"]:  # pages without the sort key stay at the end
        ds.sort(key=lambda d: wkq_sort_key(q, d)[0])
    out = dict(show=q["show"], cols=q["cols"], errors=q["errors"], pages=[], tasks=[])
    out["as"] = q["as"]
    if q["show"] == "tasks":
        byid = {x["id"]: x for x in rows}
        tasks = []
        for d in ds[:WKQ_OPEN_MAX]:
            t = texts[d["id"]] if d["id"] in texts else _text(c, byid[d["id"]])
            tasks += [{"page_id": d["id"], "path": d["path"], "line": n, "text": s} for n, s in wkq_tasks(t)]
        out.update(tasks=tasks[:q["limit"]], total=len(tasks), more=len(tasks) > q["limit"])
    else:
        keep = {k.lower() for k in q["cols"]} | {k.lower() for k, _ in q["props"]}
        out.update(pages=[{"id": d["id"], "path": d["path"], "updated_at": d["updated_at"], "created_at": d["created_at"],
                           "attrs": {k: v for k, v in d["attrs"].items() if k.lower() in keep}} for d in ds[:q["limit"]]],
                   total=len(ds), more=len(ds) > q["limit"])
    return jsonify(out)
