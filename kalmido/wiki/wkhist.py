"""2.123.0 A (#2105, #2102): knowledge pages -- the text sealed at rest and the history of a page.

#2105: the text (body) of a page in a space without the lock is sealed with the key of its space (core/orgcrypt.py, "kenc1:"):
the organisation's key, a private page the owner's account key (space -owner, like the private files). The name (path)
stays plain: the unique name per space, [[links]], the tree and the title search need it. Spaces with the lock
(wikie2e.py) hold ciphertexts of the browser: never sealed here. Reading takes both (plain from before 2.123, sealed).
New texts are sealed when the encryption of the space is on (oc_active_for: server key, org_encrypt, for private pages
private_encrypt) and the instance setting wiki_encrypt is "1" (off by default: encrypt-wiki switches it on). The start-up pass (admin/orgcrypt_cli.py encrypt_all ->
wkh_settle) seals what is still plain. The way back before running 2.122 or older:
    python -m kalmido.admin.orgcrypt_cli decrypt-wiki     (wiki_encrypt=0, every page text and version plain again)
    python -m kalmido.admin.orgcrypt_cli encrypt-wiki     (wiki_encrypt=1, sealed again)
decrypt-all and decrypt-private make them plain as well (for all / the private spaces).

#2102: wiki_versions keeps the states of a page: every save notes the text (sealed like the page) -- saves of the same person
within WKH_MERGE seconds share one version (the autosave does not make hundreds), at most WKH_KEEP per page (the oldest
go). A state saved outside this path (an older version of the app, a [[link]] renamed, an import) is noted as its own
version before the next save. Restoring = the old text saved as a new version (Undo in the app: the text before).
Spaces with the lock keep no history (the server cannot read their texts; switching the lock on drops the history of the
space, wikie2e.py wke_start). The rows go with their page (trash -> final deletion), its organisation or its owner.
"""
import os
import re
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import jsonify

from ..accounts.session import me
from ..core.config import app
from ..core.db import body, bump, db, iso_ms, now_utc
from ..core.i18n import tr
from ..core.orgcrypt import OrgCryptError, PREFIX, _aad, _b64u, oc_active_for, oc_dec_k, oc_is_enc, oc_key, oc_user_space
from ..core.pg import system_ctx, write_lock
from ..core.access import Denied
from ..accounts.session import me
from ..collab.comments import user_names
from ..collab.liste2e import le2e_is_cipher

WKH_CTX, WKH_VCTX = "wiki_pages.body", "wiki_versions.body"
WKH_MERGE = 600     # seconds: saves of the same person within this time share a version
WKH_KEEP = 100      # versions per page
WKH_BATCH = 200
WSB_SEALED_RE = re.compile(r"[A-Za-z0-9_-]+")  # 2.126.2 B (#2358): base64url without padding (orgcrypt._b64u)


def wkh_sid(oid, owner):
    """The key space of a page: its organisation, else the owner's account (orgcrypt: < 0)."""
    return int(oid) if oid else oc_user_space(owner)


def wkh_switch(c):
    with system_ctx(c):  # orgcrypt: an instance setting, no content
        r = c.execute("SELECT value FROM settings WHERE key='wiki_encrypt'").fetchone()
    # 2.123.0 (#2105): off until an admin runs encrypt-wiki -- sealed texts are unreadable for 2.122 and older, so the
    # update stays reversible without a manual step; encrypt-wiki sets "1", decrypt-wiki "0"
    return (r[0] if r else "0") == "1"


def wkh_on(c, sid):
    """New page texts of key space sid are sealed."""
    return bool(sid) and oc_active_for(c, sid) and wkh_switch(c)


def _seal(key, sid, ctx, text):
    # like orgcrypt.oc_enc_k, but also a text that itself starts with "kenc1:" is sealed (a page may hold anything)
    n = os.urandom(12)
    return PREFIX + _b64u(n + AESGCM(key).encrypt(n, text.encode(), _aad(sid, ctx)))


