"""2.123.0 A (#2106): the search of the knowledge pages over a word index instead of ILIKE on the text (the text is sealed
since #2105). 2.1002.0 (#5279): the shared word index obj_search_words (core/objwords.py, kind 'wiki_page'; was wiki_words)
holds HMAC prefix hashes of the folded words of a page's text -- the same functions and per-space keys as the documents
(docs/store.py: the space 'o<org>' / 'u<owner>' of doc_ws) -- and one row 'u:<updated_at>' = the state the index was built from. A save indexes its page at once; pages saved elsewhere
(an older version of the app, a [[link]] renamed, a move, an import) are indexed again by the next search that covers
their space (at most WKS_CATCH_UP per space and search). Spaces with the lock are searched in the browser (wikie2e.js).
2.139.0 C (#2386): a page whose text cannot be opened (its key is missing) is found by its name only and marked
'x:<updated_at>:<key state>' instead -- the next search reads it again once the key state of its space changed (a key
restored with the recovery key, a rotation, another server key), never at every search while the key stays missing.

A page matches when every query word is in its name (part of a word, as before) or in its text (2.1002.0 #5279: at the
start of a word, any length of 2+, umlauts with ae / oe / ue the same, core/objwords.py). Ranking: words in the name first,
then words in the text, then the newest. 2.1002.0 (#5279, question 15): pages a share of the shared core opens (a folder or a
page shared with the person, wkf_shared_ids) are searched by name and text too, not only the spaces of the person.
2.376 (#3292): the hits of the page shown (offset / limit) carry a short plain text snippet around the first word found in
the text (wks_snippets): opened in memory only, never stored, indexed or logged; spaces with the lock cut theirs in the
browser (wkhist.js wks_snip, same rules).
"""
import re

from ..accounts.bgjobs import bgj_add, bgj_fn
from ..collab.liste2e import le2e_is_cipher
from ..core.db import connect
from ..core.orgcrypt import _kek, _kek_check, _row, OrgCryptError  # 2.149.0 G (#2517): pulled up from functions
from .wkhist import WikiUnreadable, wkh_body  # 2.280.0 C (#3114): loads before this module (kalmido/__init__.py ORDER)
from .wkhist import wkh_sid, wsb_body_or  # 2.369.5 (#2517): pulled up from functions
from .wikie2e import wke_mode, wke_open_sql  # 2.369.5 (#2517): pulled up from functions; 2.981.0 (#5278): + wke_open_sql
from .pages import wiki_may_read, wiki_space_key  # 2.981.0 (#5278)
from ..core.objsearch import osr_ids_sql  # 2.981.0 (#5278)
from ..core.access import live_sql  # 2.981.0 (#5278)
from .wkfolder import wkf_shared_ids  # 2.1002.0 (#5279)
from ..core.objwords import OSW_MARK, osw_drop, osw_put, osw_term_hits, osw_terms, osw_words  # 2.1002.0 (#5279)

WKS_CATCH_UP = 300   # pages indexed again per space and search
WKS_LIMIT, WKS_LIMIT_MAX = 30, 100
WKS_SNIP = 180       # 2.376 (#3292): characters of a snippet (about two lines)


def wks_ws(oid, owner):
    from ..docs.store import doc_ws  # a later module (kalmido/__init__.py ORDER): imported at call time
    return doc_ws(oid, owner)


