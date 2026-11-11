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
The text is read only through wiki_dict (the page's one reading place).

2.565.0 (#4717, the shared core stage 4): a person share is a core share -- a row of fs_shares ('view') on the page's
reference node, a folder share on the folder's node (+ the node of the page of the same name, which the folder share
covered by its path too). So it follows the page / the folder through renames, moves within the tree and a restore as
"Name (2)" (#4668), and "Shared with me" reads it like every share of the knowledge trees (wkfshare.py wkfs_rows).
2.937.0 (#5244, stage 7c): the person rows of wiki_shares (the cards with core_id / core_id2) are gone; the card data (the
address typed in, the switch "show pictures", folder or page, the pair) is a row of wiki_share_cards on the share itself, the
dialog's id is "p<fs_shares id>" (section "person shares = core shares" below). Revoking puts the share(s) into obj_revoked,
the Undo puts them back under their ids; a share taken back in the file store's dialog ends the card's other share too
(wsh_fs_unshare). Link shares stay rows of wiki_shares (a public link is no share with an account), with the maker's rule of 2.560.0 (#4698 c, WSH_MAKER)."""
import html
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import quote

from flask import g, jsonify, request, Response

from ..core import objhooks  # 2.565.0: START (core/db.init_db runs the forward copy)
from ..files.fsref import fs_unshare_hooks  # 2.623.0 (#4778)
from ..core.config import app, APP_NAME, PUBLIC_URL, TZ, ATT_DIR
from ..core.i18n import browser_lang, lang, short_day, tr
from ..core.db import body, bump, db, iso, local_day, local_now, now_utc
from ..core.pg import insert_id, system_ctx
from ..core.kernretire import kern_retire_due, kern_retire_rows  # 2.937.0 (#5244): stage 7c at the start (wsh_retire)
from ..core.access import Denied, acx_anon_bind, live_sql
from ..accounts.session import _accept_lang, _rate_blocked, _rate_fail, _token_hash, me, rate_ip
from ..collab.comments import user_names
from ..core.errors import BadInput
from .pages import wiki_clean_path, wiki_dict, wiki_need, wiki_space, wiki_space_key
from ..core.orgcrypt import oc_send_file  # 2.149.0 G (#2517): pulled up from functions
from ..core.orgcrypt import oc_read_file  # 2.674.0 (#4382 finding 2)
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..files.fslock import fl_is_locked
from ..files.scan import sc_guard
from ..files.store import fs_version_row
from .wkembed import wem_visible
from .wkhist import WikiUnreadable
from .wikie2e import wke_mode, wke_open_sql  # 2.369.5 (#2517): pulled up from functions
from ..tasks.validation import valid_date  # 2.369.5 (#2517): pulled up from functions
from ..lists.public import public_links_on, PUB_ACTOR, PUB_TOKEN_RE, PUB_BAD_LIMIT, PUB_VIEW_RATE, pub_gone, pub_limited, pub_html  # 2.369.5 (#2517): pulled up from functions
from ..accounts.login import seal  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import may_see  # 2.369.5 (#2517): pulled up from functions
from ..tasks.attachments import send_stored  # 2.369.5 (#2517): pulled up from functions
from .wikiatt import SVG  # 2.369.5 (#2517): pulled up from functions
from ..lists.custview import CV_FILE_RATE  # 2.369.5 (#2517): pulled up from functions
from ..notify.alerts import aa_count  # 2.369.5 (#2517): pulled up from functions
from ..notify.alerts import aa_now  # 2.937.0 (#5244): the admins' alert of wsh_retire
from ..collab.news import news_add  # 2.369.5 (#2517): pulled up from functions

WSH_PREFIX = "/s/w/"
WSH_MAX = 300  # live shares per space
WSH_PAGES = 2000  # pages listed for one share
WSH_SEAL = "wikishare:"
# the page(s) a share covers: same space, the path itself or (a folder) below it -- s = wiki_shares, p = wiki_pages
# 2.360.0 D (#2496): a page share covers only the page it was made for (page_id; NULL = a row of an older version, by name)
WSH_COVER = ("COALESCE(s.org_id,0)=COALESCE(p.org_id,0) AND COALESCE(s.owner_id,0)=COALESCE(p.owner_id,0) AND ((lower(p.path)=lower(s.path) "
             "AND (CAST(s.is_folder AS INTEGER)=1 OR s.page_id IS NULL OR s.page_id=p.id)) "
             "OR (CAST(s.is_folder AS INTEGER)=1 AND left(lower(p.path), length(lower(s.path))+1)=lower(s.path)||'/'))")


def wsh_live(a="s"):
    """SQL: the share is neither revoked nor expired (one parameter: now as UTC ISO)."""
    return f"{a}.revoked_at IS NULL AND ({a}.expires_at IS NULL OR {a}.expires_at>?)"


def wsh_locked(c, oid, owner):
    return bool(wke_mode(c, oid, owner)[0])


def wsh_open_sql():
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
# the live rows (wsh_rows) and the ended mark (wsh_gone); a = wiki_shares. Private spaces: unchanged. 2.560.0 (#4698 c): and only
# while the maker still has a writing role there (a maker made guest / read-only / accounting no longer sees the folder)
WSH_MAKER = ("({a}.org_id IS NULL OR EXISTS (SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id={a}.org_id "
             "AND m.user_id={a}.created_by AND m.role IN ('admin','member') AND u.disabled=0))")


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
         "ended": r["id"] in gone,  # 2.126.2 B (#2358): its maker is no longer in the organisation -- the link does not work
         "images": bool(r["images"])}  # 2.380 H (#2356): the pictures of the file store embedded in the page are shown
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


# ---------------------------------------------------------------- 2.937.0 (#5244, stage 7c): person shares = core shares
# A person share of the knowledge dialog is a row of fs_shares ('view') on the page's reference node, a folder share one on the
# folder's node (+ "pair": one on the node of the page of the same name, which the folder share covers too). The share's card
# data (the switch "show pictures", the address typed in, folder or page) is a row of wiki_share_cards (fs_share_id, gone with
# the share: ON DELETE CASCADE). The dialog's id of such a share is "p<fs_shares id>" (the links keep their number of
# wiki_shares). Revoking puts the share (and its pair) into obj_revoked with the card in its row ("wiki_card"); the Undo puts
# them back under the same ids (core/objects.py obj_node_reshare). wiki_shares holds public links only.
WSH_PID = re.compile(r"p([1-9]\d{0,17})")
# Fable review of 2.937 F2: a share of a person on a page's node without a card of its own is listed too (as a page share) --
# the pair of a folder share whose folder went to the trash / was deleted, a share made in the file store's dialog -- unless
# it is the pair of a card listed anyway (its folder's node live): what opens a page stays visible and can be ended here.
WSH_PEOPLE_SQL = ("SELECT f.id, f.node_id, f.user_id, f.role, f.expires_at, f.created_by, f.created_at, k.folder, k.pair_id, k.images, "
                  "k.email, n.kind AS nkind, n.ref_kind, n.ref_id, n.owner_id AS nowner FROM fs_shares f JOIN fs_nodes n ON n.id=f.node_id "
                  "LEFT JOIN wiki_share_cards k ON k.fs_share_id=f.id WHERE n.org_id IS NULL AND " + live_sql("n") + " "
                  "AND f.user_id IS NOT NULL AND (k.fs_share_id IS NOT NULL OR (n.kind='ref' AND n.ref_kind='wiki' AND NOT EXISTS "
                  "(SELECT 1 FROM wiki_share_cards k2 JOIN fs_shares f2 ON f2.id=k2.fs_share_id JOIN fs_nodes n2 ON n2.id=f2.node_id "
                  "WHERE k2.pair_id=f.id AND " + live_sql("n2") + ")))")


def _wsh_entries(c, rows, revoked=None):
    """Person shares (raw rows: the share + its card + its node) -> entries shaped like a row of wiki_shares (kind person,
    id "p<share id>", path / is_folder / page_id from the node now: they follow renames and moves in the tree by themselves).
    A share whose page is in the trash or whose folder is no folder of a knowledge tree any more is left out."""
    from .wkfolder import WKF_KIND, wkf_folder_path
    pids = [int(x["ref_id"]) for x in rows if x["nkind"] == "ref" and x["ref_kind"] == WKF_KIND]
    pages = {p["id"]: p for p in c.execute(f"SELECT id, path, owner_id FROM wiki_pages WHERE id = ANY(CAST(? AS BIGINT[])) AND {live_sql()}",
                                           (pids,))} if pids else {}
    out = []
    for x in rows:
        page = pages.get(int(x["ref_id"])) if x["nkind"] == "ref" and x["ref_kind"] == WKF_KIND and x["ref_id"] else None
        path = page["path"] if page else (wkf_folder_path(c, x["node_id"]) if x["nkind"] == "folder" else None)
        if not path:
            continue
        folder = bool(x["folder"]) or page is None
        out.append({"id": f"p{int(x['id'])}", "fid": int(x["id"]), "node_id": x["node_id"], "pair_id": x["pair_id"], "kind": "person",
                    "org_id": None, "owner_id": x["nowner"], "path": path, "is_folder": folder, "page_id": None if folder else page["id"],
                    "user_id": x["user_id"], "role": x["role"], "token": x["email"] or "", "token_hash": None, "images": bool(x["images"]),
                    "expires_at": x["expires_at"] or None, "created_by": x["created_by"], "created_at": x["created_at"],
                    "revoked_at": revoked, "views": 0, "last_used_at": None})
    return out


def wsh_people(c, owner, live=True, fid=None):
    """The person shares of the private knowledge space of owner (entries, _wsh_entries); live: not expired; fid: just that one."""
    if not owner:
        return []
    q, a = WSH_PEOPLE_SQL + " AND n.owner_id=?", [int(owner)]
    if live:
        q += " AND (f.expires_at IS NULL OR f.expires_at>?)"
        a.append(iso(now_utc()))
    if fid is not None:
        q += " AND f.id=?"
        a.append(int(fid))
    return _wsh_entries(c, c.execute(q + f" ORDER BY f.id LIMIT {WSH_MAX * 2}", a).fetchall())


def wsh_rows(c, oid, owner, live=True):
    """The shares of a space: its public links (wiki_shares) and, in a private space, its person shares (wsh_people)."""
    w = "COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=? AND revoked_at IS NULL AND kind='link'"
    a = [oid or 0, 0 if oid else owner]
    if live:  # 2.126.2 B (#2358): a link whose maker left the organisation counts as ended too (mark, WSH_MAX)
        w += " AND (expires_at IS NULL OR expires_at>?) AND " + WSH_MAKER.format(a="wiki_shares")
        a.append(iso(now_utc()))
    links = c.execute(f"SELECT * FROM wiki_shares WHERE {w} ORDER BY id LIMIT {WSH_MAX * 2}", a).fetchall()
    return list(links) + (wsh_people(c, owner, live) if not oid and owner else [])


def wsh_covers(r, path, pid=None):
    p, s = path.lower(), r["path"].lower()
    if p == s and not r["is_folder"] and pid is not None and r["page_id"] is not None:  # 2.360.0 D (#2496): WSH_COVER
        return r["page_id"] == pid
    return p == s or (bool(r["is_folder"]) and p.startswith(s + "/"))


def wsh_mark(c, oid, uid, pages):
    """GET /api/wiki: pages a live share covers get shared: 1 (the mark in the tree)."""
    if not pages:
        return
    rows = wsh_rows(c, oid, uid)
    if not rows:
        return
    for d in pages:
        if any(wsh_covers(r, d["path"], d.get("id")) for r in rows):
            d["shared"] = 1


def wsh_count(c, r):
    """GET /api/wiki/pages/<id>: the number of live shares that cover the page (its mark)."""
    if r["path"].startswith("e2e1:"):
        return 0
    return sum(1 for s in wsh_rows(c, r["org_id"], r["owner_id"]) if wsh_covers(s, r["path"], r["id"]))


def wsh_repath(c, oid, owner, old, new, folder):
    """A page (folder False) or a folder (True: every share at or below it) got another name: the links follow (also
    revoked ones, so an Undo of the revoke finds its page). 2.937.0 (#5244): a person share lies on the node, which follows."""
    for r in c.execute("SELECT id, path, is_folder FROM wiki_shares WHERE COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=? AND kind='link'",
                       (oid or 0, 0 if oid else owner)).fetchall():
        p = r["path"]
        if folder and (p.lower() == old.lower() or p.lower().startswith(old.lower() + "/")):
            np = new + p[len(old):]
        elif not folder and not r["is_folder"] and p.lower() == old.lower():
            np = new
        else:
            continue
        c.execute("UPDATE wiki_shares SET path=? WHERE id=?", (np, r["id"]))


def wsh_end_moved(c, oid, owner, paths, folder=None, dry=False):
    """Pages left the space (wkmove.py): their page shares end, and the shares of a folder that moved as a whole.
    2.273.0 B (#3042): -> how many end; dry = only count them (the dry run names them)."""
    keys = {p.lower() for p in paths if p}
    f = folder.lower() if folder else None
    ts = iso(now_utc())
    n = 0
    for r in wsh_rows(c, oid, owner, live=dry):
        p = r["path"].lower()
        if (not r["is_folder"] and p in keys) or (f and (p == f or p.startswith(f + "/"))):
            n += 1
            if dry:
                continue
            if r["kind"] == "person":
                wsh_end(c, me(), r["fid"])  # 2.937.0 (#5244): the core share (+ pair) into obj_revoked
            else:
                c.execute("UPDATE wiki_shares SET revoked_at=? WHERE id=?", (ts, r["id"]))
    return n


def _wsh_tree(c, owner):
    """{lower folder path: folder node} of the private knowledge tree of owner (empty without one)."""
    from .wkfolder import _subtree, _walk, wkf_root
    root = wkf_root(c, owner, None)
    if not root:
        return {}
    rows = _subtree(c, root)
    fp = _walk(rows, root)
    return {fp[n["id"]][0].lower(): n for n in rows if n["kind"] == "folder" and n["id"] != root and n["id"] in fp and not fp[n["id"]][1]}


def wsh_nodes(c, r):
    """The reference nodes a person share of a private space (owner_id, path, is_folder, page_id) lies on: [page node] for a
    page share, [folder node, node of the page of the same name] for a folder share (each when there)."""
    from .wkfolder import wkf_node_of
    owner = r["owner_id"]
    out = []
    if not r["is_folder"]:
        pid = r["page_id"]
        if pid is None:  # a row of an older version (by name): the live page of that name
            x = c.execute("SELECT id FROM wiki_pages WHERE org_id IS NULL AND owner_id=? AND lower(path)=lower(?) AND deleted_at IS NULL",
                          (owner, r["path"])).fetchone()
            pid = x[0] if x else None
        n = wkf_node_of(c, pid) if pid else None
        return [n] if n is not None else []
    f = _wsh_tree(c, owner).get(r["path"].lower())
    if f is not None:
        out.append(f)
    x = c.execute("SELECT id FROM wiki_pages WHERE org_id IS NULL AND owner_id=? AND lower(path)=lower(?) AND deleted_at IS NULL",
                  (owner, r["path"])).fetchone()
    n = wkf_node_of(c, x[0]) if x else None
    if n is not None:
        out.append(n)
    return out


def _wsh_node(c, fid):
    return c.execute("SELECT n.* FROM fs_nodes n JOIN fs_shares f ON f.node_id=n.id WHERE f.id=?", (int(fid),)).fetchone()


def wsh_end(c, uid, fid, reason="unshare"):
    """2.937.0 (#5244): person share fid of the knowledge dialog ends: it and its pair go into obj_revoked (core/objects.py
    obj_node_unshare, restorable), the card rides along in the row of fid ("wiki_card"). The caller checked who may.
    -> the obj_revoked id of fid (None: no such share)."""
    from ..core.objects import obj_node_unshare
    k = c.execute("SELECT * FROM wiki_share_cards WHERE fs_share_id=?", (int(fid),)).fetchone()
    n = _wsh_node(c, fid)
    if n is None:
        return None
    pair = None
    if k is not None and k["pair_id"]:
        pn = _wsh_node(c, k["pair_id"])
        if pn is not None:
            pair = obj_node_unshare(c, uid, pn, k["pair_id"], kind="wiki", ref_id=pn["ref_id"] if pn["kind"] == "ref" else None,
                                    org=pn["org_id"] or None, reason=reason)  # 2.969.0 (#5644): the pair's row names its space too
    rv = obj_node_unshare(c, uid, n, fid, kind="wiki", ref_id=n["ref_id"] if n["kind"] == "ref" else None, org=n["org_id"] or None, reason=reason)
    if rv:  # Fable F2: a share without a card (listed as a page share) gets an empty one, so its Undo works the same way
        x = c.execute("SELECT row_json FROM obj_revoked WHERE id=?", (rv,)).fetchone()
        d = json.loads(x["row_json"] or "{}")
        d["wiki_card"] = {"folder": bool(k["folder"]), "images": bool(k["images"]), "email": k["email"] or "", "pair": pair} if k is not None \
            else {"folder": False, "images": False, "email": "", "pair": None}
        c.execute("UPDATE obj_revoked SET row_json=? WHERE id=?", (json.dumps(d, default=str), rv))
    return rv


def wsh_revoked(c, fid):
    """The obj_revoked row of person share fid taken back with its card (the newest), None without one."""
    return c.execute("SELECT * FROM obj_revoked WHERE src='fs_shares' AND kind='wiki' AND (CAST(row_json AS JSONB)->>'id')=? "
                     "AND (CAST(row_json AS JSONB)->'wiki_card') IS NOT NULL ORDER BY id DESC LIMIT 1",
                     (str(int(fid)),)).fetchone()


def wsh_news_live(c, uid, actor, path, folder):
    """collab/news.py: the News item "… shared … with you" lives while its person share does (2.937.0, #5244: a live core
    share with its card in actor's private space to uid, of that path -- the node's path now -- and kind)."""
    return any(r["user_id"] == uid and r["path"].lower() == path.lower() and bool(r["is_folder"]) == folder for r in wsh_people(c, actor))


def wsh_fs_unshare(c, uid, n, s, reason="unshare"):  # 2.649.0 (#5051): reason (the boundary repair passes "boundary")
    """2.623.0 (#4778): the file store's dialog takes share row s of node n back (files/web.py files_share_delete,
    files/fsref.py fs_unshare_hooks; the caller checked who may). 2.937.0 (#5244): a person share of the knowledge dialog
    (a card, or the pair of one) ends as a whole (wsh_end: both shares into obj_revoked, the card kept for its Undo); any
    other share of a page's node goes into obj_revoked like in the knowledge dialog."""
    k = c.execute("SELECT fs_share_id FROM wiki_share_cards WHERE fs_share_id=? OR pair_id=? LIMIT 1", (s["id"], s["id"])).fetchone()
    if k is not None:
        wsh_end(c, uid, k[0], reason)
        return True
    if not (n["kind"] == "ref" and n["ref_kind"] == "wiki"):
        return False  # a folder share of no card: the file store's way (deleted as before)
    from ..core.objects import obj_node_unshare
    # review F1 (2.623.0): the row of an organisation's page lies under that organisation in obj_revoked (as files/web.py does)
    obj_node_unshare(c, uid, n, s["id"], kind="wiki", ref_id=n["ref_id"] if n["kind"] == "ref" else None, org=n["org_id"] or None, reason=reason)
    return True


def wsh_expiry(v):
    """YYYY-MM-DD (today or later; valid through the end of that day, server time zone) -> UTC ISO, or None."""
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not valid_date(v) or v < local_now().date().isoformat():
        raise BadInput(tr("The expiry date must be today or later"))
    d = date.fromisoformat(v) + timedelta(days=1)
    return iso(datetime(d.year, d.month, d.day, tzinfo=TZ))


def wsh_images(v):
    """2.380 H (#2356): the switch "show embedded pictures" of a share (default off) -> 1 | 0."""
    if not isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", "images"))
    return 1 if v else 0


# 2.380 H (#2356): a picture of the file store embedded in a shared page: ![label](/api/files/nodes/<id>/content)
WSH_NODE_RE = re.compile(r"/api/files/nodes/(\d{1,15})/content$")
WSH_NODE_IMG_RE = re.compile(r"!\[[^\[\]\n]*\]\(\s*<?/api/files/nodes/(\d{1,15})/content>?")
# 2.380 (#2356 review): code shows as text -- a picture named in a fenced block or in `code` is not embedded
WSH_CODE_RE = re.compile(r"^[ \t]*(```|~~~).*?(?:^[ \t]*\1[^\n]*$|\Z)|`[^`\n]*`", re.S | re.M)


def wsh_img_nodes(c, shares, page, text, only=None):
    """2.380 H (#2356): {node id: (node, version)} of the file store pictures a share may show in a page -- only with the switch
    (images) of one of the shares, only pictures embedded in the page's text, of the page's own space (wem_visible), that
    the person who made that share may still see now, an image type, never in a locked (end-to-end encrypted) folder."""
    makers = sorted({s["created_by"] for s in shares if s["images"] and s["created_by"]})
    ids = sorted({int(m.group(1)) for m in WSH_NODE_IMG_RE.finditer(WSH_CODE_RE.sub("", text or "")) if int(m.group(1)) < 2 ** 62})[:200]
    if only is not None:  # one picture asked for: check just that one (review: not up to 200 nodes per fetch)
        ids = [i for i in ids if i == only]
    out = {}
    if not makers or not ids:
        return out
    from ..files.extlinks import XL_IMG
    # the share's guest / the public link reads as somebody else: the maker's rights on the file store decide (deliberately
    # across the reader's context, for the pictures embedded in this shared page only)
    with system_ctx(c):
        for nid in ids:
            if not any(wem_visible(c, u, nid, page) for u in makers) or fl_is_locked(c, nid):
                continue
            n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
            v = fs_version_row(c, nid, None)
            # 2.674.0 (#4382 finding 2): raster types only (an SVG of the file store is no picture here, see wsh_img_send)
            if n and v and (v["mime"] or n["mime"] or "") in XL_IMG:
                out[nid] = (n, v)
    return out


def wsh_img_send(c, n, v, public):
    """2.380 H (#2356): the bytes of a shared file store picture (scanned, a sandbox like wsh_send; public: never cached)."""
    full = os.path.join(ATT_DIR, v["path"])
    with system_ctx(c):  # the scan state and the space key of the maker's file store (the reader is a guest / nobody)
        sc_guard(c, "fs", n["id"], v["no"])
        if not os.path.isfile(full):
            raise Denied(404)
        # 2.674.0 (#4382 finding 2): only a raster picture whose bytes start like one (the pattern of extlinks XL_IMG);
        # anything else (an SVG, a file named .png that is none) is 404
        from ..files.extlinks import XL_IMG, XL_PREVIEW_MB
        mime = v["mime"] or n["mime"] or ""
        # 2.674.0 (#4382 review F1): read into memory only up to the preview limit of extlinks (public route)
        small = os.path.getsize(full) <= XL_PREVIEW_MB * 1024 * 1024
        data = oc_read_file(c, full) if mime in XL_IMG and small else b""
        if not data.startswith(XL_IMG.get(mime, (b"\0\0\0\0",))) or (mime == "image/webp" and data[8:12] != b"WEBP"):
            raise Denied(404)
        resp = Response(data, mimetype=mime)
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store, private"
    if public:
        resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def wsh_target(c, uid, b, write):
    """(org id, owner, path, is_folder) of {page_id} | {space, folder}; 404 unless the person manages its shares -- listing
    them too (2.200.0 F, #2747 review B1/B2: they hold link tokens, paths, people): who writes in its space (private: its
    owner), never through a share of its folders."""
    if b.get("page_id") not in (None, ""):
        try:
            pid = int(b.get("page_id"))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "page_id"))
        r = wiki_need(c, pid, write=write)
        from .wkfolder import wkf_base
        if wkf_base(c, uid, r) != "edit":
            raise Denied(404)
        return r["org_id"], r["owner_id"], r["path"], False
    oid = wiki_space(c, uid, b.get("space"), write=True)
    if b.get("folder") in (None, ""):
        return oid, None if oid else uid, None, True
    path = wiki_clean_path(b.get("folder"))
    owner = None if oid else uid
    if not c.execute("SELECT 1 FROM wiki_pages p WHERE p.deleted_at IS NULL AND COALESCE(p.org_id,0)=? AND COALESCE(p.owner_id,0)=? "
                     "AND (lower(p.path)=lower(?) OR left(lower(p.path), length(lower(?))+1)=lower(?)||'/') LIMIT 1",
                     (oid or 0, owner or 0, path, path, path)).fetchone():
        raise Denied(404)
    return oid, owner, path, True


