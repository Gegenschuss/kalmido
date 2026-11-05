"""2.508.0 (#4301): an account's deletion and what it shares privately. The foreign keys of owner_id cascade, so a private
calendar, address book, table or knowledge page used to go with its owner, with everything the others had written into it.

Before the account goes (accounts/users.py _user_purge) every such object passes to the longest-standing person who may
write it: the oldest edit / write share, a share of a folder it is filed in counting like one of its own (a group's share
for each of its members). Never an agent, a child account or a disabled account, nor anybody outside the organisation of an
address book that lies in an organisation's workspace. A table attached to a project that outlives the account falls back
to the project's owner. Without such a person the object goes with the account as before, and the delete dialog says so.

What moves stays private to the new owner. Who could reach it through a folder of the deleted person keeps the role as a
share of the object (the folder itself goes). Knowledge pages move out of the one private space of their owner, so only the
pages somebody may write move, into the heir's space (a taken name gets " (2)"); their read-only shares and public links end,
as on every move of a page (wiki/wkshare.py). A space with the lock cannot move: the server cannot read it.

2.537.0 (#4347): shared branches of the private file store too. A folder or file of the private tree shared with a person
or a group (the topmost such node of a branch; one below it only when nobody above may take it) goes the same way: to the
longest-standing person with an edit share of it or of a folder above it, into the top level of their own tree, with
everything below it -- the contributions of others included (they were the deleted person's nodes) -- every version, the
document data and the recognised text sealed again for the heir's account. The shares of others on the branch and inside
it stay; one of a folder above that goes becomes a share of the branch; the heir's own share rows end (the owner needs
none). What stays behind and goes with the account: locked folders (the server cannot re-wrap their keys), links, agent
folders and the trash. Recognised documents go along (review #4347: what the retention keeps, orgretain.upg_personal took
out of the tree before). A group's share of a folder above becomes the group's share of the branch (never one per member);
an expired row of somebody who keeps a role is replaced. External links and the file requests of others on the branch end
(another owner's workspace, as files/fsmove.py fsm_apply). A file that cannot be sealed again (its key does not open it, a
disk error) stays the deleted person's and goes; the dialog cannot foresee that and counted it as handed on. A branch that
lies in a locked folder, or nobody to take it, goes with the account as before, and the dialog counts it so.

ush_plan is the one place that decides: the dialog counts what the deletion then does. No routes."""
import os

from ..collab.comments import user_names
from ..contacts.ctfolder import CTF_BOOK, ctf_dropped
from ..contacts.model import book_touch
from ..contacts.orgbooks import obk_hand_on
from ..core.access import Denied, list_role
from ..core.objhooks import OBJ  # 2.566.0 (#4712): the kinds whose reference node is the object's own (counted as itself)
from ..core.db import iso, iso_ms, now_utc
from ..core.i18n import tr
from ..core.pg import insert_id, system_ctx
from ..core.orgcrypt import OrgCryptError
from ..files.extlinks import xl_space_moved
from ..files.fslock import fsl_of, fsl_of_chain
from ..files.fsmove import fsm_doc, fsm_text, fsm_versions, fsm_walk
from ..files.fstags import dt_move
from ..files.fsref import fs_ref_node
from ..files.store import _free_name, _now, fs_chain, fs_deleted, fs_space, fs_subtree
from ..sheets.core import sh_touch
from ..sheets.shbook import shb_move
from ..sheets.shfolder import SHF_KIND, shf_after_move
from ..sheets.shkinds import shk_move_files
from ..sheets.shshare import shs_core_move, shs_drop_cache
from ..wiki.wikie2e import wke_mode
from ..wiki.wkfolder import WKF_KIND, WKF_SEEN, wkf_node_of, wkf_sync
from ..wiki.wkhist import wkh_drop_unreadable, wsb_body_or
from ..wiki.wkmove import wkm_place
from ..wiki.wkshare import wsh_covers, wsh_rows


