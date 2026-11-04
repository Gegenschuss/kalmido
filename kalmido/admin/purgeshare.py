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

Shared folders of the file store stay out for now (#4347): the dialog names them among what goes.

ush_plan is the one place that decides: the dialog counts what the deletion then does. No routes."""
from ..collab.comments import user_names
from ..contacts.ctfolder import CTF_BOOK, ctf_dropped
from ..contacts.model import book_touch
from ..contacts.orgbooks import obk_hand_on
from ..core.access import list_role
from ..core.db import iso, iso_ms, now_utc
from ..core.pg import insert_id, system_ctx
from ..files.fsref import fs_ref_node
from ..files.store import fs_chain, fs_deleted
from ..sheets.core import sh_touch
from ..sheets.shbook import shb_move
from ..sheets.shfolder import SHF_KIND, shf_after_move
from ..sheets.shkinds import shk_move_files
from ..sheets.shshare import shs_drop_cache
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
    q = ",".join("?" * len(chain))
    return [tuple(r) for r in c.execute(f"""SELECT s.created_at, COALESCE(s.user_id, m.user_id), s.role FROM fs_shares s
                                            LEFT JOIN group_members m ON m.group_id=s.group_id
                                            WHERE s.node_id IN ({q}) AND COALESCE(s.user_id, m.user_id) IS NOT NULL
                                            AND (s.expires_at IS NULL OR s.expires_at>?)""",
                                        (*[x["id"] for x in chain], iso(now_utc()))).fetchall()]


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


def _gone_folders(c, uid):
    """Folders and files of uid's private tree shared with a person or a group, outside the areas (a table, page or address
    book in a shared folder counts as itself above): they go with the account (#4347)."""
    roots = {r[0] for r in c.execute("SELECT node_id FROM fs_area_roots WHERE node_id IS NOT NULL")}
    n = 0
    for (nid,) in c.execute("""SELECT DISTINCT n.id FROM fs_nodes n JOIN fs_shares s ON s.node_id=n.id WHERE n.owner_id=? AND n.org_id IS NULL
                               AND COALESCE(s.user_id, s.group_id) IS NOT NULL AND (s.expires_at IS NULL OR s.expires_at>?)""",
                            (uid, iso(now_utc()))).fetchall():
        chain = fs_chain(c, nid)
        if chain and not fs_deleted(chain) and not ({x["id"] for x in chain} & roots):
            n += 1
    return n


def ush_plan(c, uid):
    """{calendars, books, sheets, wiki: [item (_item)]} of account uid. Numbers and ids only (the caller may be an instance
    admin outside it all)."""
    uid = int(uid)
    out = {"calendars": [], "books": [], "sheets": [], "wiki": []}
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
    return {k: [x for x in v if x] for k, v in out.items()}


def ush_info(c, uid):
    """For the delete dialog (orgretain.upg_info): {to: {kind: n}, gone: {kind: n}, names: [who takes them over]}."""
    plan = ush_plan(c, uid)
    to = {k: sum(1 for x in v if x["heir"]) for k, v in plan.items()}
    gone = {k: sum(1 for x in v if not x["heir"]) for k, v in plan.items()}
    with system_ctx(c):  # numbers only
        gone["folders"] = _gone_folders(c, int(uid))
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
        shk_move_files(c, sid, None, heir, new_paths, old_paths)
        shb_move(c, sid, None, heir, new_paths, old_paths)
        for u, role in x["others"].items():
            c.execute("""INSERT INTO sheet_shares(sheet_id,org_id,user_id,role,created_by,created_at) VALUES(?,NULL,?,?,?,?)
                         ON CONFLICT (sheet_id, user_id) DO UPDATE SET role=excluded.role, revoked_at=NULL WHERE sheet_shares.revoked_at IS NOT NULL""",
                      (sid, u, "write" if role == "edit" else "read", heir, iso_ms(now_utc())))
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
        wkm_place(c, None, uid, heir, rows, new_paths, old_paths)
        WKF_SEEN.pop(f"u{int(heir)}", None)  # a deletion tried before and rolled back left this very state noted, without its nodes
        wkf_sync(c, heir, None)
        for pid, who in others.items():
            n = wkf_node_of(c, pid)
            for u, role in who.items() if n is not None else ():
                insert_id(c, "INSERT INTO fs_shares(node_id,user_id,role,created_by,created_at) VALUES(?,?,?,?,?)", (n["id"], u, role, heir, iso(now_utc())))


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
    n = sum(len(v) for v in plan.values())
    if n:
        print(f"account deletion: {n} shared object(s) handed on (#4301)", flush=True)
    return old_paths
