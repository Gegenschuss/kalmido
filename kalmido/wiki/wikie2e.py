"""2.64.3 (#1817): the lock per knowledge space -- path and text of the pages encrypted in the browser.

A space (an organisation or "Private") can be switched to "encrypted": its pages then hold ciphertexts in wiki_pages.path
and .body (the format of the lists with the lock, collab/liste2e.py), the space key of each generation is wrapped for every
member (wiki_keys; private: only the owner), organisation members who join wait for their copy (wiki_key_pending, trigger
wiki_e2e_members), a member who leaves marks the space "rotation pending". Search, backlinks and "mentioned in" of such a
space run in the browser; the server neither fills wiki_links nor answers search / export / agents with its pages.
"""
# 2.64.3 A (#1817): the guard of the page routes (wiki/pages.py calls it) and the routes /api/wiki/e2e... -- the protocol of
# the lists with the lock (collab/liste2e.py), per space instead of per list:
# - space key: 32 random bytes per generation, wrapped by the browser for every member: ECDH -> HKDF-SHA256(salt
#   "wiki:<space_id>:<gen>", info "kalmido-wikikey:v1") -> AES-256-GCM, AAD "kalmido-wikikey:v1:<space_id>:<gen>:<R>:<W>";
# - path / text: AES-256-GCM, AAD "kalmido-wiki:v1:<space_id>:<g>:path|body", stored as "e2e1:{v, g, iv, ct}" (body "" stays "").
# Who manages: the private space its owner, an organisation's space its admins. Agents and API tokens never take part.
import json

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.i18n import N_, tr
from ..core.pg import IntegrityError, system_ctx
from ..core.access import Denied
from ..accounts.session import me
from ..collab.liste2e import (LE2EDenied, _LE2A_CIPHER, _LE2A_OLD, _LE2A_PLAIN, le2e_is_cipher, le2e_parse, le2e_writer_ok)
from ..core.orgcrypt import oc_is_enc  # 2.149.0 G (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.149.0 G (#2517): pulled up from functions
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions

WKE_BULK_MAX = 200     # pages per todo / bulk call
WKE_KEYS_MAX = 500     # entries per start / keys / rotate call (an organisation may have more members than a list)
WKE_WRAP_MAX = 200     # characters of a wrapped space key
WKE_PATH_MAX = 4000    # characters of an encrypted path (finding L3; a plain path has at most WIKI_PATH_MAX)
WKE_MSG = {
    "wiki_e2e": N_("This space is encrypted in the browser. Pages can only be changed in the app."),
    "wiki_e2e_busy": N_("This space is being encrypted. Try again in a moment."),
    "wiki_e2e_open": N_("Encrypted texts belong only in spaces encrypted in the browser."),
}


def wke_denied(code, status=409, **extra):
    return LE2EDenied(code, status, tr(WKE_MSG[code]), **extra)


def wke_body_max():
    from .pages import WIKI_BODY_MAX
    return int(WIKI_BODY_MAX * 4 * 1.34) + 1000  # review L1: characters of up to 4 UTF-8 bytes, Base64 of those


def wke_space_sql(oid, uid, alias=""):
    """The space of organisation oid (None = the private space of uid) in wiki_spaces / wiki_pages."""
    p = alias + "." if alias else ""
    return (f"{p}org_id=?", [oid]) if oid else (f"{p}org_id IS NULL AND {p}owner_id=?", [uid])


def wke_row(c, oid, uid):
    """The wiki_spaces row of a space (None: never locked). uid = the owner of a private space."""
    w, a = wke_space_sql(oid, uid)
    return c.execute(f"SELECT * FROM wiki_spaces WHERE {w}", a).fetchone()


def wke_mode(c, oid, uid):
    """(mode, gen) of a space: (None, 0) open | ('encrypting' | 'on' | 'decrypting', generation)."""
    r = wke_row(c, oid, uid)
    return ((r["e2e"] or None), int(r["e2e_gen"] or 0)) if r else (None, 0)


def wke_page_mode(c, r):
    """The mode of the space of page row r."""
    return wke_mode(c, r["org_id"], r["owner_id"])[0]


def wke_open_sql(alias="p"):
    """SQL condition: the page (table alias) lies in an open space and is no ciphertext -- search, mentions, digests."""
    return (f"left({alias}.path, 5)<>'e2e1:' AND NOT EXISTS (SELECT 1 FROM wiki_spaces ws WHERE ws.e2e IS NOT NULL AND "
            f"COALESCE(ws.org_id, 0)=COALESCE({alias}.org_id, 0) AND COALESCE(ws.owner_id, 0)=COALESCE({alias}.owner_id, 0))")


def wke_cipher_ok(v, gen, field):
    """A value of a locked space: a ciphertext of a generation up to gen ('' only for the text)."""
    mx = WKE_PATH_MAX if field == "path" else wke_body_max()
    if not isinstance(v, str) or len(v) > mx:
        return False
    if v == "":
        return field == "body"
    d = le2e_parse(v, max_ct=mx)
    return bool(d) and d["g"] <= gen