def wsh_sid(sid):
    """The dialog's id: a number = a public link (wiki_shares), "p<n>" = a person share (fs_shares n, 2.937.0 #5244)
    -> ("link", n) | ("person", n); 404 otherwise."""
    s = str(sid)
    if s.isdigit() and 0 < len(s) <= 18:
        return "link", int(s)
    m = WSH_PID.fullmatch(s)
    if not m:
        raise Denied(404)
    return "person", int(m.group(1))


def wsh_need(c, sid):
    """A share the person may manage (the write right in its space); 404 otherwise. A person share: a live one of the
    asker's own private space (2.937.0 #5244: the node is theirs)."""
    kind, n = wsh_sid(sid)
    uid = me()
    if kind == "person":
        r = next(iter(wsh_people(c, uid, live=False, fid=n)), None)
        if r is None:
            raise Denied(404)
        return r
    r = c.execute("SELECT * FROM wiki_shares WHERE id=? AND kind='link'", (n,)).fetchone()
    if not r or (r["org_id"] is None and r["owner_id"] != uid):
        raise Denied(404)
    if r["org_id"] is not None:
        wiki_space(c, uid, r["org_id"], write=True)
    return r


def _wsh_revoked_entry(c, uid, fid):
    """The entry of person share fid taken back with its card, when it lay in uid's private space; None otherwise."""
    rv = wsh_revoked(c, fid)
    if rv is None:
        return None
    s = json.loads(rv["row_json"])
    n = c.execute("SELECT * FROM fs_nodes WHERE id=?", (int(s.get("node_id") or 0),)).fetchone()
    if n is None or n["org_id"] is not None or n["owner_id"] != uid:
        return None
    k = s.get("wiki_card") or {}
    raw = {"id": int(s["id"]), "node_id": n["id"], "user_id": s.get("user_id"), "role": s.get("role"), "expires_at": s.get("expires_at"),
           "created_by": s.get("created_by"), "created_at": s.get("created_at"), "folder": k.get("folder"), "pair_id": None,
           "images": k.get("images"), "email": k.get("email") or "", "nkind": n["kind"], "ref_kind": n["ref_kind"], "ref_id": n["ref_id"],
           "nowner": n["owner_id"]}
    return next(iter(_wsh_entries(c, [raw], revoked=rv["created_at"])), None)


