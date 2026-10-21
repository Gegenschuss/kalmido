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
"""
from ..collab.liste2e import le2e_is_cipher
from ..core.orgcrypt import _kek, _kek_check, _row, OrgCryptError  # 2.149.0 G (#2517): pulled up from functions

WKS_CATCH_UP = 300   # pages indexed again per space and search
WKS_LIMIT, WKS_LIMIT_MAX = 30, 100


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
    hs = sorted(word_hashes(c, wks_ws(oid, owner), index_words(text or ""))) + ["u:" + str(at)]
    for i in range(0, len(hs), 500):
        part = hs[i:i + 500]
        c.execute("INSERT INTO wiki_words(page_id, h) VALUES " + ",".join(["(?,?)"] * len(part)) + " ON CONFLICT DO NOTHING",
                  [x for h in part for x in (pid, h)])


def wks_catch_up(c, w, a, limit=WKS_CATCH_UP, oid=None, owner=None):
    """Index the pages of a space (condition w / args a on wiki_pages p; oid / owner = the space) whose index is missing or
    older than the page -- or (2.139.0 C #2386) that could not be read under an earlier key state of the space."""
    from .wkhist import WikiUnreadable, wkh_body
    ks = wks_key_state(c, oid, owner)
    rows = c.execute(f"SELECT p.id, p.org_id, p.owner_id, p.body, p.updated_at FROM wiki_pages p WHERE p.deleted_at IS NULL AND {w} "
                     "AND left(p.path, 5)<>'e2e1:' AND NOT EXISTS (SELECT 1 FROM wiki_words x WHERE x.page_id=p.id AND "
                     "x.h IN ('u:' || p.updated_at, 'x:' || p.updated_at || ':' || CAST(? AS text))) "
                     f"ORDER BY p.id LIMIT {int(limit)}", [*a, ks]).fetchall()
    for r in rows:
        try:
            text, bad = wkh_body(c, r), None
        except WikiUnreadable:  # 2.126.2 B (#2358): unreadable = title only; 2.139.0 C (#2386): again after a key event
            text, bad = "", ks
        wks_index(c, r["id"], r["org_id"], r["owner_id"], text, r["updated_at"], unreadable=bad)
    return len(rows)


def wks_search(c, uid, spaces, q, limit=WKS_LIMIT, offset=0):
    """(page rows ranked, total) of the open spaces (org ids, None = the private one of uid) for the query q; an empty query
    = the pages changed last."""
    from ..docs.rules import fold
    from ..docs.store import index_words, query_hashes
    from .wkhist import wsb_body_or
    from .wikie2e import wke_mode
    words = index_words(q)[:8]
    hits, did = [], 0
    for oid in spaces:
        if wke_mode(c, oid, uid)[0]:
            continue  # a space with the lock: searched in the browser
        w, a = ("p.org_id=?", [oid]) if oid else ("p.org_id IS NULL AND p.owner_id=?", [uid])
        if words:
            did += wks_catch_up(c, w, a, oid=oid, owner=None if oid else uid)
        rows = c.execute(f"SELECT p.id, p.org_id, p.owner_id, p.path, p.attrs, p.created_by, p.updated_by, p.created_at, p.updated_at "
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
                                                   f"WHERE x.h=? AND p.deleted_at IS NULL AND {w}", [h, *a])}
            if not exact:
                check.append(wd)
        cand = [r for r in rows if all(wd in titles[r["id"]] or r["id"] in inbody[wd] for wd in words)]
        need = {r["id"] for r in cand if any(wd not in titles[r["id"]] for wd in check)}
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
    if did:
        c.commit()  # the index made meanwhile stays (nothing else was changed by this request)
    hits.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
    return [x[4] for x in hits[offset:offset + limit]], len(hits)
