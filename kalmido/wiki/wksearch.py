"""2.123.0 A (#2106): the search of the knowledge pages over a word index instead of ILIKE on the text (the text is sealed
since #2105). wiki_words holds HMAC hashes of the folded words of a page's text plus prefix hashes of 4, 6 and 8 characters
-- the same functions and per-space keys as the documents (docs/store.py: the space 'o<org>' / 'u<owner>' of doc_ws) --
and one row 'u:<updated_at>' = the state the index was built from. A save indexes its page at once; pages saved elsewhere
(an older version of the app, a [[link]] renamed, a move, an import) are indexed again by the next search that covers
their space (at most WKS_CATCH_UP per space and search). Spaces with the lock are searched in the browser (wikie2e.js).
2.139.0 C (#2386): a page whose text cannot be opened (its key is missing) is found by its name only and marked
'x:<updated_at>:<key state>' instead -- the next search reads it again once the key state of its space changed (a key
restored with the recovery key, a rotation, another server key), never at every search while the key stays missing.

A page matches when every query word is in its name (part of a word, as before) or in its text (a whole word, or a word
starting with it: like the documents' search, a word of 4+ characters is found by its longest stored prefix and checked
against the opened text). Ranking: words in the name first, then words in the text, then the newest.
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
    from .wkhist import wkh_sid
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
    when the text could not be opened (2.139.0 C #2386): no words, the mark 'x:' to try it again after a key event."""
    from ..docs.store import index_words, word_hashes
    c.execute("DELETE FROM wiki_words WHERE page_id=?", (pid,))
    if unreadable is not None:
        c.execute("INSERT INTO wiki_words(page_id, h) VALUES (?,?) ON CONFLICT DO NOTHING", (pid, f"x:{at}:{unreadable}"))
        return
    if le2e_is_cipher(text):
        return
    from .wktags import wkt_hashes  # 2.371 (#3150): the tags as hashes too; 'tv:1' = indexed with its tags
    ws = wks_ws(oid, owner)
    hs = sorted(word_hashes(c, ws, index_words(text or "")) | wkt_hashes(c, ws, text)) + ["u:" + str(at), "tv:1"]
    for i in range(0, len(hs), 500):
        part = hs[i:i + 500]
        c.execute("INSERT INTO wiki_words(page_id, h) VALUES " + ",".join(["(?,?)"] * len(part)) + " ON CONFLICT DO NOTHING",
                  [x for h in part for x in (pid, h)])