def wke_reenc_again(c, oid, uid):
    """A ciphertext of an older generation arrived after a key change (a tab not reloaded): the re-encryption is due again."""
    w, a = wke_space_sql(oid, uid)
    c.execute(f"UPDATE wiki_spaces SET e2e_reenc=e2e_gen WHERE {w} AND e2e='on' AND e2e_reenc=0 AND e2e_gen>1", a)


def wke_guard(c, oid, uid, path=None, text=None, kind="update", template=False):
    """THE write guard of the page routes. oid / uid = the space (uid: owner of a private space); path / text = the values about
    to be stored (None = not changed). kind: create | update | move | export | import. Raises LE2EDenied or returns the mode:
    - open space: no ciphertext (400 wiki_e2e_open) -> None;
    - move / export / import in a locked space: 409 wiki_e2e (the browser does them);
    - 'encrypting' / 'decrypting': path and text only through /api/wiki/e2e/bulk (409 wiki_e2e_busy);
    - 'on': only a person in the web app, path a ciphertext, text a ciphertext or '' (409 wiki_e2e), no template_id (400)."""
    mode, gen = wke_mode(c, oid, uid)
    vals = {k: v for k, v in (("path", path), ("body", text)) if v is not None}
    if mode is None:
        if any(le2e_is_cipher(v) for v in vals.values()):
            raise wke_denied("wiki_e2e_open", 400)
        return None
    if kind in ("move", "export", "import"):
        raise wke_denied("wiki_e2e")
    if template:
        raise wke_denied("wiki_e2e", 400)
    if not vals:
        return mode
    if mode != "on":
        raise wke_denied("wiki_e2e_busy")
    if not le2e_writer_ok():
        raise wke_denied("wiki_e2e", 403)
    if not all(wke_cipher_ok(v, gen, k) for k, v in vals.items()):
        raise wke_denied("wiki_e2e")
    if any((le2e_parse(v, max_ct=WKE_PATH_MAX if k == "path" else wke_body_max()) or {}).get("g", gen) < gen
           for k, v in vals.items() if v):
        wke_reenc_again(c, oid, uid)
    return mode


# ---------------------------------------------------------------- people of a space
def _wke_person():
    """A person in the web app (agents, API tokens, calendar apps, public links: 403)."""
    if not le2e_writer_ok():
        raise Denied(403)
    return me()


def _wke_names(c, ids):
    from ..collab.comments import user_names
    return user_names(c, list(ids))


def wke_can_manage(c, oid, uid):
    """Private space: its owner; an organisation's space: the organisation's admins."""
    if not oid:
        return True
    from ..accounts.orgs import is_org_admin
    return is_org_admin(c, uid, oid)


def wke_member_ids(c, oid, uid):
    """[(user_id, role)] of the people of a space (agents never): private = the owner, an organisation = its members."""
    if not oid:
        return [(uid, "owner")]
    return [(r[0], r[1] or "member") for r in c.execute(
        "SELECT m.user_id, m.role FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND COALESCE(u.kind, '')<>'agent' "
        "ORDER BY m.user_id", (oid,))]


def wke_people(c, sp, oid, uid):
    """[{user_id, name, role, has_keys, pub, key_gens}] of the people of a space (sp = its wiki_spaces row or None)."""
    rows = wke_member_ids(c, oid, uid)
    ids = [u for u, _ in rows]
    q = ",".join("?" * len(ids)) or "NULL"
    names = _wke_names(c, ids)
    pubs = {r[0]: r[1] for r in c.execute(f"SELECT user_id, pub FROM e2e_keys WHERE user_id IN ({q})", ids)}
    gens = {}
    if sp:
        for r in c.execute("SELECT user_id, gen FROM wiki_keys WHERE space_id=? ORDER BY gen", (sp["id"],)):
            gens.setdefault(r[0], []).append(r[1])
    return [{"user_id": u, "name": names.get(u, ""), "role": role, "has_keys": u in pubs,
             "pub": json.loads(pubs[u]) if u in pubs else None, "key_gens": gens.get(u, [])} for u, role in rows]


def wke_pending(c, sp, people):
    """The people without a key of the current generation (the waiting list): the rows of wiki_key_pending (the trigger and
    start / rotate fill them) plus any member the trigger could not see (e.g. a membership written before the space row was
    visible to that transaction) -- computed from the members, so nobody is ever missed."""
    if not sp or not sp["e2e"]:
        return []
    since = {r[0]: r[1] for r in c.execute("SELECT user_id, since FROM wiki_key_pending WHERE space_id=?", (sp["id"],))}
    gen = int(sp["e2e_gen"] or 0)
    return [{"user_id": p["user_id"], "name": p["name"], "since": since.get(p["user_id"]), "has_keys": p["has_keys"]}
            for p in people if gen not in p["key_gens"]]


