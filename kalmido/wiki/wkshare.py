"""2.123.0 B (#2104): read-only shares of a knowledge page or a folder -- customer documentation for people outside.

A share names a page (its path) or a folder (a path prefix: the folder's own page and every page below it, also pages made
later; "Customer A" never covers "Customer AB/…", names compare without case like the pages' unique names). Two kinds:
 - person: one person with an account reads it in the app ("Shared with me" in the pages view), nothing else of the space
   (no index, search, backlinks or mentions). Only in a private space: an organisation's page stays inside the organisation
   (the workspace rule of every shared object, accounts/orgs.ws_fit_problem); people outside get a public link. Never an
   agent, never the owner, by e-mail address without revealing whether an account exists (as lists do).
 - link: a public read-only page /s/w/<token> without an account (192 random bits; only the SHA-256 is looked up, the token
   is kept sealed for the owner to copy again), optional expiry, revocable at once. Server-rendered HTML without scripts:
   the shared page(s), their pictures / files (wiki_files of a shared page only), [[links]] to pages that are not shared as
   plain text, no other names. noindex, no caching, the rate limits of the public list links (lists/public.py), the same
   admin switch (public_links) and the same answer for unknown / expired / revoked links.
Rights: creating, changing and revoking = the write right in the space (a private space: its owner). A space with the lock
(wiki/wikie2e.py: texts encrypted in the browser) has no shares: the server cannot read the text (409 when creating; existing
shares stop serving when a space gets locked). Renaming a page or a folder takes its shares along (wiki_update / wiki_move);
moving pages to the other workspace (wkmove.py) ends their shares. Revoke = revoked_at (the app's Undo restores it).
The text is read only through wiki_dict (the page's one reading place)."""
import html
import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote

from flask import g, jsonify, request

from ..core.config import app, APP_NAME, PUBLIC_URL, TZ
from ..core.i18n import lang, LANGS, short_day, tr
from ..core.db import body, bump, db, iso, local_day, local_now, now_utc
from ..core.pg import insert_id, system_ctx
from ..core.access import Denied, acx_anon_bind
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, me, rate_ip
from ..collab.comments import user_names
from ..personal.timetrack import BadInput
from .pages import wiki_clean_path, wiki_dict, wiki_need, wiki_space, wiki_space_key

WSH_PREFIX = "/s/w/"
WSH_MAX = 300  # live shares per space
WSH_PAGES = 2000  # pages listed for one share
WSH_SEAL = "wikishare:"
# the page(s) a share covers: same space, the path itself or (a folder) below it -- s = wiki_shares, p = wiki_pages
WSH_COVER = ("COALESCE(s.org_id,0)=COALESCE(p.org_id,0) AND COALESCE(s.owner_id,0)=COALESCE(p.owner_id,0) AND (lower(p.path)=lower(s.path) "
             "OR (s.is_folder=1 AND left(lower(p.path), length(lower(s.path))+1)=lower(s.path)||'/'))")


def wsh_live(a="s"):
    """SQL: the share is neither revoked nor expired (one parameter: now as UTC ISO)."""
    return f"{a}.revoked_at IS NULL AND ({a}.expires_at IS NULL OR {a}.expires_at>?)"


def wsh_locked(c, oid, owner):
    from .wikie2e import wke_mode
    return bool(wke_mode(c, oid, owner)[0])


def wsh_open_sql():
    from .wikie2e import wke_open_sql
    return wke_open_sql("p")


def wsh_expired(r):
    return bool(r["expires_at"] and r["expires_at"] <= iso(now_utc()))


def wsh_url(c, r):
    from ..accounts.login import unseal
    if r["kind"] != "link" or not r["token"]:
        return ""
    try:
        return PUBLIC_URL.rstrip("/") + WSH_PREFIX + unseal(c, WSH_SEAL + r["token_hash"], r["token"])
    except Exception:  # a server key that changed: the owner makes a new link
        return ""


# 2.126.2 B (#2358): a link of an organisation's page works only while its maker is an active member (wsh_find) -- SQL for
# the live rows (wsh_rows) and the ended mark (wsh_gone); a = wiki_shares. Private spaces: unchanged.
WSH_MAKER = ("({a}.org_id IS NULL OR EXISTS (SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id={a}.org_id "
             "AND m.user_id={a}.created_by AND u.disabled=0))")


def wsh_gone(c, rows):
    """2.126.2 B (#2358): ids of the organisation links whose maker left the organisation / was deleted / disabled (one query)."""
    org = [r for r in rows if r["org_id"] is not None]
    if not org:
        return set()
    q = ",".join("?" * len(org))
    ok = {x[0] for x in c.execute(f"SELECT id FROM wiki_shares WHERE id IN ({q}) AND {WSH_MAKER.format(a='wiki_shares')}", [r["id"] for r in org])}
    return {r["id"] for r in org if r["id"] not in ok}