def wkh_seal(c, oid, owner, text, ctx=WKH_CTX):
    """The value to store for the plain text of a page (or version) of space oid / owner: sealed when on; '' and
    ciphertexts of a locked space stay as they are."""
    if not isinstance(text, str) or text == "" or le2e_is_cipher(text):
        return text
    sid = wkh_sid(oid, owner)
    if not wkh_on(c, sid):
        return text
    key = oc_key(c, sid)
    return _seal(key, sid, ctx, text) if key else text


class WikiUnreadable(OrgCryptError):
    """2.126.2 B (#2358): a sealed page text that cannot be opened (its key is gone) -- 409 wiki_unreadable, never the
    ciphertext as text (a save would write it down as the page)."""

    def __init__(self, msg="", private=False):
        super().__init__(msg)
        self.private = private  # 2.139.0 C (#2386): a page of the private space (no organisation recovery key)


def wsb_unreadable_text(private):
    """2.139.0 C (#2386): the message names the way out -- the recovery key, else only deleting (save, rename and move are
    refused so the sealed text is never lost)."""
    if private:
        return tr("This page cannot be read: the key of its encryption is missing. It opens again once the server key of this installation is restored; otherwise it can only be deleted.")
    return tr("This page cannot be read: the key of its encryption is missing. The recovery key of the organisation opens it again; otherwise it can only be deleted.")


@app.errorhandler(WikiUnreadable)
def wsb_unreadable(e):
    return jsonify(error=wsb_unreadable_text(getattr(e, "private", False)), code="wiki_unreadable"), 409


def wsb_sealed_shape(value):
    """2.126.2 B (#2358): the value has the whole shape of a sealed text ("kenc1:" + base64url of nonce, at least one byte and
    the tag, nothing else) -- a plain text that only starts with "kenc1:" (spaces, line breaks, short) does not."""
    v = value[len(PREFIX):]
    return len(v) >= 39 and WSB_SEALED_RE.fullmatch(v) is not None


def wkh_open(c, oid, owner, value, ctx=WKH_CTX):
    """The plain text of a stored value (a plain value unchanged). WikiUnreadable when a sealed one cannot be opened -- except
    while sealing is off for the space and the value is not shaped like a sealed text: then a plain text that happens to
    start like a sealed one is shown as it is."""
    if not oc_is_enc(value):
        return value
    sid = wkh_sid(oid, owner)
    try:
        return oc_dec_k(oc_key(c, sid, create=False), sid, ctx, value)
    except OrgCryptError as e:
        if wkh_on(c, sid) or wsb_sealed_shape(value):  # 2.126.2 B (#2358): an error, not the ciphertext as the page's text
            raise WikiUnreadable(str(e), private=not oid) from None
        return value


def wkh_body(c, r):
    """The plain text of page row r."""
    return wkh_open(c, r["org_id"], r["owner_id"], r["body"])


def wsb_body_or(c, r, default=""):
    """2.126.2 B (#2358): wkh_body for read-only passes over many pages (search index, export): an unreadable page gives
    default instead of failing the whole pass."""
    try:
        return wkh_body(c, r)
    except WikiUnreadable:
        print("wiki page unreadable, skipped", r["id"], flush=True)
        return default


def _vbody(c, v):
    return wkh_open(c, v["org_id"], v["owner_id"], v["body"], WKH_VCTX)


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _locked(r):
    return str(r["path"] or "").startswith("e2e1:") or le2e_is_cipher(r["body"])


def _ins(c, r, path, text, by, at):
    c.execute("INSERT INTO wiki_versions(page_id,org_id,owner_id,path,body,size,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (r["id"], r["org_id"], r["owner_id"], path, wkh_seal(c, r["org_id"], r["owner_id"], text, WKH_VCTX),
               len(text.encode()), by, at, at))