# ---------------------------------------------------------------- what is still to convert
def _wke_cond(mode, gen, fields=("path", "body")):
    """SQL condition on wiki_pages of the pages not yet in the target format of mode (gen = the target generation; fields =
    the columns checked, 2.139.0 C #2386: one of them alone)."""
    if mode == "encrypting":
        return "(" + " OR ".join(_LE2A_PLAIN.format(f) for f in fields) + ")"
    if mode == "decrypting":
        return "(" + " OR ".join(_LE2A_CIPHER.format(f) for f in fields) + ")"
    old = _LE2A_OLD.replace("{1}", str(int(gen)))  # 'on': plain texts (there should be none) and older generations
    return "(" + " OR ".join(f"{_LE2A_PLAIN.format(f)} OR {old.format(f)}" for f in fields) + ")"


def _wke_todo_val(mode, gen, v):
    if not isinstance(v, str) or v == "":
        return False
    if not le2e_is_cipher(v):
        return mode != "decrypting"
    if mode != "on":
        return mode == "decrypting"
    d = le2e_parse(v, max_ct=max(WKE_PATH_MAX, wke_body_max()))
    return bool(d) and d["g"] < gen


def wke_left(c, sp, limit=None):
    """Pages (trash included) of space row sp not in the target format of its mode -> (pages or None, {pages: n})."""
    mode, gen = sp["e2e"] or None, int(sp["e2e_gen"] or 0)
    if not mode:
        return [], {"pages": 0}
    w, a = wke_space_sql(sp["org_id"], sp["owner_id"])
    cond = _wke_cond(mode, gen)
    # 2.139.0 C (#2386): a text sealed at rest whose key is missing cannot go to the browser -- the page is skipped (its text
    # stays as it is, it can only be deleted) and named; once only that text is left it no longer counts
    lost = _wke_lost(c, mode, gen, w, a)
    n = c.execute(f"SELECT COUNT(*) FROM wiki_pages WHERE {w} AND {cond}", a).fetchone()[0] - len(lost)
    if limit is None:
        return None, {"pages": int(n)}
    out, skipped = [], list(lost)
    from .wkhist import WikiUnreadable, wkh_body  # 2.123.0 A (#2105): a text sealed at rest goes out plain (the browser encrypts it)
    nl = f" AND id NOT IN ({','.join('?' * len(lost))})" if lost else ""
    for r in c.execute(f"SELECT id, org_id, owner_id, path, body FROM wiki_pages WHERE {w} AND {cond}{nl} ORDER BY id LIMIT ?",
                       [*a, *[x["id"] for x in lost], limit]).fetchall():
        body = None
        if _wke_todo_val(mode, gen, r["body"]):
            try:
                body = wkh_body(c, r)
            except WikiUnreadable:
                skipped.append({"id": r["id"], "path": r["path"]})
        out.append({"id": r["id"], "path": r["path"] if _wke_todo_val(mode, gen, r["path"]) else None, "body": body})
    return out, {"pages": int(n), "skipped": skipped[:200]}


def _wke_lost(c, mode, gen, w, a):
    """2.139.0 C (#2386): [{id, path}] of the pages whose name is converted but whose text (sealed at rest) cannot be opened."""
    if mode == "decrypting":
        return []  # the texts still to convert are the browser's ciphertexts, never sealed at rest
    from .wkhist import WikiUnreadable, wkh_body
    out = []
    for r in c.execute(f"SELECT id, org_id, owner_id, path, body FROM wiki_pages WHERE {w} AND {_wke_cond(mode, gen, ('body',))} "
                       f"AND NOT {_wke_cond(mode, gen, ('path',))} ORDER BY id LIMIT 1000", a).fetchall():
        if oc_is_enc(r["body"]):
            try:
                wkh_body(c, r)
            except WikiUnreadable:
                out.append({"id": r["id"], "path": r["path"]})
    return out


# ---------------------------------------------------------------- the answers
def wke_index_info(c, oid, uid):
    """The e2e block of GET /api/wiki: None (open) | {space_id, mode, gen, rotate, reenc, pending (number, only for managers),
    mine (I hold the key of the current generation), can_manage}."""
    sp = wke_row(c, oid, uid)
    if not sp or not sp["e2e"]:
        return None
    manage = wke_can_manage(c, oid, uid)
    gen = int(sp["e2e_gen"] or 0)
    d = {"space_id": sp["id"], "mode": sp["e2e"], "gen": gen, "rotate": int(sp["e2e_rotate"] or 0),
         "reenc": int(sp["e2e_reenc"] or 0), "can_manage": manage,
         "mine": c.execute("SELECT 1 FROM wiki_keys WHERE space_id=? AND user_id=? AND gen=?", (sp["id"], me(), gen)).fetchone() is not None}
    if manage:
        d["pending"] = len(wke_pending(c, sp, wke_people(c, sp, oid, uid)))
    return d