def _accounts(c, ids):
    """{id: row} of the accounts ids (kind, kid, disabled, agent: a row in agents)."""
    ids = sorted({int(i) for i in ids if i})
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: r for r in c.execute(f"""SELECT u.id, u.kind, u.kid, u.disabled, EXISTS (SELECT 1 FROM agents a WHERE a.user_id=u.id) AS agent
                                              FROM users u WHERE u.id IN ({q})""", ids).fetchall()}


def _person(r):
    return r is not None and not r["disabled"] and not r["agent"] and (r["kind"] or "user") != "agent"


def _org_ok(c, oid, u):
    return not oid or c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=? AND role IN ('admin', 'member')", (oid, u)).fetchone() is not None


def _folder_shares(c, uid, ref_kind, rid):
    """[(since, person, role)] of the live shares of the folders object rid is filed in, in uid's own tree (a group: each of
    its members). Nothing while the node lies in the trash."""
    n = fs_ref_node(c, ref_kind, rid)
    if n is None or n["org_id"] or n["owner_id"] != uid:
        return []
    chain = fs_chain(c, n["id"])
    if not chain or fs_deleted(chain):
        return []
    return _node_shares(c, [x["id"] for x in chain])


def _item(c, uid, oid, rid, direct, folder, write, fallback=None, fits=None):
    """What happens to one object: {id, heir, others: {person: role through a folder}, shared: anybody else had it}; None when
    no other person has it (and no fallback takes it). fits(person): may this one hold it at all."""
    rows = sorted(list(direct) + list(folder), key=lambda x: (x[0] or "", x[1]))
    who = _accounts(c, [x[1] for x in rows] + [fallback])
    people = [x for x in rows if x[1] != uid and _person(who.get(x[1]))]
    can = lambda u: not who[u]["kid"] and _org_ok(c, oid, u) and (fits is None or fits(u))  # noqa: E731
    heir = next((u for _, u, role in people if role in (write, "edit") and can(u)), None)
    if heir is None and fallback and fallback != uid and _person(who.get(fallback)) and can(fallback):
        heir = fallback
    if heir is None and not people:
        return None
    others = {}
    for _, u, role in folder:
        if u != uid and u != heir and _person(who.get(u)) and _org_ok(c, oid, u) and role in ("view", "edit"):
            others[u] = "edit" if role == "edit" or others.get(u) == "edit" else "view"
    return {"id": rid, "heir": heir, "others": others, "shared": bool(people)}


def _node_shares(c, ids):
    """[(since, person, role)] of the live shares of nodes ids with people (a group: each of its members)."""
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [tuple(r) for r in c.execute(f"""SELECT s.created_at, COALESCE(s.user_id, m.user_id), s.role FROM fs_shares s
                                            LEFT JOIN group_members m ON m.group_id=s.group_id
                                            WHERE s.node_id IN ({q}) AND COALESCE(s.user_id, m.user_id) IS NOT NULL
                                            AND (s.expires_at IS NULL OR s.expires_at>?)""", (*ids, iso(now_utc()))).fetchall()]


def _above_rows(c, ids):
    """({person: role}, {group: role}) of the live share rows of nodes ids with a person or a group (edit wins)."""
    direct, groups = {}, {}
    if ids:
        q = ",".join("?" * len(ids))
        for u, g, role in c.execute(f"""SELECT user_id, group_id, role FROM fs_shares WHERE node_id IN ({q})
                                        AND COALESCE(user_id, group_id) IS NOT NULL AND (expires_at IS NULL OR expires_at>?)""",
                                    (*ids, iso(now_utc()))).fetchall():
            d, k = (direct, u) if u else (groups, g)
            if role in ("view", "edit"):
                d[k] = "edit" if role == "edit" or d.get(k) == "edit" else "view"
    return direct, groups