def wks_key_state(c, oid, owner):
    """2.139.0 C (#2386): a short mark of the key a space's texts are sealed with (its key row and the current server key):
    it changes with every key event, so pages that could not be read are tried again then."""
    import hashlib
    sid = wkh_sid(oid, owner)
    if not sid:
        return "0"
    try:
        kek = _kek()
        r = _row(c, sid)
        s = "|".join(str(x) for x in (tuple(r) if r is not None else ("none",))) + "|" + (_kek_check(kek, sid) if kek else "")
    except OrgCryptError:
        s = "error"
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def wks_index(c, pid, oid, owner, text, at, unreadable=None):
    """The word index of page pid (plain text, the page's updated_at after the save). unreadable = the key state of the space
    when the text could not be opened (2.139.0 C #2386): no words, the mark 'x:' to try it again after a key event.
    2.1002.0 (#5279): in the shared word index (core/objwords.py osw_put, kind 'wiki_page')."""
    if unreadable is not None:
        osw_put(c, "wiki_page", pid, more={f"x:{at}:{unreadable}"})
        return
    if le2e_is_cipher(text):
        osw_drop(c, "wiki_page", [pid])
        return
    from .wktags import wkt_hashes  # 2.371 (#3150): the tags as hashes too
    ws = wks_ws(oid, owner)
    osw_put(c, "wiki_page", pid, ws, text or "", more=wkt_hashes(c, ws, text) | {"u:" + str(at)})


def wks_catch_up(c, w, a, limit=WKS_CATCH_UP, oid=None, owner=None):
    """Index the pages of a space (condition w / args a on wiki_pages p; oid / owner = the space) whose index is missing or
    older than the page -- or (2.139.0 C #2386) that could not be read under an earlier key state of the space."""
    ks = wks_key_state(c, oid, owner)
    rows = wks_unindexed(c, w, a, ks, limit)
    for r in rows:
        try:
            text, bad = wkh_body(c, r), None
        except WikiUnreadable:  # 2.126.2 B (#2358): unreadable = title only; 2.139.0 C (#2386): again after a key event
            text, bad = "", ks
        wks_index(c, r["id"], r["org_id"], r["owner_id"], text, r["updated_at"], unreadable=bad)
    return len(rows)


def wks_unindexed(c, w, a, ks, limit=WKS_CATCH_UP):
    """2.280.0 C (#3114): the pages of a space (w / a on wiki_pages p) whose word index is missing or older than the page
    (or that could not be read under an earlier key state ks) -- the rows wks_catch_up indexes. 2.371 (#3150): an index
    without the row 'tv:1' (made before the tags) counts as missing; 2.1002.0 (#5279): without the shared index's mark
    OSW_MARK (made before its rules: umlauts with ae, short word starts), so those pages are indexed once more."""
    return c.execute(f"SELECT p.id, p.org_id, p.owner_id, p.body, p.updated_at FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} "
                     "AND left(p.path, 5)<>'e2e1:' AND NOT EXISTS (SELECT 1 FROM obj_search_words x WHERE x.kind='wiki_page' "
                     "AND x.ref_id=p.id AND (x.h='x:' || p.updated_at || ':' || CAST(? AS text) OR x.h='u:' || p.updated_at "
                     "AND EXISTS (SELECT 1 FROM obj_search_words y WHERE y.kind='wiki_page' AND y.ref_id=p.id AND y.h=?))) "
                     f"ORDER BY p.id LIMIT {int(limit)}", [*a, ks, OSW_MARK]).fetchall()


def wks_job_add(oid, owner):
    """2.280.0 C (#3114): the word index of a space made in the background (bg_jobs) instead of in the search's GET."""
    try:
        bgj_add("wiki:index", oid, owner, org_id=oid, user_id=owner, once=True)
    except Exception as e:  # noqa: BLE001 -- the search answers anyway; the next one asks again
        print("wiki index job not queued:", type(e).__name__, flush=True)


@bgj_fn("wiki:index")  # 2.280.0 C (#3114)
def wks_job(oid, owner):
    """The background run (own connection, role system, only this space's pages): everything not indexed yet, in steps."""
    c = connect()
    try:
        w, a = ("p.org_id=?", [oid]) if oid else ("p.org_id IS NULL AND p.owner_id=?", [owner])
        seen = set()  # 2.280.0 (#3114): a page that gets no mark (text still sealed, 'e2e1:') comes back - stop then
        while True:
            ks = wks_key_state(c, oid, owner)
            ids = {r["id"] for r in wks_unindexed(c, w, a, ks)}
            if not ids or ids <= seen:
                break
            seen |= ids
            wks_catch_up(c, w, a, oid=oid, owner=owner)
            c.commit()
        c.commit()
    finally:
        c.close()