def wsh_one(c, sid):
    kind, n = wsh_sid(sid)
    if kind == "person":
        r = next(iter(wsh_people(c, me(), live=False, fid=n)), None) or _wsh_revoked_entry(c, me(), n)
        if r is None:
            raise Denied(404)
        return wsh_dict(c, r, user_names(c, {r["created_by"], r["user_id"]} - {None}))
    r = c.execute("SELECT * FROM wiki_shares WHERE id=?", (n,)).fetchone()
    return wsh_dict(c, r, user_names(c, {r["created_by"], r["user_id"]} - {None}), gone=wsh_gone(c, [r]))


@app.get("/api/wiki/shares")
def wsh_list():
    """?page=<id> | ?space=&folder=<path> -- the shares that cover the page / folder (direct: named exactly here, else from a
    folder above); ?space= alone: every live share of the space. + enabled (public links on), locked, person (person shares
    possible: a private space)."""
    c = db()
    uid = me()
    q = {"page_id": request.args.get("page"), "space": request.args.get("space"), "folder": request.args.get("folder")}
    oid, owner, path, folder = wsh_target(c, uid, q, False)
    rows = wsh_rows(c, oid, owner, live=False)
    if path is not None:
        pid = None if folder else int(q["page_id"])
        rows = [r for r in rows if wsh_covers(r, path, pid) or (folder and r["path"].lower().startswith(path.lower() + "/"))]
    names = user_names(c, ({r["created_by"] for r in rows} | {r["user_id"] for r in rows}) - {None})
    locked = wsh_locked(c, oid, owner)
    gone = wsh_gone(c, rows)
    return jsonify(enabled=public_links_on(c, "wiki"), locked=locked, person=oid is None and not locked, space=wiki_space_key(oid),
                   shares=[] if locked else [wsh_dict(c, r, names, (path, folder) if path is not None else None, gone) for r in rows])