def wke_info(c, oid, uid):
    """The answer of GET /api/wiki/e2e (also of start, stop and rotate)."""
    from .pages import wiki_space_key
    sp = wke_row(c, oid, uid)
    people = wke_people(c, sp, oid, uid)
    mode = (sp["e2e"] or None) if sp else None
    keys = [] if not sp else [
        {"gen": r["gen"], "wrapped": json.loads(r["wrapped"]), "wrapped_by": r["wrapped_by"], "wrapper_pub": json.loads(r["wrapper_pub"])}
        for r in c.execute("SELECT * FROM wiki_keys WHERE space_id=? AND user_id=? ORDER BY gen", (sp["id"], uid))]
    left = {"pages": 0}
    if sp and (mode in ("encrypting", "decrypting") or (mode == "on" and int(sp["e2e_reenc"] or 0))):
        left = wke_left(c, sp)[1]
    return {"space": wiki_space_key(oid), "space_id": sp["id"] if sp else None, "mode": mode,
            "gen": int(sp["e2e_gen"] or 0) if sp else 0, "rotate": int(sp["e2e_rotate"] or 0) if sp else 0,
            "reenc": int(sp["e2e_reenc"] or 0) if sp else 0, "by": sp["e2e_by"] if sp else None, "at": sp["e2e_at"] if sp else None,
            "can_manage": wke_can_manage(c, oid, uid), "keys": keys, "pending": wke_pending(c, sp, people), "members": people,
            "left": left}


# ---------------------------------------------------------------- routes
def _wke_space(c, v):
    """(uid, oid) of a space value the signed-in person may read (404 otherwise)."""
    from .pages import wiki_space
    uid = _wke_person()
    return uid, wiki_space(c, uid, v)


def _wke_manage(c, v):
    uid, oid = _wke_space(c, v)
    if not wke_can_manage(c, oid, uid):
        raise Denied(403, tr("Only organisation admins can change this setting"))
    return uid, oid


def _wke_switch(c, v, on_ok=True):
    """todo / bulk / finish: during a switch (on_ok: also the re-encryption in 'on'); a manager at every step (2.190.0 B, #2496:
    whoever started it and lost the role meanwhile does not continue)."""
    uid, oid = _wke_space(c, v)
    sp = wke_row(c, oid, uid)
    if not sp or sp["e2e"] not in (("encrypting", "decrypting", "on") if on_ok else ("encrypting", "decrypting")):
        return uid, oid, sp, err(tr("No encryption change is running for this space."), 409)
    if not wke_can_manage(c, oid, uid):
        raise Denied(403, tr("Only organisation admins can change this setting"))
    return uid, oid, sp, None


def _wke_wrapped(v):
    from ..collab.e2e import e2e_blob
    return e2e_blob(v, WKE_WRAP_MAX)


def _wke_given(keys, ready):
    """{user_id: wrapped} of a keys list [{user_id, wrapped}] (every user_id in ready, none twice) or None."""
    if not isinstance(keys, list) or len(keys) > WKE_KEYS_MAX:
        return None
    given = {}
    for k in keys:
        w = _wke_wrapped(k.get("wrapped")) if isinstance(k, dict) else None
        u = k.get("user_id") if isinstance(k, dict) else None
        if not w or isinstance(u, bool) or not isinstance(u, int) or u not in ready or u in given:
            return None
        given[u] = w
    return given


def _wke_ensure_row(c, oid, uid):
    """The wiki_spaces row of a space, created when missing (a second request at the same moment finds it)."""
    try:
        with c.savepoint():
            c.execute("INSERT INTO wiki_spaces(org_id, owner_id) VALUES(?,?)", (oid, None if oid else uid))
    except IntegrityError:
        pass
    return wke_row(c, oid, uid)


@app.get("/api/wiki/e2e")
def wke_get():
    """?space= -- the lock of a knowledge space as the browser needs it (see the protocol above)."""
    c = db()
    uid, oid = _wke_space(c, request.args.get("space"))
    return jsonify(wke_info(c, oid, uid))