def _wks_late(c, w, a, oid, owner):
    """{page id: its words} of the pages (w / a) whose index is missing or old, read now (at most WKS_CATCH_UP); the
    background job of the space is queued for them. 2.280.0 (#3114): sealed text = no words, as wks_index; unreadable =
    found by its name only."""
    late = {}
    for r in wks_unindexed(c, w, a, wks_key_state(c, oid, owner)):
        try:
            t = wkh_body(c, r)
            late[r["id"]] = set() if le2e_is_cipher(t) else set(osw_words(t))
        except WikiUnreadable:
            late[r["id"]] = set()
    if late:
        wks_job_add(oid, owner)
    return late


def _wks_opened(c, ws, ids):
    """{page id: its text} for the word index's check of a longer word (2.126.2 B #2358: unreadable = '')."""
    out = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in c.execute(f"SELECT id, org_id, owner_id, body FROM wiki_pages WHERE id IN ({','.join('?' * len(part))})", part):
            out[r["id"]] = wsb_body_or(c, r)
    return out


def _wks_rank(c, ws, rows, terms, late):
    """[(words in the name, words in the text, updated_at, id, row)] of rows (one space ws) that have every query term in
    the name (part of a word) or at a word start of the text (core/objwords.py osw_term_hits)."""
    from ..docs.rules import fold
    titles = {r["id"]: fold(r["path"]) for r in rows}
    inbody = osw_term_hits(c, "wiki_page", ws, list(titles), terms, _wks_opened, late)
    out = []
    for r in rows:
        pid, t = r["id"], titles[r["id"]]
        nt = nb = 0
        for ti, vs in enumerate(terms):
            in_t, in_b = any(v in t for v in vs), pid in inbody[ti]
            if not in_t and not in_b:
                break
            nt += in_t
            nb += in_b
        else:
            out.append((nt, nb, r["updated_at"], pid, r))
    return out


def wks_find(c, uid, spaces, q, limit=WKS_LIMIT, offset=0, shared=False):
    """(page rows ranked, total) of the open spaces (org ids, None = the private one of uid) for the query q; an empty query
    = the pages changed last. 2.280.0 C (#3114): the search writes nothing -- pages not indexed yet are read here (at most
    WKS_CATCH_UP per space, as the catch-up before) and indexed by a background job; only the names are read for every page,
    the full rows only for the hits of the answer. 2.1002.0 (#5279): was wks_search with a look-up of its own; the text part is
    the shared word index now (core/objwords.py osw_term_hits), this keeps the spaces, the names and the ranking; shared = also
    the pages of other spaces a share of the shared core opens for uid (question 15), each checked with wiki_may_read."""
    terms = osw_terms(q)
    hits = []
    for oid in spaces:
        if wke_mode(c, oid, uid)[0]:
            continue  # a space with the lock: searched in the browser
        w, a = ("p.org_id=?", [oid]) if oid else ("p.org_id IS NULL AND p.owner_id=?", [uid])
        late = _wks_late(c, w, a, oid, None if oid else uid) if terms else {}
        rows = c.execute(f"SELECT p.id, p.path, p.updated_at "
                         f"FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} AND left(p.path, 5)<>'e2e1:'", a).fetchall()
        if not terms:
            hits += [(0, 0, r["updated_at"], r["id"], r) for r in rows]
            continue
        hits += _wks_rank(c, wks_ws(oid, uid), rows, terms, late)
    if shared and terms:
        hits += _wks_shared(c, uid, spaces, terms)
    hits.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
    ids = [x[3] for x in hits[offset:offset + limit]]
    full = {}
    for i in range(0, len(ids), 500):  # the answer's rows in full
        part = ids[i:i + 500]
        full.update({r["id"]: r for r in c.execute(
            "SELECT p.id, p.org_id, p.owner_id, p.path, p.attrs, p.created_by, p.updated_by, p.created_at, p.updated_at "
            f"FROM wiki_pages p WHERE p.id IN ({','.join('?' * len(part))})", part)})
    return [full[i] for i in ids if i in full], len(hits)