def wsh_dict(c, r, names, target=None, gone=()):
    d = {"id": r["id"], "kind": r["kind"], "space": wiki_space_key(r["org_id"]), "path": r["path"], "folder": bool(r["is_folder"]),
         "expires_at": r["expires_at"], "expired": wsh_expired(r), "revoked": bool(r["revoked_at"]), "created_at": r["created_at"],
         "created_by": r["created_by"], "created_by_name": names.get(r["created_by"], ""), "views": r["views"], "last_used_at": r["last_used_at"],
         "ended": r["id"] in gone}  # 2.126.2 B (#2358): its maker is no longer in the organisation -- the link does not work
    if r["kind"] == "person" and r["token"]:  # 2.123.0 (#2104): shared by e-mail address -- show the typed address, never the account
        from ..accounts.login import unseal
        try:
            em = unseal(c, WSH_SEAL + "mail", r["token"])
        except Exception:  # a server key that changed
            em = ""
        d["user"] = {"id": None, "name": em, "by_email": True}
    elif r["kind"] == "person":
        d["user"] = {"id": r["user_id"], "name": names.get(r["user_id"], "")}
    else:
        d["url"] = wsh_url(c, r)
    if target is not None:  # the share names exactly this page / folder (else it comes from a folder above)
        d["direct"] = r["path"].lower() == target[0].lower() and bool(r["is_folder"]) == target[1]
    return d


def wsh_rows(c, oid, owner, live=True):
    w = "COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=? AND revoked_at IS NULL"
    a = [oid or 0, 0 if oid else owner]
    if live:  # 2.126.2 B (#2358): a link whose maker left the organisation counts as ended too (mark, WSH_MAX)
        w += " AND (expires_at IS NULL OR expires_at>?) AND " + WSH_MAKER.format(a="wiki_shares")
        a.append(iso(now_utc()))
    return c.execute(f"SELECT * FROM wiki_shares WHERE {w} ORDER BY id LIMIT {WSH_MAX * 2}", a).fetchall()


def wsh_covers(r, path):
    p, s = path.lower(), r["path"].lower()
    return p == s or (bool(r["is_folder"]) and p.startswith(s + "/"))


def wsh_mark(c, oid, uid, pages):
    """GET /api/wiki: pages a live share covers get shared: 1 (the mark in the tree)."""
    if not pages:
        return
    rows = wsh_rows(c, oid, uid)
    if not rows:
        return
    for d in pages:
        if any(wsh_covers(r, d["path"]) for r in rows):
            d["shared"] = 1


def wsh_count(c, r):
    """GET /api/wiki/pages/<id>: the number of live shares that cover the page (its mark)."""
    if r["path"].startswith("e2e1:"):
        return 0
    return sum(1 for s in wsh_rows(c, r["org_id"], r["owner_id"]) if wsh_covers(s, r["path"]))


def wsh_repath(c, oid, owner, old, new, folder):
    """A page (folder False) or a folder (True: every share at or below it) got another name: the shares follow (also
    revoked ones, so an Undo of the revoke finds its page)."""
    for r in c.execute("SELECT id, path, is_folder FROM wiki_shares WHERE COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=?",
                       (oid or 0, 0 if oid else owner)).fetchall():
        p = r["path"]
        if folder and (p.lower() == old.lower() or p.lower().startswith(old.lower() + "/")):
            np = new + p[len(old):]
        elif not folder and not r["is_folder"] and p.lower() == old.lower():
            np = new
        else:
            continue
        c.execute("UPDATE wiki_shares SET path=? WHERE id=?", (np, r["id"]))


def wsh_end_moved(c, oid, owner, paths, folder=None):
    """Pages left the space (wkmove.py): their page shares end, and the shares of a folder that moved as a whole."""
    keys = {p.lower() for p in paths if p}
    f = folder.lower() if folder else None
    ts = iso(now_utc())
    for r in wsh_rows(c, oid, owner, live=False):
        p = r["path"].lower()
        if (not r["is_folder"] and p in keys) or (f and (p == f or p.startswith(f + "/"))):
            c.execute("UPDATE wiki_shares SET revoked_at=? WHERE id=?", (ts, r["id"]))


def wsh_expiry(v):
    """YYYY-MM-DD (today or later; valid through the end of that day, server time zone) -> UTC ISO, or None."""
    from ..tasks.validation import valid_date
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not valid_date(v) or v < local_now().date().isoformat():
        raise BadInput(tr("The expiry date must be today or later"))
    d = date.fromisoformat(v) + timedelta(days=1)
    return iso(datetime(d.year, d.month, d.day, tzinfo=TZ))