@app.post("/api/wiki/shares")
def wsh_create():
    """{page_id | space + folder, kind: person | link, user_id | email (person), expires: YYYY-MM-DD | null} -> the share
    (a link with its url). A person who already has a live share of the same page / folder: its expiry changes."""
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
        return jsonify(error=tr("Pages of a workspace encrypted in the browser cannot be shared."), code="wiki_e2e_share"), 409
    exp = wsh_expiry(b.get("expires"))
    imgs = wsh_images(b.get("images", False))
    if len(wsh_rows(c, oid, owner)) >= WSH_MAX:
        raise BadInput(tr("Too many shares in this workspace (at most {0})", WSH_MAX))
    ts = iso(now_utc())
    page = None if folder else int(b["page_id"])  # 2.360.0 D (#2496): bound to the page (WSH_COVER); wsh_target checked it
    if kind == "link":
        if not public_links_on(c, "wiki"):
            return jsonify(error=tr("Public links are switched off on this server")), 409
        tok = secrets.token_urlsafe(24)  # 192 bits, the shape of the list links (lists/public.py PUB_TOKEN_RE)
        h = _token_hash(tok)
        sid = insert_id(c, "INSERT INTO wiki_shares(org_id,owner_id,path,is_folder,kind,token_hash,token,expires_at,created_by,created_at,page_id,images) "
                           "VALUES(?,?,?,?,'link',?,?,?,?,?,?,?)", (oid, owner, path, 1 if folder else 0, h, seal(c, WSH_SEAL + h, tok), exp, uid, ts, page, imgs))
        print("wiki public link created", sid, flush=True)
    else:
        if oid is not None:
            return jsonify(error=tr("Every member of the organisation reads these pages already. For people outside it, use a public link."),
                           code="wiki_share_org"), 409
        who = wsh_person(c, uid, b)
        by_mail = bool(b.get("email") and not b.get("user_id"))
        if who is None:  # by e-mail address: nothing happens, nothing is revealed
            return jsonify(ok=True, by_email=True)
        # 2.937.0 (#5244, stage 7c): the share is a core share on the page's / folder's node (the tree first: a page made just
        # now), the card (folder, pictures, the address typed in) rides on it; the same person again: expiry / pictures change
        from ..core.objects import obj_node_share
        from .wkfolder import wkf_sync
        wkf_sync(c, uid, None)
        nodes = wsh_nodes(c, {"owner_id": owner, "path": path, "is_folder": folder, "page_id": page})[:2]
        if not nodes:
            raise Denied(404)
        had = c.execute("SELECT 1 FROM fs_shares f JOIN wiki_share_cards k ON k.fs_share_id=f.id WHERE f.node_id=? AND f.user_id=? "
                        "AND (f.expires_at IS NULL OR f.expires_at>?)", (nodes[0]["id"], who, ts)).fetchone()
        ids = [obj_node_share(c, uid, n, "user_id", who, "view", exp, None) for n in nodes]
        sid = f"p{ids[0]}"
        # 2.123.0 (#2104): by e-mail address the typed address is kept (sealed) and shown instead of the account's name
        mail = seal(c, WSH_SEAL + "mail", str(b["email"]).strip()[:200]) if by_mail else ""
        pair = ids[1] if len(ids) > 1 and not c.execute("SELECT 1 FROM wiki_share_cards WHERE fs_share_id=?", (ids[1],)).fetchone() else None
        c.execute("INSERT INTO wiki_share_cards(fs_share_id,folder,pair_id,images,email) VALUES(?,?,?,?,?) ON CONFLICT (fs_share_id) "
                  "DO UPDATE SET folder=excluded.folder, pair_id=COALESCE(excluded.pair_id, wiki_share_cards.pair_id), images=excluded.images",
                  (ids[0], bool(folder), pair, bool(imgs), mail))
        if not had:  # 2.126.2 B (#2355): the same live share again: no second News item
            # a News item for exactly that person (the sharing row of their settings; no push); only the path they may read now
            news_add(c, who, "wiki_shared", data={"path": path, "folder": bool(folder)})
    bump(c)
    c.commit()
    if kind != "link" and by_mail:  # the same answer as for an unknown address: whether an account exists stays hidden
        return jsonify(ok=True, by_email=True)
    return jsonify(wsh_one(c, sid)), 201