def _wks_shared(c, uid, spaces, terms):
    """2.1002.0 (#5279, question 15): the hits among the pages outside spaces that a share of the shared core opens for uid
    (wkf_shared_ids: a shared folder or page), per space of the page; not in the trash, not of a space with the lock (the
    browser searches those), each hit checked with the page's own role (wiki_may_read) -- never more than opening it."""
    ids = sorted(int(x) for x in wkf_shared_ids(c, uid))
    if not ids:
        return []
    mine = {o for o in spaces if o}
    rows = c.execute(f"SELECT p.id, p.org_id, p.owner_id, p.path, p.updated_at FROM wiki_pages p WHERE p.id = ANY(CAST(? AS BIGINT[])) "
                     f"AND {live_sql('p')} AND left(p.path, 5)<>'e2e1:' AND {wke_open_sql('p')}", (ids,)).fetchall()
    by = {}
    for r in rows:
        if r["org_id"] in mine or (not r["org_id"] and r["owner_id"] == uid and None in spaces):
            continue  # searched with its space already
        by.setdefault((r["org_id"] or None, None if r["org_id"] else r["owner_id"]), []).append(r)
    out = []
    for (oid, owner), rs in by.items():
        late = _wks_late(c, "p.id = ANY(CAST(? AS BIGINT[]))", [[r["id"] for r in rs]], oid, owner)
        for x in _wks_rank(c, wks_ws(oid, owner), rs, terms, late):
            if wiki_may_read(c, uid, c.execute("SELECT * FROM wiki_pages WHERE id=?", (x[3],)).fetchone()):
                out.append(x)
    return out


def wks_name_hits(c, uid, q, limit=10, cand=200):
    """2.981.0 (#5278, question 15): knowledge pages whose name matches q (the shared index obj_search kind 'wiki_page': word
    start, part of the name too) that uid may read -- through the space or a share of the shared core on the page / its folders
    (wiki_may_read = wkf_role, also the pages of other spaces). Not in the trash, not of
    a space with the lock (the browser searches those). The text: the shared word index of the sealed texts (core/objwords.py, wks_find).
    [{id, path, space}] by name."""
    ids, args = osr_ids_sql("wiki_page", q, names=True)
    if ids is None:
        return []
    rows = c.execute(f"SELECT p.* FROM wiki_pages p WHERE p.id IN {ids} AND {live_sql('p')} AND {wke_open_sql('p')} "
                     f"ORDER BY lower(p.path), p.id LIMIT {int(cand)}", args).fetchall()
    out = []
    for r in rows:
        if wiki_may_read(c, uid, r):  # the page's own role per hit (never more than opening it)
            out.append({"id": r["id"], "path": r["path"], "space": wiki_space_key(r["org_id"])})
            if len(out) >= limit:
                break
    return out


# ---- 2.376 (#3292): the snippet of a hit
_WKP = ((re.compile(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S), " "),          # the frontmatter
        (re.compile(r"^[ \t]*(?:`{3,}|~{3,}).*$", re.M), " "),                                   # code fences (their text stays)
        (re.compile(r"!\[([^\[\]]*)\]\([^()\s]*\)"), r"\1"),                                  # ![alt](picture) -> alt
        (re.compile(r"\[\[([^\[\]|#\n]*)(?:#[^\[\]|\n]*)?\|([^\[\]\n]+)\]\]"), r"\2"),           # [[page|label]] -> label
        (re.compile(r"\[\[([^\[\]|#\n]+)(?:#[^\[\]\n]*)?\]\]"), lambda m: m.group(1).split("/")[-1]),  # [[folder/page]] -> page
        (re.compile(r"\[([^\[\]]+)\]\([^()\s]*\)"), r"\1"),                                    # [label](url) -> label
        (re.compile(r"<[^<>\n]{1,200}>"), " "),                                                  # html tags
        (re.compile(r"^[ \t]*(?:[-*_][ \t]*){3,}$", re.M), " "),                                 # rules
        (re.compile(r"^[ \t]*(?:>[ \t]?)*(?:#{1,6}[ \t]+|[-*+][ \t]+(?:\[[ xX]\][ \t]+)?|\d{1,9}[.)][ \t]+)?", re.M), ""),  # quote, heading, list
        (re.compile(r"[*~`]+|(?<!\w)_+|_+(?!\w)|\\(?=[!-/:-@\[-`{-~])"), ""),                     # emphasis marks, escapes
        (re.compile(r"[ \t]*\|[ \t]*"), " "),                                                     # table cells
        (re.compile(r"\s+"), " "))