def wsh_target(c, uid, b, write):
    """(org id, owner, path, is_folder) of {page_id} | {space, folder}; 404 when the person may not see it."""
    if b.get("page_id") not in (None, ""):
        try:
            pid = int(b.get("page_id"))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "page_id"))
        r = wiki_need(c, pid, write=write)
        if write:
            wiki_space(c, uid, r["org_id"], write=True)
        return r["org_id"], r["owner_id"], r["path"], False
    oid = wiki_space(c, uid, b.get("space"), write=write)
    if b.get("folder") in (None, ""):
        return oid, None if oid else uid, None, True
    path = wiki_clean_path(b.get("folder"))
    owner = None if oid else uid
    if not c.execute("SELECT 1 FROM wiki_pages p WHERE p.deleted_at IS NULL AND COALESCE(p.org_id,0)=? AND COALESCE(p.owner_id,0)=? "
                     "AND (lower(p.path)=lower(?) OR left(lower(p.path), length(lower(?))+1)=lower(?)||'/') LIMIT 1",
                     (oid or 0, owner or 0, path, path, path)).fetchone():
        raise Denied(404)
    return oid, owner, path, True


def wsh_need(c, sid):
    """A share the person may manage (the write right in its space); 404 otherwise."""
    r = c.execute("SELECT * FROM wiki_shares WHERE id=?", (sid,)).fetchone()
    uid = me()
    if not r or (r["org_id"] is None and r["owner_id"] != uid):
        raise Denied(404)
    if r["org_id"] is not None:
        wiki_space(c, uid, r["org_id"], write=True)
    return r


def wsh_one(c, sid):
    r = c.execute("SELECT * FROM wiki_shares WHERE id=?", (sid,)).fetchone()
    return wsh_dict(c, r, user_names(c, {r["created_by"], r["user_id"]} - {None}), gone=wsh_gone(c, [r]))


@app.get("/api/wiki/shares")
def wsh_list():
    """?page=<id> | ?space=&folder=<path> -- the shares that cover the page / folder (direct: named exactly here, else from a
    folder above); ?space= alone: every live share of the space. + enabled (public links on), locked, person (person shares
    possible: a private space)."""
    from ..lists.public import public_links_on
    c = db()
    uid = me()
    q = {"page_id": request.args.get("page"), "space": request.args.get("space"), "folder": request.args.get("folder")}
    oid, owner, path, folder = wsh_target(c, uid, q, False)
    rows = wsh_rows(c, oid, owner, live=False)
    if path is not None:
        rows = [r for r in rows if wsh_covers(r, path) or (folder and r["path"].lower().startswith(path.lower() + "/"))]
    names = user_names(c, ({r["created_by"] for r in rows} | {r["user_id"] for r in rows}) - {None})
    locked = wsh_locked(c, oid, owner)
    gone = wsh_gone(c, rows)
    return jsonify(enabled=public_links_on(c), locked=locked, person=oid is None and not locked, space=wiki_space_key(oid),
                   shares=[] if locked else [wsh_dict(c, r, names, (path, folder) if path is not None else None, gone) for r in rows])