@app.post("/api/wiki/e2e/start")
def wke_start():
    """{space, keys: [{user_id, wrapped}]} -- switch the lock on (a manager with own keys set up): the browser made a space key
    and wrapped it for every member with encryption set up; the others wait for it (decision E7). -> 'encrypting'.
    {space, prepare: true} -- only creates the row of the space (mode stays open) and answers like GET: the browser needs
    space_id (salt and AAD) before it wraps."""
    from ..collab.e2e import e2e_keys_of
    c = db()
    b = body()
    uid, oid = _wke_manage(c, b.get("space"))
    sp = wke_row(c, oid, uid)
    if b.get("prepare") is True:
        if not sp:
            _wke_ensure_row(c, oid, uid)
            c.commit()
        return jsonify(wke_info(c, oid, uid))
    if sp and sp["e2e"]:
        return err(tr("The space is already encrypted in the browser."), 409)
    from .wikiatt import wka_space_has_files  # 2.99.0 A (#2182): page files cannot be encrypted in the browser yet
    if wka_space_has_files(c, oid, uid):
        return err(tr("The pages of this space have files. Files cannot be encrypted in the browser yet: delete them first."), 409)
    mine = e2e_keys_of(c, uid)
    if not mine:
        return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
    people = wke_people(c, sp, oid, uid)
    ready = {p["user_id"] for p in people if p["has_keys"]}
    given = _wke_given(b.get("keys"), ready)
    if given is None:
        return err(tr("Invalid value: {0}", "keys"))
    missing = ready - set(given)
    if missing or uid not in given:
        missing |= {uid} - set(given)
        names = _wke_names(c, missing)
        return jsonify(error=tr("A key is missing for: {0}", ", ".join(sorted(names.get(u, "?") for u in missing))),
                       code="wiki_e2e_keys", missing=sorted(missing)), 409
    # review M1: a page whose plain name or text starts like a ciphertext (written before 2.64.3) would count as encrypted
    w, a = wke_space_sql(oid, uid)
    odd = c.execute(f"SELECT id, path FROM wiki_pages WHERE {w} AND (left(path, 5)='e2e1:' OR left(body, 5)='e2e1:') "
                    "ORDER BY id LIMIT 20", a).fetchall()
    if odd:
        return jsonify(error=tr("These pages start with \"e2e1:\" and cannot be encrypted. Change them first: {0}",
                                ", ".join(r["path"][:60] for r in odd)), code="wiki_e2e_prefix", pages=[r["id"] for r in odd]), 409
    if not sp:  # the first switch of this space without prepare: its row
        sp = _wke_ensure_row(c, oid, uid)
    gen, ts = int(sp["e2e_gen"] or 0) + 1, iso(now_utc())
    # the switch itself first and only from the open state of the generation read: a second start gets 409
    if not c.execute("UPDATE wiki_spaces SET e2e='encrypting', e2e_gen=?, e2e_rotate=0, e2e_reenc=0, e2e_by=?, e2e_at=? "
                     "WHERE id=? AND e2e IS NULL AND e2e_gen=?", (gen, uid, ts, sp["id"], gen - 1)).rowcount:
        c.rollback()
        return err(tr("The space is already encrypted in the browser."), 409)
    c.execute("DELETE FROM wiki_keys WHERE space_id=?", (sp["id"],))
    c.execute("DELETE FROM wiki_key_pending WHERE space_id=?", (sp["id"],))
    for u, w in given.items():
        c.execute("INSERT INTO wiki_keys(space_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?)",
                  (sp["id"], gen, u, w, uid, mine["pub"], ts))
    for p in people:
        if p["user_id"] not in given:
            c.execute("INSERT INTO wiki_key_pending(space_id,user_id,since) VALUES(?,?,?) ON CONFLICT DO NOTHING", (sp["id"], p["user_id"], ts))
    from .wikiatt import wka_drop_trashed
    gone = wka_drop_trashed(c, oid, uid)  # 2.99.0 (#2182, review M2): no plain file in the trash of an encrypted space
    from .wkhist import wkh_drop_space
    wkh_drop_space(c, oid, None if oid else uid)  # 2.123.0 A (#2102, #2106): no history / word index of a locked space
    bump(c)
    c.commit()
    unlink_files(gone)
    return jsonify(wke_info(c, oid, uid))


@app.get("/api/wiki/e2e/todo")
def wke_todo():
    """?space=&limit=200 -- the next pages the browser converts (fields already in the target format are null)."""
    c = db()
    _uid, _oid, sp, e = _wke_switch(c, request.args.get("space"))
    if e:
        return e
    try:
        limit = max(1, min(WKE_BULK_MAX, int(request.args.get("limit") or WKE_BULK_MAX)))
    except ValueError:
        return err(tr("Invalid value: {0}", "limit"))
    pages, left = wke_left(c, sp, limit)
    return jsonify(pages=pages, left=left, mode=sp["e2e"], gen=int(sp["e2e_gen"] or 0), reenc=int(sp["e2e_reenc"] or 0))


def _wke_free_path(c, oid, owner, pid, path):
    """decrypting: a free name for page pid -- "Name (2)", "Name (3)" ... when another page of the space has it."""
    from .pages import WIKI_PATH_MAX
    w, a = wke_space_sql(oid, owner)
    cand, n = path, 2
    while c.execute(f"SELECT 1 FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND lower(path)=? AND id<>?",
                    [*a, cand.lower(), pid]).fetchone():
        suf = f" ({n})"
        cand = path[:WIKI_PATH_MAX - len(suf)].rstrip() + suf
        n += 1
    return cand