def wsh_person(c, uid, b):
    """The person of {user_id} (404 when unknown / not visible / an agent / oneself) or {email} (None when there is no such
    person: the answer must not reveal it)."""
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
        raise Denied(404, tr("unknown person"))
    return who


@app.patch("/api/wiki/shares/<sid>")
def wsh_update(sid):
    """{expires: YYYY-MM-DD | null, images: bool}"""
    c = db()
    r = wsh_need(c, sid)
    b = body()
    if r["revoked_at"]:
        raise Denied(404)
    if "expires" in b or "images" in b:
        exp = wsh_expiry(b.get("expires")) if "expires" in b else None
        imgs = wsh_images(b["images"]) if "images" in b else None  # 2.380 H (#2356)
        if r["kind"] == "person":  # 2.937.0 (#5244): the core share (+ its pair) and the card
            if "expires" in b:
                from ..core.objects import obj_node_share
                for fid in (r["fid"], r["pair_id"]):
                    n = _wsh_node(c, fid) if fid else None
                    if n is not None:
                        obj_node_share(c, me(), n, "user_id", r["user_id"], r["role"] if r["role"] in ("view", "edit") else "view", exp, None)
            if "images" in b:  # Fable F2: a share listed without a card gets one here
                c.execute("INSERT INTO wiki_share_cards(fs_share_id,folder,images,email) VALUES(?,?,?,'') ON CONFLICT (fs_share_id) "
                          "DO UPDATE SET images=excluded.images", (r["fid"], bool(r["is_folder"]), bool(imgs)))
        else:
            if "expires" in b:
                c.execute("UPDATE wiki_shares SET expires_at=? WHERE id=?", (exp, r["id"]))
            if "images" in b:
                c.execute("UPDATE wiki_shares SET images=? WHERE id=?", (imgs, r["id"]))
        bump(c)
        c.commit()
    return jsonify(wsh_one(c, sid))


@app.delete("/api/wiki/shares/<sid>")
def wsh_revoke(sid):
    """Revoke: the link / the person's access ends at once (the app's Undo: POST /api/wiki/shares/<id>/restore)."""
    c = db()
    kind, n = wsh_sid(sid)
    if kind == "person" and not wsh_people(c, me(), live=False, fid=n) and _wsh_revoked_entry(c, me(), n):
        return jsonify(wsh_one(c, sid))  # ended already (the Undo's second press)
    r = wsh_need(c, sid)
    if r["kind"] == "person":
        wsh_end(c, me(), r["fid"])  # 2.937.0 (#5244): the core share (+ pair) into obj_revoked, the card with it
        bump(c)
        c.commit()
    elif not r["revoked_at"]:
        c.execute("UPDATE wiki_shares SET revoked_at=? WHERE id=?", (iso(now_utc()), r["id"]))
        bump(c)
        c.commit()
    return jsonify(wsh_one(c, sid))


@app.post("/api/wiki/shares/<sid>/restore")
def wsh_restore(sid):
    """Undo of a revoke (the same token: the link works again; a person share comes back under the same id)."""
    c = db()
    uid = me()
    kind, n = wsh_sid(sid)
    if kind == "person":
        if wsh_people(c, uid, live=False, fid=n):
            return jsonify(wsh_one(c, sid))  # live already
        r = _wsh_revoked_entry(c, uid, n)
        if r is None:
            raise Denied(404)
        if wsh_locked(c, None, uid):
            return jsonify(error=tr("Pages of a workspace encrypted in the browser cannot be shared."), code="wiki_e2e_share"), 409
        u = c.execute("SELECT kind, disabled FROM users WHERE id=?", (int(r["user_id"] or 0),)).fetchone()
        if u is None or u["disabled"] or (u["kind"] or "user") == "agent" or r["user_id"] == uid:
            raise Denied(409, tr("unknown person"))
        rv = wsh_revoked(c, n)
        k = json.loads(rv["row_json"]).get("wiki_card") or {}
        from ..core.objects import obj_node_reshare
        back = obj_node_reshare(c, rv["id"], owner=uid, org=None)  # 2.969.0 (#5644): the node must still be uid's private one
        if back is None:  # the person has a share of that node again (or the node went): nothing to bring back
            c.commit()
            raise Denied(409, tr("Already shared"))
        pair = obj_node_reshare(c, k["pair"], owner=uid, org=None) if k.get("pair") else None  # #5644: the pair too (else 409, all rolled back)
        c.execute("INSERT INTO wiki_share_cards(fs_share_id,folder,pair_id,images,email) VALUES(?,?,?,?,?) ON CONFLICT (fs_share_id) DO NOTHING",
                  (n, bool(k.get("folder")), pair[0] if pair else None, bool(k.get("images")), k.get("email") or ""))
        bump(c)
        c.commit()
        return jsonify(wsh_one(c, sid))
    r = wsh_need(c, sid)
    if not public_links_on(c, "wiki"):
        return jsonify(error=tr("Public links are switched off on this server")), 409
    if wsh_locked(c, r["org_id"], r["owner_id"]):
        return jsonify(error=tr("Pages of a workspace encrypted in the browser cannot be shared."), code="wiki_e2e_share"), 409
    if r["revoked_at"]:
        c.execute("UPDATE wiki_shares SET revoked_at=NULL WHERE id=?", (r["id"],))
        bump(c)
        c.commit()
    return jsonify(wsh_one(c, sid))


# ---------------------------------------------------------------- the guest: pages shared with me (person shares)
def wsh_reach(c, uid):
    """2.200.0 B (#2747): the pages shared with uid -- the folder / page shares of the knowledge trees uid does not read
    through the space anyway (wkfshare.py; a person card's core share is one of them) -> (rows, {page id: folder info}).
    2.647.0 (#5047): the fallback for person cards not moved yet is gone; 2.937.0 (#5244): so are the cards."""
    from .wkfshare import wkfs_rows
    return wkfs_rows(c, uid)


@app.get("/api/wiki/shared")
def wsh_shared():
    """The pages other people shared with me: id, path, owner, changed; 2.200.0 B (#2747): + role (view | edit), folder (the
    path shown: from the shared folder's name; a person share: the page's path), space, node_id -- and folders (the shared
    folders and their subfolders, where 'edit' may add pages / folders, wkfshare.py)."""
    from .wkfolder import wkf_role
    from .wkfshare import wkfs_folders
    c = db()
    uid = me()
    rows, info = wsh_reach(c, uid)
    names = user_names(c, {r["owner_id"] for r in rows} | {r["updated_by"] for r in rows})
    out = []
    for r in rows:
        x = info.get(r["id"])
        base = r["path"].rsplit("/", 1)[-1]
        out.append({"id": r["id"], "path": (x["folder"] + "/" + base if x["folder"] else base) if x else r["path"],
                    "owner_id": r["owner_id"], "owner_name": names.get(r["owner_id"], ""), "updated_at": r["updated_at"],
                    "updated_by_name": names.get(r["updated_by"], ""), "role": (wkf_role(c, uid, r) or "view") if x else "view",
                    "via": "folder" if x else "person", "space": wiki_space_key(r["org_id"]),
                    "node_id": x["node"]["id"] if x else None, "folder_id": x["node"]["parent_id"] if x and x["folder"] else None})
    return jsonify(pages=out, folders=wkfs_folders(c, uid))