def wkh_note(c, pid, uid, ts, prev=None, fresh=False):
    """The history after page pid was saved (its row holds the new state). prev = (text, path, by, at) of the state before
    the save: noted first when the history does not end with it. fresh = a version of its own (a restore)."""
    r = c.execute("SELECT id, org_id, owner_id, path, body FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    if not r or _locked(r):
        return
    text = wkh_body(c, r)
    last = c.execute("SELECT id, org_id, owner_id, path, body, created_by, created_at FROM wiki_versions WHERE page_id=? "
                     "ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    try:
        ltext = _vbody(c, last) if last else None
    except WikiUnreadable:  # 2.126.2 B (#2358): an unreadable last version: the new state gets a version of its own
        last, ltext = None, None
    if prev is not None and prev[0] and prev[0] != ltext and not le2e_is_cipher(prev[0]):
        # the state before was saved outside this path (or before 2.123); a page without history that the same person saved
        # a moment ago (a new page, an import) starts with this save
        if last is not None or fresh or prev[2] != uid or not 0 <= _ts(ts) - _ts(prev[3]) < WKH_MERGE:
            _ins(c, r, prev[1], prev[0], prev[2], prev[3])
            last, ltext = None, prev[0]
    if last is not None and ltext == text and last["path"] == r["path"]:
        return  # nothing changed
    if prev is not None and last is None and ltext == text and prev[1] == r["path"]:
        return
    if (last is not None and not fresh and last["created_by"] == uid and 0 <= _ts(ts) - _ts(last["created_at"]) < WKH_MERGE):
        c.execute("UPDATE wiki_versions SET path=?, body=?, size=?, updated_at=? WHERE id=?",
                  (r["path"], wkh_seal(c, r["org_id"], r["owner_id"], text, WKH_VCTX), len(text.encode()), ts, last["id"]))
    elif text or last is not None or prev is not None:
        _ins(c, r, r["path"], text, uid, ts)
    cut = c.execute("SELECT id FROM wiki_versions WHERE page_id=? ORDER BY id DESC LIMIT 1 OFFSET ?", (pid, WKH_KEEP - 1)).fetchone()
    if cut:
        c.execute("DELETE FROM wiki_versions WHERE page_id=? AND id<?", (pid, cut["id"]))


def wkh_prev(c, r):
    """(text, path, by, at) of page row r before a save -- for wkh_note."""
    return (wkh_body(c, r) if not _locked(r) else "", r["path"], r["updated_by"], r["updated_at"])


def wkh_drop_space(c, oid, owner):
    """The history and the word index of a space go (its lock is switched on: no plain copy stays on the server)."""
    w, a = (("org_id=?", [oid]) if oid else ("org_id IS NULL AND owner_id=?", [owner]))
    c.execute(f"DELETE FROM wiki_versions WHERE {w}", a)
    c.execute(f"DELETE FROM wiki_words WHERE page_id IN (SELECT id FROM wiki_pages WHERE {w})", a)


def wkh_move(c, rows, to, uid, keep=True):
    """Pages rows moved to space to (wkmove.py): their versions sealed again for the target (keep) or dropped (a target
    with the lock); the word index is made again on the next search (the key of the space differs)."""
    ids = [r["id"] for r in rows]
    if not ids:
        return
    q = ",".join("?" * len(ids))
    c.execute(f"DELETE FROM wiki_words WHERE page_id IN ({q})", ids)
    if not keep:
        c.execute(f"DELETE FROM wiki_versions WHERE page_id IN ({q})", ids)
        return
    owner = None if to else uid
    for v in c.execute(f"SELECT id, org_id, owner_id, body FROM wiki_versions WHERE page_id IN ({q})", ids).fetchall():
        c.execute("UPDATE wiki_versions SET org_id=?, owner_id=?, body=? WHERE id=?",
                  (to, owner, wkh_seal(c, to, owner, _vbody(c, v), WKH_VCTX), v["id"]))


# ---- the passes (admin/orgcrypt_cli.py) ---------------------------------------------------------------------------------
def wkh_settle(c, plain=None, stop=None):
    """Seal every plain text of pages and versions of spaces without the lock where sealing is on (plain None), or open
    every sealed one of the spaces sid with plain(sid) true (the way back). Compare and set, batches with a commit each.
    -> {"changed": n, "failed": n} (a text that cannot be opened stays as it is)."""
    out = {"changed": 0, "failed": 0}
    on, keys, locked = {}, {}, {}

    def key(sid):
        if sid not in keys:
            keys[sid] = oc_key(c, sid, create=plain is None)
        return keys[sid]
    for table, ctx in (("wiki_pages", WKH_CTX), ("wiki_versions", WKH_VCTX)):
        last = 0
        while True:
            if stop and stop():
                return out
            with system_ctx(c):  # orgcrypt: server-side bulk work over every space, never content handed to a person
                write_lock(c, "orgcrypt")
                rows = c.execute(f"SELECT id, org_id, owner_id, body FROM {table} WHERE id>? AND body<>'' ORDER BY id LIMIT {WKH_BATCH}",
                                 (last,)).fetchall()
                for r in rows:
                    v, sid = r["body"], wkh_sid(r["org_id"], r["owner_id"])
                    if not sid or le2e_is_cipher(v):
                        continue
                    if plain is not None:
                        if not oc_is_enc(v) or not plain(sid):
                            continue
                        try:
                            new = oc_dec_k(key(sid), sid, ctx, v)
                        except OrgCryptError:
                            out["failed"] += 1
                            continue
                    else:
                        if oc_is_enc(v):
                            continue
                        if sid not in on:
                            sp = c.execute("SELECT 1 FROM wiki_spaces WHERE COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=? AND e2e IS NOT NULL",
                                           (r["org_id"] or 0, 0 if r["org_id"] else (r["owner_id"] or 0))).fetchone()
                            locked[sid] = sp is not None
                            on[sid] = wkh_on(c, sid)
                        if locked[sid] or not on[sid] or key(sid) is None:
                            continue
                        new = _seal(key(sid), sid, ctx, v)
                    out["changed"] += c.execute(f"UPDATE {table} SET body=? WHERE id=? AND body=?", (new, r["id"], v)).rowcount
            c.commit()
            if len(rows) < WKH_BATCH:
                break
            last = rows[-1]["id"]
    return out


def wkh_count(c):
    """{"sealed": n, "plain": n} over the page texts and versions outside spaces with the lock (status)."""
    out = {"sealed": 0, "plain": 0}
    with system_ctx(c):  # orgcrypt: counts only
        for t in ("wiki_pages", "wiki_versions"):
            for r in c.execute(f"SELECT left(body, 6) AS p, COUNT(*) AS n FROM {t} WHERE body<>'' AND left(body, 5)<>'e2e1:' GROUP BY left(body, 6)"):
                out["sealed" if r["p"] == PREFIX else "plain"] += int(r["n"])
    return out


# ---- routes ---------------------------------------------------------------------------------------------------------------
def _page(pid, write=False):
    from .pages import wiki_need
    c = db()
    r = wiki_need(c, pid, write=write)  # 2.200.0 A (#2747): write = edit on the page (the space's right or a folder share)
    from .wikie2e import wke_page_mode
    return c, r, bool(wke_page_mode(c, r)) or _locked(r)


def _version(c, pid, vid):
    v = c.execute("SELECT * FROM wiki_versions WHERE id=? AND page_id=?", (vid, pid)).fetchone()
    if not v:
        raise Denied(404)
    return v


@app.get("/api/wiki/pages/<int:pid>/versions")
def wkh_list(pid):
    """The history of a page (newest first): [{id, path, size, created_at, updated_at, by_name, current}]; e2e = a space with
    the lock (no history). Who may read the page reads its history."""
    c, r, locked = _page(pid)
    if locked:
        return jsonify(versions=[], e2e=True)
    rows = c.execute("SELECT id, org_id, owner_id, path, body, size, created_by, created_at, updated_at FROM wiki_versions "
                     "WHERE page_id=? ORDER BY id DESC LIMIT ?", (pid, WKH_KEEP)).fetchall()
    names = user_names(c, {x["created_by"] for x in rows})
    try:  # 2.126.2 B (#2358): an unreadable page still lists its history (no version is marked current)
        cur = wkh_body(c, r)
    except WikiUnreadable:
        cur = None

    def same(x):
        try:
            return cur is not None and _vbody(c, x) == cur
        except WikiUnreadable:
            return False
    from .wkfolder import wkf_shared, wkf_shown_path
    uid = me()
    info = wkf_shared(c, uid)  # 2.200.0 F (#2747, review B3): through a share the paths start at the shared node
    out = [{"id": x["id"], "path": wkf_shown_path(c, uid, r, info, x["path"]), "size": x["size"], "created_at": x["created_at"],
            "updated_at": x["updated_at"], "by_name": names.get(x["created_by"], ""), "current": i == 0 and x["path"] == r["path"] and same(x)}
           for i, x in enumerate(rows)]
    return jsonify(versions=out, e2e=False)


@app.get("/api/wiki/pages/<int:pid>/versions/<int:vid>")
def wkh_get(pid, vid):
    """One version with its text."""
    c, r, locked = _page(pid)
    if locked:
        raise Denied(404)
    v = _version(c, pid, vid)
    from .wkfolder import wkf_shown_path
    # 2.200.0 F (#2747, review B3): the path from the share down
    return jsonify(id=v["id"], path=wkf_shown_path(c, me(), r, path=v["path"]), body=_vbody(c, v), size=v["size"], created_at=v["created_at"], updated_at=v["updated_at"],
                   by_name=user_names(c, [v["created_by"]]).get(v["created_by"], ""))


@app.post("/api/wiki/pages/<int:pid>/versions/<int:vid>/restore")
def wkh_restore(pid, vid):
    """{expect_updated_at?} -- the text of version vid becomes the page's text (a new version; the name stays). 409 with the
    current page when someone else saved in between. Write right on the page."""
    import json
    from .pages import wiki_dict, wiki_frontmatter, wiki_need, wiki_set_links
    from .wikie2e import wke_denied
    from .wkfolder import wkf_shown_path
    write_lock(db(), f"wiki-{int(pid)}")  # 2.269.0 B (#3034): before the page is read (same name as wiki_update)
    c, r, locked = _page(pid, write=True)
    if locked:
        raise wke_denied("wiki_e2e")
    v = _version(c, pid, vid)
    uid = me()
    exp = body().get("expect_updated_at")
    if exp and exp != r["updated_at"]:
        cur = wiki_dict(r, names=user_names(c, [r["updated_by"]]))
        cur["path"] = wkf_shown_path(c, uid, r)  # 2.200.0 (#2747, review): nothing above a share
        return jsonify(error=tr("Changed in the meantime by {0}", cur.get("updated_by_name") or "?"), page=cur), 409
    text, ts, prev = _vbody(c, v), iso_ms(now_utc()), wkh_prev(c, r)
    c.execute("UPDATE wiki_pages SET body=?, attrs=?, updated_by=?, updated_at=? WHERE id=?",
              (wkh_seal(c, r["org_id"], r["owner_id"], text), json.dumps(wiki_frontmatter(text), ensure_ascii=False), uid, ts, pid))
    wiki_set_links(c, pid, text)
    wkh_note(c, pid, uid, ts, prev=prev, fresh=True)
    from .wksearch import wks_index
    wks_index(c, pid, r["org_id"], r["owner_id"], text, ts)
    bump(c)
    c.commit()
    r2 = wiki_need(c, pid)
    d = wiki_dict(r2, names=user_names(c, [uid]))
    d["path"] = wkf_shown_path(c, uid, r2)  # 2.200.0 (#2747, review): nothing above a share
    d["restored"] = vid
    return jsonify(d)