@app.post("/api/wiki/shares")
def wsh_create():
    """{page_id | space + folder, kind: person | link, user_id | email (person), expires: YYYY-MM-DD | null} -> the share
    (a link with its url). A person who already has a live share of the same page / folder: its expiry changes."""
    from ..lists.public import public_links_on
    from ..accounts.login import seal
    c = db()
    uid = me()
    b = body()
    oid, owner, path, folder = wsh_target(c, uid, b, True)
    if path is None:
        raise BadInput(tr("Invalid value: {0}", "folder"))
    kind = b.get("kind")
    if kind not in ("person", "link"):
        raise BadInput(tr("Invalid value: {0}", "kind"))
    if path.startswith("e2e1:") or wsh_locked(c, oid, owner):
        return jsonify(error=tr("Pages of a space encrypted in the browser cannot be shared."), code="wiki_e2e_share"), 409
    exp = wsh_expiry(b.get("expires"))
    if len(wsh_rows(c, oid, owner)) >= WSH_MAX:
        raise BadInput(tr("Too many shares in this space (at most {0})", WSH_MAX))
    ts = iso(now_utc())
    if kind == "link":
        if not public_links_on(c):
            return jsonify(error=tr("Public links are turned off on this server")), 409
        tok = secrets.token_urlsafe(24)  # 192 bits, the shape of the list links (lists/public.py PUB_TOKEN_RE)
        h = _token_hash(tok)
        sid = insert_id(c, "INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,token_hash,token,expires_at,created_by,created_at) "
                           "VALUES(?,?,?,?,'link',?,?,?,?,?)", (oid, owner, path, 1 if folder else 0, h, seal(c, WSH_SEAL + h, tok), exp, uid, ts))
        print("wiki public link created", sid, flush=True)
    else:
        if oid is not None:
            return jsonify(error=tr("Every member of the organisation reads these pages already. For people outside it, use a public link."),
                           code="wiki_share_org"), 409
        who = wsh_person(c, uid, b)
        by_mail = bool(b.get("email") and not b.get("user_id"))
        if who is None:  # by e-mail address: nothing happens, nothing is revealed
            return jsonify(ok=True, by_email=True)
        old = c.execute("SELECT id FROM wiki_shares WHERE kind='person' AND org_id IS NULL AND owner_id=? AND user_id=? AND lower(path)=lower(?) "
                        f"AND is_folder=? AND {wsh_live('wiki_shares')}", (owner, who, path, 1 if folder else 0, ts)).fetchone()
        if old:  # 2.126.2 B (#2355): the same live share again: no second News item
            c.execute("UPDATE wiki_shares SET expires_at=? WHERE id=?", (exp, old["id"]))
            sid = old["id"]
        else:
            # 2.123.0 (#2104): by e-mail address the typed address is kept (sealed) and shown instead of the account's name
            sid = insert_id(c, "INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,user_id,token,expires_at,created_by,created_at) "
                               "VALUES(NULL,?,?,?,'person',?,?,?,?,?)", (owner, path, 1 if folder else 0, who,
                                                                       seal(c, WSH_SEAL + "mail", str(b["email"]).strip()[:200]) if by_mail else "", exp, uid, ts))
            # 2.126.2 B (#2355): a News item for exactly that person (the sharing row of their settings; no push); only the
            # path they may read now
            from ..collab.news import news_add
            news_add(c, who, "wiki_shared", data={"path": path, "folder": bool(folder)})
    bump(c)
    c.commit()
    if kind != "link" and by_mail:  # the same answer as for an unknown address: whether an account exists stays hidden
        return jsonify(ok=True, by_email=True)
    return jsonify(wsh_one(c, sid)), 201


def wsh_person(c, uid, b):
    """The person of {user_id} (404 when unknown / not visible / an agent / oneself) or {email} (None when there is no such
    person: the answer must not reveal it)."""
    from ..accounts.orgs import may_see
    if b.get("email") and not b.get("user_id"):
        em = str(b["email"]).strip().lower()[:200]
        r = c.execute("SELECT id FROM users WHERE lower(email)=? AND disabled=0 AND COALESCE(kind,'user')!='agent'", (em,)).fetchone()
        return r[0] if r and r[0] != uid else None
    try:
        who = int(b.get("user_id") or 0)
    except (TypeError, ValueError):
        who = 0
    u = c.execute("SELECT id, kind FROM users WHERE id=? AND disabled=0", (who,)).fetchone()
    if not u or who == uid or (u["kind"] or "user") == "agent" or not may_see(c, uid, who):
        raise Denied(404, tr("unknown user"))
    return who


@app.patch("/api/wiki/shares/<int:sid>")
def wsh_update(sid):
    """{expires: YYYY-MM-DD | null}"""
    c = db()
    r = wsh_need(c, sid)
    b = body()
    if r["revoked_at"]:
        raise Denied(404)
    if "expires" in b:
        c.execute("UPDATE wiki_shares SET expires_at=? WHERE id=?", (wsh_expiry(b.get("expires")), sid))
        bump(c)
        c.commit()
    return jsonify(wsh_one(c, sid))


@app.delete("/api/wiki/shares/<int:sid>")
def wsh_revoke(sid):
    """Revoke: the link / the person's access ends at once (the app's Undo: POST /api/wiki/shares/<id>/restore)."""
    c = db()
    r = wsh_need(c, sid)
    if not r["revoked_at"]:
        c.execute("UPDATE wiki_shares SET revoked_at=? WHERE id=?", (iso(now_utc()), sid))
        bump(c)
        c.commit()
    return jsonify(wsh_one(c, sid))