def _fs_branches(c, uid):
    """(items (_item, heir set), n gone) of the folders and files of uid's private tree shared with a person or a group,
    outside the areas (a table, page or address book in a shared folder counts as itself above). 2.537.0 (#4347): top
    down; a node inside a branch that is handed on goes along with it; the others go with the account (counted)."""
    roots = {r[0] for r in c.execute("SELECT node_id FROM fs_area_roots WHERE node_id IS NOT NULL")}
    found = []
    # 2.566.0 (#4712): the reference node of a calendar / address book on the shared core carries its shares: it counts as the
    # calendar / book above, never as a shared branch of the file store
    own = sorted(k for k, r in OBJ.items() if r.get("members"))
    skip = f" AND NOT (n.kind='ref' AND n.ref_kind IN ({','.join('?' * len(own))}))" if own else ""
    for (nid,) in c.execute("""SELECT DISTINCT n.id FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id WHERE n.owner_id=? AND n.org_id IS NULL
                               AND COALESCE(s.user_id, s.group_id) IS NOT NULL AND (s.expires_at IS NULL OR s.expires_at>?)
                               AND NOT (n.kind='ref' AND n.ref_kind='sheet')""" + skip,  # 2.565.0 (#4717): a table's own node carries its shares: the table counts above
                            (uid, iso(now_utc()), *own)).fetchall():
        chain = fs_chain(c, nid)
        if chain and not fs_deleted(chain) and not ({x["id"] for x in chain} & roots):
            found.append(chain)
    found.sort(key=lambda ch: (len(ch), ch[0]["id"]))
    items, taken, gone = [], set(), 0
    for chain in found:
        nid = chain[0]["id"]
        if any(x["id"] in taken for x in chain[1:]):
            continue  # it goes along with the branch above
        # only the person's own tree (never a node of theirs in somebody else's folder), nothing locked
        mine = all(x["owner_id"] == uid and not x["org_id"] for x in chain)
        it = None
        if mine and fsl_of_chain(c, chain) is None:
            above = [x["id"] for x in chain[1:]]
            it = _item(c, uid, None, nid, _node_shares(c, [nid]), _node_shares(c, above), "edit")
            if it:  # review #4347: a group's share above stays the group's (a member who leaves it loses it), no row per member
                direct, groups = _above_rows(c, above)
                it["others"] = {u: direct[u] for u in it["others"] if u in direct}
                it["groups"] = groups
        if it and it["heir"]:
            items.append(it)
            taken.add(nid)
        else:
            gone += 1
    return items, gone


def ush_plan(c, uid):
    """{calendars, books, sheets, wiki: [item (_item)]} of account uid. Numbers and ids only (the caller may be an instance
    admin outside it all)."""
    uid = int(uid)
    out = {"calendars": [], "books": [], "sheets": [], "wiki": [], "folders": []}
    with system_ctx(c):  # the deleted person's objects, whoever deletes the account
        for (cid,) in c.execute("SELECT id FROM ev_cals WHERE owner_id=? AND org_id IS NULL", (uid,)).fetchall():
            direct = c.execute("SELECT added_at, user_id, role FROM ev_cal_members WHERE cal_id=?", (cid,)).fetchall()
            out["calendars"].append(_item(c, uid, None, cid, [tuple(x) for x in direct], [], "edit"))
        for bid, oid in c.execute("SELECT id, org_id FROM books WHERE owner_id=? AND owner_org_id IS NULL AND deleted_at IS NULL", (uid,)).fetchall():
            direct = c.execute("SELECT added_at, user_id, role FROM book_members WHERE book_id=?", (bid,)).fetchall()
            out["books"].append(_item(c, uid, oid, bid, [tuple(x) for x in direct], _folder_shares(c, uid, CTF_BOOK, bid), "edit"))
        for sid, lid in c.execute("SELECT id, list_id FROM sheets WHERE owner_id=? AND org_id IS NULL AND book_id IS NULL AND deleted_at IS NULL", (uid,)).fetchall():
            direct = c.execute("SELECT created_at, user_id, role FROM sheet_shares WHERE sheet_id=? AND user_id IS NOT NULL AND revoked_at IS NULL", (sid,)).fetchall()
            lr = c.execute("SELECT owner_id FROM lists WHERE id=? AND org_id IS NULL", (lid,)).fetchone() if lid else None
            out["sheets"].append(_item(c, uid, None, sid, [tuple(x) for x in direct], _folder_shares(c, uid, SHF_KIND, sid), "write", lr[0] if lr else None))
        if not wke_mode(c, None, uid)[0]:
            shares = [r for r in wsh_rows(c, None, uid) if r["kind"] == "person" and r["user_id"]]
            for p in c.execute("SELECT id, path FROM wiki_pages WHERE owner_id=? AND org_id IS NULL AND deleted_at IS NULL", (uid,)).fetchall():
                read = [(r["created_at"], r["user_id"], "view") for r in shares if wsh_covers(r, p["path"], p["id"])]
                out["wiki"].append(_item(c, uid, None, p["id"], read, _folder_shares(c, uid, WKF_KIND, p["id"]), "edit",
                                         fits=lambda u: not wke_mode(c, None, u)[0]))  # review: never into a space with the lock (the text would lie open there)
        out["folders"] = _fs_branches(c, uid)[0]  # 2.537.0 (#4347)
    return {k: [x for x in v if x] for k, v in out.items()}