def wks_catch_up(c, w, a, limit=WKS_CATCH_UP, oid=None, owner=None):
    """Index the pages of a space (condition w / args a on wiki_pages p; oid / owner = the space) whose index is missing or
    older than the page -- or (2.139.0 C #2386) that could not be read under an earlier key state of the space."""
    from .wkhist import WikiUnreadable, wkh_body
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
    without the row 'tv:1' (made before the tags) counts as missing: those pages are indexed once more, with their tags."""
    return c.execute(f"SELECT p.id, p.org_id, p.owner_id, p.body, p.updated_at FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} "
                     "AND left(p.path, 5)<>'e2e1:' AND NOT EXISTS (SELECT 1 FROM wiki_words x WHERE x.page_id=p.id AND "
                     "(x.h='x:' || p.updated_at || ':' || CAST(? AS text) OR x.h='u:' || p.updated_at AND EXISTS "
                     "(SELECT 1 FROM wiki_words y WHERE y.page_id=p.id AND y.h='tv:1'))) "  # 2.371 (#3150): older ones lack the tags
                     f"ORDER BY p.id LIMIT {int(limit)}", [*a, ks]).fetchall()


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


def wks_search(c, uid, spaces, q, limit=WKS_LIMIT, offset=0):
    """(page rows ranked, total) of the open spaces (org ids, None = the private one of uid) for the query q; an empty query
    = the pages changed last. 2.280.0 C (#3114): the search writes nothing -- pages not indexed yet are read here (at most
    WKS_CATCH_UP per space, as the catch-up before) and indexed by a background job; only the names are read for every page,
    the full rows only for the hits of the answer."""
    from ..docs.rules import fold
    from ..docs.store import index_words, query_hashes
    from .wkhist import wsb_body_or
    from .wikie2e import wke_mode
    words = index_words(q)[:8]
    hits = []
    for oid in spaces:
        if wke_mode(c, oid, uid)[0]:
            continue  # a space with the lock: searched in the browser
        w, a = ("p.org_id=?", [oid]) if oid else ("p.org_id IS NULL AND p.owner_id=?", [uid])
        late = {}  # page id -> its words, read now (its index is missing or old)
        if words:
            ks = wks_key_state(c, oid, None if oid else uid)
            for r in wks_unindexed(c, w, a, ks):
                try:
                    t = wkh_body(c, r)  # 2.280.0 (#3114): sealed text = no words, as wks_index
                    late[r["id"]] = set() if le2e_is_cipher(t) else set(index_words(t))
                except WikiUnreadable:  # as the catch-up: unreadable = found by its name only
                    late[r["id"]] = set()
            if late:
                wks_job_add(oid, None if oid else uid)
        rows = c.execute(f"SELECT p.id, p.path, p.updated_at "
                         f"FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} AND left(p.path, 5)<>'e2e1:'", a).fetchall()
        if not words:
            hits += [(0, 0, r["updated_at"], r["id"], r) for r in rows]
            continue
        ws = wks_ws(oid, uid)
        titles = {r["id"]: fold(r["path"]) for r in rows}
        inbody, check = {}, []
        for wd in words:
            h, exact = query_hashes(c, ws, wd)
            inbody[wd] = {x[0] for x in c.execute(f"SELECT x.page_id FROM wiki_words x JOIN wiki_pages p ON p.id=x.page_id "
                                                   f"WHERE x.h=? AND p.deleted_at IS NULL AND {w}", [h, *a]) if x[0] not in late}
            # the pages read now: a whole word, or (4+ characters) a word starting with it -- what the index finds
            inbody[wd] |= {pid for pid, ws_ in late.items() if (wd in ws_ if len(wd) < 4 else any(x.startswith(wd) for x in ws_))}
            if not exact:
                check.append(wd)
        cand = [r for r in rows if all(wd in titles[r["id"]] or r["id"] in inbody[wd] for wd in words)]
        need = {r["id"] for r in cand if r["id"] not in late and any(wd not in titles[r["id"]] for wd in check)}
        have = {}
        if need:  # prefix hits: checked against the opened text
            ids = sorted(need)
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                for r in c.execute(f"SELECT id, org_id, owner_id, body FROM wiki_pages WHERE id IN ({','.join('?' * len(part))})", part):
                    have[r["id"]] = index_words(wsb_body_or(c, r))  # 2.126.2 B (#2358)
        for r in cand:
            pid, t = r["id"], titles[r["id"]]
            ok, nt, nb = True, 0, 0
            for wd in words:
                in_t = wd in t
                in_b = pid in inbody[wd] and (wd not in check or pid not in have or any(x.startswith(wd) for x in have[pid]))
                if not in_t and not in_b:
                    ok = False
                    break
                nt += in_t
                nb += in_b
            if ok:
                hits.append((nt, nb, r["updated_at"], pid, r))
    hits.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
    ids = [x[3] for x in hits[offset:offset + limit]]
    full = {}
    for i in range(0, len(ids), 500):  # the answer's rows in full
        part = ids[i:i + 500]
        full.update({r["id"]: r for r in c.execute(
            "SELECT p.id, p.org_id, p.owner_id, p.path, p.attrs, p.created_by, p.updated_by, p.created_at, p.updated_at "
            f"FROM wiki_pages p WHERE p.id IN ({','.join('?' * len(part))})", part)})
    return [full[i] for i in ids if i in full], len(hits)


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
    the plain text of a page -- a word of 4+ characters also at the beginning of a longer word, a shorter one whole, like
    the index; None when no word is in the text."""
    t = wks_plain(text)
    if not t or not words:
        return None
    ft, pos = _folded(t)
    marks = []
    for wd in words:
        rx = re.compile(r"(?<!\w)" + re.escape(wd) + (r"(?!\w)" if len(wd) < 4 else ""))
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
    from ..docs.store import index_words
    words = index_words(q)[:8]
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