@app.post("/api/wiki/shares/<int:sid>/restore")
def wsh_restore(sid):
    """Undo of a revoke (the same token: the link works again)."""
    from ..lists.public import public_links_on
    c = db()
    r = wsh_need(c, sid)
    if r["kind"] == "link" and not public_links_on(c):
        return jsonify(error=tr("Public links are turned off on this server")), 409
    if wsh_locked(c, r["org_id"], r["owner_id"]):
        return jsonify(error=tr("Pages of a space encrypted in the browser cannot be shared."), code="wiki_e2e_share"), 409
    if r["revoked_at"]:
        c.execute("UPDATE wiki_shares SET revoked_at=NULL WHERE id=?", (sid,))
        bump(c)
        c.commit()
    return jsonify(wsh_one(c, sid))


# ---------------------------------------------------------------- the guest: pages shared with me (person shares)
def wsh_guest_rows(c, uid, pid=None):
    """The pages live person shares give uid (private spaces of active owners, open spaces only, not in the trash)."""
    a = ([pid] if pid else []) + [uid, iso(now_utc())]
    return c.execute(f"SELECT p.* FROM wiki_pages p WHERE p.org_id IS NULL AND p.deleted_at IS NULL AND {wsh_open_sql()}" + (" AND p.id=?" if pid else "")
                     + f" AND EXISTS (SELECT 1 FROM wiki_shares s JOIN users o ON o.id=s.owner_id AND o.disabled=0 WHERE s.kind='person' "
                     f"AND s.user_id=? AND s.org_id IS NULL AND {wsh_live()} AND {WSH_COVER}) ORDER BY p.owner_id, lower(p.path) LIMIT {WSH_PAGES}", a).fetchall()


@app.get("/api/wiki/shared")
def wsh_shared():
    """The pages other people shared with me (read only): id, path, owner, changed."""
    c = db()
    rows = wsh_guest_rows(c, me())
    names = user_names(c, {r["owner_id"] for r in rows} | {r["updated_by"] for r in rows})
    return jsonify(pages=[{"id": r["id"], "path": r["path"], "owner_id": r["owner_id"], "owner_name": names.get(r["owner_id"], ""),
                           "updated_at": r["updated_at"], "updated_by_name": names.get(r["updated_by"], "")} for r in rows])


@app.get("/api/wiki/shared/pages/<int:pid>")
def wsh_shared_page(pid):
    """A page shared with me: path, text, its rendered HTML (links only to pages shared with me too, files through
    /api/wiki/shared/files/), its files, owner and change; 404 otherwise."""
    c = db()
    uid = me()
    rows = [r for r in wsh_guest_rows(c, uid) if r["owner_id"]]
    r = next((x for x in rows if x["id"] == pid), None)
    if not r:
        raise Denied(404)
    same = {x["path"].lower(): x["id"] for x in rows if x["owner_id"] == r["owner_id"]}
    files = wsh_files_of(c, list(same.values()))
    d = wiki_dict(r)
    names = user_names(c, {r["owner_id"], r["updated_by"]})
    own = [f for f in files.values() if f["page_id"] == pid]
    return jsonify(id=pid, path=r["path"], body=d["body"], attrs=d["attrs"], updated_at=r["updated_at"], updated_by_name=names.get(r["updated_by"], ""),
                   owner_name=names.get(r["owner_id"], ""), shared=True,
                   html=wsh_md(d["body"], lambda p: f"#wsh/{same[p.lower()]}" if p.lower() in same else None,
                               lambda fid: (wsh_file_url("/api/wiki/shared/files/", files[fid]), files[fid]["mime"].startswith("image/")) if fid in files else None),
                   files=[{"id": f["id"], "name": f["name"], "mime": f["mime"], "size": f["size"], "image": f["mime"].startswith("image/"),
                           "url": wsh_file_url("/api/wiki/shared/files/", f)} for f in own])


@app.get("/api/wiki/shared/files/<int:fid>")
@app.get("/api/wiki/shared/files/<int:fid>/<path:name>")
def wsh_shared_file(fid, name=None):
    c = db()
    files = wsh_files_of(c, [r["id"] for r in wsh_guest_rows(c, me())])
    if fid not in files:
        raise Denied(404)
    return wsh_send(c, files[fid], public=False)


def wsh_files_of(c, page_ids):
    """{file id: row} of the files of these pages (not in the trash)."""
    if not page_ids:
        return {}
    q = ",".join("?" * len(page_ids))
    return {f["id"]: f for f in c.execute(f"SELECT * FROM wiki_files WHERE page_id IN ({q}) AND deleted_at IS NULL ORDER BY id LIMIT 5000", page_ids)}


def wsh_file_url(base, f):
    return f"{base}{int(f['id'])}/{quote(f['name'], safe='')}"