@app.post("/api/wiki/e2e/bulk")
def wke_bulk():
    """{space, pages: [{id, path?, body?}]} -- converted pages (at most 200): encrypting / 'on' = ciphertexts of the current
    generation (body also ''), decrypting = plain texts (a name taken in the space gets " (2)" ..., answered in renamed; links
    and frontmatter are rebuilt from the plain text). A value already in the target format stays (someone saved meanwhile);
    no history, one live update per call, repeating a call is harmless."""
    from .pages import WIKI_BODY_MAX, wiki_clean_path, wiki_frontmatter, wiki_set_links
    c = db()
    b = body()
    _uid, oid, sp, e = _wke_switch(c, b.get("space"))
    if e:
        return e
    mode, gen = sp["e2e"], int(sp["e2e_gen"] or 0)
    enc = mode in ("encrypting", "on")
    pages = b.get("pages")
    if not isinstance(pages, list) or any(not isinstance(x, dict) for x in pages):
        return err(tr("Invalid data"))
    if len(pages) > WKE_BULK_MAX:
        return err(tr("At most {0} values per call", WKE_BULK_MAX))
    bad = lambda what: BadInput(tr("Invalid value: {0}", what))  # noqa: E731
    w, a = wke_space_sql(sp["org_id"], sp["owner_id"])
    renamed = []
    try:
        for x in pages:
            pid = x.get("id")
            if isinstance(pid, bool) or not isinstance(pid, int):
                raise bad("id")
            row = c.execute(f"SELECT id, org_id, owner_id, path, body, deleted_at FROM wiki_pages WHERE id=? AND {w}", [pid, *a]).fetchone()
            if not row:
                raise bad("pages")
            upd = {}
            for k in ("path", "body"):
                v = x.get(k)
                if v is None:
                    continue
                if not isinstance(v, str):
                    raise bad(k)
                if enc:
                    if v == "":
                        if k == "path" or (row[k] or "") != "":  # an empty text only stands for an empty one
                            raise bad(k)
                        continue
                    if not wke_cipher_ok(v, gen, k) or le2e_parse(v, max_ct=WKE_PATH_MAX if k == "path" else wke_body_max())["g"] != gen:
                        raise bad(k)
                    if _wke_todo_val(mode, gen, row[k]):  # a plain text or (on) an older generation; a current one stays
                        upd[k] = v
                else:
                    if le2e_is_cipher(v):
                        raise bad(k)
                    if not le2e_is_cipher(row[k]):
                        continue  # already plain (a repeated call)
                    if k == "path":
                        v = wiki_clean_path(v)
                        if not row["deleted_at"]:
                            nv = _wke_free_path(c, sp["org_id"], sp["owner_id"], pid, v)
                            if nv != v:
                                renamed.append({"id": pid, "path": nv})
                            v = nv
                    elif len(v) > WIKI_BODY_MAX:
                        raise bad(k)
                    upd[k] = v
            if not upd:
                continue
            plain = upd.get("body")
            if "body" in upd:
                upd["attrs"] = "{}" if enc else json.dumps(wiki_frontmatter(upd["body"]), ensure_ascii=False)
                if not enc:  # 2.123.0 A (#2105): the plain text again is sealed at rest
                    from .wkhist import wkh_seal
                    upd["body"] = wkh_seal(c, row["org_id"], row["owner_id"], plain)
            try:
                with c.savepoint():
                    c.execute(f"UPDATE wiki_pages SET {','.join(k + '=?' for k in upd)} WHERE id=?", [*upd.values(), pid])
            except IntegrityError:
                raise bad("path") from None
            if enc:
                c.execute("DELETE FROM wiki_links WHERE from_id=?", (pid,))
            elif "body" in upd:
                wiki_set_links(c, pid, plain)
    except BadInput as x:
        c.rollback()
        return err(str(x))
    bump(c)
    c.commit()
    return jsonify(ok=True, renamed=renamed, left=wke_left(c, sp)[1])


@app.post("/api/wiki/e2e/finish")
def wke_finish():
    """{space} -- ends a switch when nothing is left: encrypting -> 'on' (links and frontmatter copies go), decrypting -> open
    (keys and waiting list go); 'on' after a key change -> the re-encryption is done (e2e_reenc 0)."""
    c = db()
    b = body()
    uid, oid, sp, e = _wke_switch(c, b.get("space"))
    if e:
        return e
    mode, gen, reenc = sp["e2e"], int(sp["e2e_gen"] or 0), int(sp["e2e_reenc"] or 0)
    if mode == "on" and not reenc:
        return err(tr("No encryption change is running for this space."), 409)
    left = wke_left(c, sp)[1]
    if left["pages"]:
        return jsonify(error=tr("Not all pages are converted yet."), code="wiki_e2e_left", left=left), 409
    ts = iso(now_utc())
    if mode == "on":
        if not c.execute("UPDATE wiki_spaces SET e2e_reenc=0 WHERE id=? AND e2e='on' AND e2e_gen=? AND e2e_reenc=?",
                         (sp["id"], gen, reenc)).rowcount:
            c.rollback()
            return err(tr("No encryption change is running for this space."), 409)
        bump(c)
        c.commit()
        return jsonify(ok=True, mode="on")
    if not c.execute("UPDATE wiki_spaces SET e2e=?, e2e_at=? WHERE id=? AND e2e=? AND e2e_gen=?",
                     ("on" if mode == "encrypting" else None, ts, sp["id"], mode, gen)).rowcount:
        c.rollback()
        return err(tr("No encryption change is running for this space."), 409)
    w, a = wke_space_sql(sp["org_id"], sp["owner_id"])
    if mode == "encrypting":  # copies of the plain texts: links (backlinks, mentions) and the frontmatter cache
        c.execute(f"DELETE FROM wiki_links WHERE from_id IN (SELECT id FROM wiki_pages WHERE {w})", a)
        c.execute(f"UPDATE wiki_pages SET attrs='{{}}' WHERE {w} AND attrs<>'{{}}'", a)
    else:
        c.execute("UPDATE wiki_spaces SET e2e_rotate=0, e2e_reenc=0 WHERE id=?", (sp["id"],))
        c.execute("DELETE FROM wiki_keys WHERE space_id=?", (sp["id"],))
        c.execute("DELETE FROM wiki_key_pending WHERE space_id=?", (sp["id"],))
    bump(c)
    c.commit()
    return jsonify(ok=True, mode="on" if mode == "encrypting" else None)