@app.get("/api/wiki/shared/pages/<int:pid>")
def wsh_shared_page(pid):
    """A page shared with me: path, text, its rendered HTML (links only to pages shared with me too, files through
    /api/wiki/shared/files/), its files, owner and change; 404 otherwise."""
    c = db()
    uid = me()
    rows, info = wsh_reach(c, uid)  # 2.200.0 B (#2747): + folder / page shares (also an organisation's pages)
    rows = [r for r in rows if r["owner_id"] or r["id"] in info]
    r = next((x for x in rows if x["id"] == pid), None)
    if not r:
        raise Denied(404)
    same = {x["path"].lower(): x["id"] for x in rows if (x["org_id"], x["owner_id"]) == (r["org_id"], r["owner_id"])}
    files = wsh_files_of(c, list(same.values()))
    d = wiki_dict(r)
    names = user_names(c, {r["owner_id"], r["updated_by"]})
    own = [f for f in files.values() if f["page_id"] == pid]
    imgs = wsh_img_nodes(c, wsh_person_shares(c, uid, pid), r, d["body"])  # 2.380 H (#2356)
    x = info.get(pid)  # 2.200.0 B (#2747): a folder share shows the path from the shared folder on (not the folders above it)
    shown = (x["folder"] + "/" + r["path"].rsplit("/", 1)[-1] if x["folder"] else r["path"].rsplit("/", 1)[-1]) if x else r["path"]
    return jsonify(id=pid, path=shown, body=d["body"], attrs=d["attrs"], updated_at=r["updated_at"], updated_by_name=names.get(r["updated_by"], ""),
                   owner_name=names.get(r["owner_id"], ""), shared=True, role=_shared_role(c, uid, r, info),  # 2.200.0 B (#2747)
                   html=wsh_md(d["body"], lambda p: f"#wsh/{same[p.lower()]}" if p.lower() in same else None,
                               lambda fid: (wsh_file_url("/api/wiki/shared/files/", files[fid]), files[fid]["mime"].startswith("image/"), wsh_wh(files[fid])) if fid in files else None,
                               node=lambda nid: f"/api/wiki/shared/pages/{pid}/img/{nid}" if nid in imgs else None),
                   files=[{"id": f["id"], "name": f["name"], "mime": f["mime"], "size": f["size"], "image": f["mime"].startswith("image/"),
                           "url": wsh_file_url("/api/wiki/shared/files/", f)} for f in own])


@app.get("/api/wiki/shared/files/<int:fid>")
@app.get("/api/wiki/shared/files/<int:fid>/<path:name>")
def wsh_shared_file(fid, name=None):
    c = db()
    files = wsh_files_of(c, [r["id"] for r in wsh_reach(c, me())[0]])  # 2.200.0 B (#2747): + folder / page shares
    if fid not in files:
        raise Denied(404)
    return wsh_send(c, files[fid], public=False)


def wsh_person_shares(c, uid, pid):
    """2.380 H (#2356): the live person shares that give uid the page pid (their switch "show embedded pictures").
    2.937.0 (#5244): the core shares with a card of the knowledge dialog (the card's share or its pair) whose node is the
    page's node or a folder above it, of an owner still active."""
    from ..files.store import fs_chain
    from .wkfolder import wkf_node_of
    n = wkf_node_of(c, pid)
    up = [int(x["id"]) for x in fs_chain(c, n["id"])] if n is not None else []
    if not up:
        return []
    return c.execute("SELECT DISTINCT k.fs_share_id AS id, k.images, f0.created_by FROM wiki_share_cards k "
                     "JOIN fs_shares f0 ON f0.id=k.fs_share_id JOIN fs_shares f ON f.id IN (k.fs_share_id, k.pair_id) "
                     "JOIN fs_nodes nn ON nn.id=f0.node_id JOIN users o ON o.id=nn.owner_id AND o.disabled=0 "
                     "WHERE f.user_id=? AND f.node_id = ANY(CAST(? AS BIGINT[])) AND nn.org_id IS NULL AND (f.expires_at IS NULL OR f.expires_at>?) "
                     "ORDER BY 1", (uid, up, iso(now_utc()))).fetchall()


@app.get("/api/wiki/shared/pages/<int:pid>/img/<int:nid>")
def wsh_shared_img(pid, nid):
    """2.380 H (#2356): a file store picture embedded in a page shared with me, when the share shows pictures; 404 otherwise."""
    c = db()
    uid = me()
    r = next((x for x in wsh_reach(c, uid)[0] if x["id"] == pid), None)
    if not r:
        raise Denied(404)
    got = wsh_img_nodes(c, wsh_person_shares(c, uid, pid), r, wiki_dict(r)["body"], only=nid).get(nid)
    if not got:
        raise Denied(404)
    return wsh_img_send(c, *got, public=False)


def _shared_role(c, uid, r, info):
    """2.200.0 B (#2747): 'edit' only through an edit share of the page's folders (a person share stays read only)."""
    if r["id"] not in info:
        return "view"
    from .wkfolder import wkf_role
    return wkf_role(c, uid, r) or "view"


def wsh_files_of(c, page_ids):
    """{file id: row} of the files of these pages (not in the trash)."""
    if not page_ids:
        return {}
    q = ",".join("?" * len(page_ids))
    return {f["id"]: f for f in c.execute(f"SELECT * FROM wiki_files WHERE page_id IN ({q}) AND deleted_at IS NULL ORDER BY id LIMIT 5000", page_ids)}


def wsh_wh(f):
    """#5227: ' width="…" height="…"' of a page's picture whose size is known (wiki_files.img_w / img_h), else the class of the
    fixed 4:3 box -- either way the shared page keeps its place while the picture loads."""
    w, h = f.get("img_w"), f.get("img_h")
    return f' width="{int(w)}" height="{int(h)}"' if w and h else ' class="wshph"'


def wsh_file_url(base, f):
    return f"{base}{int(f['id'])}/{quote(f['name'], safe='')}"


def wsh_send(c, f, public):
    """A shared file like wikiatt.wka_get (SVG in a sandbox, a file found infected stays locked); public: never cached."""
    import os
    from ..files.scan import sc_guard
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
    member with a writing role, 2.560.0 #4698 c) or None. Then the request reads as nobody, bound to exactly the share's organisation (like the list links)."""
    if not PUB_TOKEN_RE.fullmatch(token or "") or not public_links_on(c, "wiki"):
        return None
    with system_ctx(c):  # resolve the token (one row) across organisations; nothing else is read here
        # 2.560.0 (#4698 c): the maker's rule is WSH_MAKER (a writing role in the organisation), as the dialog's ended mark
        r = c.execute("SELECT s.* FROM wiki_shares s JOIN users u ON u.id=COALESCE(s.owner_id, s.created_by) WHERE s.token_hash=? "
                      "AND s.kind='link' AND u.disabled=0 AND " + WSH_MAKER.format(a="s"), (_token_hash(token),)).fetchone()
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
                     f"AND ((lower(p.path)=lower(?) AND (? OR ?::bigint IS NULL OR p.id=?)) OR (? AND left(lower(p.path), length(lower(?))+1)=lower(?)||'/')) "
                     f"AND {wsh_open_sql()} ORDER BY lower(p.path) LIMIT {WSH_PAGES}",  # 2.360.0 D (#2496): a page share: its page (WSH_COVER)
                     (s["org_id"] or 0, s["owner_id"] or 0, s["path"], bool(s["is_folder"]), s["page_id"], s["page_id"], bool(s["is_folder"]),
                      s["path"], s["path"])).fetchall()


def wsh_lang(c, s):
    return browser_lang() or lang(c, s["owner_id"] or s["created_by"])