def ush_info(c, uid):
    """For the delete dialog (orgretain.upg_info): {to: {kind: n}, gone: {kind: n}, names: [who takes them over]}."""
    plan = ush_plan(c, uid)
    to = {k: sum(1 for x in v if x["heir"]) for k, v in plan.items()}
    gone = {k: sum(1 for x in v if not x["heir"]) for k, v in plan.items()}
    with system_ctx(c):  # numbers only
        gone["folders"] = _fs_branches(c, int(uid))[1]  # 2.537.0 (#4347): only the branches nobody takes over
        heirs = sorted({x["heir"] for v in plan.values() for x in v if x["heir"]})
        names = user_names(c, heirs)
    return {"to": {k: n for k, n in to.items() if n}, "gone": {k: n for k, n in gone.items() if n},
            "names": [names.get(h, "") for h in heirs if names.get(h)]}


def _calendars(c, items):
    for x in items:
        srt = (c.execute("SELECT MAX(sort) FROM ev_cals WHERE owner_id=?", (x["heir"],)).fetchone()[0] or 0) + 1  # its first calendar stays its default
        c.execute("DELETE FROM ev_cal_members WHERE cal_id=? AND user_id=?", (x["id"], x["heir"]))
        c.execute("UPDATE ev_cals SET owner_id=?, sort=?, changed_at=? WHERE id=?", (x["heir"], srt, iso_ms(now_utc()), x["id"]))


def _books(c, items):
    for x in items:
        ctf_dropped(c, CTF_BOOK, x["id"])
        obk_hand_on(c, x["id"], x["heir"])
        for u, role in x["others"].items():
            c.execute("""INSERT INTO book_members(book_id,user_id,role,added_at) VALUES(?,?,?,?)
                         ON CONFLICT (book_id, user_id) DO NOTHING""", (x["id"], u, role, iso(now_utc())))
        book_touch(c, x["id"])


def _sheets(c, items, new_paths, old_paths):
    for x in items:
        sid, heir = x["id"], x["heir"]
        lid = c.execute("SELECT list_id FROM sheets WHERE id=?", (sid,)).fetchone()[0]
        c.execute("DELETE FROM sheet_shares WHERE sheet_id=? AND user_id=?", (sid, heir))
        c.execute("UPDATE sheets SET owner_id=?, list_id=? WHERE id=?", (heir, lid if lid and list_role(c, lid, heir) else None, sid))
        shf_after_move(c, sid)
        shk_move_files(c, sid, None, heir, new_paths, old_paths, strict=False)  # 2.528.0 (#4306 B25): a broken file never stops the deletion
        shb_move(c, sid, None, heir, new_paths, old_paths, strict=False)
        for u, role in x["others"].items():
            c.execute("""INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at) VALUES(?,NULL,?,?,?,?)
                         ON CONFLICT (sheet_id, user_id) DO UPDATE SET role=excluded.role, revoked_at=NULL WHERE sheet_shares.revoked_at IS NOT NULL""",
                      (sid, u, "write" if role == "edit" else "read", heir, iso_ms(now_utc())))
        # 2.565.0 (#4717): the shares are core shares on the table's node -- the old node went with the move above, so every live
        # row gets its core share anew in the heir's tree (shshare.py shs_core_move)
        c.execute("UPDATE sheet_shares SET core_id=NULL WHERE sheet_id=? AND revoked_at IS NULL", (sid,))
        shs_core_move(c, sid)
        sh_touch(c, sid, heir)
    shs_drop_cache()