@app.post("/api/wiki/e2e/stop")
def wke_stop():
    """{space, password} -- the way back (a manager holding the current key, with the account password): 'on' / 'encrypting'
    -> 'decrypting'; the browser writes the plain texts back through todo / bulk / finish."""
    from ..collab.e2e import e2e_reauth
    c = db()
    b = body()
    uid, oid = _wke_manage(c, b.get("space"))
    sp = wke_row(c, oid, uid)
    if not sp or sp["e2e"] not in ("on", "encrypting"):
        return err(tr("The space is not encrypted in the browser."), 409)
    if not c.execute("SELECT 1 FROM wiki_keys WHERE space_id=? AND user_id=? AND gen=?", (sp["id"], uid, sp["e2e_gen"])).fetchone():
        return err(tr("You have no key for this space yet."), 409)
    e = e2e_reauth(c, uid, b)
    if e is not None:
        return e
    if not c.execute("UPDATE wiki_spaces SET e2e='decrypting', e2e_by=?, e2e_at=? WHERE id=? AND e2e IN ('on', 'encrypting')",
                     (uid, iso(now_utc()), sp["id"])).rowcount:
        c.rollback()
        return err(tr("The space is not encrypted in the browser."), 409)
    bump(c)
    c.commit()
    return jsonify(wke_info(c, oid, uid))


@app.post("/api/wiki/e2e/keys")
def wke_keys():
    """{space, keys: [{user_id, gen, wrapped}]} -- hand the space key to people on the waiting list (or again after they set up
    new keys): only a manager holding that generation; the recipient must be a member with encryption set up. The server stores
    the wrapper's public key itself and tells the recipient (News)."""
    from ..collab.e2e import e2e_keys_of
    from ..collab.news import news_add
    c = db()
    b = body()
    uid, oid = _wke_manage(c, b.get("space"))
    sp = wke_row(c, oid, uid)
    if not sp or not sp["e2e"]:
        return err(tr("The space is not encrypted in the browser."), 409)
    mine = e2e_keys_of(c, uid)
    keys = b.get("keys")
    if not mine or not isinstance(keys, list) or not keys or len(keys) > WKE_KEYS_MAX:
        return err(tr("Invalid value: {0}", "keys"))
    people = {p["user_id"]: p for p in wke_people(c, sp, oid, uid)}
    have = {r[0] for r in c.execute("SELECT gen FROM wiki_keys WHERE space_id=? AND user_id=?", (sp["id"], uid))}
    gen = int(sp["e2e_gen"] or 0)
    rows = []
    for k in keys:
        if not isinstance(k, dict):
            return err(tr("Invalid value: {0}", "keys"))
        u, gn, w = k.get("user_id"), k.get("gen"), _wke_wrapped(k.get("wrapped"))
        if isinstance(u, bool) or not isinstance(u, int) or isinstance(gn, bool) or not isinstance(gn, int) or not w:
            return err(tr("Invalid value: {0}", "keys"))
        if u not in people or not people[u]["has_keys"]:
            return err(tr("{0} cannot receive the key (not a member or encryption not set up).", people[u]["name"] if u in people else "?"), 409)  # review L3: no names outside
        if gn not in have or gn > gen:
            return err(tr("You have no key for this space yet."), 409)
        rows.append((u, gn, w))
    ts = iso(now_utc())
    got, skipped = set(), set()
    for u, gn, w in rows:
        # an existing copy is replaced only for myself or after the recipient set up new keys (like the lists, review L3)
        old = c.execute("SELECT created_at FROM wiki_keys WHERE space_id=? AND gen=? AND user_id=?", (sp["id"], gn, u)).fetchone()
        if old and u != uid:
            ku = c.execute("SELECT updated_at FROM e2e_keys WHERE user_id=?", (u,)).fetchone()
            if not ku or (ku[0] or "") <= (old[0] or ""):
                skipped.add(u)
                continue
        c.execute("INSERT INTO wiki_keys(space_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT (space_id,gen,user_id) DO UPDATE SET wrapped=excluded.wrapped, wrapped_by=excluded.wrapped_by, "
                  "wrapper_pub=excluded.wrapper_pub, created_at=excluded.created_at", (sp["id"], gn, u, w, uid, mine["pub"], ts))
        if gn == gen:
            c.execute("DELETE FROM wiki_key_pending WHERE space_id=? AND user_id=?", (sp["id"], u))
        got.add(u)
    skipped -= got
    if oid:
        org = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
        by = _wke_names(c, [uid]).get(uid, "")
        for u in got:
            if u != uid:
                news_add(c, u, "wiki_e2e_key", data={"org_id": oid, "name": org["name"] if org else "", "by": uid, "by_name": by},
                         row="share")
    bump(c)
    c.commit()
    return jsonify(ok=True, released=sorted(got), skipped=sorted(skipped))