def wsh_send(c, f, public):
    """A shared file like wikiatt.wka_get (SVG in a sandbox, a file found infected stays locked); public: never cached."""
    import os
    from ..core.config import ATT_DIR
    from ..core.orgcrypt import oc_send_file
    from ..files.scan import sc_guard
    from ..tasks.attachments import send_stored
    from .wikiatt import SVG
    sc_guard(c, "wiki", f["id"])
    if f["mime"] != SVG:
        resp = send_stored(f)
        if isinstance(resp, tuple):  # damaged or missing (an error answer)
            return resp
    else:
        full = os.path.join(ATT_DIR, f["path"])
        if not os.path.isfile(full):
            raise Denied(404)
        dl = request.args.get("dl") == "1"
        resp = oc_send_file(c, full, mimetype=SVG if not dl else "application/octet-stream", as_attachment=dl,
                            download_name=f["name"], conditional=True, max_age=0)
        resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if public:
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store, private"
    return resp


# ---------------------------------------------------------------- the public link /s/w/<token>
def wsh_find(c, token):
    """The live link share of a token (its space open, its owner / maker still active and, in an organisation, still a
    member) or None. Then the request reads as nobody, bound to exactly the share's organisation (like the list links)."""
    from ..lists.public import PUB_ACTOR, PUB_TOKEN_RE, public_links_on
    if not PUB_TOKEN_RE.fullmatch(token or "") or not public_links_on(c):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations; nothing else is read here
        r = c.execute("SELECT s.* FROM wiki_shares s JOIN users u ON u.id=COALESCE(s.owner_id, s.created_by) WHERE s.token_hash=? "
                      "AND s.kind='link' AND u.disabled=0 AND (s.org_id IS NULL OR EXISTS (SELECT 1 FROM org_members m WHERE "
                      "m.org_id=s.org_id AND m.user_id=s.created_by))", (_token_hash(token),)).fetchone()
    if not r or r["revoked_at"] or wsh_expired(r):
        return None
    acx_anon_bind(c, r["org_id"])
    g.user, g.auth_via = PUB_ACTOR, "public"
    if wsh_locked(c, r["org_id"], r["owner_id"]):
        return None
    return r


def wsh_pub_pages(c, s):
    """The pages of a link share (open, not in the trash), by name."""
    return c.execute(f"SELECT p.* FROM wiki_pages p WHERE p.deleted_at IS NULL AND COALESCE(p.org_id,0)=? AND COALESCE(p.owner_id,0)=? "
                     f"AND (lower(p.path)=lower(?) OR (? AND left(lower(p.path), length(lower(?))+1)=lower(?)||'/')) AND {wsh_open_sql()} "
                     f"ORDER BY lower(p.path) LIMIT {WSH_PAGES}", (s["org_id"] or 0, s["owner_id"] or 0, s["path"], bool(s["is_folder"]),
                                                                   s["path"], s["path"])).fetchall()


