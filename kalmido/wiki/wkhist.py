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

#2102: the history keeps the states of a page: every save notes the text (sealed like the page) -- saves of the same person
within WKH_MERGE seconds share one version (the autosave does not make hundreds), at most WKH_KEEP per page (the oldest
go). A state saved outside this path (an older version of the app, a [[link]] renamed, an import) is noted as its own
version before the next save. Restoring = the old text saved as a new version (Undo in the app: the text before).
Spaces with the lock keep no history (the server cannot read their texts; switching the lock on holds the history of the
space until the trash period ends, 2.528.0 D #4306: wkx_hold_space / wkx_tick). The rows go with their page (trash -> final deletion), its organisation or its owner.

2.958.0 (#5281, stage Q7a of the cross-cutting core): the states are rows of the core's versions (core/objversions.py,
obj_versions, kind "wiki" = WKH_KIND, the kind of the renames in obj_history too): title = the page's name then, held_at = held
at a lock (was wiki_versions.wkx_held_at). The rules above stay here (merge, keep, prev, rights); the table wiki_versions is
gone (wkh_retire: moved at the start, then dropped).
"""
import json
import os
import re
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import jsonify

from ..accounts.session import me
from ..core.config import app
from ..core.db import body, bump, db, iso_ms, now_utc
from ..core import objhooks  # 2.958.0 (#5281): START (wkh_retire)
from ..core.i18n import N_, tr
from ..core.orgcrypt import OrgCryptError, PREFIX, _aad, _b64u, oc_active_for, oc_dec_k, oc_is_enc, oc_key, oc_user_space
from ..core.pg import qi, system_ctx, table_columns, table_exists, ts_canon, write_lock
from ..core.kernretire import KERN_RETIRE_LOCK, kern_retire, kern_retire_floor  # 2.958.0 (#5281): wkh_retire
from ..notify.alerts import aa_now  # 2.958.0 (#5281): the admins' alert of wkh_retire
from ..core.objversions import (OBJV_CTX, obj_version_add, obj_version_drop, obj_version_get,  # 2.958.0 (#5281)
                                obj_version_merge, obj_version_prune, obj_version_rows)
from ..core.retention import ret_due, ret_report, ret_trash_cut  # 2.528.0 D (#4306)
from ..core.serializers import unlink_files  # 2.528.0 D (#4306)
from ..core.objwords import osw_drop, osw_drop_sql  # 2.1002.0 (#5279): the shared word index
from ..core.access import Denied
from ..accounts.session import me
from ..collab.comments import user_names
from ..collab.liste2e import le2e_is_cipher
from .pages import wiki_need, wiki_dict, wiki_frontmatter, wiki_set_links  # 2.369.5 (#2517): pulled up from functions
from .wikie2e import wke_page_mode, wke_denied  # 2.369.5 (#2517): pulled up from functions

WKH_CTX, WKH_VCTX = "wiki_pages.body", OBJV_CTX  # 2.958.0 (#5281): a version's text is sealed as a row of obj_versions
WKH_OLD_VCTX = "wiki_versions.body"  # 2.958.0 (#5281): the context of the old table, read once by wkh_retire
WKH_TABLES = ("wiki_pages", "obj_versions")  # 2.958.0 (#5281): the tables of the passes (wkh_settle, wkh_count; qi)
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
    obj_version_add(c, WKH_KIND, r["id"], r["org_id"], r["owner_id"], path, wkh_seal(c, r["org_id"], r["owner_id"], text, WKH_VCTX),
                    len(text.encode()), by, at)  # 2.958.0 (#5281): the core's versions


def wkh_note(c, pid, uid, ts, prev=None, fresh=False):
    """The history after page pid was saved (its row holds the new state). prev = (text, path, by, at) of the state before
    the save: noted first when the history does not end with it. fresh = a version of its own (a restore)."""
    r = c.execute("SELECT id, org_id, owner_id, path, body FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    if not r or _locked(r):
        return
    text = wkh_body(c, r)
    last = next(iter(obj_version_rows(c, WKH_KIND, pid, 1)), None)  # 2.958.0 (#5281)
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
    if last is not None and ltext == text:
        return  # nothing changed (2.571.0 #4766: a new name alone is no version, it is in obj_history: wkh_rename)
    if prev is not None and last is None and (ltext if ltext is not None else prev[0]) == text:
        return  # 2.571.0 (#4766): a page without history renamed: its text is the one before
    if (last is not None and not fresh and last["created_by"] == uid and 0 <= _ts(ts) - _ts(last["created_at"]) < WKH_MERGE
            and not last["held_at"]):  # 2.528.0 D (#4306): a version held at a lock takes no new text
        obj_version_merge(c, last["id"], r["path"], wkh_seal(c, r["org_id"], r["owner_id"], text, WKH_VCTX), len(text.encode()), ts)
    elif text or last is not None or prev is not None:
        _ins(c, r, r["path"], text, uid, ts)
    obj_version_prune(c, WKH_KIND, pid, WKH_KEEP)


# 2.571.0 (#4766): a page's name is its own field: a rename goes into the core's history (obj_history, kind "wiki"), the
# versions above stay for its text (a save that changes only the name makes no version any more)
WKH_KIND = "wiki"


def wkh_rename(c, r, path, uid):
    """2.571.0 (#4766): page row r (before the save) is now called path -> obj_history (not for a space with the lock: its
    names are ciphertexts)."""
    if path != r["path"] and not _locked(r):
        from ..core.writes import OBJ_TRACK, obj_history_add, obj_track  # core/writes.py -> core/objects.py -> files: a cycle at the top
        if WKH_KIND not in OBJ_TRACK:
            obj_track(WKH_KIND, "wiki_pages")
        obj_history_add(c, uid, WKH_KIND, r["id"], {"path": r["path"]}, {"path": path}, org_id=r["org_id"] or None)


def wkh_rename_many(c, moves, uid):
    """2.609.0 (#4928): wkh_rename for every (page row, new path) of a folder rename (pages.wiki_move) in a few statements
    (core/writes.obj_history_add_many), not three to four per page."""
    items = [(r["id"], {"path": r["path"]}, {"path": nw}, r["org_id"] or None) for r, nw in moves if nw != r["path"] and not _locked(r)]
    if items:
        from ..core.writes import OBJ_TRACK, obj_history_add_many, obj_track  # as wkh_rename: a cycle at the top
        if WKH_KIND not in OBJ_TRACK:
            obj_track(WKH_KIND, "wiki_pages")
        obj_history_add_many(c, uid, WKH_KIND, items)


def wkh_renames(c, r, uid, info=None, limit=100):
    """2.571.0 (#4766): the renames of page row r, newest first: [{at, by_name, agent, from, to}] -- the paths as uid sees
    them (through a share from the shared node down, wkfolder.wkf_shown_path)."""
    from .wkfolder import wkf_shown_path
    rows = c.execute("SELECT * FROM obj_history WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT ?", (WKH_KIND, r["id"], int(limit))).fetchall()
    names = user_names(c, {x["user_id"] for x in rows if x["user_id"]})
    out = []
    for x in rows:
        a, z = json.loads(x["vals_before"] or "{}").get("path"), json.loads(x["vals_after"] or "{}").get("path")
        if a and z:
            out.append({"at": x["updated_at"], "by_name": names.get(x["user_id"], ""), "agent": bool(x["agent"]),
                        "from": wkf_shown_path(c, uid, r, info, a), "to": wkf_shown_path(c, uid, r, info, z)})
    return out


def wkh_prev(c, r):
    """(text, path, by, at) of page row r before a save -- for wkh_note."""
    return (wkh_body(c, r) if not _locked(r) else "", r["path"], r["updated_by"], r["updated_at"])


# ---- 2.528.0 D (#4306, B26): switching the lock on holds the history and the files in the trash instead of deleting them ---
# held_at of the versions (obj_versions, 2.958.0 #5281; was wiki_versions.wkx_held_at) and wiki_files.wkx_held_at
# (migrations.d/4306_d.py) mark the rows; while the space is locked nobody sees them (the routes below answer a
# locked space without history, wikiatt serves no file of it); wkx_tick deletes held versions and held trash files after the
# trash period (ret_trash_cut; review 2.528: also with the retention switch off), or earlier wka_tick / the core trash run (2.809.0, #5365). Once the
# lock is off again a held row is shown only to the people named in wiki_spaces.wkx_holds for its time (who could read the
# space then): no later member, share or agent gets it. The org export leaves held versions out (admin/orgexport.py ox_live).
# The keys of wkx_holds are the time of the switch as text; a version's held_at reads back as the same canonical text
# (TIMESTAMPTZ, core/pg.py ts_canon), a file's wkx_held_at is that text: both are compared through ts_canon.
def _wkx_where(oid, owner, alias=""):
    p = alias + "." if alias else ""
    return (f"{p}org_id=?", [oid]) if oid else (f"{p}org_id IS NULL AND {p}owner_id=?", [owner])


def _wkx_held_times(c, w, a):
    """The times of the holds rows of a space still carry (versions and files), canonical."""
    out = {ts_canon(r[0]) for r in c.execute(f"SELECT DISTINCT held_at FROM obj_versions WHERE kind=? AND {w} AND held_at IS NOT NULL",
                                              [WKH_KIND, *a])}
    return out | {ts_canon(r[0]) for r in c.execute(f"SELECT DISTINCT wkx_held_at FROM wiki_files WHERE {w} AND wkx_held_at IS NOT NULL", a)}


def _wkx_holds(raw):
    """{canonical time: [user ids]} of a wiki_spaces.wkx_holds value (None: not readable)."""
    try:
        holds = json.loads(raw or "{}")
    except ValueError:
        return None
    return {ts_canon(k): v for k, v in holds.items()} if isinstance(holds, dict) else None


def wkx_counts(c, oid, owner):
    """What switching the lock on would hold: {versions, files} of the space (the dialog before the switch, wke_info)."""
    w, a = _wkx_where(oid, owner)
    return {"versions": c.execute(f"SELECT COUNT(*) FROM obj_versions WHERE kind=? AND {w}", [WKH_KIND, *a]).fetchone()[0],
            "files": c.execute(f"SELECT COUNT(*) FROM wiki_files WHERE deleted_at IS NOT NULL AND {w}", a).fetchone()[0]}


def wkx_hold_space(c, sp, users, ts):
    """The lock of space row sp is switched on at ts (wikie2e.wke_start): its word index goes (derived, plain words); its
    versions and its files in the trash are held from ts (also rows an earlier switch held: the new period counts) for the
    people users. -> {versions, files} held. The caller commits."""
    oid, owner = sp["org_id"], sp["owner_id"]
    w, a = _wkx_where(oid, owner)
    osw_drop_sql(c, "wiki_page", f"SELECT id FROM wiki_pages WHERE {w}", a)  # 2.1002.0 (#5279): the shared word index
    # 2.571.0 (#4766): the names of its pages in the core's history are plain words too
    c.execute(f"DELETE FROM obj_history WHERE kind='wiki' AND ref_id IN (SELECT id FROM wiki_pages WHERE {w})", a)
    row = c.execute("SELECT wkx_holds FROM wiki_spaces WHERE id=?", (sp["id"],)).fetchone()
    holds = (_wkx_holds(row[0]) if row else {}) or {}
    old = {t: set(holds.get(t) or []) for t in _wkx_held_times(c, w, a)}  # earlier holds: only who was named then AND now keeps a re-held row
    now = set(int(u) for u in users)
    for o in old.values():
        now &= o
    n_v = c.execute(f"UPDATE obj_versions SET held_at=? WHERE kind=? AND {w}", [ts, WKH_KIND, *a]).rowcount
    n_f = c.execute(f"UPDATE wiki_files SET wkx_held_at=? WHERE deleted_at IS NOT NULL AND {w}", [ts, *a]).rowcount
    c.execute("UPDATE wiki_spaces SET wkx_holds=? WHERE id=?", (json.dumps({ts_canon(ts): sorted(now)} if n_v or n_f else {}), sp["id"]))
    return {"versions": n_v, "files": n_f}


def wkx_may_see(c, r, held_at, uid):
    """May uid see a row of page r held at held_at? An ordinary row (None): yes; a held one: only who wkx_holds names for it."""
    if not held_at:
        return True
    w, a = _wkx_where(r["org_id"], r["owner_id"])
    sp = c.execute(f"SELECT wkx_holds FROM wiki_spaces WHERE {w}", a).fetchone()
    holds = _wkx_holds(sp["wkx_holds"]) if sp else {}
    if holds is None:
        return False
    return int(uid) in set(holds.get(ts_canon(held_at)) or [])


def wkx_tick(c, force=False):
    """Watchdog (hourly): held versions and held trash files of spaces still locked go after the trash period. Review 2.528
    (Fable 1): also with the retention switch off -- the person agreed to the period when switching the lock on, readable
    copies of an encrypted space must not stay for good. A space open again keeps them (its people see them again,
    wkx_may_see). Holds no row names any more are cleared.
    2.1093.0 (#5472): kept on purpose, not moved onto the core's trash run (obj_trash_tick): it runs with the retention
    switch off too (the core's run only counts then), it deletes held versions (obj_versions.held_at) that are in no
    trash at all, and it decides by the space's lock and wkx_held_at, not by deleted_at alone. The files deleted on their
    own of an open space are the core's (wiki/wikiatt.py part kind wiki_file)."""
    if not ret_due("wiki_e2e_held", force=force):
        return {}
    cut = ret_trash_cut()
    space = ("JOIN wiki_spaces s ON (v.org_id IS NOT NULL AND s.org_id=v.org_id) OR "
             "(v.org_id IS NULL AND s.org_id IS NULL AND s.owner_id=v.owner_id)")
    with system_ctx(c):  # housekeeping over every space: rows are only deleted, nothing is handed to a person
        n = c.execute(f"DELETE FROM obj_versions WHERE id IN (SELECT v.id FROM obj_versions v {space} WHERE v.kind=? "
                      "AND v.held_at IS NOT NULL AND v.held_at<? AND s.e2e IS NOT NULL)", (WKH_KIND, cut)).rowcount
        files = c.execute(f"SELECT v.id, v.path FROM wiki_files v {space} WHERE v.wkx_held_at IS NOT NULL AND v.wkx_held_at<? "
                          "AND s.e2e IS NOT NULL AND v.deleted_at IS NOT NULL ORDER BY v.id LIMIT 500", (cut,)).fetchall()
        if files:  # like wka_tick: row, scan / text marks, the stored file after the commit
            ids = [r["id"] for r in files]
            q = ",".join("?" * len(ids))
            c.execute(f"DELETE FROM upload_scan WHERE kind='wiki' AND ref_id IN ({q})", ids)
            c.execute(f"DELETE FROM file_text WHERE kind='wiki' AND ref_id IN ({q})", ids)
            c.execute(f"DELETE FROM wiki_files WHERE id IN ({q})", ids)
        ret_report(c, "trash", {"versions": n, "files": len(files)}, True, run="wiki_e2e_held")
        for s in c.execute("SELECT id, org_id, owner_id, wkx_holds FROM wiki_spaces WHERE wkx_holds<>'{}'").fetchall():
            w, a = _wkx_where(s["org_id"], s["owner_id"])
            live = _wkx_held_times(c, w, a)
            try:
                holds = json.loads(s["wkx_holds"])
            except ValueError:
                holds = {}
            keep = {k: v for k, v in holds.items() if ts_canon(k) in live}
            if keep != holds:
                c.execute("UPDATE wiki_spaces SET wkx_holds=? WHERE id=?", (json.dumps(keep), s["id"]))
    c.commit()
    unlink_files([r["path"] for r in files])
    return {"versions": n, "files": len(files)}


def wkh_move(c, rows, to, uid, keep=True):
    """Pages rows moved to space to (wkmove.py): their versions sealed again for the target (keep) or dropped (a target
    with the lock); the word index is made again on the next search (the key of the space differs)."""
    ids = [r["id"] for r in rows]
    if not ids:
        return
    q = ",".join("?" * len(ids))
    osw_drop(c, "wiki_page", ids)  # 2.1002.0 (#5279): the shared word index (was wiki_words)
    if not keep:
        obj_version_drop(c, WKH_KIND, ids)  # 2.958.0 (#5281)
        return
    owner = None if to else uid
    src = {r["id"]: r for r in rows}
    for v in c.execute(f"SELECT id, ref_id, held_at FROM obj_versions WHERE kind=? AND ref_id IN ({q}) AND held_at IS NOT NULL",
                       [WKH_KIND, *ids]).fetchall():  # 2.528.0 D (#4306): held at a lock -- along only when the mover could read the space then
        if wkx_may_see(c, src[v["ref_id"]], v["held_at"], uid):
            c.execute("UPDATE obj_versions SET held_at=NULL WHERE id=?", (v["id"],))
        else:
            c.execute("DELETE FROM obj_versions WHERE id=?", (v["id"],))
    for v in c.execute(f"SELECT id, org_id, owner_id, body FROM obj_versions WHERE kind=? AND ref_id IN ({q})", [WKH_KIND, *ids]).fetchall():
        c.execute("UPDATE obj_versions SET org_id=?, owner_id=?, body=? WHERE id=?",
                  (to, owner, wkh_seal(c, to, owner, _vbody(c, v), WKH_VCTX), v["id"]))


def wkh_drop_unreadable(c, ids):
    """2.508.0 (#4301): versions of pages ids nobody can open any more (their key is gone) would stop wkh_move, and with it an
    account's deletion; they cannot be read by anyone, so they go."""
    if not ids:
        return
    q = ",".join("?" * len(ids))
    for v in c.execute(f"SELECT id, org_id, owner_id, body FROM obj_versions WHERE kind=? AND ref_id IN ({q})", [WKH_KIND, *ids]).fetchall():
        try:
            _vbody(c, v)
        except WikiUnreadable:
            c.execute("DELETE FROM obj_versions WHERE id=?", (v["id"],))


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
    for table, ctx, only in (("wiki_pages", WKH_CTX, ""), ("obj_versions", WKH_VCTX, f" AND kind='{WKH_KIND}'")):  # 2.958.0 (#5281)
        last = 0
        while True:
            if stop and stop():
                return out
            with system_ctx(c):  # orgcrypt: server-side bulk work over every space, never content handed to a person
                write_lock(c, "orgcrypt")
                rows = c.execute(f"SELECT id, org_id, owner_id, body FROM {qi(table, WKH_TABLES)} WHERE id>? AND body<>''{only} ORDER BY id LIMIT {WKH_BATCH}",
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
                    # 2.611.0 (#4865): and still in the space it was read in -- a page moved meanwhile with its text unchanged
                    # (a target that seals nothing) was sealed with the old space's key, unreadable in the new one
                    done = c.execute(f"UPDATE {table} SET body=? WHERE id=? AND body=? AND org_id IS NOT DISTINCT FROM ? "
                                     "AND owner_id IS NOT DISTINCT FROM ?", (new, r["id"], v, r["org_id"], r["owner_id"])).rowcount
                    out["changed"] += done
                    if not done and plain is not None:
                        # 2.662.0 (#4939): the way back wrote nothing (changed meanwhile): still sealed for a space it opens = failed
                        now = c.execute(f"SELECT org_id, owner_id, body FROM {table} WHERE id=?", (r["id"],)).fetchone()
                        nsid = wkh_sid(now["org_id"], now["owner_id"]) if now else 0
                        if now and nsid and oc_is_enc(now["body"] or "") and not le2e_is_cipher(now["body"]) and plain(nsid):
                            out["failed"] += 1
                            print("[orgcrypt] knowledge text left sealed:", table, r["id"], flush=True)
            c.commit()
            if len(rows) < WKH_BATCH:
                break
            last = rows[-1]["id"]
    return out


def wkh_count(c):
    """{"sealed": n, "plain": n} over the page texts and versions outside spaces with the lock (status)."""
    out = {"sealed": 0, "plain": 0}
    with system_ctx(c):  # orgcrypt: counts only
        for t, only in (("wiki_pages", ""), ("obj_versions", f" AND kind='{WKH_KIND}'")):  # 2.958.0 (#5281)
            for r in c.execute(f"SELECT left(body, 6) AS p, COUNT(*) AS n FROM {qi(t, WKH_TABLES)} WHERE body<>'' AND left(body, 5)<>'e2e1:'{only} GROUP BY left(body, 6)"):
                out["sealed" if r["p"] == PREFIX else "plain"] += int(r["n"])
    return out


# ---- 2.958.0 (#5281, stage Q7a): wiki_versions -> obj_versions at the start, then the old table goes ---------------------
WKH_RETIRE_WAITS = N_("Knowledge history clean-up waits: {0} old versions in {1} cannot be opened now (the key of their space is missing), the old table stays. See the server log.")
# 2.958.0 (#5281, Fable review F7): the alert names the pages and the way out (docs/dev/kern.md "Versions")
WKH_RETIRE_WAITS_PAGES = N_("Knowledge history clean-up waits: {0} old versions in {1} could not move (pages {2}), the old table stays. See the server log and the way out in docs/dev/kern.md (Versions).")
WKH_RETIRE_WHY = ("cannot be opened now (the key of their space is missing) or their id is taken -- they stay there, the table "
                  "stays, nothing dropped; the next start tries again (core/migrations.d/5281_a.py; the way out for a key that "
                  "is gone for good: docs/dev/kern.md, Versions)")


def _wkh_old_ts(v, fallback):
    """An old TEXT time as it goes into a TIMESTAMPTZ column: canonical, or fallback when no cast could read it."""
    t = ts_canon(v) if v else ""
    try:
        datetime.fromisoformat(t)
        return t
    except ValueError:
        return fallback


def _wkh_old_body(c, v, keys):
    """The body of an old row sealed for obj_versions (the same key of its space, the context OBJV_CTX); None when a sealed
    text cannot be opened now (it stays in wiki_versions for the next start). Fable review F7: a value without the whole
    shape of a sealed text (wsb_sealed_shape) is no ciphertext -- it moves unchanged, and wkh_open decides at reading as for
    the old table (shown as text while sealing is off, unreadable while on), instead of holding wiki_versions for ever."""
    body = v["body"] or ""
    if not oc_is_enc(body) or le2e_is_cipher(body) or not wsb_sealed_shape(body):
        return body
    sid = wkh_sid(v["org_id"], v["owner_id"])
    if sid not in keys:
        try:
            keys[sid] = oc_key(c, sid, create=False) if sid else None
        except OrgCryptError:
            keys[sid] = None
    try:
        return _seal(keys[sid], sid, WKH_VCTX, oc_dec_k(keys[sid], sid, WKH_OLD_VCTX, body))
    except (OrgCryptError, TypeError, ValueError):
        return None


def wkh_move_old(c):
    """2.958.0 (#5281): every row of wiki_versions into obj_versions (kind "wiki"): with its id (the undo steps of
    #5253 name version ids), the next numbers of its page in the old order, wkx_held_at as held_at, a sealed text sealed again
    for obj_versions. A moved row leaves wiki_versions at once (idempotent). -> {"moved": n, "kept": m, "pages": [page ids kept]}.
    Fable review F1: a row whose id is taken in obj_versions stays (a log line) -- a new id would make the old version the
    newest (every reader sorts by id); the identity always goes on after both tables' ids, so the rows left keep theirs."""
    cols = table_columns(c, "wiki_versions")
    held = "wkx_held_at" if "wkx_held_at" in cols else "NULL"
    now = iso_ms(now_utc())
    out, keys, nxt, last, kept = {"moved": 0, "kept": 0}, {}, {}, 0, set()
    while True:
        rows = c.execute(f"SELECT id, page_id, org_id, owner_id, path, body, size, created_by, created_at, updated_at, {held} AS held "
                         f"FROM wiki_versions WHERE id>? ORDER BY id LIMIT {WKH_BATCH}", (last,)).fetchall()
        for v in rows:
            pid = int(v["page_id"])
            body = _wkh_old_body(c, v, keys)
            if body is not None and c.execute("SELECT 1 FROM obj_versions WHERE id=?", (v["id"],)).fetchone():
                print(f"knowledge history, stage Q7a (#5281): old version {v['id']} of page {pid} stays in wiki_versions -- its id is "
                      "taken in obj_versions (docs/dev/kern.md, Versions)", flush=True)  # F1: never a new id
                body = None
            if body is None:
                out["kept"] += 1
                kept.add(pid)
                continue
            if pid not in nxt:
                nxt[pid] = c.execute("SELECT COALESCE(MAX(no), 0) FROM obj_versions WHERE kind=? AND ref_id=?", (WKH_KIND, pid)).fetchone()[0]
            nxt[pid] += 1
            at = _wkh_old_ts(v["created_at"], now)
            args = (WKH_KIND, pid, nxt[pid], v["org_id"], v["owner_id"], v["path"] or "", body, int(v["size"] or 0), v["created_by"],
                    at, _wkh_old_ts(v["updated_at"], at), _wkh_old_ts(v["held"], now) if v["held"] else None)
            c.execute("INSERT INTO obj_versions(id,kind,ref_id,no,org_id,owner_id,title,body,size,created_by,created_at,updated_at,"
                      "held_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (v["id"],) + args)
            c.execute("DELETE FROM wiki_versions WHERE id=?", (v["id"],))
            out["moved"] += 1
        if len(rows) < WKH_BATCH:
            break
        last = rows[-1]["id"]
    # the identity goes on after the ids taken over AND the ids still waiting in wiki_versions (Fable review F1: also with
    # nothing moved), never lower than it already is
    c.execute("SELECT setval(pg_get_serial_sequence('obj_versions', 'id'), GREATEST((SELECT MAX(id) FROM obj_versions), "
              "(SELECT MAX(id) FROM wiki_versions), pg_sequence_last_value(pg_get_serial_sequence('obj_versions', 'id')::regclass), 1))")
    out["pages"] = sorted(kept)
    return out


def _wkh_left(c):
    return c.execute("SELECT COUNT(*) FROM wiki_versions").fetchone()[0]


def _wkh_alert(n, tables, pages=()):
    if not pages:
        aa_now("storage", "kern5281:" + ",".join(tables), WKH_RETIRE_WAITS, (int(n), ", ".join(tables)))
        return
    shown = ", ".join(str(p) for p in list(pages)[:20]) + (" ..." if len(pages) > 20 else "")  # F7: which pages, the way out
    aa_now("storage", "kern5281:" + ",".join(tables), WKH_RETIRE_WAITS_PAGES, (int(n), ", ".join(tables), shown))


def wkh_retire(c):
    """2.958.0 (#5281, core/objhooks.START, every start until done): wkh_move_old, then the start check and DROP TABLE
    wiki_versions (core/kernretire.py kern_retire: rows left = texts that cannot be opened now; the back limit rises). {} once
    the table is gone (a catalog read)."""
    if not table_exists(c, "wiki_versions"):
        return {}
    with system_ctx(c):  # every space's versions; nothing is handed to a person
        write_lock(c, KERN_RETIRE_LOCK)
        if not table_exists(c, "wiki_versions"):  # another process did it meanwhile
            return {}
        out = wkh_move_old(c)
        if out["moved"]:  # Fable review F3: the data left the old table now -- an older image must not start before the DROP
            floor = kern_retire_floor(c)
            if floor:
                print(f"knowledge history, stage Q7a (#5281): {out['moved']} old version(s) moved; versions before {floor} no "
                      "longer start on this database", flush=True)
        pages = out.pop("pages", [])
        out.update(kern_retire(c, ("wiki_versions",), _wkh_left, "knowledge history, stage Q7a (#5281)",
                               alert=lambda n, t: _wkh_alert(n, t, pages), why=WKH_RETIRE_WHY))
    return out


objhooks.START.append(("kern5281_wiki", False, wkh_retire))  # 2.958.0 (#5281): every start until wiki_versions is gone


# ---- routes ---------------------------------------------------------------------------------------------------------------
def _page(pid, write=False):
    c = db()
    r = wiki_need(c, pid, write=write)  # 2.200.0 A (#2747): write = edit on the page (the space's right or a folder share)
    return c, r, bool(wke_page_mode(c, r)) or _locked(r)


def _version(c, pid, vid, r=None):
    v = obj_version_get(c, WKH_KIND, pid, vid)  # 2.958.0 (#5281)
    if not v or (r is not None and not wkx_may_see(c, r, v["held_at"], me())):  # 2.528.0 D (#4306): held at a lock
        raise Denied(404)
    return v


@app.get("/api/wiki/pages/<int:pid>/versions")
def wkh_list(pid):
    """The history of a page (newest first): [{id, no, path, size, created_at, updated_at, by_name, current}]; e2e = a space with
    the lock (no history). Who may read the page reads its history."""
    c, r, locked = _page(pid)
    if locked:
        return jsonify(versions=[], e2e=True)
    rows = obj_version_rows(c, WKH_KIND, pid, WKH_KEEP)  # 2.958.0 (#5281)
    seen = {}  # 2.528.0 D (#4306): held at a lock -- only for who could read the space then (one look per hold)
    for h in {x["held_at"] for x in rows if x["held_at"]}:
        seen[h] = wkx_may_see(c, r, h, me())
    rows = [x for x in rows if not x["held_at"] or seen[x["held_at"]]]
    names = user_names(c, {x["created_by"] for x in rows})
    by = sorted({int(x["created_by"]) for x in rows if x["created_by"]})
    agents = {r_[0] for r_ in c.execute(f"SELECT id FROM users WHERE kind='agent' AND id IN ({','.join('?' * len(by))})", by)} if by else set()
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
    out = [{"id": x["id"], "no": x["no"],  # 2.958.0 (#5281): + its number (the core's versions)
            "path": wkf_shown_path(c, uid, r, info, x["title"]), "size": x["size"], "created_at": x["created_at"],
            "updated_at": x["updated_at"], "by_name": names.get(x["created_by"], ""),
            "agent": x["created_by"] in agents,  # 2.577.0 (#4708 4): a version an agent account wrote
            "current": i == 0 and same(x)}
           for i, x in enumerate(rows)]  # 2.571.0 (#4766): a rename since makes no version: the text alone says current
    return jsonify(versions=out, e2e=False, renames=wkh_renames(c, r, uid, info))  # 2.571.0 (#4766): + the renames


@app.get("/api/wiki/pages/<int:pid>/versions/<int:vid>")
def wkh_get(pid, vid):
    """One version with its text."""
    c, r, locked = _page(pid)
    if locked:
        raise Denied(404)
    v = _version(c, pid, vid, r)
    from .wkfolder import wkf_shown_path
    # 2.200.0 F (#2747, review B3): the path from the share down
    return jsonify(id=v["id"], no=v["no"], path=wkf_shown_path(c, me(), r, path=v["title"]), body=_vbody(c, v), size=v["size"], created_at=v["created_at"], updated_at=v["updated_at"],
                   by_name=user_names(c, [v["created_by"]]).get(v["created_by"], ""))


def wkh_put_text(c, r, text, uid):
    """Page row r gets text as a new version (the name stays): the restore of a version, 2.778.0 (#5253) also the undo of a
    person's step (wkundo.py). Caller: write right checked, write_lock wiki-<id> held, not a space with the lock."""
    import json
    pid, ts, prev = r["id"], iso_ms(now_utc()), wkh_prev(c, r)
    c.execute("UPDATE wiki_pages SET body=?, attrs=?, updated_by=?, updated_at=? WHERE id=?",
              (wkh_seal(c, r["org_id"], r["owner_id"], text), json.dumps(wiki_frontmatter(text), ensure_ascii=False), uid, ts, pid))
    wiki_set_links(c, pid, text)
    wkh_note(c, pid, uid, ts, prev=prev, fresh=True)
    from .wksearch import wks_index
    wks_index(c, pid, r["org_id"], r["owner_id"], text, ts)
    bump(c, "wiki")


@app.post("/api/wiki/pages/<int:pid>/versions/<int:vid>/restore")
def wkh_restore(pid, vid):
    """{expect_updated_at?} -- the text of version vid becomes the page's text (a new version; the name stays). 409 with the
    current page when someone else saved in between. Write right on the page."""
    from .wkfolder import wkf_shown_path
    write_lock(db(), f"wiki-{int(pid)}")  # 2.269.0 B (#3034): before the page is read (same name as wiki_update)
    c, r, locked = _page(pid, write=True)
    if locked:
        raise wke_denied("wiki_e2e")
    v = _version(c, pid, vid, r)
    uid = me()
    exp = body().get("expect_updated_at")
    if exp and ts_canon(str(exp)) != ts_canon(r["updated_at"]):
        cur = wiki_dict(r, names=user_names(c, [r["updated_by"]]))
        cur["path"] = wkf_shown_path(c, uid, r)  # 2.200.0 (#2747, review): nothing above a share
        return jsonify(error=tr("Changed in the meantime by {0}", cur.get("updated_by_name") or "?"), page=cur), 409
    from .wkundo import wku_note, wku_pre  # 2.778.0 (#5253): a restore is a step of "Recent steps" too
    pre, before = wku_pre(c, pid), wkh_body(c, r)
    wkh_put_text(c, r, _vbody(c, v), uid)
    wku_note(c, r, before, uid, pre)
    c.commit()
    r2 = wiki_need(c, pid)
    d = wiki_dict(r2, names=user_names(c, [uid]))
    d["path"] = wkf_shown_path(c, uid, r2)  # 2.200.0 (#2747, review): nothing above a share
    d["restored"] = vid
    return jsonify(d)