@app.post("/api/wiki/e2e/rotate")
def wke_rotate():
    """{space, gen, keys: [{user_id, wrapped}]} -- a new generation of the space key (after someone left, or on request): only a
    manager holding the current key, only in 'on'; gen must be e2e_gen + 1 (a second rotation at the same moment: 409
    code wiki_e2e_gen). Members not in keys wait for it; an entry for someone who is no member -> 400. Starts the
    re-encryption (e2e_reenc = gen); old generations stay (texts not re-encrypted yet, backups)."""
    from ..collab.e2e import e2e_keys_of
    c = db()
    b = body()
    uid, oid = _wke_manage(c, b.get("space"))
    sp = wke_row(c, oid, uid)
    if not sp or sp["e2e"] != "on":
        return err(tr("The space is not encrypted in the browser."), 409)
    cur = int(sp["e2e_gen"] or 0)
    mine = e2e_keys_of(c, uid)
    if not mine or not c.execute("SELECT 1 FROM wiki_keys WHERE space_id=? AND user_id=? AND gen=?", (sp["id"], uid, cur)).fetchone():
        return err(tr("You have no key for this space yet."), 409)
    gen, keys = b.get("gen"), b.get("keys")
    if isinstance(gen, bool) or not isinstance(gen, int):
        return err(tr("Invalid value: {0}", "gen"))
    if gen != cur + 1:
        return jsonify(error=tr("The key of this space was changed meanwhile."), code="wiki_e2e_gen", gen=cur), 409
    people = wke_people(c, sp, oid, uid)
    given = _wke_given(keys, {p["user_id"] for p in people if p["has_keys"]})
    if not given or uid not in given:
        return err(tr("Invalid value: {0}", "keys"))
    ts = iso(now_utc())
    # atomic: only from the generation this browser wrapped for (another rotation first = 409, nothing written)
    if not c.execute("UPDATE wiki_spaces SET e2e_gen=?, e2e_rotate=0, e2e_reenc=?, e2e_by=?, e2e_at=? WHERE id=? AND e2e='on' AND e2e_gen=?",
                     (gen, gen, uid, ts, sp["id"], cur)).rowcount:
        c.rollback()
        return jsonify(error=tr("The key of this space was changed meanwhile."), code="wiki_e2e_gen", gen=cur), 409
    # the space row is locked now: a member who left in the meantime must not get the new key (the browser asks again)
    now = {u for u, _ in wke_member_ids(c, oid, uid)}
    if set(given) - now:
        c.rollback()
        return jsonify(error=tr("The members of this space changed meanwhile. Try again."), code="wiki_e2e_members"), 409
    for u, w in given.items():
        c.execute("INSERT INTO wiki_keys(space_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?)",
                  (sp["id"], gen, u, w, uid, mine["pub"], ts))
        c.execute("DELETE FROM wiki_key_pending WHERE space_id=? AND user_id=?", (sp["id"], u))
    for u in now - set(given):
        c.execute("INSERT INTO wiki_key_pending(space_id,user_id,since) VALUES(?,?,?) ON CONFLICT DO NOTHING", (sp["id"], u, ts))
    bump(c)
    c.commit()
    return jsonify(wke_info(c, oid, uid))


def wke_shares_space(c, a, b):
    """Are people a and b in the same organisation whose knowledge space has the lock? -- /api/e2e/pub (finding H4)."""
    return c.execute("""SELECT 1 FROM org_members x JOIN org_members y ON y.org_id=x.org_id JOIN wiki_spaces s ON s.org_id=x.org_id
                        AND s.e2e IS NOT NULL WHERE x.user_id=? AND y.user_id=? LIMIT 1""", (a, b)).fetchone() is not None


def wke_user_purge(c, uid):
    """Account deletion (accounts/users.py user_purge): the spaces whose key uid held are marked "rotation pending". The trigger
    on org_members does the same, but it only sees the spaces of the deleting person's organisations (row-level security: an
    instance admin outside the organisation deletes the account) -- so this asks across organisations, before the cascade."""
    with system_ctx(c):  # the spaces of every organisation the deleted person held a key of (no content is read)
        c.execute("UPDATE wiki_spaces SET e2e_rotate=e2e_gen WHERE e2e IS NOT NULL AND org_id IS NOT NULL AND id IN "
                  "(SELECT space_id FROM wiki_keys WHERE user_id=?)", (uid,))