def wsh_lang(c, s):
    for part in (request.headers.get("Accept-Language") or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return lang(c, s["owner_id"] or s["created_by"])


def wsh_open(c, token, files=False):
    """Common checks of every /s/w/ request -> (share, None) or (None, response): the rate limits of the list links."""
    from ..api.v1 import hit_limit
    from ..lists.custview import CV_FILE_RATE
    from ..lists.public import PUB_BAD_LIMIT, PUB_VIEW_RATE, pub_gone, pub_limited
    from ..notify.alerts import aa_count
    ip = rate_ip()
    if hit_limit(("pubf:" if files else "pubv:") + ip, CV_FILE_RATE if files else PUB_VIEW_RATE):
        return None, pub_limited(_accept_lang())
    bad = [("pubbad:" + ip, PUB_BAD_LIMIT)]  # 2.126.0 C (#1979 I2): limited only when the link is not valid
    s = wsh_find(c, token)
    if not s:
        if _rate_blocked(bad):
            return None, pub_limited(_accept_lang())
        _rate_fail(bad)
        aa_count("security", "publink", ip)
        return None, pub_gone()
    return s, None


def wsh_seen(c, s):
    c.execute("UPDATE wiki_shares SET views=views+1, last_used_at=? WHERE id=?", (iso(now_utc()), s["id"]))
    c.commit()


@app.get("/s/w/<token>")
@app.get("/s/w/<token>/p/<int:pid>")
def wsh_pub_page(token, pid=None):
    from ..lists.public import pub_gone, pub_html
    c = db()
    s, bad = wsh_open(c, token)
    if bad:
        return bad
    lg = wsh_lang(c, s)
    pages = wsh_pub_pages(c, s)
    e, base = html.escape, WSH_PREFIX + token
    if pid is None and not s["is_folder"]:
        pid = pages[0]["id"] if pages else None
    if pid is None:  # a folder: the list of its pages
        if not s["is_folder"]:
            return pub_gone(lg)
        wsh_seen(c, s)
        name = s["path"].split("/")[-1]
        items = "".join(f'<li><a href="{e(base)}/p/{p["id"]}">{e(p["path"][len(s["path"]) + 1:] or p["path"].split("/")[-1])}</a></li>'
                        for p in pages)
        main = (f'<header><h1>{e(name)}</h1><p class="sub">{e(tr("Shared pages · read only", lg=lg))}</p></header>'
                + (f'<ul class="wkpidx">{items}</ul>' if items else f'<p class="empty">{e(tr("No pages yet.", lg=lg))}</p>'))
        return pub_html(f"{name} · {APP_NAME}", main, lg)
    r = next((p for p in pages if p["id"] == pid), None)
    if not r:
        return pub_gone(lg)
    wsh_seen(c, s)
    same = {p["path"].lower(): p["id"] for p in pages}
    files = wsh_files_of(c, list(same.values()))
    from .wkhist import WikiUnreadable
    try:
        d = wiki_dict(r)
    except WikiUnreadable:  # 2.126.2 B (#2358): a text that cannot be opened -- the page is gone for the link
        return pub_gone(lg)
    md = wsh_md(d["body"], lambda p: f"{base}/p/{same[p.lower()]}" if p.lower() in same else None,
                lambda fid: (f"{base}/file/{fid}", files[fid]["mime"].startswith("image/")) if fid in files else None)
    own = [f for f in files.values() if f["page_id"] == pid]
    back = f'<p class="wkpback"><a href="{e(base)}">{e(s["path"].split("/")[-1])}</a></p>' if s["is_folder"] else ""
    flist = ('<ul class="files">' + "".join(f'<li><a href="{e(base)}/file/{f["id"]}?dl=1" download rel="nofollow">{e(f["name"])}</a></li>' for f in own)
             + '</ul>') if own else ""
    title = r["path"].split("/")[-1]
    day = local_day(r["updated_at"])  # the day in the server's time zone
    when = short_day(day, lg, year=True) if day else ""
    main = (f'<header>{back}<h1>{e(title)}</h1><p class="sub">{e(tr("Read only", lg=lg))}'
            + (f' · {e(tr("Changed {0}", when, lg=lg))}' if when else "") + f'</p></header><article class="wkpub">{md}</article>{flist}')
    return pub_html(f"{title} · {APP_NAME}", main, lg)


@app.get("/s/w/<token>/file/<int:fid>")
def wsh_pub_file(token, fid):
    from ..lists.public import pub_gone
    c = db()
    s, bad = wsh_open(c, token, files=True)
    if bad:
        return bad
    files = wsh_files_of(c, [p["id"] for p in wsh_pub_pages(c, s)])
    if fid not in files:
        return pub_gone(wsh_lang(c, s))
    return wsh_send(c, files[fid], public=True)


# ---------------------------------------------------------------- Markdown -> HTML for shared pages (no scripts)
# Everything is escaped first; only these shapes become tags. Links: web / mail addresses; [[Page]] only when that page is
# shared too (else its label as text); /api/wiki/files/<id> only when the file belongs to a shared page; #123 stays text.
WSH_INLINE = re.compile(
    r"`([^`\n]+)`"                                                       # 1 code
    r"|(!?)\[([^\[\]\n]*)\]\(\s*<?([^\s()<>]{1,2000})>?(?:\s+\"[^\"\n]*\")?\s*\)"  # 2 bang, 3 label, 4 address
    r"|(!?)\[\[([^\[\]|#\n]{1,250})(?:#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]"  # 5 bang, 6 path, 7 label
    r"|\*\*(.+?)\*\*|__(.+?)__"                                          # 8, 9 strong
    r"|~~(.+?)~~"                                                        # 10 strike
    r"|\*([^*\n]+)\*|(?<!\w)_([^_\n]+)_(?!\w)"                           # 11, 12 emphasis
    r"|(https?://[^\s<>()\"]{2,2000})")                                  # 13 a bare web address
WSH_FILE_RE = re.compile(r"/api/wiki/files/(\d{1,15})(?:/.*)?$")


def wsh_inline(s, link, file, depth=0):
    e, out, pos = html.escape, [], 0
    if depth > 8:  # 2.123.0 (#2104): deep nesting is shown as text (no RecursionError on the public page)
        return e(s)
    for m in WSH_INLINE.finditer(s):
        out.append(e(s[pos:m.start()]))
        pos = m.end()
        if m.group(1) is not None:
            out.append(f"<code>{e(m.group(1))}</code>")
        elif m.group(4) is not None:
            label, addr = m.group(3), m.group(4)
            fm = WSH_FILE_RE.match(addr)
            if fm:
                got = file(int(fm.group(1)))
                if not got:
                    out.append(e(label or ""))
                elif m.group(2) and got[1]:
                    out.append(f'<img src="{e(got[0])}" alt="{e(label)}" loading="lazy">')
                else:
                    out.append(f'<a href="{e(got[0])}?dl=1" rel="nofollow">{wsh_inline(label, link, file, depth + 1) or e(addr.rsplit("/", 1)[-1])}</a>')
            elif re.match(r"(?i)(https?:|mailto:)", addr):
                out.append(f'<a href="{e(addr)}" rel="nofollow noopener noreferrer">{wsh_inline(label, link, file, depth + 1) if label else e(addr)}</a>')
            else:
                out.append(e(label or ""))  # relative addresses and pictures from elsewhere: the label only
        elif m.group(6) is not None:
            path, label = m.group(6).strip(), m.group(7)
            href = None
            try:
                href = link(wiki_clean_path(path))
            except BadInput:
                pass
            text = e(label.strip() if label and label.strip() else path)
            out.append(f'<a href="{e(href)}">{text}</a>' if href and not m.group(5) else text)
        elif m.group(8) is not None or m.group(9) is not None:
            out.append(f"<strong>{wsh_inline(m.group(8) or m.group(9), link, file, depth + 1)}</strong>")
        elif m.group(10) is not None:
            out.append(f"<del>{wsh_inline(m.group(10), link, file, depth + 1)}</del>")
        elif m.group(11) is not None or m.group(12) is not None:
            out.append(f"<em>{wsh_inline(m.group(11) or m.group(12), link, file, depth + 1)}</em>")
        else:
            out.append(f'<a href="{e(m.group(13))}" rel="nofollow noopener noreferrer">{e(m.group(13))}</a>')
    out.append(e(s[pos:]))
    return "".join(out)


def wsh_md(text, link, file, depth=0):
    """HTML of a page's Markdown: headings, paragraphs, lists (with check boxes, shown only), quotes, code blocks, rules,
    simple tables; link(path) -> address | None, file(id) -> (address, is picture) | None."""
    text = re.sub(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", "", text or "", flags=re.S)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    e, out, i, para = html.escape, [], 0, []
    il = lambda s: wsh_inline(s, link, file, depth)  # noqa: E731
    if depth > 8:  # 2.123.0 (#2104): quotes nested deeper are shown as text
        return f"<p>{html.escape(text or '')}</p>"

    def flush():
        if para:
            out.append("<p>" + "<br>".join(il(x) for x in para) + "</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        fence = re.match(r"^\s*(```|~~~)", ln)
        if fence:
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith(fence.group(1)):
                code.append(lines[i])
                i += 1
            out.append(f'<pre><code>{e(chr(10).join(code))}</code></pre>')
            i += 1
            continue
        if not st:
            flush()
            i += 1
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", st)
        if h:
            flush()
            n = min(len(h.group(1)) + 1, 6)  # the page title is the h1
            out.append(f"<h{n}>{il(h.group(2))}</h{n}>")
            i += 1
            continue
        if re.match(r"^(\*\s*\*\s*\*|-\s*-\s*-|_\s*_\s*_)[\s*_-]*$", st):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if st.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{wsh_md(chr(10).join(q), link, file, depth + 1)}</blockquote>")
            continue
        if st.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush()
            cells = lambda r: [x.strip() for x in r.strip().strip("|").split("|")]  # noqa: E731
            head = cells(ln)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            out.append('<div class="wktbl"><table><thead><tr>' + "".join(f"<th>{il(x)}</th>" for x in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{il(x)}</td>" for x in r) + "</tr>" for r in rows) + "</tbody></table></div>")
            continue
        lm = re.match(r"^(\s*)([-*+]|\d{1,9}[.)])\s+", ln)
        if lm:
            flush()
            ordered = lm.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m2 = re.match(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$", lines[i])
                if not m2 or m2.group(2)[0].isdigit() != ordered:
                    break
                items.append((len(m2.group(1).expandtabs(4)), m2.group(3)))
                i += 1
            lis = []
            for ind, t in items:
                cb = re.match(r"^\[([ xX])\]\s+(.*)$", t)
                if cb:
                    on = cb.group(1) != " "
                    t = f'<input type="checkbox" disabled{" checked" if on else ""}> ' + il(cb.group(2))
                else:
                    t = il(t)
                lis.append(f'<li class="d{min(ind // 2, 6)}{" task" if cb else ""}">{t}</li>')
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(lis)}</{tag}>")
            continue
        para.append(st)
        i += 1
    flush()
    return "".join(out)