def wks_plain(text):
    """The plain text of a page for a snippet: without frontmatter and Markdown marks, on one line."""
    s = str(text or "")[:200_000]
    for rx, to in _WKP:
        s = rx.sub(to, s)
    return s.strip()


def _folded(text):
    """(folded text, map folded position -> original position): the index's folding (docs/rules.py fold) per character."""
    from ..docs.rules import fold
    out, pos = [], []
    for i, ch in enumerate(text):
        f = ch.lower() if ch < "\x80" else (fold(ch) or ch.lower())  # ASCII: the quick way (same result)
        out.append(f)
        pos += [i] * len(f)
    return "".join(out), pos


def wks_snippet(text, words, size=WKS_SNIP):
    """(snippet, [[start, end], ...] relative to it, in code points) around the first word of words (folded query words) in
    the plain text of a page -- at the beginning of a word (2.1002.0 #5279: any length, like the index); None when no
    word is in the text."""
    t = wks_plain(text)
    if not t or not words:
        return None
    ft, pos = _folded(t)
    marks = []
    for wd in words:
        rx = re.compile(r"(?<!\w)" + re.escape(wd))  # 2.1002.0 (#5279): a word start, any length (question 14)
        for m in rx.finditer(ft):
            marks.append([pos[m.start()], pos[m.end() - 1] + 1])
            if len(marks) > 400:
                break
    if not marks:
        return None
    marks.sort()
    merged = []
    for a, b in marks:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    first = merged[0][0]
    start, end = 0, len(t)
    if len(t) > size:
        start = max(0, min(first - size // 3, len(t) - size))
        start = 0 if start < 16 else start  # a few words before the hit: from the beginning
        if start > 0:  # at a word boundary: from the next space on (never past the hit)
            sp = t.find(" ", start - 1, first)
            start = sp + 1 if sp >= 0 else start
        end = min(len(t), start + size)
        if end < len(t):
            sp = t.rfind(" ", max(start + 1, merged[0][1]), end + 1)
            end = sp if sp > 0 else end
    pre, post = ("…" if start > 0 else ""), ("…" if end < len(t) else "")
    sh = len(pre) - start
    return pre + t[start:end] + post, [[a + sh, min(b, end) + sh] for a, b in merged if start <= a < end]


def wks_snippets(c, rows, q):
    """{page id: (snippet, marks)} for the hit rows of one result page (the ones shown, at most WKS_LIMIT_MAX): their texts
    opened in memory only; a page that cannot be opened, of a space with the lock or without a word in its text has none.
    Nothing is kept, indexed or logged."""
    words = sorted({v for vs in osw_terms(q) for v in vs}, key=len, reverse=True)  # 2.1002.0 (#5279): every variant of a word
    ids = [r["id"] for r in rows if not str(r["path"]).startswith("e2e1:")]
    if not words or not ids:
        return {}
    out = {}
    for r in c.execute(f"SELECT id, org_id, owner_id, body FROM wiki_pages WHERE id IN ({','.join('?' * len(ids))})", ids):
        try:
            text = wkh_body(c, r)
        except WikiUnreadable:  # no snippet (and no log line: the search goes on as before)
            continue
        if not text or le2e_is_cipher(text):
            continue
        sn = wks_snippet(text, words)
        if sn:
            out[r["id"]] = sn
    return out