def _wiki(c, uid, items, new_paths, old_paths):
    by_heir = {}
    for x in items:
        by_heir.setdefault(x["heir"], []).append(x)
    for heir, group in by_heir.items():
        rows, others = [], {}
        for x in group:
            r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (x["id"],)).fetchone()
            if wsb_body_or(c, r, None) is None:  # a text that cannot be opened (its key is gone) goes with the account
                continue
            rows.append(r)
            others[x["id"]] = x["others"]
        if not rows:
            continue
        wkh_drop_unreadable(c, [r["id"] for r in rows])
        wkm_place(c, None, uid, heir, rows, new_paths, old_paths, strict=False)  # 2.528.0 (#4306 B25)
        WKF_SEEN.pop(f"u{int(heir)}", None)  # a deletion tried before and rolled back left this very state noted, without its nodes
        wkf_sync(c, heir, None)
        for pid, who in others.items():
            n = wkf_node_of(c, pid)
            for u, role in who.items() if n is not None else ():
                insert_id(c, "INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (n["id"], u, role, heir, iso(now_utc())))


def _folders(c, uid, items, new_paths, old_paths):
    """2.537.0 (#4347): each branch of items (_fs_branches) into the top level of its heir's own tree; what is the deleted
    person's in it passes to the heir, its files sealed again for the heir's account (as files/fsmove.py fsm_apply does)."""
    for x in items:
        nid, heir = x["id"], x["heir"]
        root = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        if root is None or root["owner_id"] != uid or root["org_id"]:
            continue
        sub = fs_subtree(c, nid)
        q = ",".join("?" * len(sub))
        # review #4347: recognised documents go along (the retention took what it keeps out of the tree before, upg_personal)
        stays = {i for i in sub if i != nid and fsl_of(c, i) is not None}  # a locked folder and what lies in it
        moved, _stay = fsm_walk(c, root, only=set(sub) - stays)
        ids = sorted(r["id"] for r in moved)  # review #4347: in node order, as fs_purge (#3090), no deadlock with the recognition
        for i in range(0, len(ids), 500):  # as fsm_apply: no recognition starts on the moved files until the commit
            part = ids[i:i + 500]
            pq = ",".join("?" * len(part))
            if any(r[0] == "run" for r in c.execute(f"SELECT state FROM doc_meta WHERE node_id IN ({pq}) ORDER BY node_id FOR UPDATE", part).fetchall() +
                   c.execute(f"SELECT state FROM file_text WHERE kind='fs' AND node_id IN ({pq}) ORDER BY node_id FOR UPDATE", part).fetchall()):
                raise Denied(409, tr("A file is being recognised right now. Please try again in a moment."))
        ts, root_ok, done = _now(), False, []
        for r in moved:  # root first
            if r["owner_id"] != uid:
                continue  # somebody else's node in the branch (sealed for that account) stays theirs
            k, j = len(new_paths), len(old_paths)
            try:
                with c.savepoint():
                    if r["id"] == nid:
                        c.execute("UPDATE fs_nodes SET parent_id=NULL, name=?, owner_id=?, updated_at=? WHERE id=?",
                                  (_free_name(c, None, heir, None, root["name"], skip=nid), heir, ts, nid))
                    else:
                        c.execute("UPDATE fs_nodes SET owner_id=?, updated_at=? WHERE id=?", (heir, ts, r["id"]))
                    dt_move(c, r["id"], f"u{int(heir)}")  # tags by name into the heir's own
                    if r["kind"] == "file":  # review #4347: checked as the heir (lists, agents of the deleted person go)
                        fsm_doc(c, r["id"], None, heir, heir, r["name"], new_paths, old_paths, df_define=True)
                        fsm_versions(c, r["id"], fs_space(None, heir), new_paths, old_paths)
                        fsm_text(c, r["id"], None, heir)
            except (Denied, OSError, OrgCryptError) as e:  # a file that cannot be sealed again: it stays the deleted person's and goes (never stops the deletion)
                if isinstance(e, Denied) and e.code != 409 or r["id"] == nid and r["kind"] == "folder":
                    raise
                for f in new_paths[k:]:
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                del new_paths[k:], old_paths[j:]
                print(f"account deletion: file {int(r['id'])} cannot be sealed again for the heir, it goes with the account (#4347): "
                      f"{type(e).__name__}", flush=True)
                continue
            done.append(r["id"])
            root_ok = root_ok or r["id"] == nid
        if not root_ok:
            continue
        stamp = iso(now_utc())
        for i in range(0, len(done), 500):
            part = done[i:i + 500]
            pq = ",".join("?" * len(part))
            c.execute(f"DELETE FROM fs_shares WHERE user_id=? AND node_id IN ({pq})", (heir, *part))  # the owner needs none
            # review #4347: into another owner's workspace, as fsm_apply: external links end, so do the file requests of others
            c.execute(f"""UPDATE fs_upload_requests SET revoked_at=? WHERE node_id IN ({pq}) AND created_by<>?
                          AND revoked_at IS NULL AND deleted_at IS NULL""", (stamp, *part, heir))
        xl_space_moved(c, done)
        live = "(expires_at IS NULL OR expires_at>?)"
        for col, want in (("user_id", x["others"]), ("group_id", x.get("groups") or {})):
            if not want:
                continue
            # review #4347: an expired row of one who keeps a role is replaced (not raised and left expired)
            c.execute(f"DELETE FROM fs_shares WHERE node_id=? AND {col} IN ({','.join('?' * len(want))}) AND NOT {live}", (nid, *want, stamp))
            have = {r[0]: r[1] for r in c.execute(f"SELECT {col}, role FROM fs_shares WHERE node_id=? AND {col} IS NOT NULL AND {live}", (nid, stamp))}
            for k, role in want.items():  # who reached it through a folder above that goes keeps the role on the branch
                if k not in have:
                    insert_id(c, f"INSERT INTO fs_shares(node_id,{col},role,created_by,created_at) VALUES(?,?,?,?,?)", (nid, k, role, heir, stamp))
                elif role == "edit" and have[k] != "edit":
                    c.execute(f"UPDATE fs_shares SET role='edit' WHERE node_id=? AND {col}=? AND {live}", (nid, k, stamp))


def ush_hand_on(c, uid, new_paths):
    """The deletion of account uid (users._user_purge, after the lists are settled, before its file store and its key go):
    everything of ush_plan with a heir passes to it. -> the stored files to remove after the commit. new_paths: the sealed
    copies made here are added, for the caller to remove if the deletion fails later on. The caller commits."""
    uid = int(uid)
    plan = {k: [x for x in v if x["heir"]] for k, v in ush_plan(c, uid).items()}
    old_paths = []
    with system_ctx(c):  # the rows of both people, whoever deletes the account
        _calendars(c, plan["calendars"])
        _books(c, plan["books"])
        _sheets(c, plan["sheets"], new_paths, old_paths)
        _wiki(c, uid, plan["wiki"], new_paths, old_paths)
        _folders(c, uid, plan["folders"], new_paths, old_paths)  # 2.537.0 (#4347): after the areas (their filed nodes went already)
    n = sum(len(v) for v in plan.values())
    if n:
        print(f"account deletion: {n} shared object(s) handed on (#4301)", flush=True)
    return old_paths