def wsh_open(c, token, files=False):
    """Common checks of every /s/w/ request -> (share, None) or (None, response): the rate limits of the list links."""
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
        main = (f'<header><h1>{e(name)}</h1><p class="sub">{e(tr("Shared pages · read-only", lg=lg))}</p></header>'
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
    imgs = wsh_img_nodes(c, [s], r, d["body"])  # 2.380 H (#2356)
    md = wsh_md(d["body"], lambda p: f"{base}/p/{same[p.lower()]}" if p.lower() in same else None,
                lambda fid: (f"{base}/file/{fid}", files[fid]["mime"].startswith("image/"), wsh_wh(files[fid])) if fid in files else None,
                node=lambda nid: f"{base}/img/{pid}/{nid}" if nid in imgs else None)
    own = [f for f in files.values() if f["page_id"] == pid]
    back = f'<p class="wkpback"><a href="{e(base)}">{e(s["path"].split("/")[-1])}</a></p>' if s["is_folder"] else ""
    flist = ('<ul class="files">' + "".join(f'<li><a href="{e(base)}/file/{f["id"]}?dl=1" download rel="nofollow">{e(f["name"])}</a></li>' for f in own)
             + '</ul>') if own else ""
    title = r["path"].split("/")[-1]
    day = local_day(r["updated_at"])  # the day in the server's time zone
    when = short_day(day, lg, year=True) if day else ""
    main = (f'<header>{back}<h1>{e(title)}</h1><p class="sub">{e(tr("Read-only", lg=lg))}'
            + (f' · {e(tr("Changed {0}", when, lg=lg))}' if when else "") + f'</p></header><article class="wkpub">{md}</article>{flist}')
    return pub_html(f"{title} · {APP_NAME}", main, lg)


@app.get("/s/w/<token>/file/<int:fid>")
def wsh_pub_file(token, fid):
    c = db()
    s, bad = wsh_open(c, token, files=True)
    if bad:
        return bad
    files = wsh_files_of(c, [p["id"] for p in wsh_pub_pages(c, s)])
    if fid not in files:
        return pub_gone(wsh_lang(c, s))
    return wsh_send(c, files[fid], public=True)


@app.get("/s/w/<token>/img/<int:pid>/<int:nid>")
def wsh_pub_img(token, pid, nid):
    """2.380 H (#2356): a file store picture embedded in a page of the link, when the link shows pictures (else 404)."""
    c = db()
    s, bad = wsh_open(c, token, files=True)
    if bad:
        return bad
    r = next((p for p in wsh_pub_pages(c, s) if p["id"] == pid), None)
    try:
        got = r and wsh_img_nodes(c, [s], r, wiki_dict(r)["body"], only=nid).get(nid)
    except WikiUnreadable:
        got = None
    if not got:
        raise Denied(404)
    return wsh_img_send(c, *got, public=True)


# ---------------------------------------------------------------- Markdown -> HTML for shared pages (no scripts)
# Everything is escaped first; only these shapes become tags. Links: web / mail addresses; [[Page]] only when that page is
# shared too (else its label as text); /api/wiki/files/<id> only when the file belongs to a shared page; #123 stays text.
WSH_INLINE = re.compile(
    r"`([^`\n]+)`"                                                       # 1 code
    r"|(!?)\[([^\[\]\n]*)\]\(\s*<?([^\s()<>]{1,2000})>?(?:\s+\"[^\"\n]*\")?\s*\)"  # 2 bang, 3 label, 4 address
    r"|(!?)\[\[([^\[\]|#\n]{1,500})(?:#[^\[\]|\n]*)?(?:\|([^\[\]\n]*))?\]\]"  # 5 bang, 6 path, 7 label
    r"|\*\*(.+?)\*\*|__(.+?)__"                                          # 8, 9 strong
    r"|~~(.+?)~~"                                                        # 10 strike
    r"|\*([^*\n]+)\*|(?<!\w)_([^_\n]+)_(?!\w)"                           # 11, 12 emphasis
    r"|(https?://[^\s<>()\"]{2,2000})")                                  # 13 a bare web address
WSH_FILE_RE = re.compile(r"/api/wiki/files/(\d{1,15})(?:/.*)?$")


def wsh_inline(s, link, file, depth=0, node=None):
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
                elif m.group(2) and got[1]:  # #5227: its size reserves the box (else the fixed 4:3 box, app.css .wshph)
                    out.append(f'<img src="{e(got[0])}" alt="{e(label)}" loading="lazy"{got[2] if len(got) > 2 else ' class="wshph"'}>')
                else:
                    out.append(f'<a href="{e(got[0])}?dl=1" rel="nofollow">{wsh_inline(label, link, file, depth + 1, node) or e(addr.rsplit("/", 1)[-1])}</a>')
            elif m.group(2) and node and WSH_NODE_RE.match(addr) and node(int(WSH_NODE_RE.match(addr).group(1))):
                # 2.380 H (#2356): a picture of the file store the share shows (its switch, wsh_img_nodes)
                out.append(f'<img src="{e(node(int(WSH_NODE_RE.match(addr).group(1))))}" alt="{e(label)}" loading="lazy" class="wshph">')  # #5227
            elif re.match(r"(?i)(https?:|mailto:)", addr):
                out.append(f'<a href="{e(addr)}" rel="nofollow noopener noreferrer">{wsh_inline(label, link, file, depth + 1, node) if label else e(addr)}</a>')
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
            out.append(f"<strong>{wsh_inline(m.group(8) or m.group(9), link, file, depth + 1, node)}</strong>")
        elif m.group(10) is not None:
            out.append(f"<del>{wsh_inline(m.group(10), link, file, depth + 1, node)}</del>")
        elif m.group(11) is not None or m.group(12) is not None:
            out.append(f"<em>{wsh_inline(m.group(11) or m.group(12), link, file, depth + 1, node)}</em>")
        else:
            out.append(f'<a href="{e(m.group(13))}" rel="nofollow noopener noreferrer">{e(m.group(13))}</a>')
    out.append(e(s[pos:]))
    return "".join(out)


def wsh_md(text, link, file, depth=0, node=None):
    """HTML of a page's Markdown: headings, paragraphs, lists (with check boxes, shown only), quotes, code blocks, rules,
    simple tables; link(path) -> address | None, file(id) -> (address, is picture) | None."""
    text = re.sub(r"\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", "", text or "", flags=re.S)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    e, out, i, para = html.escape, [], 0, []
    il = lambda s: wsh_inline(s, link, file, depth, node)  # noqa: E731
    if depth > 8:  # 2.123.0 (#2104): quotes nested deeper are shown as text
        return f"<p>{html.escape(text or '')}</p>"

    def flush():
        if para:
            out.append("<p>" + "<br>".join(il(x) for x in para) + "</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        fence = re.match(r"^\s*(```|~~~)\s*([\w-]*)", ln)
        if fence:
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith(fence.group(1)):
                code.append(lines[i])
                i += 1
            # 2.382.0 (#3153): formulas / Mermaid diagrams are drawn in the app (static/js/diagram.js) by their language
            lang = fence.group(2).lower()
            at = f' data-lang="{lang}"' if lang in ("math", "mermaid") else ""
            out.append(f'<pre{at}><code>{e(chr(10).join(code))}</code></pre>')
            i += 1
            continue
        dm = re.match(r"^\s*\$\$(.*?)\$\$\s*$", ln)  # 2.382.0 (#3153): "$$ … $$" on its own line, or a block between two "$$" lines
        if (dm and dm.group(1).strip()) or st == "$$":
            z = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == "$$"), -1) if st == "$$" else i
            if z >= i:
                flush()
                tex = dm.group(1).strip() if z == i else chr(10).join(lines[i + 1:z])
                out.append(f'<pre data-lang="math"><code>{e(tex)}</code></pre>')
                i = z + 1
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
            out.append(f"<blockquote>{wsh_md(chr(10).join(q), link, file, depth + 1, node)}</blockquote>")
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




# ---------------------------------------------------------------- 2.937.0 (#5244, stage 7c): the person rows of wiki_shares go
WSH_ISO = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d{1,6})?(Z|[+-]\d\d:\d\d)?$"
# Fable review of 2.937 F8 (as the tables): an expiry / revoke time the cast cannot read ends the link at the start's time
# instead of opening it (NULL would be "never expires" / "not revoked"); only an unreadable last use becomes NULL
WSH_RETIRE_ALTER = tuple(
    [f"ALTER TABLE wiki_shares ALTER COLUMN {x} TYPE TIMESTAMPTZ USING (CASE WHEN {x} ~ '{WSH_ISO}' THEN CAST({x} AS TIMESTAMPTZ) "
     f"WHEN {x} IS NULL OR {x}='' THEN NULL ELSE CURRENT_TIMESTAMP END)" for x in ("expires_at", "revoked_at")]
    + ["ALTER TABLE wiki_shares ALTER COLUMN last_used_at TYPE TIMESTAMPTZ USING (CASE WHEN last_used_at ~ '" + WSH_ISO + "' "
       "THEN CAST(last_used_at AS TIMESTAMPTZ) END)"]
    + [f"ALTER TABLE wiki_shares ALTER COLUMN created_at TYPE TIMESTAMPTZ USING (CASE WHEN created_at ~ '{WSH_ISO}' "
       "THEN CAST(created_at AS TIMESTAMPTZ) ELSE CURRENT_TIMESTAMP END)",
       "ALTER TABLE wiki_shares ALTER COLUMN is_folder DROP DEFAULT, ALTER COLUMN is_folder TYPE BOOLEAN USING (is_folder<>0), "
       "ALTER COLUMN is_folder SET DEFAULT false"])


def _wsh_old(c, every=False):
    """The live person rows of wiki_shares (a stage before 7c) of active owners in spaces without the lock. every (Fable F3):
    of every owner -- a card gives no right, it only keeps the dialog's data of a core share that is there anyway (an owner
    disabled at the start keeps it for the day the account is back); the filter only guards the making of new shares."""
    ts = iso(now_utc())
    rows = c.execute("SELECT s.*, u.disabled AS owner_off FROM wiki_shares s JOIN users u ON u.id=s.owner_id WHERE s.kind='person' "
                     "AND s.org_id IS NULL AND s.user_id IS NOT NULL AND s.revoked_at IS NULL AND (s.expires_at IS NULL OR s.expires_at>?) "
                     "ORDER BY s.id", (ts,)).fetchall()
    if every:
        return rows
    return [r for r in rows if not r["owner_off"] and not wsh_locked(c, None, r["owner_id"])]  # a locked space shares nothing


def _wsh_held(c, n, who):
    """The share person who holds on node n already (the oldest), None without one (Fable F5)."""
    x = c.execute("SELECT id FROM fs_shares WHERE node_id=? AND user_id=? ORDER BY id LIMIT 1", (n["id"], who)).fetchone()
    return x[0] if x else None


def _wsh_have(c, fid):
    return bool(fid) and c.execute("SELECT 1 FROM fs_shares WHERE id=?", (int(fid),)).fetchone() is not None


def wsh_carry(c):
    """Step 2 (every start while wiki_shares.core_id is there): the last forward copy -- a live person row without a core
    share gets one when its page / folder has a node (the tree checked first) -- and every live person row with a core
    share gets its card (wiki_share_cards: folder, pictures, the address typed in, the pair). Nothing is taken back.
    -> {"copied": n, "cards": m}."""
    from ..core.objects import obj_node_share
    from .wkfolder import WKF_SEEN, wkf_sync
    out = {"copied": 0, "cards": 0}
    with system_ctx(c):  # every person's private space (a start-up step)
        old = _wsh_old(c)
        for o in sorted({r["owner_id"] for r in old if not r["core_id"] and not r["core_id2"]}):
            try:
                with c.savepoint():
                    WKF_SEEN.pop(f"u{int(o)}", None)
                    wkf_sync(c, o, None)
            except Exception as e:  # noqa: BLE001  a tree that cannot be checked: its rows count as left (start check)
                print(f"WARNING knowledge tree of account {int(o)} not checked (#5244): {type(e).__name__}", flush=True)
        for r in old:
            if r["core_id"] or r["core_id2"]:
                continue
            try:
                with c.savepoint():
                    # Fable F5: a share the person holds on the node already stays as it is (role, expiry): nothing is taken back
                    ids = [_wsh_held(c, n, r["user_id"]) or obj_node_share(c, r["created_by"] or r["owner_id"], n, "user_id", r["user_id"],
                                                                        "view", r["expires_at"], None)
                           for n in wsh_nodes(c, r)[:2]]
                    if ids:
                        c.execute("UPDATE wiki_shares SET core_id=?, core_id2=? WHERE id=?", (ids[0], ids[1] if len(ids) > 1 else None, r["id"]))
                        out["copied"] += 1
            except Denied:  # too many shares on the node: the row counts as left (start check)
                print(f"WARNING knowledge share {int(r['id'])} found no room on its node (#5244)", flush=True)
        for r in _wsh_old(c, every=True):  # Fable F3: the cards of every owner (a disabled one too)
            main = r["core_id"] if _wsh_have(c, r["core_id"]) else r["core_id2"] if _wsh_have(c, r["core_id2"]) else None
            if main is None:
                continue  # ended elsewhere (its core shares were taken back): no right, no card
            pair = r["core_id2"] if main == r["core_id"] and _wsh_have(c, r["core_id2"]) else None
            out["cards"] += c.execute("INSERT INTO wiki_share_cards(fs_share_id,folder,pair_id,images,email) VALUES(?,?,?,?,?) "
                                      "ON CONFLICT (fs_share_id) DO NOTHING",
                                      (main, bool(r["is_folder"]), pair, bool(r["images"]), r["token"] or "")).rowcount
    return out


def wsh_left(c):
    """The start check of stage 7c: live person rows of wiki_shares that hold a right the core does not carry with a card --
    a core share without its card, or no core share at all while the page / folder has a node (the forward copy failed)."""
    n = 0
    with system_ctx(c):
        live = {r["id"] for r in _wsh_old(c)}
        for r in _wsh_old(c, every=True):  # Fable F3: a card is checked for every owner, the copy only where wsh_carry copies
            main = r["core_id"] if _wsh_have(c, r["core_id"]) else r["core_id2"] if _wsh_have(c, r["core_id2"]) else None
            if main is not None:
                n += not c.execute("SELECT 1 FROM wiki_share_cards WHERE fs_share_id=?", (main,)).fetchone()
            elif not r["core_id"] and not r["core_id2"] and r["id"] in live:
                n += bool(wsh_nodes(c, r))
    return n


def _wsh_prune(c):
    return c.execute("DELETE FROM wiki_shares WHERE kind<>'link'").rowcount


def _wsh_alert(n, tables):
    from ..collab.tcxcore import TCX_RETIRE_WAITS  # the one text of the admins' alert of stage 7
    aa_now("storage", "kern5244:" + ",".join(tables), TCX_RETIRE_WAITS, (int(n), ", ".join(tables)))


def wsh_retire(c):
    """2.937.0 (#5244, core/objhooks.START, every start until done): wsh_carry, then the start check and the one-way step
    (core/kernretire.py kern_retire_rows): the person rows of wiki_shares go, core_id / core_id2 are dropped, the times
    become TIMESTAMPTZ and is_folder BOOLEAN, the back limit rises. {} once the columns are gone (a catalog read)."""
    if not kern_retire_due(c, "wiki_shares", ("core_id", "core_id2"), "created_at"):  # Fable F1: done = TIMESTAMPTZ
        return {}
    out = wsh_carry(c)
    out.update(kern_retire_rows(c, "wiki_shares", ("core_id", "core_id2"), wsh_left, "knowledge shares, stage 7c (#5244)",
                                prune=_wsh_prune, alter=WSH_RETIRE_ALTER, alert=_wsh_alert))
    return out


objhooks.START.append(("kern5244_wiki", False, wsh_retire))  # 2.937.0 (#5244): every start until done (one catalog read afterwards)
fs_unshare_hooks.append(wsh_fs_unshare)  # 2.623.0 (#4778)
